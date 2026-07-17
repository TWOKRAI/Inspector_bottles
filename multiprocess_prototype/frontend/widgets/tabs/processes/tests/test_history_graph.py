# -*- coding: utf-8 -*-
"""Тесты графика телеметрии в SingleProcessPanel (Task 2.2, план gui-telemetry-read-model).

Проверяет:
  1. 10 мин — из ring-буфера VM (без похода в TelemetryHistorySource).
  2. 1 час/1 день — TelemetryHistorySource.list_range читается НЕ в main thread
     (RequestRunner/QThreadPool) — переключение диапазона не блокирует GUI.
  3. Живой батч VM обновляет график 10 мин (тот же батч-слот, что карточка).
  4. Деградация без падений: VM=None / пустая БД → спарклайн без данных.
  5. Существующие инварианты (0 серверных подписок, дебаунс воркеров) не задеты.
"""

from __future__ import annotations

import threading
from typing import Any

from PySide6.QtCore import Qt

from multiprocess_prototype.frontend.state.telemetry_view_model import TelemetryViewModel
from multiprocess_prototype.frontend.widgets.tabs.processes._panels import SingleProcessPanel
from multiprocess_prototype.frontend.widgets.tabs.processes.presenter import ProcessesPresenter

from ._helpers import make_processes_services


def _presenter() -> ProcessesPresenter:
    return ProcessesPresenter(make_processes_services())


def _delta(path: str, value: object, *, deleted: bool = False) -> dict:
    return {"data_type": "state_delta", "path": path, "value": value, "deleted": deleted}


class _RecordingHistorySource:
    """Fake TelemetryHistorySource: пишет поток вызова + аргументы, не трогает БД."""

    def __init__(self, records: list[dict[str, Any]] | None = None) -> None:
        self._records = records if records is not None else []
        self.calls: list[tuple[str, float, float, tuple, int]] = []
        self.call_threads: list[int] = []

    def list_range(
        self,
        process_name: str,
        ts_from: float,
        ts_to: float,
        metrics: tuple,
        max_points: int = 300,
    ) -> list[dict[str, Any]]:
        self.call_threads.append(threading.get_ident())
        self.calls.append((process_name, ts_from, ts_to, tuple(metrics), max_points))
        return list(self._records)


# ------------------------------------------------------------------ #
#  10 мин — ring-буфер VM, без похода в TelemetryHistorySource         #
# ------------------------------------------------------------------ #


class TestTenMinuteRangeUsesRingBuffer:
    def test_default_range_is_10m_and_does_not_call_history_source(self, qtbot) -> None:
        vm = TelemetryViewModel()
        source = _RecordingHistorySource()
        panel = SingleProcessPanel(_presenter(), None, "camera_0", telemetry=vm, history_source=source)
        qtbot.addWidget(panel)

        assert panel._graph_range == "10m"
        assert source.calls == []

    def test_ring_buffer_data_visible_immediately_late_binding(self, qtbot) -> None:
        """Точки в ring-буфере ДО создания панели — видны сразу (как snapshot карточки)."""
        vm = TelemetryViewModel()
        vm.on_state_delta(_delta("processes.camera_0.state.fps", 42.0))

        panel = SingleProcessPanel(_presenter(), None, "camera_0", telemetry=vm)
        qtbot.addWidget(panel)

        points = panel._fps_chart.series_points("fps")
        assert points and points[-1][1] == 42.0

    def test_live_batch_updates_10m_graph(self, qtbot) -> None:
        vm = TelemetryViewModel()
        panel = SingleProcessPanel(_presenter(), None, "camera_0", telemetry=vm)
        qtbot.addWidget(panel)

        vm.on_state_delta(_delta("processes.camera_0.state.fps", 33.0))
        qtbot.wait(50)  # коалесинг updated

        points = panel._fps_chart.series_points("fps")
        assert points and points[-1][1] == 33.0

    def test_batch_for_other_process_does_not_touch_graph(self, qtbot) -> None:
        vm = TelemetryViewModel()
        panel = SingleProcessPanel(_presenter(), None, "camera_0", telemetry=vm)
        qtbot.addWidget(panel)

        vm.on_state_delta(_delta("processes.processor.state.fps", 99.0))
        qtbot.wait(50)

        assert panel._fps_chart.series_points("fps") == []


# ------------------------------------------------------------------ #
#  1 час / 1 день — TelemetryHistorySource, чтение НЕ в main thread   #
# ------------------------------------------------------------------ #


class TestDeeperRangeReadsHistorySourceOffMainThread:
    def test_switch_to_1h_calls_history_source(self, qtbot) -> None:
        vm = TelemetryViewModel()
        source = _RecordingHistorySource(records=[{"ts": 1.0, "fps": 10.0, "latency_ms": 5.0}])
        panel = SingleProcessPanel(_presenter(), None, "camera_0", telemetry=vm, history_source=source)
        qtbot.addWidget(panel)

        qtbot.mouseClick(panel._graph_range_buttons["1h"], Qt.MouseButton.LeftButton)

        qtbot.waitUntil(lambda: len(source.calls) == 1, timeout=1000)
        proc, ts_from, ts_to, metrics, max_points = source.calls[0]
        assert proc == "camera_0"
        assert ts_to - ts_from == 3600.0
        assert set(metrics) == {"fps", "latency_ms"}
        assert max_points > 0

    def test_history_source_called_off_main_thread(self, qtbot) -> None:
        vm = TelemetryViewModel()
        source = _RecordingHistorySource(records=[])
        panel = SingleProcessPanel(_presenter(), None, "camera_0", telemetry=vm, history_source=source)
        qtbot.addWidget(panel)
        main_thread_id = threading.get_ident()

        panel._on_graph_range_selected("1d")
        qtbot.waitUntil(lambda: len(source.calls) == 1, timeout=1000)

        assert source.call_threads[0] != main_thread_id

    def test_1d_range_requests_86400s_window(self, qtbot) -> None:
        vm = TelemetryViewModel()
        source = _RecordingHistorySource()
        panel = SingleProcessPanel(_presenter(), None, "camera_0", telemetry=vm, history_source=source)
        qtbot.addWidget(panel)

        panel._on_graph_range_selected("1d")
        qtbot.waitUntil(lambda: len(source.calls) == 1, timeout=1000)

        _proc, ts_from, ts_to, _metrics, _max_points = source.calls[0]
        assert ts_to - ts_from == 86400.0

    def test_history_result_applied_to_sparklines_in_main_thread(self, qtbot) -> None:
        vm = TelemetryViewModel()
        records = [{"ts": 10.0, "fps": 25.0, "latency_ms": 8.0}, {"ts": 20.0, "fps": 27.0, "latency_ms": 9.0}]
        source = _RecordingHistorySource(records=records)
        panel = SingleProcessPanel(_presenter(), None, "camera_0", telemetry=vm, history_source=source)
        qtbot.addWidget(panel)

        panel._on_graph_range_selected("1h")
        qtbot.waitUntil(lambda: panel._fps_chart.series_points("fps") == [(10.0, 25.0), (20.0, 27.0)], timeout=1000)
        assert panel._latency_chart.series_points("latency") == [(10.0, 8.0), (20.0, 9.0)]

    def test_switching_back_to_10m_does_not_call_history_source_again(self, qtbot) -> None:
        vm = TelemetryViewModel()
        source = _RecordingHistorySource(records=[{"ts": 1.0, "fps": 5.0}])
        panel = SingleProcessPanel(_presenter(), None, "camera_0", telemetry=vm, history_source=source)
        qtbot.addWidget(panel)

        panel._on_graph_range_selected("1h")
        qtbot.waitUntil(lambda: len(source.calls) == 1, timeout=1000)

        panel._on_graph_range_selected("10m")
        qtbot.wait(50)
        assert len(source.calls) == 1  # 10m не ходит в историю
        assert panel._graph_range_buttons["10m"].isChecked()
        assert not panel._graph_range_buttons["1h"].isChecked()


class TestStaleHistoryResponseDiscarded:
    """Быстрое переключение диапазона: QThreadPool не гарантирует порядок завершения,
    поэтому ответ старого запроса (другая генерация) не должен перетирать график
    актуального выбора. Гейт — по _graph_request_id (инкремент на каждый рефреш)."""

    def test_stale_range_response_is_ignored(self, qtbot) -> None:
        vm = TelemetryViewModel()
        source = _RecordingHistorySource()
        panel = SingleProcessPanel(_presenter(), None, "camera_0", telemetry=vm, history_source=source)
        qtbot.addWidget(panel)

        current = panel._graph_request_id
        records = [{"ts": 1.0, "fps": 999.0, "latency_ms": 111.0}]

        # Ответ с УСТАРЕВШЕЙ генерацией — отбрасывается, график не тронут.
        panel._on_history_ready({"records": records, "request_id": current - 1})
        assert panel._fps_chart.series_points("fps") == []
        assert panel._latency_chart.series_points("latency") == []

        # Ответ с АКТУАЛЬНОЙ генерацией — применяется.
        panel._on_history_ready({"records": records, "request_id": current})
        assert panel._fps_chart.series_points("fps") == [(1.0, 999.0)]

    def test_ring_graph_drops_points_older_than_10m_window(self, qtbot) -> None:
        """Ring читается по wall-окну: после остановки потока метрики старые точки
        (deque вытесняет их лишь при append) не должны рисоваться как текущие.
        Регресс на `history(path)` без since — стейл-окно из прошлого."""
        import collections
        import time

        vm = TelemetryViewModel()
        panel = SingleProcessPanel(_presenter(), None, "camera_0", telemetry=vm)
        qtbot.addWidget(panel)

        t_now = time.time()
        path = "processes.camera_0.state.fps"
        # Старая точка (за окном 10м = 600с) + свежая точка внутри окна.
        vm._history[path] = collections.deque([(t_now - 3600.0, 11.0), (t_now - 1.0, 22.0)], maxlen=600)

        panel._refresh_graph_from_ring()

        pts = panel._fps_chart.series_points("fps")
        assert pts == [(t_now - 1.0, 22.0)], "старая точка за окном не отсечена по since"

    def test_response_without_request_id_applies_as_current(self, qtbot) -> None:
        """Ответ без request_id (RequestRunner при исключении _fetch → {"success": False})
        относится к текущему запросу: деградирует в records=[], панель не падает."""
        vm = TelemetryViewModel()
        panel = SingleProcessPanel(_presenter(), None, "camera_0", telemetry=vm)
        qtbot.addWidget(panel)

        panel._on_history_ready({"success": False, "error": "boom"})
        assert panel._fps_chart.series_points("fps") == []


# ------------------------------------------------------------------ #
#  Деградация без падений                                             #
# ------------------------------------------------------------------ #


class TestGracefulDegradation:
    def test_without_vm_graph_shows_no_points_and_does_not_crash(self, qtbot) -> None:
        panel = SingleProcessPanel(_presenter(), None, "camera_0", telemetry=None)
        qtbot.addWidget(panel)
        assert panel._fps_chart.series_points("fps") == []
        assert panel._latency_chart.series_points("latency") == []

    def test_empty_history_result_leaves_sparklines_empty(self, qtbot) -> None:
        vm = TelemetryViewModel()
        source = _RecordingHistorySource(records=[])
        panel = SingleProcessPanel(_presenter(), None, "camera_0", telemetry=vm, history_source=source)
        qtbot.addWidget(panel)

        panel._on_graph_range_selected("1h")
        qtbot.waitUntil(lambda: len(source.calls) == 1, timeout=1000)
        qtbot.wait(50)

        assert panel._fps_chart.series_points("fps") == []

    def test_default_history_source_constructed_when_not_injected(self, qtbot) -> None:
        """telemetry/history_source не переданы — панель конструируется без падений
        (дефолтный TelemetryHistorySource на несуществующий файл — просто пусто)."""
        panel = SingleProcessPanel(_presenter(), None, "camera_0")
        qtbot.addWidget(panel)
        assert panel._history_source is not None
