# -*- coding: utf-8 -*-
"""Тесты системного дашборда телеметрии (telemetry-dashboard Ф2).

Инвариант: серии строятся по списку процессов (конструкторно); refresh тянет ring-историю
из read-model; переключатель метрики меняет источник; интеграция в AllProcessesPanel.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from multiprocess_prototype.frontend.bridge.command_sender import CommandSender
from multiprocess_prototype.frontend.state.telemetry_view_model import TelemetryViewModel
from multiprocess_prototype.frontend.widgets.tabs.processes._panels import AllProcessesPanel
from multiprocess_prototype.frontend.widgets.tabs.processes._system_dashboard import (
    SystemDashboardSection,
)
from multiprocess_prototype.frontend.widgets.tabs.processes.presenter import ProcessesPresenter
from multiprocess_prototype.frontend.widgets.tabs.processes.tab import ProcessesTab

from ._helpers import make_processes_services


def _presenter() -> ProcessesPresenter:
    return ProcessesPresenter(make_processes_services())


def _cmd() -> MagicMock:
    return MagicMock(spec=CommandSender)


def _delta(path: str, value: object) -> dict:
    return {"data_type": "state_delta", "path": path, "value": value, "deleted": False}


class TestSeriesGeneration:
    def test_one_series_per_process(self, qtbot) -> None:
        dash = SystemDashboardSection(["camera_0", "camera_1", "detector"], TelemetryViewModel())
        qtbot.addWidget(dash)
        assert dash._chart.series_keys() == ["camera_0", "camera_1", "detector"]

    def test_empty_process_list(self, qtbot) -> None:
        dash = SystemDashboardSection([], TelemetryViewModel())
        qtbot.addWidget(dash)
        assert dash._chart.series_keys() == []


class TestRefresh:
    def test_refresh_pulls_ring_history_into_series(self, qtbot) -> None:
        vm = TelemetryViewModel()
        vm.on_state_delta(_delta("processes.camera_0.state.fps", 20.0))
        vm.on_state_delta(_delta("processes.camera_0.state.fps", 21.0))
        dash = SystemDashboardSection(["camera_0"], vm)
        qtbot.addWidget(dash)
        dash.refresh()
        _xs, ys = dash._chart._curves["camera_0"].getData()
        assert ys is not None and len(ys) >= 1  # ring-история доехала до серии

    def test_refresh_none_vm_is_noop(self, qtbot) -> None:
        dash = SystemDashboardSection(["camera_0"], None)
        qtbot.addWidget(dash)
        dash.refresh()  # не падает

    def test_metric_switch_changes_source(self, qtbot) -> None:
        vm = TelemetryViewModel()
        vm.on_state_delta(_delta("processes.camera_0.state.latency_ms", 46.0))
        dash = SystemDashboardSection(["camera_0"], vm)
        qtbot.addWidget(dash)
        assert dash.current_metric() == "fps"
        # Переключить на «Задержка, мс» (индекс 1).
        dash._metric_combo.setCurrentIndex(1)
        assert dash.current_metric() == "latency_ms"
        _xs, ys = dash._chart._curves["camera_0"].getData()
        assert ys is not None and len(ys) >= 1  # latency-история доехала


class TestPanelIntegration:
    def test_all_panel_builds_dashboard_with_process_series(self, qtbot) -> None:
        vm = TelemetryViewModel()
        panel = AllProcessesPanel(_presenter(), MagicMock(name="bindings"), telemetry=vm)
        qtbot.addWidget(panel)
        assert hasattr(panel, "_dashboard")
        # Серии = процессы топологии (не пусто).
        assert len(panel._dashboard._chart.series_keys()) >= 1

    def test_fps_delta_triggers_dashboard_refresh(self, qtbot) -> None:
        vm = TelemetryViewModel()
        panel = AllProcessesPanel(_presenter(), MagicMock(name="bindings"), telemetry=vm)
        qtbot.addWidget(panel)
        names = panel._dashboard._chart.series_keys()
        assert names, "нужен хотя бы один процесс"
        target = names[0]
        path = f"processes.{target}.state.fps"
        # Реалистичный поток: VM-ring наполняется on_state_delta ДО батча, затем
        # батч-слот панели → dashboard.refresh() читает уже наполненную историю.
        vm.on_state_delta(_delta(path, 21.0))
        panel._apply_telemetry_items([(path, 21.0)])
        _xs, ys = panel._dashboard._chart._curves[target].getData()
        assert ys is not None and len(ys) >= 1  # дашборд обновился по касанию fps


class TestDashboardRebuildOnRecipeSwap:
    """Нит #4 code review: дашборд не должен оставаться стейл после смены рецепта.

    ``SystemDashboardSection`` сам серии не пересобирает — актуальность обеспечивает
    ``ProcessesTab`` через ``TopologyReplaced`` → ``_sync_nav()`` (см. докстроку
    ``SystemDashboardSection``). Здесь проверяем именно эту гарантию lifecycle:
    при смене набора процессов (как при ``ActivateRecipe``, которая тоже публикует
    ``TopologyReplaced``) старая панель/дашборд уничтожаются, новая строится по
    АКТУАЛЬНОМУ списку процессов — без стейл-серий старого рецепта.
    """

    def test_dashboard_series_refresh_on_topology_replaced(self, qtbot) -> None:
        services = make_processes_services(use_holder=True)
        tab = ProcessesTab(services, command_sender=_cmd())
        qtbot.addWidget(tab)

        old_dashboard = tab._all_panel._dashboard
        assert old_dashboard._chart.series_keys() == ["camera_0", "processor", "renderer"]

        # Имитируем смену рецепта: набор процессов изменился (новый добавлен,
        # старый удалён) + событие TopologyReplaced (как публикует ActivateRecipe).
        tab._presenter.create_process("new_proc", category="utility")
        tab._presenter.delete_process("camera_0")
        tab._on_topology_replaced()

        new_dashboard = tab._all_panel._dashboard
        assert new_dashboard is not old_dashboard  # панель/дашборд пересобраны заново
        new_series = new_dashboard._chart.series_keys()
        assert "new_proc" in new_series
        assert "camera_0" not in new_series  # стейл-серия удалённого процесса не осталась

    def test_no_rebuild_keeps_dashboard_when_process_set_unchanged(self, qtbot) -> None:
        """Правки воркеров (набор процессов тот же) не пересобирают дашборд — не стейл,
        т.к. ключи серий (имена процессов) не изменились."""
        services = make_processes_services(use_holder=True)
        tab = ProcessesTab(services, command_sender=_cmd())
        qtbot.addWidget(tab)

        old_dashboard = tab._all_panel._dashboard
        tab._presenter.add_worker("camera_0", worker_name="w1")
        tab._on_topology_replaced()

        assert tab._all_panel._dashboard is old_dashboard
        assert old_dashboard._chart.series_keys() == ["camera_0", "processor", "renderer"]
