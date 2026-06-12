"""Тонкая обёртка над pymodbus (sync-клиент), транспорт-агностичная.

Назначение слоя ``sdk``:
- изолировать остальной код от деталей pymodbus (имена аргументов, типы ответов);
- graceful degradation — пакет импортируется даже без установленной pymodbus
  (``MODBUS_AVAILABLE = False``), реальная ошибка возникает только при connect();
- единый перевод низкоуровневых исключений pymodbus в ModbusDriverError.

Совместимость версий: в pymodbus 3.7+ адрес ведомого передаётся как ``device_id=``,
в более ранних 3.x — как ``slave=``/``unit=``. Обёртка пробует ``device_id`` и при
``TypeError`` откатывается на ``slave``.
"""

from __future__ import annotations

import os
import socket
from typing import Any

from loguru import logger

from Services.modbus.core.config import ModbusConfig, TransportType
from Services.modbus.sdk.errors import (
    ModbusConnectionError,
    ModbusIOError,
    ModbusNotAvailableError,
)

# Подробное wire-логирование УСПЕШНЫХ чтений (телеметрия каждые 0.5 с заливает
# консоль). По умолчанию — DEBUG (тихо); MODBUS_WIRE_LOG=1 → INFO (видно RX).
# Записи-команды, ошибки и connect логируются всегда (INFO/WARNING).
_WIRE_READ_VERBOSE = bool(os.environ.get("MODBUS_WIRE_LOG"))

# --------------------------------------------------------------------------- #
# Graceful import pymodbus
# --------------------------------------------------------------------------- #
try:
    from pymodbus.client import ModbusSerialClient, ModbusTcpClient  # type: ignore
    from pymodbus.exceptions import ModbusException  # type: ignore

    MODBUS_AVAILABLE = True
except ImportError:  # pragma: no cover - окружение без pymodbus
    ModbusTcpClient = None  # type: ignore
    ModbusSerialClient = None  # type: ignore
    ModbusException = Exception  # type: ignore
    MODBUS_AVAILABLE = False


def _fmt_addr(args: tuple) -> str:
    """Адрес (первый позиционный аргумент) в hex для лога."""
    if args and isinstance(args[0], int):
        return f"0x{args[0]:04X}"
    return "?"


class ModbusSdkClient:
    """Обёртка над sync-клиентом pymodbus.

    Создаёт нужный транспорт (TCP/RTU) из ModbusConfig и предоставляет
    единообразные методы чтения/записи, возвращающие чистые list[int]/list[bool].
    Не thread-safe сам по себе — синхронизацию обеспечивает ModbusDevice.
    """

    def __init__(self, config: ModbusConfig) -> None:
        self._cfg = config
        self._client: Any | None = None

    # ------------------------------------------------------------------ #
    # Управление соединением
    # ------------------------------------------------------------------ #

    def _build_client(self) -> Any:
        """Сконструировать pymodbus-клиент по конфигу."""
        if not MODBUS_AVAILABLE:
            raise ModbusNotAvailableError("pymodbus не установлен — установите extra: pip install '.[modbus]'")
        cfg = self._cfg
        if cfg.transport is TransportType.TCP:
            return ModbusTcpClient(
                host=cfg.host,
                port=cfg.port,
                timeout=cfg.timeout_sec,
                retries=cfg.retries,
            )
        return ModbusSerialClient(
            port=cfg.serial_port,
            baudrate=cfg.baudrate,
            parity=cfg.parity,
            stopbits=cfg.stopbits,
            bytesize=cfg.bytesize,
            timeout=cfg.timeout_sec,
            retries=cfg.retries,
        )

    def connect(self) -> bool:
        """Установить соединение. Бросает ModbusConnectionError при неудаче."""
        if self._client is None:
            self._client = self._build_client()
        logger.info(f"[MODBUS] connect → {self._cfg.describe()} (unit={self._cfg.unit_id})")
        try:
            ok = bool(self._client.connect())
        except ModbusException as exc:  # pragma: no cover - сетевые сбои
            logger.warning(f"[MODBUS] connect FAILED {self._cfg.describe()}: {exc}")
            raise ModbusConnectionError(str(exc)) from exc
        if not ok:
            logger.warning(f"[MODBUS] connect FAILED {self._cfg.describe()} (unit={self._cfg.unit_id})")
            raise ModbusConnectionError(f"Не удалось подключиться к {self._cfg.describe()}")
        logger.info(f"[MODBUS] connected {self._cfg.describe()} (unit={self._cfg.unit_id})")
        if self._cfg.transport is TransportType.TCP and self._cfg.tcp_nodelay:
            self._enable_nodelay()
        return True

    def _enable_nodelay(self) -> None:
        """Выставить TCP_NODELAY на сокете клиента (best-effort).

        Алгоритм Нейгла буферизует мелкие пакеты — для register-протоколов это
        периодические всплески латентности ~40 мс. Сокет pymodbus — приватная
        деталь, поэтому доступ через getattr и молчаливый пропуск при отказе.
        """
        sock = getattr(self._client, "socket", None)
        if sock is None:
            return
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:  # pragma: no cover - зависит от платформы/сокета
            pass

    def close(self) -> None:
        """Закрыть соединение (идемпотентно)."""
        if self._client is not None:
            try:
                self._client.close()
            finally:
                self._client = None

    @property
    def connected(self) -> bool:
        """Состояние соединения по данным pymodbus."""
        return bool(self._client is not None and getattr(self._client, "connected", False))

    # ------------------------------------------------------------------ #
    # Низкоуровневый вызов с откатом device_id -> slave
    # ------------------------------------------------------------------ #

    def _call(self, method_name: str, *args: Any, **kwargs: Any) -> Any:
        """Вызвать метод клиента, подставив адрес ведомого совместимым способом.

        Wire-логирование (что отправилось / что принялось) — для диагностики
        связи. Уровень INFO, тег ``[MODBUS host#uN]``; ошибки — WARNING с unit
        (типичная причина «нет ответа» — неверный unit_id: робот Delta = 2).
        """
        if self._client is None:
            raise ModbusConnectionError("Клиент не подключён")
        method = getattr(self._client, method_name)
        unit = self._cfg.unit_id
        tag = f"{self._cfg.host}#u{unit}"
        addr = _fmt_addr(args)
        is_read = method_name.startswith("read")
        # Записи (команды) — всегда INFO; чтения (телеметрия) — DEBUG, либо INFO
        # при MODBUS_WIRE_LOG=1 (чтобы не заливать консоль поллингом).
        read_log = logger.info if _WIRE_READ_VERBOSE else logger.debug
        # TX: что отправилось
        if is_read:
            count = kwargs.get("count", args[1] if len(args) > 1 else 1)
            read_log(f"[MODBUS {tag}] TX {method_name} @{addr} count={count}")
        else:
            payload = args[1] if len(args) > 1 else kwargs.get("values", kwargs.get("value"))
            logger.info(f"[MODBUS {tag}] TX {method_name} @{addr} = {payload}")
        try:
            result = method(*args, device_id=unit, **kwargs)
        except TypeError:
            # Старые версии pymodbus: device_id отсутствует -> slave
            result = method(*args, slave=unit, **kwargs)
        if result is None or result.isError():
            logger.warning(f"[MODBUS {tag}] ERR {method_name} @{addr} unit={unit} → {result!r}")
            raise ModbusIOError(f"{method_name} -> ошибка устройства: {result}")
        # RX: что принялось
        rx = getattr(result, "registers", None)
        if rx is None:
            rx = getattr(result, "bits", None)
        if is_read:
            read_log(f"[MODBUS {tag}] RX {method_name} @{addr} → {rx}")
        else:
            logger.info(f"[MODBUS {tag}] RX {method_name} @{addr} → ok")
        return result

    # ------------------------------------------------------------------ #
    # Чтение
    # ------------------------------------------------------------------ #

    def read_holding(self, address: int, count: int) -> list[int]:
        """Читать holding-регистры (FC=03)."""
        return list(self._call("read_holding_registers", address, count=count).registers)

    def read_input(self, address: int, count: int) -> list[int]:
        """Читать input-регистры (FC=04)."""
        return list(self._call("read_input_registers", address, count=count).registers)

    def read_coils(self, address: int, count: int) -> list[bool]:
        """Читать coils (FC=01)."""
        return list(self._call("read_coils", address, count=count).bits)[:count]

    def read_discrete_inputs(self, address: int, count: int) -> list[bool]:
        """Читать discrete inputs (FC=02)."""
        return list(self._call("read_discrete_inputs", address, count=count).bits)[:count]

    # ------------------------------------------------------------------ #
    # Запись
    # ------------------------------------------------------------------ #

    def write_register(self, address: int, value: int) -> None:
        """Записать один holding-регистр (FC=06)."""
        self._call("write_register", address, value)

    def write_registers(self, address: int, values: list[int]) -> None:
        """Записать несколько holding-регистров (FC=16)."""
        self._call("write_registers", address, list(values))

    def write_coil(self, address: int, value: bool) -> None:
        """Записать один coil (FC=05)."""
        self._call("write_coil", address, bool(value))
