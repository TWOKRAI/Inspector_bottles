"""Журнал обмена драйвера робота с контроллером: что записал ПК, что он читал, длительность, ошибка.

Purpose:
    ``ExchangeLogTransport`` оборачивает транспорт робота (``RegisterTransport``) и пишет каждый обмен в
    ``ExchangeLog`` — кольцо читаемых строк плюс счётчики по операциям. Строки читают человек и агент и сверяют
    с журналом симулятора. Новый писатель на диск не заводится: каждая новая строка уходит в ``logger_module``
    (правило конфига ``Services.device_hub.drivers.exchange_log`` направляет её в свой файл).

    Стороны — с точки зрения робота: ``in`` — ПК -> робот (запись), ``out`` — робот -> ПК (чтение). Имена адресов
    берутся из карты ``protocol_v2.REG`` (блоки — ``REG_COUNT``), значение — сырое слово десятичным числом.

Public API:
    ``ExchangeLog(device_id, *, maxlen=2000, clock=time.perf_counter, enabled=True, periodic=False)``;
    ``get(since_seq=0, limit=200) -> dict``, ``set(enabled=None, periodic=None, clear=None) -> dict``;
    ``ExchangeLogTransport(inner, log)`` — те же ``is_connected`` / ``read_registers`` / ``transaction`` /
    ``connect`` / ``disconnect``, остальное чтение атрибутов уходит во внутренний транспорт.

    ``get`` / ``set`` возвращают ``{"enabled", "periodic", "lines", "last_seq", "dropped", "counters",
    "log_errors"}`` (у ``set`` ключа ``lines`` нет). Строка — ``{"seq", "t", "side", "text", "tag", "n", "ms"}``.

    ``get``: Pre — ``since_seq >= 0``, ``limit >= 1`` (иначе ``ValueError``).
    Post — строки с ``seq >= since_seq`` по возрастанию, не больше ``limit``;
    ``last_seq`` — ``seq`` последней отданной строки (без строк — последний выданный ``seq``);
    ``dropped`` — сколько строк с ``seq >= since_seq`` уже вытеснено из кольца. Читатель заменяет строку по
    ``seq``: у последней строки склейка может поднять ``n``.
    ``set``: Pre — ручка ``None`` не меняется. Post — возвращено новое состояние; ``clear=True`` очищает кольцо
    (``seq`` не сбрасывается), счётчики остаются.

Stability: lite

Потоки. Транспорт зовут тик, поток поводка, исполнитель программ, команды плагина, ``disconnect``. Замок журнала
держится только на ``seq`` / ``t`` / склейку / счётчики; вызов транспорта, форматирование строки и вызов логгера
идут вне замка. Выключенный журнал стоит один флаг: ни часов, ни форматирования, ни счётчиков, ни записи.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable, Sequence
from typing import Any

from multiprocess_framework.modules.logger_module import get_std_logger
from Services.robot_comm.core.protocol_v2 import ERR_TEXT, OP, REG, REG_COUNT

__all__ = [
    "TEXT_BAD_CONFIG",
    "TEXT_BAD_GET_ARGS",
    "TEXT_BAD_KNOBS",
    "ExchangeLog",
    "ExchangeLogTransport",
]

# Постоянные тексты отказов (R8: без входных значений); их отдают операции драйвера
TEXT_BAD_KNOBS = "журнал обмена: ручки enabled, periodic и clear принимают только true или false"
TEXT_BAD_GET_ARGS = "exchange_log_get: since_seq и limit — целые числа, since_seq >= 0, limit >= 1"
TEXT_BAD_CONFIG = "журнал обмена: params.exchange_log — таблица enabled/periodic (bool), взяты умолчания"

# --- Карта адресов и операций ------------------------------------------------------------------------------

#: Адрес -> имя. Блок из ``REG_COUNT`` раскрыт по словам: ``CMD_ARGS[0]`` .. ``CMD_ARGS[11]``.
_ADDR_NAME: dict[int, str] = {}
for _name, _addr in REG.items():
    if _name in REG_COUNT:
        for _k in range(REG_COUNT[_name]):
            _ADDR_NAME.setdefault(_addr + _k, f"{_name}[{_k}]")
    else:
        _ADDR_NAME.setdefault(_addr, _name)

#: Код операции -> имя (коды в ``OP`` уникальны; ``E_VFD_LINK = 16`` — код ошибки из ``ERR``, не операция).
_OP_NAME: dict[int, str] = {}
for _name, _code in OP.items():
    _OP_NAME.setdefault(_code, _name)

_CMD_FLAG = REG["CMD_FLAG"]
_CMD_OPCODE = REG["CMD_OPCODE"]
_STOP_REQ = REG["STOP_REQ"]
_HB_PC = REG["HB_PC"]
_JOG_LEASE = REG["JOG_LEASE"]
_RES_SEQ = REG["RES_SEQ"]
_RES_LEN = 3  # RES_SEQ, RES_STATUS, RES_ERRNO

#: Блоки, которые пишутся одной строкой на вызов (DESIGN п.3).
_BLOCK_NAMES = ("SC_BUF", "PMIR")

#: Тег строки по адресу записи.
_TAG_BY_ADDR = {_CMD_FLAG: "cmd", _STOP_REQ: "stop", _HB_PC: "hb", _JOG_LEASE: "hb"}
#: Записи периодического трафика: при ``periodic=False`` строк нет, счётчики считаются.
_PERIODIC_ADDRS = frozenset({_HB_PC, _JOG_LEASE})

# Вид записи по правилу ``periodic``: всегда / только при periodic / тройка RES
_ALWAYS = 0
_PERIODIC = 1
_RES = 2

_MAX_ERR_TEXT = 200  # длина сообщения исключения в строке err

type _Entry = tuple[str, str, str, int, Any]  # (side, text, tag, вид, extra)


def _addr_name(address: int) -> str:
    """Имя адреса из карты v2; вне карты — ``0x1234``."""
    name = _ADDR_NAME.get(address)
    return name if name is not None else f"0x{address:04X}"


def _op_label(code: Any) -> str:
    return _OP_NAME.get(code, str(code)) if isinstance(code, int) else str(code)


def _err_text(prefix: str, exc: BaseException | None) -> str:
    """Текст строки err: контекст вызова, тип и сообщение исключения (или отказ ``transaction``)."""
    if exc is None:
        return f"ERR {prefix}: transaction вернул False"
    return f"ERR {prefix}: {type(exc).__name__}: {str(exc)[:_MAX_ERR_TEXT]}"


# --- Строки ------------------------------------------------------------------------------------------------


def _write_word(address: int, value: Any) -> _Entry:
    name = _addr_name(address)
    suffix = f" ({_op_label(value)})" if address == _CMD_OPCODE else ""
    kind = _PERIODIC if address in _PERIODIC_ADDRS else _ALWAYS
    return ("in", f"{name} = {value}{suffix}", _TAG_BY_ADDR.get(address, ""), kind, None)


def _tx_entries(ops: Sequence[tuple], failed: bool, exc: BaseException | None) -> list[_Entry]:
    """Строки одной транзакции: по строке на слово (``W`` / ``W*``), блоки ``SC_BUF`` / ``PMIR`` — одна строка."""
    entries: list[_Entry] = []
    for kind, address, value in ops:
        if kind == "w":
            side, text, tag, vis, extra = _write_word(address, value)
            entries.append((side, f"W {text}", tag, vis, extra))
            continue
        first = _addr_name(address)
        if first.partition("[")[0] in _BLOCK_NAMES:
            start = int(first[first.index("[") + 1 : -1])
            entries.append(
                (
                    "in",
                    f"W* {first.partition('[')[0]}[{start}..{start + len(value) - 1}] ({len(value)} слов)",
                    "",
                    _ALWAYS,
                    None,
                )
            )
            continue
        for i, word in enumerate(value):
            side, text, tag, vis, extra = _write_word(address + i, word)
            entries.append((side, f"W* {text}", tag, vis, extra))
    if failed:
        first_text = entries[0][1] if entries else "W"
        entries.append(("in", _err_text(first_text.partition(" =")[0], exc), "err", _ALWAYS, None))
    return entries


def _read_entries(address: int, count: int, values: Any, exc: BaseException | None, failed: bool) -> list[_Entry]:
    """Строки одного чтения: ``R <ИМЯ>..+<count>``; чтение RES целиком — строка ``res`` с тройкой."""
    head = f"R {_addr_name(address)}..+{count}"
    entries: list[_Entry] = []
    offset = _RES_SEQ - address
    if (
        not failed
        and 0 <= offset
        and offset + _RES_LEN <= count
        and values is not None
        and len(values) >= offset + _RES_LEN
    ):
        seq, status, errno = (int(v) for v in values[offset : offset + _RES_LEN])
        err_text = ERR_TEXT.get(errno, "код неизвестен")
        res_text = f"{head} RES_SEQ = {seq}, RES_STATUS = {status}, RES_ERRNO = {errno} ({err_text})"
        entries.append(("out", res_text, "res", _RES, ((seq, status, errno), head)))
    else:
        entries.append(("out", head, "", _PERIODIC, None))
    if failed:
        entries.append(("out", _err_text(head, exc), "err", _ALWAYS, None))
    return entries


def _tx_op_name(ops: Sequence[tuple]) -> str | None:
    """Имя операции для счётчиков: ``cmd <OP>`` при записи ``CMD_OPCODE``, иначе ``write <первый адрес>``."""
    if not ops:
        return None
    for kind, address, value in ops:
        if kind == "w" and address == _CMD_OPCODE:
            return f"cmd {_op_label(value)}"
        if kind == "wm" and address <= _CMD_OPCODE < address + len(value):
            return f"cmd {_op_label(value[_CMD_OPCODE - address])}"
    return f"write {_addr_name(ops[0][1])}"


def _link_entries(text: str, err_prefix: str, exc: BaseException | None) -> list[_Entry]:
    """Строка ``link`` (connect ok / connect fail / disconnect); при исключении — следом строка ``err``."""
    entries: list[_Entry] = [("", text, "link", _ALWAYS, None)]
    if exc is not None:
        entries.append(("", _err_text(err_prefix, exc), "err", _ALWAYS, None))
    return entries


# --- Журнал ------------------------------------------------------------------------------------------------


class ExchangeLog:
    """Кольцо строк обмена и счётчики по операциям; потокобезопасно (см. docstring модуля)."""

    def __init__(
        self,
        device_id: str,
        *,
        maxlen: int = 2000,
        clock: Callable[[], float] = time.perf_counter,
        enabled: bool = True,
        periodic: bool = False,
    ) -> None:
        if not isinstance(enabled, bool) or not isinstance(periodic, bool):
            raise ValueError(TEXT_BAD_KNOBS)
        self._clock = clock
        self._enabled = enabled
        self._periodic = periodic
        self._lock = threading.Lock()
        self._ring: deque[dict[str, Any]] = deque(maxlen=maxlen)
        self._seq = 0  # последний выданный seq
        self._floor = 0  # seq, по который кольцо очищено вручную (не считается вытеснением)
        self._tail: dict[str, Any] | None = None  # последняя строка: цель склейки
        self._last_res: tuple[int, int, int] | None = None
        self._counters: dict[str, list[float]] = {}  # op -> [count, errors, ms_last, ms_max, ms_sum]
        self._log_errors = 0
        self._warned = False
        self._logger = get_std_logger(f"{__name__}.{device_id}")

    # --- публичный API ---

    def get(self, since_seq: int = 0, limit: int = 200) -> dict[str, Any]:
        """Строки с ``seq >= since_seq`` по возрастанию (не больше ``limit``) и состояние журнала.

        Raises:
            ValueError: ``limit < 1``.
        """
        if limit < 1:
            raise ValueError(TEXT_BAD_GET_ARGS)
        with self._lock:
            lines: list[dict[str, Any]] = []
            for line in self._ring:
                if line["seq"] >= since_seq:
                    if len(lines) >= limit:
                        break
                    lines.append(dict(line))
            state = self._state_locked(since_seq)
            state["lines"] = lines
            state["last_seq"] = lines[-1]["seq"] if lines else self._seq
            return state

    def set(
        self, enabled: bool | None = None, periodic: bool | None = None, clear: bool | None = None
    ) -> dict[str, Any]:
        """Применить ручки (``None`` — не менять) и вернуть состояние без ``lines``.

        Raises:
            ValueError: ручка не ``bool`` и не ``None`` (строка ``"false"`` не приводится); ничего не изменено.
        """
        if any(v is not None and not isinstance(v, bool) for v in (enabled, periodic, clear)):
            raise ValueError(TEXT_BAD_KNOBS)
        with self._lock:
            tail_msg = None
            if clear:
                tail_msg = self._close_tail_locked()
                self._floor = self._seq
                self._ring.clear()
                self._last_res = None
            if enabled is not None:
                if self._enabled and not enabled:
                    tail_msg = tail_msg or self._close_tail_locked()
                self._enabled = enabled
            if periodic is not None:
                self._periodic = periodic
            state = self._state_locked(0)
        self._emit([tail_msg] if tail_msg else [])
        return state

    # --- состояние ---

    def _state_locked(self, since_seq: int) -> dict[str, Any]:
        oldest = self._ring[0]["seq"] if self._ring else self._seq + 1
        dropped = max(0, oldest - max(since_seq, self._floor + 1, 1))
        counters = {
            op: {
                "count": int(c[0]),
                "errors": int(c[1]),
                "ms_last": round(c[2], 3),
                "ms_max": round(c[3], 3),
                "ms_avg": round(c[4] / c[0], 3) if c[0] else 0.0,
            }
            for op, c in self._counters.items()
        }
        return {
            "enabled": self._enabled,
            "periodic": self._periodic,
            "last_seq": self._seq,
            "dropped": dropped,
            "counters": counters,
            "log_errors": self._log_errors,
        }

    def _close_tail_locked(self) -> str | None:
        """Закрыть склейку: запись ``#<seq> … ×<n>`` для хвоста с ``n > 1`` (отдаётся вызывающему для логгера)."""
        tail, self._tail = self._tail, None
        if tail is not None and tail["n"] > 1:
            return f"#{tail['seq']} … ×{tail['n']}"
        return None

    # --- запись (зовёт ExchangeLogTransport) ---

    def _record(self, op: str | None, ms: float, failed: bool, build: Callable[..., list[_Entry]], *args: Any) -> None:
        """Счётчики и строки одного вызова транспорта. Не бросает: сбой журнала -> ``log_errors``."""
        try:
            try:
                entries = build(*args)
            except Exception as exc:  # форматирование не ломает обмен; счётчики всё равно считаются
                entries = []
                self._note_failure(exc)
            msgs: list[str] = []
            with self._lock:
                if not self._enabled:  # вызов начался до set(enabled=False): не пишем и не считаем
                    return
                if op is not None:
                    self._count_locked(op, ms, failed)
                if entries:
                    self._append_locked(entries, ms, msgs)
            self._emit(msgs)
        except Exception as exc:  # noqa: BLE001 — журнал никогда не роняет обмен
            self._note_failure(exc)

    def _count_locked(self, op: str, ms: float, failed: bool) -> None:
        c = self._counters.get(op)
        if c is None:
            c = self._counters[op] = [0, 0, 0.0, 0.0, 0.0]
        c[0] += 1
        if failed:
            c[1] += 1
        c[2] = ms
        if ms > c[3]:
            c[3] = ms
        c[4] += ms

    def _append_locked(self, entries: list[_Entry], ms: float, msgs: list[str]) -> None:
        t: float | None = None
        periodic = self._periodic
        for side, text, tag, kind, extra in entries:
            if kind == _RES:
                triple, plain = extra
                if triple != self._last_res:
                    self._last_res = triple
                elif periodic:
                    text, tag = plain, ""
                else:
                    continue
            elif kind == _PERIODIC and not periodic:
                continue
            tail = self._tail
            if tail is not None and tail["side"] == side and tail["text"] == text:
                tail["n"] += 1
                if t is None:
                    t = self._clock()
                tail["t"] = t
                tail["ms"] = ms
                continue
            closed = self._close_tail_locked()
            if closed:
                msgs.append(closed)
            if t is None:
                t = self._clock()  # второе чтение часов — под замком, вместе с выдачей seq: t монотонен по seq
            self._seq += 1
            line = {"seq": self._seq, "t": t, "side": side, "text": text, "tag": tag, "n": 1, "ms": ms}
            self._ring.append(line)
            self._tail = line
            msgs.append(f"#{self._seq} {side} {text}")

    def _emit(self, msgs: list[str]) -> None:
        """Записи в ``logger_module`` — вне замка журнала (запись синхронная, приёмник может быть медленным)."""
        for msg in msgs:
            try:
                self._logger.info(msg)
            except Exception as exc:  # noqa: BLE001 — сбой логгера не ломает обмен
                self._note_failure(exc)

    def _note_failure(self, exc: BaseException) -> None:
        """Сбой самого журнала: ``log_errors += 1``, предупреждение один раз за жизнь журнала."""
        with self._lock:
            self._log_errors += 1
            first = not self._warned
            self._warned = True
        if first:
            try:
                self._logger.warning(f"журнал обмена: сбой {type(exc).__name__}: {exc}")
            except Exception:  # noqa: BLE001, S110 — предупреждение о сбое журнала не должно падать само
                pass


# --- Обёртка транспорта ------------------------------------------------------------------------------------


class ExchangeLogTransport:
    """Обёртка ``RegisterTransport``: каждый обмен — в ``ExchangeLog``, результат и исключения — как у внутреннего.

    Явно: ``is_connected``, ``read_registers``, ``transaction``, ``connect``, ``disconnect``. Чтение прочих
    атрибутов (``get_status``, ``state``, ``config``) уходит внутреннему транспорту. ``write_register(s)`` и
    ``read_holding`` идут мимо журнала. ``__slots__`` и ``__setattr__`` нет: тесты подменяют ``transaction``
    атрибутом экземпляра.
    """

    def __init__(self, inner: Any, log: ExchangeLog) -> None:
        self._inner = inner
        self._log = log

    def __getattr__(self, name: str) -> Any:
        # Зовётся только если обычный поиск не нашёл имя. ``_``-имена (в том числе ``_inner`` до установки) — нет.
        if name.startswith("_"):
            raise AttributeError(name)
        return getattr(self._inner, name)

    @property
    def is_connected(self) -> bool:
        return self._inner.is_connected

    def read_registers(self, address: int, count: int = 1) -> list[int]:
        log = self._log
        if not log._enabled:
            return self._inner.read_registers(address, count)
        clock = log._clock
        start = clock()
        op = f"read {_addr_name(address)}"
        try:
            values = self._inner.read_registers(address, count)
        except BaseException as exc:
            log._record(op, (clock() - start) * 1000.0, True, _read_entries, address, count, None, exc, True)
            raise
        log._record(op, (clock() - start) * 1000.0, False, _read_entries, address, count, values, None, False)
        return values

    def transaction(self, ops: list[tuple]) -> bool:
        log = self._log
        if not log._enabled:
            return self._inner.transaction(ops)
        clock = log._clock
        start = clock()
        try:
            ok = self._inner.transaction(ops)
        except BaseException as exc:
            log._record(_tx_op_name(ops), (clock() - start) * 1000.0, True, _tx_entries, ops, True, exc)
            raise
        failed = ok is False
        log._record(_tx_op_name(ops), (clock() - start) * 1000.0, failed, _tx_entries, ops, failed, None)
        return ok

    def connect(self) -> bool:
        log = self._log
        if not log._enabled:
            return self._inner.connect()
        clock = log._clock
        start = clock()
        try:
            ok = self._inner.connect()
        except BaseException as exc:
            log._record(None, (clock() - start) * 1000.0, True, _link_entries, "connect fail", "connect", exc)
            raise
        log._record(
            None, (clock() - start) * 1000.0, False, _link_entries, "connect ok" if ok else "connect fail", "", None
        )
        return ok

    def disconnect(self) -> None:
        log = self._log
        if not log._enabled:
            self._inner.disconnect()
            return
        clock = log._clock
        start = clock()
        try:
            self._inner.disconnect()
        except BaseException as exc:
            log._record(None, (clock() - start) * 1000.0, True, _link_entries, "disconnect", "disconnect", exc)
            raise
        log._record(None, (clock() - start) * 1000.0, False, _link_entries, "disconnect", "", None)
