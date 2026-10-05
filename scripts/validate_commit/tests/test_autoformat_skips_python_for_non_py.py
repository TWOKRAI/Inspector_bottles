"""Task 1.5 (commit-mechanism) — слепая приёмка: `autoformat-python.sh` уходит до запуска Python на не-.py.

Контракт (из ТЗ `plans/2026-10-03_commit-mechanism/tasks/1.5.md`, ред. 2, не из реализации):
  * первое действие хука — прочитать вход и проверить, что в сыром JSON есть подстрока `.py"`;
    нет её — `exit 0` ДО поиска интерпретатора и ДО встроенного Python (Python на каждой правке `.md`
    стоил ~0,3 с);
  * ложный проход (`.py"` где-то ещё во входе, например в `new_string`) безвреден: дальше полная
    проверка в Python, файл `.md` не форматируется;
  * на `.py` поведение прежнее: ruff доходит до файла.

Наблюдаемое: подменный интерпретатор через `CLAUDE_PYTHON_BIN` — исполняемый скрипт, который дописывает
строку в файл-счётчик и передаёт вызов настоящему Python (`sys.executable`). Число строк счётчика =
число запусков интерпретатора хуком. Времени тесты не меряют.

Тесты:
  1  Write `notes.md` -> 0 запусков, rc 0, stdout пуст (до реализации красный);
  2  Edit `notes.md`, сырой вход содержит `x.py"` -> >= 1 запуска (ложный проход), `.md` не изменён, rc 0;
  3  Write `mod.py` с неформатированным кодом -> >= 1 запуска и файл отформатирован (`x = 1`), rc 0.

Замечание про тест 2: `json.dumps` экранирует кавычку внутри строки (`x.py\\"`), так что подстрока `.py"`
в сыром JSON появляется только там, где строка ЗАКАНЧИВАЕТСЯ на `.py`. Поэтому `new_string` кончается
на `x.py`; предусловие теста проверяет сырой вход.

Запуск хука: Git Bash (не WSL), хук по абсолютному пути из проверяемого дерева, вход — JSON на stdin,
cwd и `CLAUDE_PROJECT_DIR` = временный репо; все файлы, которые хук может форматировать, лежат во
временном каталоге. Вывод процессов — во временные файлы, `timeout=120`.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
AUTOFORMAT_HOOK = REPO_ROOT / ".claude" / "plugins" / "lang-python" / "hooks" / "autoformat-python.sh"

TIMEOUT = 120
IS_WINDOWS = sys.platform == "win32"


# --------------------------------------------------------------------------- process helpers


def _clean_env() -> dict[str, str]:
    env = {
        k: v for k, v in os.environ.items() if not k.startswith("GIT_") and k not in ("PRE_COMMIT", "CLAUDE_PYTHON_BIN")
    }
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _run_raw(
    cmd: list[str],
    cwd: Path,
    env: dict[str, str],
    stdin_data: bytes | None = None,
) -> tuple[int, bytes, bytes]:
    """Запуск с выводом во временные файлы (не pipe): таймаут не виснет на внуках."""
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err, tempfile.TemporaryFile() as inp:
        if stdin_data is not None:
            inp.write(stdin_data)
            inp.seek(0)
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            env=env,
            stdin=inp if stdin_data is not None else subprocess.DEVNULL,
            stdout=out,
            stderr=err,
            timeout=TIMEOUT,
            check=False,
        )
        out.seek(0)
        err.seek(0)
        return proc.returncode, out.read(), err.read()


def _git_ok(repo: Path, *args: str) -> None:
    rc, out, err = _run_raw(["git", *args], repo, _clean_env())
    assert rc == 0, f"git {' '.join(args)} rc={rc}\n{out!r}\n{err!r}"


def _find_git_bash() -> str:
    """`bash` из PATH, но не WSL-заглушка (System32 / WindowsApps)."""
    candidates: list[str] = []
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        for name in ("bash.exe", "bash"):
            candidate = Path(directory) / name
            if directory and candidate.is_file():
                candidates.append(str(candidate))
    for candidate in candidates:
        low = candidate.lower().replace("/", "\\")
        if "\\windows\\system32\\" in low or "\\windowsapps\\" in low:
            continue
        return candidate
    pytest.fail(f"no Git Bash on PATH (only WSL/none): {candidates}")


def _init_repo(path: Path) -> Path:
    """`git init -b main` явно (pytest tmp может лежать внутри чужого репозитория)."""
    path.mkdir(parents=True, exist_ok=True)
    _git_ok(path, "init", "-q", "-b", "main")
    _git_ok(path, "config", "user.name", "Tester")
    _git_ok(path, "config", "user.email", "tester@example.invalid")
    _git_ok(path, "config", "core.autocrlf", "false")
    _git_ok(path, "config", "commit.gpgsign", "false")
    return path


# --------------------------------------------------------------------------- fake interpreter


def _make_counting_python(directory: Path) -> tuple[Path, Path]:
    """Скрипт-обёртка: дописывает строку в счётчик и исполняет настоящий Python со всеми аргументами."""
    directory.mkdir(parents=True, exist_ok=True)
    counter = directory / "python-launches.txt"
    wrapper = directory / "countpy"
    wrapper.write_bytes(
        (
            "#!/usr/bin/env bash\n"
            f'echo launched >> "{counter.as_posix()}"\n'
            f'exec "{Path(sys.executable).as_posix()}" "$@"\n'
        ).encode("utf-8")
    )
    wrapper.chmod(0o755)
    return wrapper, counter


def _launches(counter: Path) -> int:
    if not counter.exists():
        return 0
    return len(counter.read_text(encoding="utf-8").splitlines())


def _run_hook(repo: Path, payload: dict, wrapper: Path) -> tuple[int, str, str, bytes]:
    raw = json.dumps(payload).encode("utf-8")
    env = _clean_env()
    env["PATH"] = os.pathsep.join([str(Path(sys.executable).parent), env.get("PATH", "")])
    env["CLAUDE_PROJECT_DIR"] = str(repo)
    env["CLAUDE_PYTHON_BIN"] = wrapper.as_posix()
    rc, out, err = _run_raw([_find_git_bash(), str(AUTOFORMAT_HOOK)], repo, env, stdin_data=raw)
    return rc, out.decode("utf-8", "replace"), err.decode("utf-8", "replace"), raw


@pytest.fixture
def counting_python(tmp_path: Path) -> tuple[Path, Path]:
    wrapper, counter = _make_counting_python(tmp_path / "fakebin")
    return wrapper, counter


# --------------------------------------------------------------------------- 1: .md -> no Python at all


def test_autoformat_does_not_launch_python_for_md_write(tmp_path: Path, counting_python: tuple[Path, Path]) -> None:
    wrapper, counter = counting_python
    repo = _init_repo(tmp_path / "repo")
    target = repo / "notes.md"
    target.write_bytes(b"# notes  \n")

    rc, out, err, raw = _run_hook(
        repo, {"tool_name": "Write", "tool_input": {"file_path": str(target), "content": "# notes  \n"}}, wrapper
    )

    assert b'.py"' not in raw, f"fixture is not a non-.py payload: {raw!r}"
    assert _launches(counter) == 0, f"Python was launched {_launches(counter)} time(s) for a .md payload"
    assert rc == 0, f"hook rc={rc}\n{err}"
    assert out == "", f"hook printed on a .md payload: {out!r}"
    assert target.read_bytes() == b"# notes  \n"


# --------------------------------------------------------------------------- 2: false pass is harmless


def test_autoformat_false_pass_on_md_edit_launches_python_but_keeps_file(
    tmp_path: Path, counting_python: tuple[Path, Path]
) -> None:
    wrapper, counter = counting_python
    repo = _init_repo(tmp_path / "repo")
    target = repo / "notes.md"
    original = b"see old  \n"
    target.write_bytes(original)

    rc, out, err, raw = _run_hook(
        repo,
        {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": str(target),
                "old_string": "old",
                "new_string": "see x.py",  # строка кончается на `.py` -> в сыром JSON есть `.py"`
            },
        },
        wrapper,
    )

    assert b'x.py"' in raw, f'fixture has no raw `x.py"` substring: {raw!r}'
    assert _launches(counter) >= 1, 'the false pass did not reach Python: the hook cut off a payload with `.py"` in it'
    assert rc == 0, f"hook rc={rc}\n{err}"
    assert out == "", f"hook printed on a .md payload: {out!r}"
    assert target.read_bytes() == original, "the .md file was modified"


# --------------------------------------------------------------------------- 3: .py still gets formatted


def test_autoformat_still_formats_py_write(tmp_path: Path, counting_python: tuple[Path, Path]) -> None:
    wrapper, counter = counting_python
    exe = "ruff.exe" if IS_WINDOWS else "ruff"
    real_ruff = Path(sys.executable).parent / exe
    if not real_ruff.is_file() and not shutil.which("ruff"):
        pytest.skip("no ruff next to sys.executable and none on PATH: the hook cannot format anything here")

    repo = _init_repo(tmp_path / "repo")
    target = repo / "mod.py"
    target.write_bytes(b"x=1\n")

    rc, out, err, _raw = _run_hook(
        repo, {"tool_name": "Write", "tool_input": {"file_path": str(target), "content": "x=1\n"}}, wrapper
    )

    assert rc == 0, f"hook rc={rc}\n{err}"
    assert _launches(counter) >= 1, "Python was never launched for a .py payload"
    assert target.read_bytes() == b"x = 1\n", f"the .py file was not formatted: {target.read_bytes()!r}\n{err}"
