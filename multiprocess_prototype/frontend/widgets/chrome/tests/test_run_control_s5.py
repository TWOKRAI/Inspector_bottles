"""Слепые приёмочные тесты S5: пульт запуска — подпись «гейт выключен», ОСТАНОВИТЬ по stop_allowed,
один набор блокирующих степеней (фреймворка).

Пишутся по `plans/2026-10-27_system-run-state/tasks/S5.md` (REDS 1-9) без чтения реализации.
Все ожидаемые значения — литералы из спецификации, из кода не выводятся.
Модель — `build_view(snapshot, busy)` без Qt; виджет — `RunControlWidget` + собственный фейк команд.
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QLabel, QPushButton

from multiprocess_framework.modules.process_module.health import schema
from multiprocess_prototype.frontend.state.bindings import DELETED
from multiprocess_prototype.frontend.widgets.chrome.run_control import (
    RunControlWidget,
    RunView,
    build_view,
)

PREFIX = "system.run."

# Литерал подписи (REDS 1): текст и условие показа — за владельцем (Р1), смена — одна строка здесь.
GATE_TEXT = "Гейт выключен: кадры идут без ЗАПУСТИТЬ"


def R(sev: str, text: str, node: str) -> dict:  # noqa: N802 - имя из спецификации
    """Причина готовности: `R(sev, text, node)` из REDS."""
    return {"severity": sev, "reason": text, "node": node, "source": "s"}


class FakeCommands:
    """Четыре метода run_*_async; команды оператора — в `calls`, on_result затравки сохраняется и не зовётся."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.status_callbacks: list = []

    def run_start_async(self, on_result) -> None:
        self.calls.append("start")

    def run_stop_async(self, on_result) -> None:
        self.calls.append("stop")

    def run_ack_async(self, on_result) -> None:
        self.calls.append("ack")

    def run_status_async(self, on_result) -> None:
        self.status_callbacks.append(on_result)


def _make(qtbot, leaves: dict | None = None, *, with_commands: bool = True):
    """Виджет (+ фейк команд) + листья (ключ без префикса `system.run.`)."""
    fake = FakeCommands()
    w = RunControlWidget()
    qtbot.addWidget(w)
    if with_commands:
        w.set_commands(fake)
    for key, value in (leaves or {}).items():
        w.apply_leaf(PREFIX + key, value)
    return w, fake


def _btn(w, name: str) -> QPushButton:
    b = w.findChild(QPushButton, name)
    assert b is not None, f"нет кнопки {name}"
    return b


def _gate_label(w) -> QLabel:
    lb = w.findChild(QLabel, "RunGateLabel")
    assert lb is not None, "нет метки RunGateLabel"
    return lb


# ===========================================================================
# REDS 1: (б) подпись, модель
# ===========================================================================

_READY = {"state": "ready", "start_allowed": True}


def test_gate_text_shown_when_run_gate_false() -> None:
    """REDS 1: run_gate is False -> подпись-литерал; кнопки и имя состояния по флагам PM."""
    view = build_view({**_READY, "run_gate": False}, False)

    assert isinstance(view, RunView)
    assert view.gate_text == "Гейт выключен: кадры идут без ЗАПУСТИТЬ"
    assert view.start_enabled is True
    assert view.state_text == "Готов"


@pytest.mark.parametrize("gate", [True, None, 0, "false"], ids=["True", "None", "0", "str-false"])
def test_gate_text_empty_unless_exactly_false(gate) -> None:
    """REDS 1: подпись только при `run_gate is False`; True/None/0/"false" -> пусто."""
    view = build_view({**_READY, "run_gate": gate}, False)

    assert view.gate_text == ""


def test_gate_text_empty_without_run_gate_key() -> None:
    """REDS 1: старый бэкенд (нет ключа run_gate) -> подписи нет, кнопка по флагу как сегодня."""
    view = build_view(dict(_READY), False)

    assert view.gate_text == ""
    assert view.start_enabled is True


# ===========================================================================
# REDS 2: (б) подпись во всех состояниях и без данных
# ===========================================================================


def test_gate_text_with_running_keeps_stop_enabled() -> None:
    view = build_view({"state": "running", "stop_allowed": True, "run_gate": False}, False)

    assert view.gate_text == "Гейт выключен: кадры идут без ЗАПУСТИТЬ"
    assert view.stop_enabled is True


def test_gate_text_with_fault_keeps_ack_enabled() -> None:
    view = build_view({"state": "fault", "ack_allowed": True, "run_gate": False}, False)

    assert view.gate_text == "Гейт выключен: кадры идут без ЗАПУСТИТЬ"
    assert view.ack_enabled is True


def test_gate_text_with_not_ready_keeps_reason_detail() -> None:
    view = build_view(
        {
            "state": "not_ready",
            "start_allowed": False,
            "reasons": [R("failure", "нет диска", "disk")],
            "run_gate": False,
        },
        False,
    )

    assert view.gate_text == "Гейт выключен: кадры идут без ЗАПУСТИТЬ"
    assert view.detail_text == "нет диска"


def test_unknown_state_means_no_data_and_no_gate_text() -> None:
    """Состояние вне таблицы -> «Нет данных», подписи нет даже при run_gate: False."""
    view = build_view({"state": "bogus", "run_gate": False}, False)

    assert view.state_text == "Нет данных"
    assert view.gate_text == ""


# ===========================================================================
# REDS 3: (в) ОСТАНОВИТЬ по stop_allowed
# ===========================================================================


def test_stop_disabled_when_stop_allowed_false_in_running() -> None:
    assert build_view({"state": "running", "stop_allowed": False}, False).stop_enabled is False


def test_stop_enabled_when_stop_allowed_true_in_running() -> None:
    assert build_view({"state": "running", "stop_allowed": True}, False).stop_enabled is True


def test_stop_disabled_when_busy_even_if_allowed() -> None:
    assert build_view({"state": "running", "stop_allowed": True}, True).stop_enabled is False


def test_stop_falls_back_to_state_rule_without_key() -> None:
    """Старый бэкенд: нет ключа stop_allowed -> по состоянию (running -> активна)."""
    assert build_view({"state": "running"}, False).stop_enabled is True


@pytest.mark.parametrize("state", ["ready", "stopping"])
def test_stop_disabled_outside_running_even_if_allowed(state: str) -> None:
    """stop_allowed: True не включает ОСТАНОВИТЬ вне running."""
    assert build_view({"state": state, "stop_allowed": True}, False).stop_enabled is False


# ===========================================================================
# REDS 4: (в, Р2) негодный stop_allowed
# ===========================================================================


@pytest.mark.parametrize("value", [None, 0], ids=["None", "0"])
def test_stop_disabled_for_falsy_garbage_stop_allowed(value) -> None:
    """Р2 (умолчание — bool(значение)): None и 0 -> ОСТАНОВИТЬ неактивна."""
    assert build_view({"state": "running", "stop_allowed": value}, False).stop_enabled is False


@pytest.mark.parametrize("busy", [False, True])
@pytest.mark.parametrize("gate", ["x", [1], None], ids=["gate-str", "gate-list", "gate-None"])
@pytest.mark.parametrize("value", [None, "x", [1], {}], ids=["sa-None", "sa-str", "sa-list", "sa-dict"])
@pytest.mark.parametrize("state", ["running", "ready", "bogus"])
def test_garbage_stop_allowed_and_run_gate_never_raise(state, value, gate, busy) -> None:
    """Ввод любой формы не бросает: возвращается RunView (72 сочетания)."""
    view = build_view({"state": state, "stop_allowed": value, "run_gate": gate}, busy)

    assert isinstance(view, RunView)


# ===========================================================================
# REDS 5: (а) набор фреймворка без подмены, модель (контроль: зелёный и до правки)
# ===========================================================================


def _not_ready(reasons: list[dict]) -> RunView:
    return build_view({"state": "not_ready", "start_allowed": False, "reasons": reasons}, False)


@pytest.mark.parametrize("severity", ["failure", "check_function"])
def test_blocking_severity_gives_detail_and_tooltip(severity: str) -> None:
    view = _not_ready([R(severity, "X", "n")])

    assert view.detail_text == "X"
    assert view.start_tooltip == "n: X"


@pytest.mark.parametrize("severity", ["out_of_spec", "maintenance", "unknown"])
def test_non_blocking_severity_gives_no_detail_or_tooltip(severity: str) -> None:
    view = _not_ready([R(severity, "X", "n")])

    assert view.detail_text == ""
    assert view.start_tooltip == ""


def test_blocking_order_failure_first_then_check_function_in_list_order() -> None:
    view = _not_ready([R("check_function", "C", "n2"), R("failure", "F", "n1"), R("check_function", "D", "n3")])

    assert view.detail_text == "F"
    assert view.start_tooltip == "n1: F\nn2: C\nn3: D"


# ===========================================================================
# REDS 6: (а) набор читается на вызове из фреймворка (подмена атрибутов health.schema)
# ===========================================================================


def test_new_severity_from_framework_set_is_blocking_and_ordered(monkeypatch) -> None:
    """6а: фреймворк добавил степень halt между failure и check_function -> пульт её учитывает по порядку."""
    monkeypatch.setattr(
        schema, "READINESS_SEVERITIES", ("failure", "halt", "check_function", "out_of_spec", "maintenance")
    )
    monkeypatch.setattr(schema, "READINESS_BLOCKING_SEVERITIES", ("failure", "halt", "check_function"))

    view = _not_ready([R("check_function", "C", "n2"), R("halt", "H", "n1")])

    assert view.detail_text == "H"
    assert view.start_tooltip == "n1: H\nn2: C"


def test_blocking_set_alone_patched_unknown_severities_go_after_known(monkeypatch) -> None:
    """6б: READINESS_SEVERITIES не тронут, блокирующий набор расширен степенями вне шкалы ->
    известная (check_function) первой, затем остальные (alpha, zeta) по алфавиту."""
    monkeypatch.setattr(schema, "READINESS_BLOCKING_SEVERITIES", ("failure", "check_function", "zeta", "alpha"))

    view = _not_ready([R("zeta", "Z", "nz"), R("alpha", "A", "na"), R("check_function", "C", "nc")])

    assert view.detail_text == "C"
    assert view.start_tooltip == "nc: C\nna: A\nnz: Z"


# ===========================================================================
# REDS 7: (в) виджет
# ===========================================================================

_RUNNING_NO_START = {"state": "running", "start_allowed": False}


def test_widget_stop_inactive_when_stop_allowed_false(qtbot) -> None:
    w, _fake = _make(qtbot, {**_RUNNING_NO_START, "stop_allowed": False})

    assert not _btn(w, "RunStopButton").isEnabled()


def test_widget_stop_active_when_stop_allowed_leaf_true(qtbot) -> None:
    w, _fake = _make(qtbot, {**_RUNNING_NO_START, "stop_allowed": False})

    w.apply_leaf(PREFIX + "stop_allowed", True)

    assert _btn(w, "RunStopButton").isEnabled()


def test_widget_stop_click_sends_stop_command(qtbot) -> None:
    w, fake = _make(qtbot, {**_RUNNING_NO_START, "stop_allowed": True})

    _btn(w, "RunStopButton").click()

    assert fake.calls == ["stop"]


def test_widget_stop_active_after_stop_allowed_leaf_deleted(qtbot) -> None:
    """Лист stop_allowed удалён (DELETED) -> запасное правило по состоянию: running -> активна."""
    w, _fake = _make(qtbot, {"state": "running", "stop_allowed": True})

    w.apply_leaf(PREFIX + "stop_allowed", DELETED)

    assert _btn(w, "RunStopButton").isEnabled()


# ===========================================================================
# REDS 8: (б) виджет
# ===========================================================================


def test_widget_gate_label_shown_when_run_gate_false(qtbot) -> None:
    w, _fake = _make(qtbot, {"state": "ready", "start_allowed": True, "run_gate": False})

    label = _gate_label(w)
    assert label.text() == "Гейт выключен: кадры идут без ЗАПУСТИТЬ"
    assert label.isHidden() is False


def test_widget_gate_label_keeps_start_button_by_pm_flags(qtbot) -> None:
    """Подпись не гасит кнопки: ЗАПУСТИТЬ активна по start_allowed при run_gate: False."""
    w, _fake = _make(qtbot, {"state": "ready", "start_allowed": True, "run_gate": False})

    assert _btn(w, "RunStartButton").isEnabled()


def test_widget_gate_label_cleared_and_hidden_when_run_gate_true(qtbot) -> None:
    w, _fake = _make(qtbot, {"state": "ready", "start_allowed": True, "run_gate": False})
    label = _gate_label(w)
    assert label.text() == "Гейт выключен: кадры идут без ЗАПУСТИТЬ"  # предусловие: подпись была показана

    w.apply_leaf(PREFIX + "run_gate", True)

    assert label.text() == ""
    assert label.isHidden() is True


def test_widget_gate_label_hidden_without_run_gate_leaf(qtbot) -> None:
    """Старый бэкенд: листа run_gate нет -> метка существует, но скрыта."""
    w, _fake = _make(qtbot, {"state": "ready"})

    assert _gate_label(w).isHidden() is True


# ===========================================================================
# REDS 9: (Р3) затравка
# ===========================================================================


def _seeded_widget(qtbot, body: dict, leaves: dict | None = None):
    """Новый виджет, set_commands, (листья), затем ответ затравки `body`."""
    w, fake = _make(qtbot, leaves)
    assert len(fake.status_callbacks) == 1
    fake.status_callbacks[0]({"success": True, "result": body})
    return w, fake


def test_seed_brings_run_gate_into_gate_label(qtbot) -> None:
    """9а: run_gate приходит из затравки, листа ещё не было -> подпись показана."""
    w, _fake = _seeded_widget(
        qtbot, {"state": "ready", "start_allowed": True, "run_gate": False, "stop_allowed": False}
    )

    assert _gate_label(w).text() == "Гейт выключен: кадры идут без ЗАПУСТИТЬ"


def test_seed_does_not_bring_stale_stop_allowed(qtbot) -> None:
    """9а (Р3): stop_allowed из затравки не берётся -> после листа state=running ОСТАНОВИТЬ активна
    (устаревший stop_allowed=False времён ready её не гасит)."""
    w, _fake = _seeded_widget(
        qtbot, {"state": "ready", "start_allowed": True, "run_gate": False, "stop_allowed": False}
    )

    w.apply_leaf(PREFIX + "state", "running")

    assert _btn(w, "RunStopButton").isEnabled()


def test_seed_does_not_overwrite_fresher_run_gate_leaf(qtbot) -> None:
    """9б: свежий лист run_gate=True не затирается ответом затравки run_gate=False."""
    w, _fake = _seeded_widget(qtbot, {"state": "ready", "run_gate": False}, leaves={"run_gate": True})

    label = _gate_label(w)
    assert label.text() == ""
    assert label.isHidden() is True
