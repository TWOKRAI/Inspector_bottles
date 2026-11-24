# -*- coding: utf-8 -*-
"""T3 gui-frame-path: sender кадров и id дисплея — РАЗНЫЕ имена (тест автора).

Purpose: тесты слепого tester-а называют дисплеи теми же именами, что sender, и потому не
отличают ключ насоса «sender» от ключа «id дисплея». Здесь рецепт устроен как в жизни:
``displays[].id = "disp_a"``, привязка ``camA.synthetic_frame_source.frame -> disp_a``,
кадры шлёт sender ``camA``. Настоящие ``DataReceiverBridge``, ``_setup_bridge_callbacks``,
``FramePump`` и ``ImagePanelWidget``.

Что проверяется:
- ключ ящика и насоса — sender (``camA``), а не id дисплея;
- ``fps_limit`` ключа берётся из слота дисплея через маршрутизацию (10 Гц у ``disp_a``,
  а не 30 Гц скана для неизвестного ключа);
- кадр доходит до слота ``disp_a`` и не доходит до ``disp_b``.

Запуск (из корня worktree, PYTHONPATH=корень, PYTHONUTF8=1, Qt offscreen), класс ``light``.
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from types import SimpleNamespace
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer  # noqa: E402

__all__: list[str] = []

_LIMIT_A = 10.0  # fps_limit слота disp_a (не 30 — умолчание скана — и не 60)
_LIMIT_B = 40.0


def _recipe() -> dict:
    return {
        "displays": [
            {"id": "disp_a", "name": "A", "enabled": True, "position": {"x": 0, "y": 0}, "fps_limit": _LIMIT_A},
            {"id": "disp_b", "name": "B", "enabled": True, "position": {"x": 10, "y": 0}, "fps_limit": _LIMIT_B},
        ],
        "blueprint": {
            "displays": [
                {"node_id": "camA.synthetic_frame_source.frame", "display_id": "disp_a"},
                {"node_id": "camB.synthetic_frame_source.frame", "display_id": "disp_b"},
            ]
        },
    }


class _RecipeManager:
    def get_active(self) -> str:
        return "sender_vs_display"

    def read_recipe(self, slug: str) -> dict:
        assert slug == "sender_vs_display"
        return _recipe()


def _msg(sender: str, n: int) -> dict:
    frame = np.zeros((48, 64, 3), dtype=np.uint8)
    frame[0, 0, 0] = n
    return {"sender": sender, "frame": frame, "data": {"capture_ns": n, "capture_ts": float(n)}}


def _shown(wiring: SimpleNamespace, key: str) -> int:
    """Счётчик shown насоса по ключу (0, пока насос ключа не знает)."""
    return int(wiring.pump.stats().get(key, {}).get("shown", 0))


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


@pytest.fixture()
def wiring(qtbot):
    from multiprocess_prototype.frontend.app import _setup_bridge_callbacks
    from multiprocess_prototype.frontend.bridge import DataReceiverBridge
    from multiprocess_prototype.frontend.frame_intake import FrameIntake
    from multiprocess_prototype.frontend.widgets.image_panel.widget import ImagePanelWidget

    bridge = DataReceiverBridge()
    panel = ImagePanelWidget(slots=[{"id": "disp_a", "label": "A"}, {"id": "disp_b", "label": "B"}])
    qtbot.addWidget(panel)
    # дублёр GuiProcess несёт то же, что настоящий: FrameIntake (_setup_bridge_callbacks привязывает к нему насос)
    intake = FrameIntake(MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock())
    process = SimpleNamespace(_bridge=bridge, _frame_intake=intake, _log_info=MagicMock(), _log_warning=MagicMock())
    window = MagicMock(name="window")
    _setup_bridge_callbacks(process, panel, window, recipe_manager=_RecipeManager())
    yield SimpleNamespace(bridge=bridge, panel=panel, pump=process._frame_pump, process=process, window=window)
    process._frame_pump.stop()
    QCoreApplication.removePostedEvents(None)


def test_mailbox_key_is_sender_not_display_id(wiring) -> None:
    """Кадр sender ``camA`` лежит в ящике под ключом ``camA``; ключа ``disp_a`` нет."""
    wiring.pump.stop()  # насос не должен снять кадр до проверки ящика
    wiring.bridge.dispatch(_msg("camA", 1))

    assert wiring.bridge.frame_mailbox.pending_keys() == ["camA"]


def test_pump_keys_are_senders(wiring) -> None:
    """После ``_setup_bridge_callbacks`` насос настроен ровно на sender-ов, id дисплеев в ключах нет."""
    assert set(wiring.pump.stats()) == {"camA", "camB"}


def test_frame_reaches_own_slot_only(wiring) -> None:
    """Кадр ``camA`` показан в слоте ``disp_a`` и не показан в ``disp_b`` (и наоборот для ``camB``)."""
    wiring.bridge.dispatch(_msg("camA", 7))
    assert _spin_until(lambda: wiring.panel.grab_frame("disp_a") is not None, 1.0), "кадр camA не дошёл до disp_a"

    assert int(wiring.panel.grab_frame("disp_a")[0, 0, 0]) == 7
    assert wiring.panel.grab_frame("disp_b") is None

    wiring.bridge.dispatch(_msg("camB", 9))
    assert _spin_until(lambda: wiring.panel.grab_frame("disp_b") is not None, 1.0), "кадр camB не дошёл до disp_b"
    assert int(wiring.panel.grab_frame("disp_b")[0, 0, 0]) == 9
    assert int(wiring.panel.grab_frame("disp_a")[0, 0, 0]) == 7


def test_fps_limit_comes_from_display_slot_via_routing(wiring) -> None:
    """Источник ``camA`` 200 Гц, 1.5 с: показано около 10 Гц (предел ``disp_a``), не 30 Гц скана."""
    wiring.bridge.dispatch(_msg("camA", 0))
    assert _spin_until(lambda: _shown(wiring, "camA") >= 1, 1.0), "первый кадр не показан"
    base = _shown(wiring, "camA")
    stop = threading.Event()

    def _produce() -> None:
        n = 1
        t0 = time.perf_counter()
        while not stop.is_set():
            wiring.bridge.dispatch(_msg("camA", n % 250))
            n += 1
            time.sleep(max(0.0, t0 + n / 200.0 - time.perf_counter()))

    producer = threading.Thread(target=_produce, name="camA-producer", daemon=True)
    producer.start()
    _spin_until(lambda: False, 1.5)
    stop.set()
    producer.join(2.0)

    shown = _shown(wiring, "camA") - base
    assert 8 <= shown <= 22, f"показано {shown} за 1.5 с: ожидали ~15 (предел 10 Гц), 30 Гц скана дали бы ~45"
    assert "disp_a" not in wiring.pump.stats()


def test_pump_is_stopped_on_about_to_quit(wiring) -> None:
    """``aboutToQuit`` останавливает насос: кадр после сигнала остаётся в ящике и не показывается."""
    from PySide6.QtWidgets import QApplication

    QApplication.instance().aboutToQuit.emit()
    wiring.bridge.dispatch(_msg("camA", 3))
    _spin_until(lambda: False, 0.4)  # больше периода скана (100 мс) и тика 10 Гц

    assert _shown(wiring, "camA") == 0
    assert wiring.panel.grab_frame("disp_a") is None
    assert wiring.bridge.frame_mailbox.pending_keys() == ["camA"]


def test_capture_ts_reaches_frame_handler_through_pump(wiring) -> None:
    """``data.capture_ts`` доходит до ``_on_frame_received`` через насос: задержка цепочки считается из него.

    Первичный слот — ``disp_a`` (левее ``disp_b``), кадр ``camA`` идёт туда; ``_on_frame_received``
    зовёт ``window.record_chain_latency((now - capture_ts) * 1000)``.
    """
    msg = _msg("camA", 1)
    msg["data"] = {"capture_ns": 5, "capture_ts": time.time() - 5.0}
    wiring.bridge.dispatch(msg)

    assert _spin_until(lambda: wiring.window.record_chain_latency.called, 1.0), "задержка цепочки не посчитана"

    latency_ms = wiring.window.record_chain_latency.call_args.args[0]
    assert 4900.0 <= latency_ms <= 7000.0, f"задержка {latency_ms:.0f} мс, ожидали около 5000 мс"


class _MutableRecipeManager:
    """Двойник recipe_manager с подменяемым рецептом (смена рецепта на живом процессе)."""

    def __init__(self, recipe: dict) -> None:
        self.recipe = recipe

    def get_active(self) -> str:
        return "mutable_recipe"

    def read_recipe(self, slug: str) -> dict:
        return self.recipe


class _EventBus:
    """Двойник event_bus: subscribe сохраняет колбэки, fire() вызывает их как RecipeActivated / DisplaysChanged."""

    def __init__(self) -> None:
        self.callbacks: list[Callable] = []

    def subscribe(self, _event_type: object, callback: Callable) -> None:
        self.callbacks.append(callback)

    def fire(self) -> None:
        for callback in list(self.callbacks):
            callback(None)


def _single_display_recipe(fps_limit: float, *, bound: bool = True) -> dict:
    """Рецепт с одним дисплеем ``disp_a``; ``bound=False`` — sender ``camA`` без привязки."""
    return {
        "displays": [
            {"id": "disp_a", "name": "A", "enabled": True, "position": {"x": 0, "y": 0}, "fps_limit": fps_limit}
        ],
        "blueprint": {
            "displays": [{"node_id": "camA.synthetic_frame_source.frame", "display_id": "disp_a"}] if bound else []
        },
    }


def test_recipe_change_rebuilds_pump_keys_live(qtbot) -> None:
    """Смена рецепта на живом процессе пересобирает ключи насоса: новый предел, тот же таймер, потом скан 30 Гц.

    fps_limit 20 -> 10: период 50 -> 100 мс на ТОМ ЖЕ объекте таймера (фаза не теряется); затем sender
    теряет привязку: насос снимает настроенный ключ, скан находит его заново с периодом 34 мс (30 Гц),
    кадры продолжают показываться.
    """
    from multiprocess_prototype.frontend.app import _setup_bridge_callbacks
    from multiprocess_prototype.frontend.bridge import DataReceiverBridge
    from multiprocess_prototype.frontend.frame_intake import FrameIntake
    from multiprocess_prototype.frontend.widgets.image_panel.widget import ImagePanelWidget

    bridge = DataReceiverBridge()
    panel = ImagePanelWidget(slots=[{"id": "disp_a", "label": "A"}])
    qtbot.addWidget(panel)
    # дублёр GuiProcess несёт то же, что настоящий: FrameIntake (_setup_bridge_callbacks привязывает к нему насос)
    intake = FrameIntake(MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock())
    process = SimpleNamespace(_bridge=bridge, _frame_intake=intake, _log_info=MagicMock(), _log_warning=MagicMock())
    recipes = _MutableRecipeManager(_single_display_recipe(20.0))
    bus = _EventBus()
    _setup_bridge_callbacks(process, panel, MagicMock(name="window"), recipe_manager=recipes, event_bus=bus)
    assert bus.callbacks, "подписки на события дисплеев нет: пересборка при смене рецепта не подключена"
    pump = process._frame_pump
    stop = threading.Event()

    def _produce() -> None:
        n = 0
        t0 = time.perf_counter()
        while not stop.is_set():
            n += 1
            bridge.dispatch(_msg("camA", n % 250))
            time.sleep(max(0.0, t0 + n / 100.0 - time.perf_counter()))  # 100 Гц

    producer = threading.Thread(target=_produce, name="camA-rebuild-producer", daemon=True)
    producer.start()
    try:
        assert _spin_until(lambda: _shown(SimpleNamespace(pump=pump), "camA") >= 3, 1.5), "кадры не показаны"
        timer = pump._timers["camA"]  # noqa: SLF001 — объект таймера ключа: доказать, что он не пересоздан
        assert timer.interval() == 50

        recipes.recipe = _single_display_recipe(10.0)  # fps_limit 20 -> 10
        bus.fire()
        assert pump._timers["camA"] is timer, "таймер пересоздан: потеряна фаза"  # noqa: SLF001
        assert timer.interval() == 100, f"предел не обновился: {timer.interval()} мс"
        shown = _shown(SimpleNamespace(pump=pump), "camA")
        assert _spin_until(lambda: _shown(SimpleNamespace(pump=pump), "camA") > shown, 1.0), "показ остановился"

        recipes.recipe = _single_display_recipe(10.0, bound=False)  # привязка снята -> скан 30 Гц
        bus.fire()
        assert _spin_until(lambda: _shown(SimpleNamespace(pump=pump), "camA") >= 1, 0.5), "кадры не показаны"
        assert pump._timers["camA"].interval() == 34  # noqa: SLF001 — ceil(1000 / 30)
    finally:
        stop.set()
        producer.join(2.0)
        pump.stop()
        QCoreApplication.removePostedEvents(None)
