# STATUS — telemetry_sink

- **Состояние:** Phase 1 (Task 1.1–1.3) + Phase 3 (Task 3.1 тесты, 3.2 приёмка) — DONE.
  Headless live-proof зелёный (`telemetry_sink.yaml`: 20 строк, 5 окон ts, строки system, 0 SQL/fork-ошибок).
- **Контракт:** new-lite (плагин-сток, side-effect).
- **План:** `plans/2026-06-04_telemetry-db-sink.md` (Phase 1 + Phase 3).

## Тесты и приёмка (Phase 3)

- [x] **Task 3.1** — `tests/test_telemetry_sink_plugin.py`: 23 теста (по образцу `database/tests`).
      Покрыто: register/период семпла, schema/DDL, кэш подписки (`_on_deltas` fill/delete/update),
      агрегация `_sample_once` (state-колонки, `uptime→uptime_s`, workers/unknown→extra JSON,
      строка-сводка `system`, нечисловое→NULL, static-фильтр), команды flush/get_stats/purge_old,
      fork-safe конфиг `start()` (fork_safe=True + check_same_thread=False, подписка processes/system),
      гонка flush/worker (`_write_lock`, 20 потоков на файловой БД). ruff чисто.
- [x] **Task 3.2** — live headless-приёмка `backend_ctl/telemetry_sink_proof.py`
      (`python -m backend_ctl.probes.telemetry_sink_proof`): реальный процесс telemetry_sink + SQLManager →
      20 строк в `data/telemetry.db` (camera_0/system/ProcessManager/telemetry_sink × 5 окон),
      `total_written=20` в логе совпал с числом строк, ноль ошибок пула/fork.

## Реализовано (Task 1.1)

- [x] Пакет `Plugins/io/telemetry_sink/` (schemas/registers/config/plugin/__init__).
- [x] `TelemetrySnapshot(SchemaBase + SQLMeta)` минимум: `id`, `ts`, `process_name`, `fps`.
- [x] Подписка `processes.**` (callback → кэш), loop-worker семпл по таймеру.
- [x] SQLManager в `start()` (fork-safe, NullPool, sync insert_many).
- [x] Процесс `telemetry_sink` объявлен в `backend/topology/telemetry_sink.yaml` (launchable headless).
- [x] Edge cases: `state_proxy is None` → no-op + error; пустой кэш → не пишем.

## Реализовано (Task 1.2 — полная схема + агрегация)

- [x] Схема расширена: `latency_ms`, `uptime_s`, `status`, `extra` (JSON-хвост).
- [x] Подписка добавлена на `system.**` (для строки-сводки).
- [x] Агрегация `_sample_once`: строка на каждый процесс (`state.*` → колонки,
      `workers.*` → extra) + строка `process_name='system'` (`avg_fps`→fps, остальное → extra).
- [x] `config.*` и статика `system.*` фильтруются (не телеметрия).

## Реализовано (Task 1.3 — команды + retention)

- [x] register `retention_days` (default 0 = без ретенции).
- [x] Команды `flush` (форс-семпл), `get_stats` (total/pending/db_path/last_ts),
      `purge_old` (DELETE WHERE ts<cutoff при retention_days>0; иначе no-op).
- [x] `commands` dict в классе плагина.

## Сопутствующие framework-фиксы (вскрыты на headless-smoke 2026-06-04)

Доставка `ctx.state_proxy` в плагин была сломана — это вскрыло цепочку латентных багов
write-пути плагинов (никак не связанного со стоком, который только читает):

1. **`PluginContext.with_config()`** (`process_module/plugins/base.py`) не пробрасывал
   `state_proxy` в копию контекста → у всех плагинов `ctx.state_proxy is None`.
   Фикс: явный проброс. Чинит также `capture`/`color_mask`/`pilot_widgets`.
2. **`handle_state_merge`** (`state_store_module/manager`) — двойной unwrap из-за
   коллизии ключа `data` в payload merge → любой `merge()` плагина падал.
   Фикс: устойчивое извлечение payload.
3. **`command_manager`** логировал `reason` вместо `error` → ошибки команд скрывались
   как `failed: None`. Фикс: fallback на `error`.
4. **`register_schema`** (`data_schema_module`) терял конкретный подтип (возвращал
   `type[BaseModel]`) → pyright-warning на `register_bindings`. Фикс: `TypeVar` —
   декоратор сохраняет тип (чисто во всех плагинах, где используется `SchemaBase`).

## Ревью Phase 1 (Opus, 2026-06-04) — APPROVE с замечаниями, блокеров нет

Закрыто по итогам: гонка `_sample_once` (worker vs `flush`) → `_write_lock`;
глубокие/неизвестные `state.*` листья → теперь в `extra` (не теряются);
`purge_old` на мусорный ввод → `status:error`; README/STATUS синхронизированы.

Зафиксировано долгом (вне Phase 1):
- merge-фикс #2 — симптоматическая заплатка на `handle_state_merge`; чистое решение
  (явный маркер «развёрнутый payload» в диспетчере) — отдельный рефактор.
- blast-radius фикса #1: capture/color_mask пишут `processes.*.state` рядом с
  ProcessMonitor — Phase 3.2 формально проверить отсутствие конфликта метрик.

## Готово / отложено

- Phase 2 — миграция `DatabasePlugin` (sqlite3 → SQLManager) — **DONE 2026-06-04**, см. `Plugins/io/database/STATUS.md`.
- Phase 3 — pytest плагина (Task 3.1) + headless-приёмка (Task 3.2) — **DONE 2026-06-05** (см. раздел выше).
  GUI-проверка телеметрии вкладки «Процессы» (риск активированного `_publish_state`)
  ПРОЙДЕНА досрочно qt-mcp 2026-06-04: FPS live, «Активно: 6», 0 Qt-warnings — не сломана.
- **Известный долг (вынесен в отдельный план `plans/2026-06-05_sql-insert-many-atomic.md`):**
  `repo.insert_many` сейчас per-row commit (не атомарен). После фикса `telemetry_sink._sample_once`
  получит атомарность снимка бесплатно; формулировку «per-row, дублей нет» в docstring `_sample_loop`
  и race-теста — обновить в рамках того плана (Task 2.x).
