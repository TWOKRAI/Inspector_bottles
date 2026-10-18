"""Слепая приёмка T5.6: журнал обмена драйвера робота (A1–A12), написана ДО реализации.

Источник истины — ``plans/robot-protocol-v2/tasks/T5.6.md`` (Module contract, Acceptance criteria,
строка и имена из DESIGN). Ожидаемые значения — литералы из спецификации и карты ``protocol_v2``.

Уровни:
    (а) ``ExchangeLog`` + ``ExchangeLogTransport`` поверх фейкового ``RegisterTransport`` (A2–A7, A10, A11);
    (б) ``RobotDriverV2`` на настоящем sim v2 через ``E2eRig`` (A1, A8, A12);
    (в) команды плагина ``robot_exchange_log_get`` / ``robot_exchange_log_set`` (A9).

Модуль ``exchange_log`` импортируется внутри фикстуры: каждый тест падает отдельно (ImportError),
число собранных тестов видно. Всё, что может блокироваться, идёт в daemon-потоке с дедлайном.

Допущения формы (спецификация их не фиксирует, проверяются как есть):
    * строка журнала — ``dict`` с ключами ``seq``, ``side``, ``text``, ``tag``, ``n``;
    * ``counters`` — ``dict``: имя операции (``"read TLM_PROTO_VER"``) -> ``dict`` с ``count`` / ``errors``;
    * ответ ``call(...)`` / команды плагина — ``status: ok`` плюс данные журнала: допустимы и плоские ключи,
      и один вложенный ``dict`` с ключом ``lines`` / ``enabled`` (см. ``_payload``).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from Services.robot_comm.core.registers import ROBOT_UNIT_ID
from Services.robot_comm.tests.e2e_rig_v2 import E2eRig, bounded, free_port

_LOGGER_NAME = "mpf.Services.device_hub.drivers.exchange_log.rv2"
_CALL_DEADLINE_S = 15.0
_CONNECT_DEADLINE_S = 60.0
_THREAD_DEADLINE_S = 30.0

# Адреса карты v2 (литералы из protocol_v2.REG)
_CMD_FLAG = 0x1000
_CMD_SEQ = 0x1001
_RES_SEQ = 0x1010
_HB_PC = 0x1020
_STOP_REQ = 0x1021
_JOG_LEASE = 0x1022
_TLM_PROTO_VER = 0x1040
_SC_BUF = 0x1400
_UNKNOWN = 0x1234  # вне карты


# --------------------------------------------------------------------------------------------------
# Фейковый RegisterTransport (только этот файл)
# --------------------------------------------------------------------------------------------------


class FakeTransport:
    """Фейк ``RegisterTransport``: пишет вызовы, отвечает нулями или заданным ответом."""

    def __init__(self) -> None:
        self.connected = True
        self.connect_result = True
        self.read_calls: list[tuple[int, int]] = []
        self.tx_calls: list[list[tuple]] = []
        self.responses: dict[int, list[int]] = {}
        self.read_exc: BaseException | None = None
        self.tx_exc: BaseException | None = None
        self.tx_result = True
        self.disconnect_calls = 0

    @property
    def is_connected(self) -> bool:
        return self.connected

    def read_registers(self, address: int, count: int = 1) -> list[int]:
        self.read_calls.append((address, count))
        if self.read_exc is not None:
            raise self.read_exc
        return list(self.responses.get(address, [0] * count))

    def transaction(self, ops: list[tuple]) -> bool:
        self.tx_calls.append(list(ops))
        if self.tx_exc is not None:
            raise self.tx_exc
        return self.tx_result

    def connect(self) -> bool:
        self.connected = self.connect_result
        return self.connect_result

    def disconnect(self) -> None:
        self.disconnect_calls += 1
        self.connected = False

    def get_status(self) -> dict[str, Any]:
        return {"connected_since": 123.5, "marker": "fake"}


# --------------------------------------------------------------------------------------------------
# Фикстуры и помощники уровня (а)
# --------------------------------------------------------------------------------------------------


@pytest.fixture
def exchange_log_mod() -> Any:
    """Модуль под тестом; ImportError до реализации — красный в каждом тесте."""
    from Services.device_hub.drivers import exchange_log

    return exchange_log


@pytest.fixture
def make(exchange_log_mod: Any):
    """Фабрика ``(log, tr, fake)`` для журнала поверх фейка."""

    def _make(
        *,
        periodic: bool = False,
        enabled: bool = True,
        maxlen: int = 2000,
        device_id: str = "rv2",
    ) -> SimpleNamespace:
        fake = FakeTransport()
        log = exchange_log_mod.ExchangeLog(device_id, maxlen=maxlen, enabled=enabled, periodic=periodic)
        tr = exchange_log_mod.ExchangeLogTransport(fake, log)
        return SimpleNamespace(log=log, tr=tr, fake=fake)

    return _make


def _lines(log: Any, since_seq: int = 0) -> list[dict]:
    return log.get(since_seq=since_seq, limit=5000)["lines"]


def _texts(log: Any) -> list[str]:
    return [ln["text"] for ln in _lines(log)]


def _counter(log: Any, name: str) -> dict:
    return log.get()["counters"][name]


# --------------------------------------------------------------------------------------------------
# A2: транзакция CMD
# --------------------------------------------------------------------------------------------------

_A2_OPS = [("wm", 0x1001, [5, 16, 0]), ("w", 0x1000, 1)]


def test_a2_opcode_line_carries_op_name(make: Any) -> None:
    """A2: ``wm`` на 0x1001 даёт строку ``W* CMD_OPCODE = 16 (PTP_MOVE)``."""
    r = make()
    r.tr.transaction(list(_A2_OPS))
    assert "W* CMD_OPCODE = 16 (PTP_MOVE)" in _texts(r.log)


def test_a2_flag_line_has_tag_cmd(make: Any) -> None:
    """A2: запись ``CMD_FLAG`` даёт строку ``W CMD_FLAG = 1`` с ``tag == "cmd"``."""
    r = make()
    r.tr.transaction(list(_A2_OPS))
    flag = [ln for ln in _lines(r.log) if ln["text"] == "W CMD_FLAG = 1"]
    assert len(flag) == 1
    assert flag[0]["tag"] == "cmd"


def test_a2_counter_cmd_ptp_move_count_is_1(make: Any) -> None:
    """A2: операция ``cmd PTP_MOVE`` имеет ``count == 1``."""
    r = make()
    r.tr.transaction(list(_A2_OPS))
    assert _counter(r.log, "cmd PTP_MOVE")["count"] == 1


def test_a2_wm_gives_one_line_per_word_in_order(make: Any) -> None:
    """A2 (DESIGN п.3): ``wm`` -> строка ``W*`` на каждое слово, затем ``W CMD_FLAG``; адреса по карте."""
    r = make()
    r.tr.transaction(list(_A2_OPS))
    assert _texts(r.log) == [
        "W* CMD_SEQ = 5",
        "W* CMD_OPCODE = 16 (PTP_MOVE)",
        "W* CMD_ARGC = 0",
        "W CMD_FLAG = 1",
    ]


def test_a2_transaction_passes_ops_and_result_through(make: Any) -> None:
    """A2: обёртка отдаёт транспорту те же ops и возвращает его результат."""
    r = make()
    r.fake.tx_result = False
    assert r.tr.transaction(list(_A2_OPS)) is False
    assert r.fake.tx_calls == [_A2_OPS]


def test_read_passes_values_through(make: Any) -> None:
    """Контракт: ``read_registers`` возвращает то, что вернул внутренний транспорт."""
    r = make()
    r.fake.responses[_TLM_PROTO_VER] = [2, 7, 9]
    assert r.tr.read_registers(_TLM_PROTO_VER, 3) == [2, 7, 9]
    assert r.fake.read_calls == [(_TLM_PROTO_VER, 3)]


# --------------------------------------------------------------------------------------------------
# Формат строки (DESIGN п.3): стороны, имена, блоки, теги
# --------------------------------------------------------------------------------------------------


def test_format_write_line_side_in_read_line_side_out(make: Any) -> None:
    """DESIGN п.3: запись — ``side == "in"``, чтение — ``side == "out"``."""
    r = make(periodic=True)
    r.tr.transaction([("w", _CMD_SEQ, 4)])
    r.tr.read_registers(_TLM_PROTO_VER, 32)
    assert [(ln["side"], ln["text"]) for ln in _lines(r.log)] == [
        ("in", "W CMD_SEQ = 4"),
        ("out", "R TLM_PROTO_VER..+32"),
    ]


def test_format_block_write_to_sc_buf_is_single_line(make: Any) -> None:
    """DESIGN п.3: блок ``SC_BUF`` — одна строка на вызов, а не на слово."""
    r = make()
    r.tr.transaction([("wm", _SC_BUF, list(range(30)))])
    assert _texts(r.log) == ["W* SC_BUF[0..29] (30 слов)"]


def test_format_address_outside_map_is_hex(make: Any) -> None:
    """DESIGN п.3: адрес вне карты пишется как ``0x1234``."""
    r = make()
    r.tr.transaction([("w", _UNKNOWN, 7)])
    assert _texts(r.log) == ["W 0x1234 = 7"]


def test_format_heartbeat_and_lease_have_tag_hb(make: Any) -> None:
    """DESIGN п.3: запись ``HB_PC`` и ``JOG_LEASE`` — ``tag == "hb"`` (при ``periodic=True`` строки есть)."""
    r = make(periodic=True)
    r.tr.transaction([("w", _HB_PC, 7)])
    r.tr.transaction([("w", _JOG_LEASE, 8)])
    assert [(ln["text"], ln["tag"]) for ln in _lines(r.log)] == [("W HB_PC = 7", "hb"), ("W JOG_LEASE = 8", "hb")]


def test_format_line_has_non_negative_duration(make: Any) -> None:
    """DESIGN п.3: у строки есть поле ``ms`` — неотрицательное число."""
    r = make(periodic=True)
    r.tr.read_registers(_TLM_PROTO_VER, 32)
    ms = _lines(r.log)[0]["ms"]
    assert isinstance(ms, (int, float))
    assert ms >= 0


# --------------------------------------------------------------------------------------------------
# A3: склейка
# --------------------------------------------------------------------------------------------------


def test_a3_five_reads_merge_into_one_line_with_n5(make: Any) -> None:
    """A3: пять ``read_registers(0x1040, 32)`` подряд -> одна строка ``R TLM_PROTO_VER..+32``, ``n == 5``."""
    r = make(periodic=True)
    for _ in range(5):
        r.tr.read_registers(_TLM_PROTO_VER, 32)
    lines = _lines(r.log)
    assert [ln["text"] for ln in lines] == ["R TLM_PROTO_VER..+32"]
    assert lines[0]["n"] == 5


def test_a3_other_line_between_reads_breaks_merge(make: Any) -> None:
    """A3: чтения, между которыми есть другая строка, не склеиваются."""
    r = make(periodic=True)
    r.tr.read_registers(_TLM_PROTO_VER, 32)
    r.tr.transaction([("w", _CMD_SEQ, 1)])
    r.tr.read_registers(_TLM_PROTO_VER, 32)
    lines = _lines(r.log)
    assert [(ln["text"], ln["n"]) for ln in lines] == [
        ("R TLM_PROTO_VER..+32", 1),
        ("W CMD_SEQ = 1", 1),
        ("R TLM_PROTO_VER..+32", 1),
    ]


# --------------------------------------------------------------------------------------------------
# A4: ошибка транспорта
# --------------------------------------------------------------------------------------------------


def test_a4_caller_catches_same_exception_object(make: Any) -> None:
    """A4: вызывающий ловит тот же объект исключения (``is``)."""
    r = make()
    original = ConnectionError("x")
    r.fake.read_exc = original
    caught: list[BaseException] = []
    try:
        r.tr.read_registers(_TLM_PROTO_VER, 32)
    except ConnectionError as exc:
        caught.append(exc)
    assert len(caught) == 1
    assert caught[0] is original


def test_a4_error_line_has_tag_err_and_exception_type(make: Any) -> None:
    """A4: в журнале строка ``tag == "err"``, в тексте есть ``ConnectionError`` (при ``periodic=False``)."""
    r = make()
    r.fake.read_exc = ConnectionError("x")
    with pytest.raises(ConnectionError):
        r.tr.read_registers(_TLM_PROTO_VER, 32)
    errs = [ln for ln in _lines(r.log) if ln["tag"] == "err"]
    assert len(errs) == 1
    assert "ConnectionError" in errs[0]["text"]


def test_a4_counter_read_tlm_proto_ver_errors_is_1(make: Any) -> None:
    """A4: ``read TLM_PROTO_VER.errors == 1``."""
    r = make()
    r.fake.read_exc = ConnectionError("x")
    with pytest.raises(ConnectionError):
        r.tr.read_registers(_TLM_PROTO_VER, 32)
    assert _counter(r.log, "read TLM_PROTO_VER")["errors"] == 1


def test_a4_transaction_returning_false_gives_err_line(make: Any) -> None:
    """A4 (DESIGN п.3): ``transaction`` вернул ``False`` -> строка ``tag == "err"``; результат не подменяется."""
    r = make()
    r.fake.tx_result = False
    assert r.tr.transaction([("w", _CMD_SEQ, 1)]) is False
    assert [ln["tag"] for ln in _lines(r.log) if ln["tag"] == "err"] == ["err"]


# --------------------------------------------------------------------------------------------------
# A5: enabled
# --------------------------------------------------------------------------------------------------


def _exchange_burst(r: SimpleNamespace) -> None:
    r.tr.read_registers(_TLM_PROTO_VER, 32)
    r.tr.transaction([("w", _HB_PC, 3)])
    r.tr.transaction([("wm", 0x1001, [5, 16, 0]), ("w", _CMD_FLAG, 1)])


def test_a5_disabled_adds_no_lines(make: Any) -> None:
    """A5: при ``set(enabled=False)`` обмен не добавляет строк."""
    r = make(periodic=True)
    r.tr.transaction([("w", _CMD_SEQ, 1)])
    before = r.log.get()
    r.log.set(enabled=False)
    _exchange_burst(r)
    after = r.log.get()
    assert after["lines"] == before["lines"]
    assert after["last_seq"] == before["last_seq"] == 1


def test_a5_disabled_does_not_change_counters(make: Any) -> None:
    """A5: при ``set(enabled=False)`` счётчики не меняются."""
    r = make(periodic=True)
    r.tr.transaction([("w", _CMD_SEQ, 1)])
    before = r.log.get()["counters"]
    r.log.set(enabled=False)
    _exchange_burst(r)
    assert r.log.get()["counters"] == before


def test_a5_disabled_still_forwards_calls_to_inner_transport(make: Any) -> None:
    """A5: выключенный журнал не мешает обмену: транспорт получает вызовы, результат возвращается."""
    r = make()
    r.log.set(enabled=False)
    r.fake.responses[_TLM_PROTO_VER] = [9] * 4
    assert r.tr.read_registers(_TLM_PROTO_VER, 4) == [9, 9, 9, 9]
    assert r.tr.transaction([("w", _CMD_FLAG, 1)]) is True
    assert r.fake.read_calls == [(_TLM_PROTO_VER, 4)]
    assert r.fake.tx_calls == [[("w", _CMD_FLAG, 1)]]


def test_a5_reenabled_log_writes_again(make: Any) -> None:
    """A5: после ``set(enabled=True)`` журнал снова пишет."""
    r = make(periodic=True)
    r.log.set(enabled=False)
    r.tr.transaction([("w", _CMD_SEQ, 1)])
    assert _lines(r.log) == []
    r.log.set(enabled=True)
    r.tr.transaction([("w", _CMD_SEQ, 2)])
    assert _texts(r.log) == ["W CMD_SEQ = 2"]


def test_a5_set_returns_state_without_lines(make: Any) -> None:
    """Контракт ``set``: состояние в виде ``get``, но без ключа ``lines``; ручки применены."""
    r = make()
    state = r.log.set(enabled=False, periodic=True)
    assert "lines" not in state
    assert state["enabled"] is False
    assert state["periodic"] is True
    for key in ("last_seq", "dropped", "counters", "log_errors"):
        assert key in state


def test_a5_set_without_args_leaves_knobs_untouched(make: Any) -> None:
    """Контракт ``set``: ``None`` у ручки — не менять."""
    r = make(periodic=True, enabled=True)
    state = r.log.set()
    assert (state["enabled"], state["periodic"]) == (True, True)


def test_set_clear_empties_the_lines(make: Any) -> None:
    """Контракт ``set(clear=True)``: строки удалены, дальше журнал пишет."""
    r = make()
    r.tr.transaction([("w", _CMD_SEQ, 1)])
    r.log.set(clear=True)
    assert _lines(r.log) == []
    r.tr.transaction([("w", _CMD_SEQ, 2)])
    assert _texts(r.log) == ["W CMD_SEQ = 2"]


# --------------------------------------------------------------------------------------------------
# A6: periodic=False
# --------------------------------------------------------------------------------------------------


def test_a6_periodic_off_read_and_heartbeat_give_no_lines(make: Any) -> None:
    """A6: ``periodic=False``: чтение 0x1040×32 и запись ``HB_PC`` строк не дают."""
    r = make(periodic=False)
    r.tr.read_registers(_TLM_PROTO_VER, 32)
    r.tr.transaction([("w", _HB_PC, 7)])
    assert _lines(r.log) == []


def test_a6_periodic_off_stop_write_gives_tag_stop(make: Any) -> None:
    """A6: запись ``STOP_REQ`` даёт строку с ``tag == "stop"``."""
    r = make(periodic=False)
    r.tr.transaction([("w", _STOP_REQ, 1)])
    lines = _lines(r.log)
    assert len(lines) == 1
    assert lines[0]["tag"] == "stop"


def test_a6_periodic_off_read_counter_still_counts(make: Any) -> None:
    """A6: счётчик ``read TLM_PROTO_VER`` равен 1 при ``periodic=False``."""
    r = make(periodic=False)
    r.tr.read_registers(_TLM_PROTO_VER, 32)
    assert _counter(r.log, "read TLM_PROTO_VER")["count"] == 1


def test_a6_periodic_off_heartbeat_counter_still_counts(make: Any) -> None:
    """A6: счётчик ``write HB_PC`` равен 1 при ``periodic=False``."""
    r = make(periodic=False)
    r.tr.transaction([("w", _HB_PC, 7)])
    assert _counter(r.log, "write HB_PC")["count"] == 1


def test_a6_periodic_off_jog_lease_gives_no_lines(make: Any) -> None:
    """A6 (DESIGN п.4): ``JOG_LEASE`` — периодический трафик, при ``periodic=False`` строк нет, счётчик есть."""
    r = make(periodic=False)
    r.tr.transaction([("w", _JOG_LEASE, 5)])
    assert _lines(r.log) == []
    assert _counter(r.log, "write JOG_LEASE")["count"] == 1


# --------------------------------------------------------------------------------------------------
# A6b: тройка RES
# --------------------------------------------------------------------------------------------------


def _res_lines(log: Any) -> list[dict]:
    return [ln for ln in _lines(log) if ln["tag"] == "res"]


def test_a6b_same_res_triple_read_twice_gives_one_res_line(make: Any) -> None:
    """A6b: ``periodic=False``, чтение RES (0x1010×4 = [5,0,0,0]) дважды подряд -> одна строка ``res``."""
    r = make(periodic=False)
    r.fake.responses[_RES_SEQ] = [5, 0, 0, 0]
    r.tr.read_registers(_RES_SEQ, 4)
    r.tr.read_registers(_RES_SEQ, 4)
    assert len(_res_lines(r.log)) == 1


def test_a6b_changed_res_triple_gives_second_res_line(make: Any) -> None:
    """A6b: третье чтение [6,0,0,0] даёт вторую строку ``res``."""
    r = make(periodic=False)
    r.fake.responses[_RES_SEQ] = [5, 0, 0, 0]
    r.tr.read_registers(_RES_SEQ, 4)
    r.tr.read_registers(_RES_SEQ, 4)
    r.fake.responses[_RES_SEQ] = [6, 0, 0, 0]
    r.tr.read_registers(_RES_SEQ, 4)
    assert len(_res_lines(r.log)) == 2


def test_a6b_res_line_text_names_triple_and_error_text(make: Any) -> None:
    """A6b (DESIGN п.3): текст строки ``res`` — литерал из спецификации, у ``RES_ERRNO`` текст из ``ERR_TEXT``."""
    r = make(periodic=False)
    r.fake.responses[_RES_SEQ] = [5, 0, 0, 0]
    r.tr.read_registers(_RES_SEQ, 4)
    res = _res_lines(r.log)
    assert [ln["text"] for ln in res] == ["R RES_SEQ..+4 RES_SEQ = 5, RES_STATUS = 0, RES_ERRNO = 0 (ОК)"]
    assert res[0]["side"] == "out"


def test_a6b_partial_res_read_is_plain_read(make: Any) -> None:
    """A6b (DESIGN п.3): частичное чтение ``RES_SEQ`` (1 слово) — обычное чтение: при ``periodic=False`` строки нет."""
    r = make(periodic=False)
    r.fake.responses[_RES_SEQ] = [5]
    r.tr.read_registers(_RES_SEQ, 1)
    assert _lines(r.log) == []
    assert _counter(r.log, "read RES_SEQ")["count"] == 1


# --------------------------------------------------------------------------------------------------
# A7: seq, since_seq, dropped
# --------------------------------------------------------------------------------------------------


def _write_distinct(r: SimpleNamespace, values: range) -> None:
    for v in values:
        r.tr.transaction([("w", _CMD_SEQ, v)])


def test_a7_three_distinct_lines_give_last_seq_3(make: Any) -> None:
    """A7: три разные строки -> ``get()["last_seq"] == 3``."""
    r = make()
    _write_distinct(r, range(1, 4))
    assert r.log.get()["last_seq"] == 3


def test_a7_get_since_seq_returns_exactly_two_lines_with_n(make: Any) -> None:
    """A7: повтор третьей и одна новая -> ``get(since_seq=3)``: ``seq 3`` с ``n == 2`` и ``seq 4`` с ``n == 1``."""
    r = make()
    _write_distinct(r, range(1, 4))
    r.tr.transaction([("w", _CMD_SEQ, 3)])  # повтор третьей
    r.tr.transaction([("w", _CMD_SEQ, 4)])  # новая
    lines = r.log.get(since_seq=3)["lines"]
    assert [(ln["seq"], ln["n"], ln["text"]) for ln in lines] == [(3, 2, "W CMD_SEQ = 3"), (4, 1, "W CMD_SEQ = 4")]


def test_a7_ring_overflow_reports_dropped_5(make: Any) -> None:
    """A7: ``maxlen=5`` и 10 разных строк -> ``get(since_seq=0)["dropped"] == 5``."""
    r = make(maxlen=5)
    _write_distinct(r, range(1, 11))
    assert r.log.get(since_seq=0)["dropped"] == 5


def test_a7_ring_keeps_newest_maxlen_lines(make: Any) -> None:
    """A7: после переполнения кольца остаются 5 новейших строк (``seq`` 6..10)."""
    r = make(maxlen=5)
    _write_distinct(r, range(1, 11))
    assert [ln["seq"] for ln in r.log.get(since_seq=0)["lines"]] == [6, 7, 8, 9, 10]


def test_a7_get_limit_returns_first_ascending_and_last_seq_of_given(make: Any) -> None:
    """A7 (DESIGN п.9): ``limit`` — первые по возрастанию ``seq``; ``last_seq`` — ``seq`` последней отданной."""
    r = make()
    _write_distinct(r, range(1, 6))
    got = r.log.get(since_seq=0, limit=2)
    assert [ln["seq"] for ln in got["lines"]] == [1, 2]
    assert got["last_seq"] == 2


def test_a7_get_dropped_zero_when_nothing_evicted(make: Any) -> None:
    """A7: без вытеснения ``dropped == 0``."""
    r = make(maxlen=5)
    _write_distinct(r, range(1, 4))
    assert r.log.get(since_seq=0)["dropped"] == 0


def test_a7_get_has_contract_keys(make: Any) -> None:
    """Контракт ``get``: ровно ключи ``enabled, periodic, lines, last_seq, dropped, counters, log_errors``."""
    r = make()
    assert set(r.log.get()) == {"enabled", "periodic", "lines", "last_seq", "dropped", "counters", "log_errors"}


# --------------------------------------------------------------------------------------------------
# Связь: connect / disconnect и проброс атрибутов (DESIGN п.2, п.3)
# --------------------------------------------------------------------------------------------------


def test_link_connect_ok_line(make: Any) -> None:
    """DESIGN п.3: ``connect()`` обёртки пишет строку ``tag == "link"`` с текстом ``connect ok``."""
    r = make()
    assert r.tr.connect() is True
    assert [(ln["tag"], ln["text"]) for ln in _lines(r.log)] == [("link", "connect ok")]


def test_link_connect_fail_line(make: Any) -> None:
    """DESIGN п.3: неуспешный ``connect()`` пишет ``connect fail``; результат не подменяется."""
    r = make()
    r.fake.connect_result = False
    assert r.tr.connect() is False
    assert [(ln["tag"], ln["text"]) for ln in _lines(r.log)] == [("link", "connect fail")]


def test_link_disconnect_line(make: Any) -> None:
    """DESIGN п.3: ``disconnect()`` пишет ``tag == "link"``, текст ``disconnect``; внутренний транспорт отключён."""
    r = make()
    r.tr.disconnect()
    assert [(ln["tag"], ln["text"]) for ln in _lines(r.log)] == [("link", "disconnect")]
    assert r.fake.disconnect_calls == 1


def test_wrapper_get_status_reads_through_to_inner(make: Any) -> None:
    """DESIGN п.2: ``get_status`` (и прочее чтение атрибутов) отдаёт внутренний транспорт."""
    r = make()
    assert r.tr.get_status() == {"connected_since": 123.5, "marker": "fake"}


def test_wrapper_is_connected_reflects_inner(make: Any) -> None:
    """DESIGN п.2: ``is_connected`` — свойство внутреннего транспорта."""
    r = make()
    assert r.tr.is_connected is True
    r.fake.connected = False
    assert r.tr.is_connected is False


def test_wrapper_allows_instance_attribute_override(make: Any) -> None:
    """DESIGN п.2: ``__slots__``/``__setattr__`` запрещены: тесты драйвера подменяют ``transaction`` экземпляром."""
    r = make()
    r.tr.transaction = lambda ops: "patched"
    assert r.tr.transaction([("w", _CMD_FLAG, 1)]) == "patched"


def test_wrapper_private_missing_attribute_raises_attribute_error(make: Any) -> None:
    """DESIGN п.2: для имён на ``_`` прозрачного проброса нет — ``AttributeError``."""
    r = make()
    with pytest.raises(AttributeError):
        _ = r.tr._no_such_private_thing


# --------------------------------------------------------------------------------------------------
# A10: запись в логгер
# --------------------------------------------------------------------------------------------------


class _Collector(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def log_records() -> Iterator[_Collector]:
    """Обработчик на имени журнала + уровень INFO (действующий уровень ``mpf.*`` по умолчанию WARNING)."""
    logger = logging.getLogger(_LOGGER_NAME)
    handler = _Collector()
    old_level = logger.level
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    try:
        yield handler
    finally:
        logger.removeHandler(handler)
        logger.setLevel(old_level)


def test_a10_each_new_line_gives_a_logger_record_with_seq_prefix(make: Any, log_records: _Collector) -> None:
    """A10: три новые строки -> три записи логгера, текст начинается с ``#<seq> ``."""
    r = make(device_id="rv2")
    _write_distinct(r, range(1, 4))
    msgs = [rec.getMessage() for rec in log_records.records]
    assert len(msgs) == 3
    assert msgs[0].startswith("#1 ")
    assert msgs[1].startswith("#2 ")
    assert msgs[2].startswith("#3 ")


def test_a10_record_comes_from_logger_named_after_device(make: Any, log_records: _Collector) -> None:
    """A10: имя логгера ``mpf.Services.device_hub.drivers.exchange_log.rv2``."""
    r = make(device_id="rv2")
    r.tr.transaction([("w", _CMD_FLAG, 1)])
    assert {rec.name for rec in log_records.records} == {_LOGGER_NAME}


def test_a10_record_text_has_side_and_line_text(make: Any, log_records: _Collector) -> None:
    """A10 (DESIGN п.8): запись — ``#<seq> <side> <text>``."""
    r = make(device_id="rv2")
    r.tr.transaction([("w", _CMD_FLAG, 1)])
    assert [rec.getMessage() for rec in log_records.records] == ["#1 in W CMD_FLAG = 1"]


def test_a10_merged_repeat_does_not_open_a_new_numbered_record(make: Any, log_records: _Collector) -> None:
    """A10: повтор склеенной строки не даёт записи ``#<новый seq> `` (одна запись на НОВУЮ строку)."""
    r = make(device_id="rv2")
    r.tr.transaction([("w", _CMD_SEQ, 1)])
    r.tr.transaction([("w", _CMD_SEQ, 1)])
    r.tr.transaction([("w", _CMD_SEQ, 1)])
    msgs = [rec.getMessage() for rec in log_records.records]
    assert [m for m in msgs if m.startswith("#2 ")] == []
    assert len([m for m in msgs if m.startswith("#1 ")]) >= 1


def test_a10_disabled_log_gives_no_logger_records(make: Any, log_records: _Collector) -> None:
    """A10 + A5: выключенный журнал не пишет в логгер."""
    r = make(device_id="rv2", enabled=False)
    _exchange_burst(r)
    assert log_records.records == []


# --------------------------------------------------------------------------------------------------
# A11: два потока
# --------------------------------------------------------------------------------------------------


def _run_two_writers(r: SimpleNamespace, n: int = 500) -> None:
    start = threading.Barrier(2)

    def writer(address: int) -> None:
        start.wait(timeout=_THREAD_DEADLINE_S)
        for i in range(1, n + 1):
            r.tr.transaction([("w", address, i)])

    threads = [
        threading.Thread(target=writer, args=(_HB_PC,), daemon=True, name="a11-a"),
        threading.Thread(target=writer, args=(_JOG_LEASE,), daemon=True, name="a11-b"),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(_THREAD_DEADLINE_S)
    assert not any(t.is_alive() for t in threads), "поток записи не завершился за дедлайн"


def test_a11_two_threads_give_1000_lines_with_contiguous_seq(make: Any) -> None:
    """A11: 1000 строк, ``seq`` подряд без пропусков и повторов."""
    r = make(periodic=True)
    _run_two_writers(r)
    lines = _lines(r.log)
    assert len(lines) == 1000
    assert sorted(ln["seq"] for ln in lines) == list(range(1, 1001))


def test_a11_counters_count_500_per_register(make: Any) -> None:
    """A11: ``write HB_PC.count == 500`` и ``write JOG_LEASE.count == 500``."""
    r = make(periodic=True)
    _run_two_writers(r)
    assert (_counter(r.log, "write HB_PC")["count"], _counter(r.log, "write JOG_LEASE")["count"]) == (500, 500)


def test_a11_time_is_monotonic_by_seq(make: Any) -> None:
    """A11 (DESIGN п.7): ``t`` не убывает с ростом ``seq`` (второе чтение часов — под замком журнала)."""
    r = make(periodic=True)
    _run_two_writers(r)
    ts = [ln["t"] for ln in sorted(_lines(r.log), key=lambda ln: ln["seq"])]
    assert all(a <= b for a, b in zip(ts, ts[1:], strict=False))


# --------------------------------------------------------------------------------------------------
# Уровень (б): RobotDriverV2 на sim v2 (E2eRig)
# --------------------------------------------------------------------------------------------------


class _Rec:
    """``publish``-приёмник драйвера: копит ``(path, payload)``."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.items: list[tuple[str, Any]] = []

    def __call__(self, path: str, payload: Any) -> None:
        with self._lock:
            self.items.append((path, payload))


def _entry(dev_id: str, port: int, **params: Any) -> Any:
    from Services.device_hub.registry.entry import DeviceEntry

    return DeviceEntry(
        id=dev_id,
        name=dev_id,
        kind="robot",
        protocol="delta_v2",
        transport={"type": "tcp", "host": "127.0.0.1", "port": port, "unit_id": ROBOT_UNIT_ID},
        params=params,
    )


@contextmanager
def _connected(port: int, **params: Any) -> Iterator[Any]:
    """``RobotDriverV2`` после ``connect()`` (обязан вернуть ``True``) и ``desired_connected = True``."""
    from Services.device_hub.drivers.robot_driver_v2 import RobotDriverV2

    drv = RobotDriverV2(_entry("rv2", port, **params), None, publish=_Rec())
    try:
        assert bounded(drv.connect, _CONNECT_DEADLINE_S) is True, "connect() не вернул True"
        drv.desired_connected = True
        yield drv
    finally:
        try:
            bounded(drv.disconnect, _CALL_DEADLINE_S)
        except Exception:  # noqa: BLE001 — уборка не подменяет исключение теста
            pass


def _payload(res: dict) -> dict:
    """Данные журнала из ответа ``call`` / команды: плоские ключи либо один вложенный ``dict``."""
    assert isinstance(res, dict)
    assert res.get("status") == "ok", f"ответ не ok: {res!r}"
    if "enabled" in res:
        return res
    for value in res.values():
        if isinstance(value, dict) and "enabled" in value:
            return value
    raise AssertionError(f"в ответе нет данных журнала: {res!r}")


def _drv_get(drv: Any, **args: Any) -> dict:
    full = {"since_seq": 0, "limit": 2000, **args}
    return _payload(bounded(lambda: drv.call("exchange_log_get", dict(full)), _CALL_DEADLINE_S))


def _drv_set(drv: Any, **args: Any) -> dict:
    return _payload(bounded(lambda: drv.call("exchange_log_set", dict(args)), _CALL_DEADLINE_S))


def _tick(drv: Any) -> None:
    bounded(lambda: drv.tick(None), _CALL_DEADLINE_S)


def test_a1_connect_and_one_tick_log_link_heartbeat_and_telemetry_read() -> None:
    """A1: после ``connect()`` и одного ``tick()`` (``periodic=True``): ``link`` ``connect ok``, ``in`` с ``HB_PC``,
    ``out`` со строкой ``R TLM_PROTO_VER...``."""
    with E2eRig() as rig, _connected(rig.port, exchange_log={"periodic": True}) as drv:
        _tick(drv)
        lines = _drv_get(drv)["lines"]
        assert any(ln["tag"] == "link" and ln["text"] == "connect ok" for ln in lines), [ln["text"] for ln in lines][:5]
        assert any(ln["side"] == "in" and "HB_PC" in ln["text"] for ln in lines)
        assert any(ln["side"] == "out" and ln["text"].startswith("R TLM_PROTO_VER") for ln in lines)


def test_a8_reconnect_logs_disconnect_then_connect_ok_with_growing_seq() -> None:
    """A8: ``drv.transport.disconnect()`` + ``drv.connect()``: новые строки с большим ``seq``, ``link`` ``disconnect``,
    после неё ``link`` ``connect ok``."""
    with E2eRig() as rig, _connected(rig.port, exchange_log={"periodic": True}) as drv:
        seq_before = _drv_get(drv)["last_seq"]
        bounded(drv.transport.disconnect, _CALL_DEADLINE_S)
        assert bounded(drv.connect, _CONNECT_DEADLINE_S) is True
        new = _drv_get(drv, since_seq=seq_before + 1)["lines"]
        assert new, "после разрыва и connect() новых строк нет"
        assert new[0]["seq"] > seq_before
        links = [ln["text"] for ln in new if ln["tag"] == "link"]
        assert "disconnect" in links
        assert "connect ok" in links
        assert links.index("disconnect") < len(links) - 1 - links[::-1].index("connect ok")


def test_a12_toggling_enabled_does_not_reconnect() -> None:
    """A12: ``transport.get_status()["connected_since"]`` одинаков до ``enabled=False`` и после ``enabled=True``."""
    with E2eRig() as rig, _connected(rig.port, exchange_log={"periodic": True}) as drv:
        before = drv.transport.get_status()["connected_since"]
        _drv_set(drv, enabled=False)
        _drv_set(drv, enabled=True)
        after = drv.transport.get_status()["connected_since"]
        assert after == before


def test_a12_tick_after_reenable_gives_lines() -> None:
    """A12: после ``enabled=False`` -> ``enabled=True`` следующий ``tick()`` даёт строки."""
    with E2eRig() as rig, _connected(rig.port, exchange_log={"periodic": True}) as drv:
        _drv_set(drv, enabled=False)
        _drv_set(drv, enabled=True)
        mark = _drv_get(drv)["last_seq"]
        _tick(drv)
        assert _drv_get(drv, since_seq=mark + 1)["lines"]


def test_a12_tick_while_disabled_gives_no_lines() -> None:
    """A12 + A5 на драйвере: пока ``enabled=False``, ``tick()`` строк не добавляет."""
    with E2eRig() as rig, _connected(rig.port, exchange_log={"periodic": True}) as drv:
        _drv_set(drv, enabled=False)
        mark = _drv_get(drv)["last_seq"]
        _tick(drv)
        got = _drv_get(drv, since_seq=mark + 1)
        assert got["lines"] == []
        assert got["last_seq"] == mark


def test_driver_entry_params_exchange_log_set_initial_knobs() -> None:
    """Module contract: начальные ручки из ``entry.params["exchange_log"]`` (``enabled=False``, ``periodic=True``)."""
    with E2eRig() as rig, _connected(rig.port, exchange_log={"enabled": False, "periodic": True}) as drv:
        state = _drv_get(drv)
        assert (state["enabled"], state["periodic"]) == (False, True)
        assert state["lines"] == []


def test_driver_default_knobs_enabled_true_periodic_false() -> None:
    """Module contract: без ``exchange_log`` в параметрах ``enabled=True``, ``periodic=False``."""
    with E2eRig() as rig, _connected(rig.port) as drv:
        state = _drv_get(drv)
        assert (state["enabled"], state["periodic"]) == (True, False)


# --------------------------------------------------------------------------------------------------
# Уровень (в): команды плагина (A9)
# --------------------------------------------------------------------------------------------------


def _make_plugin(tmp_path: Path) -> tuple[Any, Any]:
    from Plugins.hub.device_hub.plugin import DeviceHubPlugin
    from Plugins.hub.device_hub.tests.conftest import make_ctx

    registry_file = tmp_path / "devices.yaml"
    ctx = make_ctx({"registry_path": str(registry_file)}, tmp_registry=registry_file)
    plugin = DeviceHubPlugin()
    plugin.configure(ctx)
    plugin.start(ctx)
    return plugin, ctx


@contextmanager
def _plugin(tmp_path: Path) -> Iterator[Any]:
    plugin, ctx = _make_plugin(tmp_path)
    try:
        yield plugin
    finally:
        try:
            bounded(lambda: plugin.shutdown(ctx), _CALL_DEADLINE_S)
        except Exception:  # noqa: BLE001 — уборка не подменяет исключение теста
            pass


def _upsert_robot(plugin: Any, port: int, dev_id: str = "rv2") -> None:
    res = plugin.cmd_device_upsert(
        {
            "id": dev_id,
            "name": dev_id,
            "kind": "robot",
            "protocol": "delta_v2",
            "transport": {"type": "tcp", "host": "127.0.0.1", "port": port, "unit_id": ROBOT_UNIT_ID},
            "params": {"exchange_log": {"periodic": True}},
        }
    )
    assert res["status"] == "ok", res


def _connect_via_plugin(plugin: Any, dev_id: str = "rv2") -> None:
    """Подключение, как делает супервизор плагина: команда ставит в очередь, очередь разбирается."""
    assert plugin.cmd_device_connect({"device_id": dev_id})["status"] == "ok"
    bounded(plugin._process_conn_queue, _CONNECT_DEADLINE_S)


def test_a9_get_for_connected_robot_returns_ok_with_journal_data(tmp_path: Path) -> None:
    """A9: ``robot_exchange_log_get`` для робота -> ``status: ok`` и данные журнала (``link`` ``connect ok``)."""
    with E2eRig() as rig, _plugin(tmp_path) as plugin:
        _upsert_robot(plugin, rig.port)
        _connect_via_plugin(plugin)
        res = bounded(lambda: plugin.cmd_robot_exchange_log_get({"device_id": "rv2"}), _CALL_DEADLINE_S)
        data = _payload(res)
        assert any(ln["tag"] == "link" and ln["text"] == "connect ok" for ln in data["lines"])


def test_a9_set_for_robot_returns_ok_and_applies_knob(tmp_path: Path) -> None:
    """A9: ``robot_exchange_log_set`` -> ``status: ok``, ручка применена (видно в следующем ``get``)."""
    with E2eRig() as rig, _plugin(tmp_path) as plugin:
        _upsert_robot(plugin, rig.port)
        _connect_via_plugin(plugin)
        res = bounded(
            lambda: plugin.cmd_robot_exchange_log_set({"device_id": "rv2", "periodic": False}), _CALL_DEADLINE_S
        )
        assert _payload(res)["periodic"] is False
        got = bounded(lambda: plugin.cmd_robot_exchange_log_get({"device_id": "rv2"}), _CALL_DEADLINE_S)
        assert _payload(got)["periodic"] is False


@pytest.mark.parametrize("command", ["cmd_robot_exchange_log_get", "cmd_robot_exchange_log_set"])
def test_a9_non_robot_device_gives_kind_error(tmp_path: Path, command: str) -> None:
    """A9: ``device_id`` не-робота (ПЧ) -> ``status: error`` (ошибка kind)."""
    with _plugin(tmp_path) as plugin:
        res = plugin.cmd_device_upsert(
            {"id": "vfd_1", "name": "V1", "kind": "vfd", "transport": {"type": "bridge", "bridge": "rv2"}}
        )
        assert res["status"] == "ok", res
        out = getattr(plugin, command)({"device_id": "vfd_1"})
        assert out["status"] == "error"


@pytest.mark.parametrize("command", ["cmd_robot_exchange_log_get", "cmd_robot_exchange_log_set"])
def test_a9_missing_device_id_gives_error(tmp_path: Path, command: str) -> None:
    """A9: без ``device_id`` -> ``status: error`` (как у прочих ``robot_*`` команд)."""
    with _plugin(tmp_path) as plugin:
        out = getattr(plugin, command)({})
        assert out["status"] == "error"
        assert "device_id" in out["message"]


def test_a9_get_for_unconnected_robot_with_driver_is_ok_and_shows_connect_fail(tmp_path: Path) -> None:
    """A9: робот не подключён (драйвер есть) -> ``status: ok``, в данных есть ``link`` ``connect fail`` или ``err``."""
    with _plugin(tmp_path) as plugin:
        _upsert_robot(plugin, free_port())  # на порту никто не слушает
        _connect_via_plugin(plugin)
        assert plugin._manager.get_driver("rv2") is not None, "драйвер после попытки подключения не создан"
        res = bounded(lambda: plugin.cmd_robot_exchange_log_get({"device_id": "rv2"}), _CALL_DEADLINE_S)
        lines = _payload(res)["lines"]
        assert any((ln["tag"] == "link" and ln["text"] == "connect fail") or ln["tag"] == "err" for ln in lines), [
            (ln["tag"], ln["text"]) for ln in lines
        ]
