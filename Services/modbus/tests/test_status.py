"""Тесты ModbusStatus — счётчики, uptime, сериализация."""

from __future__ import annotations

from Services.modbus.core.status import ConnectionState, ModbusStatus


def test_default_disconnected() -> None:
    st = ModbusStatus()
    assert st.state is ConnectionState.DISCONNECTED
    assert not st.is_connected
    assert st.total_errors == 0


def test_total_errors_sums() -> None:
    st = ModbusStatus(reads_err=2, writes_err=3)
    assert st.total_errors == 5


def test_uptime_none_when_not_connected() -> None:
    assert ModbusStatus().uptime(100.0) == 0.0


def test_uptime_computed() -> None:
    st = ModbusStatus(connected_since=10.0)
    assert st.uptime(35.0) == 25.0


def test_uptime_never_negative() -> None:
    st = ModbusStatus(connected_since=50.0)
    assert st.uptime(40.0) == 0.0


def test_to_dict_contains_telemetry() -> None:
    st = ModbusStatus(state=ConnectionState.CONNECTED, reads_ok=5, connected_since=0.0)
    data = st.to_dict(now=10.0)
    assert data["state"] == "connected"
    assert data["is_connected"] is True
    assert data["reads_ok"] == 5
    assert data["uptime_sec"] == 10.0


def test_to_dict_without_now_has_no_uptime() -> None:
    data = ModbusStatus().to_dict()
    assert "uptime_sec" not in data
