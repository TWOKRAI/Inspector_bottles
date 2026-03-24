# multiprocess_prototype/frontend/widgets/tabs_setting/recipes_tab/recipe_rows.py
"""
Построение строк таблицы рецептов из RegistersManager / bridge (обход регистров и полей).
"""

from __future__ import annotations

import ast
import json
from typing import Any, List, Optional

from multiprocess_prototype.managers.access_context import AccessContext


def scalar_for_editing(value: Any) -> bool:
    return value is None or isinstance(value, (bool, int, float, str))


def _scalar_for_editing(value: Any) -> bool:
    return scalar_for_editing(value)


def _register_field_editable(rm: Any, reg: Any, register_name: str, field_name: str, ctx: AccessContext) -> bool:
    if hasattr(reg, "get_field_meta"):
        meta = reg.get_field_meta(field_name)
        if meta is None:
            return True
        if meta.hidden and not ctx.show_hidden:
            return False
        if ctx.bypass_readonly:
            return True
        return meta.can_modify(ctx.level)
    meta = rm.get_field_metadata(register_name, field_name) if rm else {}
    if meta.get("hidden") and not ctx.show_hidden:
        return False
    if ctx.bypass_readonly:
        return True
    if meta.get("readonly"):
        return False
    return int(meta.get("access_level", 0)) <= ctx.level


def format_value_for_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        try:
            return json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError):
            return str(value)
    return str(value)


def coerce_string_to_value(text: str, previous: Any) -> Any:
    """Преобразовать текст ячейки к значению с учётом типа предыдущего значения."""
    s = text.strip()
    if previous is None and s == "":
        return None
    if isinstance(previous, bool):
        low = s.lower()
        if low in ("true", "1", "yes", "да"):
            return True
        if low in ("false", "0", "no", "нет"):
            return False
        return previous
    if isinstance(previous, int):
        try:
            return int(s)
        except ValueError:
            return previous
    if isinstance(previous, float):
        try:
            return float(s.replace(",", "."))
        except ValueError:
            return previous
    if isinstance(previous, str):
        return text
    if isinstance(previous, (dict, list)):
        try:
            return json.loads(s)
        except (json.JSONDecodeError, TypeError):
            try:
                return ast.literal_eval(s)
            except (ValueError, SyntaxError):
                return previous
    if s == "":
        return previous
    try:
        return ast.literal_eval(s)
    except (ValueError, SyntaxError):
        return text


def build_recipe_rows(rm: Any, access_ctx: Optional[AccessContext] = None) -> List[dict]:
    """
    Собрать строки для StructuredTableWidget.

    Каждая строка: field_id, param, value (сырое для format), info, register_name,
    field_name, _value_editable.
    """
    ctx = access_ctx or AccessContext()
    rows: List[dict] = []
    names_fn = getattr(rm, "register_names", None)
    if not callable(names_fn):
        return rows
    for register_name in names_fn():
        reg = rm.get_register(register_name)
        if reg is None:
            continue
        if hasattr(reg, "model_dump"):
            data = reg.model_dump()
        elif isinstance(reg, dict):
            data = reg
        else:
            data = {}
        for field_name, value in data.items():
            if hasattr(reg, "get_field_meta"):
                fm = reg.get_field_meta(field_name)
                if fm is not None and fm.hidden and not ctx.show_hidden:
                    continue
            else:
                meta_h = rm.get_field_metadata(register_name, field_name)
                if meta_h.get("hidden") and not ctx.show_hidden:
                    continue
            meta = rm.get_field_metadata(register_name, field_name)
            desc = ""
            if meta:
                desc = str(meta.get("description") or meta.get("info") or "")
            field_id = f"{register_name}.{field_name}"
            editable = _scalar_for_editing(value) and _register_field_editable(
                rm, reg, register_name, field_name, ctx
            )
            rows.append(
                {
                    "field_id": field_id,
                    "param": field_id,
                    "value": value,
                    "info": desc,
                    "register_name": register_name,
                    "field_name": field_name,
                    "_value_editable": editable,
                }
            )
    return rows
