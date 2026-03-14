"""
ProcessManager - главный процесс системы для управления многопроцессными приложениями.

ProcessManager наследуется от ProcessModule и выступает как:
- Централизованное хранилище SharedResources (общие ресурсы для всех процессов)
- Мониторинг всех процессов в системе
- Широковещательное общение между процессами
- Управление процессами в реальном времени (создание, запуск, остановка)
- Точка связывания всех процессов в системе

Использует ProcessManagerCore для выполнения операций управления процессами.
Обрабатывает команды через роутер с помощью специализированных воркеров.

Воркеры:
- priority_command_processor: Приоритетные команды (start/stop процесса) - REALTIME
- normal_command_processor: Обычные команды (register_worker, register_queue) - NORMAL
- batch_processor: Batch операции (статистика, мониторинг) - BATCH
- state_monitor: Мониторинг состояний процессов и broadcast изменений - NORMAL
"""

import time
from typing import Dict, Any, Optional
from multiprocessing import Event

from ...Process_module.process_module import ProcessModule
from ...Worker_module.worker_manager import ThreadConfig, ThreadPriority
from ..core.process_manager_core import ProcessManagerCore
from ..core.process_status import ProcessStatus
from ...Shared_resources_module.SharedResourcesManager import SharedResourcesManager
from ...Shared_resources_module.queue_registry import QueueRegistry
from ...Config_module.config_manager import ConfigManager
from ...Console_module import ConsoleManager
from ...Logger_module import LoggerManager
from ..platforms import get_platform_adapter


class ProcessManager(ProcessModule):
    """
    ProcessManager - главный процесс системы для управления многопроцессными приложениями.
    
    Наследуется от ProcessModule для единообразия архитектуры.
    Использует ProcessManagerCore для выполнения операций управления процессами.
    Обрабатывает команды через роутер с помощью специализированных воркеров.
    
    ProcessManager выступает как:
    - Централизованное хранилище SharedResources
    - Мониторинг всех процессов в системе
    - Широковещательное общение между процессами
    - Управление процессами в реальном времени
    - Точка связывания всех процессов
    
    Интеграция с модулями:
    - ConfigManager: удобная работа с конфигурациями процессов
    - ConsoleManager: управление консолями процессов (создание/удаление)
    - SharedResourcesManager: хранение общих ресурсов для всех процессов
    """
    
    def __init__(
        self,
        name: str = "ProcessManager",
        shared_resources: Optional[SharedResourcesManager] = None,
        config: Optional[Dict[str, Any]] = None
    ):
        """
        Инициализация ProcessManager.
        
        Args:
            name: Имя процесса (по умолчанию "ProcessManager")
            shared_resources: Менеджер общих ресурсов (создается новый если None)
            config: Конфигурация процесса
        """
        # Инициализируем ProcessModule
        super().__init__(name, shared_resources, config)
        
        # Создаем компоненты для ProcessManagerCore
        self.platform = get_platform_adapter()
        self.platform.setup_multiprocessing()
        
        # Stop event для управления процессами
        self.manager_stop_event = Event()
        
        # Создаем локальные менеджеры с интеграцией
        self.config_manager = ConfigManager()
        self.queue_registry = QueueRegistry(
            process_state_registry=self.shared_resources.process_state_registry
        )
        self.console_manager = ConsoleManager(logger=self.logger_manager)
        
        # Создаем ProcessManagerCore с логикой управления
        self.core = ProcessManagerCore(
            shared_resources=self.shared_resources,
            queue_registry=self.queue_registry,
            config_manager=self.config_manager,
            console_manager=self.console_manager,
            logger=self.logger_manager,
            platform_adapter=self.platform,
            stop_event=self.manager_stop_event
        )
        
        # Кэш предыдущих состояний для мониторинга
        self.previous_states: Dict[str, Dict[str, Any]] = {}
        self.monitor_poll_interval: float = 0.5  # Интервал мониторинга в секундах (fallback)
        
        # Подписка на события через EventManager
        self._setup_event_subscriptions()
        
        # Загружаем конфигурацию процессов из process_data
        process_data = self.shared_resources.get_process_data(self.name)
        if process_data and process_data.config:
            processes_config = process_data.config.process.get('processes_config')
            if processes_config:
                self._load_and_create_processes(processes_config)
    
    def _setup_event_subscriptions(self):
        """
        Настройка подписок на события через EventManager.
        
        Использует event-based мониторинг вместо polling для улучшения производительности.
        """
        if self.shared_resources and self.shared_resources.event_manager:
            event_manager = self.shared_resources.event_manager
            
            # Подписываемся на события изменения состояний процессов
            from ...Shared_resources_module.event_manager import EventType
            
            event_manager.subscribe(
                EventType.PROCESS_STATE_CHANGED,
                self._on_process_state_changed
            )
            
            event_manager.subscribe(
                EventType.PROCESS_REGISTERED,
                self._on_process_registered
            )
            
            event_manager.subscribe(
                EventType.PROCESS_UNREGISTERED,
                self._on_process_unregistered
            )
    
    def _on_process_state_changed(self, event_data: Dict[str, Any]):
        """Обработчик события изменения состояния процесса"""
        process_name = event_data.get("process_name")
        old_status = event_data.get("old_status")
        new_status = event_data.get("new_status")
        state = event_data.get("state", {})
        
        if process_name:
            # Обновляем кэш
            self.previous_states[process_name] = state.copy()
            
            # Обрабатываем изменение состояния
            self._handle_state_change(process_name, {"status": old_status}, state)
    
    def _on_process_registered(self, event_data: Dict[str, Any]):
        """Обработчик события регистрации процесса"""
        process_name = event_data.get("process_name")
        state = event_data.get("state", {})
        
        if process_name:
            self.log("INFO", f"New process registered: {process_name}", "process_manager")
            self.previous_states[process_name] = state.copy()
    
    def _on_process_unregistered(self, event_data: Dict[str, Any]):
        """Обработчик события удаления процесса"""
        process_name = event_data.get("process_name")
        
        if process_name:
            self.log("INFO", f"Process unregistered: {process_name}", "process_manager")
            if process_name in self.previous_states:
                del self.previous_states[process_name]
    
    def _init_application_threads(self):
        """
        Инициализация воркеров для обработки команд управления процессами и мониторинга.
        
        Создает четыре воркера с разными приоритетами:
        - Приоритетные команды (start/stop процесса) - REALTIME
        - Обычные команды (register_worker, register_queue) - NORMAL
        - Batch операции (статистика, мониторинг) - BATCH
        - Мониторинг состояний процессов - NORMAL
        """
        # Воркер для приоритетных команд (start/stop процесса)
        self.worker_manager.create_worker(
            "priority_command_processor",
            self._priority_command_loop,
            ThreadConfig(priority=ThreadPriority.REALTIME),  # 0.01s интервал
            auto_start=True
        )
        
        # Воркер для обычных команд (register_worker, register_queue)
        self.worker_manager.create_worker(
            "normal_command_processor",
            self._normal_command_loop,
            ThreadConfig(priority=ThreadPriority.NORMAL),  # 0.1s интервал
            auto_start=True
        )
        
        # Воркер для batch операций (статистика, мониторинг)
        self.worker_manager.create_worker(
            "batch_processor",
            self._batch_operations_loop,
            ThreadConfig(priority=ThreadPriority.BATCH),  # 1.0s интервал
            auto_start=True
        )
        
        # Воркер для мониторинга состояний процессов (event-based)
        self.worker_manager.create_worker(
            "state_monitor",
            self._state_monitoring_loop,
            ThreadConfig(priority=ThreadPriority.NORMAL),  # Event-based, не требует частого polling
            auto_start=True
        )
        
        # Воркер для обработки событий через роутер
        self.worker_manager.create_worker(
            "event_processor",
            self._event_processing_loop,
            ThreadConfig(priority=ThreadPriority.NORMAL),  # Обработка событий из роутера
            auto_start=True
        )
    
    def _priority_command_loop(self, stop_event, pause_event):
        """
        Обработка приоритетных команд управления процессами.
        
        Команды: start_process, stop_process, restart_process
        """
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.1)
                continue
            
            try:
                # Получаем сообщения из канала приоритетных команд
                messages = self.router_manager.receive(
                    channel='priority_commands',
                    timeout=0.01
                )
                
                for message in messages:
                    self._handle_priority_command(message)
                    
            except Exception as e:
                self.log("ERROR", f"Priority command processing error: {e}", "process_manager")
                time.sleep(0.1)
    
    def _normal_command_loop(self, stop_event, pause_event):
        """
        Обработка обычных команд управления процессами.
        
        Команды: register_worker, register_queue, update_config, configure_console
        """
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.1)
                continue
            
            try:
                # Получаем сообщения из канала обычных команд
                messages = self.router_manager.receive(
                    channel='normal_commands',
                    timeout=0.1
                )
                
                for message in messages:
                    self._handle_normal_command(message)
                    
            except Exception as e:
                self.log("ERROR", f"Normal command processing error: {e}", "process_manager")
                time.sleep(0.1)
    
    def _batch_operations_loop(self, stop_event, pause_event):
        """
        Обработка batch операций (статистика, мониторинг).
        
        Операции: get_stats, get_process_status, health_check, get_config
        """
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(1.0)
                continue
            
            try:
                # Получаем сообщения из канала batch операций
                messages = self.router_manager.receive(
                    channel='batch_operations',
                    timeout=1.0
                )
                
                for message in messages:
                    self._handle_batch_operation(message)
                    
            except Exception as e:
                self.log("ERROR", f"Batch operations error: {e}", "process_manager")
                time.sleep(1.0)
    
    def _state_monitoring_loop(self, stop_event: Event, pause_event: Event):
        """
        Мониторинг состояний процессов через события (event-based).
        
        Использует EventManager для получения событий вместо постоянного polling.
        Это значительно улучшает производительность и снижает задержку обнаружения изменений.
        
        Args:
            stop_event: Событие остановки потока
            pause_event: Событие паузы
        """
        self.log("INFO", "Process state monitor loop started (event-based)", "process_manager")
        
        # Получаем EventManager из shared_resources
        event_manager = self.shared_resources.event_manager if self.shared_resources else None
        new_event_event = event_manager.get_new_event_event() if event_manager else None
        
        while not stop_event.is_set() and not self.manager_stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.1)
                continue
            
            try:
                if event_manager and new_event_event:
                    # Event-based мониторинг: ждем события изменения состояния
                    # Используем wait с таймаутом для периодической проверки (fallback)
                    if new_event_event.wait(timeout=1.0):
                        # Есть новое событие - события обрабатываются через подписки
                        # (_on_process_state_changed вызывается автоматически)
                        new_event_event.clear()
                    else:
                        # Таймаут - периодическая проверка для новых процессов (fallback)
                        self._periodic_state_check()
                else:
                    # Fallback на polling если EventManager недоступен
                    self._polling_monitoring_fallback()
                    time.sleep(self.monitor_poll_interval)
                    
            except Exception as e:
                self.log("ERROR", f"Error in state monitoring loop: {e}", "process_manager")
                import traceback
                traceback.print_exc()
                time.sleep(0.1)
        
        self.log("INFO", "Process state monitor loop stopped", "process_manager")
    
    def _event_processing_loop(self, stop_event: Event, pause_event: Event):
        """
        Обработка событий через роутер (дополнительный канал для событий).
        
        Получает события из канала "system_events" роутера и обрабатывает их.
        Это дополняет подписки EventManager для обработки событий из других процессов.
        
        Args:
            stop_event: Событие остановки потока
            pause_event: Событие паузы
        """
        self.log("INFO", "Event processing loop started", "process_manager")
        
        while not stop_event.is_set() and not self.manager_stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.1)
                continue
            
            try:
                # Получаем события из канала system_events роутера
                messages = self.router_manager.receive(
                    channel='system_events',
                    timeout=0.1
                )
                
                for message in messages:
                    self._handle_system_event(message)
                    
            except Exception as e:
                self.log("ERROR", f"Error in event processing loop: {e}", "process_manager")
                time.sleep(0.1)
        
        self.log("INFO", "Event processing loop stopped", "process_manager")
    
    def _handle_system_event(self, message: Dict[str, Any]):
        """
        Обработка системного события из роутера.
        
        Args:
            message: Сообщение события из роутера
        """
        try:
            content = message.get('content', {})
            event_type = content.get('event_type')
            process_name = content.get('process_name')
            
            if not event_type or not process_name:
                return
            
            from ...Shared_resources_module.event_manager import EventType
            
            # Обрабатываем событие в зависимости от типа
            if event_type == EventType.PROCESS_STATE_CHANGED.value:
                old_status = content.get('old_status')
                new_status = content.get('new_status')
                state = content.get('state', {})
                
                # Обновляем кэш и обрабатываем изменение
                self.previous_states[process_name] = state.copy()
                self._handle_state_change(
                    process_name,
                    {"status": old_status} if old_status else None,
                    state
                )
            
            elif event_type == EventType.PROCESS_REGISTERED.value:
                state = content.get('state', {})
                self.log("INFO", f"Process registered via event: {process_name}", "process_manager")
                self.previous_states[process_name] = state.copy()
            
            elif event_type == EventType.PROCESS_UNREGISTERED.value:
                self.log("INFO", f"Process unregistered via event: {process_name}", "process_manager")
                if process_name in self.previous_states:
                    del self.previous_states[process_name]
        
        except Exception as e:
            self.log("ERROR", f"Error handling system event: {e}", "process_manager")
    
    def _periodic_state_check(self):
        """
        Периодическая проверка состояний (fallback для новых процессов).
        
        Выполняется при таймауте события для обнаружения процессов,
        которые могли быть пропущены событиями.
        """
        try:
            all_states = self.shared_resources.get_all_process_states()
            
            # Проверяем новые процессы
            current_processes = set(all_states.keys())
            previous_processes = set(self.previous_states.keys())
            new_processes = current_processes - previous_processes
            
            for process_name in new_processes:
                self.log("INFO", f"New process detected (periodic check): {process_name}", "process_manager")
                self.previous_states[process_name] = all_states[process_name].copy()
            
            # Проверяем удаленные процессы
            removed_processes = previous_processes - current_processes
            for process_name in removed_processes:
                self.log("INFO", f"Process removed (periodic check): {process_name}", "process_manager")
                if process_name in self.previous_states:
                    del self.previous_states[process_name]
        
        except Exception as e:
            self.log("ERROR", f"Error in periodic state check: {e}", "process_manager")
    
    def _polling_monitoring_fallback(self):
        """
        Fallback на polling мониторинг если EventManager недоступен.
        
        Используется только если EventManager не инициализирован.
        """
        try:
            # Получаем все состояния процессов
            all_states = self.shared_resources.get_all_process_states()
            
            # Проверяем изменения состояний
            for process_name, current_state in all_states.items():
                previous_state = self.previous_states.get(process_name)
                
                # Если состояние изменилось
                if previous_state != current_state:
                    self._handle_state_change(process_name, previous_state, current_state)
                    self.previous_states[process_name] = current_state.copy()
            
            # Проверяем новые процессы
            current_processes = set(all_states.keys())
            previous_processes = set(self.previous_states.keys())
            new_processes = current_processes - previous_processes
            
            for process_name in new_processes:
                self.log("INFO", f"New process detected: {process_name}", "process_manager")
                self.previous_states[process_name] = all_states[process_name].copy()
            
            # Проверяем удаленные процессы
            removed_processes = previous_processes - current_processes
            for process_name in removed_processes:
                self.log("INFO", f"Process removed: {process_name}", "process_manager")
                if process_name in self.previous_states:
                    del self.previous_states[process_name]
        
        except Exception as e:
            self.log("ERROR", f"Error in polling monitoring fallback: {e}", "process_manager")
    
    def _handle_state_change(
        self,
        process_name: str,
        previous_state: Optional[Dict[str, Any]],
        current_state: Dict[str, Any]
    ):
        """
        Обработка изменения состояния процесса.
        
        Args:
            process_name: Имя процесса
            previous_state: Предыдущее состояние (None для новых процессов)
            current_state: Текущее состояние
        """
        current_status = current_state.get("status", "unknown")
        previous_status = previous_state.get("status", "unknown") if previous_state else None
        
        # Если статус изменился
        if previous_status != current_status:
            self.log("INFO", f"Process '{process_name}' status changed: {previous_status} -> {current_status}", "process_manager")
            
            # Отправляем broadcast сообщение о изменении статуса
            self._broadcast_status_change(process_name, previous_status, current_status, current_state)
    
    def _broadcast_status_change(
        self,
        process_name: str,
        old_status: Optional[str],
        new_status: str,
        current_state: Dict[str, Any]
    ):
        """
        Отправка broadcast сообщения об изменении статуса процесса.
        
        Использует ProcessCommunication для отправки через роутер.
        
        Args:
            process_name: Имя процесса
            old_status: Старый статус
            new_status: Новый статус
            current_state: Текущее состояние процесса
        """
        try:
            # Создаем сообщение об изменении статуса
            message = {
                "type": "system",
                "subtype": "process_status_changed",
                "sender": self.name,
                "process_name": process_name,
                "old_status": old_status,
                "new_status": new_status,
                "state": current_state,
                "timestamp": time.time()
            }
            
            # Используем ProcessCommunication для broadcast через роутер
            sent_count = self.broadcast_message(message, exclude_self=True)
            
            if sent_count > 0:
                self.log("DEBUG", f"Broadcasted status change for '{process_name}' to {sent_count} processes", "process_manager")
            else:
                self.log("WARNING", f"No processes received status change for '{process_name}'", "process_manager")
                
        except Exception as e:
            self.log("ERROR", f"Failed to broadcast status change: {e}", "process_manager")
            import traceback
            traceback.print_exc()
    
    def _handle_priority_command(self, message: Dict[str, Any]):
        """Обработка приоритетной команды."""
        command = message.get('command')
        data = message.get('data', {})
        sender = message.get('sender')
        
        try:
            if command == 'start_process':
                process_name = data.get('process_name')
                success = self.core.start_process(process_name)
                self._send_response(sender, command, success, {'process_name': process_name})
                
            elif command == 'stop_process':
                process_name = data.get('process_name')
                success = self.core.stop_process(process_name)
                self._send_response(sender, command, success, {'process_name': process_name})
                
            elif command == 'restart_process':
                process_name = data.get('process_name')
                # Останавливаем и запускаем
                self.core.stop_process(process_name)
                time.sleep(0.5)
                success = self.core.start_process(process_name)
                self._send_response(sender, command, success, {'process_name': process_name})
                
            else:
                self.log("WARNING", f"Unknown priority command: {command}", "process_manager")
                
        except Exception as e:
            self.log("ERROR", f"Error handling priority command '{command}': {e}", "process_manager")
            self._send_response(sender, command, False, {'error': str(e)})
    
    def _handle_normal_command(self, message: Dict[str, Any]):
        """Обработка обычной команды."""
        command = message.get('command')
        data = message.get('data', {})
        sender = message.get('sender')
        
        try:
            if command == 'register_worker':
                success = self.core.register_worker(
                    process_name=data.get('process_name'),
                    worker_name=data.get('worker_name'),
                    worker_class_path=data.get('worker_class_path'),
                    config=data.get('config'),
                    priority=data.get('priority', 'normal'),
                    auto_start=data.get('auto_start', True)
                )
                self._send_response(sender, command, success, data)
                
            elif command == 'register_queue':
                success = self.core.register_queue(
                    process_name=data.get('process_name'),
                    queue_name=data.get('queue_name'),
                    maxsize=data.get('maxsize', 100)
                )
                self._send_response(sender, command, success, data)
                
            elif command == 'update_config':
                process_name = data.get('process_name')
                new_config = data.get('config')
                # Обновляем конфигурацию через ConfigManager
                current_config = self.config_manager.get_process_config()
                if process_name in current_config:
                    merged_config = ConfigManager.deep_merge(
                        current_config[process_name],
                        new_config
                    )
                    current_config[process_name] = merged_config
                    self.config_manager.update_process_config(current_config)
                    success = True
                else:
                    success = False
                self._send_response(sender, command, success, {'process_name': process_name})
            
            elif command == 'configure_console':
                # Управление консолью процесса через ConsoleManager
                process_name = data.get('process_name')
                console_config = data.get('console_config', {})
                
                # Настраиваем консоль
                self.console_manager.configure_process_console(
                    process_name=process_name,
                    enabled=console_config.get('enabled', True),
                    recipient=console_config.get('recipient'),
                    title=console_config.get('title')
                )
                
                # Если процесс запущен, создаем/обновляем консоль
                process = self.core.lifecycle.get_process_by_name(process_name)
                if process and process.is_alive():
                    console_created = self.console_manager.create_process_console(process_name)
                    if console_created:
                        # Обновляем ProcessData с информацией о консоли
                        all_queues = self.console_manager.get_all_queues(process_name)
                        if all_queues:
                            process_data = self.shared_resources.get_process_data(process_name)
                            if process_data:
                                process_data.update_custom(console_queues=all_queues)
                                if all_queues:
                                    process_data.update_custom(console_queue=all_queues[0])
                
                self._send_response(sender, command, True, {'process_name': process_name})
                
            elif command == 'remove_console':
                # Удаление консоли процесса
                process_name = data.get('process_name')
                self.console_manager.remove_process_console(process_name)
                self._send_response(sender, command, True, {'process_name': process_name})
                
            else:
                self.log("WARNING", f"Unknown normal command: {command}", "process_manager")
                
        except Exception as e:
            self.log("ERROR", f"Error handling normal command '{command}': {e}", "process_manager")
            self._send_response(sender, command, False, {'error': str(e)})
    
    def _handle_batch_operation(self, message: Dict[str, Any]):
        """Обработка batch операции."""
        operation = message.get('operation')
        data = message.get('data', {})
        sender = message.get('sender')
        
        try:
            if operation == 'get_stats':
                stats = self.get_stats()
                self._send_response(sender, operation, True, {'stats': stats})
                
            elif operation == 'get_process_status':
                process_name = data.get('process_name')
                status = self.core.get_process_status(process_name)
                self._send_response(sender, operation, True, {'status': status})
                
            elif operation == 'health_check':
                # Проверка здоровья всех процессов
                alive_count = len([p for p in self.core.lifecycle.os_processes if p.is_alive()])
                total_count = len(self.core.lifecycle.os_processes)
                health = {
                    'alive_processes': alive_count,
                    'total_processes': total_count,
                    'status': 'healthy' if alive_count == total_count else 'degraded'
                }
                self._send_response(sender, operation, True, health)
            
            elif operation == 'get_config':
                # Получение конфигурации процесса или всех процессов
                process_name = data.get('process_name')
                if process_name:
                    config = self.config_manager.get_process_config()
                    process_config = config.get(process_name, {})
                    self._send_response(sender, operation, True, {'config': process_config})
                else:
                    all_configs = self.config_manager.get_process_config()
                    self._send_response(sender, operation, True, {'configs': all_configs})
                
            else:
                self.log("WARNING", f"Unknown batch operation: {operation}", "process_manager")
                
        except Exception as e:
            self.log("ERROR", f"Error handling batch operation '{operation}': {e}", "process_manager")
            self._send_response(sender, operation, False, {'error': str(e)})
    
    def _send_response(self, target: str, command: str, success: bool, data: Dict[str, Any]):
        """Отправка ответа на команду."""
        response = {
            'type': 'response',
            'command': command,
            'success': success,
            'data': data,
            'sender': self.name,
            'target': target
        }
        self.send(response)
    
    def _load_and_create_processes(self, config_source):
        """Загружает конфигурацию и создает процессы через ConfigManager."""
        try:
            # Загружаем конфигурацию через ConfigManager (удобная интеграция)
            validated_config = self.config_manager.load_process_config(config_source)
            self.config_manager.update_process_config(validated_config)
            
            # Фильтруем только включенные процессы
            enabled_configs = {
                name: config 
                for name, config in validated_config.items() 
                if isinstance(config, dict) and config.get('enabled', True)
            }
            
            if not enabled_configs:
                self.log("WARNING", "No enabled processes found in config", "process_manager")
                return
            
            # Настраиваем консоли через ConsoleManager
            self._configure_consoles(enabled_configs)
            
            # Регистрируем очереди
            self._register_all_queues(enabled_configs)
            
            # Создаем процессы
            self.core.create_processes_from_config(enabled_configs)
            
            # Обновляем статус
            self.core.status = ProcessStatus(self.core.lifecycle.os_processes)
            
            self.log("INFO", f"Created {len(enabled_configs)} processes from config", "process_manager")
            
        except Exception as e:
            self.log("ERROR", f"Error loading and creating processes: {e}", "process_manager")
            import traceback
            traceback.print_exc()
    
    def _configure_consoles(self, config_data: Dict[str, Any]):
        """
        Настройка консолей для процессов через ConsoleManager.
        
        Удобная интеграция с ConsoleManager для управления консолями процессов.
        """
        for name, config in config_data.items():
            if not isinstance(config, dict):
                continue
            
            actual_name = config.get('name', name) or name
            console_config = config.get('console', {})
            
            if not console_config:
                continue
            
            enabled = console_config.get('enabled', True)
            recipient = console_config.get('recipient')
            title = console_config.get('title')
            
            # Настраиваем консоль через ConsoleManager
            self.console_manager.configure_process_console(
                process_name=actual_name,
                enabled=enabled,
                recipient=recipient,
                title=title
            )
    
    def _register_all_queues(self, config_data: Dict[str, Any]):
        """Регистрация очередей для всех процессов."""
        for name, config in config_data.items():
            if not isinstance(config, dict):
                continue
            
            actual_name = config.get('name', name) or name
            queue_config = config.get('queues', {})
            
            if not queue_config:
                continue
            
            self.queue_registry.create_and_register_queues(actual_name, queue_config)
    
    def start_all_processes(self):
        """Запускает все управляемые процессы."""
        return self.core.start_process()
    
    def stop_all_processes(self):
        """Останавливает все управляемые процессы."""
        return self.core.stop_process()
    
    def get_stats(self) -> Dict[str, Any]:
        """Получает статистику ProcessManager с мониторингом."""
        stats = super().get_stats()
        stats.update({
            'managed_processes': len(self.core.lifecycle.os_processes),
            'alive_processes': len([p for p in self.core.lifecycle.os_processes if p.is_alive()]),
            'process_statuses': self.core.get_process_status(),
            'monitoring': {
                'tracked_processes': len(self.previous_states),
                'poll_interval': self.monitor_poll_interval
            },
            'shared_resources': self.shared_resources.get_stats(),
            'config_manager': {
                'processes_count': len(self.config_manager.get_process_config())
            }
        })
        return stats
    
    def register_from_config(self, config) -> bool:
        """
        Регистрирует процесс из ProcessConfig (декларативный подход).
        
        Удобный метод для регистрации процесса через класс-конфигурацию.
        
        Args:
            config: Экземпляр ProcessConfig из builders.configs
        
        Returns:
            True если регистрация успешна
        
        Пример:
            from ...Process_manager_module.builders import ProcessConfig, QueueConfig
            
            config = ProcessConfig(
                name="ChatProcess",
                class_path="module.ChatProcess",
                queues={"messages": QueueConfig(maxsize=100)}
            )
            pm.register_from_config(config)
        """
        from ..builders.registry import ProcessRegistry
        
        registry = ProcessRegistry()
        registry.register_from_config(config)
        return registry.apply_to(self) > 0
    
    def register_decorated(self, process_class) -> bool:
        """
        Регистрирует декорированный класс процесса (декларативный подход).
        
        Удобный метод для регистрации процесса через декоратор @process.
        
        Args:
            process_class: Класс процесса, декорированный @process
        
        Returns:
            True если регистрация успешна
        
        Пример:
            from ...Process_manager_module.builders import process
            
            @process(name="ChatProcess", priority="normal")
            class ChatProcess(ProcessModule):
                pass
            
            pm.register_decorated(ChatProcess)
        """
        from ..builders.registry import ProcessRegistry
        
        registry = ProcessRegistry()
        registry.register_decorated(process_class)
        return registry.apply_to(self) > 0
    
    def export_process_config(self, process_name: str) -> Optional[Dict[str, Any]]:
        """
        Экспортирует конфигурацию процесса из ProcessData.
        
        Создает конфиг-чертеж из существующей ProcessData (ДНК → чертеж).
        
        Args:
            process_name: Имя процесса для экспорта
        
        Returns:
            Словарь конфигурации процесса или None если процесс не найден
        
        Пример:
            config = pm.export_process_config("ChatProcess")
            # Сохранить в файл или использовать для регистрации нового процесса
        """
        process_data = self.shared_resources.get_process_data(process_name)
        if not process_data:
            return None
        
        return process_data.export_to_config()
    
    def export_all_configs(self) -> Dict[str, Dict[str, Any]]:
        """
        Экспортирует конфигурации всех процессов из ProcessData.
        
        Returns:
            Словарь конфигураций процессов {process_name: config_dict}
        
        Пример:
            all_configs = pm.export_all_configs()
            # Сохранить в файл или использовать для создания нового ProcessManager
        """
        from ..builders.export import export_all_processes_to_config
        
        return export_all_processes_to_config(self.shared_resources)

