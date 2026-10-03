# ruff: noqa: E501  -- литералы-фикстуры и ожидания в одну строку
"""Тесты автора на внутренние опасности чипа «в работе» и секции `#who` (Task 5.3).

Приёмку пишет независимый тестер (test_acceptance_page_who.py, через настоящий git и CLI). Здесь — места,
видимые по устройству: экранирование КАЖДОГО подставляемого поля (путь worktree, имя плана, окно), порядок
чипов и строк при плане с несколькими worktree, закрытый план с работой, пустая секция, detached, формат
времени на коротких и длинных строках, умолчания `to_html`.

Тесты зовут `to_html` / `_plan_html` напрямую с готовыми `Plan.active`: git не нужен, вход задаётся литералами.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

import pytest

_MOD_PATH = Path(__file__).resolve().parents[1] / "plans_progress.py"
_spec = importlib.util.spec_from_file_location("plans_progress_who_under_test", _MOD_PATH)
pp = importlib.util.module_from_spec(_spec)
sys.modules["plans_progress_who_under_test"] = pp
_spec.loader.exec_module(pp)


def entry(
    worktree: str,
    branch: str = "feat/x",
    via: str = "header",
    last: str = "2026-10-03T11:00:05",
    s: int = 1,
    a: int = 1,
) -> dict:
    return {"branch": branch, "worktree": worktree, "via": via, "sessions": s, "agents": a, "last_signal": last}


def plan(
    name: str, *active: dict, archived: bool = False, tier: str | None = None, header_status: str | None = None
) -> pp.Plan:
    p = pp.Plan(name=name, rel=f"plans/{name}/plan.md", archived=archived, tier=tier)
    p.tasks = [pp.Task("1.1", "x", "pending")]
    p.header_status = header_status
    p.active = list(active)
    return p


def page(live=(), archive=(), orphans=(), window: str | None = None, root: Path | None = None) -> str:
    kw = {} if window is None else {"window_text": window}
    return pp.to_html(list(live), list(archive), root or Path("."), list(orphans), **kw)


class Chips(HTMLParser):
    """Чипы по планам в порядке документа: (data-chip, текст)."""

    def __init__(self, raw: str) -> None:
        super().__init__(convert_charrefs=True)
        self.by_plan: dict[str, list[tuple[str, str, dict]]] = {}
        self._plan = None
        self._cur = None
        self.feed(raw)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "details" and "plan" in (a.get("class") or "").split():
            self._plan = a["data-plan"]
            self.by_plan[self._plan] = []
        if tag == "span" and "chip" in (a.get("class") or "").split() and self._plan is not None:
            self._cur = [a.get("data-chip", ""), "", a]
            self.by_plan[self._plan].append(self._cur)

    def handle_data(self, data):
        if self._cur is not None:
            self._cur[1] += data

    def handle_endtag(self, tag):
        if tag == "span":
            self._cur = None
        if tag == "details":
            self._plan = None


def who_section(raw: str) -> str:
    m = re.search(r'<section id="who">.*?</section>', raw, re.S)
    assert m, "нет секции #who"
    return m.group(0)


# =========================================================================== экранирование


EVIL = "<script>alert(1)</script>&\"'"


def test_every_substituted_field_is_escaped_in_chip_and_who(tmp_path):
    e = entry(f"C:/w/{EVIL}", branch=f"feat/{EVIL}")
    o = entry(f"C:/o/{EVIL}", branch=f"orph/{EVIL}")
    raw = page([plan(f"P{EVIL}", e)], orphans=[o], window=EVIL, root=tmp_path)
    assert "<script" not in raw.lower(), raw[raw.index("<script") - 80 : raw.index("<script") + 80]
    who = who_section(page([plan(f"P{EVIL}", e)], orphans=[o], window=EVIL, root=tmp_path))
    assert "&lt;script&gt;" in who
    # пустая секция: окно тоже экранируется
    assert "<script" not in who_section(page(window=EVIL, root=tmp_path)).lower()
    assert f"окно {pp._e(EVIL)})" in who_section(page(window=EVIL, root=tmp_path))


def test_title_and_data_attributes_roundtrip_through_a_parser(tmp_path):
    wt = 'C:/w/a"b&c<d>'
    c = Chips(page([plan("P", entry(wt, branch="feat/a\"b'c"))], root=tmp_path)).by_plan["P"]
    ((_, _, attrs),) = c
    assert attrs["title"] == wt and attrs["data-active"] == "feat/a\"b'c"


def test_quote_in_branch_cannot_close_the_attribute(tmp_path):
    raw = page([plan("P", entry("C:/w", branch='x" onmouseover="alert(1)'))], root=tmp_path)
    assert 'data-active="x&quot; onmouseover=&quot;alert(1)"' in raw
    assert 'onmouseover="alert' not in raw


# =========================================================================== чип: порядок, закрытые, detached, время


def test_active_chips_keep_the_order_of_plan_active_and_come_last(tmp_path):
    p = plan("P", entry("C:/a", branch="feat/a"), entry("C:/b", branch="feat/b"))
    p.after = ["Z"]
    p.has_after_field = True
    z = plan("Z")
    chips = Chips(page([p, z], root=tmp_path)).by_plan["P"]
    kinds = [k for k, _, _ in chips]
    assert kinds[-2:] == ["active", "active"] and "after" in kinds
    assert [a["data-active"] for k, _, a in chips if k == "active"] == ["feat/a", "feat/b"]


def test_closed_plan_and_archived_plan_keep_their_active_chips_after_the_closed_chip(tmp_path):
    closed = plan("CL", entry("C:/c", branch="feat/c"), header_status="done")
    old = plan("OLD", entry("C:/o", branch="feat/o"), archived=True)
    by = Chips(page([closed], [old], root=tmp_path)).by_plan
    assert [k for k, _, _ in by["CL"]] == ["closed", "active"], by["CL"]
    assert [k for k, _, _ in by["OLD"]] == ["active"]


def test_plan_without_active_entries_has_no_active_chip(tmp_path):
    assert [k for k, _, _ in Chips(page([plan("P"), plan("Q", entry("C:/q"))], root=tmp_path)).by_plan["P"]] == []


def test_detached_chip_and_li_say_detached_and_keep_empty_attributes(tmp_path):
    raw = page([plan("P", entry("C:/d", branch=""))], orphans=[entry("C:/o", branch="")], root=tmp_path)
    assert 'data-active=""' in raw
    assert raw.count('data-branch=""') == 2
    ((_, text, _),) = Chips(raw).by_plan["P"]
    assert " ".join(text.split()) == "в работе: (detached) · сессий 1 · агентов 1 · сигнал 2026-10-03 11:00"
    assert "(detached) → P · " in raw and "(detached) — план не найден · " in raw


@pytest.mark.parametrize(
    ("last", "shown"),
    [
        ("2026-10-03T20:31:37", "2026-10-03 20:31"),
        ("2026-10-03T20:31:59.999999", "2026-10-03 20:31"),  # без округления вверх
        ("2026-10-03T23:59:59", "2026-10-03 23:59"),
        ("2026-10-03T20:31", "2026-10-03 20:31"),
        ("2026-10-03", "2026-10-03"),  # короче 16 символов — как есть, не падение
    ],
)
def test_signal_time_is_the_first_16_characters_with_t_replaced(last, shown, tmp_path):
    ((_, text, _),) = Chips(page([plan("P", entry("C:/w", last=last))], root=tmp_path)).by_plan["P"]
    assert " ".join(text.split()).endswith(f"сигнал {shown}")


# =========================================================================== #who: порядок, пустая секция, счёт


def test_who_lists_actives_then_orphans_each_sorted_by_worktree_string(tmp_path):
    live = [plan("X", entry("C:/m"), entry("C:/b")), plan("Y", entry("C:/k"))]
    raw = who_section(page(live, orphans=[entry("C:/z"), entry("C:/a")], root=tmp_path))
    order = re.findall(r'<li data-worktree="([^"]+)"', raw)
    assert order == ["C:/b", "C:/k", "C:/m", "C:/a", "C:/z"]
    assert raw.count("data-orphan=") == 2 and "Кто где · 5" in raw


def test_who_takes_actives_from_live_and_archive_plans_alike(tmp_path):
    raw = who_section(page([plan("L", entry("C:/l"))], [plan("A", entry("C:/a"), archived=True)], root=tmp_path))
    assert 'data-who-plan="L"' in raw and 'data-who-plan="A"' in raw and "Кто где · 2" in raw


def test_empty_who_has_no_ul_one_empty_line_and_exactly_two_notes_last(tmp_path):
    raw = who_section(page(root=tmp_path))
    assert "<ul>" not in raw and "<li" not in raw and "Кто где · 0" in raw
    paragraphs = re.findall(r"<p[^>]*>(.*?)</p>", raw)
    assert paragraphs == ["свежих сигналов нет (окно 6h)", *pp.WHO_NOTES]
    assert raw.count('class="note"') == 2


def test_who_with_content_has_no_empty_line_but_still_two_notes(tmp_path):
    raw = who_section(page([plan("P", entry("C:/w"))], root=tmp_path))
    assert "свежих сигналов нет" not in raw and raw.count('class="note"') == 2


def test_who_section_is_between_lanes_and_queue_even_when_empty(tmp_path):
    raw = page([plan("P")], root=tmp_path)
    assert raw.index('class="lanes"') < raw.index('id="who"') < raw.index('id="queue"')


def test_to_html_old_call_with_three_arguments_still_works(tmp_path):
    raw = pp.to_html([plan("P")], [], tmp_path)
    assert "Кто где · 0" in raw and "свежих сигналов нет (окно 6h)" in raw


def test_page_has_no_script_no_external_url_no_new_css_color(tmp_path):
    raw = page([plan("P", entry("C:/w"))], orphans=[entry("C:/o")], root=tmp_path)
    low = raw.lower()
    assert "<script" not in low and "http://" not in low and "https://" not in low
    css = re.search(r"<style>(.*?)</style>", raw, re.S).group(1)
    assert css == pp.CSS, "Task 5.3 не добавляет цветов и правил CSS"


def test_who_numbers_are_printed_as_numbers_not_repr(tmp_path):
    raw = who_section(page([plan("P", entry("C:/w", s=12, a=0))], root=tmp_path))
    assert "сессий 12 · агентов 0 · сигнал 2026-10-03 11:00" in raw
