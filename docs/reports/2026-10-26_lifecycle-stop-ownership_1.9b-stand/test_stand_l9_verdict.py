# -*- coding: utf-8 -*-
# ruff: noqa: E501  (русские docstring/строки плана длиннее 120)
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


# ---- раунд 2 ----
def test_alternation_strict_and_equal_counts():
    assert st.check_alternation(["branch", "main", "branch", "main"]) == []
    assert st.check_alternation(["main", "branch", "main", "branch"]) == []
    blocks = st.check_alternation(["branch", "branch", "main", "main"])
    assert any("не чередуется" in r for r in blocks)
    assert any("не поровну" in r for r in st.check_alternation(["branch", "main", "branch"]))
    assert any("неизвестные" in r for r in st.check_alternation(["branch", "x"]))


_PM_LOG = (
    "#1 2026-10-26 15:00:10,000 [INFO] [ProcessManager] ProcessManager: Process 'camera_0' restarted\n"
    "#2 2026-10-26 15:00:10,000 [INFO] [ProcessManager] ProcessManager: Process 'camera_0' restarted\n"  # дубль в другом файле
    "#3 2026-10-26 15:00:20,500 [INFO] [ProcessManager] ProcessManager: Process 'camera_0' restarted\n"
    "#4 2026-10-26 15:00:12,250 [INFO] [ProcessManager] ProcessManager: Process 'devices' restarted\n"
    "#5 2026-10-26 15:00:13,000 [INFO] m.m.x: something else\n"
)


def test_scan_restarted_lines_dedups_and_sorts():
    got = st.scan_restarted_lines(_PM_LOG)
    assert sorted(got) == ["camera_0", "devices"]
    assert len(got["camera_0"]) == 2 and got["camera_0"][1] - got["camera_0"][0] == 10.5
    assert len(got["devices"]) == 1


def test_pair_restart_records_marks_early_reply_with_tolerance():
    base = st.parse_log_ts("2026-10-26 15:00:10,000")
    lines = {"camera_0": [base, base + 10.5]}
    sent = [
        {"target": "camera_0", "t_send_wall": base - 4.0, "t_reply_wall": base + 0.2},  # после строки: не ранний
        {"target": "camera_0", "t_send_wall": base + 5.0, "t_reply_wall": base + 10.5 - 0.7},  # на 0,7 с раньше
        {"target": "camera_0", "t_send_wall": base + 5.0, "t_reply_wall": base + 10.5 - 0.04},  # в допуске 0,05
        {"target": "devices", "t_send_wall": base, "t_reply_wall": base + 1.0},  # нет строки
    ]
    got = st.pair_restart_records(sent, {"camera_0": lines["camera_0"] + [base + 10.5]})
    assert [g["early"] for g in got] == [False, True, False, None]
    assert got[1]["reply_minus_restarted_s"] == -0.7


def _rr(tree, target="camera_0", rep=1, el=4.0, ok=True, early=False, err=None):
    return {
        "tree": tree,
        "session": 1,
        "target": target,
        "rep": rep,
        "elapsed_s": el,
        "ok": ok,
        "early": early,
        "request_error": err,
    }


def test_judge_restart_ab_pass_and_each_fail_reason():
    recs = [_rr("branch"), _rr("main", el=4.4)]
    ok = st.judge_restart_ab(recs, ["branch", "main"])
    assert ok["verdict"] == "PASS" and ok["spread"]["branch/camera_0"]["max"] == 4.0
    assert (
        st.judge_restart_ab(
            [_rr("branch", early=True) | {"reply_minus_restarted_s": -0.7}, _rr("main")], ["branch", "main"]
        )["verdict"]
        == "FAIL"
    )
    assert st.judge_restart_ab([_rr("branch", err="timeout"), _rr("main")], ["branch", "main"])["verdict"] == "FAIL"
    assert st.judge_restart_ab([_rr("branch", ok=False), _rr("main")], ["branch", "main"])["verdict"] == "FAIL"
    assert (
        st.judge_restart_ab([_rr("branch", el=5.0), _rr("main")], ["branch", "main"])["verdict"] == "FAIL"
    )  # < 5,0 строго
    assert st.judge_restart_ab([_rr("branch", el=None), _rr("main")], ["branch", "main"])["verdict"] == "FAIL"
    assert st.judge_restart_ab([_rr("branch"), _rr("branch")], ["branch", "branch"])["verdict"] == "FAIL"  # блок
    assert (
        st.judge_restart_ab([_rr("branch"), _rr("main", el=9.0)], ["branch", "main"])["verdict"] == "PASS"
    )  # main - база


def _tx(n, branch=1.5, main=1.5):
    recs, order = [], []
    for i in range(1, n + 1):
        for tree, v in (("branch", branch), ("main", main)):
            order.append(tree)
            recs.append({"tree": tree, "run": i, "pm_exit_s": v})
    return recs, order


def test_judge_tree_exit_ab_strict_2s_ten_of_ten_each_tree():
    recs, order = _tx(10)
    assert st.judge_tree_exit_ab(recs, order)["verdict"] == "PASS"
    recs, order = _tx(10, branch=1.999)
    assert st.judge_tree_exit_ab(recs, order)["verdict"] == "PASS"
    recs, order = _tx(10, branch=2.0)
    assert st.judge_tree_exit_ab(recs, order)["verdict"] == "FAIL"  # < 2,0 строго
    recs, order = _tx(10, main=2.5)
    assert st.judge_tree_exit_ab(recs, order)["verdict"] == "FAIL"  # порог и на main - литерал
    recs, order = _tx(10)
    recs[2]["pm_exit_s"] = None
    res = st.judge_tree_exit_ab(recs, order)
    assert res["verdict"] == "FAIL" and any("ЗАВИСАНИЕ" in r for r in res["reasons"])
    recs, order = _tx(9)
    res = st.judge_tree_exit_ab(recs, order)
    assert res["verdict"] == "FAIL" and res["invalid"] is True
    recs, order = _tx(10)
    assert st.judge_tree_exit_ab(recs, sorted(order))["verdict"] == "FAIL"  # блоки


def test_watch_pid_exit_sees_a_real_process_exit():
    import subprocess  # nosec B404 — тест: свой интерпретатор, литеральный код
    import sys

    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(0.5)"])  # nosec B603
    box: dict = {}
    th = st.watch_pid_exit(proc.pid, box, "pm", limit_s=20.0)
    t0 = time.monotonic()
    th.join(20.0)
    proc.wait(5)
    assert "pm" in box and 0.2 <= box["pm"] - t0 <= 5.0
    gone: dict = {}
    st.watch_pid_exit(proc.pid, gone, "pm", limit_s=5.0).join(6.0)
    assert "pm" in gone  # уже вышел: не зависает


# ---- окна остановки: R2-C на значениях по умолчанию, остальное с override 8,0 ----
def test_stop_windows_default_has_no_override_and_override_is_8():
    d, o = st.stop_windows(True), st.stop_windows(False)
    assert d == {"mode": "default", "stop_process_timeout": None, "shutdown_timeout": None}
    assert o == {"mode": "override", "stop_process_timeout": 8.0, "shutdown_timeout": 8.0}


def _backend_for(tmp_path, default_windows):
    from types import SimpleNamespace

    root = HERE.parents[2]
    ctx = SimpleNamespace(
        root=root,
        out=tmp_path,
        python="x",
        recipe=st.DEFAULT_REPO_RECIPE,
        door="direct",
        boot_timeout_s=1.0,
        default_windows=default_windows,
    )
    be = st.Backend(ctx, f"win_{default_windows}")
    be.workdir.mkdir(parents=True, exist_ok=True)
    return be


def test_backend_temp_system_yaml_stop_timeout_override_vs_default(tmp_path):
    import yaml

    over = _backend_for(tmp_path, False)
    over._write_configs()
    assert yaml.safe_load((over.workdir / "system.yaml").read_text(encoding="utf-8"))["system"]["stop_timeout"] == 8.0
    assert over.windows["mode"] == "override"

    dflt = _backend_for(tmp_path, True)
    dflt._write_configs()
    written = yaml.safe_load((dflt.workdir / "system.yaml").read_text(encoding="utf-8"))["system"]["stop_timeout"]
    assert written == 5.0  # значение system.yaml дерева (backend/config/system.yaml), не 8.0
    assert dflt.windows == {
        "mode": "default",
        "stop_process_timeout": None,
        "shutdown_timeout": None,
        "system_yaml_stop_timeout": 5.0,
    }


def test_round2_tree_exit_runs_on_default_windows_restart_and_s4_keep_override(monkeypatch):
    from pathlib import Path
    from types import SimpleNamespace

    base = SimpleNamespace(root=Path("."), recipe="r", default_windows=False, round2=False)
    seen = []
    monkeypatch.setattr(st, "write_run", lambda *a, **k: None)
    monkeypatch.setattr(
        st,
        "_tree_exit_once",
        lambda c, tree, run, seq: (
            seen.append((tree, c.default_windows)) or {"tree": tree, "run": run, "pm_exit_s": 1.0}
        ),
    )
    st.run_r2_tree_exit(base, Path("main"), 1)
    assert seen == [("branch", True), ("main", True)]  # R2-C: окна по умолчанию, строго по очереди
    assert base.default_windows is False  # исходный контекст (R2-A, R2-B) остаётся на override 8,0
    assert st._tree_ctx(base, Path("m")).default_windows is False


def test_pair_restart_records_driver_timeout_is_not_an_early_reply():
    base = st.parse_log_ts("2026-10-26 15:00:10,000")
    sent = [{"target": "camera_0", "t_send_wall": base - 5.0, "t_reply_wall": base - 0.5, "request_error": "timeout"}]
    got = st.pair_restart_records(sent, {"camera_0": [base]})
    assert got[0]["early"] is None and got[0]["reply_minus_restarted_s"] is None


# ---- S6 (T1.10): outcome terminated, success True, ответ 5,0-5,3 с ----
def _s6(reply_s=5.1, outcome="terminated", success=True, reply="default", ok=True):
    if reply == "default":
        reply = {"success": success, "process_name": "slow", "outcome": outcome}
    return {"reply_s": reply_s, "reply": reply, "precondition_ok": ok}


def test_s6_pass_terminated_true_5_1():
    res = st.judge_s6([_s6(5.1)] * 3)
    assert res["verdict"] == "PASS" and res["outcomes"] == {"terminated": 3}


def test_s6_edges_5_0_and_5_3_pass():
    assert st.judge_s6([_s6(5.0), _s6(5.3), _s6(5.15)])["verdict"] == "PASS"


def test_s6_fail_on_exited():
    res = st.judge_s6([_s6(5.1), _s6(5.1, outcome="exited"), _s6(5.1)])
    assert res["verdict"] == "FAIL" and any("outcome='exited'" in r for r in res["reasons"])


def test_s6_fail_on_success_false():
    assert st.judge_s6([_s6(5.1, success=False)] + [_s6(5.1)] * 2)["verdict"] == "FAIL"


def test_s6_fail_on_reply_5_4_and_4_9():
    assert st.judge_s6([_s6(5.4)] + [_s6(5.1)] * 2)["verdict"] == "FAIL"
    assert st.judge_s6([_s6(4.9)] + [_s6(5.1)] * 2)["verdict"] == "FAIL"


def test_s6_fail_on_missing_reply():
    assert st.judge_s6([_s6(None, reply=None)] + [_s6(5.1)] * 2)["verdict"] == "FAIL"
    assert st.judge_s6([_s6(5.1, reply=None)] + [_s6(5.1)] * 2)["verdict"] == "FAIL"


def test_s6_precondition_failure_is_invalid_fail():
    res = st.judge_s6([_s6(ok=False)] + [_s6(5.1)] * 2)
    assert res["verdict"] == "FAIL" and res["invalid"] is True


def test_s1_outcomes_counted_and_do_not_change_verdict():
    runs = [dict(_s1(1.0), reply={"success": True, "process_name": "devices", "outcome": "exited"})] * 9
    runs.append(dict(_s1(1.0), reply={"success": True, "process_name": "devices", "outcome": "terminated"}))
    res = st.judge_s1(runs)
    assert res["verdict"] == "PASS" and res["outcomes"] == {"exited": 9, "terminated": 1}


# ---- S7 (T1.11): outcome exited, success True, ответ 6,0-6,6 с, 3 из 3 ----
def _s7(reply_s=6.2, outcome="exited", success=True, reply="default", ok=True):
    if reply == "default":
        reply = {"success": success, "process_name": "slow", "outcome": outcome}
    return {"reply_s": reply_s, "reply": reply, "precondition_ok": ok}


def test_s7_pass_exited_true_6_2():
    res = st.judge_s7([_s7(6.2)] * 3)
    assert res["verdict"] == "PASS" and res["outcomes"] == {"exited": 3}


def test_s7_edges_6_0_and_6_6_pass():
    assert st.judge_s7([_s7(6.0), _s7(6.6), _s7(6.3)])["verdict"] == "PASS"


def test_s7_fail_just_outside_edges():
    assert st.judge_s7([_s7(5.99)] + [_s7(6.2)] * 2)["verdict"] == "FAIL"
    assert st.judge_s7([_s7(6.61)] + [_s7(6.2)] * 2)["verdict"] == "FAIL"


def test_s7_fail_on_terminated():
    res = st.judge_s7([_s7(6.2, outcome="terminated")] + [_s7(6.2)] * 2)
    assert res["verdict"] == "FAIL" and any("outcome='terminated'" in r for r in res["reasons"])


def test_s7_fail_on_success_false():
    assert st.judge_s7([_s7(6.2, success=False)] + [_s7(6.2)] * 2)["verdict"] == "FAIL"


def test_s7_two_of_three_is_fail():
    res = st.judge_s7([_s7(6.2), _s7(6.2), _s7(5.2, outcome="terminated")])
    assert res["verdict"] == "FAIL" and any("прошло 2 из 3" in r for r in res["reasons"])


def test_s7_fail_on_missing_reply():
    assert st.judge_s7([_s7(None, reply=None)] + [_s7(6.2)] * 2)["verdict"] == "FAIL"


def test_s7_precondition_failure_is_invalid_fail():
    res = st.judge_s7([_s7(ok=False)] + [_s7(6.2)] * 2)
    assert res["verdict"] == "FAIL" and res["invalid"] is True


def test_s7_thresholds_are_literals():
    assert st.THRESHOLDS["S7"] == {
        "outcome": "exited",
        "success": True,
        "reply_min_s": 6.0,
        "reply_max_s": 6.6,
        "pass_runs": 3,
    }
    assert st.REPEATS["S7"] == 3


# ---- контроль S7 (--s7-control): без ключа ожидается terminated, 5,0-5,3 с ----
def test_s7_control_terminated_5_1_distinguishes():
    res = st.judge_s7_control([_s7(5.1, outcome="terminated")])
    assert res["verdict"] == "PASS" and res["distinguishes"] is True


def test_s7_control_edges_5_0_and_5_3():
    assert st.judge_s7_control([_s7(5.0, outcome="terminated")])["distinguishes"] is True
    assert st.judge_s7_control([_s7(5.3, outcome="terminated")])["distinguishes"] is True
    assert st.judge_s7_control([_s7(5.31, outcome="terminated")])["distinguishes"] is False


def test_s7_control_exited_means_stand_does_not_distinguish():
    res = st.judge_s7_control([_s7(6.2, outcome="exited")])
    assert res["verdict"] == "FAIL" and res["distinguishes"] is False
    assert any("не различает" in r and "S7 не засчитывать" in r for r in res["reasons"])


# ---- S7: сборка запуска (без бэкенда) ----
def _args(argv):
    return st.parse_args(argv)


def test_s7_not_in_scenario_all():
    assert "S7" not in st.scenarios_of(_args(["--scenario", "all"]))


def test_s7_can_be_picked_explicitly_and_cli_defaults():
    args = _args(["--scenario", "S7"])
    assert st.scenarios_of(args) == ["S7"]
    assert (args.s7_slow_stop_s, args.s7_window_s, args.s7_ceiling_s, args.s7_control) == (6.0, 10.0, 12.0, False)


def test_s7_control_requires_scenario_s7_only():
    assert st.scenarios_of(_args(["--scenario", "S7", "--s7-control"])) == ["S7"]
    for bad in (["--scenario", "all", "--s7-control"], ["--scenario", "S6,S7", "--s7-control"]):
        try:
            st.scenarios_of(_args(bad))
        except SystemExit:
            continue
        raise AssertionError(f"{bad} должен быть отвергнут")


def test_s7_control_ctx_has_one_repeat_and_main_has_three(tmp_path):
    main_ctx = st.Ctx(_args(["--scenario", "S7"]), tmp_path, tmp_path)
    ctl_ctx = st.Ctx(_args(["--scenario", "S7", "--s7-control"]), tmp_path, tmp_path)
    assert (main_ctx.n["S7"], ctl_ctx.n["S7"]) == (3, 1)
    assert (ctl_ctx.s7_pm_window_s, ctl_ctx.s7_window_s, ctl_ctx.s7_ceiling_s) == (5.0, 10.0, 12.0)


def test_add_slow_fast_sends_slow_extra_only_on_slow_record(monkeypatch):
    sent = []

    class FakeDrv:
        def send_command(self, target, cmd, args, timeout=0.0):
            sent.append((cmd, args["topology_dict"]))
            return {"success": True, "commands": [], "ready": True}

    monkeypatch.setattr(st, "leaf", lambda res: res)
    monkeypatch.setattr(st.Backend, "supervision", staticmethod(lambda drv, name=None: {name: {"alive": True}}))
    monkeypatch.setattr(st.time, "sleep", lambda s: None)
    st.add_slow_fast(FakeDrv(), None, st.S6_SLOW_CLASS, {"stop_window_s": 10.0})
    st.add_slow_fast(FakeDrv(), None)
    with_key, without_key = sent[1][1]["processes"], sent[3][1]["processes"]
    assert [p.get("stop_window_s") for p in with_key] == [10.0, None]  # slow, fast
    assert with_key[0]["process_class"] == "stand_slow_child.S6SlowChild"
    assert all("stop_window_s" not in p for p in without_key)  # S1-S6 как раньше
    assert sent[0][0] == "topology.diff" and sent[1][0] == "topology.apply"
