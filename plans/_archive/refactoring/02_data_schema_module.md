# Refactoring plan: `data_schema_module` (модуль #2)

> **Статус:** 🟢 Выполнено (2026-04-09).  
> **Автор плана:** Opus, Фаза 1 мета-плана v4.1.  
> **Исполнитель:** Cursor Composer Agent (рекомендуется Agent mode / Composer 2).  
> **Ссылки:** [00_overview.md](./00_overview.md) · [ARCHITECTURE.md](../../multiprocess_framework/ARCHITECTURE.md)

---

## 0. Контекст

**Аудит §4 (фактически):** `utils/helpers.py` и `utils/reference.py` — дубликаты `core/helpers.py` и `core/reference.py` (не shims). Канон: `storage/storage_manager.py` и `storage/process_data_container.py`; `extensions/storage_manager.py` / `process_data_container.py` — тонкие re-export (удалены). `extensions/metrics.py` → shim на `core/metrics.py`. `extensions/__init__.py` уже был коротким (~30 строк). Внешних импортов `simple_api` / `ManagerDataAdapter` нет (только `api/` + `extensions/` + удалённый `_compat`).

Модуль **уже прошёл рефакторинг v2.0** (STATUS.md: 10/11 шагов). Архитектура (core → registry → serialization → container) — корректная. Однако осталось:

1. **~20 re-export shim файлов** (`fields/`, `utils/` shims, `storage/` shims, `registry/` shims) — пустые обёртки, которые никто снаружи не импортирует.
2. **`_compat.py`** (73 строки) — backward-compat re-exports. **Ни один внешний модуль их не использует** (подтверждено grep).
3. **`tests_backup/`** (17 файлов) — старые тесты, используют удалённые пути (`fields/register_base`).
4. **`extensions/__init__.py`** — 1163 строки re-exports, раздут.
5. **Дубликаты `core/helpers.py` vs `utils/helpers.py`**, `core/reference.py` vs `utils/reference.py`** — нужна консолидация.
6. **Документация:** нет `DECISIONS.md`, `STATUS.md` и `MIGRATION.md` нужно обновить/удалить.

**Цель:** убрать ~25 файлов shims/backup, сократить LOC на ~15-20%, закрепить публичный API.

---

## 1. Vision

**Идея модуля:** Независимое ядро для описания структур данных (Pydantic v2). `SchemaBase` + `FieldMeta` + `FieldRouting` — фундамент для регистров. Нулевые зависимости от других модулей фреймворка в core-слое.

**Что НЕ менять:**
- Публичный API в `__init__.py` (~50 экспортов) — **не трогать**.
- Пути `core/`, `registry/`, `serialization/`, `container/` — **каноническая структура**, не менять.
- Содержимое canonical-файлов (`core/schema_base.py`, `core/field_meta.py` и т.д.) — **не менять логику**.

**Что убрать:** shim-файлы, backup-тесты, `_compat.py`, дубликаты в `utils/`.

---

## 2. Текущее состояние (baseline)

- **Файлов:** 97 `.py` (без tests/__pycache__)
- **LOC:** ~13 888
- **Тестов:** 24 test-файла + 17 backup
- **Публичный API:** ~50 экспортов из `__init__.py`
- **Внешние потребители:** 13 модулей, все используют `from data_schema_module import X` (top-level)

### 2.1. Внешние потребители (полный список)

| Модуль | Что импортирует |
|--------|----------------|
| `base_manager` | `FieldMeta, SchemaBase, register_schema` |
| `channel_routing_module` | `FieldMeta, SchemaBase, register_schema` |
| `command_module` | `FieldMeta, SchemaBase, register_schema` |
| `config_module` | `FieldMeta, SchemaBase, register_schema` + `data_schema_module.core.helpers.merge_with_defaults` |
| `dispatch_module` | `FieldMeta, SchemaBase, register_schema` |
| `frontend_module` | `FieldMeta, SchemaBase, register_schema` (configs) + `SchemaBase` (core/schema_config) |
| `process_manager_module` | `build_process_with_workers, config_to_dict, merge_with_defaults` |

**Критично:** `config_module/core/config.py` использует прямой путь `from data_schema_module.core.helpers import merge_with_defaults` — это корректно, оставить.

**Не используется снаружи:** `_compat.py` экспорты (`StorageManager`, `ManagerDataAdapter`, `ModelFactory`, `create_config`, `MetricsCollector`, `ProcessDataContainer`, `ComponentDNA`).

---

## 3. Файлы к удалению (26 файлов)

### 3.1. Re-export shims в `fields/` (6 файлов)

Каждый файл — 13-строчный shim, импортирующий из `core/`:

```
fields/__init__.py
fields/field_meta.py       → core/field_meta.py
fields/field_routing.py    → core/field_routing.py
fields/field_types.py      → core/field_types.py
fields/register_base.py    → core/schema_base.py
fields/register_mixin.py   → core/schema_mixin.py
```

**Проверка перед удалением:** grep `from data_schema_module.fields` — результаты только внутри `data_schema_module/` (shims и `tests_backup/`). Внешних потребителей нет.

### 3.2. Re-export shims в `utils/` (7 файлов)

```
utils/__init__.py
utils/validators.py        → core/validators.py
utils/converters.py        → serialization/converter.py
utils/registers_io.py      → serialization/io.py
utils/registers_container.py → container/registers_container.py
utils/config_converters.py → container/config_converters.py
utils/helpers.py           ← ВНИМАНИЕ: 393 строки, возможно НЕ shim (см. §4.1)
utils/reference.py         ← ВНИМАНИЕ: возможно НЕ shim (см. §4.2)
```

### 3.3. Re-export shims в `storage/` (5 файлов)

```
storage/__init__.py
storage/file_storage.py         → serialization/file_storage.py
storage/storage_manager.py      → extensions/storage_manager.py (который сам shim → storage/ canonical?)
storage/process_data_container.py → extensions/process_data_container.py
```

**ВАЖНО:** Нужно проверить, какой файл canonical: `storage/storage_manager.py` или `extensions/storage_manager.py`. По данным агента, `storage/storage_manager.py` (459 строк) — canonical, а `extensions/storage_manager.py` — shim. Значит `storage/` — НЕ shim-директория для `storage_manager.py`! Удалять аккуратно.

### 3.4. Re-export shims в `registry/` (2 файла)

```
registry/register_discovery.py  → registry/discovery.py
registry/registers_scanner.py   → registry/discovery.py
```

### 3.5. `_compat.py` (1 файл)

Весь файл — backward-compat re-exports. Ни один внешний потребитель не использует. Удалить.

### 3.6. `tests_backup/` (17 файлов)

Целая директория старых тестов. Используют удалённые пути (`fields/register_base`). Удалить целиком.

### 3.7. `MIGRATION.md` (1 файл)

После удаления `_compat.py` и shims миграция завершена. Документ неактуален.

---

## 4. Файлы, требующие расследования

### 4.1. `utils/helpers.py` (393 строки) vs `core/helpers.py` (244 строки)

**Задача:** Открыть оба файла. Если `utils/helpers.py` — shim (13 строк), удалить. Если содержит дополнительные функции — выяснить, используются ли они. Если да — перенести в `core/helpers.py`. Если нет — удалить.

### 4.2. `utils/reference.py` vs `core/reference.py`

Аналогично §4.1. Проверить, shim или дубликат.

### 4.3. `extensions/__init__.py` (1163 строки)

Проверить содержимое. Если это re-exports из подмодулей — сократить до минимума. Если содержит реальный код — оставить, но уменьшить.

### 4.4. `extensions/simple_api.py` (577 строк)

Проверить, используется ли кем-то снаружи. Если нет — кандидат на удаление.

### 4.5. `extensions/manager_adapter.py` (542 строки)

Проверить, используется ли кем-то снаружи. Если нет — кандидат на пометку «internal/optional».

### 4.6. `extensions/metrics.py` vs `core/metrics.py`

Проверить: один shim, другой canonical? Или два разных файла?

### 4.7. `storage/` — canonical или shim?

Для файлов `storage_manager.py` и `process_data_container.py` — определить, где canonical реализация:
- Если `storage/` canonical → `extensions/storage_manager.py` и `extensions/process_data_container.py` — shims, удалить их.
- Если `extensions/` canonical → `storage/` — shims, удалить.

---

## 5. Атомарные шаги

### Шаг 0 — Baseline и расследование ⬜

**Цель:** Запустить тесты, разрешить вопросы из §4.

1. Запустить тесты: `pytest multiprocess_framework/modules/data_schema_module/tests -v`
2. Записать baseline: количество тестов, все ли зелёные.
3. **Расследовать §4.1:** Открыть `utils/helpers.py` — это shim или реальный код?
4. **Расследовать §4.2:** Открыть `utils/reference.py` — shim или реальный код?
5. **Расследовать §4.3:** Открыть `extensions/__init__.py` — сколько реального кода vs re-exports?
6. **Расследовать §4.4-4.5:** `grep -r "simple_api\|ManagerDataAdapter" --include="*.py"` вне `data_schema_module/` — есть ли внешние потребители?
7. **Расследовать §4.6:** Открыть `extensions/metrics.py` и `core/metrics.py` — кто canonical?
8. **Расследовать §4.7:** Открыть `storage/storage_manager.py` (первые 20 строк) — это shim или реализация?
9. Обновить этот план с результатами расследования.
10. Коммит: `docs(data_schema_module): baseline audit before cleanup`.

---

### Шаг 1 — Удалить `tests_backup/` ⬜

1. `git rm -r multiprocess_framework/modules/data_schema_module/tests_backup/`
2. Тесты зелёные.
3. Коммит: `refactor(data_schema_module): remove legacy tests_backup/ directory`.

---

### Шаг 2 — Удалить `fields/` shims ⬜

1. Убедиться: `grep -r "from data_schema_module.fields" --include="*.py"` — результаты ТОЛЬКО внутри `data_schema_module/` (shims ссылаются друг на друга + `tests_backup/` уже удалён).
2. `git rm -r multiprocess_framework/modules/data_schema_module/fields/`
3. Тесты зелёные.
4. Коммит: `refactor(data_schema_module): remove fields/ re-export shims`.

---

### Шаг 3 — Удалить `utils/` shims ⬜

**ВНИМАНИЕ:** Этот шаг зависит от результатов §4.1 и §4.2.

**Если `utils/helpers.py` — shim (13 строк):**
1. `git rm -r multiprocess_framework/modules/data_schema_module/utils/`

**Если `utils/helpers.py` содержит доп. функции:**
1. Перенести уникальные функции в `core/helpers.py`.
2. Обновить импорты (если есть внутренние).
3. Удалить `utils/` целиком.

Тесты зелёные. Коммит: `refactor(data_schema_module): remove utils/ re-export shims`.

---

### Шаг 4 — Удалить `registry/` shims ⬜

1. `git rm multiprocess_framework/modules/data_schema_module/registry/register_discovery.py`
2. `git rm multiprocess_framework/modules/data_schema_module/registry/registers_scanner.py`
3. Тесты зелёные.
4. Коммит: `refactor(data_schema_module): remove registry/ re-export shims`.

---

### Шаг 5 — Консолидировать `storage/` и `extensions/` shims ⬜

**Зависит от результатов §4.7.**

**Сценарий A (storage/ canonical):**
1. Удалить `extensions/storage_manager.py` (shim).
2. Удалить `extensions/process_data_container.py` (shim).
3. `storage/file_storage.py` — если shim на `serialization/file_storage.py`, удалить.
4. Обновить `extensions/__init__.py` — убрать строки, импортирующие из удалённых shims.

**Сценарий B (extensions/ canonical):**
1. Удалить `storage/` целиком.
2. Обновить импорты если нужно.

Тесты зелёные. Коммит: `refactor(data_schema_module): consolidate storage/extensions shims`.

---

### Шаг 6 — Удалить `_compat.py` ⬜

1. Удалить `_compat.py`.
2. Убрать упоминание `_compat` из `__init__.py` docstring (строка 15).
3. Тесты зелёные.
4. Коммит: `refactor(data_schema_module): remove _compat.py backward compatibility layer`.

---

### Шаг 7 — Почистить `extensions/__init__.py` ⬜

**Зависит от §4.3.**

1. Если файл — 1163 строки re-exports: сократить до минимального `__init__.py` (~30 строк), экспортирующего только реально используемые классы.
2. Если содержит реальный код: вынести код в отдельные файлы, оставить `__init__.py` как фасад.
3. Тесты зелёные.
4. Коммит: `refactor(data_schema_module): slim down extensions/__init__.py`.

---

### Шаг 8 — Удалить `MIGRATION.md`, обновить `STATUS.md` ⬜

1. `git rm MIGRATION.md` — миграция завершена, shims удалены.
2. Обновить `STATUS.md`: Шаг 11 → «Cleanup shims» → ✅.
3. Обновить `README.md`: убрать секции про `_compat.py`, `fields/`, `utils/`.
4. Коммит: `docs(data_schema_module): update docs after shim cleanup`.

---

### Шаг 9 — Создать `DECISIONS.md` ⬜

Файл: `modules/data_schema_module/DECISIONS.md`

ADR для записи:
- **ADR-120:** Удаление `_compat.py` — backward-compat не нужен (0 внешних потребителей).
- **ADR-121:** Удаление shim-директорий (`fields/`, `utils/` re-exports) — canonical пути в `core/`, `serialization/`, `container/`.
- **ADR-122:** Удаление `tests_backup/` — покрыто основными тестами.
- **ADR-123:** `extensions/` — только явный импорт (`from data_schema_module.extensions.X import Y`), не входит в top-level `__init__.py`.

Обновить главный `DECISIONS.md` — добавить ссылку на `modules/data_schema_module/DECISIONS.md`.

Коммит: `docs(data_schema_module): add DECISIONS.md with ADR-120…123`.

---

### Шаг 10 — Финальная валидация ⬜

1. `pytest multiprocess_framework/modules/data_schema_module/tests -v` — зелёные.
2. `python scripts/validate.py` — зелёный.
3. Собрать метрики «после»: файлы, LOC, тесты.
4. Обновить `plans/refactoring/00_overview.md` — строка `data_schema_module` с метриками «после».
5. Коммит: `refactor(data_schema_module): final validation and metrics`.

---

## 6. Ключевые решения

### 6.1. Почему удалить `_compat.py`

Grep по всему `` показал: **0 внешних потребителей** импортов из `_compat.py`. Все 13 модулей используют top-level `from data_schema_module import X`, и все нужные символы экспортируются из `__init__.py` напрямую (через `core/`, `registry/`, `serialization/`, `container/`).

### 6.2. Почему удалить shim-директории

Shims (`fields/`, `utils/` re-exports) были созданы при рефакторинге v2.0 как переходный слой. Переход завершён — ни один внешний модуль не импортирует через старые пути. Единственные потребители старых путей — `tests_backup/` (тоже удаляется).

### 6.3. Почему оставить `extensions/`

Extensions содержат реальный код (StorageManager, VersionManager, MetricsCollector, ModelFactory). Хотя сейчас никто снаружи их не использует, это полезные инструменты для будущих milestone (M1/M2/M3). Оставить, но не экспортировать через top-level `__init__.py`.

---

## 7. Публичный API (не менять)

```python
# __init__.py — эти импорты НЕ ТРОГАТЬ
from data_schema_module import (
    SchemaBase, RegisterBase, SchemaMixin, RegisterMixin,
    FieldMeta, FieldRouting, RegisterDispatchMeta,
    Percent, NormalizedFloat, Scale, ...,  # field types
    DataSchemaError, SchemaValidationError, ...,  # exceptions
    DataValidator,
    get_nested_value, set_nested_value, merge_with_defaults, ...,  # helpers
    DataReference, is_reference, ...,  # reference
    SchemaRegistry, SchemaManager, register_schema, ...,  # registry
    DataConverter, FormatType, registers_to_dict, ...,  # serialization
    FileStorage,
    RegistersContainer, config_to_dict, process, ...,  # container
)
```

---

## 8. Целевая структура файлов

```
data_schema_module/
├── __init__.py                # ~50 экспортов (без изменений)
├── interfaces.py              # Публичный контракт
├── README.md                  # Обновлён
├── STATUS.md                  # Обновлён
├── DECISIONS.md               # НОВЫЙ (ADR-120…123)
├── core/                      # Ядро (canonical)
│   ├── __init__.py
│   ├── schema_base.py
│   ├── schema_mixin.py
│   ├── field_meta.py
│   ├── field_routing.py
│   ├── field_types.py
│   ├── register_dispatch.py
│   ├── exceptions.py
│   ├── validators.py
│   ├── helpers.py
│   ├── reference.py
│   ├── metrics.py
│   └── interfaces.py
├── registry/                  # Реестр (canonical)
│   ├── __init__.py
│   ├── schema_registry.py
│   ├── discovery.py
│   └── process_registry.py
├── serialization/             # Сериализация (canonical)
│   ├── __init__.py
│   ├── converter.py
│   ├── io.py
│   └── file_storage.py
├── container/                 # Контейнеры (canonical)
│   ├── __init__.py
│   ├── registers_container.py
│   └── config_converters.py
├── extensions/                # Расширения (явный импорт)
│   ├── __init__.py            # Сокращён до ~30 строк
│   ├── storage_manager.py     # ИЛИ в storage/ (см. §4.7)
│   ├── manager_adapter.py
│   ├── versioning.py
│   ├── simple_api.py
│   ├── metrics.py             # ИЛИ только core/metrics.py (см. §4.6)
│   ├── process_data_container.py
│   ├── factory/
│   └── models/
├── tools/                     # Инструменты (опциональные)
│   ├── __init__.py
│   ├── schema_visualizer.py
│   ├── schema_documentation_generator.py
│   └── formatters.py
├── docs/                      # Документация
│   └── examples/
└── tests/                     # Тесты (основные, без backup)
    ├── conftest.py
    ├── test_schema_base.py
    ├── test_field_meta.py
    └── ... (~22 файла)
```

**Удалено:**
- `_compat.py`
- `MIGRATION.md`
- `fields/` (целиком, 6 файлов)
- `utils/` (целиком, ~8 файлов)
- `storage/` shims (или `extensions/` shims — по результатам §4.7)
- `registry/register_discovery.py`, `registry/registers_scanner.py`
- `tests_backup/` (целиком, 17 файлов)

**Целевые метрики:** ~60 файлов (−37), ~11 000 LOC (−20%), публичный API без изменений.

---

## 9. Definition of Done (модуль #2)

- [x] Все тесты `data_schema_module` зелёные.
- [x] Все внешние потребители (13 модулей) — тесты зелёные (`run_framework_tests.py`).
- [x] `python scripts/validate.py` — зелёный.
- [x] `_compat.py` удалён.
- [x] `tests_backup/` удалён.
- [x] Shim-директории (`fields/`, `utils/` re-exports, `registry/` shims) удалены.
- [x] `extensions/__init__.py` ≤ 50 строк.
- [x] Публичный API (`__init__.py`) не изменился (кроме docstring).
- [x] `DECISIONS.md` создан (ADR-120…123).
- [x] Главный `DECISIONS.md` обновлён — ссылка на `data_schema_module/DECISIONS.md`.
- [x] Метрики «после» в `00_overview.md`.
- [x] README обновлён (без упоминаний `_compat`, `fields/`, `utils/` shims).

---

## 10. Инструкции для Cursor Composer Agent

> **Контекст для Composer:** Этот модуль — ядро фреймворка. 13 других модулей зависят от него. НЕ менять публичный API в `__init__.py`. НЕ менять canonical файлы в `core/`, `registry/`, `serialization/`, `container/`. Удалять только shim-обёртки и backup.

### Порядок работы:
1. Читай каждый шаг полностью перед началом.
2. Начинай с Шага 0 (расследование) — запиши результаты.
3. Выполняй шаги 1-7 по порядку, каждый — отдельный коммит.
4. После каждого шага: `pytest data_schema_module/tests -v`.
5. В конце: `python scripts/validate.py`.

### Что НЕ делать:
- НЕ менять `__init__.py` imports/exports (кроме удаления ссылки на `_compat` в docstring).
- НЕ менять файлы в `core/`, `registry/`, `serialization/`, `container/`.
- НЕ менять код внешних модулей.
- НЕ добавлять новые зависимости.
- НЕ рефакторить логику — только удаление мёртвого кода.
