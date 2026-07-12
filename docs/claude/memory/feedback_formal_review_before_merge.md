---
name: formal-review-before-merge
description: "Merge в main блокируется классификатором, пока в транскрипте нет ОФОРМЛЕННОГО ревью — гонять /code-review (finders → verify → ReportFindings), а не неформальные проверки"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 768c4056-8d38-4ee3-a3f1-d58bf502abff
---

Правило владельца «код-задачи через Fable-ревью до merge» enforce'ится авто-классификатором: `git merge` в main отклоняется (и даже соседние git-команды), если ревью не видно в транскрипте как процесс. Неформального чтения диффа + прогона тестов недостаточно.

**Why:** классификатор ищет явные артефакты ревью; фраза «Fable APPROVE» в merge-сообщении без них трактуется как обход.

**How to apply:** перед merge ветки агента запускать формальное ревью: `/code-review` (finder-агенты по углам → verify-агенты CONFIRMED/PLAUSIBLE/REFUTED → `ReportFindings`), находки возвращать исполнителю итерацией через SendMessage, повторное APPROVE фиксировать явно. Побочная ценность реальна: на AU-1/AU-2 такой цикл поймал потерю `restart_policy` в живых рецептах и mode-less-inspector регрессию до merge. См. [[worktree-stale-base]] — базу ветки агента тоже проверять.
