# -*- coding: utf-8 -*-
"""Вспомогательные фабрики для processes-тестов (Task E.2, F.9).

make_processes_services() — builder поверх make_test_app_services(),
строит AppServices с заданной topology (через FakeTopologyRepository).

make_processes_runtime() — builder RuntimeDeps для тестов create().
"""

from __future__ import annotations

from typing import Any

from multiprocess_prototype.domain.app_services import AppServices
from multiprocess_prototype.domain.entities import Topology
from multiprocess_prototype.domain.tests._fakes import (
    FakeAuthFacade,
    FakePluginCatalog,
)
from multiprocess_prototype.domain.tests.conftest import make_test_app_services
from multiprocess_prototype.domain.tests._fakes import FakeEventBus
from multiprocess_prototype.adapters.stores.topology_repository import (
    TopologyRepositoryStore,
)
from multiprocess_prototype.frontend.runtime_deps import RuntimeDeps


_DEFAULT_PROCESSES: list[dict[str, Any]] = [
    {"process_name": "camera_0", "plugins": [{"plugin_name": "capture", "category": "source"}]},
    {"process_name": "processor", "plugins": [{"plugin_name": "color_mask", "category": "processing"}]},
    {"process_name": "renderer", "plugins": [{"plugin_name": "render_overlay", "category": "rendering"}]},
]


def make_processes_services(
    *,
    topology_processes: list[dict[str, Any]] | None = None,
    plugins: FakePluginCatalog | None = None,
    auth: FakeAuthFacade | None = None,
    use_holder: bool = False,
) -> AppServices:
    """Создать AppServices для processes-тестов.

    Topology кладётся в TopologyRepository (domain Topology entity).

    Args:
        topology_processes: список dict процессов. По умолчанию — 3 процесса.
            Передай [] для пустой topology.
        plugins: FakePluginCatalog (по умолчанию — пустой каталог).
        auth: FakeAuthFacade (по умолчанию — all_permissions=True).
        use_holder: если True — использовать production TopologyRepositoryStore
            (проверяет совместимость store ↔ domain).
    """
    procs = topology_processes if topology_processes is not None else _DEFAULT_PROCESSES
    topo_dict: dict[str, Any] = {"processes": procs}

    if use_holder:
        topology_repo: Any = TopologyRepositoryStore(topo_dict, events=FakeEventBus())
    else:
        from multiprocess_prototype.domain.tests._fakes import FakeTopologyRepository

        topology_repo = FakeTopologyRepository(Topology.from_dict(topo_dict))

    return make_test_app_services(
        topology=topology_repo,
        plugins=plugins if plugins is not None else FakePluginCatalog(),
        auth=auth if auth is not None else FakeAuthFacade(all_permissions=True),
    )


def make_processes_runtime(
    *,
    command_sender: Any = None,
    topology_bridge: Any = None,
    bindings: Any = None,
) -> RuntimeDeps:
    """Создать RuntimeDeps для processes-тестов (Task F.9)."""
    return RuntimeDeps(
        command_sender=command_sender,
        topology_bridge=topology_bridge,
        bindings=bindings,
    )


__all__ = ["make_processes_services", "make_processes_runtime", "_DEFAULT_PROCESSES"]
