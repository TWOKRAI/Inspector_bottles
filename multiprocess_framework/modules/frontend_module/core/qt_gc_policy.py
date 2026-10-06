# -*- coding: utf-8 -*-
"""Политика памяти GUI-процесса: сборкой мусора владеет главный поток Qt — T1.

Purpose:
    В GUI-процессе автосборка ``gc`` выключена; сборка идёт по тику ``QTimer`` на
    потоке ``QCoreApplication`` и на явных границах (``collect_now``). Финализаторы
    Qt-обёрток тогда исполняются только на главном потоке, а не на случайном
    рабочем, которому выпало перейти порог поколения. Тонкий адаптер над ядром
    ``process_module/lifecycle/gc_discipline.py`` (слот процесса, ``collect_on``).

Public API:
    install_gui_memory_policy(app=None, *, interval_s=1.0, freeze=None,
                              freeze_after_s=5.0, observe=False, log=None) -> GuiMemoryPolicy
        Поставить политику (одна на процесс). Повтор — тот же объект.
    gui_memory_policy() -> GuiMemoryPolicy | None
        Установленная политика или ``None``.
    GuiMemoryPolicy
        ``collect_now() -> int``, ``enforce() -> bool``, ``set_observe(on)``,
        ``stats() -> dict``, ``uninstall()``.

Stability: lite

Правила: прямых вызовов ``gc.*`` в файле нет — всё через ядро (страж R1). Тик таймера —
только сборка: ``DeferredDelete`` доставит цикл событий. ``collect_now`` доставляет
отложенные удаления сам (``flush_deferred_deletes``) только вне цикла событий
(``loopLevel() == 0``). Таймер — ``QTimer(parent=app)``: ``QApplication`` переживает
рестарт UI, таймер живёт вместе с ним.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Optional

import shiboken6

from multiprocess_framework.modules.frontend_module.core.qt_imports import (
    QCoreApplication,
    QThread,
    QTimer,
)
from multiprocess_framework.modules.frontend_module.core.qt_lifetime import flush_deferred_deletes
from multiprocess_framework.modules.process_module.lifecycle.gc_discipline import (
    GcCollectionOwner,
    collect_on,
)

__all__ = ["GuiMemoryPolicy", "gui_memory_policy", "install_gui_memory_policy"]

_THREAD_ERROR = "install_gui_memory_policy: только поток QCoreApplication"

_policy: Optional["GuiMemoryPolicy"] = None


def _on_app_thread(app: QCoreApplication) -> bool:
    return QThread.currentThread() == app.thread()


class _QtMainThreadExecutor:
    """Исполнитель ядра: ``QTimer(parent=app)`` зовёт тик на потоке приложения.

    Без приложения на ``start`` таймер не создаётся — его подключат ``attach``
    (первый ``collect_now()`` или повторный ``install``).
    """

    def __init__(self, app: Optional[QCoreApplication]) -> None:
        self._app = app
        self._tick: Optional[Callable[[], int]] = None
        self._interval_ms = 1000
        self._timer: Optional[QTimer] = None

    def start(self, tick: Callable[[], int], *, interval_s: float) -> None:
        self._tick = tick
        self._interval_ms = max(1, round(interval_s * 1000))
        if self._app is not None:
            self.attach(self._app)

    def stop(self) -> None:
        self._tick = None
        timer, self._timer = self._timer, None
        if timer is not None and shiboken6.isValid(timer):
            timer.stop()
            timer.setParent(None)  # владение — обратно Python; обёртка уйдёт со ссылкой

    @property
    def attached(self) -> bool:
        return self._timer is not None and shiboken6.isValid(self._timer)

    def attach(self, app: QCoreApplication) -> None:
        """Подключить таймер к ``app``, если его ещё нет (или прежний умер с прежним app)."""
        if self._tick is None or self.attached:
            return
        if not _on_app_thread(app):
            return
        self._app = app
        timer = QTimer(app)
        timer.setInterval(self._interval_ms)
        timer.timeout.connect(self._on_timeout)
        timer.start()
        self._timer = timer

    def _on_timeout(self) -> None:
        tick = self._tick
        if tick is not None:
            tick()


class GuiMemoryPolicy:
    """Установленная политика памяти GUI. Методы — только с потока ``QCoreApplication``.

    Stability: lite

    Pre: политика установлена (``uninstall`` ещё не звали).
    Post ``collect_now()``: автосборка выключена; полная сборка выполнена; вне цикла
    событий доставлены отложенные удаления.
    """

    def __init__(self, owner: GcCollectionOwner, executor: _QtMainThreadExecutor) -> None:
        self._owner = owner
        self._executor = executor
        self._installed = True

    def collect_now(self) -> int:
        """Граница: ``enforce()``, таймер (если пора), полная сборка, flush вне цикла событий."""
        self._owner.enforce()
        self._attach_timer()
        collected = self._owner.collect(full=True)
        app = QCoreApplication.instance()
        if app is not None and _on_app_thread(app) and QThread.currentThread().loopLevel() == 0:
            flush_deferred_deletes()
        return collected

    def enforce(self) -> bool:
        """Автосборку включили извне → выключить снова. True — было нарушение."""
        return self._owner.enforce()

    def set_observe(self, on: bool) -> None:
        self._owner.set_observe(on)

    def stats(self) -> dict[str, Any]:
        """Счётчики ядра (13 примитивов) + ``timer_attached``."""
        data = self._owner.stats().to_dict()
        data["timer_attached"] = self._executor.attached
        return data

    def uninstall(self) -> None:
        """Снять политику: таймер остановлен, автосборка — как до установки. Повтор — no-op."""
        global _policy
        if not self._installed:
            return
        self._owner.release()
        self._installed = False
        if _policy is self:
            _policy = None

    # ── внутреннее ──

    def _attach_timer(self) -> None:
        app = QCoreApplication.instance()
        if app is not None:
            self._executor.attach(app)

    def _reinstall(self) -> None:
        self._owner.rearm_freeze()
        self._attach_timer()


def install_gui_memory_policy(
    app: Optional[QCoreApplication] = None,
    *,
    interval_s: float = 1.0,
    freeze: Optional[bool] = None,
    freeze_after_s: float = 5.0,
    observe: bool = False,
    log: Optional[Callable[[str], None]] = None,
) -> GuiMemoryPolicy:
    """Поставить политику памяти GUI-процесса (сборка — на главном потоке Qt).

    Stability: lite

    Pre: зовут с потока ``QCoreApplication`` (проверка первой, и при повторе;
    иначе ``RuntimeError``). ``app=None`` → ``QCoreApplication.instance()``; приложения
    может не быть (тесты) — тогда таймер подключится позже.
    Post: автосборка выключена, слот процесса занят исполнителем на ``QTimer``.
    Повтор: тот же объект, ``rearm_freeze()``, таймер подключён, если приложение есть.
    """
    global _policy
    if app is None:
        app = QCoreApplication.instance()
    if app is not None and not _on_app_thread(app):
        raise RuntimeError(_THREAD_ERROR)
    existing = _policy
    if existing is not None:
        existing._reinstall()
        return existing
    executor = _QtMainThreadExecutor(app)
    owner = collect_on(
        executor,
        interval_s=interval_s,
        freeze=freeze,
        freeze_after_s=freeze_after_s,
        observe=observe,
        log=log,
    )
    policy = GuiMemoryPolicy(owner, executor)
    _policy = policy
    return policy


def gui_memory_policy() -> Optional[GuiMemoryPolicy]:
    """Установленная политика или ``None``. Stability: lite."""
    return _policy
