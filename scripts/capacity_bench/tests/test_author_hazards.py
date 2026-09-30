"""Тесты автора 4.8a на внутренние хазарды оркестрации (не acceptance — те у tester).

Что здесь может сломаться, исходя из устройства: (1) baseline-worktree остаётся на диске,
если кейс упал; (2) упавший кейс теряет уже снятые и не пишет отчёт; (3) дочерний busy-процесс
самопроверки переживает исключение прибора; (4) разбор итоговой строки pytest.
Стенд не поднимается: `subprocess.run` в `__main__` подменён, `git`/`run_case.py` — фейки.
"""

from __future__ import annotations

import contextlib
import json
import subprocess
import time
from types import SimpleNamespace

import psutil
import pytest

from scripts.capacity_bench import __main__ as bench
from scripts.capacity_bench.cpu_probe import clock_selfcheck


def _fake_run_factory(calls: list, fail_case: bool):
    real_run = subprocess.run

    def fake_run(cmd, *args, **kwargs):
        if cmd[0] == "git" and "worktree" in cmd:
            calls.append(("worktree", cmd[cmd.index("worktree") + 1]))
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if cmd[0] == "git" and "rev-parse" in cmd:
            return SimpleNamespace(returncode=0, stdout="f" * 40 + "\n", stderr="")
        if any(str(part).endswith("run_case.py") for part in cmd):
            calls.append(("case", kwargs["cwd"]))
            if fail_case:
                return SimpleNamespace(returncode=3, stdout="", stderr="boom")
            out = cmd[cmd.index("--out") + 1]
            with open(out, "w", encoding="utf-8") as f:
                json.dump({"processes": {}, "total_ext_cores": 0.0}, f)
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return real_run(cmd, *args, **kwargs)

    return fake_run


def test_baseline_worktree_removed_when_case_raises(monkeypatch):
    calls: list = []
    monkeypatch.setattr(bench.subprocess, "run", _fake_run_factory(calls, fail_case=True))
    with pytest.raises(RuntimeError, match="rc=3"):
        bench.run_matrix("quick", "a" * 40, 8775, [])
    assert [c for c in calls if c[0] == "worktree"] == [("worktree", "add"), ("worktree", "remove")]


def test_baseline_runs_before_candidate_per_case(monkeypatch):
    calls: list = []
    cases: list = []
    monkeypatch.setattr(bench.subprocess, "run", _fake_run_factory(calls, fail_case=False))
    bench.run_matrix("quick", "a" * 40, 8775, cases)
    assert [(c["height"], c["tree"]) for c in cases] == [
        (480, "baseline"),
        (480, "candidate"),
        (1080, "baseline"),
        (1080, "candidate"),
    ]
    # cwd последнего запуска кандидата — текущее дерево, базы — временный каталог
    assert calls.count(("case", bench.REPO)) == 2


def test_main_writes_report_with_finished_cases_when_matrix_fails(monkeypatch, tmp_path):
    def broken_matrix(profile, baseline, port, cases_out):
        cases_out.append({"height": 480, "fps": 25, "secs": 30, "sha": "x", "tree": "candidate"})
        raise RuntimeError("второй кейс упал")

    monkeypatch.setattr(bench, "run_matrix", broken_matrix)
    monkeypatch.setattr(bench, "clock_selfcheck", lambda: {"measured": 1.0, "ok": True, "method": "psutil"})
    monkeypatch.setattr(bench, "collect_passport", lambda repo: {"host": "H", "commit": "c"})
    assert bench.main(["--out", str(tmp_path)]) == 1
    (js,) = tmp_path.glob("*.json")
    assert len(json.loads(js.read_text(encoding="utf-8"))["cases"]) == 1


@pytest.mark.parametrize(
    "text, expected",
    [
        ("....\n57 passed in 23.48s\n", (57, 0)),
        ("F.\n1 failed, 54 passed in 1.20s (0:00:01)\n", (54, 1)),
        ("no tests ran in 0.01s\n", (0, 0)),
        ("", (0, 0)),
    ],
)
def test_parse_pytest_summary(text, expected):
    assert bench._parse_pytest_summary(text) == expected


class _RaisingProbe:
    def __init__(self, pid):
        raise RuntimeError("прибор не открылся")


def test_selfcheck_child_killed_when_probe_raises():
    def live() -> set[int]:
        out = set()
        for p in psutil.Process().children(recursive=True):
            with contextlib.suppress(psutil.Error):
                if p.status() != psutil.STATUS_ZOMBIE:
                    out.add(p.pid)
        return out

    before = live()
    t0 = time.monotonic()
    with pytest.raises(RuntimeError, match="прибор"):
        clock_selfcheck(seconds=1.0, probe=_RaisingProbe)
    # Без kill() wait() тихо дождался бы естественного конца busy-цикла (seconds + 5 с):
    # список живых потомков пуст и так, поэтому проверяем ещё и время.
    assert time.monotonic() - t0 < 3.0
    assert live() - before == set()
