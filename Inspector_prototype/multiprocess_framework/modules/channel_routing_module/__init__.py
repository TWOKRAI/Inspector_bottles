# -*- coding: utf-8 -*-
"""
channel_routing_module — базовый модуль маршрутизации по каналам.

Устраняет дублирование между RouterManager, LoggerManager и ErrorManager,
предоставляя единый ChannelRoutingManager (BaseManager + ObservableMixin) с:
  - ChannelRegistry      — потокобезопасный реестр каналов
  - Dispatcher           — маршрутизация ключ → обработчик
  - IBufferStrategy      — опциональная буферизация (async/batch/direct)
  - normalize_config()   — унификация форматов конфига (Dict at Boundary)

Публичный API:
    ChannelRoutingManager  — базовый класс для наследования
    ChannelRegistry        — можно использовать отдельно
    normalize_config       — утилита нормализации конфига

    IChannel               — базовый контракт канала
    IBufferStrategy        — контракт буфера
    IChannelRoutingManager — контракт менеджера

    AsyncSenderBuffer      — PriorityQueue + поток (для RouterManager)
    BatchBuffer            — deque + timer (для LoggerManager)
    DirectBuffer           — без буферизации (для тестов)
    BatchConfig            — параметры BatchBuffer

Зависимости:
    Foundation: base_manager, data_schema_module (RegisterBase)
    Communication: dispatch_module (Dispatcher)
    Нет зависимостей от router_module / logger_module / error_module.
"""

from .interfaces import IChannel, IBufferStrategy, IChannelRoutingManager
from .core.channel_routing_manager import ChannelRoutingManager
from .core.channel_registry import ChannelRegistry
from .core.config_normalizer import normalize_config
from .core.config import ChannelRoutingConfig
from .configs.channel_routing_manager_config import ChannelRoutingManagerConfig
from .buffers.async_sender_buffer import AsyncSenderBuffer
from .buffers.batch_buffer import BatchBuffer, BatchConfig
from .buffers.direct_buffer import DirectBuffer

__all__ = [
    # Интерфейсы
    "IChannel",
    "IBufferStrategy",
    "IChannelRoutingManager",
    # Основные классы
    "ChannelRoutingManager",
    "ChannelRegistry",
    "ChannelRoutingConfig",
    "ChannelRoutingManagerConfig",
    "normalize_config",
    # Буферы
    "AsyncSenderBuffer",
    "BatchBuffer",
    "BatchConfig",
    "DirectBuffer",
]

__version__ = "1.0.0"
