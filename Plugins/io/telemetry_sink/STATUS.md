# STATUS — telemetry_sink

- **Состояние:** Task 1.1 (vertical slice) — DONE. Headless-smoke зелёный
  (`telemetry_sink.yaml`: rows>0, несколько `ts`), framework-блокер устранён.
- **Контракт:** new-lite (плагин-сток, side-effect).
- **План:** `plans/2026-06-04_telemetry-db-sink.md` (Phase 1, Task 1.1).

## Реализовано (Task 1.1)

- [x] Пакет `Plugins/io/telemetry_sink/` (schemas/registers/config/plugin/__init__).
- [x] `TelemetrySnapshot(SchemaBase + SQLMeta)` минимум: `id`, `ts`, `process_name`, `fps`.
- [x] Подписка `processes.**` (callback → кэш), loop-worker семпл по таймеру.
- [x] SQLManager в `start()` (fork-safe, NullPool, sync insert_many).
- [x] Процесс `telemetry_sink` объявлен в `backend/topology/telemetry_sink.yaml` (launchable headless).
- [x] Edge cases: `state_proxy is None` → no-op + error; пустой кэш → не пишем.

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

## Отложено

- Task 1.2 — полный набор метрик (`latency_ms`/`uptime_s`/`status`/`extra`) + system-сводка.
- Task 1.3 — конфиг-параметры (batch/retention) + команды (`flush`/`get_stats`/`purge_old`).
- Phase 3 — pytest и формальная headless-приёмка записи в БД.
  GUI-проверка телеметрии вкладки «Процессы» (риск активированного `_publish_state`)
  ПРОЙДЕНА досрочно qt-mcp 2026-06-04: FPS live, «Активно: 6», 0 Qt-warnings — не сломана.

## Отложено

- Task 1.2 — полный набор метрик (`latency_ms`/`uptime_s`/`status`/`extra`) + system-сводка.
- Task 1.3 — конфиг-параметры (batch/retention) + команды (`flush`/`get_stats`/`purge_old`).
- Phase 3 — pytest и формальная headless-приёмка.
