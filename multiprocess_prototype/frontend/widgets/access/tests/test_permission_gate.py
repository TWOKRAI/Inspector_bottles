"""Тесты bind_edit_permission — gating виджетов по permission через AuthState."""
from __future__ import annotations

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QPushButton

from multiprocess_framework.modules.frontend_module.managers.access_context import (
    AccessContext,
)
from multiprocess_prototype.frontend.widgets.access import (
    bind_edit_permission,
    gate_edit_widgets,
)


class _StubAuthState(QObject):
    access_context_changed = Signal(AccessContext)

    def __init__(self, ctx: AccessContext | None = None) -> None:
        super().__init__()
        self.access_context: AccessContext = ctx or AccessContext()

    def set_context(self, ctx: AccessContext) -> None:
        self.access_context = ctx
        self.access_context_changed.emit(ctx)


class TestBindEditPermission:
    def test_no_auth_state_is_noop(self, qtbot):
        btn = QPushButton()
        qtbot.addWidget(btn)
        btn.setEnabled(True)

        bind_edit_permission(btn, "tabs.recipes.edit", auth_state=None)
        # Состояние не меняется — функция no-op без auth_state
        assert btn.isEnabled() is True

    def test_disables_when_permission_missing(self, qtbot):
        btn = QPushButton()
        qtbot.addWidget(btn)
        stub = _StubAuthState()  # пустой контекст

        bind_edit_permission(btn, "tabs.recipes.edit", stub)

        assert btn.isEnabled() is False
        assert btn.property("readOnly") is True

    def test_enables_when_permission_present(self, qtbot):
        btn = QPushButton()
        qtbot.addWidget(btn)
        stub = _StubAuthState(
            AccessContext(permissions=frozenset({"tabs.recipes.edit"}))
        )

        bind_edit_permission(btn, "tabs.recipes.edit", stub)

        assert btn.isEnabled() is True
        assert btn.property("readOnly") is False

    def test_reacts_to_access_context_changed(self, qtbot):
        btn = QPushButton()
        qtbot.addWidget(btn)
        stub = _StubAuthState()  # начинаем без permission
        bind_edit_permission(btn, "tabs.pipeline.edit", stub)

        assert btn.isEnabled() is False

        # Login: получаем permission
        stub.set_context(
            AccessContext(permissions=frozenset({"tabs.pipeline.edit"}))
        )
        assert btn.isEnabled() is True

        # Logout: permission уходит
        stub.set_context(AccessContext())
        assert btn.isEnabled() is False

    def test_wildcard_grants_access(self, qtbot):
        btn = QPushButton()
        qtbot.addWidget(btn)
        stub = _StubAuthState(
            AccessContext(permissions=frozenset({"*"}), role_name="dev")
        )

        bind_edit_permission(btn, "tabs.any.edit", stub)

        assert btn.isEnabled() is True


class TestGateEditWidgets:
    def test_batch_apply(self, qtbot):
        b1, b2 = QPushButton(), QPushButton()
        qtbot.addWidget(b1)
        qtbot.addWidget(b2)
        stub = _StubAuthState()

        gate_edit_widgets([b1, b2], "tabs.recipes.edit", stub)

        assert b1.isEnabled() is False
        assert b2.isEnabled() is False

        stub.set_context(
            AccessContext(permissions=frozenset({"tabs.recipes.edit"}))
        )
        assert b1.isEnabled() is True
        assert b2.isEnabled() is True


class TestInstallPermissionAwareEnable:
    def test_no_auth_state_noop(self, qtbot):
        from multiprocess_prototype.frontend.widgets.access import (
            install_permission_aware_enable,
        )

        btn = QPushButton()
        qtbot.addWidget(btn)
        btn.setEnabled(True)
        install_permission_aware_enable(btn, "tabs.recipes.edit", None)
        # setEnabled остался оригинальным, состояние не изменилось
        assert btn.isEnabled() is True

    def test_proxy_intercepts_setEnabled(self, qtbot):
        from multiprocess_prototype.frontend.widgets.access import (
            install_permission_aware_enable,
        )

        btn = QPushButton()
        qtbot.addWidget(btn)
        stub = _StubAuthState()  # без permission

        install_permission_aware_enable(btn, "tabs.recipes.edit", stub)

        # Без permission даже base_enabled=True не включит кнопку
        btn.setEnabled(True)
        assert btn.isEnabled() is False

        # После получения permission — таб-код вызывает setEnabled(True) — теперь работает
        stub.set_context(
            AccessContext(permissions=frozenset({"tabs.recipes.edit"}))
        )
        assert btn.isEnabled() is True

    def test_base_false_always_disabled(self, qtbot):
        from multiprocess_prototype.frontend.widgets.access import (
            install_permission_aware_enable,
        )

        btn = QPushButton()
        qtbot.addWidget(btn)
        stub = _StubAuthState(
            AccessContext(permissions=frozenset({"tabs.recipes.edit"}))
        )
        install_permission_aware_enable(btn, "tabs.recipes.edit", stub)
        # base=True + permission → enabled
        btn.setEnabled(True)
        assert btn.isEnabled() is True
        # selection drops → base=False → disabled
        btn.setEnabled(False)
        assert btn.isEnabled() is False

    def test_revoked_permission_disables(self, qtbot):
        from multiprocess_prototype.frontend.widgets.access import (
            install_permission_aware_enable,
        )

        btn = QPushButton()
        qtbot.addWidget(btn)
        stub = _StubAuthState(
            AccessContext(permissions=frozenset({"tabs.recipes.edit"}))
        )
        install_permission_aware_enable(btn, "tabs.recipes.edit", stub)
        btn.setEnabled(True)
        assert btn.isEnabled() is True
        # logout → пустой контекст → disabled даже при base=True
        stub.set_context(AccessContext())
        assert btn.isEnabled() is False
