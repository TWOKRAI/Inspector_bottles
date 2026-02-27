"""
Интерфейсы для ConsoleModule.
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List, Callable

from ..base_manager.interfaces import IBaseManager


class IConsoleChannel(ABC):
    """
    Интерфейс для канала консоли.
    """
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Имя канала."""
        pass
    
    @property
    @abstractmethod
    def channel_type(self) -> str:
        """Тип канала."""
        pass
    
    @abstractmethod
    def send(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Отправить сообщение в консоль."""
        pass
    
    @abstractmethod
    def poll(self, timeout: float = 0.0) -> List[Dict[str, Any]]:
        """Получить сообщения из консоли (для интерактивного режима)."""
        pass


class IConsoleManager(IBaseManager, ABC):
    """
    Интерфейс для менеджера консоли.
    """
    
    @abstractmethod
    def enable_console(self, enabled: bool = True) -> bool:
        """Включить/выключить консоль в процессе."""
        pass
    
    @abstractmethod
    def is_console_enabled(self) -> bool:
        """Проверить включена ли консоль."""
        pass
    
    @abstractmethod
    def send_message(self, text: str, level: str = "INFO", **kwargs) -> bool:
        """Отправить сообщение в консоль."""
        pass
    
    @abstractmethod
    def register_in_router(self, router_manager, prefix: str = "console") -> List[str]:
        """Зарегистрировать каналы консоли в RouterManager."""
        pass
    
    @abstractmethod
    def setup_redirect(self, enabled: bool = True) -> bool:
        """Настроить перенаправление stdout/stderr."""
        pass
    
    @abstractmethod
    def create_debug_process(
        self,
        process_name: str,
        process_manager,
        router_manager,
        command_manager
    ) -> bool:
        """Создать отдельный процесс для отладки через ProcessManager."""
        pass

