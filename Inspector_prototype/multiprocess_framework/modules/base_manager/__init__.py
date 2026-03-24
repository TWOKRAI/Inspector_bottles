"""
base_manager — основа для всех менеджеров системы.

Публичный API модуля. Импортируйте только отсюда.

Примеры:
    from base_manager import BaseManager, ObservableMixin, BaseAdapter
    from base_manager.interfaces import IBaseManager, IBaseAdapter, IObservableMixin
"""

from .core.base_manager import BaseManager
from .adapters.base_adapter import BaseAdapter
from .mixins.observable_mixin import ObservableMixin

__all__ = [
    'BaseManager',
    'BaseAdapter',
    'ObservableMixin',
]
