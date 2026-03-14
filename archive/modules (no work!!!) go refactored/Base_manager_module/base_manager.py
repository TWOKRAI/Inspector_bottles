from typing import Dict, Any, Optional, Callable, List
from abc import ABC, abstractmethod
import re


class BaseManager(ABC):
    """
    Базовый абстрактный класс для всех менеджеров системы.
    
    Менеджер может иметь адаптеры (инструменты), которые подключаются через attach_adapter().
    Адаптеры предоставляют дополнительную функциональность (интеграция с процессом, упрощенный API и т.д.)
    
    Attributes:
        manager_name (str): Уникальное имя менеджера
        process (Optional[Any]): Ссылка на родительский процесс (если есть)
        is_initialized (bool): Флаг инициализации менеджера
        _adapters (Dict[str, Any]): Словарь подключенных адаптеров
    """
    
    def __init__(self, manager_name: str, process: Optional[Any] = None):
        """
        Инициализация базового менеджера.
        
        Args:
            manager_name (str): Уникальное имя менеджера
            process (Optional[Any]): Ссылка на родительский процесс
        """
        self.manager_name = manager_name
        self.process = process
        self.is_initialized = False
        self._event_handlers = {}  # Callback'и для событий
        self._adapters: Dict[str, Any] = {}  # Подключенные адаптеры (инструменты)
    
    @abstractmethod
    def initialize(self) -> bool:
        """
        Абстрактный метод инициализации менеджера.
        Должен быть реализован в дочерних классах.
        
        Returns:
            bool: True если инициализация успешна, False в противном случае
        """
        pass
    
    @abstractmethod  
    def shutdown(self) -> bool:
        """
        Абстрактный метод корректного завершения работы менеджера.
        Должен быть реализован в дочерних классах.
        
        Returns:
            bool: True если завершение успешно, False в противном случае
        """
        pass
    
    def attach_adapter(self, adapter: Any, name: Optional[str] = None) -> bool:
        """
        Подключить адаптер (инструмент) к менеджеру.
        
        Адаптер предоставляет дополнительную функциональность для менеджера.
        **Рекомендуется явно указывать имя адаптера** для надежности и читаемости.
        Если имя не указано, определяется автоматически (простая логика, может быть неточной).
        
        Args:
            adapter: Экземпляр адаптера
            name: Имя адаптера (опционально). 
                  **Рекомендуется указывать явно** для сложных имен классов.
                  Если не указано, определяется автоматически из имени класса.
            
        Returns:
            bool: True если адаптер успешно подключен
            
        Example:
            >>> adapter = CommandAdapter(manager, process)
            # Рекомендуемый способ - явное указание имени
            >>> manager.attach_adapter(adapter, name="command")
            >>> manager.command_adapter  # Доступ через magic-атрибут
            
            # Автоматическое определение (fallback)
            >>> manager.attach_adapter(adapter)  # Имя определится автоматически
        """
        if adapter is None:
            return False
        
        # Определяем имя адаптера: явное указание имеет приоритет
        if name is None:
            # Автоматическое определение используется только как fallback
            name = self._get_adapter_name_from_class(adapter.__class__.__name__)
        
        # Подключаем адаптер
        self._adapters[name] = adapter
        
        # Устанавливаем обратную ссылку на менеджера в адаптере
        if hasattr(adapter, 'manager'):
            adapter.manager = self
        
        return True
    
    def get_adapter(self, name: Optional[str] = None) -> Optional[Any]:
        """
        Получить адаптер по имени.
        
        Args:
            name: Имя адаптера. Если не указано, возвращается первый адаптер.
            
        Returns:
            Адаптер или None если не найден
        """
        if name is None:
            # Возвращаем первый адаптер если имя не указано
            for adapter in self._adapters.values():
                if adapter is not None:
                    return adapter
            return None
        
        adapter = self._adapters.get(name)
        return adapter if adapter is not None else None
    
    def has_adapter(self, name: str) -> bool:
        """Проверить наличие адаптера по имени."""
        return name in self._adapters
    
    def list_adapters(self) -> List[str]:
        """Получить список имен подключенных адаптеров."""
        return list(self._adapters.keys())
    
    def detach_adapter(self, name: str) -> bool:
        """
        Отключить адаптер от менеджера.
        
        Args:
            name: Имя адаптера
            
        Returns:
            bool: True если адаптер был отключен
        """
        if name in self._adapters:
            del self._adapters[name]
            return True
        return False
    
    def _get_adapter_name_from_class(self, class_name: str) -> str:
        """
        Определить имя адаптера из имени класса (автоматическое определение).
        
        **Простая логика для базовых случаев.** 
        Для сложных имен классов рекомендуется указывать имя явно в attach_adapter().
        
        Примеры:
            CommandAdapter -> "command"
            ProcessIntegrationAdapter -> "process_integration"
            HTTPClientAdapter -> "httpclient" (простая логика, для точности укажите имя явно)
            XMLParserAdapter -> "xmlparser"
        
        Args:
            class_name: Имя класса адаптера
            
        Returns:
            Имя адаптера в snake_case без суффикса "Adapter"
            
        Note:
            Для сложных случаев (аббревиатуры, длинные имена) рекомендуется 
            указывать имя явно: attach_adapter(adapter, name="rest_api_client")
        """
        # Убираем суффикс "Adapter" если есть
        if class_name.endswith("Adapter"):
            class_name = class_name[:-7]
        
        # Простая конвертация PascalCase в snake_case
        # Не разделяем последовательности заглавных букв (HTTP -> http, а не h_t_t_p)
        # Разделяем только переходы от строчных к заглавным
        
        # Вставляем _ перед заглавными буквами, которые следуют за строчными
        # HTTPClient -> HTTPClient (не разделяем, т.к. нет строчных перед)
        # ProcessIntegration -> Process_Integration (разделяем, т.к. есть строчные)
        name = re.sub(r'([a-z\d])([A-Z])', r'\1_\2', class_name)
        
        # Конвертируем в нижний регистр
        # HTTPClient -> httpclient (последовательности заглавных остаются вместе)
        name = name.lower()
        
        # Убираем двойные подчеркивания если появились
        name = re.sub(r'__+', '_', name)
        
        return name
    
    def __getattr__(self, name: str) -> Any:
        """
        Magic-доступ к адаптерам через атрибуты.
        
        Позволяет обращаться к адаптерам как к атрибутам:
        manager.command_adapter вместо manager.get_adapter("command")
        
        Args:
            name: Имя атрибута
            
        Returns:
            Адаптер если найден
            
        Raises:
            AttributeError: Если атрибут не найден
        """
        # Пробуем найти адаптер по имени
        if name in self._adapters:
            adapter = self._adapters[name]
            if adapter is None:
                raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{name}' (adapter is None)")
            return adapter
        
        # Пробуем найти по snake_case версии имени класса
        for adapter_name, adapter in self._adapters.items():
            if adapter is None:
                continue
            expected_name = self._get_adapter_name_from_class(adapter.__class__.__name__)
            if name == expected_name:
                return adapter
        
        # Если не нашли, вызываем стандартное поведение
        raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{name}'")
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Получение статистики и метрик менеджера.
        
        Returns:
            Dict[str, Any]: Словарь со статистикой менеджера
        """
        stats = {
            "manager_name": self.manager_name,
            "is_initialized": self.is_initialized,
            "process_name": getattr(self.process, 'name', 'unknown') if self.process else 'standalone',
            "adapters": list(self._adapters.keys())
        }
        
        # Добавляем статистику адаптеров если они есть
        if self._adapters:
            adapters_info = {}
            for name, adapter in self._adapters.items():
                if adapter is None:
                    adapters_info[name] = {}
                elif hasattr(adapter, 'get_stats'):
                    try:
                        adapters_info[name] = adapter.get_stats()
                    except Exception:
                        adapters_info[name] = {}
                else:
                    adapters_info[name] = {}
            stats["adapters_info"] = adapters_info
        
        return stats
    
    def on_event(self, event_type: str, callback: Callable) -> None:
        """
        Регистрация обработчика событий.
        
        Args:
            event_type (str): Тип события
            callback (Callable): Функция-обработчик события
        """
        self._event_handlers.setdefault(event_type, []).append(callback)
    
    def emit_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """
        Генерация события и вызов зарегистрированных обработчиков.
        
        Args:
            event_type (str): Тип события
            data (Dict[str, Any]): Данные события
        """
        for callback in self._event_handlers.get(event_type, []):
            try:
                callback(data)
            except Exception as e:
                # Fallback логирование если нет доступа к логгеру
                print(f"Error in event handler for {event_type}: {e}")
    
    def __str__(self) -> str:
        """
        Строковое представление менеджера.
        
        Returns:
            str: Информация о менеджере
        """
        return f"BaseManager(name={self.manager_name}, initialized={self.is_initialized})"
