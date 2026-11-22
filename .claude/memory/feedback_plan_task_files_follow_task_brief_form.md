---
name: plan-task-files-follow-task-brief-form
description: "/dev:plan: the manager writes tasks/<id>.md by the old TASK.template.md; atlas lint-brief wants the task-brief.md form — name the form in the manager brief"
metadata:
  node_type: memory
  type: feedback
  last-verified: 2026-11-21
  originSessionId: 8c7a7fd6-6716-4dba-87b3-c19fac637ced
  modified: 2026-11-21T07:42:22.343Z
---

Two templates describe a plan task file and they disagree. `.claude/plugins/core/templates/TASK.template.md` (the one
`/dev:plan` names) has H1 `# Task <X.Y>: <text>` and no `FACTS` label. `.claude/plugins/dev/templates/task-brief.md`
(ADR-ATL-004, read by `plans_ledger brief`, the spawn hook and `atlas lint-brief`) requires H1 `# Task <id> — <text>`,
FILES <= 6, REDS <= 10, and a `FACTS` block.

Observed 2026-11-21 (plan `observability-signal-contracts`): the manager wrote 71 task files in the old form; every one
failed `atlas lint-brief` on `H1` and `LABEL_MISSING FACTS`; the lead fixed the H1 with one `sed` and the plan reviewer
later found tasks over the 6-file limit that had to be split.

**Why:** the linter is the gate that runs at spawn time; a plan written in the other form costs a rework round.

**How to apply:** in the manager brief for `/dev:plan` say: task files follow `dev/templates/task-brief.md` (H1 with an
em dash, FILES <= 6, REDS <= 10), and run `atlas lint-brief --no-replay` on every fully written task before reporting.
`FACTS` is NOT written at plan time: it is generated right before the spawn with `python -m scripts.atlas brief
<slug>#<id> --write`, because the facts go stale while `main` moves (lead's interpretation, accepted by the plan
reviewer). `REDS_NO_FILE` on a task whose RED lives in a contract-test file created by an earlier task is expected.
Also keep `plan.md` under 16 384 bytes and each task section under 8 KB (ledger `PLAN_TOO_BIG`, hook `doc-size-guard`).

Related: [[feedback-lint-brief-override-for-non-tdd-agents]], [[feedback-use-atlas-actively]].
