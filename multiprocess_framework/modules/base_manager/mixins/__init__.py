"""
Миксины для Base Manager Module.
"""

from .observable_mixin import ObservableMixin

# ManagerExtensionMixin объединен с ObservableMixin
# Используйте ObservableMixin с auto_proxy=True для автоматических прокси-методов

__all__ = [
    'ObservableMixin',
]

