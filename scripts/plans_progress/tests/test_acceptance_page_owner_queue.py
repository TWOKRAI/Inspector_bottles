# ruff: noqa: E501  -- литералы-фикстуры и ожидания в одну строку, форматтер их не переносит
"""Приёмка Task 6.2 — слепые тесты колонки «Очередь владельца» на странице `--html`.

Источник: plans/2026-10-02_plans-progress-dashboard/tasks/6.2.md, ред. 3 (DESIGN, ACCEPTANCE P1-P9).
Реализацию страницы тестер не видел (RED до кода); читал только спек, conftest, соседние test_acceptance_*.py
и README. Из plans_progress.py ничего не читалось и не импортировалось.

Только CLI в subprocess (timeout 120 с на вызов): `plans_progress.py --root R [--order F] [--now ISO] --html F`,
для P2/P9 — ещё `--json`, `--queue`, `--check`. Страницу разбирает свой HTMLParser (дерево узлов); P6 сравнивает
подстроки СЫРОГО html (не дерево), P8 режет `<style>` на правила. Ожидания — литералы из спека.

Красные до кода (нет `<aside id="owner-queue">`): всё, что требует колонку — P1, P2 (пустой блок, контроль «маркеры
добавили — колонка есть»), P3, P4, P5, P6, P7, P8 (правило вкладки, «нет display», «нет id/anchor в колонке»), P9
(колонка на реальном дереве), а также DESIGN-тесты заголовка/заметки/разметки пункта.
ОХРАНА (зелёные до кода, помечены `GUARD` в docstring): P1 метка вкладки; P2 «нет колонки без маркеров / с --order на
несуществующий файл»; P8 правило `:target` дословно и CSS <= 6900 байт; P9 `--json`, `--queue`, реальное дерево
(exit 0, нет `<script`); перекрёстные проверки «текст чипа = находка `--check`».

Договорённости чтения (в тексте задачи неоднозначно; выбрано строгое чтение, всё продублировано в отчёте):
- Текст элемента = textContent (куски без разделителя), затем пробелы схлопываются (`" ".join(s.split())`).
  Так лишний/недостающий перенос между тегами не ломает литерал, а `·`, `—`, `⚠` сравниваются точно.
- Названия задач в фикстуре — не `x`, как в 6.1, а различимые («Первый шаг», «Второй шаг», …): иначе «текст
  содержит название задачи» совпало бы с любым `x` на странице.
- Каждый тест «чего-то нет» отдельно (охрана), а парой к нему — тест «колонка с блоком есть» (красный): так заглушка,
  которая вообще не рисует колонку, не даёт зелёного «нет колонки» вхолостую.
- P2 «`--order` на несуществующий путь»: в корне лежит `plans/queue/ORDER.md` С блоком, `--order` уводит читателя
  на несуществующий файл; контроль — тот же корень без `--order` даёт колонку.
- P6: чип сравнивается строкой сырого html: ищется `<span ... data-chip="active" ...>...</span>` с учётом вложенных
  `span`; чипы вне `<aside id="owner-queue">` — карточки, внутри — колонка.
- P8: «правило» — `селектор{тело}`; `@media`/`@supports` раскрываются до внутренних правил. Селектор правила вкладки
  сравнивается без пробелов; две обязательные подстроки (`#tab-queue…` и `:target…`) ищутся в тексте CSS дословно.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
PROGRESS = REPO_ROOT / "scripts" / "plans_progress" / "plans_progress.py"
CALL_TIMEOUT = 120

BEGIN = "<!-- owner-queue:begin -->"
END = "<!-- owner-queue:end -->"
HEADER = "| # | План | Задача | Заметка |"

NOW = "2026-10-03T12:00:00"
_NOW_DT = datetime.fromisoformat(NOW)

TAB_RULE_SELECTOR = "main:has(#tab-queue:checked)>:not(header,#queue,#owner-queue)"
TARGET_RULE = "main:has(.anchor:target)>:not(header,:has(.anchor:target)){display:none!important}"
OLD_PLAN_KEYS = [
    "plan", "path", "archived", "lane", "tier", "done", "total", "dropped", "unknown", "unmarked",
    "header_status", "tasks", "after", "after_reason", "waiting_on", "ready", "dep_unknown", "dep_cycle",
]  # fmt: skip
OLD_TASK_KEYS = ["id", "title", "status", "ref", "after", "ready"]


# =========================================================================== фикстура (как в 6.1)


def plan_md(*tasks: tuple[str, str, str], header: tuple[str, ...] = ()) -> str:
    lines = ["# План", "", "- **После:** —", *header, "", "## Порядок выполнения", ""]
    lines += [f"- Task {tid}: {title} [{status}]" for tid, title, status in tasks]
    return "\n".join(lines) + "\n"


PLANS = {
    "plans/a-plan/plan.md": plan_md(("1.1", "Первый шаг", "DONE"), ("1.2", "Второй шаг", "PENDING")),
    "plans/2026-10-01_b-plan/plan.md": plan_md(("2.1", "Шаг Б", "PENDING")),
    "plans/c-plan/plan.md": plan_md(("3.1", "Сделано раз", "DONE"), ("3.2", "Сделано два", "DONE")),
    "plans/e-plan/plan.md": plan_md(("5.1", "Шаг Э", "PENDING")),
}


def sep_for(header: str) -> str:
    return "|" + "---|" * len(header.strip().strip("|").split("|"))


def qblock(*rows: str, header: str = HEADER) -> str:
    return "\n".join([BEGIN, header, sep_for(header), *rows, END])


def order_text(
    block: str | None = None, rows41: tuple[str, ...] = ("a-plan",), rows43: tuple[str, ...] = ("e-plan",)
) -> str:
    """ORDER.md: §4.1 (a-plan), §4.2 пуст, §4.3 (e-plan); блок — в конце файла.

    b-plan (2026-10-01_b-plan) нет в §4.1-4.3 — он «вне списка». c-plan тоже вне списка, но закрыт по задачам.
    """
    out = [
        "# Порядок работ и контроль планов",
        "",
        "## 4. Контроль планов",
        "",
        "### 4.1 Активные — в работе или следующие",
        "",
        "| План | Полоса | Статус | Следующий шаг |",
        "|---|---|---|---|",
        *[f"| [{n}](../{n}/plan.md) | Ж | статус | шаг |" for n in rows41],
        "",
        "### 4.2 Ждут триггера — не трогать до условия",
        "",
        "| План | Остаток | Триггер |",
        "|---|---|---|",
        "",
        "### 4.3 Закрыты или поглощены — кандидаты в `_archive/`",
        "",
        "| План | Факт |",
        "|---|---|",
        *[f"| [{n}](../{n}/plan.md) | DONE |" for n in rows43],
        "",
    ]
    if block is not None:
        out += [block, ""]
    return "\n".join(out)


def make_root(tmp_path: Path, name: str, order: str, plans: dict[str, str] | None = None) -> Path:
    root = tmp_path / name
    for rel, text in {**(PLANS if plans is None else plans), "plans/queue/ORDER.md": order}.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(text.encode("utf-8"))
    return root


def queue_root(tmp_path: Path, name: str, *rows: str, header: str = HEADER) -> Path:
    return make_root(tmp_path, name, order_text(qblock(*rows, header=header)))


# Блок из Q1 6.1 (ACCEPTANCE P1, P9)
P1_ROWS = ("| 1 | b-plan | | сначала Б |", "| 2 | [a-plan](../a-plan/plan.md) | Task 1.2 | потом |")
P1_ITEMS = [
    {
        "n": 1,
        "kind": "plan",
        "plan": "2026-10-01_b-plan",
        "task": None,
        "note": "сначала Б",
        "known": True,
        "closed": False,
    },
    {"n": 2, "kind": "task", "plan": "a-plan", "task": "1.2", "note": "потом", "known": True, "closed": False},
]


# =========================================================================== запуск CLI


def _env() -> dict[str, str]:
    env = dict(os.environ)
    for var in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"):
        env.pop(var, None)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def run_cli(root: Path, *flags: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROGRESS), "--root", str(root), *flags],
        capture_output=True,
        timeout=CALL_TIMEOUT,
        env=_env(),
        encoding="utf-8",
        errors="replace",
    )


def _out(cp: subprocess.CompletedProcess) -> str:
    return f"exit={cp.returncode}\nstdout={cp.stdout[:500]!r}\nstderr={cp.stderr[:500]!r}"


_counter = {"n": 0}


def render(root: Path, out_dir: Path, *flags: str) -> "Page":
    _counter["n"] += 1
    out = out_dir / f"page_{_counter['n']}.html"
    cp = run_cli(root, *flags, "--html", str(out))
    assert cp.returncode == 0, f"--html: {_out(cp)}"
    assert out.is_file(), f"страница не записана: {_out(cp)}"
    return Page(out.read_text(encoding="utf-8"))


# =========================================================================== разбор страницы (дерево)

VOID = {"br", "meta", "link", "img", "input", "hr", "area", "base", "col", "embed", "source", "track", "wbr"}


class Node:
    def __init__(self, tag: str, attrs: dict[str, str | None], parent: "Node | None") -> None:
        self.tag = tag
        self.attrs = attrs
        self.parent = parent
        self.children: list[Node | str] = []

    def classes(self) -> set[str]:
        return set((self.attrs.get("class") or "").split())

    def elems(self) -> list["Node"]:
        return [c for c in self.children if isinstance(c, Node)]

    def walk(self):
        yield self
        for c in self.elems():
            yield from c.walk()

    def raw_text(self) -> str:
        parts: list[str] = []
        for c in self.children:
            parts.append(c if isinstance(c, str) else c.raw_text())
        return "".join(parts)

    def text(self) -> str:
        return " ".join(self.raw_text().split())

    def descendants(self) -> list["Node"]:
        return [n for n in self.walk() if n is not self]

    def find_all(self, tag: str | None = None, cls: str | None = None, **attrs: str) -> list["Node"]:
        return [
            n
            for n in self.descendants()
            if (tag is None or n.tag == tag)
            and (cls is None or cls in n.classes())
            and all(n.attrs.get(k.replace("_", "-")) == v for k, v in attrs.items())
        ]

    def ancestors(self):
        n = self.parent
        while n is not None:
            yield n
            n = n.parent

    def prev_elem(self) -> "Node | None":
        if self.parent is None:
            return None
        sib = self.parent.elems()
        i = sib.index(self)
        return sib[i - 1] if i > 0 else None


class _TreeBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("#doc", {}, None)
        self.cur = self.root

    def handle_starttag(self, tag, attrs):
        node = Node(tag, dict(attrs), self.cur)
        self.cur.children.append(node)
        if tag not in VOID:
            self.cur = node

    def handle_startendtag(self, tag, attrs):
        self.cur.children.append(Node(tag, dict(attrs), self.cur))

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        n: Node | None = self.cur
        while n is not None and n.tag != tag:
            n = n.parent
        if n is not None and n.parent is not None:
            self.cur = n.parent

    def handle_data(self, data):
        self.cur.children.append(data)


class Page:
    def __init__(self, html: str) -> None:
        self.html = html
        b = _TreeBuilder()
        b.feed(html)
        b.close()
        self.doc = b.root

    def by_id(self, ident: str) -> list[Node]:
        return [n for n in self.doc.walk() if n.attrs.get("id") == ident]

    def column(self) -> Node:
        """`aside#owner-queue`; единственный, иначе тест красный с понятной причиной."""
        found = self.by_id("owner-queue")
        assert found, 'на странице нет элемента с id="owner-queue" (колонки «Очередь владельца» нет)'
        assert len(found) == 1, f'элементов с id="owner-queue": {len(found)}, нужен ровно один'
        assert found[0].tag == "aside", f"id=owner-queue у <{found[0].tag}>, нужен <aside>"
        return found[0]

    def tab_label(self, tab_id: str) -> str:
        labels = [n for n in self.doc.find_all("label") if n.attrs.get("for") == tab_id]
        assert len(labels) == 1, f"меток for={tab_id!r}: {len(labels)}"
        return labels[0].text()


def items_of(col: Node) -> list[Node]:
    ols = col.find_all("ol")
    assert len(ols) == 1, f"в колонке <ol>: {len(ols)}, нужен ровно один"
    return [c for c in ols[0].elems() if c.tag == "li"]


def problem_chips(node: Node) -> list[Node]:
    return [n for n in node.descendants() if n.attrs.get("data-chip") == "queue-problem"]


def li_attr_names(li: Node) -> set[str]:
    return {k for k in li.attrs if k.startswith("data-")}


# =========================================================================== P1


@pytest.fixture
def p1(tmp_path):
    """Фикстура P1: Q1 6.1. Возвращает (root, Page)."""
    root = queue_root(tmp_path, "p1", *P1_ROWS)
    return root, render(root, tmp_path)


def test_p1_exactly_one_aside_owner_queue_right_after_section_queue_inside_main(p1):
    _, page = p1
    col = page.column()
    assert col.parent is not None and col.parent.tag == "main", f"родитель колонки: {col.parent and col.parent.tag}"
    prev = col.prev_elem()
    assert prev is not None and prev.tag == "section" and prev.attrs.get("id") == "queue", (
        f"перед колонкой: {prev and (prev.tag, prev.attrs.get('id'))}"
    )


def test_p1_h2_counts_open_of_total(p1):
    _, page = p1
    h2s = page.column().find_all("h2")
    assert [h.text() for h in h2s] == ["Очередь владельца · открыто 2 из 2"]


def test_design_column_starts_with_h2_then_note_line(p1):
    # DESIGN: `<h2>…</h2>`, под ним одна строка `<p class="note">правка — блок owner-queue в ORDER.md</p>`
    _, page = p1
    kids = page.column().elems()
    assert [k.tag for k in kids[:2]] == ["h2", "p"], [k.tag for k in kids]
    assert "note" in kids[1].classes()
    assert kids[1].text() == "правка — блок owner-queue в ORDER.md"


def test_p1_ol_has_class_owner_queue_and_two_li_in_order(p1):
    _, page = p1
    col = page.column()
    ols = col.find_all("ol")
    assert len(ols) == 1 and "owner-queue" in ols[0].classes()
    assert [li.attrs.get("data-n") for li in items_of(col)] == ["1", "2"]


def test_p1_plan_item_attributes_link_tally_and_note(p1):
    _, page = p1
    li = items_of(page.column())[0]
    assert li.attrs.get("data-n") == "1"
    assert li.attrs.get("data-kind") == "plan"
    assert li.attrs.get("data-plan") == "2026-10-01_b-plan"
    assert li_attr_names(li) == {"data-n", "data-kind", "data-plan"}, li_attr_names(li)
    links = li.find_all("a")
    assert [a.attrs.get("href") for a in links] == ["#plan-2026-10-01_b-plan"]
    tallies = li.find_all("span", "tally")
    assert [t.text() for t in tallies] == ["0 из 1 · 0%"]
    assert "— сначала Б" in li.text()
    assert li.text().index("0 из 1 · 0%") < li.text().index("— сначала Б")


def test_p1_task_item_attributes_link_id_title_status_note_no_tally(p1):
    _, page = p1
    li = items_of(page.column())[1]
    assert li.attrs.get("data-n") == "2"
    assert li.attrs.get("data-kind") == "task"
    assert li.attrs.get("data-plan") == "a-plan"
    assert li.attrs.get("data-task") == "1.2"
    assert li_attr_names(li) == {"data-n", "data-kind", "data-plan", "data-task"}, li_attr_names(li)
    assert [a.attrs.get("href") for a in li.find_all("a")] == ["#plan-a-plan"]
    assert [b.text() for b in li.find_all("b")] == ["1.2"]
    assert [s.text() for s in li.find_all("span", "st")] == ["ожидает"]
    assert li.find_all("span", "tally") == []
    text = li.text()
    for part in ("a-plan", "1.2", "Второй шаг", "ожидает", "— потом"):
        assert part in text, f"в тексте пункта нет {part!r}: {text!r}"
    # порядок частей: имя плана, id, название, статус, заметка
    pos = [text.index(p) for p in ("a-plan", "1.2", "Второй шаг", "ожидает", "— потом")]
    assert pos == sorted(pos), f"части пункта не по порядку: {text!r}"


def test_p1_anchor_targets_exist_exactly_once_on_page(p1):
    _, page = p1
    hrefs = [a.attrs.get("href") for li in items_of(page.column()) for a in li.find_all("a")]
    assert hrefs == ["#plan-2026-10-01_b-plan", "#plan-a-plan"]
    for href in hrefs:
        assert len(page.by_id(href[1:])) == 1, f"элементов с id={href[1:]!r}: {len(page.by_id(href[1:]))}"


def test_p1_no_problem_chips_and_no_strike_in_column(p1):
    _, page = p1
    col = page.column()
    assert items_of(col), "контроль: пункты в колонке есть"
    assert problem_chips(col) == []
    assert col.find_all("s") == []


def test_p1_guard_queue_tab_label_stays_one(p1):
    """GUARD (зелёный до кода): число на вкладке «Очередь» не меняется (a-plan в §4.1 — одна карточка)."""
    _, page = p1
    assert page.tab_label("tab-queue") == "Очередь · 1"


# =========================================================================== P2


def _no_column_roots(tmp_path: Path) -> dict[str, tuple[Path, tuple[str, ...]]]:
    table = "\n".join([HEADER, sep_for(HEADER), "| 1 | a-plan | | |"])
    return {
        "no-markers": (make_root(tmp_path, "nm", order_text(table)), ()),
        "order-flag-missing-file": (
            make_root(tmp_path, "mf", order_text(qblock("| 1 | a-plan | | |"))),
            ("--order", str(tmp_path / "net-takogo-ORDER.md")),
        ),
    }


@pytest.mark.parametrize("variant", ["no-markers", "order-flag-missing-file"])
def test_p2_guard_no_column_and_no_title_text_without_block(tmp_path, variant):
    """GUARD (зелёный до кода): нет маркеров / `--order` на несуществующий файл -> страница как до 6.2, exit 0."""
    root, extra = _no_column_roots(tmp_path)[variant]
    page = render(root, tmp_path, *extra)  # render требует exit 0
    assert page.by_id("owner-queue") == []
    assert "Очередь владельца" not in page.html
    assert page.doc.find_all("aside") == []


def test_p2_control_markers_around_same_table_create_the_column(tmp_path):
    """Пара к охране: тот же стол без `--order`-подвоха, но с маркерами -> колонка есть (иначе охрана вхолостую)."""
    root = make_root(tmp_path, "ctl", order_text(qblock("| 1 | a-plan | | |")))
    page = render(root, tmp_path)
    assert len(items_of(page.column())) == 1


def test_p2_control_order_flag_pointing_at_real_file_creates_the_column(tmp_path):
    """Пара к охране `--order` на несуществующий путь: тот же корень без флага даёт колонку."""
    root = make_root(tmp_path, "ctl2", order_text(qblock("| 1 | a-plan | | |")))
    assert len(items_of(render(root, tmp_path).column())) == 1


def test_p2_header_and_separator_only_block_gives_empty_column(tmp_path):
    root = make_root(tmp_path, "empty", order_text("\n".join([BEGIN, HEADER, sep_for(HEADER), END])))
    col = render(root, tmp_path).column()
    assert [h.text() for h in col.find_all("h2")] == ["Очередь владельца · открыто 0 из 0"]
    assert col.find_all("ol") == []
    assert col.find_all("li") == []
    assert [p.text() for p in col.find_all("p") if p.text() == "очередь пуста"] == ["очередь пуста"]
    assert problem_chips(col) == []


# =========================================================================== P3


P3_ROWS = ("| 1 | a-plan | 1.1 | |", "| 2 | c-plan | | |", "| 3 | e-plan | 5.1 | |", "| 4 | a-plan | 1.2 | |")


@pytest.fixture
def p3(tmp_path):
    return render(queue_root(tmp_path, "p3", *P3_ROWS), tmp_path)


def test_p3_first_three_items_closed_with_exactly_one_strike_fourth_open(p3):
    lis = items_of(p3.column())
    assert len(lis) == 4
    assert [li.attrs.get("data-closed") for li in lis] == ["1", "1", "1", None]
    assert [len(li.find_all("s")) for li in lis] == [1, 1, 1, 0]


def test_p3_strike_texts_hold_name_task_status_and_tally(p3):
    lis = items_of(p3.column())
    s1, s2, s3 = (li.find_all("s")[0].text() for li in lis[:3])
    for part in ("a-plan", "1.1", "готово"):
        assert part in s1, f"в <s> 1-го пункта нет {part!r}: {s1!r}"
    for part in ("c-plan", "2 из 2 · 100%"):
        assert part in s2, f"в <s> 2-го пункта нет {part!r}: {s2!r}"
    for part in ("e-plan", "5.1"):
        assert part in s3, f"в <s> 3-го пункта нет {part!r}: {s3!r}"


def test_p3_no_problem_chips_and_no_data_known_on_any_item(p3):
    col = p3.column()
    lis = items_of(col)
    assert len(lis) == 4, "контроль: колонка с четырьмя пунктами"
    assert problem_chips(col) == []
    assert [li.attrs.get("data-known") for li in lis] == [None] * 4
    assert all("data-known" not in li.attrs for li in lis)


def test_p3_h2_counts_one_open_of_four(p3):
    assert [h.text() for h in p3.column().find_all("h2")] == ["Очередь владельца · открыто 1 из 4"]


def test_design_note_of_closed_item_stays_outside_strike(tmp_path):
    # DESIGN п.4/п.7: в <s> — части 1-3; заметка (`span.q-note`) снаружи
    root = queue_root(tmp_path, "note", "| 1 | a-plan | 1.1 | давно |", "| 2 | a-plan | 1.2 | живая |")
    lis = items_of(render(root, tmp_path).column())
    notes = lis[0].find_all("span", "q-note")
    assert [n.text() for n in notes] == ["— давно"]
    assert len(lis[0].find_all("s")) == 1
    assert all(s not in lis[0].find_all("s") for s in notes[0].ancestors()), "q-note внутри <s>"
    assert [n.text() for n in lis[1].find_all("span", "q-note")] == ["— живая"]


# =========================================================================== P4


P4_FIXTURE_ROWS = ("| 1 | zz-plan | | |", "| 2 | a-plan | 9.9 | |", "| 3 | | | x |", "| 4 | zz-plan | abc | |")
P4_CHIPS = [
    "⚠ плана zz-plan нет",
    "⚠ в плане a-plan нет задачи 9.9",
    "⚠ в ячейке «План» нужно ровно одно имя плана, сейчас: —",
    "⚠ в ячейке «Задача» не номер задачи: abc",
]


@pytest.fixture
def p4(tmp_path):
    root = queue_root(tmp_path, "p4", *P4_FIXTURE_ROWS)
    return root, render(root, tmp_path)


def test_p4_all_four_items_are_unknown_data_known_zero(p4):
    _, page = p4
    col = page.column()
    lis = items_of(col)
    assert len(lis) == 4
    assert [li.attrs.get("data-known") for li in lis] == ["0"] * 4


def test_p4_only_second_item_has_plan_link(p4):
    _, page = p4
    col = page.column()
    lis = items_of(col)
    assert [[a.attrs.get("href") for a in li.find_all("a")] for li in lis] == [[], ["#plan-a-plan"], [], []]


def test_p4_problem_chip_texts_in_order_one_per_item(p4):
    _, page = p4
    col = page.column()
    lis = items_of(col)
    assert [[c.text() for c in problem_chips(li)] for li in lis] == [[t] for t in P4_CHIPS]
    assert [c.text() for c in problem_chips(col)] == P4_CHIPS
    for chip in problem_chips(col):
        assert chip.tag == "span" and {"chip", "warn"} <= chip.classes(), (chip.tag, chip.classes())


def test_p4_item_text_starts_with_plan_value_or_dash(p4):
    _, page = p4
    col = page.column()
    lis = items_of(col)
    assert lis[0].text().startswith("zz-plan")
    assert lis[2].text().startswith("—")


def test_p4_h2_counts_four_open_of_four(p4):
    _, page = p4
    col = page.column()
    assert [h.text() for h in col.find_all("h2")] == ["Очередь владельца · открыто 4 из 4"]


def test_p4_data_attributes_follow_queue_item_values(p4):
    # DESIGN: data-task — только у kind=task (3-й пункт и 1-й — kind=plan); значения — как в пункте `--queue`
    _, page = p4
    col = page.column()
    lis = items_of(col)
    assert [li.attrs.get("data-kind") for li in lis] == ["plan", "task", "plan", "task"]
    assert [li.attrs.get("data-plan") for li in lis] == ["zz-plan", "a-plan", "", "zz-plan"]
    assert [li.attrs.get("data-task") for li in lis] == [None, "9.9", None, "abc"]
    assert [li.attrs.get("data-closed") for li in lis] == [None] * 4


def test_p4_guard_chip_texts_are_check_findings_without_item_prefix(p4):
    """GUARD (зелёный до кода): `⚠ <текст>` — это находка `--check` без начала `пункт N очереди владельца: `."""
    root, _ = p4
    cp = run_cli(root, "--check")
    stream = cp.stdout + "\n" + cp.stderr
    for n, chip in enumerate(P4_CHIPS, 1):
        tail = chip[2:]
        assert f"пункт {n} очереди владельца: {tail}" in stream, (
            f"в --check нет находки пункта {n}: {tail!r}\n{stream[-800:]}"
        )


def test_p4_closed_known_false_never_gets_problem_chip_but_unknown_open_does(tmp_path):
    # DESIGN п.5: закрытый пункт (OWNER_QUEUE_CLOSED) чипа не получает; охрана: рядом неизвестный пункт чип получает
    root = queue_root(tmp_path, "mix", "| 1 | a-plan | 1.1 | |", "| 2 | zz-plan | | |")
    lis = items_of(render(root, tmp_path).column())
    assert problem_chips(lis[0]) == [] and lis[0].attrs.get("data-closed") == "1" and "data-known" not in lis[0].attrs
    assert [c.text() for c in problem_chips(lis[1])] == ["⚠ плана zz-plan нет"]


# =========================================================================== P5


BAD_MARKERS_TEXT = (
    "⚠ нужна ровно одна пара маркеров <!-- owner-queue:begin --> / <!-- owner-queue:end --> "
    "отдельными строками, найдено: owner-queue:begin 2, owner-queue:end 1"
)
NO_PLAN_COLUMN_TEXT = "⚠ в блоке нет таблицы с колонкой «План»"


def _p5_markers_root(tmp_path: Path) -> Path:
    table = "\n".join([HEADER, sep_for(HEADER), "| 1 | a-plan | | |"])
    return make_root(tmp_path, "p5a", order_text("\n".join([BEGIN, table, BEGIN, END])))


def test_p5_two_begin_one_end_gives_column_with_one_problem_paragraph_and_no_list(tmp_path):
    col = render(_p5_markers_root(tmp_path), tmp_path).column()
    assert col.find_all("ol") == []
    chips = problem_chips(col)
    assert len(chips) == 1
    assert chips[0].tag == "p" and {"chip", "warn"} <= chips[0].classes()
    assert chips[0].text() == BAD_MARKERS_TEXT
    assert [h.text() for h in col.find_all("h2")] == ["Очередь владельца · открыто 0 из 0"]
    assert [p.text() for p in col.find_all("p") if p.text() == "очередь пуста"] == [], (
        "«очередь пуста» вместе с проблемой"
    )


def test_p5_block_without_plan_column_gives_problem_paragraph(tmp_path):
    root = queue_root(tmp_path, "p5b", "| 1 | 1.2 | x |", header="| # | Задача | Заметка |")
    col = render(root, tmp_path).column()
    assert col.find_all("ol") == []
    assert [c.text() for c in problem_chips(col)] == [NO_PLAN_COLUMN_TEXT]
    assert [h.text() for h in col.find_all("h2")] == ["Очередь владельца · открыто 0 из 0"]


def test_p5_guard_block_problem_text_is_the_check_finding(tmp_path):
    """GUARD (зелёный до кода): текст проблемы блока — тот же, что у находки `OWNER_QUEUE_BLOCK` в `--check`."""
    for root, literal in (
        (_p5_markers_root(tmp_path), BAD_MARKERS_TEXT),
        (queue_root(tmp_path, "p5c", "| 1 | 1.2 | x |", header="| # | Задача | Заметка |"), NO_PLAN_COLUMN_TEXT),
    ):
        cp = run_cli(root, "--check")
        lines = [ln for ln in (cp.stdout + "\n" + cp.stderr).splitlines() if ln.startswith("OWNER_QUEUE_BLOCK")]
        assert len(lines) == 1, lines
        assert literal[2:] in lines[0], f"{literal[2:]!r} not in {lines[0]!r}"


# =========================================================================== P6


def _git(cwd: Path, *args: str) -> None:
    cp = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        timeout=CALL_TIMEOUT,
        env=_env(),
        encoding="utf-8",
        errors="replace",
    )
    assert cp.returncode == 0, f"git {' '.join(args)}: {cp.stderr[:400]}"


def _journal_line(ts: str) -> dict:
    return {
        "ts": ts,
        "event": "SubagentStart",
        "agent_type": "developer",
        "agent_id": "a1",
        "session_id": "s1",
        "source": "hook",
        "cwd": "x",
        "branch": "x",
        "tail": "",
    }


P6_ROWS = (
    "| 1 | x-plan | | план |",
    "| 2 | x-plan | 1.1 | открытая |",
    "| 3 | x-plan | 1.2 | закрытая |",
    "| 4 | x-plan | 9.9 | нет задачи |",
    "| 5 | y-plan | | другой план |",
)


@pytest.fixture
def p6(tmp_path):
    """Настоящий git + worktree по образцу 5.2/5.3; план x-plan с `Ветка: feat/x` и свежим журналом, план y-plan без worktree."""
    base = tmp_path.resolve()
    root = base / "repo"
    plans = {
        "plans/x-plan/plan.md": plan_md(
            ("1.1", "Открытая задача", "PENDING"), ("1.2", "Закрытая задача", "DONE"), header=("- **Ветка:** feat/x",)
        ),
        "plans/y-plan/plan.md": plan_md(("1.1", "Чужая задача", "PENDING")),
    }
    order = order_text(qblock(*P6_ROWS), rows41=("x-plan", "y-plan"), rows43=())
    for rel, text in {**plans, "plans/queue/ORDER.md": order, "NOTES.txt": "fixture"}.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(text.encode("utf-8"))
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "extensions.worktreeConfig", "true")
    _git(root, "config", "user.name", "tester")
    _git(root, "config", "user.email", "t@example.invalid")
    _git(root, "config", "core.autocrlf", "false")
    _git(root, "config", "commit.gpgsign", "false")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "init")
    wt = base / "wt_x"
    _git(root, "worktree", "add", "-q", "-b", "feat/x", str(wt), "main")
    journal = wt / "data" / "agent-journal.jsonl"
    journal.parent.mkdir(parents=True, exist_ok=True)
    ts = (_NOW_DT - timedelta(minutes=5)).isoformat(timespec="seconds")
    journal.write_bytes((json.dumps(_journal_line(ts), ensure_ascii=False) + "\n").encode("utf-8"))
    return root, render(root, tmp_path, "--now", NOW)


def _active_chips_raw(html: str) -> list[tuple[int, str]]:
    """Все `<span ... data-chip="active" ...>…</span>` сырого html: (позиция, строка); вложенные span считаются."""
    out = []
    for m in re.finditer(r"<span\b[^>]*>", html):
        if 'data-chip="active"' not in m.group(0):
            continue
        depth, pos = 1, m.end()
        for t in re.finditer(r"<span\b[^>]*>|</span>", html[m.end() :]):
            depth += -1 if t.group(0) == "</span>" else 1
            if depth == 0:
                pos = m.end() + t.end()
                break
        else:
            raise AssertionError(f"не закрыт span чипа active в позиции {m.start()}")
        out.append((m.start(), html[m.start() : pos]))
    return out


def _aside_range(html: str) -> tuple[int, int]:
    m = re.search(r'<aside\b[^>]*\bid="owner-queue"[^>]*>', html)
    assert m, 'в сыром html нет <aside id="owner-queue">'
    end = html.find("</aside>", m.end())
    assert end != -1, "<aside id=owner-queue> не закрыт"
    return m.start(), end + len("</aside>")


def test_p6_open_found_items_carry_active_chip_of_their_plan_closed_and_unknown_do_not(p6):
    _, page = p6
    # контроль: у карточки плана x-plan чип «в работе» есть (5.3), т.е. сама фикстура рабочая
    assert [c.attrs.get("data-active") for c in page.doc.find_all("span", data_chip="active")][:1] == ["feat/x"]
    lis = items_of(page.column())
    assert [li.attrs.get("data-n") for li in lis] == ["1", "2", "3", "4", "5"]
    chips = [li.find_all("span", data_chip="active") for li in lis]
    assert [len(c) for c in chips] == [1, 1, 0, 0, 0], [len(c) for c in chips]
    assert [c[0].attrs.get("data-active") for c in chips[:2]] == ["feat/x", "feat/x"]
    assert lis[2].attrs.get("data-closed") == "1" and lis[3].attrs.get("data-known") == "0", (
        "контроль: 3-й закрыт, 4-й неизвестен"
    )


def test_p6_column_chip_raw_markup_equals_card_chip(p6):
    _, page = p6
    page.column()  # колонка обязана быть (иначе сравнивать нечего)
    lo, hi = _aside_range(page.html)
    chips = _active_chips_raw(page.html)
    card = [raw for pos, raw in chips if not (lo <= pos < hi)]
    column = [raw for pos, raw in chips if lo <= pos < hi]
    assert len(card) == 1, f"чипов active на карточках: {len(card)}"
    assert len(column) == 2, f"чипов active в колонке: {len(column)}"
    assert column == [card[0], card[0]], (
        f"разметка чипа в колонке не равна карточке:\ncard={card[0]!r}\ncolumn={column!r}"
    )


def test_p6_item_of_other_plan_without_active_has_no_chip_while_neighbour_has(p6):
    _, page = p6
    lis = items_of(page.column())
    assert len(lis[1].find_all("span", data_chip="active")) == 1, "контроль: соседний пункт плана x-plan с чипом"
    assert lis[4].attrs.get("data-plan") == "y-plan"
    assert lis[4].find_all("span", data_chip="active") == []


# =========================================================================== P7


P7_NOTE = '<script>alert(1)</script> & "q"'


@pytest.fixture
def p7(tmp_path):
    root = queue_root(tmp_path, "p7", f"| 1 | a-plan | | {P7_NOTE} |", "| 2 | <b>zz</b> | | |")
    return render(root, tmp_path)


def test_p7_no_script_substring_and_column_present(p7):
    col = p7.column()  # колонка обязана быть: иначе «нет <script» зелёное вхолостую
    assert len(items_of(col)) == 2
    assert "<script" not in p7.html.lower()
    assert [n for n in p7.doc.walk() if n.tag == "script"] == []


def test_p7_note_text_survives_parse_unchanged(p7):
    assert P7_NOTE in p7.column().text()


def test_p7_plan_cell_markup_is_text_not_element(p7):
    li = items_of(p7.column())[1]
    assert li.find_all("b") == []
    assert li.text().startswith("<b>zz</b>")
    assert li.attrs.get("data-plan") == "<b>zz</b>"


# =========================================================================== P8


def css_of(page: Page) -> str:
    styles = page.doc.find_all("style")
    assert len(styles) == 1, f"<style> на странице: {len(styles)}"
    return "".join(c for c in styles[0].children if isinstance(c, str))


def css_rules(css: str) -> list[tuple[str, str]]:
    """[(селектор, тело)] для всех правил; @-правила с вложенными блоками раскрываются."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    out: list[tuple[str, str]] = []

    def parse(text: str) -> None:
        i = 0
        while i < len(text):
            j = text.find("{", i)
            if j == -1:
                return
            prelude = text[i:j].strip()
            depth, k = 1, j + 1
            while k < len(text) and depth:
                depth += {"{": 1, "}": -1}.get(text[k], 0)
                k += 1
            body = text[j + 1 : k - 1]
            if prelude.startswith("@") and "{" in body:
                parse(body)
            else:
                out.append((prelude, body))
            i = k

    parse(css)
    return out


@pytest.fixture
def p8(tmp_path):
    return render(queue_root(tmp_path, "p8", *P1_ROWS), tmp_path)


def test_p8_css_has_queue_tab_rule_literal(p8):
    assert TAB_RULE_SELECTOR in css_of(p8)


def test_p8_no_owner_queue_rule_other_than_tab_rule_sets_display(p8):
    rules = css_rules(css_of(p8))
    assert rules, "контроль: CSS разобран в правила"
    tab = [r for r in rules if r[0].replace(" ", "") == TAB_RULE_SELECTOR]
    assert len(tab) == 1, (
        f"правил вкладки с селектором {TAB_RULE_SELECTOR!r}: {len(tab)} (контроль: правило вкладки есть)"
    )
    offenders = [
        (sel, body)
        for sel, body in rules
        if "#owner-queue" in sel and sel.replace(" ", "") != TAB_RULE_SELECTOR and "display" in body
    ]
    assert offenders == [], f"в правилах с #owner-queue есть display: {offenders}"


def test_p8_guard_target_rule_kept_verbatim(p8):
    """GUARD (зелёный до кода): правило страницы плана (`:target`) на месте дословно."""
    assert TARGET_RULE in css_of(p8)


def test_p8_guard_css_at_most_6900_bytes_utf8(p8):
    """GUARD (зелёный до кода): запас CSS не съеден."""
    assert len(css_of(p8).encode("utf-8")) <= 6900


def test_p8_no_id_attribute_and_no_anchor_class_inside_column(p8):
    col = p8.column()
    assert items_of(col), "контроль: пункты в колонке есть"
    with_id = [(n.tag, n.attrs["id"]) for n in col.descendants() if "id" in n.attrs]
    assert with_id == [], f"в колонке элементы с id: {with_id}"
    assert [n for n in col.descendants() if "anchor" in n.classes()] == []


# =========================================================================== P9


def test_p9_guard_queue_stdout_equals_6_1_literal(tmp_path):
    """GUARD (зелёный до кода): `--queue` на фикстуре P1 печатает литерал Q1 6.1."""
    root = queue_root(tmp_path, "p9q", *P1_ROWS)
    cp = run_cli(root, "--queue")
    assert cp.returncode == 0, _out(cp)
    assert json.loads(cp.stdout) == {"items": P1_ITEMS}
    assert cp.stdout.strip() == json.dumps({"items": P1_ITEMS}, ensure_ascii=False, indent=2)


def test_p9_guard_json_keys_unchanged_and_no_queue_key(tmp_path):
    """GUARD (зелёный до кода): `--json` — те же ключи записи плана и задачи (5.2/7.1 + `branches`, `anchor`)."""
    root = queue_root(tmp_path, "p9j", *P1_ROWS)
    cp = run_cli(root, "--json")
    assert cp.returncode == 0, _out(cp)
    data = json.loads(cp.stdout)
    assert isinstance(data, list) and len(data) == 4, [r.get("plan") for r in data]
    for rec in data:
        assert list(rec) == [*OLD_PLAN_KEYS, "active", "branches", "anchor"], f"{rec['plan']}: {list(rec)}"
        for t in rec["tasks"]:
            assert list(t) == OLD_TASK_KEYS, f"{rec['plan']}: {list(t)}"


def test_p9_guard_real_tree_html_exit_zero_and_no_script(tmp_path):
    """GUARD (зелёный до кода): `--root` = корень репозитория: exit 0, в странице нет `<script`."""
    page = render(REPO_ROOT, tmp_path)
    assert "<script" not in page.html.lower()


def test_p9_real_tree_page_has_owner_queue_column(tmp_path):
    # в plans/queue/ORDER.md реального дерева блок owner-queue есть -> колонка на странице
    page = render(REPO_ROOT, tmp_path)
    assert 'id="owner-queue"' in page.html
    assert page.column().tag == "aside"
