# ruff: noqa: E501  -- литералы-фикстуры и ожидания в одну строку
"""Тесты автора на внутренние опасности очереди владельца (Task 6.1: блок `owner-queue` в ORDER.md).

Приёмку пишет независимый тестер (test_acceptance_owner_queue.py, через CLI). Здесь — места, видимые по устройству:
маркер внутри строки, строка без замыкающей `|`, `\\|` в заметке, архивный план с тем же слагом, повтор id,
мусор / CRLF / BOM в файле без исключений, вырезание блока до `parse_order` / `parse_snapshot`, тексты
`ORDER_BLOCK_MISSING` и `--sync-order` байт в байт.

Почти все тесты импортируют модуль напрямую (`parse_queue_block`, `build_queue`, `cut_queue_block`) с готовыми `Plan`;
вызов CLI в subprocess — один, с timeout. Ожидания — литералы.

У каждого теста в докстринге названа охраняемая строка кода; проверено вписыванием обратного изменения в эту строку
(тест краснеет), а не только зелёным прогоном.
"""

from __future__ import annotations

import importlib.util
import os
import random
import subprocess
import sys
from pathlib import Path

import pytest

_MOD_PATH = Path(__file__).resolve().parents[1] / "plans_progress.py"
_spec = importlib.util.spec_from_file_location("plans_progress_owner_queue_under_test", _MOD_PATH)
pp = importlib.util.module_from_spec(_spec)
sys.modules["plans_progress_owner_queue_under_test"] = pp
_spec.loader.exec_module(pp)

CALL_TIMEOUT = 60
BEGIN = "<!-- owner-queue:begin -->"
END = "<!-- owner-queue:end -->"
HEAD = "| # | План | Задача | Заметка |"
SEP = "|---|---|---|---|"
ITEM_KEYS = ["n", "kind", "plan", "task", "note", "known", "closed"]


def write_order(tmp_path: Path, text: str | bytes) -> Path:
    path = tmp_path / "ORDER.md"
    path.write_bytes(text if isinstance(text, bytes) else text.encode("utf-8"))
    return path


def block(*rows: str, head: str = HEAD, sep: str = SEP) -> str:
    return "\n".join([BEGIN, head, sep, *rows, END]) + "\n"


def mem_plan(name: str, tasks=(("1.1", "pending"),), archived: bool = False, tier: str | None = None) -> pp.Plan:
    p = pp.Plan(name=name, rel=f"plans/{name}/plan.md", archived=archived, tier=tier)
    p.tasks = [pp.Task(tid, "x", status) for tid, status in tasks]
    return p


def queue_of(tmp_path: Path, text: str | bytes, plans: list[pp.Plan] | None = None):
    return pp.build_queue(plans if plans is not None else [mem_plan("a-plan")], write_order(tmp_path, text))


def item(n, kind, plan, task, note, known, closed) -> dict:
    return {"n": n, "kind": kind, "plan": plan, "task": task, "note": note, "known": known, "closed": closed}


# =========================================================================== маркеры


def test_marker_inside_a_line_is_not_a_marker(tmp_path):
    """Охраняет `ln.strip() in (QUEUE_BEGIN, QUEUE_END)` в `locate_queue_block`: равенство строки, не вхождение.

    Упоминание обоих маркеров в тексте до и после исправного блока не считается маркером: пара одна, пункт один.
    """
    text = f"см. {BEGIN} в README\nа конец — {END}\n\n" + block("| 1 | a-plan | | |")
    items, findings = queue_of(tmp_path, text)
    assert items == [item(1, "plan", "a-plan", None, "", True, False)]
    assert findings == []
    assert pp.locate_queue_block(text.split("\n")) == ((3, 7), 1, 1)


def test_padded_marker_lines_are_markers_and_count_is_literal():
    """Охраняет `.strip()` в `locate_queue_block`: пробелы и табуляция по краям не в счёт."""
    assert pp.locate_queue_block([f"  {BEGIN}\t", "x", f"\t{END}  "]) == ((0, 2), 1, 1)
    assert pp.locate_queue_block([END, BEGIN]) == (None, 1, 1)
    assert pp.locate_queue_block([BEGIN, BEGIN, END]) == (None, 2, 1)


# =========================================================================== ячейки


def test_row_without_closing_pipe_keeps_columns(tmp_path):
    """Охраняет раздельное отбрасывание пустой части до ведущей и после замыкающей `|` в `_queue_cells`.

    Строка без замыкающей `|` (владелец забыл) не сдвигает колонки: `_cells` «Снимка» отбросил бы края только вместе.
    """
    rows, problem = pp.parse_queue_block(write_order(tmp_path, block("| 1 | a-plan | 1.1 | заметка", "| 2 | a-plan |")))
    assert problem == ""
    assert [(r.plan, r.task, r.note) for r in rows] == [("a-plan", "1.1", "заметка"), ("a-plan", "", "")]


def test_escaped_pipe_in_note_stays_inside_the_cell(tmp_path):
    """Охраняет `(?<!\\\\)` в `re.split` из `_queue_cells`: `\\|` не граница ячейки; `clean_md` снимает экранирование."""
    items, findings = queue_of(tmp_path, block(r"| 1 | a-plan | | до \| после |"))
    assert items == [item(1, "plan", "a-plan", None, "до | после", True, False)]
    assert findings == []


def test_only_the_first_table_of_the_block_is_read(tmp_path):
    """Охраняет `elif table: break` в `parse_queue_block`: непрерывная серия кончается первой непустой не-табличной строкой."""
    text = "\n".join(
        [BEGIN, "пояснение", HEAD, SEP, "| 1 | a-plan | | |", "", HEAD, SEP, "| 2 | a-plan | 1.1 | |", END]
    )
    items, _ = queue_of(tmp_path, text)
    assert [i["n"] for i in items] == [1]


@pytest.mark.parametrize("word", ["Task ", "task ", "TASK ", ""])
def test_task_word_prefix_is_stripped_in_any_case(tmp_path, word):
    """Охраняет `re.IGNORECASE` у `_QUEUE_TASK_WORD_RE`: `task 1.1` и `TASK 1.1` — тот же id, что `1.1`."""
    items, findings = queue_of(tmp_path, block(f"| 1 | a-plan | {word}1.1 | |"))
    assert items == [item(1, "task", "a-plan", "1.1", "", True, False)]
    assert findings == []


def test_equal_names_in_one_cell_collapse_to_one_name():
    """Охраняет `name not in out` в `queue_names`: повтор имени в ячейке — одно имя, не «больше одного» (чтение автора:
    как `snapshot_slugs`; в тексте задачи не оговорено)."""
    assert pp.queue_names("a-plan, a-plan") == ["a-plan"]
    assert pp.queue_names("a-plan, [a](../a-plan/plan.md)") == ["a-plan"]
    assert pp.queue_names("a-plan, c-plan") == ["a-plan", "c-plan"]
    assert pp.queue_names("фаза 5, `a-plan`, **c-plan**, 2026-10-01_b-plan") == [
        "a-plan",
        "c-plan",
        "2026-10-01_b-plan",
    ]


# =========================================================================== поиск плана и задачи


def test_exact_archived_name_beats_dated_live_plan(tmp_path):
    """Охраняет вызов `find_by_slug` в `_queue_item` (порядок: точное имя живой/архивный, затем имя с датой).

    Точное имя `b-plan` есть только в архиве, имя с датой `2026-10-01_b-plan` — у живого: по порядку из задачи
    выигрывает точное, пусть и архивное (закрыт, план в пункте — `b-plan`).
    """
    plans = [mem_plan("2026-10-01_b-plan"), mem_plan("b-plan", archived=True)]
    items, findings = queue_of(tmp_path, block("| 1 | b-plan | | |"), plans)
    assert items == [item(1, "plan", "b-plan", None, "", True, True)]
    assert [f.code for f in findings] == ["OWNER_QUEUE_CLOSED"]


def test_live_dated_plan_beats_archived_dated_plan_with_the_same_slug(tmp_path):
    """Охраняет тот же `find_by_slug`: среди имён с датой живой раньше архивного, даже если дата архивного позже."""
    plans = [mem_plan("2026-10-01_b-plan"), mem_plan("2026-11-01_b-plan", archived=True)]
    items, findings = queue_of(tmp_path, block("| 1 | b-plan | | |"), plans)
    assert items == [item(1, "plan", "2026-10-01_b-plan", None, "", True, False)]
    assert findings == []


def test_task_of_an_archived_plan_is_closed_even_when_pending(tmp_path):
    """Охраняет `plan_closed(plan) or …` в `closed` у `_queue_item`: задача архивного плана не выдаётся в 6.5."""
    plans = [mem_plan("old-plan", tasks=(("1.1", "pending"),), archived=True)]
    items, findings = queue_of(tmp_path, block("| 1 | old-plan | 1.1 | |"), plans)
    assert items == [item(1, "task", "old-plan", "1.1", "", True, True)]
    assert [f.code for f in findings] == ["OWNER_QUEUE_CLOSED"]


def test_duplicate_task_id_takes_the_first_entry(tmp_path):
    """Охраняет `next(t for t in plan.tasks if t.id == …)` в `_queue_item`: повтор id — первая запись (как `_dedupe_first`)."""
    plans = [mem_plan("a-plan", tasks=(("1.1", "pending"), ("1.1", "done")))]
    items, findings = queue_of(tmp_path, block("| 1 | a-plan | 1.1 | |"), plans)
    assert items == [item(1, "task", "a-plan", "1.1", "", True, False)]
    assert findings == []
    plans = [mem_plan("a-plan", tasks=(("1.1", "done"), ("1.1", "pending")))]
    items, _ = queue_of(tmp_path, block("| 1 | a-plan | 1.1 | |"), plans)
    assert items[0]["closed"] is True


# =========================================================================== находки


def test_finding_values_are_cut_to_80_chars_but_item_keeps_the_cell(tmp_path):
    """Охраняет `clean_md(…, 80)` для значений в тексте находки; в пункте `plan` остаётся с пределом 400."""
    long_cell = "x" * 200 + ", y"
    items, findings = queue_of(tmp_path, block(f"| 1 | {long_cell} | | |"))
    assert items[0]["plan"] == "x" * 200 + ", y" and items[0]["known"] is False
    assert [f.code for f in findings] == ["OWNER_QUEUE_BAD"]
    assert "x" * 79 + "…" in findings[0].text and "x" * 80 not in findings[0].text
    assert (findings[0].plan, findings[0].task_id, findings[0].blocking) == ("ORDER.md", None, False)


def test_block_finding_text_names_both_counts_and_order(tmp_path):
    """Охраняет текст `OWNER_QUEUE_BLOCK` из `parse_queue_block`: число begin, число end, «end раньше begin»."""
    _, findings = queue_of(tmp_path, f"{BEGIN}\n{HEAD}\n{SEP}\n{BEGIN}\n{END}\n")
    assert [f.line() for f in findings] == [
        "OWNER_QUEUE_BLOCK ORDER.md info — нужна ровно одна пара маркеров <!-- owner-queue:begin --> / "
        "<!-- owner-queue:end --> отдельными строками, найдено: owner-queue:begin 2, owner-queue:end 1"
    ]
    _, findings = queue_of(tmp_path, f"{END}\n{BEGIN}\n")
    assert findings[0].text.endswith(
        "найдено: owner-queue:begin 1, owner-queue:end 1; owner-queue:end стоит раньше owner-queue:begin"
    )


# =========================================================================== мусор, CRLF, BOM


GARBAGE = {
    "empty": b"",
    "only-marker-begin": BEGIN.encode(),
    "binary": bytes(range(256)) * 4,
    "invalid-utf8-in-block": BEGIN.encode() + b"\n| \xff\xfe | \xc3 |\n| 1 | \xd0 | |\n" + END.encode(),
    "lone-cr": f"{BEGIN}\r{HEAD}\r{SEP}\r| 1 | a-plan | | |\r{END}\r".encode(),
    "nul-bytes": f"{BEGIN}\n{HEAD}\n{SEP}\n| 1 | a\x00plan | \x00 | |\n{END}\n".encode(),
    "pipes-only": f"{BEGIN}\n|\n||\n| |\n|||||\n|---\n{END}\n".encode(),
    "header-only": f"{BEGIN}\n{HEAD}\n{END}\n".encode(),
    "huge-line": f"{BEGIN}\n{HEAD}\n{SEP}\n| 1 | {'a-plan, ' * 20000}| | |\n{END}\n".encode(),
}


@pytest.mark.parametrize("case", list(GARBAGE))
def test_garbage_file_never_raises(tmp_path, case):
    """Охраняет «разбор не бросает исключений ни на каком тексте»: `read_text` (замена битых байтов), пустые срезы."""
    path = write_order(tmp_path, GARBAGE[case])
    items, findings = pp.build_queue([mem_plan("a-plan")], path)
    for it in items:
        assert list(it) == ITEM_KEYS
    assert all(f.code.startswith("OWNER_QUEUE_") and not f.blocking for f in findings)
    pp.parse_order(path)
    pp.parse_snapshot(path)


def test_fuzz_fragments_never_raise_and_keep_item_contract(tmp_path):
    """Те же гарантии на 400 случайных склейках фрагментов (зерно фиксировано)."""
    fragments = [
        BEGIN,
        END,
        HEAD,
        SEP,
        "| 1 | a-plan | 1.1 | x |",
        "| a-plan",
        "|",
        r"| \| | \|",
        "|---|:-:|",
        "## Снимок 2026-10-03",
        "### 4.1 Активные",
        "| [a-plan](../a-plan/plan.md) | Ж |",
        "Task 1.1",
        "\r",
        "﻿",
        "",
        "  ",
    ]
    rng = random.Random(61)
    path = tmp_path / "ORDER.md"
    plans = [mem_plan("a-plan", tasks=(("1.1", "done"), ("1.2", "pending")))]
    for _ in range(400):
        text = "\n".join(rng.choice(fragments) for _ in range(rng.randint(0, 14)))
        path.write_bytes(text.encode("utf-8"))
        items, findings = pp.build_queue(plans, path)
        assert [i["n"] for i in items] == list(range(1, len(items) + 1)), text
        assert all(list(i) == ITEM_KEYS for i in items), text
        assert all(f.code.startswith("OWNER_QUEUE_") and not f.blocking for f in findings), text
        pp.parse_order(path)
        pp.parse_snapshot(path)


def test_bom_and_crlf_block_at_the_very_start_of_the_file(tmp_path):
    """Охраняет `read_text(path)` (utf-8-sig, CRLF -> LF) в `parse_queue_block`: BOM перед первым маркером не прячет блок."""
    raw = b"\xef\xbb\xbf" + block("| 1 | a-plan | 1.1 | заметка |").replace("\n", "\r\n").encode("utf-8")
    items, findings = pp.build_queue([mem_plan("a-plan")], write_order(tmp_path, raw))
    assert items == [item(1, "task", "a-plan", "1.1", "заметка", True, False)]
    assert findings == []


# =========================================================================== блок невидим остальному скрипту


def test_cut_blanks_the_block_lines_and_keeps_line_numbers():
    """Охраняет `cut_queue_block`: строки блока и маркеры -> пустые строки (число строк то же, соседи не склеены)."""
    text = f"до\n{BEGIN}\n| x |\n{END}\nпосле"
    assert pp.cut_queue_block(text) == "до\n\n\n\nпосле"
    assert pp.cut_queue_block(text.replace(END, "")) == text.replace(END, "")  # нет end — не трогается
    assert pp.cut_queue_block(f"{BEGIN}\n{END}") == "\n"


def test_block_rows_are_invisible_to_parse_order_and_parse_snapshot_only_when_markers_are_valid(tmp_path):
    """Охраняет `read_order` в `parse_order` / `parse_snapshot`: ссылка в блоке не становится строкой §4.1 / «Снимка»."""
    inner = ["| [b-plan](../b-plan/plan.md) | Ж | s | n |", "| 9 | Ж | b-plan | | |"]
    base = ["## 4.1 Активные", "", "| План | Полоса |", "|---|---|", "| [a-plan](../a-plan/plan.md) | Ж |"]
    snap = ["", "## Снимок 2026-10-03 — x", "", "| # | Полоса | План |", "|---|---|---|", "| 1 | Ж | a-plan |"]
    valid = write_order(tmp_path, "\n".join([*base, BEGIN, *inner, END, *snap]))
    assert [r.name for r in pp.parse_order(valid)] == ["a-plan"]
    assert [(r.n, r.slugs) for r in pp.parse_snapshot(valid)[1]] == [(1, ["a-plan"])]
    broken = write_order(tmp_path, "\n".join([*base, BEGIN, *inner, *snap]))  # begin без end: блока нет
    assert [r.name for r in pp.parse_order(broken)] == ["a-plan", "b-plan"]
    # блок с собственной таблицей между заголовком «Снимка» и его таблицей: читается вторая, не таблица блока
    own = [
        "## Снимок 2026-10-03 — x",
        "",
        BEGIN,
        "| # | Полоса | План |",
        "|---|---|---|",
        "| 7 | Ж | b-plan |",
        END,
        *snap[3:],
    ]
    inside = write_order(tmp_path, "\n".join(own))
    assert [(r.n, r.slugs) for r in pp.parse_snapshot(inside)[1]] == [(1, ["a-plan"])]


# =========================================================================== блок прогресса: тексты прежние


PROGRESS_MISSING = (
    "нужна ровно одна пара маркеров <!-- progress:begin --> / <!-- progress:end --> отдельными строками, "
    "найдено: progress:begin 0, progress:end 0"
)


def test_progress_block_error_texts_are_byte_identical_and_ignore_queue_markers(tmp_path):
    """Охраняет `locate_block` / `sync_order` / `ORDER_BLOCK_MISSING`: их тексты и маркеры очереди не затронуты."""
    queue_only = f"# ORDER\n\n{block('| 1 | a-plan | | |')}"
    assert pp.locate_block(queue_only.split("\n")) == PROGRESS_MISSING
    assert pp.locate_block(["<!-- progress:end -->", "<!-- progress:begin -->"]) == (
        "нужна ровно одна пара маркеров <!-- progress:begin --> / <!-- progress:end --> отдельными строками, "
        "найдено: progress:begin 1, progress:end 1; progress:end стоит раньше progress:begin"
    )
    order = write_order(tmp_path, queue_only)
    code, message = pp.sync_order(order, [], [])
    assert (code, message) == (2, f"ошибка --sync-order: {order}: {PROGRESS_MISSING}")
    assert order.read_text(encoding="utf-8") == queue_only
    code, message = pp.sync_order(tmp_path / "net-takogo.md", [], [])
    assert (code, message) == (2, f"ошибка --sync-order: нет файла ORDER: {tmp_path / 'net-takogo.md'}")


def test_sync_order_cli_rewrites_only_progress_lines_and_keeps_queue_block_bytes(tmp_path):
    """Охраняет побайтную неизменность блока очереди при `--sync-order` (тот работает с сырыми байтами, не `read_order`)."""
    root = tmp_path / "r"
    (root / "plans" / "a-plan").mkdir(parents=True)
    (root / "plans" / "queue").mkdir(parents=True)
    (root / "plans" / "a-plan" / "plan.md").write_bytes(
        "# План\n\n## Порядок выполнения\n\n- Task 1.1: x [DONE]\n- Task 1.2: y [PENDING]\n".encode()
    )
    queue_block = block("| 1 | a-plan | 1.2 | CRLF-заметка |").replace("\n", "\r\n")
    order = root / "plans" / "queue" / "ORDER.md"
    order.write_bytes(
        f"# ORDER\r\n\r\n{queue_block}\r\n<!-- progress:begin -->\r\nстарое\r\n<!-- progress:end -->\r\n".encode()
    )
    cp = subprocess.run(
        [sys.executable, str(_MOD_PATH), "--root", str(root), "--sync-order"],
        capture_output=True,
        timeout=CALL_TIMEOUT,
        encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
    )
    assert cp.returncode == 0, (cp.stdout, cp.stderr)
    assert order.read_bytes().decode("utf-8") == (
        f"# ORDER\r\n\r\n{queue_block}\r\n<!-- progress:begin -->\r\n- a-plan — 1 из 2 · 50%\r\nв архиве: 0\r\n<!-- progress:end -->\r\n"
    )
