"""Приёмочные тесты: повтор переноса временной выгрузки в `codemap.checkout` при сбое `os.rename` (Windows).

Purpose: живой дефект 2026-10-12 (Windows): первый `checkout` новой ревизии упал с `PermissionError: [WinError 5]`
    из `os.rename(<кэш>/.tmp-*, <кэш>/<ключ>)` (свежий каталог на миг держит другой процесс), повторный запуск
    прошёл. Здесь сбой впрыскивается подменой `codemap.os.rename`: поддельная функция бросает исключение на первых
    N вызовах, где имя источника начинается с `.tmp-`, затем зовёт настоящий `os.rename`. Проверяется видимый эффект
    (возвращённый путь, файлы на диске, тип исключения, время), а не число вызовов.
    AC1 кратковременный сбой (1, 2, 3 попытки) -> выгрузка встала, `.tmp-*` не осталось.
    AC2 постоянный `PermissionError` -> `PermissionError` за 3 с, без `.tmp-*`, итогового каталога нет.
    AC3 итоговый каталог уже создал другой процесс -> `checkout` возвращает его (поведение не меняется).
    AC4 `OSError`, не `PermissionError`, итогового нет -> ошибка выходит за 3 с.
Public API: тесты test_*; публичных имён нет.
Stability: lite
"""

from __future__ import annotations

import errno
import os
import shutil
import time
from pathlib import Path
from typing import Any, Callable

import pytest

from scripts.atlas import codemap
from scripts.atlas.tests.conftest import GitRepo, RepoFactory, run_with_deadline
from scripts.atlas.tests.test_cache_1_6e import _new_repo
from scripts.atlas.tree import Tree

__all__: list[str] = []

_ROWS = [{"id": "m", "paths": ["m/"]}]

_PY_FILES = ["m/__init__.py", "m/core.py", "m/interfaces.py"]

_HANG_GUARD_S = 60.0  # страховка от зависания, не проверяемая граница
_BOUND_S = 3.0  # граница из задания; грубая: монотонные часы Windows тикают ~15.6 мс


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


def _tmp_entries(repo: GitRepo) -> list[str]:
    root = _cache(repo)
    return sorted(p.name for p in root.iterdir() if p.name.startswith(".tmp-")) if root.is_dir() else []


def _files(directory: Path) -> list[str]:
    return sorted(p.relative_to(directory).as_posix() for p in directory.rglob("*") if p.is_file())


class _RenameInjector:
    """Поддельный `os.rename`: первые `fail_times` вызовов с источником `.tmp-*` бросают `fail`, затем настоящий."""

    def __init__(self, fail_times: int | None, fail: Callable[[Path, Path], BaseException]) -> None:
        self.fail_times = fail_times  # None — без предела (всегда падает)
        self.fail = fail
        self.failures = 0
        self.first_at: float | None = None  # момент первого сбоя
        self.last_at: float | None = None  # момент последнего сбоя
        self._real = os.rename

    def __call__(self, src: Any, dst: Any, *args: Any, **kwargs: Any) -> Any:
        if Path(src).name.startswith(".tmp-") and (self.fail_times is None or self.failures < self.fail_times):
            self.failures += 1
            now = time.perf_counter()
            if self.first_at is None:
                self.first_at = now
            self.last_at = now
            raise self.fail(Path(src), Path(dst))
        return self._real(src, dst, *args, **kwargs)


def _inject(
    monkeypatch: pytest.MonkeyPatch, fail_times: int | None, fail: Callable[[Path, Path], BaseException]
) -> _RenameInjector:
    injector = _RenameInjector(fail_times, fail)
    monkeypatch.setattr(codemap.os, "rename", injector)
    return injector


def _denied(src: Path, dst: Path) -> BaseException:
    return PermissionError(errno.EACCES, "Access is denied (имитация WinError 5)")


def _call(repo: GitRepo) -> Path:
    return run_with_deadline(lambda: codemap.checkout(Tree(repo.path, "main"), _ROWS), seconds=_HANG_GUARD_S)


def _call_raising(repo: GitRepo) -> tuple[BaseException, float]:
    """Вызвать `checkout`, ждущий исключения; вернуть (исключение, секунд от начала вызова до выхода ошибки)."""
    started = time.perf_counter()
    with pytest.raises(OSError) as info:
        _call(repo)
    return info.value, time.perf_counter() - started


@pytest.mark.parametrize("failures", [1, 2, 3])
def test_transient_permission_error_is_retried_and_checkout_is_complete(
    repo_factory: RepoFactory, monkeypatch: pytest.MonkeyPatch, failures: int
) -> None:
    """AC1: rename падает `PermissionError` на первых 1, 2, 3 попытках, потом проходит."""
    repo = _new_repo(repo_factory, f"transient{failures}")
    injector = _inject(monkeypatch, failures, _denied)
    result = _call(repo)
    assert injector.failures == failures, "сбой не впрыснулся: тест ничего не проверял"
    assert result.parent == _cache(repo)
    assert result.is_dir()
    assert _files(result) == _PY_FILES
    assert _final_entries(repo) == [result.name]
    assert _tmp_entries(repo) == [], "остался временный каталог"


def test_persistent_permission_error_raises_permission_error_within_bound(
    repo_factory: RepoFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC2: rename всегда `PermissionError`, итоговый каталог не появляется — ошибка выходит, не зависает."""
    repo = _new_repo(repo_factory, "persistent")
    injector = _inject(monkeypatch, None, _denied)
    error, _ = _call_raising(repo)
    assert isinstance(error, PermissionError), repr(error)
    assert injector.failures >= 1, "сбой не впрыснулся: тест ничего не проверял"
    assert injector.first_at is not None and injector.last_at is not None
    # окно повторов: от первой неудачной попытки до выхода ошибки (git archive в него не входит)
    assert time.perf_counter() - injector.first_at < _BOUND_S, "повторы длятся дольше 3 с"


def test_persistent_permission_error_leaves_no_tmp_and_no_final(
    repo_factory: RepoFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC2: после постоянного сбоя нет ни `.tmp-*`, ни итогового каталога."""
    repo = _new_repo(repo_factory, "persistent-clean")
    _inject(monkeypatch, None, _denied)
    with pytest.raises(PermissionError):
        _call(repo)
    assert _tmp_entries(repo) == [], "остался временный каталог"
    assert _final_entries(repo) == [], "появился итоговый каталог"


def test_failed_rename_with_final_created_by_other_process_returns_that_final(
    repo_factory: RepoFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC3: rename падает, потому что другой процесс уже поставил целый итоговый каталог — берём его."""
    repo = _new_repo(repo_factory, "other-won")

    def other_process_won(src: Path, dst: Path) -> BaseException:
        shutil.copytree(src, dst)  # другой процесс успел: под итоговым именем целая выгрузка
        return _denied(src, dst)

    _inject(monkeypatch, None, other_process_won)
    result = _call(repo)
    assert result.parent == _cache(repo)
    assert _files(result) == _PY_FILES
    assert _final_entries(repo) == [result.name]
    assert _tmp_entries(repo) == [], "остался временный каталог"


def test_non_permission_oserror_is_raised_within_bound(
    repo_factory: RepoFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC4: rename падает `OSError`, не `PermissionError`, итогового каталога нет — ошибка выходит за 3 с."""
    repo = _new_repo(repo_factory, "other-oserror")
    injector = _inject(monkeypatch, None, lambda src, dst: OSError(errno.EIO, "ошибка ввода-вывода (имитация)"))
    error, _ = _call_raising(repo)
    assert not isinstance(error, PermissionError), repr(error)
    assert error.errno == errno.EIO
    assert injector.first_at is not None
    assert time.perf_counter() - injector.first_at < _BOUND_S, "ошибка вышла позже 3 с"
    assert _tmp_entries(repo) == [], "остался временный каталог"
    assert _final_entries(repo) == [], "появился итоговый каталог"


# Тесты автора (лид, после ревью р.1): закрывают дыры I3/I4 матрицы и проверяют строку в stderr.
_NO_WAIT_S = 0.5  # меньше суммы пауз повтора (1,55 с) с запасом на сетку часов Windows


def test_other_process_won_is_taken_without_waiting(repo_factory: RepoFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    """Итоговый каталог появился с первым сбоем — его берут сразу, без пауз повтора (дыра I3)."""
    repo = _new_repo(repo_factory, "other-won-once")

    def other_process_won_once(src: Path, dst: Path) -> BaseException:
        if not dst.exists():
            shutil.copytree(src, dst)
        return _denied(src, dst)

    injector = _inject(monkeypatch, None, other_process_won_once)
    result = _call(repo)
    assert injector.first_at is not None
    assert time.perf_counter() - injector.first_at < _NO_WAIT_S, "ждал паузы повтора при готовом итоговом каталоге"
    assert _files(result) == _PY_FILES


def test_non_permission_oserror_is_not_retried(repo_factory: RepoFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    """`OSError`, не `PermissionError`, выходит сразу, без пауз повтора (дыра I4)."""
    repo = _new_repo(repo_factory, "oserror-no-retry")
    injector = _inject(monkeypatch, None, lambda src, dst: OSError(errno.EIO, "ошибка ввода-вывода (имитация)"))
    with pytest.raises(OSError):
        _call(repo)
    assert injector.first_at is not None
    assert time.perf_counter() - injector.first_at < _NO_WAIT_S, "повторял не-PermissionError"


def test_retry_is_reported_on_stderr(
    repo_factory: RepoFactory, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Каждый повтор оставляет строку `atlas: rename … retry` в stderr: живой случай виден в выводе."""
    repo = _new_repo(repo_factory, "retry-stderr")
    _inject(monkeypatch, 2, _denied)
    _call(repo)
    lines = [ln for ln in capsys.readouterr().err.splitlines() if ln.startswith("atlas: rename ")]
    assert len(lines) == 2, lines
    assert all("retry in" in ln for ln in lines), lines
