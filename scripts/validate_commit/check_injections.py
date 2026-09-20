#!/usr/bin/env python3
"""Injections-record gate (plan Task 6.2), shared by `/dev:ship` and pre-push.

A branch that changed `tests/**` relative to its base may only be pushed /
shipped once the break-injection it performed is written down: one row
``property | predicted red | observed red`` in the branch's own plan — either
``plans/<slug>/injections.md`` (anywhere in the file) or under an
``## Injections`` heading of the plan itself.

Exit codes:
    0 — the gate passes, or cannot apply (see the SKIP messages below)
    1 — tests changed and no record row was found → block
    1 — tests changed and no plan could be resolved for the branch → block

The second `1` is Task 1.5 and a behaviour change for existing projects: this
used to SKIP with rc=0 whenever the branch had no plan, i.e. it disarmed
itself on exactly the branches where nobody had written the plan down. The
owner's call is fail-closed — a branch that changes `tests/**` must name the
plan its injection record lives in. Ways out, cheapest first: add
``- **Branch:** <branch>`` to the plan's header, name the branch after the
plan's slug, or reference the plan with a ``Refs:`` trailer.

Usage:
    python scripts/validate_commit/check_injections.py [--base main]

Both call sites run this one file so their notions of "a record" cannot drift:
the shell snippet in `install_pre_push_hook.sh` and the one documented in
`/dev:ship` are plumbing (find a Python, find this script) and nothing else.

Three deliberate strictnesses, each from a hole the review reproduced:

  * A markdown table HEADER and its ``|---|---|`` separator are not records.
    A `grep`-shaped check counted them, so an empty table satisfied a gate
    whose STOP text claimed a data row had been looked for.
  * The template's placeholder row (``| <что проверяет тест> | … |``) is not a
    record either — a plan pasted from `PLAN.template.md` and never filled in
    must not pass.
  * Only the CURRENT branch's plan is scanned. The previous check scanned
    every `plans/*.md`, so the first record ever written anywhere made the
    gate permanently green for every branch afterwards. The branch → plan
    resolution is `validate_commit.plan_for_branch()`, imported rather than
    re-implemented, so both gates agree on what "this branch's plan" means.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path

_HEADER_CELLS = {"property", "predicted red", "observed red"}
_SEPARATOR_CELL_RE = re.compile(r"^:?-{2,}:?$")
_PLACEHOLDER_CELL_RE = re.compile(r"^<.*>$")
_INJECTIONS_HEADING_RE = re.compile(r"^#{2,6}\s*[«\"'`]*\s*injections", re.IGNORECASE)
_HEADING_RE = re.compile(r"^#{2,6}\s")


def _load_validate_commit():
    """Import the sibling `validate_commit.py` (same directory, by path).

    Loading by path rather than by name keeps this script runnable straight
    from a git hook, where the CWD is the repo root and nothing is on
    `sys.path`.

    The module MUST be registered in `sys.modules` before `exec_module`: on
    Python 3.14 `@dataclass` resolves its own module through
    `sys.modules[cls.__module__]`, so an unregistered module makes the import
    die with `AttributeError: 'NoneType' object has no attribute '__dict__'`.
    """
    path = Path(__file__).resolve().with_name("validate_commit.py")
    spec = importlib.util.spec_from_file_location("_validate_commit_for_gate", path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise ImportError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def is_record_row(line: str) -> bool:
    """True when *line* is a filled-in table row, not a header/separator/stub."""
    if line.count("|") < 2:
        return False
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    cells = [c for c in cells if c]
    if len(cells) < 3:
        return False
    if all(_SEPARATOR_CELL_RE.match(c) for c in cells):
        return False
    if all(c.lower() in _HEADER_CELLS for c in cells):
        return False
    return not all(_PLACEHOLDER_CELL_RE.match(c) for c in cells)


def file_has_record(path: Path) -> bool:
    """Scan *path* for a record row.

    A file named `injections.md` is scanned whole; any other file only inside
    its `## Injections` section (plans are full of unrelated tables).
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    whole_file = path.name.lower() == "injections.md"
    in_section = whole_file
    for line in text.splitlines():
        if _HEADING_RE.match(line):
            in_section = whole_file or bool(_INJECTIONS_HEADING_RE.match(line))
            continue
        if in_section and is_record_row(line):
            return True
    return False


def candidate_files(repo_root: Path, plan_rel: str) -> list[Path]:
    """Files that may hold this branch's injection record.

    The plan itself, a sibling/child `injections.md`, and the phase files of a
    multi-phase plan — nothing outside the plan's own directory.
    """
    plan = repo_root / plan_rel
    plan_dir = plan.parent if plan.name == "plan.md" else plan.with_suffix("")
    out: list[Path] = []
    if plan.is_file():
        out.append(plan)
    if plan_dir.is_dir():
        injections = plan_dir / "injections.md"
        if injections.is_file():
            out.append(injections)
        out.extend(sorted(p for p in plan_dir.glob("phase-*.md") if p.is_file()))
    return out


def tests_changed(repo_root: Path, base: str) -> bool | None:
    """Whether `tests/**` differs from *base*. None when it can't be decided."""
    try:
        out = subprocess.run(
            [
                "git",
                "-C",
                str(repo_root),
                "diff",
                "--name-only",
                f"{base}..HEAD",
                "--",
                "tests/",
            ],
            capture_output=True,
            text=True,
            # Paths are UTF-8; decoded with the locale codec (cp1251 on a
            # Russian Windows box) they left `stdout=None` and `.strip()` below
            # crashed the gate.
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
    except Exception:
        return None
    if out.returncode != 0 or out.stdout is None:
        return None
    return bool(out.stdout.strip())


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base",
        default=os.environ.get("INJECTIONS_GATE_BASE", "main"),
        help="branch the change is measured against (default: main)",
    )
    args = parser.parse_args(argv[1:])

    validate_commit = _load_validate_commit()

    repo_root = validate_commit.find_repo_root()
    if repo_root is None:
        print("SKIP injections gate: not inside a git repository", file=sys.stderr)
        return 0

    changed = tests_changed(repo_root, args.base)
    if changed is None:
        print(
            f"SKIP injections gate: cannot diff against '{args.base}' "
            "(missing base branch?)",
            file=sys.stderr,
        )
        return 0
    if not changed:
        # Said out loud on purpose: a gate that prints nothing when it does not
        # apply is indistinguishable from a gate that never ran, which is how
        # the fail-open below survived a whole phase unnoticed.
        print(
            f"injections gate: tests/** unchanged vs '{args.base}' — not applicable",
            file=sys.stderr,
        )
        return 0

    branch = validate_commit.current_branch(repo_root)
    resolution = validate_commit.resolve_plan(repo_root, branch, args.base)
    for warning in resolution.warnings:
        print(f"WARN injections gate: {warning}", file=sys.stderr)
    plan_rel = resolution.plan
    if not plan_rel:
        if resolution.source == "detached-head":
            # Not a fail-open: there is no branch to have a plan. Rebase and
            # bisect run here, and blocking them would buy nothing.
            print(
                "SKIP injections gate: detached HEAD — no branch to resolve a plan for",
                file=sys.stderr,
            )
            return 0
        # ASCII only, deliberately: this is a shipped gate and its stderr may
        # be a legacy Windows code page that cannot encode Cyrillic. A
        # UnicodeEncodeError here would turn a clean block into a crash.
        print(
            "STOP: tests/** changed on this branch but no plan could be resolved "
            "for it.\n"
            f"  Branch:    {branch}\n"
            f"  Tried:     `- **Branch:** {branch}` in a plans/*.md header; "
            "plans/YYYY-MM-DD_<slug> by slug;\n"
            f"             `Refs: plans/...` in git log {args.base}..HEAD\n"
            "  Fix:       add `- **Branch:** <branch>` to the plan's header, name the\n"
            "             branch after the plan's slug, or reference the plan from a\n"
            "             commit with a `Refs:` trailer.\n"
            "  (This SKIPped with rc=0 before Task 1.5 - the gate switched itself off\n"
            "   on exactly the branches whose plan nobody had written down.)",
            file=sys.stderr,
        )
        return 1

    files = candidate_files(repo_root, plan_rel)
    if any(file_has_record(f) for f in files):
        return 0

    looked_in = (
        ", ".join(str(f.relative_to(repo_root).as_posix()) for f in files) or "—"
    )
    print(
        "STOP: tests/** changed on this branch but its plan carries no injections "
        "record.\n"
        f"  Plan:       {plan_rel}\n"
        f"  Looked in:  {looked_in}\n"
        "  Add a filled-in row `property | predicted red | observed red` under an\n"
        "  '## Injections' heading in the plan, or in plans/<slug>/injections.md.\n"
        "  A header row, a `|---|` separator or the template's <placeholder> row\n"
        "  does not count — the record is the observed result of the injection.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
