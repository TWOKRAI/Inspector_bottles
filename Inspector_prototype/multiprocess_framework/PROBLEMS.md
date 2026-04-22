# Известные проблемы фреймворка

**Дата:** 2026-03-15  
**Проверка unit-тестов:** из `Inspector_prototype` — `python scripts/run_framework_tests.py` (см. [README.md — Testing](./README.md#testing)).

**Исправлено (2026-03-15):** MagicMock, console patch, config_handler, test_stop_with_alive, process_module log, data_schema импорты. MemoryManager — skip на macOS. **test_clear_queue** — учёт асинхронности multiprocessing.Queue на macOS в `clear_queue()`.

---

## Текущий статус

| Категория              | Статус |
|------------------------|--------|
| Unit-тесты              | ✅ OK (все проходят) |
| Документация            | ✅ OK (19/19 модулей) |
| MemoryManager на macOS | ⏭️ Пропуск (15 тестов) |

---

## Прототип v3 и слой приложения

**Статус:** ожидаемое трение до выноса общего кода.

- **`multiprocess_prototype_v3`** по-прежнему тянет **`multiprocess_prototype_v2`** для **`app_registers`**, **`managers`**, **`utils`**, **`persistence`** (в v3 этих пакетов нет; данные и общий слой приложения пока общие с v2). Схемы **`backend`**, **`frontend`**, **`registers`** в v3 — свои; реэкспорты фреймворка для удобных импортов — **ADR-115**. Полная автономия v3 — перенос или общий пакет приложения вместо кросс-импорта v2.

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
- Разные точки входа pytest: unit-тесты модулей — `modules/pytest.ini` и `cwd` в `modules/` (или `scripts/run_framework_tests.py`); в корне `Inspector_prototype` — только наборы из `pyproject.toml`

---

## Pydantic deprecation (предупреждения)

**Файл:** `data_schema_module/core/schema_mixin.py:204, 213`

**Предупреждение:** `Accessing the 'model_fields' attribute on the instance is deprecated` (Pydantic V2.11).

**Решение:** Использовать `self.__class__.model_fields` вместо `self.model_fields`.
