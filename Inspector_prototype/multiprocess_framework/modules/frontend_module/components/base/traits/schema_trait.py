# -*- coding: utf-8 -*-
"""
SchemaTrait — работа с ResolvedMeta из data_schema.

Универсальный трейт для доступа к метаданным поля.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from multiprocess_framework.modules.frontend_module.components.base.interfaces import (
    IFieldBinding,
    IRegisterPort,
)
from multiprocess_framework.modules.frontend_module.schemas.register_binding import ResolvedMeta

if TYPE_CHECKING:
    from multiprocess_framework.modules.frontend_module.components.base.config import LabelOverride


class SchemaTrait:
    """Трейт: работа с ResolvedMeta из data_schema."""

    def __init__(
        self,
        binding: IFieldBinding,
        adapter: IRegisterPort,
        config_override: "LabelOverride | None" = None,
    ) -> None:
        self._binding = binding
        self._adapter = adapter
        self._config_override = config_override
        self._refresh_meta()

    def _refresh_meta(self) -> None:
        config = dict(getattr(self._binding, "to_config_dict", lambda: {})() or {})
        if self._config_override:
            config.update(self._config_override.to_merge_dict())
        self._meta = self._adapter.resolve_meta(
            self._binding.register_name,
            self._binding.field_name,
            config,
        )

    def refresh(self) -> None:
        """Перечитать метаданные через адаптер (например, после изменения полей регистра)."""
        self._refresh_meta()

    @property
    def meta(self) -> ResolvedMeta | None:
        return self._meta

    @property
    def label(self) -> str:
        """Метка с учётом unit."""
        if not self._meta:
            return getattr(self._binding, "field_name", "") or ""
        base = self._meta.label or getattr(self._binding, "field_name", "")
        if self._meta.unit:
            return f"{base} ({self._meta.unit})"
        return base

    @property
    def effective_access_level(self) -> int:
        """Максимум из конфига и метаданных."""
        if not self._meta:
            return getattr(self._binding, "access_level", 0)
        meta_access = getattr(self._meta, "access_level", 0)
        return max(getattr(self._binding, "access_level", 0), meta_access)

    @property
    def description(self) -> str:
        return getattr(self._meta, "description", "") if self._meta else ""
