# -*- coding: utf-8 -*-
"""Демо-тест NEW-5: build_form_for_schema + UI-hints резолвера kinds.

Формы из схемы «форма = Pydantic-класс»: build_form_for_schema(schema_cls)
сам извлекает FieldInfo (extract_fields), фильтрует ui_hidden, сортирует по
ui_order, группирует по ui_group и делегирует построение существующей
7a-фабрике (build_form_for_register → CardsFieldFactory). Также проверяет,
что резолвер kinds логирует WARNING при неизвестном widget-значении и
делает graceful fallback на type-dispatch (не падает).
"""

from __future__ import annotations

import logging
from typing import Annotated

from PySide6.QtWidgets import QCheckBox, QGroupBox, QScrollArea

from multiprocess_framework.modules.data_schema_module import FieldMeta, SchemaBase
from multiprocess_prototype.frontend.forms.factory import CardsFieldFactory
from multiprocess_prototype.frontend.forms.form_builder import build_form_for_schema
from multiprocess_framework.modules.registers_module.core.field_info import FieldInfo


# --------------------------------------------------------------------------- #
#  Демо-схема: ui_group/ui_order/ui_hidden/ui_widget                          #
# --------------------------------------------------------------------------- #


class _DemoSchema(SchemaBase):
    speed: Annotated[
        float,
        FieldMeta("Скорость", ui_group="Motion", ui_order=2),
    ] = 1.0
    accel: Annotated[
        float,
        FieldMeta("Ускорение", ui_group="Motion", ui_order=1),
    ] = 0.5
    # widget="checkbox" переопределяет type-dispatch: int обычно → QSpinBox,
    # но явный widget-hint требует QCheckBox.
    flag: Annotated[
        int,
        FieldMeta("Флаг", ui_group="Misc", widget="checkbox"),
    ] = 0
    secret: Annotated[
        str,
        FieldMeta("Секрет", ui_hidden=True),
    ] = "x"


class TestBuildFormForSchema:
    """Состав/порядок/виджеты формы, построенной прямо из схемы."""

    def test_ui_hidden_field_excluded(self, qtbot):
        form, editors = build_form_for_schema(_DemoSchema)
        qtbot.addWidget(form)
        assert "secret" not in editors

    def test_visible_fields_present(self, qtbot):
        form, editors = build_form_for_schema(_DemoSchema)
        qtbot.addWidget(form)
        assert set(editors) == {"speed", "accel", "flag"}

    def test_ui_order_within_group(self, qtbot):
        """accel (ui_order=1) должен идти раньше speed (ui_order=2) в Motion."""
        form, editors = build_form_for_schema(_DemoSchema)
        qtbot.addWidget(form)

        container = form.widget()
        group_boxes = {gb.title(): gb for gb in container.findChildren(QGroupBox)}
        assert "Motion" in group_boxes

        layout = group_boxes["Motion"].layout()
        # QFormLayout: строки в порядке addRow — сверяем порядок полей по field widget identity.
        row_widgets = [layout.itemAt(i, layout.ItemRole.FieldRole).widget() for i in range(layout.rowCount())]
        assert row_widgets == [editors["accel"].widget, editors["speed"].widget]

    def test_ui_group_creates_separate_groupboxes(self, qtbot):
        form, editors = build_form_for_schema(_DemoSchema)
        qtbot.addWidget(form)

        container = form.widget()
        titles = {gb.title() for gb in container.findChildren(QGroupBox)}
        assert {"Motion", "Misc"} <= titles

    def test_ui_widget_checkbox_overrides_int_default(self, qtbot):
        """flag: int + widget='checkbox' → QCheckBox, не QSpinBox."""
        form, editors = build_form_for_schema(_DemoSchema)
        qtbot.addWidget(form)
        assert isinstance(editors["flag"].widget, QCheckBox)

    def test_returns_scroll_area(self, qtbot):
        form, _ = build_form_for_schema(_DemoSchema)
        qtbot.addWidget(form)
        assert isinstance(form, QScrollArea)


# --------------------------------------------------------------------------- #
#  Резолвер kinds: неизвестный ui_widget → WARNING + graceful fallback        #
# --------------------------------------------------------------------------- #


def _fi(field_type: type, default=None, meta: FieldMeta | None = None) -> FieldInfo:
    return FieldInfo(
        plugin_name="test",
        field_name="f",
        field_type=field_type,
        default=default,
        meta=meta,
    )


class TestUnknownWidgetWarning:
    def test_unknown_widget_falls_back_to_type_dispatch(self):
        """Неизвестное значение widget не ломает резолв — используется type-dispatch."""
        fi = _fi(int, default=1, meta=FieldMeta(widget="totally_unknown_widget"))
        assert CardsFieldFactory.resolve_kind(fi) == "int"

    def test_unknown_widget_logs_warning(self, caplog):
        fi = _fi(int, default=1, meta=FieldMeta(widget="totally_unknown_widget"))
        with caplog.at_level(logging.WARNING, logger="multiprocess_prototype.frontend.forms.factory.kinds"):
            CardsFieldFactory.resolve_kind(fi)
        assert any("totally_unknown_widget" in rec.message for rec in caplog.records)

    def test_known_widget_no_warning(self, caplog):
        fi = _fi(int, default=1, meta=FieldMeta(widget="slider"))
        with caplog.at_level(logging.WARNING, logger="multiprocess_prototype.frontend.forms.factory.kinds"):
            CardsFieldFactory.resolve_kind(fi)
        assert caplog.records == []
