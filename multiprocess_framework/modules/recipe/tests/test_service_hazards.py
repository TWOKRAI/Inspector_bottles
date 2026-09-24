"""Авторские hazard-тесты ``RecipeService`` (Task 1b.1) — то, что acceptance тестера не покрыл.

Что может сломаться в ЭТОМ механизме:

* ``recipe.delete`` удалит активный рецепт (следующий boot упадёт на отсутствующем
  файле) или удалит поверх чужой правки.
* ``recipe.validate`` молча выберет одно из двух (``body`` и ``name``) — клиент
  проверит не то, что думает.
* ``recipe.activate`` запишет манифест при отказе ``topology.apply`` (включая
  debounce) — после рестарта поднимется рецепт, который ни разу не работал.
* ``persist_active`` бросил — наружу вылетело исключение вместо ответа, и клиент
  не узнал, что топология УЖЕ применена.
* Лок имени, удержанный на ``apply_topology``, — дедлок, если применение (или
  параллельный клиент) трогает тот же рецепт.
* Упавшая атомарная запись оставляет tmp-мусор в каталоге рецептов (он не
  ``*.yaml``, но копится).
"""

from __future__ import annotations

import hashlib
import os
import threading
from pathlib import Path
from typing import Any

import pytest
import yaml

from multiprocess_framework.modules.recipe.service import COMMANDS, RecipeService


class Hook:
    def normalize(self, body: dict) -> dict:
        out = dict(body)
        out.setdefault("version", 2)  # не identity: проверяем, что на диск идёт normalize(body)
        return out

    def validate(self, body: dict) -> list[dict]:
        return [{"path": "bad", "message": "marker"}] if body.get("bad") else []

    def to_topology(self, body: dict) -> dict:
        return {"t": body.get("name")}


def make(tmp: Path, **kw: Any) -> RecipeService:
    return RecipeService(
        recipes_dir=tmp,
        hook=kw.get("hook") or Hook(),
        apply_topology=kw.get("apply_topology") or (lambda a: {"success": True}),
        persist_active=kw.get("persist_active") or (lambda p: None),
        read_active=kw.get("read_active") or (lambda: None),
    )


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def write(tmp: Path, name: str, text: str = "name: x\n") -> Path:
    p = tmp / f"{name}.yaml"
    p.write_text(text, encoding="utf-8")
    return p


# --- поверхность ------------------------------------------------------------


def test_handlers_keys_are_commands(tmp_path: Path) -> None:
    assert tuple(make(tmp_path).handlers()) == COMMANDS


def test_handler_never_raises_when_hook_raises(tmp_path: Path) -> None:
    class Boom(Hook):
        def normalize(self, body: dict) -> dict:
            raise RuntimeError("hook broke")

    write(tmp_path, "a")
    res = make(tmp_path, hook=Boom()).get({"name": "a"})
    assert res["success"] is False and res["error"] == "io_error"
    assert "hook broke" in res["message"]


# --- имя рецепта (ревью 1b.1: BLOCKER) --------------------------------------


@pytest.mark.parametrize("name", ["D:evil", ".hidden", "a/b", "a\\b", "", " lead", "..", "../x"])
def test_bad_names_rejected_on_every_command(tmp_path: Path, name: str) -> None:
    svc = make(tmp_path)
    for cmd, args in [
        (svc.get, {"name": name}),
        (svc.save, {"name": name, "base_rev": None, "body": {"x": 1}}),
        (svc.delete, {"name": name}),
        (svc.activate, {"name": name}),
        (svc.validate, {"name": name}),
    ]:
        assert cmd(args)["error"] == "bad_request", (cmd.__name__, name)
    assert list(tmp_path.iterdir()) == []


def test_symlink_out_of_dir_rejected(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "real.yaml").write_text("x: 1\n", encoding="utf-8")
    recipes = tmp_path / "recipes"
    recipes.mkdir()
    (recipes / "link.yaml").symlink_to(outside / "real.yaml")
    assert make(recipes).get({"name": "link"})["error"] == "bad_request"


@pytest.mark.parametrize("name", ["v1..2", "рецепт_1", "my recipe-2.b"])
def test_good_names_roundtrip_and_list_get_agree(tmp_path: Path, name: str) -> None:
    svc = make(tmp_path)
    assert svc.save({"name": name, "base_rev": None, "body": {"x": 1}})["success"] is True
    assert (tmp_path / f"{name}.yaml").is_file()
    assert svc.list({})["names"] == [name]
    assert svc.get({"name": name})["success"] is True


def test_list_hides_names_get_would_refuse(tmp_path: Path) -> None:
    (tmp_path / ".hidden.yaml").write_text("x: 1\n", encoding="utf-8")
    write(tmp_path, "ok")
    svc = make(tmp_path)
    names = svc.list({})["names"]
    assert names == ["ok"]
    assert all(svc.get({"name": n})["success"] for n in names)


# --- recipe.delete ----------------------------------------------------------


def test_delete_removes_file(tmp_path: Path) -> None:
    p = write(tmp_path, "gone")
    assert make(tmp_path).delete({"name": "gone"}) == {"success": True, "name": "gone"}
    assert not p.exists()


def test_delete_missing_is_not_found(tmp_path: Path) -> None:
    res = make(tmp_path).delete({"name": "nope"})
    assert res["error"] == "not_found"


def test_delete_active_is_refused_file_intact(tmp_path: Path) -> None:
    p = write(tmp_path, "live")
    before = p.read_bytes()
    res = make(tmp_path, read_active=lambda: "live").delete({"name": "live"})
    assert res["success"] is False and res["error"] == "active"
    assert p.read_bytes() == before


def test_delete_stale_base_rev_is_conflict_file_intact(tmp_path: Path) -> None:
    p = write(tmp_path, "d")
    res = make(tmp_path).delete({"name": "d", "base_rev": "stale"})
    assert res["error"] == "conflict" and res["current_rev"] == sha(p.read_bytes())
    assert p.exists()


def test_delete_with_current_base_rev_succeeds(tmp_path: Path) -> None:
    p = write(tmp_path, "d")
    assert make(tmp_path).delete({"name": "d", "base_rev": sha(p.read_bytes())})["success"] is True
    assert not p.exists()


# --- recipe.validate --------------------------------------------------------


@pytest.mark.parametrize("args", [{}, {"name": "a", "body": {}}])
def test_validate_needs_exactly_one_of_body_name(tmp_path: Path, args: dict) -> None:
    write(tmp_path, "a")
    assert make(tmp_path).validate(args)["error"] == "bad_request"


def test_validate_body_and_by_name(tmp_path: Path) -> None:
    svc = make(tmp_path)
    assert svc.validate({"body": {"bad": True}}) == {
        "success": True,
        "valid": False,
        "errors": [{"path": "bad", "message": "marker"}],
    }
    write(tmp_path, "ok")
    assert svc.validate({"name": "ok"}) == {"success": True, "valid": True, "errors": []}
    assert svc.validate({"name": "missing"})["error"] == "not_found"


def test_validate_writes_nothing(tmp_path: Path) -> None:
    make(tmp_path).validate({"body": {"name": "x"}})
    assert list(tmp_path.iterdir()) == []


# --- recipe.save ------------------------------------------------------------


def test_save_writes_normalized_body_and_rev_of_new_bytes(tmp_path: Path) -> None:
    res = make(tmp_path).save({"name": "n", "base_rev": None, "body": {"name": "n"}})
    raw = (tmp_path / "n.yaml").read_bytes()
    assert res == {"success": True, "name": "n", "rev": sha(raw)}
    assert yaml.safe_load(raw) == {"name": "n", "version": 2}


def test_save_create_over_existing_is_conflict(tmp_path: Path) -> None:
    p = write(tmp_path, "e")
    res = make(tmp_path).save({"name": "e", "base_rev": None, "body": {"x": 1}})
    assert res["error"] == "conflict" and res["current_rev"] == sha(p.read_bytes())


def test_save_without_base_rev_key_is_bad_request(tmp_path: Path) -> None:
    res = make(tmp_path).save({"name": "e", "body": {"x": 1}})
    assert res["error"] == "bad_request"
    assert list(tmp_path.iterdir()) == []


def test_failed_atomic_write_leaves_no_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    p = write(tmp_path, "a")

    def boom(*_a: Any, **_k: Any) -> None:
        raise OSError("injected")

    monkeypatch.setattr(os, "replace", boom)
    res = make(tmp_path).save({"name": "a", "base_rev": sha(p.read_bytes()), "body": {"x": 1}})
    assert res["error"] == "io_error"
    assert sorted(q.name for q in tmp_path.iterdir()) == ["a.yaml"]


# --- recipe.activate --------------------------------------------------------


@pytest.mark.parametrize(
    "reply",
    [
        {"success": False, "error": "boom"},
        {"success": False, "debounced": True, "error": "debounce cooldown"},
        {"error": "topology_dict required"},  # без success — тоже отказ
    ],
)
def test_activate_apply_failure_no_persist(tmp_path: Path, reply: dict) -> None:
    write(tmp_path, "r")
    persisted: list[Path] = []
    res = make(tmp_path, apply_topology=lambda a: reply, persist_active=persisted.append).activate({"name": "r"})
    assert res["success"] is False and res["error"] == "apply_failed"
    assert res["apply"] == reply
    assert persisted == []


def test_activate_persist_raising_is_io_error_with_apply(tmp_path: Path) -> None:
    write(tmp_path, "r")
    applied = {"success": True, "applied": 1}

    def persist(_p: Path) -> None:
        raise PermissionError("manifest read-only")

    res = make(tmp_path, apply_topology=lambda a: applied, persist_active=persist).activate({"name": "r"})
    assert res["success"] is False and res["error"] == "io_error"
    assert res["apply"] == applied
    assert "manifest read-only" in res["message"]


def test_activate_invalid_does_not_apply(tmp_path: Path) -> None:
    write(tmp_path, "bad", "bad: true\n")
    calls: list[dict] = []
    res = make(tmp_path, apply_topology=lambda a: calls.append(a) or {"success": True}).activate({"name": "bad"})
    assert res["error"] == "invalid" and res["errors"] == [{"path": "bad", "message": "marker"}]
    assert calls == []


def test_activate_does_not_hold_name_lock_during_apply(tmp_path: Path) -> None:
    """Применение, которое само сохраняет тот же рецепт, не должно зависнуть."""
    p = write(tmp_path, "r")
    svc_box: list[RecipeService] = []
    inner: list[dict] = []

    def apply_topology(_a: dict) -> dict:
        inner.append(svc_box[0].save({"name": "r", "base_rev": sha(p.read_bytes()), "body": {"x": 2}}))
        return {"success": True}

    svc = make(tmp_path, apply_topology=apply_topology)
    svc_box.append(svc)
    out: list[dict] = []
    t = threading.Thread(target=lambda: out.append(svc.activate({"name": "r"})), daemon=True)
    t.start()
    t.join(timeout=5)
    assert not t.is_alive(), "activate завис: лок имени удержан на apply_topology"
    assert out[0]["success"] is True and inner[0]["success"] is True
