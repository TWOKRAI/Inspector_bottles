---
description: Запуск активного прототипа (multiprocess_prototype/run.py)
---

Запусти активный прототип Inspector_bottles из корня проекта:

```bash
python multiprocess_prototype/run.py
```

Это PySide6 GUI-приложение системы инспекции дефектов. Приложение откроется в отдельном окне.

Если PySide6 не установлен — предложи запустить:
```bash
pip install -e ".[ml]"
```

Если процесс падает — спроси, нужно ли запустить `/debug` для диагностики.

**Кросс-платформа:** команда работает идентично на macOS и Windows (PySide6 6.10 поддерживает обе ОС).

$ARGUMENTS
