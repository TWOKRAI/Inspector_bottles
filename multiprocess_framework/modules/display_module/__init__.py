"""display_module — реестр именованных SHM-каналов для отображения кадров.

Публичный API:
    - ``DisplayEntry``    — dataclass конфигурации одного дисплея
    - ``IDisplayChannel`` — Protocol SHM-канала кадров
    - ``IDisplayRegistry`` — Protocol реестра дисплеев
    - ``DisplayRegistry`` — thread-safe singleton-реализация реестра
"""

from .interfaces import DisplayEntry, IDisplayChannel, IDisplayRegistry
from .registry import DisplayRegistry

__all__ = [
    "DisplayEntry",
    "IDisplayChannel",
    "IDisplayRegistry",
    "DisplayRegistry",
]
