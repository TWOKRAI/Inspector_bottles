# multiprocess_prototype/backend/__init__.py
"""
Backend Inspector Prototype.

Конфиги и процессы: camera, processor, renderer, robot, database.
"""

from . import configs
from . import processes

__all__ = ["configs", "processes"]
