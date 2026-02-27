"""Типы компонентов системы."""

from enum import Enum


class ComponentType(str, Enum):
    """Типы компонентов."""
    PROCESS = "process"
    MANAGER = "manager"
    MODULE = "module"
    WORKER = "worker"
    ADAPTER = "adapter"
    COMPONENT = "component"
    CUSTOM = "custom"

