"""R2-S1d: ``ModbusDevice.drop_link()`` — связь снята, клиент SDK остаётся (тесты автора).

Настоящие ``ModbusDevice`` и pymodbus по TCP на ``127.0.0.1``; сервер — ``LoopbackServer`` приёмки R2-S1a.
Сторожится: запись после ``drop_link`` открывает новый TCP (после ``disconnect`` — нет); сеанс растёт, ``on_error`` и
счётчики не трогаются; ``drop_link`` ждёт идущую запись (замок устройства); причина ошибки записи сохраняется.
"""

from __future__ import annotations

import time
from collections.abc import Iterator

import pytest

from Services.modbus.sdk.errors import ModbusConnectionError, ModbusIOError
from Services.modbus.tests.test_r2s1a_transport_acceptance import Call, LoopbackServer, _Device, run


@pytest.fixture
def srv() -> Iterator[LoopbackServer]:
    server = LoopbackServer()
    server.store.write(0, [11, 22])
    try:
        yield server
    finally:
        server.close()


def _counters(rig: _Device) -> tuple[int, int, int, int]:
    status = rig.dev.get_status()
    return status["reads_ok"], status["reads_err"], status["writes_ok"], status["writes_err"]


def test_write_after_drop_link_opens_new_tcp_and_counters_stay(srv: LoopbackServer) -> None:
    rig = _Device(srv.port)
    assert run(lambda: rig.dev.read_holding(0, 2)) == [11, 22]
    session, counters = rig.dev.session, _counters(rig)

    run(rig.dev.drop_link)

    assert rig.dev.is_connected is False
    assert rig.dev.session == session + 1
    assert rig.errors == []
    assert _counters(rig) == counters
    assert run(lambda: rig.dev.write_register(12, 3)) is True  # клиент SDK жив: неявный connect pymodbus
    assert srv.accepted == 2
    assert [(f.conn, f.addr) for f in srv.writes()] == [(2, 12)]


def test_write_after_disconnect_has_no_frame_and_no_tcp(srv: LoopbackServer) -> None:
    """Парная проверка: намеренное ``disconnect()`` выбрасывает клиента SDK — записи без connect нет."""
    rig = _Device(srv.port)
    run(rig.dev.disconnect)
    with pytest.raises(ModbusConnectionError):
        run(lambda: rig.dev.write_register(12, 3))
    assert srv.writes() == []
    assert srv.accepted == 1


def test_connect_and_disconnect_after_drop_link(srv: LoopbackServer) -> None:
    rig = _Device(srv.port)
    session = rig.dev.session
    run(rig.dev.drop_link)
    run(rig.dev.drop_link)  # идемпотентно
    assert rig.dev.session == session + 2
    assert run(rig.dev.connect) is True
    assert rig.dev.is_connected is True
    assert rig.dev.session == session + 3
    assert run(lambda: rig.dev.read_holding(0, 2)) == [11, 22]
    run(rig.dev.disconnect)
    with pytest.raises(ModbusConnectionError):
        run(lambda: rig.dev.write_register(12, 3))
    assert srv.writes() == []


def test_drop_link_waits_for_write_in_flight(srv: LoopbackServer) -> None:
    """Порядок задан сервером: запись держится на сервере, ``drop_link`` ждёт замок устройства и идёт после неё."""
    rig = _Device(srv.port)
    held = srv.on_next(lambda f: f.fc == 6 and f.addr == 12, "ok", hold=True)
    order: list[str] = []

    def write() -> bool:
        ok = rig.dev.write_register(12, 3)
        order.append("write")
        return ok

    def drop() -> None:
        rig.dev.drop_link()
        order.append("drop")

    writing = Call(write)
    assert held.entered.wait(10.0), "запись не дошла до сервера"
    dropping = Call(drop)
    time.sleep(0.3)
    assert dropping.alive() is True, "drop_link не ждал идущую запись"
    held.release.set()
    assert writing.result(10.0) is True
    dropping.result(10.0)
    assert order == ["write", "drop"]
    assert rig.dev.is_connected is False
    assert [f.addr for f in srv.writes()] == [12]


@pytest.mark.parametrize("kind", ["fin", "rst"])
def test_dead_socket_write_keeps_builtin_connection_error_cause(srv: LoopbackServer, kind: str) -> None:
    """Причина ошибки записи на мёртвом сокете — встроенный ``ConnectionError`` (по ней драйвер повторяет СТОП)."""
    rig = _Device(srv.port)
    assert run(lambda: rig.dev.read_holding(0, 2)) == [11, 22]
    srv.drop_idle(kind)
    with pytest.raises(ModbusIOError) as caught:
        run(lambda: rig.dev.write_register(12, 3))
    assert isinstance(caught.value.__cause__, ConnectionError), repr(caught.value.__cause__)


def test_timed_out_write_cause_is_not_builtin_connection_error(srv: LoopbackServer) -> None:
    """Таймаут записи: причина из pymodbus, не встроенный ``ConnectionError`` (драйвер СТОП не повторяет)."""
    rig = _Device(srv.port, timeout_sec=0.5)
    srv.on_next(lambda f: f.fc == 6, "silent")
    srv.on_next(lambda f: f.fc == 6, "silent")
    with pytest.raises(ModbusIOError) as caught:
        run(lambda: rig.dev.write_register(12, 3))
    assert caught.value.__cause__ is not None
    assert not isinstance(caught.value.__cause__, ConnectionError), repr(caught.value.__cause__)
