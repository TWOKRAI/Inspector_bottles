"""
Канал для отправки сообщений в консоль через Router.
"""

from typing import Dict, Any, List, Optional
from ..Router_module.channel import MessageChannel


class ConsoleChannel(MessageChannel):
    """Канал для отправки сообщений в консольные окна."""
    
    def __init__(
        self, 
        name: str, 
        console_manager,
        target_process: Optional[str] = None,
        target_console: Optional[str] = None
    ):
        """
        Args:
            name: Имя канала
            console_manager: Экземпляр ConsoleManager
            target_process: Имя процесса (для родной консоли)
            target_console: Имя консоли (для конкретной консоли)
        """
        self._name = name
        self._console_manager = console_manager
        self._target_process = target_process
        self._target_console = target_console
    
    @property
    def name(self) -> str:
        return self._name
    
    @property
    def channel_type(self) -> str:
        return "console"
    
    def send(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """
        Отправить сообщение в консоль.
        
        Формат: {
            "text": "Текст",
            "level": "INFO|WARNING|ERROR|DEBUG",
            "timestamp": True/False,
        }
        """
        try:
            text = message.get('text', '') or message.get('message', '') or str(message.get('content', ''))
            if not text:
                return {'status': 'error', 'reason': 'No text content'}
            
            level = message.get('level', 'INFO')
            add_timestamp = message.get('timestamp', False)
            target_process = message.get('process', self._target_process)
            target_console = message.get('console', self._target_console)
            
            formatted_text = self._format_message(text, level, add_timestamp)
            success = self._console_manager._send_text_to_queue(
                formatted_text, target_process, target_console
            )
            
            return {'status': 'success' if success else 'error', 'channel': self.name}
        except Exception as e:
            return {'status': 'error', 'reason': str(e)}
    
    def _format_message(self, text: str, level: str = 'INFO', add_timestamp: bool = False) -> str:
        """Форматирование сообщения"""
        parts = []
        
        if add_timestamp:
            from datetime import datetime
            parts.append(f"[{datetime.now().strftime('%H:%M:%S')}]")
        
        if level and level.upper() != 'INFO':
            parts.append(f"[{level.upper()}]")
        
        parts.append(text)
        
        formatted = " ".join(parts)
        if not formatted.endswith('\n'):
            formatted += '\n'
        
        return formatted
    
    def poll(self, timeout: float = 0.0) -> List[Dict[str, Any]]:
        """Консоль только для вывода"""
        return []
    
    def get_info(self) -> Dict[str, Any]:
        """Информация о канале"""
        info = super().get_info()
        info.update({
            'target_process': self._target_process,
            'target_console': self._target_console
        })
        return info

