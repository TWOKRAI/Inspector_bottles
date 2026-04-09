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

**Статус:** принято  
**Дата:** 2026-04-09  
**Контекст:** `MessageSchema` дублировал `BaseMessageSchema` и `VALID_MESSAGE_FIELDS`.  
**Решение:** Удалить dataclass. Единственный источник истины:
- `VALID_MESSAGE_FIELDS` — валидация
- `BaseMessageSchema` — Pydantic
- `Message` атрибуты — runtime state

**Последствия:** При добавлении поля обновляем 2 места вместо 3.

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
