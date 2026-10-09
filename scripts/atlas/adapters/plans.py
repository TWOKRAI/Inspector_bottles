"""Адаптер `plans`: узлы plan/task и рёбра in_plan из `plans_progress --json` (Task 1.3a, 1.3b).

Purpose: распаковывает только `plans/` ревизии сборки и зовёт plans_progress подпроцессом (`--json --root`);
    `plans_for` отдаёт один разбор адаптерам `plans` и `commits` (lru_cache); `live_plans` — тот же вызов
    на корне checkout для значения `plans` в `--json`. Находка RESULT_FORM (Task 1.9a) считается там же по
    распакованным `plans/**/tasks/*.result.md` и уходит только в `plans`; версия адаптера хеширует и result_form.py.
Public API: PLANS_PROGRESS, PLANS_TIMEOUT, PlansAdapter, RESULT_FORM_PY, adapter_version, live_plans, plans_for.
Stability: lite
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

from scripts.atlas import result_form
from scripts.atlas.schema import AdapterOutput, BuildContext, Edge, Finding, Node
from scripts.atlas.tree import AtlasError, Tree

__all__ = [
    "PLANS_PROGRESS",
    "PLANS_TIMEOUT",
    "RESULT_FORM_PY",
    "PlansAdapter",
    "adapter_version",
    "live_plans",
    "plans_for",
]

PLANS_PROGRESS = Path(__file__).resolve().parents[2] / "plans_progress" / "plans_progress.py"
PLANS_TIMEOUT = 120
RESULT_FORM_PY = Path(result_form.__file__).resolve()
_DATE_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2}_")


def adapter_version(base: int, path: Path | None = None, *more: Path) -> int:
    """Версия адаптера: `base` (руками) × 2**48 + 12 hex sha256 байт файлов `path` (None = plans_progress) и `more`.

    Нет любого из файлов -> 0 вместо хеша.
    """
    digest = hashlib.sha256()
    try:
        for file in (PLANS_PROGRESS if path is None else path, *more):
            digest.update(file.read_bytes())
        stamp = int(digest.hexdigest()[:12], 16)
    except OSError:
        stamp = 0
    return base * 2**48 + stamp


def _run(root: Path) -> list[dict[str, Any]]:
    """`plans_progress --json --root <root>`; сбой, таймаут или не-JSON на stdout -> AtlasError."""
    try:
        proc = subprocess.run(
            [sys.executable, str(PLANS_PROGRESS), "--json", "--root", str(root)],
            capture_output=True,
            check=False,
            timeout=PLANS_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        raise AtlasError("atlas: plans_progress --json timed out") from None
    data: Any = None
    if proc.returncode == 0:
        try:
            data = json.loads(proc.stdout.decode("utf-8"))
        except ValueError:  # UnicodeDecodeError и JSONDecodeError — потомки ValueError
            data = None
    if not isinstance(data, list):
        if proc.stderr:  # диагностика самого инструмента — отдельный поток, не текст ошибки
            sys.stderr.write(proc.stderr.decode("utf-8", "replace"))
        raise AtlasError(f"atlas: plans_progress --json failed (exit {proc.returncode})")
    return data


def live_plans(root: Path) -> list[dict[str, Any]]:
    """Живой вывод plans_progress для корня checkout без изменений."""
    return _run(Path(root))


def _result_findings(target: Path) -> list[Finding]:
    """RESULT_FORM по `plans/**/tasks/*.result.md` распакованного `plans/`; узел `result:<slug>#<id>` (ADR-ATL-001)."""
    out: list[Finding] = []
    for file in sorted((target / "plans").rglob("tasks/*.result.md")):
        rel = file.relative_to(target)
        if rel.parent.parent == Path("plans"):  # `plans/tasks/` — каталога плана над tasks/ нет
            continue
        found = result_form.violations(file.read_bytes().decode("utf-8-sig", "replace"))
        if found:
            slug = _DATE_PREFIX.sub("", rel.parent.parent.name)
            node = f"result:{slug}#{file.name.removesuffix('.result.md')}"
            message = "Итог не по форме 0.7: " + "; ".join(text for _, text in found)
            out.append(Finding("RESULT_FORM", "warning", node, ",".join(t for t, _ in found), message, rel.as_posix()))
    return out


@lru_cache(maxsize=8)
def _load(script: str, root: str, ref: str) -> tuple[tuple[tuple[str, dict[str, Any]], ...], tuple[Finding, ...]]:
    tree = Tree(root, ref)
    if not any(f.startswith("plans/") for f in tree.files()):
        return (), ()
    with tree.materialize("plans") as target:
        plans = _run(target)
        result_findings = _result_findings(target)
    kept: dict[str, dict[str, Any]] = {}
    findings: list[Finding] = []
    for plan in sorted(plans, key=lambda p: (bool(p.get("archived")), p["path"])):  # живой раньше архивного
        slug = _DATE_PREFIX.sub("", plan["plan"])
        if slug in kept:
            msg = f"План {plan['path']} отброшен: slug «{slug}» уже занят планом {kept[slug]['path']}"
            findings.append(Finding("PLAN_SLUG_COLLISION", "blocking", f"plan:{slug}", plan["path"], msg, plan["path"]))
            continue
        ids: set[str] = set()
        for task in plan["tasks"]:
            if task["id"] in ids:
                raise AtlasError("atlas: duplicate task id in one plan")
            ids.add(task["id"])
        kept[slug] = plan
    return tuple(kept.items()), (*findings, *result_findings)


def plans_for(tree: Tree) -> tuple[tuple[tuple[str, dict[str, Any]], ...], tuple[Finding, ...]]:
    """(пары (slug, план), находки PLAN_SLUG_COLLISION) ревизии; один запуск plans_progress на ключ кэша."""
    return _load(str(PLANS_PROGRESS), str(tree.root), tree.ref)


class PlansAdapter:
    name = "plans"
    _BASE = 2

    @property
    def version(self) -> int:
        return adapter_version(self._BASE, PLANS_PROGRESS, RESULT_FORM_PY)

    def collect(self, ctx: BuildContext) -> AdapterOutput:
        plans, findings = plans_for(ctx.tree)
        out = AdapterOutput(findings=list(findings))
        for slug, plan in plans:
            plan_id = f"plan:{slug}"
            out.nodes.append(Node("plan", slug, plan["path"], plan["header_status"]))
            for task in plan["tasks"]:
                task_id = f"{slug}#{task['id']}"
                out.nodes.append(Node("task", task_id, plan["path"], task["status"]))
                out.edges.append(Edge("in_plan", f"task:{task_id}", plan_id, "plan-line"))
        return out
