# message_module — Архитектурные решения

> Ссылки: [`../../DECISIONS.md`](../../DECISIONS.md) (ADR-008 Dict at Boundary)

## ADR-MSG-001 (was ADR-147): Message как value object с опциональной Pydantic-схемой

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

## ADR-MSG-002 (was ADR-148): MessageAdapter — единственная точка создания в процессе

**Статус:** принято  
**Дата:** 2026-04-09  
**Контекст:** `Message.create()` требует повторения `sender=` в каждом вызове.  
**Решение:**
- `MessageAdapter(sender=name)` — один на процесс/менеджер.
- Все методы (`.command()`, `.log()`, `.event()`) имеют фиксированный sender.
- `Message.create()` остаётся для тестов.

**Последствия:** Устраняет повторение sender. Методы явно указывают намерение.

---

## ADR-MSG-003 (was ADR-149): Удаление MessageSchema dataclass

**Статус:** принято (частично устарело по смыслу — см. **ADR-152**)  
**Дата:** 2026-04-09  
**Контекст:** `MessageSchema` дублировал `BaseMessageSchema` и `VALID_MESSAGE_FIELDS`.  
**Решение (историческое):** Удалить dataclass; далее в **ADR-152** единственный источник — `Message.model_fields`.

**Последствия:** См. **ADR-152**.

---

## ADR-MSG-004 (was ADR-150): Поле `routers` — маршрутизация внутри процесса

**Статус:** принято  
**Дата:** 2026-04-09  
**Контекст:** `routers` field роль неясна.  
**Решение:**
- `targets` — имена процессов (межпроцессная адресация)
- `channel` — имя канала в RouterManager получателя
- `routers` — список RouterManager'ов внутри одного процесса

**Последствия:** Default `["internal"]` — один RouterManager на процесс. LOG исключает из `to_dict()`.

---

## ADR-MSG-005 (was ADR-151): Нет pickle-safe гарантий для Message объекта

**Статус:** принято  
**Дата:** 2026-04-09  
**Контекст:** Framework принцип #5 — pickle-safe для Windows spawn.  
**Решение:** `Message` НЕ гарантируется pickle-safe. Только `msg.to_dict()` (dict) пересекает границу.  
**Тест:** `test_message_dict_is_pickle_safe` проверяет dict-форму.

**Последствия:** Developers ВСЕГДА используют `msg.to_dict()` перед IPC отправкой.

---

## ADR-MSG-006 (was ADR-152): Message наследует SchemaBase (Pydantic v2)

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

**Примечание:** `Message` — единственный `SchemaBase`-наследник без `FieldRouting`. Это осознанное решение: `Message` — value object для IPC-транспорта, а не регистр с маршрутизацией полей. Маршрутизация сообщений определяется полями `targets` / `channel` / `routers` напрямую, без `FieldRouting`.

---

## ADR-MSG-007: Иерархическая адресация — dotted-адрес внутри `targets` (`addressing/`)

**Статус:** принято  
**Дата:** 2026-05-31  
**Контекст:** План `transport-router-hub` (P0.2) и глобальный [ADR-COMM-004](../../DECISIONS.md) вводят иерархический адрес получателя `process → worker → глубже` (память `project-hierarchical-addressing`). Нужно адресовать уровень «воркер» (долг #2 `assigned_worker`), не вводя новое поле и не ломая существующий `targets`.  
**Решение:** Каждый элемент `Message.targets` — **dotted-адрес** `process[.worker[.…]]`. Пакет `message_module/addressing/` (чистые JSON-safe функции): `split_address`/`process_of`/`worker_of`/`subpath_of`/`depth`/`join_address`/`validate_address`/`normalize_targets`; исключение `AddressValidationError(MessageValidationError)`. Prefix-правило (процесс первым, воркер без процесса → ошибка), backward-compat плоского `"proc"` == `["proc"]`. `normalize_targets(target=, targets=)` сводит сосуществующие скаляр `target` (data-plane) и список `targets` к единому `list[str]` (recon #2).  
**Причина:** Иерархия живёт **внутри** существующего `targets: list[str]` — мультикаст сохранён, новое поле не вводится, JSON-safe (Dict-at-Boundary, правило #1). Транспортная семантика (доставка по `address[0]`, intra-process резолв воркера) — в `router_module`/P1–P2, здесь только парсинг/валидация.  
**Последствия:** `targets` обретает иерархию без миграции данных (плоские имена продолжают работать). `AddressValidationError` ловится существующими обработчиками `MessageValidationError`.  
**Refs:** [ADR-COMM-004](../../DECISIONS.md), [ADR-COMM-001](../../DECISIONS.md), [plans/2026-05-31_transport-router-hub/plan.md](../../../plans/2026-05-31_transport-router-hub/plan.md)
