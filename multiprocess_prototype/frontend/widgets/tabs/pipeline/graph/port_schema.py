"""PortSchema — описание порта для визуализации в NodeItem.

Определение перенесено в чистый модуль ``.data`` (Task F.1). Здесь оставлен
ре-экспорт для обратной совместимости импортов
``from .graph.port_schema import PortSchema``. Не зависит от Qt.
"""

from __future__ import annotations

from .data import PortSchema

__all__ = ["PortSchema"]
