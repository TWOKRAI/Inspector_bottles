# Phase 0.5: `base_manager` — финальная уборка

> **Статус:** ✅ Выполнено.  
> **Контекст:** Шаг 4 (код) завершён. Документация (README, DECISIONS.md, OBSERVABLE_ARCHITECTURE.md, ARCHITECTURE.md §6.1) — тоже. Осталась мелкая уборка и валидация.  
> **Исполнитель:** Cursor Composer Agent / ручная работа.

---

## Что уже сделано (НЕ трогать)

| Артефакт | Статус |
|----------|--------|
| Код рефакторинга (шаги 4.0–4.6) | ✅ 17 файлов, 1474 LOC (−39%) |
| `modules/base_manager/DECISIONS.md` (ADR-114…117) | ✅ |
| `modules/base_manager/docs/OBSERVABLE_ARCHITECTURE.md` | ✅ |
| `modules/base_manager/docs/PLUGIN_SYSTEM.md` | ✅ Удалён |
| `modules/base_manager/README.md` (переписан) | ✅ |
| `ARCHITECTURE.md` §6.1 | ✅ |
| `modules/base_manager/STATUS.md` | ✅ Обновлён |
| Главный `DECISIONS.md` — ссылка на `base_manager/DECISIONS.md` | ✅ |
| Тесты: 52 passed + 2 skipped | ✅ |

---

## Что осталось (3 задачи)

### Задача 1. Удалить пустые директории

Три директории очищены от `.py` файлов, но сами папки + `__init__.py` + `__pycache__` остались:

```
modules/base_manager/mixins/methods/     ← удалить целиком
modules/base_manager/mixins/plugins/     ← удалить целиком
modules/base_manager/mixins/decorators/  ← удалить целиком
```

**Шаги:**
1. `git rm -r multiprocess_framework/modules/base_manager/mixins/methods/`
2. `git rm -r multiprocess_framework/modules/base_manager/mixins/plugins/`
3. `git rm -r multiprocess_framework/modules/base_manager/mixins/decorators/`
4. Проверить, что `mixins/__init__.py` **не** импортирует из удалённых подпакетов. Если импортирует — убрать строки.
5. `pytest multiprocess_framework/modules/base_manager/tests -v` — зелёные.
6. Коммит: `chore(base_manager): remove empty mixins/{methods,plugins,decorators} directories`.

---

### Задача 2. Обновить метрики «после» в `00_overview.md`

Файл: `plans/refactoring/00_overview.md`, таблица §4.

Добавить колонку `after` для `base_manager` (строка #1):

| #  | Модуль         | files | loc  | tests | **files_after** | **loc_after** | **tests_after** |
|----|----------------|-------|------|-------|-----------------|---------------|-----------------|
| 1  | `base_manager` | 29    | 2425 | 4     | **17**          | **1474**      | **3** (52 tests) |

**Шаги:**
1. Открыть `plans/refactoring/00_overview.md`.
2. Добавить 3 колонки (`files_after`, `loc_after`, `tests_after`) в заголовок таблицы §4.
3. Заполнить строку `base_manager`. Остальные модули — `—` (ещё не сделаны).
4. Коммит: `docs(refactoring): add base_manager "after" metrics to overview`.

---

### Задача 3. Обновить чекбоксы в `01_base_manager.md`

Шаги 4.1–4.6 в плане отмечены `[ ]`, хотя реально завершены. Отметить все `[x]`.

Также обновить секцию 9 (Definition of Done):
- [x] Все тесты зелёные
- [x] validate.py зелёный
- [x] LOC ≥ 25% (факт −39%)
- [x] Файлы ≥ −10 (факт −12)
- [x] Публичный API без изменений
- [x] README переписан
- [x] Документация обновлена
- [x] ARCHITECTURE.md §6.1 заполнен
- [x] DECISIONS.md создан
- [x] Главный DECISIONS.md обновлён
- [x] Метрики актуализированы (после Задачи 2)

Коммит: `docs(base_manager): mark all refactoring steps complete`.

---

## Definition of Done Phase 0.5

- [x] Пустые директории удалены, `git status` чистый.
- [x] `00_overview.md` содержит метрики «после» для `base_manager`.
- [x] `01_base_manager.md` — все чекбоксы `[x]`.
- [x] `pytest base_manager/tests -v` — зелёные.
- [x] `python scripts/validate.py` — зелёный.

---

## Время

~15 минут ручной работы. Можно сделать без LLM.
