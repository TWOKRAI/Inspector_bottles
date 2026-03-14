import sys
import time
from typing import Optional, Tuple, Any, Dict

from ..Process_module.process_module import ProcessModule
from .window_manager import BaseWindowManager, WindowConfig


class GUIProcessModule(ProcessModule):
    """
    Базовый класс для всех GUI процессов с поддержкой WindowManager.
    Решает проблему сериализации PyQt объектов путем создания
    GUI только внутри целевого процесса.
    """
    
    def __init__(self, name: str, interaction_manager=None, config: dict = None):
        super().__init__(name, interaction_manager, config)
        self.gui_app = None
        self.window_manager = None
        self._gui_initialized = False
    
    def get_window_configs(self) -> Dict[str, WindowConfig]:
        """
        Возвращает конфигурацию окон для этого процесса.
        Должен быть переопределен в дочерних классах.
        """
        return {}
    
    def create_gui_application(self) -> Tuple[Any, BaseWindowManager]:
        """
        Создает PyQt приложение и WindowManager.
        Должен быть переопределен в дочерних классах.
        """
        raise NotImplementedError("Subclasses must implement create_gui_application")
    
    def initialize_gui(self):
        """Инициализация GUI компонентов"""
        if not self._gui_initialized:
            self.gui_app, self.window_manager = self.create_gui_application()
            self._gui_initialized = True
    
    def run(self):
        """Запуск GUI процесса с WindowManager"""
        try:
            print(f"🚀 Starting GUI process: {self.name}")
            
            self.initialize_gui()
            
            if self.gui_app and self.window_manager:
                print(f"✅ GUI initialized for {self.name}")
                self.window_manager.run()
            else:
                print(f"❌ GUI initialization failed for {self.name}")
                
        except Exception as e:
            print(f"❌ GUI Process {self.name} error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            self.cleanup()
    
    def cleanup(self):
        """Очистка ресурсов GUI"""
        try:
            if self.window_manager:
                self.window_manager.close_all_windows()
            if self.gui_app:
                self.gui_app.quit()
        except Exception as e:
            print(f"⚠️ Cleanup error in {self.name}: {e}")
    
    def send_gui_message(self, message_type: str, data: Any, targets: list = None):
        """
        Отправка сообщения из GUI в основной процесс.
        Используется для межпроцессной коммуникации.
        
        Args:
            message_type: Тип сообщения
            data: Данные сообщения
            targets: Список получателей (по умолчанию ["system"])
        """
        if not targets:
            targets = ["system"]
        
        # Используем новый упрощенный API
        message = {
            'type': 'general',
            'sender': self.name,
            'targets': targets,
            'content': {
                'message_type': message_type,
                'data': data
            }
        }
        
        return self.send(message)
    
    def receive_gui_message(self, timeout: float = 0.1) -> Optional[Any]:
        """
        Получение сообщений для GUI из основного процесса.
        """
        if self.interaction_manager:
            return self.interaction_manager.receive_message(self.name, timeout)
        return None
