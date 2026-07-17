# План: backend-ctl-framework-module — контрол-плейн как модуль фреймворка

- **Slug:** `backend-ctl-framework-module`
- **Дата:** 2026-07-16 (после независимого ревью: APPROVE-с-правками 8/10, правки внесены)
- **Ветки:** Phase 0 — `feat/backend-ctl-hardening` (короткая, от текущей); Phases 1–4 — `feat/backend-ctl-module` (после codemod layer-grouping)
- **Dual-save:** при одобрении сохранить копию в `plans/backend-ctl-framework-module.md` (правило `feedback_plan_dual_save`), коммит `docs(plans):`

---

## Context

`backend_ctl` доказал ценность как отладочный контрол-плейн для агентов (MCP-сервер + Python-driver к живой системе: «GUI по сокету» через единственный хаб RouterManager в ProcessManager). Аудит 2026-07-16 (3 разведчика: код, поверхности фреймворка, веб-аналоги CDP/K8s list-watch/OTel/Grafana-MCP) показал: инструмент рабочий, но перерос свою «тонкость» и не дотягивает до GUI-паритета.

**Главные находки:**

1. **God-file `driver.py` (981 строка):** транспорт + протокол (request_id-матчинг) + event-bus + 5 датаклассов + ~30 обёрток 7 доменов в одном классе.
2. **Телеметрия недоступна агентам:** `telemetry_reconfigure`/`telemetry_set` есть в driver ([driver.py:696,751](backend_ctl/driver.py#L696)), но НЕ зарегистрированы в MCP (`grep telemetry mcp_tools.py` = 0); live-тестов на телеметрию нет вовсе.
3. **Приёмная плоскость неполна против GUI:** GUI получает `observability.record` (live ЛОГИ+ОШИБКИ+СТАТИСТИКА через `observability.tail.subscribe` + авто-переподписку `ObservabilityTailActivator`) и `state.changed` по 4 wildcard (`processes.**`, `system.**`, `devices.**`, `calibration.**`) — у driver есть только `log_tail` и ручной `state_subscribe`. SHM/memory-интроспекции нет ни у кого (фреймворк умеет `MemoryManager.get_stats()`/`ShmRegistry`/`loan_ledger.snapshot_stats()`, команды нет).
4. **Баги:** реконнект MCP-сервера молча теряет подписки (события останавливаются без ошибки — ежедневная боль); гонка `close()`/`request()` (assert на `_sock`); поздние ответы после таймаута всплывают как псевдо-события; порт 8765 захардкожен в 5 местах (+8791 в `g7_fault_probe`); нестабильный конверт ответов (костыли `_find_payload`/`_leaf_result`); контракт ошибок то dict, то raise; harness мутирует глобальный `os.environ` без восстановления; `time.sleep` как readiness.
5. **Гигиена:** нет STATUS.md/DECISIONS.md/interfaces.py (правило проекта №2); 6 ad-hoc probe-скриптов в корне пакета; README/AGENTS не знают о телеметрии; тесты лезут в приватные `_dispatch`/`_port`.

**Решения владельца (2026-07-16):**
- backend_ctl становится частью `multiprocess_framework`. Имя `backend_ctl` сохраняется.
- MCP-слой — на **официальный MCP Python SDK** (пакет `mcp`, extras по образцу `modbus`; установку выполняет владелец — правило `feedback_package_install_by_user`).

**Итоги независимого ревью (Opus, 2026-07-16):** APPROVE-с-правками 8/10. Внесено:
- Размещение: **`multiprocess_framework/tooling/backend_ctl/`** — новый ВЕРХНИЙ слой пост-codemod раскладки layer-grouping (не `modules/backend_ctl_module/`, не `application/`). Создаётся ПОСЛЕ codemod — без 27-й записи в rename-таблице, без двойного переписывания шимов и entrypoint.
- Точка A с coherence оказалась ложной: Task 1.1 (единственный, трогавший driver.py) уже смержен (92d6f6f6); Tasks 1.2+/2.x/3.x coherence файлы backend_ctl НЕ трогают. Реальный гейт извлечения — codemod layer-grouping.
- Дешёвый ежедневный win — MCP-регистрация УЖЕ существующих telemetry-методов — вынесен в Phase 0 (Task 0.5) на текущий рукописный реестр, не ждёт SDK.
- Cursor-дренаж и пагинация (бывш. 3.3/3.4) понижены до опциональной поздней итерации (приоритет владельца: продукт важнее красоты движка).
- Read-model (2.3): сначала проверить переиспользование generic `TelemetryViewModel` из `frontend_module` (появится после coherence Task 3.5), не плодить второй класс.

**Жёсткие ограничения:**
- Слои импортов: framework НЕ импортирует прототип → generic harness с инъекцией `launcher_factory`; прототип-глю остаётся в top-level `backend_ctl/`.
- Кадры/SHM через сокет не гоняем (Dict at Boundary) — только статистика.
- Два import-rewrite-рефактора (извлечение backend_ctl и codemod layer-grouping) НЕ параллелятся.

---

## Сейчас → Будет (понятным языком) + честная оценка

**Сейчас** агент, отлаживая систему, может: слать команды любому процессу, читать/писать state, ловить лог-tail и клики GUI (ui_tap). Но: телеметрию можно крутить только Python-сниппетом (в MCP инструментов нет); live-поток ОШИБОК и СТАТИСТИКИ агенту недоступен вообще (его получает только GUI); заглянуть в память/SHM/пул нельзя ничем; если MCP-сервер переподключился к бэкенду — все подписки молча умирают (события просто перестают приходить, агент думает «всё тихо»); внутри — файл на 981 строку, где всё смешано, порт продублирован в 5 местах, ошибки то dict, то исключение.

**После Phase 0 (можно начинать сразу, параллельно с телеметрией; ~4–5 задач):** исчезают все известные баги — подписки переживают реконнект, гонок нет, «мёртвые» ответы не мусорят события; телеметрия появляется в MCP (агент крутит частоты/метрики без Python-сниппетов). Это «ежедневный выигрыш» без ожидания больших рефакторингов.

**После Phases 1–4 (после вливания телеметрии и перегруппировки фреймворка):** backend_ctl — полноценный модуль фреймворка в слое `tooling/`, агент = полноправная замена GUI: одна команда `watch_like_gui()` — и агент видит ВСЁ, что видит GUI (state, логи, ошибки, статистика, телеметрия с историей), плюс то, чего GUI не умеет (`introspect.memory` — память/SHM/очереди). MCP на официальном SDK: у инструментов пометки «только чтение/разрушающий», режим read-only для безопасных сессий, ошибки подсказывают «такой команды нет, есть вот эти».

**Честная оценка (0–10):**

| Ось | Сейчас | После Phase 0 | После всего | Почему |
|---|:--:|:--:|:--:|---|
| Что агент видит/может (плоскости) | 5 | 6 | **9** | сейчас: команды/state/логи есть, телеметрия без MCP, ошибки/статистика live — нет, память — нет |
| Надёжность (баги) | 4 | **8.5** | 9 | тихая потеря подписок — худший баг: агент не знает, что ослеп |
| Архитектура/поддерживаемость | 4 | 5 | **8.5** | god-file, дубли, приватные доступы; станет: слои, interfaces, домены |
| Качество MCP (каталог/безопасность/ошибки) | 5 | 6.5 | **9** | рукописный протокол без annotations/safety; станет SDK + read-only + actionable-ошибки |
| Оформление как модуль (доки/тесты/правила проекта) | 5 | 5.5 | **9** | нет STATUS/DECISIONS/interfaces, probe-мусор, нет live-теста телеметрии |
| Замена GUI (полнота паритета) | 6 | 6 | **9** | отправка уже паритетна (общие билдеры), приём — половинчат |
| **Итого (среднее)** | **~4.8** | **~6.3** | **~8.9** | честно: не «сломано», а «хороший инструмент, переросший свой каркас» |

Потолок не 10: без streamable HTTP (несколько агентов одновременно) и cursor-дренажа (отложены сознательно) — это следующая итерация, если появится реальная потребность.

---

## Глобальный порядок трёх планов (главный вывод ревью)

| Этап | Что | Почему здесь | Sync / freeze |
|---|---|---|---|
| **1 (сейчас, параллельно)** | coherence Фаза 1 (в работе) ∥ **backend_ctl Phase 0** (`feat/backend-ctl-hardening`) | Phase 0 не трогает telemetry-семантику; coherence больше не трогает файлы backend_ctl → безопасный параллелизм (разные файлы). Phase 0 закрывает ежедневную боль (потеря подписок при реконнекте) + даёт telemetry в MCP немедленно | Оба в main ДО codemod; макс 2 агента без worktree |
| **2** | coherence Фазы 2–3 до конца | Жёсткая последовательность 1→2→3 плана coherence | coherence полностью в main → конфликт по `builtin_commands.py` (Task 2.4) исчезает |
| **3 (FREEZE)** | layer-grouping Инициатива 1 (codemod: 26 модулей → 9 слоёв, import-linter) | Codemod переписывает 910 файлов, требует влитых веток; backend_ctl ещё не извлечён → в rename-таблице его нет | Freeze-окно на framework-ветки; гейт 2904 теста + lint-imports |
| **4** | **backend_ctl Phases 1–4** (`feat/backend-ctl-module`) | Модуль рождается сразу в пост-codemod раскладке `tooling/backend_ctl/` — один раз, без шимов modules-путей | Baseline sentrux до Phase 1; `check_rules` после |
| **5** | layer-grouping Инициатива 2 (2A→2D→2B→2C) | 2B (obs-DI) трогает все модули — накроет и уже извлечённый backend_ctl одним codemod-проходом | 2B под усиленным тест-гейтом |

**Требуемая правка чужого плана:** в `plans/framework-layer-grouping/plan.md` добавить слой `tooling/` в целевую структуру и контракт import-linter (`tooling` — самый верх; `forbidden`: никто не импортирует `tooling`). Это правка одного раздела документа, не кода.

**Форк по приоритету владельца:** если фичи Phases 1–2 нужны раньше codemod — допустимо извлечь модуль в текущую раскладку `modules/backend_ctl_module/` и внести 27-й записью в rename-таблицу codemod (цена: двойное переписывание шимов, механическое). По умолчанию НЕ делаем — Task 0.5 снимает главную потребность.

---

## Целевая архитектура (пост-codemod)

```
multiprocess_framework/tooling/backend_ctl/       ← НОВЫЙ верхний слой (Этап 4)
├── README.md / STATUS.md / DECISIONS.md          # правило №2
├── interfaces.py         # IBackendClient, IEventSource, ISubscriptionRegistry (Protocol)
├── __init__.py           # фасад: BackendDriver, BackendHarness, датаклассы
├── config.py             # resolve_endpoint(): арг > env BACKEND_CTL_HOST/PORT > DEFAULT_PORT
│                         #   (константа импортируется из backend_ctl_endpoint — 1 источник)
├── transport.py          # SocketConnection (TCP+reader+framing) + RequestSession
│                         #   (_Pending, request_id-матчинг, карантин поздних ответов)
├── protocol.py           # unwrap() (слияние _find_payload/_leaf_result) + RouterStats/
│                         #   QueueDepths/WorkerStatus/MemoryStats/*Capabilities
├── events.py             # EventHub: bounded deque (back-compat) + классификация по плоскостям
├── subscriptions.py      # SubscriptionRegistry: durable-намерения, replay при reconnect,
│                         #   авто-переподписка по supervisor "recovered"
├── driver.py             # BackendDriver — фасад (композиция, глубина вызова = 2)
├── domains/              # тонкие доменные группы обёрток
│   ├── introspect.py     #   introspect.* + capabilities fan-out + introspect.memory (NEW)
│   ├── registers.py      #   set_register / set_register_verified
│   ├── observability.py  #   config_reload, logger_sink_*, log_tail, observability_tail (NEW)
│   ├── telemetry.py      #   telemetry_reconfigure/telemetry_set (перенос 1:1, семантику не трогать)
│   ├── state.py          #   state_subscribe, watch_like_gui() (NEW), read-model
│   └── debug_plane.py    #   ui_tap*, debug_session/debug_stop (общий _discover_processes)
├── mcp/
│   ├── server.py         # сервер на официальном MCP SDK (stdio), lazy-connect driver
│   ├── tools.py          # ToolSpec-реестр + annotations + safety-классификация
│   └── errors.py         # actionable-ошибки: hint + валидные альтернативы
├── harness.py            # generic BackendHarness (launcher_factory ОБЯЗАТЕЛЕН, env-restore)
└── tests/                # unit (без live)

backend_ctl/                                      ← tooling-слой ВНЕ framework (остаётся)
├── driver.py, mcp_server.py, harness.py, __init__.py  # re-export-шимы → tooling.backend_ctl
│                         # (единственный compat-слой; удаляются после миграции потребителей)
├── proto_harness.py      # strip_gui + build_headless_launcher + BackendHarness со старой
│                         #   сигнатурой (recipe/with_base) — фикстуры live-тестов не меняются
├── probes/               # smoke_proof, telemetry_probe, telemetry_sink_proof, g1/g7_*
├── dump_capabilities.py  # CLI поверх модуля (drift-gate docs/contracts/CAPABILITIES.md)
└── tests/                # 11 live-suites + новые live (легально импортируют прототип)
```

Серверная половина уже во framework и не меняется, кроме additive-команды `introspect.memory`: `backend_ctl_endpoint.py`, `socket_channel.py`, `SocketBridgeAdapter`.

**Карта переноса** (git mv по кускам, поведение бит-в-бит; пути `tooling/backend_ctl/` — пост-codemod):

| Сейчас (`backend_ctl/`) | Станет (`tooling/backend_ctl/`) |
|---|---|
| `driver.py:55-96` `_find_payload`/`_leaf_result`/`_is_ok` | `protocol.py::unwrap()` |
| `driver.py:99-235` (5 датаклассов) | `protocol.py` |
| `driver.py:228-399` (_Pending, connect/close/_read_loop/_dispatch/_send_raw) | `transport.py` |
| `driver.py:403-483` (event deque/subscribe/events) | `events.py` |
| `driver.py:485-981` (обёртки) | `domains/*` по семьям |
| `mcp_server.py` / `mcp_tools.py` | `mcp/server.py` (SDK) / `mcp/tools.py` |
| `harness.py:51-109` (strip_gui, build_headless_launcher) | `backend_ctl/proto_harness.py` (импортируют прототип) |
| `harness.py:117-415` (watchdog/kill-tree/BackendHarness) | `tooling/backend_ctl/harness.py` |
| probe-скрипты | `backend_ctl/probes/` (шимы на старых путях) |

**Порядок: баги ДО реструктуризации.** Phase 0 фиксит поведение на текущей раскладке (unit-покрытие уже хорошее → зелёная характеризованная база), затем перенос — чистый `git mv` + импорты, тривиальный для ревью.

---

## Phase 0 — Hardening на текущей раскладке (Этап 1, СЕЙЧАС; ветка `feat/backend-ctl-hardening`)

> **✅ PHASE 0 ЗАВЕРШЕНА + ОТРЕВЬЮ (2026-07-17).** Все 5 задач закрыты на ветке `feat/backend-ctl-hardening`
> (worktree, изолированно от параллельной телеметрии). Код: 9be0b852 · 2dbb8b8a · 3c74b129 · a0adb2e3 · 1a420c81.
> **Ревью Opus:** merge-с-правками, 0 блокеров. Внесены фиксы (b68c439f): MAJOR #1 (реконнект воскрешал
> отписанные подписки), MAJOR #4 (env-leak при падении start()), MINOR #3 (late_replies под лок) + 2 регресс-теста.
> **Вердикт Fable: PASS** — фиксы доказаны эмпирически (регресс-тесты падают на pre-fix коде), 111/111 unit.
> Отложено в Phase 1: MINOR #2 (композиты best-effort), #6 (over-record), NIT #5 (pre-existing read_loop).
> live harness_smoke зелёный; красный `test_mcp_server_live_against_backend` — pre-existing (не регресс).
>
> **⚠️ СТРАТЕГИЯ МЕРЖА (за владельцем):** ветка ответвлена от `feat/telemetry-coherence` HEAD (11dd9dfc),
> т.к. Task 0.5 зависит от telemetry-driver методов (f75d77b1). Значит `main..feat/backend-ctl-hardening`
> несёт ~27 telemetry-коммитов (Фаза 1) + Phase 0. Прямой merge в main втянет и телеметрию Фазы 1.
> **Решение владельца (2026-07-17): вариант «сначала телеметрия, потом Phase 0».** Ждём, пока coherence
> Фаза 1 ляжет в main, ЗАТЕМ `git merge feat/backend-ctl-hardening` (добавит только backend_ctl-дельту —
> git дедуплицирует 27 общих telemetry-коммитов). main пока НЕ трогаем. НЕ включает незакрытый Task 1.4
> телеметрии (он позже 11dd9dfc). Дальше — Phases 1–4 (после codemod).

### Task 0.1 — Единый источник endpoint-конфига  ✅ (9be0b852)
**Level:** Middle (Sonnet) | **Assignee:** developer | **Layer:** mixed
**Goal:** убрать 5 хардкодов 8765; клиент читает те же env, что сервер.
**Files:** `backend_ctl/endpoint_config.py` (новый), `driver.py:256`, `mcp_server.py:70,218`, `harness.py:277`, `dump_capabilities.py:191,222`, `g7_fault_probe.py:42`.
**Steps:**
1. `resolve_endpoint(host=None, port=None) -> tuple[str, int]`: приоритет аргумент > `BACKEND_CTL_HOST`/`BACKEND_CTL_PORT` > `DEFAULT_PORT`, импортированный из `process_manager_module.process.backend_ctl_endpoint` (единственный источник числа).
2. Перевести все места; сигнатуры `port: int | None = None` — back-compat.
**Acceptance:**
- [x] grep `8765` по `backend_ctl/` — только через импорт константы (остались лишь докстроки + осознанный `_PORT=8791` в g7-пробе)
- [x] unit-тест приоритетов резолвера (6 кейсов); существующие тесты зелёные (live-фейлы pre-existing на HEAD)
**Out of scope:** серверная сторона.
**Заметка:** `smoke_proof.py`/`telemetry_probe.py` тоже переведены на резолвер (не были в списке Files, но содержали 8765). `g7_fault_probe.py` оставлен с явным `_PORT=8791` (осознанная изоляция от общих фикстур, не дубль дефолта).

### Task 0.2 — Гонка close()/request() + карантин поздних ответов  ✅ (2dbb8b8a)
**Level:** Middle+ (Sonnet) | **Assignee:** developer | **Layer:** tests/tooling
**Goal:** закрыть баги гонки и псевдо-событий.
**Files:** `backend_ctl/driver.py`, `backend_ctl/tests/test_driver.py`.
**Steps:**
1. `_send_raw`: вместо `assert self._sock is not None` — проверка под `_write_lock` + `raise ConnectionError`; в `request()` перехват → `{"success": False, "error": "connection closed"}`.
2. Поздние ответы: при таймауте `request()` кладёт `request_id` в `_timed_out` (TTL 60с, lazy-purge); `_dispatch` такие дропает + счётчик `late_replies` (property) — НЕ псевдо-событие.
**Acceptance:**
- [x] Тест: `close()` из другого потока при in-flight `request()` → error-dict, не AssertionError (стресс 100 итераций)
- [x] Тест: ответ после таймаута не появляется в `events()`, `late_replies` растёт
**Out of scope:** reconnect (0.3).
**Статус:** ✅ 2dbb8b8a (test_driver.py 33/33; +`_send_raw` захват сокета под локом, +`_quarantine_timed_out`)

### Task 0.3 — Единый контракт ошибок + durable-подписки при reconnect (ежедневная боль №1)  ✅ (3c74b129)
**Level:** Senior (Opus) | **Assignee:** teamlead | **Layer:** tests/tooling
**Goal:** один контракт ошибок; реконнект MCP-сервера не теряет подписки молча.
**Files:** `backend_ctl/driver.py`, `backend_ctl/mcp_server.py`, `backend_ctl/mcp_tools.py`, тесты.
**Steps:**
1. Контракт (Dict at Boundary, driver не бросает на backend-ошибках): каждый метод возвращает dict с обязательным `success: bool`; при ошибке `error: str` + опц. `hint: str`. Нормализация через `unwrap`-предшественника. **Telemetry-методы (:696-803) не трогать** — они уже соответствуют.
2. `SubscriptionRegistry` в driver: `state_subscribe`/`log_tail`/`ui_tap` регистрируют намерение `{command, target, args}`; `*_untail`/`*_untap` снимают; `driver.replay_subscriptions()`.
3. `mcp_server._reset_driver`: после переподключения новый driver получает реестр и делает replay; в ответ инструмента добавляется `"reconnected": true, "resubscribed": [...]`.
4. Убрать `time.sleep(0.3)` (mcp_server.py:89) → ping-проба `introspect.status("ProcessManager", timeout=2)` с 3 ретраями.
**Acceptance:**
- [x] Тест (fake-driver): обрыв → следующий tools/call переподключается и replay'ит подписки
- [x] Тест контракта: все обёртки на fake-транспорте с ошибкой → `success=False` + `error`
**Out of scope:** переезд реестра в `subscriptions.py` (Phase 1); авто-переподписка по «recovered» (Task 2.2).
**Статус:** ✅ 3c74b129 (14 unit-тестов). Контракт ошибок: переписывать 30 обёрток НЕ понадобилось — единообразие `{success:False,error}` уже гарантирует `request()`; шаг закрыт проверочным тестом на 19 обёрток. Telemetry-методы не тронуты.

### Task 0.4 — Harness: env-restore + readiness-probe; дедупликация; публичные аксессоры  ✅ (a0adb2e3)
**Level:** Middle+ (Sonnet) | **Assignee:** developer | **Layer:** tests/tooling
**Goal:** env-мутации с восстановлением; poll вместо sleep; убрать дубли и доступ тестов к приватным полям.
**Files:** `backend_ctl/harness.py`, `backend_ctl/driver.py`, `backend_ctl/tests/conftest.py`, `test_harness.py`.
**Steps:**
1. `start()` сохраняет прежние `BACKEND_CTL`/`BACKEND_CTL_PORT`/`INSPECTOR_PID_FILE`, `stop()` восстанавливает (try/finally, включая «не было»).
2. `warmup`-sleep → poll `introspect.status("ProcessManager")` до `success` (дедлайн = прежний warmup+3с).
3. Дедуп: общий `driver._discover_processes()` для `debug_session`/`debug_stop`; `_find_payload`/`_leaf_result` → единый `unwrap(res, keys=..., leaf=...)` (старые имена — алиасы до Phase 1).
4. Публичные `driver.port` (property) и `driver.dispatch_raw()` — тесты переводятся с `_port`/`_dispatch`.
**Acceptance:**
- [x] Тест: env после `stop()` == env до `start()`
- [x] live harness_smoke зелёный; grep `_dispatch\b|\._port\b` по tests пуст
**Out of scope:** перенос harness во framework.
**Статус:** ✅ a0adb2e3. `unwrap(res, *keys, leaf=)` — единый распаковщик (аргумент `keys` позиционный, не kw). `_discover_processes` дедуплицирован. Публичные `port`/`host`/`dispatch_raw`.

### Task 0.5 — Telemetry в MCP на текущем реестре (дешёвый ежедневный win, из ревью)  ✅ (1a420c81)
**Level:** Middle (Sonnet) | **Assignee:** developer | **Layer:** tests/tooling
**Goal:** агенты получают `telemetry_reconfigure`/`telemetry_set` через MCP немедленно, не дожидаясь SDK.
**Files:** `backend_ctl/mcp_tools.py`, `backend_ctl/tests/test_mcp_server.py`, `backend_ctl/README.md`, `backend_ctl/AGENTS.md`.
**Steps:**
1. Два `ToolSpec`, зеркалящие существующие driver-методы (:696, :751): схемы publish/throttle/mode/plane; описания предупреждают о wipe в `replace` и советуют `telemetry_set` для точечных правок.
2. Обновить `test_expected_tool_set`; README/AGENTS — упомянуть инструменты.
**Acceptance:**
- [x] `tools/list` содержит `telemetry_reconfigure`/`telemetry_set`; unit-тест dispatch на fake-driver
- [x] Семантика на проводе НЕ меняется (только регистрация; driver-методы не трогаются)
**Out of scope:** SDK, annotations, новые driver-методы.
**Статус:** ✅ 1a420c81. Handlers пробрасывают только присутствующие ключи (сохранена `_UNSET`-семантика; `publish=null` доходит как «выключить gate»). Live-тест телеметрии — Task 4.1.

---

## Phases 1–4 — Этап 4 глобального порядка (ПОСЛЕ: coherence в main → codemod layer-grouping в main)

### Phase 1 — Извлечение в `tooling/backend_ctl/`

#### Task 1.1 — Скелет модуля + перенос driver-ядра
**Level:** Senior (Opus) | **Assignee:** teamlead | **Layer:** framework
**Goal:** модуль по правилу №2 в новом верхнем слое `tooling/`; распил god-file по карте переноса.
**Files:** новые `multiprocess_framework/tooling/backend_ctl/{README,STATUS,DECISIONS}.md`, `interfaces.py`, `config.py`, `transport.py`, `protocol.py`, `events.py`, `subscriptions.py`, `driver.py`, `domains/*`, `tests/`; шимы в `backend_ctl/`; `.importlinter` (слой `tooling` — самый верх, `forbidden` на импорт `tooling`); `.sentrux/rules.toml`.
**Steps:**
1. Перенос по карте, поведение бит-в-бит (характеризация — существующие unit-тесты на новых импортах). `endpoint_config.py` (0.1) → `config.py`.
2. `interfaces.py`: `IBackendClient`, `IEventSource`, `ISubscriptionRegistry` — Protocol, русские docstring.
3. `backend_ctl/driver.py` и `__init__.py` → re-export-шимы (единственный compat-слой; целевой срок удаления — после миграции потребителей, зафиксировать в STATUS).
4. `telemetry_reconfigure`/`telemetry_set` → `domains/telemetry.py` **строка в строку**.
5. Unit-тесты → `tooling/backend_ctl/tests/`; live-тесты остаются в `backend_ctl/tests/`. Контракт-тест границ (по образцу `app_module/tests/test_contract.py`): **весь модуль, включая `mcp/**` и `domains/**`**, не импортирует `multiprocess_prototype`/top-level `backend_ctl`.
**Acceptance:**
- [ ] `pytest multiprocess_framework/tooling/backend_ctl backend_ctl` зелёный; `scripts/validate.py` чист
- [ ] `lint-imports` (слой tooling) + `mcp__sentrux__check_rules` чисты; контракт-тест границ зелёный
- [ ] Старый импорт `from backend_ctl import BackendDriver` работает
**Out of scope:** новые фичи; MCP; harness.

#### Task 1.2 — Generic harness + прототип-глю + перенос MCP-файлов
**Level:** Senior (Opus) | **Assignee:** teamlead | **Layer:** mixed
**Goal:** `harness.py` и `mcp/` в модуле; прототип-специфика отделена инъекцией.
**Files:** `tooling/backend_ctl/harness.py`, `tooling/backend_ctl/mcp/{server,tools,errors}.py`, `backend_ctl/proto_harness.py`, шимы `backend_ctl/mcp_server.py`/`harness.py`, `.claude/plugins/mcp-backend-ctl/README.md`, `.mcp.json`.
**Steps:**
1. Generic `BackendHarness`: `launcher_factory` обязателен (escape-hatch Ф5.13 в `harness.py:282` становится единственным путём); `backend_ctl/proto_harness.py` собирает прототипную фабрику (`strip_gui` + `build_headless_launcher`) и экспортирует обёртку со старой сигнатурой (recipe/with_base) — фикстуры live-тестов не меняются.
2. Перенос mcp_server/mcp_tools в `mcp/` (рукописный, вместе с Task 0.5-инструментами — SDK отдельно в 3.1, чтобы перенос и смена стека не смешивались); entrypoint `python -m multiprocess_framework.tooling.backend_ctl.mcp.server` + шим `python -m backend_ctl.mcp_server`; `.mcp.json`/плагин правятся ОДИН раз на финальный путь.
3. Probe-скрипты → `backend_ctl/probes/` (двухстрочные шимы на старых путях), `dump_capabilities` — CLI поверх модуля.
**Acceptance:**
- [ ] MCP-смоук (initialize → tools/list → tools/call capabilities) через оба entrypoint'а
- [ ] Все 11 live-suites зелёные без правок фикстур; sentrux чист
- [ ] Пробы запускаются со старых и новых путей
**Out of scope:** каталог инструментов и SDK (Phase 3).

### Phase 2 — Receive-plane: паритет с GUI

#### Task 2.1 — `observability_tail`: live ЛОГИ+ОШИБКИ+СТАТИСТИКА
**Level:** Middle+ (Sonnet) | **Assignee:** developer | **Layer:** framework
**Goal:** driver умеет то, что `ObservabilityTailActivator` делает для GUI.
**Files:** `domains/observability.py`, `subscriptions.py`, `events.py`, `mcp/tools.py`, unit-тесты.
**Steps:**
1. `observability_tail(process, *, subscriber=None)` → `send_command(process, "observability.tail.subscribe", {"subscriber": ...})` (контракт `ObservabilityTailSubscribeParams` в `command_contracts.py:153`); `observability_untail`.
2. Регистрация намерения в SubscriptionRegistry.
3. Push `observability.record` классифицируется EventHub в плоскости logs/errors/stats по kind записи.
4. MCP-инструменты `observability_tail`/`observability_untail`.
**Acceptance:**
- [ ] unit: fake-транспорт получает канонический конверт; записи расходятся по плоскостям
- [ ] live (Task 4.1): tail на процесс → `events()` содержит stats-записи
**Out of scope:** авто-переподписка (2.2).

#### Task 2.2 — `watch_like_gui()`: GUI-эквивалентный приёмный профиль + авто-переподписка
**Level:** Senior (Opus) | **Assignee:** teamlead | **Layer:** framework
**Goal:** одна команда включает всё, что получает GUI: `state.changed` по `processes.**`/`system.**`/`devices.**`/`calibration.**` (зеркало `multiprocess_prototype/frontend/process.py:93-110`), `observability.tail` на все процессы, log-tail. Кадры/SHM — вне контракта (README).
**Files:** `domains/state.py`, `subscriptions.py`, `driver.py`, `mcp/tools.py`, тесты.
**Steps:**
1. `watch_like_gui(*, patterns=GUI_DEFAULT_PATTERNS, tail_level="WARNING")`: `state_subscribe`×4 + `observability_tail`×N (процессы из `_discover_processes()`); best-effort сводка как у `debug_session`. Wildcard-набор — константа модуля, прототип может передать свой.
2. Клиентское зеркало `ObservabilityTailActivator` (`tail_activator.py:62-68`): подписчик EventHub на `state.changed` с `processes.<name>.supervisor.event == "recovered"` → SubscriptionRegistry повторяет subscribe для новой инкарнации.
3. `unwatch()`. MCP: `watch_like_gui`/`unwatch`.
**Acceptance:**
- [ ] unit: событие recovered → повторный subscribe ровно затронутого процесса
- [ ] live (4.1): kill_child → авто-рестарт → tail-события процесса продолжаются
**Out of scope:** телеметрический read-model (2.3).

#### Task 2.3 — Telemetry read-model (переиспользование generic-VM из frontend_module)
**Level:** Senior (Opus) | **Assignee:** teamlead | **Layer:** framework
**Goal:** GUI-эквивалент чтения телеметрии: локальная модель поверх `state.changed`-дельт + история, 0 IPC на чтение. Только приём — telemetry.*-семантика не трогается.
**Files:** `domains/state.py`, `events.py`, `mcp/tools.py`; источник — `frontend_module` (generic `TelemetryViewModel`+`HistorySource` после coherence Task 3.5).
**Steps:**
1. **Сначала проверить переиспользование** (находка ревью, DRY): coherence Task 3.5 промотирует `TelemetryViewModel`/`HistorySource` во `frontend_module` как generic (tracked_suffixes — параметры). Если класс отвязан от Qt — использовать его напрямую/тонкой обёрткой; если тянет Qt — извлечь ядро в общее место (`tooling` может импортировать `frontend_module`? — НЕТ, проверить слои: тогда ядро VM выносится в не-Qt модуль по решению teamlead + ADR). Своё дублирование — только последний вариант, с обоснованием в DECISIONS.
2. `driver.telemetry_snapshot(process=None, metric=None)` и `telemetry_history(path, limit)` — локально, 0 IPC («запись всегда, чтение локально», ADR-136).
3. Корреляционный ключ `(process, worker, ts)` во всех событиях — нормализация в EventHub (OTel: сигналы раздельно, ключ общий).
4. MCP: `telemetry_snapshot`, `telemetry_history` (readOnlyHint).
**Acceptance:**
- [ ] unit: поток синтетических дельт → snapshot/history корректны, память bounded
- [ ] live: после `watch_like_gui` snapshot непуст для fps живого процесса
- [ ] В DECISIONS зафиксировано решение reuse-vs-own с обоснованием
**Out of scope:** правки `heartbeat/telemetry.py`/`telemetry_reload.py`; история из БД-стока.

#### Task 2.4 — Новая framework-команда `introspect.memory` (SHM/память/очереди)
**Level:** Senior (Opus) | **Assignee:** teamlead | **Layer:** framework
**Goal:** инвентарь памяти по IPC — `MemoryManager.get_stats()` (`shared_resources_module/memory/core/manager.py:489`), пул (`loan_ledger.snapshot_stats()`), `ShmRegistry`, очереди — сейчас не экспонированы. Конфликт по `builtin_commands.py` снят: coherence к Этапу 4 полностью в main.
**Files:** `process_module/commands/builtin_commands.py` (новый `_cmd_introspect_memory` в блоке `_register_introspect_commands`; пути — пост-codemod), `command_contracts.py`, `domains/introspect.py`, `protocol.py` (`MemoryStats`), тесты builtin_commands.
**Steps:**
1. Команда `introspect.memory`: best-effort сбор `get_stats()` со всех доступных менеджеров shared_resources (`{"memory": ..., "pool": ..., "queues": ..., "shm_registry": ...}`; отсутствие менеджера → `null`, не ошибка).
2. Driver `introspect_memory(process)` + типизированный `MemoryStats` (`.raw` сохраняется). MCP `introspect_memory` (readOnlyHint).
3. Regen `docs/contracts/CAPABILITIES.md` (drift-gate).
**Acceptance:**
- [ ] unit builtin_commands на fake-services; live: `success=True` + хотя бы одна секция
- [ ] CAPABILITIES regen отражает команду; drift-gate CI зелёный
**Out of scope:** содержимое SHM/кадры (только статистика).

### Phase 3 — MCP на официальном SDK

#### Task 3.1 — Миграция сервера на официальный MCP Python SDK
**Level:** Senior (Opus) | **Assignee:** teamlead | **Layer:** framework
**Goal:** `mcp/server.py` на пакете `mcp`, stdio; реестр ToolSpec остаётся своим — SDK-адаптер регистрирует инструменты из него (смена стека = один файл).
**Files:** `pyproject.toml` (extras `ctl`), `mcp/server.py`, `mcp/tools.py`, `test_mcp_server.py`, `.claude/plugins/mcp-backend-ctl/README.md`, `.mcp.json`.
**Steps:**
1. Extras `ctl = ["mcp>=X.Y,<X.(Y+1)"]` — **пин конкретного minor** (находка ревью; выбрать актуальный на момент исполнения, зафиксировать в DECISIONS). Ленивый импорт SDK (без extra модуль импортируется, сервер даёт понятную ошибку с командой установки). **Команду установки выдать владельцу — не запускать самим.**
2. Сервер на SDK: lazy-connect driver и reconnect+replay (0.3) сохраняются в нашем слое; имена инструментов НЕ меняются.
3. `ToolSpec.annotations` (`readOnlyHint`/`destructiveHint`/`idempotentHint`) → через SDK.
4. Golden-тест `tools/list` (полный каталог + annotations). Рукописный сервер удаляется только после живого смоука SDK-версии из Claude Code.
5. ADR в DECISIONS: SDK за реестром, пин версии, триггеры отката.
**Acceptance:**
- [ ] `tools/list` через SDK == golden (все инструменты Phases 0–2 с annotations)
- [ ] Живой смоук из Claude Code (плагин mcp-backend-ctl на финальном entrypoint)
- [ ] Без extra `ctl` импорт модуля не падает
**Out of scope:** streamable HTTP (SDK делает дешёвым — следующая итерация); переименования инструментов.

#### Task 3.2 — Safety-режимы: `--read-only` / `--disable-destructive`
**Level:** Middle+ (Sonnet) | **Assignee:** developer | **Layer:** framework
**Goal:** лестница безопасности, enforce на сервере ДО вызова driver (annotations — только hints).
**Files:** `mcp/server.py` (argv/env `BACKEND_CTL_MCP_MODE`), `mcp/tools.py`, тесты.
**Steps:**
1. Классификация ToolSpec: `read` (capabilities, introspect_*, state_get*, events, telemetry_snapshot/history), `subscribe` (state_subscribe, *_tail, watch_like_gui, debug_session), `write` (set_register*, config_reload, logger_sink_*, telemetry_reconfigure/set), `escalated` (send_command, system_command).
2. read-only → read+subscribe; `send_command` пропускает только whitelisted `introspect.*`/`state.get*`.
3. Отказ actionable: «X заблокирован режимом read-only; доступны: …». `tools/list` в ограниченном режиме скрывает write-инструменты.
**Acceptance:**
- [ ] Тесты трёх режимов; в read-only `set_register` отклоняется в SDK-обёртке ДО driver (fake фиксирует отсутствие вызова)
**Out of scope:** аутентификация (endpoint остаётся localhost-dev).

#### Task 3.3 — Actionable-ошибки + response_format для capabilities
**Level:** Middle+ (Sonnet) | **Assignee:** developer | **Layer:** framework
**Goal:** ошибки называют валидные альтернативы («errors that teach»); capabilities не взрывает контекст агента.
**Files:** `mcp/errors.py`, `mcp/server.py`, `mcp/tools.py`.
**Steps:**
1. Неизвестный инструмент → ближайшие имена; неизвестная команда → hint «см. introspect_handlers процесса X»; timeout на адресате → hint со списком процессов из последнего capabilities-кэша.
2. `capabilities`: `response_format` (`concise` = имена команд без params_schema) + `process`-фильтр.
**Acceptance:**
- [ ] Тесты на каждый класс ошибок (fake); `capabilities(concise)` кратно меньше detailed на живой системе
**Out of scope:** i18n.

> **Отложено в бэклог (решение ревью — не грузить план):** cursor-дренаж событий по плоскостям (list-watch: `events_page(plane, cursor)` + `dropped`-счётчики) и пагинация прочих тяжёлых ответов. Вернуться, когда появится реальная боль от разрушающего `events()` у нескольких потребителей.

> **Идея владельца (2026-07-17) — «записная книжка модуля» / единый `help`:** сделать удобный человеко/агенто-читаемый вид `help(process)` / `describe(process)` поверх УЖЕ существующей машиночитаемой карточки `introspect.capabilities` (команды+описания+params_schema, `router_handlers` = какие сигналы слушает, `registers`, каналы/адреса из `capabilities_extra`). Данные уже есть — не хватает рендера «шпаргалки»: «команды (с примерами) · что можно подписать и как поймать · адреса/каналы · регистры». Логично лечь в Phase 3 рядом с `response_format` (Task 3.3): `capabilities(format="help")`. Ноль дублирования (тот же реестр). Гэпы, которые уже закрываются планом: «поймать сигналы» → Phase 2 (`observability_tail`/`watch_like_gui`), «телеметрия как ручка» → Task 0.5, «память/очереди» → Task 2.4, «errors that teach» → Task 3.3.

### Phase 4 — Тесты, документация

#### Task 4.1 — Live-тесты: telemetry, watch_like_gui, reconnect
**Level:** Middle+ (Sonnet) | **Assignee:** tester | **Layer:** tests
**Files:** `backend_ctl/tests/test_telemetry_live.py`, `test_watch_like_gui_live.py`, `test_reconnect_live.py` (новые).
**Steps:**
1. `test_telemetry_live`: harness → `watch_like_gui` → `telemetry_snapshot` непуст; `telemetry_set(metric="fps", enabled=False)` → поток fps-дельт прекращается (проверяем эффект приёма — семантика telemetry.* покрыта планом coherence).
2. live reconnect: разрыв соединения при живом бэкенде → replay подписок, события продолжаются.
3. Единый pytest-маркер live-тестов (унифицировать с `harness_smoke`, если нужно).
**Acceptance:**
- [ ] Новые live-тесты зелёные локально (Windows, реальный spawn); `scripts/run_framework_tests.py` без регрессий

#### Task 4.2 — Документация + CAPABILITIES-regen
**Level:** Middle (Sonnet) | **Assignee:** tech-writer | **Layer:** docs
**Files:** `tooling/backend_ctl/{README,STATUS,DECISIONS}.md`, `backend_ctl/README.md`, `backend_ctl/AGENTS.md`, `docs/contracts/CAPABILITIES.md`, `multiprocess_framework/DECISIONS.md` (индекс) + `python -m scripts.sync`.
**Steps:**
1. README модуля: слои, контракт ошибок (`success/error/hint`), safety-режимы, «кадры/SHM вне контракта». STATUS (срок жизни шимов). DECISIONS: ADR «SDK за реестром ToolSpec + пин», ADR «контракт ошибок dict», ADR «read-model: reuse vs own».
2. AGENTS.md: telemetry_*, watch_like_gui, observability_tail, introspect_memory, safety-режимы.
3. Regen CAPABILITIES; `python -m scripts.sync` (правило №8); обновить MODULES_RESPONSIBILITY_MAP/MODULES_STATUS (слой tooling).
**Acceptance:**
- [ ] `link-check` чист; drift-gate зелёный; AGENTS.md упоминает каждый MCP-инструмент; sync-разделы без дрифта

---

## Verification (весь план)

1. **Каждый таск:** `python scripts/validate.py` + целевые pytest; для framework — `python scripts/run_framework_tests.py`.
2. **Границы слоёв:** `mcp__sentrux__session_start` (baseline до Phase 1) → `lint-imports` (слой `tooling` — верх) + `check_rules` после каждого переноса → `session_end` после Phase 3 (не хуже baseline).
3. **Live:** 11 существующих live-suites + 3 новых на harness (Windows, реальный spawn). Эталон pre-existing: 2 Windows-фейла app_module.
4. **MCP-смоук:** оба entrypoint'а: `initialize` → `tools/list` (golden) → `tools/call capabilities` → то же в `--read-only` (заблокированный `set_register`). Финальная проверка — живая сессия Claude Code с плагином mcp-backend-ctl.
5. **Drift-gate:** `dump_capabilities` → diff `docs/contracts/CAPABILITIES.md` пуст.
6. **Back-compat:** `grep -rn "from backend_ctl" multiprocess_prototype docs plans` — все точки входа живы через шимы.
7. Коммиты: Conventional Commits + `Why:`/`Layer:` + `Refs: plans/backend-ctl-framework-module.md`; чекбоксы `[x]` + hash после каждой задачи.

## Риски

| Риск | Митигация |
|---|---|
| Параллелизм Этапа 1: coherence и Phase 0 в одном репо | Разные файлы (coherence больше не трогает backend_ctl/); макс 2 агента без worktree; Phase 0 — короткая ветка, быстрый мерж |
| Codemod layer-grouping задерживается → Phases 1–4 ждут | Форк-вариант: извлечение в `modules/backend_ctl_module/` + 27-я запись rename-таблицы (описан выше); Task 0.5 уже дал главный ежедневный win |
| План layer-grouping не примет слой `tooling/` | Согласовать правку ДО старта Этапа 3 (одна секция документа); fallback — `application/` с отдельным import-linter-исключением (хуже, но работает) |
| Framework-модуль случайно импортирует прототип (harness/пробы/mcp) | `launcher_factory` обязателен; контракт-тест границ покрывает `mcp/**` и `domains/**`; `check_rules` в каждом таске |
| Поломка внешних импортов `backend_ctl.*` | Re-export-шимы (единственный compat-слой, срок в STATUS); back-compat grep в верификации |
| MCP SDK: дрейф API | Пин minor-версии + golden `tools/list`; рукописный сервер удаляется только после живого смоука |
| Дублирование read-model с frontend_module VM | Task 2.3 шаг 1: сначала reuse-проверка, решение в DECISIONS |
| Флак live-тестов на Windows | Readiness-probe вместо sleep (0.4); ретраи ping; отдельный маркер |
