# ruff: noqa: E501  -- литералы-фикстуры планов и ожидания в одну строку
"""Приёмка Task 3.4 plans_progress (слепой тестер, RED до кода).

Три механизма:
  1. `Status:` в теле задачи наравне с `Статус:` (заголовки `### Task` и `tasks/<id>.md`);
  2. находка `BRANCH_MISSING` (информационная, только `--check`);
  3. `tier` в `--json`/странице: `"4.1"|"4.2"|"4.3"` -> `"queue"|"waiting"|"closed"`.

Тесты ходят только через CLI в subprocess (timeout=60 на вызов); реализацию не импортируют.
Ожидаемые значения — литералы. Приёмка 7 (живое дерево) — проверка лида, здесь её нет.
"""

from __future__ import annotations

import html as html_lib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
PROGRESS = REPO_ROOT / "scripts" / "plans_progress" / "plans_progress.py"
CALL_TIMEOUT = 60

FILLER = ["Описание плана, строка заполнитель."] * 32  # выталкивает тело задач за первые 30 строк шапки


# --------------------------------------------------------------------------- запуск


def _env(**extra: str) -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env.update(extra)
    return env


def _cli(root: Path, *flags: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROGRESS), "--root", str(root), *flags],
        capture_output=True,
        timeout=CALL_TIMEOUT,
        env=env or _env(),
        encoding="utf-8",
        errors="replace",
    )


def _git(cwd: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        timeout=CALL_TIMEOUT,
        env=env or _env(),
        encoding="utf-8",
        errors="replace",
    )


def _git_ok(cwd: Path, *args: str) -> None:
    cp = _git(cwd, *args)
    assert cp.returncode == 0, f"git {' '.join(args)} -> {cp.returncode}: {cp.stderr[:300]!r}"


def _write(root: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(text.encode("utf-8"))
    return root


def _json(root: Path, *extra: str) -> dict[str, dict]:
    cp = _cli(root, "--json", *extra)
    assert cp.returncode == 0, f"--json exit {cp.returncode}\nstderr={cp.stderr[:400]!r}"
    data = json.loads(cp.stdout)
    return {(r["plan"][:-3] if r["plan"].endswith(".md") else r["plan"]): r for r in data}


def _json_list(root: Path) -> list[dict]:
    cp = _cli(root, "--json")
    assert cp.returncode == 0, f"--json exit {cp.returncode}\nstderr={cp.stderr[:400]!r}"
    return json.loads(cp.stdout)


def _order_md(tier41=(), tier42=(), tier43=()) -> str:
    out = ["# Порядок работ и контроль планов", "", "## 4. Контроль планов", ""]
    out += ["### 4.1 Активные — в работе или следующие", ""]
    out += ["| План | Полоса | Статус | Следующий шаг |", "|---|---|---|---|"]
    out += [f"| [{n}](../{n}/plan.md) | С | статус | следующий шаг |" for n in tier41]
    out += ["", "### 4.2 Ждут триггера — не трогать до условия", ""]
    out += ["| План | Остаток | Триггер |", "|---|---|---|"]
    out += [f"| [{n}](../{n}/plan.md) | остаток | триггер |" for n in tier42]
    out += ["", "### 4.3 Закрыты или поглощены — кандидаты в `_archive/`", ""]
    out += ["| План | Факт |", "|---|---|"]
    out += [f"| [{n}](../{n}/plan.md) | DONE |" for n in tier43]
    out += [""]
    return "\n".join(out)


def _list_plan(*, header: tuple[str, ...] = (), tasks: tuple[str, ...] = ("- Task 1.1: делаем [PENDING]",)) -> str:
    return "\n".join(["# План", "", *header, "", "## Порядок выполнения", *tasks, ""])


# ============================================================================ 1-2. Status: / Статус:


def _heading_plan(status_lines: list[str]) -> str:
    """Каталожный план без раздела порядка: `### Task 1.1`, `### Task 1.2`, тело — строка статуса."""
    body = ["# План", "", *FILLER, "", "## Задачи", ""]
    for tid, line in zip(("1.1", "1.2"), status_lines, strict=True):
        body += [f"### Task {tid} — задача {tid}", line, ""]
    return "\n".join(body)


def _v2_files(status_lines: list[str]) -> dict[str, str]:
    """Layout v2: plan.md без раздела порядка и без `### Task`; задачи — tasks/<id>.md."""
    files = {"plans/v2/plan.md": "# План v2\n\nОписание без задач.\n"}
    for tid, line in zip(("1.1", "1.2"), status_lines, strict=True):
        files[f"plans/v2/tasks/{tid}.md"] = f"# Task {tid}: задача {tid}\n\n{line}\n"
    return files


def _counts(rec: dict) -> tuple[int, int, int]:
    return rec["done"], rec["total"], rec["unmarked"]


EN_FORMS = ["- **Status:** {w}", "- **Status**: {w}", "**Status:** {w}"]
RU_FORMS = ["- **Статус:** {w}", "- **Статус**: {w}", "**Статус:** {w}"]


@pytest.mark.parametrize("form", EN_FORMS)
def test_english_status_in_heading_task_body_counts(tmp_path, form):
    """Приёмка 1: `### Task` + `Status: DONE|PENDING` -> done 1 total 2 unmarked 0."""
    root = _write(
        tmp_path / "r", {"plans/en-heading/plan.md": _heading_plan([form.format(w="DONE"), form.format(w="PENDING")])}
    )
    rec = _json(root)["en-heading"]
    assert _counts(rec) == (1, 2, 0), f"форма {form!r}: {rec['done']}/{rec['total']} unmarked={rec['unmarked']}"


def test_english_status_in_heading_task_body_keeps_task_statuses(tmp_path):
    root = _write(
        tmp_path / "r", {"plans/en-heading/plan.md": _heading_plan(["- **Status:** DONE", "- **Status:** PENDING"])}
    )
    rec = _json(root)["en-heading"]
    assert {t["id"]: t["status"] for t in rec["tasks"]} == {"1.1": "done", "1.2": "pending"}


def test_english_status_in_heading_task_body_blocked_word(tmp_path):
    root = _write(
        tmp_path / "r", {"plans/en-heading/plan.md": _heading_plan(["- **Status:** BLOCKED", "- **Status:** DONE"])}
    )
    rec = _json(root)["en-heading"]
    assert {t["id"]: t["status"] for t in rec["tasks"]} == {"1.1": "blocked", "1.2": "done"}
    assert _counts(rec) == (1, 2, 0)


def test_english_status_in_tasks_file_counts_layout_v2(tmp_path):
    """Приёмка 1 (layout v2): tasks/1.1.md `Status: DONE`, tasks/1.2.md `Status: PENDING` -> done 1 total 2 unmarked 0."""
    root = _write(tmp_path / "r", _v2_files(["- **Status:** DONE", "- **Status:** PENDING"]))
    rec = _json(root)["v2"]
    assert _counts(rec) == (1, 2, 0)
    assert {t["id"]: t["status"] for t in rec["tasks"]} == {"1.1": "done", "1.2": "pending"}


@pytest.mark.parametrize("form", RU_FORMS)
def test_russian_status_in_heading_task_body_counts(tmp_path, form):
    """Приёмка 2: те же фикстуры с `Статус:` -> done 1 total 2 unmarked 0 (контроль, зелёный и сегодня)."""
    root = _write(
        tmp_path / "r", {"plans/ru-heading/plan.md": _heading_plan([form.format(w="DONE"), form.format(w="PENDING")])}
    )
    rec = _json(root)["ru-heading"]
    assert _counts(rec) == (1, 2, 0), f"форма {form!r}: {rec['done']}/{rec['total']} unmarked={rec['unmarked']}"


def test_russian_status_in_tasks_file_counts_layout_v2(tmp_path):
    root = _write(tmp_path / "r", _v2_files(["- **Статус:** DONE", "- **Статус:** PENDING"]))
    rec = _json(root)["v2"]
    assert _counts(rec) == (1, 2, 0)


def test_status_word_in_wrong_case_is_not_counted(tmp_path):
    """DESIGN: слово точное по регистру. `**status:**` строкой статуса не считается: задача без отметки.

    Выведено из «слово точное по регистру», дословно в приёмке не стоит. Пара в одном плане:
    `Status` (1.1) считается, `status` (1.2) нет — иначе тест зелён и без реализации.
    """
    root = _write(
        tmp_path / "r", {"plans/en-case/plan.md": _heading_plan(["- **Status:** DONE", "- **status:** DONE"])}
    )
    rec = _json(root)["en-case"]
    assert _counts(rec) == (1, 2, 1)


# ============================================================================ 3. BRANCH_MISSING

MISSING_TEXT = "нет среди локальных"
# план -> имя ветки, на которое находка обязана указать (живое дерево фикстуры)
POSITIVES = {
    "live-nope": "feat/nope",
    "waiting-nope": "feat/nope",
    "unlisted-nope-en": "feat/nope-en",
    "bold-nope": "feat/bold-nope",
    "live-nope-tail": "feat/tail-nope",
    "live-remote": "feat/remote-only",
}
# план -> строка `Ветка:`; находки быть не должно
NEGATIVES = {
    "live-yes": "- **Ветка:** `feat/yes`",
    "live-main": "- **Ветка:** `main` — короткие ветки (`docs/…`)",
    "live-tpl": "- **Ветка:** `feat/x-<фаза>`",
    "live-tpl-ellipsis": "- **Ветка:** `feat/x-…`",
    "live-tpl-star": "- **Ветка:** `feat/x-*`",
    "live-prose-first": "- **Ветка:** позже `feat/nope-later`",
    "live-master": "- **Ветка:** `master`",
    "live-tagged": "- **Ветка:** `feat/tagged`",
    "archived-nope": "- **Ветка:** `feat/nope`",
    "closed-tier-nope": "- **Ветка:** `feat/nope`",
    "header-done-nope": "- **Ветка:** `feat/nope`",
    "alldone-nope": "- **Ветка:** `feat/nope`",
}
BRANCH_LINES = {
    "live-nope": "- **Ветка:** `feat/nope`",
    "waiting-nope": "- **Ветка:** `feat/nope`",
    "unlisted-nope-en": "- **Branch:** feat/nope-en",
    "bold-nope": "- **Ветка:** **feat/bold-nope**",
    "live-nope-tail": "- **Ветка:** `feat/tail-nope` — ветка плана, живёт до слияния",
    "live-remote": "- **Ветка:** `feat/remote-only`",
    **NEGATIVES,
}


def _init_repo(root: Path) -> None:
    """git init в root; HEAD -> main; один коммит (файл обязателен); ветки/теги для случаев приёмки 3."""
    _git_ok(root, "init", "-q")
    _git_ok(root, "symbolic-ref", "HEAD", "refs/heads/main")
    _git_ok(root, "config", "user.email", "t@example.invalid")
    _git_ok(root, "config", "user.name", "tester")
    _git_ok(root, "config", "core.autocrlf", "false")
    _git_ok(root, "add", "-A")
    _git_ok(root, "commit", "-q", "-m", "init")
    _git_ok(root, "branch", "feat/yes")
    _git_ok(root, "branch", "feat/tagged")
    _git_ok(root, "tag", "feat/tagged")  # одноимённый тег: `%(refname:short)` дал бы `heads/feat/tagged`
    _git_ok(root, "update-ref", "refs/remotes/origin/feat/remote-only", "HEAD")  # только удалённая — «локальной» нет


def _branch_plan_text(branch_line: str, *, header_done: bool = False, all_done: bool = False) -> str:
    header = ["- **Статус:** DONE"] if header_done else []
    task = "- Task 1.1: делаем [DONE]" if all_done else "- Task 1.1: делаем [PENDING]"
    return _list_plan(header=(*header, branch_line), tasks=(task,))


def _branch_files(*, include_archive: bool = True) -> dict[str, str]:
    tier41 = [
        "live-nope", "live-yes", "live-main", "live-tpl", "live-tpl-ellipsis", "live-tpl-star",
        "live-prose-first", "live-master", "live-tagged", "live-remote", "live-nope-tail", "bold-nope", "alldone-nope",
    ]  # fmt: skip
    files = {"plans/queue/ORDER.md": _order_md(tier41=tier41, tier42=["waiting-nope"], tier43=["closed-tier-nope"])}
    for name, line in BRANCH_LINES.items():
        files[f"plans/{name}/plan.md"] = _branch_plan_text(
            line, header_done=(name == "header-done-nope"), all_done=(name == "alldone-nope")
        )
    if not include_archive:
        files.pop("plans/archived-nope/plan.md")
    else:
        files["plans/_archive/archived-nope/plan.md"] = files.pop("plans/archived-nope/plan.md")
    return files


def _lines(stdout: str, code: str) -> list[str]:
    return [ln for ln in stdout.splitlines() if ln.startswith(code + " ")]


def _missing_by_plan(stdout: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for ln in _lines(stdout, "BRANCH_MISSING"):
        m = re.match(r"BRANCH_MISSING (\S+) (\S+) — (.*)$", ln)
        assert m, f"строка BRANCH_MISSING не по формату `<код> <план> <уровень> — <текст>`: {ln!r}"
        out.setdefault(m.group(1), []).append(f"{m.group(2)} — {m.group(3)}")
    return out


@pytest.fixture(scope="module")
def repo_check(tmp_path_factory):
    """Фикстура-репозиторий приёмки 3 и результат одного `--check`."""
    root = _write(tmp_path_factory.mktemp("branch_repo"), _branch_files())
    _init_repo(root)
    assert _git(root, "rev-parse", "--show-toplevel").returncode == 0
    cp = _cli(root, "--check")
    return root, cp


def test_branch_missing_line_for_live_plan_exact(repo_check):
    """Приёмка 3: живой план с `feat/nope` -> `BRANCH_MISSING <план> info — ветки feat/nope нет среди локальных`."""
    _, cp = repo_check
    assert "BRANCH_MISSING live-nope info — ветки feat/nope нет среди локальных" in cp.stdout.splitlines(), cp.stdout[
        :1500
    ]


def test_branch_missing_is_informational_exit_zero(repo_check):
    """Приёмка 3: `--check` exit 0 при находке (якорь: находка есть)."""
    _, cp = repo_check
    assert _missing_by_plan(cp.stdout).get("live-nope"), "якорь: BRANCH_MISSING live-nope не напечатан"
    assert cp.returncode == 0, f"exit {cp.returncode}\n{cp.stdout[-800:]}"


@pytest.mark.parametrize("plan", sorted(POSITIVES))
def test_branch_missing_fires_with_branch_name(repo_check, plan):
    """Положительные случаи: имя ветки в тексте — именно токен из поля, без обёрток и хвоста."""
    _, cp = repo_check
    got = _missing_by_plan(cp.stdout).get(plan)
    assert got == [f"info — ветки {POSITIVES[plan]} {MISSING_TEXT}"], f"{plan}: {got!r}\n{cp.stdout[:1500]}"


def test_branch_missing_exact_set_of_plans(repo_check):
    """Ровно шесть планов получают находку, по одной строке на план."""
    _, cp = repo_check
    got = _missing_by_plan(cp.stdout)
    assert {k: len(v) for k, v in got.items()} == {k: 1 for k in POSITIVES}, cp.stdout[:2000]


@pytest.mark.parametrize("plan", sorted(NEGATIVES))
def test_branch_missing_absent_in_same_repo(repo_check, plan):
    """Отрицательные случаи — в ТОЙ ЖЕ репозиторной фикстуре, где положительный срабатывает (якорь в тесте)."""
    _, cp = repo_check
    got = _missing_by_plan(cp.stdout)
    assert "live-nope" in got, (
        "якорь: в этой фикстуре находка для feat/nope обязана быть, иначе «нет» ничего не доказывает"
    )
    assert plan not in got, f"{plan} ({NEGATIVES[plan]!r}): лишняя находка {got.get(plan)!r}"


def test_branch_missing_not_in_json_stdout(repo_check):
    """Находка — только `--check`: `--json` остаётся списком планов (якорь: --check её печатает)."""
    root, cp = repo_check
    assert _missing_by_plan(cp.stdout).get("live-nope"), "якорь"
    js = _cli(root, "--json")
    assert js.returncode == 0
    assert "BRANCH_MISSING" not in js.stdout
    assert isinstance(json.loads(js.stdout), list)


def test_branch_missing_baseline_does_not_silence_info(repo_check, tmp_path):
    """DESIGN: информационную находку база не гасит — строка есть и с базой, без пометки «(известна, в базе)»."""
    root, _ = repo_check
    base = tmp_path / "base.txt"
    base.write_text("live-nope:BRANCH_MISSING\n", encoding="utf-8")
    cp = _cli(root, "--check", "--baseline", str(base))
    assert cp.returncode == 0
    assert "BRANCH_MISSING live-nope info — ветки feat/nope нет среди локальных" in cp.stdout.splitlines(), cp.stdout[
        :1500
    ]


def _nope_plan_files() -> dict[str, str]:
    return {
        "plans/live-nope/plan.md": _branch_plan_text("- **Ветка:** `feat/nope`"),
    }


def test_branch_missing_absent_without_git_ceiling(tmp_path_factory, repo_check):
    """Приёмка 3: каталог без `git init`, GIT_CEILING_DIRECTORIES=<родитель> и для CLI, и для предусловия -> находок нет, exit 0."""
    _, anchor_cp = repo_check
    assert _missing_by_plan(anchor_cp.stdout).get("live-nope"), "якорь: в git-фикстуре находка для live-nope есть"
    root = _write(tmp_path_factory.mktemp("nogit"), _nope_plan_files())
    env = _env(GIT_CEILING_DIRECTORIES=str(root.parent))
    pre = _git(root, "rev-parse", "--show-toplevel", env=env)
    assert pre.returncode != 0, f"предусловие: каталог должен быть вне git, а toplevel={pre.stdout!r}"
    cp = _cli(root, "--check", env=env)
    assert cp.returncode == 0, f"exit {cp.returncode}\n{cp.stdout[-600:]}\n{cp.stderr[-300:]}"
    assert "BRANCH_MISSING" not in cp.stdout, cp.stdout[:1000]
    assert "live-nope" not in _missing_by_plan(cp.stdout)


def test_branch_missing_absent_when_root_is_not_repo_top(tmp_path_factory, repo_check):
    """DESIGN: `--root` не верхний каталог репозитория -> находок нет (якорь — тот же план в корне репозитория)."""
    _, anchor_cp = repo_check
    assert _missing_by_plan(anchor_cp.stdout).get("live-nope"), "якорь: в корне репозитория находка есть"
    parent = tmp_path_factory.mktemp("parent_repo")
    (parent / "README.txt").write_text("x\n", encoding="utf-8")
    _init_repo(parent)
    sub = _write(parent / "sub", _nope_plan_files())
    top = _git(sub, "rev-parse", "--show-toplevel")
    assert top.returncode == 0 and Path(top.stdout.strip()).resolve() == parent.resolve(), (
        f"предусловие: toplevel={top.stdout!r}"
    )
    assert Path(top.stdout.strip()).resolve() != sub.resolve()
    cp = _cli(sub, "--check")
    assert cp.returncode == 0, f"exit {cp.returncode}\n{cp.stdout[-600:]}"
    assert "BRANCH_MISSING" not in cp.stdout, cp.stdout[:1000]


# ============================================================================ 4-6. tier


def _matrix_files() -> dict[str, str]:
    """Матрица приёмки 5: пять планов, у каждого одна открытая задача (0 из 1)."""
    done = ("- **Статус:** DONE",)
    return {
        "plans/queue/ORDER.md": _order_md(tier41=["m41-done", "m41-plain"], tier42=["m42-done"], tier43=["m43"]),
        "plans/m41-done/plan.md": _list_plan(header=done),
        "plans/m42-done/plan.md": _list_plan(header=done),
        "plans/m43/plan.md": _list_plan(),
        "plans/mout-done/plan.md": _list_plan(header=done),
        "plans/mout-live/plan.md": _list_plan(),
        "plans/m41-plain/plan.md": _list_plan(),
    }


@pytest.fixture(scope="module")
def matrix_root(tmp_path_factory):
    return _write(tmp_path_factory.mktemp("matrix"), _matrix_files())


@pytest.fixture(scope="module")
def matrix_html(matrix_root):
    out = matrix_root / "page.html"
    cp = _cli(matrix_root, "--html", str(out))
    assert cp.returncode == 0, cp.stderr[:400]
    return out.read_text(encoding="utf-8")


TIER_JSON = {
    "m41-done": "queue",  # §4.1
    "m41-plain": "queue",
    "m42-done": "waiting",  # §4.2
    "m43": "closed",  # §4.3
    "mout-done": None,  # вне ORDER.md
    "mout-live": None,
}


@pytest.mark.parametrize("plan", sorted(TIER_JSON))
def test_json_tier_values(matrix_root, plan):
    """Приёмка 4: §4.1 -> "queue", §4.2 -> "waiting", §4.3 -> "closed", вне ORDER.md -> null."""
    rec = _json(matrix_root)[plan]
    assert rec["tier"] == TIER_JSON[plan]


def test_json_tier_never_old_numeric(matrix_root):
    """Приёмка 4: ни одного "4.1"/"4.2"/"4.3" в поле tier (якорь: queue есть)."""
    tiers = [r["tier"] for r in _json_list(matrix_root)]
    assert "queue" in tiers, f"якорь: {tiers}"
    assert not {"4.1", "4.2", "4.3"} & set(tiers), tiers


def test_json_plan_order_follows_tiers(matrix_root):
    """Порядок записей --json: §4.1 по строкам, §4.2, §4.3, затем вне ORDER.md по имени (guard переименования)."""
    names = [r["plan"] for r in _json_list(matrix_root)]
    assert names == ["m41-done", "m41-plain", "m42-done", "m43", "mout-done", "mout-live"]


def test_json_ready_respects_closed_tier(matrix_root):
    """plan_closed: §4.3 с открытой задачей закрыт -> ready false; план вне ORDER с открытой задачей -> ready true (якорь)."""
    plans = _json(matrix_root)
    assert plans["mout-live"]["ready"] is True
    assert plans["m43"]["ready"] is False
    assert plans["m41-plain"]["ready"] is True


EXPECTED_PLAN_KEYS = [
    "plan", "path", "archived", "lane", "tier", "done", "total", "dropped", "unknown", "unmarked",
    "header_status", "tasks", "after", "after_reason", "waiting_on", "ready", "dep_unknown", "dep_cycle", "active",
]  # fmt: skip
EXPECTED_TASK_KEYS = ["id", "title", "status", "ref", "after", "ready"]


def test_json_plan_key_order_unchanged(matrix_root):
    """Приёмка 6: прежний список, `active` в хвосте (после 5.5 допустим только `branches` следом)."""
    for rec in _json_list(matrix_root):
        keys = list(rec)
        assert keys[: len(EXPECTED_PLAN_KEYS)] == EXPECTED_PLAN_KEYS, keys
        # Task 7.1: ключ anchor дописан в конец (контракт append-only)
        assert keys[len(EXPECTED_PLAN_KEYS) :] in ([], ["branches"], ["branches", "anchor"]), keys


def test_json_task_key_order_unchanged(matrix_root):
    rec = _json(matrix_root)["m41-plain"]
    assert rec["tasks"], "якорь: у плана есть задача"
    assert list(rec["tasks"][0]) == EXPECTED_TASK_KEYS


def test_text_listing_keeps_numeric_tier_address(matrix_root):
    """DESIGN: текстовый список печатает адрес в ORDER.md (`4.1`/`4.2`/`4.3`), как сейчас."""
    cp = _cli(matrix_root)
    assert cp.returncode == 0
    rows = {ln.split()[0]: ln.split()[1] for ln in cp.stdout.splitlines() if ln.strip()}
    assert rows["m41-plain"] == "4.1", cp.stdout
    assert rows["m42-done"] == "4.2", cp.stdout
    assert rows["m43"] == "4.3", cp.stdout
    assert rows["mout-live"] == "—", cp.stdout


# ---- страница

_DETAILS_RE = re.compile(r'<details ([^>]*class="plan"[^>]*)>\s*<summary>(.*?)</summary>', re.S)
_ATTR_RE = re.compile(r'([\w-]+)="([^"]*)"')
_CHIP_RE = re.compile(r'<span class="chip[^"]*"([^>]*)>(.*?)</span>', re.S)
_BADGE_RE = re.compile(r'<span class="badge">(.*?)</span>', re.S)


def _plan_view(page: str, plan: str) -> dict:
    for attrs_s, summary in _DETAILS_RE.findall(page):
        attrs = dict(_ATTR_RE.findall(attrs_s))
        if attrs.get("data-plan") == plan:
            chips = [
                (dict(_ATTR_RE.findall(a)).get("data-chip", ""), html_lib.unescape(re.sub(r"<[^>]+>", "", t)).strip())
                for a, t in _CHIP_RE.findall(summary)
            ]
            badges = [html_lib.unescape(b).strip() for b in _BADGE_RE.findall(summary)]
            return {
                "tier": attrs.get("data-tier"),
                "chips": chips,
                "badges": badges,
                "progress": "<progress" in summary,
            }
    raise AssertionError(f"плана {plan!r} нет на странице")


# план -> (data-tier, бейдж §, чипы из набора {header-conflict, closed, unmarked}, есть ли полоса)
MATRIX = {
    "m41-done": ("queue", "§4.1", [("header-conflict", "⚠ шапка: DONE, задачи 0 из 1")], True),
    "m42-done": ("waiting", "§4.2", [("header-conflict", "⚠ шапка: DONE, задачи 0 из 1")], True),
    "m43": ("closed", "§4.3", [("closed", "закрыт · задачи 0 из 1")], False),
    "mout-done": ("", None, [("closed", "закрыт · задачи 0 из 1")], False),
    "m41-plain": ("queue", "§4.1", [], True),
}
_TRUST_CHIPS = {"header-conflict", "closed", "unmarked"}


@pytest.mark.parametrize("plan", sorted(MATRIX))
def test_page_data_tier(matrix_html, plan):
    """Приёмка 5: `data-tier` — queue / waiting / closed / пусто."""
    assert _plan_view(matrix_html, plan)["tier"] == MATRIX[plan][0]


@pytest.mark.parametrize("plan", sorted(MATRIX))
def test_page_badge_keeps_numeric_section(matrix_html, plan):
    """Приёмка 5: бейдж `§4.1`/`§4.2`/`§4.3` (адрес в ORDER.md), у плана вне ORDER бейджа § нет."""
    badges = [b for b in _plan_view(matrix_html, plan)["badges"] if b.startswith("§")]
    expected = MATRIX[plan][1]
    assert badges == ([expected] if expected else [])


@pytest.mark.parametrize("plan", sorted(MATRIX))
def test_page_trust_chips_and_bar(matrix_html, plan):
    """Приёмка 5: чипы шапки/закрытия и полоса прогресса по строкам таблицы."""
    view = _plan_view(matrix_html, plan)
    chips = [c for c in view["chips"] if c[0] in _TRUST_CHIPS]
    assert chips == MATRIX[plan][2]
    assert view["progress"] is MATRIX[plan][3]


def test_page_no_numeric_data_tier(matrix_html):
    """Приёмка 4/5: числовых значений `data-tier` на странице нет (якорь: queue есть)."""
    assert 'data-tier="queue"' in matrix_html, "якорь"
    assert not re.search(r'data-tier="4\.[123]"', matrix_html)


def _section_of(page: str, plan: str) -> str:
    pos = page.index(f'data-plan="{plan}"')
    marks = {
        m.group(2): m.start()
        for m in re.finditer(r'<(section|details) id="(priority|who|queue|waiting|unlisted|archive)"', page)
    }
    before = {sid: p for sid, p in marks.items() if p < pos}
    return max(before, key=before.get)


def test_page_plans_land_in_sections_by_tier(matrix_html):
    """Все сравнения яруса переехали: §4.1 -> #queue, §4.2 -> #waiting, §4.3 -> #archive, вне ORDER -> #unlisted."""
    got = {
        p: _section_of(matrix_html, p) for p in ("m41-done", "m41-plain", "m42-done", "m43", "mout-done", "mout-live")
    }
    assert got == {
        "m41-done": "queue",
        "m41-plain": "queue",
        "m42-done": "waiting",
        "m43": "archive",
        "mout-done": "unlisted",
        "mout-live": "unlisted",
    }


def _section_ids(page: str) -> list[str]:
    return re.findall(r'<(?:section|details) id="(priority|who|queue|waiting|unlisted|archive)"', page)


def test_page_section_id_order_with_unlisted(matrix_html):
    """Приёмка 6: priority, who, queue, waiting, unlisted, archive; unlisted есть (в фикстуре есть план вне ORDER)."""
    assert _section_ids(matrix_html) == ["priority", "who", "queue", "waiting", "unlisted", "archive"]


def test_page_section_id_order_without_unlisted(tmp_path):
    """Приёмка 6: без плана вне ORDER.md секции `unlisted` нет."""
    root = _write(
        tmp_path / "r",
        {
            "plans/queue/ORDER.md": _order_md(tier41=["only-queue"]),
            "plans/only-queue/plan.md": _list_plan(),
        },
    )
    out = root / "page.html"
    cp = _cli(root, "--html", str(out))
    assert cp.returncode == 0, cp.stderr[:300]
    assert _section_ids(out.read_text(encoding="utf-8")) == ["priority", "who", "queue", "waiting", "archive"]


# ---- находки, привязанные к ярусу: §4.1 блокирует, остальные нет


def _findings_files() -> dict[str, str]:
    bare = "# План без задач\n\nТолько описание.\n"
    unknown = _list_plan(tasks=("- Task 1.1: пункт без слова статуса",))
    return {
        "plans/queue/ORDER.md": _order_md(tier41=["f41-empty", "f41-unknown"], tier42=["f42-empty", "f42-unknown"]),
        "plans/f41-empty/plan.md": bare,
        "plans/f42-empty/plan.md": bare,
        "plans/fout-empty/plan.md": bare,
        "plans/f41-unknown/plan.md": unknown,
        "plans/f42-unknown/plan.md": unknown,
    }


@pytest.fixture(scope="module")
def findings_check(tmp_path_factory):
    root = _write(tmp_path_factory.mktemp("findings"), _findings_files())
    return _cli(root, "--check")


def _level(stdout: str, code: str, plan: str) -> str | None:
    for ln in stdout.splitlines():
        m = re.match(rf"{code} {re.escape(plan)}(?::\S+)? (blocking|info) — ", ln)
        if m:
            return m.group(1)
    return None


@pytest.mark.parametrize(
    ("code", "plan", "level"),
    [
        ("NO_TASKS", "f41-empty", "blocking"),
        ("NO_TASKS", "f42-empty", "info"),
        ("NO_TASKS", "fout-empty", "info"),
        ("UNKNOWN_STATUS", "f41-unknown", "blocking"),
        ("UNKNOWN_STATUS", "f42-unknown", "info"),
    ],
)
def test_tier_gated_findings_block_only_in_queue_section(findings_check, code, plan, level):
    """Guard: блокировка находок завязана на §4.1 — после переименования яруса обязана остаться (`queue`)."""
    assert _level(findings_check.stdout, "NO_TASKS", "f41-empty") == "blocking", "якорь: §4.1 блокирует"
    assert _level(findings_check.stdout, code, plan) == level, findings_check.stdout[:1500]
    assert findings_check.returncode == 1
