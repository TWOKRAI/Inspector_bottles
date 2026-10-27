"""Task 1.1 плана tooling-gate-self-service: самообслуживание окон и merge-слот в `scripts/machine_gate.sh`.

Подкоманды `request` / `release` / `wait` / `extend` / `merge-begin` / `merge-end`, строка замка `merging:`, строка
`OVERDUE` в `status`/`wait`, автовыдача (`promote`), запись замка через `machine.lock.tmp` (`lock_edit`).
Контракт — plans/2026-10-27_tooling-gate-self-service/plan.md (разделы DESIGN, «Тексты и порядок отказов», REDS R1-R15,
«Инъекции»). Ожидаемые значения здесь — литералы из этого файла плана, не вычисляются из кода под тестом.
Слепой набор: написан до реализации, на старом скрипте ожидаемо красный (старый скрипт не знает новых подкоманд).

Тесты зовут гейт ``scripts/machine_gate.sh`` через subprocess (Git Bash). КАЖДЫЙ вызов идёт с env ``MACHINE_LOCK_DIR`` =
свежий подкаталог ``tmp_path``: живой ``D:/PROJECT_INNOTECH/Inspector_vision/machine.lock`` не читается и не
переписывается. Всегда ``TZ=UTC``, ``MACHINE_GATE_NOW_EPOCH`` (1798329600 = 00:00, 1798330200 = 00:10),
``MACHINE_GATE_POLL_SEC=1``. ``MACHINE_GATE_TMP_WAIT_SEC`` ставится только там, где он нужен.

Отклонения от плана и допущения (см. отчёт тестера):
  * ``newline_in_what`` передаёт ``"a\\nb c"`` (с пробелом), как test_machine_gate_lock.py: Windows CreateProcess
    склеивает argv, голый ``a\\nb`` Git Bash режет на два аргумента.
  * ``TIMEOUT`` ищется в stdout+stderr вместе: план не говорит, в какой поток он идёт.
  * Детерминированные гонки и сбои ``mv`` делаются функцией ``mv`` в ``BASH_ENV`` (её читает каждый неинтерактивный
    bash, в том числе гейт); сигналы TERM шлёт обёртка ``bash -c`` изнутри msys (Popen.terminate() на Windows убивает
    процесс без trap и ничего бы не доказал).
  * ``pytest-timeout`` в venv нет: всё, что может зависнуть, идёт с timeout у subprocess / join-дедлайном.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GATE = (ROOT / "scripts" / "machine_gate.sh").as_posix()

REFUSE = "machine_gate: "
CALL_TIMEOUT = 60  # секунд на один вызов гейта (status — ~6 с)

# Подменённое «сейчас» (TZ=UTC): литералы из плана; остальные — 00:00 плюс часы и минуты.
NOW_0000 = 1798329600
NOW_0010 = 1798330200
NOW_2355 = 1798329300  # 23:55 предыдущих суток
NOW_2350 = 1798329000  # 23:50 предыдущих суток
NOW_0809 = 1798358940  # 08:09
NOW_0908 = 1798362480  # 09:08
NOW_1337 = 1798378620  # 13:37

TMP_BUSY = "machine.lock.tmp exists (another grant/close running, or a leftover)"
BUSY = "cannot replace machine.lock (busy), retry"


# --- bash: копия _git_bash() из test_machine_gate_lock.py (на Windows bash из Python = WSL) -------------------------


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
    """Свежий подкаталог: сюда пишется замок, сюда же смотрит MACHINE_LOCK_DIR."""
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
    elapsed: float = 0.0

    def ctx(self) -> str:
        return f"код={self.code}\nstdout={self.out!r}\nstderr={self.err!r}"

    @property
    def both(self) -> str:
        return self.out + self.err


def _env(lock_dir: Path, now: int | None, extra: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ)
    for k in ("PYTHONPATH", "BASH_ENV", "MACHINE_GATE_TMP_WAIT_SEC", "MACHINE_GATE_NOW_EPOCH"):
        env.pop(k, None)
    env["PYTHONUTF8"] = "1"
    env["TZ"] = "UTC"
    env["MACHINE_LOCK_DIR"] = lock_dir.as_posix()  # без этого гейт трогает живой замок
    env["MACHINE_GATE_POLL_SEC"] = "1"
    if now is not None:
        env["MACHINE_GATE_NOW_EPOCH"] = str(now)
    env.update(extra or {})
    return env


def _gate(
    bash: str,
    args: list[str],
    lock_dir: Path,
    *,
    now: int | None = NOW_0000,
    env: dict[str, str] | None = None,
    timeout: float = CALL_TIMEOUT,
) -> Out:
    t0 = time.monotonic()
    p = subprocess.run(
        [bash, GATE, *args],
        capture_output=True,  # байты: \r в выводе должен быть виден
        env=_env(lock_dir, now, env),
        cwd=str(lock_dir.parent),
        timeout=timeout,
        check=False,
    )
    return Out(
        code=p.returncode,
        out=p.stdout.decode("utf-8", errors="replace"),
        err=p.stderr.decode("utf-8", errors="replace"),
        raw_err=p.stderr,
        elapsed=time.monotonic() - t0,
    )


def _spawn(
    bash: str,
    args: list[str],
    lock_dir: Path,
    *,
    now: int | None = NOW_0000,
    env: dict[str, str] | None = None,
    stdout=None,
) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [bash, GATE, *args],
        stdout=stdout if stdout is not None else subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_env(lock_dir, now, env),
        cwd=str(lock_dir.parent),
    )


def _finish(p: subprocess.Popen[bytes], timeout: float = 40.0) -> Out:
    """Дождаться процесса; завис — убить и упасть с понятным сообщением."""
    try:
        out, err = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        p.kill()
        p.communicate()
        pytest.fail(f"вызов гейта завис дольше {timeout} с (убит)")
    return Out(
        code=p.returncode,
        out=(out or b"").decode("utf-8", errors="replace"),
        err=err.decode("utf-8", errors="replace"),
        raw_err=err,
    )


def _kill(p: subprocess.Popen[bytes]) -> None:
    if p.poll() is None:
        p.kill()
        p.communicate()


def _wait_until(pred: Callable[[], bool], timeout: float, step: float = 0.1) -> bool:
    def safe() -> bool:
        try:
            return pred()
        except OSError:  # замок в момент подмены (mv) на Windows недоступен на чтение
            return False

    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if safe():
            return True
        time.sleep(step)
    return safe()


def _listing(d: Path) -> list[str]:
    return sorted(p.name for p in d.iterdir())


def _lines(*lines: str) -> bytes:
    """Замок с LF, `\\n` после последней строки."""
    return ("\n".join(lines) + "\n").encode("utf-8")


def _snap(lock: Path) -> tuple[bytes, int, int]:
    st = os.stat(lock)
    return lock.read_bytes(), st.st_ino, st.st_mtime_ns


def _assert_untouched(lock: Path, snap: tuple[bytes, int, int], lock_dir: Path) -> None:
    """Замок побайтно прежний и тот же файл (inode, mtime): быстрый путь / отказ не пишет и не берёт tmp."""
    now_snap = _snap(lock)
    assert now_snap[0] == snap[0], f"замок изменён:\n{now_snap[0]!r}\nбыло:\n{snap[0]!r}"
    assert now_snap[1] == snap[1], "замок заменён (inode другой), хотя запись не нужна"
    assert now_snap[2] == snap[2], "замок переписан (mtime другой), хотя запись не нужна"
    assert _listing(lock_dir) == ["machine.lock"], f"лишние файлы: {_listing(lock_dir)}"


def _refusal(res: Out, text: str) -> None:
    """Код 2 и в stderr ровно одна строка `machine_gate: <text>`."""
    assert res.code == 2, res.ctx()
    assert res.raw_err == (REFUSE + text).encode("utf-8") + b"\n", res.ctx()


def _usage(res: Out, text: str) -> None:
    """Код 2 и ровно одна строка usage без префикса (как у grant)."""
    assert res.code == 2, res.ctx()
    assert res.raw_err == text.encode("utf-8") + b"\n", res.ctx()


def _assert_valid_lock(bash: str, lock_dir: Path) -> None:
    """Замок годен: `light` проходит проверку формата и запускает команду."""
    res = _gate(bash, ["light", "s9", "echo", "RAN"], lock_dir)
    assert res.code == 0, res.ctx()
    assert "RAN" in res.out, res.ctx()
    assert res.raw_err == b"", res.ctx()


# --- замки --------------------------------------------------------------------------------------------------------

COORD = "coordinator: c1 | since x"
STAND = "stand: free"
W_S1 = "window: s1 | heavy | a | until ~00:05"  # окно s1
WAIT_S2 = "waiting: s2 | heavy | b | ~10 min"
WAIT_S3 = "waiting: s3 | heavy | c | ~20 min"
WAIT_S4 = "waiting: s4 | heavy | d | ~30 min"
MERGING_S1 = "merging: s1 | feat/x | since 00:00"

BASE = _lines(COORD)
BUSY_LOCK = _lines(COORD, W_S1, WAIT_S2, STAND)  # окно s1, s2 в очереди


def _put(lock_dir: Path, data: bytes | None) -> Path:
    lock = lock_dir / "machine.lock"
    if data is not None:
        lock.write_bytes(data)
    return lock


def _granted(hhmm: str) -> str:
    return f"GRANTED until ~{hhmm}\n"


# --- BASH_ENV: функция mv --------------------------------------------------------------------------------------------

# Считает вызовы mv (одна строка в файле на вызов) и пропускает дальше.
MV_COUNT_ENV = """mv() {
    echo x >> "$MV_COUNT_FILE"
    command mv "$@"
}
"""

# Первые MV_FAIL_N вызовов mv падают (как «Device or resource busy» у читателя), следующие проходят.
MV_FAIL_ENV = """mv() {
    local n=0
    [ -e "$MV_FAIL_FILE" ] && n=$(wc -l < "$MV_FAIL_FILE")
    echo x >> "$MV_FAIL_FILE"
    if [ "$n" -lt "$MV_FAIL_N" ]; then
        return 1
    fi
    command mv "$@"
}
"""

# Первый вызов mv (mkdir маркера - атомарно) создаёт маркер и ждёт go-файл (не дольше 10 с); остальные идут сразу.
# Пока первый держит mv, он держит и machine.lock.tmp: окно гонки открыто детерминированно.
MV_HOLD_ENV = """mv() {
    local i
    if mkdir "$MV_MARK" 2>/dev/null; then
        for ((i = 0; i < 200; i++)); do
            [ -e "$MV_GO" ] && break
            sleep 0.05
        done
    fi
    command mv "$@"
}
"""


def _bash_env(tmp_path: Path, name: str, body: str) -> str:
    f = tmp_path / name
    f.write_bytes(body.encode("utf-8"))
    return f.as_posix()


def _count(path: Path) -> int:
    return len(path.read_text().splitlines()) if path.exists() else 0


# =====================================================================================================================
# R1. request: выдача и очередь
# =====================================================================================================================


@pytest.mark.parametrize("kind", ["heavy", "quiet", "stand"])
def test_request_grants_window_right_after_coordinator(bash: str, lock_dir: Path, kind: str) -> None:
    lock = _put(lock_dir, _lines(COORD, STAND))

    res = _gate(bash, ["request", "s1", kind, "5", "a"], lock_dir)

    assert res.code == 0, res.ctx()
    assert res.out == _granted("00:05"), res.ctx()
    assert lock.read_bytes() == _lines(COORD, f"window: s1 | {kind} | a | until ~00:05", STAND)
    assert _listing(lock_dir) == ["machine.lock"]


def test_request_queues_behind_foreign_window_and_appends_waiting_last(bash: str, lock_dir: Path) -> None:
    lock = _put(lock_dir, _lines(COORD, W_S1, STAND))

    res = _gate(bash, ["request", "s2", "heavy", "10", "b"], lock_dir)

    assert res.code == 0, res.ctx()
    assert res.out == "QUEUED position 1\n", res.ctx()
    assert lock.read_bytes() == _lines(COORD, W_S1, STAND, WAIT_S2)
    assert _listing(lock_dir) == ["machine.lock"]


def test_r1_chain_grant_then_queue_keeps_lock_valid(bash: str, lock_dir: Path) -> None:
    lock = _put(lock_dir, BASE)

    first = _gate(bash, ["request", "s1", "heavy", "5", "a"], lock_dir)
    after_first = lock.read_bytes()
    second = _gate(bash, ["request", "s2", "heavy", "10", "b"], lock_dir)

    assert (first.code, first.out) == (0, _granted("00:05")), first.ctx()
    assert after_first == _lines(COORD, W_S1)
    assert (second.code, second.out) == (0, "QUEUED position 1\n"), second.ctx()
    assert lock.read_bytes() == _lines(COORD, W_S1, WAIT_S2)
    _assert_valid_lock(bash, lock_dir)


def test_request_waiting_goes_after_every_existing_line(bash: str, lock_dir: Path) -> None:
    """Новая waiting - в конец файла: после window, merging, stand и чужих waiting."""
    lock = _put(lock_dir, _lines(COORD, W_S1, MERGING_S1, STAND, WAIT_S3))

    res = _gate(bash, ["request", "s2", "heavy", "10", "b"], lock_dir)

    assert (res.code, res.out) == (0, "QUEUED position 2\n"), res.ctx()
    assert lock.read_bytes() == _lines(COORD, W_S1, MERGING_S1, STAND, WAIT_S3, WAIT_S2)


def test_request_joins_what_words_with_single_space(bash: str, lock_dir: Path) -> None:
    lock = _put(lock_dir, BASE)

    res = _gate(bash, ["request", "s1", "heavy", "5", "T3.9", "two", "words"], lock_dir)

    assert (res.code, res.out) == (0, _granted("00:05")), res.ctx()
    assert lock.read_bytes() == _lines(COORD, "window: s1 | heavy | T3.9 two words | until ~00:05")


@pytest.mark.parametrize(
    ("minutes", "until"),
    [("1", "00:01"), ("59", "00:59"), ("60", "01:00"), ("600", "10:00")],
)
def test_request_minutes_boundaries(bash: str, lock_dir: Path, minutes: str, until: str) -> None:
    lock = _put(lock_dir, BASE)

    res = _gate(bash, ["request", "s1", "heavy", minutes, "a"], lock_dir)

    assert (res.code, res.out) == (0, _granted(until)), res.ctx()
    assert lock.read_bytes() == _lines(COORD, f"window: s1 | heavy | a | until ~{until}")


def test_request_until_follows_substituted_clock(bash: str, lock_dir: Path) -> None:
    lock = _put(lock_dir, BASE)

    res = _gate(bash, ["request", "s1", "heavy", "5", "a"], lock_dir, now=NOW_1337)

    assert (res.code, res.out) == (0, _granted("13:42")), res.ctx()
    assert lock.read_bytes() == _lines(COORD, "window: s1 | heavy | a | until ~13:42")


def test_request_until_wraps_past_midnight(bash: str, lock_dir: Path) -> None:
    lock = _put(lock_dir, BASE)

    res = _gate(bash, ["request", "s1", "heavy", "20", "a"], lock_dir, now=NOW_2350)

    assert (res.code, res.out) == (0, _granted("00:10")), res.ctx()
    assert lock.read_bytes() == _lines(COORD, "window: s1 | heavy | a | until ~00:10")


def test_request_at_0809_uses_decimal_arithmetic(bash: str, lock_dir: Path) -> None:
    """Инъекция (и): час 08 / минуты 09 не должны читаться как восьмеричные."""
    lock = _put(lock_dir, BASE)

    res = _gate(bash, ["request", "s1", "heavy", "10", "a"], lock_dir, now=NOW_0809)

    assert (res.code, res.out) == (0, _granted("08:19")), res.ctx()
    assert lock.read_bytes() == _lines(COORD, "window: s1 | heavy | a | until ~08:19")


# =====================================================================================================================
# R5. повторный request: идемпотентность
# =====================================================================================================================


@pytest.mark.parametrize(("session", "position"), [("s2", 1), ("s3", 2)])
def test_repeated_request_with_own_waiting_leaves_lock_untouched(
    bash: str, lock_dir: Path, session: str, position: int
) -> None:
    lock = _put(lock_dir, _lines(COORD, W_S1, WAIT_S2, WAIT_S3))
    snap = _snap(lock)
    kind_what = {"s2": ("10", "b"), "s3": ("20", "c")}[session]

    res = _gate(bash, ["request", session, "heavy", *kind_what], lock_dir)

    assert (res.code, res.out) == (0, f"QUEUED position {position}\n"), res.ctx()
    _assert_untouched(lock, snap, lock_dir)


@pytest.mark.parametrize(
    "args",
    [
        pytest.param(["request", "s1", "heavy", "5", "a"], id="same_args"),
        pytest.param(["request", "s1", "quiet", "30", "other text"], id="other_args"),
    ],
)
def test_request_with_own_window_returns_same_until_without_write(bash: str, lock_dir: Path, args: list[str]) -> None:
    lock = _put(lock_dir, _lines(COORD, W_S1, WAIT_S2))
    snap = _snap(lock)

    res = _gate(bash, args, lock_dir)

    assert (res.code, res.out) == (0, _granted("00:05")), res.ctx()
    _assert_untouched(lock, snap, lock_dir)


def test_request_position_counts_own_line_after_promote(bash: str, lock_dir: Path) -> None:
    """Нет окна, перед s3 стоит s2: request s3 выдаёт окно s2 (первая waiting), а s3 остаётся первой в очереди."""
    lock = _put(lock_dir, _lines(COORD, WAIT_S2))

    res = _gate(bash, ["request", "s3", "heavy", "20", "c"], lock_dir)

    assert (res.code, res.out) == (0, "QUEUED position 1\n"), res.ctx()
    assert lock.read_bytes() == _lines(COORD, "window: s2 | heavy | b | until ~00:10", WAIT_S3)


# =====================================================================================================================
# R2, R3, R3b, R4. release
# =====================================================================================================================


def test_release_hands_window_to_next_in_queue(bash: str, lock_dir: Path) -> None:
    lock = _put(lock_dir, _lines(COORD, W_S1, WAIT_S2, STAND))

    res = _gate(bash, ["release", "s1"], lock_dir)

    assert res.code == 0, res.ctx()
    assert res.out == "RELEASED\nNEXT s2 until ~00:10\n", res.ctx()
    assert lock.read_bytes() == _lines(COORD, "window: s2 | heavy | b | until ~00:10", STAND)
    assert _listing(lock_dir) == ["machine.lock"]


def test_wait_after_release_reports_granted(bash: str, lock_dir: Path) -> None:
    lock = _put(lock_dir, _lines(COORD, "window: s2 | heavy | b | until ~00:10"))
    snap = _snap(lock)

    res = _gate(bash, ["wait", "s2", "--timeout", "0"], lock_dir)

    assert (res.code, res.out) == (0, _granted("00:10")), res.ctx()
    _assert_untouched(lock, snap, lock_dir)


def test_release_without_queue_prints_only_released(bash: str, lock_dir: Path) -> None:
    lock = _put(lock_dir, _lines(COORD, W_S1, STAND))

    res = _gate(bash, ["release", "s1"], lock_dir)

    assert (res.code, res.out) == (0, "RELEASED\n"), res.ctx()
    assert lock.read_bytes() == _lines(COORD, STAND)


@pytest.mark.parametrize(
    "lock_bytes",
    [
        pytest.param(_lines(COORD, W_S1, WAIT_S2), id="foreign_window_s3_has_nothing"),
        pytest.param(_lines(COORD, WAIT_S2), id="no_window_s3_has_nothing"),
    ],
)
def test_release_by_stranger_is_refused_and_keeps_everything(bash: str, lock_dir: Path, lock_bytes: bytes) -> None:
    """Инъекция (а): release снимает любое window без проверки владельца."""
    lock = _put(lock_dir, lock_bytes)
    snap = _snap(lock)

    res = _gate(bash, ["release", "s3"], lock_dir)

    _refusal(res, "no window or request of this session")
    assert res.out == "", res.ctx()
    _assert_untouched(lock, snap, lock_dir)


def test_release_of_queued_request_cancels_it_and_keeps_foreign_window(bash: str, lock_dir: Path) -> None:
    """R3b и инъекция (л): CANCELLED снимает только свою waiting, чужое окно цело."""
    lock = _put(lock_dir, _lines(COORD, W_S1, WAIT_S2, STAND, WAIT_S3))

    res = _gate(bash, ["release", "s2"], lock_dir)

    assert (res.code, res.out) == (0, "CANCELLED\n"), res.ctx()
    assert lock.read_bytes() == _lines(COORD, W_S1, STAND, WAIT_S3)
    assert _listing(lock_dir) == ["machine.lock"]


def test_release_cancel_removes_all_own_waiting_lines(bash: str, lock_dir: Path) -> None:
    other_s2 = "waiting: s2 | quiet | second | ~5 min"
    lock = _put(lock_dir, _lines(COORD, W_S1, WAIT_S2, WAIT_S3, other_s2))

    res = _gate(bash, ["release", "s2"], lock_dir)

    assert (res.code, res.out) == (0, "CANCELLED\n"), res.ctx()
    assert lock.read_bytes() == _lines(COORD, W_S1, WAIT_S3)


def test_queue_is_fifo_on_release(bash: str, lock_dir: Path) -> None:
    """R4 и инъекция (б): окно уходит ПЕРВОЙ waiting, а не последней."""
    lock = _put(lock_dir, _lines(COORD, W_S1))

    positions = [
        _gate(bash, ["request", "s2", "heavy", "10", "b"], lock_dir).out,
        _gate(bash, ["request", "s3", "heavy", "20", "c"], lock_dir).out,
        _gate(bash, ["request", "s4", "heavy", "30", "d"], lock_dir).out,
    ]
    assert positions == ["QUEUED position 1\n", "QUEUED position 2\n", "QUEUED position 3\n"]
    assert lock.read_bytes() == _lines(COORD, W_S1, WAIT_S2, WAIT_S3, WAIT_S4)

    res = _gate(bash, ["release", "s1"], lock_dir)

    assert (res.code, res.out) == (0, "RELEASED\nNEXT s2 until ~00:10\n"), res.ctx()
    assert lock.read_bytes() == _lines(COORD, "window: s2 | heavy | b | until ~00:10", WAIT_S3, WAIT_S4)


def test_request_promotes_first_waiting_by_order_when_no_window(bash: str, lock_dir: Path) -> None:
    waiting_a = "waiting: a | heavy | x | ~3 min"
    waiting_b = "waiting: b | quiet | y | ~80 min"
    lock = _put(lock_dir, _lines(COORD, waiting_a, waiting_b))

    res = _gate(bash, ["request", "c", "heavy", "5", "z"], lock_dir)

    assert res.code == 0, res.ctx()
    assert res.out == "QUEUED position 2\n", res.ctx()
    assert lock.read_bytes() == _lines(
        COORD, "window: a | heavy | x | until ~00:03", waiting_b, "waiting: c | heavy | z | ~5 min"
    )


# =====================================================================================================================
# R12 и R15. promote: срок из 4-го поля; wait выдаёт окно при пустом окне
# =====================================================================================================================


@pytest.mark.parametrize(
    ("fourth", "until"),
    [
        pytest.param("after owner", "01:00", id="no_minutes_default_60"),
        pytest.param("~900 min", "01:00", id="over_600_default_60"),
        pytest.param("~601 min", "01:00", id="601_default_60"),
        pytest.param("~600 min", "10:00", id="600_kept"),
        pytest.param("~3 min", "00:03", id="3"),
        pytest.param("~25 min", "00:25", id="25"),
        pytest.param("~0 min", "01:00", id="zero_default_60"),
        pytest.param("~05 min", "01:00", id="leading_zero_default_60"),
        pytest.param("~1000 min", "01:00", id="four_digits_default_60"),
    ],
)
def test_promote_takes_minutes_from_fourth_field(bash: str, lock_dir: Path, fourth: str, until: str) -> None:
    """Инъекция (з): N жёстко 30. Строка с непонятным сроком не пропускается: очередь не клинится."""
    lock = _put(lock_dir, _lines(COORD, f"waiting: s | heavy | x | {fourth}"))

    res = _gate(bash, ["wait", "s", "--timeout", "0"], lock_dir)

    assert (res.code, res.out) == (0, _granted(until)), res.ctx()
    assert lock.read_bytes() == _lines(COORD, f"window: s | heavy | x | until ~{until}")


def test_promote_until_wraps_past_midnight(bash: str, lock_dir: Path) -> None:
    lock = _put(lock_dir, _lines(COORD, "waiting: s | heavy | x | ~20 min"))

    res = _gate(bash, ["wait", "s", "--timeout", "0"], lock_dir, now=NOW_2350)

    assert (res.code, res.out) == (0, _granted("00:10")), res.ctx()
    assert lock.read_bytes() == _lines(COORD, "window: s | heavy | x | until ~00:10")


def test_wait_promotes_when_no_window(bash: str, lock_dir: Path) -> None:
    """R15 и инъекция (к): замок после close координатора - waiting есть, окна нет."""
    lock = _put(lock_dir, _lines(COORD, WAIT_S2))

    res = _gate(bash, ["wait", "s2", "--timeout", "0"], lock_dir)

    assert (res.code, res.out) == (0, _granted("00:10")), res.ctx()
    assert lock.read_bytes() == _lines(COORD, "window: s2 | heavy | b | until ~00:10")
    assert _listing(lock_dir) == ["machine.lock"]


def test_request_with_own_waiting_and_no_window_grants(bash: str, lock_dir: Path) -> None:
    lock = _put(lock_dir, _lines(COORD, WAIT_S2))

    res = _gate(bash, ["request", "s2", "heavy", "10", "b"], lock_dir)

    assert (res.code, res.out) == (0, _granted("00:10")), res.ctx()
    assert lock.read_bytes() == _lines(COORD, "window: s2 | heavy | b | until ~00:10")


def test_merge_end_does_not_promote_but_wait_does(bash: str, lock_dir: Path) -> None:
    """merge-end освобождает слот и не трогает окна/очередь; пара - тот же замок, где wait окно выдаёт."""
    lock = _put(lock_dir, _lines(COORD, MERGING_S1, WAIT_S2))

    res = _gate(bash, ["merge-end", "s1"], lock_dir)

    assert (res.code, res.out) == (0, "MERGE SLOT FREE\n"), res.ctx()
    assert lock.read_bytes() == _lines(COORD, WAIT_S2), "merge-end выдал окно"

    paired = _gate(bash, ["wait", "s2", "--timeout", "0"], lock_dir)

    assert (paired.code, paired.out) == (0, _granted("00:10")), paired.ctx()
    assert lock.read_bytes() == _lines(COORD, "window: s2 | heavy | b | until ~00:10")


def test_promote_inserts_window_before_merging_line(bash: str, lock_dir: Path) -> None:
    lock = _put(lock_dir, _lines(COORD, MERGING_S1, STAND, WAIT_S2))

    res = _gate(bash, ["wait", "s2", "--timeout", "0"], lock_dir)

    assert (res.code, res.out) == (0, _granted("00:10")), res.ctx()
    assert lock.read_bytes() == _lines(COORD, "window: s2 | heavy | b | until ~00:10", MERGING_S1, STAND)


def test_close_does_not_promote(bash: str, lock_dir: Path) -> None:
    """Старый контракт: close снимает окно, waiting остаётся на месте и окно не выдаётся (promote только у новых)."""
    lock = _put(lock_dir, _lines(COORD, W_S1, WAIT_S2))

    res = _gate(bash, ["close", "c1", "s1"], lock_dir)

    assert res.code == 0, res.ctx()
    assert lock.read_bytes() == _lines(COORD, WAIT_S2)


# =====================================================================================================================
# R6. параллельные request
# =====================================================================================================================

# Исходы двух параллельных request (s1: heavy 5 a; s2: heavy 10 b): выиграл s1 или s2.
RACE_S1_WINS = _lines(COORD, W_S1, WAIT_S2)
RACE_S2_WINS = _lines(COORD, "window: s2 | heavy | b | until ~00:10", "waiting: s1 | heavy | a | ~5 min")
RACE_ROUNDS = 4


def test_parallel_requests_keep_lock_valid_and_both_sessions(bash: str, lock_dir: Path) -> None:
    lock = _put(lock_dir, BASE)
    for round_no in range(RACE_ROUNDS):
        lock.write_bytes(BASE)
        barrier = threading.Barrier(2)
        results: dict[str, Out | BaseException] = {}

        def worker(session: str, minutes: str, what: str, barrier=barrier, results=results) -> None:
            try:
                barrier.wait(timeout=30)
                results[session] = _gate(bash, ["request", session, "heavy", minutes, what], lock_dir)
            except BaseException as exc:  # noqa: BLE001 - сбой потока фиксируется как провал, не глотается
                results[session] = exc

        threads = [
            threading.Thread(target=worker, args=("s1", "5", "a"), daemon=True),
            threading.Thread(target=worker, args=("s2", "10", "b"), daemon=True),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=CALL_TIMEOUT + 30)
        assert not any(t.is_alive() for t in threads), f"раунд {round_no}: вызов гейта завис"

        r1, r2 = results["s1"], results["s2"]
        assert isinstance(r1, Out) and isinstance(r2, Out), f"раунд {round_no}: {results!r}"
        assert (r1.code, r2.code) == (0, 0), f"раунд {round_no}: {r1.ctx()}\n---\n{r2.ctx()}"
        text = lock.read_bytes()
        if text == RACE_S1_WINS:
            assert (r1.out, r2.out) == (_granted("00:05"), "QUEUED position 1\n"), f"раунд {round_no}"
        else:
            assert text == RACE_S2_WINS, f"раунд {round_no}: потеряна сессия или два окна:\n{text!r}"
            assert (r1.out, r2.out) == ("QUEUED position 1\n", _granted("00:10")), f"раунд {round_no}"
        assert _listing(lock_dir) == ["machine.lock"], f"раунд {round_no}: остался tmp"
        _assert_valid_lock(bash, lock_dir)


def test_stale_read_is_not_written_back(bash: str, lock_dir: Path, tmp_path: Path) -> None:
    """Детерминированная гонка (инъекция (в): нет set -C; нет перечитывания под tmp).

    A дошёл до mv и держит его (вместе с tmp). B стартует, пока замок ещё без окна, и обязан ждать tmp, а потом
    перечитать замок и встать в очередь. Без O_EXCL B пишет сразу, потом A затирает его запись; без перечитывания
    B пишет по старому чтению и затирает окно A.
    """
    lock = _put(lock_dir, BASE)
    mark = tmp_path / "mv.mark"
    go = tmp_path / "mv.go"
    env = {
        "BASH_ENV": _bash_env(tmp_path, "hold_mv.sh", MV_HOLD_ENV),
        "MV_MARK": mark.as_posix(),
        "MV_GO": go.as_posix(),
    }
    a_out = tmp_path / "a.out"
    b: subprocess.Popen[bytes] | None = None
    with open(a_out, "wb") as fa:
        a = _spawn(bash, ["request", "s1", "heavy", "5", "a"], lock_dir, env=env, stdout=fa)
        try:
            assert _wait_until(mark.exists, 30), "A не дошёл до mv: тест не проверяет гонку"
            b = _spawn(bash, ["request", "s2", "heavy", "10", "b"], lock_dir, env=env)
            time.sleep(1.5)
            assert b.poll() is None, "B завершился, не дождавшись tmp, пока A держит запись"
            go.write_bytes(b"go")
            res_b = _finish(b)
            res_a = _finish(a)
        finally:
            go.write_bytes(b"go")  # не оставить A висеть при падении
            _kill(a)
            if b is not None:
                _kill(b)

    assert res_a.code == 0, res_a.ctx()
    assert res_b.code == 0, res_b.ctx()
    assert a_out.read_text() == _granted("00:05")
    assert res_b.out == "QUEUED position 1\n", res_b.ctx()
    assert lock.read_bytes() == _lines(COORD, W_S1, WAIT_S2)
    assert _listing(lock_dir) == ["machine.lock"]


def test_request_prints_result_only_after_mv(bash: str, lock_dir: Path, tmp_path: Path) -> None:
    lock = _put(lock_dir, BASE)
    mark = tmp_path / "mv.mark"
    go = tmp_path / "mv.go"
    env = {
        "BASH_ENV": _bash_env(tmp_path, "hold_mv.sh", MV_HOLD_ENV),
        "MV_MARK": mark.as_posix(),
        "MV_GO": go.as_posix(),
    }
    out_file = tmp_path / "req.out"
    with open(out_file, "wb") as fo:
        p = _spawn(bash, ["request", "s1", "heavy", "5", "a"], lock_dir, env=env, stdout=fo)
        try:
            assert _wait_until(mark.exists, 30), "request не дошёл до mv"
            time.sleep(0.5)
            held_out = out_file.read_bytes()
            held_lock = lock.read_bytes()
            held_tmp = (lock_dir / "machine.lock.tmp").exists()
            go.write_bytes(b"go")
            res = _finish(p)
        finally:
            go.write_bytes(b"go")
            _kill(p)

    assert held_tmp, "в момент mv нет machine.lock.tmp: запись идёт не через tmp"
    assert held_out == b"", f"результат напечатан до mv: {held_out!r}"
    assert held_lock == BASE, "замок изменён до mv"
    assert res.code == 0, res.ctx()
    assert out_file.read_text() == _granted("00:05")
    assert lock.read_bytes() == _lines(COORD, W_S1)


# =====================================================================================================================
# Один mv на вызов; повтор mv при занятом замке
# =====================================================================================================================

MV_CASES = [
    pytest.param(["request", "s1", "heavy", "5", "a"], BASE, NOW_0000, 1, id="request_grant"),
    pytest.param(["request", "s2", "heavy", "10", "b"], _lines(COORD, W_S1), NOW_0000, 1, id="request_queue"),
    pytest.param(["release", "s1"], _lines(COORD, W_S1, WAIT_S2), NOW_0000, 1, id="release_with_next"),
    pytest.param(["release", "s1"], _lines(COORD, W_S1), NOW_0000, 1, id="release_alone"),
    pytest.param(["release", "s2"], _lines(COORD, W_S1, WAIT_S2), NOW_0000, 1, id="release_cancel"),
    pytest.param(["wait", "s2", "--timeout", "0"], _lines(COORD, WAIT_S2), NOW_0000, 1, id="wait_promote"),
    pytest.param(
        ["extend", "s1", "10"], _lines(COORD, "window: s1 | heavy | a | until ~00:20"), NOW_0010, 1, id="extend"
    ),
    pytest.param(["merge-begin", "s1", "feat/x"], BASE, NOW_0000, 1, id="merge_begin"),
    pytest.param(["merge-end", "s1"], _lines(COORD, MERGING_S1), NOW_0000, 1, id="merge_end"),
    # быстрые пути и отказы не пишут вовсе
    pytest.param(["request", "s1", "heavy", "5", "a"], _lines(COORD, W_S1), NOW_0000, 0, id="request_own_window"),
    pytest.param(
        ["request", "s2", "heavy", "10", "b"], _lines(COORD, W_S1, WAIT_S2), NOW_0000, 0, id="request_own_waiting"
    ),
    pytest.param(["release", "s3"], _lines(COORD, W_S1), NOW_0000, 0, id="release_refused"),
    pytest.param(["wait", "s2", "--timeout", "0"], _lines(COORD, W_S1, WAIT_S2), NOW_0000, 0, id="wait_foreign_window"),
    pytest.param(["extend", "s2", "10"], _lines(COORD, W_S1), NOW_0010, 0, id="extend_refused"),
]


@pytest.mark.parametrize(("argv", "lock_bytes", "now", "expected"), MV_CASES)
def test_mv_calls_per_invocation(
    bash: str, lock_dir: Path, tmp_path: Path, argv: list[str], lock_bytes: bytes, now: int, expected: int
) -> None:
    """Один mv на вызов (запись заявки и автовыдача - одной записью); быстрые пути и отказы - ноль."""
    _put(lock_dir, lock_bytes)
    counter = tmp_path / "mv.count"
    env = {"BASH_ENV": _bash_env(tmp_path, "count_mv.sh", MV_COUNT_ENV), "MV_COUNT_FILE": counter.as_posix()}

    res = _gate(bash, argv, lock_dir, now=now, env=env)

    assert res.code in (0, 2, 124), res.ctx()
    assert _count(counter) == expected, res.ctx()


def test_mv_busy_is_retried_then_succeeds(bash: str, lock_dir: Path, tmp_path: Path) -> None:
    lock = _put(lock_dir, BASE)
    fails = tmp_path / "mv.fails"
    env = {
        "BASH_ENV": _bash_env(tmp_path, "fail_mv.sh", MV_FAIL_ENV),
        "MV_FAIL_FILE": fails.as_posix(),
        "MV_FAIL_N": "3",
    }

    res = _gate(bash, ["request", "s1", "heavy", "5", "a"], lock_dir, env=env)

    assert (res.code, res.out) == (0, _granted("00:05")), res.ctx()
    assert res.raw_err == b"", res.ctx()
    assert _count(fails) == 4, "mv должен был быть вызван 4 раза: 3 сбоя и успех"
    assert lock.read_bytes() == _lines(COORD, W_S1)
    assert _listing(lock_dir) == ["machine.lock"]


def test_mv_busy_forever_is_refused_cleanly(bash: str, lock_dir: Path, tmp_path: Path) -> None:
    lock = _put(lock_dir, BASE)
    fails = tmp_path / "mv.fails"
    env = {
        "BASH_ENV": _bash_env(tmp_path, "fail_mv.sh", MV_FAIL_ENV),
        "MV_FAIL_FILE": fails.as_posix(),
        "MV_FAIL_N": "1000",
    }

    res = _gate(bash, ["request", "s1", "heavy", "5", "a"], lock_dir, env=env)

    _refusal(res, BUSY)
    assert res.out == "", f"результат напечатан без успешного mv: {res.out!r}"
    assert 5 <= _count(fails) <= 6, f"план: 5 повторов x 0.2 с; вызовов mv: {_count(fails)}"
    assert lock.read_bytes() == BASE
    assert _listing(lock_dir) == ["machine.lock"], "после отказа остался machine.lock.tmp"


# =====================================================================================================================
# R7. merge-begin / merge-end
# =====================================================================================================================


def test_merge_begin_without_window_puts_slot_right_after_coordinator(bash: str, lock_dir: Path) -> None:
    lock = _put(lock_dir, _lines(COORD, STAND, WAIT_S2))

    res = _gate(bash, ["merge-begin", "s1", "feat/x"], lock_dir)

    assert (res.code, res.out) == (0, "MERGE SLOT TAKEN\n"), res.ctx()
    assert lock.read_bytes() == _lines(COORD, MERGING_S1, STAND, WAIT_S2)
    assert _listing(lock_dir) == ["machine.lock"]


@pytest.mark.parametrize("kind", ["heavy", "stand"])
def test_merge_begin_puts_slot_right_after_window_and_allows_non_quiet(bash: str, lock_dir: Path, kind: str) -> None:
    window = f"window: s2 | {kind} | b | until ~23:59"
    lock = _put(lock_dir, _lines(COORD, window, STAND, WAIT_S3))

    res = _gate(bash, ["merge-begin", "s1", "feat/x"], lock_dir)

    assert (res.code, res.out) == (0, "MERGE SLOT TAKEN\n"), res.ctx()
    assert lock.read_bytes() == _lines(COORD, window, MERGING_S1, STAND, WAIT_S3)


def test_merge_begin_since_follows_substituted_clock(bash: str, lock_dir: Path) -> None:
    lock = _put(lock_dir, BASE)

    res = _gate(bash, ["merge-begin", "s1", "fix/a_b-c.d"], lock_dir, now=NOW_1337)

    assert (res.code, res.out) == (0, "MERGE SLOT TAKEN\n"), res.ctx()
    assert lock.read_bytes() == _lines(COORD, "merging: s1 | fix/a_b-c.d | since 13:37")


MERGE_BEGIN_REFUSALS = [
    pytest.param(_lines(COORD, MERGING_S1), "s2", "feat/y", "merge slot is taken by s1", id="taken_by_other"),
    pytest.param(_lines(COORD, MERGING_S1), "s1", "feat/x", "merge slot is taken by s1", id="taken_by_self"),
    pytest.param(
        _lines(COORD, "window: s3 | quiet | q | until ~23:59"), "s1", "feat/x", "a quiet window is open", id="quiet"
    ),
    pytest.param(
        _lines(COORD, "window: s1 | quiet | q | until ~23:59"), "s1", "feat/x", "a quiet window is open", id="own_quiet"
    ),
]


@pytest.mark.parametrize(("lock_bytes", "session", "branch", "text"), MERGE_BEGIN_REFUSALS)
def test_merge_begin_refused(
    bash: str, lock_dir: Path, lock_bytes: bytes, session: str, branch: str, text: str
) -> None:
    """Инъекция (г): нет проверки слота / quiet-окна в merge-begin."""
    lock = _put(lock_dir, lock_bytes)
    snap = _snap(lock)

    res = _gate(bash, ["merge-begin", session, branch], lock_dir)

    _refusal(res, text)
    assert res.out == "", res.ctx()
    _assert_untouched(lock, snap, lock_dir)


def test_quiet_window_can_be_granted_while_merge_slot_is_open(bash: str, lock_dir: Path) -> None:
    """Симметрии нет сознательно: слот открыт - quiet выдаётся (замер перезапускается)."""
    lock = _put(lock_dir, _lines(COORD, MERGING_S1))

    res = _gate(bash, ["request", "s2", "quiet", "10", "b"], lock_dir)

    assert (res.code, res.out) == (0, _granted("00:10")), res.ctx()
    assert lock.read_bytes() == _lines(COORD, "window: s2 | quiet | b | until ~00:10", MERGING_S1)


@pytest.mark.parametrize("session", ["s1", "c1"])
def test_merge_end_frees_slot_for_owner_and_coordinator(bash: str, lock_dir: Path, session: str) -> None:
    lock = _put(lock_dir, _lines(COORD, W_S1, MERGING_S1, STAND))

    res = _gate(bash, ["merge-end", session], lock_dir)

    assert (res.code, res.out) == (0, "MERGE SLOT FREE\n"), res.ctx()
    assert lock.read_bytes() == _lines(COORD, W_S1, STAND)
    assert _listing(lock_dir) == ["machine.lock"]


MERGE_END_REFUSALS = [
    pytest.param(_lines(COORD, MERGING_S1), "s2", "merge slot belongs to s1", id="foreign"),
    pytest.param(_lines(COORD, MERGING_S1), "c", "merge slot belongs to s1", id="coordinator_prefix"),
    pytest.param(_lines(COORD, W_S1), "s1", "no merge slot", id="no_slot"),
    pytest.param(_lines(COORD, W_S1), "c1", "no merge slot", id="no_slot_coordinator"),
]


@pytest.mark.parametrize(("lock_bytes", "session", "text"), MERGE_END_REFUSALS)
def test_merge_end_refused(bash: str, lock_dir: Path, lock_bytes: bytes, session: str, text: str) -> None:
    lock = _put(lock_dir, lock_bytes)
    snap = _snap(lock)

    res = _gate(bash, ["merge-end", session], lock_dir)

    _refusal(res, text)
    assert res.out == "", res.ctx()
    _assert_untouched(lock, snap, lock_dir)


# =====================================================================================================================
# R8. validate_lock: строка `merging:`
# =====================================================================================================================

VALID_MERGING = [
    pytest.param("merging: s1 | feat/x | since 00:00", id="simple"),
    pytest.param("merging: inspector-bottles-dd | fix/a_b-c.d | since 2026-10-27 12:00", id="name_branch_chars"),
    pytest.param("merging: s1 | main | since x", id="since_free_text"),
]


@pytest.mark.parametrize("merging", VALID_MERGING)
def test_valid_merging_line_is_accepted(bash: str, lock_dir: Path, merging: str) -> None:
    """Пара к отказам ниже: правильная строка проходит (без неё отказы мог бы давать и старый скрипт)."""
    _put(lock_dir, _lines(COORD, merging, STAND))

    _assert_valid_lock(bash, lock_dir)


# (строки после coordinator, номер физической строки в сообщении, эта строка)
BAD_MERGING = [
    pytest.param(["merging: s1 | feat/x"], 2, "merging: s1 | feat/x", id="two_fields"),
    pytest.param(
        ["merging: s1 | feat/x | since 00:00", "merging: s2 | feat/y | since 00:01"],
        3,
        "merging: s2 | feat/y | since 00:01",
        id="two_merging_lines",
    ),
    pytest.param(
        ["merging: s1 [ab] | feat/x | since 00:00"], 2, "merging: s1 [ab] | feat/x | since 00:00", id="name_with_ref"
    ),
    pytest.param(
        ["merging: s1 | feat/x | since 00:00 | extra"],
        2,
        "merging: s1 | feat/x | since 00:00 | extra",
        id="four_fields",
    ),
    pytest.param(["merging: s1 | feat/x | 00:00"], 2, "merging: s1 | feat/x | 00:00", id="no_since"),
    pytest.param(["merging: s1 | feat/x | since"], 2, "merging: s1 | feat/x | since", id="since_without_space"),
    pytest.param(["merging: s1 | feat/x | Since 00:00"], 2, "merging: s1 | feat/x | Since 00:00", id="Since_capital"),
    pytest.param(["merging: s1 | feat x | since 00:00"], 2, "merging: s1 | feat x | since 00:00", id="branch_space"),
    pytest.param(["merging: s1 | a;b | since 00:00"], 2, "merging: s1 | a;b | since 00:00", id="branch_semicolon"),
    pytest.param(["merging: s1 | a*b | since 00:00"], 2, "merging: s1 | a*b | since 00:00", id="branch_glob"),
    pytest.param(["merging: s1 | | since 00:00"], 2, "merging: s1 | | since 00:00", id="branch_empty"),
    pytest.param(
        ["merging:s1 | feat/x | since 00:00"], 2, "merging:s1 | feat/x | since 00:00", id="no_space_after_colon"
    ),
    pytest.param([STAND, "merging: s1 | feat/x"], 3, "merging: s1 | feat/x", id="line_number_counts_stand"),
]


@pytest.mark.parametrize(("after", "line_no", "line"), BAD_MERGING)
def test_bad_merging_line_is_malformed(bash: str, lock_dir: Path, after: list[str], line_no: int, line: str) -> None:
    """Инъекция (д): пропуск merging с 2 полями. Старый контракт: код 2, `malformed machine.lock:<n>: <line>`."""
    lock = _put(lock_dir, _lines(COORD, *after))
    snap = _snap(lock)

    res = _gate(bash, ["light", "s9", "echo", "RAN"], lock_dir)

    _refusal(res, f"malformed machine.lock:{line_no}: {line}")
    assert "RAN" not in res.out, res.ctx()
    _assert_untouched(lock, snap, lock_dir)


# Новые подкоманды на битом замке: код 2, ровно одна строка, замок не тронут (прежний контракт «битый замок = 2»).
NEW_COMMANDS = [
    pytest.param(["request", "s2", "heavy", "5", "x"], id="request"),
    pytest.param(["release", "s2"], id="release"),
    pytest.param(["wait", "s2", "--timeout", "0"], id="wait"),
    pytest.param(["extend", "s2", "5"], id="extend"),
    pytest.param(["merge-begin", "s2", "feat/y"], id="merge-begin"),
    pytest.param(["merge-end", "s2"], id="merge-end"),
]

MALFORMED_FOR_NEW = [
    pytest.param(
        _lines(COORD, "windw: s2 | heavy | x | until ~23:59"),
        "malformed machine.lock:2: windw: s2 | heavy | x | until ~23:59",
        id="window_typo",
    ),
    pytest.param(
        _lines(COORD, "merging: s1 | feat/x"), "malformed machine.lock:2: merging: s1 | feat/x", id="merging_2_fields"
    ),
    pytest.param(
        _lines("window: s2 | heavy | x | until ~23:59"),
        "malformed machine.lock: no coordinator line",
        id="no_coordinator",
    ),
]


@pytest.mark.parametrize("argv", NEW_COMMANDS)
@pytest.mark.parametrize(("lock_bytes", "text"), MALFORMED_FOR_NEW)
def test_malformed_lock_is_refused_by_every_new_command(
    bash: str, lock_dir: Path, lock_bytes: bytes, text: str, argv: list[str]
) -> None:
    lock = _put(lock_dir, lock_bytes)
    snap = _snap(lock)

    res = _gate(bash, argv, lock_dir)

    _refusal(res, text)
    assert res.out == "", res.ctx()
    _assert_untouched(lock, snap, lock_dir)


@pytest.mark.parametrize("argv", NEW_COMMANDS)
def test_missing_lock_is_refused_by_every_new_command(bash: str, lock_dir: Path, argv: list[str]) -> None:
    res = _gate(bash, argv, lock_dir)

    _refusal(res, "no machine.lock")
    assert _listing(lock_dir) == [], "команда создала файл без machine.lock"


# =====================================================================================================================
# Отказы: usage, имя, kind, минуты, what, branch (код 2, точный текст, замок не тронут)
# =====================================================================================================================

USAGE_REQUEST = "usage: machine_gate.sh request <session> quiet|heavy|stand <minutes> <what...>"
USAGE_RELEASE = "usage: machine_gate.sh release <session>"
USAGE_WAIT = "usage: machine_gate.sh wait <session> [--timeout <minutes>]"
USAGE_EXTEND = "usage: machine_gate.sh extend <session> <minutes>"
USAGE_MERGE_BEGIN = "usage: machine_gate.sh merge-begin <session> <branch>"
USAGE_MERGE_END = "usage: machine_gate.sh merge-end <session>"

USAGE_CASES = [
    pytest.param(["request"], USAGE_REQUEST, id="request_bare"),
    pytest.param(["request", "s1"], USAGE_REQUEST, id="request_session_only"),
    pytest.param(["request", "s1", "heavy"], USAGE_REQUEST, id="request_no_minutes"),
    pytest.param(["request", "s1", "heavy", "5"], USAGE_REQUEST, id="request_no_what"),
    pytest.param(["release"], USAGE_RELEASE, id="release_bare"),
    pytest.param(["release", "s1", "extra"], USAGE_RELEASE, id="release_extra"),
    pytest.param(["wait"], USAGE_WAIT, id="wait_bare"),
    pytest.param(["wait", "s1", "--timeout"], USAGE_WAIT, id="wait_timeout_no_value"),
    pytest.param(["wait", "s1", "--timeout", "abc"], USAGE_WAIT, id="wait_timeout_abc"),
    pytest.param(["wait", "s1", "--timeout", "-1"], USAGE_WAIT, id="wait_timeout_negative"),
    pytest.param(["wait", "s1", "--timeout", "00"], USAGE_WAIT, id="wait_timeout_00"),
    pytest.param(["wait", "s1", "--timeout", "10000"], USAGE_WAIT, id="wait_timeout_5_digits"),
    pytest.param(["wait", "s1", "--timeout", "5", "x"], USAGE_WAIT, id="wait_extra_after_timeout"),
    pytest.param(["wait", "s1", "--bogus", "5"], USAGE_WAIT, id="wait_unknown_flag"),
    pytest.param(["wait", "s1", "5"], USAGE_WAIT, id="wait_bare_number"),
    pytest.param(["extend"], USAGE_EXTEND, id="extend_bare"),
    pytest.param(["extend", "s1"], USAGE_EXTEND, id="extend_no_minutes"),
    pytest.param(["extend", "s1", "5", "x"], USAGE_EXTEND, id="extend_extra"),
    pytest.param(["merge-begin"], USAGE_MERGE_BEGIN, id="merge_begin_bare"),
    pytest.param(["merge-begin", "s1"], USAGE_MERGE_BEGIN, id="merge_begin_no_branch"),
    pytest.param(["merge-begin", "s1", "feat/x", "extra"], USAGE_MERGE_BEGIN, id="merge_begin_extra"),
    pytest.param(["merge-end"], USAGE_MERGE_END, id="merge_end_bare"),
    pytest.param(["merge-end", "s1", "extra"], USAGE_MERGE_END, id="merge_end_extra"),
]


@pytest.mark.parametrize(("argv", "usage"), USAGE_CASES)
def test_usage_refusals(bash: str, lock_dir: Path, argv: list[str], usage: str) -> None:
    lock = _put(lock_dir, BUSY_LOCK)
    snap = _snap(lock)

    res = _gate(bash, argv, lock_dir)

    _usage(res, usage)
    assert res.out == "", res.ctx()
    _assert_untouched(lock, snap, lock_dir)


BAD_NAME_CASES = [
    pytest.param(["request", "s2 [ab]", "heavy", "5", "x"], id="request"),
    pytest.param(["release", "s2 [ab]"], id="release"),
    pytest.param(["release", "s|2"], id="release_pipe"),
    pytest.param(["wait", "s2 [ab]", "--timeout", "0"], id="wait"),
    pytest.param(["extend", "s2 [ab]", "5"], id="extend"),
    pytest.param(["merge-begin", "s2 [ab]", "feat/x"], id="merge-begin"),
    pytest.param(["merge-end", "s2 [ab]"], id="merge-end"),
]

# Остальные отказы: все после валидного имени s2 на замке BUSY_LOCK (окно s1, s2 в очереди).
FIELD_REFUSALS = [
    pytest.param(["request", "s2", "fast", "5", "x"], "window kind must be quiet, heavy or stand", id="kind_fast"),
    pytest.param(["request", "s2", "medium", "5", "x"], "window kind must be quiet, heavy or stand", id="kind_medium"),
    pytest.param(["request", "s2", "Heavy", "5", "x"], "window kind must be quiet, heavy or stand", id="kind_capital"),
    pytest.param(["request", "s2", "heavy", "0", "x"], "minutes must be 1..600", id="minutes_0"),
    pytest.param(["request", "s2", "heavy", "601", "x"], "minutes must be 1..600", id="minutes_601"),
    pytest.param(["request", "s2", "heavy", "abc", "x"], "minutes must be 1..600", id="minutes_abc"),
    pytest.param(["request", "s2", "heavy", "05", "x"], "minutes must be 1..600", id="minutes_leading_zero"),
    pytest.param(["request", "s2", "heavy", "-5", "x"], "minutes must be 1..600", id="minutes_negative"),
    pytest.param(["request", "s2", "heavy", "1000", "x"], "minutes must be 1..600", id="minutes_4_digits"),
    pytest.param(["request", "s2", "heavy", "5.5", "x"], "minutes must be 1..600", id="minutes_decimal"),
    pytest.param(["extend", "s1", "0"], "minutes must be 1..600", id="extend_minutes_0"),
    pytest.param(["extend", "s1", "601"], "minutes must be 1..600", id="extend_minutes_601"),
    pytest.param(["extend", "s1", "abc"], "minutes must be 1..600", id="extend_minutes_abc"),
    pytest.param(["request", "s2", "heavy", "5", "a | b"], "what must not contain | or line breaks", id="what_pipe"),
    # пробел внутри аргумента нужен, чтобы Windows/Git Bash донёс "a<LF>b c" одним аргументом (см. docstring файла)
    pytest.param(
        ["request", "s2", "heavy", "5", "a\nb c"], "what must not contain | or line breaks", id="what_newline"
    ),
    pytest.param(["merge-begin", "s1", "feat x"], "bad branch name", id="branch_space"),
    pytest.param(["merge-begin", "s1", "a|b"], "bad branch name", id="branch_pipe"),
    pytest.param(["merge-begin", "s1", "x;y"], "bad branch name", id="branch_semicolon"),
    pytest.param(["merge-begin", "s1", "a*b"], "bad branch name", id="branch_glob"),
    pytest.param(["merge-begin", "s1", "feat/$HOME"], "bad branch name", id="branch_dollar"),
]


@pytest.mark.parametrize("argv", BAD_NAME_CASES)
def test_bad_session_name_is_refused(bash: str, lock_dir: Path, argv: list[str]) -> None:
    lock = _put(lock_dir, BUSY_LOCK)
    snap = _snap(lock)

    res = _gate(bash, argv, lock_dir)

    _refusal(res, "bad session name")
    assert res.out == "", res.ctx()
    _assert_untouched(lock, snap, lock_dir)


@pytest.mark.parametrize(("argv", "text"), FIELD_REFUSALS)
def test_field_refusals(bash: str, lock_dir: Path, argv: list[str], text: str) -> None:
    lock = _put(lock_dir, BUSY_LOCK)
    snap = _snap(lock)

    res = _gate(bash, argv, lock_dir)

    _refusal(res, text)
    assert res.out == "", res.ctx()
    _assert_untouched(lock, snap, lock_dir)


@pytest.mark.parametrize(
    ("argv", "kind"),
    [
        (["request", "s9", "quiet", "5", "x"], "quiet"),
        (["request", "s9", "stand", "5", "x"], "stand"),
    ],
)
def test_other_window_kinds_are_accepted(bash: str, lock_dir: Path, argv: list[str], kind: str) -> None:
    """Пара к отказам по kind: quiet и stand проходят проверку вида (сессия s9 встаёт в очередь)."""
    lock = _put(lock_dir, BUSY_LOCK)

    res = _gate(bash, argv, lock_dir)

    assert (res.code, res.out) == (0, "QUEUED position 2\n"), res.ctx()
    assert lock.read_bytes().endswith(f"waiting: s9 | {kind} | x | ~5 min\n".encode())


# Порядок проверок: usage -> нет замка -> битый замок -> имя -> kind -> минуты -> what -> branch -> операция.
MALFORMED_LOCK = _lines(COORD, "windw: x")
ORDER_CASES = [
    pytest.param(None, ["request", "s1", "heavy"], ("usage", USAGE_REQUEST), id="usage_before_no_lock"),
    pytest.param(
        None, ["request", "s2 [ab]", "heavy", "5", "x"], ("text", "no machine.lock"), id="no_lock_before_bad_name"
    ),
    pytest.param(
        MALFORMED_LOCK,
        ["request", "s2 [ab]", "heavy", "5", "x"],
        ("text", "malformed machine.lock:2: windw: x"),
        id="malformed_before_bad_name",
    ),
    pytest.param(
        BUSY_LOCK, ["request", "s2 [ab]", "fast", "0", "a | b"], ("text", "bad session name"), id="name_before_kind"
    ),
    pytest.param(
        BUSY_LOCK,
        ["request", "s2", "fast", "0", "a | b"],
        ("text", "window kind must be quiet, heavy or stand"),
        id="kind_before_minutes",
    ),
    pytest.param(
        BUSY_LOCK,
        ["request", "s2", "heavy", "0", "a | b"],
        ("text", "minutes must be 1..600"),
        id="minutes_before_what",
    ),
    pytest.param(
        BUSY_LOCK, ["extend", "s9", "0"], ("text", "minutes must be 1..600"), id="extend_minutes_before_no_window"
    ),
    pytest.param(
        _lines(COORD, MERGING_S1),
        ["merge-begin", "s2", "bad branch"],
        ("text", "bad branch name"),
        id="branch_before_slot_taken",
    ),
    pytest.param(
        _lines(COORD, MERGING_S1),
        ["merge-begin", "s2 [ab]", "bad branch"],
        ("text", "bad session name"),
        id="name_before_branch",
    ),
    pytest.param(BUSY_LOCK, ["release", "s9 [ab]"], ("text", "bad session name"), id="release_name_before_operation"),
]


@pytest.mark.parametrize(("lock_bytes", "argv", "expect"), ORDER_CASES)
def test_refusal_order(
    bash: str, lock_dir: Path, lock_bytes: bytes | None, argv: list[str], expect: tuple[str, str]
) -> None:
    lock = _put(lock_dir, lock_bytes)
    snap = _snap(lock) if lock_bytes is not None else None

    res = _gate(bash, argv, lock_dir)

    mode, text = expect
    if mode == "usage":
        _usage(res, text)
    else:
        _refusal(res, text)
    if snap is not None:
        _assert_untouched(lock, snap, lock_dir)
    else:
        assert _listing(lock_dir) == []


# =====================================================================================================================
# R9. wait
# =====================================================================================================================


def test_wait_without_request_is_refused(bash: str, lock_dir: Path) -> None:
    lock = _put(lock_dir, _lines(COORD, W_S1, WAIT_S2))
    snap = _snap(lock)

    res = _gate(bash, ["wait", "s9"], lock_dir)

    _refusal(res, "no request of this session")
    assert res.out == "", res.ctx()
    _assert_untouched(lock, snap, lock_dir)


def test_wait_with_foreign_window_times_out_with_124_without_write(bash: str, lock_dir: Path) -> None:
    lock = _put(lock_dir, _lines(COORD, W_S1, WAIT_S2))
    snap = _snap(lock)

    res = _gate(bash, ["wait", "s2", "--timeout", "0"], lock_dir)

    assert res.code == 124, res.ctx()
    assert "TIMEOUT" in res.both, res.ctx()
    assert "GRANTED" not in res.both, res.ctx()
    _assert_untouched(lock, snap, lock_dir)


def test_wait_with_own_window_is_granted_at_once_without_write(bash: str, lock_dir: Path) -> None:
    lock = _put(lock_dir, _lines(COORD, W_S1, WAIT_S3))
    snap = _snap(lock)

    res = _gate(bash, ["wait", "s1"], lock_dir)

    assert (res.code, res.out) == (0, _granted("00:05")), res.ctx()
    _assert_untouched(lock, snap, lock_dir)


def test_running_wait_ends_with_0_after_release_by_another_process(bash: str, lock_dir: Path) -> None:
    lock = _put(lock_dir, _lines(COORD, W_S1, WAIT_S2))
    p = _spawn(bash, ["wait", "s2", "--timeout", "1"], lock_dir)
    try:
        time.sleep(2.5)  # минимум два опроса при MACHINE_GATE_POLL_SEC=1
        assert p.poll() is None, "wait завершился, пока чужое окно ещё открыто"
        rel = _gate(bash, ["release", "s1"], lock_dir)
        res = _finish(p)
    finally:
        _kill(p)

    assert rel.code == 0, rel.ctx()
    assert (res.code, res.out) == (0, _granted("00:10")), res.ctx()
    assert lock.read_bytes() == _lines(COORD, "window: s2 | heavy | b | until ~00:10")


def test_running_wait_promotes_itself_after_close(bash: str, lock_dir: Path) -> None:
    """Инъекция (к) в живом виде: close координатора окна не выдаёт; wait на опросе выдаёт сам."""
    lock = _put(lock_dir, _lines(COORD, W_S1, WAIT_S2))
    p = _spawn(bash, ["wait", "s2", "--timeout", "1"], lock_dir)
    try:
        time.sleep(2.5)
        assert p.poll() is None, "wait завершился, пока чужое окно ещё открыто"
        closed = _gate(bash, ["close", "c1", "s1"], lock_dir)
        res = _finish(p)
    finally:
        _kill(p)

    assert closed.code == 0, closed.ctx()
    assert (res.code, res.out) == (0, _granted("00:10")), res.ctx()
    assert lock.read_bytes() == _lines(COORD, "window: s2 | heavy | b | until ~00:10")


def _replace_lock(lock: Path, data: bytes) -> None:
    """Подменить замок атомарно (как это сделал бы чужой писатель); на Windows повторить, если читатель держит файл."""
    side = lock.parent.parent / "side.lock"
    side.write_bytes(data)
    for _ in range(50):
        try:
            os.replace(side, lock)
            return
        except PermissionError:
            time.sleep(0.05)
    pytest.fail("не удалось подменить замок: файл занят")


def test_wait_refuses_when_request_disappears_mid_poll(bash: str, lock_dir: Path) -> None:
    lock = _put(lock_dir, _lines(COORD, W_S1, WAIT_S2))
    p = _spawn(bash, ["wait", "s2", "--timeout", "1"], lock_dir)
    try:
        time.sleep(2.5)
        assert p.poll() is None
        _replace_lock(lock, _lines(COORD, W_S1))
        res = _finish(p)
    finally:
        _kill(p)

    _refusal(res, "request of this session disappeared")
    assert res.out == "", res.ctx()


def test_wait_refuses_when_lock_becomes_malformed_mid_poll(bash: str, lock_dir: Path) -> None:
    lock = _put(lock_dir, _lines(COORD, W_S1, WAIT_S2))
    p = _spawn(bash, ["wait", "s2", "--timeout", "1"], lock_dir)
    try:
        time.sleep(2.5)
        assert p.poll() is None
        _replace_lock(lock, _lines(COORD, "windw: x"))
        res = _finish(p)
    finally:
        _kill(p)

    _refusal(res, "malformed machine.lock:2: windw: x")


# =====================================================================================================================
# R10. OVERDUE (status и wait)
# =====================================================================================================================


def _status_re(lock_lines: list[str], overdue: str | None) -> re.Pattern[str]:
    body = "".join(re.escape(x) + "\n" for x in lock_lines)
    if overdue is not None:
        body += re.escape(overdue) + "\n"
    return re.compile(body + r"ram_free_mb: (\d+|n/a)\ncpu_load_pct: (\d+|n/a)\n")


def _status(
    bash: str, lock_dir: Path, lock_bytes: bytes, lines: list[str], now: int, overdue: str | None, code: int
) -> None:
    lock = _put(lock_dir, lock_bytes)
    snap = _snap(lock)

    res = _gate(bash, ["status"], lock_dir, now=now)

    assert res.code == code, res.ctx()
    assert _status_re(lines, overdue).fullmatch(res.out), res.ctx()
    _assert_untouched(lock, snap, lock_dir)


def test_status_prints_overdue_line_when_someone_waits(bash: str, lock_dir: Path) -> None:
    lines = [COORD, "window: s1 | heavy | a | until ~23:50", WAIT_S2, STAND]
    _status(bash, lock_dir, _lines(*lines), lines, NOW_0010, "OVERDUE s1 +20 min", 0)


def test_status_without_waiting_is_unchanged_even_when_overdue(bash: str, lock_dir: Path) -> None:
    lines = [COORD, "window: s1 | heavy | a | until ~23:50", STAND]
    _status(bash, lock_dir, _lines(*lines), lines, NOW_0010, None, 0)


def test_status_on_malformed_lock_has_no_overdue_line(bash: str, lock_dir: Path) -> None:
    lines = [COORD, "window: s1 | heavy | a | until ~23:50", WAIT_S2, "windw: x"]
    _status(bash, lock_dir, _lines(*lines), lines, NOW_0010, None, 2)


def test_status_window_with_invalid_until_is_not_overdue(bash: str, lock_dir: Path) -> None:
    lines = [COORD, "window: s1 | heavy | a | until ~soon", WAIT_S2]
    _status(bash, lock_dir, _lines(*lines), lines, NOW_0010, None, 0)


def test_status_overdue_survives_octal_looking_digits(bash: str, lock_dir: Path) -> None:
    """Инъекция (и): арифметика без 10#. now 09:08, окно до ~08:50 -> просрочено на 18 минут."""
    lines = [COORD, "window: s1 | heavy | a | until ~08:50", WAIT_S2]
    _status(bash, lock_dir, _lines(*lines), lines, NOW_0908, "OVERDUE s1 +18 min", 0)


OVERDUE_CASES = [
    pytest.param("~23:50", NOW_0010, "OVERDUE s1 +20 min", id="over_midnight_20"),
    pytest.param("~00:09", NOW_0010, "OVERDUE s1 +1 min", id="one_minute_over"),
    pytest.param("~00:10", NOW_0010, None, id="exactly_now_not_overdue"),
    pytest.param("~00:11", NOW_0010, None, id="one_minute_left"),
    pytest.param("~11:09", NOW_0010, None, id="plus_659_left"),
    pytest.param("~11:10", NOW_0010, "OVERDUE s1 +780 min", id="plus_660_wraps_to_13h_over"),
    pytest.param("~12:00", NOW_0010, "OVERDUE s1 +730 min", id="12h_window_is_730_over"),
    pytest.param("~08:50", NOW_0908, "OVERDUE s1 +18 min", id="decimal_08_50"),
    pytest.param("~09:00", NOW_0908, "OVERDUE s1 +8 min", id="decimal_09_00"),
    pytest.param("~09:08", NOW_0908, None, id="decimal_equal_09_08"),
    pytest.param("~soon", NOW_0010, None, id="until_not_hhmm"),
    pytest.param("~24:00", NOW_0010, None, id="until_hour_24"),
    pytest.param("~12:60", NOW_0010, None, id="until_minute_60"),
]


@pytest.mark.parametrize(("until", "now", "expected"), OVERDUE_CASES)
def test_wait_prints_overdue_for_foreign_window(
    bash: str, lock_dir: Path, until: str, now: int, expected: str | None
) -> None:
    lock = _put(lock_dir, _lines(COORD, f"window: s1 | heavy | a | until {until}", WAIT_S2))
    snap = _snap(lock)

    res = _gate(bash, ["wait", "s2", "--timeout", "0"], lock_dir, now=now)

    assert res.code == 124, res.ctx()
    overdue_lines = [x for x in res.out.splitlines() if x.startswith("OVERDUE")]
    assert overdue_lines == ([expected] if expected else []), res.ctx()
    _assert_untouched(lock, snap, lock_dir)


def test_running_wait_prints_overdue_once_while_minutes_do_not_change(bash: str, lock_dir: Path) -> None:
    """Часы подменены и стоят: N не меняется, поэтому за несколько опросов строка одна."""
    _put(lock_dir, _lines(COORD, "window: s1 | heavy | a | until ~23:50", WAIT_S2))
    p = _spawn(bash, ["wait", "s2", "--timeout", "1"], lock_dir, now=NOW_0010)
    try:
        time.sleep(3.5)  # три-четыре опроса
        assert p.poll() is None
        closed = _gate(bash, ["close", "c1", "s1"], lock_dir, now=NOW_0010)
        res = _finish(p)
    finally:
        _kill(p)

    assert closed.code == 0, closed.ctx()
    assert res.code == 0, res.ctx()
    assert res.out.splitlines() == ["OVERDUE s1 +20 min", "GRANTED until ~00:10"], res.ctx()


# =====================================================================================================================
# R11. extend
# =====================================================================================================================

EXT_LOCK_TAIL = [WAIT_S2, STAND]


@pytest.mark.parametrize(
    ("until", "now", "minutes", "new_until"),
    [
        pytest.param("00:20", NOW_0010, "30", "00:50", id="r11_literal"),
        pytest.param("23:50", NOW_0010, "30", "00:40", id="overdue_extends_from_now"),
        pytest.param("00:05", NOW_2355, "30", "00:35", id="until_after_midnight_is_ahead"),
        pytest.param("00:20", NOW_0010, "590", "10:10", id="remaining_exactly_600"),
        pytest.param("09:08", NOW_0908, "5", "09:13", id="decimal_09_08"),
        pytest.param("08:50", NOW_0908, "5", "09:13", id="decimal_overdue_08_50"),
    ],
)
def test_extend_moves_until(bash: str, lock_dir: Path, until: str, now: int, minutes: str, new_until: str) -> None:
    lock = _put(lock_dir, _lines(COORD, f"window: s1 | heavy | a | until ~{until}", *EXT_LOCK_TAIL))

    res = _gate(bash, ["extend", "s1", minutes], lock_dir, now=now)

    assert (res.code, res.out) == (0, f"EXTENDED until ~{new_until}\n"), res.ctx()
    assert lock.read_bytes() == _lines(COORD, f"window: s1 | heavy | a | until ~{new_until}", *EXT_LOCK_TAIL)
    assert _listing(lock_dir) == ["machine.lock"]


def test_extend_by_stranger_is_refused(bash: str, lock_dir: Path) -> None:
    """Инъекция (е): extend без проверки владельца."""
    lock = _put(lock_dir, _lines(COORD, "window: s1 | heavy | a | until ~00:20", WAIT_S2))
    snap = _snap(lock)

    res = _gate(bash, ["extend", "s2", "30"], lock_dir, now=NOW_0010)

    _refusal(res, "no window of this session")
    assert res.out == "", res.ctx()
    _assert_untouched(lock, snap, lock_dir)


def test_extend_without_any_window_is_refused(bash: str, lock_dir: Path) -> None:
    lock = _put(lock_dir, _lines(COORD, WAIT_S2))
    snap = _snap(lock)

    res = _gate(bash, ["extend", "s2", "30"], lock_dir, now=NOW_0010)

    _refusal(res, "no window of this session")
    _assert_untouched(lock, snap, lock_dir)


def test_extend_that_leaves_more_than_600_minutes_is_refused(bash: str, lock_dir: Path) -> None:
    lock = _put(lock_dir, _lines(COORD, "window: s1 | heavy | a | until ~00:20", WAIT_S2))
    snap = _snap(lock)

    res = _gate(bash, ["extend", "s1", "591"], lock_dir, now=NOW_0010)

    _refusal(res, "extension too long (more than 600 minutes left)")
    assert res.out == "", res.ctx()
    _assert_untouched(lock, snap, lock_dir)


@pytest.mark.parametrize("until", ["~soon", "~24:00", "~12:60", "~1230", "~"])
def test_extend_needs_valid_until(bash: str, lock_dir: Path, until: str) -> None:
    lock = _put(lock_dir, _lines(COORD, f"window: s1 | heavy | a | until {until}", WAIT_S2))
    snap = _snap(lock)

    res = _gate(bash, ["extend", "s1", "30"], lock_dir, now=NOW_0010)

    _refusal(res, "window has no valid until")
    assert res.out == "", res.ctx()
    _assert_untouched(lock, snap, lock_dir)


# =====================================================================================================================
# R13. ожидание machine.lock.tmp, чужой и просроченный tmp
# =====================================================================================================================

# (argv, замок, now, stdout при успехе) - команды, которые пишут замок.
WRITERS = [
    pytest.param(["request", "s2", "heavy", "10", "b"], BASE, NOW_0000, _granted("00:10"), id="request"),
    pytest.param(["release", "s1"], _lines(COORD, W_S1), NOW_0000, "RELEASED\n", id="release"),
    pytest.param(
        ["extend", "s1", "10"],
        _lines(COORD, "window: s1 | heavy | a | until ~00:20"),
        NOW_0010,
        "EXTENDED until ~00:30\n",
        id="extend",
    ),
    pytest.param(["merge-begin", "s1", "feat/x"], BASE, NOW_0000, "MERGE SLOT TAKEN\n", id="merge-begin"),
    pytest.param(["merge-end", "s1"], _lines(COORD, MERGING_S1), NOW_0000, "MERGE SLOT FREE\n", id="merge-end"),
]


def _tmp(lock_dir: Path, age_sec: float = 0.0) -> Path:
    """Чужой machine.lock.tmp; mtime сдвинут в прошлое по РЕАЛЬНЫМ часам (os.utime)."""
    tmp = lock_dir / "machine.lock.tmp"
    tmp.write_bytes(b"x")
    if age_sec:
        t = time.time() - age_sec
        os.utime(tmp, (t, t))
    return tmp


@pytest.mark.parametrize(("argv", "lock_bytes", "now", "_ok"), WRITERS)
def test_fresh_foreign_tmp_is_waited_for_then_refused_and_kept(
    bash: str, lock_dir: Path, argv: list[str], lock_bytes: bytes, now: int, _ok: str
) -> None:
    """Инъекции (в), (м): без O_EXCL tmp затёрт; trap без флага владения снимает tmp победителя.

    Часы гейта подменены на «через два месяца»: возраст tmp считается по реальным часам, поэтому свежий tmp свежий.
    """
    lock = _put(lock_dir, lock_bytes)
    tmp = _tmp(lock_dir)
    snap = lock.read_bytes()

    res = _gate(bash, argv, lock_dir, now=now, env={"MACHINE_GATE_TMP_WAIT_SEC": "1"})

    _refusal(res, TMP_BUSY)
    assert res.out == "", res.ctx()
    assert res.elapsed >= 0.9, f"отказ за {res.elapsed:.2f} с: гейт не ждал tmp (MACHINE_GATE_TMP_WAIT_SEC=1)"
    assert tmp.read_bytes() == b"x", "чужой machine.lock.tmp тронут"
    assert lock.read_bytes() == snap
    assert _listing(lock_dir) == ["machine.lock", "machine.lock.tmp"]


def test_tmp_younger_than_60_seconds_is_not_reclaimed(bash: str, lock_dir: Path) -> None:
    lock = _put(lock_dir, BASE)
    tmp = _tmp(lock_dir, age_sec=30)

    res = _gate(bash, ["request", "s2", "heavy", "10", "b"], lock_dir, env={"MACHINE_GATE_TMP_WAIT_SEC": "1"})

    _refusal(res, TMP_BUSY)
    assert tmp.read_bytes() == b"x"
    assert lock.read_bytes() == BASE


@pytest.mark.parametrize(("argv", "lock_bytes", "now", "ok"), WRITERS)
def test_leftover_tmp_older_than_60_seconds_is_reclaimed(
    bash: str, lock_dir: Path, argv: list[str], lock_bytes: bytes, now: int, ok: str
) -> None:
    lock = _put(lock_dir, lock_bytes)
    _tmp(lock_dir, age_sec=120)

    res = _gate(bash, argv, lock_dir, now=now, env={"MACHINE_GATE_TMP_WAIT_SEC": "1"})

    assert (res.code, res.out) == (0, ok), res.ctx()
    assert lock.read_bytes() != lock_bytes, "замок не изменён"
    assert _listing(lock_dir) == ["machine.lock"], "остаток tmp не снят"


def test_tmp_wait_zero_refuses_at_once(bash: str, lock_dir: Path) -> None:
    """Пара к ожиданию: при MACHINE_GATE_TMP_WAIT_SEC=0 отказ мгновенный, tmp цел."""
    lock = _put(lock_dir, BASE)
    tmp = _tmp(lock_dir)

    res = _gate(bash, ["request", "s2", "heavy", "10", "b"], lock_dir, env={"MACHINE_GATE_TMP_WAIT_SEC": "0"})

    _refusal(res, TMP_BUSY)
    assert res.elapsed < 0.9 + 5, res.ctx()
    assert tmp.read_bytes() == b"x"
    assert lock.read_bytes() == BASE


def test_request_waits_for_busy_tmp_until_it_is_released(bash: str, lock_dir: Path) -> None:
    """R13c, инъекция (ж): ожидание вместо мгновенного отказа. tmp снимается через 2 с; ждать разрешено 8 с."""
    lock = _put(lock_dir, BASE)
    tmp = _tmp(lock_dir)

    def release() -> None:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass

    timer = threading.Timer(2.0, release)
    t0 = time.monotonic()
    timer.start()
    try:
        res = _gate(
            bash,
            ["request", "s1", "heavy", "5", "a"],
            lock_dir,
            env={"MACHINE_GATE_TMP_WAIT_SEC": "8"},
        )
    finally:
        timer.cancel()
    total = time.monotonic() - t0

    assert (res.code, res.out) == (0, _granted("00:05")), res.ctx()
    assert total >= 1.9, f"вызов вернулся за {total:.2f} с, до снятия tmp: гейт не ждал"
    assert lock.read_bytes() == _lines(COORD, W_S1)
    assert _listing(lock_dir) == ["machine.lock"]


# Быстрые пути и отказы операции не берут tmp: при чужом свежем tmp они отвечают своим текстом/результатом.
FAST_PATHS = [
    pytest.param(
        ["request", "s1", "heavy", "5", "a"], _lines(COORD, W_S1), NOW_0000, (0, _granted("00:05"), ""), id="own_window"
    ),
    pytest.param(
        ["request", "s2", "heavy", "10", "b"],
        _lines(COORD, W_S1, WAIT_S2),
        NOW_0000,
        (0, "QUEUED position 1\n", ""),
        id="own_waiting",
    ),
    pytest.param(["wait", "s1"], _lines(COORD, W_S1), NOW_0000, (0, _granted("00:05"), ""), id="wait_own_window"),
    pytest.param(
        ["release", "s3"],
        _lines(COORD, W_S1),
        NOW_0000,
        (2, "", REFUSE + "no window or request of this session\n"),
        id="release_refused",
    ),
    pytest.param(
        ["extend", "s2", "5"],
        _lines(COORD, W_S1),
        NOW_0010,
        (2, "", REFUSE + "no window of this session\n"),
        id="extend_refused",
    ),
    pytest.param(
        ["merge-end", "s1"], _lines(COORD, W_S1), NOW_0000, (2, "", REFUSE + "no merge slot\n"), id="merge_end_refused"
    ),
    pytest.param(
        ["merge-begin", "s2", "feat/y"],
        _lines(COORD, MERGING_S1),
        NOW_0000,
        (2, "", REFUSE + "merge slot is taken by s1\n"),
        id="merge_begin_refused",
    ),
]


@pytest.mark.parametrize(("argv", "lock_bytes", "now", "expect"), FAST_PATHS)
def test_fast_paths_and_refusals_do_not_take_tmp(
    bash: str, lock_dir: Path, argv: list[str], lock_bytes: bytes, now: int, expect: tuple[int, str, str]
) -> None:
    lock = _put(lock_dir, lock_bytes)
    tmp = _tmp(lock_dir)
    ino = os.stat(lock).st_ino

    res = _gate(bash, argv, lock_dir, now=now, env={"MACHINE_GATE_TMP_WAIT_SEC": "0"})

    code, out, err = expect
    assert (res.code, res.out, res.err) == (code, out, err), res.ctx()
    assert tmp.read_bytes() == b"x", "чужой tmp тронут"
    assert lock.read_bytes() == lock_bytes
    assert os.stat(lock).st_ino == ino
    assert _listing(lock_dir) == ["machine.lock", "machine.lock.tmp"]


# --- сигналы: trap на tmp ------------------------------------------------------------------------------------------

# Обёртка внутри msys: гейт в фоне, по файлу-сигналу ему шлётся TERM (как остановка долгоживущего wait).
TERM_WRAPPER = """"$BASH" "$GATE" "$@" > "$OUT" 2>&1 &
pid=$!
for ((i = 0; i < 1200; i++)); do
    [ -e "$STOP" ] && break
    sleep 0.05
done
kill -TERM "$pid" 2>/dev/null
wait "$pid"
echo $? > "$RC"
"""


def _term_run(
    bash: str,
    lock_dir: Path,
    tmp_path: Path,
    gate_args: list[str],
    ready: Callable[[], bool],
    act: Callable[[], None],
    extra_env: dict[str, str] | None = None,
) -> str:
    """Запустить гейт под обёрткой, дождаться ready(), выполнить act(), послать TERM. Возвращает вывод гейта."""
    stop = tmp_path / "stop.flag"
    rc = tmp_path / "gate.rc"
    out = tmp_path / "gate.out"
    env = _env(lock_dir, NOW_0000, extra_env)
    env.update({"GATE": GATE, "OUT": out.as_posix(), "STOP": stop.as_posix(), "RC": rc.as_posix()})
    wrapper = subprocess.Popen(
        [bash, "-c", TERM_WRAPPER, "_", *gate_args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        cwd=str(lock_dir.parent),
    )
    try:
        assert _wait_until(ready, 30), "гейт не дошёл до нужного состояния"
        act()
        stop.write_bytes(b"stop")
        wrapper.communicate(timeout=40)
    except subprocess.TimeoutExpired:
        wrapper.kill()
        wrapper.communicate()
        pytest.fail("обёртка с TERM зависла")
    finally:
        stop.write_bytes(b"stop")
        _kill(wrapper)
    assert rc.exists(), "обёртка не записала код завершения гейта"
    return out.read_text() if out.exists() else ""


def test_term_while_holding_tmp_removes_own_tmp(bash: str, lock_dir: Path, tmp_path: Path) -> None:
    """Пара к R13d: trap, снимающий свой tmp, существует и срабатывает по TERM; замок остаётся прежним."""
    lock = _put(lock_dir, BASE)
    mark = tmp_path / "mv.mark"
    tmp = lock_dir / "machine.lock.tmp"
    env = {
        "BASH_ENV": _bash_env(tmp_path, "hold_mv.sh", MV_HOLD_ENV),
        "MV_MARK": mark.as_posix(),
        "MV_GO": (tmp_path / "never.go").as_posix(),
    }
    seen: dict[str, bool] = {}

    def ready() -> bool:
        return mark.exists() and tmp.exists()

    def act() -> None:
        seen["tmp_held"] = tmp.exists()

    _term_run(bash, lock_dir, tmp_path, ["request", "s1", "heavy", "5", "a"], ready, act, env)

    assert seen["tmp_held"], "гейт не держал tmp в момент TERM"
    assert not tmp.exists(), "после TERM остался свой machine.lock.tmp"
    assert lock.read_bytes() == BASE, "замок изменён прерванным вызовом"


def test_term_after_own_mv_does_not_remove_foreign_tmp(bash: str, lock_dir: Path, tmp_path: Path) -> None:
    """R13d, инъекция (м): wait сам выдал окно другому (mv был), затем чужой tmp; остановка wait не снимает его.

    Замок без окна: wait s2 на первом опросе выдаёт окно первой в очереди (s3) и остаётся ждать своей очереди.
    """
    lock = _put(lock_dir, _lines(COORD, WAIT_S3, WAIT_S2))
    tmp = lock_dir / "machine.lock.tmp"

    def ready() -> bool:
        return b"window: s3 " in lock.read_bytes()  # промоут (и его mv) случился

    def act() -> None:
        tmp.write_bytes(b"x")  # «чужой» живой tmp
        time.sleep(1.5)  # wait успеет опросить замок ещё раз при чужом tmp

    _term_run(bash, lock_dir, tmp_path, ["wait", "s2", "--timeout", "1"], ready, act)

    assert tmp.exists(), "остановка wait сняла чужой machine.lock.tmp"
    assert tmp.read_bytes() == b"x"
    assert lock.read_bytes() == _lines(COORD, "window: s3 | heavy | c | until ~00:20", WAIT_S2)
