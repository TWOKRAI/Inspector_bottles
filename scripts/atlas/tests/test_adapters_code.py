"""Приёмочные тесты адаптера `code` (Task 1.5a, RED до кода): узлы interface и test, рёбра exposes и tests,
находки INTERFACE_WITHOUT_TEST и PRE_POST_MISSING, версия адаптера, цифры на реальном checkout.

Purpose: слой качества по коду — что выставляет модуль, чем это проверено, какие изменённые методы без контракта.
Public API: тесты test_*; публичных имён нет.
Stability: lite

Импорты проверяемого кода (CodeAdapter, store, build) внутри тестов: отсутствие кода даёт красный на каждом
тесте, а не одну ошибку сбора.
"""

from __future__ import annotations

import ast
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from scripts.atlas.tests.conftest import GitRepo, run_with_deadline

__all__: list[str] = []

_ROOT = Path(__file__).resolve().parents[3]
_PIN = "4d1b3efe0e5e88913bd6c359c5101580cdb73b69"
_PINNED_DOC: dict[str, Any] = {}


def _modules_yaml(rows: list[tuple[str, list[str]]]) -> str:
    text = "version: 1\nmodules:\n"
    for module_id, paths in rows:
        text += (
            f"  - id: {module_id}\n    paths: {json.dumps(paths)}\n    layer: scripts\n"
            "    tier: null\n    docs: []\n    parent: null\n"
        )
    return text


def _setup(repo: GitRepo, rows: list[tuple[str, list[str]]] | None, files: dict[str, str]) -> str:
    """Один коммит: .gitignore (data/), modules.yaml (если rows не None) и файлы."""
    repo.write(".gitignore", "data/\n")
    if rows is not None:
        repo.write("modules.yaml", _modules_yaml(rows))
    for rel, text in files.items():
        repo.write(rel, text)
    return repo.commit("init")


def _doc(atlas: Any, repo: GitRepo, ref: str, main_ref: str = "main") -> dict[str, Any]:
    res = atlas(repo, "--json", "--ref", ref, "--main-ref", main_ref)
    assert res.code == 0, res.err
    return json.loads(res.out)


def _nodes(doc: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    return [n for n in doc["nodes"] if n["kind"] == kind]


def _edges(doc: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    return [e for e in doc["edges"] if e["kind"] == kind]


def _findings(doc: dict[str, Any], code: str) -> list[dict[str, Any]]:
    return [f for f in doc["findings"] if f["code"] == code]


_PASS_CLASS = "class {}:\n    pass\n"


def test_interface_nodes_and_exposes_edges(repo: GitRepo, repo_factory: Any, atlas: Any) -> None:
    rows = [("m", ["m/"]), ("m/sub", ["m/sub/"]), ("n", ["n/"]), ("x", ["x/main.py"])]
    sha = _setup(
        repo,
        rows,
        {
            "m/interfaces.py": (
                '__all__ = ["I", "J", "I", "_Hidden"]\n\n\nclass I:\n    pass\n\n\nclass J:\n    pass\n\n\n'
                "class _P:\n    pass\n"
            ),
            "m/sub/interfaces.py": (
                "from os import Imported\n\nCONST = 1\n\n\nclass Pub:\n    pass\n\n\nclass _Priv:\n    pass\n\n\n"
                "def helper():\n    pass\n\n\nasync def ahelper():\n    pass\n"
            ),
            "n/interfaces.py": ('from os import path as Reexp\n\n__all__ = ["Reexp", "K"]\n\n\nclass K:\n    pass\n'),
            "m/core/interfaces.py": _PASS_CLASS.format("Nested"),
            "tools/interfaces.py": _PASS_CLASS.format("T"),
            "x/interfaces.py": _PASS_CLASS.format("XI"),
        },
    )
    doc = _doc(atlas, repo, sha)
    expected = {
        "m:I": "m/interfaces.py",
        "m:J": "m/interfaces.py",
        "m:_Hidden": "m/interfaces.py",
        "m/sub:Pub": "m/sub/interfaces.py",
        "m/sub:helper": "m/sub/interfaces.py",
        "m/sub:ahelper": "m/sub/interfaces.py",
        "n:Reexp": "n/interfaces.py",
        "n:K": "n/interfaces.py",
    }
    nodes = _nodes(doc, "interface")
    assert sorted(n["id"] for n in nodes) == sorted(expected)
    for node in nodes:
        assert node["path"] == expected[node["id"]], node
        assert node["status"] is None
        assert node["time"] is None
    edges = sorted((e["src"], e["dst"], e["via"]) for e in _edges(doc, "exposes"))
    assert edges == sorted((f"module:{key.rsplit(':', 1)[0]}", f"interface:{key}", "path") for key in expected)

    dup = repo_factory.create("dup")
    dup_sha = _setup(
        dup,
        [("n2", ["n2/"])],
        {
            "n2/interfaces.py": (
                "class Dup:\n    pass\n\n\nclass Dup:\n    pass\n\n\ndef over():\n    pass\n\n\ndef over():\n    pass\n"
            )
        },
    )
    dup_doc = _doc(atlas, dup, dup_sha)
    assert sorted(n["id"] for n in _nodes(dup_doc, "interface")) == ["n2:Dup", "n2:over"]

    bare = repo_factory.create("bare")
    bare_sha = _setup(bare, None, {"m/interfaces.py": _PASS_CLASS.format("I")})
    bare_doc = _doc(atlas, bare, bare_sha)
    assert _nodes(bare_doc, "interface") == []
    assert _edges(bare_doc, "exposes") == []


def test_interfaces_syntax_error_exits_2(repo: GitRepo, repo_factory: Any, atlas: Any) -> None:
    sha = _setup(repo, [("m", ["m/"])], {"m/interfaces.py": "class (:\n"})
    res = atlas(repo, "build", "--ref", sha, "--main-ref", "main")
    assert res.code == 2
    assert res.err == "atlas: interfaces.py is not valid Python\n"

    other = repo_factory.create("other")
    other_sha = _setup(
        other,
        [("m", ["m/"])],
        {"m/interfaces.py": _PASS_CLASS.format("I"), "q/interfaces.py": "class (:\n"},
    )
    res = atlas(other, "build", "--ref", other_sha, "--main-ref", "main")
    assert res.code == 0, res.err


_TEST_A = """import pytest


def test_one():
    pass


async def test_two():
    pass


def helper():
    pass


class TestK:
    def test_m(self):
        def test_deep():
            pass

    def util(self):
        pass


class Helper:
    def test_not(self):
        pass


@pytest.mark.parametrize("a", [1, 2])
def test_p(a):
    pass
"""


def test_test_nodes_ids(repo: GitRepo, atlas: Any) -> None:
    sha = _setup(
        repo,
        [("m", ["m/"])],
        {
            "m/tests/test_a.py": _TEST_A,
            "m/tests/b_test.py": "def test_b():\n    pass\n",
            "m/tests/test_dup.py": "def test_x():\n    pass\n\n\ndef test_x():\n    pass\n",
            "m/tests/helpers.py": "def test_hidden():\n    pass\n",
            "m/conftest.py": "def test_hidden():\n    pass\n",
        },
    )
    nodes = _nodes(_doc(atlas, repo, sha), "test")
    expected = {
        "m/tests/test_a.py::test_one": "m/tests/test_a.py",
        "m/tests/test_a.py::test_two": "m/tests/test_a.py",
        "m/tests/test_a.py::test_p": "m/tests/test_a.py",
        "m/tests/test_a.py::TestK::test_m": "m/tests/test_a.py",
        "m/tests/b_test.py::test_b": "m/tests/b_test.py",
        "m/tests/test_dup.py::test_x": "m/tests/test_dup.py",
    }
    assert sorted(n["id"] for n in nodes) == sorted(expected)
    for node in nodes:
        assert node["path"] == expected[node["id"]], node
        assert node["status"] is None
        assert node["time"] is None


def test_tests_edges_path_and_import(repo: GitRepo, atlas: Any) -> None:
    rows = [(i, [f"{i}/"]) for i in ("m", "n", "r", "s", "t", "u", "q")]
    one = "\n\n\ndef {}():\n    pass\n"
    sha = _setup(
        repo,
        rows,
        {
            "m/tests/test_a.py": (
                "from m.core import X\nfrom n.core import Y\nfrom .. import core\nimport os, sys\n"
                "from collections import deque\n# from q.x import Q\n\n\ndef test_a():\n    from r.deep import D\n"
            ),
            "m/tests/test_c.py": "from ...s.core import Z" + one.format("test_c"),
            "t/__init__.py": "",
            "m/tests/test_d.py": "import t" + one.format("test_d"),
            "m/tests/test_e.py": "import os, u.sub.mod as usm" + one.format("test_e"),
            "m/tests/test_f.py": "from nowhere import q\nfrom ....... import z" + one.format("test_f"),
            "tests/test_o.py": "from m.core import X" + one.format("test_o"),
        },
    )
    got: dict[str, list[tuple[str, str]]] = {}
    for edge in _edges(_doc(atlas, repo, sha), "tests"):
        got.setdefault(edge["src"], []).append((edge["dst"], edge["via"]))
    assert {src: sorted(pairs) for src, pairs in got.items()} == {
        "test:m/tests/test_a.py::test_a": [
            ("module:m", "path"),
            ("module:n", "ast-import"),
            ("module:r", "ast-import"),
        ],
        "test:m/tests/test_c.py::test_c": [("module:m", "path"), ("module:s", "ast-import")],
        "test:m/tests/test_d.py::test_d": [("module:m", "path"), ("module:t", "ast-import")],
        "test:m/tests/test_e.py::test_e": [("module:m", "path"), ("module:u", "ast-import")],
        "test:m/tests/test_f.py::test_f": [("module:m", "path")],
        "test:tests/test_o.py::test_o": [("module:m", "ast-import")],
    }


def test_interface_without_test_rules(repo: GitRepo, atlas: Any) -> None:
    rows = [("m", ["m/"]), ("n", ["n/"]), ("p", ["p/"])]
    sha = _setup(
        repo,
        rows,
        {
            "m/interfaces.py": (
                '__all__ = ["I", "J", "K", "L", "M", "Cfg"]\n\n\n'
                + "".join(_PASS_CLASS.format(name) + "\n\n" for name in ("I", "J", "K", "L", "M", "Cfg")).rstrip()
                + "\n"
            ),
            "n/interfaces.py": _PASS_CLASS.format("Z"),
            "p/interfaces.py": _PASS_CLASS.format("P1") + "\n\n" + _PASS_CLASS.format("P2"),
            "m/tests/test_a.py": (
                "from m.interfaces import I\n# J is covered elsewhere\nCfgExtra = 1\n\n\ndef test_x():\n    pass\n"
            ),
            "n/tests/test_n.py": "# K is tested here\n\n\ndef test_x():\n    pass\n",
            "tests/test_o.py": "from m.core import L\n# L\n\n\ndef test_x():\n    pass\n",
            "m/tests/test_empty.py": "# M is mentioned, nothing is tested\n",
            "m/tests/helpers.py": "# M again\n",
        },
    )
    found = _findings(_doc(atlas, repo, sha), "INTERFACE_WITHOUT_TEST")
    sources = {
        "interface:m:K": "m/interfaces.py",
        "interface:m:M": "m/interfaces.py",
        "interface:m:Cfg": "m/interfaces.py",
        "interface:n:Z": "n/interfaces.py",
        "interface:p:P1": "p/interfaces.py",
        "interface:p:P2": "p/interfaces.py",
    }
    assert sorted(f["node"] for f in found) == sorted(sources)
    for finding in found:
        assert finding["severity"] == "info"
        assert finding["detail"] == ""
        assert finding["source"] == sources[finding["node"]], finding
        assert finding["message"] != ""


_A_TEXT = '''__all__ = ["I", "f"]


class I:
    def a(self):
        """x"""

    def b(self):
        """Pre: p
        Post: q
        """

    def c(self):
        """Pre: p"""

    def d(self):
        """Post: q"""
        pass

    def _p(self):
        pass

    @property
    def prop(self):
        pass

    @property
    def x(self):
        pass

    @x.setter
    def x(self, v):
        pass


def f():
    pass


class J:
    def z(self):
        pass
'''

_B_TEXT = '''__all__ = ["I", "f"]


class I:
    def g(self):
        """Pre: g
        Post: g
        """

    def a(self):
        """x"""

    def b(self):
        """Pre: p"""

    def c(self):
        """Pre: p"""

    def d(self):
        """Post: q"""
        return 1

    def e(self):
        pass

    def _p(self):
        return 2

    @property
    @abstractmethod
    def prop(self):
        pass

    @property
    def x(self):
        {get}

    @x.setter
    def x(self, v):
        {set}


def f():
    return 3


class J:
    def z(self):
        return 4
'''

_N_TEXT = '''class N:
    def p(self):
        pass

    def q(self):
        """Pre: a
        Post: b
        """

    def r(self):
        """Pre: a"""


def top():
    pass
'''

_I_TEXT = '''class I:
    def a(self):
        pass

    def b(self):
        """Pre: a
        Post: b
        """

    def c(self):
        """Pre: a"""
'''


def _ppm(db: Path, root: Path, ref: str, base_ref: str | None) -> list[tuple[str, str, str, str]]:
    from scripts.atlas import store
    from scripts.atlas.build import build
    from scripts.atlas.tree import Tree

    base = Tree(root, base_ref) if base_ref else None

    def work() -> list[tuple[str, str, str, str]]:  # соединение sqlite живёт в потоке, который его создал
        con = store.connect(db)
        try:
            data = store.read_build(con, build(con, root, ref, "main", base=base))
        finally:
            con.close()
        return sorted((f.detail, f.node, f.severity, f.source) for f in data.findings if f.code == "PRE_POST_MISSING")

    return run_with_deadline(work)


def test_pre_post_missing_only_changed_public_methods(repo: GitRepo, repo_factory: Any, tmp_path: Path) -> None:
    rows = [("m", ["m/"]), ("n", ["n/"])]
    a = _setup(repo, rows, {"m/interfaces.py": _A_TEXT})
    repo.write("m/interfaces.py", _B_TEXT.format(get="pass", set="pass"))
    b = repo.commit("B")
    repo.write("m/interfaces.py", _B_TEXT.format(get="return 5", set="return 6"))
    b2 = repo.commit("B2")
    db = tmp_path / "ppm.sqlite"
    path = "m/interfaces.py"
    assert _ppm(db, repo.path, b, a) == [
        ("I.b", "interface:m:I", "blocking", f"{path}:13"),
        ("I.d", "interface:m:I", "blocking", f"{path}:19"),
        ("I.e", "interface:m:I", "blocking", f"{path}:23"),
        ("I.prop", "interface:m:I", "blocking", f"{path}:29"),
        ("f", "interface:m:f", "blocking", f"{path}:43"),
    ]
    # геттер и сеттер x изменены, оба без маркеров: одна находка по первому вхождению
    assert _ppm(db, repo.path, b2, b) == [("I.x", "interface:m:I", "blocking", f"{path}:34")]
    # сборка без base после сборок с base: находки нет вовсе
    assert _ppm(db, repo.path, b, None) == []

    # файла нет на base: все публичные функции без обоих маркеров — находки
    fresh = repo_factory.create("fresh")
    fa = _setup(fresh, rows, {"m/interfaces.py": "class M:\n    pass\n"})
    fresh.write("n/interfaces.py", _N_TEXT)
    fb = fresh.commit("add n")
    assert _ppm(tmp_path / "ppm_fresh.sqlite", fresh.path, fb, fa) == [
        ("N.p", "interface:n:N", "blocking", "n/interfaces.py:2"),
        ("N.r", "interface:n:N", "blocking", "n/interfaces.py:10"),
        ("top", "interface:n:top", "blocking", "n/interfaces.py:14"),
    ]

    # на base файл не разбирается как Python: все функции без маркеров — находки
    broken = repo_factory.create("broken")
    ba = _setup(broken, [("m", ["m/"])], {"m/interfaces.py": "class (:\n"})
    broken.write("m/interfaces.py", _I_TEXT)
    bb = broken.commit("fix syntax")
    assert _ppm(tmp_path / "ppm_broken.sqlite", broken.path, bb, ba) == [
        ("I.a", "interface:m:I", "blocking", "m/interfaces.py:2"),
        ("I.c", "interface:m:I", "blocking", "m/interfaces.py:10"),
    ]


_CHECK_BASE = '__all__ = ["I"]\n\n\nclass I:\n    def a(self):\n        pass\n'


def test_check_blocks_a_new_method_without_contract_after_json_on_head(repo: GitRepo, atlas: Any) -> None:
    _setup(repo, [("m", ["m/"])], {"m/interfaces.py": _CHECK_BASE})
    repo.git("checkout", "-q", "-b", "feat")
    repo.write("m/interfaces.py", _CHECK_BASE + "\n    def c(self):\n        pass\n")
    repo.commit("add c")
    repo.git("checkout", "-q", "main")
    repo.git("checkout", "-q", "-b", "feat2")
    repo.write("m/tests/test_x.py", "def test_x():\n    pass\n")
    repo.commit("add test")
    db = repo.path / "data" / "atlas.sqlite"

    repo.git("checkout", "-q", "feat")
    assert len(_findings(_doc(atlas, repo, "feat"), "PRE_POST_MISSING")) == 0  # HEAD без base
    res = atlas(repo, "check", "--main-ref", "main")
    lines = res.out.splitlines()
    assert res.code == 1, res.out + res.err
    assert "blocking PRE_POST_MISSING interface:m:I I.c" in lines
    assert lines[-1] == "atlas check: 1 new blocking, 0 new warning, 0 new info"

    repo.git("checkout", "-q", "feat2")
    res = atlas(repo, "check", "--main-ref", "main")
    assert res.code == 0, res.out + res.err
    repo.git("checkout", "-q", "main")
    res = atlas(repo, "check", "--main-ref", "main")
    assert res.code == 0, res.out + res.err

    # обратный порядок на свежей базе: check, затем --json на том же HEAD
    db.unlink()
    repo.git("checkout", "-q", "feat")
    res = atlas(repo, "check", "--main-ref", "main")
    assert res.code == 1, res.out + res.err
    assert len(_findings(_doc(atlas, repo, "feat"), "PRE_POST_MISSING")) == 0


def test_code_adapter_version_follows_s2_gate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts.atlas.adapters.code import CodeAdapter
    from scripts.atlas.build import fingerprint

    gate = tmp_path / "gate.py"
    monkeypatch.setattr("scripts.atlas.adapters.code.S2_GATE", gate)
    adapter = CodeAdapter()
    assert adapter.name == "code"

    gate.write_text("# one", encoding="utf-8")
    one = (adapter.version, fingerprint())
    assert isinstance(one[0], int)
    assert (adapter.version, fingerprint()) == one
    gate.write_text("# two", encoding="utf-8")
    two = (adapter.version, fingerprint())
    assert two[0] != one[0]
    assert two[1] != one[1]

    monkeypatch.setattr("scripts.atlas.adapters.code.S2_GATE", tmp_path / "missing.py")
    missing = adapter.version
    assert isinstance(missing, int)
    assert missing % 2**48 == 0
    assert isinstance(fingerprint(), str)


def _git(*args: str) -> tuple[int, str]:
    def call() -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(["git", "-C", str(_ROOT), *args], capture_output=True, check=False)

    proc = run_with_deadline(call)
    return proc.returncode, proc.stdout.decode("utf-8", "replace").strip()


def _pin_preconditions() -> None:
    code, shallow = _git("rev-parse", "--is-shallow-repository")
    assert (code, shallow) == (0, "false"), "клон неполный: выполнить `git fetch --unshallow` перед тестом"
    code, kind = _git("cat-file", "-t", _PIN)
    assert (code, kind) == (0, "commit"), f"коммит {_PIN} не разрешается в этом клоне"


def _pinned_doc(atlas: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Any]:
    """Сборка пина на СВЕЖЕЙ базе (data/atlas.sqlite checkout кэширует сборки по sha и отпечатку)."""
    if "doc" in _PINNED_DOC:
        return _PINNED_DOC["doc"]
    from scripts.atlas import store

    _pin_preconditions()
    real = store.connect
    monkeypatch.setattr("scripts.atlas.store.connect", lambda _path: real(tmp_path / "fresh.sqlite"))
    doc = _doc(atlas, GitRepo(_ROOT), _PIN, _PIN)
    _PINNED_DOC["doc"] = doc
    return doc


def test_pinned_counts_on_this_checkout(atlas: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    doc = _pinned_doc(atlas, monkeypatch, tmp_path)
    assert len(_nodes(doc, "interface")) == 187
    assert len(_nodes(doc, "test")) == 20393
    exposes = _edges(doc, "exposes")
    assert len(exposes) == 187
    assert {e["via"] for e in exposes} == {"path"}
    tests = _edges(doc, "tests")
    assert len(tests) == 34851
    assert sum(1 for e in tests if e["via"] == "path") == 20272
    assert sum(1 for e in tests if e["via"] == "ast-import") == 14579
    without_test = _findings(doc, "INTERFACE_WITHOUT_TEST")
    assert len(without_test) == 96
    assert {f["severity"] for f in without_test} == {"info"}
    assert _findings(doc, "PRE_POST_MISSING") == []
    assert len({e["src"] for e in exposes}) == 45
    router = sorted(n["id"] for n in _nodes(doc, "interface") if n["id"].startswith("router_module:"))
    assert router == ["router_module:IMessageChannel", "router_module:IRouterManager"]
    router_findings = [f["node"] for f in without_test if f["node"].startswith("interface:router_module:")]
    assert router_findings == ["interface:router_module:IRouterManager"]


def _oracle_ids() -> set[str]:
    proc = run_with_deadline(
        lambda: subprocess.run(
            ["git", "-C", str(_ROOT), "ls-tree", "-r", "--name-only", "-z", _PIN], capture_output=True, check=False
        )
    )
    assert proc.returncode == 0
    paths = [p.decode("utf-8") for p in proc.stdout.split(b"\0") if p]
    files = [p for p in paths if p.rsplit("/", 1)[-1].startswith("test_") and p.endswith(".py")]
    files += [p for p in paths if p.endswith("_test.py") and p not in files]
    batch = run_with_deadline(
        lambda: subprocess.run(
            ["git", "-C", str(_ROOT), "cat-file", "--batch"],
            input="".join(f"{_PIN}:{p}\n" for p in files).encode("utf-8"),
            capture_output=True,
            check=False,
        )
    )
    assert batch.returncode == 0
    data, pos, ids = batch.stdout, 0, set()
    for path in files:
        end = data.index(b"\n", pos)
        _sha, kind, size = data[pos:end].decode("utf-8").split(" ")
        assert kind == "blob", path
        body = data[end + 1 : end + 1 + int(size)]
        pos = end + 1 + int(size) + 1
        tree = ast.parse(body.decode("utf-8", "replace"))
        for node in tree.body:
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name.startswith("test"):
                ids.add(f"{path}::{node.name}")
            elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
                for item in node.body:
                    if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef) and item.name.startswith("test"):
                        ids.add(f"{path}::{node.name}::{item.name}")
    return ids


def test_test_nodes_match_ast_oracle(atlas: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    doc = _pinned_doc(atlas, monkeypatch, tmp_path)
    got = {n["id"] for n in _nodes(doc, "test")}
    oracle = run_with_deadline(_oracle_ids, 120)
    assert len(oracle) == 20393
    assert len(got) == 20393
    assert got == oracle, (sorted(got - oracle)[:5], sorted(oracle - got)[:5])


def test_cat_file_header_with_a_space_in_the_path_is_missing_not_error(repo: GitRepo, atlas: Any) -> None:
    _setup(repo, [("mm", ["my mod/"])], {"README.md": "x\n"})
    repo.git("checkout", "-q", "-b", "feat")
    repo.write("my mod/interfaces.py", '__all__ = ["I"]\n\n\nclass I:\n    def a(self):\n        pass\n')
    repo.commit("add interface in a path with a space")
    res = atlas(repo, "check", "--main-ref", "main")
    assert res.code == 1, res.out + res.err
    assert res.err == ""
    assert "blocking PRE_POST_MISSING interface:mm:I I.a" in res.out.splitlines()


_BOM_TEXT = b"\xef\xbb\xbfclass I:\n    def a(self):\n        pass\n"


def _commit_bytes(repo: GitRepo, rel: str, data: bytes, message: str) -> str:
    target = repo.path / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return repo.commit(message)


def test_interfaces_file_with_utf8_bom(repo: GitRepo, repo_factory: Any, atlas: Any) -> None:
    # (а) файл с BOM разбирается: сборка проходит, узел есть
    solo = repo_factory.create("solo")
    solo.write(".gitignore", "data/\n")
    solo.write("modules.yaml", _modules_yaml([("m", ["m/"])]))
    sha = _commit_bytes(solo, "m/interfaces.py", _BOM_TEXT, "bom")
    res = atlas(solo, "build", "--ref", sha, "--main-ref", "main")
    assert res.code == 0, res.err
    assert [n["id"] for n in _nodes(_doc(atlas, solo, sha), "interface")] == ["m:I"]

    # (б) BOM есть только на base; тот же текст метода на HEAD без BOM -> метод не изменён
    repo.write(".gitignore", "data/\n")
    repo.write("modules.yaml", _modules_yaml([("m", ["m/"])]))
    _commit_bytes(repo, "m/interfaces.py", _BOM_TEXT, "main with bom")
    repo.git("checkout", "-q", "-b", "nobom")
    _commit_bytes(repo, "m/interfaces.py", _BOM_TEXT[3:], "drop bom")
    res = atlas(repo, "check", "--main-ref", "main")
    assert res.code == 0, res.out + res.err
    assert "PRE_POST_MISSING" not in res.out

    # BOM на обоих, дифф — посторонний файл
    repo.git("checkout", "-q", "main")
    repo.git("checkout", "-q", "-b", "bothbom")
    repo.write("README.md", "x\n")
    repo.commit("unrelated")
    res = atlas(repo, "check", "--main-ref", "main")
    assert res.code == 0, res.out + res.err
    assert "PRE_POST_MISSING" not in res.out
