# logger_module — Статус рефакторинга

## Текущий этап: 4 / 8

## Оценки (0–10)

| Критерий | Оценка | Комментарий |
|---|---|---|
| Код | 9 | Мигрирован на CRM; BatchBuffer из CRM; ILogChannel(IChannel); thread-safe registry |
| Тесты | 7 | ~30 тестов; все проходят; нужны: стресс-тест BatchBuffer, тест scope routing |
| Документация | 8 | README в стиле router_module; обновить примеры под CRM |
| Связанность | 9 | Наследует ChannelRoutingManager; зависит от channel_routing_module |
| Дублирование | 10 | Нет: _channel_registry из CRM, BatchBuffer из CRM, Dispatcher из CRM |
| Работоспособность | 8 | BatchBuffer + scope routing работают; channel_routing вместо channels: Dict |

## Что сделано в CRM-миграции (Фаза 2)

- [x] `ILogChannel(IChannel)` — унифицированная иерархия каналов
- [x] `LogChannel(ILogChannel)` — `name`, `channel_type` как `@property`; `FileChannel`, `ConsoleChannel`, `HttpChannel` наследуют
- [x] `LoggerManager(ChannelRoutingManager, ILoggerManager)` — убраны дублирующие реализации registry/buffer
- [x] `self._channel_registry` из CRM вместо `channels: Dict` (был без lock)
- [x] `BatchBuffer` из CRM вместо `BatchManager` (старый `BatchManager.py` оставлен для backward compatibility)
- [x] `_resolve_log_config()` — принимает None | dict | LogConfig | RegisterBase → LogConfig
- [x] Свойство `channels` сохранено для backward compatibility (возвращает dict из registry)
- [x] Свойство `batcher` — alias для `self._buffer`
- [x] `initialize()` / `shutdown()` обновлены — управляют CRM-компонентами

## Чеклист рефакторинга

- [x] Этап 0: Критические баги исправлены (config_dict, _route_via_router)
- [x] Этап 1: Модуль запускается — LoggerManager.initialize() работает
- [x] Этап 2: interfaces.py, README, encoding headers, интеграция с message_module
- [x] Этап 3: BatchManager thread-safe, LogDispatcher исправлен, level-based routing
- [x] Этап 4: LoggerManager наследует ChannelRoutingManager; ILogChannel(IChannel)
- [ ] Этап 5: Интеграционный тест — приём LOG-сообщений через RouterManager
- [ ] Этап 6: Graceful shutdown — flush() перед остановкой + router unsubscribe
- [ ] Этап 7: Unit-тесты — покрытие > 85%, стресс-тест BatchBuffer под нагрузкой
- [ ] Этап 8: Полная интеграция с process_manager_module

## Известные проблемы

- На Windows `RotatingFileHandler` может падать при ротации общего файла (WinError 32). Для таких случаев в `ModuleConfig` / `ChannelConfig` есть `rotate: false` → `FileHandler` (см. ADR-051, `app_config.processor_frames`).
- `LoggerManager.log()` использует scope-based routing (список каналов из ScopeConfig).
  `route_by_level()` из LogDispatcher доступен, но не задействован как основной путь.
- `LogDispatcher` сохранён для backward compatibility и для ErrorManager.
- Стресс-тест BatchBuffer под многопоточной нагрузкой не написан.
- README не обновлён под CRM-архитектуру (показывает старую ChannelRegistry).

## История изменений

| Дата | Что сделано | Этап |
|---|---|---|
| 2026-03-11 | Начальное состояние, STATUS.md создан | 0 |
| 2026-03-12 | interfaces.py, bugs fixed, README, encoding headers | 2 |
| 2026-03-12 | BatchManager thread-safe, LogDispatcher fix, level-based routing | 3 |
| 2026-03-12 | CRM Фаза 2: LoggerManager(ChannelRoutingManager), ILogChannel(IChannel), BatchBuffer | 4 |
| 2026-03-12 | CRM Фаза 5: STATUS.md обновлён | 5 |
