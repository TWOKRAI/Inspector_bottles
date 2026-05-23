---
description: Финальная проверка перед merge/push — тесты + линтер + ревью изменений
disable-model-invocation: true
---

Выполни финальную проверку перед отправкой кода:

1. **Quality gate:**
   ```bash
   make gate        # если Makefile есть (lint + типы + тесты)
   ```
   Fallback (если make недоступен):
   ```bash
   uv run ruff check .
   uv run pyright
   uv run pytest -q
   ```

2. **Итог изменений:**
   ```bash
   git diff --stat
   git log --oneline -5
   ```

3. **Проверка Refs-трассировки (plan-driven workflow):**
   - Определи текущую ветку: `git branch --show-current`
   - Извлеки slug из имени ветки (всё после `feat/`, `fix/`, `refactor/`, `docs/` и т.д.)
   - Найди файл плана (новая конвенция — дата в имени):
     - Single plan: `ls plans/*_<slug>.md` (формат `plans/YYYY-MM-DD_<slug>.md`)
     - Multi-phase: `ls -d plans/*_<slug>` (папка `plans/YYYY-MM-DD_<slug>/`)
   - Если план найден:
     - Убедись что коммиты на ветке содержат `Refs:` trailer: `git log main..HEAD --grep="Refs:" --oneline`
     - Если есть коммиты без `Refs:` — предупреди пользователя
     - Прочитай план (single `plan.md` или metaplan + phase-N.md) и проверь: если все Task = [DONE] → предложи закрыть план (Status: DONE)
   - Если план не найден (legacy ветка, hotfix, старая конвенция без даты) — пропусти, не блокируй

4. **Результат:**
   - Если всё зелёное — предложи commit message в правильном формате
     (см. ниже) и спроси разрешение на push
   - Если есть ошибки — покажи их и предложи исправить

## Закрытие плана (если все задачи выполнены)

Если план найден и все Task = [DONE]:
```bash
# Обновить статус в плане: DRAFT/IN_PROGRESS → DONE
# Single plan:
git add plans/YYYY-MM-DD_<slug>.md
# Or multi-phase:
git add plans/YYYY-MM-DD_<slug>/

git commit -m "docs(plans): закрыть <slug>

Why: все задачи плана выполнены
Layer: docs
Refs: <точный путь к plan.md или single-file>"   # пропусти строку Layer если .claude/commit-layers.txt пуст
```

## Формат commit-сообщения

**Canonical guide:** [`.claude/COMMIT_GUIDE.md`](../../COMMIT_GUIDE.md) — полный формат, типы, trailers, примеры.
**Project settings:** [`.claude/modes/_stack.md`](../../.claude/modes/_stack.md) (validator on/off) + [`.claude/commit-layers.txt`](../../.claude/commit-layers.txt) (если файл пуст → `Layer:` опционален).

Hook `commit-msg` отклоняет неправильный формат (если установлен). Перед коммитом можно прогнать валидацию вручную:

```bash
echo "<полное сообщение>" | python3 scripts/validate_commit/validate_commit.py -
```

$ARGUMENTS
