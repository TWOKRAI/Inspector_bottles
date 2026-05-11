# -*- coding: utf-8 -*-
"""
NumericPresenter — композиция traits для числовых полей (slider, spinbox).

Работает с INumericView (контракт, без hasattr).
"""
from __future__ import annotations

from typing import Optional

from multiprocess_framework.modules.frontend_module.components.base import RegisterAdapter, ValueTransformer
from multiprocess_framework.modules.frontend_module.components.base.control_hooks import (
    ControlHooks,
    ControlKind,
    emit_access_denied,
    emit_write_committed,
    emit_write_rejected,
)
from multiprocess_framework.modules.frontend_module.components.base.config import BindingConfig
from multiprocess_framework.modules.frontend_module.components.base.interfaces import INumericView
from multiprocess_framework.modules.frontend_module.components.base.traits import (
    AccessTrait,
    DebounceTrait,
    LegacySyncContext,
    LegacySyncTrait,
    SchemaTrait,
    SyncTrait,
)
from multiprocess_framework.modules.frontend_module.components.numeric.config import NumericViewConfig
from multiprocess_framework.modules.frontend_module.managers.access_context import (
    AccessContext,
)


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
        hooks: ControlHooks | None = None,
        control_kind: ControlKind = "numeric",
    ) -> None:
        self._hooks = hooks
        self._control_kind: ControlKind = control_kind
        config_override = view_config.to_label_override() if view_config else None
        self._schema = SchemaTrait(binding, adapter, config_override)
        self._sync = SyncTrait(binding, adapter)
        self._debounce = DebounceTrait(ms=100)
        view_perm = view_config.required_view_permission if view_config else None
        edit_perm = view_config.required_edit_permission if view_config else None
        self._access = AccessTrait(
            self._schema.effective_access_level,
            required_view_permission=view_perm,
            required_edit_permission=edit_perm,
        )
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

    def refresh_metadata(self) -> None:
        """Перечитать метаданные регистра, обновить трансформер и view (если прикреплён)."""
        self._schema.refresh()
        self._access.set_required_level(self._schema.effective_access_level)
        self._transform = ValueTransformer(self._schema.meta)
        if self._view is None:
            return
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
            emit_access_denied(
                self._hooks,
                self._binding,
                self._control_kind,
                ui_value,
            )
            self._sync_from_model()
            return
        ui_value = self._transform.clamp_to_range(ui_value)
        storage_value = self._transform.to_storage(ui_value)
        self._debounce.schedule(lambda: self._write(storage_value))

    def _on_finished(self, ui_value: float) -> None:
        """Enter/LostFocus — немедленная запись, отмена debounce."""
        self._debounce.cancel()
        if not self._access.can_modify():
            emit_access_denied(
                self._hooks,
                self._binding,
                self._control_kind,
                ui_value,
            )
            self._sync_from_model()
            return
        ui_value = self._transform.clamp_to_range(ui_value)
        storage_value = self._transform.to_storage(ui_value)
        self._write(storage_value)

    def _write(self, storage_value: float) -> None:
        ok, err = self._sync.write(storage_value)
        if not ok:
            msg = err or "write failed"
            emit_write_rejected(
                self._hooks,
                self._binding,
                self._control_kind,
                msg,
                storage_value,
            )
            self._sync_from_model()
            if err:
                self._view.show_error(err)
        else:
            emit_write_committed(
                self._hooks,
                self._binding,
                self._control_kind,
                storage_value,
            )
            if self._legacy:
                self._legacy.notify_after_write(storage_value)

    def _on_external_change(self, storage_value: object) -> None:
        ui_value = self._transform.to_ui(storage_value)
        self._view.set_value_silent(ui_value)

    def _sync_from_model(self) -> None:
        current = self._sync.read()
        if current is None and self._schema.meta is not None:
            current = self._schema.meta.default_val
        if current is None:
            current = 0
        ui_value = self._transform.to_ui(current)
        self._view.set_value_silent(ui_value)

    def set_access_level(self, level: int) -> None:
        self._access.update(level)
        if self._view is not None:
            self._view.set_enabled(self._access.can_modify())

    def set_access_context(self, ctx: AccessContext) -> None:
        """Применить новый AccessContext (имя+permissions) к контролу.

        Используется при login/logout/смене роли — пропагируется из
        AuthState.access_context_changed через RegisterView/ParamsForm.
        """
        self._access.update(ctx)
        if self._view is not None:
            self._view.set_enabled(self._access.can_modify())
