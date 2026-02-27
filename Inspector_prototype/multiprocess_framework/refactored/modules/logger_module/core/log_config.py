"""
Конфигурация системы логирования.
Позволяет гибко настраивать что, куда и как логировать.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Set, Optional, Any
from enum import Enum
import yaml
from pathlib import Path


class LogLevel(Enum):
    """Уровни логирования"""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class LogScope(Enum):
    """Области логирования"""
    SYSTEM = "system"      # Системные события (запуск, остановка)
    BUSINESS = "business"  # Бизнес-логика (платежи, заказы)
    PERFORMANCE = "perf"   # Производительность (время выполнения)
    AUDIT = "audit"        # Аудит (действия пользователей)
    SECURITY = "security"  # Безопасность (логины, доступы)
    DEBUG = "debug"        # Отладочная информация


@dataclass
class ChannelConfig:
    """Конфигурация канала логирования"""
    name: str
    type: str  # file, console, database, http
    enabled: bool = True
    format: str = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    max_size: int = 10 * 1024 * 1024  # 10MB
    backup_count: int = 5
    
    # Специфичные настройки для разных типов
    file_path: Optional[str] = None
    url: Optional[str] = None
    headers: Dict[str, str] = field(default_factory=dict)


@dataclass
class ScopeConfig:
    """Конфигурация области логирования"""
    scope: LogScope
    enabled: bool = True
    min_level: LogLevel = LogLevel.INFO
    channels: List[str] = field(default_factory=list)
    modules: Set[str] = field(default_factory=set)  # Пусто = все модули
    
    def should_log(self, level: LogLevel, module: str) -> bool:
        """Определяет, нужно ли логировать это сообщение"""
        if not self.enabled:
            return False
        
        # Проверка уровня
        level_value = list(LogLevel).index(level)
        min_level_value = list(LogLevel).index(self.min_level)
        if level_value < min_level_value:
            return False
        
        # Проверка модуля
        if self.modules and module not in self.modules:
            return False
            
        return True


@dataclass
class ModuleConfig:
    """Конфигурация логирования для отдельного модуля"""
    enabled: bool = True
    file_path: Optional[str] = None
    min_level: LogLevel = LogLevel.DEBUG


@dataclass
class LogConfig:
    """Основная конфигурация логирования"""
    
    # Общие настройки
    app_name: str = "unknown_app"
    default_level: LogLevel = LogLevel.INFO
    enable_batching: bool = True
    batch_size: int = 100
    batch_interval: float = 1.0  # секунды
    
    # Области логирования
    scopes: Dict[LogScope, ScopeConfig] = field(default_factory=dict)
    
    # Каналы
    channels: Dict[str, ChannelConfig] = field(default_factory=dict)
    
    # Конфигурация модулей (для отдельных файлов)
    modules: Dict[str, ModuleConfig] = field(default_factory=dict)
    
    @classmethod
    def from_yaml(cls, config_path: str) -> 'LogConfig':
        """Загрузка конфигурации из YAML файла"""
        path = Path(config_path)
        if not path.exists():
            return cls()
        
        with open(path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f) or {}
        
        return cls.from_dict(data)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'LogConfig':
        """Создание конфигурации из словаря"""
        config = cls()
        
        # Базовые настройки
        config.app_name = data.get('app_name', 'unknown_app')
        config.enable_batching = data.get('enable_batching', True)
        config.batch_size = data.get('batch_size', 100)
        config.batch_interval = data.get('batch_interval', 1.0)
        
        # Уровень по умолчанию
        default_level_str = data.get('default_level', 'INFO')
        config.default_level = LogLevel[default_level_str.upper()]
        
        # Каналы
        for channel_name, channel_data in data.get('channels', {}).items():
            config.channels[channel_name] = ChannelConfig(
                name=channel_name,
                **channel_data
            )
        
        # Области
        for scope_str, scope_data in data.get('scopes', {}).items():
            try:
                scope = LogScope[scope_str.upper()]
                
                # Преобразуем уровень
                min_level_str = scope_data.get('min_level', 'INFO')
                min_level = LogLevel[min_level_str.upper()]
                
                config.scopes[scope] = ScopeConfig(
                    scope=scope,
                    enabled=scope_data.get('enabled', True),
                    min_level=min_level,
                    channels=scope_data.get('channels', []),
                    modules=set(scope_data.get('modules', []))
                )
            except KeyError:
                continue  # Пропускаем неизвестные области
        
        # Конфигурация модулей
        for module_name, module_data in data.get('modules', {}).items():
            try:
                min_level_str = module_data.get('min_level', 'DEBUG')
                min_level = LogLevel[min_level_str.upper()]
                
                config.modules[module_name] = ModuleConfig(
                    enabled=module_data.get('enabled', True),
                    file_path=module_data.get('file_path'),
                    min_level=min_level
                )
            except (KeyError, ValueError):
                continue
        
        return config
    
    def get_scope_config(self, scope: LogScope) -> ScopeConfig:
        """Получить конфигурацию области (с значениями по умолчанию)"""
        if scope in self.scopes:
            return self.scopes[scope]
        
        # Возвращаем конфиг по умолчанию
        return ScopeConfig(
            scope=scope,
            enabled=True,
            min_level=self.default_level,
            channels=list(self.channels.keys())[:1] if self.channels else []
        )

