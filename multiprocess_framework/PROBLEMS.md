# Известные проблемы фреймворка

**Обновлено:** 2026-05-02 — Tier-1 IMPROVEMENT_PLAN: оба доимиграционных failing-теста починены, документация синхронизирована под 21 модуль.

**Прогон unit-тестов:**

```bash
python scripts/run_framework_tests.py
```

Текущий результат: **2 465 passed / 29 skipped / 0 failed**.

---

## Текущий статус

| Категория              | Статус |
|------------------------|--------|
| Каноничные импорты      | ✅ OK (688 правок применены, 460 битых top-level импортов мигрированы) |
| Корневой фасад `multiprocess_framework` | ✅ OK (state_store/chain/sql/frontend добавлены 2026-05-02) |
| Unit-тесты              | ✅ 2 465 passed / 0 failed |
| Документация            | ✅ синхронизирована под 21 модуль (Tier-1, 2026-05-02) |
| MemoryManager на macOS | ⏭️ Пропуск 15 тестов (платформенная особенность) |
| Pydantic v2 deprecation | ✅ Исправлено (`type(self).model_fields` вместо `self.model_fields`) |

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
