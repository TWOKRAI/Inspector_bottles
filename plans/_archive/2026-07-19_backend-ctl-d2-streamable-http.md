# Мини-план D.2 — Streamable-HTTP мультиклиент

- **Slug:** `backend-ctl-d2-streamable-http`
- **Родитель:** [`backend-ctl-debug-console.md`](2026-07-19_backend-ctl-debug-console.md) → Task D.2 (Phase D)
- **Ветка:** `feat/bctl-d2-streamable-http`
- **Дата:** 2026-07-19
- **Гейт-статус:** ✅ ОДОБРЕН (2026-07-19). Владелец: «давай как лучше» → приняты все пять рекомендаций Fable (§5.1 Вариант B + `anyio.to_thread`; §5.2 graceful-lifespan + idle-TTL; §5.3 аддитивно stdio+`--http`; §5.4 fail-fast isolation-probe; §5.5 per-server safety). Код разрешён. Спот-чек владельца: `StreamableHTTPSessionManager` подтверждён в установленном `mcp` (сигнатура совпала) — подъём пина не нужен.

> **Поглощён** [`plans/backend-ctl-proof-discipline.md`](../backend-ctl-proof-discipline.md) 2026-07-21 — план закрыт, этот файл в архиве. Дальнейшая работа трека backend_ctl — в поглотившем документе.

> Основа — чтение кода 2026-07-19 (все якоря `file:line` верифицированы) + **живая проверка API установленного `mcp==1.27.1`** (не docs с main: сигнатуры сняты интроспекцией пакета в `.venv`). Перед правкой перепроверить якоря — код мог сдвинуться.

---

## 1. Зачем (проблема)

SDK-сервер ([mcp_server_sdk.py:217](../../backend_ctl/mcp_server_sdk.py#L217) `_run` → `stdio_server()`) работает **только на stdio** и держит **один** `DriverSession` ([mcp_server_sdk.py:116](../../backend_ctl/mcp_server_sdk.py#L116)) → один driver → один сокет. Stdio одноклиентен по природе: второй агент (наблюдатель/экспериментатор/ревьюер) на одной живой системе невозможен.

Дорогая часть мультиклиента уже решена: B.1 (курсорные плоскости — недеструктивное чтение несколькими потребителями) и D.1a (session-isolation на транспорте — reply/push адресуются одному сокету, за флагом). D.2 — сам HTTP-транспорт + мультиплекс MCP-сессий поверх готовой изоляции. BCTL-ADR-001: «смена стека = один файл» — транспорт делает SDK.

**Обязательный долг из D.1 §12** ([backend-ctl-d1-session-isolation.md](2026-07-19_backend-ctl-d1-session-isolation.md), §12, строка про осиротевшие подписки): durable-регистрации `backend_ctl.<sid>` мёртвой сессии накапливаются на бэкенде — cleanup/TTL были out-of-scope D.1, **вход D.2**.

---

## 2. Карта текущего контура (stdio, один клиент)

1. `main` ([mcp_server_sdk.py:226](../../backend_ctl/mcp_server_sdk.py#L226)) → создаёт **один** `SDKToolServer` (mode, host, port) → `asyncio.run(_run(...))`.
2. `SDKToolServer.__init__` ([mcp_server_sdk.py:104](../../backend_ctl/mcp_server_sdk.py#L104)) → **один** `DriverSession` на весь процесс сервера; `build_registry()` — реестр ToolSpec.
3. `build_server` ([mcp_server_sdk.py:201](../../backend_ctl/mcp_server_sdk.py#L201)) → lowlevel `Server` + два async-хендлера, замкнутых на этот единственный `tool_server`. ⚠️ `call_tool` — **синхронный блокирующий** код (driver ждёт сокет) внутри async-хендлера: при stdio терпимо (один клиент), при мультиклиенте заблокирует весь event loop (§5.1).
4. `_run` ([mcp_server_sdk.py:217](../../backend_ctl/mcp_server_sdk.py#L217)) → `stdio_server()` → `server.run(read, write, init_options)` до EOF.
5. Identity per-connection (D.1): `transport.connect()` генерит `session=uuid` ([transport.py:65](../../backend_ctl/transport.py#L65)) + dotted-`_subscriber`; `_send_raw` кладёт `session` в каждое сообщение ([transport.py:168](../../backend_ctl/transport.py#L168)). Изоляция на бэкенде — за флагом `backend_ctl.session_isolation` / env `BACKEND_CTL_SESSION_ISOLATION=1` ([backend_ctl_endpoint.py:59](../../multiprocess_framework/modules/process_manager_module/process/backend_ctl_endpoint.py#L59)), default OFF/broadcast.
6. Lifecycle driver'а: `DriverSession` ([mcp_driver_session.py:28](../../backend_ctl/mcp_driver_session.py#L28)) — lazy-connect + readiness, durable-подписки через реконнект (`export_subscriptions` → replay), watch-resume, reconnect-report. Реестр намерений — `_SubscriptionRegistry` ([subscriptions.py:19](../../backend_ctl/subscriptions.py#L19), `export`/`remove`/`load`).

**Вывод:** весь мультиплекс режется в ОДНОМ файле `mcp_server_sdk.py` + graceful-cleanup в `mcp_driver_session.py`/`driver.py`. Бэкенд-транспорт (канал/адаптер/router) — **не трогаем вообще** (сделано D.1).

---

## 3. Верифицированные факты SDK (`mcp==1.27.1`, снято интроспекцией пакета)

Сверка по правилу context7 + живая интроспекция `.venv` (надёжнее docs, которые описывают main):

1. **`StreamableHTTPSessionManager` существует в пине** (`mcp.server.streamable_http_manager`), сигнатура: `(app, event_store=None, json_response=False, stateless=False, security_settings=None, retry_interval=None, session_idle_timeout=None)`. Методы: `handle_request` (ASGI), `run()` (lifespan-контекст). **Риск подъёма пина `mcp>=1.27,<1.28` — ОТСУТСТВУЕТ.**
2. **Stateful-режим:** менеджер держит `_server_instances: {mcp_session_id → transport}` и на **каждую** MCP-сессию зовёт **отдельный** `app.run(...)`. Session-id выдаёт сервер на `initialize` (header `Mcp-Session-Id`), терминация — HTTP `DELETE` либо обрыв.
3. **Встроенный idle-reaper:** `session_idle_timeout=N` — сессия без HTTP-запросов N секунд автоматически терминируется (pop + `transport.terminate()`); активность отодвигает дедлайн. Рекомендация SDK — 1800 s. Крэш сессии тоже вычищается из `_server_instances` (finally-блок раннера). **Собственный TTL/reaper писать НЕ нужно.**
4. **Ключевой хук — lifespan lowlevel-Server'а:** `Server(name, ..., lifespan=<async-ctx-фабрика>)`; `Server.run()` входит в `lifespan(self)` на каждый вызов. Так как stateful-менеджер зовёт `run()` per-session → **lifespan входит/выходит на каждую MCP-сессию**. Выход lifespan срабатывает на ВСЕ пути завершения (DELETE / idle-timeout / крэш). Хендлеры достают per-session объект через `server.request_context.lifespan_context` (поле верифицировано в `RequestContext`).
5. `TransportSecuritySettings` — серверная защита от DNS-rebinding (allowed hosts/origins); auth в SDK-клиент не нужен (dev-only localhost, D.1 §5 «отклонено заранее»).
6. `uvicorn 0.47.0` + `starlette` присутствуют в `.venv` (зависимости `mcp`); extra `ctl` в [pyproject.toml:111](../../pyproject.toml#L111) менять не требуется — проверить на чистой установке (Step 4).
7. **Ручка чтения флага изоляции уже есть:** `SocketChannel.get_info()` отдаёт `session_isolation` ([socket_channel.py:381](../../multiprocess_framework/modules/router_module/channels/socket_channel.py#L381)) → `router_manager.get_stats()["channels"]` ([router_manager.py:1090](../../multiprocess_framework/modules/router_module/core/router_manager.py#L1090)) → driver `introspect_router_stats("ProcessManager")` ([driver.py:294](../../backend_ctl/driver.py#L294)). Инвариант §5.4 проверяется существующей read-ручкой, ноль правок бэкенда.

---

## 4. «Где резать» — файлы

| # | Файл | Что сейчас | Что нужно |
|---|---|---|---|
| 1 | [mcp_server_sdk.py:104](../../backend_ctl/mcp_server_sdk.py#L104) | один `SDKToolServer`/`DriverSession` на процесс | per-session фабрика через lifespan; хендлеры берут из `request_context.lifespan_context` |
| 2 | [mcp_server_sdk.py:210](../../backend_ctl/mcp_server_sdk.py#L210) | блокирующий `call_tool` в async-хендлере | `anyio.to_thread.run_sync` — одна сессия не морозит остальные |
| 3 | [mcp_server_sdk.py:217](../../backend_ctl/mcp_server_sdk.py#L217) | только `stdio_server()` | + HTTP-раннер: `StreamableHTTPSessionManager` (stateful) + uvicorn, opt-in `--http` |
| 4 | [mcp_driver_session.py:185](../../backend_ctl/mcp_driver_session.py#L185) | `close()` = закрыть сокет (регистрации остаются на бэкенде) | `close_graceful()`: снять durable-подписки + unwatch ДО закрытия (долг D.1 §12) |
| 5 | [driver.py:198](../../backend_ctl/driver.py#L198) | `export_subscriptions` (для replay) | + `unsubscribe_all()`: обход registry → снимающая команда на каждое намерение |
| 6 | README/AGENTS.md/DECISIONS.md | описан stdio | HTTP-режим, инвариант isolation ON, BCTL-ADR-005 |

Бэкенд (`socket_channel` / `socket_bridge_adapter` / `backend_ctl_endpoint`) — **ноль правок**.

---

## 5. ⚠️ РАЗВИЛКИ ДИЗАЙНА — решение владельца ДО кода

### 5.1. Модель мультиплекса: где живёт map `mcp_session_id → DriverSession`

**Вариант A — свой слой `MultiSessionToolServer`:** словарь `mcp_session_id → DriverSession` в нашем коде, резолв на каждый `call_tool` (session-id доставать из HTTP-заголовков через `request_context.request`). **Минусы:** дублирует SDK-механику (`_server_instances` уже есть), второй источник правды по session-id, собственный reaper для чистки словаря, ручная привязка к терминации.

**Вариант B (рекомендую) — инстанс `SDKToolServer` на сессию через lifespan:** один lowlevel `Server` (хендлеры из `build_server` регистрируются один раз), но `lifespan`-фабрика создаёт **свежий** `SDKToolServer` (свой `DriverSession` → свой сокет → свой `session`-uuid → свой dotted-subscriber) на вход каждой MCP-сессии; хендлеры резолвят его из `server.request_context.lifespan_context`. Никакого собственного словаря: сопоставление сессия↔driver держит SDK (факт §3.2/3.4). Выход lifespan = гарантированная точка cleanup для ВСЕХ путей завершения. Blast-radius — один файл. `build_registry()` дёшев — можно per-session (изоляция состояния реестра бонусом); safety-mode общий (§5.5).

**Обязательное следствие (находка сверх ТЗ):** `call_tool` — блокирующий sync-код; в мультиклиенте один `await_condition`/долгий introspect одной сессии заморозит event loop и ВСЕ сессии (риск родителя §Риски «await_condition/HTTP блокируют tools/call»). Перевод диспатча на `anyio.to_thread.run_sync` — не опция, а условие честного мультиклиента. Внутрисессионная конкурентность (параллельные POST одной сессии) безопасна: `transport.request()` thread-safe (`_pending_lock`/`_write_lock`).

### 5.2. Жизненный цикл + cleanup осиротевших подписок (долг D.1 §12)

**Рекомендация — два эшелона, оба без правок бэкенда:**
1. **Graceful на выходе lifespan (обязательно):** `DriverSession.close_graceful()` — пока сокет жив: `driver.unwatch()` (если watch активен) + новый `driver.unsubscribe_all()` (обход `_SubscriptionRegistry.export()` → снимающая команда на каждое намерение: `log.tail→log.untail`, `observability.tail→…untail`, `state.subscribe→state.unsubscribe`; таблица соответствия — рядом с registry) → затем обычный `close()`. Best-effort с коротким таймаутом (бэкенд мёртв → не виснуть). Выход lifespan срабатывает на DELETE, idle-timeout и крэш сессии (факт §3.4) → долг закрыт для **всех** путей завершения MCP-сессии.
2. **TTL сессий без явного terminate — из коробки:** `session_idle_timeout` SDK (default 1800 s, env `BACKEND_CTL_HTTP_IDLE_TIMEOUT`). Собственный reaper не пишем.

**Остаточный риск (задокументировать, не чинить в D.2):** hard-kill самого процесса MCP-сервера (`kill -9`) — lifespan не выполнится; регистрации-сироты останутся на бэкенде до его рестарта. Семантика безвредна (D.1 §12: push дропаются на канале, очереди не копятся — копятся только записи регистраций). Бэкенд-GC (хук на unbind сокета → внутренние unsubscribe) потребовал бы machinery в shared push-путях, которой D.1 намеренно избегал → **follow-up**, если live покажет накопление.

**Нюанс cancel-scope:** idle-timeout завершает `app.run()` отменой scope — cleanup в `__aexit__` не должен `await`'ить в отменённом scope. `close_graceful()` — чистый sync (сокет-I/O с таймаутом) → вызывается напрямую, отмене не подвержен; кратко блокирует loop — приемлемо, закрепить комментарием + пином.

### 5.3. stdio vs HTTP

**Рекомендация — аддитивно.** stdio остаётся дефолтом (локальный Claude Code, ноль изменений для существующих потребителей `.mcp.json`); HTTP — opt-in флагом `--http` (+ `--http-bind`, default `127.0.0.1:8901`; env `BACKEND_CTL_HTTP_BIND`). Внутренне оба раннера унифицировать через lifespan-фабрику (один код-путь создания `SDKToolServer`; stdio = ровно одна «сессия»), внешне stdio — **бит-в-бит** (пин §7). Замена stdio отклонена: ломает текущий плагин без выгоды.

### 5.4. Инвариант: HTTP-мультиклиент ТРЕБУЕТ backend `session_isolation=ON`

Иначе broadcast протекает между сессиями — мультиклиент опаснее, чем его отсутствие. Сервер **не может выставить** флаг сам (бэкенд — отдельный процесс, флаг — топология его старта, D.1 §9). **Рекомендация — fail-fast probe:** в HTTP-режиме при первом `ensure()` каждой сессии driver читает флаг существующей ручкой `introspect.router_stats` (цепочка верифицирована, факт §3.7; результат кэшируется в `DriverSession`); при OFF — каждый tool-ответ отдаёт actionable-ошибку «бэкенд без session-isolation: подними с `BACKEND_CTL_SESSION_ISOLATION=1`», НЕ тихая работа с протечкой. stdio-режим — probe не делает (один клиент, back-compat). Инвариант — в README/AGENTS.md + BCTL-ADR-005.

### 5.5. Safety-режим при мультиклиенте: per-server

**Рекомендация — per-server (как сейчас: argv/env на процесс).** Режим — свойство доверия к endpoint'у, не к сессии: per-session режим означал бы, что клиент сам выбирает себе ослабление (заголовком/параметром) → это не safety boundary. Нужны одновременно наблюдатель read-only и экспериментатор full — **два инстанса сервера** на разных портах к одному бэкенду (дёшево, изоляция D.1 это уже позволяет). Per-session negotiation — отклонить.

---

## 6. Steps по файлам (по-коммитно; каждый шаг — отдельный коммит, тест — ПЕРЕД правкой)

1. **Характеризация stdio (тест-коммит):** пины текущего поведения `SDKToolServer` на fake `driver_factory` — форма `list_tools`/`call_tool`/reconnect-report; инвентаризация существующих `test_mcp_server_sdk*` (не дублировать). Эталон «бит-в-бит» для Step 2.
2. **`mcp_server_sdk.py` — lifespan-фабрика:** `build_server(...)` принимает фабрику `SDKToolServer` вместо инстанса; lifespan создаёт per-session, `__aexit__` зовёт `close_graceful()` (пока — обычный `close()`, graceful в Step 5); хендлеры — через `request_context.lifespan_context`. stdio-раннер переходит на тот же путь. Пины Step 1 — зелёные без правок.
3. **`mcp_server_sdk.py` — `anyio.to_thread`:** диспатч `call_tool` в worker-thread. Пин: два параллельных вызова двух сессий не сериализуются глобально (fake-handler со `sleep`; суммарное время < 2×sleep).
4. **`mcp_server_sdk.py` — HTTP-раннер:** `--http` / `--http-bind` / env; `StreamableHTTPSessionManager(app=server, stateless=False, session_idle_timeout=..., security_settings=<localhost>)`; Starlette-mount + `manager.run()` в lifespan приложения; uvicorn. Проверка зависимостей extra `ctl` на чистой установке. stderr-баннер режима (как stdio-баннер [mcp_server_sdk.py:251](../../backend_ctl/mcp_server_sdk.py#L251)).
5. **`driver.py` + `subscriptions.py` + `mcp_driver_session.py` — graceful-cleanup (долг D.1 §12):** `unsubscribe_all()` (registry → снимающие команды, best-effort, короткий таймаут) + `close_graceful()` (unwatch → unsubscribe_all → close). Пин: закрытие MCP-сессии снимает все durable-намерения и закрывает сокет (fake-driver записывает вызовы).
6. **`mcp_driver_session.py` — isolation-probe (§5.4):** в HTTP-режиме первый `ensure()` читает `session_isolation` через `introspect_router_stats`; OFF → `BackendUnavailable`-класс ошибки с actionable-текстом. Пин: OFF → ошибка в tool-ответе, ON → работа; stdio — probe отсутствует.
7. **Мультиплекс-пины (fake):** две MCP-сессии поверх session-manager'а в одном event loop → два разных `DriverSession`, разные `session`-uuid/dotted-subscriber; события/reply одной не попадают во вторую (fake-транспорт); idle-reap (короткий `session_idle_timeout`) → `close_graceful` вызван.
8. **Live-смоук (маркер live, как C.0):** реальный uvicorn + два `streamablehttp_client` из SDK против живого бэкенда с `BACKEND_CTL_SESSION_ISOLATION=1`: сессия №1 тейлит observability, №2 крутит регистры — взаимных помех нет (acceptance родителя); DELETE №2 → регистрации №2 сняты (проверка `introspect_router_stats`/подписочные ручки).
9. **Docs + ревью:** README/AGENTS.md (HTTP-режим, инвариант §5.4, флаги, пример `.mcp.json` c `type: http`), `DECISIONS.md` → **BCTL-ADR-005** (per-session lifespan-модель, per-server safety, инвариант isolation); `/code-review` → merge. CAPABILITIES.yaml не меняется (набор инструментов тот же).

---

## 7. Контракт-тесты (характеризация ПЕРЕД правкой)

- **stdio бит-в-бит:** пины Step 1 переживают Steps 2–4 без правок — существующие потребители (Claude Code плагин) не замечают D.2.
- **Изоляция мультиплекса — на fake-транспорте** (реальный HTTP не нужен): два `DriverSession` двух MCP-сессий не видят reply/события друг друга сквозь HTTP-слой; разные `session`/dotted-subscriber (ядро acceptance родителя).
- **Lifecycle:** закрытие MCP-сессии (DELETE и idle-reap) → `close_graceful` → unwatch + все unsubscribe отправлены + сокет закрыт + bind снят на канале (последнее уже пинится D.1 — не дублировать, сослаться).
- **Isolation-probe:** backend OFF → actionable-ошибка, не тихий broadcast; ON → пропуск; stdio — probe нет.
- **Конкурентность:** параллельные call_tool двух сессий не сериализуются глобально (to_thread); cleanup в отменённом scope не виснет.
- **Live (маркер `live`, как C.0):** Step 8 — единственный тест, требующий реального сетевого HTTP + живого бэкенда; в CI по умолчанию скипается.

## 8. Флаги/конфиг и инварианты

- **HTTP — opt-in по CLI** (`--http`), отдельного FW-флага нет: откат = не передавать флаг; stdio-путь не тронут. Это соответствует дисциплине «за флагом до доказательства» без нового реестра флагов.
- `--http-bind` default **`127.0.0.1:8901`** (env `BACKEND_CTL_HTTP_BIND`); `TransportSecuritySettings` — localhost-only (DNS-rebinding). Auth/TLS — отклонено ранее (dev-only, D.1 §5).
- `BACKEND_CTL_HTTP_IDLE_TIMEOUT` default 1800 s (рекомендация SDK).
- **Инвариант:** HTTP-режим ⇒ backend `session_isolation=ON` (enforce probe §5.4). stdio ⇒ требований нет.
- Терминология: не путать `--host/--port` (адрес **бэкенда**, существующие) и `--http-bind` (адрес **HTTP-сервера**) — зафиксировать в help/README.

## 9. Риски

| Риск | Митигация |
|---|---|
| Блокирующий driver в async-хендлере морозит все сессии | Step 3 `anyio.to_thread` — обязательный, с пином несериализации; риск родителя закрыт |
| API SDK в пине иной, чем в docs | снято: всё верифицировано интроспекцией установленного `mcp==1.27.1` (§3); подъём пина НЕ требуется |
| Cleanup в отменённом scope (idle-reap) виснет/пропускается | `close_graceful` — sync, без await; короткие таймауты; пин lifecycle |
| Осиротевшие регистрации при hard-kill сервера | безвредны по памяти (D.1 §12); idle-TTL + graceful закрывают штатные пути; бэкенд-GC — follow-up |
| HTTP при isolation=OFF → протечка между сессиями | fail-fast probe §5.4, actionable-ошибка, инвариант в ADR/README |
| uvicorn/starlette не тянутся extra `ctl` на чистой машине | проверка на Step 4; при необходимости — явно в extra |
| Внутрисессионные параллельные POST на один driver | `transport.request()` thread-safe (verified: `_pending_lock`/`_write_lock`); отметить в ADR |

## 10. Acceptance (из родителя)

- [x] **две параллельные сессии без взаимных помех** — Step 7 (fake-мультиплекс через реальный in-memory протокол) + Step 8 (live-смоук: реальный uvicorn + два `streamablehttp_client`, ПРОШЁЛ). Каждая сессия = свой driver/сокет/`session`
- [x] долг D.1 §12 закрыт: завершение MCP-сессии (DELETE/idle/обрыв) → `close_graceful` → `unsubscribe_all` снимает durable-намерения (Step 5 + end-to-end пин §7)
- [x] stdio-путь бит-в-бит прежним — 40/40 SDK-пинов зелёные на финальном HEAD (включая e2e-over-SDK)

### Прогресс D.2 (2026-07-19) — ЗАКРЫТ (ожидает merge)

Коммиты на ветке `feat/bctl-d2-streamable-http` (9 Steps + план):
1. `docs(plans)` — мини-план + гейт §5 одобрен.
2–3. `feat(tooling)` — per-session lifespan-фабрика `build_server` + `call_tool` через `anyio.to_thread`.
4. `feat(tooling)` — HTTP-раннер (`StreamableHTTPSessionManager` + uvicorn, `--http`/`--http-bind`, idle-TTL, security localhost).
5. `feat(tooling)` — graceful cleanup (`unsubscribe_all` + `close_graceful`, долг D.1 §12).
6. `feat(tooling)` — fail-fast isolation-probe (§5.4).
7–8. `test(tooling)` — мультиплекс-пин (fake) + live-смоук (реальный HTTP, ПРОШЁЛ).
9. `docs` — README/AGENTS (HTTP-режим) + BCTL-ADR-005.

**Осталось:** формальный `/code-review` → merge (owner-gated) → разблокирован остаток Phase D (D.3–D.5) и E/F.
**Follow-up (не acceptance):** бэкенд-GC осиротевших регистраций при hard-kill сервера; live-прогон против реального бэкенда с `session_isolation=ON` (obs-tail vs register-crank) — харнесс-сценарий владельца; deprecation `streamablehttp_client`→`streamable_http_client` при подъёме пина SDK.

---

## Порядок исполнения

0. **Владелец одобряет развилки §5.1–5.5.** ← гейт (код до этого не пишется)
1. Ветка `feat/bctl-d2-streamable-http` (уже создана); baseline `sentrux session_start`.
2. Step 1 — характеризация stdio (зелёная).
3. Steps 2–4 (сервер) по одному коммиту, каждый со своим пином.
4. Steps 5–6 (cleanup + инвариант) — закрытие долга D.1 §12.
5. Steps 7–8 (мультиплекс-пины + live-смоук).
6. Step 9: docs + BCTL-ADR-005 → формальный `/code-review` → `sentrux session_end` (не хуже baseline) → merge.

---

## Записка владельцу — что требует твоего слова

1. **§5.1 Модель мультиплекса.** Рекомендую **B**: инстанс `SDKToolServer` на MCP-сессию через lifespan lowlevel-Server'а — SDK сам держит map сессий и все пути завершения, наш собственный словарь+reaper (вариант A) дублировал бы его механику. Blast-radius — один файл `mcp_server_sdk.py`. Плюс обязательный перевод call_tool на worker-thread — иначе одна сессия с `await_condition` морозит остальные (это не развилка, а условие корректности).
2. **§5.2 Cleanup осиротевших (долг D.1 §12).** Рекомендую: graceful на выходе lifespan (unwatch + unsubscribe_all по registry, пока сокет жив) + встроенный idle-TTL SDK (1800 s). Покрывает DELETE/таймаут/обрыв. Непокрыт только hard-kill самого сервера — остаток безвреден (записи, не очереди), бэкенд-GC — follow-up.
3. **§5.3 stdio vs HTTP.** Рекомендую аддитивно: stdio — дефолт (Claude Code не замечает изменений, пин бит-в-бит), HTTP — opt-in `--http`, bind `127.0.0.1:8901`.
4. **§5.4 Инвариант isolation.** Сервер не может включить флаг чужого бэкенда — рекомендую fail-fast probe существующей ручкой `introspect.router_stats` (ноль правок бэкенда): HTTP-режим при isolation=OFF громко отказывает, не течёт молча.
5. **§5.5 Safety.** Рекомендую per-server: режим — доверие к endpoint'у, не к сессии (per-session = клиент сам себе ослабляет). Нужны разные режимы — два инстанса на разных портах.

Бонус-факт для решения: API streamable-HTTP **верифицирован в установленном `mcp==1.27.1`** — подъём пина BCTL-ADR-001 не требуется, риск с этой стороны снят.
