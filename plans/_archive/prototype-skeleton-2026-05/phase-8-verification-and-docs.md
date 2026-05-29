# Phase 8 — Верификация и документация

> **Master plan**: [plan.md](plan.md)
> **Branch**: `chore/verification-and-docs`
> **Дней**: 2-3
> **Зависимости**: все предыдущие фазы
> **Refs trailer**: `Refs: plans/prototype-skeleton-2026-05/phase-8-verification-and-docs.md, plans/prototype-skeleton-2026-05/plan.md`

## Шаги

### 1. Smoke

- `python scripts/validate.py`
- `python scripts/run_framework_tests.py`
- `make gate`

### 2. Sentrux

- `mcp__sentrux__session_end` (baseline зафиксирован перед Phase 0).
- Сравнить, убедиться score не упал ниже 7000.

### 3. Manual через qt-mcp (полный сценарий)

- **ProcessesTab** → `qt_find_widget` → disabled кнопки для protected.
- **PluginManagerTab** → подвкладка «Пути», добавить путь → проверить рескан. Sandbox grayscale → `qt_screenshot`.
- **ServicesTab** → запустить webcam_camera → state в RUNNING.
- **DisplaysTab** → создать 2 дисплея → preview-окна.
- **RecipesTab** → переключить рецепт → процессы перезапустились, GUI живой.
- **PipelineTab** → запустить демо → `qt_screenshot` обоих дисплеев.

### 4. Документация

- **ADR**: «ServiceRegistry», «DisplayRegistry», «Recipe = SystemBlueprint v2», «replace_blueprint», «Foundation 2026-05» (перенос из backup), «FrameRouter helper».
- `docs/refactors/2026-05_prototype_skeleton.md` — что собрано, как мигрировать.
- Обновить `multiprocess_prototype/STATUS.md`, `Services/STATUS.md`, `multiprocess_framework/MODULES_STATUS.md` (новые модули service_module, display_module).

### 5. Memory

- Обновить `project_processes_tab.md` (protection done).
- Создать:
  - `project_service_registry.md`
  - `project_display_registry.md`
  - `project_recipes_manager.md`
  - `project_pipeline_demo.md`

## Acceptance

- Все smoke зелёные, sentrux score ≥ 7000.
- Все 6 вкладок прошли manual-сценарий через qt-mcp.
- ADR-ки опубликованы в `multiprocess_framework/DECISIONS.md`, refactor-doc создан.
- Memory обновлена в обоих местах (dual-write: `~/.claude/.../memory/` + `docs/claude/memory/`).
