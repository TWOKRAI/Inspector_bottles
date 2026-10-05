# ruff: noqa: E501  -- литералы-фикстуры и ожидания в одну строку, форматтер их не переносит
"""Приёмка Task 7.1 — слепые тесты вкладок, якорей страницы плана и переключателя планов.

Источник: plans/2026-10-02_plans-progress-dashboard/tasks/7.1.md (DESIGN + ACCEPTANCE 1-11).
Реализацию страницы тестер не видел (RED до кода); читал только спек, conftest и вид прежней страницы.

Только CLI в subprocess (`progress(root, "--html"|"--json", ...)` из conftest, timeout=60 на вызов):
зависнуть тесту нечему, поэтому поток-демон с join-дедлайном не нужен.
Страницу разбирает свой HTML-парсер со стеком (дерево узлов): вложенные `<details>` не ломают поиск.

Фикстура (спек, ACCEPTANCE): §4.1 `2026-01-01_a`, `2026-01-02_b`; §4.2 `2026-01-03_w`; §4.3 `2026-01-06_c`;
вне ORDER `2026-01-04_u`; архив `_archive/2026-Q1/2026-01-01_a` (имя как у живого) и `2026-01-05_z`;
«Снимок» из двух строк (слаги `a`, `b`). Карточек 7: a, b, w, u, c, a(архив), z — в порядке страницы.
Все строки §4.1 из `order_md` имеют полосу «С», w и u — без полосы: «Полосы · 2» (С и «без полосы»).

Ожидаемые значения — литералы из спека, не пересчёт кодом.
Охранные тесты (зелёные до кода): пункт 1, пункт 8 (CSS сейчас ~2.9 КБ без внешних ссылок), пункт 9
(golden), «прежняя разметка не меняется». Пункт 10 (прежний набор) — не тест, а прогон лида.
"""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

GOLDEN = Path(__file__).resolve().parent / "fixtures" / "page_nav.json.golden"

# ---- литералы спека ------------------------------------------------------------------------------------
# Якоря карточек в порядке страницы (ACCEPTANCE 2): a, b | w | u | c, a(архив), z.
ANCHORS = [
    "plan-2026-01-01_a",
    "plan-2026-01-02_b",
    "plan-2026-01-03_w",
    "plan-2026-01-04_u",
    "plan-2026-01-06_c",
    "plan-2026-01-01_a-archive",
    "plan-2026-01-05_z",
]
# Пути планов в порядке карточек страницы (ACCEPTANCE 11: «план — по path»).
PATHS = [
    "plans/2026-01-01_a/plan.md",
    "plans/2026-01-02_b/plan.md",
    "plans/2026-01-03_w/plan.md",
    "plans/2026-01-04_u/plan.md",
    "plans/2026-01-06_c/plan.md",
    "plans/_archive/2026-Q1/2026-01-01_a/plan.md",
    "plans/_archive/2026-Q1/2026-01-05_z/plan.md",
]
NAMES = ["2026-01-01_a", "2026-01-02_b", "2026-01-03_w", "2026-01-04_u", "2026-01-06_c", "2026-01-01_a", "2026-01-05_z"]
# N в «Задачи · N» по карточкам (ACCEPTANCE 7); None — у карточки без задач нет details.tasklist.
TASK_COUNTS = [3, 1, None, 2, 1, 2, None]
# ACCEPTANCE 4: порядок радиокнопок и метки.
TAB_IDS = ["tab-queue", "tab-waiting", "tab-unlisted", "tab-archive", "tab-who", "tab-priority", "tab-lanes"]
TAB_LABELS = {
    "tab-queue": "Очередь · 2",
    "tab-waiting": "Ждут · 1",
    "tab-unlisted": "Нет в ORDER · 1",
    "tab-archive": "Архив · 3",
    "tab-who": "Кто где · 0",
    "tab-priority": "Приоритеты · 2",
    "tab-lanes": "Полосы · 2",
}
# DESIGN «Переключатель»: группы по порядку и ссылки в них (по карточкам: a,b | w | u | c,a-арх,z).
SWITCHER_GROUPS = [
    ("Очередь", ["#plan-2026-01-01_a", "#plan-2026-01-02_b"]),
    ("Ждут", ["#plan-2026-01-03_w"]),
    ("Нет в ORDER", ["#plan-2026-01-04_u"]),
    ("Архив", ["#plan-2026-01-06_c", "#plan-2026-01-01_a-archive", "#plan-2026-01-05_z"]),
]
# DESIGN: текст <small> — как у .tally карточки без хвоста; у плана без задач `0 из 0`.
SWITCHER_SMALL = ["1 из 3 · 33%", "0 из 1 · 0%", "0 из 0", "1 из 2 · 50%", "1 из 1 · 100%", "2 из 2 · 100%", "0 из 0"]
# Коллизия (ACCEPTANCE 2/11): живые x-y и x.y вне ORDER, на странице x-y выше.
COLLISION_PATHS = ["plans/2026-01-07_x-y/plan.md", "plans/2026-01-07_x.y/plan.md"]
COLLISION_ANCHORS = ["plan-2026-01-07_x-y", "plan-2026-01-07_x-y-2"]

SNAPSHOT = (
    "## Снимок 2026-01-10 — где мы сейчас\n\n"
    "| # | Полоса | План | Следующий шаг | Чего ждёт |\n"
    "|---|---|---|---|---|\n"
    "| 1 | С | a | шаг А | ничего |\n"
    "| 2 | С | b | шаг Б | ничего |\n\n"
)


# =========================================================================== фикстуры файлов


def _plan_md(*statuses: str) -> str:
    """План с задачами 1.1..1.k в эталонном формате; без статусов — план без задач."""
    text = "# План\n"
    if statuses:
        text += "\n## Порядок выполнения\n\n" + "".join(
            f"- Task 1.{i}: x{i} [{s}]\n" for i, s in enumerate(statuses, 1)
        )
    return text


def main_files(order_md, *, unlisted: bool = True, snapshot: bool = True) -> dict[str, str]:
    order = order_md(
        tier41=["2026-01-01_a", "2026-01-02_b"],
        tier42=["2026-01-03_w"],
        tier43=["2026-01-06_c"],
    )
    if snapshot:
        marker = "## 4. Контроль планов"
        assert marker in order
        order = order.replace(marker, SNAPSHOT + marker, 1)
    files = {
        "plans/queue/ORDER.md": order,
        "plans/2026-01-01_a/plan.md": _plan_md("DONE", "PENDING", "PENDING"),
        "plans/2026-01-02_b/plan.md": _plan_md("PENDING"),
        "plans/2026-01-03_w/plan.md": _plan_md(),
        "plans/2026-01-06_c/plan.md": _plan_md("DONE"),
        "plans/_archive/2026-Q1/2026-01-01_a/plan.md": _plan_md("DONE", "DONE"),
        "plans/_archive/2026-Q1/2026-01-05_z/plan.md": _plan_md(),
    }
    if unlisted:
        files["plans/2026-01-04_u/plan.md"] = _plan_md("PENDING", "DONE")
    return files


def collision_files(order_md) -> dict[str, str]:
    return {
        "plans/queue/ORDER.md": order_md(),
        "plans/2026-01-07_x-y/plan.md": _plan_md("DONE"),
        "plans/2026-01-07_x.y/plan.md": _plan_md("PENDING"),
    }


# =========================================================================== разбор страницы (дерево со стеком)

VOID = {"br", "meta", "link", "img", "input", "hr", "area", "base", "col", "embed", "source", "track", "wbr"}


class Node:
    def __init__(self, tag: str, attrs: dict[str, str | None], parent: Node | None) -> None:
        self.tag = tag
        self.attrs = attrs
        self.parent = parent
        self.children: list[Node | str] = []

    def classes(self) -> set[str]:
        return set((self.attrs.get("class") or "").split())

    def elems(self) -> list[Node]:
        return [c for c in self.children if isinstance(c, Node)]

    def walk(self):
        yield self
        for c in self.elems():
            yield from c.walk()

    def text(self) -> str:
        parts: list[str] = []

        def rec(n: Node) -> None:
            for c in n.children:
                if isinstance(c, str):
                    parts.append(c)
                else:
                    rec(c)

        rec(self)
        return " ".join(" ".join(parts).split())

    def find_all(self, tag: str | None = None, cls: str | None = None) -> list[Node]:
        return [
            n
            for n in self.walk()
            if n is not self and (tag is None or n.tag == tag) and (cls is None or cls in n.classes())
        ]

    def ancestors(self):
        n = self.parent
        while n is not None:
            yield n
            n = n.parent


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


def parse(html: str) -> Node:
    b = _TreeBuilder()
    b.feed(html)
    b.close()
    return b.root


def cards(doc: Node) -> list[Node]:
    return doc.find_all("details", "plan")


def anchor_spans(card: Node) -> list[Node]:
    return [n for n in card.find_all("span") if "anchor" in n.classes()]


class Page:
    def __init__(self, html: str) -> None:
        self.html = html
        self.doc = parse(html)


@pytest.fixture
def render(make_root, progress, tmp_path):
    """render(files) -> (root, Page); страница пишется `--html <tmp>/page.html`, exit 0 обязателен."""
    counter = {"n": 0}

    def _render(files: dict[str, str]):
        counter["n"] += 1
        root = make_root(files)
        out = tmp_path / f"page{counter['n']}.html"
        cp = progress(root, "--html", str(out))
        assert cp.returncode == 0, (
            f"--html exit {cp.returncode}\nstdout={cp.stdout[:400]!r}\nstderr={cp.stderr[:400]!r}"
        )
        assert out.is_file(), "--html не создал файл"
        return root, Page(out.read_text(encoding="utf-8"))

    return _render


@pytest.fixture
def page(render, order_md) -> Page:
    return render(main_files(order_md))[1]


@pytest.fixture
def page_no_unlisted(render, order_md) -> Page:
    return render(main_files(order_md, unlisted=False))[1]


@pytest.fixture
def page_no_snapshot(render, order_md) -> Page:
    return render(main_files(order_md, snapshot=False))[1]


@pytest.fixture
def page_collision(render, order_md) -> Page:
    return render(collision_files(order_md))[1]


def _json_of(progress, root: Path) -> tuple[str, list[dict]]:
    cp = progress(root, "--json")
    assert cp.returncode == 0, f"--json exit {cp.returncode}\nstderr={cp.stderr[:400]!r}"
    data = json.loads(cp.stdout)
    assert isinstance(data, list)
    return cp.stdout, data


# =========================================================================== 1. охранный: страница без JS


@pytest.mark.parametrize("variant", ["main", "collision"])
def test_n1_no_script_no_on_attrs_no_javascript_url(variant, page, page_collision):
    pg = page if variant == "main" else page_collision
    assert len(cards(pg.doc)) == (7 if variant == "main" else 2), "страница не построена: нет ожидаемых карточек"
    low = pg.html.lower()
    assert "<script" not in low
    assert "javascript:" not in low
    on_attrs = [(n.tag, k) for n in pg.doc.walk() for k in n.attrs if k.lower().startswith("on")]
    assert on_attrs == [], f"атрибуты on*: {on_attrs}"


# =========================================================================== 2. якоря карточек


def test_n2_anchor_ids_in_card_order(page):
    spans = [n for n in page.doc.find_all("span") if "anchor" in n.classes()]
    assert [s.attrs.get("id") for s in spans] == ANCHORS


def test_n2_each_card_has_exactly_one_empty_anchor_right_after_summary(page):
    cs = cards(page.doc)
    assert len(cs) == 7
    for i, card in enumerate(cs):
        kids = card.elems()
        assert [k.tag for k in kids[:3]] == ["summary", "span", "div"], f"карточка {i}: порядок {[k.tag for k in kids]}"
        anchor, body = kids[1], kids[2]
        assert "anchor" in anchor.classes(), f"карточка {i}: после summary не span.anchor"
        assert anchor.children == [], f"карточка {i}: span.anchor не пуст: {anchor.children!r}"
        assert "body" in body.classes(), f"карточка {i}: после якоря не div.body"
        assert len(anchor_spans(card)) == 1, f"карточка {i}: span.anchor не один"


def test_n2_all_page_ids_unique(page):
    ids = [n.attrs["id"] for n in page.doc.walk() if n.attrs.get("id")]
    assert len(ids) > 7, f"ids страницы подозрительно мало: {ids}"
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    assert dupes == [], f"повторяются id: {dupes}"


def test_n2_plan_details_have_no_id_attribute(page):
    cs = cards(page.doc)
    assert len(cs) == 7
    assert [c.attrs.get("id") for c in cs] == [None] * 7
    assert all("id" not in c.attrs for c in cs)


def test_n2_collision_suffix_goes_to_the_second_card(page_collision):
    cs = cards(page_collision.doc)
    assert [c.find_all("span", "name")[0].text() for c in cs] == ["2026-01-07_x-y", "2026-01-07_x.y"]
    assert [anchor_spans(c)[0].attrs.get("id") if anchor_spans(c) else None for c in cs] == COLLISION_ANCHORS


# =========================================================================== 3. ссылка на страницу плана


def test_n3_plan_link_follows_name_and_points_at_own_anchor(page):
    cs = cards(page.doc)
    assert len(cs) == 7
    for i, card in enumerate(cs):
        summary = card.elems()[0]
        assert summary.tag == "summary"
        kids = summary.elems()
        idx = next((j for j, k in enumerate(kids) if k.tag == "span" and "name" in k.classes()), None)
        assert idx is not None, f"карточка {i}: нет span.name в summary"
        nxt = kids[idx + 1] if idx + 1 < len(kids) else None
        assert nxt is not None and nxt.tag == "a" and "plan-link" in nxt.classes(), (
            f"карточка {i}: сразу после span.name не a.plan-link ({[(k.tag, sorted(k.classes())) for k in kids]})"
        )
        assert nxt.attrs.get("href") == "#" + ANCHORS[i], f"карточка {i}: href {nxt.attrs.get('href')!r}"


def test_n3_plan_link_label_and_title_literals(page):
    links = page.doc.find_all("a", "plan-link")
    assert len(links) == 7
    assert [lk.text() for lk in links] == ["↗"] * 7
    assert [lk.attrs.get("title") for lk in links] == ["страница плана"] * 7


# =========================================================================== 4. вкладки


def _tabs(doc: Node) -> Node:
    navs = [n for n in doc.find_all("nav") if "tabs" in n.classes()]
    assert len(navs) == 1, f"nav.tabs: {len(navs)}"
    return navs[0]


def _radio_ids(doc: Node) -> list[str]:
    nav = _tabs(doc)
    radios = [n for n in nav.find_all("input") if n.attrs.get("type") == "radio"]
    assert all(r.attrs.get("name") == "tab" for r in radios), "у радиокнопок вкладок name != 'tab'"
    return [r.attrs.get("id") for r in radios]


def test_n4_radio_order(page):
    assert _radio_ids(page.doc) == TAB_IDS


def test_n4_only_queue_is_checked(page):
    nav = _tabs(page.doc)
    radios = [n for n in nav.find_all("input") if n.attrs.get("type") == "radio"]
    assert len(radios) == len(TAB_IDS)
    assert [r.attrs.get("id") for r in radios if "checked" in r.attrs] == ["tab-queue"]


def test_n4_labels_literal(page):
    nav = _tabs(page.doc)
    labels = {lb.attrs.get("for"): lb.text() for lb in nav.find_all("label")}
    assert labels == TAB_LABELS


def test_n4_tabs_nav_lives_in_topbar_header(page):
    headers = [h for h in page.doc.find_all("header") if "topbar" in h.classes()]
    assert len(headers) == 1
    assert len(headers[0].find_all("nav", "tabs")) == 1


def test_n4_overlaps_tab_absent_on_fixture(page):
    ids = _radio_ids(page.doc)
    assert ids == TAB_IDS, "вкладки ещё не построены"
    assert "tab-overlaps" not in ids


def test_n4_without_unlisted_plan_no_unlisted_tab(page_no_unlisted):
    ids = _radio_ids(page_no_unlisted.doc)
    assert ids == [t for t in TAB_IDS if t != "tab-unlisted"]


def test_n4_without_snapshot_rows_no_priority_tab_but_section_stays(page_no_snapshot):
    ids = _radio_ids(page_no_snapshot.doc)
    assert ids == [t for t in TAB_IDS if t != "tab-priority"]
    sections = [n for n in page_no_snapshot.doc.find_all("section") if n.attrs.get("id") == "priority"]
    assert len(sections) == 1, "секция #priority должна выводиться всегда"


def test_n4_header_keeps_h1_three_meta_and_adds_switcher_and_back(page):
    headers = [h for h in page.doc.find_all("header") if "topbar" in h.classes()]
    assert len(headers) == 1
    h = headers[0]
    assert len(h.find_all("h1")) == 1
    metas = h.find_all("div", "meta")
    assert len(metas) == 3, f"div.meta в шапке: {len(metas)}"
    assert metas[2].attrs.get("id") == "ready"
    assert len(h.find_all("details", "switcher")) == 1
    assert [a.attrs.get("href") for a in h.find_all("a", "back")] == ["#"]


# =========================================================================== 5. переключатель


def _switchers(doc: Node) -> list[Node]:
    return doc.find_all("details", "switcher")


def _the_switcher(doc: Node) -> Node:
    found = _switchers(doc)
    assert len(found) == 1, f"details.switcher: {len(found)}"
    return found[0]


def test_n5_exactly_one_switcher_with_summary_literal(page):
    sw = _switchers(page.doc)
    assert len(sw) == 1
    summary = sw[0].elems()[0] if sw[0].elems() else None
    assert summary is not None and summary.tag == "summary"
    assert summary.text() == "Планы ▾"


def test_n5_group_titles_in_order(page):
    sw = _the_switcher(page.doc)
    groups = sw.find_all("div", "sw-group")
    assert [g.find_all("b")[0].text() for g in groups] == [g for g, _ in SWITCHER_GROUPS]


def test_n5_seven_links_in_card_order_with_anchor_hrefs(page):
    sw = _the_switcher(page.doc)
    links = sw.find_all("a")
    assert [a.attrs.get("href") for a in links] == ["#" + a for a in ANCHORS]


def test_n5_links_grouped_by_tier(page):
    sw = _the_switcher(page.doc)
    got = [
        (g.find_all("b")[0].text(), [a.attrs.get("href") for a in g.find_all("a")])
        for g in sw.find_all("div", "sw-group")
    ]
    assert got == SWITCHER_GROUPS


def test_n5_link_text_is_plan_name_and_small_is_tally_without_tail(page):
    sw = _the_switcher(page.doc)
    links = sw.find_all("a")
    assert [a.text() for a in links] == NAMES
    assert [s.text() for s in sw.find_all("small")] == SWITCHER_SMALL


def test_n5_without_unlisted_plan_no_unlisted_group(page_no_unlisted):
    sw = _switchers(page_no_unlisted.doc)
    assert len(sw) == 1
    titles = [g.find_all("b")[0].text() for g in sw[0].find_all("div", "sw-group")]
    assert titles == ["Очередь", "Ждут", "Архив"]
    assert len(sw[0].find_all("a")) == 6


# =========================================================================== 6. «← все планы»


def test_n6_exactly_one_back_link_to_hash(page):
    backs = page.doc.find_all("a", "back")
    assert len(backs) == 1
    assert backs[0].attrs.get("href") == "#"
    assert backs[0].text() == "← все планы"


# =========================================================================== 7. список задач в details.tasklist


def test_n7_tasks_list_inside_tasklist_with_count_in_summary(page):
    cs = cards(page.doc)
    assert len(cs) == 7
    for i, card in enumerate(cs):
        expected = TASK_COUNTS[i]
        tasklists = card.find_all("details", "tasklist")
        if expected is None:
            assert tasklists == [], f"карточка {i} без задач, но есть details.tasklist"
            continue
        assert len(tasklists) == 1, f"карточка {i}: details.tasklist: {len(tasklists)}"
        tl = tasklists[0]
        uls = [u for u in card.find_all("ul") if "tasks" in u.classes()]
        assert len(uls) == 1, f"карточка {i}: ul.tasks: {len(uls)}"
        ul = uls[0]
        assert tl in list(ul.ancestors()), f"карточка {i}: ul.tasks вне details.tasklist"
        first = tl.elems()[0]
        assert first.tag == "summary", f"карточка {i}: summary не первый в details.tasklist"
        assert first.text() == f"Задачи · {expected}", f"карточка {i}: {first.text()!r}"
        assert len(ul.find_all("li")) == expected, f"карточка {i}: li в ul.tasks != {expected}"


def test_n7_cards_without_tasks_have_no_ul_tasks_either(page):
    cs = cards(page.doc)
    assert len(cs) == 7
    assert any(c.find_all("details", "tasklist") for c in cs), "details.tasklist ещё нет ни у одной карточки"
    for i, card in enumerate(cs):
        if TASK_COUNTS[i] is None:
            assert [u for u in card.find_all("ul") if "tasks" in u.classes()] == []


# =========================================================================== 8. CSS


def test_n8_exactly_one_style_element(page):
    assert len(page.doc.find_all("style")) == 1


def test_n8_style_content_at_most_6900_bytes_utf8(page):
    styles = page.doc.find_all("style")
    assert len(styles) == 1
    css = "".join(c for c in styles[0].children if isinstance(c, str))
    assert css.strip(), "<style> пуст"
    assert len(css.encode("utf-8")) <= 6900


def test_n8_no_external_urls_or_imports(page):
    low = page.html.lower()
    assert "<style" in low
    for needle in ("http://", "https://", "@import"):
        assert needle not in low, f"на странице есть {needle!r}"


# =========================================================================== 9. golden --json без ключа anchor


def test_n9_json_without_anchor_key_equals_golden(order_md, make_root, progress):
    root = make_root(main_files(order_md))
    cp = progress(root, "--json")
    assert cp.returncode == 0, cp.stderr[:400]
    out = cp.stdout.replace("\r\n", "\n")
    # ключ `anchor` — последний в объекте плана, отступ 4 (indent=2, плоский список): снимаем строку и запятую перед ней
    stripped = re.sub(r',\n {4}"anchor": "[^"\n]*"(?=\n)', "", out)
    golden = GOLDEN.read_bytes().decode("utf-8").replace("\r\n", "\n")
    assert golden.strip(), "golden пуст"
    assert stripped == golden


# =========================================================================== 11. якорь в --json


def test_n11_anchor_is_last_key_of_every_plan_object(order_md, make_root, progress):
    root = make_root(main_files(order_md))
    _, data = _json_of(progress, root)
    assert len(data) == 7
    assert [list(rec)[-1] for rec in data] == ["anchor"] * 7


def test_n11_json_anchor_literals_by_path(order_md, make_root, progress):
    root = make_root(main_files(order_md))
    _, data = _json_of(progress, root)
    got = {rec["path"]: rec.get("anchor") for rec in data}
    assert got == dict(zip(PATHS, ANCHORS, strict=True))


def test_n11_json_anchor_equals_html_anchor_of_same_plan_by_path(render, order_md, progress):
    root, pg = render(main_files(order_md))
    _, data = _json_of(progress, root)
    json_by_path = {rec["path"]: rec.get("anchor") for rec in data}
    html_by_path: dict[str, str | None] = {}
    for card in cards(pg.doc):
        paths = [d.text() for d in card.find_all("div", "info") if d.text() in PATHS]
        assert len(paths) == 1, f"путь карточки не найден: {paths}"
        sp = anchor_spans(card)
        html_by_path[paths[0]] = sp[0].attrs.get("id") if sp else None
    assert html_by_path == json_by_path
    assert json_by_path == dict(zip(PATHS, ANCHORS, strict=True))


def test_n11_collision_json_and_html_agree(render, order_md, progress):
    root, pg = render(collision_files(order_md))
    _, data = _json_of(progress, root)
    got = {rec["path"]: rec.get("anchor") for rec in data}
    assert got == dict(zip(COLLISION_PATHS, COLLISION_ANCHORS, strict=True))
    html_by_path = {}
    for card in cards(pg.doc):
        paths = [d.text() for d in card.find_all("div", "info") if d.text() in COLLISION_PATHS]
        assert len(paths) == 1
        sp = anchor_spans(card)
        html_by_path[paths[0]] = sp[0].attrs.get("id") if sp else None
    assert html_by_path == got


# =========================================================================== охранный: прежняя разметка только с добавками


def test_guard_old_markup_literals_and_section_order_kept(page):
    h = page.html
    assert '<details id="waiting">' in h
    assert '<details id="archive">' in h
    assert '<section id="queue">' in h
    keep = {"priority", "who", "queue", "waiting", "unlisted", "archive"}
    ids = [n.attrs["id"] for n in page.doc.walk() if n.tag in ("section", "details") and n.attrs.get("id") in keep]
    assert ids == ["priority", "who", "queue", "waiting", "unlisted", "archive"]
