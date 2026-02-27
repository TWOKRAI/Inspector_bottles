"""
Bootstrap для запуска ProcessManager (Refactored).

Создает ProcessManagerProcess как процесс ОС и передает ему управление системой.
"""

from multiprocessing import Process, Event
from typing import Optional, Union, Dict, Any
from pathlib import Path

from ..runner.process_runner import run_process_function

# Импорт из старого модуля (временно, пока не рефакторены)
import sys
from pathlib import Path as PathLib
sys.path.insert(0, str(PathLib(__file__).parent.parent.parent.parent.parent / "modules"))
from Shared_resources_module.SharedResourcesManager import SharedResourcesManager
from Config_module.config_manager import ConfigManager
from Logger_module import LoggerManager
from Process_manager_module.platforms import get_platform_adapter


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
        self.shared_resources = SharedResourcesManager()
        
        # ConfigManager для загрузки конфигурации
        self.config_manager = ConfigManager()
        
        # Logger для bootstrap
        self.logger = LoggerManager(config_manager=self.config_manager)
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
            
            # Регистрируем ProcessManagerProcess в shared_resources с конфигурацией
            # Используем новый путь к рефакторенному модулю
            process_config = {
                'process': {
                    'processes_config': self.processes_config
                },
                'managers': {},
                'modules': {}
            }
            
            self.shared_resources.register_process_with_config(
                process_name='ProcessManager',
                config=process_config,
                initial_state={'status': 'initializing'}
            )
            
            # Создаем ProcessManagerProcess как процесс ОС
            # Используем новый путь к рефакторенному модулю
            self.process_manager_process = Process(
                target=run_process_function,
                args=(
                    'multiprocess_framework.refactored.modules.process_manager_module.process.process_manager_process.ProcessManagerProcess',
                    'ProcessManager',
                    self.stop_event,
                    self.shared_resources
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
        """Останавливает ProcessManagerProcess."""
        if self.process_manager_process and self.process_manager_process.is_alive():
            self.logger.info("🛑 Stopping ProcessManagerProcess...", module="bootstrap")
            self.stop_event.set()
            self.process_manager_process.terminate()
            self.process_manager_process.join(timeout=3.0)
            
            if self.process_manager_process.is_alive():
                self.process_manager_process.kill()
            
            self.logger.info("✅ ProcessManagerProcess stopped", module="bootstrap")
    
    def wait(self):
        """Ожидает завершения ProcessManagerProcess."""
        if self.process_manager_process:
            self.process_manager_process.join()
    
    def is_running(self) -> bool:
        """Проверяет, запущен ли ProcessManagerProcess."""
        return self.process_manager_process is not None and self.process_manager_process.is_alive()

