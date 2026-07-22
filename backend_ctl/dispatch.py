# -*- coding: utf-8 -*-
"""dispatch.py — единая диспетчеризация MCP-инструментов: live / replay / record.

Отделяет ГЛАГОЛ («как вызвать инструмент») от декларативного реестра ИМЁН
(:data:`~backend_ctl.mcp_tools.TOOLS` + класс безопасности) в ``mcp_tools.py``.
Владеет: резолвом путей записи (:func:`resolve_record_path` — удержание в
каталоге записей), session-owned record-хендлерами (:data:`RECORD_HANDLERS`),
маршрутизацией поверх offline-реплея (:func:`_serve_replay` / :data:`REPLAY_SERVED`)
и усечением тяжёлых ответов по байтовому потолку (:func:`_cap_heavy`).

Единая точка входа — :func:`dispatch_tool`: ``record_*`` уходит session-owned
хендлеру; в replay-режиме обслуживается только :data:`REPLAY_SERVED`, прочие
live-инструменты отклоняются обучающей ошибкой; в live-режиме — штатный путь
через ``session.ensure()`` + handler реестра, с аудитом write/escalated вызовов.

Зависимость односторонняя: этот модуль читает реестр и классификацию
безопасности из :mod:`backend_ctl.mcp_tools` (``build_registry``, ``TOOL_SAFETY``,
``_AUDITED_SAFETY``); mcp_tools про диспетчеризацию не знает.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Callable, Dict, Optional

from backend_ctl.mcp_errors import BackendUnavailable
from backend_ctl.mcp_tools import (
    RESPONSE_BYTE_CAP,
    TOOL_SAFETY,
    _AUDITED_SAFETY,
    _UNCAPPED_TOOLS,
    build_registry,
)
from backend_ctl.recorder import MODE_REPLAY, RecordingError

# ---------------------------------------------------------------------------
# Flight recorder: session-owned диспетчеризация + offline-реплей
# ---------------------------------------------------------------------------

#: Значение session.mode для offline-реплея — из recorder (общее место обеих сторон,
#: обе ходят «вниз» на recorder; обратной зависимости диспетчера на session нет).
_MODE_REPLAY = MODE_REPLAY

#: Каталог записей по умолчанию (env BACKEND_CTL_RECORD_DIR переопределяет).
_RECORD_DIR_ENV = "BACKEND_CTL_RECORD_DIR"
_DEFAULT_RECORD_DIR = "./backend_ctl_records"

#: Допустимое имя записи: буквы/цифры/._- (без разделителей путей и '..').
_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")

#: Зарезервированные имена устройств Windows. Они проходят проверку символов, но ОС
#: резолвит их в устройство мимо каталога: "NUL" глотает запись (success без файла),
#: "CON" пишет ленту в консоль — на stdio-сервере прямо в MCP-транспорт, а чтение с
#: "CON" вешает сервер на stdin. Отсекаем по basename без расширения, регистронезависимо.
_RESERVED_DEVICE_NAMES: frozenset = frozenset(
    {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {f"LPT{i}" for i in range(1, 10)}
)


def resolve_record_path(name: Any, *, create_dir: bool = False) -> str:
    """Имя записи → путь в BACKEND_CTL_RECORD_DIR (валидация: без разделителей/'..').

    Агент передаёт ИМЯ, а не путь — сервер удерживает файлы в отведённом каталоге:
    нельзя писать/читать произвольные пути. Удержание проверяется не только
    по символам имени, но и по ФАКТИЧЕСКИ отрезолвленному пути: только так ловятся
    имена, которые ОС уводит за пределы каталога (зарезервированные устройства).

    Args:
        create_dir: создать каталог записей. Только для пишущих инструментов —
            read-инструмент (record_load) не должен создавать каталог побочным эффектом.

    Raises:
        ValueError: имя пустое, содержит разделители/'..'/недопустимые символы,
            зарезервировано ОС либо резолвится за пределы каталога записей.
    """
    if not isinstance(name, str) or not name:
        raise ValueError("record: требуется непустое имя записи (name)")
    if "/" in name or "\\" in name or os.sep in name or ".." in name:
        raise ValueError(f"недопустимое имя записи {name!r}: без разделителей путей и '..' (только имя, не путь)")
    if not _SAFE_NAME_RE.match(name):
        raise ValueError(f"недопустимое имя записи {name!r}: только буквы/цифры/._- ")
    stem = name.split(".", 1)[0].upper()
    if stem in _RESERVED_DEVICE_NAMES:
        raise ValueError(
            f"недопустимое имя записи {name!r}: {stem} — зарезервированное имя устройства ОС "
            "(запись ушла бы в устройство, а не в файл). Выбери другое имя, например "
            f"{name}_rec."
        )
    filename = name if name.endswith(".jsonl") else f"{name}.jsonl"
    base = os.path.abspath(os.environ.get(_RECORD_DIR_ENV) or _DEFAULT_RECORD_DIR)
    if create_dir:
        os.makedirs(base, exist_ok=True)
    path = os.path.abspath(os.path.join(base, filename))
    # Финальная проверка удержания: сверяем отрезолвленный путь, а не исходное имя —
    # это последний рубеж, ловящий всё, что ОС увела за пределы каталога.
    if os.path.commonpath([base, path]) != base:
        raise ValueError(f"недопустимое имя записи {name!r}: путь уходит за пределы каталога записей {base!r}")
    return path


# ---- Session-owned handlers (session, arguments) ----


class _ArgError(Exception):
    """Ошибка разбора аргумента record-инструмента → обучающий error-dict, не сырой ValueError."""


def _resolve_or_error(name: Any, *, create_dir: bool = False) -> str:
    """Резолв имени записи в путь; ошибка валидации ИЛИ файловой системы → :class:`_ArgError`.

    OSError ловится наравне с ValueError: ``create_dir=True`` делает mkdir, и
    недоступный ``BACKEND_CTL_RECORD_DIR`` (нет прав, путь — файл, диск отвалился) давал
    PermissionError/NotADirectoryError. Выше по стеку это ловила ветка «соединение с
    бэкендом оборвано» и сбрасывала ЗДОРОВЫЙ driver, обрывая живые подписки — при том что
    сеть ни при чём. Агент получал ложную диагностику вместо имени нечитаемого пути.
    """
    try:
        return resolve_record_path(name, create_dir=create_dir)
    except ValueError as exc:
        raise _ArgError(str(exc)) from exc
    except OSError as exc:
        raise _ArgError(
            f"каталог записей недоступен ({exc.__class__.__name__}: {exc}). Проверь BACKEND_CTL_RECORD_DIR."
        ) from exc


def _int_arg_or_error(value: Any, field: str) -> Optional[int]:
    """``None`` → None; иначе int(value) или обучающая :class:`_ArgError` (не сырой ValueError)."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise _ArgError(f"{field} должно быть целым числом, получено {value!r}") from exc


def _record_start(session: Any, args: Dict[str, Any]) -> Any:
    try:
        path = _resolve_or_error(args.get("name"), create_dir=True)
        max_events = _int_arg_or_error(args.get("max_events"), "max_events")
    except _ArgError as exc:
        return {"success": False, "error": str(exc)}
    return session.start_recording(path, max_events=max_events)


def _record_stop(session: Any, args: Dict[str, Any]) -> Any:
    return session.stop_recording()


def _record_status(session: Any, args: Dict[str, Any]) -> Any:
    return session.record_status()


def _record_dump(session: Any, args: Dict[str, Any]) -> Any:
    try:
        path = _resolve_or_error(args.get("name"), create_dir=True)
    except _ArgError as exc:
        return {"success": False, "error": str(exc)}
    return session.dump_recording(path)


def _record_load(session: Any, args: Dict[str, Any]) -> Any:
    try:
        path = _resolve_or_error(args.get("name"))
        ring_maxlen = _int_arg_or_error(args.get("ring_maxlen"), "ring_maxlen")
    except _ArgError as exc:
        return {"success": False, "error": str(exc)}
    position = args.get("position", "end")
    if position not in ("end", "start"):
        return {"success": False, "error": f"position должна быть 'end' или 'start', получено {position!r}"}
    try:
        return session.load_replay(path, position=position, ring_maxlen=ring_maxlen)
    except (RecordingError, FileNotFoundError) as exc:
        return {"success": False, "error": str(exc)}


def _record_unload(session: Any, args: Dict[str, Any]) -> Any:
    return session.unload_replay()


#: Session-owned record-инструменты: диспетчеризуются по session, а не driver.
RECORD_HANDLERS: Dict[str, Callable[[Any, Dict[str, Any]], Any]] = {
    "record_start": _record_start,
    "record_stop": _record_stop,
    "record_status": _record_status,
    "record_load": _record_load,
    "record_unload": _record_unload,
    "record_dump": _record_dump,
}

#: Инструменты, обслуживаемые НАД ЗАПИСЬЮ в replay-режиме через detached-driver реплеера.
_REPLAY_DRIVER_SERVED: frozenset = frozenset({"events", "events_page", "telemetry_snapshot", "telemetry_history"})
#: Инструменты, обслуживаемые реплеером напрямую (записанный снимок / offline-семантика).
_REPLAY_PLAYER_SERVED: frozenset = frozenset({"system_overview", "state_get", "state_get_subtree", "await_condition"})
#: Полный набор REPLAY_SERVED (кроме record_*, которые в RECORD_HANDLERS).
REPLAY_SERVED: frozenset = _REPLAY_DRIVER_SERVED | _REPLAY_PLAYER_SERVED

_REPLAY_REJECT = object()  # sentinel: инструмент не обслуживается над записью


def _serve_replay(session: Any, name: str, args: Dict[str, Any]) -> Any:
    """Обслужить инструмент над записью (replay-режим) или вернуть sentinel-отказ."""
    player = session.replay_player
    if player is None:
        return _REPLAY_REJECT
    if name in _REPLAY_DRIVER_SERVED:
        # Те же handler'ы, что вживую — читают hub/read-model detached-driver'а (0 IPC).
        return build_registry()[name].handler(player.driver, args)
    if name == "system_overview":
        return player.system_overview()
    if name == "state_get":
        return player.state_get(args.get("path", ""))
    if name == "state_get_subtree":
        return player.state_get_subtree(args.get("path", ""))
    if name == "await_condition":
        return player.await_condition(args.get("kind"), args.get("spec"), timeout=args.get("timeout"))
    return _REPLAY_REJECT


def _replay_rejected(name: str) -> Dict[str, Any]:
    """Обучающая ошибка для live-инструмента, вызванного в replay-режиме."""
    return {
        "success": False,
        "error": (
            f"offline-реплей записи: инструмент {name!r} требует живой системы — "
            "record_unload() для возврата к live. Над записью доступны: "
            + ", ".join(sorted(REPLAY_SERVED | set(RECORD_HANDLERS)))
        ),
    }


def _shape(value: Any) -> Any:
    """Компактная форма значения для карты усечённого ответа (тип + размер, не содержимое)."""
    if isinstance(value, dict):
        return {"type": "dict", "keys": len(value)}
    if isinstance(value, (list, tuple)):
        return {"type": "list", "len": len(value)}
    if isinstance(value, str) and len(value) > 80:
        return {"type": "str", "len": len(value), "head": value[:80]}
    return value


def _cap_dict(result: Dict[str, Any], budget: int) -> Dict[str, Any]:
    """Карта ключей: малые значения сохраняются verbatim в пределах бюджета, крупные — форма.

    Крупная секция (per-process detail) сворачивается в форму, но ценные малые (anomalies,
    счётчики) доезжают целиком — усечение не прячет то, ради чего инструмент зовут. Бюджет
    кумулятивный → общий размер ограничен даже при россыпи малых ключей.
    """
    kept: Dict[str, Any] = {}
    remaining = budget
    for k, v in result.items():
        try:
            vsize = len(json.dumps(v, ensure_ascii=False, default=str))
        except Exception:  # noqa: BLE001 — несериализуемое → сворачиваем в форму
            vsize = remaining + 1
        if 0 <= vsize <= remaining:
            kept[k] = v
            remaining -= vsize
        else:
            kept[k] = _shape(v)
    return kept


def _cap_heavy(name: str, result: Any, args: Dict[str, Any]) -> Any:
    """Усечь тяжёлый ответ, если он превышает потолок и не запрошен ``full``.

    Не тяжёлый инструмент / ``full=true`` / ответ в пределах потолка → как есть. Иначе для
    dict — карта ключей с сохранением малых секций (см. :func:`_cap_dict`) + подсказка
    сузить path / запросить полный объём. Агент видит СТРУКТУРУ и ценные малые данные,
    не глотая 50К токенов.
    """
    if name in _UNCAPPED_TOOLS or args.get("full"):
        return result
    try:
        size = len(json.dumps(result, ensure_ascii=False, default=str))
    except Exception:  # noqa: BLE001 — несериализуемое не усекаем (пусть решает сервер)
        return result
    if size <= RESPONSE_BYTE_CAP:
        return result
    hint = f"ответ усечён по размеру ({size}B > {RESPONSE_BYTE_CAP}B). full=true — полный объём"
    if isinstance(result, dict):
        return {
            "_truncated": True,
            "_bytes": size,
            "_hint": hint + " (или сузь path/limit).",
            "keys": _cap_dict(result, RESPONSE_BYTE_CAP),
        }
    if isinstance(result, list):
        return {"_truncated": True, "_bytes": size, "_hint": hint + ".", "len": len(result), "head": result[:20]}
    return {"_truncated": True, "_bytes": size, "_hint": hint + ".", "value": _shape(result)}


def dispatch_tool(session: Any, name: str, arguments: Optional[Dict[str, Any]]) -> Any:
    """Единая session-aware диспетчеризация инструмента (live + replay + record).

    Порядок:
      1. record_* → session-owned handler (работает в любом режиме);
      2. replay-режим → REPLAY_SERVED над записью, прочие → обучающая ошибка;
      3. live → штатно: session.ensure() (может бросить BackendUnavailable — ловит сервер)
         + handler реестра.

    KeyError — неизвестный инструмент (решает вызывающий сервер).
    """
    arguments = arguments or {}
    # Байтовый потолок применяется и здесь: раньше session-owned ветки уходили
    # early-return'ом мимо _cap_heavy, и потолок обходился собственным исключением.
    # Опаснее прочих именно session_log: каждая аудит-запись несёт до 4КБ args +
    # 4КБ result, а дефолтный вызов отдаёт всё кольцо — до ~1.6МБ в контекст агента
    # без opt-in full=true.
    if name in RECORD_HANDLERS:
        return _cap_heavy(name, RECORD_HANDLERS[name](session, arguments), arguments)
    if name == "session_log":
        return _cap_heavy(name, _session_log(session, arguments), arguments)
    if session.mode == _MODE_REPLAY:
        served = _serve_replay(session, name, arguments)
        if served is not _REPLAY_REJECT:
            return _cap_heavy(name, served, arguments)  # тяжёлые ответы усекаются и над записью
        return _replay_rejected(name)
    spec = build_registry()[name]
    safety = TOOL_SAFETY.get(name)
    # session.ensure() может поднять BackendUnavailable (смерть соединения посреди
    # сессии — исключение, не error-dict). Раньше это происходило ДО веток аудита
    # ниже: попытка записи в упавший бэкенд не оставляла в журнале ни следа —
    # владелец не видел, что write-инструмент вообще пытались вызвать. Для audited
    # safety записываем попытку с этим исходом и пере-поднимаем исключение (не
    # глотаем — на нём держится reconnect-аппарат). Read-путь не аудируется — ensure()
    # там просто бросает дальше без записи.
    try:
        driver = session.ensure()
    except BackendUnavailable as exc:
        if safety in _AUDITED_SAFETY:
            session.record_audit(name, safety, arguments, error=exc)
        raise
    # Предполётная сверка send_command со схемой свода — обучающая ошибка вместо
    # таймаута. Блок тоже оседает в аудит (escalated-попытка со своим исходом).
    if name == "send_command":
        verr = session.validate_send_command(arguments)
        if verr is not None:
            result = {"success": False, "error": verr, "validation": True}
            session.record_audit(name, safety, arguments, result=result)
            return result
    # write/escalated оседают в аудит-журнале сессии (успех И исключение).
    if safety in _AUDITED_SAFETY:
        try:
            result = spec.handler(driver, arguments)
        except Exception as exc:  # noqa: BLE001 — записать исход, затем пробросить серверу
            session.record_audit(name, safety, arguments, error=exc)
            raise
        session.record_audit(name, safety, arguments, result=result)
        # Cap и на audited-ветке: в журнал пишется ПОЛНЫЙ результат (аудит обязан
        # быть точным), а агенту уходит усечённый — раньше write-путь обходил потолок
        # целиком, и send_command('state.get_subtree') заливал контекст.
        return _cap_heavy(name, result, arguments)
    # Усечение по размеру (full=true снимает).
    return _cap_heavy(name, spec.handler(driver, arguments), arguments)


def _session_log(session: Any, args: Dict[str, Any]) -> Any:
    """Хвост аудит-журнала мутаций ЭТОЙ сессии. ``limit`` — сколько последних."""
    raw = args.get("limit")
    if raw is None:
        return session.read_audit(None)
    try:
        limit = int(raw)
    except (TypeError, ValueError):
        # Обучающая ошибка, как record_* через _int_arg_or_error — не сырой ValueError.
        return {"success": False, "error": f"limit должно быть целым числом, получено {raw!r}"}
    return session.read_audit(limit)
