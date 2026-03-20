# multiprocess_prototype/registers/__init__.py
"""
Регистры — единое место объявления схем и фабрики.

Вне frontend и backend.
"""
from .factory import create_registers
from .connection_map import DEFAULT_CONNECTION_MAP
from .schemas import ProcessorRegisters, RendererRegisters

__all__ = [
    "create_registers",
    "DEFAULT_CONNECTION_MAP",
    "ProcessorRegisters",
    "RendererRegisters",
]
