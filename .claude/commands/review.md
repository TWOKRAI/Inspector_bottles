---
description: Запустить Reviewer-агента (Opus) — проверить реализацию после Developer
---

Запусти агента **reviewer** (subagent_type: "reviewer", model: opus).

Передай ему:
1. Что ревьюить: git diff, конкретные файлы или номер Task X.Y
2. Оригинальное ТЗ задачи (acceptance criteria)
3. Контекст: «Прочитай CLAUDE.md для архитектурных правил»

Если $ARGUMENTS пуст — ревью последних изменений (`git diff` от последнего коммита).

После получения результата:
- Если APPROVED — сообщи пользователю
- Если CHANGES REQUESTED — покажи список правок, спроси пользователя: отправить Developer'у на исправление?
- Если Reviewer рекомендует доменных агентов (security-reviewer, ipc-routing-checker) — запусти их

Что ревьюить: $ARGUMENTS
