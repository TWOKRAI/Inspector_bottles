# План: backend-ctl-debug-console — агентская операционная консоль

- **Slug:** `backend-ctl-debug-console`
- **Дата:** 2026-07-18 (по итогам Fable-ревью всей системы после Phases 0–3)
- **Ветка:** `feat/backend-ctl-debug-console` (фазы могут ветвиться отдельно)
- **Предшественник:** [`backend-ctl-framework-module.md`](backend-ctl-framework-module.md) (Phases 0–3 закрыты; Phase 1 переезд в `tooling/` и Phase 4.1 live — гейтнуты codemod/Windows)

---

## Context

Fable-ревью (2026-07-18, 3 агента: честная оценка / охота на баги / советы) оценило backend_ctl в **~7.4/10** (было ~4.8). Вердикт: зрелый контрол-плейн с редкой дисциплиной (каждый багфикс с падающим-на-pre-fix регресс-тестом, единый source safety-классификации, ADR с триггерами отката), функциональный GUI-паритет приёма достигнут. До «отлично» не хватает трёх вещей: **сплит god-file** (driver.py вырос 981→1922, фичи лились в тот же файл — архитектура *деградировала* относительно момента аудита), **живые доказательства** (вся реконнект-механика существует только в unit на fake-транспорте), **гигиена по своим же правилам** (нет STATUS.md/interfaces.py, 6 probe-скриптов в корне пакета).

Ревью также вскрыло **баги** (часть — в свежемерженом коде main) и предложило **дорожную карту** превращения backend_ctl из «GUI по сокету» в операционную консоль уровня kubectl+CDP для многопроцессного фреймворка, которая заодно станет витриной supervision-tree, fencing-token и G.6-трейсинга (связывает три плана владельца).

**Северная звезда:** агент открывает сессию одним `system_overview` (вердикты, не сырьё) → любое ожидание через `await_condition` (не поллинг) → события в курсорных плоскостях (несколько агентов не мешают друг другу) → каждый вызов несёт trace_id и `trace()` собирает причинную цепочку → рискованные правки идут commit-confirmed с авто-откатом + аудит → флаки уезжают владельцу файлом flight-recorder для offline-дебага без живой системы.

---

## Сейчас → Будет + честная целевая оценка

| Ось | Сейчас | Цель плана | Чем закрывается |
|---|:--:|:--:|---|
| Наблюдаемость | 8 | **9** | cursor list-watch + dropped-счётчик + re-list после реконнекта (Phase B/D) |
| Управляемость | 8.5 | **9** | supervision-ручка, commit-confirmed регистры (Phase D) |
| Надёжность | 7.5 | **9** | багфиксы Phase A + live-доказательства (Phase F) |
| Архитектура | 5.5 | **8.5** | сплит god-file + STATUS/interfaces + probes/ (Phase C) |
| Качество MCP | 8 | **9** | help/concise, await_condition, system_overview, response_format (Phase B/E) |
| Оформление | 6.5 | **9** | Phase C гигиена + Phase F live-тесты |
| Замена GUI | 8 | **9** | trace/flight-recorder/overview — сверх GUI (Phase D) |

Средневзвешенно: **~7.4 → ~8.9** при закрытии A–F. Потолок не 10: streamable-HTTP мультиклиент и session-isolation — реальная работа с транспортом (Phase D), детерминированный rr-реплей сознательно отклонён.

> Цифры таблицы — мотивационный ориентир, **не критерий приёмки**: шкала самопридуманная, приёмка — только чекбоксы Acceptance по задачам. Финальную оценку даёт независимое Fable-ревью, и спорить с его цифрой этой таблицей нельзя.

---

## Порядок фаз (приоритеты)

1. **Phase A — Багфиксы ревью** (сначала: 2 регресса в main + thread-safety). Дёшево, разблокирует доверие.
2. **Phase B — P0 эргономика** (наибольшая ежедневная ценность: cursor list-watch, await_condition, system_overview, help/concise). Product-first ([[feedback_priority_product_over_engine]]).
3. **Phase C — Сплит god-file + гигиена** (архитектура; НЕ откладывать надолго — каждая фича B/D в 1922-строчный файл ухудшает его). Сначала C.0 — live-якорь (вынесен из Phase F): сплит нельзя страховать только unit'ами на fake-транспорте, недостаточность которых план сам констатирует. Сплит на текущей раскладке, переезд в `tooling/` — пост-codemod.
4. **Phase D — P1 власть агента** (supervision, session-isolation → streamable-HTTP, trace-id, flight-recorder, commit-confirmed регистры).
5. **Phase E — P2 доверие** (аудит-журнал, клиентская валидация, response_format-лимиты).
6. **Phase F — Live-доказательства** (поглощает Task 4.1 старого плана: реальный spawn, реконнект, watch, SDK-смоук из Claude Code).

**Зависимости:** B.1 (cursor-плоскости) гейтит мультиклиент D.2; session-isolation D.1a гейтит D.2; контракт trace-id D.3 — вход в Ф7 G.6 (внешний план), сама трассировка исполняется там. Сплит C рекомендуется до тяжёлых D-фич; C.0 (live-якорь) — строго до C.1.

---

## Phase A — Багфиксы ревью

### Task A.1 — subtree-delete leak в generic read-model (HIGH, в main)
**Level:** Middle+ (Sonnet) | **Layer:** framework
**Goal:** удаление узла в `TelemetryReadModel` должно чистить и всё поддерево, а не только точный ключ.
**Проблема (верифицирована эмпирически):** `tree_store.delete()` шлёт ОДНУ `Delta(new_value=MISSING)` на корень поддерева; `ingest(path, deleted=True)` делает `_state.pop(path)` по точному ключу → все листья под удалённым узлом (`processes.cam.state.fps` и т.п.) остаются НАВСЕГДА в `_state`/`_history`; snapshot/history отдают данные по несуществующим сущностям. `state.delete` — реальная команда (рецепты `recipes/presenter.py`). **Затрагивает и backend_ctl driver, и GUI `TelemetryViewModel`** (общее ядро).
**Files:** `multiprocess_framework/modules/telemetry_readmodel_module/telemetry_read_model.py`, tests.
**Steps:**
1. `ingest(deleted=True)`: удалить `path` И все ключи с префиксом `path + "."` из `_state` и `_history` (граница по точке-разделителю, как в `snapshot`).
2. Регресс-тест: subtree-delete чистит поддерево, соседний процесс с общим строковым префиксом (`cam2`) не затронут.
**Acceptance:**
- [x] unit: после `ingest("processes.cam", deleted=True)` snapshot/history по `processes.cam.*` пусты; `processes.cam2.*` целы
- [x] GUI `test_telemetry_view_model` не регрессирует (то же ядро)

### Task A.2 — утечка applier-потока при close() (MED/HIGH, в main)
**Level:** Middle+ (Sonnet) | **Layer:** tools
**Goal:** `close()` гасит `backend-ctl-resub` applier-поток; реконнект не плодит зомби-потоки.
**Проблема (верифицирована):** `close()` (driver.py:515) останавливает reader и сокет, но НЕ сигналит/join'ит `_resub_thread` — его гасит только `unwatch()`. `DriverSession.reset()` зовёт `close()` (не `unwatch`) → на каждый реконнект-с-активным-watch daemon-поток навсегда в `q.get()`.
**Files:** `backend_ctl/driver.py`, tests.
**Steps:**
1. `close()`: если `_resub_thread` жив — снять `_watch_active` под локом (чтобы self-heal applier'а не дёргал сеть), положить `None`-sentinel в его очередь, `join(timeout)`; без сетевого `observability_untail` (сокет закрывается).
2. Регресс-тест: активный watch → `close()` → applier-поток завершился (`is_alive()==False`), повторные close идемпотентны.
**Acceptance:**
- [ ] unit: watch активен → close() → `_resub_thread` не жив; счётчик живых `backend-ctl-resub` потоков не растёт после N reconnect-циклов

### Task A.3 — thread-safety close()/read_loop (MED)
**Level:** Middle+ (Sonnet) | **Layer:** tools
**Goal:** убрать TOCTOU и гонку с сокетом.
**Проблема:** (a) `_read_loop` проверяет `self._sock is not None`, затем без лока зовёт `self._sock.recv()` → `close()` в окне даёт `AttributeError`, тихо роняющий reader (daemon, только stderr). (b) `close()` обнуляет `_sock` без `_write_lock`, гонка с `_send_raw` маскируется широким except.
**Files:** `backend_ctl/driver.py`, tests.
**Steps:**
1. `_read_loop`: захватить локальную ссылку `sock = self._sock` под коротким локом (или в начале итерации) и звать `sock.recv()`; ловить `AttributeError`/`OSError` явно; при обрыве — залогировать (не только stderr-трейсбек).
2. `close()`: обнулять `_sock` под `_write_lock` (симметрия с `_send_raw`).
**Acceptance:**
- [ ] стресс-тест: конкурентные close()/read_loop 100 итераций без AttributeError-падения reader'а; reader завершается штатно

### Task A.4 — readiness-проба перестаёт молчать (MED/LOW)
**Level:** Middle (Sonnet) | **Layer:** tools
**Goal:** «бэкенд не прогрелся» — явный сигнал, не тихий таймаут на первом вызове.
**Проблема:** `DriverSession._await_ready` и `harness.start()` best-effort возвращают driver как готовый без флага/лога, если PM не ответил успехом за дедлайн.
**Files:** `backend_ctl/mcp_driver_session.py`, `backend_ctl/harness.py`, tests.
**Steps:**
1. `_await_ready` не подтвердил готовность → `log` warning + флаг `ready=False` в сессии; первый tool-ответ несёт `"backend_warming": true` (agent видит причину непонятного таймаута).
2. `DriverSession.ensure`: ловить не только `OSError`, но любое исключение фабрики → `BackendUnavailable` с текстом (соблюдение контракта «driver не бросает» на уровне сессии).

Шаги 1 и 2 независимы — коммитить раздельно, чтобы откат одного не тянул второй.
**Acceptance:**
- [ ] unit: фабрика бросает не-OSError → `BackendUnavailable`, не сырое; readiness-таймаут → warning + флаг

---

## Phase B — P0 эргономика (наибольшая ежедневная ценность)

### Task B.1 — Cursor list-watch по плоскостям (фундамент, гейтит мультиклиент)
**Level:** Senior (Opus) | **Layer:** framework
**Goal:** недеструктивное, повторяемое чтение событий с курсором и видимой потерей.
**Проблема:** `events()` деструктивно дренирует единую `deque(1000)`; два потребителя (или два tools/call подряд) крадут события друг у друга; `observability_records(events=None)` конфликтует с `events()`; переполнение вытесняет молча — агент не знает, что ослеп (тот же класс «тихой слепоты», что худший баг Phase 0, на уровень выше).
**Files:** `backend_ctl/driver.py` (EventHub), `backend_ctl/mcp_tools.py`, tests.
**Steps:**
1. EventHub → per-plane кольцевые буферы (state / logs / errors / stats / telemetry / ui) с монотонным `seq`; классификация push'ей по плоскости.
2. `events_page(plane=None, cursor=None, limit=)` — недеструктивно; ответ `{items, next_cursor, dropped, bookmark}`; `dropped` растёт при вытеснении из кольца.
3. `events()` — обёртка back-compat (дренаж всех плоскостей) с deprecation-нотой. Срок жизни ограничен этим планом: перевод вызывающих на `events_page` и **удаление обёртки — в F.1** (два конкурирующих режима потребления не должны жить дольше плана).
**Acceptance:**
- [ ] unit: два независимых курсора читают одну плоскость без взаимной кражи; переполнение кольца → `dropped>0` виден; `next_cursor` монотонен
- [ ] back-compat: существующие тесты `events()` зелёные
**Аналог:** K8s watch (resourceVersion+bookmarks), CDP event domains, journald cursor.

### Task B.2 — await_condition (серверное ожидание вместо поллинга)
**Level:** Middle+ (Sonnet) | **Layer:** tools
**Goal:** один вызов «сделал → дождался → проверил» вместо 3–10 round-trip'ов.
**Files:** `backend_ctl/driver.py`, `backend_ctl/mcp_tools.py`, tests.
**Steps:**
1. `await_condition(kind, spec, timeout)`: `state_path == value` (поверх telemetry read-model / state), `event_matches(plane, pattern)` (поверх B.1-плоскостей), `metric_threshold(path, op, value)`. Блокировка на сервере с жёстким cap таймаута.
2. Возврат: сработавшее событие/значение ИЛИ таймаут-диагноз (что ждали, что видели последним).
**Acceptance:**
- [ ] unit: синтетический поток дельт → условие срабатывает на нужной; таймаут возвращает диагноз, не пустоту
**Аналог:** `kubectl wait`, Playwright waitFor, свой же `qt_wait_for`.

### Task B.3 — system_overview («один вызов = вся картина» + anomalies)
**Level:** Middle+ (Sonnet) | **Layer:** tools
**Goal:** первая команда любой сессии: вердикты, не археология.
**Files:** `backend_ctl/driver.py`, `backend_ctl/mcp_tools.py`, tests.
**Steps:**
1. Серверный fan-out по процессам (существующие ручки: status/router_stats/queues/introspect_memory/telemetry_snapshot) → компактная сводка.
2. Секция `anomalies` (hints, не verdicts): очередь растёт, `middleware_dropped>0`, рестарт-луп, fps=0 при running, `late_replies>0`, `dropped>0`.
**Acceptance:**
- [ ] unit на fake: сводка компактна; аномалии детектятся на подставных счётчиках; ноль новых IPC-команд
**Аналог:** `kubectl get all`+`top`, Grafana health, Erlang observer.

### Task B.4 — capabilities(format="help"|"concise") + response_format
**Level:** Middle (Sonnet) | **Layer:** tools
**Goal:** холодный старт агента за 1 вызов; концайз против взрыва контекста (закрывает DEFER Task 3.3).
**Files:** `backend_ctl/mcp_tools.py`, `backend_ctl/mcp_errors.py`, tests.
**Steps:**
1. `concise` — имена команд без params_schema; `help` — карточка: 1 пример вызова (генерится из схемы) + «какое событие придёт и в какой плоскости» + корреляционные ключи (process/worker/ts, позже trace_id). Чистый рендер над реестром, ноль дублирования.
2. `process`-фильтр.
**Acceptance:**
- [ ] unit: `concise` кратно меньше detailed; `help` содержит пример вызова и подписочную подсказку
**Аналог:** `kubectl explain`, CDP domain docs.

---

## Phase C — Сплит god-file + гигиена

### Task C.0 — Live-якорь для сплита (вынесен из Phase F)
**Level:** Middle+ (Sonnet) | **Layer:** tests
**Goal:** минимальный live-тест (реальный spawn через harness, локально): watch_like_gui → snapshot непуст → разрыв соединения → replay подписок + watch-resume → tail продолжается. Прогнать **до** C.1 (зафиксировать зелёным) и **после** C.1 (доказательство «бит-в-бит» не только на fake-транспорте).
**Files:** `backend_ctl/tests/test_reconnect_live.py` (маркер `live`, skip при недоступном окружении).
**Acceptance:**
- [ ] live-тест зелёный до сплита (baseline-коммит) и после сплита; в CI по маркеру, локально обязателен для C.1

### Task C.1 — Распил driver.py (1922 стр) на модули (текущая раскладка)
**Level:** Senior (Opus) | **Layer:** tools
**Goal:** god-file → пакет `backend_ctl/driver/` (transport / protocol / events / subscriptions / domains/* / watch), поведение бит-в-бит.
**Проблема:** транспорт + протокол + 5 датаклассов + ~30 обёрток + watch-стейт-машина (~15 полей: lock/active/subscribed/listener/queue/thread/манифест) в одном классе. Watch-машина — готовый модуль, живущий полями чужого класса.
**Files:** новый пакет `backend_ctl/driver/` + re-export-шим `backend_ctl/driver.py`; tests на новых импортах.
**Steps:**
1. Распил по картам переноса из [`backend-ctl-framework-module.md`](backend-ctl-framework-module.md) (раздел «Целевая архитектура» / «Развязка сплита ⟂ переезда»): характеризация — существующие unit на новых импортах. Директива владельца «сделать красиво» (вычистить рабочие/процессные комментарии) — применить.
2. Watch-стейт-машина → отдельный класс (`WatchController`), инъекция в driver.
3. Последующий `git mv` в `tooling/` (пост-codemod) остаётся чистым.
**Acceptance:**
- [ ] `pytest backend_ctl` зелёный на новых импортах; live-якорь C.0 зелёный после сплита; `from backend_ctl.driver import BackendDriver` работает (шим); sentrux: quality/циклы/god не хуже baseline (depth — ориентир, не гейт, [[feedback_sentrux_depth_opaque]] + [[feedback_sentrux_gate_narrowed]])

### Task C.2 — Гигиена правила №2 + probes/
**Level:** Middle (Sonnet) | **Layer:** tools/docs
**Goal:** `STATUS.md` + `interfaces.py` (Protocol) для backend_ctl; probe-скрипты из корня в `backend_ctl/probes/`.
**Files:** `backend_ctl/STATUS.md`, `backend_ctl/interfaces.py`, `backend_ctl/probes/` (перенос g1/g7/telemetry_probe/smoke_proof/… с шимами при нужде).
**Acceptance:**
- [ ] `interfaces.py`: `IBackendClient`/`IEventSource`/`ISubscriptionRegistry` (Protocol); probes не в корне; `scripts/validate.py` чист

---

## Phase D — P1 власть агента

### Task D.1 — Session-isolation на транспорте (HIGH-архитектурный) + supervision-ручка
**Level:** Senior (Opus) | **Layer:** framework
**Гейт на старт:** самая рискованная задача плана при самой тонкой спецификации — перед исполнением обязателен **мини-план отдельным заходом** (Steps по файлам уровня Phase A, контракт-тесты изоляции, флаг отката). Ниже — рамка, не спецификация.
**Goal (D.1a, session-isolation):** per-connection identity в `SocketChannel`/`SocketBridgeAdapter` — реплаи и push адресуются приславшему сокету, не broadcast.
**Проблема:** один общий канал `"backend_ctl"` рассылает всем подключениям; адаптер не знает, чей запрос → отвечает всем. Изоляция сессий (на которую рассчитаны durable-subscriptions/watch) на транспорте НЕ существует; второй агент/проба → протечка реплаев и событий в чужой read-model ([[project_concurrent_backends_trap]]). **Гейтит мультиклиент (D.2).**
**Goal (D.1b, supervision):** `supervision_status(process?)` (incarnation/epoch, restarts, last_exit, стратегия, health) + `supervise(process, action=restart|drain_restart|set_policy)`; инкарнацию/epoch светить во всех событиях (основа fencing-token + маркер «до/после рестарта»).
**Files:** `socket_channel.py`, `socket_bridge_adapter.py`, `backend_ctl_endpoint.py`, `driver.py`, `mcp_tools.py`, tests.
**Acceptance:**
- [ ] два клиента на одном порту не видят реплаи/события друг друга; supervision_status читает incarnation/restarts; события несут epoch
**Аналог:** CDP multi-session, systemctl status/restart, OTP supervisor introspection.

### Task D.2 — Streamable-HTTP мультиклиент (строго после B.1 + D.1a)
**Level:** Senior (Opus) | **Layer:** tools
**Goal:** несколько агентов одновременно (наблюдатель/экспериментатор/ревьюер) на одной живой системе. SDK делает транспорт дёшево (BCTL-ADR-001); дорогая часть — per-session изоляция подписок/событий (решается B.1 + D.1a).
**Acceptance:**
- [ ] две параллельные сессии: одна тейлит observability, другая крутит регистры — без взаимных помех

### Task D.3 — Застолбить контракт trace-id в Ф7 G.6
**Level:** Middle (Sonnet) | **Layer:** docs
**Goal:** зафиксировать в контракте/плане Ф7 G.6 (внешний план) требование: trace-поля обязаны доезжать до `observability.record` и `state.changed`, не только до `Message`. **Сама трассировка** (driver штампует `trace_id` на send_command/set_register; EventHub индексирует; `trace(trace_id)` собирает waterfall — аналог OTel/Jaeger, CDP initiator-chain) — **исполняется в плане G.6**, не здесь: задача с acceptance «после G.6» в этом плане не закрывается и вечно висела бы в `/plan-status`.
**Acceptance:**
- [ ] требование записано в контракт G.6 (ссылка на документ); до G.6 корреляция — по (process, worker, ts)

### Task D.4 — Flight recorder (запись → offline-реплей в read-model)
**Level:** Senior (Opus) | **Layer:** tools
**Goal:** дешёвый тайм-трэвел: `record_start(path)` (снимок overview+state+telemetry + JSONL событий с seq/ts) + `record_load(path)` (прогрузить в тот же read-model оффлайн — snapshot/history/await_condition работают над записью). Всегда-включённый чёрный ящик (кольцо + dump при обрыве) — бонус. Детерминированный rr — **отклонён** (цена несоизмерима, multiprocess+SHM исключают).
**Files:** новый `backend_ctl/recorder.py`, `mcp_tools.py`, tests.
**Acceptance:**
- [ ] записанная сессия грузится в read-model без живой системы; snapshot/history/await_condition отвечают по записи
**Аналог:** Java Flight Recorder, Chrome tracing.

### Task D.5 — Регистры commit-confirmed + snapshot/restore
**Level:** Middle+ (Sonnet) | **Layer:** tools
**Goal:** безопасные агентские эксперименты с гарантированным откатом.
**Files:** `driver.py`, `mcp_tools.py`, tests.
**Steps:**
1. `register_snapshot(process?)` (через introspect.registers) + `register_restore(snapshot)`.
2. Режим `set_register(..., confirm_within=N)`: не подтвердил `register_confirm()` за N сек → авто-откат.
**Acceptance:**
- [ ] unit: серия правок → restore возвращает исходное; confirm_within без подтверждения → авто-откат
**Аналог:** Juniper `commit confirmed`, NETCONF candidate-config.

---

## Phase E — P2 доверие

### Task E.1 — Аудит-журнал мутаций
**Level:** Middle (Sonnet) | **Layer:** tools
**Goal:** все write/escalated вызовы сессии в JSONL (кто/что/когда/аргументы/результат) + `session_log()`. Даёт владельцу доверие к автономным сессиям и вход для откатов (D.5).
**Acceptance:** [ ] каждый write/escalated пишет запись; `session_log()` читает; read-инструменты не шумят в журнал.

### Task E.2 — Клиентская валидация send_command по схеме
**Level:** Middle (Sonnet) | **Layer:** tools
**Goal:** `send_command` сверяет args со схемой из capabilities-кэша ДО отправки; ошибка учит («поле X обязательно, схема: …») вместо таймаута.
**Acceptance:** [ ] неполные args → actionable-ошибка до отправки, не таймаут.

### Task E.3 — response_format/limits на тяжёлых ответах
**Level:** Middle (Sonnet) | **Layer:** tools
**Goal:** `state_get_subtree`/`telemetry_history`/overview с `concise`/`limit`-дефолтами — ни один инструмент не выливает 50К токенов в контекст.
**Acceptance:** [ ] тяжёлые ответы по умолчанию ограничены; полный объём — по явному флагу.

---

## Phase F — Live-доказательства (поглощает Task 4.1 старого плана)

### Task F.1 — Live-тесты + SDK-смоук
**Level:** Middle+ (Sonnet) | **Layer:** tests
**Files:** `backend_ctl/tests/test_*_live.py` (telemetry/watch/reconnect), SDK-смоук из Claude Code.
**Steps:**
1. Реальный spawn (Windows): watch_like_gui → telemetry_snapshot непуст; kill_child → авто-рестарт → tail продолжается; subtree-delete (A.1) на живом; applier-поток (A.2) не течёт. Разрыв/replay/watch-resume уже покрыт C.0 — здесь только прогнать его на Windows.
2. Живой смоук SDK-сервера из Claude Code (плагин на `mcp_server_sdk`); после успеха — **удалить рукописный `mcp_server.py`** (BCTL-ADR-001).
3. Перевести оставшихся вызывающих `events()` на `events_page` и **удалить back-compat-обёртку** (закрытие срока жизни из B.1).
**Acceptance:**
- [ ] новые live-тесты зелёные локально; SDK-смоук подтверждён; рукописный сервер удалён; `events()`-обёртка удалена

---

## Verification (весь план)

1. Каждый таск: `python scripts/validate.py` + целевые pytest; framework — `python scripts/run_framework_tests.py`.
2. Границы: `mcp__sentrux__session_start` (baseline до Phase C) → `check_rules` после сплита → `session_end` (не хуже baseline; depth после C.1 — не хуже).
3. Формальный `/code-review` перед merge каждой фазы ([[feedback_formal_review_before_merge]]); финдеры на Sonnet, оценка/советы — Fable ([[feedback_review_economy_tiers]]).
4. Коммиты: Conventional + `Why:`/`Layer:` + `Refs: plans/backend-ctl-debug-console.md`; чекбоксы `[x]` + hash после задачи.
5. **Док-синк инструментов:** каждая фаза, добавляющая/меняющая MCP-инструменты (B, D), закрывается обновлением `backend_ctl/AGENTS.md` + README (список инструментов, форматы ответов) — иначе агентские доки описывают устаревший API ([[feedback_mcp_tool_api_drift]]).

## Риски

| Риск | Митигация |
|---|---|
| Сплит god-file (C.1) конфликтует с параллельными фичами B/D | Сплит — отдельным заходом, быстрый merge; фичи после него; характеризация существующими тестами + live-якорь C.0 до/после |
| Session-isolation (D.1a) трогает серверный транспорт | обязательный мини-план перед стартом (см. гейт в D.1); baseline sentrux + контракт-тесты изоляции; за флагом до доказательства |
| await_condition/HTTP блокируют tools/call надолго | жёсткий cap таймаута; для HTTP — per-session изоляция обязательна (B.1+D.1a) |
| Live-тесты флак на Windows (Phase F) | readiness-probe (A.4) вместо sleep; отдельный маркер; эталон pre-existing 2 Windows-фейла |
| trace-id (D.3) ждёт Ф7 G.6 | заложить требование в контракт G.6 заранее; до этого — корреляция по (process,worker,ts) |
