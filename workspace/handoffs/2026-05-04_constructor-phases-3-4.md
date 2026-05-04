---
date: 2026-05-04
topic: Constructor Tab — Phases 3-4 (right panels + runtime integration)
machine: Windows
branch: main
---

## Session goal
Реализовать Фазы 3 и 4 визуального конструктора межпроцессных связей — от GUI-панелей до runtime-интеграции с ProcessManager/SHM.

## Done
- **Фаза 3 (правые панели):** ShmConfigPanel, WireInspectorPanel, ProcessPluginPanel (переиспользует ChainEditor/Catalog/ConfigPanel из ProcessesTab), QStackedWidget в widget.py, edge→wire_key маппинг в адаптере (QTimer workaround для NodeGraphQt), Save/Load Blueprint кнопки — **25 тестов**
- **Фаза 4 (runtime):** diff_wire_configs + extract_wire_commands в converters.py, _apply_wires в TopologyBridge (4-й транспорт), wire.setup/teardown/status в ProcessManagerProcess (SHM allocate + IPC wire.configure), wire.configure/deconfigure в ProcessModule (FrameShmMiddleware + RouterManager), remove_send/receive_middleware в RouterManager, WireDataBridge (QTimer polling, WireStatus enum), цвет pipes на канвасе по статусу, кнопка «Применить» — **24 теста**
- Все **73 теста** (Phase 2 + 3 + 4) зелёные
- Планы: `multiprocess_prototype/plans/phase3_constructor_right_panels.md` (DONE), `phase4_constructor_runtime_integration.md` (DONE)

## What did NOT work
- **NodeGraphQt не имеет edge_selection_changed сигнала** — workaround через QTimer.singleShot(50ms) + scene.selectedItems() для обнаружения pipe selection. Работает, но с 50ms задержкой. Альтернатива eventFilter не пробовалась.
- **NodeGraphQt pipe color API** — нет нативного set_color для pipes. Используем fallback через QPen на QGraphicsPathItem. Может сломаться при обновлении NodeGraphQt.
- **test_constructor_phase2.py ломался** после изменения GraphBuilder.build() (tuple вместо dict) — исправлено распаковкой `node_map, _addr_map = builder.build(...)` в 2 тестах.

## Key decisions made
- **Двухэтапная архитектура wire.setup:** ProcessManager аллоцирует SHM → IPC wire.configure в дочерние процессы → ProcessModule создаёт FrameShmMiddleware. Альтернатива (ProcessModule сам аллоцирует) отвергнута — SHM owner должен быть один.
- **Сосуществование hardcoded + wire-based middleware:** CameraProcess/ProcessorProcess с hardcoded FrameShmMiddleware продолжают работать; wire-based — параллельный канал. Миграция — будущие фазы.
- **SHM размеры кадра hardcoded (480×640×3):** MVP. Auto-negotiation через port types — будущее.
- **WireDataBridge — polling (не push):** ProcessManager не имеет push-уведомлений. QTimer 2s опрос + fire-and-forget wire.status.
- **ProcessPluginPanel переиспользует виджеты из ProcessesTab** — прямой импорт из конкретных модулей (не через __init__.py) чтобы избежать circular imports.

## Next step
Фаза 5 конструктора: ShmRouteNode (fan-out визуализация на канвасе — 1 вход → N выходов) + Plugin Manager Tab (каталог плагинов, lifecycle control, enable/disable, runtime метрики). Мастер-план: `~/.claude/plans/twinkling-wiggling-beacon.md`.

## Files changed

### Modified (10 files, +754 lines):
- `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py` — wire.setup/teardown/status commands
- `multiprocess_framework/modules/process_module/core/process_module.py` — wire.configure/deconfigure
- `multiprocess_framework/modules/router_module/core/_middleware.py` — MiddlewarePipeline.remove()
- `multiprocess_framework/modules/router_module/core/router_manager.py` — remove_send/receive_middleware
- `multiprocess_prototype/frontend/bridges/topology_bridge.py` — _apply_wires + SECTION_WIRES
- `multiprocess_prototype/frontend/models/system_topology_editor.py` — wires section support
- `multiprocess_prototype/frontend/widgets/tabs_setting/constructor_tab/panels/__init__.py` — exports
- `multiprocess_prototype/frontend/widgets/tabs_setting/processes_tab/blueprint_io.py` — wires round-trip
- `multiprocess_prototype/registers/system_topology/converters.py` — diff_wire_configs + extract_wire_commands
- `multiprocess_prototype/registers/system_topology/schemas.py` — WireDefinition, ShmWireConfig, SECTION_WIRES

### New files:
- `multiprocess_prototype/frontend/widgets/tabs_setting/constructor_tab/panels/shm_config_panel.py`
- `multiprocess_prototype/frontend/widgets/tabs_setting/constructor_tab/panels/wire_inspector.py`
- `multiprocess_prototype/frontend/widgets/tabs_setting/constructor_tab/panels/process_plugin_panel.py`
- `multiprocess_prototype/frontend/widgets/tabs_setting/constructor_tab/widget.py` (rewritten)
- `multiprocess_prototype/frontend/widgets/tabs_setting/constructor_tab/canvas/plugin_graph_adapter.py` (rewritten)
- `multiprocess_prototype/frontend/widgets/tabs_setting/constructor_tab/canvas/graph_builder.py` (rewritten)
- `multiprocess_prototype/frontend/bridges/wire_data_bridge.py`
- `multiprocess_prototype/tests/unit/test_constructor_phase2.py` (fixed)
- `multiprocess_prototype/tests/unit/test_constructor_phase3.py`
- `multiprocess_prototype/tests/unit/test_phase4_wire_commands.py`
- `multiprocess_prototype/tests/unit/test_phase4_wire_bridge.py`
- `multiprocess_prototype/plans/phase3_constructor_right_panels.md`
- `multiprocess_prototype/plans/phase4_constructor_runtime_integration.md`
