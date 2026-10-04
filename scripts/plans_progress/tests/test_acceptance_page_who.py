# ruff: noqa: E501  -- литералы-фикстуры и ожидания в одну строку, форматтер их не переносит
"""Приёмка Task 5.3 — слепые тесты чипа «в работе» и секции `#who` на странице.

Источник: plans/2026-10-02_plans-progress-dashboard/tasks/5.3.md (DESIGN, ACCEPTANCE W1-W6).
Реализацию страницы тестер не видел; читал только сигнатуры to_html/_plan_html и вид прежней страницы.

Только CLI в subprocess (timeout): `plans_progress.py --root R --now NOW [--active-window W] --html FILE`.
Фикстура — настоящий `git init -b main` + `extensions.worktreeConfig true` + `git worktree add`,
журналы `<worktree>/data/agent-journal.jsonl` пишет тест. Страницу разбирает свой HTMLParser.
`title` и `data-worktree` сравниваются через `Path` (porcelain на Windows даёт `C:/...`).
Сырой HTML (экранирование W6) проверяется по тексту файла, прочее — по разобранным значениям.

Договорённости чтения (в тексте задачи неоднозначно; выбрано строгое чтение):
- Пробелы в тексте элементов схлопываются (`" ".join(text.split())`): перенос строки между
  тегами не должен ломать литерал; сами слова, `·`, `→`, `—` сравниваются точно.
- Каждый негативный тест несёт контроль, который обязан быть положительным в том же прогоне:
  W3 — тот же журнал с более широким окном даёт чип; прочие — соседний worktree с чипом/li.
- Чип `active` последний в `<summary>`: после ВСЕХ чипов другого вида, а не только после `after`.
- «Корней нет» (нет git) проверяется и внутри чужого репозитория (tmp_path лежит в нём),
  GIT_CEILING_DIRECTORIES здесь не нужен.
"""

from __future__ import annotations

import itertools
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

NOTE_1 = "Агенты, запущенные из главного дерева, видны как активность main."
NOTE_2 = "Сессия без субагентов и без события SessionStart не видна."

_counter = itertools.count(1)


# =========================================================================== хелперы фикстуры


def _env() -> dict[str, str]:
    env = dict(os.environ)
    for var in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"):
        env.pop(var, None)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def at(minutes: int = 0, seconds: int = 0) -> str:
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


def plan_md(*header: str, done: bool = False) -> str:
    lines = ["# План", ""] + list(header) + [""]
    item = "- Task 1.1: x [DONE]\n" if done else "- Task 1.1: x [PENDING]\n"
    return "\n".join(lines) + "\n## Порядок выполнения\n\n" + item


def branch_line(branch: str) -> str:
    return f"- **Ветка:** {branch}"


class Repo:
    """Настоящий git-репозиторий: `repo/` (главное дерево) и соседние `wt_<имя>/` (worktree)."""

    def __init__(self, base: Path, files: dict[str, str], initial: str = "main") -> None:
        self.base = base.resolve()
        self.root = self.base / "repo"
        self.initial = initial
        (self.root / "plans").mkdir(parents=True)
        (self.root / "NOTES.txt").write_text("fixture", encoding="utf-8")
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
        """`branch=None` -> detached HEAD."""
        path = self.base / f"wt_{name}"
        if branch is None:
            self.git(self.root, "worktree", "add", "-q", "--detach", str(path), self.initial)
        else:
            self.git(self.root, "worktree", "add", "-q", "-b", branch, str(path), self.initial)
        return path.resolve()

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


# =========================================================================== разбор страницы


def _norm(text: str) -> str:
    return " ".join(text.split())


class Page(HTMLParser):
    """Разбор страницы: порядок секций, чипы в summary планов, секция #who."""

    VOID = {"br", "meta", "link", "img", "input", "hr"}

    def __init__(self, raw: str) -> None:
        super().__init__(convert_charrefs=True)
        self.raw = raw
        self.stack: list[tuple[str, dict[str, str | None]]] = []
        self.sections: list[tuple[str, str]] = []  # (class, id) в порядке документа
        self.plans: dict[str, dict] = {}  # data-plan -> {"chips": [...], "archived": bool}
        self.who: dict | None = None
        self.active_chip_total = 0
        self._collect: list[dict] = []  # открытые коллекторы текста
        self.feed(raw)
        self.close()

    def _in(self, tag: str, **want: str) -> bool:
        for t, a in self.stack:
            if t != tag:
                continue
            if all((v in (a.get(k) or "").split()) if k == "class" else (a.get(k) == v) for k, v in want.items()):
                return True
        return False

    def _current_plan(self) -> str | None:
        for tag, a in reversed(self.stack):
            if tag == "details" and "plan" in (a.get("class") or "").split():
                return a.get("data-plan")
        return None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "section":
            self.sections.append((a.get("class") or "", a.get("id") or ""))
            if a.get("id") == "who":
                self.who = {"h2": None, "lis": [], "ps": [], "has_ul": False}
        if tag in self.VOID:
            return
        self.stack.append((tag, a))
        in_who = self.who is not None and self._in("section", id="who")
        if tag == "details" and "plan" in (a.get("class") or "").split():
            self.plans[a.get("data-plan") or ""] = {"chips": [], "archived": self._in("details", id="archive")}
        if tag == "span" and "chip" in (a.get("class") or "").split() and self._in("summary"):
            plan = self._current_plan()
            if plan is not None:
                entry = {"attrs": a, "text": "", "kind": "chip"}
                self.plans[plan]["chips"].append(entry)
                self._collect.append({"tag": tag, "entry": entry})
        if tag == "span" and a.get("data-chip") == "active":
            self.active_chip_total += 1
        if in_who:
            if tag == "ul":
                self.who["has_ul"] = True
            if tag in ("li", "p", "h2"):
                entry = {"attrs": a, "text": "", "kind": tag}
                if tag == "li":
                    self.who["lis"].append(entry)
                elif tag == "p":
                    self.who["ps"].append(entry)
                else:
                    self.who["h2"] = entry
                self._collect.append({"tag": tag, "entry": entry})

    def handle_data(self, data):
        for c in self._collect:
            c["entry"]["text"] += data

    def handle_endtag(self, tag):
        for i in range(len(self._collect) - 1, -1, -1):
            if self._collect[i]["tag"] == tag:
                del self._collect[i]
                break
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break

    # ---- удобные чтения
    def chips(self, plan: str, kind: str | None = None) -> list[dict]:
        assert plan in self.plans, f"плана {plan!r} нет на странице; есть: {sorted(self.plans)}"
        got = self.plans[plan]["chips"]
        if kind is not None:
            got = [c for c in got if c["attrs"].get("data-chip") == kind]
        return got

    def need_who(self) -> dict:
        assert self.who is not None, 'на странице нет <section id="who">'
        return self.who

    def who_h2(self) -> str:
        h2 = self.need_who()["h2"]
        assert h2 is not None, "в #who нет <h2>"
        return _norm(h2["text"])

    def who_lis(self) -> list[dict]:
        return self.need_who()["lis"]

    def who_li(self, path: Path) -> dict:
        found = [li for li in self.who_lis() if Path(li["attrs"].get("data-worktree") or "") == path]
        assert len(found) == 1, (
            f"ждали одну <li> для {path}, есть: {[li['attrs'].get('data-worktree') for li in self.who_lis()]}"
        )
        return found[0]


def text_of(entry: dict) -> str:
    return _norm(entry["text"])


def render(
    root: Path, *flags: str, where: Path, cwd: Path | None = None, env_extra: dict[str, str] | None = None
) -> Page:
    out = where / f"page_{next(_counter)}.html"
    env = _env()
    if env_extra:
        env.update(env_extra)
    cp = subprocess.run(
        [sys.executable, str(PROGRESS), "--root", str(root), "--now", NOW, *flags, "--html", str(out)],
        capture_output=True,
        timeout=CALL_TIMEOUT,
        env=env,
        cwd=str(cwd) if cwd else None,
        encoding="utf-8",
        errors="replace",
    )
    assert cp.returncode == 0, f"--html: exit={cp.returncode} stderr={cp.stderr[:400]!r} stdout={cp.stdout[:200]!r}"
    assert out.is_file(), f"страница не записана: {cp.stdout[:200]!r}"
    return Page(out.read_text(encoding="utf-8"))


def ctrl_repo(tmp_path: Path, files: dict[str, str] | None = None) -> tuple[Repo, Path]:
    """Репозиторий с планом CTRL (`feat/ctrl`) и worktree со свежей строкой: у него обязан быть чип и <li>."""
    repo = Repo(tmp_path, {"plans/CTRL/plan.md": plan_md(branch_line("feat/ctrl")), **(files or {})})
    wt = repo.worktree("ctrl", "feat/ctrl")
    repo.fresh(wt)
    return repo, wt


def assert_ctrl_chip(page: Page) -> None:
    got = page.chips("CTRL", "active")
    assert len(got) == 1 and got[0]["attrs"].get("data-active") == "feat/ctrl", f"контроль не сработал: {got}"


# =========================================================================== W1: чип


def test_w1_chip_text_and_attributes_are_literal(tmp_path):
    repo = Repo(tmp_path, {"plans/X/plan.md": plan_md(branch_line("feat/x"))})
    wt = repo.worktree("x", "feat/x")
    repo.journal(
        wt,
        rec("2026-10-03T10:50:00", session="s1", agent="a1"),
        rec("2026-10-03T11:00:05", session="s2", agent="a1"),
    )
    chips = render(repo.root, where=tmp_path).chips("X", "active")
    assert len(chips) == 1, chips
    c = chips[0]
    assert c["attrs"].get("data-active") == "feat/x"
    assert text_of(c) == "в работе: feat/x · сессий 2 · агентов 1 · сигнал 2026-10-03 11:00"


def test_w1_chip_is_a_span_chip_whose_title_is_the_worktree_path(tmp_path):
    repo = Repo(tmp_path, {"plans/X/plan.md": plan_md(branch_line("feat/x"))})
    wt = repo.worktree("x", "feat/x")
    repo.fresh(wt)
    c = render(repo.root, where=tmp_path).chips("X", "active")[0]
    assert Path(c["attrs"].get("title") or "") == wt
    assert "chip" in (c["attrs"].get("class") or "").split()


def test_w1_plan_without_worktree_has_no_active_chip_while_control_has_one(tmp_path):
    repo, _ = ctrl_repo(tmp_path, {"plans/Y/plan.md": plan_md()})
    page = render(repo.root, where=tmp_path)
    assert_ctrl_chip(page)
    assert page.chips("Y", "active") == []


def test_w1_chip_belongs_to_the_summary_of_its_own_plan_only(tmp_path):
    repo, _ = ctrl_repo(tmp_path, {"plans/X/plan.md": plan_md(branch_line("feat/x"))})
    repo.fresh(repo.worktree("x", "feat/x"))
    page = render(repo.root, where=tmp_path)
    assert [c["attrs"].get("data-active") for c in page.chips("X", "active")] == ["feat/x"]
    assert [c["attrs"].get("data-active") for c in page.chips("CTRL", "active")] == ["feat/ctrl"]


# =========================================================================== W2: несколько worktree, архив, счёт


def test_w2_two_worktrees_of_one_plan_give_two_chips_in_worktree_order(tmp_path):
    repo = Repo(tmp_path, {"plans/X/plan.md": plan_md()})
    wc = repo.worktree("c", "feat/c")  # создаются не по порядку
    wa = repo.worktree("a", "feat/a")
    for wt in (wc, wa):
        repo.plan_ref(wt, "plans/X")
        repo.fresh(wt)
    chips = render(repo.root, where=tmp_path).chips("X", "active")
    assert [c["attrs"].get("data-active") for c in chips] == ["feat/a", "feat/c"]
    assert [Path(c["attrs"].get("title") or "") for c in chips] == [wa, wc]


def test_w2_archived_plan_has_a_chip(tmp_path):
    repo = Repo(tmp_path, {"plans/_archive/OLD/plan.md": plan_md(branch_line("feat/old"), done=True)})
    repo.fresh(repo.worktree("old", "feat/old"))
    page = render(repo.root, where=tmp_path)
    assert page.plans["OLD"]["archived"] is True, "контроль фикстуры: OLD должен лежать в архиве"
    assert [c["attrs"].get("data-active") for c in page.chips("OLD", "active")] == ["feat/old"]


def test_w2_closed_live_plan_has_a_chip(tmp_path):
    repo = Repo(tmp_path, {"plans/DONE1/plan.md": plan_md(branch_line("feat/d"), done=True)})
    repo.fresh(repo.worktree("d", "feat/d"))
    page = render(repo.root, where=tmp_path)
    assert page.plans["DONE1"]["archived"] is False
    assert [c["attrs"].get("data-active") for c in page.chips("DONE1", "active")] == ["feat/d"]


def test_w2_active_chip_count_on_page_equals_active_records_in_all_plans(tmp_path):
    repo = Repo(
        tmp_path,
        {
            "plans/X/plan.md": plan_md(branch_line("feat/x")),
            "plans/P/plan.md": plan_md(),
            "plans/_archive/OLD/plan.md": plan_md(branch_line("feat/old"), done=True),
        },
    )
    repo.fresh(repo.worktree("x", "feat/x"))
    wp1 = repo.worktree("p1", "feat/p1")
    wp2 = repo.worktree("p2", "feat/p2")
    for wt in (wp1, wp2):
        repo.plan_ref(wt, "plans/P")
        repo.fresh(wt)
    repo.fresh(repo.worktree("old", "feat/old"))
    repo.fresh(repo.worktree("lonely", "feat/lonely"))  # сирота: чипа нет, запись в active не входит
    page = render(repo.root, where=tmp_path)
    assert page.active_chip_total == 4
    cp = subprocess.run(
        [sys.executable, str(PROGRESS), "--root", str(repo.root), "--json", "--now", NOW],
        capture_output=True, timeout=CALL_TIMEOUT, env=_env(), encoding="utf-8", errors="replace",
    )  # fmt: skip
    assert cp.returncode == 0, cp.stderr[:300]
    assert sum(len(p["active"]) for p in json.loads(cp.stdout)) == 4


# =========================================================================== W3: старая строка


def test_w3_stale_signal_gives_no_chip_and_zero_who_with_the_window_in_text(tmp_path):
    repo = Repo(tmp_path, {"plans/X/plan.md": plan_md(branch_line("feat/x"))})
    wt = repo.worktree("x", "feat/x")
    repo.journal(wt, rec(at(minutes=120)))  # 2 ч назад
    narrow = render(repo.root, "--active-window", "1h", where=tmp_path)
    wide = render(repo.root, "--active-window", "3h", where=tmp_path)  # контроль: тот же журнал, окно шире
    assert [c["attrs"].get("data-active") for c in wide.chips("X", "active")] == ["feat/x"]
    assert wide.who_h2() == "Кто где · 1"
    assert narrow.chips("X", "active") == []
    assert narrow.who_h2() == "Кто где · 0"
    assert "свежих сигналов нет (окно 1h)" in [text_of(p) for p in narrow.need_who()["ps"]]
    assert narrow.need_who()["has_ul"] is False
    assert narrow.who_lis() == []


@pytest.mark.parametrize(
    ("flags", "window"), [((), "6h"), (("--active-window", "30m"), "30m"), (("--active-window", "2d"), "2d")]
)
def test_w3_empty_who_prints_the_window_exactly_as_passed(tmp_path, flags, window):
    repo = Repo(tmp_path, {"plans/X/plan.md": plan_md(branch_line("feat/x"))})
    repo.journal(repo.worktree("x", "feat/x"), rec("2020-01-01T00:00:00"))  # давно стёрто
    control = render(repo.root, "--active-window", "5000d", where=tmp_path)  # контроль: окно шире возраста строки
    assert [c["attrs"].get("data-active") for c in control.chips("X", "active")] == ["feat/x"]
    page = render(repo.root, *flags, where=tmp_path)
    assert page.who_h2() == "Кто где · 0"
    assert f"свежих сигналов нет (окно {window})" in [text_of(p) for p in page.need_who()["ps"]]


def test_w3_window_flag_acts_on_the_page_chip_both_sides(tmp_path):
    repo = Repo(tmp_path, {"plans/X/plan.md": plan_md(branch_line("feat/x"))})
    repo.journal(repo.worktree("x", "feat/x"), rec(at(minutes=29)))
    assert len(render(repo.root, "--active-window", "30m", where=tmp_path).chips("X", "active")) == 1
    assert render(repo.root, "--active-window", "20m", where=tmp_path).chips("X", "active") == []


# =========================================================================== W4: секция #who


def test_w4_who_section_stands_between_lanes_and_queue(tmp_path):
    repo, _ = ctrl_repo(tmp_path)
    page = render(repo.root, where=tmp_path)
    assert_ctrl_chip(page)
    ids = [(cls, i) for cls, i in page.sections]
    idx_lanes = next(k for k, (cls, _) in enumerate(ids) if "lanes" in cls.split())
    idx_who = ids.index(("", "who"))
    idx_queue = next(k for k, (_, i) in enumerate(ids) if i == "queue")
    assert idx_lanes < idx_who < idx_queue, ids


def test_w4_who_header_counts_active_plus_orphans(tmp_path):
    repo, _ = ctrl_repo(tmp_path)
    repo.fresh(repo.worktree("lonely", "feat/lonely"))
    repo.fresh(repo.worktree("det", None))
    repo.fresh(repo.root)
    assert render(repo.root, where=tmp_path).who_h2() == "Кто где · 4"


def test_w4_every_fresh_worktree_is_in_exactly_one_li(tmp_path):
    repo, wctrl = ctrl_repo(tmp_path)
    wl = repo.worktree("lonely", "feat/lonely")
    wd = repo.worktree("det", None)
    repo.fresh(wl)
    repo.fresh(wd)
    repo.fresh(repo.root)
    page = render(repo.root, where=tmp_path)
    got = sorted(Path(li["attrs"].get("data-worktree") or "") for li in page.who_lis())
    assert got == sorted([wctrl, wl, wd, repo.root])


def test_w4_active_li_has_literal_attributes_and_text(tmp_path):
    repo = Repo(tmp_path, {"plans/X/plan.md": plan_md(branch_line("feat/x"))})
    wt = repo.worktree("x", "feat/x")
    repo.journal(wt, rec("2026-10-03T10:50:00", "s1", "a1"), rec("2026-10-03T11:00:05", "s2", "a1"))
    li = render(repo.root, where=tmp_path).who_li(wt)
    assert li["attrs"].get("data-branch") == "feat/x"
    assert li["attrs"].get("data-who-plan") == "X"
    assert "data-orphan" not in li["attrs"]
    assert text_of(li) == "feat/x → X · сессий 2 · агентов 1 · сигнал 2026-10-03 11:00"


def test_w4_orphan_li_has_literal_attributes_and_text(tmp_path):
    repo, _ = ctrl_repo(tmp_path)
    wt = repo.worktree("lonely", "feat/lonely")
    repo.journal(wt, rec("2026-10-03T11:55:30", "s1", "a1"))
    page = render(repo.root, where=tmp_path)
    assert_ctrl_chip(page)
    li = page.who_li(wt)
    assert li["attrs"].get("data-orphan") == "1"
    assert li["attrs"].get("data-branch") == "feat/lonely"
    assert "data-who-plan" not in li["attrs"]
    assert text_of(li) == "feat/lonely — план не найден · сессий 1 · агентов 1 · сигнал 2026-10-03 11:55"


def test_w4_main_tree_with_fresh_signal_is_an_orphan_on_main(tmp_path):
    repo, _ = ctrl_repo(tmp_path)
    repo.journal(repo.root, rec("2026-10-03T11:40:00", "s1", "a1"))
    page = render(repo.root, where=tmp_path)
    assert_ctrl_chip(page)
    li = page.who_li(repo.root)
    assert li["attrs"].get("data-orphan") == "1"
    assert li["attrs"].get("data-branch") == "main"
    assert text_of(li).startswith("main — план не найден")


def test_w4_detached_orphan_reads_detached_and_has_empty_data_branch(tmp_path):
    repo, _ = ctrl_repo(tmp_path)
    wt = repo.worktree("det", None)
    repo.journal(wt, rec("2026-10-03T11:30:00", "s1", "a1"))
    page = render(repo.root, where=tmp_path)
    assert_ctrl_chip(page)
    li = page.who_li(wt)
    assert "data-branch" in li["attrs"] and li["attrs"]["data-branch"] in ("", None)
    assert li["attrs"].get("data-orphan") == "1"
    assert text_of(li) == "(detached) — план не найден · сессий 1 · агентов 1 · сигнал 2026-10-03 11:30"


def test_w4_detached_worktree_with_plan_ref_gets_detached_chip_and_li(tmp_path):
    repo = Repo(tmp_path, {"plans/A/plan.md": plan_md()})
    wt = repo.worktree("det", None)
    repo.plan_ref(wt, "plans/A")
    repo.journal(wt, rec("2026-10-03T11:30:00", "s1", "a1"))
    page = render(repo.root, where=tmp_path)
    chip = page.chips("A", "active")[0]
    assert chip["attrs"].get("data-active") in ("", None)
    assert text_of(chip) == "в работе: (detached) · сессий 1 · агентов 1 · сигнал 2026-10-03 11:30"
    li = page.who_li(wt)
    assert li["attrs"].get("data-who-plan") == "A" and li["attrs"].get("data-branch") in ("", None)
    assert text_of(li) == "(detached) → A · сессий 1 · агентов 1 · сигнал 2026-10-03 11:30"


def test_w4_active_come_before_orphans_each_group_sorted_by_worktree(tmp_path):
    repo = Repo(tmp_path, {"plans/X/plan.md": plan_md(), "plans/Z/plan.md": plan_md()})
    # имена worktree по возрастанию пути: a < b < c < d; активные — b и c, сироты — a и d
    wa = repo.worktree("a", "feat/a")
    wb = repo.worktree("b", "feat/b")
    wc = repo.worktree("c", "feat/c")
    wd = repo.worktree("d", "feat/d")
    repo.plan_ref(wc, "plans/X")
    repo.plan_ref(wb, "plans/Z")
    for wt in (wa, wb, wc, wd):
        repo.fresh(wt)
    lis = render(repo.root, where=tmp_path).who_lis()
    assert [Path(li["attrs"].get("data-worktree") or "") for li in lis] == [wb, wc, wa, wd]
    assert ["data-orphan" in li["attrs"] for li in lis] == [False, False, True, True]


# =========================================================================== W5: примечания


def _notes(page: Page) -> list[str]:
    return [text_of(p) for p in page.need_who()["ps"] if "note" in (p["attrs"].get("class") or "").split()]


def test_w5_both_notes_are_present_and_last_when_who_is_not_empty(tmp_path):
    repo, _ = ctrl_repo(tmp_path)
    page = render(repo.root, where=tmp_path)
    assert_ctrl_chip(page)
    assert _notes(page) == [NOTE_1, NOTE_2]
    last_two = [text_of(p) for p in page.need_who()["ps"]][-2:]
    assert last_two == [NOTE_1, NOTE_2]


def test_w5_both_notes_are_present_when_who_is_empty_and_follow_the_empty_line(tmp_path):
    repo = Repo(tmp_path, {"plans/X/plan.md": plan_md(branch_line("feat/x"))})
    repo.journal(repo.worktree("x", "feat/x"), rec(at(minutes=600)))
    control = render(repo.root, "--active-window", "1d", where=tmp_path)  # контроль: окно шире возраста строки
    assert control.who_h2() == "Кто где · 1"
    page = render(repo.root, where=tmp_path)
    assert page.who_h2() == "Кто где · 0"  # секция пустая
    assert _notes(page) == [NOTE_1, NOTE_2]
    texts = [text_of(p) for p in page.need_who()["ps"]]
    assert texts == ["свежих сигналов нет (окно 6h)", NOTE_1, NOTE_2]


# =========================================================================== W6: экранирование, порядок в summary, чистота


def test_w6_branch_with_html_specials_is_escaped_in_raw_html_and_roundtrips_in_parse(tmp_path):
    branch = "feat/a&b'c"
    repo = Repo(tmp_path, {"plans/X/plan.md": plan_md(branch_line(branch))})
    wt = repo.worktree("x", branch)
    repo.fresh(wt)
    page = render(repo.root, where=tmp_path)
    assert 'data-active="feat/a&amp;b&#x27;c"' in page.raw
    assert "feat/a&b'c" not in page.raw
    chip = page.chips("X", "active")[0]
    assert chip["attrs"].get("data-active") == branch
    assert text_of(chip).startswith("в работе: feat/a&b'c · ")


def test_w6_special_branch_is_escaped_in_who_li_too_when_bound_by_plan_ref(tmp_path):
    """Привязка через plan.ref — изолирует экранирование от разбора шапки."""
    branch = "feat/a&b'c"
    repo = Repo(tmp_path, {"plans/X/plan.md": plan_md()})
    wt = repo.worktree("x", branch)
    repo.plan_ref(wt, "plans/X")
    repo.fresh(wt)
    page = render(repo.root, where=tmp_path)
    assert 'data-active="feat/a&amp;b&#x27;c"' in page.raw
    assert 'data-branch="feat/a&amp;b&#x27;c"' in page.raw
    li = page.who_li(wt)
    assert li["attrs"].get("data-branch") == branch
    assert text_of(li).startswith("feat/a&b'c → X · ")


def test_w6_active_chip_is_last_in_summary_after_the_after_chip(tmp_path):
    repo = Repo(
        tmp_path,
        {
            "plans/CTRL/plan.md": plan_md(),
            "plans/X/plan.md": plan_md(branch_line("feat/x"), "- **После:** CTRL"),
        },
    )
    repo.fresh(repo.worktree("x", "feat/x"))
    kinds = [c["attrs"].get("data-chip") for c in render(repo.root, where=tmp_path).chips("X")]
    assert "after" in kinds and kinds.count("active") == 1, kinds
    assert kinds[-1] == "active", kinds
    assert kinds.index("after") < kinds.index("active"), kinds


def test_w6_all_active_chips_trail_the_other_chips_when_a_plan_has_two_worktrees(tmp_path):
    repo = Repo(tmp_path, {"plans/CTRL/plan.md": plan_md(), "plans/X/plan.md": plan_md("- **После:** CTRL")})
    for name in ("a", "b"):
        wt = repo.worktree(name, f"feat/{name}")
        repo.plan_ref(wt, "plans/X")
        repo.fresh(wt)
    kinds = [c["attrs"].get("data-chip") for c in render(repo.root, where=tmp_path).chips("X")]
    assert kinds.count("active") == 2 and "after" in kinds, kinds
    assert kinds[-2:] == ["active", "active"], kinds


def test_w6_page_has_no_script_and_no_external_urls_while_who_has_content(tmp_path):
    repo, _ = ctrl_repo(tmp_path)
    repo.fresh(repo.worktree("lonely", "feat/lonely"))
    page = render(repo.root, where=tmp_path)
    assert_ctrl_chip(page)  # контроль: на странице есть и чип, и #who с записями
    assert len(page.who_lis()) == 2
    low = page.raw.lower()
    assert "<script" not in low
    assert "http://" not in low
    assert "https://" not in low


def test_w6_root_without_git_has_empty_who_and_no_active_chips_while_a_git_root_has_them(tmp_path):
    plain = tmp_path / "plain"
    (plain / "plans" / "X").mkdir(parents=True)
    (plain / "plans" / "X" / "plan.md").write_text(plan_md(branch_line("feat/x")), encoding="utf-8")
    (plain / "data").mkdir()
    (plain / "data" / "agent-journal.jsonl").write_text(json.dumps(rec(at(5))) + "\n", encoding="utf-8")
    page = render(plain, where=tmp_path, cwd=tmp_path)  # tmp_path лежит в чужом репозитории
    assert page.who_h2() == "Кто где · 0"
    assert page.active_chip_total == 0
    assert _notes(page) == [NOTE_1, NOTE_2]
    # контроль: тот же набор планов в настоящем репозитории даёт чип
    sibling = tmp_path / "git_side"
    sibling.mkdir()
    repo = Repo(sibling, {"plans/X/plan.md": plan_md(branch_line("feat/x"))})
    repo.fresh(repo.worktree("x", "feat/x"))
    ctrl = render(repo.root, where=tmp_path, cwd=tmp_path)
    assert [c["attrs"].get("data-active") for c in ctrl.chips("X", "active")] == ["feat/x"]
