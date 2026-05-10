---
description: Прогон тестов фреймворка (scripts/run_framework_tests.py)
---

Запусти тесты фреймворка из корня проекта:

```bash
python scripts/run_framework_tests.py
```

Покажи результат пользователю. Если тесты падают — покажи список упавших, предложи запустить `/debug` для диагностики.

На Windows: `python` указывает на Python 3.x (не Python 2). Если нужно явно — используй `python3` или `py -3` (Windows-launcher).

$ARGUMENTS
