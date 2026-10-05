"""Приёмочные тесты modules.yaml v0 и резолвера scripts/atlas/modules.py (Task 0.3, RED).

Источник истины — plans/2026-10-04_atlas/tasks/0.3.md (DESIGN и REDS, ред. 3).
Ожидаемые значения берутся из репозитория (git ls-files, таблица §1
MODULE_TIERS.md) или записаны литералами. Ничто не выводится из кода под тестом.

Резолвер импортируется ВНУТРИ тестов (`_atlas()`), чтобы отсутствие модуля давало
по одному красному на каждый из 11 тестов, а не одну ошибку сбора.
"""

from __future__ import annotations

import re
import subprocess
import sys
import time
from functools import lru_cache
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]  # <repo>/scripts/atlas/tests/<file>
MODULES_YAML = ROOT / "modules.yaml"
MODULE_TIERS_MD = ROOT / "multiprocess_framework" / "docs" / "MODULE_TIERS.md"

MIN_ROWS = 70
LAYERS = {"framework", "services", "plugins", "prototype", "scripts", "tools", "docs", "infra"}
TIERS = {"core", "optional", "frozen"}
FRAMEWORK_MODULE_DIR = re.compile(r"^multiprocess_framework/modules/([^/]+)/$")
DOC_NAMES = ("README.md", "STATUS.md", "DECISIONS.md")

# Семь корней п.3 п.4: каталог -> id
ROOT_UNITS = {
    "backend_ctl/": "tools/backend_ctl",
    "apps/": "prototype/apps",
    "tools/": "tools/tools",
    "scripts/": "scripts",
    "Utils/": "tools/utils",
    "robot/": "prototype/robot",
    "examples/": "docs/examples",
}
# Корни п.4 для проверки other_allowed (кроме семи — четыре слоя)
LAYER_ROOTS = ("Services/", "Plugins/", "multiprocess_framework/", "multiprocess_prototype/")
SERVICE_IDS = {"framework_meta", "services_shared", "plugins_shared", "prototype_root"}
# 14 строк, которые правило п.5 даёт на ce3920df2 (литерал из задачи)
EXPECTED_SUBMODULES = {
    "frontend_module/components",
    "frontend_module/components/_examples",
    "frontend_module/components/base",
    "frontend_module/core",
    "frontend_module/widgets",
    "frontend_module/widgets/chrome",
    "frontend_module/widgets/tabs",
    "process_module/generic",
    "prototype/frontend/widgets",
    "prototype/frontend/widgets/tabs",
    "prototype/frontend/widgets/tabs/pipeline",
    "prototype/frontend/widgets/tabs/services",
    "prototype/frontend/widgets/tabs/settings",
    "tools/backend_ctl/probes",
}


# ---------------------------------------------------------------- хелперы


def _atlas():
    """Импорт резолвера. Нет модуля -> ModuleNotFoundError внутри теста."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from scripts.atlas import modules  # noqa: PLC0415

    return modules


@lru_cache(maxsize=1)
def _tracked() -> tuple[str, ...]:
    out = subprocess.run(
        ["git", "ls-files"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        timeout=5,
    ).stdout
    return tuple(line for line in out.splitlines() if line)


def _is_test_py(path: str) -> bool:
    """§6: «нетестовый .py» — отрицание этого предиката."""
    parts = path.split("/")
    name = parts[-1]
    return "tests" in parts or name.startswith("test_") or name == "conftest.py"


@lru_cache(maxsize=1)
def _non_test_py() -> tuple[str, ...]:
    return tuple(p for p in _tracked() if p.endswith(".py") and not _is_test_py(p))


def _load() -> list[dict]:
    rows = _atlas().load_modules(MODULES_YAML)
    assert len(rows) >= MIN_ROWS, f"modules.yaml: {len(rows)} строк, ожидалось >= {MIN_ROWS}"
    return rows


def _other_allowed() -> list[str]:
    import yaml  # noqa: PLC0415

    data = yaml.safe_load(MODULES_YAML.read_text(encoding="utf-8"))
    return list(data["other_allowed"])


def _under(path: str, element: str) -> bool:
    """Элемент с '/' на конце — префикс; без '/' — точный файл."""
    return path.startswith(element) if element.endswith("/") else path == element


def _dir_counts() -> dict[str, int]:
    """Сколько нетестовых .py в поддереве каждого каталога (ключ — с '/' на конце)."""
    counts: dict[str, int] = {}
    for p in _non_test_py():
        parts = p.split("/")
        for k in range(1, len(parts)):
            key = "/".join(parts[:k]) + "/"
            counts[key] = counts.get(key, 0) + 1
    return counts


def _units() -> dict[str, str]:
    """Каталоги-единицы п.4 (без служебных строк): каталог -> id, только с >= 1 нетестовым .py."""
    counts = _dir_counts()
    units: dict[str, str] = {}
    for d in counts:
        parts = d.rstrip("/").split("/")
        if len(parts) == 3 and parts[:2] == ["multiprocess_framework", "modules"] and parts[2] != "tests":
            units[d] = parts[2]
        elif len(parts) == 2 and parts[0] == "Services" and parts[1] not in {"tests", "_shared"}:
            units[d] = f"services/{parts[1]}"
        elif len(parts) == 2 and parts[0] == "Plugins" and parts[1] not in {"tests", "_shared"}:
            units[d] = f"plugins/{parts[1]}"
        elif len(parts) == 2 and parts[0] == "multiprocess_prototype" and parts[1] != "tests":
            units[d] = f"prototype/{parts[1]}"
        elif d in ROOT_UNITS:
            units[d] = ROOT_UNITS[d]
    return units


def _expected_submodules() -> dict[str, tuple[str, str]]:
    """Правило п.5: id подмодуля -> (каталог, id родителя). Считается по git ls-files."""
    counts = _dir_counts()
    result: dict[str, tuple[str, str]] = {}
    queue = list(_units().items())
    while queue:
        unit_dir, unit_id = queue.pop()
        if counts.get(unit_dir, 0) < 60:
            continue
        prefix_len = len(unit_dir)
        children = {d for d in counts if d.startswith(unit_dir) and d.count("/") == unit_dir.count("/") + 1}
        for cand in sorted(children):
            if counts[cand] < 15:
                continue
            sub_id = f"{unit_id}/{cand[prefix_len:].rstrip('/')}"
            result[sub_id] = (cand, unit_id)
            queue.append((cand, sub_id))
    return result


def _is_framework_module_row(row: dict) -> bool:
    return row["parent"] is None and any(FRAMEWORK_MODULE_DIR.match(p) for p in row["paths"])


def _tiers_table() -> dict[str, str]:
    """Разбор таблицы §1 MODULE_TIERS.md: модуль -> ярус."""
    text = MODULE_TIERS_MD.read_text(encoding="utf-8")
    start = text.index("## 1. Карта")
    end = text.index("\n---", start)
    table: dict[str, str] = {}
    for line in text[start:end].splitlines():
        m = re.match(r"^\|\s*`([A-Za-z0-9_]+)`\s*\|\s*(core|optional|frozen)\s*\|", line)
        if m:
            table[m.group(1)] = m.group(2)
    return table


# ---------------------------------------------------------------- тесты


def test_every_source_file_has_a_module():
    mods = _atlas()
    rows = _load()
    allowed = _other_allowed()
    assert len(allowed) <= 10, f"other_allowed слишком широк: {len(allowed)} элементов"
    assert "" not in allowed

    roots = LAYER_ROOTS + tuple(ROOT_UNITS)
    for element in allowed:
        for root in roots:
            assert not element.startswith(root), f"other_allowed {element!r} лежит внутри корня {root!r}"
            if element.endswith("/"):
                assert not root.startswith(element), f"other_allowed {element!r} содержит корень {root!r}"

    orphans = [p for p in _non_test_py() if mods.resolve(p, rows) == "other" and not any(_under(p, e) for e in allowed)]
    assert not orphans, f"{len(orphans)} исходников без модуля, например {orphans[:5]}"


def test_framework_tiers_match_module_tiers_md():
    rows = _load()
    table = _tiers_table()
    assert len(table) == 27, f"таблица §1 дала {len(table)} строк, ожидалось 27"

    fw_rows = [r for r in rows if _is_framework_module_row(r)]
    assert {r["id"] for r in fw_rows} == set(table)
    for r in fw_rows:
        dirname = next(FRAMEWORK_MODULE_DIR.match(p).group(1) for p in r["paths"] if FRAMEWORK_MODULE_DIR.match(p))
        assert r["id"] == dirname, f"id {r['id']!r} не совпадает с каталогом {dirname!r}"
        assert r["tier"] == table[r["id"]], f"{r['id']}: ярус {r['tier']!r}, в таблице {table[r['id']]!r}"


def test_no_dead_rows():
    rows = _load()
    tracked = _tracked()
    tracked_set = set(tracked)
    dead = []
    for r in rows:
        for element in r["paths"]:
            if element.endswith("/"):
                if not any(p.startswith(element) for p in tracked):
                    dead.append((r["id"], element))
            elif element not in tracked_set:
                dead.append((r["id"], element))
    assert not dead, f"мёртвые элементы paths: {dead[:5]}"


def test_docs_exist_and_complete():
    rows = _load()
    tracked_set = set(_tracked())
    for r in rows:
        for doc in r["docs"]:
            assert (ROOT / doc).is_file(), f"{r['id']}: docs ссылается на несуществующий {doc}"
        for element in r["paths"]:
            if not element.endswith("/"):
                continue
            for name in DOC_NAMES:
                candidate = element + name
                if candidate in tracked_set:
                    assert candidate in r["docs"], f"{r['id']}: {candidate} лежит в каталоге строки, но не в docs"


def test_ids_unique_and_parents_valid():
    rows = _load()
    ids = [r["id"] for r in rows]
    assert len(ids) == len(set(ids)), "повторяющиеся id"
    assert SERVICE_IDS <= set(ids), f"нет служебных строк: {SERVICE_IDS - set(ids)}"

    owners: dict[str, list[str]] = {}
    for r in rows:
        for element in r["paths"]:
            owners.setdefault(element, []).append(r["id"])
    shared = {e: o for e, o in owners.items() if len(o) > 1}
    assert not shared, f"элемент paths в нескольких строках: {shared}"

    by_id = {r["id"]: r for r in rows}
    for r in rows:
        if r["parent"] is None:
            continue
        assert r["parent"] in by_id, f"{r['id']}: parent {r['parent']!r} не существует"
        parent_dirs = [p for p in by_id[r["parent"]]["paths"] if p.endswith("/")]
        for element in r["paths"]:
            assert any(element.startswith(pd) for pd in parent_dirs), (
                f"{r['id']}: путь {element!r} вне путей родителя {r['parent']!r}"
            )

    for unit_dir, unit_id in _units().items():
        holders = [r for r in rows if unit_dir in r["paths"]]
        assert len(holders) == 1, f"{unit_dir}: {len(holders)} строк с этим элементом (ожидалась ровно одна)"
        assert holders[0]["parent"] is None, f"{unit_dir}: строка {holders[0]['id']!r} имеет parent"
        assert holders[0]["id"] == unit_id, f"{unit_dir}: id {holders[0]['id']!r}, ожидался {unit_id!r}"

    allowed_service_dirs = {"multiprocess_framework/docs/", "Plugins/_shared/"}
    for r in rows:
        if r["id"] in SERVICE_IDS:
            dirs = {p for p in r["paths"] if p.endswith("/")}
            assert dirs <= allowed_service_dirs, f"{r['id']}: катч-олл каталоги {dirs - allowed_service_dirs}"


def test_longest_prefix_wins():
    mods = _atlas()
    rows = _load()
    for ordering in (rows, list(reversed(rows))):
        assert (
            mods.resolve("multiprocess_framework/modules/process_module/generic/pipeline_executor.py", ordering)
            == "process_module/generic"
        )
        assert mods.resolve("multiprocess_framework/modules/process_module/__init__.py", ordering) == "process_module"
        assert mods.resolve("README.md", ordering) == "other"


def test_layer_and_tier_values():
    rows = _load()
    for r in rows:
        assert r["layer"] in LAYERS, f"{r['id']}: layer {r['layer']!r}"
        if _is_framework_module_row(r):
            assert r["tier"] in TIERS, f"{r['id']}: tier {r['tier']!r}"
        else:
            assert r["tier"] is None, f"{r['id']}: tier {r['tier']!r} вне строки модуля framework"


def test_submodule_rule_holds():
    rows = _load()
    expected = _expected_submodules()
    assert "process_module/generic" in expected
    assert "prototype/frontend/widgets/tabs/pipeline" in expected
    assert EXPECTED_SUBMODULES <= set(expected), f"правило п.5 не даёт: {EXPECTED_SUBMODULES - set(expected)}"

    by_id = {r["id"]: r for r in rows}
    missing = sorted(set(expected) - set(by_id))
    assert not missing, f"нет строк подмодулей: {missing}"
    for sub_id, (sub_dir, parent_id) in expected.items():
        row = by_id[sub_id]
        assert sub_dir in row["paths"], f"{sub_id}: каталог {sub_dir} не в paths {row['paths']}"
        assert row["parent"] == parent_id, f"{sub_id}: parent {row['parent']!r}, ожидался {parent_id!r}"


def test_resolve_all_files_fast():
    mods = _atlas()
    rows = _load()
    tracked = _tracked()
    started = time.perf_counter()
    results = [mods.resolve(p, rows) for p in tracked]
    elapsed = time.perf_counter() - started
    assert elapsed < 1.0, f"резолв {len(tracked)} путей занял {elapsed:.3f} с (лимит 1 с)"
    resolved = sum(1 for r in results if r != "other")
    # быстрый "всё в other" не должен проходить: под корнями модулей 4339 путей (замер на 3a0b4b4dd)
    assert resolved >= 3000, f"только {resolved} путей получили модуль"


def test_windows_separators():
    mods = _atlas()
    rows = _load()
    assert mods.resolve("Services\\sql\\x.py", rows) == "services/sql"
    assert mods.resolve("Services/sql/x.py", rows) == "services/sql"


_VALID_ROW = "  - id: {id}\n    paths: [{paths}]\n    layer: {layer}\n    tier: null\n    docs: []\n    parent: null\n"


def _write_yaml(path: Path, rows: str, version: int = 1) -> Path:
    path.write_text(f"version: {version}\nother_allowed: []\nmodules:\n{rows}", encoding="utf-8")
    return path


def test_load_errors(tmp_path):
    mods = _atlas()

    # контроль: корректный файл грузится (иначе ValueError ниже ничего не доказывает)
    good_rows = (
        _VALID_ROW.format(id="aa", paths='"aa/"', layer="scripts")
        + _VALID_ROW.format(id="bb", paths='"bb/"', layer="scripts")
        + _VALID_ROW.format(id="cc", paths='"cc/"', layer="scripts")
    )
    good = _write_yaml(tmp_path / "good.yaml", good_rows)
    loaded = mods.load_modules(good)
    assert [r["id"] for r in loaded] == ["aa", "bb", "cc"]

    with pytest.raises(FileNotFoundError):
        mods.load_modules(tmp_path / "absent.yaml")

    with pytest.raises(ValueError):
        mods.load_modules(_write_yaml(tmp_path / "v2.yaml", good_rows, version=2))

    # строка с индексом 2 (0-based) без layer
    no_layer = (
        _VALID_ROW.format(id="aa", paths='"aa/"', layer="scripts")
        + _VALID_ROW.format(id="bb", paths='"bb/"', layer="scripts")
        + '  - id: cc\n    paths: ["cc/"]\n    tier: null\n    docs: []\n    parent: null\n'
    )
    with pytest.raises(ValueError) as exc:
        mods.load_modules(_write_yaml(tmp_path / "no_layer.yaml", no_layer))
    message = str(exc.value)
    assert "layer" in message
    assert re.search(r"\b2\b", message), f"в тексте нет индекса строки 2: {message!r}"

    empty_path = _VALID_ROW.format(id="aa", paths='""', layer="scripts")
    with pytest.raises(ValueError):
        mods.load_modules(_write_yaml(tmp_path / "empty_path.yaml", empty_path))
