# error_module — Статус рефакторинга

## Текущий этап: 2 / 8

## Оценки (0-10)

| Критерий | Оценка | Комментарий |
|---|---|---|
| Код | 9 | Encoding headers, severity channels, _setup_level_routes() |
| Тесты | 7 | 10/10 проходят; нужно: тест _setup_level_routes, тест get_stats |
| Документация | 9 | README переписан в стиле router_module с диаграммой |
| Связанность | 9 | Зависит только от logger_module, interfaces.py — единый контракт |
| Дублирование | 10 | Нет дублирования (наследует LoggerManager корректно) |
| Работоспособность | 8 | Severity routing работает; интеграционный тест не написан |

## Что сделано в этапе 2

- [x] `# -*- coding: utf-8 -*-` добавлен во все 6 файлов модуля
- [x] `core/error_manager.py`:
      - `_DEFAULT_CONFIG` расширен до 3 severity-каналов: critical, errors, warnings
      - `default_level` изменён с ERROR на WARNING (ErrorManager ловит WARNING и выше)
      - Добавлен `initialize()` override — вызывает `_setup_level_routes()` после super()
      - Добавлен `_setup_level_routes()` — level-based routing через LogDispatcher:
          CRITICAL → critical_file, ERROR → errors_file, WARNING → warnings_file
      - `log_exception()` — улучшена проверка трейса (NoneType: None → не добавлять)
      - `get_stats()` расширен: `include_stacktrace` + `level_routes`
- [x] `config/error_config.py`:
      - Добавлены `critical_file_path` и `warnings_file_path` в ErrorManagerConfig
      - `build()` генерирует 3 канала (warnings_file — опционально, только если путь задан)
      - `default_level` изменён с "ERROR" на "WARNING"
- [x] `interfaces.py`: `IErrorManager` улучшен (warning, info, critical, get_stats)
- [x] `README.md` полностью переписан в стиле router_module

## Чеклист рефакторинга

- [x] Этап 0: interfaces.py создан, STATUS.md создан
- [x] Этап 1: Модуль запускается — ErrorManager.initialize() работает
- [x] Этап 2: interfaces.py, README, encoding headers, severity routing, ErrorManagerConfig
- [ ] Этап 3: Интеграционный тест — приём ERROR-сообщений от RouterManager
- [ ] Этап 4: Кастомный severity-канал (AlertChannel → Telegram/Slack)
- [ ] Этап 5: LoggerManager.log() переходит на route_by_level() (этап 4 logger_module)
- [ ] Этап 6: Graceful shutdown — flush() + router unsubscribe
- [ ] Этап 7: Unit-тесты — покрытие > 85% (level routes, get_stats, severity channels)
- [ ] Этап 8: Полная интеграция с process_manager_module

## Известные проблемы

- `LoggerManager.log()` использует scope-based routing, не вызывает `route_by_level()`.
  `_setup_level_routes()` регистрирует маршруты в Dispatcher, но они не задействованы
  пока LoggerManager не перейдёт на `route_by_level()` (Этап 4 logger_module).

## История изменений

| Дата | Что сделано | Этап |
|---|---|---|
| 2026-03-11 | interfaces.py добавлен, STATUS.md создан | 0 |
| 2026-03-12 | interfaces.py улучшен (warning/info/critical/get_stats) | 1 |
| 2026-03-12 | Severity channels, level routing, ErrorManagerConfig, README | 2 |
