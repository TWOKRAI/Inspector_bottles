# -*- coding: utf-8 -*-
"""Тесты G.6.6: cross-tab linking — RecipeActivated → подсветка сервисов рецепта.

Используют реальный EventBus (FakeEventBus.subscribe — no-op, не годится).

Refs: plans/2026-05-27_cross-tab-architecture/phase-g.md (Wave 7, G.6.6)
"""

from __future__ import annotations

from multiprocess_framework.modules.frontend_module.widgets.tabs.nav_tree_utils import (
    find_tree_item,
)
from multiprocess_prototype.adapters import ServiceManagerFromRegistry
from multiprocess_prototype.domain.event_bus import EventBus
from multiprocess_prototype.domain.events import RecipeActivated
from multiprocess_prototype.domain.tests._fakes import FakeAuthFacade, FakeRecipeStore
from multiprocess_prototype.domain.tests.conftest import make_test_app_services
from multiprocess_prototype.frontend.widgets.tabs.services.tab import ServicesTab

from ._helpers import _StubServiceEntry, _StubServiceRegistry


def _make_services(active_services, *, extra_recipes=None):
    """AppServices с реальным EventBus + сервисом svc_a + рецептом r1."""
    registry = _StubServiceRegistry([_StubServiceEntry("svc_a", "Service A")])
    manager = ServiceManagerFromRegistry(registry)  # type: ignore[arg-type]
    raw = {"r1": {"active_services": active_services, "blueprint": {"processes": [], "wires": []}}}
    if extra_recipes:
        raw.update(extra_recipes)
    recipes = FakeRecipeStore(raw=raw)
    return make_test_app_services(
        services=manager,
        recipes=recipes,
        events=EventBus(),
        auth=FakeAuthFacade(all_permissions=True),
    )


def _is_bold(tab: ServicesTab, key: str) -> bool:
    item = find_tree_item(tab._tree_nav.invisibleRootItem(), key)
    assert item is not None, f"tree-узел '{key}' не найден"
    return item.font(0).bold()


def test_recipe_activated_highlights_service(qtbot):
    """Активация рецепта с active_services=[svc_a] → узел svc_a жирный."""
    services = _make_services(["svc_a"])
    tab = ServicesTab(services)
    qtbot.addWidget(tab)

    services.events.publish(RecipeActivated(slug="r1"))

    assert _is_bold(tab, "svc_a") is True
    assert tab._highlighted_service_keys == ["svc_a"]


def test_highlight_clears_previous(qtbot):
    """Новая активация без active_services снимает прежнюю подсветку."""
    services = _make_services(
        ["svc_a"],
        extra_recipes={"r2": {"active_services": [], "blueprint": {"processes": [], "wires": []}}},
    )
    tab = ServicesTab(services)
    qtbot.addWidget(tab)

    services.events.publish(RecipeActivated(slug="r1"))
    assert _is_bold(tab, "svc_a") is True

    services.events.publish(RecipeActivated(slug="r2"))
    assert _is_bold(tab, "svc_a") is False
    assert tab._highlighted_service_keys == []


def test_unknown_service_graceful(qtbot):
    """active_services с неизвестным сервисом → нет падения, ничего не подсвечено."""
    services = _make_services(["ghost_service"])
    tab = ServicesTab(services)
    qtbot.addWidget(tab)

    services.events.publish(RecipeActivated(slug="r1"))  # не падает

    assert tab._highlighted_service_keys == []
    assert _is_bold(tab, "svc_a") is False


def test_no_active_services_noop(qtbot):
    """Рецепт без active_services → подсветка пуста."""
    services = _make_services([])
    tab = ServicesTab(services)
    qtbot.addWidget(tab)

    services.events.publish(RecipeActivated(slug="r1"))

    assert tab._highlighted_service_keys == []
