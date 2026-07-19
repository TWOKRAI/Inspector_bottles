"""Тесты слияния фундамент ⊕ presentation ⊕ pipeline (launch.merge_topologies).

Ф2 frontend-constructor (2026-07): презентация (`gui`) вынесена из обязательного
фундамента (`base.yaml`) в отдельный overlay (`frontend/presentation.yaml`).
Гарантируют: base.yaml — headless-only (без gui), presentation-overlay даёт gui,
merge(base, presentation) добавляет gui ровно один раз, chain_targets:[gui]
резолвится после полного слияния (base ⊕ presentation ⊕ pipeline).
"""

from pathlib import Path

import pytest
import yaml

from multiprocess_framework.modules.process_manager_module.topology.blueprint import SystemBlueprint
from multiprocess_prototype.backend.launch import merge_topologies, unwrap_recipe

TOPOLOGY_DIR = Path(__file__).resolve().parents[1]
BASE_PATH = TOPOLOGY_DIR / "base.yaml"
# gui-overlay переехал из base.yaml во frontend/presentation.yaml (Ф2).
PRESENTATION_PATH = Path(__file__).resolve().parents[3] / "frontend" / "presentation.yaml"
# region_pipeline переехал в recipes/ (запускаемый рецепт) — грузим через unwrap_recipe.
RECIPE_REGION = Path(__file__).resolve().parents[3] / "recipes" / "region_pipeline.yaml"

ACTIVE_PIPELINES = [
    "hello_world.yaml",
    "inspection_basic.yaml",
    "inspection_full.yaml",
    "multi_camera.yaml",
]

GUI_CLASS = "multiprocess_prototype.frontend.process.GuiProcess"


def _load(name: str) -> dict:
    with open(TOPOLOGY_DIR / name, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _load_region_pipeline() -> dict:
    """region_pipeline теперь рецепт — разворачиваем blueprint: в топологию."""
    with open(RECIPE_REGION, encoding="utf-8") as f:
        return unwrap_recipe(yaml.safe_load(f))


def _base() -> dict:
    with open(BASE_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _presentation() -> dict:
    with open(PRESENTATION_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _base_with_presentation() -> dict:
    """Полный фундамент с включённой презентацией: base ⊕ presentation."""
    return merge_topologies(_base(), _presentation())


class TestBaseMerge:
    """Контракт merge_topologies: фундамент ⊕ presentation-overlay ⊕ pipeline."""

    def test_base_is_headless_infra_only(self):
        """base.yaml — headless-only фундамент: только always-on инфра (devices),
        БЕЗ презентации (Ф2 — gui вынесен в overlay)."""
        base = _base()
        names = {p["process_name"] for p in base["processes"]}
        assert "gui" not in names, "gui должен быть вынесен в presentation-overlay"
        assert "devices" in names

    def test_presentation_overlay_provides_gui_process(self):
        """Презентационный overlay содержит процесс презентации `gui` (класс GuiProcess)."""
        presentation = _presentation()
        gui = next((p for p in presentation["processes"] if p["process_name"] == "gui"), None)
        assert gui is not None, "presentation.yaml должен содержать процесс gui"
        assert gui["process_class"] == GUI_CLASS

    def test_base_plus_presentation_adds_gui_once(self):
        """merge(base, presentation): gui добавлен из overlay ровно один раз,
        always-on инфра фундамента (devices) сохранена."""
        merged = _base_with_presentation()
        names = [p["process_name"] for p in merged["processes"]]
        assert names.count("gui") == 1
        assert "devices" in names
        gui = next(p for p in merged["processes"] if p["process_name"] == "gui")
        assert gui["process_class"] == GUI_CLASS

    def test_pipelines_have_no_gui(self):
        """Pipeline-топологии не объявляют gui (он в presentation-overlay)."""
        for name in ACTIVE_PIPELINES:
            names = {p["process_name"] for p in _load(name)["processes"]}
            assert "gui" not in names, f"{name}: gui должен приходить из presentation-overlay"

    @pytest.mark.parametrize("name", ACTIVE_PIPELINES)
    def test_merge_adds_gui_preserves_pipeline(self, name):
        """merge(base⊕presentation, pipeline): gui добавлен из overlay ровно один раз,
        все процессы pipeline сохранены."""
        pipeline = _load(name)
        merged = merge_topologies(_base_with_presentation(), pipeline)
        names = [p["process_name"] for p in merged["processes"]]
        assert names.count("gui") == 1, f"{name}: gui должен быть ровно один"
        gui = next(p for p in merged["processes"] if p["process_name"] == "gui")
        assert gui["process_class"] == GUI_CLASS
        for p in pipeline["processes"]:
            assert p["process_name"] in names, f"{name}: процесс {p['process_name']} потерян при merge"

    def test_region_pipeline_merge_golden_build(self):
        """Golden: merge(base⊕presentation, region_pipeline) собирается в configs;
        gui (из overlay) присутствует ровно один раз с классом GuiProcess."""
        merged = merge_topologies(_base_with_presentation(), _load_region_pipeline())
        configs = SystemBlueprint.model_validate(merged).build_configs()
        names = [c.process_name for c in configs]
        assert names.count("gui") == 1
        assert next(c for c in configs if c.process_name == "gui").process_class == GUI_CLASS

    def test_chain_targets_gui_resolves_after_merge(self):
        """chain_targets:[gui] из pipeline резолвится после полного слияния
        (base ⊕ presentation ⊕ pipeline)."""
        merged = merge_topologies(_base_with_presentation(), _load_region_pipeline())
        names = {p["process_name"] for p in merged["processes"]}
        for proc in merged["processes"]:
            for target in proc.get("chain_targets", []):
                assert target in names, f"chain_target '{target}' не резолвится в merged"

    def test_base_plus_pipeline_without_presentation_is_headless(self):
        """Полный фундамент (base, БЕЗ presentation) ⊕ pipeline собирается без gui —
        headless по умолчанию (аналог test_pipeline_alone_is_headless, но с фундаментом:
        полный манифест без presentation даёт configs без процесса gui)."""
        merged = merge_topologies(_base(), _load_region_pipeline())
        configs = SystemBlueprint.model_validate(merged).build_configs()
        names = {c.process_name for c in configs}
        assert "gui" not in names
        assert "devices" in names
        assert "camera_0" in names and "stitcher" in names

    def test_merge_dedupes_on_collision_base_wins(self):
        """Если pipeline тоже объявляет gui — побеждает фундамент (dedupe).

        base здесь = base ⊕ presentation (полный фундамент с включённой презентацией) —
        overlay мёржится ПЕРЕД pipeline, поэтому именно overlay должен победить.
        """
        base = _base_with_presentation()
        pipeline = {
            "name": "dup",
            "processes": [
                {"process_name": "cam", "plugins": []},
                {"process_name": "gui", "process_class": "other.Class", "plugins": []},
            ],
        }
        merged = merge_topologies(base, pipeline)
        guis = [p for p in merged["processes"] if p["process_name"] == "gui"]
        assert len(guis) == 1, "gui не должен дублироваться"
        assert guis[0]["process_class"] == GUI_CLASS, "должен победить presentation-overlay"

    def test_merge_preserves_pipeline_name(self):
        """Результат берёт name/description из pipeline (активная нагрузка)."""
        merged = merge_topologies(_base(), _load_region_pipeline())
        assert merged["name"] == "region_pipeline"

    def test_pipeline_alone_is_headless(self):
        """Headless: pipeline без фундамента собирается без процесса презентации,
        цепочка обработки сохраняется (бэкенд работает без GUI)."""
        configs = SystemBlueprint.model_validate(_load_region_pipeline()).build_configs()
        names = {c.process_name for c in configs}
        assert "gui" not in names
        assert "camera_0" in names and "stitcher" in names

    def test_protected_survives_merge_and_build(self):
        """Регрессия У1 (device-hub): protected: true из base.yaml переживает
        merge → SystemBlueprint → build → proc_dict["protected"] == True.

        Сценарий: base={gui(protected), devices(protected)} + pipeline={worker}.
        """
        base = {
            "name": "base",
            "processes": [
                {"process_name": "gui", "protected": True, "process_class": GUI_CLASS, "plugins": []},
                {
                    "process_name": "devices",
                    "protected": True,
                    "process_class": "multiprocess_prototype.generic_process_app.GenericProcessApp",
                    "plugins": [],
                },
            ],
            "wires": [],
        }
        pipeline = {
            "name": "test_pipeline",
            "processes": [
                {
                    "process_name": "worker",
                    "process_class": "multiprocess_prototype.generic_process_app.GenericProcessApp",
                    "plugins": [],
                },
            ],
            "wires": [],
        }
        merged = merge_topologies(base, pipeline)
        by_name = {p["process_name"]: p for p in merged["processes"]}
        assert by_name["gui"]["protected"] is True
        assert by_name["devices"]["protected"] is True
        assert by_name["worker"].get("protected") in (None, False)

        # Через SystemBlueprint → build → proc_dict
        sb = SystemBlueprint.model_validate(merged)
        protected_flags = {}
        for cfg in sb.build_configs():
            name, proc_dict = cfg.build()
            protected_flags[name] = proc_dict.get("protected", False)
        assert protected_flags["gui"] is True
        assert protected_flags["devices"] is True
        assert protected_flags["worker"] is False

    def test_real_presentation_yaml_protected_gui(self):
        """Реальный presentation.yaml: gui помечен protected, флаг доезжает до
        proc_dict через полное слияние (base ⊕ presentation ⊕ pipeline)."""
        presentation = _presentation()
        gui_proc = next(p for p in presentation["processes"] if p["process_name"] == "gui")
        assert gui_proc.get("protected") is True
        # Через build
        merged = merge_topologies(_base_with_presentation(), _load_region_pipeline())
        sb = SystemBlueprint.model_validate(merged)
        for cfg in sb.build_configs():
            if cfg.process_name == "gui":
                _name, proc_dict = cfg.build()
                assert proc_dict["protected"] is True
                break
        else:
            pytest.fail("gui не найден в build_configs")


class TestUnwrapRecipe:
    """Контракт unwrap_recipe: рецепт (editor-слой) → запускаемая топология."""

    def test_recipe_unwrapped_to_blueprint(self):
        recipe = {
            "name": "r",
            "version": 3,
            "blueprint": {"name": "r", "processes": [{"process_name": "p", "plugins": []}], "wires": []},
        }
        topo = unwrap_recipe(recipe)
        assert topo["name"] == "r"
        assert [p["process_name"] for p in topo["processes"]] == ["p"]

    def test_raw_topology_passthrough(self):
        # Сырая topology (processes на верхнем уровне) НЕ трогается (backward-compat).
        raw = {"name": "t", "processes": [{"process_name": "x", "plugins": []}]}
        assert unwrap_recipe(raw) is raw

    def test_display_bindings_folded_into_displays(self):
        recipe = {
            "blueprint": {"name": "r", "processes": [], "wires": []},
            "display_bindings": [{"node_id": "p.plug.frame", "display_id": "main"}],
        }
        topo = unwrap_recipe(recipe)
        assert topo["displays"] == [{"node_id": "p.plug.frame", "display_id": "main"}]

    def test_real_region_pipeline_recipe_carries_params(self):
        # Реальный рецепт region_pipeline разворачивается с сохранением параметров плагинов.
        topo = _load_region_pipeline()
        rs = next(p for proc in topo["processes"] for p in proc["plugins"] if p["plugin_name"] == "region_split")
        assert len(rs["regions"]) == 2 and rs["default_region"]["target"] == "process_flip"

    def test_unwrap_lifts_displays_to_display_definitions(self):
        """top-level displays рецепта → display_definitions в результате (Dict-at-Boundary)."""
        recipe = {
            "name": "r",
            "version": 3,
            "displays": [{"id": "main", "width": 1920}],
            "blueprint": {"name": "r", "processes": [], "wires": []},
        }
        topo = unwrap_recipe(recipe)
        assert "display_definitions" in topo
        assert topo["display_definitions"] == [{"id": "main", "width": 1920}]

    def test_unwrap_no_displays_no_key(self):
        """Рецепт без displays → ключ display_definitions отсутствует."""
        recipe = {
            "name": "r",
            "version": 3,
            "blueprint": {"name": "r", "processes": [], "wires": []},
        }
        topo = unwrap_recipe(recipe)
        assert "display_definitions" not in topo

    def test_unwrap_empty_displays_no_key(self):
        """Рецепт с пустым displays=[] → ключ display_definitions отсутствует (falsy)."""
        recipe = {
            "name": "r",
            "version": 3,
            "displays": [],
            "blueprint": {"name": "r", "processes": [], "wires": []},
        }
        topo = unwrap_recipe(recipe)
        assert "display_definitions" not in topo


class TestMergeDisplayDefinitions:
    """Тесты merge_topologies для display_definitions (Task 1.1)."""

    def test_merge_concatenates_display_definitions(self):
        """display_definitions суммируются из base и pipeline."""
        base = {
            "processes": [],
            "display_definitions": [{"id": "base_disp", "width": 640}],
        }
        pipeline = {
            "name": "pipe",
            "processes": [],
            "display_definitions": [{"id": "pipe_disp", "width": 1280}],
        }
        merged = merge_topologies(base, pipeline)
        assert len(merged["display_definitions"]) == 2
        ids = [d["id"] for d in merged["display_definitions"]]
        assert "base_disp" in ids
        assert "pipe_disp" in ids

    def test_merge_no_definitions_no_key(self):
        """Ни base ни pipeline не имеют display_definitions → ключ отсутствует."""
        base = {"processes": []}
        pipeline = {"name": "p", "processes": []}
        merged = merge_topologies(base, pipeline)
        assert "display_definitions" not in merged

    def test_merge_only_pipeline_has_definitions(self):
        """Только pipeline имеет display_definitions — они проходят."""
        base = {"processes": []}
        pipeline = {
            "name": "p",
            "processes": [],
            "display_definitions": [{"id": "d"}],
        }
        merged = merge_topologies(base, pipeline)
        assert merged["display_definitions"] == [{"id": "d"}]

    def test_merge_only_base_has_definitions(self):
        """Только base имеет display_definitions — они проходят."""
        base = {
            "processes": [],
            "display_definitions": [{"id": "d"}],
        }
        pipeline = {"name": "p", "processes": []}
        merged = merge_topologies(base, pipeline)
        assert merged["display_definitions"] == [{"id": "d"}]
