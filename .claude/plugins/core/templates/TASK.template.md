# Task <X.Y>: <one sentence>

- **Статус:** [PENDING] · **Level:** <…> · **Assignee:** <role> <!-- lint-language: allow -->

TASK: <X.Y> — <one sentence>                 PLAN: <plans/…/phase-N.md>
ROLE: <developer | teamlead | tester | junior | debugger>
  (a separate tester RED run only for a new module or an unclear contract; a review fix, a change
   to an existing module or wiring is one developer with REDS below — Д47) <!-- lint-language: allow -->
CHAIN: <who produced your input> -> you -> <who consumes your output>

DESIGN (decided by the lead — you type it, you do not derive it):
  <3–6 sentences: which function / class, which call site, what must NOT change,
   which existing helper to reuse. Name symbols and line ranges, not topics.>

FILES (complete list — nothing else; need another file -> stop and ask the lead):
  1. <path> — <what changes there>
  2. <path> — <…>

REDS (predicted red tests, <= 10, `path::test_name`; "n/a — <why>" for docs / config):
  - tests/<…>::test_<…>

ACCEPTANCE: numbers the lead will check by running <command>

TESTS: <exact pytest command for the task radius>

OUT OF SCOPE: <what not to touch, what not to "improve">
TRAPS: <1–3 lines from memory, the plan, or the previous agent's handoff>
HANDOFF IN: <docs/handoffs/<file>.md + SHA when continuing an unfinished run; else "none">
