# -*- coding: utf-8 -*-
"""
Метаданные полей регистров.

RegisterMetadataHelper — миксин для классов *Registers (DrawRegisters, CameraRegisters, ...).
Экземпляр регистра получает методы get_field_metadata(field_name), get_field_description(field_name) и т.д.;
источник истины — self (модель Pydantic).

RegistersContainerMetadataMixin — миксин для контейнера регистров (RegistersManager).
Добавляет get_field_metadata(register_name, field_name) и др., делегируя в соответствующий экземпляр регистра.
"""
from typing import Any, Dict, Optional

from App.Registers.models.field_core.meta_models import BaseFieldMeta, NumericFieldMeta


class RegisterMetadataHelper:
    """
    Миксин для моделей *Registers. Экземпляр регистра — self.
    Методы работают с полями этого регистра (без аргумента register_name).
    """

    def get_field_metadata(
        self,
        field_name: str,
        language: Optional[str] = None,
        translation_manager: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Получить метаданные поля (description, info, unit, range, min, max, ...).
        self — экземпляр регистра (например DrawRegisters).
        """
        field_info = self.model_fields.get(field_name)  # type: ignore[attr-defined]
        if not field_info:
            return {}

        json_schema_extra = field_info.json_schema_extra or {}
        range_str = json_schema_extra.get('range', '')
        min_val = json_schema_extra.get('min', None)
        max_val = json_schema_extra.get('max', None)

        if range_str and min_val is None and max_val is None:
            try:
                if '-' in range_str:
                    parts = range_str.split('-', 1)
                    if len(parts) == 2:
                        min_val = int(parts[0].strip()) if parts[0].strip() else None
                        max_val = int(parts[1].strip()) if parts[1].strip() else None
            except (ValueError, AttributeError):
                pass

        metadata: Dict[str, Any] = {
            'description': field_info.description or '',
            'info': json_schema_extra.get('info', ''),
            'unit': json_schema_extra.get('unit', ''),
            'range': range_str,
            'min': min_val,
            'max': max_val,
            'access_level': json_schema_extra.get('access_level', 0),
            'examples': json_schema_extra.get('examples', []),
            'default': getattr(field_info, 'default', None),
            'readonly': json_schema_extra.get('readonly', False),
            'hidden': json_schema_extra.get('hidden', False),
        }
        if 'info_i18n' in json_schema_extra:
            metadata['info_i18n'] = json_schema_extra['info_i18n']
        if 'description_i18n' in json_schema_extra:
            metadata['description_i18n'] = json_schema_extra['description_i18n']
        if 'routing' in json_schema_extra:
            metadata['routing'] = json_schema_extra['routing']

        if language and translation_manager:
            if 'info_i18n' in metadata:
                t = metadata['info_i18n'].get(language)
                if t:
                    metadata['info'] = t
            if 'description_i18n' in metadata:
                t = metadata['description_i18n'].get(language)
                if t:
                    metadata['description'] = t

        return metadata

    def get_field_meta_model(
        self,
        field_name: str,
    ) -> BaseFieldMeta | None:
        """
        Типизированная модель метаданных поля.

        Обёртка над json_schema_extra, которая позволяет работать с полем как
        с объектом (BaseFieldMeta / NumericFieldMeta) вместо «сырого» dict.
        """
        field_info = self.model_fields.get(field_name)  # type: ignore[attr-defined]
        if not field_info:
            return None

        json_schema_extra = field_info.json_schema_extra or {}

        base_kwargs: Dict[str, Any] = {
            "default": getattr(field_info, "default", None),
            "description": field_info.description or "",
            "info": json_schema_extra.get("info", ""),
            "info_i18n": json_schema_extra.get("info_i18n", {}) or {},
            "description_i18n": json_schema_extra.get("description_i18n", {}) or {},
            "unit": json_schema_extra.get("unit", ""),
            "examples": json_schema_extra.get("examples", []) or [],
            "routing": json_schema_extra.get("routing", {}) or {},
            "access_level": json_schema_extra.get("access_level", 0),
            "readonly": json_schema_extra.get("readonly", False),
            "hidden": json_schema_extra.get("hidden", False),
        }

        # Простая эвристика: если есть числовые параметры диапазона/коэф.,
        # считаем поле числовым и возвращаем NumericFieldMeta.
        if any(k in json_schema_extra for k in ("min", "max", "transfer_k", "round_k")):
            return NumericFieldMeta(
                **base_kwargs,
                min=json_schema_extra.get("min"),
                max=json_schema_extra.get("max"),
                transfer_k=json_schema_extra.get("transfer_k", 1.0),
                round_k=json_schema_extra.get("round_k", 1),
            )

        return BaseFieldMeta(**base_kwargs)

    def get_field_description(
        self,
        field_name: str,
        language: Optional[str] = None,
        translation_manager: Optional[Any] = None,
    ) -> str:
        """Описание поля с учётом i18n."""
        metadata = self.get_field_metadata(
            field_name, language=language, translation_manager=translation_manager
        )
        if translation_manager:
            return translation_manager.translate_metadata(metadata, field='info')
        if language and isinstance(metadata.get('info_i18n'), dict):
            t = metadata['info_i18n'].get(language)
            if t:
                return t
        return metadata.get('info') or metadata.get('description', '')

    def get_field_descriptions(self, separator: str = '.') -> Dict[str, str]:
        """Словарь {field_name: description} для всех полей этого регистра."""
        result: Dict[str, str] = {}
        for fn, fi in self.model_fields.items():  # type: ignore[attr-defined]
            extra = fi.json_schema_extra or {}
            result[fn] = extra.get('info') or (fi.description or '')
        return result

    def validate_field_value(
        self,
        field_name: str,
        value: Any,
        current_access_level: int = 0,
    ) -> tuple[bool, Optional[str]]:
        """Проверить значение поля (диапазон, уровень доступа)."""
        metadata = self.get_field_metadata(field_name)
        if not metadata:
            return False, f"Поле {field_name} не найдено"

        if metadata.get('access_level', 0) > current_access_level:
            return False, "Недостаточно прав доступа"

        if isinstance(value, (int, float)):
            min_v, max_v = metadata.get('min'), metadata.get('max')
            if min_v is not None and value < min_v:
                return False, f"Значение {value} меньше минимального {min_v}"
            if max_v is not None and value > max_v:
                return False, f"Значение {value} больше максимального {max_v}"
        return True, None

    def get_fields_for_access_level(
        self, access_level: int = 0
    ) -> Dict[str, Dict[str, Any]]:
        """Поля этого регистра, доступные для уровня доступа."""
        result: Dict[str, Dict[str, Any]] = {}
        for fn in self.model_fields.keys():  # type: ignore[attr-defined]
            meta = self.get_field_metadata(fn)
            if meta.get('access_level', 0) <= access_level and not meta.get('hidden'):
                result[fn] = meta
        return result

    def can_modify_field(
        self, field_name: str, access_level: int = 0
    ) -> bool:
        """Можно ли изменять поле при данном уровне доступа."""
        metadata = self.get_field_metadata(field_name)
        if not metadata:
            return False
        if metadata.get('access_level', 0) > access_level:
            return False
        if metadata.get('readonly'):
            return False
        return True


class RegistersContainerMetadataMixin:
    """
    Миксин для контейнера регистров (например RegistersManager).
    Добавляет get_field_metadata(register_name, field_name) и др., делегируя в экземпляр регистра.
    """

    def get_field_metadata(
        self,
        register_name: str,
        field_name: str,
        language: Optional[str] = None,
        translation_manager: Optional[Any] = None,
    ) -> Dict[str, Any]:
        register = getattr(self, register_name, None)
        if register is None or not hasattr(register, 'get_field_metadata'):
            return {}
        return register.get_field_metadata(
            field_name,
            language=language,
            translation_manager=translation_manager,
        )

    def get_field_description(
        self,
        register_name: str,
        field_name: str,
        language: Optional[str] = None,
        translation_manager: Optional[Any] = None,
    ) -> str:
        register = getattr(self, register_name, None)
        if register is None or not hasattr(register, 'get_field_description'):
            return ''
        return register.get_field_description(
            field_name,
            language=language,
            translation_manager=translation_manager,
        )

    def get_field_descriptions(
        self, separator: str = '.'
    ) -> Dict[str, str]:
        result: Dict[str, str] = {}
        for rn in self.register_names():  # type: ignore[attr-defined]
            register = getattr(self, rn, None)
            if register is None or not hasattr(register, 'get_field_descriptions'):
                continue
            for fn, desc in register.get_field_descriptions().items():
                result[f"{rn}{separator}{fn}"] = desc
        return result

    def validate_field_value(
        self,
        register_name: str,
        field_name: str,
        value: Any,
        current_access_level: int = 0,
    ) -> tuple[bool, Optional[str]]:
        register = getattr(self, register_name, None)
        if register is None or not hasattr(register, 'validate_field_value'):
            return False, f"Регистр {register_name} не найден"
        return register.validate_field_value(
            field_name, value, current_access_level=current_access_level
        )

    def can_modify_field(
        self,
        register_name: str,
        field_name: str,
        access_level: int = 0,
    ) -> bool:
        register = getattr(self, register_name, None)
        if register is None or not hasattr(register, 'can_modify_field'):
            return False
        return register.can_modify_field(field_name, access_level)

    def get_all_fields_metadata(
        self,
        access_level: int = 0,
        separator: str = '.',
    ) -> Dict[str, Dict[str, Any]]:
        result: Dict[str, Dict[str, Any]] = {}
        for rn in self.register_names():  # type: ignore[attr-defined]
            register = getattr(self, rn, None)
            if register is None or not hasattr(register, 'get_fields_for_access_level'):
                continue
            for fn, meta in register.get_fields_for_access_level(access_level).items():
                result[f"{rn}{separator}{fn}"] = meta
        return result


__all__ = ['RegisterMetadataHelper', 'RegistersContainerMetadataMixin']
