"""
Утилитарный класс с логикой создания и управления процессами.

ProcessManagerCore содержит всю бизнес-логику управления процессами:
- Создание процессов ОС
- Запуск и остановка процессов
- Регистрация воркеров и очередей
- Управление конфигурациями

Используется ProcessManager для выполнения операций управления.
"""

from multiprocessing import Process
from typing import Dict, Any, Optional, Type
import importlib

from .process_lifecycle import ProcessLifecycle
from .process_priority import ProcessPriority
from .process_status import ProcessStatus
from ..runner.process_runner import _run_process_function
from ...Shared_resources_module.SharedResourcesManager import SharedResourcesManager
from ...Shared_resources_module.queue_registry import QueueRegistry
# ProcessConfiguration удален - конфигурация хранится в ProcessData.custom
from ...Config_module.config_manager import ConfigManager
from ...Console_module import ConsoleManager


class ProcessManagerCore:
    """
    Утилитарный класс с логикой управления процессами.
    
    Не является процессом - содержит только бизнес-логику.
    Используется ProcessManager для выполнения операций.
    
    Attributes:
        shared_resources: Менеджер общих ресурсов
        queue_registry: Реестр очередей
        config_manager: Менеджер конфигураций
        console_manager: Менеджер консолей
        logger: Логгер для записи событий
        lifecycle: Управление жизненным циклом процессов
        priority: Управление приоритетами процессов
        status: Статусы процессов
        platform: Адаптер платформы
        stop_event: Событие остановки
        _process_classes_cache: Кэш загруженных классов процессов
    """
    
    def __init__(
        self,
        shared_resources: SharedResourcesManager,
        queue_registry: QueueRegistry,
        config_manager: ConfigManager,
        console_manager: ConsoleManager,
        logger,
        platform_adapter,
        stop_event
    ):
        """
        Инициализация ProcessManagerCore.
        
        Args:
            shared_resources: Менеджер общих ресурсов
            queue_registry: Реестр очередей
            config_manager: Менеджер конфигураций
            console_manager: Менеджер консолей
            logger: Логгер (должен иметь методы info, warning, error)
            platform_adapter: Адаптер платформы
            stop_event: Событие остановки всех процессов
        """
        self.shared_resources = shared_resources
        self.queue_registry = queue_registry
        self.config_manager = config_manager
        self.console_manager = console_manager
        self.logger = logger
        self.platform = platform_adapter
        self.stop_event = stop_event
        
        # Компоненты управления процессами
        self.lifecycle = ProcessLifecycle(stop_event, logger)
        self.priority = ProcessPriority(logger, platform_adapter=platform_adapter)
        self.status = ProcessStatus([])
        
        # Кэш загруженных классов процессов
        self._process_classes_cache: Dict[str, Type] = {}
    
    def create_process(
        self,
        name: str,
        class_path: str,
        config: Dict[str, Any],
        priority: str = "normal"
    ) -> Optional[Process]:
        """
        Создает процесс ОС на основе конфигурации.
        
        Args:
            name: Имя процесса
            class_path: Путь к классу процесса (например, 'module.path.ClassName')
            config: Конфигурация процесса
            priority: Приоритет процесса (high, normal, low)
        
        Returns:
            Объект Process или None при ошибке
        """
        try:
            # Валидация класса процесса
            if not isinstance(class_path, str):
                self.logger.error(f"❌ Process '{name}' has invalid class (must be string path)", module="process_manager")
                return None
            
            # Загружаем класс процесса (валидация)
            if class_path not in self._process_classes_cache:
                process_class = self._load_process_class(class_path)
                if not process_class:
                    self.logger.error(f"❌ Process '{name}' class '{class_path}' cannot be loaded", module="process_manager")
                    return None
                self._process_classes_cache[class_path] = process_class
            
            # Формируем конфигурацию для ProcessData
            process_config_dict = config.get('config', {})
            managers_config = process_config_dict.get('managers', {})
            modules_config = process_config_dict.get('modules', {})
            process_config_data = {
                k: v for k, v in process_config_dict.items() 
                if k not in ['managers', 'modules']
            }
            
            # Конфигурация в формате словаря для ProcessData.custom
            config_dict = {
                'process': process_config_data,
                'managers': managers_config,
                'modules': modules_config
            }
            
            # Регистрируем ProcessData с конфигурацией
            self.shared_resources.register_process_with_config(
                process_name=name,
                config=config_dict,
                initial_state={
                    "status": "initializing",
                    "metadata": {
                        "priority": priority,
                        "class_path": class_path
                    }
                }
            )
            
            # Создаем очереди для процесса
            queue_config = process_config_dict.get('queues', {})
            self.queue_registry.create_and_register_queues(name, queue_config)
            
            # Настраиваем консоль для процесса
            self._configure_process_console(name, config)
            
            # Создаем процесс ОС
            process = Process(
                target=_run_process_function,
                args=(
                    class_path,
                    name,
                    self.stop_event,
                    self.shared_resources
                ),
                name=name
            )
            
            # Добавляем в lifecycle и регистрируем приоритет
            self.lifecycle.add_process(process)
            self.priority.register_priority(name, priority)
            
            self.logger.info(f"  ✅ Configured: {name} (priority: {priority})", module="process_manager")
            return process
            
        except Exception as e:
            self.logger.error(f"❌ Error creating process '{name}': {e}", module="process_manager")
            import traceback
            traceback.print_exc()
            return None
    
    def create_processes_from_config(self, config_data: Dict[str, Any]) -> int:
        """
        Создает процессы ОС на основе конфигурации.
        
        Args:
            config_data: Словарь конфигураций процессов {name: config}
        
        Returns:
            Количество успешно созданных процессов
        """
        self.logger.info("🔄 Creating OS processes...", module="process_manager")
        
        created_count = 0
        for name, config in config_data.items():
            if not isinstance(config, dict):
                continue
            
            actual_name = config.get('name', name) or name
            class_path = config.get('class')
            
            if not class_path:
                self.logger.error(f"❌ Process '{name}' missing 'class' field, skipping", module="process_manager")
                continue
            
            priority = config.get('priority', 'normal')
            
            process = self.create_process(actual_name, class_path, config, priority)
            if process:
                created_count += 1
        
        self.logger.info(f"✅ Created {created_count} processes", module="process_manager")
        return created_count
    
    def start_process(self, process_name: Optional[str] = None) -> bool:
        """
        Запускает процесс или все процессы.
        
        Args:
            process_name: Имя процесса для запуска (None = все процессы)
        
        Returns:
            True если успешно
        """
        if process_name:
            # Запускаем конкретный процесс
            process = self.lifecycle.get_process_by_name(process_name)
            if not process:
                self.logger.warning(f"⚠️ Process '{process_name}' not found", module="process_manager")
                return False
            
            process.start()
            self.priority.apply_priority(process)
            self.logger.info(f"🚀 Started process '{process_name}'", module="process_manager")
            return True
        else:
            # Запускаем все процессы
            if not self.lifecycle.os_processes:
                self.logger.warning("⚠️ No processes to start", module="process_manager")
                return False
            
            self.logger.info(f"🚀 Starting {len(self.lifecycle.os_processes)} processes...", module="process_manager")
            self.lifecycle.start_all()
            
            # Устанавливаем приоритеты
            for process in self.lifecycle.os_processes:
                self.priority.apply_priority(process)
            
            self.logger.info("✅ All processes started", module="process_manager")
            return True
    
    def stop_process(self, process_name: Optional[str] = None) -> bool:
        """
        Останавливает процесс или все процессы.
        
        Args:
            process_name: Имя процесса для остановки (None = все процессы)
        
        Returns:
            True если успешно
        """
        if process_name:
            # Останавливаем конкретный процесс
            process = self.lifecycle.get_process_by_name(process_name)
            if not process:
                self.logger.warning(f"⚠️ Process '{process_name}' not found", module="process_manager")
                return False
            
            if process.is_alive():
                process.terminate()
                self.logger.info(f"🛑 Stopped process '{process_name}'", module="process_manager")
            return True
        else:
            # Останавливаем все процессы
            self.logger.info("🛑 Stopping all processes...", module="process_manager")
            self.lifecycle.stop_all()
            self.console_manager.close_all()
            self.logger.info("✅ All processes stopped", module="process_manager")
            return True
    
    def register_worker(
        self,
        process_name: str,
        worker_name: str,
        worker_class_path: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
        priority: str = "normal",
        auto_start: bool = True
    ) -> bool:
        """
        Регистрирует воркер в процессе через конфигурацию.
        
        Args:
            process_name: Имя процесса
            worker_name: Имя воркера
            worker_class_path: Путь к классу воркера
            config: Конфигурация воркера
            priority: Приоритет воркера
            auto_start: Автоматически запускать воркер
        
        Returns:
            True если успешно
        """
        return self.config_manager.save_worker_to_config(
            process_name, worker_name, worker_class_path, config, priority, auto_start
        )
    
    def register_queue(
        self,
        process_name: str,
        queue_name: str,
        maxsize: int = 100
    ) -> bool:
        """
        Регистрирует очередь для процесса.
        
        Args:
            process_name: Имя процесса
            queue_name: Имя очереди
            maxsize: Максимальный размер очереди
        
        Returns:
            True если успешно
        """
        # Получаем текущую конфигурацию процесса
        current_config = self.config_manager.get_process_config()
        
        if process_name not in current_config:
            self.logger.warning(f"⚠️ Process '{process_name}' not found in config", module="process_manager")
            return False
        
        process_config = current_config[process_name]
        if not isinstance(process_config, dict):
            process_config = {}
            current_config[process_name] = process_config
        
        # Добавляем конфигурацию очереди
        if 'queues' not in process_config:
            process_config['queues'] = {}
        
        process_config['queues'][queue_name] = {'maxsize': maxsize}
        
        # Обновляем конфигурацию
        self.config_manager.update_process_config(current_config)
        
        # Если процесс уже создан, создаем очередь через QueueRegistry
        process = self.lifecycle.get_process_by_name(process_name)
        if process and process.is_alive():
            self.queue_registry.create_and_register_queues(process_name, process_config.get('queues', {}))
        
        return True
    
    def get_process_status(self, process_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Получает статус процесса или всех процессов.
        
        Args:
            process_name: Имя процесса (None = все процессы)
        
        Returns:
            Словарь со статусами
        """
        if process_name:
            process = self.lifecycle.get_process_by_name(process_name)
            if not process:
                return {}
            
            process_data = self.shared_resources.get_process_data(process_name)
            return {
                'name': process_name,
                'alive': process.is_alive(),
                'pid': process.pid if process.is_alive() else None,
                'state': process_data.to_dict() if process_data else {}
            }
        else:
            # Статусы всех процессов
            self.status = ProcessStatus(self.lifecycle.os_processes)
            return self.status.get_all_status() if self.status else {}
    
    def _load_process_class(self, class_path: str) -> Optional[Type]:
        """
        Загружает класс процесса из строки пути.
        
        Args:
            class_path: Путь к классу в формате 'module.path.ClassName'
        
        Returns:
            Класс процесса или None
        """
        if class_path in self._process_classes_cache:
            return self._process_classes_cache[class_path]
        
        try:
            module_path, class_name = class_path.rsplit('.', 1)
            module = importlib.import_module(module_path)
            process_class = getattr(module, class_name)
            self._process_classes_cache[class_path] = process_class
            return process_class
        except Exception as e:
            self.logger.warning(f"⚠️ Could not load process class '{class_path}': {e}", module="process_manager")
            return None
    
    def _configure_process_console(self, process_name: str, config: Dict[str, Any]):
        """Настраивает консоль для процесса."""
        console_config = config.get('console', {})
        if not console_config:
            return
        
        actual_name = config.get('name', process_name) or process_name
        enabled = console_config.get('enabled', True)
        recipient = console_config.get('recipient')
        title = console_config.get('title')
        
        self.console_manager.configure_process_console(
            process_name=actual_name,
            enabled=enabled,
            recipient=recipient,
            title=title
        )
        
        # Создаем консоль если процесс уже запущен
        if actual_name in self.console_manager._process_consoles:
            console_created = self.console_manager.create_process_console(actual_name)
            if console_created:
                all_queues = self.console_manager.get_all_queues(actual_name)
                if all_queues:
                    process_data = self.shared_resources.get_process_data(actual_name)
                    if process_data:
                        process_data.update_custom(console_queues=all_queues)
                        if all_queues:
                            process_data.update_custom(console_queue=all_queues[0])
                        
                        console_status = self.console_manager.get_status(actual_name)
                        process_data.update_custom(console_info={
                            'has_console': True,
                            'has_native': console_status.get('has_native_console', False),
                            'recipients': console_status.get('recipients', []),
                            'title': console_status.get('native_title'),
                            'channel_name': f"console.{actual_name}"
                        })

