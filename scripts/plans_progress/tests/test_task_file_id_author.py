"""Task 3.0 (commit-mechanism), правки ревью r1: файл задачи `tasks/<id>.md` читается по грамматике id (DESIGN п. 6).

`parse_task_file` берёт id из имени файла (`ID_RE.fullmatch(path.stem)`). Файл приёмки тестера этот путь не
исполняет; здесь он закрыт: в плане нет ни пунктов, ни заголовков задач, ни таблиц — задачу даёт только файл.
Ожидаемые значения — литералы.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_MOD_PATH = Path(__file__).resolve().parents[1] / "plans_progress.py"
_spec = importlib.util.spec_from_file_location("plans_progress_task_file_under_test", _MOD_PATH)
pp = importlib.util.module_from_spec(_spec)
sys.modules["plans_progress_task_file_under_test"] = pp
_spec.loader.exec_module(pp)


def _task_ids(tmp_path: Path, stem: str) -> list[str]:
    plan_dir = tmp_path / "plans" / "2026-10-05_tf"
    (plan_dir / "tasks").mkdir(parents=True)
    main = plan_dir / "plan.md"
    main.write_text("# План\n", encoding="utf-8")
    (plan_dir / "tasks" / f"{stem}.md").write_text(f"# Task {stem} — a\n\n**Статус:** [DONE]\n", encoding="utf-8")
    plan = pp.analyze_plan("tf", main, plan_dir, "plans/2026-10-05_tf/plan.md", False)
    return [t.id for t in plan.tasks]


@pytest.mark.parametrize("stem", ["1.2.3", "ABC1"])
def test_task_file_with_new_grammar_id_is_a_task(tmp_path, stem):
    assert _task_ids(tmp_path, stem) == [stem]


def test_task_file_with_two_letter_segment_is_not_a_task(tmp_path):
    assert _task_ids(tmp_path, "1.3ab") == []
