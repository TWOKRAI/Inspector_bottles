# logger_module — Статус рефакторинга

## Текущий этап: 5 / 8

## Оценки (0–10)

| Критерий | Оценка | Комментарий |
|---|---|---|
| Код | 9 | CRM; BatchBuffer; удалены LogDispatcher, legacy batcher/, свойства channels/batcher |
| Тесты | 7 | ~30 тестов; стресс BatchBuffer и расширенное scope routing — по желанию |
| Документация | 9 | README, DECISIONS.md (ADR-LOG-001…003), §6.5 в ARCHITECTURE.md |
| Связанность | 9 | Наследует ChannelRoutingManager; зависит от channel_routing_module |
| Дублирование | 10 | Нет: registry, BatchBuffer, Dispatcher — из CRM |
| Работоспособность | 8 | BatchBuffer + scope routing; ErrorManager без LogDispatcher |

## Обновление 2026-04-01

- Резолв относительных путей логов: **`core/log_paths.py`**, поле **`LoggerManagerConfig.log_directory`**; файлы по умолчанию не создаются в каталоге пакета при запуске из `modules/` (см. **ADR-111**).

## Обновление 2026-04-02

- **`LoggerManagerConfig`:** без `from_dict` / `from_yaml` / `get_scope_config`; загрузка через **`model_validate`**, fallback scope — **`LoggerManager._scope_schema`** (см. **ADR-112**).

## Обновление 2026-04-03

- **`logger_manager_config.py`:** дефолтный порог **INFO** для **`LoggerScopeSchema`** и скоупов **BUSINESS** / **PERFORMANCE** задаётся как **`_LEVEL_ORDER[1]`** (один источник с порядком уровней в **`should_log`**); отдельное поле **`log_level`** у конфига не используется — глобальный уровень задаёт **`default_level`**, **BUSINESS** при необходимости подставляется в **`ManagersConfig.from_log_dir`**.

## Обновление 2026-04-09 (Фаза 3 cleanup)

- Удалены **`LogDispatcher`** и пакет **`batcher/`**; **`LogRecord`** в **`core/log_types.py`** (см. **ADR-LOG-001…003**).
- Убраны backward compat: **`channels`**, **`batcher`**, **`self.dispatcher`**.

## Что сделано в CRM-миграции (Фаза 2–3)

- [x] `ILogChannel(IChannel)` — унифицированная иерархия каналов
- [x] `LogChannel(ILogChannel)` — `name`, `channel_type` как `@property`; `FileChannel`, `ConsoleChannel`, `HttpChannel` наследуют
- [x] `LoggerManager(ChannelRoutingManager, ILoggerManager)` — убраны дублирующие реализации registry/buffer
- [x] `self._channel_registry` из CRM вместо `channels: Dict` (был без lock)
- [x] `BatchBuffer` из CRM вместо `BatchManager` (legacy batcher удалён)
- [x] `_resolve_log_config()` — None | dict | LoggerManagerConfig | `build()` → **LoggerManagerConfig** (SchemaBase)
- [x] Конфиги: `configs/logger_manager_config.py` — **LoggerManagerConfig** extends **ChannelRoutingConfig**
- [x] `initialize()` / `shutdown()` — только CRM-компоненты (`_dispatcher`, `_buffer`, registry)

## Чеклист рефакторинга

- [x] Этап 0: Критические баги исправлены (config_dict, _route_via_router)
- [x] Этап 1: Модуль запускается — LoggerManager.initialize() работает
- [x] Этап 2: interfaces.py, README, encoding headers, интеграция с message_module
- [x] Этап 3: level-based routing в ErrorManager; cleanup LogDispatcher / batcher
- [x] Этап 4: LoggerManager наследует ChannelRoutingManager; ILogChannel(IChannel)
- [x] Этап 5: Документация и удаление legacy dispatcher/batcher (текущий шаг плана #5)
- [ ] Этап 6: Graceful shutdown — flush() перед остановкой + router unsubscribe
- [ ] Этап 7: Unit-тесты — покрытие > 85%, стресс-тест BatchBuffer под нагрузкой
- [ ] Этап 8: Полная интеграция с process_manager_module

## Известные проблемы

- На Windows `RotatingFileHandler` может падать при ротации общего файла (WinError 32). Для таких случаев в `ModuleConfig` / `ChannelConfig` есть `rotate: false` → `FileHandler` (см. ADR-051, `app_config.processor_frames`).
- Стресс-тест BatchBuffer под многопоточной нагрузкой не написан.

## История изменений

| Дата | Что сделано | Этап |
|---|---|---|
| 2026-03-11 | Начальное состояние, STATUS.md создан | 0 |
| 2026-03-12 | interfaces.py, bugs fixed, README, encoding headers | 2 |
| 2026-03-12 | BatchManager thread-safe, LogDispatcher fix, level-based routing | 3 |
| 2026-03-12 | CRM Фаза 2: LoggerManager(ChannelRoutingManager), ILogChannel(IChannel), BatchBuffer | 4 |
| 2026-03-12 | CRM Фаза 5: STATUS.md обновлён | 5 |
| 2026-03-31 | ADR-108: убран избыточный `build()` у `LoggerManagerConfig` (наследует `SchemaMixin.build`) | — |
| 2026-04-09 | Удалены LogDispatcher и batcher/; LogRecord → log_types.py; ADR-140…142 | 5 |
