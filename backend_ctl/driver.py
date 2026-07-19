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
потоки читают их курсорами events_page()/subscribe() (`events()` — устаревший
деструктивный дренаж, удаление в F.1).

Без бизнес-логики: driver только транспортирует router-сообщения. Вся интроспекция/
команды исполняются процессами системы, ответы едут обратно чистым RouterManager.
"""

from __future__ import annotations

import logging
import socket
import threading
from typing import Any, Dict, List, Optional

from multiprocess_framework.modules.telemetry_readmodel_module import TelemetryReadModel
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

        # Событийный канал (B.1): EventHub — курсорные плоскости + подписчики.
        # reader-поток пишет (emit), клиентские потоки читают курсорами
        # (events_page) либо legacy-дренажем (events). Предикат alive выводит
        # блокирующий drain из вечного ожидания на закрытом соединении.
        self._hub = EventHub(maxlen=event_queue_maxlen, alive=lambda: self._running or self._reader is not None)

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
        потока и итерируют те же dict/deque.
        """
        deltas = iter_state_deltas(msg)
        if not deltas:
            return
        with self._telemetry_lock:
            for delta in deltas:
                new_value = delta.get("new_value")
                if new_value == self._MISSING_MARKER:
                    self._telemetry_model.ingest(delta["path"], None, deleted=True)
                else:
                    self._telemetry_model.ingest(delta["path"], new_value)

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
        effective_level = level if level is not None else self._watch.default_tail_level()
        threshold = _LOG_SEVERITY_RANK.get(str(effective_level).lower()) if effective_level else None

        source = self.events() if events is None else events
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
