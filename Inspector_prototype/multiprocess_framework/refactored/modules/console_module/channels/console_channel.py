"""
Канал для отправки сообщений в консоль через RouterManager.

Реализует интерфейс MessageChannel из router_module.
"""
from typing import Dict, Any, List, Optional

from ...router_module.channels.base_channel import MessageChannel
from ..interfaces import IConsoleChannel


class ConsoleChannel(MessageChannel, IConsoleChannel):
    """
    Канал для отправки сообщений в консольные окна.
    
    Реализует интерфейс MessageChannel для интеграции с RouterManager.
    """
    
    def __init__(
        self, 
        name: str, 
        console_manager,
        target_process: Optional[str] = None,
        target_console: Optional[str] = None
    ):
        """
        Args:
            name: Имя канала (например, "console.ProcessName")
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
        """Уникальное имя канала."""
        return self._name
    
    @property
    def channel_type(self) -> str:
        """Тип канала."""
        return "console"
    
    def send(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """
        Отправить сообщение в консоль.
        
        Формат сообщения:
        {
            "text": "Текст сообщения",      # Обязательно
            "level": "INFO|WARNING|ERROR|DEBUG",  # Опционально
            "timestamp": True/False,         # Опционально
            "process": "ProcessName",        # Опционально (переопределяет target_process)
            "console": "ConsoleName"         # Опционально (переопределяет target_console)
        }
        
        Args:
            message: Сообщение для отправки
        
        Returns:
            Результат отправки: {"status": "success|error", "channel": name, ...}
        """
        try:
            text = message.get('text', '') or message.get('message', '') or str(message.get('content', ''))
            if not text:
                return {'status': 'error', 'reason': 'No text content', 'channel': self.name}
            
            level = message.get('level', 'INFO')
            add_timestamp = message.get('timestamp', False)
            target_process = message.get('process', self._target_process)
            target_console = message.get('console', self._target_console)
            
            formatted_text = self._format_message(text, level, add_timestamp)
            success = self._console_manager._send_to_console(
                formatted_text, target_process, target_console
            )
            
            return {
                'status': 'success' if success else 'error',
                'channel': self.name
            }
        except Exception as e:
            return {'status': 'error', 'reason': str(e), 'channel': self.name}
    
    def poll(self, timeout: float = 0.0) -> List[Dict[str, Any]]:
        """
        Опрос канала для получения сообщений (для интерактивного режима).
        
        Args:
            timeout: Таймаут опроса (0 = non-blocking)
        
        Returns:
            Список полученных сообщений
        """
        # Для интерактивного режима можно получать команды из консоли
        # Пока возвращаем пустой список (будет реализовано в интерактивном режиме)
        return []
    
    def _format_message(self, text: str, level: str = 'INFO', add_timestamp: bool = False) -> str:
        """
        Форматирование сообщения для консоли.
        
        Args:
            text: Текст сообщения
            level: Уровень логирования
            add_timestamp: Добавить временную метку
        
        Returns:
            Отформатированный текст
        """
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
    
    def get_info(self) -> Dict[str, Any]:
        """Получить информацию о канале."""
        info = super().get_info()
        info.update({
            'target_process': self._target_process,
            'target_console': self._target_console
        })
        return info

