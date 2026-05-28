# -*- coding: utf-8 -*-
"""Вспомогательные фабрики для plugins-тестов (Task E.5, F.9, G.2).

make_plugins_services() навешивает raw-объекты (PluginRegistry, ServiceRegistry)
на Fake-протоколы через bridge-атрибуты (_registry), т.к. PluginCatalog/ServiceManager
Protocol'ы не покрывают rich API (plugin_class, register_classes, service entry status).

plugin_manager и registers_manager — runtime-объекты вне AppServices, передаются
через RuntimeDeps (Q-F1=B, G.2). registers_manager даёт framework FieldInfo для RegisterView.
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
from multiprocess_prototype.frontend.runtime_deps import RuntimeDeps


def make_plugins_services(
    *,
    registry: Any = None,
    service_registry: Any = None,
    auth: FakeAuthFacade | None = None,
) -> AppServices:
    """Создать AppServices для plugins-тестов.

    Args:
        registry: raw PluginRegistry → services.plugins._registry bridge.
        service_registry: raw ServiceRegistry → services.services._registry bridge.
        auth: FakeAuthFacade (по умолчанию all_permissions=True).

    NB (G.2): registers_manager больше НЕ навешивается на services через _rm bridge —
    он runtime-объект и передаётся через make_plugins_runtime() / RuntimeDeps.
    """
    plugins = FakePluginCatalog()
    if registry is not None:
        plugins._registry = registry  # type: ignore[attr-defined]

    svc = FakeServiceManager()
    if service_registry is not None:
        svc._registry = service_registry  # type: ignore[attr-defined]

    return make_test_app_services(
        plugins=plugins,
        registers=FakeRegistersBackend(),
        services=svc,
        auth=auth if auth is not None else FakeAuthFacade(all_permissions=True),
    )


def make_plugins_runtime(
    *,
    plugin_manager: Any = None,
    registers_manager: Any = None,
) -> RuntimeDeps:
    """Создать RuntimeDeps для plugins-тестов (Task F.9, G.2).

    registers_manager — live RegistersManager (FieldInfo) для RegisterView плагин-секций.
    """
    return RuntimeDeps(plugin_manager=plugin_manager, registers_manager=registers_manager)


__all__ = ["make_plugins_services", "make_plugins_runtime"]
