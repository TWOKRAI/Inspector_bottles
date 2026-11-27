# -*- coding: utf-8 -*-
"""Слепые приёмочные тесты 2.10 (GUI): вне ``running`` кадр только на display превью, пункты G1-G13.

Написаны по приёмочным пунктам задачи 2.10 до реализации. Настоящие ``_setup_bridge_callbacks``,
``DataReceiverBridge``, ``FramePump`` и ``ImagePanelWidget``; рецепт — словарь. ``bindings`` —
двойник ``bind_fanout(pattern, callback, owner)``; в G12 и G13 — настоящий ``GuiStateBindings``.

Ожидаемые тексты — литералы. Ожидание — цикл событий Qt с дедлайном. «Кадр не показан»
проверяется только после того, как контрольный экран той же проводки свой кадр показал.

Запуск (из корня worktree, PYTHONPATH=корень, PYTHONUTF8=1, Qt offscreen), класс ``light``.
"""

from __future__ import annotations

import faulthandler
import os
import time
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QLabel  # noqa: E402

__all__: list[str] = []

_IDLE = "Маска\nЛиния не запущена: обработанный кадр появится после ЗАПУСТИТЬ"
_FAULT = "Маска\nАвария: обработка остановлена"
_NO_DATA = "Маска\nНет данных о состоянии линии"
_WAIT = "Маска\nРаботает: ждём первый обработанный кадр"

_HANG_DEADLINE_S = 60.0  # pytest-timeout в venv нет: зависший тест снимает faulthandler


@pytest.fixture(autouse=True)
def _hang_deadline():
    faulthandler.dump_traceback_later(_HANG_DEADLINE_S, exit=True)
    yield
    faulthandler.cancel_dump_traceback_later()


# ---------------------------------------------------------------------------
# Помощники
# ---------------------------------------------------------------------------


def _spin_until(cond: Callable[[], bool], timeout_s: float) -> bool:
    """Крутить цикл событий Qt, пока cond() не станет True или не истечёт timeout_s."""
    loop = QEventLoop()
    deadline = time.perf_counter() + timeout_s
    state = {"ok": False}
    poll = QTimer()
    poll.setInterval(5)

    def _check() -> None:
        if cond():
            state["ok"] = True
            loop.quit()
        elif time.perf_counter() >= deadline:
            loop.quit()

    poll.timeout.connect(_check)
    poll.start()
    _check()
    if not state["ok"] and time.perf_counter() < deadline:
        loop.exec()
    poll.stop()
    return state["ok"]


def _spin(seconds: float) -> None:
    _spin_until(lambda: False, seconds)


def _msg(sender: str, capture_ts: float | None = None) -> dict:
    return {
        "sender": sender,
        "frame": np.full((48, 64, 3), 200, dtype=np.uint8),
        "data": {"capture_ts": time.time() if capture_ts is None else capture_ts},
    }


def _recipe(display_id: str, **keys: Any) -> dict:
    """Экран «Маска» (под проверкой, отправитель ``sm``) и контрольный без ``run_view`` (``sc``)."""

    def _display(ident: str, name: str, x: int, **extra: Any) -> dict:
        return {
            "id": ident,
            "name": name,
            "enabled": True,
            "position": {"x": x, "y": 0},
            "fps_limit": 30.0,
            **extra,
        }

    return {
        "displays": [
            _display(display_id, "Маска", 0, **keys),
            _display(f"{display_id}_ctl", "Контроль", 10),
        ],
        "blueprint": {
            "displays": [
                {"node_id": "sm.src.frame", "display_id": display_id},
                {"node_id": "sc.src.frame", "display_id": f"{display_id}_ctl"},
            ]
        },
    }


class _Bindings:
    """Двойник ``GuiStateBindings.bind_fanout``: лист получают подписки с подходящим шаблоном."""

    def __init__(self) -> None:
        self.subs: list[tuple[str, Callable[[str, Any], None], Any]] = []

    def bind_fanout(self, pattern: str, callback: Callable[[str, Any], None], owner: Any = None) -> object:
        self.subs.append((pattern, callback, owner))
        return object()

    def leaf(self, name: str, value: Any) -> None:
        from multiprocess_prototype.frontend.state.glob_match import match_glob

        path = f"system.run.{name}"
        matched = [callback for pattern, callback, _ in self.subs if match_glob(pattern, path)]
        if name == "state":
            assert matched, "проводка не подписалась на system.run.state"
        for callback in matched:
            callback(path, value)


def _real_bindings(bridge: Any) -> Any:
    """Настоящие read-model и ``GuiStateBindings`` на мосту проводки, порядок слушателей как в app.py."""
    from multiprocess_framework.modules.frontend_module.state import TelemetryViewModel
    from multiprocess_prototype.frontend.state.bindings import GuiStateBindings

    read_model = TelemetryViewModel(initial_cache={})
    bindings = GuiStateBindings(bridge, read_model=read_model)
    bridge.add_state_listener(read_model.on_state_delta)
    return bindings


def _state_delta(bridge: Any, name: str, value: Any) -> None:
    bridge.dispatch({"data_type": "state_delta", "path": f"system.run.{name}", "value": value})


@pytest.fixture()
def wire(qtbot):
    """Фабрика проводки: настоящие мост, насос и панель.

    ``real_bindings=True`` — вместо двойника настоящий ``GuiStateBindings``; ``before`` получает мост
    ДО ``_setup_bridge_callbacks`` (поздний GUI).
    """
    from multiprocess_prototype.frontend import app as app_module
    from multiprocess_prototype.frontend.bridge import DataReceiverBridge
    from multiprocess_prototype.frontend.frame_intake import FrameIntake
    from multiprocess_prototype.frontend.widgets.image_panel.widget import ImagePanelWidget

    pumps: list = []

    def _make(
        recipe: dict, *, real_bindings: bool = False, before: Callable[[Any], None] | None = None
    ) -> SimpleNamespace:
        class _Recipes:
            def get_active(self) -> str:
                return "run_view_blind"

            def read_recipe(self, _slug: str) -> dict:
                return recipe

        subscribers: list = []
        bus = SimpleNamespace(subscribe=lambda event, callback: subscribers.append((event, callback)))
        bridge = DataReceiverBridge()
        panel = ImagePanelWidget()
        qtbot.addWidget(panel)
        intake = FrameIntake(MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock())
        process = SimpleNamespace(_bridge=bridge, _frame_intake=intake, _log_info=MagicMock(), _log_warning=MagicMock())
        bindings = _real_bindings(bridge) if real_bindings else _Bindings()
        if before is not None:
            before(bridge)
        app_module._setup_bridge_callbacks(
            process, panel, MagicMock(name="window"), recipe_manager=_Recipes(), event_bus=bus, bindings=bindings
        )
        pumps.append(process._frame_pump)

        def activate_recipe() -> None:
            from multiprocess_prototype.domain.events import RecipeActivated

            callbacks = [callback for event, callback in subscribers if event is RecipeActivated]
            assert callbacks, "подписка на RecipeActivated не сделана"
            for callback in callbacks:
                callback(RecipeActivated(slug="run_view_blind"))

        return SimpleNamespace(
            bridge=bridge, panel=panel, pump=process._frame_pump, bindings=bindings, activate_recipe=activate_recipe
        )

    yield _make
    for pump in pumps:
        pump.stop()
    QCoreApplication.removePostedEvents(None)


def _label(panel: Any, slot_id: str) -> QLabel:
    return panel._slots[slot_id].findChild(QLabel, "DisplaySlotLabel")  # noqa: SLF001


def _shown(panel: Any, slot_id: str) -> int:
    return panel.presenter.frame_stats(slot_id)["shown"]


def _assert_text(panel: Any, slot_id: str, expected: str, timeout_s: float = 1.0) -> None:
    _spin_until(lambda: _label(panel, slot_id).text() == expected, timeout_s)
    assert _label(panel, slot_id).text() == expected


def _assert_frame_shown(w: SimpleNamespace, slot_id: str, capture_ts: float | None = None) -> None:
    before = _shown(w.panel, slot_id)
    w.bridge.dispatch(_msg("sm", capture_ts))
    assert _spin_until(lambda: _shown(w.panel, slot_id) > before, 1.0), (
        f"кадр не показан, на экране: {_label(w.panel, slot_id).text()!r}"
    )
    _spin(0.2)
    assert not _label(w.panel, slot_id).pixmap().isNull(), (
        f"кадр на экране не удержался: {_label(w.panel, slot_id).text()!r}"
    )


def _assert_frame_not_shown(w: SimpleNamespace, slot_id: str, capture_ts: float | None = None) -> None:
    control = f"{slot_id}_ctl"
    w.bridge.dispatch(_msg("sm", capture_ts))
    w.bridge.dispatch(_msg("sc"))
    assert _spin_until(lambda: _shown(w.panel, control) >= 1, 1.0), "контрольный экран кадр не показал"
    _spin(0.3)  # период насоса при 30 Гц — 33 мс
    assert _shown(w.panel, slot_id) == 0, "кадр показан"
    assert _label(w.panel, slot_id).pixmap().isNull(), "на экране картинка"


def _enter(w: SimpleNamespace, state: str) -> None:
    w.bindings.leaf("state", state)
    _spin(0.05)  # шаг time.time() на Windows ~16 мс: capture_ts следующего кадра строго позже входа


# ---------------------------------------------------------------------------
# G1-G4: кому кадр положен
# ---------------------------------------------------------------------------


def test_g1_display_without_key_shows_frame_in_ready(wire) -> None:
    """Контроль."""
    d = "rv_g1"
    w = wire(_recipe(d))
    _enter(w, "ready")

    _assert_frame_shown(w, d)


def test_g2_running_display_hides_frame_in_ready(wire) -> None:
    d = "rv_g2"
    w = wire(_recipe(d, run_view="running"))
    _enter(w, "ready")

    _assert_frame_not_shown(w, d)
    assert _label(w.panel, d).text() == _IDLE


@pytest.mark.parametrize("state", ["ready", "fault"])
def test_g3_always_display_shows_frame(wire, state: str) -> None:
    """Контроль."""
    d = f"rv_g3_{state}"
    w = wire(_recipe(d, run_view="always"))
    _enter(w, state)

    _assert_frame_shown(w, d)


@pytest.mark.parametrize("order", [("run_gate", "state"), ("state", "run_gate")], ids=["gate_first", "state_first"])
def test_g4_gate_off_shows_frame_in_ready(wire, order: tuple[str, str]) -> None:
    """Контроль."""
    d = f"rv_g4_{order[0]}"
    w = wire(_recipe(d, run_view="running"))
    values = {"run_gate": False, "state": "ready"}
    for name in order:
        w.bindings.leaf(name, values[name])
    _spin(0.05)

    _assert_frame_shown(w, d)


# ---------------------------------------------------------------------------
# G5: свежесть кадра в running
# ---------------------------------------------------------------------------


def test_g5_fresh_frame_is_shown_in_running(wire) -> None:
    d = "rv_g5_fresh"
    w = wire(_recipe(d, run_view="running"))
    _enter(w, "running")

    _assert_frame_shown(w, d, capture_ts=time.time())


def test_g5_five_seconds_old_frame_is_not_shown_in_running(wire) -> None:
    d = "rv_g5_stale"
    w = wire(_recipe(d, run_view="running"))
    _enter(w, "running")

    _assert_frame_not_shown(w, d, capture_ts=time.time() - 5.0)


# ---------------------------------------------------------------------------
# G6-G9: тексты плашек
# ---------------------------------------------------------------------------


def test_g6_leaving_running_without_frame_shows_idle_within_a_second(wire) -> None:
    d = "rv_g6"
    w = wire(_recipe(d, run_view="running"))
    _enter(w, "running")

    w.bindings.leaf("state", "ready")

    _assert_text(w.panel, d, _IDLE, timeout_s=1.0)


def test_g7_fault_plate_text(wire) -> None:
    d = "rv_g7_text"
    w = wire(_recipe(d, run_view="running"))
    _enter(w, "fault")

    _assert_text(w.panel, d, _FAULT)


def test_g7_running_display_hides_frame_in_fault(wire) -> None:
    """Goal задачи: «в том числе в fault: display run_view: running — плашка»."""
    d = "rv_g7_frame"
    w = wire(_recipe(d, run_view="running"))
    _enter(w, "fault")

    _assert_frame_not_shown(w, d)
    assert _label(w.panel, d).text() == _FAULT


def test_g8_no_state_leaf_shows_no_data(wire) -> None:
    d = "rv_g8"
    w = wire(_recipe(d, run_view="running"))

    _assert_text(w.panel, d, _NO_DATA)


def test_g9_entering_running_without_frame_shows_wait(wire) -> None:
    d = "rv_g9_wait"
    w = wire(_recipe(d, run_view="running"))
    _enter(w, "ready")

    _enter(w, "running")

    _assert_text(w.panel, d, _WAIT)


def test_g9_frame_removes_wait_plate(wire) -> None:
    d = "rv_g9_frame"
    w = wire(_recipe(d, run_view="running"))
    _enter(w, "running")
    _assert_text(w.panel, d, _WAIT)

    _assert_frame_shown(w, d)

    assert _label(w.panel, d).text() == ""
    assert _label(w.panel, d).styleSheet() == ""


def test_g9_second_start_shows_wait_again(wire) -> None:
    d = "rv_g9_again"
    w = wire(_recipe(d, run_view="running"))
    _enter(w, "running")
    _assert_frame_shown(w, d)
    _enter(w, "ready")
    _assert_text(w.panel, d, _IDLE)

    _enter(w, "running")

    _assert_text(w.panel, d, _WAIT)


# ---------------------------------------------------------------------------
# G10, G11: соседние механизмы
# ---------------------------------------------------------------------------


def test_g10_reasons_leaf_keeps_silence_plate_of_always_display(wire) -> None:
    d = "rv_g10"
    w = wire(_recipe(d, run_view="always", plate_mode="silence", plate_after_s=1))
    w.pump.stop()  # тишину сообщаем сами: текст плашки не должен меняться по таймеру
    _enter(w, "ready")
    w.pump._on_silence("sm", 2.0)  # noqa: SLF001
    plate = "Маска · № — · —\nнет кадров, 2 с"
    assert _label(w.panel, d).text() == plate

    w.bindings.leaf("reasons", [{"node": "n", "severity": "failure", "reason": "x"}])
    _spin(0.2)

    assert _label(w.panel, d).text() == plate


def test_g11_recipe_activated_in_ready_shows_idle(wire) -> None:
    d = "rv_g11"
    w = wire(_recipe(d, run_view="running"))
    _enter(w, "ready")
    _assert_text(w.panel, d, _IDLE)

    w.activate_recipe()
    _spin(0.3)

    assert _label(w.panel, d).text() == _IDLE


# ---------------------------------------------------------------------------
# G12, G13: настоящий GuiStateBindings
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("state", "plate"), [("ready", _IDLE), ("running", _WAIT)], ids=["ready", "running"])
def test_g12_late_gui_takes_state_published_before_wiring(wire, state: str, plate: str) -> None:
    d = f"rv_g12_{state}"
    w = wire(
        _recipe(d, run_view="running"),
        real_bindings=True,
        before=lambda bridge: _state_delta(bridge, "state", state),
    )

    _assert_text(w.panel, d, plate)


def test_g13_real_bindings_running_display_hides_frame_in_ready(wire) -> None:
    d = "rv_g13"
    w = wire(_recipe(d, run_view="running"), real_bindings=True)
    _state_delta(w.bridge, "state", "ready")
    _spin(0.05)

    _assert_frame_not_shown(w, d)
    assert _label(w.panel, d).text() == _IDLE
