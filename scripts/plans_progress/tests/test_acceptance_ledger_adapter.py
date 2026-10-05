# ruff: noqa: E501  -- литералы-ожидания и фикстуры планов в одну строку
"""Приёмка Task 4.1 «ledger — адаптер над analyze_plan» — слепые тесты (RED до кода).

Источник правды — `plans/2026-10-02_plans-progress-dashboard/tasks/4.1.md` (DESIGN + ACCEPTANCE 1-11).
Строки 12-13 — проверки лида (прежние тесты в обоих режимах; живое дерево), здесь их нет.

Два режима `summarize_plan` (scripts/plans_ledger.py):
  * «адаптер»: у корня проекта есть `<корень>/scripts/plans_progress/plans_progress.py` и он грузится;
  * «прежний»: иначе — нынешний код без изменений.
Фикстуры строят «адаптер» копией НАСТОЯЩЕГО plans_progress.py в `<tmp корень>/scripts/plans_progress/`.
Сам скрипт ledger лежит в worktree, где такой файл тоже есть: поэтому тесты «корень без парсера» заодно
проверяют правило «ищем по корню проекта, а не по месту скрипта».

Все ожидаемые числа — литералы. Для `fixtures/plans_formats/` они посчитаны руками по эталону
«Формат задачи» и сверены с `plans_progress.py --json` (оракул из строки 1 приёмки); для
`fixtures/real/` — те же числа печатает прежний ledger (10/21, 5/20), они совпадают с оракулом.

Вызовы — только в subprocess с timeout=60: зависший скрипт не вешает набор. `summarize_plan` дергается
через `python -c` (CLI не видит архивные планы и пустой `paths`); для CLI-строк — `status`/`close`/`add`.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
LEDGER = REPO_ROOT / "scripts" / "plans_ledger.py"
SEED_LEDGER = REPO_ROOT / ".claude" / "plugins" / "core" / "scripts" / "plans_ledger.py"
MANIFEST = REPO_ROOT / ".claude" / ".delivery-manifest.json"
PARSER = REPO_ROOT / "scripts" / "plans_progress" / "plans_progress.py"
HERE = Path(__file__).resolve().parent
FORMATS = HERE / "fixtures" / "plans_formats"
REAL = HERE / "fixtures" / "real"

CALL_TIMEOUT = 60


# --------------------------------------------------------------------------- хелперы


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, *args],
        capture_output=True,
        timeout=CALL_TIMEOUT,
        env=_env(),
        encoding="utf-8",
        errors="replace",
    )


def _nl(text: str) -> str:
    return text.replace("\r\n", "\n")


def install_parser(root: Path, text: str | None = None) -> Path:
    """Кладёт plans_progress.py в `<root>/scripts/plans_progress/` (копия настоящего или `text`)."""
    dst = root / "scripts" / "plans_progress" / "plans_progress.py"
    dst.parent.mkdir(parents=True, exist_ok=True)
    if text is None:
        shutil.copyfile(PARSER, dst)
    else:
        dst.write_bytes(text.encode("utf-8"))
    return dst


def parser_text() -> str:
    return _nl(PARSER.read_text(encoding="utf-8"))


def copy_plans(src_plans: Path, root: Path) -> Path:
    shutil.copytree(src_plans, root / "plans", dirs_exist_ok=True)
    return root


def copy_formats(root: Path) -> Path:
    """plans_formats/plans + архивный план в `plans/_archive/2026-Q3/` (каталог `_archive/` в .gitignore,
    поэтому исходник лежит в `archive_src/` и раскладывается при копировании)."""
    copy_plans(FORMATS / "plans", root)
    arch = root / "plans" / "_archive" / "2026-Q3"
    arch.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(FORMATS / "archive_src" / "2026-07-07_archived.md", arch / "2026-07-07_archived.md")
    return root


def fixture_text(rel: str) -> str:
    return _nl((FORMATS / rel).read_text(encoding="utf-8"))


DRIVER = r"""
import importlib.util, json, sys
from pathlib import Path
spec = importlib.util.spec_from_file_location("plans_ledger_under_test", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
sys.modules["plans_ledger_under_test"] = mod
spec.loader.exec_module(mod)

def as_dict(s):
    return {"done": s.done, "total": s.total, "dropped": s.dropped, "unknown": s.unknown,
            "counted": s.counted, "phase": s.phase, "open_tasks": list(s.open_tasks)}

def summ(*paths):
    return as_dict(mod.summarize_plan([Path(p) for p in paths]))

def plan(p):
    return as_dict(mod.summarize_plan(mod.discover_plan_files(Path(p))))
"""


def drive(body: str, *args: str) -> tuple[object, str]:
    """Выполняет `body` после DRIVER в свежем процессе; тело печатает JSON. -> (JSON, stderr)."""
    cp = _run(["-c", DRIVER + "\n" + body, str(LEDGER), *args])
    assert cp.returncode == 0, f"процесс упал: exit {cp.returncode}\nstderr={cp.stderr[-1500:]!r}"
    return json.loads(cp.stdout), cp.stderr


def summarize(*paths: Path) -> tuple[list[dict], str]:
    """summarize_plan(discover_plan_files(p)) для каждого пути, в одном процессе. -> ([числа], stderr)."""
    out, err = drive(
        "print(json.dumps([plan(p) for p in json.loads(sys.argv[2])]))",
        json.dumps([str(p) for p in paths]),
    )
    return out, err  # type: ignore[return-value]


def oracle(root: Path) -> dict[str, dict]:
    """analyze_plan через CLI копии парсера в корне: имя плана (без .md) -> запись --json."""
    cp = _run([str(root / "scripts" / "plans_progress" / "plans_progress.py"), "--root", str(root), "--json"])
    assert cp.returncode == 0, f"оракул упал: {cp.stderr[-800:]!r}"
    return {rec["plan"][:-3] if rec["plan"].endswith(".md") else rec["plan"]: rec for rec in json.loads(cp.stdout)}


def stderr_lines(text: str) -> list[str]:
    return [ln for ln in text.splitlines() if ln.strip()]


def mentions_path(line: str, path: Path) -> bool:
    return any(form in line for form in (str(path), str(path.resolve()), path.as_posix(), path.resolve().as_posix()))


# --------------------------------------------------------------------------- фикстуры pytest


@pytest.fixture
def fmt_parser_root(tmp_path: Path) -> Path:
    """Корень «адаптер»: набор plans_formats + копия парсера."""
    root = copy_formats(tmp_path / "fmt_p")
    install_parser(root)
    return root


@pytest.fixture
def fmt_plain_root(tmp_path: Path) -> Path:
    """Корень «прежний»: тот же набор, парсера нет."""
    return copy_formats(tmp_path / "fmt_plain")


@pytest.fixture
def real_parser_root(tmp_path: Path) -> Path:
    root = copy_plans(REAL / "plans", tmp_path / "real_p")
    install_parser(root)
    return root


@pytest.fixture
def rooted(make_root):
    """rooted(files, parser=True) -> корень; parser=True кладёт настоящий парсер, строка -> его замена."""

    def _make(files: dict[str, str], parser: bool | str = True) -> Path:
        root = make_root(files)
        if parser is True:
            install_parser(root)
        elif parser:
            install_parser(root, parser)
        return root

    return _make


# --------------------------------------------------------------------------- 1. числа адаптера = числа analyze_plan

# (идентификатор, путь внутри корня, имя в --json оракула, литералы)
FMT_CASES = [
    # пункты раздела порядка: 1 DONE, PENDING, SKIPPED (снята), пункт без статуса (unknown)
    (
        "order",
        "plans/2026-07-01_order.md",
        "2026-07-01_order",
        {"done": 1, "total": 4, "dropped": 1, "unknown": 1, "counted": 2, "phase": None, "open_tasks": ["1.2", "1.4"]},
    ),
    # заголовки `#### Task N.M — имя ✅ DONE`; у 1.2 статуса нет -> pending
    (
        "tail",
        "plans/2026-07-02_tail.md",
        "2026-07-02_tail",
        {"done": 2, "total": 3, "dropped": 0, "unknown": 0, "counted": 3, "phase": None, "open_tasks": ["1.2"]},
    ),
    # `- **Статус:** DONE|BLOCKED|DEFERRED` в теле заголовка
    (
        "bodystatus",
        "plans/2026-07-03_bodystatus.md",
        "2026-07-03_bodystatus",
        {"done": 1, "total": 3, "dropped": 1, "unknown": 0, "counted": 2, "phase": None, "open_tasks": ["2.2"]},
    ),
    # таблица `✓ T…`
    (
        "table",
        "plans/2026-07-04_table.md",
        "2026-07-04_table",
        {"done": 2, "total": 3, "dropped": 0, "unknown": 0, "counted": 3, "phase": None, "open_tasks": ["T1.2"]},
    ),
    # каталог, задачи только в tasks/<id>.md
    (
        "dirtasks",
        "plans/2026-07-05_dirtasks",
        "2026-07-05_dirtasks",
        {"done": 1, "total": 3, "dropped": 1, "unknown": 0, "counted": 2, "phase": None, "open_tasks": ["1.2"]},
    ),
    # каталог, задачи в phase-N-slug.md; открытая 2.1 лежит в phase-2-ui.md -> «phase 2» (прежнее правило фазы)
    (
        "phased",
        "plans/2026-07-06_phased",
        "2026-07-06_phased",
        {"done": 1, "total": 2, "dropped": 0, "unknown": 0, "counted": 2, "phase": "phase 2", "open_tasks": ["2.1"]},
    ),
    # план в _archive/<квартал>/ (CLI его не видит — только импорт)
    (
        "archive",
        "plans/_archive/2026-Q3/2026-07-07_archived.md",
        "2026-07-07_archived",
        {"done": 2, "total": 2, "dropped": 0, "unknown": 0, "counted": 2, "phase": None, "open_tasks": []},
    ),
]
FMT_IDS = [c[0] for c in FMT_CASES]

# реальные снимки; литералы совпадают с `status` прежнего ledger (10/21 phase 1; 5/20 phase 2)
REAL_CASES = [
    (
        "gui-service",
        "plans/2026-09-22_gui-service",
        "2026-09-22_gui-service",
        {"done": 10, "total": 21, "dropped": 0, "unknown": 0, "counted": 21, "phase": "phase 1"},
    ),
    (
        "layer-render",
        "plans/layer-render",
        "layer-render",
        {"done": 5, "total": 20, "dropped": 0, "unknown": 0, "counted": 20, "phase": "phase 2"},
    ),
]


@pytest.mark.parametrize("case", FMT_CASES, ids=FMT_IDS)
def test_adapter_formats_match_literals(fmt_parser_root, case):
    # строка 1: корень с парсером -> done/counted/dropped/unknown (и total, phase, open_tasks) как литерал
    _, rel, _, expected = case
    (got,), err = summarize(fmt_parser_root / rel)
    assert got == expected, f"{rel}: {got} != {expected}"
    assert err == "", f"успешная загрузка парсера не пишет в stderr: {err!r}"


@pytest.mark.parametrize("case", FMT_CASES, ids=FMT_IDS)
def test_adapter_formats_match_analyze_plan_oracle(fmt_parser_root, case):
    # строка 1, формулировка приёмки: done/counted/dropped/unknown == analyze_plan.done/total/dropped/unknown
    _, rel, key, _ = case
    (got,), _ = summarize(fmt_parser_root / rel)
    rec = oracle(fmt_parser_root)[key]
    assert (got["done"], got["counted"], got["dropped"], got["unknown"]) == (
        rec["done"],
        rec["total"],
        rec["dropped"],
        rec["unknown"],
    )


@pytest.mark.parametrize("case", REAL_CASES, ids=[c[0] for c in REAL_CASES])
def test_adapter_real_snapshots_match_literals(real_parser_root, case):
    _, rel, _, expected = case
    (got,), err = summarize(real_parser_root / rel)
    assert {k: got[k] for k in expected} == expected
    assert err == ""


@pytest.mark.parametrize("case", REAL_CASES, ids=[c[0] for c in REAL_CASES])
def test_adapter_real_snapshots_match_analyze_plan_oracle(real_parser_root, case):
    _, rel, key, _ = case
    (got,), _ = summarize(real_parser_root / rel)
    rec = oracle(real_parser_root)[key]
    assert (got["done"], got["counted"], got["dropped"], got["unknown"]) == (
        rec["done"],
        rec["total"],
        rec["dropped"],
        rec["unknown"],
    )


def _status_counts(stdout: str) -> tuple[dict[str, tuple[int, int]], dict[str, tuple[int, int]]]:
    """(строки планов `<ключ>: N/M, `, находки MISSING_ROW `(N/M tasks)`)."""
    plans: dict[str, tuple[int, int]] = {}
    missing: dict[str, tuple[int, int]] = {}
    for ln in _nl(stdout).splitlines():
        m = re.match(r"^(\S+): (\d+)/(\d+), ", ln)
        if m:
            plans[m.group(1)] = (int(m.group(2)), int(m.group(3)))
        m = re.match(r"^WARN MISSING_ROW (\S+): plan has no ledger row \((\d+)/(\d+) tasks\)", ln)
        if m:
            missing[m.group(1)] = (int(m.group(2)), int(m.group(3)))
    return plans, missing


def test_adapter_status_cli_prints_counted_and_total_of_analyze_plan(fmt_parser_root, ledger):
    # CLI-путь: `status` печатает done/counted адаптера, а MISSING_ROW — done/total (= len(tasks), дубль не склеивается)
    cp = ledger.status(fmt_parser_root)
    assert cp.returncode == 0, cp.stderr
    plans, missing = _status_counts(cp.stdout)
    assert plans == {
        "2026-07-01_order.md": (1, 2),
        "2026-07-02_tail.md": (2, 3),
        "2026-07-03_bodystatus.md": (1, 2),
        "2026-07-04_table.md": (2, 3),
        "2026-07-05_dirtasks/plan.md": (1, 2),
        "2026-07-06_phased/plan.md": (1, 2),
    }
    assert missing == {
        "2026-07-01_order.md": (1, 4),
        "2026-07-02_tail.md": (2, 3),
        "2026-07-03_bodystatus.md": (1, 3),
        "2026-07-04_table.md": (2, 3),
        "2026-07-05_dirtasks/plan.md": (1, 3),
        "2026-07-06_phased/plan.md": (1, 2),
    }


def test_adapter_phase_comes_from_phase_file_of_first_open_task(fmt_parser_root, ledger):
    # ИНТЕРПРЕТАЦИЯ тестера (строка про `phase` в DESIGN): первая открытая 2.1 лежит в phase-2-ui.md -> «phase 2».
    # Прежний ledger печатает здесь «phase 1» (первая НЕзакрытая по порядку файлов).
    cp = ledger.status(fmt_parser_root)
    assert "2026-07-06_phased/plan.md: 1/2, phase 2, ledger status (no row)" in _nl(cp.stdout)


# --------------------------------------------------------------------------- 2. таблица `✓ T…`

TABLE_PLAN = "# T\n\n| ✓ T1.1 | a |\n| T1.2 | b |\n"


def test_table_adapter_counts_one_of_two(rooted, ledger):
    root = rooted({"plans/2026-07-11_tab.md": TABLE_PLAN})
    assert ledger.counts(root, "2026-07-11_tab") == (1, 2)


def test_table_without_parser_keeps_zero_of_zero(rooted, ledger):
    root = rooted({"plans/2026-07-11_tab.md": TABLE_PLAN}, parser=False)
    assert ledger.counts(root, "2026-07-11_tab") == (0, 0)


# --------------------------------------------------------------------------- 3. каталог с tasks/<id>.md

DIR_PLAN_FILES = {
    "plans/2026-07-12_dt/plan.md": "# P\n\nБез раздела порядка и без заголовков Task.\n",
    "plans/2026-07-12_dt/tasks/1.1.md": "# Task 1.1: a\n\n- **Статус:** DONE\n",
}


def test_dir_plan_with_task_file_adapter_counts_one_of_one(rooted, ledger):
    root = rooted(DIR_PLAN_FILES)
    assert ledger.counts(root, "2026-07-12_dt") == (1, 1)


def test_dir_plan_with_task_file_without_parser_keeps_zero_of_one(rooted, ledger):
    root = rooted(DIR_PLAN_FILES, parser=False)
    assert ledger.counts(root, "2026-07-12_dt") == (0, 1)


CONTROL_FILES = {
    "plans/2026-07-13_ctl/plan.md": "# P\n\n## Порядок выполнения\n\n- Task 1.1: a\n",
    "plans/2026-07-13_ctl/tasks/1.1.md": "# Task 1.1: a\n\n- **Статус:** DONE\n",
}


@pytest.mark.parametrize("parser", [True, False], ids=["adapter", "legacy"])
def test_control_item_without_status_is_unknown_zero_of_zero(rooted, ledger, parser):
    # контроль: раздел порядка задаёт набор; пункт без статуса -> unknown, 0/0 в обоих режимах
    # (даже если tasks/1.1.md говорит DONE: пункт раздела порядка главнее файла задачи)
    root = rooted(CONTROL_FILES, parser=parser)
    assert ledger.counts(root, "2026-07-13_ctl") == (0, 0)
    (got,), _ = summarize(root / "plans" / "2026-07-13_ctl")
    assert (got["done"], got["unknown"], got["counted"], got["total"]) == (0, 1, 0, 1)


# --------------------------------------------------------------------------- 4. close фикстуры tpc

TPC_REL = "2026-07-16_tpc.md"


def _tpc_files() -> dict[str, str]:
    return {
        f"plans/{TPC_REL}": fixture_text(f"close_tpc/plans/{TPC_REL}"),
        "plans/README.md": fixture_text("close_tpc/plans/README.md"),
    }


def test_close_tpc_adapter_archives_into_quarter(make_git_root, ledger):
    files = _tpc_files() | {"scripts/plans_progress/plans_progress.py": parser_text()}
    root = make_git_root(files)
    cp = ledger.close(root, TPC_REL)
    assert cp.returncode == 0, f"exit {cp.returncode}\nstdout={cp.stdout!r}\nstderr={cp.stderr!r}"
    assert (root / "plans" / "_archive" / "2026-Q3" / TPC_REL).is_file()
    assert not (root / "plans" / TPC_REL).exists()


def test_close_tpc_without_parser_refuses_zero_of_three(make_git_root, ledger):
    root = make_git_root(_tpc_files())
    cp = ledger.close(root, TPC_REL)
    assert cp.returncode == 1, f"exit {cp.returncode}\nstdout={cp.stdout!r}\nstderr={cp.stderr!r}"
    assert cp.stderr.startswith("refused: plans/2026-07-16_tpc.md is not done (0/3"), cp.stderr
    assert (root / "plans" / TPC_REL).is_file()


# --------------------------------------------------------------------------- 5. корень без парсера: stdout `status` — литерал

# Снят тестером на a92e603fd (код ledger тот же, что на f3ac41aec) командой
# `python scripts/plans_ledger.py status --root <корень с plans_formats/plans без парсера>`;
# CRLF консоли заменён на LF. Копия вставлена литералом, git во время теста не зовётся.
LEGACY_STATUS_STDOUT = (
    "2026-07-01_order.md: 1/2, —, ledger status (no row)\n"
    "2026-07-02_tail.md: 0/3, —, ledger status (no row)\n"
    "2026-07-03_bodystatus.md: 0/3, —, ledger status (no row)\n"
    "2026-07-04_table.md: 0/0, —, ledger status (no row)\n"
    "2026-07-05_dirtasks/plan.md: 0/3, —, ledger status (no row)\n"
    "2026-07-06_phased/plan.md: 0/2, phase 1, ledger status (no row)\n"
    "archived rows: 0\n"
    "WARN MISSING_ROW 2026-07-01_order.md: plan has no ledger row (1/4 tasks)\n"
    "WARN MISSING_ROW 2026-07-02_tail.md: plan has no ledger row (0/3 tasks)\n"
    "WARN MISSING_ROW 2026-07-03_bodystatus.md: plan has no ledger row (0/3 tasks)\n"
    "WARN MISSING_ROW 2026-07-04_table.md: plan has no ledger row (0/0 tasks)\n"
    "WARN MISSING_ROW 2026-07-05_dirtasks/plan.md: plan has no ledger row (0/3 tasks)\n"
    "WARN MISSING_ROW 2026-07-06_phased/plan.md: plan has no ledger row (0/2 tasks)\n"
)


def test_legacy_status_stdout_is_byte_stable_without_parser(fmt_plain_root, ledger):
    # скрипт лежит в worktree, где парсер ЕСТЬ; корень без парсера -> прежний режим, вывод не меняется
    cp = ledger.status(fmt_plain_root)
    assert cp.returncode == 0, cp.stderr
    assert _nl(cp.stdout) == LEGACY_STATUS_STDOUT
    assert cp.stderr == ""


# --------------------------------------------------------------------------- 6. неудача загрузки -> прежний + одна строка stderr

BROKEN_SYNTAX = "this is not python LEAKED_SOURCE_MARKER\n"
TWO_PLANS = {
    "plans/2026-07-02_tail.md": fixture_text("plans/2026-07-02_tail.md"),
    "plans/2026-07-04_table.md": fixture_text("plans/2026-07-04_table.md"),
}


def test_broken_module_falls_back_with_exactly_one_stderr_line(rooted, ledger):
    root = rooted(TWO_PLANS, parser=BROKEN_SYNTAX)
    mod = root / "scripts" / "plans_progress" / "plans_progress.py"
    cp = ledger.status(root)
    assert cp.returncode == 0, f"exit {cp.returncode}: {cp.stderr!r}"
    plans, _ = _status_counts(cp.stdout)
    assert plans == {"2026-07-02_tail.md": (0, 3), "2026-07-04_table.md": (0, 0)}, "два плана считаются прежним кодом"
    lines = stderr_lines(cp.stderr)
    assert len(lines) == 1, f"ровно одна строка stderr на процесс и корень, получено {len(lines)}: {cp.stderr!r}"
    assert mentions_path(lines[0], mod), f"в строке нет пути модуля {mod}: {lines[0]!r}"
    assert "SyntaxError" in lines[0]
    assert "LEAKED_SOURCE_MARKER" not in cp.stderr, "строка исходника не выводится"


def test_missing_module_leaves_stderr_empty(rooted, ledger):
    root = rooted(TWO_PLANS, parser=False)
    cp = ledger.status(root)
    assert cp.returncode == 0
    assert cp.stderr == ""


def test_load_failure_prints_exception_class_but_not_its_text(rooted):
    text = parser_text() + '\nraise RuntimeError("TEXT_MARKER_BOOM")\n'
    root = rooted(TWO_PLANS, parser=text)
    mod = root / "scripts" / "plans_progress" / "plans_progress.py"
    _, err = summarize(root / "plans" / "2026-07-02_tail.md")
    lines = stderr_lines(err)
    assert len(lines) == 1, err
    assert mentions_path(lines[0], mod) and "RuntimeError" in lines[0]
    assert "TEXT_MARKER_BOOM" not in err, "текст исключения не выводится"


def test_load_failure_is_cached_per_module_path_one_line_per_root(rooted):
    # два корня с битым модулем в одном процессе: по строке на корень, повтор корня молчит
    root1 = rooted({"plans/2026-07-02_tail.md": TWO_PLANS["plans/2026-07-02_tail.md"]}, parser=BROKEN_SYNTAX)
    root2 = rooted({"plans/2026-07-02_tail.md": TWO_PLANS["plans/2026-07-02_tail.md"]}, parser=BROKEN_SYNTAX)
    p1, p2 = root1 / "plans" / "2026-07-02_tail.md", root2 / "plans" / "2026-07-02_tail.md"
    got, err = summarize(p1, p2, p1, p2, p1)
    assert [g["done"] for g in got] == [0, 0, 0, 0, 0], "прежний режим на всех вызовах"
    lines = stderr_lines(err)
    assert len(lines) == 2, f"две строки (по корню), получено {len(lines)}: {err!r}"
    m1 = root1 / "scripts" / "plans_progress" / "plans_progress.py"
    m2 = root2 / "scripts" / "plans_progress" / "plans_progress.py"
    assert sum(mentions_path(ln, m1) for ln in lines) == 1
    assert sum(mentions_path(ln, m2) for ln in lines) == 1


def test_failing_load_is_executed_once_per_process(rooted, tmp_path):
    counter = tmp_path / "fail_counter.txt"
    text = parser_text() + f'\nopen({str(counter)!r}, "a").write("x")\nraise RuntimeError("boom")\n'
    root = rooted(TWO_PLANS, parser=text)
    p = root / "plans" / "2026-07-02_tail.md"
    q = root / "plans" / "2026-07-04_table.md"
    summarize(p, q, p, q)
    assert (counter.read_text() if counter.exists() else "") == "x", (
        "неудача кэшируется на путь модуля: exec_module один раз"
    )


def test_successful_load_is_executed_once_per_process(rooted, tmp_path):
    counter = tmp_path / "ok_counter.txt"
    text = parser_text() + f'\nopen({str(counter)!r}, "a").write("x")\n'
    root = rooted(TWO_PLANS, parser=text)
    p = root / "plans" / "2026-07-02_tail.md"
    q = root / "plans" / "2026-07-04_table.md"
    got, err = summarize(p, q, p, q)
    assert [(g["done"], g["counted"]) for g in got] == [(2, 3), (2, 3), (2, 3), (2, 3)]
    assert err == ""
    assert (counter.read_text() if counter.exists() else "") == "x", (
        "успех кэшируется на путь модуля: exec_module один раз"
    )


def test_two_roots_with_different_modules_do_not_share_one_loaded_module(rooted):
    # модуль регистрируется под именем, уникальным для пути: второй корень не получает первый модуль
    patch = (
        "\n_orig_analyze = analyze_plan\n"
        "def analyze_plan(*a, **k):\n"
        "    p = _orig_analyze(*a, **k)\n"
        "    p.tasks = []\n"
        "    return p\n"
    )
    plan_text = TWO_PLANS["plans/2026-07-02_tail.md"]
    root1 = rooted({"plans/2026-07-02_tail.md": plan_text})
    root2 = rooted({"plans/2026-07-02_tail.md": plan_text}, parser=parser_text() + patch)
    p1, p2 = root1 / "plans" / "2026-07-02_tail.md", root2 / "plans" / "2026-07-02_tail.md"
    got, err = summarize(p1, p2, p1)
    assert [(g["done"], g["total"]) for g in got] == [(2, 3), (0, 0), (2, 3)]
    assert err == ""


def test_analyze_plan_exception_on_one_plan_falls_back_for_that_plan_only(rooted):
    patch = (
        "\n_orig_analyze = analyze_plan\n"
        "def analyze_plan(name, main, plan_dir, rel, archived):\n"
        '    if "2026-07-04_table" in str(main):\n'
        '        raise ZeroDivisionError("PLAN_EXC_TEXT")\n'
        "    return _orig_analyze(name, main, plan_dir, rel, archived)\n"
    )
    root = rooted(TWO_PLANS, parser=parser_text() + patch)
    got, err = summarize(root / "plans" / "2026-07-02_tail.md", root / "plans" / "2026-07-04_table.md")
    assert (got[0]["done"], got[0]["counted"]) == (2, 3), "остальные планы — адаптером"
    assert (got[1]["done"], got[1]["counted"]) == (0, 0), "упавший план — прежним кодом (таблицу он не знает)"
    lines = stderr_lines(err)
    assert len(lines) == 1, err
    assert "2026-07-04_table" in lines[0] and "ZeroDivisionError" in lines[0]


# --------------------------------------------------------------------------- 7. пустой paths, архив, каталог только с tasks/

EMPTY = {"done": 0, "total": 0, "dropped": 0, "unknown": 0, "counted": 0, "phase": None, "open_tasks": []}


def test_empty_paths_gives_empty_summary_without_exception():
    got, _ = drive("print(json.dumps(summ()))")
    assert got == EMPTY


def test_archived_plan_by_import_counts_through_adapter(fmt_parser_root):
    (got,), err = summarize(fmt_parser_root / "plans" / "_archive" / "2026-Q3" / "2026-07-07_archived.md")
    assert got == FMT_CASES[6][3]
    assert err == ""


def test_archived_plan_without_parser_keeps_legacy_zero_of_two(fmt_plain_root):
    (got,), err = summarize(fmt_plain_root / "plans" / "_archive" / "2026-Q3" / "2026-07-07_archived.md")
    assert (got["done"], got["total"], got["open_tasks"]) == (0, 2, ["1.1", "1.2"])
    assert err == ""


TASKS_ONLY = {
    "plans/2026-07-08_t/tasks/1.1.md": "# Task 1.1: a\n\n- **Статус:** DONE\n",
    "plans/2026-07-08_t/tasks/1.2.md": "# Task 1.2: b\n\n- **Статус:** PENDING\n",
}


def test_tasks_only_dir_adapter_counts_like_analyze_plan_on_plan_dir(rooted):
    root = rooted(TASKS_ONLY)
    (by_dir,), err = summarize(root / "plans" / "2026-07-08_t")
    expected = {"done": 1, "total": 2, "dropped": 0, "unknown": 0, "counted": 2, "phase": None, "open_tasks": ["1.2"]}
    assert by_dir == expected
    assert err == ""
    # те же файлы явным списком paths: plan_dir — родитель tasks/, main = plan_dir/plan.md (нет на диске)
    explicit, _ = drive(
        "print(json.dumps(summ(*json.loads(sys.argv[2]))))",
        json.dumps(
            [
                str(root / "plans" / "2026-07-08_t" / "tasks" / "1.1.md"),
                str(root / "plans" / "2026-07-08_t" / "tasks" / "1.2.md"),
            ]
        ),
    )
    assert explicit == expected


def test_tasks_only_dir_close_refusal_shows_adapter_count(rooted, ledger):
    root = rooted(TASKS_ONLY)
    cp = ledger.close(root, "2026-07-08_t")
    assert cp.returncode == 1, f"exit {cp.returncode}: {cp.stdout!r} {cp.stderr!r}"
    assert "(1/2" in cp.stderr, cp.stderr


def test_tasks_only_dir_close_refusal_without_parser_shows_legacy_count(rooted, ledger):
    root = rooted(TASKS_ONLY, parser=False)
    cp = ledger.close(root, "2026-07-08_t")
    assert cp.returncode == 1, f"exit {cp.returncode}: {cp.stdout!r} {cp.stderr!r}"
    assert "(0/2" in cp.stderr, cp.stderr


def test_plan_outside_any_plans_directory_uses_legacy_mode_without_noise(rooted):
    # «нет предка plans» -> прежний режим (числа прежнего кода), не исключение и не строка в stderr
    root = rooted({"other/2026-07-02_tail.md": TWO_PLANS["plans/2026-07-02_tail.md"]})
    (got,), err = summarize(root / "other" / "2026-07-02_tail.md")
    assert (got["done"], got["total"]) == (0, 3)
    assert err == ""


# --------------------------------------------------------------------------- 8. фаза

PHASE_PLAN = "# P\n\n## Порядок выполнения\n\n### Phase 1\n\n- Task 1.1: a\n\n### Phase 2\n\n- Task 2.1: b [PENDING]\n"


@pytest.mark.parametrize("parser", [True, False], ids=["adapter", "legacy"])
def test_phase_is_two_in_both_modes(rooted, ledger, parser):
    root = rooted({"plans/2026-07-09_ph/plan.md": PHASE_PLAN}, parser=parser)
    cp = ledger.status(root)
    assert cp.returncode == 0, cp.stderr
    assert "2026-07-09_ph/plan.md: 0/1, phase 2, ledger status (no row)" in _nl(cp.stdout)


@pytest.mark.parametrize("parser", [True, False], ids=["adapter", "legacy"])
def test_phase_json_literals_in_both_modes(rooted, ledger, parser):
    root = rooted({"plans/2026-07-09_ph/plan.md": PHASE_PLAN}, parser=parser)
    cp = ledger.status(root, "--json")
    assert cp.returncode == 0, cp.stderr
    comp = json.loads(cp.stdout)["rows"][0]["computed"]
    assert comp == {"done": 0, "total": 2, "phase": "phase 2", "open_tasks": ["1.1", "2.1"], "counted": 1}


# --------------------------------------------------------------------------- 9. дубль id

DUP_PLAN = "# D\n\n## Порядок выполнения\n\n- Task 1.1: a [DONE]\n- Task 1.1: a [PENDING]\n"


def _dup_computed(root: Path, ledger) -> dict:
    cp = ledger.status(root, "--json")
    assert cp.returncode == 0, cp.stderr
    return json.loads(cp.stdout)["rows"][0]["computed"]


def test_duplicate_id_adapter_counts_both_items_and_lists_id_once(rooted, ledger):
    root = rooted({"plans/2026-07-10_dup.md": DUP_PLAN})
    comp = _dup_computed(root, ledger)
    assert comp["done"] == 1 and comp["counted"] == 2 and comp["total"] == 2
    assert comp["open_tasks"] == ["1.1"]


def test_duplicate_id_legacy_collapses_to_one(rooted, ledger):
    root = rooted({"plans/2026-07-10_dup.md": DUP_PLAN}, parser=False)
    comp = _dup_computed(root, ledger)
    assert comp["done"] == 1 and comp["counted"] == 1 and comp["total"] == 1
    assert comp["open_tasks"] == []


# --------------------------------------------------------------------------- 10. status --plan --oneline


def _oneline(root: Path, plan_rel: str) -> str:
    cp = _run([str(LEDGER), "status", "--root", str(root), "--plan", str(root / plan_rel), "--oneline"])
    assert cp.returncode == 0, cp.stderr
    return _nl(cp.stdout).strip()


def test_oneline_adapter_prints_done_over_counted(rooted):
    root = rooted({"plans/2026-07-02_tail.md": TWO_PLANS["plans/2026-07-02_tail.md"]})
    assert _oneline(root, "plans/2026-07-02_tail.md") == "tail · — · 2/3 · (no row)"


def test_oneline_without_parser_prints_legacy_count(rooted):
    root = rooted({"plans/2026-07-02_tail.md": TWO_PLANS["plans/2026-07-02_tail.md"]}, parser=False)
    assert _oneline(root, "plans/2026-07-02_tail.md") == "tail · — · 0/3 · (no row)"


# --------------------------------------------------------------------------- 11. сид и манифест


def test_ledger_and_seed_copy_are_byte_identical():
    assert LEDGER.read_bytes() == SEED_LEDGER.read_bytes()


def test_manifest_hash_matches_lf_normalised_ledger_bytes():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    recorded = manifest["scripts/plans_ledger.py"]
    actual = hashlib.sha256(LEDGER.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    assert actual == recorded, f"манифест {recorded} != sha256(LF-байты) {actual}"


# --------------------------------------------------------------------------- DESIGN: add / автостатус


def _add(root: Path, plan: str) -> subprocess.CompletedProcess:
    return _run([str(LEDGER), "add", plan, "--root", str(root)])


def test_add_adapter_writes_adapter_count_and_autostatus_done(rooted):
    # DESIGN: `add` берёт ячейку задач и автостатус DONE из адаптера: tpc = 3/3 -> DONE
    root = rooted({f"plans/{TPC_REL}": fixture_text(f"close_tpc/plans/{TPC_REL}")})
    cp = _add(root, TPC_REL)
    assert cp.returncode == 0, cp.stderr
    readme = _nl((root / "plans" / "README.md").read_text(encoding="utf-8"))
    assert re.search(
        r"^\| \[tpc\]\(2026-07-16_tpc\.md\) \| — \| — \| 3/3 \| DONE \| \d{4}-\d{2}-\d{2} \|$", readme, re.M
    ), readme


def test_add_without_parser_keeps_legacy_count_and_draft(rooted):
    root = rooted({f"plans/{TPC_REL}": fixture_text(f"close_tpc/plans/{TPC_REL}")}, parser=False)
    cp = _add(root, TPC_REL)
    assert cp.returncode == 0, cp.stderr
    readme = _nl((root / "plans" / "README.md").read_text(encoding="utf-8"))
    assert re.search(
        r"^\| \[tpc\]\(2026-07-16_tpc\.md\) \| — \| — \| 0/3 \| DRAFT \| \d{4}-\d{2}-\d{2} \|$", readme, re.M
    ), readme
