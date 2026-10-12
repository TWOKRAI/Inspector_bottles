---
name: grep-i-misses-cyrillic-case
description: "grep -i in Git Bash on Windows does not fold Cyrillic case: `grep -i 'токен'` misses «Токены» and reports 0 — a false 'line is missing' finding; use rg -i or grep -F with the exact case (grep -i не сопоставляет регистр кириллицы, ложное «строки нет»)"
role: reviewer
mechanism: [windows-env, dev-tooling]
metadata:
  type: feedback
---

Rule: an absence claim over Russian text ("the file has no line X") is checked with `rg -i` or with
`grep -F` and the exact capitalisation, never with `grep -i` in Git Bash.

Evidence (2026-10-12, review of Task 1.1 lifecycle-owner-scope): the reviewer reported "1.1.result.md
has no tokens line" from `grep -n -i -E "токен|token"` → 0 hits. The line existed:
`git show b7736d6a8:…/1.1.result.md` → `13:- Токены задачи: около 185k`. Reproduction on a one-line
file «Токены»: `grep -c -i 'токен'` → 0, `rg -c -i 'токен'` → 1, `grep -c -F 'Токен'` → 1.

Why: the Git Bash grep runs without a UTF-8 locale that folds case for multibyte letters, so `-i`
folds only ASCII. The miss is silent: exit 1 and count 0 read the same as a real absence.

How to apply: for a "missing" finding, show the command that would have found the line (rg -i) and
its output; when a zero count on Cyrillic text decides a verdict, cross-check it with a second tool.
