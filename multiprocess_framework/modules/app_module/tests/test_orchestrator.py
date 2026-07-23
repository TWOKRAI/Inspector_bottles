"""``GenericProcessManagerApp`` + двухсортные хук-точки (Ф5.12).

Покрывает:
  - **build-time** хуки: ``state_bootstrap`` / ``throttle_rules`` → их РЕЗУЛЬТАТ
    попадает в ``orchestrator_config`` (пиклится через spawn);
  - анти-хук-взрыв (ADR-APP-006): без state-plane ``_setup_state_store`` — no-op;
  - **runtime** хук: дефолт оркестратора = generic ``GenericProcessManagerApp``,
    явный ``orchestrator_class_path`` побеждает; ``_configure_runtime`` — no-op seam.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from multiprocess_framework.modules.app_module import (
    GENERIC_ORCHESTRATOR_CLASS_PATH,
    AppSpec,
    build_app,
)
from multiprocess_framework.modules.app_module.orchestrator import GenericProcessManagerApp
from multiprocess_framework.modules.state_store_module.testing.in_memory_router import (
    InMemoryRouter,
)


# ---------------------------------------------------------------------------
# _setup_state_store — потребление build-time хуков + анти-хук-взрыв
# ---------------------------------------------------------------------------


def _make_orchestrator(config: dict) -> GenericProcessManagerApp:
    """Собрать оркестратор без multiprocessing-init (только поля для _setup_state_store)."""
    orch = GenericProcessManagerApp.__new__(GenericProcessManagerApp)
    orch.name = "ProcessManager"
    orch.config = config
    orch.config_handler = None
    orch.router_manager = InMemoryRouter()
    orch.command_manager = MagicMock()
    orch._state_store_manager = None
    return orch


class TestSetupStateStoreGating:
    """Анти-хук-взрыв: state-plane поднимается ТОЛЬКО при наличии build-time данных."""

    def test_no_state_no_throttle_is_noop(self) -> None:
        """Пустой конфиг (minimal_app) → StateStore не создаётся."""
        orch = _make_orchestrator({"initial_state": {}})
        orch._setup_state_store()
        assert orch._state_store_manager is None

    def test_absent_keys_is_noop(self) -> None:
        """Ключи вовсе отсутствуют → тоже no-op (get_config → None)."""
        orch = _make_orchestrator({})
        orch._setup_state_store()
        assert orch._state_store_manager is None

    def test_initial_state_creates_store(self) -> None:
        """Непустой initial_state (build-time state_bootstrap) → StateStore создан."""
        orch = _make_orchestrator({"initial_state": {"system": {"x": 1}}})
        orch._setup_state_store()
        assert orch._state_store_manager is not None
        assert orch._state_store_manager.is_initialized
        assert orch._state_store_manager.store.get("system.x") == 1

    def test_only_throttle_creates_store(self) -> None:
        """Только throttle_rules (без initial_state) → StateStore + middleware."""
        orch = _make_orchestrator({"initial_state": {}, "state_throttle_rules": {"system.*": {"interval_ms": 100}}})
        orch._setup_state_store()
        assert orch._state_store_manager is not None
        pipeline = orch._state_store_manager.pipeline
        assert len(pipeline._middlewares) > 0
        assert pipeline._middlewares[0].name == "throttle"

    def test_commands_registered_when_store_created(self) -> None:
        """При созданном store команды state.* регистрируются в CommandManager."""
        orch = _make_orchestrator({"initial_state": {"system": {"x": 1}}})
        orch._setup_state_store()
        names = [c.args[0] for c in orch.command_manager.register_command.call_args_list]
        assert "state.set" in names


class TestConfigureRuntimeSeam:
    """``_configure_runtime`` — no-op seam в generic (runtime-хуки подключает подкласс)."""

    def test_generic_configure_runtime_is_noop(self) -> None:
        orch = GenericProcessManagerApp.__new__(GenericProcessManagerApp)
        # Не должно бросать / что-либо требовать.
        assert orch._configure_runtime() is None


# ---------------------------------------------------------------------------
# _build_generic — проводка двухсортных хуков в launcher
# ---------------------------------------------------------------------------


def _write_manifest(tmp_path: Path) -> Path:
    """Минимальный app.yaml без авто-скана (pipeline не читается — loader переопределён)."""
    p = tmp_path / "app.yaml"
    p.write_text(
        "name: T\nversion: 1\npipeline: pipeline.yaml\ndiscovery:\n  auto_discover: false\n",
        encoding="utf-8",
    )
    return p


def _spec_with_hooks(tmp_path: Path, **overrides) -> AppSpec:
    kwargs = dict(
        manifest_path=_write_manifest(tmp_path),
        blueprint_loader=lambda manifest: {},
        proc_dicts_builder=lambda blueprint: {},
    )
    kwargs.update(overrides)
    return AppSpec(**kwargs)


class TestBuildGenericHookWiring:
    def test_default_orchestrator_is_generic(self, tmp_path: Path) -> None:
        """Без orchestrator_class_path — дефолт = generic GenericProcessManagerApp."""
        launcher = build_app(_spec_with_hooks(tmp_path))
        assert launcher._orchestrator_class_path == GENERIC_ORCHESTRATOR_CLASS_PATH

    def test_explicit_orchestrator_path_wins(self, tmp_path: Path) -> None:
        """Явный orchestrator_class_path (runtime-хук приложения) побеждает дефолт."""
        custom = "some.app.CustomOrchestrator"
        launcher = build_app(_spec_with_hooks(tmp_path, orchestrator_class_path=custom))
        assert launcher._orchestrator_class_path == custom

    def test_state_bootstrap_result_in_config(self, tmp_path: Path) -> None:
        """build-time state_bootstrap(blueprint) → orchestrator_config['initial_state']."""
        launcher = build_app(_spec_with_hooks(tmp_path, state_bootstrap=lambda blueprint: {"seeded": True}))
        assert launcher._orchestrator_config["initial_state"] == {"seeded": True}

    def test_throttle_rules_result_in_config(self, tmp_path: Path) -> None:
        """build-time throttle_rules(blueprint) → orchestrator_config['state_throttle_rules']."""
        launcher = build_app(_spec_with_hooks(tmp_path, throttle_rules=lambda blueprint: {"a.*": {"interval_ms": 50}}))
        assert launcher._orchestrator_config["state_throttle_rules"] == {"a.*": {"interval_ms": 50}}

    def test_no_build_time_hooks_minimal_config(self, tmp_path: Path) -> None:
        """Без хуков (minimal_app) — только пустой initial_state, без throttle."""
        launcher = build_app(_spec_with_hooks(tmp_path))
        assert launcher._orchestrator_config == {"initial_state": {}}

    def test_explicit_orchestrator_config_can_override(self, tmp_path: Path) -> None:
        """Явный orchestrator_config приложения применяется последним."""
        launcher = build_app(_spec_with_hooks(tmp_path, orchestrator_config={"initial_state": {"forced": 1}}))
        assert launcher._orchestrator_config["initial_state"] == {"forced": 1}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


class TestShutdownStopsStatePlane:
    """Симметрия initialize/shutdown для state-plane (предмерж-ревью Ф6).

    Оркестратор поднимал StateStoreManager, но НИКОГДА не звал его ``shutdown()`` —
    обещанный в докстринге финальный дренаж буфера коалесцирования был мёртвым кодом,
    а daemon-flusher переживал остановку оркестратора.
    """

    def test_shutdown_calls_state_store_shutdown(self, monkeypatch) -> None:
        orch = _make_orchestrator({"initial_state": {"system": {"x": 1}}})
        orch._setup_state_store()
        assert orch._state_store_manager is not None
        orch._state_store_manager.shutdown = MagicMock(return_value=True)
        monkeypatch.setattr(type(orch).__mro__[1], "shutdown", lambda self: True, raising=False)

        orch.shutdown()

        orch._state_store_manager.shutdown.assert_called_once()

    def test_shutdown_without_state_plane_is_noop(self, monkeypatch) -> None:
        """Процесс без state-plane (minimal_app) — shutdown не падает."""
        orch = _make_orchestrator({})
        monkeypatch.setattr(type(orch).__mro__[1], "shutdown", lambda self: True, raising=False)
        assert orch.shutdown() is True

    def test_state_store_shutdown_failure_does_not_block(self, monkeypatch) -> None:
        """Сбой остановки state-plane не срывает остановку ядра (best-effort)."""
        orch = _make_orchestrator({"initial_state": {"system": {"x": 1}}})
        orch._setup_state_store()
        orch._state_store_manager.shutdown = MagicMock(side_effect=RuntimeError("бум"))
        monkeypatch.setattr(type(orch).__mro__[1], "shutdown", lambda self: True, raising=False)

        assert orch.shutdown() is True
