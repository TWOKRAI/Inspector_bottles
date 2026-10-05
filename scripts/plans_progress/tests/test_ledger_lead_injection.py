"""Тесты лида, закрывающие живых мутантов break-injection по ledger (Task 1.0).

L06: «родитель без маркера не задача» держался только тестом зеркала.
L10: «имя плана проверяется раньше "готов"» держалось только тестом зеркала.
Каждый тест ниже красный на своей инъекции и зелёный на коде (см. result-1.0.md, раздел лида).
"""

from __future__ import annotations

import pytest

# Task 4.1: каждый тест — в обоих режимах summarize_plan (корень без парсера / с копией парсера).
pytestmark = pytest.mark.parametrize("parser_mode", [False, True], ids=["legacy", "adapter"], indirect=True)

SECTION = "## Порядок выполнения\n\n"


def test_parent_without_marker_does_not_keep_a_finished_plan_open(make_git_root, ledger):
    """Родитель `1b.2` без слова статуса — не задача: дети закрыты, план готов, `close` проходит без --force.

    Счёт `N/M` этого не видит (задача со статусом `?` вне знаменателя), поэтому проверяем через `close`:
    пункт `?` не даёт плану стать готовым.
    """
    plan = (
        "# План\n\n"
        + SECTION
        + "- Task 1b.1: раньше [DONE]\n"
        + "- Task 1b.2: **РАЗДЕЛЕНА на подзадачи**\n"
        + "  - Task 1b.2a: первая [DONE]\n"
        + "  - Task 1b.2b: вторая [DONE]\n"
    )
    root = make_git_root({"plans/2026-10-02_parent.md": plan})
    cp = ledger.close(root, "2026-10-02_parent.md")
    assert cp.returncode == 0, (cp.returncode, (cp.stdout + cp.stderr)[:400])


def test_undated_plan_with_open_task_is_refused_for_the_name_not_for_open_tasks(make_git_root, ledger):
    """Имя проверяется ДО «готов»: у плана без даты и с открытой задачей отказ про имя."""
    plan = "# План\n\n" + SECTION + "- Task 1.1: a [DONE]\n- Task 1.2: b [PENDING]\n"
    root = make_git_root({"plans/undated-open.md": plan})
    cp = ledger.close(root, "undated-open.md")
    out = cp.stdout + cp.stderr
    assert cp.returncode == 2, (cp.returncode, out[:300])
    assert "YYYY-MM-DD" in out, out[:300]
    assert "is not done" not in out, out[:300]
