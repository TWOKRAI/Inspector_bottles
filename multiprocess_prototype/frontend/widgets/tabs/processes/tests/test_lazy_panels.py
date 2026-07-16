# -*- coding: utf-8 -*-
"""Тесты ленивого создания SingleProcessPanel/AllProcessesPanel (Task 0.4, «Хвост»).

ProcessesTab включает BaseListNavTab(lazy_content=True): при открытии
строится только активная (по умолчанию — «Все процессы») панель, панели
остальных процессов создаются лениво при первом переключении на них.
См. plans/gui-telemetry-read-model.md (Хвост 0.4).
"""

from __future__ import annotations

from unittest.mock import MagicMock

from multiprocess_prototype.frontend.bridge.command_sender import CommandSender
from multiprocess_prototype.frontend.widgets.tabs.processes.data import ALL_PROCESSES_KEY
from multiprocess_prototype.frontend.widgets.tabs.processes.tab import ProcessesTab

from ._helpers import make_processes_services


def _cmd() -> MagicMock:
    return MagicMock(spec=CommandSender)


class _CountingProcessesTab(ProcessesTab):
    """ProcessesTab со счётчиком вызовов _create_item_widget (spy)."""

    def __init__(self, *args, **kwargs) -> None:
        self.create_calls: list[str] = []
        super().__init__(*args, **kwargs)

    def _create_item_widget(self, key: str):  # noqa: ANN201 — тестовый spy, тип как у базового
        self.create_calls.append(key)
        return super()._create_item_widget(key)


class TestLazyPanels:
    def test_open_creates_only_active_panel(self, qtbot) -> None:
        """Открытие вкладки с N процессами создаёт РОВНО 1 панель (активную)."""
        tab = _CountingProcessesTab(make_processes_services(), command_sender=_cmd())
        qtbot.addWidget(tab)

        assert len(tab.create_calls) == 1
        assert tab.create_calls == [ALL_PROCESSES_KEY]
        # Остальные процессы (3 в дефолтной topology) числятся в nav, но их
        # панели ещё не построены.
        assert tab._single_panels == {}

    def test_selecting_process_creates_its_panel(self, qtbot) -> None:
        """Переключение на процесс лениво строит его панель (итого 2)."""
        tab = _CountingProcessesTab(make_processes_services(), command_sender=_cmd())
        qtbot.addWidget(tab)

        tab._nav_list.setCurrentRow(1)  # первый процесс после «Все процессы»

        assert len(tab.create_calls) == 2
        assert tab._selected_process is not None
        assert tab._selected_process in tab.create_calls
        assert tab._selected_process in tab._single_panels

    def test_reselecting_same_process_does_not_recreate(self, qtbot) -> None:
        """Повторный выбор уже показанного процесса не пересоздаёт панель."""
        tab = _CountingProcessesTab(make_processes_services(), command_sender=_cmd())
        qtbot.addWidget(tab)

        tab._nav_list.setCurrentRow(1)
        tab._nav_list.setCurrentRow(0)  # обратно к «Все процессы» (уже создана)
        tab._nav_list.setCurrentRow(1)  # обратно к тому же процессу

        assert len(tab.create_calls) == 2  # «Все процессы» + один процесс, без дублей

    def test_switching_between_two_processes_creates_both(self, qtbot) -> None:
        """Переключение между двумя разными процессами создаёт обе панели (итого 3)."""
        tab = _CountingProcessesTab(make_processes_services(), command_sender=_cmd())
        qtbot.addWidget(tab)

        tab._nav_list.setCurrentRow(1)
        tab._nav_list.setCurrentRow(2)

        assert len(tab.create_calls) == 3
        assert len(tab._single_panels) == 2

    def test_lazily_created_panel_shows_live_state(self, qtbot) -> None:
        """Лениво созданная панель отображает актуальные данные presenter'а."""
        tab = _CountingProcessesTab(make_processes_services(), command_sender=_cmd())
        qtbot.addWidget(tab)

        tab._nav_list.setCurrentRow(1)
        single = tab._single_panels[tab._selected_process]
        assert tab._content_stack.currentWidget() is single
        assert single._inner_stack.currentIndex() == 0  # Cards
