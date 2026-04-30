"""Unit-тесты SystemTopology schema (registers/system_topology/schemas.py).

Проверяем:
- Создание пустой модели
- Roundtrip сериализации
- Создание с данными
- FK-валидацию (корректные и сломанные ссылки)
- Helper-методы workers_for_process, regions_for_camera
- Константы SECTION_KEYS
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

from multiprocess_prototype.registers.system_topology.schemas import (
    ALL_SECTIONS,
    SECTION_DISPLAYS,
    SECTION_KEYS,
    SECTION_PIPELINE,
    SECTION_PROCESSES,
    SECTION_SOURCES,
    DisplayDefinition,
    ProcessDefinition,
    SystemTopology,
    WorkerDefinition,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def topology_with_data() -> SystemTopology:
    """SystemTopology с одним процессом, воркером, камерой и регионом."""
    from multiprocess_prototype.registers.sources.schemas import (
        CameraSourceConfig,
        RegionSourceConfig,
    )

    return SystemTopology(
        processes={
            "proc_0": ProcessDefinition(name="camera_0", class_path="pkg.CameraProcess"),
        },
        workers={
            "proc_0_main": WorkerDefinition(
                process_ref="proc_0",
                name="main",
                protected=True,
            ),
        },
        cameras={
            "camera_0": CameraSourceConfig(camera_id=0, process_name="camera_0"),
        },
        regions={
            "camera_0_main": RegionSourceConfig(camera_ref="camera_0"),
        },
        displays={
            "win_0": DisplayDefinition(name="Display 0", source_ref="camera_0"),
        },
    )


# ---------------------------------------------------------------------------
# Тест 1: default empty
# ---------------------------------------------------------------------------


def test_default_empty():
    """SystemTopology() создаётся с пустыми dict-ами."""
    st = SystemTopology()
    assert isinstance(st.processes, dict)
    assert isinstance(st.workers, dict)
    assert isinstance(st.cameras, dict)
    assert isinstance(st.regions, dict)
    assert isinstance(st.pipeline, dict)
    assert isinstance(st.displays, dict)
    assert len(st.processes) == 0
    assert len(st.cameras) == 0


# ---------------------------------------------------------------------------
# Тест 2: roundtrip
# ---------------------------------------------------------------------------


def test_roundtrip(topology_with_data):
    """model_dump() → model_validate() → model_dump() возвращает идентичный dict."""
    st = topology_with_data
    dumped = st.model_dump()
    restored = SystemTopology.model_validate(dumped)
    assert restored.model_dump() == dumped


# ---------------------------------------------------------------------------
# Тест 3: создание с данными
# ---------------------------------------------------------------------------


def test_with_data(topology_with_data):
    """Создание SystemTopology с процессами, воркерами, камерами, регионами, displays."""
    st = topology_with_data
    assert "proc_0" in st.processes
    assert st.processes["proc_0"].name == "camera_0"
    assert "proc_0_main" in st.workers
    assert st.workers["proc_0_main"].protected is True
    assert "camera_0" in st.cameras
    assert "camera_0_main" in st.regions
    assert "win_0" in st.displays


# ---------------------------------------------------------------------------
# Тест 4: validate_refs_ok — корректные ссылки
# ---------------------------------------------------------------------------


def test_validate_refs_ok(topology_with_data):
    """FK-валидация: корректные ссылки → пустой список ошибок."""
    st = topology_with_data
    errors = st.validate_refs()
    # Фильтруем только process_ref и region ошибки (source_ref — мягкая проверка)
    process_errors = [e for e in errors if "process_ref" in e or "camera_ref" in e]
    assert process_errors == []


# ---------------------------------------------------------------------------
# Тест 5: validate_refs_broken_worker
# ---------------------------------------------------------------------------


def test_validate_refs_broken_worker():
    """Worker с process_ref на несуществующий процесс → ошибка."""
    st = SystemTopology(
        processes={},
        workers={
            "orphan_worker": WorkerDefinition(
                process_ref="nonexistent_proc",
                name="main",
            ),
        },
    )
    errors = st.validate_refs()
    assert any("nonexistent_proc" in e for e in errors)


# ---------------------------------------------------------------------------
# Тест 6: validate_refs_broken_region
# ---------------------------------------------------------------------------


def test_validate_refs_broken_region():
    """Region с camera_ref на несуществующую камеру → ошибка."""
    from multiprocess_prototype.registers.sources.schemas import RegionSourceConfig

    st = SystemTopology(
        cameras={},
        regions={
            "bad_region": RegionSourceConfig(camera_ref="nonexistent_cam"),
        },
    )
    errors = st.validate_refs()
    assert any("nonexistent_cam" in e for e in errors)


# ---------------------------------------------------------------------------
# Тест 7: workers_for_process
# ---------------------------------------------------------------------------


def test_workers_for_process(topology_with_data):
    """workers_for_process возвращает только воркеры данного процесса."""
    st = topology_with_data
    result = st.workers_for_process("proc_0")
    assert "proc_0_main" in result
    assert all(w.process_ref == "proc_0" for w in result.values())

    # Другой процесс → пустой dict
    assert st.workers_for_process("nonexistent") == {}


# ---------------------------------------------------------------------------
# Тест 8: regions_for_camera
# ---------------------------------------------------------------------------


def test_regions_for_camera(topology_with_data):
    """regions_for_camera возвращает только регионы данной камеры."""
    st = topology_with_data
    result = st.regions_for_camera("camera_0")
    assert "camera_0_main" in result
    assert all(r.camera_ref == "camera_0" for r in result.values())

    # Другая камера → пустой dict
    assert st.regions_for_camera("camera_99") == {}


# ---------------------------------------------------------------------------
# Тест 9: SECTION_KEYS
# ---------------------------------------------------------------------------


def test_section_keys():
    """SECTION_KEYS содержит правильные маппинги секций на ключи TopologyData."""
    assert SECTION_KEYS[SECTION_PROCESSES] == ("processes", "workers")
    assert SECTION_KEYS[SECTION_SOURCES] == ("cameras", "regions")
    assert SECTION_KEYS[SECTION_PIPELINE] == ("pipeline",)
    assert SECTION_KEYS[SECTION_DISPLAYS] == ("displays",)
    # Все секции присутствуют
    assert set(SECTION_KEYS.keys()) == set(ALL_SECTIONS)
