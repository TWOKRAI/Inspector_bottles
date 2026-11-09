"""Тесты автора map-A1: опасные места сканера `scripts/atlas/scan.py` и кэша `scan_cache`.

Purpose: то, что слепой тестер не видит: две нити в одну базу, база занята писателем, битое тело кэша, круг
    to_json/from_json, пути с пробелом/кириллицей/переводом строки, патологические исходники рядом с обычными,
    усечённый вывод cat-file, порции get_scans, огромный блоб сквозь git. Ожидаемые значения — литералы.
Public API: нет (только test_*).
Stability: lite
"""

from __future__ import annotations

import sqlite3
import subprocess
import threading

import pytest

import scripts.atlas.tree as tree_module
from scripts.atlas import store
from scripts.atlas.scan import ClassFact, DictSource, FileFacts, ImportRec, scan, scan_text
from scripts.atlas.store import get_scans, put_scans
from scripts.atlas.tests.conftest import run_with_deadline
from scripts.atlas.tree import AtlasError, Tree, read_blobs

__all__: list[str] = []

JOIN_S = 60.0


def _count(con: sqlite3.Connection) -> int:
    return con.execute("SELECT count(*) FROM scan_cache").fetchone()[0]


def test_two_scans_one_db_rows_equal_distinct_blobs(repo, tmp_path):
    files = {f"m{i}.py": f"V = {i % 4}\n" for i in range(8)}  # 8 файлов, 4 различных блоба
    for name, text in files.items():
        repo.write(name, text)
    repo.commit("init")
    db = tmp_path / "atlas.sqlite"
    paths = list(files)
    errors: list[BaseException] = []
    results: list[int] = []

    def worker() -> None:
        try:
            con = store.connect(db)  # соединение sqlite — на нить
            try:
                results.append(len(scan(Tree(repo.path, "HEAD"), paths, con).facts))
            finally:
                con.close()
        except BaseException as exc:  # noqa: BLE001 — в главную нить
            errors.append(exc)

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(JOIN_S)
        assert not t.is_alive()
    assert errors == []
    assert results == [8, 8]
    con = store.connect(db)
    assert _count(con) == 4


def test_db_locked_by_writer_scan_still_returns_facts(tmp_path, capsys):
    db = tmp_path / "atlas.sqlite"
    con = store.connect(db)
    con.execute("PRAGMA busy_timeout = 0")
    writer = sqlite3.connect(db, isolation_level=None)
    writer.execute("BEGIN EXCLUSIVE")
    try:
        assert get_scans(con, "s1", ["o1"]) == {}
        err = capsys.readouterr().err
        assert "atlas:" in err
        put_scans(con, "s1", [("o1", "[1]")])
        assert "atlas:" in capsys.readouterr().err

        res = scan(DictSource({"a.py": "A = 1\n", "b.py": "def f():\n    pass\n"}), ["a.py", "b.py"], con)
        assert (res.parsed, res.hits, res.missing) == (2, 0, ())
        assert res.facts["a.py"].loc == 1
        assert res.facts["b.py"].functions == ("f",)
    finally:
        writer.execute("ROLLBACK")
        writer.close()
    assert _count(con) == 0  # ничего не записано, исключений не было


def test_broken_cache_body_is_miss_and_rewritten(tmp_path):
    con = store.connect(tmp_path / "atlas.sqlite")
    source = DictSource({"a.py": "A = 1\n", "b.py": "B = 2\n", "c.py": "def c():\n    pass\n"})
    paths = ["a.py", "b.py", "c.py"]
    assert scan(source, paths, con).parsed == 3
    oids = source.oids()
    good = FileFacts.from_json  # тело до порчи
    original_c = con.execute("SELECT body FROM scan_cache WHERE oid = ?", (oids["c.py"],)).fetchone()[0]
    truncated = con.execute("SELECT body FROM scan_cache WHERE oid = ?", (oids["a.py"],)).fetchone()[0][:10]
    con.execute("UPDATE scan_cache SET body = ? WHERE oid = ?", (truncated, oids["a.py"]))
    con.execute("UPDATE scan_cache SET body = ? WHERE oid = ?", ("[1]", oids["b.py"]))
    con.commit()

    res = scan(source, paths, con)
    assert (res.parsed, res.hits) == (2, 1)
    assert res.facts["a.py"].loc == 1 and res.facts["b.py"].loc == 1
    assert _count(con) == 3
    bodies = dict(con.execute("SELECT oid, body FROM scan_cache"))
    assert good(bodies[oids["a.py"]]) == res.facts["a.py"]
    assert good(bodies[oids["b.py"]]) == res.facts["b.py"]
    assert bodies[oids["c.py"]] == original_c
    again = scan(source, paths, con)
    assert (again.parsed, again.hits) == (0, 3)


def test_json_round_trip_empty_and_full_tuples():
    empty = FileFacts()
    assert FileFacts.from_json(empty.to_json()) == empty
    assert FileFacts.from_json(FileFacts(loc=1, error="SyntaxError").to_json()) == FileFacts(loc=1, error="SyntaxError")

    src = (
        '"""Doc.\n\nTier: core\nContour: ipc, lifecycle\n"""\n'
        "import threading\nfrom . import n\n__all__ = ['A']\n"
        "class A(Protocol):\n    commands = {'z': 1}\n    def __call__(self): ...\n    def run(self): ...\n"
        "def f():\n    threading.Thread(target=f, name='w')\n"
    )
    full = scan_text(src)
    assert full.classes == (ClassFact("A", ("Protocol",), 9, ("__call__", "run"), "Protocol"),)
    assert full.threads == (("w", 14),)
    assert full.contour == ("ipc", "lifecycle")
    back = FileFacts.from_json(full.to_json())
    assert back == full
    assert back.imports[1] == ImportRec("hard", 7, 1, None, ("n",), True, False)
    assert hash(back) == hash(full)  # все контейнеры — tuple, иначе список ломает равенство и хеш
    for value in (back.all, back.classes, back.functions, back.imports, back.commands, back.threads, back.contour):
        assert isinstance(value, tuple)
    assert all(isinstance(t, tuple) for t in back.threads)
    assert all(isinstance(c.methods, tuple) and isinstance(c.bases, tuple) for c in back.classes)
    assert all(isinstance(i.names, tuple) for i in back.imports)


def test_paths_with_space_cyrillic_newline_do_not_shift_batch(repo):
    names = ["dir with space/a b.py", "каталог/файл.py", "plain.py"]
    for i, name in enumerate(names):
        repo.write(name, f"def f{i}():\n    pass\n")
    repo.commit("init")
    blob = repo.git("rev-parse", "HEAD:plain.py")
    newline_path = "x\ny.py"
    repo.git("-c", "core.protectNTFS=false", "update-index", "--add", "--cacheinfo", f"100644,{blob},{newline_path}")
    # на Windows такого файла не создать, запись в индекс — только с protectNTFS=false
    repo.git("commit", "-q", "-m", "newline path")

    tree = Tree(repo.path, "HEAD")
    assert newline_path in tree.oids()
    asked = [names[0], newline_path, names[1], names[2]]
    res = scan(tree, asked)
    assert res.missing == (newline_path,)
    assert list(res.facts) == [names[0], names[1], names[2]]
    assert [res.facts[n].functions for n in names] == [("f0",), ("f1",), ("f2",)]  # ответы не сдвинуты
    with pytest.raises(AtlasError):
        tree.read_many([names[0], newline_path, names[1]])
    with pytest.raises(AtlasError):
        read_blobs(repo.path, "HEAD", [newline_path], strict=False)
    assert Tree(repo.path, "HEAD").read_many(names)[names[1]] == b"def f1():\n    pass\n"


def test_pathological_sources_isolated_from_neighbours():
    chain600 = "x = " + " + ".join(["1"] * 600) + "\n"
    source = DictSource(
        {
            "chain.py": chain600,
            "nul.py": b"x = 1\x00\n",
            "latin.py": b"x = '\xe9'\n",
            "bom.py": b"\xef\xbb\xbfimport os\n",
            "paren.py": "x = " + "(" * 300 + "1" + ")" * 300 + "\n",
            "minus.py": "x = " + "-" * 3000 + "1\n",
            "syntax.py": "def (\n",
            "ok.py": "import sys\n\n\ndef ok():\n    pass\n",
        }
    )
    res = scan(source, list(source.files()))
    f = res.facts
    assert res.missing == () and res.parsed == 8
    assert f["chain.py"].loc == 1  # без исключения; error зависит от лимита рекурсии
    assert f["nul.py"].error in ("SyntaxError", "ValueError")
    assert f["latin.py"] == FileFacts(loc=0, error="UnicodeDecodeError")
    assert f["bom.py"].error is None and [r.module for r in f["bom.py"].imports] == ["os"]
    assert f["paren.py"].error == "SyntaxError"
    assert f["minus.py"].loc == 1
    assert f["syntax.py"] == FileFacts(loc=1, error="SyntaxError")
    assert f["ok.py"].error is None
    assert f["ok.py"].functions == ("ok",)
    assert [r.module for r in f["ok.py"].imports] == ["sys"]
    assert scan_text("\x00").error is not None  # str с NUL тоже не бросает


def test_truncated_cat_file_output_raises(repo, monkeypatch):
    repo.write("a.py", "A = 12345\n")
    repo.write("b.py", "B = 67890\n")
    repo.commit("init")
    real = tree_module.run_git

    def truncating(*args, **kwargs):
        proc = real(*args, **kwargs)
        return subprocess.CompletedProcess(proc.args, 0, proc.stdout[:-5], proc.stderr)  # код 0, хвост обрезан

    assert read_blobs(repo.path, "HEAD", ["a.py", "b.py"]) == {"a.py": b"A = 12345\n", "b.py": b"B = 67890\n"}
    monkeypatch.setattr(tree_module, "run_git", truncating)
    for strict in (True, False):
        with pytest.raises(AtlasError):
            read_blobs(repo.path, "HEAD", ["a.py", "b.py"], strict=strict)
    with pytest.raises(AtlasError):
        Tree(repo.path, "HEAD").read_many(["a.py", "b.py"])

    def failing(*args, **kwargs):
        proc = real(*args, **kwargs)
        return subprocess.CompletedProcess(proc.args, 128, proc.stdout, proc.stderr)

    monkeypatch.setattr(tree_module, "run_git", failing)
    with pytest.raises(AtlasError):
        read_blobs(repo.path, "HEAD", ["a.py"], strict=False)


def test_get_scans_chunks_over_500_oids(tmp_path):
    con = store.connect(tmp_path / "atlas.sqlite")
    oids = [f"{i:040x}" for i in range(1200)]
    put_scans(con, "s1", [(oid, f"body-{i}") for i, oid in enumerate(oids)])
    put_scans(con, "s2", [(oids[0], "other")])
    statements: list[str] = []
    con.set_trace_callback(statements.append)
    got = get_scans(con, "s1", oids + ["f" * 40])
    con.set_trace_callback(None)
    assert len(got) == 1200
    assert got[oids[0]] == "body-0" and got[oids[1199]] == "body-1199"
    assert len([s for s in statements if s.lstrip().upper().startswith("SELECT")]) == 3  # 500 + 500 + 201
    assert get_scans(con, "s1", []) == {}
    assert get_scans(con, "s2", oids) == {oids[0]: "other"}


def test_blob_over_limit_not_decoded(repo):
    (repo.path / "huge.py").write_bytes(b"\xff" * 1_048_577)  # не-UTF-8: декодирование дало бы UnicodeDecodeError
    (repo.path / "edge.py").write_bytes(b"#" * 1_048_576)
    repo.write("mid.py", "# строка комментария\n" * 20000)  # около 400 КБ
    repo.commit("init")
    res = scan(Tree(repo.path, "HEAD"), ["huge.py", "edge.py", "mid.py"])
    assert res.facts["huge.py"] == FileFacts(loc=0, error="BlobTooLarge")
    assert res.facts["edge.py"].error is None and res.facts["edge.py"].loc == 1
    assert res.facts["mid.py"].error is None
    assert res.facts["mid.py"].loc == 20000
    assert res.parsed == 3


def test_run_with_deadline_is_importable():
    # якорь: тесты выше зависят от git-фикстур из conftest, а не от своих копий
    assert run_with_deadline(lambda: 1, 5.0) == 1
