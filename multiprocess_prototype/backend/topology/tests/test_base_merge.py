"""Тесты слияния фундамент ⊕ pipeline ⊕ presentation-патч (launch).

Ф2 frontend-constructor (2026-07) вынес презентацию из фундамента в overlay.
План D8 (2026-08-10) поправил вторую половину: `gui` объявляет РЕЦЕПТ — в
headless-воплощении (`HeadlessGuiProcess`), а overlay ПОДМЕНЯЕТ ему класс на
Qt-шный. То есть headless — это не «процесса нет», а «процесс без окна».

Почему так, а не как было. Прежде headless означал отсутствие процесса при
живых `chain_targets: [gui]` у продюсеров: адрес без приёмника давал отказ
доставки на КАЖДЫЙ кадр — 1418 отказов за 30 с на стенде `webcam_sketch`.

Гарантируют: base.yaml — инфра без презентации; рецепт объявляет `gui` в
headless-воплощении; overlay патчит КЛАСС и не добавляет процессов; ни один
`chain_target` не ведёт в необъявленный процесс.
"""

from pathlib import Path

import pytest
import yaml

from multiprocess_framework.modules.process_manager_module.topology.blueprint import SystemBlueprint
from multiprocess_prototype.backend.launch import (
    apply_presentation_overlay,
    merge_topologies,
    unwrap_recipe,
)

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

#: Класс презентации с окном — его ставит ТОЛЬКО presentation-overlay.
GUI_CLASS = "multiprocess_prototype.frontend.process.GuiProcess"
#: Headless-воплощение того же процесса — его объявляют рецепты и топологии.
HEADLESS_CLASS = "multiprocess_prototype.frontend.headless_process.HeadlessGuiProcess"


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


def _with_presentation(topology: dict) -> dict:
    """Активная топология с включённой презентацией: патч поверх слитого."""
    return apply_presentation_overlay(topology, _presentation())


class TestBaseMerge:
    """Контракт: фундамент ⊕ pipeline, затем presentation-ПАТЧ поверх слитого."""

    def test_base_is_infra_only_without_presentation(self):
        """base.yaml — always-on инфра (devices); презентацию объявляет рецепт."""
        base = _base()
        names = {p["process_name"] for p in base["processes"]}
        assert "gui" not in names, "gui объявляет рецепт, не фундамент"
        assert "devices" in names

    def test_presentation_overlay_carries_only_the_qt_class(self):
        """Overlay несёт КЛАСС, а не процесс: он патчит то, что объявил рецепт."""
        presentation = _presentation()
        gui = next((p for p in presentation["processes"] if p["process_name"] == "gui"), None)
        assert gui is not None, "presentation.yaml должен нести патч для gui"
        assert gui["process_class"] == GUI_CLASS

    def test_recipe_declares_gui_in_the_headless_incarnation(self):
        """Рецепт объявляет процесс презентации САМ — и в headless-классе.

        Это и есть суть D8: приёмник существует всегда, окно добавляется патчем.
        """
        gui = next(p for p in _load_region_pipeline()["processes"] if p["process_name"] == "gui")
        assert gui["process_class"] == HEADLESS_CLASS
        assert gui.get("protected") is True, "презентация protected — switch не должен её сносить"

    def test_headless_build_has_gui_without_qt(self):
        """Headless-сборка (без overlay): процесс gui ЕСТЬ, класс — headless.

        Прежний контракт утверждал обратное («gui not in names»), и ровно это
        оставляло chain_targets:[gui] без приёмника.
        """
        merged = merge_topologies(_base(), _load_region_pipeline())
        configs = SystemBlueprint.model_validate(merged).build_configs()
        by_name = {c.process_name: c for c in configs}
        assert "gui" in by_name, "headless — это процесс без окна, а не отсутствие процесса"
        assert by_name["gui"].process_class == HEADLESS_CLASS
        assert "devices" in by_name and "camera_0" in by_name and "stitcher" in by_name

    def test_presentation_patch_swaps_the_class_in_place(self):
        """С overlay'ем тот же процесс получает Qt-класс — ровно один gui."""
        merged = _with_presentation(merge_topologies(_base(), _load_region_pipeline()))
        names = [p["process_name"] for p in merged["processes"]]
        assert names.count("gui") == 1, "патч не должен добавлять второй процесс"
        gui = next(p for p in merged["processes"] if p["process_name"] == "gui")
        assert gui["process_class"] == GUI_CLASS
        assert gui.get("protected") is True, "поля рецепта переживают патч"

    def test_patch_does_not_add_processes_the_topology_never_declared(self):
        """Рецепт без презентации не получает окно даже с overlay'ем.

        Добавлять приёмник, которому никто не шлёт, значило бы поднимать процесс
        зря; а молчаливое добавление читалось бы как «презентация включена».
        """
        topology = {"name": "t", "processes": [{"process_name": "cam", "plugins": []}], "wires": []}
        patched = apply_presentation_overlay(topology, _presentation())
        assert [p["process_name"] for p in patched["processes"]] == ["cam"]

    def test_patch_does_not_mutate_input(self):
        topology = {
            "name": "t",
            "processes": [{"process_name": "gui", "process_class": HEADLESS_CLASS, "plugins": []}],
            "wires": [],
        }
        apply_presentation_overlay(topology, _presentation())
        assert topology["processes"][0]["process_class"] == HEADLESS_CLASS

    @pytest.mark.parametrize("name", ACTIVE_PIPELINES)
    def test_pipelines_declare_gui_and_keep_their_processes(self, name):
        """Каждая активная топология объявляет gui сама; merge ничего не теряет."""
        pipeline = _load(name)
        gui = next((p for p in pipeline["processes"] if p["process_name"] == "gui"), None)
        assert gui is not None, f"{name}: адресует gui — обязан его объявить"
        assert gui["process_class"] == HEADLESS_CLASS
        merged = merge_topologies(_base(), pipeline)
        names = [p["process_name"] for p in merged["processes"]]
        assert names.count("gui") == 1, f"{name}: gui должен быть ровно один"
        for p in pipeline["processes"]:
            assert p["process_name"] in names, f"{name}: процесс {p['process_name']} потерян при merge"

    def test_region_pipeline_merge_golden_build(self):
        """Golden: merge(base, region_pipeline) + патч собирается в configs;
        gui ровно один, с Qt-классом."""
        merged = _with_presentation(merge_topologies(_base(), _load_region_pipeline()))
        configs = SystemBlueprint.model_validate(merged).build_configs()
        names = [c.process_name for c in configs]
        assert names.count("gui") == 1
        assert next(c for c in configs if c.process_name == "gui").process_class == GUI_CLASS

    def test_chain_targets_resolve_after_merge(self):
        """Каждый chain_target резолвится в СЛИТОЙ топологии — и это же судит
        сборка (``SystemBlueprint``), а не только этот тест."""
        merged = merge_topologies(_base(), _load_region_pipeline())
        names = {p["process_name"] for p in merged["processes"]}
        for proc in merged["processes"]:
            for target in proc.get("chain_targets", []):
                assert target in names, f"chain_target '{target}' не резолвится в merged"
        assert SystemBlueprint.model_validate(merged)._unaddressable_chain_targets() == []

    def test_merge_dedupes_on_collision_base_wins(self):
        """Если pipeline объявляет процесс фундамента — побеждает фундамент."""
        pipeline = {
            "name": "dup",
            "processes": [
                {"process_name": "cam", "plugins": []},
                {"process_name": "devices", "process_class": "other.Class", "plugins": []},
            ],
        }
        merged = merge_topologies(_base(), pipeline)
        devices = [p for p in merged["processes"] if p["process_name"] == "devices"]
        assert len(devices) == 1, "devices не должен дублироваться"
        assert devices[0]["process_class"] != "other.Class", "должен победить фундамент"

    def test_merge_preserves_pipeline_name(self):
        """Результат берёт name/description из pipeline (активная нагрузка)."""
        merged = merge_topologies(_base(), _load_region_pipeline())
        assert merged["name"] == "region_pipeline"

    def test_protected_survives_merge_and_build(self):
        """Регрессия У1 (device-hub): protected: true из base.yaml переживает
        merge → SystemBlueprint → build → proc_dict["protected"] == True.

        Сценарий: base={gui(protected), devices(protected)} + pipeline={worker}.
        """
        base = {
            "name": "base",
            "processes": [
                {"process_name": "gui", "protected": True, "process_class": HEADLESS_CLASS, "plugins": []},
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

    def test_protected_from_the_recipe_survives_the_presentation_patch(self):
        """`protected` объявляет РЕЦЕПТ, и патч класса его не теряет.

        Раньше флаг приходил из presentation.yaml; теперь overlay несёт только
        класс, и потеря флага при патче означала бы, что switch сносит окно.
        """
        presentation = _presentation()
        gui_patch = next(p for p in presentation["processes"] if p["process_name"] == "gui")
        assert "protected" not in gui_patch, "overlay несёт класс, а не флаги процесса"
        merged = _with_presentation(merge_topologies(_base(), _load_region_pipeline()))
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


class TestObservabilityLayerSurvivesRecipePath:
    """Task 5.12: слой L2 не должен теряться на пути «файл → топология»."""

    def test_unwrap_lifts_top_level_section_into_topology(self) -> None:
        """Человек пишет секцию рядом с blueprint — без подъёма она исчезала бы молча."""
        raw = {
            "blueprint": {"processes": [], "wires": []},
            "observability": {"defaults": {"log_level": "WARNING"}},
        }
        assert unwrap_recipe(raw)["observability"] == {"defaults": {"log_level": "WARNING"}}

    def test_nested_section_beats_top_level_per_key(self) -> None:
        raw = {
            "blueprint": {
                "processes": [],
                "wires": [],
                "observability": {"defaults": {"log_level": "ERROR"}},
            },
            "observability": {"defaults": {"log_level": "WARNING", "console": False}},
        }
        # Ни один ключ не пропал: вложенное победило только там, где сказало.
        assert unwrap_recipe(raw)["observability"] == {"defaults": {"log_level": "ERROR", "console": False}}

    def test_recipe_without_section_stays_untouched(self) -> None:
        raw = {"blueprint": {"processes": [], "wires": []}}
        assert "observability" not in unwrap_recipe(raw)

    def test_merge_topologies_carries_section_pipeline_over_base(self) -> None:
        """Штатная раскладка прототипа — фундамент ⊕ pipeline; секция обязана дожить."""
        base = {"processes": [], "wires": [], "observability": {"defaults": {"log_level": "INFO"}}}
        pipeline = {
            "name": "p",
            "processes": [],
            "wires": [],
            "observability": {"defaults": {"log_level": "DEBUG"}},
        }
        merged = merge_topologies(base, pipeline)
        assert merged["observability"] == {"defaults": {"log_level": "DEBUG"}}

    def test_merge_topologies_omits_key_when_neither_side_has_it(self) -> None:
        merged = merge_topologies({"processes": [], "wires": []}, {"processes": [], "wires": []})
        assert "observability" not in merged

    def test_blueprint_validation_keeps_the_section(self) -> None:
        """SystemBlueprint не должен съедать секцию при валидации (Dict at Boundary)."""
        bp = SystemBlueprint.model_validate(
            {"processes": [], "wires": [], "observability": {"defaults": {"log_level": "WARNING"}}}
        )
        assert bp.observability == {"defaults": {"log_level": "WARNING"}}
