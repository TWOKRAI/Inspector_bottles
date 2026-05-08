"""Тесты для ProcessesTab и ProcessesPresenter."""
from unittest.mock import MagicMock

import pytest

from multiprocess_prototype_2.frontend.widgets.tabs.processes.tab import ProcessesTab
from multiprocess_prototype_2.frontend.widgets.tabs.processes.presenter import ProcessesPresenter
from multiprocess_prototype_2.frontend.widgets.tabs.processes.data import ProcessInfo


def _make_mock_ctx(topology_processes=None):
    """Создать mock AppContext с topology."""
    ctx = MagicMock()
    ctx.config = {
        "topology": {
            "processes": topology_processes if topology_processes is not None else [
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
        ctx.command_sender.send_command.assert_called_once_with(
            "camera_0", "process.start", {}
        )

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
        ctx.command_sender.send_command.assert_called_once_with(
            "processor", "process.stop", {}
        )

    def test_on_process_action_restart(self):
        ctx = _make_mock_ctx()
        p = ProcessesPresenter(ctx)
        p.on_process_action("renderer", "restart")
        ctx.command_sender.send_command.assert_called_once_with(
            "renderer", "process.restart", {}
        )

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
        ctx = _make_mock_ctx()
        tab = ProcessesTab(ctx)
        qtbot.addWidget(tab)
        tab._on_toolbar_action("start_all")
        assert ctx.command_sender.send_command.call_count == 3

    def test_toolbar_stop_all(self, qtbot):
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
