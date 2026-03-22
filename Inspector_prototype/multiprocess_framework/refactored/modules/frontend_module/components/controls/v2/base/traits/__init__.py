# -*- coding: utf-8 -*-
"""Traits — переиспользуемые куски логики для композиции Presenter."""
from frontend_module.components.controls.v2.base.traits.access_trait import AccessTrait
from frontend_module.components.controls.v2.base.traits.debounce_trait import DebounceTrait
from frontend_module.components.controls.v2.base.traits.legacy_sync_trait import (
    LegacySyncContext,
    LegacySyncTrait,
)
from frontend_module.components.controls.v2.base.traits.schema_trait import SchemaTrait
from frontend_module.components.controls.v2.base.traits.sync_trait import SyncTrait

__all__ = [
    "SchemaTrait",
    "SyncTrait",
    "DebounceTrait",
    "AccessTrait",
    "LegacySyncTrait",
    "LegacySyncContext",
]
