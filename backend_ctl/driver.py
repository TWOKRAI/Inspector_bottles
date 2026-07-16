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
import socket
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Deque, Dict, List, Optional

from multiprocess_framework.modules.message_module import (
    build_command_message,
    build_system_command_message,
)

# Колбэк подписчика на события (получает распарсенный push-dict).
EventCallback = Callable[[Dict[str, Any]], None]

# Сентинел «под-секция не передана»: отличает отсутствие аргумента от явного None
# (для телеметрии ``publish=None`` — валидная команда «выключить gate», PC 3.2).
_UNSET: Any = object()


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


def _find_payload(res: Any, *keys: str) -> Dict[str, Any]:
    """Найти вложенный dict полезной нагрузки, спускаясь по ключу ``result``.

    Ответ команды может прийти как «плоским» (нужные ключи прямо в ``res``), так и
    завёрнутым оркестратором в ``{"success": ..., "result": {<payload>}}`` (иногда
    в два уровня). Спускаемся по ``result``, пока не встретим узел, содержащий любой
    из ожидаемых ``keys`` (например ``router_stats``/``queue_sizes``/``workers``).
    Если не нашли — возвращаем сам ``res`` (best-effort), чтобы парсер отдал дефолты.
    """
    node = res
    for _ in range(4):  # защита от бесконечного спуска на кривом ответе
        if not isinstance(node, dict):
            break
        if any(k in node for k in keys):
            return node
        node = node.get("result")
    return res if isinstance(res, dict) else {}


def _leaf_result(res: Any) -> Dict[str, Any]:
    """Спуститься по вложенным ``result`` до листовой полезной нагрузки хендлера.

    Ответ команды приезжает конвертом ``{success, result: {<payload хендлера>}}``
    (иногда в два уровня). Для команд, чьи значимые поля лежат В payload (config.reload
    → ``applied``, logger.sink.* → ``sink``), нужен именно лист, а не внешний конверт.
    Спускаемся по ``result``, пока следующий уровень — dict; иначе возвращаем текущий.
    """
    node = res if isinstance(res, dict) else {}
    for _ in range(4):  # защита от бесконечного спуска на кривом ответе
        nxt = node.get("result")
        if isinstance(nxt, dict):
            node = nxt
        else:
            break
    return node


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


class BackendDriver:
    """Тонкий driver: TCP-клиент + request-id matching + обёртки команд.

    Args:
        host: адрес SocketChannel хоста (по умолчанию localhost).
        port: TCP-порт (по умолчанию 8765, env BACKEND_CTL_PORT на стороне хоста).
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
        host: str = "127.0.0.1",
        port: int = 8765,
        *,
        sender: str = "backend_ctl",
        reply_to: str = "ProcessManager",
        default_timeout: float = 5.0,
        event_queue_maxlen: int = 1000,
    ) -> None:
        self._host = host
        self._port = port
        self._sender = sender
        self._reply_to = reply_to
        self._default_timeout = default_timeout

        self._sock: Optional[socket.socket] = None
        self._reader: Optional[threading.Thread] = None
        self._running = False
        self._pending: Dict[str, _Pending] = {}
        self._pending_lock = threading.Lock()
        self._write_lock = threading.Lock()

        # Событийный канал: reader-поток пишет, клиентский поток читает.
        # _events_cv охраняет и очередь, и список подписчиков; на нём же
        # блокируется events(timeout) в ожидании первого события.
        self._events: Deque[Dict[str, Any]] = deque(maxlen=event_queue_maxlen)
        self._events_cv = threading.Condition()
        self._subscribers: List[EventCallback] = []
        self._event_errors = 0  # счётчик исключений колбэков (диагностика)

    # ---- Соединение ----

    def connect(self, timeout: float = 5.0) -> None:
        """Подключиться к хосту и запустить читающий поток."""
        self._sock = socket.create_connection((self._host, self._port), timeout=timeout)
        self._sock.settimeout(0.5)
        self._running = True
        self._reader = threading.Thread(target=self._read_loop, name="backend-ctl-reader", daemon=True)
        self._reader.start()

    def close(self) -> None:
        """Остановить читающий поток и закрыть сокет."""
        self._running = False
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        if self._reader is not None:
            self._reader.join(timeout=1.0)
            self._reader = None
        # Разбудить всех ожидающих ответа (соединение закрыто).
        with self._pending_lock:
            pendings = list(self._pending.values())
            self._pending.clear()
        for p in pendings:
            p.event.set()
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
                return {"success": False, "error": "timeout", "request_id": cid}
            if pending.response is None:
                return {"success": False, "error": "connection closed", "request_id": cid}
            return pending.response.get("result", pending.response)
        finally:
            with self._pending_lock:
                self._pending.pop(cid, None)

    def _send_raw(self, message: Dict[str, Any]) -> None:
        line = (json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8")
        with self._write_lock:
            assert self._sock is not None
            self._sock.sendall(line)

    def _read_loop(self) -> None:
        buf = b""
        while self._running and self._sock is not None:
            try:
                chunk = self._sock.recv(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            if not chunk:
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
            if pending is not None:
                pending.response = msg
                pending.event.set()
                return
        # Нет request_id либо reply уже никто не ждёт → это событие.
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
        pm_name: str = "ProcessManager",
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Рантайм-переконфигурация телеметрии: адресно ИЛИ fan-out на всех детей.

        Две плоскости управления (план telemetry-publish-control), обе опциональны, но
        хотя бы одна обязательна (иначе — error-dict, ничего не шлётся):

          - ``publish`` → publisher-gate (что процесс СЧИТАЕТ/публикует и как часто).
            ``publish=None`` — валидная команда «выключить gate» (все метрики каждый тик).
            **Full-apply:** секция ЦЕЛИКОМ пересобирает gate (не дельта поверх) — не
            указанные метрики берут дефолты. Точечная правка ОДНОЙ метрики → :meth:`telemetry_set`.
          - ``throttle`` → центральный store-троттл оркестратора (rate-limit записи в дерево/IPC).

        Адресация по ``process``:
          - имя процесса → адресный ``telemetry.reconfigure`` (один адресат: его
            publisher-gate + троттл, если это оркестратор). Возвращает ``applied``
            {publish/throttle: применено ли} — виден «нет приёмника».
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

        if process in (None, "all", "*"):
            return _leaf_result(self.send_command(pm_name, "telemetry.broadcast", args, timeout=timeout))
        return _leaf_result(self.send_command(process, "telemetry.reconfigure", args, timeout=timeout))

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

        ``plane="publisher"`` (дефолт, главный рычаг) — строит
        ``publish={"metrics": {metric: {enabled?, interval_sec?}}}``. **ЗАМЕЧАНИЕ:** backend
        применяет ``publish`` full-apply (пересобирает gate из этой секции) — прочие метрики
        возьмут дефолты. Чтобы сохранить остальные override'ы, передавай ПОЛНУЮ секцию в
        :meth:`telemetry_reconfigure`.

        ``plane="throttle"`` — ``metric`` трактуется как glob-путь правила, ``interval_sec`` —
        min-интервал; строит ``throttle={metric: interval_sec}`` (адресат — центральный троттл
        оркестратора). **ОСТОРОЖНО (throttle тоже full-apply):** секция ``throttle`` применяется
        через ``set_rules`` — ПОЛНАЯ замена набора правил, а не точечная правка. Один вызов
        ``telemetry_set(plane="throttle")`` СНОСИТ все прочие правила (дефолтную IPC-страховку на
        ``latency_ms``/``effective_hz``/… из ``manager_setup._default_throttle_rules``). Чтобы
        поменять одно правило — передавай ПОЛНЫЙ набор через :meth:`telemetry_reconfigure`
        ``throttle={...}``. (Точечные ``ThrottleMiddleware.update_rule``/``remove_rule`` есть, но
        пока не проброшены в command-плоскость — кандидат на delta-apply, Фаза 4.)

        **ВАЖНО (две плоскости — потолок частоты):** центральный троттл (``throttle``) —
        независимая ступень rate-limit'а в оркестраторе поверх publisher-gate. Дефолтные
        правила (``manager_setup._default_throttle_rules``) режут ``fps``/``latency_ms``/
        ``effective_hz`` до 1 Гц. Поэтому УВЕЛИЧЕНИЕ частоты через publisher (например
        ``interval_sec=0.1``) НЕ поднимет эффективный поток выше центрального потолка — его
        надо ослабить/снять тем же вызовом с ``plane="throttle"``. Уменьшение частоты
        (реже потолка) работает через одну publisher-плоскость. Троттл = ceiling, publisher =
        floor-внутри-потолка.

        ``process`` — имя процесса ИЛИ ``"all"`` (fan-out через PM). Требуется ``enabled``
        и/или ``interval_sec`` (для throttle — обязателен ``interval_sec``), иначе error-dict.
        """
        if plane == "throttle":
            if interval_sec is _UNSET:
                return {"success": False, "error": "throttle-плоскость требует interval_sec (min-интервал правила)"}
            return self.telemetry_reconfigure(process, throttle={metric: interval_sec}, timeout=timeout)
        if plane != "publisher":
            return {"success": False, "error": f"неизвестная plane '{plane}' (publisher|throttle)"}

        rule: Dict[str, Any] = {}
        if enabled is not _UNSET:
            rule["enabled"] = bool(enabled)
        if interval_sec is not _UNSET:
            rule["interval_sec"] = interval_sec
        if not rule:
            return {"success": False, "error": "нужен enabled и/или interval_sec"}
        return self.telemetry_reconfigure(process, publish={"metrics": {metric: rule}}, timeout=timeout)

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
        return _leaf_result(
            self.send_command(
                process,
                "log.tail.subscribe",
                {"subscriber": subscriber or self._sender, "level": level},
                timeout=timeout,
            )
        )

    def log_untail(
        self,
        process: str,
        *,
        subscriber: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Снять подписку на tail логов процесса (по адресу подписчика)."""
        return _leaf_result(
            self.send_command(
                process,
                "log.tail.unsubscribe",
                {"subscriber": subscriber or self._sender},
                timeout=timeout,
            )
        )

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
        return _leaf_result(
            self.send_command(
                process,
                "ui.tap.subscribe",
                {"subscriber": subscriber or self._sender},
                timeout=timeout,
            )
        )

    def ui_untap(
        self,
        process: str = "gui",
        *,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Снять подписку на UI-события gui-процесса."""
        return _leaf_result(self.send_command(process, "ui.tap.unsubscribe", {}, timeout=timeout))

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

        procs = log_processes
        if procs is None:
            st = self.send_command("ProcessManager", "state.get_subtree", {"path": "processes"}, timeout=timeout)
            tree = _leaf_result(st)
            node = tree.get("subtree") or tree.get("value") or {}
            procs = sorted(node) if isinstance(node, dict) else []
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
        procs = log_processes
        if procs is None:
            st = self.send_command("ProcessManager", "state.get_subtree", {"path": "processes"}, timeout=timeout)
            tree = _leaf_result(st)
            node = tree.get("subtree") or tree.get("value") or {}
            procs = sorted(node) if isinstance(node, dict) else []
        for p in procs:
            summary["logs"][p] = self.log_untail(p, timeout=timeout)
        return summary

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
        return self.send_command(
            "ProcessManager",
            "state.subscribe",
            {
                "pattern": pattern,
                "subscriber": subscriber or self._sender,
                "exclude_sources": exclude_sources or [],
            },
            timeout=timeout,
        )
