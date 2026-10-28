"""C-70: приёмочные тесты шва ``relaunch`` лаунчера (слепые, написаны до правки).

Что проверяем: ``venv_guard`` / ``run.launch`` / ``frontend/run.launch`` при чужом интерпретаторе
перезапускают приложение через шов ``relaunch(exe, argv) -> int`` и возвращают код выхода
приложения как есть (в том числе ``0``); ``run.default_relaunch`` на Windows ждёт настоящего
ребёнка и отдаёт знаковый код выхода.

Правила харнеса:
  * ``relaunch`` во ВСЕХ вызовах ``launch`` / ``venv_guard`` передаётся явно: значение по
    умолчанию связано при определении функции и ``monkeypatch`` его не меняет; настоящий
    перезапуск (``os.execv`` на POSIX) убил бы pytest.
  * ``git`` подменяется лямбдой ``common_dir_of``; настоящий git не запускается.
  * ``multiprocess_prototype.main`` подменён заглушкой, возвращающей ``42`` и пишущей вызовы
    в ``app_calls``.
  * Всё, что может зависнуть (A4, A4b: настоящий дочерний процесс), идёт в daemon-потоке с
    дедлайном join 20 с.
  * Ожидаемые значения — литералы из спеки.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import threading
import types
from pathlib import Path

import pytest

import multiprocess_prototype.frontend.run as frun
import multiprocess_prototype.run as run

_JOIN_DEADLINE_S = 20.0

# --------------------------------------------------------------------------------------
# харнес
# --------------------------------------------------------------------------------------


def _py_rel() -> Path:
    """Литерал расположения python в venv (не ``run.venv_python``)."""
    if os.name == "nt":
        return Path(".venv") / "Scripts" / "python.exe"
    return Path(".venv") / "bin" / "python"


def _make_venv(root: Path) -> Path:
    """Фейковый venv: пустой файл на месте python."""
    py = root / _py_rel()
    py.parent.mkdir(parents=True, exist_ok=True)
    py.write_bytes(b"")
    return py


class _Execed(Exception):
    """Фейковый ``os.execv`` сработал (настоящий не вызывается никогда)."""


class _RelaunchFake:
    """Фейк шва ``relaunch``: запоминает вызов (позиционные и именованные) и возвращает ``rc``."""

    def __init__(self, rc: int) -> None:
        self.rc = rc
        self.calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def __call__(self, *args: object, **kwargs: object) -> int:
        self.calls.append((args, dict(kwargs)))
        return self.rc


def _relaunch_forbidden(*args: object, **kwargs: object) -> int:
    raise AssertionError(f"relaunch не должен вызываться, получено: {args!r} {kwargs!r}")


def _git_forbidden(_root: Path) -> Path | None:
    raise AssertionError("git (common_dir_of) не должен вызываться")


def _assert_same_path(actual: object, expected: Path) -> None:
    """Абсолютный путь, указывающий на ``expected`` (сравнение через resolve)."""
    assert isinstance(actual, (str, os.PathLike)), f"не путь: {actual!r}"
    assert Path(actual).is_absolute(), f"путь не абсолютный: {actual!r}"
    assert Path(actual).resolve() == expected.resolve()


def _call_with_deadline[T](fn, *args: object) -> T:
    """Вызвать ``fn(*args)`` в daemon-потоке; дедлайн join 20 с; исключение потока пробрасывается."""
    box: dict[str, object] = {}

    def _target() -> None:
        try:
            box["value"] = fn(*args)
        except BaseException as exc:  # noqa: BLE001 - пробрасываем в поток теста
            box["error"] = exc

    th = threading.Thread(target=_target, daemon=True, name="c70-relaunch-call")
    th.start()
    th.join(_JOIN_DEADLINE_S)
    if th.is_alive():
        pytest.fail(f"вызов не завершился за {_JOIN_DEADLINE_S} с (зависание)")
    if "error" in box:
        raise box["error"]  # type: ignore[misc]
    return box["value"]  # type: ignore[return-value]


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch) -> list[tuple[tuple, dict]]:
    """sys.path восстанавливается, sys.argv задан, приложение заменено заглушкой (-> 42)."""
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.setattr(sys, "argv", ["run.py"])

    app_calls: list[tuple[tuple, dict]] = []

    def _fake_main(*args: object, **kwargs: object) -> int:
        app_calls.append((args, kwargs))
        return 42

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
# A1-A3, A6: шов relaunch в venv_guard / launch
# --------------------------------------------------------------------------------------


def test_a1_launch_relaunch_returns_app_code(
    trees: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    _isolate: list[tuple[tuple, dict]],
) -> None:
    wt, main = trees
    venv_py = _make_venv(main)
    monkeypatch.setattr(sys, "argv", ["run.py", "letter_robot_sim", "--headless"])
    fake = _RelaunchFake(7)

    rc = run.launch(project_root=wt, common_dir_of=lambda _: main / ".git", relaunch=fake)

    assert len(fake.calls) == 1, f"relaunch вызван {len(fake.calls)} раз"
    args, kwargs = fake.calls[0]
    assert kwargs == {}, f"relaunch должен вызываться позиционно, получено kwargs={kwargs!r}"
    assert len(args) == 2
    exe, argv = args
    assert exe == str(venv_py)
    assert isinstance(argv, list)
    assert len(argv) == 4
    assert argv[0] == str(venv_py)
    _assert_same_path(argv[1], Path(run.__file__).resolve())
    assert argv[2:] == ["letter_robot_sim", "--headless"]
    assert rc == 7
    assert _isolate == [], "после перезапуска приложение в этом процессе не стартует"


def test_a2_launch_relaunch_zero_is_exit_code(
    trees: tuple[Path, Path],
    _isolate: list[tuple[tuple, dict]],
) -> None:
    wt, main = trees
    _make_venv(main)
    fake = _RelaunchFake(0)

    rc = run.launch(project_root=wt, common_dir_of=lambda _: main / ".git", relaunch=fake)

    assert rc == 0
    assert type(rc) is int
    assert _isolate == [], "код 0 от relaunch не значит «продолжать запуск»"


def test_a2b_venv_guard_zero_is_not_none(trees: tuple[Path, Path]) -> None:
    wt, main = trees
    _make_venv(main)
    fake = _RelaunchFake(0)

    result = run.venv_guard(
        Path(run.__file__),
        project_root=wt,
        common_dir_of=lambda _: main / ".git",
        relaunch=fake,
    )

    assert result is not None
    assert result == 0


def test_a3_frontend_launch_relaunch_returns_app_code(
    trees: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wt, main = trees
    _make_venv(main)
    monkeypatch.delenv("INSPECTOR_PRESENTATION", raising=False)
    fake = _RelaunchFake(5)

    rc = frun.launch(project_root=wt, common_dir_of=lambda _: main / ".git", relaunch=fake)

    assert rc == 5
    assert len(fake.calls) == 1, f"relaunch вызван {len(fake.calls)} раз"
    args, _kwargs = fake.calls[0]
    assert len(args) == 2
    _exe, argv = args
    assert isinstance(argv, list)
    _assert_same_path(argv[1], Path(frun.__file__).resolve())
    assert "INSPECTOR_PRESENTATION" not in os.environ


def test_a6_own_venv_relaunch_not_called(
    trees: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    _isolate: list[tuple[tuple, dict]],
) -> None:
    wt, _main = trees
    own_py = _make_venv(wt)
    monkeypatch.setattr(sys, "executable", str(own_py))

    rc = run.launch(project_root=wt, common_dir_of=_git_forbidden, relaunch=_relaunch_forbidden)

    assert rc == 42
    assert len(_isolate) == 1, f"приложение должно быть запущено один раз, вызовов: {len(_isolate)}"

    guard_result = run.venv_guard(
        Path(run.__file__),
        project_root=wt,
        common_dir_of=_git_forbidden,
        relaunch=_relaunch_forbidden,
    )

    assert guard_result is None


# --------------------------------------------------------------------------------------
# A7: POSIX-ветка default_relaunch (на Windows через подмену os.name)
# --------------------------------------------------------------------------------------


def test_a7_default_relaunch_posix_branch_execs(monkeypatch: pytest.MonkeyPatch) -> None:
    execv_calls: list[tuple[str, list[str]]] = []

    def _fake_execv(path: str, argv: list[str]) -> None:
        execv_calls.append((path, list(argv)))
        raise _Execed(path)

    def _popen_forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError(f"Popen не должен вызываться в POSIX-ветке: {args!r} {kwargs!r}")

    fn = run.default_relaunch  # до подмены os.name: имя берётся обычным путём
    raised: BaseException | None = None
    with monkeypatch.context() as mp:
        mp.setattr(os, "name", "posix")
        mp.setattr(os, "execv", _fake_execv)
        mp.setattr(subprocess, "Popen", _popen_forbidden)
        try:
            fn("X", ["X", "s"])
        except BaseException as exc:  # noqa: BLE001 - разбираем после выхода из контекста
            raised = exc

    assert isinstance(raised, _Execed), f"ожидалось _Execed, получено: {raised!r}"
    assert execv_calls == [("X", ["X", "s"])]


# --------------------------------------------------------------------------------------
# A4, A4b: настоящий дочерний процесс (Windows)
# --------------------------------------------------------------------------------------

_windows_only = pytest.mark.skipif(os.name != "nt", reason="A4/A4b: ветка Popen+wait только на Windows")


@_windows_only
def test_a4_default_relaunch_waits_and_returns_child_code(tmp_path: Path) -> None:
    marker = tmp_path / "done.marker"
    script = tmp_path / "child_exit3.py"
    script.write_text(
        textwrap.dedent(
            f"""
            import sys, time
            time.sleep(0.5)
            with open({str(marker)!r}, "w", encoding="utf-8") as fh:
                fh.write("done")
            sys.exit(3)
            """
        ),
        encoding="utf-8",
    )

    rc = _call_with_deadline(run.default_relaunch, sys.executable, [sys.executable, str(script)])

    assert rc == 3
    assert marker.exists(), "default_relaunch вернул управление до выхода ребёнка"


@_windows_only
def test_a4b_default_relaunch_returns_signed_exit_code(tmp_path: Path) -> None:
    script = tmp_path / "child_exitprocess.py"
    script.write_text(
        textwrap.dedent(
            """
            import ctypes
            ctypes.windll.kernel32.ExitProcess(0xC0000005)
            """
        ),
        encoding="utf-8",
    )

    rc = _call_with_deadline(run.default_relaunch, sys.executable, [sys.executable, str(script)])

    assert rc == -1073741819
