# -*- coding: utf-8 -*-
"""Юнит-тест вердиктов стенда T1.9b (без бэкенда): зависание = FAIL, края порогов - литералы из T1.9b_tests.md.

Запуск: ``python -m pytest -q --tb=short
docs/reports/2026-10-26_lifecycle-stop-ownership_1.9b-stand/test_stand_l9_verdict.py``
(класс шлюза light). Модуль стенда грузится по пути: каталог отчёта не пакет.
"""

from __future__ import annotations

import importlib.util
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("stand_l9", HERE / "stand_l9.py")
assert _spec is not None and _spec.loader is not None
st = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(st)


# ---- S1 ----
def _s1(reply, status="stopped", lost=0, ok=True):
    return {"reply_s": reply, "status": status, "lost": lost, "precondition_ok": ok}


def test_s1_all_in_range_passes_with_edges():
    runs = [_s1(0.85), _s1(1.20)] + [_s1(1.0)] * 8
    assert st.judge_s1(runs)["verdict"] == "PASS"


def test_s1_just_outside_range_fails():
    assert st.judge_s1([_s1(0.8499)] + [_s1(1.0)] * 9)["verdict"] == "FAIL"
    assert st.judge_s1([_s1(1.2001)] + [_s1(1.0)] * 9)["verdict"] == "FAIL"


def test_s1_hang_without_reply_is_fail_with_text():
    res = st.judge_s1([_s1(None, status=None)] + [_s1(1.0)] * 9)
    assert res["verdict"] == "FAIL" and res["hangs"] == 1
    assert any("ЗАВИСАНИЕ" in r and "нет ответа" in r for r in res["reasons"])


def test_s1_hang_by_elapsed_5s_crashed_is_fail_not_ok():
    res = st.judge_s1([_s1(5.06, status="crashed", lost=1)] + [_s1(1.0)] * 9)
    assert res["verdict"] == "FAIL" and res["hangs"] == 1
    assert any("5.06" in r for r in res["reasons"])


def test_s1_hang_threshold_edge_4_5():
    assert st.is_hung(4.5) is True
    assert st.is_hung(4.4999) is False
    assert st.is_hung(1.0, "crashed") is True
    assert st.is_hung(1.0, "stopped", lost=1) is True


def test_s1_precondition_failure_is_fail_invalid():
    res = st.judge_s1([_s1(None, ok=False)] + [_s1(1.0)] * 9)
    assert res["verdict"] == "FAIL" and res["invalid"] is True


# ---- S2 ----
def _s2(lat, reply=3.1):
    return {"stop_reply_s": reply, "latencies": lat, "waited_s": reply}


def test_s2_edges_pass_at_0_5_and_p99_0_15():
    # 99 проб по 0.05 и одна 0.5: max=0.5 (граница), p99 (ранг 99) = 0.05 -> PASS
    lat = [0.05] * 99 + [0.5]
    assert st.judge_s2([_s2(lat)])["verdict"] == "PASS"
    # 98 по 0.05 и две по 0.15: p99 = 0.15 (граница) -> PASS
    assert st.judge_s2([_s2([0.05] * 98 + [0.15, 0.15])])["verdict"] == "PASS"


def test_s2_over_edges_fail():
    assert st.judge_s2([_s2([0.05] * 99 + [0.5001])])["verdict"] == "FAIL"
    # p99 = 0.1501 при max <= 0.5
    res = st.judge_s2([_s2([0.05] * 98 + [0.1501, 0.1501])])
    assert res["verdict"] == "FAIL" and any("p99" in r for r in res["reasons"])


def test_s2_old_numbers_2_0_to_2_7_fail():
    res = st.judge_s2([_s2([2.0, 2.3, 2.7] + [0.05] * 27)])
    assert res["verdict"] == "FAIL" and any("max ответа" in r for r in res["reasons"])


def test_s2_unanswered_sample_and_stop_hang_fail():
    assert st.judge_s2([_s2([0.05] * 29 + [None])])["verdict"] == "FAIL"
    res = st.judge_s2([{"stop_reply_s": None, "latencies": [0.05] * 30, "waited_s": 25.0}])
    assert res["verdict"] == "FAIL" and res["hangs"] == 1 and any("ЗАВИСАНИЕ" in r for r in res["reasons"])


def test_s2_short_stop_or_few_samples_is_invalid_fail():
    short = st.judge_s2([_s2([0.05] * 30, reply=2.4999)])
    assert short["verdict"] == "FAIL" and short["invalid"] is True
    few = st.judge_s2([_s2([0.05] * 19)])
    assert few["verdict"] == "FAIL" and few["invalid"] is True
    assert st.judge_s2([_s2([0.05] * 20, reply=2.5)])["verdict"] == "PASS"


# ---- S3 ----
def _s3(delivery, relay, stop=3.1):
    return {"stop_reply_s": stop, "delivery_s": delivery, "relay_reply_s": relay, "waited_s": stop}


def test_s3_edges_and_missing_signal():
    assert st.judge_s3([_s3(0.5, 0.5)])["verdict"] == "PASS"
    assert st.judge_s3([_s3(0.5001, 0.1)])["verdict"] == "FAIL"
    assert st.judge_s3([_s3(0.1, 0.5001)])["verdict"] == "FAIL"
    assert st.judge_s3([_s3(None, 0.1)])["verdict"] == "FAIL"  # нет сигнала доставки - не PASS
    assert st.judge_s3([_s3(0.1, None)])["verdict"] == "FAIL"


def test_s3_stop_hang_is_fail():
    res = st.judge_s3([{"stop_reply_s": None, "delivery_s": 0.1, "relay_reply_s": 0.1, "waited_s": 25.0}])
    assert res["verdict"] == "FAIL" and res["hangs"] == 1


# ---- S4 ----
def _s4(line=1.05, exit_=3.5, dns=0, queued="system_stopping"):
    return {"shutdown_line_s": line, "pm_exit_s": exit_, "dns": dns, "queued_error": queued, "precondition_ok": True}


def test_s4_edges():
    assert st.judge_s4([_s4(1.2, 4.5)])["verdict"] == "PASS"
    assert st.judge_s4([_s4(1.2001)])["verdict"] == "FAIL"
    assert st.judge_s4([_s4(exit_=4.5001)])["verdict"] == "FAIL"
    assert st.judge_s4([_s4(dns=1)])["verdict"] == "FAIL"
    assert st.judge_s4([_s4(queued="executor_busy")])["verdict"] == "FAIL"
    assert st.judge_s4([_s4(queued=None)])["verdict"] == "FAIL"


def test_s4_pm_never_exited_is_hang_fail_with_elapsed():
    run = _s4(exit_=None)
    run["waited_s"] = 40.0
    res = st.judge_s4([run])
    assert res["verdict"] == "FAIL" and res["hangs"] == 1 and any("40.0" in r for r in res["reasons"])


def test_s4_old_numbers_fail():
    assert st.judge_s4([_s4(line=3.3, exit_=7.0, dns=1, queued=None)])["verdict"] == "FAIL"


# ---- S5 ----
def _s5_ok():
    runs = [{"kind": "restart", "target": "x", "elapsed_s": 3.0, "ok": True}] * 3
    runs += [{"kind": "activate", "target": "r", "elapsed_s": 4.0, "ok": True}]
    runs += [{"kind": "shutdown", "target": f"run {i}", "elapsed_s": 1.5, "survivors": []} for i in range(10)]
    return runs


def test_s5_pass_and_strict_inequalities():
    assert st.judge_s5(_s5_ok())["verdict"] == "PASS"
    bad_restart = _s5_ok()
    bad_restart[0] = {"kind": "restart", "target": "x", "elapsed_s": 5.0, "ok": True}
    assert st.judge_s5(bad_restart)["verdict"] == "FAIL"  # < 5.0 строго
    bad_tree = _s5_ok()
    bad_tree[-1] = {"kind": "shutdown", "target": "run 9", "elapsed_s": 2.0, "survivors": []}
    assert st.judge_s5(bad_tree)["verdict"] == "FAIL"  # < 2.0 строго
    bad_act = _s5_ok()
    bad_act[3] = {"kind": "activate", "target": "r", "elapsed_s": 5.0, "ok": True}
    assert st.judge_s5(bad_act)["verdict"] == "FAIL"


def test_s5_hang_survivor_and_incomplete_fail():
    hang = _s5_ok()
    hang[-1] = {"kind": "shutdown", "target": "run 9", "elapsed_s": None, "waited_s": 30.0, "survivors": [123]}
    res = st.judge_s5(hang)
    assert res["verdict"] == "FAIL" and res["hangs"] == 1
    short = _s5_ok()[:-1]
    assert st.judge_s5(short)["verdict"] == "FAIL"


# ---- контроль ----
def test_control_distinguishes_only_when_before_numbers_return():
    rows = {
        "S2": {"verdict": "FAIL", "max_latency_s": 2.4},
        "S3": {"verdict": "FAIL", "max_delivery_s": 2.0},
        "S4": {"verdict": "FAIL", "min_shutdown_line_s": 3.0},
    }
    assert st.judge_control(rows)["distinguishes"] is True
    weak = {**rows, "S2": {"verdict": "FAIL", "max_latency_s": 1.99}}
    assert st.judge_control(weak)["distinguishes"] is False
    passing = {**rows, "S3": {"verdict": "PASS", "max_delivery_s": 0.1}}
    assert st.judge_control(passing)["distinguishes"] is False


# ---- статистика и логи ----
def test_p99_nearest_rank_and_stats():
    assert st.percentile_nearest_rank(list(map(float, range(1, 101))), 99.0) == 99.0
    assert st.percentile_nearest_rank([], 99.0) is None
    s = st.stats([1.0, 2.0, 3.0, None])
    assert (s["min"], s["median"], s["max"], s["unanswered"], s["n"]) == (1.0, 2.0, 3.0, 1, 4)


def test_scan_log_texts_dedups_across_files_and_finds_shutdown_ts():
    line_a = (
        "#269 2026-08-26 08:40:42,349 [INFO] [ProcessManager] ProcessManager: System shutdown requested via command"
    )
    line_b = (
        "#270 2026-08-26 08:40:45,000 [WARNING] [ProcessManager] Process 'slow' did not stop in 5.0s, terminating..."
    )
    line_c = (
        "#9 2026-08-26 08:40:46,000 [INFO] [ProcessManager] stop summary: reported=2, not reported/lost: ['devices']"
    )
    # те же записи во втором файле под другим счётчиком - не должны удваиваться
    res = st.scan_log_texts(
        {
            "ProcessManager/messages.log": "\n".join([line_a, line_b, line_c]),
            "ProcessManager/system.log": "\n".join([line_a.replace("#269", "#1"), line_b.replace("#270", "#2")]),
        }
    )
    assert (res["dns"], res["lost"], res["terminating"]) == (1, 1, 1)
    assert res["dns_by_dir"] == {"ProcessManager": 1}
    expected = time.mktime(time.strptime("2026-08-26 08:40:42", "%Y-%m-%d %H:%M:%S")) + 0.349
    assert abs(res["shutdown_ts"] - expected) < 1e-3
