#!/usr/bin/env bash
# web-search-routing.sh (Task 3.9) — PreToolUse, matcher "WebSearch|WebFetch": routes
# web research away from a main session running on the top-tier model. Owner rule:
# web search is done by Sonnet or Opus, never by the expensive top-tier model (Fable)
# — a prose reminder gets ignored, so this hook turns it into a mechanical gate; the
# companion `web-researcher` agent (model: sonnet) is where delegated research lands.
#
# Same idiom as core/hooks/agent-context-ceiling.sh: read stdin once, a cheap `case`
# pre-filter before Python starts, interpreter lookup via _lib/python-bin.sh, ini keys
# via _lib/stack-ini.sh, the same JSON PreToolUse deny shape, fail-open on any error.
# Python embedded via heredoc (idiom: core/hooks/lint-brief.sh's dev-plugin twin) --
# this task adds no new _lib module.
#
# Modes (`web_search` ini key, default auto):
#   allow    — always allow, silently, main session and subagent alike; the mode
#              check happens before Python even starts.
#   delegate — a main-session call is always denied; subagent calls are unaffected.
#   auto     — a subagent call (payload carries "agent_id" -- the same discriminator
#              agent-context-ceiling.sh uses; the main thread has none) is allowed
#              unless its "agent_type" is in `web_search_deny_agents` (default: cto).
#              A main-session call is allowed only when the project's model (read
#              from .claude/settings.local.json, else .claude/settings.json, key
#              "model") is sonnet/opus/haiku (case-insensitive); absent, unknown, or
#              e.g. "fable" -> denied.
#
# LIMITATION (out of scope, not a bug): the PreToolUse payload never carries a
# SUBAGENT's own model tier -- only its "agent_type" role name. `web_search_deny_agents`
# therefore denies by ROLE (default: cto, the only role pinned to the top tier today),
# not by measuring the subagent's actual model; a role newly pinned to the top tier
# must be added to that ini list by hand.
#
# Reading settings JSON tolerates comments-free JSON only; a parse error is treated as
# "model unknown" (denied in auto mode) but a missing FILE must never raise.
#
# Any internal error -> allow: exit 0, no output. stdout carries nothing but the JSON
# deny (or nothing, on allow).

HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INPUT="$(cat)"

# Cheap pre-filter: only a WebSearch/WebFetch payload matters -- everything else exits
# before Python starts (perf floor for the ignored-tool path; the hook is also invoked
# directly by tests with arbitrary payloads, bypassing Claude Code's own matcher).
case "$INPUT" in
  *'"WebSearch"'*|*'"WebFetch"'*) ;;
  *) exit 0 ;;
esac

PY="$(source "$HOOK_DIR/_lib/python-bin.sh" 2>/dev/null && printf '%s' "$PY")" || exit 0
source "$HOOK_DIR/_lib/stack-ini.sh"
[ -n "${PY:-}" ] || exit 0

STACK_MD="${CLAUDE_PROJECT_DIR:-.}/.claude/modes/_stack.md"
WEB_SEARCH_MODE="$(stack_ini_get web_search auto "$STACK_MD")"

# allow -> exit 0 silently, before Python starts, main session and subagent alike.
[ "$WEB_SEARCH_MODE" = "allow" ] && exit 0

WEB_SEARCH_DENY_AGENTS="$(stack_ini_get web_search_deny_agents cto "$STACK_MD")"

HOOK_INPUT="$INPUT" \
  WEB_SEARCH_MODE="$WEB_SEARCH_MODE" \
  WEB_SEARCH_DENY_AGENTS="$WEB_SEARCH_DENY_AGENTS" \
  CLAUDE_PROJECT_DIR="${CLAUDE_PROJECT_DIR:-}" \
  "$PY" - <<'PYEOF' 2>/dev/null
import json
import os

DENY_REASON = (
    "web-search-routing: web search is not run on the main session here (owner rule: "
    "search on Sonnet/Opus, the top tier is too expensive). Spawn the 'web-researcher' "
    "agent with your question and the decision it feeds; it returns findings with "
    "source URLs. To allow direct search set 'web_search = allow' in "
    ".claude/modes/_stack.md (the ini block)."
)

_ALLOWED_MAIN_MODELS = ("sonnet", "opus", "haiku")


def _deny(reason):
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                }
            },
            ensure_ascii=True,
        )
    )


def _read_model(project_dir):
    """First .claude/settings.local.json, else .claude/settings.json; key "model".

    A missing file falls through to the next candidate. A parse error (or a non-dict
    document) means "model unknown" for the whole lookup -- never raises.
    """
    for name in ("settings.local.json", "settings.json"):
        path = os.path.join(project_dir, ".claude", name)
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except FileNotFoundError:
            continue
        except (OSError, ValueError):
            return None
        if not isinstance(data, dict):
            return None
        model = data.get("model")
        if isinstance(model, str):
            return model
    return None


def main():
    try:
        payload = json.loads(os.environ.get("HOOK_INPUT") or "")
    except Exception:
        return
    if not isinstance(payload, dict):
        return
    if payload.get("tool_name") not in ("WebSearch", "WebFetch"):
        return

    agent_id = payload.get("agent_id")
    if agent_id:
        deny_agents = {
            a.strip().lower()
            for a in os.environ.get("WEB_SEARCH_DENY_AGENTS", "cto").split(",")
            if a.strip()
        }
        agent_type = str(payload.get("agent_type") or "")
        if agent_type.lower() in deny_agents:
            _deny(
                f"web-search-routing: '{agent_type}' runs on the top model tier - "
                "delegate web research to the 'web-researcher' agent (Sonnet)."
            )
        return

    # Main-session call (no agent_id).
    mode = os.environ.get("WEB_SEARCH_MODE", "auto")
    if mode == "delegate":
        _deny(DENY_REASON)
        return

    project_dir = (
        os.environ.get("CLAUDE_PROJECT_DIR")
        or payload.get("cwd")
        or os.getcwd()
    )
    model = _read_model(project_dir)
    if model is not None and model.strip().lower() in _ALLOWED_MAIN_MODELS:
        return
    _deny(DENY_REASON)


try:
    main()
except Exception:
    pass
PYEOF
exit 0
