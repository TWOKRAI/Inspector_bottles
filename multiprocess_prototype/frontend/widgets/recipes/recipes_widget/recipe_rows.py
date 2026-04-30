# multiprocess_prototype/frontend/widgets/recipes_widget/recipe_rows.py
"""
Построение строк таблицы рецептов из RegistersManager / bridge (обход регистров и полей).
"""

from __future__ import annotations

import ast
import json
from collections import defaultdict
from typing import Any, List, Optional, Tuple

from multiprocess_prototype.frontend.managers.access_context import AccessContext


def scalar_for_editing(value: Any) -> bool:
    """True, если значение можно править как скаляр в текстовой ячейке."""
    return value is None or isinstance(value, (bool, int, float, str))


def _scalar_for_editing(value: Any) -> bool:
    """Алиас для scalar_for_editing (внутри build_recipe_rows)."""
    return scalar_for_editing(value)


def _register_field_editable(rm: Any, reg: Any, register_name: str, field_name: str, ctx: AccessContext) -> bool:
    """Доступность поля по FieldMeta регистра или метаданным rm."""
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
    """Строка для отображения в QTable (bool/json/scalar)."""
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
    # Обход всех регистров и полей model_dump/dict с фильтром hidden и правами.
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


def build_recipe_rows_from_snapshot(
    rm: Any,
    snapshot: dict,
    access_ctx: Optional[AccessContext] = None,
) -> List[dict]:
    """
    Собрать строки таблицы из snapshot YAML.

    Структура snapshot: {register_name: {field_name: value, ...}, ...}.
    Метаданные (field_meta, info, editable, hidden) берутся из rm — схемы регистров
    не зависят от конкретного слота. Значения — из snapshot.

    Если в snapshot нет регистра/поля — пропускаем (таблица отображает только
    то что есть в slot-снапшоте).
    """
    ctx = access_ctx or AccessContext()
    rows: List[dict] = []
    for register_name, fields in snapshot.items():
        if not isinstance(fields, dict):
            continue
        reg = rm.get_register(register_name) if rm is not None else None
        for field_name, value in fields.items():
            # Hidden filter (если есть meta)
            if reg is not None and hasattr(reg, "get_field_meta"):
                fm = reg.get_field_meta(field_name)
                if fm is not None and fm.hidden and not ctx.show_hidden:
                    continue
            elif rm is not None:
                meta_h = rm.get_field_metadata(register_name, field_name)
                if meta_h.get("hidden") and not ctx.show_hidden:
                    continue
            meta = rm.get_field_metadata(register_name, field_name) if rm is not None else {}
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


def group_rows_by_register(rows: List[dict]) -> List[Tuple[str, List[dict]]]:
    """
    Сгруппировать строки рецепта по register_name для StructuredTwoLevelTreeWidget.

    В листьях колонка param — кратко field_name; field_id и прочие ключи сохраняются.
    """
    order: List[str] = []
    by_reg: dict = defaultdict(list)
    for r in rows:
        reg = str(r.get("register_name") or "")
        if reg not in order:
            order.append(reg)
        rr = dict(r)
        rr["param"] = str(r.get("field_name") or r.get("param") or "")
        by_reg[reg].append(rr)
    for reg in by_reg:
        by_reg[reg].sort(key=lambda x: str(x.get("field_name", "")))
    return [(k, by_reg[k]) for k in order]
