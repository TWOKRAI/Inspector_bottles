"""Frame Buffer plugin — буфер кадров в RAM по времени съёма (JPEG, индекс по capture_ns).

Purpose: импорт пакета исполняет @register_plugin и экспортирует плагин, конфиг и регистры.
"""

from .config import FrameBufferPluginConfig
from .plugin import FrameBufferPlugin
from .registers import FrameBufferRegisters

__all__ = ["FrameBufferPlugin", "FrameBufferPluginConfig", "FrameBufferRegisters"]
