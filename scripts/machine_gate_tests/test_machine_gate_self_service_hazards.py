"""Hazard-тесты автора к Task 1.1 (tooling-gate-self-service): гонки, убитый держатель tmp, повторный вход, порядок.

Дополняют слепой набор test_machine_gate_self_service.py. Ожидаемые значения - литералы (TZ=UTC,
MACHINE_GATE_NOW_EPOCH=1798329600 = 00:00). Каждый вызов идёт с MACHINE_LOCK_DIR на каталог в tmp_path: живой
machine.lock не трогается. Всё, что может зависнуть, идёт с timeout / join-дедлайном (daemon-потоки).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GATE = (ROOT / "scripts" / "machine_gate.sh").as_posix()
NOW_0000 = 1798329600
CALL_TIMEOUT = 60

COORD = "coordinator: c1 | since x"
W_S1 = "window: s1 | heavy | a | until ~00:05"
WAIT_S2 = "waiting: s2 | heavy | b | ~10 min"

# Первый вызов mv создаёт маркер (mkdir атомарен) и держит запись, пока нет go-файла (не дольше 10 с).
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


def _lines(*lines: str) -> bytes:
    return ("\n".join(lines) + "\n").encode("utf-8")


@pytest.fixture(scope="module")
def bash() -> str:
    git = shutil.which("git")
    for parent in Path(git).resolve().parents if git else []:
        if (parent / "bin" / "bash.exe").is_file():
            return str(parent / "bin" / "bash.exe")
    found = shutil.which("bash") if sys.platform != "win32" else None
    assert found is not None, "Git Bash не найден: без него гейт не запустить"
    return found


@pytest.fixture
def lock_dir(tmp_path: Path) -> Path:
    d = tmp_path / "lock"
    d.mkdir()
    return d


def _env(lock_dir: Path, extra: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ)
    for k in ("PYTHONPATH", "BASH_ENV", "MACHINE_GATE_TMP_WAIT_SEC"):
        env.pop(k, None)
    env.update(
        {
            "PYTHONUTF8": "1",
            "TZ": "UTC",
            "MACHINE_LOCK_DIR": lock_dir.as_posix(),
            "MACHINE_GATE_NOW_EPOCH": str(NOW_0000),
            "MACHINE_GATE_POLL_SEC": "1",
        }
    )
    env.update(extra or {})
    return env


def _run(bash: str, args: list[str], lock_dir: Path, extra: dict[str, str] | None = None) -> tuple[int, str, str]:
    p = subprocess.run(
        [bash, GATE, *args],
        capture_output=True,
        env=_env(lock_dir, extra),
        cwd=str(lock_dir.parent),
        timeout=CALL_TIMEOUT,
        check=False,
    )
    return p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")


def _spawn(bash: str, args: list[str], lock_dir: Path, extra: dict[str, str] | None = None) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [bash, GATE, *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_env(lock_dir, extra),
        cwd=str(lock_dir.parent),
    )


def _finish(p: subprocess.Popen[bytes], timeout: float = 40.0) -> tuple[int, str]:
    try:
        out, _ = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        p.kill()
        p.communicate()
        pytest.fail(f"вызов гейта завис дольше {timeout} с (убит)")
    return p.returncode, out.decode("utf-8", "replace")


def _wait_until(pred, timeout: float) -> bool:  # noqa: ANN001
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            if pred():
                return True
        except OSError:
            pass
        time.sleep(0.1)
    return False


def _listing(d: Path) -> list[str]:
    return sorted(p.name for p in d.iterdir())


def _kill_tree(p: subprocess.Popen[bytes]) -> None:
    """kill -9 всего дерева держателя (на Windows Git Bash порождает дочерний bash: taskkill /T по PID)."""
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True, check=False, timeout=30)
    else:
        p.kill()
    p.communicate(timeout=30)


def _hold_env(tmp_path: Path) -> dict[str, str]:
    f = tmp_path / "hold_mv.sh"
    f.write_bytes(MV_HOLD_ENV.encode("utf-8"))
    return {
        "BASH_ENV": f.as_posix(),
        "MV_MARK": (tmp_path / "mv.mark").as_posix(),
        "MV_GO": (tmp_path / "mv.go").as_posix(),
    }


def test_three_parallel_requests_keep_one_window_and_all_sessions(bash: str, lock_dir: Path) -> None:
    """Гонка трёх писателей: ровно одно окно, три сессии в замке, tmp снят, замок годен."""
    lock = lock_dir / "machine.lock"
    lock.write_bytes(_lines(COORD))
    barrier = threading.Barrier(3)
    results: dict[str, tuple[int, str, str] | BaseException] = {}

    def worker(session: str) -> None:
        try:
            barrier.wait(timeout=30)
            results[session] = _run(bash, ["request", session, "heavy", "5", "x"], lock_dir)
        except BaseException as exc:  # noqa: BLE001 - сбой потока фиксируется как провал
            results[session] = exc

    threads = [threading.Thread(target=worker, args=(s,), daemon=True) for s in ("s1", "s2", "s3")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=CALL_TIMEOUT + 30)
    assert not any(t.is_alive() for t in threads), "вызов гейта завис"

    assert all(isinstance(r, tuple) and r[0] == 0 for r in results.values()), results
    text = lock.read_text()
    rows = text.splitlines()
    assert rows[0] == COORD
    assert sum(1 for r in rows if r.startswith("window: ")) == 1, text
    present = {r.split(" | ")[0].split(": ")[1] for r in rows if r.startswith(("window: ", "waiting: "))}
    assert present == {"s1", "s2", "s3"}, text
    assert len(rows) == 4, text
    assert _listing(lock_dir) == ["machine.lock"]
    outs = sorted(r[1] for r in results.values() if isinstance(r, tuple))
    assert outs == ["GRANTED until ~00:05\n", "QUEUED position 1\n", "QUEUED position 2\n"], outs


def test_killed_tmp_holder_is_recovered_by_reclaim_after_60_seconds(bash: str, lock_dir: Path, tmp_path: Path) -> None:
    """kill -9 держателя tmp: свежий tmp держит других (отказ), старше 60 с - реклеймится, запись проходит."""
    lock = lock_dir / "machine.lock"
    lock.write_bytes(_lines(COORD))
    env = _hold_env(tmp_path)
    mark = Path(env["MV_MARK"])
    holder = _spawn(bash, ["request", "s1", "heavy", "5", "a"], lock_dir, env)
    try:
        assert _wait_until(mark.exists, 30), "держатель не дошёл до mv"
        _kill_tree(holder)
    finally:
        if holder.poll() is None:
            holder.kill()
            holder.communicate()
    tmp = lock_dir / "machine.lock.tmp"
    assert tmp.exists(), "убитый держатель оставил бы tmp (SIGKILL без trap)"
    assert lock.read_bytes() == _lines(COORD)

    code, out, err = _run(bash, ["request", "s2", "heavy", "10", "b"], lock_dir, {"MACHINE_GATE_TMP_WAIT_SEC": "1"})
    assert (code, out) == (2, ""), (code, out, err)
    assert err == "machine_gate: machine.lock.tmp exists (another grant/close running, or a leftover)\n"
    assert tmp.exists()

    old = time.time() - 120
    os.utime(tmp, (old, old))
    code, out, err = _run(bash, ["request", "s2", "heavy", "10", "b"], lock_dir, {"MACHINE_GATE_TMP_WAIT_SEC": "1"})
    assert (code, out, err) == (0, "GRANTED until ~00:10\n", "")
    assert lock.read_bytes() == _lines(COORD, "window: s2 | heavy | b | until ~00:10")
    assert _listing(lock_dir) == ["machine.lock"]


def test_wait_gets_window_after_coordinator_close_and_leaves_clean_dir(bash: str, lock_dir: Path) -> None:
    """Живой wait + close координатора (close окон не выдаёт): wait выдаёт себе окно сам, tmp не остаётся."""
    lock = lock_dir / "machine.lock"
    lock.write_bytes(_lines(COORD, W_S1, WAIT_S2))
    p = _spawn(bash, ["wait", "s2", "--timeout", "1"], lock_dir)
    try:
        time.sleep(2.5)
        assert p.poll() is None
        code, _, err = _run(bash, ["close", "c1", "s1"], lock_dir)
        assert code == 0, err
        rc, out = _finish(p)
    finally:
        if p.poll() is None:
            p.kill()
            p.communicate()
    assert (rc, out) == (0, "GRANTED until ~00:10\n")
    assert lock.read_bytes() == _lines(COORD, "window: s2 | heavy | b | until ~00:10")
    assert _listing(lock_dir) == ["machine.lock"]


def test_new_request_during_release_sees_fresh_lock_after_the_write(bash: str, lock_dir: Path, tmp_path: Path) -> None:
    """release s1 держит запись (промоут s2); request s3 стартует по старому замку, ждёт tmp и решает заново."""
    lock = lock_dir / "machine.lock"
    lock.write_bytes(_lines(COORD, W_S1, WAIT_S2))
    env = _hold_env(tmp_path)
    mark, go = Path(env["MV_MARK"]), Path(env["MV_GO"])
    a = _spawn(bash, ["release", "s1"], lock_dir, env)
    b = None
    try:
        assert _wait_until(mark.exists, 30), "release не дошёл до mv"
        b = _spawn(bash, ["request", "s3", "heavy", "20", "c"], lock_dir, env)
        time.sleep(1.5)
        assert b.poll() is None, "request не дождался tmp у release"
        go.write_bytes(b"go")
        rc_b, out_b = _finish(b)
        rc_a, out_a = _finish(a)
    finally:
        go.write_bytes(b"go")
        for proc in (a, b):
            if proc is not None and proc.poll() is None:
                proc.kill()
                proc.communicate()
    assert (rc_a, out_a) == (0, "RELEASED\nNEXT s2 until ~00:10\n")
    assert (rc_b, out_b) == (0, "QUEUED position 1\n")
    assert lock.read_bytes() == _lines(
        COORD, "window: s2 | heavy | b | until ~00:10", "waiting: s3 | heavy | c | ~20 min"
    )
    assert _listing(lock_dir) == ["machine.lock"]


def test_same_session_request_during_release_leaves_no_duplicate(bash: str, lock_dir: Path, tmp_path: Path) -> None:
    """Повторный request той же сессии s2 во время release s1: быстрый путь отвечает по своему чтению, замок цел."""
    lock = lock_dir / "machine.lock"
    lock.write_bytes(_lines(COORD, W_S1, WAIT_S2))
    env = _hold_env(tmp_path)
    mark, go = Path(env["MV_MARK"]), Path(env["MV_GO"])
    a = _spawn(bash, ["release", "s1"], lock_dir, env)
    b = None
    try:
        assert _wait_until(mark.exists, 30), "release не дошёл до mv"
        b = _spawn(bash, ["request", "s2", "heavy", "10", "b"], lock_dir, env)
        rc_b, out_b = _finish(b, timeout=20)
        go.write_bytes(b"go")
        rc_a, _ = _finish(a)
    finally:
        go.write_bytes(b"go")
        for proc in (a, b):
            if proc is not None and proc.poll() is None:
                proc.kill()
                proc.communicate()
    assert rc_a == 0
    assert (rc_b, out_b) == (0, "QUEUED position 1\n")
    assert lock.read_bytes() == _lines(COORD, "window: s2 | heavy | b | until ~00:10")
    assert _listing(lock_dir) == ["machine.lock"]
