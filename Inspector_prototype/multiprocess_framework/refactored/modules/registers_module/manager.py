# -*- coding: utf-8 -*-
"""
Обобщённый менеджер регистров.

Не зависит от конкретных классов регистров: принимает словарь имя -> экземпляр Pydantic-модели.
Поддерживает get_register, get_field_metadata (включая routing), validate_field_value, model_dump_all/model_validate_all.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple, Union

from .interfaces import IRegistersManager


class RegistersManager:
    """
    Менеджер регистров на основе словаря имя -> экземпляр модели.
    Каждый процесс создаёт свой экземпляр со своим набором регистров.
    """

    def __init__(
        self,
        registers: Optional[Dict[str, Any]] = None,
    ):
        """
        Args:
            registers: Словарь {имя_регистра: экземпляр_модели}. Если None — пустой менеджер.
        """
        self._registers: Dict[str, Any] = dict(registers) if registers else {}

    def get_register(self, name: str) -> Optional[Any]:
        """Получить экземпляр регистра по имени."""
        return self._registers.get(name)

    def register_names(self) -> List[str]:
        """Список имён зарегистрированных регистров."""
        return list(self._registers.keys())

    def set_register(self, name: str, instance: Any) -> None:
        """Установить экземпляр регистра (для динамического добавления/замены)."""
        self._registers[name] = instance

    def get_field_metadata(
        self,
        register_name: str,
        field_name: str,
        language: Optional[str] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """
        Метаданные поля из json_schema_extra и model_fields.
        Включает routing: {router?, channel} для маршрутизации.
        """
        reg = self._registers.get(register_name)
        if reg is None:
            return {}
        field_info = getattr(reg, "model_fields", {}).get(field_name)
        if field_info is None:
            return {}
        extra = getattr(field_info, "json_schema_extra", None) or {}
        metadata = {
            "description": getattr(field_info, "description", "") or "",
            "info": extra.get("info", ""),
            "unit": extra.get("unit", ""),
            "range": extra.get("range", ""),
            "min": extra.get("min"),
            "max": extra.get("max"),
            "access_level": extra.get("access_level", 0),
            "examples": extra.get("examples", []),
            "default": getattr(field_info, "default", None),
            "readonly": extra.get("readonly", False),
            "hidden": extra.get("hidden", False),
        }
        if "routing" in extra:
            metadata["routing"] = dict(extra["routing"])
        for key in ("info_i18n", "description_i18n"):
            if key in extra:
                metadata[key] = extra[key]
        return metadata

    def validate_field_value(
        self,
        register_name: str,
        field_name: str,
        value: Any,
        current_access_level: int = 0,
    ) -> Tuple[bool, Optional[str]]:
        """Проверка значения по min/max и уровню доступа."""
        meta = self.get_field_metadata(register_name, field_name)
        if not meta:
            return False, f"Поле {register_name}.{field_name} не найдено"
        if meta.get("access_level", 0) > current_access_level:
            return False, f"Недостаточно прав доступа"
        if isinstance(value, (int, float)):
            min_val, max_val = meta.get("min"), meta.get("max")
            if min_val is not None and value < min_val:
                return False, f"Значение {value} меньше минимального {min_val}"
            if max_val is not None and value > max_val:
                return False, f"Значение {value} больше максимального {max_val}"
        return True, None

    def model_dump_all(self) -> Dict[str, Any]:
        """Экспорт всех регистров в словарь."""
        out: Dict[str, Any] = {}
        for name, reg in self._registers.items():
            if hasattr(reg, "model_dump"):
                out[name] = reg.model_dump()
            else:
                out[name] = dict(reg) if hasattr(reg, "__iter__") else {}
        return out

    def model_validate_all(self, data: Dict[str, Any], strict: bool = False) -> None:
        """Загрузить данные в регистры. Модели должны поддерживать model_validate (Pydantic v2)."""
        for name, reg in list(self._registers.items()):
            if name not in data:
                continue
            model_class = type(reg)
            if hasattr(model_class, "model_validate"):
                validated = model_class.model_validate(data[name], strict=strict)
                self._registers[name] = validated
