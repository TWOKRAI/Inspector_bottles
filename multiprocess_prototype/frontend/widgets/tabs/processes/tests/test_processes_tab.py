"""Тесты для ProcessesTab и ProcessesPresenter (Task E.2: AppServices DI)."""

from unittest.mock import MagicMock

from PySide6.QtCore import Qt

from multiprocess_prototype.frontend.bridge.command_sender import CommandSender
from multiprocess_prototype.frontend.widgets.tabs.processes.tab import ProcessesTab
from multiprocess_prototype.frontend.widgets.tabs.processes.presenter import ProcessesPresenter
from multiprocess_prototype.frontend.widgets.tabs.processes.data import (
    ALL_PROCESSES_KEY,
    ProcessInfo,
)

from ._helpers import make_processes_services, make_processes_runtime


def _cmd() -> MagicMock:
    """command_sender mock со spec (runtime IPC, вне AppServices Protocol)."""
    return MagicMock(spec=CommandSender)


# ------------------------------------------------------------------ #
#  Presenter                                                           #
# ------------------------------------------------------------------ #


class TestProcessesPresenter:
    def test_get_processes(self):
        p = ProcessesPresenter(make_processes_services())
        procs = p.get_processes()
        assert len(procs) == 3
        names = [proc.name for proc in procs]
        assert "camera_0" in names
        assert "processor" in names

    def test_group_by_category(self):
        p = ProcessesPresenter(make_processes_services())
        procs = [
            ProcessInfo("a", "source"),
            ProcessInfo("b", "processing"),
            ProcessInfo("c", "source"),
        ]
        groups = p.group_by_category(procs)
        assert len(groups["source"]) == 2
        assert len(groups["processing"]) == 1

    def test_category_title(self):
        p = ProcessesPresenter(make_processes_services())
        assert p.category_title("source") == "Источники"
        assert p.category_title("processing") == "Обработка"

    def test_on_process_action(self):
        cmd = _cmd()
        p = ProcessesPresenter(make_processes_services(), command_sender=cmd)
        p.on_process_action("camera_0", "start")
        cmd.send_command.assert_called_once_with("camera_0", "process.start", {})

    def test_get_processes_single(self):
        """Topology с одним процессом читается через services.topology."""
        services = make_processes_services(topology_processes=[{"process_name": "extra_proc", "plugins": []}])
        p = ProcessesPresenter(services)
        procs = p.get_processes()
        assert len(procs) == 1
        assert procs[0].name == "extra_proc"

    def test_get_processes_empty_topology(self):
        """Graceful degradation при отсутствии topology."""
        p = ProcessesPresenter(make_processes_services(topology_processes=[]))
        procs = p.get_processes()
        assert procs == []

    def test_on_process_action_stop(self):
        cmd = _cmd()
        p = ProcessesPresenter(make_processes_services(), command_sender=cmd)
        p.on_process_action("processor", "stop")
        cmd.send_command.assert_called_once_with("processor", "process.stop", {})

    def test_on_process_action_restart(self):
        cmd = _cmd()
        p = ProcessesPresenter(make_processes_services(), command_sender=cmd)
        p.on_process_action("renderer", "restart")
        cmd.send_command.assert_called_once_with("renderer", "process.restart", {})

    def test_on_process_action_prefers_bridge(self):
        """topology_bridge имеет приоритет над command_sender (Phase 12 IPC)."""
        cmd = _cmd()
        bridge = MagicMock()
        p = ProcessesPresenter(
            make_processes_services(),
            command_sender=cmd,
            topology_bridge=bridge,
        )
        p.on_process_action("camera_0", "start")
        bridge.start_process.assert_called_once_with("camera_0")
        cmd.send_command.assert_not_called()

    def test_get_processes_via_holder(self):
        """Production-путь: topology через TopologyRepositoryFromHolder."""
        services = make_processes_services(use_holder=True)
        p = ProcessesPresenter(services)
        procs = p.get_processes()
        assert len(procs) == 3

    def test_category_title_unknown(self):
        """Неизвестная категория возвращает capitalize."""
        p = ProcessesPresenter(make_processes_services())
        assert p.category_title("custom") == "Custom"

    def test_group_by_category_empty(self):
        p = ProcessesPresenter(make_processes_services())
        groups = p.group_by_category([])
        assert groups == {}

    def test_get_process_by_name(self):
        p = ProcessesPresenter(make_processes_services())
        proc = p.get_process_by_name("camera_0")
        assert proc is not None
        assert proc.name == "camera_0"

    def test_get_process_by_name_not_found(self):
        p = ProcessesPresenter(make_processes_services())
        assert p.get_process_by_name("nonexistent") is None

    def test_get_process_names(self):
        p = ProcessesPresenter(make_processes_services())
        names = p.get_process_names()
        assert len(names) == 3
        assert "camera_0" in names
        assert "processor" in names
        assert "renderer" in names

    def test_get_table_rows(self):
        p = ProcessesPresenter(make_processes_services())
        rows = p.get_table_rows()
        assert len(rows) == 3
        assert rows[0]["Имя"] in ("camera_0", "processor", "renderer")
        assert "Категория" in rows[0]
        assert "Статус" in rows[0]

    def test_get_detail_metrics(self):
        p = ProcessesPresenter(make_processes_services())
        metrics = p.get_detail_metrics("camera_0")
        assert "Категория" in metrics
        assert "Статус" in metrics
        assert "Плагины" in metrics

    def test_get_detail_metrics_not_found(self):
        p = ProcessesPresenter(make_processes_services())
        assert p.get_detail_metrics("nonexistent") == {}


# ------------------------------------------------------------------ #
#  Tab                                                                 #
# ------------------------------------------------------------------ #


class TestProcessesTab:
    def test_create(self, qtbot):
        cmd = _cmd()
        runtime = make_processes_runtime(command_sender=cmd)
        tab = ProcessesTab.create(make_processes_services(), runtime)
        qtbot.addWidget(tab)
        assert tab is not None

    def test_cards_created(self, qtbot):
        tab = ProcessesTab(make_processes_services(), command_sender=_cmd())
        qtbot.addWidget(tab)
        assert len(tab._cards) == 3
        assert "camera_0" in tab._cards

    def test_card_action_sends_command(self, qtbot):
        cmd = _cmd()
        tab = ProcessesTab(make_processes_services(), command_sender=cmd)
        qtbot.addWidget(tab)
        tab._on_card_action("camera_0", "start")
        cmd.send_command.assert_called()

    def test_toolbar_start_all(self, qtbot):
        """Legacy: обратная совместимость _on_toolbar_action."""
        cmd = _cmd()
        tab = ProcessesTab(make_processes_services(), command_sender=cmd)
        qtbot.addWidget(tab)
        tab._on_toolbar_action("start_all")
        assert cmd.send_command.call_count == 3

    def test_toolbar_stop_all(self, qtbot):
        """Legacy: обратная совместимость _on_toolbar_action."""
        cmd = _cmd()
        tab = ProcessesTab(make_processes_services(), command_sender=cmd)
        qtbot.addWidget(tab)
        tab._on_toolbar_action("stop_all")
        assert cmd.send_command.call_count == 3

    def test_empty_topology(self, qtbot):
        tab = ProcessesTab(make_processes_services(topology_processes=[]), command_sender=_cmd())
        qtbot.addWidget(tab)
        assert len(tab._cards) == 0

    def test_all_card_keys_present(self, qtbot):
        """Все три процесса из дефолтного topology должны иметь карточки."""
        tab = ProcessesTab(make_processes_services(), command_sender=_cmd())
        qtbot.addWidget(tab)
        assert "camera_0" in tab._cards
        assert "processor" in tab._cards
        assert "renderer" in tab._cards

    # Тесты для 3-колоночного layout

    def test_nav_has_all_item(self, qtbot):
        """Первый элемент навигации — «Все процессы»."""
        tab = ProcessesTab(make_processes_services(), command_sender=_cmd())
        qtbot.addWidget(tab)
        first = tab._nav_list.item(0)
        assert first is not None
        assert first.text() == "Все процессы"
        assert first.data(Qt.ItemDataRole.UserRole) == ALL_PROCESSES_KEY

    def test_nav_has_process_items(self, qtbot):
        """Навигация содержит все процессы из topology."""
        tab = ProcessesTab(make_processes_services(), command_sender=_cmd())
        qtbot.addWidget(tab)
        # 1 (Все процессы) + 3 процесса
        assert tab._nav_list.count() == 4
        names = [tab._nav_list.item(i).text() for i in range(1, tab._nav_list.count())]
        assert "camera_0" in names
        assert "processor" in names
        assert "renderer" in names

    def test_default_selection_is_all(self, qtbot):
        """По умолчанию выбран «Все процессы»."""
        tab = ProcessesTab(make_processes_services(), command_sender=_cmd())
        qtbot.addWidget(tab)
        assert tab._selected_process is None
        # Активная content-страница — AllProcessesPanel в Cards-режиме.
        assert tab._content_stack.currentWidget() is tab._all_panel
        assert tab._all_panel._inner_stack.currentIndex() == 0  # Cards

    def test_view_toggle_switches_page(self, qtbot):
        """Переключение Cards→Table меняет inner_stack текущей панели."""
        tab = ProcessesTab(make_processes_services(), command_sender=_cmd())
        qtbot.addWidget(tab)
        assert tab._all_panel._inner_stack.currentIndex() == 0
        from multiprocess_prototype.frontend.forms.view_mode_toggle import ViewMode

        tab._toggle.set_mode(ViewMode.TABLE)
        assert tab._all_panel._inner_stack.currentIndex() == 1  # Table

    def test_select_process_shows_detail(self, qtbot):
        """Выбор процесса показывает детальную карточку."""
        tab = ProcessesTab(make_processes_services(), command_sender=_cmd())
        qtbot.addWidget(tab)
        tab._nav_list.setCurrentRow(1)
        assert tab._selected_process is not None
        single = tab._single_panels[tab._selected_process]
        assert tab._content_stack.currentWidget() is single
        assert single._inner_stack.currentIndex() == 0  # Cards
        assert tab._detail_card is not None

    def test_select_all_returns_to_summary(self, qtbot):
        """Возврат к «Все процессы» показывает сводку."""
        tab = ProcessesTab(make_processes_services(), command_sender=_cmd())
        qtbot.addWidget(tab)
        tab._nav_list.setCurrentRow(1)
        tab._nav_list.setCurrentRow(0)
        assert tab._selected_process is None
        assert tab._content_stack.currentWidget() is tab._all_panel
        assert tab._all_panel._inner_stack.currentIndex() == 0  # Cards

    def test_buttons_disabled_on_all(self, qtbot):
        """Кнопки управления неактивны при выборе «Все процессы»."""
        tab = ProcessesTab(make_processes_services(), command_sender=_cmd())
        qtbot.addWidget(tab)
        assert not tab._btn_delete.isEnabled()
        assert not tab._btn_start.isEnabled()
        assert not tab._btn_stop.isEnabled()

    def test_buttons_enabled_on_selection(self, qtbot):
        """Кнопки управления активны при выборе конкретного процесса."""
        tab = ProcessesTab(make_processes_services(), command_sender=_cmd())
        qtbot.addWidget(tab)
        tab._nav_list.setCurrentRow(1)
        assert tab._btn_delete.isEnabled()
        assert tab._btn_start.isEnabled()
        assert tab._btn_stop.isEnabled()

    def test_single_process_table_view(self, qtbot):
        """Таблица одного процесса содержит key-value строки."""
        tab = ProcessesTab(make_processes_services(), command_sender=_cmd())
        qtbot.addWidget(tab)
        tab._nav_list.setCurrentRow(1)
        from multiprocess_prototype.frontend.forms.view_mode_toggle import ViewMode

        tab._toggle.set_mode(ViewMode.TABLE)
        single = tab._single_panels[tab._selected_process]
        assert single._inner_stack.currentIndex() == 1  # Table
        assert tab._detail_table.rowCount() > 0

    def test_empty_topology_nav(self, qtbot):
        """При пустом topology навигация содержит только «Все процессы»."""
        tab = ProcessesTab(make_processes_services(topology_processes=[]), command_sender=_cmd())
        qtbot.addWidget(tab)
        assert tab._nav_list.count() == 1
        assert tab._nav_list.item(0).text() == "Все процессы"


# ------------------------------------------------------------------ #
#  Protected processes                                                 #
# ------------------------------------------------------------------ #


_PROTECTED_PROCESSES = [
    {
        "process_name": "gui",
        "protected": True,
        "plugins": [{"plugin_name": "renderer", "category": "rendering"}],
    },
    {
        "process_name": "camera_0",
        "plugins": [{"plugin_name": "capture", "category": "source"}],
    },
]


class TestProtectedProcesses:
    def test_is_protected_true(self):
        """presenter.is_protected('gui') == True при protected: true в topology."""
        p = ProcessesPresenter(make_processes_services(topology_processes=_PROTECTED_PROCESSES))
        assert p.is_protected("gui") is True

    def test_is_protected_false_for_regular(self):
        """camera_0 без protected → False."""
        p = ProcessesPresenter(make_processes_services(topology_processes=_PROTECTED_PROCESSES))
        assert p.is_protected("camera_0") is False

    def test_is_protected_missing_key(self):
        """Topology без поля protected вообще → False (backward-compat)."""
        p = ProcessesPresenter(
            make_processes_services(topology_processes=[{"process_name": "proc_no_flag", "plugins": []}])
        )
        assert p.is_protected("proc_no_flag") is False

    def test_is_protected_none_selected(self):
        """is_protected('nonexistent') → False без исключений."""
        p = ProcessesPresenter(make_processes_services(topology_processes=_PROTECTED_PROCESSES))
        assert p.is_protected("nonexistent") is False

    def test_buttons_disabled_for_protected(self, qtbot):
        """После выбора gui: _btn_delete и _btn_stop disabled, _btn_start enabled."""
        tab = ProcessesTab(
            make_processes_services(topology_processes=_PROTECTED_PROCESSES),
            command_sender=_cmd(),
        )
        qtbot.addWidget(tab)

        gui_row = None
        for i in range(tab._nav_list.count()):
            if tab._nav_list.item(i).text() == "gui":
                gui_row = i
                break
        assert gui_row is not None, "Процесс gui должен быть в навигации"

        tab._nav_list.setCurrentRow(gui_row)
        assert tab._btn_delete.isEnabled() is False
        assert tab._btn_stop.isEnabled() is False
        assert tab._btn_start.isEnabled() is True

    def test_protected_buttons_have_explanatory_tooltip(self, qtbot):
        """Disabled-кнопки protected процесса несут тултип «Системный процесс …»."""
        tab = ProcessesTab(
            make_processes_services(topology_processes=_PROTECTED_PROCESSES),
            command_sender=_cmd(),
        )
        qtbot.addWidget(tab)

        gui_row = next(i for i in range(tab._nav_list.count()) if tab._nav_list.item(i).text() == "gui")
        tab._nav_list.setCurrentRow(gui_row)

        assert "Системный процесс" in tab._btn_delete.toolTip()
        assert "Системный процесс" in tab._btn_stop.toolTip()

    def test_buttons_enabled_for_unprotected(self, qtbot):
        """После выбора camera_0: _btn_delete и _btn_stop enabled."""
        tab = ProcessesTab(
            make_processes_services(topology_processes=_PROTECTED_PROCESSES),
            command_sender=_cmd(),
        )
        qtbot.addWidget(tab)

        cam_row = None
        for i in range(tab._nav_list.count()):
            if tab._nav_list.item(i).text() == "camera_0":
                cam_row = i
                break
        assert cam_row is not None

        tab._nav_list.setCurrentRow(cam_row)
        assert tab._btn_delete.isEnabled() is True
        assert tab._btn_stop.isEnabled() is True

    def test_single_panel_no_stop_for_protected(self, qtbot):
        """SingleProcessPanel для gui не содержит CardAction('stop')."""
        from multiprocess_prototype.frontend.widgets.tabs.processes._panels import SingleProcessPanel

        presenter = ProcessesPresenter(make_processes_services(topology_processes=_PROTECTED_PROCESSES))
        panel = SingleProcessPanel(presenter, None, "gui")
        qtbot.addWidget(panel)

        card = getattr(panel, "_card", None)
        assert card is not None, "_card должна быть создана для существующего процесса"
        assert "stop" not in card._action_buttons, "Кнопка 'stop' не должна присутствовать для protected процесса"

    def test_toolbar_stop_skips_protected(self, qtbot):
        """toolbar stop_all не шлёт stop для protected процессов."""
        cmd = _cmd()
        tab = ProcessesTab(
            make_processes_services(topology_processes=_PROTECTED_PROCESSES),
            command_sender=cmd,
        )
        qtbot.addWidget(tab)
        tab._on_toolbar_action("stop_all")
        calls = cmd.send_command.call_args_list
        stopped = [c[0][0] for c in calls if c[0][1] == "process.stop"]
        assert "gui" not in stopped
        assert "camera_0" in stopped
