"""Тесты опасных мест выгрузки ревизии на диске: гонка, сбой распаковки, вытеснение (Task 1.6g, тесты автора кода).

Purpose: `codemap.checkout` кладёт выгрузку в `<repo>/data/atlas/checkout/<ключ>` одним `rename`; здесь проверено, что
    два потока с одним ключом получают одну целую выгрузку, сбой распаковки не оставляет ни итогового, ни `.tmp-*`
    каталога, хранится 3 новейших выгрузки, а вытесняемая выгрузка с открытым файлом остаётся целой или исчезает.
Public API: тесты test_*; публичных имён нет.
Stability: lite
"""

from __future__ import annotations

import subprocess
import tarfile
import threading
from pathlib import Path
from typing import Any

import pytest

from scripts.atlas import codemap
from scripts.atlas.tests.conftest import GitRepo, RepoFactory, run_with_deadline
from scripts.atlas.tests.test_cache_1_6e import _new_repo
from scripts.atlas.tree import Tree

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
