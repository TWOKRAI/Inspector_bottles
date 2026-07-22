# -*- coding: utf-8 -*-
"""Реестр MCP-инструментов backend_ctl (Ф1 Task 1.7, P3).

Каждый инструмент — тонкая проекция метода :class:`~backend_ctl.driver.BackendDriver`
в MCP-форму (имя + JSON Schema аргументов + handler). Никакой бизнес-логики: реестр
только транслирует arguments → вызов driver → JSON-сериализуемый результат. Все
команды исполняются процессами системы, ответы едут чистым RouterManager (граница
Claude↔driver — см. решение владельца в plans/_archive/2026-05-31_backend-control-mcp).

Имена инструментов зеркалят методы driver (обещание AGENTS.md): `get_status`,
`introspect_handlers`, `send_command`, `set_register`, `capabilities`, …
Транспортный слой (stdio JSON-RPC, MCP SDK) — в :mod:`backend_ctl.mcp_server_sdk`
(рукописный `mcp_server.py` удалён в F.1, BCTL-ADR-001).
"""

from __future__ import annotations

import dataclasses
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Callable, Dict, List, Optional

from backend_ctl.capability_render import FORMATS, render_concise, render_help
from backend_ctl.conditions import DEFAULT_AWAIT_TIMEOUT
from backend_ctl.driver import BackendDriver
from backend_ctl.events import ALL_PLANE, PLANES, page_with_reset_retry
from backend_ctl.recorder import DEFAULT_MAX_EVENTS

#: Handler инструмента: (driver, arguments) → JSON-сериализуемый результат.
ToolHandler = Callable[[BackendDriver, Dict[str, Any]], Any]

#: Потолок блокировки events(timeout) — MCP-вызов не должен подвешивать сервер.
MAX_EVENTS_TIMEOUT = 30.0

# E.3: защита контекста агента от гигантских ответов тяжёлых read-инструментов.
#: Дефолтный лимит точек telemetry_history, если не задан явно (спарклайн, не дамп БД).
DEFAULT_HISTORY_LIMIT = 100
#: Потолок сериализации тяжёлого ответа (байт). Свыше — усечение до карты формы,
#: полный объём — по явному ``full=true``.
RESPONSE_BYTE_CAP = 12000
#: Инструменты, к ответам которых byte-cap НЕ применяется. Политика инвертирована
#: (Task 3.2): раньше это был белый список тяжёлых, и любой НОВЫЙ инструмент по
#: умолчанию отдавал неограниченный объём — fail-open, о котором никто не вспоминал,
#: пока контекст агента не заливало. Теперь урезается всё, кроме перечисленного здесь.
#:
#: Исключения — не «маленькие», а те, для кого усечение ЛОМАЕТ контракт:
#:   * ``events``/``events_page`` — курсор уже продвинулся, усечённые события потеряны
#:     безвозвратно, а у events_page в ответе ещё и next_cursor (позиция читателя);
#:   * ``register_snapshot`` — снимок целиком является входом для register_restore.
#: Их объём ограничивается своими средствами (limit/max_items), а не байтовым потолком.
_UNCAPPED_TOOLS: frozenset = frozenset({"events", "events_page", "register_snapshot"})


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
# E.3: снять дефолтное усечение тяжёлого ответа и вернуть полный объём.
_FULL = {"type": "boolean", "description": "Вернуть полный объём без усечения по размеру (E.3). По умолчанию false."}


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
    fmt = args.get("format") or "detailed"
    if fmt not in FORMATS:
        return {"success": False, "error": f"неизвестный format {fmt!r}: ожидаю один из {list(FORMATS)}"}
    caps = drv.capabilities(**_kw_timeout(args))
    process = args.get("process")
    if fmt == "concise":
        return render_concise(caps, process)
    if fmt == "help":
        return render_help(caps, process)
    if process is not None:  # detailed + фильтр: сузить карточки до одного процесса
        if process not in caps.processes:
            return {
                "success": False,
                "error": f"процесс {process!r} не найден в капабилити-своде",
                "known_processes": sorted(caps.processes),
            }
        caps = dataclasses.replace(caps, processes={process: caps.processes[process]})
    # Явный success и в detailed: у concise/help/ошибок он есть, асимметрия формата
    # заставляла бы вызывающего угадывать, по какому ключу проверять успех.
    return {"success": True, **_jsonable(caps)}


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


def _supervision_status(drv: BackendDriver, args: Dict[str, Any]) -> Any:
    return _jsonable(drv.supervision_status(args.get("process"), **_kw_timeout(args)))


def _send_command(drv: BackendDriver, args: Dict[str, Any]) -> Any:
    return drv.send_command(args["target"], args["command"], args.get("args"), **_kw_timeout(args))


def _system_command(drv: BackendDriver, args: Dict[str, Any]) -> Any:
    return drv.system_command(args["command"], **_kw_timeout(args))


def _set_register(drv: BackendDriver, args: Dict[str, Any]) -> Any:
    kw = _kw_timeout(args)
    if args.get("confirm_within") is not None:
        kw["confirm_within"] = float(args["confirm_within"])
    return drv.set_register(args["process"], args["register"], args["field"], args.get("value"), **kw)


def _set_register_verified(drv: BackendDriver, args: Dict[str, Any]) -> Any:
    return drv.set_register_verified(
        args["process"], args["register"], args["field"], args.get("value"), **_kw_timeout(args)
    )


def _register_snapshot(drv: BackendDriver, args: Dict[str, Any]) -> Any:
    return drv.register_snapshot(args.get("process"), **_kw_timeout(args))


def _register_restore(drv: BackendDriver, args: Dict[str, Any]) -> Any:
    return drv.register_restore(args["snapshot"], **_kw_timeout(args))


def _register_confirm(drv: BackendDriver, args: Dict[str, Any]) -> Any:
    return drv.register_confirm(args["commit_id"])


def _register_rollback_log(drv: BackendDriver, args: Dict[str, Any]) -> Any:
    limit = args.get("limit")
    return drv.register_rollback_log(limit=int(limit) if limit is not None else None)


def _state_get(drv: BackendDriver, args: Dict[str, Any]) -> Any:
    return drv.send_command("ProcessManager", "state.get", {"path": args["path"]}, **_kw_timeout(args))


def _state_get_subtree(drv: BackendDriver, args: Dict[str, Any]) -> Any:
    return drv.send_command("ProcessManager", "state.get_subtree", {"path": args.get("path", "")}, **_kw_timeout(args))


def _state_subscribe(drv: BackendDriver, args: Dict[str, Any]) -> Any:
    return drv.state_subscribe(args["pattern"], **_kw_timeout(args))


def _events(drv: BackendDriver, args: Dict[str, Any]) -> Any:
    """Легаси-совместимый инструмент ``events`` — F.1: переписан поверх events_page.

    driver.events() (деструктивный дренаж всего hub'а) удалён — сохраняем ИМЯ и
    привычное поведение («новое с прошлого вызова», timeout>0 недолго ждёт первое
    событие) поверх курсорного :meth:`~backend_ctl.driver.BackendDriver.events_page`.
    Курсор — приватный атрибут ЭТОГО инструмента на driver'е (``_events_tool_cursor``):
    не конкурирует с курсорами других читателей events_page (в т.ч. другого MCP-клиента
    этой же сессии) — теми самыми конкурирующими читателями, ради которых events()
    депрекировали в B.1.
    """
    timeout = min(float(args.get("timeout", 0.0) or 0.0), MAX_EVENTS_TIMEOUT)
    max_items = args.get("max_items")
    limit = int(max_items) if max_items is not None else None
    deadline = time.monotonic() + timeout if timeout > 0 else None
    while True:
        # Триплет «прочитал курсор → взял страницу → записал курсор» атомарен (Task 2.3).
        # Лок держится ТОЛЬКО на итерации, не на всём ожидании: иначе вызов с timeout
        # блокировал бы соседние чтения на все MAX_EVENTS_TIMEOUT секунд.
        with drv._tool_cursor_lock:  # noqa: SLF001 — приватное состояние курсоров этого driver'а
            cursor = getattr(drv, "_events_tool_cursor", None)
            page = page_with_reset_retry(
                lambda c: drv.events_page(cursor=c, limit=limit),
                cursor,
            )
            drv._events_tool_cursor = page.get("next_cursor", cursor)  # noqa: SLF001
        items = [it["event"] for it in page.get("items", [])]
        if items or deadline is None or time.monotonic() >= deadline:
            return items
        time.sleep(0.05)


def _events_page(drv: BackendDriver, args: Dict[str, Any]) -> Any:
    return drv.events_page(args.get("plane"), cursor=args.get("cursor"), limit=args.get("limit"))


def _await_condition(drv: BackendDriver, args: Dict[str, Any]) -> Any:
    # Жёсткий cap таймаута: блокирующий tools/call не должен подвешивать сервер.
    # timeout=0 — валидное «проверь сейчас, не жди» (не путать с «не передан»).
    raw = args.get("timeout")
    timeout = DEFAULT_AWAIT_TIMEOUT if raw is None else float(raw)
    return drv.await_condition(args["kind"], args.get("spec"), timeout=min(timeout, MAX_EVENTS_TIMEOUT))


def _system_overview(drv: BackendDriver, args: Dict[str, Any]) -> Any:
    return drv.system_overview(**_kw_timeout(args))


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


def _record_tool_stub(drv: BackendDriver, args: Dict[str, Any]) -> Any:
    """Заглушка handler'а record_* для реестра: эти инструменты session-owned (D.4).

    Диспетчеризуются через :func:`dispatch_tool` (session), а не через
    call_tool(driver, …) — им нужны запись/реплей уровня сессии, а не сам driver.
    """
    raise RuntimeError(
        "record_* — session-owned инструменты: вызывай через dispatch_tool(session, …), не через call_tool(driver, …)"
    )


def _telemetry_snapshot(drv: BackendDriver, args: Dict[str, Any]) -> Any:
    # Локальное чтение read-model (0 IPC) — timeout не нужен.
    return drv.telemetry_snapshot(args.get("process"), args.get("metric"))


def _telemetry_history(drv: BackendDriver, args: Dict[str, Any]) -> Any:
    # E.3: дефолтный лимит точек — не выливать всё кольцо истории в контекст.
    # Явный limit (в т.ч. больший) переопределяет; full=true снимает потолок.
    limit = args.get("limit")
    if limit is None and not args.get("full"):
        limit = DEFAULT_HISTORY_LIMIT
    return drv.telemetry_history(args["path"], limit=limit)


# ---------------------------------------------------------------------------
# Реестр
# ---------------------------------------------------------------------------

TOOLS: List[ToolSpec] = [
    ToolSpec(
        "capabilities",
        "«Контактная книжка» всей системы: топология процессов, их команды с описаниями, "
        "регистры (поля), router-handlers, каналы. Первый вызов сессии — вместо чтения исходников. "
        "format='concise' — только имена (кратно дешевле контексту); 'help' — карточка команды с "
        "примером вызова, подписочной подсказкой (какое push-событие в какую плоскость B.1) и "
        "корреляционными ключами; 'detailed' (дефолт) — полный дамп. process — фильтр до одной карточки.",
        _obj(
            {
                "format": {
                    "type": "string",
                    "enum": ["detailed", "concise", "help"],
                    "description": "Формат ответа (по умолчанию detailed).",
                },
                "process": {"type": "string", "description": "Сузить свод до одного процесса. Опц."},
                "timeout": _TIMEOUT,
            }
        ),
        _capabilities,
    ),
    ToolSpec(
        "system_overview",
        "«Один вызов = вся картина» (B.3): компактная сводка по всем процессам топологии "
        "(статус/воркеры/router-счётчики/очереди/память) + telemetry fps + счётчики driver'а "
        "+ секция anomalies (подсказки: router_dropped, queue_depth, fps_zero_while_running, "
        "recent_recovery, late_replies, events_evicted, …). Первая команда сессии после "
        "capabilities: вердикты, не археология. Только существующие introspect-ручки (read-only). "
        "Крупный ответ усекается до карты формы — full=true для полного объёма (E.3).",
        _obj({"timeout": _TIMEOUT, "full": _FULL}),
        _system_overview,
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
        "supervision_status",
        "Supervision-снимок (D.1b): epoch топологии + per-process incarnation, restart_count, "
        "last_exit, status. Смена incarnation процесса = пересечён его рестарт (маркер «до/после» "
        "для fencing и курсоров B.1). process — сузить до одного. Read-only.",
        _obj(
            {
                "process": {"type": "string", "description": "Сузить до одного процесса. Опц."},
                "timeout": _TIMEOUT,
            }
        ),
        _supervision_status,
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
        "Записать значение поля регистра в живой процесс (live field-write, register_update). "
        "confirm_within=N (D.5) — режим commit-confirmed: запись авто-откатится через N сек, "
        "если не подтвердить её register_confirm(commit_id из ответа). Аналог Juniper `commit confirmed`.",
        _obj(
            {
                "process": _PROCESS,
                "register": {"type": "string", "description": "Имя регистра (обычно = plugin_name владельца)"},
                "field": {"type": "string", "description": "Имя поля регистра"},
                "value": {"description": "Новое значение (любой JSON-тип)"},
                "confirm_within": {
                    "type": "number",
                    "description": "Сек до авто-отката, если нет register_confirm (commit-confirmed, D.5). "
                    "Опущено — обычная запись без предохранителя.",
                },
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
        "register_snapshot",
        "Снять снимок регистров для гарантированного отката эксперимента (D.5). "
        "process задан — один процесс; опущен — все процессы системы. Форма ответа: "
        "{processes: {proc: {register: {field: value}}}} — передать в register_restore.",
        _obj(
            {
                "process": {**_PROCESS, "description": _PROCESS["description"] + "; опущено — все процессы"},
                "timeout": _TIMEOUT,
            }
        ),
        _register_snapshot,
    ),
    ToolSpec(
        "register_restore",
        "Восстановить регистры из снимка register_snapshot (D.5): пишет каждое поле обратно "
        "и сверяет readback'ом. Ответ: success, written/verified, mismatches[].",
        _obj(
            {
                "snapshot": {
                    "type": "object",
                    "description": "Снимок из register_snapshot (ключ 'processes')",
                    "additionalProperties": True,
                },
                "timeout": _TIMEOUT,
            },
            ["snapshot"],
        ),
        _register_restore,
    ),
    ToolSpec(
        "register_confirm",
        "Подтвердить commit-confirmed запись (D.5): снять таймер авто-отката по commit_id из "
        "ответа set_register(confirm_within=…). Без подтверждения запись откатится автоматически.",
        _obj(
            {
                "commit_id": {"type": "string", "description": "commit_id из ответа set_register(confirm_within=…)"},
            },
            ["commit_id"],
        ),
        _register_confirm,
    ),
    ToolSpec(
        "register_rollback_log",
        "Журнал исходов авто-откатов commit-confirmed этой сессии (D.5): для каждого "
        "сработавшего таймера — outcome ok/failed(+error)/noop. Так агент узнаёт, чем "
        "закончился откат, даже если не вызывал register_confirm. Кольцо на 64 записи.",
        _obj(
            {
                "limit": {"type": "integer", "description": "Вернуть последние N записей (по умолчанию все, до 64)"},
            }
        ),
        _register_rollback_log,
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
        "Прочитать поддерево state-дерева по пути ('' = корень целиком — снимок состояния системы). "
        "Крупное поддерево усекается до карты ключей — сузь path или full=true для полного объёма (E.3).",
        _obj(
            {
                "path": {"type": "string", "description": "Путь поддерева ('' = корень)"},
                "timeout": _TIMEOUT,
                "full": _FULL,
            }
        ),
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
        "Простой дренаж 'новое с прошлого вызова' по ВСЕМ плоскостям (F.1: реализован поверх "
        "events_page курсором ЭТОГО инструмента — не крадёт события у events_page/у другого клиента). "
        "Для нескольких независимых читателей или чтения по одной плоскости — events_page. "
        "Забирает накопленные push-события (state.changed, log.record, …) из событийного канала driver. "
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
        "events_page",
        "Курсорное НЕдеструктивное чтение push-событий по плоскостям (B.1): state (state.changed) / "
        "logs (log.record + observability kind=log) / errors / stats / telemetry (per-delta зеркало "
        "state.changed) / ui (ui.event) / other (вне классификации) / all (всё в порядке прихода). "
        "Несколько читателей не мешают друг другу. Ответ: items [{seq, event}], next_cursor (передай "
        "в следующий вызов), dropped (сколько событий вытеснено из кольца между курсором и первым "
        "возвращённым — видимая потеря), bookmark (курсор «хвост сейчас» — начать только с нового). "
        "reset_required=true — курсор прежнего соединения: начни заново с cursor=null.",
        _obj(
            {
                "plane": {
                    "type": "string",
                    "enum": [ALL_PLANE, *PLANES],
                    "description": "Плоскость событий (по умолчанию all — оригиналы в порядке прихода).",
                },
                "cursor": {
                    "type": "string",
                    "description": "next_cursor/bookmark прошлого ответа — ТОЛЬКО полная форма "
                    "'plane:seq@gen'; пусто = с самого старого доступного. Любая ошибка курсора → "
                    "reset_required=true + bookmark.",
                },
                "limit": {"type": "integer", "description": "Максимум событий в странице (дефолт 100, потолок 500)."},
            }
        ),
        _events_page,
    ),
    ToolSpec(
        "await_condition",
        "Серверное ожидание условия одним вызовом вместо поллинга (B.2): kind='state_path' "
        "(spec={path, value} — точное значение пути в локальном read-model), 'event_matches' "
        "(spec={plane, pattern} — glob по command/path события плоскости B.1), 'metric_threshold' "
        "(spec={path, op: >|>=|<|<=|==|!=, value} — метрика пересекла порог). Блокирует до timeout "
        "(сек, максимум 30). Таймаут возвращает диагноз (waited/last_seen/events_seen), не пустоту. "
        "Требует активной подписки (watch_like_gui/state_subscribe) — иначе дельты не приходят.",
        _obj(
            {
                "kind": {
                    "type": "string",
                    "enum": ["state_path", "event_matches", "metric_threshold"],
                    "description": "Вид условия.",
                },
                "spec": {
                    "type": "object",
                    "description": "Параметры условия (по kind, см. описание инструмента).",
                    "additionalProperties": True,
                },
                "timeout": {"type": "number", "description": "Максимум ожидания, сек (по умолчанию 10, cap 30)."},
            },
            ["kind", "spec"],
        ),
        _await_condition,
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
                    "description": "Вернуть последние N точек (опц., по умолчанию 100 — E.3; больший переопределяет).",
                },
                "full": _FULL,
            },
            ["path"],
        ),
        _telemetry_history,
    ),
    # ---- Flight recorder (D.4): все SAFETY_READ, session-owned (dispatch_tool) ----
    ToolSpec(
        "record_start",
        "Начать ЗАПИСЬ потока событий driver'а в файл (flight recorder, D.4). Пишет снимок "
        "состояния + JSONL-ленту событий; позже record_load грузит запись в тот же read-model "
        "БЕЗ живой системы. name — имя записи (не путь; резолвится в BACKEND_CTL_RECORD_DIR). "
        "Пиши только то, на что подписан (watch_like_gui/state_subscribe) — без подписок лента пуста "
        "(вернётся hint). max_events — лимит (по достижении авто-стоп, файл валиден). read-only: "
        "запись — локальный наблюдатель, бэкенд не мутируется. ПРЕДУПРЕЖДЕНИЕ: запись содержит "
        "состояние системы (пути/конфиги) — не прикладывай к публичным issue.",
        _obj(
            {
                "name": {"type": "string", "description": "Имя записи (без разделителей/'..'); .jsonl добавится."},
                "max_events": {
                    "type": "integer",
                    "description": f"Лимит событий (по умолчанию {DEFAULT_MAX_EVENTS}); при достижении авто-стоп.",
                },
            },
            ["name"],
        ),
        _record_tool_stub,
    ),
    ToolSpec(
        "record_stop",
        "Остановить активную запись (footer reason=stopped, файл финализируется fsync'ом). "
        "read-only. Нет активной записи → обучающий отказ.",
        _obj({}),
        _record_tool_stub,
    ),
    ToolSpec(
        "record_status",
        "Статус flight recorder'а: активная запись (файл/счётчики events_written/dropped) ЛИБО "
        "загруженный реплей (имя/позиция playhead/total/обрыв). read-only.",
        _obj({}),
        _record_tool_stub,
    ),
    ToolSpec(
        "record_load",
        "Загрузить запись в OFFLINE-реплей: тот же read-model наполняется записью БЕЗ живой системы "
        "(detached driver). После load сессия в replay-режиме — telemetry_snapshot/telemetry_history/"
        "events_page/await_condition/state_get/system_overview отвечают ПО ЗАПИСИ; прочие (write/IPC) "
        "требуют record_unload. position='end' (дефолт) — сразу финальное состояние; 'start' — только "
        "снимок, playhead двигается await_condition'ами (тайм-трэвел). name — имя записи в "
        "BACKEND_CTL_RECORD_DIR. read-only.",
        _obj(
            {
                "name": {"type": "string", "description": "Имя записи в BACKEND_CTL_RECORD_DIR (без разделителей)."},
                "position": {
                    "type": "string",
                    "enum": ["end", "start"],
                    "description": "'end' (дефолт): вся лента сразу; 'start': только снимок, прокрутка await'ами.",
                },
                "ring_maxlen": {
                    "type": "integer",
                    "description": "Потолок колец событий реплея (опц.; по умолчанию min(события, 10000)).",
                },
            },
            ["name"],
        ),
        _record_tool_stub,
    ),
    ToolSpec(
        "record_unload",
        "Выгрузить реплей, вернуть сессию в LIVE-режим (следующий вызов переподключится к бэкенду). "
        "read-only. Нет загруженного реплея → обучающий отказ.",
        _obj({}),
        _record_tool_stub,
    ),
    ToolSpec(
        "record_dump",
        "One-shot ДАМП чёрного ящика: снимок состояния + текущее содержимое arrival-кольца событий "
        "в файл (footer reason=dump). Покрывает 'система умирает — сохрани, что driver успел увидеть'. "
        "name — имя в BACKEND_CTL_RECORD_DIR. read-only. Грузится тем же record_load.",
        _obj(
            {"name": {"type": "string", "description": "Имя дампа в BACKEND_CTL_RECORD_DIR (без разделителей)."}},
            ["name"],
        ),
        _record_tool_stub,
    ),
    ToolSpec(
        "session_log",
        "Аудит-журнал мутаций ЭТОЙ сессии (E.1): каждый write/escalated-вызов "
        "(set_register/send_command/…) с аргументами, временем и исходом (ok/error). "
        "Доверие к автономной сессии и вход для откатов. read-only; read/subscribe в журнал не шумят. "
        "limit — сколько последних записей (по умолчанию все в кольце).",
        _obj(
            {"limit": {"type": "integer", "description": "Сколько последних записей вернуть. Опц."}},
            [],
        ),
        _record_tool_stub,
    ),
]


# ---------------------------------------------------------------------------
# Классификация безопасности (Task 3.2) + MCP-annotations (Task 3.1)
# ---------------------------------------------------------------------------
#
# Один источник правды: каждому инструменту — класс безопасности. Из класса
# деривятся и MCP tool-annotations (readOnlyHint/destructiveHint/…), и лестница
# safety-режимов сервера. Классы (по возрастанию воздействия на бэкенд):
#   read       — только чтение (introspect/state.get/snapshot/events); бэкенд не меняется.
#   subscribe  — управление подписками/тапами (state.subscribe/*_tail/watch/debug/ui_tap
#                и их снятие); меняет серверную подписку, но не данные бэкенда.
#   write      — меняет поведение бэкенда (регистры/логгер-синки/телеметрия-конфиг).
#   escalated  — произвольная команда (send_command/system_command): «открытый мир».
SAFETY_READ = "read"
SAFETY_SUBSCRIBE = "subscribe"
SAFETY_WRITE = "write"
SAFETY_ESCALATED = "escalated"

TOOL_SAFETY: Dict[str, str] = {
    # read
    "capabilities": SAFETY_READ,
    "get_status": SAFETY_READ,
    "introspect_handlers": SAFETY_READ,
    "introspect_registers": SAFETY_READ,
    "introspect_router_stats": SAFETY_READ,
    "introspect_queues": SAFETY_READ,
    "introspect_plugins": SAFETY_READ,
    "introspect_memory": SAFETY_READ,
    "supervision_status": SAFETY_READ,
    "register_snapshot": SAFETY_READ,
    "register_rollback_log": SAFETY_READ,
    "state_get": SAFETY_READ,
    "state_get_subtree": SAFETY_READ,
    "events": SAFETY_READ,
    "events_page": SAFETY_READ,
    "await_condition": SAFETY_READ,
    "system_overview": SAFETY_READ,
    "telemetry_snapshot": SAFETY_READ,
    "telemetry_history": SAFETY_READ,
    "ui_tap_ping": SAFETY_READ,
    # flight recorder (D.4): бэкенд не мутируется (запись — наблюдатель, реплей — session-локален)
    "record_start": SAFETY_READ,
    "record_stop": SAFETY_READ,
    "record_status": SAFETY_READ,
    "record_load": SAFETY_READ,
    "record_unload": SAFETY_READ,
    "record_dump": SAFETY_READ,
    # audit (E.1): чтение журнала мутаций — сам по себе read-only, не мутирует бэкенд
    "session_log": SAFETY_READ,
    # subscribe
    "state_subscribe": SAFETY_SUBSCRIBE,
    "log_tail": SAFETY_SUBSCRIBE,
    "log_untail": SAFETY_SUBSCRIBE,
    "observability_tail": SAFETY_SUBSCRIBE,
    "observability_untail": SAFETY_SUBSCRIBE,
    "watch_like_gui": SAFETY_SUBSCRIBE,
    "unwatch": SAFETY_SUBSCRIBE,
    "ui_tap": SAFETY_SUBSCRIBE,
    "ui_untap": SAFETY_SUBSCRIBE,
    # write
    "set_register": SAFETY_WRITE,
    "set_register_verified": SAFETY_WRITE,
    "register_restore": SAFETY_WRITE,
    "register_confirm": SAFETY_WRITE,
    "config_reload": SAFETY_WRITE,
    "logger_sink_enable": SAFETY_WRITE,
    "logger_sink_disable": SAFETY_WRITE,
    "telemetry_reconfigure": SAFETY_WRITE,
    "telemetry_set": SAFETY_WRITE,
    # escalated
    "send_command": SAFETY_ESCALATED,
    "system_command": SAFETY_ESCALATED,
}

# Префиксы команд, безопасных для чтения через escalated send_command в read-only
# режиме (Task 3.2): только интроспекция и точечное чтение state.
READ_SAFE_COMMAND_PREFIXES: tuple[str, ...] = ("introspect.", "state.get")

# E.1: классы, чьи вызовы оседают в аудит-журнале сессии (мутации). read/subscribe —
# не шумят (наблюдение бэкенда, не изменение).
_AUDITED_SAFETY: frozenset = frozenset({SAFETY_WRITE, SAFETY_ESCALATED})

# Класс безопасности → MCP tool-annotations (hints для клиента; НЕ enforce — enforce
# делает сервер по классу, Task 3.2). Форма — dict, чтобы mcp_tools не зависел от SDK
# (SDK-адаптер конвертирует в types.ToolAnnotations).
_SAFETY_ANNOTATIONS: Dict[str, Dict[str, bool]] = {
    SAFETY_READ: {"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False},
    SAFETY_SUBSCRIBE: {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False},
    SAFETY_WRITE: {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False},
    SAFETY_ESCALATED: {"readOnlyHint": False, "destructiveHint": True, "openWorldHint": True},
}

# Safety-режимы сервера (Task 3.2).
MODE_FULL = "full"  # всё разрешено (дефолт)
MODE_READ_ONLY = "read-only"  # только read + subscribe (write/escalated блок; send_command — whitelist)
MODE_NO_DESTRUCTIVE = "no-destructive"  # блок инструментов с destructiveHint (write/escalated)

# Классы, разрешённые режимом (кроме особого случая send_command в read-only).
_MODE_ALLOWED_CLASSES: Dict[str, frozenset] = {
    MODE_FULL: frozenset({SAFETY_READ, SAFETY_SUBSCRIBE, SAFETY_WRITE, SAFETY_ESCALATED}),
    MODE_READ_ONLY: frozenset({SAFETY_READ, SAFETY_SUBSCRIBE}),
    MODE_NO_DESTRUCTIVE: frozenset({SAFETY_READ, SAFETY_SUBSCRIBE}),
}


def tool_safety(name: str) -> str:
    """Класс безопасности инструмента (KeyError, если не классифицирован — ловит build_registry)."""
    return TOOL_SAFETY[name]


def tool_annotations(name: str) -> Dict[str, bool]:
    """MCP-annotations инструмента, деривированные из класса безопасности."""
    return dict(_SAFETY_ANNOTATIONS[TOOL_SAFETY[name]])


#: Ограниченные режимы, где ``send_command`` (escalated) допускается УСЛОВНО —
#: только для read-безопасных команд (сервер доуточняет по :func:`is_command_read_safe`).
#: read-only и no-destructive согласованы: оба разрешают ЧТЕНИЕ через send_command.
_RESTRICTED_MODES: frozenset = frozenset({MODE_READ_ONLY, MODE_NO_DESTRUCTIVE})


def is_tool_allowed(name: str, mode: str) -> bool:
    """Разрешён ли инструмент в режиме (без учёта arg-whitelist send_command).

    В ограниченных режимах (read-only / no-destructive) ``send_command`` (escalated)
    допускается УСЛОВНО — проходит name-гейт, а по аргументу ``command`` фильтрует
    сервер (:func:`is_command_read_safe`). Остальные escalated/write — по классам режима.
    """
    allowed = _MODE_ALLOWED_CLASSES.get(mode, _MODE_ALLOWED_CLASSES[MODE_FULL])
    cls = TOOL_SAFETY.get(name)
    if cls is None:
        return False
    if cls in allowed:
        return True
    # Ограниченный режим: send_command проходит name-гейт, а по args фильтрует сервер.
    return name == "send_command" and mode in _RESTRICTED_MODES


def is_command_read_safe(command: str) -> bool:
    """Команда send_command безопасна для чтения (introspect.* / state.get*)?"""
    return bool(command) and command.startswith(READ_SAFE_COMMAND_PREFIXES)


@lru_cache(maxsize=1)
def build_registry() -> Dict[str, ToolSpec]:
    """Реестр name → ToolSpec (имена уникальны + все классифицированы по безопасности).

    ``TOOLS``/``TOOL_SAFETY`` иммутабельны после импорта модуля, поэтому реестр
    собирается один раз и переиспользуется (было — пересборка на каждый вызов,
    т.е. на каждый ``tools/call``).
    """
    registry: Dict[str, ToolSpec] = {}
    for spec in TOOLS:
        if spec.name in registry:
            raise ValueError(f"дубликат имени MCP-инструмента: {spec.name!r}")
        if spec.name not in TOOL_SAFETY:
            raise ValueError(f"инструмент {spec.name!r} не классифицирован в TOOL_SAFETY")
        registry[spec.name] = spec
    return registry


def call_tool(driver: BackendDriver, name: str, arguments: Dict[str, Any]) -> Any:
    """Вызвать инструмент по имени. KeyError — неизвестный инструмент (решает вызывающий)."""
    spec = build_registry()[name]
    return spec.handler(driver, arguments or {})
