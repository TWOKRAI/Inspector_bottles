---
description: Run the Tester agent (Sonnet) — write and run tests
---

Запусти агента **tester** (subagent_type: "tester", model: sonnet).

Передай ему:
1. Что тестировать: файлы, функции, модули
2. Acceptance criteria из ТЗ (если есть)
3. Контекст: «Прочитай CLAUDE.md, найди существующие тесты для стиля»

После выполнения:
- Покажи результаты тестов пользователю
- Если тесты падают из-за бага в коде — сообщи, предложи отправить Developer'у

Что тестировать: $ARGUMENTS
