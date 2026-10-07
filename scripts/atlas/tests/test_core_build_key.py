"""Приёмочные тесты ключа кэша сборки с деревом base и версии схемы базы (Task 1.5a, RED до кода).

Purpose: ключ кэша = (sha, main_ref, отпечаток, SHA ДЕРЕВА base); база другой версии схемы
    пересоздаётся, база той же версии не трогается.
Public API: тесты test_*; публичных имён нет.
Stability: lite
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from scripts.atlas.tests.conftest import GitRepo, run_with_deadline

__all__: list[str] = []

# Схема 1.3b (база коммита 4d1b3efe0), литералами; builds без base_tree.
_OLD_DDL = """
CREATE TABLE builds (
    build_id INTEGER PRIMARY KEY, sha TEXT NOT NULL, main_ref TEXT NOT NULL, fingerprint TEXT NOT NULL,
    UNIQUE (sha, main_ref, fingerprint));
CREATE TABLE nodes (
    build_id INTEGER NOT NULL, kind TEXT NOT NULL, id TEXT NOT NULL, path TEXT, status TEXT, time INTEGER,
    PRIMARY KEY (build_id, kind, id));
CREATE TABLE edges (
    build_id INTEGER NOT NULL, kind TEXT NOT NULL, src TEXT NOT NULL, dst TEXT NOT NULL, via TEXT NOT NULL);
CREATE INDEX edges_kind_dst ON edges (build_id, kind, dst);
CREATE TABLE findings (
    build_id INTEGER NOT NULL, code TEXT NOT NULL, severity TEXT NOT NULL, node TEXT NOT NULL,
    detail TEXT NOT NULL, message TEXT NOT NULL, source TEXT NOT NULL);
CREATE TABLE snapshots (
    build_id INTEGER NOT NULL, node TEXT NOT NULL, metric TEXT NOT NULL, value REAL, time INTEGER);
"""


class _Spy:
    """Адаптер: считает вызовы collect() и запоминает ctx.base."""

    name = "spy"
    version = 1

    def __init__(self) -> None:
        self.calls = 0
        self.bases: list[Any] = []

    def collect(self, ctx: Any) -> Any:
        from scripts.atlas.schema import AdapterOutput

        self.calls += 1
        self.bases.append(ctx.base)
        return AdapterOutput()


def test_cache_key_includes_the_base_tree(repo: GitRepo, tmp_path: Path, set_adapters: Any) -> None:
    from scripts.atlas import store
    from scripts.atlas.build import build
    from scripts.atlas.tree import Tree

    spy = _Spy()
    set_adapters(spy)
    shas = []
    for text in ("a", "b", "c"):
        repo.write("f.txt", text)
        shas.append(repo.commit(f"commit {text}"))
    a, b, c = shas
    root = repo.path
    db = tmp_path / "keys.sqlite"

    def go(base_ref: str | None = None) -> int:
        base = Tree(root, base_ref) if base_ref else None

        def work() -> int:  # соединение sqlite живёт в потоке, который его создал
            con = store.connect(db)
            try:
                return build(con, root, c, "main", base=base)
            finally:
                con.close()

        return run_with_deadline(work)

    x1 = go()
    x2 = go(a)
    x3 = go(b)
    assert len({x1, x2, x3}) == 3
    assert spy.calls == 3
    assert spy.bases[0] is None
    assert [spy.bases[1].ref, spy.bases[2].ref] == [a, b]

    assert go(a) == x2
    assert spy.calls == 3  # тот же base — из кэша, адаптер не зовётся

    repo.git("checkout", "-q", "-b", "side", a)
    repo.git("commit", "--allow-empty", "-q", "-m", "empty")
    e = repo.head
    assert e != a
    assert repo.git("rev-parse", f"{e}^{{tree}}") == repo.git("rev-parse", f"{a}^{{tree}}")
    assert go(e) == x2  # ключ — SHA дерева, не коммита
    assert spy.calls == 3


def _db(repo: GitRepo) -> Path:
    return repo.path / "data" / "atlas.sqlite"


def _commit_files(repo: GitRepo, text: str) -> str:
    repo.write("f.txt", text)
    return repo.commit(f"commit {text}")


def _query(path: Path, sql: str) -> list[tuple[Any, ...]]:
    con = sqlite3.connect(path)
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


def test_db_with_another_schema_version_is_recreated(repo: GitRepo, atlas: Any, set_adapters: Any) -> None:
    from scripts.atlas.tests.conftest import CountingAdapter

    set_adapters(CountingAdapter())
    repo.write(".gitignore", "data/\n")
    x = _commit_files(repo, "x")
    y = _commit_files(repo, "y")
    path = _db(repo)

    res = atlas(repo, "build", "--ref", x, "--main-ref", "main")
    assert res.code == 0, res.err
    assert path.is_file()

    # случай 1: база старой схемы (user_version 0, без base_tree, одна строка builds)
    path.unlink()
    old = sqlite3.connect(path)
    old.executescript(_OLD_DDL)
    old.execute("INSERT INTO builds (sha, main_ref, fingerprint) VALUES ('deadbeef', 'main', 'oldfp')")
    old.commit()
    assert old.execute("PRAGMA user_version").fetchone()[0] == 0
    old.close()
    res = atlas(repo, "build", "--ref", x, "--main-ref", "main")
    assert res.code == 0, res.err
    columns = [row[1] for row in _query(path, "PRAGMA table_info(builds)")]
    assert "base_tree" in columns
    assert _query(path, "SELECT sha FROM builds") == [(x,)]

    # случай 2: база другой версии схемы (user_version 999) с меткой
    marker = sqlite3.connect(path)
    marker.execute("INSERT INTO nodes (build_id, kind, id) VALUES (999, 'marker', 'marker')")
    marker.execute("PRAGMA user_version = 999")
    marker.commit()
    marker.close()
    assert _query(path, "SELECT count(*) FROM nodes WHERE kind = 'marker'") == [(1,)]
    res = atlas(repo, "build", "--ref", x, "--main-ref", "main")
    assert res.code == 0, res.err
    assert _query(path, "SELECT count(*) FROM nodes WHERE kind = 'marker'") == [(0,)]

    # случай 3: та же версия — файл не пересоздаётся: первая сборка пережила вторую, повтор не меняет байты
    path.unlink()
    for sha in (x, y):
        res = atlas(repo, "build", "--ref", sha, "--main-ref", "main")
        assert res.code == 0, res.err
    assert sorted(row[0] for row in _query(path, "SELECT sha FROM builds")) == sorted([x, y])
    before = path.read_bytes()
    res = atlas(repo, "build", "--ref", y, "--main-ref", "main")
    assert res.code == 0, res.err
    assert path.read_bytes() == before
