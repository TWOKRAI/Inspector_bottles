"""bridges — единый слой коммуникации UI ↔ Backend.

TopologyBridge координирует три транспорта:
- IPC Commands (RouterManager → ProcessManager) для lifecycle процессов
- Register Writes (RegistersManager → FieldRouting) для параметров
- Direct API (DisplayWindowManager) для UI-сущностей
"""

from .topology_bridge import TopologyBridge

__all__ = ["TopologyBridge"]
