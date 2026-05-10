"""Unit-тесты Section Views (frontend/models/sections/).

Проверяем:
- ProcessesSectionView: add_process, remove_process (cascade), protected worker, add_worker,
  workers_for_process, full_snapshot
- SourcesSectionView: add_camera (auto main region), camera_id auto-increment,
  remove_camera (cascade), add_region, regions_for_camera
- DisplaysSectionView: add_display, apply_preset("quad")
- PipelineSectionView: set + get roundtrip
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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def editor() -> SystemTopologyEditor:
    return SystemTopologyEditor()


# ---------------------------------------------------------------------------
# ProcessesSectionView
# ---------------------------------------------------------------------------


class TestProcessesSectionView:
    """Тесты ProcessesSectionView."""

    def test_add_process_creates_main_worker(self, editor):
        """add_process создаёт процесс и protected main-воркер."""
        proc_key = editor.processes.add_process(
            name="camera_0",
            class_path="pkg.CameraProcess",
        )
        assert proc_key in editor._data["processes"]
        # Main worker должен быть создан автоматически
        main_key = f"{proc_key}_main"
        assert main_key in editor._data["workers"]
        worker = editor._data["workers"][main_key]
        assert worker["protected"] is True
        assert worker["process_ref"] == proc_key

    def test_remove_process_cascade(self, editor):
        """remove_process удаляет процесс и все его воркеры."""
        proc_key = editor.processes.add_process("cam", "pkg.Cam")
        # Добавляем ещё один воркер (не protected)
        worker_key = editor.processes.add_worker(proc_key, "extra", "custom")
        # Удаляем процесс
        editor.processes.remove_process(proc_key)
        assert proc_key not in editor._data["processes"]
        # Все воркеры должны быть удалены
        assert f"{proc_key}_main" not in editor._data["workers"]
        assert worker_key not in editor._data["workers"]

    def test_remove_protected_worker_raises(self, editor):
        """Попытка удалить protected воркер → ValueError."""
        proc_key = editor.processes.add_process("cam", "pkg.Cam")
        main_key = f"{proc_key}_main"
        with pytest.raises(ValueError, match="защищён"):
            editor.processes.remove_worker(main_key)

    def test_add_worker(self, editor):
        """add_worker создаёт воркер с правильным ключом и process_ref."""
        proc_key = editor.processes.add_process("cam", "pkg.Cam")
        worker_key = editor.processes.add_worker(proc_key, "capture", "loop", 100)
        assert worker_key == f"{proc_key}_capture"
        w = editor._data["workers"][worker_key]
        assert w["process_ref"] == proc_key
        assert w["name"] == "capture"
        assert w["worker_type"] == "loop"
        assert w["target_interval_ms"] == 100
        assert w["protected"] is False

    def test_add_worker_unknown_process_raises(self, editor):
        """add_worker для несуществующего процесса → KeyError."""
        with pytest.raises(KeyError):
            editor.processes.add_worker("nonexistent", "w", "custom")

    def test_workers_for_process(self, editor):
        """workers_for_process фильтрует воркеры по process_ref."""
        pk1 = editor.processes.add_process("proc1", "pkg.P1")
        pk2 = editor.processes.add_process("proc2", "pkg.P2")
        editor.processes.add_worker(pk1, "extra1", "custom")
        w_for_p1 = editor.processes.workers_for_process(pk1)
        w_for_p2 = editor.processes.workers_for_process(pk2)
        assert all(v["process_ref"] == pk1 for v in w_for_p1.values())
        assert all(v["process_ref"] == pk2 for v in w_for_p2.values())
        # proc1 должен иметь 2 воркера (main + extra1)
        assert len(w_for_p1) == 2

    def test_full_snapshot_format(self, editor):
        """full_snapshot() возвращает dict с ключами processes и workers."""
        editor.processes.add_process("cam", "pkg.Cam")
        snap = editor.processes.full_snapshot()
        assert "processes" in snap
        assert "workers" in snap
        assert isinstance(snap["processes"], dict)
        assert isinstance(snap["workers"], dict)

    def test_full_snapshot_is_copy(self, editor):
        """full_snapshot() возвращает deepcopy, мутации не меняют editor."""
        editor.processes.add_process("cam", "pkg.Cam")
        snap = editor.processes.full_snapshot()
        snap["processes"]["injected"] = {}
        assert "injected" not in editor._data["processes"]


# ---------------------------------------------------------------------------
# SourcesSectionView
# ---------------------------------------------------------------------------


class TestSourcesSectionView:
    """Тесты SourcesSectionView."""

    def test_add_camera_auto_main_region(self, editor):
        """add_camera создаёт камеру и main-регион."""
        cam_key, reg_key = editor.sources.add_camera("simulator", camera_id=0)
        assert cam_key == "camera_0"
        assert cam_key in editor._data["cameras"]
        assert reg_key == "camera_0_main"
        assert reg_key in editor._data["regions"]
        assert editor._data["regions"][reg_key]["is_main"] is True
        assert editor._data["regions"][reg_key]["camera_ref"] == cam_key

    def test_camera_id_auto_increment(self, editor):
        """add_camera без ID: первая получает 0, вторая — 1."""
        cam0, _ = editor.sources.add_camera()
        cam1, _ = editor.sources.add_camera()
        assert editor._data["cameras"][cam0]["camera_id"] == 0
        assert editor._data["cameras"][cam1]["camera_id"] == 1

    def test_remove_camera_cascade(self, editor):
        """remove_camera удаляет камеру и все её регионы."""
        cam_key, reg_key = editor.sources.add_camera("simulator", camera_id=5)
        extra_reg = editor.sources.add_region(cam_key)
        editor.sources.remove_camera(cam_key)
        assert cam_key not in editor._data["cameras"]
        assert reg_key not in editor._data["regions"]
        assert extra_reg not in editor._data["regions"]

    def test_remove_camera_not_found_raises(self, editor):
        """remove_camera для несуществующей камеры → KeyError."""
        with pytest.raises(KeyError):
            editor.sources.remove_camera("nonexistent")

    def test_add_region(self, editor):
        """add_region создаёт регион с правильным ключом и camera_ref."""
        cam_key, _ = editor.sources.add_camera("simulator", camera_id=0)
        reg_key = editor.sources.add_region(cam_key)
        assert reg_key in editor._data["regions"]
        r = editor._data["regions"][reg_key]
        assert r["camera_ref"] == cam_key
        assert r["is_main"] is False

    def test_add_region_unknown_camera_raises(self, editor):
        """add_region для несуществующей камеры → KeyError."""
        with pytest.raises(KeyError):
            editor.sources.add_region("nonexistent")

    def test_regions_for_camera(self, editor):
        """regions_for_camera фильтрует регионы по camera_ref."""
        cam0, _ = editor.sources.add_camera("simulator", camera_id=0)
        cam1, _ = editor.sources.add_camera("simulator", camera_id=1)
        editor.sources.add_region(cam0)
        r_for_cam0 = editor.sources.regions_for_camera(cam0)
        r_for_cam1 = editor.sources.regions_for_camera(cam1)
        assert all(v["camera_ref"] == cam0 for v in r_for_cam0.values())
        assert all(v["camera_ref"] == cam1 for v in r_for_cam1.values())
        # cam0 должен иметь 2 региона (main + extra)
        assert len(r_for_cam0) == 2


# ---------------------------------------------------------------------------
# DisplaysSectionView
# ---------------------------------------------------------------------------


class TestDisplaysSectionView:
    """Тесты DisplaysSectionView."""

    def test_add_display(self, editor):
        """add_display создаёт дисплей с правильным ключом."""
        key = editor.displays.add_display("Main View", "camera_0", fps_limit=25)
        assert key == "win_0"
        d = editor._data["displays"][key]
        assert d["name"] == "Main View"
        assert d["source_ref"] == "camera_0"
        assert d["fps_limit"] == 25

    def test_add_display_keys_sequential(self, editor):
        """Несколько add_display создаёт win_0, win_1, win_2..."""
        k0 = editor.displays.add_display("D0", "camera_0")
        k1 = editor.displays.add_display("D1", "camera_1")
        k2 = editor.displays.add_display("D2", "camera_2")
        assert k0 == "win_0"
        assert k1 == "win_1"
        assert k2 == "win_2"

    def test_apply_preset_quad(self, editor):
        """apply_preset("quad", 4 cameras) → 4 дисплея."""
        # Добавляем 4 камеры
        for i in range(4):
            editor.sources.add_camera("simulator", camera_id=i)
        cam_keys = list(editor._data["cameras"].keys())
        created = editor.displays.apply_preset("quad", cam_keys)
        assert len(created) == 4
        assert len(editor._data["displays"]) == 4

    def test_apply_preset_quad_clears_existing(self, editor):
        """apply_preset заменяет существующие дисплеи."""
        editor.displays.add_display("Old", "camera_99")
        for i in range(4):
            editor.sources.add_camera("simulator", camera_id=i)
        cam_keys = list(editor._data["cameras"].keys())
        editor.displays.apply_preset("quad", cam_keys)
        # Старый дисплей должен быть удалён
        assert "Old" not in [d.get("name") for d in editor._data["displays"].values()]

    def test_apply_preset_single(self, editor):
        """apply_preset("single") → 1 дисплей."""
        editor.sources.add_camera("simulator", camera_id=0)
        cam_keys = list(editor._data["cameras"].keys())
        created = editor.displays.apply_preset("single", cam_keys)
        assert len(created) == 1


# ---------------------------------------------------------------------------
# PipelineSectionView
# ---------------------------------------------------------------------------


class TestPipelineSectionView:
    """Тесты PipelineSectionView."""

    def test_set_get_pipeline(self, editor):
        """set_pipeline_for_region + get_pipeline_for_region: roundtrip."""
        config = {"steps": ["preprocess", "detect"], "threshold": 0.8}
        editor.pipeline_section.set_pipeline_for_region("camera_0_main", config)
        result = editor.pipeline_section.get_pipeline_for_region("camera_0_main")
        assert result == config

    def test_get_pipeline_missing_region(self, editor):
        """get_pipeline_for_region для несуществующего региона → пустой dict."""
        result = editor.pipeline_section.get_pipeline_for_region("nonexistent")
        assert result == {}

    def test_remove_pipeline_for_region(self, editor):
        """remove_pipeline_for_region удаляет конфиг региона."""
        editor.pipeline_section.set_pipeline_for_region("cam_0_r0", {"steps": []})
        editor.pipeline_section.remove_pipeline_for_region("cam_0_r0")
        assert editor.pipeline_section.get_pipeline_for_region("cam_0_r0") == {}

    def test_pipeline_dirty_after_set(self, editor):
        """После set_pipeline_for_region — секция pipeline становится dirty."""
        from multiprocess_prototype.registers.system_topology.schemas import SECTION_PIPELINE
        editor.pipeline_section.set_pipeline_for_region("r", {"x": 1})
        assert editor.is_dirty(SECTION_PIPELINE) is True
