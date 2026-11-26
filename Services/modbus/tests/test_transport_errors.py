"""Авторские тесты R2-S1a, часть 1: опасные места перевода ошибок и счётчика сеанса.

Поведение на настоящем pymodbus и loopback проверяет слепая приёмка
``test_r2s1a_transport_acceptance.py``. Здесь — то, что живым сервером не
вызвать или не поймать детерминированно: сбой закрытия сокета внутри ``except``,
ошибки вызывающего, порядок «счётчик раньше колбэков», повторный вход из
колбэка, ожидание замка за ``connect()``.

Каждый вызов, способный повиснуть, идёт в потоке-демоне со сроком.
"""

from __future__ import annotations

import logging
import struct
import threading
from collections.abc import Callable, Iterator
from typing import Any

import pytest

from Services.modbus.core.config import ModbusConfig
from Services.modbus.core.device import ModbusDevice
from Services.modbus.sdk.client import ModbusSdkClient
from Services.modbus.sdk.errors import ModbusConnectionError, ModbusIOError

from .conftest import FakeSdkClient

_DEADLINE_S = 5.0


class _Call:
    """Вызов в потоке-демоне; ``result()`` ждёт не дольше срока."""

    def __init__(self, fn: Callable[[], Any]) -> None:
        self.value: Any = None
        self.exc: BaseException | None = None

        def body() -> None:
            try:
                self.value = fn()
            except BaseException as exc:  # noqa: BLE001 — уходит вызывающему
                self.exc = exc

        self._thread = threading.Thread(target=body, name="r2s1a-hazard", daemon=True)
        self._thread.start()

    def waiting(self, seconds: float) -> bool:
        """True, если за ``seconds`` вызов так и не вернулся."""
        self._thread.join(seconds)
        return self._thread.is_alive()

    def result(self) -> Any:
        self._thread.join(_DEADLINE_S)
        assert not self._thread.is_alive(), f"вызов не вернулся за {_DEADLINE_S} с"
        if self.exc is not None:
            raise self.exc
        return self.value


def _run(fn: Callable[[], Any]) -> Any:
    return _Call(fn).result()


def _wire_writes(fake: FakeSdkClient) -> list[str]:
    return [name for name, _args in fake.calls if name.startswith("write")]


# --------------------------------------------------------------------------- #
# sdk: ветка исключения вызова
# --------------------------------------------------------------------------- #


class _RaisingPymodbus:
    """Дубль pymodbus-клиента: каждый обмен бросает ``exc``; ``close()`` считает и может сам упасть."""

    def __init__(self, exc: BaseException, close_exc: BaseException | None = None) -> None:
        self.exc = exc
        self.close_exc = close_exc
        self.closed = 0
        self.requests = 0

    def connect(self) -> bool:
        return True

    def close(self) -> None:
        self.closed += 1
        if self.close_exc is not None:
            raise self.close_exc

    def read_holding_registers(self, address: int, *, count: int = 1, **_unit: Any) -> Any:
        self.requests += 1
        raise self.exc


def _sdk(fake: _RaisingPymodbus) -> ModbusSdkClient:
    # Без pymodbus ModbusException подменён на Exception — ветка вызова ловила бы всё.
    pytest.importorskip("pymodbus")
    sdk = ModbusSdkClient(ModbusConfig(host="127.0.0.1", port=1, unit_id=2))
    sdk._client = fake  # noqa: SLF001 — подмена транспорта, публичной точки нет
    return sdk


class _Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(record.getMessage())


@pytest.fixture
def warnings_log() -> Iterator[list[str]]:
    handler = _Capture()
    root = logging.getLogger()
    root.addHandler(handler)
    try:
        yield handler.lines
    finally:
        root.removeHandler(handler)


def test_close_failure_does_not_replace_the_cause(warnings_log: list[str]) -> None:
    cause = OSError("линия оборвана")
    fake = _RaisingPymodbus(cause, close_exc=RuntimeError("порт занят"))
    sdk = _sdk(fake)

    with pytest.raises(ModbusIOError) as info:
        _run(lambda: sdk.read_holding(0x10, 1))

    assert info.value.__cause__ is cause
    assert "read_holding_registers" in str(info.value)
    assert "линия оборвана" in str(info.value)
    assert fake.closed == 1
    assert len(warnings_log) == 1, warnings_log
    for part in ("unit=2", "0x0010", "линия оборвана", "порт занят"):
        assert part in warnings_log[0]
    # Обёртка не обнулена: следующий вызов снова доходит до того же клиента.
    with pytest.raises(ModbusIOError):
        _run(lambda: sdk.read_holding(0x10, 1))
    assert fake.requests == 2


@pytest.mark.parametrize("exc_type", [TypeError, ValueError, struct.error])
def test_caller_errors_pass_through_without_closing_or_new_session(exc_type: type[Exception]) -> None:
    fake = _RaisingPymodbus(exc_type("аргумент вызывающего"))
    errors: list[str] = []
    dev = ModbusDevice(ModbusConfig(host="127.0.0.1", port=1), client=_sdk(fake), on_error=errors.append)
    assert _run(dev.connect) is True
    session = dev.session

    with pytest.raises(exc_type):
        _run(lambda: dev.read_holding(0, 1))

    assert fake.closed == 0
    assert errors == []
    assert dev.is_connected is True
    assert dev.session == session


# --------------------------------------------------------------------------- #
# core: порядок счётчика и колбэков
# --------------------------------------------------------------------------- #


def test_reentrant_write_from_on_error_with_old_session_is_refused(config: ModbusConfig) -> None:
    """Счётчик растёт раньше колбэка: запись из ``on_error`` с прежним значением не уходит."""
    fake = FakeSdkClient()
    seen: list[BaseException | None] = []
    old: list[int] = []

    def on_error(_message: str) -> None:
        try:
            dev.write_register(5, 1, expected_session=old[0])
        except ModbusConnectionError as exc:
            seen.append(exc)
        else:
            seen.append(None)

    dev = ModbusDevice(config, client=fake, on_error=on_error)
    assert _run(dev.connect) is True
    old.append(dev.session)
    fake.fail_next_op = True

    with pytest.raises(ModbusIOError):
        _run(lambda: dev.read_holding(0, 1))

    assert len(seen) == 1 and isinstance(seen[0], ModbusConnectionError), seen
    assert _wire_writes(fake) == []


def test_reentrant_write_from_on_status_during_connect_is_refused(config: ModbusConfig) -> None:
    """То же для ``connect()``: колбэк «connected» уже видит новый сеанс."""
    fake = FakeSdkClient()
    seen: list[str] = []
    old: list[int] = []

    def on_status(status: dict[str, Any]) -> None:
        if old and status["state"] == "connected":
            try:
                dev.write_register(5, 1, expected_session=old[0])
            except ModbusConnectionError:
                seen.append("refused")
            else:
                seen.append("sent")

    dev = ModbusDevice(config, client=fake, on_status=on_status)
    assert _run(dev.connect) is True
    old.append(dev.session)

    assert _run(dev.connect) is True

    assert seen == ["refused"]
    assert _wire_writes(fake) == []


def test_raising_on_error_does_not_cancel_the_new_session(config: ModbusConfig) -> None:
    fake = FakeSdkClient()

    def on_error(_message: str) -> None:
        raise RuntimeError("колбэк упал")

    dev = ModbusDevice(config, client=fake, on_error=on_error)
    assert _run(dev.connect) is True
    old = dev.session
    fake.fail_next_op = True

    with pytest.raises(RuntimeError):
        _run(lambda: dev.read_holding(0, 1))

    with pytest.raises(ModbusConnectionError):
        _run(lambda: dev.write_register(5, 1, expected_session=old))
    assert _wire_writes(fake) == []


def test_failed_connect_starts_a_new_session(config: ModbusConfig) -> None:
    fake = FakeSdkClient()
    dev = ModbusDevice(config, client=fake)
    assert _run(dev.connect) is True
    old = dev.session
    fake.fail_connect = True

    assert _run(dev.connect) is False

    assert dev.session > old


@pytest.mark.parametrize("state", ["connected", "error"])
def test_refusal_touches_neither_state_nor_counters_nor_callbacks(config: ModbusConfig, state: str) -> None:
    fake = FakeSdkClient()
    events: list[str] = []
    dev = ModbusDevice(
        config,
        client=fake,
        on_status=lambda _s: events.append("status"),
        on_error=lambda _m: events.append("error"),
        on_data=lambda _d: events.append("data"),
    )
    assert _run(dev.connect) is True
    old = dev.session
    if state == "error":
        fake.fail_next_op = True
        with pytest.raises(ModbusIOError):
            _run(lambda: dev.read_holding(0, 1))
    else:
        assert _run(dev.connect) is True
    before_status = dev.get_status()
    before_events = list(events)
    before_session = dev.session

    for write in (
        lambda: dev.write_register(5, 1, expected_session=old),
        lambda: dev.write_registers(5, [1, 2], expected_session=old),
        lambda: dev.write_coil(5, True, expected_session=old),
        lambda: dev.transaction([("w", 5, 1)], expected_session=old),
    ):
        with pytest.raises(ModbusConnectionError):
            _run(write)

    after_status = dev.get_status()
    for key in ("state", "last_error", "writes_ok", "writes_err"):
        assert after_status[key] == before_status[key], key
    assert events == before_events
    assert dev.session == before_session
    assert _wire_writes(fake) == []


# --------------------------------------------------------------------------- #
# core: замок
# --------------------------------------------------------------------------- #


class _GatedClient(FakeSdkClient):
    """Клиент, у которого чтение или ``connect()`` можно задержать внутри замка устройства."""

    def __init__(self) -> None:
        super().__init__()
        self.gate_read = False
        self.gate_connect = False
        self.entered = threading.Event()
        self.release = threading.Event()

    def _hold(self) -> None:
        self.entered.set()
        self.release.wait(_DEADLINE_S * 2)

    def connect(self) -> bool:
        if self.gate_connect:
            self._hold()
        return super().connect()

    def read_holding(self, address: int, count: int) -> list[int]:
        if self.gate_read:
            self._hold()
        return super().read_holding(address, count)


def test_session_is_readable_while_the_lock_is_held(config: ModbusConfig) -> None:
    """Допуск операции не ждёт чужой обмен: чтение ``session`` без замка."""
    fake = _GatedClient()
    dev = ModbusDevice(config, client=fake)
    assert _run(dev.connect) is True
    expected = dev.session
    fake.gate_read = True
    reader = _Call(lambda: dev.read_holding(0, 1))
    try:
        assert fake.entered.wait(_DEADLINE_S)
        probe = _Call(lambda: dev.session)
        assert not probe.waiting(1.0), "session ждёт замок устройства"
        assert probe.value == expected
    finally:
        fake.release.set()
    reader.result()


def test_writer_queued_behind_connect_is_refused(config: ModbusConfig) -> None:
    """Значение снято до переподключения, замок получен после него: запись не уходит."""
    fake = _GatedClient()
    dev = ModbusDevice(config, client=fake)
    assert _run(dev.connect) is True
    old = dev.session
    fake.gate_connect = True
    connecting = _Call(dev.connect)
    try:
        assert fake.entered.wait(_DEADLINE_S)
        writer = _Call(lambda: dev.write_register(5, 1, expected_session=old))
        assert writer.waiting(0.3), "запись обязана ждать замок, пока идёт connect()"
    finally:
        fake.release.set()

    assert connecting.result() is True
    with pytest.raises(ModbusConnectionError):
        writer.result()
    assert _wire_writes(fake) == []
    # Парная проверка: свежее значение проходит.
    assert _run(lambda: dev.write_register(5, 1, expected_session=dev.session)) is True
    assert _wire_writes(fake) == ["write_register"]
