"""Авторский тест 1.6e: кэш видов сбрасывается правкой исходника Атласа (отпечаток кода, не версии адаптеров).

Purpose: `code_fingerprint()` читает *.py пакета (build._PKG); правка файла без бампа CORE_VERSION -> пересчёт.
Public API: тесты test_*; публичных имён нет.
Stability: lite
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest

from scripts.atlas.tests.conftest import RepoFactory
from scripts.atlas.tests.test_cache_1_6e import _REFS, _call, _install_spy, _new_repo

__all__: list[str] = []


def test_source_edit_of_atlas_invalidates_view_cache(
    repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from scripts.atlas import build

    pkg = tmp_path / "atlas_copy"
    shutil.copytree(build._PKG, pkg, ignore=shutil.ignore_patterns("tests", "__pycache__"))
    monkeypatch.setattr(build, "_PKG", pkg)
    repo = _new_repo(repo_factory, "code")
    spy = _install_spy(monkeypatch)
    _call(atlas, spy, repo, "ref", "m", *_REFS)
    _, warm = _call(atlas, spy, repo, "ref", "m", *_REFS)
    assert warm == {"build_graph": 0, "checkout": 0}  # без правки — из кэша
    with (pkg / "codemap.py").open("a", encoding="utf-8") as f:
        f.write("\n# правка исходника\n")
    _, cold = _call(atlas, spy, repo, "ref", "m", *_REFS)
    assert cold["build_graph"] >= 1 and cold["checkout"] >= 1
    _, again = _call(atlas, spy, repo, "ref", "m", *_REFS)
    assert again == {"build_graph": 0, "checkout": 0}  # новый отпечаток тоже кэшируется


# ---------------------------------------------------------------- находки ревью 1.6e (авторские)


def test_symbol_and_main_ref_are_part_of_the_key(repo_factory: RepoFactory, atlas: Any) -> None:
    repo = _new_repo(repo_factory, "key")
    full = atlas(repo, "ref", "m", *_REFS)
    one = atlas(repo, "ref", "m", "--symbol", "Alpha", *_REFS)
    assert full.code == one.code == 0
    assert full.out != one.out  # узкий вид не получает полный справочник из кэша
    empty = atlas(repo, "ref", "m", "--symbol", "", *_REFS)
    assert (empty.code, empty.err) == (2, "atlas: symbol not found\n")  # пустой символ — не «без символа»
    again = atlas(repo, "ref", "m", "--symbol", "Alpha", *_REFS)
    assert again.out == one.out


def test_main_ref_change_is_a_cache_miss(
    repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _new_repo(repo_factory, "mainref")
    spy = _install_spy(monkeypatch)
    _call(atlas, spy, repo, "ref", "m", "--ref", "main", "--main-ref", "main")
    _, other = _call(atlas, spy, repo, "ref", "m", "--ref", "main", "--main-ref", repo.head)
    assert other["build_graph"] >= 1


def test_unparsable_result_is_not_cached(
    repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import grimp

    repo = _new_repo(repo_factory, "unparsable")
    real = grimp.build_graph

    def broken(*args: Any, **kwargs: Any) -> Any:
        raise OSError("временный сбой")

    monkeypatch.setattr(grimp, "build_graph", broken)
    bad = atlas(repo, "ref", "n", *_REFS)
    assert "не определено" in bad.out
    monkeypatch.setattr(grimp, "build_graph", real)
    good = atlas(repo, "ref", "n", *_REFS)
    assert "не определено" not in good.out  # сбой не залип в кэше


def test_old_schema_version_recreates_view_cache(repo_factory: RepoFactory, atlas: Any) -> None:
    import sqlite3

    repo = _new_repo(repo_factory, "schema")
    assert atlas(repo, "ref", "m", *_REFS).code == 0
    con = sqlite3.connect(repo.path / "data" / "atlas.sqlite")
    con.execute("DROP TABLE view_cache")
    con.execute(  # форма таблицы промежуточного коммита: колонка fingerprint, версия 3
        "CREATE TABLE view_cache (sha TEXT, main_ref TEXT, fingerprint TEXT, code TEXT, view TEXT, arg TEXT,"
        " body TEXT, PRIMARY KEY (sha, main_ref, fingerprint, code, view, arg))"
    )
    con.execute("PRAGMA user_version = 3")
    con.commit()
    con.close()
    res = atlas(repo, "ref", "m", *_REFS)
    assert res.code == 0, res.err


def test_broken_body_is_a_miss_and_failed_write_does_not_lose_the_view(tmp_path: Path, capsys: Any) -> None:
    from scripts.atlas import store

    con = store.connect(tmp_path / "db.sqlite")
    store.put_view(con, "s", "main", "f", "c", "ref", "m", ["строка"])
    assert store.get_view(con, "s", "main", "f", "c", "ref", "m") == ["строка"]
    for bad in ("{truncated", "[1, 2]", '"abc"'):
        con.execute("UPDATE view_cache SET body = ?", (bad,))
        assert store.get_view(con, "s", "main", "f", "c", "ref", "m") is None
    con.execute("DROP TABLE view_cache")
    store.put_view(con, "s", "main", "f", "c", "ref", "m", ["x"])  # не бросает: кэш — оптимизация
    assert "кэш вида не записан" in capsys.readouterr().err
    con.close()


def test_view_is_cached_under_the_sha_it_was_computed_for(
    repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scripts.atlas import reference

    repo = _new_repo(repo_factory, "race")
    real = reference.modules_for

    def moving(tree: Any) -> Any:  # HEAD уходит вперёд между resolve и build
        repo.write(
            "m/interfaces.py",
            repo.path.joinpath("m/interfaces.py").read_text("utf-8") + "\n\nclass Gamma:\n    '''Г.'''\n",
        )
        repo.commit("gamma")
        return real(tree)

    monkeypatch.setattr(reference, "modules_for", moving)
    old = repo.head
    res = atlas(repo, "ref", "m", "--ref", "main", "--main-ref", "main")
    assert res.code == 0, res.err
    monkeypatch.setattr(reference, "modules_for", real)
    again = atlas(repo, "ref", "m", "--ref", old, "--main-ref", "main")
    assert "Gamma" not in again.out
