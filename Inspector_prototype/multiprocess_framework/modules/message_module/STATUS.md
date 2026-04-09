# message_module — Статус рефакторинга

## Текущий этап: 2 / 8

## Оценки (0-10)

| Критерий | Оценка | Комментарий |
|---|---|---|
| Код | 8 | Чистый, структурированный, encoding headers везде |
| Тесты | 8 | 103 pytest в модуле; покрытие пакета ~94% (--cov) |
| Документация | 9 | README + `DECISIONS.md` (ADR-147…151), §6.7 в `ARCHITECTURE.md` |
| Связанность | 8 | IMessage / IMessageFactory как единый контракт |
| Дублирование | 8 | MessageAdapter устраняет дублирование кода создания |
| Работоспособность | 8 | Dict at Boundary соблюдается, все тесты проходят |

## Рефакторинг по плану `plans/refactoring/07_message_module.md` (2026-04-09)

- [x] `core/message.py` — убраны ленивый `_data` / `_sync_to_dict()`, `get`/`keys`/`values`/`items` на атрибутах; `__init__` + `MESSAGE_FIELD_DEFAULTS` в `types/message_types.py`
- [x] `converters/message_converter.py` — `to_dict` собирает поля через `VALID_MESSAGE_FIELDS` и `getattr`
- [x] `DECISIONS.md` модуля (ADR-147…151), строка в главном `multiprocess_framework/DECISIONS.md`, §6.7 в `ARCHITECTURE.md`
- [x] Тесты: `TestClone`, `TestValidateWithoutSchema`, `TestParseMessage` в `tests/test_message.py`

## Что сделано в этапе 2

- [x] `interfaces.py` — добавлен `IMessage` (контракт любого сообщения), `IMessageFactory` переписан
- [x] `__init__.py` — экспортирует `IMessage`, `IMessageFactory`, `MessageAdapter`
- [x] `adapters/message_adapter.py` — единый способ создания сообщений для процессов:
      `command()`, `log()`, `system()`, `broadcast()`, `data()`, `request()`, `response()`, `event()`
- [x] `# -*- coding: utf-8 -*-` добавлен во все Python-файлы
- [x] `README.md` переписан: архитектура, таблицы полей, API, интеграция с router_module
- [x] Внутренние интерфейсы (`IMessageValidator`, `IMessageConverter`) убраны из `interfaces.py`

## Чеклист рефакторинга

- [x] Этап 0: Критические баги исправлены
- [x] Этап 1: Модуль работает — Message.create(), to_dict(), from_dict()
- [x] Этап 2: interfaces.py, MessageAdapter, README, Dict at Boundary
- [ ] Этап 3: Коммуникация через Router проверена (интеграционные тесты)
- [ ] Этап 4: Shared memory (DATA тип) — интеграция с shared_resources_module
- [ ] Этап 5: CommandManager подключён (COMMAND тип — handlers зарегистрированы)
- [ ] Этап 6: Graceful shutdown — SYSTEM тип, обработка в оркестраторе
- [ ] Этап 7: Unit-тесты — покрытие > 90%, test_adapter.py завершён
- [ ] Этап 8: Полная интеграция с process_manager_module

## Известные проблемы

- `test_adapter.py` — не все edge-cases покрыты
- Для REQUEST/RESPONSE паттерна нет встроенного correlation_id registry
  (это зона `router_module` или отдельного RequestTracker)

## История изменений

| Дата | Что сделано | Этап |
|---|---|---|
| 2026-03-11 | Начальное состояние, STATUS.md создан | 0 |
| 2026-03-12 | interfaces.py (IMessage), MessageAdapter, README, encoding headers | 2 |
| 2026-04-09 | План 07: сжатие `message.py`, DECISIONS ADR-147…151, §6.7 ARCHITECTURE, тесты clone/validate/parse | 2 |
