"""
ChildProcessStop — остановка ГРУППЫ детей PM как один ``Stoppable`` (Task 1.1, ADR-PMM-035).

Purpose:
    Эскалация «stop_event → terminate → kill» с подтверждением смерти, разложенная на фазы
    области (``base_manager.Stoppable``): запрос, ожидание к абсолютному сроку,
    неблокирующий ``kill()``, освобождение. Один объект на группу (О2): опрос всех живых за
    один проход, поэтому смерть соседа (и её метка ReaderGone) видна сразу, а не после
    последовательного ``join`` впереди стоящего процесса.

Public API (внутренний модуль ``core/``, из ``__init__``/``interfaces`` пакета не экспортируется):
    ``ChildProcessStop(processes, stop_events, *, on_confirmed_dead, logger, terminate_grace_s,
    kill_confirm_s, poll_s)`` — ``request_stop()``, ``join_until(deadline)``, ``kill()``,
    ``survivors()``, ``close()``.

Инварианты:
    * метка ``on_confirmed_dead(name, process)`` — не более одной на имя за жизнь объекта,
      в момент наблюдения смерти; выжившему метка не ставится;
    * ``survivors()`` строится по набору подтверждённых: имя не в выживших ⇒ метка была
      (правило ADR-PMM-030 «True ⇒ метка»);
    * до ``kill()`` процессам не шлётся ни одного сигнала; ``kill()`` только шлёт
      ``terminate()`` и возвращается, настоящий ``kill()`` уходит из ``join_until``.

Stability: lite
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Mapping
from typing import Any

from ...logger_module import get_std_logger
from .stop_budget import KILL_CONFIRM_S, STOP_POLL_S, TERMINATE_GRACE_S

__all__ = ["ChildProcessStop"]

_log = get_std_logger(__name__)

type ConfirmedDead = Callable[[str, Any], None]


class ChildProcessStop:
    """Группа процессов с общей эскалацией и метками «подтверждённо мёртв».

    Процесс — любой объект с ``is_alive()``, ``terminate()``, ``kill()``; событие — любой
    объект с ``set()``. Имя без события в ``stop_events`` — запись в лог: сигнал не шлётся,
    процесс останавливается только эскалацией.
    """

    def __init__(
        self,
        processes: Mapping[str, Any],
        stop_events: Mapping[str, Any],
        *,
        on_confirmed_dead: ConfirmedDead | None = None,
        logger: Any = None,
        terminate_grace_s: float = TERMINATE_GRACE_S,
        kill_confirm_s: float = KILL_CONFIRM_S,
        poll_s: float = STOP_POLL_S,
        idle: Callable[[float], None] | None = None,
        should_abort: Callable[[], bool] | None = None,
    ) -> None:
        self._processes: dict[str, Any] = dict(processes)
        self._events: dict[str, Any] = {name: stop_events.get(name) for name in self._processes}
        self._on_confirmed_dead = on_confirmed_dead
        self._logger = logger
        self._terminate_grace_s = float(terminate_grace_s)
        self._kill_confirm_s = float(kill_confirm_s)
        self._poll_s = float(poll_s)
        # Чем ждать между проходами ``join_until`` (Task 1.8, ADR-PMM-037). None — ``time.sleep``;
        # PM подставляет «вычерпать свои каналы и доспать остаток», чтобы хвост очереди PM не
        # держал выходящего ребёнка (L-9). Имя ``time.sleep`` берётся в момент вызова.
        self._idle = idle
        # Сбой idle пишется одной строкой на объект, а не на каждом проходе опроса.
        self._idle_error_logged = False
        # Task 1.9b (D4, I1): системный стоп прерывает ожидание ``join_until`` — без метки, без
        # ``terminate``: дальше ребёнка ведёт стоп корня PM (группа ``children``), у стопа один владелец.
        self._should_abort = should_abort
        self._aborted = False
        self._lock = threading.Lock()
        # Имена с подтверждённой смертью; каждое получило ровно одну попытку метки.
        self._dead: set[str] = set()
        self._missing_event_logged: set[str] = set()
        # Сбой is_alive() пишется одной строкой на имя, а не на каждом проходе опроса.
        self._alive_error_logged: set[str] = set()
        # Точка отсчёта для текста «did not stop in <N>s»: request_stop(), а без него создание.
        self._stop_requested_at = time.monotonic()
        self._stop_requested = False
        self._kill_started_at: float | None = None
        self._real_kill_sent = False
        # Task 1.10 (D2): кому из имён сигнал ДОСТАВЛЕН. Не флаги группы выше: имя, умершее между
        # окном и ``kill()``, сигнала не получает и остаётся ``exited``.
        self._terminated: set[str] = set()
        self._killed: set[str] = set()

    # ---- лог ------------------------------------------------------------------

    def _emit(self, level: str, message: str) -> None:
        """PM-логгер (``_log_<level>``), stdlib-логгер (``<level>``) или логгер модуля."""
        logger = self._logger
        try:
            method = getattr(logger, f"_log_{level}", None) if logger is not None else None
            if callable(method):
                method(message)
                return
            method = getattr(logger, level, None) if logger is not None else None
            if callable(method):
                method(message)
                return
            getattr(_log, level)(message)
        except Exception:  # noqa: BLE001 — сбой лога не прерывает остановку
            _log.exception("ChildProcessStop: сбой логгера на сообщении %r", message)

    # ---- наблюдение -----------------------------------------------------------

    def _pending(self) -> list[tuple[str, Any]]:
        with self._lock:
            return [(name, proc) for name, proc in self._processes.items() if name not in self._dead]

    def _alive(self, name: str, proc: Any) -> bool:
        try:
            return bool(proc.is_alive())
        except Exception as exc:  # noqa: BLE001 — процесс, чьё состояние не прочесть, считаем живым
            with self._lock:
                first = name not in self._alive_error_logged
                self._alive_error_logged.add(name)
            if first:
                self._emit("warning", f"is_alive() для '{name}' упал: {exc} — считается живым")
            return True

    def _confirm(self, name: str, proc: Any) -> None:
        """Смерть увидена: зафиксировать и поставить метку один раз."""
        with self._lock:
            if name in self._dead:
                return
            self._dead.add(name)
        callback = self._on_confirmed_dead
        if callback is None:
            return
        try:
            callback(name, proc)
        except Exception as exc:  # noqa: BLE001 — метка вторична к факту смерти
            self._emit("warning", f"метка подтверждённой смерти для '{name}' упала: {exc}")

    def _observe(self) -> list[tuple[str, Any]]:
        """Один проход опроса всех ещё живых; умерших метит сразу. Возвращает живых."""
        alive: list[tuple[str, Any]] = []
        for name, proc in self._pending():
            if self._alive(name, proc):
                alive.append((name, proc))
            else:
                self._confirm(name, proc)
        return alive

    # ---- Stoppable --------------------------------------------------------------

    def request_stop(self) -> None:
        """Фаза 1: ``set()`` события каждому живому. Не блокирует, идемпотентно."""
        with self._lock:
            if not self._stop_requested:
                self._stop_requested = True
                self._stop_requested_at = time.monotonic()
        for name, proc in self._pending():
            if not self._alive(name, proc):
                continue
            event = self._events.get(name)
            if event is None:
                with self._lock:
                    first = name not in self._missing_event_logged
                    self._missing_event_logged.add(name)
                if first:
                    self._emit("warning", f"stop: у '{name}' нет stop_event — только terminate/kill")
                continue
            try:
                event.set()
            except Exception as exc:  # noqa: BLE001 — остальные дети получают свой сигнал
                self._emit("warning", f"stop_event.set() для '{name}' упал: {exc}")

    @property
    def aborted(self) -> bool:
        """``join_until`` прерван ``should_abort`` (системный стоп): выжившие не подтверждены."""
        return self._aborted

    def _abort_requested(self) -> bool:
        """Опрос ``should_abort``; сбой предиката — ``False`` (стоп детей не должен падать от него)."""
        check = self._should_abort
        if check is None:
            return False
        try:
            return bool(check())
        except Exception as exc:  # noqa: BLE001 — предикат вторичен к стопу
            self._emit("warning", f"should_abort() упал: {exc} — стоп продолжается")
            return False

    def kill(self) -> None:
        """Фаза 3, начало: ``terminate()`` каждому живому и возврат без ожидания. Повтор — no-op.

        Прерванный стоп (``aborted``) — no-op: ни строки, ни ``terminate`` (D4, один владелец).
        """
        with self._lock:
            if self._aborted or self._kill_started_at is not None:
                return
            self._kill_started_at = time.monotonic()
            waited = self._kill_started_at - self._stop_requested_at
        for name, proc in self._pending():
            if not self._alive(name, proc):
                continue
            self._emit("warning", f"Process '{name}' did not stop in {waited:.1f}s, terminating...")
            try:
                proc.terminate()
            except Exception as exc:  # noqa: BLE001 — эскалация остальных продолжается
                self._emit("warning", f"Error terminating '{name}': {exc}")
            else:
                with self._lock:
                    self._terminated.add(name)

    def _kill_at(self, deadline: float) -> float | None:
        """Момент настоящего ``kill()``: ``None`` — не положен (не было ``kill()`` или уже ушёл)."""
        with self._lock:
            if self._kill_started_at is None or self._real_kill_sent:
                return None
            return min(self._kill_started_at + self._terminate_grace_s, deadline - self._kill_confirm_s)

    def _send_real_kill(self, alive: list[tuple[str, Any]]) -> None:
        with self._lock:
            if self._real_kill_sent:
                return
            self._real_kill_sent = True
        for name, proc in alive:
            self._emit("error", f"Force killing process '{name}'")
            try:
                proc.kill()
            except Exception as exc:  # noqa: BLE001 — kill остальных продолжается
                self._emit("error", f"Error killing '{name}': {exc}")
            else:
                with self._lock:
                    self._killed.add(name)

    def join_until(self, deadline: float) -> bool:
        """Фаза 2 (и ожидание фазы 3): опрос всех живых каждые ``poll_s`` до абсолютного срока.

        ``True`` — ждать некого. На сроке ``False``, не бросает; срок в прошлом — ровно один
        проход. ``should_abort()`` истинен на проходе — ``False`` досрочно, ``aborted`` ``True``.
        После ``kill()`` настоящий ``kill()`` уходит один раз на первом проходе, где
        ``now >= min(начало + terminate_grace_s, deadline - kill_confirm_s)``.
        """
        while True:
            alive = self._observe()
            if not alive:
                return True
            if self._abort_requested():
                # Метки выжившим нет; ``survivors()`` их вернёт, ``kill()`` станет no-op.
                with self._lock:
                    self._aborted = True
                return False
            now = time.monotonic()
            kill_at = self._kill_at(deadline)
            if kill_at is not None and now >= kill_at:
                self._send_real_kill(alive)
                kill_at = None
            if now >= deadline:
                return False
            pause = min(self._poll_s, deadline - now)
            if kill_at is not None:
                pause = min(pause, kill_at - now)
            self._wait(max(0.0, pause))

    def _wait(self, pause: float) -> None:
        """Пауза между проходами: ``idle(pause)`` или ``time.sleep``; сбой idle не прерывает стоп.

        idle бросил — один WARNING на объект, остаток паузы спится обычным ``time.sleep``
        (без сна ожидание превратилось бы в горячий цикл).
        """
        idle = self._idle
        if idle is None:
            time.sleep(pause)
            return
        try:
            idle(pause)
        except Exception as exc:  # noqa: BLE001 — стоп не бросает, ожидание продолжается сном
            if not self._idle_error_logged:
                self._idle_error_logged = True
                self._emit("warning", f"ChildProcessStop: idle() упал: {exc}; ожидание обычным сном")
            time.sleep(pause)

    def survivors(self) -> tuple[str, ...]:
        """Один проход наблюдения, затем имена без подтверждённой смерти — в порядке ``processes``."""
        self._observe()
        with self._lock:
            return tuple(name for name in self._processes if name not in self._dead)

    def outcomes(self) -> dict[str, str]:
        """Итог стопа каждого имени группы одним снимком (Task 1.10, D1/D2).

        Начинает с последнего прохода наблюдения (как ``survivors()``): умерший через миллисекунды
        после последнего ``join_until`` подтверждается, ``on_confirmed_dead`` — ровно один раз.
        Подтверждённое имя: ``killed`` / ``terminated`` / ``exited`` — по тому, какой сигнал доставлен
        ЕМУ (не по exitcode). Неподтверждённое: ``handed_over`` при ``aborted`` (ребёнка добьёт стоп
        корня), иначе ``survived`` (пережил kill).
        """
        self._observe()
        with self._lock:
            aborted = self._aborted
            result: dict[str, str] = {}
            for name in self._processes:
                if name in self._dead:
                    if name in self._killed:
                        result[name] = "killed"
                    elif name in self._terminated:
                        result[name] = "terminated"
                    else:
                        result[name] = "exited"
                else:
                    result[name] = "handed_over" if aborted else "survived"
            return result

    def close(self) -> None:
        """Проход наблюдения: метит подтверждённо мёртвых без метки; выживших не метит. Не бросает."""
        try:
            self._observe()
        except Exception as exc:  # noqa: BLE001 — close() из области не должен бросать
            self._emit("warning", f"ChildProcessStop.close(): {exc}")
