"""TCP-симулятор робота — фейк Modbus-slave с поведением cvt_universal_full.lua.

Для E2E-тестов и ручной разработки GUI без железа::

    python -m Services.robot_comm.server            # 127.0.0.1:5021, unit 2
    python -m Services.robot_comm.server --port 502

Устройство pymodbus 3.13: классический мутируемый datastore удалён (сервер
принимает только SimDevice), поэтому реактивность реализована через публичный
хук ``SimDevice(action=...)``: первый же запрос клиента отдаёт нам ЖИВОЙ список
регистров сервера (``RobotSimCore.attach``), дальше фоновый ticker-поток
крутит «Motion-цикл» (поллинг флагов mailbox) прямо над этим списком — как
настоящий Lua-скрипт на роботе. Мутация элементов списка из потока безопасна
(GIL), сервер видит изменения немедленно.

Graceful degradation: модуль импортируется без pymodbus; ошибка — при запуске.
"""

from __future__ import annotations

import threading
import time

from Services.modbus.sdk.errors import ModbusNotAvailableError

from Services.robot_comm.core.registers import REG_SPACE_SIZE, ROBOT_UNIT_ID
from Services.robot_comm.server.sim_core import RobotSimCore

try:  # pragma: no cover - наличие pymodbus зависит от окружения
    from pymodbus.server import ServerStop, StartTcpServer
    from pymodbus.simulator import DataType, SimData, SimDevice

    MODBUS_AVAILABLE = True
except ImportError:  # pragma: no cover
    DataType = None  # type: ignore
    SimData = None  # type: ignore
    SimDevice = None  # type: ignore
    ServerStop = None  # type: ignore
    StartTcpServer = None  # type: ignore
    MODBUS_AVAILABLE = False

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5021  # не 5020 — там тестовый slave Services/modbus
TICK_INTERVAL_S = 0.01  # период Motion-цикла симулятора


def _make_register_binder(core: RobotSimCore, bound_event: threading.Event):
    """action-хук SimDevice: захватить живой список регистров сервера.

    Вызывается сервером на КАЖДЫЙ доступ (до применения операции). Единственная
    задача — на первом вызове отдать ядру живое хранилище; дальше no-op.
    pymodbus валидирует ``action=`` как async-ФУНКЦИЮ (инстанс с async
    ``__call__`` не проходит) — поэтому замыкание, а не класс.
    """

    async def binder(_fc, _start, _addr, _count, registers, _values):
        if not bound_event.is_set():
            core.attach(registers)
            bound_event.set()
        return None  # продолжить штатную обработку

    return binder


class SimRobotServer:
    """Управляемый TCP-симулятор робота (для тестов: start/stop).

    Args:
        host/port/unit_id: адрес слушателя и Modbus id робота.
        core:          Внешнее ядро (настроенные тайминги) или дефолтное.
        tick_interval: Период Motion-цикла, сек.
    """

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        unit_id: int = ROBOT_UNIT_ID,
        *,
        core: RobotSimCore | None = None,
        tick_interval: float = TICK_INTERVAL_S,
    ) -> None:
        if not MODBUS_AVAILABLE:
            raise ModbusNotAvailableError("pymodbus не установлен — установите extra: pip install '.[modbus]'")
        self.host, self.port, self.unit_id = host, port, unit_id
        self.core = core if core is not None else RobotSimCore()
        self._tick_interval = tick_interval
        self._bound = threading.Event()
        self._stop = threading.Event()
        self._server_thread: threading.Thread | None = None
        self._ticker_thread: threading.Thread | None = None

    # ------------------------------------------------------------------ #

    def start(self) -> None:
        """Поднять сервер и Motion-ticker в фоновых потоках."""
        self._server_thread = threading.Thread(target=self._serve, name="sim-robot-server", daemon=True)
        self._ticker_thread = threading.Thread(target=self._ticker, name="sim-robot-motion", daemon=True)
        self._server_thread.start()
        self._ticker_thread.start()

    def stop(self) -> None:
        """Остановить ticker и сервер."""
        self._stop.set()
        if self._ticker_thread is not None:
            self._ticker_thread.join(timeout=2.0)
        try:
            ServerStop()
        except Exception:  # pragma: no cover - сервер мог не подняться
            pass
        if self._server_thread is not None:
            self._server_thread.join(timeout=2.0)

    # ------------------------------------------------------------------ #

    def _serve(self) -> None:
        block = SimData(address=0, count=REG_SPACE_SIZE, values=0, datatype=DataType.REGISTERS)
        device = SimDevice(
            id=self.unit_id,
            simdata=[block],
            action=_make_register_binder(self.core, self._bound),
        )
        StartTcpServer(context=device, address=(self.host, self.port))

    def _ticker(self) -> None:
        """Motion-цикл: тикать ядро. До привязки хранилища ядро тикает свой буфер,
        состояние переносится в живой список при attach (первый запрос клиента)."""
        while not self._stop.is_set():
            self.core.tick()
            time.sleep(self._tick_interval)


def run_sim_robot(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, unit_id: int = ROBOT_UNIT_ID) -> None:
    """Блокирующий запуск симулятора (CLI). Ctrl+C — выход."""
    server = SimRobotServer(host, port, unit_id)
    print(
        f"sim_robot слушает {host}:{port} (unit {unit_id}); карта universal3 "
        f"(CVT + рисование + зеркало ПЧ). Ctrl+C — выход.",
        flush=True,
    )
    server._ticker_thread = threading.Thread(target=server._ticker, name="sim-robot-motion", daemon=True)
    server._ticker_thread.start()
    try:
        server._serve()  # блокирует текущий поток
    except KeyboardInterrupt:  # pragma: no cover - ручная остановка
        print("\nОстановлено.", flush=True)
    finally:
        server._stop.set()
