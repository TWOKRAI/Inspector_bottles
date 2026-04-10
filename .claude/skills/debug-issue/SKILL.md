---
name: debug-issue
description: Систематический дебаггинг проблем в многопроцессном фреймворке Inspector_bottles.
user-invocable: true
disable-model-invocation: false
---

# Дебаггинг — Inspector_bottles

## Методика

1. **Локализуй** — определи, в каком процессе проблема (ProcessManager? дочерний? frontend?)
2. **Поищи по смыслу** — `mcp__qex__search_code("описание проблемы")` для контекста, затем `Grep` для точных вхождений
3. **Гипотеза** — сформулируй предположение о причине
4. **Проверь** — добавь логи / запусти тесты для проверки
5. **Исправь** — внеси изменение
6. **Верифицируй** — `/fw-test` или `/validate`

## Типичные проблемы фреймворка

### IPC / сообщения не доходят
- Проверь `targets` vs `channel` (не перепутаны ли?)
- `Grep` по `send_message` в модуле-отправителе
- Проверь регистрацию канала в `RouterManager`
- Справочник: `multiprocess_framework/docs/ROUTING_GLOSSARY.md`

### ModuleNotFoundError при тестах
- Рабочий каталог должен быть `Inspector_prototype/`
- Или запускай через скрипты: `python Inspector_prototype/scripts/run_framework_tests.py`

### Процесс не стартует / зависает
- Проверь `setup()` модуля — нет ли блокирующих вызовов
- Логи: `MULTIPROCESS_LOG_DIR` / `INSPECTOR_LOG_DIR`
- `Grep` по `ObservableMixin` в модуле для диагностики

### PyQt UI не обновляется
- Проверь, что UI обновляется через сигналы/слоты, не из фонового потока
- `Grep` по `setText`, `setPixmap` — должны быть в слотах

## Инструменты
```bash
# Тесты конкретного модуля
cd Inspector_prototype && python -m pytest multiprocess_framework/modules/<module>/tests/ -v

# Полная валидация
python Inspector_prototype/scripts/validate.py

# Логирование
export MULTIPROCESS_LOG_DIR=/tmp/inspector_logs
```
