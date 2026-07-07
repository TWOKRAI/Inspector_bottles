---
name: feedback-backend-ctl-for-agents
description: "Тестировать/отлаживать бэкенд агентам через backend_ctl (имитация фронтенд-сообщений), НЕ через запуск GUI и НЕ через qt-mcp"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 05a29a24-fbc4-4241-8e6f-a55d2a6b5db0
---

Директива владельца (2026-07-06): backend_ctl существует ИМЕННО для того, чтобы агенты
тестировали бэкенд, имитируя сообщения фронтенда, — без запуска самого фронтенда и без qt-mcp.

**Why:** driver шлёт те же router-сообщения, что GUI через CommandSender («GUI по сокету») —
это быстрее, стабильнее и не требует Qt-окружения; qt-mcp — только для проверки самого GUI.

**How to apply:** для любой проверки бэкенда (команды, state, introspect, логи) — BackendDriver
(`backend_ctl/AGENTS.md` — рецепт) или BackendHarness-фикстура (Ф1.3+); qt-mcp звать только
когда проверяется виджет/layout. После Ф1.7 — MCP-инструменты backend_ctl напрямую.
См. [[project-constructor-master-progress]].
