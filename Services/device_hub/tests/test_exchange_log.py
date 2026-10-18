"""Тесты автора T5.6: опасные места журнала обмена — замки, выключенный журнал, сбои форматтера и логгера.

Purpose:
    Дополняют слепую приёмку (``test_t56_exchange_log_acceptance.py``) свойствами потоков и стоимости.
    H1 — замок журнала не держится во время вызова транспорта; H2 — выключенный журнал ничего не вызывает;
    H3 — сбой форматтера не ломает обмен; H4 — логгер вызывается вне замка журнала. Плюс запись о закрытой
    склейке и сбой самого логгера. Фейк транспорта — только здесь.

Public API:
    Только тесты ``test_*``.

Stability: lite

Каждый тест, который может зависнуть, гоняет вызов в daemon-потоке с дедлайном ``join``.
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from collections.abc import Callable, Iterator
from typing import Any

import pytest

from Services.device_hub.drivers import exchange_log
from Services.device_hub.drivers.exchange_log import ExchangeLog, ExchangeLogTransport

_DEADLINE_S = 10.0
_TLM = 0x1040
_CMD_SEQ = 0x1001
_HB_PC = 0x1020
_LOGGER_PREFIX = "mpf.Services.device_hub.drivers.exchange_log."


class _Fake:
    """Фейк ``RegisterTransport``: чтение нулями; опциональная блокировка чтения на событии."""

    def __init__(self) -> None:
        self.connected = True
        self.read_gate: threading.Event | None = None
        self.read_entered = threading.Event()
        self.tx_gate: threading.Event | None = None
        self.tx_entered = threading.Event()

    @property
    def is_connected(self) -> bool:
        return self.connected

    def read_registers(self, address: int, count: int = 1) -> list[int]:
        if self.read_gate is not None:
            self.read_entered.set()
            assert self.read_gate.wait(_DEADLINE_S), "фейк не дождался освобождения"
        return [0] * count

    def transaction(self, ops: list[tuple]) -> bool:
        if self.tx_gate is not None:
            self.tx_entered.set()
            assert self.tx_gate.wait(_DEADLINE_S), "фейк не дождался освобождения"
        return True

    def connect(self) -> bool:
        return True

    def disconnect(self) -> None:
        self.connected = False


class _CountingClock:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> float:
        self.calls += 1
        return float(self.calls)


class _Collector(logging.Handler):
    def __init__(self, gate: threading.Event | None = None) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []
        self.gate = gate
        self.entered = threading.Event()

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)
        if self.gate is not None:
            self.entered.set()
            self.gate.wait(_DEADLINE_S)


@pytest.fixture
def hook() -> Iterator[Any]:
    """Подключает обработчик к логгеру журнала устройства; уровень INFO; уборка в конце."""
    attached: list[tuple[logging.Logger, _Collector, int]] = []

    def _attach(device_id: str, handler: _Collector) -> None:
        logger = logging.getLogger(_LOGGER_PREFIX + device_id)
        attached.append((logger, handler, logger.level))
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)

    yield _attach
    for logger, handler, level in attached:
        logger.removeHandler(handler)
        logger.setLevel(level)


def _run(fn: Any) -> threading.Thread:
    thread = threading.Thread(target=fn, daemon=True)
    thread.start()
    return thread


def _join(thread: threading.Thread) -> None:
    thread.join(_DEADLINE_S)
    assert not thread.is_alive(), "поток не завершился за дедлайн"


def _bounded[T](fn: Callable[[], T]) -> T:
    """Вызов в daemon-потоке с дедлайном: взаимная блокировка в журнале даёт красный тест, а не зависание набора."""
    box: list[tuple[bool, Any]] = []

    def target() -> None:
        try:
            box.append((True, fn()))
        except BaseException as exc:  # noqa: BLE001 — исключение возвращается вызывающему теста
            box.append((False, exc))

    _join(_run(target))
    ok, value = box[0]
    if not ok:
        raise value
    return value


# --------------------------------------------------------------------------------------------------
# H1: замок журнала не держится во время вызова транспорта
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("blocked", ["read", "transaction"])
def test_h1_log_lock_not_held_during_transport_call(blocked: str) -> None:
    """Вызов транспорта блокирован на событии; второй поток обменивается через другой метод и завершается."""
    fake = _Fake()
    gate = threading.Event()
    log = ExchangeLog("h1", periodic=True)
    tr = ExchangeLogTransport(fake, log)
    read_text, write_text = "R TLM_PROTO_VER..+32", "W CMD_SEQ = 1"
    if blocked == "read":
        fake.read_gate, entered = gate, fake.read_entered
        first = _run(lambda: tr.read_registers(_TLM, 32))
        other, other_text, first_text = (lambda: tr.transaction([("w", _CMD_SEQ, 1)])), write_text, read_text
    else:
        fake.tx_gate, entered = gate, fake.tx_entered
        first = _run(lambda: tr.transaction([("w", _CMD_SEQ, 1)]))
        other, other_text, first_text = (lambda: tr.read_registers(_TLM, 32)), read_text, write_text
    try:
        assert entered.wait(_DEADLINE_S), "вызов не дошёл до фейка"
        second = _run(other)
        _join(second)  # завершился, пока первый вызов внутри транспорта
        assert first.is_alive()
        assert [ln["text"] for ln in _bounded(log.get)["lines"]] == [other_text]
    finally:
        gate.set()
        _join(first)
    assert [ln["text"] for ln in _bounded(log.get)["lines"]] == [other_text, first_text]


# --------------------------------------------------------------------------------------------------
# H2: выключенный журнал ничего не вызывает
# --------------------------------------------------------------------------------------------------


def test_h2_disabled_log_calls_no_clock_no_formatter_no_logger(monkeypatch: pytest.MonkeyPatch, hook: Any) -> None:
    calls: list[str] = []

    def _spy(name: str, real: Any) -> Any:
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            calls.append(name)
            return real(*args, **kwargs)

        return wrapper

    for name in ("_tx_entries", "_read_entries", "_link_entries", "_tx_op_name"):
        monkeypatch.setattr(exchange_log, name, _spy(name, getattr(exchange_log, name)))
    clock = _CountingClock()
    handler = _Collector()
    hook("h2", handler)
    log = ExchangeLog("h2", clock=clock, enabled=False, periodic=True)
    tr = ExchangeLogTransport(_Fake(), log)

    assert _bounded(lambda: tr.read_registers(_TLM, 4)) == [0, 0, 0, 0]
    assert _bounded(lambda: tr.transaction([("wm", 0x1001, [5, 16, 0]), ("w", 0x1000, 1)])) is True
    assert _bounded(tr.connect) is True
    _bounded(tr.disconnect)

    assert clock.calls == 0
    assert calls == []
    assert handler.records == []
    state = _bounded(log.get)
    assert (state["lines"], state["counters"], state["last_seq"], state["log_errors"]) == ([], {}, 0, 0)


# --------------------------------------------------------------------------------------------------
# H3: сбой форматтера не ломает обмен
# --------------------------------------------------------------------------------------------------


def test_h3_formatter_failure_keeps_exchange_alive_and_warns_once(monkeypatch: pytest.MonkeyPatch, hook: Any) -> None:
    def _boom(*_args: Any, **_kwargs: Any) -> list:
        raise RuntimeError("форматтер сломан")

    monkeypatch.setattr(exchange_log, "_tx_entries", _boom)
    handler = _Collector()
    hook("h3", handler)
    log = ExchangeLog("h3", periodic=True)
    tr = ExchangeLogTransport(_Fake(), log)

    assert _bounded(lambda: tr.transaction([("w", _CMD_SEQ, 1)])) is True
    assert _bounded(lambda: tr.transaction([("w", _CMD_SEQ, 2)])) is True

    state = _bounded(log.get)
    assert state["log_errors"] == 2
    assert state["lines"] == []
    assert state["counters"]["write CMD_SEQ"]["count"] == 2  # счётчики считаются и при сбое форматтера
    warnings = [r for r in handler.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "RuntimeError" in warnings[0].getMessage()


# --------------------------------------------------------------------------------------------------
# H4: логгер вызывается вне замка журнала
# --------------------------------------------------------------------------------------------------


def test_h4_logger_is_called_outside_the_log_lock(hook: Any) -> None:
    gate = threading.Event()
    handler = _Collector(gate)
    hook("h4", handler)
    log = ExchangeLog("h4", periodic=False)
    tr = ExchangeLogTransport(_Fake(), log)
    writer = _run(lambda: tr.transaction([("w", _CMD_SEQ, 1)]))  # новая строка -> запись в логгер -> блок в обработчике
    try:
        assert handler.entered.wait(_DEADLINE_S), "запись не дошла до обработчика логгера"
        reader = _run(lambda: tr.read_registers(_TLM, 32))  # periodic=False: строки и записи нет, счётчик есть
        _join(reader)  # завершился, пока обработчик логгера держит писателя
        assert writer.is_alive()
        assert _bounded(log.get)["counters"]["read TLM_PROTO_VER"]["count"] == 1
        assert len(handler.records) == 1
    finally:
        gate.set()
        _join(writer)


# --------------------------------------------------------------------------------------------------
# Запись о закрытой склейке и сбой логгера
# --------------------------------------------------------------------------------------------------


def test_closed_merge_writes_times_n_record_and_open_tail_does_not(hook: Any) -> None:
    handler = _Collector()
    hook("tail", handler)
    log = ExchangeLog("tail", periodic=True)
    tr = ExchangeLogTransport(_Fake(), log)
    for _ in range(3):
        _bounded(lambda: tr.transaction([("w", _HB_PC, 7)]))
    assert [r.getMessage() for r in handler.records] == ["#1 in W HB_PC = 7"]  # хвост ещё открыт
    _bounded(lambda: tr.transaction([("w", _CMD_SEQ, 1)]))
    assert [r.getMessage() for r in handler.records] == ["#1 in W HB_PC = 7", "#1 … ×3", "#2 in W CMD_SEQ = 1"]


def test_logger_failure_is_counted_and_does_not_break_exchange() -> None:
    class _BadLogger:
        def info(self, *_a: Any, **_k: Any) -> None:
            raise OSError("диск")

        def warning(self, *_a: Any, **_k: Any) -> None:
            raise OSError("диск")

    log = ExchangeLog("bad")
    log._logger = _BadLogger()  # type: ignore[assignment]
    tr = ExchangeLogTransport(_Fake(), log)
    # сбой логгера -> _note_failure берёт замок журнала: при вызове логгера под замком это взаимная блокировка
    assert _bounded(lambda: tr.transaction([("w", _CMD_SEQ, 1)])) is True
    state = _bounded(log.get)
    assert state["log_errors"] >= 1
    assert [ln["text"] for ln in state["lines"]] == ["W CMD_SEQ = 1"]


# --------------------------------------------------------------------------------------------------
# Тройка RES: подавление повтора не должно зависеть от склейки
# --------------------------------------------------------------------------------------------------


def test_unchanged_res_triple_after_another_line_gives_no_second_res_line() -> None:
    """periodic=False: RES [5,0,0,0], другая строка (STOP_REQ), снова RES [5,0,0,0] -> ровно одна строка res, n == 1.

    Склейка (хвост уже другая строка) повтор не скроет: подавляет его только сравнение тройки с последней записанной.
    """
    fake = _Fake()
    fake.read_registers = lambda address, count=1: [5, 0, 0, 0][:count]  # type: ignore[method-assign]
    log = ExchangeLog("res", periodic=False)
    tr = ExchangeLogTransport(fake, log)
    _bounded(lambda: tr.read_registers(0x1010, 4))
    _bounded(lambda: tr.transaction([("w", 0x1021, 1)]))  # STOP_REQ: строка есть при periodic=False
    _bounded(lambda: tr.read_registers(0x1010, 4))
    lines = _bounded(log.get)["lines"]
    assert [(ln["tag"], ln["n"]) for ln in lines] == [("res", 1), ("stop", 1)]


# --------------------------------------------------------------------------------------------------
# Порядок t по seq при одновременной записи (на GIL гонку сам по себе не поймать: часы с рукопожатием)
# --------------------------------------------------------------------------------------------------


class _HandshakeClock:
    """Часы-счётчик: третий вызов в потоке (t строки: старт, конец, t под замком) у первого пришедшего задерживается.

    Лидер ждёт, пока второй поток дойдёт до своего третьего вызова, и ещё 50 мс. Если замок журнала охватывает
    чтение часов, второй поток до него не дойдёт и лидер уйдёт по таймауту; иначе второй поток успеет выдать свой
    ``seq`` первым и ``t`` по ``seq`` не будет возрастать.
    """

    def __init__(self) -> None:
        self._local = threading.local()
        self._guard = threading.Lock()
        self._counter = 0
        self._leader: int | None = None
        self.follower_arrived = threading.Event()

    def __call__(self) -> float:
        n = getattr(self._local, "n", 0) + 1
        self._local.n = n
        with self._guard:
            self._counter += 1
            value = float(self._counter)
        if n != 3:
            return value
        me = threading.get_ident()
        with self._guard:
            if self._leader is None:
                self._leader = me
        if self._leader == me:
            self.follower_arrived.wait(0.3)
            threading.Event().wait(0.05)
        else:
            self.follower_arrived.set()
        return value


def test_time_is_monotonic_by_seq_when_clock_read_yields() -> None:
    """Второе чтение часов — под замком журнала вместе с выдачей seq (DESIGN п.7): t не убывает с ростом seq."""
    log = ExchangeLog("race", clock=_HandshakeClock(), periodic=True)
    tr = ExchangeLogTransport(_Fake(), log)
    start = threading.Barrier(2)

    def writer(value: int) -> None:
        start.wait(_DEADLINE_S)
        tr.transaction([("w", _CMD_SEQ, value)])

    threads = [threading.Thread(target=writer, args=(v,), daemon=True) for v in (1, 2)]
    for t in threads:
        t.start()
    for t in threads:
        _join(t)
    lines = _bounded(log.get)["lines"]
    assert [ln["seq"] for ln in lines] == [1, 2]
    assert lines[0]["t"] < lines[1]["t"], [(ln["seq"], ln["t"]) for ln in lines]


# --------------------------------------------------------------------------------------------------
# seq из двух потоков: без дублей и пропусков, строки целы, порядок кольца = порядок seq
# --------------------------------------------------------------------------------------------------


class _HandshakeRing(deque):
    """Кольцо, у которого первый ``append`` ждёт второй поток между выдачей ``seq`` и добавлением строки.

    Корректный код держит замок журнала от выдачи ``seq`` до ``append``: второй поток не дойдёт, лидер уйдёт по
    таймауту. Без замка второй поток успеет выдать следующий ``seq`` и добавить свою строку первым — порядок кольца
    разойдётся с порядком ``seq`` (читатель по ``last_seq`` пропустит или прочтёт дважды).
    """

    def __init__(self, maxlen: int) -> None:
        super().__init__(maxlen=maxlen)
        self._guard = threading.Lock()
        self._leader: int | None = None
        self.follower_arrived = threading.Event()

    def append(self, item: Any) -> None:
        me = threading.get_ident()
        with self._guard:
            if self._leader is None:
                self._leader = me
        if self._leader == me:
            self.follower_arrived.wait(0.3)
            threading.Event().wait(0.05)
        else:
            self.follower_arrived.set()
        super().append(item)


def test_two_threads_give_contiguous_seq_intact_lines_and_exact_counters() -> None:
    per_thread = 20
    log = ExchangeLog("seq2", periodic=True)
    log._ring = _HandshakeRing(maxlen=2000)  # type: ignore[assignment]
    tr = ExchangeLogTransport(_Fake(), log)
    start = threading.Barrier(2)
    texts = {f"W CMD_SEQ = {base + i}" for base in (100, 200) for i in range(per_thread)}  # все разные: склейки нет

    def writer(base: int) -> None:
        start.wait(_DEADLINE_S)
        for i in range(per_thread):
            tr.transaction([("w", _CMD_SEQ, base + i)])

    threads = [threading.Thread(target=writer, args=(b,), daemon=True) for b in (100, 200)]
    for t in threads:
        t.start()
    for t in threads:
        _join(t)

    state = _bounded(lambda: log.get(limit=1000))
    lines = state["lines"]
    total = 2 * per_thread
    assert [ln["seq"] for ln in lines] == list(range(1, total + 1))  # подряд, без дублей и пропусков, в порядке кольца
    assert all(set(ln) == {"seq", "t", "side", "text", "tag", "n", "ms"} for ln in lines)
    assert all((ln["side"], ln["tag"], ln["n"]) == ("in", "", 1) for ln in lines)
    assert {ln["text"] for ln in lines} == texts
    assert len({ln["text"] for ln in lines}) == total
    assert state["last_seq"] == total
    assert state["counters"]["write CMD_SEQ"]["count"] == total


# --------------------------------------------------------------------------------------------------
# Врезки: команда плагина по имени через настоящий путь регистрации; обёртка внедрённого транспорта драйвера
# --------------------------------------------------------------------------------------------------


def test_plugin_command_resolves_by_name_through_command_manager(tmp_path: Any) -> None:
    """Команда ``robot_exchange_log_get`` найдена по имени в таблице ``commands`` (регистрация, как в процессе хаба)."""
    from multiprocess_framework.modules.process_module.plugins.testing import MockCommandManager
    from Plugins.hub.device_hub.plugin import DeviceHubPlugin
    from Plugins.hub.device_hub.tests.conftest import make_ctx
    from Services.robot_comm.core.registers import ROBOT_UNIT_ID
    from Services.robot_comm.tests.e2e_rig_v2 import free_port

    registry_file = tmp_path / "devices.yaml"
    ctx = make_ctx({"registry_path": str(registry_file)}, tmp_registry=registry_file)
    ctx.command_manager = MockCommandManager()
    plugin = DeviceHubPlugin()
    plugin.configure(ctx)
    plugin.start(ctx)
    try:
        plugin._auto_register_commands(ctx)  # то же, что делает фреймворк после configure
        handlers = ctx.command_manager.commands
        assert "robot_exchange_log_get" in handlers
        assert "robot_exchange_log_set" in handlers
        port = free_port()  # слушателя нет: драйвер создаётся, связи нет
        res = plugin.cmd_device_upsert(
            {
                "id": "rv2",
                "name": "rv2",
                "kind": "robot",
                "protocol": "delta_v2",
                "transport": {"type": "tcp", "host": "127.0.0.1", "port": port, "unit_id": ROBOT_UNIT_ID},
            }
        )
        assert res["status"] == "ok", res
        assert plugin.cmd_device_connect({"device_id": "rv2"})["status"] == "ok"
        _bounded(plugin._process_conn_queue)
        got = _bounded(lambda: handlers["robot_exchange_log_get"]({"device_id": "rv2"}))
        assert got["status"] == "ok", got
        assert "lines" in got
        done = _bounded(lambda: handlers["robot_exchange_log_set"]({"device_id": "rv2", "periodic": True}))
        assert done["status"] == "ok" and done["periodic"] is True, done
    finally:
        _bounded(lambda: plugin.shutdown(ctx))


def test_driver_wraps_injected_transport_so_its_calls_reach_the_journal() -> None:
    """Транспорт, внедрённый в ``RobotDriverV2(transport=...)``, обёрнут: его ``connect`` виден в журнале драйвера."""
    from Services.device_hub.drivers.robot_driver_v2 import RobotDriverV2
    from Services.device_hub.registry.entry import DeviceEntry
    from Services.robot_comm.core.registers import ROBOT_UNIT_ID

    entry = DeviceEntry(
        id="rv2",
        name="rv2",
        kind="robot",
        protocol="delta_v2",
        transport={"type": "tcp", "host": "127.0.0.1", "port": 1, "unit_id": ROBOT_UNIT_ID},
        params={"exchange_log": {"periodic": True}},
    )
    drv = RobotDriverV2(entry, None, transport=_Fake())
    assert _bounded(drv.transport.connect) is True
    _bounded(lambda: drv.transport.read_registers(_TLM, 32))
    got = _bounded(lambda: drv.call("exchange_log_get", {}))
    assert got["status"] == "ok"
    assert [(ln["tag"], ln["text"]) for ln in got["lines"]] == [
        ("link", "connect ok"),
        ("", "R TLM_PROTO_VER..+32"),
    ]
