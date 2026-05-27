# multiprocess_prototype — STATUS.md

> Обновлено: 2026-05-27
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

```bash
python -m multiprocess_prototype.main
```
или
```bash
python multiprocess_prototype/run.py
```

## Связанные документы

- [Refactor-doc 2026-05](../docs/refactors/2026-05_prototype_skeleton.md)
- [Master plan](../plans/prototype-skeleton-2026-05/plan.md)
- [Verification report](../plans/prototype-skeleton-2026-05/verification-report.md)
