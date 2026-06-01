"""Тесты тестового Modbus-slave сервера.

``format_recv`` и ``trace_write`` — чистая логика, тестируется без pymodbus
(PDU подменяется duck-typed заглушкой). Реальный round-trip (запустить сервер +
записать клиентом) помечен importorskip и пропускается без pymodbus.
"""

from __future__ import annotations

import types

import pytest

from Services.modbus.server import format_recv, trace_write


def test_format_recv_basic() -> None:
    assert format_recv(100, [640, 480, 1234], ts="16:21:07") == ("[16:21:07] recv holding[100..102] = [640, 480, 1234]")


def test_format_recv_single_value() -> None:
    assert format_recv(5, [42], ts="00:00:00") == "[00:00:00] recv holding[5..5] = [42]"


def test_format_recv_uses_current_time_when_none() -> None:
    s = format_recv(0, [1, 2])
    assert "recv holding[0..1] = [1, 2]" in s
    assert s.startswith("[") and "]" in s


def _pdu(function_code: int, address: int, registers: list[int]) -> types.SimpleNamespace:
    """Duck-typed заглушка PDU (как у pymodbus write-запросов)."""
    return types.SimpleNamespace(function_code=function_code, address=address, registers=registers)


def test_trace_write_logs_incoming_multiple() -> None:
    out: list[str] = []
    pdu = _pdu(16, 100, [640, 480, 1234])
    result = trace_write(False, pdu, emit=out.append)
    assert result is pdu  # фильтр обязан вернуть pdu без изменений
    assert len(out) == 1
    assert "recv holding[100..102] = [640, 480, 1234]" in out[0]


def test_trace_write_logs_incoming_single() -> None:
    out: list[str] = []
    trace_write(False, _pdu(6, 5, [42]), emit=out.append)
    assert len(out) == 1
    assert "recv holding[5..5] = [42]" in out[0]


def test_trace_write_skips_outgoing() -> None:
    out: list[str] = []
    trace_write(True, _pdu(16, 100, [1, 2, 3]), emit=out.append)
    assert out == []


def test_trace_write_skips_non_write_fc() -> None:
    out: list[str] = []
    trace_write(False, _pdu(3, 100, [1, 2, 3]), emit=out.append)  # FC=03 read
    assert out == []


def test_real_roundtrip_server_receives_write(capfd: pytest.CaptureFixture[str]) -> None:
    """Поднять сервер в потоке, записать клиентом, убедиться что приём залогирован."""
    pytest.importorskip("pymodbus")

    import threading
    import time

    from pymodbus.client import ModbusTcpClient

    from Services.modbus.server import run_test_server

    port = 5099
    t = threading.Thread(
        target=run_test_server,
        kwargs={"host": "127.0.0.1", "port": port, "size": 300},
        daemon=True,
    )
    t.start()
    time.sleep(1.0)  # дать серверу подняться

    client = ModbusTcpClient(host="127.0.0.1", port=port, timeout=3)
    assert client.connect()
    try:
        rr = client.write_registers(100, [640, 480, 1234], device_id=1)
        assert not rr.isError()
    finally:
        client.close()

    time.sleep(0.3)
    captured = capfd.readouterr().out
    assert "recv holding[100..102] = [640, 480, 1234]" in captured
