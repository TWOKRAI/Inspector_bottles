# ruff: noqa: E501  -- литералы-фикстуры и ожидания в одну строку, форматтер их не переносит
"""Приёмка Task 5.5 — слепые тесты ключа `branches`, флага `--branch-window` и чипа ветки.

Источник: plans/2026-10-02_plans-progress-dashboard/tasks/5.5.md (DESIGN, ACCEPTANCE 1-12).
Реализацию тестер не видел; читал только набор флагов CLI, форму `--json`/страницы до задачи и
способ сборки git-фикстур в соседних приёмочных файлах.

Только CLI в subprocess (timeout на каждый вызов): `plans_progress.py --root R --json|--html F
--now NOW [--branch-window W]`. Фикстура — настоящий `git init -b main` в tmp_path, даты коммитов
задаёт тест (`GIT_COMMITTER_DATE` / `GIT_AUTHOR_DATE` как unix-секунды). Ожидания — литералы.

Договорённости чтения (в тексте задачи неоднозначно; выбрано строгое чтение, см. отчёт):
- `branches` — ключ ЗАПИСИ ПЛАНА в `--json` (рядом с `active`), не верхнего уровня: строка 1 приёмки
  сравнивает `branches` и `done` в одном контексте, а `done` бывает только у плана. Ключ есть у КАЖДОГО
  плана, у ничьего — `[]`.
- Тесты «ветки нет в списке» несут контроль: рядом ветка, которая ОБЯЗАНА попасть в список. Без него
  заглушка «всегда []» была бы зелёной.
- Слияние по задачам (строка 12) проверено на числах, которые отличают каждое правило от соседнего:
  «ветка побеждает» и «диск побеждает» дают другой ответ, чем «движется к DONE».
- Равные вершины двух веток: родитель — меньшее имя, значит у большего имени нет своих правок
  относительно меньшего, и в списке остаётся только меньшее (прямое следствие DESIGN «Стек»).
- Тест `test_d_*` — закрепления DESIGN вне двенадцати строк приёмки; они помечены в докстроке.
- Страница: чип разбирается только внутри `<summary>` `<details class="plan">`.
- Окно свежести: `now - t <= окно`, ровно на краю — свежая, на секунду дальше — нет; будущее — свежее.
- `tmp_path` лежит внутри чужого git-репозитория: фикстура — собственный `git init`; случай «нет git»
  задаёт `GIT_CEILING_DIRECTORIES` и доказывает пустоту `git rev-parse` до запуска CLI.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
PROGRESS = REPO_ROOT / "scripts" / "plans_progress" / "plans_progress.py"
CALL_TIMEOUT = 60

NOW = "2026-10-03T12:00:00"
_NOW_DT = datetime.fromisoformat(NOW)

PLAN_KEYS_TAIL = ["active", "branches"]
ENTRY_KEYS = ["branch", "done", "total"]

D1 = timedelta(days=1)
D20 = timedelta(days=20)


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


def stamp(ago: timedelta) -> str:
    """Дата git: unix-секунды момента `NOW - ago` (NOW — местное время, как у `--now`)."""
    return f"{int((_NOW_DT - ago).timestamp())} +0000"


def items_md(tasks: list[tuple[str, str]], header: tuple[str, ...] = ()) -> str:
    """План с разделом порядка: пункты `- Task <id>: ... [<СТАТУС>]`."""
    lines = ["# План", ""] + list(header) + ["", "## Порядок выполнения", ""]
    lines += [f"- Task {tid}: задача {tid} [{st}]" for tid, st in tasks]
    return "\n".join(lines) + "\n"


def three(s1: str = "PENDING", s2: str = "PENDING", s3: str = "PENDING") -> str:
    return items_md([("1.1", s1), ("1.2", s2), ("1.3", s3)])


def head_md() -> str:
    """plan.md без списка задач (layout v2): задачи — в tasks/<id>.md."""
    return "# План\n\nописание без списка задач\n"


def task_file(tid: str, status: str) -> str:
    return f"# Task {tid}: задача {tid}\n\n**Статус:** {status}\n"


class Fx:
    """Настоящий git-репозиторий в `tmp_path/<name>`; ветка `main`."""

    def __init__(
        self, tmp_path: Path, files: dict[str, str] | None = None, name: str = "repo", main: str = "main"
    ) -> None:
        self.root = tmp_path / name
        self.root.mkdir(parents=True)
        self.base = tmp_path
        self.git("init", "-q", "-b", main)
        self.git("config", "user.name", "tester")
        self.git("config", "user.email", "t@example.invalid")
        self.git("config", "core.autocrlf", "false")
        self.git("config", "commit.gpgsign", "false")
        self.write("NOTES.txt", "fixture")
        for rel, text in (files or {}).items():
            self.write(rel, text)
        self.commit("init", ago=D20)

    def git(self, *args: str, cwd: Path | None = None, env: dict[str, str] | None = None) -> str:
        cp = subprocess.run(
            ["git", *args],
            cwd=str(cwd or self.root),
            capture_output=True,
            timeout=CALL_TIMEOUT,
            env=_env(env),
            encoding="utf-8",
            errors="replace",
        )
        assert cp.returncode == 0, f"git {' '.join(args)}: {cp.stderr[:400]}"
        return cp.stdout

    def write(self, rel: str, text: str, cwd: Path | None = None) -> None:
        p = (cwd or self.root) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(text.encode("utf-8"))

    def remove(self, rel: str) -> None:
        (self.root / rel).unlink()

    def commit(
        self, msg: str = "c", ago: timedelta = D1, author_ago: timedelta | None = None, cwd: Path | None = None
    ) -> None:
        self.git("add", "-A", cwd=cwd)
        env = {
            "GIT_COMMITTER_DATE": stamp(ago),
            "GIT_AUTHOR_DATE": stamp(author_ago if author_ago is not None else ago),
        }
        self.git("commit", "-q", "--allow-empty", "-m", msg, cwd=cwd, env=env)

    def branch(self, name: str, frm: str = "main") -> None:
        self.git("checkout", "-q", "-b", name, f"refs/heads/{frm}")

    def checkout(self, name: str) -> None:
        self.git("switch", "-q", name)

    def edit_on(
        self,
        branch: str,
        files: dict[str, str | None],
        frm: str = "main",
        ago: timedelta = D1,
        author_ago: timedelta | None = None,
    ) -> None:
        """Ветка `branch` от `frm`, один коммит: `files[rel] = None` — удалить файл. Возврат на main."""
        self.branch(branch, frm)
        for rel, text in files.items():
            if text is None:
                self.remove(rel)
            else:
                self.write(rel, text)
        self.commit(f"edit {branch}", ago=ago, author_ago=author_ago)
        self.checkout("main")

    def on_main(self, files: dict[str, str | None], ago: timedelta = D1) -> None:
        self.checkout("main")
        for rel, text in files.items():
            if text is None:
                self.remove(rel)
            else:
                self.write(rel, text)
        self.commit("main edit", ago=ago)


def run_cli(
    root: Path, *flags: str, env: dict[str, str] | None = None, cwd: Path | None = None
) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROGRESS), "--root", str(root), *flags],
        capture_output=True,
        timeout=CALL_TIMEOUT,
        env=_env(env),
        cwd=str(cwd or root.parent),
        encoding="utf-8",
        errors="replace",
    )


def _out(cp: subprocess.CompletedProcess) -> str:
    return f"exit={cp.returncode}\nstdout={cp.stdout[:500]!r}\nstderr={cp.stderr[:500]!r}"


def get_plans(root: Path, *flags: str, env: dict[str, str] | None = None) -> dict[str, dict]:
    """`--json --now NOW ...` -> {имя_плана: запись}."""
    cp = run_cli(root, "--json", "--now", NOW, *flags, env=env)
    assert cp.returncode == 0, f"--json: {_out(cp)}"
    data = json.loads(cp.stdout)
    assert isinstance(data, list), f"--json должен печатать список: {_out(cp)}"
    return {r["plan"]: r for r in data}


def branches_of(plans: dict[str, dict], name: str) -> list[dict]:
    assert name in plans, f"плана {name!r} нет в --json; есть: {sorted(plans)}"
    assert "branches" in plans[name], f"у плана {name!r} нет ключа branches; есть: {list(plans[name])}"
    return plans[name]["branches"]


def names_of(plans: dict[str, dict], name: str) -> list[str]:
    return [e["branch"] for e in branches_of(plans, name)]


def entry_of(plans: dict[str, dict], name: str, branch: str) -> dict:
    found = [e for e in branches_of(plans, name) if e["branch"] == branch]
    assert len(found) == 1, f"ждали одну запись {branch!r} у плана {name!r}, есть: {branches_of(plans, name)}"
    return found[0]


def numbers(entry: dict) -> dict:
    return {"done": entry["done"], "total": entry["total"]}


def norm(text: str) -> str:
    return " ".join(text.split())


class Page(HTMLParser):
    """Разбор страницы: чипы в `<summary>` каждого `<details class="plan">` в порядке документа."""

    def __init__(self, raw: str) -> None:
        super().__init__(convert_charrefs=True)
        self.raw = raw
        self.plans: dict[str, list[dict]] = {}
        self._plan: str | None = None
        self._in_summary = False
        self._chip: dict | None = None
        self.feed(raw)
        self.close()

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = (a.get("class") or "").split()
        if tag == "details" and "plan" in cls:
            self._plan = a.get("data-plan") or ""
            self.plans[self._plan] = []
        elif tag == "summary" and self._plan is not None:
            self._in_summary = True
        elif tag == "span" and self._in_summary and "chip" in cls and self._plan is not None:
            self._chip = {"attrs": a, "text": ""}
            self.plans[self._plan].append(self._chip)

    def handle_data(self, data):
        if self._chip is not None:
            self._chip["text"] += data

    def handle_endtag(self, tag):
        if tag == "span" and self._chip is not None:
            self._chip = None
        elif tag == "summary":
            self._in_summary = False

    def chips(self, plan: str, kind: str | None = None) -> list[dict]:
        assert plan in self.plans, f"плана {plan!r} нет на странице; есть: {sorted(self.plans)}"
        got = self.plans[plan]
        if kind is not None:
            got = [c for c in got if c["attrs"].get("data-chip") == kind]
        return got

    def kinds(self, plan: str) -> list[str]:
        return [c["attrs"].get("data-chip") or "" for c in self.chips(plan)]


def render(root: Path, where: Path, *flags: str, env: dict[str, str] | None = None) -> Page:
    out = where / "page.html"
    cp = run_cli(root, "--now", NOW, *flags, "--html", str(out), env=env)
    assert cp.returncode == 0, f"--html: {_out(cp)}"
    assert out.is_file(), f"страница не записана: {_out(cp)}"
    return Page(out.read_text(encoding="utf-8"))


def ctrl_files() -> dict[str, str]:
    """План CTRL: его правит ветка `feat/ctrl` — запись обязана быть (контроль «ветки считаются»)."""
    return {"plans/CTRL/plan.md": three("DONE")}


def add_ctrl(fx: Fx) -> None:
    fx.edit_on("feat/ctrl", {"plans/CTRL/plan.md": three("DONE", "DONE")})


def assert_ctrl(plans: dict[str, dict]) -> None:
    assert names_of(plans, "CTRL") == ["feat/ctrl"], f"контроль не сработал: {branches_of(plans, 'CTRL')}"


# =========================================================================== строка 1: числа ветки


def test_a01_branch_closing_two_more_tasks_gives_entry_3_of_3_and_disk_stays_1(tmp_path):
    fx = Fx(tmp_path, {"plans/P/plan.md": three("DONE")})
    fx.edit_on("feat/x", {"plans/P/plan.md": three("DONE", "DONE", "DONE")})
    plans = get_plans(fx.root)
    assert branches_of(plans, "P") == [{"branch": "feat/x", "done": 3, "total": 3}]
    assert plans["P"]["done"] == 1 and plans["P"]["total"] == 3, "диск (main) не меняется от ветки"


def test_a01_entry_keys_are_branch_done_total_in_that_order(tmp_path):
    fx = Fx(tmp_path, {"plans/P/plan.md": three("DONE")})
    fx.edit_on("feat/x", {"plans/P/plan.md": three("DONE", "DONE")})
    entry = branches_of(get_plans(fx.root), "P")[0]
    assert list(entry) == ENTRY_KEYS, list(entry)


def test_a01_branches_is_the_last_plan_key_right_after_active(tmp_path):
    fx = Fx(tmp_path, {"plans/P/plan.md": three("DONE")})
    fx.edit_on("feat/x", {"plans/P/plan.md": three("DONE", "DONE")})
    plans = get_plans(fx.root)
    assert list(plans["P"])[-2:] == PLAN_KEYS_TAIL, list(plans["P"])


def test_a01_plan_untouched_by_any_branch_has_empty_list_while_touched_plan_has_entry(tmp_path):
    fx = Fx(tmp_path, {"plans/P/plan.md": three("DONE"), "plans/R/plan.md": three()})
    fx.edit_on("feat/x", {"plans/P/plan.md": three("DONE", "DONE")})
    plans = get_plans(fx.root)
    assert names_of(plans, "P") == ["feat/x"]
    assert branches_of(plans, "R") == []


def test_a01_entries_are_sorted_by_branch_name(tmp_path):
    fx = Fx(tmp_path, {"plans/P/plan.md": three("DONE")})
    fx.edit_on("feat/b", {"plans/P/plan.md": three("DONE", "DONE")})
    fx.edit_on("feat/a", {"plans/P/plan.md": three("DONE", "DONE", "DONE")})
    fx.edit_on("feat/c", {"plans/P/plan.md": three("DONE", "PENDING", "DONE")})
    assert names_of(get_plans(fx.root), "P") == ["feat/a", "feat/b", "feat/c"]


# =========================================================================== строка 2: какие ветки попадают


def test_a02_branch_without_commits_above_main_is_absent(tmp_path):
    fx = Fx(tmp_path, {**ctrl_files(), "plans/P/plan.md": three("DONE")})
    add_ctrl(fx)
    fx.git("branch", "feat/empty", "main")  # указывает на тот же коммит, что main: сверх main нет ничего
    plans = get_plans(fx.root)
    assert_ctrl(plans)
    assert names_of(plans, "P") == []


def test_a02_branch_not_touching_plans_is_absent(tmp_path):
    fx = Fx(tmp_path, {**ctrl_files(), "plans/P/plan.md": three("DONE")})
    add_ctrl(fx)
    fx.edit_on("feat/code", {"src/code.py": "x = 1\n"})
    plans = get_plans(fx.root)
    assert_ctrl(plans)
    assert names_of(plans, "P") == []
    assert names_of(plans, "CTRL") == ["feat/ctrl"], "ветка без правок plans/ не попадает ни в один план"


# =========================================================================== строка 3: окно свежести вершины


def _window_fx(tmp_path: Path, ago: timedelta, **kw) -> Fx:
    fx = Fx(tmp_path, {**ctrl_files(), "plans/P/plan.md": three("DONE")})
    add_ctrl(fx)
    fx.edit_on("feat/x", {"plans/P/plan.md": three("DONE", "DONE")}, ago=ago, **kw)
    return fx


def test_a03_tip_two_days_old_is_listed_by_default(tmp_path):
    fx = _window_fx(tmp_path, timedelta(days=2))
    plans = get_plans(fx.root)
    assert_ctrl(plans)
    assert names_of(plans, "P") == ["feat/x"]


def test_a03_tip_four_days_old_is_absent_by_default(tmp_path):
    fx = _window_fx(tmp_path, timedelta(days=4))
    plans = get_plans(fx.root)
    assert_ctrl(plans)
    assert names_of(plans, "P") == []


def test_a03_branch_window_5d_lists_the_four_day_old_tip(tmp_path):
    fx = _window_fx(tmp_path, timedelta(days=4))
    assert names_of(get_plans(fx.root, "--branch-window", "5d"), "P") == ["feat/x"]


def test_a03_window_edge_exactly_3d_is_listed(tmp_path):
    fx = _window_fx(tmp_path, timedelta(days=3))
    plans = get_plans(fx.root)
    assert_ctrl(plans)
    assert names_of(plans, "P") == ["feat/x"]


def test_a03_window_edge_3d_plus_one_second_is_absent(tmp_path):
    fx = _window_fx(tmp_path, timedelta(days=3, seconds=1))
    plans = get_plans(fx.root)
    assert_ctrl(plans)
    assert names_of(plans, "P") == []


def test_a03_tip_from_the_future_is_fresh(tmp_path):
    fx = _window_fx(tmp_path, -timedelta(days=2))
    plans = get_plans(fx.root)
    assert_ctrl(plans)
    assert names_of(plans, "P") == ["feat/x"]


def test_a03_hours_unit_5h_tip_listed_and_7h_tip_absent_with_6h_window(tmp_path):
    fx = Fx(tmp_path, {"plans/P/plan.md": three("DONE"), "plans/Q/plan.md": three("DONE")})
    fx.edit_on("feat/h5", {"plans/P/plan.md": three("DONE", "DONE")}, ago=timedelta(hours=5))
    fx.edit_on("feat/h7", {"plans/Q/plan.md": three("DONE", "DONE")}, ago=timedelta(hours=7))
    plans = get_plans(fx.root, "--branch-window", "6h")
    assert names_of(plans, "P") == ["feat/h5"]
    assert names_of(plans, "Q") == []


def test_a03_committer_date_decides_not_author_date(tmp_path):
    fx = Fx(tmp_path, {"plans/P/plan.md": three("DONE"), "plans/Q/plan.md": three("DONE")})
    # P: свежий коммит-коммиттер, древний автор -> свежая; Q: наоборот -> нет
    fx.edit_on("feat/p", {"plans/P/plan.md": three("DONE", "DONE")}, ago=D1, author_ago=timedelta(days=30))
    fx.edit_on("feat/q", {"plans/Q/plan.md": three("DONE", "DONE")}, ago=timedelta(days=30), author_ago=D1)
    plans = get_plans(fx.root)
    assert names_of(plans, "P") == ["feat/p"]
    assert names_of(plans, "Q") == []


def test_a03_tip_date_decides_not_the_first_commit_of_the_branch(tmp_path):
    fx = Fx(tmp_path, {"plans/P/plan.md": three("DONE"), "plans/Q/plan.md": three("DONE")})
    fx.branch("feat/old-first")
    fx.write("plans/P/plan.md", three("DONE", "DONE"))
    fx.commit("first", ago=timedelta(days=10))
    fx.write("NOTES.txt", "tip")
    fx.commit("tip", ago=D1)
    fx.checkout("main")
    fx.branch("feat/old-tip")
    fx.write("plans/Q/plan.md", three("DONE", "DONE"))
    fx.commit("first", ago=D1)
    fx.write("NOTES.txt", "tip2")
    fx.commit("tip", ago=timedelta(days=10))
    fx.checkout("main")
    plans = get_plans(fx.root)
    assert names_of(plans, "P") == ["feat/old-first"]
    assert names_of(plans, "Q") == []


# =========================================================================== строка 4: стек веток


def test_a04_child_without_own_plan_edit_is_absent_and_parent_is_listed(tmp_path):
    fx = Fx(tmp_path, {"plans/P/plan.md": three("DONE")})
    fx.edit_on("feat/x", {"plans/P/plan.md": three("DONE", "DONE")})
    fx.edit_on("feat/x2", {"NOTES.txt": "child"}, frm="feat/x")
    assert names_of(get_plans(fx.root), "P") == ["feat/x"]


def test_a04_child_with_own_plan_edit_is_listed_with_numbers_including_parent_edits(tmp_path):
    fx = Fx(tmp_path, {"plans/P/plan.md": three("DONE")})
    fx.edit_on("feat/x", {"plans/P/plan.md": three("DONE", "DONE")})
    fx.edit_on("feat/x2", {"plans/P/plan.md": three("DONE", "DONE", "DONE")}, frm="feat/x")
    plans = get_plans(fx.root)
    assert branches_of(plans, "P") == [
        {"branch": "feat/x", "done": 2, "total": 3},
        {"branch": "feat/x2", "done": 3, "total": 3},
    ]


def test_a04_child_touching_another_plan_is_listed_only_there_parent_only_in_its_plan(tmp_path):
    """DESIGN «Стек»: тронутые планы — diff от вершины родителя, а не от merge-base с main."""
    fx = Fx(tmp_path, {"plans/P/plan.md": three("DONE"), "plans/Q/plan.md": three("DONE")})
    fx.edit_on("feat/x", {"plans/P/plan.md": three("DONE", "DONE")})
    fx.edit_on("feat/x2", {"plans/Q/plan.md": three("DONE", "DONE")}, frm="feat/x")
    plans = get_plans(fx.root)
    assert names_of(plans, "P") == ["feat/x"]
    assert names_of(plans, "Q") == ["feat/x2"]


def test_a04_parent_is_the_candidate_with_the_largest_main_diff(tmp_path):
    """x -> x2 -> x3, на x3 нет правок планов: родитель x2 (больше main..A), поэтому x3 не в списке.
    Родитель x (меньше) дал бы diff x..x3 с правкой x2 и записью у x3."""
    fx = Fx(tmp_path, {"plans/P/plan.md": three("DONE")})
    fx.edit_on("feat/x", {"plans/P/plan.md": three("DONE", "DONE")})
    fx.edit_on("feat/x2", {"plans/P/plan.md": three("DONE", "DONE", "DONE")}, frm="feat/x")
    fx.edit_on("feat/x3", {"NOTES.txt": "grandchild"}, frm="feat/x2")
    assert names_of(get_plans(fx.root), "P") == ["feat/x", "feat/x2"]


def test_a04_two_branches_at_the_same_tip_only_the_smaller_name_is_listed(tmp_path):
    fx = Fx(tmp_path, {"plans/P/plan.md": three("DONE")})
    fx.edit_on("feat/b", {"plans/P/plan.md": three("DONE", "DONE")})
    fx.git("branch", "feat/a", "feat/b")
    assert names_of(get_plans(fx.root), "P") == ["feat/a"]


def test_a04_stale_parent_is_not_a_candidate_child_diffs_from_merge_base(tmp_path):
    """Родитель вне окна — не кандидат: у фреш-потомка diff от main и своя запись включает правку родителя."""
    fx = Fx(tmp_path, {"plans/P/plan.md": three("DONE")})
    fx.edit_on("feat/old", {"plans/P/plan.md": three("DONE", "DONE")}, ago=timedelta(days=10))
    fx.edit_on("feat/new", {"NOTES.txt": "child of stale"}, frm="feat/old")
    plans = get_plans(fx.root)
    assert branches_of(plans, "P") == [{"branch": "feat/new", "done": 2, "total": 3}]


def test_a08_root_branch_is_a_candidate_parent_so_its_unedited_child_is_absent(tmp_path):
    """Корень взят на feat/x: x в списке нет, но потомок y без своих правок плана тоже не попадает."""
    fx = Fx(tmp_path, {"plans/P/plan.md": three("DONE")})
    fx.edit_on("feat/x", {"plans/P/plan.md": three("DONE", "DONE")})
    fx.edit_on("feat/y", {"NOTES.txt": "child of root branch"}, frm="feat/x")
    fx.checkout("feat/x")
    plans = get_plans(fx.root)
    assert plans["P"]["done"] == 2, "диск корня — состояние feat/x"
    assert names_of(plans, "P") == []


# =========================================================================== строка 5: ветка от старого main


def _old_main_fx(tmp_path: Path) -> Fx:
    fx = Fx(tmp_path, {"plans/P/plan.md": three("DONE")})
    fx.edit_on("feat/x", {"plans/P/notes.md": "заметка вне счёта\n"})  # ответвлена от старого main
    fx.on_main({"plans/P/plan.md": three("DONE", "DONE")})  # затем main закрыл 1.2
    return fx


def test_a05_branch_off_old_main_touching_an_uncounted_file_gets_disk_numbers(tmp_path):
    fx = _old_main_fx(tmp_path)
    plans = get_plans(fx.root)
    assert plans["P"]["done"] == 2 and plans["P"]["total"] == 3, "диск: main закрыл 1.2"
    assert branches_of(plans, "P") == [{"branch": "feat/x", "done": 2, "total": 3}]


def test_a05_same_numbers_as_disk_give_no_chip_on_the_page(tmp_path):
    fx = Fx(tmp_path, {**ctrl_files(), "plans/P/plan.md": three("DONE")})
    add_ctrl(fx)
    fx.edit_on("feat/x", {"plans/P/notes.md": "заметка вне счёта\n"})
    fx.on_main({"plans/P/plan.md": three("DONE", "DONE")})
    page = render(fx.root, tmp_path)
    assert [norm(c["text"]) for c in page.chips("CTRL", "branch")] == ["в ветке feat/ctrl: 2 из 3, в main: 1"], (
        "контроль: чип у CTRL есть"
    )
    assert page.chips("P", "branch") == [], page.chips("P")


# =========================================================================== строка 6: layout v2


def test_a06_layout_v2_branch_marks_task_done_gives_1_of_2(tmp_path):
    fx = Fx(
        tmp_path,
        {
            "plans/V/plan.md": head_md(),
            "plans/V/tasks/1.1.md": task_file("1.1", "PENDING"),
            "plans/V/tasks/1.2.md": task_file("1.2", "PENDING"),
        },
    )
    fx.edit_on("feat/v", {"plans/V/tasks/1.2.md": task_file("1.2", "DONE")})
    plans = get_plans(fx.root)
    assert plans["V"]["done"] == 0 and plans["V"]["total"] == 2, "диск: main 0 из 2"
    assert branches_of(plans, "V") == [{"branch": "feat/v", "done": 1, "total": 2}]


# =========================================================================== строка 7: какие планы и пути


def test_a07_one_branch_touching_two_plans_has_an_entry_in_both(tmp_path):
    fx = Fx(tmp_path, {"plans/P/plan.md": three("DONE"), "plans/Q/plan.md": three()})
    fx.edit_on("feat/x", {"plans/P/plan.md": three("DONE", "DONE"), "plans/Q/plan.md": three("DONE")})
    plans = get_plans(fx.root)
    assert branches_of(plans, "P") == [{"branch": "feat/x", "done": 2, "total": 3}]
    assert branches_of(plans, "Q") == [{"branch": "feat/x", "done": 1, "total": 3}]


def test_a07_single_file_plan_is_counted(tmp_path):
    fx = Fx(tmp_path, {"plans/S.md": three("DONE")})
    fx.edit_on("feat/s", {"plans/S.md": three("DONE", "DONE", "DONE")})
    plans = get_plans(fx.root)
    assert plans["S"]["done"] == 1
    assert branches_of(plans, "S") == [{"branch": "feat/s", "done": 3, "total": 3}]


def test_a07_archived_plan_is_counted(tmp_path):
    fx = Fx(tmp_path, {"plans/_archive/2026-Q3/Z/plan.md": three("DONE")})
    fx.edit_on("feat/z", {"plans/_archive/2026-Q3/Z/plan.md": three("DONE", "DONE")})
    plans = get_plans(fx.root)
    assert plans["Z"]["archived"] is True
    assert branches_of(plans, "Z") == [{"branch": "feat/z", "done": 2, "total": 3}]


def test_a07_plan_deleted_in_the_branch_has_no_entry_while_the_other_plan_has(tmp_path):
    fx = Fx(tmp_path, {"plans/D/plan.md": three("DONE"), "plans/P/plan.md": three("DONE")})
    fx.edit_on("feat/x", {"plans/D/plan.md": None, "plans/P/plan.md": three("DONE", "DONE")})
    plans = get_plans(fx.root)
    assert names_of(plans, "P") == ["feat/x"]
    assert branches_of(plans, "D") == []


def test_a07_plan_moved_away_in_the_branch_has_no_entry(tmp_path):
    """DESIGN «Выгрузка»: плана нет на вершине (удалён, перенесён) — записи нет. Диск корня: план на месте."""
    fx = Fx(tmp_path, {"plans/M/plan.md": three("DONE"), "plans/P/plan.md": three("DONE")})
    fx.branch("feat/x")
    fx.git("mv", "plans/M", "plans/N")
    fx.write("plans/P/plan.md", three("DONE", "DONE"))
    fx.commit("move M to N, edit P")
    fx.checkout("main")
    plans = get_plans(fx.root)
    assert names_of(plans, "P") == ["feat/x"]
    assert branches_of(plans, "M") == []


def test_a07_sibling_plan_dir_with_a_common_name_prefix_is_not_touched(tmp_path):
    """Путь `plans/P2/...` не относится к плану `P` (префикс без разделителя)."""
    fx = Fx(tmp_path, {"plans/P/plan.md": three("DONE"), "plans/P2/plan.md": three("DONE")})
    fx.edit_on("feat/x", {"plans/P2/plan.md": three("DONE", "DONE")})
    plans = get_plans(fx.root)
    assert names_of(plans, "P2") == ["feat/x"]
    assert branches_of(plans, "P") == []


# =========================================================================== строка 8: ветка корня


def test_a08_root_checked_out_on_the_branch_hides_that_branch_but_not_others(tmp_path):
    fx = Fx(tmp_path, {"plans/P/plan.md": three("DONE")})
    fx.edit_on("feat/x", {"plans/P/plan.md": three("DONE", "DONE", "DONE")})
    fx.edit_on("feat/y", {"plans/P/plan.md": three("DONE", "DONE")})
    fx.checkout("feat/x")
    plans = get_plans(fx.root)
    assert plans["P"]["done"] == 3, "диск корня — состояние feat/x"
    assert names_of(plans, "P") == ["feat/y"]


# =========================================================================== строка 9: нет git, подкаталог, нет main, окно


def test_a09_directory_without_git_gives_empty_branches_and_exit_0(tmp_path):
    root = tmp_path / "nogit"
    (root / "plans" / "P").mkdir(parents=True)
    (root / "plans" / "P" / "plan.md").write_bytes(three("DONE").encode("utf-8"))
    env = {"GIT_CEILING_DIRECTORIES": str(root.parent)}
    probe = subprocess.run(
        ["git", "rev-parse", "--git-dir"], cwd=str(root), capture_output=True, env=_env(env), timeout=CALL_TIMEOUT
    )
    assert probe.returncode != 0, "предусловие: каталог вне любого git"
    cp = run_cli(root, "--json", "--now", NOW, env=env)
    assert cp.returncode == 0, _out(cp)
    plans = {r["plan"]: r for r in json.loads(cp.stdout)}
    assert plans["P"]["done"] == 1
    assert branches_of(plans, "P") == []


def test_a09_root_in_a_repository_subdirectory_gives_empty_branches(tmp_path):
    fx = Fx(tmp_path, {"plans/P/plan.md": three("DONE"), "sub/plans/P/plan.md": three("DONE")})
    fx.edit_on("feat/x", {"plans/P/plan.md": three("DONE", "DONE"), "sub/plans/P/plan.md": three("DONE", "DONE")})
    assert names_of(get_plans(fx.root), "P") == ["feat/x"], "контроль: от верхнего каталога репозитория запись есть"
    plans = get_plans(fx.root / "sub")
    assert plans["P"]["done"] == 1
    assert branches_of(plans, "P") == []


def test_a09_repository_without_main_branch_gives_empty_branches_until_main_exists(tmp_path):
    fx = Fx(tmp_path, {"plans/P/plan.md": three("DONE")}, main="trunk")
    fx.branch("feat/x", "trunk")
    fx.write("plans/P/plan.md", three("DONE", "DONE"))
    fx.commit("edit")
    fx.checkout("trunk")
    plans = get_plans(fx.root)
    assert plans["P"]["done"] == 1
    assert branches_of(plans, "P") == []
    fx.git("branch", "-m", "trunk", "main")
    assert names_of(get_plans(fx.root), "P") == ["feat/x"], "контроль: с веткой main запись появляется"


def _modes(tmp_path: Path) -> dict[str, list[str]]:
    return {
        "text": [],
        "json": ["--json"],
        "who": ["--who"],
        "html": ["--html", str(tmp_path / "out.html")],
        "check": ["--check"],
    }


@pytest.mark.parametrize("mode", ["text", "json", "who", "html", "check"])
def test_a09_invalid_branch_window_exits_2_in_every_mode_and_valid_value_does_not(tmp_path, mode):
    fx = Fx(tmp_path, {"plans/P/plan.md": three("DONE")})
    fx.edit_on("feat/x", {"plans/P/plan.md": three("DONE", "DONE")})
    flags = _modes(tmp_path)[mode]
    ref = run_cli(fx.root, "--now", NOW, *flags)
    assert ref.returncode != 2, f"предусловие: режим без флага не даёт 2: {_out(ref)}"
    ok = run_cli(fx.root, "--now", NOW, *flags, "--branch-window", "3d")
    assert ok.returncode == ref.returncode, f"допустимое значение не должно менять код: {_out(ok)}"
    for bad in ("banana", "3x", ""):
        cp = run_cli(fx.root, "--now", NOW, *flags, "--branch-window", bad)
        assert cp.returncode == 2, f"--branch-window {bad!r}: {_out(cp)}"
        assert cp.stderr.strip(), "ошибка 2 без сообщения в stderr"


def test_a09_invalid_branch_window_message_does_not_echo_the_value(tmp_path):
    fx = Fx(tmp_path, {"plans/P/plan.md": three("DONE")})
    ok = run_cli(fx.root, "--json", "--now", NOW, "--branch-window", "3d")
    assert ok.returncode == 0, _out(ok)
    cp = run_cli(fx.root, "--json", "--now", NOW, "--branch-window", "zz-secret-zz")
    assert cp.returncode == 2, _out(cp)
    assert cp.stderr.strip(), "сообщение об ошибке обязано быть"
    assert "zz-secret-zz" not in cp.stderr, cp.stderr


# =========================================================================== строка 10: страница


def _x_fx(tmp_path: Path, closed: tuple[str, ...] = ("DONE", "DONE", "DONE")) -> Fx:
    fx = Fx(tmp_path, {"plans/P/plan.md": three("DONE")})
    fx.edit_on("feat/x", {"plans/P/plan.md": three(*closed)})
    return fx


def test_a10_chip_text_and_attributes_are_literal(tmp_path):
    fx = _x_fx(tmp_path)
    chips = render(fx.root, tmp_path).chips("P", "branch")
    assert len(chips) == 1, chips
    c = chips[0]
    assert c["attrs"].get("data-branch") == "feat/x"
    assert "chip" in (c["attrs"].get("class") or "").split()
    assert norm(c["text"]) == "в ветке feat/x: 3 из 3, в main: 1"


def test_a10_chip_appears_when_only_done_differs_from_disk(tmp_path):
    fx = _x_fx(tmp_path, ("DONE", "DONE", "PENDING"))
    chips = render(fx.root, tmp_path).chips("P", "branch")
    assert [norm(c["text"]) for c in chips] == ["в ветке feat/x: 2 из 3, в main: 1"]


def test_a10_chip_appears_when_only_total_differs_from_disk(tmp_path):
    fx = Fx(tmp_path, {"plans/P/plan.md": three("DONE")})
    fx.edit_on(
        "feat/x",
        {"plans/P/plan.md": items_md([("1.1", "DONE"), ("1.2", "PENDING"), ("1.3", "PENDING"), ("1.4", "PENDING")])},
    )
    chips = render(fx.root, tmp_path).chips("P", "branch")
    assert [norm(c["text"]) for c in chips] == ["в ветке feat/x: 1 из 4, в main: 1"]


def test_a10_no_chip_when_branch_numbers_equal_the_disk_but_json_entry_exists(tmp_path):
    fx = Fx(tmp_path, {**ctrl_files(), "plans/P/plan.md": three("DONE")})
    add_ctrl(fx)
    fx.edit_on("feat/x", {"plans/P/notes.md": "вне счёта\n"})
    page = render(fx.root, tmp_path)
    assert [norm(c["text"]) for c in page.chips("CTRL", "branch")] == ["в ветке feat/ctrl: 2 из 3, в main: 1"], (
        "контроль: чип у CTRL есть"
    )
    assert page.chips("P", "branch") == []
    assert branches_of(get_plans(fx.root), "P") == [{"branch": "feat/x", "done": 1, "total": 3}], (
        "запись в JSON остаётся при тех же числах"
    )


def test_a10_several_branch_chips_are_ordered_by_branch_name(tmp_path):
    fx = Fx(tmp_path, {"plans/P/plan.md": three("DONE")})
    fx.edit_on("feat/b", {"plans/P/plan.md": three("DONE", "DONE")})
    fx.edit_on("feat/a", {"plans/P/plan.md": three("DONE", "DONE", "DONE")})
    chips = render(fx.root, tmp_path).chips("P", "branch")
    assert [c["attrs"].get("data-branch") for c in chips] == ["feat/a", "feat/b"]


def test_a10_branch_chip_stands_after_the_closed_chip_and_before_the_active_chip(tmp_path):
    header = ("**Статус:** DONE", "- **Ветка:** feat/x")
    fx = Fx(tmp_path, {"plans/P/plan.md": items_md([("1.1", "DONE"), ("1.2", "PENDING")], header)})
    wt = fx.base / "wt_x"
    fx.git("worktree", "add", "-q", "-b", "feat/x", str(wt), "main")
    fx.write("plans/P/plan.md", items_md([("1.1", "DONE"), ("1.2", "DONE")], header), cwd=wt)
    fx.commit("close 1.2", cwd=wt)
    journal = {
        "ts": "2026-10-03T11:55:00", "event": "SubagentStart", "agent_type": "developer", "agent_id": "a1",
        "session_id": "s1", "source": "hook", "cwd": "x", "branch": "x", "tail": "",
    }  # fmt: skip
    (wt / "data").mkdir()
    (wt / "data" / "agent-journal.jsonl").write_bytes((json.dumps(journal) + "\n").encode("utf-8"))
    kinds = render(fx.root, tmp_path).kinds("P")
    assert "closed" in kinds and "active" in kinds, f"предусловие фикстуры: {kinds}"
    assert "branch" in kinds, f"нет чипа ветки: {kinds}"
    assert kinds.index("closed") < kinds.index("branch") < kinds.index("active"), kinds


def test_a10_archived_plan_gets_the_chip_too(tmp_path):
    fx = Fx(tmp_path, {"plans/_archive/2026-Q3/Z/plan.md": three("DONE")})
    fx.edit_on("feat/z", {"plans/_archive/2026-Q3/Z/plan.md": three("DONE", "DONE")})
    chips = render(fx.root, tmp_path).chips("Z", "branch")
    assert [norm(c["text"]) for c in chips] == ["в ветке feat/z: 2 из 3, в main: 1"]


def test_a10_closed_plan_gets_the_chip_too(tmp_path):
    header = ("**Статус:** DONE",)
    fx = Fx(tmp_path, {"plans/C/plan.md": items_md([("1.1", "DONE"), ("1.2", "PENDING")], header)})
    fx.edit_on("feat/c", {"plans/C/plan.md": items_md([("1.1", "DONE"), ("1.2", "DONE")], header)})
    page = render(fx.root, tmp_path)
    assert "closed" in page.kinds("C"), f"предусловие: чип закрытого плана: {page.kinds('C')}"
    assert [norm(c["text"]) for c in page.chips("C", "branch")] == ["в ветке feat/c: 2 из 2, в main: 1"]


def test_a10_chip_values_are_html_escaped(tmp_path):
    fx = Fx(tmp_path, {"plans/P/plan.md": three("DONE")})
    fx.edit_on("feat/a&b'c", {"plans/P/plan.md": three("DONE", "DONE")})
    cp = run_cli(fx.root, "--json", "--now", NOW)
    assert cp.returncode == 0, _out(cp)
    page = render(fx.root, tmp_path)
    chips = page.chips("P", "branch")
    assert len(chips) == 1, chips
    assert chips[0]["attrs"].get("data-branch") == "feat/a&b'c"
    assert norm(chips[0]["text"]) == "в ветке feat/a&b'c: 2 из 3, в main: 1"
    assert "feat/a&b" not in page.raw, "сырой & в странице: значение не прошло через экранирование"


# =========================================================================== строка 11: репозиторий не меняется


def _snapshot(fx: Fx) -> dict:
    tree = sorted(
        str(p.relative_to(fx.root))
        for p in fx.root.rglob("*")
        if ".git" not in p.relative_to(fx.root).parts and p.is_file()
    )
    return {
        "refs": fx.git("for-each-ref", "--format=%(refname) %(objectname)"),
        "head": fx.git("symbolic-ref", "HEAD"),
        "status": fx.git("status", "--porcelain", "--untracked-files=all", "--ignored"),
        "stash": fx.git("stash", "list"),
        "worktrees": fx.git("worktree", "list", "--porcelain"),
        "tree": tree,
    }


def test_a11_run_leaves_branch_tips_status_and_files_unchanged(tmp_path):
    fx = Fx(
        tmp_path,
        {
            "plans/P/plan.md": three("DONE"),
            "plans/V/plan.md": head_md(),
            "plans/V/tasks/1.1.md": task_file("1.1", "PENDING"),
        },
    )
    fx.edit_on("feat/x", {"plans/P/plan.md": three("DONE", "DONE")})
    fx.edit_on("feat/v", {"plans/V/tasks/1.1.md": task_file("1.1", "DONE")})
    before = _snapshot(fx)
    plans = get_plans(fx.root)
    assert names_of(plans, "P") == ["feat/x"] and names_of(plans, "V") == ["feat/v"], "контроль: ветки посчитаны"
    page_out = tmp_path / "page.html"
    cp = run_cli(fx.root, "--now", NOW, "--html", str(page_out))
    assert cp.returncode == 0, _out(cp)
    assert _snapshot(fx) == before


# =========================================================================== строка 12: слияние по задачам


def test_a12_base_pending_main_done_branch_in_progress_counts_the_task_done(tmp_path):
    fx = Fx(tmp_path, {"plans/P/plan.md": items_md([("1.1", "PENDING"), ("1.2", "PENDING")])})
    fx.edit_on("feat/x", {"plans/P/plan.md": items_md([("1.1", "IN PROGRESS"), ("1.2", "PENDING")])})
    fx.on_main({"plans/P/plan.md": items_md([("1.1", "DONE"), ("1.2", "PENDING")])})
    plans = get_plans(fx.root)
    assert plans["P"]["done"] == 1, "диск: main закрыл 1.1"
    assert branches_of(plans, "P") == [{"branch": "feat/x", "done": 1, "total": 2}]


def test_a12_branch_deleted_a_task_that_main_did_not_touch_total_is_one_less(tmp_path):
    fx = Fx(tmp_path, {"plans/P/plan.md": three("DONE")})
    fx.edit_on("feat/x", {"plans/P/plan.md": items_md([("1.1", "DONE"), ("1.2", "PENDING")])})
    plans = get_plans(fx.root)
    assert plans["P"]["total"] == 3, "диск: три задачи"
    assert branches_of(plans, "P") == [{"branch": "feat/x", "done": 1, "total": 2}]


def test_a12_branch_renamed_1_2_to_1_2a_total_stays(tmp_path):
    fx = Fx(tmp_path, {"plans/P/plan.md": three("DONE")})
    fx.edit_on("feat/x", {"plans/P/plan.md": items_md([("1.1", "DONE"), ("1.2a", "PENDING"), ("1.3", "PENDING")])})
    plans = get_plans(fx.root)
    assert plans["P"]["total"] == 3
    assert branches_of(plans, "P") == [{"branch": "feat/x", "done": 1, "total": 3}]


def test_a12_main_superseded_branch_done_counts_done_and_adds_to_total(tmp_path):
    """DESIGN: «угол» — main поставил SUPERSEDED, ветка DONE -> засчитано сделанным, total +1."""
    fx = Fx(tmp_path, {"plans/P/plan.md": items_md([("1.1", "PENDING"), ("1.2", "PENDING")])})
    fx.edit_on("feat/x", {"plans/P/plan.md": items_md([("1.1", "DONE"), ("1.2", "PENDING")])})
    fx.on_main({"plans/P/plan.md": items_md([("1.1", "SUPERSEDED"), ("1.2", "PENDING")])})
    plans = get_plans(fx.root)
    assert plans["P"]["done"] == 0 and plans["P"]["total"] == 1, "диск: 1.1 снята и вне total"
    assert branches_of(plans, "P") == [{"branch": "feat/x", "done": 1, "total": 2}]


def test_a12_both_changed_and_none_is_done_takes_the_disk_status(tmp_path):
    """DESIGN шаг 2: изменили обе и DONE нет нигде -> статус диска (SUPERSEDED вне total)."""
    fx = Fx(tmp_path, {"plans/P/plan.md": items_md([("1.1", "PENDING"), ("1.2", "PENDING")])})
    fx.edit_on("feat/x", {"plans/P/plan.md": items_md([("1.1", "IN PROGRESS"), ("1.2", "PENDING")])})
    fx.on_main({"plans/P/plan.md": items_md([("1.1", "SUPERSEDED"), ("1.2", "PENDING")])})
    assert branches_of(get_plans(fx.root), "P") == [{"branch": "feat/x", "done": 0, "total": 1}]


def test_a12_task_absent_on_disk_stays_gone_when_the_branch_did_not_touch_it(tmp_path):
    """DESIGN шаг 2: отсутствие задачи — тоже статус. Задачу удалил main, ветка её не трогала."""
    fx = Fx(tmp_path, {"plans/P/plan.md": three("DONE")})
    fx.edit_on("feat/x", {"plans/P/plan.md": three("DONE", "DONE")})
    fx.on_main({"plans/P/plan.md": items_md([("1.1", "DONE"), ("1.2", "PENDING")])})
    plans = get_plans(fx.root)
    assert plans["P"]["total"] == 2, "диск: 1.3 удалена в main"
    assert branches_of(plans, "P") == [{"branch": "feat/x", "done": 2, "total": 2}]


def test_a12_task_added_by_the_branch_joins_while_main_progress_is_kept(tmp_path):
    """DESIGN шаг 3: задача вершины, которой нет ни в базе, ни на диске, добавляется."""
    fx = Fx(tmp_path, {"plans/P/plan.md": items_md([("1.1", "PENDING"), ("1.2", "PENDING")])})
    fx.edit_on("feat/x", {"plans/P/plan.md": items_md([("1.1", "PENDING"), ("1.2", "PENDING"), ("1.3", "PENDING")])})
    fx.on_main({"plans/P/plan.md": items_md([("1.1", "DONE"), ("1.2", "PENDING")])})
    assert branches_of(get_plans(fx.root), "P") == [{"branch": "feat/x", "done": 1, "total": 3}]


# =========================================================================== закрепления DESIGN вне 12 строк


def test_d_tag_named_main_does_not_break_the_main_reference(tmp_path):
    """DESIGN «Режимы»: `main` всегда как `refs/heads/main` (тег `main` ломает голое имя).
    Тег стоит на старом коммите, где Q ещё не закрыт: голое имя дало бы merge-base с этим тегом и запись у Q."""
    fx = Fx(tmp_path, {"plans/P/plan.md": three("DONE"), "plans/Q/plan.md": three("DONE")})
    fx.git("tag", "main")  # на коммите init
    fx.on_main({"plans/Q/plan.md": three("DONE", "DONE")})
    fx.edit_on("feat/x", {"plans/P/plan.md": three("DONE", "DONE")})
    plans = get_plans(fx.root)
    assert names_of(plans, "P") == ["feat/x"]
    assert branches_of(plans, "Q") == []


def test_d_crlf_checkout_via_autocrlf_does_not_corrupt_the_plan_export(tmp_path):
    """DESIGN «Выгрузка»: `git archive` с core.autocrlf=true отдаёт CRLF; чтение tar из stdout в текстовом
    режиме теряет файлы. Layout v2 с кириллицей: три файла задач, ветка закрывает вторую."""
    fx = Fx(tmp_path)
    fx.git("config", "core.autocrlf", "true")

    def tf(tid: str, st: str) -> str:
        return f"# Task {tid}: задача номер {tid}\n\n**Статус:** {st}\n\nописание русским текстом\n"

    for tid in ("1.1", "1.2", "1.3"):
        fx.write(f"plans/V/tasks/{tid}.md", tf(tid, "PENDING"))
    fx.write("plans/V/plan.md", head_md())
    fx.commit("v", ago=D20)
    fx.edit_on("feat/v", {"plans/V/tasks/1.2.md": tf("1.2", "DONE"), "plans/V/tasks/1.3.md": tf("1.3", "DONE")})
    plans = get_plans(fx.root)
    assert plans["V"]["done"] == 0 and plans["V"]["total"] == 3
    assert branches_of(plans, "V") == [{"branch": "feat/v", "done": 2, "total": 3}]


# =========================================================================== охрана прежнего поведения (зелёные до 5.5 намеренно)


def test_guard_who_output_keeps_its_two_top_level_keys_and_has_no_branches(tmp_path):
    fx = Fx(tmp_path, {"plans/P/plan.md": three("DONE")})
    fx.edit_on("feat/x", {"plans/P/plan.md": three("DONE", "DONE")})
    cp = run_cli(fx.root, "--who", "--now", NOW)
    assert cp.returncode == 0, _out(cp)
    obj = json.loads(cp.stdout)
    assert list(obj) == ["active", "orphans"]
    assert "branches" not in cp.stdout


def test_guard_text_listing_line_is_unchanged_by_a_branch_with_other_numbers(tmp_path):
    fx = Fx(tmp_path, {"plans/P/plan.md": three("DONE")})
    fx.edit_on("feat/x", {"plans/P/plan.md": three("DONE", "DONE", "DONE")})
    cp = run_cli(fx.root, "--now", NOW)
    assert cp.returncode == 0, _out(cp)
    assert cp.stdout.splitlines() == [f"{'P':48} {'—':6} 1 из 3 · 33%"], cp.stdout
