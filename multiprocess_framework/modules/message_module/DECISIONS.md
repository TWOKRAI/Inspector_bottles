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

## ADR-MSG-004 (was ADR-150): Поле `routers` — УДАЛЕНО (§11.2)

**Статус:** отменено (2026-06-05, comm-system P0 §11.2)  
**Дата:** 2026-04-09  
**Контекст:** `routers` field роль неясна.  
**Исходное решение:**
- `targets` — имена процессов (межпроцессная адресация)
- `channel` — имя канала в RouterManager получателя
- `routers` — список RouterManager'ов внутри одного процесса

**Отмена:** Поле `routers` оказалось мёртвым — 0 prod-читателей (только писалось
validator'ом и исключалось из LOG `to_dict()`). Удалено из `Message`,
`LogMessageSchema`, `CommandMessageSchema`, `MESSAGE_TYPE_DEFAULTS` и
`MESSAGE_TYPE_EXCLUDE_FIELDS` (последний оставлен пустым как generic
extension-point). Адресация полностью покрывается `targets` (процесс/воркер) +
`channel` (канал RouterManager). Один RouterManager на процесс — инвариант
архитектуры, отдельное поле не нужно.

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

**Примечание:** `Message` — единственный `SchemaBase`-наследник без `FieldRouting`. Это осознанное решение: `Message` — value object для IPC-транспорта, а не регистр с маршрутизацией полей. Маршрутизация сообщений определяется полями `targets` / `channel` напрямую, без `FieldRouting`.

---

## ADR-MSG-007: Иерархическая адресация — dotted-адрес внутри `targets` (`addressing/`)

**Статус:** принято  
**Дата:** 2026-05-31  
**Контекст:** План `transport-router-hub` (P0.2) и глобальный [ADR-COMM-004](../../DECISIONS.md) вводят иерархический адрес получателя `process → worker → глубже` (память `project-hierarchical-addressing`). Нужно адресовать уровень «воркер» (долг #2 `assigned_worker`), не вводя новое поле и не ломая существующий `targets`.  
**Решение:** Каждый элемент `Message.targets` — **dotted-адрес** `process[.worker[.…]]`. Пакет `message_module/addressing/` (чистые JSON-safe функции): `split_address`/`process_of`/`worker_of`/`subpath_of`/`depth`/`join_address`/`validate_address`/`normalize_targets`; исключение `AddressValidationError(MessageValidationError)`. Prefix-правило (процесс первым, воркер без процесса → ошибка), backward-compat плоского `"proc"` == `["proc"]`. `normalize_targets(target=, targets=)` сводит сосуществующие скаляр `target` (data-plane) и список `targets` к единому `list[str]` (recon #2).  
**Причина:** Иерархия живёт **внутри** существующего `targets: list[str]` — мультикаст сохранён, новое поле не вводится, JSON-safe (Dict-at-Boundary, правило #1). Транспортная семантика (доставка по `address[0]`, intra-process резолв воркера) — в `router_module`/P1–P2, здесь только парсинг/валидация.  
**Последствия:** `targets` обретает иерархию без миграции данных (плоские имена продолжают работать). `AddressValidationError` ловится существующими обработчиками `MessageValidationError`.  
**Refs:** [ADR-COMM-004](../../DECISIONS.md), [ADR-COMM-001](../../DECISIONS.md), [plans/_archive/2026-05-31_transport-router-hub/plan.md](../../../plans/_archive/2026-05-31_transport-router-hub/plan.md)

---

## ADR-MSG-008: Реестр контрактов сообщений (`contracts/`) — Ф4.2

**Статус:** принято (частично — шаг 1: реестр+middleware; проводка в роутер отдельно)
**Дата:** 2026-07-08
**Контекст:** Ф4 «контракты вместо конвенций». Сейчас `command`/`data_type` → обработчик по конвенции, без реестра схем: опечатка в имени команды или неверное поле payload молча проходит (класс бага 1.6 — `set_register` слал `plugin_name` вместо `register`, обработчик тихо выходил). Нужен источник истины «форма сообщения X» + диагностика на границе.
**Решение:** Подпакет `message_module/contracts/`: `MessageContractRegistry` (`register(key, schema, *, plane, override)` / `get` / `validate`) связывает ключ маршрутизации (`command`|`data_type`) с Pydantic-схемой; `MessageContract` (key/schema/plane), `ContractCheck` (раздельные списки missing/unexpected/errors + `diff_summary()`). Чистая фабрica `make_contract_check_middleware(registry, *, strict, on_violation)` возвращает `fn(dict)->dict|None`, совместимую с `add_receive_middleware`: **warn** (дефолт) — нарушение → `on_violation(check)`, сообщение проходит; **strict** — дроп. Ключ извлекается `command → data_type → type`. Пустой реестр / неизвестный ключ → `validate` возвращает `None` (ноль оверхеда, частичное покрытие допустимо).
**Причина:** Реестр и middleware — чистые, Qt-free, не знают про `RouterManager` (проводка = отдельный шаг композиции, чтобы риск изменения hot receive-пути был изолирован). Diff полей раздельными списками → читаемый WARNING вместо сырого Pydantic-текста. `plane="data"` помечен, но здесь НЕ валидируется — инвариант для Ф7 (data-plane валидирует только payload-валидатор 4.3).
**Последствия:** Основа для warn-middleware на receive (шаг 2, флаг `FW_CONTRACTS_STRICT`), fencing-token drop-middleware (тот же pipeline) и `introspect.capabilities` v1 (`params_schema` из реестра). 26 контракт-тестов; полный `message_module` 181 passed.
**Refs:** [plans/2026-07-06_constructor-master/f4.2-fencing-contracts.md](../../../plans/2026-07-06_constructor-master/f4.2-fencing-contracts.md), [ADR-PMM-010](../process_manager_module/DECISIONS.md)

**Обновление (шаг 2, 2026-07-08):** реестр проведён в receive-pipeline процесса —
`BuiltinCommands._register_message_guards` вешает `make_contract_check_middleware`
на `RouterManager.add_receive_middleware` (per-process пустой реестр на
`services.contract_registry`, наполняется позже декларативно). Дефолт **warn**
(`FW_CONTRACTS_STRICT` unset), нарушение → счётчик `contract_violations` +
WARNING с diff. Служебные `_`-префиксные transport-ключи (`_address`,
`_receive_info`, `_fence` fencing-Ф4.2) исключены из `unexpected` в `_check`.
Наполнение реестра прод-контрактами и `introspect.capabilities` — отдельный шаг.

**Обновление (шаг 6, 2026-07-09):** реестр наполнен контрактами параметров built-in
команд (`process_module/commands/command_contracts.py`: `wire.configure`/
`wire.deconfigure`/`routing.probe`), регистрируются per-process в
`_register_message_guards`. `introspect.capabilities` отдаёт `params_schema`
(`[{name,type,required}]`, `Optional[X]`→`X`) из реестра; `dump_capabilities`
включает его, `DUMP_VERSION=1`, CAPABILITIES регенерирован (drift-gate зелёный).
**v1 — документирующие схемы** (`extra="allow"`, поля опциональны): warn-mw валидирует
конверт, а параметры едут вложенно в `data`, поэтому ложных предупреждений на реальном
трафике нет. Строгая валидация вложенного `data` — следующий инкремент. **Ф4.2 закрыта.**

**Обновление (шаг 7 / NEW-3, 2026-07-11):** строгая вложенная валидация `data` —
следующий инкремент из шага 6 реализован. Все схемы `BUILTIN_COMMAND_CONTRACTS`
переведены `extra="allow"` → `extra="forbid"` (29 built-in команд вместо прежних 3:
добавлены `worker.*`, `introspect.*`, `config.reload`, `logger.sink.*`, `log.tail.*`,
`observability.tail.*`, `health.*`, `router.relay`, `routing.refresh`) — опечатка в
имени параметра (`buffer_slotss` вместо `buffer_slots`) теперь даёт `unexpected` в
diff вместо тихого прохода, для ЛЮБОЙ built-in команды, не только трёх исходных.
Required-ность полей НЕ менялась (контракт документирует форму параметров, рантайм-
проверку обязательности внутри хендлера не дублирует) — только барьер «неизвестный
ключ».
**Находка при раскатке:** live-прогон `test_dump_matches_committed` вскрыл, что
`RouterManager.request()` зеркалит `correlation_id` в `data` ЛЮБОГО request-response
вызова (PM-обёртка `process.command`, симметрично `_extract_correlation_id`) — без
исключения strict-раскатка дропала бы КАЖДУЮ built-in команду, отправленную через
request-response (сообщение `contract WARNING: ... — лишние: correlation_id` на
каждом процессе при загрузке). Фикс — `_TRANSPORT_KEYS` в `MessageContractRegistry._check`
(`registry.py`): `correlation_id` исключён из `unexpected` наравне с `_`-префиксными
транспортными ключами. После фикса — 0 contract-violations на чистом headless-буте
(acceptance-инвариант raskatki).
**Живых нарушителей контракта (лишние поля СВЕРХ correlation_id) не найдено** —
grep-аудит вызовов built-in команд (frontend bridges, backend_ctl driver, PM-хендлеры,
router.relay/routing.refresh) на 2026-07-11 показал точное совпадение полей с новыми
схемами; ни одна built-in команда не осталась в `allow` с TODO.
**Тесты:** 20 новых (`process_module/tests/test_command_contracts.py` — 15,
`message_module/tests/test_contract_registry.py` — 2 регресса на `correlation_id`,
`backend_ctl/tests/test_capabilities.py` live drift-gate зелёный после regen); полный
`message_module`+`process_module`+`router_module` набор (941) и `run_framework_tests.py`
(3905) — 0 красных.
**Refs:** [plans/current-path/plan.md](../../../plans/current-path/plan.md) (NEW-3),
[plans/current-path/review-2026-07-11.md](../../../plans/current-path/review-2026-07-11.md) (B3)

---

## ADR-MSG-009: Fencing-token — штамп конверта + drop билета устаревшего инстанса (`fencing/`) — Ф4.2

**Статус:** принято
**Дата:** 2026-07-08
**Контекст:** Требование владельца (2026-07-08): после замены инстанса (switch/restart с пересозданием очередей) старый процесс НЕ должен вкинуть сообщение в новую топологию. `incarnation`/`epoch` есть (ADR-PMM-010), но применялись лишь к CLEANUP очередей и к самому `routing.refresh` — оставалось окно гонки.
**Решение:** Подпакет `message_module/fencing/` — две чистые фабрики (Qt-free, не знают про роутер): `make_fence_stamp_middleware(sender, get_fence)` (send-mw: штампует `_fence={sender,inc,epoch}` на control-plane, когда свой incarnation известен) и `make_fence_filter_middleware(get_expected_incarnation, on_drop)` (receive-mw: дропает `return None`, если `_fence.inc < PSR[sender].routing_incarnation` — билет от СТАРОГО инстанса, заменённого новым). `_fence` — nested transport-ключ (не поле `Message`; реестр контрактов его игнорирует). Инварианты: **только control-plane** (data-plane/кадры не трогаются — горячий путь ADR-PMM-010); **fail-open** (нет incarnation → не штампуем/не дропаем); **обратная совместимость** (без `_fence` — прозрачно). Проводка — `BuiltinCommands._register_message_guards` за флагом `FW_FENCE` (дефолт ON); провайдеры читают PSR (`routing_incarnation`). Полный разбор + урок live — [ADR-PMM-014](../process_manager_module/DECISIONS.md).
**Причина / ключевое отличие:** дроп по **per-sender incarnation**, НЕ по глобальному epoch. Live-e2e показал: epoch-критерий ложно дропает легитимный state/telemetry ТЕКУЩИХ процессов в переходном окне после switch (пока они не применили refresh, их epoch отстаёт от получателя). Incarnation же меняется ТОЛЬКО при пересоздании очередей процесса (`_bump_incarnation`) → устаревший инстанс отличим точно, текущий (даже отставший по epoch) не трогается. Урок как в Ф3.7: unit «сообщение отброшено» зелёный, а истинную семантику вскрыл только живой прогон.
**Последствия:** Жёсткая гарантия «старый инстанс не вкидывает в новую топологию» вместо окна гонки. Счётчик `fence_dropped` в router-stats. Live-доказательство — `backend_ctl/tests/test_fencing_live.py` (restart-no-reuse → PM дропает стейл старого инстанса, RED/GREEN по `FW_FENCE`); `routing_epoch_live` зелёный (нет ложных дропов). restart-reuse корректно НЕ фенсит (та же очередь). Data-plane — Ф7 G.4 под флагом; epoch остаётся в штампе для диагностики/Ф4.9.
**Refs:** [ADR-PMM-010](../process_manager_module/DECISIONS.md), [ADR-PMM-014](../process_manager_module/DECISIONS.md), [ADR-MSG-008](#adr-msg-008-реестр-контрактов-сообщений-contracts--ф42), [plans/2026-07-06_constructor-master/f4.2-fencing-contracts.md](../../../plans/2026-07-06_constructor-master/f4.2-fencing-contracts.md)
