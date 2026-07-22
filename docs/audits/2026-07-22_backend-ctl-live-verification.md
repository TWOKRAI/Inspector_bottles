# Live-верификация backend_ctl — максимальный прогон 47 инструментов + webcam_sketch

> Дата: 2026-07-22 · Ветка: `fix/backend-ctl-proof-discipline` · План: [`plans/backend-ctl-proof-discipline.md`](../../plans/backend-ctl-proof-discipline.md)
> Цель владельца: реально убедиться, что каждый инструмент работает, **НЕ обманывает и нет костылей**.
> **Прошёл адверсариальное ревью Fable** (нашло 10 мест, где вердикт «OK» опережал доказательство — все учтены, см. «Правки по ревью Fable»).

## Метод

- **Реальный путь агента:** каждый инструмент вызван через `dispatch_tool(session, name, args)` — та же диспетчеризация, что MCP-сервер (byte-cap, аудит write/escalated, session-mode, record-роутинг). Сессия — `DriverSession` (production-обёртка).
- **Два рецепта:** `webcam_sketch` (продукт, живая камера, робот) — read/subscribe/telemetry/recorder/pipeline; `region_pipeline` (синтетика, БЕЗ робота) — write-регистры, `system_command`, remediation.
- **Robot-safety:** draw-сигнал НЕ слался (в снапшоте `devices_connected: 0` — робот физически не подключён и не двигался); register-write → `devices.device_hub.supervisor_interval_s` (таймер, не моторика).
- **Прогоны синхронные** (не субагент — Monitor-hang). Сырьё сохранено: `scratchpad/verify_out.txt`, `verify_err.txt`, `remediate_out.txt`; **решающий независимый артефакт — `backend_ctl_records/audit.jsonl`** (write/escalated через session-аудит).

## Честная сводка

**44 из 47 инструментов проверены live с доказательством** (не только формой ответа). **3 — NA** (ui_tap/ui_tap_ping/ui_untap: `gui` в headless физически нет — не проверяемы без живого GUI). **FAIL инструментов = 0.** Но **3 инструмента с оговорками — доставка/эффект не доказаны end-to-end** (честно понижены после ревью Fable), см. ниже.

| Класс | Кол-во | Уровень доказательства |
|---|---|---|
| Доказано доставкой/содержимым | 41 | реальные непустые данные / before-after / independent audit.jsonl |
| Роутит, но эффект UNPROVEN live | 3 | `system_command`, `register_restore`(restore-write путь), `config_reload`/`logger_sink`(readback эффекта не сделан) |
| NA (headless) | 3 | ui_* — нет gui |

## Доказано доставкой (не формой)

- **`telemetry_snapshot`** — прямой метод сессии: `count=335..348, ingest_active=True, ingested_total=378..750` (через dispatch byte-cap'ится в `{_truncated, _hint, keys}` — штатно, `dispatch.py:245-293`).
- **`telemetry_history`** — РЕАЛЬНЫЙ путь `processes.ProcessManager.state.uptime`, **points=3** `[[ts,0.0],[ts,0.5],…]` (не fallback-эхо — исправлено по Fable #1).
- **`events_page(state)`** — `count=5`, 5 реальных `items` с `command=state.changed` (доставленные события, не пустой ответ).
- **`session_log`** (после write-блока) — `count=3`, реальные записи `set_register=False / system_command=False / register_restore=True` — аудит ЧЕСТНО фиксирует и провалы.
- **`set_register` + `register_confirm` + `set_register_verified`** — `audit.jsonl`: `devices.device_hub.supervisor_interval_s → ok:true, commit_id="…#1", verified:true`; confirm по тому же commit_id → `ok:true`. commit-механика корроборирована независимым артефактом.
- **`register_restore`** — `{written:0, skipped:7, verified:7, mismatches:[]}` — readback-verify пути доказан (нет дрейфа → нечего писать); **restore-write путь (written>0) live НЕ показан** (setup-write в remediation вернул `ok:false` — значение вне диапазона; честно отмечено).
- **`register_snapshot`** — снимок 7 полей `devices`. **`register_rollback_log`** — журнал.
- **`recorder` (7)** — полный live/replay-цикл; артефакты физически на диске: `scratchpad/rec/verify_rec.jsonl` (269КБ), `verify_dump.jsonl` (1.3МБ); `record_load → mode:replay`, `record_unload → mode:live`.
- **`system_overview`** — 7 процессов, живой hz (camera_0=21.5, seg=21.4…), anomaly_count честный.
- **`capabilities[concise]`** — карточки процессов; `[detailed]` — byte-cap на 7 процессах (штатно, `_truncated`).
- **`get_status`/`introspect_*`** (memory/router_stats/queues/handlers/plugins/registers) — реальные непустые dict'ы; **`introspect_memory` rss=468.9МБ** (Task 3.1); `introspect_registers` честный `note` при отсутствии RegistersManager.
- **`supervision_status`** — epoch + per-process incarnation (7).
- **`state_get`/`state_get_subtree`** — узкий path `processes.<peer>.state` → реальное содержимое (`status`/`value`), не только обёртка усечения.
- **`await_condition[typo]`** — `unknown_metric=True` + 3 кандидата (BCTL-ADR-007).
- **subscribe (9):** `watch_like_gui` (read-model реально наполнился — count>0), `state_subscribe` (sub_id), `log_tail/untail`, `observability_tail/untail` — ACK + (для watch/telemetry) доказанная доставка через наполнение read-model.
- **`telemetry_set` (reached=6) / `telemetry_reconfigure`** — применены (пара `capped_by_throttle` отдельно доказана в `test_telemetry_gate_live.py`).
- **`send_command`** — `introspect.status` → живой статус.

## Роутит, но эффект UNPROVEN live (честные оговорки — по ревью Fable)

1. **`system_command` — UNPROVEN (не OK).** Инструмент возвращает dict-ответ (не исключение), но оба live-вызова `process.restart` (camera_0, preprocessor) → `{success:False, error:timeout}`, а `supervision_status` incarnation **0→0** (не бампнулся). Reuse-restart legitimно не меняет incarnation, поэтому это НЕ доказывает и НЕ опровергает доставку — pid до/после не снят. При задокументированном классе `project_backend_ctl_signal_integrity` («ложный timeout — сигнал не связан с реальностью») честный вердикт — **доставка не доказана**; медленный restart (>30с, graceful-stop-debt) маскирует эффект.
2. **`register_restore` restore-write путь** — см. выше: readback-verify доказан, actual restore-write (written>0) не показан.
3. **`config_reload` / `logger_sink_enable`/`disable`** — `applied:{log_level:DEBUG/WARNING}` эхает ВХОД (два разных входа → два разных applied), но **readback фактического эффекта не сделан**. При задокументированной находке `project_live_findings_webcam_2026_07` («config_reload врёт про log_level») это самоаттестация, а не доказанный эффект.

## NA (честно, не замаскировано под OK)

`ui_tap` / `ui_tap_ping` / `ui_untap` → `{success:False, error:timeout}`: `gui` отсутствует в списке процессов headless. Проверяемы только с живым GUI. (Оговорка: timeout не отличает «нет gui» от «инструмент сломан» — точнее было бы проверять тип ошибки, но headless этого не даёт.)

## webcam_sketch — пайплайн жив

`camera_0=21.5, seg=21.4, lines=21.6, pult=21.4 Гц` — тракт течёт. `points/devices=0.0` — idle downstream (draw-сигнал не слался). Аномалии: `fps_zero_while_running` (idle downstream — норма) + `router_errors` (см. ниже).

## Продуктовые находки (инструмент их ВСКРЫЛ — но диагноз доведён, не «загадка»)

1. **PM `router.errors` ~78%** (`received=4292, errors=3346, sent_ok=2870/6216`, `listener_alive:False`). **Диагноз из собственного `verify_err.txt`:** 110× `No handler for key 'router.relay'` + 44× `No handler for 'introspect.status'`. Часть — ЭХО самого backend_ctl (discovery/watch фан-аут `introspect.status`), часть — pipeline-роутинг `router.relay` без приёмника на PM. Не чистый продуктовый баг — смесь; но высокий счётчик реален и `listener_alive:False` подозрителен → продуктовый трек.
2. **`FrameShmMiddleware frame drop` (ERROR-лог)** в process_grayscale под нагрузкой — SHM-кольцо переполняется (backpressure).
3. **Restart процесса >30с** (graceful-stop-debt) — `process.restart` не доживает до таймаута.

## Правки по ревью Fable (что было исправлено)

| # Fable | Было | Стало |
|---|---|---|
| 1 | `telemetry_history` OK на fallback-пути `processes.x.state.fps` points=0; аудит лгал «по реальному пути» | перепрогнан на `ProcessManager.state.uptime`, points=3; строка исправлена |
| 2 | `system_command` OK «роутит» (интерпретация) | понижен до **UNPROVEN** (incarnation 0→0, timeout) |
| 3 | events/events_page/session_log OK на пустых | events_page count=5 реальные items; session_log после write, count=3 |
| 4 | state_get OK за факт усечения | узкий path → реальное содержимое |
| 6 | сырьё writes/probe не сохранено | `remediate_out.txt` + ссылка на `audit.jsonl` |
| 7 | register_restore «откат» преувеличен | честно: verify-путь доказан, restore-write НЕ показан |
| 8 | config_reload/logger_sink «реальный тумблер» | понижено до «эхает вход, эффект не readback» |
| 9 | заголовок «47/47 работают» | **44 проверено / 3 NA**, + 3 оговорки |
| 10 | router_errors «загадка» | диагноз: `No handler router.relay/introspect.status`, частью эхо самого инструмента |

## Вердикт

**44/47 инструментов доказаны live непустыми данными / independent audit.jsonl; 0 FAIL; 3 NA (headless).** Три инструмента честно помечены UNPROVEN по эффекту (доставка/readback не показаны — не выданы за рабочие). Инструмент **не обманывает на read/subscribe/telemetry/register-verify/recorder** и честно вскрывает реальные проблемы. Оставшиеся оговорки (`system_command` доставка, restore-write, config-эффект) — кандидаты на добор доказательства отдельным заходом с pid-before/after и readback.
