---
name: SystemTopology phases status
description: Статус фаз рефакторинга SystemTopology — что сделано, что следующее
type: project
originSessionId: da6c6937-cd65-4b24-99c9-1b0b23d71e8d
---
SystemTopology refactoring — текущий статус (ветка refactor/flatten-structure).

**Phase 0** — DONE (commit 403052b): docs PyQt5 → PySide6

**Phase 1** — DONE (commit 7f21b30): schemas, editor (458 строк), 4 section views (780 строк), TopologyBridge (365 строк), 71 тест.

**Phase 2** — DONE (commit 2fc9f14):
- Task 2.1: Wiring AppContext + Launcher + TabFactory (3664444)
- Task 2.2: ProcessesTab → ProcessesSectionView + TopologyBridge (cc045da)
- Task 2.3: SourcesTab → SourcesSectionView + TopologyBridge + reorder (95f901c)
- Task 2.4: DisplayTab → DisplaysSectionView + TopologyBridge (95f901c)
- Task 2.5: PipelineTab → known_processes_provider из editor (ecb6636)
- Task 2.6: CrossTabComboBox — авто-обновляемый QComboBox (25f948f)
- Task 2.7: 49 новых тестов Phase 2 (38c28d0)
- Task 2.8: Удалены process_config_bridge.py, process_editor_model.py, register_bridge.py (2fc9f14)
- topology_editor_model.py НЕ удалён — используется в topology_tree_view.py

**Phase 3** — DONE (commit 7318bde):
- Task 3.1: system_diff_fn + system_commands_fn + configure_topology_manager (5840396)
- Task 3.2: orchestrator_class_path параметризован в spawner/launcher, ProcessManagerProcessApp создан (7318bde)
- Task 3.3: 28 тестов topology adapter (68b1a09) + 7 тестов Task 3.2 (7318bde)

Архитектурное решение: фреймворк параметризован (Вариант A), прототип передаёт свой подкласс ProcessManagerProcessApp через SystemLauncher(orchestrator_class_path=...).

**Phase 4** — PENDING: Cleanup + Documentation (Tasks 4.1-4.2).
Plan file: multiprocess_prototype/plans/phase2_system_topology_tab_migration.md (статус DONE для Phase 2).

**Why:** Unified SystemTopology — все вкладки редактируют один объект, каскадные зависимости между вкладками, три транспорта (IPC/Register/DirectAPI).
**How to apply:** При новых задачах по SystemTopology — читать план и INTEGRATION_STATUS.md.
