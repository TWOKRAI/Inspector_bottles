"""
Базовый класс для всех обработчиков изображений.

Каждый новый обработчик — наследник BaseProcessor.
Реализовать: process(), get_name(), get_params_schema().
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List
import numpy as np


class BaseProcessor(ABC):
    """Базовый класс. Каждое действие обработки — отдельный класс."""

    @abstractmethod
    def process(self, image: np.ndarray, params: Dict[str, Any]) -> np.ndarray:
        """Применить обработку. image — BGR или GRAY, возвращает результат."""
        pass

    @abstractmethod
    def get_name(self) -> str:
        """Имя для UI."""
        pass

    def get_params_schema(self) -> List[Dict]:
        """
        Схема параметров для UI. Список вида:
        [{"key": "thresh", "type": "int", "min": 0, "max": 255, "default": 128}, ...]
        """
        return []
