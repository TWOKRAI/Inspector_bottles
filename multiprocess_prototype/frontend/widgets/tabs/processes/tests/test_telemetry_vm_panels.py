# -*- coding: utf-8 -*-
"""Тесты миграции панелей «Процессов» на TelemetryViewModel (Task 1.3).

Проверяет три инварианта плана gui-telemetry-read-model:
  1. VM-режим: панель НЕ создаёт серверных подписок (0 bind/bind_fanout →
     0 ensure_subscription) — телеметрия читается локально из read-model.
  2. Live-обновление карточек/health/воркеров через VM (батч updated) +
     первичное наполнение из snapshot (late-binding: панель, созданная ПОСЛЕ
     публикации, показывает актуальное сразу).
  3. Fallback: панель без VM (telemetry=None) конструируется и биндит по-старому.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from multiprocess_prototype.frontend.state.telemetry_view_model import TelemetryViewModel
from multiprocess_prototype.frontend.widgets.tabs.processes._panels import (
    AllProcessesPanel,
    SingleProcessPanel,
)
from multiprocess_prototype.frontend.widgets.tabs.processes.presenter import ProcessesPresenter
from multiprocess_prototype.frontend.widgets.tabs.processes.tab import ProcessesTab

from ._helpers import make_processes_runtime, make_processes_services


# ------------------------------------------------------------------ #
#  Хелперы                                                            #
# ------------------------------------------------------------------ #


def _presenter() -> ProcessesPresenter:
    return ProcessesPresenter(make_processes_services())


def _delta(path: str, value: object, *, deleted: bool = False) -> dict:
    return {"data_type": "state_delta", "path": path, "value": value, "deleted": deleted}


def _counting_bindings() -> MagicMock:
    """Мок GuiStateBindings со счётчиками bind/bind_fanout/ensure_subscription."""
    mock = MagicMock(name="bindings")
    return mock


# ------------------------------------------------------------------ #
#  1. Инвариант: 0 серверных подписок из панелей в VM-режиме          #
# ------------------------------------------------------------------ #


class TestNoServerSubscriptionsInVmMode:
    def test_all_panel_vm_makes_no_bind_calls(self, qtbot) -> None:
        """AllProcessesPanel с VM: ни одного bind/bind_fanout (→ ensure_subscription)."""
        vm = TelemetryViewModel()
        bindings = _counting_bindings()
        panel = AllProcessesPanel(_presenter(), bindings, telemetry=vm)
        qtbot.addWidget(panel)

        assert bindings.bind.call_count == 0
        assert bindings.bind_fanout.call_count == 0
        assert bindings.ensure_subscription.call_count == 0

    def test_single_panel_vm_makes_no_bind_calls(self, qtbot) -> None:
        """SingleProcessPanel с VM: ни одного bind/bind_fanout."""
        vm = TelemetryViewModel()
        bindings = _counting_bindings()
        panel = SingleProcessPanel(_presenter(), bindings, "camera_0", telemetry=vm)
        qtbot.addWidget(panel)

        assert bindings.bind.call_count == 0
        assert bindings.bind_fanout.call_count == 0
        assert bindings.ensure_subscription.call_count == 0

    def test_tab_open_and_select_makes_no_bind_calls(self, qtbot) -> None:
        """ProcessesTab (open + выбор процесса) с VM: 0 bind/bind_fanout из панелей."""
        vm = TelemetryViewModel()
        bindings = _counting_bindings()
        runtime = make_processes_runtime(command_sender=MagicMock(), bindings=bindings, telemetry=vm)
        tab = ProcessesTab.create(make_processes_services(), runtime)
        qtbot.addWidget(tab)

        # Открытие (AllProcessesPanel создан лениво) — 0 подписок.
        assert bindings.bind.call_count == 0
        assert bindings.bind_fanout.call_count == 0

        # Выбор процесса → ленивое создание SingleProcessPanel — тоже 0.
        cam_row = next(i for i in range(tab._nav_list.count()) if tab._nav_list.item(i).text() == "camera_0")
        tab._nav_list.setCurrentRow(cam_row)
        assert tab._selected_process == "camera_0"
        assert bindings.bind.call_count == 0
        assert bindings.bind_fanout.call_count == 0
        assert bindings.ensure_subscription.call_count == 0


# ------------------------------------------------------------------ #
#  2. Live-обновление через VM + первичное наполнение из snapshot     #
# ------------------------------------------------------------------ #


class TestLiveUpdateViaVm:
    def test_all_panel_card_updates_on_batch(self, qtbot) -> None:
        """Батч VM обновляет метрику «Циклов/с» карточки процесса."""
        vm = TelemetryViewModel()
        panel = AllProcessesPanel(_presenter(), None, telemetry=vm)
        qtbot.addWidget(panel)

        vm.on_state_delta(_delta("processes.camera_0.state.fps", 24.0))
        qtbot.wait(50)  # 0-таймер коалесинга updated

        assert panel._cards["camera_0"]._metric_labels["Циклов/с"].text() == "24.0"

    def test_all_panel_health_updates_on_batch(self, qtbot) -> None:
        """Батч VM обновляет health-лейблы (active + chain_fps)."""
        vm = TelemetryViewModel()
        panel = AllProcessesPanel(_presenter(), None, telemetry=vm)
        qtbot.addWidget(panel)

        vm.on_state_delta(_delta("system.health.active", 3))
        vm.on_state_delta(_delta("system.chain_fps", 20.0))
        qtbot.wait(50)

        assert panel._lbl_active.text() == "Активно: 3"
        assert panel._lbl_chain_fps.text() == "FPS цепочки: 20.0"

    def test_all_panel_trace_fanout_via_batch(self, qtbot) -> None:
        """Fan-out trace_segments приходит через тот же батч-слот."""
        vm = TelemetryViewModel()
        panel = AllProcessesPanel(_presenter(), None, telemetry=vm)
        qtbot.addWidget(panel)
        panel.show()

        vm.on_state_delta(_delta("system.trace_segments", [{"label": "cam→det", "kind": "transport", "ms": 3.0}]))
        qtbot.wait(50)

        assert panel._trace_box.isVisible()
        assert panel._trace_table.item(0, 0).text() == "cam→det"

    def test_all_panel_snapshot_priming_late_binding(self, qtbot) -> None:
        """Панель, созданная ПОСЛЕ публикации, показывает значение сразу (snapshot)."""
        vm = TelemetryViewModel()
        # Публикация ДО создания панели.
        vm.on_state_delta(_delta("processes.processor.state.fps", 15.5))
        vm.on_state_delta(_delta("system.health.active", 2))

        panel = AllProcessesPanel(_presenter(), None, telemetry=vm)
        qtbot.addWidget(panel)

        # Без ожидания updated — первичное наполнение синхронно в _connect_bindings.
        assert panel._cards["processor"]._metric_labels["Циклов/с"].text() == "15.5"
        assert panel._lbl_active.text() == "Активно: 2"

    def test_single_panel_card_updates_on_batch(self, qtbot) -> None:
        """Батч VM обновляет статус/Циклов/с карточки одного процесса."""
        vm = TelemetryViewModel()
        panel = SingleProcessPanel(_presenter(), None, "camera_0", telemetry=vm)
        qtbot.addWidget(panel)

        vm.on_state_delta(_delta("processes.camera_0.state.fps", 30.0))
        vm.on_state_delta(_delta("processes.camera_0.state.status", "running"))
        qtbot.wait(50)

        assert panel._card._metric_labels["Циклов/с"].text() == "30.0"
        assert panel._card._indicator.state() == "running"

    def test_single_panel_snapshot_priming_late_binding(self, qtbot) -> None:
        """SingleProcessPanel после публикации показывает метрики сразу (snapshot)."""
        vm = TelemetryViewModel()
        vm.on_state_delta(_delta("processes.camera_0.state.fps", 42.0))

        panel = SingleProcessPanel(_presenter(), None, "camera_0", telemetry=vm)
        qtbot.addWidget(panel)

        assert panel._card._metric_labels["Циклов/с"].text() == "42.0"

    def test_single_panel_runtime_worker_discovered_and_updated(self, qtbot) -> None:
        """Рантайм-воркер обнаруживается из батча (discover) и обновляется по VM."""
        vm = TelemetryViewModel()
        panel = SingleProcessPanel(_presenter(), None, "camera_0", telemetry=vm)
        qtbot.addWidget(panel)

        # Обнаружение: status-путь рантайм-воркера → строка строится (debounce 50 мс).
        vm.on_state_delta(_delta("processes.camera_0.workers.grabber.status", "running"))
        qtbot.wait(250)  # 0-таймер updated + debounce 50 мс refresh

        assert "grabber" in panel._runtime_workers
        assert "grabber" in panel._worker_table.worker_names()
        # Статус наполнен из snapshot при пересборке строки.
        assert panel._worker_table.telemetry_widgets("grabber")["status"].text() == "running"

        # Live-обновление Гц воркера через VM.
        vm.on_state_delta(_delta("processes.camera_0.workers.grabber.effective_hz", 12.0))
        qtbot.wait(50)
        assert panel._worker_table.telemetry_widgets("grabber")["hz"].text() == "12.0 Гц"


# ------------------------------------------------------------------ #
#  3. Fallback: без VM — прежний bindings-путь                        #
# ------------------------------------------------------------------ #


class TestFallbackWithoutVm:
    def test_all_panel_without_vm_uses_bindings(self, qtbot) -> None:
        """telemetry=None → панель биндит по-старому (bind вызван)."""
        bindings = _counting_bindings()
        panel = AllProcessesPanel(_presenter(), bindings, telemetry=None)
        qtbot.addWidget(panel)

        assert bindings.bind.call_count > 0
        assert bindings.bind_fanout.call_count > 0

    def test_single_panel_without_vm_uses_bindings(self, qtbot) -> None:
        """telemetry=None → SingleProcessPanel биндит по-старому."""
        bindings = _counting_bindings()
        panel = SingleProcessPanel(_presenter(), bindings, "camera_0", telemetry=None)
        qtbot.addWidget(panel)

        assert bindings.bind.call_count > 0

    def test_panels_without_any_deps_construct(self, qtbot) -> None:
        """telemetry=None и bindings=None → панели всё равно конструируются."""
        all_panel = AllProcessesPanel(_presenter(), None, telemetry=None)
        qtbot.addWidget(all_panel)
        single = SingleProcessPanel(_presenter(), None, "camera_0", telemetry=None)
        qtbot.addWidget(single)
        assert all_panel is not None
        assert single is not None
