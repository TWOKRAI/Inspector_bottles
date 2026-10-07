"""Тесты CLI ядра scripts/atlas: порядок флагов, проверка ref, гонка build, коды выхода (Task 1.2, ревью р.1).

Purpose: красные на дефекты ревью р.1 — `--main-ref` до подкоманды, `--json --ref`, ref-инъекции,
    гонка find_build/INSERT, исключение вместо кода выхода 2. Фикстуры `repo` и `atlas` — из conftest.
Public API: тесты `test_*`.
Stability: lite
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest

__all__: list[str] = []


def _db(repo: Any) -> Path:
    return repo.path / "data" / "atlas.sqlite"


def _builds(repo: Any, columns: str = "main_ref") -> list[tuple[Any, ...]]:
    con = sqlite3.connect(_db(repo))
    try:
        return con.execute(f"SELECT {columns} FROM builds ORDER BY build_id").fetchall()
    finally:
        con.close()


def _seed(repo: Any, commits: int = 1) -> None:
    repo.write(".gitignore", "data/\n")
    for i in range(commits):
        repo.write("README.md", f"v{i}\n")
        repo.commit(f"c{i}")


def test_main_ref_before_and_after_subcommand_both_apply(repo: Any, atlas: Any) -> None:
    _seed(repo)
    repo.git("branch", "feat-a")
    repo.git("branch", "feat-b")
    before = atlas(repo, "--main-ref", "feat-a", "build")
    after = atlas(repo, "build", "--main-ref", "feat-b")
    assert (before.code, after.code) == (0, 0), (before.err, after.err)
    assert _builds(repo) == [("feat-a",), ("feat-b",)]


def test_json_with_ref_prints_that_revision(repo: Any, atlas: Any) -> None:
    _seed(repo, commits=2)
    parent = repo.git("rev-parse", "HEAD~1")
    res = atlas(repo, "--json", "--ref", "HEAD~1")
    assert res.code == 0, res.err
    assert f'"head": "{parent}"' in res.out


def test_json_with_subcommand_exits_2(repo: Any, atlas: Any) -> None:
    _seed(repo)
    assert atlas(repo, "--json").code == 0  # якорь: сам --json работает
    res = atlas(repo, "--json", "build")
    assert res.code == 2
    assert res.err.strip() != ""


def test_option_like_or_range_ref_exits_2_and_writes_no_file(repo: Any, atlas: Any) -> None:
    _seed(repo, commits=2)
    assert atlas(repo, "build", "--ref", "HEAD").code == 0  # якорь: валидный ref принят
    attacks = [
        ("build", "--ref=--foo"),
        ("build", "--ref", "HEAD~1..HEAD"),
        ("check", "--base=--output=PWNED"),
    ]
    codes = {args: atlas(repo, *args).code for args in attacks}
    assert codes == {args: 2 for args in attacks}
    assert [p for p in repo.path.rglob("PWNED*")] == []
    for row in _builds(repo, "sha, main_ref, fingerprint"):
        assert all("\n" not in col and "--" not in col for col in row), row


def test_build_race_loser_returns_winner_build_id(repo: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts.atlas import store
    from scripts.atlas.schema import AdapterOutput

    con = store.connect(_db(repo))
    try:
        winner = store.write_build(con, "a" * 40, "main", "fp", AdapterOutput())
        real = store.find_build
        calls: list[int] = []

        def blind_first(*args: Any) -> int | None:
            calls.append(1)
            return None if len(calls) == 1 else real(*args)

        monkeypatch.setattr(store, "find_build", blind_first)
        loser = store.write_build(con, "a" * 40, "main", "fp", AdapterOutput())
        assert loser == winner
        assert con.execute("SELECT COUNT(*) FROM builds").fetchone()[0] == 1
    finally:
        con.close()


def test_readonly_db_exits_2_not_1(repo: Any, atlas: Any) -> None:
    _seed(repo)
    assert atlas(repo, "build").code == 0  # якорь: на записываемой базе всё работает
    repo.write("README.md", "next\n")
    repo.commit("next")
    db = _db(repo)
    # каталог на месте файла БД: sqlite не откроет его на запись ни под root, ни на Windows
    db.unlink()
    db.mkdir()
    try:
        res = atlas(repo, "check")
    finally:
        db.rmdir()
    assert res.code == 2
    assert res.err.startswith("atlas: internal error:"), res.err
