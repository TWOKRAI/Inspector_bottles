"""Builders для двух представлений: Cards (QGroupBox + QFormLayout) и Table (QTableWidget).

Оба builder-а принимают опциональный ``editors`` kwarg. Если передан — виджеты
из editors размещаются в layout/cells без создания новых. Это обеспечивает
shared-editor-инвариант: один FieldEditor живёт и в cards, и в table.
"""

from __future__ import annotations

from dataclasses import replace
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

from multiprocess_framework.modules.registers_module.core.field_info import extract_fields

from .factory import CardsFieldFactory

if TYPE_CHECKING:
    from multiprocess_framework.modules.data_schema_module import SchemaBase
    from multiprocess_framework.modules.registers_module.core.field_info import FieldInfo
    from multiprocess_framework.modules.frontend_module.forms.form_context import FormContext

    from .field_editor import FieldEditor

# Сортировка по ui_order: поля без явного порядка (None) уходят в конец,
# сохраняя исходный порядок объявления в модели (stable sort).
_UNORDERED = float("inf")


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


def build_form_for_schema(
    schema_cls: type[SchemaBase],
    parent: QWidget | None = None,
    **kwargs: object,
) -> tuple[QWidget, dict[str, FieldEditor]]:
    """Построить cards-форму прямо из Pydantic-класса схемы («форма = класс»).

    Тонкий публичный хелпер над `build_form_for_register`: сам извлекает
    FieldInfo из `schema_cls` через `extract_fields` и применяет UI-hints
    каталога FieldMeta (Task NEW-5), затем делегирует построение
    существующей 7a-фабрике — builders (`CardsFieldFactory` /
    `build_form_for_register`) НЕ переопределяются и не дублируются:

        - `ui_hidden` — поля с этим флагом исключаются из формы (это
          presentation-фильтр конкретной формы, не access-control — не
          путать с `FieldMeta.hidden`/`access_level`, которые действуют на
          уровне модели и остаются нетронутыми).
        - `ui_order` — поля сортируются по возрастанию; поля без явного
          порядка (None) идут в конец, сохраняя исходный порядок объявления
          в модели (stable sort).
        - `ui_group` — поля группируются в QGroupBox. Реализовано через
          переиспользование существующего механизма `category` у
          `build_form_for_register` (`FieldInfo.category` подменяется на
          `ui_group` только для рендера — `build_form_for_schema` строит
          форму из ОДНОЙ схемы, поэтому плагин-категория здесь не нужна).
        - `ui_widget` (= `FieldMeta.widget`) учитывается штатно — резолвер
          kinds (`forms/factory/kinds.py`) уже читает `meta.widget` как
          приоритетную подсказку, отдельной обработки не требуется.

    Аргументы:
        schema_cls: SchemaBase-класс регистра/конфига.
        parent: родительский Qt-виджет.
        **kwargs: прокидываются в `build_form_for_register` (например,
            `editors`, `form_ctx`, `category_titles`, `group_by_category`).

    Возвращает:
        (scroll_widget, editors_dict) — как `build_form_for_register`;
        ключи editors — `field_name` (без префикса плагина, т.к. схема одна).
    """
    fields = extract_fields(plugin_name="", register_cls=schema_cls)

    # ui_hidden — presentation-фильтр конкретной формы (не access-control).
    visible = [fi for fi in fields if not fi.ui_hidden]

    # Сортировка по ui_order (None → в конец, stable относительно исходного
    # порядка модели), затем — подмена category на ui_group для группировки
    # через уже существующий механизм build_form_for_register.
    visible.sort(key=lambda fi: fi.ui_order if fi.ui_order is not None else _UNORDERED)
    grouped = [replace(fi, category=fi.ui_group or "") for fi in visible]

    kwargs.setdefault("group_by_category", True)
    return build_form_for_register(grouped, parent=parent, **kwargs)  # type: ignore[arg-type]


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
