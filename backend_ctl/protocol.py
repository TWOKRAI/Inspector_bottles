# -*- coding: utf-8 -*-
"""protocol.py — распаковка конверта ответа + типизированные результаты интроспекции.

Чистый слой БЕЗ транспорта и без BackendDriver: только приведение сырого router-ответа
к явным формам. :func:`unwrap` робастно спускается по вложенному ``result``-конверту
оркестратора; dataclass'ы (``RouterStats``/``QueueDepths``/… ``Capabilities``) поверх
готовых introspect.*-команд приводят dict к полям, всегда сохраняя сырой ответ в ``raw``.

Выделено из ``driver.py`` (Phase C, C.1): форма ответа — самостоятельная зона, не
завязанная на сокет/подписки/watch. Пути пост-codemod — ``tooling/backend_ctl/protocol.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


def unwrap(res: Any, *keys: str, leaf: bool = False) -> Dict[str, Any]:
    """Единая распаковка конверта ответа команды (Task 0.4 — слияние двух хелперов).

    Ответ приезжает либо «плоским», либо завёрнутым оркестратором в
    ``{"success": ..., "result": {<payload>}}`` (иногда в два уровня). Два режима:

    - ``keys`` заданы → вернуть первый узел (спускаясь по ``result``), содержащий любой
      из ``keys`` (например ``router_stats``/``queue_sizes``/``workers``); не нашли —
      сам ``res`` (best-effort, парсер отдаст дефолты). Прежний ``_find_payload``.
    - ``leaf=True`` → спуститься по ``result`` до листовой нагрузки хендлера (config.reload
      → ``applied``, logger.sink.* → ``sink``). Прежний ``_leaf_result``.
    - иначе → ``res`` как dict.
    """
    if keys:
        node = res
        for _ in range(4):  # защита от бесконечного спуска на кривом ответе
            if not isinstance(node, dict):
                break
            if any(k in node for k in keys):
                return node
            node = node.get("result")
        return res if isinstance(res, dict) else {}
    if leaf:
        node = res if isinstance(res, dict) else {}
        for _ in range(4):  # защита от бесконечного спуска на кривом ответе
            nxt = node.get("result")
            if isinstance(nxt, dict):
                node = nxt
            else:
                break
        return node
    return res if isinstance(res, dict) else {}


def _find_payload(res: Any, *keys: str) -> Dict[str, Any]:
    """Алиас :func:`unwrap` (keys-режим)."""
    return unwrap(res, *keys)


def _leaf_result(res: Any) -> Dict[str, Any]:
    """Алиас :func:`unwrap` (leaf-режим)."""
    return unwrap(res, leaf=True)


def _is_ok(res: Any, payload: Dict[str, Any]) -> bool:
    """Успех ответа: ``success`` берём из полезной нагрузки или из внешнего конверта."""
    if isinstance(payload, dict) and "success" in payload:
        return bool(payload.get("success"))
    return bool(res.get("success")) if isinstance(res, dict) else False


@dataclass
class RouterStats:
    """Счётчики router'а процесса (introspect.router_stats).

    Отвечает на «дошло/ушло/дропнулось ли сообщение». ``raw`` — весь сырой ответ.
    """

    ok: bool
    sent_ok: int
    received: int
    middleware_dropped: int
    errors: int
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_response(cls, res: Any) -> "RouterStats":
        payload = _find_payload(res, "router_stats")
        stats = payload.get("router_stats") if isinstance(payload, dict) else None
        stats = stats if isinstance(stats, dict) else {}
        return cls(
            ok=_is_ok(res, payload),
            sent_ok=int(stats.get("sent_ok", 0) or 0),
            received=int(stats.get("received", 0) or 0),
            middleware_dropped=int(stats.get("middleware_dropped", 0) or 0),
            errors=int(stats.get("errors", 0) or 0),
            raw=res if isinstance(res, dict) else {},
        )


@dataclass
class QueueDepths:
    """Глубины собственных очередей процесса (introspect.queues).

    ``sizes`` — {тип_очереди: глубина|None}. None = qsize недоступен (macOS) —
    само по себе диагностично. ``raw`` — весь сырой ответ.
    """

    ok: bool
    sizes: Dict[str, Optional[int]]
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_response(cls, res: Any) -> "QueueDepths":
        payload = _find_payload(res, "queue_sizes")
        sizes = payload.get("queue_sizes") if isinstance(payload, dict) else None
        sizes = sizes if isinstance(sizes, dict) else {}
        return cls(
            ok=_is_ok(res, payload),
            sizes=dict(sizes),
            raw=res if isinstance(res, dict) else {},
        )


@dataclass
class WorkerStatus:
    """Статус процесса и его воркеров (introspect.status).

    ``process``/``status`` — имя и текущий статус процесса; ``workers`` —
    {имя_воркера: сериализуемый статус}. ``raw`` — весь сырой ответ.
    """

    ok: bool
    process: Optional[str]
    status: Optional[str]
    workers: Dict[str, Any]
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_response(cls, res: Any) -> "WorkerStatus":
        payload = _find_payload(res, "workers", "status")
        workers = payload.get("workers") if isinstance(payload, dict) else None
        workers = workers if isinstance(workers, dict) else {}
        return cls(
            ok=_is_ok(res, payload),
            process=payload.get("process") if isinstance(payload, dict) else None,
            status=payload.get("status") if isinstance(payload, dict) else None,
            workers=dict(workers),
            raw=res if isinstance(res, dict) else {},
        )


@dataclass
class MemoryStats:
    """Инвентарь памяти процесса (introspect.memory): SHM / пул / очереди.

    Только СТАТИСТИКА (Dict at Boundary) — кадры и содержимое SHM по сокету не
    гоняем. Секции независимы и best-effort: недоступная подсистема → ``None``
    (не ошибка). ``memory`` — ``MemoryManager.get_stats()``; ``pool`` — loan-счётчики
    SHM-колец из ПУБЛИЧНОГО ``router_manager.get_stats()`` (F6: ``frame_loan_pools``/
    ``frame_slots_*``); ``queues`` — глубины очередей (как introspect.queues);
    ``shm_registry`` — инвентарь SHM-реестра (launcher-level file-marker: в дочернем
    процессе обычно ``None``). ``raw`` — сырой ответ.
    """

    ok: bool
    memory: Optional[Dict[str, Any]]
    pool: Optional[Dict[str, Any]]
    queues: Optional[Dict[str, Any]]
    shm_registry: Optional[Dict[str, Any]]
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_response(cls, res: Any) -> "MemoryStats":
        payload = _find_payload(res, "memory", "pool", "queues", "shm_registry")

        def _sec(key: str) -> Optional[Dict[str, Any]]:
            val = payload.get(key) if isinstance(payload, dict) else None
            return val if isinstance(val, dict) else None

        return cls(
            ok=_is_ok(res, payload),
            memory=_sec("memory"),
            pool=_sec("pool"),
            queues=_sec("queues"),
            shm_registry=_sec("shm_registry"),
            raw=res if isinstance(res, dict) else {},
        )


@dataclass
class ProcessCapabilities:
    """Карточка процесса из introspect.capabilities (контактная книжка, Ф1 Task 1.9).

    Контракт процесса: ``commands`` — [{name, description, tags}], ``registers`` —
    {имя_регистра: [имена_полей]} (структура, без значений), ``router_handlers`` —
    НЕ-командные ключи event_dispatcher. ``raw`` — весь сырой ответ.
    """

    ok: bool
    process: Optional[str]
    commands: List[Dict[str, Any]]
    router_handlers: List[str]
    registers: Dict[str, List[str]]
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_response(cls, res: Any) -> "ProcessCapabilities":
        payload = _find_payload(res, "commands", "registers")
        commands = payload.get("commands") if isinstance(payload, dict) else None
        registers = payload.get("registers") if isinstance(payload, dict) else None
        handlers = payload.get("router_handlers") if isinstance(payload, dict) else None
        return cls(
            ok=_is_ok(res, payload),
            process=payload.get("process") if isinstance(payload, dict) else None,
            commands=list(commands) if isinstance(commands, list) else [],
            router_handlers=list(handlers) if isinstance(handlers, list) else [],
            registers=dict(registers) if isinstance(registers, dict) else {},
            raw=res if isinstance(res, dict) else {},
        )


@dataclass
class Capabilities:
    """Свод «контактной книжки» по всей системе (driver-side fan-out, Ф1 Task 1.9).

    ``processes`` — карточки всех процессов (включая ProcessManager);
    ``topology`` — {имя: {"class": dotted-path}} управляемых процессов (из PM);
    ``channels`` — каналы router'а PM. ``ok`` = PM ответил и все карточки собраны.
    """

    ok: bool
    processes: Dict[str, ProcessCapabilities]
    topology: Dict[str, Dict[str, Any]]
    channels: List[Dict[str, str]]
    raw: Dict[str, Any] = field(default_factory=dict)


__all__ = [
    "unwrap",
    "RouterStats",
    "QueueDepths",
    "WorkerStatus",
    "MemoryStats",
    "ProcessCapabilities",
    "Capabilities",
]
