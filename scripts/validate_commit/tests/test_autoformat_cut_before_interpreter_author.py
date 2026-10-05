"""Task 1.5 (commit-mechanism) — тест автора: отсечка не-.py стоит ДО поиска интерпретатора.

Слепые тесты (`test_autoformat_skips_python_for_non_py.py`) подменяют интерпретатор через
`CLAUDE_PYTHON_BIN`, а с ним `python-bin.sh` Python не запускает (только `command -v`). Поэтому
отсечка, перенесённая ПОСЛЕ поиска интерпретатора (вариант черновика ТЗ, инъекция J2 лида), их
проходит, хотя на `.md` хук снова платит запуск `python3 -c "import sys"` (~0,1 с).

Здесь `CLAUDE_PYTHON_BIN` не задан, а первым в PATH лежит считающий `python3`: его видит и проба
`python-bin.sh`, и разбор входа. Контрольный тест на `.py` доказывает, что на этой машине подмена
вообще достижима (иначе 0 запусков на `.md` ничего бы не значил).

Найдено ревью 1.5 r1 (воспроизведение: копия хука с J2 — 1 запуск на `.md`, без J2 — 0).
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

_BLIND_PATH = Path(__file__).with_name("test_autoformat_skips_python_for_non_py.py")
_spec = importlib.util.spec_from_file_location("_autoformat_blind_helpers", _BLIND_PATH)
assert _spec is not None and _spec.loader is not None
_blind = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _blind
_spec.loader.exec_module(_blind)


def _make_counting_python3(fakebin: Path) -> Path:
    """`python3` без расширения: строка в счётчик, затем настоящий Python со всеми аргументами."""
    fakebin.mkdir(parents=True, exist_ok=True)
    counter = fakebin / "python3-launches.txt"
    wrapper = fakebin / "python3"
    wrapper.write_bytes(
        (
            "#!/usr/bin/env bash\n"
            f'echo launched >> "{counter.as_posix()}"\n'
            f'exec "{Path(sys.executable).as_posix()}" "$@"\n'
        ).encode("utf-8")
    )
    wrapper.chmod(0o755)
    return counter


def _run_hook_via_path(repo: Path, payload: dict, fakebin: Path) -> tuple[int, str, str]:
    env = _blind._clean_env()  # без CLAUDE_PYTHON_BIN
    # fakebin первым: `command -v python3` в python-bin.sh находит подмену; каталог venv — ради ruff.
    env["PATH"] = os.pathsep.join([str(fakebin), str(Path(sys.executable).parent), env.get("PATH", "")])
    env["CLAUDE_PROJECT_DIR"] = str(repo)
    raw = json.dumps(payload).encode("utf-8")
    rc, out, err = _blind._run_raw([_blind._find_git_bash(), str(_blind.AUTOFORMAT_HOOK)], repo, env, stdin_data=raw)
    return rc, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")


def test_md_write_launches_no_python_even_through_the_interpreter_probe(tmp_path: Path) -> None:
    counter = _make_counting_python3(tmp_path / "fakebin")
    repo = _blind._init_repo(tmp_path / "repo")
    target = repo / "notes.md"
    target.write_bytes(b"# notes  \n")

    rc, out, err = _run_hook_via_path(
        repo,
        {"tool_name": "Write", "tool_input": {"file_path": str(target), "content": "# notes  \n"}},
        tmp_path / "fakebin",
    )

    launches = _blind._launches(counter)
    assert launches == 0, (
        f"python3 launched {launches} time(s) on a .md payload: the cut is after the interpreter lookup"
    )
    assert rc == 0, f"hook rc={rc}\n{err}"
    assert out == ""


def test_control_py_write_reaches_the_counting_python3(tmp_path: Path) -> None:
    exe = "ruff.exe" if _blind.IS_WINDOWS else "ruff"
    if not (Path(sys.executable).parent / exe).is_file() and not shutil.which("ruff"):
        pytest.skip("no ruff next to sys.executable and none on PATH: the hook cannot format anything here")
    counter = _make_counting_python3(tmp_path / "fakebin")
    repo = _blind._init_repo(tmp_path / "repo")
    target = repo / "mod.py"
    target.write_bytes(b"x=1\n")

    rc, _out, err = _run_hook_via_path(
        repo, {"tool_name": "Write", "tool_input": {"file_path": str(target), "content": "x=1\n"}}, tmp_path / "fakebin"
    )

    assert rc == 0, f"hook rc={rc}\n{err}"
    assert _blind._launches(counter) >= 1, "the counting python3 was never reached: the .md test above proves nothing"
    assert target.read_bytes() == b"x = 1\n", f"the .py file was not formatted: {target.read_bytes()!r}\n{err}"
