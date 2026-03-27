# multiprocess_prototype/registers/__init__.py
"""
Регистры приложения — единый контракт (Dict at Boundary, ADR-008):

- **REGISTER_MODELS** (:mod:`multiprocess_prototype.registers.registry`) — имя слота
  регистра → класс Pydantic на базе ``SchemaBase``; единственный источник состава менеджера.
- **RegistersManager** (``registers_module``) — контейнер экземпляров; рецепт и IPC —
  **dict** через ``model_dump_all`` / ``model_validate_all`` (без версий схемы внутри менеджера).
- **RecipeManager** — сохраняет/загружает словари снимков; до ``model_validate_all``
  вызывается :func:`multiprocess_prototype.registers.snapshot_migrate.migrate_register_recipe_snapshot`
  (граница приложения, не менеджер).

Вне frontend и backend по смыслу; тяжёлые импорты (factory, registers_module) — лениво
через ``__getattr__``, чтобы ``command_routing`` / ``gui_command_catalog`` можно было
тестировать без полного стека.
"""
from __future__ import annotations

from typing import Any

from .command_routing import list_gui_command_ids, resolve_command_targets
from .gui_command_catalog import GUI_COMMAND_CATALOG

__all__ = [
    "REGISTER_MODELS",
    "build_default_connection_map",
    "create_registers",
    "default_register_instances",
    "GUI_COMMAND_CATALOG",
    "list_gui_command_ids",
    "ProcessorRegisters",
    "RendererRegisters",
    "resolve_command_targets",
]


def __getattr__(name: str) -> Any:
    if name == "create_registers":
        from .factory import create_registers

        return create_registers
    if name == "build_default_connection_map":
        from .factory import build_default_connection_map

        return build_default_connection_map
    if name == "REGISTER_MODELS":
        from .registry import REGISTER_MODELS

        return REGISTER_MODELS
    if name == "default_register_instances":
        from .registry import default_register_instances

        return default_register_instances
    if name == "ProcessorRegisters":
        from .schemas import ProcessorRegisters

        return ProcessorRegisters
    if name == "RendererRegisters":
        from .schemas import RendererRegisters

        return RendererRegisters
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
