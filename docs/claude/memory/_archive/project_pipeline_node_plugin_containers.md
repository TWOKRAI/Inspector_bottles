---
name: project_pipeline_node_plugin_containers
description: Pipeline editor — node=plugin внутри process-контейнеров (не node=process)
metadata:
  type: project
---

Pipeline Editor (вкладка) перешёл с модели **нода = процесс** на **нода = плагин внутри
рамки-контейнера процесса** (план `pipeline-process-container-nodes`, Phase D, 2026-05-30,
ветка `refactor/config-driven-launch`, на момент записи НЕ закоммичено).

Ключевое:
- `node_id` плагин-ноды = `{process}.{plugin_name}` (совпадает с префиксом endpoint
  `process.plugin.port` → внешние wires мапятся на конкретные плагин-ноды). Дубликаты
  plugin_name в процессе → суффикс `#i`.
- Процесс = `ProcessContainerItem` (backdrop-рамка, z=-1, `fit_to_members`); реестры
  `GraphScene._containers` / `_members_by_process`. Контейнеры НЕ считаются в `node_count()`.
- `GraphScene.get_node(process_name)` имеет fallback → первая плагин-нода процесса
  (для reveal и совместимости тестов; НЕ полагаться на node_id==process_name).
- Внутрипроцессная цепочка плагинов = `EdgeData.implicit=True` (пунктир, не selectable/
  exportable, без edge-телеметрии).
- Инспектор показывает config ВЫБРАННОГО плагина: `NodeInspectorPanel.current_plugin_index`,
  presenter читает его в `_on_inspector_field_changed` (SetPluginConfig с правильным index).
  Сигнал `field_changed(process, field, value)` НЕ менялся (3 арга) — index идёт через панель.
- Drag плагин-ноды между контейнерами / reorder = `MovePlugin`; удаление плагин-ноды =
  `RemovePlugin` (если в процессе >1 плагина) или `RemoveProcess` (последний). Drop вне
  контейнеров → snap-back reload.

Domain НЕ менялся (MovePlugin/RemovePlugin/SetPluginConfig уже всё умели). 22 новых теста
(test_process_container/test_inspector_per_plugin/test_plugin_drag). Связано:
[[feedback_pipeline_reuse_plugins_widgets]], план `pipeline-node-process-worker` (Phase A/B).
