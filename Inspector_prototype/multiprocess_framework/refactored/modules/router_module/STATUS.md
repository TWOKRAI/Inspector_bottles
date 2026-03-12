# router_module — Статус рефакторинга

## Текущий этап: 2 / 8

## Оценки (0-10)

| Критерий | Оценка | Комментарий |
|----------|--------|-------------|
| Код | 9 | Баги исправлены, print() убран, log callbacks инжектируются |
| Тесты | 8 | ~797 строк, хорошее покрытие; нет тестов _attach_logger |
| Документация | 9 | README — единый источник правды; лишние файлы удалены |
| Связанность | 8 | RouterAdapter очищен; дублирование с ProcessCommunication устранено |
| Дублирование | 8 | send_to_process/broadcast убраны из адаптера |
| Работоспособность | 8 | correlation_id отсутствует (этап 5); ErrorManager не подключён |

## Чеклист рефакторинга

- [x] Этап 0: Критические баги исправлены (falsy message, print() в каналах, isinstance check)
- [x] Этап 1: Интерфейс IRouterManager полный (remove_message_callback, clear_middleware, get_all_channels)
- [x] Этап 2: Инъекция логирования в каналы (_attach_logger, MessageChannel с log callbacks)
- [ ] Этап 3: Config-driven channels (каналы объявляются через конфиг процесса)
- [ ] Этап 4: ErrorManager интегрирован через ObservableMixin
- [ ] Этап 5: correlation_id для request-response паттерна
- [ ] Этап 6: StatsManager подключён
- [ ] Этап 7: Тесты _attach_logger + интеграционные тесты с LoggerManager
- [ ] Этап 8: Полная интеграция с process_module (config-driven setup)

## Известные проблемы

- `correlation_id` для request-response — этап 5
- `ErrorManager` не подключён — ошибки через `_log_error` попадают в `LoggerManager`
- `StatsManager` не реализован
- Config-driven channels (объявление `worker_in` через конфиг) — этап 3

## История изменений

| Дата | Что сделано | Этап |
|------|-------------|------|
| 2026-03-11 | Начальное состояние | 0 |
| 2026-03-12 | Рефакторинг: fix bugs, log injection, clean adapter, clean docs | 1-2 |
