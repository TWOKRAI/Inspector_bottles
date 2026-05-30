# -*- coding: utf-8 -*-
"""Тесты Фазы E (processes-workers-runtime): сборка панели + диалоги + nav-rebuild."""

from __future__ import annotations

from unittest.mock import MagicMock

from multiprocess_prototype.frontend.bridge.command_sender import CommandSender
from multiprocess_prototype.frontend.widgets.tabs.processes._panels import SingleProcessPanel
from multiprocess_prototype.frontend.widgets.tabs.processes.presenter import ProcessesPresenter
from multiprocess_prototype.frontend.widgets.tabs.processes.tab import ProcessesTab
from multiprocess_prototype.frontend.widgets.tabs.processes.widgets import (
    CreateProcessDialog,
    CreateWorkerDialog,
    ProcessCard,
)

from ._helpers import make_processes_services


def _cmd() -> MagicMock:
    return MagicMock(spec=CommandSender)


# ====================================================================== #
#  SingleProcessPanel — ProcessCard + WorkerTable                       #
# ====================================================================== #


class TestSinglePanelAssembly:
    def test_panel_uses_process_card(self, qtbot) -> None:
        presenter = ProcessesPresenter(make_processes_services(use_holder=True))
        panel = SingleProcessPanel(presenter, None, "camera_0")
        qtbot.addWidget(panel)
        assert isinstance(panel._card, ProcessCard)

    def test_panel_has_worker_table_with_main(self, qtbot) -> None:
        presenter = ProcessesPresenter(make_processes_services(use_holder=True))
        panel = SingleProcessPanel(presenter, None, "camera_0")
        qtbot.addWidget(panel)
        # синтетический message_processor присутствует
        assert "message_processor" in panel._worker_table.worker_names()

    def test_worker_remove_refreshes_table(self, qtbot) -> None:
        presenter = ProcessesPresenter(make_processes_services(use_holder=True), command_sender=_cmd())
        presenter.add_worker("camera_0", worker_name="grabber")
        panel = SingleProcessPanel(presenter, None, "camera_0")
        qtbot.addWidget(panel)
        assert "grabber" in panel._worker_table.worker_names()
        panel._on_worker_remove("grabber")
        assert "grabber" not in panel._worker_table.worker_names()

    def test_worker_changed_updates_spec(self, qtbot) -> None:
        services = make_processes_services(use_holder=True)
        presenter = ProcessesPresenter(services, command_sender=_cmd())
        presenter.add_worker("camera_0", worker_name="grabber", priority="NORMAL")
        panel = SingleProcessPanel(presenter, None, "camera_0")
        qtbot.addWidget(panel)
        panel._on_worker_changed("grabber", "priority", "BATCH")
        proc = presenter._find_domain_process("camera_0")
        spec = next(w for w in proc.workers if w.worker_name == "grabber")
        assert spec.priority == "BATCH"


# ====================================================================== #
#  Tab — TopologyReplaced → nav rebuild                                 #
# ====================================================================== #


class TestTabNavRebuild:
    def test_rebuild_on_process_create(self, qtbot) -> None:
        services = make_processes_services(use_holder=True)
        tab = ProcessesTab(services, command_sender=_cmd())
        qtbot.addWidget(tab)
        assert tab._nav_list.count() == 4  # «Все» + 3
        tab._presenter.create_process("new_proc", category="utility")
        tab._on_topology_replaced()
        names = [tab._nav_list.item(i).text() for i in range(tab._nav_list.count())]
        assert "new_proc" in names
        assert tab._nav_list.count() == 5

    def test_no_rebuild_on_worker_change(self, qtbot) -> None:
        services = make_processes_services(use_holder=True)
        tab = ProcessesTab(services, command_sender=_cmd())
        qtbot.addWidget(tab)
        count_before = tab._nav_list.count()
        tab._presenter.add_worker("camera_0", worker_name="w1")
        tab._on_topology_replaced()
        assert tab._nav_list.count() == count_before  # набор процессов не изменился

    def test_rebuild_on_process_delete(self, qtbot) -> None:
        services = make_processes_services(use_holder=True)
        tab = ProcessesTab(services, command_sender=_cmd())
        qtbot.addWidget(tab)
        tab._presenter.delete_process("processor")
        tab._on_topology_replaced()
        names = [tab._nav_list.item(i).text() for i in range(tab._nav_list.count())]
        assert "processor" not in names


# ====================================================================== #
#  Диалоги                                                              #
# ====================================================================== #


class TestDialogs:
    def test_create_process_dialog_result(self, qtbot) -> None:
        dialog = CreateProcessDialog()
        qtbot.addWidget(dialog)
        dialog._name_edit.setText("  proc1  ")
        dialog._category_combo.setCurrentIndex(1)
        data = dialog.result_data()
        assert data["name"] == "proc1"  # trimmed
        assert data["category"] == dialog._category_combo.currentData()

    def test_create_worker_dialog_result(self, qtbot) -> None:
        dialog = CreateWorkerDialog()
        qtbot.addWidget(dialog)
        dialog._name_edit.setText("grabber")
        dialog._priority_combo.setCurrentText("REALTIME")
        dialog._mode_combo.setCurrentText("loop")
        dialog._interval_spin.setValue(40)
        data = dialog.result_data()
        assert data == {
            "worker_name": "grabber",
            "priority": "REALTIME",
            "execution_mode": "loop",
            "target_interval_ms": 40,
        }

    def test_create_worker_dialog_zero_interval_is_none(self, qtbot) -> None:
        dialog = CreateWorkerDialog()
        qtbot.addWidget(dialog)
        dialog._name_edit.setText("w")
        dialog._interval_spin.setValue(0)  # «—» → None
        assert dialog.result_data()["target_interval_ms"] is None
