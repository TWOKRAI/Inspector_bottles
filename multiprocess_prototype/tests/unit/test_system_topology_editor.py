"""Unit-тесты SystemTopologyEditor (frontend/models/system_topology_editor.py).

Проверяем:
- Создание редактора (не dirty)
- load() сбрасывает dirty
- Per-section dirty tracking
- mark_clean() по секции и по всем
- Подписки на изменения секции
- Отсутствие cross-fire между секциями
- Cross-tab queries
- Валидация процессов и источников
- to_dict() возвращает deepcopy
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_V3_ROOT = Path(__file__).resolve().parents[2]
for _p in (_ROOT, _V3_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multiprocess_prototype.frontend.models.system_topology_editor import SystemTopologyEditor
from multiprocess_prototype.registers.system_topology.schemas import (
    SECTION_DISPLAYS,
    SECTION_PIPELINE,
    SECTION_PROCESSES,
    SECTION_SOURCES,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def editor() -> SystemTopologyEditor:
    """Свежий SystemTopologyEditor."""
    return SystemTopologyEditor()


@pytest.fixture
def editor_with_process(editor: SystemTopologyEditor) -> SystemTopologyEditor:
    """Editor с одним процессом и воркером."""
    editor._data["processes"]["proc_0"] = {
        "name": "camera_0",
        "class_path": "pkg.CameraProcess",
        "priority": "normal",
        "auto_start": True,
        "sort_order": 0,
    }
    editor._data["workers"]["proc_0_main"] = {
        "process_ref": "proc_0",
        "name": "main",
        "worker_type": "router_poll",
        "enabled": True,
        "protected": True,
        "target_interval_ms": 0,
        "sort_order": 0,
    }
    editor.mark_clean()
    return editor


@pytest.fixture
def editor_with_camera(editor: SystemTopologyEditor) -> SystemTopologyEditor:
    """Editor с одной камерой и регионом."""
    editor._data["cameras"]["camera_0"] = {
        "camera_id": 0,
        "camera_type": "simulator",
        "process_name": "camera_0",
        "execution_mode": "process",
        "region_processing": "dedicated_processor",
        "region_processor_name": "processor_0",
    }
    editor._data["regions"]["camera_0_main"] = {
        "camera_ref": "camera_0",
        "enabled": True,
        "is_main": True,
        "processing_enabled": True,
        "sort_order": 0,
    }
    editor.mark_clean()
    return editor


# ---------------------------------------------------------------------------
# Тест 1: fresh editor is clean
# ---------------------------------------------------------------------------


def test_fresh_editor_is_clean(editor):
    """Новый editor не dirty ни по одной секции."""
    assert editor.is_dirty() is False
    assert editor.is_dirty(SECTION_PROCESSES) is False
    assert editor.is_dirty(SECTION_SOURCES) is False
    assert editor.is_dirty(SECTION_PIPELINE) is False
    assert editor.is_dirty(SECTION_DISPLAYS) is False


# ---------------------------------------------------------------------------
# Тест 2: load marks clean
# ---------------------------------------------------------------------------


def test_load_marks_clean(editor):
    """load() очищает dirty флаги."""
    # Грязним данные
    editor._data["processes"]["tmp"] = {"name": "tmp", "class_path": "x"}
    # После load — чистый
    editor.load(editor.to_dict())
    assert editor.is_dirty() is False


# ---------------------------------------------------------------------------
# Тест 3: per-section dirty
# ---------------------------------------------------------------------------


def test_per_section_dirty(editor):
    """Изменение processes делает processes dirty, sources — остаётся чистым."""
    editor.update_item("processes", "new_proc", {"name": "x", "class_path": "y"})
    assert editor.is_dirty(SECTION_PROCESSES) is True
    assert editor.is_dirty(SECTION_SOURCES) is False


def test_per_section_dirty_sources(editor):
    """Изменение cameras делает sources dirty, processes — остаётся чистым."""
    editor.update_item("cameras", "camera_0", {"camera_id": 0})
    assert editor.is_dirty(SECTION_SOURCES) is True
    assert editor.is_dirty(SECTION_PROCESSES) is False


# ---------------------------------------------------------------------------
# Тест 4: mark_clean section
# ---------------------------------------------------------------------------


def test_mark_clean_section(editor):
    """mark_clean(SECTION_PROCESSES) очищает только processes."""
    editor.update_item("processes", "p", {"name": "p"})
    editor.update_item("cameras", "c", {"camera_id": 1})
    editor.mark_clean(SECTION_PROCESSES)
    assert editor.is_dirty(SECTION_PROCESSES) is False
    assert editor.is_dirty(SECTION_SOURCES) is True


# ---------------------------------------------------------------------------
# Тест 5: mark_clean all
# ---------------------------------------------------------------------------


def test_mark_clean_all(editor):
    """mark_clean() без аргументов очищает все секции."""
    editor.update_item("processes", "p", {"name": "p"})
    editor.update_item("cameras", "c", {"camera_id": 1})
    editor.mark_clean()
    assert editor.is_dirty() is False


# ---------------------------------------------------------------------------
# Тест 6: subscribe section — callback вызывается
# ---------------------------------------------------------------------------


def test_subscribe_section(editor):
    """Подписка на секцию: callback вызывается при изменении этой секции."""
    calls = []
    editor.subscribe(SECTION_PROCESSES, lambda: calls.append(1))
    editor.update_item("processes", "p", {"name": "p"})
    assert len(calls) == 1


# ---------------------------------------------------------------------------
# Тест 7: subscribe no cross-fire
# ---------------------------------------------------------------------------


def test_subscribe_no_cross_fire(editor):
    """Изменение processes НЕ вызывает callback sources."""
    sources_calls = []
    editor.subscribe(SECTION_SOURCES, lambda: sources_calls.append(1))
    editor.update_item("processes", "p", {"name": "p"})
    assert len(sources_calls) == 0


# ---------------------------------------------------------------------------
# Тест 8: cross-tab queries
# ---------------------------------------------------------------------------


def test_cross_tab_process_names(editor_with_process):
    """process_names() возвращает список имён процессов."""
    names = editor_with_process.process_names()
    assert "camera_0" in names


def test_cross_tab_camera_keys(editor_with_camera):
    """camera_keys() возвращает список ключей камер."""
    keys = editor_with_camera.camera_keys()
    assert "camera_0" in keys


def test_cross_tab_region_keys_for_camera(editor_with_camera):
    """region_keys_for_camera() возвращает ключи регионов камеры."""
    keys = editor_with_camera.region_keys_for_camera("camera_0")
    assert "camera_0_main" in keys


def test_cross_tab_region_keys_for_unknown_camera(editor_with_camera):
    """region_keys_for_camera() для несуществующей камеры возвращает []."""
    keys = editor_with_camera.region_keys_for_camera("nonexistent")
    assert keys == []


# ---------------------------------------------------------------------------
# Тест 9: validate_processes — ошибки
# ---------------------------------------------------------------------------


def test_validate_processes_empty_name(editor):
    """Процесс с пустым именем → ошибка валидации."""
    editor._data["processes"]["p1"] = {
        "name": "",
        "class_path": "some.Path",
        "priority": "normal",
        "auto_start": True,
        "sort_order": 0,
    }
    editor._data["workers"]["p1_main"] = {
        "process_ref": "p1",
        "name": "main",
        "worker_type": "router_poll",
        "enabled": True,
        "protected": True,
        "target_interval_ms": 0,
        "sort_order": 0,
    }
    errors = editor.validate(SECTION_PROCESSES)
    assert any("имя не задано" in e for e in errors)


def test_validate_processes_no_class_path(editor):
    """Процесс без class_path → ошибка валидации."""
    editor._data["processes"]["p1"] = {
        "name": "my_process",
        "class_path": "",
        "priority": "normal",
        "auto_start": True,
        "sort_order": 0,
    }
    editor._data["workers"]["p1_main"] = {
        "process_ref": "p1",
        "name": "main",
        "worker_type": "router_poll",
        "enabled": True,
        "protected": True,
        "target_interval_ms": 0,
        "sort_order": 0,
    }
    errors = editor.validate(SECTION_PROCESSES)
    assert any("class_path не задан" in e for e in errors)


# ---------------------------------------------------------------------------
# Тест 10: validate_sources — дублирование camera_id
# ---------------------------------------------------------------------------


def test_validate_sources_duplicate_camera_id(editor):
    """Две камеры с одинаковым camera_id → ошибка валидации."""
    editor._data["cameras"]["camera_0"] = {"camera_id": 0, "camera_type": "simulator"}
    editor._data["cameras"]["camera_0_dup"] = {"camera_id": 0, "camera_type": "webcam"}
    errors = editor.validate(SECTION_SOURCES)
    assert any("дублирует" in e for e in errors)


def test_validate_sources_unique_ids_ok(editor):
    """Уникальные camera_id → ошибок нет."""
    editor._data["cameras"]["camera_0"] = {"camera_id": 0}
    editor._data["cameras"]["camera_1"] = {"camera_id": 1}
    errors = editor.validate(SECTION_SOURCES)
    assert errors == []


# ---------------------------------------------------------------------------
# Тест 11: to_dict is copy
# ---------------------------------------------------------------------------


def test_to_dict_is_copy(editor_with_process):
    """to_dict() возвращает deepcopy — мутация результата не меняет editor."""
    data = editor_with_process.to_dict()
    data["processes"]["injected"] = {"name": "injected"}
    assert "injected" not in editor_with_process._data["processes"]


# ---------------------------------------------------------------------------
# Тесты 12-15: валидация plugin chain (совместимость портов)
# ---------------------------------------------------------------------------


def _make_process_with_plugins(editor, proc_key, plugins):
    """Вспомогательная: создать процесс с plugins и protected-воркером."""
    editor._data["processes"][proc_key] = {
        "name": f"proc_{proc_key}",
        "class_path": "pkg.SomeProcess",
        "priority": "normal",
        "auto_start": True,
        "sort_order": 0,
        "plugins": plugins,
    }
    editor._data["workers"][f"{proc_key}_main"] = {
        "process_ref": proc_key,
        "name": "main",
        "worker_type": "router_poll",
        "enabled": True,
        "protected": True,
        "target_interval_ms": 0,
        "sort_order": 0,
    }


def test_validate_plugin_chain_compatible(editor, monkeypatch):
    """Совместимая цепочка [capture → color_mask] → 0 ошибок порт-валидации."""
    from multiprocess_framework.modules.process_module.plugins.port import Port
    from multiprocess_framework.modules.process_module.plugins.registry import (
        PluginEntry,
        PluginRegistry,
    )

    # Создаём mock-плагины с совместимыми портами
    class FakeCapture:
        inputs = []
        outputs = [Port(name="frame", dtype="image/bgr", shape="(H, W, 3)")]

    class FakeColorMask:
        inputs = [Port(name="frame", dtype="image/bgr", shape="(H, W, 3)")]
        outputs = [Port(name="mask", dtype="image/gray", shape="(H, W, 1)")]

    # Патчим PluginRegistry.get
    fake_registry = {
        "capture": PluginEntry("capture", FakeCapture, category="source"),
        "color_mask": PluginEntry("color_mask", FakeColorMask, category="processing"),
    }
    monkeypatch.setattr(PluginRegistry, "get", lambda name: fake_registry.get(name))

    _make_process_with_plugins(editor, "proc_0", [
        {"plugin_class": "pkg.Capture", "plugin_name": "capture"},
        {"plugin_class": "pkg.ColorMask", "plugin_name": "color_mask"},
    ])

    errors = editor.validate(SECTION_PROCESSES)
    # Не должно быть ошибок совместимости портов
    port_errors = [e for e in errors if "несовместим" in e]
    assert port_errors == []


def test_validate_plugin_chain_incompatible(editor, monkeypatch):
    """Несовместимая цепочка → ошибки валидации портов."""
    from multiprocess_framework.modules.process_module.plugins.port import Port
    from multiprocess_framework.modules.process_module.plugins.registry import (
        PluginEntry,
        PluginRegistry,
    )

    # capture выдаёт image/bgr, detector ожидает tensor/float32 — несовместимо
    class FakeCapture:
        inputs = []
        outputs = [Port(name="frame", dtype="image/bgr", shape="(H, W, 3)")]

    class FakeDetector:
        inputs = [Port(name="tensor", dtype="tensor/float32", shape="(1, 3, H, W)")]
        outputs = [Port(name="detections", dtype="dict")]

    fake_registry = {
        "capture": PluginEntry("capture", FakeCapture, category="source"),
        "detector": PluginEntry("detector", FakeDetector, category="processing"),
    }
    monkeypatch.setattr(PluginRegistry, "get", lambda name: fake_registry.get(name))

    _make_process_with_plugins(editor, "proc_0", [
        {"plugin_class": "pkg.Capture", "plugin_name": "capture"},
        {"plugin_class": "pkg.Detector", "plugin_name": "detector"},
    ])

    errors = editor.validate(SECTION_PROCESSES)
    port_errors = [e for e in errors if "несовместим" in e]
    assert len(port_errors) >= 1
    assert "proc_0" in port_errors[0]


def test_validate_plugin_chain_empty_registry(editor, monkeypatch):
    """Пустой PluginRegistry → валидация портов пропускается, 0 ошибок портов."""
    from multiprocess_framework.modules.process_module.plugins.registry import (
        PluginRegistry,
    )

    # Registry не знает ни одного плагина
    monkeypatch.setattr(PluginRegistry, "get", lambda name: None)

    _make_process_with_plugins(editor, "proc_0", [
        {"plugin_class": "pkg.Capture", "plugin_name": "capture"},
        {"plugin_class": "pkg.ColorMask", "plugin_name": "color_mask"},
    ])

    errors = editor.validate(SECTION_PROCESSES)
    # Ошибок совместимости портов быть не должно (graceful degradation)
    port_errors = [e for e in errors if "несовместим" in e]
    assert port_errors == []


def test_validate_plugin_chain_no_plugins(editor):
    """Процесс без plugins → валидация портов пропускается."""
    _make_process_with_plugins(editor, "proc_0", [])

    errors = editor.validate(SECTION_PROCESSES)
    # Нет ошибок (кроме возможных базовых проверок)
    port_errors = [e for e in errors if "несовместим" in e]
    assert port_errors == []
