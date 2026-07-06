#!/usr/bin/env bash
# python-bin.sh — resolve the Python interpreter for hook scripts.
#
# Usage (source from a hook):
#   source "$(dirname "$0")/../_lib/python-bin.sh"
#   echo "$INPUT" | "$PY" -c "..."
#
# Why this exists:
# - On Windows, `python3` is often the Microsoft Store stub (silently no-ops or
#   opens the Store). Real interpreter is `python`.
# - On macOS / Linux, `python3` is canonical and `python` may point to Python 2
#   or be absent entirely.
# - Embedding `python3` directly in hooks breaks them on Windows; embedding
#   `python` breaks them on Linux. Single helper avoids both.
#
# Behaviour:
# - Prefers $CLAUDE_PYTHON_BIN if set (escape hatch for non-default installs).
# - Else picks the first working interpreter: python3 → python → py -3 (Windows
#   launcher fallback).
# - Exports PY for the caller. Exits with an error if nothing works.

if [[ -n "${CLAUDE_PYTHON_BIN:-}" ]] && command -v "$CLAUDE_PYTHON_BIN" >/dev/null 2>&1; then
  PY="$CLAUDE_PYTHON_BIN"
elif command -v python3 >/dev/null 2>&1 && python3 -c "import sys" >/dev/null 2>&1; then
  # python3 exists AND can actually run (filters out Microsoft Store stub which
  # exits non-zero on -c, vs. real Python which succeeds).
  PY="python3"
elif command -v python >/dev/null 2>&1; then
  PY="python"
elif command -v py >/dev/null 2>&1; then
  # Windows Python launcher — `py -3` always picks the highest 3.x installed.
  PY="py -3"
else
  echo "python-bin.sh: no working Python interpreter found on PATH" >&2
  echo "  Tried: \$CLAUDE_PYTHON_BIN, python3, python, py -3" >&2
  echo "  Set CLAUDE_PYTHON_BIN=/path/to/python or install Python 3.x" >&2
  exit 1
fi

export PY
