---
name: grep-i-misses-cyrillic-case
description: "grep -i in Git Bash on Windows does not fold Cyrillic case: `grep -i 'токен'` misses «Токены» and reports 0 — a false 'line is missing' finding; use rg -i or grep -F with the exact case; never `rg -E` — in ripgrep -E is --encoding, `rg -inE pat` exits 2 'unknown encoding' (grep -i не сопоставляет регистр кириллицы, ложное «строки нет»; rg -E — это кодировка, не regex)"
role: reviewer
mechanism: [windows-env, dev-tooling]
metadata:
  type: feedback
---

Rule: an absence claim over Russian text ("the file has no line X") is checked with `rg -i` or with
`grep -F` and the exact capitalisation, never with `grep -i` in Git Bash. With ripgrep, do not carry
grep's `-E` over: `rg` is regex by default and its `-E` means `--encoding`. An absence check asserts
exit code 1 (no match), not just empty stdout.

Evidence (2026-10-12, review of Task 1.1 lifecycle-owner-scope): the reviewer reported "1.1.result.md
has no tokens line" from `grep -n -i -E "токен|token"` → 0 hits. The line existed:
`git show b7736d6a8:…/1.1.result.md` → `13:- Токены задачи: около 185k`. Reproduction on a one-line
file «Токены»: `grep -c -i 'токен'` → 0, `rg -c -i 'токен'` → 1, `grep -c -F 'Токен'` → 1.

Evidence (2026-10-14, Task 6.2 layer-render): the brief's acceptance line, written to dodge the grep
trap, was `rg -inE "letter|букв|disk|диск" <file>` — it printed "error parsing flag -E: … unknown
encoding" and exited 2 with empty stdout, easy to read as "0 hits". `rg -in "…" <file>` → exit 1, the
real 0; a control run on a file with «буква на диске» matched, so rg folds Cyrillic case.

Why: the Git Bash grep runs without a UTF-8 locale that folds case for multibyte letters, so `-i`
folds only ASCII. Both misses are silent: exit 1/2 with empty output read the same as a real absence.

How to apply: for a "missing" finding, show the command that would have found the line (rg -i) and
its output, and the exit code (1 = no match, 2 = the command itself failed); when a zero count on
Cyrillic text decides a verdict, cross-check it with a second tool.
