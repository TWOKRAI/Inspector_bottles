"""Авторские hazard-тесты `build_map` (Task 4.2b-2, GREEN, teamlead): границы, которые слепые тесты не трогают.

Purpose: вложенная строка реестра (`modules:` внутри `paths` другого юнита); юниты с `paths[0]` не каталогом и без
    `__init__.py`; файл с `error`/`v2_error` (цель-файл и член юнита); цель под `exclude`; `\\` в цели; ветка
    `_stale` > 100 путей (git diff без pathspec + пересечение); счёт операторов импорта; `used_by` файла вне юнитов.
    Поведение — докстринг `passport.build_map` («Решения GREEN»). Последний тест — про `ref` и общий `_alloc`
    (ревью стадии 5, И1): список из одной записи у паспорта СИМВОЛА не режется до 0.
Public API: тесты test_*; публичных имён нет.
Stability: lite

Фикстуры — мини-репозитории git во `tmp_path` (`repo` из conftest), помощники — из `test_passport_map.py`. Вызовы идут в
daemon-потоке с дедлайном (`run_with_deadline` внутри `_build`). Ожидаемые значения — литералы.
"""

from __future__ import annotations

import pytest

from scripts.atlas.tests.conftest import GitRepo
from scripts.atlas.tests.test_passport_map import _build, _commit, _registry, _render, _row, _seed

__all__: list[str] = []


def test_map_nested_registry_row_splits_members_and_counts_inner_as_importer(repo: GitRepo) -> None:
    """Строка `inner` (`o/in/`) вложена в `outer` (`o/`): члены и тесты не пересекаются; импорт из `o/in/x.py` в
    `o/a.py` — `used_by` юнита `outer` с группой `inner` (другой юнит), а у `inner` своих импортёров нет."""
    _commit(
        repo,
        {
            "modules.yaml": _registry(_row("outer", "o/"), _row("inner", "o/in/")),
            "o/__init__.py": "",
            "o/a.py": '"""Модуль a."""\n\n\ndef fa():\n    return 1\n',
            "o/in/__init__.py": "",
            "o/in/x.py": '"""Модуль x."""\nfrom o.a import fa\n',
            "o/in/tests/test_x.py": "def test_x():\n    assert True\n",
        },
    )
    outer = _build(repo, "outer")
    assert [m["name"] for m in outer["interface"]["members"]] == ["o/a.py", "o/__init__.py"]
    assert outer["links"]["used_by"] == [{"name": "inner", "where": "o/in/x.py:2", "how": "import", "count": 1}]
    assert outer["checks"]["tests"] == []
    inner = _build(repo, "inner")
    assert [m["name"] for m in inner["interface"]["members"]] == ["o/in/__init__.py", "o/in/x.py"]
    assert inner["links"]["used_by"] == []
    assert inner["checks"]["tests"] == [{"name": "o/in/tests/test_x.py", "where": "o/in/tests/test_x.py:1", "count": 1}]


def test_map_unit_paths0_file_and_unit_without_init(repo: GitRepo) -> None:
    """Юнит `solo` (`paths: ["tools/solo.py"]`, не каталог) и юнит `ns` (`ns/` без `__init__.py`): `path` — как в
    реестре, `interface.all` — `null`, `status.frozen` — `[]` (шапка FREEZE файла юнита-файла не читается как
    `__init__`), члены — по `resolve`."""
    _commit(
        repo,
        {
            "modules.yaml": _registry(_row("solo", "tools/solo.py"), _row("ns", "ns/")),
            "tools/solo.py": (
                '"""Один файл.\n\nFREEZE 2026-01-01: стоп\n"""\n__all__ = ["go"]\n\n\ndef go():\n    pass\n'
            ),
            "tools/other.py": "def no():\n    pass\n",
            "ns/m.py": '"""Модуль m."""\n',
        },
    )
    solo = _build(repo, "solo")
    assert (solo["kind"], solo["path"]) == ("unit", "tools/solo.py")
    assert solo["interface"]["all"] is None and solo["status"]["frozen"] == []
    assert solo["interface"]["members"] == [
        {"name": "tools/solo.py", "signature": None, "where": "tools/solo.py:1", "top": ["go"], "doc": "Один файл."}
    ]
    ns = _build(repo, "ns")
    assert (ns["path"], ns["interface"]["all"], ns["status"]["frozen"]) == ("ns/", None, [])
    assert [m["name"] for m in ns["interface"]["members"]] == ["ns/m.py"]
    assert _render(ns, budget=60).splitlines()[4] == "  all: —"  # у юнита `null` — искали, `__all__` нет


def test_map_file_with_parse_error_target_and_member(repo: GitRepo) -> None:
    """`u/bad.py` с синтаксической ошибкой (`error`): цель-файл находится, ключи из разбора файла — `null`; как член
    юнита — `top: null`, `doc: null`, в тексте `(не искали)`; импортёр-файл с `error` операторов не даёт."""
    _seed(repo, {"u/bad.py": '"""Модуль bad."""\ndef broken(:\n', "v/bad_user.py": "from u.a import A\ndef (:\n"})
    bad = _build(repo, "u/bad.py")
    assert bad["kind"] == "file"
    assert bad["purpose"]["text"] is None and bad["status"]["doc_missing"] is None
    assert bad["interface"]["members"] is None and bad["status"]["dynamic"] is None
    assert bad["runtime"] == {"processes": None, "threads": None, "commands": None, "io": None}
    assert bad["status"]["frozen"] == [] and bad["status"]["stale"] == []
    unit = _build(repo, "u")
    row = next(m for m in unit["interface"]["members"] if m["name"] == "u/bad.py")
    assert (row["top"], row["doc"]) == (None, None)
    assert unit["links"]["used_by"][0] == {"name": "v", "where": "v/x.py:3", "how": "import", "count": 2}
    assert "    u/bad.py — —  (не искали)" in _render(unit, full=True).splitlines()
    text = _render(bad, full=True).splitlines()
    assert "purpose: не искали" in text and "  members: не искали" in text


def test_map_file_with_v2_error_keeps_a1_keys(repo: GitRepo, monkeypatch: pytest.MonkeyPatch) -> None:
    """`v2_error` (поля A1 целы): докстринг, `Tier:` и `doc_missing` — как обычно; `members`, `runtime.*`,
    `dynamic` — `null`; как член юнита — `top: null`, `doc` на месте. Сбой v2 вызывается подменой `_collect_v2` по
    маркеру докстринга (кэш фактов во `tmp_path` пустой)."""
    from scripts.atlas import scan

    real = scan._collect_v2

    def boom(tree):
        doc = scan.ast.get_docstring(tree) or ""
        if "V2BOOM" in doc:
            raise RecursionError("v2")
        return real(tree)

    monkeypatch.setattr(scan, "_collect_v2", boom)
    _seed(repo, {"u/deep.py": '"""Модуль deep.\n\nV2BOOM\nTier: optional\n"""\n\n\ndef f():\n    pass\n'})
    deep = _build(repo, "u/deep.py")
    assert deep["purpose"]["text"] == "Модуль deep." and deep["status"]["doc_missing"] is False
    assert deep["status"]["tier"] == "optional"
    assert deep["interface"]["members"] is None and deep["status"]["dynamic"] is None
    assert deep["runtime"]["threads"] is None and deep["runtime"]["commands"] is None and deep["runtime"]["io"] is None
    unit = _build(repo, "u")
    row = next(m for m in unit["interface"]["members"] if m["name"] == "u/deep.py")
    assert (row["top"], row["doc"]) == (None, "Модуль deep.")


def test_map_target_under_exclude_and_backslash(repo: GitRepo) -> None:
    """Цель-файл под `exclude` — `not found`; юнит, все файлы которого под `exclude`, находится с пустыми списками;
    `\\` в цели читается как `/` (и у файла, и у пути в другом регистре нет: `U\\b.py` — `not found`)."""
    from scripts.atlas.tree import AtlasError

    _seed(repo)
    with pytest.raises(AtlasError, match="^not found$"):
        _build(repo, "u/b.py", exclude=("u/",))
    gone = _build(repo, "u", exclude=("u/",))
    assert gone["kind"] == "unit"
    assert (gone["interface"]["members"], gone["checks"]["tests"], gone["links"]["used_by"]) == ([], [], [])
    back = _build(repo, "u\\b.py")
    assert (back["kind"], back["id"], back["path"]) == ("file", "u/b.py", "u/b.py")
    with pytest.raises(AtlasError, match="^not found$"):
        _build(repo, "U\\b.py")


def test_map_stale_over_hundred_paths_intersects_full_diff(repo: GitRepo) -> None:
    """Юнит из 101 файла (> 100 путей: `git diff` без pathspec): `stale` — ровно изменённые члены в порядке паспорта;
    изменённый отслеживаемый файл вне паспорта (`zz/outside.py`) в список не попадает."""
    files = {f"big/m{i:03d}.py": f'"""Модуль {i}."""\n' for i in range(101)}
    files["modules.yaml"] = _registry(_row("big", "big/"))
    files["zz/outside.py"] = "X = 1\n"
    _commit(repo, files)
    for rel in ("big/m100.py", "big/m000.py", "zz/outside.py"):
        repo.write(rel, (repo.path / rel).read_text(encoding="utf-8") + "# правка\n")
    p = _build(repo, "big")
    assert len(p["interface"]["members"]) == 101
    assert p["status"]["stale"] == ["big/m000.py", "big/m100.py"]


def test_map_import_statements_counted_by_record(repo: GitRepo) -> None:
    """Счёт операторов (решение (г)): `from u.a import A, B` — 1; `import u.a, u.b` — 2 (запись на имя);
    `from u import a, b` (подмодули) — 1 оператор, но +1 каждому файлу-цели в порядке членов."""
    _seed(
        repo,
        {
            "v/x.py": '"""Импортёр v."""\n\nfrom u.a import A, B\nimport u.a, u.b\n',
            "w/y.py": '"""Импортёр w."""\nfrom u import a, b\n',
        },
    )
    p = _build(repo, "u")
    assert p["links"]["used_by"] == [
        {"name": "v", "where": "v/x.py:3", "how": "import", "count": 3},
        {"name": "w", "where": "w/y.py:2", "how": "import", "count": 1},
    ]
    # a: 3 оператора (v:3, v:4, w:2), b: 2 (v:4, w:2), __init__: 0
    assert [m["name"] for m in p["interface"]["members"]] == ["u/a.py", "u/b.py", "u/__init__.py"]


def test_map_file_outside_units_counts_other_importers(repo: GitRepo) -> None:
    """Файл вне юнитов (`other`): импортёр тоже вне юнитов — в `used_by` группой `other` (у файла юнита импортёры
    своего юнита не считаются, у `other` исключается только сам файл)."""
    _seed(
        repo,
        {
            "scripts/__init__.py": "",
            "scripts/tool.py": "def run():\n    return 1\n",
            "scripts/user.py": "from scripts.tool import run\n",
        },
    )
    tool = _build(repo, "scripts/tool.py")
    assert tool["interface"]["layer"] == "other"
    assert tool["links"]["used_by"] == [{"name": "other", "where": "scripts/user.py:1", "how": "import", "count": 1}]


def test_ref_symbol_single_entry_list_not_cut_to_zero(repo: GitRepo) -> None:
    """`ref` (паспорт символа, не `map`), общий `_alloc`: у функции `u/a.py::f` `used_by` — 1 запись, `call_sites` — 5.
    При `budget=1` каждый список даёт минимум одну запись: `used_by` целиком без метки (до правки GREEN было
    `показано 0 из 1; все: --all used_by`), `call_sites` — 1 из 5 с меткой. Строк — минимум: полный текст минус 4
    записи `call_sites` плюс метка."""
    from scripts.atlas.passport import build_passport, render_text
    from scripts.atlas.tests.conftest import run_with_deadline

    _commit(
        repo,
        {
            "u/__init__.py": "",
            "u/a.py": '"""Модуль a."""\n\n\ndef f():\n    return 1\n',
            "v/__init__.py": "",
            "v/x.py": "from u.a import f\n\n\ndef g():\n    f()\n    f()\n    f()\n    f()\n    f()\n",
        },
    )
    p = run_with_deadline(lambda: build_passport(repo.path, "HEAD", "u/a.py::f"), 120.0)
    assert p["kind"] == "function"
    assert [e["where"] for e in p["links"]["used_by"]] == ["v/x.py:1"]
    assert len(p["links"]["call_sites"]) == 5
    cut = [line.strip() for line in render_text(p, budget=1).splitlines()]
    full = render_text(p, full=True).splitlines()
    assert "<module> — v/x.py:1 (import)" in cut
    assert not [s for s in cut if s.startswith("показано 0 из")]
    assert not [s for s in cut if "--all used_by" in s]
    assert "показано 1 из 5; все: --all call_sites" in cut
    assert len(cut) == len(full) - 4 + 1  # строк <= max(budget, минимум): ровно минимум


# ---------------------------------------------------------------- ревью стадии 5 р.2 (opus): И1, И2, М1


def test_map_file_used_by_counts_own_unit_but_not_init_chain(repo: GitRepo) -> None:
    """И1, вариант (а): `used_by` файла — импортёры своего юнита идут группой с id юнита (`u/c.py` -> `u`), а
    `__init__.py` цепочки пакетов файла (реэкспорт) — нет: у `u/a.py` скрыт `u/__init__.py`, у `u/sub/m.py` —
    `u/sub/__init__.py` и `u/__init__.py`."""
    _seed(
        repo,
        {
            "u/__init__.py": '"""Пакет u."""\nfrom u.a import A, B\nfrom u.sub.m import X\n\n__all__ = ["A", "B"]\n',
            "u/c.py": '"""Модуль c."""\nfrom u.a import A\nfrom u.sub.m import X\n',
            "u/sub/__init__.py": "from u.sub.m import X\n",
            "u/sub/m.py": "X = 1\n",
        },
    )
    assert _build(repo, "u/a.py")["links"]["used_by"] == [
        {"name": "v", "where": "v/x.py:3", "how": "import", "count": 2},
        {"name": "u", "where": "u/c.py:2", "how": "import", "count": 1},
    ]
    assert _build(repo, "u/sub/m.py")["links"]["used_by"] == [
        {"name": "u", "where": "u/c.py:3", "how": "import", "count": 1}
    ]


def test_map_unit_paths0_is_init_file(repo: GitRepo) -> None:
    """И2 (1): `paths[0]` — сам `m/__init__.py` (как `framework_meta`): он и есть `__init__.py` юнита — `all` и
    `frozen` из него."""
    _commit(
        repo,
        {
            "modules.yaml": _registry(_row("meta", "m/__init__.py")),
            "m/__init__.py": '"""Мета.\n\nFREEZE 2026-02-02: мета стоп\n"""\n__all__ = ["one", "two"]\n',
            "m/other.py": "Y = 2\n",
        },
    )
    p = _build(repo, "meta")
    assert p["path"] == "m/__init__.py"
    assert p["interface"]["all"] == ["one", "two"]
    assert p["status"]["frozen"] == [{"date": "2026-02-02", "text": "мета стоп", "where": "m/__init__.py:3"}]
    assert [m["name"] for m in p["interface"]["members"]] == ["m/__init__.py"]
    assert "  all: one, two" in _render(p, full=True).splitlines()


def test_map_unit_paths0_not_package_prints_not_searched(repo: GitRepo) -> None:
    """И2 (2): `paths[0]` — `.md` (как `prototype_root`): `__init__.py` искать негде — `all: null`, текст
    `all: не искали`; у каталога без `__all__` — `all: —` (искали, нет)."""
    _commit(
        repo,
        {
            "modules.yaml": _registry(_row("proto", "app/ARCH.md"), _row("pkg", "pkg/")),
            "app/ARCH.md": "# арх\n",
            "app/main.py": "Z = 3\n",
            "pkg/__init__.py": '"""Пакет без __all__."""\n',
        },
    )
    proto = _build(repo, "proto")
    assert (proto["path"], proto["interface"]["all"], proto["status"]["frozen"]) == ("app/ARCH.md", None, [])
    assert "  all: не искали" in _render(proto, full=True).splitlines()
    pkg = _build(repo, "pkg")
    assert pkg["interface"]["all"] is None
    assert "  all: —" in _render(pkg, full=True).splitlines()


def test_map_file_with_error_tier_not_searched(repo: GitRepo) -> None:
    """М1: файл с `error` и шапкой `Tier: core` — шапки не прочитаны: строка статуса — `не искали` у всех трёх."""
    _seed(repo, {"u/bad.py": '"""Модуль bad.\n\nTier: core\n"""\ndef broken(:\n'})
    text = _render(_build(repo, "u/bad.py"), full=True).splitlines()
    assert "status: tier не искали; doc_missing не искали; dynamic не искали" in text
