"""C-55a: приёмочные тесты venv-guard входов прототипа (слепые, написаны до правки).

Что проверяем: ``multiprocess_prototype/run.py`` и ``multiprocess_prototype/frontend/run.py``
в дереве без своего ``.venv`` берут ``.venv`` основной копии (git common dir); реализация
guard'а одна.

Правила харнеса:
  * ``execv`` во ВСЕХ вызовах ``launch`` передаётся явно фейком: значение по умолчанию связано
    с ``os.execv`` при определении функции, ``monkeypatch.setattr(os, "execv", ...)`` его не
    меняет, а настоящий ``os.execv`` на Windows запускает приложение и убивает pytest.
  * ``git`` подменяется лямбдой ``common_dir_of``; настоящий git не запускается (на этой машине
    выше tmp-каталогов лежит чужой репозиторий, поэтому «нет репозитория выше» не годится).
  * Модуль ``multiprocess_prototype.main`` подменён заглушкой: путь, дошедший до приложения,
    не стартует его.
"""

from __future__ import annotations

import os
import sys
import types
from collections.abc import Callable
from pathlib import Path

import pytest

import multiprocess_prototype.frontend.run as frun
import multiprocess_prototype.run as run

# --------------------------------------------------------------------------------------
# харнес
# --------------------------------------------------------------------------------------


def _py_rel() -> Path:
    """Литерал расположения python в venv (не ``run.venv_python``)."""
    if os.name == "nt":
        return Path(".venv") / "Scripts" / "python.exe"
    return Path(".venv") / "bin" / "python"


def _py_path(root: Path) -> Path:
    """Где python venv лежит (или лёг бы) в дереве ``root``."""
    return root / _py_rel()


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


def _call_expecting_exec(spy: _ExecvSpy, fn: Callable[..., object], **kwargs: object) -> None:
    """Вызвать ``fn`` с фейковым execv; сработавший фейк — норма."""
    try:
        fn(execv=spy, **kwargs)
    except _Execed:
        pass


def _assert_same_path(actual: object, expected: Path) -> None:
    """Абсолютный путь, указывающий на ``expected`` (сравнение через resolve)."""
    assert isinstance(actual, (str, os.PathLike)), f"не путь: {actual!r}"
    assert Path(actual).is_absolute(), f"путь не абсолютный: {actual!r}"
    assert Path(actual).resolve() == expected.resolve()


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch) -> list[tuple[tuple, dict]]:
    """sys.path восстанавливается, sys.argv задан, приложение заменено заглушкой."""
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.setattr(sys, "argv", ["run.py"])

    app_calls: list[tuple[tuple, dict]] = []

    def _fake_main(*args: object, **kwargs: object) -> int:
        app_calls.append((args, kwargs))
        return 0

    stub = types.ModuleType("multiprocess_prototype.main")
    stub.main = _fake_main  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "multiprocess_prototype.main", stub)
    return app_calls


@pytest.fixture
def trees(tmp_path: Path) -> tuple[Path, Path]:
    """Корни связанного worktree и основной копии (оба — resolve от tmp_path)."""
    base = tmp_path.resolve()
    wt = base / "wt"
    main = base / "main"
    wt.mkdir()
    main.mkdir()
    return wt, main


# --------------------------------------------------------------------------------------
# V1-V4: resolve_venv_python(project_root, main_root) -> (python | None, [кандидаты])
# --------------------------------------------------------------------------------------


def test_v1_own_venv_wins(trees: tuple[Path, Path]) -> None:
    wt, main = trees
    wt_py = _make_venv(wt)
    _make_venv(main)

    found, candidates = run.resolve_venv_python(wt, main)

    _assert_same_path(found, wt_py)
    assert [Path(c).resolve() for c in candidates] == [wt_py.resolve()]


def test_v2_main_copy_venv_when_no_own(trees: tuple[Path, Path]) -> None:
    wt, main = trees
    main_py = _make_venv(main)

    found, candidates = run.resolve_venv_python(wt, main)

    _assert_same_path(found, main_py)
    assert [Path(c).resolve() for c in candidates] == [
        _py_path(wt).resolve(),
        main_py.resolve(),
    ]


def test_v3_none_tries_both(trees: tuple[Path, Path]) -> None:
    wt, main = trees

    found, candidates = run.resolve_venv_python(wt, main)

    assert found is None
    assert [Path(c).resolve() for c in candidates] == [
        _py_path(wt).resolve(),
        _py_path(main).resolve(),
    ]


def test_v4_no_duplicate_candidate(trees: tuple[Path, Path]) -> None:
    wt, _main = trees

    # основная копия не определена
    found_none, candidates_none = run.resolve_venv_python(wt, None)
    assert found_none is None
    assert [Path(c).resolve() for c in candidates_none] == [_py_path(wt).resolve()]

    # основная копия — это само дерево: дубля кандидата нет
    found_same, candidates_same = run.resolve_venv_python(wt, wt)
    assert found_same is None
    assert [Path(c).resolve() for c in candidates_same] == [_py_path(wt).resolve()]


# --------------------------------------------------------------------------------------
# L1-L5: run.launch(project_root=, common_dir_of=, execv=)
# --------------------------------------------------------------------------------------


def test_l1_worktree_no_venv_no_uv_sync_hint(
    trees: tuple[Path, Path],
    capsys: pytest.CaptureFixture[str],
    _isolate: list[tuple[tuple, dict]],
) -> None:
    wt, main = trees

    rc = run.launch(project_root=wt, common_dir_of=lambda _: main / ".git", execv=_execv_forbidden)

    err = capsys.readouterr().err
    assert rc == 1
    assert str(_py_path(wt)) in err
    assert str(_py_path(main)) in err
    assert "uv sync" not in err
    assert _isolate == [], "приложение не должно стартовать без venv"


def test_l2_reexec_into_main_copy_venv(
    trees: tuple[Path, Path],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wt, main = trees
    main_py = _make_venv(main)
    monkeypatch.setattr(sys, "argv", ["run.py", "letter_robot_sim", "--headless"])
    spy = _ExecvSpy()

    _call_expecting_exec(spy, run.launch, project_root=wt, common_dir_of=lambda _: main / ".git")

    assert len(spy.calls) == 1, f"execv вызван {len(spy.calls)} раз"
    path, argv = spy.calls[0]
    _assert_same_path(path, main_py)
    assert len(argv) == 4
    assert argv[0] == path
    _assert_same_path(argv[1], Path(run.__file__).resolve())
    assert argv[2:] == ["letter_robot_sim", "--headless"]
    err = capsys.readouterr().err
    assert "venv основной копии" in err
    assert str(main) in err


def test_l3_git_unknown_reports_main_copy_undetermined(
    trees: tuple[Path, Path],
    capsys: pytest.CaptureFixture[str],
    _isolate: list[tuple[tuple, dict]],
) -> None:
    wt, _main = trees

    rc = run.launch(project_root=wt, common_dir_of=lambda _: None, execv=_execv_forbidden)

    err = capsys.readouterr().err
    assert rc == 1
    assert str(_py_path(wt)) in err
    assert "основная копия не определена" in err
    assert "uv sync" not in err
    assert _isolate == []


def test_l4_own_venv_skips_git(trees: tuple[Path, Path]) -> None:
    wt, _main = trees
    wt_py = _make_venv(wt)
    spy = _ExecvSpy()

    def _git_must_not_run(_root: Path) -> Path | None:
        raise AssertionError("git не должен вызываться")

    _call_expecting_exec(spy, run.launch, project_root=wt, common_dir_of=_git_must_not_run)

    assert len(spy.calls) == 1, f"execv вызван {len(spy.calls)} раз"
    path, argv = spy.calls[0]
    _assert_same_path(path, wt_py)
    assert argv[0] == path


def test_l5_main_copy_without_venv_keeps_uv_sync_hint(
    trees: tuple[Path, Path],
    capsys: pytest.CaptureFixture[str],
    _isolate: list[tuple[tuple, dict]],
) -> None:
    wt, _main = trees

    rc = run.launch(project_root=wt, common_dir_of=lambda _: wt / ".git", execv=_execv_forbidden)

    err = capsys.readouterr().err
    assert rc == 1
    assert "uv sync" in err
    assert _isolate == []


# --------------------------------------------------------------------------------------
# F1: frontend/run.py использует ту же реализацию
# --------------------------------------------------------------------------------------


def test_f1_frontend_uses_shared_guard(trees: tuple[Path, Path]) -> None:
    assert frun.venv_guard is run.venv_guard, "в frontend/run.py не должно быть второй реализации guard"

    wt, main = trees
    main_py = _make_venv(main)
    spy = _ExecvSpy()

    _call_expecting_exec(spy, frun.launch, project_root=wt, common_dir_of=lambda _: main / ".git")

    assert len(spy.calls) == 1, f"execv вызван {len(spy.calls)} раз"
    path, argv = spy.calls[0]
    _assert_same_path(path, main_py)
    assert len(argv) == 2
    assert argv[0] == path
    _assert_same_path(argv[1], Path(frun.__file__).resolve())
