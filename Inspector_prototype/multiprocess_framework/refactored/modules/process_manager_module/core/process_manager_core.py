"""
ProcessManagerCore - ядро управления процессами (Refactored).

Наследуется от BaseManager и использует ObservableMixin для логирования и мониторинга.
Является Сверхэго в архитектуре "Тройцы создания циклов".

ProcessManagerCore отвечает за:
- Создание процессов ОС
- Управление жизненным циклом процессов
- Мониторинг состояния процессов
- Управление приоритетами процессов
"""

import time
from typing import Dict, Any, Optional, List
from multiprocessing import Process, Event

from ...base_manager import BaseManager, ObservableMixin
from ...base_manager.interfaces import IBaseManager

# Компоненты управления процессами
from .process_lifecycle import ProcessLifecycle
from .process_priority import ProcessPriority
from .process_status import ProcessStatus


class ProcessManagerCore(BaseManager, ObservableMixin):
    """
    Ядро управления процессами ОС (Refactored).
    
    Наследуется от BaseManager и использует ObservableMixin для:
    - Единообразия со всеми менеджерами системы
    - Автоматического логирования через ObservableMixin
    - Стандартного жизненного цикла (initialize/shutdown)
    
    Является Сверхэго в архитектуре "Тройцы создания циклов":
    - ProcessManagerCore (Сверхэго) - управляет всеми процессами системы
    - ProcessModule (Эго) - базовый процесс, выполняет работу
    - WorkerManager (Ид) - управляет потоками внутри процесса
    
    Attributes:
        manager_name: Имя менеджера
        shared_resources: Менеджер общих ресурсов
        queue_registry: Реестр очередей
        config_manager: Менеджер конфигурации
        console_manager: Менеджер консолей
        stop_event: Событие остановки всех процессов
        _lifecycle: Управление жизненным циклом процессов
        _priority: Управление приоритетами процессов
        _status: Мониторинг статуса процессов
    """
    
    def __init__(
        self,
        manager_name: str = "ProcessManagerCore",
        shared_resources=None,
        queue_registry=None,
        config_manager=None,
        console_manager=None,
        logger=None,
        platform_adapter=None,
        stop_event: Optional[Event] = None,
        process=None
    ):
        """
        Инициализация ProcessManagerCore.
        
        Args:
            manager_name: Имя менеджера
            shared_resources: Менеджер общих ресурсов
            queue_registry: Реестр очередей
            config_manager: Менеджер конфигурации
            console_manager: Менеджер консолей
            logger: Менеджер логирования (для совместимости)
            platform_adapter: Адаптер платформы
            stop_event: Событие остановки всех процессов
            process: Ссылка на родительский процесс (опционально)
        """
        # Инициализация BaseManager
        BaseManager.__init__(self, manager_name=manager_name, process=process)
        
        # Инициализация ObservableMixin
        ObservableMixin.__init__(
            self,
            managers={},
            config={},
            auto_proxy=True  # Автоматические прокси-методы для логирования
        )
        
        # Сохраняем зависимости
        self.shared_resources = shared_resources
        self.queue_registry = queue_registry
        self.config_manager = config_manager
        self.console_manager = console_manager
        self.platform_adapter = platform_adapter
        
        # Событие остановки
        self.stop_event = stop_event or Event()
        
        # Компоненты управления процессами
        self._lifecycle = ProcessLifecycle(self.stop_event, logger=self)
        self._priority = ProcessPriority(logger=self, platform_adapter=platform_adapter)
        self._status = ProcessStatus(self._lifecycle.os_processes)
        
        # Логирование через ObservableMixin (если logger передан, используем его)
        self._legacy_logger = logger
    
    # ========================================================================
    # РЕАЛИЗАЦИЯ BaseManager - ЖИЗНЕННЫЙ ЦИКЛ
    # ========================================================================
    
    def initialize(self) -> bool:
        """
        Инициализация ProcessManagerCore.
        
        Returns:
            bool: True если инициализация успешна
        """
        try:
            # Настройка платформы
            if self.platform_adapter:
                self.platform_adapter.setup_multiprocessing()
            
            self.is_initialized = True
            self._log_info(f"ProcessManagerCore '{self.manager_name}' initialized")
            return True
        except Exception as e:
            self._log_error(f"Failed to initialize ProcessManagerCore '{self.manager_name}': {e}")
            return False
    
    def shutdown(self) -> bool:
        """
        Завершение работы ProcessManagerCore.
        
        Останавливает все процессы перед завершением.
        
        Returns:
            bool: True если завершение успешно
        """
        try:
            # Останавливаем все процессы
            self.stop_all_processes()
            
            # Закрываем все консоли
            if self.console_manager:
                self.console_manager.close_all()
            
            self.is_initialized = False
            self._log_info(f"ProcessManagerCore '{self.manager_name}' shut down")
            return True
        except Exception as e:
            self._log_error(f"Error during shutdown of ProcessManagerCore '{self.manager_name}': {e}")
            return False
    
    # ========================================================================
    # ПУБЛИЧНЫЙ API - УПРАВЛЕНИЕ ПРОЦЕССАМИ
    # ========================================================================
    
    def create_process(
        self,
        name: str,
        class_path: str,
        config: Optional[Dict[str, Any]] = None,
        priority: str = "normal"
    ) -> Optional[Process]:
        """
        Создание процесса ОС.
        
        Args:
            name: Имя процесса
            class_path: Путь к классу процесса (например, "module.ProcessClass")
            config: Конфигурация процесса
            priority: Приоритет процесса (normal, high, low)
            
        Returns:
            Process или None если создание не удалось
        """
        try:
            self._log_info(f"Creating process '{name}' from '{class_path}'")
            
            # Импортируем класс процесса
            module_path, class_name = class_path.rsplit('.', 1)
            module = __import__(module_path, fromlist=[class_name])
            process_class = getattr(module, class_name)
            
            # Создаем конфигурацию процесса
            process_config = config or {}
            process_config['name'] = name
            process_config['class'] = class_path
            
            # Сохраняем конфигурацию в ConfigManager
            if self.config_manager:
                # Сохраняем конфигурацию процесса в отдельную конфигурацию
                try:
                    process_config_obj = self.config_manager.get_config('processes')
                    if process_config_obj:
                        processes_dict = process_config_obj.data.copy()
                        processes_dict[name] = process_config
                        process_config_obj.data.update(processes_dict)
                    else:
                        # Создаем новую конфигурацию для процессов
                        self.config_manager.create_config('processes', {name: process_config})
                except Exception:
                    # Если не удалось сохранить, продолжаем без сохранения
                    pass
            
            # Создаем очереди (пропуск если уже созданы в двухфазном режиме)
            if self.queue_registry and not self.queue_registry.get_process_queues(name):
                queue_config = process_config.get('queues', {})
                self.queue_registry.create_and_register_queues(name, queue_config)
            
            # Connection bundle: queues + routing_map (телефонная книга — все процессы видят друг друга)
            queues = self.queue_registry.get_process_queues(name) if self.queue_registry else {}
            routing_map = dict(self.queue_registry.registered_queues) if self.queue_registry else {}
            process_data = self.shared_resources.get_process_data(name) if self.shared_resources else None
            custom = dict(process_data.custom) if process_data and process_data.custom else {}
            custom.setdefault('process_config', process_config)
            bundle = {"queues": queues, "config": process_config, "custom": custom, "routing_map": routing_map}
            
            from ..runner import run_process_function
            process = Process(
                target=run_process_function,
                args=(class_path, name, self.stop_event, bundle),
                name=name
            )
            
            # Добавляем в lifecycle и регистрируем приоритет
            self._lifecycle.add_process(process)
            self._priority.register_priority(name, priority)
            
            self._log_info(f"Process '{name}' created (priority: {priority})")
            return process
            
        except Exception as e:
            self._log_error(f"Failed to create process '{name}': {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def start_process(self, process_name: Optional[str] = None) -> bool:
        """
        Запуск процесса или всех процессов.
        
        Args:
            process_name: Имя процесса для запуска (None = все процессы)
            
        Returns:
            bool: True если успешно
        """
        if process_name:
            # Запускаем конкретный процесс
            process = self._lifecycle.get_process_by_name(process_name)
            if not process:
                self._log_warning(f"Process '{process_name}' not found")
                return False
            
            process.start()
            self._priority.apply_priority(process)
            self._log_info(f"Started process '{process_name}'")
            return True
        else:
            # Запускаем все процессы
            if not self._lifecycle.os_processes:
                self._log_warning("No processes to start")
                return False
            
            self._log_info(f"Starting {len(self._lifecycle.os_processes)} processes...")
            self._lifecycle.start_all()
            
            # Устанавливаем приоритеты
            for process in self._lifecycle.os_processes:
                self._priority.apply_priority(process)
            
            self._log_info("All processes started")
            return True
    
    def stop_process(self, process_name: Optional[str] = None) -> bool:
        """
        Остановка процесса или всех процессов.
        
        Args:
            process_name: Имя процесса для остановки (None = все процессы)
            
        Returns:
            bool: True если успешно
        """
        if process_name:
            # Останавливаем конкретный процесс
            process = self._lifecycle.get_process_by_name(process_name)
            if not process:
                self._log_warning(f"Process '{process_name}' not found")
                return False
            
            if process.is_alive():
                process.terminate()
                self._log_info(f"Stopped process '{process_name}'")
            return True
        else:
            # Останавливаем все процессы
            self._log_info("Stopping all processes...")
            self.stop_all_processes()
            self._log_info("All processes stopped")
            return True
    
    def stop_all_processes(self, timeout: float = 3.0):
        """
        Остановка всех процессов.
        
        Args:
            timeout: Таймаут ожидания для каждого процесса
        """
        self._lifecycle.stop_all(timeout)
    
    def create_processes_from_config(self, config_data: Dict[str, Any]) -> int:
        """
        Создает процессы ОС на основе конфигурации.
        
        Args:
            config_data: Словарь конфигураций процессов {name: config}
        
        Returns:
            Количество успешно созданных процессов
        """
        self._log_info("Creating OS processes from config...")
        
        created_count = 0
        for name, config in config_data.items():
            if not isinstance(config, dict):
                continue
            
            actual_name = config.get('name', name) or name
            class_path = config.get('class')
            
            if not class_path:
                self._log_error(f"Process '{name}' missing 'class' field, skipping")
                continue
            
            priority = config.get('priority', 'normal')
            
            process = self.create_process(actual_name, class_path, config, priority)
            if process:
                created_count += 1
        
        self._log_info(f"Created {created_count} processes")
        return created_count
    
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
        if self.config_manager:
            return self.config_manager.save_worker_to_config(
                process_name, worker_name, worker_class_path, config, priority, auto_start
            )
        return False
    
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
        if not self.config_manager:
            return False
        
        # Получаем текущую конфигурацию процесса
        current_config = self.config_manager.get_process_config() or {}
        
        if process_name not in current_config:
            self._log_warning(f"Process '{process_name}' not found in config")
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
        process = self._lifecycle.get_process_by_name(process_name)
        if process and process.is_alive() and self.queue_registry:
            self.queue_registry.create_and_register_queues(process_name, process_config.get('queues', {}))
        
        return True
    
    def get_process_status(self, process_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Получение статуса процесса или всех процессов.
        
        Args:
            process_name: Имя процесса (None = все процессы)
            
        Returns:
            Словарь со статусом или статусами всех процессов
        """
        if process_name:
            process = self._lifecycle.get_process_by_name(process_name)
            if not process:
                return {}
            
            # Получаем ProcessData для расширенной информации
            process_data = None
            if self.shared_resources:
                process_data = self.shared_resources.get_process_data(process_name)
            
            status = {
                'name': process_name,
                'alive': process.is_alive(),
                'pid': process.pid if process.is_alive() else None,
                'exitcode': process.exitcode
            }
            
            if process_data:
                status['state'] = process_data.to_dict() if hasattr(process_data, 'to_dict') else {}
            
            return status
        else:
            # Статусы всех процессов
            return self._status.get_all_status()
    
    def get_all_processes_status(self) -> Dict[str, Dict[str, Any]]:
        """
        Получение статусов всех процессов.
        
        Returns:
            Словарь статусов всех процессов
        """
        return self._status.get_all_status()
    
    # ========================================================================
    # ПУБЛИЧНЫЙ API - СТАТИСТИКА (из BaseManager)
    # ========================================================================
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Получение статистики ProcessManagerCore.
        
        Returns:
            Dict[str, Any]: Словарь со статистикой менеджера и процессов
        """
        # Базовая статистика из BaseManager
        stats = super().get_stats()
        
        # Добавляем специфичную статистику процессов
        process_stats = self._status.get_stats()
        stats.update({
            'processes': process_stats,
            'processes_count': len(self._lifecycle.os_processes),
            'alive_processes': process_stats.get('alive', 0),
            'dead_processes': process_stats.get('dead', 0)
        })
        
        return stats
    
    # ========================================================================
    # ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ
    # ========================================================================
    
    def has_process(self, process_name: str) -> bool:
        """
        Проверка наличия процесса.
        
        Args:
            process_name: Имя процесса
            
        Returns:
            bool: True если процесс зарегистрирован
        """
        return self._lifecycle.get_process_by_name(process_name) is not None
    
    def list_processes(self) -> List[str]:
        """
        Получение списка имен всех процессов.
        
        Returns:
            List[str]: Список имен процессов
        """
        return [p.name for p in self._lifecycle.os_processes]
    
    def _log_info(self, message: str, **kwargs):
        """Логирование через ObservableMixin или legacy logger."""
        if self._legacy_logger and hasattr(self._legacy_logger, 'info'):
            self._legacy_logger.info(message, **kwargs)
        else:
            ObservableMixin._log_info(self, message, **kwargs)
    
    def _log_error(self, message: str, **kwargs):
        """Логирование ошибок через ObservableMixin или legacy logger."""
        if self._legacy_logger and hasattr(self._legacy_logger, 'error'):
            self._legacy_logger.error(message, **kwargs)
        else:
            ObservableMixin._log_error(self, message, **kwargs)
    
    def _log_warning(self, message: str, **kwargs):
        """Логирование предупреждений через ObservableMixin или legacy logger."""
        if self._legacy_logger and hasattr(self._legacy_logger, 'warning'):
            self._legacy_logger.warning(message, **kwargs)
        else:
            ObservableMixin._log_warning(self, message, **kwargs)

