# Архитектурная чистка `multiprocess_framework` ↔ `multiprocess_prototype`

**Дата:** 2026-05-10
**Триггер:** sentrux + qex анализ выявил 2 критичных и 2 средних архитектурных недочёта на стыке фреймворка и prototype_2 + продуктовое решение разделить **framework / Services / Plugins / application**.
**Branch:** `chore/mlx-embeddings-migration` (текущая) или новая `refactor/arch-cleanup`.

## Целевая архитектура (после рефакторинга)

```
Inspector_bottles/
├── multiprocess_framework/     # Чистый backend-фреймворк (process/IPC/state/UI-toolkit)
│   └── modules/                #   sql_module — выехал в Services
├── Services/                   # Прикладные сервисы с тяжёлыми внешними deps
│   ├── sql_module/             #   ← из Services/sql
│   └── hikvision_camera_module_2/  # ← хардварный driver (рефакторинг уже выполнен)
├── Plugins/                    # Vocabulary плагинов — переиспользуется между приложениями
│   ├── capture/, grayscale/, region_split/, ...  # ← из multiprocess_prototype/plugins
│   └── (~19 плагинов)
└── multiprocess_prototype/   # Application = bootstrap + topology yaml + state schema
    ├── topology/*.yaml
    ├── state/, config/, frontend/  # app-specific glue
    └── plugins/                # пусто или только app-specific (если останется)
```

**Контракт layer-ов:**
- `framework` ничего не знает про Services/Plugins/app.
- `Services` импортит framework. Не знает про Plugins/app.
- `Plugins` импортят framework + Services. Не знают про конкретное app.
- `app` (prototype_2/3/...) импортит всё — это composition root.

Подтверждено: пользователь планирует второе приложение → `Plugins/` имеет прямой ROI.

---

## Контекст: текущие метрики

| Метрика | До | Цель | Источник |
|---|---|---|---|
| `quality_signal` | **6173** / 10000 | ≥ 7500 | `mcp__sentrux__health` |
| `acyclicity` (raw / score) | 2 / **3333** | 0 / ≥ 9000 | bottleneck |
| `modularity` | 0.448 / 6320 | ≥ 0.50 / 7000 | — |
| `redundancy` | 0.071 / 9289 | сохранить | — |
| Test coverage | 314 / 1274 = **24.6%** | ≥ 35% | `mcp__sentrux__test_gaps` |
| `cross_module_edges` | 461 | сохранить | — |
| Импорт `framework → prototype_2` | **9 строк** | 0 | `grep -rn` |

**DSM:** `above_diagonal=0`, `below_diagonal=1044` — слоение чистое (зависимости текут вниз). Архитектура жива, проблемы локальные.

---

## Phase 1 — P1: критичные недочёты

### Task 1.1 — Вынести prototype_2-импорты из framework-теста

**Файл:** [`multiprocess_framework/modules/process_module/tests/test_registers_integration.py`](../../multiprocess_framework/modules/process_module/tests/test_registers_integration.py) (343 строки, 9 импортов из `multiprocess_prototype.plugins.color_mask`)

**Проблема:** тест фреймворка зависит от плагина прототипа. Удалить/переименовать prototype_2 нельзя без поломки CI фреймворка → нарушение направления зависимостей.

**Подход (выбрать один):**

| Вариант | Что делать | Плюсы | Минусы |
|---|---|---|---|
| **A. Перенос (Recommended)** | Перенести файл в `multiprocess_prototype/state/tests/test_registers_integration.py` (или `multiprocess_prototype/tests/`) | минимум изменений, корректное направление зависимостей | тест перестаёт гоняться при `pytest multiprocess_framework/` — нужно убедиться что `run_framework_tests.py` отдельно ловит prototype_2-тесты или они идут через общий `pytest .` |
| B. Локальный fixture-плагин | В `multiprocess_framework/modules/process_module/tests/fixtures/` создать минимальный `_TestColorMaskPlugin` с тем же контрактом, переписать тест | framework-тесты остаются self-contained | дублирование кода, риск дрейфа от prototype_2-плагина |

**Acceptance:**
- [ ] `grep -rn "from multiprocess_prototype" multiprocess_framework/ --include="*.py"` → пусто
- [ ] `python scripts/run_framework_tests.py` → green
- [ ] `pytest multiprocess_prototype/` → green (если выбран вариант A)

**Эстимейт:** 1-2 часа (вариант A) / 3-4 часа (вариант B).

---

### Task 1.2 — Разорвать циклический импорт `config_module/core ↔ sections`

**Файлы:**
- [`multiprocess_framework/modules/config_module/core/config.py:104`](../../multiprocess_framework/modules/config_module/core/config.py#L104) — `from ...sections.config_section import ConfigSection` (lazy внутри метода)
- [`multiprocess_framework/modules/config_module/sections/config_section.py:7`](../../multiprocess_framework/modules/config_module/sections/config_section.py#L7) — `from ...core.config import Config` (top-level)

**Проблема:** sentrux acyclicity raw=2 — это и есть данный 2-cycle. Цикл сейчас «работает» только за счёт ленивого импорта в `core/config.py`, но архитектурно `sections` зависит от `core`, а обратная зависимость должна быть выкорчевана.

**Подход:**
1. Прочитать `core/config.py:90-130` (где использование `ConfigSection`).
2. Посмотреть, что именно нужно от `ConfigSection` в `Config` → скорее всего фабричная функция или базовый Protocol.
3. Вариант **A**: вынести общий type/Protocol в `multiprocess_framework/modules/config_module/types.py`. Оба файла импортят его, цикла нет.
4. Вариант **B**: переписать метод в `core/config.py` так, чтобы он принимал `ConfigSection` через DI (параметр), а конструирование секции — в вызывающем коде.

**Acceptance:**
- [ ] `mcp__sentrux__health` → `acyclicity.raw=0`, `score ≥ 9000`
- [ ] `python -c "from multiprocess_framework.modules.config_module.core.config import *"` без ошибок
- [ ] `pytest multiprocess_framework/modules/config_module/` → green
- [ ] `quality_signal` ≥ 6800 (рост за счёт acyclicity-вклада)

**Эстимейт:** 3-5 часов (зависит от того, насколько Config и ConfigSection переплетены).

---

## Phase 2 — P2: средние недочёты

### Task 2.1 — Создать `.sentrux/rules.toml` с архитектурными инвариантами

**Текущее состояние:** `mcp__sentrux__check_rules` возвращает `No rules file found at /Users/twokrai/Project_code/Inspector_bottles/.sentrux/rules.toml`. CLAUDE.md уже упоминает `process_module ∌ frontend_module` — но без файла это не enforced.

**Содержимое `.sentrux/rules.toml`:**

```toml
# Архитектурные инварианты Inspector_bottles
# Проверка: /sentrux-rules (MCP, интерактивно) или /sentrux-check (CI)

[[rules]]
name = "framework-no-prototype"
description = "multiprocess_framework НЕ импортирует prototype_2"
forbid_imports_from = "multiprocess_framework"
to = "multiprocess_prototype"

[[rules]]
name = "process-no-frontend"
description = "process_module НЕ импортирует frontend_module (по CLAUDE.md)"
forbid_imports_from = "multiprocess_framework.modules.process_module"
to = "multiprocess_framework.modules.frontend_module"

[[rules]]
name = "process-no-process-manager"
description = "process_module НЕ импортирует process_manager_module (нижний слой не знает верхнего)"
forbid_imports_from = "multiprocess_framework.modules.process_module"
to = "multiprocess_framework.modules.process_manager_module"

[[rules]]
name = "no-archived-prototypes"
description = "Никто не должен импортировать архивные multiprocess_prototype/_v2"
forbid_imports_to = "multiprocess_prototype"
forbid_imports_to_pattern = "multiprocess_prototype_v2"
```

> Точный синтаксис sentrux rules.toml уточнить через `sentrux check --help` или их доку — может быть другой формат полей. Адаптировать перед коммитом.

**Acceptance:**
- [ ] Файл создан, `/sentrux-check` → exit 0 (после Task 1.1)
- [ ] Добавить `/sentrux-check` шаг в `scripts/validate.py` или CI

**Эстимейт:** 1-2 часа (включая верификацию синтаксиса).

---

### Task 2.2 — Выпилить backward-compat kwargs из `PluginContext`

**Файл:** [`multiprocess_framework/modules/process_module/plugins/base.py:62-136`](../../multiprocess_framework/modules/process_module/plugins/base.py#L62-L136)

**Проблема:** `PluginContext.__init__` тащит 3 deprecated kwarg-а (`process_name`, `process`, `state_proxy`) и атрибут `_process` «for backward-compat». По CLAUDE.md правилу «никаких backwards-compat shims» — это технический долг.

**Подход:**
1. Найти всех вызывающих со старым API:
   ```bash
   mcp__qex__search_code "PluginContext process= process_name="
   grep -rn "PluginContext(process=" --include="*.py"
   ```
2. Переписать на новый API: `PluginContext(services=..., config=..., io=..., registers=...)`.
3. Удалить deprecated kwargs из `__init__`, удалить тесты `test_context_backward_compat_*` ([`test_plugin_context_protocol.py`](../../multiprocess_framework/modules/process_module/tests/test_plugin_context_protocol.py)).
4. Удалить `self._process = services` и `with_config` адаптировать.

**Acceptance:**
- [ ] `grep -rn "PluginContext(process=" --include="*.py"` → пусто
- [ ] `pytest multiprocess_framework/modules/process_module/` → green
- [ ] `pytest multiprocess_prototype/` → green
- [ ] `/run-proto` запускается без ошибок

**Эстимейт:** 2-4 часа (зависит от количества вызовов).

---

## Phase 3 — P3: test gaps на узлах высокой связности

**Контекст:** 960/1274 файлов без тестов, score 0.246. Полное покрытие — overkill. Покрываем только высокий fan-in (узлы, которые тянет за собой много кода).

### Task 3.1 — Покрыть top-7 риск-файлов

| Файл | Fan-in | Тип | Приоритет |
|---|---|---|---|
| `chain_module/__init__.py` | 11 | re-exports + DAG entry | **Высокий** |
| `sql_module/interfaces.py` | 8 | Protocol-контракт | Средний |
| `router_module/middleware/__init__.py` | 8 | re-exports | Средний |
| `sql_module/adapters/sync_adapter.py` | 3 | I/O | **Высокий** |
| `sql_module/adapters/async_adapter.py` | 3 | I/O | **Высокий** |
| `frontend_module/components/numeric/presenter.py` | 4 | UI presenter | Низкий |
| `frontend_module/components/group/labeled_numeric_factory.py` | 4 | factory | Низкий |

**Откладываем:**
- `frontend_module/core/qt_imports.py` (fanin=91) — это Qt-shim, тестировать smoke-импортом достаточно.
- `frontend_module/.../config.py` файлы (fanin 5-15) — это в основном Pydantic dataclass-ы, для них тесты — overkill.
- `frontend_module/interfaces.py` (fanin=24) — Protocol, тестируется implicitly через подклассы.

**Подход:** делегировать `tester`-агенту по каждому файлу отдельно (3-5 тестов на файл).

**Acceptance:**
- [ ] Coverage на 7 файлах → ≥ 70%
- [ ] `python scripts/run_framework_tests.py` → green
- [ ] Общий coverage_score → ≥ 0.30

**Эстимейт:** 6-10 часов (по 1-1.5ч на файл, через `/test`).

---

## Phase 4 — Carve-out: Services

> **Триггер:** делается **после** Phase 1+2 (чистая baseline). Phase 3 может идти параллельно.

### Task 4.1 — `sql_module` → `Services/sql/`

**Что переезжает:**
- `Services/sql/` → `Services/sql/`
- Содержимое: core, adapters (sync/async), commands, configs, export, interfaces, tests
- Папка `interfaces.py` имеет fan-in 8, `adapters/*` — fan-in 3

**Подход:**
1. `git mv Services/sql/ Services/sql/`
2. Replace импортов: `from Services.sql` → `from Services.sql`
   - Замер до: `grep -rn "from Services.sql" --include="*.py" | wc -l`
   - sed по результатам.
3. Если `sql_module` импортирует что-то из framework — оставить как есть (Services → framework OK).
4. Запустить тесты `pytest Services/sql/`.
5. Smoke-тест прототипа: `/run-proto`.

**Возможная проблема:** `sql_module` может зависеть от `data_schema_module` или `config_module` — это нормально, Services тащит framework. Обратное (framework → Services) — запрещено правилом 4.3.

**Acceptance:**
- [ ] `Services/sql/` существует, тесты green
- [ ] `grep -rn "from Services.sql" --include="*.py"` → пусто
- [ ] `mcp__sentrux__scan` → `quality_signal` не упал

**Эстимейт:** 3-4ч.

---

### Task 4.2 — Привести рефакторенный hikvision-модуль в `Services/hikvision_camera/`

**Контекст:** старый `Services/hikvision_camera/` уже удалён (deleted в `git status`), рефакторинг камера-модуля выполнен пользователем отдельно.

**Что сделать:**
1. Поместить новый рефакторенный модуль в `Services/hikvision_camera/` (имя без суффиксов `_module_2`).
2. Проверить, что плагин `capture` (или `camera_service`) импортит его через стабильный API.
3. Зарегистрировать в `pyproject.toml` extras (`[hikvision]` или `[ml]`).

**Acceptance:**
- [ ] Модуль на месте, импорт `from Services.hikvision_camera import ...` работает
- [ ] Плагин `capture`/`camera_service` запускается в smoke-тесте

**Эстимейт:** 1-2ч (если рефакторинг камеры уже завершён).

---

### Task 4.3 — Sentrux rule: framework не зависит от Services

Добавить в `.sentrux/rules.toml` (создан в Task 2.1):

```toml
[[rules]]
name = "framework-no-services"
description = "multiprocess_framework НЕ импортирует из Services"
forbid_imports_from = "multiprocess_framework"
to = "Services"
```

**Acceptance:**
- [ ] `/sentrux-check` → exit 0
- [ ] CI ловит попытку `from Services.X` внутри framework

**Эстимейт:** 30мин.

---

## Phase 5 — Carve-out: Plugins/

> **Триггер:** после Phase 4. Подтверждено пользователем — будут новые приложения, переиспользующие плагины. ROI вполне реальный.

### Task 5.1 — Перенести `multiprocess_prototype/plugins/` → `Plugins/`

**Контекст из анализа цены миграции:**
- 19 плагинов, 28 файлов registers/configs/schemas
- 15 ссылок в topology yaml
- 56 Python-импортов
- 11 тестовых файлов
- **0 прямых `state_proxy.set/get`** в плагинах ★ — плагины уже архитектурно готовы как vocabulary, не привязаны к application state-tree

**Подход:**
1. `git mv multiprocess_prototype/plugins/ Plugins/`
2. Sed по Python-импортам:
   ```bash
   grep -rln "multiprocess_prototype.plugins" --include="*.py" | \
     xargs sed -i '' 's|multiprocess_prototype\.plugins|Plugins|g'
   ```
3. Sed по topology yaml (`plugin_class`, `process_class`):
   ```bash
   grep -rln "multiprocess_prototype.plugins" multiprocess_prototype/topology/*.yaml | \
     xargs sed -i '' 's|multiprocess_prototype\.plugins|Plugins|g'
   ```
4. Обновить [`main.py:26`](../../multiprocess_prototype/main.py#L26): `PLUGINS_DIR = HERE / "plugins"` → `PLUGINS_DIR = PROJECT_ROOT / "Plugins"`.
5. Создать `Plugins/__init__.py` (пустой или с docstring).
6. Прогнать `pytest Plugins/` (1108 тестов prototype_2 включали plugin-тесты — должны переехать с плагинами).
7. Smoke-тест: `/run-proto`.

**Подводный камень:** `PluginRegistry._file_to_module` ([registry.py:175](../../multiprocess_framework/modules/process_module/plugins/registry.py#L175)) ищет ближайший `sys.path` entry. Корень репо уже в `sys.path` (см. `main.py:23-24`) → discover отработает как раньше, найдёт `Plugins/X/plugin.py`.

**Acceptance:**
- [ ] `grep -rn "multiprocess_prototype.plugins" --include="*.py" --include="*.yaml"` → пусто
- [ ] 19 плагинов discover-ятся: `mcp__qex__search_code` или smoke-тест с `PluginRegistry.list()`
- [ ] `/run-proto` запускается и работает (frame от камеры доходит до GUI)
- [ ] `pytest Plugins/` → green
- [ ] `mcp__sentrux__health` → modularity score не упал (надо вырасти)

**Эстимейт:** 4-6ч (с smoke-тестом и фиксом edge-cases).

---

### Task 5.2 — Sentrux rule: плагины не знают про конкретное приложение

```toml
[[rules]]
name = "plugins-app-agnostic"
description = "Plugins не импортируют из multiprocess_prototype/3/... — только framework + Services"
forbid_imports_from = "Plugins"
to = "multiprocess_prototype"
# в будущем добавить: to = ["multiprocess_prototype", "multiprocess_prototype_3", ...]
```

**Acceptance:**
- [ ] Правило в `.sentrux/rules.toml`
- [ ] `/sentrux-check` → exit 0

**Эстимейт:** 30мин.

---

### Task 5.3 — ADR «Plugins как vocabulary»

Создать [`multiprocess_framework/DECISIONS.md`](../../multiprocess_framework/DECISIONS.md) запись или отдельный ADR-файл `docs/ADR/2026-05-plugins-vocabulary.md`:

**Контракт плагина:**
1. Знает только `PluginContext` (services, config, io, registers).
2. **Не** знает имя процесса в топологии, ключи application state-tree, конкретное приложение.
3. State-binding только через `ctx.state_proxy` с локальным namespace или `ctx.config`.
4. Hard ban на `from multiprocess_prototype import ...` — enforced правилом 5.2.

**Acceptance:**
- [ ] ADR создан
- [ ] Ссылка в `multiprocess_framework/DECISIONS.md` через `python -m scripts.sync`

**Эстимейт:** 1ч.

---

## Phase 6 — Финал

### Task 6.1 — Зафиксировать baseline и обновить документацию

1. `mcp__sentrux__session_end` после завершения всех Phase 1-5 → новый baseline.
2. Обновить [`multiprocess_framework/DECISIONS.md`](../../multiprocess_framework/DECISIONS.md):
   - ADR-FW-XXX «Запрет prototype_2-импортов в framework тестах + `.sentrux/rules.toml`»
   - ADR-FW-XXX «Carve-out: sql_module → Services/»
   - ADR-FW-XXX «Plugins/ как vocabulary»
3. Обновить [`multiprocess_framework/MODULES_STATUS.md`](../../multiprocess_framework/MODULES_STATUS.md):
   - `sql_module`: статус «выехал в Services/sql_module»
   - `config_module`: цикл разорван
4. Обновить [`CLAUDE.md`](../../CLAUDE.md):
   - Раздел «Ключевые пути» — новые `Services/`, `Plugins/`
   - Правила проекта — упомянуть layer-инварианты
5. `python -m scripts.sync` — пересборка ADR-индекса.
6. `python scripts/validate.py` — финальная верификация.

**Acceptance:**
- [ ] Все ADR созданы, `scripts/validate.py` green
- [ ] `mcp__sentrux__health` → `quality_signal ≥ 7500`, `acyclicity.score ≥ 9000`
- [ ] `mcp__sentrux__check_rules` → все 5 правил pass
- [ ] `git log --oneline` показывает atomic коммиты по каждой Task

**Эстимейт:** 2-3ч.

---

## Сводная таблица

| Phase | Task | Срок | Статус | Commit |
|---|---|---|---|---|
| 1 | 1.1 — миграция теста registers_integration | 1-2ч | ✅ Done | `c35b8ac` |
| 1 | 1.2 — разрыв цикла config_module | 3-5ч | ✅ Done | `c35b8ac` + `e77f597` |
| 2 | 2.1 — `.sentrux/rules.toml` | 1-2ч | ✅ Done | `7a342a2` |
| 2 | 2.2 — выпилить backward-compat | 2-4ч | ✅ Done | `7a342a2` |
| 3 | 3.1 — тесты топ-7 файлов | 6-10ч | ⏳ Skipped (отложено) | — |
| 4 | 4.1 — `sql_module` → `Services/sql` + Protocol bridge | 3-4ч | ✅ Done | `a3b525c` |
| 4 | 4.2 — `hikvision_camera_module_2` в `Services/` | 1-2ч | ✅ Done | `4db04d3` |
| 4 | 4.3 — rule: framework ∌ Services | 30мин | ✅ Done | `7a342a2` |
| 5 | 5.1 — `prototype/plugins/` → `Plugins/` | 4-6ч | ✅ Done | (этот PR) |
| 5 | 5.2 — rule: Plugins ∌ prototype | 30мин | ✅ Done | `7a342a2` (включено в Task 2.1) |
| 5 | 5.3 — ADR «Plugins vocabulary» | 1ч | ✅ Done | (этот PR) — ADR-120 |
| 6 | 6.1 — финал + ADR + CLAUDE.md update | 2-3ч | ⏳ TODO | — |

**Итого:** 25-44 часа. Реалистично — **5-7 дней focused work** или 2-3 недели в фоне.

**Параллелизм:**
- Phase 1 + Phase 3 параллельно (разные файлы).
- Phase 4 (Services) ждёт Phase 1+2 — нужна чистая baseline.
- Phase 5 (Plugins) ждёт Phase 4 — структура `Services/` должна быть стабильна, чтобы плагины импортили `Services.sql` корректно.
- Phase 6 — финал, ждёт всех.

**Риски и митигейшен:**
- *Phase 4.1:* `sql_module` может оказаться больше связан с `data_schema_module`, чем кажется. Митигейшен: до миграции — `mcp__qex__search_code "sql_module imports framework"` для замера.
- *Phase 5.1:* sed может зацепить лишнее (например, в комментариях). Митигейшен: ручной проход по diff после sed, прогон полного `pytest`.
- *Phase 5.1:* PluginRegistry.discover может не найти плагины в новом месте. Митигейшен: smoke-тест discover **до** миграции PLUGINS_DIR в `main.py`.

---

## Скрипт быстрого старта

```bash
# 0. Baseline ДО
/sentrux-baseline

# 1. Phase 1 параллельно с Phase 3
/implement Task 1.1: вынести prototype_2-импорты из framework-теста
/test Task 3.1.a: chain_module/__init__.py    # параллельно

# 2. Phase 1.2 — разрыв цикла (Opus, teamlead)
/plan Task 1.2: разорвать config_module цикл
/implement по плану
/sentrux-health  # acyclicity.raw == 0?

# 3. Phase 2 — правила и backward-compat
/implement Task 2.1: .sentrux/rules.toml (базовые правила)
/sentrux-check  # exit 0?
/implement Task 2.2: выпилить backward-compat в PluginContext

# 4. Phase 4 — Services carve-out (после чистой baseline)
/implement Task 4.1: sql_module → Services/sql/
/implement Task 4.2: hikvision_camera_module_2 → Services/
/implement Task 4.3: добавить rule framework ∌ Services
/sentrux-check  # exit 0?
/run-proto        # smoke-тест прототипа

# 5. Phase 5 — Plugins carve-out
/implement Task 5.1: prototype_2/plugins/ → Plugins/
/run-proto        # smoke-тест после переноса
/implement Task 5.2: rule Plugins ∌ prototype_2
/docs Task 5.3: ADR «Plugins vocabulary»

# 6. Финал
/docs Task 6.1: ADR + MODULES_STATUS + CLAUDE.md update
/sentrux-diff   # дельта vs baseline
```

---

## Связанные документы

- [CLAUDE.md (правила проекта)](../../CLAUDE.md)
- [`docs/claude/sentrux/README.md`](../claude/sentrux/README.md)
- [`docs/claude/qex/README.md`](../claude/qex/README.md)
- [`multiprocess_framework/DECISIONS.md`](../../multiprocess_framework/DECISIONS.md)
- Предыдущий рефактор: [`docs/refactors/2026-04_widgets_reorg.md`](2026-04_widgets_reorg.md)
