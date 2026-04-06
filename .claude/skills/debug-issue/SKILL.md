---
name: debug-issue
description: Систематическое дебаггинг сложных проблем
user-invocable: true
disable-model-invocation: false
---

# Дебаггинг

## Методика
1. **Воспроизведи** — создай минимальный пример
2. **Изолируй** — найди минимальный код с проблемой
3. **Гипотеза** — сформулируй предположение о причине
4. **Проверь** — добавь логи/breakpoints для проверки
5. **Исправь** — внеси изменение
6. **Верифицируй** — убедись, что проблема решена

## Инструменты Python
```python
# Быстрый дебаг
import pdb; pdb.set_trace()

# Логирование
import logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)
logger.debug(f"Variable value: {var}")

# Профилирование
import cProfile
cProfile.run('function()')
```

## PyQt специфика
```python
# Печать всех сигналов
from PyQt5.QtCore import pyqtRemoveInputHook
pyqtRemoveInputHook()
import pdb; pdb.set_trace()
```
