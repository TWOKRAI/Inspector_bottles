# -*- coding: utf-8 -*-
"""
Реализации каналов записи логов.

Все каналы наследуют ILogChannel(IChannel) — совместимы с ChannelRoutingManager.
"""
import logging
import logging.handlers
from pathlib import Path
from typing import Dict, Any

try:
    import requests
except ImportError:
    requests = None

from ..interfaces import ILogChannel
from ..configs.logger_manager_config import LoggerChannelSchema


class LogChannel(ILogChannel):
    """Базовый класс канала логирования (реализует ILogChannel → IChannel)."""

    def __init__(self, config: LoggerChannelSchema):
        self.config = config
        self._name = config.name
        self._type = config.type

    @property
    def name(self) -> str:
        return self._name

    @property
    def channel_type(self) -> str:
        return self._type

    def write(self, record: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    def close(self) -> None:
        pass


class FileChannel(LogChannel):
    """Канал записи в файл"""
    
    def __init__(self, config: LoggerChannelSchema):
        super().__init__(config)
        self.file_path = Path(config.file_path or f"logs/{config.name}.log")
        self.file_path.parent.mkdir(parents=True, exist_ok=True)

        formatter = logging.Formatter(config.format)
        if getattr(config, "rotate", True):
            self.handler = logging.handlers.RotatingFileHandler(
                filename=self.file_path,
                maxBytes=config.max_size,
                backupCount=config.backup_count,
                encoding="utf-8",
            )
        else:
            self.handler = logging.FileHandler(
                self.file_path, encoding="utf-8", mode="a"
            )
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
            extra = record.get('extra') or {}
            log_record.proc_name = extra.get('proc_name') or '-'
            
            self.handler.emit(log_record)
            return {'status': 'success', 'channel': self.name}
        except Exception as e:
            return {'status': 'error', 'error': str(e), 'channel': self.name}
    
    def close(self):
        """Закрывает файловый канал"""
        if self.handler:
            self.handler.close()


class ConsoleChannel(LogChannel):
    """Канал записи в консоль"""
    
    def __init__(self, config: LoggerChannelSchema):
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
            extra = record.get('extra') or {}
            log_record.proc_name = extra.get('proc_name') or '-'
            
            self.handler.emit(log_record)
            return {'status': 'success', 'channel': self.name}
        except Exception as e:
            return {'status': 'error', 'error': str(e), 'channel': self.name}
    
    def close(self):
        """Закрывает консольный канал"""
        if self.handler:
            self.handler.close()


class HttpChannel(LogChannel):
    """Канал отправки логов по HTTP"""
    
    def __init__(self, config: LoggerChannelSchema):
        super().__init__(config)
        if requests is None:
            raise ImportError("requests library is required for HttpChannel")
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


def create_channel(channel_name: str, config: LoggerChannelSchema) -> LogChannel:
    """Фабрика для создания каналов (name задаётся ключом словаря channels)."""
    cfg = config.model_copy(update={"name": channel_name})
    channel_types = {
        "file": FileChannel,
        "console": ConsoleChannel,
        "http": HttpChannel,
    }
    channel_class = channel_types.get(cfg.type)
    if not channel_class:
        raise ValueError(f"Unknown channel type: {cfg.type}")
    return channel_class(cfg)

