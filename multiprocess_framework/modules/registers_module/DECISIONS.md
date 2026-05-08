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

---

## ADR-RM-006: Регистры vs State Store — когда что применять

- **Дата:** 2026-05-08
- **Статус:** принято

### Контекст

Два модуля фреймворка предоставляют pub/sub-механизмы для отслеживания изменений:

- `registers_module` — runtime-слой над типизированными Pydantic-инстансами (`SchemaBase`)
- `state_store_module` — реактивное дерево произвольных значений с glob-подписками

Оба позволяют подписываться на изменения и рассылать уведомления. Без явного разграничения новый разработчик выбирает инструмент интуитивно, что приводит к нецелевому использованию.

### Решение: Decision Matrix

| Критерий | `registers_module` | `state_store_module` |
|----------|-------------------|---------------------|
| **Структура данных** | Именованный dict: `{register_name: SchemaBase}` | Произвольное дерево: вложенные dict с dot-path навигацией |
| **Типизация** | Строгая — Pydantic v2 + `FieldMeta` валидация | Без типизации — любое JSON-serializable значение |
| **Паттерн подписки** | Per-field: `subscribe(register, field, callback)` | Glob-pattern: `subscribe("cameras.*.config.*", callback)` |
| **Доставка изменений** | Snapshot — полный `model_dump` регистра при каждом fan-out | Delta-only — `Delta(path, old_value, new_value, source, ts)` |
| **Middleware** | Нет встроенного | `ThrottleMiddleware`, `ValidationMiddleware`, `LoggingMiddleware`, `MetricsMiddleware` |
| **IPC fan-out** | `FieldRouting.process_targets` → `register_update` в `control_<process>` | Addressed delivery — сервер матчит pattern, шлёт `state.changed` только подписчикам |
| **Типичные применения** | Конфигурация устройств, UI-настройки, рецепты, параметры детекции | Real-time метрики, телеметрия, динамические топологии, heartbeat, статусы |
| **Антипаттерн (не применять)** | Динамические runtime-метрики (FPS, latency) — нет throttle, snapshot на каждое изменение | Типизированные конфиги с валидацией — нет FieldMeta, нет schema enforcement |

### Правило выбора

**Если поле имеет схему, имя и FieldRouting — регистр. Если структура динамическая, иерархическая или runtime-метрика — state store.**

### Граничные случаи

| Сценарий | Выбор | Почему |
|----------|-------|--------|
| UI-форма настроек камеры (resolution, exposure) | Регистр | Типизировано, FieldRouting нужен для fan-out в backend |
| Текущий FPS процесса (меняется 30 раз/с) | State store | Runtime-метрика, throttle, не нужна валидация |
| Список активных процессов (динамический) | State store | Glob-подписка `processes.*`, меняется при start/stop |
| Таблица рецептов (фиксированная схема) | Регистр | Pydantic-схема, snapshot/restore через RecipeEngine |

### Почему не объединять

Каждый модуль оптимизирован под свою модель доставки. Объединение создаст «швейцарский нож» без гарантий производительности:
- Delta-IPC (state_store) несовместим с full-snapshot fan-out (registers) — либо лишний трафик, либо потеря дельт.
- FieldRouting завязан на `SchemaBase.json_schema_extra` — в произвольном dict-tree этого нет.
- Middleware pipeline (throttle, validation) имеет смысл только для высокочастотных обновлений, которые registers не генерирует.

### Связанные решения

- ADR-RM-001 (композиция RegistersContainer)
- ADR-SS-001 (IRouter Protocol — модуль не зависит от конкретных интеграций)
- ADR-SS-011 (доменно-нейтральный PersistenceManager)
- CONSTRUCTOR_BLUEPRINT §4, паттерн 8
