# -*- coding: utf-8 -*-
"""
test_app_services_factory.py — интеграционные тесты AppServices factory (Task D.1).

Тестирует:
  1. build_app_services() возвращает валидный AppServices с 10 не-None полями.
  2. dispatch(AddProcess) через services.commands — процесс появляется в topology.
  3. register_domain_schemas() вызывается ровно один раз (идемпотентность).
  4. factory fails loudly при отсутствии обязательных deps (recipe_manager/auth_state).
  5. AppContext.app_services: opt-in, None по умолчанию.

G.5.1: factory принимает explicit AppServicesDeps вместо AppContext —
тесты строят deps напрямую (mock-объекты), без build_app_context.

Refs: plans/2026-05-27_cross-tab-architecture/phase-d-app-services.md (Task D.1),
      plans/2026-05-27_cross-tab-architecture/phase-g.md (Task G.5.1)
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from multiprocess_prototype.adapters.stores.topology_repository import TopologyRepositoryStore
from multiprocess_prototype.domain import AppServices, AddProcess
from multiprocess_prototype.domain.tests._fakes import FakeEventBus
from multiprocess_prototype.frontend.app_services_factory import (
    AppServicesDeps,
    build_app_services,
)


# ============================================================================
# Фикстуры
# ============================================================================


def _make_recipe_manager(recipes_dir: Path) -> MagicMock:
    """Создать mock RecipeManager с минимальным API.

    RecipeStoreFromManager ожидает .read_recipe(slug), .list(), .get_active(),
    .set_active(slug). Для factory достаточно наличия объекта.
    """
    rm = MagicMock()
    rm.list.return_value = []
    rm.read_recipe.return_value = None
    rm.get_active.return_value = None
    return rm


def _make_auth_state() -> MagicMock:
    """Создать mock AuthState с минимальным API для AuthFacadeFromAuthState."""
    state = MagicMock()
    state.is_authenticated = False
    state.access_context = MagicMock()
    state.access_context.level = 0
    state.access_context.has_permission = MagicMock(return_value=False)
    return state


def _make_registers_manager() -> MagicMock:
    """Создать mock RegistersManager с минимальным API."""
    rm = MagicMock()
    rm.get_fields.return_value = []
    rm.get_register.return_value = None
    rm.set_field_value.return_value = (True, None)
    return rm


@pytest.fixture
def _deps(tmp_path: Path) -> AppServicesDeps:
    """AppServicesDeps с заполнёнными mock-зависимостями — полный набор для factory.

    EventBus + TopologyRepositoryStore (G.3) с минимальной валидной topology.
    """
    topology_dict: dict = {
        "processes": [],
        "wires": [],
        "displays": [],
    }
    event_bus = FakeEventBus()

    plugin_registry = MagicMock()
    plugin_registry.list.return_value = []
    plugin_registry.get.return_value = None

    display_registry = MagicMock()
    display_registry.list.return_value = []
    display_registry.get.return_value = None

    service_registry = MagicMock()
    service_registry.list.return_value = []
    service_registry.get.return_value = None

    return AppServicesDeps(
        event_bus=event_bus,
        topology_store=TopologyRepositoryStore(topology_dict, events=event_bus),
        plugin_registry=plugin_registry,
        display_registry=display_registry,
        service_registry=service_registry,
        registers_manager=_make_registers_manager(),
        config={},
        recipe_manager=_make_recipe_manager(tmp_path),
        auth_state=_make_auth_state(),
    )


# ============================================================================
# Тест 1: factory создаёт valid AppServices с 10 полями
# ============================================================================


class TestBuildAppServicesSmoke:
    """Smoke: build_app_services() возвращает AppServices, все 10 полей не None."""

    def test_factory_returns_app_services(self, _deps: AppServicesDeps) -> None:
        """build_app_services возвращает экземпляр AppServices."""
        result = build_app_services(_deps)
        assert isinstance(result, AppServices)

    def test_all_10_fields_not_none(self, _deps: AppServicesDeps) -> None:
        """Все 10 полей AppServices не None после factory."""
        result = build_app_services(_deps)

        assert result.plugins is not None
        assert result.services is not None
        assert result.displays is not None
        assert result.recipes is not None
        assert result.registers is not None
        assert result.topology is not None
        assert result.commands is not None
        assert result.events is not None
        assert result.auth is not None
        assert result.config is not None

    def test_app_services_is_frozen(self, _deps: AppServicesDeps) -> None:
        """AppServices — frozen dataclass, поля нельзя перезаписать."""
        result = build_app_services(_deps)

        with pytest.raises(AttributeError):
            result.plugins = None  # type: ignore[misc]


# ============================================================================
# Тест 2: dispatch AddProcess через services.commands
# ============================================================================


class TestDispatchThroughAppServices:
    """Интеграция: dispatch(AddProcess) → процесс появляется в topology."""

    def test_dispatch_add_process(self, _deps: AppServicesDeps) -> None:
        """После dispatch(AddProcess) процесс виден через services.topology.load()."""
        svc = build_app_services(_deps)

        # dispatch AddProcess — добавить процесс "cam"
        events = svc.commands.dispatch(AddProcess(process_name="cam", plugins=()))

        # Событие ProcessAdded должно быть в результатах
        assert len(events) > 0
        assert events[0].__class__.__name__ == "ProcessAdded"

        # Процесс должен быть виден в topology
        topology = svc.topology.load()
        process_names = [p.process_name for p in topology.processes]
        assert "cam" in process_names

    def test_dispatch_add_two_processes(self, _deps: AppServicesDeps) -> None:
        """Два AddProcess подряд — оба процесса видны в topology."""
        svc = build_app_services(_deps)

        svc.commands.dispatch(AddProcess(process_name="cam", plugins=()))
        svc.commands.dispatch(AddProcess(process_name="preview", plugins=()))

        topology = svc.topology.load()
        names = {p.process_name for p in topology.processes}
        assert names == {"cam", "preview"}


# ============================================================================
# Тест 3: register_domain_schemas вызывается (идемпотентность)
# ============================================================================


class TestRegisterDomainSchemas:
    """register_domain_schemas() идемпотентна — повторный вызов не падает."""

    def test_register_called_during_factory(self, _deps: AppServicesDeps) -> None:
        """register_domain_schemas вызывается внутри build_app_services."""
        with patch("multiprocess_prototype.frontend.app_services_factory.register_domain_schemas") as mock_reg:
            build_app_services(_deps)
            mock_reg.assert_called_once()

    def test_double_build_idempotent(self, _deps: AppServicesDeps) -> None:
        """Два вызова build_app_services не падают (register идемпотентна)."""
        svc1 = build_app_services(_deps)
        svc2 = build_app_services(_deps)
        assert isinstance(svc1, AppServices)
        assert isinstance(svc2, AppServices)


# ============================================================================
# Тест 4: factory fails loudly при отсутствии обязательных deps
# ============================================================================


class TestFactoryFailsLoudly:
    """При None-значениях recipe_manager/auth_state — RuntimeError с понятным сообщением."""

    def test_missing_recipe_manager(self, _deps: AppServicesDeps) -> None:
        """recipe_manager=None — RuntimeError с понятным сообщением."""
        deps = replace(_deps, recipe_manager=None)

        with pytest.raises(RuntimeError, match="recipe_manager"):
            build_app_services(deps)

    def test_missing_auth_state(self, _deps: AppServicesDeps) -> None:
        """auth_state=None — RuntimeError с понятным сообщением."""
        deps = replace(_deps, auth_state=None)

        with pytest.raises(RuntimeError, match="auth_state"):
            build_app_services(deps)


# ============================================================================
# Тест 5: AppContext.app_services opt-in (None по умолчанию)
# ============================================================================


class TestAppContextAppServicesField:
    """Поле app_services на AppContext: opt-in, backward-compat.

    NB: AppContext удаляется в G.5.3 — этот класс уйдёт вместе с ним.
    """

    def test_app_services_default_none(self) -> None:
        """app_services по умолчанию None (backward-compat с существующими тестами)."""
        from multiprocess_prototype.frontend.app_context import build_app_context

        process = MagicMock()
        process.name = "gui_process"
        process._bridge = MagicMock()
        ctx = build_app_context(process)
        assert ctx.app_services is None

    def test_app_services_can_be_set(self, _deps: AppServicesDeps) -> None:
        """app_services можно присвоить после build."""
        from multiprocess_prototype.frontend.app_context import build_app_context

        process = MagicMock()
        process.name = "gui_process"
        process._bridge = MagicMock()
        ctx = build_app_context(process)

        svc = build_app_services(_deps)
        ctx.app_services = svc
        assert ctx.app_services is svc
        assert isinstance(ctx.app_services, AppServices)
