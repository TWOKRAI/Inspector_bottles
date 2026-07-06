---
description: Create a new agent from the template — the "HR function"
---

Создай нового агента для команды разработки.

1. Спроси у пользователя (или возьми из $ARGUMENTS):
   - **Имя** агента (английское, через дефис: `api-specialist`)
   - **Роль** — что будет делать (1-2 предложения)
   - **Модель:** opus (архитектура/ревью), sonnet (реализация/тесты), haiku (документация/простое)
   - **Инструменты:** read-only (`Read, Glob, Grep`) или full (`Read, Write, Edit, Glob, Grep, Bash`)
   - **Ограничения** — чего НЕ должен делать

2. Прочитай шаблон: `.claude/plugins/core/agents/_template.md`

3. Создай файл `.claude/plugins/core/agents/<имя>.md` на основе шаблона, заполнив все поля
   (рядом с seed-агентами; чтобы пережить `upgrade` — добавь его в canonical seed `plugins/<id>/` напрямую)

4. Опционально создай команду `.claude/plugins/core/commands/<имя>.md` для быстрого вызова `/core:имя`

5. Материализуй агента: скажи пользователю запустить `claude-kit-claude plugin sync .` (или `plugin upgrade . --apply`) — иначе новый агент из `.claude/plugins/core/agents/` не попадёт в загружаемое Claude Code зеркало и не активируется.

6. Покажи пользователю созданного агента и как его вызывать

Данные нового агента: $ARGUMENTS
