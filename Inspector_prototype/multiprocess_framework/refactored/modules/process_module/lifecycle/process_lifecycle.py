"""
Жизненный цикл процесса.

Отвечает за инициализацию и завершение работы процесса.
"""

import traceback
from typing import Dict, Any, Optional

from ..types import ProcessStatus


class ProcessLifecycle:
    """
    Управление жизненным циклом процесса.
    
    Инкапсулирует логику инициализации и завершения работы.
    """
    
    def __init__(self, process):
        """
        Инициализация жизненного цикла.
        
        Args:
            process: Ссылка на ProcessModule
        """
        self.process = process
    
    def initialize(self) -> bool:
        """
        Инициализация процесса.
        
        Returns:
            bool: True если инициализация успешна
        """
        try:
            # 1. Инициализация конфигурации
            self.process._init_configuration()
            
            # 2. Инициализация очередей
            self.process._init_queues()
            
            # 3. Инициализация менеджеров через ObservableMixin
            self.process._init_managers()
            
            # 4. Инициализация коммуникации
            self.process._init_communication()
            
            # 5. Регистрация состояния процесса
            self.process._register_process_state()
            
            # 6. Воркеры и кастомные менеджеры — до message_processor,
            #    чтобы register_message_handler успел зарегистрироваться
            self.process._init_custom_managers()
            self.process._init_application_threads()
            
            # 7. Системные потоки (message_processor) — после воркеров
            self.process._init_system_threads()
            
            # 8. Обновляем статус на "ready"
            self.process.update_process_state(status=ProcessStatus.READY.value)

            self.process.is_initialized = True
            self.process._log_info(f"Process '{self.process.name}' initialized successfully")
            return True

        except Exception as e:
            error_trace = traceback.format_exc()
            self.process._log_error(f"Failed to initialize process '{self.process.name}': {e}")
            self.process._log_error(f"Traceback: {error_trace}")
            print(f"[ProcessLifecycle] Init failed: {e}\n{error_trace}")
            return False
    
    def shutdown(self) -> bool:
        """
        Завершение работы процесса.
        
        Returns:
            bool: True если завершение успешно
        """
        try:
            # 1. Устанавливаем флаг остановки
            self.process.stop_process = True
            
            # 2. Останавливаем системные потоки
            self.process._stop_system_threads()
            
            # 3. Останавливаем воркеры
            if self.process.worker_manager:
                self.process.worker_manager.stop_all_workers()
            
            # 4. Завершаем менеджеры
            if self.process.console_manager:
                self.process.console_manager.shutdown()
            if self.process.logger_manager:
                self.process.logger_manager.shutdown()
            if self.process.command_manager:
                self.process.command_manager.shutdown()
            if self.process.router_manager:
                self.process.router_manager.shutdown()
            
            # 5. Обновляем статус процесса
            self.process.update_process_state(status=ProcessStatus.STOPPED.value)
            
            self.process.is_initialized = False
            self.process._log_info(f"Process '{self.process.name}' shut down successfully")
            return True
            
        except Exception as e:
            self.process._log_error(f"Error during shutdown of process '{self.process.name}': {e}")
            return False

