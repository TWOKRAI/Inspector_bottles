---
description: Run the Reviewer agent (Opus) — review the implementation after Developer
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
- Если Reviewer рекомендует более глубокий security-проход — запусти `/dev:security-review` (тот же reviewer в security-only режиме); IPC/UI-специализации reviewer отрабатывает inline, отдельные агенты для них не нужны

Что ревьюить: $ARGUMENTS
