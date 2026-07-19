# -*- coding: utf-8 -*-
"""Тесты SectionSpec и SectionProtocol / SectionWithEvents — pure-Python (без Qt).

Цель: убедиться, что декларация секций для `BaseTreeNavTab` работает без
импорта PySide6 — это краеугольный камень шаблона tree-nav вкладки (ADR-126).
"""

from __future__ import annotations

import dataclasses
import importlib

import pytest


# ---------------------------------------------------------------------------
# 1. Pure-Python: модули импортируются без PySide6 в `sys.modules`
# ---------------------------------------------------------------------------


def test_section_spec_module_imports_without_qt() -> None:
    """`section_spec` не должен тянуть PySide6 при импорте."""
    # Импортируем заново в изолированном виде, чтобы проверить путь импорта.
    mod = importlib.import_module("multiprocess_framework.modules.frontend_module.widgets.tabs.section_spec")
    # Сам модуль не объявляет атрибутов из Qt
    assert not any(name.startswith("Q") and name[1:2].isupper() for name in dir(mod) if not name.startswith("_"))


def test_section_protocol_module_imports_without_qt() -> None:
    """`section_protocol` использует Qt только под TYPE_CHECKING."""
    mod = importlib.import_module("multiprocess_framework.modules.frontend_module.widgets.tabs.section_protocol")
    # QWidget / SignalInstance не попадают в публичный namespace модуля
    assert "QWidget" not in vars(mod)
    assert "SignalInstance" not in vars(mod)


def test_tabs_package_reexports_section_spec_and_protocol() -> None:
    """Фасад `widgets.tabs` экспортирует SectionSpec / SectionProtocol / SectionWithEvents."""
    pkg = importlib.import_module("multiprocess_framework.modules.frontend_module.widgets.tabs")
    assert "SectionSpec" in pkg.__all__
    assert "SectionProtocol" in pkg.__all__
    assert "SectionWithEvents" in pkg.__all__
    assert hasattr(pkg, "SectionSpec")
    assert hasattr(pkg, "SectionProtocol")
    assert hasattr(pkg, "SectionWithEvents")


# ---------------------------------------------------------------------------
# 2. SectionSpec — поля, дефолты, неизменяемость
# ---------------------------------------------------------------------------


from multiprocess_framework.modules.frontend_module.widgets.tabs import (  # noqa: E402
    SectionProtocol,
    SectionSpec,
    SectionWithEvents,
)


def _stub_factory(_ctx: object) -> object:
    """Минимальная фабрика — возвращает объект без полей SectionProtocol."""
    return object()


def test_section_spec_required_fields() -> None:
    spec = SectionSpec(key="system", title="Настройки системы", factory=_stub_factory)
    assert spec.key == "system"
    assert spec.title == "Настройки системы"
    assert spec.factory is _stub_factory
    assert spec.parent_key is None
    assert spec.lazy is False


def test_section_spec_optional_fields() -> None:
    spec = SectionSpec(
        key="users",
        title="Пользователи",
        factory=_stub_factory,
        parent_key="admin",
        lazy=True,
    )
    assert spec.parent_key == "admin"
    assert spec.lazy is True


def test_section_spec_is_frozen() -> None:
    spec = SectionSpec(key="a", title="A", factory=_stub_factory)
    with pytest.raises(dataclasses.FrozenInstanceError):
        spec.key = "b"  # type: ignore[misc]


def test_section_spec_equality_by_value() -> None:
    a = SectionSpec(key="k", title="T", factory=_stub_factory)
    b = SectionSpec(key="k", title="T", factory=_stub_factory)
    c = SectionSpec(key="k", title="T", factory=_stub_factory, lazy=True)
    assert a == b
    assert a != c


def test_section_spec_hierarchy_grouping() -> None:
    """SectionSpec поддерживает построение иерархии по `parent_key`."""
    specs = [
        SectionSpec("admin", "Администрация", _stub_factory),
        SectionSpec("users", "Пользователи", _stub_factory, parent_key="admin"),
        SectionSpec("roles", "Роли", _stub_factory, parent_key="admin"),
        SectionSpec("history", "История", _stub_factory),
    ]
    top_level = [s for s in specs if s.parent_key is None]
    admin_children = [s for s in specs if s.parent_key == "admin"]
    assert [s.key for s in top_level] == ["admin", "history"]
    assert [s.key for s in admin_children] == ["users", "roles"]


# ---------------------------------------------------------------------------
# 3. SectionProtocol / SectionWithEvents — runtime_checkable
# ---------------------------------------------------------------------------


class _MinimalSection:
    """Pure-Python заглушка, удовлетворяющая SectionProtocol без Qt."""

    @property
    def key(self) -> str:
        return "stub"

    @property
    def title(self) -> str:
        return "Stub"

    def widget(self):
        return self

    def action_buttons(self):
        return []

    def on_activated(self) -> None:
        return None

    def on_deactivated(self) -> None:
        return None


class _SectionMissingMethods:
    """Реализует только key/title — недостаточно для SectionProtocol."""

    @property
    def key(self) -> str:
        return "x"

    @property
    def title(self) -> str:
        return "X"


def test_minimal_section_is_section_protocol() -> None:
    """`@runtime_checkable` пропускает любой объект с нужными атрибутами."""
    assert isinstance(_MinimalSection(), SectionProtocol)


def test_incomplete_section_is_not_section_protocol() -> None:
    assert not isinstance(_SectionMissingMethods(), SectionProtocol)


class _SectionWithBusOnly:
    """Реализует `bus_change_callback`, но без сигналов dirty/saved."""

    section_dirty_changed = None
    section_data_saved = None

    def bus_change_callback(self):
        return lambda: None


def test_section_with_events_runtime_checkable() -> None:
    """`SectionWithEvents` — самостоятельный `@runtime_checkable` Protocol."""
    assert isinstance(_SectionWithBusOnly(), SectionWithEvents)


def test_section_without_events_is_not_section_with_events() -> None:
    """Секция без `bus_change_callback` / сигнальных полей не удовлетворяет mixin."""
    assert not isinstance(_SectionMissingMethods(), SectionWithEvents)


# ---------------------------------------------------------------------------
# 4. SectionSpec фабрика вызывается с контекстом и отдаёт совместимый объект
# ---------------------------------------------------------------------------


def test_section_spec_factory_invocation() -> None:
    """Фабрика вызывается с одним аргументом (контекстом таба)."""
    seen: list[object] = []

    def factory(ctx: object) -> _MinimalSection:
        seen.append(ctx)
        return _MinimalSection()

    spec = SectionSpec(key="stub", title="Stub", factory=factory)
    sentinel = object()
    section = spec.factory(sentinel)
    assert seen == [sentinel]
    assert isinstance(section, SectionProtocol)


# Тест совместимости с прикладными секциями SettingsTab (SystemSection,
# AppearanceSection, HistorySection) перенесён в frontend-constructor Ф1
# (T1.4) в тесты settings-вкладок прототипа
# (test_section_protocol_compat.py) — frontend_module/tests не должен
# зависеть от кода приложения (инверсия слоёв).
