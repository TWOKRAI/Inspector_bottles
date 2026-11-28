"""ModbusDevice — высокоуровневый драйвер одного устройства Modbus.

Объединяет:
- конфиг (ModbusConfig);
- sdk-клиент (ModbusSdkClient, транспорт TCP/RTU);
- state machine + телеметрию (ConnectionState / ModbusStatus);
- thread-safe доступ (один Lock на все операции) — клиент pymodbus не потокобезопасен;
- callbacks on_status / on_error / on_data — «полноценная система»: статусы, ошибки и
  данные уходят наружу через API, а не только значения регистров.

Слой core НЕ зависит от фреймворка — это чистый Python, пригодный для standalone-
использования (см. __main__.py) и для оборачивания плагином/каналом.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

from Services.modbus.core.config import ModbusConfig
from Services.modbus.core.status import ConnectionState, ModbusStatus
from Services.modbus.sdk.client import ModbusSdkClient
from Services.modbus.sdk.errors import ModbusConnectionError, ModbusDriverError

StatusCallback = Callable[[dict[str, Any]], None]
ErrorCallback = Callable[[str], None]
DataCallback = Callable[[dict[str, Any]], None]


class ModbusDevice:
    """Потокобезопасный драйвер устройства Modbus (клиент/master).

    Пример::

        dev = ModbusDevice(ModbusConfig(host="192.168.1.10"))
        dev.connect()
        regs = dev.read_holding(0, 10)
        dev.write_register(0, 42)
        print(dev.get_status())
        dev.disconnect()
    """

    def __init__(
        self,
        config: ModbusConfig,
        *,
        client: ModbusSdkClient | None = None,
        on_status: StatusCallback | None = None,
        on_error: ErrorCallback | None = None,
        on_data: DataCallback | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._cfg = config
        self._client = client if client is not None else ModbusSdkClient(config)
        self._on_status = on_status
        self._on_error = on_error
        self._on_data = on_data
        self._clock = clock
        self._lock = threading.RLock()
        self._status = ModbusStatus()
        #: Номер сеанса связи (см. ``session``); меняется только под ``self._lock``.
        self._session = 0

    # ------------------------------------------------------------------ #
    # Свойства
    # ------------------------------------------------------------------ #

    @property
    def config(self) -> ModbusConfig:
        """Текущий конфиг."""
        return self._cfg

    @property
    def state(self) -> ConnectionState:
        """Текущее состояние соединения."""
        return self._status.state

    @property
    def is_connected(self) -> bool:
        """True, если соединение установлено."""
        return self._status.is_connected

    @property
    def session(self) -> int:
        """Номер сеанса связи: растёт при каждой ошибке и при каждом удачном ``connect()``.

        Вызывающий берёт значение в момент допуска операции и передаёт его в
        запись как ``expected_session``: запись из прежнего сеанса не уйдёт по
        новому соединению. Читается без замка намеренно — допуск не должен ждать,
        пока чужой обмен держит замок.
        """
        return self._session

    def get_status(self) -> dict[str, Any]:
        """Снимок статуса/счётчиков в dict (API наружу)."""
        with self._lock:
            return self._status.to_dict(now=self._clock())

    # ------------------------------------------------------------------ #
    # Управление соединением
    # ------------------------------------------------------------------ #

    def connect(self) -> bool:
        """Подключиться к устройству. Возвращает True при успехе."""
        with self._lock:
            self._set_state(ConnectionState.CONNECTING)
            try:
                self._client.connect()
            except ModbusDriverError as exc:
                self._fail(str(exc))
                return False
            # До колбэков: они уже видят новый сеанс, а их исключение его не отменит.
            self._session += 1
            self._status.connected_since = self._clock()
            self._status.last_error = ""
            self._set_state(ConnectionState.CONNECTED)
            return True

    def disconnect(self) -> None:
        """Штатно закрыть соединение."""
        with self._lock:
            self._client.close()
            self._status.connected_since = None
            self._set_state(ConnectionState.DISCONNECTED)

    def drop_link(self) -> None:
        """Снять связь, не выбрасывая клиента SDK (R2-S1d, ADR-DH-016 device_hub).

        Под замком устройства: сокет закрыт, ``is_connected`` False, ``session`` +1 (запись прежнего сеанса с
        ``expected_session`` получит отказ). Клиент SDK не обнуляется: следующая запись без ``expected_session``
        (STOP) откроет новый TCP неявным connect pymodbus. ``disconnect()`` — намеренное отключение: после него запись
        падает ``ModbusConnectionError`` без кадра. ``on_error`` и счётчики не трогаются; ``on_status`` — как у
        ``disconnect()``. Идемпотентно.
        """
        with self._lock:
            self._client.drop_socket()
            self._session += 1
            self._status.connected_since = None
            self._set_state(ConnectionState.DISCONNECTED)

    # ------------------------------------------------------------------ #
    # Операции чтения (с телеметрией)
    # ------------------------------------------------------------------ #

    def read_holding(self, address: int, count: int = 1) -> list[int]:
        """Читать holding-регистры (FC=03)."""
        return self._read("read_holding", address, count, kind="holding")

    def read_input(self, address: int, count: int = 1) -> list[int]:
        """Читать input-регистры (FC=04)."""
        return self._read("read_input", address, count, kind="input")

    def read_coils(self, address: int, count: int = 1) -> list[bool]:
        """Читать coils (FC=01)."""
        return self._read("read_coils", address, count, kind="coils")

    def read_discrete_inputs(self, address: int, count: int = 1) -> list[bool]:
        """Читать discrete inputs (FC=02)."""
        return self._read("read_discrete_inputs", address, count, kind="discrete")

    def read_registers(self, address: int, count: int = 1) -> list[int]:
        """Читать holding-регистры — alias read_holding (контракт RegisterTransport)."""
        return self.read_holding(address, count)

    # ------------------------------------------------------------------ #
    # Операции записи (с телеметрией)
    # ------------------------------------------------------------------ #

    def write_register(self, address: int, value: int, *, expected_session: int | None = None) -> bool:
        """Записать один holding-регистр (FC=06). ``expected_session`` — см. ``transaction``."""
        return self._write("write_register", address, value, expected_session)

    def write_registers(self, address: int, values: list[int], *, expected_session: int | None = None) -> bool:
        """Записать несколько holding-регистров (FC=16). ``expected_session`` — см. ``transaction``."""
        return self._write("write_registers", address, values, expected_session)

    def write_coil(self, address: int, value: bool, *, expected_session: int | None = None) -> bool:
        """Записать один coil (FC=05). ``expected_session`` — см. ``transaction``."""
        return self._write("write_coil", address, value, expected_session)

    def transaction(self, ops: list[tuple], *, expected_session: int | None = None) -> bool:
        """Серия записей под ОДНИМ Lock — данные первыми, маркер-флаг последним.

        Атомарный примитив mailbox-протоколов (CVT-робот, ПЧ и т.п.): данные и
        маркер «данные готовы» пишутся одной серией, чтобы конкурирующий поток
        (поллер, feeder, GUI-команда) не вклинился между ними.

        Args:
            ops: операции по порядку:
                ``("w", addr, value)``   — один регистр (FC=06);
                ``("wm", addr, [vals])`` — блок регистров (FC=16).
            expected_session: значение ``session``, снятое при допуске операции.
                None — сеанс не проверяется. Не равно текущему (проверка под
                замком, до первого кадра) — серия не отправляется вовсе.

        Returns:
            True — все операции выполнены.

        Raises:
            ModbusConnectionError: сеанс сменился — на провод ничего не ушло,
                счётчики и ``on_error`` не тронуты.
            ModbusDriverError: на ПЕРВОЙ неудавшейся операции — оставшиеся
                (включая маркер) НЕ выполняются. Инвариант: маркер идёт
                последней операцией, поэтому частично записанные данные без
                маркера инертны для устройства. Тихий reconnect/retry внутри
                серии запрещён — он разрывает атомарность.
            ValueError: неизвестный вид операции.
        """
        with self._lock:
            self._check_session("transaction", expected_session)
            for kind, address, value in ops:
                if kind == "w":
                    method = "write_register"
                elif kind == "wm":
                    method = "write_registers"
                else:
                    raise ValueError(f"transaction: неизвестная операция {kind!r} (ожидается 'w' | 'wm')")
                try:
                    getattr(self._client, method)(address, value)
                except ModbusDriverError as exc:
                    self._status.writes_err += 1
                    self._fail(str(exc))
                    raise
                self._status.writes_ok += 1
            self._status.last_op_ts = self._clock()
            self._emit_data({"op": "transaction", "count": len(ops)})
        return True

    # ------------------------------------------------------------------ #
    # Внутреннее
    # ------------------------------------------------------------------ #

    def _read(self, method: str, address: int, count: int, *, kind: str) -> Any:
        with self._lock:
            try:
                result = getattr(self._client, method)(address, count)
            except ModbusDriverError as exc:
                self._status.reads_err += 1
                self._fail(str(exc))
                raise
            self._status.reads_ok += 1
            self._status.last_op_ts = self._clock()
            self._emit_data({"op": method, "kind": kind, "address": address, "values": result})
            return result

    def _write(self, method: str, address: int, value: Any, expected_session: int | None) -> bool:
        with self._lock:
            self._check_session(method, expected_session)
            try:
                getattr(self._client, method)(address, value)
            except ModbusDriverError as exc:
                self._status.writes_err += 1
                self._fail(str(exc))
                raise
            self._status.writes_ok += 1
            self._status.last_op_ts = self._clock()
            self._emit_data({"op": method, "address": address, "value": value})
            return True

    def _check_session(self, operation: str, expected_session: int | None) -> None:
        """Отказать записи из прежнего сеанса. Вызывать только под ``self._lock``.

        Отказ — не обрыв связи: на провод ничего не идёт, счётчики, ``_fail`` и
        ``on_error`` не трогаются.
        """
        if expected_session is not None and expected_session != self._session:
            raise ModbusConnectionError(
                f"{operation}: сеанс связи сменился (был {expected_session}, сейчас {self._session}), "
                "запись не отправлена"
            )

    def _set_state(self, state: ConnectionState) -> None:
        """Сменить состояние и уведомить подписчиков (on_status)."""
        self._status.state = state
        self._emit_status()

    def _fail(self, message: str) -> None:
        """Зафиксировать ошибку: новый сеанс, state=ERROR, last_error, callbacks."""
        # Первым: колбэк с записью прежнего сеанса получит отказ, а не уйдёт на провод.
        self._session += 1
        self._status.last_error = message
        self._status.state = ConnectionState.ERROR
        if self._on_error is not None:
            self._on_error(message)
        self._emit_status()

    def _emit_status(self) -> None:
        if self._on_status is not None:
            self._on_status(self._status.to_dict(now=self._clock()))

    def _emit_data(self, payload: dict[str, Any]) -> None:
        if self._on_data is not None:
            self._on_data(payload)
