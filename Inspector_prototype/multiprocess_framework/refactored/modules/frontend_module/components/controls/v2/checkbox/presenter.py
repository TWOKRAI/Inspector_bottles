# -*- coding: utf-8 -*-
"""
CheckboxPresenter — композиция traits для чекбокса.
"""
from __future__ import annotations

from typing import Any, Optional

from frontend_module.components.controls.v2.base import RegisterAdapter
from frontend_module.components.controls.v2.base.config import BindingConfig
from frontend_module.components.controls.v2.base.traits import AccessTrait, SchemaTrait, SyncTrait
from frontend_module.components.controls.v2.checkbox.config import CheckboxViewConfig


class CheckboxPresenter:
    """Presenter для чекбокса. Без debounce, немедленная запись."""

    def __init__(
        self,
        binding: BindingConfig,
        adapter: RegisterAdapter,
        view_config: CheckboxViewConfig | None = None,
        current_access_level: int = 0,
    ) -> None:
        config_override = view_config.to_label_override() if view_config else None
        self._schema = SchemaTrait(binding, adapter, config_override)
        self._sync = SyncTrait(binding, adapter)
        self._access = AccessTrait(self._schema.effective_access_level)
        self._access.update(current_access_level)
        self._view: Optional[Any] = None

    def attach_view(self, view: Any) -> None:
        self._view = view
        self._view.setup(
            label=self._schema.label,
            tooltip=self._schema.description,
            enabled=self._access.can_modify(),
        )
        self._view.on_changed(self._on_changed)
        self._sync.subscribe(self._on_external_change)
        self._sync_from_model()

    def _on_changed(self, value: bool) -> None:
        if not self._access.can_modify():
            self._sync_from_model()
            return
        ok, err = self._sync.write(value)
        if not ok:
            self._sync_from_model()
            if err:
                self._view.show_error(err)

    def _on_external_change(self, value: Any) -> None:
        self._view.set_value_silent(bool(value))

    def _sync_from_model(self) -> None:
        self._view.set_value_silent(bool(self._sync.read()))

    def set_access_level(self, level: int) -> None:
        self._access.update(level)
        self._view.set_enabled(self._access.can_modify())
