"""
Template Application - шаблонное приложение для Multiprocess Framework.

Это полноценное приложение, демонстрирующее использование всех модулей
фреймворка в реальном сценарии. Может использоваться как шаблон для
создания собственных многопроцессных приложений.

Демонстрирует полное использование всех модулей фреймворка:
- ProcessManagerCore - управление процессами ОС
- ProcessModule - базовый класс процессов
- WorkerManager - управление потоками (воркерами)
- ConfigManager - работа с конфигурациями
- DataSchemaManager - работа со схемами данных
- RouterManager - маршрутизация сообщений между процессами
- CommandManager - обработка команд
- LoggerManager - структурированное логирование
- DispatchModule - диспетчеризация сообщений
- SharedResourcesManager - общие ресурсы для всех процессов

Архитектура:
1. SharedResourcesManager - архив для всех процессов (очереди, память, события)
2. ConfigManager - управление конфигурациями всех процессов
3. DataSchemaManager - регистрация и валидация схем данных
4. ProcessManagerCore - управление процессами ОС
5. Процессы (создаются через ProcessManagerCore):
   - VisionProcess - обработка изображений
   - AIProcess - машинное обучение и анализ
   - DBProcess - работа с базой данных
   - UIProcess - пользовательский интерфейс (PyQt, опционально)

Использование:
    from multiprocess_framework.tests.integration.template_app import (
        TemplateApplication,
        AppConfigManager
    )

    config = AppConfigManager().load_config()
    app = TemplateApplication(config=config)
    app.initialize()
    app.start()
    # ... работа с приложением ...
    app.stop()

Документация:
    См. TEMPLATE_FRAMEWORK_GUIDE.md и TEMPLATE_USAGE.md для подробного руководства
"""

import time
import os
import sys
from typing import Dict, Any, Optional, List
from multiprocessing import Event

# Добавляем путь к модулям для импорта процессов
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))

from multiprocess_framework.modules.process_manager_module import ProcessManagerCore
from multiprocess_framework.modules.shared_resources_module import SharedResourcesManager
from multiprocess_framework.modules.config_module import ConfigManager
from multiprocess_framework.modules.data_schema_module import SchemaRegistry
from multiprocess_framework.modules.message_module import Message

from .config.app_config import AppConfigManager, AppConfig


class TemplateApplication:
    """
    Шаблонное приложение для демонстрации Multiprocess Framework.

    Это полноценное приложение, демонстрирующее:
    1. Инициализацию всех менеджеров
    2. Создание процессов ОС через ProcessManagerCore
    3. Межпроцессное взаимодействие через RouterManager
    4. Работу с конфигурациями через ConfigManager и DataSchemaManager
    5. Управление потоками через WorkerManager
    6. Использование всех модулей фреймворка

    Структура:
    - SharedResourcesManager - архив для всех процессов
    - ConfigManager - управление конфигурациями
    - DataSchemaManager - работа со схемами данных
    - ProcessManagerCore - управление процессами ОС
    - Процессы (создаются через ProcessManagerCore):
      * VisionProcess - обработка изображений
      * AIProcess - машинное обучение
      * DBProcess - работа с БД
      * UIProcess - PyQt интерфейс (опционально)
    """

    def __init__(self, config: Optional[AppConfig] = None, test_mode: bool = False):
        """
        Инициализация шаблонного приложения.

        Args:
            config: Конфигурация приложения (если None, используется дефолтная)
            test_mode: Режим тестирования - не запускает реальные ОС процессы
        """
        self.config = config or AppConfig()
        self.stop_event = Event()
        self.test_mode = test_mode  # Режим тестирования

        # Менеджеры фреймворка
        self.shared_resources: Optional[SharedResourcesManager] = None
        self.config_manager: Optional[ConfigManager] = None
        self.data_schema_manager: Optional[SchemaRegistry] = None
        self.process_manager: Optional[ProcessManagerCore] = None

        # Статус приложения
        self.is_running = False
        self.process_names: List[str] = []

        # Ссылки на процессы (для тестирования и доступа)
        self.vision_process = None
        self.ai_process = None
        self.db_process = None
        self.ui_process = None

    def initialize(self) -> bool:
        """
        Инициализация приложения.

        Порядок инициализации:
        1. SharedResourcesManager (архив для всех процессов)
        2. DataSchemaManager (схемы данных)
        3. ConfigManager (конфигурации)
        4. ProcessManagerCore (управление процессами ОС)
        5. Создание процессов через ProcessManagerCore

        Returns:
            bool: True если инициализация успешна
        """
        try:
            self.log_info("Initializing Template Application...", module="main")

            # 1. Создаем SharedResourcesManager (архив для всех процессов)
            self.shared_resources = SharedResourcesManager(manager_name="shared_resources")
            self.shared_resources.initialize()
            self.log_info("SharedResourcesManager initialized", module="main")

            # 2. Создаем SchemaRegistry для работы со схемами данных
            self.data_schema_manager = SchemaRegistry()
            self.log_info("SchemaRegistry initialized", module="main")

            # Регистрируем схемы данных для приложения
            if self.data_schema_manager:
                self._register_data_schemas()

            # 3. Создаем ConfigManager для работы с конфигурациями
            self.config_manager = ConfigManager(
                manager_name="config_manager",
                process=None,  # ConfigManager работает в главном процессе
            )
            self.config_manager.initialize()
            self.log_info("ConfigManager initialized", module="main")

            # Сохраняем конфигурацию приложения
            app_config_dict = {
                "vision_process_enabled": self.config.vision_process_enabled,
                "ai_process_enabled": self.config.ai_process_enabled,
                "db_process_enabled": self.config.db_process_enabled,
                "ui_process_enabled": self.config.ui_process_enabled,
                "vision_workers_count": self.config.vision_workers_count,
                "ai_workers_count": self.config.ai_workers_count,
                "db_workers_count": self.config.db_workers_count,
                "queue_maxsize": self.config.queue_maxsize,
            }
            self.config_manager.create_config("app", app_config_dict)

            # 4. Создаем ProcessManagerCore для управления процессами ОС
            self.process_manager = ProcessManagerCore(
                manager_name="process_manager",
                shared_resources=self.shared_resources,
                config_manager=self.config_manager,
                stop_event=self.stop_event,
            )
            self.process_manager.initialize()
            self.log_info("ProcessManagerCore initialized", module="main")

            # 5. Создаем процессы ОС через ProcessManagerCore
            self._create_processes()

            self.log_info("Template Application initialized successfully", module="main")
            return True

        except Exception as e:
            self.log_error(f"Error initializing application: {e}", module="main")
            import traceback

            traceback.print_exc()
            return False

    def _register_data_schemas(self):
        """Регистрация схем данных для приложения."""
        # Схема для изображений
        image_schema = {
            "type": "object",
            "properties": {
                "image_id": {"type": "string"},
                "image_data": {"type": "string", "format": "binary"},
                "width": {"type": "integer"},
                "height": {"type": "integer"},
                "format": {"type": "string"},
                "timestamp": {"type": "number"},
            },
            "required": ["image_id", "image_data"],
        }

        # Регистрируем схемы через SchemaRegistry
        # SchemaRegistry работает с Pydantic моделями, но можно использовать и JSON схемы
        try:
            self.data_schema_manager.register("image_data", image_schema)
        except Exception:
            # Если метод register не поддерживает JSON схемы напрямую, пропускаем
            pass

        # Схема для результатов обработки
        processing_result_schema = {
            "type": "object",
            "properties": {
                "image_id": {"type": "string"},
                "worker_id": {"type": "integer"},
                "result": {"type": "object"},
                "timestamp": {"type": "number"},
            },
            "required": ["image_id", "result"],
        }

        try:
            self.data_schema_manager.register("processing_result", processing_result_schema)
        except Exception:
            pass

    def _create_processes(self):
        """Создание процессов ОС через ProcessManagerCore."""
        # Базовый путь к процессам
        processes_base_path = "multiprocess_framework.tests.integration.template_app.processes"

        # Vision Process
        if self.config.vision_process_enabled:
            vision_config = {
                "workers_count": self.config.vision_workers_count,
                "queue_maxsize": self.config.queue_maxsize,
            }
            class_path = f"{processes_base_path}.vision_process.VisionProcess"
            result = self.process_manager.create_process(
                name="vision_process", class_path=class_path, config=vision_config, priority="normal"
            )
            if result:
                self.process_names.append("vision_process")
                try:
                    from multiprocess_framework.tests.integration.template_app.processes.vision_process import (
                        VisionProcess,
                    )

                    self.vision_process = VisionProcess(
                        name="vision_process", shared_resources=self.shared_resources, config=vision_config
                    )
                    init_result = self.vision_process.initialize()
                    if not init_result:
                        self.log_error(
                            "Failed to initialize local VisionProcess instance (returned False)",
                            module="main",
                        )
                        # Попробуем получить больше информации об ошибке
                        if hasattr(self.vision_process, "_lifecycle"):
                            state = getattr(self.vision_process, "is_initialized", "unknown")
                            self.log_error(f"Process state: {state}", module="main")
                except Exception as e:
                    self.log_error(f"Failed to create local VisionProcess instance: {e}", module="main")
                    import traceback

                    traceback.print_exc()
                self.log_info("Vision process created", module="main")

        # AI Process
        if self.config.ai_process_enabled:
            ai_config = {"workers_count": self.config.ai_workers_count, "queue_maxsize": self.config.queue_maxsize}
            class_path = f"{processes_base_path}.ai_process.AIProcess"
            result = self.process_manager.create_process(
                name="ai_process", class_path=class_path, config=ai_config, priority="normal"
            )
            if result:
                self.process_names.append("ai_process")
                try:
                    from multiprocess_framework.tests.integration.template_app.processes.ai_process import AIProcess

                    self.ai_process = AIProcess(
                        name="ai_process", shared_resources=self.shared_resources, config=ai_config
                    )
                    self.ai_process.initialize()
                except Exception as e:
                    self.log_error(f"Failed to create local AIProcess instance: {e}", module="main")
                self.log_info("AI process created", module="main")

        # DB Process
        if self.config.db_process_enabled:
            db_config = {"workers_count": self.config.db_workers_count, "queue_maxsize": self.config.queue_maxsize}
            class_path = f"{processes_base_path}.db_process.DBProcess"
            result = self.process_manager.create_process(
                name="db_process", class_path=class_path, config=db_config, priority="normal"
            )
            if result:
                self.process_names.append("db_process")
                try:
                    from multiprocess_framework.tests.integration.template_app.processes.db_process import DBProcess

                    self.db_process = DBProcess(
                        name="db_process", shared_resources=self.shared_resources, config=db_config
                    )
                    self.db_process.initialize()
                except Exception as e:
                    self.log_error(f"Failed to create local DBProcess instance: {e}", module="main")
                self.log_info("DB process created", module="main")

        # UI Process (опционально)
        if self.config.ui_process_enabled:
            ui_config = {"ui_enabled": True, "queue_maxsize": self.config.queue_maxsize}
            class_path = f"{processes_base_path}.ui_process.UIProcess"
            result = self.process_manager.create_process(
                name="ui_process", class_path=class_path, config=ui_config, priority="normal"
            )
            if result:
                self.process_names.append("ui_process")
                self.log_info("UI process created", module="main")

    def start(self):
        """Запуск приложения и всех процессов."""
        if self.is_running:
            self.log_warning("Application is already running", module="main")
            return

        self.log_info("Starting Template Application...", module="main")

        if self.test_mode:
            # В тестовом режиме не запускаем реальные ОС процессы
            # Локальные экземпляры уже созданы и инициализированы
            self.log_info("Test mode: skipping real process startup", module="main")
            self.is_running = True
            self.log_info("Template Application started (test mode)", module="main")
        else:
            # Запускаем все процессы через ProcessManagerCore
            for process_name in self.process_names:
                if self.process_manager.start_process(process_name):
                    self.log_info(f"Process {process_name} started", module="main")
                else:
                    self.log_error(f"Failed to start process {process_name}", module="main")

            # Даем время процессам запуститься
            time.sleep(0.5)

            self.is_running = True
            self.log_info("Template Application started", module="main")

    def stop(self):
        """Остановка приложения и всех процессов."""
        if not self.is_running:
            return

        self.log_info("Stopping Template Application...", module="main")

        # Устанавливаем событие остановки
        self.stop_event.set()

        # Останавливаем все процессы через ProcessManagerCore
        for process_name in self.process_names:
            if self.process_manager.stop_process(process_name):
                self.log_info(f"Process {process_name} stopped", module="main")

        # Ждем завершения процессов
        time.sleep(0.5)

        # Завершаем менеджеры
        if self.process_manager:
            self.process_manager.shutdown()
        if self.config_manager:
            self.config_manager.shutdown()
        # SchemaRegistry не требует shutdown
        if self.data_schema_manager:
            pass
        if self.shared_resources:
            self.shared_resources.shutdown()

        self.is_running = False
        self.log_info("Template Application stopped", module="main")

    def send_test_message(self):
        """Отправка тестового сообщения для демонстрации взаимодействия."""
        if "vision_process" not in self.process_names:
            self.log_warning("Vision process is not running", module="main")
            return

        # Создаем тестовое сообщение с изображением
        test_message = Message.create(
            type="data",
            sender="main",
            targets=["vision_process"],
            data={
                "type": "image",
                "image_data": b"fake_image_data",
                "image_id": "test_001",
                "width": 640,
                "height": 480,
                "format": "jpeg",
                "timestamp": time.time(),
            },
        )

        # Отправляем через SharedResourcesManager
        if self.shared_resources and self.shared_resources.queue_registry:
            queue = self.shared_resources.queue_registry.get_queue("vision_process", "input")
            if queue:
                queue.put(test_message.to_dict())
                self.log_info("Test message sent to vision_process", module="main")
            else:
                self.log_warning("Queue for vision_process not found", module="main")

    def get_stats(self) -> Dict[str, Any]:
        """Получение статистики приложения."""
        stats = {"is_running": self.is_running, "processes": {}}

        # Получаем статистику процессов через ProcessManagerCore
        if self.process_manager:
            for process_name in self.process_names:
                process_info = self.process_manager.get_process_info(process_name)
                if process_info:
                    stats["processes"][process_name] = {
                        "status": process_info.get("status", "unknown"),
                        "pid": process_info.get("pid"),
                        "created_at": process_info.get("created_at"),
                    }

        return stats

    def log_info(self, message: str, module: str = "main"):
        """Логирование информации (fallback если нет logger_manager)."""
        print(f"[INFO][{module}] {message}")

    def log_warning(self, message: str, module: str = "main"):
        """Логирование предупреждения."""
        print(f"[WARNING][{module}] {message}")

    def log_error(self, message: str, module: str = "main"):
        """Логирование ошибки."""
        print(f"[ERROR][{module}] {message}")


def main():
    """Главная функция для запуска шаблонного приложения."""
    # Создаем конфигурацию
    config_manager = AppConfigManager()
    config = config_manager.load_config()

    # Создаем и инициализируем приложение
    app = TemplateApplication(config=config)

    if not app.initialize():
        print("Failed to initialize application")
        return

    # Запускаем приложение
    app.start()

    try:
        # Отправляем тестовое сообщение
        time.sleep(1)  # Даем время процессам запуститься
        app.send_test_message()

        # Ждем некоторое время для демонстрации работы
        print("\nApplication is running. Press Ctrl+C to stop...")
        time.sleep(5)

        # Выводим статистику
        stats = app.get_stats()
        print(f"\nApplication stats: {stats}")

    except KeyboardInterrupt:
        print("\nStopping application...")
    finally:
        app.stop()


if __name__ == "__main__":
    main()
