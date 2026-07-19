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

---

## BCTL-ADR-006: flight recorder — единый read-model через detached-driver + playhead-семантика (D.4)

**Контекст.** Живая сессия отладки невоспроизводима: агент видит поток событий один
раз, «что происходило перед сбоем» после обрыва/рестарта недоступно. Нужен дешёвый
тайм-трэвел (аналог Java Flight Recorder / Chrome tracing): записать снимок + ленту
событий, потом прогрузить запись оффлайн так, чтобы `telemetry_snapshot` /
`telemetry_history` / `await_condition` / `events_page` отвечали ПО ЗАПИСИ без живой
системы. Детерминированный rr-реплей отклонён родителем (multiprocess+SHM исключают).

**Решение — «detached driver».** Реплей идёт через ТОТ ЖЕ вход, что и живой поток.
`record_load` создаёт **неподключённый** `BackendDriver` (никогда не зовём `connect()`)
и качает записанные события через `drv._emit_event(msg)` — ровно ту точку входа,
которой пользуется reader-поток транспорта. Классификация по плоскостям
(`_classify`), telemetry-ingest, подписчики, курсоры, `dropped` — всё исполняется тем
же кодом, что вживую. **Второго read-model / второго классификатора не появляется**
(тот же принцип «нет второго парсера», что у `iter_state_deltas`). Ключевой факт:
`transport.request()` на неподключённом driver'е возвращает error-dict, не бросает; а
hub/telemetry-model/подписчики создаются в `__init__` до `connect` → неподключённый
driver уже является рабочим offline read-model.

**Playhead-семантика offline-`await_condition`.** Живой await ждёт будущего; над
записью будущее — остаток ленты. Порядок: проверить условие на достигнутом состоянии
(тот же `initial_check`) → мгновенный успех; иначе прокручивать playhead (`pump` →
`_emit_event` в вызывающем потоке, подписчики синхронны — wall-clock ожидания НЕТ) до
попадания либо конца. Попадание оставляет playhead на месте (snapshot после = момент
срабатывания — это и есть тайм-трэвел: await = навигация по ленте). Конец без
попадания → `end_of_recording`-диагноз. Предикаты и `_Waiter` переиспользуются из
`conditions.setup_condition` (публичная точка) — нет второго парсера условий.
`position="end"` (дефолт) грузит всю ленту сразу (финальное состояние);
`position="start"` — только снимок, прокрутка await'ами.

**Единственная правка framework — инъектируемый `clock`.** `TelemetryReadModel`
штамповал историю `time.time()` → при реплее точки несли бы «сейчас». Аддитивный шов:
`clock: Callable[[],float]=time.time` (дефолт бит-в-бит, характеризационный пин) +
`export_history`/`import_history`. Detached-driver получает `TelemetryReadModel(clock=
player.now)` — точки истории несут ЗАПИСАННЫЕ ts.

**Границы (§5.4).** Все `record_*` = `SAFETY_READ` (бэкенд не мутируется: запись —
локальный наблюдатель hub'а, загрузка — session-локальный режим). Файлы confined:
MCP принимает ИМЯ (не путь), резолв в `BACKEND_CTL_RECORD_DIR` с валидацией (без
разделителей/`..`). PII/секреты в v1 не редактируются — dev-only, локальный файл (тот
же trust-домен, что логи); предупреждение в доках. Формат — JSONL (Dict at Boundary):
header (версия+endpoint+подписки+снимок) → событийные строки (только arrival-плоскость,
плоскостные кольца восстанавливает `_classify` при загрузке) → footer (reason ∈
{stopped, limit, disconnect, dump} + `dropped`). Файл без footer = crash → `truncated`
при загрузке, но грузится разобранное.

**Изоляция режимов.** `DriverSession.mode ∈ {live, replay}`. В replay REPLAY_SERVED
(events/events_page/telemetry_*/state_get*/system_overview[recorded]/await_condition)
обслуживаются над записью; прочие (write/IPC/subscribe) → обучающая ошибка «требует
живой системы — record_unload()», НЕ сырое «not connected». `reset()` сессии
финализирует активную запись footer'ом `disconnect` (файл не остаётся без footer'а).

**Чёрный ящик — split.** `record_dump` (one-shot: header + текущее arrival-кольцо,
`reason=dump`) входит в D.4 (~ноль цены поверх writer'а). Авто-dump на обрыв
соединения — **follow-up** (хук в teardown reader-потока + env-флаг): ценность без
обкатанного `record_load` нулевая, а поверх готового writer'а тривиальна.

**Альтернативы.** (A) отдельный `ReplayReadModel` с собственными snapshot/history/await
— отвергнуто: второй источник правды, дублирование трёх читателей + дрейф семантики
live↔offline. (Б) прогрузка записи в ЖИВОЙ driver — отвергнуто: смешение записанных и
живых событий в одних кольцах, неотличимо для читателя. (В) детерминированный rr-реплей
— отклонён родителем (multiprocess+SHM). (Г) ротация файлов записи — отвергнута: одна
запись = один конечный файл, flight-сессия коротка по природе.

**Откат.** Инструменты аддитивны, бэкенд не трогается, replay-режим session-scoped →
откат = не звать `record_*` (та же дисциплина, что `--http` D.2); FW-флаг не нужен.
Framework-шов аддитивен с дефолтами бит-в-бит.
