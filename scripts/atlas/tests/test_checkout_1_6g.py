"""Тесты опасных мест выгрузки ревизии на диске: гонка, сбой распаковки, вытеснение (Task 1.6g, тесты автора кода).

Purpose: `codemap.checkout` кладёт выгрузку в `<repo>/data/atlas/checkout/<ключ>` одним `rename`; здесь проверено, что
    два потока с одним ключом получают одну целую выгрузку, сбой распаковки не оставляет ни итогового, ни `.tmp-*`
    каталога, хранится 3 новейших выгрузки, а вытесняемая выгрузка с открытым файлом остаётся целой или исчезает.
Public API: тесты test_*; публичных имён нет.
Stability: lite
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from scripts.atlas import codemap
from scripts.atlas.tests.conftest import GitRepo, RepoFactory, run_with_deadline
from scripts.atlas.tests.test_cache_1_6e import _install_spy, _new_repo
from scripts.atlas.tree import AtlasError, Tree

__all__: list[str] = []

_ROWS = [{"id": "m", "paths": ["m/"]}]


@pytest.fixture(autouse=True)
def _fresh_memory():
    codemap.forget()
    yield
    codemap.forget()


def _cache(repo: GitRepo) -> Path:
    return repo.path / "data" / "atlas" / "checkout"


def _final_entries(repo: GitRepo) -> list[str]:
    root = _cache(repo)
    return sorted(p.name for p in root.iterdir() if not p.name.startswith(".")) if root.is_dir() else []


def _all_entries(repo: GitRepo) -> list[str]:
    root = _cache(repo)
    return sorted(p.name for p in root.iterdir()) if root.is_dir() else []


def _files(directory: Path) -> list[str]:
    return sorted(p.relative_to(directory).as_posix() for p in directory.rglob("*") if p.is_file())


def _revisions(repo: GitRepo, count: int) -> list[str]:
    shas = [repo.head]
    for i in range(count - 1):
        repo.write("m/core.py", f'"""Реализация."""\n\n\ndef helper(x: int) -> int:\n    return x + {i + 2}\n')
        shas.append(repo.commit(f"edit {i}"))
    return shas


def test_two_threads_same_key_get_one_complete_checkout(repo_factory: RepoFactory) -> None:
    repo = _new_repo(repo_factory, "race")
    barrier = threading.Barrier(2)
    results: list[Path] = []
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            barrier.wait(timeout=30)
            results.append(codemap.checkout(Tree(repo.path, "main"), _ROWS))
        except BaseException as exc:  # noqa: BLE001 - собрать и показать в основном потоке
            errors.append(exc)

    def both() -> None:
        threads = [threading.Thread(target=worker, daemon=True) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(60)
        assert not any(t.is_alive() for t in threads), "поток checkout завис"

    run_with_deadline(both, seconds=120)
    assert errors == [], errors
    assert len(results) == 2
    assert results[0] == results[1]
    assert _files(results[0]) == ["m/__init__.py", "m/core.py", "m/interfaces.py"]
    assert len(_final_entries(repo)) == 1
    assert _all_entries(repo) == _final_entries(repo), "остался временный каталог"


@pytest.mark.parametrize("mode", ["tar-raises", "tarfile-raises"])
def test_failed_unpack_leaves_no_final_and_no_tmp_directory(
    repo_factory: RepoFactory, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    repo = _new_repo(repo_factory, mode)
    real_run = subprocess.run

    def boom_tarfile(*args: Any, **kwargs: Any) -> Any:
        raise OSError("tarfile упал на распаковке")

    def run(cmd: Any, *args: Any, **kwargs: Any) -> Any:
        if mode == "tar-raises" and isinstance(cmd, list) and cmd[0] != "git":
            partial = Path(kwargs["cwd"]) / "m"  # tar успел распаковать часть и упал
            partial.mkdir()
            (partial / "interfaces.py").write_text("часть", encoding="utf-8")
            raise OSError("tar упал на распаковке")
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(tarfile, "open", boom_tarfile)
    if mode == "tarfile-raises":
        monkeypatch.setattr(codemap.shutil, "which", lambda name: None)
    with pytest.raises(OSError):
        run_with_deadline(lambda: codemap.checkout(Tree(repo.path, "main"), _ROWS), seconds=120)
    assert _all_entries(repo) == [], "после сбоя остался каталог"


def test_four_revisions_keep_three_newest(repo_factory: RepoFactory) -> None:
    repo = _new_repo(repo_factory, "four")
    shas = _revisions(repo, 4)
    paths = [codemap.checkout(Tree(repo.path, sha), _ROWS) for sha in shas]
    assert len({p.name for p in paths}) == 4
    kept = _final_entries(repo)
    assert len(kept) == 3
    assert paths[3].name in kept, "текущая выгрузка вытеснена"
    assert paths[0].name not in kept, "самая старая не вытеснена"
    assert _all_entries(repo) == kept, "остался .tmp-/.del- каталог"


def test_pruned_checkout_with_open_file_is_whole_or_gone(repo_factory: RepoFactory) -> None:
    repo = _new_repo(repo_factory, "held")
    shas = _revisions(repo, 4)
    oldest = codemap.checkout(Tree(repo.path, shas[0]), _ROWS)
    before = _files(oldest)
    assert before == ["m/__init__.py", "m/core.py", "m/interfaces.py"]
    with (oldest / "m" / "core.py").open("rb"):  # Windows: переименовать каталог с открытым файлом нельзя
        for sha in shas[1:]:
            codemap.checkout(Tree(repo.path, sha), _ROWS)
        if oldest.exists():
            assert _files(oldest) == before, "выгрузка под итоговым именем осталась неполной"
    if oldest.exists():  # закрыли файл: следующий вызов вытесняет её окончательно или оставляет целой
        assert _files(oldest) == before


def _empty(base: Path) -> None:
    """Каталог остаётся, содержимое стёрто: как после сбоя диска."""
    for child in base.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
    assert list(base.iterdir()) == []


def test_code_of_empty_checkout_with_roots_raises(
    repo_factory: RepoFactory, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repo = _new_repo(repo_factory, "empty")
    empty = tmp_path / "empty_checkout"
    empty.mkdir()
    monkeypatch.setattr(codemap, "checkout", lambda tree, rows: empty)  # защита `code_of` отдельно от защиты `checkout`
    with pytest.raises(AtlasError, match="empty checkout"):
        run_with_deadline(lambda: codemap.code_of(Tree(repo.path, "main"), _ROWS), seconds=120)


def test_unpack_producing_nothing_raises_and_leaves_no_entry(
    repo_factory: RepoFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _new_repo(repo_factory, "nothing")
    monkeypatch.setattr(codemap, "_unpack", lambda data, target: None)
    with pytest.raises(AtlasError, match="empty checkout"):
        run_with_deadline(lambda: codemap.checkout(Tree(repo.path, "main"), _ROWS), seconds=120)
    assert _all_entries(repo) == []


def test_empty_directory_under_final_name_is_a_miss(repo_factory: RepoFactory) -> None:
    repo = _new_repo(repo_factory, "hollow")
    base = codemap.checkout(Tree(repo.path, "main"), _ROWS)
    _empty(base)
    again = run_with_deadline(lambda: codemap.checkout(Tree(repo.path, "main"), _ROWS), seconds=120)
    assert again == base
    assert _files(again) == ["m/__init__.py", "m/core.py", "m/interfaces.py"]
    assert _all_entries(repo) == [base.name]


def _deep(base: Path, length: int) -> Path:
    """Несозданный путь ровно `length` знаков под `base`."""
    pad = length - len(str(base)) - 1
    if pad < 1:
        pytest.skip("tmp_path слишком длинный для подгонки")
    return base / ("p" * pad)


@pytest.mark.skipif(sys.platform != "win32", reason="предел MAX_PATH только в Windows")
def test_too_long_primary_falls_back_to_short_temp_root(
    repo_factory: RepoFactory, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repo = _new_repo(repo_factory, "long")
    deep = _deep(tmp_path, 250)  # 250 + ключ + файл выходят за 259
    short_temp = tmp_path / "t"
    short_temp.mkdir()
    monkeypatch.setattr(codemap, "CHECKOUT_DIR", deep)
    monkeypatch.setattr(codemap, "_long_paths_enabled", lambda: False)
    monkeypatch.setattr(tempfile, "tempdir", str(short_temp))
    base = run_with_deadline(lambda: codemap.checkout(Tree(repo.path, "main"), _ROWS), seconds=120)
    assert short_temp / "atlas-checkout" in base.parents
    assert (base / "m" / "interfaces.py").is_file()
    assert not deep.exists(), "под слишком длинным основным путём что-то создано"
    ino = base.stat().st_ino
    codemap.forget()
    spy = _install_spy(monkeypatch)
    again = run_with_deadline(lambda: codemap.checkout(Tree(repo.path, "main"), _ROWS), seconds=120)
    assert again == base
    assert spy.archive == 0, "второй вызов распаковал ревизию заново"
    assert again.stat().st_ino == ino


@pytest.mark.skipif(sys.platform != "win32", reason="предел MAX_PATH только в Windows")
def test_too_long_primary_and_short_root_raise_and_leave_nothing(
    repo_factory: RepoFactory, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repo = _new_repo(repo_factory, "longlong")
    deep, deep_temp = _deep(tmp_path, 250), tmp_path / ("q" * 240)
    monkeypatch.setattr(codemap, "CHECKOUT_DIR", deep)
    monkeypatch.setattr(codemap, "_long_paths_enabled", lambda: False)
    monkeypatch.setattr(tempfile, "tempdir", str(deep_temp))
    with pytest.raises(AtlasError, match="path too long"):
        run_with_deadline(lambda: codemap.checkout(Tree(repo.path, "main"), _ROWS), seconds=120)
    assert not deep.exists()
    assert not deep_temp.exists()


def test_stale_temp_entries_are_removed_and_fresh_ones_kept(repo_factory: RepoFactory) -> None:
    repo = _new_repo(repo_factory, "stale")
    cache = _cache(repo)
    cache.mkdir(parents=True)
    for name in (".tmp-fresh-x", ".tmp-old-x", ".del-y"):
        (cache / name).mkdir()
        (cache / name / "f.py").write_text("x = 1", encoding="utf-8")
    past = time.time() - 7200
    for name in (".tmp-old-x", ".del-y"):
        os.utime(cache / name, (past, past))
    run_with_deadline(lambda: codemap.checkout(Tree(repo.path, "main"), _ROWS), seconds=120)
    assert (cache / ".tmp-fresh-x").is_dir(), "свежий .tmp-* (чужой процесс ещё распаковывает) удалён"
    assert not (cache / ".tmp-old-x").exists()
    assert not (cache / ".del-y").exists()


def test_code_memory_holds_three_revisions_only(repo_factory: RepoFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _new_repo(repo_factory, "memory")
    shas = _revisions(repo, 4)
    spy = _install_spy(monkeypatch)

    def users(sha: str) -> None:
        codemap.code_of(Tree(repo.path, sha), _ROWS).module_users("m")  # строит граф grimp

    for sha in shas:
        users(sha)
    assert spy.build_graph == 4
    spy.reset()
    users(shas[3])
    assert spy.build_graph == 0, "новейшая ревизия должна быть в памяти"
    users(shas[0])
    assert spy.build_graph == 1, "самая старая вытеснена из памяти: граф строится заново"


def test_code_memo_key_includes_rows(repo_factory: RepoFactory) -> None:
    repo = _new_repo(repo_factory, "memo")
    tree = Tree(repo.path, "main")
    rows_b = [*_ROWS, {"id": "m2", "paths": ["m/"]}]  # те же корни -> тот же каталог, другие строки
    first = codemap.code_of(tree, _ROWS)
    other = codemap.code_of(tree, rows_b)
    assert first.base == other.base
    assert first is not other
    assert codemap.code_of(tree, _ROWS) is first


def test_hit_refreshes_recency(repo_factory: RepoFactory) -> None:
    repo = _new_repo(repo_factory, "recency")
    shas = _revisions(repo, 4)
    paths = [codemap.checkout(Tree(repo.path, sha), _ROWS) for sha in shas[:3]]
    now = time.time()
    for age, path in zip((300, 200, 100), paths):  # явный порядок: r0 самая старая
        os.utime(path, (now - age, now - age))
    assert codemap.checkout(Tree(repo.path, shas[0]), _ROWS) == paths[0]  # попадание: обязано обновить давность
    last = codemap.checkout(Tree(repo.path, shas[3]), _ROWS)
    assert sorted(_final_entries(repo)) == sorted([paths[0].name, paths[2].name, last.name])
