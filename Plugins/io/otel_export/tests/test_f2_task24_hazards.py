# -*- coding: utf-8 -*-
"""Опасности асинхронной очереди на стороне плагина (Task 2.4, правки по ревью).

Здесь сторожится **своевременность** числа потерь, а не его наличие. Разница
куплена находкой ревью 2026-09-08 и предъявлена числом: синхронизация счётчика
жила только в `otel_export.status` и на останове, поэтому при **1488** реально
вытесненных записях `ctx.record_metric` не звали **ни разу** — до тех пор, пока
кто-нибудь не спросит статус. Метка времени у метрики оказывалась моментом
ОПРОСА, а не моментом потери.

Почему этого не видел ни один существующий тест: все они читают
`dropped_overflow` **через `status()`**, а `status()` сам себя чинит — зовёт
синхронизацию перед ответом. То есть сторожилась дорога опроса, а не свойство.
Здесь статус НЕ опрашивается принципиально.
"""

from __future__ import annotations

from typing import Any

import pytest

from Plugins.io.otel_export.tests.test_f2_task24_acceptance import (
    _boot_blocked_with_pilot,
    _call_with_deadline,
    _log_record,
)

#: Потолок числа записей, после которого проба сдаётся. НЕ «сколько нужно для
#: переполнения»: фиксированное число здесь — догадка о темпе, и она уже подвела.
#: Прогон ревью показал флейк ~15 % на литерале 3000 (`q_dropped=0` при
#: `depth=1751 < cap=2048`): сколько записей осядет в канале, а сколько уедет в
#: полёт к заблокированному стоку, решает планировщик. Поэтому кормим ДО
#: наблюдаемого переполнения, а число ниже — только страховка от вечного цикла.
_FEED_CEILING = 40000
#: Размер порции между проверками. Мельче — дороже проверки, крупнее — грубее
#: момент остановки; на исход утверждения не влияет ни то, ни другое.
_FEED_CHUNK = 500


class TestLossIsPublishedWhenItHappensNotWhenItIsAsked:
    """Потеря обязана попадать в плоскости В МОМЕНТ потери.

    Как это правдоподобно ломается — и сломалось: синхронизацию счётчика ставят
    в обработчик команды `status`, потому что там она нужна для ответа, и на этом
    успокаиваются. Механизм при этом «работает»: спроси — и число верное. Не
    работает наблюдаемость: между потерей и опросом число равно нулю, а `history_query`
    привяжет потерю ко времени опроса.
    """

    def _dropped_metrics(self, recorded: list[tuple[str, Any]]) -> list[tuple[str, Any]]:
        return [item for item in recorded if item[0].endswith("dropped_overflow")]

    def test_overflow_reaches_the_number_plane_without_anyone_calling_status(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        boot = _boot_blocked_with_pilot(monkeypatch)
        try:
            assert not self._dropped_metrics(boot.recorded), (
                "метрика потерь уже есть ДО переполнения — сценарий не воспроизведён"
            )

            written = 0

            def _feed() -> None:
                nonlocal written
                # Кормим ДО наблюдаемого переполнения, а не фиксированным числом:
                # сток заблокирован, ёмкость конечна, значит переполнение
                # неизбежно — вопрос лишь в том, сколько записей планировщик
                # успеет отдать в полёт. Условие выхода — сам предмет проверки.
                while written < _FEED_CEILING and not self._dropped_metrics(boot.recorded):
                    for i in range(_FEED_CHUNK):
                        boot.handler(
                            {
                                "command": "observability.record",
                                "data": {"records": [_log_record(f"m{written + i}", float(i))]},
                            }
                        )
                    written += _FEED_CHUNK

            _call_with_deadline(_feed, timeout=30.0, message="приём записей до переполнения при висящем стоке")

            # Статус НЕ опрашивается: в этом всё утверждение.
            published = self._dropped_metrics(boot.recorded)
            assert published, (
                f"{written} записей при заблокированном стоке переполнили очередь, но в числовой "
                "плоскости потери НЕТ, пока никто не спросил статус: число, заведённое ради "
                "видимости потерь, откладывает их до момента опроса"
            )
            total = sum(int(value) for _name, value in published)
            assert total > 0, f"метрика потерь опубликована с нулём: {published!r}"
        finally:
            boot.release.set()
            boot.plugin.shutdown(boot.ctx)

    def test_pair_no_overflow_publishes_nothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Пара достижимости: без переполнения метрики потерь быть не должно.

        Без неё «метрика появилась» неотличимо от «метрика публикуется всегда» —
        и утверждение выше прошло бы на реализации, которая шлёт ноль на каждую
        принятую запись.
        """
        boot = _boot_blocked_with_pilot(monkeypatch)
        try:

            def _feed() -> None:
                for i in range(10):
                    boot.handler(
                        {"command": "observability.record", "data": {"records": [_log_record(f"m{i}", float(i))]}}
                    )

            _call_with_deadline(_feed, timeout=10.0, message="приём 10 записей")

            assert not self._dropped_metrics(boot.recorded), (
                f"десять записей в очередь с потолком не меньше 1024 не могут дать потерь: "
                f"{self._dropped_metrics(boot.recorded)!r}"
            )
        finally:
            boot.release.set()
            boot.plugin.shutdown(boot.ctx)


class TestSyncDoesNotRunOnEveryRecordAfterOneOverflow:
    """Синхронизация зовётся на НОВОЙ потере, а не «после первой — всегда».

    **Находка второго прохода ревью, и она про мою же починку.** Первая редакция
    триггера читала `write()["dropped"]` как «вытеснила ли эта запись», а
    `BoundedChannel.write` возвращает **накопленный** счётчик
    (`bounded_channel.py:85,99`). Условие «поле ненулевое» после первого же
    переполнения истинно навсегда, и приёмный путь платил `get_info()` плюс
    захват лока на КАЖДОЙ записи при нуле новых потерь. Замер ревью: 2000
    вызовов синхронизации на 0 вытеснений.

    Сторожа не было: заплата «вернуть триггер на накопленное» убивала **0 тестов
    из 248**. Ноль означал не «слой лишний», а «мы не туда целились» — работа
    мёртвая, а не наблюдаемая через счётчики. Здесь она наблюдается прямо:
    считаются вызовы синхронизации после того, как очередь опустела.
    """

    def test_after_the_queue_drains_further_writes_do_not_resync(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import time

        boot = _boot_blocked_with_pilot(monkeypatch)
        try:
            written = 0

            def _feed() -> None:
                nonlocal written
                while written < _FEED_CEILING and not boot.plugin._queue.get_info().get("dropped", 0):
                    for i in range(_FEED_CHUNK):
                        boot.handler(
                            {
                                "command": "observability.record",
                                "data": {"records": [_log_record(f"m{written + i}", float(i))]},
                            }
                        )
                    written += _FEED_CHUNK

            _call_with_deadline(_feed, timeout=30.0, message="приём записей до переполнения")
            assert boot.plugin._queue.get_info().get("dropped", 0) > 0, (
                "переполнения не случилось — сценарий не воспроизведён, сторожить нечего"
            )

            # Отпускаем сток и ждём, пока очередь ОПУСТЕЕТ: только после этого
            # новые записи заведомо никого не вытесняют.
            boot.release.set()
            deadline = time.monotonic() + 15.0
            while boot.plugin._queue.depth > 0 and time.monotonic() < deadline:
                time.sleep(0.05)
            assert boot.plugin._queue.depth == 0, (
                f"очередь не опустела за 15 с (глубина {boot.plugin._queue.depth}) — "
                "измерение не состоялось, о предмете не судим"
            )

            calls: list[int] = []
            original = boot.plugin._sync_queue_counters
            monkeypatch.setattr(boot.plugin, "_sync_queue_counters", lambda: (calls.append(1), original())[1])

            def _feed_more() -> None:
                for i in range(200):
                    boot.handler(
                        {"command": "observability.record", "data": {"records": [_log_record(f"tail{i}", float(i))]}}
                    )

            _call_with_deadline(_feed_more, timeout=15.0, message="приём 200 записей на пустой очереди")

            assert not calls, (
                f"на 200 записях БЕЗ новых вытеснений синхронизация звана {len(calls)} раз: "
                "триггер стоит на накопленном счётчике, и приёмный путь платит за неё вечно "
                "после первого же переполнения"
            )
        finally:
            boot.release.set()
            boot.plugin.shutdown(boot.ctx)
