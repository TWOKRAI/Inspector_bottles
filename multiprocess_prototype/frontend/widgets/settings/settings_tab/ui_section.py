# multiprocess_prototype/frontend/widgets/settings_tab/ui_section.py
"""
UiSettingsSectionWidget — секция 'Настройка интерфейса':
SearchFilterBar + QStackedWidget[CardsView | TableWrapper].

Единый источник истины — AppRecipePresenter внутри AppRecipePanelWidget.
"""

from __future__ import annotations

from multiprocess_framework.modules.frontend_module.core.qt_imports import QStackedWidget, QVBoxLayout, QWidget

from ...chrome.search_filter_bar import SearchFilterBar, apply_filter
from ...recipes.settings_recipe_widget.app_recipe_rows import build_app_recipe_rows
from .settings_cards import SettingsCardsView
from .settings_table import SettingsTableWrapper


class UiSettingsSectionWidget(QWidget):
    """Секция настройки интерфейса: поиск + карточки/таблица."""

    def __init__(
        self,
        app_panel: QWidget,
        initial_mode: int = 0,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._app_panel = app_panel
        self._all_rows: list[dict] = []
        self._current_text = ""
        self._current_category = ""
        self._current_sort_field = ""
        self._current_sort_asc = True

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Общая панель поиска / фильтрации
        self._search_bar = SearchFilterBar()
        layout.addWidget(self._search_bar)

        # Карточки (page 0) и таблица (page 1)
        self._cards = SettingsCardsView()
        self._table = SettingsTableWrapper(app_panel)

        self._stack = QStackedWidget()
        self._stack.addWidget(self._cards)  # index 0
        self._stack.addWidget(self._table)  # index 1
        layout.addWidget(self._stack, 1)

        # Подключения
        self._search_bar.filter_changed.connect(self._on_filter_changed)
        self._search_bar.sort_changed.connect(self._on_sort_changed)
        self._cards.value_changed.connect(self._on_cards_value_changed)

        # Двунаправленная синхронизация: после Load/Default presenter дёргает
        # view.refresh_table_rows() -- оборачиваем, чтобы карточки тоже обновились.
        self._wrap_panel_refresh()

        # Начальная загрузка
        self._reload_rows()
        self.set_mode(initial_mode)

    def _wrap_panel_refresh(self) -> None:
        """Wrap refresh_table_rows: после обновления дерева — синхронизировать карточки."""
        original = getattr(self._app_panel, "refresh_table_rows", None)
        if original is None:
            return

        section = self

        def _hooked() -> None:
            original()
            section._reload_rows()
            if section._stack.currentIndex() == 0:
                section._apply_filter_and_reload_cards()

        self._app_panel.refresh_table_rows = _hooked  # type: ignore[method-assign]

    def set_mode(self, mode: int) -> None:
        """Переключить вид: 0=карточки, 1=таблица."""
        self._stack.setCurrentIndex(mode)
        if mode == 0:
            self._apply_filter_and_reload_cards()

    def _reload_rows(self) -> None:
        """Загрузить строки напрямую из агрегата (СЫРЫЕ типы — для карточек critical)."""
        presenter = getattr(self._app_panel, "_presenter", None)
        if presenter is None:
            return
        # build_rows() в presenter форматирует значения в строки (format_value_for_cell);
        # для карточек это ломает типизацию (bool/int/float → str → всегда QLineEdit).
        # Берём сырые rows напрямую через build_app_recipe_rows.
        try:
            self._all_rows = build_app_recipe_rows(
                presenter._model.app_aggregate, presenter._model.access_ctx
            )
        except AttributeError:
            return
        categories = sorted(
            {r.get("schema_name", r.get("register_name", "")) for r in self._all_rows}
        )
        self._search_bar.set_categories(categories)

    def _apply_filter_and_reload_cards(self) -> None:
        """Применить текущие фильтры и перестроить карточки."""
        filtered = apply_filter(
            self._all_rows,
            self._current_text,
            self._current_category,
            self._current_sort_field,
            self._current_sort_asc,
        )
        self._cards.load_from_rows(filtered)

    def _on_cards_value_changed(self, field_id: str, value: object) -> None:
        """Пробросить изменение из карточки в presenter."""
        presenter = getattr(self._app_panel, "_presenter", None)
        if presenter is None:
            return
        # field_id имеет формат "schema_name.field_name"
        parts = field_id.split(".", 1)
        if len(parts) == 2:
            group_id, _ = parts
        else:
            group_id = ""
        apply_fn = getattr(presenter, "on_leaf_value_changed", None)
        if apply_fn is not None:
            apply_fn(group_id, field_id, "value", str(value))

    def _on_filter_changed(self, text: str, category: str) -> None:
        self._current_text = text
        self._current_category = category
        self._apply_filter_and_reload_cards()
        self._table.apply_filter(
            text, category, self._current_sort_field, self._current_sort_asc
        )

    def _on_sort_changed(self, sort_field: str, asc: bool) -> None:
        self._current_sort_field = sort_field
        self._current_sort_asc = asc
        self._apply_filter_and_reload_cards()
        self._table.apply_filter(
            self._current_text, self._current_category, sort_field, asc
        )
