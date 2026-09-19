#!/usr/bin/env python3
"""memory_lint.py — mechanical WARN-only linter over the project memory store.

Purpose:
    Catch silent rot in `.claude/memory/` (the shared index) and
    `.claude/agent-memory/<role>/` (per-role re-entry files) mechanically —
    dead links, orphaned files, oversized entries, stale facts, broken body
    references, and possible duplicate lessons — the same checks a human
    previously had to notice by hand.

Public API:
    - read_thresholds — memory_max_bytes/memory_stale_days overrides from
      the fenced ```ini block of `.claude/modes/_stack.md`
    - parse_first_ini_block — the shared ini-block scan behind read_thresholds
      (also reused by Task 3.5's own config, and by `../hooks/_lib/stack-ini.sh`)
    - lint_memory_dir — WARN list for one `.claude/memory/`-shaped directory
    - lint_role_memory — WARN list for `.claude/agent-memory/` (every role)
    - main — CLI entry point (`--json`, `--roles`, exit 0/1)

Stability: lite

Why: `.claude/memory/MEMORY.md` (the shared index) and `.claude/agent-memory/
<role>/MEMORY.md` (per-role re-entry files) both rot silently — a renamed
file leaves a dead link, a manually-dropped file leaves an orphan, an
unchecked entry grows past Claude Code's 200-line/25KB re-entry ceiling, a
fact goes unverified for months. Nothing previously caught any of this
mechanically; a human had to notice. This script is that mechanical check —
runnable standalone (`--json` for CI/doctor consumption) and loaded dynamically
by `claude_kit_claude.doctor.check_memory` the same way `doctor.py` already
loads `validate_commit.py` by path (`template/` is package data, not an
importable package — see that module's `_load_validate_commit_for_doctor`).

Two independent stores, two entry points:

  * `lint_memory_dir(memory_dir, ...)` — the shared `.claude/memory/` index +
    entry files. Per-entry WARN codes: `dead-link` (index references a file
    absent on disk), `orphan` (a file on disk the index never references —
    `MEMORY.md` itself is never its own orphan), `oversized` (an entry file
    over `max_bytes`), `broken-body-ref` (an entry's body names a
    repo-relative path, in backticks, that does not exist), `stale`
    (frontmatter `metadata.last-verified` older than `stale_days` — a plain
    injectable `today: date`, never `date.today()` read internally, keeps
    this deterministic in tests). Per-index WARN codes, about `MEMORY.md`
    itself (Task 2.4 it2, cto verdict — "native auto-memory" makes the WHOLE
    index part of the system prompt every session, so its own size/shape now
    matters mechanically): `index-truncated` (over Claude Code's own
    200-line/25KB native auto-memory ceiling — past this CC silently
    truncates it), `index-over-budget` (over the softer, project-tunable
    `index_max_bytes`), `line-too-long` (one index line over
    `INDEX_LINE_MAX_CHARS`).
  * `lint_role_memory(agent_memory_root, ...)` — the per-role
    `agent-memory/<role>/MEMORY.md` re-entry files. WARN codes:
    `role-oversized` (over Claude Code's own 200-line/25KB injection ceiling —
    past that, content is silently truncated and the re-entry point stops
    working) and `possible-duplicate` (two lesson files in the same role
    whose `description` frontmatter overlaps heavily — the exact collision
    named in phase-2.md Task 2.4's "Коллизия параллельной записи": two
    parallel worktrees of the same role independently filing the *same*
    lesson under two names, e.g.
    `worktree-inherited-virtualenv-breaks-uv-run-pytest.md` vs
    `uv-run-pytest-worktree-fallthrough.md`).

A warning is a plain JSON-friendly ``dict`` with at least ``code`` / ``path`` /
``message`` — mirrors the ``Check``/``Section`` simplicity ``doctor.py`` and
``lint_settings.py`` already use, so a caller can render it either way.

`read_thresholds(text)` reads the FIRST fenced ```ini block anywhere in
`.claude/modes/_stack.md` that carries a recognised key (`tests_gate*` /
`memory_*` / `session_lock*` / `pre_report_gate*` / `agent_context_*` — same gate
`validate_commit.gate_config_block`
already applies for its own `tests_gate*` key, generalised here so an
unrelated/example ```ini block earlier in the file does not shadow the real
config block, review Task 2.4 it1 R3) for `memory_max_bytes` /
`memory_stale_days` overrides, defaulting to `DEFAULT_MAX_BYTES` /
`DEFAULT_STALE_DAYS` below. The underlying scan (`parse_first_ini_block`) is
written as a small, reusable function on purpose — Task 3.5 (plan
`system-to-eight`, phase-2.md Task 2.4 step 3) reuses it the same by-path-load
way this module reuses `validate_commit.py`, rather than re-implementing a
second ini-block scanner (the Task 6.2 lesson: two parsers of the same config
eventually disagree). The bash equivalent lives at `../hooks/_lib/stack-ini.sh`
— one concept, one behaviour, two runtimes.

Exit codes (``main``): 0 — no warnings; 1 — at least one warning. Every check
here is WARN-only (no ERROR severity), so this collapses `lint_settings.py`'s
0/1/2 convention to 0/1.

Stdlib only — no extra deps so it can run in any venv / pre-commit hook / a
freshly bootstrapped project with nothing installed yet.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any

__all__ = [
    "read_thresholds",
    "parse_first_ini_block",
    "lint_memory_dir",
    "lint_role_memory",
    "main",
]

#: Fenced-block WARN thresholds — overridable via the ```ini block of
#: `.claude/modes/_stack.md` (`memory_max_bytes` / `memory_stale_days`, see
#: `read_thresholds`).
DEFAULT_MAX_BYTES = 4096
DEFAULT_STALE_DAYS = 90

#: Claude Code's own subagent-memory injection ceiling (`.claude/CLAUDE.md` →
#: "Subagent-memory (нативная CC)"): past this, CC silently truncates what it
#: injects into the role's system prompt — the re-entry point stops working
#: without any error. `lint_role_memory`'s defaults mirror it exactly.
ROLE_MAX_BYTES = 25 * 1024
ROLE_MAX_LINES = 200

#: The SAME native ceiling as `ROLE_MAX_BYTES`/`ROLE_MAX_LINES`, but for the
#: SHARED index (`.claude/memory/MEMORY.md`) once it is loaded natively via
#: `autoMemoryDirectory` (Task 2.4 it2, cto verdict
#: `docs/reviews/2026-09-14_cto-verdict-e1-memory-banner.md` §"Что
#: воспроизведено" point 4 / `native_memory.py`) — past this, CC silently
#: truncates the index it puts in the system prompt, the exact failure mode
#: `index-truncated` exists to catch mechanically instead of by surprise.
#: NOT overridable: this is a fact about Claude Code, not a project
#: preference (unlike `DEFAULT_INDEX_MAX_BYTES` below).
INDEX_MAX_LINES = 200
INDEX_MAX_BYTES = 25 * 1024

#: The index's own SOFTER, project-tunable size budget — how much of
#: `INDEX_MAX_BYTES` a project actually wants to spend on the index every
#: session, overridable via `memory_index_max_bytes` in `_stack.md`'s
#: fenced ```ini block (see `read_thresholds`). cto verdict Task 2.4 it2 §1
#: "Линза «токены»": 8192 raw bytes ≈ +1.4k tokens/call vs. a 12-line banner,
#: judged worth it for a full index instead of a partial, unread selection.
DEFAULT_INDEX_MAX_BYTES = 8192

#: `line-too-long` — a single index line (any line of MEMORY.md, outside a
#: fenced code block) longer than this many characters. A constant, not a
#: `_stack.md` override (cto verdict Task 2.4 it2 §3 point 3: "тоже
#: порог-константа") — unlike `memory_index_max_bytes` this isn't a project
#: preference, it is what stops one verbose entry from silently eating most
#: of the always-loaded index (this repo's own index averaged 346
#: chars/entry before the Task 2.5 triage, well past this).
INDEX_LINE_MAX_CHARS = 150

#: Two lesson files in the same role directory whose `description` frontmatter
#: token-overlap (overlap coefficient |A∩B| / min(|A|,|B|), over lowercased
#: `[a-z0-9_]+` tokens with common English stop-words removed — see
#: `_STOPWORDS` / `_overlap_coefficient`) is at or above this are flagged
#: `possible-duplicate`. Review Task 2.4 it1 R5: the original Jaccard measure
#: (|A∩B| / |A∪B|) penalises a short retelling against a long original
#: description even when the short one is fully contained in the long one —
#: exactly the real class of incident this check exists for (a terse
#: re-filed duplicate of a verbose original), which Jaccard let straight
#: through (~0.1-0.25 on three plausible retellings of
#: `worktree-inherited-virtualenv-breaks-uv-run-pytest.md`'s real 51-token
#: description, all below the old 0.4 threshold). The overlap coefficient
#: does not have that length penalty; the same three retellings score
#: ~0.6-0.9. See
#: `tests/contract/test_memory_lint.py::TestPossibleDuplicate` for the exact
#: fixtures and measured numbers on both this repo's real role directories
#: (0 false positives) and the retelling fixture (all flagged).
_DUPLICATE_THRESHOLD = 0.5

#: Common English stop-words stripped from description tokens before the
#: overlap-coefficient comparison above — without this, two genuinely
#: distinct one-line hooks sharing only glue words ("a", "the", "in", "for")
#: would inflate the overlap score on short descriptions where every token
#: carries proportionally more weight.
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "in",
        "on",
        "at",
        "to",
        "of",
        "and",
        "or",
        "is",
        "are",
        "was",
        "were",
        "be",
        "this",
        "that",
        "it",
        "its",
        "for",
        "with",
        "as",
        "by",
        "from",
        "but",
        "not",
        "so",
        "if",
        "when",
        "which",
        "who",
        "what",
        "how",
        "than",
        "then",
        "also",
        "only",
        "into",
        "onto",
        "via",
        "per",
        "each",
        "every",
        "any",
        "all",
        "some",
        "such",
        "these",
        "those",
        "there",
        "here",
        "own",
        "same",
        "other",
        "you",
        "your",
        "even",
    }
)

_INDEX_LINK_RE = re.compile(r"^-\s*\[[^\]]*\]\(([^)]+\.md)\)")
_BACKTICK_RE = re.compile(r"`([^`\s]+)`")
_PATH_LIKE_RE = re.compile(r"^[\w./-]+/[\w./-]*\.[A-Za-z0-9]+$")

#: `broken-body-ref` plausibility gate (review Task 2.4 it1 R4): a candidate
#: whose lowercased path segment is one of these, or that has a bare
#: single-uppercase-letter segment, or that contains the literal "YYYY", is
#: documentation filler (`docs/sessions/YYYY-MM-DD.md`, `hooks/core/foo.sh`,
#: `X/__init__.py`), not a real broken reference.
_PLACEHOLDER_SEGMENTS = {"foo", "bar", "baz", "qux", "example"}
_FENCE_RE = re.compile(r"^(?P<fence>```+|~~~+)\s*(?P<info>\S*)\s*$")


# ---------------------------------------------------------------------------
# Shared ini-block scan (see the module docstring — reused, not re-derived, by
# Task 3.5). Mirrors validate_commit.py's `_scan_ini_block`, INCLUDING its
# "must carry a recognised key" gate (review Task 2.4 it1 R3: without it, an
# unrelated/example ```ini block earlier in `_stack.md` silently shadowed the
# real config block for every caller). The recognised-key prefixes below are
# a superset of validate_commit's own `tests_gate*` — `memory_*` for this
# module's own thresholds, `session_lock*` reserved for Task 3.5's config,
# `pre_report_gate*` for the SubagentStop gate of Task 2.7 (a project may carry
# a config block with ONLY that key — without it here the block is invisible),
# `agent_context_*` for the subagent context-budget hook of Task 2.6 (same reason).
# ---------------------------------------------------------------------------

_KNOWN_KEY_PREFIXES = (
    "tests_gate",
    "memory_",
    "session_lock",
    "pre_report_gate",
    "agent_context_",
)


def _has_known_key(block: dict[str, str]) -> bool:
    return any(k.startswith(_KNOWN_KEY_PREFIXES) for k in block)


def parse_first_ini_block(text: str) -> dict[str, str]:
    """The ``key = value`` pairs of the first fenced ```ini block in *text*
    that carries at least one recognised key (``tests_gate*`` / ``memory_*``
    / ``session_lock*`` / ``pre_report_gate*`` / ``agent_context_*``) — an earlier ```ini block
    without one of those is
    treated as decorative/example prose and skipped, mirroring
    ``validate_commit.py``'s ``_scan_ini_block`` gate.

    Returns ``{}`` when no such block exists. A trailing ``# comment`` on a
    line is stripped before the value is taken. Blank lines and full-line
    comments (``#...``) inside the block are skipped.
    """
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        match = _FENCE_RE.match(lines[i].strip())
        if not match or match.group("info").lower() != "ini":
            i += 1
            continue
        closing = match.group("fence")[0] * 3
        body: list[str] = []
        j = i + 1
        while j < len(lines) and not lines[j].strip().startswith(closing):
            body.append(lines[j])
            j += 1
        result: dict[str, str] = {}
        for raw in body:
            stripped = raw.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if "=" not in stripped:
                continue
            key, _, value = stripped.partition("=")
            result[key.strip().lower()] = value.split("#", 1)[0].strip()
        if _has_known_key(result):
            return result
        i = j + 1
    return {}


def read_thresholds(stack_md_text: str) -> dict[str, int]:
    """``{"memory_max_bytes": int, "memory_stale_days": int,
    "memory_index_max_bytes": int}`` from *stack_md_text*.

    Falls back to :data:`DEFAULT_MAX_BYTES` / :data:`DEFAULT_STALE_DAYS` /
    :data:`DEFAULT_INDEX_MAX_BYTES` when the key is absent from the block, the
    block itself is absent, or the value is not a valid integer (a typo must
    not silently disable the ceiling with a crash).
    """
    block = parse_first_ini_block(stack_md_text)
    thresholds = {
        "memory_max_bytes": DEFAULT_MAX_BYTES,
        "memory_stale_days": DEFAULT_STALE_DAYS,
        "memory_index_max_bytes": DEFAULT_INDEX_MAX_BYTES,
    }
    for key in thresholds:
        raw = block.get(key)
        if raw is None:
            continue
        try:
            thresholds[key] = int(raw.strip("`").strip("'\""))
        except ValueError:
            continue
    return thresholds


# ---------------------------------------------------------------------------
# Frontmatter — a tiny stdlib-only parser (no PyYAML dependency). Only the
# shapes this project's own memory files use are supported: a top-level
# ``key: value`` and one level of nesting under ``metadata:`` (``type``,
# ``last-verified``) — see `.claude/CLAUDE.md` -> "Memory (OVERRIDE)".
# ---------------------------------------------------------------------------


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """``(fields, body)`` — ``fields`` keyed ``"name"`` / ``"description"`` /
    ``"metadata.type"`` / ``"metadata.last-verified"``; ``body`` is everything
    after the closing ``---`` fence (raw text, unparsed).

    ``({}, text)`` when *text* does not open with a ``---`` frontmatter fence.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text

    fields: dict[str, str] = {}
    current_prefix = ""
    i = 1
    while i < len(lines) and lines[i].strip() != "---":
        line = lines[i]
        stripped = line.strip()
        i += 1
        if not stripped or stripped.startswith("#") or ":" not in stripped:
            continue
        indent = len(line) - len(line.lstrip(" "))
        key, _, value = stripped.partition(":")
        key = key.strip()
        value = value.strip()
        if indent == 0:
            current_prefix = key
            if value:
                fields[key] = value
        elif current_prefix:
            fields[f"{current_prefix}.{key}"] = value
    body = "\n".join(lines[i + 1 :])
    return fields, body


def _warn(code: str, path: str, message: str) -> dict[str, Any]:
    return {"code": code, "path": path, "message": message}


def _line_count(raw: bytes) -> int:
    """Line count matching Claude Code's own reckoning: a trailing newline
    does not count an extra (empty) line, but content after the last
    newline does. Shared by the ``index-truncated`` (shared index) and
    ``role-oversized`` (per-role index) checks — same ceiling, same formula."""
    return raw.count(b"\n") + (1 if raw and not raw.endswith(b"\n") else 0)


def _looks_like_placeholder(candidate: str) -> bool:
    """True when *candidate* reads as illustrative prose, not a real path.

    ``docs/sessions/YYYY-MM-DD.md`` (contains the literal date-template
    token), ``hooks/core/foo.sh`` (a placeholder segment), and
    ``X/__init__.py`` (a bare single-uppercase-letter segment) are all
    examples pulled from the current repo's own memory body text.
    """
    if "YYYY" in candidate:
        return True
    for segment in re.split(r"[/.]", candidate):
        if not segment:
            continue
        if segment.lower() in _PLACEHOLDER_SEGMENTS:
            return True
        if re.fullmatch(r"[A-Z]", segment):
            return True
    return False


def _is_plausible_repo_path(candidate: str, repo_root: Path) -> bool:
    """True when *candidate* is worth an existence check at all.

    Review Task 2.4 it1 R4: without this gate, ``broken-body-ref`` drowned
    every other doctor section in noise (84 of 98 WARN on this repo's own
    memory) — most of them partial paths that DO exist, just not directly
    under ``repo_root`` (e.g. ``core/mcp/ROUTING.md``, whose real location is
    ``src/claude_kit_claude/template/plugins/core/mcp/ROUTING.md`` — ``core``
    is not itself a top-level repo directory), plus illustrative
    placeholders (see :func:`_looks_like_placeholder`).

    Requiring the FIRST path segment to be an existing directory at
    ``repo_root`` also closes a minor security note from the review: an
    absolute path (``/etc/...``) or a ``..`` segment previously reached
    ``.exists()`` unchanged, letting a memory-entry body's *content* probe
    the filesystem OUTSIDE the repo (harmless here — WARN-only, local output
    — but an unintended oracle nonetheless). Both are rejected outright,
    before any filesystem check.
    """
    if candidate.startswith("/"):
        return False
    if ".." in Path(candidate).parts:
        return False
    if _looks_like_placeholder(candidate):
        return False
    first_segment = candidate.split("/", 1)[0]
    return (repo_root / first_segment).is_dir()


# ---------------------------------------------------------------------------
# lint_memory_dir — the shared `.claude/memory/` index + entry files.
# ---------------------------------------------------------------------------


def lint_memory_dir(
    memory_dir: Path,
    *,
    repo_root: Path,
    max_bytes: int = DEFAULT_MAX_BYTES,
    stale_days: int = DEFAULT_STALE_DAYS,
    index_max_bytes: int = DEFAULT_INDEX_MAX_BYTES,
    today: date | None = None,
) -> list[dict[str, Any]]:
    """WARN list for one `.claude/memory/`-shaped directory.

    *today* must be injected by the caller (never ``date.today()`` read
    internally) so the `stale` check is deterministic in tests — a fixed
    `last-verified` age must not depend on the wall clock the test happens to
    run on. Codes: ``dead-link``, ``orphan``, ``oversized``,
    ``broken-body-ref``, ``stale`` (all about individual entry files), plus
    ``index-truncated``, ``index-over-budget``, ``line-too-long`` (all about
    ``MEMORY.md`` — the shared index file — itself). An index-less or missing
    directory yields ``[]`` rather than raising — every check here degrades,
    never crashes.

    Pre:
      - *repo_root* is the directory ``broken-body-ref`` candidates resolve
        against; it need not equal or contain *memory_dir*.
    Post:
      - every item in the returned list has ``code`` / ``path`` / ``message``
        keys.
      - never raises on a missing/unreadable ``memory_dir``, entry file, or
        malformed frontmatter — returns fewer warnings instead.
    """
    if today is None:
        today = date.today()
    memory_dir = Path(memory_dir)
    repo_root = Path(repo_root)
    if not memory_dir.is_dir():
        return []

    index_path = memory_dir / "MEMORY.md"
    index_text = ""
    index_raw = b""
    if index_path.is_file():
        try:
            index_raw = index_path.read_bytes()
            index_text = index_raw.decode("utf-8")
        except (OSError, UnicodeDecodeError):
            index_text = ""
            index_raw = b""

    # Skip fenced code blocks while scanning for index links AND overlong
    # lines -- the bundled empty skeleton's own "Формат строки" section ships
    # illustrative "- [...](...)" lines INSIDE ``` fences (format doc +
    # examples). Those are prose, not real index entries; matching them would
    # flag a freshly bootstrapped, untouched project as having dead links or
    # an overlong illustrative line. Mirrors `session-memory-banner.sh`'s
    # identical fence-skip discipline.
    indexed_refs: set[str] = set()
    long_lines: list[tuple[int, str]] = []
    in_fence = False
    for line_no, line in enumerate(index_text.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if len(line) > INDEX_LINE_MAX_CHARS:
            long_lines.append((line_no, line))
        match = _INDEX_LINK_RE.match(stripped)
        if match:
            indexed_refs.add(match.group(1))

    entry_files = sorted(p for p in memory_dir.glob("*.md") if p.name != "MEMORY.md")
    entry_names = {p.name for p in entry_files}

    warnings: list[dict[str, Any]] = []

    # index-truncated: MEMORY.md itself is past Claude Code's own native
    # auto-memory injection ceiling -- past this, CC silently truncates what
    # it loads into the system prompt (the same failure mode
    # `role-oversized` catches for a per-role file, here for the shared
    # index). Independent of, and checked before, the softer
    # `index-over-budget` below -- an index can be both at once.
    if index_path.is_file():
        index_line_count = _line_count(index_raw)
        if len(index_raw) > INDEX_MAX_BYTES or index_line_count > INDEX_MAX_LINES:
            warnings.append(
                _warn(
                    "index-truncated",
                    str(index_path),
                    f"MEMORY.md is {len(index_raw)} bytes / {index_line_count} lines "
                    f"(over Claude Code's native auto-memory ceiling of "
                    f"{INDEX_MAX_BYTES} bytes / {INDEX_MAX_LINES} lines — past this, "
                    "CC silently truncates what it loads into the system prompt)",
                )
            )

        # index-over-budget: a SOFTER, project-tunable ceiling (default
        # DEFAULT_INDEX_MAX_BYTES, override via `memory_index_max_bytes` in
        # `_stack.md`) -- how much of the hard ceiling above a project
        # actually wants to spend on the index every session.
        if len(index_raw) > index_max_bytes:
            warnings.append(
                _warn(
                    "index-over-budget",
                    str(index_path),
                    f"MEMORY.md is {len(index_raw)} bytes, over the "
                    f"{index_max_bytes}-byte memory_index_max_bytes budget",
                )
            )

        # line-too-long: one entry silently eating most of the always-loaded
        # index. One WARN per offending line.
        for line_no, line in long_lines:
            warnings.append(
                _warn(
                    "line-too-long",
                    f"{index_path}:{line_no}",
                    f"MEMORY.md line {line_no} is {len(line)} chars, over the "
                    f"{INDEX_LINE_MAX_CHARS}-char index-line budget",
                )
            )

    # dead-link: index references a file that is not on disk.
    for ref in sorted(indexed_refs):
        if ref not in entry_names:
            warnings.append(
                _warn(
                    "dead-link",
                    str(memory_dir / ref),
                    f"MEMORY.md references '{ref}', which does not exist on disk",
                )
            )

    # orphan: a file on disk the index never references.
    for entry in entry_files:
        if entry.name not in indexed_refs:
            warnings.append(
                _warn(
                    "orphan",
                    str(entry),
                    f"'{entry.name}' exists on disk but is not referenced by MEMORY.md",
                )
            )

    # Per-file checks: oversized / stale / broken-body-ref.
    for entry in entry_files:
        try:
            raw = entry.read_bytes()
        except OSError:
            continue
        if len(raw) > max_bytes:
            warnings.append(
                _warn(
                    "oversized",
                    str(entry),
                    f"'{entry.name}' is {len(raw)} bytes, over the {max_bytes}-byte threshold",
                )
            )
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        fields, body = _parse_frontmatter(text)

        last_verified = fields.get("metadata.last-verified")
        if last_verified:
            try:
                lv_date = date.fromisoformat(last_verified)
            except ValueError:
                lv_date = None
            if lv_date is not None and (today - lv_date).days > stale_days:
                age = (today - lv_date).days
                warnings.append(
                    _warn(
                        "stale",
                        str(entry),
                        f"'{entry.name}' last-verified {last_verified} is {age} days old "
                        f"(> {stale_days})",
                    )
                )

        for candidate in _BACKTICK_RE.findall(body):
            if not _PATH_LIKE_RE.match(candidate):
                continue
            if not _is_plausible_repo_path(candidate, repo_root):
                continue
            full = (repo_root / candidate).resolve()
            try:
                full.relative_to(repo_root.resolve())
            except ValueError:
                continue  # would resolve outside repo_root -- never warn on this
            if not full.exists():
                warnings.append(
                    _warn(
                        "broken-body-ref",
                        str(entry),
                        f"'{entry.name}' body references '{candidate}', which does not "
                        "exist in the repo",
                    )
                )

    return warnings


# ---------------------------------------------------------------------------
# lint_role_memory — per-role `agent-memory/<role>/MEMORY.md` re-entry files.
# ---------------------------------------------------------------------------


def _description_tokens(text: str) -> set[str]:
    tokens = set(re.findall(r"[a-z0-9_]+", text.lower()))
    return tokens - _STOPWORDS


def _overlap_coefficient(a: set[str], b: set[str]) -> float:
    """``|A∩B| / min(|A|,|B|)`` — unlike Jaccard (``|A∩B| / |A∪B|``), a short
    description fully contained in a longer one scores 1.0 here, not
    penalised by the longer set's extra tokens. That is exactly the real
    incident class `possible-duplicate` exists to catch (review Task 2.4 it1
    R5): a terse re-filed duplicate of a verbose original."""
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def lint_role_memory(
    agent_memory_root: Path,
    *,
    max_bytes: int = ROLE_MAX_BYTES,
    max_lines: int = ROLE_MAX_LINES,
) -> list[dict[str, Any]]:
    """WARN list for `.claude/agent-memory/` (every role subdirectory).

    Codes: ``role-oversized`` (a role's own ``MEMORY.md`` over Claude Code's
    injection ceiling) and ``possible-duplicate`` (two lesson files in the
    same role directory whose ``description`` frontmatter overlaps at or
    above :data:`_DUPLICATE_THRESHOLD` — see the module docstring for the
    real incident this reproduces). A missing root yields ``[]``.

    Pre:
      - none — *agent_memory_root* need not exist.
    Post:
      - every item in the returned list has ``code`` / ``path`` / ``message``
        keys.
      - never raises on a missing/unreadable role directory or malformed
        frontmatter — returns fewer warnings instead.
    """
    agent_memory_root = Path(agent_memory_root)
    if not agent_memory_root.is_dir():
        return []

    warnings: list[dict[str, Any]] = []

    for role_dir in sorted(p for p in agent_memory_root.iterdir() if p.is_dir()):
        index_path = role_dir / "MEMORY.md"
        if index_path.is_file():
            try:
                raw = index_path.read_bytes()
            except OSError:
                raw = b""
            n_lines = _line_count(raw)
            if len(raw) > max_bytes or n_lines > max_lines:
                warnings.append(
                    _warn(
                        "role-oversized",
                        str(index_path),
                        f"'{role_dir.name}/MEMORY.md' is {len(raw)} bytes / {n_lines} lines "
                        f"(over {max_bytes} bytes or {max_lines} lines — Claude Code silently "
                        "truncates past this, breaking the re-entry point)",
                    )
                )

        lessons = sorted(p for p in role_dir.glob("*.md") if p.name != "MEMORY.md")
        descriptions: list[tuple[Path, set[str]]] = []
        for lesson in lessons:
            try:
                fields, _body = _parse_frontmatter(lesson.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError):
                continue
            description = fields.get("description")
            if description:
                descriptions.append((lesson, _description_tokens(description)))

        for idx, (path_a, tokens_a) in enumerate(descriptions):
            for path_b, tokens_b in descriptions[idx + 1 :]:
                overlap = _overlap_coefficient(tokens_a, tokens_b)
                if overlap >= _DUPLICATE_THRESHOLD:
                    warnings.append(
                        _warn(
                            "possible-duplicate",
                            str(role_dir),
                            f"'{path_a.name}' and '{path_b.name}' look like the same "
                            f"lesson filed twice (description overlap {overlap:.2f})",
                        )
                    )

    return warnings


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Lint a .claude/memory/-shaped directory for dead links, "
        "orphans, oversized/stale entries and broken body refs."
    )
    parser.add_argument("memory_dir", help="path to the memory directory to lint")
    parser.add_argument(
        "--repo-root",
        default=".",
        help="repo root body-ref paths resolve against (default: cwd)",
    )
    parser.add_argument(
        "--stack-md",
        default=None,
        help="path to _stack.md to read memory_max_bytes/memory_stale_days "
        "overrides from (default: <repo-root>/.claude/modes/_stack.md)",
    )
    parser.add_argument(
        "--today",
        default=None,
        help="ISO date to treat as 'now' for the stale check (default: real today)",
    )
    parser.add_argument(
        "--roles",
        action="store_true",
        help="lint MEMORY_DIR as a `.claude/agent-memory/` ROLES root "
        "(lint_role_memory: role-oversized / possible-duplicate) instead of "
        "the shared `.claude/memory/` index shape (lint_memory_dir, the "
        "default) — review Task 2.4 it1 R11: without this flag, pointing "
        "the CLI at an agent-memory root silently found nothing (no "
        "MEMORY.md index there to dead-link/orphan-check) and reported "
        "'OK', even when the doctor's own check_memory found real "
        "role-oversized warnings on the exact same tree",
    )
    parser.add_argument(
        "--json", action="store_true", help="emit warnings as a JSON list"
    )
    args = parser.parse_args(argv)

    if args.roles:
        warnings = lint_role_memory(Path(args.memory_dir))
    else:
        today = date.fromisoformat(args.today) if args.today else date.today()
        repo_root = Path(args.repo_root)
        stack_md_path = (
            Path(args.stack_md)
            if args.stack_md is not None
            else repo_root / ".claude" / "modes" / "_stack.md"
        )
        try:
            stack_md_text = (
                stack_md_path.read_text(encoding="utf-8")
                if stack_md_path.is_file()
                else ""
            )
        except (OSError, UnicodeDecodeError):
            stack_md_text = ""
        thresholds = read_thresholds(stack_md_text)

        warnings = lint_memory_dir(
            Path(args.memory_dir),
            repo_root=repo_root,
            max_bytes=thresholds["memory_max_bytes"],
            stale_days=thresholds["memory_stale_days"],
            index_max_bytes=thresholds["memory_index_max_bytes"],
            today=today,
        )

    if args.json:
        print(json.dumps(warnings))
    elif warnings:
        for w in warnings:
            print(f"WARN [{w['code']}] {w['path']}: {w['message']}")
    else:
        print("OK — no warnings")

    return 1 if warnings else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
