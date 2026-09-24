"""Независимые acceptance-тесты RED для ``RecipeService`` (Task 1b.1, ADR-RCP-007).

Источник контракта — докстринг ``modules/recipe/service.py`` (module-contract lite),
НЕ реализация (её нет — `__init__`/методы бросают ``NotImplementedError``). Сервис
приводится в движение в процессе, с fake ``RecipeFormatHook`` и fake инъекциями
(``apply_topology``, ``persist_active``, ``read_active``); реальный файловый
``ManifestStore`` не нужен для этих проверок — контракт "путь передаётся,
persist_active получает Path" проверяется через записывающую fake-функцию.

``rev`` непрозрачен для клиента — тесты сравнивают его только на равенство и
вычисляют ожидаемое значение НЕЗАВИСИМО через ``hashlib.sha256`` над байтами
файла, а не через ``service.compute_rev`` (код под тестом).
"""

from __future__ import annotations

import hashlib
import os
import threading
from pathlib import Path
from typing import Any

import pytest

from multiprocess_framework.modules.recipe.service import RecipeService


class FakeHook:
    """Формат рецепта под контролем теста: identity-нормализация + управляемый validate."""

    def normalize(self, body: dict) -> dict:
        return dict(body)

    def validate(self, body: dict) -> list[dict]:
        if body.get("bad") is True:
            return [{"path": "bad", "message": "marker true"}]
        return []

    def to_topology(self, body: dict) -> dict:
        return {"topology_from": dict(body)}


def make_service(
    recipes_dir: Path,
    *,
    hook: Any = None,
    apply_topology: Any = None,
    persist_active: Any = None,
    read_active: Any = None,
) -> RecipeService:
    return RecipeService(
        recipes_dir=recipes_dir,
        hook=hook or FakeHook(),
        apply_topology=apply_topology or (lambda args: {"success": True}),
        persist_active=persist_active or (lambda path: None),
        read_active=read_active or (lambda: None),
    )


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


# ---------------------------------------------------------------------------
# recipe.list
# ---------------------------------------------------------------------------


def test_list_equals_set_of_yaml_names(tmp_path: Path) -> None:
    (tmp_path / "alpha.yaml").write_text("a: 1\n", encoding="utf-8")
    (tmp_path / "beta.yaml").write_text("b: 2\n", encoding="utf-8")
    (tmp_path / "gamma.yml").write_text("c: 3\n", encoding="utf-8")  # НЕ .yaml — не считается
    (tmp_path / "notes.txt").write_text("ignore me\n", encoding="utf-8")

    service = make_service(tmp_path, read_active=lambda: "alpha")
    res = service.list({})

    assert res["success"] is True
    assert res["names"] == ["alpha", "beta"]  # множество ДВУХ *.yaml, отсортировано
    assert res["active"] == "alpha"


# ---------------------------------------------------------------------------
# recipe.get
# ---------------------------------------------------------------------------


def test_get_returns_rev_and_body(tmp_path: Path) -> None:
    recipe_path = tmp_path / "widget.yaml"
    recipe_path.write_text("name: widget\nvalue: 42\n", encoding="utf-8")
    expected_rev = _sha(recipe_path.read_bytes())

    service = make_service(tmp_path)
    res = service.get({"name": "widget"})

    assert res["success"] is True
    assert res["name"] == "widget"
    assert res["rev"] == expected_rev
    assert res["body"] == {"name": "widget", "value": 42}


def test_invalid_name_path_traversal_bad_request_fs_untouched(tmp_path: Path) -> None:
    (tmp_path / "keep.yaml").write_text("keep: true\n", encoding="utf-8")
    before = sorted(p.name for p in tmp_path.iterdir())

    service = make_service(tmp_path)
    res = service.get({"name": "../keep"})

    assert res["success"] is False
    assert res["error"] == "bad_request"
    after = sorted(p.name for p in tmp_path.iterdir())
    assert after == before  # защита от path traversal — ФС не тронута


# ---------------------------------------------------------------------------
# recipe.save
# ---------------------------------------------------------------------------


def test_save_stale_base_rev_conflict_file_bytes_unchanged(tmp_path: Path) -> None:
    recipe_path = tmp_path / "conf.yaml"
    recipe_path.write_text("name: conf\nversion: 1\n", encoding="utf-8")
    original_bytes = recipe_path.read_bytes()
    current_rev = _sha(original_bytes)

    service = make_service(tmp_path)
    res = service.save({"name": "conf", "base_rev": "not-the-real-rev-at-all", "body": {"name": "conf", "version": 2}})

    assert res["success"] is False
    assert res["error"] == "conflict"
    assert res["current_rev"] == current_rev
    assert recipe_path.read_bytes() == original_bytes  # отказ — байты на диске не изменились


def test_manual_disk_edit_makes_editor_save_conflict(tmp_path: Path) -> None:
    """rev считается от ТЕКУЩИХ байтов на диске — ручная правка мимо save() рвёт rev редактора."""
    recipe_path = tmp_path / "shared.yaml"
    recipe_path.write_text("name: shared\nversion: 1\n", encoding="utf-8")

    service = make_service(tmp_path)
    got = service.get({"name": "shared"})
    editor_rev = got["rev"]  # rev, который "редактор" запомнил при открытии

    # Писатель мимо recipe.save (ручная правка / автосохранение позиций) меняет файл.
    recipe_path.write_text("name: shared\nversion: 1\nextra_field_from_manual_edit: true\n", encoding="utf-8")
    new_bytes = recipe_path.read_bytes()

    res = service.save({"name": "shared", "base_rev": editor_rev, "body": {"name": "shared", "version": 2}})

    assert res["success"] is False
    assert res["error"] == "conflict"
    assert res["current_rev"] == _sha(new_bytes)
    assert recipe_path.read_bytes() == new_bytes  # отказ не тронул чужую правку


def test_invalid_body_returns_path_message_errors_file_unchanged(tmp_path: Path) -> None:
    service = make_service(tmp_path)  # base_rev=None — файла "bad.yaml" ещё нет
    res = service.save({"name": "bad", "base_rev": None, "body": {"bad": True}})

    assert res["success"] is False
    assert res["error"] == "invalid"
    assert res["errors"] == [{"path": "bad", "message": "marker true"}]
    assert not (tmp_path / "bad.yaml").exists()  # невалидный save ничего не создал


def test_crash_mid_write_leaves_old_file_intact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Крах на границе ОС (``os.replace``) — не спайка на внутреннем имени хелпера."""
    recipe_path = tmp_path / "atomic.yaml"
    recipe_path.write_text("name: atomic\nversion: 1\n", encoding="utf-8")
    original_bytes = recipe_path.read_bytes()
    current_rev = _sha(original_bytes)

    def boom(*_a: Any, **_k: Any) -> None:
        raise OSError("disk full (injected)")

    monkeypatch.setattr(os, "replace", boom)

    service = make_service(tmp_path)
    res = service.save({"name": "atomic", "base_rev": current_rev, "body": {"name": "atomic", "version": 2}})

    assert res["success"] is False
    assert res["error"] == "io_error"
    assert recipe_path.read_bytes() == original_bytes  # упавшая запись — старый файл цел


def test_two_saves_same_base_rev_exactly_one_wins(tmp_path: Path) -> None:
    """Инвариант ADR-RCP-007: CAS под локом на имя — из двух save с base_rev=None один успешен."""
    service = make_service(tmp_path)

    results: list[dict | None] = [None, None]
    errors: list[BaseException | None] = [None, None]
    barrier = threading.Barrier(2)

    def worker(i: int, value: int) -> None:
        try:
            barrier.wait(timeout=5)
            results[i] = service.save({"name": "race", "base_rev": None, "body": {"v": value}})
        except BaseException as exc:  # noqa: BLE001 - собираем, чтобы не потерять причину в потоке
            errors[i] = exc

    t0 = threading.Thread(target=worker, args=(0, 0), daemon=True)
    t1 = threading.Thread(target=worker, args=(1, 1), daemon=True)
    t0.start()
    t1.start()
    t0.join(timeout=10)
    t1.join(timeout=10)

    assert not t0.is_alive() and not t1.is_alive(), "save() завис под гонкой создания — не выполнился в дедлайн"
    if errors[0] is not None:
        raise errors[0]
    if errors[1] is not None:
        raise errors[1]

    successes = [r for r in results if r and r.get("success") is True]
    conflicts = [r for r in results if r and r.get("success") is False and r.get("error") == "conflict"]
    assert len(successes) == 1, results
    assert len(conflicts) == 1, results


# ---------------------------------------------------------------------------
# recipe.activate
# ---------------------------------------------------------------------------


def test_activate_unknown_not_found_active_unchanged(tmp_path: Path) -> None:
    apply_calls: list[dict] = []
    persist_calls: list[Path] = []

    service = make_service(
        tmp_path,
        apply_topology=lambda args: (apply_calls.append(args), {"success": True})[1],
        persist_active=lambda path: persist_calls.append(path),
        read_active=lambda: "existing",
    )
    res = service.activate({"name": "does-not-exist"})

    assert res["success"] is False
    assert res["error"] == "not_found"
    assert apply_calls == []
    assert persist_calls == []  # ни apply_topology, ни persist_active не звались


def test_activate_passes_abs_recipe_path_and_persists_only_after_apply_success(tmp_path: Path) -> None:
    recipe_path = tmp_path / "prod.yaml"
    recipe_path.write_text("name: prod\n", encoding="utf-8")

    order: list[str] = []
    apply_calls: list[dict] = []
    persist_calls: list[Path] = []
    apply_reply = {"success": True, "applied": "yes"}

    def apply_topology(args: dict) -> dict:
        order.append("apply")
        apply_calls.append(args)
        return apply_reply

    def persist_active(path: Path) -> None:
        order.append("persist")
        persist_calls.append(path)

    hook = FakeHook()
    service = make_service(
        tmp_path, hook=hook, apply_topology=apply_topology, persist_active=persist_active, read_active=lambda: None
    )
    res = service.activate({"name": "prod"})

    assert res == {"success": True, "name": "prod", "apply": apply_reply}
    assert order == ["apply", "persist"]  # persist ТОЛЬКО после успеха apply

    assert len(apply_calls) == 1
    call_args = apply_calls[0]
    got_path = Path(call_args["recipe_path"])
    assert got_path.is_absolute()
    assert got_path.samefile(recipe_path)
    assert call_args["topology_dict"] == hook.to_topology(hook.normalize({"name": "prod"}))

    assert len(persist_calls) == 1
    assert isinstance(persist_calls[0], Path)
    assert persist_calls[0].samefile(recipe_path)
