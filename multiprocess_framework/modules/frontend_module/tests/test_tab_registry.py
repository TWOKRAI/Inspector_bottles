# -*- coding: utf-8 -*-
"""Тесты generic-механизма вкладок (TabRegistry/TabSpec/LazyTab, NEW-D1).

Framework-уровень: тесты НЕ импортируют прикладной слой. Заглушки/фабрики/
источник прав — локальные stubs.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QLabel, QTabWidget, QWidget

from multiprocess_framework.modules.frontend_module.managers.access_context import (
    AccessContext,
)
from multiprocess_framework.modules.frontend_module.tabs import (
    LazyTab,
    TabRegistry,
    TabSpec,
)


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


class _StubAccessSource(QObject):
    """Источник прав: сигнал смены + текущий AccessContext."""

    access_context_changed = Signal(AccessContext)

    def __init__(self, ctx: AccessContext | None = None) -> None:
        super().__init__()
        self.access_context: AccessContext = ctx or AccessContext()

    def set_context(self, ctx: AccessContext) -> None:
        self.access_context = ctx
        self.access_context_changed.emit(ctx)


def _placeholder(spec: TabSpec) -> QWidget:
    """Заглушка: QLabel c objectName по id (для проверок в тестах)."""
    w = QLabel(spec.title)
    w.setObjectName(f"Placeholder_{spec.id}")
    return w


def _is_placeholder(widget: QWidget, tab_id: str) -> bool:
    return isinstance(widget, QLabel) and widget.objectName() == f"Placeholder_{tab_id}"


_SPECS = [
    TabSpec(id="alpha", title="Alpha", view_permission="tabs.alpha.view"),
    TabSpec(id="beta", title="Beta", view_permission="tabs.beta.view"),
    TabSpec(id="gamma", title="Gamma", view_permission="tabs.gamma.view"),
]


def _visible_ids(tab_widget: QTabWidget, specs=_SPECS) -> list[str]:
    bar = tab_widget.tabBar()
    return [s.id for i, s in enumerate(specs) if bar.isTabVisible(i)]


# ---------------------------------------------------------------------------
# create_tabs
# ---------------------------------------------------------------------------


class TestCreateTabs:
    def test_creates_all_in_order(self, qtbot):
        tw = QTabWidget()
        qtbot.addWidget(tw)
        TabRegistry(_SPECS, placeholder_factory=_placeholder).create_tabs(tw)
        assert tw.count() == 3
        assert [tw.tabText(i) for i in range(3)] == ["Alpha", "Beta", "Gamma"]

    def test_no_factory_uses_placeholder(self, qtbot):
        tw = QTabWidget()
        qtbot.addWidget(tw)
        TabRegistry(_SPECS, placeholder_factory=_placeholder).create_tabs(tw)
        for i, spec in enumerate(_SPECS):
            assert _is_placeholder(tw.widget(i), spec.id)

    def test_factory_wrapped_in_lazy(self, qtbot):
        tw = QTabWidget()
        qtbot.addWidget(tw)
        specs = [TabSpec(id="alpha", title="Alpha", factory=lambda: QWidget())]
        TabRegistry(specs, placeholder_factory=_placeholder).create_tabs(tw)
        assert isinstance(tw.widget(0), LazyTab)

    def test_factory_context_forwarded(self, qtbot):
        tw = QTabWidget()
        qtbot.addWidget(tw)
        # inner не трекаем через qtbot: при показе он репарентится под tw и будет
        # закрыт вместе с ним — двойной close дал бы «C++ object already deleted».
        inner = QWidget()
        fac = MagicMock(return_value=inner)
        specs = [TabSpec(id="alpha", title="Alpha", factory=fac)]
        reg = TabRegistry(specs, factory_context=("svc", "rt"), placeholder_factory=_placeholder)
        reg.create_tabs(tw)
        # Ленивая: до показа не вызвана
        fac.assert_not_called()
        assert isinstance(tw.widget(0), LazyTab)
        # Показ активной страницы (index 0) доставляет showEvent → фабрика.
        tw.show()
        qtbot.waitExposed(tw)
        fac.assert_called_once_with("svc", "rt")

    def test_non_lazy_builds_immediately(self, qtbot):
        tw = QTabWidget()
        qtbot.addWidget(tw)
        # inner уходит под tw при немедленной сборке — qtbot им не владеет.
        inner = QWidget()
        fac = MagicMock(return_value=inner)
        specs = [TabSpec(id="alpha", title="Alpha", factory=fac)]
        TabRegistry(specs, lazy=False, placeholder_factory=_placeholder).create_tabs(tw)
        fac.assert_called_once()


# ---------------------------------------------------------------------------
# create_tab (единичная фабрикация)
# ---------------------------------------------------------------------------


class TestCreateTab:
    def test_unknown_id_returns_none(self, qtbot):
        reg = TabRegistry(_SPECS, placeholder_factory=_placeholder)
        assert reg.create_tab("nope") is None

    def test_known_no_factory_returns_placeholder(self, qtbot):
        reg = TabRegistry(_SPECS, placeholder_factory=_placeholder)
        w = reg.create_tab("alpha")
        qtbot.addWidget(w)
        assert _is_placeholder(w, "alpha")

    def test_factory_called_directly(self, qtbot):
        inner = QWidget()
        qtbot.addWidget(inner)
        fac = MagicMock(return_value=inner)
        specs = [TabSpec(id="alpha", title="Alpha", factory=fac)]
        reg = TabRegistry(specs, factory_context=("svc", "rt"), placeholder_factory=_placeholder)
        result = reg.create_tab("alpha")
        fac.assert_called_once_with("svc", "rt")
        assert result is inner

    def test_factory_returns_none_falls_back(self, qtbot):
        fac = MagicMock(return_value=None)
        specs = [TabSpec(id="alpha", title="Alpha", factory=fac)]
        reg = TabRegistry(specs, placeholder_factory=_placeholder)
        w = reg.create_tab("alpha")
        qtbot.addWidget(w)
        assert _is_placeholder(w, "alpha")

    def test_factory_raises_falls_back(self, qtbot):
        def bad(*_a):
            raise ValueError("boom")

        specs = [TabSpec(id="alpha", title="Alpha", factory=bad)]
        reg = TabRegistry(specs, placeholder_factory=_placeholder)
        w = reg.create_tab("alpha")
        qtbot.addWidget(w)
        assert _is_placeholder(w, "alpha")


# ---------------------------------------------------------------------------
# LazyTab
# ---------------------------------------------------------------------------


class TestLazyTab:
    def test_not_called_before_show(self, qtbot):
        fac = MagicMock(return_value=QWidget())
        lazy = LazyTab(fac)
        qtbot.addWidget(lazy)
        fac.assert_not_called()

    def test_called_on_first_show_once(self, qtbot):
        inner = QWidget()
        fac = MagicMock(return_value=inner)
        lazy = LazyTab(fac)
        qtbot.addWidget(lazy)
        lazy.show()
        lazy.hide()
        lazy.show()
        fac.assert_called_once()

    def test_factory_error_swallowed(self, qtbot):
        def bad():
            raise RuntimeError("x")

        lazy = LazyTab(bad)
        qtbot.addWidget(lazy)
        lazy.show()  # не должно бросить наружу
        assert lazy.isVisible()


# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------


class TestPermissions:
    def test_no_source_shows_all(self, qtbot):
        tw = QTabWidget()
        qtbot.addWidget(tw)
        TabRegistry(_SPECS, access_source=None, placeholder_factory=_placeholder).create_tabs(tw)
        assert _visible_ids(tw) == ["alpha", "beta", "gamma"]

    def test_empty_context_hides_all(self, qtbot):
        tw = QTabWidget()
        qtbot.addWidget(tw)
        src = _StubAccessSource()
        TabRegistry(_SPECS, access_source=src, placeholder_factory=_placeholder).create_tabs(tw)
        assert _visible_ids(tw) == []

    def test_partial_permissions(self, qtbot):
        tw = QTabWidget()
        qtbot.addWidget(tw)
        ctx = AccessContext(permissions=frozenset({"tabs.beta.view"}))
        src = _StubAccessSource(ctx)
        TabRegistry(_SPECS, access_source=src, placeholder_factory=_placeholder).create_tabs(tw)
        assert _visible_ids(tw) == ["beta"]

    def test_wildcard_shows_all(self, qtbot):
        tw = QTabWidget()
        qtbot.addWidget(tw)
        ctx = AccessContext(permissions=frozenset({"*"}))
        src = _StubAccessSource(ctx)
        TabRegistry(_SPECS, access_source=src, placeholder_factory=_placeholder).create_tabs(tw)
        assert _visible_ids(tw) == ["alpha", "beta", "gamma"]

    def test_none_permission_always_visible(self, qtbot):
        tw = QTabWidget()
        qtbot.addWidget(tw)
        specs = [
            TabSpec(id="alpha", title="Alpha", view_permission=None),
            TabSpec(id="beta", title="Beta", view_permission="tabs.beta.view"),
        ]
        src = _StubAccessSource()  # пустой контекст
        TabRegistry(specs, access_source=src, placeholder_factory=_placeholder).create_tabs(tw)
        assert _visible_ids(tw, specs) == ["alpha"]

    def test_context_change_reapplies(self, qtbot):
        tw = QTabWidget()
        qtbot.addWidget(tw)
        src = _StubAccessSource()
        # reg держим в переменной: он не QObject, и без ссылки GC соберёт его,
        # оборвав connect(access_context_changed → reapply). В проде реестр живёт
        # столько же, сколько окно (хранится в composition root).
        reg = TabRegistry(_SPECS, access_source=src, placeholder_factory=_placeholder)
        reg.create_tabs(tw)
        assert _visible_ids(tw) == []
        src.set_context(AccessContext(permissions=frozenset({"tabs.alpha.view", "tabs.gamma.view"})))
        assert _visible_ids(tw) == ["alpha", "gamma"]
        src.set_context(AccessContext())
        assert _visible_ids(tw) == []
