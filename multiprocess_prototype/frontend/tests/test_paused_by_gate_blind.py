# -*- coding: utf-8 -*-
"""Слепые приёмочные тесты 2.11, часть B (GUI): метка ``paused_by`` и display ``run_view``, G1-G4, G6.

Написаны по задаче 2.11 (DESIGN, REDS) до реализации. Проводка — как в ``test_run_view_gate_blind.py``:
настоящие ``_setup_bridge_callbacks``, ``DataReceiverBridge``, ``FramePump`` и ``ImagePanelWidget``;
рецепт — словарь; ``bindings`` — двойник ``bind_fanout(pattern, callback, owner)``.

«Маска» — display ``run_view: running`` (отправитель ``sm``), «Кадр» — ``run_view: always`` (``sc``).
Ожидаемые тексты — литералы. «Кадр не показан» проверяется только после того, как «Кадр» той же
проводки свой кадр показал.

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

_WAIT = "Маска\nРаботает: ждём первый обработанный кадр"
_MASK = "pb_mask"  # display run_view: running
_FRAME = "pb_frame"  # display run_view: always

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


def _msg(sender: str, data: dict) -> dict:
    return {"sender": sender, "frame": np.full((48, 64, 3), 200, dtype=np.uint8), "data": dict(data)}


def _data(shape: str, **keys: Any) -> dict:
    """``bare`` — ровно названные ключи (как в REDS); ``stamped`` — плюс свежий ``capture_ts`` боевого кадра."""
    if shape == "stamped":
        return {"capture_ts": time.time(), **keys}
    return dict(keys)


def _recipe() -> dict:
    def _display(ident: str, name: str, x: int, run_view: str) -> dict:
        return {
            "id": ident,
            "name": name,
            "enabled": True,
            "position": {"x": x, "y": 0},
            "fps_limit": 30.0,
            "run_view": run_view,
        }

    return {
        "displays": [_display(_MASK, "Маска", 0, "running"), _display(_FRAME, "Кадр", 10, "always")],
        "blueprint": {
            "displays": [
                {"node_id": "sm.src.frame", "display_id": _MASK},
                {"node_id": "sc.src.frame", "display_id": _FRAME},
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


@pytest.fixture()
def wire(qtbot):
    """Настоящие мост, насос и панель с рецептом «Маска» + «Кадр»."""
    from multiprocess_prototype.frontend import app as app_module
    from multiprocess_prototype.frontend.bridge import DataReceiverBridge
    from multiprocess_prototype.frontend.frame_intake import FrameIntake
    from multiprocess_prototype.frontend.widgets.image_panel.widget import ImagePanelWidget

    class _Recipes:
        def get_active(self) -> str:
            return "paused_by_blind"

        def read_recipe(self, _slug: str) -> dict:
            return _recipe()

    bus = SimpleNamespace(subscribe=lambda event, callback: None)
    bridge = DataReceiverBridge()
    panel = ImagePanelWidget()
    qtbot.addWidget(panel)
    intake = FrameIntake(MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock())
    process = SimpleNamespace(_bridge=bridge, _frame_intake=intake, _log_info=MagicMock(), _log_warning=MagicMock())
    bindings = _Bindings()
    app_module._setup_bridge_callbacks(
        process, panel, MagicMock(name="window"), recipe_manager=_Recipes(), event_bus=bus, bindings=bindings
    )

    yield SimpleNamespace(bridge=bridge, panel=panel, bindings=bindings)

    process._frame_pump.stop()
    QCoreApplication.removePostedEvents(None)


def _label(panel: Any, slot_id: str) -> QLabel:
    return panel._slots[slot_id].findChild(QLabel, "DisplaySlotLabel")  # noqa: SLF001


def _shown(panel: Any, slot_id: str) -> int:
    return panel.presenter.frame_stats(slot_id)["shown"]


def _enter_running(w: SimpleNamespace) -> None:
    w.bindings.leaf("state", "running")
    _spin(0.05)  # шаг time.time() на Windows ~16 мс: capture_ts следующего кадра строго позже входа


def _assert_frame_shown(w: SimpleNamespace, sender: str, slot_id: str, data: dict) -> None:
    before = _shown(w.panel, slot_id)
    w.bridge.dispatch(_msg(sender, data))
    assert _spin_until(lambda: _shown(w.panel, slot_id) > before, 1.0), (
        f"кадр не показан, на экране: {_label(w.panel, slot_id).text()!r}"
    )
    _spin(0.2)
    assert not _label(w.panel, slot_id).pixmap().isNull(), (
        f"кадр на экране не удержался: {_label(w.panel, slot_id).text()!r}"
    )


# ---------------------------------------------------------------------------
# G1, G2: «Маска» в running
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("shape", ["bare", "stamped"])
def test_g1_running_display_hides_marked_frame_and_keeps_wait_plate(wire, shape: str) -> None:
    _enter_running(wire)
    assert _spin_until(lambda: _label(wire.panel, _MASK).text() == _WAIT, 1.0), "предусловие: плашка ожидания"

    wire.bridge.dispatch(_msg("sm", _data(shape, paused_by="p1")))
    wire.bridge.dispatch(_msg("sc", _data(shape)))
    assert _spin_until(lambda: _shown(wire.panel, _FRAME) >= 1, 1.0), "контрольный экран кадр не показал"
    _spin(0.3)  # период насоса при 30 Гц — 33 мс

    assert _shown(wire.panel, _MASK) == 0, "кадр с меткой показан"
    assert _label(wire.panel, _MASK).pixmap().isNull(), "на экране картинка"
    assert _label(wire.panel, _MASK).text() == _WAIT


@pytest.mark.parametrize("shape", ["bare", "stamped"])
def test_g2_running_display_shows_unmarked_frame(wire, shape: str) -> None:
    """Контроль."""
    _enter_running(wire)

    _assert_frame_shown(wire, "sm", _MASK, _data(shape))


# ---------------------------------------------------------------------------
# G3, G4, G6: кому метка не мешает
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("shape", ["bare", "stamped"])
def test_g3_always_display_shows_marked_frame_in_running(wire, shape: str) -> None:
    """Контроль."""
    _enter_running(wire)

    _assert_frame_shown(wire, "sc", _FRAME, _data(shape, paused_by="p1"))


@pytest.mark.parametrize("state", ["running", "ready"])
def test_g4_gate_off_shows_marked_frame(wire, state: str) -> None:
    """Контроль."""
    wire.bindings.leaf("run_gate", False)
    wire.bindings.leaf("state", state)
    _spin(0.05)

    _assert_frame_shown(wire, "sm", _MASK, _data("stamped", paused_by="p1"))


@pytest.mark.parametrize("value", ["", 1], ids=["empty_string", "int_one"])
def test_g6_mark_is_only_a_non_empty_string(wire, value: Any) -> None:
    """Контроль."""
    _enter_running(wire)

    _assert_frame_shown(wire, "sm", _MASK, _data("stamped", paused_by=value))
