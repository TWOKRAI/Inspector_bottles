---
description: Финальная проверка перед merge/push — тесты + линтер + ревью изменений
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

5. **Результат:**
   - Если всё зелёное — предложи commit message в правильном формате
     (см. ниже) и спроси разрешение на push
   - Если есть ошибки — покажи их и предложи исправить

## Формат commit-сообщения

ОБЯЗАТЕЛЬНО соблюдать формат — иначе `commit-msg` hook отклонит коммит.
Полный гайд: [`docs/claude/COMMIT_GUIDE.md`](../../docs/claude/COMMIT_GUIDE.md).

```
<type>(<scope>): краткое описание (≤72 симв)

- что сделано (буллетами, файлы/классы/числа тестов)

Why: одна-две строки про мотивацию
Layer: framework | services | plugins | prototype | docs | scripts | tests | infra | mixed
Refs: docs/plans/.../*.md, ADR-XXX, PR#NN  (если есть связь)
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
