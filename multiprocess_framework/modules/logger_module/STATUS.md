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

## Обновление 2026-07-26 (G4-live)

- **`adapters/std_facade.py`:** `StdLoggerFacade` + `get_std_logger(module)` — мост из
  stdlib-стиля (`logger.warning("%s", x)`) в `LoggerManager`. Повод: живой прогон показал,
  что 44 файла GUI-слоя прототипа пишут через `logging.getLogger(__name__)`, у которого в
  процессе нет ни одного хендлера → записи не доходили ни до `logs/<proc>/*.log`, ни до
  консоли. Без менеджера фасад пишет в stdlib (фолбэк), а не молчит: тишина — второй
  проглот той же ошибки. 18 тестов (`tests/test_std_facade.py`).
- Первые потребители: `topology_bridge.py` (заменил локальный шим), `processes/presenter.py`.
  Остальные 43 файла — задача H.4.

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

- На Windows `RotatingFileHandler` может падать при ротации общего файла (WinError 32). Для таких случаев в `ModuleConfig` / `ChannelConfig` есть `rotate: false` → `FileHandler` (см. ADR-051, `app_config.processor_frames`). Сам сбой ротации (fail-open — запись продолжается в текущий файл) теперь виден: `_SafeRotatingFileHandler` считает сбои подряд и не чаще раза в 60с пишет WARNING с именем файла, размером и числом неудач — раньше `PermissionError` глушился молча без счётчика и предупреждения (живая находка 2026-07-21, `messages.log` вырос до 645 МБ незамеченным).
- Стресс-тест BatchBuffer под многопоточной нагрузкой не написан.
- **Цена urgent-сброса на ERROR/CRITICAL (Ф0.1, ВРЕМЕННО).** `LoggerCore.log()` и severity-путь `ErrorManager.log()` передают `priority="urgent"`, а `BatchBuffer` по этому триггеру сбрасывает **всю накопленную пачку канала** синхронно в потоке-эмитенте. Замер (Windows, дефолтный `batch_size=100`): первая ошибка на полной пачке — **1.3 мс p50 / 1.6 мс p95**; на пустой — 0.13 мс. Шторм ошибок **не** множит цену: первый же сброс осушает пачку, последующие ошибки стоят **~0.02 мс**. То есть худший случай ограничен `batch_size` и платится один раз за окно накопления (~8–9 % бюджета кадра на 60 FPS). Размен принят сознательно: полная пачка перед падением ценна для криминалистики. Снимается задачей **Ф0.9** (floor ошибок, вариант B — синхронный конфиго-независимый путь), окончательно — Ф7.2/Ф7.3 (политика переполнения и вынос наблюдаемости с `system`-очереди). План: [`plans/observability-unified-routing.md`](../../../plans/observability-unified-routing.md).
  Счётчик `urgent_flushes` в `BatchBuffer.stats` отделяет такие сбросы от сбросов по заполнению — иначе `total_batches` перестал бы быть мерой эффективности батчинга.
  Файл `batch_buffer.py` правки логики **не потребовал**: ветка немедленного сброса там была корректна изначально, в спеке Ф0.1 он указан как место недостижимого условия, а не как объект правки.

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
| 2026-07-21 | `_SafeRotatingFileHandler`: счётчик сбоев ротации + троттлированный WARNING (видимость систематического отказа, fail-open не тронут) | 5 |
| 2026-07-26 | Ф0.1: `buffer_priority()` + `priority="urgent"` для ERROR/CRITICAL — закрыто окно потери crash-лога (было до `batch_interval`). Временно, снимается Ф0.9. Размен измерен, см. «Известные проблемы» | — |
