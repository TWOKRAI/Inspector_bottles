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
   - Если всё зелёное — предложи commit message и спроси разрешение на push
   - Если есть ошибки — покажи их и предложи исправить

$ARGUMENTS
