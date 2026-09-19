---
description: Run the Reviewer agent (Opus) — review the implementation after Developer
---

Launch the **reviewer** agent (subagent_type: "reviewer", model: opus, `run_in_background: false` — the result is needed in this same turn).

Pass to it:
1. What to review: git diff, specific files, or a Task X.Y number
2. The task's original spec (acceptance criteria)
3. Context: "Read CLAUDE.md for the architectural rules"

If $ARGUMENTS is empty — review the latest changes (`git diff` from the last commit).

After getting the result:
- If APPROVED — inform the user
- If CHANGES REQUESTED — show the list of fixes, ask the user: send it to Developer for correction?
- If Reviewer raises security questions — run `/dev:security-review`

What to review: $ARGUMENTS
