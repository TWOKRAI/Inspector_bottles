# ruff: noqa: E501  -- литералы-фикстуры планов в одну строку
"""Тесты автора на внутренние опасности порядка между планами (Task 3.1): `После:`, `(после N.M)`, `ready`, `DEP_*`.

Приёмку по критериям пишет независимый тестер (test_acceptance_deps.py). Здесь — места, видимые только по
устройству механизма: обход графа без рекурсии, участники цикла против зависящих от него, граница id в
`(после …)`, разные пути значения поля, находки задач плана, чьё поле указывает в пустоту.

Часть тестов импортирует модуль напрямую (нужны `cycle_groups`, `resolve_deps`, `find_after`); остальные идут
через CLI и дают проводку целиком. Каждое утверждение — в отдельном тесте: поломка одной гарантии не должна
красить соседние.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

_MOD_PATH = Path(__file__).resolve().parents[1] / "plans_progress.py"
_spec = importlib.util.spec_from_file_location("plans_progress_deps_under_test", _MOD_PATH)
pp = importlib.util.module_from_spec(_spec)
sys.modules["plans_progress_deps_under_test"] = pp
_spec.loader.exec_module(pp)

SECTION = "## Порядок выполнения\n\n"
OPEN_ITEM = "- Task 1.1: x [PENDING]\n"
DONE_ITEM = "- Task 1.1: x [DONE]\n"


def plan_text(header: str = "", items: str = OPEN_ITEM) -> str:
    head = "# План\n\n" + (header + "\n\n" if header else "")
    return head + SECTION + items


def field(value: str) -> str:
    return f"- **После:** {value}"


def task_after(clause: str) -> list[str]:
    items, _ = pp.parse_items(plan_text("", f"- Task 9.9: x [PENDING] {clause}\n"))
    return items[0].after


def mem_plan(name: str, after=(), archived: bool = False, status: str = "pending", tier=None):
    p = pp.Plan(name=name, rel=name, archived=archived, tier=tier)
    p.tasks = [pp.Task("1.1", "x", status)]
    p.after = list(after)
    return p


def lines_of(cp, code: str) -> list[str]:
    return [ln for ln in (cp.stdout + "\n" + cp.stderr).splitlines() if ln.startswith(code + " ")]


# ------------------------------------------------------------------ обход графа: без рекурсии, только участники


def test_cycle_groups_three_member_ring_names_all_three_and_not_the_tail():
    # 0 -> 1 -> 2 -> 0, узел 3 ссылается на 0, но в цикл не входит
    groups = pp.cycle_groups([[1], [2], [0], [0]])
    assert groups == {0: [0, 1, 2], 1: [0, 1, 2], 2: [0, 1, 2]}


def test_cycle_groups_two_separate_cycles_stay_separate():
    groups = pp.cycle_groups([[1], [0], [3], [2]])
    assert groups[0] == [0, 1] and groups[2] == [2, 3]


def test_cycle_groups_self_reference_is_a_cycle_of_one():
    assert pp.cycle_groups([[0], []]) == {0: [0]}


def test_cycle_groups_long_chain_does_not_hit_the_recursion_limit():
    n = 5000
    assert n > sys.getrecursionlimit()
    chain = [[i + 1] for i in range(n - 1)] + [[]]
    assert pp.cycle_groups(chain) == {}


def test_cycle_groups_long_ring_does_not_hit_the_recursion_limit():
    n = 5000
    ring = [[(i + 1) % n] for i in range(n)]
    groups = pp.cycle_groups(ring)
    assert len(groups) == n and groups[0] == list(range(n))


def test_resolve_deps_chain_of_2000_plans_in_memory():
    n = 2000
    plans = [mem_plan(f"p{i}", [f"p{i + 1}"]) for i in range(n - 1)]
    plans.append(mem_plan(f"p{n - 1}", archived=True))
    pp.resolve_deps(plans)
    assert [p.name for p in plans if p.ready] == [f"p{n - 2}"]
    assert all(p.dep_cycle == [] and p.dep_unknown == [] for p in plans)


def test_chain_of_2000_plans_through_cli(make_root, progress):
    import json

    n = 2000
    files = {f"plans/p{i}.md": plan_text(field(f"p{i + 1}")) for i in range(n - 1)}
    files[f"plans/p{n - 1}.md"] = plan_text()
    cp = progress(make_root(files), "--json")
    assert cp.returncode == 0, cp.stderr[:300]
    data = json.loads(cp.stdout)
    assert len(data) == n and all(r["dep_cycle"] == [] for r in data)
    assert sum(1 for r in data if r["ready"]) == 1  # только последний: у него нет ожидания


# ------------------------------------------------------------------ цикл: участники и зависящие от него


def test_three_plan_ring_names_exactly_its_members(make_root, plans_json):
    files = {
        "plans/A/plan.md": plan_text(field("B")),
        "plans/B/plan.md": plan_text(field("C")),
        "plans/C/plan.md": plan_text(field("A")),
    }
    plans = plans_json(make_root(files))
    for name in "ABC":
        assert plans[name]["dep_cycle"] == ["A", "B", "C"], name
        assert plans[name]["ready"] is False


def test_plan_depending_on_a_cycle_member_is_not_a_member(make_root, plans_json, progress):
    files = {
        "plans/A/plan.md": plan_text(field("B")),
        "plans/B/plan.md": plan_text(field("A")),
        "plans/C/plan.md": plan_text(field("A")),
    }
    root = make_root(files)
    plans = plans_json(root)
    assert plans["A"]["dep_cycle"] == ["A", "B"]
    assert plans["B"]["dep_cycle"] == ["A", "B"]
    assert plans["C"]["dep_cycle"] == [], "C ждёт участника цикла, но сама в нём не стоит"
    assert plans["C"]["ready"] is False, "A не закрыт, поэтому C всё равно ждёт"
    cp = progress(root, "--check")
    assert len(lines_of(cp, "DEP_CYCLE")) == 2


def test_task_depending_on_a_cycle_member_is_not_a_member(make_root, progress, plans_json):
    items = (
        "- Task 1.1: a [PENDING] (после 1.2)\n"
        "- Task 1.2: b [PENDING] (после 1.1)\n"
        "- Task 1.3: c [PENDING] (после 1.1)\n"
    )
    root = make_root({"plans/2026-10-03_t/plan.md": plan_text("", items)})
    cp = progress(root, "--check")
    refs = sorted(re.findall(r"^DEP_CYCLE (\S+) ", cp.stdout, flags=re.M))
    assert refs == ["2026-10-03_t:1.1", "2026-10-03_t:1.2"]
    tasks = {t["id"]: t for t in plans_json(root)["2026-10-03_t"]["tasks"]}
    assert tasks["1.3"]["ready"] is False


def test_cycle_group_members_come_out_by_node_number_not_discovery_order():
    # обход начинается с узла 0, а Тарьян достаёт участников со стека в обратном порядке: ждём сортировку
    assert pp.cycle_groups([[2], [], [0]])[2] == [0, 2]


# ------------------------------------------------------------------ имя плана против id задачи


def test_a_name_that_exists_only_as_a_task_id_is_unknown_as_a_plan(make_root, one_plan, progress):
    files = {
        "plans/A/plan.md": plan_text("", "- Task 1.1: x [DONE]\n"),
        "plans/B/plan.md": plan_text(field("1.1")),
    }
    root = make_root(files)
    rec = one_plan(root, "B")
    assert rec["dep_unknown"] == ["1.1"] and rec["ready"] is False
    cp = progress(root, "--check")
    assert [ln for ln in lines_of(cp, "DEP_UNKNOWN") if " B " in ln and "нет плана 1.1" in ln]


def test_a_plan_name_in_a_task_clause_is_a_missing_task_not_a_plan(make_root, progress):
    root = make_root(
        {"plans/A.md": plan_text("", DONE_ITEM), "plans/B.md": plan_text("", "- Task 1.1: y [PENDING] (после 2.2)\n")}
    )
    cp = progress(root, "--check")
    assert [ln for ln in lines_of(cp, "DEP_UNKNOWN") if ln.startswith("DEP_UNKNOWN B:1.1 ") and "нет задачи 2.2" in ln]


# ------------------------------------------------------------------ границы id в `(после …)`


@pytest.mark.parametrize(
    ("clause", "expected"),
    [
        ("(после 1b.2a)", ["1b.2a"]),
        ("(после 1.3h-c-fix)", ["1.3h-c-fix"]),
        ("(после 1b.2b-pre, 1.3h-c-fix)", ["1b.2b-pre", "1.3h-c-fix"]),
        ("(После 1.1)", ["1.1"]),
        ("(After 1.1)", ["1.1"]),
        ("(AFTER 1.1, 1.0)", ["1.1", "1.0"]),
        ("(после T1)", ["T1"]),
    ],
)
def test_id_forms_and_word_case_in_task_clause(clause, expected):
    assert task_after(clause) == expected


@pytest.mark.parametrize(
    "clause",
    ["(после 1.2B)", "(после 1.2.3)", "(после 1.1-Foo)", "(после 1.2_x)", "(после 1.2b3)", "(после  )"],
)
def test_not_an_id_is_not_read(clause):
    assert task_after(clause) == [], clause


def test_id_written_1_2B_does_not_leak_a_prefix_1_2():
    assert task_after("(после 1.1, 1.2B)") == ["1.1"]


def test_only_ids_right_after_the_word_count_the_rest_is_prose():
    assert task_after("(после 1b.2b-pre; до 1b.3; решение 2026-09-25)") == ["1b.2b-pre"]
    assert task_after("(после 1.1, до 1.3)") == ["1.1"]
    assert task_after("(после 1.1 и 1.2)") == ["1.1"]


def test_repeated_id_in_clause_is_kept_once():
    assert task_after("(после 1.1, 1.1)") == ["1.1"]


def test_clause_on_a_continuation_line_is_read():
    text = plan_text("", "- Task 1.1: x [PENDING]\n  продолжение (после 1.0)\n")
    items, _ = pp.parse_items(text)
    assert items[0].after == ["1.0"]


def test_clause_must_open_with_a_parenthesis():
    assert task_after("после 1.1") == []


def test_heading_and_file_tasks_get_no_after(make_root, one_plan):
    text = "# План\n\n### Task 1.1: x (после 1.0)\n\n**Статус:** PENDING\n"
    rec = one_plan(make_root({"plans/H/plan.md": text}), "H")
    assert [(t["id"], t["after"]) for t in rec["tasks"]] == [("1.1", [])]


# ------------------------------------------------------------------ значение поля `После:`


def test_find_after_returns_empty_triple_without_the_field():
    assert pp.find_after("# План\n\nпроза\n") == ([], [], "")


def test_find_after_condition_without_text_is_kept_as_the_marker():
    assert pp.find_after(field("⛔")) == ([], ["⛔"], "")


def test_find_after_keeps_an_url_as_an_unknown_name_instead_of_dropping_it():
    plans, _, _ = pp.find_after(field("https://example.com/x"))
    assert plans == ["https://example.com/x"]


def test_find_after_empty_value_first_line_wins_over_a_later_one():
    assert pp.find_after(field("") + "\n" + field("A")) == ([], [], "")


def test_find_after_link_with_anchor_resolves_to_the_plan_name():
    assert pp.find_after(field("[план](../A/plan.md#фаза-2)"))[0] == ["A"]


def test_find_after_hyphen_in_a_name_does_not_split_the_reason():
    assert pp.find_after(field("2026-10-03_a-b — причина")) == (["2026-10-03_a-b"], [], "причина")


def test_find_after_wrong_word_case_is_not_a_field():
    assert pp.find_after("- **после:** A")[0] == []


# ------------------------------------------------------------------ находки: поле плана и пункты вместе


def test_task_clause_and_unknown_plan_in_the_same_plan_give_both_findings(make_root, progress, one_plan):
    items = "- Task 1.1: x [PENDING]\n- Task 1.2: y [PENDING] (после 9.9)\n"
    root = make_root({"plans/2026-10-03_t/plan.md": plan_text(field("ghost"), items)})
    cp = progress(root, "--check")
    unknown = lines_of(cp, "DEP_UNKNOWN")
    assert any(ln.startswith("DEP_UNKNOWN 2026-10-03_t info") and "нет плана ghost" in ln for ln in unknown), unknown
    assert any(ln.startswith("DEP_UNKNOWN 2026-10-03_t:1.2 info") and "нет задачи 9.9" in ln for ln in unknown), unknown
    assert len(unknown) == 2
    tasks = {t["id"]: t for t in one_plan(root, "2026-10-03_t")["tasks"]}
    assert tasks["1.1"]["ready"] is False, "план ждёт неизвестное имя: ни одна его задача не готова"


def test_task_finding_in_tier_41_blocks_and_the_baseline_key_has_no_task_id(make_root, progress, order_md, tmp_path):
    name = "2026-10-03_b"
    files = {
        f"plans/{name}/plan.md": plan_text("", "- Task 1.1: x [PENDING] (после 9.9)\n"),
        "plans/queue/ORDER.md": order_md(tier41=[name]),
    }
    root = make_root(files)
    assert progress(root, "--check").returncode == 1
    base = tmp_path / "base.txt"
    base.write_text(f"{name}:DEP_UNKNOWN\n", encoding="utf-8")
    cp = progress(root, "--check", "--baseline", str(base))
    assert cp.returncode == 0, cp.stdout
    assert any("DEP_UNKNOWN" in ln and "blocking" in ln and "(известна, в базе)" in ln for ln in cp.stdout.splitlines())


def test_missing_name_in_finding_text_is_cut_to_80_characters(make_root, progress):
    ghost = "g" * 300
    root = make_root({"plans/B.md": plan_text(field(ghost))})
    (line,) = lines_of(progress(root, "--check"), "DEP_UNKNOWN")
    assert "g" * 80 not in line
    assert "g" * 79 + "…" in line


def test_markdown_noise_in_a_missing_name_is_cleaned_in_finding_text(make_root, progress):
    root = make_root({"plans/B.md": plan_text(field("[подпись](../ghost/plan.md)"))})
    (line,) = lines_of(progress(root, "--check"), "DEP_UNKNOWN")
    assert "нет плана ghost" in line and "](" not in line


def test_archived_plan_with_unknown_name_gets_no_finding_but_still_resolves(make_root, progress, plans_json):
    root = make_root({"plans/_archive/2026-Q4/Z/plan.md": plan_text(field("ghost")), "plans/B.md": plan_text()})
    assert lines_of(progress(root, "--check"), "DEP_UNKNOWN") == []
    z = plans_json(root)["Z"]
    assert z["dep_unknown"] == ["ghost"] and z["ready"] is False


# ------------------------------------------------------------------ готовность: что НЕ даёт ready


def test_plan_ready_needs_the_awaited_plan_closed_not_merely_present():
    a, b = mem_plan("A"), mem_plan("B", ["A"])
    pp.resolve_deps([a, b])
    assert (a.ready, b.ready) == (True, False)
    done = mem_plan("A", status="done")
    b2 = mem_plan("B", ["A"])
    pp.resolve_deps([done, b2])
    assert (done.ready, b2.ready) == (False, True), "закрытый план сам не ready, зато снимает ожидание у B"


def test_waiting_condition_alone_blocks_ready_even_with_all_plans_closed():
    p = mem_plan("B")
    p.waiting_on = ["железо"]
    pp.resolve_deps([p])
    assert p.ready is False


def test_task_ready_requires_plan_ready_and_pending_status():
    p = mem_plan("B")
    p.waiting_on = ["x"]
    pp.resolve_deps([p])
    assert p.tasks[0].ready is False
    q = mem_plan("Q", status="in_progress")
    pp.resolve_deps([q])
    assert q.tasks[0].ready is False


def test_archived_copy_decides_when_a_live_and_an_archived_copy_share_a_name():
    live_a = mem_plan("A")
    arch_a = mem_plan("A", archived=True)
    b = mem_plan("B", ["A"])
    pp.resolve_deps([live_a, arch_a, b])
    assert b.ready is True
    pp.resolve_deps([arch_a, live_a, b])
    assert b.ready is True, "порядок записей не должен менять решение"


def test_live_copy_of_an_archived_name_does_not_create_a_cycle_edge():
    live_a = mem_plan("A", ["B"])
    arch_a = mem_plan("A", archived=True)
    b = mem_plan("B", ["A"])
    pp.resolve_deps([live_a, arch_a, b])
    assert b.dep_cycle == [] and live_a.dep_cycle == []
