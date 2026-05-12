---
description: Финальная проверка перед merge/push — тесты + линтер + ревью изменений
disable-model-invocation: true
---

Выполни финальную проверку перед отправкой кода:

1. **Валидация структуры:**
   ```bash
   python scripts/validate.py
   ```

2. **Тесты фреймворка:**
   ```bash
   python scripts/run_framework_tests.py
   ```

3. **Линтер:**
   ```bash
   ruff check 
   ```

4. **Итог изменений:**
   ```bash
   git diff --stat
   git log --oneline -5
   ```

5. **Проверка Refs-трассировки (plan-driven workflow):**
   - Определи текущую ветку: `git branch --show-current`
   - Извлеки slug из имени ветки (всё после `feat/`, `fix/`, `refactor/`, `docs/` и т.д.)
   - Проверь существование файла плана: `plans/<slug>.md` или `plans/<slug>/plan.md`
   - Если план найден:
     - Убедись что коммиты на ветке содержат `Refs:` trailer: `git log main..HEAD --grep="Refs:" --oneline`
     - Если есть коммиты без `Refs:` — предупреди пользователя
     - Прочитай план и проверь: если все Task = [DONE] → предложи закрыть план (Status: DONE)
   - Если план не найден (legacy ветка, hotfix) — пропусти, не блокируй

6. **Результат:**
   - Если всё зелёное — предложи commit message в правильном формате
     (см. ниже) и спроси разрешение на push
   - Если есть ошибки — покажи их и предложи исправить

## Закрытие плана (если все задачи выполнены)

Если план найден и все Task = [DONE]:
```bash
# Обновить статус в плане: DRAFT/IN_PROGRESS → DONE
git add plans/<slug>*
git commit -m "docs(plans): закрыть <slug>

Why: все задачи плана выполнены
Layer: docs"
```

## Формат commit-сообщения

ОБЯЗАТЕЛЬНО соблюдать формат — иначе `commit-msg` hook отклонит коммит.
Полный гайд: [`docs/claude/COMMIT_GUIDE.md`](../../docs/claude/COMMIT_GUIDE.md).

```
<type>(<scope>): краткое описание (≤72 симв)

- что сделано (буллетами, файлы/классы/числа тестов)

Why: одна-две строки про мотивацию
Layer: framework | services | plugins | prototype | docs | scripts | tests | infra | mixed
Refs: plans/<slug>.md  (ОБЯЗАТЕЛЬНО если есть план для текущей ветки)
Risk: low|medium|high — короткое почему  (опц.)
Reversible: yes | migration-needed | no  (опц.)
Tested: scope/N passed, e.g. auth/120
Rejected: альтернатива X — отвергнута, потому что Y  (опц.)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

**Обязательны:** `Why:` и `Layer:`. Перед коммитом можно прогнать валидацию:

```bash
echo "<полное сообщение>" | python3 scripts/validate_commit/validate_commit.py -
```

$ARGUMENTS
