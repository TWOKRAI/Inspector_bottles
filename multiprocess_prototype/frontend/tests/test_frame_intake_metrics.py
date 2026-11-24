# -*- coding: utf-8 -*-
"""T4 gui-frame-path: слепая приёмка метрик и подписей тракта кадров.

Purpose: контракт ``FrameIntake.get_cycle_metrics`` (ровно 10 ключей: счётчики входа,
вытеснение и память ящика, показ и возраст кадра насоса, доля занятости насоса, очередь Qt),
функций ``latency_sample`` / ``fps_text`` и подписей ``MainWindow.update_status``.

Тесты написаны вслепую (до кода) по контракту из брифа T4; ожидаемые значения здесь
литералы, не вычислены из кода под тестом. Импорты ``FrameIntake``, ``latency_sample``,
``fps_text`` и модуля ``frame_intake`` стоят ВНУТРИ тестов: до появления кода каждый тест
краснеет поведением (``ImportError`` внутри теста), а не ошибкой сбора. Цикл
``FrameIntake.run_loop`` и отправители в Qt-тестах идут в демон-потоках с join по дедлайну.

Запуск (из корня worktree, PYTHONPATH=корень, PYTHONUTF8=1, Qt offscreen):
    bash ../../../scripts/machine_gate.sh light inspector-bottles-K \
        ../../../.venv/Scripts/python.exe -m pytest -q --tb=short -p no:cacheprovider \
        multiprocess_prototype/frontend/tests/test_frame_intake_metrics.py
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from PySide6.QtCore import QObject  # noqa: E402

__all__: list[str] = []

# ---------------------------------------------------------------------------
# Литералы приёмки (из брифа T4, не из кода)
# ---------------------------------------------------------------------------

_METRIC_KEYS = {
    "frames_in",
    "batches",
    "superseded",
    "pending",
    "bytes_held",
    "max_bytes_held",
    "shown",
    "max_frame_age_ms",
    "pump_busy_share",
    "qt_pending",
}
_FRAME_BYTES = 1440 * 1080 * 3  # 4 665 600
_DEADLINE_S = 5.0
_RECEIVE_KWARGS = {"timeout": 0.1, "channel_types": ["data"], "return_messages": False}

# ---------------------------------------------------------------------------
# Помощники
# ---------------------------------------------------------------------------


def _frame_msg(sender: str = "cam0") -> dict:
    """Малое сообщение-кадр (содержимое кадра в метриках не участвует)."""
    return {
        "sender": sender,
        "frame": np.zeros((2, 2, 3), dtype=np.uint8),
        "data": {"capture_ns": 1_000_000_000, "capture_ts": 1.0},
    }


def _big_frame_msg(sender: str = "cam0") -> dict:
    """Сообщение-кадр 1440x1080x3 (4 665 600 байт); np.zeros выделяет страницы лениво."""
    return {
        "sender": sender,
        "frame": np.zeros((1080, 1440, 3), dtype=np.uint8),
        "data": {"capture_ns": 1_000_000_000, "capture_ts": 1.0},
    }


class _Receiver:
    """Двойник ``receive``: отдаёт заданные пачки по очереди, затем пустые списки.

    Элемент ``batches`` — готовый список сообщений или функция без аргументов, строящая его
    лениво (чтобы большие кадры не жили все сразу). ``settled`` взводится после трёх пустых
    ответов подряд: к этому моменту все пачки обработаны и счётчики обновлены.
    """

    def __init__(self, batches: list[list[dict] | Callable[[], list[dict]]]) -> None:
        self._batches = list(batches)
        self.calls: list[tuple[tuple, dict]] = []
        self._empty_calls = 0
        self.settled = threading.Event()

    def __call__(self, *args: Any, **kwargs: Any) -> list[dict]:
        self.calls.append((args, kwargs))
        if self._batches:
            nxt = self._batches.pop(0)
            return nxt() if callable(nxt) else nxt
        self._empty_calls += 1
        if self._empty_calls >= 3:
            self.settled.set()
        return []


def _make_intake(receive: Callable[..., list[dict]], put: Callable[[dict], Any] | None = None) -> Any:
    """Настоящий ``FrameIntake`` с двойниками логов/метрик; ``sleep`` короткий, чтобы цикл не «горел»."""
    from multiprocess_prototype.frontend.frame_intake import FrameIntake

    return FrameIntake(
        receive,
        put if put is not None else MagicMock(name="put"),
        MagicMock(name="log_info"),
        MagicMock(name="log_critical"),
        MagicMock(name="track_error"),
        MagicMock(name="record_metric"),
        sleep=lambda _s: time.sleep(0.001),
    )


def _drive(intake: Any, receiver: _Receiver) -> None:
    """Прогнать ``run_loop`` в демон-потоке, пока ``receiver`` не опустеет; остановить, дождаться выхода."""
    stop = threading.Event()
    pause = threading.Event()
    thread = threading.Thread(target=intake.run_loop, args=(stop, pause), name="intake-loop", daemon=True)
    thread.start()
    settled = receiver.settled.wait(_DEADLINE_S)
    stop.set()
    thread.join(_DEADLINE_S)
    assert settled, "receive не дошёл до пустых ответов за 5 с (цикл не работает или упал)"
    assert not thread.is_alive(), "run_loop не вышел за 5 с после stop_event"


def _pump_entry(
    shown: int = 0,
    max_age_ms: float = 0.0,
    busy_ms_total: float = 0.0,
    errors: int = 0,
    window_max_age_ms: float = 0.0,
) -> dict:
    """Счётчики насоса одного ключа (пять полей контракта)."""
    return {
        "shown": shown,
        "max_age_ms": max_age_ms,
        "busy_ms_total": busy_ms_total,
        "errors": errors,
        "window_max_age_ms": window_max_age_ms,
    }


# ---------------------------------------------------------------------------
# Метрики FrameIntake
# ---------------------------------------------------------------------------


def test_metrics_have_literal_keys() -> None:
    """get_cycle_metrics отдаёт ровно 10 ключей, с провайдерами и без."""
    intake = _make_intake(_Receiver([]))

    bare = intake.get_cycle_metrics()
    assert set(bare) == _METRIC_KEYS
    assert len(bare) == 10

    intake.attach_pump_stats(lambda: {"main": _pump_entry(shown=1)})
    intake.attach_mailbox_stats(lambda: {"pending": 0})
    intake.attach_qt_pending(lambda: 0)
    full = intake.get_cycle_metrics()
    assert set(full) == _METRIC_KEYS
    assert len(full) == 10


def test_frames_in_counts_messages_not_batches() -> None:
    """7 сообщений-кадров в одной пачке: frames_in 7, batches 1; пустой receive и не-кадр не считаются кадром."""
    # случай 1: пачка из 7 кадров, затем пустые ответы
    put_a = MagicMock(name="put_a")
    receiver_a = _Receiver([[_frame_msg() for _ in range(7)]])
    intake_a = _make_intake(receiver_a, put_a)
    _drive(intake_a, receiver_a)
    metrics_a = intake_a.get_cycle_metrics()
    assert metrics_a["frames_in"] == 7
    assert metrics_a["batches"] == 1
    assert put_a.call_count == 7
    first_args, first_kwargs = receiver_a.calls[0]
    assert first_args == ()
    assert first_kwargs == _RECEIVE_KWARGS

    # случай 2: пачка из одного не-кадра: put получил его, кадров нет, пачка непустая
    put_b = MagicMock(name="put_b")
    receiver_b = _Receiver([[{"data_type": "status"}]])
    intake_b = _make_intake(receiver_b, put_b)
    _drive(intake_b, receiver_b)
    metrics_b = intake_b.get_cycle_metrics()
    assert metrics_b["frames_in"] == 0
    assert metrics_b["batches"] == 1
    assert put_b.call_count == 1

    # случай 3: только пустые ответы: ни пачек, ни кадров
    put_c = MagicMock(name="put_c")
    receiver_c = _Receiver([])
    intake_c = _make_intake(receiver_c, put_c)
    _drive(intake_c, receiver_c)
    metrics_c = intake_c.get_cycle_metrics()
    assert metrics_c["frames_in"] == 0
    assert metrics_c["batches"] == 0
    assert put_c.call_count == 0


def test_pump_metrics_aggregation_and_zero_before_attach() -> None:
    """До привязки насоса три метрики 0; после: shown суммируется (15), возраст берётся максимумом (70.0, не 110.0)."""
    intake = _make_intake(_Receiver([]))

    before = intake.get_cycle_metrics()
    assert before["shown"] == 0
    assert before["pump_busy_share"] == 0.0
    assert before["max_frame_age_ms"] == 0

    # max_age_ms (накопительный пик) нарочно больше window_max_age_ms: берётся именно окно
    intake.attach_pump_stats(
        lambda: {
            "main": _pump_entry(shown=10, max_age_ms=900.0, window_max_age_ms=40.0),
            "mask": _pump_entry(shown=5, max_age_ms=800.0, window_max_age_ms=70.0),
        }
    )
    after = intake.get_cycle_metrics()
    assert after["shown"] == 15
    assert after["max_frame_age_ms"] == 70.0
    assert after["max_frame_age_ms"] != 110.0


def test_pump_busy_share_clamped_delta(monkeypatch: pytest.MonkeyPatch) -> None:
    """pump_busy_share: дельта busy_ms_total по ключам / интервал в мс, зажим, минус на ключ -> 0, база."""
    import multiprocess_prototype.frontend.frame_intake as frame_intake

    clock = [10.0]
    fake_time = SimpleNamespace(
        perf_counter=lambda: clock[0],
        monotonic=lambda: clock[0],
        sleep=lambda _s: None,
    )
    monkeypatch.setattr(frame_intake, "time", fake_time)

    state: dict[str, dict] = {}
    intake = _make_intake(_Receiver([]))
    intake.attach_pump_stats(lambda: {k: dict(v) for k, v in state.items()})

    # первый вызов: база берётся, доля 0.0
    state.update({"main": _pump_entry(busy_ms_total=0.0)})
    assert intake.get_cycle_metrics()["pump_busy_share"] == 0.0

    # интервал 1.0 с, busy_ms_total 0 -> 400.0: доля 0.4
    clock[0] = 11.0
    state.update({"main": _pump_entry(busy_ms_total=400.0)})
    assert intake.get_cycle_metrics()["pump_busy_share"] == pytest.approx(0.4)

    # дельта 2000.0 за 1.0 с: зажим до 1.0
    clock[0] = 12.0
    state.update({"main": _pump_entry(busy_ms_total=2400.0)})
    assert intake.get_cycle_metrics()["pump_busy_share"] == 1.0

    # main ушёл, появились a (300.0) и b (0.0): новые ключи в этом вызове дают 0.0
    clock[0] = 13.0
    state.clear()
    state.update({"a": _pump_entry(busy_ms_total=300.0), "b": _pump_entry(busy_ms_total=0.0)})
    assert intake.get_cycle_metrics()["pump_busy_share"] == 0.0

    # a ушёл (300.0 -> нет), b 0 -> 200.0: доля 0.2 (не 0.0 и не по разности сумм 200 - 300)
    clock[0] = 14.0
    state.clear()
    state.update({"b": _pump_entry(busy_ms_total=200.0)})
    assert intake.get_cycle_metrics()["pump_busy_share"] == pytest.approx(0.2)

    # b 200.0 -> 100.0 (минус считается 0), c появился (0.0): доля 0.0
    clock[0] = 15.0
    state.update({"b": _pump_entry(busy_ms_total=100.0), "c": _pump_entry(busy_ms_total=0.0)})
    assert intake.get_cycle_metrics()["pump_busy_share"] == 0.0

    # b 100.0 -> 50.0 (минус -> 0), c 0 -> 300.0 (+300): доля 0.3 (по сумме было бы 250 -> 0.25)
    clock[0] = 16.0
    state.update({"b": _pump_entry(busy_ms_total=50.0), "c": _pump_entry(busy_ms_total=300.0)})
    assert intake.get_cycle_metrics()["pump_busy_share"] == pytest.approx(0.3)

    # вызовы до привязки провайдера, затем привязка, затем вызов при busy_ms_total main 5000.0: 0.0
    clock[0] = 10.0
    intake = _make_intake(_Receiver([]))
    assert intake.get_cycle_metrics()["pump_busy_share"] == 0.0
    clock[0] = 11.0
    assert intake.get_cycle_metrics()["pump_busy_share"] == 0.0

    busy = {"main": _pump_entry(busy_ms_total=5000.0)}
    intake.attach_pump_stats(lambda: {k: dict(v) for k, v in busy.items()})
    clock[0] = 12.0
    assert intake.get_cycle_metrics()["pump_busy_share"] == 0.0

    # база взята на предыдущем вызове (5000.0 в момент 12.0): 5000 -> 5400 за 1.0 с даёт 0.4
    clock[0] = 13.0
    busy["main"] = _pump_entry(busy_ms_total=5400.0)
    assert intake.get_cycle_metrics()["pump_busy_share"] == pytest.approx(0.4)


def test_superseded_grows_when_qt_blocked(qapp: Any) -> None:
    """100 кадров 1440x1080x3 одного sender-а через настоящий bridge.dispatch без насоса: superseded 99, pending 1."""
    from multiprocess_prototype.frontend.bridge import DataReceiverBridge

    bridge = DataReceiverBridge()
    # 10 пачек по 10 кадров, каждая строится лениво: вытесненные кадры освобождаются сразу
    batches: list[list[dict] | Callable[[], list[dict]]] = [
        (lambda: [_big_frame_msg("cam0") for _ in range(10)]) for _ in range(10)
    ]
    receiver = _Receiver(batches)
    intake = _make_intake(receiver, bridge.dispatch)
    intake.attach_mailbox_stats(bridge.frame_mailbox.stats)

    _drive(intake, receiver)
    metrics = intake.get_cycle_metrics()

    assert metrics["frames_in"] == 100
    assert metrics["superseded"] == 99
    assert metrics["pending"] == 1
    assert metrics["bytes_held"] == 4665600
    assert metrics["max_bytes_held"] == 4665600


def test_worker_status_contains_intake_metrics() -> None:
    """Статус настоящего WorkerManager (воркер на FrameIntake.run_loop) содержит все 10 метрик, значения живые."""
    from multiprocess_framework.modules.worker_module import ThreadConfig, ThreadPriority, WorkerManager

    receiver = _Receiver([[_frame_msg() for _ in range(3)]])
    intake = _make_intake(receiver)
    manager = WorkerManager("t4_intake_manager")
    assert manager.initialize() is True
    try:
        created = manager.create_worker("frame_intake", intake.run_loop, ThreadConfig(priority=ThreadPriority.NORMAL))
        assert created is True
        assert manager.start_worker("frame_intake") is True

        deadline = time.perf_counter() + _DEADLINE_S
        status: dict | None = None
        while time.perf_counter() < deadline:
            status = manager.get_worker_status("frame_intake")
            if status is not None and status.get("frames_in") == 3:
                break
            time.sleep(0.01)

        assert status is not None
        missing = _METRIC_KEYS - set(status)
        assert not missing, f"в статусе воркера нет метрик: {sorted(missing)}"
        assert status["frames_in"] == 3
        assert status["batches"] == 1
    finally:
        manager.stop_worker("frame_intake", timeout=_DEADLINE_S)
        manager.shutdown()


# ---------------------------------------------------------------------------
# Очередь Qt
# ---------------------------------------------------------------------------


def test_qt_pending_returns_to_zero(qapp: Any) -> None:
    """50 state-дельт из демон-потока при необработанных событиях: qt_pending 50; после обработки событий 0."""
    from multiprocess_prototype.frontend.bridge import DataReceiverBridge

    handled: list[dict] = []

    class _Sink(QObject):
        def on_state(self, msg: dict) -> None:
            handled.append(msg)

    bridge = DataReceiverBridge()
    sink = _Sink()
    bridge.state_updated.connect(sink.on_state)
    intake = _make_intake(_Receiver([]))
    intake.attach_qt_pending(lambda: bridge.qt_pending)

    def _send() -> None:
        for i in range(50):
            bridge.dispatch({"data_type": "state_delta", "path": f"a.{i}", "value": i})

    sender = threading.Thread(target=_send, name="state-sender", daemon=True)
    sender.start()
    sender.join(_DEADLINE_S)
    assert not sender.is_alive(), "отправитель дельт завис"

    # цикл событий Qt не крутился: 50 сообщений переданы в Qt и не обработаны
    assert len(handled) == 0
    assert intake.get_cycle_metrics()["qt_pending"] == 50
    assert bridge.qt_pending == 50

    deadline = time.perf_counter() + _DEADLINE_S
    while len(handled) < 50 and time.perf_counter() < deadline:
        qapp.processEvents()
        time.sleep(0.005)

    assert len(handled) == 50
    assert intake.get_cycle_metrics()["qt_pending"] == 0
    assert bridge.qt_pending == 0


# ---------------------------------------------------------------------------
# Подписи: latency_sample, fps_text, MainWindow.update_status
# ---------------------------------------------------------------------------


def test_replay_frames_excluded_from_latency() -> None:
    """latency_sample: 100.0 и 100.5 дают 500.0; replay в item или в item['data'], нет capture_ts -> None."""
    from multiprocess_prototype.frontend.frame_intake import latency_sample

    assert latency_sample({"data": {"capture_ts": 100.0}}, 100.5) == pytest.approx(500.0)
    assert latency_sample({"replay": False, "data": {"capture_ts": 100.0}}, 100.5) == pytest.approx(500.0)

    assert latency_sample({"replay": True, "data": {"capture_ts": 100.0}}, 100.5) is None
    assert latency_sample({"data": {"replay": True, "capture_ts": 100.0}}, 100.5) is None

    assert latency_sample({"data": {}}, 100.5) is None
    assert latency_sample({}, 100.5) is None


def test_latency_label_dash_without_sample(qtbot: Any) -> None:
    """Без замера Latency равна «Latency: —», header «FPS: 30.5 | Latency: —»; с замером «Latency: 12.3 ms»."""
    from multiprocess_prototype.frontend.windows.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)

    window.update_status(fps=30.5)
    assert window._latency_label.text() == "Latency: —"
    assert window.header._status_label.text() == "FPS: 30.5 | Latency: —"

    window.update_status(fps=30.5, latency_ms=12.3)
    assert window._latency_label.text() == "Latency: 12.3 ms"


def test_fps_label_shows_shown_and_superseded(qtbot: Any) -> None:
    """fps_text даёт «показано/вытеснено» с разбивкой по слотам; update_status подставляет её в _fps_label и header."""
    from multiprocess_prototype.frontend.frame_intake import fps_text
    from multiprocess_prototype.frontend.windows.main_window import MainWindow

    expected = "FPS: показано 22.0/с (main: 12.0, mask: 10.0), вытеснено 5.0/с"
    assert fps_text(22.0, 5.0, {"main": 12.0, "mask": 10.0}) == expected

    window = MainWindow()
    qtbot.addWidget(window)

    window.update_status(
        fps=30.5,
        latency_ms=None,
        shown=22.0,
        superseded=5.0,
        per_slot={"main": 12.0, "mask": 10.0},
    )
    assert window._fps_label.text() == expected
    assert window.header._status_label.text() == expected + " | Latency: —"

    # без shown и superseded остаётся прежняя подпись
    window.update_status(fps=30.5)
    assert window._fps_label.text() == "FPS: 30.5"
