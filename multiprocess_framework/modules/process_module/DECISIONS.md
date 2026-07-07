# process_module — Архитектурные решения

> Ссылки: [`../../DECISIONS.md`](../../DECISIONS.md) (ADR-008 Dict at Boundary)

## ADR-PM-001 (was ADR-163): Dual Communication API (send_message vs send)

**Статус:** принято  
**Дата:** 2026-04-09  
**Контекст:** `ProcessModule` предоставляет два стиля IPC: `send_message(target, message)` → `bool` (наследие простого API) и `send(message)` → `Dict` с полями статуса (расширенный путь через `ProcessCommunication`). Потребители и тесты используют оба контракта.  
**Решение:** Сохранить оба. Не унифицировать в один метод — разные сигнатуры возврата отражают разный уровень детализации (успех/неуспех vs структурированный ответ).  
**Последствия:** Дублирование точек входа документируется; новый код может предпочитать `send`/`receive` при необходимости метаданных.

## ADR-PM-002 (was ADR-164): ISharedResources Protocol для DI

**Статус:** принято  
**Дата:** 2026-04-09  
**Контекст:** `ProcessModule` должен работать с очередями, реестром процессов и памятью без жёсткой зависимости от конкретного класса `SharedResourcesManager`.  
**Решение:** Конструктор принимает `Optional[ISharedResources]`; доступ к полям через protocol и `getattr` там, где контракт расширяемый.  
**Последствия:** Нет циклического импорта `process_module` → `shared_resources_module` на уровне типов ядра; моки в тестах упрощаются.

## ADR-PM-003 (was ADR-165): Удаление backward-compat shim `state/process_state_registry.py`

**Статус:** принято  
**Дата:** 2026-04-09  
**Контекст:** В `process_module/state/` лежал тонкий реэкспорт `ProcessStateRegistry` из `shared_resources_module`. Grep не выявил внешних импортёров этого пути; каноничный реестр — в SRM.  
**Решение:** Удалить файл; `ProcessStateRegistry` импортировать из `shared_resources_module`. Сохранить `process_data.py` (используется, в т.ч. TYPE_CHECKING в других модулях).  
**Последствия:** Меньше дублирования путей импорта; при старых импортах из `process_module.state` — миграция на SRM.

## ADR-PM-004 (was ADR-166): Декомпозиция `ProcessManagers.initialize()` на pipeline

**Статус:** принято  
**Дата:** 2026-04-09  
**Контекст:** Монолитный `initialize()` (~200+ LOC) смешивал создание семи менеджеров, регистрацию в ObservableMixin, адаптеры и связь с `event_manager`.  
**Решение:** Вынести шаги в `_create_*_manager`, `_register_all_managers`, `_attach_all_adapters`, `_connect_event_manager`; публичный `initialize()` остаётся единой точкой входа. Lazy imports остаются внутри соответствующих методов.  
**Последствия:** Читаемость и изоляция изменений по одному менеджеру; поведение и порядок инициализации неизменны.

## ADR-PM-005 (was ADR-166a): Реализация `_init_configuration` / `_init_queues` в ProcessLifecycle + делегаты на ProcessModule

**Статус:** принято  
**Дата:** 2026-04-09  
**Контекст:** Логика инициализации конфигурации и очередей вызывается только из `ProcessLifecycle.initialize()`. Unit-тесты подменяют `process._init_configuration` / `process._init_queues` на `Mock`.  
**Решение:** Тело методов — в `ProcessLifecycle._init_configuration` / `_init_queues`; на `ProcessModule` — однострочные делегаты `self._lifecycle._init_*()`. `ProcessLifecycle.initialize()` вызывает `self.process._init_configuration()` и `self.process._init_queues()`, чтобы моки и хуки на экземпляре процесса продолжали работать.  
**Последствия:** Нет дублирования логики; точка расширения для тестов остаётся на `ProcessModule`.

## ADR-PM-006 (was ADR-167): `importlib.import_module` для динамической загрузки воркеров

**Статус:** принято  
**Дата:** 2026-04-09  
**Контекст:** `_create_workers_from_config` использовал `__import__(module_path, fromlist=[...])` для загрузки класса воркера по строке пути.  
**Решение:** Заменить на `importlib.import_module(module_path)` и `getattr` для класса — идиоматичный API, проще сопровождать.  
**Последствия:** Эквивалентная семантика для обычных модулей; поведение для edge-case имён пакетов предсказуемее для читателя кода.

---

## ADR-PM-007: Plugin composition через IProcessServices Protocol

**Статус:** принято  
**Дата:** 2026-05-08  
**Контекст:** `GenericProcess` наследовал `ProcessModule` для добавления plugin lifecycle. `PluginContext` получал весь `ProcessModule` напрямую. Контракт между plugin-системой и процессом был неявным (duck typing): плагины зависели от конкретного класса, что делало изолированное тестирование невозможным без запуска полного процесса.  
**Решение:**
- `IProcessServices` Protocol — явный контракт (structural subtyping, zero runtime cost) между plugin-системой и `ProcessModule`: только то, что плагинам действительно нужно
- `PluginOrchestrator` — composition class, управляет plugin lifecycle (load → configure → start → shutdown) через `IProcessServices`
- `ProcessModule` нативно поддерживает плагины: при наличии `config["plugins"]` создаёт `PluginOrchestrator` внутри себя
- `PluginContext` принимает `IProcessServices` вместо `ProcessModule`
- `MockProcessServices` — лёгкий мок для изолированного тестирования плагинов без запуска процесса

**Отклонённые альтернативы:**

A. **Оставить наследование (GenericProcess → ProcessModule)** — плагины через override методов
- Плюсы: минимальные изменения
- Минусы: неявный контракт, невозможно тестировать плагины изолированно, наследование как механизм расширения поведения — анти-паттерн

B. **Отдельный PluginProcess рядом с ProcessModule** — новый класс параллельно
- Плюсы: нет изменений в ProcessModule
- Минусы: два универсальных класса процессов вместо одного, дублирование lifecycle-кода

**Последствия:**
- `GenericProcess` deprecated — тонкий shim (404 → 155 LOC) для backward-compat, будет удалён
- Плагины тестируются без `ProcessModule` через `MockProcessServices` (206 тестов — все green)
- Новый composition pattern: `heartbeat`, `commands`, `orchestrator` — все через `IProcessServices`
- Присоединение будущих composition class к `ProcessModule` следует тому же паттерну

---

## ADR-PM-008: ProcessModule как единственный универсальный класс процесса

**Статус:** принято  
**Дата:** 2026-05-08  
**Контекст:** На момент рефакторинга 9 классов наследовали `ProcessModule` (`CameraProcess`, `GuiProcess`, `GenericProcess` и др.). Каждый добавлял поведение через наследование, что приводило к размытию ответственностей и усложнению тестирования. Архитектурная цель — один универсальный класс процесса, поведение которого определяется конфигурацией, а не иерархией классов.  
**Решение:** `ProcessModule` — единственный класс процесса в фреймворке. Поведение определяется конфигурацией (`plugins`, `workers`) и composition classes, не наследованием. Единственный легитимный наследник — `ProcessManagerProcess` (оркестратор со специальным «god mode» доступом к системным ресурсам).  

**Отклонённые альтернативы:**

A. **Специализированные подклассы** (CameraProcess, GuiProcess, etc.)
- Плюсы: явная типизация, понятное именование
- Минусы: размножение классов при добавлении новых сценариев, жёсткая иерархия не позволяет комбинировать поведения

B. **Mixin-наследование** (ProcessModule + CameraMixin + PluginMixin)
- Плюсы: гибкость комбинирования
- Минусы: MRO-проблемы, неочевидный порядок инициализации, сложность тестирования

**Последствия:**
- Миграция прикладных процессов (`CameraProcess` → `ProcessModule` + `CameraServicePlugin`) — future work
- `GenericProcess` → deprecated shim → будет удалён после миграции прикладного кода
- Data pipeline (`DataReceiver`, `PipelineExecutor`), пока живущий в `GenericProcess`, станет `DataPipelinePlugin` — future work
- Прикладной код (`multiprocess_prototype/`) не обязан следовать этому правилу — запрет касается только фреймворка

---

## ADR-PM-009: Return-based composition (ManagersBundle)

**Статус:** принято  
**Дата:** 2026-05-09

**Контекст:** Composition-объекты (`ProcessManagers`, `ProcessLifecycle`) напрямую мутировали атрибуты `ProcessModule` (`self.process.worker_manager = ...`). Это нарушало SRP — composition-объект знал внутреннее устройство хоста и осуществлял побочные эффекты, что усложняло тестирование и делало граница ответственности размытой.

**Решение:**
1. `ProcessManagers.create_all()` возвращает `ManagersBundle` dataclass вместо записи в `self.process.*`
2. `ProcessLifecycle.init_configuration()` / `init_queues()` возвращают `tuple` вместо записи в атрибуты
3. `ProcessModule.initialize()` стал оркестратором — сам вызывает шаги и присваивает атрибуты через `_apply_managers_bundle()`
4. `ProcessLifecycle.initialize()` удалён — оркестрация переехала в `ProcessModule`, делегаты остались
5. `IProcessCommunication` стал Protocol (structural typing) вместо ABC

**Принцип:** «Read — don't write» — composition-объекты ЧИТАЮТ из хоста (через properties), но НЕ ПИШУТ в его атрибуты. Запись осуществляется исключительно хостом через return-values.

**Последствия:**
- Добавление нового менеджера: одно поле в `ManagersBundle` + одна строка в `_apply_managers_bundle()` (было: изменения в 3+ файлах)
- Тесты: имена методов `_init_configuration()` / `_init_queues()` сохранены на `ProcessModule` → моки продолжают работать
- `ProcessManagerProcess.initialize()` → `super().initialize()` chain сохранён
- Composition class теперь предсказуемо работают: input = конфиг, output = структурированные данные, побочные эффекты = отсутствуют

## ADR-PM-010: health-примитив наблюдаемости отказов (`ctx.health`)

**Статус:** принято
**Дата:** 2026-07-07
**Refs:** plans/2026-07-06_constructor-master/plan.md (Ф2 Task 2.1)

**Контекст:** Плагины проглатывали ошибки (`try/except: pass`, breaker без счётчика) — отказ железа/соседа был невидим в state-дереве и через driver. Ф2 вводит примитив наблюдаемости, на который волны C (2.4/2.5, ~30 сайтов) и breaker (2.2) будут опираться, поэтому контракт путей важнее сиюминутной реализации.

**Решение:**
1. **Единый на процесс `HealthState`** (аккумулятор: `errors`-счётчик, `last_error`, `status`, `degraded_reason`) живёт на объекте процесса как приватный `_health_state` — тем же приёмом, что `_state_proxy`. И `ctx.health` (PluginContext), и `ProcessHeartbeat` достают ОДИН инстанс через `services`.
2. **`ctx.health` = `HealthReporter`** — фасад, который плагин видит через PluginContext (ADR-120): `report_error(exc, context, throttle)` / `set_status` / `degraded`. Плагин не знает о `HealthState`/публикации.
3. **Схема путей — контракт** (`health/schema.py`): `processes.<name>.health.{status,errors,last_error,degraded_reason,updated_at}`. Стережёт контракт-тест — менять дословно дорого (30 сайтов волн C).
4. **Публикация — через существующий heartbeat self-publish** (тот же канал, что телеметрия fps/latency), НЕ новый IPC-канал. Rate-limit двухуровневый: state — по такту heartbeat (публикуем только `take_dirty`), лог — окно `throttle` на пару (тип, context). Счётчик `errors` инкрементится ВСЕГДА (честность для breaker 2.2).
5. **Откат в лог-only** (`INSPECTOR_HEALTH_LOG_ONLY`): report_error/set_status только логируют, state-дерево не трогают — путь отката заложен в дизайн по требованию плана.
6. **Диагностический хук** `health.report` / `health.status` в BuiltinCommands — детерминированная проверка канала наблюдаемости через driver (acceptance), инструмент отладки для агентов.

**Отклонения от плана:** добавлен диагностический `health.report`/`health.status` (в наброске не был) — нужен как детерминированный live-триггер acceptance «ошибка видна через driver» без ожидания реального отказа железа; регенерирован `docs/contracts/CAPABILITIES.yaml` (новые команды во всех процессах).

**Последствия:**
- Волны C 2.4/2.5 — one-liner `ctx.health.report_error(...)` на сайт; breaker 2.2 инкрементит от того же счётчика.
- Здоровье процесса видно в state-дереве и через `backend_ctl` без единого клика в GUI.
- Reversible: yes (флаг лог-only / не звать report_error). Risk: low — аддитивно, прод-путь не меняется, health не критичен для работы процесса (все ошибки публикации гасятся).

## ADR-PM-011: честный circuit breaker поверх health (подряд-ошибки → degraded)

**Статус:** принято
**Дата:** 2026-07-07
**Refs:** plans/2026-07-06_constructor-master/plan.md (Ф2 Task 2.2), ADR-PM-010

**Контекст:** Существовавшие breaker-механики не видели ошибок, проглоченных плагинами (`try/except` + report-less), — процесс мог бесконечно крутить горячий цикл отказов, оставаясь «ok» в state-дереве. Ф2.1 дал честный счётчик (`errors` инкрементится на КАЖДЫЙ `report_error`) — breaker обязан кормиться от него же.

**Решение:**
1. **`CircuitBreaker`** (`health/breaker.py`): состояния `closed`/`open`/`half_open`, подряд-счётчик отказов, ОТДЕЛЬНЫЙ от кумулятивного `errors` (тот монотонный). `record_failure()` → open по `fail_threshold`; `record_success()` → сброс/закрытие; `poll()` → пассивное восстановление по тишине (`cooldown_sec`): open → half_open → closed. Два пути восстановления осознанно: явный успех — для loop-раннеров, тишина — для сайтов, умеющих только `report_error`.
2. **Интеграция в `HealthState`**: каждый `report_error` кормит breaker; переход в open → `set_status(degraded, "breaker open: …")`. Деградацию снимает ТОЛЬКО breaker-owned восстановление (`_breaker_owns_degraded`) — чужой явный `degraded`/`failed` не затирается.
3. **Контракт-поле `health.breaker`** (`closed|open|half_open`) — аддитивно, В КОНЦЕ `HEALTH_FIELDS` (порядок прежних пяти неизменен, дампы стабильны); heartbeat зовёт `poll()` на такте перед публикацией — пассивное восстановление попадает в снапшот.
4. **produce()-breaker в `SourceProducer`**: подряд-фейлы `produce()` кормят тот же счётчик; при открытом breaker источник спит `breaker_backoff_sec` вместо горячего цикла ошибок.
5. **Пороги** — env `INSPECTOR_HEALTH_BREAKER_THRESHOLD` (дефолт 5) / `INSPECTOR_HEALTH_BREAKER_COOLDOWN` (дефолт 30с); clock инъектируется (детерминизм тестов).

**Acceptance (live, harness):** 5 подряд `health.report` → в state-дереве `health.breaker=open` + `health.status=degraded` + `degraded_reason` с «breaker» (`test_breaker_opens_and_degrades_after_n_consecutive_errors`).

**Последствия:**
- Волны C (2.4/2.5): сайтам достаточно `report_error` — breaker и деградация приезжают бесплатно.
- Уроки инцидента: два инстанса агента в одном дереве (стойло+реанимация) — примитив и интеграцию писали параллельно; выжило благодаря «коммить каждый шаг». Правило: перед реанимацией агента проверять, не ожил ли оригинал.
- Reversible: yes — лог-only переключатель Ф2.1 гасит и breaker-эффекты (state не трогается). Risk: low — аддитивное поле контракта, дефолты консервативны.
