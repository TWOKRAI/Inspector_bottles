# mcp-backend-ctl — MCP-обёртка backend_ctl (Ф1 Task 1.7)

Проектный (BUNDLED) плагин: выставляет `backend_ctl`-driver как MCP-сервер
`backend-ctl` — инструменты `capabilities` / `get_status` / `introspect_*` /
`send_command` / `set_register` / `state_*` / `log_tail` / `events` и т.д.

- **Сервер:** [`backend_ctl/mcp_server.py`](../../../backend_ctl/mcp_server.py)
  (stdio JSON-RPC, без SDK-зависимостей), инструменты —
  [`backend_ctl/mcp_tools.py`](../../../backend_ctl/mcp_tools.py).
- **Требует живой бэкенд:** система должна быть поднята с `BACKEND_CTL=1`
  (сокет ProcessManager, порт `BACKEND_CTL_PORT`, по умолчанию 8765).
  Без бэкенда инструменты возвращают понятную ошибку — сервер не падает.
- **Гайд для агентов:** [`backend_ctl/AGENTS.md`](../../../backend_ctl/AGENTS.md).
- Command `.venv/bin/python` — серверу нужен venv проекта (импортирует
  билдеры протокола из `multiprocess_framework`).
