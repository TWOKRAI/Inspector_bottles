# -*- coding: utf-8 -*-
"""Тесты Т.2 (критерий 2) — независимый тестер, ДО реализации.

Источник контракта: акцептанс-критерии задачи Т.2 плана observation-port.
``_setup_state_path``/``_setup_metric_threshold`` сегодня сравнивают путь
дельты с наблюдаемым путём БУКВАЛЬНО — удаление ПРЕДКА (``processes.gui``
целиком, пока ждём ``processes.gui.state.plugins.capture.capture_fps``)
проходит незамеченным, ожидание сидит до таймаута с пустым ``last_seen``.
После правки такая дельта обязана лечь в ``last_seen`` как диагноз
(«удалён предок X»), но НЕ как совпадение (``success`` остаётся ``False``).

Стиль и хелперы — по образцу ``test_await_condition.py`` (уже существующего
модуля B.2): producer-поток кормит ``dispatch_raw`` с паузой, пока клиентский
поток блокируется в ``await_condition``. Любой блокирующий вызов идёт через
``th.join(timeout=...)`` с проверкой, что поток действительно завершился —
не через голый ``.join()`` без дедлайна.
"""

from __future__ import annotations

import threading
import time
from typing import Any, List

from backend_ctl.driver import BackendDriver
from backend_ctl.events import MISSING_MARKER
from backend_ctl.tests.conftest import wire_line as _line

#: Дедлайн присоединения producer-потока — страховка от голого зависшего join()
#: (жёсткое правило задания: любой потенциально блокирующий вызов — с deadline).
JOIN_DEADLINE = 5.0

WATCHED = "processes.gui.state.plugins.capture.capture_fps"


def _state_line(path: str, value: Any) -> bytes:
    return _line({"command": "state.changed", "data": {"deltas": [{"path": path, "new_value": value}]}})


def _feed_later(d: BackendDriver, lines: List[bytes], delay: float = 0.05) -> threading.Thread:
    """Producer: подать дельты в dispatch_raw после паузы (клиент уже ждёт в await_condition)."""

    def run() -> None:
        time.sleep(delay)
        for raw in lines:
            d.dispatch_raw(raw)

    th = threading.Thread(target=run, daemon=True)
    th.start()
    return th


def _join_or_fail(th: threading.Thread) -> None:
    th.join(timeout=JOIN_DEADLINE)
    assert not th.is_alive(), "producer-поток не завершился в отведённый срок — тест завис бы без дедлайна"


class TestStatePathAncestorDeletion:
    """Критерий 2 (``_setup_state_path``)."""

    def test_exact_watched_path_deletion_still_times_out_pin(self) -> None:
        """Пин регресса: удаление ТОЧНОГО наблюдаемого пути — уже работает сегодня,
        менять это поведение задача не должна. success=False, диагноз про удаление
        того же пути, что наблюдали."""
        d = BackendDriver()
        th = _feed_later(d, [_state_line(WATCHED, MISSING_MARKER)])
        res = d.await_condition("state_path", {"path": WATCHED, "value": 30}, timeout=0.3)
        _join_or_fail(th)

        assert res["success"] is False
        assert res["timed_out"] is True
        assert res["last_seen"] is not None
        assert res["last_seen"]["path"] == WATCHED
        assert res["last_seen"].get("deleted") is True

    def test_ancestor_deletion_recorded_as_diagnosis_not_match(self) -> None:
        """Удаление ПРЕДКА (``processes.gui`` целиком) — новое поведение задачи.

        До правки: ждём ``WATCHED``, дельта по ``processes.gui`` не совпадает
        буквально с ``WATCHED`` → предикат её игнорирует → last_seen пуст,
        таймаут без диагноза. После правки last_seen обязан назвать удалённого
        предка, а совпадением это НЕ считается.
        """
        d = BackendDriver()
        th = _feed_later(d, [_state_line("processes.gui", MISSING_MARKER)])
        res = d.await_condition("state_path", {"path": WATCHED, "value": 30}, timeout=0.3)
        _join_or_fail(th)

        assert res["success"] is False, "удаление предка — диагноз, а не совпадение условия"
        assert res["timed_out"] is True
        last_seen = res["last_seen"]
        assert last_seen is not None, (
            "удаление предка обязано лечь в last_seen — сегодня ожидание слепо к нему, "
            "last_seen остаётся None и диагноз пуст"
        )
        assert "processes.gui" in str(last_seen), f"диагноз обязан НАЗВАТЬ удалённого предка: {last_seen}"
        assert last_seen.get("deleted") is True or "deleted" in str(last_seen), (
            f"диагноз обязан пометить это как удаление, а не как обычное значение: {last_seen}"
        )
        # Подсказка про недостающую подписку не должна выводиться поверх настоящего
        # диагноза — релевантное наблюдение БЫЛО.
        assert "hint" not in res, res

    def test_unrelated_path_deletion_is_not_recorded(self) -> None:
        """Контроль: удаление совсем другой ветки НЕ должно ложиться в last_seen."""
        d = BackendDriver()
        th = _feed_later(d, [_state_line("devices.plc", MISSING_MARKER)])
        res = d.await_condition("state_path", {"path": WATCHED, "value": 30}, timeout=0.3)
        _join_or_fail(th)

        assert res["success"] is False
        assert res["last_seen"] is None, (
            f"удаление НЕсвязанной ветки не должно порождать наблюдение: {res['last_seen']}"
        )
        assert "hint" in res  # ни одного релевантного наблюдения — подсказка о подписке жива

    def test_textual_prefix_without_full_segment_is_not_an_ancestor(self) -> None:
        """Ловушка ложного срабатывания: ``processes.gu`` — строковый префикс
        ``processes.gui.x``, но НЕ предок по сегментам пути («gu» ≠ «gui»
        целиком). Наивная проверка через ``str.startswith`` попалась бы сюда.
        """
        d = BackendDriver()
        watched = "processes.gui.x"
        th = _feed_later(d, [_state_line("processes.gu", MISSING_MARKER)])
        res = d.await_condition("state_path", {"path": watched, "value": 1}, timeout=0.3)
        _join_or_fail(th)

        assert res["success"] is False
        assert res["last_seen"] is None, (
            f"'processes.gu' — не предок 'processes.gui.x' по сегментам, ложный текстовый "
            f"префикс не должен приниматься за удаление предка: {res['last_seen']}"
        )


class TestMetricThresholdAncestorDeletion:
    """Критерий 2 (``_setup_metric_threshold``) — то же требование, вторая настройка."""

    def test_ancestor_deletion_recorded_as_diagnosis_not_match(self) -> None:
        d = BackendDriver()
        th = _feed_later(d, [_state_line("processes.gui", MISSING_MARKER)])
        res = d.await_condition("metric_threshold", {"path": WATCHED, "op": ">", "value": 10}, timeout=0.3)
        _join_or_fail(th)

        assert res["success"] is False, "удаление предка — диагноз, а не пересечение порога"
        assert res["timed_out"] is True
        last_seen = res["last_seen"]
        assert last_seen is not None, "удаление предка обязано лечь в last_seen у metric_threshold тоже"
        assert "processes.gui" in str(last_seen), f"диагноз обязан назвать удалённого предка: {last_seen}"
        assert last_seen.get("deleted") is True or "deleted" in str(last_seen), (
            f"диагноз обязан пометить это как удаление: {last_seen}"
        )

    def test_unrelated_path_deletion_is_not_recorded(self) -> None:
        d = BackendDriver()
        th = _feed_later(d, [_state_line("devices.plc", MISSING_MARKER)])
        res = d.await_condition("metric_threshold", {"path": WATCHED, "op": ">", "value": 10}, timeout=0.3)
        _join_or_fail(th)

        assert res["success"] is False
        assert res["last_seen"] is None, (
            f"удаление НЕсвязанной ветки не должно порождать наблюдение: {res['last_seen']}"
        )
