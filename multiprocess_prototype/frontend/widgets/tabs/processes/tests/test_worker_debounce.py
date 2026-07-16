# -*- coding: utf-8 -*-
"""Тесты дебаунса каскада обнаружения рантайм-воркеров (Task 0.4, часть A).

_on_worker_discovered копит имена и взводит один отложенный
_flush_worker_refresh (QTimer.singleShot) — N обнаружений подряд должны
дать РОВНО один _refresh_workers, а не N. См. plans/gui-telemetry-read-model.md.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from multiprocess_prototype.frontend.widgets.tabs.processes._panels import SingleProcessPanel
from multiprocess_prototype.frontend.widgets.tabs.processes.presenter import ProcessesPresenter

from ._helpers import make_processes_services


def _make_panel(qtbot) -> SingleProcessPanel:
    presenter = ProcessesPresenter(make_processes_services())
    panel = SingleProcessPanel(presenter, None, "camera_0")
    qtbot.addWidget(panel)
    return panel


class TestWorkerDiscoveryDebounce:
    def test_five_discoveries_coalesce_into_one_refresh(self, qtbot) -> None:
        """5 обнаружений подряд (разные воркеры) → ровно 1 вызов _refresh_workers."""
        panel = _make_panel(qtbot)
        panel._refresh_workers = MagicMock(wraps=panel._refresh_workers)

        for i in range(5):
            panel._on_worker_discovered(f"processes.camera_0.workers.worker_{i}.status", "running")

        # Таймер ещё не сработал (debounce 50 мс) — refresh пока не вызывался.
        assert panel._refresh_workers.call_count == 0
        assert panel._worker_refresh_pending is True

        qtbot.wait(150)  # дать QTimer.singleShot(50, ...) сработать

        assert panel._refresh_workers.call_count == 1
        assert panel._worker_refresh_pending is False
        # Все 5 воркеров присутствуют в финальном наборе.
        assert panel._runtime_workers == {f"worker_{i}" for i in range(5)}

    def test_duplicate_discovery_does_not_reschedule(self, qtbot) -> None:
        """Повторное обнаружение уже известного воркера не взводит новый таймер."""
        panel = _make_panel(qtbot)
        panel._refresh_workers = MagicMock(wraps=panel._refresh_workers)

        panel._on_worker_discovered("processes.camera_0.workers.worker_0.status", "running")
        panel._on_worker_discovered("processes.camera_0.workers.worker_0.status", "running")
        panel._on_worker_discovered("processes.camera_0.workers.worker_0.status", "running")

        qtbot.wait(150)

        assert panel._refresh_workers.call_count == 1

    def test_flush_skips_when_panel_marked_destroyed(self, qtbot) -> None:
        """Гвард от гонки: панель уничтожена до срабатывания таймера → refresh не зовётся."""
        panel = _make_panel(qtbot)
        panel._refresh_workers = MagicMock()

        panel._on_worker_discovered("processes.camera_0.workers.worker_0.status", "running")
        assert panel._worker_refresh_pending is True

        # Симулируем уничтожение (сигнал destroyed) до срабатывания таймера.
        panel._mark_destroyed()

        qtbot.wait(150)

        panel._refresh_workers.assert_not_called()
