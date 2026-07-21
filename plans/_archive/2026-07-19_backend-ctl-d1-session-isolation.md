# Мини-план D.1 — Session-isolation на транспорте + supervision-ручка

- **Slug:** `backend-ctl-d1-session-isolation`
- **Родитель:** [`backend-ctl-debug-console.md`](2026-07-19_backend-ctl-debug-console.md) → Task D.1 (Phase D)
- **Ветка (при старте):** `feat/bctl-d1-session-isolation` (отдельно от родителя)
- **Дата:** 2026-07-19
- **Гейт-статус:** ✅ ДИЗАЙН ОДОБРЕН (2026-07-19). Владелец делегировал развилку §5 и флаг §8/§9 на рассуждение модели **Fable**; вердикт верифицирован чтением кода. **§5 → Вариант A** (in-band `session` + dotted-subscriber; router и три push-строителя не трогаем). Флаг §9 — принят с правками (env escape-hatch + pop-always + запрет тихого fallback). Гейт открыт, код разрешён. Историческая формулировка развилки ниже (§5) сохранена как аудиторный след; решение — в конце §5.

> **Поглощён** [`plans/backend-ctl-proof-discipline.md`](../backend-ctl-proof-discipline.md) 2026-07-21 — план закрыт, этот файл в архиве (session-identity несущая, код не удалять). Дальнейшая работа трека backend_ctl — в поглотившем документе.

> Основа — исследование транспортного контура backend_ctl (Explore-агент, 2026-07-19). Все якоря `file:line` верифицированы чтением; проверить их актуальность перед правкой (код мог сдвинуться).

---

## 1. Зачем (проблема)

Один общий канал `"backend_ctl"` рассылает reply И push **всем** подключённым driver'ам (broadcast). Второй агент/проба на том же порту → протечка чужих реплаев и событий в чужой read-model ([[project_concurrent_backends_trap]]). Session-isolation, на которую рассчитаны durable-subscriptions/watch и мультиклиент **D.2**, на транспорте физически **не существует**. D.1a гейтит D.2.

D.1b (supervision-ручка) — параллельная под-цель: отдать наружу incarnation/epoch/restart-count/last_exit и завести `supervise(action=…)`, плюс светить epoch в событиях (основа fencing-token и маркер «до/после рестарта»).

---

## 2. Карта контура — путь reply/push (где теряется identity)

**Запрос → ответ:**
1. `driver.request()` — [transport.py:111](../../backend_ctl/transport.py#L111): назначает `request_id`, `reply_to="ProcessManager"`, пишет в сокет.
2. Сервер `SocketChannel._read_loop(client)` → `_handle_line` → `self._on_inbound(msg)` — [socket_channel.py:261](../../multiprocess_framework/modules/router_module/channels/socket_channel.py#L261). **⚠️ Первичная потеря identity:** `_read_loop` знает `client`-сокет, но в `on_inbound` уходит **только `msg`** — ссылка на приславший сокет отброшена.
3. `SocketBridgeAdapter.on_inbound(msg)` — [socket_bridge_adapter.py:44](../../multiprocess_framework/modules/router_module/adapters/socket_bridge_adapter.py#L44): `router.request(msg)` → строит response `{"type":"response","channel":"backend_ctl","request_id":corr,"result":…}` — [socket_bridge_adapter.py:71](../../multiprocess_framework/modules/router_module/adapters/socket_bridge_adapter.py#L71). **Единственный адрес — имя канала**, per-connection адреса нет.
4. `router.send(response)` → `_resolve_channels` (по `channel="backend_ctl"`) → `channel.send()`.
5. `SocketChannel.send()` — **BROADCAST**: `for c in clients: c.sendall(line)` — [socket_channel.py:178](../../multiprocess_framework/modules/router_module/channels/socket_channel.py#L178).

**Push (state.changed / observability.record / log.record):**
- Строится сервером с `targets=[subscriber]`, `queue_type="system"` — напр. [delta_dispatcher.py:127](../../multiprocess_framework/modules/state_store_module/delta_dispatcher.py#L127).
- Адрес push = `subscriber`, а driver подписывается под общим `sender="backend_ctl"` — [driver.py:110](../../backend_ctl/driver.py#L110), [driver.py:1012](../../backend_ctl/driver.py#L1012).
- Маршрут: `_deliver_by_targets` → у имени `"backend_ctl"` нет очереди, но есть канал → `_deliver_via_channel` → **та же broadcast** `SocketChannel.send`.
- **Итог:** каждый driver получает каждый push любого другого driver'а — ядро проблемы.

---

## 3. Хранение соединений (текущее)

- `SocketChannel._clients: List[socket]` — [socket_channel.py:67](../../multiprocess_framework/modules/router_module/channels/socket_channel.py#L67) — **плоский список сырых сокетов, без id.**
- accept: `_clients.append(client)` + отдельный `_read_loop(client)`-поток — [socket_channel.py:215](../../multiprocess_framework/modules/router_module/channels/socket_channel.py#L215).
- Никакого `connection_id`/`session_id`/словаря-по-id нет. Identity сокета доступна только внутри read-потока и никуда не доносится.

---

## 4. «Где резать» — 5 точек для D.1a

| # | Файл:строка | Что сейчас | Что нужно |
|---|---|---|---|
| 1 | socket_channel.py:67 | `_clients: List[socket]` | словарь `conn_id → socket` (id при accept) |
| 2 | socket_channel.py:261 | `on_inbound(msg)` теряет `client` | пробросить `conn_id` в адаптер |
| 3 | socket_channel.py:178 | `send()` broadcast всем | адресная отправка по `conn_id` (fallback broadcast — за флагом) |
| 4 | socket_bridge_adapter.py:71 | envelope несёт только `channel` | нести обратный per-connection адрес |
| 5 | delta_dispatcher.py:130 + driver.py:1012 | push по общему `"backend_ctl"` | subscriber per-session уникальный |

---

## 5. ⚠️ РАЗВИЛКА ДИЗАЙНА — решение владельца ДО кода

Как адресовать reply/push конкретному соединению. Два варианта:

**Вариант A — conn_id на транспортном слое (рекомендую).** SocketChannel держит `{conn_id: sock}`; `on_inbound(msg, conn_id)`; клиент генерирует `session_id` (uuid) при connect и шлёт его в каждом сообщении (поле `session`); канал маппит `session → conn`. Reply/push, несущие `session`, отправляются в один сокет; без `session` — broadcast (back-compat). **Плюс:** RouterManager НЕ трогаем (адресация внутри канала) → минимальный blast-radius на системный транспорт (прямо гасит риск плана). **Минус:** канал становится «умнее» (маппинг session↔conn, снятие при disconnect).

**Вариант B — уникальное имя канала/подписчика per-session (router-level).** Каждое соединение = свой канал `"backend_ctl#<sid>"` в router registry; reply_to/subscriber = это имя. **Плюс:** адресация чисто через router. **Минус:** динамическая регистрация/снятие каналов на connect/disconnect, движение в системном router registry — выше риск.

**Отклонено заранее:** аутентификация/TLS — endpoint dev-only на localhost за гейтом (см. родитель, P2 §7).

Рекомендация: **Вариант A за флагом.** Владелец — выбрать A/B и подтвердить, что «клиент шлёт session в каждом сообщении» приемлемо (driver-side правка [transport.py:111](../../backend_ctl/transport.py#L111)).

### РЕШЕНИЕ (2026-07-19, Fable, верифицировано чтением)

**Вариант A.** B отклонён окончательно: требует мутаций системного `channel_registry` из сокет-потоков на каждый connect/disconnect (гонки со снапшотами `_resolve_channels`, утечки регистраций при крэше клиента) и ≥3 точек teardown — ровно тот риск, что план назвал главным.

Ключевая находка Fable сверх исходного эскиза: в router **уже есть** иерархическая dotted-адресация (P0.2, [address.py](../../multiprocess_framework/modules/message_module/addressing/address.py)) и мост Ф1.1b ([router_manager.py:391-408](../../multiprocess_framework/modules/router_module/core/router_manager.py#L391)). Значит push с `targets=["backend_ctl.<sid>"]` доезжает до `SocketChannel.send` **без правок router и трёх push-строителей** — это радикально сужает blast-radius A. Механика: identity едет **in-band** полем `session` (reply) и dotted-суффиксом subscriber (push); резолвит **только канал**. Смена сигнатуры `on_inbound` и `{conn_id:sock}` из эскиза §6 **не нужны** — см. переписанный §6.

---

## 6. D.1a — Steps по файлам (Вариант A, механика Fable — верифицирована 2026-07-19)

> Отличие от прежнего эскиза: НЕ `{conn_id: sock}` и НЕ смена сигнатуры `on_inbound`. Identity едет **in-band** полем `session`; push — dotted-subscriber через существующий мост Ф1.1b ([router_manager.py:391-408](../../multiprocess_framework/modules/router_module/core/router_manager.py#L391)); router и три push-строителя **не трогаем**.

1. **socket_channel.py:** добавить `_sessions: Dict[str, socket]` **рядом с `_clients` под тем же `_clients_lock`**. `_read_loop`/`_handle_line` пробрасывают свой `client`-сокет внутренне (внешняя сигнатура `on_inbound(msg)` неизменна); при `msg["session"]` — upsert `_sessions[sid]=client` (bind, 1 точка, self-heal на reconnect). `send()`: резолвер `sid = message.get("session")` **или** `_address[1]` (если `_address` — список >1 и `[0]==self._name`); при ON+sid-в-мапе → один сокет; при ON+sid-нет → `{"status":"error","reason":"session not connected"}` (**НЕ broadcast**); без sid → broadcast (back-compat). Unbind — 1 точка в `_drop_clients` (reverse-scan по значению-сокету). `get_info()` += `sessions`.
2. **socket_bridge_adapter.py:** `sid = msg.pop("session", None)` — **всегда**, до `router.request(msg)` (поле не течёт во внутренние handler'ы). Эхо `response["session"]=sid` — **только при флаге ON** (при OFF wire бит-в-бит сегодняшний).
3. **backend_ctl_endpoint.py:** резолв флага `session_isolation` рядом с `is_enabled` (config `backend_ctl.session_isolation` OR env `BACKEND_CTL_SESSION_ISOLATION=1`); вниз — **параметром конструктора** `SocketChannel(..., session_isolation=)` и `SocketBridgeAdapter(..., session_isolation=)`, не через `send()` и не чтением env в канале ([backend_ctl_endpoint.py:92](../../multiprocess_framework/modules/process_manager_module/process/backend_ctl_endpoint.py#L92)).
4. **driver.py / transport.py (клиент):** `sid = uuid4().hex[:12]` в `connect()` (per-connection); `transport._send_raw`/`request` кладёт `message.setdefault("session", sid)` в каждое сообщение. `driver._sender` **не трогаем** (`"backend_ctl"`, светится в логах/handler'ах). Отдельный `driver._subscriber = f"backend_ctl.{sid}"` — дефолт `subscriber` для tail/subscribe/watch (driver.py:747/760/804/909/1012 — уже параметризованы, правка в одном дефолте).
5. **Push-изоляция (проверка, не правка):** driver подписан как `backend_ctl.<sid>` → `targets=["backend_ctl.<sid>"]` едет мостом Ф1.1b до `SocketChannel.send` с `_address=["backend_ctl","<sid>"]`. Три строителя (delta/record_forward/router_push) **не меняем** — покрыть сквозным характеризационным пином моста с dotted-target.

Каждый Step — отдельный коммит с падающим-на-pre-fix характеризационным тестом (дисциплина backend_ctl).

---

## 7. D.1b — supervision-ручка (источники готовы частично)

- **restart-count — УЖЕ есть:** `ProcessMonitor.get_stats()` → `restart_counts` → команда `system.stats` ([process_monitor.py:1183](../../multiprocess_framework/modules/process_manager_module/monitor/process_monitor.py#L1183), [process_manager_process.py:470](../../multiprocess_framework/modules/process_manager_module/process/process_manager_process.py#L470)).
- **incarnation/epoch — существуют, наружу НЕ отдаются:** `_incarnations` / `_routing_epoch` монотонны per-process, растут при рестарте ([process_manager_process.py:1145](../../multiprocess_framework/modules/process_manager_module/process/process_manager_process.py#L1145)). ⚠️ Семантика — routing-fence; для supervision переиспользуемы, но надо добавить introspect-ручку/расширить `get_stats()`.
- **last_exit (exitcode) — транзиентно** в `ProcessMonitor.previous_states[...]["exitcode"]`, наружу нет — добавить.
- **supervisor-события** уже в StateStore `processes.<name>.supervisor.*` ({crashed/unresponsive/restarting/recovered/gave_up}) — driver их уже видит (overview `recent_recovery`).
- **Steps:** (1) расширить `get_stats()`/новая introspect-ручка: incarnation/epoch/last_exit наружу; (2) `supervision_status(process?)` в driver+MCP; (3) `supervise(process, action=restart|drain_restart|set_policy)`; (4) **epoch в каждом событии**.

---

## 8. Связь с B.1 (epoch-гейтинг курсоров) — обязательно

Generation-токен курсоров EventHub ловит только пересоздание **driver'а** (транспорт), НЕ рестарт наблюдаемого **процесса**. D.1b обязан протянуть epoch наблюдаемого процесса в события так, чтобы курсорная плоскость B.1 давала `reset_required` при смене инкарнации — иначе курсор молча читает **через границу рестарта**. Это записанный долг из ревью B.1 (2026-07-19).

## 9. Флаг отката (одобрено с правками Fable)

Session-isolation — **за флагом**, broadcast остаётся дефолтом (`default=off`) до доказательства.
- **Источник (OR, зеркально `is_enabled`):** config `backend_ctl.session_isolation` ИЛИ env `BACKEND_CTL_SESSION_ISOLATION=1` (escape-hatch для тестов/CI без правки yaml).
- **Резолв — одна точка:** `setup_backend_ctl_channel` рядом с `is_enabled` ([backend_ctl_endpoint.py:33](../../multiprocess_framework/modules/process_manager_module/process/backend_ctl_endpoint.py#L33)); вниз — **параметром конструктора** канала и адаптера (конфигурация топологии, не свойство сообщения; env в канал не течёт).
- **Асимметрия pop:** `msg.pop("session")` в адаптере — **всегда, вне флага** (защита внутренней маршрутизации от просачивания поля). Флаг гейтит только эхо `session` в response и адресный `send`.
- **Инвариант:** при ON + неизвестный sid → **error, НЕ fallback в broadcast** (иначе изоляция дырявая на гонке disconnect) — закрепить отдельным пином.

## 10. Контракт-тесты изоляции (характеризация ПЕРЕД правкой, пины исправлены Fable)

- **Реально ломающиеся пины — broadcast в `test_socket_channel.py`** (счётчик `clients: sent`), НЕ `test_response_shape` (он assert'ит по-ключево → аддитивное `session` его не ломает) и НЕ `test_request_called_with_same_msg` (в `_msg()` нет session → pop не виден). Характеризовать надо broadcast-путь канала. ⚠️ Верифицировать фактические имена тестов перед правкой.
- **extra-field tolerance (двойной пин):** (а) команда с лишним top-level полем (`session`) обрабатывается системой идентично (version skew driver↔сервер); (б) событие с неизвестными top-level полями (`_address`) диспетчеризуется клиентом нормально.
- **Сквозной пин моста Ф1.1b:** `targets=["backend_ctl.<sid>"]` доезжает до `SocketChannel.send` (такого пина, похоже, нет — добавить).
- **Ядро-инвариант (red pre-fix → green post):** два клиента на одном порту не видят reply/push друг друга; при ON+unknown sid → drop, не broadcast; при OFF → бит-в-бит broadcast даже при наличии `session` в сообщении.
- **Бонус-acceptance:** `log_untail` одной сессии не снимает хвост другой (два клиента, разные sid).
- `supervision_status` читает incarnation/restarts; события несут epoch.

## 11. Acceptance (из родителя)

- [x] **два клиента на одном порту не видят реплаи/события друг друга** — D.1a закрыт (`test_session_isolation.py`, 4 теста: distinct subscribers, reply не течёт, push адресный, ghost→никому)
- [x] **`supervision_status` читает incarnation/restarts** — D.1b закрыт (команда `supervision.status`: epoch + per-process incarnation/restart_count/last_exit/status; driver+MCP tool). *«события несут epoch»* — supervisor-события (`processes.<name>.supervisor.event`) несут переход рестарта (сигнал смены инкарнации) и гейтят курсоры; численный epoch/incarnation в КАЖДОМ событии — follow-up (требует плумбинга через shared push-пути, которых D.1a избегал).
- [x] **epoch наблюдаемого процесса гейтит курсоры B.1** — §8 закрыт driver-side: EventHub ротирует generation-токен на supervisor-**`recovered`** (новая инкарнация ожила — момент, с которого возможно чтение «сквозь» границу) → курсор «до» даёт `reset_required`. `crashed`/`gave_up` НЕ ротируют (ревью-фикс #3: процесс мёртв, thrashing без пользы). Гранулярность — глобальный токен (per-process/per-plane точность — follow-up, ревью #4).

### Прогресс D.1a (2026-07-19) — ЗАКРЫТ

Коммиты на ветке `feat/bctl-d1-session-isolation`:
1. `docs(plans)` — гейт §5=A + механика Fable.
2. `test(tooling)` — характеризация (broadcast fan-out, version-skew tolerance).
3. `feat(framework)` — SocketChannel: `_sessions` + адресный `send` + unbind + флаг.
4. `feat(framework)` — адаптер pop/echo + endpoint резолв флага + `get_info.session_isolation`.
5. `feat(tooling)` — клиент: sid per-connect + инъекция + dotted-subscriber + replay-retarget.
6. `test(tooling)` — acceptance два driver'а изолированы.

sentrux-дельта против baseline: signal 7008→7008 (Δ0), циклов +0, 0 нарушений. Регрессии тестов — только pre-existing env (2 live-теста observability + порт-8765 конфликт от подвисшего бэкенда).

### Прогресс D.1b + §8 (2026-07-19) — supervision-чтение + гейтинг ЗАКРЫТЫ

Коммиты (продолжение ветки):
7. `feat(framework)` — команда `supervision.status` (epoch + per-process incarnation/restart/last_exit/status) + monitor `get_supervision_snapshot`.
8. `feat(tooling)` — driver `supervision_status` + MCP tool (SAFETY_READ).
9. `feat(tooling)` — §8 epoch-гейтинг курсоров: EventHub ротирует generation-токен на supervisor-границе рестарта.

**Отложено (follow-up, НЕ acceptance-gating):**
- **`supervise(process, action=restart|drain_restart|set_policy)`** (§7 step 3) — `restart` уже доступен через `process.restart`/`send_command`; `drain_restart`/`set_policy` требуют НОВОЙ machinery (drain-примитив, live-мутация RestartPolicy) — отдельная задача, чтобы не полуфабрикатить.
- **Численный epoch/incarnation в КАЖДОМ событии** — сейчас supervisor-события несут переход рестарта (сигнал), §8 гейтит по нему. Стамп incarnation во ВСЕ push потребовал бы правки shared push-путей (delta/record_forward/router_push), которых D.1a намеренно избегал. Кандидат вместе с per-process точностью гейтинга (сейчас — safe superset).

**CAPABILITIES.yaml** (новая команда `supervision.status`) — перегенерировать на рабочем харнессе (`python -m backend_ctl.dump_capabilities`); в текущем окружении харнесс сломан (introspect-хендлеры не регистрируются), дамп вырождается — отложено владельцу/CI. `test_dump_matches_committed` (harness_smoke) уже был красным на main (telemetry-дрейф config.reload).

### Формальное ревью (2026-07-19, xhigh, 10 углов) — 7 находок, все закрыты

- **#1 (MED-HIGH)** зомби-подписка: retarget subscriber теперь на **import** (ключ реестра согласован с текущим subscriber → `*_untail` реально снимает намерение). Коммит `fix(tooling): ревью #1`.
- **#3/#4 (MED)** курсоры ротируются **только на `recovered`** (не crashed/gave_up) — убран reset-thrashing в crash-loop; per-process точность гейтинга — follow-up. Коммит `fix(tooling): ревью #3/#4`.
- **#5/#7 (MED/LOW)** hardening bind: чужой сокет не угоняет session (reject+log), тот же сокет — no-op. Коммит `fix(framework): ревью #5/#7`.
- **#6 (LOW)** guard non-dict `data` в `supervision.status`. Коммит `fix(framework): ревью #6`.
- **#2 (MED, altitude)** клиент шлёт session/dotted-subscriber безусловно (независимо от серверного флага) — **принято как дизайн** (клиент не знает флаг сервера; адаптер pop'ает session, изоляция гейтится сервером); вредное следствие (#1) устранено.

**Осталось по D.1:** merge (owner-gated) → разблокирует D.2. Опц. follow-up: `supervise`-действия, per-event numeric epoch, per-process точность гейтинга курсоров.

## 12. Риски

| Риск | Митигация |
|---|---|
| Трогаем системный транспорт (`socket_channel`/router) | Вариант A + механика Fable: правка ТОЛЬКО канал+адаптер+клиент; router и push-строители не трогаем (dotted-subscriber едет мостом Ф1.1b); baseline sentrux 7008; за флагом |
| Ломаются пины формы ответа | переписать как характеризацию ДО внедрения (§10 испр.: реально ломается broadcast-пин канала, не `test_response_shape`) |
| `session` просачивается в handler'ы через `router.request(msg)` | `pop("session")` в адаптере ВСЕГДА, до request (вне флага) |
| `_address` утекает на wire к клиенту | безвредно (клиент матчит по `type`/`request_id`); закрепить пином extra-field tolerance |
| Version skew: старый driver без session при ON | получает broadcast-ответы; dispatcher дропнет по чужому `request_id` (карантин Task 0.2); изоляция — только session-несущим клиентам; задокументировать в README |
| Осиротевшие durable-подписки `backend_ctl.<sid>` мёртвой сессии | push дропаются на канале (как «no clients» сегодня, очередь не копится); регистрации накапливаются — cleanup/TTL **out-of-scope D.1, вход D.2**; проверить, что WatchController при reconnect переоформляет подписку под новый sid |

---

## Порядок исполнения

0. **Владелец одобряет §5 (A/B) + §8/§9.** ← гейт
1. Ветка `feat/bctl-d1-session-isolation`; baseline `sentrux session_start`.
2. Характеризация (§10) → зелёная.
3. D.1a Steps (§6) по одному коммиту.
4. D.1b (§7) + epoch-гейтинг B.1 (§8).
5. Формальный `/code-review` → merge. Обновить `AGENTS.md`/README (новые MCP-ручки).
6. Разблокирован **D.2** (streamable-HTTP мультиклиент).
