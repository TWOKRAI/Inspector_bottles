"""Тесты слияния фундамент ⊕ pipeline (main.merge_topologies).

Гарантируют, что вынос процесса `gui` в фундамент (base.yaml) эквивалентен
прежней встроенной топологии: merged-сборка содержит те же процессы, gui берётся
из фундамента, chain_targets:[gui] резолвится после слияния.
"""

from pathlib import Path

import pytest
import yaml

from multiprocess_framework.modules.process_module.generic.blueprint import SystemBlueprint
from multiprocess_prototype.backend.launch import merge_topologies

TOPOLOGY_DIR = Path(__file__).resolve().parents[1]
BASE_PATH = TOPOLOGY_DIR / "base.yaml"

ACTIVE_PIPELINES = [
    "hello_world.yaml",
    "inspection_basic.yaml",
    "inspection_full.yaml",
    "multi_camera.yaml",
    "region_pipeline.yaml",
]

GUI_CLASS = "multiprocess_prototype.frontend.process.GuiProcess"


def _load(name: str) -> dict:
    with open(TOPOLOGY_DIR / name, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _base() -> dict:
    with open(BASE_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


class TestBaseMerge:
    """Контракт merge_topologies: фундамент ⊕ pipeline."""

    def test_base_provides_gui_process(self):
        """Фундамент содержит процесс презентации `gui` (класс GuiProcess)."""
        base = _base()
        gui = next((p for p in base["processes"] if p["process_name"] == "gui"), None)
        assert gui is not None, "base.yaml должен содержать процесс gui"
        assert gui["process_class"] == GUI_CLASS

    def test_pipelines_have_no_gui(self):
        """Pipeline-топологии больше НЕ объявляют gui (он в фундаменте)."""
        for name in ACTIVE_PIPELINES:
            names = {p["process_name"] for p in _load(name)["processes"]}
            assert "gui" not in names, f"{name}: gui должен быть вынесен в фундамент"

    @pytest.mark.parametrize("name", ACTIVE_PIPELINES)
    def test_merge_adds_gui_preserves_pipeline(self, name):
        """merge(base, pipeline): gui добавлен из фундамента ровно один раз,
        все процессы pipeline сохранены."""
        pipeline = _load(name)
        merged = merge_topologies(_base(), pipeline)
        names = [p["process_name"] for p in merged["processes"]]
        assert names.count("gui") == 1, f"{name}: gui должен быть ровно один"
        gui = next(p for p in merged["processes"] if p["process_name"] == "gui")
        assert gui["process_class"] == GUI_CLASS
        for p in pipeline["processes"]:
            assert p["process_name"] in names, f"{name}: процесс {p['process_name']} потерян при merge"

    def test_region_pipeline_merge_golden_build(self):
        """Golden: merge(base, region_pipeline) собирается в configs; gui (из фундамента)
        присутствует ровно один раз с классом GuiProcess."""
        merged = merge_topologies(_base(), _load("region_pipeline.yaml"))
        configs = SystemBlueprint.model_validate(merged).build_configs()
        names = [c.process_name for c in configs]
        assert names.count("gui") == 1
        assert next(c for c in configs if c.process_name == "gui").process_class == GUI_CLASS

    def test_chain_targets_gui_resolves_after_merge(self):
        """chain_targets:[gui] из pipeline резолвится после слияния с фундаментом."""
        merged = merge_topologies(_base(), _load("region_pipeline.yaml"))
        names = {p["process_name"] for p in merged["processes"]}
        for proc in merged["processes"]:
            for target in proc.get("chain_targets", []):
                assert target in names, f"chain_target '{target}' не резолвится в merged"

    def test_merge_dedupes_on_collision_base_wins(self):
        """Если pipeline тоже объявляет gui — побеждает фундамент (dedupe)."""
        base = _base()
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
        assert guis[0]["process_class"] == GUI_CLASS, "должен победить фундамент"

    def test_merge_preserves_pipeline_name(self):
        """Результат берёт name/description из pipeline (активная нагрузка)."""
        merged = merge_topologies(_base(), _load("region_pipeline.yaml"))
        assert merged["name"] == "region_pipeline"

    def test_pipeline_alone_is_headless(self):
        """Headless: pipeline без фундамента собирается без процесса презентации,
        цепочка обработки сохраняется (бэкенд работает без GUI)."""
        configs = SystemBlueprint.model_validate(_load("region_pipeline.yaml")).build_configs()
        names = {c.process_name for c in configs}
        assert "gui" not in names
        assert "camera_0" in names and "stitcher" in names
