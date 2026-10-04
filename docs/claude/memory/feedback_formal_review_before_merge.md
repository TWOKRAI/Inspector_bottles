---
name: formal-review-before-merge
description: "Merge в main блокируется классификатором, пока в транскрипте нет ОФОРМЛЕННОГО ревью — гонять /code-review (finders → verify → ReportFindings), а не неформальные проверки"
metadata:
  node_type: memory
  type: feedback
  originSessionId: 768c4056-8d38-4ee3-a3f1-d58bf502abff
---

Правило перенесено в `.claude/commands/dev/ship.md` (шаг 4) (2026-10-04).

**Why:** классификатор ищет явные артефакты ревью; фраза «Fable APPROVE» в merge-сообщении без них трактуется как обход.
