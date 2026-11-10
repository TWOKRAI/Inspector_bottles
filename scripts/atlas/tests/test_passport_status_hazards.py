"""Авторские hazard-тесты `status.stale` / `status.frozen` (Task 4.2b-1 GREEN): что слепые RED не покрывают.

Purpose: цепочка `__init__.py` через звено с `SyntaxError` (обход идёт дальше, `interface.all` как до 4.2b-1) и через
    звено с `v2_error` (его шапки в счёте); символ в самом `__init__.py` (шапка без дубля, докстринг класса — не
    шапка); юнит с `paths` без `/` (обход до корня репозитория); `stale` у основы без адреса (`where: null`) и без
    путей `frozen`; один `git diff` на паспорт, ни одного — у `resolve_ident`.
Public API: тесты test_*; публичных имён нет.
Stability: lite

Ожидания — литералы (номера строк — из текста фикстуры). Вызовы — в daemon-потоке с дедлайном (помощники
`test_passport_status`).
"""

from __future__ import annotations

import ast

import pytest

from scripts.atlas.tests.conftest import GitRepo, run_with_deadline
from scripts.atlas.tests.test_modules_roots_4_4 import _yaml
from scripts.atlas.tests.test_passport_status import _append, _build, _commit

__all__: list[str] = []

DEADLINE_S = 120.0


_ERR_LINK = {
    "a/__init__.py": '"""FREEZE 2026-01-01: пакет a\n"""\n\n__all__ = ["M"]\n',  # 1: шапка
    "a/b/__init__.py": '"""FREEZE 2026-02-02: не разобран"""\n\n\ndef broken(:\n    pass\n',  # SyntaxError
    "a/b/m.py": "class M:\n    pass\n",
}


def test_frozen_walks_past_unparsable_link(repo: GitRepo) -> None:
    """Звено `a/b/__init__.py` с `SyntaxError` пропускается, но обход не обрывается: шапка `a/__init__.py` в списке;
    `interface.all` по той же цепочке находит `__all__` пакета `a` (поведение 4.2a)."""
    _commit(repo, _ERR_LINK)
    p = _build(repo, "a/b/m.py::M")
    assert p["status"]["frozen"] == [{"date": "2026-01-01", "text": "пакет a", "where": "a/__init__.py:1"}]
    assert p["interface"]["all"] == ["a/__init__.py"]


_V2_LINK = {
    "a/__init__.py": '"""FREEZE 2026-01-01: пакет a\nV2BOOM\n"""\n',
    "a/m.py": "def f():\n    return 1\n",
}


def test_frozen_link_with_v2_error_still_counts(repo: GitRepo, monkeypatch: pytest.MonkeyPatch) -> None:
    """`v2_error` звена не влияет: шапка — поле A1, разбор v2 её не трогает."""
    from scripts.atlas import scan

    real = scan._collect_v2

    def boom(tree: ast.Module) -> dict:
        if "V2BOOM" in (ast.get_docstring(tree) or ""):
            raise ValueError("v2 сбой фикстуры")
        return real(tree)

    monkeypatch.setattr(scan, "_collect_v2", boom)
    facts = scan.scan_text(_V2_LINK["a/__init__.py"])
    assert facts.v2_error == "ValueError" and facts.error is None  # предусловие: звено с v2_error
    _commit(repo, _V2_LINK)
    assert _build(repo, "a/m.py::f")["status"]["frozen"] == [
        {"date": "2026-01-01", "text": "пакет a", "where": "a/__init__.py:1"}
    ]


_IN_INIT = {
    "top/__init__.py": '"""FREEZE 2026-05-05: верхний пакет"""\n',
    "top/pkg/__init__.py": (
        '"""Пакет.\n'  # 1
        "\n"  # 2
        "FREEZE 2026-06-06: публичный вход\n"  # 3
        '"""\n'  # 4
        "\n"  # 5
        "\n"  # 6
        "class Api:\n"  # 7
        '    """FREEZE 2026-09-09: докстринг класса - не шапка"""\n'  # 8
        "\n"  # 9
        "    def run(self):\n"  # 10
        "        return 1\n"  # 11
    ),
}


def test_frozen_symbol_in_init_has_no_duplicate(repo: GitRepo) -> None:
    """Символ в самом `__init__.py`: его шапка — один раз (файл символа, не звено), затем пакет выше; докстринг
    класса шапкой не считается. Метод — та же цепочка."""
    _commit(repo, _IN_INIT)
    expected = [
        {"date": "2026-06-06", "text": "публичный вход", "where": "top/pkg/__init__.py:3"},
        {"date": "2026-05-05", "text": "верхний пакет", "where": "top/__init__.py:1"},
    ]
    for ident in ("top/pkg/__init__.py::Api", "top/pkg/__init__.py::Api.run"):
        assert _build(repo, ident)["status"]["frozen"] == expected, ident


_FILE_UNIT_TAIL = (
    'modules:\n  - id: one\n    paths: ["lib/a/one.py"]\n    layer: scripts\n    tier: null\n    docs: []\n'
    '    parent: null\n    purpose: "Файл-юнит"\n'
)
_FILE_UNIT = {
    "modules.yaml": _yaml(("lib/", "framework", "fx/"), tail=_FILE_UNIT_TAIL),
    "__init__.py": '"""FREEZE 2026-12-01: корень"""\n',
    "lib/__init__.py": '"""FREEZE 2026-12-02: lib"""\n',
    "lib/a/__init__.py": '"""FREEZE 2026-12-03: юнит a"""\n',
    "lib/a/one.py": "def one():\n    return 1\n",
    "lib/a/two.py": "def two():\n    return 2\n",
}


def test_frozen_file_unit_walks_to_repo_root(repo: GitRepo) -> None:
    """Юнит с `paths` без `/` (файл целиком) — `stop=""`: обход идёт до корня, мимо границы каталожного юнита
    `lib/a/`; соседний файл того же каталога (юнит `lib/a/`) останавливается на `lib/a/__init__.py`."""
    _commit(repo, _FILE_UNIT)
    one = _build(repo, "lib/a/one.py::one")
    assert one["interface"]["layer"] == "one"  # предусловие: файл — свой юнит
    assert one["status"]["frozen"] == [
        {"date": "2026-12-03", "text": "юнит a", "where": "lib/a/__init__.py:1"},
        {"date": "2026-12-02", "text": "lib", "where": "lib/__init__.py:1"},
        {"date": "2026-12-01", "text": "корень", "where": "__init__.py:1"},
    ]
    assert _build(repo, "lib/a/two.py::two")["status"]["frozen"] == [
        {"date": "2026-12-03", "text": "юнит a", "where": "lib/a/__init__.py:1"}
    ]


_UNRESOLVED = {
    "pkg/__init__.py": '"""FREEZE 2026-04-04: пакет"""\n',
    "pkg/c.py": "from far import Unknown\n\n\nclass C(Unknown):\n    pass\n",
}


def test_stale_skips_null_where_and_frozen_paths(repo: GitRepo) -> None:
    """Основа без адреса (`where: null`) не роняет `stale`; путь шапки `frozen` (`pkg/__init__.py`) в `stale` не
    входит: правка пакета в рабочем дереве `stale` не меняет, правка файла символа — меняет."""
    _commit(repo, _UNRESOLVED)
    p = _build(repo, "pkg/c.py::C")
    assert p["links"]["bases"][0]["where"] is None  # предусловие
    assert p["status"]["frozen"][0]["where"] == "pkg/__init__.py:1"  # предусловие
    assert p["status"]["stale"] == []
    _append(repo, "pkg/__init__.py")
    assert _build(repo, "pkg/c.py::C")["status"]["stale"] == []
    _append(repo, "pkg/c.py")
    assert _build(repo, "pkg/c.py::C")["status"]["stale"] == ["pkg/c.py"]


_TWO = {
    "pkg/__init__.py": "",
    "pkg/lib.py": "def a():\n    return 1\n\n\ndef b():\n    return a()\n",
    "pkg/user.py": "from pkg.lib import a, b\n\n\ndef go():\n    a()\n    b()\n",  # второй путь паспорта
}


def test_one_git_diff_per_passport_none_in_resolve(repo: GitRepo, monkeypatch: pytest.MonkeyPatch) -> None:
    """Один `git diff` на паспорт (не на путь): `build_passport` — 1, `passports_for` на два id — 2,
    `resolve_ident` — 0."""
    from scripts.atlas import passport

    _commit(repo, _TWO)
    calls: list[tuple[str, ...]] = []
    real = passport.git_z

    def counting(root: object, *args: str) -> list[str]:
        if "diff" in args:
            calls.append(args)
        return real(root, *args)

    monkeypatch.setattr(passport, "git_z", counting)
    p = run_with_deadline(lambda: passport.build_passport(repo.path, "HEAD", "pkg/lib.py::b"), DEADLINE_S)
    assert [e["where"] for e in p["links"]["call_sites"]] == ["pkg/user.py:6"]  # предусловие: путей у паспорта 2
    assert len(calls) == 1
    run_with_deadline(lambda: passport.passports_for(repo.path, "HEAD", ["a", "b"]), DEADLINE_S)
    assert len(calls) == 3
    assert run_with_deadline(lambda: passport.resolve_ident(repo.path, "HEAD", "a"), DEADLINE_S) == ["pkg/lib.py::a"]
    assert len(calls) == 3
