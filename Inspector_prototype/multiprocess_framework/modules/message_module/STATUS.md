# message_module — Статус рефакторинга

## Текущий этап: 2 / 8

## Оценки (0-10)

| Критерий | Оценка | Комментарий |
|---|---|---|
| Код | 9 | `Message` = `SchemaBase`; один источник полей (`model_fields`), без Converter/Validator |
| Тесты | 9 | 112 pytest в модуле; `TestSchemaBaseIntegration` + проверка `model_dump` без `_msg_*` |
| Документация | 9 | README + `DECISIONS.md` (ADR-147…152), §6.7 в `ARCHITECTURE.md` |
| Связанность | 9 | `IMessage` как `Protocol`; фабрики и адаптер без изменений публичного API |
| Дублирование | 9 | Удалены `VALID_MESSAGE_FIELDS` / `MESSAGE_FIELD_DEFAULTS` / дублирующая `BaseMessageSchema` |
| Работоспособность | 9 | Dict at Boundary, `validate_assignment=False` для fluent API; полный прогон фреймворка OK |

## Рефакторинг по плану `plans/refactoring/08_message_schema_base.md` (2026-04-09)

- [x] `core/message.py` — `Message(SchemaBase)`, `@model_validator` вместо `apply_type_defaults`, `model_dump`/`model_validate` вместо конвертера
- [x] Удалены `converters/`, `validators/`, `schemas/base.py`; `BaseMessageSchema` = алиас на `Message` в `schemas/__init__.py`
- [x] `types/message_types.py` — только enums и `MESSAGE_TYPE_*`; убраны `VALID_MESSAGE_FIELDS`, `MESSAGE_FIELD_DEFAULTS`
- [x] `utils/utils.py` — только `generate_message_id()`
- [x] `schemas/command.py`, `schemas/log.py` — наследование `SchemaBase` + `FieldMeta` на ключевых полях
- [x] `interfaces.py` — `IMessage` переведён на `Protocol` (`@runtime_checkable`)
- [x] ADR-152 в `DECISIONS.md` модуля; строка в главном `multiprocess_framework/DECISIONS.md`

## Рефакторинг по плану `plans/refactoring/07_message_module.md` (2026-04-09) — база для 08

- [x] `MessageAdapter`, `IMessageFactory`, тесты clone/validate/parse (сохранены и проходят)

## Что сделано в этапе 2

- [x] `interfaces.py` — `IMessage` / `IMessageFactory`
- [x] `__init__.py` — публичный API без изменений имён экспортов
- [x] `adapters/message_adapter.py` — без смены внешнего API
- [x] `# -*- coding: utf-8 -*-` в Python-файлах модуля
- [x] `README.md` — структура каталога и `Message(SchemaBase)` (план 08)

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
| 2026-04-09 | План 08: Message = SchemaBase, удаление Converter/Validator/base schema, IMessage → Protocol, ADR-152 | 2 |
