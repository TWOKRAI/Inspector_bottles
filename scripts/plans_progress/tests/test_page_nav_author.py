# ruff: noqa: E501  -- литералы-фикстуры и ожидания в одну строку
"""Тесты автора на опасности вкладок, якорей и переключателя (Task 7.1).

Приёмку пишет независимый тестер (test_acceptance_page_nav.py, только CLI). Здесь — места, видимые по устройству:
- вкладка `overlaps` недостижима через CLI без git: `to_html` зовётся напрямую с готовыми `Overlap`;
- порядок якорей — порядок ПЕЧАТИ карточек, а не порядок `--json` и не порядок ORDER.md: приоритет переставляет очередь,
  и суффикс `-2` достаётся тому, кто ниже на странице; `--json` обязан дать тот же якорь (общий `card_order`);
- живой план §4.3 и архивный с тем же именем; имя, занятое и под `-archive`; символы вне `[A-Za-z0-9_-]`;
- каждое правило CSS, которое скрывает, само содержит `:has(`: браузер без `:has()` не должен остаться с пустой страницей.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

_MOD_PATH = Path(__file__).resolve().parents[1] / "plans_progress.py"
_spec = importlib.util.spec_from_file_location("plans_progress_page_nav_under_test", _MOD_PATH)
pp = importlib.util.module_from_spec(_spec)
sys.modules["plans_progress_page_nav_under_test"] = pp
_spec.loader.exec_module(pp)

PLAN_MD = "# План\n\n## Порядок выполнения\n\n- Task 1.1: x [PENDING]\n"
SNAPSHOT_XY = (
    "## Снимок 2026-01-10 — где мы сейчас\n\n"
    "| # | Полоса | План | Следующий шаг | Чего ждёт |\n"
    "|---|---|---|---|---|\n"
    "| 1 | С | x.y | шаг | ничего |\n\n"
)


def mem_plan(name: str, archived: bool = False, tier: str | None = "queue", priority: int | None = None) -> pp.Plan:
    rel = f"plans/_archive/2026-Q1/{name}/plan.md" if archived else f"plans/{name}/plan.md"
    p = pp.Plan(name=name, rel=rel, archived=archived, tier=tier)
    p.tasks = [pp.Task("1.1", "x", "pending")]
    p.priority = priority
    return p


def page(live=(), archive=(), overlaps=(), rows=()) -> str:
    return pp.to_html(list(live), list(archive), Path("."), (), "6h", "", list(rows), list(overlaps))


def span_ids(raw: str) -> list[str]:
    return re.findall(r'<span class="anchor" id="([^"]+)"></span>', raw)


def radio_ids(raw: str) -> list[str]:
    return re.findall(r'<input type="radio" name="tab" id="(tab-[a-z]+)"', raw)


# =========================================================================== вкладка «Пересечения»


def test_overlaps_tab_appears_between_who_and_lanes_with_file_count_in_label():
    a = mem_plan("a")
    ov = [
        pp.Overlap("plans/a/x.md", "a", a.rel, ("feat/x", "feat/y")),
        pp.Overlap("plans/a/y.md", "a", a.rel, ("feat/x", "feat/z")),
    ]
    raw = page([a], overlaps=ov)
    assert radio_ids(raw) == ["tab-queue", "tab-waiting", "tab-archive", "tab-who", "tab-overlaps", "tab-lanes"]
    assert '<label for="tab-overlaps">⚠ Пересечения · 2</label>' in raw
    assert '<section id="overlaps">' in raw


def test_overlaps_tab_label_counts_files_not_branches():
    a = mem_plan("a")
    raw = page([a], overlaps=[pp.Overlap("plans/a/x.md", "a", a.rel, ("feat/x", "feat/y", "feat/z"))])
    assert '<label for="tab-overlaps">⚠ Пересечения · 1</label>' in raw


def test_no_overlaps_no_tab():
    assert "tab-overlaps" not in radio_ids(page([mem_plan("a")]))


# =========================================================================== порядок якорей


def test_anchor_suffix_follows_print_order_when_priority_reorders_the_queue():
    xy, x_dot_y = mem_plan("2026-01-07_x-y"), mem_plan("2026-01-07_x.y", priority=1)
    raw = page([xy, x_dot_y])  # в ORDER.md x-y первым, на странице первым идёт x.y (приоритет 1)
    pairs = re.findall(r'data-plan="([^"]+)"[^>]*>\s*<summary>.*?<span class="anchor" id="([^"]+)"', raw, re.S)
    assert pairs == [("2026-01-07_x.y", "plan-2026-01-07_x-y"), ("2026-01-07_x-y", "plan-2026-01-07_x-y-2")]


def test_json_anchor_equals_html_anchor_when_priority_reorders_the_queue():
    xy, x_dot_y = mem_plan("2026-01-07_x-y"), mem_plan("2026-01-07_x.y", priority=1)
    live = [xy, x_dot_y]
    anchors = pp.assign_anchors(pp.card_order(live, []))
    data = json.loads(pp.to_json(live, anchors))  # порядок --json — ORDER.md, а не печати
    assert {r["path"]: r["anchor"] for r in data} == {
        "plans/2026-01-07_x-y/plan.md": "plan-2026-01-07_x-y-2",
        "plans/2026-01-07_x.y/plan.md": "plan-2026-01-07_x-y",
    }
    assert span_ids(page(live)) == ["plan-2026-01-07_x-y", "plan-2026-01-07_x-y-2"]


def test_cli_json_anchor_equals_html_anchor_with_priority_reorder(make_root, order_md, progress, tmp_path):
    marker = "## 4. Контроль планов"
    order = order_md(tier41=["2026-01-07_x-y", "2026-01-07_x.y"])
    root = make_root(
        {
            "plans/queue/ORDER.md": order.replace(marker, SNAPSHOT_XY + marker, 1),
            "plans/2026-01-07_x-y/plan.md": PLAN_MD,
            "plans/2026-01-07_x.y/plan.md": PLAN_MD,
        }
    )
    out = tmp_path / "page.html"
    assert progress(root, "--html", str(out)).returncode == 0
    cp = progress(root, "--json")
    assert cp.returncode == 0, cp.stderr[:300]
    assert span_ids(out.read_text(encoding="utf-8")) == ["plan-2026-01-07_x-y", "plan-2026-01-07_x-y-2"]
    assert {r["path"]: r["anchor"] for r in json.loads(cp.stdout)} == {
        "plans/2026-01-07_x-y/plan.md": "plan-2026-01-07_x-y-2",
        "plans/2026-01-07_x.y/plan.md": "plan-2026-01-07_x-y",
    }


# =========================================================================== §4.3, архив, символы


def test_closed_live_plan_and_archived_plan_with_the_same_name():
    closed = mem_plan("2026-01-01_a", tier="closed")
    arch = mem_plan("2026-01-01_a", archived=True)
    assert span_ids(page([closed], [arch])) == ["plan-2026-01-01_a", "plan-2026-01-01_a-archive"]


def test_assign_anchors_literal_cases():
    live_n, live_n2 = mem_plan("n"), mem_plan("n", tier="waiting")
    arch_n, arch_n2 = mem_plan("n", archived=True), mem_plan("n", archived=True)
    got = pp.assign_anchors([live_n, live_n2, arch_n, arch_n2])
    assert [got[id(p)] for p in (live_n, live_n2, arch_n, arch_n2)] == [
        "plan-n",
        "plan-n-2",
        "plan-n-archive",
        "plan-n-3",
    ]


def test_archive_name_taken_by_a_live_card_falls_through_to_numeric_suffix():
    live_n, live_n_archive = mem_plan("n"), mem_plan("n-archive")
    arch_n = mem_plan("n", archived=True)
    got = pp.assign_anchors([live_n, live_n_archive, arch_n])
    assert [got[id(p)] for p in (live_n, live_n_archive, arch_n)] == ["plan-n", "plan-n-archive", "plan-n-2"]


def test_slug_replaces_characters_outside_the_safe_set():
    p = mem_plan('a b.c"d<e>')
    assert pp.assign_anchors([p])[id(p)] == "plan-a-b-c-d-e-"


def test_plan_html_without_anchor_has_neither_link_nor_span():
    raw = pp._plan_html(mem_plan("a"), False)
    assert "plan-link" not in raw and 'class="anchor"' not in raw


def test_to_json_without_anchors_has_no_anchor_key():
    assert "anchor" not in json.loads(pp.to_json([mem_plan("a")]))[0]


# =========================================================================== CSS: скрывающие правила держат :has(


def _css_rules() -> list[tuple[list[str], str]]:
    """[(селекторы верхнего уровня, тело)] для каждого простого правила `CSS`."""
    rules = []
    for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", pp.CSS):
        parts, depth, cur = [], 0, ""
        for ch in sel:
            depth += (ch == "(") - (ch == ")")
            if ch == "," and depth == 0:
                parts.append(cur.strip())
                cur = ""
            else:
                cur += ch
        parts.append(cur.strip())
        rules.append((parts, body))
    return rules


def test_every_hiding_css_rule_selector_contains_has():
    hiding = [(parts, body) for parts, body in _css_rules() if re.search(r"display:\s*none|visibility:\s*hidden", body)]
    assert len(hiding) >= 4, "правил, скрывающих секции, неожиданно мало: разбор CSS сломан?"
    bare = [s for parts, _ in hiding for s in parts if ":has(" not in s]
    assert bare == [], f"скрывающие селекторы без :has(): {bare}"


def test_css_keeps_ok_chip_rule_and_dark_theme():
    assert ".chip.ok{color:var(--done);border-color:var(--done)}" in pp.CSS
    # Task 7.1 ред. 4: только тёмная тема — решение владельца 2026-10-05
    assert "prefers-color-scheme" not in pp.CSS
    assert re.search(r":root\{color-scheme:dark;--bg:#14171a;", pp.CSS)
