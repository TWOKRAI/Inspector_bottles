# -*- coding: utf-8 -*-
"""Тесты HistoryPresenter — pure-Python, без Qt.

Проверяет:
  - test_refresh_populates_table      : presenter заполняет таблицу из bus.history()
  - test_refresh_enables_buttons      : после refresh кнопки enabled/disabled корректно
  - test_clear_calls_bus_clear        : presenter вызывает bus.clear()
  - test_save_to_csv_writes_file      : CSV-файл содержит правильные строки
  - test_save_skips_when_no_path      : если view вернул None — файл не создаётся
  - test_save_skips_when_no_actions   : если история пуста — диалог не показывается
  - test_refresh_empty_bus            : bus=None не бросает исключений
"""

from __future__ import annotations

import csv
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


from multiprocess_prototype.frontend.widgets.tabs.settings.history.presenter import (
    HistoryPresenter,
)


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------


def _make_action(
    *,
    timestamp: float = 1_700_000_000.0,
    register_name: str = "camera",
    action_type: str = "field_set",
    field_name: str = "fps",
    description: str = "camera.fps = 30",
    forward_patch: dict | None = None,
    backward_patch: dict | None = None,
) -> SimpleNamespace:
    """Фабрика mock-действия ActionBus."""
    return SimpleNamespace(
        timestamp=timestamp,
        register_name=register_name,
        action_type=action_type,
        field_name=field_name,
        description=description,
        forward_patch=forward_patch or {"value": 30},
        backward_patch=backward_patch or {"value": 25},
    )


def _make_bus(
    actions: list | None = None,
    can_undo: bool = True,
    can_redo: bool = False,
) -> MagicMock:
    """Фабрика mock-шины ActionBus."""
    bus = MagicMock()
    bus.history.return_value = actions if actions is not None else []
    bus.can_undo.return_value = can_undo
    bus.can_redo.return_value = can_redo
    return bus


def _make_ctx(bus: MagicMock | None = None) -> MagicMock:
    """Фабрика mock AppContext."""
    ctx = MagicMock()
    ctx.action_bus.return_value = bus
    return ctx


def _make_view() -> MagicMock:
    """Фабрика mock HistoryView."""
    view = MagicMock()
    return view


def _make_presenter(
    bus: MagicMock | None = None,
    view: MagicMock | None = None,
) -> HistoryPresenter:
    """Создать HistoryPresenter с моками."""
    if view is None:
        view = _make_view()
    ctx = _make_ctx(bus)
    return HistoryPresenter(view=view, rm=None, ui=None, ctx=ctx)


# ---------------------------------------------------------------------------
# Тесты
# ---------------------------------------------------------------------------


class TestHistoryPresenterRefresh:
    """Тесты метода refresh()."""

    def test_refresh_populates_table(self) -> None:
        """presenter.refresh() вызывает view.set_table_data с правильными строками."""
        action = _make_action(
            timestamp=1_700_000_000.0,
            register_name="camera",
            field_name="fps",
            forward_patch={"value": 30},
        )
        bus = _make_bus(actions=[action])
        view = _make_view()
        presenter = _make_presenter(bus=bus, view=view)

        presenter.refresh()

        view.set_table_data.assert_called_once()
        rows = view.set_table_data.call_args[0][0]
        assert len(rows) == 1
        ts, tab_name, param, value = rows[0]
        assert tab_name == "camera"
        assert param == "fps"
        assert value == "30"

    def test_refresh_enables_buttons(self) -> None:
        """После refresh кнопки Save и Clear корректно включены/выключены."""
        action = _make_action()
        bus = _make_bus(actions=[action], can_undo=True, can_redo=False)
        view = _make_view()
        presenter = _make_presenter(bus=bus, view=view)

        presenter.refresh()

        # has_history=True → set_save_enabled(True)
        view.set_save_enabled.assert_called_with(True)
        # can_undo=True → set_clear_enabled(True)
        view.set_clear_enabled.assert_called_with(True)

    def test_refresh_disables_save_when_empty(self) -> None:
        """Если история пустая — set_save_enabled(False)."""
        bus = _make_bus(actions=[], can_undo=False, can_redo=False)
        view = _make_view()
        presenter = _make_presenter(bus=bus, view=view)

        presenter.refresh()

        view.set_save_enabled.assert_called_with(False)
        view.set_clear_enabled.assert_called_with(False)

    def test_refresh_scrolls_when_has_rows(self) -> None:
        """При наличии строк вызывается view.scroll_to_bottom()."""
        action = _make_action()
        bus = _make_bus(actions=[action])
        view = _make_view()
        presenter = _make_presenter(bus=bus, view=view)

        presenter.refresh()

        view.scroll_to_bottom.assert_called_once()

    def test_refresh_empty_bus(self) -> None:
        """Если bus=None — presenter не бросает исключений."""
        ctx = MagicMock()
        ctx.action_bus.return_value = None
        view = _make_view()
        presenter = HistoryPresenter(view=view, rm=None, ui=None, ctx=ctx)

        # Не должно бросать исключений
        presenter.refresh()

        view.set_table_data.assert_called_with([])
        view.set_save_enabled.assert_called_with(False)
        view.set_clear_enabled.assert_called_with(False)

    def test_refresh_recipe_apply_uses_recipe_name(self) -> None:
        """Для action_type='recipe_apply' значение берётся из recipe_name."""
        action = _make_action(
            action_type="recipe_apply",
            field_name=None,
            description="Применить рецепт",
            forward_patch={"recipe_name": "TestRecipe"},
        )
        bus = _make_bus(actions=[action])
        view = _make_view()
        presenter = _make_presenter(bus=bus, view=view)

        presenter.refresh()

        rows = view.set_table_data.call_args[0][0]
        _, _, _, value = rows[0]
        assert value == "TestRecipe"


class TestHistoryPresenterClear:
    """Тесты метода clear()."""

    def test_clear_calls_bus_clear(self) -> None:
        """presenter.clear() вызывает bus.clear()."""
        bus = _make_bus()
        presenter = _make_presenter(bus=bus)

        presenter.clear()

        bus.clear.assert_called_once()

    def test_clear_noop_when_no_bus(self) -> None:
        """presenter.clear() без bus — нет исключений."""
        ctx = MagicMock()
        ctx.action_bus.return_value = None
        view = _make_view()
        presenter = HistoryPresenter(view=view, rm=None, ui=None, ctx=ctx)

        # Не должно бросать исключений
        presenter.clear()


class TestHistoryPresenterSaveToCsv:
    """Тесты метода save_to_csv()."""

    def test_save_to_csv_writes_file(self, tmp_path: Path) -> None:
        """save_to_csv() создаёт CSV с правильными данными."""
        csv_path = str(tmp_path / "history.csv")
        action = _make_action(
            timestamp=1_700_000_000.0,
            register_name="camera",
            field_name="fps",
            forward_patch={"value": 30},
        )
        bus = _make_bus(actions=[action])
        # Важно: bus.history(n=0) = все записи
        bus.history.return_value = [action]

        view = _make_view()
        view.get_save_path.return_value = csv_path

        presenter = _make_presenter(bus=bus, view=view)
        presenter.save_to_csv()

        # Проверяем содержимое CSV
        with open(csv_path, encoding="utf-8-sig") as f:
            reader = csv.reader(f, delimiter=";")
            header = next(reader)
            assert header == ["Время", "Вкладка", "Параметр", "Значение"]
            rows = list(reader)

        assert len(rows) == 1
        _ts, tab, param, value = rows[0]
        assert tab == "camera"
        assert param == "fps"
        assert value == "30"

    def test_save_skips_when_no_path(self) -> None:
        """Если view.get_save_path() вернул None — файл не создаётся."""
        action = _make_action()
        bus = _make_bus(actions=[action])

        view = _make_view()
        view.get_save_path.return_value = None

        presenter = _make_presenter(bus=bus, view=view)

        with patch("builtins.open") as mock_open:
            presenter.save_to_csv()
            mock_open.assert_not_called()

    def test_save_skips_when_no_actions(self) -> None:
        """Если история пустая — view.get_save_path() не вызывается."""
        bus = _make_bus(actions=[])

        view = _make_view()
        presenter = _make_presenter(bus=bus, view=view)

        presenter.save_to_csv()

        view.get_save_path.assert_not_called()
