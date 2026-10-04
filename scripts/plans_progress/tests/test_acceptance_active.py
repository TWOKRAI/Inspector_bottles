# ruff: noqa: E501  -- литералы-фикстуры и ожидания в одну строку, форматтер их не переносит
"""Приёмка Task 5.2 — слепые тесты поля `active`, резолвера «worktree -> план» и `--who`.

Источник: plans/2026-10-02_plans-progress-dashboard/tasks/5.2.md (DESIGN, ACCEPTANCE A1-A7).
Реализацию тестер не видел; читал только набор флагов CLI и форму `--json` до задачи.

Только CLI в subprocess (timeout на каждый вызов): `plans_progress.py --root R (--json | --who)
[--now ISO] [--active-window 6h]`. Фикстура — настоящий `git init -b main` в tmp_path,
`extensions.worktreeConfig true`, `git worktree add`; журналы `<worktree>/data/agent-journal.jsonl`
пишет тест. Ожидания — литералы, не вычисленные из вывода.

Договорённости чтения (в тексте задачи неоднозначно; выбрано строгое чтение):
- ЛОВУШКА tmp_path: tmp_path лежит внутри чужого git-репозитория. Тесты A5 именно про это:
  `rev-parse --show-toplevel` другой каталог, чем `--root` -> корней нет. `GIT_CEILING_DIRECTORIES`
  выставлен ТОЛЬКО в одном тесте A5, где нужен каталог вне любого git (сказано в его docstring).
- `worktree` сравнивается как `Path(значение) == путь` (porcelain на Windows даёт `C:/...`).
- Имя плана в `--who` — литерал `X`, а не путь (DESIGN: «первый сегмент после plans/, без .md»).
- Порядок ключей записи `active` в `--json` — как в DESIGN (`branch, worktree, via, sessions,
  agents, last_signal`); в `--who` порядок ключей не фиксируется, только набор (позицию `plan`
  DESIGN не задаёт).
- Каждый негативный тест (план не активен / корня нет в выдаче) несёт контроль: рядом есть
  worktree, который ОБЯЗАН попасть в `active`; без него заглушка «всегда []» была бы зелёной.
- Граница окна: `now - ts <= окно` — ровно на краю свежая, на секунду дальше — нет.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
PROGRESS = REPO_ROOT / "scripts" / "plans_progress" / "plans_progress.py"
CALL_TIMEOUT = 60

NOW = "2026-10-03T12:00:00"
_NOW_DT = datetime.fromisoformat(NOW)

# ключи записи плана в --json ДО задачи 5.2 (снято с прежнего CLI): `active` обязан встать после них
OLD_PLAN_KEYS = [
    "plan", "path", "archived", "lane", "tier", "done", "total", "dropped", "unknown", "unmarked",
    "header_status", "tasks", "after", "after_reason", "waiting_on", "ready", "dep_unknown", "dep_cycle",
]  # fmt: skip
OLD_TASK_KEYS = ["id", "title", "status", "ref", "after", "ready"]
ACTIVE_KEYS = ["branch", "worktree", "via", "sessions", "agents", "last_signal"]


# =========================================================================== хелперы


def _env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ)
    for var in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"):
        env.pop(var, None)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    if extra:
        env.update(extra)
    return env


def at(minutes: int = 0, seconds: int = 0) -> str:
    """ts журнала: NOW минус интервал, формат `YYYY-MM-DDTHH:MM:SS` (местное, без пояса)."""
    return (_NOW_DT - timedelta(minutes=minutes, seconds=seconds)).isoformat(timespec="seconds")


def rec(ts: str, session: str = "s1", agent: str = "a1", event: str = "SubagentStart") -> dict:
    return {
        "ts": ts,
        "event": event,
        "agent_type": "developer",
        "agent_id": agent,
        "session_id": session,
        "source": "hook",
        "cwd": "x",
        "branch": "x",
        "tail": "",
    }


def plan_md(*header: str, filler: int = 0) -> str:
    """План: заголовок, `filler` строк-пустышек, строки шапки `header`, раздел порядка с одной задачей."""
    lines = ["# План", ""] + [f"строка {i}" for i in range(filler)] + list(header) + [""]
    return "\n".join(lines) + "\n## Порядок выполнения\n\n- Task 1.1: x [PENDING]\n"


def branch_line(branch: str) -> str:
    return f"- **Ветка:** {branch}"


def run_cli(
    root: Path, *flags: str, env: dict[str, str] | None = None, cwd: Path | None = None
) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROGRESS), "--root", str(root), *flags],
        capture_output=True,
        timeout=CALL_TIMEOUT,
        env=_env(env),
        cwd=str(cwd) if cwd else None,
        encoding="utf-8",
        errors="replace",
    )


def _out(cp: subprocess.CompletedProcess) -> str:
    return f"exit={cp.returncode}\nstdout={cp.stdout[:500]!r}\nstderr={cp.stderr[:500]!r}"


def get_plans(root: Path, *flags: str, cwd: Path | None = None, env: dict[str, str] | None = None) -> dict[str, dict]:
    """`--json --now NOW ...` -> {имя_плана_без_.md: запись}."""
    cp = run_cli(root, "--json", "--now", NOW, *flags, cwd=cwd, env=env)
    assert cp.returncode == 0, f"--json: {_out(cp)}"
    data = json.loads(cp.stdout)
    assert isinstance(data, list), f"--json должен печатать список: {_out(cp)}"
    return {(r["plan"][:-3] if r["plan"].endswith(".md") else r["plan"]): r for r in data}


def get_who(root: Path, *flags: str, cwd: Path | None = None, env: dict[str, str] | None = None) -> dict:
    cp = run_cli(root, "--who", "--now", NOW, *flags, cwd=cwd, env=env)
    assert cp.returncode == 0, f"--who: {_out(cp)}"
    obj = json.loads(cp.stdout)
    assert isinstance(obj, dict), f"--who должен печатать объект: {_out(cp)}"
    return obj


def active_of(plans: dict[str, dict], name: str) -> list[dict]:
    assert name in plans, f"плана {name!r} нет в --json; есть: {sorted(plans)}"
    assert "active" in plans[name], f"у плана {name!r} нет ключа active; есть: {list(plans[name])}"
    return plans[name]["active"]


def entry_at(entries: list[dict], path: Path) -> dict:
    found = [e for e in entries if Path(e["worktree"]) == path]
    assert len(found) == 1, f"ждали одну запись для {path}, есть: {[e['worktree'] for e in entries]}"
    return found[0]


class Repo:
    """Настоящий git-репозиторий: `repo/` (главное дерево) и соседние `wt_<имя>/` (worktree)."""

    def __init__(self, base: Path, files: dict[str, str], initial: str = "main") -> None:
        self.base = base.resolve()
        self.root = self.base / "repo"
        self.initial = initial
        (self.root / "plans").mkdir(parents=True)
        (self.root / "NOTES.txt").write_text("fixture", encoding="utf-8")  # коммит не пустой даже без планов
        for rel, text in files.items():
            p = self.root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(text.encode("utf-8"))
        self.git(self.root, "init", "-q", "-b", initial)
        self.git(self.root, "config", "extensions.worktreeConfig", "true")
        self.git(self.root, "config", "user.name", "tester")
        self.git(self.root, "config", "user.email", "t@example.invalid")
        self.git(self.root, "config", "core.autocrlf", "false")
        self.git(self.root, "config", "commit.gpgsign", "false")
        self.git(self.root, "add", "-A")
        self.git(self.root, "commit", "-q", "-m", "init")

    def git(self, cwd: Path, *args: str) -> str:
        cp = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            timeout=CALL_TIMEOUT,
            env=_env(),
            encoding="utf-8",
            errors="replace",
        )
        assert cp.returncode == 0, f"git {' '.join(args)}: {cp.stderr[:400]}"
        return cp.stdout

    def worktree(self, name: str, branch: str | None = None) -> Path:
        """`branch=None` -> detached HEAD. Ветка создаётся от главной ветки репозитория."""
        path = self.base / f"wt_{name}"
        if branch is None:
            self.git(self.root, "worktree", "add", "-q", "--detach", str(path), self.initial)
        else:
            self.git(self.root, "worktree", "add", "-q", "-b", branch, str(path), self.initial)
        return path.resolve()

    def commit(self, wt: Path, subject: str, *trailers: str) -> None:
        message = subject + "\n\n" + "\n".join(["Why: w", "Layer: tests", *trailers])
        self.git(wt, "commit", "-q", "--allow-empty", "-m", message)

    def plan_ref(self, wt: Path, value: str) -> None:
        self.git(wt, "config", "--worktree", "plan.ref", value)

    @staticmethod
    def journal(wt: Path, *lines: dict | str) -> None:
        path = wt / "data" / "agent-journal.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        text = "".join((ln if isinstance(ln, str) else json.dumps(ln, ensure_ascii=False)) + "\n" for ln in lines)
        path.write_bytes(text.encode("utf-8"))

    def fresh(self, wt: Path, session: str = "s1", agent: str = "a1", minutes: int = 5) -> None:
        self.journal(wt, rec(at(minutes), session, agent))

    def control(self) -> Path:
        """Контрольный worktree: план CTRL с шапкой, свежая строка. Обязан попасть в `active` плана CTRL."""
        wt = self.worktree("ctrl", "feat/ctrl")
        self.fresh(wt)
        return wt


def assert_control(plans: dict[str, dict]) -> None:
    got = active_of(plans, "CTRL")
    assert len(got) == 1 and got[0]["branch"] == "feat/ctrl", f"контроль не сработал: {got}"


def make_repo(tmp_path: Path, files: dict[str, str] | None = None, initial: str = "main", ctrl: bool = True) -> Repo:
    base = {"plans/CTRL/plan.md": plan_md(branch_line("feat/ctrl"))}
    if not ctrl:
        base = {}
    return Repo(tmp_path, {**base, **(files or {})}, initial)


# =========================================================================== A1: шапка + свежая строка


def test_a1_header_branch_with_fresh_signal_marks_plan_active(tmp_path):
    repo = make_repo(tmp_path, {"plans/X/plan.md": plan_md(branch_line("feat/x"))})
    wt = repo.worktree("x", "feat/x")
    repo.fresh(wt, minutes=5)
    plans = get_plans(repo.root)
    got = active_of(plans, "X")
    assert len(got) == 1, got
    assert got[0]["branch"] == "feat/x"
    assert got[0]["via"] == "header"
    assert got[0]["sessions"] == 1
    assert Path(got[0]["worktree"]) == wt


def test_a1_active_entry_keys_in_documented_order(tmp_path):
    repo = make_repo(tmp_path, {"plans/X/plan.md": plan_md(branch_line("feat/x"))})
    repo.fresh(repo.worktree("x", "feat/x"))
    got = active_of(get_plans(repo.root), "X")
    assert list(got[0]) == ACTIVE_KEYS, list(got[0])


def test_a1_signal_older_than_window_leaves_plan_inactive_and_out_of_who(tmp_path):
    repo = make_repo(tmp_path, {"plans/X/plan.md": plan_md(branch_line("feat/x"))})
    wt_x = repo.worktree("x", "feat/x")
    repo.journal(wt_x, rec(at(minutes=120)))  # разница 2 ч при окне 1 ч
    repo.control()
    plans = get_plans(repo.root, "--active-window", "1h")
    assert_control(plans)
    assert active_of(plans, "X") == []
    who = get_who(repo.root, "--active-window", "1h")
    assert [Path(e["worktree"]) for e in who["active"] + who["orphans"]] == [repo.base / "wt_ctrl"], (
        f"в --who чужой корень: {who}"
    )


def test_a1_signal_exactly_at_window_edge_is_fresh(tmp_path):
    repo = make_repo(tmp_path, {"plans/X/plan.md": plan_md(branch_line("feat/x"))})
    repo.journal(repo.worktree("x", "feat/x"), rec(at(minutes=60)))
    plans = get_plans(repo.root, "--active-window", "1h")
    assert len(active_of(plans, "X")) == 1


def test_a1_signal_one_second_past_window_edge_is_stale(tmp_path):
    repo = make_repo(tmp_path, {"plans/X/plan.md": plan_md(branch_line("feat/x"))})
    repo.journal(repo.worktree("x", "feat/x"), rec(at(minutes=60, seconds=1)))
    repo.control()
    plans = get_plans(repo.root, "--active-window", "1h")
    assert_control(plans)
    assert active_of(plans, "X") == []


def test_a1_future_signal_is_fresh(tmp_path):
    repo = make_repo(tmp_path, {"plans/X/plan.md": plan_md(branch_line("feat/x"))})
    repo.journal(repo.worktree("x", "feat/x"), rec("2026-10-03T13:00:00"))
    got = active_of(get_plans(repo.root), "X")
    assert len(got) == 1 and got[0]["last_signal"] == "2026-10-03T13:00:00"


def test_default_window_is_six_hours_on_both_sides_of_the_edge(tmp_path):
    repo = make_repo(
        tmp_path,
        {
            "plans/IN/plan.md": plan_md(branch_line("feat/in")),
            "plans/OUT/plan.md": plan_md(branch_line("feat/out")),
        },
    )
    repo.journal(repo.worktree("in", "feat/in"), rec(at(minutes=359)))
    repo.journal(repo.worktree("out", "feat/out"), rec(at(minutes=361)))
    repo.control()
    plans = get_plans(repo.root)  # окно по умолчанию
    assert_control(plans)
    assert len(active_of(plans, "IN")) == 1
    assert active_of(plans, "OUT") == []


@pytest.mark.parametrize(
    ("window", "age_minutes", "fresh"),
    [
        ("30m", 20, True),
        ("30m", 40, False),
        ("2h", 119, True),
        ("2h", 121, False),
        ("1d", 23 * 60, True),
        ("1d", 25 * 60, False),
    ],
)
def test_window_units_minutes_hours_days(tmp_path, window, age_minutes, fresh):
    repo = make_repo(tmp_path, {"plans/X/plan.md": plan_md(branch_line("feat/x"))})
    repo.journal(repo.worktree("x", "feat/x"), rec(at(minutes=age_minutes)))
    repo.control()
    plans = get_plans(repo.root, "--active-window", window)
    assert_control(plans)
    assert (len(active_of(plans, "X")) == 1) is fresh


def test_default_now_is_the_real_clock(tmp_path):
    """Без --now: строка 2099 года свежая (будущее), строка 2000 года — нет."""
    repo = make_repo(tmp_path, {"plans/X/plan.md": plan_md(branch_line("feat/x"))}, ctrl=False)
    repo.journal(
        repo.worktree("x", "feat/x"),
        rec("2000-01-01T00:00:00", session="sOld"),
        rec("2099-01-01T00:00:00", session="sFuture"),
    )
    cp = run_cli(repo.root, "--json")
    assert cp.returncode == 0, _out(cp)
    plans = {r["plan"].removesuffix(".md"): r for r in json.loads(cp.stdout)}
    got = active_of(plans, "X")
    assert len(got) == 1 and got[0]["sessions"] == 1 and got[0]["last_signal"] == "2099-01-01T00:00:00"


def test_journal_outside_the_worktree_list_is_not_read(tmp_path):
    repo = make_repo(tmp_path, {"plans/X/plan.md": plan_md(branch_line("feat/x"))})
    repo.control()
    # каталоги с журналом, но не worktree из `git worktree list`
    repo.fresh(repo.root / ".claude" / "worktrees" / "ghost")
    repo.fresh(repo.base / "not_a_worktree")
    plans = get_plans(repo.root)
    assert_control(plans)
    who = get_who(repo.root)
    assert [Path(e["worktree"]) for e in who["active"] + who["orphans"]] == [repo.base / "wt_ctrl"], who


def test_worktree_without_journal_is_unknown_not_orphan(tmp_path):
    repo = make_repo(tmp_path, {"plans/X/plan.md": plan_md(branch_line("feat/x"))})
    repo.worktree("x", "feat/x")  # журнала нет
    repo.control()
    plans = get_plans(repo.root)
    assert_control(plans)
    assert active_of(plans, "X") == []
    who = get_who(repo.root)
    assert [Path(e["worktree"]) for e in who["active"] + who["orphans"]] == [repo.base / "wt_ctrl"], who


# =========================================================================== A2: шаг refs


def test_a2_refs_commit_resolves_plan_via_refs(tmp_path):
    repo = make_repo(tmp_path, {"plans/Y/plan.md": plan_md()})
    wt = repo.worktree("y", "feat/y")
    repo.commit(wt, "feat: y", "Refs: plans/Y/tasks/1.1.md")
    repo.fresh(wt)
    got = active_of(get_plans(repo.root), "Y")
    assert len(got) == 1
    assert got[0]["branch"] == "feat/y" and got[0]["via"] == "refs"


def test_a2_newest_refs_commit_wins_over_older(tmp_path):
    repo = make_repo(tmp_path, {"plans/Y/plan.md": plan_md(), "plans/Z/plan.md": plan_md()})
    wt = repo.worktree("y", "feat/y")
    repo.commit(wt, "feat: y", "Refs: plans/Y/tasks/1.1.md")
    repo.commit(wt, "feat: z", "Refs: plans/Z/tasks/1.1.md")
    repo.fresh(wt)
    plans = get_plans(repo.root)
    assert len(active_of(plans, "Z")) == 1 and active_of(plans, "Z")[0]["via"] == "refs"
    assert active_of(plans, "Y") == []


def test_a2_newest_commit_naming_unknown_plan_does_not_fall_back_to_older_one(tmp_path):
    repo = make_repo(tmp_path, {"plans/Y/plan.md": plan_md()})  # плана N нет, шапки нет
    wt = repo.worktree("y", "feat/y")
    repo.commit(wt, "feat: y", "Refs: plans/Y/tasks/1.1.md")
    repo.commit(wt, "feat: n", "Refs: plans/N")
    repo.fresh(wt)
    repo.control()
    plans = get_plans(repo.root)
    assert_control(plans)
    assert active_of(plans, "Y") == []
    who = get_who(repo.root)
    assert [Path(e["worktree"]) for e in who["orphans"]] == [wt], who


def test_a2_newer_commit_without_plans_token_is_skipped_for_older_one(tmp_path):
    repo = make_repo(tmp_path, {"plans/Y/plan.md": plan_md()})
    wt = repo.worktree("y", "feat/y")
    repo.commit(wt, "feat: y", "Refs: plans/Y/tasks/1.1.md")
    repo.commit(wt, "docs: adr", "Refs: ADR-120")  # Refs без токена plans/... — не кандидат
    repo.commit(wt, "chore: nothing")  # вовсе без Refs
    repo.fresh(wt)
    got = active_of(get_plans(repo.root), "Y")
    assert len(got) == 1 and got[0]["via"] == "refs"


def test_a2_unknown_refs_name_still_lets_header_step_run(tmp_path):
    repo = make_repo(tmp_path, {"plans/Y/plan.md": plan_md(), "plans/H/plan.md": plan_md(branch_line("feat/y"))})
    wt = repo.worktree("y", "feat/y")
    repo.commit(wt, "feat: y", "Refs: plans/Y/tasks/1.1.md")
    repo.commit(wt, "feat: n", "Refs: plans/N")
    repo.fresh(wt)
    plans = get_plans(repo.root)
    got = active_of(plans, "H")
    assert len(got) == 1 and got[0]["via"] == "header"
    assert active_of(plans, "Y") == []


def test_a2_refs_beats_header(tmp_path):
    repo = make_repo(tmp_path, {"plans/Y/plan.md": plan_md(), "plans/H/plan.md": plan_md(branch_line("feat/y"))})
    wt = repo.worktree("y", "feat/y")
    repo.commit(wt, "feat: y", "Refs: plans/Y/tasks/1.1.md")
    repo.fresh(wt)
    plans = get_plans(repo.root)
    assert len(active_of(plans, "Y")) == 1 and active_of(plans, "Y")[0]["via"] == "refs"
    assert active_of(plans, "H") == []


def test_a2_first_plans_token_wins_and_trailing_punctuation_is_cut(tmp_path):
    repo = make_repo(tmp_path, {"plans/Y/plan.md": plan_md(), "plans/Z/plan.md": plan_md()})
    wt = repo.worktree("y", "feat/y")
    repo.commit(wt, "feat: y", "Refs: plans/Y/plan.md, plans/Z/plan.md; ADR-120")
    repo.fresh(wt)
    plans = get_plans(repo.root)
    assert len(active_of(plans, "Y")) == 1
    assert active_of(plans, "Z") == []


def test_a2_refs_to_flat_plan_file_names_plan_without_md_suffix(tmp_path):
    repo = make_repo(tmp_path, {"plans/F.md": plan_md()})
    wt = repo.worktree("f", "feat/f")
    repo.commit(wt, "feat: f", "Refs: plans/F.md")
    repo.fresh(wt)
    got = active_of(get_plans(repo.root), "F")
    assert len(got) == 1 and got[0]["via"] == "refs"


def test_a2_commits_already_on_main_are_not_a_trace(tmp_path):
    repo = make_repo(tmp_path, {"plans/Y/plan.md": plan_md()})
    repo.commit(repo.root, "feat: y on main", "Refs: plans/Y/tasks/1.1.md")  # на main, до создания ветки
    wt = repo.worktree("y", "feat/y")  # своих коммитов у ветки нет
    repo.fresh(wt)
    repo.control()
    plans = get_plans(repo.root)
    assert_control(plans)
    assert active_of(plans, "Y") == []
    who = get_who(repo.root)
    assert [Path(e["worktree"]) for e in who["orphans"]] == [wt], who


def test_a2_without_branch_named_main_the_refs_step_gives_no_plan(tmp_path):
    repo = make_repo(tmp_path, {"plans/Y/plan.md": plan_md()}, initial="trunk")
    wt = repo.worktree("y", "feat/y")
    repo.commit(wt, "feat: y", "Refs: plans/Y/tasks/1.1.md")
    repo.fresh(wt)
    repo.control()
    plans = get_plans(repo.root)
    assert_control(plans)
    assert active_of(plans, "Y") == []
    who = get_who(repo.root)
    assert [Path(e["worktree"]) for e in who["orphans"]] == [wt], who


# =========================================================================== A3: plan.ref и порядок шагов


def test_a3_plan_ref_beats_header(tmp_path):
    repo = make_repo(tmp_path, {"plans/A/plan.md": plan_md(), "plans/B/plan.md": plan_md(branch_line("feat/a"))})
    wt = repo.worktree("a", "feat/a")
    repo.plan_ref(wt, "plans/A")
    repo.fresh(wt)
    plans = get_plans(repo.root)
    got = active_of(plans, "A")
    assert len(got) == 1 and got[0]["via"] == "plan_ref" and got[0]["branch"] == "feat/a"
    assert active_of(plans, "B") == []


def test_a3_plan_ref_beats_refs_commit(tmp_path):
    repo = make_repo(tmp_path, {"plans/A/plan.md": plan_md(), "plans/Y/plan.md": plan_md()})
    wt = repo.worktree("a", "feat/a")
    repo.commit(wt, "feat: y", "Refs: plans/Y/tasks/1.1.md")
    repo.plan_ref(wt, "plans/A")
    repo.fresh(wt)
    plans = get_plans(repo.root)
    assert len(active_of(plans, "A")) == 1 and active_of(plans, "A")[0]["via"] == "plan_ref"
    assert active_of(plans, "Y") == []


def test_a3_plan_ref_accepts_bare_plan_name(tmp_path):
    repo = make_repo(tmp_path, {"plans/A/plan.md": plan_md()})
    wt = repo.worktree("a", "feat/a")
    repo.plan_ref(wt, "A")
    repo.fresh(wt)
    got = active_of(get_plans(repo.root), "A")
    assert len(got) == 1 and got[0]["via"] == "plan_ref"


def test_a3_plan_ref_with_path_inside_plan_names_the_plan(tmp_path):
    repo = make_repo(tmp_path, {"plans/A/plan.md": plan_md()})
    wt = repo.worktree("a", "feat/a")
    repo.plan_ref(wt, "plans/A/tasks/1.1.md")
    repo.fresh(wt)
    got = active_of(get_plans(repo.root), "A")
    assert len(got) == 1 and got[0]["via"] == "plan_ref"


def test_a3_plan_ref_with_unknown_name_falls_through_to_header(tmp_path):
    repo = make_repo(tmp_path, {"plans/B/plan.md": plan_md(branch_line("feat/a"))})
    wt = repo.worktree("a", "feat/a")
    repo.plan_ref(wt, "plans/NoSuchPlan")
    repo.fresh(wt)
    got = active_of(get_plans(repo.root), "B")
    assert len(got) == 1 and got[0]["via"] == "header"


def test_a3_plan_ref_works_on_detached_head(tmp_path):
    repo = make_repo(tmp_path, {"plans/A/plan.md": plan_md()})
    wt = repo.worktree("a", None)
    repo.plan_ref(wt, "plans/A")
    repo.fresh(wt)
    got = active_of(get_plans(repo.root), "A")
    assert len(got) == 1 and got[0]["via"] == "plan_ref" and got[0]["branch"] == ""


def test_a3_plan_ref_is_per_worktree(tmp_path):
    repo = make_repo(tmp_path, {"plans/A/plan.md": plan_md(), "plans/B/plan.md": plan_md()})
    wa = repo.worktree("a", "feat/a")
    wb = repo.worktree("b", "feat/b")
    repo.plan_ref(wa, "plans/A")
    repo.plan_ref(wb, "plans/B")
    repo.fresh(wa)
    repo.fresh(wb)
    plans = get_plans(repo.root)
    assert [Path(e["worktree"]) for e in active_of(plans, "A")] == [wa]
    assert [Path(e["worktree"]) for e in active_of(plans, "B")] == [wb]


# =========================================================================== шаг header (разметка, границы)


@pytest.mark.parametrize(
    "line",
    [
        "- **Ветка:** feat/x",
        "- **Ветка:** `feat/x`",
        "- **Branch:** feat/x",
        "- **Ветка:** `feat/x` — трек (от main)",
        "- **Ветка:** feat/x (от main)",
        "Ветка: feat/x",
    ],
)
def test_header_line_markup_variants_resolve_the_branch(tmp_path, line):
    repo = make_repo(tmp_path, {"plans/X/plan.md": plan_md(line)})
    repo.fresh(repo.worktree("x", "feat/x"))
    got = active_of(get_plans(repo.root), "X")
    assert len(got) == 1 and got[0]["via"] == "header"


def test_header_line_30_counts_and_line_31_does_not(tmp_path):
    # строки: 1 «# План», 2 пустая, затем filler; Ветка стоит ровно на 30-й / 31-й строке
    repo = make_repo(
        tmp_path,
        {
            "plans/L30/plan.md": plan_md(branch_line("feat/l30"), filler=27),
            "plans/L31/plan.md": plan_md(branch_line("feat/l31"), filler=28),
        },
    )
    text30 = (repo.root / "plans/L30/plan.md").read_text(encoding="utf-8").split("\n")
    text31 = (repo.root / "plans/L31/plan.md").read_text(encoding="utf-8").split("\n")
    assert text30[29].startswith("- **Ветка:**") and text31[30].startswith("- **Ветка:**")  # контроль фикстуры
    repo.fresh(repo.worktree("l30", "feat/l30"))
    repo.fresh(repo.worktree("l31", "feat/l31"))
    repo.control()
    plans = get_plans(repo.root)
    assert_control(plans)
    assert len(active_of(plans, "L30")) == 1
    assert active_of(plans, "L31") == []


def test_header_branch_must_match_the_whole_name(tmp_path):
    repo = make_repo(tmp_path, {"plans/X/plan.md": plan_md(branch_line("feat/xy"))})
    wt = repo.worktree("x", "feat/x")
    repo.fresh(wt)
    repo.control()
    plans = get_plans(repo.root)
    assert_control(plans)
    assert active_of(plans, "X") == []
    assert [Path(e["worktree"]) for e in get_who(repo.root)["orphans"]] == [wt]


def test_header_same_branch_in_two_live_plans_gives_no_plan(tmp_path):
    repo = make_repo(
        tmp_path,
        {"plans/P/plan.md": plan_md(branch_line("feat/dup")), "plans/Q/plan.md": plan_md(branch_line("feat/dup"))},
    )
    wt = repo.worktree("dup", "feat/dup")
    repo.fresh(wt)
    repo.control()
    plans = get_plans(repo.root)
    assert_control(plans)
    assert active_of(plans, "P") == [] and active_of(plans, "Q") == []
    assert [Path(e["worktree"]) for e in get_who(repo.root)["orphans"]] == [wt]


def test_header_live_plan_is_preferred_over_archived(tmp_path):
    repo = make_repo(
        tmp_path,
        {
            "plans/LIVE/plan.md": plan_md(branch_line("feat/x")),
            "plans/_archive/OLD/plan.md": plan_md(branch_line("feat/x")),
        },
    )
    repo.fresh(repo.worktree("x", "feat/x"))
    plans = get_plans(repo.root)
    assert len(active_of(plans, "LIVE")) == 1
    assert active_of(plans, "OLD") == []


def test_header_archived_plan_is_used_when_no_live_plan_has_the_branch(tmp_path):
    repo = make_repo(tmp_path, {"plans/_archive/OLD/plan.md": plan_md(branch_line("feat/x"))})
    repo.fresh(repo.worktree("x", "feat/x"))
    got = active_of(get_plans(repo.root), "OLD")
    assert len(got) == 1 and got[0]["via"] == "header"


# =========================================================================== A4: сироты


def test_a4_root_without_plan_by_any_step_is_orphan_with_branch(tmp_path):
    repo = make_repo(tmp_path)
    wt = repo.worktree("lonely", "feat/lonely")
    repo.fresh(wt)
    repo.control()
    plans = get_plans(repo.root)
    assert_control(plans)
    who = get_who(repo.root)
    assert [Path(e["worktree"]) for e in who["orphans"]] == [wt]
    assert who["orphans"][0]["branch"] == "feat/lonely"
    assert [Path(e["worktree"]) for e in who["active"]] == [repo.base / "wt_ctrl"]


def test_a4_detached_head_without_plan_ref_is_orphan_with_empty_branch(tmp_path):
    repo = make_repo(tmp_path)
    wt = repo.worktree("det", None)
    repo.fresh(wt)
    repo.control()
    assert_control(get_plans(repo.root))
    orphans = get_who(repo.root)["orphans"]
    assert [Path(e["worktree"]) for e in orphans] == [wt]
    assert orphans[0]["branch"] == ""


def test_a4_main_tree_with_fresh_signal_is_orphan_on_main(tmp_path):
    repo = make_repo(tmp_path)
    repo.fresh(repo.root)  # журнал главного дерева
    repo.control()
    assert_control(get_plans(repo.root))
    orphans = get_who(repo.root)["orphans"]
    assert [Path(e["worktree"]) for e in orphans] == [repo.root]
    assert orphans[0]["branch"] == "main"


def test_a4_orphan_entry_has_counters_but_no_plan_or_via(tmp_path):
    repo = make_repo(tmp_path)
    repo.journal(
        repo.worktree("lonely", "feat/lonely"),
        rec(at(10), session="s1", agent="a1"),
        rec(at(5), session="s2", agent="a1"),
    )
    orphans = get_who(repo.root)["orphans"]
    assert len(orphans) == 1
    assert set(orphans[0]) == {"branch", "worktree", "sessions", "agents", "last_signal"}
    assert orphans[0]["sessions"] == 2 and orphans[0]["agents"] == 1
    assert orphans[0]["last_signal"] == at(5)


def test_who_active_entry_carries_plan_name_and_the_same_fields(tmp_path):
    repo = make_repo(tmp_path, {"plans/X/plan.md": plan_md(branch_line("feat/x"))}, ctrl=False)
    wt = repo.worktree("x", "feat/x")
    repo.fresh(wt)
    who = get_who(repo.root)
    assert who["orphans"] == []
    assert len(who["active"]) == 1
    e = who["active"][0]
    assert set(e) == {"plan", "branch", "worktree", "via", "sessions", "agents", "last_signal"}
    assert e["plan"] == "X" and e["via"] == "header" and e["branch"] == "feat/x"
    assert Path(e["worktree"]) == wt


def test_who_prints_exactly_one_json_object_with_two_keys(tmp_path):
    repo = make_repo(tmp_path, {"plans/X/plan.md": plan_md(branch_line("feat/x"))})
    repo.fresh(repo.worktree("x", "feat/x"))
    cp = run_cli(repo.root, "--who", "--now", NOW)
    assert cp.returncode == 0, _out(cp)
    assert list(json.loads(cp.stdout)) == ["active", "orphans"]  # json.loads падает на любом постороннем тексте


def test_who_lists_are_sorted_by_worktree_ascending(tmp_path):
    repo = make_repo(tmp_path, ctrl=False)
    wc = repo.worktree("c", "feat/c")  # создаются не по порядку
    wa = repo.worktree("a", "feat/a")
    wb = repo.worktree("b", "feat/b")
    for wt in (wc, wa, wb):
        repo.fresh(wt)
    orphans = get_who(repo.root)["orphans"]
    assert [Path(e["worktree"]) for e in orphans] == [wa, wb, wc]


def test_who_active_list_is_sorted_by_worktree_ascending(tmp_path):
    repo = make_repo(
        tmp_path,
        {"plans/X/plan.md": plan_md(), "plans/Z/plan.md": plan_md()},
        ctrl=False,
    )
    wc = repo.worktree("c", "feat/c")
    wa = repo.worktree("a", "feat/a")
    wb = repo.worktree("b", "feat/b")
    for wt, name in ((wc, "X"), (wa, "Z"), (wb, "X")):
        repo.plan_ref(wt, f"plans/{name}")
        repo.fresh(wt)
    active = get_who(repo.root)["active"]
    assert [(Path(e["worktree"]), e["plan"]) for e in active] == [(wa, "Z"), (wb, "X"), (wc, "X")]


def test_json_active_of_one_plan_is_sorted_by_worktree_ascending(tmp_path):
    repo = make_repo(tmp_path, {"plans/X/plan.md": plan_md()}, ctrl=False)
    wc = repo.worktree("c", "feat/c")
    wa = repo.worktree("a", "feat/a")
    for wt in (wc, wa):
        repo.plan_ref(wt, "plans/X")
        repo.fresh(wt)
    assert [Path(e["worktree"]) for e in active_of(get_plans(repo.root), "X")] == [wa, wc]


# =========================================================================== A5: нет git — нет корней


def _plain_root(tmp_path: Path, with_journal: bool) -> Path:
    root = tmp_path / "plain"
    (root / "plans" / "X").mkdir(parents=True)
    (root / "plans" / "X" / "plan.md").write_text(plan_md(branch_line("feat/x")), encoding="utf-8")
    (root / "plans" / "Y.md").write_text(plan_md(), encoding="utf-8")
    if with_journal:
        Repo.journal(root, rec(at(5)))
    return root


def _assert_no_roots(root: Path, **kw) -> None:
    plans = get_plans(root, **kw)
    assert "X" in plans and "Y" in plans, sorted(plans)
    for name in ("X", "Y"):
        assert active_of(plans, name) == []
    cp = run_cli(root, "--who", "--now", NOW, **kw)
    assert cp.returncode == 0, _out(cp)
    assert json.loads(cp.stdout) == {"active": [], "orphans": []}


def test_a5_root_without_git_init_inside_foreign_repo_has_no_roots(tmp_path):
    """tmp_path лежит в чужом репозитории (ловушка): его worktree не наши корни, даже с журналом в data/."""
    _assert_no_roots(_plain_root(tmp_path, with_journal=True), cwd=tmp_path)


def test_a5_root_without_git_isolated_from_any_repo_has_no_roots(tmp_path):
    """Здесь GIT_CEILING_DIRECTORIES=tmp_path: git не поднимается выше, каталог вне любого репозитория."""
    root = _plain_root(tmp_path, with_journal=True)
    _assert_no_roots(root, cwd=tmp_path, env={"GIT_CEILING_DIRECTORIES": str(tmp_path.resolve())})


def test_a5_no_journal_and_no_git_gives_the_same_empty_answer(tmp_path):
    _assert_no_roots(_plain_root(tmp_path, with_journal=False), cwd=tmp_path)


def test_a5_root_that_is_a_subdirectory_of_a_repo_has_no_roots(tmp_path):
    """toplevel (repo/) != --root (repo/sub): корней нет, хотя журнал свежий и в главном дереве, и в sub/."""
    plan = plan_md(branch_line("feat/w"))
    repo = Repo(tmp_path, {"plans/X/plan.md": plan, "sub/plans/X/plan.md": plan})
    repo.fresh(repo.root)
    repo.fresh(repo.root / "sub")
    repo.fresh(repo.worktree("w", "feat/w"))  # будь sub корнем — X стал бы активным по шапке
    sub = repo.root / "sub"
    plans = get_plans(sub, cwd=tmp_path)
    assert active_of(plans, "X") == []
    cp = run_cli(sub, "--who", "--now", NOW, cwd=tmp_path)
    assert cp.returncode == 0, _out(cp)
    assert json.loads(cp.stdout) == {"active": [], "orphans": []}


def test_a5_control_same_plans_in_a_real_repo_root_do_see_the_roots(tmp_path):
    """Контроль к A5: тот же набор планов и свежий журнал, но --root = toplevel настоящего репозитория."""
    repo = Repo(tmp_path, {"plans/X/plan.md": plan_md(branch_line("feat/x")), "plans/Y.md": plan_md()}, "main")
    repo.fresh(repo.worktree("x", "feat/x"))
    plans = get_plans(repo.root, cwd=tmp_path)
    got = active_of(plans, "X")
    assert len(got) == 1 and got[0]["branch"] == "feat/x" and got[0]["via"] == "header"


# =========================================================================== A6: журнал


def test_a6_unusable_lines_are_ignored_and_counters_come_from_valid_lines(tmp_path):
    repo = make_repo(tmp_path, {"plans/X/plan.md": plan_md(branch_line("feat/x"))}, ctrl=False)
    wt = repo.worktree("x", "feat/x")
    bad = {"event": "SubagentStart", "agent_type": "d"}
    repo.journal(
        wt,
        "{broken json",
        "42",
        "null",
        "[1, 2]",
        '"text"',
        "",
        {**bad, "ts": at(10), "event": "", "session_id": "sBad1", "agent_id": "aBad1"},
        {**bad, "ts": "x", "session_id": "sBad2", "agent_id": "aBad2"},
        {**bad, "ts": "2026-10-03T11:58:00+03:00", "session_id": "sBad3", "agent_id": "aBad3"},
        {**bad, "ts": 12345, "session_id": "sBad4", "agent_id": "aBad4"},
        rec("2026-10-03T11:30:00", "s1", "a1"),
        rec("2026-10-03T11:50:00", "s2", "a1"),  # наибольший ts стоит не последним
        rec("2026-10-03T11:40:00", "s1", "a1"),
    )
    got = active_of(get_plans(repo.root), "X")
    assert len(got) == 1
    assert got[0]["sessions"] == 2
    assert got[0]["agents"] == 1
    assert got[0]["last_signal"] == "2026-10-03T11:50:00"


def test_a6_journal_with_only_unusable_lines_leaves_the_root_out_of_everything(tmp_path):
    repo = make_repo(tmp_path, {"plans/X/plan.md": plan_md(branch_line("feat/x"))})
    repo.journal(
        repo.worktree("x", "feat/x"),
        "{broken json",
        "42",
        {"ts": at(5), "event": "", "session_id": "s1", "agent_id": "a1"},
        {"ts": "x", "event": "Start", "session_id": "s1", "agent_id": "a1"},
        {"ts": "2026-10-03T11:55:00+03:00", "event": "Start", "session_id": "s1", "agent_id": "a1"},
    )
    repo.control()
    plans = get_plans(repo.root)
    assert_control(plans)
    assert active_of(plans, "X") == []
    who = get_who(repo.root)
    assert [Path(e["worktree"]) for e in who["active"] + who["orphans"]] == [repo.base / "wt_ctrl"], who


def test_a6_empty_session_and_agent_ids_are_not_counted(tmp_path):
    repo = make_repo(tmp_path, {"plans/X/plan.md": plan_md(branch_line("feat/x"))}, ctrl=False)
    repo.journal(
        repo.worktree("x", "feat/x"),
        rec(at(5), session="", agent=""),
        rec(at(4), session="s1", agent=""),
    )
    got = active_of(get_plans(repo.root), "X")
    assert len(got) == 1 and got[0]["sessions"] == 1 and got[0]["agents"] == 0


def test_a6_stale_lines_do_not_add_to_counters_or_last_signal(tmp_path):
    repo = make_repo(tmp_path, {"plans/X/plan.md": plan_md(branch_line("feat/x"))}, ctrl=False)
    repo.journal(
        repo.worktree("x", "feat/x"),
        rec(at(minutes=600), session="sOld", agent="aOld"),  # старше окна 6 ч
        rec(at(minutes=30), session="sNew", agent="aNew"),
    )
    got = active_of(get_plans(repo.root), "X")
    assert len(got) == 1
    assert got[0]["sessions"] == 1 and got[0]["agents"] == 1
    assert got[0]["last_signal"] == "2026-10-03T11:30:00"


# =========================================================================== A7: ошибки ввода и формат --json


@pytest.mark.parametrize("window", ["6x", "6", "h", "1w", "6hh"])
def test_a7_bad_active_window_exits_2_without_echoing_the_value(tmp_path, window):
    repo = make_repo(tmp_path, ctrl=False)
    ok = run_cli(repo.root, "--who", "--now", NOW, "--active-window", "6h")  # якорь: флаги существуют
    assert ok.returncode == 0, _out(ok)
    cp = run_cli(repo.root, "--who", "--now", NOW, "--active-window", window)
    assert cp.returncode == 2, _out(cp)
    assert cp.stderr.strip(), "ждали сообщение об ошибке в stderr"
    assert window not in cp.stderr, f"значение {window!r} не должно попасть в stderr: {cp.stderr!r}"


@pytest.mark.parametrize(
    "now",
    ["2026-10-03T12:00:00+03:00", "2026-10-03T12:00:00Z", "not-a-date", "2026-13-45T00:00:00"],
)
def test_a7_bad_or_zoned_now_exits_2_without_echoing_the_value(tmp_path, now):
    repo = make_repo(tmp_path, ctrl=False)
    ok = run_cli(repo.root, "--who", "--now", NOW)  # якорь: флаг существует
    assert ok.returncode == 0, _out(ok)
    cp = run_cli(repo.root, "--who", "--now", now)
    assert cp.returncode == 2, _out(cp)
    assert cp.stderr.strip(), "ждали сообщение об ошибке в stderr"
    assert now not in cp.stderr, f"значение {now!r} не должно попасть в stderr: {cp.stderr!r}"


@pytest.mark.parametrize("other", ["--json", "--html", "--check", "--sync-order"])
def test_a7_who_together_with_another_mode_exits_2(tmp_path, other):
    repo = make_repo(tmp_path, ctrl=False)
    ok = run_cli(repo.root, "--who", "--now", NOW)  # якорь: --who один — exit 0
    assert ok.returncode == 0, _out(ok)
    cp = run_cli(repo.root, "--who", other, "--now", NOW)
    assert cp.returncode == 2, _out(cp)
    assert cp.stderr.strip()


def test_a7_old_json_keys_and_their_order_are_unchanged_and_active_is_last(tmp_path):
    repo = make_repo(tmp_path, {"plans/X/plan.md": plan_md(branch_line("feat/x"))})
    repo.fresh(repo.worktree("x", "feat/x"))
    plans = get_plans(repo.root)
    for name, p in plans.items():
        assert list(p) == [*OLD_PLAN_KEYS, "active", "branches"], f"{name}: {list(p)}"
        for t in p["tasks"]:
            assert list(t) == OLD_TASK_KEYS, f"{name}: {list(t)}"


def test_a7_active_is_an_empty_list_for_plans_without_any_worktree(tmp_path):
    repo = make_repo(tmp_path, {"plans/X/plan.md": plan_md(branch_line("feat/x"))})
    repo.control()
    plans = get_plans(repo.root)
    assert_control(plans)
    assert plans["X"]["active"] == []
    assert list(plans["X"])[-2:] == ["active", "branches"]
