#!/usr/bin/env python3
"""plans_ledger.py — `plans/README.md` as a machine-readable ledger.

Purpose:
    The plan lifecycle (plan -> `Refs:` -> ledger -> archive) lived as prose in
    `/dev:plan`, `/dev:ship` and `/dev:plan-status` ("add a row to the table"),
    and nothing executed it: the repo's own ledger was prose, a closed plan sat
    outside `_archive/`, and ledger summaries drifted from git. This script is
    the one executor; the commands and `plugin doctor` call it instead of
    re-describing it.

Stability: lite (public CLI + the functions below; stdlib-only, delivered to
projects as `scripts/plans_ledger.py`, ADR-0002). Contract tests:
`tests/contract/test_plans_ledger.py`.

Ledger format — two tables, one under an «Активные»/«Active» heading, one under
«Архив»/«Archive»:

    | план | ветка | фаза | задачи | статус | обновлено |
    |------|-------|------|--------|--------|-----------|
    | [slug](2026-05-01_slug/plan.md) | feat/slug | phase 2 | 3/5 | ACTIVE | 2026-05-01 |

Header cells may be Cyrillic or Latin (plan/branch/phase/tasks/status/updated).
The plan cell is a path relative to `plans/`, bare or as a Markdown link.
Status is one of DRAFT / ACTIVE / DONE / ARCHIVED.

Counting: a task is a `### Task X.Y` heading (outside code fences), or — in a
`tasks/<id>.md` file only — a `# Task X.Y` (H1) heading (plan layout v2, Task
2.3). A task is closed when EITHER every checkbox under its heading is ticked
(the whole file, when the task lives in `tasks/<id>.md` — overriding a stale
`### Task X.Y` section of the same id elsewhere, e.g. plan.md; Task 2.3
review, F3) OR its line in a «Порядок выполнения» / «Execution order» section
carries `[DONE]` — both conventions live in real plans. The phase is the one of the first open task
(`phase-N.md` file name, or the nearest preceding `## Phase N` heading).

A plan is "done" when all its tasks are closed, or when its ledger row says
DONE (a narrative plan without `### Task` headings, status reconciled with git).

Plan layout v2 (`plans/<date>_<slug>/plan.md` + `tasks/<id>.md` + optional
`phase-N.md`, `amendments.md`) is discovered alongside the v1 layout
(`plan.md` + `phase-N.md` only); `amendments.md`/`decisions.md`/`SUMMARY.md`/
`injections.md` are never task sources. Size budgets (module constants
`PLAN_MAX_BYTES`, `SINGLE_PLAN_MAX_BYTES`, `TASK_MAX_BYTES`,
`PHASE_MAX_BYTES`, `JOURNAL_MAX_ITEMS`) are enforced by `check_plan_sizes()`
for active plans only (never `_archive/`, never a `_`-prefixed name).

Public API:
    discover_plan_files(path) -> list[Path]
    extract_task_ids(text, in_task_file=False) -> list[str]
    task_checkbox_totals(text, task_id) -> tuple[int, int] | None
    task_order_marker(all_text, task_id) -> str | None
    is_task_closed(all_text, task_id) -> bool
    summarize_plan(paths) -> PlanSummary
    parse_ledger_row_path(cell) -> str
    parse_ledger_table(readme_text) -> LedgerTable
    render_row(plan, branch, phase, tasks, status, updated) -> str
    plan_cell(rel) -> str                   Markdown link cell for a plan path
    list_active_plans(root) -> dict[str, Path]   plans directly under plans/
    resolve_plan(root, plan) -> tuple[str, Path] (ledger key, path); no `..`
    quarter_for(name) -> str                "YYYY-Qn" from a dated name
    check_plan_sizes(plan_dir_or_file) -> list[Finding]  codes: PLAN_TOO_BIG,
                                            TASK_TOO_BIG, JOURNAL_IN_PLAN,
                                            RESULT_TOO_BIG (a plan directory's
                                            tasks/<id>.result.md over
                                            RESULT_MAX_BYTES) (none fixable)
    check_plan_gate(plan_dir_or_file) -> list[Finding]  check_plan_sizes()
                                            PLUS: NO_BUDGET, TASK_INCOMPLETE,
                                            TASK_TOO_MANY_FILES (none
                                            fixable) — amendment 6
    check_ledger(root) -> list[Finding]     codes: DONE_NOT_ARCHIVED,
                                            MISSING_ROW, ROW_WITHOUT_FILE,
                                            PLAN_TOO_BIG, TASK_TOO_BIG,
                                            JOURNAL_IN_PLAN, CONTRACT_DRIFT,
                                            SCOPE_GREW, UNAPPROVED_OVER_BUDGET
                                            (only the first two are fixable)
    add_row(root, plan, *, status=None, branch=None, today=None) -> str (diff)
    archive_plan(root, plan_rel, *, today=None) -> ArchiveResult
    apply_ledger_fixes(root, *, today=None) -> list[FixReport]
    contract_fingerprint(plan_md_text) -> str   sha256 hex, status/marker-blind
    contract_files_fingerprint(plan_dir) -> tuple[str, dict[str, str]]
                                            (overall sha256, {rel_path: sha256})
                                            over every discover_plan_files()
                                            file — the contract's full extent
    parse_amendments(text) -> list[AmendmentRow]   amendments.md table rows
    approve_plan(root, plan, *, today=None, force=False) -> Path
                                            writes contract.lock
    amend_plan(root, plan, *, today=None) -> Path   refreshes contract.lock
    check_plan_contract(plan_dir) -> list[Finding]  codes: CONTRACT_DRIFT,
                                            SCOPE_GREW (none fixable; [] with
                                            no contract.lock or a single-file
                                            plan — v2 lock is opt-in)
    build_brief(root, plan_path, task_id) -> str   spawn-ready brief:
                                            tasks/<id>.md + the standing
                                            blocks of executor-brief.md
                                            (raises BriefRefused)
    build_summary(plan_dir) -> str          one-page SUMMARY.md text for a
                                            plan directory (Goal/Tasks/
                                            Amendments/Open->backlog),
                                            <= TASK_MAX_BYTES (raises
                                            ValueError when even the
                                            shrunk re-render overflows it)
    main(argv) -> int

Plan contract freeze (Task 5.1, widened by the 5.1-fix review): `approve`
writes `<plan_dir>/contract.lock` (schema=2) with `contract_files_fingerprint`
over every contract file (`plan.md` + `phase-N.md` + `tasks/<id>.md` —
results/amendments excluded), a per-file sha map (`files`), the task count at
approval, and `last_amendment_number` (the highest `amendments.md` row number
recorded so far, 0 when none). Editing ANY contract file without recording an
`amendments.md` row is `CONTRACT_DRIFT` (the message names up to 5 changed
paths with a verb — changed/added/removed — then `(+N more)`); growing past
125% of the lock's `budgeted_tasks` (a MOVING baseline — every growth past
125% needs its own budgeted amendment), with no un-amended row carrying a
budget delta, is `SCOPE_GREW`. `approve` on a plan that already carries a
readable `contract.lock` is refused (`--force` re-freezes). `amend` runs the
same `check_plan_sizes` gate `approve` does, and re-validates every new
`amendments.md` row: a why naming ADDED/MODIFIED/REMOVED, a YYYY-MM-DD date
not earlier than the lock's `approved`, and a `#` greater than
`last_amendment_number`; it never changes `approved`/`approved_tasks`, and
only advances `budgeted_tasks` to the current task count when at least one
of the new rows carries a budget delta. A lock
that is missing, unreadable, `schema` != 2, or carries a wrong-typed field is
"corrupt" (one `CONTRACT_DRIFT` finding, never an exception) — there is no
schema-1-to-2 migration. Opt-in: a plan without `contract.lock` (or a v1
single-file plan) carries neither finding.

Task results and the close-time SUMMARY.md (Task 5.3): a task's result lives
in `tasks/<id>.result.md` (`<= RESULT_MAX_BYTES`, never a task source, never a
contract file — same exclusion `discover_plan_files` already gave it at Task
2.3); an oversized one is `RESULT_TOO_BIG` from `check_plan_sizes` (never
fixable). `PlanSummary.dropped` counts the tasks that are not closed but whose
«Порядок выполнения» marker is `[SKIPPED]`/`[CANCELLED]` — `_is_done` treats
`done + dropped == total` as done, so a plan whose only remaining tasks are
dropped closes without `--force`. `close`/`archive_plan` writes a one-page
`<plan_dir>/SUMMARY.md` (`build_summary`) before the `git mv`, for a plan
DIRECTORY only (a single-file plan gets none); a `build_summary` failure
(the page would exceed `TASK_MAX_BYTES` even after the shrunk re-render)
raises before any write or move, so `close` refuses cleanly.

Usage:
    python scripts/plans_ledger.py status [--root DIR] [--json] [--check]
    python scripts/plans_ledger.py add PLAN [--status S] [--branch B] [--root DIR]
    python scripts/plans_ledger.py close PLAN [--force] [--root DIR]
    python scripts/plans_ledger.py approve PLAN [--force] [--no-gate] [--root DIR]
    python scripts/plans_ledger.py amend PLAN [--root DIR]
    python scripts/plans_ledger.py brief ID [--plan PATH] [--root DIR]
    python scripts/plans_ledger.py summary PLAN [--root DIR]

Plan gate (Task 4.2, amendment 6): `status --check --plan <p>`/`--branch <b>`
scopes to that one plan (`check_plan_gate` + `check_plan_contract`, never the
whole-ledger `check_ledger`); `approve` runs the same `check_plan_gate` first
and refuses (`--no-gate` bypasses it) — see `check_plan_gate`'s docstring for
its codes (NO_BUDGET, TASK_INCOMPLETE, TASK_TOO_MANY_FILES). A `Finding`'s
`gating` property is False only for UNAPPROVED_OVER_BUDGET — the one code
`check_ledger` emits (never `check_plan_gate`) when one or more *unlocked*
plans carry size findings: those collapse into a single advisory line
instead of gating `status --check`, since sizes gate only after `approve`.

Exit codes:
    0 — success (`status` without `--check` is informational: always 0).
    1 — `status --check` found a GATING finding; `close` refused an open
        plan; `approve`/`amend` refused (gate findings, size findings,
        missing/stale `amendments.md`, an invalid amendment row); `brief`
        refused (BriefRefused — missing plan layout v2, a missing required
        field, or executor-brief.md missing a standing block).
    2 — the plan / root does not exist, an archive destination is taken, a
        write target is unsafe (symlink / outside the root), or `git mv` of a
        tracked plan failed; `brief --plan` did not resolve, or no `--plan`
        was given with zero or several active plans.

Never deletes a plan: `close` / the doctor fix move it (`git mv` when tracked).
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as _dt
import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

__all__ = [
    "CONTRACT_DRIFT",
    "DONE_NOT_ARCHIVED",
    "JOURNAL_IN_PLAN",
    "JOURNAL_MAX_ITEMS",
    "LEDGER_COLUMNS",
    "MISSING_ROW",
    "NO_BUDGET",
    "PHASE_MAX_BYTES",
    "PLAN_MAX_BYTES",
    "PLAN_TOO_BIG",
    "RESULT_MAX_BYTES",
    "RESULT_TOO_BIG",
    "ROW_WITHOUT_FILE",
    "SCOPE_GREW",
    "SINGLE_PLAN_MAX_BYTES",
    "STATUSES",
    "TASK_MAX_BYTES",
    "TASK_MAX_FILES",
    "TASK_TOO_BIG",
    "TASK_TOO_MANY_FILES",
    "TASK_INCOMPLETE",
    "UNAPPROVED_OVER_BUDGET",
    "AmendmentRow",
    "ArchiveResult",
    "BriefRefused",
    "ContractRefused",
    "Finding",
    "FixReport",
    "LedgerTable",
    "PlanSummary",
    "add_row",
    "amend_plan",
    "apply_ledger_fixes",
    "approve_plan",
    "archive_plan",
    "build_brief",
    "build_summary",
    "check_ledger",
    "check_plan_contract",
    "check_plan_gate",
    "check_plan_sizes",
    "contract_files_fingerprint",
    "contract_fingerprint",
    "discover_plan_files",
    "extract_task_ids",
    "is_task_closed",
    "list_active_plans",
    "main",
    "parse_amendments",
    "parse_ledger_row_path",
    "parse_ledger_table",
    "plan_cell",
    "plan_for_branch",
    "quarter_for",
    "render_row",
    "resolve_plan",
    "resolve_plan_path",
    "summarize_plan",
    "task_checkbox_totals",
    "task_order_marker",
]

STATUSES = ("DRAFT", "ACTIVE", "DONE", "ARCHIVED")
LEDGER_COLUMNS = ("plan", "branch", "phase", "tasks", "status", "updated")
LEDGER_HEADER = "| план | ветка | фаза | задачи | статус | обновлено |"
LEDGER_SEPARATOR = "|------|-------|------|--------|--------|-----------|"
NO_VALUE = "—"

DONE_NOT_ARCHIVED = "DONE_NOT_ARCHIVED"
MISSING_ROW = "MISSING_ROW"
ROW_WITHOUT_FILE = "ROW_WITHOUT_FILE"
FIXABLE_CODES = frozenset({DONE_NOT_ARCHIVED, MISSING_ROW})

# Plan layout v2 size budgets (Task 2.3) — bytes on disk; never fixable
# (doctor --fix must not try to shrink a plan for the owner).
PLAN_TOO_BIG = "PLAN_TOO_BIG"
TASK_TOO_BIG = "TASK_TOO_BIG"
JOURNAL_IN_PLAN = "JOURNAL_IN_PLAN"
PLAN_MAX_BYTES = 16 * 1024
SINGLE_PLAN_MAX_BYTES = 32 * 1024
TASK_MAX_BYTES = 8 * 1024
PHASE_MAX_BYTES = 32 * 1024
JOURNAL_MAX_ITEMS = 5

# Task results (Task 5.3) — `tasks/<id>.result.md` is never a task or contract
# source (discover_plan_files already excludes it, Task 2.3); an oversized one
# is a gating, never-fixable finding, same convention as the codes above.
RESULT_TOO_BIG = "RESULT_TOO_BIG"
RESULT_MAX_BYTES = 2 * 1024

# Plan contract freeze (Task 5.1) — an approved plan's contract.lock; never
# fixable (amend is a deliberate, validated act, not something --fix should
# automate on the owner's behalf).
CONTRACT_DRIFT = "CONTRACT_DRIFT"
SCOPE_GREW = "SCOPE_GREW"

# Plan gate (Task 4.2) — an incomplete task or an over-budget plan blocks
# `approve`/`status --check`; never fixable (the owner writes the missing
# field, not --fix). UNAPPROVED_OVER_BUDGET is the one non-gating code: an
# unlocked plan's size findings collapse into a single advisory line until
# the plan is approved (amendment 6).
TASK_INCOMPLETE = "TASK_INCOMPLETE"
TASK_TOO_MANY_FILES = "TASK_TOO_MANY_FILES"
NO_BUDGET = "NO_BUDGET"
UNAPPROVED_OVER_BUDGET = "UNAPPROVED_OVER_BUDGET"
TASK_MAX_FILES = 8
NON_GATING_CODES = frozenset({UNAPPROVED_OVER_BUDGET})

_HEADER_ALIASES = {
    "план": "plan",
    "plan": "plan",
    "ветка": "branch",
    "branch": "branch",
    "фаза": "phase",
    "phase": "phase",
    "задачи": "tasks",
    "tasks": "tasks",
    "статус": "status",
    "status": "status",
    "обновлено": "updated",
    "updated": "updated",
}
_ACTIVE_STEMS = ("актив", "active")
_ARCHIVE_STEMS = ("архив", "archive")

_FENCE_RE = re.compile(r"^\s*(```|~~~)")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
_TASK_HEADER_RE = re.compile(r"^###\s+Task\s+(\d+\.\d+)(?!\d)")
_TASK_H1_HEADER_RE = re.compile(r"^#\s+Task\s+(\d+\.\d+)(?!\d)")
_PHASE_HEADING_RE = re.compile(r"^##\s+Phase\s+(\d+)(?!\d)", re.IGNORECASE)
_PHASE_FILE_RE = re.compile(r"^phase-(\d+)\.md$")
_TASK_STEM_RE = re.compile(r"^(\d+)\.(\d+)$")
_CHECKBOX_RE = re.compile(r"^\s*[-*+]\s+\[([ xX])\]")
_LIST_ITEM_RE = re.compile(r"^\s*[-*+]\s+")
_ORDER_TITLE_RE = re.compile(r"^(порядок выполнения|execution order)\b", re.IGNORECASE)
_ORDER_MARKER_RE = re.compile(
    r"\[(DONE|PENDING|IN[ _]PROGRESS|BLOCKED|SKIPPED|CANCELLED)\]"
)
# A task-index line inside a «Порядок выполнения» section — same shape as
# task_order_marker()'s per-task line_re, generalised to any task id. Used by
# contract_fingerprint to cut the marker tail ONLY here, not on an arbitrary
# line that happens to contain a `[DONE]`-shaped token (Task 5.1 fix, F7).
_ORDER_TASK_LINE_RE = re.compile(
    r"^\s*[-*+]\s+(?:\[[ xX]\]\s+)?(?:\*\*)?Task\s+\d+\.\d+(?!\d)"
)
_JOURNAL_HEADING_RE = re.compile(r"^(progress log|журнал|journal)\b", re.IGNORECASE)
_DATED_NAME_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})_")
_BRANCH_RE = re.compile(
    r"\*\*(?:Ветка|Branch)\s*:?\*\*\s*:?\s*(?:`([^`]+)`|(\S+))", re.IGNORECASE
)
_LINK_RE = re.compile(r"^\[[^\]]*\]\(([^)\s]+)\)$")
_SEPARATOR_CELL_RE = re.compile(r"^:?-+:?$")
_UNESCAPED_PIPE_RE = re.compile(r"(?<!\\)\|")
# Plan gate (Task 4.2) — a plan's Budget section, a task's required fields
# (Files/Acceptance/Handoff, Russian aliases included) and the Files field's
# path count. See check_plan_gate().
_BUDGET_HEADING_RE = re.compile(r"^#{2,6}\s+(Бюджет|Budget)\b", re.IGNORECASE)
_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "Files": ("файлы", "files"),
    "Acceptance": ("acceptance criteria", "acceptance", "приёмка"),
    "Handoff": ("handoff", "chain"),
}
_FIELD_PATTERNS: dict[str, re.Pattern[str]] = {
    name: re.compile(
        r"^\s*(?:[-*+]\s+)?\**\s*(?:"
        + "|".join(re.escape(alias) for alias in aliases)
        + r")\b[^:\n]*:",
        re.IGNORECASE,
    )
    for name, aliases in _FIELD_ALIASES.items()
}
# ANY field label ends a field's block, known or not: a bold label in any
# language (`- **Дизайн:** …`, `**Steps:**`) or an ALL-CAPS brief label
# (`REDS (predicted …):`, `OUT OF SCOPE:`). Lead probe, Task 4.2: stopping only
# at Files/Acceptance/Handoff counted the paths of the «Дизайн» line as Files.
_ANY_FIELD_LABEL_RE = re.compile(
    r"^\s*(?:[-*+]\s+)?(?:\*\*[^*\n]+:\*\*|\*\*[^*\n]+\*\*\s*:"
    r"|[A-ZА-ЯЁ][A-ZА-ЯЁ \-/]{2,}(?:[ \t]*\(.*)?:)"
)
# A task nobody will ever brief — exempt from the gate like a closed one.
_GATE_EXEMPT_MARKERS = frozenset({"SKIPPED", "CANCELLED"})
_BACKTICK_SPAN_RE = re.compile(r"`([^`\s]+)`")
_PATH_EXT_RE = re.compile(r"\.\w{1,5}$")

# Executor brief assembly (Task 5.2): `brief <id>` renders tasks/<id>.md plus
# the standing blocks of dev/templates/executor-brief.md. `_BRIEF_LABEL_RE` is
# copied byte-for-byte from dev/hooks/lint-brief.sh's `LABEL_RE` (not
# imported — that hook is bash-invoked; this module is pure Python and stays
# stdlib-only per ADR-0002) so a rendered brief opens the same label blocks
# the hook's PreToolUse lint will parse when the brief is later pasted into a
# spawn prompt.
_BRIEF_LABEL_RE = re.compile(r"^[ \t]*([A-Z][A-Z \-/]{2,})(?:[ \t]*\(.*)?:")
_BRIEF_REQUIRED_FIELDS = (
    "TASK",
    "ROLE",
    "DESIGN",
    "FILES",
    "REDS",
    "TESTS",
    "OUT OF SCOPE",
)
_BRIEF_STANDING_BLOCKS = ("FIRST EDIT", "TEST RULES", "BUDGET", "COMMIT", "REPORT")


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PlanSummary:
    done: int
    total: int
    phase: str | None
    open_tasks: list[str] = field(default_factory=list)
    dropped: int = 0


@dataclass
class LedgerTable:
    active: dict[str, dict[str, str]] = field(default_factory=dict)
    archive: dict[str, dict[str, str]] = field(default_factory=dict)


@dataclass(frozen=True)
class Finding:
    code: str
    plan: str
    detail: str

    @property
    def fixable(self) -> bool:
        return self.code in FIXABLE_CODES

    @property
    def gating(self) -> bool:
        return self.code not in NON_GATING_CODES


@dataclass(frozen=True)
class ArchiveResult:
    new_path: Path
    quarter: str
    old_rel: str
    new_rel: str
    moved_with_git: bool
    diff: str
    summary_path: Path | None = None


@dataclass(frozen=True)
class FixReport:
    plan: str
    changed: bool
    text: str


# ---------------------------------------------------------------------------
# Reading plans
# ---------------------------------------------------------------------------


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _unfenced_lines(text: str) -> list[tuple[str, bool]]:
    """``(line, inside_code_fence)`` — headings and checkboxes in fenced
    examples (a plan quoting a template) must not count."""
    out: list[tuple[str, bool]] = []
    in_fence = False
    for line in text.splitlines():
        if _FENCE_RE.match(line):
            out.append((line, True))
            in_fence = not in_fence
            continue
        out.append((line, in_fence))
    return out


def _task_file_sort_key(path: Path) -> tuple[int, tuple[int, int] | str]:
    """Numeric task-id order (``1.2`` < ``1.10``); a non-``N.M`` stem sorts
    last, by name."""
    m = _TASK_STEM_RE.match(path.stem)
    if m:
        return (0, (int(m.group(1)), int(m.group(2))))
    return (1, path.name)


def discover_plan_files(path: Path) -> list[Path]:
    """A single-file plan, or ``plan.md`` + ``phase-N.md`` (numeric order) +
    ``tasks/<id>.md`` (numeric task-id order, ``*.result.md`` excluded — plan
    layout v2, Task 2.3). ``amendments.md``/``decisions.md``/``SUMMARY.md``/
    ``injections.md`` are never returned — they carry no task content."""
    path = Path(path)
    if path.is_file():
        return [path]
    if not path.is_dir():
        raise FileNotFoundError(path)
    found: list[Path] = []
    if (path / "plan.md").is_file():
        found.append(path / "plan.md")
    phases = [
        (int(m.group(1)), p)
        for p in path.iterdir()
        if p.is_file() and (m := _PHASE_FILE_RE.match(p.name))
    ]
    found.extend(p for _, p in sorted(phases))
    tasks_dir = path / "tasks"
    if tasks_dir.is_dir():
        task_files = [
            p
            for p in tasks_dir.iterdir()
            if p.is_file() and p.suffix == ".md" and not p.name.endswith(".result.md")
        ]
        found.extend(sorted(task_files, key=_task_file_sort_key))
    return found


def extract_task_ids(text: str, in_task_file: bool = False) -> list[str]:
    """Task ids from ``### Task X.Y`` headings; with ``in_task_file=True``
    (a ``tasks/<id>.md`` file, which naturally starts with an H1) also accepts
    a bare ``# Task X.Y`` heading — the global ``###`` form is never loosened."""
    ids: list[str] = []
    for line, fenced in _unfenced_lines(text):
        if fenced:
            continue
        m = _TASK_HEADER_RE.match(line)
        if m is None and in_task_file:
            m = _TASK_H1_HEADER_RE.match(line)
        if m and m.group(1) not in ids:
            ids.append(m.group(1))
    return ids


def _task_body(text: str, task_id: str) -> list[str] | None:
    """Lines under the task's heading, up to the next heading at the same or
    a shallower level. A ``tasks/<id>.md`` file's own heading is H1, so this
    naturally becomes "the whole file" (or up to the next task file's H1, in
    a multi-file joined ``all_text``) — there is nothing shallower to stop at."""
    lines = _unfenced_lines(text)
    for i, (line, fenced) in enumerate(lines):
        if fenced:
            continue
        m = _TASK_HEADER_RE.match(line)
        start_level = 3
        if m is None:
            m = _TASK_H1_HEADER_RE.match(line)
            start_level = 1
        if not m or m.group(1) != task_id:
            continue
        body: list[str] = []
        for nxt, nxt_fenced in lines[i + 1 :]:
            heading = None if nxt_fenced else _HEADING_RE.match(nxt)
            if heading and len(heading.group(1)) <= start_level:
                break
            if not nxt_fenced:
                body.append(nxt)
        return body
    return None


def task_checkbox_totals(text: str, task_id: str) -> tuple[int, int] | None:
    """``(checked, total)`` checkboxes under the task heading; ``None`` when the
    task is absent or carries no checkbox at all."""
    body = _task_body(text, task_id)
    if body is None:
        return None
    marks = [m.group(1) for line in body if (m := _CHECKBOX_RE.match(line))]
    if not marks:
        return None
    return sum(1 for mark in marks if mark in "xX"), len(marks)


def task_order_marker(all_text: str, task_id: str) -> str | None:
    """The ``[DONE]``/``[PENDING]``/… marker of the task's line in a
    «Порядок выполнения» section, or ``None``."""
    line_re = re.compile(
        r"^\s*[-*+]\s+(?:\[[ xX]\]\s+)?(?:\*\*)?Task\s+"
        + re.escape(task_id)
        + r"(?!\d)"
    )
    section_level: int | None = None
    for line, fenced in _unfenced_lines(all_text):
        if fenced:
            continue
        heading = _HEADING_RE.match(line)
        if heading:
            level = len(heading.group(1))
            if _ORDER_TITLE_RE.match(heading.group(2)):
                section_level = level
                continue
            if section_level is not None and level <= section_level:
                section_level = None
            continue
        if section_level is None or not line_re.match(line):
            continue
        marker = _ORDER_MARKER_RE.search(line)
        if marker:
            return marker.group(1).upper().replace(" ", "_")
    return None


def is_task_closed(
    all_text: str, task_id: str, checkbox_text: str | None = None
) -> bool:
    """Closed when the «Порядок выполнения» marker in *all_text* says DONE, or
    else when every checkbox is ticked. Checkbox totals are read from
    *checkbox_text* when given (a task's own ``tasks/<id>.md`` body, so a
    stale ``### Task N.M`` section elsewhere in *all_text* cannot win — Task
    2.3 review, F3) and from *all_text* itself otherwise."""
    if task_order_marker(all_text, task_id) == "DONE":
        return True
    totals = task_checkbox_totals(
        checkbox_text if checkbox_text is not None else all_text, task_id
    )
    return totals is not None and totals[0] == totals[1]


def summarize_plan(paths: list[Path]) -> PlanSummary:
    texts = [(Path(p), _read(Path(p))) for p in paths]
    all_text = "\n".join(text for _, text in texts)
    # A task id's own tasks/<id>.md text, when it has one — threaded into
    # is_task_closed() below so its checkboxes win over a stale `### Task
    # N.M` section elsewhere (e.g. plan.md), regardless of which file's
    # heading is encountered first in document order (Task 2.3 review, F3).
    task_file_text: dict[str, str] = {}
    for path, text in texts:
        if path.parent.name != "tasks":
            continue
        for task_id in extract_task_ids(text, in_task_file=True):
            task_file_text.setdefault(task_id, text)
    seen: set[str] = set()
    done = 0
    dropped = 0
    open_tasks: list[str] = []
    phase: str | None = None
    for path, text in texts:
        file_match = _PHASE_FILE_RE.match(path.name)
        current_phase = file_match.group(1) if file_match else None
        in_task_file = path.parent.name == "tasks"
        for line, fenced in _unfenced_lines(text):
            if fenced:
                continue
            phase_heading = _PHASE_HEADING_RE.match(line)
            if phase_heading:
                current_phase = phase_heading.group(1)
                continue
            m = _TASK_HEADER_RE.match(line)
            if m is None and in_task_file:
                m = _TASK_H1_HEADER_RE.match(line)
            if not m or m.group(1) in seen:
                continue
            task_id = m.group(1)
            seen.add(task_id)
            if is_task_closed(all_text, task_id, task_file_text.get(task_id)):
                done += 1
                continue
            if task_order_marker(all_text, task_id) in _GATE_EXEMPT_MARKERS:
                dropped += 1
                continue
            open_tasks.append(task_id)
            if phase is None and current_phase is not None:
                phase = f"phase {current_phase}"
    return PlanSummary(
        done=done,
        total=len(seen),
        phase=phase,
        open_tasks=open_tasks,
        dropped=dropped,
    )


def _plan_branch(paths: list[Path]) -> str | None:
    for path in paths:
        m = _BRANCH_RE.search(_read(path))
        if m:
            return (m.group(1) or m.group(2)).strip()
    return None


# ---------------------------------------------------------------------------
# Ledger table
# ---------------------------------------------------------------------------


def parse_ledger_row_path(cell: str) -> str:
    cell = cell.strip()
    link = _LINK_RE.match(cell)
    if link:
        cell = link.group(1)
    cell = cell.strip("`").strip()
    if cell.startswith("./"):
        cell = cell[2:]
    return cell


def _cells(line: str) -> list[str] | None:
    """Table cells of one Markdown row. An escaped pipe (``\\|``) does not
    split a cell — it is unescaped back to a literal ``|`` in the result
    (Task 5.1: an ``amendments.md`` «почему» cell may quote one)."""
    stripped = line.strip()
    if not stripped.startswith("|"):
        return None
    stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [c.strip().replace("\\|", "|") for c in _UNESCAPED_PIPE_RE.split(stripped)]


def _section_of(title: str) -> str | None:
    lowered = re.sub(r"^[^\wа-яё]+", "", title.lower())
    if lowered.startswith(_ACTIVE_STEMS):
        return "active"
    if lowered.startswith(_ARCHIVE_STEMS):
        return "archive"
    return None


@dataclass
class _TableSpan:
    section: str
    header: int  # line index of the header row
    end: int  # one past the last row line
    columns: list[str]
    rows: list[tuple[int, str, dict[str, str]]]  # (line index, key, row)


def _locate_tables(lines: list[str]) -> list[_TableSpan]:
    spans: list[_TableSpan] = []
    section: str | None = None
    current: _TableSpan | None = None
    in_fence = False
    for i, line in enumerate(lines):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            current = None
            continue
        if in_fence:
            continue
        heading = _HEADING_RE.match(line)
        if heading:
            section = _section_of(heading.group(2))
            current = None
            continue
        cells = _cells(line)
        if cells is None:
            current = None
            continue
        if current is None:
            columns = [_HEADER_ALIASES.get(c.lower(), "") for c in cells]
            # A ledger header names all six columns, "plan" first — the previous
            # template's `| План | Тип | Статус | Остаток |` is prose, not a ledger.
            if (
                section is not None
                and columns
                and columns[0] == "plan"
                and set(LEDGER_COLUMNS) <= set(columns)
            ):
                current = _TableSpan(section, i, i + 1, columns, [])
                spans.append(current)
            continue
        current.end = i + 1
        if all(_SEPARATOR_CELL_RE.match(c) for c in cells if c):
            continue
        row = {
            col: (cells[j] if j < len(cells) else "")
            for j, col in enumerate(current.columns)
            if col
        }
        key = parse_ledger_row_path(row.get("plan", ""))
        if key:
            current.rows.append((i, key, row))
    return spans


def parse_ledger_table(readme_text: str) -> LedgerTable:
    table = LedgerTable()
    for span in _locate_tables(readme_text.splitlines()):
        target = table.active if span.section == "active" else table.archive
        for _, key, row in span.rows:
            target[key] = row
    return table


def render_row(
    plan: str, branch: str, phase: str, tasks: str, status: str, updated: str
) -> str:
    return f"| {plan} | {branch} | {phase} | {tasks} | {status} | {updated} |"


def plan_cell(rel: str) -> str:
    """``[slug](rel)`` — the slug without the date prefix."""
    parts = rel.rstrip("/").split("/")
    name = parts[-2] if parts[-1] == "plan.md" and len(parts) > 1 else parts[-1]
    if name.endswith(".md"):
        name = name[:-3]
    slug = _DATED_NAME_RE.sub("", name) or name
    return f"[{slug}]({rel})"


def _slug_for_key(key: str) -> str:
    """The plan key without ``/plan.md``/``.md`` and without the date prefix —
    same reduction as ``plan_cell()``'s link text, without the Markdown wrapper."""
    parts = key.rstrip("/").split("/")
    name = parts[-2] if parts[-1] == "plan.md" and len(parts) > 1 else parts[-1]
    if name.endswith(".md"):
        name = name[:-3]
    return _DATED_NAME_RE.sub("", name) or name


def _canonical(key: str) -> str:
    key = key.strip()
    if key.startswith("plans/"):
        key = key[len("plans/") :]
    if key.endswith("/"):
        key += "plan.md"
    parts = key.split("/")
    if len(parts) >= 2 and _PHASE_FILE_RE.match(parts[-1]):
        key = "/".join([*parts[:-1], "plan.md"])
    return key


# ---------------------------------------------------------------------------
# Plans on disk
# ---------------------------------------------------------------------------


def _plans_dir(root: Path) -> Path:
    return Path(root) / "plans"


def list_active_plans(root: Path) -> dict[str, Path]:
    """Ledger key -> plan path for every plan directly under ``plans/``. A
    directory needs its own ``plan.md`` to count as a plan — a ``tasks/``
    folder with no ``plan.md`` (e.g. mid-migration) is skipped (Task 2.3
    review, F7)."""
    plans_dir = _plans_dir(root)
    found: dict[str, Path] = {}
    if not plans_dir.is_dir():
        return found
    for entry in sorted(plans_dir.iterdir()):
        if entry.name.startswith(("_", ".")) or entry.name.lower() == "readme.md":
            continue
        if entry.is_file() and entry.suffix == ".md":
            found[entry.name] = entry
        elif entry.is_dir() and (entry / "plan.md").is_file():
            found[f"{entry.name}/plan.md"] = entry
    return found


def resolve_plan(root: Path, plan: str) -> tuple[str, Path]:
    """``(ledger key, plan path)`` for a CLI argument like ``slug-dir``,
    ``slug-dir/plan.md``, ``plans/x.md`` or ``_archive/2026-Q2/x.md``."""
    plans_dir = _plans_dir(root)
    rel = plan.strip().replace("\\", "/")
    if rel.startswith("plans/"):
        rel = rel[len("plans/") :]
    rel = rel.rstrip("/")
    if rel.startswith("/") or ".." in rel.split("/") or re.match(r"^[A-Za-z]:", rel):
        raise ValueError(f"plan reference must stay inside plans/: {plan}")
    candidate = plans_dir / rel
    if candidate.is_dir() and discover_plan_files(candidate):
        return f"{rel}/plan.md", candidate
    if candidate.is_file():
        parent = candidate.parent
        if parent != plans_dir and (
            candidate.name == "plan.md" or _PHASE_FILE_RE.match(candidate.name)
        ):
            return _canonical(rel), parent
        return rel, candidate
    raise FileNotFoundError(f"plan not found: plans/{rel}")


def plan_for_branch(root: Path, branch: str) -> tuple[str, Path] | None:
    """``(ledger key, plan path)`` for the active plan tracking *branch*.

    The ledger row wins when a row's ``branch`` cell names *branch* exactly;
    otherwise fall back to the plan's own declared branch (a
    ``- **Ветка/Branch:**`` line, same route as the `Refs:` gate's
    ``_plan_branch()``). Two active plans claiming the same branch — by
    ledger row, or (failing that) by declared header — is ambiguous:
    ``None``, so callers (the SessionStart banner) fall back to their own
    signal rather than silently pick one. ``None`` also when no active plan
    claims the branch at all."""
    plans_dir = _plans_dir(root)
    readme = plans_dir / "README.md"
    table = parse_ledger_table(_read(readme)) if readme.is_file() else LedgerTable()
    active_rows = {_canonical(k): v for k, v in table.active.items()}
    active_plans = list_active_plans(root)

    row_matches = [
        (key, path)
        for key, path in active_plans.items()
        if (row := active_rows.get(_canonical(key)))
        and row.get("branch", "").strip() == branch
    ]
    if len(row_matches) > 1:
        return None
    if row_matches:
        return row_matches[0]

    header_matches = [
        (key, path)
        for key, path in active_plans.items()
        if _plan_branch(discover_plan_files(path)) == branch
    ]
    if len(header_matches) > 1:
        return None
    if header_matches:
        return header_matches[0]
    return None


def resolve_plan_path(root: Path, plan_arg: str) -> tuple[str, Path] | None:
    """``(ledger key, plan path)`` for a plan named by a filesystem path —
    absolute, relative to the current working directory, or the
    ``plans/``-relative form :func:`resolve_plan` accepts for ``add``/
    ``close`` (e.g. ``2026-05-01_slug`` or ``2026-05-01_slug/plan.md``).
    Used by ``status --plan``, where the caller (the SessionStart banner)
    has already resolved a branch to a plan file via
    ``validate_commit.py --resolve-plan`` and only needs the matching
    ledger row — no branch matching happens here.

    ``None`` when *plan_arg* does not resolve to any plan directly under
    ``plans/`` (a nonexistent path, or one outside every active plan)."""
    raw = plan_arg.strip().replace("\\", "/")
    root = Path(root)
    plans_dir = _plans_dir(root)
    p = Path(raw)
    candidates: list[Path] = (
        [p] if p.is_absolute() else [Path.cwd() / raw, root / raw, plans_dir / raw]
    )
    resolved_candidates: set[Path] = set()
    for c in candidates:
        try:
            resolved_candidates.add(c.resolve())
        except OSError:
            continue
    if not resolved_candidates:
        return None
    for key, path in list_active_plans(root).items():
        try:
            path_resolved = path.resolve()
        except OSError:
            continue
        matches = {path_resolved}
        if path.is_dir():
            try:
                matches.add((path / "plan.md").resolve())
            except OSError:
                pass
        if resolved_candidates & matches:
            return key, path
    return None


def quarter_for(name: str) -> str:
    m = _DATED_NAME_RE.match(name)
    if not m:
        raise ValueError(f"{name}: no YYYY-MM-DD_ prefix — cannot pick a quarter")
    month = int(m.group(2))
    if not 1 <= month <= 12:
        raise ValueError(f"{name}: month {month} out of range")
    return f"{m.group(1)}-Q{(month - 1) // 3 + 1}"


def _is_done(summary: PlanSummary, row: dict[str, str] | None) -> bool:
    """A plan is done when every task is either closed or dropped
    (``[SKIPPED]``/``[CANCELLED]`` — Task 5.3), or the ledger row says so."""
    if summary.total > 0 and summary.done + summary.dropped == summary.total:
        return True
    return bool(row) and row.get("status", "").strip().upper() in {"DONE", "ARCHIVED"}


def _journal_findings(plan_file: Path, label: str) -> list[Finding]:
    """``JOURNAL_IN_PLAN`` — a Progress-log-like heading in *plan_file* whose
    section holds more than ``JOURNAL_MAX_ITEMS`` list items (the 176 KB plan
    this guards against had 57)."""
    lines = _unfenced_lines(_read(plan_file))
    findings: list[Finding] = []
    i, n = 0, len(lines)
    while i < n:
        line, fenced = lines[i]
        heading = None if fenced else _HEADING_RE.match(line)
        if not heading or not _JOURNAL_HEADING_RE.match(heading.group(2)):
            i += 1
            continue
        level = len(heading.group(1))
        count = 0
        j = i + 1
        while j < n:
            nxt, nxt_fenced = lines[j]
            nxt_heading = None if nxt_fenced else _HEADING_RE.match(nxt)
            if nxt_heading and len(nxt_heading.group(1)) <= level:
                break
            if not nxt_fenced and _LIST_ITEM_RE.match(nxt):
                count += 1
            j += 1
        if count > JOURNAL_MAX_ITEMS:
            findings.append(
                Finding(
                    JOURNAL_IN_PLAN,
                    label,
                    f"{heading.group(2)!r} has {count} entries > "
                    f"{JOURNAL_MAX_ITEMS} budget — move the journal to "
                    "docs/sessions/",
                )
            )
        i = j
    return findings


def check_plan_sizes(plan_dir_or_file: Path) -> list[Finding]:
    """Size-budget findings for one plan — never for anything under
    ``_archive/`` or a file/dir whose name starts with ``_``.

    Pre:
      - *plan_dir_or_file* exists (a single-file plan, or a plan directory).
    Post:
      - Read-only; sizes are bytes on disk.
      - Codes: PLAN_TOO_BIG (``plan.md`` > ``PLAN_MAX_BYTES``, or a
        single-file plan > ``SINGLE_PLAN_MAX_BYTES``), TASK_TOO_BIG
        (``tasks/<id>.md`` > ``TASK_MAX_BYTES``, ``phase-N.md`` >
        ``PHASE_MAX_BYTES``), JOURNAL_IN_PLAN (see ``_journal_findings``),
        RESULT_TOO_BIG (a plan directory's ``tasks/<id>.result.md`` >
        ``RESULT_MAX_BYTES`` — Task 5.3; never for a single-file plan, which
        has no ``tasks/`` directory). None of the four is ``fixable``.
    """
    path = Path(plan_dir_or_file)
    if path.name.startswith("_") or "_archive" in path.parts:
        return []
    is_dir = path.is_dir()
    plan_files = discover_plan_files(path) if is_dir else [path]
    plan_limit = PLAN_MAX_BYTES if is_dir else SINGLE_PLAN_MAX_BYTES

    findings: list[Finding] = []
    for f in plan_files:
        label = f"{path.name}/{f.relative_to(path).as_posix()}" if is_dir else f.name
        size = f.stat().st_size
        is_plan_doc = f.name == "plan.md" or not is_dir
        if is_plan_doc:
            if size > plan_limit:
                findings.append(
                    Finding(
                        PLAN_TOO_BIG,
                        label,
                        f"{size / 1024:.1f} KB > {plan_limit / 1024:.0f} KB budget"
                        " — move task bodies to tasks/<id>.md",
                    )
                )
        else:
            limit = TASK_MAX_BYTES if f.parent.name == "tasks" else PHASE_MAX_BYTES
            remedy = (
                "split into smaller tasks/<id>.md files"
                if f.parent.name == "tasks"
                else "move task bodies to tasks/<id>.md"
            )
            if size > limit:
                findings.append(
                    Finding(
                        TASK_TOO_BIG,
                        label,
                        f"{size / 1024:.1f} KB > {limit / 1024:.0f} KB budget — {remedy}",
                    )
                )
        # Every file is scanned for a journal section (Task 2.3 review, F2) —
        # not only plan.md / the single-file plan.
        findings.extend(_journal_findings(f, label))

    # Result files (Task 5.3): never a plan-doc/task source
    # (discover_plan_files excludes them), so they are scanned separately —
    # only for a plan directory, sorted for a deterministic finding order.
    if is_dir:
        tasks_dir = path / "tasks"
        if tasks_dir.is_dir():
            result_files = sorted(
                p
                for p in tasks_dir.iterdir()
                if p.is_file() and p.name.endswith(".result.md")
            )
            for f in result_files:
                label = f"{path.name}/{f.relative_to(path).as_posix()}"
                size = f.stat().st_size
                if size > RESULT_MAX_BYTES:
                    findings.append(
                        Finding(
                            RESULT_TOO_BIG,
                            label,
                            f"{size / 1024:.1f} KB > {RESULT_MAX_BYTES / 1024:.0f} KB"
                            " budget — keep SHA, acceptance numbers and "
                            "deviations only — the story goes to docs/sessions/",
                        )
                    )
    return findings


def _field_block(body: list[str], start: int) -> list[str]:
    """*body* lines from *start* (a field line) up to the next field label
    of ANY name (``_ANY_FIELD_LABEL_RE``), a heading, or the end of *body*."""
    block = [body[start]]
    for line in body[start + 1 :]:
        if _HEADING_RE.match(line):
            break
        if _ANY_FIELD_LABEL_RE.match(line):
            break
        block.append(line)
    return block


def _count_files_field_paths(block: list[str]) -> int:
    """Distinct backtick spans in *block* that look like a path: no
    whitespace, and either a ``/`` or a short extension."""
    spans: set[str] = set()
    for line in block:
        for span in _BACKTICK_SPAN_RE.findall(line):
            if "/" in span or _PATH_EXT_RE.search(span):
                spans.add(span)
    return len(spans)


def check_plan_gate(plan_dir_or_file: Path) -> list[Finding]:
    """``check_plan_sizes(path)`` plus the amendment-6 plan-gate findings:
    a missing Budget section, an open task missing a required field, and a
    Files field naming too many paths.

    Pre:
      - *plan_dir_or_file* exists (a single-file plan, or a plan directory).
    Post:
      - Read-only; never for anything under ``_archive/`` or a file/dir
        whose name starts with ``_`` (same exemption as
        :func:`check_plan_sizes`).
      - NO_BUDGET: ``plan.md`` (or the single-file plan) has no unfenced
        heading matching ``^#{2,6}\\s+(Бюджет|Budget)\\b``.
      - TASK_INCOMPLETE: one finding per OPEN task (:func:`is_task_closed`
        is False, checked the same way :func:`summarize_plan` does, and its
        order marker is not ``[SKIPPED]``/``[CANCELLED]``) missing
        one or more of the Files/Acceptance/Handoff fields (Russian aliases
        файлы/приёмка accepted; ``acceptance criteria`` accepted for
        Acceptance, ``chain`` for Handoff) as an unfenced
        ``- **<field>:**``-shaped line in the task's body.
      - TASK_TOO_MANY_FILES: an open task whose Files field names more than
        ``TASK_MAX_FILES`` distinct backtick-quoted paths.
      - None of the four codes is ``fixable``.
    """
    path = Path(plan_dir_or_file)
    findings = check_plan_sizes(path)
    if path.name.startswith("_") or "_archive" in path.parts:
        return findings

    is_dir = path.is_dir()
    plan_files = discover_plan_files(path)
    texts = [(p, _read(p)) for p in plan_files]
    all_text = "\n".join(text for _, text in texts)

    plan_doc = next((p for p, _ in texts if p.name == "plan.md" or not is_dir), None)
    if plan_doc is not None:
        doc_text = next(text for p, text in texts if p == plan_doc)
        has_budget = any(
            not fenced and _BUDGET_HEADING_RE.match(line)
            for line, fenced in _unfenced_lines(doc_text)
        )
        if not has_budget:
            label = (
                f"{path.name}/{plan_doc.relative_to(path).as_posix()}"
                if is_dir
                else plan_doc.name
            )
            findings.append(
                Finding(
                    NO_BUDGET,
                    label,
                    "no Budget/Бюджет section (## Budget or ## Бюджет)",
                )
            )

    # Same task-file threading as summarize_plan(): a tasks/<id>.md file's
    # own text wins over a stale ### section of the same id elsewhere.
    task_file_text: dict[str, str] = {}
    task_file_path: dict[str, Path] = {}
    for p, text in texts:
        if p.parent.name != "tasks":
            continue
        for task_id in extract_task_ids(text, in_task_file=True):
            task_file_text.setdefault(task_id, text)
            task_file_path.setdefault(task_id, p)

    seen: set[str] = set()
    for p, text in texts:
        in_task_file = p.parent.name == "tasks"
        for task_id in extract_task_ids(text, in_task_file=in_task_file):
            if task_id in seen:
                continue
            seen.add(task_id)
            if is_task_closed(all_text, task_id, task_file_text.get(task_id)):
                continue
            if task_order_marker(all_text, task_id) in _GATE_EXEMPT_MARKERS:
                continue
            source_text = task_file_text.get(task_id, all_text)
            body = _task_body(source_text, task_id) or []
            owning_path = task_file_path.get(task_id, p)
            label = (
                f"{path.name}/{owning_path.relative_to(path).as_posix()}"
                if is_dir
                else owning_path.name
            )
            field_match_idx: dict[str, int] = {}
            for name, rx in _FIELD_PATTERNS.items():
                for idx, line in enumerate(body):
                    if rx.match(line):
                        field_match_idx[name] = idx
                        break
            missing = [
                name
                for name in ("Files", "Acceptance", "Handoff")
                if name not in field_match_idx
            ]
            if missing:
                findings.append(
                    Finding(
                        TASK_INCOMPLETE,
                        label,
                        f"Task {task_id}: missing field(s): {', '.join(missing)}",
                    )
                )
            if "Files" in field_match_idx:
                block = _field_block(body, field_match_idx["Files"])
                n = _count_files_field_paths(block)
                if n > TASK_MAX_FILES:
                    findings.append(
                        Finding(
                            TASK_TOO_MANY_FILES,
                            label,
                            f"Task {task_id}: {n} paths in Files > "
                            f"{TASK_MAX_FILES} — split the task",
                        )
                    )
    return findings


def check_ledger(root: Path) -> list[Finding]:
    """Findings for plans under ``plans/`` against the ledger in its README,
    plus each active plan's size-budget findings (``check_plan_sizes``).

    Pre:
      - *root* is a directory (``plans/`` may be absent -> ``[]``).
    Post:
      - Read-only: writes nothing, runs no git.
      - Each finding's ``code`` is one of DONE_NOT_ARCHIVED, MISSING_ROW,
        ROW_WITHOUT_FILE, PLAN_TOO_BIG, TASK_TOO_BIG, JOURNAL_IN_PLAN,
        RESULT_TOO_BIG, CONTRACT_DRIFT, SCOPE_GREW (see
        ``check_plan_contract``), UNAPPROVED_OVER_BUDGET; only
        DONE_NOT_ARCHIVED and MISSING_ROW are ``fixable``.
      - Amendment 6: an active plan without a *readable* ``contract.lock``
        (a single-file plan, or ``_read_contract_lock`` returns ``None``)
        never contributes its own PLAN_TOO_BIG/TASK_TOO_BIG/JOURNAL_IN_PLAN
        findings directly — sizes gate only after ``approve``. Instead, when
        one or more such plans carry a size finding, exactly ONE
        UNAPPROVED_OVER_BUDGET finding is appended, naming the plan owning
        the largest plan file among them. A plan WITH a readable lock still
        contributes its size findings as before.
    """
    plans_dir = _plans_dir(root)
    if not plans_dir.is_dir():
        return []
    readme = plans_dir / "README.md"
    table = parse_ledger_table(_read(readme)) if readme.is_file() else LedgerTable()
    active_rows = {_canonical(k): v for k, v in table.active.items()}
    archive_rows = {_canonical(k): v for k, v in table.archive.items()}

    findings: list[Finding] = []
    unlocked_over_budget: list[tuple[str, Path]] = []
    for key, path in list_active_plans(root).items():
        is_dir = path.is_dir()
        lock_path = path / "contract.lock" if is_dir else None
        has_lock = (
            is_dir
            and lock_path is not None
            and lock_path.is_file()
            and _read_contract_lock(lock_path) is not None
        )
        size_findings = check_plan_sizes(path)
        if has_lock:
            findings.extend(size_findings)
        elif size_findings:
            unlocked_over_budget.append((key, path))
        findings.extend(check_plan_contract(path))
        row = active_rows.get(key) or archive_rows.get(key)
        summary = summarize_plan(discover_plan_files(path))
        if _is_done(summary, row):
            reason = (
                f"all {summary.total} task(s) closed"
                if summary.total and summary.done == summary.total
                else "ledger row says DONE"
            )
            suffix = "" if row else "; no ledger row"
            findings.append(
                Finding(
                    DONE_NOT_ARCHIVED,
                    key,
                    f"done ({reason}{suffix}), not archived — "
                    f"belongs in plans/_archive/<YYYY-Qn>/",
                )
            )
        elif row is None:
            findings.append(
                Finding(
                    MISSING_ROW,
                    key,
                    f"plan has no ledger row ({summary.done}/{summary.total} tasks)",
                )
            )
    for section, rows in (("active", active_rows), ("archive", archive_rows)):
        for key in rows:
            if not (plans_dir / key).exists():
                findings.append(
                    Finding(
                        ROW_WITHOUT_FILE,
                        key,
                        f"{section} ledger row points at a missing plans/{key}",
                    )
                )
    if unlocked_over_budget:
        n = len(unlocked_over_budget)
        largest_size = -1
        largest_label = ""
        largest_key = ""
        for key, path in unlocked_over_budget:
            is_dir = path.is_dir()
            for f in discover_plan_files(path) if is_dir else [path]:
                size = f.stat().st_size
                if size > largest_size:
                    largest_size = size
                    largest_label = (
                        f"{path.name}/{f.relative_to(path).as_posix()}"
                        if is_dir
                        else f.name
                    )
                    largest_key = key
        findings.append(
            Finding(
                UNAPPROVED_OVER_BUDGET,
                largest_key,
                f"{n} unapproved plan(s) over the size budget, largest "
                f"{largest_label} {largest_size / 1024:.1f} KB — sizes gate "
                "only after `approve`",
            )
        )
    return findings


# ---------------------------------------------------------------------------
# Writing the ledger
# ---------------------------------------------------------------------------


def _today(today: str | None) -> str:
    return today or _dt.date.today().isoformat()


def _split_text(text: str) -> tuple[list[str], str]:
    eol = "\r\n" if "\r\n" in text else "\n"
    return text.splitlines(), eol


def _join_text(lines: list[str], eol: str) -> str:
    return eol.join(lines) + eol


def _new_table(title: str, rows: list[str]) -> list[str]:
    return [f"## {title}", "", LEDGER_HEADER, LEDGER_SEPARATOR, *rows]


def _upsert(text: str, section: str, key: str, new_row: str | None) -> str:
    """Drop every row for *key* from both tables; append *new_row* (if any) to
    *section*'s table, creating that table at the end when absent."""
    lines, eol = _split_text(text)
    spans = _locate_tables(lines)
    drop = {i for span in spans for i, k, _ in span.rows if _canonical(k) == key}
    target = next((s for s in spans if s.section == section), None)
    insert_at = target.end if target is not None else None
    out: list[str] = []
    for i, line in enumerate(lines):
        if insert_at is not None and i == insert_at and new_row is not None:
            out.append(new_row)
            new_row = None
        if i not in drop:
            out.append(line)
    if new_row is not None:
        if target is not None:  # table runs to the end of the file
            out.append(new_row)
        else:
            while out and not out[-1].strip():
                out.pop()
            title = "Активные" if section == "active" else "Архив"
            out.extend(["", *_new_table(title, [new_row])])
    return _join_text(out, eol)


def _diff(old: str, new: str, label: str) -> str:
    return "".join(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=f"a/{label}",
            tofile=f"b/{label}",
        )
    )


def _refuse_unsafe_targets(root: Path, *paths: Path) -> None:
    """Raise ``ValueError`` before any write if a target is a symlink or resolves
    outside *root* — a hostile repo must not steer ``--fix`` out of the project."""
    real_root = Path(root).resolve()
    for path in paths:
        if path.is_symlink():
            raise ValueError(f"refusing to write through a symlink: {path}")
        resolved = path.resolve()
        if resolved != real_root and real_root not in resolved.parents:
            raise ValueError(f"refusing to write outside the project: {path}")


def _write_text(path: Path, text: str) -> None:
    """Write *text* to *path* atomically: a partial write (crash, disk full,
    an interrupted ``os.replace``) never truncates the target — a reader
    always sees either the old bytes or the new ones, never a mix (Task 5.1
    fix, F11). ``encoding``/``newline`` are unchanged from before: generated
    files stay byte-stable."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")
    with tmp_path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(text)
    os.replace(tmp_path, path)


def _row_for(
    key: str,
    paths: list[Path],
    existing: dict[str, str] | None,
    *,
    cell: str,
    status: str | None,
    branch: str | None,
    today: str,
) -> str:
    summary = summarize_plan(paths)
    existing = existing or {}
    old_branch = existing.get("branch", "").strip()
    resolved_branch = (
        branch
        or (old_branch if old_branch and old_branch != NO_VALUE else None)
        or _plan_branch(paths)
        or NO_VALUE
    )
    old_status = existing.get("status", "").strip().upper()
    if status is None:
        if old_status in STATUSES:
            status = old_status
        elif summary.total and summary.done == summary.total:
            status = "DONE"
        else:
            status = "ACTIVE" if summary.done else "DRAFT"
    return render_row(
        cell,
        resolved_branch,
        summary.phase or NO_VALUE,
        f"{summary.done}/{summary.total}",
        status,
        today,
    )


def add_row(
    root: Path,
    plan: str,
    *,
    status: str | None = None,
    branch: str | None = None,
    today: str | None = None,
) -> str:
    """Register (or refresh) a plan's row in «Активные». Returns the diff.

    Pre:
      - *plan* resolves to an existing plan under ``plans/`` (no ``..``),
        else ``FileNotFoundError`` / ``ValueError``.
      - *status* is None or one of STATUSES, else ``ValueError``.
      - ``plans/`` and ``plans/README.md`` are not symlinks and stay inside
        *root*, else ``ValueError`` before any write.
    Post:
      - Only ``plans/README.md`` is written, and only when the text changed.
      - Rows of other plans and hand-written text are kept; the plan file is
        never touched. Idempotent: a second call with the same *today*
        returns ``""``.
    """
    if status is not None and status.upper() not in STATUSES:
        raise ValueError(f"status must be one of {', '.join(STATUSES)}")
    key, path = resolve_plan(root, plan)
    readme = _plans_dir(root) / "README.md"
    _refuse_unsafe_targets(root, _plans_dir(root), readme)
    old = _read(readme) if readme.is_file() else ""
    table = parse_ledger_table(old)
    existing = {_canonical(k): v for k, v in table.active.items()}.get(key)
    row = _row_for(
        key,
        discover_plan_files(path),
        existing,
        cell=plan_cell(key),
        status=status.upper() if status else None,
        branch=branch,
        today=_today(today),
    )
    new = _upsert(old, "active", key, row)
    if new != old:
        _write_text(readme, new)
    return _diff(old, new, "plans/README.md")


def _git_tracked(root: Path, path: Path) -> bool:
    try:
        proc = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "--", str(path)],
            cwd=root,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0


def _move(root: Path, src: Path, dst: Path) -> bool:
    """``git mv`` when *src* is tracked, a plain rename otherwise. Returns
    whether git performed the move. A failing ``git mv`` of a tracked plan
    raises ``OSError`` — a plain rename would tear the index apart."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if _git_tracked(root, src):
        proc = subprocess.run(
            ["git", "mv", "--", str(src), str(dst)],
            cwd=root,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout).strip() or f"rc={proc.returncode}"
            raise OSError(f"git mv failed for tracked {src}: {detail}")
        return True
    shutil.move(str(src), str(dst))
    return False


def archive_plan(
    root: Path, plan_rel: str, *, today: str | None = None
) -> ArchiveResult:
    """Move a plan into ``plans/_archive/<YYYY-Qn>/``, move its ledger row into
    «Архив» (status ARCHIVED) and append a line to the quarter README.

    Pre:
      - *plan_rel* resolves to a plan under ``plans/`` (no ``..``), not already
        under ``_archive/``, with a ``YYYY-MM-DD_`` name, else ``ValueError`` /
        ``FileNotFoundError``.
      - ``plans/``, ``_archive/``, ``_archive/<Qn>/``, both READMEs and the
        destination are not symlinks and resolve inside *root*, else
        ``ValueError``; a taken destination -> ``FileExistsError``. All checked
        before any write.
    Post:
      - The plan (file or folder) is moved, never deleted: ``git mv`` when
        tracked (a failing ``git mv`` raises ``OSError`` before the ledger is
        written), a plain rename otherwise.
      - Only the plan's own row changes; every other row is kept.
      - A plan DIRECTORY gains ``SUMMARY.md`` (:func:`build_summary`),
        written into the plan's original location before the move so it
        travels with it; a single-file plan gets none (Task 5.3). A
        :func:`build_summary` failure (``ValueError``, the page still over
        ``TASK_MAX_BYTES`` after the shrunk re-render) is raised here before
        any write or move happens.
    """
    root = Path(root)
    plans_dir = _plans_dir(root)
    key, path = resolve_plan(root, plan_rel)
    if key.startswith("_archive/"):
        raise ValueError(f"plans/{key} is already archived")
    name = path.name
    is_dir = path.is_dir()
    quarter = quarter_for(name)
    dest = plans_dir / "_archive" / quarter / name
    readme = plans_dir / "README.md"
    quarter_readme = dest.parent / "README.md"
    summary_src = path / "SUMMARY.md" if is_dir else None
    _refuse_unsafe_targets(
        root,
        plans_dir,
        plans_dir / "_archive",
        dest.parent,
        readme,
        quarter_readme,
        dest,
        *([summary_src] if summary_src is not None else []),
    )
    if dest.exists():
        raise FileExistsError(f"archive destination already exists: {dest}")
    date = _today(today)
    new_rel = f"_archive/{quarter}/{name}" + ("/plan.md" if is_dir else "")

    old_readme = _read(readme) if readme.is_file() else ""
    table = parse_ledger_table(old_readme)
    rows = {_canonical(k): v for k, v in table.active.items()}
    rows.update(
        {
            _canonical(k): v
            for k, v in table.archive.items()
            if _canonical(k) not in rows
        }
    )
    paths = discover_plan_files(path)
    row = _row_for(
        key,
        paths,
        rows.get(key),
        cell=plan_cell(new_rel),
        status="ARCHIVED",
        branch=None,
        today=date,
    )
    cells = _cells(row) or []
    branch_cell = cells[1] if len(cells) > 1 else NO_VALUE
    tasks_cell = cells[3] if len(cells) > 3 else NO_VALUE

    # build_summary() failure raises here — before any write or move.
    summary_written = False
    if summary_src is not None:
        summary_text = build_summary(path)
        _write_text(summary_src, summary_text)
        summary_written = True

    moved_with_git = _move(root, path, dest)

    new_readme = _upsert(old_readme, "archive", key, row)
    _write_text(readme, new_readme)

    old_quarter = _read(quarter_readme) if quarter_readme.is_file() else ""
    base = old_quarter or f"# Archived plans — {quarter}\n\n"
    if base and not base.endswith("\n"):
        base += "\n"
    new_quarter = (
        base + f"- {date} — `{name}` (ветка `{branch_cell}`, задачи {tasks_cell})\n"
    )
    _write_text(quarter_readme, new_quarter)

    verb = "git mv" if moved_with_git else "mv"
    summary_rel = (
        f"plans/_archive/{quarter}/{name}/SUMMARY.md" if summary_written else None
    )
    diff = (
        (f"wrote {summary_rel}\n" if summary_rel else "")
        + f"{verb} plans/{name} plans/_archive/{quarter}/{name}\n"
        + _diff(old_readme, new_readme, "plans/README.md")
        + _diff(old_quarter, new_quarter, f"plans/_archive/{quarter}/README.md")
    )
    return ArchiveResult(
        new_path=dest,
        quarter=quarter,
        old_rel=key,
        new_rel=new_rel,
        moved_with_git=moved_with_git,
        diff=diff,
        summary_path=(dest / "SUMMARY.md") if summary_written else None,
    )


def apply_ledger_fixes(root: Path, *, today: str | None = None) -> list[FixReport]:
    """The doctor's ``--fix``: archive done plans, add missing rows. Never
    touches a ``ROW_WITHOUT_FILE`` finding (that would mean deleting a row).

    Pre:
      - *root* is a directory.
    Post:
      - One report per fixable finding; an ``OSError`` / ``ValueError`` of a
        single fix becomes ``FixReport(changed=False, text="skipped: …")``
        and the remaining fixes still run.
      - Never deletes a plan and never deletes a ledger row: a
        ``ROW_WITHOUT_FILE`` row and its finding survive the fix
        (``TestFixKeepsRowWithoutFile``).
    """
    reports: list[FixReport] = []
    for finding in check_ledger(root):
        try:
            if finding.code == DONE_NOT_ARCHIVED:
                result = archive_plan(root, finding.plan, today=today)
                reports.append(FixReport(finding.plan, True, result.diff))
            elif finding.code == MISSING_ROW:
                diff = add_row(root, finding.plan, today=today)
                reports.append(FixReport(finding.plan, bool(diff), diff))
        except (OSError, ValueError) as exc:
            reports.append(FixReport(finding.plan, False, f"skipped: {exc}"))
    return reports


# ---------------------------------------------------------------------------
# Plan contract freeze (Task 5.1) — contract.lock, approve/amend
# ---------------------------------------------------------------------------


class ContractRefused(ValueError):
    """``approve``/``amend`` refused a plan on a policy ground (size
    findings, a missing or stale ``amendments.md``, an invalid amendment
    row) — the CLI maps this to ``rc=1``, distinct from the ``rc=2`` a bad
    or missing plan path raises via ``resolve_plan``."""


class BriefRefused(ValueError):
    """``brief`` refused: plan layout v2 is absent (a single-file plan, or
    no ``tasks/<id>.md``), the task file is missing a required brief field,
    or the executor brief form itself is missing a standing block — the
    CLI maps this to ``rc=1``, distinct from the ``rc=2`` an ambiguous or
    unresolved plan raises."""


def _blank_status_value(line: str) -> str:
    """Drop only the status VALUE from a ``- **Статус:**``/``- **Status:**``
    line — the text between the marker and the first `` · `` separator, or
    the rest of the line when there is none. Anything from the first `` · ``
    onward (``**Level:**``/``**Assignee:**``/… in this repo's plan format)
    stays in the hash (Task 5.1 fix, review F8)."""
    for marker in ("**Статус:**", "**Status:**"):
        idx = line.find(marker)
        if idx == -1:
            continue
        prefix_end = idx + len(marker)
        rest = line[prefix_end:]
        sep_idx = rest.find(" · ")
        if sep_idx == -1:
            return line[:prefix_end]
        return line[:prefix_end] + rest[sep_idx:]
    return line


def contract_fingerprint(plan_md_text: str) -> str:
    """sha256 hex of *plan_md_text*, normalised so only a real contract
    change moves it:

    - on the header line declaring the plan's own status (``- **Статус:**``
      / ``- **Status:**``), only the status VALUE is dropped
      (:func:`_blank_status_value`) — a trailing ``**Level:**``/
      ``**Assignee:**`` on the same line still moves the fingerprint;
    - inside a «Порядок выполнения» / "Execution order" section (the same
      section detection as :func:`task_order_marker`), only a task-index
      line (:data:`_ORDER_TASK_LINE_RE`, the same shape as
      :func:`task_order_marker`'s own line match) is cut before its
      ``[DONE]``/``[PENDING]``/… marker (:data:`_ORDER_MARKER_RE`) —
      flipping the marker, or appending ``(merge abc123 …)`` / ``->
      backlog (…)`` after it, never moves the fingerprint; a non-task-index
      line in the same section (a rule, a note) is hashed verbatim, marker
      token and all;
    - trailing whitespace per line and trailing blank lines are stripped.

    Everything else — goals, gates, budget, a task's title, an added or
    removed task line — changes the fingerprint; that is the point. Content
    inside a fenced code block (a plan quoting a template) is never touched,
    same as the rest of this module treats fences.
    """
    out_lines: list[str] = []
    section_level: int | None = None
    for line, fenced in _unfenced_lines(plan_md_text):
        if fenced:
            out_lines.append(line.rstrip())
            continue
        if line.lstrip().startswith(("- **Статус:**", "- **Status:**")):
            line = _blank_status_value(line)
        heading = _HEADING_RE.match(line)
        if heading:
            level = len(heading.group(1))
            if _ORDER_TITLE_RE.match(heading.group(2)):
                section_level = level
            elif section_level is not None and level <= section_level:
                section_level = None
        if section_level is not None and _ORDER_TASK_LINE_RE.match(line):
            marker = _ORDER_MARKER_RE.search(line)
            if marker:
                line = line[: marker.start()].rstrip()
        out_lines.append(line.rstrip())
    while out_lines and not out_lines[-1]:
        out_lines.pop()
    normalised = "\n".join(out_lines)
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


def contract_files_fingerprint(plan_dir: Path) -> tuple[str, dict[str, str]]:
    """The contract's fingerprint over its full extent — every file
    :func:`discover_plan_files` returns for *plan_dir* (``plan.md`` +
    ``phase-N.md`` + ``tasks/<id>.md``; ``amendments.md``/``decisions.md``/…
    are never contract files), not ``plan.md`` alone (Task 5.1 fix, F2: a v2
    plan's contract lives across all of these).

    Returns ``(overall_sha256, {rel_path: file_sha256})`` where *rel_path*
    is each file's POSIX path relative to *plan_dir* and *file_sha256* is
    :func:`contract_fingerprint` of its text; *overall_sha256* is the
    sha256 of ``"\\n".join(f"{rel}\\t{sha}" for rel in sorted(files))`` — a
    renamed, added or removed contract file moves it exactly like a content
    edit would.
    """
    plan_dir = Path(plan_dir)
    files = {
        path.relative_to(plan_dir).as_posix(): contract_fingerprint(_read(path))
        for path in discover_plan_files(plan_dir)
    }
    combined = "\n".join(f"{rel}\t{files[rel]}" for rel in sorted(files))
    overall = hashlib.sha256(combined.encode("utf-8")).hexdigest()
    return overall, files


def _contract_file_changes(
    old_files: dict[str, str], new_files: dict[str, str]
) -> list[str]:
    """``["changed foo.md", "added bar.md", "removed baz.md"]``, sorted by
    path — the raw material for a CONTRACT_DRIFT message; the caller
    truncates to 5 and adds a ``(+N more)`` tail."""
    changes: list[str] = []
    for rel in sorted(set(old_files) | set(new_files)):
        if rel not in old_files:
            changes.append(f"added {rel}")
        elif rel not in new_files:
            changes.append(f"removed {rel}")
        elif old_files[rel] != new_files[rel]:
            changes.append(f"changed {rel}")
    return changes


_AMENDMENT_HEADER_ALIASES = {
    "#": "number",
    "дата": "date",
    "date": "date",
    "почему": "why",
    "why": "why",
    "δ задач": "delta_tasks",
    "delta tasks": "delta_tasks",
    "δ бюджета": "delta_budget",
    "delta budget": "delta_budget",
}
_AMENDMENT_COLUMNS = ("number", "date", "why", "delta_tasks", "delta_budget")
_AMENDMENT_NUMBER_RE = re.compile(r"^\d+$")


@dataclass(frozen=True)
class AmendmentRow:
    number: int
    date: str
    why: str
    delta_tasks: str
    delta_budget: str


def parse_amendments(text: str) -> list[AmendmentRow]:
    """Numbered rows of an ``amendments.md`` table — header
    ``| # | дата | почему | Δ задач | Δ бюджета |`` (or the English
    ``| # | date | why | delta tasks | delta budget |``). The opening row
    (``#`` cell ``—``/``-``) is not an amendment and is not returned.

    Reuses :func:`_cells` for cell splitting (an escaped ``\\|`` stays
    inside its cell rather than splitting it) — no second splitter.
    """
    rows: list[AmendmentRow] = []
    columns: list[str] | None = None
    in_fence = False
    for line in text.splitlines():
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            columns = None
            continue
        if in_fence:
            continue
        cells = _cells(line)
        if cells is None:
            columns = None
            continue
        if columns is None:
            candidate = [_AMENDMENT_HEADER_ALIASES.get(c.lower(), "") for c in cells]
            if candidate[:1] == ["number"] and set(_AMENDMENT_COLUMNS) <= set(
                candidate
            ):
                columns = candidate
            continue
        if all(_SEPARATOR_CELL_RE.match(c) for c in cells if c):
            continue
        row = {
            col: (cells[j] if j < len(cells) else "")
            for j, col in enumerate(columns)
            if col
        }
        number_cell = row.get("number", "").strip()
        if not _AMENDMENT_NUMBER_RE.match(number_cell):
            continue  # the opening row (—/-) or a malformed cell
        rows.append(
            AmendmentRow(
                number=int(number_cell),
                date=row.get("date", "").strip(),
                why=row.get("why", "").strip(),
                delta_tasks=row.get("delta_tasks", "").strip(),
                delta_budget=row.get("delta_budget", "").strip(),
            )
        )
    return rows


def _last_amendment_number(rows: list[AmendmentRow]) -> int:
    """The highest ``#`` among *rows*, or 0 when there are none — the floor
    a new amendment's number must exceed at the next ``amend`` (Task 5.1
    fix, F5)."""
    return max((row.number for row in rows), default=0)


def _read_contract_lock(lock_path: Path) -> dict | None:
    """The parsed ``contract.lock``, or ``None`` when it is missing,
    unreadable (corrupt JSON, not an object), ``schema`` != 2, a required
    key is absent, or a key's value has the wrong type — never raises. A
    schema-1 lock (pre Task-5.1-fix) is therefore "corrupt" too: re-run
    ``approve`` to write a schema-2 lock — there is no migration."""
    try:
        data = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    required = {
        "schema",
        "approved",
        "approved_tasks",
        "budgeted_tasks",
        "sha256",
        "amended_tasks",
        "amendments",
        "files",
        "last_amendment_number",
    }
    if not isinstance(data, dict) or data.get("schema") != 2:
        return None
    if not required <= data.keys():
        return None
    for key in (
        "approved_tasks",
        "budgeted_tasks",
        "amended_tasks",
        "amendments",
        "last_amendment_number",
    ):
        value = data[key]
        if isinstance(value, bool) or not isinstance(value, int):
            return None
    for key in ("sha256", "approved"):
        if not isinstance(data[key], str):
            return None
    files = data["files"]
    if not isinstance(files, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in files.items()
    ):
        return None
    return data


def approve_plan(
    root: Path, plan: str, *, today: str | None = None, force: bool = False
) -> Path:
    """Freeze *plan*'s contract: write ``<plan_dir>/contract.lock``.

    Pre:
      - *plan* resolves (like ``add``'s argument, via :func:`resolve_plan`)
        to a plan **directory** (v2 layout) under ``plans/`` — a v1
        single-file plan raises :class:`ContractRefused` (the lock is
        opt-in and directory-only). A bad/missing reference raises the same
        ``FileNotFoundError``/``ValueError`` ``resolve_plan`` raises.
      - A readable ``contract.lock`` already exists and *force* is False ->
        :class:`ContractRefused` pointing to ``amend`` (or ``--force``);
        an unreadable/corrupt lock never refuses here — ``approve`` is how
        a corrupt lock gets repaired.
      - The plan carries no :func:`check_plan_sizes` finding and has an
        ``amendments.md``, else :class:`ContractRefused`.
    Post:
      - Read-only except for writing ``contract.lock`` (JSON, sorted keys,
        one trailing newline): ``schema=2``, ``approved`` = *today* (or
        today's real date), ``approved_tasks`` = ``amended_tasks`` = the
        plan's current task count (:func:`summarize_plan`), ``sha256`` +
        ``files`` = :func:`contract_files_fingerprint` over every contract
        file, ``amendments`` = the number of rows :func:`parse_amendments`
        finds, ``last_amendment_number`` = the highest row number among
        them (0 when there are none).
    """
    root = Path(root)
    key, path = resolve_plan(root, plan)
    if not path.is_dir():
        raise ContractRefused(
            f"plans/{key} is a single file — approve needs a v2 plan "
            "directory (plan.md + tasks/<id>.md)"
        )
    lock_path = path / "contract.lock"
    if not force and lock_path.is_file() and _read_contract_lock(lock_path) is not None:
        raise ContractRefused(
            f"plans/{key} already has a contract.lock — record a change "
            "via amend, or re-run approve --force to re-freeze"
        )
    size_findings = check_plan_sizes(path)
    if size_findings:
        detail = "; ".join(f"{f.code} {f.plan}" for f in size_findings)
        raise ContractRefused(
            f"plans/{key} has size findings — fix before approve: {detail}"
        )
    amendments_file = path / "amendments.md"
    if not amendments_file.is_file():
        raise ContractRefused(
            f"plans/{key} has no amendments.md — create it before approve"
        )
    _refuse_unsafe_targets(root, path, lock_path)
    fingerprint, files = contract_files_fingerprint(path)
    total = summarize_plan(discover_plan_files(path)).total
    rows = parse_amendments(_read(amendments_file))
    data = {
        "schema": 2,
        "approved": _today(today),
        "approved_tasks": total,
        "budgeted_tasks": total,
        "sha256": fingerprint,
        "files": files,
        "amended_tasks": total,
        "amendments": len(rows),
        "last_amendment_number": _last_amendment_number(rows),
    }
    _write_text(lock_path, json.dumps(data, sort_keys=True) + "\n")
    return lock_path


def amend_plan(root: Path, plan: str, *, today: str | None = None) -> Path:
    """Record a validated amendment: refresh ``contract.lock`` once
    ``amendments.md`` gains at least one new, well-formed row.

    Pre:
      - *plan* resolves (like ``approve``) to a plan directory that already
        carries a readable, schema-2 ``contract.lock``, else
        :class:`ContractRefused`.
      - The plan carries no :func:`check_plan_sizes` finding — the same
        gate ``approve`` runs — else :class:`ContractRefused`.
      - :func:`parse_amendments` on ``amendments.md`` returns more rows than
        the lock's recorded ``amendments`` count, and every row past that
        count has a ``why`` naming ``ADDED``/``MODIFIED``/``REMOVED``, a
        ``date`` carrying a ``YYYY-MM-DD`` pattern and not earlier than the
        lock's ``approved``, and a ``#`` greater than the lock's
        ``last_amendment_number``, else :class:`ContractRefused` naming the
        row number and the failing part.
    Post:
      - ``sha256``, ``files``, ``amended_tasks``, ``amendments`` and
        ``last_amendment_number`` are refreshed from the plan's current
        state; ``approved``/``approved_tasks`` are never touched.
        ``budgeted_tasks`` advances to the current task count when at
        least one of the newly recorded rows carries a non-empty,
        non-``—``/``-`` ``Δ бюджета`` cell (a literal ``0`` counts — a
        conscious "recomputed, no change"); otherwise it is left as-is.
    """
    root = Path(root)
    key, path = resolve_plan(root, plan)
    lock_path = path / "contract.lock"
    if not lock_path.is_file():
        raise ContractRefused(f"plans/{key} has no contract.lock — run approve first")
    lock = _read_contract_lock(lock_path)
    if lock is None:
        raise ContractRefused(
            f"plans/{key}: contract.lock is unreadable — run approve again"
        )
    size_findings = check_plan_sizes(path)
    if size_findings:
        detail = "; ".join(f"{f.code} {f.plan}" for f in size_findings)
        raise ContractRefused(
            f"plans/{key} has size findings — fix before amend: {detail}"
        )
    amendments_file = path / "amendments.md"
    rows = parse_amendments(_read(amendments_file)) if amendments_file.is_file() else []
    recorded = lock["amendments"]
    if len(rows) <= recorded:
        raise ContractRefused(
            f"plans/{key}: no new amendment row since the last approve/amend "
            f"({recorded} recorded, {len(rows)} present) — add a numbered "
            "row to amendments.md first"
        )
    approved = lock["approved"]
    last_number = lock["last_amendment_number"]
    for row in rows[recorded:]:
        if not any(kw in row.why for kw in ("ADDED", "MODIFIED", "REMOVED")):
            raise ContractRefused(
                f"amendments.md row {row.number}: почему must name ADDED, "
                "MODIFIED or REMOVED"
            )
        if not re.search(r"\d{4}-\d{2}-\d{2}", row.date):
            raise ContractRefused(
                f"amendments.md row {row.number}: дата must be YYYY-MM-DD"
            )
        if row.date < approved:
            raise ContractRefused(
                f"amendments.md row {row.number}: дата {row.date} is before "
                f"approval ({approved})"
            )
        if row.number <= last_number:
            raise ContractRefused(
                f"amendments.md row {row.number}: # must be greater than "
                f"the last recorded amendment ({last_number})"
            )
    _refuse_unsafe_targets(root, path, lock_path)
    fingerprint, files = contract_files_fingerprint(path)
    total = summarize_plan(discover_plan_files(path)).total
    has_budget_delta = any(
        row.delta_budget.strip() not in ("", "—", "-") for row in rows[recorded:]
    )
    data = dict(lock)
    data.update(
        sha256=fingerprint,
        files=files,
        amended_tasks=total,
        amendments=len(rows),
        last_amendment_number=_last_amendment_number(rows),
    )
    if has_budget_delta:
        data["budgeted_tasks"] = total
    _write_text(lock_path, json.dumps(data, sort_keys=True) + "\n")
    return lock_path


def check_plan_contract(plan_dir: Path) -> list[Finding]:
    """``CONTRACT_DRIFT``/``SCOPE_GREW`` for one plan directory that already
    carries a ``contract.lock``.

    Pre:
      - *plan_dir* exists (as passed from ``check_ledger``, an active
        plan's own directory).
    Post:
      - Read-only. ``[]`` when *plan_dir* is a single file (v1 plan — the
        v2 lock is opt-in) or carries no ``contract.lock`` at all.
      - A corrupt/unsupported lock (bad JSON, ``schema`` != 2, a missing or
        wrong-typed key) is exactly one ``CONTRACT_DRIFT`` finding — never
        an exception.
      - CONTRACT_DRIFT: the current :func:`contract_files_fingerprint` of
        *plan_dir* differs from the lock's ``sha256``; the message names up
        to 5 changed paths with a verb (``changed``/``added``/``removed``),
        then ``(+N more)``.
      - SCOPE_GREW: the current task count (:func:`summarize_plan`) exceeds
        125% of the lock's ``budgeted_tasks`` (a MOVING baseline — see
        :func:`amend_plan`) AND no row :func:`parse_amendments` finds in
        ``rows[lock["amendments"]:]`` (rows written but not yet amended)
        carries a non-empty, non-``—``/``-`` ``Δ бюджета`` cell — every
        growth past 125% needs its own budgeted amendment; one budgeted
        amend only excuses the growth it was recorded for.
      - Neither code is ``fixable``.
    """
    plan_dir = Path(plan_dir)
    if not plan_dir.is_dir():
        return []
    lock_path = plan_dir / "contract.lock"
    if not lock_path.is_file():
        return []
    label = f"{plan_dir.name}/plan.md"
    lock = _read_contract_lock(lock_path)
    if lock is None:
        return [
            Finding(
                CONTRACT_DRIFT,
                label,
                f"{plan_dir.name}/contract.lock is unreadable (corrupt JSON "
                "or unsupported schema) — re-run: plans_ledger.py approve "
                f"{plan_dir.name}",
            )
        ]
    plan_md = plan_dir / "plan.md"
    if not plan_md.is_file():
        return []
    findings: list[Finding] = []
    fingerprint, files = contract_files_fingerprint(plan_dir)
    if fingerprint != lock["sha256"]:
        changes = _contract_file_changes(lock["files"], files)
        shown = changes[:5]
        more = len(changes) - len(shown)
        detail_files = ", ".join(shown) + (f" (+{more} more)" if more else "")
        findings.append(
            Finding(
                CONTRACT_DRIFT,
                label,
                f"{detail_files} after approval ({lock['approved']}) "
                "without an amendment - record the change in amendments.md "
                "(ADDED/MODIFIED/REMOVED, why, delta tasks, delta budget) "
                f"and run: plans_ledger.py amend {plan_dir.name}",
            )
        )
    approved_tasks = lock["approved_tasks"]
    budgeted_tasks = lock["budgeted_tasks"]
    if budgeted_tasks:
        total = summarize_plan(discover_plan_files(plan_dir)).total
        if total > 1.25 * budgeted_tasks:
            amendments_file = plan_dir / "amendments.md"
            rows = (
                parse_amendments(_read(amendments_file))
                if amendments_file.is_file()
                else []
            )
            has_budget_delta = any(
                row.delta_budget.strip() not in ("", "—", "-")
                for row in rows[lock["amendments"] :]
            )
            if not has_budget_delta:
                findings.append(
                    Finding(
                        SCOPE_GREW,
                        label,
                        f"{total} tasks > 125% of the {budgeted_tasks} "
                        f"budgeted (approved: {approved_tasks}) - record a "
                        "Δ бюджета in amendments.md or split into a new plan",
                    )
                )
    return findings


# ---------------------------------------------------------------------------
# Executor brief assembly (Task 5.2)
# ---------------------------------------------------------------------------


def _brief_label_positions(text: str) -> list[tuple[int, str]]:
    """``(line index, label name)`` for every line of *text* that opens a
    brief label (``_BRIEF_LABEL_RE``), in file order, skipping any line
    inside a fenced code block (``_unfenced_lines`` — a task file quoting
    the form inside an example must not count as a real field)."""
    positions: list[tuple[int, str]] = []
    for idx, (line, fenced) in enumerate(_unfenced_lines(text)):
        if fenced:
            continue
        m = _BRIEF_LABEL_RE.match(line)
        if m:
            positions.append((idx, m.group(1).strip()))
    return positions


def _first_fenced_block_lines(text: str) -> list[str]:
    """Lines strictly between the first fence-open/fence-close pair in
    *text* — the executor brief's copy-pasted form, never the prose
    around it. ``[]`` when *text* has no fenced block."""
    lines = text.splitlines()
    start = next((i for i, ln in enumerate(lines) if _FENCE_RE.match(ln)), None)
    if start is None:
        return []
    end = next(
        (j for j in range(start + 1, len(lines)) if _FENCE_RE.match(lines[j])),
        len(lines),
    )
    return lines[start + 1 : end]


def _label_blocks(lines: list[str]) -> dict[str, list[str]]:
    """First-seen label name -> its own lines (the label line through the
    line before the next label, or the end of *lines*) — the same mapping
    dev/hooks/lint-brief.sh's ``label_blocks`` builds, over a plain line
    list rather than raw text."""
    positions = [
        (idx, m.group(1).strip())
        for idx, line in enumerate(lines)
        if (m := _BRIEF_LABEL_RE.match(line))
    ]
    blocks: dict[str, list[str]] = {}
    for i, (start, name) in enumerate(positions):
        if name in blocks:
            continue
        end = positions[i + 1][0] if i + 1 < len(positions) else len(lines)
        blocks[name] = lines[start:end]
    return blocks


def _rstrip_blank_lines(lines: list[str]) -> list[str]:
    out = list(lines)
    while out and not out[-1].strip():
        out.pop()
    return out


def _find_executor_brief(root: Path) -> tuple[Path | None, list[str]]:
    """First hit of the executor-brief.md lookup order: the project's own
    composed copy, this repo's seed source (it dogfoods its own seed), then
    the copy shipped next to this script. Returns ``(path_or_None, tried)``
    — *tried* names the three lookup locations, for the refusal message."""
    glob_pattern = "src/*/template/plugins/dev/templates/executor-brief.md"
    fallback = Path(__file__).resolve().parents[2] / "dev/templates/executor-brief.md"
    tried = [
        str(root / ".claude/plugins/dev/templates/executor-brief.md"),
        str(root / glob_pattern),
        str(fallback),
    ]
    candidates = [Path(tried[0])]
    candidates.extend(sorted(root.glob(glob_pattern)))
    candidates.append(fallback)
    found = next((c for c in candidates if c.is_file()), None)
    return found, tried


def _per_model_line(brief_text: str, role: str) -> str | None:
    """The text after the colon of the ``## Per-model line`` bullet whose
    backtick role list contains *role* (case-insensitive) — ``None`` when
    no bullet matches (skipped silently)."""
    lines = brief_text.splitlines()
    start = next(
        (
            i + 1
            for i, ln in enumerate(lines)
            if ln.strip().lower().startswith("## per-model line")
        ),
        None,
    )
    if start is None:
        return None
    bullets: list[str] = []
    current: list[str] = []
    for line in lines[start:]:
        if line.startswith("#"):
            break
        if line.startswith("- "):
            if current:
                bullets.append("\n".join(current))
            current = [line]
        elif current:
            current.append(line)
    if current:
        bullets.append("\n".join(current))
    role_l = role.strip().lower()
    for bullet in bullets:
        head, sep, tail = bullet.partition(":")
        if not sep:
            continue
        roles = {span.lower() for span in _BACKTICK_SPAN_RE.findall(head)}
        if role_l in roles:
            return tail.strip()
    return None


# Tried in order: a goal heading wins over a context heading even when the
# context section comes first in the document (lead probe, Task 5.3).
_SUMMARY_GOAL_HEADING_RES = (
    re.compile(r"^#{2,6}\s+(Цель|Цели|Goal|Goals)\b", re.IGNORECASE),
    re.compile(r"^#{2,6}\s+(Контекст|Context)\b", re.IGNORECASE),
)
_SUMMARY_TITLE_LIMIT_DEFAULT = 70
_SUMMARY_TITLE_LIMIT_SHRUNK = 32
_SHA_TOKEN_RE = re.compile(r"\b[0-9a-f]{7,40}\b")
_SUMMARY_WHY_LIMIT_DEFAULT = 140
_SUMMARY_WHY_LIMIT_SHRUNK = 60
_SUMMARY_SHA_LIMIT_DEFAULT = 6
_SUMMARY_SHA_LIMIT_SHRUNK = 2


def _first_paragraph_after(lines: list[tuple[str, bool]], start: int) -> str:
    """The first non-empty paragraph (contiguous non-blank, unfenced lines)
    starting at *start* — stops at a blank line, a heading, a fenced block,
    or the end of *lines*. Lines are joined with a single space."""
    collected: list[str] = []
    for line, fenced in lines[start:]:
        if fenced:
            break
        if _HEADING_RE.match(line):
            break
        if not line.strip():
            if collected:
                break
            continue
        collected.append(line.strip())
    return " ".join(collected)


def _plan_goal_paragraph(plan_md_text: str) -> str:
    """The Goal text for ``## Goal`` in :func:`build_summary`: the first
    non-empty paragraph under the first unfenced heading matching
    ``_SUMMARY_GOAL_HEADING_RES`` — a goal heading (Цель/Цели/Goal/Goals)
    first, a context heading (Контекст/Context) only when there is none —
    falling back to the first paragraph after the document's H1 when no such
    heading exists. ``""`` when neither is found."""
    lines = _unfenced_lines(plan_md_text)
    for heading_re in _SUMMARY_GOAL_HEADING_RES:
        for i, (line, fenced) in enumerate(lines):
            if fenced:
                continue
            if heading_re.match(line):
                para = _first_paragraph_after(lines, i + 1)
                if para:
                    return para[:600]
    for i, (line, fenced) in enumerate(lines):
        if fenced:
            continue
        heading = _HEADING_RE.match(line)
        if heading and len(heading.group(1)) == 1:
            return _first_paragraph_after(lines, i + 1)[:600]
    return ""


def _order_line_for_task(all_text: str, task_id: str) -> str | None:
    """The raw text of *task_id*'s own line in a «Порядок выполнения» /
    "Execution order" section — same line match and section detection as
    :func:`task_order_marker`, but returning the whole line (so a trailing
    ``(`sha`)`` annotation can be read) instead of just the marker."""
    line_re = re.compile(
        r"^\s*[-*+]\s+(?:\[[ xX]\]\s+)?(?:\*\*)?Task\s+"
        + re.escape(task_id)
        + r"(?!\d)"
    )
    section_level: int | None = None
    for line, fenced in _unfenced_lines(all_text):
        if fenced:
            continue
        heading = _HEADING_RE.match(line)
        if heading:
            level = len(heading.group(1))
            if _ORDER_TITLE_RE.match(heading.group(2)):
                section_level = level
                continue
            if section_level is not None and level <= section_level:
                section_level = None
            continue
        if section_level is None or not line_re.match(line):
            continue
        return line
    return None


_TASK_ANY_HEADING_RE = re.compile(r"^#{1,6}\s+Task\s+(\d+\.\d+)(?!\d)(.*)$")


def _task_title(text: str, task_id: str, limit: int) -> str:
    """The task's human title for a SUMMARY row: the rest of its
    ``# Task X.Y…`` / ``### Task X.Y…`` heading in *text* — leading ``:``/``—``
    and bold markers dropped, ``|`` escaped so it cannot split a table row,
    cut at *limit* characters with ``…``. ``""`` when there is no heading."""
    for line, fenced in _unfenced_lines(text):
        if fenced:
            continue
        m = _TASK_ANY_HEADING_RE.match(line)
        if m is None or m.group(1) != task_id:
            continue
        if limit <= 0:
            return ""
        title = m.group(2).replace("**", "").strip().lstrip(":—–- ").strip()
        if len(title) > limit:
            title = title[: limit - 1].rstrip() + "…"
        return title.replace("|", "\\|")
    return ""


def _sha_tokens(text: str, limit: int) -> list[str]:
    """Up to *limit* distinct ``_SHA_TOKEN_RE`` matches from *text*, in
    first-seen order."""
    seen: list[str] = []
    for tok in _SHA_TOKEN_RE.findall(text):
        if tok in seen:
            continue
        seen.append(tok)
        if len(seen) >= limit:
            break
    return seen


def build_summary(plan_dir: Path) -> str:
    """A one-page ``SUMMARY.md`` for *plan_dir* — what a new session should
    read instead of the full (now archived) plan: Goal, a per-task table
    (status/result/sha), Amendments, and the Open -> backlog list.

    Pre:
      - *plan_dir* is a plan directory (or a single-file plan path, for the
        ``summary`` CLI subcommand's preview use — ``discover_plan_files``
        already handles both).
    Post:
      - Never writes to disk; never calls git.
      - The Goal paragraph is :func:`_plan_goal_paragraph` of ``plan.md``
        (``""``/em-dash when there is no ``plan.md`` or no paragraph).
      - The Tasks table has one row per task id in discovery order
        (:func:`discover_plan_files` order, first-seen); ``status`` is the
        task's :func:`task_order_marker`, or ``DONE`` when
        :func:`is_task_closed` and there is no marker, else ``PENDING``;
        ``result`` links ``tasks/<id>.result.md`` when it exists, else
        ``—``; ``sha`` is up to 6 distinct SHA-shaped tokens (backticked,
        space-separated) from that result file, or — when there is none —
        from the task's own «Порядок выполнения» line; ``—`` when neither
        yields one.
      - Amendments: one bullet per :func:`parse_amendments` row of
        ``amendments.md`` (absent -> none); Open -> backlog: one bullet per
        task neither closed nor dropped, plus the dropped ones tagged with
        their marker; ``none`` when empty.
      - The result is re-rendered once (shorter why/sha limits) when over
        ``TASK_MAX_BYTES``; still over budget after that -> ``ValueError``
        naming the size — never a partial/oversized string.
    """
    plan_dir = Path(plan_dir)
    paths = discover_plan_files(plan_dir)
    texts = [(p, _read(p)) for p in paths]
    all_text = "\n".join(text for _, text in texts)

    task_file_text: dict[str, str] = {}
    for p, text in texts:
        if p.parent.name != "tasks":
            continue
        for task_id in extract_task_ids(text, in_task_file=True):
            task_file_text.setdefault(task_id, text)

    task_ids: list[str] = []
    for p, text in texts:
        in_task_file = p.parent.name == "tasks"
        for task_id in extract_task_ids(text, in_task_file=in_task_file):
            if task_id not in task_ids:
                task_ids.append(task_id)

    plan_md = plan_dir / "plan.md"
    goal = _plan_goal_paragraph(_read(plan_md)) if plan_md.is_file() else ""

    amendments_file = plan_dir / "amendments.md"
    amendment_rows = (
        parse_amendments(_read(amendments_file)) if amendments_file.is_file() else []
    )

    def render(why_limit: int, sha_limit: int, title_limit: int) -> str:
        lines: list[str] = [
            f"# SUMMARY — {plan_dir.name}",
            "",
            "## Goal",
            "",
            goal or NO_VALUE,
            "",
        ]

        lines += [
            "## Tasks",
            "",
            "| task | title | status | result | sha |",
            "|------|-------|--------|--------|-----|",
        ]
        backlog: list[str] = []
        for task_id in task_ids:
            closed = is_task_closed(all_text, task_id, task_file_text.get(task_id))
            marker = task_order_marker(all_text, task_id)
            if marker is not None:
                status = marker
            elif closed:
                status = "DONE"
            else:
                status = "PENDING"

            result_path = plan_dir / "tasks" / f"{task_id}.result.md"
            if result_path.is_file():
                result_cell = f"[{task_id}](tasks/{task_id}.result.md)"
                shas = _sha_tokens(_read(result_path), sha_limit)
            else:
                result_cell = NO_VALUE
                order_line = _order_line_for_task(all_text, task_id)
                shas = _sha_tokens(order_line, sha_limit) if order_line else []
            sha_cell = " ".join(f"`{s}`" for s in shas) if shas else NO_VALUE
            title = _task_title(
                task_file_text.get(task_id, all_text), task_id, title_limit
            )
            lines.append(
                f"| {task_id} | {title or NO_VALUE} | {status} | {result_cell} "
                f"| {sha_cell} |"
            )

            named = f"{task_id} — {title}" if title else task_id
            dropped = not closed and marker in _GATE_EXEMPT_MARKERS
            if dropped:
                backlog.append(f"- {named} [{marker}]")
            elif not closed:
                backlog.append(f"- {named}")
        lines.append("")

        lines += ["## Amendments", ""]
        if amendment_rows:
            for row in amendment_rows:
                why = row.why[:why_limit]
                lines.append(
                    f"- #{row.number} ({row.date}): {why} · "
                    f"Δ tasks {row.delta_tasks or NO_VALUE} · "
                    f"Δ budget {row.delta_budget or NO_VALUE}"
                )
        else:
            lines.append("none")
        lines.append("")

        lines += ["## Open -> backlog", ""]
        lines.extend(backlog if backlog else ["none"])
        lines.append("")
        return "\n".join(lines).rstrip("\n") + "\n"

    text = render(
        _SUMMARY_WHY_LIMIT_DEFAULT,
        _SUMMARY_SHA_LIMIT_DEFAULT,
        _SUMMARY_TITLE_LIMIT_DEFAULT,
    )
    if len(text.encode("utf-8")) > TASK_MAX_BYTES:
        text = render(
            _SUMMARY_WHY_LIMIT_SHRUNK,
            _SUMMARY_SHA_LIMIT_SHRUNK,
            _SUMMARY_TITLE_LIMIT_SHRUNK,
        )
    if len(text.encode("utf-8")) > TASK_MAX_BYTES:
        # Last resort before refusing: a table of bare ids still links every
        # result file — better than no page at all.
        text = render(_SUMMARY_WHY_LIMIT_SHRUNK, _SUMMARY_SHA_LIMIT_SHRUNK, 0)
    size = len(text.encode("utf-8"))
    if size > TASK_MAX_BYTES:
        raise ValueError(
            f"SUMMARY.md for {plan_dir.name} would be {size} bytes > "
            f"{TASK_MAX_BYTES} byte budget even after the shrunk re-render"
        )
    return text


def build_brief(root: Path, plan_path: Path, task_id: str) -> str:
    """A spawn-ready brief for *task_id*: ``tasks/<task_id>.md``'s own text
    (from its first brief label onward) plus the standing blocks of
    ``executor-brief.md`` it does not already carry, a ``PLAN:`` pointer,
    and the per-model line for its ``ROLE``.

    Pre:
      - *root* is the project root; *plan_path* is a plan directory or a
        single-file plan, as returned by ``list_active_plans``/
        ``resolve_plan_path``.
      - *task_id* is the bare ``<X.Y>`` id (matches ``tasks/<task_id>.md``
        and its ``# Task <task_id>`` H1 — no ``.md``/``Task`` affixes).
    Post:
      - Never writes to disk; never calls git.
      - Raises :class:`BriefRefused` when: *plan_path* is a file, or
        ``<plan_path>/tasks/<task_id>.md`` does not exist (plan layout v2
        is required); the task file is missing one or more of
        TASK/ROLE/DESIGN/FILES/REDS/TESTS/OUT OF SCOPE (message names
        every missing field, in that order); no ``executor-brief.md`` is
        found at any of the three lookup paths; a standing block name
        (FIRST EDIT, TEST RULES, BUDGET, COMMIT, REPORT) is missing from
        ``executor-brief.md``'s first fenced block.
      - On success, returns: the task file's text from its first brief
        label to the end (its ``# Task`` H1 and status line are dropped by
        virtue of coming before that point); a
        ``PLAN: plans/<dir>/tasks/<id>.md`` line; each STANDING block the
        task file itself does not define, in STANDING order — a
        task-level COMMIT/REPORT wins and is never duplicated; the COMMIT
        block (whichever source provided it) gains a trailing
        ``  Refs: plans/<dir>/plan.md`` line; a trailing
        ``MODEL LINE: <text>`` line when the task's ROLE value matches a
        bullet under executor-brief.md's "## Per-model line" section
        (skipped silently otherwise).
    """
    plan_path = Path(plan_path)
    try:
        plan_display = plan_path.relative_to(root).as_posix()
    except ValueError:
        plan_display = plan_path.as_posix()

    task_file = None if plan_path.is_file() else plan_path / "tasks" / f"{task_id}.md"
    if plan_path.is_file() or task_file is None or not task_file.is_file():
        raise BriefRefused(
            f"brief: no tasks/{task_id}.md under {plan_display} — "
            "brief needs plan layout v2"
        )

    task_text = _read(task_file)
    positions = _brief_label_positions(task_text)
    present = {name for _, name in positions}
    missing = [name for name in _BRIEF_REQUIRED_FIELDS if name not in present]
    if missing:
        raise BriefRefused(
            f"tasks/{task_id}.md: missing field(s): {', '.join(missing)}"
        )

    plan_dir_name = plan_path.name
    lines = task_text.splitlines()
    first_idx = positions[0][0]
    label_end: dict[str, int] = {
        name: (positions[i + 1][0] if i + 1 < len(positions) else len(lines))
        for i, (_, name) in enumerate(positions)
    }
    label_start: dict[str, int] = dict((name, idx) for idx, name in positions)
    task_lines = list(lines[first_idx:])

    refs_line = f"  Refs: plans/{plan_dir_name}/plan.md"
    if "COMMIT" in present:
        insert_at = label_end["COMMIT"] - first_idx
        task_lines[insert_at:insert_at] = [refs_line]
    task_lines = _rstrip_blank_lines(task_lines)

    brief_path, tried = _find_executor_brief(Path(root))
    if brief_path is None:
        raise BriefRefused(
            "executor-brief.md not found, tried:\n  " + "\n  ".join(tried)
        )
    brief_text = _read(brief_path)
    form_lines = _first_fenced_block_lines(brief_text)
    form_blocks = _label_blocks(form_lines)
    for name in _BRIEF_STANDING_BLOCKS:
        if name not in form_blocks:
            raise BriefRefused(f"executor-brief.md: standing block {name} not found")

    parts = ["\n".join(task_lines)]
    parts.append(f"PLAN: plans/{plan_dir_name}/tasks/{task_id}.md")
    for name in _BRIEF_STANDING_BLOCKS:
        if name in present:
            continue
        block_lines = _rstrip_blank_lines(form_blocks[name])
        if name == "COMMIT":
            block_lines = block_lines + [refs_line]
        parts.append("\n".join(block_lines))

    role_idx = label_start.get("ROLE")
    if role_idx is not None:
        role_line = lines[role_idx]
        m = _BRIEF_LABEL_RE.match(role_line)
        after = role_line[m.end() :].strip() if m else ""
        tokens = after.split()
        role_value = tokens[0].strip(",.;:") if tokens else ""
        model_line = _per_model_line(brief_text, role_value) if role_value else None
        if model_line:
            parts.append(f"MODEL LINE: {model_line}")

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _status_payload(root: Path) -> dict:
    plans_dir = _plans_dir(root)
    readme = plans_dir / "README.md"
    table = parse_ledger_table(_read(readme)) if readme.is_file() else LedgerTable()
    active_rows = {_canonical(k): v for k, v in table.active.items()}
    rows: list[dict] = []
    for key, path in list_active_plans(root).items():
        summary = summarize_plan(discover_plan_files(path))
        rows.append(
            {
                "plan": key,
                "section": "active",
                "ledger": active_rows.get(key),
                "computed": {
                    "done": summary.done,
                    "total": summary.total,
                    "phase": summary.phase,
                    "open_tasks": summary.open_tasks,
                },
            }
        )
    for key, row in table.archive.items():
        rows.append(
            {"plan": key, "section": "archive", "ledger": row, "computed": None}
        )
    return {
        "rows": rows,
        "findings": [
            asdict(f) | {"fixable": f.fixable, "gating": f.gating}
            for f in check_ledger(root)
        ],
    }


def _print_status(payload: dict) -> None:
    active = [r for r in payload["rows"] if r["section"] == "active"]
    if not active:
        print("plans ledger: no active plans")
    for row in active:
        comp = row["computed"]
        ledger = row["ledger"] or {}
        print(
            f"{row['plan']}: {comp['done']}/{comp['total']}, "
            f"{comp['phase'] or NO_VALUE}, ledger status "
            f"{ledger.get('status') or '(no row)'}"
        )
    archived = sum(1 for r in payload["rows"] if r["section"] == "archive")
    print(f"archived rows: {archived}")
    for finding in payload["findings"]:
        prefix = "WARN" if finding["gating"] else "INFO"
        print(f"{prefix} {finding['code']} {finding['plan']}: {finding['detail']}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="plans_ledger.py",
        description="plans/README.md ledger: status, add a row, close (archive).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    status = sub.add_parser("status", help="print the ledger and its findings")
    status.add_argument("--root", default=".", help="project root (default: .)")
    status.add_argument("--json", action="store_true", help="machine-readable output")
    status.add_argument("--check", action="store_true", help="exit 1 on any finding")
    status.add_argument(
        "--branch", help="limit to the active plan tracking this branch"
    )
    status.add_argument(
        "--plan",
        help="limit to this plan (path — absolute, cwd-relative, or plans/-relative)",
    )
    status.add_argument(
        "--oneline",
        action="store_true",
        help="with --branch/--plan: one summary line, live task counts",
    )

    add = sub.add_parser("add", help="register or refresh a plan's active row")
    add.add_argument("plan", help="plan path relative to plans/")
    add.add_argument("--root", default=".")
    add.add_argument("--status", choices=STATUSES, type=str.upper)
    add.add_argument("--branch")

    close = sub.add_parser("close", help="archive a done plan (git mv + rows)")
    close.add_argument("plan", help="plan path relative to plans/")
    close.add_argument("--root", default=".")
    close.add_argument("--force", action="store_true", help="archive an open plan")

    approve = sub.add_parser(
        "approve", help="freeze a v2 plan's contract (writes contract.lock)"
    )
    approve.add_argument("plan", help="plan path relative to plans/")
    approve.add_argument("--root", default=".")
    approve.add_argument(
        "--force", action="store_true", help="re-freeze an already-approved plan"
    )
    approve.add_argument(
        "--no-gate",
        action="store_true",
        help="skip the plan-gate check (check_plan_gate) before approve",
    )

    amend = sub.add_parser(
        "amend", help="record a validated amendment and refresh contract.lock"
    )
    amend.add_argument("plan", help="plan path relative to plans/")
    amend.add_argument("--root", default=".")

    brief = sub.add_parser(
        "brief", help="print a spawn-ready brief for tasks/<id>.md (plan layout v2)"
    )
    brief.add_argument("id", help="task id, e.g. 1.1")
    brief.add_argument(
        "--plan", help="plan path (default: the single active plan, if unambiguous)"
    )
    brief.add_argument("--root", default=".")

    summary = sub.add_parser(
        "summary", help="print the one-page SUMMARY.md a close would write"
    )
    summary.add_argument("plan", help="plan path relative to plans/")
    summary.add_argument("--root", default=".")
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, ValueError):
            stream.reconfigure(errors="replace")  # type: ignore[union-attr]
    args = _parser().parse_args(argv)
    root = Path(args.root)
    if not root.is_dir():
        print(f"error: root not found: {root}", file=sys.stderr)
        return 2

    if args.command == "brief":
        if args.plan:
            found = resolve_plan_path(root, args.plan)
            if found is None:
                print(f"error: plan not found: {args.plan}", file=sys.stderr)
                return 2
            _, plan_path = found
        else:
            active = list_active_plans(root)
            if len(active) != 1:
                print(
                    f"brief: pass --plan <path> ({len(active)} active plans)",
                    file=sys.stderr,
                )
                return 2
            plan_path = next(iter(active.values()))
        try:
            print(build_brief(root, plan_path, args.id))
        except BriefRefused as exc:
            print(str(exc), file=sys.stderr)
            return 1
        return 0

    if args.command == "status":
        if args.plan or args.branch:
            # --plan wins when both are given: the caller (the SessionStart
            # banner) has already resolved a branch to a plan file via
            # validate_commit.py --resolve-plan, so a path is more specific
            # than re-deriving the same answer from the branch name.
            found = (
                resolve_plan_path(root, args.plan)
                if args.plan
                else plan_for_branch(root, args.branch)
            )
            if found is None:
                return 0  # no matching active plan — caller falls back silently
            key, path = found
            summary = summarize_plan(discover_plan_files(path))
            readme = _plans_dir(root) / "README.md"
            table = (
                parse_ledger_table(_read(readme)) if readme.is_file() else LedgerTable()
            )
            row = {_canonical(k): v for k, v in table.active.items()}.get(
                _canonical(key)
            )
            computed = {
                "done": summary.done,
                "total": summary.total,
                "phase": summary.phase,
                "open_tasks": summary.open_tasks,
            }
            # Targeted gate (amendment 6): scoped to this one resolved plan,
            # never check_ledger()'s whole-plans/ aggregation.
            findings = check_plan_gate(path) + check_plan_contract(path)
            if args.oneline:
                slug = _slug_for_key(key)
                status_val = (row or {}).get("status") or "(no row)"
                print(
                    f"{slug} · {summary.phase or NO_VALUE} · "
                    f"{summary.done}/{summary.total} · {status_val}"
                )
            elif args.json:
                obj = {"plan": key, "ledger": row, "computed": computed}
                if args.check:
                    obj["findings"] = [
                        asdict(f) | {"fixable": f.fixable, "gating": f.gating}
                        for f in findings
                    ]
                print(json.dumps(obj, ensure_ascii=False, indent=2))
            else:
                print(
                    f"{key}: {summary.done}/{summary.total}, "
                    f"{summary.phase or NO_VALUE}, ledger status "
                    f"{(row or {}).get('status') or '(no row)'}"
                )
            if args.check and not args.json:
                for finding in findings:
                    prefix = "WARN" if finding.gating else "INFO"
                    print(f"{prefix} {finding.code} {finding.plan}: {finding.detail}")
            return 1 if args.check and any(f.gating for f in findings) else 0
        payload = _status_payload(root)
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            _print_status(payload)
        return 1 if args.check and any(f["gating"] for f in payload["findings"]) else 0

    try:
        if args.command == "add":
            diff = add_row(root, args.plan, status=args.status, branch=args.branch)
            print(diff or "plans/README.md: row already up to date")
            return 0

        if args.command == "approve":
            if args.no_gate:
                print("gate skipped (--no-gate)")
            else:
                _, gate_path = resolve_plan(root, args.plan)
                gate_findings = check_plan_gate(gate_path)
                if gate_findings:
                    for finding in gate_findings:
                        prefix = "WARN" if finding.gating else "INFO"
                        print(
                            f"{prefix} {finding.code} {finding.plan}: {finding.detail}"
                        )
                    print(
                        f"approve refused: {len(gate_findings)} gate finding(s) "
                        "— fix and re-run, or pass --no-gate",
                        file=sys.stderr,
                    )
                    return 1
            try:
                lock_path = approve_plan(root, args.plan, force=args.force)
            except ContractRefused as exc:
                print(f"refused: {exc}", file=sys.stderr)
                return 1
            print(f"{lock_path.relative_to(root).as_posix()}: contract written")
            return 0

        if args.command == "amend":
            try:
                lock_path = amend_plan(root, args.plan)
            except ContractRefused as exc:
                print(f"refused: {exc}", file=sys.stderr)
                return 1
            print(f"{lock_path.relative_to(root).as_posix()}: contract updated")
            return 0

        if args.command == "summary":
            _, summary_plan_path = resolve_plan(root, args.plan)
            print(build_summary(summary_plan_path), end="")
            return 0

        key, path = resolve_plan(root, args.plan)
        readme = _plans_dir(root) / "README.md"
        table = parse_ledger_table(_read(readme)) if readme.is_file() else LedgerTable()
        row = {_canonical(k): v for k, v in table.active.items()}.get(key)
        summary = summarize_plan(discover_plan_files(path))
        if not args.force and not _is_done(summary, row):
            print(
                f"refused: plans/{key} is not done ({summary.done}/{summary.total} "
                f"tasks closed, open: {', '.join(summary.open_tasks) or NO_VALUE}; "
                "ledger status "
                f"{(row or {}).get('status') or '(no row)'}). Use --force to archive.",
                file=sys.stderr,
            )
            return 1
        print(archive_plan(root, args.plan).diff)
        return 0
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
