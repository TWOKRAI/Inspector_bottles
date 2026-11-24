# -*- coding: utf-8 -*-
"""T4 gui-frame-path: проводка метрик и подписей (тесты автора, дополняют слепой файл tester-а).

Purpose: решения брифа T4, которые слепой ``test_frame_intake_metrics.py`` не сторожит:
- ``_update_fps`` (настоящая ``_setup_timers`` с фальшивым ``QTimer``): строка FPS и задержка,
  ``reset_chain_latency()`` ровно один раз на тик, «показано» по слотам дельтами по ключу
  (слот заведён заново: 10 -> 2 даёт 2, не -8);
- привязка насоса к ``FrameIntake`` зовёт ``stats(reset_window=True)`` (окно сбрасывается
  первым вызовом ``get_cycle_metrics``), на настоящих ``FramePump`` и ``FrameIntake``;
- ``qt_pending`` не застревает выше нуля при исключении в колбэке и не уходит в минус;
- единый предикат ``is_frame_message`` для ``dispatch`` и ``FrameIntake``;
- счётчики показа слотов, которых нет в новом наборе дисплеев, убираются.

Запуск (из корня worktree, PYTHONPATH=корень, PYTHONUTF8=1, Qt offscreen), класс ``light``.
"""

from __future__ import annotations

import os
import threading
import time
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402

__all__: list[str] = []

_DEADLINE_S = 5.0


# ---------------------------------------------------------------------------
# _update_fps через настоящую _setup_timers
# ---------------------------------------------------------------------------


class _FakeSignal:
    def __init__(self, sink: list) -> None:
        self._sink = sink

    def connect(self, callback: Any) -> None:
        self._sink.append(callback)


class _FakeTimer:
    """Фальшивый QTimer: запоминает подключённые к timeout обработчики, сам не тикает."""

    connected: list = []

    def __init__(self) -> None:
        self.timeout = _FakeSignal(_FakeTimer.connected)

    def setInterval(self, _ms: int) -> None:  # noqa: N802 — имя Qt
        pass

    def start(self) -> None:
        pass


def _real_intake() -> Any:
    """Настоящий FrameIntake для дублёра GuiProcess (``_setup_bridge_callbacks`` привязывает к нему насос)."""
    from multiprocess_prototype.frontend.frame_intake import FrameIntake

    return FrameIntake(MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock())


def _fps_tick(process: Any, window: Any) -> Any:
    """Собрать настоящую ``_setup_timers`` с фальшивым таймером и вернуть обработчик ``_update_fps``."""
    import multiprocess_prototype.frontend.app as app_mod

    _FakeTimer.connected = []
    with patch.object(app_mod, "QTimer", _FakeTimer):
        app_mod._setup_timers(MagicMock(name="app"), process, window, MagicMock(), MagicMock())
    return _FakeTimer.connected[0]  # первый timeout.connect — fps_timer


def _fps_env(qtbot: Any, shown: dict[str, int]) -> tuple[Any, Any, Any, list]:
    from multiprocess_prototype.frontend.bridge import DataReceiverBridge

    bridge = DataReceiverBridge()
    metrics: list[dict] = []
    bridge.state_updated.connect(metrics.append)
    process = SimpleNamespace(_bridge=bridge, _shown_by_slot=dict(shown))
    window = MagicMock(name="window")
    return process, window, bridge, metrics


def test_update_fps_two_ticks_and_single_latency_reset(qtbot: Any) -> None:
    """Тик 1 и тик 2: литералы строки FPS; ``reset_chain_latency`` зовётся ровно один раз на тик."""
    process, window, bridge, metrics = _fps_env(qtbot, {"main": 12, "mask": 10})
    window.reset_frame_count.return_value = 12
    window.reset_chain_latency.return_value = None
    update = _fps_tick(process, window)
    bridge.frame_mailbox.put("cam", {"frame": 1}, 1)
    bridge.frame_mailbox.put("cam", {"frame": 2}, 1)  # вытеснил первый: superseded 1

    update()
    assert window.update_status.call_args.kwargs == {
        "fps": 12.0,
        "latency_ms": None,
        "shown": 22.0,
        "superseded": 1.0,
        "per_slot": {"main": 12.0, "mask": 10.0},
    }
    assert window.reset_chain_latency.call_count == 1
    assert not [m for m in metrics if m.get("path") == "system.chain_latency_ms"]  # замера нет: не публикуется

    process._shown_by_slot.update(main=15, mask=10)
    window.reset_chain_latency.return_value = 40.0
    update()
    assert window.update_status.call_args.kwargs == {
        "fps": 12.0,
        "latency_ms": 40.0,
        "shown": 3.0,
        "superseded": 0.0,
        "per_slot": {"main": 3.0, "mask": 0.0},
    }
    assert window.reset_chain_latency.call_count == 2  # по одному вызову на тик, не по два
    published = [m["value"] for m in metrics if m.get("path") == "system.chain_latency_ms"]
    assert published == [40.0]  # то же значение, что ушло в надпись


def test_shown_per_tick_is_per_key_delta_not_sum_difference(qtbot: Any) -> None:
    """П.3a: слот 10 -> заведён заново со значением 2: «показано» за тик 2, не -8."""
    process, window, _bridge, _metrics = _fps_env(qtbot, {"main": 10})
    window.reset_frame_count.return_value = 0
    window.reset_chain_latency.return_value = None
    update = _fps_tick(process, window)

    update()
    assert window.update_status.call_args.kwargs["shown"] == 10.0

    process._shown_by_slot.clear()
    process._shown_by_slot["main"] = 2  # слот снят и заведён заново между тиками
    update()
    assert window.update_status.call_args.kwargs["shown"] == 2.0
    assert window.update_status.call_args.kwargs["per_slot"] == {"main": 2.0}

    # слот ушёл на целый тик, затем появился заново: тик без слота 0, потом его значение
    process._shown_by_slot.clear()
    update()
    assert window.update_status.call_args.kwargs["shown"] == 0.0
    process._shown_by_slot["main"] = 2
    update()
    assert window.update_status.call_args.kwargs["shown"] == 2.0


# ---------------------------------------------------------------------------
# Привязка насоса: stats(reset_window=True)
# ---------------------------------------------------------------------------


def test_pump_binding_keeps_peak_in_sliding_window(qapp: Any) -> None:
    """Настоящие FramePump и FrameIntake, часы инжектированы: повторное чтение даёт тот же пик, через 5 с 0.0."""
    from multiprocess_framework.modules.frontend_module.bridge.frame_pump import FramePump
    from multiprocess_framework.modules.process_module.generic.latest_mailbox import LatestMailbox
    from multiprocess_prototype.frontend.app import _attach_pump_metrics
    from multiprocess_prototype.frontend.frame_intake import FrameIntake

    clock = [100.0]
    mailbox = LatestMailbox()
    pump = FramePump(mailbox=mailbox, sink=lambda _key, _item: None)
    intake = FrameIntake(
        MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock(), clock=lambda: clock[0]
    )
    process = SimpleNamespace(_frame_pump=pump, _frame_intake=intake)
    try:
        _attach_pump_metrics(process)
        mailbox.put("cam", {"frame": 1}, 1)
        time.sleep(0.08)  # возраст кадра в ящике не меньше 80 мс
        pump.set_keys({"cam": 60.0})
        deadline = time.perf_counter() + _DEADLINE_S
        while pump.stats()["cam"]["shown"] < 1 and time.perf_counter() < deadline:
            qapp.processEvents()
            time.sleep(0.005)
        assert pump.stats()["cam"]["shown"] == 1

        first = intake.get_cycle_metrics()
        assert pump.stats()["cam"]["window_max_age_ms"] == 0.0  # окно насоса сброшено чтением
        second = intake.get_cycle_metrics()  # второй читатель сразу после первого
        assert first["shown"] == 1
        assert first["max_frame_age_ms"] >= 70.0
        assert second["max_frame_age_ms"] == first["max_frame_age_ms"]  # пик не потерян
        assert second["shown"] == 1  # счётчик показа накопительный

        clock[0] += 4.9
        assert intake.get_cycle_metrics()["max_frame_age_ms"] == first["max_frame_age_ms"]  # окно ещё держит пик
        clock[0] += 0.2  # прошло больше 5 с с момента пика
        assert intake.get_cycle_metrics()["max_frame_age_ms"] == 0.0
    finally:
        pump.stop()


def test_two_readers_both_see_the_peak() -> None:
    """Насос отдаёт окно и сбрасывает его (как stats(reset_window=True)): оба читателя подряд видят 55.0."""
    from multiprocess_prototype.frontend.frame_intake import FrameIntake

    state = {"cam": 55.0}

    def provider() -> dict:
        snapshot = {"cam": {"shown": 3, "window_max_age_ms": state["cam"], "busy_ms_total": 0.0}}
        state["cam"] = 0.0  # reset_window=True
        return snapshot

    clock = [10.0]
    intake = FrameIntake(
        MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock(), clock=lambda: clock[0]
    )
    intake.attach_pump_stats(provider)

    assert intake.get_cycle_metrics()["max_frame_age_ms"] == 55.0  # heartbeat
    assert intake.get_cycle_metrics()["max_frame_age_ms"] == 55.0  # get_status сразу за ним
    clock[0] = 15.0  # ровно 5 с: пик вышел из окна
    assert intake.get_cycle_metrics()["max_frame_age_ms"] == 0.0


def test_concurrent_readers_do_not_break_busy_state() -> None:
    """Несколько потоков зовут get_cycle_metrics при смене набора ключей: ни исключений, ни доли вне [0, 1]."""
    from multiprocess_prototype.frontend.frame_intake import FrameIntake

    counter = {"n": 0}

    def provider() -> dict:
        counter["n"] += 1
        keys = ("a", "b") if counter["n"] % 2 else ("b", "c")  # набор ключей меняется между вызовами
        return {k: {"shown": 1, "window_max_age_ms": 1.0, "busy_ms_total": float(counter["n"])} for k in keys}

    intake = FrameIntake(MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock())
    intake.attach_pump_stats(provider)
    errors: list[BaseException] = []
    shares: list[float] = []

    def reader() -> None:
        try:
            for _ in range(200):
                shares.append(intake.get_cycle_metrics()["pump_busy_share"])
        except BaseException as exc:  # noqa: BLE001 — проверяем именно отсутствие исключений
            errors.append(exc)

    threads = [threading.Thread(target=reader, daemon=True) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(_DEADLINE_S)
    assert not any(t.is_alive() for t in threads)
    assert not errors
    assert all(0.0 <= share <= 1.0 for share in shares)


# ---------------------------------------------------------------------------
# qt_pending: исключение в колбэке, зажим
# ---------------------------------------------------------------------------


@pytest.mark.qt_no_exception_capture
def test_qt_pending_returns_to_zero_when_callback_raises(qapp: Any) -> None:
    """Исключение в state-колбэке не оставляет ``qt_pending`` выше нуля (try/finally в ``_on_deliver``)."""
    from multiprocess_prototype.frontend.bridge import DataReceiverBridge

    bridge = DataReceiverBridge()
    seen: list[dict] = []

    def _boom(msg: dict) -> None:
        seen.append(msg)
        raise RuntimeError("колбэк упал")

    bridge.set_state_callback(_boom)

    def _send() -> None:
        for i in range(3):
            bridge.dispatch({"data_type": "state_delta", "path": f"a.{i}", "value": i})

    sender = threading.Thread(target=_send, daemon=True)
    sender.start()
    sender.join(_DEADLINE_S)
    assert not sender.is_alive()
    assert bridge.qt_pending == 3

    deadline = time.perf_counter() + _DEADLINE_S
    while len(seen) < 3 and time.perf_counter() < deadline:
        qapp.processEvents()
        time.sleep(0.005)

    assert len(seen) == 3
    assert bridge.qt_pending == 0


def test_qt_pending_never_negative(qapp: Any) -> None:
    """Обработано больше, чем передано (гонка чтения двух счётчиков): ``qt_pending`` не уходит в минус."""
    from multiprocess_prototype.frontend.bridge import DataReceiverBridge

    bridge = DataReceiverBridge()
    bridge._on_deliver(("state", {"data_type": "state_delta"}))  # handled 1 при emitted 0
    assert bridge.qt_pending == 0


# ---------------------------------------------------------------------------
# Единый предикат кадра
# ---------------------------------------------------------------------------


def _frames_counted_by_intake(msg: dict) -> int:
    from multiprocess_prototype.frontend.frame_intake import FrameIntake

    stop = threading.Event()
    calls = [0]

    def receive(**_kwargs: Any) -> list[dict]:
        calls[0] += 1
        if calls[0] == 1:
            return [msg]
        stop.set()
        return []

    intake = FrameIntake(
        receive, MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock(), sleep=lambda _s: None
    )
    thread = threading.Thread(target=intake.run_loop, args=(stop, threading.Event()), daemon=True)
    thread.start()
    thread.join(_DEADLINE_S)
    assert not thread.is_alive()
    return int(intake.get_cycle_metrics()["frames_in"])


@pytest.mark.parametrize(
    ("msg", "is_frame"),
    [
        ({"data_type": "frame_ready", "sender": "cam"}, True),
        ({"data_type": "frame", "sender": "cam"}, True),
        ({"sender": "cam", "frame": np.zeros((2, 2, 3), dtype=np.uint8)}, True),
        ({"data_type": "status"}, False),
        ({"sender": "cam", "data": {"x": 1}}, False),
    ],
)
def test_dispatch_and_intake_agree_on_what_is_a_frame(qapp: Any, msg: dict, is_frame: bool) -> None:
    """Одно и то же сообщение: ящик ``dispatch`` и счётчик ``frames_in`` согласны, кадр это или нет."""
    from multiprocess_prototype.frontend.bridge import DataReceiverBridge

    bridge = DataReceiverBridge()
    bridge.dispatch(msg)
    in_mailbox = bridge.frame_mailbox.stats()["put"]

    assert in_mailbox == (1 if is_frame else 0)
    assert _frames_counted_by_intake(msg) == (1 if is_frame else 0)


# ---------------------------------------------------------------------------
# Счётчики показа слотов следуют за набором дисплеев
# ---------------------------------------------------------------------------


def _recipe(ids: list[str]) -> dict:
    return {
        "displays": [
            {"id": i, "name": i, "enabled": True, "position": {"x": n * 10, "y": 0}, "fps_limit": 10.0}
            for n, i in enumerate(ids)
        ],
        "blueprint": {"displays": []},
    }


def test_shown_counters_of_removed_slots_are_dropped(qtbot: Any) -> None:
    """Пересборка дисплеев убирает счётчики слотов, которых нет в новом наборе."""
    from multiprocess_prototype.frontend.app import _setup_bridge_callbacks
    from multiprocess_prototype.frontend.bridge import DataReceiverBridge
    from multiprocess_prototype.frontend.widgets.image_panel.widget import ImagePanelWidget

    current = {"ids": ["disp_a", "disp_b"]}

    class _Recipes:
        def get_active(self) -> str:
            return "r"

        def read_recipe(self, _slug: str) -> dict:
            return _recipe(current["ids"])

    subscribers: list = []
    event_bus = SimpleNamespace(subscribe=lambda _event, callback: subscribers.append(callback))
    bridge = DataReceiverBridge()
    panel = ImagePanelWidget(slots=[{"id": "disp_a", "label": "A"}, {"id": "disp_b", "label": "B"}])
    qtbot.addWidget(panel)
    process = SimpleNamespace(
        _bridge=bridge, _frame_intake=_real_intake(), _log_info=MagicMock(), _log_warning=MagicMock()
    )
    _setup_bridge_callbacks(process, panel, MagicMock(), recipe_manager=_Recipes(), event_bus=event_bus)
    try:
        assert subscribers, "подписка на пересборку дисплеев не сделана"
        process._shown_by_slot.update({"disp_a": 3, "disp_b": 4, "old_slot": 5})

        current["ids"] = ["disp_a"]
        subscribers[0](None)  # RecipeActivated

        assert process._shown_by_slot == {"disp_a": 3}
    finally:
        process._frame_pump.stop()


# ---------------------------------------------------------------------------
# Перезапуск UI: база вытеснения
# ---------------------------------------------------------------------------


def test_superseded_base_is_current_value_after_ui_restart(qtbot: Any) -> None:
    """Ящик пережил прошлый проход UI с накопленным вытеснением: первый тик нового замыкания даёт 0.0."""
    process, window, bridge, _metrics = _fps_env(qtbot, {"main": 5})
    for i in range(100):  # 99 вытеснено до создания нового замыкания _setup_timers
        bridge.frame_mailbox.put("cam", {"frame": i}, 1)
    window.reset_frame_count.return_value = 0
    window.reset_chain_latency.return_value = None
    update = _fps_tick(process, window)

    update()
    assert window.update_status.call_args.kwargs["superseded"] == 0.0

    bridge.frame_mailbox.put("cam", {"frame": 100}, 1)  # ещё одно вытеснение уже в новом проходе
    update()
    assert window.update_status.call_args.kwargs["superseded"] == 1.0


# ---------------------------------------------------------------------------
# Проводка _setup_bridge_callbacks: счёт показа, задержка, насос, резерв main
# ---------------------------------------------------------------------------


def _wired_process(qtbot: Any, window: Any, current: dict) -> tuple[Any, list]:
    """Настоящая ``_setup_bridge_callbacks``; набор дисплеев берётся из ``current["ids"]`` при каждой пересборке."""
    from multiprocess_prototype.frontend.app import _setup_bridge_callbacks
    from multiprocess_prototype.frontend.bridge import DataReceiverBridge
    from multiprocess_prototype.frontend.widgets.image_panel.widget import ImagePanelWidget

    class _Recipes:
        def get_active(self) -> str:
            return "r"

        def read_recipe(self, _slug: str) -> dict:
            return _recipe(current["ids"])

    bridge = DataReceiverBridge()
    panel = ImagePanelWidget(slots=[{"id": i, "label": i} for i in current["ids"]])
    qtbot.addWidget(panel)
    process = SimpleNamespace(
        _bridge=bridge, _frame_intake=_real_intake(), _log_info=MagicMock(), _log_warning=MagicMock()
    )
    subscribers: list = []
    event_bus = SimpleNamespace(subscribe=lambda _event, callback: subscribers.append(callback))
    _setup_bridge_callbacks(process, panel, window, recipe_manager=_Recipes(), event_bus=event_bus)
    return process, subscribers


def test_on_frame_counts_shown_and_replay_gives_no_latency_sample(qtbot: Any) -> None:
    """Кадр считается показанным в своём слоте; replay показан, но задержку не пишет."""
    window = MagicMock(name="window")
    process, _subs = _wired_process(qtbot, window, {"ids": ["main"]})
    try:
        frame = np.zeros((4, 4, 3), dtype=np.uint8)
        now = time.time()
        process._bridge._frame_cb({"sender": "x", "frame": frame, "data": {"capture_ts": now - 0.5}})
        assert process._shown_by_slot == {"main": 1}
        assert window.record_chain_latency.call_count == 1
        assert 400.0 < window.record_chain_latency.call_args[0][0] < 900.0

        process._bridge._frame_cb({"sender": "x", "frame": frame, "replay": True, "data": {"capture_ts": now - 0.5}})
        assert process._shown_by_slot == {"main": 2}  # replay показан ...
        assert window.record_chain_latency.call_count == 1  # ... но сэмпла задержки не даёт
    finally:
        process._frame_pump.stop()


def test_wiring_attaches_pump_metrics_at_pump_creation(qtbot: Any) -> None:
    """_setup_bridge_callbacks сам привязывает насос к FrameIntake процесса (run_gui ничего не добавляет)."""
    from PySide6.QtCore import QCoreApplication

    from multiprocess_prototype.frontend.app import _setup_bridge_callbacks
    from multiprocess_prototype.frontend.bridge import DataReceiverBridge
    from multiprocess_prototype.frontend.frame_intake import FrameIntake
    from multiprocess_prototype.frontend.widgets.image_panel.widget import ImagePanelWidget

    bridge = DataReceiverBridge()
    panel = ImagePanelWidget(slots=[{"id": "main", "label": "M"}])
    qtbot.addWidget(panel)
    intake = FrameIntake(MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock())
    process = SimpleNamespace(_bridge=bridge, _frame_intake=intake, _log_info=MagicMock(), _log_warning=MagicMock())
    _setup_bridge_callbacks(process, panel, MagicMock(), recipe_manager=None)
    try:
        bridge.frame_mailbox.put("cam", {"frame": 1}, 1)
        deadline = time.perf_counter() + _DEADLINE_S
        while intake.get_cycle_metrics()["shown"] < 1 and time.perf_counter() < deadline:
            QCoreApplication.processEvents()
            time.sleep(0.005)
        assert intake.get_cycle_metrics()["shown"] == 1  # насос привязан: shown виден
    finally:
        process._frame_pump.stop()


def test_main_slot_survives_rebuild_without_enabled_displays(qtbot: Any) -> None:
    """Набор без включённых дисплеев: кадры идут в слот main, его счётчик пересборка не убирает."""
    current = {"ids": ["disp_a"]}
    process, subscribers = _wired_process(qtbot, MagicMock(name="window"), current)
    try:
        process._shown_by_slot.update({"main": 4, "disp_a": 3})
        current["ids"] = []  # рецепт без дисплеев
        subscribers[0](None)
        assert process._shown_by_slot == {"main": 4}  # disp_a ушёл, резерв main остался
    finally:
        process._frame_pump.stop()


# ---------------------------------------------------------------------------
# Надписи и цикл: мелкие стражи
# ---------------------------------------------------------------------------


def test_update_status_without_per_slot_has_no_breakdown(qtbot: Any) -> None:
    """shown и superseded без per_slot: строка без разбивки по слотам и без пустых скобок."""
    from multiprocess_prototype.frontend.windows.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    window.update_status(fps=1.0, latency_ms=None, shown=3.0, superseded=1.0)
    assert window._fps_label.text() == "FPS: показано 3.0/с, вытеснено 1.0/с"


def test_fps_text_without_slots_has_no_parentheses() -> None:
    from multiprocess_prototype.frontend.frame_intake import fps_text

    assert fps_text(3.0, 1.0, {}) == "FPS: показано 3.0/с, вытеснено 1.0/с"


def test_paused_loop_does_not_receive() -> None:
    """Пауза: run_loop не зовёт receive, а ждёт 0.05 с; после stop выходит."""
    from multiprocess_prototype.frontend.frame_intake import FrameIntake

    stop, pause = threading.Event(), threading.Event()
    pause.set()
    sleeps: list[float] = []

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        if len(sleeps) >= 3:
            stop.set()

    receive = MagicMock(return_value=[])
    intake = FrameIntake(receive, MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock(), sleep=fake_sleep)
    thread = threading.Thread(target=intake.run_loop, args=(stop, pause), daemon=True)
    thread.start()
    thread.join(_DEADLINE_S)
    assert not thread.is_alive()
    assert receive.call_count == 0
    assert sleeps == [0.05, 0.05, 0.05]


# ---------------------------------------------------------------------------
# qt_pending: несколько отправителей
# ---------------------------------------------------------------------------


def test_qt_pending_counts_all_senders(qapp: Any) -> None:
    """4 потока по 25 дельт: до обработки qt_pending 100, после 0 (проверяется итоговый счёт, не гонка)."""
    from multiprocess_prototype.frontend.bridge import DataReceiverBridge

    bridge = DataReceiverBridge()
    handled: list[dict] = []
    bridge.state_updated.connect(handled.append)

    def send(base: int) -> None:
        for i in range(25):
            bridge.dispatch({"data_type": "state_delta", "path": f"s{base}.{i}", "value": i})

    threads = [threading.Thread(target=send, args=(n,), daemon=True) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(_DEADLINE_S)
    assert not any(t.is_alive() for t in threads)
    assert bridge.qt_pending == 100

    deadline = time.perf_counter() + _DEADLINE_S
    while len(handled) < 100 and time.perf_counter() < deadline:
        qapp.processEvents()
        time.sleep(0.005)
    assert len(handled) == 100
    assert bridge.qt_pending == 0


# ---------------------------------------------------------------------------
# Насосные метрики: замок читателей и интервал доли занятости
# ---------------------------------------------------------------------------


def test_readers_of_pump_metrics_are_serialized() -> None:
    """Пока первый читатель внутри провайдера, второй ждёт замок FrameIntake (состояние базы не делится)."""
    from multiprocess_prototype.frontend.frame_intake import FrameIntake

    entered = [0]
    first_in = threading.Event()
    release = threading.Event()

    def provider() -> dict:
        entered[0] += 1
        if entered[0] == 1:
            first_in.set()
            release.wait(_DEADLINE_S)
        return {"cam": {"shown": 1, "window_max_age_ms": 0.0, "busy_ms_total": 0.0}}

    intake = FrameIntake(MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock())
    intake.attach_pump_stats(provider)
    first = threading.Thread(target=intake.get_cycle_metrics, daemon=True)
    second = threading.Thread(target=intake.get_cycle_metrics, daemon=True)
    first.start()
    assert first_in.wait(_DEADLINE_S)
    second.start()
    time.sleep(0.1)
    assert entered[0] == 1  # второй читатель ещё не вошёл в провайдер
    release.set()
    first.join(_DEADLINE_S)
    second.join(_DEADLINE_S)
    assert entered[0] == 2
    assert not first.is_alive()
    assert not second.is_alive()


def test_busy_share_uses_real_interval(monkeypatch: pytest.MonkeyPatch) -> None:
    """Интервал между вызовами берётся из часов, не 1 с: 400 мс занятости за 2.0 с дают 0.2."""
    import multiprocess_prototype.frontend.frame_intake as frame_intake

    clock = [50.0]
    monkeypatch.setattr(
        frame_intake,
        "time",
        SimpleNamespace(perf_counter=lambda: clock[0], monotonic=lambda: clock[0], sleep=lambda _s: None),
    )
    busy = {"main": {"shown": 0, "window_max_age_ms": 0.0, "busy_ms_total": 0.0}}
    intake = frame_intake.FrameIntake(MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock())
    intake.attach_pump_stats(lambda: {k: dict(v) for k, v in busy.items()})

    assert intake.get_cycle_metrics()["pump_busy_share"] == 0.0
    clock[0] = 52.0
    busy["main"]["busy_ms_total"] = 400.0
    assert intake.get_cycle_metrics()["pump_busy_share"] == pytest.approx(0.2)


def test_peak_arriving_after_first_read_enters_window() -> None:
    """Пик 80 приходит МЕЖДУ чтениями: попадает в окно, держится до 5 с, на границе 5.0 с уходит."""
    from multiprocess_prototype.frontend.frame_intake import FrameIntake

    state = {"cam": 0.0}

    def provider() -> dict:
        snapshot = {"cam": {"shown": 1, "window_max_age_ms": state["cam"], "busy_ms_total": 0.0}}
        state["cam"] = 0.0  # reset_window=True
        return snapshot

    clock = [100.0]
    intake = FrameIntake(
        MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock(), clock=lambda: clock[0]
    )
    intake.attach_pump_stats(provider)

    assert intake.get_cycle_metrics()["max_frame_age_ms"] == 0.0  # первое чтение: пика нет
    state["cam"] = 80.0  # пик между чтениями
    clock[0] = 101.0
    assert intake.get_cycle_metrics()["max_frame_age_ms"] == 80.0
    clock[0] = 105.9  # 4.9 с после записи пика
    assert intake.get_cycle_metrics()["max_frame_age_ms"] == 80.0
    clock[0] = 106.0  # ровно 5.0 с: запись вышла из окна
    assert intake.get_cycle_metrics()["max_frame_age_ms"] == 0.0
