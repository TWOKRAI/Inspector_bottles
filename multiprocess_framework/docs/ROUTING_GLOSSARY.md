# Глоссарий маршрутизации

Краткая карта терминов, чтобы не путать **логический канал Router** и **цель доставки сообщения от GUI** (`register_update`).

---

## Таблица понятий

| Концепция | Где живёт | Назначение |
|-----------|-----------|------------|
| `Message.targets` | `message_module` | Логические получатели в dict-сообщении |
| `connection_map` | `RegistersManager` / `FrontendRegistersBridge` | `register_name` → имя процесса для доставки `register_update` (опциональный override; см. ADR в `DECISIONS.md`) |
| `FieldRouting` / `routing` в `FieldMeta` | `data_schema_module`, поля в **схемах приложения** (классы регистров) | В т.ч. **канал Router** (`channel`) для `RouterSchemaAdapter` / очередей; опционально `process_targets` на поле для GUI-доставки |
| `RegisterDispatchMeta` | `data_schema_module`, атрибут класса регистра `register_dispatch` | Список имён процессов для `register_update` по **всему** регистру (fan-out — несколько процессов подряд) |
| Имя канала Router (`msg["channel"]`, `QueueChannel`) | `router_module` | Физическая привязка к очереди из `shared_resources_module` |

---

## Три оси адресации: процесс, канал, источник

1. **Имя процесса** — аргумент `target` в `send_message(target, msg)` (например `renderer`, `processor`). Его использует `FrontendRegistersBridge` после нормализации префикса `control_` в callback `RegistersManager`.
2. **Строка канала Router** — ключ в реестре очередей (часто вида `control_*`), по которому backend подписывает обработчики. Задаётся в `FieldRouting(channel=...)`.
3. **Имя источника наблюдаемости** — поле `module` записи: иерархическое точечное имя
   (`multiprocess_framework.modules.router_module`), по которому решается **порог и приёмники
   записи**. Живёт в `observability.loggers`, действует по самому длинному совпавшему префиксу.

Первые две строки **не обязаны совпадать**: например, поля регистра `draw` маршрутизируются в канал `control_draw`, а сообщения `register_update` с GUI могут уходить в процесс `renderer`, если так задано в `register_dispatch` или `connection_map`.

**Третья ось не пересекается с первыми двумя вовсе,** и путать её с ними — типовая ошибка:
транспорт отвечает на «кому доставить сообщение», источник — на «чья это запись и куда её
писать». Транспорт отделён от плоскости наблюдаемости whitelist'ом (`RouterManager` унаследовал
`set_sink_enabled` от общей базы, но операторской командой не адресуем — иначе IPC-канал снимался
бы одной командой пульта).

Отдельная ловушка имени: **наш `scope`** (`SYSTEM`/`BUSINESS`/`PERFORMANCE`/`DEBUG`) — это
*группа* логирования, ключ маршрутизации. **`InstrumentationScope` у OTel** — идентификация
*источника*, и эту роль у нас играет `module`. Понятия разные, имя похожее; дисциплина
зафиксирована в ADR-LOG-005. Подробности — [`observability/CONNECTORS.md`](./observability/CONNECTORS.md).

---

## Fan-out (`process_targets` / `RegisterDispatchMeta.process_targets`)

Если указано **несколько** процессов:

- Вызовы `send_callback` (и далее `send_message`) выполняются **по порядку** в кортеже.
- Приёмники должны быть **идемпотентны** там, где одно и то же обновление может прийти нескольким процессам.
- При исключении в callback текущая реализация **глотает** ошибку (как и раньше для одного target); частичный сбой не откатывает уже отправленные цели.

---

## Схемы регистров приложения и `shared_resources_module`

| Пакет / слой | Роль |
|--------------|------|
| **Регистры приложения** | Статические Pydantic-схемы (`SchemaBase`): поля, `FieldMeta`, `FieldRouting`, `register_dispatch`. В прототипе — `multiprocess_prototype/registers/schemas` (не часть фреймворка). |
| **shared_resources_module** | Runtime IPC: очереди, события, shared memory — инфраструктура, на которой строится Router. |

Подробнее об обзоре фреймворка: [MODULES_OVERVIEW.md](./MODULES_OVERVIEW.md)
(прежний `FRAMEWORK_OVERVIEW.md` лежит в [`archive/`](./archive/FRAMEWORK_OVERVIEW.md) и живым
источником не является).
