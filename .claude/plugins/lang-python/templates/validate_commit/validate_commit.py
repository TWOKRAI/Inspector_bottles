#!/usr/bin/env python3
"""Commit message validator (portable, seed-shipped).

Checks:
1. Subject in Conventional Commits format: `<type>(<scope>): <subject>`
2. Blank line between subject and body.
3. Required trailers: `Why:` and `Layer:` (with allowed values).
4. Optional trailers (if present) — valid format: `Risk:`, `Reversible:`, `Tested:`, `Refs:`, `Rejected:`.
5. Tests-discipline gate (default ON): staged code without staged tests must
   carry a `Tested:` trailer in the grammar `tests/<path>` | `skip (<reason>)`.
   `tests/<path>` additionally requires the path to exist — staged in this
   commit, or already committed to HEAD; see `_path_exists_in_head()`.
   See `load_tests_gate_config()` for the toggle/globs and where they live.

Layer values are loaded from .claude/commit-layers.txt (one layer per line,
'#' for comments). Fallback to a generic default if the file is absent —
this keeps the validator usable in a brand-new project before customization.

Also the home of the branch → plan resolver (`resolve_plan()` /
`plan_for_branch()`) that decides which plan a branch is working on. It is a
public contract of this file: the `Refs:` check below, `check_injections.py`
and the `session-plan-status.sh` banner all read it, the last through
`--resolve-plan`. Three routes, in order — the plan's `Ветка:`/`Branch:`
header field, the `plans/YYYY-MM-DD_<slug>` glob, a `Refs:` trailer already in
`<base>..HEAD`.

Usage:
    python scripts/validate_commit/validate_commit.py <path-to-commit-msg-file>
    git log -1 --format=%B | python scripts/validate_commit/validate_commit.py -
    python scripts/validate_commit/validate_commit.py --resolve-plan [branch]

Used as git commit-msg hook (see scripts/validate_commit/install_hook.sh).
Exit 0 — OK, exit 1 — validation failed.

Skipped: merge commits (Merge ..., merge: ...), reverts, fixup!/squash!/amend!.
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

# ────────────────────────── Config ──────────────────────────

ALLOWED_TYPES = {
    "feat",
    "fix",
    "refactor",
    "docs",
    "test",
    "chore",
    "perf",
    "build",
    "ci",
    "style",
    "revert",
}

# Generic defaults. Override by writing layers (one per line) to
# .claude/commit-layers.txt at the project root.
DEFAULT_LAYERS = {
    "app",
    "lib",
    "tests",
    "docs",
    "scripts",
    "infra",
    "build",
    "ci",
    "mixed",
}

LAYERS_CONFIG_REL = ".claude/commit-layers.txt"

# Tests-discipline gate (plan `2026-09-03_harvest-inspector-bottles.md`, Task
# 6.2): toggle + globs are read from the fenced ```ini block of
# .claude/modes/_stack.md (see `gate_config_block`). Defaults below apply
# whenever the repo, the file, the block, or a given key is missing — the gate
# is ON by default in the seed, even with no _stack.md at all.
STACK_CONFIG_REL = ".claude/modes/_stack.md"
TESTS_GATE_CODE_DEFAULT = "src/**/*.py"
TESTS_GATE_EXCLUDE_DEFAULT = "**/template/**"
TESTS_DIR_GLOB = "tests/**"

# Branches matching `<conv-type>/<slug>` are treated as plan-driven; if a plan
# exists at plans/<slug>.md (or plans/<slug>/plan.md), the commit MUST include
# `Refs: plans/<slug>...`. See .claude/commands/dev/plan.md for the workflow.
CONV_TYPES_ALT = "feat|fix|refactor|docs|test|chore|perf|build|ci|style|revert"
BRANCH_SLUG_RE = re.compile(rf"^(?:{CONV_TYPES_ALT})/(?P<slug>.+)$")

# ── Branch → plan resolution (Task 1.5) ──────────────────────────────────────
#
# Three routes, tried in this order; see `resolve_plan()` for the contract.
#
#   1. the plan's own `- **Ветка:** <branch>` / `- **Branch:** <branch>` header
#      field,
#   2. the slug glob `plans/YYYY-MM-DD_<slug>...`,
#   3. a `Refs: plans/…` trailer already written by this branch's own commits.
#
# Only route 2 existed before, which made the resolution `branch slug == plan
# slug` and nothing else. Every branch that legitimately diverged from that —
# `feat/harvest-gaps` working the `harvest-inspector-bottles` plan, an agent
# worktree named `worktree-agent-<id>` — resolved to `None`, and BOTH gates
# that ask this question then disarmed themselves: the `Refs:` requirement in
# `validate()` never fired, and `check_injections.py` printed SKIP and exited
# 0. 93 of 94 commits on that branch carried `Refs:` because agents were told
# to, not because anything checked.
#
# Route 1 is the fix a human can apply on purpose (declare the branch in the
# plan); route 3 is the one that needs no bookkeeping at all — a branch that
# ever referenced a plan keeps being held to it.
PLAN_HEADER_LINES = 20

# `- **Ветка:** x` / `- **Ветка**: x` / `Branch: x` — the три spellings real
# plan headers use. The colon sits inside the bold markers in the first form,
# which is why this is an alternation rather than one optional-`**` pattern.
PLAN_BRANCH_FIELD_RE = re.compile(
    r"^\s*(?:[-*+]\s+)?"
    r"(?:"
    r"\*\*(?:Ветка|Branch)\s*:\*\*"
    r"|\*\*(?:Ветка|Branch)\*\*\s*:"
    r"|(?:Ветка|Branch)\s*:"
    r")\s*(?P<value>.*)$",
    re.IGNORECASE,
)

# A header field is prose as often as not ("Phase 0–5 — `feat/a`, слита в
# `main` (`0af39e5`); Phase 6 — `feat/b`"), so only `<conv-type>/<name>` tokens
# are read out of it. That deliberately refuses to read `main`, a SHA or a tag
# as a branch claim: a plan narrating its own merge into `main` must not make
# every commit on `main` plan-bound.
PLAN_BRANCH_TOKEN_RE = re.compile(rf"(?:{CONV_TYPES_ALT})/[A-Za-z0-9._\-/]+")
# …unless the whole value IS one bare token, which is how a branch outside the
# convention (`worktree-agent-<id>`, `release-1.2`) can still be declared.
BARE_BRANCH_RE = re.compile(r"^[A-Za-z0-9._\-/]+$")

REFS_TRAILER_RE = re.compile(r"^\s*Refs:\s*(?P<value>.+)$")
PLAN_PATH_RE = re.compile(r"plans/[A-Za-z0-9._\-/]+\.md")
PLAN_DATE_PREFIX_RE = re.compile(r"^(?P<date>\d{4}-\d{2}-\d{2})_")

# Base branches probed for route 3 when the caller names none. `<base>..HEAD`
# is empty while HEAD *is* the base, which is what keeps a merged plan from
# demanding `Refs:` on every subsequent commit to the base branch.
PLAN_BASE_REF_CANDIDATES = ("main", "master")
PLAN_REFS_LOG_LIMIT = 200

ALLOWED_RISK = {"low", "medium", "high"}
ALLOWED_REVERSIBLE = {"yes", "no", "migration-needed"}

SUBJECT_RE = re.compile(
    r"^(?P<type>[a-z]+)(?:\((?P<scope>[a-z0-9_\-/,\s]+)\))?(?P<breaking>!)?: (?P<subject>.+)$"
)
TRAILER_RE = re.compile(r"^([A-Z][A-Za-z\-]*): (.+)$")

# `Tested:` grammar enforced ONLY while the tests-discipline gate fires (see
# load_tests_gate_config()/apply below). Outside the gate `Tested:` stays
# free-form, unchanged from prior behaviour.
#
# TESTED_PATH_VALUE_RE checks GRAMMAR only (`tests/<anything>`) — it does NOT
# prove the path exists. That used to be the whole check, which accepted any
# string shaped like a test path, existing or not (`Tested: tests/test_nope.py`
# on a project with zero tests still passed). The gate below additionally
# requires the path to exist — staged in THIS commit, or already in HEAD (a
# human referencing a test committed earlier, unmodified here) — via
# `_tested_path_exists()`.
TESTED_PATH_VALUE_RE = re.compile(r"^tests/.+$")
TESTED_SKIP_VALUE_RE = re.compile(r"^skip \([^)]+\)$")

# tests_gate / tests_gate_code / tests_gate_exclude are read ONLY from a
# machine-readable fenced ```ini block in `.claude/modes/_stack.md` — never
# from the prose around it.
#
# Why a dedicated block and not a regex over the document: `_stack.md` is the
# one file every project is told to hand-edit and document itself in, so any
# parser that shares a namespace with prose eventually reads a sentence as
# configuration. It did, twice, in opposite directions:
#
#   * the seed's own line "**Disable:** set `tests_gate: off` — restores …"
#     — a sentence explaining how to switch the gate off — parsed as the
#     switch, so every generated project got the gate OFF while the same
#     document said "on by default";
#   * "**`tests_gate_exclude:`** `src/*/template/**` — bundled seed under …"
#     swallowed the explanation into the glob, producing a pattern matching
#     nothing; writing the intent down made the gate STRICTER than omitting
#     the key, because the junk value replaced a working default.
#
# Anchoring the regex to a bare list item would narrow that, not close it: a
# doc example written as "- `tests_gate: off`" is still valid prose and still
# parses. A fenced block cannot be written by accident, and prose can then say
# anything it likes about the keys.
#
# Inside the block, glob keys take the REST OF THE LINE and split on commas so
# a project can list several globs per key. Capturing a single non-space token
# would be quietly dangerous: `tests_gate_code = src/**/*.py, lib/**/*.py`
# would grab `src/**/*.py,` — trailing comma included — matching no path at
# all and silently disabling the gate instead of narrowing it.
_GATE_KEY_RE = re.compile(
    r"^\s*(tests_gate|tests_gate_code|tests_gate_exclude)\s*[:=]\s*(.*)$",
    re.IGNORECASE,
)
_FENCE_RE = re.compile(r"^\s*(?P<fence>`{3,}|~{3,})\s*(?P<info>\S*)\s*$")
_GATE_BLOCK_INFO = "ini"


def _split_globs(raw: str) -> list[str]:
    """Comma-separated glob list from a config line; backticks/space stripped.

    Empty items are dropped. Returns [] when nothing usable is left, which
    callers treat as "key absent" and fall back to the default.
    """
    return [
        g for g in (part.strip().strip("`").strip() for part in raw.split(",")) if g
    ]


REQUIRED_BASE_TRAILERS = {"Why"}
KNOWN_TRAILERS = REQUIRED_BASE_TRAILERS | {
    "Layer",
    "Refs",
    "Risk",
    "Reversible",
    "Tested",
    "Rejected",
    "Co-Authored-By",
    "Signed-off-by",
    "Reviewed-by",
}

SKIP_PREFIXES = ("Merge ", "merge: ", "Revert ", "fixup!", "squash!", "amend!")


# ────────────────────────── Structures ──────────────────────────


@dataclass
class ValidationResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


@dataclass
class TestsGateConfig:
    """Tests-discipline commit gate config (Task 6.2).

    See `load_tests_gate_config()` for where these are read from and what
    the defaults mean.
    """

    enabled: bool = True
    code_globs: list[str] = field(default_factory=lambda: [TESTS_GATE_CODE_DEFAULT])
    exclude_globs: list[str] = field(
        default_factory=lambda: [TESTS_GATE_EXCLUDE_DEFAULT]
    )


def find_repo_root() -> Path | None:
    """First ancestor of CWD that contains .git."""
    cwd = Path.cwd().resolve()
    for parent in [cwd, *cwd.parents]:
        if (parent / ".git").exists():
            return parent
    return None


def current_branch(repo_root: Path) -> str | None:
    """Current branch name via symbolic-ref. None for detached HEAD or errors."""
    try:
        out = subprocess.run(
            ["git", "-C", str(repo_root), "symbolic-ref", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        return out.stdout.strip() or None
    except Exception:
        return None


@dataclass(frozen=True)
class PlanResolution:
    """Which plan a branch is working on, and how that was decided.

    `source` is one of `branch-field` | `slug` | `refs-log` (a plan was found)
    or `detached-head` | `none` (it was not). Callers that must *act* on the
    absence — the injections gate fails closed — need to tell "this branch has
    no plan" apart from "there is no branch to ask about", which is what the
    two negative sources are for.
    """

    plan: str | None
    source: str
    warnings: tuple[str, ...] = ()


def branch_key(name: str) -> str:
    """Identity of a branch for plan matching: its slug, prefix stripped.

    `feat/auth`, `fix/auth` and a bare `auth` are the same work as far as a
    plan is concerned, so the conventional-commits prefix is decoration on
    both sides of the comparison — a plan may declare `- **Ветка:** feat/auth`
    while a caller holds only `auth`.
    """
    m = BRANCH_SLUG_RE.match(name)
    return m.group("slug") if m else name


def branches_declared_in(value: str) -> set[str]:
    """Branch names declared by one `Ветка:`/`Branch:` header value.

    Pre:
      - *value* is the text right of the field's colon (may be prose).
    Post:
      - every returned name is either `<conv-type>/<something>` or the whole
        value when that is a single bare token; nothing else is inferred.
    """
    found = {t.rstrip(".,;:)»") for t in PLAN_BRANCH_TOKEN_RE.findall(value)}
    bare = value.strip().strip("`").strip()
    if bare and BARE_BRANCH_RE.match(bare):
        found.add(bare)
    return found


def plan_header_branches(plan_path: Path) -> set[str]:
    """Branches declared in the header of *plan_path* (first PLAN_HEADER_LINES).

    Bounded on purpose: plans quote branch names all through their Progress
    log, and a Progress-log line is a narration, not a declaration.
    """
    try:
        with plan_path.open(encoding="utf-8", errors="replace") as fh:
            head = [next(fh, "") for _ in range(PLAN_HEADER_LINES)]
    except OSError:
        return set()
    declared: set[str] = set()
    for line in head:
        m = PLAN_BRANCH_FIELD_RE.match(line.rstrip("\n"))
        if m:
            declared |= branches_declared_in(m.group("value"))
    return declared


def _plan_sort_key(rel: str) -> tuple[str, str]:
    """Sort plans oldest-first by their ISO date prefix, then by path."""
    name = Path(rel).parent.name if rel.endswith("/plan.md") else Path(rel).stem
    m = PLAN_DATE_PREFIX_RE.match(name)
    return (m.group("date") if m else "0000-00-00", rel)


def active_plan_files(repo_root: Path) -> list[str]:
    """Top-level plan files: `plans/*.md` and `plans/*/plan.md`.

    `plans/_archive/**` is excluded — a closed plan must not keep claiming the
    branch it once ran on and re-arm a gate months later.
    """
    plans_dir = repo_root / "plans"
    if not plans_dir.is_dir():
        return []
    out = [p for p in plans_dir.glob("*.md") if p.is_file()]
    out += [p for p in plans_dir.glob("*/plan.md") if p.is_file()]
    return sorted(
        p.relative_to(repo_root).as_posix()
        for p in out
        if "_archive" not in p.relative_to(repo_root).parts
    )


def plans_declaring_branch(repo_root: Path, branch: str) -> list[str]:
    """Plans whose header declares *branch*, oldest first."""
    key = branch_key(branch)
    hits = [
        rel
        for rel in active_plan_files(repo_root)
        if any(branch_key(d) == key for d in plan_header_branches(repo_root / rel))
    ]
    return sorted(hits, key=_plan_sort_key)


def plan_by_slug(repo_root: Path, branch: str) -> str | None:
    """The plan named after this branch's slug, or None.

    Matched at one of:
      plans/<slug>.md                    (legacy, undated)
      plans/<slug>/plan.md               (legacy, undated multi-phase)
      plans/<YYYY-MM-DD>_<slug>.md       (dated single — current convention)
      plans/<YYYY-MM-DD>_<slug>/plan.md  (dated multi-phase — current convention)

    The dated convention (`plans/YYYY-MM-DD_<slug>...`) is what `/dev:plan`
    actually writes; the original code only matched the undated forms, so the
    Refs requirement silently never fired for real plans. The dated glob
    anchors the tail on `_<slug>` (no trailing wildcard) so a longer slug
    cannot false-match a shorter plan (branch `feat/auth` must NOT match
    `plans/2026-01-01_auth-rbac.md`). On multiple same-slug dated plans, the
    most recent (lexicographically last ISO date) wins — that's the active
    plan a fresh branch references.
    """
    slug = branch_key(branch)
    # Undated (legacy) forms first — exact, cheapest.
    for rel in (f"plans/{slug}.md", f"plans/{slug}/plan.md"):
        if (repo_root / rel).exists():
            return rel
    # Dated convention: plans/YYYY-MM-DD_<slug>.md or plans/YYYY-MM-DD_<slug>/plan.md.
    # Restrict matches to the literal ISO-date prefix: the glob `*_<slug>.md` also
    # matches NON-dated strays ending in `_<slug>.md` (e.g. a scratch `wip_<slug>.md`),
    # and since letters sort after digits such a file would win latest-wins and
    # shadow the active dated plan — falsely rejecting a correct commit. The date
    # regex filter keeps only real dated plans, so latest-wins (lexical == ISO order)
    # holds.
    plans_dir = repo_root / "plans"
    if plans_dir.is_dir():
        dated = re.compile(r"^\d{4}-\d{2}-\d{2}_" + re.escape(slug) + r"$")
        single = sorted(
            p for p in plans_dir.glob(f"*_{slug}.md") if dated.match(p.stem)
        )
        if single:
            return single[-1].relative_to(repo_root).as_posix()
        multi = sorted(
            p for p in plans_dir.glob(f"*_{slug}/plan.md") if dated.match(p.parent.name)
        )
        if multi:
            return multi[-1].relative_to(repo_root).as_posix()
    return None


def _ref_exists(repo_root: Path, ref: str) -> bool:
    try:
        out = subprocess.run(
            [
                "git",
                "-C",
                str(repo_root),
                "rev-parse",
                "--verify",
                "-q",
                f"{ref}^{{commit}}",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
        )
    except Exception:
        return False
    return out.returncode == 0


def _normalise_plan_ref(repo_root: Path, rel: str) -> str | None:
    """An existing plan path for *rel*, phase files folded to their plan root.

    `Refs: plans/<dated>/phase-2.md` identifies the same plan as
    `plans/<dated>/plan.md`; returning the root keeps the `Refs:` prefix check
    in `validate()` satisfied by a reference to *any* phase of it.
    """
    if ".." in Path(rel).parts:
        return None
    path = repo_root / rel
    if not path.is_file():
        return None
    if path.name != "plan.md" and path.parent.name != "plans":
        root = path.parent / "plan.md"
        if root.is_file():
            return root.relative_to(repo_root).as_posix()
    return path.relative_to(repo_root).as_posix()


def plan_from_refs_log(repo_root: Path, base: str | None = None) -> str | None:
    """The newest plan referenced by a `Refs:` trailer in `<base>..HEAD`.

    Pre:
      - *repo_root* is a git work tree; *base* names a ref or is None (then
        `main`/`master` are probed in that order).
    Post:
      - the returned path exists on disk, or None. Never raises: git missing,
        no such base, no commits — all mean "this route has no answer".
    """
    candidates = [base] if base else list(PLAN_BASE_REF_CANDIDATES)
    ref = next((c for c in candidates if c and _ref_exists(repo_root, c)), None)
    if ref is None:
        return None
    try:
        out = subprocess.run(
            [
                "git",
                "-C",
                str(repo_root),
                "log",
                f"-n{PLAN_REFS_LOG_LIMIT}",
                "--format=%B",
                f"{ref}..HEAD",
            ],
            capture_output=True,
            text=True,
            # Commit messages are UTF-8 (git's default `i18n.commitEncoding`),
            # but `text=True` alone decodes with the LOCALE codec — cp1251 on a
            # Russian Windows box. That raises UnicodeDecodeError inside
            # subprocess' reader thread, which does NOT propagate: `run()`
            # returns with `stdout=None` and the next `.splitlines()` dies with
            # a bare AttributeError. Observed on this repo's own log, where the
            # whole route silently produced nothing. Decode explicitly.
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
    except Exception:
        return None
    if out.returncode != 0 or not out.stdout:
        return None
    for line in out.stdout.splitlines():
        m = REFS_TRAILER_RE.match(line)
        if not m:
            continue
        for candidate in PLAN_PATH_RE.findall(m.group("value")):
            resolved = _normalise_plan_ref(repo_root, candidate)
            if resolved:
                return resolved
    return None


def resolve_plan(
    repo_root: Path, branch: str | None, base: str | None = None
) -> PlanResolution:
    """The one answer to "which plan is this branch working on".

    Pre:
      - *repo_root* is the repository root (`find_repo_root()`).
      - *branch* is a branch name, its bare slug, or None for detached HEAD.
      - *base* names the branch the work is measured against, or None to probe
        `main`/`master`.
    Post:
      - `plan` is a repo-relative POSIX path to an existing file, or None.
      - `source` names the route that answered (see `PlanResolution`).
      - `warnings` is non-empty only when the answer was ambiguous; the caller
        decides whether to print them.

    Detached HEAD returns `detached-head` and resolves nothing: rebase, bisect
    and CI checkouts all run detached, "this branch's plan" has no meaning
    there, and a gate that guessed from history would block a rebase.
    """
    if not branch:
        return PlanResolution(None, "detached-head")

    declaring = plans_declaring_branch(repo_root, branch)
    if declaring:
        warnings: tuple[str, ...] = ()
        if len(declaring) > 1:
            # ASCII only — this text reaches a shipped hook's stderr, which on
            # Windows may be a code page that cannot encode Cyrillic.
            warnings = (
                f"branch '{branch}' is declared by {len(declaring)} plans "
                f"({', '.join(declaring)}); using the newest, {declaring[-1]}. "
                "Keep one `- **Branch:**` claim per branch.",
            )
        return PlanResolution(declaring[-1], "branch-field", warnings)

    by_slug = plan_by_slug(repo_root, branch)
    if by_slug:
        return PlanResolution(by_slug, "slug")

    from_log = plan_from_refs_log(repo_root, base)
    if from_log:
        return PlanResolution(from_log, "refs-log")

    return PlanResolution(None, "none")


def plan_for_branch(
    repo_root: Path, branch: str | None, base: str | None = None
) -> str | None:
    """`resolve_plan().plan`, with any ambiguity warned about on stderr.

    Pre / Post — as `resolve_plan()`. This is the form both shipped gates and
    `--resolve-plan` call; keep it the only entry point they use, so the
    `Refs:` gate, the injections gate and the SessionStart banner cannot
    develop three opinions about the same branch.
    """
    resolution = resolve_plan(repo_root, branch, base)
    for warning in resolution.warnings:
        sys.stderr.write(f"WARNING: {warning}\n")
    return resolution.plan


def load_allowed_layers() -> set[str] | None:
    """Read layer whitelist from .claude/commit-layers.txt.

    Returns:
        - set of layer names if config exists with at least one non-comment line
        - empty set if config exists but is empty / comments-only → `Layer:` is OPTIONAL
        - set of DEFAULT_LAYERS if config is absent → `Layer:` is required, generic values

    Searches upwards from CWD for the project root (first ancestor containing .git).
    """
    cwd = Path.cwd().resolve()
    for parent in [cwd, *cwd.parents]:
        if (parent / ".git").exists():
            config = parent / LAYERS_CONFIG_REL
            if config.exists():
                lines = config.read_text(encoding="utf-8").splitlines()
                layers = {
                    line.strip()
                    for line in lines
                    if line.strip() and not line.strip().startswith("#")
                }
                return layers  # may be empty → Layer trailer optional
            break
    return set(DEFAULT_LAYERS)


def staged_files(repo_root: Path) -> list[str] | None:
    """Staged file paths (relative, POSIX-style) via `git diff --cached --name-only`.

    Returns None whenever staged paths cannot be determined — git missing,
    `repo_root` not a git repository, the command failing for any reason.
    Callers MUST treat None as "gate cannot fire": the commit-msg hook has no
    right to crash just because the environment lacks git.
    """
    try:
        out = subprocess.run(
            # `-z`: NUL-separated and never quoted. Without it git quotes every
            # non-ASCII path (`"tests/\321..."`, `core.quotepath` default), which
            # no longer starts with `tests/` — the gate went silent on it.
            ["git", "-C", str(repo_root), "diff", "--cached", "--name-only", "-z"],
            capture_output=True,
            text=True,
            # Paths are UTF-8; the locale codec (cp1251 on a Russian Windows
            # box) cannot decode them — see `plan_from_refs_log`.
            encoding="utf-8",
            errors="replace",
            timeout=5,
        )
        if out.returncode != 0 or out.stdout is None:
            return None
        return [p.strip() for p in out.stdout.split("\0") if p.strip()]
    except Exception:
        return None


def _path_exists_in_head(repo_root: Path, rel_path: str) -> bool:
    """True when *rel_path* exists as a blob at HEAD (`git cat-file -e`).

    Backs the `Tested: tests/<path>` existence check: a human may reference a
    test committed in an earlier commit without touching it in this one, so
    "exists" must mean "staged OR already in HEAD", not "staged only".

    False on any git failure — no commits yet (fresh repo, no HEAD), a
    non-git `repo_root`, git not on PATH, or the path genuinely absent at
    HEAD. Callers must not distinguish "false because absent" from "false
    because unknown": both mean the trailer cannot be trusted from history.
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(repo_root), "cat-file", "-e", f"HEAD:{rel_path}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return out.returncode == 0
    except Exception:
        return False


def _scan_ini_block(lines: list[str]) -> tuple[int, int, list[str]] | None:
    """First fenced ```ini block carrying a `tests_gate*` key, as
    ``(open_idx, close_idx, body)`` — 0-based indices into *lines* of the
    opening and closing fence lines (both inclusive of the block). Returns
    None when no such block exists.

    The shared scan behind `gate_config_block()` (body only, the original
    API) and `gate_config_block_span()` (the line range — added for
    `doctor`'s decorative-mention WARN, which needs to tell "inside the
    block" from "prose around it" without re-walking the fence logic; see
    that function's docstring). One scan, two views — not a second parser.
    """
    i = 0
    while i < len(lines):
        m = _FENCE_RE.match(lines[i])
        if not m or m.group("info").lower() != _GATE_BLOCK_INFO:
            i += 1
            continue
        closing = m.group("fence")[0] * 3
        body: list[str] = []
        j = i + 1
        while j < len(lines) and not lines[j].strip().startswith(closing):
            body.append(lines[j])
            j += 1
        if any(
            _GATE_KEY_RE.match(b) for b in body if not b.strip().startswith("#")
        ):
            close_idx = j if j < len(lines) else len(lines) - 1
            return i, close_idx, body
        i = j + 1
    return None


def gate_config_block(text: str) -> list[str] | None:
    """Lines of the first fenced ```ini block that carries a `tests_gate*` key.

    Returns None when the document has no such block — callers then keep the
    defaults. Requiring BOTH the `ini` info string and a recognised key means
    an unrelated ini snippet elsewhere in `_stack.md` is skipped rather than
    read as gate configuration.
    """
    found = _scan_ini_block(text.splitlines())
    return found[2] if found is not None else None


def gate_config_block_span(text: str) -> tuple[int, int] | None:
    """``(open_line_idx, close_line_idx)`` of the qualifying ```ini block —
    0-based indices into ``text.splitlines()``, BOTH inclusive (the opening
    fence line and the closing fence line both count as "inside the block").
    None when `gate_config_block()` would also return None.

    Exists for `doctor`'s tests_gate-prose WARN check (a mention of
    `tests_gate*` outside the block, with the key absent from it, is
    decorative — see doctor.py's `check_tests_gate_config`): it needs to
    exclude the machine-readable block itself while scanning `_stack.md` for
    decorative key mentions, without re-implementing the fence scan.
    """
    found = _scan_ini_block(text.splitlines())
    return (found[0], found[1]) if found is not None else None


def load_tests_gate_config() -> TestsGateConfig:
    """Read `tests_gate` / `tests_gate_code` / `tests_gate_exclude` from the
    fenced ```ini block of `.claude/modes/_stack.md` (see `gate_config_block`).

    Defaults (`TestsGateConfig()` — enabled, `src/**/*.py` minus
    `**/template/**`) apply whenever the repo root, the file, the block, or a
    given key is missing, and on any read error. The gate defaults to ON even
    with no `_stack.md` at all — that is the seed's documented default, not an
    omission. An unparseable `tests_gate` value (a typo, say) likewise leaves
    the default in place: a misspelling must not be able to disable the gate.

    Searches from `Path.cwd()` upward for the repo root (via
    `find_repo_root()`), same convention as `load_allowed_layers()`.
    """
    cfg = TestsGateConfig()
    try:
        repo_root = find_repo_root()
        if repo_root is None:
            return cfg
        stack_md = repo_root / STACK_CONFIG_REL
        if not stack_md.exists():
            return cfg
        body = gate_config_block(stack_md.read_text(encoding="utf-8"))
        if body is None:
            return cfg
        for line in body:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            m = _GATE_KEY_RE.match(line)
            if not m:
                continue
            key = m.group(1).lower()
            # Trailing `# comment` is documentation, not part of the value.
            raw = m.group(2).split("#", 1)[0].strip()
            if key == "tests_gate":
                value = raw.strip("`").strip("'\"").strip().lower()
                if value in ("on", "off"):
                    cfg.enabled = value == "on"
            else:
                globs = _split_globs(raw)
                if globs:
                    if key == "tests_gate_code":
                        cfg.code_globs = globs
                    else:
                        cfg.exclude_globs = globs
    except Exception:
        return TestsGateConfig()
    return cfg


def _glob_to_regex(pattern: str) -> re.Pattern[str]:
    """Compile a gitignore-style glob (with `**` = zero or more path segments)
    to a fullmatch regex over POSIX-style relative paths.

    `pathlib.PurePath.match()` doesn't give `**` this recursive meaning on
    Python < 3.13 (this project targets 3.11+), and `fnmatch` treats `*` as
    matching across `/` with no `**` concept at all — neither would make
    `src/**/*.py` match a direct child like `src/x.py`. Hence this small
    hand-rolled translator instead of a stdlib one.
    """
    i, n = 0, len(pattern)
    out: list[str] = []
    while i < n:
        c = pattern[i]
        i += 1
        if c == "*":
            if i < n and pattern[i] == "*":
                i += 1  # consume second '*'
                if i < n and pattern[i] == "/":
                    i += 1  # consume trailing '/' — '**/' matches zero-or-more dirs
                    out.append("(?:.*/)?")
                else:
                    out.append(".*")
            else:
                out.append("[^/]*")
        elif c == "?":
            out.append("[^/]")
        else:
            out.append(re.escape(c))
    return re.compile("^" + "".join(out) + "$")


# ────────────────────────── Parsing ──────────────────────────


def parse_message(text: str) -> tuple[str, list[str], dict[str, list[str]]]:
    """Return (subject, body_lines, trailers).

    Split into paragraphs by blank lines. Walk from the end — while the last
    paragraph consists entirely of trailer lines, treat it as a trailer block.
    This allows multiple trailer paragraphs (e.g., business trailers +
    separate Co-Authored-By at the bottom).

    trailers — dict[key -> list[values]] (one key can appear multiple times).
    """
    lines = [ln for ln in text.splitlines() if not ln.startswith("#")]
    while lines and not lines[-1].strip():
        lines.pop()

    if not lines:
        return "", [], {}

    subject = lines[0]
    rest = lines[1:]
    if rest and not rest[0].strip():
        rest = rest[1:]

    paragraphs: list[list[str]] = []
    current: list[str] = []
    for ln in rest:
        if not ln.strip():
            if current:
                paragraphs.append(current)
                current = []
        else:
            current.append(ln)
    if current:
        paragraphs.append(current)

    trailers: dict[str, list[str]] = {}
    while paragraphs:
        last = paragraphs[-1]
        if all(TRAILER_RE.match(line) for line in last):
            for line in last:
                m = TRAILER_RE.match(line)
                if m:
                    key, val = m.group(1), m.group(2).strip()
                    trailers.setdefault(key, []).append(val)
            paragraphs.pop()
        else:
            break

    body: list[str] = []
    for i, p in enumerate(paragraphs):
        if i > 0:
            body.append("")
        body.extend(p)

    return subject, body, trailers


# ────────────────────────── Validation ──────────────────────────


def validate(
    text: str,
    allowed_layers: set[str] | None = None,
    plan_path: str | object | None = ...,  # sentinel to allow None as "no plan"
) -> ValidationResult:
    result = ValidationResult()
    text = text.strip()

    if not text:
        result.errors.append("Empty commit message")
        return result

    first_line = text.splitlines()[0]
    if any(first_line.startswith(p) for p in SKIP_PREFIXES):
        return result  # merge/revert/fixup — skip validation

    layers = allowed_layers if allowed_layers is not None else load_allowed_layers()
    layer_required = bool(layers)
    required = REQUIRED_BASE_TRAILERS | ({"Layer"} if layer_required else set())

    # Resolve plan for current branch (if not explicitly provided).
    if plan_path is ...:
        repo = find_repo_root()
        branch = current_branch(repo) if repo else None
        # `branch` may be None (detached HEAD) — resolve_plan() answers that
        # case itself rather than being short-circuited here, so the three
        # routes stay in one place.
        plan_path = plan_for_branch(repo, branch) if repo else None

    subject, _body, trailers = parse_message(text)

    # Position-independent trailers: parse_message only captures the bottom
    # trailer block (the git-trailer convention the guide recommends). But a
    # human-friendly `Why:`/`Refs:` placed right under the subject — or a `Why:`
    # whose value wraps onto a second line — is common and must NOT be rejected.
    # Merge any KNOWN trailer found anywhere in the message so the presence and
    # value checks below see it regardless of placement. Only known keys are
    # collected, so prose like "Note: ..." in the body is not mistaken for one.
    for raw_line in text.splitlines():
        if raw_line.startswith("#"):
            continue
        anywhere = TRAILER_RE.match(raw_line)
        if anywhere and anywhere.group(1) in KNOWN_TRAILERS:
            a_key, a_val = anywhere.group(1), anywhere.group(2).strip()
            if a_val not in trailers.get(a_key, []):
                trailers.setdefault(a_key, []).append(a_val)

    # 1. Subject format
    if not subject:
        result.errors.append("Empty subject (first line)")
        return result

    m = SUBJECT_RE.match(subject)
    if not m:
        result.errors.append(
            f"Subject not in Conventional Commits format.\n"
            f"  Got: '{subject}'\n"
            f"  Expected: <type>(<scope>): <description>\n"
            f"  Example: feat(auth): add wildcard to has_permission"
        )
        return result

    t = m.group("type")
    if t not in ALLOWED_TYPES:
        result.errors.append(f"Unknown type '{t}'. Allowed: {sorted(ALLOWED_TYPES)}")

    # 2. Blank line between subject and body
    full_lines = [ln for ln in text.splitlines() if not ln.startswith("#")]
    if len(full_lines) >= 2 and full_lines[1].strip():
        result.errors.append("Missing blank line between subject and body")

    # 3. Required trailers
    missing = required - set(trailers.keys())
    if missing:
        hint = "    Why: one line about motivation"
        if "Layer" in missing:
            hint += f"\n    Layer: {' | '.join(sorted(layers))}"
        result.errors.append(
            f"Missing required trailers: {sorted(missing)}.\n"
            f"  Add at end of message (after blank line):\n{hint}"
        )

    # 4. Trailer value validation
    if "Layer" in trailers and layer_required:
        for val in trailers["Layer"]:
            given = {x.strip() for x in val.split(",") if x.strip()}
            unknown = given - layers
            if unknown:
                result.errors.append(
                    f"Layer: unknown values {sorted(unknown)}. Allowed: {sorted(layers)}\n"
                    f"  (configure via {LAYERS_CONFIG_REL})"
                )

    if "Risk" in trailers:
        for val in trailers["Risk"]:
            level = val.split("—")[0].split("-")[0].strip().lower()
            if level not in ALLOWED_RISK:
                result.warnings.append(
                    f"Risk: '{val}'. Expected to start with low/medium/high"
                )

    if "Reversible" in trailers:
        for val in trailers["Reversible"]:
            level = val.split("—")[0].strip().lower()
            if level not in ALLOWED_REVERSIBLE:
                result.warnings.append(
                    f"Reversible: '{val}'. Expected: yes | no | migration-needed"
                )

    # 5. Unknown trailers — warning (don't block, extensible)
    for key in trailers:
        if key not in KNOWN_TRAILERS:
            result.warnings.append(
                f"Unknown trailer '{key}:'. Known: {sorted(KNOWN_TRAILERS)}"
            )

    if "Why" in trailers:
        for val in trailers["Why"]:
            if len(val) < 5:
                result.warnings.append(
                    f"Why: too brief ('{val}'). Describe motivation in at least one phrase"
                )

    # 6. Plan-driven workflow: if branch has a plan, require matching Refs trailer.
    if plan_path:
        refs = trailers.get("Refs", [])
        # Plan path without extension: `plans/<slug>` (works for both
        # `plans/<slug>.md` and `plans/<slug>/plan.md` / `phase-N.md`).
        plan_prefix = plan_path.rsplit("/plan.md", 1)[0].rsplit(".md", 1)[0]
        if not any(plan_prefix in val for val in refs):
            result.errors.append(
                f"Branch has a plan ({plan_path}) but commit is missing matching "
                f"`Refs:` trailer.\n"
                f"  Add: Refs: {plan_path}\n"
                f"  (or for multi-phase plans, ref the specific phase file)"
            )

    # 7. Tests-discipline gate (Task 6.2): fires only when a staged path
    # matches tests_gate_code minus tests_gate_exclude. When it fires, the
    # commit is accepted only with a staged tests/** path OR a `Tested:`
    # trailer matching `tests/<path>` | `skip (<reason>)`. Degrades silently
    # (never fires) if staged paths can't be determined — see staged_files().
    gate_cfg = load_tests_gate_config()
    if gate_cfg.enabled:
        gate_repo_root = find_repo_root()
        staged = staged_files(gate_repo_root) if gate_repo_root else None
        if staged:
            code_res = [_glob_to_regex(g) for g in gate_cfg.code_globs]
            exclude_res = [_glob_to_regex(g) for g in gate_cfg.exclude_globs]
            tests_re = _glob_to_regex(TESTS_DIR_GLOB)
            gated_paths = [
                p
                for p in staged
                if any(r.match(p) for r in code_res)
                and not any(r.match(p) for r in exclude_res)
            ]
            tests_staged = any(tests_re.match(p) for p in staged)
            if gated_paths and not tests_staged:
                tested_values = trailers.get("Tested", [])
                satisfied = False
                # Grammar matched (`tests/<path>`) but the path itself was
                # not found staged or in HEAD — tracked separately so the
                # rejection can name the observed fact instead of falling
                # back to the generic "no Tested: trailer at all" message.
                missing_path: str | None = None
                for val in tested_values:
                    if TESTED_SKIP_VALUE_RE.match(val):
                        satisfied = True
                        break
                    if not TESTED_PATH_VALUE_RE.match(val):
                        continue
                    in_staged = val in staged
                    in_head = bool(gate_repo_root) and _path_exists_in_head(
                        gate_repo_root, val
                    )
                    if in_staged or in_head:
                        satisfied = True
                        break
                    missing_path = val
                if not satisfied:
                    if missing_path is not None:
                        result.errors.append(
                            f"Tested: {missing_path} — no such path in the staged "
                            f"index or in HEAD.\n"
                            f"  Reference a test that actually exists (staged, or "
                            f"already committed to HEAD), stage the test itself, "
                            f"or use:\n"
                            f"    Tested: skip (<reason>)"
                        )
                    else:
                        result.errors.append(
                            f"Gated code staged without tests: {sorted(gated_paths)}.\n"
                            f"  Either stage a test under tests/**, or add a trailer:\n"
                            f"    Tested: tests/<path-to-test>\n"
                            f"    Tested: skip (<reason>)"
                        )

    return result


# ────────────────────────── CLI ──────────────────────────


def _cli_resolve_plan(args: list[str]) -> int:
    """`--resolve-plan [branch]` — print this branch's plan path, or nothing.

    The shell-facing form of `plan_for_branch()`, so `session-plan-status.sh`
    (and anything else in the seed that needs the active plan) can ask the
    same function the gates ask instead of re-globbing `plans/` in bash.

    Exit 0 + one line on stdout when a plan resolves; exit 1 and silence when
    it does not — an empty `$(...)` is what a shell caller can test.
    """
    repo = find_repo_root()
    if repo is None:
        return 1
    branch = args[0] if args else current_branch(repo)
    resolution = resolve_plan(repo, branch)
    for warning in resolution.warnings:
        sys.stderr.write(f"WARNING: {warning}\n")
    if resolution.plan is None:
        return 1
    sys.stdout.write(resolution.plan + "\n")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[1] == "--resolve-plan":
        return _cli_resolve_plan(argv[2:])

    if len(argv) != 2:
        sys.stderr.write(
            "Usage: validate_commit.py <file>\n"
            "       echo '...' | validate_commit.py -\n"
            "       validate_commit.py --resolve-plan [branch]\n"
        )
        return 2

    src = argv[1]
    text = sys.stdin.read() if src == "-" else Path(src).read_text(encoding="utf-8")

    result = validate(text)

    if result.warnings:
        sys.stderr.write("WARNING:\n")
        for w in result.warnings:
            sys.stderr.write(f"  - {w}\n")

    if result.errors:
        sys.stderr.write("\nERROR: Commit message is invalid:\n")
        for e in result.errors:
            sys.stderr.write(f"  - {e}\n")
        sys.stderr.write(
            "\nGuide: .claude/COMMIT_GUIDE.md\nBypass (merge/rebase only): git commit --no-verify\n"
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
