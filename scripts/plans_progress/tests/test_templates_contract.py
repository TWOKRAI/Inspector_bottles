# ruff: noqa: E501
"""Контракт шаблонов планов (Task 3.5): шаблон, парсер и ledger читают одно и то же.

Тест автора (слепого тестера нет: задача — текст шаблонов, это сказано в итоге 3.5).
Шаблон — единственное, что копируют соседние сессии, поэтому дрейф шаблона от парсера
ловится здесь, а не ревью. Ходит в настоящие CLI (`plans_progress.py`, `plans_ledger.py`).
Читает источники шаблонов `.claude/plugins/core/templates/`.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
TEMPLATES = REPO_ROOT / ".claude" / "plugins" / "core" / "templates"
LEDGER = REPO_ROOT / "scripts" / "plans_ledger.py"

# метки, без которых `plans_ledger.py brief` отказывает (замер ревью Fable 2026-10-03: REDS, TESTS, OUT OF SCOPE)
TASK_LABELS = ("TASK", "ROLE", "CHAIN", "DESIGN", "FILES", "REDS", "ACCEPTANCE", "TESTS", "OUT OF SCOPE")


def _read(name: str) -> str:
    return (TEMPLATES / name).read_bytes().decode("utf-8").replace("\r\n", "\n")


def test_plan_from_template_gives_its_tasks_without_findings(make_root, one_plan, progress):
    """План, созданный из шаблона без правок, читается: 3 задачи, ни `?`, ни «без отметки», ни одной находки."""
    root = make_root({"plans/2026-10-03_from-template.md": _read("PLAN.template.md")})
    rec = one_plan(root, "2026-10-03_from-template")
    assert [t["id"] for t in rec["tasks"]] == ["1.1", "1.2", "2.1"]
    assert rec["unknown"] == 0
    assert rec["unmarked"] == 0
    cp = progress(root, "--check")
    assert cp.returncode == 0, cp.stdout
    assert "информационных 0" in cp.stdout, cp.stdout


def test_task_template_has_no_second_status():
    """Статус пишется один раз, в плане: в теле задачи строки `**Статус:**`/`**Status:**` нет."""
    text = _read("TASK.template.md")
    assert not re.search(r"\*\*(Статус|Status):?\*\*", text), "второе место статуса в TASK.template.md"


def test_task_template_carries_every_label_the_brief_requires():
    text = _read("TASK.template.md")
    missing = [lab for lab in TASK_LABELS if not re.search(rf"^{re.escape(lab)}\b", text, re.MULTILINE)]
    assert missing == [], f"в TASK.template.md нет меток: {missing}"


def test_task_template_points_at_layout_v2_plan():
    assert "phase-N" not in _read("TASK.template.md")


def test_plan_template_closing_words_are_the_status_set():
    text = _read("PLAN.template.md")
    assert "[SKIPPED]" not in text
    assert "[CANCELLED]" not in text


def test_plan_template_table_names_design_and_reports():
    text = _read("PLAN.template.md")
    assert "`design.md`" in text
    assert "`reports/<id>.md`" in text


def test_ledger_brief_accepts_the_task_template(tmp_path):
    """Настоящий ledger собирает бриф по файлу задачи, скопированному из шаблона (проводка, не фикстура)."""
    plan_dir = tmp_path / "plans" / "2026-10-03_tpl"
    (plan_dir / "tasks").mkdir(parents=True)
    (plan_dir / "plan.md").write_bytes(_read("PLAN.template.md").encode("utf-8"))
    (plan_dir / "tasks" / "1.1.md").write_bytes(_read("TASK.template.md").encode("utf-8"))
    # шаблон брифа ledger ищет от `--root`: кладём настоящий файл проекта в тестовый корень
    brief_tpl = tmp_path / ".claude" / "plugins" / "dev" / "templates" / "executor-brief.md"
    brief_tpl.parent.mkdir(parents=True)
    brief_tpl.write_bytes((REPO_ROOT / ".claude" / "plugins" / "dev" / "templates" / "executor-brief.md").read_bytes())
    cp = subprocess.run(
        [sys.executable, str(LEDGER), "brief", "--plan", str(plan_dir / "plan.md"), "--root", str(tmp_path), "1.1"],
        capture_output=True,
        timeout=60,
        encoding="utf-8",
        errors="replace",
    )
    assert cp.returncode == 0, f"brief exit {cp.returncode}: {cp.stdout[:300]!r} {cp.stderr[:300]!r}"
    assert "missing field" not in cp.stdout + cp.stderr
