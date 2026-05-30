# -*- coding: utf-8 -*-
"""
multiprocess_prototype.domain — изолированный типизированный domain-слой.

Публичный API: 7 frozen-entities на базе SchemaBase + исключения.

Использование:
    from multiprocess_prototype.domain import (
        PluginInstance, Wire, DisplayInstance,
        Process, RecipeMeta, Recipe, Topology, Project,
        DomainError, EntityValidationError,
    )

Границы импортов (enforced):
    - Разрешено: multiprocess_framework.modules.data_schema_module (SchemaBase, FieldMeta)
    - Разрешено: стандартная библиотека Python + Pydantic
    - ЗАПРЕЩЕНО: PySide6, PyQt6, PyQt5
    - ЗАПРЕЩЕНО: multiprocess_prototype.frontend
    - ЗАПРЕЩЕНО: multiprocess_prototype.backend
    - ЗАПРЕЩЕНО: multiprocess_framework.modules.frontend_module

Phase D подключит domain к runtime через AppServices DI-контейнер.
"""

from __future__ import annotations

from .entities import (
    DisplayInstance,
    PluginInstance,
    Process,
    Project,
    Recipe,
    RecipeMeta,
    Topology,
    Wire,
    WorkerSpec,
)
from .entities.project import ApplyContext
from .errors import DomainError, EntityValidationError
from .event_bus import EventBus
from .app_services import AppServices
from .protocols import (
    AuthFacade,
    CommandDispatcher,
    ConfigStore,
    DisplayCatalog,
    DisplaySpec,
    EventBusProtocol,
    FieldSpec,
    PluginCatalog,
    PluginSpec,
    PortSpec,
    RecipeStore,
    RegistersBackend,
    ServiceCatalog,
    ServiceLifecycle,
    ServiceManager,
    ServiceSpec,
    Subscription,
    TopologyRepository,
)
from .commands import (
    ActivateRecipe,
    AddProcess,
    AssignTargetProcess,
    BindDisplay,
    ConnectWire,
    DeactivateRecipe,
    DisconnectWire,
    InsertPlugin,
    MovePlugin,
    ProjectCommand,
    RemovePlugin,
    RemoveProcess,
    RenameProcess,
    ReplaceTopology,
    SetPluginConfig,
    UnbindDisplay,
)
from .events import (
    DisplayBound,
    DisplayUnbound,
    PluginConfigChanged,
    PluginInserted,
    PluginMoved,
    PluginRemoved,
    ProcessAdded,
    ProcessRemoved,
    ProcessRenamed,
    ProjectEvent,
    RecipeActivated,
    RecipeDeactivated,
    TargetProcessAssigned,
    TopologyReplaced,
    WireConnected,
    WireDisconnected,
)

# ------------------------------------------------------------------
# Явная регистрация в SchemaRegistry (lazy — вызывается явно)
# ------------------------------------------------------------------
# Импорт пакета НЕ регистрирует ничего в SchemaRegistry (Task C.0).
# Вызовите register_domain_schemas() явно (например, в фабрике AppServices).
# При registry=None использует глобальный default registry.
#
# Решение Q3 (Phase C decisions): lazy registration вместо import-time side-effect,
# чтобы избежать name collision с framework-уровневыми регистрациями.


def register_domain_schemas(registry: object = None) -> None:  # type: ignore[assignment]
    """Зарегистрировать все 8 domain-entity в SchemaRegistry (7 + RecipeMeta).

    Args:
        registry: Экземпляр SchemaRegistry. При None — использует глобальный
                  default registry (get_default_registry()).

    Вызывается явно (например, в фабрике AppServices или в тестах).
    Импорт пакета больше не вызывает эту функцию автоматически.
    """
    try:
        from multiprocess_framework.modules.data_schema_module import (
            get_default_registry,
        )

        target = registry if registry is not None else get_default_registry()
        _domain_classes = [
            ("PluginInstance", PluginInstance),
            ("WorkerSpec", WorkerSpec),
            ("Wire", Wire),
            ("DisplayInstance", DisplayInstance),
            ("Process", Process),
            ("RecipeMeta", RecipeMeta),
            ("Recipe", Recipe),
            ("Topology", Topology),
            ("Project", Project),
        ]
        import logging as _log

        _logger = _log.getLogger(__name__)
        for _name, _cls in _domain_classes:
            try:
                target.register(_name, _cls)  # type: ignore[union-attr]
            except Exception as _reg_exc:  # nosec B110 — дублирующая регистрация не критична
                _logger.debug("domain: register %s skipped: %s", _name, _reg_exc)
    except Exception as _exc:
        import logging as _logging

        _logging.getLogger(__name__).debug("domain: SchemaRegistry registration skipped: %s", _exc)


__all__ = [
    # Регистрация в SchemaRegistry (Task C.0, lazy)
    "register_domain_schemas",
    # ApplyContext (Task B.4)
    "ApplyContext",
    # EventBus + AppServices (Task B.6)
    "EventBus",
    "AppServices",
    # Entities
    "PluginInstance",
    "WorkerSpec",
    "Wire",
    "DisplayInstance",
    "Process",
    "RecipeMeta",
    "Recipe",
    "Topology",
    "Project",
    # Исключения
    "DomainError",
    "EntityValidationError",
    # Protocols (Task B.5 + D.2b)
    "PluginCatalog",
    "ServiceManager",
    "ServiceCatalog",
    "ServiceLifecycle",
    "DisplayCatalog",
    "RecipeStore",
    "RegistersBackend",
    "TopologyRepository",
    "CommandDispatcher",
    "EventBusProtocol",
    "AuthFacade",
    "ConfigStore",
    # Sidecar-dataclasses (Task B.5)
    "PluginSpec",
    "PortSpec",
    "ServiceSpec",
    "DisplaySpec",
    "FieldSpec",
    "Subscription",
    # События (Task B.2)
    "ProjectEvent",
    "ProcessAdded",
    "ProcessRemoved",
    "ProcessRenamed",
    "PluginInserted",
    "PluginRemoved",
    "PluginConfigChanged",
    "PluginMoved",
    "WireConnected",
    "WireDisconnected",
    "DisplayBound",
    "DisplayUnbound",
    "TargetProcessAssigned",
    "RecipeActivated",
    "RecipeDeactivated",
    "TopologyReplaced",
    # Команды (Task B.3)
    "ProjectCommand",
    "AddProcess",
    "RemoveProcess",
    "RenameProcess",
    "InsertPlugin",
    "RemovePlugin",
    "SetPluginConfig",
    "MovePlugin",
    "ConnectWire",
    "DisconnectWire",
    "BindDisplay",
    "UnbindDisplay",
    "AssignTargetProcess",
    "ActivateRecipe",
    "DeactivateRecipe",
    "ReplaceTopology",
]
