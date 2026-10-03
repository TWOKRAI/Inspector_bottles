# ruff: noqa: E501  -- литералы-фикстуры планов и ожидания в одну строку
"""Приёмка Task 3.2 (слепой тестер): чипы зависимостей и сводка «можно начинать» на HTML-странице.

Контракт — plans/2026-10-02_plans-progress-dashboard/tasks/3.2.md (DESIGN + Q1-Q8), реализацию тест не видел.
Всё идёт через CLI (`plans_progress.py --root <фикстура> --html <файл>`; `--json` — только санити фикстуры),
реализация не импортируется. Страницу разбирает собственный `_Page` ниже: `parse_html` из conftest
чипов и `data-ready` не видит.

Одна большая фикстура `matrix` (по плану на каждый случай Q1-Q8), поэтому каждый красный тест сверяет
своё свойство по литеральным словарям; несовпадения собираются списком `problems`, чтобы одно падение
показало все расхождения. Красные тесты — с «якорем существования»: отрицательное утверждение
(«у X нет data-ready / чипа») без положительного соседа на той же странице зелёное и сегодня.

Санити-тесты (зелёные ДО реализации): страница собирается, планы лежат в своих секциях, `--json` даёт
ожидаемые `after`/`waiting_on`/`dep_*` — то есть красный результат значит «нет чипа», а не «сломана фикстура».
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

# .../scripts/plans_progress/tests/<файл> -> корень worktree (как в conftest)
REPO_ROOT = Path(__file__).resolve().parents[3]

READY_TEXT = "можно начинать"
# Новые виды чипов Task 3.2. У страницы уже есть чипы с data-chip другого вида (closed, header-conflict ...) — их не считаем.
NEW_CHIPS = {"ready", "after", "waiting", "cycle"}
ARCH = "2026-10-01_arch"  # архивный план: plans/_archive/2026-Q4/<имя>/plan.md


# --------------------------------------------------------------------------------------
# Разбор страницы: атрибуты <details class="plan">, чипы в <summary>, #ready, позиции
# --------------------------------------------------------------------------------------


class _Chip:
    def __init__(self, tag: str, attrs: dict[str, str | None]) -> None:
        self.tag = tag
        self.attrs = attrs
        self.parts: list[str] = []

    @property
    def text(self) -> str:
        return " ".join("".join(self.parts).split())

    @property
    def classes(self) -> set[str]:
        return set((self.attrs.get("class") or "").split())


class _PlanRec:
    def __init__(self, attrs: dict[str, str | None], section: str | None) -> None:
        self.attrs = attrs
        self.section = section
        self.chips: list[_Chip] = []  # только чипы с data-chip внутри <summary> этого плана
        self.seq: list[tuple[str, str]] = []  # ("tally", "") / ("chip", <data-chip>) в порядке документа


class _Page(HTMLParser):
    SECTION_IDS = {"queue", "waiting", "unlisted", "archive"}
    VOID = {"br", "meta", "link", "img", "input", "hr"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, dict[str, str | None]]] = []
        self.pos = 0
        self.plans: dict[str, _PlanRec] = {}
        self.order: list[str] = []
        self.ready_nodes: list[_Chip] = []  # элементы с id="ready"
        self.ready_pos: list[int] = []
        self.queue_pos: int | None = None
        self.lanes_pos: int | None = None
        self.meta_pos: list[int] = []  # div.meta, кроме #ready
        self.style: list[str] = []
        self._in_style = False
        self._caps: list[tuple[list[str], int]] = []  # (куда писать текст, глубина стека элемента)

    # ---- контекст
    def _ctx(self) -> tuple[str | None, bool]:
        """(data-plan ближайшего плана | None, мы внутри его <summary>)."""
        in_summary = False
        for tag, attrs in reversed(self.stack):
            if tag == "summary":
                in_summary = True
            if tag == "details" and "plan" in (attrs.get("class") or "").split():
                return attrs.get("data-plan") or "", in_summary
        return None, False

    def _section(self) -> str | None:
        for _tag, attrs in reversed(self.stack):
            if attrs.get("id") in self.SECTION_IDS:
                return attrs.get("id")
        return None

    # ---- события
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        self.pos += 1
        if tag == "style":
            self._in_style = True
        if tag in self.VOID:
            return
        classes = set((a.get("class") or "").split())
        if a.get("id") == "queue":
            self.queue_pos = self.pos
        if tag == "section" and "lanes" in classes:
            self.lanes_pos = self.pos
        if tag == "div" and "meta" in classes and a.get("id") != "ready":
            self.meta_pos.append(self.pos)
        plan_name, in_summary = self._ctx()
        caps: list[list[str]] = []
        if a.get("id") == "ready":
            node = _Chip(tag, a)
            self.ready_nodes.append(node)
            self.ready_pos.append(self.pos)
            caps.append(node.parts)
        if tag == "details" and "plan" in classes:
            name = a.get("data-plan") or ""
            self.plans[name] = _PlanRec(a, self._section())
            self.order.append(name)
        elif plan_name is not None and in_summary and tag == "span":
            rec = self.plans[plan_name]
            if "tally" in classes:
                rec.seq.append(("tally", ""))
            if "data-chip" in a:
                chip = _Chip(tag, a)
                rec.chips.append(chip)
                rec.seq.append(("chip", a.get("data-chip") or ""))
                caps.append(chip.parts)
        self.stack.append((tag, a))
        for parts in caps:
            self._caps.append((parts, len(self.stack)))

    def handle_endtag(self, tag):
        if tag == "style":
            self._in_style = False
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break
        self._caps = [(p, d) for p, d in self._caps if d <= len(self.stack)]

    def handle_data(self, data):
        if self._in_style:
            self.style.append(data)
        for parts, _d in self._caps:
            parts.append(data)

    # ---- запросы
    def chips(self, name: str, kind: str) -> list[_Chip]:
        return [c for c in self.plans[name].chips if c.attrs.get("data-chip") == kind]

    def texts(self, name: str, kind: str) -> list[str]:
        return [c.text for c in self.chips(name, kind)]

    def ready_pairs(self) -> list[tuple[str, str | None]]:
        return [(n, self.plans[n].attrs["data-ready"]) for n in self.order if "data-ready" in self.plans[n].attrs]

    def style_text(self) -> str:
        return "".join(self.style)


def _parse(raw: str) -> _Page:
    page = _Page()
    page.feed(raw)
    page.close()
    return page


def _diff(problems: list[str], label: str, got, want) -> None:
    if got != want:
        problems.append(f"{label}: ожидалось {want!r}, на странице {got!r}")


# --------------------------------------------------------------------------------------
# Фикстуры-файлы
# --------------------------------------------------------------------------------------


def _plan(after: str | None = None, tasks: list[str] | None = ("PENDING",), head: str | None = None) -> str:
    """Текст плана: шапка (Статус / После) в первых строках, задачи под `## Порядок выполнения`.

    tasks=None — план без задач (проза).
    """
    lines = ["# P", ""]
    if head:
        lines.append(head)
    if after is not None:
        lines.append(f"- **После:** {after}")
    if head or after is not None:
        lines.append("")
    if tasks is None:
        lines += ["Проза без задач.", ""]
    else:
        lines += ["## Порядок выполнения", ""]
        lines += [f"- Task 1.{i}: x [{s}]" for i, s in enumerate(tasks, 1)]
        lines.append("")
    return "\n".join(lines)


# §4.1 в порядке очереди: (имя, После, задачи, шапка)
_M41: list[tuple[str, str | None, list[str] | None, str | None]] = [
    ("q-free", None, ["PENDING"], None),
    ("q-dep", "z-closed", ["PENDING"], None),
    ("q-blocked", None, ["BLOCKED"], None),
    ("q-prog", None, ["IN_PROGRESS", "DONE"], None),
    ("q-notasks", None, None, None),
    ("q-hw", "⛔ железо", ["PENDING"], None),
    ("q-hw2", "⛔ железо, ⛔ API", ["PENDING"], None),
    ("q-wait", "q-free", ["PENDING"], None),
    ("q-two", "q-prog, q-free", ["PENDING"], None),
    ("q-dedup", "q-free, q-free, [q-free](../q-free/plan.md)", ["PENDING"], None),
    ("q-reason", "q-free — ждёт API", ["PENDING"], None),
    ("q-reason-hw", "q-free, ⛔ железо — ждёт API", ["PENDING"], None),
    ("q-unk", "ghost", ["PENDING"], None),
    ("q-cyc-b", "q-cyc-a, ⛔ железо", ["PENDING"], None),
    ("q-cyc-a", "q-cyc-b", ["PENDING"], None),
    ("q-self", "q-self", ["PENDING"], None),
    ("q-hdr", "q-free, ⛔ железо", ["PENDING"], "- **Статус:** DONE"),
    ("q-alldone", "q-free, ⛔ железо", ["DONE", "DONE"], None),
]
_M42 = [("w-free", None), ("w-dep", "q-free")]
_M43 = [("z-closed", None, ["DONE"]), ("c-43", "q-free, ⛔ железо", ["PENDING"]), ("c-self", "c-self", ["PENDING"])]
_MU = [("u-free", None), ("u-dep", "q-free")]

# план -> секция страницы (санити)
_MATRIX_SECTIONS = (
    {n: "queue" for n, *_ in _M41}
    | {n: "waiting" for n, _ in _M42}
    | {n: "unlisted" for n, _ in _MU}
    | {n: "archive" for n, *_ in _M43}
    | {ARCH: "archive"}
)

# Ожидание: «можно начинать» (в порядке очереди)
_STARTABLE = ["q-free", "q-dep", "q-blocked", "q-prog"]
# Закрытые планы (с После: q-free[, ⛔ железо] и открытой задачей, кроме q-alldone)
_CLOSED = ["c-43", "c-self", ARCH, "q-hdr", "q-alldone"]


def _matrix_files(order_md) -> dict[str, str]:
    files: dict[str, str] = {}
    for n, after, tasks, head in _M41:
        files[f"plans/{n}/plan.md"] = _plan(after, tasks, head)
    for n, after in _M42:
        files[f"plans/{n}/plan.md"] = _plan(after)
    for n, after, tasks in _M43:
        files[f"plans/{n}/plan.md"] = _plan(after, tasks)
    for n, after in _MU:
        files[f"plans/{n}/plan.md"] = _plan(after)
    files[f"plans/_archive/2026-Q4/{ARCH}/plan.md"] = _plan("q-free, ⛔ железо")
    files["plans/queue/ORDER.md"] = order_md(
        tier41=[n for n, *_ in _M41], tier42=[n for n, _ in _M42], tier43=[n for n, *_ in _M43]
    )
    return files


def _build(make_root, progress, tmp_path: Path, files: dict[str, str]) -> tuple[_Page, str, Path]:
    root = make_root(files)
    out = tmp_path / f"{root.name}.html"
    cp = progress(root, "--html", str(out))
    assert cp.returncode == 0, f"--html exit {cp.returncode}\nstderr={cp.stderr[:400]!r}"
    raw = out.read_text(encoding="utf-8")
    return _parse(raw), raw, root


@pytest.fixture
def matrix(make_root, progress, tmp_path, order_md) -> tuple[_Page, str, Path]:
    return _build(make_root, progress, tmp_path, _matrix_files(order_md))


# --------------------------------------------------------------------------------------
# Санити: зелёные до реализации (красное = нет фичи, а не поломка фикстуры / разбора)
# --------------------------------------------------------------------------------------


def test_sanity_parser_reads_chips_ready_and_positions_from_a_known_snippet():
    snippet = (
        "<style>.chip.ok{color:red}</style><main>"
        '<div class="meta">m1</div><div class="meta">m2</div>'
        '<div class="meta" id="ready">можно начинать: a &amp; b</div>'
        '<section class="lanes"></section><section id="queue">'
        '<details class="plan" data-plan="a" data-ready="true"><summary>'
        '<span class="name">a</span><span class="tally">0 из 1</span>'
        '<span class="chip ok" data-chip="ready">можно начинать</span>'
        '<span class="chip warn" data-chip="after" data-unknown="1" title="t &quot;1&quot;">после: <b>g</b></span>'
        '</summary><div class="body"><span data-chip="after">в теле</span></div></details>'
        "</section></main>"
    )
    page = _parse(snippet)
    assert page.order == ["a"]
    assert page.ready_pairs() == [("a", "true")]
    assert [c.attrs.get("data-chip") for c in page.plans["a"].chips] == [
        "ready",
        "after",
    ]  # чип из <div class="body"> не считается
    assert page.texts("a", "after") == ["после: g"]  # вложенный тег внутри чипа входит в текст
    assert page.chips("a", "after")[0].attrs["title"] == 't "1"'
    assert page.chips("a", "ready")[0].classes == {"chip", "ok"}
    assert page.plans["a"].seq == [("tally", ""), ("chip", "ready"), ("chip", "after")]
    assert page.plans["a"].section == "queue"
    assert [" ".join("".join(n.parts).split()) for n in page.ready_nodes] == ["можно начинать: a & b"]
    assert max(page.meta_pos) < page.ready_pos[0] < page.lanes_pos < page.queue_pos
    assert page.style_text() == ".chip.ok{color:red}"


def test_sanity_parser_does_not_see_data_ready_or_chips_on_a_plain_page():
    plain = (
        '<section id="queue"><details class="plan" data-plan="p"><summary>'
        '<span class="name">p</span><span class="chip">старый</span></summary></details></section>'
    )
    page = _parse(plain)
    assert page.order == ["p"] and page.ready_pairs() == [] and page.plans["p"].chips == []
    assert page.ready_nodes == []


def test_sanity_matrix_page_builds_and_every_plan_sits_in_its_section(matrix):
    page, _raw, _root = matrix
    assert {n: page.plans[n].section for n in page.order} == _MATRIX_SECTIONS
    assert len(page.order) == len(_MATRIX_SECTIONS)
    # очередь в порядке ORDER.md
    assert [n for n in page.order if page.plans[n].section == "queue"] == [n for n, *_ in _M41]


def test_sanity_matrix_json_confirms_what_the_fixture_means(make_root, plans_json, order_md):
    recs = plans_json(make_root(_matrix_files(order_md)))
    assert recs["q-two"]["after"] == ["q-prog", "q-free"]
    assert recs["q-dedup"]["after"] == ["q-free"]
    assert recs["q-hw"]["waiting_on"] == ["железо"]
    assert recs["q-hw2"]["waiting_on"] == ["железо", "API"]
    assert recs["q-reason"]["after_reason"] == "ждёт API"
    assert (recs["q-reason-hw"]["after"], recs["q-reason-hw"]["waiting_on"], recs["q-reason-hw"]["after_reason"]) == (
        ["q-free"],
        ["железо"],
        "ждёт API",
    )
    assert recs["q-unk"]["dep_unknown"] == ["ghost"]
    assert recs["q-cyc-a"]["dep_cycle"] == recs["q-cyc-b"]["dep_cycle"] == ["q-cyc-a", "q-cyc-b"]
    assert recs["q-self"]["dep_cycle"] == ["q-self"]
    assert recs["q-hdr"]["header_status"] == "done"
    assert recs[ARCH]["archived"] is True
    assert {n: recs[n]["tier"] for n in ("q-free", "w-dep", "z-closed", "u-dep", ARCH)} == {
        "q-free": "4.1",
        "w-dep": "4.2",
        "z-closed": "4.3",
        "u-dep": None,
        ARCH: None,
    }
    # данные 3.1: «готов» у стартующих и нет у ждущих
    assert all(recs[n]["ready"] is True for n in _STARTABLE)
    assert all(recs[n]["ready"] is False for n in ("q-wait", "q-two", "q-hw", "q-unk", "q-self", "q-cyc-a"))


def test_sanity_matrix_page_has_no_scripts_or_external_references(matrix):
    _page, raw, _root = matrix
    low = raw.lower()
    assert "<script" not in low and "http://" not in low and "https://" not in low


def test_sanity_real_tree_page_builds_with_exit_zero(progress, tmp_path):
    out = tmp_path / "real.html"
    cp = progress(REPO_ROOT, "--html", str(out))
    assert cp.returncode == 0, cp.stderr[:400]
    page = _parse(out.read_text(encoding="utf-8"))
    assert page.order, "на реальной странице нет ни одного плана"


# --------------------------------------------------------------------------------------
# RED: поведение страницы Task 3.2
# --------------------------------------------------------------------------------------


def test_after_chip_per_unclosed_plan_and_name_in_written_order_with_reason_as_title(matrix):
    """Q1 + Q2 + Q7: чип `after` — по одному на пару (незакрытый план, имя), порядок записи, дубли схлопнуты,
    §4.2 и вне ORDER.md тоже; у закрытых чипов нет; `title` = after_reason, без причины title нет."""
    page, _raw, _root = matrix
    want: dict[str, list[str]] = {n: [] for n in page.order}
    want.update(
        {
            "q-dep": ["после: z-closed"],
            "q-wait": ["после: q-free"],
            "q-two": ["после: q-prog", "после: q-free"],  # порядок записи, не очереди и не алфавита
            "q-dedup": ["после: q-free"],  # `q-free, q-free, [q-free](...)` -> один
            "q-reason": ["после: q-free"],
            "q-reason-hw": ["после: q-free"],
            "q-unk": ["после: ghost"],
            "q-cyc-b": ["после: q-cyc-a"],
            "q-cyc-a": ["после: q-cyc-b"],
            "q-self": ["после: q-self"],
            "w-dep": ["после: q-free"],  # §4.2
            "u-dep": ["после: q-free"],  # вне ORDER.md
        }
    )
    problems: list[str] = []
    got = {n: page.texts(n, "after") for n in page.order}
    for n in page.order:
        _diff(problems, f"чипы after у {n}", got[n], want[n])
    _diff(problems, "всего чипов after (пары незакрытый план-имя)", sum(map(len, got.values())), 13)
    for n in ("q-reason", "q-reason-hw"):
        chips = page.chips(n, "after")
        _diff(problems, f"title чипа after у {n}", [c.attrs.get("title") for c in chips], ["ждёт API"])
    chips = page.chips("q-wait", "after")
    _diff(problems, "атрибут title у чипа after без причины", ["title" in c.attrs for c in chips], [False])
    _diff(problems, "тег чипа after у q-wait", [c.tag for c in chips], ["span"])
    assert not problems, "\n".join(problems)


def test_waiting_chip_per_condition_in_written_order_with_reason_as_title(matrix):
    """Q2 + DESIGN: `⛔ условие` -> чип `waiting` с текстом `ждёт: <условие>`, по одному на условие;
    title = after_reason; у закрытых чипов нет."""
    page, _raw, _root = matrix
    want: dict[str, list[str]] = {n: [] for n in page.order}
    want.update(
        {
            "q-hw": ["ждёт: железо"],
            "q-hw2": ["ждёт: железо", "ждёт: API"],
            "q-reason-hw": ["ждёт: железо"],
            "q-cyc-b": ["ждёт: железо"],
        }
    )
    problems: list[str] = []
    for n in page.order:
        _diff(problems, f"чипы waiting у {n}", page.texts(n, "waiting"), want[n])
    _diff(
        problems,
        "title чипа waiting у q-reason-hw",
        [c.attrs.get("title") for c in page.chips("q-reason-hw", "waiting")],
        ["ждёт API"],
    )
    _diff(
        problems,
        "атрибут title у чипа waiting без причины (q-hw)",
        ["title" in c.attrs for c in page.chips("q-hw", "waiting")],
        [False],
    )
    assert not problems, "\n".join(problems)


def test_data_ready_exactly_on_queue_plans_with_open_task_and_ready(matrix):
    """Q3 (+ Q1: B после открытого A не готов): data-ready="true" ровно у q-free, q-dep (После: закрытый),
    q-blocked (одни BLOCKED), q-prog; нет у: все DONE, без задач, §4.2, вне ORDER.md, архив, §4.3,
    ⛔, После: открытый, неизвестное имя, цикл."""
    page, _raw, _root = matrix
    got = page.ready_pairs()
    want = [(n, "true") for n in _STARTABLE]
    assert got == want, f"data-ready: ожидалось {want!r} (в порядке очереди), на странице {got!r}"


def test_ready_chip_text_class_count_order_and_css(matrix):
    """Q3 + DESIGN: чип `можно начинать` (span.chip.ok, data-chip=ready) — ровно у data-ready-планов, по одному;
    в <summary> идёт первым среди чипов и после .tally; CSS `.chip.ok{color:var(--done);border-color:var(--done)}`."""
    page, _raw, _root = matrix
    problems: list[str] = []
    with_chip = [n for n in page.order if page.chips(n, "ready")]
    _diff(problems, "планы с чипом ready (порядок страницы)", with_chip, _STARTABLE)
    _diff(
        problems,
        "число чипов ready == число [data-ready]",
        sum(len(page.chips(n, "ready")) for n in page.order),
        len(page.ready_pairs()),
    )
    for n in _STARTABLE:
        chips = page.chips(n, "ready")
        _diff(problems, f"текст чипа ready у {n}", [c.text for c in chips], [READY_TEXT])
        _diff(problems, f"классы чипа ready у {n}", [c.classes for c in chips], [{"chip", "ok"}])
        _diff(problems, f"тег чипа ready у {n}", [c.tag for c in chips], ["span"])
    seq = [(t, k) for t, k in page.plans["q-dep"].seq if t == "tally" or k in NEW_CHIPS]
    _diff(
        problems,
        "порядок в <summary> q-dep: .tally, затем чипы ready, after",
        seq[-3:],
        [("tally", ""), ("chip", "ready"), ("chip", "after")],
    )
    css = re.sub(r"\s+", "", page.style_text())
    if ".chip.ok{color:var(--done);border-color:var(--done)}" not in css:
        problems.append("в <style> нет правила `.chip.ok{color:var(--done);border-color:var(--done)}`")
    assert not problems, "\n".join(problems)


def test_ready_summary_text_and_placement_before_queue(matrix):
    """Q4: `<div class="meta" id="ready">можно начинать: <имена data-ready-планов в порядке очереди через ', '></div>`;
    стоит после двух строк .meta, до `<section class="lanes">` и до #queue."""
    page, _raw, _root = matrix
    problems: list[str] = []
    _diff(problems, "число элементов #ready", len(page.ready_nodes), 1)
    if page.ready_nodes:
        node = page.ready_nodes[0]
        _diff(problems, "текст #ready", node.text, "можно начинать: q-free, q-dep, q-blocked, q-prog")
        _diff(problems, "тег #ready", node.tag, "div")
        _diff(problems, "классы #ready содержат meta", "meta" in node.classes, True)
        pos = page.ready_pos[0]
        _diff(problems, "две строки .meta до #ready", len(page.meta_pos), 2)
        if page.meta_pos and not pos > max(page.meta_pos):
            problems.append(f"#ready (поз. {pos}) должен идти после строк .meta (поз. {page.meta_pos})")
        if page.lanes_pos is not None and not pos < page.lanes_pos:
            problems.append(f"#ready (поз. {pos}) должен идти до <section class=lanes> (поз. {page.lanes_pos})")
        if page.queue_pos is not None and not pos < page.queue_pos:
            problems.append(f"#ready (поз. {pos}) должен идти до #queue (поз. {page.queue_pos})")
    assert not problems, "\n".join(problems)


def test_ready_summary_text_for_zero_and_for_single_startable_plan(make_root, progress, tmp_path, order_md):
    """Q4: при нуле планов (поле в дереве есть) `можно начинать: нет`; при одном — имя без запятой."""
    zero = {
        "plans/z-done/plan.md": _plan(None, ["DONE"]),  # §4.1, всё закрыто
        "plans/z-wait/plan.md": _plan("z-done"),  # §4.2, открыт; поле в дереве есть (иначе «не определено», Q9)
        "plans/z-free/plan.md": _plan(None),  # вне ORDER.md
        "plans/queue/ORDER.md": order_md(tier41=["z-done"], tier42=["z-wait"]),
    }
    single = {
        "plans/s-one/plan.md": _plan(None),
        "plans/s-after/plan.md": _plan("s-one"),
        "plans/queue/ORDER.md": order_md(tier41=["s-one", "s-after"]),
    }
    problems: list[str] = []
    for label, files, want_text, want_ready in (
        ("ноль", zero, "можно начинать: нет", []),
        ("один", single, "можно начинать: s-one", [("s-one", "true")]),
    ):
        page, _raw, _root = _build(make_root, progress, tmp_path, files)
        _diff(
            problems,
            f"[{label}] планы страницы",
            sorted(page.order),
            sorted(n.split("/")[1] for n in files if n.endswith("plan.md")),
        )
        _diff(problems, f"[{label}] data-ready", page.ready_pairs(), want_ready)
        _diff(
            problems,
            f"[{label}] тексты #ready",
            [" ".join("".join(n.parts).split()) for n in page.ready_nodes],
            [want_text],
        )
    assert not problems, "\n".join(problems)


def _q9_files(order_md, *, archived_field: bool = False, live_field: str | None = None) -> dict[str, str]:
    """База Q9: два плана §4.1 (PENDING и BLOCKED), один §4.2, один вне ORDER.md; поля нет ни у кого.

    archived_field — поле `После:` только у архивного плана; live_field — куда добавить поле у НЕархивного
    плана: "4.2" (поле у w-wait), "unlisted" (у u-free), "4.1" (у нового §4.1-плана u-three).
    """
    files = {
        "plans/u-one/plan.md": _plan(None, ["PENDING"]),
        "plans/u-two/plan.md": _plan(None, ["BLOCKED"]),
        "plans/w-wait/plan.md": _plan("u-one" if live_field == "4.2" else None),
        "plans/u-free/plan.md": _plan("u-one" if live_field == "unlisted" else None),
    }
    tier41 = ["u-one", "u-two"]
    if live_field == "4.1":
        files["plans/u-three/plan.md"] = _plan("u-one")
        tier41.append("u-three")
    if archived_field:
        files[f"plans/_archive/2026-Q4/{ARCH}/plan.md"] = _plan("u-one")
    files["plans/queue/ORDER.md"] = order_md(tier41=tier41, tier42=["w-wait"])
    return files


def test_ready_is_undefined_until_a_live_plan_has_the_field(make_root, progress, tmp_path, order_md):
    """Q9: пока ни у одного НЕархивного плана нет `После:` (поле только у архивного не считается) — нет data-ready,
    нет чипов ready, `#ready` = `можно начинать: не определено (...)`; поле у любого живого плана (§4.2, вне ORDER.md,
    §4.1) возвращает поведение Q3/Q4: u-one и u-two (одни BLOCKED) снова data-ready."""
    undefined = "можно начинать: не определено (поле «После:» не заполнено ни у одного плана)"
    scenarios = (
        ("поля нет нигде", dict(), [], undefined),
        ("поле только у архивного плана", dict(archived_field=True), [], undefined),
        (
            "поле у плана §4.2",
            dict(live_field="4.2"),
            [("u-one", "true"), ("u-two", "true")],
            "можно начинать: u-one, u-two",
        ),
        (
            "поле у плана вне ORDER.md",
            dict(live_field="unlisted"),
            [("u-one", "true"), ("u-two", "true")],
            "можно начинать: u-one, u-two",
        ),
        (
            "поле у плана §4.1",
            dict(live_field="4.1"),
            [("u-one", "true"), ("u-two", "true")],
            "можно начинать: u-one, u-two",
        ),
    )
    problems: list[str] = []
    for label, kw, want_ready, want_text in scenarios:
        page, _raw, _root = _build(make_root, progress, tmp_path, _q9_files(order_md, **kw))
        _diff(problems, f"[{label}] data-ready", page.ready_pairs(), want_ready)
        _diff(
            problems,
            f"[{label}] планы с чипом ready",
            [n for n in page.order if page.chips(n, "ready")],
            [n for n, _v in want_ready],
        )
        _diff(problems, f"[{label}] тексты #ready", [n.text for n in page.ready_nodes], [want_text])
    assert not problems, "\n".join(problems)


def test_warn_chips_for_unknown_name_and_cycle_with_chip_order(matrix):
    """Q5: неизвестное имя -> чип after `chip warn` + data-unknown="1" (у известного ни того, ни другого);
    цикл A<->B -> у каждого один `⚠ цикл: A, B` (порядок по имени плана, не очереди); самоссылка -> `⚠ цикл: A`;
    порядок чипов в <summary>: after, waiting, cycle."""
    page, _raw, _root = matrix
    problems: list[str] = []
    unk = page.chips("q-unk", "after")
    _diff(problems, "q-unk: классы чипа after", [c.classes for c in unk], [{"chip", "warn"}])
    _diff(problems, "q-unk: data-unknown", [c.attrs.get("data-unknown") for c in unk], ["1"])
    known = page.chips("q-wait", "after")
    _diff(problems, "q-wait (известное имя): data-unknown есть", ["data-unknown" in c.attrs for c in known], [False])
    _diff(problems, "q-wait (известное имя): класс warn", ["warn" in c.classes for c in known], [False])
    want_cycle = {n: [] for n in page.order}
    want_cycle.update(
        {
            "q-cyc-b": ["⚠ цикл: q-cyc-a, q-cyc-b"],  # в очереди b стоит раньше a
            "q-cyc-a": ["⚠ цикл: q-cyc-a, q-cyc-b"],
            "q-self": ["⚠ цикл: q-self"],
        }
    )
    for n in page.order:
        _diff(problems, f"чипы cycle у {n}", page.texts(n, "cycle"), want_cycle[n])
    for n in ("q-cyc-a", "q-cyc-b", "q-self"):
        _diff(problems, f"классы чипа cycle у {n}", [c.classes for c in page.chips(n, "cycle")], [{"chip", "warn"}])
    chip_kinds = lambda n: [kind for typ, kind in page.plans[n].seq if typ == "chip" and kind in NEW_CHIPS]  # noqa: E731
    _diff(problems, "порядок чипов q-cyc-b", chip_kinds("q-cyc-b"), ["after", "waiting", "cycle"])
    _diff(problems, "порядок чипов q-cyc-a", chip_kinds("q-cyc-a"), ["after", "cycle"])
    assert not problems, "\n".join(problems)


def test_closed_plans_get_no_dependency_chips_and_no_ready(matrix):
    """Q6: закрытый план (§4.3, архив, §4.1 с `Статус: DONE` и открытой задачей, §4.1 все DONE, плюс самоссылка
    в §4.3) с `После: q-free[, ⛔ железо]` — ни одного чипа after/waiting/cycle/ready, нет data-ready.
    Якорь: открытый q-wait с тем же `После` чип after имеет (иначе тест зелёный и без фичи)."""
    page, _raw, _root = matrix
    assert page.texts("q-wait", "after") == ["после: q-free"], "якорь: у открытого плана нет чипа after — фичи нет"
    assert page.texts("q-hw", "waiting") == ["ждёт: железо"], "якорь: у открытого плана нет чипа waiting — фичи нет"
    problems: list[str] = []
    for n in _CLOSED:
        assert n in page.plans, f"закрытый план {n} пропал со страницы"
        kinds = [k for typ, k in page.plans[n].seq if typ == "chip" and k in NEW_CHIPS]
        _diff(problems, f"чипы закрытого плана {n} (виды after/waiting/cycle/ready)", kinds, [])
        _diff(problems, f"data-ready у закрытого плана {n}", "data-ready" in page.plans[n].attrs, False)
    assert not problems, "\n".join(problems)


def test_chip_text_and_title_are_html_escaped_and_page_stays_script_free(make_root, progress, tmp_path, order_md):
    """Q8: условие `⛔ <script>&` не создаёт тега script, текст чипа `ждёт: <script>&` в виде сущностей;
    причина с кавычками и тегом (`ждёт "API" <b>x`) не ломает атрибут title; на странице нет `<script`, `http://`, `https://`."""
    files = {
        "plans/e-free/plan.md": _plan(None),
        "plans/e-esc/plan.md": _plan("⛔ <script>&"),
        "plans/e-title/plan.md": _plan('e-free — ждёт "API" <b>x'),
        "plans/queue/ORDER.md": order_md(tier41=["e-free", "e-esc", "e-title"]),
    }
    page, raw, root = _build(make_root, progress, tmp_path, files)
    problems: list[str] = []
    _diff(problems, "чипы waiting у e-esc (раскодированный текст)", page.texts("e-esc", "waiting"), ["ждёт: <script>&"])
    if "ждёт: &lt;script&gt;&amp;" not in raw:
        problems.append("в исходнике страницы нет `ждёт: &lt;script&gt;&amp;` (текст чипа должен быть сущностями)")
    low = raw.lower()
    for bad in ("<script", "http://", "https://", "<b>x"):
        if bad in low:
            problems.append(f"в исходнике страницы есть {bad!r}")
    _diff(
        problems,
        "title чипа after у e-title",
        [c.attrs.get("title") for c in page.chips("e-title", "after")],
        ['ждёт "API" <b>x'],
    )
    _diff(problems, "e-title: текст чипа after", page.texts("e-title", "after"), ["после: e-free"])
    assert not problems, "\n".join(problems)


def test_real_tree_page_has_ready_summary_and_only_queue_plans_are_startable(progress, tmp_path):
    """Q8: на реальном дереве `--html` exit 0, `#ready` есть, ни у одного плана §4.2 нет data-ready
    (и data-ready вообще только у планов §4.1)."""
    out = tmp_path / "real.html"
    cp = progress(REPO_ROOT, "--html", str(out))
    assert cp.returncode == 0, f"--html exit {cp.returncode}: {cp.stderr[:400]!r}"
    page = _parse(out.read_text(encoding="utf-8"))
    problems: list[str] = []
    _diff(problems, "число элементов #ready", len(page.ready_nodes), 1)
    if page.ready_nodes:
        text = page.ready_nodes[0].text
        if not text.startswith("можно начинать: "):
            problems.append(f"текст #ready не начинается с 'можно начинать: ': {text!r}")
    tier42 = [n for n in page.order if page.plans[n].attrs.get("data-tier") == "4.2"]
    assert tier42, "якорь: на реальной странице нет планов §4.2 (data-tier=4.2) — проверять нечего"
    _diff(problems, "планы §4.2 с data-ready", [n for n in tier42 if "data-ready" in page.plans[n].attrs], [])
    not_queue = [n for n, _v in page.ready_pairs() if page.plans[n].attrs.get("data-tier") != "4.1"]
    _diff(problems, "data-ready у планов не из §4.1", not_queue, [])
    assert not problems, "\n".join(problems)
