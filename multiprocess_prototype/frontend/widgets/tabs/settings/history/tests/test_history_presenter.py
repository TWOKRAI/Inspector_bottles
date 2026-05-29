# -*- coding: utf-8 -*-
"""Тесты HistoryPresenter — pure-Python, без Qt.

G.4.4: presenter читает domain-историю (``services.commands.history()`` →
``HistoryEntry`` label/command_type/timestamp), таблица — 3 колонки
(Время / Тип / Описание). Фантомный ActionBus-путь (``action_bus()``) удалён.

Проверяет:
  - test_refresh_populates_table      : presenter заполняет таблицу из commands.history()
  - test_refresh_enables_buttons      : после refresh кнопки enabled/disabled корректно
  - test_refresh_disables_save_when_empty
  - test_refresh_scrolls_when_has_rows
  - test_refresh_empty_history        : пустая история не бросает исключений
  - test_clear_calls_clear_history    : presenter вызывает commands.clear_history()
  - test_save_to_csv_writes_file      : CSV-файл содержит правильные строки (3 колонки)
  - test_save_skips_when_no_path / no_history
"""

from __future__ import annotations

import csv
from collections.abc import Callable
from pathlib import Path
from unittest.mock import MagicMock, patch

from multiprocess_prototype.domain.protocols import HistoryEntry
from multiprocess_prototype.domain.tests.conftest import make_test_app_services
from multiprocess_prototype.frontend.widgets.tabs.settings.history.presenter import (
    HistoryPresenter,
)


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------


def _entry(
    *,
    label: str = "AddProcess: camera",
    command_type: str = "AddProcess",
    timestamp: float = 1_700_000_000.0,
) -> HistoryEntry:
    """Фабрика domain HistoryEntry."""
    return HistoryEntry(label=label, command_type=command_type, timestamp=timestamp)


class _FakeHistoryCommands:
    """Лёгкий CommandDispatcher с настраиваемой историей (G.4.4).

    HistoryPresenter — чистая проекция: читает history()/can_undo()/can_redo() и
    делегирует clear_history(). Этого фейка достаточно для unit-теста presenter'а
    без сборки реального orchestrator (его history() покрыт в test_command_dispatcher).
    """

    def __init__(
        self,
        entries: list[HistoryEntry] | None = None,
        *,
        can_undo: bool = True,
        can_redo: bool = False,
    ) -> None:
        self._entries = entries or []
        self._can_undo = can_undo
        self._can_redo = can_redo
        self.clear_history_calls = 0

    def dispatch(self, command):  # noqa: ANN001 — Protocol-совместимость
        return []

    def undo(self) -> bool:
        return False

    def redo(self) -> bool:
        return False

    def can_undo(self) -> bool:
        return self._can_undo

    def can_redo(self) -> bool:
        return self._can_redo

    def history(self, n: int = 20) -> list[HistoryEntry]:
        # n=0 → все записи (как у ProjectHistory.entries / ActionBus.history)
        return list(self._entries) if n == 0 else list(self._entries[-n:])

    def clear_history(self) -> None:
        self.clear_history_calls += 1
        self._entries = []

    def add_change_callback(self, cb: Callable[[], None]) -> None:
        pass


def _make_view() -> MagicMock:
    return MagicMock()


def _make_presenter(
    commands: _FakeHistoryCommands,
    view: MagicMock | None = None,
) -> HistoryPresenter:
    if view is None:
        view = _make_view()
    services = make_test_app_services(commands=commands)
    return HistoryPresenter(view=view, rm=None, ui=None, services=services)


# ---------------------------------------------------------------------------
# Тесты
# ---------------------------------------------------------------------------


class TestHistoryPresenterRefresh:
    """Тесты метода refresh()."""

    def test_refresh_populates_table(self) -> None:
        """refresh() → view.set_table_data со строками (Время, Тип, Описание)."""
        commands = _FakeHistoryCommands([_entry(label="AddProcess: camera", command_type="AddProcess")])
        view = _make_view()
        presenter = _make_presenter(commands, view)

        presenter.refresh()

        view.set_table_data.assert_called_once()
        rows = view.set_table_data.call_args[0][0]
        assert len(rows) == 1
        ts, command_type, label = rows[0]
        assert command_type == "AddProcess"
        assert label == "AddProcess: camera"
        assert ts  # отформатированное время непустое

    def test_refresh_enables_buttons(self) -> None:
        """has_history → save enabled; can_undo → clear enabled."""
        commands = _FakeHistoryCommands([_entry()], can_undo=True, can_redo=False)
        view = _make_view()
        presenter = _make_presenter(commands, view)

        presenter.refresh()

        view.set_save_enabled.assert_called_with(True)
        view.set_clear_enabled.assert_called_with(True)

    def test_refresh_disables_save_when_empty(self) -> None:
        """Пустая история → save и clear disabled."""
        commands = _FakeHistoryCommands([], can_undo=False, can_redo=False)
        view = _make_view()
        presenter = _make_presenter(commands, view)

        presenter.refresh()

        view.set_table_data.assert_called_with([])
        view.set_save_enabled.assert_called_with(False)
        view.set_clear_enabled.assert_called_with(False)

    def test_refresh_clear_enabled_on_redo_only(self) -> None:
        """clear enabled, если есть redo (даже при пустом undo)."""
        commands = _FakeHistoryCommands([], can_undo=False, can_redo=True)
        view = _make_view()
        presenter = _make_presenter(commands, view)

        presenter.refresh()

        view.set_clear_enabled.assert_called_with(True)

    def test_refresh_scrolls_when_has_rows(self) -> None:
        """При наличии строк вызывается view.scroll_to_bottom()."""
        commands = _FakeHistoryCommands([_entry()])
        view = _make_view()
        presenter = _make_presenter(commands, view)

        presenter.refresh()

        view.scroll_to_bottom.assert_called_once()

    def test_refresh_empty_history(self) -> None:
        """Стандартный FakeCommandDispatcher (пустая история) не бросает исключений."""
        view = _make_view()
        services = make_test_app_services()  # FakeCommandDispatcher: history() → []
        presenter = HistoryPresenter(view=view, rm=None, ui=None, services=services)

        presenter.refresh()

        view.set_table_data.assert_called_with([])
        view.set_save_enabled.assert_called_with(False)
        view.set_clear_enabled.assert_called_with(False)


class TestHistoryPresenterClear:
    """Тесты метода clear()."""

    def test_clear_calls_clear_history(self) -> None:
        """presenter.clear() делегирует в commands.clear_history()."""
        commands = _FakeHistoryCommands([_entry()])
        presenter = _make_presenter(commands)

        presenter.clear()

        assert commands.clear_history_calls == 1

    def test_clear_noop_on_default_fake(self) -> None:
        """clear() на стандартном FakeCommandDispatcher не бросает исключений."""
        view = _make_view()
        services = make_test_app_services()
        presenter = HistoryPresenter(view=view, rm=None, ui=None, services=services)

        presenter.clear()  # clear_history() no-op в FakeCommandDispatcher


class TestHistoryPresenterSaveToCsv:
    """Тесты метода save_to_csv()."""

    def test_save_to_csv_writes_file(self, tmp_path: Path) -> None:
        """save_to_csv() создаёт CSV с заголовком (Время, Тип, Описание) и данными."""
        csv_path = str(tmp_path / "history.csv")
        commands = _FakeHistoryCommands(
            [_entry(label="ConnectWire: a→b", command_type="ConnectWire", timestamp=1_700_000_000.0)]
        )
        view = _make_view()
        view.get_save_path.return_value = csv_path

        presenter = _make_presenter(commands, view)
        presenter.save_to_csv()

        with open(csv_path, encoding="utf-8-sig") as f:
            reader = csv.reader(f, delimiter=";")
            header = next(reader)
            assert header == ["Время", "Тип", "Описание"]
            rows = list(reader)

        assert len(rows) == 1
        _ts, command_type, label = rows[0]
        assert command_type == "ConnectWire"
        assert label == "ConnectWire: a→b"

    def test_save_skips_when_no_path(self) -> None:
        """get_save_path() вернул None → файл не создаётся."""
        commands = _FakeHistoryCommands([_entry()])
        view = _make_view()
        view.get_save_path.return_value = None

        presenter = _make_presenter(commands, view)

        with patch("builtins.open") as mock_open:
            presenter.save_to_csv()
            mock_open.assert_not_called()

    def test_save_skips_when_no_history(self) -> None:
        """Пустая история → get_save_path() не вызывается."""
        commands = _FakeHistoryCommands([])
        view = _make_view()
        presenter = _make_presenter(commands, view)

        presenter.save_to_csv()

        view.get_save_path.assert_not_called()
