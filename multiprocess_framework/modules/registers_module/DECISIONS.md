# registers_module — архитектурные решения

Локальные ADR для runtime-слоя регистров. Глобальный контекст: `multiprocess_framework/DECISIONS.md` (ADR-002, ADR-048).

---

## ADR-RM-001: Композиция RegistersContainer вместо дублирования

- **Дата:** 2026-04-10
- **Статус:** принято
- **Контекст:** `RegistersManager` дублировал хранение dict, ручной разбор `json_schema_extra` для метаданных и логику `model_dump_all` / `model_validate_all`, уже реализованные в `data_schema_module.RegistersContainer` и `SchemaMixin`.
- **Решение:** `RegistersManager` **композирует** `RegistersContainer`. Хранение, `get_field_metadata`, `validate_field` (через контейнер) и сериализация — делегирование. В модуле остаются подписки, `set_field_value`, `resolve_dispatch_targets` / `send_callback`.
- **Почему не наследование:** контейнер — data-oriented (diff, snapshot, IO); менеджер — runtime-oriented (pub/sub, dispatch). Композиция явно разделяет ответственность.
- **Следствие:** `RegistersContainer` принимает в конструкторе как **классы** моделей, так и **готовые экземпляры** (для совместимости с фабриками прототипа); добавлен `__setitem__` для динамической подстановки регистра.

---

## ADR-RM-002: Удаление IRegistersConverter

- **Дата:** 2026-04-10
- **Статус:** принято
- **Контекст:** Протокол без реализаций и потребителей кроме реэкспорта в `__init__.py`.
- **Решение:** Удалён. Конвертация dict/JSON/YAML — `RegistersContainer.to_dict` / `from_dict` / `to_json` и т.д.

---

## ADR-RM-003: Модуль `core/dispatch.py`

- **Дата:** 2026-04-10
- **Статус:** принято
- **Контекст:** `build_connection_map_from_registers` жил отдельно от логики выбора целей `register_update`.
- **Решение:** В `core/dispatch.py` объединены `build_connection_map_from_registers` и публичная `resolve_dispatch_targets()` (бывшая внутренняя логика менеджера). Менеджер вызывает функцию; проще тестировать dispatch изолированно.

---

## ADR-RM-004: Логирование вместо silent `except`

- **Дата:** 2026-04-10
- **Статус:** принято
- **Контекст:** Исключения в observer callbacks и в `send_callback` проглатывались.
- **Решение:** `logging.getLogger(__name__)`. Ошибки подписчиков — `warning` с `exc_info`; ошибки `send_callback` — `error`; успешный `set_field_value` — `debug`.

---

## ADR-RM-005: Этапы 1–6 не применимы к registers_module

- **Статус:** Принято (2026-04-10)
- **Контекст:** `registers_module` — не `ProcessModule`, а runtime-библиотека внутри процесса. Этапы 1–6 общего чеклиста (оркестратор, subprocess, Router, ДНК, CommandManager, graceful shutdown) описаны для модулей с отдельным lifecycle и IPC-менеджерами.
- **Решение:** Этапы 1–6 для данного модуля помечены как **N/A**. Завершённость модуля фиксируется по этапам 0, 7 и 8 (качество кода, тесты, контракт и документация). Протокол `IRegistersManager` расширен до полного mirror публичного API `RegistersManager` (хранение, dump/validate, pub/sub, запись и dispatch), чтобы `build_routing_map`, тесты и UI опирались на один контракт.
- **Обоснование:** `RegistersManager` создаётся в процессе (часто GUI), не имеет собственного subprocess/Router lifecycle. Связь с роутером — через `send_callback`, который настраивает `FrontendRegistersBridge` или приложение.
