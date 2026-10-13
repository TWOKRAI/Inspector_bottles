"""Обвязка e2e «клиент v2 <-> sim v2» в одном процессе (T3.5, plans/robot-protocol-v2).

Purpose:
    Стенд для приёмки: ``SimRobotServer`` над ``RecordingCore`` на свободном порту, настоящие ``ModbusDevice`` и
    ``RobotClientV2`` по TCP. ``RecordingCore`` пишет снимок после каждого тика (``Tick``, время sim) и строки
    событий sim со штампом тика (включён хук ``trace_sc``: ``SC rec`` / ``SC act``). Каждый блокирующий вызов
    идёт под дедлайном (``bounded``) — тест падает, набор не висит.

Public API:
    ``WS_PARAMS``, ``FORBIDDEN_PORTS``, ``free_port``, ``bounded``, ``pulse``, ``Tick``, ``RecordingCore``,
    ``Pending``, ``E2eRig``. Файл без префикса ``test_``: pytest его не собирает; тесты импортируют
    ``from Services.robot_comm.tests.e2e_rig_v2 import ...``. pytest в обвязке не импортируется: ошибки —
    обычные исключения.

Stability: lite

Время sim: ``Tick.t`` — сумма ``dt`` тиков ядра. ``dt`` тикера ``SimRobotServer`` — реальное время, зажатое
0.1 с, поэтому время sim почти равно стенному, но меряется только суммой ``dt``. Исключение тика роняет поток
тикера ``SimRobotServer`` молча — ``RecordingCore`` копит его в ``tick_errors()``, ``E2eRig`` предъявляет.
"""

from __future__ import annotations

import math
import re
import socket
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from types import MappingProxyType, TracebackType
from typing import Any

from Services.modbus.core.config import ModbusConfig
from Services.modbus.core.device import ModbusDevice
from Services.robot_comm.core.client_v2 import ClientV2Config, RobotClientV2, RunReport
from Services.robot_comm.core.protocol_v2 import REG
from Services.robot_comm.core.registers import ROBOT_UNIT_ID
from Services.robot_comm.programs import FrameDef, Scenario, compile_program
from Services.robot_comm.server.sim_core_v2 import TICK_INTERVAL_S, RobotSimCoreV2
from Services.robot_comm.server.sim_robot import SimRobotServer

__all__ = [
    "FORBIDDEN_PORTS",
    "WS_PARAMS",
    "E2eRig",
    "Pending",
    "RecordingCore",
    "Tick",
    "bounded",
    "free_port",
    "pulse",
]

#: Зона и рука, как в приёмке T3.3/T3.4 и умолчаниях sim (мм, °).
WS_PARAMS: Mapping[str, float] = MappingProxyType(
    {
        "P_WS_R_MIN": 100,
        "P_WS_R_MAX": 600,
        "P_WS_Z_MIN": -150,
        "P_WS_Z_MAX": 0,
        "P_WS_RZ_MIN": -360,
        "P_WS_RZ_MAX": 360,
        "P_WS_ANG_MIN": -165,
        "P_WS_ANG_MAX": 165,
        "P_WS_BOX_EN": 0,
        "P_WS_X_MIN": -600,
        "P_WS_X_MAX": 600,
        "P_WS_Y_MIN": -600,
        "P_WS_Y_MAX": 600,
        "P_HAND": 1,
    }
)

#: Порты стенда ``scripts/run_sim_all.ps1`` и прежних тестов: стенд тестов их не занимает.
FORBIDDEN_PORTS: frozenset[int] = frozenset({5021, 8765, 8766, 8091, 8092} | set(range(8860, 8900)))

_HOST = "127.0.0.1"
_MESSAGE_DEADLINE = "bounded: вызов не уложился в дедлайн"
_POLL_S = 0.005


def free_port() -> int:
    """Свободный порт ОС вне ``FORBIDDEN_PORTS``. 20 запрещённых подряд -> ``RuntimeError``."""
    for _ in range(20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind((_HOST, 0))
            port = sock.getsockname()[1]
        if port not in FORBIDDEN_PORTS:
            return port
    raise RuntimeError("free_port: 20 запрещённых портов подряд")


def bounded[T](fn: Callable[[], T], deadline_s: float = 20.0) -> T:
    """Вызвать ``fn()`` в daemon-потоке и ждать не дольше ``deadline_s``.

    Вернул — его значение; бросил — то же исключение (не обёрнутое); не уложился — ``TimeoutError`` с постоянным
    текстом (без входных значений), диагностика — в заметке. Поток не убивается: тест падает, набор не висит.
    """
    box: dict[str, Any] = {}

    def body() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 — исключение вызова уходит вызывающему как есть
            box["exc"] = exc

    thread = threading.Thread(target=body, name="e2e-bounded", daemon=True)
    thread.start()
    thread.join(deadline_s)
    if thread.is_alive():
        timeout = TimeoutError(_MESSAGE_DEADLINE)
        timeout.add_note(f"fn={fn!r} deadline_s={deadline_s}")
        raise timeout
    if "exc" in box:
        raise box["exc"]
    return box["value"]


@dataclass
class PulseStats:
    """Итог фонового вызова ``pulse``: ``count`` — сделано вызовов, ``errors`` — исключения ``fn``."""

    count: int = 0
    errors: list[BaseException] = field(default_factory=list)


@contextmanager
def pulse(fn: Callable[[], object], period_s: float) -> Iterator[PulseStats]:
    """Фоновый daemon-поток зовёт ``fn()`` сразу и затем каждые ``period_s``, пока идёт блок.

    Исключения ``fn`` копятся в ``errors``, поток продолжает. Выход: флаг стопа, ``join(2.0)``; поток жив ->
    ``RuntimeError``. После выхода новых вызовов нет.
    """
    stats = PulseStats()
    stop = threading.Event()

    def body() -> None:
        while True:
            try:
                fn()
            except BaseException as exc:  # noqa: BLE001 — копится, поток продолжает
                stats.errors.append(exc)
            stats.count += 1
            if stop.wait(period_s):
                return

    thread = threading.Thread(target=body, name="e2e-pulse", daemon=True)
    thread.start()
    try:
        yield stats
    finally:
        stop.set()
        thread.join(2.0)
        if thread.is_alive():
            raise RuntimeError("pulse: поток не остановился за 2 с")


@dataclass(frozen=True, slots=True)
class Tick:
    """Снимок регистров ПОСЛЕ тика ядра. ``t`` — время sim в конце тика, с; ``pose`` — ``TLM_X/Y/Z/RZ`` (s16 / 10)."""

    t: float
    dt: float
    pose: tuple[float, float, float, float]
    activity: int
    moving: int
    sc_index: int
    sc_done_n: int
    do_mask: int
    spd_pct: int
    wdg_state: int
    servo: int
    jog_lease: int
    hb_pc: int
    belt_mm_s: float


def _s16(word: int) -> int:
    return word - 0x10000 if word >= 0x8000 else word


class RecordingCore(RobotSimCoreV2):
    """Ядро-осциллограф: снимок после каждого тика, строки событий и словари ``on_job_done`` со штампом тика.

    Хук ``trace_sc`` включён всегда. Событие получает штамп тика, в котором возникло (до первого тика — 0.0).
    Читающие методы возвращают копии под замком. Частные поля ядра не читаются — только ``regs``, ``REG`` и
    ``belt_mm_s``. Исключение тика уходит и в ``tick_errors()``, и дальше (тикер ``SimRobotServer`` его не ловит).
    """

    def __init__(self, regs: list[int] | None = None, **kwargs: Any) -> None:
        # Поля записи — ДО super().__init__: он зовёт _boot(), а тот может породить событие.
        self._rec_lock = threading.Lock()
        self._rec_ticks: list[Tick] = []
        self._rec_events: list[tuple[float, str]] = []
        self._rec_jobs: list[dict] = []
        self._rec_errors: list[BaseException] = []
        self._rec_t = 0.0  # время sim на конце последнего завершённого тика
        self._rec_t_now = 0.0  # время sim на конце тика, который идёт сейчас
        super().__init__(regs, trace_sc=True, on_event=self._record_event, on_job_done=self._record_job, **kwargs)

    def tick(self, dt_s: float | None = None) -> None:
        dt = TICK_INTERVAL_S if dt_s is None else dt_s
        if not (math.isfinite(dt) and dt > 0):
            dt = 0.0  # правило ядра: скачок часов — время не прошло
        self._rec_t_now = self._rec_t + dt
        try:
            super().tick(dt_s)
        except BaseException as exc:
            with self._rec_lock:
                self._rec_errors.append(exc)
            raise
        self._rec_t = self._rec_t_now
        snapshot = self._snapshot(dt)
        with self._rec_lock:
            self._rec_ticks.append(snapshot)

    def _snapshot(self, dt: float) -> Tick:
        regs = self.regs

        def word(name: str) -> int:
            return regs[REG[name]]

        pose = tuple(_s16(word(name)) / 10 for name in ("TLM_X", "TLM_Y", "TLM_Z", "TLM_RZ"))
        return Tick(
            t=self._rec_t,
            dt=dt,
            pose=(pose[0], pose[1], pose[2], pose[3]),
            activity=word("TLM_ACTIVITY"),
            moving=word("TLM_MOVING"),
            sc_index=word("TLM_SC_INDEX"),
            sc_done_n=word("TLM_SC_DONE_N"),
            do_mask=word("TLM_DO_MASK"),
            spd_pct=word("TLM_SPD_PCT"),
            wdg_state=word("TLM_WDG_STATE"),
            servo=word("TLM_SERVO"),
            jog_lease=word("JOG_LEASE"),
            hb_pc=word("HB_PC"),
            belt_mm_s=self.belt_mm_s,
        )

    def _record_event(self, text: str) -> None:
        with self._rec_lock:
            self._rec_events.append((self._rec_t_now, text))

    def _record_job(self, event: dict) -> None:
        with self._rec_lock:
            self._rec_jobs.append(dict(event))

    def ticks(self) -> list[Tick]:
        with self._rec_lock:
            return list(self._rec_ticks)

    def events(self) -> list[tuple[float, str]]:
        with self._rec_lock:
            return list(self._rec_events)

    def jobs(self) -> list[dict]:
        with self._rec_lock:
            return [dict(job) for job in self._rec_jobs]

    def tick_errors(self) -> list[BaseException]:
        with self._rec_lock:
            return list(self._rec_errors)


class Pending:
    """Прогон ``run_chunks`` в daemon-потоке: ``wait(deadline_s)`` — итог или исключение прогона как есть."""

    def __init__(self, fn: Callable[[], RunReport]) -> None:
        self._box: dict[str, Any] = {}

        def body() -> None:
            try:
                self._box["value"] = fn()
            except BaseException as exc:  # noqa: BLE001 — уходит в wait() как есть
                self._box["exc"] = exc

        self._thread = threading.Thread(target=body, name="e2e-run", daemon=True)
        self._thread.start()

    def done(self) -> bool:
        return not self._thread.is_alive()

    def wait(self, deadline_s: float = 30.0) -> RunReport:
        self._thread.join(deadline_s)
        if self._thread.is_alive():
            raise TimeoutError("Pending: прогон не завершился за дедлайн")
        if "exc" in self._box:
            raise self._box["exc"]
        return self._box["value"]


def _tick_error_names(core: RecordingCore) -> str:
    return ", ".join(type(exc).__name__ for exc in core.tick_errors())


class E2eRig:
    """Контекст-менеджер стенда: sim в процессе + настоящие ``ModbusDevice`` и ``RobotClientV2``.

    Поля: ``core``, ``server``, ``device``, ``client``, ``port``. После ``__enter__`` сделаны ``probe()`` и
    ``servo(True)``. Выход предъявляет исключения тика sim (``AssertionError``); сбой подъёма тоже убирает
    стенд (сервер, тикер, порт) до выхода исключения.
    """

    def __init__(self, *, core: RecordingCore | None = None) -> None:
        self.core: RecordingCore = core or RecordingCore()
        self.server: SimRobotServer | None = None
        self.device: ModbusDevice | None = None
        self.client: RobotClientV2 | None = None
        self.port: int = 0

    # --- подъём и выход -------------------------------------------------------------------

    def __enter__(self) -> E2eRig:
        self._start_server()
        try:
            self.device = ModbusDevice(ModbusConfig(host=_HOST, port=self.port, unit_id=ROBOT_UNIT_ID))
            self._connect_device()
            self.client = RobotClientV2(
                self.device,
                # SOFT-эхо приходит только при обрыве на EXACT-точке: на скорости стенда окно до него ~1.1 с,
                # под нагрузкой стоп по стенным часам до 1.67 с — штатные 2.0 с без запаса (ревью р.2).
                ClientV2Config.from_dict({"poll_interval_s": 0.01, "soft_echo_timeout_s": 5.0}),
            )
            bounded(self.client.probe)
            bounded(lambda: self.client.servo(True))
        except BaseException as exc:
            self._cleanup_failed_enter(exc)
            if self.core.tick_errors():
                raise AssertionError(_tick_error_names(self.core)) from exc
            raise
        return self

    def _start_server(self) -> None:
        """До 3 попыток: порт мог занять другой процесс между ``free_port`` и ``start``."""
        last: Exception | None = None
        for _ in range(3):
            self.port = free_port()
            server = SimRobotServer(_HOST, self.port, ROBOT_UNIT_ID, core=self.core)
            try:
                bounded(server.start, 10.0)
            except (RuntimeError, TimeoutError) as exc:  # TimeoutError — start не уложился в дедлайн bounded
                bounded(server.stop, 5.0)  # start() при сбое оставляет тикер живым
                last = exc
                continue
            self.server = server
            return
        assert last is not None
        raise last

    def _cleanup_failed_enter(self, exc: BaseException) -> None:
        """Уборка при сбое ``__enter__`` (``__exit__`` в этом случае не вызывается). Ошибки уборки — заметки."""
        if self.device is not None:
            try:
                self.device.disconnect()
            except Exception as cleanup_exc:  # noqa: BLE001
                exc.add_note(f"cleanup: device.disconnect: {cleanup_exc!r}")
        try:
            bounded(self.server.stop, 5.0)
        except Exception as cleanup_exc:  # noqa: BLE001
            exc.add_note(f"cleanup: server.stop: {cleanup_exc!r}")

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        cleanup_errors: list[str] = []
        failure: Exception | None = None
        try:
            self.device.disconnect()
        except Exception as exc:  # noqa: BLE001 — не подменяет исключение блока и не прячет ошибки тика
            cleanup_errors.append(f"cleanup: device.disconnect: {exc!r}")
            failure = exc
        try:
            bounded(self.server.stop, 5.0)
        except Exception as exc:  # noqa: BLE001
            cleanup_errors.append(f"cleanup: server.stop: {exc!r}")
            failure = failure or exc
        tick_names = _tick_error_names(self.core) if self.core.tick_errors() else ""
        if exc_value is not None:
            for note in cleanup_errors:
                exc_value.add_note(note)
            if tick_names:
                exc_value.add_note(f"tick_errors: {tick_names}")
            return False
        if tick_names:
            error = AssertionError(tick_names)
            for note in cleanup_errors:
                error.add_note(note)
            raise error
        if failure is not None:
            raise failure
        return False

    def _connect_device(self) -> None:
        deadline = time.monotonic() + 5.0
        while not bounded(self.device.connect, 10.0):
            if time.monotonic() >= deadline:
                raise TimeoutError("E2eRig: sim не принял соединение за 5 с")
            time.sleep(0.05)

    # --- прогон сценария ------------------------------------------------------------------

    def compile(self, gp: Any, frames: Mapping[str, FrameDef] | None = None) -> Scenario:
        """``compile_program`` с ``WS_PARAMS`` для ``GeneratedProgram`` (``program`` + ``points``)."""
        return compile_program(gp.program, gp.points, frames or {}, WS_PARAMS)

    def start_run(self, gp_or_scenario: Any, frames: Mapping[str, FrameDef] | None = None) -> Pending:
        """``client.run_chunks`` в daemon-потоке; компиляция — в потоке вызывающего (``CompileError`` сразу)."""
        scenario = gp_or_scenario if isinstance(gp_or_scenario, Scenario) else self.compile(gp_or_scenario, frames)
        return Pending(lambda: self.client.run_chunks(scenario, params=WS_PARAMS))

    def run(
        self, gp_or_scenario: Any, frames: Mapping[str, FrameDef] | None = None, deadline_s: float = 30.0
    ) -> RunReport:
        return self.start_run(gp_or_scenario, frames).wait(deadline_s)

    # --- ожидания и чтение ----------------------------------------------------------------

    def wait_event(self, pattern: str, *, after: int = 0, timeout_s: float = 5.0) -> tuple[int, float, str]:
        """Первая строка события с индексом >= ``after``, где ``re.search(pattern, text)``: (индекс, штамп, текст)."""
        deadline = time.monotonic() + timeout_s
        regex = re.compile(pattern)
        while True:
            events = self.core.events()
            for index in range(after, len(events)):
                stamp, text = events[index]
                if regex.search(text):
                    return index, stamp, text
            if time.monotonic() >= deadline:
                raise TimeoutError(f"wait_event: не дождались строки по шаблону {pattern!r} за {timeout_s} с")
            time.sleep(_POLL_S)

    def wait_tick(self, pred: Callable[[Tick], bool], *, timeout_s: float = 5.0) -> Tick:
        """Первый ``Tick``, для которого ``pred(tick)`` истинно."""
        deadline = time.monotonic() + timeout_s
        seen = 0
        while True:
            ticks = self.core.ticks()
            for tick in ticks[seen:]:
                if pred(tick):
                    return tick
            seen = len(ticks)
            if time.monotonic() >= deadline:
                raise TimeoutError(f"wait_tick: условие не наступило за {timeout_s} с")
            time.sleep(_POLL_S)

    def read(self, name: str, count: int = 1) -> list[int]:
        """Регистры по проводу (``device.read_registers``) с адреса ``REG[name]``."""
        return bounded(lambda: self.device.read_registers(REG[name], count))

    def pose_wire(self) -> tuple[float, float, float, float]:
        """``TLM_X..TLM_RZ`` по проводу, s16 / 10."""
        words = [self.read(name)[0] for name in ("TLM_X", "TLM_Y", "TLM_Z", "TLM_RZ")]
        x, y, z, rz = (_s16(w) / 10 for w in words)
        return (x, y, z, rz)

    # --- рестарт --------------------------------------------------------------------------

    def restart(self, *, keep_regs: bool = True) -> None:
        """Рестарт программы контроллера: новое ядро и новый сервер на ТОМ ЖЕ порту.

        ``keep_regs=True`` — регистры (в них зеркало параметров) переходят в новое ядро. Клиент и
        ``ModbusDevice`` прежние: ``connect()`` и ``probe()`` заново (как у драйвера, T3.1). Порт Windows после
        ``stop()`` освобождается за ~0.3 с — подъём повторяется до 5 с.
        """
        if self.core.tick_errors():  # мёртвый sim молча не перезапускаем: причина тика пропала бы со старым ядром
            raise AssertionError(_tick_error_names(self.core))
        bounded(self.server.stop, 5.0)
        regs = list(self.core.regs) if keep_regs else None
        self.core = RecordingCore(regs=regs)
        deadline = time.monotonic() + 5.0
        while True:
            server = SimRobotServer(_HOST, self.port, ROBOT_UNIT_ID, core=self.core)
            try:
                bounded(server.start, 10.0)
            except (RuntimeError, TimeoutError):
                bounded(server.stop, 5.0)
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.1)
                continue
            self.server = server
            break
        self.device.disconnect()
        self._connect_device()
        bounded(self.client.probe)
