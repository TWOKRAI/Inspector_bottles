# -*- coding: utf-8 -*-
"""capability_render.py — форматы «контактной книжки»: concise / help (B.4).

Холодный старт агента за один вызов без взрыва контекста (закрывает DEFER
Task 3.3). Чистый РЕНДЕР над результатом :meth:`BackendDriver.capabilities`
(реестр контрактов процессов) — ноль дублирования данных, ноль новых IPC:

  * ``concise`` — имена команд БЕЗ params_schema/описаний: «что вообще есть»
    кратно дешевле полной карточки;
  * ``help`` — карточка команды: 1 пример вызова (генерится из params_schema) +
    подписочная подсказка «какое push-событие придёт и в какой плоскости B.1» +
    корреляционные ключи событий (:data:`CORRELATION_KEYS`; trace_id — после
    Ф7 G.6, план D.3);
  * ``detailed`` — прежний полный дамп (рендер не здесь — dataclass как есть).

Фильтр ``process`` сужает оба формата до одной карточки.

Аналог: ``kubectl explain``, CDP domain docs.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .protocol import Capabilities

#: Допустимые значения format у MCP-инструмента capabilities.
FORMATS: tuple[str, ...] = ("detailed", "concise", "help")

#: Корреляционные ключи push-событий (сопоставить «команда → её эффект в потоке»).
#: После Ф7 G.6 (план D.3) сюда добавится trace_id.
CORRELATION_KEYS: tuple[str, ...] = ("process", "worker", "ts")

# Подписочная подсказка: subscribe-команда → какой push приедет и в какую
# плоскость B.1 (см. events.py). Статичная карта wire-контрактов, не эвристика.
_SUBSCRIPTION_EVENTS: Dict[str, Dict[str, str]] = {
    "state.subscribe": {
        "push_command": "state.changed",
        "plane": "state (+ telemetry per-delta)",
    },
    "log.tail.subscribe": {"push_command": "log.record", "plane": "logs"},
    "observability.tail.subscribe": {
        "push_command": "observability.record",
        "plane": "logs|errors|stats (по kind записи)",
    },
    "ui.tap.subscribe": {"push_command": "ui.event", "plane": "ui"},
}

# Тип поля params_schema → placeholder примера вызова.
_TYPE_PLACEHOLDERS: Dict[str, Any] = {
    "str": "<str>",
    "int": 0,
    "float": 0.0,
    "bool": False,
    "dict": {},
    "list": [],
}


def _placeholder(type_name: Any) -> Any:
    return _TYPE_PLACEHOLDERS.get(str(type_name).lower(), "<value>")


def _selected(caps: Capabilities, process: Optional[str]) -> Any:
    """Карточки к рендеру: все или одна; неизвестный процесс — обучающая ошибка."""
    if process is None:
        return caps.processes
    if process not in caps.processes:
        return {
            "success": False,
            "error": f"процесс {process!r} не найден в капабилити-своде",
            "known_processes": sorted(caps.processes),
        }
    return {process: caps.processes[process]}


def render_concise(caps: Capabilities, process: Optional[str] = None) -> Dict[str, Any]:
    """Имена команд/регистров/handlers без схем и описаний — кратно меньше detailed."""
    cards = _selected(caps, process)
    if isinstance(cards, dict) and cards.get("success") is False:
        return cards
    return {
        "success": True,
        "format": "concise",
        "ok": caps.ok,
        "topology": sorted(caps.topology),
        "processes": {
            name: {
                "ok": card.ok,
                "commands": sorted(str(c.get("name") or "") for c in card.commands),
                "registers": {reg: list(fields) for reg, fields in sorted(card.registers.items())},
                "router_handlers": sorted(card.router_handlers),
            }
            for name, card in cards.items()
        },
    }


def render_help(caps: Capabilities, process: Optional[str] = None) -> Dict[str, Any]:
    """Карточки команд: пример вызова из схемы + подписочная подсказка."""
    cards = _selected(caps, process)
    if isinstance(cards, dict) and cards.get("success") is False:
        return cards
    processes: Dict[str, Any] = {}
    for name, card in cards.items():
        commands: List[Dict[str, Any]] = []
        for cmd in card.commands:
            cmd_name = str(cmd.get("name") or "")
            entry: Dict[str, Any] = {
                "name": cmd_name,
                "description": str(cmd.get("description") or ""),
                "example": _example_call(name, cmd_name, cmd.get("params_schema")),
            }
            subscription = _SUBSCRIPTION_EVENTS.get(cmd_name)
            if subscription is not None:
                entry["subscription"] = {
                    **subscription,
                    "read_with": "events_page(plane=...) / await_condition(event_matches)",
                }
            commands.append(entry)
        processes[name] = {"ok": card.ok, "commands": commands, "registers": dict(card.registers)}
    return {
        "success": True,
        "format": "help",
        "ok": caps.ok,
        "correlation_keys": list(CORRELATION_KEYS),
        "processes": processes,
    }


def _example_call(process: str, command: str, params_schema: Any) -> Dict[str, Any]:
    """1 пример вызова команды, сгенерированный из params_schema (v1: name/type/required).

    Обязательные поля — placeholder по типу; опциональные не включаются (пример
    минимален). Команда без схемы — пример без args.
    """
    args: Dict[str, Any] = {}
    if isinstance(params_schema, list):
        for field in params_schema:
            if isinstance(field, dict) and field.get("required"):
                args[str(field.get("name") or "")] = _placeholder(field.get("type"))
    arguments: Dict[str, Any] = {"target": process, "command": command}
    if args:
        arguments["args"] = args
    return {"tool": "send_command", "arguments": arguments}


__all__ = ["render_concise", "render_help", "FORMATS", "CORRELATION_KEYS"]
