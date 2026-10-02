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

---

## ADR-RM-007: Копия регистра из описания каталога

- **Дата:** 2026-09-25
- **Статус:** принято

### Контекст

Task 1b.2a дал `RegistersManager.from_catalog()` (payload команды `catalog.plugins`,
Dict at Boundary — GUI-процесс не импортирует класс плагина). До этой задачи метод
заполнял только `_fields_cache` для `get_fields()` — ни одного экземпляра регистра
не создавалось. Значит `set_value`/`validate`/`set_field_value`/`register_names()`/
`get_register()`/`model_dump_all()` у catalog-менеджера были пустыми или `False`:
форма из каталога отображалась, но правка пользователя нигде не оседала — молча.

### Решение

Для каждой записи каталога с непустыми `register.fields` строим СИНТЕТИЧЕСКУЮ копию
регистра: `pydantic.create_model(name, __base__=SchemaBase, **{field_name: (Annotated[
field_type, meta] if meta else field_type, default)})()` — над уже декодированными
`FieldInfo` (тот же кодек `FieldInfo.to_dict()`/`from_dict()`, что даёт `get_fields()`).

`SchemaBase` несёт `validate_assignment=True` — та же проверка ТИПА и `Literal`-
принадлежности при `setattr`, что и на живом инстансе плагина. Измерено лидом
эмпирически на реальных полях: копия и оригинал совпадают на невалидном `Literal`,
`str`→`int`, значении ниже `min`. Для параметризованных `list`/`dict` это стало так
только с Task 1b.2d-1 (2026-10-02): кодек несёт тип элемента (`item`/`key`/`value`).

Изоляция per-plugin: если `create_model`/инстанцирование одного плагина падает —
ошибка ловится и пишется одной строкой через `get_std_logger(__name__)` — он работает и
без `logger=` (фасад сам выбирает LoggerManager процесса или stdlib), а `_log_warning`
без слота `logger` запись теряет (MAJOR ревью ниже; второй канал `_log_warning` снят в
итерации 2 — при поднятом LoggerManager запись уходила дважды). Изоляция покрывает оба
шага на запись: разбор описания (`FieldInfo.from_dict` — поле без `type`, поле-строка) и
сборку копии (`create_model`). Не разобранная запись пропускается целиком; не собранная
остаётся с формой (`get_fields`), но без инстанса — правка такого поля отвечает «Регистр
не найден», и строка в логе объясняет почему. Изоляция проверена тестами (a) и (g).

### Ограничения (то, что НЕ переносится в копию — ЧЕСТНО, по находкам ревью 2026-09-25)

- **Class-level python-валидаторы** (`field_validator`/`model_validator` на классе
  плагина) — копия строится из `FieldInfo` (имя/тип/дефолт/`FieldMeta`), а не из
  исходного класса, поэтому кастомные Python-валидаторы физически недоступны на
  границе (Dict at Boundary — класс плагина не пересекает процесс). **Такие
  валидаторы могут быть УНАСЛЕДОВАНЫ из `Services`, не только объявлены в
  `Plugins/`** — грепом по `Plugins/` их не проинвентаризировать. Пример, найденный
  ревью: `otel_export` — `OtelExportConfig` в `Services/otel_export/config.py` несёт
  4 `field_validator` + 1 `model_validator`; один из них нормализует значение
  (`'  http://…/v1/logs  '` → реальный класс убирает пробелы, копия — нет). Полный
  инвентарь наследуемых валидаторов по всем 43 плагинам с регистром НЕ проводился.
- **Class attribute `register_dispatch`** (`RegisterDispatchMeta` на классе) — та же
  причина: атрибут класса, не поле модели, `FieldInfo` его не переносит.
- **Ведущий `_` в имени поля НЕ бросает исключение** — pydantic трактует такое имя как
  приватный атрибут и молча не создаёт поле модели (`model_fields` его не содержит).
  Команда `catalog.plugins` такое имя не выдаёт: оно приходит из `model_fields`
  реального класса плагина (`extract_fields`), где поля с ведущим `_` нет. Ручной
  payload через `from_catalog` такое поле передать может (ревью итерации 1: `_secret`
  прошёл) — поле молча выпадает, `set_field_value` на нём отвечает `(True, None)`.
  Из имён защищённого namespace `model_*` реально бросают исключение только
  `model_dump`/`model_validate` (конфликт с методом `BaseModel`); прочие `model_*`
  собираются с `UserWarning`, без исключения.
- `validate()`/`RegistersManager.validate_field_value()` проверяет ТОЛЬКО
  `FieldMeta` (`access_level`, числовой диапазон `[min, max]`) — на РЕАЛЬНОМ
  `from_registry`-регистре тоже, это не регрессия копии (см. модульный докстринг
  `test_catalog_registers_editing_acceptance.py`, AC4). Полная проверка (типы,
  `Literal`-принадлежность через pydantic) происходит на `setattr`
  (`validate_assignment=True`) — одинаково на копии и оригинале (параметризованные
  `list`/`dict` — с Task 1b.2d-1, см. строку ниже).
- **2026-10-02, Task 1b.2d-1:** ограничение «параметризованные `list`/`dict` вырождаются
  в голый контейнер» СНЯТО — `FieldInfo.to_dict()` пишет `item` (для `list[X]`) и
  `key`/`value` (для `dict[K, V]`) вложенным описанием `{"type": тег, ...}`
  (`field_info.py::_describe_type`), `from_dict()` собирает тип обратно
  (`_build_type`); старый payload без этих ключей читается как голый контейнер.
  Копия шире оригинала на элементах вне закрытого набора тегов (тег `unsupported` — ключ
  не пишется): `Optional`/`Union`, ограничения через `Annotated` (например
  `list[Annotated[int, Field(ge=0)]]` с `[-1]`: оригинал отвергает, копия принимает),
  модели, `tuple` кроме трёх `int`. `Any` совпадает. В реальных регистрах таких полей
  сейчас 0 (обход каталога прогоном).
- **2026-10-02, Task 1b.2d-2:** ограничение «class-level python-валидаторы не доезжают»
  для двух регистров, которые их несли (`otel_export` — 4 `field_validator` + 1
  `model_validator`, унаследованные из `OtelExportConfig`; `line_filter` — 1
  `model_validator`), СНЯТО переносом правил в данные: `FieldMeta(rules=...)` (закрытый
  словарь `strip`/`pattern`/`value_pattern`/`choices_map`/`le_field`, ADR-DS-010) едет в
  копию через `FieldMeta.to_dict()/from_dict()` и исполняется на ней тем же кодом, что на
  оригинале. Контракт-тест `adapters/tests/test_1b2d_no_python_validators_contract.py`
  падает на любом новом `field_validator`/`model_validator` у register-класса каталога —
  новое правило обязано стать данными. `set_field_value` пишет через
  `SchemaMixin.apply_values` (всё или ничего: отказ ничего не оставляет в регистре, текст
  отказа без введённого значения) и уведомляет подписчиков и `send_callback`
  СОХРАНЁННЫМ (нормализованным) значением, а не введённым (`warn` → `WARNING`).
- **Финальный судья — бэкенд.** Копия существует только на GUI-стороне для
  немедленной обратной связи форме; фактическая запись регистра процесса идёт через
  `send_callback`/`register_update` и там же валидируется ещё раз (`cmd_set_config`,
  `validate_assignment` реального класса плагина, включая унаследованные из
  `Services` python-валидаторы). Совпадение копии и оригинала НЕ гарантировано на
  элементах вне закрытого набора тегов и на кастомных Python-валидаторах — см. пункты выше.

### Связанные решения

- ADR-RM-005 (N/A этапов 1–6, протокол `IRegistersManager`)
- Task 1b.2a (`FieldInfo.to_dict()`/`from_dict()` — dict-кодек через границу)
