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

---

## BCTL-ADR-005: streamable-HTTP мультиклиент — per-session lifespan (D.2)

**Контекст.** SDK-сервер работал только на stdio (одноклиентный по природе) с одним
`DriverSession` на процесс. Несколько агентов (наблюдатель/экспериментатор/ревьюер) на
одной живой системе были невозможны. Дорогая часть — per-session изоляция подписок/событий
— уже решена B.1 (курсорные плоскости) и D.1a (session-isolation на транспорте).

**Решение.** Транспорт — официальный `StreamableHTTPSessionManager` (stateful) поверх
Starlette+uvicorn, opt-in флагом `--http` (stdio — дефолт, бит-в-бит). Мультиплекс —
**per-session lifespan** (Вариант B): `build_server` принимает фабрику `SDKToolServer`;
stateful-менеджер зовёт `app.run()` на каждую MCP-сессию → lifespan создаёт СВЕЖИЙ
`SDKToolServer` (свой `DriverSession` → сокет → `session`-uuid → dotted-subscriber,
изоляция поверх D.1a) на вход и закрывает его на выход. Собственный словарь
`session_id → driver` и reaper НЕ нужны — SDK держит map сессий (`_server_instances`) и
все пути завершения (DELETE / idle-timeout / крэш), а `session_idle_timeout` заменяет
свой TTL.

**Обязательное следствие.** `call_tool` — блокирующий sync (driver ждёт сокет); диспатч
через `anyio.to_thread.run_sync` — иначе одна долгая сессия (`await_condition`/introspect)
заморозила бы event loop и ВСЕ сессии.

**Cleanup долга D.1 §12.** Выход lifespan → `DriverSession.close_graceful` (unwatch →
`unsubscribe_all` по реестру → close, всё SYNC: idle-reap отменяет cancel-scope, где
`await` недопустим). Осиротевшие durable-регистрации `backend_ctl.<sid>` снимаются на
всех штатных путях завершения. Остаток — hard-kill самого сервера (регистрации-сироты
до рестарта бэкенда; семантика безвредна, D.1 §12) → бэкенд-GC — follow-up.

**Инвариант isolation.** HTTP-режим ТРЕБУЕТ backend `session_isolation=ON` (иначе broadcast
течёт между сессиями). Сервер не может включить чужой флаг (бэкенд — отдельный процесс) →
**fail-fast probe** существующей ручкой `introspect.router_stats` при первом `ensure()`:
OFF/непрочитано → громкий отказ в каждом tool-ответе, не тихая протечка. stdio — без probe.

**Safety-режим — per-server** (argv/env на процесс), НЕ per-session: режим — доверие к
endpoint'у, не к сессии (per-session = клиент сам себе ослабляет, не security boundary).
Нужны оба режима — два инстанса сервера на разных портах (D.1-изоляция это позволяет).

**Пин SDK.** `StreamableHTTPSessionManager` присутствует в `mcp>=1.27,<1.28` (верифицировано
интроспекцией установленного пакета) — подъём границы пина BCTL-ADR-001 НЕ требуется.

**Альтернативы.** (A) свой слой `MultiSessionToolServer` со словарём `session_id→driver` —
отвергнуто: дублирует SDK-механику, требует своего reaper'а и привязки к терминации.
(Б) замена stdio на HTTP — отвергнуто: ломает текущий плагин без выгоды (аддитивно лучше).
