"""Hazard-тесты автора Task 1.2 (machine_gate.sh grant / close / status и проверка формата замка).

Приёмочные тесты тестера — в test_machine_gate_lock.py; здесь только то, что они не покрывают: гонка двух grant,
CR/BOM/пробельные строки, границы minutes, виды окон, пустое <что>. Ожидаемые значения — литералы из
plans/2026-10-13_tooling-machine-gate-hook/task-1.2.md, не вычисляются из кода под тестом.

КАЖДЫЙ вызов гейта идёт с env MACHINE_LOCK_DIR = подкаталог tmp_path: живой machine.lock не трогается.
Всё, что может зависнуть, идёт с timeout.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import threading
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GATE = (ROOT / "scripts" / "machine_gate.sh").as_posix()
CALL_TIMEOUT = 60  # секунд на один вызов гейта (status — ~6 с)


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
    d = tmp_path / "lock"
    d.mkdir()
    return d


def _run(bash: str, args: list[str], lock_dir: Path) -> subprocess.CompletedProcess[bytes]:
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env["PYTHONUTF8"] = "1"
    env["MACHINE_LOCK_DIR"] = lock_dir.as_posix()  # без этого гейт трогает живой замок
    return subprocess.run(
        [bash, GATE, *args],
        capture_output=True,
        env=env,
        cwd=str(lock_dir.parent),
        timeout=CALL_TIMEOUT,
        check=False,
    )


def _run_sh(bash: str, script: str, lock_dir: Path) -> subprocess.CompletedProcess[bytes]:
    r"""Гейт из вложенного bash: ANSI-C кавычки `$'a\rb'` доносят CR/LF одним аргументом.

    Windows CreateProcess склеивает argv в строку, а Git Bash режет её по пробельным символам, включая CR и LF,
    поэтому через argv Python голый `a\rb` приходит как два аргумента (проверено: гейт пишет `a b`).
    """
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env["PYTHONUTF8"] = "1"
    env["MACHINE_LOCK_DIR"] = lock_dir.as_posix()
    env["GATE"] = GATE
    return subprocess.run(
        [bash, "-c", script], capture_output=True, env=env, cwd=str(lock_dir.parent), timeout=CALL_TIMEOUT, check=False
    )


def _lines(*lines: str) -> bytes:
    return ("\n".join(lines) + "\n").encode("utf-8")


R1_LINES = [
    "coordinator: c1 | since x",
    "waiting: s2 | heavy | a | ~3 min",
    "waiting: s22 | heavy | c | ~1 min",
    "waiting: s3 | heavy | b | ~80 min",
    "stand: free",
]
R1 = _lines(*R1_LINES)


def _hhmm_allowed(t0: datetime, t1: datetime, minutes: int) -> set[str]:
    allowed: set[str] = set()
    t = t0
    while t <= t1:
        allowed.add((t + timedelta(minutes=minutes)).strftime("%H:%M"))
        t += timedelta(minutes=1)
    return allowed


def _assert_valid_lock(bash: str, lock_dir: Path, session: str = "s9") -> None:
    """Замок годен: `light` проходит проверку формата и запускает команду (чужое окно quiet пропустило бы: 75)."""
    res = _run(bash, ["light", session, "echo", "RAN"], lock_dir)
    assert res.returncode == 0, (res.returncode, res.stdout, res.stderr)
    assert b"RAN" in res.stdout
    assert res.stderr == b""


# --- (a) гонка: несколько grant одновременно на одном замке ---------------------------------------------------------

# Допустимые строки отказа проигравшего (список отказов task-1.2.md, пп. 9 и 10).
RACE_REFUSALS = {
    b"machine_gate: a window is already open\n",
    b"machine_gate: machine.lock.tmp exists (another grant/close running, or a leftover)\n",
}
RACE_SESSIONS = ["s2", "s3", "s4"]
RACE_ROUNDS = 8


def test_concurrent_grants_exactly_one_wins(bash: str, lock_dir: Path) -> None:
    lock = lock_dir / "machine.lock"
    for round_no in range(RACE_ROUNDS):
        lock.write_bytes(R1)
        barrier = threading.Barrier(len(RACE_SESSIONS))
        results: dict[str, subprocess.CompletedProcess[bytes] | BaseException] = {}

        def worker(session: str, barrier: threading.Barrier = barrier, results: dict = results) -> None:
            try:
                barrier.wait(timeout=30)
                results[session] = _run(bash, ["grant", "c1", session, "heavy", "20", "race"], lock_dir)
            except BaseException as exc:  # noqa: BLE001 - тест фиксирует любой сбой потока как провал, а не глотает
                results[session] = exc

        threads = [threading.Thread(target=worker, args=(s,), daemon=True) for s in RACE_SESSIONS]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=CALL_TIMEOUT + 30)
        assert not any(t.is_alive() for t in threads), f"раунд {round_no}: вызов гейта завис"

        procs = {}
        for s in RACE_SESSIONS:
            r = results[s]
            assert not isinstance(r, BaseException), f"раунд {round_no}: {s}: {r!r}"
            procs[s] = r
        codes = sorted(p.returncode for p in procs.values())
        ctx = {s: (p.returncode, p.stdout, p.stderr) for s, p in procs.items()}
        assert codes == [0, 2, 2], f"раунд {round_no}: {ctx}"

        winners = [s for s, p in procs.items() if p.returncode == 0]
        for s, p in procs.items():
            if p.returncode == 2:
                assert p.stderr in RACE_REFUSALS, f"раунд {round_no}: {s}: {p.stderr!r}"
            else:
                assert p.stderr == b"", f"раунд {round_no}: {s}: {p.stderr!r}"

        text = lock.read_bytes().decode("utf-8")
        window_lines = [x for x in text.split("\n") if x.startswith("window: ")]
        assert len(window_lines) == 1, f"раунд {round_no}: {text!r}"
        assert re.fullmatch(rf"window: {winners[0]} \| heavy \| race \| until ~\d\d:\d\d", window_lines[0]), text
        assert text.endswith("\n") and "\r" not in text
        # проигравшие не потеряли чужие waiting; waiting победителя снят
        assert f"waiting: {winners[0]} |" not in text
        for line in R1_LINES:
            if line.startswith("waiting: ") and line.split(" | ")[0] != f"waiting: {winners[0]}":
                assert line in text.split("\n"), f"раунд {round_no}: пропала строка {line!r}\n{text!r}"
        assert sorted(p.name for p in lock_dir.iterdir()) == ["machine.lock"], f"раунд {round_no}: остался tmp"
        _assert_valid_lock(bash, lock_dir)


# BASH_ENV читает каждый неинтерактивный bash: функция date с паузой между первой проверкой grant и захватом
# machine.lock.tmp (окно гонки); файл-след задаёт тест через переменную DATE_MARK.
SLOW_DATE_ENV = """date() {
    echo called >> "$DATE_MARK"
    sleep 3
    command date "$@"
}
"""


def test_grant_does_not_write_from_a_stale_read(bash: str, lock_dir: Path, tmp_path: Path) -> None:
    """Детерминированная гонка: grant B прошёл проверки, пока окна нет, и застрял на `date`; grant A успел закончить.

    B обязан перечитать замок под защитой machine.lock.tmp и отказать (окно уже открыто), а не затереть окно A.
    Опирается на то, что `date` зовётся между проверками и захватом tmp; нет вызова `date` -> тест падает громко.
    """
    bash_env = tmp_path / "slow_date.sh"
    bash_env.write_bytes(SLOW_DATE_ENV.encode("utf-8"))
    mark = tmp_path / "date.called"
    lock = lock_dir / "machine.lock"
    lock.write_bytes(R1)

    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env["PYTHONUTF8"] = "1"
    env["MACHINE_LOCK_DIR"] = lock_dir.as_posix()
    env["BASH_ENV"] = bash_env.as_posix()
    env["DATE_MARK"] = mark.as_posix()
    slow = subprocess.Popen(
        [bash, GATE, "grant", "c1", "s3", "heavy", "20", "slow"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        cwd=str(lock_dir.parent),
    )
    try:
        deadline = 20.0
        waited = 0.0
        while not mark.exists() and waited < deadline:  # B дошёл до date
            threading.Event().wait(0.1)
            waited += 0.1
        assert mark.exists(), "grant не вызвал date: тест не проверяет гонку"
        fast = _run(bash, ["grant", "c1", "s2", "heavy", "20", "fast"], lock_dir)  # A: с обычным date
        out, err = slow.communicate(timeout=CALL_TIMEOUT)
    finally:
        if slow.poll() is None:
            slow.kill()
            slow.communicate()

    assert fast.returncode == 0, (fast.returncode, fast.stdout, fast.stderr)
    assert slow.returncode == 2, (slow.returncode, out, err)
    assert err == b"machine_gate: a window is already open\n", err
    text = lock.read_bytes().decode("utf-8")
    window_lines = [x for x in text.split("\n") if x.startswith("window: ")]
    assert len(window_lines) == 1 and window_lines[0].startswith("window: s2 | heavy | fast | until ~"), text
    assert "waiting: s3 |" in text, "waiting медленного grant снят, хотя окно ему не выдано"
    assert sorted(p.name for p in lock_dir.iterdir()) == ["machine.lock"]


# --- (b) status на замке с CRLF: ни одного \r в выводе ----------------------------------------------------------------


def test_status_on_crlf_lock_prints_no_cr(bash: str, lock_dir: Path) -> None:
    (lock_dir / "machine.lock").write_bytes(R1.replace(b"\n", b"\r\n"))

    res = _run(bash, ["status"], lock_dir)

    assert res.returncode == 0, (res.returncode, res.stdout, res.stderr)
    assert b"\r" not in res.stdout, res.stdout
    assert res.stdout.startswith(R1), res.stdout
    tail = res.stdout[len(R1) :].decode("utf-8")
    m = re.fullmatch(r"ram_free_mb: (\d+|n/a)\ncpu_load_pct: (\d+|n/a)\n", tail)
    assert m is not None, tail
    if sys.platform == "win32":  # без tr -d CR хвостовой CR сделал бы число нечитаемым -> n/a
        assert m.group(1).isdigit(), tail


# --- (c) строка из пробелов и BOM в начале файла -> malformed со своим номером ---------------------------------------

SPACES_LINE = "   "


@pytest.mark.parametrize("call", [["light", "s9", "echo", "RAN"], ["heavy", "s9", "echo", "RAN"], ["status"]])
def test_whitespace_only_line_is_malformed_with_its_number(bash: str, lock_dir: Path, call: list[str]) -> None:
    (lock_dir / "machine.lock").write_bytes(_lines("coordinator: c1 | since x", "stand: free", SPACES_LINE))

    res = _run(bash, call, lock_dir)

    assert res.returncode == 2, (res.returncode, res.stdout, res.stderr)
    assert res.stderr == b"machine_gate: malformed machine.lock:3:    \n", res.stderr
    assert b"RAN" not in res.stdout


def test_whitespace_only_line_with_crlf_is_malformed(bash: str, lock_dir: Path) -> None:
    # `\r` снимается, остаются пробелы: строка непустая -> ошибка (пустой считается только длина 0 после снятия `\r`)
    (lock_dir / "machine.lock").write_bytes(b"coordinator: c1 | since x\r\n \r\nstand: free\r\n")

    res = _run(bash, ["light", "s9", "echo", "RAN"], lock_dir)

    assert res.returncode == 2, (res.returncode, res.stdout, res.stderr)
    assert res.stderr == b"machine_gate: malformed machine.lock:2:  \n", res.stderr


@pytest.mark.parametrize("call", [["light", "s9", "echo", "RAN"], ["heavy", "s9", "echo", "RAN"]])
def test_bom_at_file_start_is_malformed_line_1(bash: str, lock_dir: Path, call: list[str]) -> None:
    (lock_dir / "machine.lock").write_bytes(b"\xef\xbb\xbfcoordinator: c1 | since x\nstand: free\n")

    res = _run(bash, call, lock_dir)

    assert res.returncode == 2, (res.returncode, res.stdout, res.stderr)
    assert res.stderr == b"machine_gate: malformed machine.lock:1: \xef\xbb\xbfcoordinator: c1 | since x\n", res.stderr
    assert b"RAN" not in res.stdout


def test_empty_lines_count_in_line_numbers(bash: str, lock_dir: Path) -> None:
    (lock_dir / "machine.lock").write_bytes(b"coordinator: c1 | since x\n\n\nwindw: s2\n")

    res = _run(bash, ["light", "s9", "echo", "RAN"], lock_dir)

    assert res.returncode == 2, (res.returncode, res.stdout, res.stderr)
    assert res.stderr == b"machine_gate: malformed machine.lock:4: windw: s2\n", res.stderr


def test_empty_lock_file_has_no_coordinator(bash: str, lock_dir: Path) -> None:
    (lock_dir / "machine.lock").write_bytes(b"")

    res = _run(bash, ["light", "s9", "echo", "RAN"], lock_dir)

    assert res.returncode == 2, (res.returncode, res.stdout, res.stderr)
    assert res.stderr == b"machine_gate: malformed machine.lock: no coordinator line\n", res.stderr


def test_malformed_crlf_line_is_reported_without_cr(bash: str, lock_dir: Path) -> None:
    (lock_dir / "machine.lock").write_bytes(b"coordinator: c1 | since x\r\nwindw: x\r\n")

    res = _run(bash, ["heavy", "s9", "echo", "RAN"], lock_dir)

    assert res.returncode == 2, (res.returncode, res.stdout, res.stderr)
    assert res.stderr == b"machine_gate: malformed machine.lock:2: windw: x\n", res.stderr


# --- (d) \r внутри <что> -> отказ 8 -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "what_literal",
    [pytest.param(r"$'a\rb'", id="cr"), pytest.param(r"$'a\nb'", id="lf"), pytest.param(r"$'a\r\nb'", id="crlf")],
)
def test_line_break_inside_what_is_refused(bash: str, lock_dir: Path, what_literal: str) -> None:
    lock = lock_dir / "machine.lock"
    lock.write_bytes(R1)

    res = _run_sh(bash, f'bash "$GATE" grant c1 s2 heavy 20 {what_literal}', lock_dir)

    assert res.returncode == 2, (res.returncode, res.stdout, res.stderr)
    assert res.stderr == b"machine_gate: what must not contain | or line breaks\n", res.stderr
    assert lock.read_bytes() == R1
    assert sorted(p.name for p in lock_dir.iterdir()) == ["machine.lock"]


# --- (e) границы minutes и виды окон ------------------------------------------------------------------------------


@pytest.mark.parametrize("minutes", [1, 600])
def test_minutes_boundaries_accepted(bash: str, lock_dir: Path, minutes: int) -> None:
    lock = lock_dir / "machine.lock"
    lock.write_bytes(R1)

    t0 = datetime.now().replace(second=0, microsecond=0)
    res = _run(bash, ["grant", "c1", "s2", "heavy", str(minutes), "edge"], lock_dir)
    t1 = datetime.now().replace(second=0, microsecond=0)

    assert res.returncode == 0, (res.returncode, res.stdout, res.stderr)
    assert res.stderr == b""
    text = lock.read_bytes().decode("utf-8")
    m = re.fullmatch(
        r"coordinator: c1 \| since x\nwindow: s2 \| heavy \| edge \| until ~(\d\d:\d\d)\n"
        r"waiting: s22 \| heavy \| c \| ~1 min\nwaiting: s3 \| heavy \| b \| ~80 min\nstand: free\n",
        text,
    )
    assert m is not None, text
    assert m.group(1) in _hhmm_allowed(t0, t1, minutes), (m.group(1), minutes)


@pytest.mark.parametrize("minutes", ["", "007", "1000", "-1", "+5", "5.5", "601", "0", "abc"])
def test_minutes_outside_range_refused(bash: str, lock_dir: Path, minutes: str) -> None:
    lock = lock_dir / "machine.lock"
    lock.write_bytes(R1)

    res = _run(bash, ["grant", "c1", "s2", "heavy", minutes, "x"], lock_dir)

    assert res.returncode == 2, (res.returncode, res.stdout, res.stderr)
    assert res.stderr == b"machine_gate: minutes must be 1..600\n", res.stderr
    assert lock.read_bytes() == R1


@pytest.mark.parametrize("kind", ["quiet", "stand", "heavy"])
def test_window_kinds_accepted_and_lock_stays_valid(bash: str, lock_dir: Path, kind: str) -> None:
    lock = lock_dir / "machine.lock"
    lock.write_bytes(R1)

    res = _run(bash, ["grant", "c1", "s2", kind, "30", "kind", "check"], lock_dir)

    assert res.returncode == 0, (res.returncode, res.stdout, res.stderr)
    assert res.stderr == b""
    text = lock.read_bytes().decode("utf-8")
    assert re.fullmatch(
        rf"coordinator: c1 \| since x\nwindow: s2 \| {kind} \| kind check \| until ~\d\d:\d\d\n"
        r"waiting: s22 \| heavy \| c \| ~1 min\nwaiting: s3 \| heavy \| b \| ~80 min\nstand: free\n",
        text,
    ), text
    _assert_valid_lock(bash, lock_dir, session="s2")


# --- (f) пустое <что> и замкнутый круг grant -> close -------------------------------------------------------------


def test_empty_what_is_accepted_and_close_restores_lock(bash: str, lock_dir: Path) -> None:
    lock = lock_dir / "machine.lock"
    lock.write_bytes(R1)

    res = _run(bash, ["grant", "c1", "s2", "heavy", "20", ""], lock_dir)

    assert res.returncode == 0, (res.returncode, res.stdout, res.stderr)
    assert res.stderr == b""
    text = lock.read_bytes().decode("utf-8")
    assert re.fullmatch(
        r"coordinator: c1 \| since x\nwindow: s2 \| heavy \|  \| until ~\d\d:\d\d\n"
        r"waiting: s22 \| heavy \| c \| ~1 min\nwaiting: s3 \| heavy \| b \| ~80 min\nstand: free\n",
        text,
    ), text
    _assert_valid_lock(bash, lock_dir)

    res = _run(bash, ["close", "c1", "s2"], lock_dir)

    assert res.returncode == 0, (res.returncode, res.stdout, res.stderr)
    assert res.stderr == b""
    # waiting: s2 grant снял, close его не возвращает; остальное прежнее
    assert lock.read_bytes() == _lines(R1_LINES[0], *R1_LINES[2:])
    assert sorted(p.name for p in lock_dir.iterdir()) == ["machine.lock"]


def test_free_text_with_punctuation_is_written_verbatim(bash: str, lock_dir: Path) -> None:
    lock = lock_dir / "machine.lock"
    lock.write_bytes(R1)
    what = "T3.7 (J1-J5, one file), then e2e ~3 runs: it's a/b \\ c"

    res = _run(bash, ["grant", "c1", "s2", "heavy", "20", what], lock_dir)

    assert res.returncode == 0, (res.returncode, res.stdout, res.stderr)
    text = lock.read_bytes().decode("utf-8")
    assert f"window: s2 | heavy | {what} | until ~" in text, text
    _assert_valid_lock(bash, lock_dir)


def test_grant_on_crlf_lock_writes_lf_only(bash: str, lock_dir: Path) -> None:
    lock = lock_dir / "machine.lock"
    lock.write_bytes(R1.replace(b"\n", b"\r\n") + b"\r\n")  # + пустая строка CRLF в конце

    res = _run(bash, ["grant", "c1", "s2", "heavy", "20", "x"], lock_dir)

    assert res.returncode == 0, (res.returncode, res.stdout, res.stderr)
    data = lock.read_bytes()
    assert b"\r" not in data, data
    assert data.endswith(b"stand: free\n\n"), data  # пустая строка сохранена, LF


def test_close_keeps_other_sessions_waiting_and_blank_lines(bash: str, lock_dir: Path) -> None:
    lock = lock_dir / "machine.lock"
    lock.write_bytes(
        b"coordinator: c1 | since x\r\nwindow: s2 | heavy | x | until ~23:59\r\n\r\n"
        b"waiting: s2 | heavy | again | ~5 min\r\n"
    )

    res = _run(bash, ["close", "c1", "s2"], lock_dir)

    assert res.returncode == 0, (res.returncode, res.stdout, res.stderr)
    assert lock.read_bytes() == b"coordinator: c1 | since x\n\nwaiting: s2 | heavy | again | ~5 min\n"
