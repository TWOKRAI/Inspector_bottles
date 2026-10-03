# ruff: noqa: E501  -- литералы-фикстуры планов и ожидания в одну строку, форматтер их не переносит
"""Приёмка Task 3.1 — слепые тесты поля `После:`/`After:`, `(после N.M)`, `ready`, `DEP_*`.

Источник: plans/2026-10-02_plans-progress-dashboard/tasks/3.1.md (DESIGN, ACCEPTANCE P1–P8) и design.md
(«Фаза 3: порядок между планами»). Реализацию тестер не видел.

Только CLI в subprocess: `plans_progress.py --root R (--json | --check [--baseline P]) [--order P]`.
Ожидания — литералы из ACCEPTANCE, не вычисленные из вывода.

Договорённости чтения (в тексте задачи неоднозначно; выбрано строгое чтение):
- имена планов `A`, `B`, `C` — basename каталога/файла; `A` в фикстуре «закрыт» = все пункты DONE;
- `ready` ПЛАНА по DESIGN: «не закрыт, нет waiting_on, каждый after найден и закрыт, не в цикле»;
  поэтому проверяемый план всегда держит открытый пункт (PENDING), иначе он сам «закрыт» и `ready` = false;
- содержимое `dep_cycle` в задаче не уточнено (список участников цикла или его соседей): тест требует
  непустой список из имён планов фикстуры, а не точное значение;
- маркер списка `*` и цитата `>` — «маркер списка/цитата» из DESIGN; ограждение `~~~` — тоже ограждение кода;
- строка находки: `<КОД> <план>[:<id>] <blocking|info> — <текст>` (решение 3 design.md).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

SECTION = "## Порядок выполнения\n\n"
OPEN_ITEM = "- Task 1.1: x [PENDING]\n"
DONE_ITEM = "- Task 1.1: x [DONE]\n"

NEW_PLAN_KEYS = ["after", "after_reason", "waiting_on", "ready", "dep_unknown", "dep_cycle"]


# =========================================================================== хелперы


def plan_text(header: str = "", items: str = OPEN_ITEM) -> str:
    """План: заголовок, блок шапки `header` (с 3-й строки), раздел порядка с пунктами `items`."""
    head = "# План\n\n" + (header + "\n\n" if header else "")
    return head + SECTION + items


def field(value: str, word: str = "После") -> str:
    return f"- **{word}:** {value}"


def check_out(cp) -> str:
    return cp.stdout + "\n" + cp.stderr


def findings(out: str, code: str, ref: str) -> list[tuple[str, str]]:
    """Строки `<КОД> <ref> <blocking|info> …` -> [(severity, строка)]; `ref` совпадает целиком (B != B:1.2)."""
    pat = re.compile(rf"^\s*{re.escape(code)} {re.escape(ref)} (blocking|info)\b.*$", re.MULTILINE)
    return [(m.group(1), m.group(0)) for m in pat.finditer(out)]


def need(rec: dict, key: str, what: str = "запись") -> object:
    assert key in rec, f"в --json нет ключа {key!r} у записи ({what}); есть: {list(rec)}"
    return rec[key]


def tasks_by_id(rec: dict) -> dict[str, dict]:
    return {t["id"]: t for t in rec["tasks"]}


@pytest.fixture
def plans_list(progress):
    """plans_list(root) -> список записей --json как есть (в нём бывают две записи с одним именем)."""
    import json

    def _call(root):
        cp = progress(root, "--json")
        assert cp.returncode == 0, f"--json exit {cp.returncode}: {cp.stderr[:300]!r}"
        return json.loads(cp.stdout)

    return _call


# =========================================================================== контроли: фикстуры читаются (зелёные сегодня)


def test_sanity_dir_plan_with_header_field_is_read(make_root, one_plan):
    root = make_root({"plans/A/plan.md": plan_text("", DONE_ITEM), "plans/B/plan.md": plan_text(field("A"))})
    assert [t["id"] for t in one_plan(root, "B")["tasks"]] == ["1.1"]


def test_sanity_single_file_plan_is_read(make_root, one_plan):
    root = make_root({"plans/A.md": plan_text("", DONE_ITEM)})
    rec = one_plan(root, "A")
    assert (rec["done"], rec["total"]) == (1, 1)


def test_sanity_archived_plan_is_read(make_root, one_plan):
    root = make_root({"plans/_archive/2026-Q4/A/plan.md": plan_text("", OPEN_ITEM)})
    rec = one_plan(root, "A")
    assert rec["archived"] is True and [t["id"] for t in rec["tasks"]] == ["1.1"]


def test_sanity_order_fixture_has_tier_and_clean_check(make_root, one_plan, progress, order_md):
    # контроль для P6: фикстура с §4.1 без поля `После:` не даёт ни одной блокирующей находки
    root = make_root(
        {
            "plans/2026-10-03_b/plan.md": plan_text(),
            "plans/queue/ORDER.md": order_md(tier41=["2026-10-03_b"]),
        }
    )
    assert one_plan(root, "2026-10-03_b")["tier"] == "4.1"
    cp = progress(root, "--check")
    assert cp.returncode == 0, check_out(cp)[:500]
    assert "DEP_" not in check_out(cp)


def test_sanity_task_with_after_clause_is_read_with_status(make_root, one_plan, statuses):
    items = "- Task 1.1: x [PENDING]\n- Task 1.2: y [PENDING] (после 1.1)\n"
    root = make_root({"plans/2026-10-03_t/plan.md": plan_text("", items)})
    assert statuses(one_plan(root, "2026-10-03_t")) == {"1.1": "pending", "1.2": "pending"}


# =========================================================================== формат `--json`


def test_json_dependency_keys_are_appended_in_documented_order(make_root, one_plan):
    items = "- Task 1.1: x [PENDING]\n- Task 1.2: y [PENDING] (после 1.1)\n"
    root = make_root({"plans/A/plan.md": plan_text(field("ghost"), items)})
    rec = one_plan(root, "A")
    keys = list(rec)
    assert keys[-7:] == ["tasks", *NEW_PLAN_KEYS], f"ключи плана: {keys}"
    for t in rec["tasks"]:
        assert list(t)[-3:] == ["ref", "after", "ready"], f"ключи задачи: {list(t)}"


# =========================================================================== P1: план без поля


def test_p1_plan_without_field_is_independent_and_ready(make_root, one_plan):
    root = make_root({"plans/B/plan.md": plan_text()})
    rec = one_plan(root, "B")
    assert need(rec, "after") == []
    assert need(rec, "after_reason") == ""
    assert need(rec, "waiting_on") == []
    assert need(rec, "dep_unknown") == []
    assert need(rec, "dep_cycle") == []
    assert need(rec, "ready") is True


# =========================================================================== P2: готовность по состоянию ожидаемого плана

LIVE_ARCHIVE_COPIES = {
    "plans/A/plan.md": plan_text("", OPEN_ITEM),
    "plans/_archive/2026-Q4/A/plan.md": plan_text("", OPEN_ITEM),
}

# (A-файлы, ORDER-таблицы, ожидаемая ready у B). У B — открытый пункт и `- **После:** A`.
AWAITED_CASES = {
    "open_pending": ({"plans/A/plan.md": plan_text("", "- Task 1.1: x [PENDING]\n")}, {}, False),
    "open_in_progress": ({"plans/A/plan.md": plan_text("", "- Task 1.1: x [IN PROGRESS]\n")}, {}, False),
    "open_blocked": ({"plans/A/plan.md": plan_text("", "- Task 1.1: x [BLOCKED]\n")}, {}, False),
    "open_unknown_status": ({"plans/A/plan.md": plan_text("", "- Task 1.1: x [DONE-ish]\n")}, {}, False),
    "open_done_plus_pending": (
        {"plans/A/plan.md": plan_text("", "- Task 1.1: x [DONE]\n- Task 1.2: y [PENDING]\n")},
        {},
        False,
    ),
    "open_no_tasks_at_all": ({"plans/A/plan.md": "# План\n\nТолько проза.\n"}, {}, False),
    "closed_all_done": ({"plans/A/plan.md": plan_text("", DONE_ITEM)}, {}, True),
    "closed_done_plus_deferred": (
        {"plans/A/plan.md": plan_text("", "- Task 1.1: x [DONE]\n- Task 1.2: y [DEFERRED]\n")},
        {},
        True,
    ),
    "closed_only_deferred_and_superseded": (
        {"plans/A/plan.md": plan_text("", "- Task 1.1: x [DEFERRED]\n- Task 1.2: y [SUPERSEDED]\n")},
        {},
        True,
    ),
    "closed_archived_with_open_task": (
        {"plans/_archive/2026-Q4/A/plan.md": plan_text("", OPEN_ITEM)},
        {},
        True,
    ),
    "closed_tier_43_with_open_task": ({"plans/A/plan.md": plan_text("", OPEN_ITEM)}, {"tier43": ["A"]}, True),
    "closed_header_status_done_with_open_task": (
        {"plans/A/plan.md": plan_text("- **Статус:** DONE", OPEN_ITEM)},
        {},
        True,
    ),
    "two_copies_live_open_archived_wins": (LIVE_ARCHIVE_COPIES, {}, True),
}


@pytest.mark.parametrize("case", list(AWAITED_CASES))
def test_p2_plan_after_a_plan_is_ready_only_when_that_plan_is_closed(make_root, plans_list, order_md, case):
    a_files, tiers, expected_ready = AWAITED_CASES[case]
    files = dict(a_files)
    files["plans/B/plan.md"] = plan_text(field("A"))
    if tiers:
        files["plans/queue/ORDER.md"] = order_md(**tiers)
    recs = [r for r in plans_list(make_root(files)) if r["plan"].removesuffix(".md") == "B"]
    assert len(recs) == 1, [r["plan"] for r in recs]
    rec = recs[0]
    assert need(rec, "after") == ["A"]
    assert need(rec, "dep_unknown") == [], "план A найден, неизвестным его считать нельзя"
    assert need(rec, "ready") is expected_ready


# =========================================================================== P3: значение поля — условия, списки, причина

# (значение поля, какие из A/C открыты (PENDING), after, waiting_on, after_reason, ready)
FIELD_CASES = {
    "condition_only": ("⛔ железо", (), [], ["железо"], "", False),
    "plan_then_condition": ("A, ⛔ железо", (), ["A"], ["железо"], "", False),
    "condition_then_plan": ("⛔ железо, A", (), ["A"], ["железо"], "", False),
    "multi_word_condition": ("⛔ решение владельца", (), [], ["решение владельца"], "", False),
    "two_plans_both_closed": ("A, C", (), ["A", "C"], [], "", True),
    "two_plans_no_space": ("A,C", (), ["A", "C"], [], "", True),
    "two_plans_second_open": ("A, C", ("C",), ["A", "C"], [], "", False),
    "two_plans_first_open": ("A, C", ("A",), ["A", "C"], [], "", False),
    "two_plans_both_open": ("A, C", ("A", "C"), ["A", "C"], [], "", False),
    "reason_after_em_dash": ("A — ждёт API", (), ["A"], [], "ждёт API", True),
    "reason_after_en_dash": ("A – ждёт API", (), ["A"], [], "ждёт API", True),
    "reason_cut_at_first_dash": ("A — ждёт API — и ещё", (), ["A"], [], "ждёт API — и ещё", True),
    "condition_with_reason": ("A, ⛔ железо — причина", (), ["A"], ["железо"], "причина", False),
}


@pytest.mark.parametrize("case", list(FIELD_CASES))
def test_p3_field_value_splits_into_plans_conditions_and_reason(make_root, one_plan, case):
    value, open_plans, exp_after, exp_waiting, exp_reason, exp_ready = FIELD_CASES[case]
    files = {f"plans/{n}/plan.md": plan_text("", OPEN_ITEM if n in open_plans else DONE_ITEM) for n in ("A", "C")}
    files["plans/B/plan.md"] = plan_text(field(value))
    rec = one_plan(make_root(files), "B")
    assert need(rec, "after") == exp_after
    assert need(rec, "waiting_on") == exp_waiting
    assert need(rec, "after_reason") == exp_reason
    assert need(rec, "dep_unknown") == [], "условие ⛔ — не имя плана, неизвестным оно не считается"
    assert need(rec, "ready") is exp_ready


# =========================================================================== P4: формы записи и окно поиска


def _field_at_line(n: int, line: str) -> str:
    """Блок шапки так, чтобы `line` стояла ровно на строке n файла (1 — `# План`, 2 — пустая, дальше блок)."""
    return "\n".join(["заметка"] * (n - 3) + [line])


# (блок шапки B, раскладка плана A, ожидаемый after)
RECOGNITION_CASES = {
    "bold_list_dir": (field("A"), "dir", ["A"]),
    "bold_list_single_file": (field("A"), "file", ["A"]),
    "backticks": (field("`A`"), "dir", ["A"]),
    "md_link_to_plan_md": (field("[A](../A/plan.md)"), "dir", ["A"]),
    "md_link_to_file": (field("[A](../A.md)"), "file", ["A"]),
    "repeat_kept_once": (field("A, A"), "dir", ["A"]),
    "repeat_across_forms_kept_once": (field("`A`, [A](../A/plan.md)"), "dir", ["A"]),
    "english_word": (field("A", "After"), "dir", ["A"]),
    "no_list_marker": ("**После:** A", "dir", ["A"]),
    "star_list_marker": ("* **После:** A", "dir", ["A"]),
    "quote": ("> **После:** A", "dir", ["A"]),
    "no_bold": ("- После: A", "dir", ["A"]),
    "line_30_is_read": (_field_at_line(30, field("A")), "dir", ["A"]),
    "line_31_is_not_read": (_field_at_line(31, field("A")), "dir", []),
    "inside_backtick_fence_is_ignored": ("```\n" + field("ghost") + "\n```", "dir", []),
    "inside_tilde_fence_is_ignored": ("~~~\n" + field("ghost") + "\n~~~", "dir", []),
    "field_after_a_fence_is_found": ("```\n" + field("ghost") + "\n```\n\n" + field("A"), "dir", ["A"]),
    "first_matching_line_wins": (field("A") + "\n" + field("C"), "dir", ["A"]),
}


@pytest.mark.parametrize("case", list(RECOGNITION_CASES))
def test_p4_field_forms_and_search_window(make_root, one_plan, case):
    header, layout, expected_after = RECOGNITION_CASES[case]
    files = {"plans/C/plan.md": plan_text("", DONE_ITEM), "plans/B/plan.md": plan_text(header)}
    files["plans/A.md" if layout == "file" else "plans/A/plan.md"] = plan_text("", DONE_ITEM)
    rec = one_plan(make_root(files), "B")
    assert need(rec, "after") == expected_after
    assert need(rec, "dep_unknown") == [], "имя найдено среди планов: A — каталог или файл"
    assert need(rec, "ready") is True


# =========================================================================== P5: DEP_UNKNOWN и DEP_CYCLE у планов

# файлы; ожидание по планам: (after|None, dep_unknown, цикл?, ready); строки находок: (код, ссылка) -> сколько; тексты
UNKNOWN_FILES = {"plans/B/plan.md": plan_text(field("ghost")), "plans/C/plan.md": plan_text()}
CYCLE_FILES = {
    "plans/A/plan.md": plan_text(field("B")),
    "plans/B/plan.md": plan_text(field("A")),
    "plans/C/plan.md": plan_text(),
}

PLAN_FINDING_CASES = {
    "unknown_plan": dict(
        files=UNKNOWN_FILES,
        plans={"B": (["ghost"], ["ghost"], False, False), "C": (None, [], False, True)},
        lines={("DEP_UNKNOWN", "B"): 1, ("DEP_UNKNOWN", "C"): 0, ("DEP_CYCLE", "B"): 0},
        texts=[("DEP_UNKNOWN", "B", r"— нет плана ghost\b")],
    ),
    "two_unknown_names_two_findings": dict(
        files={"plans/B/plan.md": plan_text(field("ghost1, ghost2"))},
        plans={"B": (["ghost1", "ghost2"], ["ghost1", "ghost2"], False, False)},
        lines={("DEP_UNKNOWN", "B"): 2},
        texts=[("DEP_UNKNOWN", "B", r"— нет плана ghost1\b"), ("DEP_UNKNOWN", "B", r"— нет плана ghost2\b")],
    ),
    "same_unknown_name_twice_is_one_finding": dict(
        files={"plans/B/plan.md": plan_text(field("ghost, ghost"))},
        plans={"B": (["ghost"], ["ghost"], False, False)},
        lines={("DEP_UNKNOWN", "B"): 1},
        texts=[],
    ),
    "cycle_a_b": dict(
        files=CYCLE_FILES,
        plans={"A": (["B"], [], True, False), "B": (["A"], [], True, False), "C": (None, [], False, True)},
        lines={("DEP_CYCLE", "A"): 1, ("DEP_CYCLE", "B"): 1, ("DEP_CYCLE", "C"): 0, ("DEP_UNKNOWN", "A"): 0},
        texts=[],
    ),
    "self_reference_is_a_cycle": dict(
        files={"plans/A/plan.md": plan_text(field("A")), "plans/C/plan.md": plan_text()},
        plans={"A": (["A"], [], True, False), "C": (None, [], False, True)},
        lines={("DEP_CYCLE", "A"): 1, ("DEP_CYCLE", "C"): 0},
        texts=[],
    ),
    "archived_member_breaks_the_cycle": dict(
        files={
            "plans/_archive/2026-Q4/A/plan.md": plan_text(field("B")),
            "plans/B/plan.md": plan_text(field("A")),
        },
        plans={"B": (["A"], [], False, True)},
        lines={("DEP_CYCLE", "A"): 0, ("DEP_CYCLE", "B"): 0, ("DEP_UNKNOWN", "B"): 0},
        texts=[],
    ),
}


@pytest.mark.parametrize("case", list(PLAN_FINDING_CASES))
def test_p5_unknown_name_and_cycle_between_plans(make_root, plans_list, progress, case):
    spec = PLAN_FINDING_CASES[case]
    root = make_root(spec["files"])
    by_name = {r["plan"].removesuffix(".md"): r for r in plans_list(root) if not r["archived"]}
    for name, (exp_after, exp_unknown, in_cycle, exp_ready) in spec["plans"].items():
        rec = by_name[name]
        if exp_after is not None:
            assert need(rec, "after") == exp_after, name
        assert need(rec, "dep_unknown") == exp_unknown, name
        cyc = need(rec, "dep_cycle")
        if in_cycle:
            assert cyc and set(cyc) <= {"A", "B"}, (
                f"{name}: dep_cycle должен назвать участников цикла из A/B, получено {cyc!r}"
            )
        else:
            assert cyc == [], name
        assert need(rec, "ready") is exp_ready, name
    out = check_out(progress(root, "--check"))
    for (code, ref), count in spec["lines"].items():
        got = findings(out, code, ref)
        assert len(got) == count, f"{code} {ref}: ждали {count} строк(и), получено {got!r}\n{out[:600]}"
        assert all(sev == "info" for sev, _ in got), f"вне §4.1 находка info: {got!r}"
    for code, ref, pattern in spec["texts"]:
        assert any(re.search(pattern, ln) for _, ln in findings(out, code, ref)), (
            f"нет строки {code} {ref} с текстом {pattern!r}\n{out[:600]}"
        )


# =========================================================================== P6: блокировка только в §4.1

B41 = "2026-10-03_b"
A41 = "2026-10-03_a"

P6_CASES = {
    "unknown_in_41_blocks": dict(
        kind="unknown",
        tiers={"tier41": [B41]},
        baseline=None,
        exit=1,
        sev={("DEP_UNKNOWN", B41): "blocking"},
        absent=[],
    ),
    "unknown_in_42_is_info": dict(
        kind="unknown",
        tiers={"tier42": [B41]},
        baseline=None,
        exit=0,
        sev={("DEP_UNKNOWN", B41): "info"},
        absent=[],
    ),
    "unknown_unlisted_is_info": dict(
        kind="unknown", tiers=None, baseline=None, exit=0, sev={("DEP_UNKNOWN", B41): "info"}, absent=[]
    ),
    "cycle_both_in_41_blocks": dict(
        kind="cycle",
        tiers={"tier41": [A41, B41]},
        baseline=None,
        exit=1,
        sev={("DEP_CYCLE", A41): "blocking", ("DEP_CYCLE", B41): "blocking"},
        absent=[],
    ),
    "cycle_one_in_41_one_in_42": dict(
        kind="cycle",
        tiers={"tier41": [A41], "tier42": [B41]},
        baseline=None,
        exit=1,
        sev={("DEP_CYCLE", A41): "blocking", ("DEP_CYCLE", B41): "info"},
        absent=[],
    ),
    "cycle_both_in_42_is_info": dict(
        kind="cycle",
        tiers={"tier42": [A41, B41]},
        baseline=None,
        exit=0,
        sev={("DEP_CYCLE", A41): "info", ("DEP_CYCLE", B41): "info"},
        absent=[],
    ),
    "archived_plan_is_not_checked": dict(
        kind="archived_unknown",
        tiers={"tier41": [B41]},
        baseline=None,
        exit=1,
        sev={("DEP_UNKNOWN", B41): "blocking"},
        absent=[("DEP_UNKNOWN", "2026-10-03_c")],
    ),
    "baseline_key_plan_colon_code_covers": dict(
        kind="unknown",
        tiers={"tier41": [B41]},
        baseline=f"{B41}:DEP_UNKNOWN\n",
        exit=0,
        sev={("DEP_UNKNOWN", B41): "blocking"},
        absent=[],
    ),
    "baseline_of_another_plan_does_not_cover": dict(
        kind="unknown",
        tiers={"tier41": [B41]},
        baseline="2026-10-03_other:DEP_UNKNOWN\n",
        exit=1,
        sev={("DEP_UNKNOWN", B41): "blocking"},
        absent=[],
    ),
}


def _p6_files(kind: str) -> dict[str, str]:
    if kind == "cycle":
        return {
            f"plans/{A41}/plan.md": plan_text(field(B41)),
            f"plans/{B41}/plan.md": plan_text(field(A41)),
        }
    files = {f"plans/{B41}/plan.md": plan_text(field("ghost"))}
    if kind == "archived_unknown":
        files["plans/_archive/2026-Q4/2026-10-03_c/plan.md"] = plan_text(field("ghost"))
    return files


@pytest.mark.parametrize("case", list(P6_CASES))
def test_p6_dep_findings_block_only_for_tier_41(make_root, progress, order_md, tmp_path, case):
    spec = P6_CASES[case]
    files = _p6_files(spec["kind"])
    if spec["tiers"]:
        files["plans/queue/ORDER.md"] = order_md(**spec["tiers"])
    root = make_root(files)
    flags = ["--check"]
    if spec["baseline"] is not None:
        base = tmp_path / "base.txt"
        base.write_text(spec["baseline"], encoding="utf-8")
        flags += ["--baseline", str(base)]
    cp = progress(root, *flags)
    out = check_out(cp)
    for (code, ref), severity in spec["sev"].items():
        got = findings(out, code, ref)
        assert [s for s, _ in got] == [severity], (
            f"{code} {ref}: ждали одну строку {severity}, получено {got!r}\n{out[:600]}"
        )
    for code, ref in spec["absent"]:
        assert findings(out, code, ref) == [], f"{code} {ref} в архиве не смотрится: {findings(out, code, ref)!r}"
    assert cp.returncode == spec["exit"], f"exit {cp.returncode}, ждали {spec['exit']}\n{out[:600]}"


# =========================================================================== P7: связи между задачами плана

T = "2026-10-03_t"
ARCHIVED_T = "archived"  # маркер раскладки: план лежит в _archive/2026-Q4/
WAITING = "waiting"  # маркер раскладки: шапка `- **После:** ⛔ x`
AWAITS_OPEN = "awaits_open_plan"  # шапка `- **После:** A`, где A открыт

# id -> (after, ready)
TASK_CASES = {
    "pending_dep_blocks": (
        "- Task 1.1: x [PENDING]\n- Task 1.2: y [PENDING] (после 1.1)\n",
        None,
        {"1.1": ([], True), "1.2": (["1.1"], False)},
    ),
    "done_dep_unblocks_and_done_task_is_not_ready": (
        "- Task 1.1: x [DONE]\n- Task 1.2: y [PENDING] (после 1.1)\n",
        None,
        {"1.1": ([], False), "1.2": (["1.1"], True)},
    ),
    "deferred_dep_unblocks": (
        "- Task 1.1: x [DEFERRED]\n- Task 1.2: y [PENDING] (после 1.1)\n",
        None,
        {"1.2": (["1.1"], True)},
    ),
    "superseded_dep_unblocks": (
        "- Task 1.1: x [SUPERSEDED]\n- Task 1.2: y [PENDING] (после 1.1)\n",
        None,
        {"1.2": (["1.1"], True)},
    ),
    "english_word_two_ids_both_done": (
        "- Task 1.0: w [DONE]\n- Task 1.1: x [DONE]\n- Task 1.2: y [PENDING] (after 1.1, 1.0)\n",
        None,
        {"1.2": (["1.1", "1.0"], True)},
    ),
    "english_word_two_ids_one_open": (
        "- Task 1.0: w [DONE]\n- Task 1.1: x [PENDING]\n- Task 1.2: y [PENDING] (after 1.1, 1.0)\n",
        None,
        {"1.1": ([], True), "1.2": (["1.1", "1.0"], False)},
    ),
    "done_task_with_after_is_not_ready": (
        "- Task 1.1: x [DONE]\n- Task 1.2: y [DONE] (после 1.1)\n",
        None,
        {"1.2": (["1.1"], False)},
    ),
    "deferred_task_keeps_its_after_and_is_not_ready": (
        "- Task 4.1: w [PENDING]\n- Task 1.2: y [DEFERRED (после 4.1)]\n",
        None,
        {"4.1": ([], True), "1.2": (["4.1"], False)},
    ),
    "in_progress_task_is_not_ready": ("- Task 1.1: x [IN PROGRESS]\n", None, {"1.1": ([], False)}),
    "blocked_task_is_not_ready": ("- Task 1.1: x [BLOCKED]\n", None, {"1.1": ([], False)}),
    "pending_in_waiting_plan_is_not_ready": ("- Task 1.1: x [PENDING]\n", WAITING, {"1.1": ([], False)}),
    "pending_in_archived_plan_is_not_ready": ("- Task 1.1: x [PENDING]\n", ARCHIVED_T, {"1.1": ([], False)}),
    "pending_in_plan_awaiting_an_open_plan_is_not_ready": (
        "- Task 1.1: x [PENDING]\n",
        AWAITS_OPEN,
        {"1.1": ([], False)},
    ),
    "word_case_is_ignored": (
        "- Task 1.1: x [DONE]\n- Task 1.2: y [PENDING] (После 1.1)\n- Task 1.3: z [PENDING] (AFTER 1.1)\n",
        None,
        {"1.2": (["1.1"], True), "1.3": (["1.1"], True)},
    ),
    "prose_in_parentheses_is_not_a_dependency": (
        "- Task 1b.2b-pre: w [DONE]\n- Task 1b.2c: y [PENDING] (после 1b.2b-pre; до 1b.3; решение 2026-09-25)\n",
        None,
        {"1b.2c": (["1b.2b-pre"], True)},
    ),
    "clause_inside_code_span_is_not_read": (
        "- Task 1.1: x [PENDING]\n- Task 1.2: y `(после 1.1)` [PENDING]\n",
        None,
        {"1.1": ([], True), "1.2": ([], True)},
    ),
}


def _task_root(make_root, items, layout):
    header = {WAITING: field("⛔ x"), AWAITS_OPEN: field("A")}.get(layout, "")
    path = f"plans/_archive/2026-Q4/{T}/plan.md" if layout == ARCHIVED_T else f"plans/{T}/plan.md"
    files = {path: plan_text(header, items)}
    if layout == AWAITS_OPEN:
        files["plans/A/plan.md"] = plan_text("", OPEN_ITEM)
    return make_root(files)


@pytest.mark.parametrize("case", list(TASK_CASES))
def test_p7_task_after_and_ready(make_root, one_plan, case):
    items, layout, expected = TASK_CASES[case]
    rec = one_plan(_task_root(make_root, items, layout), T)
    tasks = tasks_by_id(rec)
    for tid, (exp_after, exp_ready) in expected.items():
        assert tid in tasks, f"задачи {tid} нет в --json: {sorted(tasks)}"
        assert need(tasks[tid], "after", f"задача {tid}") == exp_after, tid
        assert need(tasks[tid], "ready", f"задача {tid}") is exp_ready, tid


# =========================================================================== P7: находки по задачам

TASK_FINDING_CASES = {
    "missing_id_is_unknown": dict(
        items="- Task 1.1: x [PENDING]\n- Task 1.2: y [PENDING] (после 9.9)\n",
        lines={("DEP_UNKNOWN", f"{T}:1.2"): 1, ("DEP_UNKNOWN", f"{T}:1.1"): 0},
        texts=[("DEP_UNKNOWN", f"{T}:1.2", r"— нет задачи 9\.9\b")],
        ready={"1.1": True, "1.2": False},
    ),
    "cycle_between_two_tasks": dict(
        items="- Task 1.1: x [PENDING] (после 1.2)\n- Task 1.2: y [PENDING] (после 1.1)\n",
        lines={("DEP_CYCLE", f"{T}:1.1"): 1, ("DEP_CYCLE", f"{T}:1.2"): 1},
        texts=[],
        ready={"1.1": False, "1.2": False},
    ),
    "task_after_itself_is_a_cycle": dict(
        items="- Task 1.1: x [PENDING] (после 1.1)\n- Task 1.2: y [PENDING]\n",
        lines={("DEP_CYCLE", f"{T}:1.1"): 1, ("DEP_CYCLE", f"{T}:1.2"): 0},
        texts=[],
        ready={"1.1": False, "1.2": True},
    ),
    "closed_task_breaks_the_cycle": dict(
        items="- Task 1.1: x [DONE] (после 1.2)\n- Task 1.2: y [PENDING] (после 1.1)\n",
        lines={("DEP_CYCLE", f"{T}:1.1"): 0, ("DEP_CYCLE", f"{T}:1.2"): 0},
        texts=[],
        ready={"1.2": True},
    ),
    "prose_in_parentheses_gives_no_unknown": dict(
        items="- Task 1b.2b-pre: w [DONE]\n- Task 1b.2c: y [PENDING] (после 1b.2b-pre; до 1b.3; решение 2026-09-25)\n",
        lines={("DEP_UNKNOWN", f"{T}:1b.2c"): 0},
        texts=[],
        ready={"1b.2c": True},
    ),
}


@pytest.mark.parametrize("case", list(TASK_FINDING_CASES))
def test_p7_task_findings_unknown_id_and_cycle(make_root, one_plan, progress, case):
    spec = TASK_FINDING_CASES[case]
    root = make_root({f"plans/{T}/plan.md": plan_text("", spec["items"])})
    tasks = tasks_by_id(one_plan(root, T))
    for tid, exp_ready in spec["ready"].items():
        assert need(tasks[tid], "ready", f"задача {tid}") is exp_ready, tid
    out = check_out(progress(root, "--check"))
    for (code, ref), count in spec["lines"].items():
        got = findings(out, code, ref)
        assert len(got) == count, f"{code} {ref}: ждали {count} строк(и), получено {got!r}\n{out[:600]}"
        assert all(sev == "info" for sev, _ in got), f"план вне §4.1 -> info: {got!r}"
    for code, ref, pattern in spec["texts"]:
        assert any(re.search(pattern, ln) for _, ln in findings(out, code, ref)), (
            f"нет строки {code} {ref} с текстом {pattern!r}\n{out[:600]}"
        )
    if case == "prose_in_parentheses_gives_no_unknown":
        assert "DEP_UNKNOWN" not in out, out[:600]


# =========================================================================== P8: реальное дерево


def test_p8_real_tree_after_of_known_tasks(plans_json):
    plans = plans_json(REPO_ROOT)
    dash = tasks_by_id(plans["2026-10-02_plans-progress-dashboard"])
    gui = tasks_by_id(plans["2026-09-22_gui-service"])
    got = {
        "dashboard 1.1": need(dash["1.1"], "after", "dashboard 1.1"),
        "dashboard 1.2": need(dash["1.2"], "after", "dashboard 1.2"),
        "dashboard 3.2": need(dash["3.2"], "after", "dashboard 3.2"),
        "gui-service 1b.2c": need(gui["1b.2c"], "after", "gui-service 1b.2c"),
    }
    assert got == {
        "dashboard 1.1": ["1.0"],
        "dashboard 1.2": ["1.1"],
        "dashboard 3.2": ["3.1"],
        "gui-service 1b.2c": ["1b.2b-pre"],
    }


def test_p8_real_tree_check_with_baseline_is_green_and_has_no_dep_lines(progress):
    base = REPO_ROOT / "plans" / "queue" / "progress-baseline.txt"
    assert base.is_file(), "базовый файл храповика отсутствует в дереве"
    cp = progress(REPO_ROOT, "--check", "--baseline", str(base))
    out = check_out(cp)
    assert cp.returncode == 0, out[:600]
    assert not [ln for ln in out.splitlines() if "DEP_" in ln], out[:600]
