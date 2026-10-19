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

Stability: lite

Потоки (DESIGN п.9). Замок драйвера ``_flags_lock`` — только на флаги (``_busy``, ``_last_hold``, состояние jog,
множество своих стопов), вокруг вызовов клиента не держится: ``ModbusDevice`` сериализует RLock-ом, а
``stop`` / ``kick_heartbeat`` / ``jog_lease`` / ``poll_errors`` нарочно минуют замок mailbox клиента. Второй замок
``_jog_tx_lock`` — только для переходов jog: ``client.jog_cont`` в ``jog_hold`` и ``client.stop(SOFT)`` стопа jog.
Тик, исполнитель и ``poll_errors`` его не берут. Путь ``connect`` и повторная синхронизация не идут, пока жив поток
поводка или исполнителя.

Задания (T3.7). Очереди заданий и возвратов дренирует тик: одно действие за тик, только при свободном захвате.
Флаг ``_job_active`` — под ``_flags_lock``, ставится в одной секции с проверкой ``_busy`` / jog и взятием задания,
ДО ``cvt_job``; при нём ``jog_hold`` и запуск программы отвечают «робот выполняет задание». Тик блокируется на
``wait_done`` до исхода задания; пульс ``HB_PC`` в это время — ``on_poll``. ``connect`` при задании не идёт. Новых
потоков нет: возврат идёт программой на потоке исполнителя.

Остановка (T5.3a, круг 2). ``request_stop(deadline)`` — фаза 1 остановки плагина: защёлка ``_shutdown`` и ОДНА запись
стопа на сильнейшем нужном уровне (задание / программа — HARD, jog — SOFT), без ожидания эха и потоков. Защёлка стопа
(на робота) помнит сильнейший записанный уровень и «последняя запись упала»: стоп процесса не пишется, если уровень не
ниже уже записан; упавшая запись повторяется ровно один раз и только если успевает до срока (не больше двух
попыток на поколение). Защёлка сбрасывается ПОСЛЕ записи движения (JOG_CONT) и при захвате программы / задания
(поколение прогона), а также в ``connect()``; jog без записанного стопа пишется мимо неё. Исключение из «одна
запись»: JOG_CONT, вернувшийся после стопа процесса (замок перехода не взят), получает свой стоп (H-B).
Повтор стопа исполнителя в ``on_progress`` (микроокно
К1) идёт мимо защёлки: он привязан к прогону (один раз на прогон). Простой робот (ничего не исполняется) стопа не
получает. ``disconnect()`` после ``request_stop`` стоп не пишет: одна проверка эха (нет эха — ``last_error``
«стоп не подтверждён роботом»), ожидание потоков, закрытие транспорта. Обычный ``disconnect()`` (без остановки
плагина) — стоп с ожиданием эха, как раньше; защёлку ``_shutdown`` он не ставит. Потоки поводка и исполнителя живут
в области (``spawn``): имя ``<entry.id>-lease-<k>`` / ``<entry.id>-prog-<k>``, ``k`` — счётчик модуля.
"""

from __future__ import annotations

import itertools
import math
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
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
from Services.robot_comm.core.client_v2 import ClientV2Config, RobotClientV2
from Services.robot_comm.core.params_v2 import PARAM_ID, PARAMS, to_eng
from Services.robot_comm.core.protocol_v2 import CONSTANTS, ERR, REG, STOP_LEVEL
from Services.robot_comm.errors import RobotAborted, RobotCommandError, RobotNak, RobotTimeout
from Services.robot_comm.programs import Point, compile_program
from Services.robot_comm.programs.generators import return_slot, toolchange

__all__ = ["RobotDriverV2"]

# Минимальный интервал между попытками переподключения, с (как v1, robot_driver.py:29)
_RECONNECT_THROTTLE_SEC = 2.0
# Окно удержания jog: подтверждений GUI нет дольше — драйвер сам шлёт стоп (Л3, Д3)
_HOLD_WINDOW_S = 0.2
# Дедлайн подтверждения действий при подключении по телеметрии (SERVO / DO_SET — instant, без wait_done)
_ON_CONNECT_DEADLINE_S = 2.0
_ON_CONNECT_POLL_S = 0.02
# Дедлайн join потока поводка в jog_release и disconnect
_LEASE_JOIN_S = 1.0
# Дедлайн join исполнителя программ в disconnect
_PROGRAM_JOIN_S = 5.0
# Период поводка, если клиент его ещё не знает (до probe), с: треть умолчания P_JOG_LEASE_MS
_LEASE_PERIOD_FALLBACK_S = 0.1
# Интервал тика хаба по умолчанию (Plugins/hub/device_hub/plugin.py:346)
_HUB_POLL_DEFAULT_S = 0.5

# Поля ClientV2Config, которые берутся из entry.params как есть (DESIGN п.2)
_CLIENT_KEYS = (
    "round_step",
    "res_timeout_s",
    "done_timeout_s",
    "longest_gap_s",
    "stop_echo_timeout_s",
    "soft_echo_timeout_s",
)
_DO_CHANNELS = range(1, 17)

_TLM_BASE = REG["TLM_PROTO_VER"]
_TLM_COUNT = 32  # TLM_PROTO_VER .. TLM_CFG_PENDING + 1 (0x1040..0x105F)
_WIRE_SCALE = CONSTANTS["WIRE_SCALE"]

TEXT_LEASE_LOST = "поводок jog прерван: нет связи с роботом"
TEXT_STOPPING = "драйвер робота останавливается"
TEXT_SCOPE_CLOSED = "область потоков хаба закрыта"
TEXT_SPAWN_NAME_BUSY = "имя потока драйвера занято"
TEXT_SPAWN_FAILED = "поток драйвера не запущен"
TEXT_THREAD_SURVIVED = "поток драйвера не вышел за срок"
TEXT_WDG_INTERVAL = "интервал тика больше четверти таймаута сторожа"
TEXT_NO_SPAWN = "RobotDriverV2 без spawn не запускает потоки"
TEXT_STOP_UNCONFIRMED = "стоп не подтверждён роботом"
TEXT_BAD_STOP_LEVEL = "неверный уровень стопа"
# Срок стопа процесса, если request_stop() позван без срока (отдельный драйвер, не плагин), с
_PROCESS_STOP_DEFAULT_S = 2.5
_BUSY_PROGRAM = {"status": "error", "message": "робот занят программой"}
_BUSY_JOG = {"status": "error", "message": "робот в режиме jog"}
_BUSY_JOB = {"status": "error", "message": "робот выполняет задание"}
_NOT_CONNECTED = {"status": "error", "message": "нет связи с роботом"}
# Ответы «захват занят» исполнителя: возврат из очереди при таком ответе идёт обратно в её начало (DESIGN п.6)
_BUSY_REPLIES = (_BUSY_PROGRAM, _BUSY_JOG, _BUSY_JOB)
# Тексты отказа постановки — постоянные, без входного значения (R8)
TEXT_BAD_JOB_ARGS = "неверные аргументы задания"
TEXT_BAD_RETURN_ARGS = "неверные аргументы возврата"
# Глубина очередей заданий и возвратов по умолчанию (паритет v1)
_JOB_QUEUE_MAXLEN = 256
# Предел координаты на проводе: |v| * WIRE_SCALE <= W_MAX (R8)
_WIRE_MAX = CONSTANTS["W_MAX"]

# Один счётчик номеров потоков на модуль (поводок и исполнитель, все экземпляры): имя потока уникально в области
_THREAD_SEQ = itertools.count(1)
_THREAD_SEQ_LOCK = threading.Lock()

type _Place = tuple[float, float, float, float]
type _Job = tuple[float, float, float, int, _Place | None]


class _JobStopped(Exception):
    """``stop_event`` хаба взведён, пока тик ждёт завершения задания (DESIGN п.5)."""


class _BadArgs(Exception):
    """Аргумент операции не прошёл проверку R8. Текст ответа — постоянный, задаёт вызывающий."""


def _next_thread_k() -> int:
    """Следующий номер потока; замок — чтобы гарантия не зависела от атомарности ``next()`` в сборке CPython."""
    with _THREAD_SEQ_LOCK:
        return next(_THREAD_SEQ)


def _coord(args: Mapping[str, Any], key: str, default: float | None = None) -> float:
    """Координата из аргументов: конечное число, ``|v| * WIRE_SCALE <= W_MAX``; нет ключа и нет умолчания — ошибка."""
    raw = args.get(key)
    if raw is None:
        if default is None:
            raise _BadArgs(key)
        return default
    if isinstance(raw, bool):
        raise _BadArgs(key)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise _BadArgs(key) from None
    _check_wire(value, key)
    return value


def _check_wire(value: float, what: str) -> None:
    if not math.isfinite(value) or abs(value) * _WIRE_SCALE > _WIRE_MAX:
        raise _BadArgs(what)


def _whole(raw: Any, key: str) -> int:
    """Целое без дробной части (``e_capture``); bool, строка не-числа, nan, 1.5 — ошибка."""
    if isinstance(raw, bool):
        raise _BadArgs(key)
    if isinstance(raw, int):
        return raw
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise _BadArgs(key) from None
    if not math.isfinite(value) or not value.is_integer():
        raise _BadArgs(key)
    return int(value)


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


@dataclass
class _JogRun:
    """Один запуск JOG_CONT этого драйвера. Замки полей: ``active``, ``released``, ``stop_requested`` — под
    ``_flags_lock``; ``handle`` пишет ``jog_hold`` под ``_jog_tx_lock`` (без ``_flags_lock``, читатели берут снимок);
    ``stop_sent`` — под ``_flags_lock`` сразу после записи стопа.

    ``active`` — поток поводка ещё не вышел; ``handle`` — запись потока в области (None, пока ``spawn`` не вернулся);
    ``released`` — поводок больше не пишется, поток выходит без своего стопа (стоп шлёт тот, кто поставил флаг:
    ``jog_release`` или стоп процесса);
    ``stop_requested`` — release, истёкшее окно или стоп процесса: стоп этого jog нужен;
    ``stop_sent`` — запись ``STOP_REQ`` для этого jog прошла (ставится сразу после записи, до эха и независимо от
    него). Обычно под ``_jog_tx_lock``; стоп процесса, не взявший замок за остаток срока, пишет без него (В1).
    """

    seq: int
    wake: threading.Event = field(default_factory=threading.Event)
    handle: IHandle | None = None
    active: bool = True
    released: bool = False
    stop_requested: bool = False
    stop_sent: bool = False


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

        # Флаги — только поля экземпляра, под _flags_lock
        self._flags_lock = threading.Lock()
        self._jog_tx_lock = threading.Lock()
        self._busy = False  # идёт программа
        self._jog_starting = False  # jog_hold между проверкой флагов и записью self._jog (Д4)
        self._jog_stopping = False  # jog_release от снятия поводка до возврата стопа: тик не берёт задание (T3.7)
        self._last_hold = 0.0  # время последнего jog_hold активного jog
        self._jog: _JogRun | None = None
        self._prog_handle: IHandle | None = None  # запись потока исполнителя в области
        self._prog_alive = False  # исполнитель занят от захвата до конца _program_loop, под _flags_lock
        # Остановка (T5.3a К1), всё под _flags_lock: _stopping снимает connect(); _shutdown не снимается никогда
        self._stopping = False
        self._shutdown = False
        self._stop_level = 0  # сильнейший уровень стопа программы с последнего connect()
        self._spawn: Callable[..., IHandle] | None = spawn
        # Защёлка стопа (T5.3 круг 2), под _flags_lock: сбрасывается при захвате нового действия и в connect()
        self._latch_level = 0  # сильнейший записанный уровень STOP_REQ в этом поколении
        self._latch_failed = False  # последняя запись STOP_REQ упала
        self._latch_value: int | None = None  # значение последней удачной записи (проверка эха в фазе 4)
        self._latch_attempts = 0  # попытки записи стопа процесса в этом поколении (не больше двух)
        self._echo_checked: int | None = None  # значение, эхо которого уже проверено
        self._stop_unconfirmed = False  # стоп процесса не подтверждён роботом (health через плагин); сброс — connect()
        self._own_stops: deque[int] = deque(maxlen=8)  # seq своих JOG_CONT, остановленных драйвером (Д1)

        # Задания CVT_JOB и возвраты (T3.7 DESIGN п.1): очереди — паритет v1, дренаж — тик, по одному действию
        maxlen = int(params.get("job_queue_maxlen", _JOB_QUEUE_MAXLEN))
        self._job_queue: deque[_Job] = deque(maxlen=maxlen)  # (x, y, z, e_signed, place)
        self._return_queue: deque[tuple[float, float, float]] = deque(maxlen=maxlen)
        self._pick_lead_mm = float(params.get("pick_lead_mm", 0.0))
        self._job_active = False  # тик держит задание от захвата до исхода wait_done (R7), под _flags_lock
        self.jobs_sent = 0
        self.jobs_done = 0
        self.jobs_failed = 0
        self.returns_done = 0
        self.returns_failed = 0

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

    def _activity_alive(self) -> bool:
        """Жив поток поводка или исполнителя: путь connect и повторная синхронизация не идут (п.9).

        Живость — флаги (``run.active`` снимает поток поводка, ``_prog_alive`` — исполнитель), не объекты потоков.
        """
        with self._flags_lock:
            run = self._jog
            return (run is not None and run.active) or self._prog_alive

    def connect(self) -> bool:
        """Транспорт -> probe -> sync_params -> действия при подключении (DESIGN п.3).

        Не идёт, пока жив поток поводка или исполнителя, и пока тик держит задание (T3.7 R9): иначе ``probe`` +
        ``sync_params`` посреди хода дали бы NAK ``E_BUSY`` на ``PARAM_SET`` и ``_ready = False``.
        """
        with self._flags_lock:
            shutdown = self._shutdown
            job_active = self._job_active
        if shutdown:
            return False  # защёлка request_stop(): после остановки плагина драйвер не подключается (К1)
        if job_active or self._activity_alive():
            return self.is_connected
        with self._flags_lock:
            self._stopping = False  # ручное «Подключить» после обычного disconnect снова разрешает jog и программы
            self._stop_level = 0
            self._latch_reset_locked()
            self._stop_unconfirmed = False
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
            self._values, self._epoch = self._load_params()
            client.sync_params(self._values, self._epoch)
            self._run_on_connect(client)
        except Exception as exc:
            self._record_err()
            self._last_quality = "bad"
            logger.warning(f"робот {self.entry.id!r}: подключение не удалось: {type(exc).__name__}: {exc}")
            self._publish_error(f"подключение к роботу не удалось: {type(exc).__name__}: {exc}")
            return False
        period = client.heartbeat_period_s
        if period is not None and self._hub_poll_s > period:
            self._publish_error(TEXT_WDG_INTERVAL)
        with self._flags_lock:
            shutdown = self._shutdown
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
        """Стоп (задание HARD, jog SOFT, программа SOFT), ожидание потоков через ``IHandle.close``, закрытие транспорта.

        Защёлку ``_shutdown`` не ставит: после обычного отключения ручной ``connect()`` снова работает (К1).
        После ``request_stop()`` (фаза 4 остановки плагина) стоп не пишется и эхо не читается (проверено в фазе 1).
        """
        with self._flags_lock:
            shutdown = self._shutdown
        if not shutdown:  # после request_stop стоп не пишется: эхо проверено в фазе 1 (H7)
            self._request_stop(program_level=STOP_LEVEL["SOFT"])
        with self._flags_lock:
            run, prog = self._jog, self._prog_handle
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
        сильнейший нужный: задание и программа HARD (SOFT посреди хода ждал бы цели), jog SOFT. Простой робот (нет
        задания, программы и jog) стопа не получает. Защёлка: уровень не ниже уже записан и последняя запись не упала
        — записи нет; упавшая запись повторяется ровно один раз, пока не вышел срок. ``_jog_tx_lock`` берётся с
        таймаутом остатка срока; не взят — стоп пишется без замка (В1). Затем проверка эха этой записи (H7): чтения
        начинаются, только пока чтение с повторами транспорта успевает до срока; нет эха или нет времени — «стоп не
        подтверждён роботом» (``last_error``, свойство ``stop_unconfirmed`` для health плагина).
        Не бросает. Повторный вызов безопасен. После него ``connect()`` возвращает False, ``jog_hold`` и запуск
        программы отвечают ``TEXT_STOPPING``.
        """
        if deadline is None:
            deadline = time.monotonic() + _PROCESS_STOP_DEFAULT_S
        with self._flags_lock:
            self._shutdown = True
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
        with self._flags_lock:
            return self._stop_unconfirmed

    def _process_stop(self, deadline: float) -> None:
        """Тело ``request_stop`` (замок перехода jog взят или не взят по сроку): пометки, защёлка, запись."""
        with self._flags_lock:
            self._stopping = True
            self._stop_level = max(self._stop_level, STOP_LEVEL["HARD"])
            run = self._jog
            stop_jog = run is not None and not run.stop_sent and (run.active or run.stop_requested)
            if run is not None and stop_jog:
                run.released = True  # поток поводка выходит без своего стопа: стоп пишет этот путь
                run.stop_requested = True
                run.wake.set()
            jog_in_flight = self._jog_starting  # JOG_CONT в полёте (замок не взят): стоп нужен и ему
            hard = self._prog_alive or self._job_active
            level = STOP_LEVEL["HARD"] if hard else (STOP_LEVEL["SOFT"] if stop_jog or jog_in_flight else 0)
            # Jog без записанного стопа (stop_sent False) или JOG_CONT в полёте пишется всегда, мимо защёлки (H-A)
            latch_applies = not (stop_jog or jog_in_flight)
            attempts = self._latch_attempts
            if attempts == 0:
                if level and latch_applies and self._latch_level >= level and not self._latch_failed:
                    level = 0  # такой стоп уже записан в этом поколении
            elif not (attempts == 1 and self._latch_failed):
                level = 0  # стоп процесса уже записан или повтор уже был: в поколении не больше двух попыток
        if not level or self._client is None:
            return  # простой робот, стоп уже записан или нет клиента: записи нет
        jog_run = run if stop_jog else None
        while True:
            with self._flags_lock:
                attempt = self._latch_attempts + 1
                # Повтор — только после упавшей записи и только если запись успеет до срока (таймаут транспорта
                # с его повторами): поздний повтор не доставит стоп раньше срока, а поток стопа пережил бы его
                if attempt > 2 or (attempt == 2 and time.monotonic() + self._write_budget_s() > deadline):
                    return
                self._latch_attempts = attempt
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
            with self._flags_lock:
                if run.seq not in self._own_stops:
                    self._own_stops.append(run.seq)
        try:
            value = self._client.issue_stop(level)
        except Exception:
            with self._flags_lock:
                self._latch_failed = True
            raise
        with self._flags_lock:
            self._latch_level = max(self._latch_level, value & 3)
            self._latch_failed = False
            self._latch_value = value
            if run is not None:
                run.stop_sent = True
        return value

    def _stop_and_wait(self, level: int, run: _JogRun | None = None) -> None:
        """Стоп с эхом (пути оператора и обычный disconnect): запись через защёлку + эхо по таймауту клиента."""
        value = self._write_stop(level, run)
        written = value & 3
        timeout = self._cfg.soft_echo_timeout_s if written == STOP_LEVEL["SOFT"] else self._cfg.stop_echo_timeout_s
        self._client.await_stop_echo(value, written, deadline=time.monotonic() + timeout)

    def _latch_reset_locked(self) -> None:
        """Под ``_flags_lock``: новое поколение (захват действия, ``connect``) — прежние стопы его не покрывают."""
        self._latch_level = 0
        self._latch_failed = False
        self._latch_attempts = 0
        self._latch_value = None  # H6: эхо проверяется только для записи этого поколения

    def _check_stop_echo(self, deadline: float) -> None:
        """Эхо записи стопа процесса этого поколения, без записи, один раз на значение (H7).

        Чтения идут до ``deadline - _write_budget_s()``: чтение, начатое позже, могло бы пережить срок на мёртвой
        связи. Нет эха, нет времени или запись стопа не прошла — ``last_error`` «стоп не подтверждён роботом» и
        ``stop_unconfirmed``. Простой робот (записи не было) не проверяется. Не бросает.
        """
        with self._flags_lock:
            value = self._latch_value
            attempted = self._latch_attempts > 0
            if value is not None and value == self._echo_checked:
                return
            if value is None and (not attempted or self._stop_unconfirmed):
                return
            self._echo_checked = value
        client = self._client
        read_until = deadline - self._write_budget_s()
        confirmed = False
        if value is not None and client is not None and time.monotonic() < read_until:
            try:
                client.await_stop_echo(value, value & 3, deadline=read_until)
                confirmed = True
            except Exception as exc:
                logger.warning(f"робот {self.entry.id!r}: эхо стопа не получено: {type(exc).__name__}: {exc}")
        if confirmed:
            return
        with self._flags_lock:
            self._stop_unconfirmed = True
        self._record_err()
        logger.warning(f"робот {self.entry.id!r}: {TEXT_STOP_UNCONFIRMED}")
        self._publish_error(TEXT_STOP_UNCONFIRMED)

    def _stop_latched(self, level: int) -> None:
        """Запись стопа без эха через защёлку: такой уровень уже записан в этом поколении — записи нет (H1)."""
        with self._flags_lock:
            if self._latch_level >= level and not self._latch_failed:
                return
        self._write_stop(level)

    def _request_stop(self, program_level: int) -> None:
        """Стоп обычного ``disconnect``: флаг ``_stopping``, пометка jog, стопы с ожиданием эха без замков (К1)."""
        # V1: JOG_CONT в полёте дописывает self._jog под _jog_tx_lock — читаем его под тем же замком
        with self._jog_tx_lock:
            with self._flags_lock:
                self._stopping = True
                self._stop_level = max(self._stop_level, program_level)
                run = self._jog
                stop_jog = run is not None and not run.stop_sent
                if stop_jog:
                    run.released = True
                    run.stop_requested = True
                    run.wake.set()
                prog_alive = self._prog_alive
                job_active = self._job_active
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
        now = self._clock()
        if now - self._last_reconnect < _RECONNECT_THROTTLE_SEC:
            return False
        self._last_reconnect = now
        self._record_reconnect()
        if self.connect():
            self.reset_reconnect()
            return True
        self._note_reconnect_failed()
        return False

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
                with self._flags_lock:
                    own = ev.errno == ERR["E_ABORTED"] and ev.seq in self._own_stops
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

        «Захват свободен» и взятие задания — одна секция ``_flags_lock``: ``_job_active`` ставится ДО ``cvt_job``,
        поэтому ``jog_hold`` / ``start_program`` между проверкой и записью видят ``_BUSY_JOB`` (R7).
        """
        if not free:
            return
        job: _Job | None = None
        item: tuple[float, float, float] | None = None
        with self._flags_lock:
            run = self._jog
            if (
                self._stopping
                or self._busy
                or self._jog_starting
                or self._jog_stopping
                or (run is not None and run.active)
                or self._job_active
            ):
                return
            if self._return_queue:
                item = self._return_queue.popleft()
            elif self._job_queue:
                job = self._job_queue.popleft()
                self._job_active = True
                self._latch_reset_locked()
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
                with self._flags_lock:
                    self._job_queue.appendleft(job)  # робот занят — повтор следующим тиком (паритет v1)
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
            with self._flags_lock:
                self._job_active = False

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
            with self._flags_lock:
                self._return_queue.appendleft(item)  # захват перехвачен между секциями — повтор следующим тиком
            return
        with self._flags_lock:
            self.returns_failed += 1
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

    def _resync_maybe(self, client: RobotClientV2) -> None:
        """Метка робота не равна метке ПК -> sync_params снова (§11.4 п.4), не при программе или jog."""
        if self._activity_alive():
            return
        now = self._clock()
        if now - self._last_resync < _RECONNECT_THROTTLE_SEC and self._last_resync:
            return
        self._last_resync = now
        try:
            self._values, self._epoch = self._load_params()
            client.sync_params(self._values, self._epoch)
        except Exception as exc:
            self._record_err()
            self._publish_error(f"синхронизация параметров не удалась: {type(exc).__name__}: {exc}")

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
            "queue_len": len(self._job_queue),
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
            return {"status": "error", "message": TEXT_BAD_JOB_ARGS, "queue_len": len(self._job_queue)}
        if not self.is_connected:
            return {**_NOT_CONNECTED, "queue_len": len(self._job_queue)}
        if ecap is None:
            ecap = _parse_tlm(self._read_tlm())[2]  # R5: энкодер сейчас, в потоке команды (s32)
        if self._pick_lead_mm != 0.0:
            # R4: ход ленты на импульс — P_BELT_FACTOR × 1e-5 мм/имп (не константа v1)
            ecap -= round(self._pick_lead_mm / (self._values["P_BELT_FACTOR"] * 1e-5))
        with self._flags_lock:
            self._job_queue.append((x, y, z, ecap, place))  # maxlen: старейшее вытесняется (паритет v1)
            n = len(self._job_queue)
        return {"status": "ok", "queue_len": n}

    def _op_return_job(self, args: dict) -> dict:
        """Возврат из слота {x_mm, y_mm, z_mm?} в очередь возвратов; исполнение — тиком (R2, DESIGN п.3).

        Без ``spawn`` — ``RuntimeError`` до очереди: возврат идёт программой на потоке исполнителя (H2).
        """
        self._spawn_fn()
        try:
            item = (_coord(args, "x_mm"), _coord(args, "y_mm"), _coord(args, "z_mm", 0.0))
        except _BadArgs:
            return {"status": "error", "message": TEXT_BAD_RETURN_ARGS, "return_queue_len": len(self._return_queue)}
        if not self.is_connected:
            return {**_NOT_CONNECTED, "return_queue_len": len(self._return_queue)}
        with self._flags_lock:
            self._return_queue.append(item)
            n = len(self._return_queue)
        return {"status": "ok", "return_queue_len": n}

    # --- jog ---

    def _op_abort(self, args: dict) -> dict:
        """Стоп оператора {mode: 1|2|3 или "SOFT"|"HARD"|"HALT"}: пишется всегда (защёлка стопа процесса не блокирует,
        запись в неё учитывается), затем ждёт эха по таймауту клиента."""
        raw = args.get("mode", STOP_LEVEL["SOFT"])
        if isinstance(raw, str) and raw.upper() in STOP_LEVEL:
            mode = STOP_LEVEL[raw.upper()]
        elif isinstance(raw, int) and not isinstance(raw, bool) and raw in STOP_LEVEL.values():
            mode = raw
        else:
            return {"status": "error", "message": TEXT_BAD_STOP_LEVEL}
        if self._client is None:
            return dict(_NOT_CONNECTED)
        self._stop_and_wait(mode)
        return {"status": "ok", "mode": mode}

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
        direction, speed = int(args["dir"]), int(args["spd"])
        with self._flags_lock:
            if self._stopping:
                return {"status": "error", "message": TEXT_STOPPING}
            if self._busy:
                return dict(_BUSY_PROGRAM)
            if self._job_active:
                return dict(_BUSY_JOB)
            if self._holding_locked():
                self._last_hold = self._clock()
                return {"status": "ok"}
        if not self.is_connected:
            return dict(_NOT_CONNECTED)
        client = self._client
        # Переход jog: стоп в полёте держит этот замок — новый JOG_CONT уйдёт после возврата stop() (п.9)
        with self._jog_tx_lock:
            with self._flags_lock:
                if self._stopping:
                    return {"status": "error", "message": TEXT_STOPPING}
                if self._busy:
                    return dict(_BUSY_PROGRAM)
                if self._job_active:
                    return dict(_BUSY_JOB)
                if self._holding_locked():
                    self._last_hold = self._clock()
                    return {"status": "ok"}
                prev = self._jog
                # Д4: от проверки _busy до записи self._jog start_program видит переход как jog (_BUSY_JOG)
                self._jog_starting = True
            try:
                if prev is not None and prev.stop_requested and not prev.stop_sent:
                    self._stop_jog_locked(prev)  # release / окно ещё не дослали стоп — шлём его сами, один раз
                result = client.jog_cont(direction, speed)
                run = _JogRun(seq=result.seq)
                # _last_hold — ДО spawn: spawn запускает поток при вызове, поток читает _last_hold (К3)
                with self._flags_lock:
                    self._jog = run
                    self._last_hold = self._clock()
                    # H-A: запись движения — новое поколение защёлки ПОСЛЕ неё (стоп prev выше её не покрывает)
                    self._latch_reset_locked()
                    stopping = self._stopping
                if stopping:
                    # H-B: стоп процесса не взял замок перехода и записан, пока JOG_CONT был в полёте, — он мог лечь
                    # раньше движения. Стоп этого seq пишется здесь, мимо защёлки; поводок не запускается.
                    # Единственное исключение из «одна запись стопа процесса на робота»: в этой гонке их две.
                    with self._flags_lock:
                        run.released = True
                        run.stop_requested = True
                        run.active = False
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
                    with self._flags_lock:
                        run.active = False
                        self._jog = prev
                    return self._spawn_failed(thread_name, exc)
            finally:
                with self._flags_lock:
                    self._jog_starting = False
        return {"status": "ok", "seq": result.seq}

    def _holding_locked(self) -> bool:
        """Под ``_flags_lock``: свой jog жив и его стоп не запрошен."""
        run = self._jog
        return run is not None and run.active and not run.stop_requested

    def _op_jog_release(self, _args: dict) -> dict:
        """Перестать писать поводок и явно остановить свой jog (Л4); нет своего jog -> ok без записи стопа."""
        with self._flags_lock:
            run = self._jog
            if run is None or not run.active or run.stop_requested:
                return {"status": "ok"}
            run.released = True
            run.stop_requested = True
            run.wake.set()
            # T3.7 (ревью р.1): поток поводка выходит (active = False) раньше записи стопа — до её возврата тик
            # не берёт задание, иначе SOFT этого jog оборвал бы CVT_JOB (E_ABORTED)
            self._jog_stopping = True
        try:
            # handle is None: spawn ещё не вернулся — без close; _stop_jog ждёт _jog_tx_lock, который jog_hold держит
            # до возврата spawn, поток поводка видит run.released и выходит сам (К4). close — вне _jog_tx_lock:
            # поток поводка на пути Д3 сам может ждать этот замок
            handle = run.handle
            if handle is not None:
                self._close_thread(handle, _LEASE_JOIN_S)
            self._stop_jog(run)
        finally:
            with self._flags_lock:
                self._jog_stopping = False
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
                with self._flags_lock:
                    if run.released:
                        return  # стоп шлёт release
                    stop = ev.is_set() or self._clock() - self._last_hold > _HOLD_WINDOW_S
                    if stop:
                        run.stop_requested = True
                if stop:
                    self._stop_jog(run)  # Д3
                    return
                client.jog_lease()
                run.wake.wait(period)
        except Exception as exc:
            self._record_err()
            logger.warning(f"робот {self.entry.id!r}: поводок jog прерван: {type(exc).__name__}: {exc}")
            self._publish_error(TEXT_LEASE_LOST)
        finally:
            with self._flags_lock:
                run.active = False

    # --- программы ---

    def start_program(self, program: Any, points: Mapping[str, Point], frames: Any = None, *, name: str) -> dict:
        """Запустить программу в потоке исполнителя; один прогон за раз (DESIGN п.6)."""
        return self._launch(program, points, frames, name=name, kind="program")

    def _launch(self, program: Any, points: Mapping[str, Point], frames: Any, *, name: str, kind: str) -> dict:
        """Захват (программа / задание / jog) -> компиляция -> поток исполнителя. ``kind`` уходит в счётчики
        возвратов ``_program_loop`` (T3.7 DESIGN п.7). Без ``spawn`` — ``RuntimeError`` до захвата."""
        spawn = self._spawn_fn()
        with self._flags_lock:
            if self._stopping:
                return {"status": "error", "message": TEXT_STOPPING}
            if self._busy:
                return dict(_BUSY_PROGRAM)
            if self._job_active:
                return dict(_BUSY_JOB)
            run = self._jog
            if self._jog_starting or self._jog_stopping or (run is not None and run.active):
                return dict(_BUSY_JOG)  # окно T3.7: поводок вышел, стоп jog_release ещё не вернулся
            if not self.is_connected:
                return dict(_NOT_CONNECTED)
            self._busy = True
            self._prog_alive = True
            self._latch_reset_locked()
        try:
            scenario = compile_program(program, points, frames or {}, self._ws_params())
            total = len(scenario.records)
        except Exception as exc:
            with self._flags_lock:
                self._busy = False
                self._prog_alive = False
            return {"status": "error", "message": str(exc)}
        thread_name = f"{self.entry.id}-prog-{_next_thread_k()}"
        try:
            handle = spawn(lambda ev: self._program_loop(scenario, name, total, kind), name=thread_name)
        except Exception as exc:
            with self._flags_lock:
                self._busy = False
                self._prog_alive = False
            return self._spawn_failed(thread_name, exc)
        with self._flags_lock:
            self._prog_handle = handle
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
            # Микроокно (К1): стоп, записанный между проверкой _stopping и взятием поколения в run_chunks, прогон
            # не видит — повторяем его при первом же опросе. Повтор привязан к прогону и идёт мимо защёлки стопа
            # процесса (та запись удачна, но могла лечь до g0 прогона); только запись, без эха
            with self._flags_lock:
                level = self._stop_level if (self._stopping and not resent[0]) else 0
                if level:
                    resent[0] = True
            if level:
                try:
                    self._write_stop(level)
                except Exception as exc:
                    self._record_err()
                    logger.warning(f"робот {self.entry.id!r}: повтор стопа программы не доставлен: {exc}")

        try:
            self._pub(path, dict(state))
            with self._flags_lock:
                stopping = self._stopping
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
                # Итог публикуется ДО снятия _busy: robot_program_run может прийти сразу после (DESIGN 7)
                self._pub(path, dict(state))
            finally:
                with self._flags_lock:
                    self._busy = False
                    self._prog_alive = False
                    if kind == "return":
                        if state["state"] == "done":
                            self.returns_done += 1
                        else:
                            self.returns_failed += 1

    # ------------------------------------------------------------------ #
    # Snapshot
    # ------------------------------------------------------------------ #

    def snapshot(self, data: dict | None = None, quality: str | None = None) -> dict:
        """Snapshot со счётчиками заданий и возвратов (T3.7 п.11, по образцу v1); ключей ``mode`` / ``draw_*`` нет."""
        base: dict[str, Any] = {
            "queue_len": len(self._job_queue),
            "jobs_sent": self.jobs_sent,
            "jobs_done": self.jobs_done,
            "jobs_failed": self.jobs_failed,
            "returns_done": self.returns_done,
            "returns_failed": self.returns_failed,
            "return_queued": len(self._return_queue),
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


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


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
