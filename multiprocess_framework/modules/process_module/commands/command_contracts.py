# -*- coding: utf-8 -*-
"""Контракты параметров встроенных команд (Ф4.2 шаг 6, «контактная книжка» v1).

Декларативное наполнение `MessageContractRegistry` для built-in команд: связывает
имя команды с Pydantic-схемой её ПАРАМЕТРОВ. Даёт две вещи:

  - `introspect.capabilities` v1 отдаёт `params_schema` (имена/типы/обязательность
    полей) — агент/оператор видит форму команды без чтения исходников;
  - основа для будущего ужесточения warn-mw (Ф4.2 шаг 1) до валидации payload.

**v1 — документирующие схемы, не строгий барьер.** `extra="allow"` и поля
опциональны: warn-middleware, валидируя ВЕСЬ конверт сообщения (а параметры едут
вложенно в ``data``), НЕ поднимает ложных предупреждений на реальном трафике. Схема
документирует, КАКИЕ параметры принимает команда; строгая валидация вложенного
``data`` — следующий шаг (см. ADR-MSG-008). Регистрируются per-process в
``BuiltinCommands._register_message_guards``; команды, которых в процессе нет, просто
не попадут в его карточку (capabilities итерирует реальные регистрации CommandManager).
"""
from __future__ import annotations

import typing
from typing import Any, Dict, Optional, Type

from pydantic import BaseModel, ConfigDict


class WireConfigureParams(BaseModel):
    """Параметры ``wire.configure`` (runtime-настройка SHM-канала)."""

    model_config = ConfigDict(extra="allow")

    wire_key: Optional[str] = None
    role: Optional[str] = None  # "sender" | "receiver"
    shm_name: Optional[str] = None
    shm_owner: Optional[str] = None
    buffer_slots: Optional[int] = None


class WireDeconfigureParams(BaseModel):
    """Параметры ``wire.deconfigure`` (снять wire-middleware)."""

    model_config = ConfigDict(extra="allow")

    wire_key: Optional[str] = None


class RoutingProbeParams(BaseModel):
    """Параметры ``routing.probe`` (диагностика peer→peer доставки, Ф3.1)."""

    model_config = ConfigDict(extra="allow")

    target: Optional[str] = None
    inner: Optional[Dict[str, Any]] = None


#: Реестр контрактов built-in команд: имя команды → Pydantic-схема параметров.
#: Наполняется в BuiltinCommands._register_message_guards.
BUILTIN_COMMAND_CONTRACTS: Dict[str, Type[BaseModel]] = {
    "wire.configure": WireConfigureParams,
    "wire.deconfigure": WireDeconfigureParams,
    "routing.probe": RoutingProbeParams,
}


def _type_str(ann: Any) -> str:
    """Читаемое имя типа поля; ``Optional[X]`` разворачивается в ``X``."""
    origin = typing.get_origin(ann)
    if origin is typing.Union:
        non_none = [a for a in typing.get_args(ann) if a is not type(None)]
        if len(non_none) == 1:
            return _type_str(non_none[0])
        return " | ".join(_type_str(a) for a in non_none)
    return getattr(ann, "__name__", None) or str(ann).replace("typing.", "")


def params_schema_of(schema: Type[BaseModel]) -> list[dict[str, Any]]:
    """Детерминированная форма схемы для карточки: [{name, type, required}] по имени.

    Только контракт (имена/типы/обязательность), без runtime-значений — как
    ``registers`` в capability-манифесте. Тип рендерится читаемой строкой.
    """
    out: list[dict[str, Any]] = []
    for name, info in schema.model_fields.items():
        out.append(
            {"name": name, "type": _type_str(info.annotation), "required": bool(info.is_required())}
        )
    return sorted(out, key=lambda f: f["name"])


__all__ = [
    "WireConfigureParams",
    "WireDeconfigureParams",
    "RoutingProbeParams",
    "BUILTIN_COMMAND_CONTRACTS",
    "params_schema_of",
]
