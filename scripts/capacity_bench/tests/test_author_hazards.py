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
import textwrap
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import psutil
import pytest
import yaml

from scripts.capacity_bench import __main__ as bench
from scripts.capacity_bench.cpu_probe import clock_selfcheck
from scripts.capacity_bench.passport import collect_passport
from scripts.capacity_bench.recipe import render_recipe
from scripts.capacity_bench.report import write_report


def _fake_run_factory(calls: list):
    """Подмена `subprocess.run` для git; кейс идёт через `_run_tree` (см. `_fake_run_tree_factory`)."""
    real_run = subprocess.run

    def fake_run(cmd, *args, **kwargs):
        if cmd[0] == "git" and "worktree" in cmd:
            calls.append(("worktree", cmd[cmd.index("worktree") + 1]))
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if cmd[0] == "git" and "rev-parse" in cmd:
            return SimpleNamespace(returncode=0, stdout="f" * 40 + "\n", stderr="")
        return real_run(cmd, *args, **kwargs)

    return fake_run


def _fake_run_tree_factory(calls: list, fail_case: bool):
    def fake_run_tree(cmd, *, cwd, env, timeout):
        calls.append(("case", cwd))
        if fail_case:
            return 3, "", "boom"
        out = cmd[cmd.index("--out") + 1]
        with open(out, "w", encoding="utf-8") as f:
            json.dump({"processes": {}, "total_ext_cores": 0.0}, f)
        return 0, "", ""

    return fake_run_tree


def _patch_matrix_io(monkeypatch, calls: list, fail_case: bool):
    monkeypatch.setattr(bench.subprocess, "run", _fake_run_factory(calls))
    monkeypatch.setattr(bench, "_run_tree", _fake_run_tree_factory(calls, fail_case))


def test_baseline_worktree_removed_when_case_raises(monkeypatch):
    calls: list = []
    _patch_matrix_io(monkeypatch, calls, fail_case=True)
    with pytest.raises(RuntimeError, match="rc=3"):
        bench.run_matrix("quick", "a" * 40, 8775, [])
    assert [c for c in calls if c[0] == "worktree"] == [("worktree", "add"), ("worktree", "remove")]


def test_baseline_runs_before_candidate_per_case(monkeypatch):
    calls: list = []
    cases: list = []
    _patch_matrix_io(monkeypatch, calls, fail_case=False)
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


# --- ревью 4.8a, итерация 1 -------------------------------------------------------------------


def _in_daemon_thread(fn, deadline_s: float):
    """(finished, result, exc): зависший вызов не вешает набор — join с дедлайном."""
    box: dict = {}

    def target():
        try:
            box["result"] = fn()
        except BaseException as exc:  # noqa: BLE001 — тест разбирает любое исключение вызова
            box["exc"] = exc

    th = threading.Thread(target=target, daemon=True)
    th.start()
    th.join(deadline_s)
    return (not th.is_alive()), box.get("result"), box.get("exc")


_HUNG_CASE = textwrap.dedent(
    """
    import os, subprocess, sys, time
    pid_file = os.environ["BENCH_TEST_GC_PID"]
    # Внук держит унаследованный stdout-pipe (как PM стенда) и живёт дольше таймаута.
    gc = "import os, sys, time; open(sys.argv[1], 'w').write(str(os.getpid())); time.sleep(60)"
    subprocess.Popen([sys.executable, "-c", gc, pid_file])
    while not os.path.exists(pid_file):
        time.sleep(0.05)
    time.sleep(600)  # «зависший стенд»
    """
)


def test_run_one_timeout_kills_grandchild_tree(monkeypatch, tmp_path):
    fake_dir = tmp_path / "pkg"
    fake_dir.mkdir()
    (fake_dir / "run_case.py").write_text(_HUNG_CASE, encoding="utf-8")
    pid_file = tmp_path / "gc.pid"
    monkeypatch.setenv("BENCH_TEST_GC_PID", str(pid_file))
    monkeypatch.setattr(bench, "PKG_DIR", fake_dir)
    monkeypatch.setattr(bench, "CASE_TIMEOUT_MARGIN_S", 0)
    monkeypatch.setattr(bench, "_git_head", lambda tree: "f" * 40)
    try:
        t0 = time.monotonic()
        # secs=6: на медленном старте внук успевает записать pid до таймаута
        finished, _, exc = _in_daemon_thread(lambda: bench.run_one(Path.cwd(), "candidate", 480, 25, 6, 8775), 40)
        elapsed = time.monotonic() - t0
        gc_pid = int(pid_file.read_text()) if pid_file.exists() else None
        assert finished, "run_one завис: сирота держит pipe, communicate() ждёт её выхода"
        assert isinstance(exc, subprocess.TimeoutExpired), repr(exc)
        assert elapsed < 30, elapsed
        assert gc_pid is not None, "внук не успел стартовать до таймаута — тест не проверил дерево"
        deadline = time.monotonic() + 5
        while psutil.pid_exists(gc_pid) and time.monotonic() < deadline:
            time.sleep(0.1)
        assert not psutil.pid_exists(gc_pid), f"внук {gc_pid} пережил таймаут кейса"
    finally:
        # красный прогон оставил бы сироту на 60 с: убрать в любом случае
        if pid_file.exists():
            with contextlib.suppress(psutil.Error, ValueError):
                psutil.Process(int(pid_file.read_text())).kill()


def test_run_tests_timeout_still_returns_result(monkeypatch, tmp_path):
    hang = tmp_path / "test_hang.py"
    hang.write_text("import time\n\n\ndef test_hang():\n    time.sleep(120)\n", encoding="utf-8")
    monkeypatch.setattr(bench, "TEST_DIRS", (str(hang),))
    monkeypatch.setattr(bench, "TESTS_TIMEOUT_S", 2)
    finished, result, exc = _in_daemon_thread(lambda: bench.run_tests(bench.REPO), 60)
    assert finished, "run_tests завис"
    assert exc is None, f"run_tests бросил {exc!r}: замер не должен отменяться падением тестов"
    assert result["rc"] is None and result["passed"] is None and result["failed"] is None
    assert result["error"].startswith("TimeoutExpired"), result
    assert isinstance(result["duration_s"], float)


def _find_keys(node, key):
    found = []
    if isinstance(node, dict):
        for k, v in node.items():
            if k == key:
                found.append(v)
            found += _find_keys(v, key)
    elif isinstance(node, list):
        for v in node:
            found += _find_keys(v, key)
    return found


def test_render_recipe_db_path_in_out_dir(tmp_path):
    out = render_recipe(480, 25, tmp_path)
    paths = _find_keys(yaml.safe_load(out.read_text(encoding="utf-8")), "db_path")
    assert paths, "в рецепте нет db_path: тест проверял бы пустоту"
    for value in paths:
        assert Path(value).parent == tmp_path, f"db_path {value!r} вне каталога кейса {tmp_path}"
        assert Path(value).name == "inspection_results.db"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, timeout=60)


def test_commit_dirty_truth_on_temp_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    tracked = repo / "a.txt"
    tracked.write_text("one\n", encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "add", "a.txt")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", "commit", "-q", "-m", "x")
    clean = collect_passport(repo)
    assert clean["commit"] and clean["commit_dirty"] is False
    tracked.write_text("two\n", encoding="utf-8")
    assert collect_passport(repo)["commit_dirty"] is True


def test_report_lists_missing_processes(tmp_path):
    def text(missing, sub):
        case = {
            "height": 480,
            "fps": 25,
            "secs": 30,
            "sha": "f" * 40,
            "tree": "candidate",
            "total_ext_cores": 1.5,
            "missing": missing,
            "processes": {"camera_0": {"ext_cores": 1.5}},
        }
        md, _ = write_report({"passport": {"host": "H"}, "selfcheck": {}, "cases": [case]}, tmp_path / sub)
        return md.read_text(encoding="utf-8")

    with_missing = text(["storage", "gui"], "a")
    assert "не измерены: storage, gui" in with_missing
    assert "сумма ядер снаружи по измеренным процессам рецепта" in with_missing
    assert "не измерены" not in text([], "b")


def test_worktree_remove_failure_warns_and_prunes(monkeypatch, capsys):
    calls: list = []

    def fake_run(cmd, *args, **kwargs):
        verb = cmd[cmd.index("worktree") + 1]
        calls.append(verb)
        return SimpleNamespace(returncode=1 if verb == "remove" else 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(bench.subprocess, "run", fake_run)
    with bench._baseline_worktree("a" * 40) as tree:
        assert tree is not None
    assert calls == ["add", "remove", "prune"]
    assert str(tree) in capsys.readouterr().err
