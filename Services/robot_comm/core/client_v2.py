"""RobotClientV2 — клиент протокола Delta v2 (mailbox, стоп, пульс, параметры) поверх DeviceTransport.

Purpose:
    Один объект на робота: ``probe`` (проверка прошивки), ``cmd`` (транзакция mailbox,
    protocol-spec §3.1/§4), ``wait_done`` (завершение команды), ``poll_errors`` (асинхронные
    события ошибок), ``stop`` (плоскость STOP_REQ с seq, §8), ``kick_heartbeat`` /
    ``jog_lease`` (пульс и поводок, §9), ``sync_params`` (синхронизация по метке, params.md §11.4).
    Собственных потоков нет: расписание пульса и поводка держит вызывающий (драйвер).

Public API:
    ``RobotClientV2``, ``ClientV2Config``, ``CmdResult``, ``ErrorEvent``, ``StopResult``,
    ``SyncReport``. Ошибки — ``Services.robot_comm.errors`` (``WrongFirmware``, ``RobotNak``,
    ``RobotCommandError``, ``RobotAborted``, ``RobotTimeout``, ``RobotSyncError``).

Stability: lite

Потоки. ``_mailbox_lock`` сериализует ТОЛЬКО ``cmd()``. ``stop``, ``wait_done``, ``kick_heartbeat``,
``jog_lease``, ``poll_errors`` его не берут: стоп проходит, пока ``cmd()`` ждёт ответ робота.
Остальные замки (``_stop_lock``, ``_hb_lock``, ``_jog_lock``, ``_err_lock``, ``_state_lock``,
``_probe_lock``) короткие и друг в друга не вкладываются, кроме пары ``_probe_lock`` ->
``_stop_lock`` / ``_hb_lock`` / ... внутри ``probe()``. Замок mailbox ни разу не берётся
под другим замком.

Pre (общее): первый пишущий вызов (``cmd``, ``stop``, ``sync_params``, ``kick_heartbeat``, ``jog_lease``) на клиенте
без ``probe()`` выполняет ``probe()`` сам (``_ensure_probed``, только чтения): прошивка не v2 -> ``WrongFirmware`` без
единой записи; транспорт не подключён -> ``RobotNotConnectedError``.

Константы и адреса — только из ``protocol_v2`` и ``params_v2`` (сгенерированы).
"""

from __future__ import annotations

import operator
import random
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from Services.robot_comm.core.params_v2 import DICT_FINGERPRINT, PARAM_ID
from Services.robot_comm.core.protocol_v2 import CONSTANTS, ERR, ERR_TEXT, OP, OP_SPEC, REASON_TEXT, REG, STOP_LEVEL
from Services.robot_comm.errors import (
    RobotAborted,
    RobotCommandError,
    RobotNak,
    RobotNotConnectedError,
    RobotSyncError,
    RobotTimeout,
    WrongFirmware,
)
from Services.robot_comm.interfaces import DeviceTransport

__all__ = [
    "ClientV2Config",
    "CmdResult",
    "ErrorEvent",
    "RobotClientV2",
    "StopResult",
    "SyncReport",
]

# --- раскладка блоков чтения ---------------------------------------------------------------
_RES_BASE = REG["RES_SEQ"]  # 0x1010: начало блока «ответ + пульс + телеметрия»
_BLOCK_COUNT = REG["TLM_CFG_PENDING"] + 1 - _RES_BASE + 1  # 0x1010..0x105F — 80 регистров (probe, база cmd)
_RES_BLOCK_COUNT = 4 + 8  # RES_SEQ, STATUS, ERRNO, RVALC + RES_RVALS[8]
_RES_RVALS_MAX = 8
_TLM_BASE = REG["TLM_PROTO_VER"]  # 0x1040
_TLM_COUNT = REG["TLM_CFG_PENDING"] + 2 - _TLM_BASE  # 0x1040..0x105F — 32 регистра

_STATUS_ACK = 1
_ACTIVITY_IDLE = 0
_ACTIVITY_FAULT = 5
_PROTO_MAJOR = 0x02
_SEQ_MAX = 0xFFFF
_STOP_SEQ_MAX = 0x3FFF  # STOP_REQ = stop_seq*4 + level, stop_seq 1..16383
_STOP_HALF_CIRCLE = _STOP_SEQ_MAX // 2  # 8191: окно «новее» по кругу из 16383 значений (разность — по модулю 16383)
_UNKNOWN_ERR_TEXT = "неизвестная ошибка"
_MASKED_EVENT_TEXT = "событие обрыва перекрыто"
_HB_PERIOD_DIV = 4000.0  # P_WDG_TIMEOUT_MS / 4000 -> секунды (четверть таймаута сторожа)
_JOG_PERIOD_DIV = 3000.0  # P_JOG_LEASE_MS / 3000 -> секунды (треть срока поводка)


def _off(name: str) -> int:
    """Смещение регистра ``name`` в блоке, прочитанном от ``_RES_BASE``."""
    return REG[name] - _RES_BASE


def _toff(name: str) -> int:
    """Смещение регистра ``name`` в блоке, прочитанном от ``_TLM_BASE``."""
    return REG[name] - _TLM_BASE


def _next_seq(value: int) -> int:
    """Следующий seq по кругу 65535 -> 1 (0 не используется)."""
    return 1 if value >= _SEQ_MAX else value + 1


def _encode_word(value: object, what: str) -> int:
    """Слово mailbox: целое в ``W_MIN``..65535 -> ``& 0xFFFF``. Текст ошибки — без значения."""
    try:
        number = operator.index(value)  # type: ignore[arg-type]
    except TypeError:
        raise ValueError(f"{what}: ожидается целое") from None
    if not CONSTANTS["W_MIN"] <= number <= 0xFFFF:
        raise ValueError(f"{what}: вне диапазона W_MIN..65535")
    return number & 0xFFFF


# --- типы результата -----------------------------------------------------------------------


class ClientV2Config(BaseModel):
    """Тайминги клиента. Граница — только ``from_dict`` (Dict at Boundary): прямой конструктор
    ``ClientV2Config(...)`` при ошибке показывает во ``ValidationError`` входные значения."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    poll_interval_s: float = Field(default=0.02, gt=0)
    #: Самый длинный интервал между точками опроса робота (примитив, цепочка LINE_PASS до EXACT, DELAY_MS).
    longest_gap_s: float = Field(default=1.5, gt=0)
    res_timeout_s: float = Field(default=2.0, gt=0)
    done_timeout_s: float = Field(default=30.0, gt=0)
    stop_echo_timeout_s: float = Field(default=1.0, gt=0)  # HARD / HALT
    soft_echo_timeout_s: float = Field(default=2.0, gt=0)

    @model_validator(mode="after")
    def _timeouts_cover_longest_gap(self) -> ClientV2Config:
        # protocol-spec §4 п.3, §8 п.6: ответ и SOFT-эхо могут ждать до конца самого длинного примитива.
        if self.res_timeout_s < self.longest_gap_s:
            raise ValueError("res_timeout_s не может быть меньше longest_gap_s")
        if self.soft_echo_timeout_s < self.longest_gap_s:
            raise ValueError("soft_echo_timeout_s не может быть меньше longest_gap_s")
        return self

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> ClientV2Config:
        """Pre: ``data`` — словарь полей. Post: конфиг или ``ValueError`` (без значений в тексте)."""
        try:
            return cls.model_validate(dict(data))
        except ValidationError as exc:
            fields = sorted({".".join(str(p) for p in err["loc"]) or "<model>" for err in exc.errors()})
            raise ValueError(f"ClientV2Config: некорректные поля: {', '.join(fields)}") from None


@dataclass(frozen=True, slots=True)
class CmdResult:
    """Принятая роботом команда: ``seq`` и значения ответа (первые ``RES_RVALC``)."""

    seq: int
    rvals: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class ErrorEvent:
    """Событие ошибки из TLM: ``evt`` — счётчик ``ERR_EVT``; ``missed`` — сколько событий между опросами потеряно."""

    evt: int
    seq: int
    errno: int
    text: str
    missed: int


class StopResult(Enum):
    """Итог ожидания эха стопа."""

    ACKED = "acked"  # TLM_STOP_ACK == наше значение
    SUPERSEDED = "superseded"  # эхо уже новее нашего стопа (его перекрыл другой)


@dataclass(frozen=True, slots=True)
class SyncReport:
    """Итог ``sync_params``: ``sent`` — число отправленных ``PARAM_SET`` значений (без метки);
    ``applied`` — выдан ли ``PARAM_APPLY``; ``epoch`` — метка ПК."""

    sent: int
    applied: bool
    epoch: int


@dataclass(frozen=True, slots=True)
class _Inflight:
    """Метка «seq в полёте»: seq, поколение стопа на шаге (2) и признак опкода ``done_seq`` (для О5)."""

    seq: int
    generation: int
    done_seq: bool


@dataclass(frozen=True, slots=True)
class _DoneBase:
    """База ожидания завершения: seq команды и ``ERR_EVT`` ДО записи CMD."""

    seq: int
    err_evt: int


# --- клиент --------------------------------------------------------------------------------


class RobotClientV2:
    """Клиент протокола v2. Транспорт внедряется (``ModbusDevice`` или ``FakeRobotTransport``).

    Args:
        transport: ``DeviceTransport`` (подключённый вызывающим).
        config:    ``ClientV2Config``.
        rng/clock/sleep: инъекция для детерминированных тестов.
    """

    def __init__(
        self,
        transport: DeviceTransport,
        config: ClientV2Config,
        *,
        rng: random.Random | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._t = transport
        self._cfg = config
        self._clock = clock
        self._sleep = sleep
        # seq mailbox — не секрет, а метка команды: криптостойкий генератор не нужен.
        self._next_seq_value = (rng if rng is not None else random.Random()).randint(1, _SEQ_MAX)  # nosec B311

        self._mailbox_lock = threading.Lock()  # только cmd()
        self._stop_lock = threading.Lock()  # «выдать stop_seq + одна запись FC6» и сверка поколения
        self._hb_lock = threading.Lock()
        self._jog_lock = threading.Lock()
        self._err_lock = threading.Lock()
        self._state_lock = threading.Lock()  # листовой: только поля без ввода-вывода
        self._probe_lock = threading.Lock()

        self._probed = False
        self._inflight: _Inflight | None = None  # ответ на этот seq не дождались (только cmd()/probe())
        self._last_done: _DoneBase | None = None
        self._hb_value = 0
        self._jog_value = 0
        self._err_cursor = 0
        # Счётчики изменений: probe не затирает базу, если пока он читал, её уже сдвинул kick/stop/poll.
        self._hb_gen = 0
        self._jog_gen = 0
        self._err_gen = 0
        self._stop_seq = 0
        self._stop_generation = 0  # растёт ПОСЛЕ записи STOP_REQ, под _stop_lock
        self._last_halt_gen = 0
        self._wdg_raw: int | None = None
        self._jog_raw: int | None = None

    # ------------------------------------------------------------------ #
    # probe
    # ------------------------------------------------------------------ #

    def probe(self) -> None:
        """Проверить прошивку и снять базу пульса, поводка, стопа и событий. Только чтения.

        Pre: транспорт подключён. Post: успех -> «probed», метка «seq в полёте» снята;
        любой исход начинается со сброса «probed».
        Raises: ``WrongFirmware`` (TLM_PROTO_VER = 0 или старший байт ≠ 0x02) — дальше ничего не читается.
        """
        with self._state_lock:
            self._probed = False  # неудачный probe не оставляет клиента «проверенным»
        with self._hb_lock:
            hb_gen = self._hb_gen
        with self._jog_lock:
            jog_gen = self._jog_gen
        with self._err_lock:
            err_gen = self._err_gen
        with self._stop_lock:
            stop_gen = self._stop_generation
        block = self._t.read_registers(_RES_BASE, _BLOCK_COUNT)
        proto = int(block[_off("TLM_PROTO_VER")])
        if proto == 0 or (proto >> 8) != _PROTO_MAJOR:
            raise WrongFirmware(proto)
        wdg_raw = self._read_param_slot("P_WDG_TIMEOUT_MS")
        jog_raw = self._read_param_slot("P_JOG_LEASE_MS")
        with self._hb_lock:
            if self._hb_gen == hb_gen:
                self._hb_value = int(block[_off("HB_PC")])
        with self._jog_lock:
            if self._jog_gen == jog_gen:
                self._jog_value = int(block[_off("JOG_LEASE")])
        with self._err_lock:
            if self._err_gen == err_gen:
                self._err_cursor = int(block[_off("TLM_ERR_EVT")])
        with self._stop_lock:
            if self._stop_generation == stop_gen:  # стоп, прошедший во время probe, уже сдвинул stop_seq дальше эха
                self._stop_seq = int(block[_off("TLM_STOP_ACK")]) >> 2
        with self._state_lock:
            self._wdg_raw = wdg_raw
            self._jog_raw = jog_raw
            self._inflight = None
            self._probed = True

    def _read_param_slot(self, name: str) -> int:
        return int(self._t.read_registers(CONSTANTS["PMIR_BASE"] + PARAM_ID[name], 1)[0])

    def _ensure_probed(self) -> None:
        """Первый вызов любого метода до ``probe()``: проверка прошивки делается сама (только чтения)."""
        if not self._t.is_connected:
            with self._state_lock:
                self._probed = False  # после разрыва базы устарели: следующий вызов проверит прошивку заново
            raise RobotNotConnectedError("Транспорт робота не подключён")
        if self._probed:
            return
        with self._probe_lock:
            if not self._probed:
                self.probe()

    @property
    def heartbeat_period_s(self) -> float | None:
        """Период ``kick_heartbeat`` (четверть ``P_WDG_TIMEOUT_MS``); None — сторож выключен или нет probe."""
        raw = self._wdg_raw
        return None if not raw else raw / _HB_PERIOD_DIV

    @property
    def jog_lease_period_s(self) -> float | None:
        """Период ``jog_lease`` (треть ``P_JOG_LEASE_MS``); None до probe."""
        raw = self._jog_raw
        return None if raw is None else raw / _JOG_PERIOD_DIV

    # ------------------------------------------------------------------ #
    # пульс и поводок
    # ------------------------------------------------------------------ #

    def kick_heartbeat(self) -> None:
        """Записать ``HB_PC`` = последнее значение + 1 (по кругу 16 бит). Одна запись FC6, mailbox не берёт.

        Pre: транспорт подключён (до probe проверка прошивки делается сама). Post: регистр изменён относительно
        прочитанного в probe. Raises: ``RobotNotConnectedError``, ``WrongFirmware``.
        """
        self._ensure_probed()
        with self._hb_lock:
            self._hb_gen += 1
            self._hb_value = (self._hb_value + 1) & 0xFFFF  # значение «израсходовано» и при сбое записи
            self._t.transaction([("w", REG["HB_PC"], self._hb_value)])

    def jog_lease(self) -> None:
        """Записать ``JOG_LEASE`` = последнее значение + 1 (по кругу 16 бит). Одна запись FC6, mailbox не берёт.

        Pre: транспорт подключён (до probe проверка прошивки делается сама). Post: регистр изменён относительно
        прочитанного в probe. Raises: ``RobotNotConnectedError``, ``WrongFirmware``.
        """
        self._ensure_probed()
        with self._jog_lock:
            self._jog_gen += 1
            self._jog_value = (self._jog_value + 1) & 0xFFFF
            self._t.transaction([("w", REG["JOG_LEASE"], self._jog_value)])

    # ------------------------------------------------------------------ #
    # mailbox
    # ------------------------------------------------------------------ #

    def cmd(self, op: str, args: Sequence[int]) -> CmdResult:
        """Одна транзакция mailbox. Сериализуется ``_mailbox_lock``.

        Pre: ``op`` ∈ ``OP``; ``len(args) == OP_SPEC[op]["argc"]``; каждый аргумент целый в ``W_MIN``..65535
        (иначе ``ValueError`` без записи). Post: ACK -> ``CmdResult``; для опкодов ``done_seq`` — ещё и база для
        ``wait_done``. Raises: ``RobotNak`` (NAK), ``RobotTimeout("response")`` (после него — ``stop()``),
        ``RobotAborted`` (команда ``done_seq`` принята уже после стопа, О5; клиент сам повторил стоп; то же при
        позднем ACK прежней команды «в полёте» — тогда новая команда не пишется).
        """
        spec = OP_SPEC.get(op)
        if spec is None:
            raise ValueError("неизвестная операция")
        if len(args) != spec["argc"]:
            raise ValueError("число аргументов не совпадает с OP_SPEC")
        words = [_encode_word(value, f"аргумент #{i}") for i, value in enumerate(args)]
        self._ensure_probed()
        with self._mailbox_lock:
            self._settle_inflight()
            with self._stop_lock:
                generation = self._stop_generation
            base = self._t.read_registers(_RES_BASE, _BLOCK_COUNT)
            seq = self._issue_seq(base)
            # Метка — ДО записи: сбой транспорта на записи оставляет её, и следующий cmd() сначала досмотрит seq.
            self._inflight = _Inflight(seq, generation, spec["result"] == "done_seq")
            self._t.transaction(
                [
                    ("wm", REG["CMD_SEQ"], [seq, OP[op], len(words), *words]),
                    ("w", REG["CMD_FLAG"], 1),
                ]
            )
            self._wait_res(seq)
            self._inflight = None
            result = self._parse_res(self._t.read_registers(_RES_BASE, _RES_BLOCK_COUNT))
            if spec["result"] != "done_seq":
                return result
            self._abort_if_overtaken(seq, generation)
            with self._state_lock:
                self._last_done = _DoneBase(seq, int(base[_off("TLM_ERR_EVT")]))
            return result

    def _settle_inflight(self) -> None:
        """Досмотреть ответ на прежний seq «в полёте»; метка снимается в любом исходе.

        О5 и здесь: поздний ACK команды ``done_seq`` при сменившемся поколении стопа -> повтор стопа и ``RobotAborted``
        (из этого же ``cmd()``, своя команда не пишется). Поздний NAK — команда не исполнялась, ничего не делаем.
        """
        mark = self._inflight
        if mark is None:
            return
        try:
            self._wait_res(mark.seq)
        finally:
            self._inflight = None
        if not mark.done_seq:
            return
        try:
            self._parse_res(self._t.read_registers(_RES_BASE, _RES_BLOCK_COUNT))
        except RobotNak:
            return
        self._abort_if_overtaken(mark.seq, mark.generation)

    def _issue_seq(self, base: Sequence[int]) -> int:
        """Выдать seq: пропустить 0 и текущие ``RES_SEQ`` / ``DONE_SEQ`` / ``ERR_SEQ`` (повтор seq = прежний RES)."""
        taken = {0, int(base[_off("RES_SEQ")]), int(base[_off("TLM_DONE_SEQ")]), int(base[_off("TLM_ERR_SEQ")])}
        seq = self._next_seq_value
        while seq in taken:
            seq = _next_seq(seq)
        self._next_seq_value = _next_seq(seq)
        return seq

    def _wait_res(self, seq: int) -> None:
        deadline = self._clock() + self._cfg.res_timeout_s
        while True:
            if int(self._t.read_registers(REG["RES_SEQ"], 1)[0]) == seq:
                return
            if self._clock() >= deadline:
                raise RobotTimeout("response", seq)
            self._sleep(self._cfg.poll_interval_s)

    @staticmethod
    def _parse_res(block: Sequence[int]) -> CmdResult:
        status, errno = int(block[1]), int(block[2])
        rvalc = min(int(block[3]), _RES_RVALS_MAX)  # RVAL сверх RES_RVALC — остаток прошлого ответа
        rvals = tuple(int(v) for v in block[4 : 4 + rvalc])
        seq = int(block[0])
        if status == _STATUS_ACK:
            return CmdResult(seq, rvals)
        reason: int | None = None
        index: int | None = None
        if errno == ERR["E_RANGE"] and rvalc >= 1:
            reason = rvals[0]
        elif errno == ERR["E_SC_RECORD"]:
            index = rvals[0] if rvalc >= 1 else None
            reason = rvals[1] if rvalc >= 2 else None
        text = ERR_TEXT.get(errno, _UNKNOWN_ERR_TEXT)
        if reason in REASON_TEXT:
            text += ": " + REASON_TEXT[reason]
        raise RobotNak(errno, reason, text, index, rvals)

    def _abort_if_overtaken(self, seq: int, generation: int) -> None:
        """О5: стоп прошёл между базой и ACK -> команду нельзя считать живой; повторить стоп и поднять RobotAborted.

        Сверка и повтор — под одним ``_stop_lock``: чужой стоп не вклинится между ними.
        """
        with self._stop_lock:
            if self._stop_generation == generation:
                return
            level = STOP_LEVEL["HALT"] if self._last_halt_gen > generation else STOP_LEVEL["HARD"]
            self._issue_stop_locked(level)
        raise RobotAborted(seq, ERR["E_ABORTED"], ERR_TEXT[ERR["E_ABORTED"]])

    # ------------------------------------------------------------------ #
    # завершение команды и события
    # ------------------------------------------------------------------ #

    def wait_done(self, seq: int) -> None:
        """Ждать завершения последней команды ``done_seq`` этого клиента. ``_mailbox_lock`` не берёт.

        Pre: ``seq`` — seq последнего ``CmdResult`` опкода ``done_seq`` (иначе ``ValueError``). Post: возврат —
        ``TLM_DONE_SEQ == seq``. Raises: ``RobotAborted`` / ``RobotCommandError`` (событие ``ERR_*`` нашей
        команды или «событие обрыва перекрыто»), ``RobotTimeout("done")``.
        """
        with self._state_lock:
            base = self._last_done
        if base is None or base.seq != seq:
            raise ValueError("seq не принадлежит последней команде done_seq этого клиента")
        deadline = self._clock() + self._cfg.done_timeout_s
        while True:
            tlm = self._t.read_registers(_TLM_BASE, _TLM_COUNT)
            if int(tlm[_toff("TLM_DONE_SEQ")]) == seq:
                return
            if int(tlm[_toff("TLM_ERR_EVT")]) != base.err_evt:
                errno = int(tlm[_toff("TLM_ERRNO_LAST")])
                if int(tlm[_toff("TLM_ERR_SEQ")]) == seq:
                    text = ERR_TEXT.get(errno, _UNKNOWN_ERR_TEXT)
                    if errno == ERR["E_ABORTED"]:
                        raise RobotAborted(seq, errno, text)
                    raise RobotCommandError(seq, errno, text)
                if int(tlm[_toff("TLM_ACTIVITY")]) in (_ACTIVITY_IDLE, _ACTIVITY_FAULT):
                    raise RobotCommandError(seq, None, _MASKED_EVENT_TEXT)
            if self._clock() >= deadline:
                raise RobotTimeout("done", seq)
            self._sleep(self._cfg.poll_interval_s)

    def poll_errors(self) -> list[ErrorEvent]:
        """Асинхронные события: ``ERR_EVT`` изменился с прошлого вызова -> одно событие (последнее из TLM).

        Курсор — ``ERR_EVT`` из probe, от ``wait_done`` не зависит; события своих команд тоже возвращаются.
        ``missed`` = число пропущенных событий между опросами.

        Pre: транспорт подключён (до probe проверка прошивки делается сама). Post: список из 0 или 1 события; курсор
        сдвинут к прочитанному ``ERR_EVT``. Raises: ``RobotNotConnectedError``, ``WrongFirmware``.
        """
        self._ensure_probed()
        with self._err_lock:
            block = self._t.read_registers(REG["TLM_ERR_SEQ"], 3)  # ERR_SEQ, ERRNO_LAST, ERR_EVT
            evt = int(block[2])
            delta = (evt - self._err_cursor) & 0xFFFF
            if delta == 0:
                return []
            self._err_cursor = evt
            self._err_gen += 1
        errno = int(block[1])
        return [ErrorEvent(evt, int(block[0]), errno, ERR_TEXT.get(errno, _UNKNOWN_ERR_TEXT), delta - 1)]

    # ------------------------------------------------------------------ #
    # стоп
    # ------------------------------------------------------------------ #

    def stop(self, level: int) -> StopResult:
        """Стоп с seq (protocol-spec §8). Замок держится только на «выдать stop_seq + одна запись FC6».

        Pre: ``level`` ∈ {1 SOFT, 2 HARD, 3 HALT} (иначе ``ValueError`` без записи). Post: ``ACKED`` —
        ``TLM_STOP_ACK`` равен нашему значению; ``SUPERSEDED`` — эхо уже новее. Raises: ``RobotTimeout("stop_echo")``.
        ``_mailbox_lock`` не берёт: стоп проходит, пока ``cmd()`` ждёт ответ.
        """
        if not isinstance(level, int) or isinstance(level, bool) or level not in STOP_LEVEL.values():
            raise ValueError("level стопа вне 1..3")
        self._ensure_probed()
        with self._stop_lock:
            value = self._issue_stop_locked(level)
        return self._wait_stop_echo(value, level)

    def _issue_stop_locked(self, level: int) -> int:
        """Под ``_stop_lock``: следующий ``stop_seq`` + одна запись FC6. Поколение растёт ПОСЛЕ записи, в finally."""
        self._stop_seq = self._stop_seq % _STOP_SEQ_MAX + 1
        value = self._stop_seq * 4 + level
        try:
            self._t.transaction([("w", REG["STOP_REQ"], value)])
        finally:
            self._stop_generation += 1
            if level == STOP_LEVEL["HALT"]:
                self._last_halt_gen = self._stop_generation
        return value

    def _wait_stop_echo(self, value: int, level: int) -> StopResult:
        timeout = self._cfg.soft_echo_timeout_s if level == STOP_LEVEL["SOFT"] else self._cfg.stop_echo_timeout_s
        deadline = self._clock() + timeout
        ours = value >> 2
        while True:
            echo = int(self._t.read_registers(REG["TLM_STOP_ACK"], 1)[0])
            if echo == value:
                return StopResult.ACKED
            if 1 <= ((echo >> 2) - ours) % _STOP_SEQ_MAX <= _STOP_HALF_CIRCLE:
                return StopResult.SUPERSEDED
            if self._clock() >= deadline:
                raise RobotTimeout("stop_echo")
            self._sleep(self._cfg.poll_interval_s)

    # ------------------------------------------------------------------ #
    # синхронизация параметров
    # ------------------------------------------------------------------ #

    def sync_params(self, values: Mapping[str, int], epoch: int) -> SyncReport:
        """Синхронизация по метке (params.md §11.4 п.3). Значения сырые (§11.1).

        Pre: ``values`` содержит все имена ``PARAM_ID`` кроме ``P_CONFIG_EPOCH`` (лишнего и неизвестного нет);
        ``epoch`` в 1..65535 (иначе ``ValueError`` без записи). Post: метка и отпечаток словаря совпали ->
        ни одной записи, ``SyncReport(0, False, epoch)``; иначе все ``PARAM_SET``, ``PARAM_APPLY`` при
        ``TLM_CFG_PENDING == 1``, сверка ``PMIR`` и ``PARAM_SET P_CONFIG_EPOCH`` ПОСЛЕДНЕЙ записью.
        Raises: ``RobotNak`` (метка не пишется), ``RobotSyncError`` (метка не пишется).
        """
        expected_names = set(PARAM_ID) - {"P_CONFIG_EPOCH"}
        if set(values) != expected_names:
            raise ValueError("values: набор имён не совпадает с PARAM_ID без P_CONFIG_EPOCH")
        raw_by_id = {
            PARAM_ID[name]: _encode_word(values[name], f"параметр #{PARAM_ID[name]}")
            for name in PARAM_ID
            if name in expected_names
        }
        if isinstance(epoch, bool) or not isinstance(epoch, int) or not 1 <= epoch <= _SEQ_MAX:
            raise ValueError("epoch вне диапазона 1..65535")
        self._ensure_probed()

        robot_epoch = int(self._t.read_registers(REG["TLM_CFG_EPOCH"], 1)[0])
        robot_dict = int(self._t.read_registers(REG["PMIR_DICT"], 1)[0])
        if robot_epoch == epoch and robot_dict == DICT_FINGERPRINT:
            return SyncReport(0, False, epoch)

        for pid, raw in raw_by_id.items():
            self.cmd("PARAM_SET", [pid, raw])
        applied = False
        if int(self._t.read_registers(REG["TLM_CFG_PENDING"], 1)[0]) == 1:
            self.cmd("PARAM_APPLY", [])
            applied = True
        self._verify_mirror(raw_by_id)
        self.cmd("PARAM_SET", [PARAM_ID["P_CONFIG_EPOCH"], epoch])
        with self._state_lock:
            self._wdg_raw = raw_by_id[PARAM_ID["P_WDG_TIMEOUT_MS"]]
            self._jog_raw = raw_by_id[PARAM_ID["P_JOG_LEASE_MS"]]
        return SyncReport(len(raw_by_id), applied, epoch)

    def _verify_mirror(self, raw_by_id: Mapping[int, int]) -> None:
        """Прочитать слоты ``PMIR`` чтениями ≤ ``READ_MAX`` и сверить с записанным."""
        total = max(raw_by_id) + 1
        mirror: list[int] = []
        while len(mirror) < total:
            count = min(CONSTANTS["READ_MAX"], total - len(mirror))
            mirror.extend(int(v) for v in self._t.read_registers(CONSTANTS["PMIR_BASE"] + len(mirror), count))
        for pid, expected in raw_by_id.items():
            if mirror[pid] != expected:
                raise RobotSyncError(pid, expected, mirror[pid])
