"""Unit-тесты для CameraRegistry (Phase 3, Task 3.9)."""

from __future__ import annotations

from multiprocess_prototype.frontend.managers.camera_registry import (
    CameraEntry,
    CameraRegistry,
)


class TestCameraEntry:
    def test_defaults(self):
        e = CameraEntry()
        assert e.camera_id == 0
        assert e.status == "stopped"
        assert e.fps == 0.0
        assert e.drops_count == 0

    def test_serialization(self):
        e = CameraEntry(camera_id=1, camera_type="hikvision", status="running")
        d = e.model_dump()
        assert d["camera_id"] == 1
        assert d["camera_type"] == "hikvision"


class TestCameraRegistry:
    def test_create_from_dicts(self):
        reg = CameraRegistry(
            [
                {"camera_id": 0, "camera_type": "webcam"},
                {"camera_id": 1, "camera_type": "hikvision"},
            ]
        )
        assert reg.camera_count() == 2

    def test_get_entry(self):
        reg = CameraRegistry([{"camera_id": 0, "camera_type": "webcam"}])
        entry = reg.get_entry(0)
        assert entry is not None
        assert entry.camera_type == "webcam"

    def test_get_entry_missing(self):
        reg = CameraRegistry([{"camera_id": 0, "camera_type": "webcam"}])
        assert reg.get_entry(99) is None

    def test_all_entries(self):
        reg = CameraRegistry(
            [
                {"camera_id": 1, "camera_type": "hikvision"},
                {"camera_id": 0, "camera_type": "webcam"},
            ]
        )
        entries = reg.all_entries()
        assert len(entries) == 2
        # Сортировка по camera_id
        assert entries[0].camera_id == 0
        assert entries[1].camera_id == 1

    def test_update_status(self):
        reg = CameraRegistry([{"camera_id": 0, "camera_type": "webcam"}])
        reg.update_status(0, "running")
        assert reg.get_entry(0).status == "running"

    def test_update_fps(self):
        reg = CameraRegistry([{"camera_id": 0, "camera_type": "webcam"}])
        reg.update_fps(0, 29.5)
        assert reg.get_entry(0).fps == 29.5

    def test_update_drops(self):
        reg = CameraRegistry([{"camera_id": 0, "camera_type": "webcam"}])
        reg.update_drops(0, 42)
        assert reg.get_entry(0).drops_count == 42

    def test_callback_on_update(self):
        reg = CameraRegistry([{"camera_id": 0, "camera_type": "webcam"}])
        events = []
        reg.add_callback(lambda cid, field, val: events.append((cid, field, val)))
        reg.update_status(0, "running")
        assert len(events) == 1
        assert events[0] == (0, "status", "running")

    def test_remove_callback(self):
        reg = CameraRegistry([{"camera_id": 0, "camera_type": "webcam"}])
        events = []
        cb = lambda cid, field, val: events.append((cid, field, val))
        reg.add_callback(cb)
        reg.remove_callback(cb)
        reg.update_status(0, "running")
        assert len(events) == 0

    def test_empty_registry(self):
        reg = CameraRegistry()
        assert reg.camera_count() == 0
        assert reg.all_entries() == []
