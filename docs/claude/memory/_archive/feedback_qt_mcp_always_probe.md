---
name: feedback_qt_mcp_always_probe
description: Always launch prototype/smoke with QT_MCP_PROBE=1 so qt-mcp can attach (port 9142)
metadata:
  node_type: memory
  type: feedback
  originSessionId: b9fd435c-64f1-47ec-9dc7-443f357cdb10
---

Владелец (2026-06-13): при любом запуске прототипа для smoke/проверки ВСЕГДА выставлять `QT_MCP_PROBE=1` — `QT_MCP_PROBE=1 python multiprocess_prototype/run.py <recipe>` (run.py сам re-exec в .venv). Это поднимает qt-mcp probe на порту 9142, чтобы делать qt_snapshot/qt_screenshot реального GUI.

**Why:** без probe нельзя визуально верифицировать сборку (а pytest-qt юнит-тесты не доказывают реальный pipeline). Связано с [[feedback_qt_mcp_smoke_verification]] и [[reference_qt_mcp_launch]].

**How to apply:** smoke делегировать tester-агенту (у него есть qt_screenshot/qt_snapshot), запуск в фоне с QT_MCP_PROBE=1, остановка по конкретному PID (не глобальный taskkill — [[feedback_no_global_taskkill]]).
