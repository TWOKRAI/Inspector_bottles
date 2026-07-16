# Plan: GUI Telemetry Read-Model — «запись всегда, чтение локально, история по запросу»

- **Slug:** gui-telemetry-read-model
- **Дата:** 2026-07-16
- **Ветка:** feat/gui-telemetry-read-model (Фаза 0 допустимо hotfix-ом раньше остальных)
- **Статус:** ACTIVE
- **Реактивирует:** [`telemetry-delivery-simplification.md`](telemetry-delivery-simplification.md) Option D (был DEFERRED
  «до gate: 2-й реактивный потребитель ИЛИ замер показал боль двойного glob»). **Gate сработал 2026-07-16:**
  диагностирован шторм блокирующих подписок при открытии вкладки «Процессы» (см. Context). После Фазы 3 пометить
  telemetry-delivery-simplification как SUPERSEDED (ссылкой сюда).
- **Координация:** [`framework-layer-grouping/plan.md`](framework-layer-grouping/plan.md) — НЕ выполнять параллельно
  с его Фазой 3 (codemod переписывает импорты по всему репо). Порядок: Фаза 0 отсюда → затем либо этот план целиком,
  либо layer-grouping Инициатива 1 — по приоритету владельца, но строго последовательно.

---

## Context (диагноз 2026-07-16, доказан по коду)

Первое открытие вкладки «Процессы» всегда фризит GUI на ~5 с (теперь дольше). Корневая причина:

1. `ProcessesTab._sync_nav()` жадно создаёт панели **всех** процессов; каждый `bindings.bind()` зовёт
   `ensure_subscription(pattern)` → `StateProxy.subscribe()` → `router.request(timeout=5.0)` —
   **блокирующий IPC-раундтрип в Qt main thread** на каждый уникальный паттерн (~60–150 подряд).
2. Дедуп подписок — по **точному совпадению строки**; стартовые wildcard'ы `processes.**`/`system.**`
   (frontend/process.py) уже покрывают все пути, но точечные подписки создаются всё равно.
3. Сервер на каждый subscribe делает `_replay_initial_state` → `get_subtree("")` — **deep-copy всего
   дерева состояния** (state_store_manager.py:412). Растёт с размером телеметрии (Ф7, dualcam).
4. Каскад: fan-out `workers.*.status` обнаруживает runtime-воркеров по одному → полное перестроение
   WorkerTable + новые биндинги + новые блокирующие подписки на каждого.
5. Побочный налог навсегда: ~100 лишних серверных подписок → PM матчит каждую дельту против всех.

Данные при этом **уже текут** в GUI одним wildcard-потоком и лежат в `GuiStateProxy._cache` — точечные
подписки дублируют существующую доставку. История **уже пишется** плагином `telemetry_sink`
(`Plugins/io/telemetry_sink`, SQLite, семпл 5 с) — read-стороны для GUI нет.

## Принцип (кандидат в глобальный ADR)

**«Запись — всегда, чтение — локально, история — по запросу»** (паттерн вкладки «Наблюдаемость»):

- Backend публикует телеметрию постоянно (троттлинг 1 Гц), независимо от открытых вкладок.
- GUI держит **один** локальный read-model, наполняемый **одним** wildcard-потоком, оформленным при старте.
- Виджеты читают **только локально**. Инварианты (enforce тестом):
  1. GUI main thread никогда не делает блокирующий IPC (`router.request`).
  2. Открытие вкладки не создаёт серверных подписок (`state.subscribe` == 0 на открытие).
- Live ≠ история: live — из read-model (push-поток), история/графики — pull страницами из БД стока.
  Live-значения из SQLite не читаем (семпл 5 с, чужой процесс, лишний I/O-путь).

---

## Фазы

### Фаза 0 — Hotfix шторма подписок (самодостаточна, шипится отдельно и первой)

#### Task 0.1 — Coverage-check вместо строкового дедупа
**Level:** Middle+ (Sonnet) · **Assignee:** developer
**Goal:** паттерн, уже покрытый существующей серверной подпиской, не создаёт новую.
**Files:** `multiprocess_framework/modules/state_store_module/proxy/state_proxy.py` (`ensure_subscription`),
  реюз glob-матчера модуля (`core/subscription_manager` / `pattern_utils`), tests.
**Steps:** 1. В `ensure_subscription`: перед созданием проверить, покрывает ли какой-либо активный паттерн
  (`_sub_patterns` + `_pattern_sub_id`) новый паттерн (glob-накрытие: `processes.**` ⊇ `processes.X.state.fps`).
  2. Покрыт → зарегистрировать refcount на покрывающий, серверный subscribe НЕ слать.
**Acceptance:**
- [x] Открытие ProcessesTab при живых стартовых wildcard'ах → 0 исходящих `state.subscribe` (характеризационный тест) — c69ffd05
- [x] Непокрытый паттерн по-прежнему создаёт подписку (регресс-тест 5.9 «панель мертва») — c69ffd05
**Out of scope:** доставка/replay, GUI-код.

#### Task 0.2 — Fire-and-forget подписка вне main thread
**Level:** Middle+ (Sonnet) · **Assignee:** developer
**Goal:** непокрытые паттерны подписываются без блокировки вызывающего потока.
**Files:** `state_proxy.py` (`subscribe`/`_send_sync`), `frontend/state/bindings.py` (`_ensure`), tests.
**Steps:** 1. Вариант async: `subscribe(..., sync: bool = True)`; из `bindings._ensure` звать `sync=False` —
  отправка `send()` без ожидания ответа, ошибка сервера ловится логом (warning), sub_id локальный.
  2. Replay при этом приедет асинхронно штатным путём дельт — виджеты обновятся через bindings.
**Acceptance:**
- [x] Ни одного `router.request` из Qt main thread на пути `bind()` (тест с мок-router, assert по потоку) — c69ffd05
**Out of scope:** переделка `router.request` как такового.

#### Task 0.3 — Реплей по префиксу паттерна, не всё дерево
**Level:** Middle+ (Sonnet) · **Assignee:** developer
**Goal:** `_replay_initial_state` копирует только поддерево статического префикса паттерна.
**Files:** `state_store_module/manager/state_store_manager.py:395-433`, tests.
**Steps:** 1. Выделить статический префикс паттерна до первого wildcard-сегмента
  (`processes.cam.state.fps` → сам путь; `processes.**` → `processes`). 2. `get_subtree(prefix)` вместо `""`.
**Acceptance:**
- [x] Реплей эквивалентен прежнему по содержимому (характеризационный тест на матчи) — c69ffd05
- [x] Тест: подписка на узкий паттерн не вызывает копию корня (spy на `get_subtree`) — c69ffd05
**Out of scope:** формат Delta, dispatcher.

#### Task 0.4 — Дебаунс каскада runtime-воркеров
**Level:** Middle (Sonnet) · **Assignee:** developer
**Goal:** N обнаружений воркеров → 1 перестроение таблицы.
**Files:** `multiprocess_prototype/frontend/widgets/tabs/processes/_panels.py`
  (`_on_worker_discovered`/`_refresh_workers`), tests (pytest-qt).
**Steps:** 1. `_on_worker_discovered` только копит имя и взводит `QTimer.singleShot(50, ...)`
  (coalescing-флагом). 2. Однократный `_refresh_workers` по срабатыванию.
**Acceptance:**
- [x] Тест: 5 обнаружений подряд → 1 вызов `set_workers` — c69ffd05
- [x] Qt-smoke: proto + qt_snapshot, вкладка живая (правило feedback_qt_mcp_smoke_verification) — 63d59356 (WSL: инструментальный лаг ~9с)
**Verification Фазы 0 (整):** запуск `webcam_sketch`, открытие вкладки «Процессы» — без фриза
  (замер лог-таймстампом); `INSPECTOR_STALL_DUMP=1` — нет срезов >1 с в момент открытия.

> Хвост 0.4 (2026-07-16): в нативном Windows-запуске владельца открытие вкладки ~30с. Инструментирование
> (INSPECTOR_TAB_TRACE) показало: Python-конструктор вкладки быстрый, стойло в Qt C++ (show/layout/paint)
> при глубокой вложенности (панель×N процессов × QTableWidget×3 + QSS). Фикс: ленивое создание
> SingleProcessPanel (только активная панель при открытии) — 03d21058. Ожидание: первый показ строит
> 1 панель вместо 8. Верификация на нативном Windows — за владельцем.

### Фаза 1 — TelemetryViewModel: локальный read-model

#### Task 1.1 — TelemetryViewModel (владелец «снимок→виджет»)
**Level:** Senior (Opus) · **Assignee:** teamlead
**Goal:** один объект в GUI: текущие значения телеметрии + батч-сигнал обновления; питается существующим
  wildcard-потоком (delta_sink), поглощает роль `cache_snapshot`-replay.
**Files:** новый `multiprocess_prototype/frontend/state/telemetry_view_model.py`, wiring в `app.py`, tests.
**Steps:** 1. Модель: `dict[path, value]` + `updated(list[tuple[path, value]])` Qt-сигнал (батч на пачку дельт).
  2. Подключить вторым потребителем `bridge.add_state_listener` (рядом с bindings, §11.15).
  3. API чтения: `get(path)`, `snapshot(prefix)` — для открытия вкладок без ожидания дельт.
**Acceptance:**
- [x] Вкладка, созданная после публикации, видит значения сразу (тест late-binding) — 74497fdf
- [x] Ни одной серверной подписки из view-model (стартовые wildcard'ы — единственный источник) — 74497fdf

#### Task 1.2 — Кольцевые буферы для мгновенных графиков
**Level:** Middle+ (Sonnet) · **Assignee:** developer
**Goal:** последние ~10 мин ключевых метрик (fps/latency/hz) в памяти GUI для спарклайнов без похода в БД.
**Files:** `telemetry_view_model.py` (ring buffer per отслеживаемый путь, конфиг: длительность/набор префиксов), tests.
**Acceptance:**
- [x] Fixed-size deque, O(1) append; выборка диапазона для графика — 74497fdf

#### Task 1.3 — Перевод панелей «Процессов» на view-model
**Level:** Senior (Opus) · **Assignee:** teamlead
**Goal:** `_panels.py` (карточки, health, WorkerTable) читают view-model; `bindings.bind(glob)` на телеметрию
  процессов из панелей уходит.
**Files:** `processes/_panels.py`, `processes/tab.py`, tests.
**Steps:** 1. Подписка панели: один слот на `updated`, фильтрация по своим путям (как `matches_live`
  в Наблюдаемости). 2. Первичное наполнение из `snapshot()`. 3. Обнаружение runtime-воркеров — из тех же батчей.
**Acceptance:**
- [x] Открытие вкладки: 0 `state.subscribe`, 0 блокирующих IPC (инвариант-тест) — 61799b83
- [x] Live-обновления карточек/воркеров работают (qt-smoke по правилу) — 61799b83 (66 GUI-тестов, 892 suite)
**Out of scope:** остальные вкладки (devices/calibration) — мигрируют по мере надобности этим же паттерном.

### Фаза 2 — История и графики (pull из telemetry_sink)

#### Task 2.1 — Read-сторона telemetry.db
**Level:** Middle+ (Sonnet) · **Assignee:** developer
**Goal:** страничный/диапазонный доступ к `telemetry_snapshots` для GUI (паттерн RecordSource Наблюдаемости).
**Files:** новый `TelemetryHistorySource` (рядом с observability/record_source-паттерном),
  чтение SQLite read-only (`data/telemetry.db`), tests.
**Steps:** 1. `list_range(process_name, ts_from, ts_to, metrics, max_points)` c даунсемплом до max_points.
  2. Read-only подключение (`mode=ro`), отказоустойчиво к отсутствию файла.
**Acceptance:**
- [x] Диапазонная выборка с даунсемплом; отсутствие БД → пустой результат, не исключение — 0f74ec1a (25 тестов)

#### Task 2.2 — Графики в SingleProcessPanel
**Level:** Middle+ (Sonnet) · **Assignee:** developer
**Goal:** график fps/latency процесса: последние минуты — из ring buffer (Task 1.2), глубже — из Task 2.1.
**Files:** `processes/_panels.py` (+ мини-виджет графика), tests.
**Acceptance:**
- [x] Открытие графика не блокирует main thread (чтение БД — в воркере/по таймеру) — 468e698c (QThread + history_ready)
- [x] Переключение диапазона (10 мин / час / день) — 468e698c (кнопки 10м/1ч/1д)

### Фаза 3 — Cleanup + enforcement + docs

#### Task 3.1 — Вырезать дублирующий механизм
**Level:** Senior (Opus) · **Assignee:** teamlead
**Goal:** после миграции панелей: убрать `ensure_subscription` из `bind()`-пути телеметрии, убрать
  `cache_snapshot`-replay из `GuiStateBindings` (роль у view-model), снять мёртвые точечные подписки.
**Acceptance:**
- [x] Нет вызовов `ensure_subscription` из `bind()` для путей, покрытых wildcard (координация с Task 0.1) — 74d21af8 (полное удаление ensure/release из bind()-пути)
- [x] Тест-инвариант в CI: открытие каждой вкладки → счётчик `state.subscribe` == 0 — 74d21af8 (все 8 вкладок, реестр-паритет)

#### Task 3.2 — ADR + память + статусы планов
**Level:** Middle (Sonnet) · **Assignee:** tech-writer
**Goal:** зафиксировать инвариант и закрыть хвосты знаний.
**Steps:** 1. Глобальный ADR «GUI read-model: запись всегда, чтение локально, история по запросу»
  (`multiprocess_framework/DECISIONS.md` + `python -m scripts.sync`). 2. Обновить memory
  `project_webcam_sketch_freeze` (диагноз «Python ни при чём» опровергнут: блокирующий IPC в main thread).
  3. `telemetry-delivery-simplification.md` → SUPERSEDED (ссылка сюда). 4. Dual-write memory.
**Acceptance:**
- [x] ADR в индексе; memory обновлена в обоих местах; статусы планов согласованы — 0192c0a5 (ADR-131, 2 memory dual-write, SUPERSEDED)

---

## Что сознательно НЕ делаем

- **Snapshot-канал вместо дельт (полный Option D, бэкенд-часть)** — отложено ещё раз: после Фаз 0–1 двойной
  glob-матчинг перестаёт быть болью (подписок мало, биндинги локальные). Реанимировать, если замер покажет
  боль на масштабе (20 проц × 50 метрик). Текущий план даёт read-model поверх работающего потока — меньший риск.
- Live-чтение из SQLite; изменение серверной публикации/троттлинга; миграция вкладок вне «Процессов».

## Риски

| Риск | Митигация |
|------|-----------|
| Coverage-check ломает случай «wildcard ещё не подтверждён сервером» | Считать покрывающими только подтверждённые подписки; иначе fallback на async-subscribe (Task 0.2) |
| Async-subscribe теряет отказ сервера | Warning-лог + счётчик в статистику; replay приедет потоком — виджет не «мёртв», а пуст |
| Два потребителя state-потока (bindings + view-model) на переходный период | Штатный multi-subscriber (§11.15); после Фазы 3 телеметрию читает только view-model |
| Конфликт с codemod layer-grouping | Не выполнять параллельно; порядок фиксирован в шапке |
| telemetry_sink переезжает в stdlib/ (layer-grouping 2D) | Task 2.1 изолирует путь к БД в одном месте (конфиг), переезд кода истории не трогает |

## Verification (весь план)

1. Инвариант-тест: открытие каждой вкладки → 0 `state.subscribe`, 0 `router.request` из main thread.
2. Открытие «Процессов» на `webcam_sketch` < 300 мс (замер логом), stall-dump чистый.
3. Live-телеметрия карточек/воркеров живая (qt-smoke: proto + `QT_MCP_PROBE=1` + qt_snapshot).
4. График процесса строится за историю (telemetry_sink включён в рецепт) и за последние минуты (ring).
5. `python scripts/run_framework_tests.py` + тесты прототипа зелёные; sentrux не хуже baseline.
