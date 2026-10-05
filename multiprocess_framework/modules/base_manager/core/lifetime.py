"""Область владения: реализация ``IScope`` / ``IHandle`` (ADR-BM-008, Task 0.2).

Контракт — docstring'и ``base_manager/interfaces.py``; уточнения реализации —
``plans/2026-10-03_lifecycle-owner-scope/task-0.2.md``, раздел «Контракт
реализации». Здесь они не копируются.

Снаружи доступны только ``open_scope`` и ``unclosed_roots`` (через пакет
``base_manager``). Классы ``Scope`` и ``Handle`` не экспортируются: второй
владелец через наследование не пишется.

Правило блокировок: ни один вызов ресурса (фазы 1–3, вызываемые, reporter)
не идёт под локом области — ресурс может позвать ``own``/``close`` этой же
области.
"""

from __future__ import annotations

import itertools
import logging
import math
import threading
import time
import weakref
from collections.abc import Callable
from typing import Any

from ..interfaces import CloseReport, IHandle, IScope, Reporter, Resource, ScopeClosedError, Stoppable

_log = logging.getLogger(__name__)

_STOPPABLE = "stoppable"
_CALLABLE = "callable"
_THREAD = "thread"
_SCOPE = "scope"

_SELF_SUFFIX = " (self)"
_THREAD_ERRORS_CAP = 20

# Поток, запущенный spawn, знает свою запись: так close распознаёт
# «поток закрывает свою область» и «spawn-поток поддерева».
_tls = threading.local()


# =============================================================================
# Проверка аргументов
# =============================================================================


def _seconds(field: str, value: object, *, allow_negative: bool = False) -> float:
    """Число секунд: ``bool``/не число → ``TypeError``; NaN, ±inf, отрицательное → ``ValueError``."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field}: ожидается int | float, получено {type(value).__name__}")
    if math.isnan(value) or math.isinf(value):
        raise ValueError(f"{field}: ожидается конечное число, получено {value!r}")
    if not allow_negative and value < 0:
        raise ValueError(f"{field}: ожидается число ≥ 0, получено {value!r}")
    return float(value)


def _check_name(name: object) -> str:
    """Имя записи: непустая ``str`` без ``/`` и без суффикса ``" (self)"``."""
    if not isinstance(name, str):
        raise TypeError(f"name: ожидается str, получено {type(name).__name__}")
    if not name or "/" in name or name.endswith(_SELF_SUFFIX):
        raise ValueError(f"name {name!r}: нужна непустая строка без '/' и без суффикса '{_SELF_SUFFIX}'")
    return name


def _check_kind(kind: object) -> str:
    if not isinstance(kind, str) or not kind:
        raise TypeError(f"kind: ожидается непустая str, получено {type(kind).__name__}")
    return kind


# =============================================================================
# Запись и накопитель отчёта
# =============================================================================


class _Entry:
    """Одна запись области. После освобождения не держит ни ресурс, ни область."""

    __slots__ = (
        "name",
        "path",
        "kind",
        "mode",
        "res",
        "scope",
        "segment",
        "state",
        "stop_requested",
        "claimed",
        "releaser",
        "finished",
        "done",
        "thread",
        "event",
        "out_survivors",
        "out_killed",
        "out_errors",
    )

    def __init__(self, scope: Scope | None, name: str, path: str, kind: str, mode: str, res: Any) -> None:
        self.name = name
        self.path = path
        self.kind = kind
        self.mode = mode
        self.res = res
        self.scope = scope
        self.segment: list[_Entry] | None = None
        self.state = "open"
        self.stop_requested = False
        self.claimed = False  # взята закрывающим (close области или IHandle.close)
        self.releaser: int | None = None  # поток, который освобождает запись
        self.finished = False  # spawn-поток вышел и сам отцепился
        self.done = threading.Event()  # исход записи известен
        self.thread: threading.Thread | None = None
        self.event: threading.Event | None = None
        self.out_survivors: list[str] = []
        self.out_killed: list[str] = []
        self.out_errors: list[tuple[str, str]] = []


class _Acc:
    """Накопитель одного отчёта."""

    __slots__ = ("survivors", "killed", "errors", "complete", "emits")

    def __init__(self) -> None:
        self.survivors: list[str] = []
        self.killed: list[str] = []
        self.errors: list[tuple[str, str]] = []
        self.complete = True
        self.emits = 0  # отклонённые доставки (канал note_emits_after_close)

    def merge(self, report: CloseReport) -> None:
        self.survivors.extend(report.survivors)
        self.killed.extend(report.killed)
        self.errors.extend(report.errors)
        self.complete = self.complete and report.complete
        self.emits += report.emits_after_close

    def report(self, path: str, start: float) -> CloseReport:
        return CloseReport(
            path=path,
            elapsed_s=time.monotonic() - start,
            survivors=tuple(self.survivors),
            killed=tuple(self.killed),
            errors=tuple(self.errors),
            emits_after_close=self.emits,
            complete=self.complete,
        )


def _error_text(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"


def _incomplete(path: str, start: float) -> CloseReport:
    return CloseReport(
        path=path, elapsed_s=time.monotonic() - start, survivors=(), killed=(), errors=(), complete=False
    )


# =============================================================================
# Сторож корней (G3)
# =============================================================================

# RLock, не Lock: ``_mark_abandoned`` — колбэк ``weakref.finalize``, его зовёт gc в том
# потоке, который аллоцирует. Любой ``with _roots_lock`` с аллокацией внутри (список в
# ``unclosed_roots``) может войти в финализатор этим же потоком — обычный Lock там виснет.
# Финализатор меняет только ``record["state"]``, не размер ``_roots``: обход внутри безопасен.
_roots_lock = threading.RLock()
_roots: dict[int, dict[str, str]] = {}
_root_keys = itertools.count()


def _mark_abandoned(key: int) -> None:
    """Колбэк ``weakref.finalize``: корень собран без ``close``. Ссылки на корень не держит."""
    with _roots_lock:
        record = _roots.get(key)
        if record is not None:
            record["state"] = "abandoned"


def unclosed_roots() -> list[dict]:
    """Корни без начатого ``close``: ``{"path", "state"}``, ``state`` ∈ {``"open"``, ``"abandoned"``}.

    ``"abandoned"`` копятся до конца процесса: это дефекты, сброса нет.
    """
    with _roots_lock:
        return [{"path": rec["path"], "state": rec["state"]} for rec in _roots.values()]


# =============================================================================
# Handle
# =============================================================================


class Handle:
    """Реализация ``IHandle`` (контракт — ``interfaces.IHandle``).

    После своего закрытия не держит ни ресурс, ни область.
    """

    def __init__(self, scope: Scope, entry: _Entry) -> None:
        self._scope: Scope | None = scope
        self._entry: _Entry | None = entry
        self._path = entry.path
        self._kind = entry.kind
        self._lock = threading.Lock()
        self._report: CloseReport | None = None
        self._closing_by: int | None = None  # поток, который сейчас закрывает ручку
        self._done = threading.Event()

    @property
    def path(self) -> str:
        return self._path

    @property
    def kind(self) -> str:
        return self._kind

    def close(self, budget_s: float | None = None) -> CloseReport:
        """Контракт — ``IHandle.close``.

        Под локом ручки — только решение «кто закрывает»; ресурс освобождается
        вне лока (ресурс может позвать ``close`` своей же ручки). Реентрантный
        вызов тем потоком, который сейчас освобождает запись, сразу возвращает
        ``complete=False`` — то же правило, что у реентрантного ``close`` области.
        """
        start = time.monotonic()
        if budget_s is not None:
            budget_s = _seconds("budget_s", budget_s)
        me = threading.get_ident()
        with self._lock:
            if self._report is not None:
                return self._report
            scope, entry = self._scope, self._entry
            assert scope is not None and entry is not None
            if self._closing_by is not None:
                if self._closing_by == me:
                    return _incomplete(self._path, start)
                waiting = True
            else:
                waiting = False
                self._closing_by = me
        if waiting:
            deadline = start + (scope._budget_s if budget_s is None else budget_s)
            if self._done.wait(max(0.0, deadline - time.monotonic())) and self._report is not None:
                return self._report
            return _incomplete(self._path, start)
        report = None
        try:
            report = scope._close_entry_early(entry, budget_s)
        finally:
            with self._lock:
                self._closing_by = None
                if report is not None:
                    self._report = report
                    self._scope = None
                    self._entry = None
                    self._done.set()
        if report is None:  # запись освобождает этот же поток (идёт close области)
            return _incomplete(self._path, start)
        return report

    def __reduce_ex__(self, protocol: object) -> Any:
        raise TypeError(f"запись '{self._path}': pickle запрещён — копия в другом процессе была бы вторым владельцем")

    def __repr__(self) -> str:
        return f"<Handle {self._path!r} kind={self._kind!r}>"


# =============================================================================
# Scope
# =============================================================================


class Scope:
    """Реализация ``IScope`` (контракт — ``interfaces.IScope``).

    Создаётся только ``open_scope`` (корень) и ``child`` (ребёнок).
    """

    def __init__(
        self,
        path: str,
        *,
        parent: Scope | None,
        budget_s: float,
        kill_reserve_s: float,
        reporter: Reporter | None,
    ) -> None:
        self._path = path
        self._parent = parent
        self._budget_s = budget_s
        self._kill_reserve_s = kill_reserve_s
        self._reporter = reporter
        self._lock = threading.RLock()
        self._segments: list[list[_Entry]] = [[]]
        self._names: dict[str, _Entry] = {}
        self._state = "open"  # open → closing → closed
        self._closer: int | None = None
        self._done = threading.Event()
        self._report: CloseReport | None = None
        self._deadline = 0.0  # D идущего close
        self._limit = 0.0  # K идущего close
        self._extra = _Acc()  # освобождения own во время закрытия
        self._thread_errors: list[tuple[_Entry, tuple[str, str]]] = []
        self._thread_errors_dropped = 0
        self._root_key: int | None = None
        self._finalizer: weakref.finalize | None = None

    # ---- свойства -----------------------------------------------------------

    @property
    def path(self) -> str:
        return self._path

    @property
    def closed(self) -> bool:
        return self._state != "open"

    @property
    def parent(self) -> IScope | None:
        return self._parent

    @property
    def budget_s(self) -> float:
        return self._budget_s

    @property
    def kill_reserve_s(self) -> float:
        return self._kill_reserve_s

    def __reduce_ex__(self, protocol: object) -> Any:
        raise TypeError(
            f"область '{self._path}': pickle запрещён — она держит потоки и локи, "
            "копия в другом процессе была бы вторым владельцем"
        )

    def __repr__(self) -> str:
        return f"<Scope {self._path!r} state={self._state}>"

    # ---- регистрация --------------------------------------------------------

    def _closed_error(self, name: str) -> ScopeClosedError:
        state = "closing" if self._state == "closing" else "closed"
        return ScopeClosedError(f"область '{self._path}' ({state}): запись '{name}' не принята")

    def _register_locked(self, entry: _Entry) -> None:
        if entry.name in self._names:
            raise ValueError(f"область '{self._path}': имя '{entry.name}' уже занято незакрытой записью")
        segment = self._segments[-1]
        segment.append(entry)
        entry.segment = segment
        self._names[entry.name] = entry

    def own(self, res: Resource, *, name: str, kind: str = "resource") -> IHandle:
        """Контракт — ``IScope.own``.

        Вызываемое не прерывается сроком: оно работает на потоке закрывающего,
        и его блокировка растягивает ``close``.
        """
        if isinstance(res, type):
            raise TypeError(f"own: передан класс {res.__name__}, нужен экземпляр")
        if isinstance(res, Stoppable):
            mode = _STOPPABLE
        elif callable(res):
            mode = _CALLABLE
        else:
            raise TypeError(f"own: {type(res).__name__} — не Stoppable и не вызываемое")
        _check_name(name)
        _check_kind(kind)
        entry = _Entry(self, name, f"{self._path}/{name}", kind, mode, res)
        with self._lock:
            state = self._state
            if state == "open":
                self._register_locked(entry)
                return Handle(self, entry)
            error = self._closed_error(name)
        self._release_refused(entry, state)
        raise error

    def _release_refused(self, entry: _Entry, state: str) -> None:
        """Освободить ресурс, пришедший в закрывающуюся или закрытую область."""
        start = time.monotonic()
        acc = _Acc()
        entry.claimed = True
        entry.releaser = threading.get_ident()
        if state == "closing":
            deadline = min(self._deadline, start + self._budget_s)
            limit = min(deadline + self._kill_reserve_s, self._limit)
        else:
            deadline = start + self._budget_s
            limit = deadline + self._kill_reserve_s
        self._close_entries([entry], deadline, limit, acc)
        report = acc.report(entry.path, start)
        with self._lock:
            merged = self._state == "closing"
            if merged:
                self._extra.merge(report)
        if not merged:
            self._call_reporter(report)

    def child(self, name: str, *, budget_s: float | None = None, kill_reserve_s: float | None = None) -> IScope:
        _check_name(name)
        budget = self._budget_s if budget_s is None else _seconds("budget_s", budget_s)
        reserve = self._kill_reserve_s if kill_reserve_s is None else _seconds("kill_reserve_s", kill_reserve_s)
        child = Scope(
            f"{self._path}/{name}",
            parent=self,
            budget_s=budget,
            kill_reserve_s=reserve,
            reporter=self._reporter,
        )
        entry = _Entry(self, name, child._path, "scope", _SCOPE, child)
        with self._lock:
            if self._state != "open":
                raise self._closed_error(name)
            self._register_locked(entry)
        return child

    def barrier(self) -> None:
        with self._lock:
            self._segments.append([])

    def spawn(self, target: Callable[[threading.Event], None], *, name: str) -> IHandle:
        _check_name(name)
        if not callable(target):
            raise TypeError(f"spawn: target {type(target).__name__} не вызываемое")
        entry = _Entry(self, name, f"{self._path}/{name}", "thread", _THREAD, None)
        event = threading.Event()
        thread = threading.Thread(target=self._thread_main, args=(entry, target, event), name=entry.path, daemon=True)
        entry.thread = thread
        entry.event = event
        with self._lock:
            if self._state != "open":
                raise self._closed_error(name)
            self._register_locked(entry)
        thread.start()
        return Handle(self, entry)

    def _thread_main(self, entry: _Entry, target: Callable[[threading.Event], None], event: threading.Event) -> None:
        _tls.entry = entry
        try:
            target(event)
        except Exception as exc:
            pair = (entry.path, _error_text(exc))
            _log.warning("поток %s вышел с исключением %s", entry.path, pair[1])
            with self._lock:
                if len(self._thread_errors) < _THREAD_ERRORS_CAP:
                    self._thread_errors.append((entry, pair))
                else:
                    self._thread_errors_dropped += 1
        finally:
            _tls.entry = None
            self._thread_exited(entry)

    def _thread_exited(self, entry: _Entry) -> None:
        """Самоотцепление по тождеству записи: имя свободно, в ``live()`` записи нет."""
        with self._lock:
            if entry.claimed and entry.state != "survivor":
                return  # закрывающий ждёт этот поток и освободит запись сам
            self._remove_locked(entry)
            entry.finished = True
            entry.thread = None
            entry.event = None
            entry.done.set()

    def _remove_locked(self, entry: _Entry) -> None:
        segment = entry.segment
        if segment is not None:
            for index, item in enumerate(segment):
                if item is entry:
                    del segment[index]
                    break
            entry.segment = None
        if self._names.get(entry.name) is entry:
            del self._names[entry.name]

    def _drain_thread_errors_locked(self, entry: _Entry | None) -> list[tuple[str, str]]:
        """Забрать пары исключений потоков: одной записи или все (+ пара-счётчик сверх потолка)."""
        if entry is None:
            pairs = [pair for _, pair in self._thread_errors]
            self._thread_errors = []
            if self._thread_errors_dropped:
                pairs.append((self._path, f"ещё {self._thread_errors_dropped} исключений потоков не показано"))
                self._thread_errors_dropped = 0
            return pairs
        mine = [pair for owner, pair in self._thread_errors if owner is entry]
        if mine:
            self._thread_errors = [item for item in self._thread_errors if item[0] is not entry]
        return mine

    # ---- фазы ---------------------------------------------------------------

    def _fail(self, entry: _Entry, exc: Exception, acc: _Acc | None) -> None:
        pair = (entry.path, _error_text(exc))
        entry.out_errors.append(pair)
        if acc is None:
            _log.warning("фаза 1 записи %s бросила %s", entry.path, pair[1])
        else:
            acc.errors.append(pair)

    def _survive(self, entry: _Entry, text: str, acc: _Acc) -> None:
        acc.survivors.append(text)
        entry.out_survivors.append(text)
        with self._lock:
            entry.state = "survivor"
        entry.done.set()

    def _release(self, entry: _Entry) -> None:
        # Ссылки выносятся из-под лока: последняя ссылка на ресурс может рваться здесь,
        # а ``__del__``/weakref-колбэк ресурса не должен идти под локом области.
        with self._lock:
            self._remove_locked(entry)
            res, entry.res = entry.res, None
            scope, entry.scope = entry.scope, None
            thread, entry.thread = entry.thread, None
            entry.event = None
            entry.state = "closed"
        del res, scope, thread
        entry.done.set()

    def _finish_stoppable(self, entry: _Entry, acc: _Acc) -> None:
        """Остановка подтверждена: ``close()`` ресурса, если есть, ровно один раз; затем освобождение."""
        close = getattr(entry.res, "close", None)
        if callable(close):
            try:
                close()
            except Exception as exc:
                self._fail(entry, exc, acc)
        self._release(entry)

    def _phase1(self, entries: list[_Entry], acc: _Acc | None) -> None:
        """Фаза 1 по поддереву: записи + верхние сегменты дочерних областей, рекурсивно. Идемпотентно."""
        todo: list[_Entry] = []
        with self._lock:
            for entry in entries:
                if entry.state == "open":
                    entry.state = "stopping"
                if entry.mode == _SCOPE or not entry.stop_requested:
                    entry.stop_requested = True
                    todo.append(entry)
        for entry in todo:
            if entry.mode == _STOPPABLE:
                try:
                    entry.res.request_stop()
                except Exception as exc:
                    self._fail(entry, exc, acc)
            elif entry.mode == _THREAD:
                event = entry.event
                if event is not None:
                    event.set()
            elif entry.mode == _SCOPE:
                child = entry.res
                if child is not None:
                    child._phase1_top(acc)

    def _phase1_top(self, acc: _Acc | None) -> None:
        with self._lock:
            entries = list(self._segments[-1])
        self._phase1(entries, acc)

    def _close_entries(self, entries: list[_Entry], deadline: float, limit: float, acc: _Acc) -> None:
        """Фаза 1 → фаза 2 LIFO → фаза 3 для одного сегмента (или одной записи)."""
        self._phase1(entries, acc)
        pending: list[_Entry] = []
        for entry in reversed(entries):
            if entry.mode == _CALLABLE:
                try:
                    entry.res()
                except Exception as exc:
                    self._fail(entry, exc, acc)
                self._release(entry)
            elif entry.mode == _STOPPABLE:
                try:
                    stopped = bool(entry.res.join_until(deadline))
                except Exception as exc:
                    self._fail(entry, exc, acc)
                    stopped = False
                if stopped:
                    self._finish_stoppable(entry, acc)
                else:
                    pending.append(entry)
            elif entry.mode == _THREAD:
                self._join_thread(entry, deadline, acc)
            else:
                self._close_child_entry(entry, deadline, acc)
        self._phase3(pending, limit, acc)

    def _join_thread(self, entry: _Entry, deadline: float, acc: _Acc) -> None:
        thread = entry.thread
        if thread is None:  # поток уже вышел и отцепился
            self._release(entry)
            return
        if thread is threading.current_thread():
            self._survive(entry, f"{entry.path}{_SELF_SUFFIX}", acc)
            return
        thread.join(max(0.0, deadline - time.monotonic()))
        if thread.is_alive():
            self._survive(entry, entry.path, acc)
        else:
            self._release(entry)

    def _close_child_entry(self, entry: _Entry, deadline: float, acc: _Acc) -> None:
        child: Scope | None = entry.res
        if child is None:
            self._release(entry)
            return
        child_deadline = min(deadline, time.monotonic() + child._budget_s)
        report = child._close(child_deadline, child_deadline + child._kill_reserve_s, from_parent=True)
        acc.merge(report)
        entry.out_survivors.extend(report.survivors)
        entry.out_killed.extend(report.killed)
        entry.out_errors.extend(report.errors)
        if report.survivors:
            with self._lock:
                entry.state = "survivor"
            entry.done.set()
        else:
            self._release(entry)

    def _phase3(self, pending: list[_Entry], limit: float, acc: _Acc) -> None:
        """``kill()`` всем не остановившимся, затем ОДНО общее ожидание до ``min(now + резерв, K)``."""
        waiting: list[_Entry] = []
        for entry in pending:
            kill = getattr(entry.res, "kill", None)
            if not callable(kill):
                self._survive(entry, entry.path, acc)
                continue
            try:
                kill()
            except Exception as exc:
                self._fail(entry, exc, acc)
            waiting.append(entry)
        if not waiting:
            return
        until = min(time.monotonic() + self._kill_reserve_s, limit)
        for entry in waiting:
            try:
                stopped = bool(entry.res.join_until(until))
            except Exception as exc:
                self._fail(entry, exc, acc)
                stopped = False
            if stopped:
                acc.killed.append(entry.path)
                entry.out_killed.append(entry.path)
                self._finish_stoppable(entry, acc)
            else:
                self._survive(entry, entry.path, acc)

    # ---- cancel / close -----------------------------------------------------

    def cancel(self) -> None:
        self._phase1_top(None)

    def close(self, budget_s: float | None = None, *, deadline: float | None = None) -> CloseReport:
        if budget_s is not None and deadline is not None:
            raise ValueError(f"область '{self._path}': close получил и budget_s, и deadline — нужен один срок")
        now = time.monotonic()
        if deadline is not None:
            limit_d = _seconds("deadline", deadline, allow_negative=True)
        elif budget_s is not None:
            limit_d = now + _seconds("budget_s", budget_s)
        else:
            limit_d = now + self._budget_s
        return self._close(limit_d, limit_d + self._kill_reserve_s, from_parent=False)

    def _is_subtree_thread(self) -> bool:
        """Текущий поток — spawn-поток этой области или любой области её поддерева."""
        entry: _Entry | None = getattr(_tls, "entry", None)
        scope = entry.scope if entry is not None else None
        while scope is not None:
            if scope is self:
                return True
            scope = scope._parent
        return False

    def _close(self, deadline: float, limit: float, *, from_parent: bool) -> CloseReport:
        start = time.monotonic()
        me = threading.get_ident()
        with self._lock:
            if self._state == "closed":
                assert self._report is not None
                return self._report
            if self._state == "closing":
                if self._closer == me or self._is_subtree_thread():
                    return _incomplete(self._path, start)
                waiting = True
            else:
                waiting = False
                self._state = "closing"
                self._closer = me
                self._deadline = deadline
                self._limit = limit
                self._forget_root()
        if waiting:
            if self._done.wait(max(0.0, deadline - time.monotonic())) and self._report is not None:
                return self._report
            return _incomplete(self._path, start)

        acc = _Acc()
        try:
            with self._lock:
                segments = list(self._segments)
            for segment in reversed(segments):
                with self._lock:
                    entries = [entry for entry in segment if not entry.claimed]
                    for entry in entries:
                        entry.claimed = True
                        entry.releaser = me
                self._close_entries(entries, deadline, limit, acc)
        finally:
            hand_off = 0
            with self._lock:
                acc.merge(self._extra.report(self._path, start))
                acc.errors.extend(self._drain_thread_errors_locked(None))
                if not from_parent and self._parent is not None:
                    # Закрыта не родителем: счётчик уходит родителю (в его отчёт),
                    # в своём отчёте — 0. Корень держит счётчик сам.
                    hand_off, acc.emits = acc.emits, 0
                report = acc.report(self._path, start)
                self._extra = _Acc()
                # Сегменты не пересобираются: освобождённые записи уже удалены, остались
                # выжившие, а их entry.segment обязан указывать на живой список —
                # иначе самоотцепление выжившего потока промахнётся мимо области.
                self._report = report
                self._state = "closed"
            parent_scope = self._parent
            absorbed = True
            if hand_off:
                # Вне лока и ДО _done.set(): ждущий нас close родителя ещё не
                # закрыл свой отчёт — прибавка попадёт в него, а не в третий вид.
                assert parent_scope is not None
                absorbed = parent_scope._absorb_emits(hand_off)
            self._done.set()
            if not absorbed:
                # Третий вид — ПОСЛЕ _done.set(): медленный reporter не держит ждущих
                # этот close (ревью 0.3 р1 п.3).
                assert parent_scope is not None
                parent_scope._report_emits_after_chain(hand_off)
        if not from_parent:
            parent = self._parent
            if parent is not None:
                parent._detach_child(self)
            self._call_reporter(report)
        return report

    def _detach_child(self, child: Scope) -> None:
        """Досрочный ``child.close()``: отцепить запись ребёнка, если её не взял идущий close."""
        found: _Entry | None = None
        with self._lock:
            for segment in self._segments:
                for entry in segment:
                    if entry.res is child and not entry.claimed:
                        found = entry
                        break
                if found is not None:
                    break
            if found is None:
                return
            self._remove_locked(found)
            # Ссылки — вне лока: сборка ребёнка не должна идти под локом родителя.
            res, found.res = found.res, None
            scope, found.scope = found.scope, None
            found.state = "closed"
        del res, scope
        found.done.set()

    def _close_entry_early(self, entry: _Entry, budget_s: float | None) -> CloseReport | None:
        """``IHandle.close``: отцепить запись, затем закрыть тем же кодом, что и область.

        ``None`` — запись сейчас освобождает этот же поток (ресурс в своей фазе
        зовёт свою ручку) или идущий ``close`` области, который ждёт поток поддерева
        (вызывающий): ждать нельзя, ответ — ``complete=False`` без reporter'а и кэша.
        """
        start = time.monotonic()
        deadline = start + (self._budget_s if budget_s is None else budget_s)
        limit = deadline + self._kill_reserve_s
        acc = _Acc()
        with self._lock:
            if entry.finished:
                mine, wait = False, False
                acc.errors.extend(self._drain_thread_errors_locked(entry))
            elif entry.claimed:
                if entry.releaser == threading.get_ident() and not entry.done.is_set():
                    return None
                if (
                    self._state == "closing"
                    and entry.releaser == self._closer
                    and not entry.done.is_set()
                    and self._is_subtree_thread()
                ):
                    # Запись взял идущий close этой области, а он ждёт поток поддерева —
                    # этот. Ждать его нельзя (взаимное ожидание до срока): то же правило,
                    # что у реентрантного close области — сразу ``complete=False``, без
                    # reporter'а и без кэша в ручке (отчёт о записи даст close области).
                    return None
                else:
                    mine, wait = False, True
            else:
                mine, wait = True, False
                entry.claimed = True
                entry.releaser = threading.get_ident()
                self._remove_locked(entry)
        if mine:
            self._close_entries([entry], deadline, limit, acc)
            with self._lock:
                acc.errors.extend(self._drain_thread_errors_locked(entry))
        elif wait:
            if entry.done.wait(max(0.0, deadline - time.monotonic())):
                acc.survivors.extend(entry.out_survivors)
                acc.killed.extend(entry.out_killed)
                acc.errors.extend(entry.out_errors)
            else:
                acc.complete = False
        report = acc.report(entry.path, start)
        self._call_reporter(report)
        return report

    def note_emits_after_close(self, n: int) -> None:
        if isinstance(n, bool) or not isinstance(n, int):
            raise TypeError(f"note_emits_after_close: n — ожидается int, получено {type(n).__name__}")
        if n < 1:
            raise ValueError("note_emits_after_close: n — нужно int ≥ 1")
        if not self._absorb_emits(n):
            self._report_emits_after_chain(n)

    def _absorb_emits(self, n: int) -> bool:
        """``+n`` в первую незакрытую область цепочки; ``False`` — вся цепочка закрыта."""
        scope: Scope | None = self
        while scope is not None:
            with scope._lock:
                # Та же секция лока, что финальный блок _close: либо прибавка
                # попадёт в отчёт, либо область уже closed — идём к родителю.
                if scope._state != "closed":
                    scope._extra.emits += n
                    return True
            scope = scope._parent
        return False

    def _report_emits_after_chain(self, n: int) -> None:
        """Третий вид вызова reporter'а: цепочка закрыта, ``n`` отклонённых доставок."""
        report = CloseReport(
            path=self._path, elapsed_s=0.0, survivors=(), killed=(), errors=(), emits_after_close=n, kind="late_emits"
        )
        if self._reporter is None:
            _log.warning("область %s: %d доставок после закрытия цепочки, reporter'а нет", self._path, n)
            return
        self._call_reporter(report)

    def _call_reporter(self, report: CloseReport) -> None:
        reporter = self._reporter
        if reporter is None:
            return
        try:
            reporter(report)
        except Exception as exc:
            _log.warning("reporter области %s бросил %s", self._path, _error_text(exc))

    def _forget_root(self) -> None:
        """Корень с начатым close не попадает в ``unclosed_roots`` никогда."""
        if self._root_key is None:
            return
        with _roots_lock:
            _roots.pop(self._root_key, None)
        if self._finalizer is not None:
            self._finalizer.detach()
            self._finalizer = None

    # ---- live ---------------------------------------------------------------

    def live(self) -> list[dict]:
        with self._lock:
            snapshot = [
                (entry.path, entry.kind, entry.state, entry.res if entry.mode == _SCOPE else None)
                for segment in self._segments
                for entry in segment
            ]
        result: list[dict] = []
        for path, kind, state, child in snapshot:
            result.append({"path": path, "kind": kind, "state": state})
            if child is not None:
                result.extend(child.live())
        return result


# =============================================================================
# Дверь
# =============================================================================


def open_scope(
    path: str,
    *,
    budget_s: float,
    kill_reserve_s: float = 0.0,
    reporter: Reporter | None = None,
) -> IScope:
    """Создать корень области. Единственная дверь создания корня (ADR-BM-008, Q2)."""
    if not isinstance(path, str):
        raise TypeError(f"path: ожидается str, получено {type(path).__name__}")
    if not path:
        raise ValueError("path: нужна непустая строка")
    if reporter is not None and not callable(reporter):
        raise TypeError(f"reporter: ожидается вызываемое, получено {type(reporter).__name__}")
    root = Scope(
        path,
        parent=None,
        budget_s=_seconds("budget_s", budget_s),
        kill_reserve_s=_seconds("kill_reserve_s", kill_reserve_s),
        reporter=reporter,
    )
    key = next(_root_keys)
    with _roots_lock:
        _roots[key] = {"path": path, "state": "open"}
    root._root_key = key
    finalizer = weakref.finalize(root, _mark_abandoned, key)
    finalizer.atexit = False
    root._finalizer = finalizer
    return root
