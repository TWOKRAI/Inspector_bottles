"""
Реализации каналов записи логов.
"""

import logging
import logging.handlers
from pathlib import Path
from typing import Dict, Any
import requests

from config import ChannelConfig

class LogChannel:
    """Базовый класс канала логирования"""
    
    def __init__(self, config: ChannelConfig):
        self.config = config
        self.name = config.name
    
    def write(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """Записывает запись лога"""
        raise NotImplementedError


class FileChannel(LogChannel):
    """Канал записи в файл"""
    
    def __init__(self, config: ChannelConfig):
        super().__init__(config)
        self.file_path = Path(config.file_path or f"logs/{config.name}.log")
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Используем стандартный rotating file handler
        self.handler = logging.handlers.RotatingFileHandler(
            filename=self.file_path,
            maxBytes=config.max_size,
            backupCount=config.backup_count,
            encoding='utf-8'
        )
        
        formatter = logging.Formatter(config.format)
        self.handler.setFormatter(formatter)
    
    def write(self, record: Dict[str, Any]) -> Dict[str, Any]:
        try:
            log_record = logging.LogRecord(
                name=record['module'],
                level=getattr(logging, record['level']),
                pathname='',
                lineno=0,
                msg=record['message'],
                args=(),
                exc_info=None
            )
            log_record.created = record['timestamp']
            
            self.handler.emit(log_record)
            return {'status': 'success', 'channel': self.name}
        except Exception as e:
            return {'status': 'error', 'error': str(e), 'channel': self.name}


class ConsoleChannel(LogChannel):
    """Канал записи в консоль"""
    
    def __init__(self, config: ChannelConfig):
        super().__init__(config)
        self.handler = logging.StreamHandler()
        formatter = logging.Formatter(config.format)
        self.handler.setFormatter(formatter)
    
    def write(self, record: Dict[str, Any]) -> Dict[str, Any]:
        try:
            log_record = logging.LogRecord(
                name=record['module'],
                level=getattr(logging, record['level']),
                pathname='',
                lineno=0,
                msg=record['message'],
                args=(),
                exc_info=None
            )
            log_record.created = record['timestamp']
            
            self.handler.emit(log_record)
            return {'status': 'success', 'channel': self.name}
        except Exception as e:
            return {'status': 'error', 'error': str(e), 'channel': self.name}


class HttpChannel(LogChannel):
    """Канал отправки логов по HTTP"""
    
    def __init__(self, config: ChannelConfig):
        super().__init__(config)
        self.url = config.url
        self.headers = config.headers or {'Content-Type': 'application/json'}
    
    def write(self, record: Dict[str, Any]) -> Dict[str, Any]:
        try:
            response = requests.post(
                self.url,
                json=record,
                headers=self.headers,
                timeout=5
            )
            response.raise_for_status()
            return {'status': 'success', 'channel': self.name}
        except Exception as e:
            return {'status': 'error', 'error': str(e), 'channel': self.name}


def create_channel(config: ChannelConfig) -> LogChannel:
    """Фабрика для создания каналов"""
    channel_types = {
        'file': FileChannel,
        'console': ConsoleChannel,
        'http': HttpChannel
    }
    
    channel_class = channel_types.get(config.type)
    if not channel_class:
        raise ValueError(f"Unknown channel type: {config.type}")
    
    return channel_class(config)