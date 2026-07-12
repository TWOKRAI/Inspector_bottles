# -*- coding: utf-8 -*-
"""
Round-trip тесты для domain entities.

Проверяет:
- Загрузка реальных YAML-файлов → entity → dict и обратно (roundtrip).
- Frozen behaviour (попытка мутации → ValidationError).
- extra="forbid" (лишние поля → ValidationError).
- Обязательные поля (отсутствие → EntityValidationError).
- Process.plugins — тип tuple, не list (immutability).
- to_dict / from_dict идемпотентность.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from multiprocess_prototype.domain import (
    DisplayCrop,
    DisplayDefinition,
    DisplayInstance,
    DisplayPosition,
    EntityValidationError,
    PluginInstance,
    Process,
    Project,
    Recipe,
    RecipeMeta,
    Topology,
    Wire,
    WorkerSpec,
)


# ==============================================================================
# Вспомогательные функции
# ==============================================================================


def _load_yaml(path: Path) -> dict[str, Any]:
    """Загрузить YAML-файл в dict."""
    return yaml.safe_load(path.read_text(encoding="utf-8"))  # type: ignore[return-value]


# ==============================================================================
# Round-trip: pilot_widgets.yaml → Topology (blueprint)
# ==============================================================================


class TestDefaultBlueprintRoundtrip:
    """Тесты round-trip для pilot_widgets.yaml (DEFAULT_BLUEPRINT)."""

    def test_default_blueprint_roundtrip(self, fixtures_dir: Path) -> None:
        """pilot_widgets.yaml → Topology → dict и назад, поля совпадают."""
        blueprint_path = fixtures_dir / "backend" / "topology" / "pilot_widgets.yaml"
        assert blueprint_path.exists(), f"Файл не найден: {blueprint_path}"

        raw = _load_yaml(blueprint_path)

        # Создаём Topology из секции processes (wires и displays отсутствуют в pilot_widgets.yaml)
        # blueprint содержит только processes — thin Topology с пустыми wires/displays
        topology_data: dict[str, Any] = {
            "processes": raw.get("processes", []),
            "wires": raw.get("wires", []),
            "displays": raw.get("displays", []),
        }
        topology = Topology.from_dict(topology_data)

        # Проверяем структуру
        assert len(topology.processes) == 2  # pilot + gui

        pilot = topology.processes[0]
        assert pilot.process_name == "pilot"
        assert len(pilot.plugins) == 1
        assert pilot.plugins[0].plugin_name == "pilot_widgets"

        gui = topology.processes[1]
        assert gui.process_name == "gui"
        assert gui.protected is True
        assert len(gui.plugins) == 0

        # Round-trip: to_dict → from_dict
        topo_dict = topology.to_dict()
        topology2 = Topology.from_dict(topo_dict)

        # Ключевые поля совпадают
        assert topology2.processes[0].process_name == topology.processes[0].process_name
        assert topology2.processes[1].process_name == topology.processes[1].process_name
        assert topology2.processes[0].plugins[0].plugin_name == "pilot_widgets"

    def test_blueprint_processes_are_tuple(self, fixtures_dir: Path) -> None:
        """processes в Topology — tuple, не list."""
        blueprint_path = fixtures_dir / "backend" / "topology" / "pilot_widgets.yaml"
        raw = _load_yaml(blueprint_path)
        topology = Topology.from_dict({"processes": raw.get("processes", [])})
        assert isinstance(topology.processes, tuple)
        for proc in topology.processes:
            assert isinstance(proc.plugins, tuple)


# ==============================================================================
# Round-trip: demo_webcam_split_merge.yaml → Recipe
# ==============================================================================

# Рецепт удалён (webcam_camera деприкейчен); вычисляем путь аналогично fixtures_dir
_DEMO_RECIPE_PATH = Path(__file__).resolve().parent.parent.parent / "recipes" / "demo_webcam_split_merge.yaml"
_SKIP_DEMO = pytest.mark.skipif(
    not _DEMO_RECIPE_PATH.exists(),
    reason="рецепт demo_webcam_split_merge.yaml удалён (webcam_camera деприкейчен)",
)


@_SKIP_DEMO
class TestDemoRecipeRoundtrip:
    """Тесты round-trip для demo_webcam_split_merge.yaml."""

    def test_demo_recipe_blueprint_roundtrip(self, fixtures_dir: Path) -> None:
        """demo_webcam_split_merge.yaml → Recipe → проверка blueprint."""
        recipe_path = fixtures_dir / "recipes" / "demo_webcam_split_merge.yaml"
        assert recipe_path.exists(), f"Файл не найден: {recipe_path}"

        raw = _load_yaml(recipe_path)

        # Recipe.from_dict поддерживает формат с name/version на верхнем уровне
        # display_bindings в формате v3 (node_id/display_id)
        recipe = Recipe.from_dict(raw)

        # Проверяем meta
        assert recipe.meta.name == "demo_webcam_split_merge"

        # Проверяем blueprint (processes)
        assert len(recipe.blueprint.processes) == 4
        process_names = [p.process_name for p in recipe.blueprint.processes]
        assert "capture_proc" in process_names
        assert "merge_proc" in process_names

        # Проверяем wires
        assert len(recipe.blueprint.wires) == 4

        # Проверяем active_services
        assert "webcam_camera" in recipe.active_services

    def test_demo_recipe_display_bindings_v3(self, fixtures_dir: Path) -> None:
        """display_bindings в формате v3 (node_id/display_id) загружаются напрямую.

        YAML использует ключи node_id/display_id — нормализация не требуется.
        DisplayInstance создаётся напрямую через from_dict.
        """
        recipe_path = fixtures_dir / "recipes" / "demo_webcam_split_merge.yaml"
        raw = _load_yaml(recipe_path)
        recipe = Recipe.from_dict(raw)

        assert len(recipe.display_bindings) == 2

        binding0 = recipe.display_bindings[0]
        assert binding0.node_id == "merge_proc.render_overlay.rendered_frame"
        assert binding0.display_id == "main"

        binding1 = recipe.display_bindings[1]
        assert binding1.node_id == "capture_proc.resize.frame"
        assert binding1.display_id == "debug"

    def test_legacy_source_display_format_rejected(self) -> None:
        """Устаревший формат display_bindings (source/display) отклоняется.

        Recipe.from_dict с ключами source/display вместо node_id/display_id
        вызывает ValidationError — forcing function для когерентности формата v3.
        """
        legacy_data = {
            "name": "legacy_test",
            "version": 3,
            "blueprint": {"processes": [], "wires": []},
            "display_bindings": [{"source": "proc.plugin.port", "display": "main"}],
        }
        with pytest.raises((ValidationError, EntityValidationError)):
            Recipe.from_dict(legacy_data)

    def test_demo_recipe_roundtrip_idempotent(self, fixtures_dir: Path) -> None:
        """Recipe.from_dict(raw) → to_dict() → from_dict() даёт те же ключевые поля."""
        recipe_path = fixtures_dir / "recipes" / "demo_webcam_split_merge.yaml"
        raw = _load_yaml(recipe_path)
        recipe1 = Recipe.from_dict(raw)

        # После to_dict() display_bindings уже в нормализованном формате (node_id/display_id)
        recipe_dict = recipe1.to_dict()
        recipe2 = Recipe.from_dict(recipe_dict)

        assert recipe2.meta.name == recipe1.meta.name
        assert len(recipe2.blueprint.processes) == len(recipe1.blueprint.processes)
        assert len(recipe2.blueprint.wires) == len(recipe1.blueprint.wires)
        assert len(recipe2.display_bindings) == len(recipe1.display_bindings)
        assert recipe2.display_bindings[0].node_id == recipe1.display_bindings[0].node_id
        assert recipe2.display_bindings[0].display_id == recipe1.display_bindings[0].display_id


# ==============================================================================
# Frozen behaviour
# ==============================================================================


class TestFrozenBehaviour:
    """Тесты frozen=True для entities."""

    def test_process_frozen(self) -> None:
        """Попытка мутации process_name → ValidationError (frozen=True)."""
        proc = Process(process_name="test_proc", plugins=())
        with pytest.raises((ValidationError, TypeError)):
            proc.process_name = "mutated"  # type: ignore[misc]

    def test_wire_frozen(self) -> None:
        """Попытка мутации Wire.source → ValidationError."""
        wire = Wire(source="a.plugin.port", target="b.plugin.port")
        with pytest.raises((ValidationError, TypeError)):
            wire.source = "mutated"  # type: ignore[misc]

    def test_topology_frozen(self) -> None:
        """Попытка мутации Topology.processes → ValidationError."""
        topo = Topology()
        with pytest.raises((ValidationError, TypeError)):
            topo.processes = ()  # type: ignore[misc]


# ==============================================================================
# extra="forbid"
# ==============================================================================


class TestExtraForbid:
    """Политика extra для entities: Wire=forbid; Process/PluginInstance сворачивают
    плоские runtime-поля runnable-формата в extras/metadata/config (без потери данных)."""

    def test_wire_extra_forbid(self) -> None:
        """Wire с unknown полем → ValidationError."""
        with pytest.raises(ValidationError):
            Wire(source="a", target="b", unknown_field="x")  # type: ignore[call-arg]

    def test_process_shorthand_folds_into_extras(self) -> None:
        """Pipeline-routing shorthand (source_target_fps) → в extras, не metadata (AU-2).

        Framework-blueprint читает эти ключи только из typed-поля/extras — в metadata они
        для бэкенда нем (тихая деградация после GUI round-trip).
        """
        p = Process(process_name="p", plugins=(), source_target_fps=25)  # type: ignore[call-arg]
        assert p.extras.get("source_target_fps") == 25
        assert "source_target_fps" not in p.metadata

    def test_process_opaque_flat_field_folds_into_metadata(self) -> None:
        """Неизвестный НЕ-shorthand ключ (телеметрия) → по-прежнему в metadata."""
        p = Process(process_name="p", plugins=(), telemetry_tag="cam-A")  # type: ignore[call-arg]
        assert p.metadata.get("telemetry_tag") == "cam-A"
        assert "telemetry_tag" not in p.extras

    def test_plugin_instance_extra_folds_into_config(self) -> None:
        """PluginInstance с плоским параметром (runnable-формат) → сворачивается в config."""
        pi = PluginInstance(plugin_name="blur", radius=5)  # type: ignore[call-arg]
        assert pi.config.get("radius") == 5


class TestInspectorEscapeHatchRoundtrip:
    """AU-2 / ADR-PMM-017 п.5: явный inspector-escape-hatch переживает GUI round-trip.

    До фикса домен-entity Process сворачивал плоский inspector в metadata, где
    infer_missing_inspectors его игнорирует (только тонкая настройка, не mode) →
    ручной {mode: fanin} стирался первым же GUI-save и деградировал в структурный join.
    Теперь inspector едет через extras и остаётся авторитетным.
    """

    def test_explicit_inspector_survives_load_save_in_extras(self) -> None:
        """Плоский inspector: {mode: fanin} → extras, переживает to_dict → from_dict."""
        proc = Process.from_dict(
            {
                "process_name": "draw",
                "plugins": [{"plugin_name": "overlay_draw"}],
                "inspector": {"mode": "fanin"},
            }
        )
        # На load — inspector осел в extras, НЕ в metadata
        assert proc.extras.get("inspector") == {"mode": "fanin"}
        assert "inspector" not in proc.metadata

        # Round-trip: сериализация → десериализация сохраняет escape-hatch в extras
        proc2 = Process.from_dict(proc.to_dict())
        assert proc2.extras.get("inspector") == {"mode": "fanin"}
        assert "inspector" not in proc2.metadata

    def test_explicit_extras_inspector_survives_roundtrip(self) -> None:
        """Явный extras: {inspector: ...} в рецепте не теряется (extras — typed-поле)."""
        proc = Process.from_dict(
            {
                "process_name": "draw",
                "extras": {"inspector": {"mode": "fanin", "timeout_sec": 2.0}},
            }
        )
        proc2 = Process.from_dict(proc.to_dict())
        assert proc2.extras["inspector"] == {"mode": "fanin", "timeout_sec": 2.0}

    def test_explicit_extras_wins_over_flat_shorthand(self) -> None:
        """Конфликт: явный extras.inspector имеет приоритет над плоским inspector."""
        proc = Process.from_dict(
            {
                "process_name": "draw",
                "inspector": {"mode": "join"},
                "extras": {"inspector": {"mode": "fanin"}},
            }
        )
        assert proc.extras["inspector"] == {"mode": "fanin"}

    def test_inspector_extras_authoritative_in_blueprint(self) -> None:
        """Домен-сериализованный extras.inspector авторитетен для framework-blueprint.

        Плоский inspector, пройдя через домен-entity, оседает в extras — и framework
        ProcessConfig читает его как escape-hatch (`as_generic_config._pick` /
        `infer_missing_inspectors`). Конструируем ProcessConfig из релевантных полей
        (в реальном пути process_class-нормализацию делает адаптер/unwrap).
        """
        from multiprocess_framework.modules.process_manager_module.topology.blueprint import (
            ProcessConfig,
        )

        proc_dict = Process.from_dict({"process_name": "draw", "inspector": {"mode": "fanin"}}).to_dict()
        assert proc_dict["extras"]["inspector"] == {"mode": "fanin"}

        pc = ProcessConfig(process_name=proc_dict["process_name"], extras=proc_dict["extras"])
        # extras.inspector виден framework как escape-hatch (typed inspector пуст)
        assert (pc.inspector or pc.extras.get("inspector")) == {"mode": "fanin"}


class TestRestartPolicyRoundtrip:
    """F1: плоский restart_policy — typed-поле домена, переживает round-trip и виден framework.

    До фикса домен сворачивал плоский restart_policy в metadata, откуда framework
    (as_generic_config берёт только typed-поле) его не читал → per-process авто-рестарт
    молча отключался при boot после GUI-save (живые camera_0 в phone_sketch/hikvision).
    """

    def test_flat_restart_policy_folds_into_typed_field(self) -> None:
        """Плоский restart_policy → typed-поле, НЕ metadata/extras."""
        proc = Process.from_dict(
            {
                "process_name": "camera_0",
                "restart_policy": {"enabled": True, "max_retries": 3, "backoff_sec": 2.0},
            }
        )
        assert proc.restart_policy == {"enabled": True, "max_retries": 3, "backoff_sec": 2.0}
        assert "restart_policy" not in proc.metadata
        assert "restart_policy" not in proc.extras

    def test_restart_policy_survives_roundtrip_and_visible_in_blueprint(self) -> None:
        """restart_policy переживает to_dict → from_dict и виден ProcessConfig (typed)."""
        from multiprocess_framework.modules.process_manager_module.topology.blueprint import (
            ProcessConfig,
        )

        proc = Process.from_dict({"process_name": "camera_0", "restart_policy": {"enabled": True, "max_retries": 3}})
        proc2 = Process.from_dict(proc.to_dict())
        assert proc2.restart_policy == {"enabled": True, "max_retries": 3}

        pc = ProcessConfig(process_name="camera_0", restart_policy=proc2.restart_policy)
        assert pc.restart_policy == {"enabled": True, "max_retries": 3}


class TestExtrasShorthandDriftGuard:
    """F4: _EXTRAS_SHORTHAND_KEYS — рукописное зеркало `_pick`-набора ProcessConfig.

    Cross-layer contract-тест (импорт framework разрешён слоями): новый `_pick`-ключ во
    framework, забытый в домене, тихо ушёл бы в metadata при зелёных тестах — здесь ловим.
    """

    # Pinned зеркало ключей ProcessConfig.as_generic_config._pick (blueprint.py:200-203).
    # При добавлении нового _pick-ключа во framework — обнови и этот набор, и домен.
    _PINNED_PICK_SET = frozenset({"chain_targets", "source_target_fps", "inspector", "io_peek"})

    def test_extras_shorthand_mirrors_pick_set(self) -> None:
        """_EXTRAS_SHORTHAND_KEYS + chain_targets (typed-поле домена) == _pick-набор."""
        from multiprocess_prototype.domain.entities.process import _EXTRAS_SHORTHAND_KEYS

        assert _EXTRAS_SHORTHAND_KEYS | {"chain_targets"} == self._PINNED_PICK_SET

    def test_shorthand_keys_are_real_process_config_fields(self) -> None:
        """Каждый shorthand-ключ — реальное поле ProcessConfig (ловит опечатку/ренейм)."""
        from multiprocess_framework.modules.process_manager_module.topology.blueprint import (
            ProcessConfig,
        )
        from multiprocess_prototype.domain.entities.process import _EXTRAS_SHORTHAND_KEYS

        assert _EXTRAS_SHORTHAND_KEYS <= set(ProcessConfig.model_fields)

    def test_pinned_pick_set_matches_process_config_fields(self) -> None:
        """Pinned _pick-набор целиком — поля ProcessConfig (детект дрейфа имён во framework)."""
        from multiprocess_framework.modules.process_manager_module.topology.blueprint import (
            ProcessConfig,
        )

        assert self._PINNED_PICK_SET <= set(ProcessConfig.model_fields)


# ==============================================================================
# Обязательные поля
# ==============================================================================


class TestMissingRequired:
    """Тесты на отсутствие обязательных полей.

    Проверяют реальное поведение API: entities бросают pydantic.ValidationError
    напрямую (domain-слой не оборачивает ошибки автоматически).
    EntityValidationError — утилита для consumers, не автоматический wrapper.
    """

    def test_process_missing_name(self) -> None:
        """Process без process_name → ValidationError (реальное поведение API)."""
        with pytest.raises(ValidationError):
            Process(plugins=())  # type: ignore[call-arg]

    def test_wire_missing_source(self) -> None:
        """Wire без source → ValidationError."""
        with pytest.raises(ValidationError):
            Wire(target="b")  # type: ignore[call-arg]

    def test_wire_missing_target(self) -> None:
        """Wire без target → ValidationError."""
        with pytest.raises(ValidationError):
            Wire(source="a")  # type: ignore[call-arg]

    def test_plugin_missing_name(self) -> None:
        """PluginInstance без plugin_name → ValidationError."""
        with pytest.raises(ValidationError):
            PluginInstance()  # type: ignore[call-arg]

    def test_entity_validation_error_wraps_pydantic(self) -> None:
        """EntityValidationError.from_pydantic() корректно оборачивает ValidationError."""
        try:
            Process(plugins=())  # type: ignore[call-arg]
        except ValidationError as exc:
            wrapped = EntityValidationError.from_pydantic(exc)
            assert isinstance(wrapped, EntityValidationError)
            assert wrapped.cause is exc
            assert str(exc) in str(wrapped)
        else:
            pytest.fail("ValidationError должен был быть брошен")


# ==============================================================================
# plugins is tuple
# ==============================================================================


class TestPluginsIsTuple:
    """Тесты что plugins хранится как tuple, не list."""

    def test_process_plugins_is_tuple_from_list(self) -> None:
        """Process(plugins=[PluginInstance(...)]) → plugins тип tuple."""
        plugin = PluginInstance(plugin_name="blur")
        proc = Process(process_name="p", plugins=[plugin])  # type: ignore[arg-type]
        assert isinstance(proc.plugins, tuple), f"ожидался tuple, получен {type(proc.plugins)}"

    def test_process_plugins_is_tuple_from_dict(self) -> None:
        """Process.from_dict({'plugins': [...]}) → plugins тип tuple."""
        proc = Process.from_dict(
            {
                "process_name": "p",
                "plugins": [{"plugin_name": "blur"}, {"plugin_name": "capture"}],
            }
        )
        assert isinstance(proc.plugins, tuple)
        assert len(proc.plugins) == 2
        assert all(isinstance(p, PluginInstance) for p in proc.plugins)

    def test_topology_collections_are_tuples(self) -> None:
        """Topology.processes, .wires, .displays — tuple, не list."""
        topo = Topology(
            processes=[Process(process_name="p", plugins=())],  # type: ignore[list-item]
            wires=[Wire(source="a", target="b")],  # type: ignore[list-item]
            displays=[DisplayInstance(node_id="n", display_id="d")],  # type: ignore[list-item]
        )
        assert isinstance(topo.processes, tuple)
        assert isinstance(topo.wires, tuple)
        assert isinstance(topo.displays, tuple)


# ==============================================================================
# to_dict / from_dict идемпотентность
# ==============================================================================


class TestToDictFromDictIdempotent:
    """Тесты идемпотентности to_dict / from_dict."""

    def test_process_with_plugin_roundtrip(self) -> None:
        """Process с одним PluginInstance: to_dict → from_dict идемпотентен."""
        plugin = PluginInstance(
            plugin_name="blur",
            config={"kernel_size": 5, "sigma": 1.0},
        )
        proc = Process(
            process_name="blur_proc",
            plugins=(plugin,),
            target_process="display_proc",
            description="Процесс размытия",
            protected=False,
            category="processing",
        )

        proc_dict = proc.to_dict()
        proc2 = Process.from_dict(proc_dict)

        assert proc2.process_name == proc.process_name
        assert proc2.target_process == proc.target_process
        assert proc2.description == proc.description
        assert proc2.protected == proc.protected
        assert proc2.category == proc.category
        assert len(proc2.plugins) == 1
        assert proc2.plugins[0].plugin_name == "blur"
        assert proc2.plugins[0].config == {"kernel_size": 5, "sigma": 1.0}
        assert isinstance(proc2.plugins, tuple)

    def test_wire_roundtrip(self) -> None:
        """Wire: to_dict → from_dict идемпотентен."""
        wire = Wire(
            source="proc_a.plugin_x.frame",
            target="proc_b.plugin_y.frame",
            src_dtype="ndarray",
            tgt_dtype="ndarray",
        )
        wire2 = Wire.from_dict(wire.to_dict())
        assert wire2.source == wire.source
        assert wire2.target == wire.target
        assert wire2.src_dtype == wire.src_dtype
        assert wire2.tgt_dtype == wire.tgt_dtype

    def test_wire_description_roundtrip(self) -> None:
        """Wire.description: round-trip lossless (Task C.0)."""
        wire = Wire(
            source="proc_a.plugin.port",
            target="proc_b.plugin.port",
            description="hello",
        )
        wire_dict = wire.to_dict()
        wire2 = Wire.from_dict(wire_dict)
        assert wire2.description == "hello"
        assert wire2 == wire

    def test_wire_description_default_empty(self) -> None:
        """Wire.description по умолчанию пустая строка."""
        wire = Wire(source="a", target="b")
        assert wire.description == ""
        wire2 = Wire.from_dict(wire.to_dict())
        assert wire2.description == ""

    def test_process_metadata_roundtrip(self) -> None:
        """Process.metadata: round-trip lossless с runtime-полями (Task C.0)."""
        proc = Process(
            process_name="capture_proc",
            metadata={"source_target_fps": 30.0, "custom": "x"},
        )
        proc_dict = proc.to_dict()
        proc2 = Process.from_dict(proc_dict)
        assert proc2.metadata == {"source_target_fps": 30.0, "custom": "x"}
        assert proc2.process_name == "capture_proc"

    def test_process_metadata_default_empty(self) -> None:
        """Process.metadata по умолчанию пустой dict."""
        proc = Process(process_name="p")
        assert proc.metadata == {}
        proc2 = Process.from_dict(proc.to_dict())
        assert proc2.metadata == {}

    def test_project_roundtrip(self) -> None:
        """Project: to_dict → from_dict идемпотентен."""
        topo = Topology(
            processes=(
                Process(
                    process_name="proc",
                    plugins=(PluginInstance(plugin_name="blur"),),
                ),
            ),
        )
        project = Project(topology=topo, active_recipe="my_recipe")
        project_dict = project.to_dict()
        project2 = Project.from_dict(project_dict)

        assert project2.active_recipe == "my_recipe"
        assert len(project2.topology.processes) == 1
        assert project2.topology.processes[0].process_name == "proc"


# ==============================================================================
# Topology.from_dict: whitelist / typo protection
# ==============================================================================


class TestTopologyFromDictWhitelist:
    """Тесты защиты whitelist в Topology.from_dict."""

    def test_topology_typo_field_raises(self) -> None:
        """Опечатка в ключе (proceses вместо processes) → ValidationError.

        extra='forbid' должен сработать через from_dict, а не молча поглотить опечатку.
        """
        with pytest.raises(ValidationError):
            Topology.from_dict({"proceses": [], "wires": [], "displays": []})

    def test_topology_meta_field_normalizes(self) -> None:
        """SystemBlueprint-поля name/description помещаются в metadata.

        Whitelist {"name", "description"} перемещается в Topology.metadata,
        не вызывая extra='forbid'.
        """
        topo = Topology.from_dict(
            {
                "processes": [],
                "wires": [],
                "displays": [],
                "name": "x",
                "description": "y",
            }
        )
        assert topo.metadata.get("name") == "x"
        assert topo.metadata.get("description") == "y"

    def test_topology_known_keys_no_metadata_shuffle(self) -> None:
        """Только known_keys → from_dict не трогает metadata."""
        topo = Topology.from_dict({"processes": [], "wires": [], "displays": []})
        assert topo.metadata == {}

    def test_topology_mixed_meta_and_typo_raises(self) -> None:
        """name (whitelist) + опечатка (вне whitelist) → ValidationError."""
        with pytest.raises(ValidationError):
            Topology.from_dict(
                {
                    "proceses": [],  # опечатка — не в known_keys и не в whitelist
                    "wires": [],
                    "displays": [],
                    "name": "x",
                }
            )


# ==============================================================================
# Frozen behaviour: PluginInstance, DisplayInstance, RecipeMeta, Recipe, Project
# ==============================================================================


class TestFrozenBehaviourExtended:
    """Frozen-тесты для entities, не охваченных TestFrozenBehaviour."""

    def test_plugin_instance_frozen(self) -> None:
        """Попытка мутации PluginInstance.plugin_name → TypeError (frozen=True)."""
        plugin = PluginInstance(plugin_name="blur")
        with pytest.raises((ValidationError, TypeError)):
            plugin.plugin_name = "mutated"  # type: ignore[misc]

    def test_display_instance_frozen(self) -> None:
        """Попытка мутации DisplayInstance.node_id → TypeError (frozen=True)."""
        display = DisplayInstance(node_id="n", display_id="d")
        with pytest.raises((ValidationError, TypeError)):
            display.node_id = "mutated"  # type: ignore[misc]

    def test_recipe_meta_frozen(self) -> None:
        """Попытка мутации RecipeMeta.name → TypeError (frozen=True)."""
        meta = RecipeMeta(name="my_recipe")
        with pytest.raises((ValidationError, TypeError)):
            meta.name = "mutated"  # type: ignore[misc]

    def test_recipe_frozen(self) -> None:
        """Попытка мутации Recipe.meta → TypeError (frozen=True)."""
        recipe = Recipe(meta=RecipeMeta(name="r"))
        with pytest.raises((ValidationError, TypeError)):
            recipe.meta = RecipeMeta(name="mutated")  # type: ignore[misc]

    def test_project_frozen(self) -> None:
        """Попытка мутации Project.active_recipe → TypeError (frozen=True)."""
        project = Project(topology=Topology(), active_recipe="r1")
        with pytest.raises((ValidationError, TypeError)):
            project.active_recipe = "mutated"  # type: ignore[misc]


# ==============================================================================
# Recipe: полный YAML round-trip (yaml.dump → yaml.safe_load → from_dict)
# ==============================================================================


@_SKIP_DEMO
class TestDemoRecipeYamlRoundtrip:
    """Полный YAML round-trip: entity → yaml.dump → yaml.safe_load → entity."""

    def test_demo_recipe_yaml_full_roundtrip(self, fixtures_dir: Path) -> None:
        """Полный round-trip через yaml.dump → yaml.safe_load подтверждает сохранность данных."""
        recipe_path = fixtures_dir / "recipes" / "demo_webcam_split_merge.yaml"
        assert recipe_path.exists(), f"Файл не найден: {recipe_path}"

        raw = _load_yaml(recipe_path)
        recipe1 = Recipe.from_dict(raw)

        # Сериализуем в dict → YAML-строку → обратно в dict → entity
        recipe_dict = recipe1.to_dict()
        yaml_str = yaml.dump(recipe_dict, allow_unicode=True, default_flow_style=False)
        reloaded_dict = yaml.safe_load(yaml_str)
        recipe2 = Recipe.from_dict(reloaded_dict)

        assert recipe2.meta.name == recipe1.meta.name
        assert len(recipe2.blueprint.processes) == len(recipe1.blueprint.processes)
        assert len(recipe2.blueprint.wires) == len(recipe1.blueprint.wires)
        assert len(recipe2.display_bindings) == len(recipe1.display_bindings)
        assert recipe2.display_bindings[0].node_id == recipe1.display_bindings[0].node_id
        assert recipe2.display_bindings[0].display_id == recipe1.display_bindings[0].display_id
        assert len(recipe2.active_services) == len(recipe1.active_services)


# ==============================================================================
# DisplayInstance: гибридный формат display_binding
# ==============================================================================


class TestDisplayInstanceHybridFormat:
    """Тест на гибридный формат display_binding (одновременно node_id и source)."""

    def test_display_binding_hybrid_node_id_and_source_raises(self) -> None:
        """DisplayInstance с node_id и source одновременно → ValidationError (extra='forbid').

        DisplayInstance принимает только нормализованный формат (node_id/display_id).
        Поле 'source' — устаревший live-формат, не разрешён в entity напрямую.
        """
        with pytest.raises(ValidationError):
            DisplayInstance(node_id="n", display_id="d", source="s")  # type: ignore[call-arg]


# ==============================================================================
# WorkerSpec + Process.workers (processes-workers-runtime)
# ==============================================================================


class TestWorkerSpec:
    """Тесты WorkerSpec entity и Process.workers."""

    def test_worker_spec_defaults(self) -> None:
        """WorkerSpec с одним именем — дефолты NORMAL/loop, не protected."""
        w = WorkerSpec(worker_name="grabber")
        assert w.worker_name == "grabber"
        assert w.priority == "NORMAL"
        assert w.execution_mode == "loop"
        assert w.target_interval_ms is None
        assert w.worker_class is None
        assert w.protected is False
        assert w.config == {}

    def test_worker_spec_roundtrip(self) -> None:
        """WorkerSpec: to_dict → from_dict идемпотентен (все поля)."""
        w = WorkerSpec(
            worker_name="inference",
            priority="REALTIME",
            execution_mode="loop",
            target_interval_ms=40,
            worker_class="pkg.mod.MyWorker",
            protected=False,
            description="ML инференс",
            config={"batch": 4},
        )
        w2 = WorkerSpec.from_dict(w.to_dict())
        assert w2 == w
        assert w2.priority == "REALTIME"
        assert w2.target_interval_ms == 40
        assert w2.config == {"batch": 4}

    def test_worker_spec_frozen(self) -> None:
        """WorkerSpec frozen — мутация поднимает ошибку."""
        w = WorkerSpec(worker_name="w")
        with pytest.raises((ValidationError, TypeError)):
            w.priority = "SYSTEM"  # type: ignore[misc]

    def test_worker_spec_invalid_priority_rejected(self) -> None:
        """Неизвестный priority → ValidationError (Literal)."""
        with pytest.raises(ValidationError):
            WorkerSpec(worker_name="w", priority="TURBO")  # type: ignore[arg-type]

    def test_worker_spec_extra_folds_into_config(self) -> None:
        """Плоское неизвестное поле сворачивается в config (passthrough)."""
        w = WorkerSpec(worker_name="w", custom_param=7)  # type: ignore[call-arg]
        assert w.config.get("custom_param") == 7

    def test_worker_spec_missing_name(self) -> None:
        """WorkerSpec без worker_name → ValidationError."""
        with pytest.raises(ValidationError):
            WorkerSpec()  # type: ignore[call-arg]

    def test_process_workers_default_empty_tuple(self) -> None:
        """Process.workers по умолчанию — пустой tuple."""
        proc = Process(process_name="p")
        assert proc.workers == ()
        assert isinstance(proc.workers, tuple)

    def test_process_workers_is_tuple_from_list(self) -> None:
        """Process(workers=[WorkerSpec(...)]) → workers тип tuple."""
        proc = Process(
            process_name="p",
            workers=[WorkerSpec(worker_name="w1")],  # type: ignore[arg-type]
        )
        assert isinstance(proc.workers, tuple)
        assert proc.workers[0].worker_name == "w1"

    def test_process_workers_roundtrip_from_dict(self) -> None:
        """Process.from_dict с workers как list[dict] → tuple[WorkerSpec]."""
        proc = Process.from_dict(
            {
                "process_name": "capture_proc",
                "plugins": [{"plugin_name": "capture"}],
                "workers": [
                    {"worker_name": "message_processor", "priority": "NORMAL", "protected": True},
                    {"worker_name": "grabber", "priority": "REALTIME", "target_interval_ms": 33},
                ],
            }
        )
        assert isinstance(proc.workers, tuple)
        assert len(proc.workers) == 2
        assert all(isinstance(w, WorkerSpec) for w in proc.workers)
        assert proc.workers[0].protected is True
        assert proc.workers[1].target_interval_ms == 33

        # Round-trip
        proc2 = Process.from_dict(proc.to_dict())
        assert len(proc2.workers) == 2
        assert proc2.workers[1].priority == "REALTIME"
        assert proc2.workers[0].worker_name == "message_processor"

    def test_process_with_workers_in_topology_roundtrip(self) -> None:
        """Topology с процессом, у которого есть workers — round-trip lossless."""
        topo = Topology(
            processes=(
                Process(
                    process_name="cam",
                    plugins=(PluginInstance(plugin_name="capture"),),
                    workers=(WorkerSpec(worker_name="grabber", priority="REALTIME", target_interval_ms=33),),
                ),
            ),
        )
        topo2 = Topology.from_dict(topo.to_dict())
        assert len(topo2.processes[0].workers) == 1
        assert topo2.processes[0].workers[0].worker_name == "grabber"
        assert topo2.processes[0].workers[0].priority == "REALTIME"


# ==============================================================================
# Project.from_topology factory (Task D.3)
# ==============================================================================


class TestProjectFromTopologyFactory:
    """Тесты factory-метода Project.from_topology (Task D.3)."""

    def test_project_from_topology_creates_with_active_recipe_none(self) -> None:
        """Project.from_topology(topology) создаёт Project без активного рецепта."""
        topology = Topology()
        project = Project.from_topology(topology)

        assert project.topology is topology
        assert project.active_recipe is None

    def test_project_from_topology_with_processes(self) -> None:
        """from_topology сохраняет processes из topology."""
        from multiprocess_prototype.domain import Process

        topology = Topology(
            processes=(Process(process_name="cam"),),
        )
        project = Project.from_topology(topology)

        assert project.topology is topology
        assert len(project.topology.processes) == 1
        assert project.topology.processes[0].process_name == "cam"
        assert project.active_recipe is None

    def test_project_from_topology_returns_frozen_project(self) -> None:
        """Project созданный через from_topology — frozen (нельзя мутировать)."""
        topology = Topology()
        project = Project.from_topology(topology)

        with pytest.raises((ValidationError, TypeError)):
            project.active_recipe = "mutated"  # type: ignore[misc]


# ==============================================================================
# DisplayDefinition: структура, frozen, extra="forbid", round-trip
# ==============================================================================


class TestDisplayDefinition:
    """Тесты entity DisplayDefinition (Task 1.1)."""

    def test_minimal_definition(self) -> None:
        """Минимальное определение: только id (обязательное поле)."""
        dd = DisplayDefinition(id="main")
        assert dd.id == "main"
        assert dd.name == ""
        assert dd.width == 1280
        assert dd.height == 720
        assert dd.format == "BGR"
        assert dd.fps_limit == 30.0
        assert dd.ring_buffer_blocks == 3
        assert dd.position == DisplayPosition(x=0, y=0)
        assert dd.fit == "contain"
        assert dd.scale == 100
        assert dd.rotate == 0
        assert dd.flip == "none"
        assert dd.crop is None

    def test_full_definition_roundtrip(self) -> None:
        """Полное определение: from_dict → to_dict round-trip идемпотентен."""
        data = {
            "id": "debug",
            "name": "Отладочный дисплей",
            "width": 640,
            "height": 480,
            "format": "RGB",
            "fps_limit": 15.0,
            "ring_buffer_blocks": 2,
            "position": {"x": 100, "y": 50},
            "fit": "cover",
            "scale": 200,
            "rotate": 90,
            "flip": "horizontal",
            "crop": {"x": 10, "y": 20, "w": 600, "h": 400},
        }
        dd = DisplayDefinition.from_dict(data)
        assert dd.id == "debug"
        assert dd.name == "Отладочный дисплей"
        assert dd.width == 640
        assert dd.position.x == 100
        assert dd.position.y == 50
        assert dd.fit == "cover"
        assert dd.scale == 200
        assert dd.rotate == 90
        assert dd.flip == "horizontal"
        assert dd.crop is not None
        assert dd.crop.x == 10
        assert dd.crop.w == 600

        # Round-trip: to_dict → from_dict
        d2 = dd.to_dict()
        dd2 = DisplayDefinition.from_dict(d2)
        assert dd2.to_dict() == d2

    def test_extra_field_raises(self) -> None:
        """DisplayDefinition с лишним полем → ValidationError (extra='forbid')."""
        with pytest.raises(ValidationError):
            DisplayDefinition(id="x", unknown_field="bad")  # type: ignore[call-arg]

    def test_missing_id_raises(self) -> None:
        """DisplayDefinition без id → ValidationError."""
        with pytest.raises(ValidationError):
            DisplayDefinition()  # type: ignore[call-arg]

    def test_frozen(self) -> None:
        """DisplayDefinition frozen — мутация бросает ошибку."""
        dd = DisplayDefinition(id="main")
        with pytest.raises((ValidationError, TypeError)):
            dd.name = "mutated"  # type: ignore[misc]

    def test_crop_none(self) -> None:
        """crop: null → None."""
        dd = DisplayDefinition.from_dict({"id": "x", "crop": None})
        assert dd.crop is None

    def test_crop_as_dict(self) -> None:
        """crop: dict → DisplayCrop."""
        dd = DisplayDefinition.from_dict({"id": "x", "crop": {"x": 0, "y": 0, "w": 100, "h": 100}})
        assert isinstance(dd.crop, DisplayCrop)
        assert dd.crop.w == 100

    def test_position_absent_default(self) -> None:
        """position отсутствует → default {0, 0}."""
        dd = DisplayDefinition.from_dict({"id": "x"})
        assert dd.position.x == 0
        assert dd.position.y == 0

    def test_position_as_dict(self) -> None:
        """position: dict → DisplayPosition."""
        dd = DisplayDefinition.from_dict({"id": "x", "position": {"x": 42, "y": 7}})
        assert isinstance(dd.position, DisplayPosition)
        assert dd.position.x == 42
        assert dd.position.y == 7

    def test_to_dict_produces_plain_dict(self) -> None:
        """to_dict возвращает чистый dict (Dict-at-Boundary)."""
        dd = DisplayDefinition(id="main", crop=DisplayCrop(x=1, y=2, w=3, h=4))
        d = dd.to_dict()
        assert isinstance(d, dict)
        assert isinstance(d["position"], dict)
        assert isinstance(d["crop"], dict)
        # Нет Pydantic-объектов
        assert d["crop"] == {"x": 1, "y": 2, "w": 3, "h": 4}


# ==============================================================================
# Recipe.displays: секция определений дисплеев (Task 1.1)
# ==============================================================================


class TestRecipeDisplays:
    """Тесты поля Recipe.displays (tuple[DisplayDefinition, ...])."""

    def _make_recipe_data(self, displays: list[dict] | None = None) -> dict:
        """Вспомогательный: минимальный dict рецепта с optional displays."""
        data: dict[str, Any] = {
            "name": "test_recipe",
            "version": 3,
            "blueprint": {"processes": [], "wires": []},
        }
        if displays is not None:
            data["displays"] = displays
        return data

    def test_recipe_with_displays_from_dict(self) -> None:
        """Recipe.from_dict с секцией displays создаёт DisplayDefinition."""
        data = self._make_recipe_data(displays=[{"id": "main", "width": 1920}])
        recipe = Recipe.from_dict(data)
        assert len(recipe.displays) == 1
        assert recipe.displays[0].id == "main"
        assert recipe.displays[0].width == 1920

    def test_recipe_displays_empty_section(self) -> None:
        """Пустая секция displays → пустой tuple."""
        recipe = Recipe.from_dict(self._make_recipe_data(displays=[]))
        assert recipe.displays == ()

    def test_recipe_displays_absent(self) -> None:
        """Отсутствующая секция displays → пустой tuple (default)."""
        recipe = Recipe.from_dict(self._make_recipe_data(displays=None))
        assert recipe.displays == ()

    def test_recipe_displays_roundtrip_idempotent(self) -> None:
        """Recipe с displays: from_dict → to_dict → from_dict идемпотентен."""
        displays_data = [
            {"id": "main", "name": "Основной", "width": 1280, "height": 720},
            {
                "id": "debug",
                "name": "Отладочный",
                "width": 640,
                "height": 480,
                "crop": {"x": 0, "y": 0, "w": 640, "h": 480},
            },
        ]
        data = self._make_recipe_data(displays=displays_data)
        recipe1 = Recipe.from_dict(data)
        recipe_dict = recipe1.to_dict()
        recipe2 = Recipe.from_dict(recipe_dict)

        assert len(recipe2.displays) == 2
        assert recipe2.displays[0].id == "main"
        assert recipe2.displays[1].id == "debug"
        assert recipe2.displays[1].crop is not None
        assert recipe2.displays[1].crop.w == 640
        # Полная идемпотентность dict
        assert recipe2.to_dict() == recipe_dict

    def test_recipe_to_dict_displays_is_list_of_dicts(self) -> None:
        """to_dict()["displays"] — list[dict] (Dict-at-Boundary)."""
        data = self._make_recipe_data(displays=[{"id": "main"}])
        recipe = Recipe.from_dict(data)
        out = recipe.to_dict()
        assert isinstance(out["displays"], list)
        assert isinstance(out["displays"][0], dict)
        assert out["displays"][0]["id"] == "main"

    def test_recipe_displays_not_in_meta_delete_list(self) -> None:
        """top-level 'displays' НЕ удаляется как meta-поле в from_dict."""
        data = {
            "name": "test",
            "version": 3,
            "displays": [{"id": "main"}],
            "blueprint": {"processes": [], "wires": []},
        }
        recipe = Recipe.from_dict(data)
        assert len(recipe.displays) == 1

    def test_recipe_displays_coexist_with_display_bindings(self) -> None:
        """displays (определения) и display_bindings (привязки) сосуществуют."""
        data = {
            "name": "coexist",
            "version": 3,
            "displays": [{"id": "main", "name": "Основной"}],
            "display_bindings": [{"node_id": "proc.plug.frame", "display_id": "main"}],
            "blueprint": {"processes": [], "wires": []},
        }
        recipe = Recipe.from_dict(data)
        assert len(recipe.displays) == 1
        assert recipe.displays[0].id == "main"
        assert len(recipe.display_bindings) == 1
        assert recipe.display_bindings[0].display_id == "main"

    def test_recipe_displays_crop_null_roundtrip(self) -> None:
        """crop: null в определении → None, round-trip сохраняется."""
        data = self._make_recipe_data(displays=[{"id": "x", "crop": None}])
        recipe = Recipe.from_dict(data)
        assert recipe.displays[0].crop is None
        out = recipe.to_dict()
        assert out["displays"][0]["crop"] is None


# ==============================================================================
# DisplayDefinition field_validators (Task 1.2)
# ==============================================================================


class TestDisplayDefinitionValidators:
    """Тесты field_validator'ов DisplayDefinition (Task 1.2).

    Проверяет инварианты: scale [10..1000], rotate {0/90/180/270},
    flip/fit/format — enum.
    """

    # scale
    def test_scale_minimum_valid(self) -> None:
        """scale=10 — минимально допустимое значение."""
        dd = DisplayDefinition(id="x", scale=10)
        assert dd.scale == 10

    def test_scale_maximum_valid(self) -> None:
        """scale=1000 — максимально допустимое значение."""
        dd = DisplayDefinition(id="x", scale=1000)
        assert dd.scale == 1000

    def test_scale_default_valid(self) -> None:
        """scale=100 (по умолчанию) — корректен."""
        dd = DisplayDefinition(id="x")
        assert dd.scale == 100

    def test_scale_below_minimum_raises(self) -> None:
        """scale=5 → ValueError с упоминанием значения."""
        with pytest.raises(ValidationError) as exc_info:
            DisplayDefinition(id="x", scale=5)
        assert "5" in str(exc_info.value)

    def test_scale_zero_raises(self) -> None:
        """scale=0 → ValueError (кадр не виден)."""
        with pytest.raises(ValidationError):
            DisplayDefinition(id="x", scale=0)

    def test_scale_above_maximum_raises(self) -> None:
        """scale=1001 → ValueError."""
        with pytest.raises(ValidationError):
            DisplayDefinition(id="x", scale=1001)

    # rotate
    def test_rotate_valid_values(self) -> None:
        """rotate ∈ {0, 90, 180, 270} — все допустимы."""
        for angle in (0, 90, 180, 270):
            dd = DisplayDefinition(id="x", rotate=angle)
            assert dd.rotate == angle

    def test_rotate_invalid_raises(self) -> None:
        """rotate=45 → ValueError."""
        with pytest.raises(ValidationError) as exc_info:
            DisplayDefinition(id="x", rotate=45)
        assert "45" in str(exc_info.value)

    def test_rotate_negative_raises(self) -> None:
        """rotate=-90 → ValueError."""
        with pytest.raises(ValidationError):
            DisplayDefinition(id="x", rotate=-90)

    # flip
    def test_flip_valid_values(self) -> None:
        """flip ∈ {none, horizontal, vertical, both} — все допустимы."""
        for val in ("none", "horizontal", "vertical", "both"):
            dd = DisplayDefinition(id="x", flip=val)
            assert dd.flip == val

    def test_flip_invalid_raises(self) -> None:
        """flip='mirror' → ValueError."""
        with pytest.raises(ValidationError) as exc_info:
            DisplayDefinition(id="x", flip="mirror")
        assert "mirror" in str(exc_info.value)

    def test_flip_empty_string_raises(self) -> None:
        """flip='' → ValueError."""
        with pytest.raises(ValidationError):
            DisplayDefinition(id="x", flip="")

    # fit
    def test_fit_valid_values(self) -> None:
        """fit ∈ {contain, cover, stretch, none} — все допустимы."""
        for val in ("contain", "cover", "stretch", "none"):
            dd = DisplayDefinition(id="x", fit=val)
            assert dd.fit == val

    def test_fit_invalid_raises(self) -> None:
        """fit='fill' → ValueError."""
        with pytest.raises(ValidationError) as exc_info:
            DisplayDefinition(id="x", fit="fill")
        assert "fill" in str(exc_info.value)

    # format
    def test_format_valid_values(self) -> None:
        """format ∈ {BGR, RGB, GRAY, RGBA} — все допустимы."""
        for val in ("BGR", "RGB", "GRAY", "RGBA"):
            dd = DisplayDefinition(id="x", format=val)
            assert dd.format == val

    def test_format_invalid_raises(self) -> None:
        """format='YUV' → ValueError."""
        with pytest.raises(ValidationError) as exc_info:
            DisplayDefinition(id="x", format="YUV")
        assert "YUV" in str(exc_info.value)

    def test_format_lowercase_raises(self) -> None:
        """format='bgr' (строчные) → ValueError (case-sensitive)."""
        with pytest.raises(ValidationError):
            DisplayDefinition(id="x", format="bgr")


# ==============================================================================
# Recipe инварианты уникальности и валидации ссылок (Task 1.2)
# ==============================================================================


class TestRecipeInvariants:
    """Тесты @model_validator Recipe: уникальность displays[].id
    и валидация ссылок blueprint.displays[].display_id.
    """

    def _make_recipe(
        self,
        displays: list[dict] | None = None,
        blueprint_displays: list[dict] | None = None,
    ) -> dict:
        """Вспомогательный: минимальный dict рецепта."""
        bp: dict[str, Any] = {"processes": [], "wires": []}
        if blueprint_displays is not None:
            bp["displays"] = blueprint_displays
        data: dict[str, Any] = {
            "name": "test",
            "version": 3,
            "blueprint": bp,
        }
        if displays is not None:
            data["displays"] = displays
        return data

    # --- уникальность id ---

    def test_duplicate_display_id_raises(self) -> None:
        """Два дисплея с одинаковым id → ValueError с упоминанием id."""
        data = self._make_recipe(displays=[{"id": "main"}, {"id": "main"}])
        with pytest.raises(ValidationError) as exc_info:
            Recipe.from_dict(data)
        assert "main" in str(exc_info.value)

    def test_unique_display_ids_ok(self) -> None:
        """Два дисплея с разными id → ok."""
        data = self._make_recipe(displays=[{"id": "main"}, {"id": "debug"}])
        recipe = Recipe.from_dict(data)
        assert len(recipe.displays) == 2

    def test_single_display_id_ok(self) -> None:
        """Один дисплей → ok."""
        data = self._make_recipe(displays=[{"id": "main"}])
        recipe = Recipe.from_dict(data)
        assert recipe.displays[0].id == "main"

    def test_empty_displays_ok(self) -> None:
        """Пустая секция displays (без привязок) → ok."""
        data = self._make_recipe(displays=[])
        recipe = Recipe.from_dict(data)
        assert recipe.displays == ()

    # --- валидация ссылок ---

    def test_dangling_display_id_in_blueprint_raises(self) -> None:
        """blueprint.displays ссылается на несуществующий display_id → ValueError."""
        data = self._make_recipe(
            displays=[],
            blueprint_displays=[{"node_id": "proc.plug.frame", "display_id": "ghost"}],
        )
        with pytest.raises(ValidationError) as exc_info:
            Recipe.from_dict(data)
        assert "ghost" in str(exc_info.value)

    def test_valid_display_reference_ok(self) -> None:
        """blueprint.displays ссылается на существующий display_id → ok."""
        data = self._make_recipe(
            displays=[{"id": "main"}],
            blueprint_displays=[{"node_id": "proc.plug.frame", "display_id": "main"}],
        )
        recipe = Recipe.from_dict(data)
        assert recipe.blueprint.displays[0].display_id == "main"

    def test_no_blueprint_bindings_ok(self) -> None:
        """Нет привязок в blueprint → ok (дисплей без привязки допустим)."""
        data = self._make_recipe(
            displays=[{"id": "main"}],
            blueprint_displays=[],
        )
        recipe = Recipe.from_dict(data)
        assert recipe.blueprint.displays == ()
        assert recipe.displays[0].id == "main"

    def test_empty_displays_with_bindings_raises(self) -> None:
        """displays пуст + есть привязки → ошибка (висячие ссылки)."""
        data = self._make_recipe(
            displays=[],
            blueprint_displays=[{"node_id": "proc.plug.frame", "display_id": "main"}],
        )
        with pytest.raises(ValidationError):
            Recipe.from_dict(data)

    def test_multiple_bindings_one_dangling_raises(self) -> None:
        """Одна корректная + одна висячая ссылка → ValueError с указанием проблемного id."""
        data = self._make_recipe(
            displays=[{"id": "main"}],
            blueprint_displays=[
                {"node_id": "proc.plug.frame1", "display_id": "main"},
                {"node_id": "proc.plug.frame2", "display_id": "missing"},
            ],
        )
        with pytest.raises(ValidationError) as exc_info:
            Recipe.from_dict(data)
        assert "missing" in str(exc_info.value)

    def test_multiple_valid_bindings_ok(self) -> None:
        """Несколько корректных привязок к разным дисплеям → ok."""
        data = self._make_recipe(
            displays=[{"id": "main"}, {"id": "debug"}],
            blueprint_displays=[
                {"node_id": "proc.plug.frame1", "display_id": "main"},
                {"node_id": "proc.plug.frame2", "display_id": "debug"},
            ],
        )
        recipe = Recipe.from_dict(data)
        assert len(recipe.blueprint.displays) == 2
