# -*- coding: utf-8 -*-
"""
ComboPresenter — композиция traits для выпадающего списка.

Контракт View: `IControlView[str]` (реализация — `ComboView`).
"""

from __future__ import annotations

import warnings
from typing import TYPE_CHECKING, List, Optional

from multiprocess_framework.modules.frontend_module.components.base.control_hooks import (
    ControlHooks,
    emit_access_denied,
    emit_write_committed,
    emit_write_rejected,
)
from multiprocess_framework.modules.frontend_module.components.base.interfaces import (
    IControlView,
    IFieldBinding,
    IRegisterPort,
)
from multiprocess_framework.modules.frontend_module.components.base.traits import (
    AccessTrait,
    SchemaTrait,
    SyncTrait,
)
from multiprocess_framework.modules.frontend_module.components.combo.config import ComboViewConfig
from multiprocess_framework.modules.frontend_module.managers.access_context import (
    AccessContext,
)

if TYPE_CHECKING:
    from multiprocess_framework.modules.frontend_module.forms.form_context import FormContext


class ComboPresenter:
    """
    Связывает `IControlView[str]` с полем регистра через `SchemaTrait`, `SyncTrait`, `AccessTrait`.

    Значение пишется в регистр сразу при изменении выбора (без debounce и без `on_finished`).
    """

    def __init__(
        self,
        binding: IFieldBinding,
        adapter: IRegisterPort,
        view_config: ComboViewConfig | None = None,
        current_access_level: int = 0,
        hooks: ControlHooks | None = None,
        items: List[str] | None = None,
        *,
        form_ctx: "FormContext | None" = None,
    ) -> None:
        """
        Args:
            binding: Привязка к `register_name.field_name` (+ `access_level`, опционально `index`).
            adapter: Доступ к чтению/записи/подписке (обычно `RegisterAdapter`).
            view_config: UI-переопределения (`label`, `tooltip` — приоритет
                над метаданными регистра).
            current_access_level: Текущий уровень доступа пользователя для `AccessTrait`.
            hooks: Колбэки для внешних менеджеров (лог / ошибки / статистика).
            items: Список допустимых вариантов для QComboBox. Если None — caller
                настраивает через `view.set_items()` напрямую.
            form_ctx: обязателен в production. Если передан, write идёт через
                ``form_ctx.write(...)`` (ActionBus + coalescing + undo/redo).
                None допустим только в ``_examples/`` и FW unit-тестах (без ActionBus).
                В production None вызовет ``DeprecationWarning``.
        """
        self._binding = binding
        self._hooks = hooks
        self._view_config = view_config
        self._form_ctx = form_ctx
        self._items: List[str] = items or []
        self._schema = SchemaTrait(binding, adapter, view_config)
        self._sync = SyncTrait(binding, adapter)
        view_perm = view_config.required_view_permission if view_config else None
        edit_perm = view_config.required_edit_permission if view_config else None
        self._access = AccessTrait(
            self._schema.effective_access_level,
            required_view_permission=view_perm,
            required_edit_permission=edit_perm,
        )
        self._access.update(current_access_level)
        self._view: Optional[IControlView[str]] = None

    def _effective_tooltip(self) -> str:
        """Подсказка: непустой `ComboViewConfig.tooltip` иначе описание из метаданных регистра."""
        if self._view_config and self._view_config.tooltip:
            t = str(self._view_config.tooltip).strip()
            if t:
                return t
        return self._schema.description

    def attach_view(self, view: IControlView[str]) -> None:
        """
        Подключить view: установить items, настроить подписи, подписаться на изменения.

        После вызова виджет отражает текущее значение из регистра.
        """
        self._view = view
        # Установить items если они есть и view поддерживает set_items
        if self._items and hasattr(view, "set_items"):
            view.set_items(self._items)  # type: ignore[attr-defined]
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

    def _on_changed(self, value: str) -> None:
        """Обработчик смены выбора пользователем: запись в регистр или откат при запрете прав."""
        if not self._access.can_modify():
            emit_access_denied(
                self._hooks,
                self._binding,
                "combo",
                value,
            )
            self._sync_from_model()
            return

        if self._form_ctx is not None:
            # Новый путь: write через ActionBus (coalescing, undo/redo, IPC bridge).
            old_value = self._sync.read()
            ok = self._form_ctx.write(
                self._binding.register_name,
                self._binding.field_name,
                value,
                old_value,
            )
            err = None if ok else "write failed"
        else:
            # LEGACY ONLY: _examples/ и FW unit-тесты. В production form_ctx обязателен.
            warnings.warn(
                "ComboPresenter._on_changed без form_ctx — legacy путь только для "
                "_examples/ и FW unit-тестов. Передай form_ctx в production-коде.",
                DeprecationWarning,
                stacklevel=2,
            )
            ok, err = self._sync.write(value)

        if not ok:
            msg = err or "write failed"
            emit_write_rejected(
                self._hooks,
                self._binding,
                "combo",
                msg,
                value,
            )
            self._sync_from_model()
            if err and self._view is not None:
                self._view.show_error(err)
        else:
            emit_write_committed(
                self._hooks,
                self._binding,
                "combo",
                value,
            )

    def _on_external_change(self, value: object) -> None:
        """Реакция на изменение поля извне (подписка `SyncTrait`); без эмита обратно в модель."""
        # SyncTrait.read() может вернуть int (для Literal[1,2,3]) — всегда str-каст.
        self._view.set_value_silent(str(value))

    def _sync_from_model(self) -> None:
        """Выставить текущее значение из регистра (str-каст)."""
        self._view.set_value_silent(str(self._sync.read()))

    def set_access_level(self, level: int) -> None:
        """Обновить уровень доступа; если view уже прикреплён — обновить `set_enabled`."""
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
