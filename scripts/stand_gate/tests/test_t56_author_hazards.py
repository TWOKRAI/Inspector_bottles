"""Task 5.6 — тесты автора на опасные места своего механизма (дополнение к слепой приёмке тестера).

Что может сломаться в ЭТОМ механизме, учитывая, как он построен:
  * дренаж: опрос из нескольких команд (как у stand5) делает шаг ~0.17 с и прячет порог 0.1 с —
    сторож «один вызов драйвера на опрос»; медленный вызов обязан дать NOT_MEASURED, а не зелёный;
    очередь, которая не вернулась, обязана дать ``None`` за потолок, а не вечный цикл;
    отрицательный sleep при вызове дольше шага — исключение ``ValueError`` в ``time.sleep``;
  * журнал: одинаковые строки в двух ``messages.log`` (каналы scope BUSINESS) не дубли;
    ``observability.db`` не читается вовсе (stand5 считал его текстом — 95–462 ложных дубля);
  * отчёт: второй прогон в ту же секунду не затирает первый; каталог создаётся;
  * замок: нет файла / чужой токен → ``StandRunError`` (CLI → код 2).
Время — фейковые часы: тесты не спят и не зависят от планировщика.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from scripts.stand_gate import analyze as A
from scripts.stand_gate import run as R
from scripts.stand_gate.report import write_report


class _Clock:
    def __init__(self) -> None:
        self.t = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        assert s >= 0, f"отрицательный sleep {s}"
        self.sleeps.append(s)
        self.t += s


def _drain(sizes, *, call_cost: float, baseline: float = 0, cap_s: float = 30.0):
    clock = _Clock()
    calls = []
    it = iter(sizes)

    def poll():
        calls.append(clock.t)
        clock.t += call_cost
        return next(it, sizes[-1])

    out: dict = {}

    def target():
        out.update(R.measure_drain(poll, baseline, step_s=0.02, cap_s=cap_s, clock=clock, sleep=clock.sleep))

    th = threading.Thread(target=target, daemon=True)
    th.start()
    th.join(5.0)
    assert not th.is_alive(), "measure_drain завис"
    return out, calls, clock


def test_drain_one_poll_call_per_trace_point_and_step_is_20ms():
    out, calls, _ = _drain([9, 7, 4, 0], call_cost=0.003)
    assert len(calls) == len(out["drain_trace"]) == 4
    assert out["drain_poll_period_s"] == pytest.approx(0.02, abs=1e-9)
    assert out["drain_s"] == pytest.approx(0.063, abs=1e-9)  # три шага по 0.02 + вызов 0.003


def test_drain_returns_at_first_poll_at_or_below_baseline():
    out, calls, _ = _drain([5, 3, 2, 2, 2], call_cost=0.001, baseline=3)
    assert len(calls) == 2 and out["drain_trace"][-1][1] == 3


def test_slow_poll_is_not_measured_not_green():
    """Вызов 0.15 с: период > 0.1 → вердикт NOT_MEASURED (код 1), даже если drain_s мал."""
    out, _, clock = _drain([0], call_cost=0.15)
    assert out["drain_poll_period_s"] > 0.1
    check = A._drain_check({"drain_s": out["drain_s"], "drain_poll_period_s": out["drain_poll_period_s"]})
    assert check.status == A.NOT_MEASURED and check.failed
    assert "NOT_MEASURED" in check.line() and check.line().startswith("FAIL drain")


def test_call_longer_than_step_never_sleeps_negative():
    out, _, clock = _drain([4, 3, 0], call_cost=0.05)
    assert clock.sleeps and min(clock.sleeps) == 0.0


def test_queue_that_never_drains_returns_none_at_cap():
    out, calls, _ = _drain([10], call_cost=0.001, cap_s=1.0)
    assert out["drain_s"] is None
    assert 40 <= len(calls) <= 60  # ~1 с / 0.02 с, без вечного цикла


def test_chain_queue_size_is_found_inside_the_driver_envelope():
    resp = {"result": {"queues": {"data": {"size": 3}}, "chain_queue": {"size": 7, "maxsize": 64}}}
    assert R.chain_queue_size(resp) == 7
    assert R.chain_queue_size({"result": {"queues": {}}}) is None


def _write_log(path: Path, traces: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"x event inspection: reject: brak trace={t}\n" for t in traces), encoding="utf-8")


def test_journal_same_lines_in_two_message_logs_are_not_duplicates(tmp_path):
    _write_log(tmp_path / "a" / "messages.log", ["t1", "t2", "t3"])
    _write_log(tmp_path / "b" / "messages.log", ["t1", "t2", "t3"])
    (tmp_path / "observability.db").write_text(
        "event inspection: reject: x trace=t1\n" * 50, encoding="utf-8"
    )  # текстом «внутри SQLite» — не читать
    j = R.journal(tmp_path)
    assert j["rows"] == 3 and j["dup"] == 0 and len(j["files"]) == 2


def test_journal_counts_a_real_duplicate_inside_one_file(tmp_path):
    _write_log(tmp_path / "messages.log", ["t1", "t2", "t1"])
    assert R.journal(tmp_path)["dup"] == 1


def test_report_creates_dir_and_never_overwrites_same_second(tmp_path):
    res = A.CaseResult(label="x", case="E", checks=[A.Check("dup", A.PASS, "0", "== 0")], numbers={"lag": 464})
    out = tmp_path / "deep" / "out"
    p1 = write_report([res], out, exit_code=0, host="h", now=1_800_000_000.0)
    p2 = write_report([res], out, exit_code=0, host="h", now=1_800_000_000.0)
    assert p1 != p2 and p1.is_file() and p2.is_file()
    assert "464" in p1.read_text(encoding="utf-8")


def test_lock_missing_or_foreign_is_a_run_error(tmp_path):
    lock = tmp_path / "stand.lock"
    with pytest.raises(R.StandRunError):
        R.check_stand_lock(lock, None)
    lock.write_text("owner=other-session", encoding="utf-8")
    with pytest.raises(R.StandRunError):
        R.check_stand_lock(lock, "t56-lead")
    lock.write_text("owner=t56-lead", encoding="utf-8")
    R.check_stand_lock(lock, "t56-lead")
