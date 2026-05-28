"""Тесты health summary в ProcessesTab (Task E.2: AppServices DI)."""

from multiprocess_prototype.frontend.widgets.tabs.processes.presenter import ProcessesPresenter

from ._helpers import make_processes_services


_HEALTH_PROCESSES = [
    {"process_name": "cam", "plugins": [{"plugin_name": "camera_service"}]},
    {"process_name": "proc", "plugins": [{"plugin_name": "grayscale"}]},
    {"process_name": "gui", "plugins": []},
]


class TestProcessesPresenterHealth:
    """Тесты get_health_summary()."""

    def test_total_count(self):
        """total = количество процессов в topology."""
        presenter = ProcessesPresenter(make_processes_services(topology_processes=_HEALTH_PROCESSES))
        summary = presenter.get_health_summary()
        assert summary["total"] == 3

    def test_initial_active_zero(self):
        """active начинается с 0."""
        presenter = ProcessesPresenter(make_processes_services(topology_processes=_HEALTH_PROCESSES))
        summary = presenter.get_health_summary()
        assert summary["active"] == 0

    def test_empty_topology(self):
        """Пустая topology → total=0."""
        presenter = ProcessesPresenter(make_processes_services(topology_processes=[]))
        summary = presenter.get_health_summary()
        assert summary["total"] == 0

    def test_summary_keys(self):
        """Summary содержит все 4 ключа."""
        presenter = ProcessesPresenter(make_processes_services(topology_processes=_HEALTH_PROCESSES))
        summary = presenter.get_health_summary()
        assert set(summary.keys()) == {"total", "active", "broken_wires", "avg_fps"}

    def test_avg_fps_initial(self):
        """avg_fps начинается с 0.0."""
        presenter = ProcessesPresenter(make_processes_services(topology_processes=_HEALTH_PROCESSES))
        summary = presenter.get_health_summary()
        assert summary["avg_fps"] == 0.0

    def test_broken_wires_initial(self):
        """broken_wires начинается с 0."""
        presenter = ProcessesPresenter(make_processes_services(topology_processes=_HEALTH_PROCESSES))
        summary = presenter.get_health_summary()
        assert summary["broken_wires"] == 0
