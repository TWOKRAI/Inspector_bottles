---
name: lint-brief-override-for-non-tdd-agents
description: "lint-brief режет spawn без DESIGN/FILES/REDS/REPORT: слепому tester, живому прогону и матрице инъекций нужна первая строка BRIEF-OVERRIDE; откат инъекций — cp, не git checkout"
metadata:
  type: feedback
---

Spawn `tester`, `developer` и `junior` без блоков DESIGN, FILES, REDS, REPORT хук `lint-brief` отклоняет (2026-11-09, Task 1.4m: пять отказов подряд, каждый — повторная отправка длинного брифа).

**Why:** слепому tester DESIGN и FILES запрещены правилом слепоты, а живой прогон и матрица инъекций — не TDD, у них нет REDS. Хук этого не знает.
**How to apply:** первой строкой брифа `BRIEF-OVERRIDE: <причина>` (слепой tester; живая проверка без правок кода; механический прогон инъекций) — либо добавь блок REDS (список готовых тестов), если исполнитель пишет код. Откат инъекции — `cp` из резервной копии в scratchpad: `git checkout -- <файл>` в режиме junior отклоняется правами, и прогон встаёт посреди матрицы (I1 из 10). Связано: [[feedback-injection-scripts-on-committed-code]].
