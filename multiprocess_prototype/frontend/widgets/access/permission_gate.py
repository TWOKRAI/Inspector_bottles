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


def propagate_access_context_to_tree(
    root: "QWidget",
    auth_state: "AuthState | None",
) -> None:
    """Подписать дерево виджетов под `root` на изменения AccessContext.

    Алгоритм:
    1. Подписаться на `auth_state.access_context_changed`.
    2. При каждом сигнале (и сразу при подключении) рекурсивно обойти
       `root.findChildren(QWidget)`:
       - если у виджета есть атрибут `_trait` с методом `update` —
         вызвать `_trait.update(ctx)`.
       - если есть `_apply_access` — вызвать.
       - если есть `_presenter.set_access_context` — вызвать (через
         любой подходящий атрибут: `_presenter`, `presenter`, `_access`).

    Используется в `app.py` сразу после создания `MainWindow`. Tab-код
    ничего дополнительно не должен делать — любой виджет с `_trait`
    или presenter автоматически реагирует на login/logout/смену роли.

    Без `auth_state` — no-op (legacy/тесты).
    """
    if auth_state is None:
        return

    def _apply(ctx: "AccessContext") -> None:
        from PySide6.QtWidgets import QWidget as _QWidget

        for widget in root.findChildren(_QWidget):
            trait = getattr(widget, "_trait", None)
            if trait is not None and hasattr(trait, "update"):
                try:
                    trait.update(ctx)
                except Exception:
                    pass
            apply_access = getattr(widget, "_apply_access", None)
            if callable(apply_access):
                try:
                    apply_access()
                except Exception:
                    pass
            for attr in ("_presenter", "presenter"):
                presenter = getattr(widget, attr, None)
                if presenter is None:
                    continue
                set_ctx = getattr(presenter, "set_access_context", None)
                if callable(set_ctx):
                    try:
                        set_ctx(ctx)
                    except Exception:
                        pass
                break  # достаточно одного presenter-атрибута

    _apply(auth_state.access_context)
    auth_state.access_context_changed.connect(_apply)


def gate_register_view(
    view: "QWidget",
    edit_permission: str,
    auth_state: "AuthState | None",
    *,
    view_permission: str | None = None,
) -> None:
    """Применить permission gating ко всем editors в RegisterView.

    Args:
        view: экземпляр RegisterView (с методом `editors() -> dict[str, FieldEditor]`).
        edit_permission: permission на редактирование полей (`tabs.<id>.edit`).
        auth_state: текущий AuthState. None → no-op.
        view_permission: опционально — permission на показ всего RegisterView
            (`tabs.<id>.view`). Если задан и отсутствует — RegisterView
            скрывается через `setVisible(False)`.

    Эффект:
    - `view_permission` (если задан) отсутствует → весь RegisterView скрыт.
    - `edit_permission` отсутствует → каждый `editor.widget` переходит в
      `setEnabled(False)` + `readOnly=true` (QSS — приглушённый стиль).
    - Подписка на `access_context_changed` пересчитывает состояние при
      login/logout/смене роли.

    Используется в табах, у которых master-detail построен на RegisterView
    (Plugins, Services, Recipes cards-страница).
    """
    if auth_state is None:
        return

    def _apply(ctx: "AccessContext") -> None:
        if view_permission is not None:
            visible = ctx.has_permission(view_permission)
            view.setVisible(visible)
            if not visible:
                return
        else:
            view.setVisible(True)

        allowed = ctx.has_permission(edit_permission)
        # Достучаться до editors через публичный API; gracefully fall back,
        # если структура RegisterView другая.
        editors_fn = getattr(view, "editors", None)
        if editors_fn is None:
            return
        editors = editors_fn() if callable(editors_fn) else editors_fn
        if not isinstance(editors, dict):
            return
        for editor in editors.values():
            widget = getattr(editor, "widget", None)
            if widget is None:
                continue
            widget.setEnabled(allowed)
            widget.setProperty("readOnly", not allowed)
            style = widget.style()
            if style is not None:
                style.unpolish(widget)
                style.polish(widget)

    _apply(auth_state.access_context)
    auth_state.access_context_changed.connect(_apply)


def install_permission_aware_enable(
    widget: "QWidget",
    permission: str,
    auth_state: "AuthState | None",
) -> None:
    """Подменить `widget.setEnabled` на permission-aware proxy.

    После установки вызовы `widget.setEnabled(True)` со стороны selection-aware
    логики таба автоматически учитывают наличие permission: enabled только
    если `base_enabled AND has_permission`. `setEnabled(False)` всегда
    отключает. Дополнительно подписка на `access_context_changed`
    пересчитывает состояние при смене роли.

    Без `auth_state` — no-op (legacy/тесты).

    Use case: вкладки с selection-driven кнопками (Load/Delete), которые
    управляют enabled по выбору строки. Permission-driven gating
    наслаивается прозрачно — таб-код не меняется.
    """
    if auth_state is None:
        return

    original_set_enabled = widget.setEnabled
    state = {"base": bool(widget.isEnabled())}

    def _refresh() -> None:
        base = state["base"]
        if not base:
            original_set_enabled(False)
            widget.setProperty("readOnly", False)
            return
        allowed = auth_state.access_context.has_permission(permission)
        original_set_enabled(allowed)
        widget.setProperty("readOnly", not allowed)
        style = widget.style()
        if style is not None:
            style.unpolish(widget)
            style.polish(widget)

    def proxy(enabled: bool) -> None:
        state["base"] = bool(enabled)
        _refresh()

    widget.setEnabled = proxy  # type: ignore[method-assign]
    auth_state.access_context_changed.connect(lambda _ctx: _refresh())
    _refresh()
