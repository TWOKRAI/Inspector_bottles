# -*- coding: utf-8 -*-
"""
BackendDriver — socket-клиент к SocketChannel хоста (request-id matching).

Зеркало P0.5 над сокетом: пишет dict+"\n", читающий поток складывает ответы по
request_id в pending-слоты, request() блокирует до ответа/таймаута. Высокоуровневые
обёртки строят сообщения общими билдерами протокола (один источник правды с GUI).

Помимо reply-пути есть **событийный канал** (Ф1 Task 1.1): push-сообщения без
request_id (или не матчащие ни один pending) — например `state.changed` — не
дропаются, а складываются в bounded-очередь и рассылаются подписчикам. Так
`state.subscribe` через driver становится рабочим end-to-end. Разделение потоков:
reader-поток пишет события, клиентский поток читает их через events()/subscribe().

Без бизнес-логики: driver только транспортирует router-сообщения. Вся интроспекция/
команды исполняются процессами системы, ответы едут обратно чистым RouterManager.
"""

from __future__ import annotations

import json
import logging
import queue
import socket
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Deque, Dict, List, Optional

from multiprocess_framework.modules.telemetry_readmodel_module import TelemetryReadModel
from multiprocess_framework.modules.message_module import (
    build_command_message,
    build_system_command_message,
)

from .endpoint_config import resolve_endpoint

# Логгер клиента: reader-поток — daemon, его необработанное исключение уходит только
# в stderr-трейсбек; обрыв соединения логируем явно (A.3), чтобы причина «reader молча
# умер» была видима, а не терялась.
_log = logging.getLogger(__name__)

# Колбэк подписчика на события (получает распарсенный push-dict).
EventCallback = Callable[[Dict[str, Any]], None]

# Сентинел «под-секция не передана»: отличает отсутствие аргумента от явного None
# (для телеметрии ``publish=None`` — валидная команда «выключить gate», PC 3.2).
_UNSET: Any = object()

# TTL карантина таймаутнутых request_id (Task 0.2): дольше этого поздний ответ уже
# не ждём — запись протухает и вычищается лениво. Запас над самым долгим таймаутом.
_TIMED_OUT_TTL_SEC: float = 60.0

# Команда live-хвоста наблюдаемости на проводе (Ф5.20b): процесс пушит записи
# логов/ошибок/статистики адресно подписчику ЭТИМ command (зеркало
# RecordForwardChannel.FORWARD_COMMAND). Строка-контракт, не импортируем из
# framework-канала — чтобы driver не тянул серверный модуль (Dict at Boundary).
OBSERVABILITY_RECORD_COMMAND: str = "observability.record"

# Ранги лог-severity для клиентского фильтра observability_records(level=...) (F5).
# Только лог-плоскость: stats-метрики (gauge/counter) сюда НЕ попадают и не режутся.
_LOG_SEVERITY_RANK: Dict[str, int] = {
    "debug": 10,
    "info": 20,
    "warning": 30,
    "warn": 30,
    "error": 40,
    "critical": 50,
    "fatal": 50,
}

# GUI-эквивалентный набор wildcard'ов state-подписки (Task 2.2): зеркало
# multiprocess_prototype/frontend/process.py — ровно то, на что подписан GUI.
# Прототип может передать свой набор в watch_like_gui(patterns=...).
# F7 (framework-first): ``devices.**``/``calibration.**`` — app-домены прототипа,
# захардкоженные здесь как удобный дефолт. Пост-codemod (переезд в tooling/) набор
# инжектируется app-слоем (прототип передаёт свои паттерны), а модульный дефолт
# сузится до generic ``processes.**``/``system.**``. Сейчас поведение НЕ меняем.
GUI_DEFAULT_PATTERNS: tuple[str, ...] = (
    "processes.**",
    "system.**",
    "devices.**",
    "calibration.**",
)


def _drain_queue(q: "queue.Queue") -> None:
    """Ненадолго осушить очередь без блокировки (F3: leftover-намерения на unwatch).

    Снимает все немедленно доступные элементы; ``task_done`` сохраняет баланс для
    ``queue.join()``. Sentinel/имена процессов, оставшиеся после снятия watch, не
    должны применяться — applier их и так пропустит по guard'у, но пустая очередь
    исключает лишний виток.
    """
    while True:
        try:
            q.get_nowait()
        except queue.Empty:
            return
        else:
            try:
                q.task_done()
            except ValueError:  # task_done без соответствующего get — баланс уже нулевой
                pass


# ---------------------------------------------------------------------------
# Типизированные результаты интроспекции (Ф1 Task 1.2)
#
# Форма, а не бизнес-логика: обёртки поверх готовых introspect.*-команд лишь
# приводят сырой dict-ответ к dataclass'у с явными полями. Сырой ответ всегда
# сохраняется в поле ``raw`` — ничего не теряется, диагностику можно достать целиком.
# Ответ команды приезжает через request-response; введённый оркестратором конверт
# может вкладывать полезную нагрузку под ``result`` (одна-две вложенности), поэтому
# парсеры ищут её через :func:`_find_payload` — робастно к обеим формам.
# ---------------------------------------------------------------------------


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
    """Алиас :func:`unwrap` (keys-режим). Оставлен до Phase 1 (переезд в protocol.py)."""
    return unwrap(res, *keys)


def _leaf_result(res: Any) -> Dict[str, Any]:
    """Алиас :func:`unwrap` (leaf-режим). Оставлен до Phase 1 (переезд в protocol.py)."""
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


class _Pending:
    """Слот ожидания ответа по request_id."""

    __slots__ = ("event", "response")

    def __init__(self) -> None:
        self.event = threading.Event()
        self.response: Optional[Dict[str, Any]] = None


class _SubscriptionRegistry:
    """Реестр durable-намерений подписки (Task 0.3, ежедневная боль №1).

    Хранит, на ЧТО driver подписался (``state.subscribe`` / ``log.tail.subscribe`` /
    ``ui.tap.subscribe``), чтобы при реконнекте MCP-сервера подписки можно было
    повторить, а не потерять молча (события просто переставали приходить — агент
    думал «всё тихо»). Живёт в driver'е; Phase 1 вынесет в ``subscriptions.py``.

    Идентичность намерения — ``(command, target, identity)``, где identity = pattern
    (для state) либо subscriber (для log/ui): повторная подписка того же ключа
    перезаписывает, не плодит дубли.
    """

    def __init__(self) -> None:
        self._intents: Dict[tuple, Dict[str, Any]] = {}

    @staticmethod
    def _key(command: str, target: str, args: Dict[str, Any]) -> tuple:
        identity = args.get("pattern") or args.get("subscriber") or ""
        return (command, target, identity)

    def add(self, command: str, target: str, args: Dict[str, Any]) -> None:
        """Запомнить намерение подписки (idempotent по ключу)."""
        self._intents[self._key(command, target, args)] = {
            "command": command,
            "target": target,
            "args": dict(args),
        }

    def remove(self, command: str, target: str, args: Optional[Dict[str, Any]] = None) -> None:
        """Снять намерение. ``args=None`` → снять все с данными command+target
        (напр. ``ui.tap.unsubscribe`` без subscriber снимает tap процесса целиком)."""
        if args is not None:
            self._intents.pop(self._key(command, target, args), None)
            return
        for k in [k for k in self._intents if k[0] == command and k[1] == target]:
            del self._intents[k]

    def remove_by_command(self, command: str) -> None:
        """Снять ВСЕ намерения данной команды по всем target'ам (F2: подчистка watch).

        Используется unwatch'ем как safety-net: полу-durable watch (контур потерян при
        реконнекте) не должен воскресить obs-tail-намерения на любом процессе.
        """
        for k in [k for k in self._intents if k[0] == command]:
            del self._intents[k]

    def export(self) -> List[Dict[str, Any]]:
        """Снимок намерений (для передачи новому driver'у при реконнекте)."""
        return [
            {"command": v["command"], "target": v["target"], "args": dict(v["args"])} for v in self._intents.values()
        ]

    def load(self, intents: List[Dict[str, Any]]) -> None:
        """Загрузить намерения (в новый driver после реконнекта)."""
        for it in intents or []:
            self.add(it["command"], it["target"], it.get("args") or {})


class BackendDriver:
    """Тонкий driver: TCP-клиент + request-id matching + обёртки команд.

    Args:
        host: адрес SocketChannel хоста; ``None`` → env ``BACKEND_CTL_HOST`` → localhost.
        port: TCP-порт; ``None`` → env ``BACKEND_CTL_PORT`` → ``DEFAULT_PORT`` (8765).
            Резолв через ``resolve_endpoint`` — клиент читает те же env, что сервер.
        sender: имя отправителя в router-сообщениях.
        reply_to: адрес ответа. Driver не в queue_registry, ответ физически приходит
            в очередь ProcessManager (где живёт сокет) → reply_to="ProcessManager".
        default_timeout: таймаут request() по умолчанию.
        event_queue_maxlen: ёмкость bounded-очереди событий. При переполнении
            вытесняются самые старые (deque maxlen) — очередь не течёт, даже если
            подписчиков нет и события никто не вычитывает.
    """

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        *,
        sender: str = "backend_ctl",
        reply_to: str = "ProcessManager",
        default_timeout: float = 5.0,
        event_queue_maxlen: int = 1000,
    ) -> None:
        self._host, self._port = resolve_endpoint(host, port)
        self._sender = sender
        self._reply_to = reply_to
        self._default_timeout = default_timeout

        self._sock: Optional[socket.socket] = None
        self._reader: Optional[threading.Thread] = None
        self._running = False
        self._pending: Dict[str, _Pending] = {}
        self._pending_lock = threading.Lock()
        self._write_lock = threading.Lock()

        # Карантин таймаутнутых request_id (Task 0.2): request() при таймауте кладёт
        # сюда cid → срок годности; поздний ответ, пришедший ПОСЛЕ таймаута, dispatcher
        # опознаёт по этому множеству и дропает (иначе всплыл бы псевдо-событием).
        # TTL-purge ленивый — множество не растёт бесконечно. Под _pending_lock.
        self._timed_out: Dict[str, float] = {}
        self._late_replies = 0  # счётчик дропнутых поздних ответов (диагностика)

        # Durable-намерения подписки (Task 0.3): чтобы реконнект MCP-сервера мог
        # повторить подписки, а не потерять их молча. Заполняется subscribe-обёртками.
        self._subscriptions = _SubscriptionRegistry()

        # Событийный канал: reader-поток пишет, клиентский поток читает.
        # _events_cv охраняет и очередь, и список подписчиков; на нём же
        # блокируется events(timeout) в ожидании первого события.
        self._events: Deque[Dict[str, Any]] = deque(maxlen=event_queue_maxlen)
        self._events_cv = threading.Condition()
        self._subscribers: List[EventCallback] = []
        self._event_errors = 0  # счётчик исключений колбэков (диагностика)

        # GUI-эквивалентный watch (Task 2.2): авто-переподписка observability-хвоста
        # после авто-рестарта процесса. Слушатель живёт в reader-потоке и НЕ смеет
        # звать request() сам (дедлок — см. watch_like_gui): он лишь кладёт имя
        # процесса в очередь намерений, а отдельный applier-поток применяет их на
        # безопасном потоке. Всё под _watch_lock (reader и applier — разные потоки).
        self._watch_lock = threading.Lock()
        self._watch_active = False
        self._watch_subscribed: set[str] = set()  # процессы с активным obs-хвостом (дедуп)
        self._watch_listener: Optional[EventCallback] = None
        self._resub_queue: "queue.Queue[Optional[str]]" = queue.Queue()
        self._resub_thread: Optional[threading.Thread] = None
        self._watch_resub_timeout: Optional[float] = None
        self._watch_resub_errors = 0  # счётчик неудачных авто-переподписок (диагностика)
        self._watch_patterns: tuple[str, ...] = ()  # реально включённые watch-паттерны (для unwatch)
        self._watch_tail_level = "WARNING"  # объявленный порог логов (для watch-манифеста, F2)

        # Локальный read-model телеметрии (Task 2.3): «запись — всегда, чтение —
        # локально, история — по запросу» (ADR-136). Пассивно накапливает проекцию
        # state.changed-дельт (0 IPC на чтение), питая telemetry_snapshot/
        # telemetry_history. Generic Qt-free ядро (то же, что у GUI TelemetryViewModel).
        # Ингест лёгкий (dict + deque, без request()) — исполняется в reader-потоке;
        # читатели (snapshot/history) зовутся из другого потока, поэтому доступ к
        # модели сериализуется _telemetry_lock (dict/deque не потокобезопасны на
        # одновременную запись+итерацию).
        self._telemetry_model = TelemetryReadModel()
        self._telemetry_lock = threading.Lock()
        self.subscribe(self._ingest_state_changed)

    # ---- Соединение ----

    @property
    def host(self) -> str:
        """Адрес endpoint'а, к которому подключён driver (публичный аксессор, Task 0.4)."""
        return self._host

    @property
    def port(self) -> int:
        """TCP-порт endpoint'а (публичный аксессор вместо приватного _port, Task 0.4)."""
        return self._port

    def dispatch_raw(self, raw: bytes) -> None:
        """Публичная точка инъекции входящей строки (для тестов; Task 0.4).

        Тонкая обёртка над внутренним разбором: тесты событийного канала подают
        «проводные» строки, не трогая приватный ``_dispatch``.
        """
        self._dispatch(raw)

    def connect(self, timeout: float = 5.0) -> None:
        """Подключиться к хосту и запустить читающий поток."""
        self._sock = socket.create_connection((self._host, self._port), timeout=timeout)
        self._sock.settimeout(0.5)
        self._running = True
        self._reader = threading.Thread(target=self._read_loop, name="backend-ctl-reader", daemon=True)
        self._reader.start()

    def close(self) -> None:
        """Остановить читающий поток и закрыть сокет.

        Гасит и applier-поток watch (``backend-ctl-resub``): его иначе снимает только
        :meth:`unwatch`, а реконнект зовёт ``close()`` (``DriverSession.reset``) — без
        этого на каждый реконнект-с-активным-watch daemon-поток навсегда висел бы в
        ``q.get()``, удерживая ссылкой на ``self._resub_loop`` весь старый driver.
        """
        self._running = False
        # Снять watch-контур ПОД ЛОКОМ: гасим _watch_active, чтобы применитель по
        # layer-1 guard не дёргал сеть на закрывающемся сокете; забираем поток+очередь.
        with self._watch_lock:
            self._watch_active = False
            resub_thread = self._resub_thread
            self._resub_thread = None
            resub_q = self._resub_queue
        # Закрыть и обнулить сокет под _write_lock (симметрия с _send_raw/_read_loop):
        # иначе гонка обнуления с чтением _sock в другом потоке (A.3). Обнуление здесь
        # ДО очистки/пробуждения _pending ниже — намеренно: применитель, чей request()
        # ещё не вставил pending, увидит _sock is None в _send_raw и упадёт ConnectionError
        # мгновенно (не повиснет), а уже вставленные pending будятся снапшотом ниже.
        with self._write_lock:
            sock = self._sock
            self._sock = None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        # Разбудить всех ожидающих ответа (соединение закрыто) — в т.ч. applier,
        # если он застрял в in-flight request(): иначе его join ниже висел бы до таймаута.
        with self._pending_lock:
            pendings = list(self._pending.values())
            self._pending.clear()
        for p in pendings:
            p.event.set()
        # Остановить applier: sentinel в очередь его поколения + join. Idle-поток
        # получит None и выйдет; in-flight — уже разбужен пробуждением pendings выше.
        if resub_thread is not None:
            resub_q.put(None)
            resub_thread.join(timeout=1.0)
        if self._reader is not None:
            self._reader.join(timeout=1.0)
            self._reader = None
        # Разбудить тех, кто блокирует в events(timeout): новых событий не будет.
        with self._events_cv:
            self._events_cv.notify_all()

    def __enter__(self) -> "BackendDriver":
        self.connect()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # ---- Низкоуровневый request-response ----

    def request(self, message: Dict[str, Any], timeout: Optional[float] = None) -> Dict[str, Any]:
        """Отправить router-сообщение и дождаться ответа по request_id.

        Если в message нет request_id — назначается; в reply_to ставится self.reply_to,
        если не задан. Возвращает result из ответа (или error-dict при таймауте/обрыве).
        """
        if self._sock is None:
            return {"success": False, "error": "not connected"}

        cid = message.get("request_id") or str(uuid.uuid4())
        message["request_id"] = cid
        message.setdefault("reply_to", self._reply_to)

        pending = _Pending()
        with self._pending_lock:
            self._pending[cid] = pending
        try:
            self._send_raw(message)
            wait = timeout if timeout is not None else self._default_timeout
            if not pending.event.wait(wait):
                # Таймаут: пометить cid в карантин — поздний ответ dispatcher дропнет,
                # а не выдаст псевдо-событием (Task 0.2).
                self._quarantine_timed_out(cid)
                return {"success": False, "error": "timeout", "request_id": cid}
            if pending.response is None:
                return {"success": False, "error": "connection closed", "request_id": cid}
            return pending.response.get("result", pending.response)
        except (ConnectionError, OSError) as exc:
            # Гонка close()/request(): сокет обнулён/закрыт из другого потока во время
            # отправки → чистый error-dict, не AssertionError/утечка исключения (Task 0.2).
            return {"success": False, "error": "connection closed", "detail": str(exc), "request_id": cid}
        finally:
            with self._pending_lock:
                self._pending.pop(cid, None)

    def _quarantine_timed_out(self, cid: str) -> None:
        """Пометить request_id как таймаутнутый + лениво вычистить протухшие (Task 0.2)."""
        now = time.monotonic()
        with self._pending_lock:
            if self._timed_out:
                for stale in [k for k, exp in self._timed_out.items() if exp <= now]:
                    del self._timed_out[stale]
            self._timed_out[cid] = now + _TIMED_OUT_TTL_SEC

    def _send_raw(self, message: Dict[str, Any]) -> None:
        line = (json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8")
        with self._write_lock:
            sock = self._sock
            if sock is None:
                # close() из другого потока обнулил сокет — не assert'им, а поднимаем
                # штатную ConnectionError (request() превращает её в error-dict).
                raise ConnectionError("socket closed")
            sock.sendall(line)

    def _read_loop(self) -> None:
        buf = b""
        while self._running:
            # Захватить локальную ссылку под _write_lock: close() из другого потока
            # обнуляет _sock, и без этого self._sock.recv() в окне между проверкой
            # условия и вызовом дал бы AttributeError, тихо роняющий reader (daemon,
            # только stderr). Локальная копия делает recv() устойчивым к гонке.
            with self._write_lock:
                sock = self._sock
            if sock is None:
                break
            try:
                chunk = sock.recv(4096)
            except socket.timeout:
                continue
            except (OSError, AttributeError) as exc:
                # Обрыв в момент чтения. Штатное закрытие (_running=False) — молча;
                # неожиданный обрыв при живом клиенте — залогировать (не только stderr).
                if self._running:
                    _log.warning("backend_ctl reader: обрыв соединения при recv (%s)", exc)
                break
            if not chunk:
                if self._running:
                    _log.warning("backend_ctl reader: сервер закрыл соединение")
                break
            buf += chunk
            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                if raw.strip():
                    self._dispatch(raw)

    def _dispatch(self, raw: bytes) -> None:
        """Распарсить входящую строку и развести по reply-пути или событийному каналу.

        Reply-путь: если у сообщения есть request_id и его ждёт pending-слот — будим
        ожидающего request(). Иначе (нет request_id ИЛИ никто уже не ждёт — поздний
        ответ после таймаута / push вроде state.changed) сообщение становится
        событием и уходит в очередь + подписчикам (раньше здесь молча дропалось).
        """
        try:
            msg = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return
        if not isinstance(msg, dict):
            return
        cid = msg.get("request_id")
        if cid:
            with self._pending_lock:
                pending = self._pending.get(cid)
                # Поздний ответ после таймаута: pending уже снят, но cid в карантине —
                # опознаём и дропаем (не псевдо-событие). Иначе — обычная логика.
                is_late = pending is None and cid in self._timed_out
                if is_late:
                    del self._timed_out[cid]
                    # Инкремент под тем же локом: dispatch_raw (Task 0.4) сделал _dispatch
                    # публичным → нельзя опираться на «только reader-поток» (ревью MINOR #3).
                    self._late_replies += 1
            if pending is not None:
                pending.response = msg
                pending.event.set()
                return
            if is_late:
                return
        # Нет request_id либо reply уже никто не ждёт (и это не карантин) → это событие.
        self._emit_event(msg)

    # ---- Событийный канал (push-сообщения без reply) ----

    def _emit_event(self, msg: Dict[str, Any]) -> None:
        """Положить событие в bounded-очередь и синхронно оповестить подписчиков.

        Вызывается только из reader-потока. Исключение любого колбэка не роняет
        reader-поток (глотается, инкрементит счётчик _event_errors) и не мешает
        остальным подписчикам.
        """
        with self._events_cv:
            self._events.append(msg)
            subscribers = list(self._subscribers)  # снимок под локом
            self._events_cv.notify_all()
        # Колбэки — вне лока: могут быть медленными и/или звать driver повторно.
        for cb in subscribers:
            try:
                cb(msg)
            except Exception:  # noqa: BLE001 — контракт: колбэк не роняет reader
                self._event_errors += 1

    def subscribe(self, callback: EventCallback) -> EventCallback:
        """Подписаться на события: callback зовётся на каждое push-сообщение.

        Колбэк исполняется в reader-потоке — держи его лёгким (тяжёлую работу
        отдай в свой поток/очередь). Возвращает сам callback (хэндл для unsubscribe).
        """
        with self._events_cv:
            self._subscribers.append(callback)
        return callback

    def unsubscribe(self, callback: EventCallback) -> None:
        """Отписать ранее зарегистрированный callback (no-op, если его нет)."""
        with self._events_cv:
            try:
                self._subscribers.remove(callback)
            except ValueError:
                pass

    def events(
        self,
        timeout: Optional[float] = 0.0,
        *,
        max_items: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Прочитать накопленные события (drain).

        Семантика timeout:
        - `0.0` (по умолчанию) — поллинг: сразу вернуть, что накоплено (может быть []);
        - `>0` — блокировать до появления хотя бы одного события, но не дольше timeout,
          затем слить всё накопленное;
        - `None` — блокировать до первого события (или до close()).

        max_items ограничивает размер пачки (остаток останется в очереди).
        Возвращает список событий в порядке поступления (FIFO).
        """
        with self._events_cv:
            # Три режима ожидания разведены явно — так `deadline` в блокирующей
            # ветке всегда float (без Optional-narrowing) и каждая семантика читается
            # отдельно. Поллинг (timeout == 0.0) вообще не ждёт — сразу к drain.
            if timeout is None:
                while not self._events:
                    # Бесконечное ожидание: не висеть вечно на закрытом/не открытом
                    # соединении — выходим (новых событий не будет).
                    if not self._running and self._reader is None:
                        break
                    self._events_cv.wait()
            elif timeout > 0.0:
                deadline = time.monotonic() + timeout
                while not self._events:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    self._events_cv.wait(remaining)
            if max_items is None:
                count = len(self._events)
            else:
                count = min(max_items, len(self._events))
            return [self._events.popleft() for _ in range(count)]

    @property
    def event_errors(self) -> int:
        """Сколько раз колбэк подписчика бросил исключение (диагностика)."""
        return self._event_errors

    @property
    def late_replies(self) -> int:
        """Сколько поздних ответов (пришли после таймаута request) дропнуто (Task 0.2)."""
        return self._late_replies

    # ---- Durable-подписки (Task 0.3): переживают реконнект MCP-сервера ----

    @staticmethod
    def _looks_failed(res: Any) -> bool:
        """Ответ явно провальный? (для решения «регистрировать ли намерение»)."""
        return isinstance(res, dict) and res.get("success") is False

    def _register_subscription(self, command: str, target: str, args: Dict[str, Any], res: Any) -> None:
        """Записать намерение подписки, если команда НЕ провалилась явно.

        Смещение в сторону over-record: лишний replay безвреден (просто повторный
        subscribe), а вот потеря реальной подписки — это как раз баг, который чиним.
        """
        if not self._looks_failed(res):
            self._subscriptions.add(command, target, args)

    def export_subscriptions(self) -> List[Dict[str, Any]]:
        """Снимок durable-намерений (MCP-сервер передаёт их новому driver'у)."""
        return self._subscriptions.export()

    def import_subscriptions(self, intents: List[Dict[str, Any]]) -> None:
        """Загрузить намерения в этот driver (после реконнекта)."""
        self._subscriptions.load(intents)

    def replay_subscriptions(self) -> List[Dict[str, Any]]:
        """Повторить все записанные подписки на текущем соединении.

        Зовётся после реконнекта: восстанавливает поток событий, который иначе
        молча оборвался бы. Идёт напрямую через send_command (не через обёртки),
        поэтому не пере-регистрирует намерения. Возвращает список
        ``{command, target, success}`` для отчёта агенту.
        """
        results: List[Dict[str, Any]] = []
        for it in self._subscriptions.export():
            res = self.send_command(it["target"], it["command"], it["args"])
            results.append(
                {
                    "command": it["command"],
                    "target": it["target"],
                    "success": bool(isinstance(res, dict) and res.get("success")),
                }
            )
        return results

    # ---- Высокоуровневые обёртки (общие билдеры протокола) ----

    def send_command(
        self,
        target: str,
        command: str,
        args: Optional[Dict[str, Any]] = None,
        *,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Прямая команда процессу (форма CommandSender.send_command) + request-response."""
        msg = build_command_message(target, command, args, sender=self._sender, reply_to=self._reply_to)
        return self.request(msg, timeout=timeout)

    def system_command(
        self,
        command: Dict[str, Any],
        *,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """System-команда в ProcessManager (форма CommandSender.send_system_command)."""
        msg = build_system_command_message(command, sender=self._sender, reply_to=self._reply_to)
        return self.request(msg, timeout=timeout)

    # ---- Интроспекция (P1 команды) ----

    def introspect_handlers(self, process: str, **kw: Any) -> Dict[str, Any]:
        """Хендлеры процесса: ключи message_dispatcher + команды CommandManager."""
        return self.send_command(process, "introspect.handlers", **kw)

    def introspect_registers(self, process: str, **kw: Any) -> Dict[str, Any]:
        """Регистры процесса (имена + поля; пусто = нет worker-side приёмника)."""
        return self.send_command(process, "introspect.registers", **kw)

    def introspect_status(self, process: str, **kw: Any) -> Dict[str, Any]:
        """Статус процесса: имя, воркеры, состояние."""
        return self.send_command(process, "introspect.status", **kw)

    def get_status(self, process: str, **kw: Any) -> Dict[str, Any]:
        """Алиас introspect_status (симметрия с MCP-инструментами P3)."""
        return self.introspect_status(process, **kw)

    def introspect_router_stats(self, process: str, **kw: Any) -> Dict[str, Any]:
        """Счётчики router'а процесса (сырой dict): sent_ok/received/dropped/errors."""
        return self.send_command(process, "introspect.router_stats", **kw)

    def introspect_queues(self, process: str, **kw: Any) -> Dict[str, Any]:
        """Глубины очередей процесса (сырой dict): backpressure-диагностика."""
        return self.send_command(process, "introspect.queues", **kw)

    def introspect_plugins(self, process: str, **kw: Any) -> Dict[str, Any]:
        """Каталог плагинов процесса + failed_imports (Ф2.3: опечатка в плагине видна)."""
        return self.send_command(process, "introspect.plugins", **kw)

    def introspect_memory(self, process: str, *, timeout: Optional[float] = None) -> MemoryStats:
        """Инвентарь памяти процесса (SHM / пул займов / очереди) как :class:`MemoryStats`.

        Только статистика (Dict at Boundary) — кадры/содержимое SHM по сокету не
        гоняем. Секции best-effort: недоступная подсистема → ``None`` (не ошибка).
        Возвращает типизированный результат с сырым ответом в ``.raw`` (симметрия
        с :meth:`queues`/:meth:`router_stats`, но команда — новая ``introspect.memory``).
        """
        res = self.send_command(process, "introspect.memory", timeout=timeout)
        return MemoryStats.from_response(res)

    # ---- Типизированные обёртки (dataclass-результаты, Ф1 Task 1.2) ----
    #
    # Никакой бизнес-логики — только форма: сырой introspect-ответ → dataclass с
    # явными полями (+ сырой dict в .raw). Реальные команды берутся из
    # BuiltinCommands._register_introspect_commands (router_stats/queues/status).
    # Отдельной introspect.wire-команды в системе НЕТ (есть только wire.configure/
    # deconfigure — это действия, не интроспекция), поэтому wire_status() не вводим:
    # обёртывать нечего (сверено с builtin_commands.py). Появится introspect.wire —
    # добавим симметрично.

    def router_stats(self, process: str, **kw: Any) -> RouterStats:
        """Счётчики router'а процесса как :class:`RouterStats` (форма, не логика)."""
        return RouterStats.from_response(self.introspect_router_stats(process, **kw))

    def queues(self, process: str, **kw: Any) -> QueueDepths:
        """Глубины очередей процесса как :class:`QueueDepths` (форма, не логика)."""
        return QueueDepths.from_response(self.introspect_queues(process, **kw))

    def worker_status(self, process: str, **kw: Any) -> WorkerStatus:
        """Статус процесса и воркеров как :class:`WorkerStatus` (форма, не логика)."""
        return WorkerStatus.from_response(self.introspect_status(process, **kw))

    def introspect_capabilities(self, process: str, **kw: Any) -> Dict[str, Any]:
        """Карточка процесса (сырой dict): команды+descriptions, регистры, handlers."""
        return self.send_command(process, "introspect.capabilities", **kw)

    def capabilities(
        self,
        *,
        pm_name: str = "ProcessManager",
        timeout: float = 8.0,
    ) -> Capabilities:
        """Свод «контактной книжки» по всей системе (Ф1 Task 1.9).

        Fan-out на стороне driver'а (НЕ внутри PM-хендлера — там блокирующий сбор
        ответов детей дедлочит message_processor): сперва карточка PM (в ней
        ``processes``-топология и ``channels`` из ``capabilities_extra``), затем
        ``introspect.capabilities`` каждому управляемому процессу. Карточка,
        не ответившая за timeout, попадает в свод с ``ok=False`` (диагностично).
        """
        pm_res = self.introspect_capabilities(pm_name, timeout=timeout)
        pm_card = ProcessCapabilities.from_response(pm_res)
        pm_payload = _find_payload(pm_res, "processes", "commands")
        topology = pm_payload.get("processes") if isinstance(pm_payload, dict) else None
        topology = topology if isinstance(topology, dict) else {}
        channels = pm_payload.get("channels") if isinstance(pm_payload, dict) else None
        channels = channels if isinstance(channels, list) else []

        cards: Dict[str, ProcessCapabilities] = {pm_name: pm_card}
        for name in sorted(topology):
            cards[name] = ProcessCapabilities.from_response(self.introspect_capabilities(name, timeout=timeout))

        return Capabilities(
            ok=pm_card.ok and all(c.ok for c in cards.values()),
            processes=cards,
            topology={k: dict(v) if isinstance(v, dict) else {} for k, v in topology.items()},
            channels=[dict(c) for c in channels if isinstance(c, dict)],
            raw=pm_res if isinstance(pm_res, dict) else {},
        )

    def set_register(
        self,
        process: str,
        register: str,
        field: str,
        value: Any,
        **kw: Any,
    ) -> Dict[str, Any]:
        """Записать значение регистра в живой процесс (live field-write).

        Ключи data — канонический контракт ``register_update`` (тот же, что шлёт GUI
        через routing_map/CommandSender): ``{"register", "field", "value"}``.
        Исторический баг: driver слал ``plugin_name`` — обработчик оркестратора молча
        выходил, запись была no-op (найдено verify-probe Ф1.6). Имя регистра обычно
        совпадает с plugin_name (регистр на плагин).
        """
        return self.send_command(
            process,
            "register_update",
            {"register": register, "field": field, "value": value},
            **kw,
        )

    def set_register_verified(
        self,
        process: str,
        register: str,
        field: str,
        value: Any,
        *,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Verify-probe (Ф1 Task 1.6): write → readback → diff.

        Не доверяет ack'у записи: после :meth:`set_register` читает
        ``introspect.registers`` того же процесса и сравнивает фактическое значение
        поля с ожидаемым. Ловит весь класс молчаливых no-op'ов: несуществующий
        регистр/поле, неверные ключи payload, отвал приёмника. ``verified`` может
        отличаться от ``value`` и при легитимной коэрции значения Pydantic-схемой —
        тогда смотреть ``actual``.
        """
        ack = self.set_register(process, register, field, value, timeout=timeout)
        res = self.introspect_registers(process, timeout=timeout)
        payload = _find_payload(res, "registers")
        registers = payload.get("registers") if isinstance(payload, dict) else None
        registers = registers if isinstance(registers, dict) else {}
        reg = registers.get(register)
        found = isinstance(reg, dict) and field in reg
        actual = reg.get(field) if found else None
        verified = bool(found and actual == value)
        return {
            "success": verified,
            "verified": verified,
            "found": found,
            "process": process,
            "register": register,
            "field": field,
            "expected": value,
            "actual": actual,
            "known_registers": sorted(registers),
            "ack": ack,
        }

    # ---- Observability control plane (Ф1 Task 1.4: config.reload / logger.sink.*) ----

    def config_reload(
        self,
        process: str,
        *,
        observability: Optional[Dict[str, Any]] = None,
        path: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Перечитать/применить observability-секцию процесса на лету.

        ``observability`` — inline-override (dict), например ``{"log_level": "DEBUG"}``
        (сменить уровень логгера на лету). Без него процесс читает свой файл конфига
        (``path`` или ``observability_config_path`` — тот же путь, что hot-reload watcher).
        Ответ содержит ``applied.log_level`` — применённый уровень (диагностика).
        """
        args: Dict[str, Any] = {}
        if observability is not None:
            args["observability"] = observability
        if path is not None:
            args["path"] = path
        return _leaf_result(self.send_command(process, "config.reload", args, timeout=timeout))

    def logger_sink_enable(self, process: str, sink: str, *, timeout: Optional[float] = None) -> Dict[str, Any]:
        """Включить sink логгера процесса по имени (register_channel)."""
        return _leaf_result(self.send_command(process, "logger.sink.enable", {"sink": sink}, timeout=timeout))

    def logger_sink_disable(self, process: str, sink: str, *, timeout: Optional[float] = None) -> Dict[str, Any]:
        """Выключить sink логгера процесса по имени (unregister_channel)."""
        return _leaf_result(self.send_command(process, "logger.sink.disable", {"sink": sink}, timeout=timeout))

    # ---- Telemetry publish control plane (PC 3.2/3.3: адресно + fan-out на всех) ----

    def telemetry_reconfigure(
        self,
        process: str = "all",
        *,
        publish: Any = _UNSET,
        throttle: Any = _UNSET,
        mode: str = "replace",
        pm_name: str = "ProcessManager",
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Рантайм-переконфигурация телеметрии: адресно ИЛИ fan-out на всех детей.

        Две плоскости управления (план telemetry-publish-control), обе опциональны, но
        хотя бы одна обязательна (иначе — error-dict, ничего не шлётся):

          - ``publish`` → publisher-gate (что процесс СЧИТАЕТ/публикует и как часто).
            ``publish=None`` — валидная команда «выключить gate» (все метрики каждый тик).
          - ``throttle`` → центральный store-троттл оркестратора (rate-limit записи в дерево/IPC).

        ``mode`` (Task 1.1) — режим применения ОБЕИХ плоскостей:
          - ``"replace"`` (дефолт) — секция применяется ЦЕЛИКОМ. **ОСТОРОЖНО (wipe):**
            publisher-gate пересобирается из ``publish`` (не указанные метрики → дефолты);
            ``throttle`` идёт через ``set_rules`` — ПОЛНАЯ замена набора правил (сносит все
            прочие правила, включая дефолтную IPC-страховку). Для «точечной» правки без
            сноса соседей — ``mode="merge"`` или :meth:`telemetry_set` (он и есть merge).
          - ``"merge"`` — дельта поверх ЖИВОГО состояния: publisher-override сохраняются,
            throttle правится по-правилу (``update_rule``/``remove_rule``; значение ``None``
            у throttle-паттерна → удалить правило). На проводе режим присутствует только при
            ``merge`` (``replace`` — прежний конверт бит-в-бит).

        Адресация по ``process`` (Task 1.4 — ОБА пути через PM, cap-aware):
          - имя процесса → адресно ОДНОМУ ребёнку транзитом через PM
            (``telemetry.broadcast`` с ``target=process``): PM форвардит ``publish`` этому
            ребёнку, ``throttle`` применяет к ЦЕНТРАЛЬНОМУ троттлу (троттл оркестратор-
            глобален). Транзит через PM — чтобы он детектил ``capped_by_throttle`` и на
            per-process пути (прямой driver→child путь этого не мог: central-правила живут
            лишь на оркестраторе, ADR-PM-017 Task 1.4). Возвращает ОХВАТ (``reached``/
            ``target_count`` = 0/1) + ``capped_by_throttle`` при срезе. Fire-and-forward:
            per-child ``applied`` больше не возвращается (сбор ответа ребёнка в PM дедлочил
            бы message_processor) — факт применения смотреть по ``effective_hz`` в дереве.
          - ``"all"`` / ``"*"`` / ``None`` → fan-out: ``telemetry.broadcast`` на PM →
            ``publish`` рассылается ВСЕМ живым детям, ``throttle`` применяется к
            ЦЕНТРАЛЬНОМУ троттлу оркестратора. Возвращает агрегированный ОХВАТ
            (``publish.reached`` / ``target_count`` — «no silent caps»).
        """
        args: Dict[str, Any] = {}
        if publish is not _UNSET:
            args["publish"] = publish
        if throttle is not _UNSET:
            args["throttle"] = throttle
        if not args:
            return {"success": False, "error": "нужна хотя бы одна под-секция: publish и/или throttle"}
        # На проводе telemetry_mode присутствует ТОЛЬКО при merge: replace — дефолт
        # хендлеров, прежний конверт бит-в-бит (backward-compat старых сообщений).
        if mode != "replace":
            args["telemetry_mode"] = mode

        # Task 1.4: и адресный, и fan-out путь идут через PM (единственный держатель
        # central-троттла → детектит capped_by_throttle на ОБОИХ путях). Адресный кейс
        # помечается data["target"] — PM форвардит publish ОДНОМУ ребёнку (не broadcast),
        # throttle применяет центрально. Прямой driver→child путь ретрополнен: cap на нём
        # был принципиально не детектируем (central-правила живут лишь на оркестраторе).
        if process not in (None, "", "all", "*"):
            args["target"] = process
        return _leaf_result(self.send_command(pm_name, "telemetry.broadcast", args, timeout=timeout))

    def telemetry_set(
        self,
        process: str,
        metric: str,
        *,
        enabled: Any = _UNSET,
        interval_sec: Any = _UNSET,
        plane: str = "publisher",
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Точечно поменять ОДНУ метрику/правило (узкая обёртка над :meth:`telemetry_reconfigure`).

        **Точечность (Task 1.1):** обёртка шлёт ``mode="merge"`` — дельта применяется поверх
        ЖИВОГО состояния, поэтому меняется РОВНО одно правило/метрика, а остальные override'ы
        и правила сохраняются (раньше был full-apply, сносивший соседей).

        ``plane="publisher"`` (дефолт, главный рычаг) — строит
        ``publish={"metrics": {metric: {enabled?, interval_sec?}}}`` и мержит его в живой gate:
        прочие метрики-override сохраняются.

        ``plane="throttle"`` — ``metric`` трактуется как glob-путь правила, ``interval_sec`` —
        min-интервал; строит ``throttle={metric: interval_sec}`` и мержит в центральный троттл
        оркестратора через ``update_rule`` (остальные правила, включая дефолтную IPC-страховку
        на ``latency_ms``/``effective_hz``/…, не тронуты). Чтобы СНЯТЬ правило точечно — передай
        ``interval_sec=None`` в :meth:`telemetry_reconfigure` ``throttle={metric: None}, mode="merge"``.

        **Троттл = IPC-предохранитель, НЕ потолок (Task 1.3, ADR-PM-017):** central-троттл
        (``throttle``) — независимая ступень rate-limit'а в оркестраторе НАД publisher-gate,
        но её роль — страховка от СБОЙНОГО публикатора, а не второй авторитет частоты.
        Дефолтные central-правила заведомо мягче любого осмысленного publisher-интервала
        (``0.05с`` ≈ 20 Гц) — поднятие частоты через publisher (например ``interval_sec=0.1``)
        в дефолтном сценарии доходит до дерева БЕЗ среза.

        Если оператор вручную задал строгое central-правило (``plane="throttle"``) и затем
        поднял publisher-частоту НИЖЕ него — троттл его НЕ ослабляет автоматически («no
        silent caps»): результат несёт явный флаг ``capped_by_throttle: {metric:
        {publisher_interval_sec, throttle_interval_sec}}`` — увидев его, ослабь central-
        правило тем же вызовом с ``plane="throttle"``. Task 1.4: флаг детектится на ОБОИХ
        путях — и fan-out (``process="all"``), и адресном (конкретный процесс), т.к. оба
        идут транзитом через PM (держатель central-троттла). Throttle-плоскость
        по-прежнему full-apply в ``mode="replace"`` и точечная (per-правило) в ``mode="merge"``
        (Task 1.1).

        ``process`` — имя процесса ИЛИ ``"all"`` (fan-out через PM). Требуется ``enabled``
        и/или ``interval_sec`` (для throttle — обязателен ``interval_sec``), иначе error-dict.
        """
        if plane == "throttle":
            if interval_sec is _UNSET:
                return {"success": False, "error": "throttle-плоскость требует interval_sec (min-интервал правила)"}
            return self.telemetry_reconfigure(process, throttle={metric: interval_sec}, mode="merge", timeout=timeout)
        if plane != "publisher":
            return {"success": False, "error": f"неизвестная plane '{plane}' (publisher|throttle)"}

        rule: Dict[str, Any] = {}
        if enabled is not _UNSET:
            rule["enabled"] = bool(enabled)
        if interval_sec is not _UNSET:
            rule["interval_sec"] = interval_sec
        if not rule:
            return {"success": False, "error": "нужен enabled и/или interval_sec"}
        return self.telemetry_reconfigure(process, publish={"metrics": {metric: rule}}, mode="merge", timeout=timeout)

    # ---- Telemetry read-model (Task 2.3: GUI-эквивалент чтения телеметрии, 0 IPC) ----

    # Зеркало Delta.to_dict(): new_value=='__MISSING__' → удаление узла. Литерал, а
    # не импорт, СОЗНАТЕЛЬНО: импорт state_store_module.core.delta затащил бы Qt в
    # headless-драйвер (package __init__ тянет GuiStateProxy→PySide6). Дрейф маркера
    # ловит контракт-тест test_missing_marker_matches_state_store (импорт Qt в тесте — ок).
    _MISSING_MARKER = "__MISSING__"

    def _ingest_state_changed(self, msg: Dict[str, Any]) -> None:
        """Слушатель событийного канала: питает локальный telemetry read-model.

        Исполняется в reader-потоке (колбэк :meth:`subscribe`) — только лёгкий
        ingest в память, без ``request()`` (как и :meth:`_on_watch_event`). Разбирает
        push ``state.changed`` (конверт ``{"command":"state.changed","data":{"deltas":
        [Delta.to_dict(), ...]}}``): каждую дельту вносит в read-model. Удаление узла
        распознаётся по ``new_value == "__MISSING__"`` (сериализация MISSING).

        Ингест под ``_telemetry_lock`` — читатели snapshot/history зовутся из другого
        потока и итерируют те же dict/deque.
        """
        if not isinstance(msg, dict) or msg.get("command") != "state.changed":
            return
        data = msg.get("data")
        if not isinstance(data, dict):
            return
        deltas = data.get("deltas")
        if not isinstance(deltas, list):
            return
        with self._telemetry_lock:
            for delta in deltas:
                if not isinstance(delta, dict):
                    continue
                path = delta.get("path")
                if not isinstance(path, str) or not path:
                    continue
                new_value = delta.get("new_value")
                if new_value == self._MISSING_MARKER:
                    self._telemetry_model.ingest(path, None, deleted=True)
                else:
                    self._telemetry_model.ingest(path, new_value)

    @staticmethod
    def _telemetry_key(path: str) -> Dict[str, Optional[str]]:
        """Корреляционный ключ ``(process, worker)`` из пути телеметрии.

        Форма пути — ``processes.<process>[...workers.<worker>...].<metric>``
        (см. ``build_worker_telemetry``). ts у истории отдельно (в точках буфера) —
        вместе это ключ ``(process, worker, ts)`` (OTel: сигналы раздельно, ключ общий).
        Не-``processes.*`` путь → process/worker = None.
        """
        parts = path.split(".")
        process = parts[1] if len(parts) >= 2 and parts[0] == "processes" else None
        worker = None
        if "workers" in parts:
            wi = parts.index("workers")
            if wi + 1 < len(parts):
                worker = parts[wi + 1]
        return {"process": process, "worker": worker}

    def _telemetry_matches_metric(self, path: str, metric: str) -> bool:
        """Путь соответствует метрике: точное совпадение или суффикс ``.<metric>``.

        ``metric="fps"`` матчит ``processes.cam.state.fps``; ``metric="state.fps"``
        тоже. Граница — точка-разделитель (не подстрока), чтобы ``fps`` не цеплял
        ``max_fps`` и т.п.
        """
        return path == metric or path.endswith("." + metric)

    def telemetry_snapshot(
        self,
        process: Optional[str] = None,
        metric: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Локальный снимок телеметрии из read-model — 0 IPC (ADR-136).

        Читает накопленную проекцию ``state.changed``-дельт (наполняется, пока
        активна state-подписка на ``processes.**`` — напр. после
        :meth:`watch_like_gui`). Похода на сервер НЕ делает.

        Args:
            process: фильтр по процессу — снимок поддерева ``processes.<process>``.
                None → весь накопленный снимок.
            metric: фильтр по метрике (суффикс ``.<metric>`` или точное совпадение),
                напр. ``"fps"`` / ``"state.fps"`` / ``"effective_hz"``. None → все пути.

        Returns:
            ``{"success": True, "process": ..., "metric": ..., "count": N,
            "metrics": {path: {"value": v, "process": p, "worker": w}}}``. Пустой
            read-model (не было дельт) → ``count=0`` (не ошибка).
        """
        prefix = f"processes.{process}" if process else ""
        with self._telemetry_lock:
            snap = self._telemetry_model.snapshot(prefix)
        metrics: Dict[str, Any] = {}
        for path, value in snap.items():
            if metric is not None and not self._telemetry_matches_metric(path, metric):
                continue
            metrics[path] = {"value": value, **self._telemetry_key(path)}
        return {
            "success": True,
            "process": process,
            "metric": metric,
            "count": len(metrics),
            "metrics": metrics,
        }

    def telemetry_history(
        self,
        path: str,
        limit: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Локальный кольцевой буфер истории метрики — 0 IPC (спарклайн без БД).

        История копится только для отслеживаемых суффиксов read-model
        (``DEFAULT_TRACKED_SUFFIXES``: fps/latency_ms/uptime/effective_hz/
        cycle_duration_ms). Глубже (час/день) — из БД-стока (вне контракта Task 2.3).

        Args:
            path: полный путь метрики (``processes.cam.state.fps``).
            limit: вернуть последние N точек (None → весь буфер, ≤ окна ~600).

        Returns:
            ``{"success": True, "path": ..., "process": ..., "worker": ...,
            "count": N, "points": [[ts, value], ...]}`` в хронологическом порядке.
            Нет буфера (путь не трекается / нет данных) → ``count=0``.
        """
        with self._telemetry_lock:
            points = self._telemetry_model.history(path)
        if limit is not None:
            # limit>0 → последние N; limit==0 → пусто («последние 0 точек»);
            # limit<0 (бессмыслица) → пусто. Нельзя points[-limit:]: при limit==0
            # это points[0:] = ВЕСЬ буфер.
            points = points[-limit:] if limit > 0 else []
        return {
            "success": True,
            "path": path,
            **self._telemetry_key(path),
            "count": len(points),
            "points": [[ts, val] for ts, val in points],
        }

    # ---- Tail логов (Ф1 Task 1.5: подписка level≥X → событийный канал driver'а) ----

    def log_tail(
        self,
        process: str,
        *,
        level: str = "ERROR",
        subscriber: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Подписаться на LogRecord'ы процесса с level ≥ ``level``.

        Процесс ставит router-push sink: записи ≥ level едут пушем на ``subscriber``
        (по умолчанию self.sender = адрес driver'а) через мост 1.1b и приходят в
        событийный канал — читаются через :meth:`events` / :meth:`subscribe` как
        сообщения с ``command == "log.record"`` (``data.record`` — сам LogRecord-dict).
        """
        args = {"subscriber": subscriber or self._sender, "level": level}
        res = _leaf_result(self.send_command(process, "log.tail.subscribe", args, timeout=timeout))
        self._register_subscription("log.tail.subscribe", process, args, res)
        return res

    def log_untail(
        self,
        process: str,
        *,
        subscriber: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Снять подписку на tail логов процесса (по адресу подписчика)."""
        args = {"subscriber": subscriber or self._sender}
        res = _leaf_result(self.send_command(process, "log.tail.unsubscribe", args, timeout=timeout))
        self._subscriptions.remove("log.tail.subscribe", process, args)
        return res

    # ---- Observability-tail (Task 2.1: live ЛОГИ+ОШИБКИ+СТАТИСТИКА одним хвостом) ----
    #
    # Богаче log_tail: тот несёт только LogRecord'ы (одна плоскость), а
    # observability.tail форвардит ВСЕ три плоскости наблюдаемости процесса
    # (drain log/stats из hub'а + write-through error/critical) адресным пушем
    # command="observability.record". Это тот же хвост, что активирует GUI
    # (ObservabilityTailActivator). Записи приходят в событийный канал driver'а —
    # классифицировать по kind помогает :meth:`observability_records`.

    def observability_tail(
        self,
        process: str,
        *,
        subscriber: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Подписаться на live-хвост наблюдаемости процесса (логи+ошибки+статистика).

        Ставит на процессе форвардер (drain log/stats) + error-tap'ы (write-through):
        каждая запись пушится ``targets=[subscriber]`` + ``queue_type="system"`` →
        мост 1.1b → событийный канал driver'а. Записи читаются через :meth:`events` /
        :meth:`subscribe` как сообщения с ``command == "observability.record"``:
        ``data.records`` (пачка из drain log/stats) ИЛИ ``data.record`` (одна запись
        error/critical). Каждая запись несёт ``kind`` ∈ {``log``, ``error``, ``stats``}
        — разложить по плоскостям помогает :meth:`observability_records`.

        Зеркало :meth:`log_tail`: ``subscriber`` по умолчанию = self.sender (адрес
        driver'а); намерение регистрируется в durable-реестре (переживает реконнект).
        Подписка идемпотентна по подписчику на стороне процесса.

        Args:
            process: имя процесса-источника (должен поддерживать observability-hub;
                процесс без него вернёт ``success=False`` — честно, не бросок).
            subscriber: адрес получателя пушей (по умолчанию адрес driver'а).
            timeout: таймаут ожидания подтверждения подписки.

        Returns:
            dict результата подписки (``success`` + детали процесса).
        """
        args = {"subscriber": subscriber or self._sender}
        res = _leaf_result(self.send_command(process, "observability.tail.subscribe", args, timeout=timeout))
        self._register_subscription("observability.tail.subscribe", process, args, res)
        return res

    def observability_untail(
        self,
        process: str,
        *,
        subscriber: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Снять подписку на live-хвост наблюдаемости процесса (зеркало :meth:`log_untail`).

        F1: форвардер наблюдаемости на процессе — per-subscriber (несколько
        подписчиков сосуществуют). Поэтому ``observability.tail.unsubscribe`` ОБЯЗАН
        нести ``subscriber`` на проводе — снять форвардер ТОЛЬКО driver'а, не задев
        GUI-хвост (раньше слался пустой payload → без per-subscriber-контракта это
        снесло бы хвост GUI). Тот же ``subscriber`` снимает durable-намерение.
        """
        identity = {"subscriber": subscriber or self._sender}
        res = _leaf_result(self.send_command(process, "observability.tail.unsubscribe", identity, timeout=timeout))
        self._subscriptions.remove("observability.tail.subscribe", process, identity)
        return res

    def observability_records(
        self,
        events: Optional[List[Dict[str, Any]]] = None,
        *,
        kind: Optional[str] = None,
        level: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Выбрать записи наблюдаемости из событий и (опц.) отфильтровать по плоскости/severity.

        Классификатор поверх :meth:`events`: отбирает сообщения
        ``command == "observability.record"``, разворачивает их полезную нагрузку
        (``data.records`` — пачка и/или ``data.record`` — одиночная запись) в ПЛОСКИЙ
        список записей и фильтрует по ``kind`` (плоскость) и ``level`` (severity).

        Классификация — ПО ФАКТУ доступного поля ``kind`` записи (нормализатор
        ``record_display`` проставляет ``kind`` ∈ {``log``, ``error``, ``stats``} каждой
        записи). Запись без ``kind`` при ``kind=None`` отдаётся как есть; при заданном
        фильтре — отбрасывается (сопоставить не с чем).

        F5: ``level`` — КЛИЕНТСКИЙ severity-фильтр (``observability.tail`` форвардит все
        severity без фильтра на проводе). Это и есть эффект ``tail_level`` из
        :meth:`watch_like_gui`: при активном watch ``level=None`` берёт объявленный
        ``tail_level`` дефолтом (раньше ``tail_level`` был пустышкой — нигде не срезал).
        Фильтр применяется ТОЛЬКО к записям с распознаваемым лог-severity
        (debug/info/warning/error/critical); записи с чужим severity (stats-метрики:
        gauge/counter) НЕ режутся log-порогом — плоскости независимы. Передай
        ``level="DEBUG"``, чтобы явно вернуть все severity даже при активном watch.

        Args:
            events: список событий для разбора. ``None`` → **дренирует** канал через
                :meth:`events` (деструктивно: прочие события — state.changed/log.record
                — при этом теряются). Для неразрушающего разбора передай снимок:
                ``recs = drv.observability_records(drv.events())`` — там останутся все
                события, а сюда придёт их копия.
            kind: плоскость-фильтр (``"log"`` | ``"error"`` | ``"stats"``); ``None`` —
                вернуть все плоскости.
            level: severity-порог (``"WARNING"`` и т.п.); ``None`` — дефолт watch
                (``tail_level``, если watch активен) либо без severity-фильтра.

        Returns:
            Плоский список record-dict'ов (display-вид: kind/process/module/ts/
            severity/message/extra) в порядке поступления.
        """
        # F5: дефолт severity-фильтра — объявленный tail_level активного watch.
        effective_level = level if level is not None else (self._watch_tail_level if self._watch_active else None)
        threshold = _LOG_SEVERITY_RANK.get(str(effective_level).lower()) if effective_level else None

        source = self.events() if events is None else events
        out: List[Dict[str, Any]] = []
        for msg in source:
            if not isinstance(msg, dict) or msg.get("command") != OBSERVABILITY_RECORD_COMMAND:
                continue
            data = msg.get("data")
            if not isinstance(data, dict):
                continue
            records: List[Dict[str, Any]] = []
            batch = data.get("records")
            if isinstance(batch, list):
                records.extend(r for r in batch if isinstance(r, dict))
            single = data.get("record")
            if isinstance(single, dict):
                records.append(single)
            for rec in records:
                if kind is not None and rec.get("kind") != kind:
                    continue
                if threshold is not None:
                    rank = _LOG_SEVERITY_RANK.get(str(rec.get("severity", "")).lower())
                    # Режем ТОЛЬКО распознанный лог-severity ниже порога; чужой severity
                    # (stats-метрики) и записи без severity — плоскость независима, пропускаем.
                    if rank is not None and rank < threshold:
                        continue
                out.append(rec)
        return out

    # ---- UI-tap (отладка фронтенда): кнопки/табы GUI → события ui.event ----

    def ui_tap(
        self,
        process: str = "gui",
        *,
        subscriber: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Подписаться на UI-события gui-процесса (нажатия кнопок, переключения табов).

        GUI ставит UiEventTap-пуш: события едут тем же маршрутом, что log-tail
        (мост 1.1b / relay 1.7), и приходят в событийный канал driver'а как
        сообщения с ``command == "ui.event"`` (``data.record`` — событие:
        kind=button|tab|ping, text, path, ts). Смоук цепочки — :meth:`ui_tap_ping`.
        """
        args = {"subscriber": subscriber or self._sender}
        res = _leaf_result(self.send_command(process, "ui.tap.subscribe", args, timeout=timeout))
        self._register_subscription("ui.tap.subscribe", process, args, res)
        return res

    def ui_untap(
        self,
        process: str = "gui",
        *,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Снять подписку на UI-события gui-процесса."""
        res = _leaf_result(self.send_command(process, "ui.tap.unsubscribe", {}, timeout=timeout))
        self._subscriptions.remove("ui.tap.subscribe", process)
        return res

    def ui_tap_ping(
        self,
        process: str = "gui",
        *,
        note: str = "ping",
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Синтетическое ui.event тем же путём доставки — проверка цепочки без клика."""
        return _leaf_result(self.send_command(process, "ui.tap.ping", {"note": note}, timeout=timeout))

    # ---- Debug-plane: полная наблюдаемость одним вызовом ----

    def debug_session(
        self,
        *,
        gui_process: str = "gui",
        logs_level: str = "WARNING",
        log_processes: Optional[List[str]] = None,
        state_pattern: str = "**",
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Включить отладочную плоскость одним вызовом (debug-plane v1).

        Жест+намерение (``ui_tap`` gui: клики/табы + команды GUI→бэкенд), эффект
        (``log_tail`` уровня ``logs_level`` на процессы ``log_processes``, по
        умолчанию — все из state-топологии, + ``state_subscribe(state_pattern)``).
        Всё приходит в ЕДИНУЮ очередь :meth:`events`: команды ``ui.event`` /
        ``log.record`` / ``state.changed``, упорядочивание — ts (+seq у ui.event).

        Возвращает сводку по каждому включённому источнику (best-effort: недоступный
        источник — честная запись об ошибке, остальные работают).
        """
        summary: Dict[str, Any] = {"ui": None, "logs": {}, "state": None}
        summary["ui"] = self.ui_tap(gui_process, timeout=timeout)

        procs = log_processes if log_processes is not None else self._discover_processes(timeout=timeout)
        for p in procs:
            summary["logs"][p] = self.log_tail(p, level=logs_level, timeout=timeout)

        summary["state"] = self.state_subscribe(state_pattern, timeout=timeout)
        summary["success"] = bool((summary["ui"] or {}).get("success") is not False)
        return summary

    def debug_stop(
        self,
        *,
        gui_process: str = "gui",
        log_processes: Optional[List[str]] = None,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Выключить отладочную плоскость: ui_untap + log_untail по процессам.

        Подписка state.subscribe снимается вместе с закрытием соединения driver'а
        (server-side привязана к подписчику) — отдельной команды не требует.
        """
        summary: Dict[str, Any] = {"ui": self.ui_untap(gui_process, timeout=timeout), "logs": {}}
        procs = log_processes if log_processes is not None else self._discover_processes(timeout=timeout)
        for p in procs:
            summary["logs"][p] = self.log_untail(p, timeout=timeout)
        return summary

    def _discover_processes(self, *, timeout: Optional[float] = None) -> List[str]:
        """Список процессов из state-топологии (общий для debug_session/debug_stop, Task 0.4)."""
        st = self.send_command("ProcessManager", "state.get_subtree", {"path": "processes"}, timeout=timeout)
        tree = unwrap(st, leaf=True)
        node = tree.get("subtree") or tree.get("value") or {}
        return sorted(node) if isinstance(node, dict) else []

    # ---- Подписка на состояние (state.subscribe → событийный канал) ----

    def state_subscribe(
        self,
        pattern: str,
        *,
        subscriber: Optional[str] = None,
        exclude_sources: Optional[List[str]] = None,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Подписаться на изменения state-дерева по glob-паттерну.

        Отправляет `state.subscribe` в ProcessManager (форма StateProxy.subscribe).
        После подтверждения сервер шлёт адресные push `state.changed` (targets=
        [subscriber], без request_id) — они приходят в событийный канал driver'а:
        читаются через events()/subscribe(). subscriber по умолчанию = self.sender
        (адрес, на который сервер направляет пуши). Возвращает result подписки
        (status + sub_id).
        """
        args = {
            "pattern": pattern,
            "subscriber": subscriber or self._sender,
            "exclude_sources": exclude_sources or [],
        }
        res = self.send_command("ProcessManager", "state.subscribe", args, timeout=timeout)
        self._register_subscription("state.subscribe", "ProcessManager", args, res)
        return res

    def state_unsubscribe(
        self,
        pattern: str,
        *,
        subscriber: Optional[str] = None,
        timeout: Optional[float] = None,  # noqa: ARG002 — симметрия сигнатур wrapper'ов
    ) -> Dict[str, Any]:
        """Явно снять подписку на state-паттерн (F2: обёртка, которой не было).

        Снимает durable-намерение ``state.subscribe`` этого паттерна из реестра — чтобы
        реконнект НЕ воскресил его через replay (главная и единственная задача: вернуть
        управляемость watch-профилем). Серверную подписку поштучно НЕ снимаем: сервер
        отписывает по ``sub_id`` (у нас его нет) либо ``state.unsubscribe_all`` по
        подписчику (снёс бы и НЕ-watch подписки того же driver'а — слишком широко).
        Серверная state-подписка освобождается закрытием соединения (как в
        :meth:`debug_stop`); durable-намерение — это то, что переживало бы реконнект.
        """
        sub = subscriber or self._sender
        self._subscriptions.remove("state.subscribe", "ProcessManager", {"pattern": pattern})
        return {"success": True, "pattern": pattern, "subscriber": sub}

    # ---- GUI-эквивалентный приёмный профиль (Task 2.2: watch_like_gui) ----

    def watch_like_gui(
        self,
        *,
        patterns: tuple[str, ...] = GUI_DEFAULT_PATTERNS,
        tail_level: str = "WARNING",
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Включить ВЕСЬ приёмный профиль GUI одной командой (state + observability-хвост).

        Одна команда даёт агенту ровно то, что получает GUI:

          - ``state.subscribe`` на каждый wildcard из ``patterns`` (по умолчанию
            :data:`GUI_DEFAULT_PATTERNS` — зеркало ``frontend/process.py``);
          - ``observability.tail`` на КАЖДЫЙ процесс из state-топологии
            (:meth:`_discover_processes`) — live логи+ошибки+статистика;
          - **авто-переподписку** observability-хвоста после авто-рестарта процесса
            (порт логики ``ObservabilityTailActivator``, см. ниже).

        Всё приходит в ЕДИНУЮ очередь :meth:`events`; записи наблюдаемости
        раскладывает по плоскостям :meth:`observability_records`. Кадры/SHM через
        сокет НЕ гоняются (Dict at Boundary) — вне контракта watch.

        Сводка best-effort (как у :meth:`debug_session`): недоступный источник —
        честная запись об ошибке, остальные работают. Повторный вызов при активном
        watch сначала делает :meth:`unwatch` (чистый рестарт профиля).

        **Авто-переподписка и thread-safety (главный риск задачи, п.5 ТЗ).**
        Триггер переподписки — громкое supervisor-событие
        ``processes.<name>.supervisor.event = "recovered"`` (публикуется по возврату
        heartbeat после авто-рестарта, ADR-PMM-015): авто-рестарт поднимает НОВУЮ
        инкарнацию процесса, её форвардер не подписан, а дедуп по имени переподписку
        блокировал бы. Слушатель ловит это в событийном канале и снимает дедуп.

        Слушатель исполняется в **reader-потоке** driver'а (колбэк :meth:`subscribe`).
        Из reader-потока НЕЛЬЗЯ звать :meth:`observability_tail` напрямую: она уходит
        в ``request()`` и блокируется в ``pending.event.wait()`` — но ответ на этот
        самый запрос дренирует ТОТ ЖЕ reader-поток (``_read_loop`` → ``_dispatch``),
        который сейчас заблокирован. Итог — request таймаутит (переподписка всегда
        падает) и на время таймаута встаёт вся доставка событий. Поэтому слушатель
        лишь КЛАДЁТ имя процесса в очередь намерений (:attr:`_resub_queue`), а
        отдельный applier-поток (:meth:`_resub_loop`) применяет переподписку на
        безопасном потоке — там ``request()`` блокируется штатно, reader свободен
        дренировать ответ. Идемпотентность subscribe сохраняется (дедуп-множество).

        Args:
            patterns: набор state-wildcard'ов (по умолчанию GUI-набор).
            tail_level: декларируемый порог логов. **Замечание:** observability.tail
                форвардит ВСЕ плоскости и severity без фильтра на проводе, поэтому
                уровень применяется на стороне клиента —
                ``observability_records(kind="error")`` и т.п. Возвращается в сводке
                как объявленное намерение (сервер его не срезает).
            timeout: таймаут каждой под-команды (и авто-переподписок).

        Returns:
            Сводка: ``{"state": {pattern: res}, "observability": {proc: res},
            "processes": [...], "tail_level": ..., "success": bool}``.
        """
        if self._watch_active:
            self.unwatch(timeout=timeout)

        summary: Dict[str, Any] = {
            "state": {},
            "observability": {},
            "processes": [],
            "tail_level": tail_level,
        }

        # F4: активируем watch-контур и регистрируем слушатель+applier ПЕРВЫМИ, ДО
        # первичных подписок. Раньше слушатель вешался ПОСЛЕДНИМ (после N×obs_tail до
        # 5с каждый) → supervisor-``recovered``, прилетевший в это окно, терялся и
        # процесс оставался без хвоста. Дедуп ``_watch_subscribed`` оптимистичен и
        # потокобезопасен (под ``_watch_lock``), поэтому ранний старт безопасен:
        # applier переподпишет идемпотентно, если listener опередит основной цикл.
        with self._watch_lock:
            self._watch_active = True
            self._watch_resub_timeout = timeout
            self._watch_subscribed = set()
            self._watch_patterns = tuple(patterns)  # запомнить фактический набор для unwatch
            self._watch_tail_level = tail_level
            self._resub_queue = queue.Queue()  # свежая очередь на поколение watch (F3: изоляция)
            q = self._resub_queue

        # Applier-поток намерений переподписки (безопасный поток для request()).
        self._resub_thread = threading.Thread(target=self._resub_loop, args=(q,), name="backend-ctl-resub", daemon=True)
        self._resub_thread.start()
        # Слушатель авто-переподписки на событийном канале (исполняется в reader-потоке).
        self._watch_listener = self.subscribe(self._on_watch_event)

        for pattern in patterns:
            summary["state"][pattern] = self.state_subscribe(pattern, timeout=timeout)

        procs = self._discover_processes(timeout=timeout)
        summary["processes"] = list(procs)

        for proc in procs:
            # F7: не тейлим собственный процесс driver'а (self._sender) — тейлить себя
            # бессмысленно (ObservabilityTailActivator у GUI тоже себя не подписывает).
            # gui-процесс НЕ исключаем: driver может его тейлить, но у него нет пилот-hub'а,
            # поэтому obs_tail(gui) честно вернёт success=False (reason: нет hub'а) — это
            # ОЖИДАЕМО, не ошибка; в сводку кладём как есть, без шумного «fail».
            if proc == self._sender:
                continue
            res = self.observability_tail(proc, timeout=timeout)
            summary["observability"][proc] = res
            # Дедуп: пометить процесс подписанным независимо от исхода (over-record —
            # безопаснее; recovered-триггер всё равно снимет пометку и переподпишет).
            with self._watch_lock:
                self._watch_subscribed.add(proc)

        # Успех: хотя бы одна state-подписка и хотя бы один obs-хвост не провалились
        # (best-effort — часть процессов может не поддерживать observability-hub).
        state_ok = any((r or {}).get("success") is not False for r in summary["state"].values())
        summary["success"] = bool(state_ok)
        return summary

    def unwatch(self, *, timeout: Optional[float] = None) -> Dict[str, Any]:
        """Выключить GUI-профиль: снять obs-хвосты + слушатель + applier-поток.

        Снимает ``observability.tail`` со всех процессов, на которые watch подписался,
        отключает слушатель авто-переподписки и останавливает applier-поток. Durable-
        намерения (``state.subscribe`` по watch-паттернам и obs-хвосты) вычищаются из
        реестра, чтобы будущий реконнект НЕ воскресил снятый профиль. Серверную
        state-подписку снимаем через :meth:`state_unsubscribe` (durable-намерение;
        серверная подписка освобождается закрытием соединения, как в :meth:`debug_stop`).

        F3 (гонка in-flight resub): applier может держать незавершённый
        ``observability_tail`` дольше join'а. Само-исцеление — в :meth:`_resub_loop`:
        по завершении resub'а applier перепроверяет ``_watch_active`` и, если watch уже
        снят, ОТМЕНЯЕТ свою переподписку (untail) — форвардер/намерение не воскресают
        независимо от тайминга join'а. Свежая очередь на поколение (:meth:`watch_like_gui`)
        изолирует стоп-sentinel от будущего watch (инвариант «один applier»).

        F2 (б, реконнект без восстановления контура): даже при ``was_active=False``
        всё равно чистим watch-намерения (obs-tail целиком + state.subscribe по
        GUI-паттернам fallback), чтобы «полу-durable» watch не воскрес молча.
        """
        with self._watch_lock:
            was_active = self._watch_active
            self._watch_active = False
            procs = sorted(self._watch_subscribed)
            self._watch_subscribed = set()
            listener = self._watch_listener
            self._watch_listener = None
            thread = self._resub_thread
            self._resub_thread = None
            # Снять ровно те паттерны, что включал watch_like_gui (не хардкод — кастомный
            # набор иначе утёк бы в реестре). Fallback на GUI-набор — только если контур
            # был потерян при реконнекте (was_active=False, паттерны не восстановлены).
            patterns = (
                self._watch_patterns if self._watch_patterns else (GUI_DEFAULT_PATTERNS if not was_active else ())
            )
            self._watch_patterns = ()
            resub_q = self._resub_queue

        if listener is not None:
            self.unsubscribe(listener)

        # Остановить applier-поток: sentinel в его (текущего поколения) очередь + join.
        if thread is not None:
            resub_q.put(None)
            thread.join(timeout=2.0)
        # Дренировать хвост очереди этого поколения (leftover-намерения не должны
        # применяться после снятия watch — applier их и так пропустит по guard'у).
        _drain_queue(resub_q)

        summary: Dict[str, Any] = {"observability": {}, "was_active": was_active}
        for proc in procs:
            summary["observability"][proc] = self.observability_untail(proc, timeout=timeout)

        # Снять durable state.subscribe watch-паттернов через явную обёртку.
        for pattern in patterns:
            self.state_unsubscribe(pattern, timeout=timeout)

        # F2 (б): подчистить ЛЮБЫЕ висящие obs-tail-намерения (watch-owned), если контур
        # был потерян и procs пуст — иначе полу-durable watch воскреснет при реконнекте.
        if not was_active and not procs:
            self._subscriptions.remove_by_command("observability.tail.subscribe")

        summary["success"] = True
        return summary

    @property
    def watch_resub_errors(self) -> int:
        """Сколько авто-переподписок хвоста завершились ошибкой (диагностика, Task 2.2)."""
        return self._watch_resub_errors

    def watch_manifest(self) -> Dict[str, Any]:
        """Снимок активного watch-профиля для переживания реконнекта (F2).

        MCP-сервер сохраняет манифест ДО сброса driver'а и после реконнекта передаёт
        его новому driver'у (:meth:`resume_watch`), чтобы восстановить watch-КОНТУР
        (слушатель авто-переподписки + applier), а не только durable-намерения. Раньше
        реконнект replay'ил намерения, но контур не поднимался → авто-resub был мёртв,
        а ``unwatch`` — no-op (профиль воскресал каждый реконнект).
        """
        with self._watch_lock:
            if not self._watch_active:
                return {"active": False}
            return {
                "active": True,
                "patterns": list(self._watch_patterns),
                "tail_level": self._watch_tail_level,
                "processes": sorted(self._watch_subscribed),
            }

    def resume_watch(self, manifest: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Восстановить watch-контур из манифеста ПОСЛЕ реконнекта (F2, парный к :meth:`watch_manifest`).

        Поднимает ТОЛЬКО клиентский контур (слушатель + applier + watch-состояние) БЕЗ
        повторных подписок: серверные ``state.subscribe``/``observability.tail`` уже
        восстановлены replay'ем durable-намерений (:meth:`replay_subscriptions`) на новом
        соединении. Двойной подписки нет; ``observability.tail`` идемпотентна на сервере.

        Нет активного watch в манифесте → no-op. Идемпотентно: если контур уже поднят
        (``_watch_active``) — сначала :meth:`unwatch`, чтобы не плодить второй applier.
        """
        if not manifest or not manifest.get("active"):
            return {"resumed": False}
        if self._watch_active:
            self.unwatch()

        patterns = tuple(manifest.get("patterns") or ())
        procs = list(manifest.get("processes") or [])
        with self._watch_lock:
            self._watch_active = True
            self._watch_patterns = patterns
            self._watch_tail_level = str(manifest.get("tail_level") or "WARNING")
            self._watch_subscribed = set(procs)
            self._watch_resub_timeout = None
            self._resub_queue = queue.Queue()
            q = self._resub_queue

        self._resub_thread = threading.Thread(target=self._resub_loop, args=(q,), name="backend-ctl-resub", daemon=True)
        self._resub_thread.start()
        self._watch_listener = self.subscribe(self._on_watch_event)
        return {"resumed": True, "processes": procs, "patterns": list(patterns)}

    def _on_watch_event(self, msg: Dict[str, Any]) -> None:
        """Слушатель событийного канала: ловит supervisor-recovered → намерение переподписки.

        Исполняется в reader-потоке — ТОЛЬКО кладёт имя процесса в очередь намерений
        (никаких блокирующих ``request()`` — см. :meth:`watch_like_gui`). Разбирает
        ``state.changed``-дельты: процесс, чей ``processes.<name>.supervisor.event``
        стал ``recovered``, переподписываем заново (новая инкарнация); процесс, ещё
        не подписанный (свежее появление в топологии), подписываем впервые — паритет
        с ``ObservabilityTailActivator.on_state_delta``.
        """
        if not isinstance(msg, dict) or msg.get("command") != "state.changed":
            return
        data = msg.get("data")
        if not isinstance(data, dict):
            return
        deltas = data.get("deltas")
        if not isinstance(deltas, list):
            return
        for delta in deltas:
            if not isinstance(delta, dict):
                continue
            path = delta.get("path") or ""
            if not path.startswith("processes."):
                continue
            parts = path.split(".")
            proc = parts[1] if len(parts) >= 2 else ""
            if not proc or proc == self._sender:
                continue  # F7: себя не тейлим (симметрично стартовому циклу watch_like_gui)
            recovered = path.endswith(".supervisor.event") and delta.get("new_value") == "recovered"
            with self._watch_lock:
                if not self._watch_active:
                    return
                if recovered:
                    # Новая инкарнация: снять дедуп, чтобы переподписать заново.
                    self._watch_subscribed.discard(proc)
                if proc in self._watch_subscribed:
                    continue
                # Пометить оптимистично (как ObservabilityTailActivator) и поставить
                # намерение — applier применит observability_tail на безопасном потоке.
                self._watch_subscribed.add(proc)
            self._resub_queue.put(proc)

    def _resub_loop(self, q: "queue.Queue[Optional[str]]") -> None:
        """Applier-поток намерений переподписки (безопасный поток для ``request()``).

        Дренирует очередь ``q`` СВОЕГО поколения (свежая на каждый watch — изоляция
        стоп-sentinel'ов, инвариант «один applier»): на каждое имя процесса делает
        :meth:`observability_tail` (тут блокировка в ``request()`` штатна — reader-
        поток свободен дренировать ответ). ``None`` — sentinel остановки (кладёт
        :meth:`unwatch`). ``task_done`` на каждый элемент — чтобы тесты могли
        детерминированно дождаться обработки через ``_resub_queue.join()``.

        F3 (гонка с unwatch), два слоя:
          1. Пред-guard: перед resub'ом проверяем ``_watch_active``; watch уже снят →
             пропускаем (не переподписываем на снятом профиле).
          2. Само-исцеление: после resub'а перепроверяем ``_watch_active``; если watch
             сняли, ПОКА наш ``observability_tail`` был in-flight (unwatch не дождался
             join'а) — немедленно ``observability_untail`` откатывает нашу переподписку
             (форвардер + durable-намерение), чтобы профиль не воскрес.
        """
        while True:
            proc = q.get()
            try:
                if proc is None:
                    return
                # Слой 1: watch снят до старта resub'а — не применяем.
                with self._watch_lock:
                    active = self._watch_active
                if not active:
                    continue
                try:
                    res = self.observability_tail(proc, timeout=self._watch_resub_timeout)
                    if isinstance(res, dict) and res.get("success") is False:
                        self._watch_resub_errors += 1
                except Exception:  # noqa: BLE001 — авто-переподписка best-effort, поток не роняем
                    self._watch_resub_errors += 1
                # Слой 2: watch сняли, пока resub был in-flight → откатить (само-исцеление).
                with self._watch_lock:
                    still_active = self._watch_active
                if not still_active:
                    try:
                        self.observability_untail(proc, timeout=self._watch_resub_timeout)
                    except Exception:  # noqa: BLE001 — откат best-effort
                        pass
            finally:
                q.task_done()
