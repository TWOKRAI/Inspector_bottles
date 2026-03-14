"""
Bootstrap для запуска ProcessManager.

Создает ProcessManager как процесс и передает ему управление системой.
"""

from multiprocessing import Process, Event
from typing import Optional, Union, Dict, Any
from pathlib import Path

from ..runner.process_runner import _run_process_function
# ProcessConfiguration удален - конфигурация хранится в ProcessData.custom
from ...Shared_resources_module.SharedResourcesManager import SharedResourcesManager
from ...Config_module.config_manager import ConfigManager
from ...Logger_module import LoggerManager
from ..platforms import get_platform_adapter


class ProcessManagerBootstrap:
    """
    Bootstrap для запуска ProcessManager.
    
    Создает ProcessManager как процесс ОС и передает управление.
    Легковесный класс - только создание и запуск ProcessManager.
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
        self.shared_resources = SharedResourcesManager()
        
        # ConfigManager для загрузки конфигурации
        self.config_manager = ConfigManager()
        
        # Logger для bootstrap
        self.logger = LoggerManager(config_manager=self.config_manager)
        self.logger.initialize()
        
        # Конфигурация процессов
        self.processes_config = config
        
        # ProcessManager как процесс ОС
        self.process_manager_process: Optional[Process] = None
    
    def start(self) -> bool:
        """
        Запускает ProcessManager.
        
        Returns:
            True если успешно запущен
        """
        try:
            self.logger.info("🚀 Starting ProcessManager...", module="bootstrap")
            
            # Регистрируем ProcessManager в shared_resources с конфигурацией
            process_config = ProcessConfiguration(
                process={'processes_config': self.processes_config},
                managers={},
                modules={}
            )
            
            self.shared_resources.register_process_with_config(
                process_name='ProcessManager',
                config=process_config,
                initial_state={'status': 'initializing'}
            )
            
            # Создаем ProcessManager как процесс ОС
            self.process_manager_process = Process(
                target=_run_process_function,
                args=(
                    'src.Modules.Process_manager_module.process.manager_process.ProcessManager',
                    'ProcessManager',
                    self.stop_event,
                    self.shared_resources
                ),
                name='ProcessManager'
            )
            
            # Запускаем ProcessManager
            self.process_manager_process.start()
            
            self.logger.info(
                f"✅ ProcessManager started (PID: {self.process_manager_process.pid})",
                module="bootstrap"
            )
            
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Failed to start ProcessManager: {e}", module="bootstrap")
            import traceback
            traceback.print_exc()
            return False
    
    def stop(self):
        """Останавливает ProcessManager."""
        if self.process_manager_process and self.process_manager_process.is_alive():
            self.logger.info("🛑 Stopping ProcessManager...", module="bootstrap")
            self.stop_event.set()
            self.process_manager_process.terminate()
            self.process_manager_process.join(timeout=3.0)
            
            if self.process_manager_process.is_alive():
                self.process_manager_process.kill()
            
            self.logger.info("✅ ProcessManager stopped", module="bootstrap")
    
    def wait(self):
        """Ожидает завершения ProcessManager."""
        if self.process_manager_process:
            self.process_manager_process.join()
    
    def is_running(self) -> bool:
        """Проверяет, запущен ли ProcessManager."""
        return self.process_manager_process is not None and self.process_manager_process.is_alive()

