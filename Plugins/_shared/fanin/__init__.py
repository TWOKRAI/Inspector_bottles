"""fanin — доменные корреляционные буферы DataReceiver (fan-in / join).

Публичный API:
- ``InspectorManager`` — буферизация items по (camera_id, seq_id) для region fan-in.
- ``JoinInspectorManager`` — корреляция N именованных входов по (seq_id, data_type).
- ``build_inspector`` — фабрика выбора буфера по конфигу процесса (mode: fanin|join).

Импорт пакета регистрирует ``build_inspector`` в framework-реестре
(``process_module.generic.inspector_registry``) — generic-движок получает буфер через DI.
См. C6 дизайн §5(b) и ``README.md``.
"""

from .factory import build_inspector
from .inspector_manager import InspectorManager
from .join_inspector_manager import JoinInspectorManager

__all__ = [
    "InspectorManager",
    "JoinInspectorManager",
    "build_inspector",
]
