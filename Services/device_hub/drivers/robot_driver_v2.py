"""RobotDriverV2 — драйвер хаба для робота протокола Delta v2 (T5.1, plans/robot-protocol-v2/tasks/T5.1.md).

Purpose:
    Драйвер ``device_hub`` поверх ``RobotClientV2``: подключение (транспорт -> ``probe`` -> ``sync_params`` ->
    действия при подключении), тик хаба (пульс ``HB_PC`` каждый тик, блок телеметрии, сверка метки параметров,
    асинхронные ошибки в ``devices.state.<id>.last_error``), удержание jog с поводком и явным стопом,
    исполнитель программ в своём потоке (состояние — ``devices.state.<id>.program``). Фабрика хаба выбирает этот
    класс по ``entry.protocol == "delta_v2"``; драйвер v1 (``robot_driver.py``) не меняется.

Public API:
    ``RobotDriverV2(entry, protocol=None, *, transport=None, publish=None, param_source=None, clock=None,
    sleep=None)``; ``connect() -> bool``, ``disconnect()``, ``is_connected``, ``tick(stop_event)``,
    ``call(op, args)`` с операциями ``jog_hold`` {dir, spd}, ``jog_release``, ``get_telemetry``;
    ``start_program(program, points, frames=None, *, name)``, ``start_return(slot, **kw)``,
    ``start_toolchange(current, target, points, **kw)``; свойство ``transport`` (свой ``ModbusDevice``).
    ``param_source`` — точка подключения T5.2: ``() -> (сырые значения {имя: int} без P_CONFIG_EPOCH, метка)``.

Stability: lite

Потоки (DESIGN п.9). Замок драйвера ``_flags_lock`` — только на флаги (``_busy``, ``_last_hold``, состояние jog,
множество своих стопов), вокруг вызовов клиента не держится: ``ModbusDevice`` сериализует RLock-ом, а
``stop`` / ``kick_heartbeat`` / ``jog_lease`` / ``poll_errors`` нарочно минуют замок mailbox клиента. Второй замок
``_jog_tx_lock`` — только для переходов jog: ``client.jog_cont`` в ``jog_hold`` и ``client.stop(SOFT)`` стопа jog.
Тик, исполнитель и ``poll_errors`` его не берут. Путь ``connect`` и повторная синхронизация не идут, пока жив поток
поводка или исполнителя.
"""

from __future__ import annotations

import threading
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from Services.device_hub.drivers.base import BaseDeviceDriver, logger
from Services.robot_comm.core.client_v2 import ClientV2Config, RobotClientV2
from Services.robot_comm.core.params_v2 import PARAM_ID, PARAMS, to_eng
from Services.robot_comm.core.protocol_v2 import CONSTANTS, ERR, REG, STOP_LEVEL
from Services.robot_comm.errors import RobotAborted
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
TEXT_WDG_INTERVAL = "интервал тика больше четверти таймаута сторожа"
_BUSY_PROGRAM = {"status": "error", "message": "робот занят программой"}
_BUSY_JOG = {"status": "error", "message": "робот в режиме jog"}
_NOT_CONNECTED = {"status": "error", "message": "нет связи с роботом"}


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
    """Один запуск JOG_CONT этого драйвера. Поля меняются только под ``_flags_lock``.

    ``active`` — поток поводка ещё не вышел; ``stop_requested`` — release или истёкшее окно: стоп этого jog нужен;
    ``stop_sent`` — стоп этого jog уже записан (под ``_jog_tx_lock``).
    """

    seq: int
    wake: threading.Event = field(default_factory=threading.Event)
    thread: threading.Thread | None = None
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
        self._last_hold = 0.0  # время последнего jog_hold активного jog
        self._jog: _JogRun | None = None
        self._prog_thread: threading.Thread | None = None
        self._own_stops: deque[int] = deque(maxlen=8)  # seq своих JOG_CONT, остановленных драйвером (Д1)

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
        """Жив поток поводка или исполнителя: путь connect и повторная синхронизация не идут (п.9)."""
        with self._flags_lock:
            run, prog = self._jog, self._prog_thread
        lease_alive = run is not None and run.thread is not None and run.thread.is_alive()
        return lease_alive or (prog is not None and prog.is_alive())

    def connect(self) -> bool:
        """Транспорт -> probe -> sync_params -> действия при подключении (DESIGN п.3)."""
        if self._activity_alive():
            return self.is_connected
        was_ready = self._ready
        self._ready = False
        try:
            if self._transport is not None and self._transport.is_connected and not was_ready:
                self._transport.disconnect()  # сокет после сбоя мог остаться «подключённым» (см. _link_lost)
            if self._transport is None:
                from Services.device_hub.transports import build_transport

                self._transport = build_transport(self.entry, lambda _id: None)
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
        """Активный jog -> стоп SOFT; программа -> стоп SOFT (прерывание); потоки — join с дедлайном."""
        with self._flags_lock:
            run = self._jog
            stop_jog = run is not None and run.active and not run.stop_requested
            if stop_jog:
                run.released = True
                run.stop_requested = True
                run.wake.set()
            prog = self._prog_thread
        if stop_jog:
            self._join(run.thread, _LEASE_JOIN_S)
            try:
                self._stop_jog(run)
            except Exception as exc:
                self._record_err()
                logger.warning(f"робот {self.entry.id!r}: стоп jog при отключении не доставлен: {exc}")
        if prog is not None and prog.is_alive() and self._client is not None:
            try:
                self._client.stop(STOP_LEVEL["SOFT"])
            except Exception as exc:
                self._record_err()
                logger.warning(f"робот {self.entry.id!r}: стоп программы при отключении не доставлен: {exc}")
            self._join(prog, _PROGRAM_JOIN_S)
        self._ready = False
        if self._transport is not None:
            try:
                self._transport.disconnect()
            except Exception:
                self._record_err()  # сбой закрытия фиксируется, не глушится молча (как v1)
        self._last_quality = "bad"

    @staticmethod
    def _join(thread: threading.Thread | None, deadline_s: float) -> None:
        if thread is not None and thread is not threading.current_thread():
            thread.join(deadline_s)

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
        except Exception:
            self._record_err()
        quality = "bad" if self._stats["tx_err"] > err_before else "good"
        return self.snapshot(data, quality=quality)

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
        except Exception:
            self._record_err()

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
        return {"status": "ok", "telemetry": telemetry, "free": free, "encoder": encoder, "queue_len": 0}

    # --- jog ---

    def _op_jog_hold(self, args: dict) -> dict:
        """Подтверждение удержания: нет своего jog -> JOG_CONT и поток поводка; есть -> только ``_last_hold``."""
        direction, speed = int(args["dir"]), int(args["spd"])
        with self._flags_lock:
            if self._busy:
                return dict(_BUSY_PROGRAM)
            if self._holding_locked():
                self._last_hold = self._clock()
                return {"status": "ok"}
        if not self.is_connected:
            return dict(_NOT_CONNECTED)
        client = self._client
        # Переход jog: стоп в полёте держит этот замок — новый JOG_CONT уйдёт после возврата stop() (п.9)
        with self._jog_tx_lock:
            with self._flags_lock:
                if self._busy:
                    return dict(_BUSY_PROGRAM)
                if self._holding_locked():
                    self._last_hold = self._clock()
                    return {"status": "ok"}
                prev = self._jog
            if prev is not None and prev.stop_requested and not prev.stop_sent:
                self._stop_jog_locked(prev)  # release / окно ещё не дослали стоп — шлём его сами, один раз
            result = client.jog_cont(direction, speed)
            run = _JogRun(seq=result.seq)
            run.thread = threading.Thread(
                target=self._lease_loop, args=(run,), name=f"rv2-lease-{self.entry.id}", daemon=True
            )
            with self._flags_lock:
                self._jog = run
                self._last_hold = self._clock()
            run.thread.start()
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
        self._join(run.thread, _LEASE_JOIN_S)  # вне _jog_tx_lock: поток поводка сам может ждать этот замок
        self._stop_jog(run)
        return {"status": "ok"}

    def _stop_jog(self, run: _JogRun) -> None:
        with self._jog_tx_lock:
            if not run.stop_sent:
                self._stop_jog_locked(run)

    def _stop_jog_locked(self, run: _JogRun) -> None:
        """Под ``_jog_tx_lock``: стоп SOFT своего jog. Seq — в множество своих стопов ДО записи (Д1)."""
        with self._flags_lock:
            if run.seq not in self._own_stops:
                self._own_stops.append(run.seq)
        self._client.stop(STOP_LEVEL["SOFT"])  # ошибка транспорта / RobotTimeout — наружу, не глушится
        with self._flags_lock:
            run.stop_sent = True

    def _lease_loop(self, run: _JogRun) -> None:
        """Поток поводка: пока окно удержания не истекло и нет release — ``jog_lease()`` раз в период.

        Окно истекло -> стоп шлёт сам поток (без join себя). Выход по любой причине снимает ``active``.
        """
        client = self._client
        period = client.jog_lease_period_s or _LEASE_PERIOD_FALLBACK_S
        try:
            while True:
                with self._flags_lock:
                    if run.released:
                        return
                    expired = self._clock() - self._last_hold > _HOLD_WINDOW_S
                    if expired:
                        run.stop_requested = True
                if expired:
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
        with self._flags_lock:
            if self._busy:
                return dict(_BUSY_PROGRAM)
            run = self._jog
            if run is not None and run.active:
                return dict(_BUSY_JOG)
            if not self.is_connected:
                return dict(_NOT_CONNECTED)
            self._busy = True
        try:
            scenario = compile_program(program, points, frames or {}, self._ws_params())
            total = len(scenario.records)
            thread = threading.Thread(
                target=self._program_loop,
                args=(scenario, name, total),
                name=f"rv2-prog-{self.entry.id}",
                daemon=True,
            )
            with self._flags_lock:
                self._prog_thread = thread
            thread.start()
        except Exception as exc:
            with self._flags_lock:
                self._busy = False
            return {"status": "error", "message": str(exc)}
        return {"status": "ok", "name": name, "total": total}

    def start_return(self, slot: Point, **kw: Any) -> dict:
        """Возврат из слота с домом в конце: ``return_slot(slot, home=<дом из параметров>, **kw)``."""
        try:
            gp = return_slot(slot, home=self._home_point(), **kw)
        except Exception as exc:
            return {"status": "error", "message": str(exc)}
        return self.start_program(gp.program, gp.points, None, name=gp.program.name)

    def start_toolchange(self, current: int, target: int, points: Mapping[str, Point], **kw: Any) -> dict:
        """Смена инструмента с домом в конце: ``toolchange(..., home=<дом из параметров>)``."""
        try:
            gp = toolchange(current, target, points, home=self._home_point(), **kw)
        except Exception as exc:
            return {"status": "error", "message": str(exc)}
        return self.start_program(gp.program, gp.points, None, name=gp.program.name)

    def _program_loop(self, scenario: Any, name: str, total: int) -> None:
        path = f"devices.state.{self.entry.id}.program"
        state = {"name": name, "state": "running", "done": 0, "total": total, "error": None}

        def on_progress(done: int, all_records: int) -> None:
            state["done"], state["total"] = done, all_records
            self._pub(path, dict(state))

        try:
            self._pub(path, dict(state))
            self._client.run_chunks(scenario, params=self._ws_params(), on_progress=on_progress)
            state["state"], state["done"] = "done", state["total"]
        except RobotAborted:
            state["state"] = "aborted"
        except Exception as exc:
            self._record_err()
            state["state"], state["error"] = "failed", f"программа прервана ошибкой: {type(exc).__name__}: {exc}"
            logger.warning(f"робот {self.entry.id!r}: программа {name!r}: {state['error']}")
        finally:
            with self._flags_lock:
                self._busy = False
        self._pub(path, dict(state))


RobotDriverV2._OPS = {
    "jog_hold": RobotDriverV2._op_jog_hold,
    "jog_release": RobotDriverV2._op_jog_release,
    "get_telemetry": RobotDriverV2._op_get_telemetry,
}
