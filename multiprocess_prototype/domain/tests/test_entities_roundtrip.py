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
    Topology,
    Wire,
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
        # и live-формат display_bindings (source/display)
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

    def test_demo_recipe_display_bindings_normalized(self, fixtures_dir: Path) -> None:
        """display_bindings из live-формата (source/display) корректно нормализуются.

        Live-формат YAML использует ключи source/display (не node_id/display_id).
        Recipe.from_dict() выполняет нормализацию через _normalize_display_binding().
        После нормализации DisplayInstance имеет node_id и display_id.

        TODO(Phase F): Удалить поддержку live-формата после миграции рецептов.
        """
        recipe_path = fixtures_dir / "recipes" / "demo_webcam_split_merge.yaml"
        raw = _load_yaml(recipe_path)
        recipe = Recipe.from_dict(raw)

        assert len(recipe.display_bindings) == 2

        binding0 = recipe.display_bindings[0]
        # node_id соответствует полю source из live-формата
        assert binding0.node_id == "merge_proc.render_overlay.rendered_frame"
        assert binding0.display_id == "main_output"

        binding1 = recipe.display_bindings[1]
        assert binding1.node_id == "capture_proc.resize.frame"
        assert binding1.display_id == "debug_input"

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
    """Тесты extra='forbid' для entities."""

    def test_wire_extra_forbid(self) -> None:
        """Wire с unknown полем → ValidationError."""
        with pytest.raises(ValidationError):
            Wire(source="a", target="b", unknown_field="x")  # type: ignore[call-arg]

    def test_process_extra_forbid(self) -> None:
        """Process с неизвестным полем → ValidationError."""
        with pytest.raises(ValidationError):
            Process(process_name="p", plugins=(), unknown="x")  # type: ignore[call-arg]

    def test_plugin_instance_extra_forbid(self) -> None:
        """PluginInstance с неизвестным полем → ValidationError."""
        with pytest.raises(ValidationError):
            PluginInstance(plugin_name="blur", extra_field="x")  # type: ignore[call-arg]


# ==============================================================================
# Обязательные поля
# ==============================================================================


class TestMissingRequired:
    """Тесты на отсутствие обязательных полей."""

    def test_process_missing_name(self) -> None:
        """Process без process_name → EntityValidationError."""
        with pytest.raises((EntityValidationError, ValidationError)):
            try:
                Process(plugins=())  # type: ignore[call-arg]
            except ValidationError as exc:
                raise EntityValidationError.from_pydantic(exc) from exc

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
