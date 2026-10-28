# -*- coding: utf-8 -*-
"""Тесты RecipeDevicesStore — устройства в секции devices: активного рецепта.

Использует реальный ruamel round-trip через update_yaml_preserving (tmp-файл),
чтобы проверить сохранение комментариев и корректную перезапись списка устройств.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from multiprocess_framework.modules.recipe import RecipeConflict
from multiprocess_prototype.frontend.widgets.tabs.services.devices_common.recipe_devices import (
    RecipeDevicesError,
    RecipeDevicesStore,
)
from multiprocess_prototype.recipes.yaml_io import update_yaml_preserving


class _FakeRecipeStore:
    """Минимальный RecipeStore поверх tmp-каталога (read_canonical/save_raw/get_active, счётчик rev)."""

    def __init__(self, recipe_dir: Path, active: str | None = None) -> None:
        self._dir = recipe_dir
        self._active = active
        self._revs: dict[str, int] = {}

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

    def _current_rev(self, slug: str) -> str | None:
        return str(self._revs.get(slug, 0)) if (self._dir / f"{slug}.yaml").exists() else None

    def read_canonical(self, slug: str) -> tuple[dict | None, str | None]:
        return self.read_raw(slug), self._current_rev(slug)

    def save_raw(self, slug: str, data: dict, *, expected_rev: str | None = None) -> str:
        current = self._current_rev(slug)
        if expected_rev is not None and expected_rev != current:
            raise RecipeConflict(slug, expected_rev, current)
        update_yaml_preserving(self._dir / f"{slug}.yaml", data)
        self._revs[slug] = self._revs.get(slug, 0) + 1
        return str(self._revs[slug])


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


# ---------------------------------------------------------------------------
# C-30 Task 1.9: настоящая цепочка (RecipeStoreFromManager + RecipeManager + TopologySession)
# ---------------------------------------------------------------------------

_SLUG = "letter_robot_sim"
_CONFLICT_TEXT = "Рецепт изменён снаружи — перезагрузите его"
_PROBE_DEV = {"id": "probe_dev", "name": "Проба", "kind": "robot", "transport": {"type": "tcp", "host": "2.2.2.2"}}
# Рецепт B без секции devices (upsert создаёт её).
_RECIPE_B = b"name: B\nversion: 1\nblueprint:\n  processes: []\n  wires: []\n"


class _SpyStore:
    """Обёртка над настоящим стором: считает read_canonical и отдаёт чужой литерал-rev; запись пробрасывает."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.read_canonical_calls = 0
        self.save_calls: list[dict] = []

    def get_active(self) -> str | None:
        return self._inner.get_active()

    def read_raw(self, slug: str) -> dict | None:
        return self._inner.read_raw(slug)

    def read_canonical(self, slug: str) -> tuple[dict | None, str | None]:
        self.read_canonical_calls += 1
        doc, _real_rev = self._inner.read_canonical(slug)
        return doc, "SPY-OWN-READ-REV"

    def save_raw(self, slug: str, data: dict, **kwargs: Any) -> str:
        self.save_calls.append(dict(kwargs))
        return self._inner.save_raw(slug, data, **kwargs)


def _real_chain(tmp_path: Path, slug: str = _SLUG, data: bytes | None = None) -> tuple[Any, Path, Any]:
    """tmp-копия фикстуры A (или ``data``) + настоящая цепочка + сессия с захваченной базой файла."""
    from multiprocess_prototype.domain.topology_session import TopologySession
    from multiprocess_prototype.recipes.tests.test_save_noise_store import _put, build_chain, fixture_a_lf

    path = _put(tmp_path, slug, fixture_a_lf() if data is None else data)
    store = build_chain(tmp_path, slug)
    session = TopologySession()
    session.capture_base(slug, store.read_raw_with_rev(slug)[1])
    return store, path, session


def _file_doc(path: Path) -> dict:
    import yaml

    return yaml.safe_load(path.read_bytes().decode("utf-8"))


def _editor_topology_camera_protected() -> dict:
    """Топология фикстуры A, как её отдаёт редактор, с правкой ``camera_0.protected = True``."""
    import yaml

    from multiprocess_prototype.domain.entities import Topology
    from multiprocess_prototype.recipes.tests.test_save_noise_store import fixture_a_lf

    blueprint = yaml.safe_load(fixture_a_lf().decode("utf-8"))["blueprint"]
    topology = Topology.from_dict(blueprint).to_dict()
    next(p for p in topology["processes"] if p["process_name"] == "camera_0")["protected"] = True
    return topology


def _editor_save(store: Any, session: Any, slug: str = _SLUG) -> str:
    from multiprocess_prototype.recipes.save import save_editor_topology_to_recipe
    from multiprocess_prototype.recipes.tests.test_save_noise_store import _within

    return _within(
        60,
        save_editor_topology_to_recipe,
        store,
        slug,
        _editor_topology_camera_protected(),
        expected_rev=session.base_rev_for(slug),
    )


def test_devices_upsert_reads_canonical_and_passes_base_rev(tmp_path: Path) -> None:
    """upsert читает через read_canonical и пишет с базой сессии, а не с rev своего чтения."""
    from multiprocess_prototype.recipes.tests.test_save_noise_store import _within

    real, path, session = _real_chain(tmp_path)
    spy = _SpyStore(real)
    base_before = session.base_rev_for(_SLUG)
    assert base_before is not None and base_before != "SPY-OWN-READ-REV"

    _within(60, RecipeDevicesStore(spy, active_provider=lambda: _SLUG, session=session).upsert, dict(_PROBE_DEV))

    assert spy.read_canonical_calls == 1
    assert [c["expected_rev"] for c in spy.save_calls] == [base_before]
    assert [d["id"] for d in _file_doc(path)["devices"]] == ["robot_main", "vfd_belt", "probe_dev"]


def test_devices_upsert_after_hand_edit_conflict_bytes_intact(tmp_path: Path) -> None:
    """База захвачена -> ручная правка файла -> upsert: конфликт с текстом для пользователя, файл и база целы."""
    from multiprocess_prototype.recipes.tests.test_save_noise_store import _within

    store, path, session = _real_chain(tmp_path)
    base_before = session.base_rev_for(_SLUG)
    hand_edited = path.read_bytes().replace(b"      port: 5021\n", b"      port: 5099\n")
    assert hand_edited != path.read_bytes()
    path.write_bytes(hand_edited)
    devices = RecipeDevicesStore(store, active_provider=lambda: _SLUG, session=session)

    with pytest.raises(RecipeDevicesError) as info:
        _within(60, devices.upsert, dict(_PROBE_DEV))

    assert str(info.value) == _CONFLICT_TEXT
    assert path.read_bytes() == hand_edited
    assert session.base_rev_for(_SLUG) == base_before


def test_devices_upsert_then_editor_save_no_false_conflict(tmp_path: Path) -> None:
    """База захвачена -> upsert probe_dev -> Save редактора с базой сессии проходит (F1 ревью 1.8)."""
    from multiprocess_prototype.recipes.tests.test_save_noise_store import _within

    store, path, session = _real_chain(tmp_path)
    _within(60, RecipeDevicesStore(store, active_provider=lambda: _SLUG, session=session).upsert, dict(_PROBE_DEV))

    _editor_save(store, session)

    doc = _file_doc(path)
    assert [d["id"] for d in doc["devices"]] == ["robot_main", "vfd_belt", "probe_dev"]
    camera = next(p for p in doc["blueprint"]["processes"] if p["process_name"] == "camera_0")
    assert camera["protected"] is True


def test_devices_remove_then_editor_save_no_false_conflict(tmp_path: Path) -> None:
    """База захвачена -> remove vfd_belt -> Save редактора с базой сессии проходит."""
    from multiprocess_prototype.recipes.tests.test_save_noise_store import _within

    store, path, session = _real_chain(tmp_path)
    _within(60, RecipeDevicesStore(store, active_provider=lambda: _SLUG, session=session).remove, "vfd_belt")

    _editor_save(store, session)

    doc = _file_doc(path)
    assert [d["id"] for d in doc["devices"]] == ["robot_main"]
    camera = next(p for p in doc["blueprint"]["processes"] if p["process_name"] == "camera_0")
    assert camera["protected"] is True


def test_devices_write_other_slug_uses_own_read_rev_base_untouched(tmp_path: Path) -> None:
    """База на рецепте A, активный у Устройств B: запись в B проходит, база A прежняя, у B базы нет."""
    from multiprocess_prototype.recipes.tests.test_save_noise_store import _put, _within

    store, _path_a, session = _real_chain(tmp_path)
    path_b = _put(tmp_path, "b_recipe", _RECIPE_B)
    base_a = session.base_rev_for(_SLUG)
    assert base_a is not None

    _within(60, RecipeDevicesStore(store, active_provider=lambda: "b_recipe", session=session).upsert, dict(_PROBE_DEV))

    assert [d["id"] for d in _file_doc(path_b)["devices"]] == ["probe_dev"]
    assert session.base_rev_for(_SLUG) == base_a
    assert session.base_rev_for("b_recipe") is None


def test_devices_write_without_base_does_not_rebase(tmp_path: Path) -> None:
    """База (slug, None) — как после сбоя чтения на активации: запись проходит, база остаётся None."""
    from multiprocess_prototype.recipes.tests.test_save_noise_store import _within

    store, path, session = _real_chain(tmp_path)
    session.capture_base(_SLUG, None)

    _within(60, RecipeDevicesStore(store, active_provider=lambda: _SLUG, session=session).upsert, dict(_PROBE_DEV))

    assert [d["id"] for d in _file_doc(path)["devices"]] == ["robot_main", "vfd_belt", "probe_dev"]
    assert session.base_rev_for(_SLUG) is None


def test_devices_list_broken_yaml_returns_empty(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """Битый YAML: list() == [] (слот панели вызывает list() без try), предупреждение без содержимого файла."""
    from multiprocess_prototype.recipes.tests.test_save_noise_store import _put, build_chain

    _put(tmp_path, _SLUG, b"name: [unclosed\n  - x: : :\n")
    store = build_chain(tmp_path, _SLUG)

    with caplog.at_level("WARNING"):
        result = RecipeDevicesStore(store, active_provider=lambda: _SLUG).list()

    assert result == []
    assert any(r.levelname == "WARNING" for r in caplog.records)
    assert "unclosed" not in caplog.text


def test_devices_remove_unknown_id_without_devices_key_leaves_bytes_and_base(tmp_path: Path) -> None:
    """remove("nope") в рецепте без секции devices ничего не пишет: байты и база прежние (шум Save, C-30)."""
    from multiprocess_prototype.recipes.tests.test_save_noise_store import _within

    store, path, session = _real_chain(tmp_path, "b_recipe", _RECIPE_B)
    base_before = session.base_rev_for("b_recipe")
    assert base_before is not None

    devices = RecipeDevicesStore(store, active_provider=lambda: "b_recipe", session=session)
    _within(60, devices.remove, "nope")

    assert path.read_bytes() == _RECIPE_B
    assert session.base_rev_for("b_recipe") == base_before
