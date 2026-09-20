---
description: Run a focused read-only security audit of the diff (deserialization/IPC/injection/secret-leak) — drives the reviewer agent in security-only mode
---

Run the **reviewer** agent (subagent_type: "reviewer", model: opus) in
**security-only mode** — a focused **read-only** security audit. As of Phase 2 the
dedicated `security-review` agent has been folded into `reviewer` → `## Specialization: Security`
(five classes + secrets-audit). The agent only reads and returns a list of findings; fixes
are applied by `developer`/`teamlead`, not by it.

Input: $ARGUMENTS — what to audit (git diff, specific files, or a Task X.Y number).
If $ARGUMENTS is empty — audit the latest changes (`git diff` from the last commit).

Pass the agent:
1. What to audit: diff/files/Task.
2. Mode: "Run ONLY `## Specialization: Security` — this is a dedicated pre-merge
   security gate, not a full review. Skip the other specializations (architecture, UI, …)".
3. Context: "Read `CLAUDE.md` + `.claude/modes/_stack.md` — trust boundaries, the IPC map,
   the serialization rule, secrets conventions".
4. Reminder: five classes — deserialization, IPC/events, shared-memory, injection, secrets;
   secrets — via Bash `uv run --no-project python scripts/secrets_audit/secrets_audit.py --format json`
   (the same script as `/core:quality:secrets-audit`), not a new MCP tool.

After getting the result:
- If there are no findings (security clear) — tell the user (note the fallbacks used,
  the exit status of `secrets_audit.py`, and what's still worth checking manually).
- If there are findings (CHANGES REQUESTED) — show them (confirmed blockers first),
  ask the user: send to `developer`/`teamlead` for fixes?

## When to call

- Before merging a branch that changed code involving deserialization, IPC, user input,
  HTML rendering, or authorization.
- When `/dev:review` (full review) recommended a deeper security pass.
- As part of `/dev:pipeline` before `/dev:ship` for security-sensitive tasks.

## When NOT to call

- No code in the risk zone (pure refactoring, docs, dep-bump) → skip.
- Only a secrets check is needed → `/core:quality:secrets-audit` directly (cheaper).
- A fix needs to be APPLIED → that's `developer`/`teamlead`, the security pass only diagnoses.

What to audit: $ARGUMENTS
