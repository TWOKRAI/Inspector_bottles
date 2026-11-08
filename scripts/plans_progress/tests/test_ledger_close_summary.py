# ruff: noqa: E501  -- литералы-фикстуры планов в одну строку
"""Task 7.1b: итог плана при `close` и словарь статусов plans_ledger.py.

Тесты ходят через CLI в subprocess (как и остальные acceptance-тесты ledger):
реализацию не импортируют, ожидания — литералы.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
LEDGER = REPO_ROOT / "scripts" / "plans_ledger.py"
PLAN_TEMPLATE = REPO_ROOT / ".claude" / "plugins" / "core" / "templates" / "PLAN.template.md"

PLAN = "2026-11-01_itog"
ARCHIVED = f"plans/_archive/2026-Q4/{PLAN}"
ITEMS = "## Порядок выполнения\n\n- Task 1.1: a [DONE]\n"
BUDGET = "## Бюджет\n\n$1\n\n"


def _run(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(LEDGER), *args, "--root", str(root)],
        capture_output=True,
        timeout=60,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
    )


def _locked_plan(tmp_path: Path, body: str, *, lock: bool = True) -> Path:
    """Каталог плана с (или без) contract.lock; корень — tmp_path."""
    plan_dir = tmp_path / "plans" / PLAN
    plan_dir.mkdir(parents=True)
    (plan_dir / "plan.md").write_text(
        f"# План\n\n- **Статус:** ACTIVE\n\n## Цели\n\nСделать.\n\n{BUDGET}{ITEMS}{body}", encoding="utf-8"
    )
    if lock:
        (plan_dir / "contract.lock").write_text('{"schema": 2}\n', encoding="utf-8")
    return tmp_path


def test_close_refuses_locked_catalog_without_itog_even_with_force(tmp_path):
    root = _locked_plan(tmp_path, "")
    for flags in ((), ("--force",)):
        cp = _run(root, "close", PLAN, *flags)
        assert cp.returncode == 2, (flags, cp.stdout, cp.stderr)
        assert "CLOSED_WITHOUT_SUMMARY" in cp.stderr, (flags, cp.stderr)
        assert (root / "plans" / PLAN / "plan.md").is_file(), "план должен остаться на месте"
        assert not (root / ARCHIVED).exists()


def test_close_refuses_empty_itog_section(tmp_path):
    # Заголовок без текста до следующего заголовка — то же, что отсутствие раздела.
    root = _locked_plan(tmp_path, "\n## Итог\n\n\n## Хвост\n\nпроза\n")
    cp = _run(root, "close", PLAN)
    assert cp.returncode == 2, (cp.stdout, cp.stderr)
    assert "CLOSED_WITHOUT_SUMMARY" in cp.stderr


def test_close_writes_itog_verbatim_into_summary(tmp_path):
    root = _locked_plan(
        tmp_path, "\n## Итог\n\nВышло: первое.\nFROZEN: второе.\n\nПреемник: третье.\n\n## Хвост\n\nне итог\n"
    )
    cp = _run(root, "close", PLAN)
    assert cp.returncode == 0, (cp.stdout, cp.stderr)
    summary = (root / ARCHIVED / "SUMMARY.md").read_text(encoding="utf-8")
    assert "## Итог\n\nВышло: первое.\nFROZEN: второе.\n\nПреемник: третье.\n" in summary
    assert "не итог" not in summary
    # Итог — после Goal и до таблицы задач.
    assert summary.index("## Goal") < summary.index("## Итог") < summary.index("## Tasks")


def test_summary_without_itog_has_no_section_and_does_not_refuse(tmp_path):
    root = _locked_plan(tmp_path, "")
    cp = _run(root, "summary", PLAN)
    assert cp.returncode == 0, (cp.stdout, cp.stderr)
    assert "## Итог" not in cp.stdout


def _status_lines(tmp_path: Path, header: str) -> tuple[int, list[str]]:
    plan_dir = tmp_path / "plans" / PLAN
    plan_dir.mkdir(parents=True)
    (plan_dir / "plan.md").write_text(f"# План\n\n{header}\n\n## Цели\n\nСделать.\n\n{BUDGET}{ITEMS}", encoding="utf-8")
    cp = _run(tmp_path, "status", "--check", "--plan", f"plans/{PLAN}")
    return cp.returncode, [ln for ln in cp.stdout.splitlines() if "STATUS_OUTSIDE_DICTIONARY" in ln]


def test_status_outside_dictionary_is_info_not_gating(tmp_path):
    rc, lines = _status_lines(tmp_path, "- **Статус:** ЗАКРЫТ")
    assert rc == 0
    assert lines == [
        f"INFO STATUS_OUTSIDE_DICTIONARY plans/{PLAN}/plan.md: header status 'ЗАКРЫТ' is outside the dictionary"
    ]


@pytest.mark.parametrize(
    "header, outside",
    [
        ("- **Статус:** DRAFT,", None),
        ("- **Статус:** **APPROVED", None),
        ("- **Статус:** IN PROGRESS (этап 2)", None),
        ("- **Status:** `ACTIVE`", None),
        ("- **Статус:** FROZEN", None),
        ("- **Статус:** FREEZE", None),
        ("- **Status:** **ACTIVE**", None),
        ("- **Статус:** draft", None),
        ("- **Status:** In Progress (x)", None),
        ("- **Статус:** PLANNED.", "PLANNED"),
        ("- **Статус:** ВЫПОЛНЕН; осталось ревью", "ВЫПОЛНЕН"),
    ],
)
def test_header_status_normalization(tmp_path, header, outside):
    rc, lines = _status_lines(tmp_path, header)
    assert rc == 0
    if outside is None:
        assert lines == []
    else:
        assert len(lines) == 1
        assert f"header status '{outside}' is outside the dictionary" in lines[0]


def _itog(lines: int, chars: int) -> str:
    return "\n## Итог\n\n" + "\n".join("я" * chars for _ in range(lines)) + "\n"


def test_close_accepts_30_cyrillic_lines_and_refuses_oversize(tmp_path):
    ok = _locked_plan(tmp_path / "ok", _itog(30, 40))
    cp = _run(ok, "close", PLAN)
    assert cp.returncode == 0, (cp.stdout, cp.stderr)

    big = _locked_plan(tmp_path / "big", _itog(30, 50))
    cp = _run(big, "close", PLAN)
    assert cp.returncode == 2, (cp.stdout, cp.stderr)
    assert "CLOSED_WITHOUT_SUMMARY: '## Итог' is 3029 bytes, max 2560" in cp.stderr
    assert (big / "plans" / PLAN / "plan.md").is_file()


def test_close_single_file_plan_needs_no_itog(tmp_path):
    single = tmp_path / "plans" / "2026-11-01_single.md"
    single.parent.mkdir(parents=True)
    single.write_text(f"# План\n\n{ITEMS}", encoding="utf-8")
    cp = _run(tmp_path, "close", "2026-11-01_single.md")
    assert cp.returncode == 0, (cp.stdout, cp.stderr)
    assert (tmp_path / "plans" / "_archive" / "2026-Q4" / "2026-11-01_single.md").is_file()


def test_close_catalog_without_lock_needs_no_itog(tmp_path):
    root = _locked_plan(tmp_path, "", lock=False)
    cp = _run(root, "close", PLAN)
    assert cp.returncode == 0, (cp.stdout, cp.stderr)


def test_frozen_is_accepted_by_add_status(tmp_path):
    single = tmp_path / "plans" / "2026-11-01_frz.md"
    single.parent.mkdir(parents=True)
    single.write_text("# План\n\n- Task 1.1: a [PENDING]\n", encoding="utf-8")
    cp = _run(tmp_path, "add", "2026-11-01_frz.md", "--status", "FROZEN")
    assert cp.returncode == 0, (cp.stdout, cp.stderr)
    readme = (tmp_path / "plans" / "README.md").read_text(encoding="utf-8")
    assert "| FROZEN |" in readme


def test_close_itog_limit_boundary_2560_passes_2561_refused(tmp_path):
    # «я» — 2 байта UTF-8: 1280 символов = ровно 2560 байт; «a» сверху — 2561.
    ok = _locked_plan(tmp_path / "ok", "\n## Итог\n\n" + "я" * 1280 + "\n")
    cp = _run(ok, "close", PLAN)
    assert cp.returncode == 0, (cp.stdout, cp.stderr)

    over = _locked_plan(tmp_path / "over", "\n## Итог\n\n" + "я" * 1280 + "a\n")
    cp = _run(over, "close", PLAN)
    assert cp.returncode == 2, (cp.stdout, cp.stderr)
    assert "CLOSED_WITHOUT_SUMMARY: '## Итог' is 2561 bytes, max 2560" in cp.stderr
    assert (over / "plans" / PLAN / "plan.md").is_file()


AMENDMENTS = (
    "| # | дата | почему | Δ задач | Δ бюджета |\n|---|---|---|---|---|\n| — | 2026-11-01 | открытие | — | — |\n"
)


def _approvable_plan(tmp_path: Path, header: str, *, budget: bool) -> Path:
    """Каталог плана, готовый к approve: шапка как задана, задача закрыта, amendments.md есть."""
    plan_dir = tmp_path / "plans" / PLAN
    plan_dir.mkdir(parents=True)
    (plan_dir / "plan.md").write_text(
        f"# План\n\n{header}\n\n## Цели\n\nСделать.\n\n{BUDGET if budget else ''}{ITEMS}", encoding="utf-8"
    )
    (plan_dir / "amendments.md").write_text(AMENDMENTS, encoding="utf-8")
    return tmp_path


def test_approve_with_header_outside_dictionary_succeeds_and_writes_lock(tmp_path):
    root = _approvable_plan(tmp_path, "- **Статус:** ЗАКРЫТ", budget=True)
    cp = _run(root, "approve", PLAN)
    assert cp.returncode == 0, (cp.stdout, cp.stderr)
    assert "INFO STATUS_OUTSIDE_DICTIONARY" in cp.stdout
    assert (root / "plans" / PLAN / "contract.lock").is_file()


def test_approve_still_refuses_on_gating_finding(tmp_path):
    root = _approvable_plan(tmp_path, "- **Статус:** ЗАКРЫТ", budget=False)
    cp = _run(root, "approve", PLAN)
    assert cp.returncode == 1, (cp.stdout, cp.stderr)
    assert "WARN NO_BUDGET" in cp.stdout
    assert "approve refused: 1 gate finding(s)" in cp.stderr
    assert not (root / "plans" / PLAN / "contract.lock").exists()


def test_close_refuses_untouched_itog_section_of_the_template(tmp_path):
    template = PLAN_TEMPLATE.read_text(encoding="utf-8")
    section = re.search(r"^## Итог\n.*?(?=^## |\Z)", template, re.S | re.M)
    assert section, "в шаблоне нет раздела «## Итог»"
    root = _locked_plan(tmp_path, "\n" + section.group(0))
    cp = _run(root, "close", PLAN)
    assert cp.returncode == 2, (cp.stdout, cp.stderr)
    assert "CLOSED_WITHOUT_SUMMARY" in cp.stderr
    assert (root / "plans" / PLAN / "plan.md").is_file()


def test_close_refuses_itog_with_only_html_comment(tmp_path):
    root = _locked_plan(tmp_path, "\n## Итог\n\n<!-- первая строка\n     вторая строка -->\n")
    cp = _run(root, "close", PLAN)
    assert cp.returncode == 2, (cp.stdout, cp.stderr)
    assert "CLOSED_WITHOUT_SUMMARY" in cp.stderr


def test_close_keeps_text_and_drops_comment_in_summary(tmp_path):
    body = "\n## Итог\n\n<!-- пояснение\n     в два ряда -->\n\nВышло: всё.\nХвост <!-- встроенный --> строки.\n"
    root = _locked_plan(tmp_path, body)
    cp = _run(root, "close", PLAN)
    assert cp.returncode == 0, (cp.stdout, cp.stderr)
    summary = (root / ARCHIVED / "SUMMARY.md").read_text(encoding="utf-8")
    assert "## Итог\n\nВышло: всё.\nХвост  строки.\n" in summary
    assert "<!--" not in summary
    assert "пояснение" not in summary


def test_heading_inside_comment_is_not_a_section_boundary_or_a_section(tmp_path):
    # Заголовок внутри комментария не обрывает раздел...
    inner = _locked_plan(tmp_path / "inner", "\n## Итог\n\nтекст\n<!-- ## Хвост\nскрытый -->\nещё\n")
    cp = _run(inner, "close", PLAN)
    assert cp.returncode == 0, (cp.stdout, cp.stderr)
    summary = (inner / ARCHIVED / "SUMMARY.md").read_text(encoding="utf-8")
    assert "## Итог\n\nтекст\nещё\n" in summary
    assert "скрытый" not in summary
    # ...и «## Итог» внутри комментария — не раздел.
    hidden = _locked_plan(tmp_path / "hidden", "\n<!--\n## Итог\nтекст в комментарии\n-->\n")
    cp = _run(hidden, "close", PLAN)
    assert cp.returncode == 2, (cp.stdout, cp.stderr)
    assert "CLOSED_WITHOUT_SUMMARY" in cp.stderr
