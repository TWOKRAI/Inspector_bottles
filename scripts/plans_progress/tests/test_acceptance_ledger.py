"""Приёмка Task 1.0 (правка plans_ledger.py) — слепые тесты по плану plans-progress-dashboard.

Красные там, где поведение меняется. Источник правды — раздел «Формат задачи» и приёмка
Task 1.0 плана. Ожидаемые числа — литералы из плана или из самих фикстур; вывод кода как
эталон не используется.

Только CLI: `plans_ledger.py status --root R` (читаем строку `<план>: N/M`) и
`plans_ledger.py close <план> --root R` (в git-копии, `close` делает git mv).
"""

from __future__ import annotations

import pytest

# Task 4.1: каждый тест — в обоих режимах summarize_plan (корень без парсера / с копией парсера).
pytestmark = pytest.mark.parametrize("parser_mode", [False, True], ids=["legacy", "adapter"], indirect=True)


# --------------------------------------------------------------------------- фикстуры a/b/c/d

SECTION = "## Порядок выполнения\n\n"


def test_fixture_a_item_with_tail_without_heading_counts_one_of_one(make_root, ledger):
    # a: пункт с хвостом, заголовка `### Task` нет -> 1/1
    text = "# A\n\n" + SECTION + "- Task 1.1: первая [DONE 2026-10-02 — `abc1234`; 5 тестов]\n"
    root = make_root({"plans/2026-10-02_a/plan.md": text})
    assert ledger.counts(root, "2026-10-02_a") == (1, 1)


def test_fixture_b_bare_done_item_without_heading_counts_one_of_one(make_root, ledger):
    # b: пункт с голым `[DONE]`, заголовка нет -> 1/1
    text = "# B\n\n" + SECTION + "- Task 1.1: первая [DONE]\n"
    root = make_root({"plans/2026-10-02_b/plan.md": text})
    assert ledger.counts(root, "2026-10-02_b") == (1, 1)


def test_fixture_c_item_with_tail_plus_heading_counts_one_of_one(make_root, ledger):
    # c: и пункт с хвостом, и заголовок с НЕотмеченным чекбоксом -> пункт решает, 1/1
    text = (
        "# C\n\n" + SECTION + "- Task 1.1: первая [DONE 2026-10-02 — `abc1234`; ok]\n\n"
        "## Задачи\n\n### Task 1.1 — первая\n- [ ] шаг\n"
    )
    root = make_root({"plans/2026-10-02_c/plan.md": text})
    assert ledger.counts(root, "2026-10-02_c") == (1, 1)


def test_fixture_d_item_and_fully_ticked_heading_counts_one_of_one(make_root, ledger):
    # d: пункт `[DONE …]` и заголовок с отмеченными чекбоксами одновременно -> всё равно 1/1 (не 2)
    text = (
        "# D\n\n" + SECTION + "- Task 1.1: первая [DONE 2026-10-02 — `abc1234`; ok]\n\n"
        "## Задачи\n\n### Task 1.1 — первая\n- [x] шаг\n"
    )
    root = make_root({"plans/2026-10-02_d/plan.md": text})
    assert ledger.counts(root, "2026-10-02_d") == (1, 1)


# --------------------------------------------------------------------------- статус-слова и хвосты


def test_code_span_pending_in_text_then_done_at_end_counts_done(make_root, ledger):
    # `[PENDING]` в обратных кавычках — цитата; настоящий статус `[DONE]` в конце -> 1/1
    text = "# P\n\n" + SECTION + "- Task 1.1: заменить `[PENDING]` на метку [DONE]\n"
    root = make_root({"plans/2026-10-02_span/plan.md": text})
    assert ledger.counts(root, "2026-10-02_span") == (1, 1)


def test_denominator_excludes_deferred(make_root, ledger):
    # DONE, DEFERRED, PENDING -> 1 из 2: отложенная задача не в знаменателе
    text = "# P\n\n" + SECTION + "- Task 1.1: a [DONE]\n- Task 1.2: b [DEFERRED — после 4.1]\n- Task 1.3: c [PENDING]\n"
    root = make_root({"plans/2026-10-02_defer/plan.md": text})
    assert ledger.counts(root, "2026-10-02_defer") == (1, 2)


def test_denominator_excludes_superseded(make_root, ledger):
    text = "# P\n\n" + SECTION + "- Task 1.1: a [DONE]\n- Task 1.2: b [SUPERSEDED]\n- Task 1.3: c [PENDING]\n"
    root = make_root({"plans/2026-10-02_sup/plan.md": text})
    assert ledger.counts(root, "2026-10-02_sup") == (1, 2)


# --------------------------------------------------------------------------- id и вложенность


def test_id_with_suffix_is_separate_from_its_prefix(make_root, ledger):
    # `1.3` и `1.3a` — две задачи; статус одной не протекает в другую -> 1 из 2
    text = "# P\n\n" + SECTION + "- Task 1.3: a [DONE]\n- Task 1.3a: b [PENDING]\n"
    root = make_root({"plans/2026-10-02_ids/plan.md": text})
    assert ledger.counts(root, "2026-10-02_ids") == (1, 2)


def test_pre_suffix_id_does_not_leak_status_to_stem(make_root, ledger):
    # `1b.2b-pre` DONE, `1b.2b` PENDING: две разные задачи -> 1 из 2 (не 2 из 2)
    text = "# P\n\n" + SECTION + "- Task 1b.2b-pre: a [DONE]\n- Task 1b.2b: b [PENDING]\n"
    root = make_root({"plans/2026-10-02_pre/plan.md": text})
    assert ledger.counts(root, "2026-10-02_pre") == (1, 2)


def test_parent_without_marker_is_not_a_task_children_are(make_root, ledger):
    # родитель `1b.2` без маркера — не задача; дети с отступом — задачи: 1 из 2
    text = (
        "# P\n\n"
        + SECTION
        + "- Task 1b.2: **РАЗДЕЛЕНА на подзадачи**\n"
        + "  - Task 1b.2a: первая [DONE]\n"
        + "  - Task 1b.2b: вторая [PENDING]\n"
    )
    root = make_root({"plans/2026-10-02_parent/plan.md": text})
    assert ledger.counts(root, "2026-10-02_parent") == (1, 2)


def test_child_status_is_not_given_to_parent_with_own_marker(make_root, ledger):
    # `1b.2` PENDING + `1b.2a` DONE: статус `1b.2a` не отдаётся родителю `1b.2` -> 1 из 2
    text = "# P\n\n" + SECTION + "- Task 1b.2: родитель [PENDING]\n- Task 1b.2a: ребёнок [DONE]\n"
    root = make_root({"plans/2026-10-02_child/plan.md": text})
    assert ledger.counts(root, "2026-10-02_child") == (1, 2)


# --------------------------------------------------------------------------- набор задач


def test_set_rule_headings_do_not_add_ids_when_section_has_items(make_root, ledger):
    # в разделе два пункта; заголовок `### Task 3.3` другой нарезки НЕ добавляет id -> 1 из 2 (не 1 из 3)
    text = (
        "# P\n\n" + SECTION + "- Task 1.1: a [DONE]\n- Task 1.2: b [PENDING]\n\n"
        "## Старая нарезка\n\n### Task 3.3 — старая задача\n- [ ] шаг\n"
    )
    root = make_root({"plans/2026-10-02_n1/plan.md": text})
    assert ledger.counts(root, "2026-10-02_n1") == (1, 2)


def test_set_rule_phase_file_headings_do_not_add_ids_when_section_has_items(make_root, ledger):
    root = make_root(
        {
            "plans/2026-10-02_n1p/plan.md": "# P\n\n" + SECTION + "- Task 1.1: a [DONE]\n- Task 1.2: b [PENDING]\n",
            "plans/2026-10-02_n1p/phase-2.md": "# Фаза 2\n\n### Task 4.3 — старая\n- [ ] шаг\n",
        }
    )
    assert ledger.counts(root, "2026-10-02_n1p") == (1, 2)


def test_phase_file_with_name_suffix_is_read(make_root, ledger):
    # раздела нет; `phase-2-core.md` с закрытой `### Task 2.1` читается -> 1 из 1
    root = make_root(
        {
            "plans/2026-10-02_pn/plan.md": "# P\n\nПроза без задач.\n",
            "plans/2026-10-02_pn/phase-2-core.md": "# Фаза 2\n\n### Task 2.1 — a\n- [x] шаг\n",
        }
    )
    assert ledger.counts(root, "2026-10-02_pn") == (1, 1)


def test_phase_file_with_letter_and_name_suffix_is_read(make_root, ledger):
    # `phase-1b-recipe-service.md` с открытой `### Task 1b.1` читается -> 0 из 1
    root = make_root(
        {
            "plans/2026-10-02_pl/plan.md": "# P\n\nПроза без задач.\n",
            "plans/2026-10-02_pl/phase-1b-recipe-service.md": "# Фаза 1b\n\n### Task 1b.1 — a\n- [ ] шаг\n",
        }
    )
    assert ledger.counts(root, "2026-10-02_pl") == (0, 1)


# --------------------------------------------------------------------------- реальные снимки


def test_real_layer_render_counts_five_of_twenty(real_root, ledger):
    # литерал плана: layer-render -> 5 из 20 (не 0/17 и не 5/23)
    assert ledger.counts(real_root, "layer-render") == (5, 20)


def test_real_gui_service_counts_ten_of_twenty_one(real_root, ledger):
    # литерал плана: gui-service -> 10 из 21 (не 0/0 и не 12/22)
    assert ledger.counts(real_root, "2026-09-22_gui-service") == (10, 21)


# --------------------------------------------------------------------------- close


ETALON = (
    "# Эталон\n\n"
    + SECTION
    + "- Task 1.1: первая [DONE 2026-10-02 — `abc1234`; тесты]\n"
    + "- Task 1.2: вторая [DONE 2026-10-02 — `def5678`; тесты]\n"
)


def test_close_etalon_passes_without_force(make_git_root, ledger):
    # литерал приёмки: файл 2026-10-02_etalon.md с двумя `[DONE 2026-10-02 — …]` закрывается без --force
    root = make_git_root({"plans/2026-10-02_etalon.md": ETALON})
    cp = ledger.close(root, "2026-10-02_etalon.md")
    assert cp.returncode == 0, f"close обязан пройти без --force: stdout={cp.stdout!r} stderr={cp.stderr!r}"


def test_close_etalon_lands_in_archive_of_quarter_from_name(make_git_root, ledger):
    root = make_git_root({"plans/2026-10-02_etalon.md": ETALON})
    cp = ledger.close(root, "2026-10-02_etalon.md")
    assert cp.returncode == 0, f"{cp.stdout!r} {cp.stderr!r}"
    assert (root / "plans" / "_archive" / "2026-Q4" / "2026-10-02_etalon.md").is_file()
    assert not (root / "plans" / "2026-10-02_etalon.md").exists()


def test_close_takes_quarter_from_name_not_from_closing_date(make_git_root, ledger):
    # имя датировано февралём (Q1); сегодня — другой квартал -> архив `2026-Q1`
    text = ETALON
    root = make_git_root({"plans/2026-02-15_early.md": text})
    cp = ledger.close(root, "2026-02-15_early.md")
    assert cp.returncode == 0, f"{cp.stdout!r} {cp.stderr!r}"
    assert (root / "plans" / "_archive" / "2026-Q1" / "2026-02-15_early.md").is_file()


def test_close_does_not_archive_plan_with_open_task_in_new_format(make_git_root, ledger):
    # одна DONE, одна PENDING -> не закрыт: отказ и файл на месте (граница «все задачи», а не «хотя бы одна»)
    text = "# P\n\n" + SECTION + "- Task 1.1: a [DONE 2026-10-02 — `abc1234`; ok]\n- Task 1.2: b [PENDING]\n"
    root = make_git_root({"plans/2026-10-02_half.md": text})
    cp = ledger.close(root, "2026-10-02_half.md")
    assert cp.returncode != 0
    assert (root / "plans" / "2026-10-02_half.md").is_file()


def test_close_undated_name_is_refused_with_done_new_format(make_git_root, ledger):
    # имя без даты: `close` отказывает (код != 0), файл остаётся
    root = make_git_root({"plans/etalon-without-date.md": ETALON})
    cp = ledger.close(root, "etalon-without-date.md")
    assert cp.returncode != 0, f"без даты в имени close обязан отказать: {cp.stdout!r}"
    assert (root / "plans" / "etalon-without-date.md").is_file()


def test_close_undated_refusal_is_about_the_name_not_about_unfinished_tasks(make_git_root, ledger):
    # ИНТЕРПРЕТАЦИЯ тестера: причина отказа — отсутствие даты, а не «не готов» (план готов по эталону).
    # Сегодня ledger отвечает `is not done (0/0 …)`, т.е. по неверной причине.
    root = make_git_root({"plans/etalon-without-date.md": ETALON})
    cp = ledger.close(root, "etalon-without-date.md")
    out = cp.stdout + cp.stderr
    assert cp.returncode != 0 and out.strip(), "ожидается непустой отказ"
    assert "is not done" not in out, f"план готов; отказ должен быть про имя, а не про задачи: {out!r}"
