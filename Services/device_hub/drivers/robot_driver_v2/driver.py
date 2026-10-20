"""RobotDriverV2 — драйвер хаба для робота протокола Delta v2 (T5.1, plans/robot-protocol-v2/tasks/T5.1.md).

Purpose:
    Драйвер ``device_hub`` поверх ``RobotClientV2``: подключение (транспорт -> ``probe`` -> ``sync_params`` ->
    действия при подключении), тик хаба (пульс ``HB_PC`` каждый тик, блок телеметрии, сверка метки параметров,
    асинхронные ошибки в ``devices.state.<id>.last_error``), удержание jog с поводком и явным стопом,
    исполнитель программ в своём потоке (состояние — ``devices.state.<id>.program``). Фабрика хаба выбирает этот
    класс по ``entry.protocol == "delta_v2"``; драйвер v1 (``robot_driver.py``) не меняется.

Public API:
    ``RobotDriverV2(entry, protocol=None, *, transport=None, publish=None, param_source=None, clock=None,
    sleep=None, spawn=None)``; ``connect() -> bool``, ``disconnect()``, ``request_stop()``, ``is_connected``,
    ``tick(stop_event)``,
    ``call(op, args)`` с операциями ``jog_hold`` {dir, spd}, ``jog_release``, ``get_telemetry``,
    ``enqueue_job`` {x_mm, y_mm, z_mm?, e_capture?, place_x?, place_y?, place_z?, place_rz?} (T3.7: CVT_JOB;
    ``place_rz`` — доворот к ``P_PICK_RZ``; ответ ``queue_len``), ``return_job`` {x_mm, y_mm, z_mm?} (T3.7:
    программа ``return_slot``; ответ ``return_queue_len``); ``start_program(program, points, frames=None, *, name)``,
    ``start_return(slot, **kw)``, ``start_toolchange(current, target, points, **kw)``; ``snapshot`` со счётчиками
    ``jobs_*`` / ``returns_*``; свойство ``transport`` (свой ``ModbusDevice``).
    ``param_source`` — точка подключения T5.2: ``() -> (сырые значения {имя: int} без P_CONFIG_EPOCH, метка)``.
    ``spawn`` — T5.3a: ``(target, *, name) -> IHandle`` (``IScope.spawn`` области плагина), ``target(event)``. Драйвер
    корней не открывает и ``Thread`` не создаёт (T5.3 круг 2): без ``spawn`` операции с потоком (``jog_hold``, запуск
    программы / возврата / смены инструмента) бросают ``RuntimeError``; без потоков драйвер работает как прежде.
    ``call("abort", {mode})`` — стоп оператора: пишется всегда, защёлка стопа процесса его не блокирует.
    T5.3d d1: ``store=`` (``RobotDataStore``) и операции ``stop`` {level}, ``servo``, ``do_set``, ``jog_step``,
    ``point_capture``, ``param_set``, ``param_apply``, ``program_run``, ``program_abort``; плохие аргументы —
    ``TEXT_BAD_ARGS``; ``param_set`` / ``param_apply`` берут ``_param_lock`` не блокируя.

Stability: lite

Потоки (DESIGN п.9). Состояние драйвера — ``RobotState`` (T5.3f): поля и переходы под одним листовым замком
состояния (программа, ``_last_hold``, состояние jog, множество своих стопов, защёлка, очереди); вокруг вызовов клиента
он не держится: ``ModbusDevice`` сериализует RLock-ом, а
``stop`` / ``kick_heartbeat`` / ``jog_lease`` / ``poll_errors`` нарочно минуют замок mailbox клиента. Второй замок
``_jog_tx_lock`` — только для переходов jog: ``client.jog_cont`` в ``jog_hold`` и ``client.stop(SOFT)`` стопа jog.
Тик, исполнитель и ``poll_errors`` его не берут. Путь ``connect`` и повторная синхронизация не идут, пока жив поток
поводка или исполнителя.

Задания (T3.7). Очереди заданий и возвратов дренирует тик: одно действие за тик, только при свободном захвате.
Флаг ``job_active`` — в ``RobotState``, ставится одним переходом с проверкой программы / jog и взятием задания,
ДО ``cvt_job``; при нём ``jog_hold`` и запуск программы отвечают «робот выполняет задание». Тик блокируется на
``wait_done`` до исхода задания; пульс ``HB_PC`` в это время — ``on_poll``. ``connect`` при задании не идёт. Новых
потоков нет: возврат идёт программой на потоке исполнителя.

Остановка (T5.3a, круг 2). ``request_stop(deadline)`` — фаза 1 остановки плагина: защёлка ``_shutdown`` и ОДНА запись
стопа на сильнейшем нужном уровне (задание / программа — HARD, jog — SOFT), без ожидания эха и потоков. Защёлка стопа
(на робота) помнит сильнейший записанный уровень и «последняя запись упала»: стоп процесса не пишется, если уровень не
ниже уже записан; упавшая запись повторяется ровно один раз и только если успевает до срока (не больше двух
попыток на поколение). Защёлка сбрасывается ПОСЛЕ записи движения (JOG_CONT) и при захвате программы / задания
(поколение прогона), в ``connect()`` и первым запросом выключения (``request_stop`` / ``disconnect``: один стоп на
выключение, прежние стопы его не покрывают); jog без записанного стопа пишется мимо неё. Исключение из «одна
запись»: JOG_CONT, вернувшийся после стопа процесса (замок перехода не взят), получает свой стоп (H-B).
Повтор стопа исполнителя в ``on_progress`` (микроокно К1) идёт мимо защёлки: он привязан к прогону (один раз на
прогон). Простой подключённый робот (ничего не исполняется) получает один SOFT (решение владельца 2026-10-19:
выключаемый робот получает стоп и в покое; при остановке процесса стоп получают все подключённые, при
``disconnect()`` одного робота — только он). ``disconnect()`` после ``request_stop`` стоп не пишет: одна проверка эха
(нет эха — ``last_error`` «стоп не подтверждён роботом»; нет времени на чтение, срок меньше бюджета записи, —
«эхо не читалось (нет окна)»), ожидание потоков, закрытие транспорта. Обычный ``disconnect()`` (без остановки
плагина): задание (HARD), jog и программа — стоп с ожиданием эха; простой подключённый робот — только запись SOFT,
без чтения эха и без ``last_error`` (T5.3c c3); защёлку ``_shutdown`` он не ставит.
Потоки поводка и исполнителя живут в области (``spawn``): имя ``<entry.id>-lease-<k>`` / ``<entry.id>-prog-<k>``,
``k`` — счётчик модуля.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Mapping
from typing import Any

from multiprocess_framework.modules.base_manager.interfaces import IHandle, ScopeClosedError

from Services.device_hub.drivers.base import BaseDeviceDriver, logger
from Services.device_hub.drivers.exchange_log import TEXT_BAD_CONFIG, ExchangeLog, ExchangeLogTransport
from Services.device_hub.drivers.robot_driver_v2.args import _StoreIOError
from Services.device_hub.drivers.robot_driver_v2.jobs import JobMixin
from Services.device_hub.drivers.robot_driver_v2.jog import JogMixin
from Services.device_hub.drivers.robot_driver_v2.ops import OPS, OpsMixin
from Services.device_hub.drivers.robot_driver_v2.params import ParamMixin
from Services.device_hub.drivers.robot_driver_v2.programs import ProgramMixin
from Services.device_hub.drivers.robot_driver_v2.state import RobotState, _JogRun
from Services.device_hub.drivers.robot_driver_v2.texts import (
    TEXT_NO_ECHO_WINDOW,
    TEXT_NO_SPAWN,
    TEXT_SCOPE_CLOSED,
    TEXT_SPAWN_FAILED,
    TEXT_SPAWN_NAME_BUSY,
    TEXT_STOP_UNCONFIRMED,
    TEXT_THREAD_SURVIVED,
    TEXT_WDG_INTERVAL,
    _CLIENT_KEYS,
    _DO_CHANNELS,
    _HUB_POLL_DEFAULT_S,
    _JOB_QUEUE_MAXLEN,
    _LEASE_JOIN_S,
    _ON_CONNECT_DEADLINE_S,
    _ON_CONNECT_POLL_S,
    _PROCESS_STOP_DEFAULT_S,
    _PROGRAM_JOIN_S,
    _RECONNECT_THROTTLE_SEC,
    _TLM_BASE,
    _TLM_COUNT,
)
from Services.device_hub.drivers.robot_driver_v2.tlm import _parse_tlm, _w
from Services.device_hub.robot_data_ops import TEXT_STORE_ERROR
from Services.robot_comm.core.client_v2 import ClientV2Config, RobotClientV2
from Services.robot_comm.core.params_v2 import PARAMS, PARAM_ID, to_eng
from Services.robot_comm.core.protocol_v2 import ERR, STOP_LEVEL
from Services.robot_comm.programs import Point
from Services.robot_comm.store import RobotDataStore

__all__ = ["RobotDriverV2"]


class RobotDriverV2(JogMixin, ProgramMixin, JobMixin, ParamMixin, OpsMixin, BaseDeviceDriver):
    """Драйвер робота Delta v2 (DESIGN п.1-10 брифа T5.1).

    Args:
        entry:        DeviceEntry с ``kind="robot"``, ``protocol="delta_v2"``.
        protocol:     DeviceProtocol или None (не используется: адреса — из ``protocol_v2``).
        transport:    Инъекция транспорта (тесты); иначе ``build_transport`` в ``connect()``.
        publish:      ``(path, payload) -> None`` — публикация ``last_error`` и ``program`` (Л5).
        param_source: ``() -> (values, epoch)`` — источник параметров (T5.2); None — умолчания словаря
                      с переопределениями ``entry.params["robot_params"]`` и меткой ``entry.params["config_epoch"]``.
        clock/sleep:  Инъекция времени.
        spawn:        ``(target, *, name) -> IHandle`` — потоки поводка и исполнителя берутся у области плагина
                      (T5.3a). None — драйвер без потоков: ``jog_hold`` и запуск программы бросают ``RuntimeError``.
        store:        ``RobotDataStore`` данных робота (T5.3d): точки, программы, параметры для ``point_capture``,
                      ``program_run``, ``param_set``; None — эти операции отвечают «хранилище данных робота не задано».

    Raises:
        ValueError: некорректные поля конфига клиента, ``robot_params`` или ``on_connect``.
    """

    kind = "robot"

    _OPS: dict[str, Callable[[RobotDriverV2, dict], dict]]  # заполняется после класса

    def __init__(
        self,
        entry: Any,
        protocol: Any = None,
        *,
        transport: Any = None,
        publish: Callable[[str, Any], None] | None = None,
        param_source: Callable[[], tuple[Mapping[str, int], int]] | None = None,
        clock: Any = None,
        sleep: Any = None,
        spawn: Callable[..., IHandle] | None = None,
        store: RobotDataStore | None = None,
    ) -> None:
        super().__init__(entry, protocol, clock=clock, sleep=sleep)
        params: Mapping[str, Any] = getattr(entry, "params", None) or {}
        self._params = params

        cfg: dict[str, Any] = {key: params[key] for key in _CLIENT_KEYS if key in params}
        if "client_poll_interval_s" in params:
            cfg["poll_interval_s"] = params["client_poll_interval_s"]
        self._cfg = ClientV2Config.from_dict(cfg)  # ValueError — ошибка конфига

        self._transport: Any = transport
        self._client: RobotClientV2 | None = None
        self._pub: Callable[[str, Any], None] = publish or (lambda _p, _d: None)
        self._param_source = param_source
        self._values, self._epoch = self._load_params()
        self._servo_on, self._do_on_connect = self._parse_on_connect(params.get("on_connect"))
        self._hub_poll_s = float(params.get("poll_interval_s", _HUB_POLL_DEFAULT_S))

        self._ready = False  # последний connect() прошёл целиком
        self._last_reconnect = 0.0
        self._last_resync = 0.0

        # Замок перехода jog: client.jog_cont и стоп jog; с замком состояния — только снаружи (он листовой)
        self._jog_tx_lock = threading.Lock()
        # Третий замок (T5.3d): только вокруг param_set / param_apply (и синхронизации, d2); берётся не блокируя.
        # Порядок: _param_lock -> замок состояния; вместе с _jog_tx_lock не держится
        self._param_lock = threading.Lock()
        self._store = store  # единственный RobotDataStore процесса (фабрика); None — автономный драйвер
        self._spawn: Callable[..., IHandle] | None = spawn

        # Состояние (T5.3f): флаги, jog, защёлка стопа, очереди заданий и возвратов — поля RobotState под его замком
        # Задания CVT_JOB и возвраты (T3.7 DESIGN п.1): очереди — паритет v1, дренаж — тик, по одному действию
        maxlen = int(params.get("job_queue_maxlen", _JOB_QUEUE_MAXLEN))
        self._state = RobotState(clock=self._clock, queue_maxlen=maxlen)
        self._pick_lead_mm = float(params.get("pick_lead_mm", 0.0))
        self.jobs_sent = 0
        self.jobs_done = 0
        self.jobs_failed = 0

        # Журнал обмена (T5.6): живёт столько же, сколько драйвер; ручки — entry.params["exchange_log"]
        log_cfg = params.get("exchange_log")
        if isinstance(log_cfg, bool):  # сокращение: false — журнал выключен, true — умолчания
            log_cfg = {"enabled": log_cfg}
        try:
            if log_cfg is not None and not isinstance(log_cfg, Mapping):
                raise ValueError(TEXT_BAD_CONFIG)
            log_cfg = log_cfg or {}
            self._exchange_log = ExchangeLog(
                entry.id, enabled=log_cfg.get("enabled", True), periodic=log_cfg.get("periodic", False)
            )
        except ValueError:  # плохой конфиг журнала не мешает создать драйвер: умолчания и предупреждение
            logger.warning(f"робот {entry.id!r}: {TEXT_BAD_CONFIG}")
            self._exchange_log = ExchangeLog(entry.id)
        if self._transport is not None:  # внедрённый транспорт (тесты); иначе обёртка — в connect()
            self._transport = ExchangeLogTransport(self._transport, self._exchange_log)

    # ------------------------------------------------------------------ #
    # Параметры и конфиг подключения
    # ------------------------------------------------------------------ #

    def _load_params(self) -> tuple[dict[str, int], int]:
        """Сырые значения всех параметров (без P_CONFIG_EPOCH) и метка ПК (Л1)."""
        if self._param_source is not None:
            values, epoch = self._param_source()
            return {name: int(raw) for name, raw in values.items()}, int(epoch)
        values = {name: int(PARAMS[pid]["default"]) for name, pid in PARAM_ID.items() if name != "P_CONFIG_EPOCH"}
        overrides = self._params.get("robot_params") or {}
        for name, raw in overrides.items():
            if name not in values:
                raise ValueError(f"robot_params: неизвестный параметр {name!r}")
            values[name] = int(raw)
        return values, int(self._params.get("config_epoch", 1))

    @staticmethod
    def _parse_on_connect(raw: Any) -> tuple[bool | None, dict[int, bool]]:
        """``{"servo": bool, "do": {"<канал 1..16>": bool}}`` (Л2); умолчание — серво включить, DO не трогать."""
        spec = {"servo": True, "do": {}} if raw is None else dict(raw)
        servo = spec.get("servo", True)
        do: dict[int, bool] = {}
        for channel, on in (spec.get("do") or {}).items():
            ch = int(channel)
            if ch not in _DO_CHANNELS:
                raise ValueError("on_connect.do: канал вне 1..16")
            do[ch] = bool(on)
        return (None if servo is None else bool(servo)), do

    def _ws_params(self) -> dict[str, float]:
        """Инженерные значения параметров для ``compile_program`` / ``run_chunks``: ``to_eng`` (raw / scale)."""
        return {name: to_eng(name, raw) for name, raw in self._values.items()}

    def _home_point(self) -> Point:
        v = self._values
        return Point(
            name="home",
            x=to_eng("P_HOME_X", v["P_HOME_X"]),
            y=to_eng("P_HOME_Y", v["P_HOME_Y"]),
            z=to_eng("P_HOME_Z", v["P_HOME_Z"]),
            rz=to_eng("P_HOME_RZ", v["P_HOME_RZ"]),
            hand=int(v["P_HAND"]),
        )

    # ------------------------------------------------------------------ #
    # Соединение
    # ------------------------------------------------------------------ #

    @property
    def transport(self) -> Any:
        """Свой ``ModbusDevice`` (Д2); None до первого ``connect()``, если транспорт не внедрён."""
        return self._transport

    @property
    def is_connected(self) -> bool:
        transport = self._transport
        return self._ready and transport is not None and bool(transport.is_connected)

    @property
    def state(self) -> RobotState:
        """Состояние драйвера (только чтение; внутреннее, не SPI хаба): снимок — ``state.view()``."""
        return self._state

    @property
    def returns_done(self) -> int:
        """Возвраты, исполненные до конца; чтение без замка (как ``snapshot``)."""
        return self._state.returns_done

    @property
    def returns_failed(self) -> int:
        """Возвраты с отказом или неудачей программы; чтение без замка (как ``snapshot``)."""
        return self._state.returns_failed

    def _activity_alive(self) -> bool:
        """Жив поток поводка или исполнителя: путь connect и повторная синхронизация не идут (п.9).

        Живость — флаги (``run.active`` снимает поток поводка, ``program_active`` — исполнитель), не объекты потоков.
        """
        return self._state.activity_alive()

    def connect(self) -> bool:
        """Ручное подключение: ``_connect_locked`` под ``_param_lock`` (ждёт идущий ``param_set`` — его ввод-вывод
        ограничен; тик замок берёт не блокируя и не ждёт)."""
        with self._param_lock:
            return self._connect_locked()

    def _connect_locked(self) -> bool:
        """Транспорт -> probe -> sync_params -> действия при подключении (DESIGN п.3); под ``_param_lock``.

        Не идёт, пока жив поток поводка или исполнителя, и пока тик держит задание (T3.7 R9): иначе ``probe`` +
        ``sync_params`` посреди хода дали бы NAK ``E_BUSY`` на ``PARAM_SET`` и ``_ready = False``.
        """
        shutdown, job_active = self._state.connect_check()
        if shutdown:
            return False  # защёлка request_stop(): после остановки плагина драйвер не подключается (К1)
        if job_active or self._activity_alive():
            return self.is_connected
        self._state.connect_reset()  # ручное «Подключить» после обычного disconnect снова разрешает jog и программы
        was_ready = self._ready
        self._ready = False
        try:
            if self._transport is not None and self._transport.is_connected and not was_ready:
                self._transport.disconnect()  # сокет после сбоя мог остаться «подключённым» (см. _link_lost)
            if self._transport is None:
                from Services.device_hub.transports import build_transport

                self._transport = build_transport(self.entry, lambda _id: None)
                self._transport = ExchangeLogTransport(self._transport, self._exchange_log)
            if self._client is None:
                self._client = RobotClientV2(self._transport, self._cfg)
            client = self._client
            if not self._transport.is_connected and not self._transport.connect():
                raise ConnectionError("транспорт не подключился")
            client.probe()
            if not self._sync_on_connect(client):
                if self._sync_cancelled():
                    return False  # стоп посреди подключения: драйвер не готов, метка не доверена
                self._ready = was_ready  # посреди подключения появилась активность: синхронизации нет, всё как было
                return self.is_connected
            self._run_on_connect(client)
        except _StoreIOError:  # диск хранилища: полный текст уже в логе, в last_error — константа без пути
            self._record_err()
            self._last_quality = "bad"
            self._publish_error(TEXT_STORE_ERROR)
            return False
        except Exception as exc:
            if self._sync_cancelled():  # «Отключить» / стоп посреди подключения — не ошибка обмена
                logger.warning(f"робот {self.entry.id!r}: подключение прервано остановкой: {type(exc).__name__}: {exc}")
                self._last_quality = "bad"
                return False
            self._record_err()
            self._last_quality = "bad"
            logger.warning(f"робот {self.entry.id!r}: подключение не удалось: {type(exc).__name__}: {exc}")
            self._publish_error(f"подключение к роботу не удалось: {type(exc).__name__}: {exc}")
            return False
        period = client.heartbeat_period_s
        if period is not None and self._hub_poll_s > period:
            self._publish_error(TEXT_WDG_INTERVAL)
        shutdown = self._state.is_shutdown()
        if shutdown:
            return False  # подключение, начатое до request_stop(), не делает драйвер готовым
        self._ready = True
        self._last_quality = "good"
        return True

    def _run_on_connect(self, client: RobotClientV2) -> None:
        """SERVO и DO_SET — instant: без wait_done, подтверждение — чтением TLM с дедлайном (Л2).

        Д5: действия идемпотентны — «обеспечить состояние». Сначала читается TLM; команда шлётся, только если
        состояние не равно цели. Так переподключение во время jog прошивки, который ещё дожидается срока поводка,
        не получает NAK ``E_BUSY`` на SERVO (``busy: deny``).
        """
        if self._servo_on is not None:
            want = 1 if self._servo_on else 0
            if _w(self._read_tlm(), "TLM_SERVO") != want:
                client.servo(self._servo_on)
                self._await_tlm(lambda tlm: _w(tlm, "TLM_SERVO") == want, "TLM_SERVO")
        for ch, on in self._do_on_connect.items():
            bit = 1 << (ch - 1)
            if bool(_w(self._read_tlm(), "TLM_DO_MASK") & bit) != on:
                client.do_set(ch, on)
                self._await_tlm(lambda tlm, b=bit, o=on: bool(_w(tlm, "TLM_DO_MASK") & b) == o, f"DO{ch}")

    def _await_tlm(self, pred: Callable[[list[int]], bool], what: str) -> None:
        deadline = self._clock() + _ON_CONNECT_DEADLINE_S
        while True:
            if pred(self._read_tlm()):
                return
            if self._clock() >= deadline:
                raise TimeoutError(f"робот не подтвердил {what} за {_ON_CONNECT_DEADLINE_S} с")
            self._sleep(_ON_CONNECT_POLL_S)

    def disconnect(self) -> None:
        """Стоп (задание HARD, jog SOFT, программа SOFT, простой подключённый робот SOFT), ожидание потоков, закрытие.

        Потоки ждёт ``IHandle.close``, затем закрывается транспорт.

        Защёлку ``_shutdown`` не ставит: после обычного отключения ручной ``connect()`` снова работает (К1).
        После ``request_stop()`` (фаза 4 остановки плагина) стоп не пишется и эхо не читается (проверено в фазе 1).
        """
        shutdown = self._state.disconnect_begin()  # не выключение — новое поколение защёлки
        if not shutdown:  # после request_stop стоп не пишется: эхо проверено в фазе 1 (H7)
            self._request_stop(program_level=STOP_LEVEL["SOFT"])
        run, prog = self._state.threads_to_close()
        if run is not None and run.handle is not None:
            self._close_thread(run.handle, _LEASE_JOIN_S)
        if prog is not None:
            self._close_thread(prog, _PROGRAM_JOIN_S)
        self._ready = False
        if self._transport is not None:
            try:
                self._transport.disconnect()
            except Exception as exc:
                self._record_err()  # сбой закрытия фиксируется, не глушится молча (как v1)
                logger.warning(
                    f"робот {self.entry.id!r}: транспорт при отключении не закрыт: {type(exc).__name__}: {exc}"
                )
        self._last_quality = "bad"

    def request_stop(self, deadline: float | None = None) -> None:
        """Фаза 1 остановки плагина (К1): защёлка ``_shutdown`` и одна запись стопа без эха, потоков и закрытия.

        ``deadline`` — абсолютный срок по ``time.monotonic()`` (None — сейчас + ``_PROCESS_STOP_DEFAULT_S``). Уровень —
        сильнейший нужный: задание и программа HARD (SOFT посреди хода ждал бы цели), jog SOFT. Простой подключённый
        робот (нет задания, программы и jog) тоже получает один SOFT (решение владельца 2026-10-19); не подключённый
        простой — нет. Защёлка: уровень не ниже уже записан и последняя запись не упала
        — записи нет; упавшая запись повторяется ровно один раз, пока не вышел срок. ``_jog_tx_lock`` берётся с
        таймаутом остатка срока; не взят — стоп пишется без замка (В1). Затем проверка эха этой записи (H7): чтения
        начинаются, только пока чтение с повторами транспорта успевает до срока; окно было, эха нет, или запись не
        прошла — «стоп не подтверждён роботом»; окна нет (срок меньше бюджета записи) — «эхо не читалось (нет окна)»
        (``last_error``, свойство ``stop_unconfirmed`` для health плагина).
        Не бросает. Повторный вызов безопасен. После него ``connect()`` возвращает False, ``jog_hold`` и запуск
        программы отвечают ``TEXT_STOPPING``.
        """
        if deadline is None:
            deadline = time.monotonic() + _PROCESS_STOP_DEFAULT_S
        self._state.request_stop_begin()  # защёлка выключения; первый вызов — новое поколение защёлки
        locked = self._jog_tx_lock.acquire(timeout=max(0.0, deadline - time.monotonic()))
        try:
            if not locked:
                logger.warning(f"робот {self.entry.id!r}: замок перехода jog не взят до срока — стоп пишется без него")
            self._process_stop(deadline)
        except Exception as exc:
            self._record_err()
            logger.warning(f"робот {self.entry.id!r}: стоп процесса прерван: {type(exc).__name__}: {exc}")
        finally:
            if locked:
                self._jog_tx_lock.release()
        try:
            self._check_stop_echo(deadline)
        except Exception as exc:
            self._record_err()
            logger.warning(f"робот {self.entry.id!r}: проверка эха прервана: {type(exc).__name__}: {exc}")

    @property
    def stop_unconfirmed(self) -> bool:
        """Стоп процесса этого робота не подтверждён (нет эха или запись не прошла); для health плагина."""
        return self._state.stop_unconfirmed()

    @property
    def stop_unconfirmed_text(self) -> str | None:
        """Текст причины для health: ``TEXT_STOP_UNCONFIRMED`` или ``TEXT_NO_ECHO_WINDOW``; ``None`` — не помечен."""
        return self._state.stop_unconfirmed_text()

    def _process_stop(self, deadline: float) -> None:
        """Тело ``request_stop`` (замок перехода jog взят или не взят по сроку): пометки, защёлка, запись."""
        # is_connected зовётся под замком состояния, в той же ветке, что и раньше (простой робот)
        level, run, stop_jog = self._state.process_stop_plan(lambda: self.is_connected)
        if not level or self._client is None:
            return  # простой неподключённый робот, стоп уже записан или нет клиента: записи нет
        jog_run = run if stop_jog else None
        while True:
            # Повтор — только после упавшей записи и только если запись успеет до срока (не больше двух попыток)
            attempt = self._state.next_stop_attempt(deadline, self._write_budget_s)
            if attempt is None:
                return
            try:
                self._write_stop(level, jog_run)
                return
            except Exception as exc:
                self._record_err()
                logger.warning(
                    f"робот {self.entry.id!r}: стоп процесса не записан ({attempt}): {type(exc).__name__}: {exc}"
                )

    def _write_budget_s(self) -> float:
        """Худшее время одной записи: ``timeout_sec * (retries + 1)`` транспорта (умолчания build_transport)."""
        transport = getattr(self.entry, "transport", None) or {}
        return float(transport.get("timeout_sec", 1.0)) * (int(transport.get("retries", 1)) + 1)

    def _write_stop(self, level: int, run: _JogRun | None = None) -> int:
        """Одна запись ``STOP_REQ`` (``client.issue_stop``) без эха; итог — в защёлку. Ошибка записи — наружу.

        ``run`` — jog, которому адресован стоп: его seq — в множество своих стопов ДО записи (Д1), ``stop_sent`` —
        сразу ПОСЛЕ удачной записи (флаг отражает запись, не эхо).
        """
        if run is not None:
            self._state.note_own_stop(run.seq)
        try:
            value = self._client.issue_stop(level)
        except Exception:
            self._state.stop_write_failed()
            raise
        self._state.stop_written(value, run)
        return value

    def _stop_and_wait(self, level: int, run: _JogRun | None = None) -> None:
        """Стоп с эхом (пути оператора и обычный disconnect): запись через защёлку + эхо по таймауту клиента."""
        value = self._write_stop(level, run)
        written = value & 3
        timeout = self._cfg.soft_echo_timeout_s if written == STOP_LEVEL["SOFT"] else self._cfg.stop_echo_timeout_s
        self._client.await_stop_echo(value, written, deadline=time.monotonic() + timeout)

    def _check_stop_echo(self, deadline: float) -> None:
        """Эхо записи стопа процесса этого поколения, без записи, один раз на значение (H7).

        Чтения идут до ``deadline - _write_budget_s()``: чтение, начатое позже, могло бы пережить срок на мёртвой
        связи. Исходы без подтверждения (``stop_unconfirmed`` и ``last_error``): запись прошла, окно было, эха нет —
        ``TEXT_STOP_UNCONFIRMED``; запись прошла, окна нет — ``TEXT_NO_ECHO_WINDOW``; запись не прошла —
        ``TEXT_STOP_UNCONFIRMED``. Простой робот (записи не было) не проверяется. Не бросает.
        """
        check, value = self._state.echo_check_plan()  # проверяемое значение помечается в том же переходе
        if not check:
            return
        client = self._client
        read_until = deadline - self._write_budget_s()
        confirmed = False
        has_window = value is not None and client is not None and time.monotonic() < read_until
        if has_window:
            try:
                client.await_stop_echo(value, value & 3, deadline=read_until)
                confirmed = True
            except Exception as exc:
                logger.warning(f"робот {self.entry.id!r}: эхо стопа не получено: {type(exc).__name__}: {exc}")
        if confirmed:
            return
        # запись прошла, а читать эхо было некогда (срок минус бюджет записи) — это не «эхо не пришло»
        no_window = value is not None and client is not None and not has_window
        text = TEXT_NO_ECHO_WINDOW if no_window else TEXT_STOP_UNCONFIRMED
        self._state.mark_unconfirmed(text)
        self._record_err()
        logger.warning(f"робот {self.entry.id!r}: {text}")
        self._publish_error(text)

    def _stop_latched(self, level: int) -> None:
        """Запись стопа без эха через защёлку: такой уровень уже записан в этом поколении — записи нет (H1)."""
        if self._state.latch_covers(level):
            return
        self._write_stop(level)

    def _request_stop(self, program_level: int) -> None:
        """Стоп обычного ``disconnect``: флаг ``_stopping``, пометка jog, стопы с ожиданием эха без замков (К1)."""
        # V1: JOG_CONT в полёте дописывает jog под _jog_tx_lock — читаем его под тем же замком
        with self._jog_tx_lock:
            run, stop_jog, prog_alive, job_active = self._state.disconnect_stop_plan(program_level)
        # _stop_jog снова берёт _jog_tx_lock (не реентерабельный) — замки отпущены
        client = self._client
        if client is None:
            return
        if job_active:
            # HARD обрывает ход CVT сразу; SOFT на CVT откладывается до точки захвата (R9). Тик, ждущий wait_done,
            # получает RobotAborted или ошибку транспорта и считает задание неудачным.
            try:
                self._stop_and_wait(STOP_LEVEL["HARD"])
            except Exception as exc:
                self._record_err()
                logger.warning(f"робот {self.entry.id!r}: стоп задания не доставлен: {type(exc).__name__}: {exc}")
        if stop_jog and run is not None:
            try:
                self._stop_jog(run)
            except Exception as exc:
                self._record_err()
                logger.warning(f"робот {self.entry.id!r}: стоп jog не доставлен: {type(exc).__name__}: {exc}")
        if prog_alive:
            try:
                self._stop_and_wait(program_level)
            except Exception as exc:
                self._record_err()
                logger.warning(f"робот {self.entry.id!r}: стоп программы не доставлен: {type(exc).__name__}: {exc}")
        if not (job_active or stop_jog or prog_alive) and self.is_connected:
            # Решение владельца 2026-10-19: отключаемый подключённый робот получает стоп и в покое (SOFT);
            # защёлка гасит вторую запись в том же выключении (jog со стопом этого вызова). Только запись SOFT:
            # эхо простого робота не читается (supervisor не ждёт soft_echo_timeout_s), last_error нет (T5.3c c3)
            covered = self._state.latch_covers(STOP_LEVEL["SOFT"])
            if not covered:
                try:
                    self._write_stop(STOP_LEVEL["SOFT"])
                except Exception as exc:
                    self._record_err()
                    logger.warning(
                        f"робот {self.entry.id!r}: стоп простого робота не записан: {type(exc).__name__}: {exc}"
                    )

    def _close_thread(self, handle: IHandle, budget_s: float) -> None:
        """Дождаться выхода потока через его запись. Выживший виден: ``tx_err`` +1, ``last_error``; не бросает.

        ``IHandle.close`` отцепляет запись от владельца, поэтому выживший не попадёт в отчёт ``scope.close()``;
        в health он доходит через reporter корня плагина (отчёт самого ``close``).
        """
        try:
            report = handle.close(budget_s)
        except Exception as exc:
            self._record_err()
            logger.warning(f"робот {self.entry.id!r}: запись потока не закрыта: {type(exc).__name__}: {exc}")
            return
        if report.survivors:
            self._record_err()
            logger.warning(f"робот {self.entry.id!r}: поток драйвера не вышел за срок: {', '.join(report.survivors)}")
            self._publish_error(TEXT_THREAD_SURVIVED)

    def _spawn_failed(self, thread_name: str, exc: Exception) -> dict:
        """Ответ на исключение ``spawn``: область закрыта / имя занято / прочее; тексты постоянные (К5)."""
        if isinstance(exc, ScopeClosedError):
            return {"status": "error", "message": TEXT_SCOPE_CLOSED}
        if isinstance(exc, ValueError):
            logger.error(f"робот {self.entry.id!r}: имя потока {thread_name!r} занято")
            return {"status": "error", "message": TEXT_SPAWN_NAME_BUSY}
        logger.error(f"робот {self.entry.id!r}: поток {thread_name!r} не запущен: {type(exc).__name__}: {exc}")
        return {"status": "error", "message": TEXT_SPAWN_FAILED}

    def _ensure_connected(self) -> bool:
        """Переподключение с порогом и лимитом попыток, как v1 (НР-1: только при ``desired_connected``)."""
        if self.is_connected:
            return True
        if not self.desired_connected:
            return False
        if self._activity_alive():
            return False
        # Замок — действие: идёт param_set / param_apply -> тихий выход до порога, счётчика и транспорта (следующий тик)
        if not self._param_lock.acquire(blocking=False):
            return False
        try:
            if self.is_connected:  # ручной connect() успел между проверкой выше и захватом замка
                return True
            now = self._clock()
            if now - self._last_reconnect < _RECONNECT_THROTTLE_SEC:
                return False
            self._last_reconnect = now
            self._record_reconnect()
            connected = self._connect_locked()
            if not self.desired_connected:
                self._close_after_disconnect()  # «Отключить» пришло во время подключения: сокет не оставляем
                return False
            if connected:
                self.reset_reconnect()
                return True
            self._note_reconnect_failed()
            return False
        finally:
            self._param_lock.release()

    # ------------------------------------------------------------------ #
    # Тик
    # ------------------------------------------------------------------ #

    def _read_tlm(self) -> list[int]:
        return [int(v) for v in self._transport.read_registers(_TLM_BASE, _TLM_COUNT)]

    def tick(self, stop_event: Any = None) -> dict | None:
        """Пульс -> телеметрия -> сверка метки -> ошибки -> snapshot (DESIGN п.4)."""
        if not self._ensure_connected():
            return self.snapshot(quality="bad")
        client = self._client
        err_before = self._stats["tx_err"]
        data: dict[str, Any] = {}
        try:
            client.kick_heartbeat()  # каждый тик: сторож робота взводится только изменением HB_PC
        except Exception as exc:
            self._record_err()
            logger.warning(f"робот {self.entry.id!r}: пульс HB_PC не записан: {type(exc).__name__}: {exc}")
            self._link_lost()
            return self.snapshot(quality="bad")
        tlm: list[int] | None = None
        try:
            t0 = self._clock()
            tlm = self._read_tlm()
            self._record_ok((self._clock() - t0) * 1000)
        except Exception as exc:
            self._record_err()
            logger.warning(f"робот {self.entry.id!r}: телеметрия не прочитана: {type(exc).__name__}: {exc}")
            self._link_lost()
            return self.snapshot(quality="bad")
        if tlm is not None:
            telemetry, free, encoder = _parse_tlm(tlm)
            data = {"telemetry": telemetry, "free": free, "encoder": encoder}
            if _w(tlm, "TLM_CFG_EPOCH") != self._epoch:
                self._resync_maybe(client)
        try:
            for ev in client.poll_errors():
                own = self._state.is_own_stop(ev.errno == ERR["E_ABORTED"], ev.seq)
                if own:
                    continue  # свой стоп jog — ожидаемый обрыв (Д1)
                text = ev.text if ev.missed <= 0 else f"{ev.text} (пропущено {ev.missed})"
                self._publish_error(text)
        except Exception as exc:
            self._record_err()
            logger.warning(f"робот {self.entry.id!r}: ошибки робота не прочитаны: {type(exc).__name__}: {exc}")
        if tlm is not None:
            self._dispatch(client, data["free"], stop_event)
        quality = "bad" if self._stats["tx_err"] > err_before else "good"
        return self.snapshot(data, quality=quality)

    # --- задания и возвраты (T3.7) ---

    def _link_lost(self) -> None:
        """Ошибка ввода-вывода в тике: связь считается оборванной, следующий тик переподключается.

        ``ModbusDevice`` помечает связь оборванной только на ``ModbusDriverError``; сырой ``OSError`` сокета
        (WinError 10053 после рестарта контроллера) оставляет ``is_connected == True`` навсегда — без этого сброса
        драйвер писал бы в мёртвый сокет каждый тик и не переподключался. Сокет закрывается, только пока нет живого
        потока поводка или исполнителя: их запись сама упадёт на том же сокете, тик закроет его после их выхода.
        """
        self._ready = False
        if self._activity_alive() or self._transport is None:
            return
        try:
            self._transport.disconnect()
        except Exception as exc:
            self._record_err()
            logger.warning(f"робот {self.entry.id!r}: сокет после обрыва не закрыт: {type(exc).__name__}: {exc}")

    def _close_after_disconnect(self) -> None:
        """``disconnect()`` отработал, пока тик открывал транспорт: закрыть его и снять готовность. Не бросает."""
        self._ready = False
        transport = self._transport
        if transport is None:
            return
        try:
            transport.disconnect()
        except Exception as exc:
            self._record_err()
            logger.warning(f"робот {self.entry.id!r}: сокет после отключения не закрыт: {type(exc).__name__}: {exc}")

    def _publish_error(self, text: str) -> None:
        self._pub(f"devices.state.{self.entry.id}.last_error", text)

    # ------------------------------------------------------------------ #
    # Операции
    # ------------------------------------------------------------------ #

    def call(self, op: str, args: dict) -> dict:
        handler = self._OPS.get(op)
        if handler is None:
            return {"status": "error", "message": f"Неизвестная операция робота: {op!r}"}
        try:
            return handler(self, args)
        except Exception as exc:
            self._record_err()
            return {"status": "error", "message": str(exc)}

    # --- задания ---

    # --- jog ---

    def _spawn_fn(self) -> Callable[..., IHandle]:
        """``spawn`` драйвера; None — ``RuntimeError`` (драйвер сам потоков не создаёт, T5.3 круг 2)."""
        if self._spawn is None:
            raise RuntimeError(TEXT_NO_SPAWN)
        return self._spawn

    # --- программы ---

    # ------------------------------------------------------------------ #
    # Операции движения и параметров (T5.3d, часть d1)
    # ------------------------------------------------------------------ #

    # ------------------------------------------------------------------ #
    # Snapshot
    # ------------------------------------------------------------------ #

    def snapshot(self, data: dict | None = None, quality: str | None = None) -> dict:
        """Snapshot со счётчиками заданий и возвратов (T3.7 п.11, по образцу v1); ключей ``mode`` / ``draw_*`` нет."""
        base: dict[str, Any] = {
            "queue_len": self._state.job_queue_len(),
            "jobs_sent": self.jobs_sent,
            "jobs_done": self.jobs_done,
            "jobs_failed": self.jobs_failed,
            "returns_done": self.returns_done,
            "returns_failed": self.returns_failed,
            "return_queued": self._state.return_queue_len(),
            "pick_lead_mm": self._pick_lead_mm,
        }
        if data:
            base.update(data)
        return super().snapshot(base, quality)


RobotDriverV2._OPS = OPS
