
# ═════════════════════════════════════════════════════════════════════
# Window Registry — фабрика и хранилище
# ═════════════════════════════════════════════════════════════════════


from typing import Optional, Dict, List, Callable, Any, Set
from PyQt5.QtWidgets import QWidget

from App.Core.Application.window_entry import WindowEntry


class WindowRegistry:
    """Реестр всех окон приложения."""
    
    def __init__(self):
        self._entries: Dict[str, WindowEntry] = {}
        self._order: List[str] = []  # Порядок регистрации
    
    def register(
        self,
        name: str,
        factory: Callable[..., QWidget],
        *,
        singleton: bool = True,
        needs_fullscreen: bool = True,
        needs_cursor: bool = True,
        needs_access_level: bool = True,
        auto_close: int = 0,
    ) -> "WindowRegistry":
        """
        Регистрация окна. Chainable API.
        
        Args:
            name: Уникальное имя окна ('main', 'loading', 'neuroun')
            factory: Функция factory(**kwargs) -> QWidget
            singleton: True = создать один раз, потом только show/hide
            needs_fullscreen: Участвует в глобальном fullscreen?
            needs_cursor: Участвует в глобальном cursor toggle?
            needs_access_level: Получает уведомления об изменении access_level?
            auto_close: Автозакрытие через N секунд (для message windows)
        """
        if name in self._entries:
            raise ValueError(f"Window '{name}' already registered")
        
        self._entries[name] = WindowEntry(
            factory=factory,
            singleton=singleton,
            needs_fullscreen=needs_fullscreen,
            needs_cursor=needs_cursor,
            needs_access_level=needs_access_level,
            auto_close=auto_close,
        )
        self._order.append(name)
        return self
    
    def create(self, name: str, **kwargs) -> Optional[QWidget]:
        """
        Создать окно по имени.
        
        Args:
            name: Имя зарегистрированного окна
            **kwargs: Аргументы для factory
        
        Returns:
            Созданное окно или None если уже создано (singleton)
        """
        entry = self._entries.get(name)
        if not entry:
            raise KeyError(f"Window '{name}' not registered")
        
        # Singleton: вернуть существующее
        if entry.singleton and entry.created and entry.instance:
            return entry.instance
        
        # Создаём новое
        entry.instance = entry.factory(**kwargs)
        entry.created = True
        
        return entry.instance
    
    def get(self, name: str) -> Optional[QWidget]:
        """Получить созданный инстанс (или None)."""
        entry = self._entries.get(name)
        return entry.instance if entry else None
    
    def is_created(self, name: str) -> bool:
        """Создано ли окно?"""
        entry = self._entries.get(name)
        return entry.created if entry else False
    
    def get_entry(self, name: str) -> Optional[WindowEntry]:
        """Получить полную конфигурацию окна."""
        return self._entries.get(name)
    
    def all_names(self) -> List[str]:
        """Все зарегистрированные имена."""
        return list(self._order)
    
    def created_names(self) -> List[str]:
        """Имена созданных окон."""
        return [n for n in self._order if self._entries[n].created]
    
    def filter_names(
        self,
        *,
        needs_fullscreen: Optional[bool] = None,
        needs_cursor: Optional[bool] = None,
        needs_access_level: Optional[bool] = None,
        created_only: bool = True,
    ) -> List[str]:
        """
        Фильтрация имён окон по критериям.
        
        Args:
            needs_fullscreen: Фильтр по флагу fullscreen
            needs_cursor: Фильтр по флагу cursor
            needs_access_level: Фильтр по флагу access_level
            created_only: Только созданные окна?
        """
        result = []
        for name in self._order:
            entry = self._entries[name]
            
            if created_only and not entry.created:
                continue
            
            if needs_fullscreen is not None and entry.needs_fullscreen != needs_fullscreen:
                continue
            
            if needs_cursor is not None and entry.needs_cursor != needs_cursor:
                continue
            
            if needs_access_level is not None and entry.needs_access_level != needs_access_level:
                continue
            
            result.append(name)
        
        return result
    
    def apply(self, names: List[str], action: Callable[[QWidget], None]) -> None:
        """Применить действие к списку окон."""
        for name in names:
            entry = self._entries.get(name)
            if entry and entry.instance:
                action(entry.instance)
    
    def close_all(self) -> None:
        """Закрыть все окна и очистить инстансы."""
        for entry in self._entries.values():
            if entry.instance:
                entry.instance.close()
                entry.instance.deleteLater()
                entry.instance = None
            entry.created = False
