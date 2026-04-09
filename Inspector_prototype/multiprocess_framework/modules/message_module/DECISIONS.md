# message_module — Архитектурные решения

> Ссылки: [`../../DECISIONS.md`](../../DECISIONS.md) (ADR-008 Dict at Boundary)

## ADR-147: Message как value object с опциональной Pydantic-схемой

**Статус:** принято  
**Дата:** 2026-04-09  
**Контекст:** Нужен IPC-примитив для передачи между процессами. Сообщение должно быть легковесным, но типизированным.  
**Решение:**
- `Message` — value object: нет ID-based equality.
- `schema=None` — нормальный путь. Pydantic схема — опциональное усиление.
- Между процессами: только `msg.to_dict()`.
- `Message.from_dict(raw)` — восстановление на стороне получателя.

**Последствия:** Message остаётся легковесным. Pydantic overhead только где нужна строгая валидация.

---

## ADR-148: MessageAdapter — единственная точка создания в процессе

**Статус:** принято  
**Дата:** 2026-04-09  
**Контекст:** `Message.create()` требует повторения `sender=` в каждом вызове.  
**Решение:**
- `MessageAdapter(sender=name)` — один на процесс/менеджер.
- Все методы (`.command()`, `.log()`, `.event()`) имеют фиксированный sender.
- `Message.create()` остаётся для тестов.

**Последствия:** Устраняет повторение sender. Методы явно указывают намерение.

---

## ADR-149: Удаление MessageSchema dataclass

**Статус:** принято (частично устарело по смыслу — см. **ADR-152**)  
**Дата:** 2026-04-09  
**Контекст:** `MessageSchema` дублировал `BaseMessageSchema` и `VALID_MESSAGE_FIELDS`.  
**Решение (историческое):** Удалить dataclass; далее в **ADR-152** единственный источник — `Message.model_fields`.

**Последствия:** См. **ADR-152**.

---

## ADR-150: Поле `routers` — маршрутизация внутри процесса

**Статус:** принято  
**Дата:** 2026-04-09  
**Контекст:** `routers` field роль неясна.  
**Решение:**
- `targets` — имена процессов (межпроцессная адресация)
- `channel` — имя канала в RouterManager получателя
- `routers` — список RouterManager'ов внутри одного процесса

**Последствия:** Default `["internal"]` — один RouterManager на процесс. LOG исключает из `to_dict()`.

---

## ADR-151: Нет pickle-safe гарантий для Message объекта

**Статус:** принято  
**Дата:** 2026-04-09  
**Контекст:** Framework принцип #5 — pickle-safe для Windows spawn.  
**Решение:** `Message` НЕ гарантируется pickle-safe. Только `msg.to_dict()` (dict) пересекает границу.  
**Тест:** `test_message_dict_is_pickle_safe` проверяет dict-форму.

**Последствия:** Developers ВСЕГДА используют `msg.to_dict()` перед IPC отправкой.

---

## ADR-152: Message наследует SchemaBase (Pydantic v2)

**Статус:** принято  
**Дата:** 2026-04-09  
**Контекст:** `Message` был plain class с ручным `MessageConverter`, `MessageValidator`, dict'ами `VALID_MESSAGE_FIELDS` / `MESSAGE_FIELD_DEFAULTS` и отдельным `BaseMessageSchema`, дублировавшим поля. Общие `{}` / `[]` в дефолтах давали риск мутации между экземплярами.

**Решение:**

- `Message` наследует `SchemaBase` (`data_schema_module`).
- Все поля объявлены как поля Pydantic с `FieldMeta` где нужна интроспекция.
- `model_dump()` / сериализация в `to_dict()` заменяют `MessageConverter`.
- `model_validate()` / конструктор заменяют ручную сборку в конвертере.
- `@model_validator(mode='after')` заменяет `apply_type_defaults()`.
- `validate_assignment=False` на `Message` — без лишнего overhead на fluent setters (в отличие от базового `SchemaBase`).
- `IMessage` — `Protocol` (`@runtime_checkable`) вместо ABC.
- `BaseMessageSchema` — алиас на `Message` для обратной совместимости импорта.

**Удалено:**

- `converters/message_converter.py`
- `validators/message_validator.py`
- `schemas/base.py` (класс `BaseMessageSchema`)
- `VALID_MESSAGE_FIELDS`, `MESSAGE_FIELD_DEFAULTS`, `apply_type_defaults()`

**Последствия:** Один источник истины — `Message.model_fields`; строгие схемы `CommandMessageSchema` / `LogMessageSchema` остаются отдельными (`extra='forbid'`). Публичный API (`create`, `to_dict`, `from_dict`, `MessageAdapter`) сохранён.
