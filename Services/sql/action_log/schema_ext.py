"""
ActionLogRow -- SQL-friendly проекция Action для хранения в таблице action_log.

Проблема: Action.forward_patch / backward_patch имеют тип Dict[str, Any],
что нельзя хранить как отдельные SQL-колонки.
Решение: сериализация патчей в JSON-строки (forward_patch_json, backward_patch_json).

Конвертеры to_action_log_row / from_action_log_row обеспечивают round-trip:
    Action -> ActionLogRow -> Action (идентичный).
"""

from __future__ import annotations

import json

from multiprocess_framework.modules.data_schema_module import SchemaBase

from multiprocess_framework.modules.frontend_module.actions.schemas import Action


class ActionLogRow(SchemaBase):
    """
    SQL-friendly строка таблицы action_log.

    Все поля -- примитивные типы (str, float, bool),
    что гарантирует прямой маппинг через SchemaBaseMapper.
    """

    class SQLMeta:
        table_name = "action_log"
        primary_key = ["action_id"]
        indexes = [("timestamp",), ("action_type",)]

    action_id: str
    action_type: str
    register_name: str | None = None
    field_name: str | None = None
    forward_patch_json: str = "{}"
    backward_patch_json: str = "{}"
    coalesce_key: str | None = None
    undoable: bool = True
    description: str = ""
    timestamp: float = 0.0


def to_action_log_row(action: Action) -> ActionLogRow:
    """Конвертировать Action в ActionLogRow для записи в БД.

    forward_patch и backward_patch сериализуются в JSON-строки.
    default=str обрабатывает numpy-типы и прочие не-JSON объекты.

    action_type -- уже str в фреймворке; если приложение передаёт enum,
    .value берётся автоматически (str(Enum) == Enum.value для str-enum).
    """
    at = action.action_type
    # Поддержка str-enum из приложения: если enum -- берём .value
    if hasattr(at, "value"):
        at = at.value
    return ActionLogRow(
        action_id=action.action_id,
        action_type=at,
        register_name=action.register_name,
        field_name=action.field_name,
        forward_patch_json=json.dumps(action.forward_patch, default=str, ensure_ascii=False),
        backward_patch_json=json.dumps(action.backward_patch, default=str, ensure_ascii=False),
        coalesce_key=action.coalesce_key,
        undoable=action.undoable,
        description=action.description,
        timestamp=action.timestamp,
    )


def from_action_log_row(row: ActionLogRow) -> Action:
    """Конвертировать ActionLogRow обратно в Action.

    JSON-строки десериализуются в Dict[str, Any].
    action_type остаётся str -- приложение может обернуть в свой enum при необходимости.
    """
    return Action(
        action_id=row.action_id,
        action_type=row.action_type,
        register_name=row.register_name,
        field_name=row.field_name,
        forward_patch=json.loads(row.forward_patch_json),
        backward_patch=json.loads(row.backward_patch_json),
        coalesce_key=row.coalesce_key,
        undoable=row.undoable,
        description=row.description,
        timestamp=row.timestamp,
    )
