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

import sys
import threading
import time
import traceback
from typing import Callable

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
#: Сколько раз печатать сбой наблюдателя обмена, прежде чем замолчать (не спамить в цикле).
_OBSERVER_ERROR_LIMIT = 3


def _make_register_binder(
    core: RobotSimCore,
    bound_event: threading.Event,
    on_write: Callable[[int, int, list[int] | None], None] | None = None,
):
    """action-хук SimDevice: захватить живой список регистров сервера.

    Вызывается сервером на КАЖДЫЙ доступ (до применения операции). Задачи две:
    на первом вызове отдать ядру живое хранилище, и — если задан ``on_write`` —
    отдать наблюдателю сырой доступ (``values=None`` для чтений). Хук зовётся ДО
    применения операции, поэтому в ``values`` лежат ЕЩЁ НЕ записанные значения:
    именно они и нужны монитору (в ``registers`` пока старое).
    pymodbus валидирует ``action=`` как async-ФУНКЦИЮ (инстанс с async
    ``__call__`` не проходит) — поэтому замыкание, а не класс.
    """
    observer_errors = 0

    async def binder(fc, _start, addr, _count, registers, values):
        nonlocal observer_errors
        if not bound_event.is_set():
            core.attach(registers)
            bound_event.set()
        if on_write is not None:
            try:
                on_write(int(fc), int(addr), None if values is None else [int(v) for v in values])
            except Exception:  # наблюдатель не имеет права ронять симулятор...
                observer_errors += 1
                if observer_errors <= _OBSERVER_ERROR_LIMIT:  # ...но и молчать не должен
                    print(f"sim_robot: сбой наблюдателя обмена #{observer_errors}:", file=sys.stderr)
                    traceback.print_exc()
        return None  # продолжить штатную обработку

    return binder


class SimRobotServer:
    """Управляемый TCP-симулятор робота (для тестов: start/stop).

    Args:
        host/port/unit_id: адрес слушателя и Modbus id робота.
        core:          Внешнее ядро (настроенные тайминги) или дефолтное.
        tick_interval: Период Motion-цикла, сек.
        on_write:      Наблюдатель обмена ``(func_code, address, values|None)``;
                       ``None`` у values = чтение. Для монитора (см. sim_journal).
    """

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        unit_id: int = ROBOT_UNIT_ID,
        *,
        core: RobotSimCore | None = None,
        tick_interval: float = TICK_INTERVAL_S,
        on_write: Callable[[int, int, list[int] | None], None] | None = None,
    ) -> None:
        if not MODBUS_AVAILABLE:
            raise ModbusNotAvailableError("pymodbus не установлен — установите extra: pip install '.[modbus]'")
        self.host, self.port, self.unit_id = host, port, unit_id
        self.core = core if core is not None else RobotSimCore()
        self._tick_interval = tick_interval
        self._on_write = on_write
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
            action=_make_register_binder(self.core, self._bound, self._on_write),
        )
        StartTcpServer(context=device, address=(self.host, self.port))

    def _ticker(self) -> None:
        """Motion-цикл: тикать ядро. До привязки хранилища ядро тикает свой буфер,
        состояние переносится в живой список при attach (первый запрос клиента)."""
        while not self._stop.is_set():
            self.core.tick()
            time.sleep(self._tick_interval)


def run_sim_robot(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    unit_id: int = ROBOT_UNIT_ID,
    *,
    core_kwargs: dict | None = None,
    gui: bool = False,
) -> None:
    """Блокирующий запуск симулятора (CLI). Ctrl+C — выход.

    Args:
        core_kwargs: Параметры ``RobotSimCore`` (тайминги, скорость ленты).
        gui:         Поднять окно-монитор обмена (две колонки + счёт дублей).
                     Требует PySide6; журнал слушает и записи с провода, и
                     события ядра.
    """
    journal = None
    sinks = [lambda m: print(m, flush=True)]  # verbose-лог в консоль (зеркало print() прошивки)
    if gui:
        from Services.robot_comm.server.sim_journal import SimJournal

        journal = SimJournal()
        sinks.append(journal.on_event)

    def emit(message: str) -> None:
        for sink in sinks:
            sink(message)

    # flush=True в консольном sink — события видны вживую (без block-буферизации
    # stdout при перенаправлении в файл).
    core = RobotSimCore(on_event=emit, **(core_kwargs or {}))
    server = SimRobotServer(host, port, unit_id, core=core, on_write=journal.on_write if journal else None)
    print(
        f"sim_robot слушает {host}:{port} (unit {unit_id}); карта universal3 "
        f"(CVT + DRAW + MANUAL + RETURN + TOOLCHANGE + зеркало ПЧ). Ctrl+C — выход.",
        flush=True,
    )
    server.start()
    try:
        if journal is not None:
            _run_monitor_window(journal)
        else:
            while True:
                time.sleep(0.5)
    except KeyboardInterrupt:  # pragma: no cover - ручная остановка
        print("\nОстановлено.", flush=True)
    finally:
        server.stop()


def _run_monitor_window(journal) -> None:  # pragma: no cover - требует GUI
    """Показать окно-монитор; блокирует до его закрытия (Qt держит главный поток)."""
    from PySide6.QtWidgets import QApplication

    from Services.robot_comm.server.sim_monitor import SimMonitorWindow

    app = QApplication.instance() or QApplication(sys.argv)
    window = SimMonitorWindow(journal)
    window.show()
    app.exec()
