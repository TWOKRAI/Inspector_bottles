# -*- coding: utf-8 -*-
"""
SchemaBase — базовый класс для всех регистров и конфигов с метаданными полей.

Объединяет SchemaMixin (5 секций методов) и pydantic.BaseModel (Pydantic v2).
Включает автоматическую валидацию ограничений min/max из FieldMeta при создании.

Использование:

    from typing import Annotated
    from multiprocess_framework.modules.data_schema_module import FieldMeta, SchemaBase

    class ProcessConfig(SchemaBase):
        timeout: Annotated[float, FieldMeta("Таймаут, сек", min=0.1, max=60.0)] = 5.0
        workers: Annotated[int,   FieldMeta("Кол-во воркеров", min=1, max=32)]  = 4
        debug:   bool = False

    cfg = ProcessConfig()
    cfg.timeout             # → 5.0
    cfg.model_dump()        # → {"timeout": 5.0, "workers": 4, "debug": False}
    cfg.get_field_meta("timeout").max   # → 60.0
    cfg.update_field("timeout", 10.0)   # → (True, None)
    cfg.update_field("timeout", 999.0)  # → (False, "Значение 999.0 больше максимального 60.0")

Backward compatibility: RegisterBase = SchemaBase (алиас в конце файла).
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, model_validator

from .schema_mixin import SchemaMixin


class SchemaBase(SchemaMixin, BaseModel):
    """
    Базовый класс для регистров и конфигов с метаданными полей.

    Наследуйтесь для создания любых моделей:
    - регистры UI (DrawRegisters, ProcessingRegisters, ...)
    - конфиги процессов (ServerConfig, AlgorithmConfig, ...)
    - конфиги оборудования (CameraConfig, HikvisionConfig, ...)
    """

    model_config = ConfigDict(
        # Валидация типов при setattr → update_field() корректно обрабатывает ошибки
        validate_assignment=True,
        # Разрешить populate по имени поля при model_validate
        populate_by_name=True,
    )

    @model_validator(mode="after")
    def _check_field_constraints(self) -> "SchemaBase":
        """
        Проверить ограничения min/max из FieldMeta при создании экземпляра.

        Только для числовых полей (int, float). Нечисловые — пропускаются.

        Оптимизация: get_all_fields_meta() кэшируется per class — O(1).
        Итерируем только поля с FieldMeta, пропуская plain-поля без метаданных.
        """
        for name, meta in type(self).get_all_fields_meta().items():
            # Пропускаем поля без числовых ограничений — раннее завершение
            if meta.min is None and meta.max is None:
                continue
            value = getattr(self, name)
            if not isinstance(value, (int, float)):
                continue
            if meta.min is not None and value < meta.min:
                raise ValueError(
                    f"Поле '{name}': значение {value} меньше минимального {meta.min}"
                )
            if meta.max is not None and value > meta.max:
                raise ValueError(
                    f"Поле '{name}': значение {value} больше максимального {meta.max}"
                )
        return self


# Backward compatibility alias
RegisterBase = SchemaBase
