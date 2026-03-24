# multiprocess_prototype/frontend/widgets/tabs_setting/recipes_tab/app_recipe_rows.py
"""
Строки таблицы для app-рецептов (SchemaBase приложения, не RegistersManager).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from multiprocess_framework.refactored.modules.data_schema_module import SchemaBase

from multiprocess_prototype.managers.access_context import AccessContext

from .recipe_rows import scalar_for_editing


def _field_editable(schema: SchemaBase, field_name: str, ctx: AccessContext) -> bool:
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
