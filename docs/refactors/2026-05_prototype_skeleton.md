# Рефактор: Prototype Skeleton 2026-05

> Дата: 2026-05-27
> Master plan: [plans/prototype-skeleton-2026-05/plan.md](../../plans/prototype-skeleton-2026-05/plan.md)

## Цель и контекст

Цель рефактора — собрать живой «конструкторский» контур приложения Inspector_bottles: шесть вкладок (Процессы → Плагины → Сервисы → Дисплеи → Рецепты → Pipeline), полностью config-driven, без параллельных источников правды. Старый прототип содержал точечные реализации без унифицированных реестров и формата рецептов; часть готового кода осталась в `multiprocess_prototype_backup/`.

Подход «framework first»: любой компонент, переиспользуемый вне конкретного приложения, переносится в `multiprocess_framework/`. Prototype потребляет framework через Protocol-контракты. Ценный код из backup переносился целиком; удалённый `PluginGraphAdapter`-слой (коммит `261b90f`) использовался только как reference (`git show 9885bb88:<path>`), не восстанавливался.

## Что было собрано (Phases 0–7b)

| Phase | Ветка | Что сделано | Коммит |
|-------|-------|-------------|--------|
| 0 — Foundation | `chore/foundation-from-backup-and-state-schema` | FrameRouter, IStateAdapter, PluginManager, state schema; перенос из backup | `bea4c72` |
| 1 — Processes protection | `feat/processes-protection` | Защита GUI+orchestrator процессов, мониторинг heartbeat/cpu/memory | `c6b9862` |
| 2 — Discovery + config paths | `feat/discovery-config-paths` | Config-driven discovery `plugin_paths`/`service_paths`, подвкладка «Пути», PluginManager hot-reload | `d405e1e` |
| 3 — ServiceRegistry | `feat/service-registry` | `service_module` в framework, `ServiceRegistry` singleton + lifecycle + scanner; ServicesTab + lifecycle кнопки | `3ed4ec4` |
| 4 — DisplaysTab | `feat/displays-tab` | `display_module` в framework, `DisplayRegistry` singleton + YAML persist; DisplaysTab CRUD + PreviewWindow | `b7fa95db` |
| 5 — RecipesManager v2 | `feat/recipes-manager-v2` | `RecipeEngine` + format v1→v2 миграция; `replace_blueprint` с snapshot+rollback; RecipesTab полное переписывание | `506308a1` |
| 6 — Plugin sandbox | `feat/plugin-sandbox` | Sandbox-прогон плагина через файл/камеру → preview; WebcamCameraService integration | `3947353e` |
| 7a — Pipeline display node | `feat/pipeline-display-node-and-io` | `DisplayNodeItem` в QGraphicsScene, `target_process` binding, graph↔blueprint сериализация | `935c2b49` |
| 7b — Telemetry + demo | `feat/pipeline-telemetry-and-demo` | Wire telemetry (`WireStatus`), плагин `blur`, demo-рецепт `demo_webcam_split_merge.yaml`, `clear_all` эмиттит `edge_removed` | `4a3b0b28` |

## Ключевые архитектурные решения

ADR хранятся в `multiprocess_framework/DECISIONS.md` (секция «Принято»):

- **ADR-128 — Foundation Phase 0**: `FrameRouter`, `IStateAdapter`/`StateAdapterBase`, `PluginManager`, `state schema` — основа конструктора.
- **ADR-129 — ServiceRegistry**: singleton через `__new__` + Lock; `IService` Protocol (runtime_checkable); хранит классы, не экземпляры (инстанцирование — ответственность application-слоя).
- **ADR-130 — DisplayRegistry**: singleton по образу ServiceRegistry; generic-контракт без vision-полей; `persist(path)` — явный аргумент; cleanup при `unregister` — только warning, фактическое освобождение SHM при рестарте ProcessManagerProcess.
- **ADR-131 — SystemBlueprint generic + параллельные yaml-секции**: `Recipe = SystemBlueprint + active_services + display_bindings`; старый формат 8 слотов с topology dict заменён на `recipe_<slug>.yaml`.
- **ADR-132 — replace_blueprint с snapshot+rollback**: атомарная замена blueprint активного рецепта; при partial failure — откат к снэпшоту.
- **ADR-133 — FrameRouter helper в prototype**: `frame_router_setup.py` с `subscribe_to_camera/unsubscribe_from_camera` живёт в `multiprocess_prototype/backend/routing/`, не в framework — Inspector-специфичная семантика `camera_id` не должна проникать в generic routing.

Локальные ADR модулей: `ADR-SVC-001/002/003` (service_module), `ADR-DM-001/002/003` (display_module).

## Новые модули фреймворка

- **service_module** — `ServiceRegistry` singleton + `IService` Protocol + `ServiceLifecycle` enum + scanner (`discover`). 91 тест. Детали: `multiprocess_framework/modules/service_module/STATUS.md`.
- **display_module** — `DisplayRegistry` singleton + YAML persist/load + `DisplayEntry`/`IDisplayRegistry`/`IDisplayChannel` Protocol. 12 тестов. Детали: `multiprocess_framework/modules/display_module/STATUS.md`.

## Новые сервисы

- **webcam_camera** в `Services/webcam_camera/` — `WebcamCameraService` реализует `IService`, декорирован `@register_service`, захватывает кадры через `cv2.VideoCapture`. Перенесён из backup в Phase 0; интеграция в ServiceRegistry в Phase 3; использован в sandbox (Phase 6) и demo-рецепте (Phase 7b). ADR-128.

## Новые плагины

- **blur** в `Plugins/processing/blur/` — OpenCV `GaussianBlur`, ~50 строк. Создан в Phase 7b для demo-рецепта; реализует стандартный Plugin Protocol из `Plugins/`.

## Демо-рецепт

`multiprocess_prototype/recipes/demo_webcam_split_merge.yaml` — полный end-to-end контур:

```
webcam_camera → resize → region_split
    ↓ (N items, target=stitcher_proc.stitcher, total_regions=N)
    ├── process A: gray + color_mask
    └── process B: negative + blur
        ↓
InspectorManager (fan-in по seq_id) → stitcher → render_overlay → display (SHM-канал)
```

## Как мигрировать рецепты v1 → v2

**v1 (старый формат)**: `recipe_N.yaml` — dict с 8 именованными слотами (`slot_0`..`slot_7`), topology описывался плоским dict `{"process": ..., "chain": [...]}`.

**v2 (новый формат)**: `recipe_<slug>.yaml` — корень файла содержит `SystemBlueprint` (секция `blueprint`) + application-секции `active_services` (список имён зарегистрированных сервисов) + `display_bindings` (id дисплея → channel_key в SHM). `SystemBlueprint` — generic, не знает о `active_services`/`display_bindings`.

**Миграция**: `multiprocess_prototype/recipes/migrations/format_v1_to_v2.py` — скрипт преобразования; принимает путь к v1-файлу, выдаёт v2-совместимую структуру. Используется `RecipeEngine` из `multiprocess_framework/modules/state_store_module/recipes/recipe_engine.py`.

Пример запуска:
```bash
python -m multiprocess_prototype.recipes.migrations.format_v1_to_v2 recipes/old_recipe_1.yaml
```

## Известные ограничения и defer-ы

Следующее **не входит** в данный рефактор (из master plan, секция «Что НЕ входит в этот план»):

- Авторизация / RBAC — `Services/auth` только зарегистрирован в ServiceRegistry, не интегрирован в GUI.
- Hot-reload плагинов **в RUNNING-процессах** — rescan каталога работает, замена кода на лету — нет.
- Drag-drop плагина из палитры прямо на процесс в ProcessesTab.
- Сохранение результатов sandbox в файл / history.
- Layout-композитор дисплеев (1x1, 2x2 в одном окне) — отложен до после MVP.
- Восстановление NodeGraphQt-слоя (текущий QGraphicsScene с Schema-Driven Ports уже работает).
- ML-фазы (PyTorch, YOLO, ONNX Runtime) — выходят за рамки скелета.

## Связанные документы

- [Verification report](../../plans/prototype-skeleton-2026-05/verification-report.md)
- [Master plan](../../plans/prototype-skeleton-2026-05/plan.md)
- [Framework DECISIONS.md](../../multiprocess_framework/DECISIONS.md)
