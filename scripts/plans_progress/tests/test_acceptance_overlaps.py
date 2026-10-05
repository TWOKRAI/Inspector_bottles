# ruff: noqa: E501  -- литералы-фикстуры и ожидания в одну строку, форматтер их не переносит
"""Приёмка Task 5.6 — слепые тесты «Радара пересечений»: секция `#overlaps` и чип `overlap` на странице.

Источник: plans/2026-10-02_plans-progress-dashboard/tasks/5.6.md (DESIGN, ACCEPTANCE 1-13).
Реализацию тестер не видел; читал плану-код 5.5 (`collect_branches` и соседние функции), чтобы знать
границу вызовов git, и способ сборки git-фикстур в `test_acceptance_branches.py`.

Как устроено:
- Ходим через CLI в subprocess (timeout на вызов): `plans_progress.py --root R --now NOW --html F`.
  Исключение — строка 12 приёмки: `main([...])` в процессе под шпионом на `subprocess.run`, вызов — в
  daemon-потоке с дедлайном (зависший git не вешает набор).
- Фикстура — настоящий `git init` в tmp_path + `symbolic-ref HEAD refs/heads/main`; даты коммитера задаёт тест.
  Все ожидания — литералы. Страница пишется ВНЕ репозитория фикстуры (иначе `git status` грязнится).
- Каждый тест вида «секции нет / чипа нет» несёт КОНТРОЛЬ достижимости в той же фикстуре: пара независимых
  веток на другом файле, которая ОБЯЗАНА дать строку. Заглушка «секции не бывает» на таких тестах красная.
- Единственные тесты, которые зелены до реализации, — охранные (`test_guard_*`, `test_a09_*_exit_0`):
  они закрепляют прежнее поведение (`--json`, прежние секции, нет git -> exit 0).

Договорённости чтения (в тексте задачи неоднозначно; выбрано строгое чтение, см. отчёт):
- Порядок строк внутри `<ul>` в задаче не задан («файлы по пути»): тесты сравнивают строки как множество
  и порядок не фиксируют; порядок веток внутри `data-branches` — по имени (в строке 1 это видно литералом).
- Фикстура 4 в задаче не говорит, лежит ли `tasks/1.1.md` в `main`; здесь его создаёт `feat/a`.
- Базовый план `y` в строках 2-4 — контроль достижимости (его правят вторая и третья ветки пары-контроля).
- Чип разбирается только внутри `<summary>` `<details class="plan">`; секция — `<section id="overlaps">`.
"""

from __future__ import annotations

import importlib.util
import itertools
import json
import os
import shutil
import subprocess
import sys
import threading
from collections import Counter
from datetime import datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
PROGRESS = REPO_ROOT / "scripts" / "plans_progress" / "plans_progress.py"
CALL_TIMEOUT = 60
DEADLINE = 150  # секунд на вызов в потоке

NOW = "2026-10-03T12:00:00"
_NOW_DT = datetime.fromisoformat(NOW)

D1 = timedelta(days=1)
D4 = timedelta(days=4)
D10 = timedelta(days=10)
D20 = timedelta(days=20)

X = "plans/2026-01-01_x/plan.md"
XT = "plans/2026-01-01_x/tasks/1.1.md"
Y = "plans/2026-01-01_y.md"
XN, YN = "2026-01-01_x", "2026-01-01_y"  # имена планов на странице (data-plan / data-overlap-plan)

_page_counter = itertools.count(1)


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


def plan_md(title: str, note: str = "", status: str = "PENDING") -> str:
    """Однозадачный план: `## Порядок выполнения` и `- Task 1.1: a [<СТАТУС>]`; note — HTML-комментарий в хвосте."""
    text = f"# План {title}\n\n## Порядок выполнения\n\n- Task 1.1: a [{status}]\n"
    return text + (f"\n<!-- {note} -->\n" if note else "")


def body_for(rel: str, note: str) -> str:
    """Содержимое файла, различное для каждой ветки (`note`): так правка — настоящая, и коммит не пуст."""
    if rel.endswith("/plan.md"):
        return plan_md(rel.split("/")[-2], note)
    if rel == Y:
        return plan_md("y", note)
    if "/tasks/" in rel:
        return f"# Task 1.1: a\n\n**Статус:** PENDING\n\n<!-- {note} -->\n"
    return f"служебный файл\n<!-- {note} -->\n"


class Fx:
    """Настоящий git-репозиторий в `tmp_path/<name>`; главная ветка называется `main` (или иначе — `main=`)."""

    def __init__(self, tmp_path: Path, name: str = "repo", main: str = "main", extra: dict[str, str] | None = None):
        self.root = tmp_path / name
        self.root.mkdir(parents=True)
        self.base = tmp_path
        self.main = main
        self.git("init", "-q")
        self.git("symbolic-ref", "HEAD", f"refs/heads/{main}")
        self.git("config", "user.name", "tester")
        self.git("config", "user.email", "t@example.invalid")
        self.git("config", "core.autocrlf", "false")
        self.git("config", "commit.gpgsign", "false")
        self.write("NOTES.txt", "fixture")
        self.write(X, plan_md("x"))
        self.write(Y, plan_md("y"))
        for rel, text in (extra or {}).items():
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

    def commit(self, msg: str = "c", ago: timedelta = D1, cwd: Path | None = None) -> None:
        self.git("add", "-A", cwd=cwd)
        env = {"GIT_COMMITTER_DATE": stamp(ago), "GIT_AUTHOR_DATE": stamp(ago)}
        self.git("commit", "-q", "--allow-empty", "-m", msg, cwd=cwd, env=env)

    def checkout(self, name: str) -> None:
        self.git("switch", "-q", name)

    def touch(self, branch: str, *paths: str, frm: str | None = None, ago: timedelta = D1) -> None:
        """Ветка `branch` от `frm` (по умолчанию главной), один коммит с правкой `paths`; возврат на главную."""
        self.git("checkout", "-q", "-b", branch, f"refs/heads/{frm or self.main}")
        for rel in paths:
            self.write(rel, body_for(rel, branch))
        self.commit(f"edit {branch}", ago=ago)
        self.checkout(self.main)


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


def norm(text: str) -> str:
    return " ".join(text.split())


class Page(HTMLParser):
    """Страница: секции с id по порядку, секция `#overlaps` (заголовок, строки), чипы в `<summary>` планов."""

    def __init__(self, raw: str) -> None:
        super().__init__(convert_charrefs=True)
        self.raw = raw
        self.ids: list[str] = []  # id секций и details в порядке документа
        self.overlaps_open = False
        self.has_overlaps = False
        self.h2 = ""
        self.rows: list[dict[str, str | None]] = []
        self.plans: dict[str, list[dict]] = {}
        self._plan: str | None = None
        self._in_summary = False
        self._in_h2 = False
        self._chip: dict | None = None
        self.feed(raw)
        self.close()

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = (a.get("class") or "").split()
        if tag in ("section", "details") and a.get("id"):
            self.ids.append(a["id"])
        if tag == "section" and a.get("id") == "overlaps":
            self.overlaps_open = self.has_overlaps = True
        elif self.overlaps_open and tag == "h2":
            self._in_h2 = True
        elif self.overlaps_open and tag == "li":
            self.rows.append(a)
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
        if self._in_h2:
            self.h2 += data

    def handle_endtag(self, tag):
        if tag == "span" and self._chip is not None:
            self._chip = None
        elif tag == "summary":
            self._in_summary = False
        elif tag == "h2":
            self._in_h2 = False
        elif tag == "section" and self.overlaps_open:
            self.overlaps_open = False

    def row_set(self) -> list[tuple[str | None, str | None, str | None]]:
        """Строки секции как (data-path, data-overlap-plan, data-branches), отсортированные (порядок не закреплён)."""
        return sorted((r.get("data-path"), r.get("data-overlap-plan"), r.get("data-branches")) for r in self.rows)

    def chips(self, plan: str, kind: str | None = None) -> list[dict]:
        assert plan in self.plans, f"плана {plan!r} нет на странице; есть: {sorted(self.plans)}"
        got = self.plans[plan]
        if kind is not None:
            got = [c for c in got if c["attrs"].get("data-chip") == kind]
        return got

    def kinds(self, plan: str) -> list[str]:
        return [c["attrs"].get("data-chip") or "" for c in self.chips(plan)]

    def all_overlap_chips(self) -> list[tuple[str, dict]]:
        return [(p, c) for p, chips in self.plans.items() for c in chips if c["attrs"].get("data-chip") == "overlap"]


def render(root: Path, where: Path, *flags: str, env: dict[str, str] | None = None) -> Page:
    out = where / f"page_{next(_page_counter)}.html"  # вне репозитория фикстуры
    cp = run_cli(root, "--now", NOW, *flags, "--html", str(out), env=env)
    assert cp.returncode == 0, f"--html: {_out(cp)}"
    assert out.is_file(), f"страница не записана: {_out(cp)}"
    return Page(out.read_text(encoding="utf-8"))


def x_row(branches: str, path: str = X) -> tuple[str, str, str]:
    return (path, XN, branches)


def y_row(branches: str) -> tuple[str, str, str]:
    return (Y, YN, branches)


def add_control(fx: Fx, first: str = "feat/c", second: str = "feat/d") -> None:
    """Пара-контроль: две независимые свежие ветки правят `plans/2026-01-01_y.md` -> ОБЯЗАНА дать строку y."""
    fx.touch(first, Y)
    fx.touch(second, Y)


def assert_control(page: Page, branches: str = "feat/c,feat/d") -> None:
    assert y_row(branches) in page.row_set(), f"контроль достижимости: строки y нет; строки: {page.row_set()}"
    chips = page.chips(YN, "overlap")
    assert len(chips) == 1, f"контроль достижимости: у плана y нет чипа overlap: {page.kinds(YN)}"


# =========================================================================== строка 1: две независимые ветки — строка и чип


@pytest.fixture(scope="module")
def page1(tmp_path_factory) -> Page:
    """Фикстура 1: `feat/b` создана РАНЬШЕ `feat/a` (порядок в строке — по имени, не по созданию)."""
    base = tmp_path_factory.mktemp("a01")
    fx = Fx(base)
    fx.touch("feat/b", X)
    fx.touch("feat/a", X)
    return render(fx.root, base)


def test_a01_two_independent_branches_give_exactly_one_row_with_literal_attributes(page1):
    assert page1.has_overlaps, "секции <section id=overlaps> нет"
    assert page1.row_set() == [(X, XN, "feat/a,feat/b")]


def test_a01_heading_counts_files(page1):
    assert norm(page1.h2) == "Пересечения · 1"


def test_a01_plan_card_carries_one_overlap_chip_with_literal_text_and_count(page1):
    chips = page1.chips(XN, "overlap")
    assert len(chips) == 1, f"ждали один чип overlap у плана x: {page1.kinds(XN)}"
    chip = chips[0]
    assert norm(chip["text"]) == "⚠ пересечение, веток: 2"
    assert chip["attrs"].get("data-overlap") == "2"
    assert "chip" in (chip["attrs"].get("class") or "").split()


def test_a01_plan_without_overlap_has_no_chip_next_to_the_plan_with_one(page1):
    assert page1.chips(XN, "overlap"), "контроль достижимости: у плана x чип есть"
    assert page1.chips(YN, "overlap") == []


def test_a01_rows_do_not_use_the_data_plan_attribute(page1):
    assert page1.rows, "контроль достижимости: строка есть"
    assert all("data-plan" not in r for r in page1.rows), page1.rows


def test_a01_section_stands_right_after_who_and_other_sections_keep_their_order(page1):
    assert "overlaps" in page1.ids, "контроль достижимости: секция есть"
    without = [i for i in page1.ids if i != "overlaps"]
    assert without == ["priority", "who", "queue", "waiting", "unlisted", "archive"]
    assert page1.ids.index("overlaps") == page1.ids.index("who") + 1, page1.ids


# =========================================================================== строка 2: стек — не пересечение


def test_a02_stacked_branches_make_no_row_and_no_chip(tmp_path):
    fx = Fx(tmp_path)
    fx.touch("feat/a", X)
    fx.touch("feat/b", X, frm="feat/a")
    add_control(fx)
    page = render(fx.root, tmp_path)
    assert_control(page)
    assert page.row_set() == [y_row("feat/c,feat/d")], "x от стека в радар попасть не должен"
    assert page.chips(XN, "overlap") == []


def test_a02_branches_with_equal_tips_are_one_stack_not_two_independent_branches(tmp_path):
    fx = Fx(tmp_path)
    fx.touch("feat/a", X)
    fx.git("branch", "feat/b", "refs/heads/feat/a")  # та же вершина: у feat/b нет своих правок относительно feat/a
    add_control(fx)
    page = render(fx.root, tmp_path)
    assert_control(page)
    assert page.row_set() == [y_row("feat/c,feat/d")]
    assert page.chips(XN, "overlap") == []


# =========================================================================== строка 3: разные файлы


def test_a03_branches_changing_different_plan_files_make_no_row_for_them(tmp_path):
    fx = Fx(tmp_path)
    fx.touch("feat/a", X)
    fx.touch("feat/b", Y)
    fx.touch("feat/c", Y)  # контроль: b и c правят один файл y
    page = render(fx.root, tmp_path)
    assert_control(page, "feat/b,feat/c")
    assert page.row_set() == [y_row("feat/b,feat/c")], "feat/a (только x) в строку y попасть не должна"
    assert page.chips(XN, "overlap") == []


# =========================================================================== строка 4: разные файлы одного плана


def test_a04_two_different_files_of_one_plan_make_no_row(tmp_path):
    fx = Fx(tmp_path)
    fx.touch("feat/a", XT)
    fx.touch("feat/b", X)
    add_control(fx)
    page = render(fx.root, tmp_path)
    assert_control(page)
    assert page.row_set() == [y_row("feat/c,feat/d")], "пересечение по плану, а не по файлу — ложное"
    assert page.chips(XN, "overlap") == []


# =========================================================================== строка 5: служебные файлы не файлы плана


def test_a05_queue_order_md_is_not_a_plan_file_one_row_for_the_plan(tmp_path):
    fx = Fx(tmp_path)
    for name in ("feat/a", "feat/b"):
        fx.touch(name, "plans/queue/ORDER.md", X)
    page = render(fx.root, tmp_path)
    assert page.row_set() == [x_row("feat/a,feat/b")]
    assert norm(page.h2) == "Пересечения · 1"


def test_a05_readme_and_queue_md_of_plans_are_not_plan_files_either(tmp_path):
    fx = Fx(tmp_path)
    for name in ("feat/a", "feat/b"):
        fx.touch(name, "plans/README.md", "plans/QUEUE.md", "plans/queue/ORDER.md", X)
    page = render(fx.root, tmp_path)
    assert page.row_set() == [x_row("feat/a,feat/b")], "служебные файлы дали строки"
    assert norm(page.h2) == "Пересечения · 1"


# =========================================================================== строка 6: окно свежести


@pytest.fixture
def stale_b(tmp_path) -> Fx:
    fx = Fx(tmp_path)
    fx.touch("feat/a", X)
    fx.touch("feat/b", X, ago=D4)  # на 4 суток раньше NOW
    add_control(fx)
    return fx


def test_a06_branch_older_than_the_default_window_does_not_take_part(stale_b, tmp_path):
    page = render(stale_b.root, tmp_path)
    assert_control(page)
    assert page.row_set() == [y_row("feat/c,feat/d")]
    assert page.chips(XN, "overlap") == []


def test_a06_wider_branch_window_brings_the_old_branch_back(stale_b, tmp_path):
    page = render(stale_b.root, tmp_path, "--branch-window", "5d")
    assert page.row_set() == [x_row("feat/a,feat/b"), y_row("feat/c,feat/d")]
    assert page.chips(XN, "overlap")[0]["attrs"].get("data-overlap") == "2"


# =========================================================================== строка 7: три ветки, стек внутри


@pytest.fixture(scope="module")
def fx7(tmp_path_factory) -> Fx:
    """a и c от main, b от a; все три правят plan.md своими коммитами; корень на main."""
    base = tmp_path_factory.mktemp("a07")
    fx = Fx(base)
    fx.touch("feat/a", X)
    fx.touch("feat/c", X)
    fx.touch("feat/b", X, frm="feat/a")
    return fx


def test_a07_row_lists_all_three_branches_by_name(fx7, tmp_path):
    page = render(fx7.root, tmp_path)
    assert page.row_set() == [x_row("feat/a,feat/b,feat/c")]


def test_a07_chip_counts_three_branches(fx7, tmp_path):
    chips = render(fx7.root, tmp_path).chips(XN, "overlap")
    assert len(chips) == 1
    assert norm(chips[0]["text"]) == "⚠ пересечение, веток: 3"
    assert chips[0]["attrs"].get("data-overlap") == "3"


def test_a07_stack_child_pairs_with_an_independent_branch_and_stack_parent_that_left_the_file_is_not_listed(tmp_path):
    fx = Fx(tmp_path)
    fx.touch("feat/a", Y)  # родитель стека правит только y
    fx.touch("feat/b", X, frm="feat/a")  # ребёнок правит x
    fx.touch("feat/c", X)  # независимая ветка правит x
    page = render(fx.root, tmp_path)
    assert page.row_set() == [x_row("feat/b,feat/c")], "feat/a файла x не трогала — в строке ей не место"


# =========================================================================== строка 8: ветка корня участвует


def test_a08_root_on_feat_a_takes_part_in_the_radar(tmp_path):
    fx = Fx(tmp_path)
    fx.touch("feat/a", X)
    fx.touch("feat/b", X)
    fx.checkout("feat/a")
    page = render(fx.root, tmp_path)
    assert page.row_set() == [x_row("feat/a,feat/b")]


def test_a08_window_does_not_apply_to_the_root_branch(tmp_path):
    fx = Fx(tmp_path)
    fx.touch("feat/a", X, ago=D10)  # вершина старше окна 3d
    fx.touch("feat/b", X)
    fx.checkout("feat/a")
    page = render(fx.root, tmp_path)
    assert page.row_set() == [x_row("feat/a,feat/b")]


def test_a08_root_branch_that_did_not_touch_the_file_is_not_listed_and_gives_no_row(tmp_path):
    fx = Fx(tmp_path)
    fx.touch("feat/a", Y)  # ветка корня правит y
    fx.touch("feat/b", X)  # b правит x: в одиночку строки не даёт
    fx.touch("feat/c", Y)  # контроль: a и c правят один файл y
    fx.checkout("feat/a")
    page = render(fx.root, tmp_path)
    assert_control(page, "feat/a,feat/c")
    assert page.row_set() == [y_row("feat/a,feat/c")]
    assert page.chips(XN, "overlap") == []


def test_a08_stale_non_root_branch_still_does_not_take_part_when_root_is_on_a_branch(tmp_path):
    fx = Fx(tmp_path)
    fx.touch("feat/a", X)
    fx.touch("feat/b", X, ago=D10)  # b — не ветка корня: окно к ней применяется
    fx.touch("feat/c", Y)
    fx.touch("feat/d", Y)
    fx.checkout("feat/a")
    page = render(fx.root, tmp_path)
    assert_control(page)
    assert page.row_set() == [y_row("feat/c,feat/d")]
    assert page.chips(XN, "overlap") == []


# =========================================================================== строка 9: нет git, подкаталог, нет main


def _build_with_pair(tmp_path: Path, main: str = "main") -> Fx:
    fx = Fx(tmp_path, main=main)
    fx.touch("feat/a", X)
    fx.touch("feat/b", X)
    return fx


def test_a09_directory_without_git_gives_no_section_and_no_chip(tmp_path):
    fx = _build_with_pair(tmp_path)
    control = render(fx.root, tmp_path)
    assert control.row_set() == [x_row("feat/a,feat/b")], "контроль достижимости: та же фикстура под git даёт строку"
    nogit = tmp_path / "nogit"
    shutil.copytree(fx.root / "plans", nogit / "plans")
    env = {"GIT_CEILING_DIRECTORIES": str(nogit.parent)}
    probe = subprocess.run(
        ["git", "rev-parse", "--git-dir"], cwd=str(nogit), capture_output=True, env=_env(env), timeout=CALL_TIMEOUT
    )
    assert probe.returncode != 0, "предусловие: каталог вне любого git"
    page = render(nogit, tmp_path, env=env)
    assert XN in page.plans, "страница собрана и план x на ней есть"
    assert not page.has_overlaps and page.rows == []
    assert page.all_overlap_chips() == []


def test_a09_root_in_a_repository_subdirectory_gives_no_section_and_no_chip(tmp_path):
    sub = {"sub/" + X: plan_md("x"), "sub/" + Y: plan_md("y")}
    fx = Fx(tmp_path, extra=sub)
    for name in ("feat/a", "feat/b"):
        fx.touch(name, X, "sub/" + X)
    control = render(fx.root, tmp_path)
    assert control.row_set() == [x_row("feat/a,feat/b")], "контроль достижимости: от верхнего каталога строка есть"
    page = render(fx.root / "sub", tmp_path)
    assert XN in page.plans
    assert not page.has_overlaps and page.rows == []
    assert page.all_overlap_chips() == []


def test_a09_repository_without_main_gives_no_section_until_main_exists(tmp_path):
    fx = _build_with_pair(tmp_path, main="trunk")
    page = render(fx.root, tmp_path)
    assert XN in page.plans
    assert not page.has_overlaps and page.rows == []
    assert page.all_overlap_chips() == []
    fx.git("branch", "-m", "trunk", "main")
    again = render(fx.root, tmp_path)
    assert again.row_set() == [x_row("feat/a,feat/b")], "контроль: с веткой main строка появляется"


@pytest.mark.parametrize("case", ["nogit", "subdir", "nomain"])
def test_a09_degenerate_roots_exit_0_and_write_the_page(tmp_path, case):
    """Охранный (зелёный до реализации): ни один из случаев не роняет страницу."""
    if case == "nomain":
        fx = _build_with_pair(tmp_path, main="trunk")
        root, env = fx.root, None
    elif case == "subdir":
        fx = Fx(tmp_path, extra={"sub/" + X: plan_md("x")})
        root, env = fx.root / "sub", None
    else:
        root = tmp_path / "nogit"
        (root / "plans" / "2026-01-01_x").mkdir(parents=True)
        (root / "plans" / "2026-01-01_x" / "plan.md").write_bytes(plan_md("x").encode("utf-8"))
        env = {"GIT_CEILING_DIRECTORIES": str(root.parent)}
    out = tmp_path / "out.html"
    cp = run_cli(root, "--now", NOW, "--html", str(out), env=env)
    assert cp.returncode == 0, _out(cp)
    assert out.is_file(), _out(cp)


# =========================================================================== строка 10: --json не меняется


def _json(root: Path) -> list[dict]:
    cp = run_cli(root, "--json", "--now", NOW)
    assert cp.returncode == 0, _out(cp)
    return json.loads(cp.stdout)


def _all_keys(value) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in _all_keys(v)}
    if isinstance(value, list):
        return {k for v in value for k in _all_keys(v)}
    return set()


def test_a10_json_keys_are_the_same_with_and_without_branches_and_have_no_overlap_key(tmp_path):
    """Охранный (зелёный до реализации): ключей `--json` не добавляем (его читает Атлас 1.3a)."""
    with_br = Fx(tmp_path, name="with_branches")
    with_br.touch("feat/a", X)
    with_br.touch("feat/b", X)
    without = Fx(tmp_path, name="without_branches")
    got, base = _json(with_br.root), _json(without.root)
    assert [r["plan"] for r in got] == [r["plan"] for r in base]
    assert [list(r) for r in got] == [list(r) for r in base]
    assert [e["branch"] for r in got if r["plan"].startswith(XN) for e in r["branches"]] == ["feat/a", "feat/b"], (
        "контроль достижимости: ветки в `--json` считаются"
    )
    assert not [k for k in _all_keys(got) if "overlap" in k.lower()], _all_keys(got)


def test_a10_text_list_and_who_do_not_mention_overlaps(tmp_path):
    """Охранный (зелёный до реализации): прочие режимы без пересечений."""
    fx = Fx(tmp_path)
    fx.touch("feat/a", X)
    fx.touch("feat/b", X)
    text = run_cli(fx.root, "--now", NOW)
    who = run_cli(fx.root, "--who", "--now", NOW)
    assert text.returncode == 0 and who.returncode == 0, (_out(text), _out(who))
    low = (text.stdout + who.stdout).lower()
    assert "overlap" not in low and "пересеч" not in low
    assert list(json.loads(who.stdout)) == ["active", "orphans"]


def test_guard_page_without_overlaps_keeps_the_sections_in_their_old_order(tmp_path):
    """Охранный (зелёный до реализации): ни одной пары — секции `overlaps` нет, порядок прежний."""
    fx = Fx(tmp_path)
    fx.touch("feat/a", X)
    page = render(fx.root, tmp_path)
    assert page.ids == ["priority", "who", "queue", "waiting", "unlisted", "archive"]


# =========================================================================== строка 11: порядок чипов


def test_a11_chip_order_branch_then_overlap_then_active(tmp_path):
    fx = Fx(tmp_path)
    wt = fx.base / "wt_a"
    fx.git("worktree", "add", "-q", "-b", "feat/a", str(wt), "main")
    fx.write(X, plan_md("x", status="DONE"), cwd=wt)  # Task 1.1 -> DONE: у ветки другие числа, чем в main
    fx.commit("close 1.1\n\nRefs: plans/2026-01-01_x/plan.md", cwd=wt)
    journal = {
        "ts": "2026-10-03T11:55:00", "event": "SubagentStart", "agent_type": "developer", "agent_id": "a1",
        "session_id": "s1", "source": "hook", "cwd": "x", "branch": "x", "tail": "",
    }  # fmt: skip
    (wt / "data").mkdir()
    (wt / "data" / "agent-journal.jsonl").write_bytes((json.dumps(journal) + "\n").encode("utf-8"))
    fx.touch("feat/b", X)
    page = render(fx.root, tmp_path)
    kinds = page.kinds(XN)
    assert "branch" in kinds and "active" in kinds, f"предусловие фикстуры (чипы 5.5): {kinds}"
    assert "overlap" in kinds, f"нет чипа overlap: {kinds}"
    assert kinds.index("branch") < kinds.index("overlap") < kinds.index("active"), kinds


# =========================================================================== строка 12: вызовы git


FIVE = ("diff", "rev-list", "merge-base", "for-each-ref", "archive")


def _load_module():
    name = "plans_progress_overlaps_under_test"
    spec = importlib.util.spec_from_file_location(name, PROGRESS)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # @dataclass ищет модуль по имени
    spec.loader.exec_module(module)
    return module


def _with_deadline(fn):
    box: dict = {}

    def target():
        try:
            box["result"] = fn()
        except BaseException as exc:  # noqa: BLE001 — перебросим в потоке теста
            box["error"] = exc

    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join(DEADLINE)
    assert not t.is_alive(), f"вызов завис дольше {DEADLINE} с"
    if "error" in box:
        raise box["error"]
    return box.get("result")


def _spied(fn) -> Counter:
    """Выполняет `fn` под шпионом на `subprocess.run` (граница ОС) -> Counter по глаголам git из FIVE."""
    calls: list[list[str]] = []
    real = subprocess.run

    def spy(cmd, *a, **kw):
        if isinstance(cmd, (list, tuple)) and len(cmd) > 1 and cmd[0] == "git":
            calls.append(list(cmd))
        return real(cmd, *a, **kw)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(subprocess, "run", spy)
        _with_deadline(fn)
    seen = Counter(c[1] for c in calls)
    return Counter({verb: seen[verb] for verb in FIVE})


@pytest.fixture(scope="module")
def a12(fx7, tmp_path_factory):
    mod = _load_module()
    plans = mod.discover(fx7.root)
    once = _spied(lambda: mod.collect_branches(fx7.root, plans, _NOW_DT, timedelta(days=3)))
    out = tmp_path_factory.mktemp("a12") / "page.html"
    full = _spied(lambda: mod.main(["--root", str(fx7.root), "--now", NOW, "--html", str(out)]))
    assert out.is_file(), "main(--html) страницу не записал"
    return once, full, Page(out.read_text(encoding="utf-8"))


def test_a12_main_html_makes_as_many_git_calls_as_one_collect_branches(a12):
    """Охранный по счёту (зелёный до реализации): радар не добавляет проходов по веткам."""
    once, full, _page = a12
    assert once["for-each-ref"] == 1 and once["rev-list"] >= 3 and once["diff"] >= 3, f"шпион ничего не видит: {once}"
    assert full == once, (dict(once), dict(full))


def test_a12_page_built_in_that_same_run_has_the_row_for_fixture_7(a12):
    """Контроль достижимости счёта: тот же прогон `main(--html)` обязан дать строку (иначе счёт равен «ничего не делали»)."""
    _once, _full, page = a12
    assert page.row_set() == [x_row("feat/a,feat/b,feat/c")]


# =========================================================================== строка 13: репозиторий не меняется


def _snapshot(fx: Fx) -> dict:
    return {
        "refs": fx.git("for-each-ref", "--format=%(refname) %(objectname)"),
        "head": fx.git("symbolic-ref", "HEAD"),
        "status": fx.git("status", "--porcelain", "--untracked-files=all", "--ignored"),
        "stash": fx.git("stash", "list"),
        "worktrees": fx.git("worktree", "list", "--porcelain"),
    }


def test_a13_branch_tips_and_status_are_the_same_after_the_run_and_the_row_was_built(tmp_path):
    fx = Fx(tmp_path)
    fx.touch("feat/a", X)
    fx.touch("feat/c", X)
    fx.touch("feat/b", X, frm="feat/a")
    before = _snapshot(fx)
    assert "feat/a" in before["refs"] and before["status"] == "", before
    page = render(fx.root, tmp_path)
    assert page.row_set() == [x_row("feat/a,feat/b,feat/c")], "контроль достижимости: радар отработал"
    assert _snapshot(fx) == before


# =========================================================================== закрепления DESIGN вне 13 строк приёмки


def test_d_chip_counts_distinct_branches_over_all_files_of_the_plan_and_heading_counts_files(tmp_path):
    fx = Fx(tmp_path)
    fx.touch("feat/a", X)
    fx.touch("feat/b", X, XT)
    fx.touch("feat/c", XT)
    page = render(fx.root, tmp_path)
    assert page.row_set() == [x_row("feat/a,feat/b"), x_row("feat/b,feat/c", XT)]
    assert norm(page.h2) == "Пересечения · 2"
    chips = page.chips(XN, "overlap")
    assert len(chips) == 1
    assert norm(chips[0]["text"]) == "⚠ пересечение, веток: 3", "три РАЗНЫЕ ветки, а не 2 + 2"
    assert chips[0]["attrs"].get("data-overlap") == "3"


def test_d_each_plan_gets_its_own_chip_with_its_own_count(tmp_path):
    fx = Fx(tmp_path)
    fx.touch("feat/a", X, Y)
    fx.touch("feat/b", X, Y)
    fx.touch("feat/c", Y)
    page = render(fx.root, tmp_path)
    assert page.row_set() == [x_row("feat/a,feat/b"), y_row("feat/a,feat/b,feat/c")]
    assert [c["attrs"].get("data-overlap") for c in page.chips(XN, "overlap")] == ["2"]
    assert [c["attrs"].get("data-overlap") for c in page.chips(YN, "overlap")] == ["3"]
    assert norm(page.h2) == "Пересечения · 2"


def test_d_file_of_an_archived_plan_counts_and_the_chip_is_on_the_archived_card(tmp_path):
    arch = "plans/_archive/2026-Q3/2026-01-01_z/plan.md"
    fx = Fx(tmp_path, extra={arch: plan_md("z")})
    for name in ("feat/a", "feat/b"):
        fx.touch(name, arch)
    page = render(fx.root, tmp_path)
    assert page.row_set() == [(arch, "2026-01-01_z", "feat/a,feat/b")]
    assert [norm(c["text"]) for c in page.chips("2026-01-01_z", "overlap")] == ["⚠ пересечение, веток: 2"]


def test_d_plan_that_exists_only_in_branches_is_not_in_the_radar(tmp_path):
    """Правило 1: план обязан быть на диске `--root`; два новых плана с одним путём — вне радара (OUT OF SCOPE)."""
    fx = Fx(tmp_path)
    new = "plans/2026-02-02_new/plan.md"
    for name in ("feat/a", "feat/b"):
        fx.touch(name, new)
    fx.touch("feat/c", X)
    fx.touch("feat/d", X)  # контроль: пара на плане, который на диске есть
    page = render(fx.root, tmp_path)
    assert page.row_set() == [x_row("feat/c,feat/d")], "плана `new` нет на диске корня — строки быть не должно"


def test_d_branch_names_are_html_escaped_in_the_row(tmp_path):
    fx = Fx(tmp_path)
    fx.touch("feat/a&b'c", X)
    fx.touch("feat/z", X)
    out = tmp_path / "esc.html"
    cp = run_cli(fx.root, "--now", NOW, "--html", str(out))
    assert cp.returncode == 0, _out(cp)
    page = Page(out.read_text(encoding="utf-8"))
    assert page.row_set() == [x_row("feat/a&b'c,feat/z")]
    assert "feat/a&b" not in page.raw, "сырой & в странице: значение не прошло через экранирование"
    assert "a&b'c" not in page.raw, "сырая одинарная кавычка в странице"
