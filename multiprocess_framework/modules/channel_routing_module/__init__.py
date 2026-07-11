# -*- coding: utf-8 -*-
"""
channel_routing_module — базовый модуль маршрутизации по каналам.

Устраняет дублирование между RouterManager, LoggerManager и ErrorManager,
предоставляя единый ChannelRoutingManager (BaseManager + ObservableMixin) с:
  - ChannelRegistry      — потокобезопасный реестр каналов
  - Dispatcher           — маршрутизация ключ → обработчик
  - IBufferStrategy      — опциональная буферизация (async/batch/direct)
  - normalize_config()   — унификация форматов конфига (Dict at Boundary)
  - resolve_build_result() — извлечение (name, dict) из build()-объекта
    (общий примитив; LoggerCore/ErrorManager строят типизированную
    нормализацию поверх него — ADR-CRM-008, D1)

Публичный API:
    ChannelRoutingManager  — базовый класс для наследования
    ChannelRegistry        — можно использовать отдельно
    normalize_config       — утилита нормализации конфига (None|dict|build())
    resolve_build_result   — низкоуровневый примитив извлечения build()-payload

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
from .core.config_normalizer import normalize_config, resolve_build_result
from .core.config import ChannelRoutingConfig
from .configs.channel_routing_manager_config import ChannelRoutingManagerConfig
from .buffers.async_sender_buffer import AsyncSenderBuffer
from .buffers.batch_buffer import BatchBuffer, BatchConfig
from .buffers.direct_buffer import DirectBuffer
from .observability import (
    BoundedChannel,
    ErrorLike,
    LoggerLike,
    ObservabilityHub,
    StatsLike,
)

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
    "resolve_build_result",
    # Буферы
    "AsyncSenderBuffer",
    "BatchBuffer",
    "BatchConfig",
    "DirectBuffer",
    # Observability (Ф5.15) — фасад наблюдаемости модуля
    "ObservabilityHub",
    "BoundedChannel",
    "LoggerLike",
    "StatsLike",
    "ErrorLike",
]

__version__ = "1.0.0"
