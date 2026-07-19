# multiprocess_prototype — STATUS.md

> Обновлено: 2026-07-18 (Ф2 frontend-constructor — граница фронт/бэк)
> Активный прототип Inspector_bottles.

## Что это

Активный прототип системы инспекции (только сюда вносить app-specific изменения).
Композирует framework + Services + Plugins под конкретное приложение Inspector_bottles.
Слой импортов: `multiprocess_framework → Services → Plugins → multiprocess_prototype`.

## Ключевые пути

- `main.py` — точка входа (config-driven bootstrap)
- `frontend/app.py` — главное окно (6 вкладок)
- `backend/config/` — конфиги (system.yaml, displays.yaml, user_overrides.yaml)
- `backend/routing/` — FrameRouter helper (см. ADR-133); `frame_router_setup.py` с `subscribe_to_camera/unsubscribe_from_camera`
- `backend/state/` — application state adapters (наследуют framework StateAdapterBase)
- `backend/displays/` — `blueprint_binding.py` — bind DisplayRegistry → SystemBlueprint
- `recipes/` — конкретные рецепты как данные + `manager.py` (обёртка над RecipeEngine) + `migrations/format_v1_to_v2.py`
- `registers/` — application-схемы регистров

## Состояние вкладок

| Вкладка | Статус | Phase | Ключевые файлы |
|---------|--------|-------|----------------|
| Процессы | production | Phase 1 | `frontend/widgets/tabs/processes/` |
| Плагины | stable | Phase 2, 6 | `frontend/widgets/tabs/plugins/` |
| Сервисы | stable | Phase 3 | `frontend/widgets/tabs/services/` |
| Дисплеи | stable | Phase 4 | `frontend/widgets/tabs/displays/` |
| Рецепты | stable | Phase 5 | `frontend/widgets/tabs/recipes/` |
| Pipeline | stable | Phase 7a/7b | `frontend/widgets/tabs/pipeline/` |

## Зависимости от framework-модулей

- `process_module` + `process_manager_module` — оркестрация процессов
- `service_module` (Phase 3) — ServiceRegistry, IService, @register_service
- `display_module` (Phase 4) — DisplayRegistry, DisplayEntry, YAML persist
- `state_store_module` — реактивный StateStore + RecipeEngine
- `chain_module` — pipeline DAG-executor
- `shared_resources_module` — IPC + SHM (MemoryManager, ConfigStore)
- `router_module` — broadcast routing (RouterManager.register_broadcast_route)

## Конфигурационные файлы

- `backend/config/system.yaml` — основной конфиг с секцией `discovery` (`plugin_paths`, `service_paths`)
- `backend/config/displays.yaml` — данные дисплеев (источник истины для DisplayRegistry)
- `backend/config/user_overrides.yaml` — пользовательские overrides (опционально)

## Точка входа

Ф2 frontend-constructor (2026-07) развёл фронт/бэк на уровне composition root: **два
режима запуска**, headless по умолчанию.

**Headless (backend-only, по умолчанию)** — always-on инфра (`devices`) + pipeline,
без окна:
```bash
python -m multiprocess_prototype.main
```
или
```bash
python multiprocess_prototype/run.py
```
Явный headless-флаг (перебивает presentation, даже если та задана) — `INSPECTOR_HEADLESS=1`
или `--headless`:
```bash
python multiprocess_prototype/run.py --headless
```

**GUI (фронт, отдельная точка входа)** — тот же бэкенд + презентационный overlay
(`frontend/presentation.yaml`, процесс `gui`):
```bash
python multiprocess_prototype/frontend/run.py
```
Подробности хардкод-shell механизма — [`frontend/README.md`](frontend/README.md).

## Граница фронт/бэк (Ф2 frontend-constructor)

- `backend/topology/base.yaml` — headless-only фундамент (только `devices`); презентация
  (`gui`) вынесена в `frontend/presentation.yaml` (overlay, подмешивается ⟺ явно запрошен).
- `AppManifest.presentation: Path | None` — `None` = headless. Резолвер: `SystemBuilder.
  from_manifest(app, include_presentation=...)` — единственная точка, где решается,
  подмешивать ли overlay (`base ⊕ presentation ⊕ pipeline`).
- `backend/config/manifest.py` больше не хардкодит `frontend/styles/themes` — `styles`
  опционален (headless не читает); фронт fail-loud, если `styles` не задан.
- sentrux-инвариант `backend/* → frontend/*` = forbid (`.sentrux/rules.toml`) — backend
  не импортирует Qt-слой на уровне Python (обратное, `frontend/` форвард-импортит
  `backend.launch/config/state`, — разрешено, это хардкод-shell по определению).
- **Отложено (эстафета в В3/конструктор фронта):** dual-launcher runtime-аттач (фронт
  как отдельный ОС-процесс к живому бэкенду — грабли «два бэкенда в одном прогоне»),
  сокращение forward-импортов `frontend → backend`, реконсиляция recipe-инлайн `gui`
  (5-6 рецептов держат свой `gui` внутри — после C3/4.7 recipe-оси, вне скоупа Ф2).

## Связанные документы

- [Refactor-doc 2026-05](../docs/refactors/2026-05_prototype_skeleton.md)
- [Master plan](../plans/prototype-skeleton-2026-05/plan.md)
- [Verification report](../plans/prototype-skeleton-2026-05/verification-report.md)
- [frontend-constructor plan](../plans/frontend-constructor/plan.md) — Ф2 (граница фронт/бэк)
- [proto-frontend-carve.md](../plans/proto-frontend-carve.md) — справочная спецификация задач Ф2
