# ruff: noqa: E501  -- литералы-фикстуры и ожидания в одну строку, форматтер их не переносит
"""Приёмка Task 3.7 — слепые тесты приоритетов из таблицы «Снимок» ORDER.md на странице.

Источник: plans/2026-10-02_plans-progress-dashboard/tasks/3.7.md (DESIGN, ACCEPTANCE P1-P6).
Реализацию тестер не видел; из plans_progress.py читались только имена функций и вид прежней страницы.

Только CLI в subprocess (timeout на вызов): `plans_progress.py --root R --html F | --check | --json | --sync-order`.
Фикстура — обычный каталог без git: `plans/<имя>/plan.md` и `plans/queue/ORDER.md` с таблицами §4.1-§4.3
и разделом `## Снимок 2026-10-03 — где мы сейчас` (колонки `# | Полоса | План | Сейчас | Следующий шаг | Чего ждёт`).
Страницу разбирает свой HTMLParser. Ожидания — литералы.

Договорённости чтения (в тексте задачи неоднозначно; выбрано строгое чтение):
- Пробелы в тексте элементов схлопываются (`" ".join(text.split())`); слова, `·`, `—`, `#` — точно.
- Каждый негативный тест («нет чипа», «порядок прежний», «находок нет») несёт положительный контроль
  в том же прогоне: соседний план с чипом / тот же ORDER.md со «Снимком» даёт перестановку.
- «Стартуют» = §4.1, своё `После: —`, открытая задача (правило 3.2): `#ready` = `можно начинать: <имена>`.
- Раздел «Снимок» стоит в начале ORDER.md (как в реальном файле), до §4.
- Чип приоритета — ПЕРВЫЙ чип после `span.name` в summary (DESIGN: «сразу после name»).
"""

from __future__ import annotations

import html
import itertools
import json
import os
import re
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PROGRESS = REPO_ROOT / "scripts" / "plans_progress" / "plans_progress.py"
CALL_TIMEOUT = 60

NO_TABLE = "в ORDER.md нет таблицы «Снимок»"
DEFAULT_COLS = ["#", "Полоса", "План", "Сейчас", "Следующий шаг", "Чего ждёт"]
OLD_JSON_KEYS = [
    "plan", "path", "archived", "lane", "tier", "done", "total", "dropped", "unknown", "unmarked",
    "header_status", "tasks", "after", "after_reason", "waiting_on", "ready", "dep_unknown", "dep_cycle", "active", "branches",
]  # fmt: skip

_counter = itertools.count(1)


# =========================================================================== фикстура


def plan_md(after: str | None = "—", tasks: tuple[str, ...] = ("PENDING",)) -> str:
    lines = ["# План", ""]
    if after is not None:
        lines += [f"- **После:** {after}", ""]
    lines += ["## Порядок выполнения", ""]
    lines += [f"- Task 1.{i}: x [{s}]" for i, s in enumerate(tasks, 1)]
    return "\n".join(lines) + "\n"


def snap_row(n, lane="Ж", plan="a-plan", now="сейчас", nxt="шаг", wait="ничего") -> dict[str, str]:
    return {"#": str(n), "Полоса": lane, "План": plan, "Сейчас": now, "Следующий шаг": nxt, "Чего ждёт": wait}


def order_md(
    q41: list[str],
    q42: tuple[str, ...] = (),
    q43: tuple[str, ...] = (),
    snapshot: list[dict[str, str]] | None = None,
    cols: list[str] | None = None,
    heading: str = "## Снимок 2026-10-03 — где мы сейчас",
    markers: bool = False,
) -> str:
    out = ["# Порядок работ и контроль планов", ""]
    if snapshot is not None:
        cols = cols or DEFAULT_COLS
        out += [heading, "", "Строки стоят в порядке приоритета.", ""]
        out += ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
        out += ["| " + " | ".join(r[c] for c in cols) + " |" for r in snapshot]
        out += [""]
    out += ["## 4. Контроль планов", "", "### 4.1 Активные — в работе или следующие", ""]
    out += ["| План | Полоса | Статус | Следующий шаг |", "|---|---|---|---|"]
    out += [f"| [{n}](../{n}/plan.md) | Ж | статус | шаг |" for n in q41]
    out += ["", "### 4.2 Ждут триггера — не трогать до условия", "", "| План | Остаток | Триггер |", "|---|---|---|"]
    out += [f"| [{n}](../{n}/plan.md) | остаток | триггер |" for n in q42]
    out += ["", "### 4.3 Закрыты или поглощены — кандидаты в `_archive/`", "", "| План | Факт |", "|---|---|"]
    out += [f"| [{n}](../{n}/plan.md) | DONE |" for n in q43]
    out += [""]
    if markers:
        out += ["<!-- progress:begin -->", "<!-- progress:end -->", ""]
    return "\n".join(out)


def make_root(tmp_path: Path, name: str, plans: dict[str, str], order: str) -> Path:
    root = tmp_path / name
    for rel, text in {**plans, "plans/queue/ORDER.md": order}.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(text.encode("utf-8"))
    return root


def plans_of(*names: str, after: str | None = "—") -> dict[str, str]:
    return {f"plans/{n}/plan.md": plan_md(after) for n in names}


# =========================================================================== запуск CLI


def _run(root: Path, *flags: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROGRESS), "--root", str(root), *flags],
        capture_output=True,
        timeout=CALL_TIMEOUT,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
    )


def _out(cp: subprocess.CompletedProcess) -> str:
    return f"exit={cp.returncode}\nstdout={cp.stdout[:400]!r}\nstderr={cp.stderr[:400]!r}"


def check_lines(root: Path) -> tuple[int, str]:
    cp = _run(root, "--check")
    return cp.returncode, cp.stdout + "\n" + cp.stderr


# =========================================================================== разбор страницы


def _norm(text: str) -> str:
    return " ".join(text.split())


class Page(HTMLParser):
    SECTION_IDS = {"queue", "waiting", "unlisted", "archive"}
    VOID = {"br", "meta", "link", "img", "input", "hr"}

    def __init__(self, raw: str) -> None:
        super().__init__(convert_charrefs=True)
        self.raw = raw
        self.stack: list[tuple[str, dict[str, str | None]]] = []
        self.pos = 0
        self.plans: dict[str, dict] = {}
        self.order: dict[str, list[str]] = {k: [] for k in self.SECTION_IDS}
        self.ready_text = ""
        self.ready_pos: int | None = None
        self.lanes_pos: int | None = None
        self.queue_pos: int | None = None
        self.priority: dict | None = None
        self.priority_pos: int | None = None
        self._caps: list[tuple[dict, str, int, str]] = []
        self._new: list[tuple[dict, str]] = []
        self.feed(raw)
        self.close()
        m = re.search(r'<div class="meta" id="ready">(.*?)</div>', raw, re.S)
        self.ready_text = html.unescape(re.sub(r"<[^>]+>", "", m.group(1))) if m else ""

    def _ctx_plan(self) -> tuple[str | None, bool]:
        in_summary = False
        for tag, a in reversed(self.stack):
            if tag == "summary":
                in_summary = True
            if tag == "details" and "plan" in (a.get("class") or "").split():
                return a.get("data-plan") or "", in_summary
        return None, False

    def _section(self) -> str | None:
        for _t, a in reversed(self.stack):
            if a.get("id") in self.SECTION_IDS:
                return a.get("id")
        return None

    def _in_priority(self) -> bool:
        return any(t == "section" and a.get("id") == "priority" for t, a in self.stack)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        self.pos += 1
        if tag in self.VOID:
            return
        cls = (a.get("class") or "").split()
        if tag == "section" and "lanes" in cls:
            self.lanes_pos = self.pos
        if a.get("id") == "queue":
            self.queue_pos = self.pos
        if a.get("id") == "ready":
            self.ready_pos = self.pos
        if tag == "section" and a.get("id") == "priority":
            self.priority = {"h2": "", "lis": [], "ps": [], "has_ol": False}
            self.priority_pos = self.pos
        plan, in_summary = self._ctx_plan()
        if tag == "details" and "plan" in cls:
            name = a.get("data-plan") or ""
            self.plans[name] = {"section": self._section(), "seq": [], "chips": [], "infos": []}
            sec = self._section()
            if sec:
                self.order[sec].append(name)
        elif plan is not None and in_summary and tag == "span":
            rec = self.plans[plan]
            if "name" in cls:
                rec["seq"].append("name")
            if "badge" in cls:
                rec["seq"].append("badge")
            if "data-chip" in a:
                chip = {"attrs": a, "text": ""}
                rec["chips"].append(chip)
                rec["seq"].append(a.get("data-chip") or "")
                self._new.append((chip, "chip"))
        elif plan is not None and not in_summary and "info" in cls:
            info = {"text": "", "raw_b": False}
            self.plans[plan]["infos"].append(info)
            self._new.append((info, "info"))
        if self._in_priority() or (tag == "section" and a.get("id") == "priority"):
            if tag == "ol":
                self.priority["has_ol"] = True
            if tag in ("li", "p", "h2"):
                entry = {"attrs": a, "text": ""}
                if tag == "li":
                    self.priority["lis"].append(entry)
                elif tag == "p":
                    self.priority["ps"].append(entry)
                else:
                    self.priority["h2"] = entry
                self._new.append((entry, tag))
        self.stack.append((tag, a))
        for entry, kind in self._new:
            self._caps.append((entry, kind, len(self.stack), tag))
        self._new = []

    def handle_data(self, data):
        for c in self._caps:
            c[0]["text"] += data

    def handle_endtag(self, tag):
        for i in range(len(self._caps) - 1, -1, -1):
            if self._caps[i][3] == tag and self._caps[i][2] == len(self.stack):
                del self._caps[i]
                break
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break

    # ---- чтения
    def chips(self, plan: str, kind: str = "priority") -> list[dict]:
        assert plan in self.plans, f"плана {plan!r} нет на странице; есть: {sorted(self.plans)}"
        return [c for c in self.plans[plan]["chips"] if c["attrs"].get("data-chip") == kind]

    def need_priority(self) -> dict:
        assert self.priority is not None, 'нет <section id="priority">'
        return self.priority

    def h2(self) -> str:
        h = self.need_priority()["h2"]
        assert h, "в #priority нет <h2>"
        return _norm(h["text"])

    def lis(self) -> list[dict]:
        return self.need_priority()["lis"]

    def li_priorities(self) -> list[str | None]:
        return [li["attrs"].get("data-priority") for li in self.lis()]

    def ready(self) -> str:
        assert self.ready_pos is not None, "нет #ready"
        return _norm(self.ready_text)


def render(root: Path, tmp_path: Path) -> Page:
    out = tmp_path / f"page_{next(_counter)}.html"
    cp = _run(root, "--html", str(out))
    assert cp.returncode == 0, f"--html: {_out(cp)}"
    assert out.is_file(), f"страница не записана: {_out(cp)}"
    return Page(out.read_text(encoding="utf-8"))


def text_of(entry: dict) -> str:
    return _norm(entry["text"])


def ab_fixture(tmp_path: Path, name: str = "r", snapshot: bool = True) -> Path:
    """a-plan, b-plan в §4.1 (порядок a, b), оба стартуют; снимок 1 -> b-plan, 2 -> a-plan."""
    snap = [snap_row(1, "Ж", "b-plan", nxt="шаг Б", wait="ничего"), snap_row(2, "С", "a-plan", nxt="шаг А", wait="API")]
    return make_root(
        tmp_path,
        name,
        plans_of("a-plan", "b-plan"),
        order_md(["a-plan", "b-plan"], snapshot=snap if snapshot else None),
    )


# =========================================================================== P1: очередь и #ready


def test_p1_queue_follows_snapshot_priority_not_section_order(tmp_path):
    page = render(ab_fixture(tmp_path), tmp_path)
    assert page.order["queue"] == ["b-plan", "a-plan"]


def test_p1_priority_chips_carry_number_text_and_attribute(tmp_path):
    page = render(ab_fixture(tmp_path), tmp_path)
    cb, ca = page.chips("b-plan"), page.chips("a-plan")
    assert len(cb) == 1 and len(ca) == 1
    assert (cb[0]["attrs"].get("data-priority"), text_of(cb[0])) == ("1", "#1")
    assert (ca[0]["attrs"].get("data-priority"), text_of(ca[0])) == ("2", "#2")
    assert "chip" in (cb[0]["attrs"].get("class") or "").split()


def test_p1_priority_chip_is_the_first_chip_right_after_the_name(tmp_path):
    page = render(ab_fixture(tmp_path), tmp_path)
    seq = page.plans["b-plan"]["seq"]
    assert seq[:2] == ["name", "priority"], seq


def test_p1_ready_summary_lists_startable_plans_in_priority_order(tmp_path):
    page = render(ab_fixture(tmp_path), tmp_path)
    assert page.ready() == "можно начинать: b-plan, a-plan"


def test_p1_without_snapshot_order_is_old_no_chips_and_a_stub_line(tmp_path):
    without = render(ab_fixture(tmp_path, "plain", snapshot=False), tmp_path)
    with_snap = render(ab_fixture(tmp_path, "snap"), tmp_path)
    assert with_snap.order["queue"] == ["b-plan", "a-plan"]  # контроль: со «Снимком» порядок меняется
    assert without.order["queue"] == ["a-plan", "b-plan"]
    assert without.ready() == "можно начинать: a-plan, b-plan"
    assert [c for p in without.plans for c in without.chips(p)] == []
    assert [text_of(p) for p in without.need_priority()["ps"]] == [NO_TABLE]
    assert without.lis() == []


def test_p1_unprioritised_plans_follow_in_their_old_order(tmp_path):
    snap = [snap_row(1, "Ж", "c-plan")]
    root = make_root(
        tmp_path,
        "r",
        plans_of("a-plan", "c-plan", "b-plan", "d-plan"),
        order_md(["a-plan", "c-plan", "b-plan", "d-plan"], snapshot=snap),
    )
    page = render(root, tmp_path)
    assert page.order["queue"] == ["c-plan", "a-plan", "b-plan", "d-plan"]
    assert len(page.chips("c-plan")) == 1 and page.chips("a-plan") == []


def test_p1_queue_sorts_by_number_while_li_keep_table_order(tmp_path):
    snap = [snap_row(2, "С", "a-plan"), snap_row(1, "Ж", "b-plan")]  # таблица не по возрастанию
    root = make_root(tmp_path, "r", plans_of("a-plan", "b-plan"), order_md(["a-plan", "b-plan"], snapshot=snap))
    page = render(root, tmp_path)
    assert page.li_priorities() == ["2", "1"]
    assert page.order["queue"] == ["b-plan", "a-plan"]


# =========================================================================== P2: секция #priority


def test_p2_section_stands_after_ready_and_before_lanes(tmp_path):
    page = render(ab_fixture(tmp_path), tmp_path)
    assert page.ready_pos is not None and page.priority_pos is not None and page.lanes_pos is not None
    assert page.ready_pos < page.priority_pos < page.lanes_pos < (page.queue_pos or 10**9)


def test_p2_heading_carries_the_snapshot_date(tmp_path):
    assert render(ab_fixture(tmp_path), tmp_path).h2() == "Приоритеты · снимок 2026-10-03"


def test_p2_one_li_per_table_row_in_table_order_inside_an_ol(tmp_path):
    page = render(ab_fixture(tmp_path), tmp_path)
    assert page.need_priority()["has_ol"] is True
    assert page.li_priorities() == ["1", "2"]


def test_p2_li_text_is_literal(tmp_path):
    page = render(ab_fixture(tmp_path), tmp_path)
    assert text_of(page.lis()[0]) == "#1 · полоса Ж · b-plan — дальше: шаг Б · ждёт: ничего"
    assert text_of(page.lis()[1]) == "#2 · полоса С · a-plan — дальше: шаг А · ждёт: API"


def test_p2_row_with_non_integer_number_is_skipped(tmp_path):
    snap = [snap_row(1, plan="a-plan"), snap_row("x", plan="b-plan"), snap_row(3, plan="c-plan")]
    root = make_root(
        tmp_path, "r", plans_of("a-plan", "b-plan", "c-plan"), order_md(["a-plan", "b-plan", "c-plan"], snapshot=snap)
    )
    page = render(root, tmp_path)
    assert page.li_priorities() == ["1", "3"]
    assert len(page.chips("a-plan")) == 1 and page.chips("b-plan") == []


# =========================================================================== P3: имена в ячейке «План»


def test_p3_slug_part_gets_chip_and_phase_text_is_silently_skipped(tmp_path):
    snap = [snap_row(1, plan="c-plan, фаза 5"), snap_row(2, plan="zz-unknown")]
    root = make_root(tmp_path, "r", plans_of("c-plan"), order_md(["c-plan"], snapshot=snap))
    page = render(root, tmp_path)
    assert [text_of(c) for c in page.chips("c-plan")] == ["#1"]
    code, out = check_lines(root)
    lines = [ln for ln in out.splitlines() if ln.startswith("SNAPSHOT_UNKNOWN")]
    assert code == 0, out
    assert len(lines) == 1 and re.match(r"^SNAPSHOT_UNKNOWN ORDER\.md info\b", lines[0]) and "zz-unknown" in lines[0], (
        lines
    )
    assert not any("фаза" in ln or "c-plan" in ln for ln in lines)
    assert len(page.lis()) == 2  # обе строки таблицы видны на странице, даже без плана


def test_p3_plan_named_in_two_rows_gets_the_smaller_number(tmp_path):
    snap = [
        snap_row(3, plan="a-plan", nxt="шаг 3"),
        snap_row(5, plan="a-plan", nxt="шаг 5"),
        snap_row(4, plan="b-plan"),
    ]
    root = make_root(tmp_path, "r", plans_of("a-plan", "b-plan"), order_md(["b-plan", "a-plan"], snapshot=snap))
    page = render(root, tmp_path)
    assert [text_of(c) for c in page.chips("a-plan")] == ["#3"]
    assert [text_of(c) for c in page.chips("b-plan")] == ["#4"]
    assert page.order["queue"] == ["a-plan", "b-plan"]


def test_p3_one_row_naming_two_plans_marks_both(tmp_path):
    snap = [snap_row(1, plan="a-plan, b-plan")]
    root = make_root(tmp_path, "r", plans_of("a-plan", "b-plan"), order_md(["a-plan", "b-plan"], snapshot=snap))
    page = render(root, tmp_path)
    assert [text_of(c) for c in page.chips("a-plan")] == ["#1"] and [text_of(c) for c in page.chips("b-plan")] == ["#1"]


def test_p3_linked_part_is_resolved_through_its_path(tmp_path):
    snap = [snap_row(1, plan="[алиас](../b-plan/plan.md)")]
    root = make_root(tmp_path, "r", plans_of("a-plan", "b-plan"), order_md(["a-plan", "b-plan"], snapshot=snap))
    page = render(root, tmp_path)
    assert [text_of(c) for c in page.chips("b-plan")] == ["#1"]
    assert page.chips("a-plan") == []


def test_p3_unknown_slug_finding_is_info_and_does_not_block_while_known_name_is_silent(tmp_path):
    snap = [snap_row(1, plan="a-plan"), snap_row(2, plan="zz-unknown")]
    root = make_root(tmp_path, "r", plans_of("a-plan"), order_md(["a-plan"], snapshot=snap))
    code, out = check_lines(root)
    unknown = re.findall(r"^SNAPSHOT_UNKNOWN ORDER\.md (blocking|info)\b.*$", out, re.M)
    assert unknown == ["info"], out
    assert code == 0, out


def test_p3_all_names_known_gives_no_finding_and_unchanged_check_output(tmp_path):
    snap = [snap_row(1, plan="a-plan, b-plan")]
    with_snap = make_root(tmp_path, "s", plans_of("a-plan", "b-plan"), order_md(["a-plan", "b-plan"], snapshot=snap))
    plain = make_root(tmp_path, "p", plans_of("a-plan", "b-plan"), order_md(["a-plan", "b-plan"]))
    c1, o1 = check_lines(with_snap)
    c2, o2 = check_lines(plain)
    bad = make_root(tmp_path, "b", plans_of("a-plan"), order_md(["a-plan"], snapshot=[snap_row(1, plan="zz-unknown")]))
    assert "SNAPSHOT_UNKNOWN" in check_lines(bad)[1]  # контроль: находка вообще бывает
    assert "SNAPSHOT_UNKNOWN" not in o1
    assert (c1, o1.replace(str(with_snap), "R")) == (c2, o2.replace(str(plain), "R"))


# =========================================================================== P4: имена с датой, колонки, sync


def test_p4_dated_directory_matches_the_bare_slug(tmp_path):
    snap = [snap_row(1, plan="d-plan"), snap_row(2, plan="a-plan")]
    root = make_root(
        tmp_path, "r", plans_of("a-plan", "2026-10-01_d-plan"), order_md(["a-plan", "2026-10-01_d-plan"], snapshot=snap)
    )
    page = render(root, tmp_path)
    assert [text_of(c) for c in page.chips("2026-10-01_d-plan")] == ["#1"]
    assert page.order["queue"] == ["2026-10-01_d-plan", "a-plan"]
    code, out = check_lines(root)
    assert "SNAPSHOT_UNKNOWN" not in out and code == 0, out


def test_p4_exact_name_beats_dated_name(tmp_path):
    snap = [snap_row(1, plan="d-plan")]
    root = make_root(
        tmp_path, "r", plans_of("d-plan", "2026-10-01_d-plan"), order_md(["2026-10-01_d-plan", "d-plan"], snapshot=snap)
    )
    page = render(root, tmp_path)
    assert [text_of(c) for c in page.chips("d-plan")] == ["#1"]
    assert page.chips("2026-10-01_d-plan") == []


def test_p4_live_dated_plan_beats_archived_dated_plan(tmp_path):
    snap = [snap_row(1, plan="e-plan")]
    files = {
        **plans_of("2026-10-01_e-plan"),
        "plans/_archive/2026-Q3/2026-09-01_e-plan/plan.md": plan_md("—", ("DONE",)),
    }
    root = make_root(tmp_path, "r", files, order_md(["2026-10-01_e-plan"], snapshot=snap))
    page = render(root, tmp_path)
    assert [text_of(c) for c in page.chips("2026-10-01_e-plan")] == ["#1"]
    assert page.chips("2026-09-01_e-plan") == []


def test_p4_reordered_header_columns_give_the_same_priorities(tmp_path):
    cols = ["План", "Полоса", "#", "Следующий шаг", "Чего ждёт", "Сейчас"]
    snap = [snap_row(1, "Ж", "b-plan", nxt="шаг Б", wait="ничего"), snap_row(2, "С", "a-plan", nxt="шаг А", wait="API")]
    root = make_root(
        tmp_path, "r", plans_of("a-plan", "b-plan"), order_md(["a-plan", "b-plan"], snapshot=snap, cols=cols)
    )
    page = render(root, tmp_path)
    assert page.order["queue"] == ["b-plan", "a-plan"]
    assert [text_of(c) for c in page.chips("b-plan")] == ["#1"]
    assert text_of(page.lis()[0]) == "#1 · полоса Ж · b-plan — дальше: шаг Б · ждёт: ничего"


def _block(order: Path) -> str:
    text = order.read_text(encoding="utf-8")
    m = re.search(r"<!-- progress:begin -->(.*?)<!-- progress:end -->", text, re.S)
    assert m, "в ORDER.md нет блока progress:begin…end"
    return m.group(1)


def test_p4_sync_order_block_is_the_same_with_and_without_snapshot(tmp_path):
    snap = [snap_row(1, plan="b-plan"), snap_row(2, plan="a-plan")]
    with_snap = make_root(
        tmp_path, "s", plans_of("a-plan", "b-plan"), order_md(["a-plan", "b-plan"], snapshot=snap, markers=True)
    )
    plain = make_root(tmp_path, "p", plans_of("a-plan", "b-plan"), order_md(["a-plan", "b-plan"], markers=True))
    for root in (with_snap, plain):
        cp = _run(root, "--sync-order")
        assert cp.returncode == 0, _out(cp)
    b1, b2 = _block(with_snap / "plans/queue/ORDER.md"), _block(plain / "plans/queue/ORDER.md")
    assert "a-plan" in b2 and b2.index("a-plan") < b2.index("b-plan"), "контроль: блок не пуст и в порядке §4.1"
    assert b1 == b2


# =========================================================================== P5: тело плана, §4.2


def test_p5_body_starts_with_the_priority_info_line(tmp_path):
    page = render(ab_fixture(tmp_path), tmp_path)
    infos = [_norm(i["text"]) for i in page.plans["b-plan"]["infos"]]
    assert infos[0] == "Приоритет #1: дальше — шаг Б; ждёт — ничего"
    assert any("plans/b-plan/plan.md" in t for t in infos[1:])  # прежняя .info с путём осталась
    assert re.search(r"<b>Приоритет #1:</b>", page.raw)


def test_p5_plan_without_priority_has_no_priority_info(tmp_path):
    snap = [snap_row(1, plan="b-plan")]
    root = make_root(tmp_path, "r", plans_of("a-plan", "b-plan"), order_md(["a-plan", "b-plan"], snapshot=snap))
    page = render(root, tmp_path)
    assert _norm(page.plans["b-plan"]["infos"][0]["text"]).startswith("Приоритет #1:")  # контроль
    assert not any("Приоритет" in i["text"] for i in page.plans["a-plan"]["infos"])


def test_p5_info_comes_from_the_row_with_the_smallest_number(tmp_path):
    snap = [snap_row(5, plan="a-plan", nxt="шаг 5", wait="пять"), snap_row(3, plan="a-plan", nxt="шаг 3", wait="три")]
    root = make_root(tmp_path, "r", plans_of("a-plan"), order_md(["a-plan"], snapshot=snap))
    page = render(root, tmp_path)
    assert _norm(page.plans["a-plan"]["infos"][0]["text"]) == "Приоритет #3: дальше — шаг 3; ждёт — три"


def test_p5_waiting_unlisted_and_archive_keep_their_order_while_chips_appear(tmp_path):
    snap = [snap_row(1, plan="b-plan"), snap_row(2, plan="w-b"), snap_row(3, plan="u-b"), snap_row(4, plan="z-b")]
    files = {**plans_of("a-plan", "b-plan"), **plans_of("w-a", "w-b", "u-a", "u-b"), **plans_of("z-a", "z-b")}
    order = order_md(["a-plan", "b-plan"], q42=("w-a", "w-b"), q43=("z-a", "z-b"), snapshot=snap)
    page = render(make_root(tmp_path, "r", files, order), tmp_path)
    assert page.order["queue"] == ["b-plan", "a-plan"]  # контроль: очередь переставлена
    assert page.order["waiting"] == ["w-a", "w-b"]
    assert page.order["unlisted"] == ["u-a", "u-b"]
    assert page.order["archive"] == ["z-a", "z-b"]
    assert [text_of(c) for c in page.chips("w-b")] == ["#2"]
    assert [text_of(c) for c in page.chips("u-b")] == ["#3"]


# =========================================================================== P6: экранирование, чистота, --json, реальное дерево


def test_p6_cells_with_script_and_ampersand_are_escaped(tmp_path):
    snap = [snap_row(1, plan="a-plan", nxt="<script>alert(1)</script> & шаг", wait="a & b")]
    root = make_root(tmp_path, "r", plans_of("a-plan"), order_md(["a-plan"], snapshot=snap))
    page = render(root, tmp_path)
    assert len(page.chips("a-plan")) == 1  # контроль: строка разобрана
    low = page.raw.lower()
    assert "<script" not in low
    assert "&lt;script&gt;" in low
    assert "&amp;" in page.raw
    assert "http://" not in low and "https://" not in low
    assert "alert(1)" in text_of(page.lis()[0]) and "a & b" in text_of(page.lis()[0])


def test_p6_json_keeps_old_keys_and_record_order_without_priority(tmp_path):
    root = ab_fixture(tmp_path)
    cp = _run(root, "--json")
    assert cp.returncode == 0, _out(cp)
    data = json.loads(cp.stdout)
    assert [r["plan"].removesuffix(".md") for r in data] == ["a-plan", "b-plan"]
    for r in data:
        assert list(r) == OLD_JSON_KEYS, list(r)
        assert "priority" not in r
    assert len(render(root, tmp_path).chips("b-plan")) == 1  # контроль: на странице приоритет есть


def test_p6_real_tree_page_builds_and_has_the_priority_section(tmp_path):
    out = tmp_path / "real.html"
    cp = _run(REPO_ROOT, "--html", str(out))
    assert cp.returncode == 0, _out(cp)
    page = Page(out.read_text(encoding="utf-8"))
    assert page.priority is not None, 'в реальной странице нет <section id="priority">'
    assert page.h2().startswith("Приоритеты · снимок ")
    assert len(page.lis()) >= 1
