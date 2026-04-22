# -*- coding: utf-8 -*-
"""
Единая карта регистров приложения: имя слота → класс Pydantic.

Контракт: ``REGISTER_MODELS`` — единственный источник состава менеджера; фабрика
(:func:`multiprocess_prototype.registers.factory.create_registers`) собирает
``RegistersManager`` и ``connection_map`` из этой карты.

Полная миграция UI/бэка на :mod:`multiprocess_prototype.schemas`
— отдельный эпик; пока процессорный регистр остаётся
:class:`~multiprocess_prototype.registers.schemas.processing_tab.processor.ProcessorRegisters`
(ключ ``processor``), совместимый с :func:`multiprocess_prototype.registers.snapshot_migrate.migrate_register_recipe_snapshot`.
"""

from __future__ import annotations

from typing import Any, Dict, Type

from multiprocess_framework.modules.data_schema_module import SchemaBase

from .schemas.camera_tab import CAMERA_REGISTER, CameraRegisters
from .schemas.processing_tab import (
    PROCESSOR_REGISTER,
    RENDERER_REGISTER,
    ProcessorRegisters,
    RendererRegisters,
)

REGISTER_MODELS: Dict[str, Type[SchemaBase]] = {
    CAMERA_REGISTER: CameraRegisters,
    PROCESSOR_REGISTER: ProcessorRegisters,
    RENDERER_REGISTER: RendererRegisters,
}


def default_register_instances() -> Dict[str, Any]:
    """Экземпляры для ``RegistersManager`` (один проход по ``REGISTER_MODELS``)."""
    return {name: cls() for name, cls in REGISTER_MODELS.items()}
