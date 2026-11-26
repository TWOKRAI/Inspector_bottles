"""Слепая приёмка R2-S1a, часть 1 (A1-A10): обрыв Modbus виден вызывающему, сеанс отсекает старую запись.

Настоящие ``ModbusSdkClient``, ``ModbusDevice`` и pymodbus поверх своего TCP-сервера на ``127.0.0.1`` (порт даёт ОС).
Единственный дублёр клиента — в A5. Сервер пишет каждый принятый кадр (функция, адрес, число, значения), умеет
оборвать связь по FIN и RST, оборвать простаивающее соединение, молчать, держать ответ до отпускания и считает
принятые соединения. ``LoopbackServer`` импортирует и приёмка части 2 (``device_hub``).

Режимы обрыва:
    ``fin``  — сервер принял запрос и закрыл соединение без ответа (штатное закрытие);
    ``rst``  — то же, но сброс (SO_LINGER = 0);
    ``idle`` — сервер закрыл простаивающее соединение ДО следующего запроса.
"""

from __future__ import annotations

import socket
import struct
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

import pytest

from Services.modbus.core.config import ModbusConfig
from Services.modbus.core.device import ModbusDevice
from Services.modbus.sdk import client as sdk_client_module
from Services.modbus.sdk.client import ModbusSdkClient
from Services.modbus.sdk.errors import ModbusConnectionError, ModbusIOError

_HOST = "127.0.0.1"
_WRITE_FC = (5, 6, 15, 16)
_DEADLINE_S = 15.0


# --------------------------------------------------------------------------------------------------
# Сервер
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Frame:
    conn: int  # номер соединения с 1
    fc: int
    addr: int
    count: int
    values: tuple[int, ...]  # значения записи; у чтения пусто


class _Rule:
    """Разовое правило: на первый подходящий кадр выполнить ``action``; ``hold`` — сначала ждать ``release``."""

    def __init__(self, pred: Callable[[Frame], bool], action: str, hold: bool) -> None:
        self.pred = pred
        self.action = action
        self.hold = hold
        self.entered = threading.Event()
        self.release = threading.Event()


class DictStore:
    def __init__(self) -> None:
        self.regs: dict[int, int] = {}

    def read(self, address: int, count: int) -> list[int]:
        return [self.regs.get(address + i, 0) for i in range(count)]

    def write(self, address: int, values: list[int]) -> None:
        for i, value in enumerate(values):
            self.regs[address + i] = value


class LoopbackServer:
    """Минимальный Modbus TCP сервер (FC 1-6, 16) с инъекцией обрывов."""

    def __init__(self, store: Any = None) -> None:
        self.store = store if store is not None else DictStore()
        self.store_lock = threading.RLock()
        self.accepted = 0
        self._lock = threading.Lock()
        self._frames: list[Frame] = []
        self._rules: list[_Rule] = []
        self._all_rules: list[_Rule] = []
        self._conns: list[socket.socket] = []
        self._closed = False
        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener.bind((_HOST, 0))
        self._listener.listen(16)
        self.port: int = self._listener.getsockname()[1]
        threading.Thread(target=self._accept_loop, name="r2s1a-accept", daemon=True).start()

    # --- управление ---

    def on_next(self, pred: Callable[[Frame], bool], action: str, *, hold: bool = False) -> _Rule:
        """``action``: ``fin`` | ``rst`` | ``silent`` | ``exc`` (ответ-исключение) | ``ok``."""
        rule = _Rule(pred, action, hold)
        with self._lock:
            self._rules.append(rule)
            self._all_rules.append(rule)
        return rule

    def drop_idle(self, kind: str = "fin") -> None:
        """Закрыть все живые соединения, пока на них нет запроса."""
        with self._lock:
            conns, self._conns = self._conns, []
        assert conns, "обрывать нечего: нет живых соединений"
        for conn in conns:
            self._kill(conn, kind)
        time.sleep(0.2)  # FIN / RST должен дойти до клиента

    def close(self) -> None:
        self._closed = True
        with self._lock:
            conns, self._conns = self._conns, []
            rules = list(self._all_rules)
        for rule in rules:
            rule.release.set()
        try:
            self._listener.close()
        except OSError:
            pass
        for conn in conns:
            self._kill(conn, "fin")

    # --- журнал ---

    def mark(self) -> int:
        with self._lock:
            return len(self._frames)

    def frames(self, since: int = 0) -> list[Frame]:
        with self._lock:
            return self._frames[since:]

    def writes(self, since: int = 0) -> list[Frame]:
        return [f for f in self.frames(since) if f.fc in _WRITE_FC]

    # --- внутреннее ---

    @staticmethod
    def _kill(conn: socket.socket, kind: str) -> None:
        try:
            if kind == "rst":
                conn.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("hh", 1, 0))
            else:
                conn.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            conn.close()
        except OSError:
            pass

    def _accept_loop(self) -> None:
        while not self._closed:
            try:
                conn, _ = self._listener.accept()
            except OSError:
                return
            with self._lock:
                self.accepted += 1
                number = self.accepted
                self._conns.append(conn)
            threading.Thread(target=self._serve, args=(conn, number), name="r2s1a-conn", daemon=True).start()

    @staticmethod
    def _recv(conn: socket.socket, size: int) -> bytes | None:
        data = b""
        while len(data) < size:
            try:
                chunk = conn.recv(size - len(data))
            except OSError:
                return None
            if not chunk:
                return None
            data += chunk
        return data

    def _serve(self, conn: socket.socket, number: int) -> None:
        while not self._closed:
            header = self._recv(conn, 7)
            if header is None:
                return
            tid, _pid, length, unit = struct.unpack(">HHHB", header)
            pdu = self._recv(conn, length - 1)
            if pdu is None:
                return
            frame = self._parse(number, pdu)
            with self._lock:
                self._frames.append(frame)
                rule = next((r for r in self._rules if r.pred(frame)), None)
                if rule is not None:
                    self._rules.remove(rule)
            action = "ok"
            if rule is not None:
                rule.entered.set()
                if rule.hold:
                    rule.release.wait(30.0)
                action = rule.action
            if action in ("fin", "rst"):
                with self._lock:
                    if conn in self._conns:
                        self._conns.remove(conn)
                self._kill(conn, action)
                return
            if action == "silent":
                continue
            reply = bytes([frame.fc | 0x80, 2]) if action == "exc" else self._reply(frame, pdu)
            try:
                conn.sendall(struct.pack(">HHHB", tid, 0, len(reply) + 1, unit) + reply)
            except OSError:
                return

    @staticmethod
    def _parse(number: int, pdu: bytes) -> Frame:
        fc = pdu[0]
        addr, second = struct.unpack(">HH", pdu[1:5])
        if fc in (5, 6):
            return Frame(number, fc, addr, 1, (second,))
        if fc == 16:
            values = struct.unpack(f">{second}H", pdu[6 : 6 + 2 * second])
            return Frame(number, fc, addr, second, tuple(values))
        return Frame(number, fc, addr, second, ())

    def _reply(self, frame: Frame, pdu: bytes) -> bytes:
        with self.store_lock:
            if frame.fc in _WRITE_FC:
                values = [int(v == 0xFF00) for v in frame.values] if frame.fc == 5 else list(frame.values)
                self.store.write(frame.addr, values)
                return pdu[:5]
            words = list(self.store.read(frame.addr, frame.count))
        words += [0] * (frame.count - len(words))
        if frame.fc in (1, 2):
            packed = bytearray((frame.count + 7) // 8)
            for i, word in enumerate(words):
                if word & 1:
                    packed[i // 8] |= 1 << (i % 8)
            return bytes([frame.fc, len(packed)]) + bytes(packed)
        return bytes([frame.fc, 2 * frame.count]) + struct.pack(f">{frame.count}H", *words)


# --------------------------------------------------------------------------------------------------
# Помощники
# --------------------------------------------------------------------------------------------------


class Call:
    """Вызов в потоке-демоне: ``result()`` ждёт не дольше срока и отдаёт значение или исключение как есть."""

    def __init__(self, fn: Callable[[], Any]) -> None:
        self.value: Any = None
        self.exc: BaseException | None = None

        def body() -> None:
            try:
                self.value = fn()
            except BaseException as exc:  # noqa: BLE001 — уходит вызывающему
                self.exc = exc

        self._thread = threading.Thread(target=body, name="r2s1a-call", daemon=True)
        self._thread.start()

    def alive(self) -> bool:
        return self._thread.is_alive()

    def join(self, deadline_s: float = _DEADLINE_S) -> None:
        self._thread.join(deadline_s)
        assert not self._thread.is_alive(), f"вызов не вернулся за {deadline_s} с"

    def result(self, deadline_s: float = _DEADLINE_S) -> Any:
        self.join(deadline_s)
        if self.exc is not None:
            raise self.exc
        return self.value


def run(fn: Callable[[], Any], deadline_s: float = _DEADLINE_S) -> Any:
    return Call(fn).result(deadline_s)


def _config(port: int, **kw: Any) -> ModbusConfig:
    params: dict[str, Any] = {"host": _HOST, "port": port, "unit_id": 1, "timeout_sec": 2.0, "retries": 1}
    params.update(kw)
    return ModbusConfig(**params)


@pytest.fixture
def server() -> Iterator[LoopbackServer]:
    srv = LoopbackServer()
    srv.store.write(0, [11, 22])
    try:
        yield srv
    finally:
        srv.close()


class _Device:
    """Настоящий ``ModbusDevice`` + список вызовов ``on_error``."""

    def __init__(self, port: int, **kw: Any) -> None:
        self.errors: list[str] = []
        self.dev = ModbusDevice(_config(port, **kw), on_error=self.errors.append)
        assert run(self.dev.connect) is True

    def status(self, key: str) -> Any:
        return self.dev.get_status()[key]


_READS = [("read_holding", 3), ("read_input", 4), ("read_coils", 1), ("read_discrete_inputs", 2)]

_WRITES: dict[str, Callable[..., Any]] = {
    "write_register": lambda dev, addr, **kw: dev.write_register(addr, 7, **kw),
    "write_registers": lambda dev, addr, **kw: dev.write_registers(addr, [7, 8], **kw),
    "write_coil": lambda dev, addr, **kw: dev.write_coil(addr, True, **kw),
    "transaction": lambda dev, addr, **kw: dev.transaction([("w", addr, 7), ("wm", addr + 1, [8, 9])], **kw),
}


def _drop_by_read(server: LoopbackServer, dev: ModbusDevice, kind: str) -> None:
    """Оборвать связь на чтении регистра 900; исход самого чтения здесь не проверяется."""
    server.on_next(lambda f: f.addr == 900, kind)
    call = Call(lambda: dev.read_holding(900, 1))
    call.join()


# --------------------------------------------------------------------------------------------------
# A1-A4: ошибка вызова видна как ModbusIOError
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["fin", "rst"])
@pytest.mark.parametrize(("method", "fc"), _READS)
def test_a01_dropped_read_raises_modbus_io_error(server: LoopbackServer, method: str, fc: int, kind: str) -> None:
    sdk = ModbusSdkClient(_config(server.port))
    run(sdk.connect)
    server.on_next(lambda f: f.fc == fc, kind)
    try:
        with pytest.raises(ModbusIOError):
            run(lambda: getattr(sdk, method)(0, 1))
        assert [f.fc for f in server.frames()] == [fc]  # сервер запрос принял
    finally:
        sdk.close()


@pytest.mark.parametrize("kind", ["fin", "rst"])
@pytest.mark.parametrize(("method", "fc"), _READS)
def test_a02_dropped_read_marks_device_error(server: LoopbackServer, method: str, fc: int, kind: str) -> None:
    rig = _Device(server.port)
    server.on_next(lambda f: f.fc == fc, kind)
    with pytest.raises(ModbusIOError):
        run(lambda: getattr(rig.dev, method)(0, 1))
    assert rig.dev.is_connected is False
    assert len(rig.errors) == 1
    assert rig.status("reads_err") == 1


@pytest.mark.parametrize("kind", ["fin", "rst"])
@pytest.mark.parametrize("op", ["write_register", "write_registers", "write_coil"])
def test_a03_dropped_write_marks_device_error(server: LoopbackServer, op: str, kind: str) -> None:
    rig = _Device(server.port)
    server.on_next(lambda f: f.addr == 20, kind)
    with pytest.raises(ModbusIOError):
        run(lambda: _WRITES[op](rig.dev, 20))
    assert rig.dev.is_connected is False
    assert rig.status("writes_err") == 1
    assert len(server.writes()) == 1


@pytest.mark.parametrize("kind", ["fin", "rst"])
def test_a03_dropped_transaction_stops_the_series(server: LoopbackServer, kind: str) -> None:
    rig = _Device(server.port)
    server.on_next(lambda f: f.addr == 11, kind)
    ops = [("w", 10, 1), ("w", 11, 2), ("w", 12, 3)]
    with pytest.raises(ModbusIOError):
        run(lambda: rig.dev.transaction(ops))
    assert rig.dev.is_connected is False
    assert rig.status("writes_err") == 1
    assert [f.addr for f in server.writes()] == [10, 11]  # остаток серии (12) не пришёл
    # парная проверка: тот же сервер кадр по адресу 12 записывает
    assert run(rig.dev.connect) is True
    run(lambda: rig.dev.write_register(12, 3))
    assert [f.addr for f in server.writes()] == [10, 11, 12]


@pytest.mark.parametrize("kind", ["fin", "rst"])
def test_a04_idle_drop_before_request_raises_then_new_tcp_works(server: LoopbackServer, kind: str) -> None:
    rig = _Device(server.port)
    assert run(lambda: rig.dev.read_holding(0, 2)) == [11, 22]
    server.drop_idle(kind)
    with pytest.raises(ModbusIOError):
        run(lambda: rig.dev.read_holding(0, 2))
    assert run(rig.dev.connect) is True
    assert run(lambda: rig.dev.read_holding(0, 2)) == [11, 22]
    assert server.accepted == 2
    assert server.frames()[-1].conn == 2


# --------------------------------------------------------------------------------------------------
# A5: ветка slave= (единственный дублёр клиента)
# --------------------------------------------------------------------------------------------------


def _slave_only_client(exc: BaseException) -> type:
    class SlaveOnly:
        """Клиент старой pymodbus: аргумента ``device_id`` нет (TypeError), вызов с ``slave=`` бросает ``exc``."""

        calls: list[str] = []

        def __init__(self, **_kw: Any) -> None:
            self.socket = None

        def connect(self) -> bool:
            return True

        def close(self) -> None:
            pass

        def read_holding_registers(self, address: int, *, count: int = 1, slave: int = 0) -> Any:
            type(self).calls.append("read")
            raise exc

        def write_register(self, address: int, value: int, *, slave: int = 0) -> Any:
            type(self).calls.append("write")
            raise exc

    return SlaveOnly


@pytest.mark.parametrize("exc_name", ["OSError", "ModbusException"])
@pytest.mark.parametrize("method", ["read_holding", "write_register"])
def test_a05_slave_branch_errors_become_modbus_io_error(
    monkeypatch: pytest.MonkeyPatch, method: str, exc_name: str
) -> None:
    from pymodbus.exceptions import ModbusException

    exc = OSError("сокет закрыт") if exc_name == "OSError" else ModbusException("нет ответа")
    fake = _slave_only_client(exc)
    monkeypatch.setattr(sdk_client_module, "ModbusTcpClient", fake)
    sdk = ModbusSdkClient(_config(1))  # порт не используется: клиент подменён
    run(sdk.connect)
    with pytest.raises(ModbusIOError):
        run(lambda: getattr(sdk, method)(0, 1))
    assert len(fake.calls) == 1  # дошли именно до вызова с slave=


# --------------------------------------------------------------------------------------------------
# A6-A8: восстановление, таймаут, прежнее поведение
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["fin", "rst", "idle"])
def test_a06_connect_after_error_opens_new_tcp(server: LoopbackServer, kind: str) -> None:
    rig = _Device(server.port)
    assert run(lambda: rig.dev.read_holding(0, 2)) == [11, 22]
    if kind == "idle":
        server.drop_idle("fin")
    else:
        server.on_next(lambda f: f.fc == 3, kind)
    failed = Call(lambda: rig.dev.read_holding(0, 2))
    failed.join()
    assert failed.exc is not None, "чтение по оборванной связи обязано упасть"
    assert run(rig.dev.connect) is True
    assert run(lambda: rig.dev.read_holding(0, 2)) == [11, 22]
    assert server.accepted == 2


def test_a07_silent_server_timeout_raises_modbus_io_error(server: LoopbackServer) -> None:
    rig = _Device(server.port, timeout_sec=0.3, retries=0)
    server.on_next(lambda f: f.fc == 3, "silent")
    with pytest.raises(ModbusIOError):
        run(lambda: rig.dev.read_holding(0, 2))
    assert rig.dev.is_connected is False
    assert len(server.frames()) == 1


def test_a08_normal_read_and_write_unchanged(server: LoopbackServer) -> None:
    rig = _Device(server.port)
    assert run(lambda: rig.dev.write_register(5, 42)) is True
    assert run(lambda: rig.dev.write_registers(6, [43, 44])) is True
    assert run(lambda: rig.dev.write_coil(30, True)) is True
    assert run(lambda: rig.dev.transaction([("w", 8, 45)])) is True
    assert run(lambda: rig.dev.read_holding(5, 4)) == [42, 43, 44, 45]
    assert run(lambda: rig.dev.read_coils(30, 1)) == [True]
    assert rig.dev.is_connected is True
    assert rig.errors == []
    assert server.accepted == 1


@pytest.mark.parametrize("op", ["read", "write"])
def test_a08_error_reply_keeps_old_behaviour_and_socket(server: LoopbackServer, op: str) -> None:
    rig = _Device(server.port)
    server.on_next(lambda f: True, "exc")
    with pytest.raises(ModbusIOError):
        if op == "read":
            run(lambda: rig.dev.read_holding(0, 2))
        else:
            run(lambda: rig.dev.write_register(5, 1))
    assert rig.dev.is_connected is False
    assert rig.status("reads_err") == (1 if op == "read" else 0)
    assert rig.status("writes_err") == (1 if op == "write" else 0)
    assert len(rig.errors) == 1
    assert run(rig.dev.connect) is True
    assert run(lambda: rig.dev.read_holding(0, 2)) == [11, 22]
    assert server.accepted == 1  # ответ isError() сокет не закрывает


# --------------------------------------------------------------------------------------------------
# A9: сеанс
# --------------------------------------------------------------------------------------------------


def test_a09_session_grows_on_error_and_on_successful_connect(server: LoopbackServer) -> None:
    rig = _Device(server.port)
    s0 = rig.dev.session
    assert isinstance(s0, int)
    server.on_next(lambda f: f.fc == 3, "exc")
    with pytest.raises(ModbusIOError):
        run(lambda: rig.dev.read_holding(0, 1))
    s1 = rig.dev.session
    assert s1 > s0, "session не вырос после ошибки"
    assert run(rig.dev.connect) is True
    s2 = rig.dev.session
    assert s2 > s1, "session не вырос после удачного connect() после ошибки"
    assert run(rig.dev.connect) is True
    assert rig.dev.session > s2, "session не вырос после удачного connect() без ошибки"


@pytest.mark.parametrize("cause", ["connect", "error"])
@pytest.mark.parametrize("op", sorted(_WRITES))
def test_a09_stale_session_write_is_refused_without_frames(server: LoopbackServer, op: str, cause: str) -> None:
    rig = _Device(server.port)
    stale = rig.dev.session
    if cause == "connect":
        assert run(rig.dev.connect) is True
    else:
        _drop_by_read(server, rig.dev, "fin")
    errors_before = len(rig.errors)
    writes_err_before = rig.status("writes_err")
    mark = server.mark()
    with pytest.raises(ModbusConnectionError):
        run(lambda: _WRITES[op](rig.dev, 50, expected_session=stale))
    time.sleep(0.2)
    assert server.writes(mark) == []
    assert rig.status("writes_err") == writes_err_before
    assert len(rig.errors) == errors_before

    # парная проверка: свежее значение и запись без expected_session проходят и видны серверу
    if cause == "error":
        assert run(rig.dev.connect) is True
    mark = server.mark()
    assert run(lambda: _WRITES[op](rig.dev, 60, expected_session=rig.dev.session)) is True
    assert run(lambda: _WRITES[op](rig.dev, 70)) is True
    addrs = [f.addr for f in server.writes(mark)]
    assert addrs == ([60, 61, 70, 71] if op == "transaction" else [60, 70])


# --------------------------------------------------------------------------------------------------
# A10: поток, ждавший замок в момент обрыва
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["fin", "rst"])
@pytest.mark.parametrize("op", sorted(_WRITES))
def test_a10_waiting_writer_with_old_session_is_refused(server: LoopbackServer, op: str, kind: str) -> None:
    rig = _Device(server.port, timeout_sec=10.0)
    held = server.on_next(lambda f: f.addr == 900, kind, hold=True)
    a = Call(lambda: rig.dev.read_holding(900, 1))
    assert held.entered.wait(5.0), "чтение A не дошло до сервера"
    session = rig.dev.session if hasattr(rig.dev, "session") else None
    assert session is not None, "у ModbusDevice нет session"
    b = Call(lambda: _WRITES[op](rig.dev, 100, expected_session=session))
    c = Call(lambda: rig.dev.transaction([("w", 200, 5), ("w", 201, 6)]))
    time.sleep(0.4)
    assert b.alive() and c.alive(), "B и C обязаны ждать замок, пока A висит"
    held.release.set()
    a.join()
    b.join()
    c.join()
    assert isinstance(a.exc, ModbusIOError), f"A: {a.exc!r}"
    assert isinstance(b.exc, ModbusConnectionError), f"B: {b.exc!r} / {b.value!r}"
    assert c.exc is None, f"серия без expected_session не ушла: {c.exc!r}"
    time.sleep(0.2)
    assert [f.addr for f in server.writes()] == [200, 201]
    assert [f.conn for f in server.writes()] == [2, 2]
