---
name: Constructor Phase 6 status
description: Phase 6 done — DisplayTargetNode + WireMetricsBadge overlay + ShmDashboardPanel + display combo + metrics polling
type: project
originSessionId: 15a3fe08-0b68-4a3b-9799-f43234b0e0d8
---
Constructor Phase 6 — DONE (2026-05-04).

**Wire Metrics Infrastructure:**
- WireMetrics dataclass (fps, latency_ms, buffer_fill) in WireDataBridge
- Separate metrics_changed signal (dict payload), independent from statuses_changed
- Dedicated _metrics_timer (1000ms) for wire.metrics polling (fire-and-forget)
- set_metrics_interval(ms) for configurable polling rate

**Wire Monitoring Overlay:**
- WireMetricsBadge(QGraphicsRectItem) — overlay on pipe midpoint
- Compact badge "30fps | 5.0ms | 50%" with semi-transparent background
- Auto-hidden when all metrics zero (wire inactive)
- Integrated in PluginGraphAdapter._rebuild_badges() — created per pipe on load_scene

**DisplayTargetNode:**
- Custom NodeGraphQt node (pattern: ShmRouteNode) — green background #3a5a3a
- One input port "frame", properties: display_key, display_name, fps_limit
- Generated from SECTION_DISPLAYS in GraphBuilder.build() (4-tuple now)
- Wire connect to display → auto-creates wire with target "ui_process.{key}.frame"
- Wire disconnect → auto-removes wire

**Display Combo (WireInspectorPanel):**
- QComboBox "Display:" with available displays from topology
- Selection emits wire_changed with {"display_target": key}
- Updates DisplayDefinition.source_ref in topology editor

**SHM Dashboard:**
- ShmDashboardPanel: QScrollArea with _WireMetricsRow per wire
- QProgressBar with color coding: green (<60%), yellow (60-85%), red (>=85%)
- Page index 3 in QStackedWidget, toggle via checkable "SHM" button in toolbar
- When active — selection-based page switching is paused

**Tests:** 26 new tests (Phase 6), total 172 Phase 2-6 (all green)
**Plan:** multiprocess_prototype/plans/phase6_display_monitoring.md (DONE)

**Why:** Constructor Phase 6 completes the visual monitoring layer — users see live metrics on wires and can assign streams to display windows directly from canvas.
**How to apply:** GraphBuilder.build() now returns 4-tuple (node_map, addr_wire_map, route_nodes, display_nodes). All callers updated. Master plan complete through Phase 6.
