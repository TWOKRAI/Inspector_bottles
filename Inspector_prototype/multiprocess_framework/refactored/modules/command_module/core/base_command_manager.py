"""
Базовый класс для командных менеджеров.

Предоставляет общий интерфейс для работы с командами.
"""
from typing import Dict, Any, Callable, Optional, List
from abc import ABC, abstractmethod


class BaseCommandManager(ABC):
    """
    Базовый класс для командных менеджеров.
    
    Определяет общий интерфейс для регистрации и выполнения команд.
    """
    
    def __init__(self, process_name: str):
        """
        Инициализация базового командного менеджера.
        
        Args:
            process_name: Имя процесса для идентификации
        """
        self.process_name = process_name
    
    @abstractmethod
    def register_command(
        self,
        command_name: str,
        handler: Callable,
        **kwargs
    ) -> bool:
        """
        Регистрация новой команды.
        
        Args:
            command_name: Название команды
            handler: Функция-обработчик команды
            **kwargs: Дополнительные аргументы
            
        Returns:
            bool: Успешность регистрации
        """
        pass
    
    @abstractmethod
    def handle_command(self, message: Dict) -> Any:
        """
        Обработка командного сообщения.
        
        Args:
            message: Сообщение для обработки
            
        Returns:
            Результат выполнения команды или сообщение об ошибке
        """
        pass
    
    @abstractmethod
    def get_commands(self) -> List[Dict]:
        """
        Получение списка всех зарегистрированных команд.
        
        Returns:
            Список словарей с информацией о командах
        """
        pass

