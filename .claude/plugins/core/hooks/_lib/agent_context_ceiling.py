"""Decide the PreToolUse response for a subagent context-budget ceiling.

Contract:
  - Soft budget: once the subagent's context (relative to its own transcript
    start) crosses ``soft`` tokens, return a checkpoint (``additionalContext``)
    asking the agent to decide (Д48): commit what works, then finish a small
    clear remainder or hand off a large one. The warning re-fires every ``WARN_STEP``
    (50k) tokens past the soft threshold, at most once per step, so a
    long-running agent keeps getting reminded rather than being nagged on
    every single tool call. Levels are strict: the first warning fires at
    ctx > start + soft, and each repeat at ctx > the last warned level +
    WARN_STEP. A context drop (e.g. compaction) stays silent until ctx
    passes the last warned level again. An unwritable logs dir means no
    soft warning at all (fail-open); two parallel calls in the same turn
    may both warn once (harmless duplicate).
  - Hard budget: OFF by default (``hard is None``). When set (via env or a
    per-agent override file), crossing ``start + hard`` denies the tool call
    unless it is on the narrow allow-list: Bash where every segment (split at
    ``;`` ``&`` ``|`` newline) is ``cd <dir>`` or ``[VAR=val ...] git
    [--no-pager|-C d|-c k=v ...] add|commit|status|diff|log|show``, with no
    ``$(...)``/backticks except a quoted-delimiter heredoc commit message and
    no redirection or subshell; writing a handoff doc under
    ``docs/handoffs/``; or reporting via ``SubagentHandback`` or
    ``SendMessage``. This allow-list is not a security boundary (git config,
    env vars and hooks can still run arbitrary programs) — it only stops a
    runaway agent from continuing the task.
  - Per-agent override: a ``key=value`` file at
    ``<logs_dir>/<agent_id>.budget`` (e.g. ``soft=150000 hard=off``) takes
    precedence over the environment-provided defaults. Accepted forms: spaces
    around ``=``, upper-case keys, comma/semicolon-separated pairs, and a
    trailing ``# comment``; later duplicate keys win.
  - stdlib only. Never imports the claude_kit_* package. The hook must never
    break a tool call: every error path returns ``None`` (no hook output) or
    ``main()`` exits 0.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import sys
from pathlib import Path

import transcript_usage

START_FALLBACK = 60_000
WARN_STEP = 50_000
DEFAULT_SOFT = 100_000

_OVERRIDE_PAIR = re.compile(r"(\w+)\s*=\s*([^\s,;#]+)")
_GIT_VERBS = frozenset({"add", "commit", "status", "diff", "log", "show"})
_ENV_ASSIGN = re.compile(r"[A-Za-z_]\w*=")
_SEPARATOR_CHARS = ";&|\n"
_HEREDOC_HEAD = re.compile(r"\$\(\s*cat\s+<<(-?)\s*(['\"])(\w+)\2[ \t]*\n")
_CLOSE_PAREN = re.compile(r"\s*\)")


def parse_limit(raw, default):
    """Parse an env/override limit string into an int, ``None`` (off), or ``default``."""
    if raw is None or not str(raw).strip():
        return default
    v = str(raw).strip().lower()
    if v in ("off", "0", "none"):
        return None
    try:
        n = int(v.replace("_", ""))
    except ValueError:
        return default
    return n if n > 0 else default


def read_override(path) -> dict[str, str]:
    """Read a ``key=value`` override file. Missing/unreadable -> {}."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, ValueError):
        return {}
    return {key.lower(): value for key, value in _OVERRIDE_PAIR.findall(text)}


def _strip_heredoc_messages(command):
    """Replace each `$(cat <<'EOF' ... EOF\n)` with a plain word; ``None`` if one is unterminated."""
    out, pos = [], 0
    while (head := _HEREDOC_HEAD.search(command, pos)) is not None:
        indent = r"\t*" if head[1] else ""
        end = re.compile(rf"^{indent}{re.escape(head[3])}$", re.M).search(
            command, head.end()
        )
        close = _CLOSE_PAREN.match(command, end.end()) if end else None
        if close is None:
            return None
        out += [command[pos : head.start()], "MSG"]
        pos = close.end()
    out.append(command[pos:])
    return "".join(out)


def _segment_allowed(words):
    """`cd [dir]` or `[VAR=val ...] git [--no-pager | -C d | -c k=v ...] <allowed verb> ...`."""
    if words[0] == "cd":
        return len(words) <= 2
    i = 0
    while i < len(words) and _ENV_ASSIGN.match(words[i]):
        i += 1
    if i >= len(words) or words[i] != "git":
        return False
    i += 1
    while i < len(words) and words[i] in ("--no-pager", "-C", "-c"):
        i += 1 if words[i] == "--no-pager" else 2
    return i < len(words) and words[i] in _GIT_VERBS


def _bash_allowed(command):
    """Every segment split at ; & | newline is allowed; no $( ` < > ( ) and no unclosed quote."""
    text = _strip_heredoc_messages(command)
    if text is None or "$(" in text or "`" in text:
        return False
    lexer = shlex.shlex(text, posix=True, punctuation_chars=_SEPARATOR_CHARS + "<>()")
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    lexer.commenters = ""
    try:
        tokens = list(lexer)
    except ValueError:
        return False
    segments, current = [], []
    for token in tokens:
        if token and all(c in _SEPARATOR_CHARS for c in token):
            segments.append(current)
            current = []
        elif token and all(c in _SEPARATOR_CHARS + "<>()" for c in token):
            return False
        else:
            current.append(token)
    segments.append(current)
    segments = [s for s in segments if s]
    return bool(segments) and all(_segment_allowed(s) for s in segments)


def _allowed_over_hard(payload) -> bool:
    """Whether this tool call stays allowed even over the hard budget."""
    tool = payload.get("tool_name")
    ti = payload.get("tool_input") or {}
    if not isinstance(ti, dict):
        ti = {}
    if tool in ("SubagentHandback", "SendMessage"):
        return True
    if tool == "Bash":
        return _bash_allowed(str(ti.get("command", "")))
    if tool == "Write":
        fp = str(ti.get("file_path", ""))
        return (
            fp.endswith(".md")
            and ".." not in fp.replace(os.sep, "/").split("/")
            and os.path.realpath(os.path.dirname(fp)).endswith(
                os.sep + os.path.join("docs", "handoffs")
            )
            and not os.path.islink(fp)
        )
    return False


def _warn(ctx, start, soft, hard_at):
    text = (
        f"Context checkpoint — soft budget passed: {ctx} tokens > {start} start + {soft} soft budget. Decide, do not stop by reflex. "
        "First commit only your own changes that already work (leave other untracked files alone). "
        "If what is left is clear and under ~30 tool calls, continue and finish the task — a finished task needs no handoff. "
        "Judge by the tool calls left, not by the share of the task left. "
        "If more is left, or you are going in circles (re-reading the same files, tests that stay red), write "
        "docs/handoffs/<YYYY-MM-DD>_task-<X.Y>-<role>.md (done / left / next step / files / SHA — enough for a fresh agent "
        "to resume within ~5 calls) and report via SubagentHandback; a fresh agent continues from it. "
        "Either way, no new exploration outside the task."
    )
    if hard_at is not None:
        text += f" Tools other than git add/commit, the handoff file and SubagentHandback are denied above {hard_at} tokens."
    return {
        "hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": text}
    }


def _deny(ctx, limit):
    reason = "\n".join(
        [
            f"Context hard budget: {ctx} > {limit} tokens. Allowed now only:",
            "1) git add / git commit — only your own changes (leave other untracked files alone);",
            "2) Write the handoff docs/handoffs/<YYYY-MM-DD>_task-<X.Y>-<role>.md — done / left / next step / files / SHA;",
            "3) report via SubagentHandback. The rest of the task goes to a fresh agent from your handoff.",
        ]
    )
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def decide(payload, soft_raw, hard_raw, logs_dir):
    """Compute the PreToolUse hook decision, or ``None`` for no hook output."""
    aid = payload.get("agent_id")
    if not aid:
        return None

    logs_dir = Path(logs_dir)
    ov = read_override(logs_dir / f"{aid}.budget")

    soft = parse_limit(soft_raw, DEFAULT_SOFT)
    if "soft" in ov:
        soft = parse_limit(ov["soft"], soft)
    hard = parse_limit(hard_raw, None)
    if "hard" in ov:
        hard = parse_limit(ov["hard"], hard)

    if soft is None and hard is None:
        return None

    try:
        start, ctx = transcript_usage.read_context(
            transcript_usage.subagent_transcript(
                payload["transcript_path"], payload["session_id"], aid
            )
        )
    except (OSError, KeyError, TypeError):
        return None

    if start is None:
        start = START_FALLBACK

    if hard is not None and ctx > start + hard:
        return None if _allowed_over_hard(payload) else _deny(ctx, start + hard)

    if soft is not None and ctx > start + soft:
        base = start + soft
        level = base + (ctx - base - 1) // WARN_STEP * WARN_STEP
        state = logs_dir / f"{aid}.ceiling-warned"
        try:
            logs_dir.mkdir(parents=True, exist_ok=True)
            if state.exists():
                try:
                    prev = int(state.read_text().strip())
                except ValueError:
                    prev = -1
            else:
                prev = -1
        except OSError:
            return None
        if level <= prev:
            return None
        try:
            state.write_text(str(level))
        except OSError:
            return None
        return _warn(ctx, start, soft, None if hard is None else start + hard)

    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            return 0
        logs_dir = (
            Path(
                os.environ.get("CLAUDE_PROJECT_DIR")
                or payload.get("cwd")
                or os.getcwd()
            )
            / ".claude"
            / "logs"
            / "agents"
        )
        decision = decide(
            payload,
            os.environ.get("AGENT_CONTEXT_BUDGET"),
            os.environ.get("AGENT_CONTEXT_HARD_BUDGET"),
            logs_dir,
        )
        if decision is not None:
            print(json.dumps(decision, ensure_ascii=False))
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
