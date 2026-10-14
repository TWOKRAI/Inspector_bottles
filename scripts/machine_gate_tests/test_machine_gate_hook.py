"""Task 1.1 плана tooling-machine-gate-hook: хук PreToolUse, `classify`, класс `medium` и `timed` гейта.

Контракт — plans/2026-10-13_tooling-machine-gate-hook.md (Task 1.1) и
plans/2026-10-13_tooling-machine-gate-hook/classification.md (§2 таблица C1–C31 и N1–N8, §3 правило pytest,
§4 реклассификация, §5 timed, §6 допуск, §7 таблицы G/T/R/K, §9 REDS). Ожидаемые значения здесь — литералы из
таблиц, не вычисляются из кода под тестом. Каждая строка таблицы — свой параметр pytest с ID из таблицы.

Тесты зовут гейт ``scripts/machine_gate.sh`` и хук ``.claude/plugins/dev/hooks/machine-gate-guard.sh`` через
subprocess. Замок — только временный (env ``MACHINE_LOCK_DIR``), список timed — только временный
(env ``MACHINE_GATE_TIMED_LIST``): живой ``machine.lock``/``stand.lock`` и поставляемый список не затрагиваются.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GATE = (ROOT / "scripts" / "machine_gate.sh").as_posix()
HOOK = (ROOT / ".claude" / "plugins" / "dev" / "hooks" / "machine-gate-guard.sh").as_posix()
TIMED_SHIPPED = ROOT / "scripts" / "machine_gate_timed.txt"
SETTINGS = ROOT / ".claude" / "settings.json"
HOOK_REL = ".claude/plugins/dev/hooks/machine-gate-guard.sh"

PY = Path(sys.executable).as_posix()
SESSION = "s1"


# --- bash: копия _git_bash() из scripts/atlas/tests/test_lint_brief_1_9c.py (на Windows bash из Python = WSL) ----


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


# --- временные замки, списки, окружение ---------------------------------------------------------------------------


def _write_lock(lock_dir: Path, *, window: str | None = None, machine: bool = True, stand: bool = False) -> None:
    """Замок на temp-каталоге. window = '<владелец>:<вид>' (вторая строка). Всё с LF."""
    lock_dir.mkdir(parents=True, exist_ok=True)
    if machine:
        lines = ["coordinator: c1 | since x"]
        if window is not None:
            owner, kind = window.split(":")
            lines.append(f"window: {owner} | {kind} | x | until ~23:59")
        (lock_dir / "machine.lock").write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    if stand:
        (lock_dir / "stand.lock").write_bytes(b"other-s | x | measure\n")


def _write_timed_list(path: Path) -> None:
    """Временный список timed — с CRLF: гейт обязан снимать \\r (инъекция M18)."""
    entries = ["Services/robot_comm/", "multiprocess_framework/", "zz_timed_only_here/"]
    path.write_bytes(("\r\n".join(entries) + "\r\n").encode("utf-8"))


def _make_tests(tmp_path: Path) -> None:
    """Каталоги с test_m.py; seen.txt появляется в родителе каталога tests, если команда запускалась."""
    body = (
        "import pathlib\n"
        "def test_m():\n"
        '    pathlib.Path(__file__).resolve().parents[1].joinpath("seen.txt").write_text("RAN")\n'
    )
    for rel in ("mod/tests", "Services/robot_comm/tests", "zz_timed_only_here/tests"):
        d = tmp_path / rel
        d.mkdir(parents=True, exist_ok=True)
        (d / "test_m.py").write_text(body, encoding="utf-8", newline="\n")


def _env(lock_dir: Path, timed_list: Path | None = None) -> dict[str, str]:
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env["PYTHONUTF8"] = "1"
    env["MACHINE_LOCK_DIR"] = lock_dir.as_posix()
    env["CLAUDE_PYTHON_BIN"] = sys.executable
    if timed_list is not None:
        env["MACHINE_GATE_TIMED_LIST"] = timed_list.as_posix()
    return env


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


def _hook(
    bash: str,
    command: str | None,
    tmp_path: Path,
    *,
    raw_stdin: str | None = None,
    cwd: Path | None = None,
    project_dir: Path | None = None,
):
    """Вызов хука как это делает Claude Code: stdin JSON, код выхода 2 = блок."""
    env = _env(tmp_path / "lock")
    env["CLAUDE_PROJECT_DIR"] = str(project_dir if project_dir is not None else ROOT)
    if raw_stdin is None:
        raw_stdin = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    return _run([bash, HOOK], env=env, cwd=cwd if cwd is not None else tmp_path, stdin=raw_stdin)


# --- 1. test_classify: C1–C18, C20–C31 (kind и reason) -----------------------------------------------------------

CLASSIFY_CASES = [
    ("C1", "python scripts/run_framework_tests.py", "heavy", "run_framework_tests"),
    ("C2", "uv run --no-sync python scripts/run_framework_tests.py -k recipe", "heavy", "run_framework_tests"),
    ("C3", "powershell -File scripts/run_sim_all.ps1", "heavy", "run_sim_all"),
    ("C4", "python scripts/validate_commit/check_injections.py --plan x", "heavy", "injection_matrix"),
    ("C5", "python scripts/mutation_gate.py", "heavy", "injection_matrix"),
    ("C6", "python backend_ctl/probes/break_inject_g3_seams.py", "heavy", "injection_matrix"),
    ("C7", "uv run --no-project python .claude/plugins/mcp-qex/reindex_retry.py", "heavy", "qex_index"),
    ("C8", "python scripts/qex_retry.py", "heavy", "qex_index"),
    ("C9", "pytest -q", "heavy", "pytest_no_file_args"),
    ("C10", "python -m pytest multiprocess_framework/modules", "heavy", "pytest_dir_not_module_tests"),
    ("C11", "pytest -n 4 a/tests/test_x.py", "heavy", "pytest_xdist"),
    (
        "C12",
        ".venv/Scripts/python.exe -m pytest -q --tb=short Services/robot_comm/tests/test_kinematics_v2.py",
        "light",
        "pytest_files",
    ),
    ("C13", "PYTHONPATH=/d/wt pytest a/tests/test_x.py::test_one -q", "light", "pytest_files"),
    ("C14", "cd /d/wt && pytest -q", "heavy", "pytest_no_file_args"),
    ("C15", "pytest Services/robot_comm/tests", "medium", "pytest_module_dir"),
    (
        "C16",
        "python -m pytest -q --tb=short multiprocess_framework/modules/recipe/tests/",
        "medium",
        "pytest_module_dir",
    ),
    (
        "C17",
        ".venv/Scripts/python.exe -m pytest Services/robot_comm/tests Services/robot_comm/tests/test_kinematics_v2.py",
        "medium",
        "pytest_module_dir",
    ),
    ("C18", "PYTHONPATH=/d/wt pytest -q /d/wt/Services/robot_comm/tests -k kin", "medium", "pytest_module_dir"),
    ("C20", "pytest Services", "heavy", "pytest_no_file_args"),
    ("C21", "pytest tests", "heavy", "pytest_no_file_args"),
    ("C22", "pytest ./tests", "heavy", "pytest_dir_not_module_tests"),
    ("C23", "pytest Services/", "heavy", "pytest_dir_not_module_tests"),
    ("C24", "pytest Services/robot_comm/tests Services/line_sim/tests", "heavy", "pytest_multi_dir"),
    ("C25", "pytest -n 4 Services/robot_comm/tests", "heavy", "pytest_xdist"),
    (
        "C26",
        "pytest -q Services/robot_comm/tests multiprocess_framework/modules",
        "heavy",
        "pytest_dir_not_module_tests",
    ),
    ("C27", "python -m pytest --version", "heavy", "pytest_no_file_args"),
    ("C28", "pytest Services\\robot_comm\\tests", "heavy", "pytest_dir_not_module_tests"),
    ("C29", "pytest -c /d/wt/pyproject.toml a/tests/test_x.py", "light", "pytest_files"),
    ("C30", "pytest --ignore a/tests/slow Services/robot_comm/tests", "medium", "pytest_module_dir"),
    ("C31", "python backend_ctl/probes/break_inject_g4_other.py", "heavy", "injection_matrix"),
]
# Сегмент, который classify печатает третьим полем: для C14 это второй сегмент строки.
_SEGMENT_OVERRIDE = {"C14": "pytest -q"}


@pytest.mark.parametrize(
    ("command", "kind", "reason", "cid"),
    [pytest.param(c, k, r, i, id=i) for i, c, k, r in CLASSIFY_CASES],
)
def test_classify(bash, tmp_path, command, kind, reason, cid):
    p = _classify(bash, command, tmp_path)
    assert p.returncode == 0, _ctx(p)
    lines = [ln for ln in p.stdout.splitlines() if ln.strip()]
    assert len(lines) == 1, f"ожидалась ровно одна строка вывода, получено {len(lines)}\n{_ctx(p)}"
    fields = lines[0].split("\t")
    assert len(fields) == 3, f"формат <kind>\\t<reason>\\t<сегмент>\n{_ctx(p)}"
    assert fields[0] == kind, _ctx(p)
    assert fields[1] == reason, _ctx(p)
    assert fields[2].strip() == _SEGMENT_OVERRIDE.get(cid, command), _ctx(p)


# --- 2. test_classify_none: N1–N8, C19 + положительный параметр достижимости ---------------------------------------

NEGATIVE_COMMANDS = [
    ("N1", "grep -n pytest pyproject.toml"),
    ("N2", "git log --grep=pytest --oneline"),
    ("N3", "cat pytest.ini"),
    ("N4", "rg run_framework_tests scripts"),
    ("N5", "git show HEAD:scripts/run_sim_all.ps1"),
    ("N6", "echo pytest"),
    ("N7", "pip show pytest"),
    ("N8", "ls"),
]
C19 = "bash scripts/machine_gate.sh light s1 pytest Services/robot_comm/tests"


@pytest.mark.parametrize(
    ("command", "empty"),
    [pytest.param(c, True, id=i) for i, c in NEGATIVE_COMMANDS]
    + [pytest.param(C19, True, id="C19")]
    # положительный параметр достижимости: та же обвязка на настоящей тестовой команде (C9) вывод даёт
    + [pytest.param("pytest -q", False, id="reach_C9")],
)
def test_classify_none(bash, tmp_path, command, empty):
    p = _classify(bash, command, tmp_path)
    assert p.returncode == 0, _ctx(p)
    if empty:
        assert p.stdout.strip() == "", f"тестовых команд нет, вывод должен быть пуст\n{_ctx(p)}"
    else:
        assert p.stdout.startswith("heavy\t"), f"достижимость: C9 должен классифицироваться\n{_ctx(p)}"


# --- 3. test_hook_allows --------------------------------------------------------------------------------------------

_FOREIGN = "other-s:heavy"


@pytest.mark.parametrize(
    "name",
    # reach_C9 — положительный параметр достижимости: тот же замок и та же обвязка, голый pytest -q блокируется
    ["no_lock", "wrapped", *[i for i, _ in NEGATIVE_COMMANDS], "bad_json", "reach_C9"],
)
def test_hook_allows(bash, tmp_path, name):
    lock_dir = tmp_path / "lock"
    commands = dict(NEGATIVE_COMMANDS)
    raw = None
    if name == "no_lock":
        _write_lock(lock_dir, machine=False)
        command = "pytest -q"
    else:
        _write_lock(lock_dir, window=_FOREIGN)
        if name == "wrapped":
            command = f'bash "{GATE}" heavy s1 pytest -q'
        elif name == "bad_json":
            command = None
            raw = '{"tool_input": {"command": "pytest -q"'
        elif name == "reach_C9":
            command = "pytest -q"
        else:
            command = commands[name]
    p = _hook(bash, command, tmp_path, raw_stdin=raw)
    if name == "reach_C9":
        assert p.returncode == 2, f"достижимость: хук обязан блокировать C9\n{_ctx(p)}"
        assert "BLOCKED by machine-gate-guard" in p.stderr, _ctx(p)
        return
    assert p.returncode == 0, _ctx(p)
    assert p.stderr == "", _ctx(p)


# --- 4. test_hook_blocks --------------------------------------------------------------------------------------------

HOOK_BLOCK_CASES = [
    (
        "C10",
        "python -m pytest multiprocess_framework/modules",
        [
            "BLOCKED by machine-gate-guard",
            'machine_gate.sh" heavy <session> python -m pytest multiprocess_framework/modules',
        ],
    ),
    (
        "C12",
        ".venv/Scripts/python.exe -m pytest -q --tb=short Services/robot_comm/tests/test_kinematics_v2.py",
        ["BLOCKED by machine-gate-guard", 'machine_gate.sh" light <session>'],
    ),
    (
        "C15",
        "pytest Services/robot_comm/tests",
        [
            "BLOCKED by machine-gate-guard",
            "this command is medium (pytest_module_dir)",
            'machine_gate.sh" medium <session> pytest Services/robot_comm/tests',
        ],
    ),
]


@pytest.mark.parametrize(
    ("command", "expected"),
    [pytest.param(c, e, id=i) for i, c, e in HOOK_BLOCK_CASES],
)
def test_hook_blocks(bash, tmp_path, command, expected):
    _write_lock(tmp_path / "lock", window=_FOREIGN)
    p = _hook(bash, command, tmp_path)
    assert p.returncode == 2, _ctx(p)
    for part in expected:
        assert part in p.stderr, f"в stderr нет {part!r}\n{_ctx(p)}"
    assert any(ln.startswith("hook:") for ln in p.stderr.splitlines()), f"нет строки hook:\n{_ctx(p)}"


def test_hook_blocks_unwrapped_segment_after_wrapped(bash, tmp_path):
    _write_lock(tmp_path / "lock", window=_FOREIGN)
    command = f'bash "{GATE}" light s1 pytest a/tests/test_x.py && pytest -q'
    p = _hook(bash, command, tmp_path)
    assert p.returncode == 2, _ctx(p)
    assert "BLOCKED by machine-gate-guard" in p.stderr, _ctx(p)


def test_hook_independent_of_cwd(bash, tmp_path):
    _write_lock(tmp_path / "lock", window=_FOREIGN)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    p = _hook(bash, "pytest -q", tmp_path, cwd=elsewhere, project_dir=elsewhere)
    assert p.returncode == 2, _ctx(p)
    assert "BLOCKED by machine-gate-guard" in p.stderr, _ctx(p)


# --- 7. test_gate_claim: R1–R4 --------------------------------------------------------------------------------------


@dataclass
class ClaimRow:
    claim: str
    command: str  # "frt" = <T>/run_framework_tests.py, "version" = pytest --version, "echo" = echo RAN
    code: int
    out_has: list[str] = field(default_factory=list)
    out_not: list[str] = field(default_factory=list)
    err_has: list[str] = field(default_factory=list)


CLAIM_ROWS = {
    "R1": ClaimRow(
        "light",
        "frt",
        75,
        ["NO WINDOW"],
        ["FAKE"],
        ["machine_gate: reclassified light -> heavy (run_framework_tests)"],
    ),
    "R2": ClaimRow(
        "light",
        "version",
        75,
        ["NO WINDOW"],
        [],
        ["machine_gate: reclassified light -> heavy (pytest_no_file_args)"],
    ),
    "R3": ClaimRow(
        "medium",
        "frt",
        75,
        ["NO WINDOW"],
        ["FAKE"],
        ["machine_gate: reclassified medium -> heavy (run_framework_tests)"],
    ),
    "R4": ClaimRow("fast", "echo", 2, [], ["RAN"], ["kind must be heavy, medium or light"]),
}


@pytest.mark.parametrize("rid", list(CLAIM_ROWS))
def test_gate_claim(bash, tmp_path, rid):
    row = CLAIM_ROWS[rid]
    lock_dir = tmp_path / "lock"
    _write_lock(lock_dir)  # замок без окна s1
    frt = tmp_path / "run_framework_tests.py"
    frt.write_text('print("FAKE")\n', encoding="utf-8", newline="\n")
    timed = tmp_path / "timed.txt"
    _write_timed_list(timed)
    commands = {
        "frt": [PY, f"{tmp_path.as_posix()}/run_framework_tests.py"],
        "version": [PY, "-m", "pytest", "--version"],
        "echo": ["echo", "RAN"],
    }
    p = _run(
        [bash, GATE, row.claim, SESSION, *commands[row.command]],
        env=_env(lock_dir, timed),
        cwd=tmp_path,
    )
    assert p.returncode == row.code, _ctx(p)
    for s in row.out_has:
        assert s in p.stdout, f"в stdout нет {s!r}\n{_ctx(p)}"
    for s in row.out_not:
        assert s not in p.stdout, f"в stdout не должно быть {s!r}\n{_ctx(p)}"
    for s in row.err_has:
        assert s in p.stderr, f"в stderr нет {s!r}\n{_ctx(p)}"


# --- 8. test_gate_medium: G1–G12, T1–T14 ----------------------------------------------------------------------------


@dataclass
class MedRow:
    args: list[str]  # до <cmd>: [--timed] <класс> <сессия>
    window: str | None  # None = окон нет; иначе '<владелец>:<вид>'
    command: str  # MOD | MODF | MODT | FILET | FILETW | MODZ
    code: int
    seen: bool
    out_has: list[str] = field(default_factory=list)
    out_not: list[str] = field(default_factory=list)
    err_has: list[str] = field(default_factory=list)
    machine: bool = True  # есть machine.lock
    stand: bool = False  # есть stand.lock
    missing_list: bool = False  # env списка указывает на несуществующий файл


def _med(args: str, window: str | None, command: str, code: int, seen: bool, **kw) -> MedRow:
    return MedRow(args.split(), window, command, code, seen, **kw)


_STAND_MEASURE = "STAND MEASURE (stand.lock)"
_NO_LOCK = {"machine": False}
_RECL_MED = "machine_gate: reclassified light -> medium (pytest_module_dir)"

MED_ROWS: dict[str, MedRow] = {
    # G — не-timed
    "G1": _med("medium s1", None, "MOD", 0, True),
    "G2": _med("medium s1", "other-s:quiet", "MOD", 75, False, out_has=["QUIET WINDOW", "(machine_gate: medium, s1)"]),
    "G3": _med("medium s1", "other-s:stand", "MOD", 75, False, out_has=["STAND WINDOW", "(machine_gate: medium, s1)"]),
    "G4": _med("medium s1", "other-s:heavy", "MOD", 0, True),
    "G5-quiet": _med("medium s1", "s1:quiet", "MOD", 0, True),
    "G5-heavy": _med("medium s1", "s1:heavy", "MOD", 0, True),
    "G5-stand": _med("medium s1", "s1:stand", "MOD", 0, True),
    "G6": _med("medium s1", None, "MOD", 0, True, **_NO_LOCK),
    "G7": _med("medium s1", None, "MOD", 75, False, out_has=[_STAND_MEASURE], stand=True, **_NO_LOCK),
    "G8": _med(
        "light s1",
        "other-s:quiet",
        "MOD",
        75,
        False,
        out_has=["QUIET WINDOW", "(machine_gate: medium, s1)"],
        err_has=[_RECL_MED],
    ),
    "G9": _med("light s1", "other-s:stand", "MOD", 75, False, out_has=["STAND WINDOW"], err_has=[_RECL_MED]),
    "G10": _med("--timed medium s1", None, "MOD", 75, False, out_has=["NO WINDOW", "(machine_gate: medium, s1)"]),
    "G11": _med("--timed medium s1", "s1:heavy", "MOD", 0, True),
    "G12": _med("--timed light s1", None, "MODF", 0, True),
    # T — timed
    "T1": _med("medium s1", None, "MODT", 75, False, out_has=["NO WINDOW", "(machine_gate: medium, s1)"]),
    "T2": _med("medium s1", "other-s:heavy", "MODT", 75, False, out_has=["NO WINDOW"]),
    "T3": _med("medium s1", "other-s:quiet", "MODT", 75, False, out_has=["NO WINDOW"], out_not=["QUIET WINDOW"]),
    "T4": _med("medium s1", "other-s:stand", "MODT", 75, False, out_has=["NO WINDOW"], out_not=["STAND WINDOW"]),
    "T5-quiet": _med("medium s1", "s1:quiet", "MODT", 0, True),
    "T5-heavy": _med("medium s1", "s1:heavy", "MODT", 0, True),
    "T5-stand": _med("medium s1", "s1:stand", "MODT", 0, True),
    "T6": _med("medium s1", None, "MODT", 0, True, **_NO_LOCK),
    "T7": _med("medium s1", None, "MODT", 75, False, out_has=[_STAND_MEASURE], stand=True, **_NO_LOCK),
    "T8": _med(
        "light s1",
        None,
        "MODT",
        75,
        False,
        out_has=["NO WINDOW", "(machine_gate: medium, s1)"],
        err_has=[_RECL_MED],
    ),
    "T9": _med("medium s1", None, "FILET", 75, False, out_has=["NO WINDOW"]),
    "T10": _med(
        "medium s1",
        None,
        "MOD",
        75,
        False,
        out_has=["NO WINDOW"],
        err_has=["machine_gate: timed list not found:", "no_such.txt"],
        missing_list=True,
    ),
    "T11": _med(
        "medium s1",
        "s1:heavy",
        "MOD",
        0,
        True,
        err_has=["machine_gate: timed list not found:", "no_such.txt"],
        missing_list=True,
    ),
    "T12": _med("light s1", None, "FILET", 0, True),
    "T13": _med("medium s1", None, "FILETW", 75, False, out_has=["NO WINDOW"]),
    "T14": _med("medium s1", None, "MODZ", 75, False, out_has=["NO WINDOW"]),
}

# Каталог, в родителе tests которого появляется seen.txt, для каждой команды.
_SEEN_DIR = {
    "MOD": "mod",
    "MODF": "mod",
    "MODT": "Services/robot_comm",
    "FILET": "Services/robot_comm",
    "FILETW": "Services/robot_comm",
    "MODZ": "zz_timed_only_here",
}


def _med_command(name: str, tmp_path: Path) -> list[str]:
    t = tmp_path.as_posix()
    base = [PY, "-m", "pytest", "-q", "-p", "no:cacheprovider"]
    target = {
        "MOD": f"{t}/mod/tests",
        "MODF": f"{t}/mod/tests/test_m.py",
        "MODT": f"{t}/Services/robot_comm/tests",
        "FILET": f"{t}/Services/robot_comm/tests/test_m.py",
        "FILETW": str(tmp_path) + "\\Services\\robot_comm\\tests\\test_m.py",
        "MODZ": f"{t}/zz_timed_only_here/tests",
    }[name]
    return [*base, target]


@pytest.mark.parametrize("rid", list(MED_ROWS))
def test_gate_medium(bash, tmp_path, rid):
    row = MED_ROWS[rid]
    lock_dir = tmp_path / "lock"
    _write_lock(lock_dir, window=row.window, machine=row.machine, stand=row.stand)
    _make_tests(tmp_path)
    timed = tmp_path / "timed.txt"
    _write_timed_list(timed)
    list_env = tmp_path / "no_such.txt" if row.missing_list else timed
    p = _run(
        [bash, GATE, *row.args, *_med_command(row.command, tmp_path)],
        env=_env(lock_dir, list_env),
        cwd=tmp_path,
    )
    assert p.returncode == row.code, _ctx(p)
    for s in row.out_has:
        assert s in p.stdout, f"в stdout нет {s!r}\n{_ctx(p)}"
    for s in row.out_not:
        assert s not in p.stdout, f"в stdout не должно быть {s!r}\n{_ctx(p)}"
    for s in row.err_has:
        assert s in p.stderr, f"в stderr нет {s!r}\n{_ctx(p)}"
    if not row.err_has:
        assert "reclassified" not in p.stderr, _ctx(p)
        assert "timed list not found" not in p.stderr, _ctx(p)
    seen = (tmp_path / _SEEN_DIR[row.command] / "seen.txt").exists()
    assert seen is row.seen, f"seen.txt: ожидалось {row.seen}, есть {seen}\n{_ctx(p)}"


# --- 9. test_hook_installed ----------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["settings", "eol_lf"])
def test_hook_installed(name):
    if name == "settings":
        data = json.loads(SETTINGS.read_text(encoding="utf-8"))
        entries = [e for e in data["hooks"]["PreToolUse"] if e.get("matcher") == "Bash"]
        assert entries, "в PreToolUse нет записи с matcher Bash"
        hooks = entries[0]["hooks"]
        assert len(hooks) >= 3, f"в записи Bash ждём >= 3 хуков, есть {len(hooks)}"
        assert "protect-branch.sh" in hooks[1]["command"], hooks[1]
        assert "machine-gate-guard.sh" in hooks[2]["command"], hooks[2]
        assert hooks[2].get("timeout") == 10, hooks[2]
    else:
        p = subprocess.run(
            ["git", "check-attr", "eol", "--", HOOK_REL],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(ROOT),
            timeout=60,
            check=False,
        )
        assert p.returncode == 0, _ctx(p)
        assert p.stdout.strip().endswith("eol: lf"), _ctx(p)


# --- 10. test_timed_list_shipped -----------------------------------------------------------------------------------


def test_timed_list_shipped():
    assert TIMED_SHIPPED.is_file(), f"нет поставляемого списка timed: {TIMED_SHIPPED}"
    lines = [ln for ln in TIMED_SHIPPED.read_bytes().decode("utf-8").splitlines() if ln.strip()]
    assert lines == [
        "Plugins/sim/",
        "Services/robot_comm/",
        "Services/line_sim/",
        "Services/device_hub/",
        "multiprocess_framework/",
        "run_framework_tests.py",
        "run_sim_all.ps1",
    ]


# --- стражи (зелёные и до правки) ----------------------------------------------------------------------------------


def test_gate_light_file_runs_without_window(bash, tmp_path):
    lock_dir = tmp_path / "lock"
    _write_lock(lock_dir)  # замок без окна
    ok = tmp_path / "test_ok.py"
    ok.write_text("def test_ok(): pass\n", encoding="utf-8", newline="\n")
    p = _run(
        [bash, GATE, "light", SESSION, PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", ok.as_posix()],
        env=_env(lock_dir),
        cwd=tmp_path,
    )
    assert p.returncode == 0, _ctx(p)


def _exit(n: int) -> list[str]:
    return [PY, "-c", f"import sys; sys.exit({n})"]


@dataclass
class KRow:
    claim: str
    window: str | None
    command: str  # "exit3" | "exit4" | "exit5" | "pytest_ok"
    code: int
    out_has: list[str] = field(default_factory=list)
    machine: bool = True
    stand: bool = False


K_ROWS = {
    "K1": KRow("heavy", "other-s:heavy", "exit3", 75, ["NO WINDOW", "(machine_gate: heavy, s1)"]),
    "K2": KRow("light", "other-s:quiet", "exit3", 75, ["QUIET WINDOW", "(machine_gate: light, s1)"]),
    "K3": KRow("light", "other-s:heavy", "exit4", 4),
    "K4": KRow("light", "other-s:stand", "exit4", 4),
    "K5": KRow("light", None, "exit3", 75, [_STAND_MEASURE], machine=False, stand=True),
    "K6": KRow("heavy", None, "pytest_ok", 75, ["NO WINDOW"]),
    "K7": KRow("heavy", None, "exit5", 5, machine=False),
}


@pytest.mark.parametrize("kid", list(K_ROWS))
def test_gate_call_form_compat(bash, tmp_path, kid):
    row = K_ROWS[kid]
    lock_dir = tmp_path / "lock"
    _write_lock(lock_dir, window=row.window, machine=row.machine, stand=row.stand)
    ok = tmp_path / "test_ok.py"
    ok.write_text("def test_ok(): pass\n", encoding="utf-8", newline="\n")
    commands = {
        "exit3": _exit(3),
        "exit4": _exit(4),
        "exit5": _exit(5),
        "pytest_ok": [PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", ok.as_posix()],
    }
    p = _run(
        [bash, GATE, row.claim, SESSION, *commands[row.command]],
        env=_env(lock_dir),
        cwd=tmp_path,
    )
    assert p.returncode == row.code, _ctx(p)
    for s in row.out_has:
        assert s in p.stdout, f"в stdout нет {s!r}\n{_ctx(p)}"
    assert "reclassified" not in p.stderr, _ctx(p)
