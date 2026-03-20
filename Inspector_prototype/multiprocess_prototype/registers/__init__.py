# multiprocess_prototype/registers/__init__.py
"""
Регистры — единое место объявления схем и фабрики.

Вне frontend и backend.

Тяжёлые импорты (factory, registers_module) — лениво через ``__getattr__``,
чтобы ``command_routing`` / ``gui_command_catalog`` можно было тестировать без полного стека.
"""
from __future__ import annotations

from typing import Any

from .command_routing import list_gui_command_ids, resolve_command_targets
from .gui_command_catalog import GUI_COMMAND_CATALOG

__all__ = [
    "create_registers",
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
    if name == "ProcessorRegisters":
        from .schemas import ProcessorRegisters

        return ProcessorRegisters
    if name == "RendererRegisters":
        from .schemas import RendererRegisters

        return RendererRegisters
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
