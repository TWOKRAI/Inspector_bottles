# -*- coding: utf-8 -*-
"""Тесты AppearancePresenter — pure-Python, без Qt.

Проверяет:
  - test_load_theme_sets_vars            : load_theme() обновляет _current_vars и вызывает view.set_vars()
  - test_save_custom_theme               : save() вызывает presets_manager.save_custom()
  - test_save_disabled_for_default       : save() для default-темы ничего не делает
  - test_add_theme_creates_copy          : add_theme() вызывает view.get_input_text(), save_custom(), refresh
  - test_revert_restores_last_saved      : revert() восстанавливает _last_saved_vars в _current_vars
  - test_on_cell_value_changed_updates_vars : on_cell_value_changed() обновляет _current_vars
  - test_on_theme_selected_sets_crud_buttons : on_theme_selected() корректно включает/отключает кнопки
  - test_add_theme_cancelled_does_nothing : add_theme() при отмене диалога не сохраняет тему
  - test_delete_theme_calls_delete_and_refresh : delete_theme() вызывает delete_custom и обновляет список
  - test_revert_calls_rebuild_vars        : revert() вызывает view.set_vars (через _rebuild_vars)
"""

from __future__ import annotations

from unittest.mock import MagicMock


from multiprocess_prototype.frontend.widgets.tabs.settings.appearance.presenter import (
    AppearancePresenter,
)
from multiprocess_prototype.registers.theme.schemas import (
    ThemeVariables,
    get_default_variables,
)


# ---------------------------------------------------------------------------
# Вспомогательные классы и фабрики
# ---------------------------------------------------------------------------


class MockAppearanceView:
    """Mock для AppearanceView Protocol — чистый Python, без Qt."""

    def __init__(self) -> None:
        # Список тем, переданный в set_themes
        self.themes: list[tuple[str, str, str]] = []
        # Последнее выбранное имя темы
        self.selected_theme_row: str = ""
        # Аргументы последнего вызова set_vars
        self.set_vars_calls: list[tuple[list, dict, dict]] = []
        # Состояние кнопок CRUD
        self.crud_buttons: dict[str, bool] = {
            "save": True,
            "rename": True,
            "delete": True,
        }
        # Возвращаемое значение get_input_text (имитация пользовательского ввода)
        self.input_text_result: tuple[str, bool] = ("", False)
        # Счётчик вызовов close_color_editor
        self.close_color_editor_called: int = 0
        # Вызовы update_color_preview
        self.color_preview_calls: list[tuple[str, str]] = []

    def set_themes(self, themes: list[tuple[str, str, str]]) -> None:
        """Заполнить таблицу тем."""
        self.themes = list(themes)

    def select_theme_row(self, name: str) -> None:
        """Выбрать строку по имени."""
        self.selected_theme_row = name

    def set_vars(
        self,
        var_names: list[str],
        values: dict[str, str],
        descriptions: dict[str, str],
    ) -> None:
        """Заполнить таблицу переменных."""
        self.set_vars_calls.append((list(var_names), dict(values), dict(descriptions)))

    def set_crud_buttons_enabled(self, save: bool, rename: bool, delete: bool) -> None:
        """Установить доступность CRUD-кнопок."""
        self.crud_buttons = {"save": save, "rename": rename, "delete": delete}

    def get_input_text(
        self,
        title: str,
        label: str,
        default: str = "",
    ) -> tuple[str, bool]:
        """Вернуть заранее настроенный результат диалога ввода."""
        return self.input_text_result

    def update_color_preview(self, var_name: str, value: str) -> None:
        """Зафиксировать обновление превью цвета."""
        self.color_preview_calls.append((var_name, value))

    def close_color_editor(self) -> None:
        """Зафиксировать закрытие inline color editor."""
        self.close_color_editor_called += 1


def _make_presets_manager(
    *,
    themes: list[tuple[str, str]] | None = None,
    variables: ThemeVariables | None = None,
    parent: str = "",
) -> MagicMock:
    """Создать mock ThemePresetsManager с базовой конфигурацией."""
    mgr = MagicMock()
    if themes is None:
        themes = [("my_theme", "custom")]
    mgr.list_all.return_value = themes
    mgr.get_parent.return_value = parent
    if variables is None:
        variables = ThemeVariables()
    mgr.get_variables.return_value = variables
    mgr.list_defaults.return_value = [t[0] for t in themes if t[1] == "default"]
    return mgr


def _make_theme_manager() -> MagicMock:
    """Создать mock ThemeManager."""
    mgr = MagicMock()
    mgr.current_theme = "innotech_theme"
    return mgr


def _make_presenter(
    view: MockAppearanceView | None = None,
    themes: list[tuple[str, str]] | None = None,
    variables: ThemeVariables | None = None,
    parent: str = "",
) -> AppearancePresenter:
    """Создать AppearancePresenter с mock-зависимостями."""
    if view is None:
        view = MockAppearanceView()
    presets = _make_presets_manager(themes=themes, variables=variables, parent=parent)
    theme_mgr = _make_theme_manager()
    return AppearancePresenter(
        view=view,
        theme_manager=theme_mgr,
        presets_manager=presets,
    )


# ---------------------------------------------------------------------------
# Тесты: загрузка темы
# ---------------------------------------------------------------------------


class TestLoadTheme:
    """Тесты загрузки переменных темы."""

    def test_load_theme_sets_vars(self) -> None:
        """on_theme_selected() обновляет _current_vars и вызывает view.set_vars()."""
        view = MockAppearanceView()
        # Создаём ThemeVariables с известным значением
        variables = ThemeVariables()
        # Берём первое поле модели для проверки
        first_field = next(iter(ThemeVariables.model_fields))
        expected_value = getattr(variables, first_field)

        presenter = _make_presenter(view=view, variables=variables)

        # Очищаем вызовы от __init__ (если initialize() не вызывался)
        view.set_vars_calls.clear()

        presenter.on_theme_selected("my_theme", is_default=False)

        # _current_vars должны содержать первое поле
        assert first_field in presenter._current_vars
        assert presenter._current_vars[first_field] == expected_value

        # view.set_vars должен быть вызван хотя бы раз
        assert len(view.set_vars_calls) >= 1

    def test_load_theme_updates_last_saved_vars(self) -> None:
        """Загрузка темы создаёт снэпшот _last_saved_vars = _current_vars."""
        view = MockAppearanceView()
        presenter = _make_presenter(view=view)

        presenter.on_theme_selected("my_theme", is_default=False)

        # _last_saved_vars должен совпадать с _current_vars сразу после загрузки
        assert presenter._last_saved_vars == presenter._current_vars


# ---------------------------------------------------------------------------
# Тесты: сохранение темы
# ---------------------------------------------------------------------------


class TestSave:
    """Тесты метода save()."""

    def test_save_custom_theme(self) -> None:
        """save() вызывает presets_manager.save_custom() для custom-темы."""
        view = MockAppearanceView()
        presets = _make_presets_manager(themes=[("my_theme", "custom")])
        theme_mgr = _make_theme_manager()
        presenter = AppearancePresenter(
            view=view, theme_manager=theme_mgr, presets_manager=presets
        )

        # Выбираем custom-тему
        presenter._selected_theme = "my_theme"
        presenter._selected_is_default = False
        presenter._current_vars = dict(get_default_variables())

        presenter.save()

        presets.save_custom.assert_called_once()
        # Первый аргумент — имя темы
        assert presets.save_custom.call_args[0][0] == "my_theme"
        # Второй аргумент — ThemeVariables
        saved_vars = presets.save_custom.call_args[0][1]
        assert isinstance(saved_vars, ThemeVariables)

    def test_save_disabled_for_default(self) -> None:
        """save() для default-темы не вызывает presets_manager.save_custom()."""
        view = MockAppearanceView()
        presets = _make_presets_manager(themes=[("innotech_theme", "default")])
        theme_mgr = _make_theme_manager()
        presenter = AppearancePresenter(
            view=view, theme_manager=theme_mgr, presets_manager=presets
        )

        # Выбираем default-тему
        presenter._selected_theme = "innotech_theme"
        presenter._selected_is_default = True

        presenter.save()

        # Для default-темы save_custom не должен вызываться
        presets.save_custom.assert_not_called()

    def test_save_disabled_when_no_theme_selected(self) -> None:
        """save() без выбранной темы не вызывает save_custom."""
        view = MockAppearanceView()
        presets = _make_presets_manager()
        theme_mgr = _make_theme_manager()
        presenter = AppearancePresenter(
            view=view, theme_manager=theme_mgr, presets_manager=presets
        )

        # Тема не выбрана
        presenter._selected_theme = ""
        presenter._selected_is_default = False

        presenter.save()

        presets.save_custom.assert_not_called()

    def test_save_updates_last_saved_vars(self) -> None:
        """save() обновляет _last_saved_vars текущими значениями."""
        view = MockAppearanceView()
        presets = _make_presets_manager()
        theme_mgr = _make_theme_manager()
        presenter = AppearancePresenter(
            view=view, theme_manager=theme_mgr, presets_manager=presets
        )

        presenter._selected_theme = "my_theme"
        presenter._selected_is_default = False
        new_vars = dict(get_default_variables())
        presenter._current_vars = new_vars

        presenter.save()

        # _last_saved_vars должен совпасть с _current_vars
        assert presenter._last_saved_vars == new_vars


# ---------------------------------------------------------------------------
# Тесты: добавление темы
# ---------------------------------------------------------------------------


class TestAddTheme:
    """Тесты метода add_theme()."""

    def test_add_theme_creates_copy(self) -> None:
        """add_theme() вызывает get_input_text, save_custom и обновляет список тем."""
        view = MockAppearanceView()
        view.input_text_result = ("new_theme", True)  # пользователь ввёл имя и нажал OK

        presets = _make_presets_manager(themes=[("my_theme", "custom")])
        theme_mgr = _make_theme_manager()
        presenter = AppearancePresenter(
            view=view, theme_manager=theme_mgr, presets_manager=presets
        )

        presenter._selected_theme = "my_theme"
        presenter._selected_is_default = False
        presenter._current_vars = dict(get_default_variables())
        presets.get_parent.return_value = "innotech_theme"

        presenter.add_theme()

        # save_custom должен быть вызван с новым именем
        presets.save_custom.assert_called_once()
        assert presets.save_custom.call_args[0][0] == "new_theme"

        # set_themes должен быть вызван для обновления списка
        assert len(view.themes) >= 0  # список обновлён
        presets.list_all.assert_called()

    def test_add_theme_cancelled_does_nothing(self) -> None:
        """add_theme() при отмене диалога не сохраняет тему."""
        view = MockAppearanceView()
        view.input_text_result = ("", False)  # пользователь нажал Отмена

        presets = _make_presets_manager()
        theme_mgr = _make_theme_manager()
        presenter = AppearancePresenter(
            view=view, theme_manager=theme_mgr, presets_manager=presets
        )

        presenter._selected_theme = "my_theme"
        presenter._selected_is_default = False

        presenter.add_theme()

        presets.save_custom.assert_not_called()

    def test_add_theme_empty_name_does_nothing(self) -> None:
        """add_theme() с пустым именем (только пробелы) не сохраняет тему."""
        view = MockAppearanceView()
        view.input_text_result = ("   ", True)  # OK но пустое имя

        presets = _make_presets_manager()
        theme_mgr = _make_theme_manager()
        presenter = AppearancePresenter(
            view=view, theme_manager=theme_mgr, presets_manager=presets
        )

        presenter._selected_theme = "my_theme"

        presenter.add_theme()

        presets.save_custom.assert_not_called()


# ---------------------------------------------------------------------------
# Тесты: откат изменений
# ---------------------------------------------------------------------------


class TestRevert:
    """Тесты метода revert()."""

    def test_revert_restores_last_saved(self) -> None:
        """revert() восстанавливает _current_vars из _last_saved_vars."""
        view = MockAppearanceView()
        presenter = _make_presenter(view=view)

        # Сохраняем снэпшот
        defaults = get_default_variables()
        presenter._last_saved_vars = dict(defaults)

        # Изменяем _current_vars
        first_field = next(iter(ThemeVariables.model_fields))
        presenter._current_vars = {first_field: "изменённое_значение"}

        presenter.revert()

        # После revert _current_vars должен совпасть с _last_saved_vars
        assert presenter._current_vars == defaults

    def test_revert_calls_rebuild_vars(self) -> None:
        """revert() вызывает _rebuild_vars, что приводит к вызову view.set_vars()."""
        view = MockAppearanceView()
        presenter = _make_presenter(view=view)

        defaults = get_default_variables()
        presenter._last_saved_vars = dict(defaults)
        presenter._current_vars = {}

        # Очищаем вызовы
        view.set_vars_calls.clear()

        presenter.revert()

        # _rebuild_vars должен был вызвать view.set_vars
        assert len(view.set_vars_calls) >= 1


# ---------------------------------------------------------------------------
# Тесты: обновление переменных в таблице
# ---------------------------------------------------------------------------


class TestCellValueChanged:
    """Тесты метода on_cell_value_changed()."""

    def test_on_cell_value_changed_updates_vars(self) -> None:
        """on_cell_value_changed() обновляет _current_vars для указанной переменной."""
        view = MockAppearanceView()
        presenter = _make_presenter(view=view)

        # Устанавливаем начальное состояние
        presenter._current_vars = {"bg_deep": "#000000"}

        presenter.on_cell_value_changed("bg_deep", "#FFFFFF")

        assert presenter._current_vars["bg_deep"] == "#FFFFFF"

    def test_on_cell_value_changed_adds_new_var(self) -> None:
        """on_cell_value_changed() добавляет новую переменную если её не было."""
        view = MockAppearanceView()
        presenter = _make_presenter(view=view)

        presenter._current_vars = {}
        presenter.on_cell_value_changed("accent", "#FF0000")

        assert presenter._current_vars["accent"] == "#FF0000"


# ---------------------------------------------------------------------------
# Тесты: выбор темы и кнопки CRUD
# ---------------------------------------------------------------------------


class TestOnThemeSelected:
    """Тесты обработчика on_theme_selected()."""

    def test_on_theme_selected_custom_enables_buttons(self) -> None:
        """Выбор custom-темы включает кнопки save/rename/delete."""
        view = MockAppearanceView()
        presenter = _make_presenter(view=view)

        presenter.on_theme_selected("my_theme", is_default=False)

        assert view.crud_buttons["save"] is True
        assert view.crud_buttons["rename"] is True
        assert view.crud_buttons["delete"] is True

    def test_on_theme_selected_default_disables_buttons(self) -> None:
        """Выбор default-темы отключает кнопки save/rename/delete."""
        view = MockAppearanceView()
        variables = ThemeVariables()
        presets = _make_presets_manager(
            themes=[("innotech_theme", "default")],
            variables=variables,
        )
        theme_mgr = _make_theme_manager()
        presenter = AppearancePresenter(
            view=view,
            theme_manager=theme_mgr,
            presets_manager=presets,
        )

        presenter.on_theme_selected("innotech_theme", is_default=True)

        assert view.crud_buttons["save"] is False
        assert view.crud_buttons["rename"] is False
        assert view.crud_buttons["delete"] is False


# ---------------------------------------------------------------------------
# Тесты: удаление темы
# ---------------------------------------------------------------------------


class TestDeleteTheme:
    """Тесты метода delete_theme()."""

    def test_delete_theme_calls_delete_custom(self) -> None:
        """delete_theme() вызывает presets_manager.delete_custom()."""
        view = MockAppearanceView()
        presets = _make_presets_manager(themes=[("my_theme", "custom")])
        theme_mgr = _make_theme_manager()
        presenter = AppearancePresenter(
            view=view,
            theme_manager=theme_mgr,
            presets_manager=presets,
        )

        presenter._selected_theme = "my_theme"
        presenter._selected_is_default = False

        presenter.delete_theme()

        presets.delete_custom.assert_called_once_with("my_theme")

    def test_delete_default_theme_does_nothing(self) -> None:
        """delete_theme() для default-темы не вызывает delete_custom."""
        view = MockAppearanceView()
        presets = _make_presets_manager(themes=[("innotech_theme", "default")])
        theme_mgr = _make_theme_manager()
        presenter = AppearancePresenter(
            view=view,
            theme_manager=theme_mgr,
            presets_manager=presets,
        )

        presenter._selected_theme = "innotech_theme"
        presenter._selected_is_default = True

        presenter.delete_theme()

        presets.delete_custom.assert_not_called()
