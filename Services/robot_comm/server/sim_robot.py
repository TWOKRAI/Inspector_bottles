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

import asyncio
import socket
import sys
import threading
import time
import traceback
from typing import Callable

from Services.modbus.sdk.errors import ModbusNotAvailableError

from Services.robot_comm.core.registers import REG_SPACE_SIZE, ROBOT_UNIT_ID
from Services.robot_comm.server.sim_core import TICK_INTERVAL_S, RobotSimCore

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
# TICK_INTERVAL_S — реэкспорт из sim_core.py (ревью Task 2.1, п.3: раньше
# дублировалось здесь отдельной константой; sim_core.py — источник истины,
# этот модуль и так импортирует RobotSimCore из него).
#: Сколько раз печатать сбой наблюдателя обмена, прежде чем замолчать (не спамить в цикле).
_OBSERVER_ERROR_LIMIT = 3
# ponytail: потолок измеренного dt тикера — пауза процесса (GC, swap, отладчик)
# не должна превращаться в прыжок ленты на всю длительность паузы; апгрейд —
# докатка суб-шагами, если когда-нибудь понадобится плавность вместо просто
# «не проскочить».
_MAX_TICK_DT_S = 0.1

# Task 5.4 (fault.drop): сколько ждать, пока свежий слушатель НАЧНЁТ принимать TCP-
# соединения, прежде чем start_listener() вернёт управление. Значение специально
# МЕНЬШЕ внешнего join-бюджета fault.clear/shutdown (<=1с, см. Plugins/sim/robot_host/
# plugin.py) — если бинд аномально завис, start_listener() обязан сдаться и поднять
# исключение ДО того, как внешний join истечёт молча (иначе гонка: fault.clear()
# закрывает listener ДО того, как pymodbus успел выставить active_server внутри
# своего потока — см. TRAPS брифа Task 5.4).
_LISTENER_READY_TIMEOUT_S = 0.5


def _make_register_binder(
    core: RobotSimCore,
    bound_event: threading.Event,
    on_write: Callable[[int, int, list[int] | None], None] | None = None,
    delay_source: Callable[[], float] | None = None,
):
    """action-хук SimDevice: захватить живой список регистров сервера.

    Вызывается сервером на КАЖДЫЙ доступ (до применения операции). Задачи три:
    на первом вызове отдать ядру живое хранилище, если задан ``on_write`` —
    отдать наблюдателю сырой доступ (``values=None`` для чтений), и если задан
    ``delay_source`` (Task 5.4, ``fault.delay_ms``) — задержать ОТВЕТ на
    ``delay_source()`` секунд. Хук зовётся ДО применения операции, поэтому в
    ``values`` лежат ЕЩЁ НЕ записанные значения: именно они и нужны монитору
    (в ``registers`` пока старое).
    pymodbus валидирует ``action=`` как async-ФУНКЦИЮ (инстанс с async
    ``__call__`` не проходит) — поэтому замыкание, а не класс.

    ``await asyncio.sleep(delay)`` (не ``time.sleep``!) — pymodbus 3.15 ждёт
    хук через ``await`` (``pymodbus/simulator/simruntime.py:60-62``), поэтому
    неблокирующий sleep держит ответ ЭТОМУ клиенту, не мешая event loop'у
    сервера обслуживать другие соединения параллельно (DESIGN п.2 брифа
    Task 5.4).

    Фикс-раунд ревью (R1, MAJOR) — задержка идёт ПЕРВОЙ, до attach/on_write,
    НЕ последней. Повтор бага: биндер ``await``-ит ``asyncio.sleep`` ПОСЛЕ
    ``on_write`` (счёт журнала уже произошёл), потом ``fault.drop`` рвёт
    соединение ``ServerStop()`` — pymodbus отменяет (``CancelledError``)
    зависшую в ``sleep`` корутину биндера ПОСЛЕ того, как ``on_write`` уже
    отработал, но САМА запись в регистры (pymodbus применяет её уже ПОСЛЕ
    возврата из ``action``) так и не случилась — клиент, не получив ответ,
    переподключается и шлёт ЭТУ ЖЕ команду повторно, журнал видит ДВЕ записи
    на одно логическое задание (ложный dup: воспроизведено ревьюером —
    ``delay_ms=1500``, запись JOB_FLAG, ``fault.drop`` через 0.3с внутрь
    задержки, повтор записи после восстановления -> было
    ``{'jobs': 2, 'dups': 1}`` вместо ``{'jobs': 1, 'dups': 0}``). Задержка
    ПЕРВОЙ чинит это: отменённая на полпути корутина не успевает дойти ни до
    ``attach``, ни до ``on_write`` — при обрыве ни один наблюдатель не видит
    "недошедшую" попытку, её видит только УСПЕШНЫЙ повтор.
    """
    observer_errors = 0

    async def binder(fc, _start, addr, _count, registers, values):
        nonlocal observer_errors
        if delay_source is not None:
            delay = delay_source()
            if delay > 0:
                await asyncio.sleep(delay)
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
        #: Task 5.4 (``fault.delay_ms``) — сек. задержки ответа на КАЖДЫЙ Modbus-доступ,
        #: читается ``_make_register_binder`` на каждый вызов (``lambda: self.delay_ms/1000``
        #: в :meth:`_serve`) — смена значения НЕ требует рестарта слушателя.
        self.delay_ms: int = 0
        self._bound = threading.Event()
        self._stop = threading.Event()
        self._server_thread: threading.Thread | None = None
        self._ticker_thread: threading.Thread | None = None

    # ------------------------------------------------------------------ #

    def start(self) -> None:
        """Поднять Motion-ticker и слушателя в фоновых потоках.

        Фикс-раунд ревью (K3) — ``ready_timeout=5.0`` (не дефолтные 0.5с
        ``start_listener()``): обычный подъём процесса не должен зависеть от
        того же тесного бюджета, что рассчитан на fault.drop-восстановление
        (см. ``_LISTENER_READY_TIMEOUT_S``)."""
        self._ticker_thread = threading.Thread(target=self._ticker, name="sim-robot-motion", daemon=True)
        self._ticker_thread.start()
        self.start_listener(ready_timeout=5.0)

    def stop(self) -> None:
        """Остановить ticker и слушателя (симметрично ``start()``)."""
        self._stop.set()
        if self._ticker_thread is not None:
            self._ticker_thread.join(timeout=2.0)
        self.stop_listener()

    # ------------------------------------------------------------------ #
    # Task 5.4: слушатель отдельно от тикера — fault.drop рвёт ТОЛЬКО связь,
    # робот (тикер/ядро) продолжает жить. См. докстринг модуля и брифа Task 5.4.
    # ------------------------------------------------------------------ #

    def stop_listener(self) -> None:
        """Остановить ТОЛЬКО TCP-слушателя. Тикер не трогаем — ``fault.drop`` это
        обрыв СВЯЗИ, не перезагрузка робота. Безопасно звать, когда слушатель уже
        не поднят (``ServerStop()`` бросает ``RuntimeError`` «not running» —
        глотаем, как и раньше в ``stop()``)."""
        try:
            ServerStop()
        except Exception:  # pragma: no cover - сервер мог не подняться / уже остановлен
            pass
        if self._server_thread is not None:
            self._server_thread.join(timeout=2.0)
            self._server_thread = None

    def start_listener(self, *, ready_timeout: float = _LISTENER_READY_TIMEOUT_S) -> None:
        """Поднять слушателя заново (порт освобождён ``stop_listener()``).

        ``self._bound`` сбрасывается — новый ``SimDevice`` получит свежий пустой
        список регистров, и ПЕРВЫЙ же запрос клиента заново вызовет
        ``core.attach(...)``, который скопирует ЖИВОЕ состояние ядра (тикер её
        не останавливал) в этот новый список — так состояние переживает drop.

        Ждём (не дольше ``ready_timeout``), пока порт начнёт принимать TCP —
        иначе вызывающий (например ``fault.clear``/``shutdown``), позвав
        ``stop_listener()`` сразу следом, рисковал бы застать pymodbus ДО того,
        как тот выставил ``active_server`` внутри своего потока — ``ServerStop()``
        бросила бы «not running», листенер остался бы висеть в фоне (TRAPS
        брифа Task 5.4). Ожидание — обычный TCP-коннект+закрытие, Modbus PDU не
        шлём, поэтому пробное подключение НЕ триггерит ``core.attach``.
        """
        self._bound.clear()
        server_thread = threading.Thread(target=self._serve, name="sim-robot-server", daemon=True)
        self._server_thread = server_thread
        server_thread.start()
        deadline = time.monotonic() + ready_timeout
        while time.monotonic() < deadline:
            # Фикс-раунд ревью (K2) — если НАШ поток уже умер (bind провалился,
            # исключение внутри _serve/StartTcpServer), успешный TCP-коннект
            # ниже мог бы быть к ЧУЖОМУ листенеру, случайно занявшему тот же
            # порт (например соседний тестовый процесс) — это НЕ наш сервер,
            # объявлять готовность на основании такого коннекта нельзя.
            if not server_thread.is_alive():
                raise RuntimeError(f"sim_robot: поток слушателя умер во время подъёма на {self.host}:{self.port}")
            probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                probe.settimeout(max(0.05, deadline - time.monotonic()))
                probe.connect((self.host, self.port))
            except OSError:
                time.sleep(0.02)
                continue
            finally:
                probe.close()
            return
        raise RuntimeError(f"sim_robot: слушатель не поднялся на {self.host}:{self.port} за {ready_timeout}с")

    # ------------------------------------------------------------------ #

    def _serve(self) -> None:
        block = SimData(address=0, count=REG_SPACE_SIZE, values=0, datatype=DataType.REGISTERS)
        device = SimDevice(
            id=self.unit_id,
            simdata=[block],
            action=_make_register_binder(
                self.core, self._bound, self._on_write, delay_source=lambda: self.delay_ms / 1000.0
            ),
        )
        StartTcpServer(context=device, address=(self.host, self.port))

    def _ticker(self) -> None:
        """Motion-цикл: тикать ядро. До привязки хранилища ядро тикает свой буфер,
        состояние переносится в живой список при attach (первый запрос клиента).

        Скорость ленты идёт по РЕАЛЬНОМУ времени (Task 2.1b, line-sim Ф2):
        `time.sleep(interval)` не гарантирует ровно `interval` — ОС планирует
        поток позже (замерено на macOS, 2026-09-21: 11.6-12.0 мс без нагрузки,
        ~20 мс при соседнем потоке, держащем GIL — не абсолютная величина,
        конкретный запуск), из-за чего лента при фиксированном
        dt=TICK_INTERVAL_S ехала медленнее команды. Первый тик — по
        `TICK_INTERVAL_S` (не с чего измерять интервал); дальше `dt` —
        фактически прошедшее с прошлого тика время (`time.perf_counter()` —
        точнее `monotonic()` на Windows/Python 3.12, где у `monotonic()`
        гранулярность ~15.6мс), зажатое `_MAX_TICK_DT_S`: пауза процесса
        (GC, отладчик, свап) не должна прыжком доехать ленту на всю свою
        длительность.
        """
        last = time.perf_counter()
        self.core.tick(TICK_INTERVAL_S)
        while not self._stop.is_set():
            time.sleep(self._tick_interval)
            now = time.perf_counter()
            dt = min(now - last, _MAX_TICK_DT_S)
            last = now
            self.core.tick(dt)


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
