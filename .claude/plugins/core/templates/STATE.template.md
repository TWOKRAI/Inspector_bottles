# Task State — {{SLUG}} / {{TASK_ID}}

## S0 Research

- research.md: {{RESEARCH_PATH}} | skipped (trivial)
- Chosen approach: {{APPROACH}}

## S1 Plan

- plan: {{PLAN_PATH}}
- Vertical slice verified: yes | no

## S2 Contract

- interface.py: {{INTERFACE_PATH}} | n/a
- Pre/Post complete: yes | no (s2_gate.py check — Phase 2)

## S3 RED

- failing test: {{RED_TEST_PATH}}
- red_gate.py verdict: PASS | BLOCK | pending

## S4 GREEN

- impl: {{IMPL_PATH}}
- RED now green: yes | no

## S5 Final tests

- regression: green | failing
- live-smoke: green | failing | skipped (Phase 2)

## S6 Review

- reviewer verdict: APPROVED | CHANGES | pending

## S7 Integration

- integration.md: {{INTEGRATION_PATH}} | pending
- integration_gate.py verdict: PASS | BLOCK | pending

## Ship

- merged: yes | no
- handoff note: {{HANDOFF_PATH}}
