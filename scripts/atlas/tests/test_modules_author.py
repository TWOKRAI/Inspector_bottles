"""Тесты автора на скрытые места резолвера (Task 0.3): порядок строк, точный файл против
префикса, граница каталога, cwd. Приёмочные тесты tester — в test_modules_map.py."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

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


# ---------------------------------------------------------------- слои и ошибки загрузки

_ROOT_LAYERS = {
    "tools/backend_ctl": "tools",
    "prototype/apps": "prototype",
    "tools/tools": "tools",
    "scripts": "scripts",
    "tools/utils": "tools",
    "prototype/robot": "prototype",
    "docs/examples": "docs",
}
_FRAMEWORK_MODULES_DIR = "multiprocess_framework/modules/"


def _expected_layer(row: dict, by_id: dict) -> str | None:
    """Слой строки по её классу (литералы из п.4 задачи); None — класс не распознан."""
    if row["parent"] is not None:
        return _expected_layer(by_id[row["parent"]], by_id)  # подмодуль наследует слой родителя
    id_ = row["id"]
    if id_ in _ROOT_LAYERS:
        return _ROOT_LAYERS[id_]
    if id_ == "framework_meta" or row["paths"][0].startswith(_FRAMEWORK_MODULES_DIR):
        return "framework"
    literal_ids = {"services_shared": "services", "plugins_shared": "plugins", "prototype_root": "prototype"}
    if id_ in literal_ids:
        return literal_ids[id_]
    for prefix in ("services", "plugins", "prototype"):
        if id_.startswith(f"{prefix}/"):
            return prefix
    return None


def test_layer_matches_row_class():
    rows = load_modules()
    by_id = {r["id"]: r for r in rows}
    wrong = []
    for r in rows:
        expected = _expected_layer(r, by_id)
        if expected is None or r["layer"] != expected:
            wrong.append((r["id"], r["layer"], expected))
    assert not wrong, f"слой не по классу строки (id, layer, ожидался): {wrong[:5]}"
    # сами строки-пробы существуют: иначе проверка выше могла пройти по пустому классу
    assert {"services/sql", "tools/backend_ctl", "framework_meta", "prototype_root"} <= set(by_id)


_GOOD_ROW = (
    '  - id: {id}\n    paths: ["{id}/"]\n    layer: scripts\n    tier: null\n    docs: []\n    parent: null\n'
    '    purpose: "тестовое назначение строки"\n'
)
_KEYS = ("id", "paths", "layer", "tier", "docs", "parent")


def _yaml(tmp_path: Path, rows: str, version: str = "1") -> Path:
    path = tmp_path / "m.yaml"
    path.write_text(f"version: {version}\nmodules:\n{rows}", encoding="utf-8")
    return path


def _row_without(key: str, id_: str = "cc") -> str:
    """Строка списка без ключа `key`; первая оставшаяся строка получает «- »."""
    fields = {
        "id": f"id: {id_}",
        "paths": f'paths: ["{id_}/"]',
        "layer": "layer: scripts",
        "tier": "tier: null",
        "docs": "docs: []",
        "parent": "parent: null",
        "purpose": 'purpose: "тестовое назначение строки"',
    }
    kept = [text for name, text in fields.items() if name != key]
    return "  - " + "\n    ".join(kept) + "\n"


@pytest.mark.parametrize("key", _KEYS)
def test_missing_required_key_names_key_and_index(tmp_path, key):
    rows = _GOOD_ROW.format(id="aa") + _GOOD_ROW.format(id="bb") + _row_without(key)
    with pytest.raises(ValueError) as exc:
        load_modules(_yaml(tmp_path, rows))
    message = str(exc.value)
    assert key in message
    assert re.search(r"\b2\b", message), message


def test_error_text_does_not_echo_values(tmp_path):
    marker = "SECRET_MARKER_X"
    # у строки нет layer; маркер лежит в соседних полях
    bad_row = _row_without("layer", id_=marker)
    for version, rows in (("777777", _GOOD_ROW.format(id="aa")), ("1", bad_row)):
        with pytest.raises(ValueError) as exc:
            load_modules(_yaml(tmp_path, rows, version=version))
        assert marker not in str(exc.value)
        assert "777777" not in str(exc.value)
    empty_path = (
        f'  - id: {marker}\n    paths: [""]\n    layer: scripts\n    tier: null\n    docs: []\n    parent: null\n'
        '    purpose: "тестовое назначение строки"\n'
    )
    with pytest.raises(ValueError) as exc:
        load_modules(_yaml(tmp_path, empty_path))
    assert marker not in str(exc.value)


@pytest.mark.parametrize("version", ["true", "1.0", "'1'", "null"])
def test_version_must_be_the_integer_one(tmp_path, version):
    with pytest.raises(ValueError):
        load_modules(_yaml(tmp_path, _GOOD_ROW.format(id="aa"), version=version))
