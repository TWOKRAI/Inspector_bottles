"""
Модуль диспетчеризации сообщений.

Предоставляет гибкую систему маршрутизации и обработки сообщений с различными стратегиями.

Основные классы:
    - BaseDispatcher: Базовый класс диспетчера
    - Dispatcher: Универсальный диспетчер со всеми стратегиями

Типы данных:
    - DispatchStrategy: Enum со стратегиями диспетчеризации
    - HandlerInfo: Информация об обработчике
    - Scenario: Сценарий выполнения цепочки обработчиков

Стратегии:
    - EXACT_MATCH: Точное совпадение ключей
    - PATTERN_MATCH: Сопоставление по регулярным выражениям
    - FALLBACK_MATCH: Fallback с приоритетом эффективности
    - CHAIN_MATCH: Цепочки выполнения (сценарии)

Пример использования:
    from ..Dispatch_module import Dispatcher, DispatchStrategy
    
    # Простая стратегия
    dispatcher = Dispatcher("my_dispatcher")
    dispatcher.register_handler("process", lambda data: {"result": data})
    result = dispatcher.dispatch({"command": "process", "data": {"test": 1}})
    
    # Стратегия сценариев
    dispatcher = Dispatcher("processor", DispatchStrategy.CHAIN_MATCH)
    dispatcher.create_scenario("image_processing", "Обработка изображений")
    dispatcher.add_handler_to_scenario("image_processing", "preprocess", handler1, stage=1)
    result = dispatcher.dispatch_scenario("image_processing", {"data": image_data})
"""
from .types import DispatchStrategy, HandlerInfo, Scenario
from .base import BaseDispatcher
from .dispatcher import Dispatcher
from .scenario_builder import ScenarioBuilder

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
    # Обратная совместимость
    "AdvancedDispatcher",
]
