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
- [ ] Live-пара до/после флипа (протокол §Флип ниже): глубина `gui_system` 85-94 → 0-2; `system_evict_blocked` дельта за 60с = 0; `get_status("gui")` отвечает; `ui_tap_ping` OK — **за координатором, live-сессия**
**Out of scope:** дедуп, смена очереди, правки gui/StateProxy, ThrottleMiddleware.

### Task 1.2 — Очередь класса "state" для state.changed (`FW_STATE_QUEUE`, default OFF)
**Решение:** отдельная третья очередь, НЕ маппинг в data (data дренируется `_data_receiver_loop` gui в чужом потоке, там `state.changed` классифицировался бы как kind="command" в `bridge_impl.py:83-94`, и data делится с кадрами).
**Files:** `process_module/configs/process_launch_config.py:14-17` и `process_manager_module/process/process_manager_process.py:197` (дефолт `"state": {"maxsize": 8}` — очередь создаётся всегда, аддитивно), `shared_resources_module/state/process_data.py:33-34` (константа), `delta_dispatcher.py:135` (под флагом `queue_type="state"`), `process_module/threads/system_threads.py:69` (`channel_types=["system","state"]`), `feature_flags.py`, тесты qos/router/process_module.
**Суть:** очередь/каналы возникают из конфига автоматически (`process_registry.py:109-110`, `process_communication.py:84-100` генеричны); `_deliver_by_targets` уважает `msg["queue_type"]` (`router_manager.py:411-413`) → drop_oldest из готовой механики `remove_old_if_full`. Подписчик backend_ctl не задет (у него нет очереди — мост Ф1.1b идёт каналом). Глубина 8 (не history_depth=1 профиля): каждый evict = resync round-trip, 8 амортизирует burst — расхождение с профилем зафиксировать комментарием.
**Acceptance (пары):**
- [x] OFF: полный прогон зелёный (1770 passed по 4 suite), `state`-очередь объявлена аддитивно (`test_default_queues_include_state`), queue_type="system" бит-в-бит (`test_off_routes_to_system`); live-`introspect_queues` `{proc}_state`=0 — за координатором
- [x] ON (unit): конверт уходит в `state` (`test_on_routes_to_state`, ортогонально коалесцированию); переполнение → `data_evicted`-инкремент, НЕ `system_evict_blocked`, на обоих путях `FW_QOS_PROFILES` (`test_full_state_queue_evicts_not_blocks`); контраст system остаётся never-drop; StateProxy-resync по разрыву revision — механизм покрыт gap-детектором (Task 1.1 сквозной), полная сходимость после дропа — live
- [ ] Live: под искусственным флудом `state.set` — `gui_system` ≈ 0, `get_status("gui")` и `ui_tap_ping` отвечают ВО ВРЕМЯ флуда; после дропа — один WARNING «разрыв revision» + успешный resync — **за координатором, live-сессия**
**Out of scope:** kind-каналы (FW_USE_KIND_CHANNELS), канальная дверь (transport-plan), глубины data/system.

### Task 1.3 (ОПЦИОНАЛЬНАЯ, measure-gated) — Батч-emit в bridge (`FW_GUI_STATE_BATCH`)
Делать ТОЛЬКО если после флипа 1.1+1.2 замер покажет давление на Qt main thread (темп `_deliver.emit` > ~200/с через gui_local_metric). Дизайн: один `dispatch(data_type="state_delta_batch")`, разворачивание в per-delta вызовы существующих `_state_cb`/`_state_listeners` уже в main thread (`frontend/process.py`, `frontend/state/delta_message.py`, `frontend/bridge_impl.py`) — потребители не меняются.

### Флип-протокол Фазы 1 (память `project_f7_g7_flip_ladder`)
baseline-замер → `FW_STATE_COALESCE=1` → замер → `FW_STATE_QUEUE=1` → замер → решение по 1.3 → решение о default-ON обоих флагов (отдельный коммит). Каждый замер (backend_ctl, live webcam_sketch): `introspect_queues` (глубины gui_system/gui_state), `introspect_router_stats` PM (дельты `system_evict_blocked`/`data_evicted` за 60с), `get_status("gui")`, `ui_tap_ping`, `watch_like_gui` 30с (дельты живы), `log_tail(gui)` (нет цикличных resync). **Критерий успеха фазы: gui отвечает на introspect/ui_tap, `gui_system` ≈ 0, `system_evict_blocked` заморожен.**

### Task 1.4 — ui_*-плоскость: доказательство парой (закрытие NA)
После успеха 1.1-1.2: live-пара `ui_tap` → клик через qt-mcp → `events_page(plane=ui)` несёт `ui.event`; `ui_tap_ping` OK; `ui_untap` → тишина. Закрывает вечное «ui_* NA» прошлых верификаций. Дописать результат в аудит-док.

---

## Фаза 2 — Правда supervision: замена инстанса видима

### Task 2.1 — pid/started_at/manual_restarts в supervision.status
**Files:** `process_manager_module/process/process_manager_process.py` (`_cmd_supervision_status` :485-512, `restart_process` :1875-1949), `monitor/process_monitor.py` (snapshot :1220-1231), `backend_ctl/protocol.py`/`driver.py` (проброс полей), тесты обоих модулей + `backend_ctl/tests/test_fencing_live.py` (дополнить плечом «reuse-restart: incarnation 0→0, но pid сменился и manual_restarts вырос»).
**Суть:** не трогая fence-семантику (reuse-restart осознанно не фенсится), сделать замену инстанса ВИДИМОЙ: в per-process supervision-снимок добавить `pid` (истина ОС), `started_at` и счётчик `manual_restarts` (безусловный инкремент в `restart_process`, в отличие от условного `_bump_incarnation`). `restart_count` оставить как есть (краш-рестарты) с пояснением в описании команды.
**Acceptance:**
- [ ] Пара: reuse-restart → incarnation прежняя, но `pid` новый + `manual_restarts` +1 (live); no-reuse-restart (конфиг теста) → incarnation бампается как раньше
- [ ] `supervision_status` через MCP несёт новые поля; AGENTS.md: пометка «маркер до/после рестарта = pid+manual_restarts, incarnation — только для no-reuse полосы»

---

## Фаза 3 — Ротация логов: корень, не видимость

### Task 3.1 — Диагноз-репро + фикс конкуренции ротации
**Files (диагноз определит точный набор):** `logger_module/channels/log_channel.py` (`_SafeRotatingFileHandler`), `logger_module/configs/logger_manager_config.py` (канал `messages_file` + module-канал `router_messages` — **оба пишут в один `messages.log` двумя хэндлерами одного процесса** — главный подозреваемый), тесты logger_module.
**Steps:**
1. Репро под контролем: маленький `max_size` (например 64КБ) → live-прогон → показать, что rollover систематически падает (`_rollover_failures` растёт) и КТО держит файл (два хэндлера в одном процессе vs чужой процесс).
2. Фикс по диагнозу; кандидат по умолчанию — развести `messages_file` и `module_router_messages` по разным файлам ЛИБО один общий handler на файл в рамках процесса (реестр хэндлеров по resolved-path); при межпроцессной конкуренции — ротация с retry+reopen.
3. Live-пруф: с малым max_size ротация происходит (появляются `.1`-бэкапы), `_rollover_failures` не растёт.
**Acceptance:**
- [ ] Пара: до фикса — репро провала (растущий счётчик), после — живая ротация на том же сценарии
- [ ] Полный suite logger_module зелёный; `test_rollover_visibility.py` не деградировал

---

## Фаза 4 — backend_ctl: правда и удобство (инструментный трек)

### Task 4.1 — `introspect.telemetry`: readback телеметрийного gate
**Files:** `process_module/commands/builtin_commands.py` (`_register_introspect_commands` :348, шаблон — `_cmd_introspect_queues` :637), `backend_ctl/driver.py`, `backend_ctl/mcp_tools.py` (новый read-инструмент `introspect_telemetry`), тесты.
**Суть:** тонкая обёртка над уже существующими `heartbeat.current_telemetry_publish()` (`process_heartbeat.py:362`) + `current_unknown_metrics()` (:350): эффективная publish-секция без записи. Закрывает «gate виден только по эффекту».
**Acceptance:** [ ] пара: после `telemetry_set(fps, enabled=false)` readback показывает `fps.enabled=false`; после включения — true (live).

### Task 4.2 — Честная семантика fan-out: `delivered`, не `reached`
**Files:** `process_manager_process.py` (`_cmd_telemetry_broadcast` :1561-1568), `backend_ctl/driver.py` (`_flag_unreached_metric`), доки/тесты.
**Суть:** в ответ добавить `semantics: "delivered"` (или переименовать с алиасом) + в driver-обёртке `telemetry_set` опциональный `verify=true`: после команды — readback через Task 4.1 и поле `verified_effect` (паттерн `set_register_verified`). Не блокируем, только маркируем (консервативность E.2).
**Acceptance:** [ ] пара: verify=true при живом процессе → `verified_effect=true`; при опечатке метрики → `verified_effect=false` + подсказка.

### Task 4.3 — «Кто душит очередь X»: per-sender учёт + потери в introspect
**Files:** `router_module/core/router_manager.py` (`_deliver_by_targets` :416+), `shared_resources_module/queues/core/manager.py` (`_report_never_drop_loss` :404-440 — счётчики в `get_stats`, а не только в лог), `queue_channel.py` (`get_info`), `backend_ctl/protocol.py` (missing-контракт для новых полей — BCTL-ADR-007), тесты.
**Суть:** словарь-счётчик put'ов по `message["sender"]` per-очередь (cap кардинальности ~32 отправителя), экспонировать в `introspect.router_stats`/`introspect.queues`; `never_drop_loss_total` — в `get_stats` (сейчас только `_fallback_logger`, мимо introspect). Новый счётчик обязан показать ненуль live (BCTL-ADR-007).
**Acceptance:** [ ] live: на живом рецепте у `gui_system`/`gui_state` виден топ-отправитель (ProcessManager) с ненулевым счётчиком; `never_drop_loss_total` доступен инструменту.

### Task 4.4 — `process_restart_verified`: pid-proof одним вызовом (решение владельца: tool сейчас)
**Files:** `backend_ctl/driver.py`, `backend_ctl/mcp_tools.py`, live-тест.
**Суть:** обёртка: pid-до (`introspect_memory`) → `system_command{cmd: process.restart}` (терпим timeout ответа) → поллинг pid/ready (до N сек) → `{restarted: true, pid_before, pid_after, elapsed}`. Плюс `supervision_status`-поля из Task 2.1 в ответе.
**Acceptance:** [ ] live: рестарт лёгкого процесса → `restarted=true, pid_before≠pid_after` за один вызов; несуществующий процесс → честная ошибка.

### Task 4.5 — Доки: «Известные ограничения» + stale-MCP
**Files:** `backend_ctl/README.md` (новый раздел), `backend_ctl/AGENTS.md` (`## Подводные камни` :191-208).
**Суть:** зафиксировать: (а) MCP-сервер держит код на момент старта — свежие правки драйвера проверять свежим процессом или рестартом MCP; (б) gui-шторм до Фазы 1 / после — снят (обновить по факту); (в) receiver-side `introspect_queues` ненадёжен под затором — надёжны счётчики отправителя; (г) `reached=delivered`.

---

## Фаза 5 — Закрывающий live-прогон

### Task 5.1 — Полная верификация на webcam_sketch (обновлённая методика)
Прогон всех 47+новых инструментов по методике аудита 2026-07-22: пары ON/OFF, readback-эффекты, ui_* с живым GUI (Task 1.4), `capabilities` с карточкой gui (должна ожить после Фазы 1). Новый аудит-док + обновление памяти (`project_gui_system_queue_storm` → закрыт/остатки).
**Гейт выхода плана:** [ ] gui отвечает live; [ ] ui_* доказаны; [ ] ротация живая; [ ] supervision показывает замену инстанса; [ ] 0 инструментов с UNPROVEN-эффектом (или честно помечены с причиной вне инструмента).

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
Фаза 5 — последней
```

Правила: флаги default OFF, флип по одному с замером; приёмка гоночного/флагового — только парами;
максимум 2 агента без worktree; каждый коммит `Refs: plans/truth-holes-closure.md` + `Why:`/`Layer:`;
live-прогоны строго одиночные (порт 8765 — ловушка двух бэкендов, подтверждена в этой сессии).

## Верификация плана целиком

1. Unit: полные suites state_store/router/process_module/logger_module/shared_resources + backend_ctl (без live) — зелёные на каждом шаге.
2. Live: флип-протокол Фазы 1 с числами в аудит-док; финальный прогон Task 5.1.
3. `python scripts/validate.py` чист; sentrux `session_start` до Фазы 1 → `session_end` после Фазы 4 — не хуже baseline.
```
