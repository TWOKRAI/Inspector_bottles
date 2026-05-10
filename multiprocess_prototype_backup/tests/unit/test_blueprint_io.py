"""Тесты для blueprint_io.py — конвертеры topology ↔ SystemBlueprint + JSON I/O.

Модуль загружается через importlib.util напрямую — минуя circular imports
в tabs_setting/__init__.py пакетной иерархии.

Запуск: python -m pytest multiprocess_prototype/tests/unit/test_blueprint_io.py -v
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Загрузка blueprint_io напрямую (минуя circular imports в tabs_setting)
# ---------------------------------------------------------------------------

def _load_blueprint_io():
    """Загрузить blueprint_io.py через importlib.util без __init__.py-цепочки."""
    module_path = (
        Path(__file__).resolve().parents[2]
        / "frontend" / "widgets" / "tabs_setting"
        / "processes_tab" / "blueprint_io.py"
    )
    spec = importlib.util.spec_from_file_location(
        "blueprint_io_isolated", module_path
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["blueprint_io_isolated"] = mod
    spec.loader.exec_module(mod)
    return mod


_bio = _load_blueprint_io()

topology_to_blueprint = _bio.topology_to_blueprint
blueprint_to_topology = _bio.blueprint_to_topology
save_blueprint = _bio.save_blueprint
load_blueprint = _bio.load_blueprint


# ---------------------------------------------------------------------------
# Фикстуры
# ---------------------------------------------------------------------------

def _make_proc_data() -> dict[str, dict]:
    """Создать тестовый proc_data с двумя процессами и плагинами."""
    return {
        "camera_0": {
            "name": "camera_0",
            "class_path": "backend.processes.CameraProcess",
            "priority": "high",
            "auto_start": True,
            "sort_order": 0,
            "plugins": [
                {
                    "plugin_class": "backend.plugins.capture.CapturePlugin",
                    "plugin_name": "capture",
                    "width": 1280,
                    "height": 720,
                },
            ],
        },
        "processor_0": {
            "name": "processor_0",
            "class_path": "backend.processes.ProcessorProcess",
            "priority": "normal",
            "auto_start": True,
            "sort_order": 1,
            "plugins": [
                {
                    "plugin_class": "backend.plugins.color_mask.ColorMaskPlugin",
                    "plugin_name": "color_mask",
                    "hue_min": 10,
                    "hue_max": 40,
                },
                {
                    "plugin_class": "backend.plugins.render.RenderPlugin",
                    "plugin_name": "render",
                },
            ],
        },
    }


# ---------------------------------------------------------------------------
# test_topology_to_blueprint
# ---------------------------------------------------------------------------

def test_topology_to_blueprint_basic():
    """topology_to_blueprint создаёт blueprint с корректным числом процессов."""
    proc_data = _make_proc_data()
    bp = topology_to_blueprint(proc_data, name="test_recipe")

    assert bp.name == "test_recipe"
    assert len(bp.processes) == 2
    # Wires пустые (не поддерживаются в UI)
    assert bp.wires == []


def test_topology_to_blueprint_plugins():
    """topology_to_blueprint сохраняет plugins в ProcessConfig."""
    proc_data = _make_proc_data()
    bp = topology_to_blueprint(proc_data)

    # Найти camera_0
    camera_cfg = next(p for p in bp.processes if p.process_name == "camera_0")
    assert len(camera_cfg.plugins) == 1
    assert camera_cfg.plugins[0]["plugin_name"] == "capture"
    assert camera_cfg.plugins[0]["width"] == 1280

    # Найти processor_0
    proc_cfg = next(p for p in bp.processes if p.process_name == "processor_0")
    assert len(proc_cfg.plugins) == 2
    assert proc_cfg.plugins[0]["plugin_name"] == "color_mask"
    assert proc_cfg.plugins[1]["plugin_name"] == "render"


def test_topology_to_blueprint_priority():
    """topology_to_blueprint сохраняет priority процесса."""
    proc_data = _make_proc_data()
    bp = topology_to_blueprint(proc_data)

    camera_cfg = next(p for p in bp.processes if p.process_name == "camera_0")
    assert camera_cfg.priority == "high"

    proc_cfg = next(p for p in bp.processes if p.process_name == "processor_0")
    assert proc_cfg.priority == "normal"


def test_topology_to_blueprint_sort_order():
    """topology_to_blueprint сортирует по sort_order."""
    proc_data = _make_proc_data()
    bp = topology_to_blueprint(proc_data)

    # camera_0 (sort_order=0) должен идти перед processor_0 (sort_order=1)
    names = [p.process_name for p in bp.processes]
    assert names.index("camera_0") < names.index("processor_0")


# ---------------------------------------------------------------------------
# test_blueprint_to_topology
# ---------------------------------------------------------------------------

def test_blueprint_to_topology_basic():
    """blueprint_to_topology возвращает корректный snapshot-словарь."""
    proc_data = _make_proc_data()
    bp = topology_to_blueprint(proc_data, name="test")

    snapshot = blueprint_to_topology(bp)

    assert "processes" in snapshot
    assert "workers" in snapshot
    assert len(snapshot["processes"]) == 2


def test_blueprint_to_topology_main_workers():
    """blueprint_to_topology автоматически создаёт protected main-воркеры."""
    proc_data = _make_proc_data()
    bp = topology_to_blueprint(proc_data)

    snapshot = blueprint_to_topology(bp)
    workers = snapshot["workers"]

    # Для каждого процесса должен быть main-воркер
    assert "camera_0_main" in workers
    assert "processor_0_main" in workers

    # Воркер должен быть protected
    assert workers["camera_0_main"]["protected"] is True
    assert workers["camera_0_main"]["worker_type"] == "router_poll"
    assert workers["camera_0_main"]["process_ref"] == "camera_0"


def test_blueprint_to_topology_plugins_preserved():
    """blueprint_to_topology сохраняет plugins в processes."""
    proc_data = _make_proc_data()
    bp = topology_to_blueprint(proc_data)

    snapshot = blueprint_to_topology(bp)
    processes = snapshot["processes"]

    assert "camera_0" in processes
    plugins = processes["camera_0"]["plugins"]
    assert len(plugins) == 1
    assert plugins[0]["plugin_name"] == "capture"


# ---------------------------------------------------------------------------
# test_roundtrip
# ---------------------------------------------------------------------------

def test_roundtrip_plugins():
    """Round-trip: topology → blueprint → topology сохраняет plugins идентично."""
    original = _make_proc_data()

    # topology → blueprint → topology snapshot
    bp = topology_to_blueprint(original)
    snapshot = blueprint_to_topology(bp)
    restored_processes = snapshot["processes"]

    # Плагины должны быть идентичны
    assert restored_processes["camera_0"]["plugins"] == original["camera_0"]["plugins"]
    assert restored_processes["processor_0"]["plugins"] == original["processor_0"]["plugins"]


def test_roundtrip_priority():
    """Round-trip сохраняет priority процессов."""
    original = _make_proc_data()

    bp = topology_to_blueprint(original)
    snapshot = blueprint_to_topology(bp)

    assert snapshot["processes"]["camera_0"]["priority"] == "high"
    assert snapshot["processes"]["processor_0"]["priority"] == "normal"


# ---------------------------------------------------------------------------
# test_save_load_json
# ---------------------------------------------------------------------------

def test_save_load_json(tmp_path: Path):
    """save_blueprint → load_blueprint: данные идентичны."""
    proc_data = _make_proc_data()
    bp = topology_to_blueprint(proc_data, name="save_load_test", description="Тест")

    file_path = tmp_path / "test_recipe.json"
    save_blueprint(bp, file_path)

    # Файл должен существовать
    assert file_path.exists()

    # Загрузить обратно
    loaded = load_blueprint(file_path)

    assert loaded.name == "save_load_test"
    assert loaded.description == "Тест"
    assert len(loaded.processes) == 2


def test_save_load_json_content(tmp_path: Path):
    """Сохранённый JSON содержит корректные данные процессов и плагинов."""
    proc_data = _make_proc_data()
    bp = topology_to_blueprint(proc_data, name="content_test")

    file_path = tmp_path / "content.json"
    save_blueprint(bp, file_path)

    # Проверить raw JSON
    with file_path.open("r", encoding="utf-8") as f:
        raw = json.load(f)

    assert raw["name"] == "content_test"
    assert len(raw["processes"]) == 2

    # Плагины должны быть в JSON
    camera_proc = next(p for p in raw["processes"] if p["process_name"] == "camera_0")
    assert camera_proc["plugins"][0]["plugin_name"] == "capture"


def test_save_creates_parent_dirs(tmp_path: Path):
    """save_blueprint создаёт родительские директории при необходимости."""
    proc_data = _make_proc_data()
    bp = topology_to_blueprint(proc_data, name="nested")

    nested_path = tmp_path / "a" / "b" / "c" / "nested.json"
    save_blueprint(bp, nested_path)

    assert nested_path.exists()


def test_load_file_not_found(tmp_path: Path):
    """load_blueprint бросает FileNotFoundError если файл не найден."""
    with pytest.raises(FileNotFoundError):
        load_blueprint(tmp_path / "nonexistent.json")


# ---------------------------------------------------------------------------
# test_empty_processes
# ---------------------------------------------------------------------------

def test_empty_processes():
    """topology_to_blueprint с пустым dict создаёт blueprint без процессов."""
    bp = topology_to_blueprint({}, name="empty")

    assert bp.name == "empty"
    assert bp.processes == []
    assert bp.wires == []


def test_empty_blueprint_to_topology():
    """blueprint_to_topology с пустым blueprint возвращает пустые processes/workers."""
    bp = topology_to_blueprint({})

    snapshot = blueprint_to_topology(bp)

    assert snapshot["processes"] == {}
    assert snapshot["workers"] == {}


def test_empty_roundtrip_json(tmp_path: Path):
    """Round-trip пустого blueprint через JSON работает без ошибок."""
    bp = topology_to_blueprint({}, name="empty_rt")

    path = tmp_path / "empty.json"
    save_blueprint(bp, path)
    loaded = load_blueprint(path)

    assert loaded.name == "empty_rt"
    assert loaded.processes == []
