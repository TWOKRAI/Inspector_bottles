# -*- coding: utf-8 -*-
"""
Числовое поле: модель с clamp/round_value; схема для регистров — NumericFieldMeta.schema_defaults().
"""
from typing import Any, Dict, Optional

from pydantic import BaseModel

from .base_field import BaseFieldMeta


class NumericFieldMeta(BaseModel):
    """Числовое поле: min/max, transfer_k, round_k; методы clamp, round_value."""

    transfer_k: float = 1.0
    round_k: int = 1

    @classmethod
    def schema_defaults(cls) -> Dict[str, Any]:
        """Словарь метаданных по умолчанию для FieldSchema регистров (один источник истины)."""
        return cls().model_dump()

    def clamp(self, value: float) -> float:
        if self.min is not None and value < self.min:
            value = self.min
        if self.max is not None and value > self.max:
            value = self.max
        return value

    def round_value(self, value: float) -> float:
        if self.round_k <= 0:
            return value
        return round(value / self.round_k) * self.round_k

    def validate_value(self, value: Any, access_level: int = 0) -> tuple[bool, Optional[str]]:
        ok, msg = super().validate_value(value, access_level)
        if not ok:
            return ok, msg
        if isinstance(value, (int, float)):
            if self.min is not None and value < self.min:
                return False, f"Значение {value} меньше минимального {self.min}"
            if self.max is not None and value > self.max:
                return False, f"Значение {value} больше максимального {self.max}"
        return True, None

    @classmethod
    def from_pydantic_field(cls, field_info: Any) -> Optional[BaseFieldMeta]:
        """Собрать BaseFieldMeta или NumericFieldMeta из FieldInfo поля Pydantic."""
        if field_info is None:
            return None
        extra = getattr(field_info, "json_schema_extra", None) or {}
        default = getattr(field_info, "default", None)
        try:
            if hasattr(default, "default"):
                default = default.default
        except Exception:
            pass
        kwargs: Dict[str, Any] = {
            "default": default,
            "description": getattr(field_info, "description", "") or "",
            "info": extra.get("info", ""),
            "info_i18n": extra.get("info_i18n") or {},
            "description_i18n": extra.get("description_i18n") or {},
            "unit": extra.get("unit", ""),
            "examples": extra.get("examples") or [],
            "routing": extra.get("routing") or {},
            "access_level": extra.get("access_level", 0),
            "readonly": extra.get("readonly", False),
            "hidden": extra.get("hidden", False),
            "min": extra.get("min"),
            "max": extra.get("max"),
        }
        range_str = extra.get("range", "")
        if range_str and kwargs["min"] is None and kwargs["max"] is None and "-" in range_str:
            try:
                parts = range_str.split("-", 1)
                if len(parts) == 2:
                    kwargs["min"] = int(parts[0].strip()) if parts[0].strip() else None
                    kwargs["max"] = int(parts[1].strip()) if parts[1].strip() else None
            except (ValueError, AttributeError):
                pass
        if any(extra.get(k) is not None for k in ("min", "max", "transfer_k", "round_k")):
            return cls(
                **kwargs,
                transfer_k=extra.get("transfer_k", 1.0),
                round_k=extra.get("round_k", 1),
            )
        return BaseFieldMeta(**kwargs)


# Тонкие миксины: только делегирование в meta-модель (меньше ссылок, меньше кода).
class RegisterMetadataHelper:
    """Миксин для *Registers: один источник — get_field_meta_model, остальное через него."""

    def get_field_meta_model(self, field_name: str) -> Optional[BaseFieldMeta]:
        fi = self.model_fields.get(field_name)  # type: ignore[attr-defined]
        return NumericFieldMeta.from_pydantic_field(fi) if fi else None

    def get_field_metadata(
        self,
        field_name: str,
        language: Optional[str] = None,
        translation_manager: Optional[Any] = None,
    ) -> Dict[str, Any]:
        meta = self.get_field_meta_model(field_name)
        return meta.to_metadata_dict(language=language, translation_manager=translation_manager) if meta else {}

    def get_field_description(
        self,
        field_name: str,
        language: Optional[str] = None,
        translation_manager: Optional[Any] = None,
    ) -> str:
        meta = self.get_field_meta_model(field_name)
        if not meta:
            return ""
        if translation_manager:
            return translation_manager.translate_metadata(meta.to_metadata_dict(), field="info")
        return meta.get_info(language) or meta.get_description(language)

    def get_field_descriptions(self, separator: str = ".") -> Dict[str, str]:
        result: Dict[str, str] = {}
        for fn in self.model_fields:  # type: ignore[attr-defined]
            meta = self.get_field_meta_model(fn)
            result[fn] = meta.get_info() if meta else ""
        return result

    def validate_field_value(
        self, field_name: str, value: Any, current_access_level: int = 0
    ) -> tuple[bool, Optional[str]]:
        meta = self.get_field_meta_model(field_name)
        if not meta:
            return False, f"Поле {field_name} не найдено"
        return meta.validate_value(value, current_access_level)

    def get_fields_for_access_level(self, access_level: int = 0) -> Dict[str, Dict[str, Any]]:
        return {
            fn: meta.to_metadata_dict()
            for fn in self.model_fields  # type: ignore[attr-defined]
            if (meta := self.get_field_meta_model(fn)) and meta.is_visible_for(access_level)
        }

    def can_modify_field(self, field_name: str, access_level: int = 0) -> bool:
        meta = self.get_field_meta_model(field_name)
        return bool(meta and meta.can_modify(access_level))


class RegistersContainerMetadataMixin:
    """Миксин контейнера: всё делегирует в экземпляр регистра по имени."""

    def get_field_metadata(
        self,
        register_name: str,
        field_name: str,
        language: Optional[str] = None,
        translation_manager: Optional[Any] = None,
    ) -> Dict[str, Any]:
        r = getattr(self, register_name, None)
        return r.get_field_metadata(field_name, language=language, translation_manager=translation_manager) if r and hasattr(r, "get_field_metadata") else {}

    def get_field_description(
        self,
        register_name: str,
        field_name: str,
        language: Optional[str] = None,
        translation_manager: Optional[Any] = None,
    ) -> str:
        r = getattr(self, register_name, None)
        return r.get_field_description(field_name, language=language, translation_manager=translation_manager) if r and hasattr(r, "get_field_description") else ""

    def get_field_descriptions(self, separator: str = ".") -> Dict[str, str]:
        result: Dict[str, str] = {}
        for rn in self.register_names():  # type: ignore[attr-defined]
            r = getattr(self, rn, None)
            if r and hasattr(r, "get_field_descriptions"):
                for fn, desc in r.get_field_descriptions().items():
                    result[f"{rn}{separator}{fn}"] = desc
        return result

    def validate_field_value(
        self, register_name: str, field_name: str, value: Any, current_access_level: int = 0
    ) -> tuple[bool, Optional[str]]:
        r = getattr(self, register_name, None)
        if not r or not hasattr(r, "validate_field_value"):
            return False, f"Регистр {register_name} не найден"
        return r.validate_field_value(field_name, value, current_access_level)

    def can_modify_field(self, register_name: str, field_name: str, access_level: int = 0) -> bool:
        r = getattr(self, register_name, None)
        return bool(r and hasattr(r, "can_modify_field") and r.can_modify_field(field_name, access_level))

    def get_all_fields_metadata(
        self, access_level: int = 0, separator: str = "."
    ) -> Dict[str, Dict[str, Any]]:
        result: Dict[str, Dict[str, Any]] = {}
        for rn in self.register_names():  # type: ignore[attr-defined]
            r = getattr(self, rn, None)
            if r and hasattr(r, "get_fields_for_access_level"):
                for fn, meta in r.get_fields_for_access_level(access_level).items():
                    result[f"{rn}{separator}{fn}"] = meta
        return result


__all__ = [
    "NumericFieldMeta",
    "RegisterMetadataHelper",
    "RegistersContainerMetadataMixin",
]
