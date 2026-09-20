#!/usr/bin/env python3
"""lint_interpreter.py — stdlib-only gate linter: no bare ``python`` command
invocation in shipped markdown (commands/agents/skills).

Purpose:
    On macOS and Ubuntu there is no ``python`` binary on ``PATH`` by default
    (only ``python3``) — a consumer's agent following a shipped command's
    fenced shell example hits ``command not found`` on the first call and
    retries with ``python3``, friction on every invocation. ``uv`` is a hard
    prerequisite of this tool on every platform (Windows included), so
    ``uv run [--no-project] python`` is the one interpreter entry point that
    exists everywhere — the MCP launchers already moved to this form
    (commit ``8c00516``). This linter keeps that precedent at zero
    regressions across the shipped template.

Public API:
    - find_bare_python — the RULE: bare ``python`` command occurrences in one
      markdown text, fence-aware and inline-code-aware
    - iter_markdown — every ``*.md`` under a root (git-tracked when the root
      is a git work tree, else a filesystem walk)
    - lint — the findings for one root
    - Finding — one gate row (``path`` / ``line`` / ``snippet``)
    - main — CLI entry point (``--root``, ``--json``, exit 0/1/2)

Stability: lite

THE RULE (see plans/2026-09-17_rollout-and-stability/phase-3.md Task 3.4 for
the full design): a bare ``python`` invocation is the exact token ``python``
(not ``python3``, not prose that merely mentions it) used as a COMMAND —
either on a line inside a fenced code block (``` ``` `` or ``~~~``, any info
string except ``python``/``py``/``toml``/``json``/``yaml``/``ini``/``text``/
``diff`` — i.e. shell-like or unlabelled blocks) or inside inline code that
starts with ``python `` — AND the match sits at a command position: start of
line (after an optional ``$ ``/``> `` prompt and whitespace) or right after
one of ``&&``, ``||``, ``;``, ``|``, ``(``, ``$(``, `` ` ``, ``env …`` (with
optional ``VAR=val`` assignments), ``timeout N``. NOT a command position:
right after ``uv run``/``uv run --no-project``/``uvx``/``poetry run``/
``pipx run``/``conda run …``, a path ending in ``/`` (covers ``.venv/bin/``,
``venv/bin/``, ``/usr/bin/``, …), or a shebang line (``#!/usr/bin/env
python``) — shebang lines are skipped outright, both inside and outside a
scannable fence.

Fence and ``git ls-files`` MECHANICS below follow the same shape as this
directory's sibling ``lint_doc_size.py`` (state-machine over lines, ATX/fence
regex, ``git ls-files -z`` with an ``rglob`` fallback) — reimplemented here,
not imported, because the two linters track unrelated things (document size
vs. an interpreter token) and would otherwise share nothing but the walking
idiom.

Exit codes (``main``): 0 no findings, 1 findings present (THIS linter IS a
gate — Task 3.4 acceptance is "zero bare ``python`` in the shipped
template"), 2 when ``--root`` does not exist.

Stdlib only — no extra deps; this ships to every consumer project and must
run in a fresh venv with nothing installed yet.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

__all__ = [
    "find_bare_python",
    "iter_markdown",
    "lint",
    "Finding",
    "main",
]

#: Directory names skipped everywhere (git-tracked listing and rglob
#: fallback alike) — regenerated/vendored/archived content is not part of
#: the shipped-command surface this gate protects.
_SKIP_DIR_NAMES = frozenset({".git", ".venv", "node_modules", "_archive"})

#: Fence info strings that are NOT scanned — either already-correct Python
#: source (```python`` / ```py``) or data/config formats where the bare word
#: ``python`` is data, not a shell command.
_EXEMPT_FENCE_INFOS = frozenset(
    {"python", "py", "toml", "json", "yaml", "ini", "text", "diff"}
)

_MAX_SNIPPET_CHARS = 120


@dataclass(frozen=True, slots=True)
class Finding:
    """One gate row: *path* is POSIX-relative to the scanned root, *line* is
    1-based, *snippet* is the offending line trimmed to 120 chars."""

    path: str
    line: int
    snippet: str


# ---------------------------------------------------------------------------
# find_bare_python — THE RULE, fence-aware and inline-code-aware.
# ---------------------------------------------------------------------------

_FENCE_LINE_RE = re.compile(r"^(?P<fence>`{3,}|~{3,})\s*(?P<info>\S*)")
_PYTHON_TOKEN_RE = re.compile(r"\bpython\b")
_INLINE_CODE_RE = re.compile(r"`([^`]+)`")

#: Prefix (everything on the line before the "python" match) is a command
#: position when it is entirely whitespace, optionally preceded by a shell
#: prompt marker (``$ `` / ``> ``) — i.e. the match starts the line.
_LINE_START_RE = re.compile(r"^\s*(?:[$>]\s*)?$")

#: Prefix (right-stripped of trailing spaces/tabs) ends with a shell
#: operator that starts a new command.
_OPERATOR_END_RE = re.compile(r"(?:&&|\|\||;|\||\(|\$\(|`)$")

#: ``env`` (optionally with ``VAR=val`` assignments) immediately before the
#: match — ``env python foo.py`` / ``env FOO=bar python foo.py``.
_ENV_PREFIX_RE = re.compile(r"\benv\s+(?:[A-Za-z_][A-Za-z0-9_]*=\S+\s+)*$")

#: ``timeout N`` (with an optional unit suffix, e.g. ``timeout 30s``)
#: immediately before the match.
_TIMEOUT_PREFIX_RE = re.compile(r"\btimeout\s+\d+\S*\s+$")

#: Runner prefixes that make ``python`` NOT a bare invocation — ``uv run``,
#: ``uv run --no-project``, ``uvx``, ``poetry run``, ``pipx run``,
#: ``conda run <env-args>``.
_EXCLUDED_RUNNER_RE = re.compile(
    r"\b(?:uv run(?: --no-project)?|uvx|poetry run|pipx run|conda run(?:\s+\S+)*)\s+$"
)

#: Fence info strings that mark a block as a Windows-only example — THE
#: RULE's own "not a command position" carve-out ("a Windows-only example
#: explicitly marked by the surrounding text/``.ps1``/``py -3``"): on
#: Windows ``python``/``py`` already resolves via the Python Launcher, so
#: this task's macOS/Ubuntu portability problem does not apply there.
_WINDOWS_FENCE_INFOS = frozenset({"powershell", "ps1", "pwsh"})


def _is_shebang(line: str) -> bool:
    return line.strip().startswith("#!")


def _is_command_position(prefix: str) -> bool:
    if _LINE_START_RE.match(prefix):
        return True
    if _OPERATOR_END_RE.search(prefix.rstrip(" \t")):
        return True
    if _ENV_PREFIX_RE.search(prefix):
        return True
    if _TIMEOUT_PREFIX_RE.search(prefix):
        return True
    return False


def _is_excluded_runner(prefix: str) -> bool:
    # A path ending in "/" directly attached to "python" — .venv/bin/python,
    # venv/bin/python, /usr/bin/python, etc.
    if prefix.endswith("/"):
        return True
    return bool(_EXCLUDED_RUNNER_RE.search(prefix))


def _scan_fenced_line(line: str, lineno: int, findings: list[tuple[int, str]]) -> None:
    if _is_shebang(line):
        return
    for match in _PYTHON_TOKEN_RE.finditer(line):
        prefix = line[: match.start()]
        if _is_excluded_runner(prefix):
            continue
        if _is_command_position(prefix):
            findings.append((lineno, line.rstrip()))
            return


def _scan_inline_code(line: str, lineno: int, findings: list[tuple[int, str]]) -> None:
    if _is_shebang(line):
        return
    for match in _INLINE_CODE_RE.finditer(line):
        content = match.group(1)
        if content.startswith("python ") and _PYTHON_TOKEN_RE.match(content):
            findings.append((lineno, line.rstrip()))
            return


def find_bare_python(text: str) -> list[tuple[int, str]]:
    """Every bare ``python`` command occurrence in *text* — see the module
    docstring for THE RULE. Returns ``(1-based line number, raw line)``
    pairs, at most one per offending line."""
    findings: list[tuple[int, str]] = []
    lines = text.splitlines()
    in_fence = False
    fence_char = ""
    fence_len = 0
    fence_scannable = False
    fence_windows = False

    for lineno, line in enumerate(lines, start=1):
        stripped = line.strip()

        if in_fence:
            match = _FENCE_LINE_RE.match(stripped)
            if (
                match
                and match.group("fence")[0] == fence_char
                and len(match.group("fence")) >= fence_len
            ):
                in_fence = False
                continue
            if fence_scannable and not fence_windows:
                _scan_fenced_line(line, lineno, findings)
            continue

        fence_match = _FENCE_LINE_RE.match(stripped)
        if fence_match:
            in_fence = True
            fence_char = fence_match.group("fence")[0]
            fence_len = len(fence_match.group("fence"))
            info = fence_match.group("info").lower()
            fence_scannable = info not in _EXEMPT_FENCE_INFOS
            fence_windows = info in _WINDOWS_FENCE_INFOS
            continue

        _scan_inline_code(line, lineno, findings)

    return findings


# ---------------------------------------------------------------------------
# iter_markdown — every *.md under root.
# ---------------------------------------------------------------------------


def _iter_markdown_via_git(root: Path) -> list[Path] | None:
    """``git ls-files -z -- '*.md'`` output, or ``None`` when *root* is not
    usable as a git work tree — tells the caller to fall back to a
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
    paths = [root / name.decode("utf-8") for name in names]
    return [
        p
        for p in paths
        if not any(part in _SKIP_DIR_NAMES for part in p.relative_to(root).parts[:-1])
    ]


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
    git work tree, else a plain :meth:`Path.rglob`, both skipping
    ``.git``/``.venv``/``node_modules``/``_archive``."""
    root = Path(root)
    via_git = _iter_markdown_via_git(root)
    if via_git is not None:
        return via_git
    return _iter_markdown_via_rglob(root)


# ---------------------------------------------------------------------------
# lint — the public gate scan.
# ---------------------------------------------------------------------------


def lint(root: Path) -> list[Finding]:
    """Gate findings for every markdown file under *root*. Never raises: an
    unreadable file or a decode failure is skipped, not reported."""
    root = Path(root)
    findings: list[Finding] = []

    for path in iter_markdown(root):
        try:
            rel_posix = path.relative_to(root).as_posix()
        except ValueError:
            rel_posix = path.as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        for lineno, raw_line in find_bare_python(text):
            snippet = raw_line.strip()
            if len(snippet) > _MAX_SNIPPET_CHARS:
                snippet = snippet[:_MAX_SNIPPET_CHARS]
            findings.append(Finding(path=rel_posix, line=lineno, snippet=snippet))

    return findings


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _reconfigure_stdout_utf8() -> None:
    """Reconfigure stdout/stderr to UTF-8 with ``errors="replace"`` at the
    I/O boundary — without this, a non-ASCII line crashes on a Windows
    cp1251 console (project memory: ``cli-nonascii-windows-encoding.md``)."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str]) -> int:
    _reconfigure_stdout_utf8()

    parser = argparse.ArgumentParser(
        description="Gate: no bare 'python' command invocation in shipped "
        "markdown — use 'uv run [--no-project] python' instead."
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

    findings = lint(root)

    if args.json:
        print(json.dumps([asdict(f) for f in findings]))
    else:
        for f in findings:
            print(
                f"{f.path}:{f.line}: BARE_PYTHON — use 'uv run --no-project "
                f"python' (seed script) or 'uv run python' (project env): "
                f"{f.snippet}"
            )
        print(f"{len(findings)} finding(s)")

    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
