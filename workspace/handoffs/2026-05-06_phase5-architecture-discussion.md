---
date: 2026-05-06
topic: Phase 5 архитектурная дискуссия — открытые вопросы (Q1-Q10), Q4 решён
machine: macOS
branch: main
---

## Session goal

Обсудить архитектуру Phase 5 (рефакторинг GenericProcess: плагины как pure functions, замена `register_message_handler` boilerplate на `process(items) -> items`). Зафиксировать в плане 8 открытых архитектурных вопросов, начать обсуждать по одному. Закрыть Q4 (backwards-compat). Обсудить регистры как control plane.

## Done

- **Контракт плагина зафиксирован как универсальный** `process(items) -> items` (после короткого захода в гибрид с `process_each` — отказались, по запросу пользователя). Опциональный декоратор `@for_each` в base.py для 1:1 плагинов как сахар. Все семантики (1:1, 1:N, N:1, batching, фильтрация) покрываются одним методом.
- **InspectorManager: ключ буфера сделан составным `(camera_id, seq_id)`** — multi-camera изоляция. Без этого seq_id=5 от cam_0 смешался бы с seq_id=5 от cam_1. Добавлен ac-criterion и edge-case в Task 5.1.
- **8 открытых архитектурных вопросов** зафиксированы как раздел `## Открытые архитектурные вопросы` в плане со статусом `[OPEN]`/`[DECIDED]`, контекстом, вариантами, влиянием на задачи, полем "Решение".
- **Q4 (backwards-compat для `register_message_handler`) → DECIDED Variant B.** Обоснование: data plane (`frame_ready`, `region_ready`, ...) полностью мигрируется на `process(items)`. Control plane (`state.changed`, `heartbeat`, `<command>`, `register_update`) остаётся через `register_message_handler` нетронутым. Чистое разделение без exception cases. Все 12 плагинов прототипа_2 мигрируются в той же фазе — нет внешних API consumers.
- **Изучены регистры** в `multiprocess_prototype/registers/` (v1, 8 доменов) и `multiprocess_framework/modules/registers_module/` (полноценный модуль фреймворка). В `prototype_v2` регистров пока нет — это пробел. Регистры = Pydantic SchemaBase + FieldMeta (UI-метаданные) + FieldRouting (маршрутизация). Один Python-класс работает на frontend и backend.
- **Регистры зафиксированы как control plane** в плане (раздел `## Регистры — control plane между frontend и backend`). Подтверждает Variant B из Q4.
- **Добавлены два новых вопроса** Q9 (per-plugin vs централизованные регистры) и Q10 (где живёт RegistersManager).
- **Добавлена Task 5.9 (DRAFT)** "Per-plugin registers integration" — зависит от решения Q9, Q10.

## What did NOT work

- **Гибрид `process_each` + `process` (item-centric внутри 1:1, list-centric для остального)** — пользователь предложил вернуться к универсальному `process(items)`. Аргумент пользователя принят: один метод проще объяснить ("когда что использовать?" — не возникает), boilerplate в простых плагинах = 2-строчный list comprehension, не страшно. **Не идти обратно к гибриду** — пользователь явно предпочёл универсальный.
- **Раннее предложение item-centric `for item in items: for plugin in plugins:`** (плагины как `process_one(item)`) — отвергнуто из-за: ломает 1:N (region_split → list[dict]), N:1 (stitcher) принципиально не вписывается, threading даёт marginal profit для cv2 (multi-process параллелизм уже есть через WorkerPoolDispatcher).
- **Идея вынести InspectorManager в отдельный модуль `multiprocess_framework/modules/inspector_manager/`** — отвергнута. Полноценный модуль (interfaces.py + README + STATUS + tests + регистрация) overkill для ~150 строк. Используется только GenericProcess. Оставлен в `process_module/generic/inspector_manager.py`. Если позже всплывёт reuse — вынесем.

## Key decisions made

- **Q4: Variant B (полная миграция data plane).** Один путь данных в GenericProcess: `IPC → Data Worker → item → InspectorManager → chain_queue → Chain Worker → process() → SHM → IPC`. Без backwards-compat кода. `register_message_handler` остаётся для control plane.
- **Контракт плагина: универсальный `process(items) -> items`** + опциональный декоратор `@for_each` в `multiprocess_framework/modules/process_module/plugins/base.py`. Не два метода в API.
- **InspectorManager в `process_module/generic/`**, не отдельный модуль.
- **Multi-camera изоляция** через составной ключ буфера `(camera_id, seq_id)`.
- **Регистры — обязательная инфраструктура для prototype_v2** (когда появится runtime-настройка плагинов). Заменят команды типа `set_hsv_range`. Источник истины frontend ↔ backend.

## Next step

**Продолжить обсуждение оставшихся открытых вопросов в плане `multiprocess_prototype/plans/phase5_data_pipeline.md`, начиная с Q9 (per-plugin vs централизованные регистры) — это естественное продолжение разговора про регистры.**

Порядок дальнейшего обсуждения (по предложению из плана):
1. Q9 — организация регистров (per-plugin vs централизованно vs гибрид)
2. Q10 — где живёт RegistersManager
3. Q2 — item schema (TypedDict / pydantic / dual)
4. Q3 — frame ownership / IPC safety (связан с Q2)
5. Q1 — routing (chain_targets / item.target / wires / гибрид)
6. Q5 — декомпозиция GenericProcess (god-class риск)
7. Q6+Q7 — backpressure + error policy (вместе)
8. Q8 — thread-safety (одна строчка docstring)

## Files changed

- `multiprocess_prototype/plans/phase5_data_pipeline.md` (+481 / -58):
  - Раздел "Новый контракт плагина" — универсальный `process(items)` + опциональный декоратор `@for_each`
  - Task 5.1 (InspectorManager) — multi-camera изоляция через `(camera_id, seq_id)`, мотивация
  - Task 5.2 — добавлен декоратор `@for_each` в шаги, расширен ac-criteria
  - Task 5.5 — простые плагины через `@for_each`, frame_counter без декоратора (нужен batching)
  - Новый раздел "Открытые архитектурные вопросы" — Q1-Q8 с вариантами и статусами
  - Q4 → DECIDED Variant B с обоснованием
  - Новый раздел "Регистры — control plane между frontend и backend" — определение, инфраструктура, связь с Q4, Q9, Q10
  - Новая Task 5.9 (DRAFT) — Per-plugin registers integration

## Контекст для быстрой ориентации на новой машине

**Где читать:** `multiprocess_prototype/plans/phase5_data_pipeline.md` — целиком. Особенно раздел "Открытые архитектурные вопросы" и "Регистры".

**Ключевые файлы для разговора про регистры:**
- `multiprocess_framework/modules/registers_module/README.md` — полное описание API
- `multiprocess_framework/modules/registers_module/core/manager.py` — RegistersManager
- `multiprocess_prototype/registers/__init__.py` — пример организации в v1 (8 доменов)
- `multiprocess_prototype/registers/processor/schemas.py` — пример схемы регистра с FieldMeta
- `multiprocess_prototype/registers/pipeline/widget_bridge.py` — пример bridge frontend ↔ backend

**Ключевые файлы для остальных Q:**
- `multiprocess_framework/modules/process_module/generic/generic_process.py` — текущий GenericProcess (для Q5, декомпозиция)
- `multiprocess_framework/modules/process_module/plugins/base.py` — контракт плагина (для Q2, Q8)
- `multiprocess_prototype/plugins/grayscale/plugin.py` — типичный плагин с register_message_handler boilerplate (для понимания что мигрируем)
- `multiprocess_prototype/plugins/capture/plugin.py` — source плагин (target routing для Q1)
- `multiprocess_prototype/plugins/region_split/plugin.py` — fan-out 1:N (для Q1, Q2)
- `multiprocess_prototype/plugins/stitcher/plugin.py` — fan-in N:1 (для Q1, Q2)

**Авто mode:** активирован в текущей сессии. Пользователь предпочитает действие планированию, минимизация interruptions.

**Языковая политика:** все ответы пользователю на русском. Технические термины (pipeline, frontmatter, RAG, ...) — английские. CLAUDE.md, agent prompts, settings.json — английские для token efficiency.
