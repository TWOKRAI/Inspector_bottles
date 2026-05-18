# -*- coding: utf-8 -*-
"""AppearanceSection -- секция «Оформление» для Settings таба.

Реализует:
- SectionProtocol   -- интерфейс секции (key, title, widget, action_buttons, on_activated)
- AppearanceView    -- интерфейс вью для AppearancePresenter

Компонует ThemesTable + VarsEditor, владеет кнопками action-колонки.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .themes_table import ThemesTable
from .vars_editor import VarsEditor

if TYPE_CHECKING:
    from .presenter import AppearancePresenter


class AppearanceSection(QWidget):
    """Секция «Оформление» -- таблица тем + редактор переменных + action-кнопки.

    Реализует SectionProtocol и AppearanceView -- presenter вызывает view-методы
    напрямую на объекте секции.

    Presenter инжектируется через set_presenter() после создания секции,
    что позволяет тестам подсунуть mock через SectionSpec.presenter_factory.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # Presenter инжектируется позже через set_presenter() — до этого None
        self._presenter: "AppearancePresenter | None" = None
        self._init_buttons()
        self._build_ui()

    # ------------------------------------------------------------------
    # SectionProtocol
    # ------------------------------------------------------------------

    @property
    def key(self) -> str:
        """Уникальный идентификатор секции."""
        return "appearance"

    @property
    def title(self) -> str:
        """Отображаемое название секции."""
        return "Оформление"

    def widget(self) -> QWidget:
        """Корневой QWidget секции."""
        return self

    def action_buttons(self) -> list[QWidget]:
        """Кнопки для action-колонки."""
        return [
            self._btn_apply,
            self._btn_save,
            self._btn_refresh,
            self._make_separator(),
            self._btn_add,
            self._btn_copy,
            self._btn_rename,
            self._btn_delete,
            self._make_separator(),
            self._btn_defaults,
            self._btn_revert,
        ]

    def on_activated(self) -> None:
        """Вызывается при переключении на секцию."""

    def on_deactivated(self) -> None:
        """Вызывается при уходе с секции."""

    # ------------------------------------------------------------------
    # AppearanceView Protocol
    # ------------------------------------------------------------------

    def set_themes(self, themes: list[tuple[str, str, str]]) -> None:
        """Заполнить таблицу тем."""
        self._themes_table.set_themes(themes)

    def select_theme_row(self, name: str) -> None:
        """Выбрать строку таблицы тем по имени."""
        self._themes_table.select_by_name(name)

    def set_vars(
        self,
        var_names: list[str],
        values: dict[str, str],
        descriptions: dict[str, str],
    ) -> None:
        """Заполнить таблицу переменных."""
        self._vars_editor.set_vars(var_names, values, descriptions)

    def set_crud_buttons_enabled(
        self,
        save: bool,
        rename: bool,
        delete: bool,
    ) -> None:
        """Установить доступность кнопок CRUD."""
        self._btn_save.setEnabled(save)
        self._btn_rename.setEnabled(rename)
        self._btn_delete.setEnabled(delete)

    def get_input_text(
        self,
        title: str,
        label: str,
        default: str = "",
    ) -> tuple[str, bool]:
        """Показать диалог ввода текста."""
        if default:
            text, ok = QInputDialog.getText(self, title, label, text=default)
        else:
            text, ok = QInputDialog.getText(self, title, label)
        return text, ok

    def update_color_preview(self, var_name: str, value: str) -> None:
        """Обновить превью цвета для переменной."""
        self._vars_editor.update_color_preview(var_name, value)

    def close_color_editor(self) -> None:
        """Закрыть inline color editor."""
        self._vars_editor.close_color_editor()

    # ------------------------------------------------------------------
    # Построение UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        """Компоновка: ThemesTable + VarsEditor."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._themes_table = ThemesTable()
        layout.addWidget(self._themes_table)

        self._vars_editor = VarsEditor()
        layout.addWidget(self._vars_editor)

    # ------------------------------------------------------------------
    # Кнопки action-колонки
    # ------------------------------------------------------------------

    def _init_buttons(self) -> None:
        """Создать все кнопки action-колонки."""
        self._btn_apply = QPushButton("Применить тему")
        self._btn_apply.setProperty("role", "primary")
        self._btn_apply.setToolTip("Применить текущую тему с редактированными переменными")

        self._btn_save = QPushButton("Сохранить")
        self._btn_save.setToolTip("Сохранить текущие переменные в выбранную custom-тему")

        self._btn_refresh = QPushButton("Обновить")
        self._btn_refresh.setToolTip("Перечитать список тем и переменные с диска")

        self._btn_add = QPushButton("Добавить")
        self._btn_add.setToolTip("Создать новую пустую custom-тему")

        self._btn_copy = QPushButton("Копировать")
        self._btn_copy.setToolTip("Скопировать выбранную тему как новую custom-тему")

        self._btn_rename = QPushButton("Переименовать")
        self._btn_rename.setToolTip("Переименовать выбранную custom-тему")

        self._btn_delete = QPushButton("Удалить")
        self._btn_delete.setToolTip("Удалить выбранную custom-тему")

        self._btn_defaults = QPushButton("По умолчанию")
        self._btn_defaults.setToolTip("Загрузить дефолтные значения выбранной темы")

        self._btn_revert = QPushButton("Отменить")
        self._btn_revert.setToolTip("Откатить изменения к последнему сохранённому состоянию")

        # Сигналы кнопок -> слоты
        self._btn_apply.clicked.connect(self._on_apply)
        self._btn_save.clicked.connect(self._on_save)
        self._btn_refresh.clicked.connect(self._on_refresh)
        self._btn_add.clicked.connect(self._on_add)
        self._btn_copy.clicked.connect(self._on_copy)
        self._btn_rename.clicked.connect(self._on_rename)
        self._btn_delete.clicked.connect(self._on_delete)
        self._btn_defaults.clicked.connect(self._on_reset_defaults)
        self._btn_revert.clicked.connect(self._on_revert)

    def set_presenter(self, presenter: "AppearancePresenter") -> None:
        """Инжектировать presenter в секцию.

        Подключает сигналы виджетов к presenter'у и вызывает initialize()
        для загрузки таблицы тем.

        ВАЖНО: вызывается из BaseTreeNavTab._apply_presenter_factory ПЕРЕД
        _connect_section_events.
        """
        self._presenter = presenter
        # Подключить сигналы виджетов к presenter через слоты-врапперы
        self._themes_table.theme_selected.connect(self._on_theme_selected)
        self._vars_editor.var_changed.connect(self._on_var_changed)
        self._vars_editor.category_changed.connect(self._on_category_changed)
        # Инициализация: загрузить темы
        self._presenter.initialize()

    # ------------------------------------------------------------------
    # Слоты кнопок -> делегация в presenter (с guard на None)
    # ------------------------------------------------------------------

    def _on_apply(self) -> None:
        if self._presenter is None:
            return
        self._presenter.apply()

    def _on_save(self) -> None:
        if self._presenter is None:
            return
        self._presenter.save()

    def _on_refresh(self) -> None:
        if self._presenter is None:
            return
        self._presenter.refresh()

    def _on_add(self) -> None:
        if self._presenter is None:
            return
        self._presenter.add_theme()

    def _on_copy(self) -> None:
        if self._presenter is None:
            return
        self._presenter.copy_theme()

    def _on_rename(self) -> None:
        if self._presenter is None:
            return
        self._presenter.rename_theme()

    def _on_delete(self) -> None:
        if self._presenter is None:
            return
        self._presenter.delete_theme()

    def _on_reset_defaults(self) -> None:
        if self._presenter is None:
            return
        self._presenter.reset_defaults()

    def _on_revert(self) -> None:
        if self._presenter is None:
            return
        self._presenter.revert()

    # ------------------------------------------------------------------
    # Слоты-врапперы для сигналов виджетов -> presenter
    # ------------------------------------------------------------------

    def _on_theme_selected(self, name: str, is_default: bool) -> None:
        """Враппер сигнала theme_selected → presenter.on_theme_selected."""
        if self._presenter is not None:
            self._presenter.on_theme_selected(name, is_default)

    def _on_var_changed(self, name: str, value: str) -> None:
        """Враппер сигнала var_changed → presenter.on_cell_value_changed."""
        if self._presenter is not None:
            self._presenter.on_cell_value_changed(name, value)

    # ------------------------------------------------------------------
    # Внутренние обработчики
    # ------------------------------------------------------------------

    def _on_category_changed(self, category: str, subcategory: str) -> None:
        """Маршрутизация сигнала category_changed в presenter."""
        if self._presenter is None:
            return
        if subcategory:
            self._presenter.on_subcategory_selected(category, subcategory)
        else:
            self._presenter.on_category_selected(category)

    # ------------------------------------------------------------------
    # Вспомогательные
    # ------------------------------------------------------------------

    @staticmethod
    def _make_separator() -> QWidget:
        """Горизонтальный разделитель для action-колонки."""
        container = QWidget()
        container_layout = QHBoxLayout(container)
        container_layout.setContentsMargins(10, 4, 10, 4)
        container_layout.setSpacing(0)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Plain)
        line.setObjectName("ThemeDivider")
        line.setFixedHeight(2)
        container_layout.addWidget(line)
        return container
