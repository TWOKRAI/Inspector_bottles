"""Task 1.4 (C-30): бэкенд-писатели модуля recipe пишут дельту через движок ``yaml_io``.

``RecipeService.save`` (``recipe.save`` хаба) и ``RecipeEngine.save`` не пересоздают файл,
а применяют к нему ``before -> after``: комментарии, порядок и стиль исходника целы,
пустая дельта файл не трогает, отказ записи оставляет байты прежними.

Ожидаемые значения — литералы (не выводятся из кода под тестом); ``rev`` сверяется с
``hashlib.sha256`` независимо от ``compute_rev``. Слои: прототип не импортируется
(хук — ``FakeHook``, v1-файл — литерал ``topology:``).
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest
import yaml

from multiprocess_framework.modules.recipe.recipe_engine import RecipeEngine
from multiprocess_framework.modules.recipe.service import RecipeService
from multiprocess_framework.modules.state_store_module.core.tree_store import TreeStore


class FakeHook:
    """Как ``test_service.py``: identity-нормализация + управляемый validate."""

    def normalize(self, body: dict) -> dict:
        return dict(body)

    def validate(self, body: dict) -> list[dict]:
        if body.get("bad") is True:
            return [{"path": "bad", "message": "marker true"}]
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
    path.write_text("# keep\na: 1  # eol\nb: 2\n", encoding="utf-8")
    base_rev = _sha(path.read_bytes())

    res = _service(tmp_path).save({"name": "r", "base_rev": base_rev, "body": {"a": 1, "b": 3}})

    assert res["success"] is True
    text = path.read_text(encoding="utf-8")
    assert "# keep" in text
    assert "# eol" in text
    assert yaml.safe_load(text) == {"a": 1, "b": 3}


def test_service_save_same_body_no_write_same_rev(tmp_path: Path) -> None:
    path = tmp_path / "r.yaml"
    path.write_text("# c\na: 1\n", encoding="utf-8")
    raw_before = path.read_bytes()
    mtime_before = path.stat().st_mtime_ns
    rev_before = _sha(raw_before)

    res = _service(tmp_path).save({"name": "r", "base_rev": rev_before, "body": {"a": 1}})

    assert res["success"] is True
    assert res["rev"] == rev_before
    assert path.read_bytes() == raw_before
    assert path.stat().st_mtime_ns == mtime_before


def test_service_save_unserializable_body_bad_request_file_intact(tmp_path: Path) -> None:
    path = tmp_path / "r.yaml"
    path.write_text("a: 1\n", encoding="utf-8")
    raw_before = path.read_bytes()

    res = _service(tmp_path).save({"name": "r", "base_rev": _sha(raw_before), "body": {"a": object()}})

    assert res["success"] is False
    assert res["error"] == "bad_request"
    assert "object" not in res["message"]  # текст исключения (repr значения) в ответ не попадает
    assert path.read_bytes() == raw_before
    assert list(tmp_path.glob("*.tmp")) == []
    assert list(tmp_path.glob(".*.tmp")) == []


def test_service_save_unparseable_current_invalid_file_intact(tmp_path: Path) -> None:
    path = tmp_path / "r.yaml"
    path.write_text("a: [1\n", encoding="utf-8")
    raw_before = path.read_bytes()

    res = _service(tmp_path).save({"name": "r", "base_rev": _sha(raw_before), "body": {"a": 1}})

    assert res["success"] is False
    assert res["error"] == "invalid"
    assert path.read_bytes() == raw_before


def test_service_save_v1_topology_bad_request_file_intact(tmp_path: Path) -> None:
    path = tmp_path / "r.yaml"
    path.write_text("topology:\n  x: 1\n", encoding="utf-8")
    raw_before = path.read_bytes()

    res = _service(tmp_path).save({"name": "r", "base_rev": _sha(raw_before), "body": {"topology": {"x": 2}}})

    assert res["success"] is False
    assert res["error"] == "bad_request"
    assert path.read_bytes() == raw_before


# ---------------------------------------------------------------------------
# RecipeEngine.save
# ---------------------------------------------------------------------------

_CREATED_AT = "2020-01-01T00:00:00+00:00"

_SNAPSHOT_FILE = (
    "# header keep\n"
    'meta: {name: p, version: 2, created_at: "2020-01-01T00:00:00+00:00", description: ""}\n'
    "data:\n"
    "  cameras:\n"
    '    "0":\n'
    "      config:\n"
    "        fps: 30  # eol keep\n"
)


def _engine(tmp_path: Path, store_data: dict[str, Any], default_paths: list[str]) -> RecipeEngine:
    return RecipeEngine(store=TreeStore(store_data), recipes_dir=tmp_path, default_paths=default_paths)


def test_engine_save_keeps_comments(tmp_path: Path) -> None:
    path = tmp_path / "p.yaml"
    path.write_text(_SNAPSHOT_FILE, encoding="utf-8")
    engine = _engine(tmp_path, {"cameras": {"0": {"config": {"fps": 25}}}}, ["cameras"])

    engine.save("p")

    text = path.read_text(encoding="utf-8")
    assert "# eol keep" in text
    assert "# header keep" in text
    assert yaml.safe_load(text)["data"]["cameras"]["0"]["config"]["fps"] == 25


def test_engine_save_keeps_created_at(tmp_path: Path) -> None:
    path = tmp_path / "p.yaml"
    path.write_text(_SNAPSHOT_FILE, encoding="utf-8")
    engine = _engine(tmp_path, {"cameras": {"0": {"config": {"fps": 25}}}}, ["cameras"])

    engine.save("p")

    meta = yaml.safe_load(path.read_text(encoding="utf-8"))["meta"]
    assert meta["created_at"] == _CREATED_AT
    assert meta["name"] == "p"
    assert meta["version"] == 2


def test_engine_save_partial_snapshot_keeps_other_data_branches(tmp_path: Path) -> None:
    path = tmp_path / "p.yaml"
    path.write_text(
        'meta: {name: p, version: 2}\ndata:\n  robot:\n    config: {speed: 100}\n  cameras:\n    "0": {fps: 30}\n',
        encoding="utf-8",
    )
    engine = _engine(tmp_path, {"cameras": {"0": {"fps": 25}}, "robot": {"config": {"speed": 999}}}, [])

    engine.save("p", paths=["cameras.0.fps"])

    data = yaml.safe_load(path.read_text(encoding="utf-8"))["data"]
    assert data["robot"] == {"config": {"speed": 100}}  # путь вне snapshot_paths остался как в файле
    assert data["cameras"]["0"]["fps"] == 25


def test_engine_save_deleted_path_prunes_empty_ancestors(tmp_path: Path) -> None:
    path = tmp_path / "p.yaml"
    path.write_text(
        'meta: {name: p, version: 2}\ndata: {cameras: {"0": {regions: {"0": {deep: {x: 1}}}, config: {fps: 30}}}}\n',
        encoding="utf-8",
    )
    engine = _engine(tmp_path, {"cameras": {"0": {"config": {"fps": 30}}}}, [])

    engine.save("p", paths=["cameras.0.regions.0.deep.x"])  # в сторе пути нет

    data = yaml.safe_load(path.read_text(encoding="utf-8"))["data"]
    assert data["cameras"]["0"] == {"config": {"fps": 30}}


def test_engine_save_v3_without_meta_raises_file_intact(tmp_path: Path) -> None:
    path = tmp_path / "v3.yaml"
    path.write_text("name: v3\nversion: 3\nblueprint: {processes: []}\n", encoding="utf-8")
    raw_before = path.read_bytes()
    engine = _engine(tmp_path, {"cameras": {}}, ["cameras"])

    with pytest.raises(ValueError):
        engine.save("v3")

    assert path.read_bytes() == raw_before
