# handler_dispatcher.py

from typing import Dict, Any, Callable, Optional, List, Set
from enum import Enum
import inspect
from dataclasses import dataclass
from pathlib import Path


@dataclass
class HandlerInfo:
    """Полная информация о зарегистрированном обработчике"""
    key: str
    function: Callable
    function_name: str
    module: str
    expects_full_message: bool
    signature: inspect.Signature
    metadata: Dict[str, Any]
    description: str = ""
    tags: Set[str] = None
    
    def __post_init__(self):
        if self.tags is None:
            self.tags = set()
    
    def to_dict(self) -> Dict[str, Any]:
        """Конвертация в словарь для сериализации"""
        return {
            "key": self.key,
            "function_name": self.function_name,
            "module": self.module,
            "expects_full_message": self.expects_full_message,
            "parameters": list(self.signature.parameters.keys()),
            "metadata": self.metadata,
            "description": self.description,
            "tags": list(self.tags)
        }


class DispatchStrategy(Enum):
    EXACT_MATCH = "exact"      # Точное совпадение ключа
    PATTERN_MATCH = "pattern"  # Регулярные выражения
    PRIORITY_MATCH = "priority" # Приоритетная обработка
    CONTEXT_MATCH = "context"  # На основе контекста


class HandlerDispatcher:
    """
    Универсальный диспетчер для выполнения функций на основе входных данных.
    Может использоваться в CommandManager, LoggerManager, Router и других компонентах.
    """
    
    def __init__(self, name: str, strategy: DispatchStrategy = DispatchStrategy.EXACT_MATCH):
        self.name = name
        self.strategy = strategy
        self.handlers: Dict[str, Dict] = {}
        # Формат: {key: {"function": callable, "expects_message": bool, "metadata": {...}}}
    
    def __init__(self, name: str, strategy: DispatchStrategy = DispatchStrategy.EXACT_MATCH):
        self.name = name
        self.strategy = strategy
        self.handlers: Dict[str, HandlerInfo] = {}
    
    def register_handler(self, 
                       key: str, 
                       handler_func: Callable,
                       expects_full_message: bool = False,
                       metadata: Dict = None,
                       description: str = "",
                       tags: List[str] = None) -> bool:
        """
        Расширенная регистрация обработчика с метаданными
        """
        try:
            # Получаем информацию о функции
            func_name = handler_func.__name__
            module = handler_func.__module__
            signature = inspect.signature(handler_func)
            
            handler_info = HandlerInfo(
                key=key,
                function=handler_func,
                function_name=func_name,
                module=module,
                expects_full_message=expects_full_message,
                signature=signature,
                metadata=metadata or {},
                description=description,
                tags=set(tags) if tags else set()
            )
            
            self.handlers[key] = handler_info
            return True
            
        except Exception as e:
            print(f"HandlerDispatcher {self.name}: Failed to register handler '{key}': {e}")
            return False

    def get_handler_info(self, key: str) -> Optional[HandlerInfo]:
        """Получение полной информации об обработчике"""
        return self.handlers.get(key)
    
    def get_all_handlers_info(self) -> List[HandlerInfo]:
        """Получение информации о всех обработчиках"""
        return list(self.handlers.values())
    
    def get_handlers_by_tag(self, tag: str) -> List[HandlerInfo]:
        """Получение обработчиков по тегу"""
        return [info for info in self.handlers.values() if tag in info.tags]
    
    def get_available_actions(self) -> List[Dict[str, Any]]:
        """Получение списка доступных действий для API/UI"""
        actions = []
        for handler_info in self.handlers.values():
            action = {
                "name": handler_info.key,
                "description": handler_info.description,
                "parameters": list(handler_info.signature.parameters.keys()),
                "metadata": handler_info.metadata,
                "tags": list(handler_info.tags)
            }
            actions.append(action)
        return actions
    
    def get_handler_statistics(self) -> Dict[str, Any]:
        """Статистика по зарегистрированным обработчикам"""
        total = len(self.handlers)
        tags_count = {}
        modules_count = {}
        
        for handler in self.handlers.values():
            # Считаем теги
            for tag in handler.tags:
                tags_count[tag] = tags_count.get(tag, 0) + 1
            
            # Считаем модули
            modules_count[handler.module] = modules_count.get(handler.module, 0) + 1
        
        return {
            "total_handlers": total,
            "tags_distribution": tags_count,
            "modules_distribution": modules_count,
            "strategy": self.strategy.value
        }
    
    def dispatch(self, 
                message: Dict[str, Any],
                key_field: str = "command",
                data_field: str = "data") -> Any:
        """
        Основной метод диспетчеризации
        
        :param message: Входное сообщение
        :param key_field: Поле, содержащее ключ для поиска обработчика
        :param data_field: Поле, содержащее данные для обработчика
        :return: Результат выполнения обработчика или None
        """
        try:
            # Извлекаем ключ для диспетчеризации
            key = self._extract_key(message, key_field)
            if not key:
                return {"status": "error", "reason": f"Key field '{key_field}' not found"}
            
            # Ищем подходящий обработчик
            handler_info = self._find_handler(key)
            if not handler_info:
                return {"status": "error", "reason": f"No handler for key '{key}'"}
            
            # Подготавливаем данные для обработчика
            handler_data = self._prepare_handler_data(message, handler_info, data_field)
            
            # Выполняем обработчик
            return self._execute_handler(handler_info, handler_data)
            
        except Exception as e:
            return {"status": "error", "reason": f"Dispatch failed: {str(e)}"}
    
    def _extract_key(self, message: Dict, key_field: str) -> Optional[str]:
        """Извлечение ключа из сообщения"""
        # Поддержка вложенных полей через точную нотацию: "data.command"
        if '.' in key_field:
            parts = key_field.split('.')
            current = message
            for part in parts:
                if isinstance(current, dict) and part in current:
                    current = current[part]
                else:
                    return None
            return str(current) if current else None
        else:
            return message.get(key_field)
    
    def _find_handler(self, key: str) -> Optional[Dict]:
        """Поиск подходящего обработчика на основе стратегии"""
        if self.strategy == DispatchStrategy.EXACT_MATCH:
            return self.handlers.get(key)
        
        # Здесь можно добавить другие стратегии поиска
        # PATTERN_MATCH, PRIORITY_MATCH и т.д.
        
        return self.handlers.get(key)
    
    def _prepare_handler_data(self, message: Dict, handler_info: Dict, data_field: str) -> Any:
        """Подготовка данных для обработчика"""
        if handler_info["expects_message"]:
            return message  # Передаем всё сообщение
        
        # Извлекаем данные из указанного поля
        if '.' in data_field:
            parts = data_field.split('.')
            current = message
            for part in parts:
                if isinstance(current, dict) and part in current:
                    current = current[part]
                else:
                    return {}
            return current or {}
        else:
            return message.get(data_field, {})
    
    def _execute_handler(self, handler_info: Dict, handler_data: Any) -> Any:
        """Выполнение обработчика с учетом его сигнатуры"""
        handler_func = handler_info["function"]
        signature = handler_info["signature"]
        
        try:
            # Если обработчик ожидает конкретные аргументы, пытаемся их передать
            if isinstance(handler_data, dict) and len(signature.parameters) > 0:
                # Проверяем, можно ли передать handler_data как **kwargs
                try:
                    bound_args = signature.bind(**handler_data)
                    bound_args.apply_defaults()
                    return handler_func(*bound_args.args, **bound_args.kwargs)
                except TypeError:
                    # Если не получается, передаем как есть
                    return handler_func(handler_data)
            else:
                # Просто передаем данные
                return handler_func(handler_data)
                
        except Exception as e:
            print(f"Handler execution error: {e}")
            raise
    
    def get_registered_handlers(self) -> List[str]:
        """Получение списка зарегистрированных обработчиков"""
        return list(self.handlers.keys())
    
    def has_handler(self, key: str) -> bool:
        """Проверка наличия обработчика"""
        return key in self.handlers