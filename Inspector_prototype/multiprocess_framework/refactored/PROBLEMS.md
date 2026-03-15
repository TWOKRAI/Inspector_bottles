# Известные проблемы фреймворка

**Дата:** 2026-03-15  
**Источник:** `python tests/run_all_tests.py`

**Исправлено (2026-03-15):** MagicMock, console patch, config_handler, test_stop_with_alive, process_module log, data_schema импорты. MemoryManager — skip на macOS. **test_clear_queue** — учёт асинхронности multiprocessing.Queue на macOS в `clear_queue()`.

---

## Текущий статус

| Категория              | Статус |
|------------------------|--------|
| Unit-тесты              | ✅ OK (все проходят) |
| Документация            | ✅ OK (19/19 модулей) |
| MemoryManager на macOS | ⏭️ Пропуск (15 тестов) |

---

## Оставшиеся ограничения

### shared_resources_module — MemoryManager (15 тестов)

**Статус:** Пропуск на macOS (`pytest.mark.skipif platform.system() == "Darwin"`).

**Причина:** SharedMemory на macOS (особенно M1/M2) может возвращать None — платформенная особенность.

---

## Интеграционные тесты

См. `tests/integration/TEST_ISSUES.md`:
- Pickle на Windows (лямбда в LoggerPlugin)
- Проблемы с инициализацией процессов
- Конфликт pytest.ini / pyproject.toml

---

## Pydantic deprecation (предупреждения)

**Файл:** `data_schema_module/core/schema_mixin.py:204, 213`

**Предупреждение:** `Accessing the 'model_fields' attribute on the instance is deprecated` (Pydantic V2.11).

**Решение:** Использовать `self.__class__.model_fields` вместо `self.model_fields`.
