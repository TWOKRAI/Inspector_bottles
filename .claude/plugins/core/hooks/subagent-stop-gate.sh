#!/usr/bin/env bash
# subagent-stop-gate.sh (Task 2.7) — SubagentStop hook: runs pre_report_gate.py
# in the writing agent's own worktree before letting it report done.
#
# Gated roles only: developer, teamlead, junior, debugger. Any other role
# (reviewer, cto, investigator, ...) allows immediately, gate never run.
#
# Block mechanics are STATE-based (live probe, CC 2.1.270): once an agent has
# been blocked, every later stop arrives with stop_hook_active=true and a block
# on such an event IS honoured; the harness also sets it on its own ordinary
# second stop. So stop_hook_active takes no part in the decision (it is only
# written to the status line) — every stop of a gated role is gated, and the
# loop guard is a per agent_type-agent_id counter in .claude/logs/agents/
# (<type>-<id>.blocks): red -> block, red -> block, red -> allow with
# "gate: red (cap reached, allowed)".
#
# Tree fingerprint (<type>-<id>.gate.json): sha256 over HEAD, status, diff
# against HEAD, untracked file contents and modes, tests and base. An
# unchanged tree reuses the last gate result instead of re-running the gate; a
# non-git agent dir has no fingerprint and is gated every time. A `worktree`
# result is never reused: its inputs (venv, materialized scripts) live outside
# the tree.
#
# The agent's own worktree is not in the payload (`cwd` is the MAIN
# session's directory) — it is the latest `cd <path>` in a Bash tool_use in the
# tail of agent_transcript_path that is absolute, an existing directory inside
# a git work tree (normalised to its toplevel) AND the same repository as
# `cwd` (same --git-common-dir, or a shared root commit); rejected candidates
# are skipped for earlier ones. None found -> the payload `cwd` and the status
# line says dir_fallback. If `cwd` is not a git repo, the first valid
# candidate is taken and the status line says dir_unverified.
#
# The gate script is looked up in trusted places first ($CLAUDE_PLUGIN_ROOT,
# then this hook's own plugin) and in the agent's tree last — otherwise an
# agent could drop a stub of its own and get a green.
#
# Deliberate cost: the gate runs BEFORE the context-ceiling check, because
# the over-ceiling status must say how many tests are failing. The ceiling is
# agent-context-ceiling.sh's own soft level: start + agent_context_budget
# (ini, default 100000) or the per-agent override
# .claude/logs/agents/<agent_id>.budget (same file that hook reads); unknown
# start falls back to 60000; `off` means never over ceiling. An agent over
# it therefore still pays for one gate run — the fingerprint makes repeat
# stops free — and is then allowed with
# "gate: red (over ceiling, N tests failing)".
#
# Report file .claude/logs/agents/<agent_type>-<agent_id>.md: first line is
# the status `gate: <state> | dir=<dir> | stop_hook_active=<bool>[ | flags]`,
# then last_assistant_message (a later non-empty message never regresses to
# empty/shorter). It is written in a finally block, whatever the decision.
#
# Config: .claude/modes/_stack.md ini block, keys `pre_report_gate`
# (default off), `pre_report_gate_tests` (default "tests" — the generated
# skeleton's test dir) and `pre_report_gate_base` (default empty = the gate's own
# merge-base detection). off -> allow without running anything.
#
# Report-status pre-check (Task 4.1, ini key `report_status`, default on,
# independent of `pre_report_gate`): before the gate runs at all, the SAME
# gated roles are held to one cheap rule on `last_assistant_message` — a
# missing/empty message fails OPEN (the field is optional; skip the check
# entirely). Otherwise the first non-empty line must match
# `STATUS: DONE|DONE_WITH_CONCERNS|NEEDS_CONTEXT|BLOCKED` (case-sensitive);
# the three non-DONE statuses also need >= 2 further non-empty lines (a bare
# status is not a report). A violation blocks the stop with a fixed reason,
# reusing the SAME per-agent `.blocks` cap-2 counter `pre_report_gate` already
# uses below — never a second counter, so the two mechanisms share one "stop
# blocking after N attempts" budget. A well-formed `NEEDS_CONTEXT`/`BLOCKED`
# skips `pre_report_gate` entirely and allows the stop: an unfinished
# hand-back is never held to a green-tests bar. `DONE`/`DONE_WITH_CONCERNS`
# fall through to `pre_report_gate` exactly as before.
#
# A red result names the base ref that scoped it: ` | base=<ref>` in the
# status line and `dir: <dir> (base=<ref>)` in the block reason.
#
# Gate timeout (env PRE_REPORT_GATE_TIMEOUT seconds, default 285) -> allow +
# "gate: timeout (allowed)"; unparseable gate output
# -> allow + "gate: error (allowed)". Any hook error -> allow, one line in
# .claude/logs/agents/_hook-errors.log. This hook must never block an agent's
# completion by accident.

HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HOOK_DIR/_lib/python-bin.sh"
source "$HOOK_DIR/_lib/stack-ini.sh"

[ -n "${PY:-}" ] || exit 0

GATE_MODE="$(stack_ini_get pre_report_gate off)"
GATE_TESTS="$(stack_ini_get pre_report_gate_tests "tests")"
GATE_BASE="$(stack_ini_get pre_report_gate_base "")"
AGENT_BUDGET="$(stack_ini_get agent_context_budget "")"
REPORT_STATUS_MODE="$(stack_ini_get report_status on)"

PY="$PY" GATE_MODE="$GATE_MODE" GATE_TESTS="$GATE_TESTS" GATE_BASE="$GATE_BASE" \
AGENT_CONTEXT_BUDGET="$AGENT_BUDGET" REPORT_STATUS_MODE="$REPORT_STATUS_MODE" \
HOOK_DIR="$HOOK_DIR" CLAUDE_PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-}" \
"$PY" -c '
import datetime, hashlib, json, os, re, shlex, signal, subprocess, sys, tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.environ.get("HOOK_DIR", ""), "_lib"))

MAX_BLOCKS = 2
GATED_ROLES = {"developer", "teamlead", "junior", "debugger"}
TAIL_BYTES = 4000000
GATE_TIMEOUT_DEFAULT = 285  # gate itself: lint 60 + tests 240; plugin.json hook timeout is 300
GIT_TIMEOUT = 30
REASON_MAX_LINES = 10
HASH_MAX_BYTES = 1024 * 1024
LOGS_EXCLUDE = ":(exclude).claude/logs"

# Task 4.1: report-status pre-check.
STATUS_RE = re.compile(r"^STATUS: (DONE|DONE_WITH_CONCERNS|NEEDS_CONTEXT|BLOCKED)\b")
STATUS_BODY_MIN_LINES = 2
STATUS_REASON = (
    "report-status: start your final message with one line "
    "\"STATUS: DONE | DONE_WITH_CONCERNS | NEEDS_CONTEXT | BLOCKED\" (then the report). "
    "DONE = every acceptance criterion met and verified; "
    "DONE_WITH_CONCERNS = delivered but something is open - say what; "
    "NEEDS_CONTEXT = cannot proceed without an answer - ask it; "
    "BLOCKED = a hard blocker - name it."
)



def _gate_timeout():
    try:
        value = int(os.environ.get("PRE_REPORT_GATE_TIMEOUT", ""))
    except ValueError:
        return GATE_TIMEOUT_DEFAULT
    return value if value > 0 else GATE_TIMEOUT_DEFAULT


GATE_TIMEOUT = _gate_timeout()
_CD_RE = re.compile(r"^\s*cd\s+(\"[^\"]*\"|\x27[^\x27]*\x27|\S+)")
_CTX = {"cwd": None, "label": "?"}


def _atomic_write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix="." + path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, str(path))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _git(directory, *args):
    try:
        proc = subprocess.run(
            ["git", "-C", directory, *args], capture_output=True, timeout=GIT_TIMEOUT
        )
    except (OSError, subprocess.TimeoutExpired):
        return 1, b""
    return proc.returncode, proc.stdout


def _tail_lines(path):
    with open(path, "rb") as f:
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, size - TAIL_BYTES))
        return f.read().splitlines()


def _cds_latest_first(transcript_path):
    for raw in reversed(_tail_lines(transcript_path)):
        try:
            e = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(e, dict) or e.get("type") != "assistant":
            continue
        blocks = (e.get("message") or {}).get("content")
        if not isinstance(blocks, list):
            continue
        for block in reversed(blocks):
            if not isinstance(block, dict):
                continue
            if block.get("type") != "tool_use" or block.get("name") != "Bash":
                continue
            command = (block.get("input") or {}).get("command") or ""
            m = _CD_RE.match(command)
            if m:
                yield m.group(1).strip("\"\x27")


def _toplevel(directory):
    rc, out = _git(directory, "rev-parse", "--show-toplevel")
    top = os.fsdecode(out).strip()
    return top if rc == 0 and top else None


def _repo_identity(directory):
    """(real --git-common-dir or None, set of root commits)."""
    rc, out = _git(directory, "rev-parse", "--path-format=absolute", "--git-common-dir")
    common = os.path.realpath(os.fsdecode(out).strip()) if rc == 0 and out.strip() else None
    rc, out = _git(directory, "rev-list", "--max-parents=0", "HEAD")
    roots = set(out.split()) if rc == 0 else set()
    return common, roots


def _same_repo(a, b):
    return (a[0] is not None and a[0] == b[0]) or bool(a[1] & b[1])


def _find_agent_dir(transcript_path, fallback_cwd):
    """(agent_dir, dir_fallback, dir_unverified).

    The latest absolute, existing `cd` dir inside a git work tree that belongs
    to the same repository as fallback_cwd; if fallback_cwd is not a git repo,
    the latest valid one, unverified.
    """
    cwd_identity = _repo_identity(fallback_cwd) if _toplevel(fallback_cwd) else None
    seen = set()
    try:
        for candidate in _cds_latest_first(transcript_path):
            if candidate in seen:
                continue
            seen.add(candidate)
            if not (os.path.isabs(candidate) and os.path.isdir(candidate)):
                continue
            top = _toplevel(candidate)
            if not top:
                continue
            if cwd_identity is None:
                return top, False, True
            if _same_repo(cwd_identity, _repo_identity(top)):
                return top, False, False
    except OSError:
        pass
    return fallback_cwd, True, False


def _find_gate_script(agent_dir):
    roots = []
    if os.environ.get("CLAUDE_PLUGIN_ROOT"):
        roots.append(os.environ["CLAUDE_PLUGIN_ROOT"])
    if os.environ.get("HOOK_DIR"):
        roots.append(os.path.join(os.environ["HOOK_DIR"], os.pardir))
    roots.append(agent_dir)  # untrusted: the agent controls this tree, so last
    for root in roots:
        candidate = os.path.normpath(os.path.join(root, "scripts", "pre_report_gate.py"))
        if os.path.isfile(candidate):
            return candidate
    return None


def _gate_cmd(py, script, tests_list, base):
    cmd = [py, script, "--json"]
    if tests_list:
        cmd += ["--tests", *tests_list]
    if base:
        cmd += ["--base", base]
    return cmd


def _kill_tree(proc):
    try:
        if hasattr(os, "killpg"):
            os.killpg(proc.pid, signal.SIGKILL)
        else:
            proc.kill()
    except OSError:
        pass
    try:
        proc.communicate(timeout=5)
    except Exception:
        pass


def _run_gate(py, script, agent_dir, tests_list, base):
    """Gate result dict; outcome is result | timeout | error."""
    if not script:
        return {"outcome": "error", "output": ["pre_report_gate.py not found"]}
    try:
        proc = subprocess.Popen(
            _gate_cmd(py, script, tests_list, base),
            cwd=agent_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except OSError as exc:
        return {"outcome": "error", "output": [str(exc)]}
    try:
        out, err = proc.communicate(timeout=GATE_TIMEOUT)
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        return {"outcome": "timeout", "output": []}
    try:
        data = json.loads(out.decode("utf-8", "replace"))
        if not isinstance(data, dict):
            raise ValueError("gate JSON is not an object")
    except ValueError:
        text = (out + err).decode("utf-8", "replace").splitlines()
        return {"outcome": "error", "output": text[-5:]}
    return {
        "outcome": "result",
        "ok": bool(data.get("ok")),
        "code": data.get("code"),
        "path": data.get("path"),
        "output": [str(x) for x in (data.get("output") or [])],
        "base_degraded": bool(data.get("base_degraded")),
        "lint_skipped": bool(data.get("lint_skipped")),
        "base": data.get("base") if isinstance(data.get("base"), str) else None,
    }


def _record_gate(gate_file, fingerprint, agent_dir, result):
    payload = {"fingerprint": fingerprint, "agent_dir": agent_dir, "result": result}
    _atomic_write(gate_file, json.dumps(payload, ensure_ascii=False, indent=1) + "\n")


def _run_gate_unfingerprinted(py, script, agent_dir, tests_list, base, gate_file):
    result = _run_gate(py, script, agent_dir, tests_list, base)
    _record_gate(gate_file, None, agent_dir, result)
    return result


# ---- tree fingerprint (optimisation only). To drop it: call
# ---- _run_gate_unfingerprinted in main() and delete this section.
def _hash_untracked(h, agent_dir):
    rc, out = _git(agent_dir, "ls-files", "-o", "--exclude-standard", "-z", "--", ".", LOGS_EXCLUDE)
    if rc != 0:
        return False
    for rel in sorted(p for p in out.split(b"\0") if p):
        full = os.path.join(os.fsencode(agent_dir), rel)
        h.update(b"U\0" + rel + b"\0")
        try:
            st = os.lstat(full)
            if os.path.islink(full):
                h.update(b"L" + os.fsencode(os.readlink(full)))
            elif st.st_size > HASH_MAX_BYTES:
                h.update(b"M%o" % (st.st_mode & 0o7777))
                h.update(("S%d:%d" % (st.st_size, st.st_mtime_ns)).encode())
            else:
                h.update(b"M%o" % (st.st_mode & 0o7777))
                with open(full, "rb") as f:
                    h.update(hashlib.sha256(f.read()).digest())
        except OSError:
            h.update(b"?")
    return True


def _tree_fingerprint(agent_dir, tests_list, base):
    """sha256 hex of the agent tree state, or None if agent_dir is not a git work tree."""
    rc, status = _git(
        agent_dir, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--", ".", LOGS_EXCLUDE
    )
    if rc != 0:
        return None
    h = hashlib.sha256()
    _, head = _git(agent_dir, "rev-parse", "HEAD")
    _, diff = _git(agent_dir, "diff", "HEAD", "--", ".", LOGS_EXCLUDE)
    for label, part in ((b"H", head.strip()), (b"S", status), (b"D", diff)):
        h.update(label + str(len(part)).encode() + b"\0" + part)
    if not _hash_untracked(h, agent_dir):
        return None
    h.update(json.dumps({"tests": tests_list, "base": base}, sort_keys=True).encode())
    return h.hexdigest()


def _read_json(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _run_gate_fingerprinted(py, script, agent_dir, tests_list, base, gate_file):
    before = _tree_fingerprint(agent_dir, tests_list, base)
    if before is not None:
        cached = _read_json(gate_file) or {}
        result = cached.get("result")
        if (
            cached.get("fingerprint") == before
            and cached.get("agent_dir") == agent_dir
            and isinstance(result, dict)
            and result.get("outcome") == "result"
        ):
            return result
    result = _run_gate(py, script, agent_dir, tests_list, base)
    after = None
    # a worktree finding depends on inputs outside the tree (venv, materialized
    # scripts): fixing them does not change the fingerprint, so never reuse it.
    if before is not None and result.get("outcome") == "result" and result.get("code") != "worktree":
        # taken AFTER the run: files the gate itself leaves in the tree must
        # not force a re-run on the next stop.
        after = _tree_fingerprint(agent_dir, tests_list, base)
    _record_gate(gate_file, after, agent_dir, result)
    return result
# ---- end tree fingerprint


def _extract_fail_n(output):
    text = "\n".join(str(x) for x in (output or []))
    m = re.search(r"(\d+)\s+failed", text)
    return m.group(1) if m else "?"


def _build_reason(result, agent_dir, py, script, tests_list, base):
    head = ["pre_report_gate: red (%s)" % (result.get("code") or "unknown")]
    if result.get("path"):
        head.append("path: %s" % result["path"])
    rerun = " ".join(shlex.quote(x) for x in _gate_cmd(py, script, tests_list, base))
    dir_line = "dir: %s" % agent_dir
    if result.get("base"):
        dir_line += " (base=%s)" % result["base"]
    tail = [dir_line, "re-run: cd %s && %s" % (shlex.quote(agent_dir), rerun)]
    room = REASON_MAX_LINES - len(head) - len(tail)
    body = []
    for item in result.get("output") or []:
        body.extend(str(item).splitlines() or [""])
    body = body[-room:] if room > 0 else []
    return "\n".join(head + body + tail)


def _read_report(path):
    if not path.exists():
        return None, ""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None, ""
    lines = text.split("\n")
    if lines and lines[0].startswith("gate: "):
        return lines[0], "\n".join(lines[1:]).strip("\n")
    return None, text


def _write_report(path, status_line, new_message):
    old_status, old_message = _read_report(path)
    new_message = (new_message or "").strip()
    old_message = (old_message or "").strip()
    if new_message and len(new_message) >= len(old_message):
        message = new_message
    else:
        message = old_message
    status = status_line if status_line is not None else old_status
    parts = [status] if status else []
    parts.append(message)
    _atomic_write(path, "\n".join(parts) + "\n")


def _read_blocks(path):
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except Exception:
        return 0


def _block_or_cap(blocks_file):
    """True -> block this stop (one slot of the shared cap-2 counter spent);
    False -> the cap is already used up, allow instead. Shared with the same
    red-result counting pre_report_gate does below (same file, same rule) --
    Task 4.1 deliberately reuses it instead of adding a second counter."""
    count = _read_blocks(blocks_file)
    if count < MAX_BLOCKS:
        _atomic_write(blocks_file, str(count + 1))
        return True
    return False


def _check_report_status(message):
    """(status, ok) for the final message a writer role sends.

    status is the matched value, or None if the first non-empty line does not
    match `STATUS: ...` at all. ok is False on any format violation: no
    match, or a DONE_WITH_CONCERNS/NEEDS_CONTEXT/BLOCKED status with fewer
    than STATUS_BODY_MIN_LINES further non-empty lines (a bare status is not
    a report). Leading blank lines and leading/trailing whitespace on the
    first non-empty line are stripped before matching; CRLF is normalised
    first. A line of prose before the status line is NOT skipped -- only
    blank lines are -- so a status line is recognised only when it truly is
    the first thing the message says.
    """
    lines = message.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    idx = 0
    while idx < len(lines) and lines[idx].strip() == "":
        idx += 1
    if idx >= len(lines):
        return None, False
    m = STATUS_RE.match(lines[idx].strip())
    if not m:
        return None, False
    status = m.group(1)
    if status != "DONE":
        body = [ln for ln in lines[idx + 1 :] if ln.strip() != ""]
        if len(body) < STATUS_BODY_MIN_LINES:
            return status, False
    return status, True


def _status_line(state, agent_dir, stop_hook_active, dir_flags, result):
    parts = [
        "gate: %s" % state,
        "dir=%s" % agent_dir,
        "stop_hook_active=%s" % ("true" if stop_hook_active else "false"),
    ]
    dir_fallback, dir_unverified = dir_flags
    if dir_fallback:
        parts.append("dir_fallback")
    if dir_unverified:
        parts.append("dir_unverified")
    if result.get("base_degraded"):
        parts.append("base_degraded")
    if result.get("lint_skipped"):
        parts.append("lint_skipped")
    if result.get("base"):
        parts.append("base=%s" % result["base"])
    return " | ".join(parts)


def _decide(d, cwd, logs_dir, prefix, stop_hook_active):
    """(status_line, decision) for a gated role with the gate on."""
    transcript = d.get("agent_transcript_path")
    if not transcript or not os.path.isfile(transcript):
        return None, None
    py = os.environ.get("PY") or sys.executable
    tests_list = (os.environ.get("GATE_TESTS") or "").split()
    base = (os.environ.get("GATE_BASE") or "").strip()
    blocks_file = logs_dir / (prefix + ".blocks")
    gate_file = logs_dir / (prefix + ".gate.json")

    agent_dir, dir_fallback, dir_unverified = _find_agent_dir(transcript, cwd)
    import transcript_usage
    from agent_context_ceiling import DEFAULT_SOFT, START_FALLBACK, parse_limit, read_override

    start, ctx = transcript_usage.read_context(transcript)
    override = read_override(logs_dir / (str(d.get("agent_id")) + ".budget"))
    soft = parse_limit(os.environ.get("AGENT_CONTEXT_BUDGET"), DEFAULT_SOFT)
    if "soft" in override:
        soft = parse_limit(override["soft"], soft)
    over_soft = soft is not None and ctx > (start or START_FALLBACK) + soft
    script = _find_gate_script(agent_dir)
    # Deliberate order: gate first, ceiling second (see header comment) — the
    # over-ceiling status needs the failing-test count.
    result = _run_gate_fingerprinted(py, script, agent_dir, tests_list, base, gate_file)

    decision = None
    outcome = result.get("outcome")
    if outcome == "timeout":
        state = "timeout (allowed)"
    elif outcome != "result":
        state = "error (allowed)"
    elif result.get("ok"):
        state = "green (%s)" % result["code"] if result.get("code") else "green"
    elif over_soft:
        state = "red (over ceiling, %s tests failing)" % _extract_fail_n(result.get("output"))
    else:
        if _block_or_cap(blocks_file):
            state = "red (%s)" % (result.get("code") or "unknown")
            decision = {
                "decision": "block",
                "reason": _build_reason(result, agent_dir, py, script, tests_list, base),
            }
        else:
            state = "red (cap reached, allowed)"
    dir_flags = (dir_fallback, dir_unverified)
    return _status_line(state, agent_dir, stop_hook_active, dir_flags, result), decision


def main():
    d = json.loads(sys.stdin.read())
    agent_type = d.get("agent_type")
    agent_id = d.get("agent_id")
    if not agent_type or not agent_id:
        return

    cwd = d.get("cwd") or "."
    prefix = "%s-%s" % (agent_type, agent_id)
    _CTX["cwd"] = cwd
    _CTX["label"] = prefix
    logs_dir = Path(cwd) / ".claude" / "logs" / "agents"
    gate_mode = (os.environ.get("GATE_MODE") or "off").strip().lower()
    report_status_mode = (os.environ.get("REPORT_STATUS_MODE") or "on").strip().lower()

    status_line = None
    decision = None
    try:
        if agent_type in GATED_ROLES:
            skip_pre_report_gate = False
            if report_status_mode == "on":
                message = d.get("last_assistant_message") or ""
                if message.strip():
                    status, ok = _check_report_status(message)
                    if not ok:
                        blocks_file = logs_dir / (prefix + ".blocks")
                        if _block_or_cap(blocks_file):
                            status_line = "report-status: invalid"
                            decision = {"decision": "block", "reason": STATUS_REASON}
                        else:
                            status_line = "report-status: invalid (cap reached, allowed)"
                    elif status in ("NEEDS_CONTEXT", "BLOCKED"):
                        skip_pre_report_gate = True
                        status_line = "report-status: %s (pre_report_gate skipped)" % status
            if gate_mode == "on" and not skip_pre_report_gate and decision is None:
                status_line, decision = _decide(
                    d, cwd, logs_dir, prefix, bool(d.get("stop_hook_active"))
                )
    finally:
        _write_report(logs_dir / (prefix + ".md"), status_line, d.get("last_assistant_message") or "")

    if decision:
        print(json.dumps(decision, ensure_ascii=False))


def _log_hook_error(exc):
    try:
        if not _CTX["cwd"]:
            return
        log = Path(_CTX["cwd"]) / ".claude" / "logs" / "agents" / "_hook-errors.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
        msg = str(exc).replace("\n", " ")
        with open(log, "a", encoding="utf-8") as f:
            f.write("%s %s %s: %s\n" % (stamp, _CTX["label"], type(exc).__name__, msg))
    except Exception:
        pass


try:
    main()
except Exception as exc:
    _log_hook_error(exc)
sys.exit(0)
'
exit 0
