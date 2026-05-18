"""Builders для двух представлений: Cards (QGroupBox + QFormLayout) и Table (QTableWidget).

Оба builder-а принимают опциональный ``editors`` kwarg. Если передан — виджеты
из editors размещаются в layout/cells без создания новых. Это обеспечивает
shared-editor-инвариант: один FieldEditor живёт и в cards, и в table.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QHeaderView,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .factory import CardsFieldFactory

if TYPE_CHECKING:
    from multiprocess_framework.modules.registers_module.core.field_info import FieldInfo
    from multiprocess_framework.modules.frontend_module.forms.form_context import FormContext

    from .field_editor import FieldEditor


# ---------------------------------------------------------------------------
# Cards view
# ---------------------------------------------------------------------------


def build_form_for_register(
    fields: list[FieldInfo],
    *,
    editors: dict[str, FieldEditor] | None = None,
    parent: QWidget | None = None,
    group_by_category: bool = True,
    category_titles: dict[str, str] | None = None,
    form_ctx: FormContext | None = None,
) -> tuple[QWidget, dict[str, FieldEditor]]:
    """Построить cards-представление (QGroupBox + QFormLayout в QScrollArea).

    Аргументы:
        fields: список FieldInfo для отображения.
        editors: если передан — используются существующие editors (shared mode).
                 Если None — editors создаются внутри через CardsFieldFactory.
        parent: родительский виджет.
        group_by_category: группировать поля по category в QGroupBox.
        category_titles: маппинг category → русское название группы.
        form_ctx: передаётся в CardsFieldFactory.create; если None — legacy путь без binding.
                  NOTE: в shared-mode (editors переданы извне) form_ctx игнорируется —
                  уже созданные editors не перестраиваются.

    Возвращает:
        (scroll_widget, editors_dict) — QScrollArea с формой и словарь editors.
    """
    if category_titles is None:
        category_titles = {}

    # Создать editors если не переданы
    if editors is None:
        editors = {}
        for fi in fields:
            key = _editor_key(fi)
            editors[key] = CardsFieldFactory.create(fi, form_ctx=form_ctx)

    # Группировка по category
    if group_by_category:
        groups: dict[str, list[FieldInfo]] = {}
        for fi in fields:
            cat = fi.category or ""
            groups.setdefault(cat, []).append(fi)
    else:
        groups = {"": list(fields)}

    # Контейнер внутри scroll area
    container = QWidget()
    container_layout = QVBoxLayout(container)
    container_layout.setContentsMargins(4, 4, 4, 4)

    for cat_key, cat_fields in groups.items():
        # Название группы
        title = category_titles.get(cat_key, cat_key) if cat_key else ""

        if group_by_category and title:
            group_box = QGroupBox(title, container)
            form_layout = QFormLayout(group_box)
        else:
            group_box = None
            form_layout = QFormLayout()

        for fi in cat_fields:
            key = _editor_key(fi)
            editor = editors[key]
            form_layout.addRow(editor.label, editor.widget)

        if group_box is not None:
            container_layout.addWidget(group_box)
        else:
            container_layout.addLayout(form_layout)

    container_layout.addStretch()

    # Обернуть в QScrollArea
    scroll = QScrollArea(parent)
    scroll.setWidgetResizable(True)
    scroll.setWidget(container)

    return scroll, editors


# ---------------------------------------------------------------------------
# Table view
# ---------------------------------------------------------------------------

_TABLE_COLUMNS = ["Параметр", "Значение", "Единица", "Описание"]


def build_table_for_register(
    fields: list[FieldInfo],
    *,
    editors: dict[str, FieldEditor] | None = None,
    parent: QWidget | None = None,
    category_titles: dict[str, str] | None = None,
    form_ctx: FormContext | None = None,
) -> tuple[QWidget, dict[str, FieldEditor]]:
    """Построить table-представление (QTableWidget с 4 колонками).

    Колонки: Параметр | Значение | Единица | Описание.
    Категории отображаются как строки-заголовки с объединёнными ячейками.

    Аргументы:
        fields: список FieldInfo.
        editors: если передан — используются существующие editors (shared mode).
        parent: родительский виджет.
        category_titles: маппинг category → русское название.
        form_ctx: передаётся в CardsFieldFactory.create; если None — legacy путь без binding.
                  NOTE: в shared-mode (editors переданы извне) form_ctx игнорируется —
                  уже созданные editors не перестраиваются.

    Возвращает:
        (table_widget, editors_dict).
    """
    if category_titles is None:
        category_titles = {}

    # Создать editors если не переданы
    if editors is None:
        editors = {}
        for fi in fields:
            key = _editor_key(fi)
            editors[key] = CardsFieldFactory.create(fi, form_ctx=form_ctx)

    # Группировка по category для отображения разделителей
    groups: dict[str, list[FieldInfo]] = {}
    for fi in fields:
        cat = fi.category or ""
        groups.setdefault(cat, []).append(fi)

    # Подсчёт строк: категории-разделители + поля
    total_rows = 0
    for cat_key, cat_fields in groups.items():
        title = category_titles.get(cat_key, cat_key) if cat_key else ""
        if title:
            total_rows += 1  # строка-разделитель
        total_rows += len(cat_fields)

    table = QTableWidget(total_rows, len(_TABLE_COLUMNS), parent)
    table.setHorizontalHeaderLabels(_TABLE_COLUMNS)
    table.verticalHeader().setVisible(False)

    # Растянуть колонки
    header = table.horizontalHeader()
    header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
    header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
    header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
    header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)

    row = 0
    for cat_key, cat_fields in groups.items():
        title = category_titles.get(cat_key, cat_key) if cat_key else ""

        # Строка-разделитель категории
        if title:
            item = QTableWidgetItem(title)
            font = item.font()
            font.setBold(True)
            item.setFont(font)
            table.setItem(row, 0, item)
            table.setSpan(row, 0, 1, len(_TABLE_COLUMNS))
            row += 1

        # Строки полей
        for fi in cat_fields:
            key = _editor_key(fi)
            editor = editors[key]

            # Колонка 0: Параметр (название)
            name_item = QTableWidgetItem(fi.title)
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(row, 0, name_item)

            # Колонка 1: Значение (виджет)
            table.setCellWidget(row, 1, editor.widget)

            # Колонка 2: Единица
            unit_item = QTableWidgetItem(fi.unit or "")
            table.setItem(row, 2, unit_item)

            # Колонка 3: Описание
            description = ""
            if fi.meta:
                description = fi.meta.info or fi.meta.description or ""
            desc_item = QTableWidgetItem(description)
            table.setItem(row, 3, desc_item)

            row += 1

    return table, editors


# ---------------------------------------------------------------------------
# Утилиты
# ---------------------------------------------------------------------------


def _editor_key(fi: FieldInfo) -> str:
    """Ключ редактора: plugin_name.field_name или просто field_name."""
    if fi.plugin_name:
        return f"{fi.plugin_name}.{fi.field_name}"
    return fi.field_name
