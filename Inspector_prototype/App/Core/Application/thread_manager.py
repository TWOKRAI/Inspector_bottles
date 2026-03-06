# App/Core/Application/thread_manager.py
# -*- coding: utf-8 -*-
"""
ThreadManager — управление жизненным циклом QThread.
"""

from typing import Optional, Dict, List, Callable, Type, Any
from dataclasses import dataclass, field
from PyQt5.QtCore import QObject, QThread, pyqtSignal


@dataclass
class ThreadEntry:
    """Конфигурация потока в реестре."""
    thread_class: Type[QThread]
    factory: Optional[Callable[..., QThread]] = None
    auto_start: bool = True
    stop_timeout_ms: int = 2000
    
    # Runtime state
    instance: Optional[QThread] = field(default=None, repr=False)
    created: bool = field(default=False, repr=False)
    running: bool = field(default=False, repr=False)


class ThreadManager(QObject):
    """
    Управление всеми потоками приложения.
    """
    
    thread_created = pyqtSignal(str)
    thread_started = pyqtSignal(str)
    thread_stopped = pyqtSignal(str)
    all_stopped = pyqtSignal()
    
    def __init__(
        self,
        queue_manager: Any,
        stop_event: Any,
        parent=None,
    ):
        super().__init__(parent)
        
        self._queue_manager = queue_manager
        self._stop_event = stop_event
        
        self._entries: Dict[str, ThreadEntry] = {}
        self._order: List[str] = []
    
    # ═════════════════════════════════════════════════════════════════
    # Регистрация
    # ═════════════════════════════════════════════════════════════════
    
    def register(
        self,
        name: str,
        thread_class: Type[QThread],
        *,
        factory: Optional[Callable[..., QThread]] = None,
        auto_start: bool = True,
        stop_timeout_ms: int = 2000,
    ) -> "ThreadManager":
        """Регистрация потока. Chainable API."""
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
    
    def register_standard_threads(self) -> "ThreadManager":
        """
        Регистрация стандартных потоков приложения.
        Вызывается из Coordinator после создания ThreadManager.
        """
        # Image Update Thread — читает кадры из очереди
        from App.Core.Threads.thread_image_update import UpdateImage
        
        self.register(
            "image_update",
            UpdateImage,
            factory=lambda: UpdateImage(  # ← убрали **kwargs!
                queue_manager=self._queue_manager,
                stop_event=self._stop_event,
            ),
            auto_start=True,
            stop_timeout_ms=1000,
        )
        
        # Bot Thread — сообщения от бота
        from App.Core.Threads.thread_bot_message import BotThread
        
        self.register(
            "bot",
            BotThread,
            factory=lambda: BotThread(
                queue_manager=self._queue_manager,
                stop_event=self._stop_event,
            ),
            auto_start=True,
            stop_timeout_ms=500,
        )
        
        return self
    
    # ═════════════════════════════════════════════════════════════════
    # Создание и запуск
    # ═════════════════════════════════════════════════════════════════
    
    def create(self, name: str) -> Optional[QThread]:
        """Создать конкретный поток по имени."""
        entry = self._entries.get(name)
        if not entry:
            raise KeyError(f"Thread '{name}' not registered")
        
        if entry.created and entry.instance:
            return entry.instance
        
        # Создаём через фабрику или напрямую
        if entry.factory:
            thread = entry.factory()
        else:
            thread = entry.thread_class()
        
        entry.instance = thread
        entry.created = True
        
        # Подключаем сигнал завершения
        thread.finished.connect(lambda: self._on_thread_finished(name))
        
        self.thread_created.emit(name)
        return thread
    
    def create_all(self) -> None:
        """Создать все зарегистрированные потоки."""
        for name in self._order:
            self.create(name)
    
    def start(self, name: str) -> bool:
        """Запустить конкретный поток."""
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
        """Запустить все потоки с auto_start=True."""
        for name in self._order:
            entry = self._entries[name]
            if entry.auto_start:
                self.start(name)
    
    # ═════════════════════════════════════════════════════════════════
    # Остановка
    # ═════════════════════════════════════════════════════════════════
    
    def stop(self, name: str, wait: Optional[bool] = None) -> bool:
        """Остановить конкретный поток (graceful)."""
        entry = self._entries.get(name)
        if not entry or not entry.instance:
            return True
        
        if not entry.running:
            return True
        
        thread = entry.instance
        
        # Graceful stop
        if hasattr(thread, 'stop'):
            thread.stop()
        
        # Ждём завершения
        should_wait = wait if wait is not None else (entry.stop_timeout_ms > 0)
        if should_wait and entry.stop_timeout_ms > 0:
            if not thread.wait(entry.stop_timeout_ms):
                print(f"[ThreadManager] Thread '{name}' didn't stop, terminating...")
                thread.terminate()
                thread.wait(500)
        
        entry.running = False
        self.thread_stopped.emit(name)
        return True
    
    def stop_all(self, reverse: bool = True) -> None:
        """Остановить все потоки."""
        names = list(reversed(self._order)) if reverse else self._order
        
        for name in names:
            self.stop(name)
        
        self.all_stopped.emit()
    
    # ═════════════════════════════════════════════════════════════════
    # Доступ к потокам (для подключения сигналов!)
    # ═════════════════════════════════════════════════════════════════
    
    def get_thread(self, name: str) -> Optional[QThread]:
        """
        Получить поток по имени (для подключения сигналов).
        
        Usage:
            image_thread = thread_manager.get_thread("image_update")
            image_thread.frame_ready.connect(main_window.display_frame)
        """
        entry = self._entries.get(name)
        return entry.instance if entry else None
    
    def is_running(self, name: str) -> bool:
        """Работает ли поток?"""
        entry = self._entries.get(name)
        return entry.running if entry else False
    
    # ═════════════════════════════════════════════════════════════════
    # Private
    # ═════════════════════════════════════════════════════════════════
    
    def _on_thread_finished(self, name: str) -> None:
        """Callback когда поток сам завершился."""
        entry = self._entries.get(name)
        if entry:
            entry.running = False
            self.thread_stopped.emit(name)