# -*- coding: utf-8 -*-
"""
Базовое поле: модель метаданных — единственный источник истины.

Схему для FieldSchema получают через BaseFieldMeta.schema_defaults().
"""
from typing import Any, Dict, Optional

from pydantic import BaseModel


class BaseFieldMeta(BaseModel):
    """Метаданные поля: описание, i18n, доступ, валидация. У каждой модели — свои методы."""

    default: Any | None = None
    description: str = ""
    info: str = ""
    info_i18n: Dict[str, str] = {"ru": "", "en": "", "de": ""}
    description_i18n: Dict[str, str] = {"ru": "", "en": "", "de": ""}
    unit: str = ""
    examples: list[Any] = []
    routing: Dict[str, Any] = {}
    access_level: int = 0
    readonly: bool = False
    hidden: bool = False
    min: Optional[float] = None
    max: Optional[float] = None

    @classmethod
    def schema_defaults(cls) -> Dict[str, Any]:
        """Словарь метаданных по умолчанию для FieldSchema и json_schema_extra (один источник истины)."""
        return cls().model_dump()

    def get_description(self, lang: Optional[str] = None) -> str:
        return self.description_i18n.get(lang, "") or self.description if lang else self.description

    def get_info(self, lang: Optional[str] = None) -> str:
        return self.info_i18n.get(lang, "") or self.info if lang else self.info

    def is_visible_for(self, access_level: int) -> bool:
        return not self.hidden and self.access_level <= access_level

    def can_modify(self, access_level: int) -> bool:
        return not self.readonly and self.access_level <= access_level

    def validate_value(self, value: Any, access_level: int = 0) -> tuple[bool, Optional[str]]:
        if self.access_level > access_level:
            return False, "Недостаточно прав доступа"
        if isinstance(value, (int, float)) and (self.min is not None or self.max is not None):
            if self.min is not None and value < self.min:
                return False, f"Значение {value} меньше минимального {self.min}"
            if self.max is not None and value > self.max:
                return False, f"Значение {value} больше максимального {self.max}"
        return True, None

    def to_metadata_dict(
        self,
        language: Optional[str] = None,
        translation_manager: Optional[Any] = None,
    ) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "description": self.get_description(language),
            "info": self.get_info(language),
            "unit": self.unit,
            "min": self.min,
            "max": self.max,
            "access_level": self.access_level,
            "examples": self.examples,
            "default": self.default,
            "readonly": self.readonly,
            "hidden": self.hidden,
        }
        if self.info_i18n:
            d["info_i18n"] = self.info_i18n
        if self.description_i18n:
            d["description_i18n"] = self.description_i18n
        if self.routing:
            d["routing"] = self.routing
        if translation_manager:
            d["info"] = translation_manager.translate_metadata(d, field="info")
        return d


__all__ = ["BaseFieldMeta"]
