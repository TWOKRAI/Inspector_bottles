#!/usr/bin/env bash
# Stop hook — append a per-stage token/tool-call metric to data/pipeline-metrics.jsonl.
#
# Observability for the gated pipeline (gated-pipeline-system Phase 2, Task 2.2).
# Each pipeline stage (S0–S7) that exports PIPELINE_STAGE gets one append-only
# record so "before/after" pipeline cost can be measured honestly instead of
# guessed. Pairs with the budget hard-stop documented in
# `commands/dev/pipeline.md` → "## Token budget".
#
# ⚠️ OPT-IN — the default seed settings.json does NOT register this hook (it is a
# pipeline instrument, not an always-on guard). To enable, add to
# .claude/settings.json under "hooks":
#   "Stop": [
#     { "hooks": [{ "type": "command",
#                   "command": "${CLAUDE_PLUGIN_ROOT}/hooks/token-budget-meter.sh",
#                   "timeout": 10 }] }
#   ]
# and `export PIPELINE_STAGE=S3` (etc.) around each stage in the pipeline driver.
#
# Record shape (one JSON object per line):
#   {"ts","session_id","stage","tokens_in","tokens_out","tool_calls"}
#
# Inputs:
#   - stdin: the Stop-hook JSON (session_id, transcript_path, cwd, …).
#   - env PIPELINE_STAGE        — stage label (default "unknown").
#   - env PIPELINE_TOKENS_IN / PIPELINE_TOKENS_OUT / PIPELINE_TOOL_CALLS — explicit
#     overrides; when unset, the last assistant turn is tallied from the transcript.
#   - env PIPELINE_STAGE_BUDGET — soft token budget; a breach prints a warning to
#     stderr (a Stop hook cannot block — the hard-stop lives in pipeline.md).
#   - env PIPELINE_METRICS_DIR  — output dir (default <repo>/data).
#
# Quiet: always exits 0, never blocks the Stop event.

set -e

# python-bin.sh lives alongside this hook in _lib/ (resolves $PY cross-platform).
# Guarded source: a missing lib degrades to python3 rather than crashing the Stop
# event — this hook must never block a session end.
PYLIB="$(dirname "$0")/_lib/python-bin.sh"
# shellcheck source=/dev/null
[ -f "$PYLIB" ] && source "$PYLIB"
PY="${PY:-python3}"

INPUT=$(cat)

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
METRICS_DIR="${PIPELINE_METRICS_DIR:-$REPO_ROOT/data}"
METRICS_FILE="$METRICS_DIR/pipeline-metrics.jsonl"
mkdir -p "$METRICS_DIR" 2>/dev/null || true

HOOK_INPUT="$INPUT" "$PY" - "$METRICS_FILE" <<'PYEOF'
import datetime
import json
import os
import sys

metrics_file = sys.argv[1]

try:
    data = json.loads(os.environ.get("HOOK_INPUT", "") or "{}")
except Exception:
    data = {}

stage = os.environ.get("PIPELINE_STAGE", "unknown")
session_id = data.get("session_id", "")
transcript = data.get("transcript_path", "")


def _env_int(name):
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except ValueError:
        return None


tokens_in = _env_int("PIPELINE_TOKENS_IN")
tokens_out = _env_int("PIPELINE_TOKENS_OUT")
tool_calls = _env_int("PIPELINE_TOOL_CALLS")

# When not overridden, tally the LAST assistant turn from the transcript JSONL.
if (tokens_in is None or tokens_out is None or tool_calls is None) and transcript and os.path.exists(
    transcript
):
    last_in = last_out = last_calls = 0
    try:
        with open(transcript, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except Exception:
                    continue
                msg = entry.get("message", entry)
                if not isinstance(msg, dict) or msg.get("role") != "assistant":
                    continue
                usage = msg.get("usage", {}) or {}
                ti = (
                    (usage.get("input_tokens", 0) or 0)
                    + (usage.get("cache_read_input_tokens", 0) or 0)
                    + (usage.get("cache_creation_input_tokens", 0) or 0)
                )
                to = usage.get("output_tokens", 0) or 0
                if ti or to:
                    last_in, last_out = ti, to
                content = msg.get("content", [])
                if isinstance(content, list):
                    calls = sum(
                        1
                        for b in content
                        if isinstance(b, dict) and b.get("type") == "tool_use"
                    )
                    if calls:
                        last_calls = calls
    except Exception:
        pass
    if tokens_in is None:
        tokens_in = last_in
    if tokens_out is None:
        tokens_out = last_out
    if tool_calls is None:
        tool_calls = last_calls

tokens_in = tokens_in or 0
tokens_out = tokens_out or 0
tool_calls = tool_calls or 0

record = {
    "ts": datetime.datetime.now().isoformat(timespec="seconds"),
    "session_id": session_id,
    "stage": stage,
    "tokens_in": tokens_in,
    "tokens_out": tokens_out,
    "tool_calls": tool_calls,
}

try:
    with open(metrics_file, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")
except Exception:
    pass

budget = _env_int("PIPELINE_STAGE_BUDGET")
if budget and (tokens_in + tokens_out) > budget:
    sys.stderr.write(
        "[token-budget-meter] stage '%s' used %d tokens > budget %d — "
        "STOP and escalate to teamlead (see pipeline.md -> Token budget).\n"
        % (stage, tokens_in + tokens_out, budget)
    )
PYEOF

exit 0
