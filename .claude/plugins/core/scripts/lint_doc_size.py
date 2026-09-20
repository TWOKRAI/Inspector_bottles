#!/usr/bin/env python3
"""lint_doc_size.py — stdlib-only WARN-only linter over markdown document size.

Purpose:
    Flag markdown files and heading-delimited sections too big for the
    project's own tooling to ingest — the qex embedder chunks at a fixed
    token window (2048 on Windows / 4096 on macOS), so the tail of an
    oversized section never reaches dense search; graphify hands documents to
    one subagent in batches of 20-25 files, so one 100 KB file eats its whole
    context. Never a gate — mechanical WARN only, same convention as its
    sibling ``memory_lint.py`` in this directory.

Public API:
    - iter_markdown — every ``*.md`` under a root (git-tracked when the root
      is a git work tree, else a filesystem walk)
    - section_sizes — a markdown text split into heading-delimited sections,
      each with its UTF-8 byte size
    - lint — the WARN findings for one root (``FILE_TOO_BIG`` /
      ``SECTION_TOO_BIG``)
    - Finding — one WARN row (``path`` / ``code`` / ``size_kb`` / ``detail``)
    - main — CLI entry point (``--root``, ``--json``, exit 0/2)

Stability: lite

Sizes are measured in BYTES of UTF-8 (not characters) — Cyrillic text is 2
bytes/char in UTF-8, which tracks LLM tokenization more closely than a raw
character count, so this is intended, not a bug.

Thresholds (overridable via the fenced ```ini block of
``.claude/modes/_stack.md`` — see ``read_doc_size_config``):
    - ``doc_size_warn_kb`` (int, default 32) — a whole FILE over this many KB
    - ``doc_section_warn_kb`` (int, default 8) — a single heading-delimited
      SECTION over this many KB
    - ``doc_size_exempt`` (comma-separated globs, REPLACES the default list
      when present) — paths this linter never flags
    - ``doc_size`` (``on``/``off``, default ``on``) — ``off`` disables every
      finding without touching the other keys

Not imported from ``memory_lint.py``: that module's ``parse_first_ini_block``
gates a fenced ```ini block behind a "must carry a recognised key" check
whose recognised prefixes (``tests_gate*`` / ``memory_*`` / ``session_lock*``
/ ``pre_report_gate*`` / ``agent_context_*``) do not include ``doc_size`` —
importing it verbatim would silently ignore a project's ``doc_size_*``
overrides on any ``_stack.md`` whose shared block hasn't also picked up one
of those other keys yet (a fresh project, or one that never enabled memory
linting). The block-scanning MECHANICS below are copied from
``memory_lint.py``'s ``parse_first_ini_block`` (same file, same directory) —
same fenced-```ini-block dialect, same key=value parsing, same
"first-block-with-a-recognised-key-wins" gate design — with this module's
own recognised-key prefix (``doc_size``) instead of re-deriving a third
parser dialect.

Exit codes (``main``): 0 always, EXCEPT 2 when ``--root`` does not exist. This
linter is WARN-only by design (owner rule 2026-09-17: "Rules become
mechanics here: WARN, never a gate") — a project can have findings and still
build/ship; only a broken invocation (bad root) is an error.

Stdlib only — no extra deps; this ships to every consumer project and must
run in a fresh venv with nothing installed yet.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

__all__ = [
    "iter_markdown",
    "section_sizes",
    "lint",
    "Finding",
    "read_doc_size_config",
    "read_doc_size_config_for_root",
    "main",
]

#: WARN thresholds — overridable via the ```ini block of
#: `.claude/modes/_stack.md` (see `read_doc_size_config`).
DEFAULT_FILE_KB = 32
DEFAULT_SECTION_KB = 8

#: Paths this linter never flags, matched with `fnmatch` semantics against
#: the POSIX-style path relative to the scanned root (`**` spans directories
#: because `fnmatch`'s `*` already matches `/` — it has no path-separator
#: awareness of its own). Replaced wholesale, not merged, by a project's own
#: `doc_size_exempt` override.
DEFAULT_EXEMPT: tuple[str, ...] = (
    "CHANGELOG.md",
    "**/_archive/**",
    "**/fixtures/**",
    "**/node_modules/**",
)

_ATX_HEADING_RE = re.compile(r"^#{1,6}[ \t]")
_FENCE_LINE_RE = re.compile(r"^(?P<fence>`{3,}|~{3,})")

_SKIP_DIR_NAMES = frozenset({".git", ".venv", "node_modules"})


@dataclass(frozen=True, slots=True)
class Finding:
    """One WARN row. ``code`` is ``FILE_TOO_BIG`` or ``SECTION_TOO_BIG``;
    ``detail`` is empty for the former, the offending heading's text for the
    latter."""

    path: str
    code: str
    size_kb: float
    detail: str


# ---------------------------------------------------------------------------
# iter_markdown — every *.md under root.
# ---------------------------------------------------------------------------


def _iter_markdown_via_git(root: Path) -> list[Path] | None:
    """``git ls-files -z -- '*.md'`` output, or ``None`` when *root* is not
    usable as a git work tree (no ``.git``, git missing, or a non-zero exit —
    e.g. a bare/corrupt repo). ``None`` tells the caller to fall back to a
    filesystem walk instead."""
    if not (root / ".git").exists():
        return None
    try:
        result = subprocess.run(  # noqa: S603, S607 — fixed argv, no shell
            ["git", "ls-files", "-z", "--", "*.md"],
            cwd=root,
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    names = [chunk for chunk in result.stdout.split(b"\0") if chunk]
    return [root / name.decode("utf-8") for name in names]


def _iter_markdown_via_rglob(root: Path) -> list[Path]:
    found: list[Path] = []
    for path in root.rglob("*.md"):
        parts = path.relative_to(root).parts[:-1]  # directory parts only
        if any(part in _SKIP_DIR_NAMES for part in parts):
            continue
        found.append(path)
    return found


def iter_markdown(root: Path) -> list[Path]:
    """Every ``*.md`` under *root* — via ``git ls-files -z`` when *root* is a
    git work tree, else a plain :meth:`Path.rglob` skipping ``.git``,
    ``.venv``, ``node_modules``."""
    root = Path(root)
    via_git = _iter_markdown_via_git(root)
    if via_git is not None:
        return via_git
    return _iter_markdown_via_rglob(root)


# ---------------------------------------------------------------------------
# section_sizes — heading-delimited sections, fence-aware.
# ---------------------------------------------------------------------------


def section_sizes(text: str) -> list[tuple[str, int]]:
    """Split *text* on ATX headings (``^#{1,6} ``) that are OUTSIDE fenced
    code blocks (``` `` ` or ``~~~`` fences — a heading-looking line inside a
    fence is not a boundary), return ``(heading, size_in_bytes_utf8)`` pairs.

    The heading text has its leading ``#``s and surrounding whitespace
    stripped (``"## Foo"`` -> ``"Foo"``). Content before the first heading
    (if any) is named ``"<preamble>"`` — omitted entirely when empty, so a
    file that starts directly with a heading never reports a spurious
    zero-byte preamble section.
    """
    lines = text.splitlines()
    sections: list[tuple[str, list[str]]] = [("<preamble>", [])]
    in_fence = False
    fence_char = ""
    fence_len = 0

    for line in lines:
        stripped = line.strip()
        if in_fence:
            match = _FENCE_LINE_RE.match(stripped)
            if (
                match
                and match.group("fence")[0] == fence_char
                and len(match.group("fence")) >= fence_len
            ):
                in_fence = False
            sections[-1][1].append(line)
            continue

        fence_match = _FENCE_LINE_RE.match(stripped)
        if fence_match:
            in_fence = True
            fence_char = fence_match.group("fence")[0]
            fence_len = len(fence_match.group("fence"))
            sections[-1][1].append(line)
            continue

        if _ATX_HEADING_RE.match(line):
            heading_text = line.lstrip("#").strip()
            sections.append((heading_text, [line]))
            continue

        sections[-1][1].append(line)

    result: list[tuple[str, int]] = []
    for heading, body_lines in sections:
        if heading == "<preamble>" and not body_lines:
            continue
        block = "\n".join(body_lines)
        result.append((heading, len(block.encode("utf-8"))))
    return result


# ---------------------------------------------------------------------------
# exempt matching
# ---------------------------------------------------------------------------


def _is_exempt(rel_posix: str, exempt: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatchcase(rel_posix, pattern) for pattern in exempt)


# ---------------------------------------------------------------------------
# lint — the public WARN scan.
# ---------------------------------------------------------------------------


def lint(
    root: Path,
    *,
    file_kb: int = DEFAULT_FILE_KB,
    section_kb: int = DEFAULT_SECTION_KB,
    exempt: tuple[str, ...] = DEFAULT_EXEMPT,
) -> list[Finding]:
    """WARN findings for every markdown file under *root*.

    ``FILE_TOO_BIG`` — the whole file exceeds ``file_kb`` KB. ``SECTION_TOO_BIG``
    — one finding per file: only the BIGGEST heading-delimited section, when
    it exceeds ``section_kb`` KB (the biggest section is, by construction,
    the only one that can exceed the threshold without a smaller one also
    doing so). A file can carry both findings at once. Never raises: an
    unreadable file or a decode failure is skipped, not reported.
    """
    root = Path(root)
    file_bytes_limit = file_kb * 1024
    section_bytes_limit = section_kb * 1024
    findings: list[Finding] = []

    for path in iter_markdown(root):
        try:
            rel_posix = path.relative_to(root).as_posix()
        except ValueError:
            rel_posix = path.as_posix()
        if _is_exempt(rel_posix, exempt):
            continue
        try:
            raw = path.read_bytes()
        except OSError:
            continue

        size = len(raw)
        if size > file_bytes_limit:
            findings.append(
                Finding(
                    path=rel_posix,
                    code="FILE_TOO_BIG",
                    size_kb=round(size / 1024, 1),
                    detail="",
                )
            )

        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue

        sections = section_sizes(text)
        if not sections:
            continue
        heading, biggest = max(sections, key=lambda item: item[1])
        if biggest > section_bytes_limit:
            findings.append(
                Finding(
                    path=rel_posix,
                    code="SECTION_TOO_BIG",
                    size_kb=round(biggest / 1024, 1),
                    detail=heading,
                )
            )

    return findings


# ---------------------------------------------------------------------------
# ini-block scan — copied (minimal) from memory_lint.py's parse_first_ini_block
# (same directory: src/claude_kit_claude/template/plugins/core/scripts/
# memory_lint.py) — same fenced ```ini block dialect and "first block with a
# recognised key wins" gate design, scoped to THIS module's own recognised
# key prefix (see the module docstring for why it is copied, not imported).
# ---------------------------------------------------------------------------

_INI_FENCE_RE = re.compile(r"^(?P<fence>```+|~~~+)\s*(?P<info>\S*)\s*$")
_KNOWN_KEY_PREFIX = "doc_size"


def _has_known_key(block: dict[str, str]) -> bool:
    return any(k.startswith(_KNOWN_KEY_PREFIX) for k in block)


def _parse_first_ini_block(text: str) -> dict[str, str]:
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        match = _INI_FENCE_RE.match(lines[i].strip())
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


def read_doc_size_config(stack_md_text: str) -> dict[str, Any]:
    """``{"file_kb", "section_kb", "exempt", "enabled"}`` from
    *stack_md_text*'s fenced ```ini block — falls back to the module defaults
    for any key that is absent, unparsable, or the block itself absent."""
    block = _parse_first_ini_block(stack_md_text)
    config: dict[str, Any] = {
        "file_kb": DEFAULT_FILE_KB,
        "section_kb": DEFAULT_SECTION_KB,
        "exempt": DEFAULT_EXEMPT,
        "enabled": True,
    }

    raw_file_kb = block.get("doc_size_warn_kb")
    if raw_file_kb is not None:
        try:
            config["file_kb"] = int(raw_file_kb.strip("`").strip("'\""))
        except ValueError:
            pass

    raw_section_kb = block.get("doc_section_warn_kb")
    if raw_section_kb is not None:
        try:
            config["section_kb"] = int(raw_section_kb.strip("`").strip("'\""))
        except ValueError:
            pass

    raw_exempt = block.get("doc_size_exempt")
    if raw_exempt is not None:
        globs = tuple(g.strip() for g in raw_exempt.split(",") if g.strip())
        if globs:
            config["exempt"] = globs

    raw_enabled = block.get("doc_size")
    if raw_enabled is not None:
        normalized = raw_enabled.strip("`").strip("'\"").strip().lower()
        config["enabled"] = normalized not in ("off", "false", "0", "no")

    return config


def read_doc_size_config_for_root(root: Path) -> dict[str, Any]:
    """:func:`read_doc_size_config` over ``<root>/.claude/modes/_stack.md`` —
    the single lookup both the CLI (``main``) and
    ``doctor.check_document_size`` call, so a project's ``doc_size_*``
    overrides apply the same way whether the linter runs standalone or is
    loaded in-process by the doctor against an arbitrary target root. A
    missing/unreadable ``_stack.md`` degrades to ``""`` (module defaults),
    never raises.
    """
    stack_md = Path(root) / ".claude" / "modes" / "_stack.md"
    try:
        stack_md_text = (
            stack_md.read_text(encoding="utf-8") if stack_md.is_file() else ""
        )
    except (OSError, UnicodeDecodeError):
        stack_md_text = ""
    return read_doc_size_config(stack_md_text)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _reconfigure_stdout_utf8() -> None:
    """Reconfigure stdout/stderr to UTF-8 with ``errors="replace"`` at the
    I/O boundary — without this, a non-ASCII heading/path crashes on a
    Windows cp1251 console (project memory:
    ``cli-nonascii-windows-encoding.md``; same pattern as
    ``mcp-graphify/scripts/graph_slice.py``)."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str]) -> int:
    _reconfigure_stdout_utf8()

    parser = argparse.ArgumentParser(
        description="Lint markdown files/sections too big for qex/graphify/an "
        "agent's Read (WARN-only, never a gate)."
    )
    parser.add_argument(
        "--root", default=".", help="project root to scan (default: cwd)"
    )
    parser.add_argument(
        "--json", action="store_true", help="emit findings as a JSON list"
    )
    args = parser.parse_args(argv)

    root = Path(args.root)
    if not root.exists():
        print(f"root does not exist: {root}", file=sys.stderr)
        return 2

    config = read_doc_size_config_for_root(root)

    if config["enabled"]:
        findings = lint(
            root,
            file_kb=config["file_kb"],
            section_kb=config["section_kb"],
            exempt=config["exempt"],
        )
    else:
        findings = []

    if args.json:
        print(json.dumps([asdict(f) for f in findings]))
    else:
        for f in findings:
            if f.code == "FILE_TOO_BIG":
                hint = "split by level-2 headings into separate files"
            else:
                hint = f"add sub-headings or split the section '{f.detail}'"
            print(f"{f.path}: {f.size_kb} KB: {f.code} — {hint}")
        print(f"{len(findings)} finding(s)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
