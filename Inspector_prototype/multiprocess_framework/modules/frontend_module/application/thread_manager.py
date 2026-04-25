# -*- coding: utf-8 -*-
"""
ThreadManager — управление жизненным циклом QThread.
Workers строятся на QThread.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Type

from multiprocess_framework.modules.frontend_module.core.qt_imports import QObject, QThread, pyqtSignal


@dataclass
class ThreadEntry:
    """Конфигурация потока в реестре."""
    thread_class: Type[QThread]
    factory: Optional[Callable[..., QThread]] = None
    auto_start: bool = True
    stop_timeout_ms: int = 2000
    instance: Optional[QThread] = field(default=None, repr=False)
    created: bool = field(default=False, repr=False)
    running: bool = field(default=False, repr=False)


class ThreadManager(QObject):
    """Управление всеми потоками приложения (QThread-based)."""
    thread_created = pyqtSignal(str)
    thread_started = pyqtSignal(str)
    thread_stopped = pyqtSignal(str)
    all_stopped = pyqtSignal()

    def __init__(
        self,
        queue_manager: Optional[Any] = None,
        stop_event: Optional[Any] = None,
        parent=None,
    ):
        super().__init__(parent)
        self._queue_manager = queue_manager
        self._stop_event = stop_event
        self._entries: Dict[str, ThreadEntry] = {}
        self._order: List[str] = []

    def register(
        self,
        name: str,
        thread_class: Type[QThread],
        *,
        factory: Optional[Callable[..., QThread]] = None,
        auto_start: bool = True,
        stop_timeout_ms: int = 2000,
    ) -> "ThreadManager":
        """Регистрация потока. Chainable."""
        if name in self._entries:
            raise ValueError(f"Thread '{name}' already registered")
        self._entries[name] = ThreadEntry(
            thread_class=thread_class,
            factory=factory,
            auto_start=auto_start,
            stop_timeout_ms=stop_timeout_ms,
        )
        self._order.append(name)
        return self

    def create(self, name: str) -> Optional[QThread]:
        """Создать поток по имени."""
        entry = self._entries.get(name)
        if not entry:
            raise KeyError(f"Thread '{name}' not registered")
        if entry.created and entry.instance:
            return entry.instance
        if entry.factory:
            thread = entry.factory()
        else:
            thread = entry.thread_class()
        entry.instance = thread
        entry.created = True
        thread.finished.connect(lambda: self._on_thread_finished(name))
        self.thread_created.emit(name)
        return thread

    def create_all(self) -> None:
        for name in self._order:
            self.create(name)

    def start(self, name: str) -> bool:
        entry = self._entries.get(name)
        if not entry or not entry.instance:
            return False
        if entry.running:
            return True
        entry.instance.start()
        entry.running = True
        self.thread_started.emit(name)
        return True

    def start_all(self) -> None:
        for name in self._order:
            entry = self._entries[name]
            if entry.auto_start:
                self.start(name)

    def stop(self, name: str, wait: Optional[bool] = None) -> bool:
        entry = self._entries.get(name)
        if not entry or not entry.instance:
            return True
        if not entry.running:
            return True
        thread = entry.instance
        if hasattr(thread, "stop"):
            thread.stop()
        should_wait = wait if wait is not None else (entry.stop_timeout_ms > 0)
        if should_wait and entry.stop_timeout_ms > 0:
            if not thread.wait(entry.stop_timeout_ms):
                thread.terminate()
                thread.wait(500)
        entry.running = False
        self.thread_stopped.emit(name)
        return True

    def stop_all(self, reverse: bool = True) -> None:
        names = list(reversed(self._order)) if reverse else self._order
        for name in names:
            self.stop(name)
        self.all_stopped.emit()

    def get_thread(self, name: str) -> Optional[QThread]:
        entry = self._entries.get(name)
        return entry.instance if entry else None

    def is_running(self, name: str) -> bool:
        entry = self._entries.get(name)
        return entry.running if entry else False

    def _on_thread_finished(self, name: str) -> None:
        entry = self._entries.get(name)
        if entry:
            entry.running = False
            self.thread_stopped.emit(name)
