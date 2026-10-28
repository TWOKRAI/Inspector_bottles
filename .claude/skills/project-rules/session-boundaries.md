# Session boundaries — offer the reset, don't wait to be asked (was project-rules §8)

A finished task is the cheapest moment to shed context. End your report with exactly one line:

| Situation | The line you end with |
|---|---|
| More of the same task, context still modest | nothing — keep working |
| Task closed, next task same plan/area | `Boundary: task closed. /compact (focus: files + tests + plan path).` |
| Phase closed, feature merged, or next task elsewhere | `Boundary: <what closed>. Better: new chat — branch <b>, plan <path>, SHA <sha>, state "<line>".` |

Parallel lanes under a coordinator (owner, 2026-10-25): the boundary is the merge. Before sending «влит <sha>»
commit a 10–15 line handoff (`docs/handoffs/<date>_<lane>-<task>-merged.md`: next ORDER line, what stays open,
findings) and name it in the «влит» line; the coordinator asks the owner for `/clear` with a one-line restart
prompt. Never clear inside a task — the predictions and the agentId table live in your context; past ~150k use
`/compact` with the focus above.
