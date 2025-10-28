from abc import ABC, abstractmethod
from typing import Any, Dict


class IWindow(ABC):
    """Абстрактный интерфейс для всех окон приложения"""
    
    @abstractmethod
    def show(self) -> None:
        """Показать окно"""
        pass
    
    @abstractmethod
    def hide(self) -> None:
        """Скрыть окно"""
        pass
    
    @abstractmethod
    def close(self) -> None:
        """Закрыть окно"""
        pass
    
    @abstractmethod
    def showFullScreen(self) -> None:
        """Показать в полноэкранном режиме"""
        pass
    
    @abstractmethod
    def showNormal(self) -> None:
        """Показать в нормальном режиме"""
        pass
    
    @abstractmethod
    def setCursor(self, cursor) -> None:
        """Установить курсор"""
        pass
    
    @abstractmethod
    def isVisible(self) -> bool:
        """Проверить видимость окна"""
        pass
    
    @abstractmethod
    def winId(self) -> int:
        """Получить ID окна"""
        pass
    
    @abstractmethod
    def update_access_level(self, access_level: int) -> None:
        """Обновить уровень доступа (опционально)"""
        pass