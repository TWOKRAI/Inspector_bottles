---
name: project-recipe-hotswap
description: Recipe hot-swap (replace_blueprint) — Task 1-7 DONE; Task 7 (кадры после switch) РЕШЁН (5cd23192) двухфазной регистрацией очередей, НЕ SHM
metadata:
  type: project
---

Hot-swap переключения рецепта (replace_blueprint), сессия 2026-06-06, ветка `fix/recipe-v3-engine-decouple`, план `plans/2026-06-06_replace-blueprint-hotswap.md`.

**DONE + committed (eb6f1575), все с тестами (~800 зелёных):**
- Task 1 `ProcessRegistry.stop_many()` — параллельный стоп в replace_blueprint (35с→~5с).
- Task 2 `MemoryManager.release_process_memory()` (+IMemoryManager) — close+unlink блоков + unregister PSR.
- Task 5 `_build_proc_dicts()` — raw recipe-blueprint → канонический proc_dict как boot (`SystemBlueprint.build_configs → process(cfg)`); БЕЗ этого hot-swap процессы стартовали пустыми (нет плагинов/chain_targets/queues). Камера после фикса РЕАЛЬНО поднимается (verified в логах).
- Task 6 `create_shm_blocks()` — свежая инкарнация имени при FileExistsError (Windows hot-swap, unlink no-op). Убрал «File exists camera_0_frame».
- log_dir: `INSPECTOR_LOG_DIR` env в launch.build → hot-swap процессы логируют в logs/prototype_2.
- Recipes UI: индикатор активного рецепта (`show_active_recipe`).

**Task 7 РЕШЁН (commit 5cd23192, сессия 2026-06-06, проверено live qt-mcp):**
- Симптом: после switch «Активен» меняется, но картинка замёрзшая, FPS 0. Boot любого рецепта работает (FPS 22).
- **Корень — НЕ SHM и НЕ камера** (обе гипотезы live-опровергнуты: камера release за 0.07с; producer produce() работает; ошибок `output_frames not found` в свопе НЕТ).
- Реальная причина: `replace_blueprint` step 7 собирал процессы **однофазно** (register+create+start по одному), а boot `_create_processes_from_config` — **двухфазно** (очереди ВСЕХ → старт ВСЕХ). На Windows-spawn каждый процесс держит снимок shared_resources из bundle; `camera_0` (первый в рецепте) спавнился ДО регистрации очереди `detector` → слал кадры «в пустоту» → consumer не получал → GUI замерзал.
- **Фикс:** двухфазный `replace_blueprint` (фаза 1 register_process всех очередей; фаза 2 create+start), зеркало boot. Rollback сохранён. 246 тестов зелёные, своп в обе стороны даёт кадры (FPS 22/21).
- **Метод (важно для будущего):** статикой не добивалось — нашли live-трассировкой (qt-mcp скриншоты + точечные DIAG в CapturePlugin/SourceProducer + пер-процессные логи). Гипотезы отсекались по очереди тестами, не догадками.
- Это **частный случай** плана `recipe-orchestrator-unify` (boot==switch): ad-hoc hot-swap не повторял корректную сборку boot. План диагностики — `plans/2026-06-06_frames-blocker-hotswap-resource-release.md`.

**Остаётся (не блокеры кадров):** debounce единой точки appl(Pipeline Старт/Перезапуск + Recipes Загрузить); косметический logging error (I/O on closed file при teardown). Направление — `recipe-orchestrator-unify` (`[[project_recipe_hotswap]]` → unify).

Связано: [[project_pipeline_live_control_stage1]], [[project_transport_router_hub]], [[feedback_fix_framework_forward]], [[project_pipeline_recipe_driven_launch]].
