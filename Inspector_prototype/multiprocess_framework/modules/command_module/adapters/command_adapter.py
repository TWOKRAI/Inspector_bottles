"""
Адаптер для CommandManager.

Предоставляет дополнительную функциональность для интеграции с процессом.
"""
from typing import Any, Optional, Dict, Callable, List

from ...base_manager.adapters.base_adapter import BaseAdapter


class CommandAdapter(BaseAdapter):
    """
    Адаптер для CommandManager (инструмент интеграции с процессом).
    
    Предоставляет дополнительную функциональность для CommandManager:
    - Выполнение команд через систему сообщений (execute_via_message)
    - Интеграция с process.message_manager для межпроцессного взаимодействия
    
    Основная функциональность (register_command, handle_command, get_commands)
    доступна напрямую через менеджер - адаптер не дублирует эти методы.
    """
    
    def __init__(self, command_manager: Any, process: Optional[Any] = None):
        """
        Инициализация адаптера команд.
        
        Args:
            command_manager: Экземпляр CommandManager
            process: Ссылка на родительский процесс
        """
        super().__init__(command_manager, process, "CommandAdapter")
    
    def setup(self) -> bool:
        """
        Настройка адаптера команд.
        
        Returns:
            bool: True если настройка успешна
        """
        try:
            if not self.manager:
                self._log("error", "Manager is not set")
                return False
            
            self._initialized = True
            self._log("info", "CommandAdapter initialized")
            return True
            
        except Exception as e:
            self._log("error", f"Setup failed - {e}")
            return False
    
    def execute_via_message(self, command_name: str, args: Dict, 
                           targets: List[str], need_ack: bool = False) -> bool:
        """
        Выполнение команды через систему сообщений.
        
        Args:
            command_name: Название команды
            args: Аргументы команды
            targets: Список получателей
            need_ack: Требуется ли подтверждение
            
        Returns:
            bool: True если отправка успешна
        """
        try:
            if not self.process or not hasattr(self.process, 'message_manager'):
                self._log("error", "Process or MessageManager not available")
                return False
            
            # Создаем командное сообщение
            cmd_msg = self.process.message_manager.create_command_message(
                command=command_name,
                args=args,
                targets=targets,
                need_ack=need_ack
            )
            
            # Отправляем через роутер
            if hasattr(self.process, 'router'):
                result = self.process.router.send(cmd_msg.to_dict())
                return result.get('status') == 'success'
            
            return False
            
        except Exception as e:
            self._log("error", f"Failed to execute command via message: {e}")
            return False
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Получение статистики адаптера.
        
        Returns:
            Dict[str, Any]: Статистика адаптера и менеджера
        """
        stats = super().get_stats()
        
        # Добавляем статистику менеджера если доступна
        if self.manager and hasattr(self.manager, 'get_stats'):
            try:
                manager_stats = self.manager.get_stats()
                stats["manager_stats"] = manager_stats
            except Exception:
                pass
        
        return stats

