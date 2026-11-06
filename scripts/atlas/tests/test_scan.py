"""Красные map-A1: ядро сканера scripts/atlas/scan.py и кэш фактов по oid блоба (RED).

Purpose: слепые приёмочные тесты (14 штук) по `plans/2026-10-04_atlas/tasks/map-A1.md`:
    факты дерева git и фикстуры в памяти равны, классификация импортов, разрешение
    импортов, шапка, число процессов git, кэш по oid, ключ SCANNER, непарсящийся
    исходник, методы классов. Все ожидаемые значения — литералы из задачи.
Public API: нет (только test_*).
Stability: lite

Модуль `scripts.atlas.scan` и его имена импортируются ВНУТРИ тестов: отсутствие кода
даёт красный на каждом тесте, а не одну ошибку сбора.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

from scripts.atlas.tests.conftest import run_with_deadline

__all__: list[str] = []

DEADLINE_S = 120.0

SRC_KINDS = """\
import a
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    import b
else:
    import c
class K:
    import d
def f():
    import e
    if True:
        import g
async def h():
    import i
if True:
    import j
"""

SRC_COMMANDS_THREADS = """\
import threading
from threading import Thread


class M:
    commands = {"zeta": 1, "alpha": 2}

    def setup(self):
        self.register_command("beta", self.h)
        self.register_command(name_var)
        t = threading.Thread(target=self.h, name="worker-1")
        u = Thread(target=self.h, name=self.label)
        v = Thread(target=self.h)
"""

SRC_METHODS_PROTOCOL = """\
from typing import Protocol
class P(Protocol):
    def __call__(self, x): ...
class C:
    def __init__(self): ...
    def _hidden(self): ...
    def run(self): ...
    def run(self): ...
"""

SRC_STYLES = """\
from abc import ABC, ABCMeta
from typing import Protocol, TypeVar
T = TypeVar("T")
class A(ABC):
    pass
class B(A):
    pass
class N(metaclass=ABCMeta):
    pass
class G(Protocol[T]):
    pass
class H(G):
    pass
class Plain:
    pass
"""


def _rec(module, names=(), level=0, is_from=True, kind="hard", line=1, guarded=False):
    from scripts.atlas.scan import ImportRec

    return ImportRec(kind=kind, line=line, level=level, module=module, names=names, is_from=is_from, guarded=guarded)


def _imports(src: str):
    from scripts.atlas.scan import scan_text

    return scan_text(src).imports


def _classes(src: str):
    from scripts.atlas.scan import scan_text

    return {c.name: c for c in scan_text(src).classes}


class _RunCounter:
    """Обёртка над subprocess.run: пишет argv каждого вызова и зовёт настоящий run."""

    def __init__(self, real) -> None:
        self.real = real
        self.calls: list[list[str]] = []

    def __call__(self, *args, **kwargs):
        argv = args[0] if args else kwargs["args"]
        self.calls.append([str(a) for a in argv])
        return self.real(*args, **kwargs)

    def count(self, word: str) -> int:
        return sum(1 for argv in self.calls if word in argv)


def _rows(con) -> int:
    return con.execute("SELECT count(*) FROM scan_cache").fetchone()[0]


def test_tree_and_dict_source_give_equal_facts(repo):
    from scripts.atlas.scan import DictSource, FileFacts, ImportRec, scan
    from scripts.atlas.tree import Tree

    init = '"""Pkg doc."""\n__all__ = ["run"]\n'
    mod = "import os\nfrom . import n\n\n\ndef run():\n    pass\n"
    leaf = "X = 1\n"
    repo.write("pkg/__init__.py", init)
    repo.write("pkg/m.py", mod)
    repo.write("pkg/n.py", leaf)
    repo.commit("init")
    dict_source = DictSource({"pkg/__init__.py": init, "pkg/m.py": mod, "pkg/n.py": leaf})
    paths = ["pkg/n.py", "pkg/__init__.py", "pkg/m.py"]

    def scenario():
        tree = Tree(repo.path, "HEAD")
        from_tree = scan(tree, paths).facts
        from_dict = scan(dict_source, paths).facts
        assert from_tree == from_dict
        assert list(from_tree) == paths

        init_f = from_tree["pkg/__init__.py"]
        assert init_f.loc == 2
        assert init_f.doc == "Pkg doc."
        assert init_f.all == ("run",)
        assert init_f.imports == ()
        assert init_f.classes == ()
        assert init_f.error is None

        mod_f = from_tree["pkg/m.py"]
        assert mod_f.loc == 4
        assert mod_f.functions == ("run",)
        assert mod_f.doc is None
        assert mod_f.all is None
        assert mod_f.imports == (
            ImportRec(kind="hard", line=1, level=0, module="os", names=(), is_from=False, guarded=False),
            ImportRec(kind="hard", line=2, level=1, module=None, names=("n",), is_from=True, guarded=False),
        )
        assert from_tree["pkg/n.py"].loc == 1

        assert dict_source.oids() == tree.oids()
        assert set(dict_source.oids()) == set(paths)
        assert DictSource({"n.py": "X = 1\n"}).oids()["n.py"] == "96766802bd555f14ace322a7f376c4551f1bf5b7"
        assert DictSource({"e.py": ""}).oids()["e.py"] == "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"

        res = scan(tree, ["pkg/n.py", "ghost.py"])
        assert res.missing == ("ghost.py",)
        assert list(res.facts) == ["pkg/n.py"]

        for facts in from_tree.values():
            assert FileFacts.from_json(facts.to_json()) == facts

    run_with_deadline(scenario, DEADLINE_S)


def test_import_kinds_hard_lazy_tc():
    recs = _imports(SRC_KINDS)
    assert [(r.module, r.kind, r.line) for r in recs] == [
        ("a", "hard", 1),
        ("typing", "hard", 2),
        ("b", "tc", 4),
        ("c", "hard", 6),
        ("d", "hard", 8),
        ("e", "lazy", 10),
        ("g", "lazy", 12),
        ("i", "lazy", 14),
        ("j", "hard", 16),
    ]
    typing_rec = recs[1]
    assert typing_rec.names == ("TYPE_CHECKING",)
    assert typing_rec.is_from is True
    assert typing_rec.level == 0
    assert recs[0].names == ()
    assert recs[0].is_from is False

    # решение лида (R9): под TYPE_CHECKING внутри def -> tc
    only = _imports("from typing import TYPE_CHECKING\ndef f():\n    if TYPE_CHECKING:\n        import a\n")
    # правка лида 2026-11-06: строка 1 — тоже импорт (typing, hard); в тексте задачи было «одна запись»
    assert [(r.module, r.kind, r.line) for r in only] == [("typing", "hard", 1), ("a", "tc", 4)]
    # решение лида (R9): def в теле if TYPE_CHECKING -> tc
    only = _imports("from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    def g():\n        import b\n")
    assert [(r.module, r.kind, r.line) for r in only] == [("typing", "hard", 1), ("b", "tc", 4)]

    qualified = _imports("import typing\nif typing.TYPE_CHECKING:\n    import k\n")
    assert [(r.module, r.kind, r.line) for r in qualified] == [("typing", "hard", 1), ("k", "tc", 3)]

    negated = _imports("from typing import TYPE_CHECKING\nif not TYPE_CHECKING:\n    import m\n")
    m_rec = [r for r in negated if r.module == "m"]
    assert len(m_rec) == 1
    assert m_rec[0].kind == "hard"
    assert m_rec[0].line == 3

    multi = _imports("import q\nimport r.s as t, u\n")
    assert [(r.module, r.line, r.kind, r.names) for r in multi] == [
        ("q", 1, "hard", ()),
        ("r.s", 2, "hard", ()),
        ("u", 2, "hard", ()),
    ]


def test_guarded_relative_import_marked_guarded():
    (rec,) = _imports("try:\n    from . import x\nexcept ImportError:\n    x = None\n")
    assert rec.guarded is True
    assert rec.level == 1
    assert rec.module is None
    assert rec.names == ("x",)
    assert rec.kind == "hard"
    assert rec.line == 2

    (rec,) = _imports("try:\n    from . import x\nexcept ValueError:\n    x = None\n")
    assert rec.guarded is False

    (rec,) = _imports("try:\n    def f():\n        from . import x\nexcept ImportError:\n    pass\n")
    assert rec.kind == "lazy"
    assert rec.guarded is False

    for head in ("except (KeyError, ModuleNotFoundError):", "except:", "except Exception:", "except BaseException:"):
        (rec,) = _imports(f"try:\n    import q\n{head}\n    pass\n")
        assert rec.guarded is True, head

    recs = _imports("try:\n    pass\nexcept ImportError:\n    import y\nelse:\n    import z\nfinally:\n    import w\n")
    assert [(r.module, r.line) for r in recs] == [("y", 4), ("z", 6), ("w", 8)]
    assert all(r.guarded is False for r in recs)
    assert all(r.kind == "hard" for r in recs)


def test_from_pkg_import_submodule_targets_submodule():
    from scripts.atlas.scan import ImportIndex, Resolved

    idx = ImportIndex(["pkg/__init__.py", "pkg/sub.py", "pkg/mod.py", "pkg/inner/__init__.py", "other.py"])
    assert idx.roots == frozenset({"pkg", "other"})

    res = idx.resolve("other.py", _rec("pkg", ("sub", "helper")))
    assert res == Resolved(status="internal", targets=(("pkg/sub.py", ("sub",)), ("pkg/__init__.py", ("helper",))))
    res = idx.resolve("other.py", _rec("pkg", ("helper", "sub")))
    assert res.targets == (("pkg/__init__.py", ("helper",)), ("pkg/sub.py", ("sub",)))
    res = idx.resolve("other.py", _rec("pkg", ("helper", "missing")))
    assert res.targets == (("pkg/__init__.py", ("helper", "missing")),)
    res = idx.resolve("other.py", _rec("pkg", ("inner",)))
    assert res.targets == (("pkg/inner/__init__.py", ("inner",)),)
    res = idx.resolve("other.py", _rec("pkg", ("*",)))
    assert res.targets == (("pkg/__init__.py", ("*",)),)

    res = idx.resolve("other.py", _rec("pkg.sub", (), is_from=False))
    assert res.status == "internal"
    assert res.targets == (("pkg/sub.py", ()),)
    res = idx.resolve("other.py", _rec("other", (), is_from=False))
    assert res.targets == (("other.py", ()),)

    res = idx.resolve("other.py", _rec("os", (), is_from=False))
    assert res.status == "external"
    assert res.targets == ()
    assert idx.resolve("other.py", _rec("os", ("path",))).status == "external"

    res = idx.resolve("other.py", _rec("pkg.nope", (), is_from=False))
    assert res.status == "unresolved"
    assert res.targets == ()
    assert idx.resolve("other.py", _rec("pkg.nope", ("x",))).status == "unresolved"

    # D2: каталог без __init__.py модулем не считается
    idx2 = ImportIndex(["ns/a.py", "other.py"])
    assert idx2.resolve("other.py", _rec("ns", ("a",))) == Resolved("unresolved", ())
    assert idx2.resolve("other.py", _rec("ns.a", (), is_from=False)) == Resolved("internal", (("ns/a.py", ()),))
    assert idx2.roots == frozenset({"ns", "other"})


def test_init_level_one_is_package():
    from scripts.atlas.scan import ImportIndex, Resolved, resolve_relative

    assert resolve_relative(1, None, "pkg", True) == "pkg"
    assert resolve_relative(1, "m", "pkg", True) == "pkg.m"
    assert resolve_relative(1, "m", "pkg.mod", False) == "pkg.m"
    assert resolve_relative(1, None, "pkg.mod", False) == "pkg"
    assert resolve_relative(2, None, "pkg", True) is None
    assert resolve_relative(2, "x", "a.b.c", False) == "a.x"
    assert resolve_relative(3, None, "a.b.c", False) is None

    idx = ImportIndex(["pkg/__init__.py", "pkg/m.py"])
    res = idx.resolve("pkg/__init__.py", _rec(None, ("m",), level=1))
    assert res == Resolved("internal", (("pkg/m.py", ("m",)),))
    res = idx.resolve("pkg/__init__.py", _rec("m", ("x",), level=1))
    assert res.targets == (("pkg/m.py", ("x",)),)
    # самоссылка как есть
    res = idx.resolve("pkg/__init__.py", _rec(None, ("zzz",), level=1))
    assert res.targets == (("pkg/__init__.py", ("zzz",)),)
    # у обычного файла точка — его каталог; цель — сам файл, отсев не делается
    res = idx.resolve("pkg/m.py", _rec(None, ("m",), level=1))
    assert res.targets == (("pkg/m.py", ("m",)),)
    res = idx.resolve("pkg/__init__.py", _rec(None, ("x",), level=2))
    assert res.status == "unresolved"
    assert res.targets == ()
    # путь вне индекса: не KeyError
    assert idx.resolve("zz/q.py", _rec("m", ("x",), level=1)) == Resolved("unresolved", ())


def test_commands_and_threads_literals():
    from scripts.atlas.scan import scan_text

    facts = scan_text(SRC_COMMANDS_THREADS)
    assert facts.commands == ("alpha", "beta", "zeta")
    assert facts.threads == (("worker-1", 11), ("self.label", 12))


def test_all_plus_equals():
    from scripts.atlas.scan import scan_text

    cases = [
        ('__all__ = ["a"]\n__all__ += ["b"]\n', ("a", "b")),
        ('__all__ = ["a"]\n__all__ += other\n', None),
        ('__all__ = ["a"]\n__all__.extend(["b"])\n', None),
        ('__all__ = ("a", "b")\n', ("a", "b")),
        ('__all__ = ["a", name]\n', None),
        ('__all__: list[str] = ["a"]\n', ("a",)),
        ("x = 1\n", None),
    ]
    for src, expected in cases:
        assert scan_text(src).all == expected, src


def test_header_tier_contour_parsed():
    from scripts.atlas.scan import scan_text

    facts = scan_text('"""Цель.\n\nTier: Core\nContour: ipc, lifecycle\n"""\n')
    assert (facts.tier, facts.contour) == ("core", ("ipc", "lifecycle"))
    assert facts.doc == "Цель."

    cases = [
        ("Цель.\n\nTier: huge", (None, None)),
        ("Tier: huge\nTier: optional", ("optional", None)),
        ("Contour: a\nContour: b", (None, ("a",))),
        ("Contour: , ,", (None, None)),
        ("Contour: a, ,b ", (None, ("a", "b"))),
    ]
    for docstring, expected in cases:
        facts = scan_text('"""' + docstring + '\n"""\n')
        assert (facts.tier, facts.contour) == expected, docstring


def test_one_git_process_per_scan(repo, monkeypatch):
    import scripts.atlas.tree as tree_module
    from scripts.atlas.scan import DictSource, scan
    from scripts.atlas.store import connect
    from scripts.atlas.tree import AtlasError, Tree, read_blobs

    repo.write("a.py", "A = 1\n")
    repo.write("b.py", "B = 2\n")
    repo.write("c.py", "C = 3\n")
    repo.commit("init")
    counter = _RunCounter(tree_module.subprocess.run)
    monkeypatch.setattr(tree_module.subprocess, "run", counter)  # ПОСЛЕ подготовки фикстуры
    paths = ["a.py", "b.py", "c.py"]

    def scenario():
        con = connect(repo.path.parent / "atlas.sqlite")

        # холодно: ls-tree -r -z, затем cat-file --batch
        counter.calls.clear()
        res = scan(Tree(repo.path, "HEAD"), paths, con)
        assert len(counter.calls) == 2, counter.calls
        assert {"ls-tree", "-r", "-z"} <= set(counter.calls[0])
        assert {"cat-file", "--batch"} <= set(counter.calls[1])
        assert res.parsed == 3

        # повтор без изменений: только ls-tree
        counter.calls.clear()
        res = scan(Tree(repo.path, "HEAD"), paths, con)
        assert len(counter.calls) == 1, counter.calls
        assert "ls-tree" in counter.calls[0]
        assert counter.count("cat-file") == 0
        assert (res.parsed, res.hits) == (0, 3)

        # правка одного файла
        repo.write("a.py", "A = 10\n")
        repo.commit("edit a")
        counter.calls.clear()
        res = scan(Tree(repo.path, "HEAD"), paths, con)
        assert len(counter.calls) == 2, counter.calls
        assert (res.parsed, res.hits) == (1, 2)

        # gitlink и символьная ссылка: files() видит, oids() и scan — нет
        repo.git("update-index", "--add", "--cacheinfo", f"160000,{repo.head},sub")
        repo.git("update-index", "--add", "--cacheinfo", f"120000,{repo.git('rev-parse', 'HEAD:a.py')},link")
        repo.git("commit", "-q", "-m", "special")
        tree = Tree(repo.path, "HEAD")
        counter.calls.clear()
        assert tree.files() == ["a.py", "b.py", "c.py", "link", "sub"]
        assert set(tree.oids()) == {"a.py", "b.py", "c.py"}
        assert counter.count("ls-tree") == 1, counter.calls
        res = scan(tree, ["a.py", "link", "sub"])
        assert res.missing == ("link", "sub")
        assert list(res.facts) == ["a.py"]

        # пустой ввод — без git; перевод строки в пути — AtlasError
        fresh = Tree(repo.path, "HEAD")
        counter.calls.clear()
        assert read_blobs(repo.path, "HEAD", []) == {}
        assert fresh.read_many([]) == {}
        assert counter.calls == []
        with pytest.raises(AtlasError):
            read_blobs(repo.path, "HEAD", ["x\ny.py"])
        with pytest.raises(AtlasError):
            fresh.read_many(["a.py", "x\ny.py"])
        assert fresh.read_many(["a.py", "nope.py"]) == {"a.py": b"A = 10\n", "nope.py": None}

        # scan не прерывается на пути с переводом строки
        res = scan(DictSource({"a.py": "A = 1\n", "x\ny.py": "B = 2\n"}), ["a.py", "x\ny.py"])
        assert res.missing == ("x\ny.py",)
        assert list(res.facts) == ["a.py"]

    run_with_deadline(scenario, DEADLINE_S)


def test_blob_cache_reparses_only_changed_oids(repo, tmp_path):
    from scripts.atlas.scan import scan
    from scripts.atlas.store import connect, get_scans, put_scans
    from scripts.atlas.tree import Tree

    repo.write("x.py", "X = 1\n")
    repo.write("y.py", "Y = 2\n")
    repo.write("z.py", "Z = 3\n")
    repo.commit("init")

    def scenario():
        con = connect(tmp_path / "atlas.sqlite")
        assert con.execute("PRAGMA user_version").fetchone()[0] == 5
        assert [r[1] for r in con.execute("PRAGMA table_info(scan_cache)")] == ["oid", "scanner", "body"]

        res = scan(Tree(repo.path, "HEAD"), ["x.py", "y.py", "z.py"], con)
        assert (res.parsed, res.hits, _rows(con)) == (3, 0, 3)

        repo.write("x.py", "X = 10\n")
        repo.commit("edit x")
        res = scan(Tree(repo.path, "HEAD"), ["x.py", "y.py", "z.py"], con)
        assert (res.parsed, res.hits, _rows(con)) == (1, 2, 4)

        repo.git("mv", "y.py", "w.py")
        repo.commit("rename y")
        res = scan(Tree(repo.path, "HEAD"), ["x.py", "w.py", "z.py"], con)
        assert (res.parsed, res.hits, _rows(con)) == (0, 3, 4)

        # хранилище напрямую: тела возвращаются как есть
        put_scans(con, "s1", [("o1", "[1]"), ("o2", "{}")])
        assert get_scans(con, "s1", ["o1", "o2", "o3"]) == {"o1": "[1]", "o2": "{}"}
        assert get_scans(con, "s2", ["o1"]) == {}
        put_scans(con, "s1", [("o1", "new")])
        assert get_scans(con, "s1", ["o1"]) == {"o1": "new"}

    run_with_deadline(scenario, DEADLINE_S)


def test_facts_depend_only_on_content(tmp_path):
    from scripts.atlas.scan import DictSource, scan
    from scripts.atlas.store import connect

    text = '"""Doc."""\n__all__ = ["a"]\nimport os\n'

    def scenario():
        con = connect(tmp_path / "atlas.sqlite")
        res = scan(DictSource({"pkg/__init__.py": text, "pkg/m.py": text}), ["pkg/__init__.py", "pkg/m.py"], con)
        assert res.facts["pkg/__init__.py"] == res.facts["pkg/m.py"]
        for path in ("pkg/__init__.py", "pkg/m.py"):
            assert res.facts[path].doc == "Doc."
            assert res.facts[path].all == ("a",)
        assert (res.parsed, res.hits) == (1, 0)
        assert _rows(con) == 1

    run_with_deadline(scenario, DEADLINE_S)


def test_scanner_change_is_full_miss(tmp_path, monkeypatch):
    import scripts.atlas.scan as scan_mod
    from scripts.atlas.scan import DictSource, scan
    from scripts.atlas.store import connect

    assert re.fullmatch(r"1-[0-9a-f]{12}", scan_mod.SCANNER)
    assert scan_mod.SCANNER == "1-" + hashlib.sha256(Path(scan_mod.__file__).read_bytes()).hexdigest()[:12]
    source = DictSource({"a.py": "A = 1\n", "b.py": "B = 2\n", "c.py": "C = 3\n"})
    paths = ["a.py", "b.py", "c.py"]

    def scenario():
        con = connect(tmp_path / "atlas.sqlite")
        res = scan(source, paths, con)
        assert (res.parsed, res.hits, _rows(con)) == (3, 0, 3)
        res = scan(source, paths, con)
        assert (res.parsed, res.hits) == (0, 3)

        monkeypatch.setattr(scan_mod, "SCANNER", "x")
        res = scan(source, paths, con)
        assert (res.parsed, res.hits, _rows(con)) == (3, 0, 6)

    run_with_deadline(scenario, DEADLINE_S)


def test_unparsable_source_gives_error_facts(tmp_path):
    import scripts.atlas.scan as scan_mod
    from scripts.atlas.scan import DictSource, FileFacts, scan, scan_text
    from scripts.atlas.store import connect

    assert scan_text("def (") == FileFacts(loc=1, error="SyntaxError")
    assert scan(DictSource({"bad.py": b"\xff\xfe"}), ["bad.py"]).facts["bad.py"] == FileFacts(
        loc=0, error="UnicodeDecodeError"
    )

    # BOM снимается и в тексте, и в байтах
    facts = scan_text("﻿import os")
    assert facts.error is None
    assert len(facts.imports) == 1
    assert facts.imports[0].module == "os"
    bom = scan(DictSource({"b.py": b"\xef\xbb\xbfimport os"}), ["b.py"]).facts["b.py"]
    assert bom.error is None
    assert len(bom.imports) == 1
    assert bom.imports[0].module == "os"

    # scan_text не бросает никогда
    chain_600 = "x = " + " + ".join(["1"] * 600) + "\n"
    chain_3000 = "x = " + " + ".join(["1"] * 3000) + "\n"
    facts = scan_text(chain_600)  # на error утверждений нет: зависит от лимита рекурсии
    assert facts.loc == 1
    facts = scan_text(chain_3000)
    assert facts.error == "RecursionError"
    assert facts.loc == 1

    # соседний файл цел
    res = scan(DictSource({"bad.py": b"\xff\xfe", "ok.py": "X = 1\n"}), ["bad.py", "ok.py"])
    assert res.facts["ok.py"].error is None
    assert res.facts["ok.py"].loc == 1
    assert res.facts["bad.py"].error == "UnicodeDecodeError"
    res = scan(DictSource({"chain.py": chain_600, "ok.py": "X = 1\n"}), ["chain.py", "ok.py"])
    assert res.facts["ok.py"].error is None
    assert res.facts["ok.py"].loc == 1

    # D1: предел размера блоба
    assert scan_mod.MAX_BLOB_BYTES == 1_048_576
    edge = scan(DictSource({"edge.py": b"#" * 1_048_576}), ["edge.py"]).facts["edge.py"]
    assert edge.error is None
    assert edge.loc == 1

    def big_scenario():
        con = connect(tmp_path / "atlas.sqlite")
        big = DictSource({"big.py": b"#" * 1_048_577})
        res = scan(big, ["big.py"], con)
        assert res.facts["big.py"] == FileFacts(loc=0, error="BlobTooLarge")
        assert (res.parsed, res.hits, _rows(con)) == (1, 0, 1)
        res = scan(big, ["big.py"], con)
        assert (res.parsed, res.hits, _rows(con)) == (0, 1, 1)

    run_with_deadline(big_scenario, DEADLINE_S)


def test_class_methods_keep_dunder_members():
    protocol = _classes(SRC_METHODS_PROTOCOL)
    assert protocol["P"].methods == ("__call__",)
    assert protocol["P"].style == "Protocol"
    assert protocol["P"].bases == ("Protocol",)
    assert protocol["P"].line == 2
    assert protocol["C"].methods == ("__init__", "run")
    assert protocol["C"].style == "class"
    assert protocol["C"].bases == ()
    assert protocol["C"].line == 4

    styles = _classes(SRC_STYLES)
    assert {n: c.style for n, c in styles.items()} == {
        "A": "ABC",
        "B": "ABC",
        "N": "ABC",
        "G": "Protocol",
        "H": "Protocol",
        "Plain": "class",
    }
    assert {n: c.bases for n, c in styles.items()} == {
        "A": ("ABC",),
        "B": ("A",),
        "N": (),
        "G": ("Protocol[T]",),
        "H": ("G",),
        "Plain": (),
    }
    assert {n: c.line for n, c in styles.items()} == {"A": 4, "B": 6, "N": 8, "G": 10, "H": 12, "Plain": 14}
