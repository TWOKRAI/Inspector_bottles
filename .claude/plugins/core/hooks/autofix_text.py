"""autofix_text.py (Task 1.2) - PostToolUse logic of autofix-text.sh.

Mirrors the two pre-commit-hooks fixers that run at commit time, so a file the
agent just wrote with Edit/Write already has the bytes the commit would produce:

  1. trailing-whitespace --markdown-linebreak-ext=md
  2. end-of-file-fixer

Both algorithms are VERBATIM copies of pre-commit-hooks v5.0.0 (MIT licence),
files `pre_commit_hooks/trailing_whitespace_fixer.py` (`_process_line`) and
`pre_commit_hooks/end_of_file_fixer.py` (`fix_file`), as installed in
`~/.cache/pre-commit/repo*/py_env-python3/Lib/site-packages/`. They run in
memory on bytes (no decoding); one write happens at the end.

Skipped targets (the hook stays silent, exit 0 always):
  * any tool other than Edit/Write; not a regular file; symbolic link; > 1 MiB;
  * `*.py` - ruff owns Python (`autoformat-python.sh`). Known leftover:
    trailing whitespace inside multi-line non-docstring strings of a `.py`
    file is not touched here; pre-commit notices it at commit time;
  * outside the repository: the nearest ancestor holding `.git` (directory or
    file) must lie inside realpath(CLAUDE_PROJECT_DIR);
  * relative to that repository root: `^robot/` and `^docs/claude/frozen/`
    (the same excludes as `.pre-commit-config.yaml`);
  * binary: a byte outside {7,8,9,10,11,12,13,27} + 0x20-0x7E + 0x80-0xFF in
    the first 1024 bytes (`identify.is_text`). One rule for every extension.
    Known leftover: a text-extension file with a control byte in the first KB
    (for example a `.md` holding a NUL) is skipped here and fixed by pre-commit.

Stdout stays empty: the harness parses a PostToolUse stdout as JSON.
"""

from __future__ import annotations

import io
import json
import os
import sys

MAX_BYTES = 1024 * 1024
SKIP_PREFIXES = ("robot/", "docs/claude/frozen/")
_TEXT_CHARS = frozenset({7, 8, 9, 10, 11, 12, 13, 27} | set(range(0x20, 0x7F)) | set(range(0x80, 0x100)))


def _repo_root(real_path: str, project_real: str) -> str | None:
    """Nearest ancestor with `.git`, accepted only inside the project directory.

    TWIN: the same rule is duplicated in `.claude/plugins/lang-python/hooks/autoformat-python.sh`
    (embedded Python), because a `lang-python` -> `core` dependency is worse than a copy.
    Change both together.
    """
    current = os.path.dirname(real_path)
    while True:
        if os.path.exists(os.path.join(current, ".git")):
            if current == project_real or current.startswith(project_real + os.sep):
                return current
            return None
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent


def _is_text(head: bytes) -> bool:
    return all(byte in _TEXT_CHARS for byte in head)


# --- pre-commit-hooks v5.0.0, trailing_whitespace_fixer._process_line (verbatim) -------------


def _process_line(
    line: bytes,
    is_markdown: bool,
    chars: bytes | None,
) -> bytes:
    if line[-2:] == b"\r\n":
        eol = b"\r\n"
        line = line[:-2]
    elif line[-1:] == b"\n":
        eol = b"\n"
        line = line[:-1]
    else:
        eol = b""
    # preserve trailing two-space for non-blank lines in markdown files
    if is_markdown and (not line.isspace()) and line.endswith(b"  "):
        return line[:-2].rstrip(chars) + b"  " + eol
    return line.rstrip(chars) + eol


# --- pre-commit-hooks v5.0.0, end_of_file_fixer.fix_file (verbatim) -------------------------


def fix_file(file_obj) -> int:  # noqa: ANN001 - IO[bytes], kept as upstream
    # Test for newline at end of file
    # Empty files will throw IOError here
    try:
        file_obj.seek(-1, os.SEEK_END)
    except OSError:
        return 0
    last_character = file_obj.read(1)
    # last_character will be '' for an empty file
    if last_character not in {b"\n", b"\r"} and last_character != b"":
        # Needs this seek for windows, otherwise IOError
        file_obj.seek(0, os.SEEK_END)
        file_obj.write(b"\n")
        return 1

    while last_character in {b"\n", b"\r"}:
        # Deal with the beginning of the file
        if file_obj.tell() == 1:
            # If we've reached the beginning of the file and it is all
            # linebreaks then we can make this file empty
            file_obj.seek(0)
            file_obj.truncate()
            return 1

        # Go back two bytes and read a character
        file_obj.seek(-2, os.SEEK_CUR)
        last_character = file_obj.read(1)

    # Our current position is at the end of the file just before any amount of
    # newlines.  If we find extraneous newlines, then backtrack and trim them.
    position = file_obj.tell()
    remaining = file_obj.read()
    for sequence in (b"\n", b"\r\n", b"\r"):
        if remaining == sequence:
            return 0
        elif remaining.startswith(sequence):
            file_obj.seek(position + len(sequence))
            file_obj.truncate()
            return 1

    return 0


# --- the hook ---------------------------------------------------------------------------------


def fixed_bytes(original: bytes, path: str) -> bytes:
    """Trailing-whitespace pass, then end-of-file pass, both in memory."""
    is_markdown = os.path.splitext(path.lower())[1] == ".md"
    lines = io.BytesIO(original).readlines()  # splits on b"\n" only, like the upstream hook
    processed = b"".join(_process_line(line, is_markdown, None) for line in lines)
    buffer = io.BytesIO(processed)
    # `io.BytesIO(initial)` starts at position 0; fix_file seeks itself.
    fix_file(buffer)
    return buffer.getvalue()


def process(payload: dict, project_dir: str) -> None:
    if payload.get("tool_name") not in ("Edit", "Write"):
        return
    tool_input = payload.get("tool_input")
    path = tool_input.get("file_path") if isinstance(tool_input, dict) else None
    if not isinstance(path, str) or not path or path.lower().endswith(".py"):
        return
    if os.path.islink(path) or not os.path.isfile(path):
        return
    before = os.stat(path)
    if before.st_size > MAX_BYTES:
        return

    project_real = os.path.normcase(os.path.realpath(project_dir))
    real = os.path.normcase(os.path.realpath(path))
    root = _repo_root(real, project_real)
    if root is None:
        return
    rel = os.path.relpath(real, root).replace(os.sep, "/")
    if rel.startswith(SKIP_PREFIXES):
        return

    with open(path, "rb") as handle:
        original = handle.read()
    if not _is_text(original[:1024]):
        return

    updated = fixed_bytes(original, path)
    if updated == original:
        return

    # Recheck right before the single write: a concurrent writer wins, we skip.
    after = os.stat(path)
    if (after.st_mtime_ns, after.st_size) != (before.st_mtime_ns, before.st_size):
        return
    with open(path, "wb") as handle:
        handle.write(updated)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        if isinstance(payload, dict):
            project_dir = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()
            process(payload, project_dir)
    except Exception:  # noqa: BLE001 - a hook must never break the Edit/Write that triggered it
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
