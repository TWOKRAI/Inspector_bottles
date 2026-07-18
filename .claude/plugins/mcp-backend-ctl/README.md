# mcp-backend-ctl — MCP-обёртка backend_ctl

Проектный (BUNDLED) плагин: выставляет `backend_ctl`-driver как MCP-сервер
`backend-ctl` — инструменты `capabilities` / `get_status` / `introspect_*` /
`send_command` / `set_register` / `state_*` / `log_tail` / `events` /
`telemetry_*` / `watch_like_gui` и т.д. (полный каталог — `tools/list`).

- **Сервер (Phase 3, на официальном MCP SDK):**
  [`backend_ctl/mcp_server_sdk.py`](../../../backend_ctl/mcp_server_sdk.py) —
  `mcp.server.lowlevel` + stdio поверх реестра
  [`backend_ctl/mcp_tools.py`](../../../backend_ctl/mcp_tools.py). Инструменты
  несут **annotations** (`readOnlyHint`/`destructiveHint`/…). Требует extra
  `ctl` (`pip install '.[ctl]'`, пакет `mcp`).
  Рукописный [`mcp_server.py`](../../../backend_ctl/mcp_server.py) — fallback без
  SDK-зависимостей (остаётся до подтверждения живого смоука SDK-версии).
- **Safety-режимы** (флаги сервера или env `BACKEND_CTL_MCP_MODE`):
  - `--read-only` — только read+subscribe; write/escalated скрыты из `tools/list`
    и блокируются; `send_command` пропускает лишь `introspect.*`/`state.get*`.
  - `--disable-destructive` — блок разрушающих (write/escalated); read+subscribe ок.
- **Требует живой бэкенд:** система должна быть поднята с `BACKEND_CTL=1`
  (сокет ProcessManager, порт `BACKEND_CTL_PORT`, по умолчанию 8765).
  Без бэкенда инструменты возвращают понятную ошибку — сервер не падает.
- **Actionable-ошибки:** неизвестный инструмент называет ближайшие имена; блок
  режимом называет доступные инструменты.
- **Гайд для агентов:** [`backend_ctl/AGENTS.md`](../../../backend_ctl/AGENTS.md).
  ADR решений — [`backend_ctl/DECISIONS.md`](../../../backend_ctl/DECISIONS.md).
- Command `.venv/bin/python` — серверу нужен venv проекта (импортирует
  билдеры протокола из `multiprocess_framework` и пакет `mcp`).
