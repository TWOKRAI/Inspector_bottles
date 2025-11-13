# module_message.py
import time
import uuid
from typing import Any, Optional, Dict, Union, List
from dataclasses import dataclass, field
from enum import Enum

class MessageType(Enum):
    COMMAND = "command"
    LOG = "log" 
    METRIC = "metric"
    STATE = "state"
    EVENT = "event"
    CONFIG = "config"
    RESPONSE = "response"

class MessageTarget(Enum):
    ALL_PROCESSES = "all_processes"
    SPECIFIC_PROCESSES = "specific_processes"
    PROCESS_GROUP = "process_group"

@dataclass
class SystemMessage:
    msg_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    msg_type: MessageType = MessageType.EVENT
    sender: str = "system"
    
    # Новая система таргетирования
    target_type: MessageTarget = MessageTarget.SPECIFIC_PROCESSES
    target_processes: Union[str, List[str]] = None  # "all", "process_name", ["p1", "p2"]
    
    data: Any = None
    timestamp: float = field(default_factory=time.time)
    priority: int = 1
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def get_target_processes(self) -> List[str]:
        """Получение списка процессов-получателей"""
        if self.target_type == MessageTarget.ALL_PROCESSES:
            return []  # Пустой список = всем процессам
        elif self.target_type == MessageTarget.SPECIFIC_PROCESSES:
            if isinstance(self.target_processes, str):
                return [self.target_processes]
            elif isinstance(self.target_processes, list):
                return self.target_processes
        return []
    
    def is_for_all_processes(self) -> bool:
        return self.target_type == MessageTarget.ALL_PROCESSES
    
    def is_for_specific_process(self, process_name: str) -> bool:
        if self.is_for_all_processes():
            return True
        return process_name in self.get_target_processes()
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SystemMessage':
        return cls(
            msg_id=data.get('msg_id', str(uuid.uuid4())),
            msg_type=MessageType(data['msg_type']),
            sender=data['sender'],
            target=data.get('target'),
            data=data.get('data'),
            timestamp=data.get('timestamp', time.time()),
            priority=data.get('priority', 1),
            metadata=data.get('metadata', {})
        )
    
    def create_response(self, response_data: Any, **kwargs) -> 'SystemMessage':
        return SystemMessage(
            msg_type=MessageType.RESPONSE,
            sender=self.target or "system",
            target=self.sender,
            data=response_data,
            priority=self.priority,
            metadata={
                'original_msg_id': self.msg_id,
                **self.metadata,
                **kwargs
            }
        )
    
    def is_for_me(self, recipient: str) -> bool:
        return self.target is None or self.target == recipient

# Специализированные классы сообщений
@dataclass
class CommandMessage(SystemMessage):
    """Специализированное сообщение для команд"""
    def __post_init__(self):
        self.msg_type = MessageType.COMMAND
        
    @property
    def command_name(self) -> str:
        return self.data.get('command', '') if isinstance(self.data, dict) else str(self.data)
    
    @property
    def command_args(self) -> Dict:
        return self.data.get('args', {}) if isinstance(self.data, dict) else {}

@dataclass
class LogMessage(SystemMessage):
    """Специализированное сообщение для логов"""
    def __post_init__(self):
        self.msg_type = MessageType.LOG
        
    @property
    def log_level(self) -> str:
        return self.data.get('level', 'INFO') if isinstance(self.data, dict) else 'INFO'
    
    @property
    def log_message(self) -> str:
        return self.data.get('message', '') if isinstance(self.data, dict) else str(self.data)

@dataclass  
class EventMessage(SystemMessage):
    """Специализированное сообщение для событий"""
    def __post_init__(self):
        self.msg_type = MessageType.EVENT
        
    @property
    def event_type(self) -> str:
        return self.data.get('event', '') if isinstance(self.data, dict) else str(self.data)

# Улучшенная фабрика
class MessageFactory:
    @staticmethod
    def create_command(sender: str, command: str, args: Dict = None, target: str = None, **kwargs) -> CommandMessage:
        return CommandMessage(
            sender=sender,
            target=target,
            data={'command': command, 'args': args or {}, **kwargs}
        )
    
    @staticmethod
    def create_log(sender: str, level: str, message: str, module: str = "main", **kwargs) -> LogMessage:
        return LogMessage(
            sender=sender,
            data={'level': level, 'message': message, 'module': module, **kwargs}
        )
    
    @staticmethod
    def create_event(sender: str, event_type: str, data: Any = None, **kwargs) -> EventMessage:
        return EventMessage(
            sender=sender,
            data={'event': event_type, 'payload': data, **kwargs}
        )
    
    @staticmethod
    def create_metric(sender: str, metric_name: str, value: Any, **kwargs) -> SystemMessage:
        return SystemMessage(
            msg_type=MessageType.METRIC,
            sender=sender,
            data={'metric': metric_name, 'value': value, **kwargs}
        )