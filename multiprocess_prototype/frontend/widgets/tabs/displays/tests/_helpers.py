# -*- coding: utf-8 -*-
"""Вспомогательные фабрики для displays-тестов (Task E.6).

make_displays_services() навешивает реальный DisplayRegistry на FakeDisplayCatalog
через bridge-атрибут _registry — DisplayCatalog Protocol покрывает только read-only
list_displays/resolve (DisplaySpec), а presenter'у нужен полный CRUD + DisplayEntry
(register/unregister/persist/__contains__). См. tab.py TODO Phase F.

router_manager — runtime-объект вне AppServices, передаётся explicit-параметром
в DisplaysTab (паттерн E.2/E.5), здесь не моделируется.

Refs: plans/2026-05-27_cross-tab-architecture/phase-e-per-tab-migration.md (Task E.6)
"""

from __future__ import annotations

from multiprocess_framework.modules.display_module import DisplayRegistry
from multiprocess_prototype.domain.app_services import AppServices
from multiprocess_prototype.domain.tests._fakes import FakeAuthFacade, FakeDisplayCatalog
from multiprocess_prototype.domain.tests.conftest import make_test_app_services


def make_displays_services(
    *,
    registry: DisplayRegistry | None = None,
    auth: FakeAuthFacade | None = None,
) -> AppServices:
    """Создать AppServices для displays-тестов.

    Args:
        registry: реальный DisplayRegistry → services.displays._registry bridge.
            По умолчанию — singleton DisplayRegistry() (как в production preload).
        auth: FakeAuthFacade (по умолчанию all_permissions=True).
    """
    displays = FakeDisplayCatalog()
    displays._registry = registry if registry is not None else DisplayRegistry()  # type: ignore[attr-defined]

    return make_test_app_services(
        displays=displays,
        auth=auth if auth is not None else FakeAuthFacade(all_permissions=True),
    )


class _StubDisplaysCtx:
    """Минимальный AppContext-стуб для DisplaysTab.create() (без _DeprecatedExtrasDict)."""

    def __init__(self, services: AppServices) -> None:
        self.app_services = services


__all__ = ["make_displays_services", "_StubDisplaysCtx"]
