# ruff: noqa: E501  -- литералы-фикстуры планов в одну строку
"""Тесты автора на внутренние опасности разбора plans_progress (Task 1.1+1.2).

Приёмку по критериям пишет независимый тестер (test_acceptance_progress.py). Здесь — места, которые
видны только по устройству механизма: границы раздела, маска код-спанов, вложенность скобок, префиксы
id, ограждения кода, битый ORDER.md, CRLF и BOM, экранирование HTML.

Тесты импортируют модуль напрямую (нужны внутренние функции), поэтому они не заменяют CLI-приёмку.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_MOD_PATH = Path(__file__).resolve().parents[1] / "plans_progress.py"
_spec = importlib.util.spec_from_file_location("plans_progress_under_test", _MOD_PATH)
pp = importlib.util.module_from_spec(_spec)
sys.modules["plans_progress_under_test"] = pp
_spec.loader.exec_module(pp)

SECTION = "## Порядок выполнения\n\n"


def items_of(body: str, head: str = SECTION) -> list:
    items, _ = pp.parse_items("# План\n\n" + head + body)
    return items


def statuses(items) -> dict[str, str]:
    return {i.id: i.status for i in items}


# ------------------------------------------------------------------ граница раздела


def test_section_ends_at_level_one_heading():
    items = items_of("- Task 1.1: a [DONE]\n\n# Другой документ\n\n- Task 1.2: b [DONE]\n")
    assert [i.id for i in items] == ["1.1"]


def test_nested_section_heading_does_not_double_count_or_end_the_outer_section():
    body = "- Task 1.1: a [DONE]\n\n### Порядок выполнения: фаза 1\n\n- Task 1.2: b [PENDING]\n"
    assert [i.id for i in items_of(body)] == ["1.1", "1.2"]


def test_second_section_after_the_first_ended_is_read_too():
    body = "- Task 1.1: a [DONE]\n\n## Риски\n\n- Task 9.9: x [DONE]\n\n## Execution order\n\n- Task 1.2: b [DONE]\n"
    assert [i.id for i in items_of(body)] == ["1.1", "1.2"]


def test_level_one_heading_is_not_a_section():
    items, had = pp.parse_items("# Порядок выполнения\n\n- Task 1.1: a [DONE]\n")
    assert items == [] and had is False


def test_fenced_block_hides_items_and_headings():
    body = "- Task 1.1: a [DONE]\n\n```\n## Риски\n- Task 9.9: ложный [DONE]\n```\n\n- Task 1.2: b [PENDING]\n"
    # заголовок внутри ограждения раздел не кончает, пункт внутри — не задача; пустая строка после ```
    assert [i.id for i in items_of(body)] == ["1.1", "1.2"]


# ------------------------------------------------------------------ код-спан, скобки


def test_code_span_with_brackets_is_masked_but_later_group_still_found():
    items = items_of("- Task 1.1: правим `[x] [PENDING]` и `]` потом [DONE 2026-10-02]\n")
    assert statuses(items) == {"1.1": "done"}


def test_double_backtick_span_is_masked():
    items = items_of("- Task 1.1: цитата ``a ` [DONE] b`` без статуса\n")
    assert statuses(items) == {"1.1": "unknown"}


def test_deeply_nested_brackets_close_on_the_matching_bracket():
    items = items_of("- Task 1.1: a [DONE [a [b] c] d] [PENDING]\n")
    assert statuses(items) == {"1.1": "done"}


def test_unclosed_group_runs_to_end_of_item_and_is_a_status():
    items = items_of("- Task 1.1: a [DEFERRED — после 4.1\n")
    assert statuses(items) == {"1.1": "deferred"}


def test_unclosed_group_with_no_word_is_unknown_and_does_not_eat_next_item():
    items = items_of("- Task 1.1: a [скобка не закрыта\n- Task 1.2: b [DONE]\n")
    assert statuses(items) == {"1.1": "unknown", "1.2": "done"}


def test_ref_comes_from_the_status_tail_not_from_the_title():
    items = items_of("- Task 1.1: правка `deadbee` и [DONE — `abc1234`]\n")
    assert items[0].ref == "abc1234"


def test_non_hash_backtick_is_not_a_ref():
    items = items_of("- Task 1.1: a [DONE — `run.py`; `ABC1234`; `abc12`]\n")
    assert items[0].ref is None


# ------------------------------------------------------------------ id


@pytest.mark.parametrize(
    ("line", "ids"),
    [
        ("- Task 1.1: a [DONE]\n- Task 1.10: b [DONE]\n- Task 1.1a: c [DONE]\n", ["1.1", "1.10", "1.1a"]),
        ("- Task 1.1–1.3: диапазон [DONE]\n", []),
        ("- Task 12: a [DONE]\n", ["12"]),
        ("- Task AB1.2: a [DONE]\n", ["AB1.2"]),
        ("- Task 1.4. Название [DONE]\n", ["1.4"]),
    ],
)
def test_id_extraction_edge_cases(line, ids):
    assert [i.id for i in items_of(line)] == ids


def test_task_word_inside_other_word_is_not_an_item():
    assert items_of("- Subtask 1.1: a [DONE]\n- Taskforce 1.2: b [DONE]\n") == []


def test_parent_needs_a_deeper_next_item_to_be_skipped():
    flat = items_of("- Task 1: **группа**\n- Task 2: b [DONE]\n")
    nested = items_of("- Task 1: **группа**\n  - Task 1a: a [DONE]\n")
    assert statuses(flat) == {"1": "unknown", "2": "done"}
    assert statuses(nested) == {"1a": "done"}


def test_marked_parent_with_children_is_kept():
    items = items_of("- Task 1: группа [DONE]\n  - Task 1a: a [DONE]\n")
    assert [i.id for i in items] == ["1", "1a"]


def test_strike_with_group_status_uses_the_group():
    assert statuses(items_of("- ~~Task 1.2~~: старая [DONE]\n")) == {"1.2": "done"}


# ------------------------------------------------------------------ чекбокс рядом со статусом


def test_checkbox_marked_next_to_done_is_one_marker_without_conflict():
    (it,) = items_of("- [x] Task 1.1: a [DONE]\n")
    assert (it.status, it.conflict) == ("done", False)


def test_checkbox_empty_next_to_done_is_conflict():
    (it,) = items_of("- [ ] Task 1.1: a [DONE]\n")
    assert (it.status, it.conflict) == ("done", True)


def test_checkbox_alone_gives_no_status():
    (it,) = items_of("- [x] Task 1.1: a\n")
    assert (it.status, it.conflict) == ("unknown", False)


# ------------------------------------------------------------------ CRLF и BOM


def test_crlf_and_bom_plan_parses_like_lf(tmp_path):
    lf = "# План\n\n## Порядок выполнения\n\n- Task 1.1: a [DONE — `abc1234`]\n  [PENDING]\n- Task 1.2: b [PENDING]\n"
    plan_dir = tmp_path / "plans" / "2026-10-02_crlf"
    plan_dir.mkdir(parents=True)
    (plan_dir / "plan.md").write_bytes(b"\xef\xbb\xbf" + lf.replace("\n", "\r\n").encode("utf-8"))
    plan = pp.discover(tmp_path)[0]
    assert [(t.id, t.status, t.ref) for t in plan.tasks] == [("1.1", "done", "abc1234"), ("1.2", "pending", None)]


def test_lone_cr_line_breaks_are_normalized(tmp_path):
    f = tmp_path / "p.md"
    f.write_bytes("a\rb\r\nc".encode("utf-8"))
    assert pp.read_text(f) == "a\nb\nc"


# ------------------------------------------------------------------ ORDER.md


def test_missing_empty_and_garbage_order_files_give_no_rows(tmp_path):
    assert pp.parse_order(tmp_path / "нет.md") == []
    empty = tmp_path / "e.md"
    empty.write_text("", encoding="utf-8")
    assert pp.parse_order(empty) == []
    junk = tmp_path / "j.md"
    junk.write_bytes(b"\xff\xfe\x00### 4.1\n| \\|\n|||\n[](\n")
    pp.parse_order(junk)  # не падает


def test_order_row_without_cells_or_links_is_skipped_and_header_row_too(tmp_path):
    f = tmp_path / "o.md"
    f.write_text(
        "### 4.1 Активные\n\n| План | Полоса |\n|---|---|\n| текст без ссылки | С |\n|\n| [a](../a/plan.md) | Р | ст | шаг |\n",
        encoding="utf-8",
    )
    rows = pp.parse_order(f)
    assert [(r.name, r.tier, r.lane) for r in rows] == [("a", "4.1", "Р")]


def test_order_escaped_pipe_does_not_shift_columns(tmp_path):
    f = tmp_path / "o.md"
    f.write_text("### 4.1 Активные\n\n| [a](../a/plan.md) | Р | сверить \\|J1\\| ≤ 100 | шаг |\n", encoding="utf-8")
    (row,) = pp.parse_order(f)
    assert row.info == [("Статус", "сверить |J1| ≤ 100"), ("Следующий шаг", "шаг")]


def test_order_multiple_links_in_one_cell_and_flat_file_links(tmp_path):
    f = tmp_path / "o.md"
    f.write_text(
        "### 4.3 Закрыты\n\n| [a](../a.md) · [b](../b/plan.md) · [web](https://x.y/z.md) | DONE |\n", encoding="utf-8"
    )
    assert [(r.name, r.tier, r.lane) for r in pp.parse_order(f)] == [("a", "4.3", None), ("b", "4.3", None)]


def test_order_tables_outside_the_three_tiers_are_ignored(tmp_path):
    f = tmp_path / "o.md"
    f.write_text(
        "## 2. Очередь\n\n| [x](../x/plan.md) | Р |\n\n### 4.1 A\n\n| [a](../a/plan.md) | — | s | n |\n\n## 5. Иное\n\n| [y](../y/plan.md) | Р |\n",
        encoding="utf-8",
    )
    assert [(r.name, r.lane) for r in pp.parse_order(f)] == [("a", None)]


def test_same_plan_in_two_tiers_takes_the_first(tmp_path):
    f = tmp_path / "o.md"
    f.write_text(
        "### 4.1 A\n\n| [a](../a/plan.md) | Р | s | n |\n\n### 4.3 C\n\n| [a](../a/plan.md) | DONE |\n",
        encoding="utf-8",
    )
    assert [(r.name, r.tier) for r in pp.parse_order(f)] == [("a", "4.1")]


# ------------------------------------------------------------------ набор, находки, HTML


def test_phase_file_name_pattern():
    ok = ["phase-1.md", "phase-2-core.md", "phase-1b-recipe-service.md", "phase-5-editor.md"]
    bad = ["phase-x.md", "phases-1.md", "phase-1.txt", "xphase-1.md", "task-1b2d.md"]
    assert all(pp.PHASE_FILE_RE.match(n) for n in ok)
    assert not any(pp.PHASE_FILE_RE.match(n) for n in bad)


def test_table_rows_skip_gate_phase_and_x_suffix():
    text = "| ✓ T1.2 | a |\n| T1.3 | b |\n| T4.x | c |\n| GATE-1 | d |\n| Ф7 | e |\n| ✓ T-00 | f |\n"
    assert [(t.id, t.status) for t in pp.parse_table_tasks(text)] == [("T1.2", "done"), ("T1.3", "pending")]


def test_task_status_in_heading_body_stops_at_next_task_heading():
    text = "### Task 1.1 — a\nпроза\n#### Task 1.2 — b\n**Статус:** [DONE]\n"
    got = {h.id: h.status for h in pp.parse_heading_tasks(text)}
    assert got == {"1.1": "pending", "1.2": "done"}


def test_findings_never_come_from_archived_plans():
    p = pp.Plan(name="old", rel="plans/_archive/old.md", archived=True)
    assert pp.build_findings([p]) == []


def test_baseline_ignores_comments_and_blank_lines(tmp_path):
    f = tmp_path / "b.txt"
    f.write_text("# комментарий\n\n  plan:NO_TASKS  \nplan:UNKNOWN_STATUS:1.1\n", encoding="utf-8")
    assert pp.load_baseline(f) == {"plan:NO_TASKS", "plan:UNKNOWN_STATUS:1.1"}


def test_html_escapes_titles_and_names():
    p = pp.Plan(
        name="a<b>", rel="plans/a.md", archived=False, tasks=[pp.Task("1.1", "<script>alert(1)</script>", "done")]
    )
    page = pp.to_html([p], [], Path("."))
    assert "<script>" not in page
    assert "&lt;script&gt;" in page
    assert 'data-plan="a&lt;b&gt;"' in page


def test_html_progress_for_plan_with_only_dropped_tasks_is_valid():
    p = pp.Plan(name="x", rel="plans/x.md", archived=False, tasks=[pp.Task("1.1", "t", "deferred")])
    page = pp.to_html([p], [], Path("."))
    assert '<progress value="0" max="1">' in page  # max=0 был бы невалиден
    assert "0 из 0" in page


# ------------------------------------------------------------------ нумерованный раздел порядка


@pytest.mark.parametrize(
    "heading",
    ["## 3. Порядок выполнения", "### 2) Execution order", "## 10. Порядок", "## 1.Порядок выполнения (ред. 2)"],
)
def test_numbered_section_title_is_a_section(heading):
    assert [i.id for i in items_of("- Task 1.1: a [DONE]\n", head=heading + "\n\n")] == ["1.1"]


@pytest.mark.parametrize("heading", ["## Порядок и окна", "## 3. Порядок и окна", "## 1.2 Порядок выполнения"])
def test_numbered_or_plain_non_section_titles_stay_non_sections(heading):
    assert items_of("- Task 1.1: a [DONE]\n", head=heading + "\n\n") == []


# ------------------------------------------------------------------ NO_STATUS_MARK / unmarked

UNMARKED_PLAN = """# План

### Task 1.1 — без признаков
проза без статуса

### Task 1.2 — группа в заголовке [DONE]
текст

### Task 1.3 — со строкой статуса
**Статус:** [PENDING]

### Task 1.4 — чекбоксы
- [ ] шаг

### Task 1.5 — голое слово — DONE 50df705f
текст
"""


def _write_plan(tmp_path: Path, name: str, text: str) -> Path:
    d = tmp_path / "plans" / name
    d.mkdir(parents=True)
    (d / "plan.md").write_text(text, encoding="utf-8")
    return tmp_path


def _cli(root: Path, *flags: str):
    import subprocess

    return subprocess.run(
        [sys.executable, str(_MOD_PATH), "--root", str(root), *flags],
        capture_output=True,
        timeout=60,
        encoding="utf-8",
        env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
    )


def test_unmarked_counts_only_heading_tasks_without_any_sign(tmp_path):
    plan = pp.discover(_write_plan(tmp_path, "2026-10-02_um", UNMARKED_PLAN))[0]
    marks = {t.id: t.unmarked for t in plan.tasks}
    # 1.1 и 1.5 (голое слово не статус) без признаков; 1.2 группа, 1.3 строка, 1.4 чекбокс
    assert marks == {"1.1": True, "1.2": False, "1.3": False, "1.4": False, "1.5": True}
    assert plan.unmarked == 2
    assert {t.id: t.status for t in plan.tasks}["1.5"] == "pending"


def test_no_status_mark_is_printed_as_info_and_does_not_block(tmp_path):
    root = _write_plan(tmp_path, "2026-10-02_um", UNMARKED_PLAN)
    cp = _cli(root, "--check")
    lines = [ln for ln in cp.stdout.splitlines() if ln.startswith("NO_STATUS_MARK")]
    assert lines == ["NO_STATUS_MARK 2026-10-02_um info — 2 из 5 задач без отметки статуса, считаются PENDING"]
    assert cp.returncode == 0


def test_json_has_unmarked_and_list_plan_has_zero(tmp_path):
    import json

    root = _write_plan(tmp_path, "2026-10-02_um", UNMARKED_PLAN)
    _write_plan(tmp_path, "2026-10-02_list", "# P\n\n## Порядок выполнения\n\n- Task 1.1: a [PENDING]\n- Task 1.2: b\n")
    data = {r["plan"]: r for r in json.loads(_cli(root, "--json").stdout)}
    assert data["2026-10-02_um"]["unmarked"] == 2
    assert data["2026-10-02_list"]["unmarked"] == 0


def test_html_chip_and_cell_attribute_only_for_unmarked_plan(tmp_path):
    root = _write_plan(tmp_path, "2026-10-02_um", UNMARKED_PLAN)
    _write_plan(tmp_path, "2026-10-02_list", "# P\n\n## Порядок выполнения\n\n- Task 1.1: a [PENDING]\n")
    out = tmp_path / "page.html"
    assert _cli(root, "--html", str(out)).returncode == 0
    page = out.read_text(encoding="utf-8")
    um, lst = page.split('data-plan="2026-10-02_um"')[1], page.split('data-plan="2026-10-02_list"')[1]
    um = um.split("</details>")[0]
    lst = lst.split("</details>")[0]
    assert (
        '<span class="chip warn" data-chip="unmarked" title="статус не размечен, цифра может быть занижена">⚠ 2 без отметки</span>'
        in um
    )
    assert um.count('data-unmarked="1"') == 2
    assert um.count('class="cell" data-status="pending" data-unmarked="1"') == 2
    assert "data-chip" not in lst and "data-unmarked" not in lst
