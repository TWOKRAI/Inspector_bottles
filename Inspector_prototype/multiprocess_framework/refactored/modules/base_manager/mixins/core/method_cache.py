"""
Кэш методов для ObservableMixin.

Оптимизация производительности через кэширование методов менеджеров.
"""

from typing import Dict, Optional, Callable, Tuple


class MethodCache:
    """
    Кэш методов для оптимизации вызовов.
    
    Внутренний компонент ObservableMixin, отвечающий за:
    - Кэширование методов менеджеров
    - Быстрый доступ к методам
    - Очистку кэша при изменении менеджеров
    """
    
    def __init__(self):
        """Инициализация кэша."""
        # Формат: {(manager_name, method_name): callable_method}
        self._cache: Dict[Tuple[str, str], Optional[Callable]] = {}
    
    def get(self, manager_name: str, method_name: str) -> Optional[Callable]:
        """
        Получить метод из кэша.
        
        Args:
            manager_name: Имя менеджера
            method_name: Имя метода
            
        Returns:
            Метод или None если не найден
        """
        cache_key = (manager_name, method_name)
        return self._cache.get(cache_key)
    
    def set(self, manager_name: str, method_name: str, method: Optional[Callable]):
        """
        Сохранить метод в кэш.
        
        Args:
            manager_name: Имя менеджера
            method_name: Имя метода
            method: Метод для кэширования (может быть None)
        """
        cache_key = (manager_name, method_name)
        self._cache[cache_key] = method
    
    def has(self, manager_name: str, method_name: str) -> bool:
        """
        Проверить наличие метода в кэше.
        
        Args:
            manager_name: Имя менеджера
            method_name: Имя метода
            
        Returns:
            True если метод есть в кэше
        """
        cache_key = (manager_name, method_name)
        return cache_key in self._cache
    
    def clear_manager(self, manager_name: str):
        """
        Очистить кэш для конкретного менеджера.
        
        Args:
            manager_name: Имя менеджера
        """
        self._cache = {
            k: v for k, v in self._cache.items() 
            if k[0] != manager_name
        }
    
    def clear(self):
        """Очистить весь кэш."""
        self._cache.clear()
    
    def pop(self, manager_name: str, method_name: str) -> Optional[Callable]:
        """
        Удалить метод из кэша и вернуть его.
        
        Args:
            manager_name: Имя менеджера
            method_name: Имя метода
            
        Returns:
            Удаленный метод или None
        """
        cache_key = (manager_name, method_name)
        return self._cache.pop(cache_key, None)





