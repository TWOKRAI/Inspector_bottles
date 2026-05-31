---
name: project-pipeline-recipe-driven-launch
description: "Owner direction — editor produces topology, backend runs it recipe-driven, must work headless without GUI"
metadata:
  node_type: memory
  type: project
  originSessionId: 78570f3b-c446-4359-bb07-5c336d210b2c
---

Направление после transport-router-hub P2 (2026-05-31, владелец). Цель: собрать рабочую демо-цепочку (камера→split→negative/grayscale/flip→stitch→display) **в Pipeline-редакторе** и запускать оттуда — повторить и запускать.

**Архитектурная модель владельца (STRICT):**
- GUI лишь формирует **топологию** (текстовый файл). Остальное делает бэкенд.
- **Должно работать и без GUI** (headless).
- Применение топологии в основном — из **выбора рецепта**; оркестратор (главный процесс) всё собирает. Можно в реальном времени.
- В стартовых файлах (`app.yaml`/system config) указан путь к папке рецептов + **дефолтный рецепт**. В рецепте хранятся топологии.

**Как устроено сейчас (spike 2026-05-31):**
- `app.yaml` манифест: `system:`, `base:` (foundation, merge), `pipeline:` (сырая topology region_pipeline.yaml — РЕАЛЬНО запускается), `recipes:` (папка, «запуском пока не используется»).
- `main()` → `SystemBuilder.from_manifest` → `load_topology_dict(pipeline)` → `merge_topologies(base, pipeline)` → SystemLauncher. `_merge_defaults` подмешивает defaults из system.yaml.
- Рецепт v3 (`recipes/*.yaml`): топология во вложенном `blueprint:` (processes/wires) + `active_services` + `display_bindings`. Структурно blueprint == topology.

**Три разрыва (spike):**
1. ~~Launch via GUI proxy~~ — отпал под моделью владельца (бэкенд самодостаточен; `replace_blueprint` в ProcessManagerProcess готов для real-time).
2. **Параметры плагинов:** `PluginInstance.config: dict` есть, загрузка region_pipeline.yaml сворачивает плоские поля (`_fold_extra_into_config`), сохранение пишет в YAML. НО inspector (`CardsFieldFactory`) НЕ редактирует `list[dict]` (region_split.regions) / `list[str]` (stitcher.expected_regions) → собрать геометрию с нуля в GUI нельзя, только load+resave или правка YAML.
3. **Формат:** editor сохраняет recipe v3 (blueprint+display_bindings), backend грузит topology. Нужно: загрузчик recipe-aware (разворачивать `blueprint:`).

**Сделано (2026-05-31, коммит `de7331d3`):** (1) ✅ recipe-driven launch — `unwrap_recipe` в launch.py разворачивает `blueprint:`→топология; `recipes/region_pipeline.yaml` (полные параметры); `app.yaml`/`main.py` дефолт → рецепт; старый `backend/topology/region_pipeline.yaml` УДАЛЁН (рецепт = single source, восстановим из git). **Доказано вживую:** дефолтный запуск со снесённым старым файлом → дисплей кажет кадры, 0 ERROR. Headless-сборка без gui (test_pipeline_alone_is_headless). 156 backend-тестов + 4 unwrap_recipe.

**Осталось:** (2) **list[dict]-виджет** в inspector (`CardsFieldFactory`) для region_split.regions / stitcher.expected_regions — без него геометрию с нуля в GUI не задать (только load+resave/правка YAML). (3) опц. дефолт-config при drag + manifest `default_recipe` поле + GUI «сохранить как рецепт» → запуск.

Связано: [[project_priority_product_over_engine]] (продукт > движок — это оно), [[project_pipeline_node_plugin_containers]], [[project_recipes_manager]], [[project_transport_router_hub]] (P3 каналов отложен ради этого).
