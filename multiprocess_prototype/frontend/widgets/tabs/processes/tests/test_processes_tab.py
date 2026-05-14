"""Тесты для ProcessesTab и ProcessesPresenter."""

from unittest.mock import MagicMock


from PySide6.QtCore import Qt

from multiprocess_prototype.frontend.widgets.tabs.processes.tab import ProcessesTab
from multiprocess_prototype.frontend.widgets.tabs.processes.presenter import ProcessesPresenter
from multiprocess_prototype.frontend.widgets.tabs.processes.data import (
    ALL_PROCESSES_KEY,
    ProcessInfo,
)


def _make_mock_ctx(topology_processes=None):
    """Создать mock AppContext с topology."""
    ctx = MagicMock()
    ctx.config = {
        "topology": {
            "processes": topology_processes
            if topology_processes is not None
            else [
                {
                    "process_name": "camera_0",
                    "plugins": [{"plugin_name": "capture", "category": "source"}],
                },
                {
                    "process_name": "processor",
                    "plugins": [{"plugin_name": "color_mask", "category": "processing"}],
                },
                {
                    "process_name": "renderer",
                    "plugins": [{"plugin_name": "render_overlay", "category": "rendering"}],
                },
            ],
        },
    }
    ctx.extras = {}
    ctx.plugin_registry.return_value = None
    ctx.bindings.return_value = None
    ctx.command_sender = MagicMock()
    return ctx


# ------------------------------------------------------------------ #
#  Presenter                                                           #
# ------------------------------------------------------------------ #


class TestProcessesPresenter:
    def test_get_processes(self):
        ctx = _make_mock_ctx()
        p = ProcessesPresenter(ctx)
        procs = p.get_processes()
        assert len(procs) == 3
        names = [proc.name for proc in procs]
        assert "camera_0" in names
        assert "processor" in names

    def test_group_by_category(self):
        ctx = _make_mock_ctx()
        p = ProcessesPresenter(ctx)
        procs = [
            ProcessInfo("a", "source"),
            ProcessInfo("b", "processing"),
            ProcessInfo("c", "source"),
        ]
        groups = p.group_by_category(procs)
        assert len(groups["source"]) == 2
        assert len(groups["processing"]) == 1

    def test_category_title(self):
        ctx = _make_mock_ctx()
        p = ProcessesPresenter(ctx)
        assert p.category_title("source") == "Источники"
        assert p.category_title("processing") == "Обработка"

    def test_on_process_action(self):
        ctx = _make_mock_ctx()
        p = ProcessesPresenter(ctx)
        p.on_process_action("camera_0", "start")
        ctx.command_sender.send_command.assert_called_once_with("camera_0", "process.start", {})

    def test_get_processes_from_extras(self):
        """Проверяем fallback на extras когда topology нет в config."""
        ctx = MagicMock()
        ctx.config = {}
        ctx.extras = {
            "topology": {
                "processes": [
                    {"process_name": "extra_proc", "plugins": []},
                ]
            }
        }
        ctx.plugin_registry.return_value = None
        ctx.bindings.return_value = None

        p = ProcessesPresenter(ctx)
        procs = p.get_processes()
        assert len(procs) == 1
        assert procs[0].name == "extra_proc"

    def test_get_processes_empty_topology(self):
        """Graceful degradation при отсутствии topology."""
        ctx = MagicMock()
        ctx.config = {}
        ctx.extras = {}
        ctx.plugin_registry.return_value = None
        ctx.bindings.return_value = None

        p = ProcessesPresenter(ctx)
        procs = p.get_processes()
        assert procs == []

    def test_on_process_action_stop(self):
        ctx = _make_mock_ctx()
        p = ProcessesPresenter(ctx)
        p.on_process_action("processor", "stop")
        ctx.command_sender.send_command.assert_called_once_with("processor", "process.stop", {})

    def test_on_process_action_restart(self):
        ctx = _make_mock_ctx()
        p = ProcessesPresenter(ctx)
        p.on_process_action("renderer", "restart")
        ctx.command_sender.send_command.assert_called_once_with("renderer", "process.restart", {})

    def test_category_title_unknown(self):
        """Неизвестная категория возвращает capitalize."""
        ctx = _make_mock_ctx()
        p = ProcessesPresenter(ctx)
        assert p.category_title("custom") == "Custom"

    def test_group_by_category_empty(self):
        ctx = _make_mock_ctx()
        p = ProcessesPresenter(ctx)
        groups = p.group_by_category([])
        assert groups == {}

    # Новые тесты для добавленных методов

    def test_get_process_by_name(self):
        ctx = _make_mock_ctx()
        p = ProcessesPresenter(ctx)
        proc = p.get_process_by_name("camera_0")
        assert proc is not None
        assert proc.name == "camera_0"

    def test_get_process_by_name_not_found(self):
        ctx = _make_mock_ctx()
        p = ProcessesPresenter(ctx)
        assert p.get_process_by_name("nonexistent") is None

    def test_get_process_names(self):
        ctx = _make_mock_ctx()
        p = ProcessesPresenter(ctx)
        names = p.get_process_names()
        assert len(names) == 3
        assert "camera_0" in names
        assert "processor" in names
        assert "renderer" in names

    def test_get_table_rows(self):
        ctx = _make_mock_ctx()
        p = ProcessesPresenter(ctx)
        rows = p.get_table_rows()
        assert len(rows) == 3
        assert rows[0]["Имя"] in ("camera_0", "processor", "renderer")
        assert "Категория" in rows[0]
        assert "Статус" in rows[0]

    def test_get_detail_metrics(self):
        ctx = _make_mock_ctx()
        p = ProcessesPresenter(ctx)
        metrics = p.get_detail_metrics("camera_0")
        assert "Категория" in metrics
        assert "Статус" in metrics
        assert "Плагины" in metrics

    def test_get_detail_metrics_not_found(self):
        ctx = _make_mock_ctx()
        p = ProcessesPresenter(ctx)
        assert p.get_detail_metrics("nonexistent") == {}


# ------------------------------------------------------------------ #
#  Tab                                                                 #
# ------------------------------------------------------------------ #


class TestProcessesTab:
    def test_create(self, qtbot):
        ctx = _make_mock_ctx()
        tab = ProcessesTab.create(ctx)
        qtbot.addWidget(tab)
        assert tab is not None

    def test_cards_created(self, qtbot):
        ctx = _make_mock_ctx()
        tab = ProcessesTab(ctx)
        qtbot.addWidget(tab)
        assert len(tab._cards) == 3
        assert "camera_0" in tab._cards

    def test_card_action_sends_command(self, qtbot):
        ctx = _make_mock_ctx()
        tab = ProcessesTab(ctx)
        qtbot.addWidget(tab)
        tab._on_card_action("camera_0", "start")
        ctx.command_sender.send_command.assert_called()

    def test_toolbar_start_all(self, qtbot):
        """Legacy: обратная совместимость _on_toolbar_action."""
        ctx = _make_mock_ctx()
        tab = ProcessesTab(ctx)
        qtbot.addWidget(tab)
        tab._on_toolbar_action("start_all")
        assert ctx.command_sender.send_command.call_count == 3

    def test_toolbar_stop_all(self, qtbot):
        """Legacy: обратная совместимость _on_toolbar_action."""
        ctx = _make_mock_ctx()
        tab = ProcessesTab(ctx)
        qtbot.addWidget(tab)
        tab._on_toolbar_action("stop_all")
        assert ctx.command_sender.send_command.call_count == 3

    def test_empty_topology(self, qtbot):
        ctx = _make_mock_ctx(topology_processes=[])
        tab = ProcessesTab(ctx)
        qtbot.addWidget(tab)
        assert len(tab._cards) == 0

    def test_all_card_keys_present(self, qtbot):
        """Все три процесса из дефолтного topology должны иметь карточки."""
        ctx = _make_mock_ctx()
        tab = ProcessesTab(ctx)
        qtbot.addWidget(tab)
        assert "camera_0" in tab._cards
        assert "processor" in tab._cards
        assert "renderer" in tab._cards

    # Новые тесты для 3-колоночного layout

    def test_nav_has_all_item(self, qtbot):
        """Первый элемент навигации — «Все процессы»."""
        ctx = _make_mock_ctx()
        tab = ProcessesTab(ctx)
        qtbot.addWidget(tab)
        first = tab._nav_list.item(0)
        assert first is not None
        assert first.text() == "Все процессы"
        assert first.data(Qt.ItemDataRole.UserRole) == ALL_PROCESSES_KEY

    def test_nav_has_process_items(self, qtbot):
        """Навигация содержит все процессы из topology."""
        ctx = _make_mock_ctx()
        tab = ProcessesTab(ctx)
        qtbot.addWidget(tab)
        # 1 (Все процессы) + 3 процесса
        assert tab._nav_list.count() == 4
        names = [tab._nav_list.item(i).text() for i in range(1, tab._nav_list.count())]
        assert "camera_0" in names
        assert "processor" in names
        assert "renderer" in names

    def test_default_selection_is_all(self, qtbot):
        """По умолчанию выбран «Все процессы»."""
        ctx = _make_mock_ctx()
        tab = ProcessesTab(ctx)
        qtbot.addWidget(tab)
        assert tab._selected_process is None
        assert tab._center_stack.currentIndex() == 0  # _PAGE_ALL_CARDS

    def test_view_toggle_switches_page(self, qtbot):
        """Переключение Cards→Table меняет страницу стека."""
        ctx = _make_mock_ctx()
        tab = ProcessesTab(ctx)
        qtbot.addWidget(tab)
        # Начинаем с Cards (page 0)
        assert tab._center_stack.currentIndex() == 0
        # Переключаем на Table
        from multiprocess_prototype.frontend.forms.view_mode_toggle import ViewMode

        tab._toggle.set_mode(ViewMode.TABLE)
        assert tab._center_stack.currentIndex() == 1  # _PAGE_ALL_TABLE

    def test_select_process_shows_detail(self, qtbot):
        """Выбор процесса показывает детальную карточку."""
        ctx = _make_mock_ctx()
        tab = ProcessesTab(ctx)
        qtbot.addWidget(tab)
        # Выбрать второй элемент (первый процесс)
        tab._nav_list.setCurrentRow(1)
        assert tab._selected_process is not None
        assert tab._center_stack.currentIndex() == 2  # _PAGE_SINGLE_CARDS
        assert tab._detail_card is not None

    def test_select_all_returns_to_summary(self, qtbot):
        """Возврат к «Все процессы» показывает сводку."""
        ctx = _make_mock_ctx()
        tab = ProcessesTab(ctx)
        qtbot.addWidget(tab)
        # Выбрать процесс, потом вернуться
        tab._nav_list.setCurrentRow(1)
        tab._nav_list.setCurrentRow(0)
        assert tab._selected_process is None
        assert tab._center_stack.currentIndex() == 0  # _PAGE_ALL_CARDS

    def test_buttons_disabled_on_all(self, qtbot):
        """Кнопки управления неактивны при выборе «Все процессы»."""
        ctx = _make_mock_ctx()
        tab = ProcessesTab(ctx)
        qtbot.addWidget(tab)
        assert not tab._btn_delete.isEnabled()
        assert not tab._btn_start.isEnabled()
        assert not tab._btn_stop.isEnabled()

    def test_buttons_enabled_on_selection(self, qtbot):
        """Кнопки управления активны при выборе конкретного процесса."""
        ctx = _make_mock_ctx()
        tab = ProcessesTab(ctx)
        qtbot.addWidget(tab)
        tab._nav_list.setCurrentRow(1)
        assert tab._btn_delete.isEnabled()
        assert tab._btn_start.isEnabled()
        assert tab._btn_stop.isEnabled()

    def test_single_process_table_view(self, qtbot):
        """Таблица одного процесса содержит key-value строки."""
        ctx = _make_mock_ctx()
        tab = ProcessesTab(ctx)
        qtbot.addWidget(tab)
        tab._nav_list.setCurrentRow(1)
        from multiprocess_prototype.frontend.forms.view_mode_toggle import ViewMode

        tab._toggle.set_mode(ViewMode.TABLE)
        assert tab._center_stack.currentIndex() == 3  # _PAGE_SINGLE_TABLE
        assert tab._detail_table.rowCount() > 0

    def test_empty_topology_nav(self, qtbot):
        """При пустом topology навигация содержит только «Все процессы»."""
        ctx = _make_mock_ctx(topology_processes=[])
        tab = ProcessesTab(ctx)
        qtbot.addWidget(tab)
        assert tab._nav_list.count() == 1
        assert tab._nav_list.item(0).text() == "Все процессы"
