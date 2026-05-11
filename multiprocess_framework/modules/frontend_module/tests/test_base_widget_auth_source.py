# -*- coding: utf-8 -*-
"""BaseConfigurableWidget — реактивная подписка на AuthState через auth_source."""
from __future__ import annotations

import pytest
from PySide6.QtCore import QObject, Signal

from multiprocess_framework.modules.frontend_module.components.base.traits.access_trait import (
    AccessTrait,
)
from multiprocess_framework.modules.frontend_module.core.base_configurable_widget import (
    BaseConfigurableWidget,
)
from multiprocess_framework.modules.frontend_module.managers.access_context import (
    AccessContext,
)


class _StubAuthSource(QObject):
    """Минимальный AuthState: сигнал access_context_changed + атрибут access_context."""

    access_context_changed = Signal(AccessContext)

    def __init__(self, ctx: AccessContext | None = None) -> None:
        super().__init__()
        self.access_context: AccessContext = ctx or AccessContext()

    def set_context(self, ctx: AccessContext) -> None:
        self.access_context = ctx
        self.access_context_changed.emit(ctx)


class _WidgetWithTrait(BaseConfigurableWidget):
    """Тестовый виджет — добавляет _trait с view+edit permissions."""

    def __init__(self, view_perm: str, edit_perm: str, auth_source=None) -> None:
        super().__init__(auth_source=auth_source)
        self._trait = AccessTrait(
            legacy_required_level=0,
            required_view_permission=view_perm,
            required_edit_permission=edit_perm,
        )
        # Применить начальный контекст после установки _trait
        if auth_source is not None:
            self._on_auth_context_changed(auth_source.access_context)


class TestBaseWidgetAuthSource:
    """auth_source подписка автоматически применяет AccessContext к _trait."""

    def test_no_auth_source_legacy_noop(self, qtbot):
        """Без auth_source виджет создаётся как раньше — никаких подписок."""
        w = BaseConfigurableWidget()
        qtbot.addWidget(w)
        # Нет _trait — не падает; access_context_changed не вызывается
        assert getattr(w, "_auth_source", None) is None

    def test_initial_context_applied(self, qtbot):
        """Сразу после создания текущий AccessContext применён к trait."""
        stub = _StubAuthSource(
            AccessContext(permissions=frozenset({"tabs.x.view", "tabs.x.edit"}))
        )
        w = _WidgetWithTrait("tabs.x.view", "tabs.x.edit", auth_source=stub)
        qtbot.addWidget(w)
        assert w._trait.can_view() is True
        assert w._trait.can_modify() is True

    def test_login_reapplies_trait(self, qtbot):
        """access_context_changed → trait обновляется реактивно."""
        stub = _StubAuthSource()  # пустой контекст
        w = _WidgetWithTrait("tabs.x.view", "tabs.x.edit", auth_source=stub)
        qtbot.addWidget(w)
        assert w._trait.can_view() is False

        # Login → permission получен
        stub.set_context(
            AccessContext(permissions=frozenset({"tabs.x.view", "tabs.x.edit"}))
        )
        assert w._trait.can_view() is True
        assert w._trait.can_modify() is True

    def test_logout_disables_modify(self, qtbot):
        """Logout — trait снова без permissions, can_modify=False."""
        stub = _StubAuthSource(
            AccessContext(permissions=frozenset({"tabs.x.view", "tabs.x.edit"}))
        )
        w = _WidgetWithTrait("tabs.x.view", "tabs.x.edit", auth_source=stub)
        qtbot.addWidget(w)
        assert w._trait.can_modify() is True

        stub.set_context(AccessContext())
        assert w._trait.can_modify() is False

    def test_auth_source_without_signal_is_safe(self, qtbot):
        """Если у auth_source нет access_context_changed — корректно no-op."""

        class _BadSource:
            access_context = AccessContext()

        # Создание не должно падать
        w = BaseConfigurableWidget(auth_source=_BadSource())
        qtbot.addWidget(w)
