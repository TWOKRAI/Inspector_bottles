"""Тесты лида, закрывающие живых мутантов инъекций по Task 2.5 (2026-10-03).

T03: `PARTIAL` обрезает разбор хвоста заголовка — тест автора брал вход, который отвергался и без обрезки
     (слово «отложен» без разделителя), поэтому обрезку не проверял.
T13: чип «⚠ шапка: DONE, …» только при незакрытых задачах — тест автора проверял лишь «есть конфликт».
Каждый тест красный на своей инъекции и зелёный на коде.
"""

from __future__ import annotations

import re


def test_partial_cutoff_hides_a_status_word_that_follows_a_separator(make_root, one_plan):
    # без обрезки: после `(` слово ЗАКРЫТА принимается с любым текстом -> done; с обрезкой по PARTIAL -> pending
    plan = "# Т\n\n### Task 1.1: шаг — PARTIAL (ЗАКРЫТА частично, шаг 1)\n\nтекст задачи без чекбоксов\n"
    root = make_root({"plans/2026-10-02_partial.md": plan})
    tasks = {t["id"]: t["status"] for t in one_plan(root, "2026-10-02_partial")["tasks"]}
    assert tasks == {"1.1": "pending"}, tasks


def test_queue_plan_with_done_header_and_all_tasks_done_gets_no_warning(make_root, progress, tmp_path, order_md):
    plan = "# Т\n\n**Статус:** DONE\n\n## Порядок выполнения\n\n- Task 1.1: a [DONE]\n- Task 1.2: b [DONE]\n"
    root = make_root({"plans/p-ok.md": plan, "plans/queue/ORDER.md": order_md(tier41=["p-ok"])})
    out = tmp_path / "p.html"
    assert progress(root, "--html", str(out)).returncode == 0
    raw = out.read_text(encoding="utf-8")
    summ = raw.split('data-plan="p-ok"', 1)[1].split("</summary>", 1)[0]
    assert 'data-chip="header-conflict"' not in summ, summ
    assert re.search(r'data-chip="closed"[^>]*>закрыт<', summ), summ
