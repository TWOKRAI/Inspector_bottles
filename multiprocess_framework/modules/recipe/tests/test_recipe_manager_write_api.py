"""API записи RecipeManager (Task 1.1e): read_recipe_rev, patch_recipe(layout=), save_layout, RecipeConflict.

Приёмка по ``plans/2026-10-26_recipe-save-noise/design.md`` §9.1, §9.2, §9.5 и поправке №1 (``amendments.md``).

Правила файла:
- ожидаемые байты и ``rev`` — литералы и ``hashlib``, не результат кода под тестом;
- проверяется наблюдаемый эффект (байты файла, ``rev``, тип исключения); шпион ``yaml_patcher`` — только там,
  где сам контракт — «ровно одна запись» и «вызван инжектированный писатель»;
- вызов, который может зависнуть (ожидание межпроцессного лока), идёт в daemon-потоке с ``join(timeout)``;
- ``RecipeManager(format_hook=...)`` строится безусловно: нет параметра — красный тест, а не обход.
"""

from __future__ import annotations

import copy
import hashlib
import importlib
import os
import pickle
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml

from multiprocess_framework.modules.recipe.file_lock import RecipeLockTimeout, recipe_file_lock
from multiprocess_framework.modules.recipe.manager import RecipeManager
from multiprocess_framework.modules.recipe.recipe_engine import RecipeEngine
from multiprocess_framework.modules.recipe.yaml_io import patch_yaml_preserving
from multiprocess_framework.modules.state_store_module.core.tree_store import TreeStore

_REPO_ROOT = Path(__file__).resolve().parents[4]

SLUG = "r1"

# Рецепты записаны в стиле движка (ruamel indent 2/4/2: тире списка на 2 от ключа): иначе целая запись
# переотступит файл, и ожидаемые байты перестанут быть «одна строка».
# Рецепт без раскладки.
BASE_TEXT = "name: r1\ndescription: old\nblueprint:\n  processes:\n    - id: a\n"

# Рецепт с раскладкой в blueprint.metadata.
LAYOUT_TEXT = (
    "name: r1\n"
    "description: old\n"
    "blueprint:\n"
    "  processes:\n"
    "    - id: a\n"
    "  metadata:\n"
    "    gui_positions:\n"
    "      a: [10, 20]\n"
    "    locked_nodes:\n"
    "      - a\n"
)

_OLD_MTIME_NS = 1_000_000_000_000_000_000  # 2001-09-09; запись перезаписала бы mtime на «сейчас»


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _rc() -> Any:
    """Пакет ``recipe``; ``RecipeConflict`` берётся из него лениво — отсутствие класса красит тест, а не сбор."""
    return importlib.import_module("multiprocess_framework.modules.recipe")


def _make(tmp_path: Path, **kwargs: Any) -> tuple[RecipeManager, Path]:
    recipes_dir = tmp_path / "recipes"
    recipes_dir.mkdir(exist_ok=True)
    engine = RecipeEngine(store=TreeStore({"cameras": {}}), recipes_dir=recipes_dir)
    return RecipeManager(engine=engine, **kwargs), recipes_dir


def _put(recipes_dir: Path, text: str, slug: str = SLUG) -> bytes:
    raw = text.encode("utf-8")
    (recipes_dir / f"{slug}.yaml").write_bytes(raw)
    return raw


def _pin_mtime(path: Path) -> None:
    os.utime(path, ns=(_OLD_MTIME_NS, _OLD_MTIME_NS))
    assert path.stat().st_mtime_ns == _OLD_MTIME_NS


def _call(mgr: RecipeManager, entry: str, expected_rev: str | None, *, change: bool) -> Any:
    """Один и тот же сценарий через обе точки входа; ``change=False`` — запись того, что уже в файле."""
    if entry == "patch_recipe":
        after = yaml.safe_load(LAYOUT_TEXT)
        if change:
            after["description"] = "new"
        return mgr.patch_recipe(SLUG, after, expected_rev=expected_rev)
    positions = {"a": [99, 99]} if change else {"a": [10, 20]}
    return mgr.save_layout(SLUG, positions, ["a"], expected_rev=expected_rev)


# --- RecipeConflict / сверка rev ------------------------------------------------------------


@pytest.mark.parametrize("entry", ["patch_recipe", "save_layout"])
def test_stale_rev_conflict_file_intact(tmp_path: Path, entry: str) -> None:
    mgr, d = _make(tmp_path)
    raw = _put(d, LAYOUT_TEXT)
    stale = "0" * 64

    with pytest.raises(_rc().RecipeConflict) as info:
        _call(mgr, entry, stale, change=True)

    assert (info.value.slug, info.value.expected_rev, info.value.current_rev) == (SLUG, stale, _sha(raw))
    assert (d / f"{SLUG}.yaml").read_bytes() == raw


def test_patch_recipe_fresh_rev_writes_and_returns_new_rev(tmp_path: Path) -> None:
    mgr, d = _make(tmp_path)
    raw = _put(d, LAYOUT_TEXT)

    new_rev = _call(mgr, "patch_recipe", _sha(raw), change=True)

    expected = LAYOUT_TEXT.replace("description: old", "description: new").encode("utf-8")
    assert (d / f"{SLUG}.yaml").read_bytes() == expected
    assert new_rev == _sha(expected)


@pytest.mark.parametrize("entry", ["patch_recipe", "save_layout"])
def test_noop_keeps_rev_and_mtime(tmp_path: Path, entry: str) -> None:
    mgr, d = _make(tmp_path)
    raw = _put(d, LAYOUT_TEXT)
    path = d / f"{SLUG}.yaml"
    _pin_mtime(path)

    rev = _call(mgr, entry, _sha(raw), change=False)

    assert rev == _sha(raw)
    assert path.read_bytes() == raw
    assert path.stat().st_mtime_ns == _OLD_MTIME_NS


def test_patch_recipe_existing_file_without_rev_rejected(tmp_path: Path) -> None:
    mgr, d = _make(tmp_path)
    raw = _put(d, LAYOUT_TEXT)

    with pytest.raises(ValueError):
        _call(mgr, "patch_recipe", None, change=True)

    assert (d / f"{SLUG}.yaml").read_bytes() == raw


# --- before строит менеджер, формат-хук ----------------------------------------------------


class _CaseHook:
    """normalize: ``name`` -> нижний регистр, ``label`` -> верхний (формат-хук приложения в миниатюре)."""

    def normalize(self, body: dict) -> dict:
        out = copy.deepcopy(body)
        if "name" in out:
            out["name"] = out["name"].lower()
        if "label" in out:
            out["label"] = out["label"].upper()
        return out

    def validate(self, body: dict) -> list[dict]:
        return []

    def to_topology(self, body: dict) -> dict:
        return body


def test_patch_recipe_builds_before_from_file_with_hook(tmp_path: Path) -> None:
    mgr, d = _make(tmp_path, format_hook=_CaseHook())
    text = "name: R1\nlabel: X\ndescription: old\nblueprint:\n  processes:\n    - id: a\n"
    raw = _put(d, text)
    # Файл и ``after`` различаются только регистром ``name``/``label`` — после ``normalize`` они равны, правка одна:
    # ``description``. Без ``normalize`` у ``before`` переписался бы ``name``; без него у ``after`` — ``label``;
    # без чтения файла (``before = after``) не было бы и правки описания.
    after = {
        "name": "r1",
        "label": "x",
        "description": "new",
        "blueprint": {"processes": [{"id": "a"}]},
    }

    new_rev = mgr.patch_recipe(SLUG, after, expected_rev=_sha(raw))

    expected = text.replace("description: old", "description: new").encode("utf-8")
    assert (d / f"{SLUG}.yaml").read_bytes() == expected
    assert new_rev == _sha(expected)


# --- slug ----------------------------------------------------------------------------------


@pytest.mark.parametrize("slug", ["", "..", "a/b"], ids=["empty", "dotdot", "sep"])
def test_patch_recipe_rejects_path_like_slug(tmp_path: Path, slug: str) -> None:
    mgr, d = _make(tmp_path)
    before_tree = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))

    with pytest.raises(ValueError):
        mgr.patch_recipe(slug, {"name": "x"}, expected_rev=None)

    assert sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*")) == before_tree


# --- раскладка одной записью ---------------------------------------------------------------


def test_patch_recipe_with_layout_is_one_write(tmp_path: Path) -> None:
    calls: list[tuple[Path, dict, dict]] = []

    def spy(path: Any, before: dict, after: dict) -> bool:
        calls.append((Path(path), before, after))
        return patch_yaml_preserving(path, before, after)

    mgr, d = _make(tmp_path, yaml_patcher=spy)
    raw = _put(d, LAYOUT_TEXT)
    after = yaml.safe_load(LAYOUT_TEXT)
    after["description"] = "new"
    after["blueprint"]["processes"] = [{"id": "a"}, {"id": "b"}]

    new_rev = mgr.patch_recipe(
        SLUG,
        after,
        expected_rev=_sha(raw),
        layout=({"a": [1, 2], "b": [3, 4]}, ["b"]),
    )

    assert len(calls) == 1
    written = (d / f"{SLUG}.yaml").read_bytes()
    body = yaml.safe_load(written)
    assert body["description"] == "new"
    assert body["blueprint"]["processes"] == [{"id": "a"}, {"id": "b"}]
    assert body["blueprint"]["metadata"] == {"gui_positions": {"a": [1, 2], "b": [3, 4]}, "locked_nodes": ["b"]}
    assert new_rev == _sha(written)


@pytest.mark.parametrize(
    "text",
    [
        "name: r1\nblueprint:\n  processes:\n  - id: a\n",
        "name: r1\nblueprint:\n  processes:\n  - id: a\n  metadata:\n    name: default\n",
    ],
    ids=["no_metadata", "metadata_without_collections"],
)
def test_save_layout_empty_collections_not_created(tmp_path: Path, text: str) -> None:
    mgr, d = _make(tmp_path)
    raw = _put(d, text)

    rev = mgr.save_layout(SLUG, {}, [], expected_rev=_sha(raw))

    assert (d / f"{SLUG}.yaml").read_bytes() == raw
    assert rev == _sha(raw)


def test_save_layout_empty_locked_not_created_when_positions_written(tmp_path: Path) -> None:
    mgr, d = _make(tmp_path)
    raw = _put(d, "name: r1\nblueprint:\n  processes:\n  - id: a\n")

    mgr.save_layout(SLUG, {"a": [1, 2]}, [], expected_rev=_sha(raw))

    body = yaml.safe_load((d / f"{SLUG}.yaml").read_bytes())
    assert body["blueprint"]["metadata"] == {"gui_positions": {"a": [1, 2]}}


@pytest.mark.parametrize(
    "text",
    [None, "name: r1\nblueprint:\n  - x\n", "name: r1\ndescription: old\n"],
    ids=["no_file", "blueprint_not_mapping", "blueprint_absent"],
)
def test_save_layout_without_file_or_blueprint_no_write(tmp_path: Path, text: str | None) -> None:
    mgr, d = _make(tmp_path)
    path = d / f"{SLUG}.yaml"
    raw = None if text is None else _put(d, text)

    rev = mgr.save_layout(SLUG, {"a": [1, 2]}, ["a"], expected_rev=None if raw is None else _sha(raw))

    if raw is None:
        assert rev is None
        assert not path.exists()
    else:
        assert rev == _sha(raw)
        assert path.read_bytes() == raw


# --- инжектируемый писатель ---------------------------------------------------------------


def test_patch_recipe_uses_injected_yaml_patcher(tmp_path: Path) -> None:
    calls: list[tuple[Path, dict, dict]] = []

    def fake(path: Any, before: dict, after: dict) -> bool:
        calls.append((Path(path), before, after))
        Path(path).write_bytes(b"injected: 1\n")
        return True

    mgr, d = _make(tmp_path, yaml_patcher=fake)
    raw = _put(d, BASE_TEXT)
    after = {"name": "r1", "description": "new", "blueprint": {"processes": [{"id": "a"}]}}

    new_rev = mgr.patch_recipe(SLUG, after, expected_rev=_sha(raw))

    assert calls == [
        (
            d / f"{SLUG}.yaml",
            {"name": "r1", "description": "old", "blueprint": {"processes": [{"id": "a"}]}},
            {"name": "r1", "description": "new", "blueprint": {"processes": [{"id": "a"}]}},
        )
    ]
    assert (d / f"{SLUG}.yaml").read_bytes() == b"injected: 1\n"
    assert new_rev == _sha(b"injected: 1\n")


# --- сверка rev под межпроцессным локом (схема Task 1.1h) -----------------------------------

# Ребёнок: берёт лок, ставит маркер held, ждёт маркер release (с дедлайном), затем ПОД локом переписывает
# рецепт байтами из файла argv[4] и отпускает лок.
_CHILD = r"""
import sys, time, pathlib
from multiprocess_framework.modules.recipe.file_lock import recipe_file_lock
recipe, held, release, new_bytes_file = sys.argv[1:5]
with recipe_file_lock(recipe, timeout=10.0):
    pathlib.Path(held).write_text("1")
    end = time.monotonic() + 30.0
    while not pathlib.Path(release).exists():
        if time.monotonic() > end:
            sys.exit(3)
        time.sleep(0.01)
    pathlib.Path(recipe).write_bytes(pathlib.Path(new_bytes_file).read_bytes())
"""


def test_patch_recipe_rev_check_inside_interprocess_lock(tmp_path: Path) -> None:
    mgr, d = _make(tmp_path)
    path = d / f"{SLUG}.yaml"
    raw_v1 = _put(d, LAYOUT_TEXT)
    child_bytes = LAYOUT_TEXT.replace("description: old", "description: child").encode("utf-8")
    new_file = tmp_path / "child_new.yaml"
    new_file.write_bytes(child_bytes)
    held, release, err_file = tmp_path / "held", tmp_path / "release", tmp_path / "child_stderr.txt"
    env = dict(os.environ)
    env["PYTHONPATH"] = str(_REPO_ROOT)
    with open(err_file, "wb") as err:
        proc = subprocess.Popen(
            [sys.executable, "-c", _CHILD, str(path), str(held), str(release), str(new_file)],
            cwd=str(_REPO_ROOT),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=err,
        )
    box: dict[str, Any] = {}

    def run() -> None:
        try:
            box["result"] = _call(mgr, "patch_recipe", _sha(raw_v1), change=True)
        except BaseException as exc:  # noqa: BLE001 — тип исключения проверяет тест
            box["exc"] = exc

    t = threading.Thread(target=run, daemon=True)
    try:
        end = time.monotonic() + 60.0
        while not held.exists():
            if proc.poll() is not None:
                pytest.fail(f"ребёнок вышел до held: {err_file.read_text(errors='replace')}")
            if time.monotonic() > end:
                pytest.fail("ребёнок не взял лок за дедлайн")
            time.sleep(0.01)
        t.start()
        # Даём писателю дойти до ожидания лока (сверка rev до лока прошла бы здесь, при файле v1).
        time.sleep(0.6)
        assert t.is_alive(), f"писатель не ждёт лок ребёнка: {box}"
        release.write_text("1")
        assert proc.wait(timeout=30) == 0, err_file.read_text(errors="replace")
        t.join(timeout=30)
        assert not t.is_alive(), "писатель завис после снятия лока"
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=15)

    assert isinstance(box.get("exc"), _rc().RecipeConflict), box
    assert box["exc"].current_rev == _sha(child_bytes)
    assert path.read_bytes() == child_bytes


# --- read_recipe_rev -----------------------------------------------------------------------


def test_read_recipe_rev_returns_body_and_rev_of_same_bytes(tmp_path: Path) -> None:
    mgr, d = _make(tmp_path)
    raw = _put(d, BASE_TEXT)

    body, rev = mgr.read_recipe_rev(SLUG)

    assert body == {"name": "r1", "description": "old", "blueprint": {"processes": [{"id": "a"}]}}
    assert rev == _sha(raw)


def test_read_recipe_rev_missing_file(tmp_path: Path) -> None:
    mgr, _ = _make(tmp_path)

    assert mgr.read_recipe_rev("ghost") == (None, None)


# --- запись идёт под локом (ревью 1.1e, F1) -------------------------------------------------


@pytest.mark.parametrize("entry", ["patch_recipe", "save_layout"])
def test_yaml_patcher_runs_while_interprocess_lock_is_held(tmp_path: Path, entry: str) -> None:
    outcome: list[str] = []

    def probe(path: Any, before: dict, after: dict) -> bool:
        # Повторный вход того же процесса ждёт сам себя: если лок держит писатель, он не взят за 0.1 с.
        try:
            with recipe_file_lock(path, timeout=0.1):
                outcome.append("acquired")
        except RecipeLockTimeout:
            outcome.append("busy")
        return patch_yaml_preserving(path, before, after)

    mgr, d = _make(tmp_path, yaml_patcher=probe)
    raw = _put(d, LAYOUT_TEXT)

    _call(mgr, entry, _sha(raw), change=True)

    assert outcome == ["busy"]


# --- файл не разбирается (F2) ----------------------------------------------------------------


@pytest.mark.parametrize("entry", ["patch_recipe", "save_layout"])
def test_unparseable_file_raises_value_error_bytes_intact(tmp_path: Path, entry: str) -> None:
    mgr, d = _make(tmp_path)
    raw = _put(d, "a: [\n")

    with pytest.raises(ValueError) as info:
        _call(mgr, entry, _sha(raw), change=True)

    assert str(info.value) == f"{SLUG}: файл рецепта не разбирается — запись отменена"
    assert (d / f"{SLUG}.yaml").read_bytes() == raw


# --- каталога рецептов нет (F3) --------------------------------------------------------------


def test_patch_recipe_creates_missing_recipes_dir_and_file(tmp_path: Path) -> None:
    recipes_dir = tmp_path / "not_yet" / "recipes"
    # RecipeEngine создаёт каталог сам, поэтому менеджеру даётся заглушка с одним атрибутом ``recipes_dir``.
    mgr = RecipeManager(engine=SimpleNamespace(recipes_dir=recipes_dir))
    assert not recipes_dir.exists()

    new_rev = mgr.patch_recipe("fresh", {"name": "fresh", "blueprint": {"processes": []}}, expected_rev=None)

    written = (recipes_dir / "fresh.yaml").read_bytes()
    assert yaml.safe_load(written) == {"name": "fresh", "blueprint": {"processes": []}}
    assert new_rev == _sha(written)


# --- set -> отсортированный список (F4) -------------------------------------------------------

_HASHSEED_CHILD = r"""
import sys, pathlib
from types import SimpleNamespace
from multiprocess_framework.modules.recipe.manager import RecipeManager
d = pathlib.Path(sys.argv[1])
p = d / "r1.yaml"
raw = b"name: r1\nblueprint:\n  processes:\n    - id: a\n"
p.write_bytes(raw)
import hashlib
mgr = RecipeManager(engine=SimpleNamespace(recipes_dir=d))
mgr.save_layout("r1", {"a": [1, 2]}, {"z", "b", "m", "q", "c"}, expected_rev=hashlib.sha256(raw).hexdigest())
sys.stdout.write(p.read_bytes().hex())
"""


def test_save_layout_set_locked_nodes_written_sorted(tmp_path: Path) -> None:
    mgr, d = _make(tmp_path)
    raw = _put(d, "name: r1\nblueprint:\n  processes:\n    - id: a\n")

    mgr.save_layout(SLUG, {"a": [1, 2]}, {"z", "b", "m"}, expected_rev=_sha(raw))

    body = yaml.safe_load((d / f"{SLUG}.yaml").read_bytes())
    assert body["blueprint"]["metadata"]["locked_nodes"] == ["b", "m", "z"]


def test_save_layout_set_bytes_identical_across_hash_seed(tmp_path: Path) -> None:
    outputs = []
    for seed in ("0", "1", "2"):
        work = tmp_path / f"seed{seed}"
        work.mkdir()
        env = dict(os.environ)
        env["PYTHONPATH"] = str(_REPO_ROOT)
        env["PYTHONHASHSEED"] = seed
        proc = subprocess.run(
            [sys.executable, "-c", _HASHSEED_CHILD, str(work)],
            cwd=str(_REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert proc.returncode == 0, proc.stderr
        outputs.append(proc.stdout)

    assert outputs[0] == outputs[1] == outputs[2]
    body = yaml.safe_load(bytes.fromhex(outputs[0]))
    assert body["blueprint"]["metadata"]["locked_nodes"] == ["b", "c", "m", "q", "z"]


# --- tuple в позициях (F9) ---------------------------------------------------------------------


def test_save_layout_tuple_positions_equal_to_file_list_is_noop(tmp_path: Path) -> None:
    mgr, d = _make(tmp_path)
    raw = _put(d, LAYOUT_TEXT)
    path = d / f"{SLUG}.yaml"
    _pin_mtime(path)

    rev = mgr.save_layout(SLUG, {"a": (10, 20)}, ["a"], expected_rev=_sha(raw))

    assert rev == _sha(raw)
    assert path.read_bytes() == raw
    assert path.stat().st_mtime_ns == _OLD_MTIME_NS


def test_save_layout_tuple_positions_written_as_yaml_list(tmp_path: Path) -> None:
    mgr, d = _make(tmp_path)
    raw = _put(d, BASE_TEXT)

    mgr.save_layout(SLUG, {"a": (1, 2)}, [], expected_rev=_sha(raw))

    body = yaml.safe_load((d / f"{SLUG}.yaml").read_bytes())
    assert body["blueprint"]["metadata"] == {"gui_positions": {"a": [1, 2]}}


# --- save_layout без файла: ни каталога, ни lock-файла (F5) ---------------------------------


def test_save_layout_without_file_creates_no_lock_file(tmp_path: Path) -> None:
    mgr, d = _make(tmp_path)

    assert mgr.save_layout("ghost", {"a": [1, 2]}, ["a"], expected_rev=None) is None

    assert sorted(p.name for p in d.iterdir()) == []


def test_save_layout_without_file_but_with_rev_is_conflict(tmp_path: Path) -> None:
    mgr, d = _make(tmp_path)

    with pytest.raises(_rc().RecipeConflict) as info:
        mgr.save_layout("ghost", {"a": [1, 2]}, ["a"], expected_rev="0" * 64)

    assert (info.value.slug, info.value.expected_rev, info.value.current_rev) == ("ghost", "0" * 64, None)
    assert sorted(p.name for p in d.iterdir()) == []


# --- RecipeConflict пиклится (F7) ---------------------------------------------------------------


@pytest.mark.parametrize("current", ["c" * 64, None], ids=["file", "no_file"])
def test_recipe_conflict_pickle_round_trip(current: str | None) -> None:
    original = _rc().RecipeConflict("r1", "b" * 64, current)

    restored = pickle.loads(pickle.dumps(original))

    assert isinstance(restored, _rc().RecipeConflict)
    assert (restored.slug, restored.expected_rev, restored.current_rev) == ("r1", "b" * 64, current)
    assert str(restored) == str(original)
