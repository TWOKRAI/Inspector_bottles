from typing import Any, Dict, Optional

from pydantic import BaseModel

"""
Типизированные модели метаданных полей.

Эти модели поверх json_schema_extra позволяют работать с полем как с объектом:
- base: описание, info, i18n, routing, access_level, readonly/hidden;
- numeric: дополнительно min/max, transfer_k, round_k и методы clamp/round_value.
"""


class BaseFieldMeta(BaseModel):
    """Базовая модель метаданных поля (для любых типов)."""

    default: Any | None = None

    description: str = ""
    info: str = ""

    info_i18n: Dict[str, str] = {}
    description_i18n: Dict[str, str] = {}

    unit: str = ""
    examples: list[Any] = []
    routing: Dict[str, Any] = {}

    access_level: int = 0
    readonly: bool = False
    hidden: bool = False

    def get_description(self, lang: Optional[str] = None) -> str:
        if lang:
            return self.description_i18n.get(lang) or self.description
        return self.description

    def get_info(self, lang: Optional[str] = None) -> str:
        if lang:
            return self.info_i18n.get(lang) or self.info
        return self.info

    def is_visible_for(self, access_level: int) -> bool:
        return (not self.hidden) and (self.access_level <= access_level)


class NumericFieldMeta(BaseFieldMeta):
    """Метаданные числового поля с диапазоном и коэффициентами."""

    min: Optional[float] = None
    max: Optional[float] = None
    transfer_k: float = 1.0
    round_k: int = 1

    def clamp(self, value: float) -> float:
        """Ограничить значение диапазоном [min, max]."""
        if self.min is not None and value < self.min:
            value = self.min
        if self.max is not None and value > self.max:
            value = self.max
        return value

    def round_value(self, value: float) -> float:
        """Округлить значение по шагу round_k."""
        if self.round_k <= 0:
            return value
        return round(value / self.round_k) * self.round_k


__all__ = ["BaseFieldMeta", "NumericFieldMeta"]

