"""
Менеджер процессов с правильной сериализацией для Windows.
Все конфигурации хранятся в ConfigManager и передаются процессам.

ПРИМЕЧАНИЕ: Для новой архитектуры с ProcessManager как процессом используйте:
- ProcessManagerBootstrap - для запуска ProcessManagerProcess
- ProcessManagerProcess - процесс-менеджер с воркерами и роутером
- ProcessManagerCore - утилитарный класс с логикой управления

Этот класс оставлен для обратной совместимости.
"""

from multiprocessing import Process, Event, Manager
from typing import Dict, Any, Optional, Type, Union
from pathlib import Path
import importlib

from ..core.process_lifecycle import ProcessLifecycle
from ..core.process_priority import ProcessPriority
from ..core.process_status import ProcessStatus
from ..runner.process_runner import _run_process_function
from ..platforms import get_platform_adapter
from ...Console_module import ConsoleManager

from ...Shared_resources_module.SharedResourcesManager import SharedResourcesManager
from ...Shared_resources_module.queue_registry import QueueRegistry
# ProcessConfiguration удален - конфигурация хранится в ProcessData.custom
# Используйте ComponentDataManager для доступа к конфигурации
from ...Config_module.config_manager import ConfigManager
from ...Logger_module import LoggerManager
from ..monitor.process_monitor import ProcessMonitor


class ProcessManager:
    """
    Менеджер процессов с централизованным хранением конфигураций в ConfigManager.
    
    Упрощенная архитектура:
    1. ConfigManager хранит ВСЕ конфигурации и валидирует их через указанные классы
    2. ProcessManager использует ConfigManager для получения конфигураций
    3. Все сериализуемые данные передаются через ConfigManager
    4. Использует платформо-зависимые адаптеры для кроссплатформенной поддержки
    """
    
    def __init__(self, platform_adapter=None, config: Optional[Union[str, Path, Dict[str, Any]]] = None):
        """
        Инициализация менеджера процессов.
        
        Args:
            platform_adapter: Адаптер платформы (если None, определяется автоматически)
            config: Конфигурация процессов (путь к файлу, словарь или None).
                   Если передан, автоматически загружается через load_config.
                   Если None, конфиг можно загрузить позже через load_config().
        """
        # Получаем адаптер платформы и настраиваем multiprocessing
        self.platform = platform_adapter or get_platform_adapter()
        self.platform.setup_multiprocessing()
        
        self.stop_event = Event()
        
        # Менеджер общих ресурсов (легковесный контейнер с ProcessStateRegistry)
        self.shared_resources = SharedResourcesManager()
        
        # ConfigManager создается локально в основном процессе
        self.config_manager = ConfigManager()
        
        # QueueRegistry создается локально с ссылкой на ProcessStateRegistry
        self.queue_registry = QueueRegistry(process_state_registry=self.shared_resources.process_state_registry)
        
        # Менеджер логирования
        self.logger = LoggerManager(config_manager=self.config_manager)
        self.logger.initialize()

        # Компоненты через композицию
        self.lifecycle = ProcessLifecycle(self.stop_event, self.logger)
        self.priority = ProcessPriority(self.logger, platform_adapter=self.platform)
        self.status = ProcessStatus([])  # Инициализируем пустым списком
        
        # Кэш загруженных классов процессов
        self._process_classes_cache: Dict[str, Type] = {}
        
        # Монитор состояний процессов
        self.process_monitor = ProcessMonitor(
            shared_resources=self.shared_resources,
            stop_event=self.stop_event,
            queue_registry=self.queue_registry,
            logger=self.logger  # Передаем сам logger, а не метод
        )
        
        # Менеджер консольных окон
        self.console_manager = ConsoleManager(logger=self.logger)
        
        # Если конфиг передан, загружаем его автоматически
        if config is not None:
            self.load_config(config)

    def load_config(self, config_source: Optional[Union[str, Path, Dict[str, Any]]] = None) -> Dict[str, Any]:
        """
        Загружает конфигурацию процессов через ConfigManager.
        
        Валидация выполняется в ConfigManager через указанный класс валидации.
        Автоматически загружает классы процессов из строк в кэш.
        
        Args:
            config_source: Путь к файлу конфигурации, словарь или None для дефолтной конфигурации
        
        Returns:
            Валидированный словарь конфигурации процессов
        """
        self.logger.info("🔄 Loading process configuration...", module="process_manager")
        
        # Делегируем всю работу ConfigManager (включая валидацию)
        validated_config = self.config_manager.load_process_config(config_source)
        
        # Сохраняем валидированную конфигурацию обратно в ConfigManager
        self.config_manager.update_process_config(validated_config)
        
        # Загружаем классы процессов в кэш и заменяем строки на классы
        self._load_and_replace_process_classes(validated_config)
        
        return validated_config

    def _load_and_replace_process_classes(self, config_data: Dict[str, Any]):
        """
        Загружает классы процессов в кэш для валидации.
        НЕ заменяет строки на классы - оставляет строки для сериализации на Windows.
        
        Args:
            config_data: Конфигурация процессов (НЕ модифицируется)
        """
        for name, config in config_data.items():
            if not isinstance(config, dict):
                continue
            
            class_path = config.get('class')
            if isinstance(class_path, str):
                # Загружаем класс только для валидации, но НЕ заменяем строку на класс
                # На Windows нужно передавать строки, а не объекты классов
                process_class = self._load_process_class(class_path)
                if process_class:
                    self._process_classes_cache[class_path] = process_class
                    # НЕ заменяем строку на класс - оставляем строку для сериализации
                else:
                    self.logger.warning(f"⚠️ Failed to load class '{class_path}' for process '{name}'", module="process_manager")

    def initialize_processes(self, config_source: Optional[Union[str, Path, Dict[str, Any]]] = None):
        """
        Инициализирует процессы на основе конфигурации.
        
        Порядок выполнения:
        1. Загрузка и валидация конфигурации через ConfigManager
        2. Фильтрация только включенных процессов
        3. Регистрация очередей для всех процессов
        4. Создание процессов ОС
        
        Args:
            config_source: Путь к файлу конфигурации, словарь или None
        """
        # Загружаем и валидируем конфигурацию через ConfigManager
        config_data = self.load_config(config_source)
        
        if not config_data:
            self.logger.warning("⚠️ No processes found in configuration", module="process_manager")
            return
        
        # Фильтруем только включенные процессы
        enabled_configs = {
            name: config 
            for name, config in config_data.items() 
            if isinstance(config, dict) and config.get('enabled', True)
        }
        
        if not enabled_configs:
            self.logger.warning("⚠️ No enabled processes found", module="process_manager")
            return
        
        self.logger.info(f"🔄 Initializing {len(enabled_configs)} processes...", module="process_manager")
        
        # Настраиваем консоли для процессов
        self._configure_consoles(enabled_configs)
        
        # Регистрируем очереди для всех процессов
        self._register_all_queues(enabled_configs)
        
        # Создаем процессы ОС
        self._create_os_processes(enabled_configs)
        
        # Обновляем ProcessStatus с актуальным списком процессов
        self.status = ProcessStatus(self.lifecycle.os_processes)
        
        self.logger.info(f"✅ Initialized {len(self.lifecycle.os_processes)} processes", module="process_manager")

    def _configure_consoles(self, config_data: Dict[str, Any]):
        """
        Настройка консолей для процессов на основе конфигурации.
        
        Поддерживаемая конфигурация:
        - console.enabled: true/false - включать/выключать вывод в консоль
        - console.group: "group_name" - группа для группировки процессов (опционально)
                       Если не указан, используется имя процесса (отдельная консоль)
        - console.title: "Custom Title" - кастомный заголовок окна консоли (опционально)
        
        Args:
            config_data: Конфигурация процессов
        """
        self.logger.info("🔄 Configuring console windows...", module="process_manager")
        
        for name, config in config_data.items():
            if not isinstance(config, dict):
                continue
            
            actual_name = config.get('name', name) or name
            console_config = config.get('console', {})
            
            # Если консоль не настроена, пропускаем
            if not console_config:
                continue
            
            # Получаем параметры консоли
            enabled = console_config.get('enabled', True)
            recipient = console_config.get('recipient')  # Может быть строкой или списком
            title = console_config.get('title')
            
            # Настраиваем консоль
            self.console_manager.configure_process_console(
                process_name=actual_name,
                enabled=enabled,
                recipient=recipient,  # None, строка или список
                title=title
            )
            
            # Формируем информационное сообщение
            if enabled and recipient:
                recipient_str = recipient if isinstance(recipient, str) else ', '.join(recipient)
                info_msg = f"  ✅ Console configured for {actual_name}: native + recipients [{recipient_str}]"
            elif enabled:
                info_msg = f"  ✅ Console configured for {actual_name}: native console only"
            elif recipient:
                recipient_str = recipient if isinstance(recipient, str) else ', '.join(recipient)
                info_msg = f"  ✅ Console configured for {actual_name}: recipients only [{recipient_str}]"
            else:
                info_msg = f"  ✅ Console configured for {actual_name}: disabled"
            
            if title:
                info_msg += f" [title: '{title}']"
            
            self.logger.info(info_msg, module="process_manager")
    
    def _register_all_queues(self, config_data: Dict[str, Any]):
        """
        Регистрирует очереди для всех процессов.
        
        Args:
            config_data: Конфигурация процессов
        """
        self.logger.info("🔄 Registering queues for all processes...", module="process_manager")
        
        for name, config in config_data.items():
            actual_name = config.get('name', name) or name
            queue_config = config.get('queues', {})
            
            if not queue_config:
                continue
            
            success = self.queue_registry.create_and_register_queues(
                actual_name,
                queue_config
            )
            
            if success:
                queues = self.queue_registry.get_process_queues(actual_name)
                self.logger.info(f"  ✅ Registered {len(queues)} queues for {actual_name}", module="process_manager")
            else:
                self.logger.warning(f"  ⚠️ Failed to register queues for {actual_name}", module="process_manager")

    def _create_os_processes(self, config_data: Dict[str, Any]):
        """
        Создает процессы ОС на основе конфигурации.
        
        Args:
            config_data: Конфигурация процессов
        """
        self.logger.info("🔄 Creating OS processes...", module="process_manager")
        
        for name, config in config_data.items():
            try:
                actual_name = config.get('name', name) or name
                class_path = config.get('class')
                
                if not class_path:
                    self.logger.error(f"❌ Process '{name}' missing 'class' field, skipping", module="process_manager")
                    continue
                
                # На Windows нужно передавать строку пути к классу, а не объект класса
                # Класс будет загружен в дочернем процессе
                if not isinstance(class_path, str):
                    self.logger.error(f"❌ Process '{name}' has invalid class (must be string path), skipping", module="process_manager")
                    continue
                
                # Проверяем, что класс может быть загружен (валидация)
                if class_path not in self._process_classes_cache:
                    process_class = self._load_process_class(class_path)
                    if not process_class:
                        self.logger.error(f"❌ Process '{name}' class '{class_path}' cannot be loaded, skipping", module="process_manager")
                        continue
                    self._process_classes_cache[class_path] = process_class
                
                priority = config.get('priority', 'normal')
                process_config_dict = config.get('config', {})
                
                # Формируем ProcessConfiguration из конфигурации процесса
                # Извлекаем конфигурации менеджеров и модулей из основной конфигурации
                managers_config = process_config_dict.get('managers', {})
                modules_config = process_config_dict.get('modules', {})
                process_config_data = {
                    k: v for k, v in process_config_dict.items() 
                    if k not in ['managers', 'modules']
                }
                
                # Создаем ProcessConfiguration
                process_config = ProcessConfiguration(
                    process=process_config_data,
                    managers=managers_config,
                    modules=modules_config
                )
                
                # Регистрируем ProcessData с конфигурацией перед созданием процесса
                # Это позволяет процессу получить конфигурацию через shared_resources.get_process_data()
                self.shared_resources.register_process_with_config(
                    process_name=actual_name,
                    config=process_config,
                    initial_state={
                        "status": "initializing",
                        "metadata": {
                            "priority": priority,
                            "class_path": class_path
                        }
                    }
                )
                
                # Создаем очереди для процесса через локальный QueueRegistry
                queue_config = process_config_dict.get('queues', {})
                self.queue_registry.create_and_register_queues(actual_name, queue_config)
                
                # Создаем консоль для процесса если настроена
                console_created = False
                if actual_name in self.console_manager._process_consoles:
                    # Создаем все консоли для процесса (родную + получатели)
                    console_created = self.console_manager.create_process_console(actual_name)
                    if console_created:
                        # Сохраняем все queues в ProcessData для доступа в дочернем процессе
                        all_queues = self.console_manager.get_all_queues(actual_name)
                        if all_queues:
                            process_data = self.shared_resources.get_process_data(actual_name)
                            if process_data:
                                # Сохраняем список queues для redirector (дублирование)
                                process_data.update_custom(console_queues=all_queues)
                                
                                # Для обратной совместимости сохраняем также первую queue
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
                        
                        self.logger.info(f"  ✅ Console created for {actual_name}", module="process_manager")
                
                # Создаем процесс ОС
                # Передаем строку пути к классу вместо объекта класса
                # На Windows передаем SharedResourcesManager напрямую (БЕЗ Manager)
                # Queue и Event сериализуемы сами по себе
                # Конфигурация уже загружена в ProcessData
                process = Process(
                    target=_run_process_function,
                    args=(
                        class_path,  # Передаем строку пути к классу
                        actual_name,
                        self.stop_event,
                        self.shared_resources  # Передаем SharedResourcesManager напрямую (БЕЗ Manager)
                    ),
                    name=actual_name
                )
                
                # Добавляем в lifecycle
                self.lifecycle.add_process(process)
                
                # Регистрируем приоритет
                self.priority.register_priority(actual_name, priority)
                
                self.logger.info(f"  ✅ Configured: {actual_name} (priority: {priority})", module="process_manager")
                
            except Exception as e:
                self.logger.error(f"❌ Error creating process '{name}': {e}", module="process_manager")
                import traceback
                traceback.print_exc()

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

    def start_processes(self):
        """Запускает все процессы и устанавливает приоритеты."""
        if not self.lifecycle.os_processes:
            self.logger.warning("⚠️ No processes to start", module="process_manager")
            return
        
        self.logger.info(f"🚀 Starting {len(self.lifecycle.os_processes)} processes...", module="process_manager")
        
        # Запускаем процессы
        self.lifecycle.start_all()
        
        # Устанавливаем приоритеты
        for process in self.lifecycle.os_processes:
            self.priority.apply_priority(process)
        
        # Запускаем монитор состояний процессов
        self.process_monitor.start()
        
        self.logger.info("✅ All processes started", module="process_manager")

    def stop_processes(self):
        """Корректно останавливает все процессы."""
        self.logger.info("🛑 Stopping all processes...", module="process_manager")
        
        # Останавливаем монитор состояний
        self.process_monitor.stop()
        
        # Останавливаем процессы
        self.lifecycle.stop_all()
        
        # Закрываем все консоли
        self.console_manager.close_all()

    def join_processes(self, timeout: float = 3.0):
        """
        Ожидает завершения процессов ОС.
        
        Args:
            timeout: Таймаут ожидания для каждого процесса в секундах
        """
        self.lifecycle.join_all(timeout)
    
    def wait_for_processes(self):
        """Ожидание завершения всех процессов"""
        self.lifecycle.wait_for_all()

    def get_process_status(self) -> Dict[str, Any]:
        """
        Получает статус всех процессов.
        
        Returns:
            Словарь со статусами процессов
        """
        return self.status.get_all_status() if self.status else {}

    def get_process_config(self) -> Dict[str, Any]:
        """
        Получает текущую конфигурацию процессов из ConfigManager.
        
        Returns:
            Словарь конфигурации процессов
        """
        return self.config_manager.get_process_config()
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Получает полную статистику менеджера процессов.
        
        Returns:
            Словарь со статистикой
        """
        process_config = self.get_process_config()
        enabled_count = sum(
            1 for config in process_config.values()
            if isinstance(config, dict) and config.get('enabled', True)
        )
        
        stats = {
            'processes': self.get_process_status(),
            'process_count': len(self.lifecycle.os_processes),
            'config_manager': {
                'total_configs': len(self.config_manager.get_all_configs()),
                'processes_config_loaded': self.config_manager.processes_config is not None,
                'processes_in_config': len(process_config),
                'enabled_processes': enabled_count
            },
            'shared_resources': self.shared_resources.get_stats()
        }
        
        if self.status:
            stats.update(self.status.get_stats())
        
        return stats

    # ========================================================================
    # СВОЙСТВА ДЛЯ УДОБСТВА
    # ========================================================================
    
    @property
    def os_processes(self):
        """Список процессов ОС."""
        return self.lifecycle.os_processes
    
    @property
    def is_running(self) -> bool:
        """Проверяет, запущены ли процессы."""
        return any(process.is_alive() for process in self.lifecycle.os_processes)

    # ========================================================================
    # РЕГИСТРАЦИЯ И КОНФИГУРАЦИЯ ПРОЦЕССОВ
    # ========================================================================
    
    def load_process_config(self, process_name: str, config_source: Union[str, Path, Dict[str, Any]]) -> bool:
        """
        Загружает индивидуальный конфиг для процесса с переопределением существующей конфигурации.
        
        Если процесс с таким именем уже существует в конфигурации, новый конфиг рекурсивно
        перезаписывает его данные (глубокий merge).
        
        Args:
            process_name: Имя процесса
            config_source: Путь к файлу конфигурации или словарь конфигурации
            
        Returns:
            True если конфиг успешно загружен и применен
        """
        try:
            self.logger.info(f"🔄 Loading individual config for process '{process_name}'...", module="process_manager")
            
            # Загружаем новый конфиг через ConfigManager
            if isinstance(config_source, (str, Path)):
                validated_config = self.config_manager.load_process_config(config_source)
            else:
                # Если словарь, валидируем через ConfigManager
                validated_config = self.config_manager.load_process_config(config_source)
            
            # Получаем текущую конфигурацию процессов
            current_config = self.config_manager.get_process_config()
            
            # Если процесс уже существует, мерджим конфиги рекурсивно
            if process_name in current_config:
                self.logger.info(f"🔄 Merging config for existing process '{process_name}'...", module="process_manager")
                merged_config = ConfigManager.deep_merge(current_config[process_name], validated_config.get(process_name, {}))
                current_config[process_name] = merged_config
            else:
                # Новый процесс
                if validated_config:
                    process_config = validated_config.get(process_name) or list(validated_config.values())[0]
                    current_config[process_name] = process_config
            
            # Обновляем конфигурацию в ConfigManager
            self.config_manager.update_process_config(current_config)
            
            # Загружаем класс процесса в кэш если есть
            if process_name in current_config:
                process_config = current_config[process_name]
                if isinstance(process_config, dict):
                    class_path = process_config.get('class')
                    if isinstance(class_path, str):
                        self._load_and_replace_process_classes({process_name: process_config})
            
            self.logger.info(f"✅ Config loaded for process '{process_name}'", module="process_manager")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Failed to load config for process '{process_name}': {e}", module="process_manager")
            import traceback
            traceback.print_exc()
            return False
    
    def register_process(
        self,
        name: str,
        class_path: str,
        config: Optional[Dict[str, Any]] = None,
        priority: str = "normal",
        enabled: bool = True,
        console_config: Optional[Dict[str, Any]] = None,
        queue_config: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Программная регистрация процесса.
        
        Args:
            name: Имя процесса
            class_path: Путь к классу процесса (например, 'module.path.ClassName')
            config: Конфигурация процесса
            priority: Приоритет процесса (high, normal, low)
            enabled: Включен ли процесс
            console_config: Конфигурация консоли
            queue_config: Конфигурация очередей
            
        Returns:
            True если процесс успешно зарегистрирован
        """
        try:
            self.logger.info(f"🔄 Registering process '{name}'...", module="process_manager")
            
            # Валидируем класс процесса
            process_class = self._load_process_class(class_path)
            if not process_class:
                self.logger.error(f"❌ Failed to load class '{class_path}' for process '{name}'", module="process_manager")
                return False
            
            # Формируем конфигурацию процесса
            process_config = {
                'name': name,
                'class': class_path,
                'priority': priority,
                'enabled': enabled,
                'config': config or {},
            }
            
            if console_config:
                process_config['console'] = console_config
            
            if queue_config:
                process_config['queues'] = queue_config
            
            # Получаем текущую конфигурацию и добавляем новый процесс
            current_config = self.config_manager.get_process_config()
            current_config[name] = process_config
            
            # Обновляем конфигурацию в ConfigManager
            self.config_manager.update_process_config(current_config)
            
            self.logger.info(f"✅ Process '{name}' registered", module="process_manager")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Failed to register process '{name}': {e}", module="process_manager")
            import traceback
            traceback.print_exc()
            return False
    
    def register_queue(self, process_name: str, queue_name: str, maxsize: int = 100) -> bool:
        """
        Регистрация очереди для процесса.
        
        Args:
            process_name: Имя процесса
            queue_name: Имя очереди
            maxsize: Максимальный размер очереди
            
        Returns:
            True если очередь успешно зарегистрирована
        """
        try:
            self.logger.info(f"🔄 Registering queue '{queue_name}' for process '{process_name}'...", module="process_manager")
            
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
            if process_name in [p.name for p in self.lifecycle.os_processes]:
                self.queue_registry.create_and_register_queues(process_name, process_config.get('queues', {}))
            
            self.logger.info(f"✅ Queue '{queue_name}' registered for process '{process_name}'", module="process_manager")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Failed to register queue '{queue_name}' for process '{process_name}': {e}", module="process_manager")
            return False
    
    def register_worker(
        self,
        process_name: str,
        worker_name: str,
        worker_function=None,
        worker_class_path: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
        priority: str = "normal",
        auto_start: bool = True
    ) -> bool:
        """
        Регистрация воркера в процессе.
        
        Воркер может быть зарегистрирован:
        - До запуска процесса (через конфиг)
        - После запуска процесса (через команду в процесс)
        
        Args:
            process_name: Имя процесса
            worker_name: Имя воркера
            worker_function: Функция воркера (если None, будет загружена из worker_class_path)
            worker_class_path: Путь к классу воркера (например, 'module.path.WorkerClass')
            config: Конфигурация воркера
            priority: Приоритет воркера (high, normal, low)
            auto_start: Автоматически запускать воркер при регистрации
            
        Returns:
            True если воркер успешно зарегистрирован
        """
        try:
            self.logger.info(f"🔄 Registering worker '{worker_name}' for process '{process_name}'...", module="process_manager")
            
            # Проверяем, запущен ли процесс
            process_running = any(
                p.name == process_name and p.is_alive() 
                for p in self.lifecycle.os_processes
            )
            
            if process_running:
                # Процесс запущен - отправляем команду через command_manager
                # Используем router для отправки команды в процесс
                from ...Message_module.message import Message
                from ...Message_module.message_types import MessageType
                
                command_message = Message(
                    message_type=MessageType.COMMAND,
                    sender="process_manager",
                    target=process_name,
                    content={
                        "command": "register_worker",
                        "data": {
                            "worker_name": worker_name,
                            "worker_class_path": worker_class_path,
                            "config": config or {},
                            "priority": priority,
                            "auto_start": auto_start
                        }
                    }
                )
                
                # Отправляем через router (если есть доступ)
                # Пока используем упрощенный вариант через shared_resources
                self.logger.info(f"📤 Sending worker registration command to running process '{process_name}'...", module="process_manager")
                
                # TODO: Реализовать отправку команды через router/command_manager
                # Пока сохраняем в конфиг для будущей регистрации
                if not self.config_manager.save_worker_to_config(
                    process_name, worker_name, worker_class_path, config, priority, auto_start
                ):
                    self.logger.warning(f"⚠️ Process '{process_name}' not found in config", module="process_manager")
                
            else:
                # Процесс еще не запущен - сохраняем в конфиг
                if not self.config_manager.save_worker_to_config(
                    process_name, worker_name, worker_class_path, config, priority, auto_start
                ):
                    self.logger.warning(f"⚠️ Process '{process_name}' not found in config", module="process_manager")
            
            self.logger.info(f"✅ Worker '{worker_name}' registered for process '{process_name}'", module="process_manager")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Failed to register worker '{worker_name}' for process '{process_name}': {e}", module="process_manager")
            import traceback
            traceback.print_exc()
            return False
    
