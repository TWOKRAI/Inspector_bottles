# ruff: noqa: E501  -- литералы-фикстуры и ожидания в одну строку, форматтер их не переносит
"""Приёмка Task 6.1 — слепые тесты блока `owner-queue` в ORDER.md и режима `--queue`.

Источник: plans/2026-10-02_plans-progress-dashboard/tasks/6.1.md, ред. 3 (DESIGN, ACCEPTANCE Q1-Q8).
Реализации `--queue` тестер не видел; из plans_progress.py читались только определения аргументов CLI.

Только CLI в subprocess (timeout на вызов): `plans_progress.py --root R [--order F] --queue | --check | --json |
--sync-order | --html F | --who`. Фикстура — обычный каталог без git (pytest tmp_path). Ожидания — литералы.

Договорённости чтения (в тексте задачи неоднозначно; выбрано строгое чтение):
- Q1 «печатает ровно ...»: сверяю json.loads, порядок ключей пункта и порядок ключа верхнего объекта; кроме того
  в T1 stdout побайтно равен `json.dumps(литерал, ensure_ascii=False, indent=2)` (DESIGN называет этот вызов).
- «текст находки называет `n`»: ищу `n` отдельным числом-токеном `(?<![\\w.])N(?![\\w.])` в строке находки.
  Как именно написано («пункт 2», «#2», «n=2») спецификация не говорит; токен — самое слабое честное чтение.
- «`OWNER_QUEUE_BLOCK` (число begin и end в тексте)»: оба числа есть в строке находки отдельными токенами.
- Q8: блок стоит в §4.1/§4.3 сразу под последней строкой таблицы, без пустой строки между ними (строже).
- Q8 `--sync-order`: «тот же блок прогресса» = текст между `<!-- progress:begin -->` и `<!-- progress:end -->`.
- Каждый отрицательный тест несёт положительный контроль в том же прогоне (соседний пункт с известным результатом).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
PROGRESS = REPO_ROOT / "scripts" / "plans_progress" / "plans_progress.py"
CALL_TIMEOUT = 60

BEGIN = "<!-- owner-queue:begin -->"
END = "<!-- owner-queue:end -->"
HEADER = "| # | План | Задача | Заметка |"
ITEM_KEYS = ["n", "kind", "plan", "task", "note", "known", "closed"]


# =========================================================================== фикстура


def plan_md(tasks: tuple[tuple[str, str], ...]) -> str:
    lines = ["# План", "", "- **После:** —", "", "## Порядок выполнения", ""]
    lines += [f"- Task {tid}: x [{status}]" for tid, status in tasks]
    return "\n".join(lines) + "\n"


PLANS = {
    "plans/a-plan/plan.md": plan_md((("1.1", "DONE"), ("1.2", "PENDING"))),
    "plans/2026-10-01_b-plan/plan.md": plan_md((("2.1", "PENDING"),)),
    "plans/c-plan/plan.md": plan_md((("3.1", "DONE"), ("3.2", "DONE"))),
    "plans/e-plan/plan.md": plan_md((("5.1", "PENDING"),)),
}


def sep_for(header: str) -> str:
    return "|" + "---|" * (len(header.strip().strip("|").split("|")))


def qblock(*rows: str, header: str = HEADER) -> str:
    return "\n".join([BEGIN, header, sep_for(header), *rows, END])


def order_text(block: str | None = None, where: str = "end", progress: bool = False) -> str:
    """ORDER.md: §4.1 (a-plan), §4.2 пуст, §4.3 (e-plan); блок — в конце, внутри §4.1 или внутри §4.3.

    b-plan (2026-10-01_b-plan) нет в §4.1-4.3 — он «вне списка». c-plan тоже вне списка, но закрыт по задачам.
    """

    def at(w: str) -> list[str]:
        return [block] if block is not None and where == w else []

    out = [
        "# Порядок работ и контроль планов",
        "",
        "## 4. Контроль планов",
        "",
        "### 4.1 Активные — в работе или следующие",
        "",
        "| План | Полоса | Статус | Следующий шаг |",
        "|---|---|---|---|",
        "| [a-plan](../a-plan/plan.md) | Ж | статус | шаг |",
        *at("in41"),
        "",
        "### 4.2 Ждут триггера — не трогать до условия",
        "",
        "| План | Остаток | Триггер |",
        "|---|---|---|",
        "",
        "### 4.3 Закрыты или поглощены — кандидаты в `_archive/`",
        "",
        "| План | Факт |",
        "|---|---|",
        "| [e-plan](../e-plan/plan.md) | DONE |",
        *at("in43"),
        "",
    ]
    if progress:
        out += ["<!-- progress:begin -->", "<!-- progress:end -->", ""]
    if block is not None and where == "end":
        out += [block, ""]
    return "\n".join(out)


def make_root(tmp_path: Path, name: str, order: str) -> Path:
    root = tmp_path / name
    for rel, text in {**PLANS, "plans/queue/ORDER.md": order}.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(text.encode("utf-8"))
    return root


def item(n, kind, plan, task, note, known, closed) -> dict:
    return {"n": n, "kind": kind, "plan": plan, "task": task, "note": note, "known": known, "closed": closed}


def queue_root(tmp_path: Path, name: str, *rows: str, header: str = HEADER) -> Path:
    return make_root(tmp_path, name, order_text(qblock(*rows, header=header)))


# =========================================================================== запуск CLI


def _run(root: Path, *flags: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROGRESS), "--root", str(root), *flags],
        capture_output=True,
        timeout=CALL_TIMEOUT,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
    )


def _out(cp: subprocess.CompletedProcess) -> str:
    return f"exit={cp.returncode}\nstdout={cp.stdout[:600]!r}\nstderr={cp.stderr[:600]!r}"


def queue(root: Path, *flags: str) -> subprocess.CompletedProcess:
    cp = _run(root, *flags, "--queue")
    assert cp.returncode == 0, f"--queue: {_out(cp)}"
    return cp


def items_of(cp: subprocess.CompletedProcess) -> list[dict]:
    data = json.loads(cp.stdout)
    assert list(data) == ["items"], f"ключи верхнего объекта: {list(data)}"
    for it in data["items"]:
        assert list(it) == ITEM_KEYS, f"порядок ключей пункта: {list(it)}"
    return data["items"]


def owner_lines(root: Path, *flags: str) -> tuple[int, list[str]]:
    cp = _run(root, "--check", *flags)
    text = cp.stdout + "\n" + cp.stderr
    return cp.returncode, [ln for ln in text.splitlines() if ln.startswith("OWNER_QUEUE_")]


def has_token(line: str, token: int | str) -> bool:
    return re.search(rf"(?<![\w.]){re.escape(str(token))}(?![\w.])", line) is not None


# =========================================================================== Q1


FIRST_CELL_SPELLINGS = ["b-plan", "2026-10-01_b-plan", "[b](../2026-10-01_b-plan/plan.md)"]


@pytest.mark.parametrize("first_cell", FIRST_CELL_SPELLINGS, ids=["slug", "full-name", "link"])
def test_q1_plan_and_task_items_literal_and_no_findings(tmp_path, first_cell):
    root = queue_root(
        tmp_path,
        "r",
        f"| 1 | {first_cell} | | сначала Б |",
        "| 2 | [a-plan](../a-plan/plan.md) | Task 1.2 | потом |",
    )
    expected = [
        item(1, "plan", "2026-10-01_b-plan", None, "сначала Б", True, False),
        item(2, "task", "a-plan", "1.2", "потом", True, False),
    ]
    cp = queue(root)
    assert items_of(cp) == expected
    assert cp.stdout.strip() == json.dumps({"items": expected}, ensure_ascii=False, indent=2)
    code, lines = owner_lines(root)
    assert code == 0 and lines == []


# =========================================================================== Q2


def _q2_root(tmp_path: Path, variant: str) -> tuple[Path, tuple[str, ...]]:
    if variant == "no-markers":
        # контроль: таблица с валидной строкой, но без маркеров — это не блок
        table = "\n".join([HEADER, sep_for(HEADER), "| 1 | a-plan | | |"])
        return make_root(tmp_path, "r", order_text(table)), ()
    return make_root(tmp_path, "r", order_text()), ("--order", str(tmp_path / "net-takogo-ORDER.md"))


@pytest.mark.parametrize("variant", ["no-markers", "missing-order"])
def test_q2_queue_is_empty_without_markers_or_order_file(tmp_path, variant):
    root, extra = _q2_root(tmp_path, variant)
    cp = queue(root, *extra)
    assert json.loads(cp.stdout) == {"items": []}


@pytest.mark.parametrize("variant", ["no-markers", "missing-order"])
def test_q2_check_has_no_owner_queue_lines_without_markers_or_order_file(tmp_path, variant):
    # зелёный уже на текущем коде: находок `OWNER_QUEUE_*` ещё нет вовсе; охраняет молчание проверки без блока
    root, extra = _q2_root(tmp_path, variant)
    code, lines = owner_lines(root, *extra)
    assert code == 0 and lines == []


# =========================================================================== Q3


def test_q3_closed_items_known_and_four_info_findings(tmp_path):
    root = queue_root(
        tmp_path,
        "r",
        "| 1 | a-plan | 1.1 | |",
        "| 2 | c-plan | | |",
        "| 3 | e-plan | | |",
        "| 4 | e-plan | 5.1 | |",
    )
    assert items_of(queue(root)) == [
        item(1, "task", "a-plan", "1.1", "", True, True),
        item(2, "plan", "c-plan", None, "", True, True),
        item(3, "plan", "e-plan", None, "", True, True),
        item(4, "task", "e-plan", "5.1", "", True, True),
    ]
    code, lines = owner_lines(root)
    assert code == 0, lines
    assert len(lines) == 4 and all(re.match(r"^OWNER_QUEUE_CLOSED ORDER\.md info\b", ln) for ln in lines), lines
    assert any("1.1" in ln for ln in lines) and any("c-plan" in ln for ln in lines), lines


# =========================================================================== Q4


Q4_CASES = {
    # id: (ячейки План|Задача, ожидаемый пункт n=2, код находки, токен в тексте находки)
    "unknown-slug": (
        "zz-plan | ",
        item(2, "plan", "zz-plan", None, "", False, False),
        "OWNER_QUEUE_UNKNOWN",
        "zz-plan",
    ),
    "unknown-link": (
        "[zz](../zz-plan/plan.md) | ",
        item(2, "plan", "zz-plan", None, "", False, False),
        "OWNER_QUEUE_UNKNOWN",
        "zz-plan",
    ),
    "unknown-task": ("a-plan | 9.9", item(2, "task", "a-plan", "9.9", "", False, False), "OWNER_QUEUE_UNKNOWN", "9.9"),
    "bad-task-id": ("zz-plan | abc", item(2, "task", "zz-plan", "abc", "", False, False), "OWNER_QUEUE_BAD", "abc"),
}


@pytest.mark.parametrize("case", list(Q4_CASES))
def test_q4_unknown_and_bad_rows_stay_in_queue_with_one_info_finding(tmp_path, case):
    cells, expected_item, code_name, token = Q4_CASES[case]
    # строка 1 — контроль: известный открытый пункт-план не даёт находки и не сбивает счёт
    root = queue_root(tmp_path, "r", "| 1 | a-plan | | |", f"| 2 | {cells} | |")
    assert items_of(queue(root)) == [item(1, "plan", "a-plan", None, "", True, False), expected_item]
    code, lines = owner_lines(root)
    assert code == 0, lines
    assert len(lines) == 1 and re.match(rf"^{code_name} ORDER\.md info\b", lines[0]), lines
    assert token in lines[0], lines
    assert has_token(lines[0], 2), f"в тексте находки нет n=2: {lines[0]!r}"


# =========================================================================== Q5


def test_q5_broken_rows_stay_in_queue_as_bad_with_known_false(tmp_path):
    root = queue_root(tmp_path, "r", "| 1 | | | x |", "| 2 | a-plan, c-plan | | |", "| 3 | a-plan | abc | |")
    assert items_of(queue(root)) == [
        item(1, "plan", "", None, "x", False, False),
        item(2, "plan", "a-plan, c-plan", None, "", False, False),
        item(3, "task", "a-plan", "abc", "", False, False),
    ]
    code, lines = owner_lines(root)
    assert code == 0, lines
    assert len(lines) == 3 and all(re.match(r"^OWNER_QUEUE_BAD ORDER\.md info\b", ln) for ln in lines), lines
    for n in (1, 2, 3):
        assert any(has_token(ln, n) for ln in lines), f"нет находки с n={n}: {lines}"


# =========================================================================== Q6


def _two(*parts: str) -> str:
    return "\n".join(parts)


TABLE = f"{HEADER}\n{sep_for(HEADER)}\n| 1 | a-plan | | |"
ONE_ITEM = [item(1, "plan", "a-plan", None, "", True, False)]
Q6_CASES = {
    # id: (текст блока, ожидаемые пункты, (число begin, число end) для OWNER_QUEUE_BLOCK или None — находок нет)
    "two-begin-one-end": (_two(BEGIN, TABLE, BEGIN, END), [], (2, 1)),
    "end-before-begin": (_two(END, TABLE, BEGIN), [], (1, 1)),
    "begin-without-end": (_two(BEGIN, TABLE), [], (1, 0)),
    "end-without-begin": (_two(TABLE, END), [], (0, 1)),
    "markers-inside-text": (
        _two("см. <!-- owner-queue:begin --> выше", TABLE, "см. <!-- owner-queue:end --> ниже"),
        [],
        None,
    ),
    "padded-markers-are-markers": (_two(f"  {BEGIN}  ", TABLE, f"\t{END} "), ONE_ITEM, None),
}


@pytest.mark.parametrize("case", list(Q6_CASES))
def test_q6_marker_combinations(tmp_path, case):
    text, expected, counts = Q6_CASES[case]
    root = make_root(tmp_path, "r", order_text(text))
    assert items_of(queue(root)) == expected
    code, lines = owner_lines(root)
    assert code == 0, lines
    if counts is None:
        assert lines == []
    else:
        assert len(lines) == 1 and re.match(r"^OWNER_QUEUE_BLOCK ORDER\.md info\b", lines[0]), lines
        nums = set(re.findall(r"(?<![\w.])\d+(?![\w.])", lines[0]))
        assert {str(counts[0]), str(counts[1])} <= nums, f"в тексте нет чисел begin/end {counts}: {lines[0]!r}"
    # контроль: исправный блок с теми же строками даёт пункт без находок
    ok_root = make_root(tmp_path, "ok", order_text(_two(BEGIN, TABLE, END)))
    assert items_of(queue(ok_root)) == ONE_ITEM
    assert owner_lines(ok_root) == (0, [])


# =========================================================================== Q7


Q1_ITEMS = [
    item(1, "plan", "2026-10-01_b-plan", None, "сначала Б", True, False),
    item(2, "task", "a-plan", "1.2", "потом", True, False),
]
REORDERED = "| Заметка | План | # | Задача |"
Q7_CASES = {
    # id: (шапка, строки, ожидаемые пункты, ожидается ли OWNER_QUEUE_BLOCK)
    "reordered-header": (
        REORDERED,
        ["| сначала Б | b-plan | 1 | |", "| потом | [a-plan](../a-plan/plan.md) | 2 | Task 1.2 |"],
        Q1_ITEMS,
        False,
    ),
    "hash-cells-are-ignored": (
        HEADER,
        ["| 5 | b-plan | | сначала Б |", "| 3 | [a-plan](../a-plan/plan.md) | Task 1.2 | потом |"],
        Q1_ITEMS,
        False,
    ),
    "blank-row-is-not-an-item": (
        HEADER,
        ["| 1 | b-plan | | сначала Б |", "|  |  |  |  |", "| 2 | [a-plan](../a-plan/plan.md) | Task 1.2 | потом |"],
        Q1_ITEMS,
        False,
    ),
    "no-plan-column": ("| # | Задача | Заметка |", ["| 1 | 1.2 | x |"], [], True),
}


@pytest.mark.parametrize("case", list(Q7_CASES))
def test_q7_columns_by_header_n_is_ordinal_and_blank_rows_skipped(tmp_path, case):
    header, rows, expected, block_finding = Q7_CASES[case]
    root = queue_root(tmp_path, "r", *rows, header=header)
    assert items_of(queue(root)) == expected
    code, lines = owner_lines(root)
    assert code == 0, lines
    if block_finding:
        assert len(lines) == 1 and re.match(r"^OWNER_QUEUE_BLOCK ORDER\.md info\b", lines[0]), lines
    else:
        assert lines == []


# =========================================================================== Q8


CONFLICTS = {
    "json": ("--json",),
    "html": ("--html", "{html}"),
    "check": ("--check",),
    "sync-order": ("--sync-order",),
    "who": ("--who",),
}


@pytest.mark.parametrize("mode", list(CONFLICTS))
def test_q8_queue_with_another_output_mode_is_exit_2_with_empty_stdout(tmp_path, mode):
    root = make_root(tmp_path, "r", order_text(qblock("| 1 | a-plan | | |"), progress=True))
    order = root / "plans/queue/ORDER.md"
    before = order.read_bytes()
    html_out = tmp_path / "page.html"
    flags = [f.format(html=html_out) for f in CONFLICTS[mode]]
    # контроль: сам по себе --queue принят (иначе exit 2 даёт argparse на неизвестный флаг, а не проверка сочетаний)
    assert items_of(queue(root)) == ONE_ITEM
    cp = _run(root, *flags, "--queue")
    assert cp.returncode == 2, _out(cp)
    assert "--queue" in cp.stderr, _out(cp)
    assert cp.stdout == "", _out(cp)
    assert order.read_bytes() == before, "ORDER.md изменён при отказе"
    assert not html_out.exists(), "страница записана при отказе"


def _normalize(text: str, root: Path) -> str:
    return text.replace(str(root), "R").replace(str(root).replace("\\", "/"), "R")


def _progress_block(order: Path) -> str:
    text = order.read_text(encoding="utf-8")
    m = re.search(r"<!-- progress:begin -->(.*?)<!-- progress:end -->", text, re.S)
    assert m, "в ORDER.md нет блока progress:begin…end"
    return m.group(1)


def test_q8_block_is_invisible_to_json_in_41_and_to_sync_order_in_43(tmp_path):
    block = qblock("| [b-plan](../2026-10-01_b-plan/plan.md) | | |", header="| План | Задача | Заметка |")
    # --json: блок внутри §4.1 после её таблицы
    with_41 = make_root(tmp_path, "j1", order_text(block, "in41"))
    without = make_root(tmp_path, "j0", order_text())
    cp1, cp0 = _run(with_41, "--json"), _run(without, "--json")
    assert cp1.returncode == 0 and cp0.returncode == 0, (_out(cp1), _out(cp0))
    assert json.loads(cp0.stdout), "контроль: --json без блока не пуст"
    assert _normalize(cp1.stdout, with_41) == _normalize(cp0.stdout, without)
    # --sync-order: тот же блок внутри §4.3 после её таблицы
    s1 = make_root(tmp_path, "s1", order_text(block, "in43", progress=True))
    s0 = make_root(tmp_path, "s0", order_text(progress=True))
    for r in (s1, s0):
        cp = _run(r, "--sync-order")
        assert cp.returncode == 0, _out(cp)
    b1 = _progress_block(s1 / "plans/queue/ORDER.md")
    b0 = _progress_block(s0 / "plans/queue/ORDER.md")
    assert "2026-10-01_b-plan" in b0 and "в архиве: 1" in b0, "контроль: блок прогресса без блока очереди"
    assert _normalize(b1, s1) == _normalize(b0, s0)
    assert BEGIN in (s1 / "plans/queue/ORDER.md").read_text(encoding="utf-8"), "--sync-order затёр блок очереди"


def test_q8_real_tree_queue_exits_zero_and_prints_items_list():
    cp = _run(REPO_ROOT, "--queue")
    assert cp.returncode == 0, _out(cp)
    data = json.loads(cp.stdout)
    assert isinstance(data, dict) and isinstance(data.get("items"), list), cp.stdout[:300]
