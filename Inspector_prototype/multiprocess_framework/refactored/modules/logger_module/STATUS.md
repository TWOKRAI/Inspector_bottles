# logger_module — Статус рефакторинга

## Текущий этап: 3 / 8

## Оценки (0-10)

| Критерий | Оценка | Комментарий |
|---|---|---|
| Код | 9 | Все 3 критических бага устранены, level-based routing добавлен |
| Тесты | 4 | 10/10 проходят; нужно: тест BatchManager под нагрузкой, тест route_by_level |
| Документация | 8 | README в стиле router_module |
| Связанность | 8 | LogDispatcher аналогичен channel_dispatcher из RouterManager |
| Дублирование | 9 | _convert_level упрощён до `LogLevel[level.upper()]` |
| Работоспособность | 8 | thread-safe BatchManager, handler вызывается напрямую |

## Что сделано в этапе 3

- [x] **Bug fix**: `LogDispatcher.route_log()` вызывал `dispatcher.dispatch(channel_name, record_dict)` —
      первый аргумент трактовался как `message` (str), второй как `key_field` (dict) → TypeError
      поглощался молча → **логи физически не записывались**. Исправлено:
      `handler(record_dict)` вызывается напрямую.
- [x] **Bug fix**: `BatchManager.flush_all()` не был thread-safe при конкурентном доступе.
      Добавлен `threading.Lock`; атомарное извлечение пачки под локом,
      вызов flush_callback вне лока (I/O не блокирует других писателей).
- [x] **Bug fix**: `LoggerAdapter._convert_level()` имел мёртвый код с ручным маппингом.
      Упрощено до `LogLevel[level.upper()]` + except KeyError → None.
- [x] **Архитектурное улучшение**: `LogDispatcher.register_level_route()` + `route_by_level()` —
      level-based routing через Dispatcher (аналог `channel_dispatcher` в RouterManager):
      `dispatch(record_dict, key_field='level')` — теперь dispatch_module используется корректно.
      Позволяет: `ERROR → errors.log`, `WARNING → system.log`, `r".*" → console`.
- [x] `LogDispatcher.get_level_routes()` / `get_channel_names()` — интроспекция маршрутов.

## Чеклист рефакторинга

- [x] Этап 0: Критические баги исправлены (config_dict, _route_via_router)
- [x] Этап 1: Модуль запускается — LoggerManager.initialize() работает
- [x] Этап 2: interfaces.py, README, encoding headers, интеграция с message_module
- [x] Этап 3: BatchManager thread-safe, LogDispatcher исправлен, level-based routing
- [ ] Этап 4: LoggerManager.log() использует route_by_level (заменить scope-based на level-based)
- [ ] Этап 5: Интеграционный тест — приём LOG-сообщений через RouterManager
- [ ] Этап 6: Graceful shutdown — flush() перед остановкой + router unsubscribe
- [ ] Этап 7: Unit-тесты — покрытие > 85%, стресс-тест батчинга
- [ ] Этап 8: Полная интеграция с process_manager_module

## Известные проблемы

- `LoggerManager.log()` всё ещё использует scope-based канальный список из ScopeConfig,
  а не новый `route_by_level()`. Этап 4 исправит это.
- Стресс-тест BatchManager под многопоточной нагрузкой не написан.

## История изменений

| Дата | Что сделано | Этап |
|---|---|---|
| 2026-03-11 | Начальное состояние, STATUS.md создан | 0 |
| 2026-03-12 | interfaces.py, bugs fixed, README, encoding headers | 2 |
| 2026-03-12 | BatchManager thread-safe, LogDispatcher fix, level-based routing, _convert_level | 3 |
