# multiprocess_prototype_v3/tests/unit/test_settings_yaml_store.py
"""Unit-тесты `SettingsYamlStore` — YAML round-trip + missing-file (Phase 0, Task 0.2)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from multiprocess_prototype_v3.frontend.managers.settings_yaml_store import (
    DEFAULT_PROFILE_ID,
    SETTINGS_FILE_VERSION,
    SettingsYamlStore,
    default_profile_snapshot,
)


@pytest.fixture()
def tmp_path_yaml(tmp_path: Path) -> Path:
    return tmp_path / "settings_profiles.yaml"


class TestReadMissing:
    def test_returns_none_for_missing_file(self, tmp_path_yaml: Path) -> None:
        store = SettingsYamlStore(data_path=str(tmp_path_yaml))
        assert store.read_dict() is None

    def test_returns_none_for_malformed_yaml(self, tmp_path_yaml: Path) -> None:
        tmp_path_yaml.write_text("{ unclosed: [broken", encoding="utf-8")
        store = SettingsYamlStore(data_path=str(tmp_path_yaml))
        assert store.read_dict() is None

    def test_returns_none_for_non_mapping_root(self, tmp_path_yaml: Path) -> None:
        tmp_path_yaml.write_text("- item1\n- item2\n", encoding="utf-8")
        store = SettingsYamlStore(data_path=str(tmp_path_yaml))
        assert store.read_dict() is None


class TestRoundTrip:
    def test_save_then_read_preserves_structure(self, tmp_path_yaml: Path) -> None:
        store = SettingsYamlStore(data_path=str(tmp_path_yaml))
        profiles = {
            "default": default_profile_snapshot(),
            "fast": {**default_profile_snapshot(), "camera_count": 4, "ring_buffer_size": 2},
        }
        assert store.save(current_profile="fast", profiles=profiles) is True

        restored = store.read_dict()
        assert restored is not None
        assert restored["version"] == SETTINGS_FILE_VERSION
        assert restored["current_profile"] == "fast"
        assert set(restored["profiles"].keys()) == {"default", "fast"}
        assert restored["profiles"]["fast"]["camera_count"] == 4
        assert restored["profiles"]["fast"]["ring_buffer_size"] == 2

    def test_save_creates_missing_parent_dir(self, tmp_path: Path) -> None:
        nested = tmp_path / "a" / "b" / "c" / "settings.yaml"
        store = SettingsYamlStore(data_path=str(nested))
        assert store.save(profiles={"default": default_profile_snapshot()}) is True
        assert nested.is_file()


class TestDefaults:
    def test_default_profile_snapshot_has_schema_fields(self) -> None:
        snap = default_profile_snapshot()
        assert snap["camera_count"] == 1
        assert snap["ring_buffer_size"] == 3
        assert snap["shm_budget_mb"] == 512
        assert snap["camera_source_type"] == "simulator"

    def test_default_profile_id_is_default(self) -> None:
        assert DEFAULT_PROFILE_ID == "default"


class TestYamlFormat:
    def test_saved_yaml_uses_expected_top_keys(self, tmp_path_yaml: Path) -> None:
        store = SettingsYamlStore(data_path=str(tmp_path_yaml))
        store.save(profiles={"default": default_profile_snapshot()})
        raw = yaml.safe_load(tmp_path_yaml.read_text(encoding="utf-8"))
        assert set(raw.keys()) == {"version", "current_profile", "profiles"}
