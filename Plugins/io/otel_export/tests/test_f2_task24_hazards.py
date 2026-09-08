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

#: Больше любого правдоподобного потолка: дефолт `BatchDrainWorker` 1024,
#: дефолт `OtelExportConfig.max_queue_size` 2048. Литерал, а не чтение конфига:
#: число, выведенное из предмета проверки, согласилось бы с любым потолком.
_OVERFLOWING = 3000


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

            def _feed() -> None:
                for i in range(_OVERFLOWING):
                    boot.handler(
                        {"command": "observability.record", "data": {"records": [_log_record(f"m{i}", float(i))]}}
                    )

            _call_with_deadline(_feed, timeout=10.0, message=f"приём {_OVERFLOWING} записей при висящем стоке")

            # Статус НЕ опрашивается: в этом всё утверждение.
            published = self._dropped_metrics(boot.recorded)
            assert published, (
                f"{_OVERFLOWING} записей переполнили очередь, но в числовой плоскости потери НЕТ, "
                "пока никто не спросил статус: число, заведённое ради видимости потерь, "
                "откладывает их до момента опроса"
            )
            total = sum(int(value) for _name, value in published)
            assert total > 0, f"метрика потерь опубликована с нулём: {published!r}"
        finally:
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
            boot.plugin.shutdown(boot.ctx)
