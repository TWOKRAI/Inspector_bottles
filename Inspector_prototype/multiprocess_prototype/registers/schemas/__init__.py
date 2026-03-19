# multiprocess_prototype/registers/schemas/__init__.py
"""Схемы регистров."""

from .draw import DrawRegisters
from .processor import ProcessorRegisters
from .renderer import RendererRegisters

__all__ = ["DrawRegisters", "ProcessorRegisters", "RendererRegisters"]
