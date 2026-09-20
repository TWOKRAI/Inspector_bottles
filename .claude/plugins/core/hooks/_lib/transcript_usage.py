"""Context-size helpers for a Claude Code transcript (JSONL).

One shared implementation of "how many context tokens did this turn use",
so hooks that need it (token-budget-meter.sh today; the ceiling hooks later)
call the same code instead of each inlining their own copy of the sum.

Stdlib only — never imports any part of the claude_kit_* package. Callers
are shell hooks that must never block a Stop/PreToolUse event: every
function here either returns a safe default on malformed input, or lets
OSError propagate untouched so the caller's own try/except (or "fail open"
default) decides what to do about a missing/unreadable file.

Contract per function (pre/post):

usage_context(usage) -> int
    Pre: `usage` is anything (typically the "usage" dict off an assistant
    message, but may be malformed or not a dict at all).
    Post: sum of int(usage.get(k) or 0) over ("input_tokens",
    "cache_read_input_tokens", "cache_creation_input_tokens").
    `usage` not a dict -> 0. A field that is not int-coercible (raises
    TypeError/ValueError) counts as 0 for that field only, the rest of the
    sum is unaffected. output_tokens is not part of context and is ignored.
    Never raises.

line_context(raw) -> int | None
    Pre: `raw` is one JSONL line, as bytes or str.
    Post: None unless `raw` parses as a JSON object with "type" ==
    "assistant" and a truthy dict "message"["usage"] -- in which case
    returns usage_context(that usage). Malformed JSON (ValueError,
    RecursionError) -> None. Never raises.

read_context(path) -> tuple[int | None, int]
    Pre: `path` is a transcript file path.
    Post: opens `path` once in binary mode, reads at most HEAD_BYTES from
    the start and at most TAIL_BYTES from the end (module globals, read at
    call time so tests can monkeypatch them). `start` is the first truthy
    line_context() found scanning the head forward, else None. `last` is
    the first truthy line_context() found scanning the tail backward
    (skipping trailing lines with no usage, e.g. a final assistant turn
    that made no model call), else 0. OSError from `open`/`read`/`seek`
    propagates to the caller -- this function does not fail open.
    Limit: a single line longer than TAIL_BYTES written after the last
    usage line (e.g. a large base64 image) leaves no whole usage line in
    the tail, so `last` is 0 -- accepted (review 2.6 R9, won't fix).

subagent_transcript(transcript_path, session_id, agent_id) -> str
    Pre: `transcript_path` is the main session transcript's path.
    Post: pure path formula for a subagent's own transcript file, sibling
    to the main transcript's directory:
    <dirname(transcript_path)>/<session_id>/subagents/agent-<agent_id>.jsonl.
    Never touches the filesystem, never raises.
"""

from __future__ import annotations

import json
import os

HEAD_BYTES = 2_000_000
TAIL_BYTES = 4_000_000

_CTX_FIELDS = ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")


def usage_context(usage: object) -> int:
    if not isinstance(usage, dict):
        return 0
    total = 0
    for key in _CTX_FIELDS:
        try:
            total += int(usage.get(key) or 0)
        except (TypeError, ValueError):
            pass
    return total


def line_context(raw: bytes | str) -> int | None:
    try:
        entry = json.loads(raw)
    except (ValueError, RecursionError):
        return None
    if not isinstance(entry, dict) or entry.get("type") != "assistant":
        return None
    message = entry.get("message")
    if not isinstance(message, dict):
        return None
    usage = message.get("usage")
    if not usage:
        return None
    return usage_context(usage)


def read_context(path) -> tuple[int | None, int]:
    with open(path, "rb") as f:
        head = f.read(HEAD_BYTES)
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(max(0, size - TAIL_BYTES))
        tail = f.read()

    start = None
    for line in head.splitlines():
        ctx = line_context(line)
        if ctx:
            start = ctx
            break

    last = 0
    for line in reversed(tail.splitlines()):
        ctx = line_context(line)
        if ctx:
            last = ctx
            break

    return start, last


def subagent_transcript(transcript_path: str, session_id: str, agent_id: str) -> str:
    return os.path.join(
        os.path.dirname(transcript_path),
        session_id,
        "subagents",
        f"agent-{agent_id}.jsonl",
    )
