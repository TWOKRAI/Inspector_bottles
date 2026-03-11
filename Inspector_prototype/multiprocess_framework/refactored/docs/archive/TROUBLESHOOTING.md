# Устранение неполадок

## 🔍 Диагностика ошибок

### Шаг 1: Запустить тесты с подробным выводом

```bash
# С максимально подробным выводом
pytest src/multiprocess_framework/refactored/modules/worker_module/tests -v --tb=long

# Или конкретный тест
pytest src/multiprocess_framework/refactored/modules/worker_module/tests/test_worker_manager.py::TestWorkerManager::test_create_manager -v --tb=long
```

### Шаг 2: Проверить импорты

```bash
python -c "from multiprocess_framework.refactored.modules.worker_module import WorkerManager; print('Импорт OK')"
```

### Шаг 3: Проверить структуру модуля

```bash
python src/multiprocess_framework/refactored/check_module.py worker_module --all
```

## 🐛 Частые проблемы и решения

### Проблема 1: AttributeError с is_enabled

**Симптомы:**
```
AttributeError: 'WorkerRegistry' object has no attribute 'is_enabled'
```

**Причина:**
Где-то осталось использование `_registry` вместо `_worker_registry`.

**Решение:**
Проверить все использования `_registry` в WorkerModule:
```bash
grep -r "_registry" src/multiprocess_framework/refactored/modules/worker_module/
```

### Проблема 2: NameError с _log_method

**Симптомы:**
```
NameError: name '_log_method' is not defined
```

**Причина:**
Проблема с замыканием в методах логирования (исправлено).

**Решение:**
Убедиться, что используется последняя версия `logging_methods.py`.

### Проблема 3: Ошибки импорта

**Симптомы:**
```
ModuleNotFoundError: No module named 'multiprocess_framework'
```

**Причина:**
Проблемы с путями или PYTHONPATH.

**Решение:**
Запускать из корня проекта или установить PYTHONPATH.

## 📝 Как сообщить об ошибке

1. Скопируйте полный текст ошибки
2. Укажите команду запуска
3. Укажите какой тест падает
4. Приложите стек трейс

---

**Пожалуйста, пришлите точный текст ошибки для диагностики!**

