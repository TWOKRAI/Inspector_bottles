# multiprocess_prototype/frontend/widgets/settings_recipe_widget/app_recipe_rows.py
"""
Строки таблицы для app-рецептов (SchemaBase приложения, не RegistersManager).
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

from multiprocess_framework.modules.data_schema_module import SchemaBase

from multiprocess_prototype_v2.managers.access_context import AccessContext

from ..recipes_widget.recipe_rows import scalar_for_editing


def _field_editable(schema: SchemaBase, field_name: str, ctx: AccessContext) -> bool:
    """Учитывая FieldMeta и уровень доступа — можно ли редактировать ячейку значения."""
    meta = schema.get_field_meta(field_name) if hasattr(schema, "get_field_meta") else None
    if meta is None:
        return True
    if meta.hidden and not ctx.show_hidden:
        return False
    if ctx.bypass_readonly:
        return True
    return meta.can_modify(ctx.level)


def build_app_recipe_rows(
    aggregate: Dict[str, SchemaBase],
    access_ctx: Optional[AccessContext] = None,
) -> List[dict]:
    """
    Строки для StructuredTableWidget: schema_name.field, значение, описание, редактируемость.
    """
    ctx = access_ctx or AccessContext()
    rows: List[dict] = []
    for schema_name, schema in aggregate.items():
        if not hasattr(schema, "model_dump"):
            continue
        data = schema.model_dump()
        for field_name, value in data.items():
            meta = schema.get_field_meta(field_name) if hasattr(schema, "get_field_meta") else None
            if meta is not None and meta.hidden and not ctx.show_hidden:
                continue
            desc = ""
            if meta:
                desc = str(meta.description or getattr(meta, "info", "") or "")
            field_id = f"{schema_name}.{field_name}"
            editable = scalar_for_editing(value) and _field_editable(schema, field_name, ctx)
            rows.append(
                {
                    "field_id": field_id,
                    "param": field_id,
                    "value": value,
                    "info": desc,
                    "schema_name": schema_name,
                    "field_name": field_name,
                    "_value_editable": editable,
                }
            )
    return rows


def group_rows_by_schema(rows: List[dict]) -> List[Tuple[str, List[dict]]]:
    """Сгруппировать строки app-рецепта по schema_name для StructuredTwoLevelTreeWidget."""
    order: List[str] = []
    by_schema: dict = defaultdict(list)
    for r in rows:
        sch = str(r.get("schema_name") or "")
        if sch not in order:
            order.append(sch)
        rr = dict(r)
        rr["param"] = str(r.get("field_name") or r.get("param") or "")
        by_schema[sch].append(rr)
    for sch in by_schema:
        by_schema[sch].sort(key=lambda x: str(x.get("field_name", "")))
    return [(k, by_schema[k]) for k in order]
