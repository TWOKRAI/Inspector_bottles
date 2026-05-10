# Генеральный рефакторинг multiprocess_prototype

## Контекст

Прототип Inspector Bottles вырос до ~68,700 строк / 630+ файлов. Глубокий анализ показал:
- **53% кода (17,300 стр.)** — полностью универсальный, может работать с ЛЮБЫМ приложением
- **17% (5,430 стр.)** — универсальный паттерн с доменной имплементацией
- **30% (9,700 стр.)** — реально доменный код (бутылки, камеры, CV, робот)

**Цель:** Превратить прототип в **тонкий конфигурационный слой** (~10K строк), перенести универсальные системы во фреймворк, создать SYSTEM_SPEC для NL-управления.

---

## Оценка текущего состояния

| Подсистема | Архитектура | Организация | Интеграция с fw | Поддерживаемость | Итого |
|---|---|---|---|---|---|
| **services/** (5,456 стр.) | 9 | 8 | 9 | 8 | **8.5** ★ лучшая |
| **config/** (382 стр.) | 8 | 8 | 9 | 7 | **8.0** |
| **backend/** (4,362 стр.) | 8 | 8 | 7 | 7 | **7.5** |
| **state_store/** (14,621 стр.) | 8 | 7 | 3 (не подключён!) | 6 | **6.0** |
| **registers/** (5,446 стр.) | 7 | 6 | 8 | 6 | **6.8** |
| **tests/** (23,367 стр.) | 7 | 6 | 7 | 6 | **6.5** |
| **frontend/** (12,063 стр.) | 6 | 5 | 6 | 5 | **5.5** ★ проблемная |
| **Общий балл** | | | | | **6.9/10** |

### Ключевые проблемы:
1. **state_store не подключён:** StateStoreManager (зрелый, 7 IPC-команд) не создаётся в ProcessManagerProcess. 14K строк не работают. Нужно ~50 строк "проводки"
2. **frontend/_archive/:** 20 файлов мёртвого кода (~1,896 стр.)
3. **registers/schemas/:** Дублирует доменные регистры
4. **53% кода прототипа — универсальный:** state_store core, action bus, entity editor, theme, styles, chain engine, metrics — всё это застряло в прототипе

---

## Единая vision

### Фреймворк = Полноценный конструктор многопроцессных PySide6-приложений
19 существующих модулей + новые из прототипа:
- `state_store_module` — реактивное дерево состояния с IPC
- `frontend_module` (расширение) — entity editor, action bus, chrome, themes, styles
- `chain_module` — DAG execution engine (pipeline любых операций)
- `config_module` (расширение) — YAML persistence, recipe snapshots

### Прототип = Тонкий доменный слой (~10K строк)
Только то, что специфично для инспекции бутылок:
- **Регистры** — схемы параметров (камера, процессор, рендерер, pipeline)
- **Конфиги процессов** — AppConfig, CameraConfig, ProcessorConfig, etc.
- **Доменные сервисы** — CV-операции, камера-бэкенды, робот, БД
- **Доменные виджеты** — pipeline editor, sources tab, processing tab
- **Bootstrap** — начальное дерево состояния, точка входа

### Правило границы
> Мог бы этот код работать в приложении мониторинга трафика? Да → фреймворк. Нет → прототип.

---

## Фазы рефакторинга

### Фаза 0: Очистка (без архитектурных изменений)

**0.1 Удалить мёртвый код:**
- `frontend/widgets/_archive/` — 20 файлов → DELETE
- Проверить `backend/processes/*/__main__.py` — если не используются → DELETE

**0.2 Устранить дублирование registers/schemas/:**
- `registers/schemas/pipeline/widget_bridge.py` → объединить с `registers/pipeline/widget_bridge.py`
- `registers/schemas/processing_tab/` → содержимое в `registers/payloads/`
- `registers/schemas/camera_tab.py` → в `registers/camera/`
- `registers/schemas/` → DELETE после переноса

**0.3 Файлы-одиночки:**
- `camera_policy.py` (корень) → проверить дубликат с `registers/camera/policy.py`
- `registers/producer.py`, `registers/aggregator.py` → в подходящие поддиректории

**0.4 Deprecated:**
- `AppConfig.processor` property → удалить
- `config/logging.py` (23 стр.) → встроить в `config/app.py`

**0.5 Канонические импорты:**
- `from state_store.X` → `from multiprocess_prototype.state_store.X` (~40 замен)

**0.6 Тесты в одно место:**
- `registers/system_topology/tests/` → `tests/unit/registers/`
- `frontend/models/sections/tests/` → `tests/unit/frontend/`

**Результат:** ~2,500 строк удалено, порядок в файлах

---

### Фаза 1: Подключение StateStore

**StateStoreManager** — зрелая серверная подсистема с 7 IPC-командами. Дополняет Registers:
- **Registers** = что МОЖНО настроить (Pydantic-схемы)
- **StateStore** = что ПРОИСХОДИТ сейчас (runtime: статусы, FPS, drops, pipeline state)

**Что делаем:**
1. `ProcessManagerProcessApp._setup_state_store()` → создать StateStoreManager
2. Bootstrap: `build_initial_state(app_config.to_dict())`
3. Подключить middleware (validation, throttle)
4. Проверить StateProxy в процессах end-to-end
5. НЕ удалять devtools, health, persistence — пригодятся позже

**Результат:** ~50 строк нового кода, 14K строк state_store начинают работать

---

### Фаза 2: Извлечение во фреймворк — CORE INFRASTRUCTURE (самый большой перенос)

#### 2.1 State Store → `multiprocess_framework/modules/state_store_module/` (НОВЫЙ модуль)

| Что переносим | Строк |
|---|---|
| `core/` — TreeStore, Delta, SubscriptionManager | ~1,065 |
| `manager/` — StateStoreManager, DeltaDispatcher | ~530 |
| `proxy/` — StateProxy, GuiStateProxy | ~1,035 |
| `middleware/` — base, throttle, validation, logging, metrics | ~940 |
| `selectors/` — Selector (computed views) | ~340 |
| `devtools/` — Inspector (debug browser) | ~217 |
| `health/` — Monitor (heartbeat tracking) | ~265 |
| `persistence/` — PersistenceManager (snapshot/restore) | ~370 |
| `recipes/` — RecipeEngine (snapshot engine) | ~665 |
| **Итого** | **~5,427** |

**В прототипе остаётся (🔴):**
- `bootstrap.py` (~129 стр.) — начальное дерево для бутылок
- `adapters/camera_state_adapter.py` — доменный адаптер
- `adapters/recipe_adapter.py` — доменный адаптер
- `adapters/registers_adapter.py` — доменный адаптер
- `recipes/migrations/v1_to_v2.py` — доменная миграция

#### 2.2 Frontend Base → `frontend_module/` (расширение существующего)

**Entity Editor → `frontend_module/widgets/entity_editor/`:**

| Что переносим | Строк |
|---|---|
| `base/editor/base_editor_model.py` | ~170 |
| `base/editor/base_editor_toolbar.py` | ~100 |
| `base/editor/base_editor_tree.py` | ~330 |
| `base/editor/entity_tree_widget.py` | ~565 |
| `base/editor/entity_tree_config.py` | ~70 |
| `base/editor/params_form.py` | ~380 |
| `base/editor/schema_inspector_panel.py` | ~160 |
| **Итого** | **~1,775** |

**Action Bus → `frontend_module/actions/`:**

| Что переносим | Строк |
|---|---|
| `actions/bus.py` — undo/redo, coalescing | ~200 |
| `actions/builder.py` — action builder | ~100 |
| `actions/schemas.py` — base action types | ~80 |
| `actions/persistence/` — action log, recovery, rotation | ~300 |
| **Итого** | **~680** |

**Chrome widgets → `frontend_module/widgets/chrome/`:**

| Что переносим | Строк |
|---|---|
| `widgets/chrome/` — header, recording indicator, search, overlays, side panels, watchdog, view toggle | ~800 |
| **Итого** | **~800** |

**Managers → `frontend_module/managers/`:**

| Что переносим | Строк |
|---|---|
| `managers/window_manager.py` — window lifecycle | ~240 |
| `managers/theme_manager.py` — QSS management | ~200 |
| `managers/theme_presets_manager.py` — presets | ~120 |
| `managers/settings_yaml_store.py` → `YamlPersistenceStore[T]` | ~133 |
| `managers/recipe_manager.py` → `ConfigSnapshotManager` | ~100 |
| `managers/recipe_manager_protocol.py` — protocol | ~50 |
| `managers/settings_profile_protocol.py` — protocol | ~50 |
| `managers/access_context.py` — permission checking | ~80 |
| `managers/display_router.py` — display routing | ~450 |
| **Итого** | **~1,423** |

**Other generic → framework:**

| Что переносим | Куда | Строк |
|---|---|---|
| `styles/` — QSS themes, schemas | `frontend_module/styling/` | ~400 |
| `threads/` — Qt worker thread helpers | `frontend_module/core/threads/` | ~150 |
| `utils/qt_thread_guard.py` | `frontend_module/core/` | ~50 |
| `models/` (generic Qt models) | `frontend_module/models/` | ~300 |
| `app_context.py` — DI container | `frontend_module/core/` | ~100 |
| `diagnostics.py` — UI diagnostics | `frontend_module/core/` | ~80 |
| **Итого** | | **~1,080** |

**В прототипе остаётся (🔴):**
- `widgets/pipeline/` — pipeline editor (доменный)
- `widgets/processing/` — cropped regions, post-processing
- `widgets/recipes/` — recipe UI
- `widgets/settings/` — settings tab
- `widgets/sources/` — camera/region editors
- `widgets/tabs_setting/` — configuration tabs
- `windows/` — main/loading windows (доменная компоновка)
- `managers/camera_registry.py` — доменный
- `managers/app_recipe_aggregate.py` — доменный
- `configs/frontend_config.py` — доменный
- `coordinators/logical_cameras.py` — доменный
- `launcher.py` — разбить (Фаза 4), доменная часть остаётся
- `bridges/` — доменная связка
- `commands/` — доменные команды
- `actions/handlers/` — доменные обработчики

#### 2.3 Chain/DAG Engine → `multiprocess_framework/modules/chain_module/` (НОВЫЙ модуль)

| Что переносим | Строк |
|---|---|
| `services/processor/chain/runnable.py` — step abstraction | ~100 |
| `services/processor/chain/dag_runnable.py` — DAG executor | ~200 |
| `services/processor/chain/parallel_runnable.py` — parallel steps | ~150 |
| `services/processor/chain/thread_pool.py` — thread pool | ~200 |
| `services/processor/chain/autofill.py` — I/O wiring | ~100 |
| `services/processor/chain/builder.py` → generic part | ~150 |
| `services/processor/worker_pool/protocol.py` | ~50 |
| `services/processor/worker_pool/dispatcher.py` → generic part | ~100 |
| `services/metrics/latency.py` — latency tracking | ~100 |
| **Итого** | **~1,150** |

#### 2.4 SHM Ring Buffer → `shared_resources_module/` (расширение)

| Что переносим | Строк |
|---|---|
| `backend/shm/ring_buffer.py` — generic ring buffer | ~200 |
| `backend/shm/registry.py` → generic SHM registry | ~150 |
| `backend/shm/cleanup.py` → generic cleanup | ~100 |
| **Итого** | **~450** |

---

### Фаза 3: Тесты — перенос вслед за кодом

Тесты для перенесённых модулей переезжают во фреймворк:
- `state_store/tests/` — тесты core, manager, middleware, proxy, selectors, devtools, health (~7,000 стр.)
- Доменные тесты (adapters, bootstrap) остаются в прототипе (~2,000 стр.)
- Frontend тесты для generic виджетов → framework

---

### Фаза 4: Launcher cleanup + frontend reorganization

- `frontend/launcher.py` (456 строк монолит) → разбить на:
  - `launcher/ui_builder.py` — построение UI (generic часть → fw)
  - `launcher/register_binder.py` — привязка регистров (generic → fw)
  - `launcher/hooks_setup.py` — доменная конфигурация (остаётся)

---

### Фаза 5: SYSTEM_SPEC.md — документ для реверс-промтинга

Создать `multiprocess_prototype/SYSTEM_SPEC.md`:

```
1. Архитектура
   - Карта процессов (camera → processor → renderer → GUI + DB + robot)
   - Диаграмма потока данных
   - IPC контракты
   - Три системы данных: ConfigStore (запуск), Registers (UI-схемы), StateStore (runtime)

2. Доменная модель
   - Camera domain (регистры, конфиг, бэкенд, сервис, UI)
   - Processor domain (операции, chain, pipeline, topology)
   - Renderer / Database / Robot domains

3. Файловая карта (ядро реверс-промтинга)
   Для каждого домена:
   - Schema/Register файлы → что определяют
   - Process файлы → что делают
   - Service файлы → бизнес-логика
   - UI widget файлы → что рендерят
   - Перекрёстные ссылки: «изменение X требует обновления Y»

4. Система конфигурации
   - AppConfig → как собираются процессы
   - Settings profiles → YAML persistence
   - Recipes → snapshot/restore
   - State Store → реактивное дерево состояния

5. Frontend архитектура
   - Launcher flow
   - Иерархия виджетов (tab → panel → control)
   - Action bus (undo/redo)
   - Register binding
   - Display routing

6. Гайды по изменениям (ключевое для реверс-промтинга)
   - «Добавить новый тип камеры» → файлы: X, Y, Z
   - «Добавить новую CV операцию» → файлы: ...
   - «Добавить новый тип процесса» → файлы: ...
   - «Изменить pipeline editor» → файлы: ...
   - «Изменить persistence» → файлы: ...
   - «Добавить новый плагин» → файлы: ...

7. Инварианты и правила
   - Dict at Boundary
   - Register-driven UI
   - Framework vs prototype boundary
```

---

## Итоговое влияние

| Метрика | До | После |
|---|---|---|
| **Строк прототипа (production)** | ~45,300 | **~10,000** (78% reduction) |
| **Строк тестов прототипа** | ~23,400 | ~7,000 |
| **Мёртвый код удалён** | 0 | ~2,500 |
| **Код перенесён в fw** | 0 | **~12,800** |
| **Тесты перенесены в fw** | 0 | ~7,000 |
| Конфиг-систем | 3 (StateStore disconnected) | 3 (все подключены) |
| Import violations | ~40 | 0 |
| SYSTEM_SPEC | нет | есть |

### Что остаётся в прототипе (~10K строк):

| Компонент | Строк | Что содержит |
|---|---|---|
| **registers/** | ~3,700 | Все доменные схемы (камера, процессор, рендерер, pipeline, topology) |
| **services/** (domain) | ~2,300 | CV-операции, камера-бэкенды, рендеринг, робот, БД |
| **backend/** (domain) | ~1,900 | Конфиги процессов, доменные адаптеры, command handlers |
| **frontend/** (domain widgets) | ~1,700 | Pipeline editor, sources tab, processing tab, settings |
| **config/** | ~400 | AppConfig, profiles, SHM specs |
| **state_store/** (domain) | ~400 | bootstrap, adapters, migrations |
| **entry points** | ~200 | main.py, run.py |

### Что добавляется во фреймворк:

| Новый модуль fw | Строк | Что содержит |
|---|---|---|
| `state_store_module/` | ~5,400 | TreeStore, Delta, StateStoreManager, StateProxy, middleware, selectors, devtools, health, persistence, recipes |
| `chain_module/` | ~1,150 | DAG executor, parallel steps, thread pool, worker pool protocol |
| `frontend_module/` (расширение) | ~5,760 | Entity editor, action bus, chrome, managers, styles, threads, models |
| `shared_resources_module/` (расширение) | ~450 | Ring buffer, SHM registry, cleanup |
| **Итого** | **~12,760** | |

---

## Ключевые файлы для модификации

| Файл | Фаза | Действие |
|---|---|---|
| `frontend/widgets/_archive/` | 0 | DELETE |
| `registers/schemas/` | 0 | Merge + DELETE |
| `camera_policy.py` (корень) | 0 | Merge с `registers/camera/policy.py` |
| `backend/processes/process_manager/process.py` | 1 | Подключить StateStoreManager |
| `state_store/core/`, `manager/`, `proxy/`, `middleware/`, `selectors/`, `devtools/`, `health/`, `persistence/`, `recipes/` | 2 | → `multiprocess_framework/modules/state_store_module/` |
| `frontend/widgets/base/editor/` | 2 | → `frontend_module/widgets/entity_editor/` |
| `frontend/actions/` (generic) | 2 | → `frontend_module/actions/` |
| `frontend/widgets/chrome/` | 2 | → `frontend_module/widgets/chrome/` |
| `frontend/managers/` (generic) | 2 | → `frontend_module/managers/` |
| `frontend/styles/` | 2 | → `frontend_module/styling/` |
| `services/processor/chain/` | 2 | → `multiprocess_framework/modules/chain_module/` |
| `backend/shm/` | 2 | → `shared_resources_module/` |
| `frontend/launcher.py` | 4 | Разбить на части |
| `SYSTEM_SPEC.md` | 5 | Создать |

## Верификация

После каждой фазы:
1. `python scripts/validate.py` — структурная валидация
2. `python scripts/run_framework_tests.py` — тесты фреймворка
3. `pytest multiprocess_prototype/tests/ -v` — тесты прототипа
4. `python multiprocess_prototype/run.py` — GUI запускается
5. Проверка импортов: `python -c "from multiprocess_prototype.main import *"`
