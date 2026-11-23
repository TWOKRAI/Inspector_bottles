"""REDS Task 1.4 (C-30): бэкенд-писатели модуля recipe пишут дельту через движок yaml_io.

``RecipeService.save`` и ``RecipeEngine.save`` не перезаписывают файл целиком: комментарии,
``meta.created_at`` и ветви, которых писатель не касается, остаются. Ожидаемые значения —
литералы (не из кода под тестом); ``rev`` считается независимо через ``hashlib.sha256``.
Прототип не импортируется (ADR-120): хук — ``FakeHook``, рецепт v1 — литерал ``topology:``.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest
import yaml

from multiprocess_framework.modules.recipe.recipe_engine import RecipeEngine
from multiprocess_framework.modules.recipe.service import RecipeService
from multiprocess_framework.modules.state_store_module.core.tree_store import TreeStore


class FakeHook:
    """Identity-нормализация, пустая валидация (как в test_service.py)."""

    def normalize(self, body: dict) -> dict:
        return dict(body)

    def validate(self, body: dict) -> list[dict]:
        return []

    def to_topology(self, body: dict) -> dict:
        return {"topology_from": dict(body)}


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _service(recipes_dir: Path) -> RecipeService:
    return RecipeService(
        recipes_dir=recipes_dir,
        hook=FakeHook(),
        apply_topology=lambda args: {"success": True},
        persist_active=lambda path: None,
        read_active=lambda: None,
    )


# ---------------------------------------------------------------------------
# RecipeService.save
# ---------------------------------------------------------------------------


def test_service_save_keeps_comments(tmp_path: Path) -> None:
    path = tmp_path / "r.yaml"
    raw = b"# keep\na: 1  # eol\nb: 2\n"
    path.write_bytes(raw)

    res = _service(tmp_path).save({"name": "r", "base_rev": _sha(raw), "body": {"a": 1, "b": 3}})

    assert res["success"] is True
    text = path.read_text(encoding="utf-8")
    assert "# keep" in text
    assert "# eol" in text
    assert yaml.safe_load(text) == {"a": 1, "b": 3}


def test_service_save_same_body_no_write_same_rev(tmp_path: Path) -> None:
    path = tmp_path / "r.yaml"
    raw = b"# c\na: 1\n"
    path.write_bytes(raw)
    os.utime(path, ns=(1_000_000_000_000_000_000, 1_000_000_000_000_000_000))
    mtime_before = path.stat().st_mtime_ns

    res = _service(tmp_path).save({"name": "r", "base_rev": _sha(raw), "body": {"a": 1}})

    assert res == {"success": True, "name": "r", "rev": _sha(raw)}
    assert path.read_bytes() == raw
    assert path.stat().st_mtime_ns == mtime_before


def test_service_save_unserializable_body_bad_request_file_intact(tmp_path: Path) -> None:
    path = tmp_path / "r.yaml"
    raw = b"a: 1\n"
    path.write_bytes(raw)

    res = _service(tmp_path).save({"name": "r", "base_rev": _sha(raw), "body": {"a": object()}})

    assert res["success"] is False
    assert res["error"] == "bad_request"
    assert "object" not in res["message"]
    assert path.read_bytes() == raw
    assert [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")] == []


def test_service_save_unparseable_current_invalid_file_intact(tmp_path: Path) -> None:
    path = tmp_path / "r.yaml"
    raw = b"a: [1\n"
    path.write_bytes(raw)

    res = _service(tmp_path).save({"name": "r", "base_rev": _sha(raw), "body": {"a": 1}})

    assert res["success"] is False
    assert res["error"] == "invalid"
    assert path.read_bytes() == raw


def test_service_save_v1_topology_bad_request_file_intact(tmp_path: Path) -> None:
    path = tmp_path / "r.yaml"
    raw = b"topology:\n  x: 1\n"
    path.write_bytes(raw)

    res = _service(tmp_path).save({"name": "r", "base_rev": _sha(raw), "body": {"topology": {"x": 2}}})

    assert res["success"] is False
    assert res["error"] == "bad_request"
    assert path.read_bytes() == raw


# ---------------------------------------------------------------------------
# RecipeEngine.save
# ---------------------------------------------------------------------------

_ENGINE_FILE = (
    'meta: {name: p, version: 2, created_at: "2020-01-01T00:00:00+00:00", description: ""}\n'
    "data:\n"
    "  cameras:\n"
    '    "0":\n'
    "      config:\n"
    "        fps: 30  # eol keep\n"
)


def _engine(tmp_path: Path, store_data: dict) -> RecipeEngine:
    return RecipeEngine(store=TreeStore(store_data), recipes_dir=tmp_path, recipe_version=2)


def test_engine_save_keeps_comments(tmp_path: Path) -> None:
    (tmp_path / "p.yaml").write_text(_ENGINE_FILE, encoding="utf-8")
    engine = _engine(tmp_path, {"cameras": {"0": {"config": {"fps": 25}}}})

    engine.save("p", paths=["cameras.0.config.fps"])

    text = (tmp_path / "p.yaml").read_text(encoding="utf-8")
    assert "# eol keep" in text
    assert yaml.safe_load(text)["data"]["cameras"]["0"]["config"]["fps"] == 25


def test_engine_save_keeps_created_at(tmp_path: Path) -> None:
    (tmp_path / "p.yaml").write_text(_ENGINE_FILE, encoding="utf-8")
    engine = _engine(tmp_path, {"cameras": {"0": {"config": {"fps": 25}}}})

    engine.save("p", paths=["cameras.0.config.fps"])

    loaded = yaml.safe_load((tmp_path / "p.yaml").read_text(encoding="utf-8"))
    assert loaded["meta"]["created_at"] == "2020-01-01T00:00:00+00:00"


def test_engine_save_partial_snapshot_keeps_other_data_branches(tmp_path: Path) -> None:
    raw = _ENGINE_FILE + "  renderer:\n    config:\n      draw: true\n"
    (tmp_path / "p.yaml").write_text(raw, encoding="utf-8")
    engine = _engine(tmp_path, {"cameras": {"0": {"config": {"fps": 25}}}, "renderer": {"config": {"draw": False}}})

    engine.save("p", paths=["cameras.0.config.fps"])

    loaded = yaml.safe_load((tmp_path / "p.yaml").read_text(encoding="utf-8"))
    assert loaded["data"]["renderer"] == {"config": {"draw": True}}
    assert loaded["data"]["cameras"]["0"]["config"]["fps"] == 25


def test_engine_save_deleted_path_prunes_empty_ancestors(tmp_path: Path) -> None:
    raw = (
        'meta: {name: p, version: 2, created_at: "2020-01-01T00:00:00+00:00", description: ""}\n'
        'data: {cameras: {"0": {regions: {"0": {deep: {x: 1}}}, config: {fps: 30}}}}\n'
    )
    (tmp_path / "p.yaml").write_text(raw, encoding="utf-8")
    engine = _engine(tmp_path, {"cameras": {"0": {"config": {"fps": 30}}}})

    engine.save("p", paths=["cameras.0.regions.0.deep.x"])

    loaded = yaml.safe_load((tmp_path / "p.yaml").read_text(encoding="utf-8"))
    assert loaded["data"]["cameras"]["0"] == {"config": {"fps": 30}}


def test_engine_save_v3_without_meta_raises_file_intact(tmp_path: Path) -> None:
    path = tmp_path / "v3.yaml"
    raw = b"name: v3\nversion: 3\nblueprint: {processes: []}\n"
    path.write_bytes(raw)
    engine = _engine(tmp_path, {"cameras": {"0": {"config": {"fps": 25}}}})

    with pytest.raises(ValueError):
        engine.save("v3", paths=["cameras.0.config.fps"])

    assert path.read_bytes() == raw
