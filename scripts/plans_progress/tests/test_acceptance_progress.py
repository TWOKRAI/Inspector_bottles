# ruff: noqa: E501  -- литералы-фикстуры планов и ожидания в одну строку, форматтер их не переносит
"""Приёмка Task 1.1 + 1.2 (scripts/plans_progress/plans_progress.py) — слепые тесты по плану
plans/2026-10-02_plans-progress-dashboard.md (разделы «Формат задачи», «Интерфейс», приёмка 1.1 и 1.2).

Скрипта ещё нет: тесты красные по построению. Каждый тест проверяет конкретный литерал
(число, статус, id, код находки, порядок), а не только код возврата.

Только CLI в subprocess: `python scripts/plans_progress/plans_progress.py --root R
(--json | --check [--baseline P] | --html P) [--order P]`. Фикстуры — тексты планов в tmp_path.

Договорённости чтения (в плане не уточнены, см. отчёт тестера):
- имя плана в `--json`/`data-plan` сравнивается без суффикса `.md` (`conftest._norm_key`);
- статус задачи в JSON сравнивается в каноне `in_progress` (регистр и пробел не важны);
- строка находки `--check` — любая строка stdout/stderr, где одновременно стоят код находки
  и id/имя плана; формат строки тестами не фиксируется.
"""

from __future__ import annotations

import re

import pytest

SECTION = "## Порядок выполнения\n\n"


def plan_text(items: str, *, tail: str = "") -> str:
    """План с разделом порядка и пунктами `items` (+ произвольный хвост после раздела)."""
    return "# План\n\n" + SECTION + items + ("\n" + tail if tail else "")


def finding_lines(out: str, code: str) -> list[str]:
    return [ln for ln in out.splitlines() if code in ln]


def check_out(cp) -> str:
    return cp.stdout + "\n" + cp.stderr


# =========================================================================== реальные снимки


def test_real_layer_render_counts_five_of_twenty(real_root, one_plan):
    rec = one_plan(real_root, "layer-render")
    assert (rec["done"], rec["total"]) == (5, 20)


def test_real_gui_service_counts_ten_of_twenty_one(real_root, one_plan):
    rec = one_plan(real_root, "2026-09-22_gui-service")
    assert (rec["done"], rec["total"]) == (10, 21)


def test_real_order_md_gives_tier_and_lane(real_root, one_plan):
    # layer-render: §4.1, полоса «С»; gui-service: §4.1, полоса «И» (литералы из ORDER.md на коммите снимка)
    lr = one_plan(real_root, "layer-render")
    gs = one_plan(real_root, "2026-09-22_gui-service")
    assert (lr["tier"], lr["lane"]) == ("4.1", "С")
    assert (gs["tier"], gs["lane"]) == ("4.1", "И")


def test_real_check_reports_status_conflicts_of_layer_render(real_root, progress):
    # план: «сейчас такие есть: 1.1, 1.3, 2.1, 5.3 у layer-render»
    out = check_out(progress(real_root, "--check"))
    conflicts = finding_lines(out, "STATUS_CONFLICT")
    for tid in ("1.1", "1.3", "2.1", "5.3"):
        assert any(
            "layer-render" in ln and re.search(rf"(?<![\d.]){re.escape(tid)}(?![\d.]*\d)", ln) for ln in conflicts
        ), f"нет STATUS_CONFLICT для layer-render {tid}; строки: {conflicts[:6]}"


# =========================================================================== пункт списка: статус


def test_item_with_tail_is_done_and_ref_is_first_backtick_hash(make_root, one_plan, statuses):
    text = plan_text("- Task 1.1: первая [DONE 2026-10-02 — `abc1234`; `def5678`; 5 тестов]\n")
    root = make_root({"plans/2026-10-02_tail/plan.md": text})
    rec = one_plan(root, "2026-10-02_tail")
    assert (rec["done"], rec["total"]) == (1, 1)
    assert statuses(rec) == {"1.1": "done"}
    assert [t["ref"] for t in rec["tasks"]] == ["abc1234"]


def test_item_without_hash_has_null_ref(make_root, one_plan):
    root = make_root({"plans/2026-10-02_noref/plan.md": plan_text("- Task 1.1: первая [DONE]\n")})
    assert [t["ref"] for t in one_plan(root, "2026-10-02_noref")["tasks"]] == [None]


def test_item_title_is_given(make_root, one_plan):
    root = make_root({"plans/2026-10-02_title/plan.md": plan_text("- Task 1.1: Разбор формата [DONE]\n")})
    titles = [t["title"] for t in one_plan(root, "2026-10-02_title")["tasks"]]
    assert len(titles) == 1 and "Разбор формата" in titles[0], titles


def test_status_on_continuation_line_belongs_to_the_item(make_root, one_plan, statuses):
    items = "- Task 1.1: первая задача\n  с переносом строки\n  [DONE 2026-09-01 — `abc1234`; ok]\n"
    root = make_root({"plans/2026-10-02_cont/plan.md": plan_text(items)})
    rec = one_plan(root, "2026-10-02_cont")
    assert statuses(rec) == {"1.1": "done"}
    assert [t["ref"] for t in rec["tasks"]] == ["abc1234"]


def test_status_after_blank_line_is_not_part_of_the_item(make_root, one_plan, statuses):
    items = "- Task 1.1: первая\n\n  [DONE]\n"
    root = make_root({"plans/2026-10-02_blank/plan.md": plan_text(items)})
    rec = one_plan(root, "2026-10-02_blank")
    assert statuses(rec) == {"1.1": "unknown"}
    assert (rec["done"], rec["total"], rec["unknown"]) == (0, 0, 1)


def test_status_of_next_item_does_not_leak_into_previous(make_root, one_plan, statuses):
    items = "- Task 1.1: первая\n- Task 1.2: вторая [DONE]\n"
    root = make_root({"plans/2026-10-02_leak/plan.md": plan_text(items)})
    assert statuses(one_plan(root, "2026-10-02_leak")) == {"1.1": "unknown", "1.2": "done"}


def test_status_word_not_first_in_group(make_root, one_plan, statuses):
    items = "- Task 5.3a: подзадача [5.3a DONE 2026-09-23, 10 тестов]\n"
    root = make_root({"plans/2026-10-02_word/plan.md": plan_text(items)})
    rec = one_plan(root, "2026-10-02_word")
    assert statuses(rec) == {"5.3a": "done"}
    assert (rec["done"], rec["total"]) == (1, 1)


def test_blocked_with_tail_counts_in_denominator(make_root, one_plan, statuses):
    items = "- Task 1.1: a [DONE]\n- Task 1.2: b [BLOCKED, частично]\n"
    root = make_root({"plans/2026-10-02_blk/plan.md": plan_text(items)})
    rec = one_plan(root, "2026-10-02_blk")
    assert statuses(rec) == {"1.1": "done", "1.2": "blocked"}
    assert (rec["done"], rec["total"], rec["unknown"]) == (1, 2, 0)


def test_in_progress_word_with_space(make_root, one_plan, statuses):
    root = make_root({"plans/2026-10-02_inp/plan.md": plan_text("- Task 1.1: a [IN PROGRESS]\n")})
    assert statuses(one_plan(root, "2026-10-02_inp")) == {"1.1": "in_progress"}


@pytest.mark.parametrize("word", ["SKIPPED", "CANCELLED"])
def test_old_words_map_to_superseded(make_root, one_plan, statuses, word):
    items = f"- Task 1.1: a [DONE]\n- Task 1.2: b [{word}]\n"
    root = make_root({"plans/2026-10-02_old/plan.md": plan_text(items)})
    rec = one_plan(root, "2026-10-02_old")
    assert statuses(rec)["1.2"] == "superseded"
    assert (rec["done"], rec["total"], rec["dropped"]) == (1, 1, 1)


@pytest.mark.parametrize("bad", ["[DONE-ish]", "[UNDONE]", "[DONE_x]"])
def test_status_word_glued_to_letter_underscore_or_dash_is_not_a_status(make_root, one_plan, statuses, bad):
    root = make_root({"plans/2026-10-02_glue/plan.md": plan_text(f"- Task 1.1: a {bad}\n")})
    rec = one_plan(root, "2026-10-02_glue")
    assert statuses(rec) == {"1.1": "unknown"}
    assert (rec["done"], rec["total"], rec["unknown"]) == (0, 0, 1)


def test_done_pending_doneish_literal_from_plan(make_root, one_plan):
    # литерал приёмки: DONE, PENDING, [DONE-ish] -> done=1, total=2, unknown=1
    items = "- Task 1.1: a [DONE]\n- Task 1.2: b [PENDING]\n- Task 1.3: c [DONE-ish]\n"
    root = make_root({"plans/2026-10-02_three/plan.md": plan_text(items)})
    rec = one_plan(root, "2026-10-02_three")
    assert (rec["done"], rec["total"], rec["unknown"]) == (1, 2, 1)


def test_lint_names_the_unknown_status_line(make_root, progress):
    # план вне ORDER.md: информационная находка, exit 0; но называет id строки
    items = "- Task 1.1: a [DONE]\n- Task 1.3: c [DONE-ish]\n"
    root = make_root({"plans/2026-10-02_name/plan.md": plan_text(items)})
    cp = progress(root, "--check")
    lines = finding_lines(check_out(cp), "UNKNOWN_STATUS")
    assert any("1.3" in ln for ln in lines), f"UNKNOWN_STATUS для 1.3 не назван: {check_out(cp)[:500]!r}"
    assert cp.returncode == 0


def test_code_span_pending_is_quote_and_done_at_end_wins(make_root, one_plan, statuses):
    items = "- Task 1.1: заменить `[PENDING]` на метку [DONE]\n"
    root = make_root({"plans/2026-10-02_span/plan.md": plan_text(items)})
    rec = one_plan(root, "2026-10-02_span")
    assert statuses(rec) == {"1.1": "done"}
    assert (rec["done"], rec["total"]) == (1, 1)


def test_code_span_alone_is_not_a_status(make_root, one_plan, statuses):
    root = make_root({"plans/2026-10-02_span2/plan.md": plan_text("- Task 1.1: метка `[DONE]` в тексте\n")})
    assert statuses(one_plan(root, "2026-10-02_span2")) == {"1.1": "unknown"}


def test_nested_brackets_in_status_group(make_root, one_plan, statuses):
    items = "- Task 1.1: a [DONE 2026-10-02 — [контракт](docs/x.md); `abc1234`]\n- Task 1.2: b [PENDING]\n"
    root = make_root({"plans/2026-10-02_nest/plan.md": plan_text(items)})
    rec = one_plan(root, "2026-10-02_nest")
    assert statuses(rec) == {"1.1": "done", "1.2": "pending"}
    assert (rec["done"], rec["total"]) == (1, 2)


def test_bold_status_and_date_outside_brackets(make_root, one_plan, statuses):
    root = make_root({"plans/2026-10-02_bold/plan.md": plan_text("- Task 1.1: a **[DONE] 2026-08-31**\n")})
    assert statuses(one_plan(root, "2026-10-02_bold")) == {"1.1": "done"}


def test_first_group_with_a_set_word_wins(make_root, one_plan, statuses):
    items = "- Task 1.1: a [см. выше] [PENDING] потом [DONE]\n"
    root = make_root({"plans/2026-10-02_first/plan.md": plan_text(items)})
    assert statuses(one_plan(root, "2026-10-02_first")) == {"1.1": "pending"}


def test_deferred_and_superseded_not_in_denominator_but_listed(make_root, one_plan):
    items = (
        "- Task 1.1: a [DONE]\n- Task 1.2: b [DEFERRED — после 4.1]\n"
        "- Task 1.3: c [SUPERSEDED]\n- Task 1.4: d [PENDING]\n"
    )
    root = make_root({"plans/2026-10-02_drop/plan.md": plan_text(items)})
    rec = one_plan(root, "2026-10-02_drop")
    assert (rec["done"], rec["total"], rec["dropped"], rec["unknown"]) == (1, 2, 2, 0)
    assert len(rec["tasks"]) == 4


def test_tilde_struck_task_is_superseded(make_root, one_plan, statuses):
    items = "- Task 1.1: a [DONE]\n- ~~Task 1.2~~: старая задача\n"
    root = make_root({"plans/2026-10-02_tilde/plan.md": plan_text(items)})
    rec = one_plan(root, "2026-10-02_tilde")
    assert statuses(rec) == {"1.1": "done", "1.2": "superseded"}
    assert (rec["done"], rec["total"], rec["dropped"]) == (1, 1, 1)


def test_snyata_word_is_superseded(make_root, one_plan, statuses):
    items = "- Task 1.1: a [DONE]\n- Task 1.2: старая задача — СНЯТА\n"
    root = make_root({"plans/2026-10-02_snyata/plan.md": plan_text(items)})
    assert statuses(one_plan(root, "2026-10-02_snyata"))["1.2"] == "superseded"


# =========================================================================== id


@pytest.mark.parametrize("tid", ["1.3a", "1b.2b-pre", "1.3h-c-fix", "T1", "1b.2a", "1.3"])
def test_id_is_extracted_whole(make_root, one_plan, tid):
    root = make_root({"plans/2026-10-02_id/plan.md": plan_text(f"- Task {tid}: название [DONE]\n")})
    rec = one_plan(root, "2026-10-02_id")
    assert [t["id"] for t in rec["tasks"]] == [tid]


@pytest.mark.parametrize(
    ("line", "tid"),
    [
        ("- Task 1.4. Название [DONE]", "1.4"),
        ("- Task 1.5; название [DONE]", "1.5"),
        ("- **Task 1.6**: название [DONE]", "1.6"),
        ("- Task 1.7, затем 1.8: название [DONE]", "1.7"),
    ],
)
def test_trailing_punctuation_is_not_part_of_id(make_root, one_plan, line, tid):
    root = make_root({"plans/2026-10-02_punct/plan.md": plan_text(line + "\n")})
    assert [t["id"] for t in one_plan(root, "2026-10-02_punct")["tasks"]] == [tid]


def test_after_clause_does_not_create_a_task(make_root, one_plan):
    items = "- Task 1.2: b [PENDING] (после 1.1)\n"
    root = make_root({"plans/2026-10-02_after/plan.md": plan_text(items)})
    rec = one_plan(root, "2026-10-02_after")
    assert [t["id"] for t in rec["tasks"]] == ["1.2"]


def test_stem_and_suffixed_ids_keep_separate_statuses(make_root, one_plan, statuses):
    # `1b.2b-pre` DONE не отдаёт статус `1b.2b`; `1b.2a` DONE не отдаёт статус родителю `1b.2`; `1.3a` против `1.3`
    items = (
        "- Task 1b.2b-pre: a [DONE]\n- Task 1b.2b: b [PENDING]\n"
        "- Task 1b.2: c [PENDING]\n- Task 1b.2a: d [DONE]\n"
        "- Task 1.3: e [PENDING]\n- Task 1.3a: f [DONE]\n"
    )
    root = make_root({"plans/2026-10-02_sep/plan.md": plan_text(items)})
    assert statuses(one_plan(root, "2026-10-02_sep")) == {
        "1b.2b-pre": "done",
        "1b.2b": "pending",
        "1b.2": "pending",
        "1b.2a": "done",
        "1.3": "pending",
        "1.3a": "done",
    }


# =========================================================================== раздел и зона разбора


def test_parent_without_marker_is_not_a_task_children_are(make_root, one_plan, statuses):
    items = "- Task 1b.2: **РАЗДЕЛЕНА на подзадачи**\n  - Task 1b.2a: первая [DONE]\n  - Task 1b.2b: вторая [PENDING]\n"
    root = make_root({"plans/2026-10-02_par/plan.md": plan_text(items)})
    rec = one_plan(root, "2026-10-02_par")
    assert statuses(rec) == {"1b.2a": "done", "1b.2b": "pending"}
    assert (rec["done"], rec["total"]) == (1, 2)


def test_bold_task_outside_section_is_a_reference_not_a_task(make_root, one_plan):
    text = (
        "# План\n\n## Контекст\n\n- **Task 9.9** — см. там [DONE]\n- **Task 9.8** — см. там [PENDING]\n\n"
        + SECTION
        + "- Task 1.1: a [DONE]\n"
    )
    root = make_root({"plans/2026-10-02_out/plan.md": text})
    rec = one_plan(root, "2026-10-02_out")
    assert [t["id"] for t in rec["tasks"]] == ["1.1"]


def test_bold_task_in_section_is_a_task(make_root, one_plan):
    root = make_root({"plans/2026-10-02_boldin/plan.md": plan_text("- **Task 1.1**: a [DONE]\n")})
    assert [t["id"] for t in one_plan(root, "2026-10-02_boldin")["tasks"]] == ["1.1"]


def test_section_with_name_after_the_phrase_is_not_a_section(make_root, one_plan):
    # `## Порядок и окна` не раздел: пункты под ним не задачи
    text = "# План\n\n## Порядок и окна\n\n- Task 1.1: a [DONE]\n- Task 1.2: b [PENDING]\n"
    root = make_root(
        {
            "plans/2026-10-02_win/plan.md": text,
            # якорь: парсер жив — настоящий раздел в соседнем плане даёт задачу
            "plans/2026-10-02_anchor/plan.md": plan_text("- Task 1.1: a [DONE]\n"),
        }
    )
    assert one_plan(root, "2026-10-02_anchor")["total"] == 1
    rec = one_plan(root, "2026-10-02_win")
    assert rec["tasks"] == []
    assert (rec["done"], rec["total"]) == (0, 0)


@pytest.mark.parametrize(
    "heading", ["## Порядок", "## Execution order", "## ПОРЯДОК ВЫПОЛНЕНИЯ", "### Порядок выполнения: фаза 1"]
)
def test_section_title_variants_are_sections(make_root, one_plan, heading):
    text = f"# План\n\n{heading}\n\n- Task 1.1: a [DONE]\n"
    root = make_root({"plans/2026-10-02_var/plan.md": text})
    assert [t["id"] for t in one_plan(root, "2026-10-02_var")["tasks"]] == ["1.1"]


def test_section_ends_at_heading_of_same_or_higher_level(make_root, one_plan):
    text = plan_text(
        "- Task 1.1: a [DONE]\n\n### Phase 2\n\n- Task 1.2: b [PENDING]\n\n## Риски\n\n- Task 1.3: c [DONE]\n"
    )
    root = make_root({"plans/2026-10-02_end/plan.md": text})
    # подзаголовок `###` внутри раздела `##` раздел НЕ кончает; `## Риски` кончает
    assert [t["id"] for t in one_plan(root, "2026-10-02_end")["tasks"]] == ["1.1", "1.2"]


def test_section_is_searched_only_in_plan_md(make_root, one_plan):
    # раздел в phase-1.md игнорируется; задачи берутся из заголовка plan.md
    root = make_root(
        {
            "plans/2026-10-02_onlyplan/plan.md": "# P\n\n### Task 5.5 — h\n**Статус:** [DONE]\n",
            "plans/2026-10-02_onlyplan/phase-1.md": "# Ф1\n\n" + SECTION + "- Task 1.1: x [DONE]\n",
        }
    )
    assert [t["id"] for t in one_plan(root, "2026-10-02_onlyplan")["tasks"]] == ["5.5"]


# =========================================================================== набор задач (N1) и приоритеты


def test_n1_headings_and_phase_files_add_no_new_ids_when_section_has_items(make_root, one_plan):
    root = make_root(
        {
            "plans/2026-10-02_n1/plan.md": plan_text(
                "- Task 1.1: a [DONE]\n- Task 1.2: b [PENDING]\n",
                tail="## Старая нарезка\n\n### Task 3.3 — старая\n**Статус:** [PENDING]\n",
            ),
            "plans/2026-10-02_n1/phase-2.md": "# Ф2\n\n### Task 4.3 — старая\n**Статус:** [PENDING]\n",
        }
    )
    rec = one_plan(root, "2026-10-02_n1")
    assert sorted(t["id"] for t in rec["tasks"]) == ["1.1", "1.2"]
    assert (rec["done"], rec["total"]) == (1, 2)


def test_list_item_wins_over_status_line_and_conflict_is_reported(make_root, one_plan, statuses, progress):
    text = plan_text(
        "- Task 1.1: a [DONE]\n",
        tail="## Задачи\n\n### Task 1.1 — a\n**Статус:** [PENDING]\n",
    )
    root = make_root({"plans/2026-10-02_conf/plan.md": text})
    rec = one_plan(root, "2026-10-02_conf")
    assert statuses(rec) == {"1.1": "done"}
    assert (rec["done"], rec["total"]) == (1, 1)
    cp = progress(root, "--check")
    assert any("1.1" in ln for ln in finding_lines(check_out(cp), "STATUS_CONFLICT")), check_out(cp)[:500]
    assert cp.returncode == 0


def test_agreeing_statuses_give_no_conflict_only_the_disagreeing_task_does(make_root, progress):
    text = plan_text(
        "- Task 1.1: a [DONE]\n- Task 1.2: b [DONE]\n",
        tail="## Задачи\n\n### Task 1.1 — a\n**Статус:** [DONE]\n\n### Task 1.2 — b\n**Статус:** [PENDING]\n",
    )
    root = make_root({"plans/2026-10-02_agree/plan.md": text})
    lines = finding_lines(check_out(progress(root, "--check")), "STATUS_CONFLICT")
    assert any("1.2" in ln for ln in lines), "для 1.2 конфликт обязан быть (иначе проверка бессмысленна)"
    assert not any(re.search(r"(?<![\d.])1\.1(?![\d.]*\d)", ln) for ln in lines), lines


# =========================================================================== задачи без списка


HEADING_PLAN = """# План

### Task 1.1 — из статуса
**Статус:** [DONE]

#### Task 1.2 — четвёртый уровень
**Статус:** BLOCKED

### Task 1.3 — из заголовка [IN PROGRESS]
текст

### Task 1.4 — все чекбоксы
- [x] а
- [x] б

### Task 1.5 — не все чекбоксы
- [x] а
- [ ] б

### Task 1.6 — без чекбоксов и статуса
просто текст

### Task 1.7 — приоритет статуса-строки над заголовком [BLOCKED]
**Статус:** DONE
"""


@pytest.mark.parametrize(
    ("tid", "expected"),
    [
        ("1.1", "done"),  # `**Статус:** [DONE]`
        ("1.2", "blocked"),  # `#### Task` + `**Статус:** BLOCKED`
        ("1.3", "in_progress"),  # статус из строки заголовка
        ("1.4", "done"),  # все чекбоксы отмечены
        ("1.5", "pending"),  # не все чекбоксы
        ("1.6", "pending"),  # ни статуса, ни чекбоксов
        ("1.7", "done"),  # `**Статус:**` важнее группы в заголовке
    ],
)
def test_task_from_heading_status_rules(make_root, one_plan, statuses, tid, expected):
    root = make_root({"plans/2026-10-02_heads/plan.md": HEADING_PLAN})
    rec = one_plan(root, "2026-10-02_heads")
    assert statuses(rec)[tid] == expected


def test_heading_plan_totals(make_root, one_plan):
    root = make_root({"plans/2026-10-02_heads/plan.md": HEADING_PLAN})
    rec = one_plan(root, "2026-10-02_heads")
    # done: 1.1, 1.4, 1.7 = 3; всего 7; `?` у задач-заголовков не бывает
    assert (rec["done"], rec["total"], rec["unknown"]) == (3, 7, 0)


def test_phase_files_with_name_suffix_are_read(make_root, one_plan, statuses):
    root = make_root(
        {
            "plans/2026-10-02_phasefiles/plan.md": "# План\n\nПроза без задач.\n",
            "plans/2026-10-02_phasefiles/phase-2-core.md": "# Ф2\n\n### Task 2.1 — a\n**Статус:** [DONE]\n",
            "plans/2026-10-02_phasefiles/phase-1b-recipe-service.md": "# Ф1b\n\n### Task 1b.1 — b\n**Статус:** [PENDING]\n",
        }
    )
    rec = one_plan(root, "2026-10-02_phasefiles")
    assert statuses(rec) == {"2.1": "done", "1b.1": "pending"}
    assert (rec["done"], rec["total"]) == (1, 2)


TABLE = """# Карта

| Задача | Название |
|---|---|
| ✓ T1.2 | сделано |
| T1.3 | не сделано |
| ✓ T2.J2 | буквенный суффикс |
| T2.x | шаблонная строка, не задача |
| GATE-1 | ворота, не задача |
| Ф7 | фаза, не задача |
"""


def test_table_with_check_mark_in_tasks_md(make_root, one_plan, statuses):
    root = make_root(
        {
            "plans/2026-10-02_table/plan.md": "# План без списка\n",
            "plans/2026-10-02_table/tasks.md": TABLE,
        }
    )
    rec = one_plan(root, "2026-10-02_table")
    assert statuses(rec) == {"T1.2": "done", "T1.3": "pending", "T2.J2": "done"}
    assert (rec["done"], rec["total"]) == (2, 3)


def test_table_is_read_from_tasks_dash_file(make_root, one_plan, statuses):
    root = make_root(
        {
            "plans/2026-10-02_table2/plan.md": "# План без списка\n",
            "plans/2026-10-02_table2/tasks-2.md": "| Задача | Название |\n|---|---|\n| ✓ T3.1 | сделано |\n",
        }
    )
    assert statuses(one_plan(root, "2026-10-02_table2")) == {"T3.1": "done"}


def test_table_is_read_from_plan_md(make_root, one_plan, statuses):
    text = "# План\n\n| Задача | Название |\n|---|---|\n| T5.1 | a |\n| ✓ T5.2 | b |\n"
    root = make_root({"plans/2026-10-02_table3/plan.md": text})
    assert statuses(one_plan(root, "2026-10-02_table3")) == {"T5.1": "pending", "T5.2": "done"}


def test_tasks_dir_files(make_root, one_plan, statuses):
    root = make_root(
        {
            "plans/2026-10-02_tdir/plan.md": "# План без списка\n",
            "plans/2026-10-02_tdir/tasks/1.1.md": "# Task 1.1 — a\n\n**Статус:** [DONE]\n",
            "plans/2026-10-02_tdir/tasks/1.2.md": "# Task 1.2 — b\n\n**Статус:** [PENDING]\n",
            "plans/2026-10-02_tdir/tasks/1.3.md": "# Task 1.3 — c\n\n- [ ] шаг\n",
        }
    )
    rec = one_plan(root, "2026-10-02_tdir")
    assert statuses(rec) == {"1.1": "done", "1.2": "pending", "1.3": "pending"}
    assert (rec["done"], rec["total"]) == (1, 3)


# =========================================================================== охват, архив, служебные файлы


def test_service_files_and_queue_dir_are_not_plans(make_root, plans_json):
    root = make_root(
        {
            "plans/2026-10-02_real/plan.md": plan_text("- Task 1.1: a [DONE]\n"),
            "plans/QUEUE.md": plan_text("- Task 1.1: a [DONE]\n"),
            "plans/README.md": plan_text("- Task 1.1: a [DONE]\n"),
            "plans/queue/backlog.md": plan_text("- Task 1.1: a [DONE]\n"),
        }
    )
    assert set(plans_json(root)) == {"2026-10-02_real"}


def test_archived_plan_is_listed_with_flag_and_tally(make_root, plans_json):
    root = make_root(
        {
            "plans/2026-10-02_live/plan.md": plan_text("- Task 1.1: a [PENDING]\n"),
            "plans/_archive/2026-Q4/2026-10-01_old/plan.md": plan_text(
                "- Task 1.1: a [DONE 2026-10-01 — `abc1234`; ok]\n"
            ),
        }
    )
    plans = plans_json(root)
    old = plans["2026-10-01_old"]
    assert old["archived"] is True
    assert (old["done"], old["total"]) == (1, 1)
    assert "_archive/2026-Q4/" in old["path"].replace("\\", "/")
    assert plans["2026-10-02_live"]["archived"] is False


def test_json_path_is_relative_and_uses_given_root(make_root, one_plan):
    root = make_root({"plans/2026-10-02_rel/plan.md": plan_text("- Task 1.1: a [DONE]\n")})
    path = one_plan(root, "2026-10-02_rel")["path"].replace("\\", "/")
    assert path.startswith("plans/") and "2026-10-02_rel" in path


def test_missing_order_file_is_not_an_error_and_gives_null_tier(make_root, one_plan, progress):
    root = make_root({"plans/2026-10-02_noorder/plan.md": plan_text("- Task 1.1: a [DONE]\n")})
    rec = one_plan(root, "2026-10-02_noorder")
    assert (rec["done"], rec["total"]) == (1, 1)  # якорь: план разобран и без ORDER.md
    assert rec["tier"] is None
    assert progress(root, "--check").returncode == 0


def test_explicit_order_option_is_used(make_root, one_plan, order_md):
    root = make_root(
        {
            "plans/2026-10-02_ord/plan.md": plan_text("- Task 1.1: a [DONE]\n"),
            "elsewhere/MY_ORDER.md": order_md(tier42=["2026-10-02_ord"]),
        }
    )
    rec = one_plan(root, "2026-10-02_ord", "--order", str(root / "elsewhere" / "MY_ORDER.md"))
    assert rec["tier"] == "4.2"


def test_order_md_tiers_by_basename(make_root, plans_json, order_md):
    root = make_root(
        {
            "plans/p-one/plan.md": plan_text("- Task 1.1: a [DONE]\n"),
            "plans/p-two/plan.md": plan_text("- Task 1.1: a [DONE]\n"),
            "plans/p-three/plan.md": plan_text("- Task 1.1: a [DONE]\n"),
            "plans/p-none/plan.md": plan_text("- Task 1.1: a [DONE]\n"),
            "plans/queue/ORDER.md": order_md(tier41=["p-one"], tier42=["p-two"], tier43=["p-three"]),
        }
    )
    plans = plans_json(root)
    assert {n: plans[n]["tier"] for n in plans} == {"p-one": "4.1", "p-two": "4.2", "p-three": "4.3", "p-none": None}


# =========================================================================== --check: блокирующие и информационные


def _with_order(make_root, files, order_text):
    files = dict(files)
    files["plans/queue/ORDER.md"] = order_text
    return make_root(files)


def test_no_tasks_blocks_for_tier_41(make_root, progress, order_md):
    root = _with_order(
        make_root, {"plans/2026-10-02_empty/plan.md": "# Пустой\n\nПроза.\n"}, order_md(tier41=["2026-10-02_empty"])
    )
    cp = progress(root, "--check")
    assert cp.returncode == 1, check_out(cp)[:500]
    assert any("2026-10-02_empty" in ln for ln in finding_lines(check_out(cp), "NO_TASKS"))


def test_no_tasks_does_not_block_for_tier_43(make_root, progress, order_md):
    root = _with_order(
        make_root, {"plans/2026-10-02_empty/plan.md": "# Пустой\n\nПроза.\n"}, order_md(tier43=["2026-10-02_empty"])
    )
    cp = progress(root, "--check")
    assert cp.returncode == 0, check_out(cp)[:500]
    assert any("2026-10-02_empty" in ln for ln in finding_lines(check_out(cp), "NO_TASKS")), (
        "информационная находка обязана печататься"
    )


def test_no_tasks_does_not_block_for_tier_42_and_unlisted(make_root, progress, order_md):
    files = {"plans/p-wait/plan.md": "# A\n\nПроза.\n", "plans/p-free/plan.md": "# B\n\nПроза.\n"}
    root = _with_order(make_root, files, order_md(tier42=["p-wait"]))
    cp = progress(root, "--check")
    assert cp.returncode == 0, check_out(cp)[:500]
    lines = finding_lines(check_out(cp), "NO_TASKS")  # информационные находки печатаются для обоих
    assert any("p-wait" in ln for ln in lines) and any("p-free" in ln for ln in lines), lines


def test_unknown_status_blocks_for_tier_41(make_root, progress, order_md):
    items = "- Task 1.1: a [DONE]\n- Task 1.2: b [DONE-ish]\n"
    root = _with_order(
        make_root, {"plans/2026-10-02_unk/plan.md": plan_text(items)}, order_md(tier41=["2026-10-02_unk"])
    )
    cp = progress(root, "--check")
    assert cp.returncode == 1, check_out(cp)[:500]
    assert any("1.2" in ln for ln in finding_lines(check_out(cp), "UNKNOWN_STATUS"))


def test_unknown_status_does_not_block_for_tier_43(make_root, progress, order_md):
    items = "- Task 1.1: a [DONE]\n- Task 1.2: b [DONE-ish]\n"
    root = _with_order(
        make_root, {"plans/2026-10-02_unk/plan.md": plan_text(items)}, order_md(tier43=["2026-10-02_unk"])
    )
    cp = progress(root, "--check")
    assert cp.returncode == 0, check_out(cp)[:500]
    assert finding_lines(check_out(cp), "UNKNOWN_STATUS"), "информационная находка обязана печататься"


def test_dup_id_between_two_list_items_blocks(make_root, progress):
    items = "- Task 1.1: a [DONE]\n- Task 1.1: другая [PENDING]\n"
    root = make_root({"plans/2026-10-02_dup/plan.md": plan_text(items)})
    cp = progress(root, "--check")
    assert cp.returncode == 1, check_out(cp)[:500]
    assert any("1.1" in ln for ln in finding_lines(check_out(cp), "DUP_ID"))


def test_dup_heading_between_two_files_does_not_block(make_root, progress):
    root = make_root(
        {
            "plans/2026-10-02_duph/plan.md": "# План\n\nПроза.\n",
            "plans/2026-10-02_duph/phase-1.md": "# Ф1\n\n### Task 2.1 — a\n**Статус:** [DONE]\n",
            "plans/2026-10-02_duph/phase-2.md": "# Ф2\n\n### Task 2.1 — a\n**Статус:** [DONE]\n",
        }
    )
    cp = progress(root, "--check")
    out = check_out(cp)
    assert cp.returncode == 0, out[:500]
    assert any("2.1" in ln for ln in finding_lines(out, "DUP_HEADING")), "информационная DUP_HEADING обязана быть"
    assert not finding_lines(out, "DUP_ID")


def test_all_done_not_archived_info_and_only_for_plans_without_open_tasks(make_root, progress):
    root = make_root(
        {
            "plans/2026-10-02_finished/plan.md": plan_text("- Task 1.1: a [DONE]\n- Task 1.2: b [DEFERRED]\n"),
            "plans/2026-10-02_notyet/plan.md": plan_text("- Task 1.1: a [DONE]\n- Task 1.2: b [PENDING]\n"),
        }
    )
    cp = progress(root, "--check")
    lines = finding_lines(check_out(cp), "ALL_DONE_NOT_ARCHIVED")
    assert any("2026-10-02_finished" in ln for ln in lines), check_out(cp)[:500]
    assert not any("2026-10-02_notyet" in ln for ln in lines)
    assert cp.returncode == 0


def test_all_done_not_archived_is_not_reported_for_archived_plan(make_root, progress):
    root = make_root(
        {
            "plans/2026-10-02_live/plan.md": plan_text("- Task 1.1: a [DONE]\n"),
            "plans/_archive/2026-Q4/2026-10-01_old/plan.md": plan_text("- Task 1.1: a [DONE]\n"),
        }
    )
    lines = finding_lines(check_out(progress(root, "--check")), "ALL_DONE_NOT_ARCHIVED")
    assert any("2026-10-02_live" in ln for ln in lines), "якорь: живой закрытый план обязан быть назван"
    assert not any("2026-10-01_old" in ln for ln in lines)


def test_no_date_in_name_is_informational(make_root, progress):
    root = make_root(
        {
            "plans/undated-plan/plan.md": plan_text("- Task 1.1: a [PENDING]\n"),
            "plans/2026-10-02_dated/plan.md": plan_text("- Task 1.1: a [PENDING]\n"),
        }
    )
    cp = progress(root, "--check")
    lines = finding_lines(check_out(cp), "NO_DATE_IN_NAME")
    assert any("undated-plan" in ln for ln in lines), check_out(cp)[:500]
    assert not any("2026-10-02_dated" in ln for ln in lines)
    assert cp.returncode == 0


def test_old_archive_plan_in_unknown_format_gives_no_findings(make_root, progress, plans_json):
    root = make_root(
        {
            "plans/2026-10-02_live/plan.md": plan_text("- Task 1.1: a [PENDING]\n"),
            "plans/_archive/2026-Q1/2026-01-05_legacy.md": "# Старый план\n\nТолько проза, задач в эталоне нет.\n",
        }
    )
    cp = progress(root, "--check")
    assert cp.returncode == 0, check_out(cp)[:500]
    assert "legacy" in plans_json(root), "якорь: архивный план виден в --json"
    assert not any(
        "legacy" in ln for ln in check_out(cp).splitlines() if re.search(r"NO_TASKS|UNKNOWN_STATUS|DUP_|NO_DATE", ln)
    )


# =========================================================================== храповик (--baseline)


RATCHET_PLAN = "2026-10-02_rt"


def _ratchet_root(make_root, order_md):
    items = "- Task 1.1: a [DONE-ish]\n- Task 1.2: b [DONE]\n"
    return _with_order(make_root, {f"plans/{RATCHET_PLAN}/plan.md": plan_text(items)}, order_md(tier41=[RATCHET_PLAN]))


def test_ratchet_new_finding_outside_baseline_blocks(make_root, progress, order_md, tmp_path):
    root = _ratchet_root(make_root, order_md)
    base = tmp_path / "base_empty.txt"
    base.write_text("", encoding="utf-8")
    assert progress(root, "--check", "--baseline", str(base)).returncode == 1


def test_ratchet_finding_in_baseline_does_not_block(make_root, progress, order_md, tmp_path):
    root = _ratchet_root(make_root, order_md)
    base = tmp_path / "base_known.txt"
    base.write_text(f"{RATCHET_PLAN}:UNKNOWN_STATUS:1.1\n", encoding="utf-8")
    assert progress(root, "--check").returncode == 1  # контроль: без базы та же находка блокирует
    cp = progress(root, "--check", "--baseline", str(base))
    assert cp.returncode == 0, check_out(cp)[:500]


def test_ratchet_baseline_key_includes_id_so_new_id_in_known_plan_blocks(make_root, progress, order_md, tmp_path):
    root = _ratchet_root(make_root, order_md)
    base = tmp_path / "base_other_id.txt"
    base.write_text(f"{RATCHET_PLAN}:UNKNOWN_STATUS:9.9\n", encoding="utf-8")
    assert progress(root, "--check", "--baseline", str(base)).returncode == 1


def test_ratchet_baseline_of_another_plan_does_not_cover(make_root, progress, order_md, tmp_path):
    root = _ratchet_root(make_root, order_md)
    base = tmp_path / "base_other_plan.txt"
    base.write_text("some-other-plan:UNKNOWN_STATUS:1.1\n", encoding="utf-8")
    assert progress(root, "--check", "--baseline", str(base)).returncode == 1


def test_ratchet_no_tasks_key_has_no_id(make_root, progress, order_md, tmp_path):
    root = _with_order(make_root, {"plans/2026-10-02_nt/plan.md": "# Пустой\n"}, order_md(tier41=["2026-10-02_nt"]))
    assert progress(root, "--check").returncode == 1  # контроль: без базы блокирует
    base = tmp_path / "base_nt.txt"
    base.write_text("2026-10-02_nt:NO_TASKS\n", encoding="utf-8")
    assert progress(root, "--check", "--baseline", str(base)).returncode == 0


def test_ratchet_dup_id_key_includes_id(make_root, progress, tmp_path):
    items = "- Task 1.1: a [DONE]\n- Task 1.1: b [PENDING]\n"
    root = make_root({"plans/2026-10-02_dupb/plan.md": plan_text(items)})
    wrong = tmp_path / "base_dup_wrong.txt"
    wrong.write_text("2026-10-02_dupb:DUP_ID:7.7\n", encoding="utf-8")
    right = tmp_path / "base_dup_right.txt"
    right.write_text("2026-10-02_dupb:DUP_ID:1.1\n", encoding="utf-8")
    assert progress(root, "--check", "--baseline", str(wrong)).returncode == 1
    assert progress(root, "--check", "--baseline", str(right)).returncode == 0


# =========================================================================== --html


def _html(progress, root, tmp_path, *flags):
    out = tmp_path / "out" / "page.html"
    cp = progress(root, "--html", str(out), *flags)
    assert cp.returncode == 0, f"--html exit {cp.returncode}: {cp.stderr[:400]!r}"
    assert out.is_file(), "--html не создал файл"
    return out.read_text(encoding="utf-8")


def test_html_plan_block_has_summary_with_progress(make_root, progress, parse_html, tmp_path, norm_key):
    items = "- Task 1.1: a [DONE]\n- Task 1.2: b [DEFERRED]\n- Task 1.3: c [PENDING]\n"
    root = make_root({"plans/2026-10-02_html/plan.md": plan_text(items)})
    page = parse_html(_html(progress, root, tmp_path))
    names = [norm_key(n) for n in page.plans]
    assert names == ["2026-10-02_html"], names
    key = page.plans[0]
    assert page.plan_has_summary_progress.get(key) is True
    prog = page.plan_progress[key]
    assert (float(prog["value"]), float(prog["max"])) == (1.0, 2.0)  # 1 из 2: DEFERRED не в знаменателе


def test_html_cell_count_equals_all_tasks_including_dropped_and_unknown(make_root, progress, parse_html, tmp_path):
    items = (
        "- Task 1.1: a [DONE]\n- Task 1.2: b [PENDING]\n- Task 1.3: c [IN PROGRESS]\n- Task 1.4: d [BLOCKED]\n"
        "- Task 1.5: e [DEFERRED]\n- Task 1.6: f [SUPERSEDED]\n- Task 1.7: g [DONE-ish]\n"
    )
    root = make_root({"plans/2026-10-02_cells/plan.md": plan_text(items)})
    page = parse_html(_html(progress, root, tmp_path))
    cells = page.plan_cells[page.plans[0]]
    assert len(cells) == 7
    assert sorted(cells) == sorted(["done", "pending", "in_progress", "blocked", "deferred", "superseded", "unknown"])


def test_html_order_follows_order_md_tables_then_unlisted_then_archive(
    make_root, progress, parse_html, tmp_path, order_md, norm_key
):
    files = {
        f"plans/{n}/plan.md": plan_text("- Task 1.1: a [PENDING]\n")
        for n in ("p-a", "p-b", "c-wait", "d-closed", "u-2", "u-1")
    }
    files["plans/_archive/2026-Q4/2026-10-01_arch/plan.md"] = plan_text("- Task 1.1: a [DONE]\n")
    files["plans/queue/ORDER.md"] = order_md(tier41=["p-b", "p-a"], tier42=["c-wait"], tier43=["d-closed"])
    root = make_root(files)
    page = parse_html(_html(progress, root, tmp_path))
    names = [norm_key(n) for n in page.plans]
    # §4.1 по порядку таблицы (b раньше a, хотя по алфавиту наоборот), §4.2, §4.3, вне ORDER по имени, затем архив
    assert names == ["p-b", "p-a", "c-wait", "d-closed", "u-1", "u-2", "2026-10-01_arch"], names
    assert page.plan_in_archive["2026-10-01_arch"] is True
    assert all(not page.plan_in_archive[n] for n in names[:-1])


def test_html_swapping_rows_in_tier_41_swaps_plans(make_root, progress, parse_html, tmp_path, order_md, norm_key):
    base = {f"plans/{n}/plan.md": plan_text("- Task 1.1: a [PENDING]\n") for n in ("p-a", "p-b")}
    root_ab = make_root({**base, "plans/queue/ORDER.md": order_md(tier41=["p-a", "p-b"])})
    root_ba = make_root({**base, "plans/queue/ORDER.md": order_md(tier41=["p-b", "p-a"])})
    ab = [norm_key(n) for n in parse_html(_html(progress, root_ab, tmp_path / "ab")).plans]
    ba = [norm_key(n) for n in parse_html(_html(progress, root_ba, tmp_path / "ba")).plans]
    assert (ab, ba) == (["p-a", "p-b"], ["p-b", "p-a"])


def test_html_broken_link_in_order_md_does_not_break_page(
    make_root, progress, parse_html, tmp_path, order_md, norm_key
):
    ghost = "| [ghost-plan](../ghost-plan/plan.md) | С | статус | шаг |"
    files = {
        "plans/p-live/plan.md": plan_text("- Task 1.1: a [DONE]\n"),
        "plans/queue/ORDER.md": order_md(tier41=["p-live"], extra_41_rows=[ghost]),
    }
    page = parse_html(_html(progress, make_root(files), tmp_path))
    assert [norm_key(n) for n in page.plans] == ["p-live"]


def test_html_archive_section_holds_archived_plan_only(make_root, progress, parse_html, tmp_path, norm_key):
    files = {
        "plans/2026-10-02_live/plan.md": plan_text("- Task 1.1: a [PENDING]\n"),
        "plans/_archive/2026-Q4/2026-10-01_old/plan.md": plan_text("- Task 1.1: a [DONE]\n"),
    }
    raw = _html(progress, make_root(files), tmp_path)
    page = parse_html(raw)
    assert re.search(r'<details[^>]*\bid\s*=\s*["\']archive["\']', raw), 'нет <details id="archive">'
    by_name = {norm_key(n): page.plan_in_archive[n] for n in page.plans}
    assert by_name == {"2026-10-02_live": False, "2026-10-01_old": True}


def test_html_has_no_external_resources(make_root, progress, parse_html, tmp_path):
    files = {
        "plans/2026-10-02_live/plan.md": plan_text("- Task 1.1: a [DONE 2026-10-02 — `abc1234`; ok]\n"),
        "plans/_archive/2026-Q4/2026-10-01_old/plan.md": plan_text("- Task 1.1: a [DONE]\n"),
    }
    raw = _html(progress, make_root(files), tmp_path)
    page = parse_html(raw)
    assert len(page.plans) == 2, "якорь: страница не пустая"
    assert page.external_refs == []
    assert not re.search(r"@import\s+(?:url\(\s*)?[\"']?\s*(?:https?:)?//", "".join(page.style_text))
    assert not re.search(r"""(?:src|href)\s*=\s*["']?\s*https?://""", raw)


def test_html_has_light_and_dark_theme(make_root, progress, parse_html, tmp_path):
    # ИНТЕРПРЕТАЦИЯ тестера: «светлая и тёмная тема» = media-запрос prefers-color-scheme в <style>
    raw = _html(progress, make_root({"plans/2026-10-02_t/plan.md": plan_text("- Task 1.1: a [DONE]\n")}), tmp_path)
    assert "prefers-color-scheme" in "".join(parse_html(raw).style_text)
