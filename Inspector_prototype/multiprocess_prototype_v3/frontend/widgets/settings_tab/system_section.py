# multiprocess_prototype_v3/frontend/widgets/settings_tab/system_section.py
"""
SystemSettingsSectionWidget — каркас секции «Настройки системы».

Структура копирует UiSettingsSectionWidget: SearchFilterBar + QStackedWidget
[Cards | Table-placeholder]. Источник данных — пустой list[dict] до подключения
ConfigStore процессов (дефолт из конфига + override в БД).

TODO: заменить пустой `_all_rows` на адаптер ConfigStore — каждое поле
конфига процесса становится row-dict (как `build_app_recipe_rows` для UI).
"""

from __future__ import annotations

from multiprocess_framework.modules.frontend_module.core.qt_imports import (
    QLabel,
    QStackedWidget,
    Qt,
    QVBoxLayout,
    QWidget,
)

from ..chrome.search_filter_bar import SearchFilterBar, apply_filter
from .settings_cards import SettingsCardsView


class SystemSettingsSectionWidget(QWidget):
    """Каркас секции «Настройки системы» — UI готов, источник данных пуст."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._all_rows: list[dict] = []  # TODO: подключить ConfigStore процессов
        self._current_text = ""
        self._current_category = ""
        self._current_sort_field = ""
        self._current_sort_asc = True

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._search_bar = SearchFilterBar()
        layout.addWidget(self._search_bar)

        self._cards = SettingsCardsView()
        self._table_placeholder = self._build_table_placeholder()

        self._stack = QStackedWidget()
        self._stack.addWidget(self._cards)  # 0
        self._stack.addWidget(self._table_placeholder)  # 1
        layout.addWidget(self._stack, 1)

        self._search_bar.filter_changed.connect(self._on_filter_changed)
        self._search_bar.sort_changed.connect(self._on_sort_changed)

        self._reload_rows()

    @staticmethod
    def _build_table_placeholder() -> QWidget:
        """Заглушка для таблицы — заменится на SystemTableWrapper после модели."""
        w = QWidget()
        v = QVBoxLayout(w)
        lbl = QLabel(
            "Таблица системных настроек\n\n"
            "TODO: подключить ConfigStore процессов "
            "(дефолт из конфига + override в БД)"
        )
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet("color: #888;")
        v.addWidget(lbl)
        return w

    def set_mode(self, mode: int) -> None:
        """Переключить вид: 0=карточки, 1=таблица."""
        self._stack.setCurrentIndex(mode)
        if mode == 0:
            self._apply_filter_and_reload_cards()

    def _reload_rows(self) -> None:
        """TODO: подгрузить rows из ConfigStore процессов. Сейчас — пусто."""
        self._all_rows = []
        categories: list[str] = sorted(
            {r.get("schema_name", r.get("register_name", "")) for r in self._all_rows}
        )
        self._search_bar.set_categories(categories)
        self._apply_filter_and_reload_cards()

    def _apply_filter_and_reload_cards(self) -> None:
        filtered = apply_filter(
            self._all_rows,
            self._current_text,
            self._current_category,
            self._current_sort_field,
            self._current_sort_asc,
        )
        self._cards.load_from_rows(filtered)

    def _on_filter_changed(self, text: str, category: str) -> None:
        self._current_text = text
        self._current_category = category
        self._apply_filter_and_reload_cards()

    def _on_sort_changed(self, sort_field: str, asc: bool) -> None:
        self._current_sort_field = sort_field
        self._current_sort_asc = asc
        self._apply_filter_and_reload_cards()
