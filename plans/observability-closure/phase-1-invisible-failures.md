# Невидимые отказы становятся видимыми

> Фаза Ф1 плана [`observability-closure`](./plan.md). Правила приёмки — `plan.md` §3 (наследуют `observation-port/plan.md` §3), развилки владельца — `plan.md` §4, что удаляется и миграции — `plan.md` §9–§10. Номера находок (C*, M*, m*) — по [ревью 2026-08-28](../../docs/reviews/2026-08-28_observability-full-review.md).

## Ф1 — Невидимые отказы становятся видимыми

### Task 1.1 — `install_process_hooks`: исключения потоков и `warnings` в плоскость ошибок (C3)
**Level:** Senior (Opus) · **Assignee:** teamlead · **Layer:** framework
**Goal:** любое необработанное исключение в любом потоке процесса и любой `warnings.warn` оставляют след в плоскости ошибок/логов с адресом потока и трассой; хук — один на процесс, ставится фреймворком.
**Files:** новый `multiprocess_framework/modules/logger_module/core/process_hooks.py`, `process_module/core/process_module.py`
(точка после подъёма `LoggerManager`), `process_module/lifecycle/*` (снятие при останове), `error_module/core/error_manager.py`
(маршрут `thread_exception`), `channel_routing_module/core/channel_routing_manager.py:46` (`LOSS_COUNTER_KEYS` — новые счётчики).
**Steps:**
1. `install_process_hooks(services)`: `threading.excepthook`, `sys.excepthook`, `logging.captureWarnings(True)`; каждый хук — тонкий: собирает `(thread_name, exc, tb)` и зовёт `services.report_error(..., context=...)`; при мёртвом менеджере — `_fallback.emergency_log` + счётчик.
2. Счётчики `thread_exceptions`, `warnings_captured`, `hook_delivery_failures` — в readback `introspect.observability.counters.error` и в `system_overview.anomalies`.
3. Снятие хуков при останове процесса (восстановить прежние), чтобы тесты не текли (фикстура).
4. Тесты автора: реентрантность (исключение внутри хука), хук при остановленном менеджере, порядок «до/после LoggerManager».
**Acceptance criteria:**
- [ ] Юнит: исключение в `threading.Thread` → одна запись `kind=error` с `thread=<имя>` и трассой в сторе, `thread_exceptions == 1`, health-счётчик ошибок вырос; `warnings.warn` → одна запись `kind=log severity=warning` с категорией.
- [ ] Живьём: `health.report`-аналог — команда диагностики `diag.thread_raise` (или зонд) → запись в `errors.log` + стор + `system_overview.anomalies`.
- [ ] Пара инъекций: хук снят → 0 записей при 728 байтах в stderr (красный); хук стоит, менеджер мёртв → `hook_delivery_failures == 1`, не тишина.
- [ ] `CONNECTORS.md`: раздел «что ловится автоматически» с этими тремя механизмами.
**Out of scope:** fd-перехват нативного stderr (9.2), `faulthandler` в останове (§13 плана порта).

### Task 1.2 — Лаунчер и ранние записи не теряются (M14, m3)
**Level:** Middle+ (Sonnet) · **Assignee:** developer · **Layer:** framework
**Goal:** INFO лаунчера виден в файле; у `ProcessManager` `unresolved_channel_records == 0` на старте; отказ уборки SHM — не `except: pass`.
**Files:** `process_manager_module/launcher/system_launcher.py:160-190`, `process_manager_module/launcher/spawner.py:73`,
`shared_resources_module/buffers/cleanup.py:160`, `logger_module/adapters/std_facade.py:150-170`, подъём логгера ПМ
(`process_manager_module/process/process_manager_process.py` — точка регистрации каналов).
**Steps:**
1. Лаунчер поднимает минимальный `LoggerManager` (console + `launcher/system.log` в `INSPECTOR_LOG_DIR`) тем же конфигом слоёв, что процессы, — не отдельный механизм.
2. `except: pass` вокруг уборки SHM → `log_error` с исключением + счётчик `shm_cleanup_failures`; успех — INFO с числом сегментов.
3. У ПМ каналы регистрируются до первой записи (или ранние записи идут в ранний буфер и сливаются) — цель `unresolved_channel_records == 0`.
**Acceptance criteria:**
- [ ] Живьём: `launcher/system.log` содержит `cleanup_stale_shm: очищено N`; `introspect.observability(ProcessManager).counters.logger.unresolved_channel_records == 0`; `system_overview.anomalies` без `observability_loss` у ПМ на чистом старте.
- [ ] Инъекция: сломать уборку (несуществующий путь) → ERROR с трассой в `errors.log`, счётчик 1.
**Out of scope:** формат каталога логов (m1 — Ф3.2).

### Task 1.3 — Плоскость ошибок: решение Р-1 и проводка (M8)
**Level:** Senior (Opus) · **Assignee:** teamlead · **Layer:** framework, plugins
**Goal:** по решению Р-1(а): `errors.log`, health и breaker видят отказы подсистем; один инцидент — одна строка в сторе.
**Files:** `process_module/generic/plugin_orchestrator.py:157,180,202`, `worker_module/` (5 точек `_log_error`),
`router_module/channels/socket_channel.py:132,341`, `router_module/core/router_manager.py:398-399`,
`Plugins/sources/capture/plugin.py:288`, `base_manager/mixins/observable_mixin.py` (`report_error` с параметром `also_log=False`),
`multiprocess_framework/docs/observability/CONNECTORS.md`, новый страж `multiprocess_framework/modules/tests/test_one_connector_per_point.py`.
**Steps:**
1. Инвентарь: список из 226 `_log_error` классифицировать скриптом на «отказ подсистемы» / «ошибка обработки данных» (первые → `report_error`, вторые остаются логом). Список в задаче, не в голове.
2. Правило «один разъём на точку»: AST-страж — соседние вызовы `_log_error` и `_track_error`/`report_error` в одной функции запрещены (whitelist с причиной).
3. `report_error` пишет ОДНУ запись (error-плоскость) с полным Resource-контекстом; логгер-tap стора не дублирует записи, у которых `origin=error_manager` (маркер в `extra`).
4. Живой отказ для приёмки: камера не открывается headless (`capture/plugin.py:288`) — сейчас `log_error` мимо плоскости ошибок.
**Acceptance criteria:**
- [ ] Живьём на стенде без камеры: `errors.log` содержит отказ открытия камеры; в сторе по нему одна строка `kind=error`; `health.status` показывает ошибку; `system_overview.anomalies` — тоже.
- [ ] `health.report` даёт одну строку в сторе (было три).
- [ ] Инъекция: вернуть пару `_log_error + _track_error` в `router_manager.py:398` → страж красный по адресу; снять маркер `origin` → тест дубля красный.
- [ ] `CONNECTORS.md`: таблица «какая дорога для какого класса события» + ссылка на страж.
**Out of scope:** fingerprint/группировка (9.1).

### Task 1.4 — Голоса-повторы окном на ключ; `trace_id` вне текста (M17, m2)
**Level:** Middle+ (Sonnet) · **Assignee:** developer · **Layer:** framework, plugins
**Goal:** повторяющееся состояние — один голос на окно + счётчик; WARNING-константы старта не повторяются; ключ дросселя не зависит от `trace_id`.
**Files:** `router_module/core/router_manager.py:388-399` (образец `_SEND_ERROR_LOG_INTERVAL_SEC` → обобщить),
`channel_routing_module/core/channel_routing_manager.py` или `base_manager/mixins/observable_mixin.py` (новый `log_windowed(key, interval, level, msg, **ctx)`),
`shared_resources_module/queues/core/manager.py` (пара `Full()`/`drop_oldest`), `process_manager_module/process/process_manager_process.py`
(priority/liveness WARNING'и), `Plugins/control/robot_control/plugin.py:285`, `logger_module/core/sampling.py` (ключ по источнику+call-site — опционально, по бенчу).
**Steps:**
1. `log_windowed`: первый голос сразу, дальше — не чаще `interval` на ключ, в тексте — число подавленных; счётчик `windowed_suppressed` в readback. Окно — из политики (`observability.voices.default_window_sec`), не литерал.
2. Перевести на него: `Full()`/`drop_oldest` (один голос на окно + счётчик `queue_full_events`), `Failed to set priority` (один раз за процесс, INFO), `ready via liveness-fallback` (INFO, WARNING только если > `N` раз подряд).
3. `robot_control`: `trace_id` в `extra.context.trace_id`, текст постоянный; линт-страж: сообщение не содержит 32-hex.
4. Опционально (по бенчу, решение в задаче): ключ сэмплера `(уровень, источник, call-site)` до сборки записи — цена подавленной записи ≤ 1 мкс.
**Acceptance criteria:**
- [ ] Живьём: бут → 0 WARNING-констант (список из ревью m2 — по каждому контрольная строка INFO один раз); сценарий переполнения очереди (`gui` под нагрузкой) → ≤ 1 голос на окно при растущем `queue_full_events`.
- [ ] Пара инъекций: окно снято → шторм красный по числу; счётчик снят → «событие есть, счётчик 0» красный.
- [ ] `sampling_first_n` включён на стенде → `records_sampled_out > 0` при включённом дросселе (С-8 закрывается числом).
**Out of scope:** переписывание всех 226 точек — только перечисленные.

### Task 1.5 — Живой стенд Ф1 + ревью фазы
- [ ] Стенд без камеры и с камерой; `errors.log` непустой на первом, пустой на втором — пара; агентская сессия: `system_overview` называет отказ камеры в `anomalies`.
