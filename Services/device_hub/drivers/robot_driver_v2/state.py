"""``robot_driver_v2.state`` (T5.3f f2).

Purpose:
    Состояние драйвера робота Delta v2: ``RobotState`` (поля и переходы под одним листовым замком),
    ``RobotStateView`` / ``JogView`` (замороженные срезы), ``_JogRun`` (прогон поводка jog). Внутреннее,
    не SPI хаба.

Stability: lite
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field

from multiprocess_framework.modules.base_manager.interfaces import IHandle

from Services.device_hub.drivers.robot_driver_v2.texts import (
    TEXT_STOPPING,
    TEXT_SYNCING,
    _BUSY_JOB,
    _BUSY_JOG,
    _BUSY_PROGRAM,
    _HOLD_WINDOW_S,
    _NOT_CONNECTED,
)
from Services.robot_comm.core.protocol_v2 import STOP_LEVEL

__all__ = ["JogView", "RobotState", "RobotStateView", "_Job", "_JogRun", "_Place"]


type _Place = tuple[float, float, float, float]


type _Job = tuple[float, float, float, int, _Place | None]


@dataclass
class _JogRun:
    """Один запуск JOG_CONT этого драйвера. Замки полей: ``active``, ``released``, ``stop_requested`` — под замком
    ``RobotState`` (только его переходы); ``handle`` пишет ``jog_hold`` под ``_jog_tx_lock`` (без замка состояния,
    читатели берут снимок); ``stop_sent`` — переходом ``stop_written`` сразу после записи стопа.

    ``active`` — поток поводка ещё не вышел; ``handle`` — запись потока в области (None, пока ``spawn`` не вернулся);
    ``released`` — поводок больше не пишется, поток выходит без своего стопа (стоп шлёт тот, кто поставил флаг:
    ``jog_release`` или стоп процесса);
    ``stop_requested`` — release, истёкшее окно или стоп процесса: стоп этого jog нужен;
    ``stop_sent`` — запись ``STOP_REQ`` для этого jog прошла (ставится сразу после записи, до эха и независимо от
    него). Обычно под ``_jog_tx_lock``; стоп процесса, не взявший замок за остаток срока, пишет без него (В1).
    """

    seq: int
    wake: threading.Event = field(default_factory=threading.Event)
    handle: IHandle | None = None
    active: bool = True
    released: bool = False
    stop_requested: bool = False
    stop_sent: bool = False


@dataclass(frozen=True)
class JogView:
    """Снимок ``_JogRun`` в ``RobotStateView``: ``has_handle`` — запись потока поводка уже есть."""

    seq: int
    active: bool
    released: bool
    stop_requested: bool
    stop_sent: bool
    has_handle: bool


@dataclass(frozen=True)
class RobotStateView:
    """Замороженный снимок ``RobotState``, снят под его замком (``view()``). Внутреннее, не SPI хаба.

    ``has_prog_handle`` — вместо записи потока исполнителя; очереди и ``own_stops`` — кортежи.
    """

    program_active: bool
    has_prog_handle: bool
    job_active: bool
    jog: JogView | None
    jog_starting: bool
    jog_stopping: bool
    last_hold: float
    syncing: bool
    stopping: bool
    shutdown: bool
    stop_level: int
    latch_level: int
    latch_failed: bool
    latch_value: int | None
    latch_attempts: int
    echo_checked: int | None
    stop_unconfirmed: bool
    stop_unconfirmed_text: str | None
    own_stops: tuple[int, ...]
    job_queue: tuple[_Job, ...]
    return_queue: tuple[tuple[float, float, float], ...]
    returns_done: int
    returns_failed: int


class RobotState:
    """Состояние драйвера робота v2 (T5.3f f1): 23 поля и 4 поля текущего ``_JogRun`` под одним замком ``_lock``.

    Внутреннее, не SPI хаба: переходы зовёт только ``RobotDriverV2``; снаружи — ``view()``.

    Каждый переход — одна секция замка состояния на месте прежней секции замка флагов драйвера (правило 1:1):
    порядок проверок прежний, ввода-вывода под замком нет, замок листовой (под ним другие замки не берутся).
    Переход возвращает решение — драйвер действует вне замка. Под замком — только то, что было под ним раньше:
    ``run.wake.set()``, ``ev.is_set()``, часы ``clock``, ``time.monotonic()`` и ``budget()``
    (``next_stop_attempt``, только попытка 2), ``connected()`` (``process_stop_plan``, ``admit_launch``) —
    вызываемые, зовутся в той же ветке, что и раньше.

    Вне состояния: ``_ready`` драйвера (без замка), ``_values`` / ``_epoch`` (владелец ``_param_lock``),
    ``run.handle`` (под ``_jog_tx_lock``), счётчики ``jobs_*``.
    """

    def __init__(self, *, clock: Callable[[], float], queue_maxlen: int) -> None:
        self._lock = threading.Lock()
        self._clock = clock
        self._program_active = False  # исполнитель занят от захвата до конца _program_loop (бывшие _busy, _prog_alive)
        self._prog_handle: IHandle | None = None  # запись потока исполнителя в области
        self._job_active = False  # тик держит задание от захвата до исхода wait_done (R7)
        self._jog: _JogRun | None = None
        self._jog_starting = False  # jog_hold между проверкой флагов и записью jog (Д4)
        self._jog_stopping = False  # jog_release от снятия поводка до возврата стопа: тик не берёт задание (T3.7)
        self._last_hold = 0.0  # время последнего jog_hold активного jog
        self._syncing = False  # идёт синхронизация параметров (d2)
        # Остановка (T5.3a К1): _stopping снимает connect(); _shutdown не снимается никогда
        self._stopping = False
        self._shutdown = False
        self._stop_level = 0  # сильнейший уровень стопа программы с последнего connect()
        # Защёлка стопа (T5.3 круг 2): сбрасывается при захвате нового действия и в connect()
        self._latch_level = 0  # сильнейший записанный уровень STOP_REQ в этом поколении
        self._latch_failed = False  # последняя запись STOP_REQ упала
        self._latch_value: int | None = None  # значение последней удачной записи (проверка эха в фазе 4)
        self._latch_attempts = 0  # попытки записи стопа процесса в этом поколении (не больше двух)
        self._echo_checked: int | None = None  # значение, эхо которого уже проверено
        self._stop_unconfirmed = False  # стоп процесса не подтверждён роботом (health через плагин); сброс — connect()
        self._stop_unconfirmed_text: str | None = None  # текст для health; ставится вместе с флагом
        self._own_stops: deque[int] = deque(maxlen=8)  # seq своих JOG_CONT, остановленных драйвером (Д1)
        # Задания CVT_JOB и возвраты (T3.7 DESIGN п.1): очереди — паритет v1, дренаж — тик, по одному действию
        self._job_queue: deque[_Job] = deque(maxlen=queue_maxlen)  # (x, y, z, e_signed, place)
        self._return_queue: deque[tuple[float, float, float]] = deque(maxlen=queue_maxlen)
        self._returns_done = 0
        self._returns_failed = 0

    # --- без замка: чтения, которые и раньше шли без него ---

    @property
    def returns_done(self) -> int:
        return self._returns_done

    @property
    def returns_failed(self) -> int:
        return self._returns_failed

    def job_queue_len(self) -> int:
        return len(self._job_queue)

    def return_queue_len(self) -> int:
        return len(self._return_queue)

    # --- помощники; зовутся только под self._lock ---

    def _latch_reset_locked(self) -> None:
        """Новое поколение (захват действия, ``connect``) — прежние стопы его не покрывают."""
        self._latch_level = 0
        self._latch_failed = False
        self._latch_attempts = 0
        self._latch_value = None  # H6: эхо проверяется только для записи этого поколения

    def _holding_locked(self) -> bool:
        """Свой jog жив и его стоп не запрошен."""
        run = self._jog
        return run is not None and run.active and not run.stop_requested

    # --- снимок ---

    def view(self) -> RobotStateView:
        """Замороженный снимок всех полей, снят одной секцией."""
        with self._lock:
            run = self._jog
            jog = None
            if run is not None:
                jog = JogView(
                    seq=run.seq,
                    active=run.active,
                    released=run.released,
                    stop_requested=run.stop_requested,
                    stop_sent=run.stop_sent,
                    has_handle=run.handle is not None,
                )
            return RobotStateView(
                program_active=self._program_active,
                has_prog_handle=self._prog_handle is not None,
                job_active=self._job_active,
                jog=jog,
                jog_starting=self._jog_starting,
                jog_stopping=self._jog_stopping,
                last_hold=self._last_hold,
                syncing=self._syncing,
                stopping=self._stopping,
                shutdown=self._shutdown,
                stop_level=self._stop_level,
                latch_level=self._latch_level,
                latch_failed=self._latch_failed,
                latch_value=self._latch_value,
                latch_attempts=self._latch_attempts,
                echo_checked=self._echo_checked,
                stop_unconfirmed=self._stop_unconfirmed,
                stop_unconfirmed_text=self._stop_unconfirmed_text,
                own_stops=tuple(self._own_stops),
                job_queue=tuple(self._job_queue),
                return_queue=tuple(self._return_queue),
                returns_done=self._returns_done,
                returns_failed=self._returns_failed,
            )

    # --- соединение ---

    def activity_alive(self) -> bool:
        """Жив поток поводка (``run.active``) или исполнитель (``program_active``)."""
        with self._lock:
            run = self._jog
            return (run is not None and run.active) or self._program_active

    def connect_check(self) -> tuple[bool, bool]:
        """``connect``: (выключение, задание тика)."""
        with self._lock:
            shutdown = self._shutdown
            job_active = self._job_active
            return shutdown, job_active

    def connect_reset(self) -> None:
        """``connect``: снять останов, уровень 0, сброс защёлки, снять «стоп не подтверждён» (текст остаётся)."""
        with self._lock:
            self._stopping = False  # ручное «Подключить» после обычного disconnect снова разрешает jog и программы
            self._stop_level = 0
            self._latch_reset_locked()
            self._stop_unconfirmed = False

    def is_shutdown(self) -> bool:
        with self._lock:
            return self._shutdown

    def disconnect_begin(self) -> bool:
        """``disconnect``: выключение; не выключение — новое поколение защёлки."""
        with self._lock:
            shutdown = self._shutdown
            if not shutdown:
                # Одно выключение — один стоп: отключение робота открывает новое поколение защёлки, прежние стопы
                # (оператор, отпускание jog) его не покрывают
                self._latch_reset_locked()
            return shutdown

    def threads_to_close(self) -> tuple[_JogRun | None, IHandle | None]:
        """``disconnect``: (jog, запись потока исполнителя)."""
        with self._lock:
            return self._jog, self._prog_handle

    # --- стоп процесса и защёлка (ADR-DH-009: меняются только секции) ---

    def request_stop_begin(self) -> None:
        """``request_stop``: защёлка выключения; первый вызов открывает новое поколение защёлки."""
        with self._lock:
            if not self._shutdown:
                # Первый запрос выключения открывает новое поколение защёлки: стопы до него (оператор, отпускание
                # jog) стоп выключения не покрывают; повторные вызовы в этом выключении поколение не сбрасывают
                self._latch_reset_locked()
            self._shutdown = True

    def stop_unconfirmed(self) -> bool:
        with self._lock:
            return self._stop_unconfirmed

    def stop_unconfirmed_text(self) -> str | None:
        with self._lock:
            return self._stop_unconfirmed_text

    def process_stop_plan(self, connected: Callable[[], bool]) -> tuple[int, _JogRun | None, bool]:
        """``_process_stop``: пометки останова и jog, уровень записи (0 — записи нет). -> (уровень, jog, стоп jog)."""
        with self._lock:
            self._stopping = True
            self._stop_level = max(self._stop_level, STOP_LEVEL["HARD"])
            run = self._jog
            stop_jog = run is not None and not run.stop_sent and (run.active or run.stop_requested)
            if run is not None and stop_jog:
                run.released = True  # поток поводка выходит без своего стопа: стоп пишет этот путь
                run.stop_requested = True
                run.wake.set()
            jog_in_flight = self._jog_starting  # JOG_CONT в полёте (замок не взят): стоп нужен и ему
            hard = self._program_active or self._job_active
            if hard:
                level = STOP_LEVEL["HARD"]
            elif stop_jog or jog_in_flight:
                level = STOP_LEVEL["SOFT"]
            elif connected():
                level = STOP_LEVEL["SOFT"]  # решение владельца 2026-10-19: выключаемый робот получает стоп и в покое
            else:
                level = 0  # простой и не подключён: писать некуда
            # Jog без записанного стопа (stop_sent False) или JOG_CONT в полёте пишется всегда, мимо защёлки (H-A)
            latch_applies = not (stop_jog or jog_in_flight)
            attempts = self._latch_attempts
            if attempts == 0:
                if level and latch_applies and self._latch_level >= level and not self._latch_failed:
                    level = 0  # такой стоп уже записан в этом поколении
            elif not (attempts == 1 and self._latch_failed):
                level = 0  # стоп процесса уже записан или повтор уже был: в поколении не больше двух попыток
            return level, run, stop_jog

    def next_stop_attempt(self, deadline: float, budget: Callable[[], float]) -> int | None:
        """Номер следующей попытки записи стопа процесса или None (больше двух или повтор не успевает до срока)."""
        with self._lock:
            attempt = self._latch_attempts + 1
            # Повтор — только после упавшей записи и только если запись успеет до срока (таймаут транспорта
            # с его повторами): поздний повтор не доставит стоп раньше срока, а поток стопа пережил бы его
            if attempt > 2 or (attempt == 2 and time.monotonic() + budget() > deadline):
                return None
            self._latch_attempts = attempt
            return attempt

    def note_own_stop(self, seq: int) -> None:
        """seq jog — в множество своих стопов ДО записи (Д1)."""
        with self._lock:
            if seq not in self._own_stops:
                self._own_stops.append(seq)

    def stop_write_failed(self) -> None:
        with self._lock:
            self._latch_failed = True

    def stop_written(self, value: int, run: _JogRun | None) -> None:
        """Запись ``STOP_REQ`` прошла: защёлка и ``stop_sent`` jog (флаг отражает запись, не эхо)."""
        with self._lock:
            self._latch_level = max(self._latch_level, value & 3)
            self._latch_failed = False
            self._latch_value = value
            if run is not None:
                run.stop_sent = True

    def echo_check_plan(self) -> tuple[bool, int | None]:
        """``_check_stop_echo``: (проверять ли эхо, значение записи); проверяемое значение помечается."""
        with self._lock:
            value = self._latch_value
            attempted = self._latch_attempts > 0
            if value is not None and value == self._echo_checked:
                return False, value
            if value is None and (not attempted or self._stop_unconfirmed):
                return False, value
            self._echo_checked = value
            return True, value

    def mark_unconfirmed(self, text: str) -> None:
        with self._lock:
            self._stop_unconfirmed = True
            self._stop_unconfirmed_text = text

    def latch_covers(self, level: int) -> bool:
        """Такой уровень уже записан в этом поколении и последняя запись не упала."""
        with self._lock:
            return self._latch_level >= level and not self._latch_failed

    def disconnect_stop_plan(self, program_level: int) -> tuple[_JogRun | None, bool, bool, bool]:
        """``_request_stop`` (под ``_jog_tx_lock``): останов, пометка jog. -> (jog, стоп jog, программа, задание)."""
        with self._lock:
            self._stopping = True
            self._stop_level = max(self._stop_level, program_level)
            run = self._jog
            stop_jog = run is not None and not run.stop_sent
            if stop_jog:
                run.released = True
                run.stop_requested = True
                run.wake.set()
            prog_alive = self._program_active
            job_active = self._job_active
            return run, stop_jog, prog_alive, job_active

    def is_own_stop(self, aborted: bool, seq: int) -> bool:
        """Ошибка робота — обрыв своего jog (Д1)."""
        with self._lock:
            return aborted and seq in self._own_stops

    # --- задания и возвраты (тик) ---

    def take_next_action(self) -> tuple[tuple[float, float, float] | None, _Job | None]:
        """Одно действие за тик: (возврат, None) / (None, задание: ``job_active``, сброс защёлки) / (None, None)."""
        with self._lock:
            run = self._jog
            if (
                self._stopping
                or self._syncing  # тик прошёл _ensure_connected до начала синхронизации другим потоком
                or self._program_active
                or self._jog_starting
                or self._jog_stopping
                or (run is not None and run.active)
                or self._job_active
            ):
                return None, None
            if self._return_queue:
                return self._return_queue.popleft(), None
            if self._job_queue:
                job = self._job_queue.popleft()
                self._job_active = True
                self._latch_reset_locked()
                return None, job
            return None, None

    def requeue_job(self, job: _Job) -> None:
        with self._lock:
            self._job_queue.appendleft(job)  # робот занят — повтор следующим тиком (паритет v1)

    def job_finished(self) -> None:
        with self._lock:
            self._job_active = False

    def requeue_return(self, item: tuple[float, float, float]) -> None:
        with self._lock:
            self._return_queue.appendleft(item)  # захват перехвачен между секциями — повтор следующим тиком

    def return_failed(self) -> None:
        with self._lock:
            self._returns_failed += 1

    def enqueue_job(self, job: _Job) -> int:
        with self._lock:
            self._job_queue.append(job)  # maxlen: старейшее вытесняется (паритет v1)
            return len(self._job_queue)

    def enqueue_return(self, item: tuple[float, float, float]) -> int:
        with self._lock:
            self._return_queue.append(item)
            return len(self._return_queue)

    # --- синхронизация параметров ---

    def begin_sync(self) -> bool:
        """«Активности нет» + ``syncing`` одной секцией (T5.3d2 DESIGN 2); занято — False, флаг не ставится.

        Активность — программа, jog (в том числе стартующий и останавливающийся), задание тика; остановка — после
        стопа параметры роботу не пишутся. Снимает флаг вызывающий (``end_sync``) в ``finally``.
        """
        with self._lock:
            run = self._jog
            if (
                self._stopping
                or self._shutdown
                or self._program_active
                or self._jog_starting
                or self._jog_stopping
                or (run is not None and run.active)
                or self._job_active
            ):
                return False
            self._syncing = True
            return True

    def end_sync(self) -> None:
        with self._lock:
            self._syncing = False

    def sync_cancelled(self) -> bool:
        """Остановка — после стопа параметры не пишутся."""
        with self._lock:
            return self._stopping or self._shutdown

    # --- jog ---

    def jog_hold_check(self) -> dict | str | None:
        """``jog_hold`` до ``_jog_tx_lock``: отказ / ``"hold"`` (продление: ``last_hold``) / None (дальше)."""
        with self._lock:
            if self._stopping:
                return {"status": "error", "message": TEXT_STOPPING}
            if self._program_active:
                return dict(_BUSY_PROGRAM)
            if self._job_active:
                return dict(_BUSY_JOB)
            if self._holding_locked():
                self._last_hold = self._clock()
                return "hold"
            if self._syncing:
                return {"status": "error", "message": TEXT_SYNCING}
            return None

    def jog_hold_admit(self) -> tuple[dict | str | None, _JogRun | None]:
        """``jog_hold`` под ``_jog_tx_lock``: те же проверки; допуск — ``jog_starting`` и прежний jog."""
        with self._lock:
            if self._stopping:
                return {"status": "error", "message": TEXT_STOPPING}, None
            if self._program_active:
                return dict(_BUSY_PROGRAM), None
            if self._job_active:
                return dict(_BUSY_JOB), None
            if self._holding_locked():
                self._last_hold = self._clock()
                return "hold", None
            if self._syncing:
                return {"status": "error", "message": TEXT_SYNCING}, None
            prev = self._jog
            # Д4: от проверки программы до записи jog start_program видит переход как jog (_BUSY_JOG)
            self._jog_starting = True
            return None, prev

    def jog_started(self, run: _JogRun) -> bool:
        """JOG_CONT подтверждён: jog, ``last_hold``, новое поколение защёлки (H-A). -> останов уже идёт (H-B)."""
        with self._lock:
            self._jog = run
            self._last_hold = self._clock()
            # H-A: запись движения — новое поколение защёлки ПОСЛЕ неё (стоп prev выше её не покрывает)
            self._latch_reset_locked()
            stopping = self._stopping
            return stopping

    def jog_aborted_by_stop(self, run: _JogRun) -> None:
        """H-B: стоп процесса лёг, пока JOG_CONT был в полёте, — поводок не запускается."""
        with self._lock:
            run.released = True
            run.stop_requested = True
            run.active = False

    def jog_spawn_failed(self, run: _JogRun, prev: _JogRun | None) -> None:
        with self._lock:
            run.active = False
            self._jog = prev

    def jog_start_done(self) -> None:
        with self._lock:
            self._jog_starting = False

    def jog_release_begin(self) -> _JogRun | None:
        """``jog_release``: свой держащийся jog -> пометки и ``jog_stopping``; нет -> None."""
        with self._lock:
            run = self._jog
            if run is None or not run.active or run.stop_requested:
                return None
            run.released = True
            run.stop_requested = True
            run.wake.set()
            # T3.7 (ревью р.1): поток поводка выходит (active = False) раньше записи стопа — до её возврата тик
            # не берёт задание, иначе SOFT этого jog оборвал бы CVT_JOB (E_ABORTED)
            self._jog_stopping = True
            return run

    def jog_release_done(self) -> None:
        with self._lock:
            self._jog_stopping = False

    def lease_check(self, run: _JogRun, ev: threading.Event) -> tuple[str, str | None, bool | None]:
        """Шаг поводка: ``("released", None, None)`` / ``("stop", причина, после начала остановки)`` /
        ``("lease", None, None)``. Окно истекло или область закрывается -> ``stop_requested``."""
        with self._lock:
            if run.released:
                return "released", None, None  # стоп шлёт release
            stop = ev.is_set() or self._clock() - self._last_hold > _HOLD_WINDOW_S
            if stop:
                run.stop_requested = True
                # причина для лога (D-L1): приоритет ``ev`` — порядок прежнего ``or``
                reason = "область закрывается" if ev.is_set() else "окно удержания истекло"
                late = self._stopping
                return "stop", reason, late
            return "lease", None, None

    def lease_exit(self, run: _JogRun) -> None:
        with self._lock:
            run.active = False

    # --- программы ---

    def admit_launch(self, connected: Callable[[], bool]) -> dict | None:
        """Захват исполнителя: отказ или None (``program_active``, сброс защёлки)."""
        with self._lock:
            if self._stopping:
                return {"status": "error", "message": TEXT_STOPPING}
            if self._program_active:
                return dict(_BUSY_PROGRAM)
            if self._job_active:
                return dict(_BUSY_JOB)
            run = self._jog
            if self._jog_starting or self._jog_stopping or (run is not None and run.active):
                return dict(_BUSY_JOG)  # окно T3.7: поводок вышел, стоп jog_release ещё не вернулся
            if self._syncing:
                return {"status": "error", "message": TEXT_SYNCING}
            if not connected():
                return dict(_NOT_CONNECTED)
            self._program_active = True
            self._latch_reset_locked()
            return None

    def launch_failed(self) -> None:
        with self._lock:
            self._program_active = False

    def program_started(self, handle: IHandle) -> None:
        with self._lock:
            self._prog_handle = handle

    def stop_resend_level(self, already_resent: bool) -> int:
        """Микроокно К1: уровень повтора стопа в ``on_progress`` (0 — повтора нет)."""
        with self._lock:
            return self._stop_level if (self._stopping and not already_resent) else 0

    def is_stopping(self) -> bool:
        with self._lock:
            return self._stopping

    def program_finished(self, kind: str, done: bool) -> None:
        """Исполнитель вышел: снять ``program_active``; возврат — счётчик исхода."""
        with self._lock:
            self._program_active = False
            if kind == "return":
                if done:
                    self._returns_done += 1
                else:
                    self._returns_failed += 1

    # --- операции движения и параметров ---

    def motion_refusal(self, syncing: bool = False) -> dict | None:
        """Отказ занятости: останов, программа, задание, jog (и синхронизация при ``syncing``)."""
        with self._lock:
            if self._stopping:
                return {"status": "error", "message": TEXT_STOPPING}
            if self._program_active:
                return dict(_BUSY_PROGRAM)
            if self._job_active:
                return dict(_BUSY_JOB)
            run = self._jog
            if self._jog_starting or self._jog_stopping or (run is not None and run.active):
                return dict(_BUSY_JOG)
            if syncing and self._syncing:
                return {"status": "error", "message": TEXT_SYNCING}
            return None

    def program_running(self) -> bool:
        with self._lock:
            return self._program_active

    def param_refusal(self) -> str | None:
        """``param_set`` / ``param_apply`` после ``_param_lock``: текст отказа (останов, синхронизация) или None."""
        with self._lock:
            stopping, syncing = self._stopping, self._syncing
        if stopping or syncing:
            return TEXT_STOPPING if stopping else TEXT_SYNCING
        return None
