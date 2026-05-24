# Phase 0 — Foundation из backup + state schema

> **Master plan**: [plan.md](plan.md)
> **Branch**: `chore/foundation-from-backup-and-state-schema`
> **Дней**: 2-3
> **Зависимости**: —
> **Refs trailer**: `Refs: plans/prototype-skeleton-2026-05/phase-0-foundation.md, plans/prototype-skeleton-2026-05/plan.md`

## Цель

Перенести из `multiprocess_prototype_backup/` готовый код, который покрывает реальные дыры активного prototype. Это не «копировать как есть» — это адаптация под текущую архитектуру framework (Plugins/Services carve-out, ADR-120/121).

## Что НЕ нужно делать (проверено в ревью v2)

- `RingBuffer` уже в framework (`shared_resources_module/buffers/ring_buffer.py`). Файл из backup — re-export, не переносим.
- `RecipeEngine` уже в framework (`state_store_module/recipes/recipe_engine.py`, 369 строк, с миграциями и тестами). Не создавать `recipe_module/`. Используем существующий API.
- Sentrux boundaries обновлять не нужно — generic `from = "multiprocess_framework/*"` уже покрывает любые новые модули. Достаточно `mcp__sentrux__check_rules` после Phase 0 для валидации.

## Что переносим

Правило: portable инфраструктура → framework, application-specific → prototype.

### 1. FrameRouter (subscribe-паттерн) (~80 строк) — utility в shared_resources_module или prototype

- `backup/backend/routing/frame_router_setup.py` — это тонкая обёртка над существующим `RouterManager.register_broadcast_route()`. Не заслуживает нового framework-модуля.
- **Решение**: положить как `multiprocess_framework/modules/shared_resources_module/routing/frame_subscribe.py` (helpers + `IFrameSubscriber` Protocol) ИЛИ как `multiprocess_prototype/backend/routing/frame_router_setup.py` (если привязка к `camera_id` остаётся Inspector-специфичной). **Решить ADR'ом в Phase 0**.
- Phase 4 будет использовать готовый API `RouterManager.register_broadcast_route(channel, [subscribers])`.

### 2. Wrapper для RecipeEngine (~50 строк) — в prototype

- `backup/state_store/recipes/recipe_engine.py` — это доменный wrapper над framework-классом. Перенести как `multiprocess_prototype/state_store/recipes/recipe_engine.py` (просто re-export + регистрация Inspector-специфичных миграций при bootstrap).
- **Внимание**: backup-миграция `v1_to_v2.py` уже существует в backup и конвертирует `processing_blocks → nodes` (внутри рецепта). **Это НЕ та миграция, что нам нужна** в Phase 5 (формат `recipe_N.yaml → recipe_<slug>.yaml`). Backup-миграцию можно перенести как есть (она уже работает с RecipeEngine), но новую формат-миграцию пишем с нуля в Phase 5.

### 3. PluginManager (auto-discovery + hot-reload) (~250 строк) — в framework

- `backup/plugins/manager.py` → `multiprocess_framework/modules/process_module/plugins/manager.py`
- Обёртка над `PluginRegistry.discover()` с `importlib.reload`. Публичный API: `PluginManager(registry, paths).rescan() -> PluginDiscoveryResult`.

### 4. StateStore adapter pattern — в framework (паттерн) + prototype (конкретные адаптеры)

- `multiprocess_framework/modules/state_store_module/adapters/base.py` — `IStateAdapter` Protocol (`bind(state_proxy) / unbind / sync_domain_to_state / sync_state_to_domain`) и `StateAdapterBase` с шаблонами sync-циклов и signal suppression.
- `multiprocess_prototype/backend/state/adapters/{recipe,registers,service,display}_adapter.py` — конкретные реализации, наследуют `StateAdapterBase`. Большинство берётся из backup'а как референс.

### 5. State-tree schema declaration — в prototype (Inspector-специфичные имена ключей)

- `multiprocess_prototype/backend/state/schema.py` — единый файл с полной структурой ветвей: `state.processes.*`, `state.services.*`, `state.displays.*`, `state.recipes.{active,available}`, `state.plugins.{catalog,paths}`.
- Декларация делается сразу в Phase 0, даже если конкретные данные заполняются в Phases 3-5. Это контракт между фазами — каждая фаза знает где её ветка.

### 6. Service-классы — в Services/

- `Services/webcam_camera/service.py` — новый, на базе `backup/services/camera/CameraService` (адаптирован под `IService` Protocol из Phase 3).
- `Services/metrics/` — позже, если решим использовать для wire-метрик. Не в Phase 0.
- НЕ переносим: `backup/database/` (только .db), `backup/services/database/` (требует серьёзной адаптации, не блокирует MVP).

## Что НЕ переносим

- `backup/frontend/widgets/` (268 файлов) — устаревшая структура до реорга.
- `backup/plugins/cameras/`, `backup/plugins/database/` — уже перенесено в `Plugins/`/`Services/` через ADR-120/121.
- Любые удалённые Constructor-компоненты (DisplayTargetNode и др.) — используем как чертёж через `git show 9885bb88:`.

## Acceptance

- Все скрипты переноса успешно работают, файлы на новых местах, импорты починены.
- `pytest` зелёный (минимум — не сломали существующие тесты).
- ADR в `multiprocess_framework/DECISIONS.md`: «Foundation 2026-05: перенос из backup, какие модули и почему».
- Sentrux health не упал.
