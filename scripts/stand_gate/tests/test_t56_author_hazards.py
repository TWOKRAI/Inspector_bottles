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


def _drain(cycles, *, call_cost: float, target: int = 104, cap_s: float = 30.0):
    """``cycles`` — ответы опросов по порядку (последний повторяется); ``t0`` = 0."""
    clock = _Clock()
    calls = []
    it = iter(cycles)

    def poll():
        calls.append(clock.t)
        clock.t += call_cost
        return next(it, cycles[-1])

    out: dict = {}

    def target_fn():
        out.update(R.measure_drain(poll, target, 0.0, step_s=0.02, cap_s=cap_s, clock=clock, sleep=clock.sleep))

    th = threading.Thread(target=target_fn, daemon=True)
    th.start()
    th.join(5.0)
    assert not th.is_alive(), "measure_drain завис"
    return out, calls, clock


def test_drain_one_poll_call_per_trace_point_and_step_is_20ms():
    out, calls, _ = _drain([100, 101, 103, 104], call_cost=0.003)
    assert len(calls) == len(out["drain_trace"]) == 4
    assert out["drain_poll_period_s"] == pytest.approx(0.02, abs=1e-9)
    assert out["drain_s"] == pytest.approx(0.063, abs=1e-9)  # три шага по 0.02 + вызов 0.003


def test_drain_returns_at_first_poll_reaching_the_target():
    out, calls, _ = _drain([100, 104, 110, 120], call_cost=0.001, target=104)
    assert len(calls) == 2 and out["drain_trace"][-1][1] == 104


def test_slow_poll_is_not_measured_not_green():
    """Вызов 0.15 с: период > 0.1 → вердикт NOT_MEASURED (код 1), даже если drain_s мал."""
    out, _, clock = _drain([104], call_cost=0.15)
    assert out["drain_poll_period_s"] > 0.1
    check = A._drain_check({"drain_s": out["drain_s"], "drain_poll_period_s": out["drain_poll_period_s"]})
    assert check.status == A.NOT_MEASURED and check.failed
    assert "NOT_MEASURED" in check.line() and check.line().startswith("FAIL drain")


def test_call_longer_than_step_never_sleeps_negative():
    out, _, clock = _drain([100, 102, 104], call_cost=0.05)
    assert clock.sleeps and min(clock.sleeps) == 0.0


def test_queue_that_never_drains_returns_none_at_cap():
    out, calls, _ = _drain([100], call_cost=0.001, cap_s=1.0)
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
    lock.write_text("other-session | 2026-10-03 15:00 | measure | abc | 8775", encoding="utf-8")
    with pytest.raises(R.StandRunError):
        R.check_stand_lock(lock, "t56-lead")
    lock.write_text("t56-lead | 2026-10-03 15:00 | measure | abc | 8775", encoding="utf-8")
    R.check_stand_lock(lock, "t56-lead")


# =================================================================================
# Раунд 2 (ревью кода, итерация 1): замок, сорванная пауза, дренаж от отправки worker.start,
# ошибка снимка. Каждый тест ниже был КРАСНЫМ на cbbae2ff6 (до правки) — вывод в отчёте.
# =================================================================================
import json  # noqa: E402
import subprocess  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures"
_LOCK_LINE = "inspector-bottles-79 | 2026-10-03 15:00 | measure | abc | 8775"


def _fixture(name: str) -> dict:
    return json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))


def test_r2_default_lock_is_beside_the_main_tree_not_in_the_worktree():
    tree = Path(__file__).resolve().parents[3]
    common = subprocess.run(
        ["git", "rev-parse", "--git-common-dir"], cwd=tree, capture_output=True, text=True, check=True
    ).stdout.strip()
    expected = (tree / common).resolve().parent.parent / "stand.lock"
    assert R.default_lock_path(tree) == expected


def test_r2_lock_without_token_is_a_run_error_even_when_the_file_exists(tmp_path):
    """Вход ревьюера: файл с чужой сессией, токен None — сегодня проходит, обязан дать код 2."""
    lock = tmp_path / "stand.lock"
    lock.write_text(_LOCK_LINE + "\n", encoding="utf-8")
    with pytest.raises(R.StandRunError):
        R.check_stand_lock(lock, None)


def test_r2_lock_in_a_mode_other_than_measure_is_a_run_error(tmp_path):
    lock = tmp_path / "stand.lock"
    lock.write_text("inspector-bottles-79 | 2026-10-03 15:00 | debug | abc | 8775\n", encoding="utf-8")
    with pytest.raises(R.StandRunError):
        R.check_stand_lock(lock, "inspector-bottles-79")


def test_r2_lock_with_our_session_in_measure_passes(tmp_path):
    lock = tmp_path / "stand.lock"
    lock.write_text(_LOCK_LINE + "\n", encoding="utf-8")
    R.check_stand_lock(lock, "inspector-bottles-79")
    with pytest.raises(R.StandRunError):  # токен — другая сессия: замок чужой
        R.check_stand_lock(lock, "inspector-bottles-80")
    with pytest.raises(R.StandRunError):  # префикс чужой сессии — не наша сессия (не подстрока)
        R.check_stand_lock(lock, "inspector-bottles-7")


def test_r2_ordered_pause_that_did_not_happen_is_a_run_error():
    for paused in (None, False):
        with pytest.raises(R.StandRunError):
            R.require_pause(True, paused, {"pause_error": "executor worker not found"})
    R.require_pause(True, True, {})
    R.require_pause(False, None, {})


@pytest.mark.parametrize("variant", ["pause_error", "tag_P10"])
def test_r2_p10_json_without_pause_is_input_error_not_case_E(variant):
    data = _fixture("green_P10")
    del data["pause"]
    if variant == "pause_error":
        data["pause_error"] = "executor worker not found"
    else:
        data["tag"] = "P10"
    with pytest.raises(A.GateInputError):
        A.analyze(data, throughput_gate=False)


@pytest.mark.parametrize(
    "base, site",
    [("green_D100", "s0.processor"), ("green_D100", "s2.inspector"), ("green_P10", "pause.after.renderer")],
)
def test_r2_snapshot_with_error_is_input_error_not_zeros(base, site):
    data = _fixture(base)
    cur = data
    *head, last = site.split(".")
    for part in head:
        cur = cur[part]
    cur[last] = {"workers": {}, "rs": {}, "error": "TimeoutError: introspect"}
    with pytest.raises(A.GateInputError):
        A.analyze(data, throughput_gate=False)


class _FakeTime:
    def __init__(self) -> None:
        self.t = 100.0

    def perf_counter(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.t += max(0.0, s)


class _FakeStand:
    """Поддельный драйвер: исполнитель возобновляется в момент ПОЛУЧЕНИЯ worker.start, ответ на команду
    приходит через 0.12 с, настоящий дренаж (backlog 3 + 1 кадр) занимает 0.15 с. chain_queue.size = 3
    и во время паузы, и в установившемся режиме — сигнал «очередь вернулась к медиане» вырожден."""

    BASE = 1000

    def __init__(self, ft: _FakeTime) -> None:
        self.ft = ft
        self.resumed_at: float | None = None
        self.status_calls: list[float] = []

    def _cycles(self) -> int:
        if self.resumed_at is not None and self.ft.t >= self.resumed_at + 0.15:
            return self.BASE + 4
        return self.BASE

    def introspect_status(self, name):
        self.status_calls.append(self.ft.t)
        self.ft.t += 0.002
        return {"result": {"workers": {"pipeline_executor": {"cycles": self._cycles()}}}}

    def introspect_queues(self, name):
        self.ft.t += 0.002
        return {"result": {"chain_queue": {"size": 3, "maxsize": 64}}}

    def introspect_router_stats(self, name):
        return {"result": {"router_stats": {}}}

    def send_command(self, proc, cmd, payload=None, timeout=10):
        if cmd == "worker.start":
            self.resumed_at = self.ft.t  # возобновление по получению
            self.ft.t += 0.12  # ответ через 0.12 с
        return {"success": True}


def test_r2_drain_is_timed_from_sending_worker_start_and_counts_cycles(monkeypatch):
    """Сегодня: PASS ~0.02 с (очередь «уже» на медиане). После правки: ≥ 0.15 с → FAIL drain."""
    ft = _FakeTime()
    monkeypatch.setattr(R, "time", ft)
    drv = _FakeStand(ft)
    res: dict = {}
    box: dict = {}

    def target():
        box["ok"] = R.pause_executor(drv, res, 10)

    th = threading.Thread(target=target, daemon=True)
    th.start()
    th.join(10.0)
    assert not th.is_alive(), "pause_executor завис"
    assert box.get("ok") is True
    pause = {k: v for k, v in res["pause"].items() if k not in ("after", "drain_trace")}
    assert pause.get("drain_s") is not None and pause["drain_s"] >= 0.15, pause
    assert pause["backlog"] == 3
    # Первый интервал считается от t0 и включает ответ на команду (0.12 с): период 0.122 > 0.1 → вердикт
    # NOT_MEASURED (строка ``FAIL drain``, код 1). Это честно: момент завершения известен с точностью до
    # 0.122 с, а нижняя граница ничего не доказывает — бэклог паузы при 5.3 уходит маркерами, которые
    # cycles не пишут, и цель +backlog+1 набирают свежие кадры (раунд 2c, P10_1: backlog 3, Δcycles 10).
    assert pause["drain_poll_period_s"] >= 0.12, pause
    assert pause["drain_lower_s"] == pytest.approx(0.14, abs=1e-9), pause  # НАЧАЛО второго опроса
    check = A._drain_check(res["pause"])
    assert check.status == A.NOT_MEASURED, check.line()
    assert check.line().startswith("FAIL drain: NOT_MEASURED"), check.line()
    assert drv.status_calls, "дренаж обязан опрашивать introspect_status (cycles), а не очередь"


def test_r2c_drain_lower_is_a_report_number_and_never_changes_the_verdict():
    slow_poll = {"drain_s": 0.3, "drain_poll_period_s": 0.25}
    assert A._drain_check(slow_poll).status == A.NOT_MEASURED
    assert A._drain_check({**slow_poll, "drain_lower_s": 0.2}).status == A.NOT_MEASURED
    fast = {"drain_s": 0.05, "drain_poll_period_s": 0.02}
    assert A._drain_check({**fast, "drain_lower_s": 0.5}).status == A.PASS
    assert A._drain_check({"drain_s": 0.2, "drain_poll_period_s": 0.02, "drain_lower_s": 0.0}).status == A.FAIL


def test_r2b_drain_lower_is_zero_when_the_first_poll_already_shows_completion():
    out, _, _ = _drain([104], call_cost=0.003)
    assert out["drain_lower_s"] == 0.0


def test_r2b_drain_lower_is_the_last_poll_below_target():
    out, _, _ = _drain([100, 101, 103, 104], call_cost=0.003)
    assert out["drain_lower_s"] == pytest.approx(0.04, abs=1e-9)  # НАЧАЛО третьего опроса: 2 шага по 0.02


def test_r2c_drain_lower_is_the_start_of_the_last_poll_below_target():
    """Вход ревьюера: опрос длится 0.06 с, цель достигнута на 0.07 с (значение снимается в начале
    опроса). Опросы: [0, 0.06) ниже, [0.06, 0.12) ниже (снят в 0.06), [0.12, 0.18) — цель. Нижняя
    граница — 0.06 (начало второго), а не 0.12 (его конец)."""
    clock = _Clock()

    def poll():
        value = 104 if clock.t >= 0.07 else 100
        clock.t += 0.06
        return value

    out = R.measure_drain(poll, 104, 0.0, step_s=0.02, cap_s=5.0, clock=clock, sleep=clock.sleep)
    assert out["drain_lower_s"] == pytest.approx(0.06, abs=1e-9), out
    assert out["drain_s"] == pytest.approx(0.18, abs=1e-9), out


def test_r2c_lock_with_more_than_one_holder_is_a_conflict(tmp_path):
    lock = tmp_path / "stand.lock"
    lock.write_text(
        "inspector-bottles-79 | 2026-10-03 15:00 | measure | abc | 8775\n"
        "otel-lead | 2026-10-03 15:01 | measure | def | 8776\n",
        encoding="utf-8",
    )
    with pytest.raises(R.StandRunError, match="держателей замка 2"):
        R.check_stand_lock(lock, "inspector-bottles-79")
