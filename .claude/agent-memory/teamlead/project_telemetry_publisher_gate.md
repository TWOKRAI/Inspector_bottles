---
name: telemetry-publisher-gate
description: publisher-gate телеметрии активен ТОЛЬКО при секции telemetry.publish (1.3 не инжектить пустую); PC 3.1 gate рантайм-мутабельный; PC 3.2/3.3 driver telemetry_* + fan-out; Task 1.1 mode:merge|replace дельта; Task 1.2 DONE — publish.tick_sec (частота публикации в контракте, вариант а ADR-PM-016), + валидация mode∈{replace,merge}
metadata:
  type: project
---

Publisher-gate телеметрии (PC 1.2, `process_module/heartbeat/`) активен ТОЛЬКО когда
в конфиге процесса есть секция `telemetry.publish`. `ProcessHeartbeat._build_telemetry_gate()`:
нет `telemetry` / нет под-ключа `publish` → `TelemetryGate=None` → `allowed_metrics=None`
пробрасывается везде → все метрики публикуются каждый тик (байт-в-байт прежнее поведение).
Present-but-empty (`telemetry.publish: {}`) → гейт активируется с `default_interval_sec=1.0`
(все метрики throttled до 1.0с).

**Why:** обратная совместимость завязана на ОТСУТСТВИЕ секции, а не на дефолтных
значениях внутри неё. `TelemetryPublishConfig()` дефолт = 1.0с throttle, что при
heartbeat быстрее 1с изменило бы наблюдаемую частоту у процессов, которые ничего не
настраивали.

**How to apply:** Task 1.3 (плумбинг `SystemConfig.telemetry` → `get_config("telemetry")`
через assembler, как observability overlay) НЕ должен подставлять пустой `publish: {}`
по умолчанию — иначе троттлинг молча включится на КАЖДОМ процессе. Секция должна
доезжать до `get_config` только если задана в system.yaml/blueprint. Гейт-контракт:
`fps`/`latency_ms`/`effective_hz`/`cycle_duration_ms`/`shm` гейтятся; `status`/health/
errors — всегда. Связано с [[project_telemetry_self_publish]],
[[project_observability_control_plane]].

**PC 3.1 (DONE, f05aa26c) — gate стал рантайм-мутабельным.**
`ProcessHeartbeat.reconfigure_telemetry(publish_section)` пересобирает gate БЕЗ рестарта
(`None`→gate off). Потокобезопасность: gate читается в потоке heartbeat, смена — атомарный
swap ссылки под GIL на полностью собранный объект; `_loop` читает `self._telemetry_gate` в
ЛОКАЛЬНУЮ переменную ОДИН раз за тик (иначе `is not None`→`.due_metrics()` словил бы None при
конкурентной смене). Новый gate стартует со свежим `_next_due` (перенос старого отвергнут —
чтение `_next_due` из потока команд гонится с heartbeat). Единая идемпотентная точка —
`managers/telemetry_reload.py::apply_telemetry_reconfigure(section,*,heartbeat,store_throttle)`
(по образцу `apply_observability_reconfigure`): применяет по НАЛИЧИЮ ключа (`publish`→heartbeat,
`throttle`→`ThrottleMiddleware.set_rules`). Достаётся из контекста процесса: heartbeat=
`getattr(svc,"_heartbeat")`, троттл=`svc._state_store_manager.get_middleware("throttle")`
(StateStoreManager держит ТОЛЬКО оркестратор). Пути: IPC `telemetry.reconfigure`, расширенный
`config.reload` (`data["telemetry"]` inline+файл, прежний `applied.log_level` сохранён,
telemetry→`telemetry_applied`), файловый watcher (seam `on_reload_extra`).
**PC 3.2/3.3 (DONE, f75d77b1) — driver + fan-out на ВСЕХ детей.**
Driver (`backend_ctl/driver.py`): `telemetry_reconfigure(process="all"/имя, *, publish=_UNSET,
throttle=_UNSET)` + узкая `telemetry_set(process, metric, *, enabled, interval_sec, plane=publisher|throttle)`.
Сентинел `_UNSET` (модульный) обязателен: `publish=None` — ВАЛИДНАЯ команда «выключить gate»,
`None`≠«не передано». `process` in {"all","*",None} → шлёт `telemetry.broadcast` на PM; иначе адресный
`telemetry.reconfigure`. Fan-out (`ProcessManagerProcess._cmd_telemetry_broadcast`, зарег. в
`_register_builtin_commands`): **две плоскости разведены** — `publish` рассылается ВСЕМ детям через
`comm.broadcast(exclude_self=True)` (сам PM НЕ переконфигурируется broadcast'ом), `throttle` применяется
к ЦЕНТРАЛЬНОМУ `ThrottleMiddleware` САМОГО оркестратора (детям НЕ шлётся — у них нет StateStoreManager).
Общий примитив `_broadcast_command(command, data)` вынесен из `_broadcast_routing_refresh` (тот же путь
`ProcessCommunication.broadcast` — свежие очереди PM → **долетает после hot-swap**, ключевое свойство);
примитив НЕ глотает исключения (routing сохраняет свой error-путь try/except). Общий
`resolve_store_throttle(holder)` в `telemetry_reload.py` дедупит с `BuiltinCommands._resolve_store_throttle`.
**Broadcast fire-and-forget:** результат несёт ОХВАТ ДОСТАВКИ (`publish.reached`/`target_count`/`complete`,
`targets` из `get_process_names`), а НЕ per-child подтверждение применения (для него — адресный вызов).
**Follow-up:** файловый watcher оркестратора всё ещё фанит детям только `throttle`;
проброс publisher-gate детям через watcher — не сделан (добавляет побочный broadcast на каждый reload файла,
отдельное решение; примитивы готовы). Тесты: `test_telemetry_driver.py`, `test_telemetry_broadcast.py`.

**Task 1.1 (DONE, 92d6f6f6) — дельта-семантика `mode: merge|replace`, закрыт full-apply на ОБЕИХ плоскостях.**
`apply_telemetry_reconfigure(section, *, mode="replace"|"merge", ...)`: `replace`=прежнее полное применение
(дефолт, бит-в-бит характеризован); `merge`=дельта поверх ЖИВОГО. **Publisher merge:** источник эффективной
секции — `ProcessHeartbeat.current_telemetry_publish()` (=`gate.config.to_dict()`, добавлен property
`TelemetryGate.config`); `reconfigure_telemetry(delta, *, mode="merge")` строит gate из
`deep_merge(current, delta)` (канон `data_schema_module.deep_merge`); `publish=None` выключает gate НЕЗАВИСИМО
от mode. **Throttle merge:** per-правило `update_rule`/`remove_rule` вместо `set_rules` (оживил мёртвый API
PC 0.1 — продакшн-потребитель `telemetry_reload._apply_throttle`); маркер удаления = `None` (JSON null; `0`
остаётся валидной «полной блокировкой», НЕ маркер). **Контракт mode (решение teamlead):**
`data["telemetry_mode"]` — ключ-СОСЕД `publish`/`throttle`, НЕ внутри секции (секция уходит в config-билдеры →
должна быть чистым config-dict). На проводе ТОЛЬКО при `merge` (`replace`=прежний конверт бит-в-бит,
backward-compat старых сообщений); прокинут в `telemetry.reconfigure`/`telemetry.broadcast` (детям+central-throttle)/
`config.reload`. **Driver:** `telemetry_set`→`mode="merge"` (обещал точечность); `telemetry_reconfigure`→
`replace`-дефолт+`mode`-параметр. 79 telemetry-тестов зелёные. **NB:** 12-13 `backend_ctl/tests/*_live.py`
падают и на чистом дереве (spawn реального бэкенда на Windows, «ProcessManager did not stop in 5.0s») —
pre-existing/env, НЕ от этой задачи (проверено stash+прогон).

**Task 1.2 (DONE, 03449743) — телеметрийный тик в контракте (`publish.tick_sec`), ADR-PM-016 вариант (а).**
Частота публикации управлялась захардкоженным `heartbeat_interval=5.0` (читался ОДИН раз в `start()`,
`reconfigure` его не трогал) → publisher `interval_sec<5с` тихий no-op (finding D). Фикс: `TelemetryPublishConfig.tick_sec:
float|None=None` (None→heartbeat_interval, backward-compat бит-в-бит). **Вариант (а):** ОДИН heartbeat-воркер
тикает `min(heartbeat_interval, tick_sec)`; телеметрия каждый тик (per-метрика rate-limit держит `TelemetryGate`),
а heartbeat-СООБЩЕНИЕ к ProcessManager + health/observability/GC — по расписанию liveness (`_heartbeat_due`:
now-last>=interval-tick/2; при tick_sec=None → tick>=interval → каждый тик = heartbeat-такт, бит-в-бит).
**КРИТ.ИНВАРИАНТ:** частота heartbeat-сообщений (liveness→ProcessMonitor) НЕ меняется тиком (иначе ложные «process
dead»); провозится time-gate + acceptance-тестом. `_telemetry_tick()`/`_heartbeat_due()` читаются каждую итерацию
`_loop` → runtime-смена tick_sec живьём (со след. тика). Clock ИНЪЕКТИРУЕТСЯ в `ProcessHeartbeat(services,*,clock=)`
и прокидывается в `TelemetryGate(config, clock=self._clock)` → детерминированные fake-clock тесты каденции
(`test_telemetry_tick.py`). Валидация `capped_metrics(config, effective_tick)` (в telemetry.py — там GATED_METRICS
уже импортируется, цикл-риск Task 2.3 НЕ тронут): `interval_sec<эффективного тика` → WARNING (был тихий no-op).
Отвергнут (б) отдельный воркер telemetry_publisher — второй lifecycle+дубль get_all_workers_status+дележ health/obs/GC.
**Доп (замечание ревьюера 1.1, тот же участок):** валидация `mode∈VALID_MODES={replace,merge}` в единой точке
`apply_telemetry_reconfigure` — опечатка (`mrege`) → `{"error":...,"mode":...}` НИЧЕГО не применяет (не молчаливый
деструктивный replace); тест `test_unknown_mode_rejected`. process_module/774 + PM/444 зелёные.

**Task 1.3 (DONE) — троттл=IPC-предохранитель, publisher-gate=единственный авторитет частоты (ADR-PM-017). ФАЗА 1 ЗАКРЫТА.**
Residual #6 (две плоскости с равными дефолтами каскадируют) + вторая половина finding D. ДВА механизма:
(1) `manager_setup._default_throttle_rules()` — все правила на единый мягкий `_SAFETY_INTERVAL_SEC=0.05с`
(`_MIN_PUBLISHER_INTERVAL_SEC 0.1 × _THROTTLE_SAFETY_MULTIPLIER 0.5`), заведомо НИЖЕ пола публикации → дефолт-троттл
НЕ режет поднятие частоты (прежние жёсткие 1.0/2.0/5.0с убраны). (2) `telemetry_reload.detect_throttle_caps(publish, throttle)`
в `_cmd_telemetry_broadcast` — при операторском СТРОГОМ central-правиле и publisher-подъёме НИЖЕ него → флаг
`capped_by_throttle:{metric:{publisher_interval_sec,throttle_interval_sec}}` (НЕ авто-меняет троттл). Сопоставление
метрика→central-правило по СУФФИКСУ паттерна (`processes.**.state.fps`→`fps`, `.rsplit('.',1)[-1]`; строжайшее=макс.интервал,
0=полная блокировка). **Выбор step2: capped_by_throttle, НЕ auto-relax** — auto-relax МОЛЧА снёс бы операторскую страховку
(runaway-публикатор авто-снял бы защиту); дефолт-мягкость (мех.1) уже даёт «частота реально растёт» в дефолт-сценарии без
жертвы страховкой. **Finding-1 ревью 1.2 (закрыто тут):** битый mode всплывает до `success=False` в ТРЁХ хендлерах —
`_cmd_telemetry_broadcast` (pre-валидация mode ДО fan-out, т.к. broadcast fire-and-forget), `_cmd_telemetry_reconfigure`/
`_cmd_config_reload` (`if "error" in applied: return success=False`). Сквозной store-gate тест доказывает рост частоты
(`test_integration.py`); 1801 process/PM/state_store зелёные. ADR-PM-017 в process_module/DECISIONS.md (не global — серия PM),
sync → global index `ADR-PM-001…017`.
**ФАЗА 1 (блокер Фазы 4 GUI plan telemetry-publish-control) ЗАКРЫТА** — Tasks 1.1/1.2/1.3 done. Следующее: Фаза 2
(Task 2.1 boot≡reload throttle:{}, 2.2 config.reload per-process overlay, 2.3 validate metrics-ключи); Task 3.2 персист дельты.
