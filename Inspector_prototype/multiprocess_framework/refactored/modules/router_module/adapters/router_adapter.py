"""
Адаптер для RouterManager (Refactored).

Предоставляет упрощенный интерфейс для работы с роутером:
- Отправка сообщений между процессами
- Получение сообщений из очередей
- Broadcast сообщений
"""

from typing import Dict, Any, List, Optional, Union

from ...base_manager.adapters.base_adapter import BaseAdapter

# Импорт Message для типизации
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from ...message_module import Message


class RouterAdapter(BaseAdapter):
    """
    Адаптер для RouterManager (инструмент интеграции с процессом).
    
    Предоставляет дополнительную функциональность для RouterManager:
    - Отправка сообщений конкретному процессу (send_to_process)
    - Broadcast сообщений всем процессам (broadcast)
    - Интеграция с queue_registry процесса
    
    Основная функциональность (send, receive) доступна напрямую через менеджер.
    """
    
    def __init__(self, router_manager, process: Optional[Any] = None):
        """
        Инициализация адаптера роутера.
        
        Args:
            router_manager: Экземпляр RouterManager
            process: Ссылка на родительский процесс
        """
        super().__init__(router_manager, process, "RouterAdapter")
    
    def setup(self) -> bool:
        """
        Настройка адаптера роутера.
        
        Returns:
            bool: True если настройка успешна
        """
        try:
            if not self.manager:
                self._log("error", "Manager is not set")
                return False
            
            self._initialized = True
            self._log("info", "RouterAdapter initialized")
            return True
            
        except Exception as e:
            self._log("error", f"Setup failed - {e}")
            return False
    
    def send_to_process(self, target: str, message: Union['Message', Dict[str, Any]]) -> bool:
        """
        Отправить сообщение конкретному процессу через queue_registry.
        Поддерживает как объекты Message, так и словари.
        
        Args:
            target: Имя целевого процесса
            message: Сообщение (Message объект или словарь)
            
        Returns:
            bool: True если отправка успешна
        """
        try:
            if not self.manager:
                return False
            
            # Конвертируем Message в dict если нужно
            if hasattr(message, 'to_dict'):
                message_dict = message.to_dict()
            else:
                message_dict = message.copy() if isinstance(message, dict) else message
            
            # Добавляем информацию о получателе
            message_dict['targets'] = [target]
            message_dict['sender'] = self.process.name if self.process else 'unknown'
            
            # Используем queue_registry если доступен
            if self.manager.queue_registry:
                # Определяем тип очереди (по умолчанию 'system')
                queue_type = message_dict.get('queue_type', 'system')
                result = self.manager.queue_registry.send_to_queue(target, queue_type, message_dict)
                return result
            
            # Fallback: отправка через роутер
            result = self.manager.send(message_dict)
            return result.get('status') == 'success'
            
        except Exception as e:
            self._log("error", f"Failed to send to process '{target}': {e}")
            return False
    
    def broadcast(self, message: Union['Message', Dict[str, Any]], exclude_self: bool = True) -> int:
        """
        Рассылка сообщения всем процессам.
        Поддерживает как объекты Message, так и словари.
        
        Args:
            message: Сообщение (Message объект или словарь)
            exclude_self: Исключить себя из рассылки
            
        Returns:
            int: Количество успешных доставок
        """
        try:
            if not self.manager:
                return 0
            
            # Конвертируем Message в dict если нужно
            if hasattr(message, 'to_dict'):
                message_dict = message.to_dict()
            else:
                message_dict = message.copy() if isinstance(message, dict) else message
            
            # Используем queue_registry если доступен
            if self.manager.queue_registry:
                exclude_process = self.process.name if exclude_self and self.process else None
                queue_type = message_dict.get('queue_type', 'system')
                return self.manager.queue_registry.broadcast_message(message_dict, queue_type, exclude_process)
            
            # Fallback: отправка через роутер с broadcast флагом
            message_dict['targets'] = ['all']
            result = self.manager.send(message_dict)
            return 1 if result.get('status') == 'success' else 0
            
        except Exception as e:
            self._log("error", f"Failed to broadcast message: {e}")
            return 0
    
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

