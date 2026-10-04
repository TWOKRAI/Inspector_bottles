---
name: Constructor Phase 6 status
description: DEPRECATED — Phase 6 компоненты удалены 2026-05 в коммите 261b90f. Сохранены ИДЕИ паттернов (raw code reference в git show 9885bb88).
type: project
originSessionId: 15a3fe08-0b68-4a3b-9799-f43234b0e0d8
---

# Constructor Phase 6 — УДАЛЕНО (2026-05)

**Status:** Все компоненты Constructor-слоя удалены в коммите `261b90f` ("chore: remove obsolete hikvision drafts and archived prototype").

**Last commit before deletion:** `9885bb88` — для просмотра raw code использовать `git show 9885bb88:<path>`.

## Удалённые файлы (все ~3300 строк)

| Файл | Строк | Путь (на 9885bb88) |
|------|-------|--------------------|
| DisplayTargetNode | 193 | `multiprocess_prototype/frontend/widgets/tabs_setting/constructor_tab/canvas/display_target_node.py` |
| WireMetricsBadge | 149 | `.../canvas/wire_metrics_badge.py` |
| WireInspectorPanel | 269 | `.../panels/wire_inspector.py` |
| ShmDashboardPanel | 201 | `.../panels/shm_dashboard_panel.py` |
| PluginGraphAdapter | 1118 | `.../canvas/plugin_graph_adapter.py` |
| GraphBuilder | 460 | `.../canvas/graph_builder.py` |

## Сохранённые ИДЕИ (стоит унаследовать при переделке)

1. **Раздельная телеметрия wire**: `WireStatus` (ACTIVE/BROKEN/IDLE/PENDING, медленный таймер ~2с) и `WireMetrics` (fps/latency_ms/buffer_fill, быстрый таймер ~1с) — два независимых канала. Не смешивать.
2. **Display = узел canvas первого класса** с одним input-портом `frame` и properties (display_key, display_name, fps_limit). Wire → display = визуальный граф.
3. **Adapter pattern**: canvas = view, topology editor = source of truth. Signal suppression context (`_block_signals()`) — для предотвращения циклов sync.
4. **Route nodes** для fan-out >= 2 — опциональная визуальная фича, не обязательная для MVP.
5. **Metrics badge** позиционируется в midpoint QPainterPath, обновляется при re-layout.

## Что НЕ переносить слепо

- **NodeGraphQt** как базу — текущий PipelineTab уже на нативном QGraphicsScene со Schema-Driven Ports (PortSchema). Не возвращаться к NodeGraphQt.
- **SECTION_DISPLAYS** как абстракцию — была экспериментальной, может быть проще через node properties.
- **PluginGraphAdapter** целиком (1118 строк) — это прототип, переписать с нуля с правильными абстракциями.
- **Auto-layout** — был базовый ярусный, может потребоваться другой алгоритм.

**Why:** Memory прямо вводила в заблуждение — план эволюции прототипа опирался на «готовый Phase 6», которого нет.
**How to apply:** При планировании любых работ с PipelineTab/DisplaysTab — НЕ ссылаться на «готовый DisplayTargetNode/WireMetricsBadge». Изучать `git show 9885bb88:<path>` как reference, но реализовывать заново на нативном QGraphicsScene.
