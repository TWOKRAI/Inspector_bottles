"""Минимальный Modbus-TCP slave-сервер для теста/симуляции приёма.

Назначение: `Services.modbus` сам по себе — только master/client (умеет писать в
регистры). Чтобы в demo-пайплайне увидеть, что реально приходит по шине, нужен
встречный slave. Этот модуль поднимает локальный Modbus-TCP сервер, который при
каждой записи в holding-регистры печатает её в терминал::

    [16:21:07] recv holding[100..102] = [640, 480, 1234]

Хук логирования — ``trace_pdu`` callback сервера (``trace_write``). В pymodbus 3.13
datastore переписан на SimData: старый приём «override ``DataBlock.setValues``»
сервером не вызывается, а ``trace_pdu`` получает каждый входящий PDU и работает
независимо от способа хранения.

Хранилище — нативный ``SimData``/``SimDevice`` (поддерживаемый путь 3.13; классический
``ModbusServerContext`` помечен deprecated). Общий REGISTERS-блок 0..size-1 принимает
запись в holding-регистры, поэтому мастер получает корректный ACK (writes_ok).

Graceful degradation (как в ``sdk/client.py``): модуль импортируется даже без
установленной pymodbus (``MODBUS_AVAILABLE = False``); реальная ошибка возникает
только при попытке запустить сервер.
"""

from __future__ import annotations

import datetime as _dt

from Services.modbus.sdk.errors import ModbusNotAvailableError

# --------------------------------------------------------------------------- #
# Graceful import pymodbus (server + simulator-datastore)
# --------------------------------------------------------------------------- #
try:
    from pymodbus.server import StartTcpServer  # type: ignore
    from pymodbus.simulator import DataType, SimData, SimDevice  # type: ignore

    MODBUS_AVAILABLE = True
except ImportError:  # pragma: no cover — окружение без pymodbus
    DataType = None  # type: ignore
    SimData = None  # type: ignore
    SimDevice = None  # type: ignore
    StartTcpServer = None  # type: ignore
    MODBUS_AVAILABLE = False

# Function-коды записи holding-регистров: FC=06 (один), FC=16 (несколько).
_WRITE_FCS = (6, 16)


def _ts() -> str:
    """Время HH:MM:SS для лога приёма."""
    return _dt.datetime.now().strftime("%H:%M:%S")


def format_recv(address: int, values: list[int], *, ts: str | None = None) -> str:
    """Собрать строку лога входящей записи (чистая функция — тестируема без pymodbus).

    Пример: ``[16:21:07] recv holding[100..102] = [640, 480, 1234]``.
    """
    vals = list(values)
    end = address + len(vals) - 1
    return f"[{ts or _ts()}] recv holding[{address}..{end}] = {vals}"


def trace_write(sending, pdu, *, emit=print):
    """``trace_pdu``-callback: печатает входящие записи в holding-регистры.

    Сервер зовёт ``trace_pdu(sending, pdu)`` на каждый PDU в обе стороны. Логируем
    только входящие (``sending is False``) write-запросы (FC 6/16). Это фильтр —
    обязан вернуть ``pdu`` без изменений.
    """
    if not sending and getattr(pdu, "function_code", None) in _WRITE_FCS:
        regs = list(getattr(pdu, "registers", None) or [])
        if regs:
            emit(format_recv(getattr(pdu, "address", 0), regs))
    return pdu


def run_test_server(
    host: str = "127.0.0.1",
    port: int = 5020,
    unit_id: int = 1,
    size: int = 300,
) -> None:
    """Поднять блокирующий Modbus-TCP slave с логированием записей.

    Блокирует поток до Ctrl+C. ``unit_id`` — id ведомого (мастер должен писать на тот
    же id). Holding-регистры адресуются ``0..size-1`` — пишите по адресам в этом
    диапазоне (дефолт плагина: base_address=100).
    """
    if not MODBUS_AVAILABLE:
        raise ModbusNotAvailableError("pymodbus не установлен — установите extra: pip install '.[modbus]'")

    # Общий REGISTERS-блок 0..size-1: запись в holding-регистры успешно
    # подтверждается (мастер видит writes_ok). id совпадает с unit_id мастера.
    block = SimData(address=0, count=size, values=0, datatype=DataType.REGISTERS)
    device = SimDevice(id=unit_id, simdata=[block])

    print(
        f"Modbus-slave слушает {host}:{port} (unit {unit_id}); holding[0..{size - 1}]. Ctrl+C — выход.",
        flush=True,
    )
    try:
        StartTcpServer(context=device, address=(host, port), trace_pdu=trace_write)
    except KeyboardInterrupt:  # pragma: no cover — ручная остановка
        print("\nОстановлено.", flush=True)
