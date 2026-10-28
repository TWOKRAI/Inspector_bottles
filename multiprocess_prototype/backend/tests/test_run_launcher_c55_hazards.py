"""C-55a: сторожа разработчика к venv-guard входов прототипа (Н1-Н7).

Приёмочные тесты тестера (``test_run_launcher_c55.py``) гоняют guard на подменённом git.
Здесь — то, что подмена скрывает: зацикливание re-exec, настоящий git (в том числе вне
репозитория и без git), сбои ``subprocess.run`` и бутстрап ``frontend/run.py`` под
изолированным python.

Правила харнеса те же: seam ``relaunch`` во ВСЕХ вызовах ``launch`` передаётся явно фейком
(значение по умолчанию — ``run.default_relaunch``, связано при определении функции; настоящий
``run.default_relaunch`` на Windows ждёт дочерний процесс вместо ``os.execv`` и без фейка
запустит настоящее приложение и будет ждать его — pytest зависнет); приложение подменено
заглушкой.
"""

from __future__ import annotations

import os
import subprocess
import sys
import types
from pathlib import Path

import pytest

import multiprocess_prototype.frontend.run as frun
import multiprocess_prototype.run as run

# --------------------------------------------------------------------------------------
# харнес
# --------------------------------------------------------------------------------------


def _py_path(root: Path) -> Path:
    """Где python venv лежит (или лёг бы) в дереве ``root`` — литерал, не ``run.venv_python``."""
    if os.name == "nt":
        return root / ".venv" / "Scripts" / "python.exe"
    return root / ".venv" / "bin" / "python"


def _make_venv(root: Path) -> Path:
    """Фейковый venv: пустой файл на месте python."""
    py = _py_path(root)
    py.parent.mkdir(parents=True, exist_ok=True)
    py.write_bytes(b"")
    return py


class _Execed(Exception):
    """Фейковый ``execv`` сработал (настоящий не вызывается никогда)."""


class _ExecvSpy:
    """Фейк ``execv``: запоминает аргументы и бросает ``_Execed``."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str]]] = []

    def __call__(self, path: str, argv: list[str]) -> None:
        self.calls.append((path, list(argv)))
        raise _Execed(path)


def _execv_forbidden(*args: object, **kwargs: object) -> None:
    raise AssertionError(f"execv не должен вызываться, получено: {args!r} {kwargs!r}")


def _git(cwd: Path, *args: str) -> None:
    """Настоящий git в ``cwd`` (всегда ``tmp_path`` теста — не репозиторий проекта)."""
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True, timeout=60)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch) -> None:
    """sys.path восстанавливается, sys.argv задан, приложение заменено заглушкой."""
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.setattr(sys, "argv", ["run.py"])

    stub = types.ModuleType("multiprocess_prototype.main")
    stub.main = lambda *a, **k: 0  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "multiprocess_prototype.main", stub)


@pytest.fixture
def repo_root() -> Path:
    """Корень дерева, чей код исполняется в тесте (worktree или основная копия)."""
    return Path(run.__file__).resolve().parent.parent


# --------------------------------------------------------------------------------------
# Н1: нет зацикливания re-exec
# --------------------------------------------------------------------------------------


def test_h1_no_reexec_loop_when_already_in_main_venv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Процесс уже запущен python основной копии: повторный re-exec не нужен."""
    wt = tmp_path.resolve() / "wt"
    main = tmp_path.resolve() / "main"
    wt.mkdir()
    main.mkdir()
    main_py = _make_venv(main)
    monkeypatch.setattr(sys, "executable", str(main_py))

    rc = run.launch(project_root=wt, common_dir_of=lambda _: main / ".git", relaunch=_execv_forbidden)

    assert rc == 0


# --------------------------------------------------------------------------------------
# Н2-Н5: git_common_dir
# --------------------------------------------------------------------------------------


def test_h2_real_git_in_this_tree(repo_root: Path) -> None:
    common = run.git_common_dir(repo_root)

    assert common is not None
    assert common.name == ".git"
    assert common.is_dir()


def test_h3_outside_repo_with_outer_repo_above(tmp_path: Path) -> None:
    """Каталог без своего ``.git`` внутри чужого репозитория: git выше потолка не ищем."""
    outer = tmp_path / "outer"
    proj = outer / "proj"
    proj.mkdir(parents=True)
    _git(tmp_path, "init", "outer")

    assert run.git_common_dir(proj) is None


def test_h4_no_git_on_path(tmp_path: Path, repo_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))

    assert run.git_common_dir(repo_root) is None


def _completed(returncode: int, stdout: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=["git"], returncode=returncode, stdout=stdout, stderr="")


def test_h5_timeout_is_none(repo_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def _hang(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(cmd="git", timeout=5)

    monkeypatch.setattr(run.subprocess, "run", _hang)

    assert run.git_common_dir(repo_root) is None


@pytest.mark.parametrize(
    ("returncode", "stdout"),
    [
        pytest.param(128, "", id="not-a-repo-128"),
        pytest.param(129, "", id="old-git-unknown-option-129"),
        pytest.param(0, "", id="empty-output"),
    ],
)
def test_h5_failed_git_is_none(repo_root: Path, monkeypatch: pytest.MonkeyPatch, returncode: int, stdout: str) -> None:
    monkeypatch.setattr(run.subprocess, "run", lambda *a, **k: _completed(returncode, stdout))

    assert run.git_common_dir(repo_root) is None


def test_h8_git_env_does_not_leak(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``GIT_DIR`` из окружения (git hook, ``rebase --exec``) не должен перебивать cwd."""
    tmp = tmp_path.resolve()
    _git(tmp, "init", "a")
    _git(tmp, "init", "b")
    monkeypatch.setenv("GIT_DIR", str(tmp / "b" / ".git"))

    common = run.git_common_dir(tmp / "a")

    assert common is not None
    assert common.resolve() == (tmp / "a" / ".git").resolve()


# --------------------------------------------------------------------------------------
# Н6: настоящие объекты — git worktree без common_dir_of
# --------------------------------------------------------------------------------------


def test_h6_real_worktree_reexecs_into_main_venv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        monkeypatch.delenv(name, raising=False)
    tmp = tmp_path.resolve()
    _git(tmp, "init", "main")
    _git(
        tmp,
        "-C",
        "main",
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@t",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "--allow-empty",
        "-m",
        "init",
    )
    _git(tmp, "-C", "main", "worktree", "add", "--detach", "../wt")
    main_py = _make_venv(tmp / "main")
    spy = _ExecvSpy()

    with pytest.raises(_Execed):
        run.launch(project_root=tmp / "wt", relaunch=spy)

    assert len(spy.calls) == 1
    assert Path(spy.calls[0][0]).resolve() == main_py.resolve()


# --------------------------------------------------------------------------------------
# Н7: бутстрап frontend/run.py под изолированным python
# --------------------------------------------------------------------------------------


def test_h7_frontend_bootstrap_under_isolated_python(tmp_path: Path) -> None:
    """``-I`` отбрасывает PYTHONPATH: без бутстрапа импорт ``multiprocess_prototype`` не пройдёт.

    ``run_name='probe'`` — блок ``__main__`` не исполняется, приложение не стартует.
    """
    code = f"import runpy; runpy.run_path({frun.__file__!r}, run_name='probe')"

    result = subprocess.run(
        [sys.executable, "-I", "-c", code],
        cwd=tmp_path,
        capture_output=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
