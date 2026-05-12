"""Тесты для TreeNavWidget — 2-уровневое дерево навигации."""
from __future__ import annotations

import pytest

from multiprocess_prototype.frontend.widgets.primitives import TreeNavWidget


# Фикстура: типичное дерево для тестов
SAMPLE_TREE = {
    "Компоненты": ["Кнопки", "Поля ввода", "Чекбоксы"],
    "Макет": ["Отступы", "Сетка"],
}


class TestTreeNavWidget:
    """Тесты TreeNavWidget."""

    def _make(self, qtbot, **kwargs) -> TreeNavWidget:
        w = TreeNavWidget(**kwargs)
        qtbot.addWidget(w)
        return w

    # ------------------------------------------------------------------
    # Создание
    # ------------------------------------------------------------------

    def test_creates_with_defaults(self, qtbot):
        nav = self._make(qtbot)
        assert nav.objectName() == "TreeNavWidget"
        assert nav.width() == 200

    def test_custom_nav_width(self, qtbot):
        nav = self._make(qtbot, nav_width=300)
        assert nav.maximumWidth() == 300  # noqa: PLR2004

    # ------------------------------------------------------------------
    # set_tree
    # ------------------------------------------------------------------

    def test_set_tree_creates_categories_and_children(self, qtbot):
        nav = self._make(qtbot)
        nav.set_tree(SAMPLE_TREE)

        tree = nav._tree
        assert tree.topLevelItemCount() == 2  # noqa: PLR2004
        # Первая категория — 3 ребёнка
        cat0 = tree.topLevelItem(0)
        assert cat0.text(0) == "Компоненты"
        assert cat0.childCount() == 3  # noqa: PLR2004
        assert cat0.child(0).text(0) == "Кнопки"

    def test_set_tree_empty_dict(self, qtbot):
        nav = self._make(qtbot)
        nav.set_tree({})
        assert nav._tree.topLevelItemCount() == 0

    def test_set_tree_skips_empty_categories(self, qtbot):
        """Категория с пустым списком подкатегорий не отображается."""
        nav = self._make(qtbot)
        nav.set_tree({"Пустая": [], "Непустая": ["Один"]})
        assert nav._tree.topLevelItemCount() == 1
        assert nav._tree.topLevelItem(0).text(0) == "Непустая"

    def test_set_tree_replaces_previous(self, qtbot):
        nav = self._make(qtbot)
        nav.set_tree(SAMPLE_TREE)
        nav.set_tree({"Новая": ["Элемент"]})
        assert nav._tree.topLevelItemCount() == 1

    # ------------------------------------------------------------------
    # select / current_selection
    # ------------------------------------------------------------------

    def test_select_sets_current(self, qtbot):
        nav = self._make(qtbot)
        nav.set_tree(SAMPLE_TREE)
        nav.select("Компоненты", "Чекбоксы")
        result = nav.current_selection()
        assert result == ("Компоненты", "Чекбоксы")

    def test_current_selection_none_when_empty(self, qtbot):
        nav = self._make(qtbot)
        assert nav.current_selection() is None

    def test_current_selection_none_when_no_leaf_selected(self, qtbot):
        nav = self._make(qtbot)
        nav.set_tree(SAMPLE_TREE)
        # Ничего не выбрано
        assert nav.current_selection() is None

    def test_select_nonexistent_no_crash(self, qtbot):
        nav = self._make(qtbot)
        nav.set_tree(SAMPLE_TREE)
        nav.select("НетТакой", "Тоже")
        assert nav.current_selection() is None

    # ------------------------------------------------------------------
    # Сигналы
    # ------------------------------------------------------------------

    def test_leaf_selected_signal_on_select(self, qtbot):
        nav = self._make(qtbot)
        nav.set_tree(SAMPLE_TREE)

        with qtbot.waitSignal(nav.leaf_selected, timeout=1000) as blocker:
            nav.select("Компоненты", "Кнопки")

        assert blocker.args == ["Компоненты", "Кнопки"]

    def test_category_selected_signal_on_click(self, qtbot):
        nav = self._make(qtbot)
        nav.set_tree(SAMPLE_TREE)

        cat_item = nav._tree.topLevelItem(0)
        with qtbot.waitSignal(nav.category_selected, timeout=1000) as blocker:
            # Имитация клика на категорию
            nav._tree.itemClicked.emit(cat_item, 0)

        assert blocker.args == ["Компоненты"]

    def test_leaf_click_emits_leaf_selected(self, qtbot):
        nav = self._make(qtbot)
        nav.set_tree(SAMPLE_TREE)

        leaf = nav._tree.topLevelItem(1).child(0)  # Макет -> Отступы
        with qtbot.waitSignal(nav.leaf_selected, timeout=1000) as blocker:
            nav._tree.setCurrentItem(leaf)

        assert blocker.args == ["Макет", "Отступы"]

    # ------------------------------------------------------------------
    # filter / clear_filter
    # ------------------------------------------------------------------

    def test_filter_hides_non_matching(self, qtbot):
        nav = self._make(qtbot)
        nav.set_tree(SAMPLE_TREE)
        nav.filter("кноп")

        tree = nav._tree
        # "Кнопки" видна
        assert not tree.topLevelItem(0).child(0).isHidden()
        # "Поля ввода" скрыта
        assert tree.topLevelItem(0).child(1).isHidden()
        # "Чекбоксы" скрыта
        assert tree.topLevelItem(0).child(2).isHidden()

    def test_filter_hides_empty_categories(self, qtbot):
        nav = self._make(qtbot)
        nav.set_tree(SAMPLE_TREE)
        nav.filter("кноп")

        # "Макет" — все дети скрыты → категория скрыта
        assert nav._tree.topLevelItem(1).isHidden()

    def test_filter_expands_matching_categories(self, qtbot):
        nav = self._make(qtbot)
        nav.set_tree(SAMPLE_TREE)
        nav.filter("кноп")

        # "Компоненты" содержит совпадение — развёрнута
        assert nav._tree.topLevelItem(0).isExpanded()

    def test_filter_no_matches_hides_all(self, qtbot):
        nav = self._make(qtbot)
        nav.set_tree(SAMPLE_TREE)
        nav.filter("zzzzz")

        tree = nav._tree
        for i in range(tree.topLevelItemCount()):
            assert tree.topLevelItem(i).isHidden()

    def test_clear_filter_restores_all(self, qtbot):
        nav = self._make(qtbot)
        nav.set_tree(SAMPLE_TREE)
        nav.filter("кноп")
        nav.clear_filter()

        tree = nav._tree
        for cat_idx in range(tree.topLevelItemCount()):
            cat = tree.topLevelItem(cat_idx)
            assert not cat.isHidden()
            assert not cat.isExpanded()
            for sub_idx in range(cat.childCount()):
                assert not cat.child(sub_idx).isHidden()
