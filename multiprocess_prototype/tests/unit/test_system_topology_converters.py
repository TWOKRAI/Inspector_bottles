"""Unit-тесты converters (registers/system_topology/converters.py).

Проверяем:
- extract_source_topology: cameras/regions из dict → SourceTopology
- diff_process_configs: added, removed, modified, no_changes
- extract_process_commands: порядок (stop → create), protected workers пропускаются
- extract_display_diff: added, removed, modified
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

from multiprocess_prototype.registers.system_topology.converters import (
    diff_process_configs,
    extract_display_diff,
    extract_process_commands,
    extract_source_topology,
)
from multiprocess_prototype.registers.sources.schemas import SourceTopology


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_process(name: str, class_path: str = "pkg.Proc") -> dict:
    return {
        "name": name,
        "class_path": class_path,
        "priority": "normal",
        "auto_start": True,
        "sort_order": 0,
    }


def _make_worker(process_ref: str, name: str = "main", protected: bool = True,
                  interval: int = 0) -> dict:
    return {
        "process_ref": process_ref,
        "name": name,
        "worker_type": "router_poll",
        "enabled": True,
        "protected": protected,
        "target_interval_ms": interval,
        "sort_order": 0,
    }


def _make_camera(camera_id: int) -> dict:
    return {
        "camera_id": camera_id,
        "camera_type": "simulator",
        "process_name": f"camera_{camera_id}",
        "execution_mode": "process",
        "region_processing": "dedicated_processor",
        "region_processor_name": f"processor_{camera_id}",
    }


def _make_region(camera_ref: str) -> dict:
    return {
        "camera_ref": camera_ref,
        "enabled": True,
        "is_main": True,
        "processing_enabled": True,
        "sort_order": 0,
    }


def _make_display(name: str, source_ref: str, fps_limit: int = 30) -> dict:
    return {"name": name, "source_ref": source_ref, "fps_limit": fps_limit}


# ---------------------------------------------------------------------------
# extract_source_topology
# ---------------------------------------------------------------------------


def test_extract_source_topology():
    """extract_source_topology преобразует cameras/regions из dict → SourceTopology."""
    data = {
        "cameras": {
            "camera_0": _make_camera(0),
        },
        "regions": {
            "camera_0_main": _make_region("camera_0"),
        },
    }
    st = extract_source_topology(data)
    assert isinstance(st, SourceTopology)
    assert "camera_0" in st.cameras
    assert "camera_0_main" in st.regions


def test_extract_source_topology_empty():
    """extract_source_topology с пустым dict → пустая SourceTopology."""
    st = extract_source_topology({})
    assert len(st.cameras) == 0
    assert len(st.regions) == 0


# ---------------------------------------------------------------------------
# diff_process_configs — added
# ---------------------------------------------------------------------------


def test_diff_process_configs_added():
    """Новые процессы в desired → processes_added."""
    current = {"processes": {}, "workers": {}}
    desired = {
        "processes": {"cam": _make_process("camera_0")},
        "workers": {"cam_main": _make_worker("cam")},
    }
    diff = diff_process_configs(current, desired)
    assert "cam" in diff["processes_added"]
    assert diff["has_changes"] is True


# ---------------------------------------------------------------------------
# diff_process_configs — removed
# ---------------------------------------------------------------------------


def test_diff_process_configs_removed():
    """Процесс удалён из desired → processes_removed."""
    current = {
        "processes": {"cam": _make_process("camera_0")},
        "workers": {"cam_main": _make_worker("cam")},
    }
    desired = {"processes": {}, "workers": {}}
    diff = diff_process_configs(current, desired)
    assert "cam" in diff["processes_removed"]
    assert diff["has_changes"] is True


# ---------------------------------------------------------------------------
# diff_process_configs — modified
# ---------------------------------------------------------------------------


def test_diff_process_configs_modified():
    """Изменённый target_interval_ms у воркера → workers_modified."""
    current = {
        "processes": {"cam": _make_process("camera_0")},
        "workers": {"cam_main": _make_worker("cam", interval=0)},
    }
    desired = {
        "processes": {"cam": _make_process("camera_0")},
        "workers": {"cam_main": _make_worker("cam", interval=50)},
    }
    diff = diff_process_configs(current, desired)
    assert "cam_main" in diff["workers_modified"]
    assert diff["has_changes"] is True


# ---------------------------------------------------------------------------
# diff_process_configs — no changes
# ---------------------------------------------------------------------------


def test_diff_process_configs_no_changes():
    """Одинаковые данные → has_changes=False."""
    state = {
        "processes": {"cam": _make_process("camera_0")},
        "workers": {"cam_main": _make_worker("cam", interval=0)},
    }
    diff = diff_process_configs(state, state)
    assert diff["has_changes"] is False
    assert diff["processes_added"] == []
    assert diff["processes_removed"] == []
    assert diff["workers_modified"] == []


# ---------------------------------------------------------------------------
# extract_process_commands — stop before create
# ---------------------------------------------------------------------------


def test_extract_process_commands_stop_before_create():
    """Порядок команд: stop удалённых → create новых."""
    current = {
        "processes": {"old": _make_process("old_proc")},
        "workers": {"old_main": _make_worker("old")},
    }
    desired = {
        "processes": {"new": _make_process("new_proc")},
        "workers": {"new_main": _make_worker("new")},
    }
    commands = extract_process_commands(current, desired)
    cmds = [c["cmd"] for c in commands]
    assert "process.stop" in cmds
    assert "process.create" in cmds
    # stop должен идти раньше create
    stop_idx = cmds.index("process.stop")
    create_idx = cmds.index("process.create")
    assert stop_idx < create_idx


# ---------------------------------------------------------------------------
# extract_process_commands — protected workers пропускаются
# ---------------------------------------------------------------------------


def test_extract_process_commands_skip_protected():
    """Protected workers не генерируют отдельные worker.create/worker.stop команды."""
    current = {"processes": {}, "workers": {}}
    desired = {
        "processes": {"cam": _make_process("camera_0")},
        "workers": {
            "cam_main": _make_worker("cam", name="main", protected=True),
            "cam_extra": _make_worker("cam", name="extra", protected=False),
        },
    }
    commands = extract_process_commands(current, desired)
    # Protected worker не должен генерировать worker.create
    worker_creates = [c for c in commands if c["cmd"] == "worker.create"]
    worker_names = [c.get("worker_name") for c in worker_creates]
    assert "main" not in worker_names  # protected → пропущен
    assert "extra" in worker_names     # не protected → создан


# ---------------------------------------------------------------------------
# extract_process_commands — from None (первый запуск)
# ---------------------------------------------------------------------------


def test_extract_process_commands_from_none():
    """current=None означает пустую систему — все процессы создаются."""
    desired = {
        "processes": {"cam": _make_process("camera_0")},
        "workers": {"cam_main": _make_worker("cam")},
    }
    commands = extract_process_commands(None, desired)
    assert any(c["cmd"] == "process.create" for c in commands)
    assert not any(c["cmd"] == "process.stop" for c in commands)


# ---------------------------------------------------------------------------
# extract_display_diff — added
# ---------------------------------------------------------------------------


def test_extract_display_diff_added():
    """Новый display → added dict содержит его ключ."""
    current = {"displays": {}}
    desired = {"displays": {"win_0": _make_display("Main", "camera_0")}}
    diff = extract_display_diff(current, desired)
    assert "win_0" in diff["added"]
    assert diff["has_changes"] is True
    assert diff["removed"] == []
    assert diff["modified"] == {}


# ---------------------------------------------------------------------------
# extract_display_diff — removed
# ---------------------------------------------------------------------------


def test_extract_display_diff_removed():
    """Удалённый display → removed list содержит его ключ."""
    current = {"displays": {"win_0": _make_display("Main", "camera_0")}}
    desired = {"displays": {}}
    diff = extract_display_diff(current, desired)
    assert "win_0" in diff["removed"]
    assert diff["has_changes"] is True
    assert diff["added"] == {}


# ---------------------------------------------------------------------------
# extract_display_diff — modified
# ---------------------------------------------------------------------------


def test_extract_display_diff_modified():
    """Изменённый fps_limit → modified dict содержит ключ с новыми данными."""
    current = {"displays": {"win_0": _make_display("Main", "camera_0", fps_limit=30)}}
    desired = {"displays": {"win_0": _make_display("Main", "camera_0", fps_limit=60)}}
    diff = extract_display_diff(current, desired)
    assert "win_0" in diff["modified"]
    assert diff["has_changes"] is True
    assert diff["modified"]["win_0"]["fps_limit"] == 60


# ---------------------------------------------------------------------------
# extract_display_diff — no changes
# ---------------------------------------------------------------------------


def test_extract_display_diff_no_changes():
    """Одинаковые displays → has_changes=False."""
    state = {"displays": {"win_0": _make_display("Main", "camera_0")}}
    diff = extract_display_diff(state, state)
    assert diff["has_changes"] is False
    assert diff["added"] == {}
    assert diff["removed"] == []
    assert diff["modified"] == {}
