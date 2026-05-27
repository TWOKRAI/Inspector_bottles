# -*- coding: utf-8 -*-
"""
Phase C / Task C.7 — Integration smoke: AppServices через реальные adapter'ы.

Тест проверяет, что все 9 adapter'ов из Phase C можно собрать в AppServices
и выполнить dispatch(AddProcess) end-to-end:

    1. Сборка AppServices без TypeError (все adapter'ы satisfy Protocol'ы).
    2. dispatch(AddProcess("test")) → ProcessAdded event в списке.
    3. topology.load().processes содержит process "test" после dispatch.

Стратегия минимальных реестров:
    Реальные реестры (PluginRegistry, ServiceRegistry, DisplayRegistry)
    требуют discover_plugins() с YAML и IPC для полной инициализации.
    В данном тесте используются минимальные API-compatible fakes
    там, где реальные реестры требуют слишком сложной обвязки.
    Adapter'ы НАСТОЯЩИЕ — только реестры-shim.

    Полная сборка с реальными реестрами помечена @pytest.mark.skip
    (TODO Phase D когда AppServices factory появится в app.py).

Refs: plans/2026-05-27_cross-tab-architecture/phase-c-adapters.md (Task C.7)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from multiprocess_prototype.adapters import (
    AuthFacadeFromAuthState,
    CommandDispatcherOrchestrator,
    DisplayCatalogFromRegistry,
    PluginCatalogFromRegistry,
    ProjectHolder,
    RecipeStoreFromManager,
    RegistersBackendFromManager,
    ServiceManagerFromRegistry,
    TopologyRepositoryFromHolder,
)
from multiprocess_prototype.domain.app_services import AppServices
from multiprocess_prototype.domain.commands import AddProcess
from multiprocess_prototype.domain.entities.project import ApplyContext, Project
from multiprocess_prototype.domain.entities.topology import Topology
from multiprocess_prototype.domain.event_bus import EventBus
from multiprocess_prototype.domain.events import ProcessAdded
from multiprocess_prototype.frontend.topology_holder import TopologyHolder


# =============================================================================
# Минимальные API-compatible fakes для реестров
# =============================================================================
# Используются потому что реальные реестры требуют discover_plugins() с YAML.
# Интеграционный смысл: adapter'ы реальные — только реестры-shim.
# Документировано в docstring модуля выше.


class _FakePluginRegistry:
    """Минимальный in-memory _PluginRegistry shim.

    Имитирует API _PluginRegistry из framework:
        list() -> list[PluginEntry]
        get(name) -> PluginEntry | None
        filter(category) -> list[PluginEntry]

    Реальный PluginRegistry требует discover_plugins() → YAML-файлы плагинов.
    """

    def list(self) -> list[Any]:
        """Пустой каталог — нет зарегистрированных плагинов."""
        return []

    def get(self, name: str) -> None:
        """Плагин не найден (пустой каталог)."""
        return None

    def filter(self, category: str) -> list[Any]:
        """Нет плагинов в данной категории."""
        return []


class _FakeServiceRegistry:
    """Минимальный ServiceRegistry shim.

    ServiceRegistry — singleton с внутренним state. Вместо очистки глобального
    singleton используем stub-объект для изоляции интеграционного теста.
    """

    def list(self) -> list[Any]:
        return []

    def get(self, service_id: str) -> None:
        return None

    def clear(self) -> None:
        pass


class _FakeDisplayRegistry:
    """Минимальный DisplayRegistry shim.

    DisplayRegistry в реальном коде загружает entries из YAML/конфига.
    """

    def list(self) -> list[Any]:
        return []

    def get(self, display_id: str) -> None:
        return None

    def clear(self) -> None:
        pass


class _FakeRecipeManager:
    """Минимальный RecipeManager shim для RecipeStoreFromManager.

    RecipeManager требует инициализации с путями к YAML-файлам.
    Shim возвращает пустые результаты для операций чтения.
    """

    def read_recipe(self, slug: str) -> dict[str, Any] | None:
        return None

    def get_active_recipe(self) -> str | None:
        return None

    def activate(self, slug: str) -> None:
        pass

    @property
    def _active_name(self) -> None:  # noqa: B027
        return None

    @_active_name.setter
    def _active_name(self, value: Any) -> None:
        pass


class _FakeRegistersManager:
    """Минимальный RegistersManager shim.

    RegistersManager знает о register-классах и полях конфигурации плагинов.
    Для интеграционного теста достаточно пустого shim.
    """

    def get_fields(self, register_name: str) -> list[Any]:
        return []

    def get_register(self, register_name: str) -> None:
        return None

    def set_field_value(self, register_name: str, field_name: str, value: Any) -> tuple[bool, None]:
        return (False, None)


class _FakeAccessContext:
    """Минимальный AccessContext shim для AuthFacadeFromAuthState."""

    def __init__(self) -> None:
        self.level = 0

    def has_permission(self, key: str) -> bool:
        return True


class _FakeAuthState:
    """Минимальный AuthState shim для AuthFacadeFromAuthState.

    AuthState — QObject. Используем duck-typed shim без PySide6.
    """

    def __init__(self) -> None:
        self._access_context = _FakeAccessContext()
        self.is_authenticated = False

    @property
    def access_context(self) -> _FakeAccessContext:
        return self._access_context


# =============================================================================
# Вспомогательные фабрики
# =============================================================================


def _build_app_services(tmp_path: Path) -> AppServices:
    """Собрать AppServices через все 9 реальных adapter'ов.

    Стратегия:
        - Adapter'ы — НАСТОЯЩИЕ классы из Phase C.
        - Реестры — минимальные API-compatible fakes (см. выше).
        - TopologyHolder — реальный (простой Python-объект, не QObject).
        - EventBus — реальный.
        - ProjectHolder — реальный.

    Returns:
        Собранный AppServices с реальными adapter'ами.
    """
    # --- Реальные helper-объекты ---
    holder = TopologyHolder()  # реальный, не QObject
    event_bus = EventBus()  # реальный

    # --- 9 реальных adapter'ов (fakes только для реестров-зависимостей) ---

    # 1. PluginCatalogFromRegistry
    plugin_catalog = PluginCatalogFromRegistry(_FakePluginRegistry())  # type: ignore[arg-type]

    # 2. ServiceManagerFromRegistry
    service_manager = ServiceManagerFromRegistry(_FakeServiceRegistry())  # type: ignore[arg-type]

    # 3. DisplayCatalogFromRegistry
    display_catalog = DisplayCatalogFromRegistry(_FakeDisplayRegistry())  # type: ignore[arg-type]

    # 4. TopologyRepositoryFromHolder (реальный holder)
    topology_repo = TopologyRepositoryFromHolder(holder)

    # 5. RecipeStoreFromManager
    recipe_store = RecipeStoreFromManager(
        recipe_manager=_FakeRecipeManager(),  # type: ignore[arg-type]
        recipe_dir=tmp_path / "recipes",
    )
    (tmp_path / "recipes").mkdir(parents=True, exist_ok=True)

    # 6. RegistersBackendFromManager (Variant A: знает topology_repo + plugin_catalog)
    registers_backend = RegistersBackendFromManager(
        registers_manager=_FakeRegistersManager(),  # type: ignore[arg-type]
        topology_repo=topology_repo,
        plugin_catalog=plugin_catalog,
    )

    # 7. AuthFacadeFromAuthState
    auth_facade = AuthFacadeFromAuthState(auth_state=_FakeAuthState())

    # 8-9. ProjectHolder + CommandDispatcherOrchestrator
    initial_project = Project(topology=Topology())
    project_holder = ProjectHolder(initial=initial_project)

    def _apply_ctx_factory() -> ApplyContext:
        """Динамический ApplyContext — каждый dispatch получает свежий контекст."""
        return ApplyContext(
            plugins=plugin_catalog,
            displays=display_catalog,
        )

    dispatcher = CommandDispatcherOrchestrator(
        project_holder=project_holder,
        topology_repo=topology_repo,
        event_bus=event_bus,
        apply_context_factory=_apply_ctx_factory,
    )

    return AppServices(
        plugins=plugin_catalog,
        services=service_manager,
        displays=display_catalog,
        recipes=recipe_store,
        registers=registers_backend,
        topology=topology_repo,
        commands=dispatcher,
        events=event_bus,
        auth=auth_facade,
    )


# =============================================================================
# Тесты
# =============================================================================


def test_assemble_app_services_with_real_adapters(tmp_path: Path) -> None:
    """Integration smoke: 9 реальных adapter'ов собираются в AppServices без TypeError.

    Верифицирует сборку (AppServices.__init__ с реальными adapter'ами) —
    отсутствие TypeError означает, что все adapter'ы satisfy соответствующие Protocol'ы
    с точки зрения конструктора dataclass.
    """
    services = _build_app_services(tmp_path)
    # Сборка прошла без TypeError — все adapter'ы переданы корректно
    assert services is not None
    assert services.plugins is not None
    assert services.services is not None
    assert services.displays is not None
    assert services.recipes is not None
    assert services.registers is not None
    assert services.topology is not None
    assert services.commands is not None
    assert services.events is not None
    assert services.auth is not None


def test_dispatch_add_process_end_to_end(tmp_path: Path) -> None:
    """Integration smoke: dispatch(AddProcess) end-to-end через реальные adapter'ы.

    Проверяет полный цикл:
    1. dispatch(AddProcess("test")) → список событий содержит ProcessAdded.
    2. topology.load() отражает новый процесс (ProjectHolder → TopologyHolder → load()).
    3. Пустой PluginCatalog — catalog-invariant пропускается (ApplyContext.plugins=None
       или пустой каталог не блокирует AddProcess без плагинов).
    """
    services = _build_app_services(tmp_path)

    # Dispatch команды
    events = services.commands.dispatch(AddProcess(process_name="test"))

    # Минимум одно событие ProcessAdded
    assert any(isinstance(e, ProcessAdded) for e in events), f"Ожидался ProcessAdded в событиях, получено: {events}"

    # Проверяем что process 'test' появился в topology через TopologyRepository
    topology = services.topology.load()
    process_names = {p.process_name for p in topology.processes}
    assert "test" in process_names, f"Процесс 'test' не найден в topology.processes: {process_names}"

    # Пустой plugin catalog → list_plugins() возвращает пустой tuple (нормально)
    plugins = services.plugins.list_plugins()
    assert isinstance(plugins, tuple)


def test_dispatch_duplicate_process_raises_domain_error(tmp_path: Path) -> None:
    """Edge case: повторный AddProcess с тем же именем → DomainError.

    Holder и topology остаются в предыдущем состоянии (implicit rollback из apply()).
    """
    from multiprocess_prototype.domain.errors import DomainError

    services = _build_app_services(tmp_path)

    # Первый dispatch — успешно
    services.commands.dispatch(AddProcess(process_name="dup_proc"))

    # Проверяем что 'dup_proc' появился
    assert "dup_proc" in {p.process_name for p in services.topology.load().processes}

    # Второй dispatch с тем же именем — DomainError
    with pytest.raises(DomainError):
        services.commands.dispatch(AddProcess(process_name="dup_proc"))

    # Topology не сломалась — процесс по-прежнему только один
    topology = services.topology.load()
    dup_count = sum(1 for p in topology.processes if p.process_name == "dup_proc")
    assert dup_count == 1, f"Ожидался ровно 1 'dup_proc', найдено: {dup_count}"


@pytest.mark.skip(
    reason=(
        "TODO Phase D: полная сборка с реальными реестрами требует AppServices factory в app.py. "
        "discover_plugins() нужен YAML-каталог, DisplayRegistry — displays.yaml, "
        "RecipeManager — production recipe_dir. Активировать при Phase D Task D.1."
    )
)
def test_assemble_with_real_registries(tmp_path: Path) -> None:  # pragma: no cover
    """TODO Phase D — smoke с полностью реальными реестрами (discover_plugins, реальные YAML).

    Этот тест демонстрирует целевую сборку после Phase D AppServices factory:

        from multiprocess_framework.modules.process_module.plugins.registry import PluginRegistry
        from multiprocess_prototype.registers import PluginRegistry as AppPluginRegistry
        AppPluginRegistry.discover_plugins(...)

        from multiprocess_framework.modules.service_module.registry import ServiceRegistry
        ServiceRegistry().discover(...)

        from multiprocess_framework.modules.display_module.registry import DisplayRegistry
        DisplayRegistry().load_from_yaml(...)

        from multiprocess_prototype.recipes.manager import RecipeManager
        rm = RecipeManager(recipe_dir=...)
        rm.load()

        services = AppServices(
            plugins=PluginCatalogFromRegistry(PluginRegistry),
            services=ServiceManagerFromRegistry(ServiceRegistry()),
            ...
        )
        assert len(services.plugins.list_plugins()) > 0
    """
    pass
