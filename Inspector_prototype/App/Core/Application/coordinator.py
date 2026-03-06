# App/Core/Application/coordinator.py
# -*- coding: utf-8 -*-
"""
ApplicationCoordinator — высокоуровневый фасад приложения.

Ответственность:
  - Инициализация всех слоёв (Config → Domain → IPC → UI)
  - Владение жизненным циклом: создание → запуск → остановка
  - Координация между менеджерами (но НЕ их реализация!)

НЕ делает:
  - Не управляет окнами напрямую (делегирует WindowManager)
  - Не управляет потоками напрямую (делегирует ThreadManager)
  - Не шлёт IPC сообщения (делегирует RouterManager)

Архитектура:
  Coordinator
    ├── Config (AppConfig)
    ├── Domain Layer
    │     ├── RegistersManager
    │     └── DataManager (координатор Camera/Region/Recipe)
    ├── Infrastructure Layer  
    │     └── RouterManager (уже есть во фреймворке)
    └── Application Layer
          ├── WindowManager (окна)
          ├── ThreadManager (потоки)
          └── SignalRouter (межвиджетные связи, опционально)
"""
from typing import Optional, Dict, Any
from pathlib import Path

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QObject, pyqtSignal
import qdarkstyle

# Config
from App.Core.Config.app_config import AppConfig, get_config, set_config

# Domain
from App.Core.Domain.Registers.manager import RegistersManager
from App.Core.Managers.data_manager import DataManager
from App.Core.Managers.camera_manager import CameraManager
from App.Core.Managers.region_manager import RegionManager
from App.Core.Managers.recipe_manager import RecipeManager
from App.Core.Managers.converter_manager import ConverterManager

# Infrastructure (IPC уже есть во фреймворке, импортируем)
try:
    from multiprocess_framework.refactored.modules.router_module import (
        RouterManager, QueueChannel, Message, MessageType
    )
    
    _ROUTER_AVAILABLE = True
except ImportError:
    RouterManager = None
    QueueChannel = None
    Message = None
    MessageType = None
    _ROUTER_AVAILABLE = False

# Application services
from App.Core.Application.window_manager import WindowManager
from App.Core.Application.thread_manager import ThreadManager


class ApplicationCoordinator(QObject):
    """
    Главный фасад приложения App Inspector.
    
    Единственный объект, который знает о всех остальных.
    Инициализация строго по порядку: Config → Domain → Infra → App → UI
    """
    
    # Сигналы для внешнего мира (тесты, мониторинг)
    initialized = pyqtSignal()      # Все слои созданы
    started = pyqtSignal()          # Приложение запущено
    shutting_down = pyqtSignal()    # Начало остановки
    finished = pyqtSignal()         # Полная остановка
    
    def __init__(
        self,
        queue_manager,           # Извне (создаётся выше)
        stop_event,              # Извне
        config_path: Optional[Path] = None,
        parent=None,
    ):
        super().__init__(parent)
        
        # Внешние зависимости (созданы выше, мы только используем)
        self._queue_manager = queue_manager
        self._stop_event = stop_event
        
        # Runtime state
        self._is_initialized = False
        self._is_running = False
        
        # Слои (инициализируем в _initialize())
        self._config: Optional[AppConfig] = None
        self._registers: Optional[RegistersManager] = None
        self._data_manager: Optional[DataManager] = None
        self._router: Optional[Any] = None
        self._window_manager: Optional[WindowManager] = None
        self._thread_manager: Optional[ThreadManager] = None
        
        # Сохраняем путь конфига для ленивой загрузки
        self._config_path = config_path

    # ═════════════════════════════════════════════════════════════════
    # Инициализация слоёв (строгий порядок!)
    # ═════════════════════════════════════════════════════════════════
    
    def initialize(self) -> bool:
        """
        Инициализация всех слоёв. Вызывается один раз перед run().
        
        Returns:
            True если успешно, False при ошибке
        """
        if self._is_initialized:
            return True
        
        try:
            # Layer 0: Config (cross-cutting)
            self._init_config()
            
            # Layer 1: Domain (Registers + Data)
            self._init_domain()
            
            # Layer 2: Infrastructure (IPC Router)
            self._init_infrastructure()
            
            # Layer 3: Application Services (Windows + Threads)
            self._init_application_services()
            
            # Связываем сигналы между слоями
            self._connect_cross_layer_signals()
            
            self._is_initialized = True
            self.initialized.emit()
            return True
            
        except Exception as e:
            print(f"[Coordinator] Initialization failed: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _init_config(self) -> None:
        """Layer 0: Config — читаем раз, потом не меняем."""
        if self._config_path:
            self._config = AppConfig.load(self._config_path)
        else:
            self._config = AppConfig.load()
        
        set_config(self._config)
        print(f"[Coordinator] Config loaded: {self._config.window.language}")
    
    def _init_domain(self) -> None:
        """Layer 1: Domain Models + Services."""
        # Registers — единый источник истины
        self._registers = RegistersManager()
        
        # DataManager — координатор структур данных
        converter = ConverterManager()
        recipe_manager = RecipeManager(converter=converter)
        
        self._data_manager = DataManager(
            registers_manager=self._registers,
            recipe_manager=recipe_manager,
            converter=converter,
        )
        
        print(f"[Coordinator] Domain layer initialized")
    
    def _init_infrastructure(self) -> None:
        """Layer 2: IPC (Router уже есть во фреймворке)."""
        if not _ROUTER_AVAILABLE:
            print("[Coordinator] Router not available, IPC disabled")
            self._router = None
            return
        
        # Router создаётся снаружи или здесь — зависит от фреймворка
        # Предполагаем, что нам передали готовый или создаём
        self._router = RouterManager("app_ui_router")
        
        # Регистрируем каналы
        channels = [
            "control_draw", "control_camera", "control_conveyor",
            "control_neuroun", "control_robot", "control_processing",
            "control_post_processing", "control_frame_process", "control_overlay",
        ]
        
        for channel_name in channels:
            queue = getattr(self._queue_manager, channel_name, None)
            if queue:
                self._router.register_channel(QueueChannel(channel_name, queue))
        
        self._router.initialize()
        
        # Подключаем RegistersManager к Router (для авто-отправки изменений)
        self._registers.subscribe_all(self._on_register_changed)
        
        print(f"[Coordinator] Infrastructure initialized, channels: {len(channels)}")
    
    def _init_application_services(self) -> None:
        """Layer 3: Windows + Threads."""
        # Qt Application (если ещё не создано)
        self._qt_app = QApplication.instance()
        if self._qt_app is None:
            import sys
            self._qt_app = QApplication(sys.argv)
        
        self._qt_app.setStyleSheet(qdarkstyle.load_stylesheet_pyqt5())
        
        # ThreadManager — владеет всеми потоками
        self._thread_manager = ThreadManager(
            queue_manager=self._queue_manager,
            stop_event=self._stop_event,
        )
        
        # WindowManager — владеет всеми окнами
        # Передаём только нужные зависимости, не self!
        self._window_manager = WindowManager(
            config=self._config,
            registers_manager=self._registers,
            data_manager=self._data_manager,
            # WindowManager НЕ знает про Coordinator напрямую
        )
        
        print(f"[Coordinator] Application services initialized")
    
    def _connect_cross_layer_signals(self) -> None:
        """Связь между слоями (через сигналы, не прямые вызовы)."""
        
        # ThreadManager → WindowManager (кадры)
        image_thread = self._thread_manager.get_thread("image_update")
        if image_thread:
            main_window = self._window_manager.get_window("main")
            if main_window:
                # ПОДКЛЮЧАЕМ СИГНАЛ ЗДЕСЬ!
                image_thread.frame_ready.connect(main_window.display_frame)
        
        # WindowManager → Coordinator (запросы действий)
        self._window_manager.reset_count_requested.connect(self._on_reset_count)
        self._window_manager.recipe_apply_requested.connect(self._on_apply_recipe)
        
        print(f"[Coordinator] Cross-layer signals connected")

    # ═════════════════════════════════════════════════════════════════
    # Runtime: запуск и остановка
    # ═════════════════════════════════════════════════════════════════
    
    def run(self) -> int:
        """
        Запуск главного цикла. Блокирующий вызов.
        
        Returns:
            Exit code (0 = success)
        """
        if not self._is_initialized:
            if not self.initialize():
                return 1
        
        self._is_running = True
        
        # Создаём и стартуем потоки
        self._thread_manager.create_all()
        self._thread_manager.start_all()
        
        # Показываем начальное окно
        self._window_manager.show_initial_window()
        
        self.started.emit()
        
        # Главный цикл Qt
        return self._qt_app.exec_()
    
    def shutdown(self) -> None:
        """Graceful shutdown всех слоёв в обратном порядке."""
        if not self._is_running:
            return
        
        self.shutting_down.emit()
        
        # 1. Останавливаем потоки (чтобы не приходили данные)
        if self._thread_manager:
            self._thread_manager.stop_all()
        
        # 2. Закрываем окна
        if self._window_manager:
            self._window_manager.close_all()
        
        # 3. Останавливаем IPC
        if self._router:
            self._router.shutdown()
        
        # 4. Сигнализируем бэкенду
        if self._stop_event:
            self._stop_event.set()
        
        self._is_running = False
        self.finished.emit()

    # ═════════════════════════════════════════════════════════════════
    # Callbacks (реакция на события из слоёв)
    # ═════════════════════════════════════════════════════════════════
    
    def _on_register_changed(self, register_name: str, field_name: str, value: Any) -> None:
        """
        Любое изменение регистра → отправка в бэкенд через Router.
        Вызывается из RegistersManager (observer pattern).
        """
        if not self._router:
            return
        
        # Получаем снапшот регистра
        reg_obj = self._registers.get_register(register_name)
        snapshot = reg_obj.model_dump() if reg_obj else {field_name: value}
        
        # Формируем сообщение
        channel = f"control_{register_name}"
        msg = (
            Message.create(MessageType.COMMAND, sender="app_ui")
            .set_channel(channel)
            .set_command("set_register", args={
                "register": register_name,
                "field": field_name,
                "value": value,
                "snapshot": snapshot,
            })
        )
        
        # Асинхронная отправка (не блокирует UI)
        self._router.send_async(msg)
    
    def _on_reset_count(self) -> None:
        """Запрос сброса счётчика из UI."""
        # Отправляем команду в бэкенд
        if self._router:
            msg = (
                Message.create(MessageType.COMMAND, sender="app_ui")
                .set_channel("control_robot")
                .set_command("reset_count")
            )
            self._router.send_async(msg)
    
    def _on_apply_recipe(self, recipe_id: str) -> None:
        """Запрос применения рецепта."""
        # Загружаем через DataManager
        if self._data_manager:
            self._data_manager.load_recipe(recipe_id)

    # ═════════════════════════════════════════════════════════════════
    # Публичный API (для тестов, мониторинга, расширений)
    # ═════════════════════════════════════════════════════════════════
    
    @property
    def config(self) -> AppConfig:
        return self._config
    
    @property
    def registers(self) -> RegistersManager:
        return self._registers
    
    @property
    def data_manager(self) -> DataManager:
        return self._data_manager
    
    @property
    def window_manager(self) -> WindowManager:
        return self._window_manager
    
    @property
    def thread_manager(self) -> ThreadManager:
        return self._thread_manager

    # ═════════════════════════════════════════════════════════════════
    # Context manager для удобства
    # ═════════════════════════════════════════════════════════════════
    
    def __enter__(self):
        self.initialize()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.shutdown()
        return False  # Не подавляем исключения


# ═════════════════════════════════════════════════════════════════════
# Entry point
# ═════════════════════════════════════════════════════════════════════

def create_and_run(
    queue_manager,
    stop_event,
    config_path: Optional[Path] = None,
) -> int:
    """
    Фабричная функция — единая точка входа.
    
    Usage:
        from App.Core.Application.coordinator import create_and_run
        exit_code = create_and_run(queue_manager, stop_event)
    """
    coordinator = ApplicationCoordinator(
        queue_manager=queue_manager,
        stop_event=stop_event,
        config_path=config_path,
    )
    
    # Graceful shutdown на SIGINT/SIGTERM
    import signal
    def signal_handler(signum, frame):
        print(f"\n[Coordinator] Signal {signum} received, shutting down...")
        coordinator.shutdown()
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Запуск
    try:
        return coordinator.run()
    except Exception as e:
        print(f"[Coordinator] Fatal error: {e}")
        coordinator.shutdown()
        return 1