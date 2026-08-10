"""
Утилиты для Base Manager Module.
"""

from .app_identity import (
    APP_NAME_ENV,
    DEFAULT_APP_NAME,
    app_name_slug,
    resolve_app_name,
)
from .name_utils import get_adapter_name_from_class

__all__ = [
    "get_adapter_name_from_class",
    "APP_NAME_ENV",
    "DEFAULT_APP_NAME",
    "resolve_app_name",
    "app_name_slug",
]
