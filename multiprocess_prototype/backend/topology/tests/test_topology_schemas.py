"""Тесты валидации topology YAML файлов."""

import pytest
from pathlib import Path
import yaml

TOPOLOGY_DIR = Path(__file__).resolve().parents[1]
BASE_PATH = TOPOLOGY_DIR / "base.yaml"

# Все рабочие topology (не TEMPLATE, не архив)
ACTIVE_TOPOLOGIES = [
    "hello_world.yaml",
    "inspection_basic.yaml",
    "inspection_full.yaml",
    "multi_camera.yaml",
    "region_pipeline.yaml",
]


def _base_process_names() -> set[str]:
    """Имена процессов фундамента (base.yaml) — валидные цели chain_targets."""
    with open(BASE_PATH, encoding="utf-8") as f:
        base = yaml.safe_load(f) or {}
    return {p["process_name"] for p in base.get("processes", [])}


@pytest.fixture(params=ACTIVE_TOPOLOGIES)
def topology(request):
    """Загрузить topology YAML."""
    path = TOPOLOGY_DIR / request.param
    assert path.exists(), f"Topology не найден: {path}"
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


class TestTopologySchema:
    """Валидация структуры topology файлов."""

    def test_has_name(self, topology):
        """Topology содержит поле name."""
        assert "name" in topology

    def test_has_processes(self, topology):
        """Topology содержит непустой список processes."""
        assert "processes" in topology
        assert isinstance(topology["processes"], list)
        assert len(topology["processes"]) > 0

    def test_unique_process_names(self, topology):
        """Имена процессов уникальны."""
        names = [p["process_name"] for p in topology["processes"]]
        assert len(names) == len(set(names)), f"Дублирующиеся имена: {names}"

    def test_each_process_has_plugins(self, topology):
        """Каждый процесс имеет список plugins."""
        for proc in topology["processes"]:
            assert "plugins" in proc, f"Процесс {proc['process_name']} без plugins"
            assert isinstance(proc["plugins"], list)

    def test_chain_targets_reference_existing(self, topology):
        """chain_targets ссылаются на процессы pipeline ИЛИ фундамента (base.yaml)."""
        # Процессы фундамента (gui и пр.) — валидные цели: суммируются при запуске.
        names = {p["process_name"] for p in topology["processes"]} | _base_process_names()
        for proc in topology["processes"]:
            for target in proc.get("chain_targets", []):
                assert target in names, f"{proc['process_name']}: chain_target '{target}' нет в topology+base"


class TestTemplateYaml:
    """Проверка TEMPLATE.yaml."""

    def test_template_is_valid_yaml(self):
        """TEMPLATE.yaml парсится без ошибок."""
        path = TOPOLOGY_DIR / "TEMPLATE.yaml"
        assert path.exists()
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert data is not None
        assert "processes" in data
