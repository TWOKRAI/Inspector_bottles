"""Тесты YamlPersistenceStore."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from multiprocess_framework.modules.frontend_module.managers.yaml_persistence_store import YamlPersistenceStore


def make_store(tmp_path: Path, filename: str = "store.yaml") -> YamlPersistenceStore:
    return YamlPersistenceStore(
        tmp_path / filename,
        default_snapshot_factory=lambda: {"value": 0, "name": "default"},
    )


class TestYamlPersistenceStoreInit:
    def test_path_property(self, tmp_path):
        p = tmp_path / "s.yaml"
        store = YamlPersistenceStore(p, default_snapshot_factory=lambda: {})
        assert store.path == p


class TestYamlPersistenceStoreReadWrite:
    def test_read_raw_returns_none_when_no_file(self, tmp_path):
        store = make_store(tmp_path)
        result = store._read_raw()
        assert result is None

    def test_write_raw_creates_file(self, tmp_path):
        store = make_store(tmp_path)
        ok = store._write_raw({"version": 1, "profiles": {}})
        assert ok is True
        assert store.path.is_file()

    def test_write_and_read_roundtrip(self, tmp_path):
        store = make_store(tmp_path)
        payload = {"version": 1, "current_profile": "default", "profiles": {"default": {"v": 42}}}
        store._write_raw(payload)
        result = store._read_raw()
        assert result == payload

    def test_read_corrupt_file_returns_none(self, tmp_path):
        store = make_store(tmp_path)
        store.path.write_text(":: invalid: yaml: {", encoding="utf-8")
        result = store._read_raw()
        assert result is None

    def test_read_non_dict_yaml_returns_none(self, tmp_path):
        store = make_store(tmp_path)
        store.path.write_text("- item1\n- item2\n", encoding="utf-8")
        result = store._read_raw()
        assert result is None

    def test_write_creates_parent_dirs(self, tmp_path):
        nested = tmp_path / "a" / "b" / "store.yaml"
        store = YamlPersistenceStore(nested, default_snapshot_factory=lambda: {})
        ok = store._write_raw({"x": 1})
        assert ok is True
        assert nested.is_file()


class TestYamlPersistenceStoreSave:
    def test_save_creates_file(self, tmp_path):
        store = make_store(tmp_path)
        ok = store.save("p1", {"threshold": 0.5})
        assert ok is True
        assert store.path.is_file()

    def test_save_and_read_profile(self, tmp_path):
        store = make_store(tmp_path)
        data = {"threshold": 0.85, "fps": 30}
        store.save("my_profile", data)
        loaded = store.read("my_profile")
        assert loaded["threshold"] == pytest.approx(0.85)
        assert loaded["fps"] == 30

    def test_save_multiple_profiles(self, tmp_path):
        store = make_store(tmp_path)
        store.save("a", {"v": 1})
        store.save("b", {"v": 2})
        profiles = store.list_profiles()
        assert "a" in profiles
        assert "b" in profiles

    def test_overwrite_profile(self, tmp_path):
        store = make_store(tmp_path)
        store.save("p", {"v": 1})
        store.save("p", {"v": 99})
        loaded = store.read("p")
        assert loaded["v"] == 99

    def test_save_sets_current_profile(self, tmp_path):
        store = make_store(tmp_path)
        store.save("my_p", {"v": 1}, current_profile="my_p")
        assert store.get_current_profile_id() == "my_p"

    def test_save_preserves_other_profiles(self, tmp_path):
        store = make_store(tmp_path)
        store.save("a", {"v": 1})
        store.save("b", {"v": 2})
        store.save("a", {"v": 99})
        assert store.read("b") == {"v": 2}


class TestYamlPersistenceStoreRead:
    def test_read_missing_profile_returns_default(self, tmp_path):
        store = make_store(tmp_path)
        result = store.read("nonexistent")
        # Возвращает default_snapshot_factory() — {"value": 0, "name": "default"}
        assert result["value"] == 0

    def test_read_no_profile_id_uses_current(self, tmp_path):
        store = make_store(tmp_path)
        store.save("p1", {"v": 42}, current_profile="p1")
        result = store.read()
        assert result["v"] == 42

    def test_read_dict_returns_raw_or_none(self, tmp_path):
        store = make_store(tmp_path)
        assert store.read_dict() is None
        store.save("p", {"v": 1})
        raw = store.read_dict()
        assert raw is not None
        assert "profiles" in raw


class TestYamlPersistenceStoreListProfiles:
    def test_list_profiles_empty_store(self, tmp_path):
        store = make_store(tmp_path)
        profiles = store.list_profiles()
        assert profiles == []

    def test_list_profiles_after_save(self, tmp_path):
        store = make_store(tmp_path)
        store.save("x", {"v": 1})
        store.save("y", {"v": 2})
        profiles = store.list_profiles()
        assert "x" in profiles
        assert "y" in profiles
        assert len(profiles) == 2


class TestYamlPersistenceStoreCurrentProfile:
    def test_get_current_profile_id_default(self, tmp_path):
        store = make_store(tmp_path)
        # Нет файла → возвращает default_profile_id
        assert store.get_current_profile_id() == "default"

    def test_get_current_profile_id_after_save(self, tmp_path):
        store = make_store(tmp_path)
        store.save("custom", {"v": 1}, current_profile="custom")
        assert store.get_current_profile_id() == "custom"


class TestYamlPersistenceStoreFromDict:
    def test_read_with_from_dict(self, tmp_path):
        @dataclass
        class MyConfig:
            value: int = 0

        store = YamlPersistenceStore(
            tmp_path / "typed.yaml",
            default_snapshot_factory=lambda: {"value": 0},
            from_dict=lambda d: MyConfig(value=d.get("value", 0)),
        )
        store.save("typed", {"value": 7})
        obj = store.read("typed")
        assert isinstance(obj, MyConfig)
        assert obj.value == 7

    def test_read_with_from_dict_fallback_on_error(self, tmp_path):
        def bad_from_dict(d):
            raise ValueError("invalid")

        store = YamlPersistenceStore(
            tmp_path / "fallback.yaml",
            default_snapshot_factory=lambda: {"value": 99},
            from_dict=bad_from_dict,
        )
        store.save("p", {"value": 1})
        # from_dict падает → применяется default
        result = store.read("p")
        assert result["value"] == 99
