# ruff: noqa: E501  -- литералы-фикстуры и ожидания в одну строку
"""Тесты автора на опасности радара пересечений (Task 5.6: `run_branch_pass`, `find_overlaps`, `#overlaps`, чип).

Что может сломаться в этом механизме (по устройству, а не по списку приёмки; приёмку пишет независимый тестер,
`test_acceptance_overlaps.py`, только через CLI):
- ветка влила свежий `main`: её `touched` не должен нести чужие правки `main` — иначе «пересечение» с веткой,
  которая просто тронула файл, изменённый в `main`;
- удаление и переименование файла плана: `diff --no-renames` даёт оба пути; удаление против правки — настоящий
  конфликт слияния, новый путь переименования сам по себе пересечения не даёт;
- ветка корня и её потомок: потомок со стеком — не пересечение; независимая третья ветка делает строку из всех трёх;
- пустое множество `main..<ветка>` (git не ответил): ветка не участвует, остальные пары живы, исключения нет;
- ветка без merge-base (несвязанная история) не участвует и ничего не роняет;
- экранирование: имена веток, планов и путей идут через `_e`, ни одно значение не вырывается из атрибута;
- чип привязан к карточке по `Plan.rel`, а не по имени: живой и архивный план с одним именем не делят чип;
- стоимость — число вызовов git на границе ОС: корень на устаревшей ветке стоит +1 `merge-base` и +1 `diff`,
  второго прохода по веткам нет (`for-each-ref` один), корень не попадает в числа 5.5 и не стоит ни одного `archive`.

Модуль импортируется напрямую; git настоящий (фикстура — `git init` в tmp_path), подменяется только
`subprocess.run` вокруг вызова (шпион) и `_own_commits` (сбой `git rev-list` для одной ветки).
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

import pytest

_MOD_PATH = Path(__file__).resolve().parents[1] / "plans_progress.py"
_spec = importlib.util.spec_from_file_location("plans_progress_overlaps_author_under_test", _MOD_PATH)
pp = importlib.util.module_from_spec(_spec)
sys.modules["plans_progress_overlaps_author_under_test"] = pp
_spec.loader.exec_module(pp)

NOW = datetime(2026, 10, 3, 12, 0, 0)
WINDOW = timedelta(days=3)
D1 = timedelta(days=1)
D10 = timedelta(days=10)
D20 = timedelta(days=20)

X = "plans/2026-01-01_x/plan.md"
XT = "plans/2026-01-01_x/tasks/1.1.md"
Y = "plans/2026-01-01_y.md"


def _env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_") or k == "GIT_CEILING_DIRECTORIES"}
    env["PYTHONUTF8"] = "1"
    env.update(extra or {})
    return env


def stamp(ago: timedelta) -> str:
    return f"{int((NOW - ago).timestamp())} +0000"


def plan_text(note: str = "") -> str:
    return "# План\n\n## Порядок выполнения\n\n- Task 1.1: a [PENDING]\n" + (f"\n<!-- {note} -->\n" if note else "")


class Repo:
    def __init__(self, tmp_path: Path) -> None:
        self.root = tmp_path / "repo"
        self.root.mkdir()
        self.git("init", "-q", "-b", "main")
        for key, value in (
            ("user.name", "t"),
            ("user.email", "t@example.invalid"),
            ("core.autocrlf", "false"),
            ("commit.gpgsign", "false"),
        ):
            self.git("config", key, value)
        self.write("NOTES.txt", "x")
        self.write(X, plan_text())
        self.write(XT, "# Task 1.1\n")
        self.write(Y, plan_text())
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

    def touch(self, branch: str, *paths: str, frm: str = "main", ago: timedelta = D1) -> None:
        """Ветка от `frm`, один коммит с правкой `paths` (содержимое разное у каждой ветки); возврат на `main`."""
        self.git("checkout", "-q", "-b", branch, f"refs/heads/{frm}")
        for rel in paths:
            self.write(rel, plan_text(branch) if rel.endswith(".md") and "tasks" not in rel else f"# {branch}\n")
        self.commit(f"edit {branch}", ago)
        self.git("checkout", "-q", "main")

    def radar(self, window: timedelta = WINDOW) -> list[tuple[str, tuple[str, ...]]]:
        plans = pp.discover(self.root)
        found = pp.find_overlaps(self.root, plans, pp.run_branch_pass(self.root, NOW, window))
        return [(o.path, o.branches) for o in found]


@pytest.fixture
def repo(tmp_path) -> Repo:
    return Repo(tmp_path)


# =========================================================================== влитый main


def test_branch_that_merged_fresh_main_does_not_overlap_through_the_file_main_changed(repo):
    """`a` влила `main`, в котором кто-то правил X; `b` правит X. Файл X `a` не трогала — строки нет."""
    repo.touch("feat/a", Y)
    repo.git("checkout", "-q", "main")
    repo.write(X, plan_text("main edit"))
    repo.commit("main edits x")
    repo.git("checkout", "-q", "feat/a")
    repo.git("merge", "-q", "--no-edit", "main")
    repo.git("checkout", "-q", "main")
    repo.touch("feat/b", X)
    assert repo.radar() == []


def test_stack_child_of_a_branch_that_merged_main_keeps_only_its_own_files(repo):
    """Родитель `a` влил `main` (правки X); ребёнок `c` от `a` правит только Y; независимая `b` правит X и Y."""
    repo.touch("feat/a", XT)
    repo.git("checkout", "-q", "main")
    repo.write(X, plan_text("main edit"))
    repo.commit("main edits x")
    repo.git("checkout", "-q", "feat/a")
    repo.git("merge", "-q", "--no-edit", "main")
    repo.git("checkout", "-q", "main")
    repo.touch("feat/c", Y, frm="feat/a")
    repo.touch("feat/b", X, Y)
    assert repo.radar() == [(Y, ("feat/b", "feat/c"))]


def test_stack_child_that_merged_main_itself_does_not_inherit_main_edits_as_its_own(repo):
    """Ребёнок `c` от `a` сам влил `main` (в `main` правили X): diff от вершины родителя несёт X, правки `c` — только Y.
    `b` правит X и Y: общий с `c` файл один — Y. X у `c` — чужая правка `main`, строки по X быть не должно."""
    repo.touch("feat/a", XT)
    repo.touch("feat/c", Y, frm="feat/a")
    repo.git("checkout", "-q", "main")
    repo.write(X, plan_text("main edit"))
    repo.commit("main edits x")
    repo.git("checkout", "-q", "feat/c")
    repo.git("merge", "-q", "--no-edit", "main")
    repo.git("checkout", "-q", "main")
    repo.touch("feat/b", X, Y)
    assert repo.radar() == [(Y, ("feat/b", "feat/c"))]


def test_branch_stacked_with_every_other_toucher_is_not_listed_even_when_the_others_are_independent(repo):
    """`b` и `c` — дети `a`, `b` и `c` друг другу независимы; все три правят X. У `a` независимой пары нет:
    она в строку не входит (её правка X идёт в слияние вместе с потомками), строка — `b,c`."""
    repo.touch("feat/a", X)
    repo.touch("feat/b", X, frm="feat/a")
    repo.touch("feat/c", X, frm="feat/a")
    assert repo.radar() == [(X, ("feat/b", "feat/c"))]


# =========================================================================== удаление и переименование


def test_delete_against_edit_of_a_plan_file_is_an_overlap(repo):
    repo.git("checkout", "-q", "-b", "feat/a", "main")
    (repo.root / XT).unlink()
    repo.commit("a removes task file")
    repo.git("checkout", "-q", "main")
    repo.touch("feat/b", XT)
    assert repo.radar() == [(XT, ("feat/a", "feat/b"))]


def test_rename_counts_the_old_path_but_the_new_path_alone_is_no_overlap(repo):
    new = "plans/2026-01-01_x/tasks/1.1-renamed.md"
    repo.git("checkout", "-q", "-b", "feat/a", "main")
    repo.git("mv", XT, new)
    repo.commit("a renames task file")
    repo.git("checkout", "-q", "main")
    repo.touch("feat/b", XT)
    assert repo.radar() == [(XT, ("feat/a", "feat/b"))], "строка только по старому пути; новый путь трогала одна ветка"


# =========================================================================== ветка корня


def test_root_branch_child_is_a_stack_and_gives_no_row_until_an_independent_branch_appears(repo):
    repo.touch("feat/a", X)
    repo.touch("feat/b", X, frm="feat/a")
    repo.git("checkout", "-q", "feat/a")
    assert repo.radar() == [], "корень на feat/a, feat/b — её потомок: стек"
    repo.touch("feat/c", X)
    repo.git("checkout", "-q", "feat/a")
    assert repo.radar() == [(X, ("feat/a", "feat/b", "feat/c"))]


def test_stale_root_branch_takes_part_but_is_not_in_the_5_5_numbers_and_costs_no_archive(repo):
    repo.touch("feat/old", X, ago=D10)
    repo.touch("feat/b", X)
    repo.git("checkout", "-q", "feat/old")
    plans = pp.discover(repo.root)
    calls = _spy(lambda: pp.collect_branches(repo.root, plans, NOW, WINDOW))
    assert [e["branch"] for p in plans for e in p.branches] == ["feat/b"], "ветка корня в числа 5.5 не выводится"
    assert Counter(c[1] for c in calls)["archive"] == 2, "архивы: вершина feat/b и база; вершина корня не выгружается"
    assert repo.radar() == [(X, ("feat/b", "feat/old"))], "окно к ветке корня не применяется"


def test_root_on_a_stale_branch_costs_one_merge_base_and_one_diff_more_than_root_on_main(repo):
    repo.touch("feat/old", X, ago=D10)
    repo.touch("feat/a", X)
    repo.touch("feat/b", X)
    on_main = Counter(c[1] for c in _spy(lambda: pp.run_branch_pass(repo.root, NOW, WINDOW)))
    repo.git("checkout", "-q", "feat/old")
    on_old = Counter(c[1] for c in _spy(lambda: pp.run_branch_pass(repo.root, NOW, WINDOW)))
    assert (on_main["for-each-ref"], on_main["rev-list"], on_main["merge-base"], on_main["diff"]) == (1, 2, 2, 2)
    assert (on_old["for-each-ref"], on_old["rev-list"], on_old["merge-base"], on_old["diff"]) == (1, 3, 3, 3)


def test_main_html_runs_the_branch_pass_once_also_when_the_root_is_on_a_branch(repo, tmp_path):
    repo.touch("feat/a", X)
    repo.touch("feat/b", X)
    repo.git("checkout", "-q", "feat/a")
    out = tmp_path / "page.html"
    calls = _spy(lambda: pp.main(["--root", str(repo.root), "--now", NOW.isoformat(), "--html", str(out)]))
    seen = Counter(c[1] for c in calls)
    assert seen["for-each-ref"] == 1, f"второй проход по веткам: {seen}"
    assert 'data-branches="feat/a,feat/b"' in out.read_text(encoding="utf-8")


def test_json_mode_does_not_run_the_radar_but_the_numbers_stay(repo, capsys):
    repo.touch("feat/a", X)
    repo.touch("feat/b", X)
    assert pp.main(["--root", str(repo.root), "--now", NOW.isoformat(), "--json"]) == 0
    out = capsys.readouterr().out
    assert '"branch": "feat/a"' in out and "overlap" not in out.lower()


# =========================================================================== сбой git, нет merge-base


def test_branch_whose_own_set_is_unavailable_does_not_take_part_and_the_rest_still_pair(repo, monkeypatch):
    for name in ("feat/a", "feat/b", "feat/c"):
        repo.touch(name, X)
    real = pp._own_commits
    monkeypatch.setattr(pp, "_own_commits", lambda root, branch: set() if branch == "feat/a" else real(root, branch))
    assert repo.radar() == [(X, ("feat/b", "feat/c"))]


def test_all_own_sets_unavailable_give_no_overlaps_and_no_exception(repo, monkeypatch):
    repo.touch("feat/a", X)
    repo.touch("feat/b", X)
    monkeypatch.setattr(pp, "_own_commits", lambda root, branch: set())
    assert repo.radar() == []


def test_unrelated_history_branch_has_no_merge_base_and_does_not_take_part(repo):
    repo.touch("feat/a", X)
    repo.touch("feat/b", X)
    repo.git("checkout", "-q", "--orphan", "feat/orphan")
    repo.git("rm", "-rq", "--cached", ".")
    repo.write(X, plan_text("orphan"))
    repo.commit("orphan root")
    repo.git("checkout", "-q", "main")
    assert repo.radar() == [(X, ("feat/a", "feat/b"))]


def test_no_git_gives_no_overlaps(tmp_path, monkeypatch):
    plain = tmp_path / "plain"
    (plain / "plans" / "P").mkdir(parents=True)
    (plain / "plans" / "P" / "plan.md").write_bytes(plan_text().encode("utf-8"))
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    plans = pp.discover(plain)
    assert pp.find_overlaps(plain, plans, pp.run_branch_pass(plain, NOW, WINDOW)) == []
    assert pp.find_overlaps(plain, plans, None) == []


# =========================================================================== страница: экранирование и привязка чипа


def _plan(name: str, rel: str, archived: bool = False):
    return pp.Plan(name, rel, archived, tasks=[pp.Task("1.1", "a", "pending")])


def test_overlap_values_are_escaped_in_row_and_section_heading_counts_rows():
    evil_plan = 'p"><script>alert(1)</script>'
    overlap = pp.Overlap('plans/a"b&c.md', evil_plan, "plans/a.md", ("f/<x>", "f/y'z"))
    page = pp.to_html([_plan("a", "plans/a.md")], [], Path("."), overlaps=[overlap])
    assert "<script>" not in page and "<x>" not in page
    assert 'data-path="plans/a&quot;b&amp;c.md"' in page
    assert 'data-branches="f/&lt;x&gt;,f/y&#x27;z"' in page
    assert "<h2>Пересечения · 1</h2>" in page


def test_no_overlaps_no_section_and_no_chip():
    page = pp.to_html([_plan("a", "plans/a.md")], [], Path("."), overlaps=[])
    assert 'id="overlaps"' not in page and 'data-chip="overlap"' not in page


def test_rows_are_sorted_by_path_and_the_chip_counts_distinct_branches_per_plan():
    rows = [
        pp.Overlap("plans/a/z.md", "a", "plans/a", ("f/1", "f/2")),
        pp.Overlap("plans/a/b.md", "a", "plans/a", ("f/2", "f/3")),
    ]
    page = pp.to_html([_plan("a", "plans/a")], [], Path("."), overlaps=rows)
    assert page.index('data-path="plans/a/b.md"') < page.index('data-path="plans/a/z.md"')
    assert page.count('data-chip="overlap"') == 1 and 'data-overlap="3">⚠ пересечение, веток: 3<' in page


def test_chip_goes_to_the_card_with_the_same_rel_not_to_every_plan_with_that_name():
    live, archived = _plan("same", "plans/same.md"), _plan("same", "plans/_archive/2026-Q3/same.md", archived=True)
    overlap = pp.Overlap("plans/_archive/2026-Q3/same.md", "same", archived.rel, ("f/1", "f/2"))
    page = pp.to_html([live], [archived], Path("."), overlaps=[overlap])
    assert page.count('data-chip="overlap"') == 1
    archive_part = page.split('<details id="archive">', 1)[1]
    assert 'data-chip="overlap"' in archive_part
    assert 'data-chip="overlap"' not in page.split('<details id="archive">', 1)[0]


# =========================================================================== шпион


def _spy(fn) -> list[list[str]]:
    calls: list[list[str]] = []
    real = subprocess.run

    def run(cmd, *a, **kw):
        if isinstance(cmd, (list, tuple)) and len(cmd) > 1 and cmd[0] == "git":
            calls.append(list(cmd))
        return real(cmd, *a, **kw)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(pp.subprocess, "run", run)
        fn()
    return calls
