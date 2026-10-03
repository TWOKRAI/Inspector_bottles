# ruff: noqa: E501  -- литералы-фикстуры в одну строку
"""Область страницы и блока: только очередь и актуальное из ORDER.md (решение владельца 2026-10-03).

Страница: основной список — §4.1; `<details id="waiting">` — §4.2; `<section id="unlisted">` — планы без
яруса (нет в ORDER.md); `<details id="archive">` — архивные планы и §4.3. Блок `--sync-order`: планы §4.1,
§4.2 и без яруса, счётчик `в архиве: N` = архивные + §4.3. `--json` и `--check` не сужаются.

Фикстура: по одному плану в §4.1, §4.2, §4.3, ни в одной таблице и один архивный.
"""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path

BEGIN = "<!-- progress:begin -->"
END = "<!-- progress:end -->"

Q, W, C, F, A = "p-queue", "p-wait", "p-closed", "p-free", "2026-10-01_arch"


def _plan(status: str) -> str:
    return f"# P\n\n## Порядок выполнения\n\n- Task 1.1: a [{status}]\n"


class _Sections(HTMLParser):
    """plan (data-plan) -> id ближайшего контейнера из {queue, waiting, unlisted, archive} и его тег."""

    IDS = {"queue", "waiting", "unlisted", "archive"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, str | None]] = []
        self.plans: list[str] = []
        self.section_of: dict[str, str | None] = {}
        self.tag_of: dict[str, str] = {}
        self.text: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("br", "meta", "link", "img", "input", "hr"):
            return
        sec = a.get("id") if a.get("id") in self.IDS else None
        if sec:
            self.tag_of[sec] = tag
        if tag == "details" and "plan" in (a.get("class") or "").split():
            name = a.get("data-plan") or ""
            self.plans.append(name)
            self.section_of[name] = next((s for _t, s in reversed(self.stack) if s), None)
        self.stack.append((tag, sec))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        self.text.append(data)


def _files(order_md, *, with_unlisted: bool = True, extra_order: str = "") -> dict[str, str]:
    files = {
        f"plans/{Q}/plan.md": _plan("DONE"),
        f"plans/{W}/plan.md": _plan("PENDING"),
        f"plans/{C}/plan.md": _plan("DONE"),
        f"plans/_archive/2026-Q4/{A}/plan.md": _plan("DONE"),
        "plans/queue/ORDER.md": order_md(tier41=[Q], tier42=[W], tier43=[C]) + extra_order,
    }
    if with_unlisted:
        files[f"plans/{F}/plan.md"] = _plan("PENDING")
    return files


def _page(make_root, progress, tmp_path, order_md, **kw) -> tuple[_Sections, str]:
    root = make_root(_files(order_md, **kw))
    out = tmp_path / "page.html"
    cp = progress(root, "--html", str(out))
    assert cp.returncode == 0, cp.stderr[:300]
    raw = out.read_text(encoding="utf-8")
    p = _Sections()
    p.feed(raw)
    p.close()
    return p, raw


def test_plans_land_in_their_sections(make_root, progress, tmp_path, order_md):
    page, _ = _page(make_root, progress, tmp_path, order_md)
    assert page.section_of == {Q: "queue", W: "waiting", F: "unlisted", C: "archive", A: "archive"}


def test_section_kinds_and_document_order(make_root, progress, tmp_path, order_md):
    page, _ = _page(make_root, progress, tmp_path, order_md)
    assert page.tag_of["waiting"] == "details"
    assert page.tag_of["unlisted"] == "section"
    assert page.tag_of["archive"] == "details"
    # очередь, ждущие, не в ORDER, затем архив: сначала закрытые §4.3, потом архивные планы
    assert page.plans == [Q, W, F, C, A]


def test_unlisted_section_is_absent_when_every_plan_is_listed(make_root, progress, tmp_path, order_md):
    page, raw = _page(make_root, progress, tmp_path, order_md, with_unlisted=False)
    assert 'id="unlisted"' not in raw
    assert page.section_of == {Q: "queue", W: "waiting", C: "archive", A: "archive"}


def test_header_counts_line(make_root, progress, tmp_path, order_md):
    page, _ = _page(make_root, progress, tmp_path, order_md)
    text = " ".join("".join(page.text).split())
    assert "в очереди 1 · ждут 1 · не в ORDER 1 · закрыто и в архиве 2" in text


def test_lane_cards_count_only_queue_waiting_and_unlisted(make_root, progress, tmp_path, order_md):
    page, _ = _page(make_root, progress, tmp_path, order_md)
    text = " ".join("".join(page.text).split())
    # Q — полоса «С» (1 план); W и F без полосы; закрытый C и архивный A карточек не дают
    assert "Полоса С · планов 1" in text
    assert "Полоса — · планов 2" in text
    assert "планов 3" not in text and "планов 4" not in text


def _block(root: Path) -> list[str]:
    text = (root / "plans" / "queue" / "ORDER.md").read_text(encoding="utf-8")
    m = re.search(re.escape(BEGIN) + r"\n(.*?)" + re.escape(END), text, re.S)
    assert m, text[-300:]
    return m.group(1).splitlines()


def test_block_has_queue_waiting_unlisted_and_archive_counter(make_root, progress, order_md):
    root = make_root(_files(order_md, extra_order=f"\n## Прогресс\n\n{BEGIN}\n{END}\n"))
    cp = progress(root, "--sync-order")
    assert cp.returncode == 0, cp.stderr[:300]
    assert _block(root) == [
        f"- {Q} — 1 из 1 · 100%",
        f"- {W} — 0 из 1 · 0%",
        f"- {F} — 0 из 1 · 0%",
        "в архиве: 2",
    ]


def test_json_still_lists_every_plan_with_its_tier(make_root, plans_json, order_md):
    root = make_root(_files(order_md))
    recs = plans_json(root)
    assert {n: r["tier"] for n, r in recs.items()} == {Q: "4.1", W: "4.2", C: "4.3", F: None, A: None}
    assert recs[A]["archived"] is True


def test_check_still_sees_every_plan(make_root, progress, order_md):
    # план §4.3 без задач остаётся в --check (информационная находка), хотя страница прячет его в архив
    files = _files(order_md)
    files[f"plans/{C}/plan.md"] = "# Пустой\n\nПроза.\n"
    root = make_root(files)
    cp = progress(root, "--check")
    assert cp.returncode == 0
    assert any(ln.startswith("NO_TASKS ") and C in ln for ln in cp.stdout.splitlines()), cp.stdout[-400:]
    assert json.loads(progress(root, "--json").stdout)
