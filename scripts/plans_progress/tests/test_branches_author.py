# ruff: noqa: E501  -- литералы-фикстуры и ожидания в одну строку
"""Тесты автора на внутренние опасности чисел веток (Task 5.5, `collect_branches` и её части).

Приёмку по критериям пишет независимый тестер (test_acceptance_branches.py, только CLI). Здесь — места, видимые
по устройству механизма: временный каталог выгрузки при любом исходе git (сбой, таймаут, битый и враждебный tar);
имена веток со слэшем и кириллицей в аргументах git; план-каталог без `plan.md`; merge-коммит с двумя родителями;
повтор id задачи (первая запись); стоимость — число вызовов git на границе ОС (`subprocess.run`), а не имя функции:
устаревшие и вошедшие в `main` ветки не стоят ни одного вызова сверх общих.

Модуль импортируется напрямую; git настоящий (фикстура — `git init` в tmp_path), подменяется только
`subprocess.run` вокруг самого вызова `collect_branches`, и только как шпион/сбойник.
"""

from __future__ import annotations

import importlib.util
import io
import os
import re
import subprocess
import sys
import tarfile
import tempfile
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

import pytest

_MOD_PATH = Path(__file__).resolve().parents[1] / "plans_progress.py"
_spec = importlib.util.spec_from_file_location("plans_progress_branches_under_test", _MOD_PATH)
pp = importlib.util.module_from_spec(_spec)
sys.modules["plans_progress_branches_under_test"] = pp
_spec.loader.exec_module(pp)

NOW = datetime(2026, 10, 3, 12, 0, 0)
WINDOW = timedelta(days=3)
D1 = timedelta(days=1)
D10 = timedelta(days=10)
D20 = timedelta(days=20)
SHA40 = re.compile(r"[0-9a-f]{40}")


# =========================================================================== хелперы


def _env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_") or k == "GIT_CEILING_DIRECTORIES"}
    env["PYTHONUTF8"] = "1"
    env.update(extra or {})
    return env


def items(*statuses: str) -> str:
    lines = ["# План", "", "## Порядок выполнения", ""]
    lines += [f"- Task 1.{i}: задача {i} [{st}]" for i, st in enumerate(statuses, 1)]
    return "\n".join(lines) + "\n"


def stamp(ago: timedelta) -> str:
    return f"{int((NOW - ago).timestamp())} +0000"


class Repo:
    def __init__(self, tmp_path: Path, files: dict[str, str]) -> None:
        self.root = tmp_path / "repo"
        self.root.mkdir()
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "t")
        self.git("config", "user.email", "t@example.invalid")
        self.git("config", "core.autocrlf", "false")
        self.git("config", "commit.gpgsign", "false")
        self.write("NOTES.txt", "x")
        for rel, text in files.items():
            self.write(rel, text)
        self.commit("init", D20)

    def git(self, *args: str, env: dict[str, str] | None = None) -> str:
        cp = subprocess.run(
            ["git", *args], cwd=str(self.root), capture_output=True, encoding="utf-8", errors="replace",
            timeout=60, env=_env(env),
        )  # fmt: skip
        assert cp.returncode == 0, f"git {' '.join(args)}: {cp.stderr[:300]}"
        return cp.stdout

    def write(self, rel: str, text: str) -> None:
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(text.encode("utf-8"))

    def commit(self, msg: str, ago: timedelta = D1) -> None:
        self.git("add", "-A")
        date = stamp(ago)
        self.git("commit", "-q", "--allow-empty", "-m", msg, env={"GIT_COMMITTER_DATE": date, "GIT_AUTHOR_DATE": date})

    def edit_on(self, branch: str, files: dict[str, str], frm: str = "main", ago: timedelta = D1) -> None:
        self.git("checkout", "-q", "-b", branch, f"refs/heads/{frm}")
        for rel, text in files.items():
            self.write(rel, text)
        self.commit(f"edit {branch}", ago)
        self.git("checkout", "-q", "main")

    def collect(self, window: timedelta = WINDOW) -> dict[str, list[dict]]:
        """{имя плана: branches} после `collect_branches` на настоящем git."""
        plans = pp.discover(self.root)
        pp.collect_branches(self.root, plans, NOW, window)
        return {p.name: p.branches for p in plans}


def spy_run(monkeypatch, fail: dict[str, str] | None = None) -> list[list[str]]:
    """Шпион на границе ОС: журнал команд git; `fail[<глагол>]` — 'timeout' | 'nonzero' для этого глагола."""
    calls: list[list[str]] = []
    real = subprocess.run

    def run(cmd, *a, **kw):
        calls.append(list(cmd))
        mode = (fail or {}).get(cmd[1])
        if mode == "timeout":
            raise subprocess.TimeoutExpired(cmd, 10)
        if mode == "nonzero":
            return subprocess.CompletedProcess(cmd, 128, "", "fatal: simulated")
        return real(cmd, *a, **kw)

    monkeypatch.setattr(pp.subprocess, "run", run)
    return calls


def verbs(calls: list[list[str]]) -> Counter:
    return Counter(c[1] for c in calls)


@pytest.fixture
def tmp_area(tmp_path, monkeypatch) -> Path:
    """Каталог, который `tempfile` использует вместо системного: любой остаток видно."""
    area = tmp_path / "tmp-area"
    area.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(area))
    return area


def base_repo(tmp_path: Path) -> Repo:
    return Repo(tmp_path, {"plans/P/plan.md": items("DONE", "PENDING", "PENDING")})


# =========================================================================== временный каталог выгрузки


def test_tempdir_is_removed_after_a_successful_export(tmp_path, tmp_area):
    repo = base_repo(tmp_path)
    repo.edit_on("feat/x", {"plans/P/plan.md": items("DONE", "DONE", "PENDING")})
    assert repo.collect()["P"] == [{"branch": "feat/x", "done": 2, "total": 3}], "контроль: выгрузка прошла"
    assert list(tmp_area.iterdir()) == []


@pytest.mark.parametrize("mode", ["timeout", "nonzero"])
def test_archive_failure_gives_no_entry_no_exception_and_no_tempdir_left(tmp_path, tmp_area, monkeypatch, mode):
    repo = base_repo(tmp_path)
    repo.edit_on("feat/x", {"plans/P/plan.md": items("DONE", "DONE", "PENDING")})
    calls = spy_run(monkeypatch, fail={"archive": mode})
    result = repo.collect()
    assert verbs(calls)["archive"] >= 1, "предусловие: archive действительно вызывался и упал"
    assert result["P"] == []
    assert list(tmp_area.iterdir()) == []


def _fake_git_writing_tar(payload: bytes):
    """Подмена `pp._git`: на `archive -o <файл>` кладёт в файл готовые байты и отвечает успехом."""

    def fake(args, cwd):
        assert args[0] == "archive"
        Path(args[args.index("-o") + 1]).write_bytes(payload)
        return ""

    return fake


def test_corrupt_tar_gives_none_and_leaves_no_tempdir(tmp_area, monkeypatch):
    monkeypatch.setattr(pp, "_git", _fake_git_writing_tar(b"not a tar at all" * 100))
    assert pp.analyze_plan_at(Path("."), "abc", "plans/P", "P", False) is None
    assert list(tmp_area.iterdir()) == []


def test_hostile_tar_member_outside_the_target_is_refused_and_nothing_is_written(tmp_path, tmp_area, monkeypatch):
    """Путь `../evil.txt` в архиве: `filter="data"` обязан отказать, файл за пределами каталога не появляется."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        data = b"pwned"
        info = tarfile.TarInfo("../../evil.txt")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    monkeypatch.setattr(pp, "_git", _fake_git_writing_tar(buf.getvalue()))
    assert pp.analyze_plan_at(Path("."), "abc", "plans/P", "P", False) is None
    assert not (tmp_area / "evil.txt").exists() and not (tmp_area.parent / "evil.txt").exists()
    assert list(tmp_area.iterdir()) == []


def test_tar_without_the_plan_path_gives_none(tmp_path, tmp_area, monkeypatch):
    """git ответил успехом, но в архиве другого пути нет — не исключение и не пустой план."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        info = tarfile.TarInfo("plans/OTHER/plan.md")
        info.size = 1
        tar.addfile(info, io.BytesIO(b"x"))
    monkeypatch.setattr(pp, "_git", _fake_git_writing_tar(buf.getvalue()))
    assert pp.analyze_plan_at(Path("."), "abc", "plans/P", "P", False) is None


# =========================================================================== имена веток и пути


def test_branch_name_with_slashes_goes_through_full_refs_and_commits_get_hashes(tmp_path, monkeypatch):
    repo = base_repo(tmp_path)
    repo.edit_on("feat/deep/name", {"plans/P/plan.md": items("DONE", "DONE", "DONE")})
    calls = spy_run(monkeypatch)
    result = repo.collect()
    assert result["P"] == [{"branch": "feat/deep/name", "done": 3, "total": 3}]
    diffs = [c for c in calls if c[1] == "diff"]
    assert diffs and all("refs/heads/feat/deep/name" in c for c in diffs), diffs
    archives = [c for c in calls if c[1] == "archive"]
    assert archives
    for c in archives:
        assert SHA40.fullmatch(c[c.index("--") - 1]), f"коммит в archive не sha: {c}"
        assert c[c.index("--") + 1] == "plans/P"
    assert all("feat/deep/name" not in a or a.endswith("refs/heads/feat/deep/name") for c in calls for a in c)


def test_cyrillic_branch_name_survives_the_for_each_ref_roundtrip(tmp_path):
    repo = base_repo(tmp_path)
    repo.edit_on("feat/фича", {"plans/P/plan.md": items("DONE", "DONE", "PENDING")})
    assert repo.collect()["P"] == [{"branch": "feat/фича", "done": 2, "total": 3}]


def test_plan_directory_without_plan_md_counts_its_task_files(tmp_path, tmp_area):
    def tf(tid: str, st: str) -> str:
        return f"# Task {tid}: задача {tid}\n\n**Статус:** {st}\n"

    repo = Repo(tmp_path, {"plans/N/tasks/1.1.md": tf("1.1", "PENDING"), "plans/N/tasks/1.2.md": tf("1.2", "PENDING")})
    assert not (repo.root / "plans" / "N" / "plan.md").exists()
    repo.edit_on("feat/n", {"plans/N/tasks/1.1.md": tf("1.1", "DONE")})
    assert repo.collect()["N"] == [{"branch": "feat/n", "done": 1, "total": 2}]
    assert list(tmp_area.iterdir()) == []


# =========================================================================== история: merge-коммит, чужие корни


def test_branch_that_merged_another_branch_is_a_child_and_numbers_include_the_second_parent(tmp_path):
    """merge-коммит с двумя родителями: вершина `feat/a` входит в `main..feat/m`, поэтому `feat/m` — её потомок,
    diff идёт от вершины `feat/a`, а числа `feat/m` (три разбора от merge-base с main) включают правки обоих."""
    repo = base_repo(tmp_path)
    repo.edit_on("feat/a", {"plans/P/plan.md": items("DONE", "DONE", "PENDING")})
    repo.git("checkout", "-q", "-b", "feat/m", "refs/heads/main")
    repo.write("NOTES.txt", "own work of m")
    repo.commit("m own")
    repo.git("merge", "-q", "--no-ff", "-m", "merge a", "feat/a")
    repo.write("plans/P/plan.md", items("DONE", "DONE", "DONE"))
    repo.commit("m closes 1.3")
    repo.git("checkout", "-q", "main")
    assert repo.git("rev-list", "--parents", "-n", "1", "feat/m~1").count(" ") == 2, "предусловие: merge-коммит"
    assert repo.collect()["P"] == [
        {"branch": "feat/a", "done": 2, "total": 3},
        {"branch": "feat/m", "done": 3, "total": 3},
    ]


def test_branch_that_merged_main_back_uses_the_new_merge_base(tmp_path):
    """Ветка влила `main` (два родителя): merge-base с main — вершина main, база = main, числа — правки ветки."""
    repo = Repo(tmp_path, {"plans/P/plan.md": items("PENDING", "PENDING", "PENDING", "PENDING", "PENDING")})
    repo.git("checkout", "-q", "-b", "feat/m", "refs/heads/main")
    repo.write("plans/P/plan.md", items("PENDING", "PENDING", "PENDING", "PENDING", "DONE"))
    repo.commit("m closes 1.5")
    repo.git("checkout", "-q", "main")
    repo.write("plans/P/plan.md", items("DONE", "PENDING", "PENDING", "PENDING", "PENDING"))
    repo.commit("main closes 1.1")
    repo.git("checkout", "-q", "feat/m")
    repo.git("merge", "-q", "--no-edit", "main")
    repo.git("checkout", "-q", "main")
    assert repo.collect()["P"] == [{"branch": "feat/m", "done": 2, "total": 5}]


def test_unrelated_history_has_no_merge_base_and_gives_no_entry_without_exception(tmp_path):
    repo = base_repo(tmp_path)
    repo.edit_on("feat/ok", {"plans/P/plan.md": items("DONE", "DONE", "PENDING")})
    repo.git("checkout", "-q", "--orphan", "feat/orphan")
    repo.git("rm", "-rq", "--cached", ".")
    repo.write("plans/P/plan.md", items("DONE", "DONE", "DONE"))
    repo.commit("orphan root")
    repo.git("checkout", "-q", "main")
    assert repo.collect()["P"] == [{"branch": "feat/ok", "done": 2, "total": 3}]


def test_stale_root_branch_is_still_a_parent_candidate_for_its_fresh_child(tmp_path):
    """Корень взят на устаревшей ветке: она не выводится, но потомок без своих правок плана тоже не выводится."""
    repo = base_repo(tmp_path)
    repo.edit_on("feat/old", {"plans/P/plan.md": items("DONE", "DONE", "PENDING")}, ago=D10)
    repo.edit_on("feat/new", {"NOTES.txt": "child"}, frm="feat/old")
    repo.git("checkout", "-q", "feat/old")
    result = repo.collect()
    assert result["P"] == []
    repo.git("checkout", "-q", "main")
    assert repo.collect()["P"] == [{"branch": "feat/new", "done": 2, "total": 3}], "контроль: без корня на old — запись"


def test_detached_head_at_root_hides_nothing(tmp_path):
    repo = base_repo(tmp_path)
    repo.edit_on("feat/x", {"plans/P/plan.md": items("DONE", "DONE", "PENDING")})
    repo.git("checkout", "-q", "--detach", "main")
    assert pp._checked_out_branch(repo.root) == ""
    assert repo.collect()["P"] == [{"branch": "feat/x", "done": 2, "total": 3}]


# =========================================================================== слияние: повтор id и разбор даты


def mem_plan(*pairs: tuple[str, str]) -> pp.Plan:
    return pp.Plan(name="P", rel="plans/P/plan.md", archived=False, tasks=[pp.Task(i, "", s) for i, s in pairs])


def test_duplicate_task_id_first_record_wins_on_every_side_and_counts_once():
    base = mem_plan(("1.1", "pending"))
    tip = mem_plan(("1.1", "pending"), ("1.1", "done"))  # первая — pending, вторая (должна игнорироваться) — done
    disk = mem_plan(("1.1", "pending"), ("1.1", "pending"))
    assert pp.merge_branch_numbers(base, tip, disk) == (0, 1)


def test_task_removed_by_the_branch_and_rewritten_by_main_takes_the_disk_status():
    """Обе стороны изменили задачу (ветка убрала, main закрыл): done на диске побеждает отсутствие на вершине."""
    base = mem_plan(("1.1", "pending"), ("1.2", "pending"))
    tip = mem_plan(("1.2", "pending"))
    disk = mem_plan(("1.1", "done"), ("1.2", "pending"))
    assert pp.merge_branch_numbers(base, tip, disk) == (1, 2)


def test_plan_absent_on_base_means_empty_base():
    tip = mem_plan(("1.1", "done"), ("1.2", "pending"))
    disk = mem_plan(("1.1", "pending"), ("1.2", "pending"))
    assert pp.merge_branch_numbers(None, tip, disk) == (1, 2)


@pytest.mark.parametrize(
    ("unix_time", "fresh"),
    [
        (str(int(NOW.timestamp())), True),
        (str(int((NOW - WINDOW).timestamp())), True),
        (str(int((NOW - WINDOW).timestamp()) - 1), False),
        (str(int((NOW + D10).timestamp())), True),
        ("", False),
        ("abc", False),
        ("9" * 30, False),
        ("-99999999999999999", False),
    ],
)
def test_freshness_boundary_future_and_garbage(unix_time, fresh):
    assert pp._is_fresh(unix_time, NOW, WINDOW) is fresh


# =========================================================================== стоимость: вызовы git на границе ОС


def test_stale_and_merged_branches_cost_no_extra_git_calls(tmp_path, monkeypatch):
    repo = base_repo(tmp_path)
    repo.edit_on("feat/a", {"plans/P/plan.md": items("DONE", "DONE", "PENDING")})
    repo.edit_on("feat/b", {"plans/P/plan.md": items("DONE", "DONE", "DONE")})
    calls0 = spy_run(monkeypatch)
    repo.collect()
    monkeypatch.undo()  # шпион снят до построения шумовых веток

    for i in range(10):
        repo.edit_on(f"stale/{i:02d}", {"plans/P/plan.md": items("DONE", "DONE", "PENDING")}, ago=D10)
    for i in range(5):
        repo.git("branch", f"merged/{i}", "main")
    calls1 = spy_run(monkeypatch)
    result = repo.collect()
    assert [e["branch"] for e in result["P"]] == ["feat/a", "feat/b"], "контроль: шумовые ветки не попали"
    assert verbs(calls1) == verbs(calls0), (verbs(calls0), verbs(calls1))
    noise = [a for c in calls1 for a in c if a.startswith(("stale/", "merged/")) or "/stale/" in a or "/merged/" in a]
    assert noise == [], f"git спрашивали про шумовые ветки: {noise}"


def test_git_calls_are_bounded_by_the_number_of_actual_branches(tmp_path, monkeypatch):
    repo = base_repo(tmp_path)
    for name in ("feat/a", "feat/b", "feat/c"):
        repo.edit_on(name, {"plans/P/plan.md": items("DONE", "DONE", "PENDING")})
    calls = spy_run(monkeypatch)
    repo.collect()
    c, fresh = verbs(calls), 3
    assert c["for-each-ref"] == 1 and c["symbolic-ref"] == 1
    assert c["rev-list"] == fresh and c["merge-base"] == fresh and c["diff"] == fresh
    assert c["archive"] <= 2 * fresh, "вершина + база на (ветка, план); база общая — кэш не даёт больше"
    assert sum(c.values()) <= 3 + 3 * fresh + 2 * fresh


def test_branches_off_the_same_base_export_the_base_once(tmp_path, monkeypatch):
    repo = base_repo(tmp_path)
    for name in ("feat/a", "feat/b", "feat/c"):
        repo.edit_on(name, {"plans/P/plan.md": items("DONE", "DONE", "PENDING")})
    calls = spy_run(monkeypatch)
    repo.collect()
    base_sha = repo.git("rev-parse", "main").strip()
    base_exports = [c for c in calls if c[1] == "archive" and c[c.index("--") - 1] == base_sha]
    assert len(base_exports) == 1, base_exports


def test_no_git_and_no_main_stop_after_the_first_probes(tmp_path, monkeypatch):
    plain = tmp_path / "plain"
    (plain / "plans" / "P").mkdir(parents=True)
    (plain / "plans" / "P" / "plan.md").write_bytes(items("DONE").encode("utf-8"))
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    calls = spy_run(monkeypatch)
    plans = pp.discover(plain)
    pp.collect_branches(plain, plans, NOW, WINDOW)
    assert [c[1] for c in calls] == ["rev-parse"] and plans[0].branches == []


def test_repository_without_main_costs_two_calls(tmp_path, monkeypatch):
    repo = base_repo(tmp_path)
    repo.edit_on("feat/x", {"plans/P/plan.md": items("DONE", "DONE", "PENDING")})
    repo.git("branch", "-m", "main", "trunk")
    calls = spy_run(monkeypatch)
    assert repo.collect()["P"] == []
    assert [c[1] for c in calls] == ["rev-parse", "for-each-ref"], [c[:3] for c in calls]
