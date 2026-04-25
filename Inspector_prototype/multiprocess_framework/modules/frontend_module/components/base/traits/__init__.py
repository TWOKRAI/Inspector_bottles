# -*- coding: utf-8 -*-
"""Traits — переиспользуемые куски логики для композиции Presenter."""
from multiprocess_framework.modules.frontend_module.components.base.traits.access_trait import AccessTrait
from multiprocess_framework.modules.frontend_module.components.base.traits.debounce_trait import DebounceTrait
from multiprocess_framework.modules.frontend_module.components.base.traits.legacy_sync_trait import (
    LegacySyncContext,
    LegacySyncTrait,
)
from multiprocess_framework.modules.frontend_module.components.base.traits.schema_trait import SchemaTrait
from multiprocess_framework.modules.frontend_module.components.base.traits.sync_trait import SyncTrait

__all__ = [
    "SchemaTrait",
    "SyncTrait",
    "DebounceTrait",
    "AccessTrait",
    "LegacySyncTrait",
    "LegacySyncContext",
]
