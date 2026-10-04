---
name: SourcesTabWidget refactor handoff
description: Full context for next-chat refactoring of sources widget — architecture, bugs found, design decisions
type: project
originSessionId: 1223cca6-a6d2-4550-a4ca-364f8450e68a
---
## Состояние на 2026-04-28

SourcesTabWidget частично работает, но inline editing сломано (QTreeWidget editItem/flags/triggers конфликт). Нужен генеральный рефакторинг с чистым разделением frontend/backend.

### Что сделано
- SourceTopology schema (Layer 1) — cameras + regions
- ProcessingConfig schema (Layer 2) — processing nodes per region  
- TopologyManager в ProcessManagerProcess (фреймворк)
- diff_topologies + diff_to_commands + topology_to_process_configs
- Widget переведён на dict API (не трогает Pydantic)

### Что сломано
- QTreeWidget inline editing: конфликт setFlags/editItem/DoubleClicked triggers
- Рекурсия itemChanged → _on_item_edited (частично пофикшена через blockSignals)

### Ключевые файлы
- `multiprocess_prototype/registers/sources/schemas.py` — SourceTopology
- `multiprocess_prototype/registers/processing/schemas.py` — ProcessingConfig
- `multiprocess_prototype/registers/sources/converters.py` — layers_to_pipeline
- `multiprocess_prototype/registers/sources/topology_commands.py` — diff + commands
- `multiprocess_prototype/frontend/widgets/tabs_setting/sources_tab/widget.py` — виджет (нужен рефакторинг)
- `multiprocess_framework/modules/process_manager_module/process/topology_manager.py` — TopologyManager
