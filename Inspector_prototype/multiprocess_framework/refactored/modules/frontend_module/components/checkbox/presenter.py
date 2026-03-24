# -*- coding: utf-8 -*-
"""
CheckboxPresenter — композиция traits для чекбокса.

Контракт View: `IControlView[bool]` (реализация — `CheckboxView`).
"""
from __future__ import annotations

from typing import Optional

from frontend_module.components.base.control_hooks import (
    ControlHooks,
    emit_access_denied,
    emit_write_committed,
    emit_write_rejected,
)
from frontend_module.components.base.interfaces import (
    IControlView,
    IFieldBinding,
    IRegisterPort,
)
from frontend_module.components.base.traits import (
    AccessTrait,
    SchemaTrait,
    SyncTrait,
)
from frontend_module.components.checkbox.config import CheckboxViewConfig


class CheckboxPresenter:
    """
    Связывает `IControlView[bool]` с полем регистра через `SchemaTrait`, `SyncTrait`, `AccessTrait`.

    Значение пишется в регистр сразу при изменении галочки (без debounce и без `on_finished`).
    """

    def __init__(
        self,
        binding: IFieldBinding,
        adapter: IRegisterPort,
        view_config: CheckboxViewConfig | None = None,
        current_access_level: int = 0,
        hooks: ControlHooks | None = None,
    ) -> None:
        """
        Args:
            binding: Привязка к `register_name.field_name` (+ `access_level`, опционально `index`).
            adapter: Доступ к чтению/записи/подписке (обычно `RegisterAdapter`).
            view_config: UI-переопределения (`label` через `LabelOverride`, непустой `tooltip` — приоритет над описанием регистра).
            current_access_level: Текущий уровень доступа пользователя для `AccessTrait`.
            hooks: Колбэки для внешних менеджеров (лог / ошибки / статистика).
        """
        self._binding = binding
        self._hooks = hooks
        self._view_config = view_config
        config_override = view_config.to_label_override() if view_config else None
        self._schema = SchemaTrait(binding, adapter, config_override)
        self._sync = SyncTrait(binding, adapter)
        self._access = AccessTrait(self._schema.effective_access_level)
        self._access.update(current_access_level)
        self._view: Optional[IControlView[bool]] = None

    def _effective_tooltip(self) -> str:
        """Подсказка: непустой `CheckboxViewConfig.tooltip` иначе описание из метаданных регистра."""
        if self._view_config and self._view_config.tooltip:
            t = str(self._view_config.tooltip).strip()
            if t:
                return t
        return self._schema.description

    def attach_view(self, view: IControlView[bool]) -> None:
        """
        Подключить view: настроить подписи, подписаться на изменения и на внешние обновления регистра.

        После вызова виджет отражает текущее значение из регистра.
        """
        self._view = view
        self._view.setup(
            label=self._schema.label,
            tooltip=self._effective_tooltip(),
            enabled=self._access.can_modify(),
        )
        self._view.on_changed(self._on_changed)
        self._sync.subscribe(self._on_external_change)
        self._sync_from_model()

    def refresh_metadata(self) -> None:
        """Перечитать метаданные регистра и обновить view (если прикреплён)."""
        self._schema.refresh()
        self._access.set_required_level(self._schema.effective_access_level)
        if self._view is None:
            return
        self._view.setup(
            label=self._schema.label,
            tooltip=self._effective_tooltip(),
            enabled=self._access.can_modify(),
        )
        self._sync_from_model()

    def _on_changed(self, value: bool) -> None:
        """Обработчик клика пользователя: запись в регистр или откат при запрете прав."""
        if not self._access.can_modify():
            emit_access_denied(
                self._hooks,
                self._binding,
                "checkbox",
                value,
            )
            self._sync_from_model()
            return
        ok, err = self._sync.write(value)
        if not ok:
            msg = err or "write failed"
            emit_write_rejected(
                self._hooks,
                self._binding,
                "checkbox",
                msg,
                value,
            )
            self._sync_from_model()
            if err:
                self._view.show_error(err)
        else:
            emit_write_committed(
                self._hooks,
                self._binding,
                "checkbox",
                value,
            )

    def _on_external_change(self, value: object) -> None:
        """Реакция на изменение поля извне (подписка `SyncTrait`); без эмита обратно в модель."""
        self._view.set_value_silent(bool(value))

    def _sync_from_model(self) -> None:
        """Выставить галочку по текущему значению регистра (bool-каст)."""
        self._view.set_value_silent(bool(self._sync.read()))

    def set_access_level(self, level: int) -> None:
        """Обновить уровень доступа; если view уже прикреплён — обновить `set_enabled`."""
        self._access.update(level)
        if self._view is not None:
            self._view.set_enabled(self._access.can_modify())
