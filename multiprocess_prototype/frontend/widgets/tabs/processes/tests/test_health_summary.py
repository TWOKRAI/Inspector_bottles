"""Тесты health summary в ProcessesTab."""
import pytest
from unittest.mock import MagicMock


def _make_ctx(topology=None):
    """Создать mock AppContext."""
    ctx = MagicMock()
    ctx.config = {}
    ctx.extras = {
        "topology": topology or {
            "processes": [
                {"process_name": "cam", "plugins": [{"plugin_name": "camera_service"}]},
                {"process_name": "proc", "plugins": [{"plugin_name": "grayscale"}]},
                {"process_name": "gui", "plugins": []},
            ]
        },
    }
    ctx.plugin_registry.return_value = None
    return ctx


class TestProcessesPresenterHealth:
    """Тесты get_health_summary()."""

    def test_total_count(self):
        """total = количество процессов в topology."""
        from multiprocess_prototype.frontend.widgets.tabs.processes.presenter import ProcessesPresenter
        ctx = _make_ctx()
        presenter = ProcessesPresenter(ctx)
        summary = presenter.get_health_summary()
        assert summary["total"] == 3

    def test_initial_active_zero(self):
        """active начинается с 0."""
        from multiprocess_prototype.frontend.widgets.tabs.processes.presenter import ProcessesPresenter
        ctx = _make_ctx()
        presenter = ProcessesPresenter(ctx)
        summary = presenter.get_health_summary()
        assert summary["active"] == 0

    def test_empty_topology(self):
        """Пустая topology → total=0."""
        from multiprocess_prototype.frontend.widgets.tabs.processes.presenter import ProcessesPresenter
        ctx = _make_ctx(topology={"processes": []})
        presenter = ProcessesPresenter(ctx)
        summary = presenter.get_health_summary()
        assert summary["total"] == 0

    def test_summary_keys(self):
        """Summary содержит все 4 ключа."""
        from multiprocess_prototype.frontend.widgets.tabs.processes.presenter import ProcessesPresenter
        ctx = _make_ctx()
        presenter = ProcessesPresenter(ctx)
        summary = presenter.get_health_summary()
        assert set(summary.keys()) == {"total", "active", "broken_wires", "avg_fps"}

    def test_avg_fps_initial(self):
        """avg_fps начинается с 0.0."""
        from multiprocess_prototype.frontend.widgets.tabs.processes.presenter import ProcessesPresenter
        ctx = _make_ctx()
        presenter = ProcessesPresenter(ctx)
        summary = presenter.get_health_summary()
        assert summary["avg_fps"] == 0.0

    def test_broken_wires_initial(self):
        """broken_wires начинается с 0."""
        from multiprocess_prototype.frontend.widgets.tabs.processes.presenter import ProcessesPresenter
        ctx = _make_ctx()
        presenter = ProcessesPresenter(ctx)
        summary = presenter.get_health_summary()
        assert summary["broken_wires"] == 0
