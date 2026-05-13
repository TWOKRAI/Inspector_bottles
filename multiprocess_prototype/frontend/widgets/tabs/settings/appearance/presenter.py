# -*- coding: utf-8 -*-
"""AppearancePresenter -- презентер секции «Оформление» для Settings таба.

Отвечает за:
- CRUD тем (add, copy, rename, delete)
- apply / save / refresh / revert / reset_defaults
- владение данными переменных (_current_vars, _last_saved_vars)
- навигацию по категориям / подкатегориям

НЕ импортирует Qt-классы напрямую. Работает исключительно через AppearanceView Protocol.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from multiprocess_framework.modules.frontend_module.widgets.tabs import TabPresenterBase

from multiprocess_prototype.registers.theme.schemas import (
    THEME_VAR_DESCRIPTIONS,
    THEME_VAR_TREE,
    ThemeVariables,
    get_default_variables,
)

from .view import AppearanceView

if TYPE_CHECKING:
    from multiprocess_framework.modules.frontend_module.managers.theme_manager import ThemeManager
    from multiprocess_prototype.frontend.managers.theme_presets_manager import ThemePresetsManager

logger = logging.getLogger(__name__)


class AppearancePresenter(TabPresenterBase[AppearanceView, None]):
    """Презентер секции «Оформление» -- CRUD тем, владелец данных переменных.

    Получает зависимости через конструктор. Не содержит Qt-кода.
    """

    def __init__(
        self,
        *,
        view: AppearanceView,
        theme_manager: "ThemeManager",
        presets_manager: "ThemePresetsManager",
    ) -> None:
        super().__init__(view=view, rm=None, ui=None)
        self._theme_manager = theme_manager
        self._presets_manager = presets_manager

        # Текущие значения переменных (редактируемые в UI)
        self._current_vars: dict[str, str] = {}
        # Снэпшот при загрузке/сохранении -- для кнопки «Отменить»
        self._last_saved_vars: dict[str, str] = {}

        # Выбранная в таблице тема
        self._selected_theme: str = ""
        self._selected_is_default: bool = False

        # Текущая выбранная категория/подкатегория для навигации
        self._current_category: str = ""
        self._current_subcategory: str = ""

    # ------------------------------------------------------------------
    # Инициализация (вызывается из section после построения UI)
    # ------------------------------------------------------------------

    def initialize(self) -> None:
        """Загрузить список тем и выбрать первую."""
        self._refresh_themes_and_select_first()

    # ------------------------------------------------------------------
    # Загрузка тем
    # ------------------------------------------------------------------

    def _refresh_themes_and_select_first(self) -> None:
        """Перезагрузить список тем, передать в view, выбрать первую."""
        themes = self._build_themes_list()
        self._view.set_themes(themes)

        if themes:
            first_name = themes[0][0]
            self._view.select_theme_row(first_name)
            self.on_theme_selected(first_name, is_default=(themes[0][1] == "default"))

    def _build_themes_list(self) -> list[tuple[str, str, str]]:
        """Собрать список тем: [(name, kind, parent), ...]."""
        all_themes = self._presets_manager.list_all()
        result: list[tuple[str, str, str]] = []
        for name, kind in all_themes:
            parent = self._presets_manager.get_parent(name)
            result.append((name, kind, parent if parent else "\u2014"))
        return result

    def _load_theme(self, name: str) -> None:
        """Загрузить переменные темы по имени и обновить view."""
        variables: ThemeVariables = self._presets_manager.get_variables(name)
        # Собрать в плоский dict
        self._current_vars = {
            field: getattr(variables, field)
            for field in ThemeVariables.model_fields
        }
        # Дополнить пропущенные ключи дефолтами
        defaults = get_default_variables()
        for k, v in defaults.items():
            if k not in self._current_vars:
                self._current_vars[k] = v

        # Снэпшот -- для «Отменить»
        self._last_saved_vars = dict(self._current_vars)

        self._rebuild_vars()

    # ------------------------------------------------------------------
    # Навигация по переменным
    # ------------------------------------------------------------------

    def _get_vars_for_subcategory(self, category: str, subcategory: str) -> list[str]:
        """Получить список имён переменных для подкатегории."""
        return THEME_VAR_TREE.get(category, {}).get(subcategory, [])

    def _get_vars_for_category(self, category: str) -> list[str]:
        """Получить ВСЕ переменные из всех подкатегорий данной категории."""
        result: list[str] = []
        for var_list in THEME_VAR_TREE.get(category, {}).values():
            result.extend(var_list)
        return result

    def _rebuild_vars(self) -> None:
        """Определить список переменных для отображения и передать в view."""
        self._view.close_color_editor()

        if self._current_subcategory:
            var_names = self._get_vars_for_subcategory(
                self._current_category, self._current_subcategory,
            )
        elif self._current_category:
            var_names = self._get_vars_for_category(self._current_category)
        else:
            # Ничего не выбрано -- показать всё из первой категории
            first_cat = next(iter(THEME_VAR_TREE), "")
            if first_cat:
                var_names = self._get_vars_for_category(first_cat)
                self._current_category = first_cat
            else:
                var_names = []

        # Собрать значения и описания для списка переменных
        values = {name: self._current_vars.get(name, "") for name in var_names}
        descriptions = {name: THEME_VAR_DESCRIPTIONS.get(name, "") for name in var_names}
        self._view.set_vars(var_names, values, descriptions)

    # ------------------------------------------------------------------
    # Обработчики событий от view
    # ------------------------------------------------------------------

    def on_theme_selected(self, name: str, is_default: bool) -> None:
        """Тема выбрана в таблице -- загрузить переменные."""
        self._selected_theme = name
        self._selected_is_default = is_default
        can_modify = not is_default and bool(name)
        self._view.set_crud_buttons_enabled(
            save=can_modify, rename=can_modify, delete=can_modify,
        )
        self._load_theme(name)

    def on_subcategory_selected(self, category: str, subcategory: str) -> None:
        """Клик по подкатегории в TreeNavWidget."""
        self._current_category = category
        self._current_subcategory = subcategory
        self._rebuild_vars()

    def on_category_selected(self, category: str) -> None:
        """Клик по категории в TreeNavWidget."""
        self._current_category = category
        self._current_subcategory = ""
        self._rebuild_vars()

    def on_cell_value_changed(self, var_name: str, value: str) -> None:
        """Значение переменной изменилось в таблице."""
        self._current_vars[var_name] = value

    def on_color_changed(self, var_name: str, hex_color: str) -> None:
        """Цвет изменён через inline color editor."""
        self._current_vars[var_name] = hex_color
        self._view.update_color_preview(var_name, hex_color)

    # ------------------------------------------------------------------
    # Действия кнопок
    # ------------------------------------------------------------------

    def apply(self) -> None:
        """Применить тему с текущими переменными."""
        defaults = self._presets_manager.list_defaults()
        base_theme = defaults[0] if defaults else self._theme_manager.current_theme
        self._theme_manager.apply_theme_with_variables(base_theme, self._current_vars)

    def save(self) -> None:
        """Сохранить текущие переменные в выбранную custom-тему."""
        if not self._selected_theme or self._selected_is_default:
            return
        variables = ThemeVariables.model_validate(self._current_vars)
        parent = self._presets_manager.get_parent(self._selected_theme)
        self._presets_manager.save_custom(
            self._selected_theme, variables, parent=parent,
        )
        self._last_saved_vars = dict(self._current_vars)

    def refresh(self) -> None:
        """Перечитать список тем и переменные с диска."""
        prev_selected = self._selected_theme
        themes = self._build_themes_list()
        self._view.set_themes(themes)
        if prev_selected:
            self._view.select_theme_row(prev_selected)

    def add_theme(self) -> None:
        """Создать новую custom-тему на базе текущей выбранной."""
        name, ok = self._view.get_input_text("Новая тема", "Введите имя новой темы:")
        if not ok or not name.strip():
            return
        name = name.strip()
        # Родительская тема -- выбранная default или parent выбранной custom
        if self._selected_is_default:
            parent = self._selected_theme
        else:
            parent = (
                self._presets_manager.get_parent(self._selected_theme)
                or self._selected_theme
            )
        variables = ThemeVariables.model_validate(self._current_vars)
        self._presets_manager.save_custom(name, variables, parent=parent)
        self._refresh_and_select(name)

    def copy_theme(self) -> None:
        """Скопировать выбранную тему в новую custom-тему."""
        if not self._selected_theme:
            return
        copy_name = self._selected_theme + "_copy"
        name, ok = self._view.get_input_text(
            "Копировать тему", "Введите имя копии:", default=copy_name,
        )
        if not ok or not name.strip():
            return
        name = name.strip()
        self._presets_manager.copy_theme(self._selected_theme, name)
        self._refresh_and_select(name)

    def rename_theme(self) -> None:
        """Переименовать выбранную custom-тему."""
        if not self._selected_theme or self._selected_is_default:
            return
        new_name, ok = self._view.get_input_text(
            "Переименовать тему", "Введите новое имя:", default=self._selected_theme,
        )
        if not ok or not new_name.strip():
            return
        new_name = new_name.strip()
        self._presets_manager.rename_custom(self._selected_theme, new_name)
        self._refresh_and_select(new_name)

    def delete_theme(self) -> None:
        """Удалить выбранную custom-тему."""
        if not self._selected_theme or self._selected_is_default:
            return
        self._presets_manager.delete_custom(self._selected_theme)
        self._selected_theme = ""
        self._selected_is_default = False
        self._refresh_themes_and_select_first()

    def reset_defaults(self) -> None:
        """Загрузить дефолтные значения выбранной темы (без сохранения)."""
        if not self._selected_theme:
            return
        self._load_theme(self._selected_theme)

    def revert(self) -> None:
        """Откатить переменные к последнему сохранённому состоянию."""
        self._current_vars = dict(self._last_saved_vars)
        self._rebuild_vars()

    # ------------------------------------------------------------------
    # Вспомогательные
    # ------------------------------------------------------------------

    def _refresh_and_select(self, name: str) -> None:
        """Обновить список тем и выбрать тему по имени."""
        themes = self._build_themes_list()
        self._view.set_themes(themes)
        self._view.select_theme_row(name)
