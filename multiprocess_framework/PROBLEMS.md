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

Каталог `multiprocess_framework/tests/integration/` **удалён** (D2.2, 2026-08-10): все семь его
тестовых файлов падали на сборке с `ImportError: cannot import name 'ProcessManagerCore'` —
символа нет в истории репозитория вовсе, то есть они не гонялись никогда. Вместе с ними ушли
подпорки, которые никто больше не звал: `template_app/`, `run_integration_tests.py` и восемь
руководств, описывавших несуществующий API (`TEST_ISSUES.md` в их числе).

Что из прежних записей остаётся верным:

- Разные точки входа pytest: unit-тесты модулей — `modules/pytest.ini` (через
  `scripts/run_framework_tests.py`); корневой гейт — `testpaths` в `pyproject.toml`.
- Интеграция «всё вместе» (SystemLauncher + IPC + graceful shutdown) сегодня живёт в
  `modules/process_manager_module/tests/` и в `multiprocess_prototype/backend/tests/`.
- Утверждение про pickle-лямбду в `LoggerPlugin` пришло из удалённого `TEST_ISSUES.md` и
  ничем не подтверждено на текущем коде — воспроизводить заново, если всплывёт.
