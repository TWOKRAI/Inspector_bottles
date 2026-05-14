"""Тесты build_table_for_register (table-представление, ~4 теста)."""

from __future__ import annotations

from PySide6.QtWidgets import QTableWidget

from multiprocess_framework.modules.data_schema_module import FieldMeta
from multiprocess_prototype.frontend.forms.form_builder import build_table_for_register
from multiprocess_prototype.registers.field_info import FieldInfo


def _fi(
    field_name: str,
    field_type: type = int,
    default=0,
    meta: FieldMeta | None = None,
    plugin_name: str = "test",
    category: str = "",
) -> FieldInfo:
    return FieldInfo(
        plugin_name=plugin_name,
        field_name=field_name,
        field_type=field_type,
        default=default,
        meta=meta,
        category=category,
    )


class TestBuildTableForRegister:
    """Тесты table-представления."""

    def test_returns_table_with_4_columns(self, qtbot):
        """Таблица имеет 4 колонки: Параметр, Значение, Единица, Описание."""
        fields = [_fi("x", int, 10, meta=FieldMeta("Координата X", unit="px"))]
        table, editors = build_table_for_register(fields)
        qtbot.addWidget(table)

        assert isinstance(table, QTableWidget)
        assert table.columnCount() == 4
        headers = [table.horizontalHeaderItem(i).text() for i in range(4)]
        assert headers == ["Параметр", "Значение", "Единица", "Описание"]

    def test_category_separator_row(self, qtbot):
        """Категория отображается как строка-разделитель с объединёнными ячейками."""
        fields = [
            _fi("a", int, 1, category="system"),
            _fi("b", int, 2, category="system"),
        ]
        titles = {"system": "Система"}
        table, editors = build_table_for_register(fields, category_titles=titles)
        qtbot.addWidget(table)

        # Первая строка — разделитель "Система"
        assert table.rowCount() == 3  # 1 разделитель + 2 поля
        separator = table.item(0, 0)
        assert separator is not None
        assert separator.text() == "Система"
        # span: 1 row x 4 columns
        assert table.columnSpan(0, 0) == 4

    def test_cell_widget_is_set(self, qtbot):
        """В колонку 'Значение' помещается editor.widget через setCellWidget."""
        fields = [_fi("val", int, 42)]
        table, editors = build_table_for_register(fields)
        qtbot.addWidget(table)

        # Без категории — первая строка = поле
        cell_widget = table.cellWidget(0, 1)
        assert cell_widget is not None
        assert cell_widget is editors["test.val"].widget

    def test_empty_fields_returns_empty_table(self, qtbot):
        """Пустой список полей → таблица с 0 строками."""
        table, editors = build_table_for_register([])
        qtbot.addWidget(table)

        assert table.rowCount() == 0
        assert editors == {}
