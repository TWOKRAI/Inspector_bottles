# -*- coding: utf-8 -*-
"""Вспомогательные фабрики для displays-тестов (Task E.6 + F.3 + F.9).

make_displays_services() создаёт AppServices с FakeDisplayCatalog (populated).
Phase F: больше нет bridge services.displays._registry — FakeDisplayCatalog
сам является writable store (register/unregister/has/persist).

router_manager — runtime-объект вне AppServices, передаётся explicit-параметром
в DisplaysTab (паттерн E.2/E.5), здесь не моделируется.

Refs: plans/2026-05-27_cross-tab-architecture/phase-f-legacy-removal.md (Task F.3, F.9)
"""

from __future__ import annotations

from multiprocess_prototype.domain.app_services import AppServices
from multiprocess_prototype.domain.protocols.display_catalog import DisplaySpec
from multiprocess_prototype.domain.tests._fakes import FakeAuthFacade, FakeDisplayCatalog
from multiprocess_prototype.domain.tests.conftest import make_test_app_services
from multiprocess_prototype.frontend.runtime_deps import RuntimeDeps


def make_displays_services(
    *,
    specs: dict[str, DisplaySpec] | None = None,
    auth: FakeAuthFacade | None = None,
) -> AppServices:
    """Создать AppServices для displays-тестов.

    Args:
        specs: начальный набор дисплеев (dict id->DisplaySpec).
            По умолчанию — пустой store.
        auth: FakeAuthFacade (по умолчанию all_permissions=True).
    """
    displays = FakeDisplayCatalog(specs=specs)

    return make_test_app_services(
        displays=displays,
        auth=auth if auth is not None else FakeAuthFacade(all_permissions=True),
    )


def make_displays_runtime() -> RuntimeDeps:
    """Создать RuntimeDeps для displays-тестов (Task F.9).

    DisplaysTab не использует runtime-зависимостей.
    """
    return RuntimeDeps()


__all__ = ["make_displays_services", "make_displays_runtime"]
