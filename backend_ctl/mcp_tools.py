# -*- coding: utf-8 -*-
"""Реестр MCP-инструментов backend_ctl (Ф1 Task 1.7, P3).

Каждый инструмент — тонкая проекция метода :class:`~backend_ctl.driver.BackendDriver`
в MCP-форму (имя + JSON Schema аргументов + handler). Никакой бизнес-логики: реестр
только транслирует arguments → вызов driver → JSON-сериализуемый результат. Все
команды исполняются процессами системы, ответы едут чистым RouterManager (граница
Claude↔driver — см. решение владельца в plans/_archive/2026-05-31_backend-control-mcp).

Имена инструментов зеркалят методы driver (обещание AGENTS.md): `get_status`,
`introspect_handlers`, `send_command`, `set_register`, `capabilities`, …
Транспортный слой (stdio JSON-RPC) — в :mod:`backend_ctl.mcp_server`.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from backend_ctl.driver import BackendDriver

#: Handler инструмента: (driver, arguments) → JSON-сериализуемый результат.
ToolHandler = Callable[[BackendDriver, Dict[str, Any]], Any]

#: Потолок блокировки events(timeout) — MCP-вызов не должен подвешивать сервер.
MAX_EVENTS_TIMEOUT = 30.0


@dataclass(frozen=True)
class ToolSpec:
    """Описание одного MCP-инструмента: имя, описание, схема аргументов, handler."""

    name: str
    description: str
    input_schema: Dict[str, Any]
    handler: ToolHandler

    def to_mcp(self) -> Dict[str, Any]:
        """Форма для ответа tools/list (без handler'а)."""
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
        }


def _obj(
    properties: Dict[str, Any],
    required: Optional[List[str]] = None,
    *,
    additional: bool = False,
) -> Dict[str, Any]:
    """Короткий конструктор JSON Schema type=object."""
    schema: Dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": additional,
    }
    if required:
        schema["required"] = required
    return schema


_PROCESS = {"type": "string", "description": "Имя процесса (например 'preprocessor', 'ProcessManager')"}
_TIMEOUT = {"type": "number", "description": "Таймаут ожидания ответа, сек (по умолчанию таймаут driver)"}


def _kw_timeout(args: Dict[str, Any]) -> Dict[str, Any]:
    """timeout из arguments → kwargs driver-метода (если задан)."""
    return {"timeout": float(args["timeout"])} if args.get("timeout") is not None else {}


def _jsonable(value: Any) -> Any:
    """Dataclass-результаты driver → dict (Dict at Boundary для MCP-ответа)."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return dataclasses.asdict(value)
    return value


# ---------------------------------------------------------------------------
# Handlers — тонкие проекции методов driver (без логики)
# ---------------------------------------------------------------------------


def _capabilities(drv: BackendDriver, args: Dict[str, Any]) -> Any:
    return _jsonable(drv.capabilities(**_kw_timeout(args)))


def _get_status(drv: BackendDriver, args: Dict[str, Any]) -> Any:
    return drv.get_status(args["process"], **_kw_timeout(args))


def _introspect_handlers(drv: BackendDriver, args: Dict[str, Any]) -> Any:
    return drv.introspect_handlers(args["process"], **_kw_timeout(args))


def _introspect_registers(drv: BackendDriver, args: Dict[str, Any]) -> Any:
    return drv.introspect_registers(args["process"], **_kw_timeout(args))


def _introspect_router_stats(drv: BackendDriver, args: Dict[str, Any]) -> Any:
    return drv.introspect_router_stats(args["process"], **_kw_timeout(args))


def _introspect_queues(drv: BackendDriver, args: Dict[str, Any]) -> Any:
    return drv.introspect_queues(args["process"], **_kw_timeout(args))


def _introspect_plugins(drv: BackendDriver, args: Dict[str, Any]) -> Any:
    return drv.introspect_plugins(args["process"], **_kw_timeout(args))


def _introspect_memory(drv: BackendDriver, args: Dict[str, Any]) -> Any:
    return _jsonable(drv.introspect_memory(args["process"], **_kw_timeout(args)))


def _send_command(drv: BackendDriver, args: Dict[str, Any]) -> Any:
    return drv.send_command(args["target"], args["command"], args.get("args"), **_kw_timeout(args))


def _system_command(drv: BackendDriver, args: Dict[str, Any]) -> Any:
    return drv.system_command(args["command"], **_kw_timeout(args))


def _set_register(drv: BackendDriver, args: Dict[str, Any]) -> Any:
    return drv.set_register(args["process"], args["register"], args["field"], args.get("value"), **_kw_timeout(args))


def _set_register_verified(drv: BackendDriver, args: Dict[str, Any]) -> Any:
    return drv.set_register_verified(
        args["process"], args["register"], args["field"], args.get("value"), **_kw_timeout(args)
    )


def _state_get(drv: BackendDriver, args: Dict[str, Any]) -> Any:
    return drv.send_command("ProcessManager", "state.get", {"path": args["path"]}, **_kw_timeout(args))


def _state_get_subtree(drv: BackendDriver, args: Dict[str, Any]) -> Any:
    return drv.send_command("ProcessManager", "state.get_subtree", {"path": args.get("path", "")}, **_kw_timeout(args))


def _state_subscribe(drv: BackendDriver, args: Dict[str, Any]) -> Any:
    return drv.state_subscribe(args["pattern"], **_kw_timeout(args))


def _events(drv: BackendDriver, args: Dict[str, Any]) -> Any:
    timeout = min(float(args.get("timeout", 0.0) or 0.0), MAX_EVENTS_TIMEOUT)
    max_items = args.get("max_items")
    return drv.events(timeout=timeout, max_items=int(max_items) if max_items is not None else None)


def _log_tail(drv: BackendDriver, args: Dict[str, Any]) -> Any:
    return drv.log_tail(args["process"], level=args.get("level", "ERROR"), **_kw_timeout(args))


def _log_untail(drv: BackendDriver, args: Dict[str, Any]) -> Any:
    return drv.log_untail(args["process"], **_kw_timeout(args))


def _observability_tail(drv: BackendDriver, args: Dict[str, Any]) -> Any:
    return drv.observability_tail(args["process"], **_kw_timeout(args))


def _observability_untail(drv: BackendDriver, args: Dict[str, Any]) -> Any:
    return drv.observability_untail(args["process"], **_kw_timeout(args))


def _watch_like_gui(drv: BackendDriver, args: Dict[str, Any]) -> Any:
    kw: Dict[str, Any] = {}
    if args.get("patterns"):
        kw["patterns"] = tuple(args["patterns"])
    if args.get("tail_level"):
        kw["tail_level"] = args["tail_level"]
    return drv.watch_like_gui(**kw, **_kw_timeout(args))


def _unwatch(drv: BackendDriver, args: Dict[str, Any]) -> Any:
    return drv.unwatch(**_kw_timeout(args))


def _ui_tap(drv: BackendDriver, args: Dict[str, Any]) -> Any:
    return drv.ui_tap(args.get("process", "gui"), **_kw_timeout(args))


def _ui_untap(drv: BackendDriver, args: Dict[str, Any]) -> Any:
    return drv.ui_untap(args.get("process", "gui"), **_kw_timeout(args))


def _ui_tap_ping(drv: BackendDriver, args: Dict[str, Any]) -> Any:
    return drv.ui_tap_ping(args.get("process", "gui"), note=args.get("note", "ping"), **_kw_timeout(args))


def _debug_session(drv: BackendDriver, args: Dict[str, Any]) -> Any:
    return drv.debug_session(
        gui_process=args.get("gui_process", "gui"),
        logs_level=args.get("logs_level", "WARNING"),
        log_processes=args.get("log_processes"),
        state_pattern=args.get("state_pattern", "**"),
        **_kw_timeout(args),
    )


def _debug_stop(drv: BackendDriver, args: Dict[str, Any]) -> Any:
    return drv.debug_stop(
        gui_process=args.get("gui_process", "gui"),
        log_processes=args.get("log_processes"),
        **_kw_timeout(args),
    )


def _config_reload(drv: BackendDriver, args: Dict[str, Any]) -> Any:
    return drv.config_reload(
        args["process"],
        observability=args.get("observability"),
        path=args.get("path"),
        **_kw_timeout(args),
    )


def _logger_sink_enable(drv: BackendDriver, args: Dict[str, Any]) -> Any:
    return drv.logger_sink_enable(args["process"], args["sink"], **_kw_timeout(args))


def _logger_sink_disable(drv: BackendDriver, args: Dict[str, Any]) -> Any:
    return drv.logger_sink_disable(args["process"], args["sink"], **_kw_timeout(args))


def _telemetry_reconfigure(drv: BackendDriver, args: Dict[str, Any]) -> Any:
    # publish/throttle пробрасываем ТОЛЬКО если ключ присутствует: явный null у publish —
    # валидная команда «выключить gate», её нельзя путать с «не передано» (_UNSET в driver).
    kw: Dict[str, Any] = {}
    if "publish" in args:
        kw["publish"] = args["publish"]
    if "throttle" in args:
        kw["throttle"] = args["throttle"]
    if args.get("mode"):
        kw["mode"] = args["mode"]
    return drv.telemetry_reconfigure(args.get("process", "all"), **kw, **_kw_timeout(args))


def _telemetry_set(drv: BackendDriver, args: Dict[str, Any]) -> Any:
    kw: Dict[str, Any] = {}
    if "enabled" in args:
        kw["enabled"] = args["enabled"]
    if "interval_sec" in args:
        kw["interval_sec"] = args["interval_sec"]
    if args.get("plane"):
        kw["plane"] = args["plane"]
    return drv.telemetry_set(args["process"], args["metric"], **kw, **_kw_timeout(args))


def _telemetry_snapshot(drv: BackendDriver, args: Dict[str, Any]) -> Any:
    # Локальное чтение read-model (0 IPC) — timeout не нужен.
    return drv.telemetry_snapshot(args.get("process"), args.get("metric"))


def _telemetry_history(drv: BackendDriver, args: Dict[str, Any]) -> Any:
    return drv.telemetry_history(args["path"], limit=args.get("limit"))


# ---------------------------------------------------------------------------
# Реестр
# ---------------------------------------------------------------------------

TOOLS: List[ToolSpec] = [
    ToolSpec(
        "capabilities",
        "«Контактная книжка» всей системы: топология процессов, их команды с описаниями, "
        "регистры (поля), router-handlers, каналы. Первый вызов сессии — вместо чтения исходников.",
        _obj({"timeout": _TIMEOUT}),
        _capabilities,
    ),
    ToolSpec(
        "get_status",
        "Статус процесса и его воркеров (introspect.status).",
        _obj({"process": _PROCESS, "timeout": _TIMEOUT}, ["process"]),
        _get_status,
    ),
    ToolSpec(
        "introspect_handlers",
        "Хендлеры процесса: ключи message_dispatcher + команды CommandManager. "
        "Отвечает на «примет ли процесс команду X».",
        _obj({"process": _PROCESS, "timeout": _TIMEOUT}, ["process"]),
        _introspect_handlers,
    ),
    ToolSpec(
        "introspect_registers",
        "Регистры процесса (имена + поля со значениями). Пусто = нет worker-side приёмника.",
        _obj({"process": _PROCESS, "timeout": _TIMEOUT}, ["process"]),
        _introspect_registers,
    ),
    ToolSpec(
        "introspect_router_stats",
        "Счётчики router'а процесса: sent_ok/received/middleware_dropped/errors — "
        "«дошло/ушло/дропнулось ли сообщение».",
        _obj({"process": _PROCESS, "timeout": _TIMEOUT}, ["process"]),
        _introspect_router_stats,
    ),
    ToolSpec(
        "introspect_queues",
        "Глубины собственных очередей процесса (backpressure-диагностика). "
        "None = qsize недоступен на платформе (macOS) — само по себе диагностично.",
        _obj({"process": _PROCESS, "timeout": _TIMEOUT}, ["process"]),
        _introspect_queues,
    ),
    ToolSpec(
        "introspect_plugins",
        "Каталог плагинов процесса: зарегистрированные (имя → категория) + failed_imports "
        "(модули, упавшие на discover — «куда делся мой плагин»).",
        _obj({"process": _PROCESS, "timeout": _TIMEOUT}, ["process"]),
        _introspect_plugins,
    ),
    ToolSpec(
        "introspect_memory",
        "Инвентарь памяти процесса: SHM / пул займов / очереди — только СТАТИСТИКА "
        "(read-only; кадры/содержимое SHM не отдаёт). Секции memory/pool/queues/shm_registry "
        "best-effort: недоступная подсистема → null (не ошибка). То, чего не видит даже GUI.",
        _obj({"process": _PROCESS, "timeout": _TIMEOUT}, ["process"]),
        _introspect_memory,
    ),
    ToolSpec(
        "send_command",
        "Прямая команда процессу (та же форма, что GUI через CommandSender) + ожидание ответа. "
        "Escape-hatch для команд, у которых нет отдельного инструмента.",
        _obj(
            {
                "target": {"type": "string", "description": "Имя процесса-адресата"},
                "command": {"type": "string", "description": "Имя команды (см. capabilities)"},
                "args": {
                    "type": "object",
                    "description": "Аргументы команды (data)",
                    "additionalProperties": True,
                },
                "timeout": _TIMEOUT,
            },
            ["target", "command"],
        ),
        _send_command,
    ),
    ToolSpec(
        "system_command",
        "System-команда в ProcessManager (форма CommandSender.send_system_command), "
        "например {'command': 'get_all_processes_status'}.",
        _obj(
            {
                "command": {
                    "type": "object",
                    "description": "Dict system-команды (ключ 'command' + параметры)",
                    "additionalProperties": True,
                },
                "timeout": _TIMEOUT,
            },
            ["command"],
        ),
        _system_command,
    ),
    ToolSpec(
        "set_register",
        "Записать значение поля регистра в живой процесс (live field-write, register_update).",
        _obj(
            {
                "process": _PROCESS,
                "register": {"type": "string", "description": "Имя регистра (обычно = plugin_name владельца)"},
                "field": {"type": "string", "description": "Имя поля регистра"},
                "value": {"description": "Новое значение (любой JSON-тип)"},
                "timeout": _TIMEOUT,
            },
            ["process", "register", "field", "value"],
        ),
        _set_register,
    ),
    ToolSpec(
        "set_register_verified",
        "Verify-probe записи регистра (Ф1.6): write → readback introspect.registers → diff. "
        "Возвращает verified/expected/actual — ловит молчаливые no-op'ы (нет регистра/поля).",
        _obj(
            {
                "process": _PROCESS,
                "register": {"type": "string", "description": "Имя регистра (обычно = plugin_name владельца)"},
                "field": {"type": "string", "description": "Имя поля регистра"},
                "value": {"description": "Новое значение (любой JSON-тип)"},
                "timeout": _TIMEOUT,
            },
            ["process", "register", "field", "value"],
        ),
        _set_register_verified,
    ),
    ToolSpec(
        "state_get",
        "Прочитать значение из state-дерева по точному пути (state.get у StateStore в ProcessManager).",
        _obj(
            {
                "path": {"type": "string", "description": "Путь в дереве, например 'processes.gui.status'"},
                "timeout": _TIMEOUT,
            },
            ["path"],
        ),
        _state_get,
    ),
    ToolSpec(
        "state_get_subtree",
        "Прочитать поддерево state-дерева по пути ('' = корень целиком — снимок состояния системы).",
        _obj({"path": {"type": "string", "description": "Путь поддерева ('' = корень)"}, "timeout": _TIMEOUT}),
        _state_get_subtree,
    ),
    ToolSpec(
        "state_subscribe",
        "Подписаться на изменения state-дерева по glob-паттерну (например 'processes.**'). "
        "Пуши state.changed копятся в событийном канале driver — читать инструментом events.",
        _obj(
            {
                "pattern": {"type": "string", "description": "Glob-паттерн путей ('a.b.*', 'a.**')"},
                "timeout": _TIMEOUT,
            },
            ["pattern"],
        ),
        _state_subscribe,
    ),
    ToolSpec(
        "events",
        "Забрать накопленные push-события (state.changed, log.record, …) из событийного канала driver. "
        "timeout>0 — подождать первое событие (сек, максимум 30); 0 — вернуть что есть сразу.",
        _obj(
            {
                "timeout": {"type": "number", "description": "Ожидание первого события, сек (0 = поллинг)"},
                "max_items": {"type": "integer", "description": "Ограничить размер пачки"},
            }
        ),
        _events,
    ),
    ToolSpec(
        "log_tail",
        "Подписаться на LogRecord'ы процесса с level ≥ заданного: записи едут push'ем "
        "в событийный канал (command='log.record') — читать инструментом events.",
        _obj(
            {
                "process": _PROCESS,
                "level": {"type": "string", "description": "Минимальный уровень (по умолчанию ERROR)"},
                "timeout": _TIMEOUT,
            },
            ["process"],
        ),
        _log_tail,
    ),
    ToolSpec(
        "log_untail",
        "Снять подписку на tail логов процесса.",
        _obj({"process": _PROCESS, "timeout": _TIMEOUT}, ["process"]),
        _log_untail,
    ),
    ToolSpec(
        "observability_tail",
        "Подписаться на live-хвост наблюдаемости процесса: ЛОГИ+ОШИБКИ+СТАТИСТИКА "
        "(богаче log_tail — три плоскости). Записи едут push'ем (command='observability.record', "
        "поле kind=log|error|stats) в событийный канал — читать инструментом events. Создаёт подписку.",
        _obj({"process": _PROCESS, "timeout": _TIMEOUT}, ["process"]),
        _observability_tail,
    ),
    ToolSpec(
        "observability_untail",
        "Снять подписку на live-хвост наблюдаемости процесса (форвардер + error-tap'ы).",
        _obj({"process": _PROCESS, "timeout": _TIMEOUT}, ["process"]),
        _observability_untail,
    ),
    ToolSpec(
        "watch_like_gui",
        "Включить ВЕСЬ приёмный профиль GUI одной командой: state.subscribe на GUI-wildcard'ы "
        "(processes.**/system.**/devices.**/calibration.**) + observability.tail на все процессы "
        "+ авто-переподписка хвоста после авто-рестарта процесса. Дальше читать инструментом events. "
        "Создаёт подписки (не read-only). Кадры/SHM вне контракта.",
        _obj(
            {
                "patterns": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "State-wildcard'ы (по умолчанию GUI-набор из 4 паттернов).",
                },
                "tail_level": {
                    "type": "string",
                    "description": "Порог логов. observability.tail форвардит ВСЕ severity; этот порог "
                    "становится КЛИЕНТСКИМ дефолтом severity-фильтра: observability_records(level=None) "
                    "при активном watch режет лог-записи ниже него (stats/errors — независимые плоскости, "
                    "не режутся). По умолчанию WARNING.",
                },
                "timeout": _TIMEOUT,
            }
        ),
        _watch_like_gui,
    ),
    ToolSpec(
        "unwatch",
        "Выключить GUI-профиль watch_like_gui: снять observability-хвосты со всех процессов "
        "и отключить авто-переподписку.",
        _obj({"timeout": _TIMEOUT}),
        _unwatch,
    ),
    ToolSpec(
        "ui_tap",
        "Отладка фронтенда: подписаться на UI-события gui (нажатия кнопок, переключения "
        "табов) — события едут push'ем (command='ui.event') — читать инструментом events.",
        _obj(
            {"process": {"type": "string", "description": "Имя gui-процесса (по умолчанию 'gui')"}, "timeout": _TIMEOUT}
        ),
        _ui_tap,
    ),
    ToolSpec(
        "ui_untap",
        "Снять подписку на UI-события gui.",
        _obj(
            {"process": {"type": "string", "description": "Имя gui-процесса (по умолчанию 'gui')"}, "timeout": _TIMEOUT}
        ),
        _ui_untap,
    ),
    ToolSpec(
        "ui_tap_ping",
        "Синтетическое ui.event по пути доставки тапа — проверить цепочку GUI→driver без клика.",
        _obj(
            {
                "process": {"type": "string", "description": "Имя gui-процесса (по умолчанию 'gui')"},
                "note": {"type": "string", "description": "Метка события (по умолчанию 'ping')"},
                "timeout": _TIMEOUT,
            }
        ),
        _ui_tap_ping,
    ),
    ToolSpec(
        "debug_session",
        "Включить ПОЛНУЮ отладочную плоскость одним вызовом: жесты+команды GUI (ui.event), "
        "логи процессов (log.record, уровень logs_level) и state-дельты (state.changed). "
        "Дальше читать инструментом events — единый поток «клик → команда → лог → state».",
        _obj(
            {
                "gui_process": {"type": "string", "description": "Имя gui-процесса (по умолчанию 'gui')"},
                "logs_level": {"type": "string", "description": "Мин. уровень логов (по умолчанию WARNING)"},
                "log_processes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Процессы для log_tail (по умолчанию все из state-топологии)",
                },
                "state_pattern": {"type": "string", "description": "Glob подписки state (по умолчанию '**')"},
                "timeout": _TIMEOUT,
            }
        ),
        _debug_session,
    ),
    ToolSpec(
        "debug_stop",
        "Выключить отладочную плоскость (ui_untap + log_untail по процессам).",
        _obj(
            {
                "gui_process": {"type": "string", "description": "Имя gui-процесса (по умолчанию 'gui')"},
                "log_processes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Процессы для log_untail (по умолчанию все из state-топологии)",
                },
                "timeout": _TIMEOUT,
            }
        ),
        _debug_stop,
    ),
    ToolSpec(
        "config_reload",
        "Перечитать/применить observability-секцию процесса на лету. "
        "observability={'log_level': 'DEBUG'} — сменить уровень логгера без рестарта.",
        _obj(
            {
                "process": _PROCESS,
                "observability": {
                    "type": "object",
                    "description": "Inline-override секции observability",
                    "additionalProperties": True,
                },
                "path": {"type": "string", "description": "Путь к файлу конфига (вместо inline)"},
                "timeout": _TIMEOUT,
            },
            ["process"],
        ),
        _config_reload,
    ),
    ToolSpec(
        "logger_sink_enable",
        "Включить sink логгера процесса по имени.",
        _obj(
            {"process": _PROCESS, "sink": {"type": "string", "description": "Имя sink'а"}, "timeout": _TIMEOUT},
            ["process", "sink"],
        ),
        _logger_sink_enable,
    ),
    ToolSpec(
        "logger_sink_disable",
        "Выключить sink логгера процесса по имени.",
        _obj(
            {"process": _PROCESS, "sink": {"type": "string", "description": "Имя sink'а"}, "timeout": _TIMEOUT},
            ["process", "sink"],
        ),
        _logger_sink_disable,
    ),
    ToolSpec(
        "telemetry_reconfigure",
        "Рантайм-переконфигурация телеметрии: publisher-gate (что процесс считает/публикует и как "
        "часто) и/или central-троттл оркестратора. process='all' (дефолт) — fan-out на всех детей; "
        "имя процесса — адресно. mode='replace' (дефолт) ПРИМЕНЯЕТ СЕКЦИЮ ЦЕЛИКОМ — ОСТОРОЖНО: сносит "
        "неуказанные метрики/правила (включая дефолтную IPC-страховку). Для точечной правки ОДНОЙ "
        "метрики без сноса соседей используй telemetry_set (он и есть merge). Меняет поведение бэкенда "
        "(разрушающий).",
        _obj(
            {
                "process": {
                    "type": "string",
                    "description": "Имя процесса или 'all'/'*' (fan-out на всех детей). По умолчанию 'all'.",
                },
                "publish": {
                    "type": ["object", "null"],
                    "description": "Publisher-gate config ({'metrics': {...}}). null = выключить gate.",
                    "additionalProperties": True,
                },
                "throttle": {
                    "type": ["object", "null"],
                    "description": "Central store-троттл оркестратора ({glob_path: min_interval_sec}).",
                    "additionalProperties": True,
                },
                "mode": {
                    "type": "string",
                    "enum": ["replace", "merge"],
                    "description": "replace (дефолт, ЦЕЛИКОМ, wipe) | merge (дельта поверх живого состояния).",
                },
                "timeout": _TIMEOUT,
            },
        ),
        _telemetry_reconfigure,
    ),
    ToolSpec(
        "telemetry_set",
        "Точечно поменять ОДНУ метрику/правило телеметрии (merge поверх живого состояния — соседние "
        "override'ы и правила сохраняются). plane='publisher' (дефолт, главный рычаг частоты публикации) "
        "или plane='throttle' (central rate-limit; metric трактуется как glob-путь, требуется interval_sec). "
        "Безопаснее telemetry_reconfigure(mode='replace') для правки одной метрики. Меняет поведение бэкенда.",
        _obj(
            {
                "process": {"type": "string", "description": "Имя процесса или 'all' (fan-out через PM)."},
                "metric": {
                    "type": "string",
                    "description": "Имя метрики (publisher) ИЛИ glob-путь правила (throttle), напр. 'fps'.",
                },
                "enabled": {"type": "boolean", "description": "Включить/выключить публикацию метрики (publisher)."},
                "interval_sec": {
                    "type": ["number", "null"],
                    "description": "Интервал публикации/min-интервал правила, сек (для throttle обязателен).",
                },
                "plane": {
                    "type": "string",
                    "enum": ["publisher", "throttle"],
                    "description": "publisher (дефолт) — частота публикации | throttle — central rate-limit.",
                },
                "timeout": _TIMEOUT,
            },
            ["process", "metric"],
        ),
        _telemetry_set,
    ),
    ToolSpec(
        "telemetry_snapshot",
        "Снимок телеметрии из ЛОКАЛЬНОГО read-model — read-only, 0 IPC (не ходит на сервер). "
        "Наполняется, пока активна state-подписка на 'processes.**' (напр. после watch_like_gui). "
        "process — снимок поддерева процесса; metric — фильтр по суффиксу метрики (например 'fps', "
        "'effective_hz'). Каждая запись несёт корреляционный ключ process/worker. Пустой read-model "
        "(не было дельт) → count=0 (не ошибка).",
        _obj(
            {
                "process": {"type": "string", "description": "Фильтр по процессу (снимок поддерева). Опц."},
                "metric": {
                    "type": "string",
                    "description": "Фильтр по метрике: суффикс '.<metric>' или точное совпадение (напр. 'fps'). Опц.",
                },
            },
        ),
        _telemetry_snapshot,
    ),
    ToolSpec(
        "telemetry_history",
        "Кольцевой буфер истории метрики из ЛОКАЛЬНОГО read-model — read-only, 0 IPC (спарклайн без БД). "
        "История копится только для штатных gated-метрик (fps/latency_ms/uptime/effective_hz/"
        "cycle_duration_ms). Возвращает точки [ts, value] в хронологическом порядке + ключ process/worker. "
        "Путь не трекается / нет данных → count=0. Глубже (час/день) — из БД-стока (вне этого инструмента).",
        _obj(
            {
                "path": {"type": "string", "description": "Полный путь метрики (например 'processes.cam.state.fps')."},
                "limit": {
                    "type": "integer",
                    "description": "Вернуть последние N точек (опц., по умолчанию весь буфер).",
                },
            },
            ["path"],
        ),
        _telemetry_history,
    ),
]


def build_registry() -> Dict[str, ToolSpec]:
    """Реестр name → ToolSpec (имена уникальны — проверяется на импорте)."""
    registry: Dict[str, ToolSpec] = {}
    for spec in TOOLS:
        if spec.name in registry:
            raise ValueError(f"дубликат имени MCP-инструмента: {spec.name!r}")
        registry[spec.name] = spec
    return registry


def call_tool(driver: BackendDriver, name: str, arguments: Dict[str, Any]) -> Any:
    """Вызвать инструмент по имени. KeyError — неизвестный инструмент (решает вызывающий)."""
    spec = build_registry()[name]
    return spec.handler(driver, arguments or {})
