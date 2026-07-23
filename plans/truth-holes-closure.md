# truth-holes-closure — закрытие оставшихся дыр прозрачности и управления

> Предлагаемый слаг: `truth-holes-closure` → `plans/truth-holes-closure.md`, ветка `fix/truth-holes-closure`.
> Преемник закрытого `backend-ctl-proof-discipline` (правило «один активный план на инструмент»).
> Основание: глубокий live-анализ 2026-07-22 (`docs/audits/2026-07-22_backend-ctl-deep-live-analysis.md`), коммит фиксов 9a0f4137.

## Контекст

Live-анализ закрыл 3 UNPROVEN и починил 4 «вранья» инструмента (config.reload, health.report,
set_register_verified, system_command-контракт). Остались дыры, мешающие цели владельца
«прозрачная система, инструмент чётко показывает правду, всем можно управлять»:

1. **gui-шторм (главная)**: PM шлёт каждую state-мутацию отдельным `state.changed` в never-drop
   system-очередь gui; gui дренирует ~18 сообщ/с → очередь вечно 85–94/100, команды не могут войти →
   gui слеп (introspect/ui_*/подписки), PM `router.errors`=25k — это backpressure.
2. **Замена инстанса невидима в supervision**: `process.restart` при reuse-очередей (дефолт) не
   бампает incarnation (осознанно, DECISIONS PMM:311-333), restart_count считает только краш-рестарты —
   pid сменился, а supervision-снимок не отличим от «ничего не было».
3. **Ротация логов**: видимость провала уже починена (`_SafeRotatingFileHandler`, счётчик+warning),
   но КОРЕНЬ жив — ротация систематически не срабатывает (645МБ messages.log), файлы растут без предела.
4. **backend_ctl — «сигнал ≠ реальность» residual**: `reached` в fan-out = доставка, не применение;
   телеметрийный gate нечитаем (только эффект); нет диагностики «кто душит очередь X»;
   `never_drop_loss_*` идёт только в лог, мимо introspect; медленные команды выглядят отказом.

Разведка подтвердила: фикс шторма **ортогонален** `plans/transport-single-policy.md` (тот правит
канальную дверь для кадров; state идёт targets-дверью, у которой QoS-механика уже есть) — пересечения
нет, QoS-инфраструктуру (`qos.py`, `queues/core/manager.py`) переиспользуем, не переписываем.

Решение владельца (спрошено): медленные команды — **tool-side verified сейчас, server-side job потом**
(отложенный пункт с триггером).

---

## Фаза 1 — Гашение gui-шторма (флип-лесенка, по одному флагу с замером)

Ключевые факты (проверены разведкой):
- `state_store_manager.py`: `handle_state_set`→`dispatch_single` (:203) — **одно IPC-сообщение на каждую мутацию**; межвызовного коалесцирования нет.
- `delta_dispatcher.py:135` хардкодит `queue_type="system"`; конверт уже несёт `first_revision=min/revision=max` (:123-125).
- QoS-профиль класса **"state"** (best_effort/drop_oldest) уже объявлен в `shared_resources_module/qos.py:96-113`, но не привязан ни к одной очереди.
- Gap-детектор gui (`state_proxy.py:726-782`): при разрыве revision пакет всё равно применяется + запускается resync (`state.get_subtree`) — т.е. drop конверта = один лишний round-trip, не потеря корректности.

### Task 1.1 — Tick-коалесцирование в DeltaDispatcher (`FW_STATE_COALESCE`, default OFF)
**Files:** `state_store_module/manager/delta_dispatcher.py`, `state_store_module/manager/state_store_manager.py` (lifecycle: старт flusher в initialize, финальный flush в shutdown:130), `config_module/feature_flags.py`, новый `state_store_module/tests/test_delta_coalescing.py`.
**Суть:** буфер дельт per-subscriber под `threading.Lock` (матчинг подписок — в момент мутации, чтобы новый подписчик не получил чужие буферизованные дельты); собственный daemon-flusher (тик 100–150 мс + cap ~200 дельт); flush = swap буфера под локом, отправка вне лока через существующий `_send_state_changed` (min/max revision уже считаются — **приёмник gui не меняется ни на строку**). Дедуп keep-last-per-path — ЗАПРЕЩЁН в этой задаче (ломает непрерывность revision → resync-шторм).
**Acceptance (пары):**
- [x] OFF: путь бит-в-бит, все тесты state_store зелёные — 624 passed, немедленная отправка в вызывающем потоке (unit)
- [x] ON (unit): N set-мутаций внутри тика → ровно 1 конверт, `first_revision=min`, порядок revision; сквозной с реальным StateProxy — resync НЕ запускается; shutdown-flush доставляет буфер — `test_delta_coalescing.py` 13 passed
- [x] Live-пара до/после флипа (`webcam_sketch`, 2026-07-22): `gui_system` **100/100 → 0**; `system_evict_blocked` **1466 → 0**; `errors` **1461 → 0**; доставка **267/1728 (15%) → 270/270 (100%)**; `get_status("gui")` **не отвечал → отвечает** (pid 10876, 3 воркера живы). Детали — `docs/audits/2026-07-22_phase1-flip-webcam-sketch.md`
**Out of scope:** дедуп, смена очереди, правки gui/StateProxy, ThrottleMiddleware.

### Task 1.2 — Очередь класса "state" для state.changed (`FW_STATE_QUEUE`, default OFF)
**Решение:** отдельная третья очередь, НЕ маппинг в data (data дренируется `_data_receiver_loop` gui в чужом потоке, там `state.changed` классифицировался бы как kind="command" в `bridge_impl.py:83-94`, и data делится с кадрами).
**Files:** `process_module/configs/process_launch_config.py:14-17` и `process_manager_module/process/process_manager_process.py:197` (дефолт `"state": {"maxsize": 8}` — очередь создаётся всегда, аддитивно), `shared_resources_module/state/process_data.py:33-34` (константа), `delta_dispatcher.py:135` (под флагом `queue_type="state"`), `process_module/threads/system_threads.py:69` (`channel_types=["system","state"]`), `feature_flags.py`, тесты qos/router/process_module.
**Суть:** очередь/каналы возникают из конфига автоматически (`process_registry.py:109-110`, `process_communication.py:84-100` генеричны); `_deliver_by_targets` уважает `msg["queue_type"]` (`router_manager.py:411-413`) → drop_oldest из готовой механики `remove_old_if_full`. Подписчик backend_ctl не задет (у него нет очереди — мост Ф1.1b идёт каналом). Глубина 8 (не history_depth=1 профиля): каждый evict = resync round-trip, 8 амортизирует burst — расхождение с профилем зафиксировать комментарием.
**Acceptance (пары):**
- [x] OFF: полный прогон зелёный (1770 passed по 4 suite), `state`-очередь объявлена аддитивно (`test_default_queues_include_state`), queue_type="system" бит-в-бит (`test_off_routes_to_system`); live-`introspect_queues` `{proc}_state`=0 — за координатором
- [x] ON (unit): конверт уходит в `state` (`test_on_routes_to_state`, ортогонально коалесцированию); переполнение → `data_evicted`-инкремент, НЕ `system_evict_blocked`, на обоих путях `FW_QOS_PROFILES` (`test_full_state_queue_evicts_not_blocks`); контраст system остаётся never-drop; StateProxy-resync по разрыву revision — механизм покрыт gap-детектором (Task 1.1 сквозной), полная сходимость после дропа — live
- [x] Live (`webcam_sketch`, 2026-07-22): искусственный флуд не понадобился — **рецепт штормит сам** (baseline: 597+ безвозвратных потерь в gui за ~30с, ~30/с). При ON: `gui_system` **0**, `gui_state` **0**, `get_status("gui")` отвечает; `sent_via_targets.state` **247** (конверты ушли в state-очередь), `queue_data_evicted` **89** — drop_oldest штатно роняет старые снимки вместо блокировки команд; строк «ПОТЕРЯ СООБЩЕНИЯ» в логе **нет**. `ui_tap_ping` — честное «тап не включён (нужен ui.tap.subscribe)» → Task 1.4
**Out of scope:** kind-каналы (FW_USE_KIND_CHANNELS), канальная дверь (transport-plan), глубины data/system.

### Task 1.3 (ОПЦИОНАЛЬНАЯ, measure-gated) — Батч-emit в bridge (`FW_GUI_STATE_BATCH`)
Делать ТОЛЬКО если после флипа 1.1+1.2 замер покажет давление на Qt main thread (темп `_deliver.emit` > ~200/с через gui_local_metric). Дизайн: один `dispatch(data_type="state_delta_batch")`, разворачивание в per-delta вызовы существующих `_state_cb`/`_state_listeners` уже в main thread (`frontend/process.py`, `frontend/state/delta_message.py`, `frontend/bridge_impl.py`) — потребители не меняются.

### Флип-протокол Фазы 1 (память `project_f7_g7_flip_ladder`)
baseline-замер → `FW_STATE_COALESCE=1` → замер → `FW_STATE_QUEUE=1` → замер → решение по 1.3 → решение о default-ON обоих флагов (отдельный коммит). Каждый замер (backend_ctl, live webcam_sketch): `introspect_queues` (глубины gui_system/gui_state), `introspect_router_stats` PM (дельты `system_evict_blocked`/`data_evicted` за 60с), `get_status("gui")`, `ui_tap_ping`, `watch_like_gui` 30с (дельты живы), `log_tail(gui)` (нет цикличных resync). **Критерий успеха фазы: gui отвечает на introspect/ui_tap, `gui_system` ≈ 0, `system_evict_blocked` заморожен.**

### Task 1.4 — ui_*-плоскость: доказательство парой (закрытие NA) — [x] ЗАКРЫТ 2026-07-22
Live на `webcam_sketch` (флаги ON, `QT_MCP_PROBE=1`):
- [x] `ui_tap` → `success`, `subscriber=backend_ctl.0b245cfb5956`, `command=ui.event`, `sources=[gesture, command]`
- [x] `ui_tap_ping` → `events_sent=3, send_errors=0`; событие в `events_page(plane=ui)` (`kind=ping`, note совпал)
- [x] **Реальный клик** через qt-mcp → `ui.event` с полной атрибуцией: `kind=button`, `text="Audit log"`, `widget=QPushButton`, полный `path` в дереве виджетов; иерархический адрес `_address=[backend_ctl, 0b245cfb5956]`; `dropped=0`
- [x] `ui_untap` → **тишина**: повторный клик дал 0 событий (проверено курсором)

Вечное «ui_* NA» прошлых верификаций закрыто. Детали — `docs/audits/2026-07-22_phase1-flip-webcam-sketch.md`.

**Побочная находка (residual → Фаза 4/5): «No handler for key» врёт про причину.**
Первый вызов сразу после boot упал с `No handler for key 'ui.tap.subscribe'`, хотя команда
существует — gui был объявлен готовым по liveness-fallback (`'gui' ready via liveness-fallback
(event не пришёл за 5.0s)`) ДО регистрации своих команд. Сообщение читается как «фичи нет»,
хотя правда — «ещё не готов». На прогретой системе тот же вызов проходит. Инструмент обязан
различать «нет такого хендлера» и «процесс ещё не поднял хендлеры».

---

## Фаза 2 — Правда supervision: замена инстанса видима

### Task 2.1 — pid/started_at/instance_restarts в supervision.status
**Files:** `process_manager_module/process/process_manager_process.py` (`_cmd_supervision_status` :485-512, `restart_process` :1875-1949), `monitor/process_monitor.py` (snapshot :1220-1231), `backend_ctl/protocol.py`/`driver.py` (проброс полей), тесты обоих модулей + `backend_ctl/tests/test_fencing_live.py` (дополнить плечом «reuse-restart: incarnation 0→0, но pid сменился и manual_restarts вырос»).
**Суть:** не трогая fence-семантику (reuse-restart осознанно не фенсится), сделать замену инстанса ВИДИМОЙ: в per-process supervision-снимок добавить `pid` (истина ОС), `started_at` и счётчик `instance_restarts` (безусловный инкремент в `restart_process`, в отличие от условного `_bump_incarnation`). `restart_count` оставить как есть (краш-рестарты) с пояснением в описании команды.

**Правка спеки по ревью Fable (2026-07-23):** имя `manual_restarts` из исходной спеки — **ложь**: авто-рестарт монитора приходит в PM той же командой `process.restart` и попадает в тот же счётчик. Поле названо `instance_restarts` (любая замена инстанса оркестратором), происхождение замены не заявляется.

**Acceptance:**
- [x] Пара (unit): reuse-restart → incarnation прежняя, `instance_restarts` +1, `started_at` обновлён; no-reuse-restart (форс `ids_before != ids_after`) → incarnation бампается как раньше — `test_supervision_instance_truth.py`, 12 passed. **Смена самого `pid` — live-плечо** (mock даёт детерминированный pid по имени), см. ниже
- [x] `supervision_status` несёт новые поля (`pid`/`alive`/`started_at`/`instance_restarts`) — passthrough драйвера сырым dict, описания MCP/driver/AGENTS.md обновлены, `docs/contracts/CAPABILITIES.*` перегенерированы
- [x] Ревью Fable (итерация 1, 7/10 → фиксы): (1) честное имя поля + тест авто-пути; (2) `_cleanup_process_resources` снимает хвосты — иначе снятый процесс висит призраком в снимке, а новый одноимённый наследует чужой счётчик (`_incarnations` НЕ чистится осознанно — fence-плоскость); (3) bulk-старт метит только реально стартовавших; (4) оговорка про тривиальность reuse-плеча в моке
- [x] **Live (`webcam_sketch`, 2026-07-23)**: два рестарта `lines` → `pid` **24808 → 26476 → 17748**, `instance_restarts` **0 → 1 → 2**, `started_at` обновился, `incarnation` **0 всё время** (reuse-очередей, fence цел), `restart_count` **0** (краш-счётчик не подменён), `epoch` 0→1→2 как раньше. Дыра «замена инстанса неотличима» закрыта
- [x] **Live-находка, починена**: PM отдавал про СЕБЯ `pid=null/alive=null` — он не состоит в собственном реестре. Теперь подставляет `os.getpid()` для своего имени (у чужих имён без записи в реестре остаётся `null` — тест-контраст). Перепроверено свежим boot: `pid=29592, alive=true`

---

## Фаза 3 — Ротация логов: корень, не видимость

### Task 3.1 — Диагноз-репро + фикс конкуренции ротации
**Files (диагноз определит точный набор):** `logger_module/channels/log_channel.py` (`_SafeRotatingFileHandler`), `logger_module/configs/logger_manager_config.py` (канал `messages_file` + module-канал `router_messages` — **оба пишут в один `messages.log` двумя хэндлерами одного процесса** — главный подозреваемый), тесты logger_module.
**Steps:**
1. Репро под контролем: маленький `max_size` (например 64КБ) → live-прогон → показать, что rollover систематически падает (`_rollover_failures` растёт) и КТО держит файл (два хэндлера в одном процессе vs чужой процесс).
2. Фикс по диагнозу; кандидат по умолчанию — развести `messages_file` и `module_router_messages` по разным файлам ЛИБО один общий handler на файл в рамках процесса (реестр хэндлеров по resolved-path); при межпроцессной конкуренции — ротация с retry+reopen.
3. Live-пруф: с малым max_size ротация происходит (появляются `.1`-бэкапы), `_rollover_failures` не растёт.
**Диагноз подтверждён и починен** (`2a48ebe8`): `messages_file` и module-канал `router_messages`
пишут в ОДИН `messages.log` двумя `_SafeRotatingFileHandler` → на Windows `doRollover`→`os.rename`
падает WinError32, пока второй fd открыт. Фикс — per-process refcounted реестр хэндлеров по
абсолютному пути (каналы с тем же файлом делят один ротатор).

**Acceptance:**
- [x] Пара: до фикса — репро провала (`_rollover_failures` растёт, `.1` не появляется), после — живая ротация на том же сценарии — `test_rotation_shared_handler.py`, 8 тестов (конкуренция fd эмулируется кросс-платформенно, assert на ФАКТ провала)
- [x] Полный suite logger_module зелёный (59 passed); `test_rollover_visibility.py` не деградировал
- [x] **Live (2026-07-23)**: на живом `webcam_sketch` ротация сработала штатно — `camera_0/system.log.1` = **10 485 676 байт** (ровно лимит), базовый файл начался заново; жалоб «Ротация лог-файла … не удалась» в логах нет
- [x] **Live на файле-виновнике**: `messages.log` (два канала, продовый max_size 10 МБ, реальная сборка `LoggerCore`, ускорена только скорость записи) ротировался **дважды**: `.1` и `.2` по 10.0 МБ, базовый 6.53 МБ, `_rollover_failures` = **0**, `scope_ch.handler is module_ch.handler` = True. До фикса тот же сценарий давал вечный рост (645 МБ на живом прогоне)

---

## Фаза 4 — backend_ctl: правда и удобство (инструментный трек)

### Task 4.1 — `introspect.telemetry`: readback телеметрийного gate
**Files:** `process_module/commands/builtin_commands.py` (`_register_introspect_commands` :348, шаблон — `_cmd_introspect_queues` :637), `backend_ctl/driver.py`, `backend_ctl/mcp_tools.py` (новый read-инструмент `introspect_telemetry`), тесты.
**Суть:** тонкая обёртка над уже существующими `heartbeat.current_telemetry_publish()` (`process_heartbeat.py:362`) + `current_unknown_metrics()` (:350): эффективная publish-секция без записи. Закрывает «gate виден только по эффекту».
**Acceptance:**
- [x] Unit: 14 тестов (`test_introspect_telemetry.py`) — gate off даёт честную `note` (не пустоту), `resolved` разворачивает наследование `default_interval_sec`, опечатка видна после факта, throttle-плоскость `null` у процесса без StateStoreManager, readback ничего не пересобирает
- [x] **Live (`webcam_sketch`, 2026-07-23)**: `lines` на boot — `gate_active=false` + причина; `gated_metrics` полон; у ProcessManager видны **7 правил central-троттла** (все 0.05с) — вторая плоскость перестала быть невидимой. Детали — `docs/audits/2026-07-23_phase4-live-acceptance.md`
- [x] Пара после записи (см. Task 4.2): `fps.enabled` **false → true** читается в `resolved`

### Task 4.2 — Честная семантика fan-out: `delivered`, не `reached`
**Files:** `process_manager_process.py` (`_cmd_telemetry_broadcast` :1561-1568), `backend_ctl/driver.py` (`_flag_unreached_metric`), доки/тесты.
**Суть:** в ответ добавить `semantics: "delivered"` (или переименовать с алиасом) + в driver-обёртке `telemetry_set` опциональный `verify=true`: после команды — readback через Task 4.1 и поле `verified_effect` (паттерн `set_register_verified`). Не блокируем, только маркируем (консервативность E.2).
**Acceptance:**
- [x] Unit: 8 тестов (`TestTelemetrySetVerify`) — применилось/не применилось/опечатка/gate off/fan-out без адресата/дельта только с `interval_sec`; плечо OFF (без verify — ответ бит-в-бит, лишнего IPC нет) + `semantics="delivered"` на стороне PM
- [x] **Live (`webcam_sketch`, 2026-07-23)**: `fps enabled=false` → `verified_effect=true` (`observed.enabled=false`); обратно `enabled=true` → `verified_effect=true`; опечатка `latency` → **`verified_effect=false`** + «не входит в GATED_METRICS». У ВСЕХ трёх `reached=1` — охват одинаков, различает только readback
- [x] **Фикс по ревью (Fable, minor 4)**: `resolved` разворачивает дефолты, поэтому запрос `enabled=True` совпал бы с наследованием даже при потерянной дельте — вакуумное «да». Теперь требуется НАЛИЧИЕ ключа метрики в сырой `publish.metrics`; совпадение с дефолтом без правила → `false` с причиной. Пара тестов (правило есть / только совпадение)

### Task 4.3 — «Кто душит очередь X»: per-sender учёт + потери в introspect
**Files:** `router_module/core/router_manager.py` (`_deliver_by_targets` :416+), `shared_resources_module/queues/core/manager.py` (`_report_never_drop_loss` :404-440 — счётчики в `get_stats`, а не только в лог), `queue_channel.py` (`get_info`), `backend_ctl/protocol.py` (missing-контракт для новых полей — BCTL-ADR-007), тесты.
**Суть:** словарь-счётчик put'ов по `message["sender"]` per-очередь (cap кардинальности ~32 отправителя), экспонировать в `introspect.router_stats`/`introspect.queues`; `never_drop_loss_total` — в `get_stats` (сейчас только `_fallback_logger`, мимо introspect). Новый счётчик обязан показать ненуль live (BCTL-ADR-007).
**Сужение против Files (осознанно):** `queue_channel.py::get_info` и `introspect.queues` НЕ тронуты — учёт живёт на стороне ОТПРАВИТЕЛЯ (`QueueRegistry` → `router_stats`), а `introspect.queues` receiver-side и под затором сам не доходит (то самое ограничение из Task 4.5). Вторая точка агрегации не заводилась намеренно.
**Acceptance:**
- [x] Unit: 11 тестов (`test_queue_sender_attribution.py`) — атрибуция put/lost, `__unknown__` для груза без `sender` (пропуск исказил бы сумму), потолок кардинальности с ведром `__other__`, снимок-копия, экспозиция в `get_stats`; + 2 теста `RouterStats` (missing-контракт: `None` ≠ `0`)
- [x] **Live С флагами Ф1 (`webcam_sketch`, 2026-07-23)**: 9 очередей под учётом; `gui_state` → топ-отправитель **`StateStore`, put=901**; `*_system` → **`ProcessManager`** (31–35); потерь **0**, `data_evicted`=**106** (drop_oldest штатно)
- [x] **Live БЕЗ флагов Ф1 — плечо ненуля (BCTL-ADR-007, по требованию ревью)**: `queue_never_drop_loss_total`=**1702**; в `gui_system` **`StateStore` put=1871/lost=1687** против `ProcessManager` put=32/lost=15. Счётчик не просто ненулевой — он **назвал душителя поимённо** (подозреваемые различаются в ~100 раз); прежний `system_evict_blocked` давал только факт затора. Вопрос «кто душит» получает ответ ИМЕНЕМ, а не глубиной

### Task 4.4 — `process_restart_verified`: pid-proof одним вызовом (решение владельца: tool сейчас)
**Files:** `backend_ctl/driver.py`, `backend_ctl/mcp_tools.py`, live-тест.
**Суть:** обёртка: pid-до (`introspect_memory`) → `system_command{cmd: process.restart}` (терпим timeout ответа) → поллинг pid/ready (до N сек) → `{restarted: true, pid_before, pid_after, elapsed}`. Плюс `supervision_status`-поля из Task 2.1 в ответе.
**Acceptance:**
- [x] Unit: 6 тестов (`test_restart_verified.py`) — главный: **ответ `timeout` при сменившемся pid → `restarted=true`** (ответ команды стал справкой, не вердиктом); обратное плечо: `success` при неизменном pid → `restarted=false` + причина
- [x] **Live (`webcam_sketch`, 2026-07-23)**: рестарт `lines` — `restarted=true`, **pid 4712 → 22124**, `instance_restarts` **0 → 1**, `elapsed` **6.42 с**, за ОДИН вызов; `linez` (опечатка) → `restarted=false` + «не найден» и **ни одной разрушающей команды**
- [x] **Фикс по ревью (Fable, major)**: вердикт был по ОДНОЙ смене pid → «поднялся и сразу умер» читалось как успех, а переиспользованный ОС pid дал бы ложный отказ. Теперь `restarted = (pid ИЛИ instance_restarts изменились) И alive`; полуудача видна отдельным `replaced=true` + причина. Плюс «PM недоступен» больше не выдаётся за опечатку в имени. Тесты: +3 (мёртвый инстанс судится по вердикту, а не по полю; переиспользование pid; лежащий PM)

### Task 4.5 — Доки: «Известные ограничения» + stale-MCP — [x] ЗАКРЫТ 2026-07-23
**Files:** `backend_ctl/README.md` (новый раздел «Известные ограничения»), `backend_ctl/AGENTS.md` (`## Подводные камни`).
**Записано:** (а) MCP-сервер держит код на момент старта; (б) `reached` = доставка (`semantics="delivered"`), применение — через readback/verify; (в) receiver-side `introspect_queues` под затором молчит (сама команда не доходит) — надёжны счётчики отправителя `queue_senders`/`queue_never_drop_loss_total`; (г) live гонять с флагами Ф1 до флипа дефолтов; (д) медленные команды выглядят отказом → `process_restart_verified`.
**Подтверждено ходом приёмки:** запущенный MCP-сервер новых ручек не знал, и live-прогон пошёл свежим процессом-драйвером — ограничение (а) сработало на первом же шаге.

---

## Фаза 5 — Закрывающий live-прогон

### Task 5.1 — Полная верификация на webcam_sketch — [x] ЗАКРЫТ 2026-07-23
Прогон **всех 49** инструментов через ТОТ ЖЕ путь, что MCP-сервер (`dispatch_tool(DriverSession, …)`), на живом `webcam_sketch` с GUI (`QT_MCP_PROBE=1`, флаги Ф1). Аудит — [`docs/audits/2026-07-23_phase5-full-sweep.md`](../docs/audits/2026-07-23_phase5-full-sweep.md), сырые вердикты — `docs/audits/evidence_2026-07-23_phase5/`.

**Результат: 49 вызвано / 49 OK / 0 SUSPECT / 0 NA.** Плоскость `register_*` доказана на реальной мишени (`lines.edge_detection.invert`: verified → confirm → restore `written=1, skipped=127, verified=128, mismatches=[]`); `await_condition` доказан ПАРОЙ (выполнимое → `success`; невыполнимое → `timed_out` + `events_seen=342` + `last_seen` — таймаут отдаёт диагноз, не пустоту).

**Урок прогона:** первый заход дал 7 SUSPECT, и НИ ОДИН не был дефектом инструмента — все пять причин в проверяющем скрипте (чтение не того уровня конверта; усечённый ответ принят за пустой; своя фабрика драйвера без `connect()`; значения read-model — dict, а не число; отписка без подписки). Записано в `backend_ctl/README.md` § «Известные ограничения» — это ловушки ЧИТАТЕЛЯ ответов, и они уже повторялись (verify-скрипт 2026-07-17).

**Гейт выхода плана:**
- [x] gui отвечает live — `get_status(gui)` с pid, карточка `gui` в `capabilities` (8 карточек)
- [x] `ui_*` доказаны — tap (атрибуция `sources=[gesture, command]`) / ping (`events_sent=9, errors=0`) / untap
- [x] ротация живая — Фаза 3 (`system.log.1` = 10 485 676 байт; `messages.log` ротировался дважды)
- [x] supervision показывает замену инстанса — pid **11492 → 31280**, `instance_restarts` 0→1, `alive=true`
- [x] 0 инструментов с UNPROVEN-эффектом

---

## Фаза 6 — Снятие лесов: удаление флагов, а не только флип дефолтов

**Зачем отдельной фазой.** «Переключить дефолт» ≠ «убрать флаг». После default-ON OFF-ветка
остаётся в коде и требует поддержки вечно — так dark-launch превращается в костыль, а реестр
из 18 флагов становится памятником нерешённым спорам. Конечное состояние обеих задач Фазы 1 —
**один путь**, без переключателя. Установка владельца (2026-07-22): флаги не должны стать костылями.

Критерий готовности к фазе: дефолты флипнуты, soak на дефолт-ON прошёл без регресса
(метрики не хуже пары из `docs/audits/2026-07-22_phase1-flip-webcam-sketch.md`).

### Task 6.1 — Флип дефолтов обоих флагов — [x] ЗАКРЫТ 2026-07-23 (`b284c561`)
Флип `FW_STATE_COALESCE`/`FW_STATE_QUEUE` в `default=True`. Откат — env `NAME=0`.
**Acceptance:**
- [x] **soak 1 час на `webcam_sketch` БЕЗ единого env-флага** (13 замеров с шагом 5 мин): `system_evict_blocked` **0**, `never_drop_loss_total` **0**, потерь по отправителям **нет**, `errors` **0**, очереди gui **0/0/0**, gui отвечает весь час одним pid (26672), `sent_ok` вырос до **48 310**. Данные — `docs/audits/evidence_2026-07-23_phase6/soak_60min.jsonl`, разбор — `docs/audits/2026-07-23_phase6-levels-vs-edges.md`
- [x] Откат через env проверен парой (`test_state_storm_flags_are_on_by_default` / `..._rollback_via_env`) — env `=0` побеждает `default=True`
- [x] **Побочно вскрыто флипом:** 31 тест был пришпилен к СТАРОМУ транспорту (ассертили `queue_type=="system"` — путь, признанный причиной шторма) и проходил только потому, что флаг стоял OFF. Обновлены на новую истину; остальные сделаны независимыми от режима через `_deterministic_delivery` (тик flusher'а → детерминированный flush, прод-путь сохранён)

### Task 6.2 — Удалить `FW_STATE_QUEUE` вместе с OFF-веткой
**Чистый случай.** OFF-ветка — одна тернарка (`queue_type` `"state"` vs `"system"`), а очередь
`state` создаётся ВСЕГДА (аддитивно, независимо от флага), поэтому удаление = просто убрать выбор.
**Files:** `delta_dispatcher.py` (`_state_queue_type` → константа `"state"`, ctor-параметр `state_queue` убрать), `feature_flags.py` (снять декларацию), тесты (`test_state_queue.py` — плечо OFF удалить, ON стал единственным поведением).
**Acceptance:** — [x] ЗАКРЫТ 2026-07-23 (`f22435ed`)
- [x] `FW_STATE_QUEUE` как переключатель не существует: декларация снята из реестра, ctor-параметр `state_queue` убран, `queue_type` — константа. Оставшиеся вхождения — только пояснения «удалён» + регресс-якорь `test_no_state_queue_switch_left` (проверяет отсутствие И параметра, И флага в `FLAGS`)
- [x] Полный прогон: framework/modules **5303 passed**, prototype **3249 passed**, backend_ctl **528 passed**, `validate.py` чист
- [x] Live (soak Ф6.1): `system_evict_blocked`=**0** час подряд, конверты идут очередью `state`, gui отвечает
- [x] Плечо OFF в тестах удалено ОСОЗНАННО: тестировать снятую ветку — значит держать её живой и создавать иллюзию поддерживаемого пути

### Task 6.3 — `FW_STATE_COALESCE`: не флаг, а различие по классу сигнала
**Не удалять «в лоб».** Коалесцирование добавляет **до 120 мс** задержки: для уровней (FPS,
глубины, счётчики) это невидимо, для фронтов (ошибка, смерть процесса, значимый переход) —
вредно. Оставить глобальный флаг «навсегда» = ровно тот костыль, которого избегаем; удалить
без разбора = замедлить фронты.
**Целевое состояние:** выбор делает **природа сигнала**, а не переключатель — фронты идут мимо
буфера немедленно, уровни коалесцируются. Тогда флаг удаляется за ненадобностью.
**Зависимость снята:** инвентарь levels-vs-edges СДЕЛАН (2026-07-23) прямо здесь, по снимку
живой системы — 506 путей, свёрнутых до 41 формы. Разбор: [`docs/audits/2026-07-23_phase6-levels-vs-edges.md`](../docs/audits/2026-07-23_phase6-levels-vs-edges.md).

**Поправка к постановке, найденная инвентарём.** «Фронты нельзя коалесцировать — потеряются» —
неточно для ЭТОГО флага: дедуп keep-last запрещён ещё в Task 1.1, поэтому буфер сохраняет все
дельты и порядок (`A→B→A` доедет тремя дельтами в одном конверте). Потери события нет —
есть только задержка до 120 мс. А реагирующих потребителей у `state.changed` нет: подписчики —
`StateProxy`/GUI-панели, read-model backend_ctl, `telemetry_sink` (все наблюдатели); реакция
на смерть процесса живёт в `ProcessMonitor` и идёт heartbeat'ом, мимо state-плоскости.

**Статус: ОТКРЫТА, ждёт решения владельца** (не техническое — про инвариант):
- **A.** Просто удалить флаг (коалесцирование — единственный путь). ~20 строк. Цена: теряется аварийный откат env `=0`.
- **B.** Байпас для 12 форм-фронтов + удалить флаг. Дороже, список фронтов надо поддерживать, новая метрика молча попадёт в «уровни».
- **C.** Оставить флаг — как исход не рассматривается (ровно тот костыль, против которого Фаза 6).

Рекомендация: **A**, если 120 мс на state-плоскости никому не мешают (сегодня — не мешают, доказано инвентарём).
**Acceptance:** [x] классификация зафиксирована по природе сигнала; [ ] решение владельца A/B; [ ] `grep FW_STATE_COALESCE` пуст; [ ] live-пара не хуже Ф1.

---

## Отложено с триггером (не входит)

| Пункт | Триггер возврата |
|---|---|
| **Server-side async job для длинных команд** (PM: `{accepted, job_id}` + поллинг) — решение владельца «потом» | второй потребитель длинных команд (GUI-кнопка рестарта / оркестрация рецептов) |
| Канальная дверь / политика кадров | это `plans/transport-single-policy.md` — не дублировать |
| Дедуп keep-last-per-path в коалесцировании | только с конвертом «first_revision = min по поглощённым» (иначе resync-шторм) |
| Переезд backend_ctl в `tooling/` | внешний гейт codemod (как в закрытом плане) |

## Порядок и зависимости

```
Фаза 1: 1.1 → замер → 1.2 → замер → [1.3 по замеру] → 1.4;  Фаза 2 и 3 — параллельно Фазе 1 (файлы не пересекаются)
Фаза 4: 4.1 → 4.2 (verify использует 4.1); 4.3, 4.5 параллельно; 4.4 после 2.1 (поля supervision)
Фаза 5 — предпоследней (закрывающий live-прогон)
Фаза 6 — ПОСЛЕ Ф5: 6.1 флип дефолтов → soak → 6.2 удалить FW_STATE_QUEUE;
         6.3 (FW_STATE_COALESCE) ждёт инвентарь levels-vs-edges из telemetry-pull-on-demand
```

**План НЕ считается закрытым, пока живы флаги Фазы 1** — иначе dark-launch становится костылём
(установка владельца 2026-07-22). Гейт выхода Ф5 закрывает функциональность, Ф6 — леса.

Правила: флаги default OFF, флип по одному с замером; приёмка гоночного/флагового — только парами;
максимум 2 агента без worktree; каждый коммит `Refs: plans/truth-holes-closure.md` + `Why:`/`Layer:`;
live-прогоны строго одиночные (порт 8765 — ловушка двух бэкендов, подтверждена в этой сессии).

## Верификация плана целиком

1. Unit: полные suites state_store/router/process_module/logger_module/shared_resources + backend_ctl (без live) — зелёные на каждом шаге.
2. Live: флип-протокол Фазы 1 с числами в аудит-док; финальный прогон Task 5.1.
3. `python scripts/validate.py` чист; sentrux `session_start` до Фазы 1 → `session_end` после Фазы 4 — не хуже baseline.
```
