# multiprocess_prototype/registers/connection_map.py
"""
Совместимость: DEFAULT_CONNECTION_MAP собирается из тех же схем, что и factory.

Предпочтительно вызывать create_registers() или build_default_connection_map() из factory.
"""
from .factory import build_default_connection_map

DEFAULT_CONNECTION_MAP = build_default_connection_map()
