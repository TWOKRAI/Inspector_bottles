# -*- coding: utf-8 -*-
"""
BackendDriver — socket-клиент к SocketChannel хоста (request-id matching).

Зеркало P0.5 над сокетом: пишет dict+"\n", читающий поток складывает ответы по
request_id в pending-слоты, request() блокирует до ответа/таймаута. Высокоуровневые
обёртки строят сообщения общими билдерами протокола (один источник правды с GUI).

Помимо reply-пути есть **событийный канал** (Ф1 Task 1.1 → B.1): push-сообщения без
request_id (или не матчащие ни один pending) — например `state.changed` — не
дропаются, а уходят в :class:`~backend_ctl.events.EventHub`: курсорные плоскости
(state/logs/errors/stats/telemetry/ui) с недеструктивным чтением `events_page()`
и видимой потерей + синхронные подписчики. Так `state.subscribe` через driver
работает end-to-end. Разделение потоков: reader-поток пишет события, клиентские
потоки читают их курсорами events_page()/subscribe() (legacy-дренаж `events()`
удалён в F.1).

Без бизнес-логики: driver только транспортирует router-сообщения. Вся интроспекция/
команды исполняются процессами системы, ответы едут обратно чистым RouterManager.
"""

from __future__ import annotations

import copy
import itertools
import logging
import socket
import threading
from collections import deque
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from multiprocess_framework.modules.telemetry_readmodel_module import (
    DEFAULT_TRACKED_SUFFIXES,
    TelemetryReadModel,
)
from multiprocess_framework.modules.message_module import (
    build_command_message,
    build_system_command_message,
)

from .endpoint_config import resolve_endpoint

# Форма ответа + типизированные результаты интроспекции вынесены в protocol.py (C.1).
# Реэкспорт здесь сохраняет обратную совместимость: `from backend_ctl.driver import
# Capabilities/_find_payload/…` продолжает работать у существующих потребителей.
from .protocol import (  # noqa: F401 — re-export для back-compat шима
    Capabilities,
    MemoryStats,
    ProcessCapabilities,
    QueueDepths,
    RouterStats,
    WorkerStatus,
    _find_payload,
    _leaf_result,
    unwrap,
)
from .conditions import DEFAULT_AWAIT_TIMEOUT, await_condition as _await_condition
from .overview import system_overview as _system_overview
from .subscriptions import _SubscriptionRegistry
from .events import (  # noqa: F401 — EventCallback/OBSERVABILITY_RECORD_COMMAND re-export
    _EventChannelMixin,
    EventCallback,
    EventHub,
    MISSING_MARKER,
    OBSERVABILITY_RECORD_COMMAND,
    extract_observability_records,
    iter_state_deltas,
    page_with_reset_retry,
)
from .transport import _TransportMixin, _Pending  # noqa: F401 — _Pending re-export для тестов
from .watch import WatchController, GUI_DEFAULT_PATTERNS  # noqa: F401 — GUI_DEFAULT_PATTERNS re-export

# Логгер клиента: reader-поток — daemon, его необработанное исключение уходит только
# в stderr-трейсбек; обрыв соединения логируем явно (A.3), чтобы причина «reader молча
# умер» была видима, а не терялась.
_log = logging.getLogger(__name__)

# Сентинел «под-секция не передана»: отличает отсутствие аргумента от явного None
# (для телеметрии ``publish=None`` — валидная команда «выключить gate», PC 3.2).
_UNSET: Any = object()

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


@dataclass
class _PendingCommit:
    """Ожидающая подтверждения запись регистра (D.5, commit-confirmed).

    Клиентский предохранитель по аналогии с Juniper ``commit confirmed``: пока не
    вызван :meth:`BackendDriver.register_confirm`, армированный таймер восстановит
    ``pre_value`` (или снимет запись, если поля до записи не было). ``had_field``
    отличает «поле существовало, откатываем к прежнему значению» от «поля не было —
    откатывать нечего, только разоружить».
    """

    commit_id: str
    process: str
    register: str
    field: str
    pre_value: Any
    had_field: bool
    timer: "threading.Timer"


class BackendDriver(_TransportMixin, _EventChannelMixin):
    """Тонкий driver: TCP-клиент + request-id matching + обёртки команд.

    Args:
        host: адрес SocketChannel хоста; ``None`` → env ``BACKEND_CTL_HOST`` → localhost.
        port: TCP-порт; ``None`` → env ``BACKEND_CTL_PORT`` → ``DEFAULT_PORT`` (8765).
            Резолв через ``resolve_endpoint`` — клиент читает те же env, что сервер.
        sender: имя отправителя в router-сообщениях.
        reply_to: адрес ответа. Driver не в queue_registry, ответ физически приходит
            в очередь ProcessManager (где живёт сокет) → reply_to="ProcessManager".
        default_timeout: таймаут request() по умолчанию.
        event_queue_maxlen: ёмкость КАЖДОГО кольца событий (arrival + плоскости
            EventHub). При переполнении вытесняются самые старые — память не
            течёт, даже если события никто не вычитывает; курсорный читатель
            видит потерю в поле ``dropped`` (B.1).
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

        # session-identity (D.1): назначается в connect() (per-connection). До connect
        # _subscriber падает на плоский _sender (back-compat: не-connected unit-тесты и
        # broadcast-режим сервера). После connect — dotted "<sender>.<session>":
        # дефолт получателя push'ей, изолирующий driver'ы на push-плоскости.
        self._session: Optional[str] = None
        self._subscriber: str = sender

        self._sock: Optional[socket.socket] = None
        self._reader: Optional[threading.Thread] = None
        self._running = False
        self._pending: Dict[str, _Pending] = {}
        self._pending_lock = threading.Lock()
        self._write_lock = threading.Lock()

        # Task 2.3: приватные курсоры инструментов (_events_tool_cursor, _obs_records_cursor)
        # читаются, продвигаются и записываются НЕ атомарно, а tools/call идут в параллельных
        # потоках SDK. Без лока два вызова читают один курсор и оба получают одну страницу —
        # события дублируются, а часть теряется (курсор перезаписывается младшим значением).
        self._tool_cursor_lock = threading.Lock()

        # Task 1.1: неожиданная смерть соединения (сервер закрыл сокет / OSError в reader'е)
        # в отличие от намеренного close(). Ставит ТОЛЬКО reader-поток; request() по нему
        # поднимает BackendUnavailable → срабатывает reconnect-аппарат D.1.
        self._conn_lost: bool = False
        self._conn_lost_reason: str = ""

        # Карантин таймаутнутых request_id (Task 0.2): request() при таймауте кладёт
        # сюда cid → срок годности; поздний ответ, пришедший ПОСЛЕ таймаута, dispatcher
        # опознаёт по этому множеству и дропает (иначе всплыл бы псевдо-событием).
        # TTL-purge ленивый — множество не растёт бесконечно. Под _pending_lock.
        self._timed_out: Dict[str, float] = {}
        self._late_replies = 0  # счётчик дропнутых поздних ответов (диагностика)

        # Durable-намерения подписки (Task 0.3): чтобы реконнект MCP-сервера мог
        # повторить подписки, а не потерять их молча. Заполняется subscribe-обёртками.
        self._subscriptions = _SubscriptionRegistry()

        # Событийный канал (B.1): EventHub — курсорные плоскости + подписчики.
        # reader-поток пишет (emit), клиентские потоки читают курсорами (events_page,
        # недеструктивно — единственный публичный способ с F.1, legacy-дренаж events()
        # удалён). Предикат alive — часть контракта hub'а для будущих блокирующих
        # читателей поверх ``_cv``.
        self._hub = EventHub(maxlen=event_queue_maxlen, alive=lambda: self._running or self._reader is not None)

        # F.1: приватный курсор для наблюдательного дефолта observability_records(events=None) —
        # «новое с прошлого вызова» поверх events_page(all), НЕ конкурирует с курсорами
        # других читателей (свой, привязанный к этому driver'у).
        self._obs_records_cursor: Optional[str] = None

        # GUI-эквивалентный watch (Task 2.2): авто-переподписка observability-хвоста
        # после авто-рестарта. Стейт-машина ВЫНЕСЕНА в WatchController (C.1) — она
        # владеет своими ~15 полями и держит back-ref на driver для команд; driver-
        # обёртки (watch_like_gui/unwatch/…) лишь делегируют. close() гасит applier
        # через self._watch.stop().
        self._watch = WatchController(self)

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
        # Провенанс нуля: count=0 у snapshot/history сам по себе не отличает «дельт не
        # было» от «подписки не было». Счётчик — под тем же локом, что и ingest.
        self._telemetry_ingested_total = 0
        self.subscribe(self._ingest_state_changed)

        # commit-confirmed регистры (D.5): армированные, но ещё не подтверждённые
        # записи. Каждая держит threading.Timer, который восстановит pre-image, если
        # register_confirm() не вызван за confirm_within сек (клиентский предохранитель
        # для безопасных экспериментов — аналог Juniper `commit confirmed`). Таймеры
        # снимаются в close() (driver уходит → откатывать по мёртвому сокету нечем).
        self._pending_commits: Dict[str, _PendingCommit] = {}
        self._pending_commits_lock = threading.Lock()
        self._commit_counter = itertools.count(1)
        # Исходы авто-откатов (D.5): таймер бьёт в фоновом потоке, синхронного возврата
        # агенту нет — фиксируем результат каждого срабатывания сюда (ограниченное
        # кольцо), чтобы register_confirm/register_rollback_log могли ответить «что
        # случилось с этим commit_id». Под _pending_commits_lock.
        self._rollback_journal: "deque[Dict[str, Any]]" = deque(maxlen=64)

    # ---- Соединение ----

    @property
    def host(self) -> str:
        """Адрес endpoint'а, к которому подключён driver (публичный аксессор, Task 0.4)."""
        return self._host

    @property
    def port(self) -> int:
        """TCP-порт endpoint'а (публичный аксессор вместо приватного _port, Task 0.4)."""
        return self._port

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
        """Загрузить намерения в этот driver (после реконнекта).

        subscriber durable-намерения ПЕРЕ-НАЦЕЛИВАЕТСЯ на текущую сессию ЗДЕСЬ, при
        загрузке (D.1): реконнект создаёт driver с новым session, и намерение старой
        сессии (``<sender>.<old_sid>``) иначе осело бы в реестре с ключом по старому
        subscriber (``_SubscriptionRegistry._key`` идентифицирует log/ui/obs-намерение
        ПО subscriber). Тогда последующий ``*_untail`` (снимает по ТЕКУЩЕМУ subscriber)
        не нашёл бы намерение → снятая подписка воскресала бы на следующем реконнекте.
        Ретаргет на import держит ключ реестра согласованным с текущим subscriber.
        """
        retargeted = [{**it, "args": self._retarget_subscriber(it.get("args") or {})} for it in (intents or [])]
        self._subscriptions.load(retargeted)

    def _retarget_subscriber(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Пере-нацелить subscriber durable-намерения на ТЕКУЩУЮ сессию (D.1).

        Реконнект создаёт driver с новым session → dotted-subscriber старой сессии
        (``<sender>.<old_sid>``) при session_isolation ON адресовал бы push мёртвому
        соединению (канал → «session not connected»). Переписываем СВОЙ subscriber
        (плоский ``<sender>`` или dotted той же семьи) на актуальный ``self._subscriber``;
        чужой/явный subscriber (напр. "watcher") не трогаем. При OFF безвредно.
        """
        sub = args.get("subscriber")
        if isinstance(sub, str) and (sub == self._sender or sub.startswith(self._sender + ".")):
            if sub != self._subscriber:
                return {**args, "subscriber": self._subscriber}
        return args

    def replay_subscriptions(self) -> List[Dict[str, Any]]:
        """Повторить все записанные подписки на текущем соединении.

        Зовётся после реконнекта: восстанавливает поток событий, который иначе
        молча оборвался бы. Идёт напрямую через send_command (не через обёртки),
        поэтому не пере-регистрирует намерения. subscriber уже пере-нацелен на
        текущую сессию при :meth:`import_subscriptions`, поэтому реестр и отправка
        согласованы. Возвращает список ``{command, target, success}`` для отчёта агенту.
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

    def unsubscribe_all(self, *, timeout: Optional[float] = None) -> List[Dict[str, Any]]:
        """Снять ВСЕ durable-подписки на бэкенде, пока сокет ещё жив (D.2 §5.2, долг D.1 §12).

        Обход снимка реестра намерений (:meth:`_SubscriptionRegistry.export`) → снимающая
        команда на каждое, через существующие обёртки (та же адресная семантика, что и
        ручное снятие: ui.tap → пустой payload, log/obs → по subscriber). ``state.subscribe``
        освобождается закрытием сокета (сервер-команды снятия по subscriber нет) → снимаем
        только локальное намерение. Best-effort: бэкенд мог умереть — исключения глушатся
        (сокет всё равно закрывается следом). Итерируем СНИМОК, обёртки мутируют реестр —
        безопасно. Возвращает отчёт ``{command, target, success}`` (для лога/пина).
        """
        results: List[Dict[str, Any]] = []
        for it in self._subscriptions.export():
            command = it.get("command")
            target = it.get("target") or ""
            args = it.get("args") or {}
            subscriber = args.get("subscriber")
            ok = True
            try:
                if command == "log.tail.subscribe":
                    self.log_untail(target, subscriber=subscriber, timeout=timeout)
                elif command == "observability.tail.subscribe":
                    self.observability_untail(target, subscriber=subscriber, timeout=timeout)
                elif command == "ui.tap.subscribe":
                    self.ui_untap(target, timeout=timeout)
                elif command == "state.subscribe":
                    self.state_unsubscribe(args.get("pattern", ""), subscriber=subscriber, timeout=timeout)
                else:
                    continue  # неизвестное намерение — не трогаем
            except Exception:  # noqa: BLE001 — best-effort перед закрытием сокета
                ok = False
            results.append({"command": command, "target": target, "success": ok})
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

    def supervision_status(
        self,
        process: Optional[str] = None,
        *,
        pm_name: str = "ProcessManager",
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Supervision-снимок (D.1b): epoch топологии + per-process incarnation,
        restart_count, last_exit, status. ``process`` фильтрует один процесс.

        Сырой dict (Dict at Boundary). incarnation растёт на каждое пересоздание
        очередей процесса → смена incarnation = пересечён рестарт (маркер «до/после»
        для fencing-token и курсорной плоскости B.1).
        """
        args = {"process": process} if process else {}
        return self.send_command(pm_name, "supervision.status", args, timeout=timeout)

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

    def _read_registers(self, process: str, *, timeout: Optional[float] = None) -> Dict[str, Any]:
        """Регистры процесса как ``{register: {field: value}}`` (один readback-хелпер).

        Общий разбор ответа ``introspect.registers`` (снимает конверт ``{success,
        result: …}`` через ``_find_payload``) для verify-probe, snapshot и restore —
        чтобы форма ответа парсилась в одном месте.
        """
        res = self.introspect_registers(process, timeout=timeout)
        payload = _find_payload(res, "registers")
        registers = payload.get("registers") if isinstance(payload, dict) else None
        return registers if isinstance(registers, dict) else {}

    def _topology_process_names(
        self,
        *,
        pm_name: str = "ProcessManager",
        timeout: Optional[float] = None,
    ) -> List[str]:
        """Список процессов системы одним запросом карточки PM (без fan-out).

        Берёт только ``processes``-топологию из ``introspect.capabilities`` PM — не
        зовёт :meth:`capabilities` (та вдобавок опрашивает карточку КАЖДОГО процесса,
        что для перечисления имён избыточно). Возвращает PM + детей.
        """
        pm_res = self.introspect_capabilities(pm_name, timeout=timeout)
        payload = _find_payload(pm_res, "processes", "commands")
        topology = payload.get("processes") if isinstance(payload, dict) else None
        children = sorted(topology) if isinstance(topology, dict) else []
        return [pm_name, *children]

    def set_register(
        self,
        process: str,
        register: str,
        field: str,
        value: Any,
        *,
        confirm_within: Optional[float] = None,
        **kw: Any,
    ) -> Dict[str, Any]:
        """Записать значение регистра в живой процесс (live field-write).

        Ключи data — канонический контракт ``register_update`` (тот же, что шлёт GUI
        через routing_map/CommandSender): ``{"register", "field", "value"}``.
        Исторический баг: driver слал ``plugin_name`` — обработчик оркестратора молча
        выходил, запись была no-op (найдено verify-probe Ф1.6). Имя регистра обычно
        совпадает с plugin_name (регистр на плагин).

        ``confirm_within=N`` (D.5) переводит запись в режим *commit-confirmed*: перед
        записью снимается pre-image поля, а после — readback-подтверждение (иначе
        молчаливый no-op не вооружает таймер) и армируется таймер, который через ``N``
        секунд восстановит прежнее значение, если не вызван :meth:`register_confirm` с
        вернувшимся ``commit_id``. Аналог Juniper ``commit confirmed`` — безопасный
        эксперимент с гарантированным откатом. **Ограничение:** предохранитель живёт
        только в пределах этой driver-сессии — ``close()``/реконнект снимает таймер, и
        неподтверждённая запись остаётся применённой (ответ несёт ``session_scoped``).
        """
        if confirm_within is not None:
            return self._set_register_confirmed(process, register, field, value, float(confirm_within), **kw)
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
        registers = self._read_registers(process, timeout=timeout)
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

    # ---- Snapshot / restore регистров (D.5): гарантированный откат эксперимента ----

    def register_snapshot(
        self,
        process: Optional[str] = None,
        *,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Снять снимок регистров для последующего :meth:`register_restore` (D.5).

        ``process`` задан — снимок одного процесса; опущен — снимок всех процессов
        системы (топология одним запросом карточки PM, без per-process fan-out).
        Форма всегда единообразна::

            {"processes": {proc: {register: {field: value}}}}

        Значения — глубокие копии (отвязаны от живого read-model), поэтому снимок
        переживает последующие правки. Аналог NETCONF candidate-config / running snapshot.
        """
        if process is not None:
            targets = [process]
        else:
            targets = self._topology_process_names(timeout=timeout)
        processes: Dict[str, Dict[str, Any]] = {}
        for name in targets:
            registers = self._read_registers(name, timeout=timeout)
            processes[name] = {
                reg: copy.deepcopy(fields) for reg, fields in registers.items() if isinstance(fields, dict)
            }
        return {"processes": processes}

    def register_restore(
        self,
        snapshot: Dict[str, Any],
        *,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Восстановить регистры из снимка :meth:`register_snapshot` (D.5).

        Для каждого процесса: readback → пишет ТОЛЬКО дрейфнувшие поля (уже-верные и
        неизменившиеся read-only не трогаются — меньше лишних write и меньше шума от
        полей, которые всё равно совпадают), затем сверяет свежим readback'ом. Не
        доверяет ack'ам записи (как verify-probe). Возвращает ``success`` (все поля
        снимка совпали), ``written`` (реально изменённые), ``skipped`` (уже верные),
        ``verified`` (доведённые до снимка) и ``mismatches``.

        Замечание: поля с живым/вычисляемым значением (счётчики, timestamps), успевшие
        измениться после снимка, попадут в ``mismatches`` — их «восстановить» нельзя, и
        это честный сигнал, а не сбой самого restore.
        """
        processes = snapshot.get("processes") if isinstance(snapshot, dict) else None
        if not isinstance(processes, dict):
            return {"success": False, "error": "снимок без ключа 'processes' (ожидается форма register_snapshot)"}

        written = 0
        total = 0
        mismatches: List[Dict[str, Any]] = []
        for proc, registers in processes.items():
            if not isinstance(registers, dict):
                continue
            current = self._read_registers(proc, timeout=timeout)  # readback ДО записи
            wrote_this_proc = False
            for reg, fields in registers.items():
                if not isinstance(fields, dict):
                    continue
                creg = current.get(reg)
                for field, value in fields.items():
                    total += 1
                    cur = creg.get(field) if isinstance(creg, dict) else None
                    if cur != value:  # пишем только то, что дрейфнуло
                        self.set_register(proc, reg, field, value, timeout=timeout)
                        written += 1
                        wrote_this_proc = True

            # Verify: свежий readback только если что-то писали (иначе current актуален).
            verify_src = self._read_registers(proc, timeout=timeout) if wrote_this_proc else current
            for reg, fields in registers.items():
                if not isinstance(fields, dict):
                    continue
                vreg = verify_src.get(reg)
                for field, value in fields.items():
                    got = vreg.get(field) if isinstance(vreg, dict) else None
                    if got != value:
                        mismatches.append(
                            {"process": proc, "register": reg, "field": field, "expected": value, "actual": got}
                        )
        return {
            "success": not mismatches,
            "written": written,
            "skipped": total - written,
            "verified": total - len(mismatches),
            "mismatches": mismatches,
        }

    # ---- commit-confirmed запись регистра (D.5): авто-откат без подтверждения ----

    def _set_register_confirmed(
        self,
        process: str,
        register: str,
        field: str,
        value: Any,
        confirm_within: float,
        **kw: Any,
    ) -> Dict[str, Any]:
        """Ядро режима ``set_register(confirm_within=N)`` — см. :meth:`set_register`."""
        # pre-image ДО записи: к нему откатимся, если поле уже существовало.
        registers = self._read_registers(process, timeout=kw.get("timeout"))
        reg = registers.get(register)
        had_field = isinstance(reg, dict) and field in reg
        pre_value = copy.deepcopy(reg[field]) if had_field else None

        ack = self.send_command(
            process,
            "register_update",
            {"register": register, "field": field, "value": value},
            **kw,
        )
        if self._looks_failed(ack):
            # Запись явно провалилась — таймер отката не армируем (откатывать нечего).
            return {
                "success": False,
                "pending": False,
                "error": "запись регистра провалилась — commit-confirmed не вооружён",
                "process": process,
                "register": register,
                "field": field,
                "ack": ack,
            }

        # Readback-подтверждение ДО арминга (не доверяем ack'у, как verify-probe Ф1.6):
        # если поля нет в снимке после записи — это молчаливый no-op (опечатка в имени
        # регистра/поля, отвал приёмника). Армировать таймер отката тогда — ложная
        # уверенность: откатывать нечего, а агент верит, что вооружён. Значение может
        # НЕ совпасть с value при легитимной Pydantic-коэрции — тогда verified=False,
        # но поле есть → запись применилась, откат к pre_value корректен.
        post = self._read_registers(process, timeout=kw.get("timeout"))
        preg = post.get(register)
        field_present = isinstance(preg, dict) and field in preg
        actual = preg.get(field) if field_present else None
        if not field_present:
            return {
                "success": False,
                "pending": False,
                "verified": False,
                "error": "запись не подтверждена readback'ом (нет регистра/поля?) — commit-confirmed не вооружён",
                "process": process,
                "register": register,
                "field": field,
                "expected": value,
                "actual": actual,
                "had_field": had_field,
                "ack": ack,
            }

        commit_id = f"{process}:{register}.{field}#{next(self._commit_counter)}"
        timer = threading.Timer(confirm_within, self._auto_rollback, args=(commit_id,))
        timer.daemon = True
        pc = _PendingCommit(commit_id, process, register, field, pre_value, had_field, timer)
        with self._pending_commits_lock:
            self._pending_commits[commit_id] = pc
        timer.start()
        return {
            "success": True,
            "pending": True,
            "verified": actual == value,
            "commit_id": commit_id,
            "process": process,
            "register": register,
            "field": field,
            "value": value,
            "actual": actual,
            "pre_value": pre_value,
            "had_field": had_field,
            "confirm_within": confirm_within,
            # Предохранитель живёт только в пределах ЭТОЙ driver-сессии: close()/реконнект
            # (DriverSession.reset) снимает таймер, и неподтверждённая запись остаётся
            # применённой. Не полагаться на авто-откат через границу реконнекта.
            "session_scoped": True,
            "ack": ack,
        }

    def register_confirm(self, commit_id: str) -> Dict[str, Any]:
        """Подтвердить commit-confirmed запись (D.5): снять таймер авто-отката.

        После подтверждения значение остаётся навсегда. Если ``commit_id`` неизвестен —
        ``success=False`` со списком ещё ожидающих ``known``; если он уже откатился по
        таймауту, из журнала подставляется ``rolled_back`` (исход отката), чтобы
        «опоздавший» confirm не гадал, что случилось.
        """
        with self._pending_commits_lock:
            pc = self._pending_commits.pop(commit_id, None)
            known = sorted(self._pending_commits)
            prior = None
            if pc is None:
                prior = next((e for e in reversed(self._rollback_journal) if e["commit_id"] == commit_id), None)
        if pc is None:
            res = {
                "success": False,
                "commit_id": commit_id,
                "error": "нет ожидающего commit-confirmed (уже подтверждён, откачен или неизвестен)",
                "known": known,
            }
            if prior is not None:
                res["rolled_back"] = prior  # уже откатился по таймауту — вот исход
            return res
        pc.timer.cancel()
        return {
            "success": True,
            "commit_id": commit_id,
            "confirmed": True,
            "process": pc.process,
            "register": pc.register,
            "field": pc.field,
        }

    def _auto_rollback(self, commit_id: str) -> None:
        """Callback таймера: восстановить pre-image, если запись не подтверждена.

        Атомарный ``pop`` под локом — арбитр гонки с :meth:`register_confirm`: кто
        первым забрал запись, тот и действует (второй увидит ``None`` и выйдет). Исход
        (ok/failed/noop) пишется в журнал — иначе провал отката в фоновом потоке был бы
        невидим агенту (он вызывал в расчёте на откат). Проверяем и ack (обрыв/таймаут
        возвращают error-dict, а не исключение), и исключение.
        """
        with self._pending_commits_lock:
            pc = self._pending_commits.pop(commit_id, None)
        if pc is None:
            return
        if not pc.had_field:
            # Поля до записи не существовало — откатывать нечего, только разоружаем.
            self._record_rollback(pc, "noop")
            return
        try:
            ack = self.set_register(pc.process, pc.register, pc.field, pc.pre_value)
        except Exception as exc:  # noqa: BLE001 — таймер в daemon-потоке, исключение иначе теряется
            _log.exception("commit-confirmed авто-откат %s не удался", commit_id)
            self._record_rollback(pc, "failed", error=str(exc))
            return
        if self._looks_failed(ack):
            _log.warning("commit-confirmed авто-откат %s: запись отклонена бэкендом (%s)", commit_id, ack)
            self._record_rollback(pc, "failed", error=ack)
        else:
            self._record_rollback(pc, "ok")

    def _record_rollback(self, pc: _PendingCommit, outcome: str, *, error: Any = None) -> None:
        """Зафиксировать исход авто-отката в кольце журнала (под локом)."""
        entry: Dict[str, Any] = {
            "commit_id": pc.commit_id,
            "process": pc.process,
            "register": pc.register,
            "field": pc.field,
            "outcome": outcome,
        }
        if error is not None:
            entry["error"] = error
        with self._pending_commits_lock:
            self._rollback_journal.append(entry)

    def register_rollback_log(self, *, limit: Optional[int] = None) -> Dict[str, Any]:
        """Журнал исходов авто-откатов этой driver-сессии (D.5, новейшие последними).

        Позволяет агенту, армировавшему commit-confirmed и не подтвердившему его,
        узнать, ЧЕМ закончился откат: ``outcome`` = ``ok`` / ``failed`` (+``error``) /
        ``noop`` (поля не было, откатывать нечего). Кольцо на 64 записи.
        """
        with self._pending_commits_lock:
            entries = list(self._rollback_journal)
        if limit is not None:
            # limit>0 → последние N; limit==0 → пусто («последние 0 записей»);
            # limit<0 (бессмыслица) → пусто. Нельзя entries[-limit:]: при limit==0
            # это entries[0:], то есть ВЕСЬ журнал вместо пустого (зеркало контракта
            # telemetry_history — там та же ловушка falsy-slice уже закрыта).
            entries = entries[-limit:] if limit > 0 else []
        return {"success": True, "entries": entries}

    def _cancel_all_pending_commits(self) -> None:
        """Снять все армированные таймеры отката (вызывается из close())."""
        with self._pending_commits_lock:
            pcs = list(self._pending_commits.values())
            self._pending_commits.clear()
        for pc in pcs:
            pc.timer.cancel()

    def close(self) -> None:
        """Закрыть driver: сперва снять таймеры commit-confirmed, затем транспорт.

        Driver уходит — откатывать по закрывающемуся сокету нечем (и не нужно: авто-
        откат это клиентский предохранитель на время жизни сессии). Неподтверждённые
        записи остаются применёнными; таймеры снимаются, чтобы не бить по мёртвому сокету.
        """
        self._cancel_all_pending_commits()
        super().close()

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

        **Имя сверяемо (BCTL-ADR-007):** если сервер отчитался, что publish-
        часть команды не дошла ни до одного адресата (``publish.reached == 0`` либо
        ``publish.target_count == 0``), ответ дополняется клиентским ``hint`` — вероятная
        причина: опечатка в имени процесса/метрики, либо процесс не жив. Консервативно:
        только маркировка, ``success`` и остальная форма ответа не трогаются (см.
        :meth:`_flag_unreached_metric`).
        """
        if plane == "throttle":
            if interval_sec is _UNSET:
                return {"success": False, "error": "throttle-плоскость требует interval_sec (min-интервал правила)"}
            res = self.telemetry_reconfigure(process, throttle={metric: interval_sec}, mode="merge", timeout=timeout)
            return self._flag_unreached_metric(res, process, metric)
        if plane != "publisher":
            return {"success": False, "error": f"неизвестная plane '{plane}' (publisher|throttle)"}

        rule: Dict[str, Any] = {}
        if enabled is not _UNSET:
            rule["enabled"] = bool(enabled)
        if interval_sec is not _UNSET:
            rule["interval_sec"] = interval_sec
        if not rule:
            return {"success": False, "error": "нужен enabled и/или interval_sec"}
        res = self.telemetry_reconfigure(process, publish={"metrics": {metric: rule}}, mode="merge", timeout=timeout)
        return self._flag_unreached_metric(res, process, metric)

    @staticmethod
    def _flag_unreached_metric(res: Dict[str, Any], process: str, metric: str) -> Dict[str, Any]:
        """Клиентская подсказка при ``publish.reached == 0`` / ``target_count == 0`` (BCTL-ADR-007).

        Консервативно — только МАРКИРУЕТ (мутирует и возвращает тот же ``res``): ``success``
        и остальная форма ответа не меняются, никакого нового отказа не вводится. Сервер
        уже даёт честный охват доставки (``reached``/``target_count`` — ADR-PM-017), здесь
        только клиентский перевод «0 из N» в подсказку «проверь имя».

        Throttle-плоскость не несёт ``publish`` (только ``throttle.applied``) — для неё
        функция no-op: серверного реестра метрик нет, чтобы объявить конкретное
        throttle-правило «недостигнутым».
        """
        publish = res.get("publish") if isinstance(res, dict) else None
        if not isinstance(publish, dict):
            return res
        reached, target_count = publish.get("reached"), publish.get("target_count")
        if reached == 0 or target_count == 0:
            res["hint"] = (
                f"telemetry_set(process={process!r}, metric={metric!r}): publish не достиг "
                f"ни одного адресата (reached={reached}, target_count={target_count}) — "
                "проверь имя процесса/метрики (возможна опечатка) либо жив ли процесс."
            )
        return res

    # ---- Telemetry read-model (Task 2.3: GUI-эквивалент чтения телеметрии, 0 IPC) ----

    # Зеркало Delta.to_dict(): new_value==MISSING_MARKER → удаление узла. Литерал
    # живёт в events.py (один источник для driver и плоскостной классификации);
    # в state_store не ходим СОЗНАТЕЛЬНО — package __init__ затащил бы Qt в
    # headless-драйвер. Дрейф ловит контракт-тест test_missing_marker_matches_state_store.
    _MISSING_MARKER = MISSING_MARKER

    def _ingest_state_changed(self, msg: Dict[str, Any]) -> None:
        """Слушатель событийного канала: питает локальный telemetry read-model.

        Исполняется в reader-потоке (колбэк :meth:`subscribe`) — только лёгкий
        ingest в память, без ``request()`` (как и :meth:`_on_watch_event`). Разбирает
        push ``state.changed`` (конверт ``{"command":"state.changed","data":{"deltas":
        [Delta.to_dict(), ...]}}``): каждую дельту вносит в read-model. Удаление узла
        распознаётся по ``new_value == "__MISSING__"`` (сериализация MISSING).

        Ингест под ``_telemetry_lock`` — читатели snapshot/history зовутся из другого
        потока и итерируют те же dict/deque. Заодно растёт ``_telemetry_ingested_total``
        (тот же лок) — провенанс нуля snapshot/history: «дельт не было» и «подписки не
        было» перестают быть одним и тем же нулём.
        """
        deltas = iter_state_deltas(msg)
        if not deltas:
            return
        # ПОЗДНЕЕ СВЯЗЫВАНИЕ (grep-маркер): recorder.ReplayPlayer монки-патчит
        # self._telemetry_model на clock-aware инстанс ЗАДНИМ числом (offline-реплей D.4).
        # Этот колбэк ОБЯЗАН читать модель по атрибуту self._telemetry_model в момент
        # вызова — НЕ кэшировать её в локальной переменной подписчика, иначе реплей
        # писал бы историю в старую модель с ложными ts.
        with self._telemetry_lock:
            for delta in deltas:
                new_value = delta.get("new_value")
                if new_value == self._MISSING_MARKER:
                    self._telemetry_model.ingest(delta["path"], None, deleted=True)
                else:
                    self._telemetry_model.ingest(delta["path"], new_value)
                self._telemetry_ingested_total += 1

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

    def _telemetry_ingest_active(self) -> bool:
        """Есть ли живое durable-намерение ``state.subscribe`` (см. :meth:`export_subscriptions`).

        Реестр подписок уже ведёт учёт durable-намерений — здесь только проверка «есть
        ли среди них ``state.subscribe``», без нового механизма учёта. Не гарантирует,
        что паттерн покрывает ``processes.**`` (а значит и то, что read-model реально
        наполняется) — это факт «подписка идёт», а не факт «поток ненулевой»; за сам
        поток отвечает ``_telemetry_ingested_total``.
        """
        return any(intent.get("command") == "state.subscribe" for intent in self.export_subscriptions())

    def _telemetry_ingest_patterns(self) -> List[str]:
        """Паттерны живых state.subscribe-намерений (провенанс покрытия ingest).

        Агент сам судит, покрывает ли паттерн источник телеметрии (processes.**);
        второй glob-матчер рядом со state_store НЕ строим — источник расхождений.
        """
        return [
            intent.get("args", {}).get("pattern", "")
            for intent in self.export_subscriptions()
            if intent.get("command") == "state.subscribe"
        ]

    @staticmethod
    def _telemetry_is_tracked(path: str) -> bool:
        """Путь входит в трекаемые суффиксы read-model (``DEFAULT_TRACKED_SUFFIXES``).

        Зеркалит критерий отбора истории ``TelemetryReadModel`` (суффиксное совпадение),
        не залезая внутрь самого read-model (наружу он суффиксы не отдаёт). Путь вне
        набора не имеет истории по устройству — пустой результат для него норма, а не
        поломка, и агенту нужно это отличать от «подписки нет»/«данных нет».
        """
        return any(path.endswith(suffix) for suffix in DEFAULT_TRACKED_SUFFIXES)

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
            "metrics": {path: {"value": v, "process": p, "worker": w}},
            "ingest_active": bool, "ingested_total": N, "ingest_patterns": [...]}``.
            Пустой read-model (``count=0``) сам по себе не говорит, ПОЧЕМУ пусто —
            ``ingest_active`` и ``ingested_total`` разводят «нет данных» / «нет
            подписки»: без подписки ``ingest_active=False``; под активной подпиской,
            но пока без дельт — ``ingest_active=True, ingested_total=0``.

            **Осторожно с толкованием ``ingest_active``.** Он значит только «durable-
            подписка ``state.subscribe`` ОБЪЯВЛЕНА» — НЕ «поток телеметрии идёт»: если
            паттерн подписки не покрывает ``processes.**`` (источник телеметрии),
            ``ingest_active`` всё равно будет ``True`` при пустом read-model.
            Покрывает ли объявленная подписка источник телеметрии — смотри
            ``ingest_patterns`` (список паттернов активных ``state.subscribe``-намерений)
            и суди сам: второй glob-матчер здесь сознательно не строится.
        """
        prefix = f"processes.{process}" if process else ""
        with self._telemetry_lock:
            snap = self._telemetry_model.snapshot(prefix)
            ingested_total = self._telemetry_ingested_total
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
            "ingest_active": self._telemetry_ingest_active(),
            "ingested_total": ingested_total,
            "ingest_patterns": self._telemetry_ingest_patterns(),
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
            "count": N, "points": [[ts, value], ...], "tracked": bool,
            "ingest_active": bool, "ingest_patterns": [...]}`` в хронологическом
            порядке. ``count=0`` сам по себе не говорит, ПОЧЕМУ пусто: ``tracked=False``
            — путь вне ``DEFAULT_TRACKED_SUFFIXES``, истории для него не бывает по
            устройству (норма, не поломка); ``tracked=True`` при пустом буфере — путь
            трекается, но точек ещё/уже нет (смотри ``ingest_active`` — была ли вообще
            подписка).

            **``ingest_active`` = подписка ОБЪЯВЛЕНА, не «покрывает источник телеметрии».**
            Как и у :meth:`telemetry_snapshot` — покрытие смотри в ``ingest_patterns``,
            вердикт «покрывает ли паттерн ``processes.**``» оставлен агенту.
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
            "tracked": self._telemetry_is_tracked(path),
            "ingest_active": self._telemetry_ingest_active(),
            "ingest_patterns": self._telemetry_ingest_patterns(),
        }

    # ---- system_overview (B.3): «один вызов = вся картина» ----

    def system_overview(self, *, timeout: Optional[float] = None) -> Dict[str, Any]:
        """Компактная сводка системы + anomalies-подсказки (делегат :mod:`.overview`).

        Fan-out существующими introspect-ручками по процессам топологии + локальные
        источники (telemetry read-model, счётчики driver'а/hub'а) — ноль новых
        IPC-команд. Первая команда сессии: вердикты, не археология.
        """
        return _system_overview(self, timeout=timeout)

    # ---- await_condition (B.2): серверное ожидание вместо поллинга ----

    def await_condition(
        self,
        kind: str,
        spec: Optional[Dict[str, Any]] = None,
        *,
        timeout: float = DEFAULT_AWAIT_TIMEOUT,
    ) -> Dict[str, Any]:
        """Дождаться условия на живом потоке событий (делегат :mod:`.conditions`).

        Один вызов «сделал → дождался → проверил» вместо серии поллингов:
        ``state_path`` (значение пути в read-model), ``event_matches`` (событие
        плоскости B.1 по glob'у), ``metric_threshold`` (метрика пересекла порог).
        Блокирует вызывающий поток не дольше timeout; таймаут возвращает диагноз
        (что ждали / что видели последним), не пустоту.
        """
        return _await_condition(self, kind, spec, timeout=timeout)

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
        событийный канал — читаются через :meth:`events_page` / :meth:`subscribe` как
        сообщения с ``command == "log.record"`` (``data.record`` — сам LogRecord-dict).
        """
        args = {"subscriber": subscriber or self._subscriber, "level": level}
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
        args = {"subscriber": subscriber or self._subscriber}
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
        мост 1.1b → событийный канал driver'а. Записи читаются через :meth:`events_page` /
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
        args = {"subscriber": subscriber or self._subscriber}
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
        identity = {"subscriber": subscriber or self._subscriber}
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

        Классификатор поверх :meth:`events_page`: отбирает сообщения
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
            events: список событий для разбора. ``None`` → читает НЕдеструктивно
                через :meth:`events_page` (плоскость ``all``) курсором ЭТОГО метода
                (F.1: свой приватный курсор, не делится с другими читателями
                events_page/MCP `events` — конкуренции за события нет).
            kind: плоскость-фильтр (``"log"`` | ``"error"`` | ``"stats"``); ``None`` —
                вернуть все плоскости.
            level: severity-порог (``"WARNING"`` и т.п.); ``None`` — дефолт watch
                (``tail_level``, если watch активен) либо без severity-фильтра.

        Returns:
            Плоский список record-dict'ов (display-вид: kind/process/module/ts/
            severity/message/extra) в порядке поступления.
        """
        # F5: дефолт severity-фильтра — объявленный tail_level активного watch.
        effective_level = level if level is not None else self._watch.default_tail_level()
        threshold = _LOG_SEVERITY_RANK.get(str(effective_level).lower()) if effective_level else None

        if events is None:
            # Триплет «прочитал курсор → взял страницу → записал курсор» под локом
            # (Task 2.3): иначе параллельный вызов отдаёт ту же страницу второй раз.
            with self._tool_cursor_lock:
                cursor = self._obs_records_cursor
                page = page_with_reset_retry(lambda c: self.events_page(cursor=c), cursor)
                # Провал обеих попыток (двойная ротация gen между ними) — СОХРАНИТЬ старый
                # курсор, а не обнулить: page.get("next_cursor") дал бы None, и следующий
                # вызов перечитал бы весь ринг логов заново. Семантика едина с мостом
                # MCP-инструмента events (ревью Task 2.3).
                self._obs_records_cursor = page.get("next_cursor", cursor)
            source: List[Dict[str, Any]] = [it["event"] for it in page.get("items", [])]
        else:
            source = events
        out: List[Dict[str, Any]] = []
        for msg in source:
            if not isinstance(msg, dict) or msg.get("command") != OBSERVABILITY_RECORD_COMMAND:
                continue
            for rec in extract_observability_records(msg.get("data")):
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
        args = {"subscriber": subscriber or self._subscriber}
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
        Всё приходит в ЕДИНЫЙ событийный канал (:meth:`events_page`, plane ``all``):
        команды ``ui.event`` / ``log.record`` / ``state.changed``, упорядочивание —
        ts (+seq у ui.event).

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
        читаются через events_page()/subscribe(). subscriber по умолчанию = self.sender
        (адрес, на который сервер направляет пуши). Возвращает result подписки
        (status + sub_id).
        """
        args = {
            "pattern": pattern,
            "subscriber": subscriber or self._subscriber,
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

        ``timeout`` принимается ради симметрии сигнатур обёрток и СОЗНАТЕЛЬНО
        игнорируется: метод правит только локальный реестр намерений, сетевого вызова
        здесь нет — ждать нечего. Названо явно, чтобы вызывающий не считал, будто
        задаёт таймаут какой-то отправке (Task 5.4).

        Снимает durable-намерение ``state.subscribe`` этого паттерна из реестра — чтобы
        реконнект НЕ воскресил его через replay (главная и единственная задача: вернуть
        управляемость watch-профилем). Серверную подписку поштучно НЕ снимаем: сервер
        отписывает по ``sub_id`` (у нас его нет) либо ``state.unsubscribe_all`` по
        подписчику (снёс бы и НЕ-watch подписки того же driver'а — слишком широко).
        Серверная state-подписка освобождается закрытием соединения (как в
        :meth:`debug_stop`); durable-намерение — это то, что переживало бы реконнект.
        """
        sub = subscriber or self._subscriber
        self._subscriptions.remove("state.subscribe", "ProcessManager", {"pattern": pattern})
        return {"success": True, "pattern": pattern, "subscriber": sub}

    # ---- GUI-эквивалентный приёмный профиль (Task 2.2) — делегаты в WatchController ----

    def watch_like_gui(
        self,
        *,
        patterns: tuple[str, ...] = GUI_DEFAULT_PATTERNS,
        tail_level: str = "WARNING",
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Включить весь приёмный профиль GUI одной командой (делегат :meth:`WatchController.start`)."""
        return self._watch.start(patterns=patterns, tail_level=tail_level, timeout=timeout)

    def unwatch(self, *, timeout: Optional[float] = None) -> Dict[str, Any]:
        """Выключить GUI-профиль (делегат :meth:`WatchController.stop_profile`)."""
        return self._watch.stop_profile(timeout=timeout)

    def watch_manifest(self) -> Dict[str, Any]:
        """Снимок активного watch-профиля для переживания реконнекта (делегат)."""
        return self._watch.manifest()

    def resume_watch(self, manifest: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Восстановить watch-контур из манифеста после реконнекта (делегат)."""
        return self._watch.resume(manifest)

    @property
    def watch_resub_errors(self) -> int:
        """Сколько авто-переподписок хвоста завершились ошибкой (диагностика, делегат)."""
        return self._watch.resub_errors
