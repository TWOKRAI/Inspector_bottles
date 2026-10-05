# -*- coding: utf-8 -*-
"""Владение Qt-объектами через область (``IScope``) — Task 0.4.

Purpose:
    Связать время жизни ``QObject``/``QThread`` с областью владения base_manager.
    Область, закрываясь, отдаёт объект C++ (``deleteLater``); удаление идёт на
    потоке объекта. Qt, удаливший объект первым, закрывает область синхронно.
    ``flush_deferred_deletes`` выполняет отложенные удаления без цикла событий.

Public API:
    attach_qt(scope, obj, *, name=None) -> IHandle
        Привязать ``QObject`` к области (запись вида ``"qobject"``).
    flush_deferred_deletes() -> None
        Доставить ``DeferredDelete`` на потоке ``QCoreApplication``, пока
        модуль ставит новые ``deleteLater`` (до 16 проходов).
    QThreadHandle(thread, *, stop=None)
        ``Stoppable`` над ``QThread``: без ``kill`` (``terminate`` запрещён),
        не остановившийся поток — выживший.
    QtTreeMismatch(RuntimeError)
        Qt-родитель привязанного объекта вне объектов области и её предков.

Stability: lite

Правила (DESIGN §2.4, ADR-BM-008): вызовы Qt — никогда под локом модуля; под
локом только множества адресов и счётчик ``_posted``. Обработчик ``destroyed``
не держит объект (только слабые ссылки и адрес C++). Реестр адресов чистит
только ``_on_destroyed``, после ``scope.close()``. Это единственный файл
нового кода с вызовом ``deleteLater`` (G6).
"""

from __future__ import annotations

import functools
import itertools
import logging
import math
import threading
import time
import weakref
from collections.abc import Callable

import shiboken6

from multiprocess_framework.modules.base_manager.interfaces import IHandle, IScope
from multiprocess_framework.modules.frontend_module.core.qt_imports import (
    QCoreApplication,
    QDeadlineTimer,
    QEvent,
    QObject,
    QThread,
)

__all__ = ["QThreadHandle", "QtTreeMismatch", "attach_qt", "flush_deferred_deletes"]

_log = logging.getLogger(__name__)

_FLUSH_MAX_PASSES = 16

# Под _lock — только _reg и _posted; вызовов Qt под ним нет.
_lock = threading.RLock()
_reg: weakref.WeakKeyDictionary[IScope, set[int]] = weakref.WeakKeyDictionary()
_posted = 0
_counter = itertools.count(1)


class QtTreeMismatch(RuntimeError):
    """Qt-родитель привязанного объекта вне объектов области и её предков (правило C)."""


class _Att:
    """Связь «запись области ↔ объект». Держит обёртку до освобождения областью."""

    __slots__ = ("obj", "scope_ref", "destroyed", "__weakref__")

    def __init__(self, obj: QObject, scope_ref: weakref.ref, destroyed: bool = False) -> None:
        self.obj: QObject | None = obj
        self.scope_ref = scope_ref
        self.destroyed = destroyed


def _addr(obj: QObject) -> int:
    return shiboken6.getCppPointer(obj)[0]


def _note_posted() -> None:
    global _posted
    with _lock:
        _posted += 1


def _thread_alive(th: QThread, app: QCoreApplication) -> bool:
    """Поток объекта доставит ``deleteLater``: главный, работающий или ещё не запущенный."""
    return th == app.thread() or not th.isFinished()


def _tree_mismatch(scope: IScope, obj: QObject) -> str | None:
    """Проверка Qt-предка по правилу C. Текст несовпадения или ``None``.

    Звать только на потоке объекта (TOCTOU: ``parent()`` чужого потока небезопасен).
    """
    me = _addr(obj)
    with _lock:
        above: set[int] = set()
        anc = scope.parent
        while anc is not None:
            above |= _reg.get(anc, set())
            anc = anc.parent
        own = _reg.get(scope, set()) - {me}
    if not above:
        return None  # правило миграции: выше никто ничего не привязал
    owned = above | own
    p = obj.parent()
    if p is None:
        return None  # верхний объект (QTimer() без родителя и т. п.)
    while p is not None:
        if _addr(p) in owned:
            return None
        p = p.parent()
    return f"qt-tree mismatch: {type(obj).__name__} — Qt-родитель вне объектов области '{scope.path}' и её предков"


class _QtRelease:
    """Функция освобождения записи ``"qobject"`` (фаза 2 области, поток закрывающего)."""

    __slots__ = ("_att",)

    def __init__(self, att: _Att) -> None:
        self._att = att

    def __call__(self) -> None:
        att = self._att
        obj = att.obj
        att.obj = None
        if obj is None or att.destroyed or not shiboken6.isValid(obj):
            return
        mismatch: str | None = None
        thread_error: str | None = None
        scope = att.scope_ref()
        th = obj.thread()
        if scope is not None and QThread.currentThread() == th:
            mismatch = _tree_mismatch(scope, obj)
        app = QCoreApplication.instance()
        if app is not None and th != app.thread() and th.isFinished():
            thread_error = (
                f"qt-thread finished: {type(obj).__name__} — поток объекта не работает, объект не будет удалён"
            )
        del th
        # deleteLater ДО потери последней ссылки: владение уходит C++; иначе
        # обёртка удалила бы объект синхронно на чужом потоке (DESIGN §2.4).
        obj.deleteLater()
        _note_posted()
        del obj
        if mismatch is not None:
            raise QtTreeMismatch(mismatch)
        if thread_error is not None:
            raise RuntimeError(thread_error)


def _on_destroyed(att_ref: weakref.ref, scope_ref: weakref.ref, addr: int, *args: object) -> None:
    """Обработчик ``destroyed``: Qt удалил объект первым — область без него не нужна."""
    try:
        att = att_ref()
        if att is not None:
            att.destroyed = True
        scope = scope_ref()
        if scope is None:
            return
        try:
            # att is None: освобождён нами. scope.closed: истинно с начала close —
            # повторный close ждал бы первого (фриз flush; на QThread — ADR-BM-008).
            if att is not None and not scope.closed:
                scope.close()
        finally:
            with _lock:
                _reg.get(scope, set()).discard(addr)
    except Exception as exc:  # noqa: BLE001 - сигнал Qt не должен ронять поток
        _log.warning("qt_lifetime: ошибка в обработчике destroyed: %s: %s", type(exc).__name__, exc)


def attach_qt(scope: IScope, obj: QObject, *, name: str | None = None) -> IHandle:
    """Привязать ``obj`` к ``scope``. Порядок: проверки → own → реестр → destroyed.

    Закрытая область: объект освобождается (``deleteLater``) и бросается
    ``ScopeClosedError``; имя занято — ``ValueError``. В обоих случаях нет ни
    записи в реестре, ни подключения к ``destroyed``.
    """
    if not isinstance(obj, QObject):
        raise TypeError(f"attach_qt: ожидается QObject, получено {type(obj).__name__}")
    if shiboken6.isValid(obj) is False:
        raise ValueError("attach_qt: Qt-объект уже удалён")
    app = QCoreApplication.instance()
    if app is None:
        raise RuntimeError("attach_qt: нет QCoreApplication — deleteLater некому доставить")
    if not _thread_alive(obj.thread(), app):
        raise ValueError(
            f"attach_qt: поток объекта не работает ({type(obj).__name__}) — deleteLater не будет доставлен"
        )
    entry_name = name if name is not None else f"{type(obj).__name__}#{next(_counter)}"
    scope_ref = weakref.ref(scope)
    att = _Att(obj, scope_ref, destroyed=False)
    handle = scope.own(_QtRelease(att), name=entry_name, kind="qobject")
    addr = _addr(obj)
    with _lock:
        _reg.setdefault(scope, set()).add(addr)
    obj.destroyed.connect(functools.partial(_on_destroyed, weakref.ref(att), scope_ref, addr))
    return handle


def flush_deferred_deletes() -> None:
    """Выполнить отложенные удаления на потоке ``QCoreApplication`` без цикла событий.

    Повторяет проход, пока за проход модуль поставил новые ``deleteLater``
    (каскад: удаление ``a`` закрывает область, её ``_QtRelease`` ставит ``b``).
    Доставляется только ``DeferredDelete``: таймеры и сигналы — нет.
    """
    app = QCoreApplication.instance()
    if app is None:
        return
    if QThread.currentThread() != app.thread():
        raise RuntimeError(
            f"flush_deferred_deletes: только поток QCoreApplication, вызван из {threading.current_thread().name}"
        )
    for _ in range(_FLUSH_MAX_PASSES):
        with _lock:
            before = _posted
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        with _lock:
            if _posted == before:
                return
    _log.warning("flush_deferred_deletes: исчерпан предел %d проходов, каскад удалений не завершён", _FLUSH_MAX_PASSES)


class QThreadHandle:
    """``Stoppable`` над ``QThread`` (base_manager.interfaces). ``kill`` нет: ``terminate()`` запрещён (G6).

    Не остановившийся поток — выживший; объект не удаляется (нет abort
    «Destroyed while thread is still running»). Ручка держит ``QThread`` до
    подтверждённой остановки и ``close()``.
    """

    def __init__(self, thread: QThread, *, stop: Callable[[], None] | None = None) -> None:
        if not isinstance(thread, QThread):
            raise TypeError(f"QThreadHandle: ожидается QThread, получено {type(thread).__name__}")
        if stop is not None and not callable(stop):
            raise TypeError(f"QThreadHandle: stop должен быть вызываемым, получено {type(stop).__name__}")
        self._thread: QThread | None = thread
        self._stop = stop
        self._stop_lock = threading.Lock()
        self._stop_requested = False

    def request_stop(self) -> None:
        """Фаза 1: ``requestInterruption``, ``quit``, ``stop`` — один раз за жизнь ручки."""
        with self._stop_lock:
            if self._stop_requested:
                return
            self._stop_requested = True
        th = self._thread
        if th is not None and shiboken6.isValid(th):
            th.requestInterruption()
            th.quit()
        del th
        if self._stop is not None:
            self._stop()

    def join_until(self, deadline: float) -> bool:
        """Фаза 2: ждать до абсолютного ``time.monotonic()``. Из самого ``QThread`` — без ожидания."""
        th = self._thread
        if th is None or not shiboken6.isValid(th):
            return True
        if QThread.currentThread() == th:
            return th.isFinished()
        if not th.isRunning():
            return True  # не запущен или уже завершён
        ms = max(0, math.ceil((deadline - time.monotonic()) * 1000))
        return bool(th.wait(QDeadlineTimer(ms)))

    def close(self) -> None:
        """После подтверждённой остановки: ``deleteLater`` (если обёртка жива), ссылка отпускается."""
        th = self._thread
        self._thread = None
        if th is None:
            return
        if shiboken6.isValid(th):
            th.deleteLater()
            _note_posted()
        del th
