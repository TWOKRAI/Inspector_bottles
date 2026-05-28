# -*- coding: utf-8 -*-
"""Вспомогательные фабрики для plugins-тестов (Task E.5).

make_plugins_services() навешивает raw-объекты (PluginRegistry, RegistersManager,
ServiceRegistry) на Fake-протоколы через bridge-атрибуты (_registry/_rm), т.к.
PluginCatalog/ServiceManager/RegistersBackend Protocol'ы не покрывают rich API
(plugin_class, register_classes, inputs/outputs, service entry status).

plugin_manager — runtime-объект вне AppServices, передаётся explicit-параметром.
"""

from __future__ import annotations

from typing import Any

from multiprocess_prototype.domain.app_services import AppServices
from multiprocess_prototype.domain.tests._fakes import (
    FakeAuthFacade,
    FakePluginCatalog,
    FakeRegistersBackend,
    FakeServiceManager,
)
from multiprocess_prototype.domain.tests.conftest import make_test_app_services


def make_plugins_services(
    *,
    registry: Any = None,
    registers_manager: Any = None,
    service_registry: Any = None,
    auth: FakeAuthFacade | None = None,
) -> AppServices:
    """Создать AppServices для plugins-тестов.

    Args:
        registry: raw PluginRegistry → services.plugins._registry bridge.
        registers_manager: raw RegistersManager → services.registers._rm bridge.
        service_registry: raw ServiceRegistry → services.services._registry bridge.
        auth: FakeAuthFacade (по умолчанию all_permissions=True).
    """
    plugins = FakePluginCatalog()
    if registry is not None:
        plugins._registry = registry  # type: ignore[attr-defined]

    registers = FakeRegistersBackend()
    if registers_manager is not None:
        registers._rm = registers_manager  # type: ignore[attr-defined]

    svc = FakeServiceManager()
    if service_registry is not None:
        svc._registry = service_registry  # type: ignore[attr-defined]

    return make_test_app_services(
        plugins=plugins,
        registers=registers,
        services=svc,
        auth=auth if auth is not None else FakeAuthFacade(all_permissions=True),
    )


class _StubPluginsCtx:
    """Минимальный AppContext-стуб для PluginsTab.create() (без _DeprecatedExtrasDict)."""

    def __init__(self, services: AppServices, *, plugin_manager: Any = None) -> None:
        self.app_services = services
        self._plugin_manager = plugin_manager

    def plugin_manager(self) -> Any:
        return self._plugin_manager


__all__ = ["make_plugins_services", "_StubPluginsCtx"]
