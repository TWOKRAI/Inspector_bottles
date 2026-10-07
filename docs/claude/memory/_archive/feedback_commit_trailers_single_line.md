---
name: commit-trailers-single-line
description: commit-msg hook требует Why/Layer (и другие trailers) каждый ровно ОДНОЙ физической строкой
metadata:
  type: feedback
---

commit-msg hook (`scripts/validate_commit/validate_commit.py`) парсит trailer-блок как
последний параграф, состоящий целиком из строк `^[A-Z][A-Za-z\-]*: (.+)$`. Перенос
длинного `Why:` на вторую строку — рвёт блок, хук отвечает «Missing required trailers:
Layer, Why», даже если оба присутствуют в тексте.

**Why:** дважды получил этот отказ при коммитах документации (C8 docs-sync,
2026-07-12) — писал `Why:` многострочным (перенос по смыслу), не подозревая, что
парсер требует одну физическую строку.

**How to apply:** при коммитах через Bash-heredoc — `Why:`/`Layer:`/`Refs:`/`Risk:`/
`Reversible:`/`Tested:`/`Rejected:`/`Co-Authored-By:` строго одной строкой каждый, без
пустых строк между ними, весь длинный смысл — в одну строку без переноса. Тело
(буллеты с деталями) — отдельным параграфом ВЫШЕ, отделено пустой строкой от
trailer-блока. См. подробный разбор в teamlead-памяти
`.claude/agent-memory/teamlead/feedback_commit_validator_trailers.md` (тот же баг,
описан детальнее).
