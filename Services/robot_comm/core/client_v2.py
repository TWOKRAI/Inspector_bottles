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
единой записи; транспорт не подключён -> ``RobotNotConnectedError``. Исключение — ``stop()`` проверенного клиента:
он пишет всегда и ``is_connected`` не проверяет (``ModbusDevice`` после одной случайной ошибки считает связь
оборванной); если связи правда нет, транспорт бросит ошибку, и вызывающий узнает, что стоп не доставлен.

Переподключение: любое исключение транспорта в клиенте и смена ``get_status()['connected_since']`` помечают базы
устаревшими, следующий вызов (кроме ``stop()``) сам делает ``probe()``. Драйвер обязан звать ``probe()`` после каждого
``transport.connect()``.

Уровень стопа не понижается до эха: пока более сильный стоп не подтверждён эхом, новый пишется с уровнем
``max(запрошенный, сильнейший неподтверждённый)``; ожидающий получает ``SUPERSEDED`` только от эха новее,
чей уровень не ниже его собственного.

О5 не теряется на путях с исключением: метка «в полёте» команды ``done_seq`` снимается только после разбора ответа
и сверки поколения стопа (при NAK — после разбора); при любом исключении она остаётся, и следующий ``cmd()`` сверит
поколение заново. ``probe()`` метку ``done_seq`` не снимает.

Константы и адреса — только из ``protocol_v2`` и ``params_v2`` (сгенерированы).
"""

from __future__ import annotations

import math
import operator
import random
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from Services.robot_comm.core import wire_v2
from Services.robot_comm.core.params_v2 import DICT_FINGERPRINT, PARAM_ID, PARAMS
from Services.robot_comm.core.protocol_v2 import (
    ACT,
    CONSTANTS,
    ERR,
    ERR_TEXT,
    KIND,
    OP,
    OP_SPEC,
    REASON_TEXT,
    REG,
    STOP_LEVEL,
)
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

if TYPE_CHECKING:
    from Services.robot_comm.programs.program import Scenario

__all__ = [
    "ClientV2Config",
    "CmdResult",
    "ErrorEvent",
    "RobotClientV2",
    "RunReport",
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


def _seq_newer(echo_seq: int, ours: int) -> bool:
    """``echo_seq`` строго новее ``ours`` на круге 1..16383 (окно в полкруга). Seq 0 вне круга (эхо с загрузки)."""
    return echo_seq != 0 and 1 <= (echo_seq - ours) % _STOP_SEQ_MAX <= _STOP_HALF_CIRCLE


def _echo_covers(echo: int, seq: int, level: int) -> bool:
    """Эхо ``echo`` подтверждает стоп (``seq``, ``level``): тот же seq или новее, уровень эха не ниже."""
    return (echo >> 2) == seq and (echo & 3) >= level or _seq_newer(echo >> 2, seq) and (echo & 3) >= level


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
    #: Шаг округления координат сценария, мм и °: кратен шагу провода ``1 / WIRE_SCALE`` и не меньше его.
    round_step: float = 1 / CONSTANTS["WIRE_SCALE"]

    @field_validator("round_step")
    @classmethod
    def _round_step_on_wire_grid(cls, v: float) -> float:
        k = v * CONSTANTS["WIRE_SCALE"]
        if not math.isfinite(k) or round(k) < 1 or abs(k - round(k)) > 1e-9:
            # Текст без входного значения (правило проекта, см. from_dict).
            raise ValueError("round_step: кратен шагу провода 0.1 и не меньше его")
        return v

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
class RunReport:
    """Итог ``run_chunks``: ``chunks`` — ``(start, count, offset)`` каждого куска по порядку; ``total`` — записей."""

    chunks: tuple[tuple[int, int, int], ...]
    total: int


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

    #: Обёртка на каждый опкод: опкод ``OP`` -> имя метода (ключи == ``set(OP)``).
    WRAPPERS: dict[str, str] = {
        "PING": "ping",
        "CLEAR_ERR": "clear_err",
        "PTP_MOVE": "ptp_move",
        "HOME": "home",
        "JOG_STEP": "jog_step",
        "JOG_CONT": "jog_cont",
        "CVT_JOB": "cvt_job",
        "SC_RUN": "sc_run",
        "SERVO": "servo",
        "DO_SET": "do_set",
        "PARAM_SET": "param_set",
        "PARAM_GET": "param_get",
        "PARAM_APPLY": "param_apply",
    }

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

        self._probed = False  # прошивка v2 подтверждена, и последний probe не провалился
        self._stale = False  # связь рвалась или транспорт дал ошибку после probe: базы устарели
        self._probed_link: object = None  # connected_since на момент probe
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
        self._stop_base_gen = 0  # растёт при каждом изменении _stop_seq (запись стопа, probe)
        self._run_stop_base: int | None = None  # поколение стопа на старте последнего run_chunks (g0)
        self._echo_log: deque[int] = deque(maxlen=16)  # недавние различные значения TLM_STOP_ACK (кто бы ни читал)
        self._stop_pending: tuple[int, int] | None = None  # (уровень, seq) сильнейшего неподтверждённого стопа
        self._last_halt_gen = 0
        self._wdg_raw: int | None = None
        self._jog_raw: int | None = None
        self._sc_active = False  # идёт run_chunks (под _state_lock): второй прогон на клиенте — RuntimeError

    # ------------------------------------------------------------------ #
    # probe
    # ------------------------------------------------------------------ #

    def probe(self) -> None:
        """Проверить прошивку и снять базу пульса, поводка, стопа и событий. Только чтения.

        Pre: транспорт подключён. Post: успех -> «probed», метка мгновенного опкода снята (метка ``done_seq``
        остаётся для О5); любой исход начинается со сброса «probed».
        Raises: ``WrongFirmware`` (TLM_PROTO_VER = 0 или старший байт ≠ 0x02) — дальше ничего не читается.
        """
        with self._state_lock:
            self._probed = False  # неудачный probe не оставляет клиента «проверенным»
        link = self._link_id()  # до чтения: переподключение во время probe сделает следующий вызов проверкой заново
        with self._hb_lock:
            hb_gen = self._hb_gen
        with self._jog_lock:
            jog_gen = self._jog_gen
        with self._err_lock:
            err_gen = self._err_gen
        with self._stop_lock:
            stop_gen = self._stop_base_gen
        block = self._rd(_RES_BASE, _BLOCK_COUNT)
        proto = int(block[_off("TLM_PROTO_VER")])
        if proto == 0 or (proto >> 8) != _PROTO_MAJOR:
            raise WrongFirmware(proto)
        wdg_raw = self._read_param_slot("P_WDG_TIMEOUT_MS")
        jog_raw = self._read_param_slot("P_JOG_LEASE_MS")
        with self._hb_lock:
            if self._hb_gen == hb_gen:
                self._hb_value = int(block[_off("HB_PC")])
                self._hb_gen += 1
        with self._jog_lock:
            if self._jog_gen == jog_gen:
                self._jog_value = int(block[_off("JOG_LEASE")])
                self._jog_gen += 1
        with self._err_lock:
            if self._err_gen == err_gen:
                self._err_cursor = int(block[_off("TLM_ERR_EVT")])
                self._err_gen += 1
        with self._stop_lock:
            if self._stop_base_gen == stop_gen:  # стоп, прошедший во время probe, уже сдвинул stop_seq дальше эха
                ack_seq = int(block[_off("TLM_STOP_ACK")]) >> 2
                req_seq = int(block[_off("STOP_REQ")]) >> 2
                # Следующий seq считаем от более нового из запроса и эха: записанный, но ещё не подтверждённый стоп
                # (STOP_REQ впереди эха) нельзя повторить тем же значением — робот его проигнорирует.
                self._stop_seq = req_seq if _seq_newer(req_seq, ack_seq) else ack_seq
                self._stop_base_gen += 1
                self._echo_log.clear()
                if block[_off("STOP_REQ")] == block[_off("TLM_STOP_ACK")]:
                    self._stop_pending = None  # всё записанное подтверждено (или робот перезапущен)
        with self._state_lock:
            self._wdg_raw = wdg_raw
            self._jog_raw = jog_raw
            if self._inflight is not None and not self._inflight.done_seq:
                self._inflight = None  # метку done_seq снимает только cmd() после сверки О5
            self._probed = True
            self._stale = False
            self._probed_link = link

    def _rd(self, address: int, count: int = 1) -> list[int]:
        """Чтение через транспорт; любое исключение транспорта помечает базы устаревшими."""
        try:
            return self._t.read_registers(address, count)
        except Exception:
            self._mark_stale()
            raise

    def _wr(self, ops: list[tuple]) -> bool:
        """Запись через транспорт; любое исключение транспорта помечает базы устаревшими."""
        try:
            return self._t.transaction(ops)
        except Exception:
            self._mark_stale()
            raise

    def _mark_stale(self) -> None:
        with self._state_lock:
            self._stale = True

    def _link_id(self) -> object:
        """Идентификатор соединения: ``connected_since`` из ``get_status()`` (меняется при каждом connect())."""
        return self._t.get_status().get("connected_since")

    def _read_param_slot(self, name: str) -> int:
        return int(self._rd(CONSTANTS["PMIR_BASE"] + PARAM_ID[name], 1)[0])

    def _ensure_probed(self) -> None:
        """Первый вызов любого метода до ``probe()``: проверка прошивки делается сама (только чтения)."""
        if not self._t.is_connected:
            with self._state_lock:
                self._stale = True  # после разрыва базы устарели: следующий вызов проверит прошивку заново
            raise RobotNotConnectedError("Транспорт робота не подключён")
        if self._probed and not self._stale and self._link_id() == self._probed_link:
            return
        with self._probe_lock:
            if not (self._probed and not self._stale and self._link_id() == self._probed_link):
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
            self._wr([("w", REG["HB_PC"], self._hb_value)])

    def jog_lease(self) -> None:
        """Записать ``JOG_LEASE`` = последнее значение + 1 (по кругу 16 бит). Одна запись FC6, mailbox не берёт.

        Pre: транспорт подключён (до probe проверка прошивки делается сама). Post: регистр изменён относительно
        прочитанного в probe. Raises: ``RobotNotConnectedError``, ``WrongFirmware``.
        """
        self._ensure_probed()
        with self._jog_lock:
            self._jog_gen += 1
            self._jog_value = (self._jog_value + 1) & 0xFFFF
            self._wr([("w", REG["JOG_LEASE"], self._jog_value)])

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
            base = self._rd(_RES_BASE, _BLOCK_COUNT)
            self._note_echo(int(base[_off("TLM_STOP_ACK")]))
            seq = self._issue_seq(base)
            # Метка — ДО записи: сбой транспорта на записи оставляет её, и следующий cmd() сначала досмотрит seq.
            self._inflight = _Inflight(seq, generation, spec["result"] == "done_seq")
            self._wr(
                [
                    ("wm", REG["CMD_SEQ"], [seq, OP[op], len(words), *words]),
                    ("w", REG["CMD_FLAG"], 1),
                ]
            )
            self._wait_res(seq)
            result = self._read_result(seq, generation, spec["result"] == "done_seq")
            if spec["result"] != "done_seq":
                return result
            with self._state_lock:
                self._last_done = _DoneBase(seq, int(base[_off("TLM_ERR_EVT")]))
            return result

    def _settle_inflight(self) -> None:
        """Досмотреть ответ на прежний seq «в полёте».

        Нет ответа за ``res_timeout_s`` -> ``RobotTimeout("response")``; метка снимается, кроме ``done_seq`` при
        прошедшем стопе и живом слоте CMD (``_keep_mark_after_timeout``). Любое другое исключение метку оставляет.
        О5 и здесь: поздний ACK команды ``done_seq`` при сменившемся поколении стопа -> повтор стопа и
        ``RobotAborted`` (из этого же ``cmd()``, своя команда не пишется). Поздний NAK — команда не исполнялась.
        """
        mark = self._inflight
        if mark is None:
            return
        try:
            self._wait_res(mark.seq)
        except RobotTimeout:
            if not self._keep_mark_after_timeout(mark):
                if mark.done_seq:
                    # Fail-safe: метку снимаем, но команда могла стартовать позже, чем мы ждали, — стоп повторяем.
                    self._reissue_stop_if_overtaken(mark.generation)  # ошибка записи уйдёт наружу, метка останется
                self._inflight = None
            raise
        try:
            self._read_result(mark.seq, mark.generation, mark.done_seq)
        except RobotNak:
            return

    def _keep_mark_after_timeout(self, mark: _Inflight) -> bool:
        """О5: робот молчит, а стоп уже прошёл -> метку ``done_seq`` держим, пока слот CMD жив.

        Слот мёртв, если ``CMD_SEQ`` в нём не наш seq (регистры сброшены, робот перезапущен): команда не исполнится
        никогда. Поколение не менялось -> прежнее поведение (метка снимается, следующий cmd() пишет сразу).
        """
        if not mark.done_seq:
            return False
        with self._stop_lock:
            if self._stop_generation == mark.generation:
                return False
        slot = self._rd(REG["CMD_FLAG"], 2)  # CMD_FLAG, CMD_SEQ
        # Слот исполнится, только пока флаг взведён: флаг 0 без RES за res_timeout_s — прошивка взяла слот и умерла.
        return int(slot[0]) == 1 and int(slot[1]) == mark.seq

    def _read_result(self, seq: int, generation: int, done_seq: bool) -> CmdResult:
        """Прочитать и разобрать RES-блок; для ``done_seq`` — сверить поколение стопа (О5).

        Метка «в полёте» снимается ТОЛЬКО на успешном выходе: после NAK, после сверки без обгона и после успешного
        повтора стопа (``RobotAborted``). Ошибка чтения или записи стопа оставляет метку — сверка повторится.
        """
        try:
            result = self._parse_res(self._rd(_RES_BASE, _RES_BLOCK_COUNT))
        except RobotNak:
            self._inflight = None
            raise
        if done_seq:
            self._abort_if_overtaken(seq, generation)
        self._inflight = None
        return result

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
            if int(self._rd(REG["RES_SEQ"], 1)[0]) == seq:
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

    def _reissue_stop_if_overtaken(self, generation: int) -> bool:
        """Если с поколения ``generation`` проходил стоп — одна запись стопа (HALT, если в окне был HALT, иначе HARD).

        Под ``_stop_lock``, без ожидания эха. Возвращает True, если стоп записан.
        """
        with self._stop_lock:
            if self._stop_generation == generation:
                return False
            level = STOP_LEVEL["HALT"] if self._last_halt_gen > generation else STOP_LEVEL["HARD"]
            self._issue_stop_locked(level)
        return True

    def _abort_if_overtaken(self, seq: int, generation: int) -> None:
        """О5: стоп прошёл между базой и ACK -> команду нельзя считать живой; повторить стоп и поднять RobotAborted.

        Сверка и повтор — под одним ``_stop_lock``: чужой стоп не вклинится между ними.
        """
        if not self._reissue_stop_if_overtaken(generation):
            return
        self._inflight = None
        raise RobotAborted(seq, ERR["E_ABORTED"], ERR_TEXT[ERR["E_ABORTED"]])

    # ------------------------------------------------------------------ #
    # завершение команды и события
    # ------------------------------------------------------------------ #

    def wait_done(self, seq: int, *, on_poll: Callable[[Sequence[int]], None] | None = None) -> None:
        """Ждать завершения последней команды ``done_seq`` этого клиента. ``_mailbox_lock`` не берёт.

        Pre: ``seq`` — seq последнего ``CmdResult`` опкода ``done_seq`` (иначе ``ValueError``). Post: возврат —
        ``TLM_DONE_SEQ == seq``. ``on_poll(tlm)`` — после каждого чтения блока TLM (32 слова от ``TLM_PROTO_VER``)
        и до проверок; его исключение выходит наружу. Raises: ``RobotAborted`` / ``RobotCommandError`` (событие
        ``ERR_*`` нашей команды или «событие обрыва перекрыто»), ``RobotTimeout("done")``.
        """
        with self._state_lock:
            base = self._last_done
        if base is None or base.seq != seq:
            raise ValueError("seq не принадлежит последней команде done_seq этого клиента")
        deadline = self._clock() + self._cfg.done_timeout_s
        while True:
            tlm = self._rd(_TLM_BASE, _TLM_COUNT)
            if on_poll is not None:
                on_poll(tlm)
            self._note_echo(int(tlm[_toff("TLM_STOP_ACK")]))
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
            block = self._rd(REG["TLM_ERR_SEQ"], 3)  # ERR_SEQ, ERRNO_LAST, ERR_EVT
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

        Pre: ``level`` ∈ {1 SOFT, 2 HARD, 3 HALT} (иначе ``ValueError`` без записи). Проверенный клиент пишет всегда
        и ``is_connected`` не проверяет; непроверенный сначала проверяет прошивку (``WrongFirmware`` /
        ``RobotNotConnectedError`` без записи). Post: записан уровень ``max(level, сильнейший неподтверждённый)``;
        ``ACKED`` — ``TLM_STOP_ACK`` равен нашему значению; ``SUPERSEDED`` — эхо новее нашего с уровнем не ниже.
        Raises: ``RobotTimeout("stop_echo")``, ошибка транспорта (стоп не доставлен). ``_mailbox_lock`` не берёт:
        стоп проходит, пока ``cmd()`` ждёт ответ.
        """
        value = self.issue_stop(level)
        written_level = value & 3
        soft = written_level == STOP_LEVEL["SOFT"]
        timeout = self._cfg.soft_echo_timeout_s if soft else self._cfg.stop_echo_timeout_s
        return self.await_stop_echo(value, written_level, deadline=self._clock() + timeout)

    def issue_stop(self, level: int) -> int:
        """Только запись стопа (T5.3 круг 2): ``stop_seq`` + одна запись FC6 ``STOP_REQ``, без ожидания эха.

        Pre/Raises — как у ``stop`` до записи: ``ValueError`` вне 1..3, непроверенный клиент проверяет прошивку;
        ошибка транспорта — наружу (стоп не доставлен). Post: возвращает записанное значение
        ``stop_seq * 4 + уровень``; записанный уровень = ``значение & 3`` (не ниже сильнейшего неподтверждённого).
        """
        if not isinstance(level, int) or isinstance(level, bool) or level not in STOP_LEVEL.values():
            raise ValueError("level стопа вне 1..3")
        if not self._probed:
            self._ensure_probed()  # только непроверенный клиент: проверенный пишет стоп без оглядки на is_connected
        with self._stop_lock:
            value, _written_level = self._issue_stop_locked(level)
        return value

    def await_stop_echo(self, value: int, level: int, *, deadline: float) -> StopResult:
        """Только ожидание эха стопа ``value`` до абсолютного срока ``deadline`` (часы клиента, монотонные).

        Записей нет. ``ACKED`` — эхо равно ``value``; ``SUPERSEDED`` — эхо новее с уровнем не ниже ``level``.
        Хотя бы одно чтение эха делается и при уже прошедшем сроке. Raises: ``RobotTimeout("stop_echo")`` после
        срока, ошибка транспорта чтения.
        """
        return self._wait_stop_echo(value, max(level, value & 3), deadline)

    def _issue_stop_locked(self, level: int) -> tuple[int, int]:
        """Под ``_stop_lock``: следующий ``stop_seq`` + одна запись FC6. Поколение растёт ПОСЛЕ записи, в finally.

        Уровень не понижается до эха: пишется ``max(level, сильнейший неподтверждённый)``.
        Возвращает (значение, записанный уровень).
        """
        pending = self._stop_pending
        written_level = level if pending is None else max(level, pending[0])
        self._stop_seq = self._stop_seq % _STOP_SEQ_MAX + 1
        self._stop_base_gen += 1
        value = self._stop_seq * 4 + written_level
        self._stop_pending = (written_level, self._stop_seq)  # эхо этого seq подтвердит и все прежние
        try:
            self._wr([("w", REG["STOP_REQ"], value)])
        finally:
            self._stop_generation += 1
            if written_level == STOP_LEVEL["HALT"]:
                self._last_halt_gen = self._stop_generation
        return value, written_level

    def _note_echo(self, echo: int) -> None:
        """Учесть прочитанное эхо: запомнить в журнале, снять «неподтверждённый» стоп, если эхо его покрывает."""
        with self._stop_lock:
            if not self._echo_log or self._echo_log[-1] != echo:
                self._echo_log.append(echo)
            pending = self._stop_pending
            if pending is not None and _echo_covers(echo, pending[1], pending[0]):
                self._stop_pending = None

    def _wait_stop_echo(self, value: int, level: int, deadline: float) -> StopResult:
        ours = value >> 2
        while True:
            self._note_echo(int(self._rd(REG["TLM_STOP_ACK"], 1)[0]))
            with self._stop_lock:
                seen = list(self._echo_log)  # эхо мог увидеть и другой читатель до того, как его перекрыли
            if value in seen:
                return StopResult.ACKED
            if any(_seq_newer(echo >> 2, ours) and (echo & 3) >= level for echo in seen):
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

        robot_epoch = int(self._rd(REG["TLM_CFG_EPOCH"], 1)[0])
        robot_dict = int(self._rd(REG["PMIR_DICT"], 1)[0])
        if robot_epoch == epoch and robot_dict == DICT_FINGERPRINT:
            return SyncReport(0, False, epoch)

        for pid, raw in raw_by_id.items():
            self.cmd("PARAM_SET", [pid, raw])
        applied = False
        if int(self._rd(REG["TLM_CFG_PENDING"], 1)[0]) == 1:
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
            mirror.extend(int(v) for v in self._rd(CONSTANTS["PMIR_BASE"] + len(mirror), count))
        for pid, expected in raw_by_id.items():
            if mirror[pid] != expected:
                raise RobotSyncError(pid, expected, mirror[pid])

    # ------------------------------------------------------------------ #
    # обёртки опкодов (только cmd(); ожидание завершения — вызывающий, wait_done)
    # ------------------------------------------------------------------ #

    def ping(self) -> tuple[int, ...]:
        """PING: значения ответа (``rvals``)."""
        return self.cmd("PING", []).rvals

    def clear_err(self) -> CmdResult:
        """CLEAR_ERR."""
        return self.cmd("CLEAR_ERR", [])

    def ptp_move(self, x: float, y: float, z: float, rz: float, kind: str, spd_pct: int) -> CmdResult:
        """PTP_MOVE: цель в мм и ° (шаг провода), ``kind`` — имя из ``KIND``. Ждать — ``wait_done(result.seq)``."""
        return self.cmd("PTP_MOVE", [*_geom_words(x, y, z, rz), _kind_code(kind), spd_pct])

    def home(self, spd_pct: int) -> CmdResult:
        """HOME."""
        return self.cmd("HOME", [spd_pct])

    def jog_step(self, dx: float, dy: float, dz: float, drz: float, spd_pct: int) -> CmdResult:
        """JOG_STEP: приращения в мм и ° (шаг провода)."""
        return self.cmd("JOG_STEP", [*_geom_words(dx, dy, dz, drz), spd_pct])

    def jog_cont(self, direction: int, speed: int) -> CmdResult:
        """JOG_CONT (поводок — ``jog_lease``)."""
        return self.cmd("JOG_CONT", [direction, speed])

    def cvt_job(
        self,
        ecap: int,
        pick_x: float,
        pick_y: float,
        pick_z: float,
        flags: int,
        place_x: float,
        place_y: float,
        place_z: float,
        place_rz: float,
    ) -> CmdResult:
        """CVT_JOB: ``ecap`` (u32) делится на ``dw_lo`` / ``dw_hi``; координаты в мм и ° (шаг провода)."""
        try:
            ecap_value = operator.index(ecap)
        except TypeError:
            raise ValueError("ecap: ожидается целое") from None
        if not 0 <= ecap_value <= 0xFFFFFFFF:
            raise ValueError("ecap: вне диапазона 0..2^32-1")
        pick = _geom_words(pick_x, pick_y, pick_z)
        place = _geom_words(place_x, place_y, place_z, place_rz)
        return self.cmd("CVT_JOB", [ecap_value & 0xFFFF, ecap_value >> 16, *pick, flags, *place])

    def sc_run(
        self, count: int, sc_id: int, offset: int, spd_pct: int = 0, accel: int = 0, accur: int = 0
    ) -> CmdResult:
        """SC_RUN: ``count`` записей буфера с ``offset``. Ждать — ``wait_done(result.seq)``.

        Стартовое состояние — коды провода как есть (0 не задано; ``accur``: 1 ROUGH, 2 HIGH); диапазон проверяет робот.
        """
        return self.cmd("SC_RUN", [count, sc_id, offset, spd_pct, accel, accur])

    def servo(self, on: bool) -> CmdResult:
        """SERVO."""
        return self.cmd("SERVO", [1 if on else 0])

    def do_set(self, channel: int, on: bool) -> CmdResult:
        """DO_SET."""
        return self.cmd("DO_SET", [channel, 1 if on else 0])

    def param_set(self, name: str, raw: int) -> CmdResult:
        """PARAM_SET по имени из ``PARAM_ID``; ``raw`` — сырое значение (params.md §11.1)."""
        return self.cmd("PARAM_SET", [_param_id(name), raw])

    def param_get(self, name: str) -> int:
        """PARAM_GET по имени из ``PARAM_ID``: сырое значение (params.md §11.1 — u16 или s16).

        Знаковый параметр (``PARAMS[id]["signed"]``) возвращается s16: слово ``>= 0x8000`` -> ``word - 0x10000``
        (круг с ``param_set(name, -1500)`` даёт -1500). Беззнаковый — ``rvals[0]`` как есть.
        """
        pid = _param_id(name)
        raw = int(self.cmd("PARAM_GET", [pid]).rvals[0])
        if PARAMS[pid]["signed"] and raw >= 0x8000:
            return raw - 0x10000
        return raw

    def param_apply(self) -> CmdResult:
        """PARAM_APPLY."""
        return self.cmd("PARAM_APPLY", [])

    # ------------------------------------------------------------------ #
    # буфер сценария и пинг-понг
    # ------------------------------------------------------------------ #

    @property
    def run_stop_base(self) -> int | None:
        """Поколение стопа, взятое последним ``run_chunks`` на старте (g0); None — прогона не было. Только чтение.

        ``stop_generation != run_stop_base`` во время прогона — стоп записан после g0, прогон видит его сам.
        """
        return self._run_stop_base

    @property
    def stop_generation(self) -> int:
        """Поколение стопа клиента: растёт после каждой записи ``STOP_REQ`` (своей или повтора О5). Только чтение."""
        return self._stop_generation

    def upload(self, records: Sequence[Sequence[int]], offset: int) -> None:
        """Записать слова записей в ``SC_BUF`` с записи ``offset`` блоками FC16 по <= ``WRITE_CHUNK`` регистров.

        Pre: каждая запись — ``SC_STRIDE`` целых в ``W_MIN``..65535; ``0 <= offset``, ``offset + len(records) <=
        SC_CAP`` (иначе ``ValueError`` без записи). Пишет ``& 0xFFFF``, по порядку, путём записи ``cmd()`` (ошибка
        транспорта помечает базы устаревшими и уходит наружу). ``_mailbox_lock`` не берёт. Константы буфера
        читаются из ``CONSTANTS`` в момент вызова.
        """
        self._upload(records, offset, lambda: False)

    def _upload(self, records: Sequence[Sequence[int]], offset: int, abort: Callable[[], bool]) -> bool:
        """``upload`` с проверкой ``abort()`` перед каждым блоком: ``True`` -> блок не пишется, возврат ``False``."""
        stride = CONSTANTS["SC_STRIDE"]
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError("offset: ожидается целое >= 0")
        if offset + len(records) > CONSTANTS["SC_CAP"]:
            raise ValueError("offset + число записей больше SC_CAP")
        flat: list[int] = []
        for i, record in enumerate(records):
            if len(record) != stride:
                raise ValueError(f"запись #{i}: число слов не равно SC_STRIDE")
            flat.extend(_encode_word(word, f"запись #{i}, слово #{j}") for j, word in enumerate(record))
        self._ensure_probed()
        base = CONSTANTS["SC_BASE"] + offset * stride
        chunk = CONSTANTS["WRITE_CHUNK"]
        for pos in range(0, len(flat), chunk):
            if abort():
                return False
            self._wr([("wm", base + pos, flat[pos : pos + chunk])])
        return True

    def run_chunks(
        self,
        scenario: Scenario,
        *,
        params: Mapping[str, float],
        on_progress: Callable[[int, int], None] | None = None,
    ) -> RunReport:
        """Исполнить сценарий кусками пинг-понгом по половинам буфера (protocol-spec §7.4).

        Кодирование (``wire_v2.encode_scenario`` с ``round_step`` конфига) и нарезка (``plan_chunks``, половина
        ``SC_CAP // 2``) — целиком до первой записи. Кусок k: метка стопа -> ``SC_RUN`` -> метка после ACK ->
        загрузка куска k+1 в другую половину -> ``wait_done``. ``on_progress(done, total)`` — при изменении числа
        пройденных записей (``TLM_SC_INDEX``) и ``(total, total)`` после последнего DONE. ``SC_RUN`` куска k+1 несёт
        состояние конца куска k (protocol-spec §7.4).

        Метка стопа: поколение стопа клиента сменилось или ``TLM_STOP_ACK`` отличается от прочитанного в начале
        (стоп другого клиента виден только на чтениях TLM — до загрузки и после ACK SC_RUN; внутри загрузки — только
        поколение, один блок FC16 может уже быть в полёте).

        Pre: на время ``run_chunks`` никаких ``done_seq``-``cmd()`` на этом клиенте (``wait_done`` держит один слот
        последней команды); второй ``run_chunks`` на том же клиенте -> ``RuntimeError``. Пульс (``kick_heartbeat``)
        — забота потока вызывающего. Post: все куски DONE -> ``RunReport``.
        Raises: ``CompileError`` (до записи); ``RobotAborted`` (стоп; к возврату робот остановлен: после метки
        после ACK — ``wait_done`` этого SC_RUN, после О5 в ``sc_run`` — опрос TLM до обрыва команды);
        ``RobotNak`` на SC_RUN (команда не начата; без стопа); любое другое исключение после первого SC_RUN —
        сначала ``stop(HARD)`` (его ошибка — заметка к исходному), затем исходное. Недоставленный стоп после метки
        уходит наружу своей ошибкой (транспорт, ``RobotTimeout("stop_echo")``), не ``RobotAborted``.
        """
        words = wire_v2.encode_scenario(scenario, params=params, round_step=self._cfg.round_step)
        half = CONSTANTS["SC_CAP"] // 2
        spans = wire_v2.plan_chunks([r.kind for r in scenario.records], half, scenario.step_of)
        if not spans:
            raise ValueError("сценарий пуст")
        chunks = tuple((start, count, 0 if k % 2 == 0 else half) for k, (start, count) in enumerate(spans))
        states = _chunk_start_states(words, chunks)
        with self._state_lock:
            if self._sc_active:
                raise RuntimeError("run_chunks уже идёт на этом клиенте")
            self._sc_active = True
        try:
            self._run_chunks(words, chunks, states, on_progress)
        finally:
            with self._state_lock:
                self._sc_active = False
        return RunReport(chunks, len(words))

    def _run_chunks(
        self,
        words: Sequence[Sequence[int]],
        chunks: Sequence[tuple[int, int, int]],
        states: Sequence[tuple[int, int, int]],
        on_progress: Callable[[int, int], None] | None,
    ) -> None:
        total = len(words)
        self._ensure_probed()
        g0 = self._stop_generation
        self._run_stop_base = g0
        ack0 = self._read_stop_ack()

        def by_generation() -> bool:
            return self._stop_generation != g0

        def marked() -> bool:
            """Метка стопа с одним чтением TLM_STOP_ACK."""
            return by_generation() or self._read_stop_ack() != ack0

        def records(k: int) -> Sequence[Sequence[int]]:
            start, count, _ = chunks[k]
            return words[start : start + count]

        self._upload(records(0), chunks[0][2], by_generation)  # прерванная загрузка — метка на шаге (1)
        progress = {"done": -1}
        seq = 0
        started = False
        try:
            for k, (start, count, offset) in enumerate(chunks):
                if marked():
                    raise RobotAborted(seq, ERR["E_ABORTED"], "стоп между кусками")
                started = True
                try:
                    seq = self.sc_run(count, k + 1, offset, *states[k]).seq
                except RobotAborted as o5:
                    # О5: клиент повторил стоп без ожидания эха — вернуть управление, когда робот остановился.
                    self._wait_robot_stopped(o5.seq)
                    raise
                if marked():
                    self._abort_after_ack(seq)
                upload_cut = False
                if k + 1 < len(chunks):
                    upload_cut = marked() or not self._upload(records(k + 1), chunks[k + 1][2], by_generation)

                def on_poll(tlm: Sequence[int], start: int = start) -> None:
                    done = start + int(tlm[_toff("TLM_SC_INDEX")])
                    if done != progress["done"]:
                        progress["done"] = done
                        if on_progress is not None:
                            on_progress(done, total)

                self.wait_done(seq, on_poll=on_poll)
                if upload_cut:
                    raise RobotAborted(seq, ERR["E_ABORTED"], "стоп во время загрузки")
            if progress["done"] != total and on_progress is not None:
                on_progress(total, total)
        except (RobotAborted, RobotNak):
            # RobotAborted — стоп уже прошёл; RobotNak бывает только на SC_RUN: команда не начата, HARD оборвал бы
            # чужой ход (E_BUSY).
            raise
        except BaseException as exc:
            if started:
                try:
                    self.stop(STOP_LEVEL["HARD"])
                except Exception as stop_exc:  # noqa: BLE001 — ошибка стопа не прячет исходную
                    exc.add_note(f"stop(HARD) после ошибки run_chunks не удался: {type(stop_exc).__name__}: {stop_exc}")
            raise

    def _read_stop_ack(self) -> int:
        """Одно чтение ``TLM_STOP_ACK`` (эхо учитывается, как на любом чтении TLM)."""
        ack = int(self._rd(REG["TLM_STOP_ACK"], 1)[0])
        self._note_echo(ack)
        return ack

    def _abort_after_ack(self, seq: int) -> None:
        """Метка стопа сразу после ACK SC_RUN: кусок уже принят — ``stop(HARD)``, ждать конца куска, ``RobotAborted``.

        Управление возвращается только после остановки робота: ``wait_done(seq)`` этого SC_RUN. ``RobotAborted`` из
        него — наружу; DONE — всё равно ``RobotAborted``; ``RobotTimeout("done")`` — наружу как есть. Ошибка самого
        стопа (транспорт, ``RobotTimeout("stop_echo")``) не прячется за ``RobotAborted``: уходит наружу с заметкой,
        внешний обработчик повторяет ``stop(HARD)``.
        """
        try:
            self.stop(STOP_LEVEL["HARD"])
        except Exception as stop_exc:
            stop_exc.add_note("метка стопа после ACK SC_RUN: кусок принят")
            raise
        self.wait_done(seq)  # RobotAborted — ожидаемый исход, уходит наружу как есть
        raise RobotAborted(seq, ERR["E_ABORTED"], "стоп между кусками")

    def _wait_robot_stopped(self, seq: int) -> None:
        """О5 внутри SC_RUN: стоп записан, эхо не ждалось — ждать, пока робот оборвёт или закончит команду ``seq``.

        Опрос блока TLM каждые ``poll_interval_s``: ``TLM_ERR_SEQ == seq`` с ``E_ABORTED`` или ``TLM_ACTIVITY`` в
        простое / ошибке -> возврат. Нет за ``done_timeout_s`` -> ``RobotTimeout("done", seq)`` с заметкой.
        """
        deadline = self._clock() + self._cfg.done_timeout_s
        while True:
            tlm = self._rd(_TLM_BASE, _TLM_COUNT)
            self._note_echo(int(tlm[_toff("TLM_STOP_ACK")]))
            aborted = int(tlm[_toff("TLM_ERR_SEQ")]) == seq and int(tlm[_toff("TLM_ERRNO_LAST")]) == ERR["E_ABORTED"]
            if aborted or int(tlm[_toff("TLM_ACTIVITY")]) in (_ACTIVITY_IDLE, _ACTIVITY_FAULT):
                return
            if self._clock() >= deadline:
                timeout = RobotTimeout("done", seq)
                timeout.add_note("О5 на SC_RUN: стоп записан, робот не остановился за done_timeout_s")
                raise timeout
            self._sleep(self._cfg.poll_interval_s)


def _kind_code(kind: str) -> int:
    code = KIND.get(kind)
    if code is None:
        raise ValueError(f"kind: неизвестный вид хода; допустимы: {', '.join(KIND)}")
    return code


def _chunk_start_states(
    words: Sequence[Sequence[int]], chunks: Sequence[tuple[int, int, int]]
) -> tuple[tuple[int, int, int], ...]:
    """Стартовое состояние каждого куска ``(spd_pct, accel, accur)`` — кодами провода (protocol-spec §7.4).

    Кусок 0 — нули. Кусок k > 0 — последние SPEED_PCT / ACCEL / ACCUR из записей ``0..end_{k-1}``
    (``accur`` — значение + 1, ноль на проводе — «не задано»); действие, которого не было, — 0.
    """
    states = []
    for k in range(len(chunks)):
        spd_pct = accel = accur = 0
        if k > 0:
            for word in words[0 : chunks[k][0]]:
                action, aparam = word[4] >> 8, word[5]
                if action == ACT["SPEED_PCT"]:
                    spd_pct = aparam
                elif action == ACT["ACCEL"]:
                    accel = aparam
                elif action == ACT["ACCUR"]:
                    accur = aparam + 1
        states.append((spd_pct, accel, accur))
    return tuple(states)


def _param_id(name: str) -> int:
    pid = PARAM_ID.get(name)
    if pid is None:
        raise ValueError("неизвестное имя параметра")
    return pid


def _geom_words(*values: float) -> list[int]:
    """Координаты в мм и ° -> целые шага провода (×``WIRE_SCALE``, половина от нуля) в ``W_MIN..W_MAX``."""
    scale = CONSTANTS["WIRE_SCALE"]
    out: list[int] = []
    for i, value in enumerate(values):
        x = float(value) * scale
        if not math.isfinite(x):
            raise ValueError(f"координата #{i}: ожидается конечное число")
        n = wire_v2._round_half_away(x)  # одно правило округления с кодировщиком сценария
        if not CONSTANTS["W_MIN"] <= n <= CONSTANTS["W_MAX"]:
            raise ValueError(f"координата #{i}: вне диапазона W_MIN..W_MAX")
        out.append(n)
    return out
