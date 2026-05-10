"""Тесты примитивных виджетов второго пакета (Task primitives batch 2).

Покрывает: MasterDetailLayout, SlotSelector, CrudTable, SectionedForm.
"""

import pytest
from multiprocess_prototype.frontend.widgets.primitives.master_detail import MasterDetailLayout
from multiprocess_prototype.frontend.widgets.primitives.slot_selector import SlotSelector
from multiprocess_prototype.frontend.widgets.primitives.crud_table import CrudTable
from multiprocess_prototype.frontend.widgets.primitives.sectioned_form import SectionedForm


# ===========================================================================
# MasterDetailLayout
# ===========================================================================

class TestMasterDetailLayout:
    def test_create(self, qtbot):
        """Виджет создаётся без ошибок."""
        w = MasterDetailLayout()
        qtbot.addWidget(w)

    def test_set_items(self, qtbot):
        """set_items заполняет список без ошибок."""
        w = MasterDetailLayout()
        qtbot.addWidget(w)
        w.set_items([("p1", "Plugin 1", "processing"), ("p2", "Plugin 2", "source")])

    def test_set_categories(self, qtbot):
        """set_categories заполняет комбобокс без ошибок."""
        w = MasterDetailLayout()
        qtbot.addWidget(w)
        w.set_categories(["processing", "source", "output"])

    def test_selection_initially_none(self, qtbot):
        """До выбора элемента selected_key() возвращает None."""
        w = MasterDetailLayout()
        qtbot.addWidget(w)
        w.set_items([("p1", "Plugin 1", "processing")])
        assert w.selected_key() is None

    def test_set_detail_widget(self, qtbot):
        """set_detail_widget добавляет виджет в стек без ошибок."""
        from PySide6.QtWidgets import QLabel

        w = MasterDetailLayout()
        qtbot.addWidget(w)
        w.set_detail_widget("p1", QLabel("Details for p1"))

    def test_filter_text_empty_by_default(self, qtbot):
        """filter_text() по умолчанию возвращает пустую строку."""
        w = MasterDetailLayout()
        qtbot.addWidget(w)
        assert w.filter_text() == ""

    def test_set_items_count(self, qtbot):
        """После set_items количество элементов в списке совпадает с переданным."""
        w = MasterDetailLayout()
        qtbot.addWidget(w)
        w.set_items([
            ("k1", "Item 1", "cat_a"),
            ("k2", "Item 2", "cat_b"),
            ("k3", "Item 3", "cat_a"),
        ])
        assert w._item_list.count() == 3

    def test_categories_include_all(self, qtbot):
        """После set_categories первый элемент комбобокса — «Все»."""
        w = MasterDetailLayout()
        qtbot.addWidget(w)
        w.set_categories(["cat_a", "cat_b"])
        assert w._category_filter.itemText(0) == "Все"
        assert w._category_filter.count() == 3  # "Все" + 2 категории

    def test_search_placeholder(self, qtbot):
        """Кастомный placeholder отображается в поле поиска."""
        w = MasterDetailLayout(search_placeholder="Найти плагин...")
        qtbot.addWidget(w)
        assert w._search.placeholderText() == "Найти плагин..."

    def test_signal_on_selection(self, qtbot):
        """selection_changed эмитируется при выборе элемента в списке."""
        w = MasterDetailLayout()
        qtbot.addWidget(w)
        w.set_items([("key1", "Item One", "cat")])

        with qtbot.waitSignal(w.selection_changed) as blocker:
            w._item_list.setCurrentRow(0)

        assert blocker.args == ["key1"]


# ===========================================================================
# SlotSelector
# ===========================================================================

class TestSlotSelector:
    def test_create(self, qtbot):
        """Виджет создаётся с правильным количеством слотов."""
        w = SlotSelector(count=8)
        qtbot.addWidget(w)
        assert w.count() == 8

    def test_select(self, qtbot):
        """select() выделяет нужный слот."""
        w = SlotSelector(count=4)
        qtbot.addWidget(w)
        w.select(2)
        assert w.selected_index() == 2

    def test_select_changes_previous(self, qtbot):
        """select() снимает выделение с предыдущего выбранного слота."""
        w = SlotSelector(count=4)
        qtbot.addWidget(w)
        w.select(0)
        assert w.selected_index() == 0
        w.select(3)
        assert w.selected_index() == 3
        # Предыдущий слот должен быть в состоянии "empty"
        assert w._states[0] == "empty"

    def test_set_slot_state(self, qtbot):
        """set_slot_state меняет состояние без ошибок."""
        w = SlotSelector(count=4)
        qtbot.addWidget(w)
        w.set_slot_state(0, "occupied")
        assert w._states[0] == "occupied"

    def test_slot_label(self, qtbot):
        """set_slot_label меняет текст кнопки."""
        w = SlotSelector(count=4)
        qtbot.addWidget(w)
        w.set_slot_label(0, "Recipe A")
        assert w._buttons[0].text() == "Recipe A"

    def test_signal(self, qtbot):
        """slot_selected эмитируется при клике на кнопку."""
        w = SlotSelector(count=4)
        qtbot.addWidget(w)
        with qtbot.waitSignal(w.slot_selected):
            w._buttons[1].click()

    def test_signal_index(self, qtbot):
        """slot_selected передаёт корректный индекс."""
        w = SlotSelector(count=4)
        qtbot.addWidget(w)
        with qtbot.waitSignal(w.slot_selected) as blocker:
            w._buttons[2].click()
        assert blocker.args == [2]

    def test_initial_state_empty(self, qtbot):
        """Все слоты при создании имеют состояние 'empty'."""
        w = SlotSelector(count=3)
        qtbot.addWidget(w)
        assert all(s == "empty" for s in w._states)

    def test_initial_selected_minus_one(self, qtbot):
        """При создании ничего не выбрано — selected_index() == -1."""
        w = SlotSelector(count=4)
        qtbot.addWidget(w)
        assert w.selected_index() == -1


# ===========================================================================
# CrudTable
# ===========================================================================

class TestCrudTable:
    def test_create(self, qtbot):
        """Таблица создаётся без ошибок."""
        t = CrudTable(columns=["Name", "Value"])
        qtbot.addWidget(t)

    def test_add_row(self, qtbot):
        """add_row возвращает корректный индекс и увеличивает row_count."""
        t = CrudTable(columns=["Name", "Value"])
        qtbot.addWidget(t)
        idx = t.add_row(["key1", "val1"])
        assert idx == 0
        assert t.row_count() == 1

    def test_add_multiple_rows(self, qtbot):
        """add_row возвращает последовательные индексы."""
        t = CrudTable(columns=["A"])
        qtbot.addWidget(t)
        assert t.add_row(["x"]) == 0
        assert t.add_row(["y"]) == 1
        assert t.row_count() == 2

    def test_set_data(self, qtbot):
        """set_data заменяет данные и обновляет row_count."""
        t = CrudTable(columns=["A", "B"])
        qtbot.addWidget(t)
        t.set_data([["a1", "b1"], ["a2", "b2"]])
        assert t.row_count() == 2

    def test_set_data_replaces_existing(self, qtbot):
        """set_data полностью заменяет предыдущие данные."""
        t = CrudTable(columns=["A"])
        qtbot.addWidget(t)
        t.add_row(["old"])
        t.set_data([["new1"], ["new2"]])
        assert t.row_count() == 2
        assert t.get_row_data(0) == ["new1"]

    def test_remove_selected(self, qtbot):
        """remove_selected удаляет выбранную строку."""
        t = CrudTable(columns=["A"])
        qtbot.addWidget(t)
        t.add_row(["x"])
        t.add_row(["y"])
        t._table.selectRow(0)
        t.remove_selected()
        assert t.row_count() == 1

    def test_get_row_data(self, qtbot):
        """get_row_data возвращает данные строки как список строк."""
        t = CrudTable(columns=["A", "B"])
        qtbot.addWidget(t)
        t.add_row(["x", "y"])
        assert t.get_row_data(0) == ["x", "y"]

    def test_selected_row_initially_minus_one(self, qtbot):
        """При создании ничего не выбрано — selected_row() == -1."""
        t = CrudTable(columns=["A"])
        qtbot.addWidget(t)
        assert t.selected_row() == -1

    def test_row_added_signal(self, qtbot):
        """row_added эмитируется при добавлении строки через add_row."""
        t = CrudTable(columns=["A"])
        qtbot.addWidget(t)
        with qtbot.waitSignal(t.row_added):
            t.add_row(["val"])

    def test_row_removed_signal(self, qtbot):
        """row_removed эмитируется при удалении строки через remove_selected."""
        t = CrudTable(columns=["A"])
        qtbot.addWidget(t)
        t.add_row(["val"])
        t._table.selectRow(0)
        with qtbot.waitSignal(t.row_removed):
            t.remove_selected()

    def test_set_add_enabled(self, qtbot):
        """set_add_enabled отключает кнопку «Добавить»."""
        t = CrudTable(columns=["A"])
        qtbot.addWidget(t)
        t.set_add_enabled(False)
        assert not t._add_btn.isEnabled()

    def test_set_remove_enabled(self, qtbot):
        """set_remove_enabled отключает кнопку «Удалить»."""
        t = CrudTable(columns=["A"])
        qtbot.addWidget(t)
        t.set_remove_enabled(False)
        assert not t._remove_btn.isEnabled()


# ===========================================================================
# SectionedForm
# ===========================================================================

class TestSectionedForm:
    def test_create(self, qtbot):
        """Форма создаётся без секций."""
        f = SectionedForm()
        qtbot.addWidget(f)
        assert f.section_count() == 0

    def test_add_section(self, qtbot):
        """add_section добавляет секцию и возвращает QGroupBox."""
        from PySide6.QtWidgets import QLabel

        f = SectionedForm()
        qtbot.addWidget(f)
        gb = f.add_section("Test Section", QLabel("Content"))
        assert f.section_count() == 1
        assert gb is not None

    def test_add_section_title(self, qtbot):
        """Заголовок QGroupBox соответствует переданному title."""
        from PySide6.QtWidgets import QLabel

        f = SectionedForm()
        qtbot.addWidget(f)
        gb = f.add_section("My Section", QLabel("x"))
        assert gb.title() == "My Section"

    def test_add_multiple_sections(self, qtbot):
        """Можно добавить несколько секций."""
        from PySide6.QtWidgets import QLabel

        f = SectionedForm()
        qtbot.addWidget(f)
        f.add_section("A", QLabel("a"))
        f.add_section("B", QLabel("b"))
        f.add_section("C", QLabel("c"))
        assert f.section_count() == 3

    def test_clear_sections(self, qtbot):
        """clear_sections удаляет все секции."""
        from PySide6.QtWidgets import QLabel

        f = SectionedForm()
        qtbot.addWidget(f)
        f.add_section("A", QLabel("a"))
        f.add_section("B", QLabel("b"))
        assert f.section_count() == 2
        f.clear_sections()
        assert f.section_count() == 0

    def test_add_after_clear(self, qtbot):
        """После clear_sections можно снова добавлять секции."""
        from PySide6.QtWidgets import QLabel

        f = SectionedForm()
        qtbot.addWidget(f)
        f.add_section("Old", QLabel("old"))
        f.clear_sections()
        f.add_section("New", QLabel("new"))
        assert f.section_count() == 1
