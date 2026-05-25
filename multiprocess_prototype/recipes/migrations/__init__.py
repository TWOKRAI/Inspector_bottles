"""migrations — миграции формата рецептов между версиями.

Текущие миграции:
- format_v1_to_v2: slot-based topology → blueprint v2
"""

from .format_v1_to_v2 import migrate_v1_to_v2, is_v1_recipe

__all__ = ["migrate_v1_to_v2", "is_v1_recipe"]
