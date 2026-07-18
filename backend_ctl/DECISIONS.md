# backend_ctl — архитектурные решения (ADR)

Контрол-плейн отладки: MCP-сервер + Python-driver к живой системе через сокет
ProcessManager. Локальная BCTL-серия (модуль — tooling вне `multiprocess_framework`;
переезд в `tooling/backend_ctl/` — пост-codemod, Phase 1 плана).

---

## BCTL-ADR-001: MCP-сервер на официальном SDK ЗА реестром ToolSpec (Phase 3)

**Контекст.** Рукописный tools-only JSON-RPC сервер ([`mcp_server.py`](mcp_server.py))
работал, но не давал tool-annotations, safety-режимов и actionable-ошибок —
инструмент перерос свою «тонкость».

**Решение.** Сервер на официальном SDK ([`mcp_server_sdk.py`](mcp_server_sdk.py),
`mcp.server.lowlevel` + stdio) поверх **того же** реестра `ToolSpec`
([`mcp_tools.py`](mcp_tools.py)). SDK-адаптер (`SDKToolServer`) регистрирует
инструменты из реестра и зовёт их `handler`'ы — логика инструментов и driver не
дублируются. Имена и семантика инструментов НЕ меняются: смена стека = один файл.

**Пин версии.** Extra `ctl = ["mcp>=1.27,<1.28"]` — пин minor: SDK молодой,
minor-релизы двигают API low-level `Server` (сигнатуры `list_tools`/`call_tool`).
Ленивый импорт: без extra модуль импортируется, запуск даёт команду установки.

**Триггеры отката.** Если minor SDK ломает API — вернуть плагин на рукописный
`mcp_server.py` (одна строка в `.mcp.json`), поднять верхнюю границу пина после
проверки. Рукописный сервер НЕ удаляется до подтверждённого живого смоука
SDK-версии из Claude Code (acceptance Task 3.1).

**Альтернативы.** FastMCP (декораторы) — отвергнуто: реестр динамический
(ToolSpec), а не набор декорированных функций; low-level `Server` ложится на
реестр без переписывания инструментов.

---

## BCTL-ADR-002: класс безопасности инструмента — единый источник annotations и режимов

**Контекст.** Task 3.1 требует tool-annotations, Task 3.2 — safety-режимы.
Оба — про «насколько инструмент опасен».

**Решение.** Один источник правды — `TOOL_SAFETY` в [`mcp_tools.py`](mcp_tools.py):
класс `read` / `subscribe` / `write` / `escalated` на каждый инструмент. Из класса
**деривятся** и MCP-annotations (`readOnlyHint`/`destructiveHint`/`idempotentHint`/
`openWorldHint`), и лестница режимов. `build_registry` требует классификации
каждого инструмента — новый инструмент без класса роняет импорт (ловит дрейф).

**Режимы** (`--read-only` / `--disable-destructive`, env `BACKEND_CTL_MCP_MODE`):
enforce на сервере ДО driver'а (annotations — лишь hints клиенту). Ограниченный
режим скрывает недоступные инструменты из `tools/list`. Особый случай: в read-only
`send_command` (escalated) пропускается только для read-команд (`introspect.*` /
`state.get*`) — фильтр по аргументу `command`.

---

## BCTL-ADR-003: контракт ошибок dict + «ошибки, которые учат»

**Решение.** Driver соблюдает Dict-at-Boundary: каждый метод возвращает dict с
`success: bool` (+ `error`/`hint`), не бросает на backend-ошибках (Task 0.3).
На MCP-слое ошибка инструмента — `CallToolResult(isError=True)` (по спеке НЕ
protocol-error), с actionable-текстом ([`mcp_errors.py`](mcp_errors.py)): неизвестный
инструмент называет ближайшие имена (difflib), блок режимом называет доступные.

---

## BCTL-ADR-004: общий DriverSession — один lifecycle для обоих серверов

**Решение.** Тонкая логика жизненного цикла driver'а (lazy-connect + readiness-проба
+ durable-подписки через реконнект + watch-resume + одноразовый reconnect-report)
вынесена в [`mcp_driver_session.py`](mcp_driver_session.py)`.DriverSession`. И
рукописный, и SDK-сервер держат `DriverSession` — реализация lifecycle ОДНА, не
расходящиеся копии. После удаления рукописного сервера остаётся единственный потребитель.
