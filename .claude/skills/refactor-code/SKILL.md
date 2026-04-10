---
name: refactor-code
description: Рефакторинг кода с сохранением функциональности в многопроцессном фреймворке Inspector_bottles.
user-invocable: true
disable-model-invocation: false
---

# Рефакторинг кода — Inspector_bottles

## Перед рефакторингом

1. **Семантический обзор** — `mcp__qex__search_code("кто использует <рефакторимый класс/функцию>")` — найди все зависимости по смыслу
2. **Точный поиск** — `Grep` по имени символа — полный список текстовых вхождений
3. **Тесты до** — убедись, что тесты проходят ДО изменений:
   ```bash
   python Inspector_prototype/scripts/run_framework_tests.py
   ```
4. **Проверь ADR** — прочитай `multiprocess_framework/DECISIONS.md` и `modules/<module>/DECISIONS.md` — не нарушит ли рефакторинг архитектурных решений

## В процессе

1. Рефакторь маленькими шагами
2. **Dict at Boundary** — между процессами только dict, Pydantic внутри
3. Зависимости через `interfaces.py`, не прямые импорты
4. После каждого значимого шага — `/fw-test`

## После

1. Полный набор тестов: `/fw-test`
2. Валидация структуры: `/validate`
3. Линтер: `ruff check Inspector_prototype/`
4. Если рефакторинг архитектурный — запись в `DECISIONS.md`
5. Обновить `STATUS.md` затронутого модуля
6. При массовых изменениях — `/qex-reindex` для обновления семантического индекса
