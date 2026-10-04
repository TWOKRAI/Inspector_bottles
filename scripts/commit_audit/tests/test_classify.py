# -*- coding: utf-8 -*-
"""Task 2.3 (commit-mechanism): приёмка классификатора срывов git commit / git merge, стадия RED.

Источник правды: plans/2026-10-03_commit-mechanism/tasks/2.3.md (ред. 2) — CLI (a), попытка (b)-(e),
таблица классов (f), писатель A1 (g), hidden (h), REDS R1-R6 — и разметка 19 попыток в
tasks/2.3-fixture-labels.md. Реализации (scripts/commit_audit/classify.py) при написании не было.

Тесты запускают CLI подпроцессом на фикстурах из tests/fixtures/:
    real/<каталог проекта>/...   — 19 попыток из настоящих транскриптов, обрезанные (R1);
    synthetic/<имя>/...          — малые собранные вручную корни для R4, R5, R6 и граничных правил.
Ожидаемые значения — литералы, посчитанные руками по разметке (не из кода под тестом).

ДОГОВОР ФОРМЫ `--json` (ДОГАДКА тестера, спека её не задаёт; живёт в одном месте — функции-«крючки»
attempts() / table() / counter() ниже; при другой форме правится только они):
    {
      "table":   {"A1": {"commit": 4, "per100_commit": 25.0, "merge": 0, "per100_merge": 0.0}, ... 13 строк ...},
      "commit_calls": 16, "merge_calls": 1, "both_calls": 0, "not_executed": 0, "any_failure": 13,
      "attempts": {"<tool_use.id>": {"kinds": ["commit"], "classes": ["A1", "A1-Bash"],
                                     "hidden": false, "outcome": "failure"}}
    }
    kinds   — подмножество ["commit", "merge"], отсортированное; classes — метки (строки таблицы без hidden;
              C3/C5/C6/B3 разрешены, тестами не проверяются); outcome — "failure" | "success" | "unknown".
    В "attempts" нет не исполненных (d) попыток и не-попыток (heredoc-тело, merge-base) — тестом не
    закреплено для (d), закреплено для не-попыток.

ЧТО ТЕСТЕР СЧИТАЕТ НЕОДНОЗНАЧНЫМ (вынесено в отдельные тесты, чтобы лид правил один литерал; подробности — в отчёте):
    * hidden для пунктов 6, 10, 19 (разметка молчит, правило (h) говорит «скрыто»:
      `2>&1 | tail` или `| grep` у самой команды);
    * (решено лидом, Ред. 3) writer-split пункта 4 — A1-Bash: `cp` в цикле с именами в том же вызове;
      примечание разметки про «ранний A1-повтор» неверно;
    * (решено лидом, Ред. 3) outcome пунктов 14 и 15 — строго unknown (правило (e), нет `[ветка sha]`);
    * any_failure: считаю вызовы (commit или merge) хоть с одним классом; «только commit» дало бы 12, а не 13;
    * дедупликация по tool_use.id между файлами (в спеке — «по tool_use.id», про файлы ничего).
"""

from __future__ import annotations

import ast
import functools
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "classify.py"
REAL = HERE / "fixtures" / "real"
SYN = HERE / "fixtures" / "synthetic"

# Окно, в которое попадают все даты фикстуры в любом часовом поясе (самое раннее — 2026-09-04T23:30Z,
# самое позднее — 2026-10-03T09:30Z).
WIDE = ("2026-09-01", "2026-10-05")

ROW_ORDER = [
    "A1",
    "A1-Edit/Write",
    "A1-F401",
    "A1-Bash",
    "A1-undecided",
    "A2",
    "A3",
    "C1",
    "C2",
    "C4",
    "B1",
    "B2",
    "hidden",
]
CLASS_ROWS = [r for r in ROW_ORDER if r != "hidden"]
WRITER_SPLIT = {"A1-Edit/Write", "A1-Bash", "A1-undecided"}
FOOTER = ("commit_calls", "merge_calls", "both_calls", "not_executed", "any_failure")


# ----------------------------------------------------------------------------------------------
# запуск CLI и «крючки» формы JSON
# ----------------------------------------------------------------------------------------------
@functools.lru_cache(maxsize=None)
def _run(root: str, args: tuple[str, ...]) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(SCRIPT), "--root", root, *args]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
    )


def _ok(proc: subprocess.CompletedProcess) -> subprocess.CompletedProcess:
    assert proc.returncode == 0, f"classify.py вышел с {proc.returncode}; stderr: {proc.stderr.strip()[:400]}"
    return proc


def run_json(root: Path, since: str = WIDE[0], until: str = WIDE[1], *extra: str) -> dict:
    proc = _ok(_run(str(root), ("--since", since, "--until", until, *extra, "--json")))
    return json.loads(proc.stdout)


def run_md(root: Path, since: str = WIDE[0], until: str = WIDE[1]) -> str:
    return _ok(_run(str(root), ("--since", since, "--until", until))).stdout


def attempts(report: dict) -> dict:
    return report["attempts"]


def table(report: dict) -> dict:
    return report["table"]


def counter(report: dict, key: str) -> int:
    return report[key]


def classes_of(report: dict, tid: str) -> set[str]:
    """Метки попытки, ограниченные строками таблицы (C3/C5/C6/B3 вне объёма Task 2.3)."""
    return set(attempts(report)[tid]["classes"]) & set(CLASS_ROWS)


def base_classes_of(report: dict, tid: str) -> set[str]:
    return classes_of(report, tid) - WRITER_SPLIT


def real() -> dict:
    return run_json(REAL)


# ----------------------------------------------------------------------------------------------
# разметка 19 попыток (R2). Ключ — номер пункта; id — tool_use.id оригинала
# ----------------------------------------------------------------------------------------------
ID = {
    1: "toolu_01K8txNP29bMXd5fX7BHGMvw",
    2: "toolu_01FTKxYNCBQhohz9u6tuqLCQ",
    3: "toolu_01Tq66bGWhhp4fzf5hQ7WqKi",
    4: "toolu_015K33dDpTc9ta4DGh5tTa5i",
    5: "toolu_011LsCKVoLYejqLoQsW2B8m7",
    6: "toolu_015kqpKCKbHCA1vFHLHgATXC",
    7: "toolu_01A3oSox9tcfiyHXLrSxsYTw",
    8: "toolu_01HX1VEXdCEQRaX7Crfs1Yue",
    9: "toolu_01WuDf3tsWdtwEDFduXddcGz",
    10: "toolu_01LDnKqtZngE4XfR2JQ7m32E",
    11: "toolu_01F4j4S2Ee24TPYxRiDkotqg",
    12: "toolu_01JJVZPa3CzG1uCgdiXwdxs6",
    13: "toolu_01TY4MoyvcpYQLYMhU7jmRSL",
    14: "toolu_019zPriixxrbN89qY17ppvLt",
    15: "toolu_014H5JvKjRbHoPyhc7gTp6Kw",
    16: "toolu_011bbweQffD5bHPek7tpxESA",
    17: "toolu_01CGqtJ88Ff8rFfAjHjqNvEr",  # негатив: git commit только в теле heredoc
    18: "toolu_01F2YgCjdrpqnaKJu7UEQ88t",  # негатив: git log / git merge-base
    19: "toolu_011Uuy7DtwGAnNLkyVzGeVS9",
}
ATTEMPT_ITEMS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 19]

# классы без разбивки A1 по писателю (она — отдельной осью, см. WRITER_SPLIT_EXPECT)
BASE_CLASSES = {
    1: {"A1"},
    2: {"A1", "C1"},
    3: {"A1"},
    4: {"A1", "A1-F401", "C1"},
    5: {"A2"},
    6: {"A3"},
    7: {"C1"},
    8: {"C2"},
    9: {"C4"},
    10: {"C4"},
    11: {"B1"},
    12: {"B2"},
    13: {"A2"},
    14: set(),
    15: set(),
    16: set(),
    19: set(),
}
# последний писатель .py перед попыткой (g): 1, 2 — Bash (cat >, sed -i); 3 — Edit; 4 — Bash (cp-цикл)
WRITER_SPLIT_EXPECT = {1: "A1-Bash", 2: "A1-Bash", 3: "A1-Edit/Write", 4: "A1-Bash"}
KINDS = {i: ["commit"] for i in ATTEMPT_ITEMS}
KINDS[9] = ["merge"]  # `git merge --no-ff -q -F - feat/t45`
FAILING_ITEMS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13]
# hidden, разметка названа явно: 9, 13, 14 (grep include), 16 (tail -3);
# не скрыты — остальные без tail/grep у самой команды.
# 12 — важный различитель: `2>&1 | tail -15` стоит у pytest, а не у `git commit` — не скрыто.
HIDDEN_LABELLED_TRUE = [9, 13, 14, 16]
HIDDEN_LABELLED_FALSE = [1, 2, 3, 4, 5, 7, 8, 11, 12, 15]
HIDDEN_BY_RULE_H = [6, 10, 19]  # `... 2>&1 | tail -15` / `| grep -iE ... | head -3` у самой команды; разметка молчит


# ----------------------------------------------------------------------------------------------
# (a) CLI
# ----------------------------------------------------------------------------------------------
def test_cli_json_output_is_one_json_object_on_stdout():
    out = real()
    assert isinstance(out, dict) and {"table", "attempts", *FOOTER} <= set(out)


def test_cli_default_output_is_a_markdown_table_with_rows_in_spec_order():
    lines = [ln.strip() for ln in run_md(REAL).splitlines() if ln.strip().startswith("|")]
    cells = [[c.strip() for c in ln.strip("|").split("|")] for ln in lines]
    assert cells[0] == ["class", "commit", "per100_commit", "merge", "per100_merge"]
    body = [row for row in cells[1:] if not all(set(c) <= set("-: ") for c in row)]
    assert [row[0] for row in body] == ROW_ORDER


def test_cli_default_output_carries_the_hand_counted_numbers():
    lines = [ln.strip() for ln in run_md(REAL).splitlines() if ln.strip().startswith("|")]
    cells = [[c.strip() for c in ln.strip("|").split("|")] for ln in lines[1:]]
    rows = {r[0]: r for r in cells if r and r[0] in ROW_ORDER}
    # строка C1: 3 из 16 commit-вызовов, 0 merge
    assert [float(x) for x in rows["C1"][1:]] == [3.0, 18.75, 0.0, 0.0]
    # строка C4: 1 commit (пункт 10) и 1 merge (пункт 9) из 1 merge-вызова
    assert [float(x) for x in rows["C4"][1:]] == [1.0, 6.25, 1.0, 100.0]


@pytest.mark.parametrize(
    "key,value",
    [("commit_calls", 16), ("merge_calls", 1), ("both_calls", 0), ("not_executed", 0)],
)
def test_cli_default_output_prints_the_footer_counters(key, value):
    m = re.search(rf"\b{key}\b\W*(\d+)", run_md(REAL))
    assert m is not None, f"под таблицей нет {key}"
    assert int(m.group(1)) == value


def test_classify_py_imports_only_the_standard_library():
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    bad = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            bad += [a.name for a in node.names if a.name.split(".")[0] not in sys.stdlib_module_names]
        elif isinstance(node, ast.ImportFrom):
            if node.level or (node.module or "").split(".")[0] not in sys.stdlib_module_names:
                bad.append(("." * node.level) + (node.module or ""))
    assert bad == [], f"не stdlib: {bad}"


# ----------------------------------------------------------------------------------------------
# R1/R2: метки по попыткам (ключ — tool_use.id)
# ----------------------------------------------------------------------------------------------
def test_real_fixture_has_exactly_the_seventeen_attempts():
    assert set(attempts(real())) == {ID[i] for i in ATTEMPT_ITEMS}


def test_negative_item_17_git_commit_inside_a_heredoc_body_is_not_an_attempt():
    assert ID[17] not in attempts(real())


def test_negative_item_18_git_log_and_merge_base_are_not_attempts():
    assert ID[18] not in attempts(real())


@pytest.mark.parametrize("item", ATTEMPT_ITEMS)
def test_attempt_classes_without_the_writer_split(item):
    assert base_classes_of(real(), ID[item]) == BASE_CLASSES[item]


@pytest.mark.parametrize("item", [1, 2, 3])
def test_a1_writer_split_follows_the_last_writer_of_the_staged_py(item):
    got = classes_of(real(), ID[item]) & WRITER_SPLIT
    assert got == {WRITER_SPLIT_EXPECT[item]}


def test_a1_writer_split_of_item_4_is_bash_because_of_the_cp_loop_naming_the_files():
    """Пункт 4: `for f in <3 имени>; do cp "$W/$f" "$f"; done` в вызове перед попыткой — писатель Bash (g).
    Решение лида (Ред. 3): A1-Bash; прежняя метка A1-undecided и её примечание были неверны."""
    got = classes_of(real(), ID[4]) & WRITER_SPLIT
    assert got == {"A1-Bash"}


def test_attempts_without_a1_have_no_writer_split_label():
    out = real()
    leaked = {i: classes_of(out, ID[i]) & WRITER_SPLIT for i in ATTEMPT_ITEMS if i not in (1, 2, 3, 4)}
    assert {i: s for i, s in leaked.items() if s} == {}


def test_attempt_kinds_commit_except_item_9_which_is_a_merge():
    out = attempts(real())
    assert {i: sorted(out[ID[i]]["kinds"]) for i in ATTEMPT_ITEMS} == KINDS


@pytest.mark.parametrize("item", HIDDEN_LABELLED_TRUE)
def test_hidden_true_when_the_failure_is_filtered_by_grep_or_tail(item):
    assert attempts(real())[ID[item]]["hidden"] is True


@pytest.mark.parametrize("item", HIDDEN_LABELLED_FALSE)
def test_hidden_false_without_a_filter_on_the_commit_pipeline(item):
    assert attempts(real())[ID[item]]["hidden"] is False


@pytest.mark.parametrize("item", HIDDEN_BY_RULE_H)
def test_hidden_true_for_2to1_pipe_into_tail_or_grep_where_the_label_is_silent(item):
    """Пункты 6, 10 (`2>&1 | tail -15`) и 19 (`2>&1 | grep -iE ... | head -3`): по (h) скрыто, разметка не называет."""
    assert attempts(real())[ID[item]]["hidden"] is True


def test_outcome_failure_for_every_attempt_with_a_class():
    out = attempts(real())
    assert {i: out[ID[i]]["outcome"] for i in FAILING_ITEMS} == {i: "failure" for i in FAILING_ITEMS}


def test_outcome_success_when_the_branch_sha_line_follows_a_hidden_pipe():
    assert attempts(real())[ID[16]]["outcome"] == "success"


def test_outcome_unknown_for_an_attempt_without_class_and_without_success_line():
    """Пункт 19: цепочка `&&` оборвалась до git commit; спека R2: «попытка без класса, исход unknown»."""
    assert attempts(real())[ID[19]]["outcome"] == "unknown"


@pytest.mark.parametrize("item", [14, 15])
def test_quiet_commit_without_a_branch_sha_line_has_outcome_unknown(item):
    """`-q` прячет `[ветка sha]`; правило (e) без неё даёт unknown (решение лида, Ред. 3). Класса нет."""
    got = attempts(real())[ID[item]]
    assert got["outcome"] == "unknown"
    assert classes_of(real(), ID[item]) == set()


# ----------------------------------------------------------------------------------------------
# R3: таблица на всей фикстуре — литералы, посчитанные руками (16 commit-вызовов, 1 merge-вызов)
# commit-вызовы: пункты 1-8, 10-16, 19; merge-вызов: пункт 9.
# ----------------------------------------------------------------------------------------------
TABLE = {
    "A1": (4, 25.0, 0, 0.0),  # 1, 2, 3, 4
    "A1-Edit/Write": (1, 6.25, 0, 0.0),  # 3
    "A1-F401": (1, 6.25, 0, 0.0),  # 4
    "A1-Bash": (3, 18.75, 0, 0.0),  # 1, 2, 4
    "A1-undecided": (0, 0.0, 0, 0.0),  # никто: пункт 4 — A1-Bash
    "A2": (2, 12.5, 0, 0.0),  # 5, 13
    "A3": (1, 6.25, 0, 0.0),  # 6
    "C1": (3, 18.75, 0, 0.0),  # 2, 4, 7
    "C2": (1, 6.25, 0, 0.0),  # 8
    "C4": (1, 6.25, 1, 100.0),  # commit: 10; merge: 9
    "B1": (1, 6.25, 0, 0.0),  # 11
    "B2": (1, 6.25, 0, 0.0),  # 12
    "hidden": (6, 37.5, 1, 100.0),  # commit: 6, 10, 13, 14, 16, 19 (разметка явно: 13, 14, 16 -> 3); merge: 9
}


def test_table_has_the_thirteen_rows_in_spec_order():
    assert list(table(real())) == ROW_ORDER


@pytest.mark.parametrize(
    "row",
    [r for r in ROW_ORDER if r != "hidden"] + [pytest.param("hidden", id="hidden-counts-6-10-19")],
)
def test_table_row_is_the_hand_counted_literal(row):
    got = table(real())[row]
    commit, per100_commit, merge, per100_merge = TABLE[row]
    assert got["commit"] == commit
    assert got["per100_commit"] == pytest.approx(per100_commit, abs=1e-9)
    assert got["merge"] == merge
    assert got["per100_merge"] == pytest.approx(per100_merge, abs=1e-9)


@pytest.mark.parametrize(
    "key,value",
    [("commit_calls", 16), ("merge_calls", 1), ("both_calls", 0), ("not_executed", 0)],
)
def test_footer_counter_is_the_hand_counted_literal(key, value):
    assert counter(real(), key) == value


def test_any_failure_counts_calls_with_at_least_one_class():
    """1-13: двенадцать commit-вызовов с классом + merge пункта 9 = 13 (при счёте только commit было бы 12)."""
    assert counter(real(), "any_failure") == 13


# ----------------------------------------------------------------------------------------------
# R4: дедупликация
# ----------------------------------------------------------------------------------------------
def test_the_same_tool_use_and_tool_result_written_twice_in_one_file_count_once():
    out = run_json(SYN / "dedup")
    assert table(out)["B1"]["commit"] == 1  # toolu_SYN_dd1 записан дважды


def test_a_copy_of_an_attempt_inside_an_agent_tool_result_is_not_a_second_attempt():
    out = run_json(SYN / "dedup")
    assert table(out)["A2"]["commit"] == 1  # toolu_SYN_dd2 процитирован в tool_result вызова Agent


def test_dedup_root_has_exactly_two_attempts_and_no_agent_attempt():
    out = run_json(SYN / "dedup")
    assert set(attempts(out)) == {"toolu_SYN_dd1", "toolu_SYN_dd2"}
    assert counter(out, "commit_calls") == 2


def test_the_same_tool_use_id_in_a_main_file_and_a_subagent_file_counts_once():
    out = run_json(SYN / "dedup_files")
    assert counter(out, "commit_calls") == 2
    assert table(out)["B1"]["commit"] == 1


# ----------------------------------------------------------------------------------------------
# R5: окно по timestamp записи; --until включительно
# ----------------------------------------------------------------------------------------------
W = {d: f"toolu_SYN_w{d}" for d in ("09", "10", "11", "12")}  # по одной попытке на дни 09-09 … 09-12 в 12:00Z


def test_window_excludes_attempts_outside_since_and_until():
    out = run_json(SYN / "window", "2026-09-10", "2026-09-11")
    assert set(attempts(out)) == {W["10"], W["11"]}


def test_window_until_is_inclusive():
    out = run_json(SYN / "window", "2026-09-01", "2026-09-09")
    assert set(attempts(out)) == {W["09"]}


def test_window_since_is_inclusive_and_a_one_day_window_keeps_that_day():
    out = run_json(SYN / "window", "2026-09-10", "2026-09-10")
    assert set(attempts(out)) == {W["10"]}


def test_window_with_no_attempts_exits_zero_and_counts_nothing():
    out = run_json(SYN / "window", "2026-10-01", "2026-10-02")
    assert counter(out, "commit_calls") == 0
    assert attempts(out) == {}


# ----------------------------------------------------------------------------------------------
# проекты: --project-substr (по умолчанию Inspector-vision-Inspector-bottles)
# ----------------------------------------------------------------------------------------------
def test_default_project_substr_takes_the_main_and_the_worktree_directories_only():
    out = run_json(SYN / "projects")
    assert set(attempts(out)) == {"toolu_SYN_pm", "toolu_SYN_pw"}


def test_project_substr_option_selects_another_directory():
    out = run_json(SYN / "projects", WIDE[0], WIDE[1], "--project-substr", "Other-Repo")
    assert set(attempts(out)) == {"toolu_SYN_po"}


# ----------------------------------------------------------------------------------------------
# R6: опыты в commitlab / scratchpad / tmp не считаются (c)
# ----------------------------------------------------------------------------------------------
@pytest.mark.parametrize("name", ["ctl1", "ctl2", "ctl3"])
def test_attempt_inside_the_repo_is_counted(name):
    """ctl1 — cwd репо; ctl2 — относительный `cd .claude/worktrees/...`; ctl3 — последний cd снова в репо."""
    assert f"toolu_SYN_cl_{name}" in attempts(run_json(SYN / "commitlab"))


@pytest.mark.parametrize(
    "name",
    [
        pytest.param("a", id="cwd-is-a-scratchpad-commitlab"),
        pytest.param("b", id="cd-to-a-scratchpad-commitlab"),
        pytest.param("c", id="cwd-in-repo-but-named-commitlab"),
        pytest.param("d", id="cd-to-tmp"),
        pytest.param("e", id="last-cd-wins-tmp"),
        pytest.param("f", id="cd-dollar-var-set-in-the-same-command"),
    ],
)
def test_attempt_in_a_scratch_or_commitlab_directory_is_not_counted(name):
    assert f"toolu_SYN_cl_{name}" not in attempts(run_json(SYN / "commitlab"))


def test_commitlab_root_counts_exactly_the_three_in_repo_attempts():
    assert counter(run_json(SYN / "commitlab"), "commit_calls") == 3


# ----------------------------------------------------------------------------------------------
# (d), (e): не исполнено и исход
# ----------------------------------------------------------------------------------------------
def test_denied_and_hook_blocked_attempts_are_not_executed_and_leave_the_denominator():
    out = run_json(SYN / "outcomes")
    # ne_perm, ne_perm_err, ne_auto, ne_hook
    assert counter(out, "not_executed") == 4
    # исполненные commit-вызовы: ok_commit, ex_protect, ex_late
    assert counter(out, "commit_calls") == 3


def test_merge_denominator_counts_the_three_executed_merges():
    assert counter(run_json(SYN / "outcomes"), "merge_calls") == 3


def test_a_protect_branch_hook_error_is_an_executed_attempt():
    got = attempts(run_json(SYN / "outcomes"))["toolu_SYN_oc_ex_protect"]
    assert got["outcome"] == "unknown"
    assert got["classes"] == []


def test_permission_text_after_the_first_line_does_not_make_an_attempt_not_executed():
    assert "toolu_SYN_oc_ex_late" in attempts(run_json(SYN / "outcomes"))


def test_commit_success_is_the_branch_sha_line():
    assert attempts(run_json(SYN / "outcomes"))["toolu_SYN_oc_ok_commit"]["outcome"] == "success"


@pytest.mark.parametrize("name", ["ok_merge_ort", "ok_merge_ff", "ok_merge_utd"])
def test_merge_success_lines(name):
    got = attempts(run_json(SYN / "outcomes"))[f"toolu_SYN_oc_{name}"]
    assert got["outcome"] == "success"
    assert got["kinds"] == ["merge"]


def test_no_failure_in_the_outcomes_root():
    assert counter(run_json(SYN / "outcomes"), "any_failure") == 0


# ----------------------------------------------------------------------------------------------
# per100: округление до двух знаков
# ----------------------------------------------------------------------------------------------
def test_per100_is_rounded_to_two_places_down_and_up():
    out = run_json(SYN / "rates")
    assert table(out)["A3"]["commit"] == 2 and table(out)["B1"]["commit"] == 1
    assert table(out)["A3"]["per100_commit"] == pytest.approx(66.67, abs=1e-9)  # 2/3
    assert table(out)["B1"]["per100_commit"] == pytest.approx(33.33, abs=1e-9)  # 1/3


def test_any_failure_in_the_rates_root():
    assert counter(run_json(SYN / "rates"), "any_failure") == 3


# ----------------------------------------------------------------------------------------------
# (b): какие команды — попытки
# ----------------------------------------------------------------------------------------------
RECOGNISED = ["p1", "p2", "p3", "p4", "p5", "p6", "p7", "m1", "m2"]
NOT_ATTEMPTS = ["n1", "n2", "n3", "n4", "n5", "n6", "n7", "n8", "n9"]


@pytest.mark.parametrize(
    "name",
    [
        pytest.param("p1", id="git-C-path-commit"),
        pytest.param("p2", id="git-c-key-commit"),
        pytest.param("p3", id="env-assignment-prefix"),
        pytest.param("p4", id="after-and-and"),
        pytest.param("p5", id="after-then"),
        pytest.param("p6", id="git-no-pager-commit"),
        pytest.param("p7", id="subshell"),
        pytest.param("m1", id="merge-no-ff"),
        pytest.param("m2", id="git-C-dot-merge"),
    ],
)
def test_command_form_is_recognised_as_an_attempt(name):
    assert f"toolu_SYN_rc_{name}" in attempts(run_json(SYN / "recognition"))


@pytest.mark.parametrize(
    "name",
    [
        pytest.param("n1", id="commit-dry-run"),
        pytest.param("n2", id="merge-abort"),
        pytest.param("n3", id="merge-quit"),
        pytest.param("n4", id="quoted-in-echo"),
        pytest.param("n5", id="quoted-in-grep-arg"),
        pytest.param("n6", id="commit-graph"),
        pytest.param("n7", id="merge-base"),
        pytest.param("n8", id="inside-heredoc-body"),
        pytest.param("n9", id="inside-python-c-quotes"),
    ],
)
def test_command_form_is_not_an_attempt(name):
    assert f"toolu_SYN_rc_{name}" not in attempts(run_json(SYN / "recognition"))


def test_recognition_root_denominators_count_only_the_recognised_forms():
    out = run_json(SYN / "recognition")
    assert counter(out, "commit_calls") == 7
    assert counter(out, "merge_calls") == 2


def test_one_call_with_git_merge_and_git_commit_counts_in_both_and_in_both_calls():
    out = run_json(SYN / "both")
    assert sorted(attempts(out)["toolu_SYN_both"]["kinds"]) == ["commit", "merge"]
    assert (counter(out, "commit_calls"), counter(out, "merge_calls"), counter(out, "both_calls")) == (1, 1, 1)


# ----------------------------------------------------------------------------------------------
# (h): hidden — границы правила
# ----------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "name,expected",
    [
        pytest.param("devnull", True, id="2-gt-dev-null"),
        pytest.param("ampdevnull", True, id="amp-gt-dev-null"),
        pytest.param("head", True, id="2to1-pipe-head"),
        pytest.param("pipeamp", True, id="pipe-amp-tail"),
        pytest.param("grepv", False, id="grep-v-is-not-hidden"),
        pytest.param("quiet", False, id="dash-q-is-not-hidden"),
    ],
)
def test_hidden_flag_boundaries(name, expected):
    assert attempts(run_json(SYN / "hidden"))[f"toolu_SYN_h_{name}"]["hidden"] is expected


# ----------------------------------------------------------------------------------------------
# (f): сигнатуры — якорь ^, блок хука, условия на числа
# ----------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "name,expected",
    [
        pytest.param("pre", set(), id="E501-before-a-passed-ruff-block"),
        pytest.param("quote", set(), id="signatures-quoted-mid-line"),
        pytest.param("rollback", set(), id="rolling-back-without-patch-does-not-apply"),
        pytest.param("f401_count", {"A1-F401"}, id="ruff-check-N-fixed-is-F401-without-A1"),
        pytest.param("f401_zero", set(), id="ruff-check-0-fixed-is-not-F401"),
        pytest.param("trim", {"A2"}, id="trim-trailing-whitespace-failed"),
        pytest.param("c2_heredoc", {"C2"}, id="here-document-delimited-by-end-of-file"),
    ],
)
def test_signature_conditions(name, expected):
    assert classes_of(run_json(SYN / "signatures"), f"toolu_SYN_sg_{name}") == expected
