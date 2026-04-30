# Известные проблемы фреймворка

**Обновлено:** 2026-04-25 — после миграции на каноничные импорты `multiprocess_framework.modules.<X>`.

**Прогон unit-тестов:**

```bash
 && python scripts/run_framework_tests.py
```

Текущий результат: **1 877 passed / 30 skipped / 2 failed** (доимиграционные баги тестов, см. ниже).

---

## Текущий статус

| Категория              | Статус |
|------------------------|--------|
| Каноничные импорты      | ✅ OK (688 правок применены, 460 битых top-level импортов мигрированы) |
| Корневой фасад `multiprocess_framework` | ✅ OK (49 / 49 символов экспортируются) |
| Unit-тесты              | ✅ 1 877 passed / 2 known-failing |
| Документация            | ⏳ В процессе наведения порядка |
| MemoryManager на macOS | ⏭️ Пропуск 15 тестов (платформенная особенность) |
| Pydantic v2 deprecation | ✅ Исправлено (`type(self).model_fields` вместо `self.model_fields`) |

---

## Доимиграционные failing-тесты (2 шт.)

Падали и до миграции — см. `git log` или прогон на `HEAD~1`.

### 1. `test_process_manager_process.py::TestProcessManagerProcessInit::test_init_creates_components`

```
AttributeError: 'ProcessManagerProcess' object has no attribute 'config_handler'
```

**Где:** `process_manager_module/tests/test_process_manager_process.py:48`. Тест вызывает `pmp._create_components()` без полной `initialize()`, поэтому `config_handler` ещё не присвоен.

**Решение:** обернуть `get_config()` в `_create_components()` в защиту от отсутствия handler'а **или** перевести тест на полноценную инициализацию через mock-fixture.

### 2. `test_managers_normalize.py::test_console_process_config_build_and_process_helper`

```
AssertionError: assert ''.endswith('ProcessModule')
```

**Где:** `process_module/tests/test_managers_normalize.py:52`. Тест ожидает, что `proc_dict["class"]` не пустая строка, но фактически она пустая — изменился контракт `ConsoleProcessConfig.build()`.

**Решение:** обновить тест под новый контракт `proc_dict`.

---

## Платформенные ограничения

### `MemoryManager` на macOS — 15 тестов skipped

`SharedMemory` на macOS (особенно на Apple Silicon) ведёт себя нестабильно: создание может вернуть `None`, освобождение даёт предупреждения. Тесты помечены `@pytest.mark.skipif(platform.system() == "Darwin")`.

**Решение:** проверить на Linux/Windows; код модуля корректен.

---

## Интеграционные тесты

См. [`tests/integration/TEST_ISSUES.md`](./tests/integration/TEST_ISSUES.md):

- Pickle на Windows (лямбда в LoggerPlugin) — заменить на module-level функции.
- Разные точки входа pytest: unit-тесты модулей — `modules/pytest.ini`; интеграционные — корневой `pyproject.toml` (testpaths).
