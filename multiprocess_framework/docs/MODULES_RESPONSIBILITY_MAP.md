# Карта ответственности модулей — где что живёт

**Назначение:** зафиксировать за каждым из 24 модулей фреймворка **одну зону ответственности** и явно развести оси, которые легко перепутать. Цель — чтобы при переносе кода из `multiprocess_prototype/` во фреймворк не появлялось дублирования: для каждой задачи есть ровно один «правильный» модуль.

- Быстрая карта по слоям и API — [`MODULES_OVERVIEW.md`](MODULES_OVERVIEW.md).
- Статусы/LOC/тесты — [`../MODULES_STATUS.md`](../MODULES_STATUS.md).
- Детали одного модуля — `modules/<имя>/README.md`.

**Обновлено:** 2026-07-08 — первичная сверка с фактическим кодом (24 модуля; `sql_module` в `Services/sql`).

---

## 1. Правило одной ответственности

Каждый модуль **владеет** одной осью и **не лезет** в соседнюю. Колонка «НЕ владеет» — граница, которую нельзя нарушать при добавлении фич.

| Модуль | Владеет (единственная ответственность) | НЕ владеет (не тащить сюда) |
|---|---|---|
| `base_manager` | lifecycle менеджера + `ObservableMixin` (прокси лог/метрик/ошибок) | конкретной доменной логикой |
| `data_schema_module` | **чертёж** данных: `SchemaBase`, `FieldMeta`, `FieldRouting` | живыми экземплярами, runtime-значениями |
| `dispatch_module` | примитив `ключ → handler` (4 стратегии) | сетью, процессами, undo |
| `channel_routing_module` | общая база каналов/буферов (CRM) | конкретными каналами (лог/ошибки/метрики — у наследников) |
| `message_module` | value object IPC (`Message`, `MessageAdapter`) | доставкой (это `router_module`) |
| `router_module` | доставка сообщений **между процессами** | выбором handler внутри процесса (`dispatch`) |
| `logger_module` | логирование (scope-based routing) | ошибками (наследник `error_module`) и метриками (`statistics`) |
| `error_module` | ошибки с severity-routing | обычными логами |
| `statistics_module` | метрики/агрегация (counter/gauge/timing) | логами, ошибками |
| `shared_resources_module` | **межпроцессные** ресурсы: очереди, SHM, `EventManager`, `ConfigStore`, PSR | внутрипроцессным состоянием/подписками GUI |
| `config_module` | runtime-**конфигурация** (dot-notation, env-fallback, subscribe) | доменным состоянием, регистрами |
| `state_store_module` | **глобальное реактивное дерево** состояния (glob-подписки, дельты) | статической конфигурацией, доменными регистрами |
| `registers_module` | runtime **экземпляров регистров** + routing (fan-out полей) | чертежом (`data_schema`), глобальным деревом (`state_store`) |
| `command_module` | реестр `имя команды → handler` (тонкий фасад над dispatch) | откатом/undo (это `actions_module`) |
| `actions_module` | building-blocks undo/redo (`ActionBus` PATCH + `SnapshotHistory` SNAPSHOT) | IPC-командами без отката. **NB:** сейчас прод-undo в прототипе идёт через domain `CommandDispatcherOrchestrator`, `ActionBus` как прод-путь не задействован; модуль **сохраняется** как переиспользуемый building-block (решение владельца, 2026-07-08) — ADR-COMM-002 о его удалении **не исполняется** |
| `event_module` | **in-proc** typed pub/sub «фактов» (по `type(event)`) | межпроцессными событиями (`EventManager`), командами, состоянием |
| `worker_module` | потоки внутри процесса (LOOP/TASK, lifecycle) | процессами, DAG-пайплайнами |
| `chain_module` | DAG/Chain/Parallel **исполнение** пайплайна + worker-pool | сетевым IPC, потоками общего назначения |
| `process_module` | база дочернего процесса (собирает подсистемы) | оркестрацией нескольких процессов |
| `process_manager_module` | оркестратор системы (spawn/monitor/registry) | внутренней логикой конкретного процесса |
| `console_module` | терминальный I/O процесса (passive/active/God) | бизнес-командами (только транспорт stdin→CommandManager) |
| `service_module` | реестр **сервисов** с lifecycle (камеры, БД, auth) | реестром регистров/дисплеев/плагинов |
| `display_module` | реестр **SHM-каналов кадров** (blueprint + YAML) | созданием SHM (это SRM), vision-семантикой |
| `registers_module`↑ | *(см. выше)* | |
| `frontend_module` | PySide6-виджеты ↔ регистры (bridge) | бизнес-логикой backend-процессов |

> `sql_module` — **не во фреймворке**: живёт в `Services/sql` (Phase 4.1). Storage — прикладная ответственность.

---

## 2. Оси, которые путают — разбор с вердиктами

Ниже — пары/тройки модулей, которые звучат похоже. Для каждой: чем реально отличаются и как выбрать.

### Три оси «событий» ⚠️ два разных «EventBus»

Три независимых механизма, у двух похожие имена — **самый частый источник путаницы**.

| Что нужно | Модуль | Приметы |
|---|---|---|
| Внутрипроцессно оповестить о **факте** («что произошло») | `event_module.EventBus` | синхронно, диспетчеризация по `type(event)`, pure Python, leaf |
| **Межпроцессное** системное событие | `shared_resources_module.EventManager` | emit → локальные подписчики + роутер, pickle-safe |
| Реакция на **изменение значения** в состоянии | `state_store_module` (glob-подписки) / `registers_module` (observers) | дельты пути / fan-out поля |
| Выбрать **handler по ключу** входящего сообщения | `dispatch_module` | это не событие, а команда `ключ→handler` |

**Правило:** «что-то произошло, внутри процесса, без адресата» → `event_module`. «Событие должно уйти в другой процесс» → `EventManager` (SRM). «Значение поменялось» → `state_store`/`registers`.

### config vs state_store vs registers ⚠️ самая размытая граница

Все три «хранят данные и умеют subscribe». Разводим по **природе данных**:

| Природа данных | Модуль | Пример |
|---|---|---|
| **Настройки** (относительно статичны, env-fallback, dot-path) | `config_module` | `config.get("database.host")`, таймауты, пороги |
| **Живое глобальное состояние**, видимое всем процессам, с дельтами | `state_store_module` | `cameras.*.status`, runtime-телеметрия, GUI-подписки |
| **Экземпляры доменных регистров** с маршрутизацией полей в процессы | `registers_module` | регистр «камера №3» с `FieldRouting`, uplink значения в backend |

**Эвристика выбора:**
- Меняется редко, читается как параметр → **config**.
- Меняется часто, много подписчиков в разных процессах, нужны дельты → **state_store**.
- Это именованная доменная сущность приложения, поля которой роутятся в процессы → **register** (чертёж в `data_schema`, экземпляр в `registers_module`).

> `ConfigStore` (внутри SRM) — это **транспорт** синхронизации config между процессами, не отдельная ось: `config_module` использует его под капотом.

### command vs action vs dispatch — слоятся, но undo раздвоен ⚠️

Ось «ключ → handler» слоится корректно:

```
dispatch_module   примитив «ключ → handler» (4 стратегии)
   └─ command_module   тонкий фасад: «имя команды → handler» (IPC-команды, без отката)
   └─ actions_module   ортогонально: building-blocks «действие с undo/redo» (ActionBus PATCH / SnapshotHistory SNAPSHOT)
```

**Правило:** пришло IPC-сообщение-команда → `command_module`. Нужен свой матчинг ключей (паттерны/сценарии) → напрямую `dispatch_module`.

**⚠️ Раздвоение undo-движка (реальный дубль ответственности):** прод-undo в `multiprocess_prototype` идёт через domain `CommandDispatcherOrchestrator`, а не через `actions_module.ActionBus` (0 прод-`execute`). То есть **две реализации undo/redo** — framework-building-block (`actions_module`) и domain-движок (прототип). ADR-COMM-002 предлагал удалить `actions_module`, но по решению владельца (2026-07-08) модуль **сохраняется** как переиспользуемый building-block. Это единственная зона в §2 с **фактическим дублированием функции** — консолидация отложена (не удалять).

### Семейство реестров (`*Registry`) ⚠️ общий паттерн, разные сущности

В коде ~15 классов `*Registry`. Большинство — приватные утилиты разных доменов (`QueueRegistry`, `WorkerRegistry`, `ProcessRegistry`, `ChannelRegistry`, `SchemaRegistry`, `ShmRegistry`, `SelectorRegistry`…) и **не дублируют** друг друга.

Публичное «семейство реестров сущностей» с одинаковым паттерном (singleton + lifecycle):

| Реестр | Сущность | Модуль |
|---|---|---|
| `ServiceRegistry` | long-running сервисы (камеры, БД, auth) | `service_module` |
| `DisplayRegistry` | SHM-каналы кадров | `display_module` |
| `RegistersManager` (`RegistersContainer`) | экземпляры доменных регистров | `registers_module` |
| `PluginRegistry` | плагины (hot-reload) | `Plugins/` (application) |

**Вердикт:** дублирования функции нет (разные сущности), но общий базовый контракт `IRegistry` не выделен — кандидат на мелкий рефактор, если семейство продолжит расти. Имена `registers_module` ↔ `ProcessRegistersRegistry` близки — при чтении сверяться по домену.

### Routing ✅ слоятся корректно

`router_module` (между процессами) · `channel_routing_module` (общая база каналов) · `dispatch_module` (in-proc `ключ→handler`) · `registers_module.build_routing_map()` (маппинг полей регистра → каналы/процессы). Разные уровни, дублирования нет. Терминология — [`ROUTING_GLOSSARY.md`](ROUTING_GLOSSARY.md).

---

## 3. Чек-лист при переносе кода из `multiprocess_prototype/`

Перед тем как класть новый код во фреймворк, ответь:

1. **Это уже чья-то ось?** Сверься с таблицей §1 «Владеет». Если да — расширяй тот модуль, не создавай новый.
2. **События?** Реши по §2: in-proc факт (`event_module`) / cross-proc (`EventManager`) / изменение значения (`state_store`/`registers`).
3. **Хранение данных?** config / state_store / register — по «природе данных» из §2.
4. **Реестр сущностей?** Проверь семейство §2 — возможно, хватит существующего.
5. **Generic ли код?** Во фреймворк едет только доменно-нейтральное. Доменное (vision, конкретные сервисы) → `Services/` или `Plugins/` (правило слоёв импортов, ADR-120).

---

## 4. Открытые вопросы / кандидаты на рефактор

- **`IRegistry` базовый контракт** для `service_module` / `display_module` / `registers_module` — унифицировать singleton+lifecycle+persist (§2 «Семейство реестров»). Чистый net-new кандидат, ни с чем не пересекается.
- **Раздвоение undo-движка** (`actions_module.ActionBus` ↔ domain `CommandDispatcherOrchestrator`) — единственный фактический дубль ответственности (§2). Владелец решил **сохранить** `actions_module` (2026-07-08), консолидация отложена. ADR-COMM-002 (удаление) фактически **не исполняется** — при следующем ревью коммуникаций стоит обновить его статус на «отложено/superseded».
- **Именование двух EventBus** — `EventManager` (SRM) vs `event_module.EventBus`. Переименование в `SystemEventBus` **не свободно**: `EventManager` затронут консолидацией транспорта (ADR-COMM-001, план `transport-router-hub` — «EventManager dual-write» в списке обходов Router). Решать только в связке с этим планом, не отдельным рефактором.
- **Граница config ↔ state_store** — при переносе прототипа зафиксировать явные примеры «что где», чтобы эвристика §2 не размывалась.
