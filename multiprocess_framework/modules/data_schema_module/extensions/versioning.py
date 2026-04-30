# -*- coding: utf-8 -*-
"""
VersionManager — менеджер версий конфигов в ProcessData.

Зависит от ProcessData — поэтому в extensions/.
Не импортируется автоматически в основном __init__.py.

Использование:
    from multiprocess_framework.modules.data_schema_module.extensions.versioning import VersionManager, VersionInfo
"""
from ..versioning.version_manager import VersionManager, VersionInfo

__all__ = ["VersionManager", "VersionInfo"]
