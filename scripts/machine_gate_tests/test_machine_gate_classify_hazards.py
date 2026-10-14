"""Task 1.1 плана tooling-machine-gate-hook, раунд 2 (после ревью кода): авторские тесты developer.

Контракт — plans/2026-10-13_tooling-machine-gate-hook/classification.md §1 (кавычки, heredoc, префиксы, make),
§2 (строки C32–C48 и N9–N19), блок «Совет хука» (H1–H4) и префильтр. Ожидаемые значения здесь — литералы из
таблиц, не вычисляются из кода под тестом. Слепой файл tester (test_machine_gate_hook.py) не затронут.

Замок — только временный (env ``MACHINE_LOCK_DIR``); живой ``machine.lock`` не трогается.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GATE = (ROOT / "scripts" / "machine_gate.sh").as_posix()
HOOK = (ROOT / ".claude" / "plugins" / "dev" / "hooks" / "machine-gate-guard.sh").as_posix()


# --- bash: копия _git_bash() из test_machine_gate_hook.py (на Windows bash из Python = WSL) -----------------------


def _git_bash() -> str | None:
    git = shutil.which("git")
    for parent in Path(git).resolve().parents if git else []:
        if (parent / "bin" / "bash.exe").is_file():
            return str(parent / "bin" / "bash.exe")
    return shutil.which("bash") if sys.platform != "win32" else None


@pytest.fixture(scope="module")
def bash() -> str:
    found = _git_bash()
    assert found is not None, "Git Bash не найден: без него гейт и хук не запустить (не пропуск, а падение)"
    return found


def _env(lock_dir: Path) -> dict[str, str]:
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env["PYTHONUTF8"] = "1"
    env["MACHINE_LOCK_DIR"] = lock_dir.as_posix()
    env["CLAUDE_PYTHON_BIN"] = sys.executable
    env["CLAUDE_PROJECT_DIR"] = str(ROOT)
    return env


def _write_foreign_lock(lock_dir: Path) -> None:
    lock_dir.mkdir(parents=True, exist_ok=True)
    body = "coordinator: c1 | since x\nwindow: other-s | heavy | x | until ~23:59\n"
    (lock_dir / "machine.lock").write_bytes(body.encode("utf-8"))


def _run(argv: list[str], *, env: dict[str, str], cwd: Path, stdin: str | None = None):
    return subprocess.run(
        argv,
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        cwd=str(cwd),
        timeout=60,
        check=False,
    )


def _ctx(p: subprocess.CompletedProcess[str]) -> str:
    return f"код={p.returncode}\nstdout={p.stdout!r}\nstderr={p.stderr!r}"


def _classify(bash: str, command: str, tmp_path: Path):
    return _run([bash, GATE, "classify", command], env=_env(tmp_path / "lock"), cwd=tmp_path)


def _hook(bash: str, command: str, tmp_path: Path):
    stdin = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    return _run([bash, HOOK], env=_env(tmp_path / "lock"), cwd=tmp_path, stdin=stdin)


# --- 1. test_classify_hazards: C32–C48 (ряды) и N9–N19 (пусто) -----------------------------------------------------

# (id, команда, ряды); ряд = (kind, reason, третье поле или None — не проверять). Пустой список = пустой вывод.
Row = tuple[str, str, str | None]

HAZARD_CASES: list[tuple[str, str, list[Row]]] = [
    ("C32", r"powershell -ExecutionPolicy Bypass -File scripts\run_sim_all.ps1", [("heavy", "run_sim_all", None)]),
    ("C33", "pwsh -File scripts/run_sim_all.ps1", [("heavy", "run_sim_all", None)]),
    (
        "C34",
        "python -X faulthandler -m pytest Services/robot_comm/tests",
        [("medium", "pytest_module_dir", None)],
    ),
    ("C35", "python -X utf8 -m pytest -q", [("heavy", "pytest_no_file_args", None)]),
    ("C36", "python -W ignore -m pytest a/tests/test_x.py", [("light", "pytest_files", None)]),
    ("C37", "env PYTHONUTF8=1 pytest -q", [("heavy", "pytest_no_file_args", None)]),
    ("C38", "time pytest a/tests/test_x.py", [("light", "pytest_files", "pytest a/tests/test_x.py")]),
    (
        "C39",
        "for f in a b; do pytest -q $f; done",
        [("heavy", "pytest_no_file_args", "pytest -q $f")],
    ),
    ("C40", "if true; then pytest -q; fi", [("heavy", "pytest_no_file_args", "pytest -q")]),
    ("C41", "uv run --python 3.12 pytest -q", [("heavy", "pytest_no_file_args", None)]),
    ("C42", "timeout -k 5 300 pytest -q", [("heavy", "pytest_no_file_args", None)]),
    ("C43", "make gate", [("heavy", "make_suite", None)]),
    ("C44", "make test-fast", [("heavy", "make_suite", None)]),
    ("C45", "cat <<'EOF'\nx\nEOF\npytest -q", [("heavy", "pytest_no_file_args", "pytest -q")]),
    ("C46", 'pytest -q && echo "done; ok"', [("heavy", "pytest_no_file_args", "pytest -q")]),
    ("C47", 'echo "a \\" b" ; pytest -q', [("heavy", "pytest_no_file_args", "pytest -q")]),
    ("C48", "{ pytest -q; }", [("heavy", "pytest_no_file_args", "pytest -q")]),
    ("N9", 'grep -n -E "cwd|pytest|subprocess" scripts/run_framework_tests.py', []),
    ("N10", 'rg -n "conftest|pytest|unittest" scripts', []),
    ("N11", 'git commit -m "fix: hook; pytest -q is blocked"', []),
    ("N12", 'git log --grep="x; pytest -q"', []),
    ("N13", "echo 'a && pytest -q'", []),
    ("N14", "cat >> report.md <<'EOF'\npytest -q\nEOF", []),
    ("N15", "git commit -F - <<EOF\npython -m pytest a/tests\nEOF", []),
    ("N16", "cat <<-EOF\n\tpytest -q\n\tEOF", []),
    ("N17", "make check", []),
    ("N18", "make test-ctl-offline", []),
    ("N19", "make help", []),
]


@pytest.mark.parametrize(
    ("command", "rows"),
    [pytest.param(c, r, id=i) for i, c, r in HAZARD_CASES],
)
def test_classify_hazards(bash, tmp_path, command, rows):
    p = _classify(bash, command, tmp_path)
    assert p.returncode == 0, _ctx(p)
    lines = [ln for ln in p.stdout.splitlines() if ln.strip()]
    assert len(lines) == len(rows), f"ожидалось рядов: {len(rows)}, получено {len(lines)}\n{_ctx(p)}"
    for line, (kind, reason, segment) in zip(lines, rows, strict=True):
        fields = line.split("\t")
        assert len(fields) == 3, f"формат <kind>\\t<reason>\\t<сегмент>\n{_ctx(p)}"
        assert fields[0] == kind, _ctx(p)
        assert fields[1] == reason, _ctx(p)
        if segment is not None:
            assert fields[2].strip() == segment, _ctx(p)


# --- 2. test_hook_hazards_allow: N9–N16 при живом замке с чужим окном -> 0 --------------------------------------------

_ALLOW_IDS = {"N9", "N10", "N11", "N12", "N13", "N14", "N15", "N16"}
_ALLOW_CASES = [(i, c) for i, c, _ in HAZARD_CASES if i in _ALLOW_IDS]


@pytest.mark.parametrize(
    ("command", "blocks"),
    # reach_C9 — достижимость: те же замок и обвязка, голый pytest -q блокируется
    [pytest.param(c, False, id=i) for i, c in _ALLOW_CASES] + [pytest.param("pytest -q", True, id="reach_C9")],
)
def test_hook_hazards_allow(bash, tmp_path, command, blocks):
    _write_foreign_lock(tmp_path / "lock")
    p = _hook(bash, command, tmp_path)
    if blocks:
        assert p.returncode == 2, f"достижимость: хук обязан блокировать C9\n{_ctx(p)}"
        assert "BLOCKED by machine-gate-guard" in p.stderr, _ctx(p)
        return
    assert p.returncode == 0, _ctx(p)
    assert p.stderr == "", _ctx(p)


# --- 3. test_hook_advice: H1–H4 ------------------------------------------------------------------------------------

_GATE_CALL = 'bash "$(git rev-parse --path-format=absolute --git-common-dir)/../scripts/machine_gate.sh"'

ADVICE_CASES = [
    (
        "H1",
        "cd D:/wt && PYTHONPATH=. python -m pytest a/tests/test_x.py",
        [f"PYTHONPATH=. {_GATE_CALL} light <session> python -m pytest a/tests/test_x.py"],
        ["light <session> PYTHONPATH"],
    ),
    ("H2", "pytest a/tests/test_x.py && pytest -q", ['machine_gate.sh" heavy <session> pytest -q'], []),
    ("H3", "make gate", ['machine_gate.sh" heavy <session> make gate'], []),
    ("H4", r"powershell -ExecutionPolicy Bypass -File scripts\run_sim_all.ps1", ["(run_sim_all)"], []),
]


@pytest.mark.parametrize(
    ("command", "has", "has_not"),
    [pytest.param(c, h, n, id=i) for i, c, h, n in ADVICE_CASES],
)
def test_hook_advice(bash, tmp_path, command, has, has_not):
    _write_foreign_lock(tmp_path / "lock")
    p = _hook(bash, command, tmp_path)
    assert p.returncode == 2, _ctx(p)
    for s in has:
        assert s in p.stderr, f"в stderr нет {s!r}\n{_ctx(p)}"
    for s in has_not:
        assert s not in p.stderr, f"в stderr не должно быть {s!r}\n{_ctx(p)}"


# --- 4. test_classify_many_segments_is_fast -------------------------------------------------------------------------


def test_classify_many_segments_is_fast(bash, tmp_path):
    # 12 КБ в одном argv обрезает лаунчер Git Bash на Windows (предел ~8 КБ), поэтому строка идёт через файл:
    # внутренний bash -> bash вызов предела не имеет.
    command_file = tmp_path / "many.txt"
    command_file.write_bytes(("; ".join(["echo x"] * 1500) + "; pytest -q").encode("utf-8"))
    started = time.perf_counter()
    p = _run(
        [bash, "-c", 'bash "$0" classify "$(cat "$1")"', GATE, command_file.as_posix()],
        env=_env(tmp_path / "lock"),
        cwd=tmp_path,
    )
    elapsed = time.perf_counter() - started
    assert p.returncode == 0, _ctx(p)
    lines = [ln for ln in p.stdout.splitlines() if ln.strip()]
    assert len(lines) == 1, f"ожидался один ряд\n{_ctx(p)}"
    assert lines[0].split("\t")[:2] == ["heavy", "pytest_no_file_args"], _ctx(p)
    assert elapsed <= 8, f"classify 1500 сегментов занял {elapsed:.1f} с, предел 8 с (таймаут хука 10 с)"
