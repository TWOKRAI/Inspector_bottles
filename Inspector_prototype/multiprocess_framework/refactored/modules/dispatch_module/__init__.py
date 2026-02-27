"""
Dispatch Module (Refactored) - Модуль диспетчеризации сообщений.

Предоставляет гибкую систему маршрутизации и обработки сообщений с поддержкой различных стратегий диспетчеризации.
"""

from .types.types import DispatchStrategy, HandlerInfo, Scenario
from .core.base_dispatcher import BaseDispatcher
from .core.dispatcher import Dispatcher
from .builders.scenario_builder import ScenarioBuilder
from .interfaces import IDispatcher

# Для обратной совместимости
AdvancedDispatcher = Dispatcher

__all__ = [
    # Типы данных
    "DispatchStrategy",
    "HandlerInfo",
    "Scenario",
    # Классы диспетчеров
    "BaseDispatcher",
    "Dispatcher",
    # Построитель сценариев
    "ScenarioBuilder",
    # Интерфейсы
    "IDispatcher",
    # Обратная совместимость
    "AdvancedDispatcher",
]

