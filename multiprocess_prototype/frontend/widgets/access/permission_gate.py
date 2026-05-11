"""permission_gate — привязка виджета к permission через AuthState.

Использование во вкладках:

    from multiprocess_prototype.frontend.widgets.access import bind_edit_permission

    bind_edit_permission(
        self._save_btn,
        permission="tabs.settings.edit",
        auth_state=ctx.auth_state(),
    )

Эффект:
- При отсутствии permission в текущем `AccessContext` виджет переходит в
  `setEnabled(False)` и получает Qt-свойство `readOnly=true` — стиль QSS
  применяется автоматически (см. AccessTrait/BaseConfigurableWidget).
- Подписка на `auth_state.access_context_changed` пересчитывает состояние
  при login/logout/смене роли.

Если `auth_state` равен `None` (тесты/legacy) — виджет остаётся в текущем
состоянии (None permission означает «безусловный доступ»).
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Iterable

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget
    from multiprocess_framework.modules.frontend_module.managers.access_context import (
        AccessContext,
    )
    from multiprocess_prototype.frontend.state.auth_state import AuthState


def _apply_permission(widget: "QWidget", permitted: bool) -> None:
    """Применить enabled-состояние и QSS-свойство readOnly к виджету."""
    widget.setEnabled(permitted)
    widget.setProperty("readOnly", not permitted)
    style = widget.style()
    if style is not None:
        style.unpolish(widget)
        style.polish(widget)


def bind_edit_permission(
    widget: "QWidget",
    permission: str,
    auth_state: "AuthState | None",
) -> None:
    """Привязать виджет к permission: enabled только при `ctx.has_permission`.

    Args:
        widget: целевой виджет (обычно QPushButton, но любой QWidget подходит).
        permission: имя permission, например `tabs.recipes.edit`.
        auth_state: текущий AuthState. Если None — функция no-op (legacy/тесты).

    Подписка живёт пока живёт виджет; AuthState.access_context_changed
    автоматически отвязывается, если виджет удалён (Qt управляет lifetime).
    """
    if auth_state is None:
        return

    def _update(ctx: "AccessContext") -> None:
        _apply_permission(widget, ctx.has_permission(permission))

    # Применяем текущее состояние сразу — до первого сигнала.
    _update(auth_state.access_context)
    auth_state.access_context_changed.connect(_update)


def gate_edit_widgets(
    widgets: "Iterable[QWidget]",
    permission: str,
    auth_state: "AuthState | None",
) -> None:
    """Batch-применить permission к набору виджетов с одним правом."""
    for w in widgets:
        bind_edit_permission(w, permission, auth_state)
