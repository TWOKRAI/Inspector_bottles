"""
Bootstrap для запуска ProcessManager (Refactored).

Создает ProcessManagerProcess как процесс ОС и передает ему управление системой.
"""

from multiprocessing import Process, Event
from typing import Optional, Union, Dict, Any
from pathlib import Path

from ..runner.process_runner import run_process_function
from ..platforms import get_platform_adapter

from ...shared_resources_module import SharedResourcesManager
from ...config_module import ConfigManager
from ...logger_module import LoggerManager


class ProcessManagerBootstrap:
    """
    Bootstrap для запуска ProcessManager (Refactored).
    
    Создает ProcessManagerProcess как процесс ОС и передает управление.
    Легковесный класс - только создание и запуск ProcessManagerProcess.
    """
    
    def __init__(
        self,
        config: Optional[Union[str, Path, Dict[str, Any]]] = None,
        platform_adapter=None
    ):
        """
        Инициализация Bootstrap.
        
        Args:
            config: Конфигурация процессов (путь к файлу или словарь)
            platform_adapter: Адаптер платформы (если None, определяется автоматически)
        """
        self.platform = platform_adapter or get_platform_adapter()
        self.platform.setup_multiprocessing()

        self.stop_event = Event()
        self.shared_resources = SharedResourcesManager(manager_name="shared_resources")
        self.shared_resources.initialize()

        self.config_manager = ConfigManager(manager_name="config_manager", process=None)
        self.config_manager.initialize()

        self.logger = LoggerManager(
            manager_name="bootstrap_logger",
            config_manager=self.config_manager,
        )
        self.logger.initialize()
        
        # Конфигурация процессов
        self.processes_config = config
        
        # ProcessManagerProcess как процесс ОС
        self.process_manager_process: Optional[Process] = None
    
    def start(self) -> bool:
        """
        Запускает ProcessManagerProcess.
        
        Returns:
            True если успешно запущен
        """
        try:
            self.logger.info("🚀 Starting ProcessManagerProcess...", module="bootstrap")
            
            # Connection bundle (только picklable) — избегаем pickle SharedResourcesManager/RLock
            process_config = {'processes_config': self.processes_config}
            bundle = {
                "queues": {},
                "config": process_config,
                "custom": {"process_config": process_config}
            }
            
            self.process_manager_process = Process(
                target=run_process_function,
                args=(
                    'multiprocess_framework.refactored.modules.process_manager_module.process.process_manager_process.ProcessManagerProcess',
                    'ProcessManager',
                    self.stop_event,
                    bundle
                ),
                name='ProcessManager'
            )
            
            # Запускаем ProcessManagerProcess
            self.process_manager_process.start()
            
            self.logger.info(
                f"✅ ProcessManagerProcess started (PID: {self.process_manager_process.pid})",
                module="bootstrap"
            )
            
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Failed to start ProcessManagerProcess: {e}", module="bootstrap")
            import traceback
            traceback.print_exc()
            return False
    
    def stop(self):
        """Останавливает ProcessManagerProcess и освобождает shared_resources."""
        if self.process_manager_process and self.process_manager_process.is_alive():
            self.logger.info("🛑 Stopping ProcessManagerProcess...", module="bootstrap")
            self.stop_event.set()
            self.process_manager_process.terminate()
            self.process_manager_process.join(timeout=3.0)
            if self.process_manager_process.is_alive():
                self.process_manager_process.kill()
            self.logger.info("✅ ProcessManagerProcess stopped", module="bootstrap")
        if self.shared_resources:
            self.shared_resources.shutdown()
    
    def wait(self):
        """Ожидает завершения ProcessManagerProcess."""
        if self.process_manager_process:
            self.process_manager_process.join()
    
    def is_running(self) -> bool:
        """Проверяет, запущен ли ProcessManagerProcess."""
        return self.process_manager_process is not None and self.process_manager_process.is_alive()

