"""RED Task 4.5c (developer): срез текста паспорта и ввод CLI.

Purpose: порядок записей `used_by`/`call_sites`/`subclasses` в тексте (продукт, продукт в docs/plans/.claude, тесты);
    срез `members` класса (`ещё N; --full`, минимум 3); `--budget` < 1 и `ref --exclude` без `--format` -> код 2;
    блок `ambiguous` в бюджет; `./` `\\` `..` в id, цели `map` и `--exclude`; первое звено `interface.all` — файл
    символа. Слепой набор tester — `test_passport_slice_blind_4_5c.py`; здесь свои REDS из ТЗ (по одному на пункт).
Public API: тесты test_*; публичных имён нет.
Stability: lite

Фикстуры — мини-репозитории git (`repo`, `atlas` из conftest). Ожидаемые значения — литералы. Обратная косая черта —
только в `test_dot_slash_and_backslash_paths_resolve`.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest

from scripts.atlas.tests.conftest import GitRepo

__all__: list[str] = []


def _commit(repo: GitRepo, files: dict[str, str]) -> None:
    repo.git("config", "core.autocrlf", "false")
    for rel, text in files.items():
        repo.write(rel, text)
    repo.commit("fixture")


def _yaml(root: str, prefix: str, rows: str = "") -> str:
    """modules.yaml ревизии: юниты — подкаталоги `root` с `__init__.py`; `rows` — записи `modules:`."""
    return (
        f'version: 1\nroots:\n  - path: "{root}"\n    layer: framework\n    id_prefix: "{prefix}"\n'
        f"root_exclude: []\nmodules:{' []' if not rows else ''}\n{rows}"
    )


_PKG_ROW = (
    '  - id: pkg\n    paths: ["pkg/"]\n    layer: framework\n    tier: null\n    docs: []\n'
    '    parent: null\n    purpose: "P."\n'
)
_ADDR = re.compile(r"^\s+\S+ — (\S+:\d+) \((?:import|name-call|same-file|test-body)\)$")


def _addresses(text: str, section: str) -> list[str]:
    """Адреса записей раздела `  <section>: N` в порядке печати (строки с отступом 4 до следующего заголовка)."""
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if re.fullmatch(rf"  {section}: \d+", line))
    out: list[str] = []
    for line in lines[start + 1 :]:
        if not line.startswith("    "):
            break
        if m := _ADDR.match(line):
            out.append(m.group(1))
    return out


# ---------------------------------------------------------------- порядок записей

_ORDER = {
    "core/__init__.py": "",
    "core/lib.py": "class Base:\n    pass\n\n\ndef target():\n    return 1\n",
    "zzpkg/__init__.py": "",
    "zzpkg/prod.py": "from core.lib import Base, target\n\ntarget()\n\n\nclass Low(Base):\n    pass\n",
    "docs/example.py": "from core.lib import Base, target\n\ntarget()\n\n\nclass Doc(Base):\n    pass\n",
    "tests/test_a.py": "from core.lib import Base, target\n\ntarget()\n\n\nclass T(Base):\n    pass\n",
}


def test_used_by_prod_before_docs_before_tests(repo: GitRepo, atlas: Any) -> None:
    """Текст: продукт вне docs/ -> продукт в docs/ -> тесты; по пути `docs` < `tests` < `zzpkg`, значит старый порядок
    ставил `zzpkg/prod.py` последним. То же у `call_sites` и `subclasses`; JSON остаётся по `(where, line)`."""
    _commit(repo, _ORDER)
    target = atlas(repo, "ref", "core/lib.py::target", "--format", "passport", "--full")
    assert target.code == 0, target.err
    assert _addresses(target.out, "used_by") == ["zzpkg/prod.py:1", "docs/example.py:1", "tests/test_a.py:1"]
    assert _addresses(target.out, "call_sites") == ["zzpkg/prod.py:3", "docs/example.py:3", "tests/test_a.py:3"]
    base = atlas(repo, "ref", "core/lib.py::Base", "--format", "passport", "--full")
    assert _addresses(base.out, "subclasses") == ["zzpkg/prod.py:6", "docs/example.py:6", "tests/test_a.py:6"]
    cut = atlas(repo, "ref", "core/lib.py::target", "--format", "passport", "--budget", "1")
    assert _addresses(cut.out, "used_by") == ["zzpkg/prod.py:1"]  # срез берёт первую запись нового порядка
    as_json = json.loads(atlas(repo, "ref", "core/lib.py::target", "--format", "json").out)[0]
    assert [e["where"] for e in as_json["links"]["used_by"]] == [
        "docs/example.py:1",
        "tests/test_a.py:1",
        "zzpkg/prod.py:1",
    ]


# ---------------------------------------------------------------- members

_BIG = (
    '"""Модуль."""\n\n\nclass Big:\n    """Большой."""\n\n'
    + "".join(f"    def meth_{i:02d}(self, x: int) -> int:\n        return x\n\n" for i in range(1, 31)).rstrip("\n")
    + "\n"
)
_MEMBER = re.compile(r"^    meth_\d\d\(x: int\) -> int  :\d+$")


def _members(text: str) -> list[str]:
    lines = text.splitlines()
    start = lines.index("  members:")
    end = next(i for i in range(start + 1, len(lines)) if lines[i].startswith("links:"))
    return lines[start + 1 : end]


def test_class_members_cut_with_more_hint(repo: GitRepo, atlas: Any) -> None:
    """Класс с 30 методами, бюджет 40: не меньше 3 членов (первые по исходнику), последняя строка раздела
    `    ещё N; --full`, показано + N == 30, весь текст <= 40 строк; `--full` — все 30 без хвоста; `--budget 10` — 3."""
    _commit(repo, {"pkg/__init__.py": "", "pkg/big.py": _BIG})
    res = atlas(repo, "ref", "pkg/big.py::Big", "--format", "passport")
    assert res.code == 0, res.err
    section = _members(res.out)
    shown = [line for line in section if _MEMBER.match(line)]
    tail = re.fullmatch(r"    ещё (\d+); --full", section[-1])
    assert tail is not None, section[-1]
    assert len(shown) >= 3 and len(shown) + int(tail.group(1)) == 30
    assert [line.split("(")[0].strip() for line in shown] == [f"meth_{i:02d}" for i in range(1, len(shown) + 1)]
    assert len(res.out.splitlines()) <= 40
    tight = _members(atlas(repo, "ref", "pkg/big.py::Big", "--format", "passport", "--budget", "10").out)
    assert len([line for line in tight if _MEMBER.match(line)]) == 3
    full = _members(atlas(repo, "ref", "pkg/big.py::Big", "--format", "passport", "--full").out)
    assert len(full) == 30 and all(_MEMBER.match(line) for line in full)


# ---------------------------------------------------------------- ввод CLI

_SMALL = {"pkg/__init__.py": "", "pkg/a.py": "def f():\n    return 1\n"}


@pytest.mark.parametrize("value", ["0", "-1"])
def test_budget_below_one_exit_2(repo: GitRepo, atlas: Any, value: str) -> None:
    """`ref --format passport` и `map` с `--budget 0|-1` -> код 2, stdout пуст, stderr `atlas: --budget принимает целое
    >= 1`; `--budget 1` допустим."""
    _commit(repo, _SMALL)
    for argv in (("ref", "pkg/a.py::f", "--format", "passport"), ("map", "pkg/a.py")):
        res = atlas(repo, *argv, "--budget", value)
        assert res.code == 2 and res.out == "", (argv, res.out)
        assert "atlas: --budget принимает целое >= 1" in res.err.splitlines(), res.err
        assert atlas(repo, *argv, "--budget", "1").code == 0


def test_exclude_without_format_exit_2(repo: GitRepo, atlas: Any) -> None:
    """`ref <модуль> --exclude <путь>` без `--format` -> код 2 и строка в stderr; с `--format` допустим."""
    _commit(
        repo,
        {
            **_SMALL,
            "modules.yaml": _yaml(
                "none/",
                "fx/",
                _PKG_ROW,
            ),
        },
    )
    assert atlas(repo, "ref", "pkg").code == 0
    res = atlas(repo, "ref", "pkg", "--exclude", "other")
    assert res.code == 2 and res.out == ""
    assert "atlas ref: --exclude требует --format" in res.err.splitlines()
    assert atlas(repo, "ref", "pkg/a.py::f", "--format", "passport", "--exclude", "other").code == 0


_DUP = {"pkg/__init__.py": "", **{f"pkg/m{i}.py": "def dup():\n    return 1\n" for i in range(1, 7)}}


def test_ambiguous_candidates_cut_to_budget(repo: GitRepo, atlas: Any) -> None:
    """6 кандидатов: `--budget 5` — заголовок, ошибка, 2 кандидата, `ещё 4; уточните путь::имя` (5 строк);
    `--budget 1` — 3 строки без кандидатов; `--budget 8` и бюджет по умолчанию — все 6, без хвоста; JSON не режется."""
    _commit(repo, _DUP)
    cands = [f"pkg/m{i}.py::dup" for i in range(1, 7)]
    five = atlas(repo, "ref", "dup", "--format", "passport", "--budget", "5")
    assert five.code == 2
    assert five.out.splitlines() == ["== dup ==", "ambiguous", *cands[:2], "ещё 4; уточните путь::имя"]
    one = atlas(repo, "ref", "dup", "--format", "passport", "--budget", "1")
    assert one.out.splitlines() == ["== dup ==", "ambiguous", "ещё 6; уточните путь::имя"]
    for extra in (("--budget", "8"), ()):
        fits = atlas(repo, "ref", "dup", "--format", "passport", *extra)
        assert fits.out.splitlines() == ["== dup ==", "ambiguous", *cands]
    assert len(json.loads(atlas(repo, "ref", "dup", "--format", "json", "--budget", "5").out)[0]["candidates"]) == 6


# ---------------------------------------------------------------- нормализация путей

_PATHS = {
    "modules.yaml": _yaml(
        "a/",
        "fx/",
        _PKG_ROW,
    ),
    "pkg/__init__.py": "",
    "pkg/a.py": "def f(x: int) -> int:\n    return x\n",
    "pkg/call.py": "from lib.x import g\n\n\ndef run():\n    return g()\n",
    "lib/__init__.py": "",
    "lib/x.py": "def g():\n    return 1\n",
    "a/__init__.py": "",
    "a/b/__init__.py": '"""Юнит b."""\n',
    "a/b/x.py": "def in_b():\n    return 1\n",
    "a/bc/__init__.py": '"""Юнит bc."""\n',
    "a/bc/x.py": "def in_bc():\n    return 2\n",
}


def test_dot_slash_and_backslash_paths_resolve(repo: GitRepo, atlas: Any) -> None:
    """`./pkg/a.py::f` и `pkg\\a.py::f` дают тот же вывод, что `pkg/a.py::f`; `map ./pkg` — юнит `pkg`;
    `--exclude ./pkg` скрывает вызов из `pkg/call.py`, как `--exclude pkg`."""
    _commit(repo, _PATHS)
    canon = atlas(repo, "ref", "pkg/a.py::f", "--format", "json")
    assert canon.code == 0, canon.err
    for spelling in ("./pkg/a.py::f", "pkg\\a.py::f"):
        other = atlas(repo, "ref", spelling, "--format", "json")
        assert other.code == 0, other.err
        assert other.out == canon.out
    unit = atlas(repo, "map", "pkg", "--format", "json")
    assert atlas(repo, "map", "./pkg", "--format", "json").out == unit.out
    plain = atlas(repo, "ref", "lib/x.py::g", "--format", "json", "--exclude", "pkg")
    assert json.loads(plain.out)[0]["links"]["call_sites"] == []
    assert atlas(repo, "ref", "lib/x.py::g", "--format", "json", "--exclude", "./pkg").out == plain.out
    assert len(json.loads(atlas(repo, "ref", "lib/x.py::g", "--format", "json").out)[0]["links"]["call_sites"]) == 1


def test_dotdot_path_not_assigned_to_foreign_unit(repo: GitRepo, atlas: Any) -> None:
    """`a/b/../bc/x.py` — файл `a/bc/x.py` юнита `fx/bc`, не `fx/b` (префикс `a/b/` совпал бы с сырой строкой)."""
    _commit(repo, _PATHS)
    [rec] = json.loads(atlas(repo, "ref", "a/b/../bc/x.py::in_bc", "--format", "json").out)
    assert (rec["id"], rec["interface"]["layer"]) == ("a/bc/x.py::in_bc", "fx/bc")
    [mapped] = json.loads(atlas(repo, "map", "a/b/../bc/x.py", "--format", "json").out)
    assert (mapped["id"], mapped["interface"]["layer"]) == ("a/bc/x.py", "fx/bc")


@pytest.mark.parametrize("bad", ["", "../x.py::f", "a/../../x.py"])
def test_bad_path_exit_2_with_atlas_line(repo: GitRepo, atlas: Any, bad: str) -> None:
    """Пустая строка и `..` выше корня в id `ref`, цели `map` и `--exclude` -> код 2, строка stderr начинается с
    `atlas:`, без traceback."""
    _commit(repo, _PATHS)
    runs = [
        ("ref", bad, "--format", "passport"),
        ("map", bad.partition("::")[0]),
        ("ref", "pkg/a.py::f", "--format", "passport", "--exclude", bad.partition("::")[0]),
    ]
    for argv in runs:
        res = atlas(repo, *argv)
        assert res.code == 2, (argv, res.out)
        assert any(line.startswith("atlas:") for line in res.err.splitlines()), (argv, res.err)
        assert "Traceback" not in res.err and "internal error" not in res.err


def test_map_directory_with_trailing_slash_is_still_not_found(repo: GitRepo, atlas: Any) -> None:
    """`map pkg/` — каталог, не цель (пин 4.2b-2): `normpath` слэш не снимает молча, `not found`, код 2."""
    _commit(repo, _PATHS)
    res = atlas(repo, "map", "pkg/")
    assert res.code == 2 and "atlas map: not found" in res.err.splitlines()


# ---------------------------------------------------------------- interface.all

_ALL = {
    "modules.yaml": _yaml("lib/", "fx/"),
    "lib/a/__init__.py": '"""Юнит А."""\nfrom lib.a.sub import Widget\n\n__all__ = ["Widget"]\n',
    "lib/a/sub/__init__.py": 'from lib.a.sub.impl import Widget\n\n__all__ = ["Widget"]\n',
    "lib/a/sub/impl.py": '__all__ = ["Widget"]\n\n\nclass Widget:\n    pass\n',
    "lib/b/__init__.py": '"""Юнит Б."""\n__all__ = ["Own"]\n\n\nclass Own:\n    pass\n',
}


def test_all_chain_starts_with_own_file(repo: GitRepo, atlas: Any) -> None:
    """В14: файл символа с `__all__ = [имя]` — первое звено цепочки, затем пакеты; символ в самом `__init__.py` не
    дублируется (файл уже звено цепочки)."""
    _commit(repo, _ALL)
    [rec] = json.loads(atlas(repo, "ref", "lib/a/sub/impl.py::Widget", "--format", "json").out)
    assert rec["interface"]["all"] == ["lib/a/sub/impl.py", "lib/a/sub/__init__.py", "lib/a/__init__.py"]
    [own] = json.loads(atlas(repo, "ref", "lib/b/__init__.py::Own", "--format", "json").out)
    assert own["interface"]["all"] == ["lib/b/__init__.py"]


# ---------------------------------------------------------------- ревью r1


def test_error_block_not_found_has_no_zero_tail(repo: GitRepo, atlas: Any) -> None:
    """`not found` (кандидатов нет) при `--budget 1`: две строки, без `ещё 0; ...`."""
    _commit(repo, _SMALL)
    res = atlas(repo, "ref", "zzzNoSuchName", "--format", "passport", "--budget", "1")
    assert res.code == 2
    assert res.out.splitlines() == ["== zzzNoSuchName ==", "not found"]


@pytest.mark.parametrize("prefix", [".", "./", "a/.."])
def test_exclude_equal_to_root_exit_2(repo: GitRepo, atlas: Any, prefix: str) -> None:
    """`--exclude` с путём, равным корню, скрыл бы весь репозиторий: код 2, строка без значения пути."""
    _commit(repo, _SMALL)
    for argv in (("ref", "pkg/a.py::f", "--format", "passport"), ("map", "pkg/a.py")):
        res = atlas(repo, *argv, "--exclude", prefix)
        assert res.code == 2 and res.out == "", (argv, res.out)
        assert "atlas: --exclude: путь совпадает с корнем репозитория" in res.err.splitlines(), res.err


@pytest.mark.skipif(sys.platform == "win32", reason="symlink_to на Windows требует прав; ветка алиаса — posix")
def test_absolute_path_through_symlink_alias_inside_root(repo: GitRepo, atlas: Any, tmp_path: Path) -> None:
    """Абсолютный путь через симлинк-алиас корня (macOS `/tmp` -> `/private/tmp`) читается как внутри корня."""
    from scripts.atlas.modules import norm_path

    _commit(repo, _SMALL)
    alias = tmp_path / "alias"
    alias.symlink_to(repo.path, target_is_directory=True)
    assert norm_path(str(alias / "pkg" / "a.py"), repo.path) == "pkg/a.py"
    canon = atlas(repo, "ref", "pkg/a.py::f", "--format", "json")
    other = atlas(repo, "ref", f"{alias}/pkg/a.py::f", "--format", "json")
    assert other.code == 0, other.err
    assert other.out == canon.out


def test_nested_docs_dir_is_product_group(repo: GitRepo, atlas: Any) -> None:
    """Группа 1 — только верхний уровень `docs/`: вложенный `pkg/docs/x.py` — продукт (группа 0, по пути перед
    `zzpkg/`), `docs/y.py` — группа 1, затем тесты."""
    _commit(
        repo,
        {
            "core/__init__.py": "",
            "core/lib.py": "def target():\n    return 1\n",
            "pkg/__init__.py": "",
            "pkg/docs/x.py": "from core.lib import target\n",
            "zzpkg/__init__.py": "",
            "zzpkg/prod.py": "from core.lib import target\n",
            "docs/y.py": "from core.lib import target\n",
            "tests/test_a.py": "from core.lib import target\n",
        },
    )
    res = atlas(repo, "ref", "core/lib.py::target", "--format", "passport", "--full")
    assert res.code == 0, res.err
    assert _addresses(res.out, "used_by") == ["pkg/docs/x.py:1", "zzpkg/prod.py:1", "docs/y.py:1", "tests/test_a.py:1"]
