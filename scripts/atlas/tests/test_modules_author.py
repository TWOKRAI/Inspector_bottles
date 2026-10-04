"""Тесты автора на скрытые места резолвера (Task 0.3): порядок строк, точный файл против
префикса, граница каталога, cwd. Приёмочные тесты tester — в test_modules_map.py."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.atlas.modules import load_modules, resolve  # noqa: E402


def _row(id_: str, *paths: str) -> dict:
    return {"id": id_, "paths": list(paths), "layer": "scripts", "tier": None, "docs": [], "parent": None}


def test_exact_file_beats_shorter_prefix_in_any_order():
    parent = _row("parent", "pkg/")
    leaf = _row("leaf", "pkg/special.py")
    for rows in ([parent, leaf], [leaf, parent]):
        assert resolve("pkg/special.py", rows) == "leaf"
        assert resolve("pkg/other.py", rows) == "parent"


def test_longer_prefix_beats_exact_file_of_same_dir():
    # точный файл короче префикса соседнего каталога: побеждает длина, а не «файл против каталога»
    rows = [_row("file", "a/b"), _row("dir", "a/b/c/")]
    assert resolve("a/b/c/x.py", rows) == "dir"
    assert resolve("a/b", rows) == "file"


def test_prefix_stops_at_directory_boundary():
    rows = [_row("sql", "Services/sql/")]
    assert resolve("Services/sqlx/y.py", rows) == "other"
    assert resolve("Services/sql", rows) == "other"  # сам каталог без «/» не файл строки


def test_exact_file_is_not_a_prefix():
    rows = [_row("one", "pkg/mod.py")]
    assert resolve("pkg/mod.py.bak", rows) == "other"
    assert resolve("pkg/mod.py/x", rows) == "other"


def test_empty_inputs_never_raise():
    assert resolve("a/b.py", []) == "other"
    assert resolve("", [_row("x", "a/")]) == "other"
    assert resolve("a/b.py", [_row("empty")]) == "other"


def test_child_row_listed_before_parent_still_wins():
    child = _row("child", "pkg/sub/")
    parent = _row("parent", "pkg/")
    assert resolve("pkg/sub/f.py", [child, parent]) == "child"
    assert resolve("pkg/sub/f.py", [parent, child]) == "child"


def test_load_modules_relative_default_ignores_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # в tmp_path нет modules.yaml
    rows = load_modules()
    assert len(rows) >= 70
    assert load_modules("modules.yaml") == rows
