# ruff: noqa: E501  -- литералы-фикстуры и ожидания в одну строку
"""Тесты автора на внутренние опасности приоритетов из «Снимка» ORDER.md (Task 3.7).

Приёмку пишет независимый тестер (test_acceptance_priority.py, через CLI). Здесь — места, видимые по устройству:
колонки ищутся по тексту шапки (жирная шапка, лишние колонки, нет `#` или `План`), таблица после §4 и вторая
таблица, `\\|` в ячейке, короткая строка, номер `**1**` / `1.5` / `-1`, имя с датой при двух кандидатах, один план
в двух строках, повтор неизвестного слага, устойчивость сортировки очереди, экранирование полос и ячеек.

Почти все тесты импортируют модуль напрямую: `parse_snapshot`, `snapshot_slugs`, `find_by_slug`, `apply_snapshot`,
`to_html` с готовыми `Plan`.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

_MOD_PATH = Path(__file__).resolve().parents[1] / "plans_progress.py"
_spec = importlib.util.spec_from_file_location("plans_progress_priority_under_test", _MOD_PATH)
pp = importlib.util.module_from_spec(_spec)
sys.modules["plans_progress_priority_under_test"] = pp
_spec.loader.exec_module(pp)

HEAD = "| # | Полоса | План | Сейчас | Следующий шаг | Чего ждёт |"
SEP = "|---|---|---|---|---|---|"


def write_order(tmp_path: Path, text: str, crlf: bool = False, bom: bool = False) -> Path:
    path = tmp_path / "ORDER.md"
    data = text.replace("\n", "\r\n") if crlf else text
    path.write_bytes((b"\xef\xbb\xbf" if bom else b"") + data.encode("utf-8"))
    return path


def snapshot_text(
    *rows: str, heading: str = "## Снимок 2026-10-03 — где мы сейчас", head: str = HEAD, sep: str = SEP
) -> str:
    return "\n".join(["# ORDER", "", heading, "", "Пояснение.", "", head, sep, *rows, "", "## 4. Контроль", ""])


def mem_plan(name: str, archived: bool = False, tier: str | None = "4.1") -> pp.Plan:
    p = pp.Plan(name=name, rel=f"plans/{name}/plan.md", archived=archived, tier=tier)
    p.tasks = [pp.Task("1.1", "x", "pending")]
    return p


def page(live=(), archive=(), date: str = "2026-10-03", rows=(), tmp: Path = Path(".")) -> str:
    return pp.to_html(list(live), list(archive), tmp, (), "6h", date, list(rows))


def section(raw: str, sid: str) -> str:
    m = re.search(rf'<section id="{sid}">.*?</section>', raw, re.S)
    assert m, f"нет секции #{sid}"
    return m.group(0)


def queue_order(raw: str) -> list[str]:
    return re.findall(r'data-plan="([^"]+)"', section(raw, "queue"))


# =========================================================================== parse_snapshot: форма


def test_parse_basic_row_fields_and_date(tmp_path):
    date, rows = pp.parse_snapshot(write_order(tmp_path, snapshot_text("| 1 | Ж | a-plan | сейчас | шаг | ничего |")))
    assert date == "2026-10-03"
    assert [(r.n, r.lane, r.plan_text, r.next_step, r.waits, r.slugs) for r in rows] == [
        (1, "Ж", "a-plan", "шаг", "ничего", ["a-plan"])
    ]


def test_parse_missing_file_section_or_table_gives_no_rows(tmp_path):
    assert pp.parse_snapshot(tmp_path / "nope.md") == ("", [])
    assert pp.parse_snapshot(write_order(tmp_path, "# ORDER\n\n## 4. Контроль\n")) == ("", [])
    assert pp.parse_snapshot(write_order(tmp_path, "## Снимок 2026-10-03 — x\n\nтекст без таблицы\n\n## 4.\n")) == (
        "2026-10-03",
        [],
    )


def test_parse_heading_without_date_gives_empty_date_but_rows(tmp_path):
    date, rows = pp.parse_snapshot(
        write_order(tmp_path, snapshot_text("| 1 | Ж | a-plan | с | ш | ж |", heading="## Снимок — где мы"))
    )
    assert date == "" and len(rows) == 1


def test_parse_only_level_two_heading_counts_and_first_one_wins(tmp_path):
    text = (
        "### Снимок 2020-01-01 — не тот\n\n"
        + HEAD
        + "\n"
        + SEP
        + "\n| 9 | Ж | z-plan | | | |\n\n"
        + snapshot_text("| 1 | Ж | a-plan | | | |")
    )
    date, rows = pp.parse_snapshot(write_order(tmp_path, text))
    assert date == "2026-10-03" and [r.n for r in rows] == [1]


def test_parse_table_ends_at_next_h2_and_second_table_is_ignored(tmp_path):
    text = snapshot_text("| 1 | Ж | a-plan | | | |") + "\n" + HEAD + "\n" + SEP + "\n| 2 | Ж | b-plan | | | |\n"
    assert [r.n for r in pp.parse_snapshot(write_order(tmp_path, text))[1]] == [1]
    inside = (
        "## Снимок 2026-10-03 — x\n\n"
        + HEAD
        + "\n"
        + SEP
        + "\n| 1 | Ж | a-plan | | | |\n\nабзац\n\n"
        + HEAD
        + "\n"
        + SEP
        + "\n| 2 | Ж | b-plan | | | |\n"
    )
    assert [r.n for r in pp.parse_snapshot(write_order(tmp_path, inside))[1]] == [1]


def test_parse_snapshot_placed_after_section_four_is_still_found(tmp_path):
    text = (
        "## 4. Контроль\n\n### 4.1 Активные\n\n| План |\n|---|\n| x |\n\n"
        + "## Снимок 2026-10-03 — позже\n\n"
        + HEAD
        + "\n"
        + SEP
        + "\n| 1 | Ж | a-plan | | | |\n"
    )
    assert [r.n for r in pp.parse_snapshot(write_order(tmp_path, text))[1]] == [1]


def test_parse_crlf_and_bom_files(tmp_path):
    text = snapshot_text("| 1 | Ж | a-plan | с | ш | ж |")
    for kw in ({"crlf": True}, {"bom": True}, {"crlf": True, "bom": True}):
        date, rows = pp.parse_snapshot(write_order(tmp_path, text, **kw))
        assert date == "2026-10-03" and [r.waits for r in rows] == ["ж"], kw


# =========================================================================== parse_snapshot: колонки по тексту


def test_columns_found_by_header_text_with_bold_and_extra_columns(tmp_path):
    head = "| Лишняя | **План** | `#` | Чего ждёт | Полоса | Следующий шаг |"
    row = "| ... | b-plan | 7 | долго | С | шаг Б |"
    _, rows = pp.parse_snapshot(write_order(tmp_path, snapshot_text(row, head=head, sep="|---|---|---|---|---|---|")))
    assert [(r.n, r.lane, r.slugs, r.next_step, r.waits) for r in rows] == [(7, "С", ["b-plan"], "шаг Б", "долго")]


def test_header_text_is_case_insensitive(tmp_path):
    head = "| № | ПЛАН | # |"
    _, rows = pp.parse_snapshot(
        write_order(tmp_path, snapshot_text("| x | a-plan | 3 |", head=head, sep="|---|---|---|"))
    )
    assert [(r.n, r.slugs, r.lane, r.next_step, r.waits) for r in rows] == [(3, ["a-plan"], "", "", "")]


@pytest.mark.parametrize("head", ["| Полоса | План | Сейчас |", "| # | Полоса | Сейчас |", "| Номер | Название |"])
def test_missing_number_or_plan_column_gives_no_rows_but_keeps_date(tmp_path, head):
    sep = "|" + "---|" * (head.count("|") - 1)
    date, rows = pp.parse_snapshot(write_order(tmp_path, snapshot_text("| 1 | 2 | 3 |", head=head, sep=sep)))
    assert (date, rows) == ("2026-10-03", [])


def test_duplicate_header_names_use_the_first_column(tmp_path):
    head = "| # | План | План |"
    _, rows = pp.parse_snapshot(
        write_order(tmp_path, snapshot_text("| 1 | a-plan | b-plan |", head=head, sep="|---|---|---|"))
    )
    assert rows[0].slugs == ["a-plan"]


# =========================================================================== parse_snapshot: ячейки и номера


@pytest.mark.parametrize(
    ("cell", "kept"),
    [
        ("1", True),
        ("**1**", True),
        (" 12 ", True),
        ("007", True),
        ("0", True),
        ("x", False),
        ("1.5", False),
        ("-1", False),
        ("", False),
        ("1a", False),
        ("٣", False),
    ],
)
def test_number_cell_must_be_a_plain_non_negative_integer(tmp_path, cell, kept):
    _, rows = pp.parse_snapshot(write_order(tmp_path, snapshot_text(f"| {cell} | Ж | a-plan | | | |")))
    assert bool(rows) is kept


def test_short_row_gives_empty_trailing_cells_not_a_crash(tmp_path):
    _, rows = pp.parse_snapshot(write_order(tmp_path, snapshot_text("| 1 | Ж | a-plan |")))
    assert [(r.n, r.next_step, r.waits) for r in rows] == [(1, "", "")]


def test_escaped_pipe_stays_inside_its_cell(tmp_path):
    _, rows = pp.parse_snapshot(write_order(tmp_path, snapshot_text(r"| 1 | Ж | a-plan | с | а \| б | ж |")))
    assert rows[0].next_step == "а | б" and rows[0].waits == "ж"


def test_table_order_is_kept_and_numbers_may_repeat(tmp_path):
    _, rows = pp.parse_snapshot(
        write_order(
            tmp_path, snapshot_text("| 2 | Ж | b-plan | | | |", "| 1 | Ж | a-plan | | | |", "| 1 | Ж | c-plan | | | |")
        )
    )
    assert [(r.n, r.slugs[0]) for r in rows] == [(2, "b-plan"), (1, "a-plan"), (1, "c-plan")]


# =========================================================================== имена в ячейке «План»


@pytest.mark.parametrize(
    ("cell", "slugs"),
    [
        ("a-plan", ["a-plan"]),
        ("a-plan, b-plan", ["a-plan", "b-plan"]),
        ("c-plan, фаза 5", ["c-plan"]),
        ("`a-plan`", ["a-plan"]),
        ("**a-plan**", ["a-plan"]),
        ("[алиас](../b-plan/plan.md)", ["b-plan"]),
        ("[x](../z-plan.md), a-plan", ["z-plan", "a-plan"]),
        ("[внешняя](https://example.org/p)", []),  # имя из URL не слаг плана
        ("a-plan, a-plan", ["a-plan"]),
        ("A-Plan", []),  # заглавные — не слаг
        ("-plan", []),
        ("transport-single-policy, фаза 5", ["transport-single-policy"]),
        ("", []),
        ("1.2-x", ["1.2-x"]),
    ],
)
def test_snapshot_slugs(cell, slugs):
    got = pp.snapshot_slugs(cell)
    if cell.startswith("[внешняя"):
        assert "https" not in "".join(got)
    else:
        assert got == slugs


def test_find_by_slug_exact_beats_dated_live_beats_archived_latest_date_among_dated():
    exact, dated = mem_plan("d-plan"), mem_plan("2026-10-01_d-plan")
    assert pp.find_by_slug([dated, exact], "d-plan") is exact
    live, arch = mem_plan("2026-10-01_e-plan"), mem_plan("2026-10-09_e-plan", archived=True)
    assert pp.find_by_slug([arch, live], "e-plan") is live
    old, new = mem_plan("2026-09-01_f-plan"), mem_plan("2026-10-01_f-plan")
    assert pp.find_by_slug([old, new], "f-plan") is new
    assert pp.find_by_slug([arch], "e-plan") is arch  # живых нет — архивный


def test_find_by_slug_does_not_match_a_suffix_or_a_prefix_of_another_name():
    plans = [
        mem_plan("my-d-plan"),
        mem_plan("2026-10-01_d-plan-v2"),
        mem_plan("d-plan-v2"),
        mem_plan("26-10-01_d-plan"),
    ]
    assert pp.find_by_slug(plans, "d-plan") is None


def test_find_by_slug_escapes_regex_chars_in_the_slug():
    assert pp.find_by_slug([mem_plan("2026-10-01_aXb")], "a.b") is None
    assert pp.find_by_slug([mem_plan("2026-10-01_a.b")], "a.b") is not None


# =========================================================================== apply_snapshot


def test_apply_snapshot_smallest_number_wins_and_row_is_that_row():
    a = mem_plan("a-plan")
    rows = [
        pp.SnapRow(5, "Ж", "a-plan", "шаг 5", "пять", ["a-plan"]),
        pp.SnapRow(3, "Ж", "a-plan", "шаг 3", "три", ["a-plan"]),
    ]
    assert pp.apply_snapshot([a], rows) == []
    assert (a.priority, a.priority_row.next_step) == (3, "шаг 3")


def test_apply_snapshot_one_row_marks_every_named_plan_and_zero_is_a_priority():
    a, b = mem_plan("a-plan"), mem_plan("b-plan")
    pp.apply_snapshot([a, b], [pp.SnapRow(0, "Ж", "a-plan, b-plan", "", "", ["a-plan", "b-plan"])])
    assert (a.priority, b.priority) == (0, 0)


def test_apply_snapshot_unknown_slugs_once_each_in_order_of_appearance():
    a = mem_plan("a-plan")
    rows = [
        pp.SnapRow(1, "", "", "", "", ["zz", "a-plan"]),
        pp.SnapRow(2, "", "", "", "", ["yy", "zz"]),
        pp.SnapRow(3, "", "", "", "", ["zz"]),
    ]
    assert pp.apply_snapshot([a], rows) == ["zz", "yy"]


def test_snapshot_findings_are_info_not_blocking_and_name_the_slug_once():
    f = pp.snapshot_findings(["zz-unknown"])
    assert len(f) == 1 and f[0].blocking is False and f[0].code == "SNAPSHOT_UNKNOWN"
    line = f[0].line()
    assert line.startswith("SNAPSHOT_UNKNOWN ORDER.md info") and line.count("zz-unknown") == 1
    assert pp.snapshot_findings([]) == []


# =========================================================================== страница


def test_queue_sort_is_stable_for_equal_numbers_and_puts_unprioritised_last_in_old_order():
    names = ["a", "b", "c", "d", "e"]
    plans = [mem_plan(n) for n in names]
    plans[3].priority = 1  # d
    plans[1].priority = 1  # b — тот же номер: прежний порядок b раньше d
    plans[4].priority = 0  # e
    assert queue_order(page(plans)) == ["e", "b", "d", "a", "c"]


def test_only_the_queue_is_reordered_waiting_unlisted_and_archive_keep_order():
    waiting = [mem_plan("w-a", tier="4.2"), mem_plan("w-b", tier="4.2")]
    unlisted = [mem_plan("u-a", tier=None), mem_plan("u-b", tier=None)]
    arch = [mem_plan("z-a", archived=True), mem_plan("z-b", archived=True)]
    for p in (waiting[1], unlisted[1], arch[1]):
        p.priority = 1
    raw = page(waiting + unlisted, arch)
    assert re.findall(
        r'data-plan="([^"]+)"',
        re.search(r'<details id="waiting">.*?</details>\s*(?=<section|<details id="archive")', raw, re.S).group(0),
    )[:2] == ["w-a", "w-b"]
    assert re.findall(r'data-plan="([^"]+)"', section(raw, "unlisted")) == ["u-a", "u-b"]
    assert raw.index('data-plan="z-a"') < raw.index('data-plan="z-b"')
    assert raw.count('data-chip="priority"') == 3


def test_lanes_block_keeps_its_old_lane_order_when_queue_is_reordered():
    a, b = mem_plan("a"), mem_plan("b")
    a.lane, b.lane = "Ж", "С"
    b.priority = 1
    raw = page([a, b])
    lanes = re.search(r'<section class="lanes">.*?</section>', raw, re.S).group(0)
    assert lanes.index("Полоса Ж") < lanes.index("Полоса С")


def test_chip_is_first_after_name_before_badges_and_info_is_first_in_body():
    p = mem_plan("a")
    p.lane = "Ж"
    p.priority, p.priority_row = 4, pp.SnapRow(4, "Ж", "a", "шаг", "ждёт-чего", ["a"])
    raw = page([p])
    summary = re.search(
        r"<summary>(.*?)</summary>", re.search(r'<section id="queue">.*?</section>', raw, re.S).group(0), re.S
    ).group(1)
    assert re.findall(r'<span class="(name|chip|badge)"', summary)[:3] == ["name", "chip", "badge"]
    body = re.search(r'<div class="body">\s*(.*?)</div>', raw, re.S).group(1)
    assert body.startswith('<div class="info"><b>Приоритет #4:</b> дальше — шаг; ждёт — ждёт-чего')


def test_priority_chip_present_for_archived_and_closed_plans_too():
    arch = mem_plan("z", archived=True)
    arch.priority = 2
    assert 'data-chip="priority" data-priority="2">#2<' in page([], [arch])


def test_ready_summary_follows_the_resorted_queue():
    a, b = mem_plan("a-plan"), mem_plan("b-plan")
    for p in (a, b):
        p.has_after_field = True
        p.ready = True
    b.priority = 1
    m = re.search(r'id="ready">(.*?)</div>', page([a, b]))
    assert m.group(1).startswith("можно начинать: b-plan, a-plan")


def test_without_rows_page_has_stub_and_old_order_and_no_priority_markup():
    raw = page([mem_plan("a"), mem_plan("b")], date="", rows=())
    sec = section(raw, "priority")
    assert re.findall(r"<p[^>]*>(.*?)</p>", sec) == ["в ORDER.md нет таблицы «Снимок»"]
    assert "<ol>" not in sec and "<li" not in sec and "<h2>Приоритеты</h2>" in sec
    assert queue_order(raw) == ["a", "b"] and 'data-chip="priority"' not in raw


def test_priority_section_stands_between_ready_and_lanes_even_with_rows():
    raw = page([mem_plan("a")], rows=[pp.SnapRow(1, "Ж", "a", "ш", "ж", ["a"])])
    assert raw.index('id="ready"') < raw.index('id="priority"') < raw.index('class="lanes"') < raw.index('id="queue"')


def test_every_cell_is_escaped_in_li_info_and_heading():
    evil = "<script>alert(1)</script>&\"'"
    row = pp.SnapRow(1, evil, evil, evil, evil, ["a"])
    p = mem_plan("a")
    p.priority, p.priority_row = 1, row
    raw = page([p], rows=[row], date="2026-10-03")
    assert "<script" not in raw.lower()
    assert raw.count("&lt;script&gt;") >= 5  # li: полоса, план, шаг, ждёт (4) + info: шаг, ждёт (2)
    li = re.search(r'<li data-priority="1">(.*?)</li>', raw).group(1)
    assert "&quot;" in li or "&#x27;" in li


def test_li_text_for_empty_cells_keeps_the_literal_shape():
    raw = page([], rows=[pp.SnapRow(8, "", "", "", "", [])])
    assert '<li data-priority="8">#8 · полоса  ·  — дальше:  · ждёт: </li>' in raw


def test_to_html_old_call_without_snapshot_arguments_still_works(tmp_path):
    raw = pp.to_html([mem_plan("a")], [], tmp_path)
    assert "в ORDER.md нет таблицы «Снимок»" in raw


# =========================================================================== CLI: проводка


def test_check_prints_snapshot_unknown_even_outside_git_and_outside_main(tmp_path, capsys):
    root = tmp_path / "r"
    (root / "plans" / "queue").mkdir(parents=True)
    (root / "plans" / "a-plan").mkdir()
    (root / "plans" / "a-plan" / "plan.md").write_text(
        "# a\n\n## Порядок выполнения\n\n- Task 1.1: x [PENDING]\n", encoding="utf-8"
    )
    (root / "plans" / "queue" / "ORDER.md").write_text(
        snapshot_text("| 1 | Ж | a-plan, zz-unknown, zz-unknown | | | |"), encoding="utf-8"
    )
    code = pp.main(["--root", str(root), "--check"])
    out = capsys.readouterr().out
    lines = [ln for ln in out.splitlines() if ln.startswith("SNAPSHOT_UNKNOWN")]
    assert code == 0 and len(lines) == 1 and "zz-unknown" in lines[0] and "a-plan" not in lines[0]
