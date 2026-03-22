# -*- coding: utf-8 -*-
"""
NumericPresenter — композиция traits для числовых полей (slider, spinbox).

Работает с INumericView (контракт, без hasattr).
"""
from __future__ import annotations

from typing import Optional

from frontend_module.components.controls.v2.base import RegisterAdapter, ValueTransformer
from frontend_module.components.controls.v2.base.config import BindingConfig
from frontend_module.components.controls.v2.base.interfaces import INumericView
from frontend_module.components.controls.v2.base.traits import (
    AccessTrait,
    DebounceTrait,
    LegacySyncContext,
    LegacySyncTrait,
    SchemaTrait,
    SyncTrait,
)
from frontend_module.components.controls.v2.numeric.config import NumericViewConfig


class NumericPresenter:
    """
    Presenter для числовых полей.
    Композиция: Schema + Sync + Debounce + Access + ValueTransformer [+ LegacySync].
    """

    def __init__(
        self,
        binding: BindingConfig,
        adapter: RegisterAdapter,
        view_config: NumericViewConfig | None = None,
        current_access_level: int = 0,
        legacy_context: LegacySyncContext | None = None,
        registers_manager: Optional[object] = None,
    ) -> None:
        config_override = view_config.to_label_override() if view_config else None
        self._schema = SchemaTrait(binding, adapter, config_override)
        self._sync = SyncTrait(binding, adapter)
        self._debounce = DebounceTrait(ms=100)
        self._access = AccessTrait(self._schema.effective_access_level)
        self._access.update(current_access_level)
        self._transform = ValueTransformer(self._schema.meta)
        self._view: Optional[INumericView] = None
        self._binding = binding
        self._legacy = None
        if legacy_context and registers_manager:
            self._legacy = LegacySyncTrait(
                legacy_context,
                registers_manager,
                binding.register_name,
                binding.field_name,
            )

    def attach_view(self, view: INumericView) -> None:
        """Внедрение View и настройка (контракт INumericView)."""
        self._view = view
        meta = self._schema.meta
        if not meta:
            return

        self._view.setup(
            label=self._schema.label,
            tooltip=self._schema.description,
            enabled=self._access.can_modify(),
        )

        ui_min = self._transform.to_ui(meta.min_val)
        ui_max = self._transform.to_ui(meta.max_val)
        step = self._transform.get_step()
        self._view.set_range(min_val=ui_min, max_val=ui_max, step=step)

        if meta.round_k == 0:
            self._view.set_validator_int()
        else:
            self._view.set_validator_float()

        self._view.on_changed(self._on_changing)
        self._view.on_finished(self._on_finished)
        self._sync.subscribe(self._on_external_change)
        self._sync_from_model()

        if self._legacy:
            current = self._sync.read()
            self._legacy.setup_legacy_refs(
                value=current,
                element=self._view.get_legacy_element(),
                can_modify=self._access.can_modify(),
                resolved_meta=meta,
            )

    def _on_changing(self, ui_value: float) -> None:
        """Движение слайдера — с debounce."""
        if not self._access.can_modify():
            self._sync_from_model()
            return
        ui_value = self._transform.clamp_to_range(ui_value)
        storage_value = self._transform.to_storage(ui_value)
        self._debounce.schedule(lambda: self._write(storage_value))

    def _on_finished(self, ui_value: float) -> None:
        """Enter/LostFocus — немедленная запись, отмена debounce."""
        self._debounce.cancel()
        if not self._access.can_modify():
            self._sync_from_model()
            return
        ui_value = self._transform.clamp_to_range(ui_value)
        storage_value = self._transform.to_storage(ui_value)
        self._write(storage_value)

    def _write(self, storage_value: float) -> None:
        ok, err = self._sync.write(storage_value)
        if not ok:
            self._sync_from_model()
            if err:
                self._view.show_error(err)
        elif self._legacy:
            self._legacy.notify_after_write(storage_value)

    def _on_external_change(self, storage_value: object) -> None:
        ui_value = self._transform.to_ui(storage_value)
        self._view.set_value_silent(ui_value)

    def _sync_from_model(self) -> None:
        current = self._sync.read()
        ui_value = self._transform.to_ui(current)
        self._view.set_value_silent(ui_value)

    def set_access_level(self, level: int) -> None:
        self._access.update(level)
        self._view.set_enabled(self._access.can_modify())
