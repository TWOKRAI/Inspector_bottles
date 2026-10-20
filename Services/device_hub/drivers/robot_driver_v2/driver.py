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
from Services.device_hub.drivers.exchange_log import (
    TEXT_BAD_CONFIG,
    TEXT_BAD_GET_ARGS,
    TEXT_BAD_KNOBS,
    ExchangeLog,
    ExchangeLogTransport,
)
from Services.device_hub.drivers.robot_driver_v2.args import (
    _STORE_ERRORS,
    _BadArgs,
    _StoreIOError,
    _base_rev_arg,
    _bool_arg,
    _check_wire,
    _coord,
    _int_in,
    _is_int,
    _name_arg,
    _number_arg,
    _store_refusal,
    _strict_coord,
    _whole,
)
from Services.device_hub.drivers.robot_driver_v2.state import RobotState, _Job, _JogRun, _Place
from Services.device_hub.drivers.robot_driver_v2.texts import (
    TEXT_BAD_DO,
    TEXT_BAD_JOB_ARGS,
    TEXT_BAD_RANGE,
    TEXT_BAD_RETURN_ARGS,
    TEXT_BAD_STOP_LEVEL,
    TEXT_EPOCH_NOT_WRITTEN,
    TEXT_LEASE_LOST,
    TEXT_NO_ECHO_WINDOW,
    TEXT_NO_PROGRAM,
    TEXT_NO_SPAWN,
    TEXT_NO_STORE,
    TEXT_PARAM_DIVERGED,
    TEXT_PARAM_NO_REPLY,
    TEXT_SCOPE_CLOSED,
    TEXT_SPAWN_FAILED,
    TEXT_SPAWN_NAME_BUSY,
    TEXT_STOPPING,
    TEXT_STOP_UNCONFIRMED,
    TEXT_SYNCING,
    TEXT_THREAD_SURVIVED,
    TEXT_UNKNOWN_PARAM,
    TEXT_WDG_INTERVAL,
    _BUSY_REPLIES,
    _CLIENT_KEYS,
    _DO_CHANNELS,
    _HUB_POLL_DEFAULT_S,
    _JOB_QUEUE_MAXLEN,
    _LEASE_JOIN_S,
    _LEASE_PERIOD_FALLBACK_S,
    _NOT_CONNECTED,
    _ON_CONNECT_DEADLINE_S,
    _ON_CONNECT_POLL_S,
    _OPERATOR_ECHO_BUDGET_S,
    _PROCESS_STOP_DEFAULT_S,
    _PROGRAM_JOIN_S,
    _RECONNECT_THROTTLE_SEC,
    _STOP_NAMES,
    _TLM_BASE,
    _TLM_COUNT,
    _WIRE_SCALE,
    _next_thread_k,
)
from Services.device_hub.robot_data_ops import TEXT_BAD_ARGS, TEXT_STORE_ERROR
from Services.robot_comm.core.client_v2 import ClientV2Config, RobotClientV2, SyncCancelled
from Services.robot_comm.core.params_v2 import PARAMS, PARAM_ID, to_eng, to_raw
from Services.robot_comm.core.protocol_v2 import ERR, REG, STOP_LEVEL
from Services.robot_comm.errors import RevisionConflict, RobotAborted, RobotCommandError, RobotNak, RobotTimeout
from Services.robot_comm.programs import Point, compile_program
from Services.robot_comm.programs.generators import return_slot, toolchange
from Services.robot_comm.robot_data import (
    load_frames,
    load_params,
    load_points,
    load_program,
    param_bounds,
    save_params,
    save_points,
)
from Services.robot_comm.store import RobotDataStore

__all__ = ["RobotDriverV2"]


class _JobStopped(Exception):
    """``stop_event`` хаба взведён, пока тик ждёт завершения задания (DESIGN п.5)."""


def _s16(word: int) -> int:
    return word - 0x10000 if word >= 0x8000 else word


def _w(tlm: list[int], name: str) -> int:
    """Слово регистра ``name`` из блока TLM, прочитанного от ``TLM_PROTO_VER``."""
    return int(tlm[REG[name] - _TLM_BASE])


def _parse_tlm(tlm: list[int]) -> tuple[dict[str, Any], bool, int]:
    """Блок TLM -> (телеметрия с именами v1, free, encoder). DESIGN п.5."""
    telemetry = {
        "x_mm": _s16(_w(tlm, "TLM_X")) / _WIRE_SCALE,
        "y_mm": _s16(_w(tlm, "TLM_Y")) / _WIRE_SCALE,
        "z_mm": _s16(_w(tlm, "TLM_Z")) / _WIRE_SCALE,
        "rz_deg": _s16(_w(tlm, "TLM_RZ")) / _WIRE_SCALE,
        "moving": _w(tlm, "TLM_MOVING") == 1,
        "spd_pct": _w(tlm, "TLM_SPD_PCT"),
        "belt_mm_s": _s16(_w(tlm, "TLM_BELT_MMS")),
        "heartbeat": _w(tlm, "TLM_HB_ROBOT"),
        "servo": _w(tlm, "TLM_SERVO") == 1,
        "hand": _w(tlm, "TLM_HAND"),
        "miss_count": _w(tlm, "TLM_MISS_COUNT"),
    }
    free = _w(tlm, "TLM_ACTIVITY") == 0
    # TLM_ENC — два слова, младшее первым (порядок слов транспорта не используется), s32
    offset = REG["TLM_ENC"] - _TLM_BASE
    raw = (int(tlm[offset]) & 0xFFFF) | ((int(tlm[offset + 1]) & 0xFFFF) << 16)
    encoder = raw - 0x1_0000_0000 if raw >= 0x8000_0000 else raw
    return telemetry, free, encoder


class RobotDriverV2(BaseDeviceDriver):
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

    def _dispatch(self, client: RobotClientV2, free: bool, stop_event: Any) -> None:
        """Одно действие за тик (DESIGN п.4): возврат из очереди, иначе задание. Обе ветки требуют ``free``.

        «Захват свободен» и взятие задания — один переход ``take_next_action``: ``job_active`` ставится ДО
        ``cvt_job``, поэтому ``jog_hold`` / ``start_program`` между проверкой и записью видят ``_BUSY_JOB`` (R7).
        """
        if not free:
            return
        item, job = self._state.take_next_action()
        if item is not None:
            self._start_next_return(item)
        elif job is not None:
            self._run_next_job(client, job, stop_event)

    def _run_next_job(self, client: RobotClientV2, job: _Job, stop_event: Any) -> None:
        """CVT_JOB + ожидание завершения в потоке тика (R1); пульс — ``on_poll``. Исключения из тика не выходят."""
        x, y, z, ecap, place = job

        def on_poll(_tlm: Any) -> None:
            if stop_event is not None and stop_event.is_set():
                raise _JobStopped
            client.kick_heartbeat()

        try:
            flags = (1 if z != 0.0 else 0) | (2 if place is not None else 0)
            if place is not None:
                px, py, pz, turn = place
                prz = to_eng("P_PICK_RZ", self._values["P_PICK_RZ"]) + turn  # R3: v2 забирает под P_PICK_RZ
            else:
                px = py = pz = prz = 0.0
            try:
                res = client.cvt_job(ecap & 0xFFFFFFFF, x, y, z, flags, px, py, pz, prz)
            except RobotNak as exc:
                if exc.errno != ERR["E_BUSY"]:
                    raise
                self._state.requeue_job(job)  # робот занят — повтор следующим тиком (паритет v1)
                return
            self.jobs_sent += 1
            client.wait_done(res.seq, on_poll=on_poll)
            self.jobs_done += 1
            self._record_ok()
        except (RobotTimeout, _JobStopped) as exc:
            self.jobs_failed += 1
            try:
                # R9: HARD (SOFT на CVT отложился бы до точки захвата). Останов хаба — через защёлку без эха (H1):
                # стоп процесса уже записал HARD этому заданию; таймаут задания — стоп с эхом, как раньше
                if isinstance(exc, _JobStopped):
                    self._stop_latched(STOP_LEVEL["HARD"])
                else:
                    self._stop_and_wait(STOP_LEVEL["HARD"])
            except Exception as stop_exc:
                self._record_err()
                logger.warning(f"робот {self.entry.id!r}: стоп задания не доставлен: {type(stop_exc).__name__}")
            text = "останов хаба" if isinstance(exc, _JobStopped) else str(exc)
            self._publish_error(f"задание прервано: {text}")
        except (RobotNak, RobotCommandError) as exc:
            self.jobs_failed += 1  # RobotAborted — подкласс RobotCommandError; задание теряется (паритет v1)
            self._publish_error(exc.text)
        except ValueError as exc:
            self.jobs_failed += 1  # R8: аргумент вне провода — не обрыв связи
            self._publish_error(f"задание не отправлено: {exc}")
        except Exception as exc:
            self.jobs_failed += 1
            self._record_err()
            logger.warning(f"робот {self.entry.id!r}: задание прервано сбоем связи: {type(exc).__name__}: {exc}")
            self._link_lost()  # урок fd5c003e8: сырой OSError оставляет is_connected == True
        finally:
            self._state.job_finished()

    def _start_next_return(self, item: tuple[float, float, float]) -> None:
        """Возврат, взятый тиком из очереди, — программой ``return_slot`` на потоке исполнителя (R2, DESIGN п.6)."""
        x, y, z = item
        v = self._values
        slot = Point(
            name="return_slot",
            x=x,
            y=y,
            z=z if z != 0.0 else to_eng("P_PLACE_Z", v["P_PLACE_Z"]),
            rz=to_eng("P_PICK_RZ", v["P_PICK_RZ"]),
            hand=int(v["P_HAND"]),
        )
        try:
            res = self.start_return(slot)
        except Exception as exc:  # H2: возврат не теряется молча — отказ считается и виден
            res = {"status": "error", "message": str(exc)}
        if res.get("status") == "ok":
            return
        if res in _BUSY_REPLIES:
            self._state.requeue_return(item)  # захват перехвачен между секциями — повтор следующим тиком
            return
        self._state.return_failed()
        self._publish_error(str(res.get("message")))

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

    def _end_sync(self) -> None:
        self._state.end_sync()

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

    def _sync_cancelled(self) -> bool:
        """Отмена синхронизации: остановка (``stopping`` / ``shutdown``) — после стопа параметры не пишутся."""
        return self._state.sync_cancelled()

    def _sync_on_connect(self, client: RobotClientV2) -> bool:
        """``_connect_locked``: ``_load_params()`` + ``sync_params`` под флагом ``syncing``; ``_param_lock`` уже держит
        вызывающий (``connect`` / ``_ensure_connected``). Порядок замков: ``_param_lock`` -> замок состояния.

        False — синхронизации не было: активность появилась после ранней проверки ``connect``.
        """
        if not self._state.begin_sync():
            return False
        old = self._values, self._epoch
        try:
            self._values, self._epoch = self._load_params_io()
            client.sync_params(self._values, self._epoch, cancelled=self._sync_cancelled)
        except SyncCancelled:  # остановка посреди синхронизации: не синхронизировано, метка прежняя, не ошибка
            self._values, self._epoch = old
            return False
        finally:
            self._end_sync()
        return True

    def _load_params_io(self) -> tuple[dict[str, int], int]:
        """``_load_params`` с диском: ``OSError`` хранилища -> лог с полным текстом и ``_StoreIOError``."""
        try:
            return self._load_params()
        except OSError as exc:
            logger.warning(f"робот {self.entry.id!r}: ошибка хранилища данных: {type(exc).__name__}: {exc}")
            raise _StoreIOError from None

    def _resync_maybe(self, client: RobotClientV2) -> None:
        """Метка робота не равна метке ПК -> sync_params снова (§11.4 п.4), только когда робот свободен.

        ``_param_lock`` берётся не блокируя (идёт ``param_set`` / ``param_apply`` — тик не стоит на замке, пульс
        сторожа не пропадает; метку обновит сам ``param_set``). Под замком метка и ``TLM_ACTIVITY`` читаются заново:
        ``param_set`` мог записать метку между чтением тика и захватом замка (равны — выхода без sync достаточно),
        а ``jog_step`` отвечает после ACK без флага — при ``TLM_ACTIVITY != 0`` ``PARAM_SET`` получил бы ``E_BUSY``.
        ``_last_resync`` ставится только после того, как проверка активности прошла.
        """
        if not self._param_lock.acquire(blocking=False):
            return
        try:
            try:
                tlm = self._read_tlm()
            except Exception as exc:  # связь разберёт тик по своему чтению
                self._record_err()
                logger.warning(f"робот {self.entry.id!r}: метка не перечитана: {type(exc).__name__}: {exc}")
                return
            if _w(tlm, "TLM_CFG_EPOCH") == self._epoch or _w(tlm, "TLM_ACTIVITY") != 0:
                return
            now = self._clock()
            if now - self._last_resync < _RECONNECT_THROTTLE_SEC and self._last_resync:
                return
            started = self._state.begin_sync()
            if not started:
                return
            self._last_resync = now
            old = self._values, self._epoch
            try:
                self._values, self._epoch = self._load_params_io()
                client.sync_params(self._values, self._epoch, cancelled=self._sync_cancelled)
            except SyncCancelled:  # остановка посреди синхронизации: метка прежняя, не ошибка
                self._values, self._epoch = old
            except _StoreIOError:
                self._record_err()
                self._publish_error(TEXT_STORE_ERROR)
            except Exception as exc:
                self._record_err()
                self._publish_error(f"синхронизация параметров не удалась: {type(exc).__name__}: {exc}")
            finally:
                self._end_sync()
        finally:
            self._param_lock.release()

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

    def _op_get_telemetry(self, _args: dict) -> dict:
        if not self.is_connected:
            return dict(_NOT_CONNECTED)
        telemetry, free, encoder = _parse_tlm(self._read_tlm())
        return {
            "status": "ok",
            "telemetry": telemetry,
            "free": free,
            "encoder": encoder,
            "queue_len": self._state.job_queue_len(),
        }

    # --- задания ---

    def _op_enqueue_job(self, args: dict) -> dict:
        """Задание CVT_JOB в очередь (R1, R3-R6, R8): ключи v1 {x_mm, y_mm, z_mm?, e_capture?, place_x?, place_y?,
        place_z?, place_rz?}; ``place_rz`` — доворот к ``P_PICK_RZ``. Плохой ввод -> постоянный текст, очередь цела."""
        try:
            x, y = _coord(args, "x_mm"), _coord(args, "y_mm")
            z = _coord(args, "z_mm", 0.0)  # R6: 0 — умолчание прошивки P_PICK_Z (бит0 = 0)
            place: _Place | None = None
            if args.get("place_x") is not None and args.get("place_y") is not None:
                turn = _coord(args, "place_rz", 0.0)
                _check_wire(to_eng("P_PICK_RZ", self._values["P_PICK_RZ"]) + turn, "place_rz")
                place = (_coord(args, "place_x"), _coord(args, "place_y"), _coord(args, "place_z", 0.0), turn)
            raw_ecap = args.get("e_capture")
            ecap = None if raw_ecap is None else _whole(raw_ecap, "e_capture")
        except _BadArgs:
            return {"status": "error", "message": TEXT_BAD_JOB_ARGS, "queue_len": self._state.job_queue_len()}
        if not self.is_connected:
            return {**_NOT_CONNECTED, "queue_len": self._state.job_queue_len()}
        if ecap is None:
            ecap = _parse_tlm(self._read_tlm())[2]  # R5: энкодер сейчас, в потоке команды (s32)
        if self._pick_lead_mm != 0.0:
            # R4: ход ленты на импульс — P_BELT_FACTOR × 1e-5 мм/имп (не константа v1)
            ecap -= round(self._pick_lead_mm / (self._values["P_BELT_FACTOR"] * 1e-5))
        n = self._state.enqueue_job((x, y, z, ecap, place))  # maxlen: старейшее вытесняется (паритет v1)
        return {"status": "ok", "queue_len": n}

    def _op_return_job(self, args: dict) -> dict:
        """Возврат из слота {x_mm, y_mm, z_mm?} в очередь возвратов; исполнение — тиком (R2, DESIGN п.3).

        Без ``spawn`` — ``RuntimeError`` до очереди: возврат идёт программой на потоке исполнителя (H2).
        """
        self._spawn_fn()
        try:
            item = (_coord(args, "x_mm"), _coord(args, "y_mm"), _coord(args, "z_mm", 0.0))
        except _BadArgs:
            return {
                "status": "error",
                "message": TEXT_BAD_RETURN_ARGS,
                "return_queue_len": self._state.return_queue_len(),
            }
        if not self.is_connected:
            return {**_NOT_CONNECTED, "return_queue_len": self._state.return_queue_len()}
        n = self._state.enqueue_return(item)
        return {"status": "ok", "return_queue_len": n}

    # --- jog ---

    def _op_abort(self, args: dict) -> dict:
        """Стоп оператора {mode: 1|2|3 или "SOFT"|"HARD"|"HALT"}: тело — ``_operator_stop``; ответ прежней формы."""
        result = self._operator_stop(args.get("mode", STOP_LEVEL["SOFT"]))
        if result["status"] != "ok":
            return result
        return {"status": "ok", "mode": result["level"]}

    def _operator_stop(self, raw_level: Any) -> dict:
        """Общее тело ``stop`` и ``abort`` (T5.3d DESIGN 3): запись ``STOP_REQ`` через ``_write_stop`` (мимо защёлки
        стопа процесса, но с её учётом), затем опрос эха до ``t0 + 0,8 с``. Замков драйвера не берёт, ``_stopping`` не
        ставит. Итог: ``{"status": "ok", "level": <int>, "echo": bool}``; нет эха к сроку — ``echo: False`` без ошибки
        (отложенный SOFT до цели хода — норма протокола). Плохой уровень — ``TEXT_BAD_STOP_LEVEL``, робот не тронут."""
        t0 = time.monotonic()
        if isinstance(raw_level, str) and raw_level.upper() in STOP_LEVEL:
            level = STOP_LEVEL[raw_level.upper()]
        elif isinstance(raw_level, int) and not isinstance(raw_level, bool) and raw_level in STOP_LEVEL.values():
            level = raw_level
        else:
            return {"status": "error", "message": TEXT_BAD_STOP_LEVEL}
        client = self._client
        if client is None:
            return dict(_NOT_CONNECTED)
        value = self._write_stop(level)  # ошибка записи — наружу: стоп не доставлен
        try:
            client.await_stop_echo(value, value & 3, deadline=t0 + _OPERATOR_ECHO_BUDGET_S)
        except RobotTimeout:
            return {"status": "ok", "level": level, "echo": False}
        return {"status": "ok", "level": level, "echo": True}

    def _spawn_fn(self) -> Callable[..., IHandle]:
        """``spawn`` драйвера; None — ``RuntimeError`` (драйвер сам потоков не создаёт, T5.3 круг 2)."""
        if self._spawn is None:
            raise RuntimeError(TEXT_NO_SPAWN)
        return self._spawn

    def _op_jog_hold(self, args: dict) -> dict:
        """Подтверждение удержания: нет своего jog -> JOG_CONT и поток поводка; есть -> только ``_last_hold``.

        Без ``spawn`` — ``RuntimeError`` до любой записи.
        """
        spawn = self._spawn_fn()
        try:
            direction, speed = _int_in(args, "dir", 1, 8), _int_in(args, "spd", 1, 100)
        except _BadArgs:
            return {"status": "error", "message": TEXT_BAD_ARGS}
        decision = self._state.jog_hold_check()  # свой jog держится -> продление (last_hold) без JOG_CONT
        if decision == "hold":
            return {"status": "ok"}
        if decision is not None:
            return decision
        if not self.is_connected:
            return dict(_NOT_CONNECTED)
        client = self._client
        # Переход jog: стоп в полёте держит этот замок — новый JOG_CONT уйдёт после возврата stop() (п.9)
        with self._jog_tx_lock:
            # Д4: допуск ставит jog_starting — до записи jog start_program видит переход как jog (_BUSY_JOG)
            decision, prev = self._state.jog_hold_admit()
            if decision == "hold":
                return {"status": "ok"}
            if decision is not None:
                return decision
            try:
                if prev is not None and prev.stop_requested and not prev.stop_sent:
                    self._stop_jog_locked(prev)  # release / окно ещё не дослали стоп — шлём его сами, один раз
                result = client.jog_cont(direction, speed)
                run = _JogRun(seq=result.seq)
                # _last_hold — ДО spawn: spawn запускает поток при вызове, поток читает _last_hold (К3)
                # H-A: запись движения — новое поколение защёлки ПОСЛЕ неё (стоп prev выше её не покрывает)
                stopping = self._state.jog_started(run)
                if stopping:
                    # H-B: стоп процесса не взял замок перехода и записан, пока JOG_CONT был в полёте, — он мог лечь
                    # раньше движения. Стоп этого seq пишется здесь, мимо защёлки; поводок не запускается.
                    # Единственное исключение из «одна запись стопа процесса на робота»: в этой гонке их две.
                    self._state.jog_aborted_by_stop(run)
                    try:
                        self._write_stop(STOP_LEVEL["SOFT"], run)
                    except Exception as exc:
                        self._record_err()
                        logger.warning(
                            f"робот {self.entry.id!r}: стоп jog после остановки не доставлен: "
                            f"{type(exc).__name__}: {exc}"
                        )
                    return {"status": "error", "message": TEXT_STOPPING}
                thread_name = f"{self.entry.id}-lease-{_next_thread_k()}"
                try:
                    run.handle = spawn(lambda ev: self._lease_loop(run, ev), name=thread_name)
                except Exception as exc:
                    # JOG_CONT уже подтверждён: без поводка робот остался бы в JOG_CONT, а его E_ABORTED ушёл бы в
                    # last_error как чужая ошибка — стоп шлём сами (seq — в _own_stops), затем откат (К5)
                    try:
                        self._stop_jog_locked(run)
                    except Exception as stop_exc:
                        self._record_err()
                        logger.warning(
                            f"робот {self.entry.id!r}: стоп jog после отказа spawn не доставлен: "
                            f"{type(stop_exc).__name__}: {stop_exc}"
                        )
                    self._state.jog_spawn_failed(run, prev)
                    return self._spawn_failed(thread_name, exc)
            finally:
                self._state.jog_start_done()
        return {"status": "ok", "seq": result.seq}

    def _op_jog_release(self, _args: dict) -> dict:
        """Перестать писать поводок и явно остановить свой jog (Л4); нет своего jog -> ok без записи стопа."""
        # T3.7 (ревью р.1): jog_stopping ставится вместе с пометками — до возврата стопа тик не берёт задание
        run = self._state.jog_release_begin()
        if run is None:
            return {"status": "ok"}
        try:
            # handle is None: spawn ещё не вернулся — без close; _stop_jog ждёт _jog_tx_lock, который jog_hold держит
            # до возврата spawn, поток поводка видит run.released и выходит сам (К4). close — вне _jog_tx_lock:
            # поток поводка на пути Д3 сам может ждать этот замок
            handle = run.handle
            if handle is not None:
                self._close_thread(handle, _LEASE_JOIN_S)
            self._stop_jog(run)
        finally:
            self._state.jog_release_done()
        return {"status": "ok"}

    def _stop_jog(self, run: _JogRun) -> None:
        with self._jog_tx_lock:
            if not run.stop_sent:
                self._stop_jog_locked(run)

    def _stop_jog_locked(self, run: _JogRun) -> None:
        """Под ``_jog_tx_lock``: стоп SOFT своего jog с ожиданием эха. Seq — в множество своих стопов ДО записи (Д1),
        ``stop_sent`` — сразу после записи (П4: флаг отражает запись, эхо его не держит)."""
        self._stop_and_wait(STOP_LEVEL["SOFT"], run)  # ошибка транспорта / RobotTimeout — наружу, не глушится

    def _lease_loop(self, run: _JogRun, ev: threading.Event) -> None:
        """Поток поводка: пока окно удержания не истекло, нет release и область открыта — ``jog_lease()`` раз в период.

        Окно истекло или область закрывается (``ev``) -> стоп шлёт сам поток (без close своей записи).
        Выход по любой причине снимает ``active``.
        """
        client = self._client
        period = client.jog_lease_period_s or _LEASE_PERIOD_FALLBACK_S
        try:
            while True:
                # окно удержания / ev -> stop_requested; причина для лога (D-L1) и «после начала остановки»
                decision, reason, late = self._state.lease_check(run, ev)
                if decision == "released":
                    return  # стоп шлёт release
                if decision == "stop":
                    # то же, что ``_stop_jog`` (Д3): замок и условие прежние, но «писал ли поток» известно для лога
                    with self._jog_tx_lock:
                        wrote = not run.stop_sent
                        if wrote:
                            self._stop_jog_locked(run)
                    if wrote:
                        # вне обоих замков; нет строки при release, уже записанном стопе и исключении (warning ниже)
                        suffix = " после начала остановки" if late else ""
                        logger.info(f"робот {self.entry.id!r}: jog остановлен поводком{suffix}: {reason}")
                    return
                client.jog_lease()
                run.wake.wait(period)
        except Exception as exc:
            self._record_err()
            logger.warning(f"робот {self.entry.id!r}: поводок jog прерван: {type(exc).__name__}: {exc}")
            self._publish_error(TEXT_LEASE_LOST)
        finally:
            self._state.lease_exit(run)

    # --- программы ---

    def start_program(self, program: Any, points: Mapping[str, Point], frames: Any = None, *, name: str) -> dict:
        """Запустить программу в потоке исполнителя; один прогон за раз (DESIGN п.6)."""
        return self._launch(program, points, frames, name=name, kind="program")

    def _launch(self, program: Any, points: Mapping[str, Point], frames: Any, *, name: str, kind: str) -> dict:
        """Захват (программа / задание / jog) -> компиляция -> поток исполнителя. ``kind`` уходит в счётчики
        возвратов ``_program_loop`` (T3.7 DESIGN п.7). Без ``spawn`` — ``RuntimeError`` до захвата."""
        spawn = self._spawn_fn()
        # is_connected зовётся под замком состояния последней проверкой, как раньше
        refusal = self._state.admit_launch(lambda: self.is_connected)
        if refusal is not None:
            return refusal
        try:
            scenario = compile_program(program, points, frames or {}, self._ws_params())
            total = len(scenario.records)
        except Exception as exc:
            self._state.launch_failed()
            return {"status": "error", "message": str(exc)}
        thread_name = f"{self.entry.id}-prog-{_next_thread_k()}"
        try:
            handle = spawn(lambda ev: self._program_loop(scenario, name, total, kind), name=thread_name)
        except Exception as exc:
            self._state.launch_failed()
            return self._spawn_failed(thread_name, exc)
        self._state.program_started(handle)
        return {"status": "ok", "name": name, "total": total}

    def start_return(self, slot: Point, **kw: Any) -> dict:
        """Возврат из слота с домом в конце: ``return_slot(slot, home=<дом из параметров>, **kw)``."""
        try:
            gp = return_slot(slot, home=self._home_point(), **kw)
        except Exception as exc:
            return {"status": "error", "message": str(exc)}
        return self._launch(gp.program, gp.points, None, name=gp.program.name, kind="return")

    def start_toolchange(self, current: int, target: int, points: Mapping[str, Point], **kw: Any) -> dict:
        """Смена инструмента с домом в конце: ``toolchange(..., home=<дом из параметров>)``."""
        try:
            gp = toolchange(current, target, points, home=self._home_point(), **kw)
        except Exception as exc:
            return {"status": "error", "message": str(exc)}
        return self.start_program(gp.program, gp.points, None, name=gp.program.name)

    def _program_loop(self, scenario: Any, name: str, total: int, kind: str = "program") -> None:
        path = f"devices.state.{self.entry.id}.program"
        state = {"name": name, "state": "running", "done": 0, "total": total, "error": None}
        resent = [False]  # повтор стопа в on_progress — один раз на прогон

        def on_progress(done: int, all_records: int) -> None:
            state["done"], state["total"] = done, all_records
            self._pub(path, dict(state))
            # Микроокно (К1): стоп, записанный между проверкой stopping и взятием поколения в run_chunks, прогон
            # не видит — повторяем его при первом же опросе. Повтор привязан к прогону и идёт мимо защёлки стопа
            # процесса (та запись удачна, но могла лечь до g0 прогона); только запись, без эха
            level = self._state.stop_resend_level(resent[0])
            if level:
                resent[0] = True  # локальная переменная потока исполнителя
            client = self._client
            if level and client.stop_generation != client.run_stop_base:
                level = 0  # стоп записан после g0: прогон видит его сам, повтор дал бы вторую запись
            if level:
                try:
                    self._write_stop(level)
                except Exception as exc:
                    self._record_err()
                    logger.warning(f"робот {self.entry.id!r}: повтор стопа программы не доставлен: {exc}")

        try:
            self._pub(path, dict(state))
            stopping = self._state.is_stopping()
            if stopping:
                state["state"] = "aborted"  # стоп пришёл до первого хода: run_chunks не зовём
            else:
                self._client.run_chunks(scenario, params=self._ws_params(), on_progress=on_progress)
                state["state"], state["done"] = "done", state["total"]
        except RobotAborted:
            state["state"] = "aborted"
        except Exception as exc:
            self._record_err()
            state["state"], state["error"] = "failed", f"программа прервана ошибкой: {type(exc).__name__}: {exc}"
            logger.warning(f"робот {self.entry.id!r}: программа {name!r}: {state['error']}")
        finally:
            try:
                # Итог публикуется ДО снятия program_active: robot_program_run может прийти сразу после (DESIGN 7)
                self._pub(path, dict(state))
            finally:
                self._state.program_finished(kind, state["state"] == "done")

    # ------------------------------------------------------------------ #
    # Операции движения и параметров (T5.3d, часть d1)
    # ------------------------------------------------------------------ #

    def _motion_refusal(self, *, syncing: bool = False) -> dict | None:
        """Отказ занятости для движения и записи параметров: останов, программа, задание, jog (и синхронизация)."""
        return self._state.motion_refusal(syncing)

    def _op_stop(self, args: dict) -> dict:
        """Стоп оператора {level}: занятость не проверяет; ответ ``{"status", "level": <ИМЯ>, "echo": bool}``."""
        result = self._operator_stop(args.get("level", STOP_LEVEL["SOFT"]))
        if result["status"] != "ok":
            return result
        return {"status": "ok", "level": _STOP_NAMES[result["level"]], "echo": result["echo"]}

    def _op_servo(self, args: dict) -> dict:
        try:
            on = _bool_arg(args, "on")
        except _BadArgs:
            return {"status": "error", "message": TEXT_BAD_ARGS}
        refusal = self._motion_refusal()
        if refusal is not None:
            return refusal
        if not self.is_connected:
            return dict(_NOT_CONNECTED)
        self._client.servo(on)
        return {"status": "ok"}

    def _op_do_set(self, args: dict) -> dict:
        try:
            on = _bool_arg(args, "on")
            ch = args.get("ch")
            if type(ch) is not int:
                raise _BadArgs("ch")
        except _BadArgs:
            return {"status": "error", "message": TEXT_BAD_ARGS}
        if ch not in _DO_CHANNELS:
            return {"status": "error", "message": TEXT_BAD_DO}
        refusal = self._motion_refusal()
        if refusal is not None:
            return refusal
        if not self.is_connected:
            return dict(_NOT_CONNECTED)
        self._client.do_set(ch, on)
        return {"status": "ok"}

    def _op_jog_step(self, args: dict) -> dict:
        """JOG_STEP {dx, dy, dz=0, drz=0, spd 1..100}: ``done_seq``-команда — отказ при программе / jog / задании /
        синхронизации; ответ после ACK, без ожидания DONE."""
        try:
            dx, dy = _strict_coord(args, "dx"), _strict_coord(args, "dy")
            dz, drz = _strict_coord(args, "dz", 0.0), _strict_coord(args, "drz", 0.0)
            speed = _int_in(args, "spd", 1, 100)
        except _BadArgs:
            return {"status": "error", "message": TEXT_BAD_ARGS}
        refusal = self._motion_refusal(syncing=True)
        if refusal is not None:
            return refusal
        if not self.is_connected:
            return dict(_NOT_CONNECTED)
        result = self._client.jog_step(dx, dy, dz, drz, speed)
        return {"status": "ok", "seq": result.seq}

    def _store_call[T](self, fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """Вызов хранилища: ``OSError`` (диск) -> лог с полным текстом и ``_StoreIOError`` (ответ — константа)."""
        try:
            return fn(*args, **kwargs)
        except OSError as exc:
            logger.warning(f"робот {self.entry.id!r}: ошибка хранилища данных: {type(exc).__name__}: {exc}")
            raise _StoreIOError from None

    def _op_point_capture(self, args: dict) -> dict:
        """Поза из TLM -> ``Point(frame=None)`` -> вставка в ``points.yaml``; ответ после записи файла (О9-а)."""
        try:
            name, base_rev = _name_arg(args, "name"), _base_rev_arg(args)
        except _BadArgs:
            return {"status": "error", "message": TEXT_BAD_ARGS}
        store = self._store
        if store is None:
            return {"status": "error", "message": TEXT_NO_STORE}
        if not self.is_connected:
            return dict(_NOT_CONNECTED)
        telemetry, _free, _encoder = _parse_tlm(self._read_tlm())
        point = Point(
            name=name,
            x=telemetry["x_mm"],
            y=telemetry["y_mm"],
            z=telemetry["z_mm"],
            rz=telemetry["rz_deg"],
            hand=telemetry["hand"],
            frame=None,
        )
        try:
            points, _rev = self._store_call(load_points, store, self.entry.id)
            points[name] = point
            rev = self._store_call(save_points, store, self.entry.id, points, base_rev=base_rev)
        except _STORE_ERRORS as exc:
            return _store_refusal(exc)
        return {"status": "ok", "point": point.to_dict(), "rev": rev}

    def _op_program_run(self, args: dict) -> dict:
        """Программа, точки и СК из хранилища -> ``start_program``; ответ сразу, ход — в потоке исполнителя."""
        try:
            name = _name_arg(args, "name")
        except _BadArgs:
            return {"status": "error", "message": TEXT_BAD_ARGS}
        store = self._store
        if store is None:
            return {"status": "error", "message": TEXT_NO_STORE}
        try:
            program, _rev = self._store_call(load_program, store, self.entry.id, name)
            if program is None:
                return {"status": "error", "message": TEXT_NO_PROGRAM}
            points, _points_rev = self._store_call(load_points, store, self.entry.id)
            frames, _frames_rev = self._store_call(load_frames, store, self.entry.id)
        except _STORE_ERRORS as exc:
            return _store_refusal(exc)
        return self.start_program(program, points, frames, name=name)

    def _op_program_abort(self, _args: dict) -> dict:
        """Программа идёт -> ТОЛЬКО запись SOFT (``_write_stop``), без эха: подтверждение — итог ``.program``
        ``aborted``. Программы нет -> ``stopped: False``, ``STOP_REQ`` не пишется. ``_stopping`` не ставится."""
        running = self._state.program_running()
        if not running:
            return {"status": "ok", "stopped": False}
        self._write_stop(STOP_LEVEL["SOFT"])
        return {"status": "ok", "stopped": True}

    def _param_gate(self) -> dict | None:
        """Взять ``_param_lock`` без блокировки. Отказ (замок занят, останов или ``syncing``) — ответ; успех — None,
        замок взят, вызывающий отпускает его в ``finally``. Блокирующий захват стоял бы всю синхронизацию на
        командном потоке."""
        if not self._param_lock.acquire(blocking=False):
            return {"status": "error", "message": TEXT_SYNCING}
        refusal = self._state.param_refusal()
        if refusal is not None:
            self._param_lock.release()
            return {"status": "error", "message": refusal}
        return None

    def _op_param_set(self, args: dict) -> dict:
        """PARAM_SET {name, value, base_rev}: границы -> робот -> метка -> файл -> ``self._values`` / ``self._epoch``.

        Порядок (§11.4 «файл — правда»): значение в робота ДО файла; сбой записи значения без NAK (таймаут, обрыв) или
        сбой метки после ACK значения — откат значения роботу, ответ-ошибка, файл и ``self._epoch`` не тронуты; сбой
        записи файла — ``self._epoch`` прежний, следующий тик видит расхождение меток и возвращает роботу значения
        файла."""
        try:
            name, base_rev = _name_arg(args, "name"), _base_rev_arg(args)
            value = _number_arg(args, "value")
        except _BadArgs:
            return {"status": "error", "message": TEXT_BAD_ARGS}
        store = self._store
        if store is None:
            return {"status": "error", "message": TEXT_NO_STORE}
        if name not in PARAM_ID or name == "P_CONFIG_EPOCH":
            return {"status": "error", "message": TEXT_UNKNOWN_PARAM}
        try:
            raw = to_raw(name, value)
        except OverflowError:  # 1.7e308 * scale -> inf
            return {"status": "error", "message": TEXT_BAD_ARGS}
        low, high = param_bounds(name)  # имя проверено выше: PARAM_ID без P_CONFIG_EPOCH
        if not low <= raw <= high:
            return {"status": "error", "message": TEXT_BAD_RANGE}
        if not self.is_connected:
            return dict(_NOT_CONNECTED)
        refusal = self._param_gate()
        if refusal is not None:
            return refusal
        try:
            return self._param_set_locked(store, name, raw, base_rev)
        except _STORE_ERRORS as exc:
            return _store_refusal(exc)
        finally:
            self._param_lock.release()

    def _param_set_locked(self, store: RobotDataStore, name: str, raw: int, base_rev: str | None) -> dict:
        """Тело ``param_set`` под ``_param_lock``."""
        old_values, old_epoch = dict(self._values), self._epoch  # владелец — _param_lock (T5.3f Q6)
        current_rev = self._store_call(load_params, store, self.entry.id).rev
        if current_rev != base_rev:
            raise RevisionConflict(current_rev)  # робот не тронут
        client = self._client
        old_raw = old_values[name]
        try:
            client.param_set(name, raw)
        except RobotNak:
            raise  # робот ответил отказом: значение не принято, файл не тронут
        except Exception as exc:
            # Исход записи неизвестен (таймаут, обрыв: робот мог применить, ответ потерян) — как сбой метки: значение
            # файла возвращается роботу, метка и файл не тронуты
            self._record_err()
            logger.warning(f"робот {self.entry.id!r}: запись параметра без ответа: {type(exc).__name__}: {exc}")
            self._roll_back_param(client, name, old_raw, TEXT_PARAM_NO_REPLY)
            return {"status": "error", "message": TEXT_PARAM_NO_REPLY}
        new_epoch = old_epoch % 65535 + 1
        try:
            client.param_set("P_CONFIG_EPOCH", new_epoch)
        except Exception as exc:
            self._record_err()
            logger.warning(f"робот {self.entry.id!r}: метка параметров не записана: {type(exc).__name__}: {exc}")
            self._roll_back_param(client, name, old_raw, TEXT_EPOCH_NOT_WRITTEN)
            return {"status": "error", "message": TEXT_EPOCH_NOT_WRITTEN}
        new_values = {**old_values, name: raw}
        # Запись файла упала -> исключение наружу, self._epoch прежний: тик увидит расхождение меток (§11.4 п.4)
        rev = self._store_call(save_params, store, self.entry.id, new_values, new_epoch, base_rev=base_rev)
        self._values, self._epoch = new_values, new_epoch  # владелец — _param_lock (T5.3f Q6)
        self._pub(
            f"devices.state.{self.entry.id}.params",
            {
                "epoch": new_epoch,
                "rev": rev,
                "values": {key: {"raw": r, "value": float(to_eng(key, r))} for key, r in new_values.items()},
            },
        )
        return {
            "status": "ok",
            "name": name,
            "raw": raw,
            "value": float(to_eng(name, raw)),
            "epoch": new_epoch,
            "rev": rev,
        }

    def _roll_back_param(self, client: RobotClientV2, name: str, old_raw: int, failed_text: str) -> None:
        """Одна попытка вернуть роботу значение файла; итог — в ``last_error``: ``failed_text`` (откат прошёл) или
        ``TEXT_PARAM_DIVERGED`` (не прошёл: робот и файл расходятся)."""
        try:
            client.param_set(name, old_raw)
        except Exception as exc:
            self._record_err()
            logger.warning(f"робот {self.entry.id!r}: откат параметра не прошёл: {type(exc).__name__}: {exc}")
            self._publish_error(TEXT_PARAM_DIVERGED)
        else:
            self._publish_error(failed_text)

    def _op_param_apply(self, _args: dict) -> dict:
        """PARAM_APPLY: параметры класса ``reinit`` вступают в силу; под ``_param_lock`` (не при синхронизации)."""
        if not self.is_connected:
            return dict(_NOT_CONNECTED)
        refusal = self._param_gate()
        if refusal is not None:
            return refusal
        try:
            self._client.param_apply()
        finally:
            self._param_lock.release()
        return {"status": "ok"}

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


RobotDriverV2._OPS = {
    "jog_hold": RobotDriverV2._op_jog_hold,
    "jog_release": RobotDriverV2._op_jog_release,
    "get_telemetry": RobotDriverV2._op_get_telemetry,
    "enqueue_job": RobotDriverV2._op_enqueue_job,
    "return_job": RobotDriverV2._op_return_job,
}
RobotDriverV2._OPS["abort"] = RobotDriverV2._op_abort  # T5.3 круг 2: стоп оператора, мимо защёлки


# --- Журнал обмена (T5.6): две операции отдельным блоком, литерал _OPS выше не тронут ---


def _op_exchange_log_get(drv: RobotDriverV2, args: dict) -> dict:
    """Строки журнала обмена {since_seq=0, limit=200} и состояние; работает и без связи с роботом.

    Плохой аргумент — постоянный текст отказа (R8), счётчик ошибок обмена не растёт.
    """
    since_seq, limit = args.get("since_seq", 0), args.get("limit", 200)
    if not (_is_int(since_seq) and _is_int(limit)) or since_seq < 0 or limit < 1:
        return {"status": "error", "message": TEXT_BAD_GET_ARGS}
    return {"status": "ok", **drv._exchange_log.get(since_seq=since_seq, limit=limit)}


def _op_exchange_log_set(drv: RobotDriverV2, args: dict) -> dict:
    """Ручки журнала {enabled?, periodic?, clear?} без переподключения; ответ — состояние без строк."""
    knobs = {key: args.get(key) for key in ("enabled", "periodic", "clear")}
    if any(v is not None and not isinstance(v, bool) for v in knobs.values()):
        return {"status": "error", "message": TEXT_BAD_KNOBS}
    return {"status": "ok", **drv._exchange_log.set(**knobs)}


_EXCHANGE_OPS = {
    "exchange_log_get": _op_exchange_log_get,
    "exchange_log_set": _op_exchange_log_set,
}
RobotDriverV2._OPS.update(_EXCHANGE_OPS)


# --- Операции движения и параметров (T5.3d d1): отдельным блоком, литерал _OPS и _EXCHANGE_OPS (T5.6) не тронуты ---

RobotDriverV2._OPS.update(
    {
        "stop": RobotDriverV2._op_stop,
        "servo": RobotDriverV2._op_servo,
        "do_set": RobotDriverV2._op_do_set,
        "jog_step": RobotDriverV2._op_jog_step,
        "point_capture": RobotDriverV2._op_point_capture,
        "param_set": RobotDriverV2._op_param_set,
        "param_apply": RobotDriverV2._op_param_apply,
        "program_run": RobotDriverV2._op_program_run,
        "program_abort": RobotDriverV2._op_program_abort,
    }
)
