# multiprocess_prototype/frontend/widgets/tabs_setting/recipes_tab/recipe_content_section.py
"""
RecipeContentSection — секция контента рецептов:
SearchFilterBar + QStackedWidget[CardsView | RecipeTableWrapper].

Аналог UiSettingsSectionWidget (settings_tab/ui_section.py), но для рецептов
регистров. Учитывает preview mode (snapshot из YAML vs live registers).
"""

from __future__ import annotations

from multiprocess_framework.modules.frontend_module.core.qt_imports import (
    QStackedWidget,
    QVBoxLayout,
    QWidget,
    Signal,
)

from ...recipes.recipes_widget.recipe_rows import (
    build_recipe_rows,
    build_recipe_rows_from_snapshot,
)
from ...chrome.search_filter_bar import SearchFilterBar, apply_filter
from ...settings.settings_tab.settings_cards import SettingsCardsView


class RecipeTableWrapper(QWidget):
    """Хостит tree из register_panel и фильтрует элементы."""

    def __init__(
        self,
        tree_widget: QWidget,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._tree = tree_widget

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(tree_widget, 1)

    def apply_filter(
        self,
        text: str,
        category: str,
        sort_field: str,
        asc: bool,
    ) -> None:
        """Фильтрация через tree.invisibleRootItem()."""
        tree = self._tree
        if tree is None:
            return

        root = tree.invisibleRootItem()
        text_lower = text.lower()

        for gi in range(root.childCount()):
            group_item = root.child(gi)
            group_name = group_item.text(0)

            # Фильтр по категории на уровне группы
            if category and group_name != category:
                group_item.setHidden(True)
                continue

            visible_children = 0
            for ci in range(group_item.childCount()):
                child = group_item.child(ci)
                if not text:
                    child.setHidden(False)
                    visible_children += 1
                    continue

                # Поиск в колонках param (0) и info (2)
                col0 = child.text(0).lower()
                col2 = (
                    child.text(2).lower()
                    if child.columnCount() > 2
                    else ""
                )
                matches = text_lower in col0 or text_lower in col2
                child.setHidden(not matches)
                if matches:
                    visible_children += 1

            group_item.setHidden(visible_children == 0)


class RecipeContentSection(QWidget):
    """Секция контента рецептов: поиск + карточки/таблица."""

    value_changed = Signal(str, object)  # (field_id, value)

    def __init__(
        self,
        register_panel: QWidget,
        initial_mode: int = 0,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._register_panel = register_panel
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
        tree = getattr(register_panel, "_tree", None)
        self._table = RecipeTableWrapper(tree) if tree else QWidget()

        self._stack = QStackedWidget()
        self._stack.addWidget(self._cards)   # index 0
        self._stack.addWidget(self._table)   # index 1
        layout.addWidget(self._stack, 1)

        # Подключения
        self._search_bar.filter_changed.connect(
            self._on_filter_changed,
        )
        self._search_bar.sort_changed.connect(
            self._on_sort_changed,
        )
        self._cards.value_changed.connect(
            self._on_cards_value_changed,
        )

        # Двунаправленная синхронизация: после refresh_table_rows
        # (presenter дёргает view.refresh_table_rows) — карточки тоже
        # обновляются.
        self._wrap_panel_refresh()

        # Начальная загрузка + установка режима
        self._reload_rows()
        self.set_mode(initial_mode)

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    def set_mode(self, mode: int) -> None:
        """Переключить вид: 0=карточки, 1=таблица."""
        self._stack.setCurrentIndex(mode)
        if mode == 0:
            self._apply_filter_and_reload_cards()

    # ------------------------------------------------------------------
    # Загрузка данных
    # ------------------------------------------------------------------

    def _wrap_panel_refresh(self) -> None:
        """Обернуть refresh_table_rows: после обновления дерева —
        синхронизировать карточки."""
        original = getattr(
            self._register_panel, "refresh_table_rows", None,
        )
        if original is None:
            return

        section = self

        def _hooked() -> None:
            original()
            section._reload_rows()
            if section._stack.currentIndex() == 0:
                section._apply_filter_and_reload_cards()

        # Подменяем метод на обёртку
        self._register_panel.refresh_table_rows = _hooked  # type: ignore[method-assign]

    def _reload_rows(self) -> None:
        """Загрузить строки из presenter — учитывая preview mode."""
        presenter = getattr(
            self._register_panel, "_presenter", None,
        )
        if presenter is None:
            return

        model = getattr(presenter, "_model", None)
        if model is None:
            return

        rm = getattr(model, "rm", None)
        access_ctx = getattr(model, "access_ctx", None)

        # Проверяем preview mode
        is_preview = getattr(presenter, "is_preview_mode", None)
        if is_preview is not None and is_preview():
            # Preview — строим из snapshot
            snapshot = getattr(presenter, "_preview_snapshot", None)
            if snapshot and rm and access_ctx:
                self._all_rows = build_recipe_rows_from_snapshot(
                    rm, snapshot, access_ctx,
                )
            else:
                self._all_rows = []
        else:
            # Live registers
            if rm and access_ctx:
                self._all_rows = build_recipe_rows(rm, access_ctx)
            else:
                self._all_rows = []

        # Обновить категории в SearchFilterBar
        categories = sorted(
            {r.get("register_name", "") for r in self._all_rows},
        )
        self._search_bar.set_categories(categories)

    # ------------------------------------------------------------------
    # Фильтрация
    # ------------------------------------------------------------------

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

    def _on_filter_changed(self, text: str, category: str) -> None:
        self._current_text = text
        self._current_category = category
        self._apply_filter_and_reload_cards()
        if isinstance(self._table, RecipeTableWrapper):
            self._table.apply_filter(
                text,
                category,
                self._current_sort_field,
                self._current_sort_asc,
            )

    def _on_sort_changed(self, sort_field: str, asc: bool) -> None:
        self._current_sort_field = sort_field
        self._current_sort_asc = asc
        self._apply_filter_and_reload_cards()
        if isinstance(self._table, RecipeTableWrapper):
            self._table.apply_filter(
                self._current_text,
                self._current_category,
                sort_field,
                asc,
            )

    # ------------------------------------------------------------------
    # Проброс изменений из карточек
    # ------------------------------------------------------------------

    def _on_cards_value_changed(
        self, field_id: str, value: object,
    ) -> None:
        """Пробросить изменение из карточки в presenter."""
        presenter = getattr(
            self._register_panel, "_presenter", None,
        )
        if presenter is None:
            return
        # field_id имеет формат "register_name.field_name"
        parts = field_id.split(".", 1)
        group_id = parts[0] if len(parts) == 2 else ""
        apply_fn = getattr(presenter, "on_leaf_value_changed", None)
        if apply_fn is not None:
            apply_fn(group_id, field_id, "value", str(value))
        self.value_changed.emit(field_id, value)
