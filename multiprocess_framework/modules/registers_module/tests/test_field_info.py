# -*- coding: utf-8 -*-
"""FieldInfo: конвенience-свойства для UI-hints FieldMeta (NEW-5).

ui_group/ui_order/ui_hidden/ui_widget — тонкие проксирующие свойства над
self.meta, зеркалят существующий паттерн title/min_value/max_value/unit.
ui_widget — алиас на FieldMeta.widget (единый источник widget-подсказки,
отдельного атрибута FieldMeta.ui_widget не заводим — см. ADR-DS-008).
"""

from __future__ import annotations

from typing import Annotated

from multiprocess_framework.modules.data_schema_module import FieldMeta, SchemaBase
from multiprocess_framework.modules.registers_module.core.field_info import FieldInfo, extract_fields


class _WithHints(SchemaBase):
    a: Annotated[
        float,
        FieldMeta("A", ui_group="Оптика", ui_order=2, ui_hidden=False, widget="slider"),
    ] = 1.0
    b: Annotated[
        int,
        FieldMeta("B", ui_hidden=True),
    ] = 0
    # Поле без FieldMeta — meta=None, свойства должны отдавать безопасные дефолты.
    plain: int = 5


def test_ui_group_from_meta() -> None:
    fields = extract_fields("p", _WithHints)
    fi = next(f for f in fields if f.field_name == "a")
    assert fi.ui_group == "Оптика"


def test_ui_order_from_meta() -> None:
    fields = extract_fields("p", _WithHints)
    fi = next(f for f in fields if f.field_name == "a")
    assert fi.ui_order == 2


def test_ui_hidden_from_meta() -> None:
    fields = extract_fields("p", _WithHints)
    fi_a = next(f for f in fields if f.field_name == "a")
    fi_b = next(f for f in fields if f.field_name == "b")
    assert fi_a.ui_hidden is False
    assert fi_b.ui_hidden is True


def test_ui_widget_aliases_meta_widget() -> None:
    fields = extract_fields("p", _WithHints)
    fi = next(f for f in fields if f.field_name == "a")
    assert fi.ui_widget == "slider"


def test_defaults_without_meta() -> None:
    fields = extract_fields("p", _WithHints)
    fi = next(f for f in fields if f.field_name == "plain")
    assert fi.ui_group is None
    assert fi.ui_order is None
    assert fi.ui_hidden is False
    assert fi.ui_widget == ""


def test_defaults_with_meta_but_no_hints() -> None:
    fi = FieldInfo(
        plugin_name="p",
        field_name="x",
        field_type=int,
        default=0,
        meta=FieldMeta("X"),
    )
    assert fi.ui_group is None
    assert fi.ui_order is None
    assert fi.ui_hidden is False
    assert fi.ui_widget == ""
