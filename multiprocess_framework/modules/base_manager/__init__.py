"""
base_manager — основа для всех менеджеров системы.

Публичный API модуля. Импортируйте только отсюда.

Примеры:
    from multiprocess_framework.modules.base_manager import BaseManager, ObservableMixin, BaseAdapter
    from multiprocess_framework.modules.base_manager.interfaces import IBaseManager, IBaseAdapter, IObservableMixin
"""

from .core.base_manager import BaseManager
from .adapters.base_adapter import BaseAdapter
from .mixins.observable_mixin import ObservableMixin
from .configs.base_manager_config import BaseManagerConfig
from .types import ProcessStatus

# Контракт владения (ADR-BM-008): только дверь и сторож корней.
# Классы Scope/Handle не экспортируются — снаружи аннотация IScope/IHandle.
from .core.lifetime import open_scope, unclosed_roots

__all__ = [
    "BaseManager",
    "BaseAdapter",
    "ObservableMixin",
    "BaseManagerConfig",
    "ProcessStatus",
    "open_scope",
    "unclosed_roots",
]
