# -*- coding: utf-8 -*-
"""
multiprocess_prototype.domain.protocols — Protocols для внешних зависимостей domain.

Пакет содержит 10 Protocol-файлов и sidecar-dataclasses. Ни один Protocol не имеет
default-реализации — только сигнатуры. Реализации (адаптеры) создаются в Phase C/D.

Экспортируемые Protocols:
  PluginCatalog     — read-only реестр плагинов
  ServiceManager    — управление сервисами (read + lifecycle)
  ServiceCatalog    — backward-compatible alias для ServiceManager
  DisplayCatalog    — read-only реестр дисплеев
  RecipeStore       — CRUD-доступ к рецептам
  RegistersBackend  — чтение/запись регистров Inspector
  TopologyRepository — persistence топологии (load/save)
  CommandDispatcher — диспетчеризация команд
  EventBusProtocol  — typed pub/sub шина событий
  AuthFacade        — read-only auth-состояние
  ConfigStore       — конфиг-хранилище с реактивным API (Task D.2b)

Sidecar-dataclasses (frozen, slots):
  PluginSpec, PortSpec   — из PluginCatalog
  ServiceSpec            — из ServiceManager
  ServiceLifecycle       — из ServiceManager (реэкспорт из framework)
  DisplaySpec            — из DisplayCatalog
  FieldSpec              — из RegistersBackend
  Subscription           — управление подпиской EventBus / ConfigStore
"""

from __future__ import annotations

from .auth_facade import AuthFacade
from .command_dispatcher import CommandDispatcher, HistoryEntry
from .config_store import ConfigStore
from .display_catalog import (
    DisplayCatalog,
    DisplaySpec,
    definition_to_spec,
    spec_to_definition_dict,
)
from .event_bus import EventBusProtocol, Subscription
from .plugin_catalog import PluginCatalog, PluginSpec, PortSpec
from .recipe_store import RecipeStore
from .registers_backend import FieldSpec, RegistersBackend
from .service_catalog import ServiceCatalog, ServiceLifecycle, ServiceManager, ServiceSpec
from .topology_repository import TopologyRepository

__all__ = [
    # Protocols
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
    # Sidecar-dataclasses
    "HistoryEntry",
    "PluginSpec",
    "PortSpec",
    "ServiceSpec",
    "DisplaySpec",
    "definition_to_spec",
    "spec_to_definition_dict",
    "FieldSpec",
    "Subscription",
]
