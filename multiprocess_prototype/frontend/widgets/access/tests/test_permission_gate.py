"""Тесты bind_edit_permission — gating виджетов по permission через AuthFacade."""

from __future__ import annotations

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
    """Stub-реализация AuthFacade с Qt-сигналом для реактивных тестов.

    Совместима с AuthFacade duck-type (has_permission + on_access_changed).
    Qt-сигнал access_context_changed используется adapter'ом через on_access_changed.
    """

    access_context_changed = Signal(AccessContext)

    def __init__(self, ctx: AccessContext | None = None) -> None:
        super().__init__()
        self.access_context: AccessContext = ctx or AccessContext()

    def set_context(self, ctx: AccessContext) -> None:
        self.access_context = ctx
        self.access_context_changed.emit(ctx)

    # --- AuthFacade Protocol методы ---

    @property
    def access_level(self) -> int:
        return self.access_context.level

    def is_authenticated(self) -> bool:
        return self.access_context.level > 0

    def has_permission(self, key: str) -> bool:
        return self.access_context.has_permission(key)

    def on_access_changed(self, callback) -> None:
        """Мостит Qt-сигнал → callback (0 аргументов)."""
        self.access_context_changed.connect(lambda *_: callback())


class TestBindEditPermission:
    def test_no_auth_is_noop(self, qtbot):
        btn = QPushButton()
        qtbot.addWidget(btn)
        btn.setEnabled(True)

        bind_edit_permission(btn, "tabs.recipes.edit", auth=None)
        # Состояние не меняется — функция no-op без auth
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
        stub = _StubAuthState(AccessContext(permissions=frozenset({"tabs.recipes.edit"})))

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
        stub.set_context(AccessContext(permissions=frozenset({"tabs.pipeline.edit"})))
        assert btn.isEnabled() is True

        # Logout: permission уходит
        stub.set_context(AccessContext())
        assert btn.isEnabled() is False

    def test_wildcard_grants_access(self, qtbot):
        btn = QPushButton()
        qtbot.addWidget(btn)
        stub = _StubAuthState(AccessContext(permissions=frozenset({"*"}), role_name="dev"))

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

        stub.set_context(AccessContext(permissions=frozenset({"tabs.recipes.edit"})))
        assert b1.isEnabled() is True
        assert b2.isEnabled() is True


class TestPropagateAccessContextToTree:
    """propagate_access_context_to_tree применяет AccessContext рекурсивно к виджетам с _trait или presenter."""

    def _make_tree(self, qtbot):
        """Создать root QWidget с двумя children: один с _trait, один с _presenter."""
        from PySide6.QtWidgets import QWidget
        from multiprocess_framework.modules.frontend_module.components.base.traits.access_trait import (
            AccessTrait,
        )

        root = QWidget()
        qtbot.addWidget(root)

        # Child 1: с _trait + _apply_access
        child1 = QWidget(root)
        child1._trait = AccessTrait(
            legacy_required_level=0,
            required_view_permission="tabs.x.view",
            required_edit_permission="tabs.x.edit",
        )
        applied_flag = {"count": 0}

        def _apply_access():
            applied_flag["count"] += 1
            child1.setEnabled(child1._trait.can_modify())

        child1._apply_access = _apply_access

        # Child 2: с _presenter имеющим set_access_context
        child2 = QWidget(root)
        presenter_calls = []

        class _StubPresenter:
            def set_access_context(self, ctx):
                presenter_calls.append(ctx)

        child2._presenter = _StubPresenter()

        return root, child1, child2, applied_flag, presenter_calls

    def test_no_auth_state_noop(self, qtbot):
        from multiprocess_prototype.frontend.widgets.access import (
            propagate_access_context_to_tree,
        )

        root, child1, _, applied_flag, _ = self._make_tree(qtbot)
        propagate_access_context_to_tree(root, None)
        assert applied_flag["count"] == 0

    def test_initial_apply_runs(self, qtbot):
        from multiprocess_prototype.frontend.widgets.access import (
            propagate_access_context_to_tree,
        )

        root, child1, child2, applied_flag, presenter_calls = self._make_tree(qtbot)
        stub = _StubAuthState(AccessContext(permissions=frozenset({"tabs.x.view", "tabs.x.edit"})))
        propagate_access_context_to_tree(root, stub)

        # child1._trait получил ctx через update + _apply_access вызван
        assert applied_flag["count"] >= 1
        assert child1._trait.can_modify() is True
        # child2 presenter получил ctx
        assert len(presenter_calls) == 1
        assert presenter_calls[0].has_permission("tabs.x.edit") is True

    def test_reactive_on_change(self, qtbot):
        from multiprocess_prototype.frontend.widgets.access import (
            propagate_access_context_to_tree,
        )

        root, child1, _, applied_flag, presenter_calls = self._make_tree(qtbot)
        stub = _StubAuthState()  # пустой
        propagate_access_context_to_tree(root, stub)
        initial_apply_count = applied_flag["count"]

        # Login → re-apply
        stub.set_context(AccessContext(permissions=frozenset({"tabs.x.view", "tabs.x.edit"})))
        assert applied_flag["count"] > initial_apply_count
        assert child1._trait.can_modify() is True
        assert len(presenter_calls) >= 2  # initial + login


class TestGateRegisterView:
    """gate_register_view применяет permission ко всем editor.widget внутри RegisterView."""

    def _make_view(self, qtbot, editors_count: int = 3):
        """Минимальный stub RegisterView с editors() -> dict."""
        from dataclasses import dataclass

        @dataclass
        class _Editor:
            widget: QPushButton

        from PySide6.QtWidgets import QWidget

        class _View(QWidget):
            def __init__(self) -> None:
                super().__init__()
                self._editors = {f"e{i}": _Editor(widget=QPushButton()) for i in range(editors_count)}

            def editors(self):
                return self._editors

        view = _View()
        qtbot.addWidget(view)
        for ed in view._editors.values():
            qtbot.addWidget(ed.widget)
        return view

    def test_no_auth_state_noop(self, qtbot):
        from multiprocess_prototype.frontend.widgets.access import gate_register_view

        view = self._make_view(qtbot)
        for ed in view.editors().values():
            ed.widget.setEnabled(True)
        gate_register_view(view, "tabs.plugins.edit", None)
        # Состояние сохранено — функция no-op
        for ed in view.editors().values():
            assert ed.widget.isEnabled() is True

    def test_disables_widgets_without_permission(self, qtbot):
        from multiprocess_prototype.frontend.widgets.access import gate_register_view

        view = self._make_view(qtbot)
        stub = _StubAuthState()  # без permission
        gate_register_view(view, "tabs.plugins.edit", stub)

        for ed in view.editors().values():
            assert ed.widget.isEnabled() is False
            assert ed.widget.property("readOnly") is True

    def test_enables_with_edit_permission(self, qtbot):
        from multiprocess_prototype.frontend.widgets.access import gate_register_view

        view = self._make_view(qtbot)
        stub = _StubAuthState(AccessContext(permissions=frozenset({"tabs.plugins.edit"})))
        gate_register_view(view, "tabs.plugins.edit", stub)

        for ed in view.editors().values():
            assert ed.widget.isEnabled() is True

    def test_view_permission_hides_whole_view(self, qtbot):
        from multiprocess_prototype.frontend.widgets.access import gate_register_view

        view = self._make_view(qtbot)
        view.show()
        stub = _StubAuthState(AccessContext(permissions=frozenset({"tabs.plugins.view"})))
        gate_register_view(
            view,
            edit_permission="tabs.plugins.edit",
            auth_state=stub,
            view_permission="tabs.plugins.view",
        )
        assert view.isVisible() is True

        # Logout → view_permission уходит → setVisible(False)
        stub.set_context(AccessContext())
        assert view.isVisible() is False

    def test_reactive_on_login(self, qtbot):
        from multiprocess_prototype.frontend.widgets.access import gate_register_view

        view = self._make_view(qtbot)
        stub = _StubAuthState()
        gate_register_view(view, "tabs.plugins.edit", stub)

        # Login → permission получен
        stub.set_context(AccessContext(permissions=frozenset({"tabs.plugins.edit"})))
        for ed in view.editors().values():
            assert ed.widget.isEnabled() is True

        # Logout
        stub.set_context(AccessContext())
        for ed in view.editors().values():
            assert ed.widget.isEnabled() is False


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
        stub.set_context(AccessContext(permissions=frozenset({"tabs.recipes.edit"})))
        assert btn.isEnabled() is True

    def test_base_false_always_disabled(self, qtbot):
        from multiprocess_prototype.frontend.widgets.access import (
            install_permission_aware_enable,
        )

        btn = QPushButton()
        qtbot.addWidget(btn)
        stub = _StubAuthState(AccessContext(permissions=frozenset({"tabs.recipes.edit"})))
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
        stub = _StubAuthState(AccessContext(permissions=frozenset({"tabs.recipes.edit"})))
        install_permission_aware_enable(btn, "tabs.recipes.edit", stub)
        btn.setEnabled(True)
        assert btn.isEnabled() is True
        # logout → пустой контекст → disabled даже при base=True
        stub.set_context(AccessContext())
        assert btn.isEnabled() is False
