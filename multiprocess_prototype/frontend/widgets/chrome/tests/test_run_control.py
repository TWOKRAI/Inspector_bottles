"""Приёмочные тесты Task 2.3: модель `build_view` и виджет `RunControlWidget`.

Слепые: пишутся по `plans/2026-10-27_system-run-state/tasks/2.3.md` (DESIGN П.1-П.2,
REDS 1-15a), без реализации. Все ожидания - литералы из спецификации.
"""

from __future__ import annotations

import time

import pytest
from PySide6.QtWidgets import QLabel, QPushButton

from multiprocess_prototype.frontend.state.bindings import DELETED
from multiprocess_prototype.frontend.widgets.chrome import run_control
from multiprocess_prototype.frontend.widgets.chrome.run_control import (
    RunControlWidget,
    RunView,
    build_view,
)

PREFIX = "system.run."


def _reason(severity: str, text: str, node: str = "n", source: str = "s") -> dict:
    return {"severity": severity, "reason": text, "node": node, "source": source}


# ---------------------------------------------------------------------------
# Фейк команд и помощники виджета
# ---------------------------------------------------------------------------


class FakeCommands:
    """Четыре метода run_*_async; записывает вызовы и сохраняет on_result.

    `run_status_async` (затравка) on_result сохраняет и НЕ зовёт; в `calls` он не
    попадает - там только команды оператора.
    """

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.callbacks: dict[str, list] = {"start": [], "stop": [], "ack": []}
        self.status_callbacks: list = []

    def run_start_async(self, on_result) -> None:
        self.calls.append("start")
        self.callbacks["start"].append(on_result)

    def run_stop_async(self, on_result) -> None:
        self.calls.append("stop")
        self.callbacks["stop"].append(on_result)

    def run_ack_async(self, on_result) -> None:
        self.calls.append("ack")
        self.callbacks["ack"].append(on_result)

    def run_status_async(self, on_result) -> None:
        self.status_callbacks.append(on_result)


def _make(qtbot, leaves: dict | None = None, commands: FakeCommands | None = None):
    """Виджет + фейк команд + листья (ключ без префикса `system.run.`)."""
    fake = commands if commands is not None else FakeCommands()
    w = RunControlWidget()
    qtbot.addWidget(w)
    w.set_commands(fake)
    for key, value in (leaves or {}).items():
        w.apply_leaf(PREFIX + key, value)
    return w, fake


def _make_no_commands(qtbot, leaves: dict):
    w = RunControlWidget()
    qtbot.addWidget(w)
    for key, value in leaves.items():
        w.apply_leaf(PREFIX + key, value)
    return w


def _btn(w, name: str) -> QPushButton:
    b = w.findChild(QPushButton, name)
    assert b is not None, f"нет кнопки {name}"
    return b


def _lbl(w, name: str) -> QLabel:
    lb = w.findChild(QLabel, name)
    assert lb is not None, f"нет метки {name}"
    return lb


READY_LEAVES = {"state": "ready", "start_allowed": True}


# ===========================================================================
# Модель (без Qt)
# ===========================================================================


@pytest.mark.parametrize(
    ("state", "text", "level", "stop_en", "ack_vis"),
    [
        ("booting", "Поднимается", "neutral", False, False),
        ("not_ready", "Не готов", "warn", False, False),
        ("ready", "Готов", "ok", False, False),
        ("running", "Работает", "ok", True, False),
        ("stopping", "Останавливается", "neutral", False, False),
        ("fault", "Авария", "danger", False, True),
        ("shutting_down", "Завершение", "neutral", False, False),
    ],
)
def test_model_state_table(state, text, level, stop_en, ack_vis) -> None:
    """REDS 2: имя, level, stop_enabled, ack_visible; start_allowed False -> ЗАПУСТИТЬ неактивна."""
    view = build_view({"state": state, "start_allowed": False}, False)

    assert isinstance(view, RunView)
    assert view.state_text == text
    assert view.level == level
    assert view.stop_enabled is stop_en
    assert view.ack_visible is ack_vis
    assert view.start_enabled is False


def test_model_empty_snapshot_and_busy_gating() -> None:
    """REDS 1 + 4: пустой снимок; busy гасит start/stop/ack."""
    # --- 1: пустой снимок и состояние вне таблицы -> «Нет данных»
    for snapshot in ({}, {"state": "bogus", "start_allowed": True, "ack_allowed": True}):
        v = build_view(snapshot, False)
        assert v.state_text == "Нет данных"
        assert v.level == "neutral"
        assert v.start_enabled is False
        assert v.stop_enabled is False
        assert v.ack_visible is False
        assert v.ack_enabled is False
        assert v.detail_text == ""
        assert v.indicators_text == ""
        assert v.fault_text == ""
        assert v.start_tooltip == ""

    # --- 4: ready + start_allowed True
    ready = {"state": "ready", "start_allowed": True}
    v = build_view(ready, False)
    assert v.start_enabled is True
    assert v.detail_text == ""
    assert build_view(ready, True).start_enabled is False
    # отсутствие листа start_allowed = False
    assert build_view({"state": "ready"}, False).start_enabled is False

    # --- 4: running + busy -> stop неактивна
    running = {"state": "running", "start_allowed": False}
    assert build_view(running, False).stop_enabled is True
    assert build_view(running, True).stop_enabled is False

    # --- 4: fault + ack_allowed True + busy -> ack неактивна
    fault = {"state": "fault", "ack_allowed": True}
    assert build_view(fault, False).ack_enabled is True
    assert build_view(fault, True).ack_enabled is False
    # ack_allowed отсутствует -> ack неактивна (но видна)
    v = build_view({"state": "fault"}, False)
    assert v.ack_visible is True
    assert v.ack_enabled is False


def test_model_blocking_reasons_and_fault_override() -> None:
    """REDS 3 + 5: блокирующие причины; в fault правило ЗАПУСТИТЬ перекрыто."""
    # --- 3: out_of_spec «A» не блокирует; failure раньше check_function
    snap = {
        "state": "not_ready",
        "start_allowed": False,
        "reasons": [
            _reason("out_of_spec", "A", node="n0"),
            _reason("failure", "диск не найден", node="n1"),
            _reason("check_function", "B", node="n2"),
        ],
    }
    v = build_view(snap, False)
    assert v.start_enabled is False
    assert v.detail_text == "диск не найден"
    assert "диск не найден" in v.start_tooltip
    assert "B" in v.start_tooltip
    assert "A" not in v.start_tooltip
    # построчно `node: reason`, failure раньше check_function
    assert v.start_tooltip == "n1: диск не найден\nn2: B"

    # failure важнее check_function независимо от порядка в списке
    snap_swapped = {
        "state": "not_ready",
        "start_allowed": False,
        "reasons": [_reason("check_function", "B", node="n2"), _reason("failure", "F", node="n1")],
    }
    v = build_view(snap_swapped, False)
    assert v.detail_text == "F"
    assert v.start_tooltip == "n1: F\nn2: B"

    # нет failure -> первая check_function
    only_check = {
        "state": "not_ready",
        "start_allowed": False,
        "reasons": [_reason("check_function", "C1", node="m1"), _reason("check_function", "C2", node="m2")],
    }
    assert build_view(only_check, False).detail_text == "C1"
    assert build_view(only_check, False).start_tooltip == "m1: C1\nm2: C2"

    # только неблокирующие -> пусто
    non_blocking = {
        "state": "not_ready",
        "start_allowed": False,
        "reasons": [_reason("out_of_spec", "A"), _reason("maintenance", "M")],
    }
    v = build_view(non_blocking, False)
    assert v.detail_text == ""
    assert v.start_tooltip == ""

    # --- 5: fault, ack_allowed False, reasons с failure -> «идёт остановка»
    v = build_view({"state": "fault", "ack_allowed": False, "reasons": [_reason("failure", "X")]}, False)
    assert v.ack_visible is True
    assert v.ack_enabled is False
    assert v.detail_text == "идёт остановка"

    # --- 5: ack_allowed True -> первая причина last_fault.reasons
    last_fault = {"at": 100.0, "reasons": [_reason("failure", "обрыв")], "acknowledged_at": None}
    v = build_view(
        {"state": "fault", "ack_allowed": True, "reasons": [_reason("failure", "X")], "last_fault": last_fault},
        False,
    )
    assert v.ack_enabled is True
    assert v.detail_text == "обрыв"

    # --- 5: ack_allowed True, last_fault None -> пусто
    v = build_view({"state": "fault", "ack_allowed": True, "last_fault": None}, False)
    assert v.detail_text == ""


def test_model_indicators_fault_text_and_invalid_input() -> None:
    """REDS 6 + 7 + 8: индикаторы В8, строка последней аварии, негодный ввод."""
    # --- 6: индикаторы только в running, цвет аварии не используют
    reasons = [_reason("out_of_spec", "диск"), _reason("maintenance", "замена")]
    v = build_view({"state": "running", "reasons": reasons}, False)
    assert v.indicators_text == "Вне допуска: диск · Обслуживание: замена"
    assert v.level == "ok"
    assert build_view({"state": "ready", "reasons": reasons}, False).indicators_text == ""

    two_oos = [_reason("out_of_spec", "r1"), _reason("out_of_spec", "r2")]
    assert build_view({"state": "running", "reasons": two_oos}, False).indicators_text == "Вне допуска: r1; r2"
    only_maint = [_reason("maintenance", "замена")]
    assert build_view({"state": "running", "reasons": only_maint}, False).indicators_text == "Обслуживание: замена"

    # --- 7: fault_text; ожидаемое время - локальное strftime от `at`
    t100 = time.strftime("%H:%M:%S", time.localtime(100.0))
    t120 = time.strftime("%H:%M:%S", time.localtime(120.0))
    lf = {"at": 100.0, "reasons": [_reason("failure", "обрыв")], "acknowledged_at": None}
    v = build_view({"state": "ready", "last_fault": lf}, False)
    assert v.fault_text == f"Последняя авария {t100} — обрыв — не квитирована"

    lf_ack = {"at": 100.0, "reasons": [_reason("failure", "обрыв")], "acknowledged_at": 120.0}
    v = build_view({"state": "ready", "last_fault": lf_ack}, False)
    assert v.fault_text == f"Последняя авария {t100} — обрыв — квитирована {t120}"
    assert "не квитирована" not in v.fault_text

    assert build_view({"state": "ready", "last_fault": None}, False).fault_text == ""

    # --- 8: негодный ввод не бросает
    bad_snapshots = [
        {"state": "not_ready", "reasons": "строка вместо списка"},
        {"state": "not_ready", "start_allowed": False, "reasons": [1, None, "x", ["y"]]},
        {"state": "not_ready", "reasons": [{"severity": "failure"}]},
        {"state": "running", "reasons": "строка"},
        {"state": "fault", "ack_allowed": True, "last_fault": 5},
        {"state": "fault", "ack_allowed": False, "reasons": "oops", "last_fault": 5},
        {"state": "ready", "last_fault": {}},
        {"state": "ready", "last_fault": {"reasons": "s"}},
        {"state": ["не", "хешируемое"]},
    ]
    for snap in bad_snapshots:
        for busy in (False, True):
            assert isinstance(build_view(snap, busy), RunView)

    assert build_view({"state": "fault", "ack_allowed": True, "last_fault": 5}, False).fault_text == ""
    assert build_view({"state": "ready", "last_fault": "строка"}, False).fault_text == ""
    assert build_view({"state": ["не", "хешируемое"]}, False).state_text == "Нет данных"

    # негодные записи пропускаются, годные работают
    mixed = {
        "state": "not_ready",
        "start_allowed": False,
        "reasons": ["мусор", None, _reason("failure", "диск")],
    }
    assert build_view(mixed, False).detail_text == "диск"


# ===========================================================================
# Виджет
# ===========================================================================


def test_widget_start_click_busy_cycle(qtbot) -> None:
    """REDS 9: клик ЗАПУСТИТЬ -> busy до смены state; порядок «ответ/дельта» в обе стороны."""
    # --- A: ответ раньше дельты
    w, fake = _make(qtbot, READY_LEAVES)
    start = _btn(w, "RunStartButton")
    assert start.text() == "ЗАПУСТИТЬ"
    assert _btn(w, "RunStopButton").text() == "ОСТАНОВИТЬ"
    assert _btn(w, "RunAckButton").text() == "Квитировать"
    assert start.isEnabled()

    start.click()
    assert fake.calls == ["start"]
    assert not start.isEnabled()  # до on_result

    start.click()
    assert fake.calls == ["start"]  # повторный клик ничего не шлёт

    fake.callbacks["start"][0]({"success": True, "result": {"success": True, "state": "running"}})
    assert not start.isEnabled()  # state ещё не сменился -> busy держится

    w.apply_leaf(PREFIX + "start_allowed", False)
    w.apply_leaf(PREFIX + "state", "running")
    stop = _btn(w, "RunStopButton")
    assert stop.isEnabled()
    assert not start.isEnabled()

    # после клика ОСТАНОВИТЬ повторный клик ничего не шлёт
    stop.click()
    assert fake.calls == ["start", "stop"]
    stop.click()
    assert fake.calls == ["start", "stop"]

    # --- B: дельта state=running ПРИШЛА ДО on_result
    w2, fake2 = _make(qtbot, READY_LEAVES)
    start2 = _btn(w2, "RunStartButton")
    start2.click()
    assert fake2.calls == ["start"]
    w2.apply_leaf(PREFIX + "start_allowed", False)
    w2.apply_leaf(PREFIX + "state", "running")
    fake2.callbacks["start"][0]({"success": True, "result": {"success": True, "state": "running"}})
    stop2 = _btn(w2, "RunStopButton")
    assert stop2.isEnabled()  # включена сразу, без ожидания новой смены
    assert not start2.isEnabled()
    stop2.click()
    assert fake2.calls == ["start", "stop"]


def test_widget_stop_and_ack_clicks(qtbot) -> None:
    """REDS 12: ОСТАНОВИТЬ -> run_stop_async; Квитировать -> run_ack_async; Ack скрыта вне fault."""
    # --- running
    w, fake = _make(qtbot, {"state": "running", "start_allowed": False})
    stop = _btn(w, "RunStopButton")
    assert stop.isEnabled()
    assert _btn(w, "RunAckButton").isHidden()
    stop.click()
    assert fake.calls == ["stop"]

    # --- fault + ack_allowed True
    w2, fake2 = _make(qtbot, {"state": "fault", "ack_allowed": True, "start_allowed": False})
    ack = _btn(w2, "RunAckButton")
    assert not ack.isHidden()
    assert ack.isEnabled()
    assert not _btn(w2, "RunStopButton").isEnabled()
    ack.click()
    assert fake2.calls == ["ack"]

    # --- fault + ack_allowed False: видна, но неактивна, клик ничего не шлёт
    w3, fake3 = _make(qtbot, {"state": "fault", "ack_allowed": False})
    ack3 = _btn(w3, "RunAckButton")
    assert not ack3.isHidden()
    assert not ack3.isEnabled()
    ack3.click()
    assert fake3.calls == []


def test_widget_refusal_and_failures(qtbot) -> None:
    """REDS 10 + 11: отказ, транспортный сбой, коды отказа; busy снимается."""
    # --- 10: отказ с причиной
    w, fake = _make(qtbot, READY_LEAVES)
    start = _btn(w, "RunStartButton")
    detail = _lbl(w, "RunDetailLabel")
    start.click()
    assert not start.isEnabled()
    fake.callbacks["start"][0](
        {
            "success": False,
            "result": {
                "success": False,
                "state": "not_ready",
                "error": "not_ready",
                "reasons": [
                    _reason("failure", "нет диска", node="n"),
                    _reason("failure", "вторая причина", node="m"),
                ],
            },
        }
    )
    assert start.isEnabled()  # busy снят (state ready, start_allowed True)
    assert "система не готова" in detail.text()
    assert "нет диска" in detail.text()
    assert "вторая причина" not in detail.text()  # только первая причина

    # повторная доставка ТОГО ЖЕ значения state - текст не стирает
    w.apply_leaf(PREFIX + "state", "ready")
    assert "система не готова" in detail.text()
    # смена значения - стирает
    w.apply_leaf(PREFIX + "state", "booting")
    assert "система не готова" not in detail.text()
    assert "нет диска" not in detail.text()

    # --- 11: транспортные сбои и форма «исключение в обработчике PM»
    failures = [
        ({"success": False, "error": "timeout", "correlation_id": "c1"}, "нет ответа от системы"),
        ({"success": False, "error": "пул упал"}, "нет ответа от системы"),
        ({"success": False, "result": {"status": "error", "reason": "x"}}, "отказ"),
    ]
    for payload, expected in failures:
        w2, fake2 = _make(qtbot, READY_LEAVES)
        b = _btn(w2, "RunStartButton")
        b.click()
        assert not b.isEnabled()
        fake2.callbacks["start"][0](payload)
        text = _lbl(w2, "RunDetailLabel").text()
        assert expected in text, payload
        assert "None" not in text, payload
        assert b.isEnabled(), payload  # кнопки не зависают

    # --- коды отказа (П.2): литералы
    codes = [
        ("not_ready", "система не готова"),
        ("already_running", "уже работает"),
        ("stopping", "идёт остановка"),
        ("fault_unacknowledged", "авария не квитирована"),
        ("fault_stopping", "идёт остановка после аварии"),
        ("no_fault", "аварии нет"),
        ("shutting_down", "система завершает работу"),
        ("неведомый_код", "отказ: неведомый_код"),
    ]
    for code, expected in codes:
        w3, fake3 = _make(qtbot, READY_LEAVES)
        _btn(w3, "RunStartButton").click()
        fake3.callbacks["start"][0]({"success": False, "result": {"success": False, "state": "ready", "error": code}})
        assert expected in _lbl(w3, "RunDetailLabel").text(), code

    for result_body in (
        {"success": False, "state": "ready"},
        {"success": False, "state": "ready", "error": None},
    ):
        w4, fake4 = _make(qtbot, READY_LEAVES)
        _btn(w4, "RunStartButton").click()
        fake4.callbacks["start"][0]({"success": False, "result": result_body})
        text = _lbl(w4, "RunDetailLabel").text()
        assert "отказ" in text
        assert "None" not in text


def test_widget_without_commands_and_deleted_leaf(qtbot) -> None:
    """REDS 13 + 14: клик без commands - «нет связи»; удаление листа state - «Нет данных»."""
    # --- 13
    w = _make_no_commands(qtbot, READY_LEAVES)
    start = _btn(w, "RunStartButton")
    assert start.isEnabled()
    start.click()  # не бросает (pytest-qt поймал бы исключение в слоте)
    assert "нет связи" in _lbl(w, "RunDetailLabel").text()

    # --- 14
    w2, fake2 = _make(qtbot, {"state": "running", "start_allowed": True, "ack_allowed": True})
    assert _lbl(w2, "RunStateLabel").text() == "Работает"
    w2.apply_leaf(PREFIX + "state", DELETED)
    assert _lbl(w2, "RunStateLabel").text() == "Нет данных"
    assert not _btn(w2, "RunStartButton").isEnabled()
    assert not _btn(w2, "RunStopButton").isEnabled()
    assert not _btn(w2, "RunAckButton").isEnabled()
    assert fake2.calls == []

    # удалённый лист не мешает вернуться: новое значение снова рисуется
    w2.apply_leaf(PREFIX + "state", "ready")
    assert _lbl(w2, "RunStateLabel").text() == "Готов"


def test_widget_display_wiring(qtbot) -> None:
    """REDS 15: подсказка, level, last_fault, индикаторы, «Нет данных» до первого листа."""
    w = RunControlWidget()
    qtbot.addWidget(w)
    state_lbl = _lbl(w, "RunStateLabel")
    assert state_lbl.text() == "Нет данных"

    # --- подсказка при неактивной кнопке
    w.apply_leaf(PREFIX + "state", "not_ready")
    w.apply_leaf(PREFIX + "start_allowed", False)
    w.apply_leaf(PREFIX + "reasons", [_reason("failure", "нет диска", node="disk")])
    start = _btn(w, "RunStartButton")
    assert not start.isEnabled()
    assert "нет диска" in start.toolTip()
    assert state_lbl.text() == "Не готов"
    assert state_lbl.property("level") == "warn"

    # --- level
    w.apply_leaf(PREFIX + "state", "fault")
    assert state_lbl.text() == "Авария"
    assert state_lbl.property("level") == "danger"
    w.apply_leaf(PREFIX + "state", "running")
    assert state_lbl.text() == "Работает"
    assert state_lbl.property("level") == "ok"

    # --- индикаторы В8
    indicators = _lbl(w, "RunIndicatorsLabel")
    w.apply_leaf(PREFIX + "reasons", [_reason("out_of_spec", "диск")])
    assert "Вне допуска: диск" in indicators.text()
    w.apply_leaf(PREFIX + "state", "ready")
    assert indicators.text() == ""

    # --- last_fault: лист-значение целиком, затем None
    fault_lbl = _lbl(w, "RunFaultLabel")
    w.apply_leaf(
        PREFIX + "last_fault",
        {"at": 100.0, "reasons": [_reason("failure", "обрыв")], "acknowledged_at": None},
    )
    assert "обрыв" in fault_lbl.text()
    w.apply_leaf(PREFIX + "last_fault", None)
    assert fault_lbl.text() == ""


def test_widget_busy_safety_timer(qtbot, monkeypatch) -> None:
    """REDS 15a: страховка BUSY_SAFETY_MS снимает busy; таймер старого клика не трогает новый."""
    # --- часть 1: BUSY_SAFETY_MS = 50 до создания виджета
    monkeypatch.setattr(run_control, "BUSY_SAFETY_MS", 50)
    w, fake = _make(qtbot, READY_LEAVES)
    start = _btn(w, "RunStartButton")
    start.click()
    assert fake.calls == ["start"]
    fake.callbacks["start"][0]({"success": True, "result": {"success": True, "state": "running"}})
    assert not start.isEnabled()  # смены state не было -> busy держится
    start.click()
    assert fake.calls == ["start"]  # в пределах окна страховки второй команды нет
    qtbot.waitUntil(start.isEnabled, timeout=2000)  # страховка сняла busy
    assert fake.calls == ["start"]

    # --- часть 2: таймер первого клика не снимает busy второго.
    # Окно 400 мс, клики разнесены на 200 мс: таймер 1-го сработает на t=400,
    # таймера 2-го на t=600; проверка на t=500. Ожидание по времени неизбежно:
    # проверяется ОТСУТСТВИЕ срабатывания, waitUntil тут не применим.
    monkeypatch.setattr(run_control, "BUSY_SAFETY_MS", 400)
    w2, fake2 = _make(qtbot, READY_LEAVES)
    start2 = _btn(w2, "RunStartButton")
    start2.click()  # t=0, таймер 1
    assert fake2.calls == ["start"]
    fake2.callbacks["start"][0]({"success": False, "error": "timeout"})  # busy снят отказом
    assert start2.isEnabled()
    qtbot.wait(200)
    assert start2.isEnabled()
    start2.click()  # t=200, таймер 2
    assert fake2.calls == ["start", "start"]
    qtbot.wait(300)  # t=500: таймер 1 уже сработал, таймер 2 - нет
    assert not start2.isEnabled(), "таймер старого клика снял busy нового"
    assert fake2.calls == ["start", "start"]
    qtbot.waitUntil(start2.isEnabled, timeout=2000)  # таймер 2 сработал
