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

## ADR-PM-012: payload-валидатор PluginRunner по Port-декларациям + оживление validate_chain

**Статус:** принято
**Дата:** 2026-07-11
**Refs:** plans/2026-07-06_constructor-master/plan.md (Ф4 Task 4.3), ADR-PM-006/007 (Port/GStreamer-модель)

**Контекст:** `Port`/`are_ports_compatible` (`plugins/port.py`) описывали контракт входов/выходов плагина статически (декларация в `inputs`/`outputs`), но НИЧЕГО не сверяло фактические `items` на границе плагина с этой декларацией в рантайме — рассинхрон обнаруживался только по косвенным симптомам (KeyError глубже в цепочке). Отдельно `validate_chain()` (детальная диагностика внутрипроцессной линейной цепочки) висел 0 прод-вызовов (C-4, ревью-находка) — реэкспортировался в `plugins/__init__.py`, но никогда не звался; межпроцессные Wire уже проверялись через `are_ports_compatible` в `SystemBlueprint.check()`, а внутрипроцессная цепочка — только однопарным `_is_covered_by_auto_wiring` (bool, без детального сообщения). Инвариант Ф4.2 зафиксировал: «после трека G (hot-path) data-plane валидируется только 4.3» — это единственная задача, которой разрешено трогать data-plane границу плагина.

**Решение:**
1. **`validate_items_against_ports(plugin_name, direction, ports, items)`** (`plugins/port.py`) — новая dev-only функция: для каждого НЕ-optional порта проверяет присутствие его поля (`port.name`) в каждом item. Пустой `items` — не ошибка (легитимный «ничего не нашли»). НЕ проверяет dtype/shape в рантайме — это осталось статической декларацией контракта, а не runtime-типизацией данных (расширение — вне объёма 4.3). Несоответствие → `PortValidationError(ValueError)` с именем плагина/direction/порта/индекса item.
2. **`PluginRunner`** (`generic/plugin_runner.py`) — единственная точка вызова `plugin.process()`/`produce()` в data-plane (см. модульный docstring раннера) — получил флаг `validate_ports` (constructor kwarg, default `None` → читает `os.environ["FW_PORT_VALIDATE"]` один раз при инициализации, не на каждый вызов). `call_process`: input-check ДО `plugin.process()`, output-check ПОСЛЕ — только если `plugin.enabled` (bypass не проверяется — прошедшие насквозь items принадлежат upstream-контракту, не этому плагину). `call_produce`: только output-check (у источника нет входа). Ошибка валидатора пробрасывается как и исключение самого плагина — НЕ ловится/не глушится раннером (та же error-policy, что и раньше).
3. **OFF по умолчанию — ноль оверхеда в prod:** флаг читается ОДИН раз в `__init__`, на hot path (`call_process`/`call_produce`) — единственная проверка `if self._validate_ports:` (bool-attribute lookup), при `False` код валидатора не выполняется вообще. Прод-путь (`FW_PORT_VALIDATE` не установлен) бит-в-бит идентичен коду до 4.3 — подтверждено характеризационным прогоном `phone_sketch`/`hikvision_letter_robot` (см. п.5) и юнит-тестами `test_port_validate_off_by_default_*`.
4. **`validate_chain` оживлён в `SystemBlueprint.check()`** (`generic/blueprint.py`) — единственная точка сборки внутрипроцессной линейной цепочки плагинов (тот же метод уже валидирует межпроцессные Wire). Для каждого процесса строится `(plugin_name, inputs, outputs)` по позиции; **inputs, уже покрытые explicit Wire (`wired_inputs`), исключаются** из проверки — иначе fan-in (второй вход плагина приходит НЕ от предыдущего по цепочке, а явным межпроцессным Wire) давал бы ложные срабатывания. Ошибки `validate_chain` ДОПОЛНЯЮТ (не заменяют) существующий generic-цикл «Вход '{addr}' не подключен» — оба могут сработать на одном и том же адресе (детальное сообщение + generic), дублирование осознанно принято ради нулевого риска регрессии старого сообщения (ни один существующий тест не проверял точное множество ошибок `check()`).
5. **Regression-guard на живых рецептах:** `phone_sketch.yaml`/`hikvision_letter_robot.yaml` (два «живых» рецепта, план запрещает ломать) прогнаны через `unwrap_recipe → normalize_blueprint → SystemBlueprint.check()` до/после изменения — множество ошибок ИДЕНТИЧНО (3 и 6 pre-existing Wire/generic-ошибок соответственно, ни одной новой `validate_chain`-ошибки формата «X → Y: вход ... несовместим»).

**Отклонения от плана:** нет.

**Последствия:**
- `FW_PORT_VALIDATE=1` в dev/CI ловит рассинхрон декларации портов и фактических items прямо на границе плагина (было — падало глубже по цепочке с непрозрачным KeyError).
- `validate_chain` больше не мёртвый код (C-4 закрыта) — несовместимая внутрипроцессная линейная цепочка (auto-wiring) теперь даёт человекочитаемую ошибку («X → Y: вход 'Z' (dtype shape) несовместим с выходами [...]») уже на сборке чертежа, а не в рантайме.
- Reversible: yes (флаг off, `validate_chain`-блок в `check()` можно откатить отдельным коммитом без побочных эффектов — он только ДОБАВЛЯЕТ строки в `errors`). Risk: low — аддитивно, прод-путь (флаг off) не изменился, hot-path не тронут за пределами одной bool-проверки на вызов (инвариант Ф4: hot-path трогается только в Ф7 — здесь он именно ЧИТАЕТСЯ проверкой флага, не переписывается).

## ADR-PM-013: статический манифест плагина (VERSION/API_VERSION/REQUIRES) + канонизация category + boot fail-fast

**Статус:** принято
**Дата:** 2026-07-11
**Refs:** plans/2026-07-06_constructor-master/plan.md (Ф4 Task 4.4), plans/current-path/review-2026-07-11.md (находки C-1/C-2/C-3), plans/current-path/architecture-10-of-10.md §5

**Контекст:** У плагина не было статического манифеста, читаемого БЕЗ импорта кода и без живого бэкенда (образец — VS Code `package.json` / Home Assistant `manifest.json`) — только runtime-интроспекция уже поднятого процесса (C-1). Отдельно `category` была свободной строкой: аудит 51 плагина показал 10 фактических значений (`processing`×34, `rendering`×3, `output`×3, `io`×3, `utility`×2, `source`×2, `sink`/`hub`/`filter`/`calibration`×1) против 3 задекларированных в докстринге `base.py:230` (C-2), без какой-либо валидации при регистрации. И `PluginContext` собирает менеджеры через тихие `getattr(services, "X", None)` (`base.py:85-123`) — недостающий менеджер («плагин ожидает `worker_manager`, процесс его не поднял») всплывал поздним немым `AttributeError` внутри `configure()`/`start()` плагина, а не на границе оркестратора (C-3).

**Решение:**
1. **Манифест-поля на `ProcessModulePlugin`** (`plugins/base.py`): `VERSION: ClassVar[str] = "0.0.0"` (semver плагина), `API_VERSION: ClassVar[str] = PLUGIN_API_VERSION` (semver контракта плагин↔фреймворк, НЕ версия плагина), `REQUIRES: ClassVar[tuple[str, ...]] = ()` (декларация зависимостей). Все три — обратно совместимые дефолты; существующие 51 плагин работают без единой правки. `PLUGIN_API_VERSION = "1.0"` — константа текущего контракта, заведена в новом `plugins/manifest.py` (не в `base.py`, чтобы не смешивать «определение контракта» и «класс, который ему следует»).
2. **`PluginCategory(str, Enum)`** (`plugins/manifest.py`) — канонический словарь из 11 значений, выровненный с доменными папками `Plugins/*`: `source/processing/render/io/sink/hub/control/filter/calibration/runtime/utility`. `str`-подмешивание — категория остаётся сравнимой/хэшируемой как обычная строка везде, где сейчас читается `entry.category`/`plugin.category` (GUI-каталог, `is_source`, фильтры) — ни один из потребителей не правился. `CATEGORY_LEGACY_ALIASES = {"rendering": "render", "output": "sink"}` — покрывает ровно 6 живых плагинов (`contour_draw`/`overlay_draw`/`circle_draw` → render; `database`/`frame_saver`/`telemetry_sink` → sink, терминальные писатели). Сами файлы плагинов НЕ правились (там остался явный классовый атрибут `category = "rendering"|"output"` — это ДОПУСТИМОЕ расхождение между `cls.category`/`plugin.category` (инстанс, легаси-строка) и `PluginEntry.category` в каталоге (канонизировано) — расхождение живёт только у этих 6 плагинов, задокументировано в докстринге `base.py`).
3. **`canonicalize_category()` — единственная точка канонизации**, вызывается ВНУТРИ `_PluginRegistry.register()` (не в декораторе — так канонизируются И прямые вызовы `.register()`, напр. в тестах, И `@register_plugin`). Неканоничное (не входит ни в `PluginCategory`, ни в алиасы) значение — громкий `logger.warning(...)`, НЕ отказ (Принцип №1: регистрация плагина не должна падать из-за таксономии). `register_plugin()` декоратор берёт `cls.category` из `entry.category` (уже канонизированной), а не из «сырого» аргумента — иначе классовый атрибут разошёлся бы с записью каталога. `_PluginRegistry.register()` теперь возвращает `PluginEntry` (было `None`) — аддитивное расширение сигнатуры, оба существующих вызывающих (декоратор, `test_blueprint_chain_validation.py`) return-значение не используют.
4. **`check_requires(ctx, requires)`** (`plugins/manifest.py`) — валидирует три формата REQUIRES: `"shm"` (`ctx.memory_manager is not None`), `"manager:<attr>"` (`getattr(ctx, attr, None) is not None`, напр. `manager:worker_manager`), `"service:<name>"` (`getattr(ctx.services, name, None) is not None` — задел под менеджеры, которые плагин вешает на `services` в `configure_managers()`, напр. будущий `self._services.sql_manager = ...`; на дату ADR — 0 живых потребителей этого конкретного вида, инфраструктура на будущее). Неопознанный формат REQUIRES-строки тоже считается неудовлетворённым требованием (не игнорируется молча — опечатка в декларации плагина не должна тихо проходить проверку).
5. **Boot-проверки в `PluginOrchestrator.boot()`** (`generic/plugin_orchestrator.py`, Фаза 1, ДО `plugin._do_configure(ctx)`) — асимметричная строгость:
   - **`API_VERSION` mismatch по major** → `services.log_warning(...)`, boot ПРОДОЛЖАЕТСЯ (план: «boot mismatch → WARNING») — несовместимость контракта вероятна, но не гарантирована, отказ был бы слишком грубым инструментом.
   - **`REQUIRES` не удовлетворены** → `services.log_error(...)` с именем плагина и точным списком отсутствующего, плагин ПРОПУСКАЕТСЯ (`continue`, не добавляется в `self._plugins`/`self._contexts`, `configure()`/`start()` не вызываются) — ТА ЖЕ строгость, что уже существовала у провала самого `configure()` (см. `except Exception` в той же Фазе 1): skip/loud, процесс жив. Осознанно строже, чем API_VERSION — недостающий `getattr(ctx, X, None)` гарантированно уронит плагин на первом обращении, откладывать точку отказа некуда.
6. **`introspect.plugins` обогащён полем `manifest`** (`commands/builtin_commands.py`) — АДДИТИВНО, рядом с уже существующим `plugins` (name → category, контракт-тест `test_introspect_commands.py::TestIntrospectPlugins` не тронут): `manifest[name] = {category, version, api_version, requires}` — runtime-зеркало статического манифеста. `docs/contracts/CAPABILITIES.yaml` не перегенерирован — драйв-скрипт `--check` показывает дрейф, ИДЕНТИЧНЫЙ дрейфу на чистом `main` до этой задачи (проверено `git stash` + повторный прогон) — payload-поля команд в дамп не входят (только name/description/tags), регенерация не требуется.
7. **Пилоты (2 из 3, разных доменов)**: `capture` (source) → `VERSION="1.0.0"`, `REQUIRES=("manager:command_manager",)` (без CommandManager start/stop-команды не регистрируются — источник без пультового управления); `robot_io` (io) → `VERSION="2.0.0"`, `REQUIRES=("manager:worker_manager",)` (`job_forwarder`-воркер создаётся в `start()` через `ctx.worker_manager.create_worker(...)` — без него задания копятся в deque и никогда не форвардятся, тихий deadlock). `crop` (processing) → только `VERSION="1.0.0"`, `REQUIRES=()` — демонстрирует минимальный манифест (плагин без framework-зависимостей). REQUIRES у обоих REQUIRES-несущих пилотов заведомо удовлетворены в реальном boot (используемые менеджеры действительно нужны этим плагинам для функционирования) — регрессии на живых рецептах не создаёт.

**Остаток (сознательно не сделано в этой задаче):**
- **Версия рецепта при save** (п.5 расширенного скоупа) — исследован save-путь; НЕ тронут: канонизация формата рецепта идёт параллельно в задаче 4.8 (другой агент, тот же файл-класс области), трогать сейчас — гарантированный конфликт зон. Остаётся открытым пунктом для 4.8 или отдельной задачи после её закрытия.
- **GUI category-карты** (`multiprocess_prototype/frontend/widgets/tabs/pipeline/graph/constants.py::CATEGORY_COLORS`, `.../plugins/presenter.py::CATEGORY_TITLES`) всё ещё keyed по легаси-строкам `"rendering"`/`"output"` — после канонизации 6 плагинов в каталоге (`entry.category`) их цвет/заголовок в GUI будет молча падать на дефолт (`"utility"`/сырое имя категории), т.к. GUI это НЕ `entry.category` напрямую матчит один-в-один с `cls.category` инстанса (который у этих 6 плагинов остаётся легаси — см. п.2) — риск косметический (не функциональный), файлы вне листа задачи 4.4, не тронуты.
- **Симметрия ресурсов SHM** (C-5, contract-тест «выделено в configure() — освобождено в shutdown()») и **entry-points discovery** (C-7) — отдельные находки ревью, не входят в объём 4.4 (см. таблицу находок C-1..C-8).

**Отклонения от плана:** план (`plan.md` Ф4.4) формулировал задачу короче («version/api_version/requires... boot mismatch → WARNING»); реализация расширена ревью 2026-07-11 (Master plan В1) до полного контура C-1/C-2/C-3 — канонический Enum категорий и fail-fast REQUIRES не были в исходной формулировке плана, добавлены по расширенному скоупу задания.

**Последствия:**
- Статический манифест плагина теперь читаем без импорта кода (класс-уровневые `VERSION`/`API_VERSION`/`REQUIRES`) и без живого бэкенда, runtime-зеркало — через `introspect.plugins.manifest`.
- Таксономия категорий канонична и валидируется на регистрации; легаси-значения (`rendering`/`output`) прозрачно маппятся без правки плагинов.
- Недостающая зависимость плагина (`manager:`/`service:`/`shm`) ловится на boot с именем плагина и точным описанием нехватки — вместо позднего немого `AttributeError`.
- Reversible: yes — все три поля манифеста и boot-проверки чисто аддитивны (дефолты не меняют поведение немаркированных плагинов); канонизация category — единственное изменение с наблюдаемым эффектом (текст в `introspect.plugins`/GUI-каталоге для 6 плагинов), обратимо удалением `CATEGORY_LEGACY_ALIASES`-записей. Risk: low — REQUIRES объявлены только на 2 пилотах с заведомо удовлетворёнными зависимостями, hot-path (`process()`/`produce()`) не тронут, boot-проверки — O(len(REQUIRES)) на плагин при старте процесса, не на кадр.

## ADR-PM-014: frame_trace вынесен из `ProcessModulePlugin.__init_subclass__` в `PluginOrchestrator.boot()` (C6 рычаг 2)

**Статус:** принято
**Дата:** 2026-07-11
**Refs:** plans/2026-07-06_constructor-master/c6-pipeline-engine-design.md §4, plans/current-path/review-2026-07-11.md (находка C-6)

**Контекст:** `ProcessModulePlugin.__init_subclass__` оборачивал `process`/`produce` в `frame_trace.traced` на этапе ОБЪЯВЛЕНИЯ класса, импортируя `..generic.frame_trace`. Это создавало жёсткую связь фундамент-плагина (`plugins/base.py`) → inspection-домен (`generic/`) для КАЖДОГО плагина любого будущего приложения — ещё до того, как плагин выбрал категорию. Проблема архитектурная (домен в фундаменте), не производительность (`traced` дёшев при выключенном флаге).

**Разведка (Variant A vs B, §7 Q2):** grep тестов на `.process._traced`/`.produce._traced` без бута — единственные потребители `_traced` это `frame_trace.py` (сеттер) и `plugins/base.py` (снятый чек); тесты (`test_frame_trace.py`) используют `@frame_trace.traced` на функции НАПРЯМУЮ, ни один не полагается на авто-обёртку в момент объявления подкласса `ProcessModulePlugin`. → нулевой риск регресса поведения при переходе на boot-время.

**Решение (Variant A):**
1. `plugins/base.py`: `__init_subclass__` УДАЛЁН целиком (единственное, что он делал — frame_trace-обёртка). База плагина больше НЕ импортирует `generic.frame_trace` — связь фундамент→домен снята.
2. `frame_trace.install_tracing(cls)` — новый публичный хелпер: тот же loop (`process`/`produce`, guard `_traced` idempotency), что был в `__init_subclass__`.
3. `PluginOrchestrator.boot()` вызывает `frame_trace.install_tracing(type(plugin))` рядом с установкой `plugin._trace_node` — оркестратор уже владеет lifecycle-моментом бута и уже трогает trace-related атрибут (`plugin_orchestrator.py:132`), это легитимный дом инструментовки (в отличие от `plugins/base.py`).

**Отклонения от дизайна:** нет. Дизайн рекомендовал Variant A, разведка подтвердила безопасность.

**Rejected:** Variant B (opt-in hook-реестр в `__init_subclass__`) — отвергнут: оставлял бы обёртку на class-время (неявная инвариант «`generic` импортирован до объявления плагина»), при том что разведка показала — class-время vs boot-время не наблюдается ни одним тестом, значит более простой Variant A без нового реестра предпочтителен.

**Последствия:**
- `plugins/base.py` — чистая механика (state machine, PluginContext, порты), не знает про `generic`.
- Обёртка ставится на бутe (idempotent-guard `_traced` защищает от двойной обёртки при бутe одного класса в двух процессах) — даже точнее по времени: плагин, импортированный но не забученный, не оборачивается зря.
- Reversible: yes — вернуть `__init_subclass__` тривиально. Risk: low — поведение (обёртка process/produce при `INSPECTOR_FRAME_TRACE`) идентично, сдвинут только МОМЕНТ установки (class-декл → boot), не наблюдаемый тестами; hot-path не тронут.

## ADR-PM-015: PipelineExecutor исполняет processing-цепочку через ChainRunnable (C6d инкремент 1)

**Статус:** принято
**Дата:** 2026-07-13
**Refs:** plans/2026-07-06_constructor-master/c6-pipeline-engine-design.md §5(d) инкремент 1, plans/2026-07-06_constructor-master/plan.md (C6d)

**Контекст:** `PipelineExecutor._execute_chain` был плоским собственным sequential-loop по `list[ProcessModulePlugin]` — дублировал роль исполнителя, при том что `chain_module` (`ChainRunnable`) — механизм последовательного прохода шагов — «дремал» с 0 живых потребителей (аудит D4/D2, дизайн §1.5). C6d делает `chain_module` живым исполнителем processing-цепочки одного процесса, не размазывая по нему breaker/IPC.

**Решение:**
1. Типизация `chain_module` обобщена `frame: np.ndarray` → `payload: Any` (`ChainRunnable.execute`, `IRunnableChain`, `ChainResult.frame`) — тело duck-typed, не тронуто; contract processing-pipeline (`list[dict]` items) прогоняется тем же исполнителем.
2. Новый мост `PluginOperationStep` (`IExecutionStep`, дом — `process_module/generic/`) делегирует СТРОГО через `PluginRunner.call_process` (io-debug/FW_PORT_VALIDATE не отключаются — риск №2 дизайна §6, контракт-тест); сам ловит исключение → тег `not_inspected` + `on_fail`-репорт; `on_error` шага всегда `skip`.
3. Вся breaker-семантика (consecutive_fails/bypass/auto_reset/critical→suspect) остаётся в `PipelineExecutor`, `chain_module/core/error_policy.py` НЕ тронут (0 изменений). Критический bypassed плагин ПОДМЕНЯЕТСЯ на позиции лёгким `SuspectTagStep` (точная per-position семантика — тег на items, существующих в момент прохода), некритический — выбрасывается из шагов.
4. Активные шаги мемоизируются (dirty-флаг, инвалидация в `_on_plugin_fail`/`_check_auto_reset`) — 0 пересборок в стабильном breaker-окне.
5. Скоуп — строго Инкремент 1. Инкремент 2 (`DagRunnable`/`ParallelChainRunnable` для intra-process ветвления) — ВНЕ скоупа (нет живого потребителя, анти-карго-культ, дизайн §5(d)).

**Перф (микробенч old list-loop vs chain-based):** фиксированный overhead `ChainRunnable.execute` ~2µs/батч (ChainContext+ChainResult+per-step hasattr, тело chain.py менять нельзя). Пустые синтетические плагины: −45…−67% throughput (worst case машинерии); реальная работа звена: 50µs/звено −1.25%, 200µs −0.36%, 1ms −0.03%. Кроссовер под 5% — уже при мизерной работе; на настоящих CV-плагинах регресс FPS <1.3%. Дизайн §6 предвидел (мерить на рецептах, откат к list-loop только при реальном регрессе). Прод-рецепты headless не бутятся — реалистичный synthetic-work бенч = прокси recipe-FPS.

**Rejected:** держать все плагины шагами и фильтровать bypass ВНУТРИ шага (чтение `is_bypassed` в шаге) — отвергнуто: breaker-семантика утекла бы в chain-слой. Ранняя реализация «фильтр bypassed до сборки + suspect-тег upfront» — отвергнута ревью (Fable HIGH): upfront-тег терял позицию (downstream-плагин перезаписывал статус; замена списка теряла тег) — доказано 2 RED-тестами, исправлено `SuspectTagStep`-на-позиции.

**Последствия:**
- `chain_module` — живой исполнитель processing-цепочки (acceptance C6 «живой пайплайн через chain»); DAG/parallel доступны, НЕ подключены.
- `run_loop`/`_send_results`/`bind_queue`/метрики/IPC НЕ переехали в chain_module; `SourceProducer` не тронут; hot-path (SHM/seqlock/per-frame Message) не тронут.
- Reversible: yes — откат к прямому list-loop локален в `_execute_chain`. Risk: medium (перф, см. выше; смягчён — реальный регресс FPS <1.3%).
