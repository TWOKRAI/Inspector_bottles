#!/usr/bin/env bash
# PostToolUse(Edit|Write) — non-blocking incremental pyright on changed .py.
#
# Default: OFF. Enable per-shell or in settings.local.json env block:
#   export CLAUDE_TYPECHECK_ON_EDIT=1
#
# Why default-off: on cold-start (first run after venv refresh) pyright takes
# 3-10s to build its analysis context. On a 70k LoC project that's painful on
# every Edit. Once warm, incremental runs settle to ~500ms-2s — acceptable.
# Opt-in per-project so small projects stay snappy.
#
# Non-blocking: ALWAYS exits 0. Errors print to stderr; the agent sees them
# in the next turn and can react, but the Edit isn't reverted.
#
# Skip cases:
#   - $CLAUDE_TYPECHECK_ON_EDIT != "1"
#   - tool isn't Edit or Write
#   - file isn't .py
#   - file no longer exists (deleted)
#   - pyright not on PATH and not in .venv

[ "${CLAUDE_TYPECHECK_ON_EDIT:-0}" != "1" ] && exit 0

source "$(dirname "$0")/../_lib/python-bin.sh"

INPUT=$(cat)
read -r TOOL_NAME FILE_PATH < <($PY -c "import sys,json
d=json.load(sys.stdin)
print(d.get('tool_name',''), d.get('tool_input',{}).get('file_path',''))" <<< "$INPUT" 2>/dev/null)

[[ "$TOOL_NAME" != "Edit" && "$TOOL_NAME" != "Write" ]] && exit 0
[[ "$FILE_PATH" != *.py ]] && exit 0
[[ -z "$FILE_PATH" || ! -f "$FILE_PATH" ]] && exit 0

# Resolve pyright — prefer project venv, fall back to PATH
PYRIGHT=""
for c in ".venv/Scripts/pyright.exe" ".venv/bin/pyright" "venv/Scripts/pyright.exe" "venv/bin/pyright"; do
    [[ -f "$c" ]] && PYRIGHT="$c" && break
done
[[ -z "$PYRIGHT" ]] && command -v pyright >/dev/null 2>&1 && PYRIGHT="pyright"
[[ -z "$PYRIGHT" ]] && exit 0

# Run pyright on the single file, JSON output for parseable diagnostics.
# Use 'timeout' if available — pyright can hang briefly on cold cache.
if command -v timeout >/dev/null 2>&1; then
    OUT=$(timeout 30 "$PYRIGHT" --outputjson "$FILE_PATH" 2>/dev/null) || exit 0
else
    OUT=$("$PYRIGHT" --outputjson "$FILE_PATH" 2>/dev/null) || exit 0
fi

# Parse + emit human-readable errors (max 5) to stderr. Always exit 0.
echo "$OUT" | $PY -c "
import sys, json
try:
    d = json.loads(sys.stdin.read())
    errs = [x for x in d.get('generalDiagnostics', []) if x.get('severity') == 'error']
    if not errs:
        sys.exit(0)
    print(f'pyright: {len(errs)} type error(s) (non-blocking, info-only):', file=sys.stderr)
    for e in errs[:5]:
        rng = e.get('range', {}).get('start', {})
        line = rng.get('line', 0) + 1
        msg = e.get('message', '').replace(chr(10), ' ')[:180]
        print(f'  L{line}: {msg}', file=sys.stderr)
    if len(errs) > 5:
        print(f'  ... and {len(errs) - 5} more', file=sys.stderr)
except Exception:
    pass
"

exit 0
