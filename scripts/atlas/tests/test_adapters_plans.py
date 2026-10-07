"""Приёмочные тесты адаптера `plans` (Task 1.3a, RED до кода).

Purpose: узлы plan/task и рёбра in_plan из дерева сборки, значение `plans` в `--json`,
    ошибки plans_progress (exit 2 с точным текстом stderr).
Public API: тесты test_*; публичных имён нет.
Stability: lite

Ожидаемые значения — литералы; единственный оракул — независимый вызов plans_progress (RED 3).
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from scripts.atlas.tests.conftest import GitRepo, run_with_deadline

__all__: list[str] = []

_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _ROOT / "scripts" / "plans_progress" / "plans_progress.py"

_ALPHA = (
    "# Alpha\n\n**Статус:** IN PROGRESS\n\n## Порядок выполнения\n\n"
    "- Task 1.1: первая задача [DONE 2026-10-02 — `abc1234`; ok]\n"
    "- Task 1.2: second [PENDING] (после 1.1)\n"
)
_BETA = "# Beta\n\n## Порядок выполнения\n\n- Task 1.1: only [PENDING]\n"


def _seed(repo: GitRepo) -> None:
    repo.write("plans/2026-10-01_alpha/plan.md", _ALPHA)
    repo.write("plans/beta.md", _BETA)
    repo.commit("seed plans")


def _json(repo: GitRepo, atlas: Any, *argv: str) -> dict[str, Any]:
    res = atlas(repo, "--json", *argv)
    assert res.code == 0, res.err
    return json.loads(res.out)


def _by_key(doc: dict[str, Any], kind: str) -> dict[str, dict[str, Any]]:
    return {n["id"]: n for n in doc["nodes"] if n["kind"] == kind}


def _live(root: Path) -> subprocess.CompletedProcess[bytes]:
    def call() -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            [sys.executable, str(_SCRIPT), "--json", "--root", str(root)],
            capture_output=True,
            check=False,
        )

    return run_with_deadline(call, 120)


def test_plan_and_task_nodes_and_in_plan_edges(repo: GitRepo, atlas: Any) -> None:
    _seed(repo)
    doc = _json(repo, atlas, "--ref", repo.head, "--main-ref", "main")
    plans = _by_key(doc, "plan")
    tasks = _by_key(doc, "task")
    assert sorted(plans) == ["alpha", "beta"]
    assert plans["alpha"]["path"] == "plans/2026-10-01_alpha/plan.md"
    assert plans["beta"]["path"] == "plans/beta.md"
    assert sorted(tasks) == ["alpha#1.1", "alpha#1.2", "beta#1.1"]
    assert plans["alpha"]["status"] == "in_progress"
    assert tasks["alpha#1.1"]["status"] == "done"
    assert tasks["alpha#1.2"]["status"] == "pending"
    assert tasks["beta#1.1"]["status"] == "pending"
    assert tasks["alpha#1.1"]["path"] == "plans/2026-10-01_alpha/plan.md"
    assert tasks["beta#1.1"]["path"] == "plans/beta.md"
    assert all(n["time"] is None for n in plans.values())
    assert all(n["time"] is None for n in tasks.values())
    in_plan = [(e["src"], e["dst"], e["via"]) for e in doc["edges"] if e["kind"] == "in_plan"]
    assert in_plan == [
        ("task:alpha#1.1", "plan:alpha", "plan-line"),
        ("task:alpha#1.2", "plan:alpha", "plan-line"),
        ("task:beta#1.1", "plan:beta", "plan-line"),
    ]
    # `abc1234` в строке DONE — несуществующий объект: единственная находка (1.3b, перенос из 1.3a)
    assert [(f["code"], f["severity"], f["node"], f["detail"], f["source"]) for f in doc["findings"]] == [
        ("DONE_HASH_NOT_IN_MAIN", "blocking", "task:alpha#1.1", "abc1234", "plans/2026-10-01_alpha/plan.md")
    ]


def test_nodes_follow_the_build_ref_not_the_working_tree(repo: GitRepo, atlas: Any) -> None:
    pending = "# Gamma\n\n## Порядок выполнения\n\n- Task 1.1: work [PENDING]\n"
    done = "# Gamma\n\n## Порядок выполнения\n\n- Task 1.1: work [DONE 2026-10-02 — `abc1234`; ok]\n"
    repo.write("plans/gamma.md", pending)
    commit_a = repo.commit("A: pending")
    repo.write("plans/gamma.md", done)
    repo.commit("B: done")
    repo.write("plans/gamma.md", done + "- Task 1.2: extra [DONE 2026-10-03 — `def5678`; ok]\n")  # не закоммичено

    head = _json(repo, atlas)
    tasks = _by_key(head, "task")
    assert sorted(tasks) == ["gamma#1.1"]
    assert tasks["gamma#1.1"]["status"] == "done"

    old = _json(repo, atlas, "--ref", commit_a)
    assert _by_key(old, "task")["gamma#1.1"]["status"] == "pending"
    assert sorted(_by_key(old, "task")) == ["gamma#1.1"]
    assert old["plans"] is None


def test_plans_value_equals_live_plans_progress(repo: GitRepo, repo_factory: Any, atlas: Any) -> None:
    _seed(repo)
    # не закоммичено: рабочее дерево отличается от HEAD
    repo.write("plans/beta.md", _BETA + "- Task 1.2: добавленная позже [PENDING]\n")
    res = atlas(repo, "--json")
    assert res.code == 0, res.err
    doc = json.loads(res.out)
    plans = doc["plans"]
    assert plans is not None
    beta = next(p for p in plans if p["plan"] == "beta")
    assert [t["id"] for t in beta["tasks"]] == ["1.1", "1.2"]
    assert "task:beta#1.2" not in {f"{n['kind']}:{n['id']}" for n in doc["nodes"]}
    live = _live(repo.path)
    assert live.returncode == 0, live.stderr
    assert json.loads(live.stdout.decode("utf-8")) == plans

    bare = repo_factory.create("bare")
    bare.write("README.md", "# no plans\n")
    bare.commit("readme only")
    res = atlas(bare, "--json")
    assert res.code == 0, res.err
    assert json.loads(res.out)["plans"] is None


def test_plans_progress_failure_exits_2_without_the_value(
    repo: GitRepo, atlas: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    repo.write("plans/beta.md", _BETA)
    repo.commit("beta")
    bad_exit = tmp_path / "fake_exit3.py"
    bad_exit.write_text("import sys\nprint('[]')\nsys.exit(3)\n", encoding="utf-8")
    bad_json = tmp_path / "fake_notjson.py"
    bad_json.write_text("print('not json')\n", encoding="utf-8")

    monkeypatch.setattr("scripts.atlas.adapters.plans.PLANS_PROGRESS", bad_exit)
    res = atlas(repo, "build")
    assert res.code == 2
    assert res.err == "atlas: plans_progress --json failed (exit 3)\n"

    monkeypatch.setattr("scripts.atlas.adapters.plans.PLANS_PROGRESS", bad_json)
    res = atlas(repo, "build")
    assert res.code == 2
    assert res.err == "atlas: plans_progress --json failed (exit 0)\n"


def _explicit(repo: GitRepo, atlas: Any) -> dict[str, Any]:
    return _json(repo, atlas, "--ref", repo.head, "--main-ref", "main")


def _plan_nodes(doc: dict[str, Any]) -> list[tuple[str, str, str | None]]:
    return [(n["kind"], n["id"], n["path"]) for n in doc["nodes"] if n["kind"] in ("plan", "task")]


def test_slug_collision_is_a_finding_and_duplicate_task_id_still_exits_2(
    repo: GitRepo, repo_factory: Any, atlas: Any
) -> None:
    # обе живые: остаётся план с меньшим путём ("plans/2-..." < "plans/x.md")
    repo.write("plans/2026-10-01_x/plan.md", _BETA)
    repo.write("plans/x.md", _BETA)
    repo.commit("two plans, one slug")
    doc = _explicit(repo, atlas)
    assert [(f["code"], f["severity"], f["node"], f["detail"], f["source"]) for f in doc["findings"]] == [
        ("PLAN_SLUG_COLLISION", "blocking", "plan:x", "plans/x.md", "plans/x.md")
    ]
    assert _plan_nodes(doc) == [
        ("plan", "x", "plans/2026-10-01_x/plan.md"),
        ("task", "x#1.1", "plans/2026-10-01_x/plan.md"),
    ]

    # живой раньше архивного, как бы ни сортировались пути
    live_first = repo_factory.create("live_first")
    live_first.write("plans/2026-10-01_y/plan.md", _BETA)
    live_first.write("plans/_archive/2026-05-01_y/plan.md", _BETA)
    live_first.commit("live and archived, one slug")
    doc = _explicit(live_first, atlas)
    assert [(f["code"], f["node"], f["detail"], f["source"]) for f in doc["findings"]] == [
        ("PLAN_SLUG_COLLISION", "plan:y", "plans/_archive/2026-05-01_y/plan.md", "plans/_archive/2026-05-01_y/plan.md")
    ]
    assert _plan_nodes(doc) == [
        ("plan", "y", "plans/2026-10-01_y/plan.md"),
        ("task", "y#1.1", "plans/2026-10-01_y/plan.md"),
    ]

    # здесь путь архивного ("plans/_archive/...") меньше пути живого ("plans/z.md"): живой всё равно остаётся
    archive_smaller = repo_factory.create("archive_smaller")
    archive_smaller.write("plans/z.md", _BETA)
    archive_smaller.write("plans/_archive/2026-05-01_z/plan.md", _BETA)
    archive_smaller.commit("live z sorts after archived z")
    doc = _explicit(archive_smaller, atlas)
    assert [(f["code"], f["node"], f["detail"], f["source"]) for f in doc["findings"]] == [
        ("PLAN_SLUG_COLLISION", "plan:z", "plans/_archive/2026-05-01_z/plan.md", "plans/_archive/2026-05-01_z/plan.md")
    ]
    assert _plan_nodes(doc) == [("plan", "z", "plans/z.md"), ("task", "z#1.1", "plans/z.md")]

    dup = repo_factory.create("dup")
    dup.write(
        "plans/dup.md",
        "# Dup\n\n## Порядок выполнения\n\n- Task 1.1: a [PENDING]\n- Task 1.1: b [PENDING]\n",
    )
    dup.commit("duplicate task id")
    assert _live(dup.path).returncode == 0  # сам plans_progress дубль принимает
    res = atlas(dup, "build", "--ref", dup.head, "--main-ref", "main")
    assert res.code == 2
    assert res.err == "atlas: duplicate task id in one plan\n"


def test_plans_progress_timeout_exits_2(repo: GitRepo, atlas: Any, tmp_path: Path, monkeypatch: Any) -> None:
    repo.write("plans/beta.md", _BETA)
    repo.commit("beta")
    slow = tmp_path / "fake_slow.py"
    slow.write_text("import time\ntime.sleep(30)\nprint('[]')\n", encoding="utf-8")
    monkeypatch.setattr("scripts.atlas.adapters.plans.PLANS_PROGRESS", slow)
    monkeypatch.setattr("scripts.atlas.adapters.plans.PLANS_TIMEOUT", 1)
    started = time.monotonic()
    res = atlas(repo, "build", "--ref", repo.head, "--main-ref", "main")
    elapsed = time.monotonic() - started
    assert res.code == 2
    assert res.err == "atlas: plans_progress --json timed out\n"
    assert elapsed < 20, f"вызов вернулся за {elapsed:.1f} с: таймаут не сработал"


def test_plans_progress_stderr_is_forwarded_on_failure(
    repo: GitRepo, atlas: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    repo.write("plans/beta.md", _BETA)
    repo.commit("beta")
    # байты через sys.stderr.buffer: текстовый режим дал бы CRLF на Windows
    failing = tmp_path / "fake_fail.py"
    failing.write_text(
        "import sys\nsys.stderr.buffer.write(b'boom\\n')\nsys.stderr.buffer.flush()\nprint('[]')\nsys.exit(3)\n",
        encoding="utf-8",
    )
    noisy = tmp_path / "fake_noisy.py"
    noisy.write_text(
        "import sys\nsys.stderr.buffer.write(b'noise\\n')\nsys.stderr.buffer.flush()\nprint('[]')\n",
        encoding="utf-8",
    )

    monkeypatch.setattr("scripts.atlas.adapters.plans.PLANS_PROGRESS", failing)
    res = atlas(repo, "build", "--ref", repo.head, "--main-ref", "main")
    assert res.code == 2
    assert res.err == "boom\natlas: plans_progress --json failed (exit 3)\n"

    monkeypatch.setattr("scripts.atlas.adapters.plans.PLANS_PROGRESS", noisy)
    res = atlas(repo, "build", "--ref", repo.head, "--main-ref", "main")
    assert res.code == 0, res.err
    assert res.err == ""


def test_plans_progress_runs_once_per_build(repo: GitRepo, atlas: Any, tmp_path: Path, monkeypatch: Any) -> None:
    from scripts.atlas.adapters.commits import CommitsAdapter
    from scripts.atlas.adapters.plans import PlansAdapter
    from scripts.atlas.build import ADAPTERS

    names = [type(a).__name__ for a in ADAPTERS]
    assert "CommitsAdapter" in names and "PlansAdapter" in names, names
    assert any(isinstance(a, CommitsAdapter) for a in ADAPTERS)
    assert any(isinstance(a, PlansAdapter) for a in ADAPTERS)

    counter = tmp_path / "calls.txt"
    payload = [
        {
            "plan": "2026-10-01_alpha",
            "path": "plans/2026-10-01_alpha/plan.md",
            "archived": False,
            "header_status": None,
            "tasks": [{"id": "1.1", "status": "pending", "ref": None}],
        }
    ]
    fake = tmp_path / "fake_counting.py"
    fake.write_text(
        "import json\n"
        f"with open({str(counter)!r}, 'a', encoding='utf-8') as fh:\n"
        "    fh.write('call\\n')\n"
        f"print(json.dumps({payload!r}))\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("scripts.atlas.adapters.plans.PLANS_PROGRESS", fake)
    repo.write("plans/beta.md", _BETA)
    first = repo.commit("beta")

    res = atlas(repo, "build", "--ref", first, "--main-ref", "main")
    assert res.code == 0, res.err
    assert len(counter.read_text(encoding="utf-8").splitlines()) == 1

    repo.write("README.md", "# second\n")
    second = repo.commit("second sha")
    res = atlas(repo, "build", "--ref", second, "--main-ref", "main")
    assert res.code == 0, res.err
    assert len(counter.read_text(encoding="utf-8").splitlines()) == 2


def test_adapter_versions_follow_plans_progress_content(tmp_path: Path, monkeypatch: Any) -> None:
    from scripts.atlas.adapters.commits import CommitsAdapter
    from scripts.atlas.adapters.modules import ModulesAdapter
    from scripts.atlas.adapters.plans import PlansAdapter
    from scripts.atlas.build import fingerprint

    def snapshot() -> tuple[Any, Any, Any]:
        return PlansAdapter().version, CommitsAdapter().version, fingerprint()

    script = tmp_path / "pp.py"
    script.write_text("# one", encoding="utf-8")
    monkeypatch.setattr("scripts.atlas.adapters.plans.PLANS_PROGRESS", script)
    before = snapshot()
    assert isinstance(before[0], int) and isinstance(before[1], int)
    assert snapshot() == before

    script.write_text("# two", encoding="utf-8")
    after = snapshot()
    assert after[0] != before[0]
    assert after[1] != before[1]
    assert after[2] != before[2]

    monkeypatch.setattr("scripts.atlas.adapters.plans.PLANS_PROGRESS", tmp_path / "missing.py")
    gone = snapshot()  # нет файла -> без исключения
    assert isinstance(gone[0], int) and isinstance(gone[1], int) and isinstance(gone[2], str)
    assert ModulesAdapter().version == 1
