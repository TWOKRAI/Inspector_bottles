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
    DisplayInstance,
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
    плоские runtime-поля runnable-формата в metadata/config (без потери данных)."""

    def test_wire_extra_forbid(self) -> None:
        """Wire с unknown полем → ValidationError."""
        with pytest.raises(ValidationError):
            Wire(source="a", target="b", unknown_field="x")  # type: ignore[call-arg]

    def test_process_extra_folds_into_metadata(self) -> None:
        """Process с плоским runtime-полем (runnable-формат) → сворачивается в metadata."""
        p = Process(process_name="p", plugins=(), source_target_fps=25)  # type: ignore[call-arg]
        assert p.metadata.get("source_target_fps") == 25

    def test_plugin_instance_extra_folds_into_config(self) -> None:
        """PluginInstance с плоским параметром (runnable-формат) → сворачивается в config."""
        pi = PluginInstance(plugin_name="blur", radius=5)  # type: ignore[call-arg]
        assert pi.config.get("radius") == 5


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
