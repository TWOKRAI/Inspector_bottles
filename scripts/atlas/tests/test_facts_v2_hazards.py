"""Whitebox-тесты ветки `v2_error` сканера (Task 4.1): сбой разбора v2 не трогает поля A1.

Purpose: поля v2 (`defs`, `calls`, `io`, `thread_sites`, `test_defs`) считаются в своём `try` после A1. Вслепую
    ветка недостижима: tester не знает, какой вход ломает только v2. Здесь — подмена внутреннего разбора
    (`_collect_v2`) и настоящий вход: цепочка вызовов, на которой `ast.unparse` получателя переполняет стек,
    а разбор A1 ещё нет. `RecursionError`/`MemoryError` в `v2_error` (как и в `error`) в кэш не идут.
Public API: тесты test_*; публичных имён нет.
Stability: lite

Ожидаемые значения — литералы. Глубина стека у pytest плавает, поэтому настоящий вход разбирается в свежем
daemon-потоке (`run_with_deadline`): глубина на входе в `scan_text` там одна и та же.
"""

from __future__ import annotations

import sqlite3

from scripts.atlas import scan as scan_mod
from scripts.atlas import store
from scripts.atlas.scan import ClassFact, DictSource, ImportRec, scan, scan_text
from scripts.atlas.tests.conftest import run_with_deadline

__all__: list[str] = []

_SRC = '''\
"""Шапка.

Tier: core
"""
import os
from pkg import thing

__all__ = ["Svc", "run"]


class Svc:
    commands = {"go": 1}

    def go(self):
        os.replace("a", "b")


def run():
    pass
'''

_A1 = {
    "loc": 12,
    "doc": "Шапка.",
    "all": ("Svc", "run"),
    "classes": (ClassFact("Svc", (), 11, ("go",), "class"),),
    "functions": ("run",),
    "imports": (
        ImportRec("hard", 5, 0, "os", (), False, False),
        ImportRec("hard", 6, 0, "pkg", ("thing",), True, False),
    ),
    "commands": ("go",),
    "tier": "core",
    "error": None,
}


def _a1(facts) -> dict:
    return {key: getattr(facts, key) for key in _A1}


def _boom(exc: type[BaseException]):
    def collect(tree):
        raise exc("v2 сломан")

    return collect


def _count(con: sqlite3.Connection) -> int:
    return con.execute("SELECT COUNT(*) FROM scan_cache").fetchone()[0]


def test_v2_failure_keeps_a1_fields(monkeypatch):
    clean = scan_text(_SRC)
    assert _a1(clean) == _A1  # вход тот же, что ниже; A1 — литералы
    assert clean.v2_error is None
    assert [d.qualname for d in clean.defs] == ["Svc", "Svc.go", "run"]

    monkeypatch.setattr(scan_mod, "_collect_v2", _boom(ValueError))
    broken = scan_text(_SRC)
    assert _a1(broken) == _A1
    assert broken.v2_error == "ValueError"
    assert (broken.defs, broken.calls, broken.io, broken.thread_sites, broken.test_defs) == ((), (), (), (), ())


def test_v2_recursion_error_not_cached_a1_kept(monkeypatch, tmp_path):
    monkeypatch.setattr(scan_mod, "_collect_v2", _boom(RecursionError))
    source = DictSource({"m.py": _SRC})
    con = store.connect(tmp_path / "atlas.sqlite")
    try:
        first = scan(source, ["m.py"], con)
        assert _a1(first.facts["m.py"]) == _A1
        assert first.facts["m.py"].v2_error == "RecursionError"
        assert (first.parsed, first.hits, _count(con)) == (1, 0, 0)  # зависит от стека, не от блоба: в кэш нельзя

        again = scan(source, ["m.py"], con)
        assert (again.parsed, again.hits) == (1, 0)
    finally:
        con.close()


def test_v2_deterministic_failure_is_cached(monkeypatch, tmp_path):
    """Обратная сторона: сбой v2, зависящий только от блоба, в кэш идёт (иначе условие кэша — «никогда»)."""
    monkeypatch.setattr(scan_mod, "_collect_v2", _boom(ValueError))
    source = DictSource({"m.py": _SRC})
    con = store.connect(tmp_path / "atlas.sqlite")
    try:
        scan(source, ["m.py"], con)
        again = scan(source, ["m.py"], con)
        assert (again.parsed, again.hits) == (0, 1)
        assert again.facts["m.py"].v2_error == "ValueError"
    finally:
        con.close()


def test_real_deep_chain_breaks_only_v2():
    """Цепочка `a.m().m()...` из 200 звеньев: A1 разбирается, `ast.unparse` получателя в v2 — `RecursionError`."""
    src = "import os\n\n\ndef f():\n    pass\n\n\nx = a" + ".m()" * 200 + "\n"
    facts = run_with_deadline(lambda: scan_text(src), 30.0)
    assert facts.error is None
    assert facts.functions == ("f",)
    assert facts.imports == (ImportRec("hard", 1, 0, "os", (), False, False),)
    assert facts.v2_error == "RecursionError"
    assert facts.defs == ()


def test_lone_surrogate_body_falls_back_to_ascii(tmp_path):
    """Тело кэша — UTF-8 без экранирования, но одиночный суррогат (escape `\\ud800` в докстринге) в UTF-8 не
    кодируется: тело уходит в ASCII-форму, запись в sqlite и чтение обратно дают те же факты."""
    src = 'def f():\n    """Ключ \\ud800 конец."""\n'
    source = DictSource({"s.py": src, "u.py": 'def g():\n    """Кириллица."""\n'})
    con = store.connect(tmp_path / "atlas.sqlite")
    try:
        first = scan(source, ["s.py", "u.py"], con)
        assert first.facts["s.py"].defs[0].doc == "Ключ \ud800 конец."
        bodies = {oid: body for oid, body in con.execute("SELECT oid, body FROM scan_cache")}
        oids = source.oids()
        assert bodies[oids["s.py"]].isascii()  # суррогат: прежняя ASCII-форма
        assert "Кириллица" in bodies[oids["u.py"]]  # без суррогата: UTF-8 как есть
        again = scan(source, ["s.py", "u.py"], con)
        assert (again.parsed, again.hits) == (0, 2)
        assert again.facts == first.facts
    finally:
        con.close()


def test_subclasses_same_file_included():
    """Наследники из файла базы (иерархии исключений и интерфейсов) видны: `how: "same-file"`, `scope` — по файлу."""
    from scripts.atlas.links import build_links

    src = (
        "import ext\n\n\nclass Base:\n    pass\n\n\nclass Kid(Base):\n    pass\n\n\nclass Grand(Kid):\n    pass\n"
        "\n\nclass Outside(ext.Base):\n    pass\n"  # `ext.Base` — чужой модуль, не `Base` этого файла
    )
    other = "from pkg.m import Base\n\n\nclass Far(Base):\n    pass\n"
    links = build_links(
        {"pkg/m.py": scan_text(src), "pkg/tests/test_far.py": scan_text(other), "pkg/far.py": scan_text(other)}
    )
    got = links.of("pkg/m.py::Base")["subclasses"]
    assert got == [
        {"where": "pkg/far.py:4", "how": "import", "scope": "prod", "enclosing": "Far"},
        {"where": "pkg/m.py:8", "how": "same-file", "scope": "prod", "enclosing": "Kid"},
        {"where": "pkg/tests/test_far.py:4", "how": "import", "scope": "test", "enclosing": "Far"},
    ]
    assert links.of("pkg/m.py::Kid")["subclasses"] == [
        {"where": "pkg/m.py:12", "how": "same-file", "scope": "prod", "enclosing": "Grand"}
    ]
    assert links.of("pkg/m.py::Grand")["subclasses"] == []
