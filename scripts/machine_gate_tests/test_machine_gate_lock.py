"""Task 1.2 плана tooling-machine-gate-hook: `grant` / `close` / `status` и проверка формата замка `machine.lock`.

Контракт — plans/2026-10-13_tooling-machine-gate-hook/task-1.2.md (разделы «Грамматика замка», «Подкоманды», «REDS»,
«Стражи», «TRAPS»). Ожидаемые значения здесь — литералы из этого файла, не вычисляются из кода под тестом.

Тесты зовут гейт ``scripts/machine_gate.sh`` через subprocess (Git Bash). КАЖДЫЙ вызов идёт с env ``MACHINE_LOCK_DIR`` =
свежий подкаталог ``tmp_path``: живой ``D:/PROJECT_INNOTECH/Inspector_vision/machine.lock`` не читается и не
переписывается. Замки пишутся ``write_bytes`` (точные байты, LF/CRLF).

Отклонение от текста спеки (одно): ``newline_in_what`` передаёт ``"a\\nb c"``, а не ``"a\\nb"``. Windows
CreateProcess склеивает argv в строку, а Git Bash режет голый ``a\\nb`` по переводу строки на два аргумента; без пробела
гейт не увидит перевода строки внутри одного аргумента вообще (проверено: ``bash -c 'echo $#' _ "a\\nb" z`` даёт 3).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GATE = (ROOT / "scripts" / "machine_gate.sh").as_posix()

REFUSE_PREFIX = "machine_gate: "


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
    assert found is not None, "Git Bash не найден: без него гейт не запустить (не пропуск, а падение)"
    return found


@pytest.fixture
def lock_dir(tmp_path: Path) -> Path:
    """Свежий подкаталог на случай: сюда пишется замок, сюда же смотрит MACHINE_LOCK_DIR."""
    d = tmp_path / "lock"
    d.mkdir()
    return d


# --- вызов гейта -------------------------------------------------------------------------------------------------


@dataclass
class Out:
    code: int
    out: str
    err: str
    raw_err: bytes

    def ctx(self) -> str:
        return f"код={self.code}\nstdout={self.out!r}\nstderr={self.err!r}"


def _env(lock_dir: Path) -> dict[str, str]:
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env["PYTHONUTF8"] = "1"
    env["MACHINE_LOCK_DIR"] = lock_dir.as_posix()  # без этого гейт трогает живой замок
    return env


def _gate(bash: str, args: list[str], lock_dir: Path) -> Out:
    p = subprocess.run(
        [bash, GATE, *args],
        capture_output=True,  # байты: \r в выводе должен быть виден, а не съеден universal newlines
        env=_env(lock_dir),
        cwd=str(lock_dir.parent),
        timeout=60,
        check=False,
    )
    return Out(
        code=p.returncode,
        out=p.stdout.decode("utf-8", errors="replace"),
        err=p.stderr.decode("utf-8", errors="replace"),
        raw_err=p.stderr,
    )


def _listing(d: Path) -> list[str]:
    return sorted(p.name for p in d.iterdir())


def _lines(*lines: str) -> bytes:
    """Замок с LF, `\\n` после последней строки."""
    return ("\n".join(lines) + "\n").encode("utf-8")


# «Замок R1» из спеки.
R1_LINES = [
    "coordinator: c1 | since x",
    "waiting: s2 | heavy | a | ~3 min",
    "waiting: s22 | heavy | c | ~1 min",
    "waiting: s3 | heavy | b | ~80 min",
    "stand: free",
]
R1 = _lines(*R1_LINES)


def _r1_with_window(window: str) -> bytes:
    """R1 + строка `window:` второй (сразу после coordinator)."""
    return _lines(R1_LINES[0], window, *R1_LINES[1:])


def _assert_one_line_refusal(res: Out, line: str) -> None:
    """Код 2 и в stderr ровно одна строка `line` (с одним `\\n`)."""
    assert res.code == 2, res.ctx()
    assert res.raw_err == line.encode("utf-8") + b"\n", res.ctx()


# --- REDS 1. grant: пишет окно, снимает waiting сессии ------------------------------------------------------------


@pytest.mark.parametrize("eol", ["lf", "crlf"])
def test_grant_writes_window_and_drops_waiting(bash: str, lock_dir: Path, eol: str) -> None:
    lock = lock_dir / "machine.lock"
    lock.write_bytes(R1 if eol == "lf" else R1.replace(b"\n", b"\r\n"))
    ino_before = os.stat(lock).st_ino

    t0 = datetime.now().replace(second=0, microsecond=0)
    res = _gate(bash, ["grant", "c1", "s2", "heavy", "20", "T3.9", "tests"], lock_dir)
    t1 = datetime.now().replace(second=0, microsecond=0)

    assert res.code == 0, res.ctx()
    assert res.raw_err == b"", res.ctx()

    expected = (
        r"coordinator: c1 \| since x\n"
        r"window: s2 \| heavy \| T3\.9 tests \| until ~(\d\d:\d\d)\n"
        r"waiting: s22 \| heavy \| c \| ~1 min\n"
        r"waiting: s3 \| heavy \| b \| ~80 min\n"
        r"stand: free\n"
    )
    text = lock.read_bytes().decode("utf-8")
    m = re.fullmatch(expected, text, re.ASCII)
    assert m is not None, text

    # HH:MM — между (часы до вызова + 20 мин) и (часы после вызова + 20 мин), с точностью до минуты
    allowed: set[str] = set()
    t = t0
    while t <= t1:
        allowed.add((t + timedelta(minutes=20)).strftime("%H:%M"))
        t += timedelta(minutes=1)
    assert m.group(1) in allowed, (m.group(1), sorted(allowed))

    assert os.stat(lock).st_ino != ino_before, "замок переписан на месте, а не заменён через tmp + mv"
    assert _listing(lock_dir) == ["machine.lock"]


# --- REDS 2. grant: отказы -----------------------------------------------------------------------------------------

GRANT_USAGE = "usage: machine_gate.sh grant <coordinator> <session> quiet|heavy|stand <minutes> <what...>"

# (id, замок или None для пустого каталога, argv, строка stderr целиком, tmp рядом с замком, держать ли замок открытым)
GRANT_REFUSALS = [
    pytest.param(
        _r1_with_window("window: s3 | heavy | b | until ~23:59"),
        ["grant", "c1", "s2", "heavy", "20", "x"],
        REFUSE_PREFIX + "a window is already open",
        False,
        False,
        id="second_window",
    ),
    pytest.param(
        _r1_with_window("window: s2 | heavy | b | until ~23:59"),
        ["grant", "c1", "s2", "heavy", "20", "x"],
        REFUSE_PREFIX + "a window is already open",
        False,
        False,
        id="own_window",
    ),
    pytest.param(
        R1,
        ["grant", "s9", "s2", "heavy", "20", "x"],
        REFUSE_PREFIX + "not the coordinator",
        False,
        False,
        id="non_coordinator",
    ),
    pytest.param(
        R1,
        ["grant", "c", "s2", "heavy", "20", "x"],
        REFUSE_PREFIX + "not the coordinator",
        False,
        False,
        id="coordinator_prefix",
    ),
    pytest.param(
        R1,
        ["grant", "c.", "s2", "heavy", "20", "x"],
        REFUSE_PREFIX + "not the coordinator",
        False,
        False,
        id="coordinator_regex",
    ),
    pytest.param(
        R1,
        ["grant", "c1", "s2 [ab]", "heavy", "20", "x"],
        REFUSE_PREFIX + "bad session name",
        False,
        False,
        id="bad_session",
    ),
    pytest.param(
        R1,
        ["grant", "c1", "s2", "fast", "20", "x"],
        REFUSE_PREFIX + "window kind must be quiet, heavy or stand",
        False,
        False,
        id="bad_kind",
    ),
    pytest.param(
        R1,
        ["grant", "c1", "s2", "medium", "20", "x"],
        REFUSE_PREFIX + "window kind must be quiet, heavy or stand",
        False,
        False,
        id="medium_kind",
    ),
    pytest.param(
        R1,
        ["grant", "c1", "s2", "heavy", "0", "x"],
        REFUSE_PREFIX + "minutes must be 1..600",
        False,
        False,
        id="bad_minutes_0",
    ),
    pytest.param(
        R1,
        ["grant", "c1", "s2", "heavy", "601", "x"],
        REFUSE_PREFIX + "minutes must be 1..600",
        False,
        False,
        id="bad_minutes_601",
    ),
    pytest.param(
        R1,
        ["grant", "c1", "s2", "heavy", "abc", "x"],
        REFUSE_PREFIX + "minutes must be 1..600",
        False,
        False,
        id="bad_minutes_abc",
    ),
    pytest.param(
        R1,
        ["grant", "c1", "s2", "heavy", "20", "a | b"],
        REFUSE_PREFIX + "what must not contain | or line breaks",
        False,
        False,
        id="pipe_in_what",
    ),
    pytest.param(
        R1,
        # пробел внутри аргумента нужен, чтобы Windows/Git Bash донёс "a<LF>b c" одним аргументом (см. docstring файла)
        ["grant", "c1", "s2", "heavy", "20", "a\nb c"],
        REFUSE_PREFIX + "what must not contain | or line breaks",
        False,
        False,
        id="newline_in_what",
    ),
    pytest.param(
        R1,
        ["grant", "c1", "s2", "heavy", "20"],
        GRANT_USAGE,
        False,
        False,
        id="few_args",
    ),
    pytest.param(
        None,
        ["grant", "c1", "s2", "heavy", "20", "x"],
        REFUSE_PREFIX + "no machine.lock",
        False,
        False,
        id="no_lock",
    ),
    pytest.param(
        R1,
        ["grant", "c1", "s2", "heavy", "20", "x"],
        REFUSE_PREFIX + "machine.lock.tmp exists (another grant/close running, or a leftover)",
        True,
        False,
        id="tmp_exists",
    ),
    pytest.param(
        R1,
        ["grant", "c1", "s2", "heavy", "20", "x"],
        REFUSE_PREFIX + "cannot replace machine.lock (busy), retry",
        False,
        True,
        marks=pytest.mark.skipif(sys.platform != "win32", reason="на POSIX rename поверх открытого файла проходит"),
        id="busy",
    ),
]


@pytest.mark.parametrize(("lock_bytes", "argv", "line", "tmp_before", "hold_open"), GRANT_REFUSALS)
def test_grant_refuses(
    bash: str,
    lock_dir: Path,
    lock_bytes: bytes | None,
    argv: list[str],
    line: str,
    tmp_before: bool,
    hold_open: bool,
) -> None:
    lock = lock_dir / "machine.lock"
    tmp = lock_dir / "machine.lock.tmp"
    if lock_bytes is not None:
        lock.write_bytes(lock_bytes)
    if tmp_before:
        tmp.write_bytes(b"x")

    if hold_open:
        with open(lock, "rb"):  # держим дескриптор на время вызова: mv поверх него на Windows падает
            res = _gate(bash, argv, lock_dir)
    else:
        res = _gate(bash, argv, lock_dir)

    _assert_one_line_refusal(res, line)
    if lock_bytes is None:
        assert not lock.exists(), "без замка grant создал machine.lock"
        assert _listing(lock_dir) == []
    else:
        assert lock.read_bytes() == lock_bytes, "отказ изменил замок"
    if tmp_before:
        assert tmp.read_bytes() == b"x", "чужой machine.lock.tmp тронут"
        assert _listing(lock_dir) == ["machine.lock", "machine.lock.tmp"]
    elif lock_bytes is not None:
        assert _listing(lock_dir) == ["machine.lock"], "после отказа остался machine.lock.tmp"


# --- REDS 3. close: снимает своё окно -----------------------------------------------------------------------------


def test_close_removes_own_window(bash: str, lock_dir: Path) -> None:
    lock = lock_dir / "machine.lock"
    lock.write_bytes(
        b"coordinator: c1 | since x\n"
        b"window: s2 | heavy | x | until ~23:59\n"
        b"\n"
        b"waiting: s3 | heavy | b | ~80 min\n"
        b"stand: free\n"
    )
    ino_before = os.stat(lock).st_ino

    res = _gate(bash, ["close", "c1", "s2"], lock_dir)

    assert res.code == 0, res.ctx()
    # stderr пуст — читаю «остальное как у grant» строго (см. отчёт: вопрос к спеке)
    assert res.raw_err == b"", res.ctx()
    assert lock.read_bytes() == b"coordinator: c1 | since x\n\nwaiting: s3 | heavy | b | ~80 min\nstand: free\n"
    assert os.stat(lock).st_ino != ino_before, "замок переписан на месте, а не заменён через tmp + mv"
    assert _listing(lock_dir) == ["machine.lock"]


# --- REDS 4. close: отказы ----------------------------------------------------------------------------------------

CLOSE_REFUSALS = [
    pytest.param(
        _r1_with_window("window: s22 | heavy | x | until ~23:59"),
        ["close", "c1", "s2"],
        REFUSE_PREFIX + "no window of this session",
        id="foreign_window",
    ),
    pytest.param(R1, ["close", "c1", "s2"], REFUSE_PREFIX + "no window of this session", id="no_window"),
    pytest.param(
        _r1_with_window("window: s2 | heavy | x | until ~23:59"),
        ["close", "s9", "s2"],
        REFUSE_PREFIX + "not the coordinator",
        id="non_coordinator",
    ),
]


@pytest.mark.parametrize(("lock_bytes", "argv", "line"), CLOSE_REFUSALS)
def test_close_refuses(bash: str, lock_dir: Path, lock_bytes: bytes, argv: list[str], line: str) -> None:
    lock = lock_dir / "machine.lock"
    lock.write_bytes(lock_bytes)

    res = _gate(bash, argv, lock_dir)

    _assert_one_line_refusal(res, line)
    assert lock.read_bytes() == lock_bytes, "отказ изменил замок"
    assert _listing(lock_dir) == ["machine.lock"], "после отказа остался machine.lock.tmp"


# --- REDS 5. битый замок: код 2 во всех режимах и подкомандах (10 замков × 6 вызовов) -------------------------------

COORD = "coordinator: c1 | since x"
W_OK = "window: s2 | heavy | x | until ~23:59"


def _bad(*defect_lines: str) -> bytes:
    return _lines(COORD, *defect_lines)


# (замок, проверка stderr): ("exact", строка) — вся строка; ("prefix", начало) — начало строки.
MALFORMED_LOCKS = [
    pytest.param(
        _bad("window:s2 | heavy | x | until ~23:59"),
        ("prefix", "machine_gate: malformed machine.lock:2: "),
        id="window_no_space",
    ),
    pytest.param(
        _bad("windw: s2 | heavy | x | until ~23:59"),
        ("exact", "machine_gate: malformed machine.lock:2: windw: s2 | heavy | x | until ~23:59"),
        id="windw_typo",
    ),
    pytest.param(
        _bad("window: s2 | heavy | x | until ~23:59", "window: s3 | heavy | x | until ~23:59"),
        ("prefix", "machine_gate: malformed machine.lock:3: window: s3"),
        id="two_windows",
    ),
    pytest.param(
        _bad("window: s2 | fast | x | until ~1"),
        ("prefix", "machine_gate: malformed machine.lock:2: "),
        id="kind_fast",
    ),
    pytest.param(
        _bad("window: s2 | medium | x | until ~1"),
        ("prefix", "machine_gate: malformed machine.lock:2: "),
        id="kind_medium",
    ),
    pytest.param(
        _bad("window: s2 | heavy | until ~1"),
        ("prefix", "machine_gate: malformed machine.lock:2: "),
        id="window_3_fields",
    ),
    pytest.param(
        _bad("window: s2 [ab] | heavy | x | until ~23:59"),
        ("prefix", "machine_gate: malformed machine.lock:2: "),
        id="name_with_ref",
    ),
    pytest.param(
        _bad("coordinator: c2 | since y"),
        ("prefix", "machine_gate: malformed machine.lock:2: "),
        id="second_coordinator",
    ),
    pytest.param(
        _bad("waiting: s3 | heavy | b"),
        ("prefix", "machine_gate: malformed machine.lock:2: "),
        id="waiting_3_fields",
    ),
    pytest.param(
        _lines(W_OK),
        ("exact", "machine_gate: malformed machine.lock: no coordinator line"),
        id="no_coordinator",
    ),
]

# (argv, меняет ли замок при успехе — для проверки «байты прежние»)
MALFORMED_CALLS = [
    pytest.param(["heavy", "s2", "echo", "RAN"], False, id="heavy"),
    pytest.param(["medium", "s2", "echo", "RAN"], False, id="medium"),
    pytest.param(["--timed", "medium", "s2", "echo", "RAN"], False, id="timed_medium"),
    pytest.param(["light", "s2", "echo", "RAN"], False, id="light"),
    pytest.param(["grant", "c1", "s2", "heavy", "5", "x"], True, id="grant"),
    pytest.param(["close", "c1", "s2"], True, id="close"),
]


@pytest.mark.parametrize(("argv", "is_writer"), MALFORMED_CALLS)
@pytest.mark.parametrize(("lock_bytes", "expect"), MALFORMED_LOCKS)
def test_malformed_lock_exit_2(
    bash: str, lock_dir: Path, lock_bytes: bytes, expect: tuple[str, str], argv: list[str], is_writer: bool
) -> None:
    lock = lock_dir / "machine.lock"
    lock.write_bytes(lock_bytes)

    res = _gate(bash, argv, lock_dir)

    assert res.code == 2, res.ctx()
    assert "RAN" not in res.out, "команда запущена при битом замке\n" + res.ctx()
    # ровно одна строка: нет ни reclassified, ни timed list not found, ничего лишнего
    assert res.raw_err.endswith(b"\n") and res.raw_err.count(b"\n") == 1, res.ctx()
    line = res.err[:-1]
    mode, text = expect
    if mode == "exact":
        assert line == text, res.ctx()
    else:
        assert line.startswith(text), res.ctx()
    if is_writer:
        assert lock.read_bytes() == lock_bytes, "grant/close изменил битый замок"
        assert _listing(lock_dir) == ["machine.lock"], "остался machine.lock.tmp"


# --- REDS 6. status: строки замка + числа нагрузки (~6 с на вызов) --------------------------------------------------

STATUS_CASES = [
    pytest.param(R1, "coordinator: c1 | since x\n" + "".join(f"{x}\n" for x in R1_LINES[1:]), 0, None, id="lock"),
    pytest.param(None, "machine.lock: none\n", 0, None, id="no_lock"),
    pytest.param(
        R1[:-1],  # замок R1 без `\n` в конце
        "coordinator: c1 | since x\n" + "".join(f"{x}\n" for x in R1_LINES[1:]),
        0,
        None,
        id="no_final_newline",
    ),
    pytest.param(
        b"coordinator: c1 | since x\nwindw: x\n",
        "coordinator: c1 | since x\nwindw: x\n",
        2,
        "machine_gate: malformed machine.lock:2: windw: x",
        id="malformed",
    ),
]


@pytest.mark.parametrize(("lock_bytes", "prefix", "code", "err_line"), STATUS_CASES)
def test_status_prints_lock_and_metrics(
    bash: str, lock_dir: Path, lock_bytes: bytes | None, prefix: str, code: int, err_line: str | None
) -> None:
    if lock_bytes is not None:
        (lock_dir / "machine.lock").write_bytes(lock_bytes)

    res = _gate(bash, ["status"], lock_dir)

    assert res.code == code, res.ctx()
    if err_line is not None:
        assert res.raw_err == err_line.encode("utf-8") + b"\n", res.ctx()

    # строки замка (или `machine.lock: none`) первыми, по порядку, без CR; две последние строки - числа нагрузки
    m = re.fullmatch(re.escape(prefix) + r"ram_free_mb: (\d+|n/a)\ncpu_load_pct: (\d+|n/a)\n", res.out, re.ASCII)
    assert m is not None, res.ctx()
    assert re.search(r"^ram_free_mb: (\d+|n/a)$", res.out, re.M)
    assert re.search(r"^cpu_load_pct: (\d+|n/a)$", res.out, re.M)

    ram, cpu = m.group(1), m.group(2)
    if sys.platform == "win32":
        assert ram.isdigit(), f"ram_free_mb на win32 должен быть числом: {res.ctx()}"
        assert int(ram) > 0, res.ctx()
    if cpu.isdigit():
        assert 0 <= int(cpu) <= 100, res.ctx()

    if lock_bytes is None:
        assert _listing(lock_dir) == [], "status создал файл в каталоге замка"
    else:
        assert (lock_dir / "machine.lock").read_bytes() == lock_bytes, "status изменил замок"


# --- стражи (зелёные и до правки) ---------------------------------------------------------------------------------

LIVE_LINES = [
    "coordinator: inspector-bottles-84 | since 2026-10-13 12:00",
    "waiting: inspector-bottles-3e | heavy | T3.9 post-merge Services/robot_comm/tests on main"
    " (after owner's word in its session) | ~3 min",
    "waiting: inspector-bottles-a4 | heavy | qex full reindex — only after the .ignore cause is found, evening"
    " | ~80 min",
    "stand: free",
]


def _live_bytes(variant: str) -> bytes:
    if variant == "lf":
        return "\n".join(LIVE_LINES).encode("utf-8") + b"\n"
    if variant == "crlf":
        # каждая строка \r\n и пустая строка \r\n после первой
        return "\r\n".join([LIVE_LINES[0], "", *LIVE_LINES[1:]]).encode("utf-8") + b"\r\n"
    if variant == "no_final_newline":
        return "\n".join(LIVE_LINES).encode("utf-8")
    raise AssertionError(variant)


@pytest.mark.parametrize("variant", ["lf", "crlf", "no_final_newline"])
def test_live_sample_lock_is_valid(bash: str, lock_dir: Path, variant: str) -> None:
    (lock_dir / "machine.lock").write_bytes(_live_bytes(variant))

    res = _gate(bash, ["heavy", "inspector-bottles-3e", "echo", "RAN"], lock_dir)

    assert res.code == 75, res.ctx()
    assert "NO WINDOW" in res.out, res.ctx()
    assert "RAN" not in res.out, res.ctx()
    assert res.raw_err == b"", res.ctx()


FREE_TEXT_LOCK = _lines(
    "coordinator: inspector-bottles-23 | since 2026-10-14 08:43",
    "window: inspector-bottles-5d | heavy | T3.7 matrix (J1–J5, one file), then e2e ~3 runs | until ~13:40",
    "waiting: layer-render-6-2-17 | quiet | A/B timing, 2 × 5 min — after the window above | ~10 min",
    "stand: free",
)


@pytest.mark.parametrize(
    ("kind", "code"),
    [pytest.param("light", 0, id="light"), pytest.param("heavy", 75, id="heavy")],
)
def test_coordinator_free_text_is_valid(bash: str, lock_dir: Path, kind: str, code: int) -> None:
    (lock_dir / "machine.lock").write_bytes(FREE_TEXT_LOCK)

    res = _gate(bash, [kind, "s9", "echo", "RAN"], lock_dir)

    assert res.code == code, res.ctx()
    assert res.raw_err == b"", res.ctx()
    if kind == "light":
        assert "RAN" in res.out, res.ctx()
    else:
        assert "NO WINDOW" in res.out, res.ctx()
        assert "RAN" not in res.out, res.ctx()
