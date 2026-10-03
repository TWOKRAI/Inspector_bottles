"""Task 3.2, автор: опасности чипов зависимостей и сводки `#ready` на странице.

Слепой тестер проверяет контракт (test_acceptance_page_deps.py). Здесь то, что виден только автору:
экранирование в атрибутах и тексте, порядок чипов внутри `<summary>`, §4.2 против §4.1, порядок очереди
в `#ready`, префиксные имена. Страница читается регулярками по сырому тексту: нужен именно исходный текст
атрибутов, а парсер его раскодирует. Один тест — одно свойство, чтобы инъекцию можно было ломать по одной.
"""

from __future__ import annotations

import html
import re

import pytest

READY_RE = re.compile(r'<div class="meta" id="ready">(.*?)</div>', re.S)
UNDEFINED = "можно начинать: не определено (поле «После:» не заполнено ни у одного плана)"


def _plan(after: str | None = None, tasks: tuple[str, ...] = ("PENDING",), head: str | None = None) -> str:
    lines = ["# P", ""]
    if head:
        lines.append(head)
    if after is not None:
        lines.append(f"- **После:** {after}")
    lines += ["", "## Порядок выполнения", ""]
    lines += [f"- Task 1.{i}: x [{s}]" for i, s in enumerate(tasks, 1)]
    lines.append("")
    return "\n".join(lines)


# Незакрытый план вне ORDER.md с полем `После:`: включает чипы «можно начинать» на странице.
FIELD = {"p-field": _plan(after="ghost")}


@pytest.fixture
def page_of(make_root, progress, order_md, tmp_path):
    """page_of({имя: текст плана}, tier41=[...], tier42=[...]) -> сырой текст страницы."""

    def _call(plans: dict[str, str], tier41=(), tier42=(), tier43=()) -> str:
        files = {f"plans/{n}/plan.md": text for n, text in plans.items()}
        files["plans/queue/ORDER.md"] = order_md(tier41=tier41, tier42=tier42, tier43=tier43)
        root = make_root(files)
        out = tmp_path / f"{root.name}.html"
        cp = progress(root, "--html", str(out))
        assert cp.returncode == 0, f"--html exit {cp.returncode}\nstderr={cp.stderr[:400]!r}"
        return out.read_text(encoding="utf-8")

    return _call


def _summary(raw: str, name: str) -> str:
    """Сырой текст от `<details ... data-plan="имя">` до `</summary>`."""
    head = r'<details class="plan" data-plan="' + re.escape(html.escape(name))
    m = re.search(head + r'"[^>]*>.*?</summary>', raw, re.S)
    assert m, f"план {name!r} не найден на странице"
    return m.group(0)


def _ready_text(raw: str) -> str:
    m = READY_RE.search(raw)
    assert m, "на странице нет #ready"
    return html.unescape(m.group(1))


def _chip_kinds(summary: str) -> list[str]:
    return re.findall(r'data-chip="([a-z-]+)"', summary)


# ----------------------------------------------------------------------------- экранирование


def test_unknown_name_with_markup_is_escaped_in_chip_text(page_of):
    raw = page_of({"p-a": _plan(after="""g"<i>&'x""")}, tier41=["p-a"])
    assert "после: g&quot;&lt;i&gt;&amp;&#x27;x</span>" in _summary(raw, "p-a")


def test_unknown_name_with_markup_creates_no_tag(page_of):
    raw = page_of({"p-a": _plan(after="g<i>x")}, tier41=["p-a"])
    assert "<i>" not in raw


def test_waiting_condition_with_quotes_and_markup_is_escaped_in_text(page_of):
    raw = page_of({"p-a": _plan(after="""⛔ ждать "X" <b>&'""")}, tier41=["p-a"])
    assert "ждёт: ждать &quot;X&quot; &lt;b&gt;&amp;&#x27;</span>" in _summary(raw, "p-a")


def test_reason_with_quotes_cannot_break_out_of_title_attribute(page_of):
    raw = page_of({"p-a": _plan(after="""⛔ hw — ждёт "API" onmouseover="x" <b>""")}, tier41=["p-a"])
    chip = re.search(r'<span class="chip" data-chip="waiting"[^>]*>', _summary(raw, "p-a"))
    assert chip
    assert chip.group(0) == (
        '<span class="chip" data-chip="waiting" title="ждёт &quot;API&quot; onmouseover=&quot;x&quot; &lt;b&gt;">'
    )


def test_title_is_absent_not_empty_when_there_is_no_reason(page_of):
    raw = page_of({"p-a": _plan(after="⛔ hw, ghost")}, tier41=["p-a"])
    chips = re.findall(r'<span class="chip[^"]*" data-chip="(?:after|waiting)"[^>]*>', _summary(raw, "p-a"))
    assert len(chips) == 2
    assert all("title" not in c for c in chips)


def test_plan_name_with_amp_and_apostrophe_is_escaped_in_attribute_and_summary(page_of):
    name = "p&q'r"
    raw = page_of({name: _plan(), **FIELD}, tier41=[name])
    assert 'data-plan="p&amp;q&#x27;r"' in raw
    assert _ready_text(raw) == "можно начинать: p&q'r"
    assert "можно начинать: p&amp;q&#x27;r</div>" in raw


# ----------------------------------------------------------------------------- порядок чипов


def test_dependency_chips_come_after_the_unmarked_chip(page_of):
    unmarked = "# P\n\n- **После:** ghost\n\n### Task 1.1 — a [DONE]\n\n### Task 1.2 — b\nтекст без признаков статуса\n"
    raw = page_of({"p-a": unmarked}, tier41=["p-a"])
    kinds = _chip_kinds(_summary(raw, "p-a"))
    assert kinds == ["unmarked", "after"]


def test_ready_chip_comes_before_after_chip(page_of):
    raw = page_of(
        {"p-done": _plan(tasks=("DONE",)), "p-a": _plan(after="p-done")},
        tier41=["p-a"],
        tier43=["p-done"],
    )
    assert _chip_kinds(_summary(raw, "p-a")) == ["ready", "after"]


def test_after_chips_come_before_waiting_chips(page_of):
    raw = page_of({"p-a": _plan(after="⛔ hw, ghost")}, tier41=["p-a"])
    assert _chip_kinds(_summary(raw, "p-a")) == ["after", "waiting"]


def test_header_done_plan_gets_closed_chip_and_no_dependency_chips(page_of):
    raw = page_of({"p-a": _plan(after="ghost, ⛔ hw", head="- **Статус:** DONE")}, tier41=["p-a"])
    assert _chip_kinds(_summary(raw, "p-a")) == ["header-conflict"]


# ----------------------------------------------------------------------------- §4.1 против §4.2


def test_same_shape_plan_in_queue_is_ready_and_in_waiting_is_not(page_of):
    raw = page_of({"p-q": _plan(), "p-w": _plan(), **FIELD}, tier41=["p-q"], tier42=["p-w"])
    assert 'data-plan="p-q" data-tier="4.1" data-lane="С" data-ready="true"' in raw
    assert "data-ready" not in _summary(raw, "p-w")
    assert 'data-chip="ready"' not in _summary(raw, "p-w")


def test_waiting_plan_keeps_its_after_chip_without_ready_attribute(page_of):
    raw = page_of({"p-q": _plan(), "p-w": _plan(after="p-q")}, tier41=["p-q"], tier42=["p-w"])
    summary = _summary(raw, "p-w")
    assert _chip_kinds(summary) == ["after"]
    assert "data-ready" not in summary


# ----------------------------------------------------------------------------- сводка #ready


def test_ready_summary_follows_queue_order_not_alphabet(page_of):
    raw = page_of({"aa-early": _plan(), "zz-late": _plan(), **FIELD}, tier41=["zz-late", "aa-early"])
    assert _ready_text(raw) == "можно начинать: zz-late, aa-early"


def test_ready_summary_is_none_when_no_plan_is_startable(page_of):
    raw = page_of({"p-a": _plan(after="ghost")}, tier41=["p-a"])
    assert _ready_text(raw) == "можно начинать: нет"


def test_ready_summary_names_the_prefix_plan_only_when_the_longer_one_waits_for_it(page_of):
    raw = page_of({"p": _plan(), "p-long": _plan(after="p")}, tier41=["p", "p-long"])
    assert _ready_text(raw) == "можно начинать: p"


def test_prefix_named_plan_does_not_inherit_data_ready_from_its_prefix(page_of):
    raw = page_of({"p": _plan(), "p-long": _plan(after="p")}, tier41=["p", "p-long"])
    assert 'data-ready="true"' in _summary(raw, "p")
    assert "data-ready" not in _summary(raw, "p-long")


def test_ready_summary_skips_header_done_plan_with_open_task(page_of):
    raw = page_of(
        {"p-hdr": _plan(head="- **Статус:** DONE"), "p-ok": _plan(), **FIELD},
        tier41=["p-hdr", "p-ok"],
    )
    assert _ready_text(raw) == "можно начинать: p-ok"


def test_ready_summary_sits_between_meta_rows_and_lanes(page_of):
    raw = page_of({"p-a": _plan()}, tier41=["p-a"])
    assert raw.index('class="meta">в очереди') < raw.index('id="ready"') < raw.index('<section class="lanes">')


# ----------------------------------------------------------------------------- «не определено» (Q9)


def test_undefined_summary_has_the_exact_text_when_no_plan_has_the_field(page_of):
    raw = page_of({"p-a": _plan()}, tier41=["p-a"])
    assert _ready_text(raw) == UNDEFINED


def test_undefined_page_has_no_data_ready_and_no_ready_chip(page_of):
    raw = page_of({"p-a": _plan(), "p-b": _plan()}, tier41=["p-a", "p-b"])
    assert "data-ready" not in raw
    assert 'data-chip="ready"' not in raw


def test_field_with_only_a_waiting_condition_counts_as_in_use(page_of):
    raw = page_of({"p-a": _plan(after="⛔ hw"), "p-b": _plan()}, tier41=["p-a", "p-b"])
    assert _ready_text(raw) == "можно начинать: p-b"


def test_field_only_in_a_4_3_plan_does_not_count(page_of):
    raw = page_of({"p-c": _plan(after="ghost"), "p-b": _plan()}, tier41=["p-b"], tier43=["p-c"])
    assert _ready_text(raw) == UNDEFINED


def test_field_only_in_a_header_done_plan_does_not_count(page_of):
    raw = page_of(
        {"p-h": _plan(after="ghost", head="- **Статус:** DONE"), "p-b": _plan()},
        tier41=["p-h", "p-b"],
    )
    assert _ready_text(raw) == UNDEFINED


def test_field_only_in_a_plan_with_all_tasks_done_does_not_count(page_of):
    raw = page_of({"p-d": _plan(after="ghost", tasks=("DONE",)), "p-b": _plan()}, tier41=["p-d", "p-b"])
    assert _ready_text(raw) == UNDEFINED


def test_field_in_an_open_plan_outside_order_flips_the_page_to_defined(page_of):
    raw = page_of({"p-b": _plan(), **FIELD}, tier41=["p-b"])
    assert _ready_text(raw) == "можно начинать: p-b"


def test_real_tree_prints_undefined_and_no_data_ready_while_nobody_writes_the_field(progress, tmp_path):
    """Живое дерево на 2026-10-03: поле `После:` не пишет ни один план. Станет красным, когда его запишут (Task 3.3)."""
    from pathlib import Path

    repo = Path(__file__).resolve().parents[3]
    out = tmp_path / "real.html"
    cp = progress(repo, "--html", str(out))
    assert cp.returncode == 0, cp.stderr[:400]
    raw = out.read_text(encoding="utf-8")
    assert _ready_text(raw) == UNDEFINED
    assert "data-ready" not in raw
