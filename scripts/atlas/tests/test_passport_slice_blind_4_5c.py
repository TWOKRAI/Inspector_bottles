"""Слепые приёмочные тесты Task 4.5c (RED до кода): порядок записей текста паспорта, срез `members`, ввод CLI.

Purpose: C1 порядок `used_by`/`call_sites`/`subclasses` в ТЕКСТЕ (продукт вне docs/plans/.claude, затем продукт внутри
    них, затем тесты; JSON не меняется); C2 срез `members` класса с хвостом `ещё N; --full`; C3 `--budget` < 1 у
    `ref` и `map`; C4 `ref --exclude` без `--format`; C5 блок `ambiguous` под бюджет; C6 нормализация путей на входе
    (`modules.norm_path`, `ref`, `map`, `--exclude`); C7 цепочка `interface.all` начинается с файла символа, если он
    сам объявляет `__all__` с именем символа. Тесты написаны по критериям приёмки без чтения дизайна и без кода
    реализации (слепой tester); красные до кода — спецификация исполнителя.
Public API: тесты test_*; публичных имён нет.
Stability: lite

Фикстуры — мини-репозитории git во `tmp_path` (`repo`, `atlas` из conftest; `atlas` гонит `main` в daemon-потоке с
дедлайном). Ожидаемые значения — литералы, не выводятся из кода под тестом. Обратная косая черта встречается только в
тестах путей. Зелёные до кода — только регрессионные (отмечены в докстринге теста).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from scripts.atlas.tests.conftest import GitRepo

__all__: list[str] = []

DEADLINE_S = 120.0


# ---------------------------------------------------------------- помощники


def _commit(repo: GitRepo, files: dict[str, str]) -> str:
    repo.git("config", "core.autocrlf", "false")
    for rel, text in files.items():
        repo.write(rel, text)
    return repo.commit("fixture")


def _yaml_roots(root: str, prefix: str, extra_rows: str = "") -> str:
    """modules.yaml ревизии: юниты — прямые подкаталоги `root` с `__init__.py` (id = prefix + имя) и `modules:`."""
    return (
        "version: 1\nroots:\n"
        f'  - path: "{root}"\n    layer: framework\n    id_prefix: "{prefix}"\n'
        "root_exclude: [tests, _shared]\n"
        f"modules:{' []' if not extra_rows else ''}\n{extra_rows}"
    )


def _row(ident: str, path: str) -> str:
    return (
        f'  - id: {ident}\n    paths: ["{path}"]\n    layer: framework\n    tier: null\n    docs: []\n'
        f'    parent: null\n    purpose: "Юнит {ident}."\n'
    )


_ROW = re.compile(r"^\s+(\S+) — (\S+):(\d+) \((import|name-call|same-file|test-body)\)$")


def _rows(text: str, name: str) -> list[str]:
    """Адреса `путь:строка` записей раздела `  <name>: N` текста паспорта в порядке печати."""
    lines = [line.rstrip() for line in text.splitlines()]
    start = next(i for i, line in enumerate(lines) if re.fullmatch(rf"  {name}: \d+", line))
    out: list[str] = []
    for line in lines[start + 1 :]:
        if not line.startswith("    "):
            break
        m = _ROW.match(line)
        if m:
            out.append(f"{m.group(2)}:{m.group(3)}")
    return out


def _stderr_atlas_line(err: str) -> bool:
    return any(line.startswith("atlas:") for line in err.splitlines())


# ---------------------------------------------------------------- C1. порядок записей в тексте

_C1 = {
    "core/__init__.py": "",
    "zzpkg/__init__.py": "",
    "core/lib.py": "class Base:\n    pass\n\n\ndef target():\n    return 1\n",
    # prod, ранг 0: вызов на уровне модуля
    "zzpkg/a_low.py": "from core.lib import Base, target\n\ntarget()\n\n\nclass Low(Base):\n    pass\n",
    # prod, ранг 2: `hot` зовут два prod-файла
    "zzpkg/zz_late.py": (
        "from core.lib import Base, target\n\n\ndef hot():\n    target()\n\n\nclass Late(Base):\n    pass\n"
    ),
    "zzpkg/use1.py": "from zzpkg.zz_late import hot\n\nhot()\n",
    "zzpkg/use2.py": "from zzpkg.zz_late import hot\n\nhot()\n",
    # prod внутри docs/, plans/, .claude/
    "docs/example.py": "from core.lib import Base, target\n\ntarget()\n\n\nclass Doc(Base):\n    pass\n",
    "plans/p.py": "from core.lib import Base, target\n\ntarget()\n\n\nclass Doc(Base):\n    pass\n",
    ".claude/h.py": "from core.lib import Base, target\n\ntarget()\n\n\nclass Doc(Base):\n    pass\n",
    "tests/test_x.py": (
        "from core.lib import Base, target\n\n\ndef test_x():\n    target()\n\n\nclass T(Base):\n    pass\n"
    ),
    "tests/test_a.py": "from core.lib import Base, target\n\ntarget()\n\n\nclass T2(Base):\n    pass\n",
}

# порядок по старому правилу (по пути) ставил .claude/docs/plans/tests раньше zzpkg; новый — продукт первым
_C1_USED_BY = [
    "zzpkg/a_low.py:1",
    "zzpkg/zz_late.py:1",
    ".claude/h.py:1",
    "docs/example.py:1",
    "plans/p.py:1",
    "tests/test_a.py:1",
    "tests/test_x.py:1",
]
_C1_CALL_SITES = [
    "zzpkg/zz_late.py:5",  # ранг 2 впереди ранга 0 внутри группы
    "zzpkg/a_low.py:3",
    ".claude/h.py:3",
    "docs/example.py:3",
    "plans/p.py:3",
    "tests/test_a.py:3",
    "tests/test_x.py:5",
]
_C1_SUBCLASSES = [
    "zzpkg/a_low.py:6",
    "zzpkg/zz_late.py:8",
    ".claude/h.py:6",
    "docs/example.py:6",
    "plans/p.py:6",
    "tests/test_a.py:6",
    "tests/test_x.py:8",
]


def _full_text(repo: GitRepo, atlas: Any, ident: str) -> str:
    res = atlas(repo, "ref", ident, "--format", "passport", "--full")
    assert res.code == 0, res.err
    return res.out


def test_text_used_by_prod_first_then_prod_in_docs_then_tests(repo: GitRepo, atlas: Any) -> None:
    """used_by в тексте: prod вне docs/plans/.claude, затем prod внутри них (по path), затем tests; старый порядок по
    path ставил `.claude/`, `docs/`, `plans/`, `tests/` раньше `zzpkg/`."""
    _commit(repo, _C1)
    assert _rows(_full_text(repo, atlas, "core/lib.py::target"), "used_by") == _C1_USED_BY


def test_text_call_sites_group_order_and_rank_inside_group(repo: GitRepo, atlas: Any) -> None:
    """call_sites в тексте: группы как у used_by; внутри группы `(-rank, path, line)` — `hot` (ранг 2,
    `zzpkg/zz_late.py`) раньше `<module>` ранга 0 из `zzpkg/a_low.py`."""
    _commit(repo, _C1)
    assert _rows(_full_text(repo, atlas, "core/lib.py::target"), "call_sites") == _C1_CALL_SITES


def test_text_subclasses_group_order(repo: GitRepo, atlas: Any) -> None:
    """subclasses в тексте: подклассы из `zzpkg/` первыми, затем из `.claude/`, `docs/`, `plans/`, затем из тестов."""
    _commit(repo, _C1)
    assert _rows(_full_text(repo, atlas, "core/lib.py::Base"), "subclasses") == _C1_SUBCLASSES


def test_text_cut_keeps_first_entries_of_new_order(repo: GitRepo, atlas: Any) -> None:
    """Срез берёт ПЕРВЫЕ записи нового порядка: при `--budget 1` список показывает одну запись — продукт вне
    docs/, не `.claude/h.py`, которую старый порядок ставил первой."""
    _commit(repo, _C1)
    res = atlas(repo, "ref", "core/lib.py::target", "--format", "passport", "--budget", "1")
    assert res.code == 0, res.err
    assert _rows(res.out, "used_by") == ["zzpkg/a_low.py:1"]
    assert _rows(res.out, "call_sites") == ["zzpkg/zz_late.py:5"]
    base = atlas(repo, "ref", "core/lib.py::Base", "--format", "passport", "--budget", "1")
    assert base.code == 0, base.err
    assert _rows(base.out, "subclasses") == ["zzpkg/a_low.py:6"]


def test_text_counts_prod_and_tests_unchanged(repo: GitRepo, atlas: Any) -> None:
    """Счётчик `из продукта N, из тестов M` не зависит от порядка: у `target` 5+5 записей продукта, 2+2 тестов."""
    _commit(repo, _C1)
    text = _full_text(repo, atlas, "core/lib.py::target")
    assert "links: найдено 14 (формы: import, name-call)" in text
    assert "  из продукта 10, из тестов 4" in text.splitlines()


def test_json_order_unchanged_by_where_line(repo: GitRepo, atlas: Any) -> None:
    """Регрессия (зелёный до кода): JSON-порядок записей — по `(where, line)`, как до задачи; тестовые и docs-записи
    стоят среди прочих по пути (`.claude` < `docs` < `plans` < `tests` < `zzpkg`)."""
    _commit(repo, _C1)
    res = atlas(repo, "ref", "core/lib.py::target", "--format", "json")
    assert res.code == 0, res.err
    [rec] = json.loads(res.out)
    assert [e["where"] for e in rec["links"]["used_by"]] == [
        ".claude/h.py:1",
        "docs/example.py:1",
        "plans/p.py:1",
        "tests/test_a.py:1",
        "tests/test_x.py:1",
        "zzpkg/a_low.py:1",
        "zzpkg/zz_late.py:1",
    ]
    assert [e["where"] for e in rec["links"]["call_sites"]] == [
        ".claude/h.py:3",
        "docs/example.py:3",
        "plans/p.py:3",
        "tests/test_a.py:3",
        "tests/test_x.py:5",
        "zzpkg/a_low.py:3",
        "zzpkg/zz_late.py:5",
    ]
    res_base = atlas(repo, "ref", "core/lib.py::Base", "--format", "json")
    [base] = json.loads(res_base.out)
    assert [e["where"] for e in base["links"]["subclasses"]] == [
        ".claude/h.py:6",
        "docs/example.py:6",
        "plans/p.py:6",
        "tests/test_a.py:6",
        "tests/test_x.py:8",
        "zzpkg/a_low.py:6",
        "zzpkg/zz_late.py:8",
    ]


# ---------------------------------------------------------------- C2. срез members

_METHODS_N = 30


def _big_class_source(n: int) -> str:
    body = "".join(f"    def meth_{i:02d}(self, x: int) -> int:\n        return x\n\n" for i in range(1, n + 1))
    return '"""Модуль."""\n\n\nclass Big:\n    """Большой класс."""\n\n' + body.rstrip("\n") + "\n"


_C2 = {
    "pkg/__init__.py": "",
    "pkg/big.py": _big_class_source(_METHODS_N),
    "pkg/small.py": (
        "class Small:\n    def one(self) -> int:\n        return 1\n\n    def two(self) -> int:\n"
        "        return 2\n\n    def three(self) -> int:\n        return 3\n\n"
        "    def four(self) -> int:\n        return 4\n"
    ),
}
_MEMBER_ROW = re.compile(r"^    meth_\d\d\(x: int\) -> int  :\d+$")
_HIDDEN_ROW = re.compile(r"^    ещё (\d+); --full$")


def _members_section(text: str) -> list[str]:
    """Строки раздела `  members:` (заголовок не входит) до следующего заголовка раздела верхнего уровня."""
    lines = [line.rstrip() for line in text.splitlines()]
    start = lines.index("  members:")
    end = next(i for i in range(start + 1, len(lines)) if lines[i].startswith("links:"))
    return lines[start + 1 : end]


def test_members_cut_with_default_budget(repo: GitRepo, atlas: Any) -> None:
    """Класс с 30 методами, бюджет по умолчанию 40: показано не меньше 3 членов, последняя строка раздела —
    `ещё N; --full`, показано + N == 30; весь текст <= 40 строк."""
    _commit(repo, _C2)
    res = atlas(repo, "ref", "pkg/big.py::Big", "--format", "passport")
    assert res.code == 0, res.err
    section = _members_section(res.out)
    shown = [line for line in section if _MEMBER_ROW.match(line)]
    assert len(shown) >= 3, section
    tail = _HIDDEN_ROW.match(section[-1])
    assert tail is not None, section[-1]
    assert int(tail.group(1)) >= 1
    assert len(shown) + int(tail.group(1)) == _METHODS_N
    assert [line for line in section if "ещё" in line] == [section[-1]]  # хвост один
    assert len(res.out.splitlines()) <= 40


def test_members_shown_are_first_in_source_order(repo: GitRepo, atlas: Any) -> None:
    """Показанные члены — первые по порядку исходника: `meth_01`, `meth_02`, ... без пропусков."""
    _commit(repo, _C2)
    res = atlas(repo, "ref", "pkg/big.py::Big", "--format", "passport")
    names = [line.split("(")[0].strip() for line in _members_section(res.out) if _MEMBER_ROW.match(line)]
    assert names == [f"meth_{i:02d}" for i in range(1, len(names) + 1)]
    assert len(names) >= 3


def test_members_full_shows_all_and_no_hidden_line(repo: GitRepo, atlas: Any) -> None:
    """Регрессия-контракт: с `--full` показаны все 30 членов, строки `ещё` нет."""
    _commit(repo, _C2)
    res = atlas(repo, "ref", "pkg/big.py::Big", "--format", "passport", "--full")
    assert res.code == 0, res.err
    section = _members_section(res.out)
    assert len([line for line in section if _MEMBER_ROW.match(line)]) == _METHODS_N
    assert not [line for line in section if "ещё" in line]


def test_members_cut_under_tight_budget_keeps_three(repo: GitRepo, atlas: Any) -> None:
    """Допущение: минимум 3 члена держится и при тесном бюджете (10): показано >= 3, хвост `ещё N; --full`, сумма 30."""
    _commit(repo, _C2)
    res = atlas(repo, "ref", "pkg/big.py::Big", "--format", "passport", "--budget", "10")
    assert res.code == 0, res.err
    section = _members_section(res.out)
    shown = [line for line in section if _MEMBER_ROW.match(line)]
    assert len(shown) >= 3
    tail = _HIDDEN_ROW.match(section[-1])
    assert tail is not None, section[-1]
    assert len(shown) + int(tail.group(1)) == _METHODS_N


def test_members_small_class_not_cut(repo: GitRepo, atlas: Any) -> None:
    """Регрессия (зелёный до кода): класс с 4 методами при бюджете по умолчанию — все 4, строки `ещё` нет."""
    _commit(repo, _C2)
    res = atlas(repo, "ref", "pkg/small.py::Small", "--format", "passport")
    assert res.code == 0, res.err
    section = _members_section(res.out)
    assert [line.strip().split("(")[0] for line in section] == ["one", "two", "three", "four"]


def test_ref_all_members_still_usage_error(repo: GitRepo, atlas: Any) -> None:
    """Регрессия (зелёный до кода): `ref ... --all members` — по-прежнему код 2 (членов нет среди имён среза `ref`)."""
    _commit(repo, _C2)
    res = atlas(repo, "ref", "pkg/big.py::Big", "--format", "passport", "--all", "members")
    assert res.code == 2 and res.out == ""
    assert "atlas ref: --all принимает used_by, call_sites, subclasses, structural, tests" in res.err.splitlines()


# ---------------------------------------------------------------- C3. --budget >= 1

_C3 = {
    "pkg/__init__.py": "",
    "pkg/a.py": "def f():\n    return 1\n",
}
_BUDGET_ERR = "atlas: --budget принимает целое >= 1"
_C4 = {**_C3, "modules.yaml": _yaml_roots("none/", "fx/", _row("pkg", "pkg/"))}


@pytest.mark.parametrize("value", ["0", "-1"])
def test_ref_budget_below_one_is_usage_error(repo: GitRepo, atlas: Any, value: str) -> None:
    """`ref ... --format passport --budget 0|-1` -> код 2, stdout пуст, в stderr строка `atlas: --budget принимает
    целое >= 1`."""
    _commit(repo, _C3)
    res = atlas(repo, "ref", "pkg/a.py::f", "--format", "passport", "--budget", value)
    assert res.code == 2, res.out
    assert res.out == ""
    assert _BUDGET_ERR in res.err.splitlines()
    assert "Traceback" not in res.err


@pytest.mark.parametrize("value", ["0", "-1"])
def test_map_budget_below_one_is_usage_error(repo: GitRepo, atlas: Any, value: str) -> None:
    """То же у `map pkg/a.py --budget 0|-1`."""
    _commit(repo, _C3)
    res = atlas(repo, "map", "pkg/a.py", "--budget", value)
    assert res.code == 2, res.out
    assert res.out == ""
    assert _BUDGET_ERR in res.err.splitlines()
    assert "Traceback" not in res.err


def test_budget_one_is_allowed(repo: GitRepo, atlas: Any) -> None:
    """Регрессия (зелёный до кода): `--budget 1` допустим у `ref` и у `map` (код 0, паспорт напечатан)."""
    _commit(repo, _C3)
    ref = atlas(repo, "ref", "pkg/a.py::f", "--format", "passport", "--budget", "1")
    assert ref.code == 0, ref.err
    assert ref.out.splitlines()[0] == "== pkg/a.py::f =="
    mp = atlas(repo, "map", "pkg/a.py", "--budget", "1")
    assert mp.code == 0, mp.err
    assert mp.out.splitlines()[0] == "== file pkg/a.py =="


@pytest.mark.parametrize("value", ["abc", "2.5"])
def test_budget_not_a_number_is_usage_error(repo: GitRepo, atlas: Any, value: str) -> None:
    """Регрессия (зелёный до кода): нечисло -> код 2 (разбор argparse), как сейчас; stdout пуст."""
    _commit(repo, _C3)
    ref = atlas(repo, "ref", "pkg/a.py::f", "--format", "passport", "--budget", value)
    assert ref.code == 2 and ref.out == ""
    mp = atlas(repo, "map", "pkg/a.py", "--budget", value)
    assert mp.code == 2 and mp.out == ""


# ---------------------------------------------------------------- C4. --exclude без --format


def test_ref_exclude_without_format_is_usage_error(repo: GitRepo, atlas: Any) -> None:
    """`ref <модуль> --exclude <путь>` без `--format` -> код 2, stdout пуст, stderr не пуст. Контроль: тот же `ref pkg`
    без `--exclude` проходит с кодом 0 (старый вывод по модулю), значит код 2 даёт именно `--exclude`."""
    _commit(repo, _C4)
    control = atlas(repo, "ref", "pkg")
    assert control.code == 0, control.err
    res = atlas(repo, "ref", "pkg", "--exclude", "other")
    assert res.code == 2, res.out
    assert res.out == ""
    assert res.err.strip() != ""
    assert "Traceback" not in res.err


def test_ref_exclude_with_format_passport_is_allowed(repo: GitRepo, atlas: Any) -> None:
    """С `--format passport` тот же `--exclude` допустим: код 0, паспорт напечатан."""
    _commit(repo, _C3)
    res = atlas(repo, "ref", "pkg/a.py::f", "--format", "passport", "--exclude", "other")
    assert res.code == 0, res.err
    assert res.out.splitlines()[0] == "== pkg/a.py::f =="


# ---------------------------------------------------------------- C5. ambiguous под бюджет

_C5 = {"pkg/__init__.py": "", **{f"pkg/m{i}.py": "def dup():\n    return 1\n" for i in range(1, 7)}}
_TAIL_HINT = "уточните путь::имя"


def _ambiguous(repo: GitRepo, atlas: Any, *extra: str) -> Any:
    return atlas(repo, "ref", "dup", "--format", "passport", *extra)


def test_ambiguous_budget_five_shows_two_candidates_and_tail(repo: GitRepo, atlas: Any) -> None:
    """6 кандидатов, `--budget 5`: заголовок, `ambiguous`, 2 кандидата (`max(budget - 3, 0)`), хвост — ровно 5 строк."""
    _commit(repo, _C5)
    res = _ambiguous(repo, atlas, "--budget", "5")
    assert res.code == 2
    assert res.out.splitlines() == [
        "== dup ==",
        "ambiguous",
        "pkg/m1.py::dup",
        "pkg/m2.py::dup",
        f"ещё 4; {_TAIL_HINT}",
    ]


def test_ambiguous_budget_four_shows_one_candidate(repo: GitRepo, atlas: Any) -> None:
    """`--budget 4`: один кандидат и хвост `ещё 5; ...` — 4 строки."""
    _commit(repo, _C5)
    res = _ambiguous(repo, atlas, "--budget", "4")
    assert res.code == 2
    assert res.out.splitlines() == ["== dup ==", "ambiguous", "pkg/m1.py::dup", f"ещё 5; {_TAIL_HINT}"]


@pytest.mark.parametrize("budget", ["1", "3"])
def test_ambiguous_block_is_at_least_three_lines(repo: GitRepo, atlas: Any, budget: str) -> None:
    """`--budget 1` и `--budget 3`: кандидатов не показано, блок — ровно 3 строки (заголовок, ошибка, `ещё 6; ...`)."""
    _commit(repo, _C5)
    res = _ambiguous(repo, atlas, "--budget", budget)
    assert res.code == 2
    assert res.out.splitlines() == ["== dup ==", "ambiguous", f"ещё 6; {_TAIL_HINT}"]


def test_ambiguous_default_budget_lists_all_without_tail(repo: GitRepo, atlas: Any) -> None:
    """Регрессия (зелёный до кода): при бюджете по умолчанию 6 кандидатов помещаются целиком, строки `ещё` нет."""
    _commit(repo, _C5)
    res = _ambiguous(repo, atlas)
    assert res.code == 2
    assert res.out.splitlines() == ["== dup ==", "ambiguous", *(f"pkg/m{i}.py::dup" for i in range(1, 7))]


def test_ambiguous_json_keeps_all_candidates(repo: GitRepo, atlas: Any) -> None:
    """Регрессия (зелёный до кода): JSON-запись `ambiguous` бюджетом не режется: все 6 кандидатов по пути."""
    _commit(repo, _C5)
    res = atlas(repo, "ref", "dup", "--format", "json", "--budget", "5")
    assert res.code == 2
    assert json.loads(res.out) == [
        {"id": "dup", "error": "ambiguous", "candidates": [f"pkg/m{i}.py::dup" for i in range(1, 7)]}
    ]


# ---------------------------------------------------------------- C6. нормализация путей на входе


def test_norm_path_table_without_root() -> None:
    """`norm_path` без корня: `\\` -> `/`, без ведущего `./`, `..` внутри пути сворачивается."""
    from scripts.atlas.modules import norm_path

    assert norm_path("pkg/a.py") == "pkg/a.py"
    assert norm_path("./pkg/a.py") == "pkg/a.py"
    assert norm_path("././pkg/a.py") == "pkg/a.py"
    assert norm_path("pkg\\a.py") == "pkg/a.py"
    assert norm_path(".\\pkg\\a.py") == "pkg/a.py"
    assert norm_path("a/b/../bc/x.py") == "a/bc/x.py"
    assert norm_path("a\\b\\..\\bc\\x.py") == "a/bc/x.py"
    assert norm_path("a/../b.py") == "b.py"
    assert norm_path("a/b/../../c.py") == "c.py"


@pytest.mark.parametrize(
    "bad",
    ["", "..", "../x.py", "a/../../x.py", "..\\x.py", "a\\..\\..\\x.py", "/abs/x.py"],
    ids=[
        "empty",
        "dotdot",
        "above-root",
        "above-root-deep",
        "above-root-backslash",
        "above-root-deep-backslash",
        "abs",
    ],
)
def test_norm_path_rejects_without_root(bad: str) -> None:
    """Пустая строка, `..` выше корня, абсолютный путь при `root is None` -> `AtlasError`."""
    from scripts.atlas.modules import norm_path
    from scripts.atlas.tree import AtlasError

    with pytest.raises(AtlasError):
        norm_path(bad)


def test_norm_path_absolute_inside_root_is_relative(tmp_path: Path) -> None:
    """Абсолютный путь внутри `root` -> путь от корня (в том числе с `..`, не выходящим за корень)."""
    from scripts.atlas.modules import norm_path

    root = tmp_path / "repo"
    assert norm_path(str(root / "pkg" / "a.py"), root) == "pkg/a.py"
    assert norm_path(str(root / "pkg" / ".." / "pkg" / "a.py"), root) == "pkg/a.py"
    assert norm_path("./pkg/a.py", root) == "pkg/a.py"
    assert norm_path("pkg\\a.py", root) == "pkg/a.py"


@pytest.mark.parametrize("kind", ["outside", "escape", "above"])
def test_norm_path_absolute_outside_root_rejected(tmp_path: Path, kind: str) -> None:
    """Абсолютный путь вне `root` (чужой каталог, выход через `..`) и `..` выше корня при заданном `root` ->
    `AtlasError`."""
    from scripts.atlas.modules import norm_path
    from scripts.atlas.tree import AtlasError

    root = tmp_path / "repo"
    bad = {
        "outside": str(tmp_path / "other" / "x.py"),
        "escape": str(root / ".." / "x.py"),
        "above": "../x.py",
    }[kind]
    with pytest.raises(AtlasError):
        norm_path(bad, root)


def test_resolve_does_not_raise_on_odd_paths() -> None:
    """Регрессия (зелёный до кода): `modules.resolve` не бросает на пустой строке, `..` выше корня и абсолютном пути —
    возвращает `other` (элемент `paths` не совпал); обычный путь юнита находится."""
    from scripts.atlas.modules import resolve

    rows = [{"id": "pkg", "paths": ["pkg/"]}]
    assert resolve("", rows) == "other"
    assert resolve("../x.py", rows) == "other"
    assert resolve("/abs/x.py", rows) == "other"
    assert resolve("pkg/a.py", rows) == "pkg"


_C6 = {
    "modules.yaml": _yaml_roots("a/", "fx/", _row("pkg", "pkg/")),
    "pkg/__init__.py": "",
    "pkg/a.py": '"""Модуль a."""\n\n\ndef f(x: int) -> int:\n    """Функция f."""\n    return x\n',
    "lib/__init__.py": "",
    "lib/x.py": "def g():\n    return 1\n",
    "pkg/call.py": "from lib.x import g\n\n\ndef run():\n    return g()\n",
    "a/__init__.py": "",
    "a/b/__init__.py": '"""Юнит b."""\n',
    "a/b/x.py": "def in_b():\n    return 1\n",
    "a/bc/__init__.py": '"""Юнит bc."""\n',
    "a/bc/x.py": "def in_bc():\n    return 2\n",
}


def test_c6_fixture_canonical_forms_work(repo: GitRepo, atlas: Any) -> None:
    """Контроль фикстуры (зелёный до кода): канонические `ref pkg/a.py::f`, `map pkg`, `map pkg/a.py` и
    `ref a/bc/x.py::in_bc` находятся; слой `a/bc/x.py` — `fx/bc`."""
    _commit(repo, _C6)
    assert atlas(repo, "ref", "pkg/a.py::f", "--format", "json").code == 0
    assert json.loads(atlas(repo, "map", "pkg", "--format", "json").out)[0]["kind"] == "unit"
    assert json.loads(atlas(repo, "map", "pkg/a.py", "--format", "json").out)[0]["kind"] == "file"
    [rec] = json.loads(atlas(repo, "ref", "a/bc/x.py::in_bc", "--format", "json").out)
    assert rec["interface"]["layer"] == "fx/bc"
    assert json.loads(atlas(repo, "map", "a/bc/x.py", "--format", "json").out)[0]["interface"]["layer"] == "fx/bc"


def _ref_pair(repo: GitRepo, atlas: Any, ident: str, fmt: str = "json") -> tuple[Any, Any]:
    canon = atlas(repo, "ref", "pkg/a.py::f", "--format", fmt)
    other = atlas(repo, "ref", ident, "--format", fmt)
    assert canon.code == 0, canon.err
    return canon, other


@pytest.mark.parametrize("fmt", ["json", "passport"])
def test_ref_id_with_leading_dot_slash(repo: GitRepo, atlas: Any, fmt: str) -> None:
    """`ref ./pkg/a.py::f` находит тот же символ, что `pkg/a.py::f`: одинаковый вывод."""
    _commit(repo, _C6)
    canon, other = _ref_pair(repo, atlas, "./pkg/a.py::f", fmt)
    assert other.code == 0, other.err
    assert other.out == canon.out


@pytest.mark.parametrize("fmt", ["json", "passport"])
def test_ref_id_with_backslash(repo: GitRepo, atlas: Any, fmt: str) -> None:
    """`ref pkg\\a.py::f` — тот же символ и тот же вывод."""
    _commit(repo, _C6)
    canon, other = _ref_pair(repo, atlas, "pkg\\a.py::f", fmt)
    assert other.code == 0, other.err
    assert other.out == canon.out


def test_ref_id_absolute_inside_root(repo: GitRepo, atlas: Any) -> None:
    """Абсолютный путь внутри корня репо читается как относительный от корня."""
    _commit(repo, _C6)
    canon, other = _ref_pair(repo, atlas, f"{repo.path.resolve()}/pkg/a.py::f")
    assert other.code == 0, other.err
    assert other.out == canon.out


def test_ref_id_dotdot_inside_goes_to_neighbour_unit(repo: GitRepo, atlas: Any) -> None:
    """`a/b/../bc/x.py::in_bc` — это `a/bc/x.py` и относится к юниту `fx/bc`, а не к `fx/b` (наивный prefix-match
    по `a/b/` отнёс бы его к `fx/b`)."""
    _commit(repo, _C6)
    res = atlas(repo, "ref", "a/b/../bc/x.py::in_bc", "--format", "json")
    assert res.code == 0, res.err
    [rec] = json.loads(res.out)
    assert rec["id"] == "a/bc/x.py::in_bc"
    assert rec["path"] == "a/bc/x.py"
    assert rec["interface"]["layer"] == "fx/bc"


def test_map_target_with_leading_dot_slash(repo: GitRepo, atlas: Any) -> None:
    """`map ./pkg` — как `map pkg` (юнит `pkg`): одинаковый вывод; то же для `./pkg/a.py` и `pkg\\a.py`."""
    _commit(repo, _C6)
    canon = atlas(repo, "map", "pkg", "--format", "json")
    assert canon.code == 0, canon.err
    assert json.loads(canon.out)[0]["kind"] == "unit"
    dotted = atlas(repo, "map", "./pkg", "--format", "json")
    assert dotted.code == 0, dotted.err
    assert dotted.out == canon.out


def test_map_file_target_with_dot_slash(repo: GitRepo, atlas: Any) -> None:
    """`map ./pkg/a.py` — как `map pkg/a.py` (файл)."""
    _commit(repo, _C6)
    canon = atlas(repo, "map", "pkg/a.py", "--format", "json")
    assert canon.code == 0, canon.err
    assert json.loads(canon.out)[0]["kind"] == "file"
    dotted = atlas(repo, "map", "./pkg/a.py", "--format", "json")
    assert dotted.code == 0, dotted.err
    assert dotted.out == canon.out


def test_map_file_target_with_backslash(repo: GitRepo, atlas: Any) -> None:
    """`map pkg\\a.py` — как `map pkg/a.py`; регрессия: обратная косая уже читается (зелёный до кода)."""
    _commit(repo, _C6)
    canon = atlas(repo, "map", "pkg/a.py", "--format", "json")
    other = atlas(repo, "map", "pkg\\a.py", "--format", "json")
    assert other.code == 0, other.err
    assert other.out == canon.out


def test_map_file_target_absolute_inside_root(repo: GitRepo, atlas: Any) -> None:
    """`map <root>/pkg/a.py` — как относительный от корня."""
    _commit(repo, _C6)
    canon = atlas(repo, "map", "pkg/a.py", "--format", "json")
    other = atlas(repo, "map", f"{repo.path.resolve()}/pkg/a.py", "--format", "json")
    assert other.code == 0, other.err
    assert other.out == canon.out


def test_map_target_dotdot_inside_goes_to_neighbour_unit(repo: GitRepo, atlas: Any) -> None:
    """`map a/b/../bc/x.py` — файл `a/bc/x.py` юнита `fx/bc` (слой `fx/bc`, не `fx/b`)."""
    _commit(repo, _C6)
    res = atlas(repo, "map", "a/b/../bc/x.py", "--format", "json")
    assert res.code == 0, res.err
    [rec] = json.loads(res.out)
    assert (rec["kind"], rec["id"]) == ("file", "a/bc/x.py")
    assert rec["interface"]["layer"] == "fx/bc"


def test_exclude_with_dot_slash_hides_links_like_plain_prefix(repo: GitRepo, atlas: Any) -> None:
    """`--exclude ./pkg` (у `ref --format passport|json`) работает как `--exclude pkg`: вызов `g()` из `pkg/call.py` не
    читается, `used_by` и `call_sites` пусты. Без исключения вызов виден (контроль фикстуры)."""
    _commit(repo, _C6)
    free = atlas(repo, "ref", "lib/x.py::g", "--format", "json")
    assert [e["where"] for e in json.loads(free.out)[0]["links"]["call_sites"]] == ["pkg/call.py:5"]
    plain = atlas(repo, "ref", "lib/x.py::g", "--format", "json", "--exclude", "pkg")
    assert json.loads(plain.out)[0]["links"]["call_sites"] == []
    dotted = atlas(repo, "ref", "lib/x.py::g", "--format", "json", "--exclude", "./pkg")
    assert dotted.code == 0, dotted.err
    assert dotted.out == plain.out


def test_exclude_with_dot_slash_hides_symbol_file(repo: GitRepo, atlas: Any) -> None:
    """Символ из файла под `--exclude ./pkg` не находится (код 2, `not found`), как под `--exclude pkg`."""
    _commit(repo, _C6)
    plain = atlas(repo, "ref", "pkg/a.py::f", "--format", "passport", "--exclude", "pkg")
    assert plain.code == 2
    dotted = atlas(repo, "ref", "pkg/a.py::f", "--format", "passport", "--exclude", "./pkg")
    assert dotted.code == 2, dotted.out
    assert dotted.out == plain.out


@pytest.mark.parametrize(
    "bad",
    ["", "../x.py::f", "../x.py", "OUTSIDE/x.py::f"],
    ids=["empty", "above-root-id", "above-root-path", "abs-outside"],
)
def test_ref_bad_input_path_is_usage_error(repo: GitRepo, atlas: Any, tmp_path: Path, bad: str) -> None:
    """Пустая строка, `..` выше корня, абсолютный путь вне корня в id `ref` -> код 2 и строка stderr `atlas: ...`,
    без traceback и `internal error`."""
    _commit(repo, _C6)
    ident = bad.replace("OUTSIDE", str(tmp_path / "outside"))
    res = atlas(repo, "ref", ident, "--format", "passport")
    assert res.code == 2, res.out
    assert _stderr_atlas_line(res.err), res.err
    assert "Traceback" not in res.err and "internal error" not in res.err


@pytest.mark.parametrize(
    "bad",
    ["", "../x.py", "a/../../x.py", "OUTSIDE/x.py"],
    ids=["empty", "above-root", "above-root-deep", "abs-outside"],
)
def test_map_bad_target_is_usage_error(repo: GitRepo, atlas: Any, tmp_path: Path, bad: str) -> None:
    """То же у цели `map`: код 2, строка stderr `atlas: ...`, без traceback и `internal error`."""
    _commit(repo, _C6)
    target = bad.replace("OUTSIDE", str(tmp_path / "outside"))
    res = atlas(repo, "map", target)
    assert res.code == 2, res.out
    assert _stderr_atlas_line(res.err), res.err
    assert "Traceback" not in res.err and "internal error" not in res.err


# ---------------------------------------------------------------- C7. interface.all: файл символа первым звеном

_C7 = {
    "modules.yaml": _yaml_roots("lib/", "fx/"),
    "lib/a/__init__.py": '"""Юнит А."""\nfrom lib.a.sub import Widget\n\n__all__ = ["Widget"]\n',
    "lib/a/sub/__init__.py": 'from lib.a.sub.impl import Widget\n\n__all__ = ["Widget"]\n',
    "lib/a/sub/impl.py": '__all__ = ["Widget"]\n\n\nclass Widget:\n    pass\n',
    "lib/c/__init__.py": '"""Юнит C."""\nfrom lib.c.sub import Gadget\n\n__all__ = ["Gadget"]\n',
    "lib/c/sub/__init__.py": 'from lib.c.sub.impl import Gadget\n\n__all__ = ["Gadget"]\n',
    # у файла свой `__all__`, но без имени символа: файл первым звеном не становится
    "lib/c/sub/impl.py": '__all__ = ["Other"]\n\n\nclass Gadget:\n    pass\n\n\nclass Other:\n    pass\n',
    # у файла `__all__` с именем, пакет `__all__` не объявляет: цепочка — один файл
    "lib/b/__init__.py": '"""Юнит Б."""\n',
    "lib/b/mod.py": '__all__ = ["Thing"]\n\n\nclass Thing:\n    pass\n',
}


def test_all_chain_starts_with_symbol_file_when_it_declares_the_name(repo: GitRepo, atlas: Any) -> None:
    """`lib/a/sub/impl.py` объявляет `__all__ = ["Widget"]`; пакеты `sub` и `a` реэкспортируют `Widget`: цепочка `all` —
    файл символа, затем `lib/a/sub/__init__.py`, затем `lib/a/__init__.py`."""
    _commit(repo, _C7)
    res = atlas(repo, "ref", "lib/a/sub/impl.py::Widget", "--format", "json")
    assert res.code == 0, res.err
    [rec] = json.loads(res.out)
    assert rec["interface"]["all"] == ["lib/a/sub/impl.py", "lib/a/sub/__init__.py", "lib/a/__init__.py"]


def test_all_chain_text_line_starts_with_symbol_file(repo: GitRepo, atlas: Any) -> None:
    """В тексте строка `all:` начинается с файла символа."""
    _commit(repo, _C7)
    res = atlas(repo, "ref", "lib/a/sub/impl.py::Widget", "--format", "passport")
    assert res.code == 0, res.err
    assert "  all: lib/a/sub/impl.py, lib/a/sub/__init__.py, lib/a/__init__.py" in res.out.splitlines()


def test_all_chain_file_alone_when_packages_do_not_declare_all(repo: GitRepo, atlas: Any) -> None:
    """Допущение: файл объявляет `__all__` с именем, пакеты `__all__` не объявляют -> цепочка из одного файла."""
    _commit(repo, _C7)
    res = atlas(repo, "ref", "lib/b/mod.py::Thing", "--format", "json")
    assert res.code == 0, res.err
    [rec] = json.loads(res.out)
    assert rec["interface"]["all"] == ["lib/b/mod.py"]


def test_all_chain_skips_symbol_file_when_its_all_lacks_the_name(repo: GitRepo, atlas: Any) -> None:
    """Регрессия (зелёный до кода): файл объявляет `__all__ = ["Other"]` без `Gadget`: первым звеном не становится,
    цепочка — пакеты, которые реэкспортируют `Gadget`."""
    _commit(repo, _C7)
    res = atlas(repo, "ref", "lib/c/sub/impl.py::Gadget", "--format", "json")
    assert res.code == 0, res.err
    [rec] = json.loads(res.out)
    assert rec["interface"]["all"] == ["lib/c/sub/__init__.py", "lib/c/__init__.py"]
