"""``GenericProcessManagerApp`` + двухсортные хук-точки (Ф5.12).

Покрывает:
  - **build-time** хуки: ``state_bootstrap`` / ``throttle_rules`` → их РЕЗУЛЬТАТ
    попадает в ``orchestrator_config`` (пиклится через spawn);
  - анти-хук-взрыв (ADR-APP-006): без state-plane ``_setup_state_store`` — no-op;
  - **runtime** хук: дефолт оркестратора = generic ``GenericProcessManagerApp``,
    явный ``orchestrator_class_path`` побеждает; ``_configure_runtime`` — no-op seam.
"""

from __future__ import annotations

import time
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


class TestRetargetRecipeWatcherAddress:
    """R6 (живой switch, 2026-07-29): ретаргет обязан обновить АДРЕС рецепта.

    Адрес читают трое: watcher (атрибут), ассемблер на каждой сборке и
    ``observability.persist`` — и последние двое читают КОНФИГ. Пока ретаргет
    писал только атрибут, «сохранить» после switch уходило в спутник рецепта,
    с которого ушли, а следующая замена раздавала детям его же адрес.

    Тестов у ретаргета не было вовсе с момента ввода (5.12); единственный
    смежный (``test_hot_swap_resolves_recipe_path_per_build``) правил ключ
    руками — то есть проверял резолвер, а не то, что этот ключ кто-то пишет.
    """

    @staticmethod
    def _orch(config: dict) -> GenericProcessManagerApp:
        orch = _make_orchestrator(config)
        orch.logger_manager = MagicMock()
        orch.error_manager = MagicMock()
        orch.stats_manager = MagicMock()
        orch._log_info = MagicMock()
        orch._log_error = MagicMock()
        orch._observability_recipe_watcher = None
        return orch

    def test_retarget_writes_the_address_into_config(self) -> None:
        from multiprocess_framework.modules.process_module.configs.observability_layers import (
            RECIPE_PATH_CONFIG_KEY,
        )

        orch = self._orch({RECIPE_PATH_CONFIG_KEY: "recipes/a.yaml"})

        returned = orch.retarget_observability_recipe_watcher("recipes/b.yaml")

        assert returned == "recipes/b.yaml"
        # Читателем выступает тот же способ чтения, что у ассемблера и persist.
        assert orch.get_config(RECIPE_PATH_CONFIG_KEY) == "recipes/b.yaml"

    def test_retarget_without_path_and_without_manifest_clears_the_address(self) -> None:
        """Пустой адрес — не «оставить как было»: watcher продолжил бы применять
        чужой файл, выдавая это за работающий hot-reload."""
        from multiprocess_framework.modules.process_module.configs.observability_layers import (
            RECIPE_PATH_CONFIG_KEY,
        )

        orch = self._orch({RECIPE_PATH_CONFIG_KEY: "recipes/a.yaml"})

        returned = orch.retarget_observability_recipe_watcher("")

        assert returned == ""
        assert orch.get_config(RECIPE_PATH_CONFIG_KEY) == ""

    def test_retarget_repoints_the_layer_source_without_touching_content(self) -> None:
        """Читатель (`introspect.observability`) и писатель (`persist`) обязаны
        назвать ОДИН файл. Живьём после switch оркестратор остался единственным,
        кто показывал источником покинутый рецепт, — при том что сохранял уже в
        новый. Содержимое слоя ретаргет не меняет: его оркестратору не раздаёт и
        boot, и выдача здесь развела бы switch со стартом."""
        from multiprocess_framework.modules.process_module.configs.observability_layers import (
            LAYER_RECIPE,
            RECIPE_PATH_CONFIG_KEY,
            process_observability_layers,
        )

        orch = self._orch({RECIPE_PATH_CONFIG_KEY: "recipes/a.yaml"})
        layers = process_observability_layers(orch)
        layers.replace_layer(LAYER_RECIPE, {"log_level": "WARNING"}, source="recipes/a.yaml", origin="test")

        orch.retarget_observability_recipe_watcher("recipes/b.yaml")

        assert layers.recipe_source == "recipes/b.yaml"
        assert layers.recipe == {"log_level": "WARNING"}


class TestRetargetIsOneCriticalBlock:
    """R6-F (Task 5.11.e): адрес рецепта и источник слоя — ОДИН факт.

    Прежде ключ конфига писался вне ``layers.lock``, а ``replace_layer`` — внутри.
    Конкурентный ``introspect.observability``, попавший в зазор, видел новый
    адрес при старом ``recipe_source`` и показывал их как два разных факта — то
    есть отвечал на «где мой слой» двумя несовместимыми ответами подряд.
    """

    def test_concurrent_reader_never_sees_a_half_moved_address(self) -> None:
        import threading

        from multiprocess_framework.modules.process_module.configs.observability_layers import (
            LAYER_RECIPE,
            RECIPE_PATH_CONFIG_KEY,
            process_observability_layers,
        )

        orch = _make_orchestrator({RECIPE_PATH_CONFIG_KEY: "recipes/a.yaml"})
        orch.logger_manager = MagicMock()
        orch.error_manager = MagicMock()
        orch.stats_manager = MagicMock()
        orch._log_info = MagicMock()
        orch._log_error = MagicMock()
        orch._observability_recipe_watcher = None
        layers = process_observability_layers(orch)
        layers.replace_layer(LAYER_RECIPE, {"log_level": "WARNING"}, source="recipes/a.yaml", origin="test")

        reader_may_go = threading.Event()
        seen: list[tuple] = []

        def _reader():
            """Читает пару (адрес конфига, источник слоя) — так же, как readback."""
            reader_may_go.wait(2.0)
            # Лок берётся ЯВНО: `introspect.observability` читает стек слоёв под
            # ним же. Без лока тест проверял бы гонку, а не защиту от неё.
            if not layers.lock.acquire(timeout=2.0):
                seen.append(("НЕ ВЗЯЛ ЛОК", None))
                return
            try:
                seen.append((orch.get_config(RECIPE_PATH_CONFIG_KEY), layers.recipe_source))
            finally:
                layers.lock.release()

        reader = threading.Thread(target=_reader, daemon=True)
        reader.start()

        original_update = orch.update_config

        def _slow_update(key, value):
            """Шов ВНУТРИ критического блока: даём читателю реальный шанс влезть."""
            result = original_update(key, value)
            reader_may_go.set()
            time.sleep(0.15)
            return result

        orch.update_config = _slow_update
        orch.retarget_observability_recipe_watcher("recipes/b.yaml")

        reader.join(timeout=3.0)
        assert not reader.is_alive(), "читатель завис — критический блок не отпустил лок"
        assert seen, "читатель не отработал"
        address, source = seen[0]
        assert (address, source) == ("recipes/b.yaml", "recipes/b.yaml"), (
            f"читатель увидел половину переезда: адрес={address!r}, источник слоя={source!r}"
        )


class TestWatcherFansOutToChildren:
    """R4 (Task 5.11.f): правка файла доезжает до ДЕТЕЙ, а не только до оркестратора.

    Оба watcher'а живут только у оркестратора и до 5.11 применяли файл только к
    его менеджерам: пульт показывал новое значение, а дети продолжали писать
    по-старому до следующего рестарта. Своих watcher'ов детям не заводим — один
    наблюдатель на файл, — поэтому раздача идёт рассылкой «перечитай свой
    источник».
    """

    @staticmethod
    def _orch(tmp_path, monkeypatch):
        from multiprocess_framework.modules.process_module.configs.observability_layers import (
            RECIPE_PATH_CONFIG_KEY,
        )

        system_yaml = tmp_path / "system.yaml"
        system_yaml.write_text("observability:\n  log_level: INFO\n", encoding="utf-8")
        recipe = tmp_path / "demo.yaml"
        recipe.write_text("name: demo\n", encoding="utf-8")
        companion = recipe.with_name("demo.observability.yaml")
        companion.write_text("observability:\n  defaults:\n    log_level: DEBUG\n", encoding="utf-8")

        orch = _make_orchestrator(
            {
                "observability_config_path": str(system_yaml),
                RECIPE_PATH_CONFIG_KEY: str(recipe),
            }
        )
        orch.logger_manager = MagicMock()
        orch.error_manager = MagicMock()
        orch.stats_manager = MagicMock()
        orch._log_info = MagicMock()
        orch._log_error = MagicMock()
        orch._observability_watcher = None
        orch._observability_recipe_watcher = None

        sent: list = []
        orch._broadcast_command = lambda command, data, **kw: sent.append((command, dict(data))) or 3

        # Перехват фабрики: нужен НЕ живой watchdog, а колбэк, который он позовёт.
        started: list = []
        import multiprocess_framework.modules.process_module.managers.observability_reload as reload_mod

        monkeypatch.setattr(
            reload_mod,
            "start_observability_watcher",
            lambda **kw: started.append(kw) or MagicMock(),
        )
        return orch, started, sent

    def test_both_watchers_hand_the_edit_to_children(self, tmp_path, monkeypatch) -> None:
        orch, started, sent = self._orch(tmp_path, monkeypatch)

        orch._start_observability_watcher()

        assert len(started) == 2, "подняты не оба watcher'а (L1 + L2)"
        # Зовём то, что watchdog позвал бы при правке файла, и смотрим на ЭФФЕКТ.
        for kw in started:
            callback = kw.get("on_reload_extra")
            assert callable(callback), "watcher поднят без раздачи детям"
            callback(MagicMock())

        commands = [c for c, _d in sent]
        assert commands == ["config.reload", "config.reload"]
        payloads = [d for _c, d in sent]
        # L1 — «перечитай свой источник» (у ребёнка он может быть другим файлом),
        # L2 — «пересобери слой рецепта со своего адреса».
        assert {} in payloads
        assert {"observability_recipe_reload": True} in payloads

    def test_fan_out_failure_does_not_kill_hot_reload(self, tmp_path, monkeypatch) -> None:
        orch, started, _sent = self._orch(tmp_path, monkeypatch)

        def _dead(command, data, **kw):
            raise RuntimeError("очередь закрыта")

        orch._broadcast_command = _dead
        orch._start_observability_watcher()

        for kw in started:
            kw["on_reload_extra"](MagicMock())  # не имеет права бросить

        assert orch._log_error.called

    def test_l1_fan_out_runs_after_the_telemetry_callback_not_instead_of_it(self, tmp_path, monkeypatch) -> None:
        """Раздача — добавка к существующему extra-колбэку (центральный троттл),
        а не его замена: иначе одна правка чинила бы одну плоскость и ломала другую."""
        orch, started, sent = self._orch(tmp_path, monkeypatch)
        order: list = []
        orch._broadcast_command = lambda command, data, **kw: order.append("fan-out") or 1

        extra = orch._compose_fan_out(lambda cfg: order.append("telemetry"), {}, "тест")
        extra(MagicMock())

        assert order == ["telemetry", "fan-out"]
