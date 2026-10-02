# ruff: noqa: E501  -- литералы-фикстуры планов в одну строку
"""Заголовок раздела порядка: оба парсера (ledger и дашборд) читают его по одному правилу.

Правило эталона: уровень `#{2,6}`; из текста снимаются `*`, `_`, `` ` ``, затем нумерация
`^\\d+[.)]\\s*`; текст начинается с «Порядок выполнения»/«Execution order» или равен «Порядок».
Расхождение парсеров на одной фикстуре — дефект (ревью кода Task 1.0, итерация 1).
"""

from __future__ import annotations

import pytest

ITEMS = "- Task 1.1: a [DONE]\n- Task 1.2: b [PENDING]\n"

CASES = [
    # (имя, заголовок, ожидание (done, total) для обоих парсеров)
    ("numbered", "## 3. Порядок выполнения", (1, 2)),
    ("numbered-paren", "### 2) Execution order", (1, 2)),
    ("bold", "## **Порядок выполнения**", (1, 2)),
    ("code", "## `Порядок`", (1, 2)),
    ("h1-is-not-section", "# Порядок выполнения", (0, 0)),
    ("prefix-word-is-not-section", "## Порядок и окна", (0, 0)),
]


@pytest.mark.parametrize("name, heading, expected", CASES, ids=[c[0] for c in CASES])
def test_ledger_and_dashboard_agree_on_order_heading(make_root, ledger, one_plan, name, heading, expected):
    plan = f"2026-10-02_{name}"
    text = f"# План\n\n{heading}\n\n{ITEMS}"
    root = make_root({f"plans/{plan}.md": text})
    assert ledger.counts(root, plan) == expected, "ledger"
    rec = one_plan(root, plan)
    assert (rec["done"], rec["total"]) == expected, "дашборд"
