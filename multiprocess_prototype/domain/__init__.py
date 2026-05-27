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
)
from .errors import DomainError, EntityValidationError
from .events import (
    DisplayBound,
    DisplayUnbound,
    PluginConfigChanged,
    PluginInserted,
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
# Опциональная регистрация в SchemaRegistry
# ------------------------------------------------------------------
# SchemaRegistry.register(name, class) принимает два аргумента (str + Type[BaseModel]).
# Domain entities — frozen Pydantic модели, что совместимо с BaseModel.
# Регистрируем в глобальный default registry для discovery в Phase E (Inspector).
# Если импорт SchemaRegistry недоступен — пропускаем с предупреждением в log.
# TODO(B.1): Если глобальный default registry конфликтует с изолированными
# тестовыми registry — вынести регистрацию в фабрику AppServices (Phase D).
try:
    from multiprocess_framework.modules.data_schema_module import (
        get_default_registry,
    )

    _registry = get_default_registry()
    _domain_classes = [
        ("PluginInstance", PluginInstance),
        ("Wire", Wire),
        ("DisplayInstance", DisplayInstance),
        ("Process", Process),
        ("RecipeMeta", RecipeMeta),
        ("Recipe", Recipe),
        ("Topology", Topology),
        ("Project", Project),
    ]
    for _name, _cls in _domain_classes:
        try:
            _registry.register(_name, _cls)
        except Exception as _reg_exc:  # nosec B110 — дублирующая регистрация не критична
            import logging as _log

            _log.getLogger(__name__).debug("domain: register %s skipped: %s", _name, _reg_exc)
except Exception as _exc:
    import logging as _logging

    _logging.getLogger(__name__).debug("domain: SchemaRegistry registration skipped: %s", _exc)


__all__ = [
    # Entities
    "PluginInstance",
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
    # События (Task B.2)
    "ProjectEvent",
    "ProcessAdded",
    "ProcessRemoved",
    "ProcessRenamed",
    "PluginInserted",
    "PluginRemoved",
    "PluginConfigChanged",
    "WireConnected",
    "WireDisconnected",
    "DisplayBound",
    "DisplayUnbound",
    "TargetProcessAssigned",
    "RecipeActivated",
    "RecipeDeactivated",
    "TopologyReplaced",
]
