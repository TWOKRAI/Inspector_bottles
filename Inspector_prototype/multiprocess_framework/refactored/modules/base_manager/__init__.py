"""
Base Manager Module - Основа для всех менеджеров системы.

Публичный API модуля. Импортируйте отсюда все необходимое.
"""

from .core.base_manager import BaseManager, _noop
from .adapters.base_adapter import BaseAdapter
from .mixins.observable_mixin import ObservableMixin

# ManagerExtensionMixin объединен с ObservableMixin
# Используйте ObservableMixin с auto_proxy=True для автоматических прокси-методов

__all__ = [
    # Основные классы
    'BaseManager',
    'BaseAdapter',
    # Миксин (объединяет ObservableMixin и ManagerExtensionMixin)
    'ObservableMixin',
]

