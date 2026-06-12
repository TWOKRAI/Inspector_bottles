# -*- coding: utf-8 -*-
"""Тесты RecipeDevicesStore — устройства в секции devices: активного рецепта.

Использует реальный ruamel round-trip через update_yaml_preserving (tmp-файл),
чтобы проверить сохранение комментариев и корректную перезапись списка устройств.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from multiprocess_prototype.frontend.widgets.tabs.services.devices_common.recipe_devices import (
    RecipeDevicesError,
    RecipeDevicesStore,
)
from multiprocess_prototype.recipes.yaml_io import update_yaml_preserving


class _FakeRecipeStore:
    """Минимальный RecipeStore поверх tmp-каталога (read_raw/save_raw/get_active)."""

    def __init__(self, recipe_dir: Path, active: str | None = None) -> None:
        self._dir = recipe_dir
        self._active = active

    def get_active(self) -> str | None:
        return self._active

    def set_active(self, slug: str | None) -> None:
        self._active = slug

    def read_raw(self, slug: str) -> dict | None:
        import yaml

        path = self._dir / f"{slug}.yaml"
        if not path.exists():
            return None
        return yaml.safe_load(path.read_text(encoding="utf-8"))

    def save_raw(self, slug: str, data: dict) -> None:
        update_yaml_preserving(self._dir / f"{slug}.yaml", data)


def _robot(dev_id: str) -> dict:
    return {
        "id": dev_id,
        "name": dev_id,
        "kind": "robot",
        "transport": {"type": "tcp", "host": "1.1.1.1", "port": 502, "unit_id": 1},
    }


@pytest.fixture
def recipe_with_comments(tmp_path: Path) -> Path:
    """Создать рецепт-файл с комментарием и пустой секцией devices."""
    path = tmp_path / "demo.yaml"
    path.write_text(
        "# Демо-рецепт — комментарий должен пережить save_raw\nname: Demo\nversion: 1\nblueprint:\n  processes: []\n",
        encoding="utf-8",
    )
    return path


class TestList:
    def test_list_no_active_returns_empty(self, tmp_path: Path) -> None:
        store = RecipeDevicesStore(_FakeRecipeStore(tmp_path, active=None))
        assert store.list() == []

    def test_list_reads_devices(self, tmp_path: Path, recipe_with_comments: Path) -> None:
        fake = _FakeRecipeStore(tmp_path, active="demo")
        fake.save_raw("demo", {"devices": [_robot("r1"), {"id": "v1", "kind": "vfd"}]})
        store = RecipeDevicesStore(fake)
        assert {d["id"] for d in store.list()} == {"r1", "v1"}

    def test_list_filters_by_kind(self, tmp_path: Path) -> None:
        fake = _FakeRecipeStore(tmp_path, active="demo")
        fake.save_raw("demo", {"devices": [_robot("r1"), {"id": "v1", "kind": "vfd"}]})
        store = RecipeDevicesStore(fake)
        assert [d["id"] for d in store.list(kind="vfd")] == ["v1"]

    def test_list_ignores_non_dict_entries(self, tmp_path: Path) -> None:
        fake = _FakeRecipeStore(tmp_path, active="demo")
        fake.save_raw("demo", {"devices": [_robot("r1"), "garbage", 42]})
        store = RecipeDevicesStore(fake)
        assert [d["id"] for d in store.list()] == ["r1"]


class TestUpsert:
    def test_upsert_no_active_raises(self, tmp_path: Path) -> None:
        store = RecipeDevicesStore(_FakeRecipeStore(tmp_path, active=None))
        with pytest.raises(RecipeDevicesError):
            store.upsert(_robot("r1"))

    def test_upsert_empty_id_raises(self, tmp_path: Path) -> None:
        store = RecipeDevicesStore(_FakeRecipeStore(tmp_path, active="demo"))
        with pytest.raises(RecipeDevicesError):
            store.upsert({"kind": "robot"})

    def test_upsert_adds_new(self, tmp_path: Path, recipe_with_comments: Path) -> None:
        fake = _FakeRecipeStore(tmp_path, active="demo")
        store = RecipeDevicesStore(fake)
        store.upsert(_robot("r1"))
        assert [d["id"] for d in store.list()] == ["r1"]

    def test_upsert_merges_existing(self, tmp_path: Path) -> None:
        fake = _FakeRecipeStore(tmp_path, active="demo")
        store = RecipeDevicesStore(fake)
        store.upsert(_robot("r1"))
        store.upsert({"id": "r1", "name": "Renamed"})
        devices = store.list()
        assert len(devices) == 1
        assert devices[0]["name"] == "Renamed"
        assert devices[0]["transport"]["host"] == "1.1.1.1"  # старое поле сохранилось

    def test_upsert_preserves_comments(self, tmp_path: Path, recipe_with_comments: Path) -> None:
        fake = _FakeRecipeStore(tmp_path, active="demo")
        store = RecipeDevicesStore(fake)
        store.upsert(_robot("r1"))
        text = recipe_with_comments.read_text(encoding="utf-8")
        assert "комментарий должен пережить" in text


class TestRemove:
    def test_remove_no_active_raises(self, tmp_path: Path) -> None:
        store = RecipeDevicesStore(_FakeRecipeStore(tmp_path, active=None))
        with pytest.raises(RecipeDevicesError):
            store.remove("r1")

    def test_remove_deletes_device(self, tmp_path: Path) -> None:
        fake = _FakeRecipeStore(tmp_path, active="demo")
        store = RecipeDevicesStore(fake)
        store.upsert(_robot("r1"))
        store.upsert(_robot("r2"))
        store.remove("r1")
        assert [d["id"] for d in store.list()] == ["r2"]

    def test_remove_unknown_is_noop(self, tmp_path: Path) -> None:
        fake = _FakeRecipeStore(tmp_path, active="demo")
        store = RecipeDevicesStore(fake)
        store.upsert(_robot("r1"))
        store.remove("nope")
        assert [d["id"] for d in store.list()] == ["r1"]


class TestHasActive:
    def test_has_active_true(self, tmp_path: Path) -> None:
        assert RecipeDevicesStore(_FakeRecipeStore(tmp_path, active="demo")).has_active()

    def test_has_active_false(self, tmp_path: Path) -> None:
        assert not RecipeDevicesStore(_FakeRecipeStore(tmp_path, active=None)).has_active()
