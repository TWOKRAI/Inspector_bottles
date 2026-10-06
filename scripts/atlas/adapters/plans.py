"""Адаптер `plans`: узлы plan/task и рёбра in_plan из `plans_progress --json` (Task 1.3a).

Purpose: распаковывает только `plans/` ревизии сборки и зовёт plans_progress подпроцессом (`--json --root`);
    `live_plans` — тот же вызов на корне checkout для значения `plans` в `--json`.
Public API: PLANS_PROGRESS, PlansAdapter, live_plans.
Stability: lite
Принятый предел: отпечаток кэша (CORE_VERSION + name:version) не хеширует plans_progress.py; смена его
    парсера -> поднять PlansAdapter.version, иначе кэш `<ref>` хранит старый разбор.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from scripts.atlas.schema import AdapterOutput, BuildContext, Edge, Node
from scripts.atlas.tree import AtlasError

__all__ = ["PLANS_PROGRESS", "PlansAdapter", "live_plans"]

PLANS_PROGRESS = Path(__file__).resolve().parents[2] / "plans_progress" / "plans_progress.py"
_DATE_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2}_")


def _run(root: Path) -> list[dict[str, Any]]:
    """`plans_progress --json --root <root>`; сбой процесса или не-JSON на stdout -> AtlasError."""
    proc = subprocess.run(
        [sys.executable, str(PLANS_PROGRESS), "--json", "--root", str(root)], capture_output=True, check=False
    )
    failed = AtlasError(f"atlas: plans_progress --json failed (exit {proc.returncode})")
    if proc.returncode != 0:
        raise failed
    try:
        data = json.loads(proc.stdout.decode("utf-8"))
    except ValueError as exc:  # UnicodeDecodeError и JSONDecodeError — потомки ValueError
        raise failed from exc
    if not isinstance(data, list):
        raise failed
    return data


def live_plans(root: Path) -> list[dict[str, Any]]:
    """Живой вывод plans_progress для корня checkout без изменений."""
    return _run(Path(root))


class PlansAdapter:
    name = "plans"
    version = 1

    def collect(self, ctx: BuildContext) -> AdapterOutput:
        out = AdapterOutput()
        if not any(f.startswith("plans/") for f in ctx.tree.files()):
            return out
        with ctx.tree.materialize("plans") as target:
            plans = _run(target)
        seen: set[str] = set()
        for plan in plans:
            slug = _DATE_PREFIX.sub("", plan["plan"])
            if slug in seen:
                raise AtlasError("atlas: two plans share one slug — rename one plan")
            seen.add(slug)
            plan_id = f"plan:{slug}"
            out.nodes.append(Node("plan", slug, plan["path"], plan["header_status"]))
            ids: set[str] = set()
            for task in plan["tasks"]:
                if task["id"] in ids:
                    raise AtlasError("atlas: duplicate task id in one plan")
                ids.add(task["id"])
                task_id = f"{slug}#{task['id']}"
                out.nodes.append(Node("task", task_id, plan["path"], task["status"]))
                out.edges.append(Edge("in_plan", f"task:{task_id}", plan_id, "plan-line"))
        return out
