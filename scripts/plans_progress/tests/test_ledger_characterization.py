"""Характеризация plans_ledger.py ДО правки Task 1.0: зелёная и сейчас, и после.

Фиксирует старое поведение, которое Task 1.0 обязана сохранить: счёт задач по заголовкам
`### Task X.Y` и чекбоксам, голый `[DONE]` в разделе порядка, файлы `phase-N.md`, поведение
`close`. Ожидаемые числа — литералы из самих фикстур (считаны вручную), не вывод кода.

Только CLI в subprocess (см. conftest.py).
"""

from __future__ import annotations

import re

import pytest

# Task 4.1: каждый тест — в обоих режимах summarize_plan (корень без парсера / с копией парсера).
pytestmark = pytest.mark.parametrize("parser_mode", [False, True], ids=["legacy", "adapter"], indirect=True)

CATALOG_PLAN = """# Каталожный план

## Phase 1

### Task 1.1 — первая
- [x] шаг а
- [x] шаг б

### Task 1.2 — вторая
- [x] шаг а
- [ ] шаг б

## Phase 2

### Task 2.1 — третья
- [ ] шаг а
"""


def test_status_counts_headings_with_ticked_checkboxes(make_root, ledger):
    # 1.1 закрыта (оба чекбокса), 1.2 открыта (один не отмечен), 2.1 открыта -> 1 из 3
    root = make_root({"plans/2026-09-01_catalog/plan.md": CATALOG_PLAN})
    assert ledger.counts(root, "2026-09-01_catalog") == (1, 3)


def test_status_unticked_checkbox_keeps_task_open(make_root, ledger):
    # одна задача, один неотмеченный чекбокс -> 0 из 1 (граница: «почти закрыта» не считается)
    text = "# P\n\n### Task 1.1 — a\n- [x] a\n- [ ] b\n"
    root = make_root({"plans/2026-09-01_open/plan.md": text})
    assert ledger.counts(root, "2026-09-01_open") == (0, 1)


def test_status_bare_done_marker_in_order_section_closes_heading_task(make_root, ledger):
    # заголовок есть, чекбокс не отмечен, но в разделе порядка стоит голый [DONE] -> задача закрыта
    text = (
        "# P\n\n## Порядок выполнения\n\n- Task 1.1: первая [DONE]\n- Task 1.2: вторая [PENDING]\n\n"
        "## Задачи\n\n### Task 1.1 — первая\n- [ ] шаг\n\n### Task 1.2 — вторая\n- [ ] шаг\n"
    )
    root = make_root({"plans/2026-09-01_bare/plan.md": text})
    assert ledger.counts(root, "2026-09-01_bare") == (1, 2)


def test_status_reads_numbered_phase_file(make_root, ledger):
    # plan.md: 1.1 закрыта; phase-2.md: 2.1 открыта -> 1 из 2 (старый `phase-N.md` обязан читаться)
    root = make_root(
        {
            "plans/2026-09-01_phased/plan.md": "# P\n\n### Task 1.1 — a\n- [x] a\n",
            "plans/2026-09-01_phased/phase-2.md": "# Фаза 2\n\n### Task 2.1 — b\n- [ ] a\n",
        }
    )
    assert ledger.counts(root, "2026-09-01_phased") == (1, 2)


def test_close_done_dated_catalog_plan_moves_into_quarter_of_name(make_git_root, ledger):
    # закрытый по чекбоксам план `2026-02-15_*` уходит в `_archive/2026-Q1/` (квартал — из имени)
    text = "# P\n\n### Task 1.1 — a\n- [x] a\n"
    root = make_git_root({"plans/2026-02-15_done/plan.md": text})
    cp = ledger.close(root, "2026-02-15_done")
    assert cp.returncode == 0, f"close должен пройти: {cp.stdout!r} {cp.stderr!r}"
    assert (root / "plans" / "_archive" / "2026-Q1" / "2026-02-15_done" / "plan.md").is_file()
    assert not (root / "plans" / "2026-02-15_done").exists()


def test_close_refuses_open_plan_and_leaves_it_in_place(make_git_root, ledger):
    text = "# P\n\n### Task 1.1 — a\n- [ ] a\n"
    root = make_git_root({"plans/2026-02-15_open/plan.md": text})
    cp = ledger.close(root, "2026-02-15_open")
    assert cp.returncode != 0
    assert re.search(r"not done|refused", cp.stdout + cp.stderr), cp.stdout + cp.stderr
    assert (root / "plans" / "2026-02-15_open" / "plan.md").is_file()


def test_close_force_archives_open_plan(make_git_root, ledger):
    text = "# P\n\n### Task 1.1 — a\n- [ ] a\n"
    root = make_git_root({"plans/2026-02-15_forced/plan.md": text})
    cp = ledger.close(root, "2026-02-15_forced", "--force")
    assert cp.returncode == 0, f"{cp.stdout!r} {cp.stderr!r}"
    assert (root / "plans" / "_archive" / "2026-Q1" / "2026-02-15_forced" / "plan.md").is_file()


def test_close_undated_name_is_refused_even_when_plan_is_done(make_git_root, ledger):
    # план закрыт по старому формату (заголовок + чекбокс), но без даты в имени -> отказ, файл на месте
    text = "# P\n\n### Task 1.1 — a\n- [x] a\n"
    root = make_git_root({"plans/undated-plan/plan.md": text})
    cp = ledger.close(root, "undated-plan")
    assert cp.returncode != 0, f"close без даты в имени обязан отказать: {cp.stdout!r}"
    assert (root / "plans" / "undated-plan" / "plan.md").is_file()
    assert not (root / "plans" / "_archive").exists() or not any((root / "plans" / "_archive").rglob("plan.md"))
