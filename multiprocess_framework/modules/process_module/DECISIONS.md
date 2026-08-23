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


## ADR-PM-016: телеметрийный тик в контракте (`publish.tick_sec`) — вариант (а), heartbeat-сообщение по счётчику времени

**Статус:** принято
**Дата:** 2026-07-16
**Refs:** plans/telemetry-coherence-remediation.md (Task 1.2), ADR-PM-010/PC 1.2 (publisher-gate), telemetry-publish-control.md (finding D)

**Контекст:** Частота публикации телеметрии де-факто задавалась `heartbeat_interval=5.0` — читался ОДИН раз в `ProcessHeartbeat.start()`, `reconfigure_telemetry` его не трогал. Верхняя ступень частотной лестницы (finding D ревью Fable): publisher `interval_sec < 5с` — тихий no-op, «поднять частоту» нельзя ни одной ручкой control-plane. `TelemetryGate` per-метрика rate-limit был доминирован захардкоженным 5с-тиком воркера.

**Решение — вариант (а)** (из двух в плане): heartbeat-воркер тикает по `min(heartbeat_interval, tick_sec)`; телеметрия публикуется КАЖДЫЙ тик (per-метрика rate-limit держит `TelemetryGate`), а heartbeat-СООБЩЕНИЕ к `ProcessManager` + хозяйственные self-publish'ы (health/observability/GC) — по расписанию liveness (`_heartbeat_due`: прошло >= `heartbeat_interval` с прошлой отправки, порог с запасом `tick/2` против джиттера). `TelemetryPublishConfig.tick_sec: float | None = None` (None → `heartbeat_interval`, backward-compat). `_telemetry_tick()`/`_heartbeat_due()` читаются каждую итерацию `_loop` → рантайм-смена `tick_sec` через `reconfigure_telemetry` подхватывается на следующем тике. Валидация: метрика с `interval_sec < min(heartbeat_interval, tick_sec)` → WARNING «частота ограничена тиком» (было тихим no-op). Clock инъектируется в `ProcessHeartbeat` и прокидывается в `TelemetryGate` — детерминированные fake-clock тесты каденции.

**Rejected — вариант (б)** (отдельный воркер `telemetry_publisher` со своим `stop_event.wait(tick_sec)`): отвергнут — второй воркер = второй lifecycle + дубль `get_all_workers_status()` + необходимость делить health/observability/GC между двумя циклами (какой контур «хозяйничает»). Вариант (а) — один воркер, один снимок воркеров за тик, инвариант liveness провозится ЯВНОЙ time-gate проверкой (heartbeat-сообщение бит-в-бит раз в `heartbeat_interval`), меньше слоёв (предпочтение владельца).

**Критический инвариант:** частота heartbeat-СООБЩЕНИЙ к `ProcessMonitor` (liveness) НЕ меняется телеметрийным тиком — иначе ложные «process dead». Провозится `_heartbeat_due` (при `tick_sec=None` → `tick >= interval` → каждый тик = heartbeat-такт, бит-в-бит) и покрыт acceptance-тестом (`test_telemetry_tick.py`: `tick_sec=0.5` → телеметрия 20/10с ~ 2 Гц, heartbeat 2/10с ~ 0.2 Гц).

**Последствия:**
- Частота телеметрии управляется контрактом (boot + runtime `telemetry.reconfigure`), а не хардкодом — finding D закрыт (верхняя ступень лестницы стала управляемой).
- health/observability/GC остаются на каденции `heartbeat_interval` (сгруппированы с heartbeat-сообщением) — их частота НЕ меняется при подъёме телеметрийного тика (нет scope-creep).
- Reversible: yes — `tick_sec=None` возвращает прежнее поведение целиком; откат правки локален в `heartbeat/`.
- Risk: low — liveness-инвариант под тестом; backward-compat (tick_sec=None) характеризован; `GATED_METRICS` из configs не выносился (цикл-риск Task 2.3 не тронут — `capped_metrics` живёт в heartbeat-слое, где оба импорта уже есть).

## ADR-PM-017: центральный троттл — IPC-предохранитель, publisher-gate — единственный авторитет частоты

**Статус:** принято
**Дата:** 2026-07-16
**Refs:** plans/telemetry-coherence-remediation.md (Task 1.3 + Task 1.4 Amendment), ADR-PM-016 (тик публикации), telemetry-publish-control.md (residual #6, finding D вторая половина)

**Контекст:** Частотная лестница телеметрии имела ДВА авторитета с равными дефолтами: publisher-gate процесса (`telemetry.publish`, per-метрика `interval_sec`, дефолт 1.0с) и центральный `ThrottleMiddleware` оркестратора (`_default_throttle_rules`, fps/latency/… = 1.0с). Поднятие частоты метрики через publisher (напр. `interval_sec=0.2`) МОЛЧА гасилось второй ступенью: троттл 1.0с > 0.2с → апдейты придерживались, эффективная частота в дереве StateStore не росла (residual #6 — «две плоскости с равными дефолтами каскадируют»; вторая половина finding D — «поднять частоту нельзя ни одной ручкой control-plane»). Central-троттл, задуманный как IPC-страховка (не перегружать StateStore/IPC), де-факто стал вторым авторитетом каденции.

**Решение:** Central-троттл понижен до роли ЧИСТОГО IPC-предохранителя от СБОЙНОГО публикатора; единственный авторитет частоты — publisher-gate. Два механизма:
1. **Дефолт заведомо мягче тика** (`manager_setup._default_throttle_rules`): все дефолт-правила на единый мягкий `_SAFETY_INTERVAL_SEC = _MIN_PUBLISHER_INTERVAL_SEC (0.1с) × _THROTTLE_SAFETY_MULTIPLIER (0.5) = 0.05с` — заведомо НИЖЕ минимального осмысленного интервала публикации. Легитимное поднятие частоты через publisher доходит до дерева без среза; троттл срабатывает лишь на публикатор, шлющий БЫСТРЕЕ собственной декларации (реальный сбой, потолок ≈20 Гц). Прежние жёсткие 1.0/2.0/5.0с (совпадавшие с publisher-дефолтом) убраны.
2. **«No silent caps» при явном конфликте** (`telemetry_reload.detect_throttle_caps`, вызывается в `ProcessManagerProcess._cmd_telemetry_broadcast`): если оператор ВРУЧНУЮ задал строгое central-правило и поднимает publisher-частоту НИЖЕ него, троттл срезал бы поднятие → вместо тихого среза возвращается явный флаг `capped_by_throttle: {metric: {publisher_interval_sec, throttle_interval_sec}}`. Инициатор (backend_ctl/GUI) видит потолок и осознанно ослабляет central-правило (`telemetry_set plane=throttle`). Сопоставление метрика→central-правило — по СУФФИКСУ паттерна (`processes.**.state.fps` → метрика `fps`), чтобы framework не хардкодил layout дерева прототипа.

**Rejected — auto-relax** (автоматически ослаблять central-правило под publisher-дельту через `update_rule`): отвергнут. (1) Прячет страховку: publisher МОЛЧА переписал бы операторский предохранитель — сбойный публикатор, декларирующий крошечный `interval_sec`, авто-снял бы защиту, ровно ту, ради которой троттл сохранён (Out of scope Task 1.3: «не удалять центральный троттл — остаётся IPC-страховкой»). (2) Молча отменяет ОСОЗНАННУЮ операторскую настройку строгого правила. `capped_by_throttle` держит обе плоскости authoritative-и-видимыми: страховка нетронута, конфликт виден. Дефолт-мягкость (механизм 1) уже обеспечивает «частота реально растёт» в дефолтном сценарии (главный acceptance) без жертвы страховкой — auto-relax не нужен для этого.

**Критический инвариант (оба пути + дефолт-сценарий):** central-троттл НИКОГДА не отменяет молча
поднятие частоты — ни на fan-out-пути (`telemetry.broadcast`, `process="all"`), ни на адресном
per-process (Task 1.4, см. Amendment ниже). Оба идут транзитом через PM (держатель central-
троттла), поэтому на обоих `detect_throttle_caps` работает: либо дефолт мягче публикатора (частота
растёт), либо оператор получает `capped_by_throttle` (видит потолок). Ни одного тихого no-op.

**Последствия:**
- Publisher-gate — единственный авторитет каденции; троттл лишь страхует от runaway (residual #6 закрыт **не полностью — см. амендмент ниже**).

**Амендмент (2026-08-07, Ф8.2 → ADR-SS-021):** формулировка «residual #6 закрыт» была верна для
ДЕФОЛТОВ и неверна для механизма. Механизм 1 (дефолт мягче публикатора) снял каскад в дефолтном
сценарии, но сам троттл продолжал резать по РАЗНОСТИ показаний часов, поэтому публикатор,
работающий ровно на пределе ручного central-правила, терял половину записей — и терял молча,
потому что механизм 2 (`detect_throttle_caps`) сравнивает строго `>` и на равных интервалах не
срабатывает. Закрыто в `ThrottleMiddleware`: допуск считается по фиксированной сетке
`floor(now / interval)`. **`detect_throttle_caps` при этом не менялся** — после правки зоны
ответственности перестали перекрываться: сетка отвечает за `T ≤ P`, детектор за `T > P`.
Расширение условия детектора (`>=` или порог с запасом) рассмотрено и отвергнуто — обоснование
и замеры в ADR-SS-021.
- Дефолт-троттл больше не режет current-рецепты (публикуют на 5с-тике — 0.05с предохранитель им не мешает; характеризация в `test_integration.py`).
- Reversible: yes — значения дефолтов и helper локальны; откат тривиален. Risk: low — сквозной store-gate тест доказывает рост частоты; `detect_throttle_caps` read-only (троттл не мутирует).

**Amendment (Task 1.4, 2026-07-17) — Known-gap закрыт, вариант (а) «перехват в PM»:** адресный
per-process `telemetry.reconfigure` больше НЕ уходит от driver'а ребёнку напрямую — он тоже идёт
транзитом через PM: `driver.telemetry_reconfigure(process=X)` → `telemetry.broadcast` c
`data["target"]=X`. PM детектит `capped_by_throttle` СВОИМ `resolve_store_throttle(self)` (тем же,
что на broadcast-пути) и форвардит `publish` ОДНОМУ ребёнку через `_send_child_command`
(`comm.send_to_process`); `throttle`-плоскость применяется центрально (троттл оркестратор-глобален,
`target` её не касается). Прежний прямой driver→child путь ретрополнен — на нём cap был
принципиально не детектируем (`resolve_store_throttle` на ребёнке всегда `None`). **Trade-off:**
адресный путь стал fire-and-forward — per-child `applied` больше не возвращается (охват `reached`
0/1 вместо него), т.к. синхронный сбор ответа ребёнка в хендлере PM заблокировал бы
message_processor (тот же дедлок, что в `driver.capabilities`). Факт применения смотреть по
`effective_hz` в дереве. **Rejected — вариант (б) «явный отказ»** (адресный raise возвращает
error «используй process=all»): отвергнут — не разблокировал бы per-process крутилку Фазы 4 (она
как раз про адресное поднятие частоты одному процессу), ради которой Task 1.4 и делалась.

## ADR-PM-018: Управляемая публикация телеметрии — errors always-on, logs/stats/telemetry управляемо у источника

**Статус:** принято
**Дата:** 2026-07-17
**Refs:** plans/telemetry-publish-control.md, ADR-PM-016, ADR-PM-017, ADR-CRM-006

**Контекст:** Владелец хотел задавать частоту публикации per-параметр/группу и вкл/выкл, менять это
в рантайме (конфиг ИЛИ backend_ctl), управляя «через statistics manager», чтобы не грузить систему.
Разведка (`telemetry-publish-control.md`, Context) вскрыла три факта: (1) существовавший per-путь
троттл (`build_throttle_rules`) был de-facto no-op на телеметрию — `ThrottleMiddleware.before_merge`
не был переопределён, а телеметрия едет через `proxy.merge` (heartbeat self-publish), не `before_set`;
(2) телеметрия НЕ идёт через `StatsManager` — тот пишет в локальные каналы, remote-транспорта в
дерево StateStore у него нет (см. [[project_telemetry_self_publish]]) — публикация fps/latency/hz
всегда шла self-publish'ом из heartbeat; (3) следовательно «управлять через stats manager» не может
означать «пустить данные через stats manager» — это дублировало бы уже работающий канал доставки;
управлять нужно было ДРУГИМ — плоскостью конфигурации, размещённой рядом со stats/observability-
настройками, а данные оставить на heartbeat-канале.

**Решение:**
1. **Принцип:** ошибки — всегда (always-on, не конфигурируются); логи/статистика/телеметрия —
   управляемо (вкл/выкл + частота), декларативно из конфига, у ИСТОЧНИКА данных (publisher-gate внутри
   heartbeat, не в отдельном стоке), изменяемо в рантайме тем же путём, что и boot.
2. **Разделение «плоскость управления» vs «канал данных»:** тумблеры/частота живут в
   stats/observability-конфигурационной плоскости (`TelemetryPublishConfig`, framework schema), но
   сами данные телеметрии по-прежнему едут heartbeat self-publish'ом (`build_worker_telemetry` →
   `proxy.merge`) — НЕ через `StatsManager`-транспорт, которого для этого не существует.
3. **Framework-first:** контракт `TelemetryPublishConfig`, publisher-gate (`TelemetryGate` в
   `heartbeat/telemetry.py`), рантайм-команды (`config.reload`, backend_ctl `telemetry.reconfigure`/
   `telemetry.set`/`telemetry.broadcast`) и fan-out — целиком во `process_module`/`state_store_module`/
   `process_manager_module`/`backend_ctl`. Прототип задаёт только значения (`system.yaml`/рецепт) и
   GUI-контролы (Task 4.1) — управляемую публикацию получает даром.
4. **Две плоскости троттла, одна главная:** publisher-gate (per-process, ГЛАВНЫЙ рычаг — что считать/
   публиковать и как часто) + центральный `ThrottleMiddleware` (оркестратор, вторая линия — IPC-
   страховка от сбойного публикатора). Роли не симметричны и не заменяют друг друга.

**Связь с ADR-PM-016/017 (не дублируется здесь):** ADR-PM-016 развёл частоту heartbeat-СООБЩЕНИЯ
(liveness, неизменна) и частоту телеметрийного ТИКА (`publish.tick_sec`, управляема). ADR-PM-017
понизил центральный троттл до роли чистого IPC-предохранителя (дефолт заведомо мягче любого
осмысленного publisher-интервала) и сделал publisher-gate единственным авторитетом каденции, добавив
явную видимость конфликта (`capped_by_throttle`) вместо тихого среза; Amendment Task 1.4 закрыл
адресный per-process путь тем же механизмом через ProcessManager.

**Известный residual (сознательный known-gap, не закрыт этим ADR):** две плоскости троттла с равными
дефолтами каскадируют — центральный троттл как НЕЗАВИСИМЫЙ потолок поверх publisher-gate может молча
отменить попытку ПОДНЯТЬ частоту через publisher при равных интервалах, плюс двойное прореживание
искажает эффективную частоту на фазовом рассогласовании двух `monotonic`-часов. ADR-PM-017 смягчил
дефолтный сценарий (дефолт-троттл 0.05с — заведомо ниже публикаторского), но при РУЧНОМ строгом
central-правиле остаточный каскад возможен; текущая мера — не автоматическое разрешение конфликта, а
ВИДИМОСТЬ (`capped_by_throttle` прокидывается до backend_ctl/GUI, Task 3.2/4.1) и явная фиксация в
docstring `telemetry_set`: троттл = ceiling, publisher = floor-внутри-ceiling. Направление фикса на
будущее (вне объёма этой задачи): при активном publisher-gate на метрику ослаблять/снимать
соответствующее central-правило для НЕЁ, делая publisher единственным авторитетом без исключений —
не сделано, т.к. требует связывать per-метрика publisher-состояние с central-правилами по glob-паттерну
(риск скрытой сложности ради редкого ручного кейса).

**ЗАКРЫТО 2026-08-07 — ADR-SS-021, и не тем способом, который здесь предсказан.** Три поправки
к абзацу выше, каждая воспроизведена запуском:

1. **Заявленная мера не покрывала названный случай.** Абзац называет каскад «при равных
   интервалах» и объявляет действующей мерой видимость через `capped_by_throttle`. Но
   `detect_throttle_caps` сравнивает строго (`throttle > publisher`) — ровно при равенстве
   флага НЕТ. Документация обещала сторож, которого в этом случае не существовало.
2. **Причина названа неверно.** «Фазовое рассогласование двух `monotonic`-часов» — часы здесь
   ОДНИ (`ThrottleMiddleware._now`). Настоящая причина: скользящее окно меряет РАЗНОСТЬ двух
   показаний и потому зависит от их разрешения, а `time.monotonic` на Windows —
   `GetTickCount64()` с шагом 15.625 мс. Промежуток 50 мс читается как 46.875 мс → запись
   отбрасывается. Замер: 33 из 60 при `T == P`, 60 из 60 при `T == 0.9P`.
3. **Направление фикса выбрано другое.** Предложенный здесь путь (ослаблять central-правило
   под активный publisher-gate) отвергнут вместе с `auto-relax` из ADR-PM-017 — он прячет
   операторскую страховку. Вместо этого исправлен сам механизм окна: троттл считает окна
   фиксированной сетки, а не разности. Тогда предохранитель прозрачен для трафика на своём
   пределе и ниже, а детектор остаётся строгим и отвечает только за `T > P`. Зоны перестали
   перекрываться — дыра на стыке исчезла вместе с перекрытием, а не была заклеена третьей
   редакцией предупреждения.

Плоскостей по-прежнему две, и это НЕ два авторитета одной величины: publisher задаёт каденцию,
троттл ограничивает потолок IPC. Подробности, замеры и отвергнутые альтернативы — ADR-SS-021.

**Последствия:**
- Архитектурные изменения: framework получил полный контур управляемой публикации — schema →
  publisher-gate → hot-reload → backend_ctl-команды → fan-out; любое приложение на фреймворке получает
  это бесплатно, задавая лишь значения.
- Миграция: не требуется — все механизмы аддитивны с backward-compat дефолтами (отсутствие секции
  `telemetry` → прежнее поведение целиком, `tick_sec=None` → прежний heartbeat-тик).
- Ограничения: errors остаются неконфигурируемыми (always-on) — ни один путь конфигурации не должен
  получить возможность выключить error-репортинг; central-троттл не заменяет publisher-gate как primary
  control и не должен обрастать per-метрика логикой (это утекло бы обратно в publisher-плоскость).
- Известные риски: residual двух плоскостей троттла (см. выше); рантайм-дельта телеметрии теряется при
  hot-swap рецепта (пересозданный процесс берёт boot-конфиг) — задокументировано в плане как отдельный
  low-priority follow-up, не решается этим ADR.

## ADR-PM-019: Оптовый ключ рецепта не адресует оркестратора; имя оркестратора — константа цепочки слоёв

**Статус:** принято
**Дата:** 2026-07-29
**Refs:** plans/observability-unified-routing.md (Task 5.13), ADR-CRM-006, ADR-PM-016

**Контекст:** Оркестратор (`ProcessManager`) поднимался на голых дефолтах L0 — `INFO` и
`log_directory=None` — при `system.yaml`, говорящем `WARNING`. Корень оказался общим у двух симптомов
(«дети WARNING, PM INFO» и пустой каталог логов у PM): ассемблер раскладывает слои в
`proc_dict["managers"]` только ДОЧЕРНИМ процессам, а bundle оркестратора ключа `managers` не несёт
вовсе (`spawner`). Воспроизводилось без рецепта, одним `system.yaml`.

Починив доставку, пришлось ответить на вопрос, которого до этого не существовало: **действует ли
`defaults:` рецепта на оркестратора?** Рецепт описывает КОНВЕЙЕР, а оркестратор — не его звено:
он живёт дольше рецепта, переживает switch и обслуживает все конвейеры по очереди. Оптовый ключ,
задуманный как «накрыть все процессы обработки», накрыл бы заодно и того, кто этими процессами
управляет — включая случай, где оператор ставит `DEBUG` на конвейер и получает `DEBUG` в журнале
оркестратора, где его никто не ждёт.

**Решение:**
1. **`defaults:` (и его короткая форма — ключи прямо в секции) на оркестратора НЕ действуют.**
   Единственный способ адресовать его из рецепта — назвать поимённо в
   `observability.processes.ProcessManager`. Объём исключения — весь `defaults` целиком, включая
   не-глушащие ключи: правило «оптовое не для оркестратора» должно быть одним, а не списком исключений
   из исключения.
2. **Правило живёт ВНУТРИ `resolve_recipe_section`**, а не параметром у вызывающих. Call-sites пять,
   и три из них исполняются внутри процесса (boot, `config.reload`, конверт switch'а) — параметр
   у вызывающих дал бы `effective`, зависящий от того, какой путь стрелял последним. Аварийный выход
   есть и он явный: `include_defaults=True` возвращает прежнюю семантику.
3. **Асимметрия наблюдаема снаружи:** `introspect.observability` отдаёт `layers.recipe_defaults_applied`
   (`False` у оркестратора, `True` у остальных), и флаг вычисляется той же функцией, что и резолв.
   Иначе «почему у меня не DEBUG» осталось бы без ответа, а расхождение флага с поведением — возможным.
4. **Имя оркестратора — константа `ORCHESTRATOR_PROCESS_NAME`** в `configs/observability_layers.py`
   (самый нижний модуль, которому имя нужно; обратное направление дало бы цикл
   `process_module` ← `process_manager_module`). Она покрывает цепочку «спавн + слои», где имя раньше
   было тремя расходящимися литералами. Адресные дефолты `StateProxy`/`RouterManager.relay_hub`/
   GUI-моста НЕ сводятся к ней сознательно: там имя — контракт АДРЕСАЦИИ, независимый от контракта
   сборки, и одна константа связала бы два несвязанных решения.

**Rejected — «оптовое действует, а PM исключается фильтром глушащих ключей»:** отвергнуто — превращает
одно правило в список (какой ключ считать глушащим?), и список расходится с реальностью на первом же
новом ключе схемы.
**Rejected — «параметр `include_defaults` обязателен у каждого вызывающего»:** отвергнуто — см. п.2,
даёт `effective`, зависящий от порядка вызовов.
**Rejected — «отдельная секция `observability.orchestrator:`»:** отвергнуто — вторая форма записи для
того же смысла; `processes.<имя>` уже существует и работает, а новая секция потребовала бы своего
резолва, своего провенанса и своей ветки в спутнике.

**Последствия:**
- Приложение на фреймворке получает предсказуемый журнал оркестратора из `system.yaml` без единой
  строки кода; рецепт может поднять оркестратору уровень, но только назвав его.
- Ограничение: процесс, названный `ProcessManager` и НЕ являющийся оркестратором, получит исключение.
  Это цена спецслучая по имени, принятая сознательно: имя уже входит в дисковый контракт
  (`observability.persist` пишет спутник по `svc.name`), и структурного признака «я оркестратор»
  на момент резолва секции не существует.
- Миграция не требуется: рецепты без `processes.ProcessManager` меняют поведение только в ту сторону,
  где оркестратор перестаёт молча наследовать конвейерный `defaults`.

## ADR-PM-020: Молчащие слои наблюдаемости не дают повода трогать менеджеры

**Статус:** принято
**Дата:** 2026-07-29
**Refs:** plans/observability-unified-routing.md (ревью Task 5.13), ADR-PM-019, ADR-CRM-006

**Контекст:** Финальное ревью 5.13 нашло одно правило, живущее тремя редакциями. `expand_observability({})`
возвращает не пустой словарь, а ПОЛНЫЙ набор дефолтов L0. Наложенный на готовую секцию менеджеров, он
затирает то, что пришло другим путём и слоями не описано. Три адресата обходились с этим по-разному:

* generic-дорога (`assemble_proc_dicts`) проверяла молчание слоёв и секцию не трогала;
* прикладная (`BlueprintAssembler`) накладывала безусловно — у процесса с молчащими слоями появлялась
  секция `managers`, целиком собранная из дефолтов L0;
* пересборка на boot (`_apply_boot_observability_layers`, ADR-PM-019) читала «секция менеджеров пуста»
  как «менеджеры не настроены» — что не следует: во фреймворке-конструкторе встройщик вправе собрать
  `LoggerManager` программно и секции не заводить.

Расхождение было латентным ровно потому, что в прототипе `system.yaml` всегда несёт секцию
`observability`, а значит слои никогда не молчат.

**Решение:**
1. **Молчание слоёв означает «решает нижний», а не «сбросить к дефолтам».** Предикат один —
   `layers_are_silent(layers)`; продакшн-адресатов **два** — общий шов раскладки `apply_layers_to_proc_dict` (обе дороги сборки) и пересборка на boot, и оба спрашивают его. (Было записано «три» — по числу дорог ДО их сведения в один шов; сверено с кодом 2026-08-02.)
2. **Раскладка «слои → менеджеры» — один шов `apply_layers_to_proc_dict`** на обе дороги сборки. При
   молчащих слоях proc_dict не мутируется вовсе. Цена нарушения — не «лишний ключ»: к моменту вызова
   секция `managers` уже собрана `managers_from_log_dir` (каталог логов, пути файлов, уровень из
   `INSPECTOR_LOG_LEVEL`), и наложение `expand_observability({})` молча возвращает уровень из
   окружения к дефолту L0. Проверено литералом в страж-тесте, а не рассуждением.
3. **Пересборка на boot требует ДВУХ условий:** секция менеджеров пуста И слои непусты. Первое без
   второго тихо отменяло бы программную настройку встройщика.
4. **Отказ чтения секции менеджеров слышен.** Он выбирает консервативную ветку (пересборку не делать),
   то есть меняет поведение — проглоченный молча, оставлял бы процесс на дефолтах L0 без причины
   в журнале.

**Rejected — «свести две дороги сборки в одну»:** отвергнуто — прикладная несёт app-специфику
(per-category defaults, telemetry), которой generic не знает; сводить надо было не дороги, а ОБЩЕЕ
правило. Паритет раскладки закреплён стражем `test_assembly_roads_agree` в тестах прототипа (фреймворку
запрещено импортировать прототип, поэтому сверка живёт на нижнем слое).

**Последствия:**
- Встройщик фреймворка может настроить менеджеры программно и не заводить секцию конфига — его решение
  переживёт boot.
- Ограничение: `layers_are_silent` судит по РЕЗОЛВУ слоёв. Слой, задающий ключ значением, равным
  дефолту L0, молчащим не считается — и это правильно: «задано явно» и «не задано» различимы в
  провенансе, и различие сохраняется.

## ADR-PM-021: Спутник рецепта не входит в базу слоя L2 — только поверх неё

**Статус:** принято
**Дата:** 2026-08-02
**Refs:** plans/observability-unified-routing.md (сквозное ревью Ф5, блокер ФР-3 / находка X2-1),
ADR-PM-019, ADR-PM-020

**Контекст:** Слой L2 процесса собирается из двух источников — БАЗЫ (долька самого рецепта, её кладут
ассемблеры в `proc_dict["config"]["observability_override"]`) и спутника рецепта
(`<recipe>.observability.yaml`, machine-owned, его пишет `observability.persist`). Task 5.13 свела
«спутник поверх рецепта» к шву `merge_companion_over` и позвала его из трёх мест ПРИКЛАДНОЙ дороги:
boot (`launch.py`), пересборка switch'а (`orchestrator_hooks`), конверт switch'а
(`_recipe_layer_payload`). Все три мержили спутник в СЕКЦИЮ рецепта — то есть в базу, и до резолва по
именам. Generic-дорога (`app_module.SystemBuilder`) спутника не мержила вовсе.

Асимметрия наблюдалась только на снятом ключе. Слой заменяется целиком, а база — нет: она живёт в
конфиге процесса и переживает пересборки. Значит ключ, снятый оператором из спутника, на прикладной
дороге оставался в базе НАВСЕГДА, а на generic честно возвращался к значению рецепта. Пока спутник жив,
обе дороги дают одинаковый результат — поэтому дефект не имел симптома. Комментарий в
`builtin_commands` («спутник сюда не пишется намеренно — иначе снятый из него ключ въехал бы в базу и
не исчез бы уже никогда») описывал ровно этот инвариант, и он был нарушен на главной прод-дороге.

Вторым, тихим следствием секционной гранулярности было нарушение самого правила «спутник сверху»:
`defaults` спутника проигрывал `processes[<имя>]` рецепта, потому что мерж шёл ДО резолва.

**Решение:**
1. **База слоя L2 не содержит спутника ни на одной дороге.** Ассемблеры, конверт switch'а и
   `orchestrator_observability_config` работают с сырой секцией РЕЦЕПТА. Контракт
   `orchestrator_observability_config` («секция, уже смерженная со спутником») отменён и переписан.
2. **Наложение спутника — один шов `observability_companion.compose_over_base`,** и он исполняется
   ПОСЛЕДНИМ у каждого потребителя: у ребёнка на старте (`_apply_boot_observability_layers`) и в ветке
   switch'а/refresh `config.reload`, у оркестратора — в `_compose_own_recipe_layer`. Гранулярность —
   уже разрешённая per-process долька с обеих сторон, поэтому направление «спутник сверху» держится и
   для `defaults` спутника.
3. **Секционный шов `merge_companion_over` удалён.** Оставленный без вызовов, он был бы приглашением
   повторить дефект: его семантика — ровно то, чего делать нельзя.
4. **Громкий отказ на битом спутнике остаётся ровно в одной точке — `SystemBuilder.build()` прототипа**
   (читает файл и не глушит исключение). Каждый процесс дальше обязан ошибку проглотить в журнал:
   падать на старте из-за спутника ему нельзя, а switch не имеет права ронять живую систему.
5. **Нормализация пустой секции конверта названа явно.** `None` («рецепт переехал, слой не трогать») и
   `{}` («новый рецепт молчит» → снять прежний слой) различаются у получателя; прежде нормализацию
   делал `merge_companion_over` побочным эффектом.

**Rejected — «домержить спутник и на generic-дороге» (сойтись в другую сторону):** отвергнуто — это
починило бы паритет и закрепило дефект: снятый ключ перестал бы исчезать у всех. Паритет здесь не цель,
а следствие правильного правила.

**Rejected — «оставить `merge_companion_over` под стражами, но без вызовов»:** отвергнуто — мёртвая
публичная функция, чья семантика и есть дефект. Её юнит-тесты переписаны на `compose_over_base`.

**Последствия:**
- Ключ, снятый из спутника, возвращает значение рецепта на ОБЕИХ дорогах и на всех трёх путях
  (boot, switch, live-refresh). Пока спутник жив, действующий слой не изменился ни на бит.
- `defaults`, дописанный в спутник руками, теперь побеждает `processes[<имя>]` рецепта — как и
  заявляло правило «спутник новее». Прежнее поведение прикладной дороги было обратным.
- Ограничение (резидуал, вне ФР-3): L2-watcher оркестратора применяет ФАЙЛ СПУТНИКА как весь слой L2
  (`make_observability_on_reload` с `layer=recipe`), то есть на правку спутника оркестратор теряет
  собственную дольку рецепта. Дефект предсуществующий и от базы не зависит.

---

## ADR-PM-022: Ссылки без приёмника проверяются в шве сборки слоя L2, а не у каждой дороги

**Статус:** принято
**Дата:** 2026-08-02
**Refs:** plans/observability-unified-routing.md (сквозное ревью Ф5, блокер ФР-2 / находка C-4-1),
Task 5.5, ADR-PM-021

**Контекст:** Task 5.5 завела проверку ссылок наблюдаемости, за которыми нет приёмника
(`unknown_observability_refs`): `channels: {messages_fil: {enabled: false}}` адресует канал, которого
нет, и до 5.5 стоил ровно ничего. Проверка была написана ВНУТРИ ветки `config.reload`, там же, где
считался каталог известных имён и формировалась громкая строка. Тем самым она стала свойством ОДНОЙ
дороги, а не свойством слоя.

Тело в слой L2 кладут пять дорог. Проверены были две — inline-ручка оператора (отказ) и файл L1
(громко). Три остальные молчали: конверт switch'а, перечитка спутника по команде
(`observability_recipe_reload`) и подхват спутника на boot. Живое репро: конверт switch'а с опечаткой
`messages_fil` → `success=true`, `unknown_refs` в ответе нет, громких строк ноль.

Замыкала круг связка с `observability.persist`. Пульт сохраняет слой сессии в спутник; ключ на СНЯТЫЙ
канал там законен (снятый приёмник остаётся в конфиге, и `{enabled: true}` про него — возврат, а не
опечатка), но ключ на НЕСУЩЕСТВУЮЩИЙ канал сохраняется ровно так же. На следующем старте он въезжает
тихой дорогой — опечатка, увековеченная машиной в machine-owned файле, который человек не читает.

**Решение:**
1. **Правило — одно, и оно в `observability_refs`:** `unknown_refs_for(svc, section)` (каталог имён
   живого процесса + сироты) и `report_unknown_refs(svc, section, source=...)` (то же плюс громкая
   строка). У вызывающего остаётся только выбор политики, не расчёт.
2. **Точка вызова для живого процесса — шов сборки слоя, `compose_recipe_layer`.** Ровно три дороги
   кладут тело в L2 у процесса, и все три собирают это тело ею: конверт switch'а, перечитка спутника,
   boot. Функция возвращает третьим значением сироты, то есть собрать слой L2, не узнав про них,
   больше нельзя. Оркестратор идёт мимо (база у него из конверта, а не из конфига — см. ADR-PM-021),
   поэтому в `_compose_own_recipe_layer` то же правило зовётся явно.
3. **Политика по дорогам не меняется:** отказывает ровно inline-ручка (имя написано руками, узнать об
   опечатке через час по отсутствию логов дороже, чем сейчас). Все остальные применяют остальное и
   говорят вслух: отказ на них означал бы, что опечатка в machine-owned спутнике валит switch рецепта
   или старт процесса.
4. **Пустой каталог = молчание, а не «всё сироты».** Каталога нет у процесса, которому менеджеров не
   собирали вовсе (тот же случай, что стережёт `layers_are_silent`, ADR-PM-020); сравнение с пустым
   множеством объявило бы опечаткой каждое имя подряд.

**Rejected — «позвать проверку в каждой из трёх веток»:** отвергнуто. Именно так и появился ФР-2:
проверка стояла там, где её написали, и следующая дорога оказалась тихой. Три вызова стали бы четырьмя
на первой же правке, и одна снова была бы забыта.

**Rejected — «проверять внутри `replace_layer` / `apply_observability_layers`»:** отвергнуто. Оба
исполняются на КАЖДОЙ пересборке (её вызывает любая ручка оператора), а слой с опечаткой живёт до
следующего switch'а: одна и та же строка печаталась бы снова и снова, и громкость выродилась бы в фон.
Проверка принадлежит появлению нового тела, а не его применению.

**Rejected — «проверять в `compose_over_base` (шов ещё глубже)»:** отвергнуто. Функция чистая и
каталога имён не имеет; чтобы его получить, пришлось бы протаскивать его параметром через всех
вызывающих — то есть вернуться к «правило у каждой дороги», только длиннее.

**Последствия:**
- Опечатка в спутнике или в дольке рецепта громкая на всех дорогах: у детей — строкой и полем
  `unknown_refs` в ответе `config.reload`, на boot — строкой (отвечать некому), у оркестратора —
  строкой в его журнале.
- Имя, названное однажды, попадает в каталог процесса (`каталог = реестр ∪ конфиг`) и на следующей
  перечитке уже своё — то есть канал-сирота называется один раз на инкарнацию процесса. Свойство
  предсуществующее и одинаковое на всех дорогах; закреплено тестом, потому что иначе читается как
  отказ проверки.
- Ограничение (резидуал, тот же, что назван в ADR-PM-021): L2-watcher оркестратора применяет файл
  спутника к своим менеджерам напрямую (`make_observability_on_reload` с `layer=recipe`), мимо шва
  сборки, — эта дорога остаётся тихой у одного PM. Детям та же правка приезжает рассылкой
  `observability_recipe_reload`, то есть громкой; опечатка не теряется, но названа будет не тем, кто
  применил её первым.

## ADR-PM-023: Пустой словарь в слое наблюдаемости = ВЛАДЕНИЕ, единым примитивом resolve и provenance

**Статус:** принято
**Дата:** 2026-08-02
**Refs:** plans/observability-unified-routing.md (решение владельца на гейте Ф5, Г3;
корзина 2 п.6 / находка A-A4-1), docs/reviews/2026-08-01_f5-cross-review.md, ADR-CRM-006,
Task 5.12

**Контекст:** секция наблюдаемости живёт в четырёх слоях (L0 код → L1 приложение → L2 рецепт
→ L3 сессия), и отсутствие ключа на слое означает наследование нижнего (модель 5.12).
Пустой словарь `{}` под ключом трактовался ДВУМЯ несогласованными способами:

- `resolve` накладывал слои каноническим `deep_merge`, где вложенный `{}` рекурсирует в
  `if not overlay: return base` — то есть no-op, нижний слой побеждает;
- `flatten_section` (на нём стоит `provenance`) считает `{}` ЛИСТОМ — слой владеет.

Итог (A-A4-1, воспроизведено): рецепт с `scopes: {}` поверх `system.yaml` со `scopes.SYSTEM.*` —
`resolve` отдавал scopes из приложения, а `provenance` называл владельцем рецепт. Оператор,
спросив «чей это ключ», получал имя файла, правка которого ничего не меняла.

**Решение владельца (критерий «архитектурно лучше и эффективнее»):** `{}` = **владение**.
Правило целиком: **нет ключа → наследую нижний; ключ есть, что бы в нём ни лежало
(скаляр, список, `{}`, `null`) → владею.** Способ сказать «наследую» в модели уже есть — отсутствие
ключа; если `{}` значил бы то же, было бы два способа сказать одно и ни одного, чтобы сказать
«здесь пусто, и это моё решение» (законная настройка «в этом рецепте приёмников нет»).

**Реализация — ОДИН примитив различения на всю плоскость слоёв (требование владельца):**
1. `layer_merge` (замена `deep_merge` в `resolve`) отличается от канона ровно одним: рекурсия
   только в НЕПУСТОЙ словарь поверх словаря; пустой/скаляр/список/`null` — заменяет (владеет).
   Верхнеуровневый пустой слой по-прежнему наследует (`layers_are_silent`, ADR-PM-020): пустой
   namespace нельзя объявить владением, владеть в нём нечем.
2. `provenance` считается ТЕМ ЖЕ обходом (`_overlay_owner` зеркалит `layer_merge`, листья —
   `(слой, источник)`), а не независимым плющением каждого слоя. Иначе починка одного `resolve`
   создала бы НОВОЕ расхождение: провенанс продолжал бы приписывать затенённый `{}`-ом ключ
   нижнему слою. Теперь resolve и объяснение делят примитив и разойтись не могут.

**Rejected — «глобальный sentinel `MISSING` через канонический `deep_merge`»:** отвергнуто.
`deep_merge` — общий примитив всего проекта (далеко за пределами слоёв); менять его семантику
`{}`/`null` глобально опасно и вне задачи. Плоскости слоёв нужен СВОЙ merge в любом случае
(правило Г3 отличается от канона), поэтому примитив локален для слоёв, а различение «есть
ключ ↔ нет ключа» выражается присутствием ключа (`in`), а не отдельным объектом-часовым.

**Rejected — реализовать в правиле литеральное `null → наследую`:** отвергнуто в этой правке.
Ни `flatten_section`, ни `deep_merge` сегодня так `null` не трактуют (оба — «владеет/лист»), а
слоистая телеметрия требует `publish: null → выключить gate` (ADR соседней правки A-A1-1,
«различим от отсутствия»). Реализация `null→наследую` в `resolve` заставила бы гейт никогда не
видеть `None` → потребовала бы телеметрийного исключения, то есть two-rule split — ровно то, что
Г3 устраняет. Действующее правило «ключ есть → владею» покрывает и `{}`, и `null` согласованно.

**Последствия:**
- `scopes: {}` (и любой `{}`) на верхнем слое перекрывает нижний пустым; `resolve` и `provenance`
  согласованы поkey. Непустой словарь по-прежнему мержится адресно (сосед по ключу не гибнет).
- Отсутствие ключа — единственный способ наследовать; `null` наследованием НЕ является (владеет
  значением `null`). **Поправка 2026-08-02 (ревью корзины 2, находка Ф-8):** формулировка
  решения выше сама себе противоречила — в ней стояло «нет ключа **или `null`** → наследую»,
  тогда как отвергнутая альтернатива и это следствие говорят обратное, и обратное же реализовано.
  Противоречие в ADR опаснее его отсутствия: читатель верит первой строке, а система живёт по
  третьей. Формулировка приведена к реализации.
- Тесты: `test_observability_empty_dict_ownership.py` (8), 5 слом-инъекций по прогнозу, включая
  «истинный откат примитива» (обе стороны сразу) — согласованность resolve↔provenance доказана
  тем, что её слом валит и то, и другое.

---

## ADR-PM-024: непрозрачный лист непрозрачен на ЛЮБОЙ глубине сброса, а не только на точном пути

**Статус:** принято · **Дата:** 2026-08-02
**Refs:** plans/observability-unified-routing.md, docs/reviews/2026-08-01_f5-cross-review.md (находка A-A1-2 + R3b, корзина 2 п.4), `configs/observability_layers.py::_reset_keys_unrecorded` / `session_set` / `_reject_path_inside_opaque`

**Контекст — воскрешение 5.10.g на соседней развилке.** Task 5.10.g объявила
`telemetry.throttle` непрозрачным листом: он хранит правила ПЛОСКИМ словарём, где
имена-паттерны сами содержат точки (`processes.**.state.fps`). Перечислять его по
точкам нельзя — отчёт назвал бы ключи, которых в namespace не существует. Защита была
поставлена на ТОЧНЫЙ путь (`path in OPAQUE_LAYER_PATHS`), а сброс РОДИТЕЛЬСКОЙ ветки —
`config.reload {"observability_reset": ["telemetry"]}` → `session_reset_keys("telemetry")` —
спускался ниже и разрезал лист. Репро: `removed = ('telemetry.throttle.processes.**.state.fps',)`
в отчёте оператору И в записи аудита. Класс — «дефект починен на одном пути из трёх»:
правило было названо, но реализовано у одной развилки из двух.

**Решение.**

1. **Резка ветки узнаёт лист по АБСОЛЮТНОМУ имени.** `flatten_section` получает полный
   префикс пути, поэтому, спускаясь от `telemetry` к `telemetry.throttle`, видит лист как
   один атомарный ключ на любой глубине. Непрозрачность стала свойством ключа, а не
   свойством способа, которым до него дошли.
2. **Вход внутрь листа — громкий отказ (R3b).** `session_set` с дотированным путём
   ВНУТРЬ листа заводил бы в слое вложенное дерево РЯДОМ с настоящим правилом — ровно та
   порча, ради которой лист и объявлен непрозрачным. Production-вызывающих такого пути
   нет (операторские команды кладут дельту троттла листом целиком), но грабля латентна.
   Строгое `startswith(opaque + ".")`: владеть листом целиком по-прежнему можно, запрещён
   только спуск глубже него.

**Отвергнуто.** Перечислять содержимое листа с экранированием точек в именах: это
корень S1 (экранирование плоского namespace), он шире одной находки и стоит дороже —
припаркован как был. Здесь закрыт симптом там, где он воспроизводится, без расширения
скоупа.

**Границы.** Непрозрачность по-прежнему держится списком `OPAQUE_LAYER_PATHS` — то есть
остаётся локальным спецслучаем, а не общим правилом языка путей. Ревью назвало это
оправданной ценой; настоящее лечение — S1.

**Доказательство.** 11 тестов: сброс родителя атомарен в отчёте и в аудите; лист
действительно снят, а не только переименован в отчёте; смешанная ветка перечисляет
`publish` по листьям и держит `throttle` целиком ОДНОЙ операцией; обычная ветка
перечисляется как раньше (регресс); возврат по сроку тоже атомарен; страж R3b с
контрастом «владеть целиком можно» и «после отказа лист не испорчен».

**Слом-инъекции: 2 из 2 совпали — со второго прогона, и расхождение первого записано.**
IA1 (резка ветки не знает абсолютного имени листа) убивает 4 теста, IA2 (страж входа
снят) — 2. Прогноз для IA1 был на 5: я ошибочно ждал смерти
`test_expire_due_of_the_opaque_leaf_is_atomic`. Он выжил, и это верно — `expire_due`
идёт по ТОЧНОМУ истёкшему ключу `telemetry.throttle`, попадает в прежнюю проверку
`path in OPAQUE_LAYER_PATHS` и до спуска по ветке не доходит. То есть этот тест —
регресс 5.10.g, а гарантию настоящего ADR он не сторожит; сторожат четыре остальных.
Ошибка прогноза в безопасную сторону, но записана: молча подогнанное ожидание
превращает инъекцию в ритуал.

**Откат.** Поведение меняется в одну сторону: отчёт и аудит называют лист вместо
несуществующих ключей; `session_set` внутрь листа теперь падает вместо тихой порчи.
Reversible: yes.

---

## ADR-PM-025: подряд идущие одинаковые записи аудита схлопываются в одну со счётчиком

**Статус:** принято · **Дата:** 2026-08-02
**Refs:** plans/observability-unified-routing.md, docs/reviews/2026-08-01_f5-cross-review.md (находка A-A6-1, корзина 2 п.5; закрывает резидуал A3 задачи 5.9), `configs/observability_audit.py::record` / `_same_condition`, `managers/observability_ttl.py::sweep_session_ttl`

**Контекст — залипший отказ прятал истину.** Подметальщик TTL повторяет попытку
пересборки каждый такт (~5 с) и каждый писал свою запись аудита. Кольцо на 100 записей
выедалось за ~8.3 минуты. `session_reverts` и `ttl_report` — выборки из ТОГО ЖЕ кольца,
поэтому в инциденте становились невидимы и авто-возвраты, и авторство ключей: **следствие
вытесняло причину** ровно тогда, когда причина нужнее всего. Репро ревьюера: 1 настоящий
возврат + 100 повторов → `reverts total: 100, real(ok) visible: 0, ACTION_SET visible: 0`.

**Решение.**

1. **Схлопывание живёт в `record`, то есть у единственного писателя** (ADR-PM-016, «один
   писатель аудита»). Любой повторяющийся писатель получает правило даром; будь оно у
   подметальщика, второй такой источник завёл бы вторую копию.
2. **Схлопываются только ПОДРЯД идущие записи.** Разбавленные чужой записью — не одно
   длящееся условие, а история; слить их значило бы переставить её.
3. **Сравниваются ВСЕ поля, кроме принадлежащих самому аудиту** (`seq`, `ts`, `repeats`,
   `last_ts`, `log_failed`). Перечень «значимых» полей пришлось бы держать в аудите — то
   есть аудит знал бы про поля своих писателей, и первое же новое поле схлопывалось бы
   молча. Полное сравнение ошибается в безопасную сторону: лишнее различие схлопывание
   просто прекращает.
4. **Держим ПЕРВОЕ вхождение** (когда условие началось — для длящегося отказа информативно
   именно это) плюс `repeats` и `last_ts`.
5. **`seq` на схлопывании НЕ растёт.** На нём держится `dropped() = seq − len(ring)`:
   посчитай повтор новой записью — и счётчик отрапортовал бы вытеснение, которого не было,
   то есть соврал бы ровно там, где заведён, чтобы не врать.
6. **Подметальщик перестал писать собственную отметку времени.** Поле `at` дублировало
   `ts` самого аудита и делало каждый такт уникальным — схлопывание не сработало бы ни
   разу. Читателей у `at` не было ни одного (проверено grep'ом по репозиторию): снятие
   дубля, а не потеря.

**Цена, названная вслух.** Повтор не пишет строку в журнал процесса — он и есть тот поток
строк, ради которого схлопывание заведено. Первое вхождение объявлено громко; то, что
условие ещё держится, видно счётчиком `repeats` в readback'е `introspect.observability`.
Оператор, читающий ТОЛЬКО журнал, увидит начало отказа и не увидит, что он длится.

**Отвергнуто.** Увеличить кольцо: отодвигает переполнение, но не лечит — залипшее условие
выест любой размер. Отдельное кольцо для отказов: два кольца отвечали бы на один вопрос
по-разному, а вытеснение вернулось бы внутрь нового.

**Доказательство.** 8 юнит-тестов аудита (включая контроли на пере-схлопывание: чужая
запись между повторами прекращает его; другой текст отказа — другое условие; две РАЗНЫЕ
правки одного ключа не слипаются) + 2 теста на ПРОДАКШН-пути через настоящий
`sweep_session_ttl`. Продакшн-путь показал точнее ожидания: отказов остаётся **два**, и это
правильно — первый такт несёт истёкшие ключи («снятие не доехало»), повторы идут с пустыми
(«пересобрать всё ещё не удаётся»), это разные факты. **4/4 слом-инъекции совпали**;
прогноз IB3 поправлен после первого прогона с разбором (частичное схлопывание оставляет
~51 запись, кольцо не переполняется, и два теста про вытеснение остаются зелёными — они
сторожат вытеснение, а не правило). Инъекция IB4 (вернуть `at` подметальщику) убивает
ровно два продакшн-теста при живых юнит-тестах — доказательство, что они проверяют
продакшн-путь, а не обвязку.

**Откат.** Аддитивно: два новых поля в записи (`repeats`, `last_ts`). Reversible: yes.

---

## ADR-PM-026: машинный контекст переопределяется только ЯВНЫМ ключом — правило доведено до уровня ключа

**Статус:** принято · **Дата:** 2026-08-02
**Refs:** plans/observability-unified-routing.md, docs/reviews/2026-08-01_f5-cross-review.md (находка A-A4-2, корзина 2 п.7), ADR-PM-020, `configs/observability_config.py::expand_observability`

**Контекст.** ADR-PM-020 объявил: «молчание слоёв означает „решает нижний“, а не „сбросить
к дефолтам L0“». Но молчание проверялось у СЕКЦИИ целиком (`layers_are_silent`), а внутри
секции правило было реализовано ровно для одного ключа — `log_directory` эмитится, только
если задан явно. `default_level` эмитился ВСЕГДА. Следствие: одного ключа `channels.*` в
любом слое хватало, чтобы секция перестала быть молчащей, материализованный дефолт L0
`INFO` лёг поверх уровня из `INSPECTOR_LOG_LEVEL` — а он к этому моменту уже стоял в базе
(`managers_from_log_dir`). Репро: `merged default_level: INFO (base was DEBUG)`. Класс —
тот же, что ловит вся корзина: правило названо, но живёт на одной развилке из двух.

**Решение.** `default_level` эмитится по тому же правилу, что и `log_directory`: только
когда ключ пришёл явно. «Явно» здесь не выводится из значения — у уровня нет свободного
`None`, каким располагает каталог, — поэтому спрашивается `model_fields_set`: приезжал ли
ключ вообще. Значение, СОВПАВШЕЕ с дефолтом L0, остаётся явным: намерение оператора,
написавшего `INFO` поверх `DEBUG` из окружения, — не то же самое, что молчание (то же
основание, что в ограничении ADR-PM-020).

**Границы, названные честно.** Правило доведено до уровня ключа только для `log_level`.
`errors.level` и `stats.log_level` эмитятся по-прежнему безусловно — и это пока не дефект,
а факт: машинного источника (env) у них нет, `managers_from_log_dir` их не выставляет,
затирать нечего. Появится env-источник — правило придётся распространить, и тогда
разумнее сделать его общим для всей раскладки, а не третьей копией.

**Отвергнуто.** Сделать дефолт `log_level` равным `None` в модели и резолвить ниже: это
меняет тип публичного поля конфига и его читают в нескольких местах — цена больше вопроса.
`model_fields_set` даёт ровно то различие, которого не хватало, и не трогает контракт.

**Доказательство.** 5 тестов: отсутствующий ключ не эмитится; явный доезжает; явный,
равный дефолту L0, считается явным; репро ревьюера на продакшн-форме (overlay поверх базы
из окружения) — уровень выживает; пара к нему — слой, который действительно задаёт
уровень, побеждает. **IC1 (эмитить всегда) убивает ровно 2** — совпало с прогнозом.
**IC2 (не эмитить никогда) убивает 12 при прогнозе 6:** шесть сверх ожидания — стражи
«явный уровень обязан доехать до менеджеров» в тестах verified-смены и раскладки слоёв;
я перечислял утверждения только в двух файлах. Ошибка прогноза в безопасную сторону
(гарантия охраняется шире, чем я знал), записана, а не подогнана.

**Откат.** Поведение меняется в одну сторону: частичный слой перестаёт затирать уровень,
пришедший другим путём. Reversible: yes.


## ADR-PM-027: Каталог метрик наполняется объявлениями, а не литералом (Ф8.1)

**Дата:** 2026-08-06 · **Статус:** принято

**Контекст.** Метрики publisher-gate перечислял кортеж-литерал
`GATED_METRICS = ("fps", "latency_ms", "effective_hz", "cycle_duration_ms", "shm")`
в `configs/telemetry_publish_config.py`. Завести метрику значило править файл
фреймворка — то есть конструктор требовал правки конструктора. Кортеж при этом жил на
два слоя ниже вычисления, и связь «строка каталога ↔ величина» держалась только
совпадением имени.

**Решение.** Метрика объявляется ТАМ, ГДЕ СЧИТАЕТСЯ: `declare_metric()` рядом с кодом.
Четыре собирает `heartbeat/telemetry.py`, `shm` — `process_heartbeat.py`. Каталог
отдаёт `gated_metrics()`.

**Функция, а не константа-снимок.** Реестр наполняется импортом, и снимок, взятый на
импорте `configs/`, застал бы только тех производителей, кто успел импортироваться
раньше, — каталог зависел бы от порядка импортов, ровно от чего реестр и защищает.

**Порядок — сортированный.** Каталог уезжает в readback пульта и в шаблон строк вкладки
«Процессы»; порядок, зависящий от порядка импортов, переставлял бы строки интерфейса от
запуска к запуску.

**Пустой каталог означает «судить не по чему», а не «известных нет».** Пока каталог был
литералом, он существовал всегда; теперь процесс, не считающий телеметрию, видит его
пустым законно. Без этой ветки `unknown_metrics()` объявлял бы опечаткой КАЖДЫЙ ключ.
Ветка не прикрывает настоящий промах — как только импортирован хоть один производитель,
неизвестный ключ снова слышен, и это стережёт отдельный тест.

**Правила-дефолта у метрики нет намеренно.** У лог-источника он есть, потому что модуль
знает про себя «я болтливый». Метрика такого знания не несёт: как часто её публиковать —
решение того, кто собирает систему, и оно живёт в `telemetry.publish` рецепта.

**Резидуал, названный вслух.** GUI строит строки контролов из ИМПОРТА производителей, а
не из readback `introspect_telemetry(process).gated_metrics`. Пять метрик фреймворка
доезжают (GUI импортирует их сам), а метрика, объявленная только в бэкенд-процессе,
строки не получит. До Ф8.1 каталог был литералом и такой развилки не существовало.

**Живая проверка.** `introspect_telemetry("seg").gated_metrics` на прогоне 2026-08-06
вернул все пять имён отсортированными — собранные объявлениями, без литерала.

## ADR-PM-028: Второе правило допуска — плоскость документов, адресуемая конфигом (Ф8.5, итог фазы Ф8)

**Дата:** 2026-08-09 · **Статус:** принято
**Refs:** [plans/observability-unified-routing.md](../../../plans/observability-unified-routing.md) (Task 8.5, 8.4-ADR),
[ADR-CRM-013](../channel_routing_module/DECISIONS.md) (допуск гейтится severity),
[ADR-SS-021](../state_store_module/DECISIONS.md) (троттл считает окна),
[ADR-PM-025](#adr-pm-025-подряд-идущие-одинаковые-записи-аудита-схлопываются-в-одну-со-счётчиком) (схлопывание аудита)

**Контекст.** Долговечное хранилище фреймворка принимало запись по ОДНОМУ правилу — по
важности (`tap` с `min_level="ERROR"`). Правило работает для диагностики и неверно для
записи, чья ценность важностью не выражается: «кто и когда сменил настройку» пишется на
INFO, «деталь N признана браком» — тоже. Такие записи либо не доезжали вовсе (ADR-CRM-013,
воспроизведено), либо жили в ротируемом журнале и умирали за дни вместе с диагностикой.

**Решение — второе правило допуска, выраженное СТРУКТУРНО.** У документа свой приёмник
(`IDocumentSink`, один метод `append(dict) -> bool`) и свой срок хранения per-kind по
ВРЕМЕНИ. Попадание в него от уровня не зависит вовсе — фильтра, который надо не забыть
настроить, здесь нет. Правило одно на оба рода записей: аудит и вердикты — два клиента
одного механизма, а не две дороги.

**Адресация реализации — строкой из конфига, а не импортом.** Фреймворк не имеет права
импортировать `Services` (правило слоёв 9), а живой сток ему нужен: аудит рождается внутри
его процесса. Поэтому конфиг несёт `observability.documents.factory` — import-path, который
фреймворк резолвит `importlib` и зовёт с dict'ом. Канон не новый: так же грузятся класс
процесса (`class_loader`), оркестратор (`orchestrator_class_path`) и приёмники логгера
(`register_sink_factory`). Проверка результата — СТРУКТУРНАЯ (`callable(obj.append)`), а не
`isinstance` протокола: импортировать протокол значило бы отменить всю развилку.

Отвергнуто: generic пер-процессный хук старта (слой ради одного клиента, против ADR-APP-006);
`ServiceRegistry` (хранит классы, а не экземпляры — живой сток из него не достать); переезд
плоскости во фреймворк (втащил бы SQL-стек против правила слоёв).

**Ключ читается из РАЗРЕШЁННЫХ СЛОЁВ, а не отдельным полем `proc_dict`.** Секция
`observability` уже едет к процессу целиком обеими дорогами сборки — boot и switch. Свой
плоский ключ пришлось бы класть в ДВУХ конструкторах ассемблера, и забытый второй дал бы
«дефект на одном пути из трёх»: после горячей смены рецепта плоскость молча исчезала бы.
Побочная выгода — ключ настраивается рецептом (L2) и командой (L3) наравне с уровнем лога.

**Config-owned sink vs runtime-owned подписка — разные вещи, и это решение, а не аналогия.**
Плоскость документов сшивается КОНФИГОМ на старте процесса и живёт, пока живёт процесс:
её адресат — хранилище, у неё нет отправителя, которому можно отказать, и терять её нечем,
кроме отказа БД. Live-хвост наблюдаемости (Ф5.20b, брокер 5.11) — наоборот, RUNTIME-владение:
подписчик приходит и уходит командой, его tap'ы именованы по подписчику и снимаются при
отписке. Слить их в один механизм соблазнительно и неверно: подписка обязана переживать
исчезновение подписчика, а сток — нет; подписка держит порог, у стока порога нет по
построению. Отсюда и разные точки снятия: `unwire_document_sink` зовётся на teardown
процесса, `unwire_observability_forward` — на каждой отписке.

**Сток есть у КАЖДОГО процесса, а не только у пилота hub'а.** Смена конфигурации приходит
куда угодно, поэтому аудит есть везде; hub — только у `worker_module`. Сшивка документов
вынесена из-под условия `hub is not None` осознанно и закреплена тестом на настоящем
`ProcessModule` без воркеров.

**Отказ фабрики — громкий, но не фатальный.** Процесс стартует без плоскости и пишет
WARNING с АДРЕСОМ КЛЮЧА. Молчаливый `sink is None` неотличим от «плоскость не настроена»,
то есть ровно класс «проглоченный сбой», которым фаза и занималась. Правило применено ко
ВСЕМ точкам отказа — их две (не резолвится / резолвится, но не сток); первую редакцию с
адресом в одной из двух нашёл независимый tester.

**Уборка живёт на такте heartbeat, не в своём потоке.** Такт уже идёт в каждом процессе и
уже несёт три хозяйственных дела; четвёртое стоит одного `if`, а поток стоил бы ещё одной
процедуры остановки ради операции раз в час. Срок следующей уборки ставится ДО самой
уборки: иначе отказ БД не обновлял бы дедлайн и превращался бы в поход в неё каждый такт —
сбой стал бы источником нагрузки на то, что уже сломано.

**Цена названа числами.** `append` зовётся СИНХРОННО из пути смены конфигурации. Под
конкуренцией 6 процессов-писателей: медиана 3.6 мс, p95 82 мс, max 928 мс, потерь 0 из 300
(замер воспроизведён дважды). Столько может занять `config.reload`. Терпимо потому, что
документы редки; писателя-посредника поэтому не заводится. Появится клиент с частотой выше
единиц в секунду — бюджет пересчитать.

**Что осталось за границей решения.** (1) Вердикты как второй клиент — задача 8.7; дорога
для них уже есть (`svc.document_sink`), перенос истории `action_log` — решение владельца.
(2) Соответствие словаря OTel остаётся ЗАЯВЛЕННЫМ, а не доказанным: единственная проверка
внешним потребителем (`Services/otel_export`, 8.6) отложена решением владельца 2026-08-06 —
возвращать её имеет смысл, когда появится настоящий приёмник OTLP, а не стенд ради теста.
(3) Неизменяемость документа (хэш-цепочка) — до появления регуляторного требования.

**Живая проверка (webcam_sketch, 2026-08-09).** `config.reload` с `log_level: DEBUG` на
дочернем процессе `seg` и на оркестраторе `ProcessManager` — обе формы доставки конфига;
четыре документа в `data/documents.db`, каждый называет процесс-источник. `journal_mode`
живого файла = `wal`. Рестарт `seg` (pid 24816 → 21168) документы пережили: «когда и где
включили DEBUG» отвечается ЗАПРОСОМ к плоскости, а не grep'ом по журналу. Ротация логов
документ не трогает структурно — файл БД лежит вне каталога логов.

## ADR-PM-029: Вердикт — второй клиент плоскости; дорога приложения это `ctx.write_document` (Ф8.7)

**Дата:** 2026-08-09 · **Статус:** принято
**Refs:** [plans/observability-unified-routing.md](../../../plans/observability-unified-routing.md) (Task 8.7),
[ADR-PM-028](#adr-pm-028-второе-правило-допуска--плоскость-документов-адресуемая-конфигом-ф85-итог-фазы-ф8) (сама плоскость),
[ADR-CRM-013](../channel_routing_module/DECISIONS.md) (допуск гейтится severity)

**Контекст.** Пока клиент один, «плоскость документов» неотличима от «аудит пишет в свою
таблицу»: механизм и его единственное применение выглядят одинаково. Вердикт о качестве
изделия — второй род с другим сроком (десять лет против года), другим писателем (плагин
приложения, а не фреймворк) и другой частотой (событие линии, а не смена конфигурации).

**Решение — одна дорога, `PluginContext.write_document(kind, summary, /, **fields)`.**
Второго механизма не заводится: сток остаётся один на процесс (`svc.document_sink`,
сшивает `wire_document_sink`), а приложение получает к нему доступ через тот же фасад,
которым уже пользуется для логов и health. Заведи приложение свой стор — писателей на файл
стало бы вдвое больше, и «один писатель на процесс» перестало бы быть правдой.

**Четыре решения, принятые по ходу.**

1. **`kind` и `summary` — позиционные (`/`), а не обычные параметры.** Прикладной словарь
   неизвестного состава — обычный способ звать эту дорогу (`write_document(KIND, s,
   **payload)`). С обычными параметрами ключ `kind` в нагрузке давал бы `TypeError`
   «got multiple values», то есть вердикт терялся бы ИСКЛЮЧЕНИЕМ на линии — хуже подмены,
   от которой защита (конверт кладётся после `**fields`) и ставилась. Найдено собственным
   тестом конверта: защита была верной, а её обход — недостижимым. `source`/`ts` оставлены
   именованными: одноимённый ключ нагрузки означает ровно их.
2. **Сборка конверта — внутри `try`.** `float(ts)` применяется к значению, пришедшему от
   приложения. Мусор в нём обязан стоить документа, а не линии.
3. **Отсутствие плоскости и отказ записи отвечают ОДИНАКОВО (`False`).** Разные формы
   отказа заставили бы клиента знать, в каком контексте он живёт. Различие возвращено там,
   где оно наблюдаемо: у ненастроенной плоскости отказов не бывает вовсе, а у настроенной
   каждый посчитан стоком (`dropped`) и назван строкой журнала.
4. **`SubPluginContext` получает `write_document` полем, а не наследованием.** Своей
   плоскости у вложенного контекста нет и быть не должно — сток это ресурс процесса.
   Дефолт отказывает; родитель пробрасывает свою дорогу явно. Без поля sub-плагин падал бы
   `AttributeError` в момент вынесения вердикта, то есть на самом дорогом пути.

**Вердикт пишется на ФРОНТЕ решения, а не на каждом кадре брака.** Дефектное изделие видно
детектору десятки кадров подряд, а `append` синхронный (медиана 3.6 мс, max 928 мс) при
бюджете кадра 16–40 мс на 25–60 FPS. Документ на каждый кадр остановил бы линию и дал бы
вместо одного решения десятки строк об одном и том же. Живой прогон подтвердил цену
буквально: **95 кадров брака → 1 документ**.

**Чего у вердикта честно нет.** Идентификатора изделия: конвейер его не несёт. `reject_seq`
— порядковый номер отбраковки в этом запуске процесса, а не номер детали, и живёт он
столько же, сколько процесс. Per-part traceability уровня MES требует внешнего
идентификатора и в объём задачи не входила. Поэтому «вердикт о качестве» здесь означает
«решение линии с порогом, по которому оно вынесено», а не «паспорт детали».

**Живая проверка (inspection_full, 2026-08-09).** 3163 инспекции, 95 отбраковок,
`verdicts_written=1`, `verdicts_unwritten=0` — через `get_stats`, то есть путь наружу
существует. В `data/documents.db` рядом с четырьмя документами аудита лежит один
`kind=verdict` с `source=robot_control` и порогом решения в payload; после смерти всех
процессов он на месте. Дефект рецепта, вскрытый этим же прогоном: маршрута
`processor→inspector` на уровне процессов не существовало при объявленном проводе портов —
`RobotControlPlugin.process` не вызывался НИ РАЗУ (`total_inspected=0` при 1772 принятых
сообщениях), и об этом никто не говорил ни строчкой.

---

## ADR-PM-030: `log_error` — строка, `health.report_error` — инцидент; вторая половина сделана правдой (C2)

**Дата:** 2026-08-09 · **Статус:** принято · **Основание:** major-1 приёмочного ревью
2026-08-09, план `plans/observability-review-remediation.md` (Task C2)

### Контекст

У плагина три дороги, которые на call-site выглядят взаимозаменяемо:
`ctx.log_error(str)`, `ctx.health.report_error(exc)` и — у фреймворковых менеджеров —
`_track_error(exc)`. Ревью считало, что первая ведёт в logger-маршрут (верно), а в файлы
`critical/errors/warnings` ведёт вторая.

**Прогон опроверг вторую половину.** `backend_ctl/probes/probe_c2_error_route.py` поднимает
настоящие `LoggerManager` и `ErrorManager` в свежий каталог и ищет маркеры по всем файлам:

```
ctx.log_error            → ['system.log']
ctx.health.report_error  → ['system.log']      ← НЕ плоскость ошибок
services.track_error     → ['errors.log']
```

`HealthState.report_error` писал через `services.log_warning` (см. `_resolve_log`), то есть
уходил в плоскость логов. Единственной дорогой в плоскость ошибок оставался `_track_error`,
которого у `PluginContext` нет вовсе. Итог: **плагин не мог попасть в плоскость ошибок
никак**, а `report_error` было названием без обязательства — ровно класс «названный
механизм ≠ обязательство».

### Решение

Вариант «б» задачи C2 — фасад разводит намерения ЯВНО, — но со второй половиной,
приведённой в соответствие с именем:

| Разъём | Смысл | Куда едет |
|---|---|---|
| `ctx.log_debug/info/warning/error/critical(str)` | диагностическая **строка** | плоскость логов |
| `ctx.health.report_error(exc, context=…)` | **инцидент** | плоскость ошибок **+** дросселированная строка в журнал **+** счётчик health/breaker |
| `ctx.write_document(kind, …)` | **решение** (вердикт, аудит) | плоскость документов |

`HealthState` получил зависимость `track` (резолв — `services.track_error` /
`_track_error`, тем же приёмом, что `log`). Инцидент отдаётся плоскости ошибок **под тем
же дросселем**, что и строка журнала (`throttle`, дефолт 5 с на пару «тип исключения +
контекст»), а счётчик health считает ВСЕ вызовы — число не теряется.

### Отвергнуто

- **Вариант «а» — дублировать `ctx.log_error` в error-маршрут.** Диагностическая строка
  («парсер не понял кадр») стала бы инцидентом, и плоскость ошибок, которая сегодня пуста,
  превратилась бы в копию `system.log`. Смысл отдельной плоскости — «инцидент», а не
  «строка с уровнем ERROR».
- **Отдавать инцидент без дросселя.** Проглоченное исключение в горячем цикле — типовой
  сайт `report_error`; «пишем каждое» сделало бы журнал инцидентов потоком. Честность
  числа обеспечивает счётчик, а не одна запись на вызов.
- **Переименовать `ctx.log_error`.** Правка call-sites плагинов вне скоупа задачи, а
  проксирование имён (`__getattr__`) превращает опечатку в молчаливый no-op (ADR-PM-029,
  тот же довод, что у явной пятёрки `log_*`).

### Последствия

- Плоскость ошибок перестаёт быть пустой по построению: `errors.log` начинает получать
  инциденты плагинов. Объём — дросселированный, но **ретеншен корневых файлов плоскости
  ошибок остаётся слепой зоной** (задача D5 плана), и это названо здесь, а не обнаружено
  потом.
- Тесты судят **маршрут** (какая плоскость приняла), а не имя вызванного метода:
  `modules/process_module/tests/test_error_route.py`, дубли плоскостей — РАЗНЫЕ объекты,
  иначе маршрут неразличим.
- Прогон-доказательство остаётся в репозитории и перезапускается:
  `python -m backend_ctl.probes.probe_c2_error_route`.

## ADR-PM-031: имя ключа наблюдаемости судится на границе слоя — но только у ручки оператора

**Статус:** принято
**Дата:** 2026-08-12
**Refs:** plans/observability-roadmap.md (задача 5.4), docs/reviews/2026-08-12_observability-acceptance-f2.md
(находки Н-C/Н-D), ADR-PM-022, мерило 2 плана

**Контекст:** до этой задачи `validate_layer_section` судила ЗНАЧЕНИЯ объявленных ключей, а ИМЕНА
отдавала вердикту `config.reload` (`unknown_keys` → `verdict=failed`). Довод был записан в её
докстринге и звучал разумно: «второй предохранитель на то же место сделал бы неизвестным, который
из них держит». Приёмка F2 показала цену этого разделения на живом стенде:

```
config.reload {"observability": {"logger": {"default_level": "DEBUG"}}}
→ success=true
  session_keys=['logger.default_level']    # лёг в L3 и съел срок
  effective.logger.default_level='INFO'    # и НЕ действует
  verified={'verdict': 'failed', 'unknown_keys': ['logger.default_level']}
```

Ответ противоречил себе: верхнеуровневый `success` и вложенный вердикт в одном payload говорили
разное, а оператор читает `success`. Мерило 2 плана требует буквально: «`success` ⇔ валидно,
сохранено, действует; мусор любого рода (значение, тип, **ключ**) — адресный отказ».

**Решение:**

1. Имена судит тот же страж границы (`unknown_section_keys` внутри `validate_layer_section`), и
   отказывает он **только у слоя `session`** — то есть у ручки оператора: `config.reload` inline и
   `session_set`. Это не второй предохранитель на то же место: значение и имя — разные свойства, и
   держит их одна функция в одной точке.
2. Файл, рецепт, спутник и конверт switch'а **не отвергаются**. Политика и довод — те же, что у
   ссылок без приёмника (ADR-PM-022): отказ означал бы, что опечатка в спутнике валит switch рецепта
   или старт процесса. Их голос — запись аудита `unknown_keys` (кладёт `replace_layer` — одно место
   на все пять файловых дорог) и строка журнала «ВНЕ КОНТРАКТА (ключ есть, эффекта нет)».
3. Механизм ОДИН на две дороги: `observability_verified` теперь зовёт ту же `unknown_section_keys`,
   а не свою копию round-trip'а. Две копии разошлись бы на первом же новом поле схемы, и
   «неизвестный ключ» значило бы разное на границе и в вердикте.

**Отвергнутые варианты:**

- **Отказывать на всех слоях.** Симметрично и заманчиво, но опечатка в machine-owned спутнике
  (его пишет `observability.persist`) валила бы switch рецепта — то есть цена ошибки оператора
  переносилась бы на конвейер. Инъекция I2 проверяет, что этого нет.
- **Оставить имена вердикту и лишь громче показать `verified`.** Не закрывает мерило 2: ключ всё
  равно оседает в L3, съедает срок и не действует, а `success` продолжает означать «команда не
  упала». Разница «команда сломалась» / «команда ничего не изменила» сохранена иначе: отказ вообще
  не несёт `verified` — применять было нечего.
- **Своя таблица известных имён.** Разошлась бы со схемой на первом новом поле; round-trip через ту
  же схему, из которой считается раскладка, разойтись не может по построению.

**Названная цена и две ловушки механизма** (обе воспроизведены ДО правки и обе давали ложное «имя
незнакомо» ещё в вердикте 5.7 — то есть с отказом на границе стали бы отказом ЗАКОННОЙ правке):

- ключ `telemetry` схема наблюдаемости не знает вовсе (его содержимое судит
  `validate_telemetry_section`) — снимается до сверки. Пробел покрытия на файловой двери вскрыла
  инъекция I3: там сверщик получает тело СЫРЫМ, и без снятия объявил бы «вне контракта» каждый путь
  телеметрии;
- имя скоупа схема приводит к верхнему регистру (`scopes.system` → `SYSTEM`). Правило вынесено в
  `canonical_scope_keys` и зовётся из ОБОИХ мест (схема и сверщик), а не копируется.
- Живая цена ручки: `enable_batching` и соседи (снятые ключи батчинга) через ручку оператора теперь
  получают отказ, а не `emergency_log`-предупреждение. Для файла поведение прежнее.

**Последствия:**

- `unknown_keys` в вердикте остаётся достижимым — но только с файловой дороги, где отказа нет. Слой
  вердикта не стал мёртвым: инъекция I1 краснит 17 тестов, I7 (своя копия расчёта) — 3.
- Доказательства перезапускаются: `multiprocess_framework/modules/process_module/tests/test_layer_unknown_keys.py`
  (132 зелёных на предмете) и живой зонд `python -m backend_ctl.probes.probe_5_4_unknown_key_live`
  (22 проверки на двух адресатах: ребёнок через дорогу ПМ→роутер→процесс и сам оркестратор).
  Зонд снят красным под инъекцией I1 на боевом стенде: 14 красных из 22, ровно предсказанных.
- Прогон против боевых конфигов показал **0 ключей вне контракта** в `system.yaml` и во всех 17
  рецептах, то есть новый голос молчит на здоровой системе, а не шумит.


## ADR-PM-032: прицельная подписка на хвост сильнее оптовой, и намерение едет на проводе

**Статус:** принято
**Дата:** 2026-08-12
**Refs:** plans/observability-roadmap.md (задача 5.6), docs/reviews/2026-08-12_observability-acceptance-f2-round2.md
(блокер Н2-1, находка Н2-2), ADR-PMM-024, мерило 1 плана

**Контекст.** Подписка на живой хвост — форвардер на каждом процессе, per-subscriber. Оптовую
команду (`observability.tail.subscribe_all`) брокер оркестратора разворачивает в те же самые адресные
`observability.tail.subscribe`, поэтому процесс не мог отличить «оператор просит ЭТОТ процесс на INFO»
от «оператор просит ВСЕХ на WARNING». Побеждала последняя воля — молча:

```
subscribe(camera_0, INFO)     -> 31 запись {info}
subscribe_all(WARNING)        -> 0 записей info, {error: 6}
обратный порядок              -> 35 записей {info}       # то есть дело в порядке, а не в правиле
манифест export_subscriptions -> продолжает обещать INFO
```

Зеркальная половина (Н2-2): оптовое СНЯТИЕ (`unwatch` драйвера ходит `untail_all`) сносило прицельную
подписку, которой не создавало — воспроизведено с профилем, ни разу не включённым: 28 записей → 28.

**Решение владельца 2026-08-12 — объединение** по мерилу 1 («подписчик с level=INFO получает INFO от
каждого процесса»). Реализовано двумя частями:

1. **Намерение едет на проводе:** брокер помечает свою раздачу `scope="all"` (и подписку, и снятие, и
   адресный replay свежей инкарнации — брокер по построению держит только оптовые намерения).
   Поле объявлено в контрактах команд: при `extra="forbid"` незаявленный ключ дал бы
   `contract_violation` на каждой раздаче, а под `FW_CONTRACTS_STRICT=1` — молча дропнутое сообщение.
2. **Процесс помнит, чем задан порог** (`_observability_tail_intents`: уровень + `targeted`).
   Оптовая раздача не понижает прицельный порог и ГОВОРИТ об этом (`kept_level` / `ignored_level` /
   `reason`); оптовое снятие не трогает прицельную подписку (`removed=False`, `kept_targeted=True`).
   Понизить или снять прицельную можно тем же жестом, которым её задавали, — прицельной командой.

**Отвергнутые варианты.**

- **«Берём самый громкий порог всегда» (min по уровням).** Проще на вид, но ломает зеркально:
  оператор перестаёт уметь сделать тише тем же жестом, каким сделал громче. Пара-тест на это стоит.
- **«Последняя воля побеждает, но ГРОМКО»** (только назвать смену уровня в ответе и в манифесте).
  Вдвое дешевле, лечит молчание — но не лечит мерило 1: подписчик, объявивший INFO, продолжал бы
  получать WARNING. Названо владельцу как вариант и отвергнуто им.
- **«Одна дверь»: отклонять второго клиента** (рекомендация припаркованного плана
  `backend-ctl-review-remediation` Task 3.2) — отвергнута тем же разбором, что в ADR-PMM-026:
  ломает HTTP-мультиклиент и саму приёмку.

**Названная цена.** Атрибут намерений объявлен на уровне КЛАССА (как `document_sink`): процесс
собирают не только через `__init__` (оркестратор, тестовые стенды через `__new__`), и объявление
только в конструкторе давало бы `AttributeError` вместо работы — это вскрылось прогоном, а не чтением.
Мутаций на месте нет ни одной (только атомарный rebind), поэтому общий классовый словарь не может
стать общим состоянием двух процессов.

**Последствия.**

- Доказательства перезапускаются: `python -m backend_ctl.probes.probe_5_6_subscription_union_live`
  (6 проверок; INFO-записи 25 → 51 → 77 сквозь оптовую WARNING и оптовое снятие, при том что
  прицельное понижение и прицельное снятие гасят их насмерть) + 8 юнитов.
- **Инъекция K4 вскрыла вакуум:** снятие чтения `scope` в хендлере не красило НИ ОДНОГО теста —
  механизм был покрыт, маркер брокера покрыт, а шов между ними нет. Блокер мог вернуться молча;
  страж шва добавлен (`test_scope_all_on_the_wire_reaches_the_process_as_wholesale`).
- Побочно закрыт корень находки Н2-6: «флейк» проверки I4 зонда 5.5 был этим самым дефектом —
  `unwatch()` глушил прицельный хвост, который I4 и мерила.

## ADR-PM-033: stats-разъём плагина — четвёрка `StatsManager` дословно, и ни одного нового написания

**Статус:** принято
**Дата:** 2026-08-12
**Refs:** plans/telemetry-stage6.md (задача 1.1, этап 6 roadmap), вход C1/Ф8.3 (решение Р-2в),
ADR-PM-029 (дорога документов — образец порта), Н-6/Н-9 (уроки суб-контекста и объявления порта)

**Контекст.** Плоскость stats существовала целиком, кроме одного: **эмитента**. `StatsManager` с
окном агрегации, дорога `KIND_STATS` из hub'а в стор и хвост, вкладка «Статистика» — всё живое, а в
`IProcessServices`/`PluginContext` stats-методов не было ни одного, и 0 из ~30 плагинов могли отдать
бизнес-число. Мерило этапа 6 — «плагин отдаёт бизнес-метрику тем же жестом, что лог».

**Решение.** Узкий протокол `IPluginStatsManager` (четвёрка `record_metric`/`gauge`/`record_timing`/
`histogram`), порт `stats_manager` в `IProcessServices`, четыре метода на `PluginContext` и
`SubPluginContext`. Три вещи решены явно:

1. **Сигнатуры дословны `StatsManager`, включая единицы.** Не стиль: имя `record_metric` уже живёт в
   проекте с ДВУМЯ противоположными смыслами — у `StatsManager`/`ObservableMixin` это counter, у
   `ObservabilityHub._emit_stat` — **gauge, то есть перезапись**. Третье написание сделало бы
   расхождение вопросом времени. Совпадение сторожит не `isinstance` (у `runtime_checkable`-протокола
   он проверяет только имена и перестановку аргументов пропустил бы молча), а контракт-тест по
   `inspect.signature` против настоящего менеджера.
2. **Единица `record_timing` — СЕКУНДЫ.** Соблазн миллисекунд назван здесь потому, что тестом он не
   падает: агрегат собрался бы, а границы бакетов задачи 2.2 сложили бы все кадровые тайминги в
   первый бакет — p95 стал бы константой при зелёном прогоне. Судится числом, где единицы расходятся
   в тысячу раз (1/60 с), и читается из настоящего `StatsManager`.
3. **Ненастроенная плоскость слышима.** Возврата у метрики нет (сигнатура дословна), поэтому счётчик
   `stats.without_plane` + однократный WARNING с именем метрики и источником — её ЕДИНСТВЕННЫЙ канал
   наблюдаемости. Число выходит наружу секцией `stats` команды `introspect.observability`: у
   документов рядом есть `False`, здесь его нет, и «тихо вернули» было бы полной слепотой.

**Штамп источника.** Метрика автоматически получает тег `plugin` по имени плагина (явный тег
call-site выигрывает — та же лесенка, что у `module=` в логах). Без него две серии `frames_processed`
разных плагинов одного процесса сливаются в одну, и разошедшиеся числа выглядят как одно
правдоподобное.

**Отвергнутые варианты.**

- **Пятый аргумент `metric_type="counter"`** вместо четырёх методов — тот же выбор в двух написаниях;
  ровно так и разошлось значение имени `record_metric`. Сторожится тестом «в сигнатурах нет
  `metric_type`».
- **Второй алиас порта** (`ctx.stats`, отдельный атрибут процесса) — два имени одной дороги. Порт —
  существующий `stats_manager` процесса.
- **Писать из фасада прямо в `ObservabilityHub`**, минуя окно, — шторм стора: метрика на кадр при
  30 fps даёт строку на эмиссию, агрегация теряется. Дорога доставки — задача 2.1, и она идёт через
  снапшот окна.
- **Проксирование `__getattr__`** вместо явной четвёрки — делает ЛЮБОЕ имя существующим, то есть
  превращает опечатку в молчаливый no-op (довод уже записан у пятёрки `log_*`).

**Названная цена — числом.** Фасад добавляет **0.31–0.38 мкс** к прямому вызову менеджера с тем же
тегом (замер `TestTheCostOfTheHotPath`, 20 000 повторов, gc выключен на окно, вперемежку). Для
сравнения: отклонённая запись лога — 0.26–0.35 мкс. Отдельно измерено и названо: сам **тег** стоит
+1.15 мкс внутри `StatsManager` (мерено прямым вызовом, без фасада) — это работа с тегами в
`_merged_tags`/`_ensure_record`, не в разъёме, и она — вход для пределов задачи 2.2, а не долг 1.1.

**Последствия.**

- 33 теста (`tests/test_plugin_stats_road.py`), 10 инъекций с предсказанием: 9 совпали точно, №1
  («порт снят из протокола») дала 6 красных вместо предсказанных 2 — переименование свойства завело
  в протокол НОВОГО члена, и три проверки `isinstance` покраснели по артефакту инъекции, а не по
  сломанной гарантии. Инъекция была грубее задуманного; предсказанные два красных при этом сработали.
- Дубль `MockStatsManager` умеет отказывать (`raises=`): дубль-всегда-успех сделал бы путь «сбой
  учёта» непроверяемым, а различить его можно только по тому, что фасад сказал в журнал.
- Доставка `kind=stats` в стор и хвост здесь **не делается** — это задача 2.1 плана.

**Находка независимого тестера (42 теста от критериев приёмки, без диффа) — и она подтверждает
правило.** Заглушки `SubPluginContext` без родителя были поставлены ОДНОЙ функцией
`_noop_stat(name, value=1, tags=None)` с доводом «сигнатуры совпадают по форме». Довод неверен: у
`StatsManager` параметр таймингов зовётся `duration`, а у `gauge`/`histogram` значение обязательно и
дефолта не имеет. Плагин, звавший по эталонной сигнатуре, получал:

```
SubPluginContext().record_timing("frame", duration=0.016)
TypeError: _noop_stat() got an unexpected keyword argument 'duration'
```

То есть заглушка, поставленная РАДИ безопасности вызова без родителя, сама роняла линию. Тест автора
рядом звал заглушку **позиционно** и оставался зелёным — он подтверждал согласие автора с
собственной моделью, а не с контрактом. Исправлено четырьмя заглушками с дословными сигнатурами;
добавлены два стража (оракул сигнатур поверх дефолтов суб-контекста + вызов именованными
аргументами), инъекция «вернуть прежнюю форму» красит 4 теста поимённо — 2 авторских и 2 тестера.

---

## ADR-PM-034: под-секция телеметрии без исполнителя — отказ у ручки оператора, голос у файла

**Статус:** принято
**Дата:** 2026-08-14
**Refs:** plans/telemetry-stage6.md (задача 3.1, Ф3), ADR-PM-031 (прецедент «разный ответ по месту»),
ADR-PM-022 (ссылки без приёмника), `managers/observability_reload.py::telemetry_unaddressable`

**Контекст.** У секции `telemetry` две под-секции с РАЗНЫМИ исполнителями: `publish` применяет
`ProcessHeartbeat` (есть у каждого процесса), `throttle` — центральный `ThrottleMiddleware`, который
живёт только на оркестраторе (`resolve_store_throttle` отдаёт не-None лишь там). Присланная обычному
ребёнку под-секция `throttle` вела себя так:

```
camera_0 ← telemetry.reconfigure {"throttle": {"a.b": 1.0}}
→ success=true                       # оператор читает «команда прошла»
  applied={"throttle": false}        # …а применения не было
  session_keys=['telemetry.throttle']# слот L3 занят, дефолтный срок 300 с тикает
  правило не действует никогда
```

Ровно тот же класс, что закрыла ADR-PM-031 для имён ключей: `success` означал «команда не упала», а
не «сохранено и действует». Мерило то же — `success` ⇔ валидно, сохранено, действует.

**Решение.**

1. **Отказ ставится у ДВЕРИ сессии на адресате, и ответ разный по месту** — та же политика и тот же
   довод, что у ADR-PM-031 и ADR-PM-022:
   - `source == "inline"` (ручка оператора: `telemetry.reconfigure`, `config.reload` с inline-секцией)
     → `success=false`, `reason` называет АДРЕС («…адресуйте под-секцию процессу ProcessManager»),
     поле `telemetry_no_receiver`, и всё это **до первой записи в слой**;
   - **файл** (`config.reload` с `path` / `observability_config_path`) → применить остальное и
     сказать вслух (`telemetry_no_receiver` в ответе + строка журнала). Отказ здесь валил бы
     `config.reload` у КАЖДОГО ребёнка из-за строки `telemetry.throttle` в общем `system.yaml`, где
     она совершенно законна: её адресат — оркестратор, а читают файл все.
   - **рецепт / switch / L1-watcher голоса НЕ получили** — см. «Известный долг» ниже. Первая
     редакция этого ADR перечисляла их здесь наравне с файлом; ревью воспроизвело обратное, и
     формулировка сужена до дорог, которые страж действительно закрывает.
2. **Отказ целый, а не частичный.** Приехали обе под-секции, применима одна → отказ целиком.
   Частичное применение оставило бы состояние, изменённое командой, которая ответила «отказ»:
   откатывать нечего, и оператор не знает, что уехало. «Состояние не изменилось» обязано быть
   правдой без оговорок — иначе inline-половина правила не стоит ничего.
3. **Владение плоскостью захватывает тот, кто применил.** `layers.throttle_owned = True` переехало
   ЗА проверку получателя в `_apply_throttle_from_layers`. Прежде владение бралось по одному факту
   «в слое лежит dict», то есть раньше, чем выяснялось, что применять некому. Флаг ЛИПКИЙ: захватив
   его, слои владеют плоскостью навсегда, и истечение срока начинало бы «возвращать к загрузочным
   правилам» на процессе, где правил не было. Честный текст ответа этого не чинит — слот остался бы
   занятым, поэтому правка обязана была тронуть само присвоение.
4. **Место стража — дверь, а не применение.** Через ДВЕРИ КОМАНД телеметрия въезжает в слой тремя
   путями: `telemetry.reconfigure` и `config.reload` с одной телеметрией идут через
   `_apply_telemetry_section`, а `config.reload` с секцией `observability` рядом зовёт
   `_merge_telemetry_layer` напрямую, мимо неё. (Всего дорог в слой больше трёх — остальные
   перечислены в «Известном долге»; страж закрывает командные.)
   Страж внутри `_apply_telemetry_section` закрыл бы
   две дороги из трёх, и «отказ зависит от того, приехала ли рядом секция observability» воскрес бы
   там же, где уже воскресала проверка `telemetry_mode` (замечание 2 ревью 5.10). Поэтому проверка
   стоит рядом с `validate_telemetry_section` — там, где секция окончательно собрана (inline либо
   файл + per-process overlay) и где ещё ничего не записано.

**Ветка `publish` при `heartbeat is None` — покрыта тем же правилом, а не объявлена недостижимой.**
`_apply_telemetry_from_layers` возвращает `applied or None`, то есть при отсутствии heartbeat publish
тоже молча не применяется. В проде heartbeat строится безусловно (`process_module.py:973`), и на этом
основании ветку можно было бы объявить мёртвой — но воспроизведения «heartbeat не бывает None» у нас
нет, а `_heartbeat = None` уже используется как легитимное состояние сервиса в тестовых харнессах
(`test_observability_ttl._Svc`). Аргумент «в конструкторе создаётся безусловно» — это чтение кода
конструктора, а не наблюдаемое поведение обработчика команды, и он перестанет быть верным в тот день,
когда heartbeat станет опциональным (например, у процесса без телеметрии вовсе). Поэтому симметрия
сделана буквальной: нет исполнителя — не успех, для обеих под-секций одинаково. Цена решения названа:
на процессе без heartbeat команда `telemetry.reconfigure {"publish": …}` теперь отказывает, тогда как
раньше отвечала `success=true` ни с чем.

**Известный долг: рецепт, switch и L1-watcher въезжают в слой молча.** Найдено ревью задачи, с
воспроизведением, и записано здесь, а не замолчано. Кроме командных дорог, телеметрия попадает в слой
ещё через `replace_layer(LAYER_RECIPE)` из конверта switch'а, через перечитку спутника
(`observability_recipe_reload`) и через `replace_layer(LAYER_APP)` L1-watcher'а. Там голоса нет:

```
camera_0 ← config.reload {"observability_recipe": {"defaults": {"telemetry": {"throttle": {"a.b": 7.0}}}},
                          "observability_recipe_path": "…"}
→ success=true, telemetry_applied={'throttle': False}
  telemetry_no_receiver — поля НЕТ,  _log_error — пусто,  throttle_owned=False
```

Поведение не ухудшилось (прежний ответ `applied.throttle=False` на этой дороге сохранён), поэтому
долг, а не регрессия. Цена реальная: `defaults` рецепта по решению Р1 ИСКЛЮЧАЕТ оркестратора, то есть
`defaults.telemetry.throttle` доедет ровно до процессов, которые применить его не могут, и ни до
одного, который может. Закрывать это следует ОДНИМ местом — `_apply_telemetry_from_layers`, где
сходятся все дороги, — а не четвёртой копией стража у четвёртой двери; отдельной задачей, потому что
у watcher'а нет ответа, куда положить голос, и ему нужен свой носитель (запись аудита с `applied`).

**Отвергнутые варианты.**

- **Оставить `applied={"throttle": false}` и лишь громче документировать.** Не закрывает мерило:
  ключ всё равно оседает в L3, съедает срок и не действует, а `success` продолжает означать
  «команда не упала». Ровно тот довод, по которому этот вариант отвергнут в ADR-PM-031.
- **Отказывать на всех дорогах, включая файловую.** Симметрично, но строка `telemetry.throttle` в
  общем `system.yaml` валила бы `config.reload` на каждом ребёнке — цена конфигурации, законной для
  оркестратора, переносилась бы на всех соседей.
- **Проверять получателя внутри `_apply_telemetry_section` (единая точка применения).** Короче на
  один вызов, но закрывает две дороги из трёх: третья (`config.reload` с секцией observability)
  вливает телеметрию в слой мимо неё. Пара `test_reload_with_observability_alongside_still_refuses`
  краснеет именно при таком размещении.
- **Частичное применение с голосом на inline-двери.** Отвергнуто в п.2: команда, ответившая
  «отказ», не имеет права оставить половину применённой.

**Проверено.** Приёмка независимого тестера — `tests/test_telemetry_no_receiver_acceptance.py`
(9 тестов, до правки 5 красных / 4 зелёных, после — 9 зелёных; файл автором не правился). Опасности
механизма — `tests/test_telemetry_no_receiver_hazards.py` (14 тестов). Две инъекции с предсказанием,
обе совпали поимённо: снятие стражей у дверей → 8 красных из 14 (6 зелёных — три контроля
«получатель есть» и три проверки чистого резолвера); возврат прежнего порядка присвоения
`throttle_owned` → ровно 1 красный
(`test_telemetry_layers::test_file_road_does_not_capture_ownership_without_a_receiver`).
Корпус `process_module`: 1939 собрано / 1934 прошло до правки → 1954 собрано / 1954 прошло после.
Весь фреймворк: 8062 passed, 8 skipped.

Отдельно — восемь инъекций владельца по корпусу из 4 файлов (база 60 собрано / 60 зелёных),
предсказания записаны до прогонов, шесть первых совпали поимённо: снять inline-отказ у
`telemetry.reconfigure` → 10; снять его у `config.reload` → 4; вернуть прежний порядок
`throttle_owned` → 1; убрать голос на файловой дороге → 1; обезличить адрес в `reason` → 3;
отказывать и на файловой дороге → 1. Седьмая (срок ставится всем ключам сессии) предсказание
НЕ подтвердила — покраснел не авторский `test_refusal_neither_refreshes_nor_drops_a_neighbours_ttl`,
а существующий `test_merge_does_not_extend_the_deadline_of_foreign_keys`; восьмая (пара «страж снят
+ срок всем ключам») показала, что авторский тест не вакуумен, а сторожит КОМПОЗИЦИЮ и краснеет
только от двух изломов сразу. Разбор записан в его докстринге, тест оставлен.

Живая приёмка — `backend_ctl/probes/probe_3_1_no_receiver_live.py` (11 проверок, контрольная пара
`camera_0` / `ProcessManager`). Зелёный на стенде; под инъекцией «оба стража двери сняты» с
перезапуском `camera_0` — 6 красных (P1, P1b, P2, P3, P3b, P6), ровно предсказанные. До правки на
том же стенде: `camera_0` → `success=true, applied.throttle=false, ttl_sec=300.0,
survives_reload=true`; после — `success=false` с адресом и `session_keys` без `telemetry.throttle`.

## ADR-PM-035: опрос уровней — расширение существующей команды, а не пятнадцатая

**Статус:** принято
**Дата:** 2026-08-14
**Refs:** plans/telemetry-stage6.md (задача 3.2, Ф3, развилка РТ-3), ADR-PM-018 (publisher-гейт),
ADR-136 (read-model телеметрии у потребителя), ADR-PM-016 (`tick_sec` — частота публикации),
`heartbeat/process_heartbeat.py::current_levels_snapshot`, `heartbeat/telemetry.py::build_router_shm_telemetry`

**Контекст.** Уровни («сколько СЕЙЧАС»: fps, latency_ms, частота воркера) процесс считает на
каждый тик и **отдаёт только push'ем** в дерево состояния. Пока publisher-гейт открыт, числа
видны; закрой его — и единственный способ узнать значение исчезает вместе с трафиком. Требование
владельца формулирует это прямо: «любая телеметрия должна работать при опросе… а до этого — просто
записывать у себя в памяти, в самом процессе». Первая половина уже была правдой (сборщик считает
на каждый тик), вторая — нет: спросить процесс было нечем.

Закрытое окно GUI при этом даёт ноль наблюдателей и полный push-трафик — это и есть цена, ради
которой заводится опрос (главный приз меряется в 3.3).

**Решение.**

1. **Расширить `introspect.telemetry` двумя секциями — `levels` и `snapshot_ts` — вместо новой
   команды `telemetry.pull`** (развилка РТ-3, вариант (а)). Имя `telemetry.pull` чище, но это
   +1 команда к четырнадцати существующим против правила Б.1 «телеметрия не заводит новой двери»,
   и обе команды отвечали бы про одну подсистему разным адресом. Секции уже существующей команды
   отвечают «что публикуется» — «сколько сейчас» встаёт рядом естественно. Цена варианта (б)
   записана и остаётся доступной, если (а) окажется тесным.

2. **Снимок собирается ТЕМ ЖЕ сборщиком, что тик публикации, с `allowed_metrics=None`.**
   Publisher-гейт — про push, а не про то, что процесс знает о себе. Обратное («опрос показывает
   только разрешённое к публикации») сделало бы поле бесполезным ровно в том случае, ради
   которого оно заводится: гейт закрыт, трафика нет, числа нужны.

3. **Сборка живёт одним методом — `ProcessHeartbeat.current_levels_snapshot()`**, рядом с
   `current_telemetry_publish` / `current_unknown_metrics`; команда остаётся тонкой обёрткой,
   как и обещал её докстринг. Второй дороги к сборщику не заводится: разойдись push и poll —
   «опрос отдаёт то же, что push» стало бы ложью, видимой только на стенде.

4. **`snapshot_ts` — wall-clock (`time.time()`, эпоха), не `time.monotonic()`, и он измеряет
   возраст ОТВЕТА, а не возраст чисел.** Первая редакция этого ADR обещала здесь, что поле даёт
   потребителю отличить «свежо» от «процесс завис». **Это было неверно, и найдено ревью
   воспроизведением** (`CycleMetricsRecorder`, 20 циклов по 47 мс, затем воркер остановлен
   полностью):

   ```
   опрос #1: snapshot_ts=1786706886.811  state={'fps': 21.0, 'latency_ms': 47.7}
   опрос #2: snapshot_ts=1786706890.812  state={'fps': 21.0, 'latency_ms': 47.7}   (+4.00 с)
   числа идентичны после 4 с полного простоя; status воркера — 'running'
   ```

   Штамп идёт, числа стоят. Хуже: зависни процесс целиком — ответа не будет вовсе, то есть ровно
   в том случае, ради которого поле якобы заводилось, оно не доезжает. Вырожденный случай той же
   природы: без heartbeat'а ответ несёт `levels=None` И свежий `snapshot_ts`.

   Что поле даёт на самом деле и за чем оставлено: **возраст ответа** — «когда собран ЭТОТ
   ответ». Этого хватает, чтобы отличить свежий ответ от показанного из кэша потребителя и
   упорядочить ответы между собой. Эпоха, а не monotonic: monotonic одного процесса с часами
   потребителя несравним в принципе (точка отсчёта произвольная и своя у каждого процесса), тот
   же выбор и по той же причине уже сделан для `timestamp` heartbeat-сообщения. **Отвергнуто:**
   `time.monotonic()` — потребителю пришлось бы держать историю опросов, то есть заводить у себя
   состояние ради поля, отвечающего одним запросом. **Цена названа:** перевод системных часов
   назад делает поле убывающим. Приёмка тестера сторожит «не убывает», а не «строго растёт», —
   при разрешении часов Windows ~15.6 мс строгий рост между двумя быстрыми опросами и так не был
   бы сигналом.

   **Признак свежести САМИХ ЧИСЕЛ — отдельное поле: per-worker `cycles`** (счётчик завершённых
   циклов `CycleMetricsRecorder`). Взят потому, что оказался бесплатен: `WorkerManager.get_worker_status`
   уже подмешивает его наверх статуса воркера (`worker_manager.py:329-335`), то есть он лежит в том
   же снимке — ни нового механизма, ни второго обхода, одно чтение `w.get("cycles")`. Счётчик стоит
   → числа протухли; растёт → живые. Судить по ПАРЕ (`snapshot_ts`, `cycles`), а не по штампу:
   один маркер врёт (урок «вердикт по одному маркеру»). В push `cycles` НЕ идёт (флаг
   `include_cycles`, по умолчанию выключен): это не уровень «для глаз», а нужда опрашивающего, и
   лист на каждого воркера каждый тик ради неё дерево не получит. Асимметрия односторонняя —
   push остаётся ПОДМНОЖЕСТВОМ опроса, поэтому «числа опроса совпадают с числами push» не
   нарушено (приёмка п.5 и проверяет подмножество).

5. **Группа `shm` входит в `levels`.** На боевом процессе с router'ом тик публикует
   `processes.<name>.state.shm.*`; не отдавай их опрос — свойство «опрос отдаёт то же, что push»
   оказалось бы ложным именно на стенде и **невидимым в юнит-тестах**, где `router is None`.
   Чтение `router.get_stats()` ничего не мутирует. Список из тринадцати счётчиков выехал из
   публикатора в общий `build_router_shm_telemetry` — иначе добавленный счётчик появлялся бы у
   push и молча отсутствовал у опроса. У публикатора осталась ПОЛИТИКА: «все нули → не грузим
   дерево»; у опроса те же нули — показание «кадрового пути нет / всё чисто». Разные ответы на
   одни данные намеренны и проверяются порознь
   (`tests/test_telemetry_levels_poll_hazards.py::TestShmTravelsWithThePoll`).

6. **Округление до одного знака (`round(x, 1)`) действует и на опросе** — как следствие общего
   сборщика, а не по недосмотру. Снимок — вид уровней для глаз, а не измерительный прибор;
   расхождение push и poll в последнем знаке стоило бы дороже потерянной точности. Полную
   точность, если понадобится, заводить отдельным решением и на обеих дорогах сразу.

**Что осталось прежним.** Публикация уровней остаётся дефолтом (развилка РТ-2 отложена до живых
чисел 3.3 — флип только парой маркеров ON/OFF). Фронты (`status`, ошибки, переходы) идут push'ем
и мимо гейта, как и раньше. Опрос **не пишет в дерево и не двигает расписание гейта**: снимок не
зовёт `due_metrics()`, поэтому наблюдение не съедает слот метрики у следующего тика — соблазн
позвать `due_metrics()` «чтобы push и poll совпали» отвергнут именно поэтому, и оба свойства
сторожатся (расписание гейта + тик после серии опросов).

**Цена опроса: узкий аксессор вместо полного `get_stats()` (ревью-блокер 1).** Первая редакция
звала ради тринадцати int'ов полный `RouterManager.get_stats()`, который строит `channel_routes`,
`message_handler_list`, `channels` и берёт `_stats_lock`. «Read-only» не значит «дёшево», и цена
не была названа. A/B на живом стенде (15 вызовов, медианы; `camera_0` — новый код, `seg` — старый,
контроль на той же машине в ту же минуту):

| процесс | команда | медиана, мс |
|---|---|---|
| camera_0 | `introspect.telemetry` (с `levels`) | **56.25** |
| seg | `introspect.telemetry` (без `levels`) | 11.05 |
| camera_0 | `introspect.status` (пол транспорта) | 11.00 |
| camera_0 | `introspect.router_stats` | 64.13 |

Весь прирост опроса — цена `get_stats()`. Ревью независимо намерило интерференцию: шторм опросов
21.7/с просадил боевой fps `camera_0` с 21.31 до 19.73 Гц (−7.4 %), после прекращения шторма
восстановилось до 21.28. Задача 3.3 подключает опрос на восемь процессов — при 1 Гц это было бы
≈360 мс/с процессорного времени до того, как GUI что-либо нарисует.

**Результат правки — те же 15 вызовов, потом контрольный замер N=41 интерливом** (интерлив,
чтобы дрейф стенда бил по всем пробам поровну; `camera_0` перезапущен на новый код, pid 7884 → 38032):

| проба | до правки | после правки |
|---|---|---|
| `camera_0` `introspect.telemetry` (с `levels`) | **65.73 мс** | **11.13 мс** |
| `camera_0` `introspect.status` (пол транспорта) | 10.99 мс | 11.00 мс |
| `seg` `introspect.telemetry` (без `levels`, старый код) | 11.08 мс | 11.11 мс |
| `camera_0` `introspect.router_stats` (полный `get_stats`, не трогали) | 54.64 мс | 43.82 мс |

Опрос уровней стал **неотличим от пола транспорта**: 11.13 против 11.00 мс у пустейшей команды
процесса, то есть +0.13 мс за все уровни. Было +54.7 мс. Полный `get_stats()` остался дорогим —
его никто не удешевлял, и `introspect.router_stats` честно продолжает столько стоить.

**Интерференция ушла — повторён замер ревью.** Шторм опросов **80.4/с** (вчетверо плотнее
ревьюшных 21.7/с): fps `camera_0` под штормом 21.38 против 21.34 без шторма (**+0.2 %**), после
шторма 21.25. До правки ревью намерило −7.4 % при 21.7 опр/с.

**Решение:** `RouterManager.get_shm_stats()` — узкий аксессор ровно на эти тринадцать чисел
(суммы по frame-middleware, дешёвые property `queue_registry`, один ключ `_stats` под замком),
без сборки маршрутов/хендлеров/каналов. Приём не новый: `queue_data_evicted` уже брался дешёвым
property мимо полного `get_stats()`. `build_router_shm_telemetry` предпочитает узкий путь, полный
`get_stats()` остаётся фолбэком для router'ов без аксессора (duck-typing). **Выигрыш достаётся и
push-тику**, который платил те же ~45 мс на каждом такте heartbeat'а. Чтобы узкий и полный пути не
разошлись, `get_stats()` splice'ит результат аксессора к себе (`**self.get_shm_stats()`) — точка
вычисления одна, эквивалентность сторожит `router_module/tests/test_shm_stats_narrow.py`.

**Как мерить «ноль трафика» на стенде, чтобы не прочесть результат наоборот (важно для РТ-2).**
Закрытый гейт НЕ обнуляет число IPC-сообщений публикации: `status` воркеров идёт **мимо гейта**
(always-on, ADR-PM-018), поэтому тик по-прежнему шлёт один `proxy.merge` на
`processes.<name>` каждый тик — с одними статусами и без единого числа. Воспроизведено:
гейт с `enabled=False` на всех пяти метриках каталога, два тика → 2 merge'а по пути
`processes.camera_0`, полезной нагрузки в них нет.

Обнуляется другое — **дельты** `state.changed`: `TreeStore.set` возвращает `None` на неизменившемся
значении, и `merge` их не порождает. Воспроизведено на `TreeStore`: первый merge
`{"workers":{"w0":{"status":"running"}}}` → 1 дельта, второй и третий тем же значением → 0 дельт,
смена статуса на `stopped` → снова 1. То есть критерий приёмки «счёт `state.changed` по
телеметрийным путям за окно = 0» достижим и осмыслен, а «ноль IPC-сообщений» — нет, и мерить
надо именно дельты. Полное обнуление сообщений потребовало бы вывести `status` из тика, то есть
тронуть инвариант фронтов — вне задачи 3.2 и против §0 спеки.

**Резидуал, найденный живым стендом (2026-08-14).** `levels` — это то, что собирает
телеметрийный тик, а НЕ весь `processes.<name>.state` дерева. На живом `camera_0` рядом с
`fps` / `latency_ms` / `shm.*` лежат ещё **восемь** ключей: `status`, `pid`, `frame_count`,
`error`, `uptime`, `drops`, `paused`, `frozen`. Всего в живом `processes.camera_0.state`
одиннадцать ключей, опрос отдаёт три. Их пишут ДРУГИЕ публикаторы (bootstrap состояния и
прикладные процессы прототипа). Список полный намеренно: он — вход развилки 3.3, и неполный
вход дал бы неполное решение. Потребитель,
который сегодня берёт `uptime` из дерева (а он в `DEFAULT_TRACKED_SUFFIXES` read-model), опросом
его не получит. Для 3.3 это выбор из двух и он НЕ сделан здесь: либо GUI продолжает брать эти
поля push'ем, либо их эмитенты въезжают в тот же сборщик. Флип дефолта публикации (РТ-2) до
закрытия этого пункта означал бы молчаливую потерю `uptime` во вкладке.

Тот же стенд дал и подтверждение п.5: `camera_0` публикует `state.shm.boundary_crossings = 77749`
— ненулевой счётчик, ежетиково уезжающий push'ем. Исключи опрос `shm` — и расхождение push/poll
было бы реальным с первого же боевого запуска, оставаясь невидимым в юнит-тестах (`router is None`).

**Известная ловушка каталога (не дефект, но кусается при проверках).** `gated_metrics()`
наполняется **побочным эффектом импорта**: `declare_metric` стоит на уровне модулей
`heartbeat/telemetry.py` (четыре метрики) и `heartbeat/process_heartbeat.py` (`shm`). Импорт
`gated_metrics` из `configs/telemetry_publish_config.py` в изолированном скрипте, не затянувшем
эти модули, отдаёт неполный каталог — `['shm']` или пусто. Проверять каталог только там, где
цепочка импортов заведомо полна (найдено независимым тестером Task 3.2 характеризацией).

## ADR-PM-036: широкая запись — жест плагина поверх существующего носителя, с живым хозяином отбора

**Статус:** принято
**Дата:** 2026-08-16
**Refs:** plans/telemetry-stage6.md (задача 4.1, Ф4, развилка РТ-4 и решения Р4.1-1…Р4.1-12),
ADR-PM-029 (`ctx.write_document` — дорога вердикта), ADR-PM-033 (stats-четвёрка),
ADR-PM-028 (плоскость документов), `plugins/base.py::PluginContext.write_event`,
`managers/observability_wiring.py::WideEventSelector`

**Контекст.** «Почему изделие N забраковано» собирается по россыпи записей: вердикт-документ в
одном месте, счётчики в другом, спаны кадра в третьем, строки журнала в четвёртом. Ингредиенты
уже есть — `trace_id` в каждой записи (Ф7 G.6), спаны при `MULTIPROCESS_FRAME_TRACE`,
вердикт-документ Ф8.7. Не хватало сборки в ОДНУ запись.

**Решение.**

1. **Носитель — существующая пятёрка `log_*`, нового порта записи нет** (РТ-4, вариант (а)).
   `LoggerCore.info` — это уже `LogScope.BUSINESS` + `INFO`, то есть носитель существует целиком.
   Документ-на-единицу отклонён ценой `append` в SQLite (медиана 3.6 мс, max 928 мс — бюджет
   редкого события, не потока); `kind=stats` отклонён по смыслу: широкая запись — факт о единице,
   а не агрегат за окно.

2. **`trace_id` едет В ТЕКСТЕ записи**, а не только в `extra`. Полнотекстовый индекс стора
   построен по `message`/`module`/`process` и в `extra` не смотрит (тот же довод, что у
   `snapshot_message`). Структурно — да, но текст обязателен: иначе запись находится фильтром по
   виду и никогда по следу, то есть ровно на вопрос, ради которого она едет в стор, ответа нет.
   Форма постоянна (`event <род>: <суть> trace=<след>`) даже при пустом следе — переменная
   сломала бы поиск по образцу.

3. **Отбор — свой (`WideEventSelector`), а не `RateSampler`.** Дроссель логгера ключует пару
   «уровень + текст»; у широкой записи текст свой у каждой единицы, и на таком ключе он не
   задросселировал бы ничего. Ключ отбора здесь — РОД единицы (`kind`), лесенка — `first_n`, далее
   каждая `every_mth`-я. `decisive=True` идёт мимо отбора всегда и считается ОТДЕЛЬНО: считай мы
   фронты общим счётчиком, «каждая третья» означала бы разное в спокойную минуту и под серией
   отбраковок.

4. **Ноль здесь означает «выключено», в отличие от одноимённых ручек логгера.** У
   `sampling_every_mth` стоит `min=1` (ноль дал бы деление на ноль на горячем пути), у
   `events.every_mth` ноль штатен и означает «после первых N не проходит ничего». Ловушка названа
   и в схеме, и в докстринге селектора, и тестом, сверяющим оба поведения рядом: одинаковые слова
   с противоположным смыслом нуля — готовый источник неверного вывода.

5. **Отключённость имеет ОДНО исполнение.** Процесс без сшивки (`event_selector is None`) ведёт
   себя ровно как настроенный селектор с дефолтом `0/0`: фронты пишутся, поток нет. Разъедься эти
   два случая — «поток молчит» означало бы разное на соседних процессах.

6. **Карта родов насыщаема.** `kind` кладёт приложение, и род, собранный из данных, превратил бы
   карту в утечку. После 64 родов новые считаются общим бакетом, факт виден числом
   `kinds_saturated`. Форма взята у детектора незнакомых групп логгера — там насыщаемость уже
   названа обязательной.

7. **Прикладное поле с именем параметра НОСИТЕЛЯ стоит записи, но не линии — и исход сверяется
   ДВУМЯ способами.** Конверт после `**fields` защищает `event`/`trace_id`/`spans`, позиционные
   `kind`/`summary` — род записи, но имя `message`/`msg`/`scope`/`level` принадлежит чужой
   сигнатуре, и позиционность фасада от него не спасает. Одного `except` при этом НЕ ХВАТАЕТ, и
   это воспроизведено на реальном `LoggerManager` строками с диска (ревью 4.1):
   `ObservableMixin._call_manager` ловит исключение менеджера У СЕБЯ и считает его в
   `manager_call_failures` — поэтому `scope`/`level` давали `write_event=True` при нуле строк и
   нулевом `refused`, то есть молчащую потерю. Теперь после вызова сверяется счётчик носителя
   (`carrier_failures`), и инвариант `refused` («`selected` минус `refused` равно числу строк»)
   верен для всех четырёх имён. Цена сверки платится только на записях, ПРОШЕДШИХ отбор.
   Показание счётчика суммарное по паре `logger.info`, поэтому `refused` — верхняя оценка:
   отказ соседнего потока в окне между снятиями будет приписан сюда. Обратная ошибка (потеря,
   которую никто не считает) хуже, и выбор сделан в её пользу осознанно.

8. **Штамп источника — тоже конверт.** `module` в перечень опасных имён не входит: он не
   отказывает, а тихо уводил запись под чужое имя (`_stamped` ставит `partial(log_fn, module=…)`,
   а keyword на call-site партиал перебивает без ошибки). Портилась при этом колонка, по которой
   строится FTS-поиск, — то есть ровно та дорога, ради которой `trace_id` кладётся в текст.
   Штамп кладётся ПОСЛЕ `**fields`; при пустом имени ключ снимается, и действует умолчание
   носителя. Перечень опасных имён живёт в ОДНОЙ копии (докстринг `PluginContext.write_event`):
   их было две, они разошлись, и обе ошибочно перечисляли `module`.

**Четыре вопроса фреймворка-конструктора (§3.6 спеки).**

* **Универсальность.** Механизм не знает ни одного имени из `multiprocess_prototype` / `Plugins`:
  `kind`, `summary`, `unit` и поля — целиком от приложения; в `observability_wiring.py` и
  `plugins/base.py` нет ни импорта, ни литерала из верхних слоёв. Судится импортами, а не
  намерением: единственный эмитент (`RobotControlPlugin`) живёт в `Plugins/` и зовёт фасад.
* **Отключаемость.** Процесс без сшивки селектора работает названным поведением, а не
  `AttributeError` (п.5); процесс без плоскости логов теряет запись со счётчиком и голосом, а не
  с исключением. Ярус механизма — тот же, что у `process_module`.
* **Единообразие.** Дорога та же, что у `log_*`, `health`, `write_document` и stats-четвёрки:
  `IProcessServices` → `PluginContext` → `SubPluginContext`, порт объявлен вместе с атрибутом
  класса ОДНОЙ правкой (урок 4.2), заглушка вложенного контекста дословна сигнатуре (урок четырёх
  заглушек 1.1), проброс — в единственном перечислении дорог (урок Н-6).
* **Меньше слоёв.** Новых слоёв два и оба снимают названное: селектор — потому что существующий
  дроссель на этом ключе не работает (п.3); секция `events` — в ТОЙ ЖЕ `observability`, пятой
  двери конфига не заводится (правило Б.1), `TELEMETRY_SUBSECTIONS` не расширяется. Второго
  механизма замера спанов нет — `MULTIPROCESS_FRAME_TRACE` остаётся единственным, а его
  выключенность НАЗВАНА в самой записи (`spans: "off"`), потому что «не мерили» и «мерили, спанов
  нет» — разные факты.

**Цена — числами живого стенда** (`inspection_full`, 7 процессов, 21.3 единицы/с, 2026-08-16):

* **476 Б на запись** (min 475, max 476, n=483). При `every_mth=9` это **8 548 строк/ч =
  3.88 МиБ/ч** — **вдвое выше ориентира гейта этапа** (≤ ~2 МиБ/ч на 8 процессов). В ориентир
  укладываются два режима: дефолт `0/0` (поток не пишется, идут только фронты) либо прореживание
  **не чаще ~1/18** (2 МиБ/ч ÷ 476 Б ≈ 4 400 записей/ч при 76 700 единицах/ч). Это не запрет, а
  цена, которую оператор обязан видеть до того, как откроет поток;
* **фасад при закрытом отборе — 661 нс/вызов**: прорежённая запись действительно не платит ни за
  сборку текста, ни за импорт `frame_trace` (проверено, не заявлено);
* **эмитент платит больше и без потолка.** `RobotControlPlugin` собирает нагрузку ДО обращения к
  фасаду, поэтому цена растёт с числом дефектов на кадре: **2.14 мкс при 1, 3.79 при 10, 19.0 при
  100, 74.2 мкс при 500**. Потолка у этой работы нет — при шумной маске и
  `max_detections_for_reject=0` число блобов ничем не ограничено. На темпе стенда это ~0.005% CPU,
  то есть не блокер; но «фасад дёшев» и «вызов дёшев» — разные утверждения, и второе неверно.
  Гейт у ИСТОЧНИКА (не собирать нагрузку, пока отбор закрыт) остаётся доступным улучшением с
  названной ценой — его не делаем, пока живой темп не потребует.

**Материализация дефолта проверена, а не предположена.** Секция `events` появляется в
`sys_config.observability` (полный дамп `ObservabilityConfig` у оркестратора) — ровно там же, где
уже материализованы `channels`, `sampling_*`, `session_ttl_sec`, `commands` и остальные дефолты.
В СЛОЙ (`observability_app`, L1) она НЕ попадает: сверено по golden-снапшоту сборки обоих живых
рецептов. Поэтому урок «материализованный дефолт перебивает нижние слои» здесь не применяется —
перебивать нечего, ключ в бухгалтерию слоёв не въезжает. Сторожит это тот же снапшот: попади
`events` в `observability_app`, тест сборки покраснеет.

**Последствия.** У плагина появляется третий разъём наблюдаемости рядом с `write_document` и
stats-четвёркой; ручки `observability.events.{first_n,every_mth}` идут дорогой трёх точек (схема →
сшивка/пересборка → readback живого селектора в `introspect.observability -> events`). Контекст,
собранный вручную (тестовые дубли), обязан нести `write_event` — как уже обязан нести
`write_document`.

## ADR-PM-037: flight recorder — кольцо ЗАПИСЕЙ процесса, выгружаемое жестом плагина

**Статус:** принято
**Дата:** 2026-08-16
**Refs:** plans/telemetry-stage6.md (задача 5.1, Ф5, развилка РТ-5 и решения Р5.1-1…Р5.1-14),
ADR-PM-036 (широкая запись — предыдущий разъём той же дороги), ADR-PM-029 (`ctx.write_document`),
задача 2.9 (`MemoryChannel` и `read_sink_tail`),
`managers/observability_flight.py::FlightRecorder`, `plugins/base.py::PluginContext.flight_dump`

**Контекст.** Широкая запись (ADR-PM-036) отвечает «что было с ЭТОЙ единицей». Она не отвечает на
соседний вопрос — «что происходило в процессе ВОКРУГ момента брака»: соседние единицы, служебные
строки, отказы, из-за которых решение и получилось таким. Ингредиенты для ответа уже лежали
готовыми: кольцо последних записей в памяти процесса (`MemoryChannel`, 2.9) с ретроспективным
чтением `observability.sink.tail`, и триггер — фронт pass→reject, где уже пишется вердикт-документ
Ф8.7 (95 кадров брака → 1 срабатывание). Не хватало ровно двух вещей: выгрузки кольца в файл и
вызова этой выгрузки от прикладного события.

**Решение.**

1. **Триггер — явный `ctx.flight_dump(reason)`, а не авто-хук на вердикт-документ** (РТ-5,
   вариант (а), решение владельца). Связка «документ рода `verdict` — значит дамп» неочевидна и
   неуправляема: у приложения бывают вердикты, дампа не требующие, а выключить магию можно было бы
   только перестав писать документ. Жест такой же явный, как `write_document` и `write_event`, и
   стоит рядом с ними в `PluginContext`.

2. **Кольцо читается СУЩЕСТВУЮЩЕЙ дорогой** — `ChannelRoutingManager.read_sink_tail(sink, limit)`
   у `logger_manager`. В процессный реестр колец (`log_channel._memory_rings`) рекордер не лезет:
   реестр — внутренность канала, по этой же дороге уже ходит команда `observability.sink.tail`, и
   второй способ прочитать одно кольцо разошёлся бы с первым молча. Новых колец не заводится ни
   одного.

3. **Путь дампа резолвится дорогой ФАЙЛОВ ЖУРНАЛА** — `<база>/<процесс>/flight/<ts>_<reason>.jsonl`,
   через `log_paths.process_log_directory` и `resolve_log_file_path`. Вычисление базы вынесено из
   `LoggerCore._resolved_file_path` в функцию: у него появился второй клиент, а скопированная
   тройка строк разошлась бы на первой же правке приоритета каталогов — и дампы легли бы не туда,
   где их ищут, без единой ошибки. Относительный путь от cwd запрещён замером, а не вкусом: он уже
   стоил проекту 467 МиБ в дереве репозитория (урок 3.3).

4. **Выключенность имеет ОДИН адрес** (Р5.1-5). Соблазн выразить её вторым способом («нет
   memory-канала в конфиге») отвергнут: два независимых способа быть выключенным дают класс, где
   оператор гасит один, а действует другой. Процесс без сшивки отвечает ТЕМ ЖЕ отказом, что
   настроенный рекордер с `enabled=False`.

5. **Отказов ТРИ класса, и они не слипаются**: `refused_disabled` (ручка
   `observability.flight.enabled`, лечится конфигом), `refused_no_ring` (приёмник не объявлен, или
   не `type: memory`, или не смаршрутизирован — лечится конфигом кольца), `refused_failed` (кольцо
   прочитано, файл не написан — лечится машиной). Спека называла два; третий добавлен потому, что
   молчаливый `return False` на отказе диска — ровно класс «проглоченный сбой», ради которого фаза
   и затевалась, а отправлять оператора править ключ, который в порядке, хуже, чем завести
   четвёртое число. У каждого свой счётчик и свой однократный голос с адресом.

6. **Формат — JSONL, шапка первой строкой.** Шапка несёт причину, процесс, источник, поля
   вызывающего (прежде всего `trace_id` единицы) и СНИМОК КОЛЬЦА (`capacity`/`size`/`written`/
   `evicted`). Без снимка счёт записей нечитаем: «в дампе 12 записей, потому что столько было» и
   «потому что 488 вытеснено» — разные факты. Сериализация с `default=str`; отказ ОДНОЙ записи
   оставляет на её месте строку-заглушку с индексом (`flight_record_unreadable`) и не стоит дампа
   целиком, потому что `extra` держит ссылки на произвольные объекты вызывающего. Отказ
   сериализации ШАПКИ снимает прикладные поля и называет причину в ней же — дамп без шапки
   нечитаем.

7. **Ретеншен — по числу ФАЙЛОВ, голос на КАЖДОЕ вытеснение** (INFO, с именем удалённого файла).
   Это обратно правилу однократного голоса у отказов, и разница названа: отказ повторяется на
   каждом такте линии, а вытеснение так же редко, как сам дамп, — молчаливое удаление улики хуже
   строки в журнале. `keep=0` означает «без предела» (уже написанная в проекте форма, ср.
   `log_line_max_bytes`, `max_series`). Порядок — по имени файла: метка времени фиксированной
   ширины, лексикографический порядок равен хронологическому.

8. **Порядок вызова у эмитента несущий**: `write_event(decisive=True)`, затем `write_document`,
   затем `flight_dump`. Кольцо снимается В МОМЕНТ вызова, поэтому дамп, позванный раньше широкой
   записи, её не содержит — и пункт приёмки «в дампе wide event бракованной единицы» был бы
   зелёным на пустом месте (кольцо-то непустое). Свойство сторожится тестом по СОДЕРЖИМОМУ файла,
   а не порядком строк в исходнике.

9. **Секреты не получают обходную дорогу — но их у дампа было ДВЕ, и это найдено и закрыто
   отдельной задачей (S-2, Ф6), а не этой.** ТЕЛО дампа секретов не несёт по построению: кольцо
   кормится ПОСЛЕ цепочки процессоров (`_run_processors` стоит до раздачи по каналам), то есть
   `SecretRedactor` отработал раньше кольца, и дамп своей дороги записи для тела не заводит.
   **Первая редакция этого пункта останавливалась здесь и была неполной.** `reason` и `fields` —
   прикладные строки из `ctx.flight_dump(reason, **fields)` — редактору не показывались НИКОГДА:
   до S-2 секрет из `reason` был виден в ИМЕНИ ФАЙЛА (`reason_slug` — санитайзер для файловой
   системы, а не для секретов, он режет небезопасные символы) без открытия файла, а из
   `reason`/`fields` — в ШАПКЕ (`_write` клал их в `_dumps` напрямую, минуя редактор). Найдено
   приёмкой (`test_flight_manifest_redaction_acceptance.py`, воспроизведение —
   `flight_dump("token=SECRET_R", token="SECRET_F")`), закрыто одной редакцией на входе
   `FlightRecorder.dump()`: `redaction.redact_text(reason)` и `redaction.redact_mapping(fields)` —
   теперь публичные функции `logger_module`, та же реализация правил, что у `SecretRedactor`, а не
   вторая копия набора имён. Путь и шапка получают ОДНО отредактированное значение `reason`, не
   два независимых (второй, независимой редакции для имени файла в модуле нет). Сторож судит ФАЙЛ
   ДАМПА целиком — путь, шапку и тело, — а не только кольцо.

**Граница с чужим одноимённым механизмом (Р5.1-13).** В репозитории уже живут две вещи, которые
зовут «flight recorder», и следующий читатель склеит их по имени, если не написать:

| Механизм | Что кольцует | Где стоит | Кто читает |
|---|---|---|---|
| `backend_ctl record_*` | ТЕЛЕМЕТРИЮ системы | снаружи процесса | оператор, offline-реплей |
| `telemetry_readmodel.export_history` | ТЕЛЕМЕТРИЮ уровней дерева | снаружи процесса | оператор, offline-реплей |
| **ADR-PM-037** | **ЗАПИСИ одного процесса** | **внутри процесса** | сам процесс, по триггеру |

Первые два отвечают на «как менялись показания», этот — на «что процесс писал вокруг момента X».
И ни один из трёх не кольцует ПИКСЕЛИ: изображения кадров едут своими механизмами (copy_out,
датасет), и видеорегистратором это не станет.

**Четыре вопроса фреймворка-конструктора (§3.6 спеки).**

* **Универсальность.** Механизм не знает ни одного имени из `multiprocess_prototype` и `Plugins`:
  `reason` и поля шапки целиком от приложения, имя кольца — из конфига. В `observability_flight.py`
  нет ни импорта, ни литерала из верхних слоёв; судится импортами, а не намерением. Единственный
  эмитент (`RobotControlPlugin`) живёт в `Plugins/` и зовёт фасад.
* **Отключаемость.** Дефолт — выключено, и выключенный механизм не создаёт ни файлов, ни каталога.
  Процесс без сшивки работает названным поведением, а не `AttributeError`; процесс без кольца
  получает отказ со счётчиком и голосом, а не исключение. Отказ дампа не меняет решения линии
  (Р5.1-14). Ярус механизма — тот же, что у `process_module`.
* **Единообразие.** Дорога та же, что у `log_*`, `health`, `write_document`, `write_event` и
  stats-четвёрки: `IProcessServices` — `PluginContext` — `SubPluginContext`. Порт объявлен вместе с
  атрибутом класса ОДНОЙ правкой (урок 4.2), заглушка вложенного контекста дословна сигнатуре
  (урок четырёх заглушек 1.1 плюс урок 4.1-И8 про позиционно-only параметр), проброс — в
  единственном перечислении дорог `from_parent` (урок Н-6). Ручка идёт дорогой трёх точек и
  подключена на ВСЕХ дорогах пересборки (находка 1 задачи 4.1).
* **Меньше слоёв.** Новый слой ровно один — сам рекордер, и он держит только политику и
  бухгалтерию: кольцо принадлежит логгеру, каталог — плоскости логов, чтение и резолв пути —
  существующим функциям. Секция `flight` живёт в ТОЙ ЖЕ `observability`, пятой двери конфига не
  заводится (правило Б.1), `TELEMETRY_SUBSECTIONS` не расширяется. Второго кольца, второго формата
  и второго способа читать кольцо не появилось.

**Дороги пересборки — ШЕСТЬ, а не пять.** Спека называла пять (`config.reload`,
`make_observability_on_reload`, `start_observability_watcher`, оба watcher'а оркестратора, возврат
по TTL); шестая — `_reset_observability_sessions` оркестратора на switch рецепта
(`process_manager_process.py`). Она подключена вместе с остальными: пропусти её — и на switch
политика дампа держалась бы на снятой правке, тогда как readback честно отвечал бы «сессия пуста».

**Цена — числом** (Windows, 500 записей в кольце, файл 142 КБ, 284 Б на запись): медиана
**2.96 мс**, min 2.65, p95 3.17, max 3.24; с включённым ретеншеном (`keep=5`) медиана 3.32 мс,
max 6.65 мс. Это бюджет РЕДКОГО события: фронт вердикта на живом стенде — единицы срабатываний
против тысяч единиц работы. На кадре 25 FPS (бюджет 40 мс) один дамп занял бы около 8% бюджета, и
именно поэтому триггер стоит на ФРОНТЕ, а не на кадре брака.

**Последствия.** У плагина появляется четвёртый разъём наблюдаемости; контекст, собранный вручную
(тестовые дубли), обязан нести `flight_dump` — как уже обязан нести `write_document` и
`write_event`. Каталог `flight/` появляется в дереве логов только у процессов с включённым
рекордером. Рецепт стенда `inspection_full.yaml` объявляет кольцо ТОЛЬКО на `inspector` (форма
`processes:` без `defaults:`): кольцо на каждом процессе — это 500 записей на семь процессов
задаром.

**Правка S-5 (Ф6, 2026-08-17): дефолт «выключено» жил в ЧЕТЫРЁХ копиях, а не в одной.**
Сквозное ревью этапа 6 нашло, что ветка «секции `observability.flight` нет вообще»
в `_flight_knobs` возвращала захардкоженный литерал `(False, "", 5, 0)`, минуя
`ObservabilityFlightConfig.model_validate` целиком; тот же литерал был продублирован ещё в
двух местах (вызов `wire_flight_recorder`, fallback `apply_flight_recorder`). Инъекция «секции
нет → считаем включённым» проходила мимо всех трёх копий: 76 passed, ноль красных, при этом
механизм НАЧИНАЛ писать улики на диск у процесса, который их не заказывал. Правка: «секции
нет» стало равнозначно `section = {}`, и единственный путь — `ObservabilityFlightConfig.model_validate(section)`
(единый источник — `_flight_default_knobs()`, читает `ObservabilityFlightConfig()` живьём).
Патч дефолта схемы теперь долетает до ОБЕИХ дорог (стартовая сшивка и пересборка) одним и тем
же путём. Цена дополнительного экземпляра схемы, замерено (`timeit`, 20000 вызовов):
**≈1.7–1.8 мкс/вызов** — вызывается один раз на старт процесса и один раз на `config.reload`,
не на кадр, лишним предохранителем не заводился.

**Правка S-6 (Ф6, 2026-08-17): голос «уже сказали» не сбрасывался никогда.** `_WARNED_DISABLED_ATTR`
/ `_WARNED_NO_RING_ATTR` / `_WARNED_FAILED_ATTR` ставились один раз на процесс и не снимались
до конца жизни процесса — воспроизведено приёмкой: опечатка в `sink` → голос; починили → дамп
проходит; НОВАЯ опечатка → отказ засчитан счётчиком, а новых слов в журнале уже не было. Правка
не трогает `FlightRecorder.configure()`/`apply_flight_recorder` (у рекордера сознательно нет
ссылки на процесс — см. докстринг класса, и протаскивать `svc` туда ради этого не пришлось):
«уже сказали» хранится ТРОЙКОЙ атрибутов флаг+четвёрка-ручек рядом с каждым из трёх флагов
(`_WARNED_*_KNOBS_ATTR`), и `_say_once` сравнивает ТЕКУЩУЮ четвёрку `knobs` (снятую в момент
вызова `FlightRecorder.dump()`, где `svc` и так под рукой) с меткой прошлого голоса — совпали,
молчим; разошлись хоть по одной из четырёх ручек (не обязательно `sink`) — метка устарела, голос
звучит заново. Пересборка С ТЕМИ ЖЕ значениями метку не меняет, поэтому спама не даёт; серия
отказов подряд без смены настроек по-прежнему даёт РОВНО ОДИН голос (свойство, которое правка не
имеет права сломать). Три флага независимы друг от друга: устаревание метки одного класса не
порождает голос другого.

---

## ADR-PM-038: уровень плагина едет сборщиком тика, а не прямой записью в дерево

**Статус:** принято
**Дата:** 2026-08-16
**Refs:** plans/telemetry-stage6.md (Task 3.5, решения Р3.5-1…Р3.5-15, K-8), ADR-PM-017
(троттл — предохранитель, не авторитет частоты), ADR-PM-018 (publisher-gate), ADR-PM-035 (пакетный
опрос уровней, `levels`), ADR-136 (read-model телеметрии), Ф8.1 (`observability_declarations` —
реестр объявлений), E6/Task 5.7 (один merge вместо 3W+2 set),
`heartbeat/telemetry.py::build_plugin_levels`, `plugins/base.py::PluginContext.publish_metric`

**Редакции.** Первая (2026-08-16, коммит `2de8b540`) дала плагину разъём, но разрешала спор двух
писателей за один лист **порядком двух merge**. Ревью нашло блокер, и владелец потребовал не
латать, а пересмотреть подход. Разделы «Владение стережётся при публикации», «Один merge на тик»,
«Две величины — два имени» и «Свежесть жизненным циклом» ниже — вторая редакция (Р3.5-11…Р3.5-15);
снятые решения первой редакции названы поимённо, а не вычеркнуты молча.

**Контекст.** Publisher-gate (ADR-PM-018) обещает: закрыл окно — нет трафика уровней. Опрос
(ADR-PM-035) обещает: закрытое окно не ослепляет вкладку. Живой замер 2026-08-16 показал, что оба
обещания держатся только для метрик, которые считает сам фреймворк. Гейт `camera_0` был закрыт на
`fps`, `latency_ms`, `shm` (readback `gate_active: true`, `resolved.enabled: false` по всем трём);
за окно **41.1 с** чисто-тиковые `latency_ms` и `shm.boundary_crossings` дали **0** дельт, а путь
`state.fps` — **35** (0.85/с) от источника `camera_0`. Ноль засчитан только потому, что рядом было
ненулевое: контроль отличает «гейт сработал» от «измеритель не подключён».

Причина: у пути `state.fps` **два писателя**. Второй — `CapturePlugin`, он пишет
`state_proxy.merge("processes.<p>.state", {...})` напрямую, минуя сборщик тика, гейт и опрос.
Таких прямых писателей **на момент этого замера — восемь**, считая сам `CapturePlugin`. Число
относится к диагностике ДО решения, а не к HEAD: решение ниже (Р3.5-13) переводит уровни
`CapturePlugin` на `declare_metric`/`publish_metric`, и на HEAD остаётся **семь** немигрированных
писателей уровней (реестр с причинами — `README.md` модуля, то же число в `STATUS.md`). Фронты
`CapturePlugin` (`status`/`paused`/`frozen`) продолжают идти прямой записью — легитимно, см.
«Не удаляется». Цифру 8 здесь не правим на 7: она обосновывает необходимость самого решения,
и стереть её значило бы стереть повод.

**Ред. 2026-08-18 (ревью, блокер Б2): числа `~0.6/с`, `16 %` и `84 %` ниже СНЯТЫ — они не
выводятся из собственной итемизации задачи, а не переписаны молча.** Разбор той же строки
исчерпывающий: `35 + 40 + 83 = 158` дельт за 41.1 с = **3.84/с** (слагаемого `0.6` в нём нет).
Ошибка — в атрибуции `frame_count` (40 дельт, 0.97/с): его объявляет и публикует **плагин
захвата** (`ctx.declare_metric("frame_count")`, `Plugins/sources/capture/plugin.py:104`) дорогой
`ctx.publish_metric`, то есть ПОД ГЕЙТОМ, а не `ProcessMonitor` — в нём слова `frame_count` нет
вовсе (grep → 0 совпадений); он публикует `uptime` (`process_monitor.py:465`), `status`,
`supervisor.*`. Честная доля «плагинная дорога + ПМ» = `(0.85 + 2.02) / 3.84` = **74.7 %**, не
84 % — вывод «гейт не владеет большинством трафика» устоял, число под ним — нет. Выводимая
НИЖНЯЯ граница флипа — **не менее 25 %** (доля `frame_count`); верхняя из этого замера не
извлекается — гейтовая доля самого `fps` в нём уже была подавлена (гейт стоял закрытым). Полный
разбор с итоговой таблицей — `plans/telemetry-stage6.md` (Task 3.3, поправка к предсказаниям
С2/С4/С5, «Вторая правка той же поправки»).

**Решение — вариант (г): плагин ОБЪЯВЛЯЕТ уровень и ОТДАЁТ значение; собирает, гейтит и отдаёт
опросом фреймворк.**

* `ctx.declare_metric(имя)` — объявление через **существующий** реестр
  `observability_declarations` (плоскость `KIND_METRIC`), владелец = имя плагина;
* `ctx.publish_metric(имя, значение)` — текущее значение в процессное хранилище `PluginLevels`;
* `ProcessHeartbeat._publish_telemetry_to_tree` кладёт его в
  `processes.<процесс>.state.<имя>` на том же тике и под тем же `TelemetryGate`;
* `current_levels_snapshot` (опрос) собирает его **тем же** `build_plugin_levels`.

Порт `plugin_levels` объявлен в `IProcessServices` ОДНОЙ правкой с атрибутом класса
`ProcessModule` (урок 4.2), заглушки `SubPluginContext` дословны сигнатурам и добавлены **обе
сразу** в единственное перечисление дорог `from_parent` (урок Н-6).

**Почему не (а) «эмитенты въезжают в общий сборщик тика».** Неисполнима целиком: сборщик живёт В
ПРОЦЕССЕ, а `uptime`/`status`/`pid` — знание **ProcessManager'а** о ЧУЖОМ процессе, вычисленное из
его собственного `first_seen`. Процесс не знает точки отсчёта ПМ и отдать её не может ни одним
механизмом.

**Почему не (б) «остаются push'ем как фронты».** Честна для `status`/`error`/`pid`, но не для
уровней захвата: они текут по тику, и оставить их вне гейта значило бы оставить пункт 2 гейта
этапа («закрытое окно = ноль трафика уровней») невыполнимым по построению. Измерение показало, что
болезнь не в покрытии опроса, а в негейтируемой второй дороге.

**Граница названа: `uptime`/`status`/`pid` принадлежат ПМ.** Они не въезжают в снимок процесса — и
это ГРАНИЦА, а не долг. Цель §0 читается честно как «ноль трафика уровней, **которыми владеет
процесс**». `uptime` при этом крупнейший источник дельт (83 из 158 на `camera_0`), и это названо
числом, а не замолчано. Отдельно: `state.pid` живьём `None` у всех семи процессов — ключ мёртв, и
«опрос его не отдаёт» не долг опроса.

**Соседство `record_metric` и `publish_metric` — названо намеренно.** Имена похожи, плоскости
разные, и это ровно тот класс ловушки, на котором §Ф1 уже обжигался (`record_metric` у
`ObservableMixin` — counter, у `ObservabilityHub._emit_stat` — gauge):

| Разъём | Плоскость | Что означает | Где оседает |
|---|---|---|---|
| `ctx.record_metric` / `gauge` / `record_timing` / `histogram` | stats (дорога 2, задача 1.1) | вклад в **агрегат за окно** + история | `StatsManager` → стор |
| `ctx.publish_metric` | дерево состояния (дорога 1, эта задача) | **текущее значение**, перезапись | `processes.<p>.state.<имя>` |

Обе дороги остаются: величина может быть нужна и как «сколько сейчас» на карточке, и как «сколько
за смену» в истории. Сводить их в одну — унификация по букве.

**Три следствия, принятые с открытыми глазами.**

1. **Имя, которым публикатор не владеет, не публикуется НИКОГДА и об этом говорится.** Отбор
   идёт по владению (см. раздел «Владение стережётся при публикации»), а не по членству в общем
   каталоге. `ProcessHeartbeat` называет отсеянное имя WARNING'ом ОДИН раз, и в голосе три
   участника: имя, публикатор и владелец (либо «не объявлено никем»). Три участника, а не один,
   потому что «я опечатался в имени» и «это имя не моё» — разные диагнозы с разными действиями.
   Ругаемся на ТИКЕ, а не в `publish_metric`: на момент публикации порядок «объявил → отдал» ещё
   не устоялся (плагин вправе отдать стартовое значение раньше объявления в том же `configure`),
   а на момент тика — уже.
2. **Имя-дубль не разрешается — он отбрасывается.** Прежняя редакция объявляла политику наложения
   («порядок несущий», «плагин побеждает»); она снята целиком, см. ниже.
3. **Опрос гейту не подчиняется, push подчиняется.** Асимметрия унаследована от ADR-PM-035 и
   намеренна: гейт про трафик, а не про то, что процесс знает о себе. Именно она делает флип РТ-2
   возможным — закрытое окно даёт ноль в дереве и живые числа вкладке.

**Что мигрировано.** Ровно один писатель — `Plugins/sources/capture`. Его уровни едут
разъёмом под именами `capture_fps` / `frame_count` / `drops`; фронты
(запущен/приостановлен/заморожен) остаются прямой записью: собранный тиком «уровень», который между
сменами состояния не обновляется, был бы хуже прямой записи. Остальные семь писателей — реестр с
причинами в `README.md`, без правок кода.

**Четыре вопроса фреймворка-конструктора (§3.6 спеки).**

* **Универсальность.** Механизм не знает ни одного прикладного имени: каталог наполняется
  объявлениями плагинов, сборщик работает над снимком «имя → значение». Судится **положительным**
  свойством, а не грепом: плагин объявляет `zzz_made_up_level` — имя, которого нет нигде в
  репозитории, — и оно доезжает и в дерево, и в опрос (`test_plugin_levels_hazards.py`). Механизм
  с зашитым списком имён провалит этот тест по построению. Отрицательный grep отвергнут владельцем
  плана: он не отличает докстринг от кода и даёт ложные срабатывания на законных `frame_counter`
  (пример в докстринге `plugins/base.py`) и `frame_stale_drops` (счётчик SHM).
* **Отключаемость.** Хранилище создаётся лениво, на первой отдаче значения; у процесса без
  телеметрии значение просто никто не читает — это и есть отключённость. Сервисы, не принимающие
  порт (иммутабельный дубль), дают названный no-op с ОДНИМ голосом, а не `AttributeError`.
  Исключений `publish_metric` не бросает ни при какой конфигурации: уровень не имеет права ронять
  линию. Гейт остаётся единственным рычагом «не грузить»: выключил метрику — ни merge, ни дельты.
* **Единообразие.** Дорога та же, что у `log_*`, `health`, `write_document`, `write_event`,
  `flight_dump` и stats-четвёрки: `IProcessServices` → `PluginContext` → `SubPluginContext`. Порт
  объявлен вместе с атрибутом класса, обе заглушки вложенного контекста дословны сигнатурам, обе
  дороги внесены в единственное перечисление `from_parent`.
* **Меньше слоёв.** Второго реестра не заведено (Р3.5-2): имя объявляется тем же
  `declare_metric`, который уже открыл `GATED_METRICS` — один словарь с составным ключом на три
  плоскости. Второго способа посчитать те же величины тоже нет: `build_plugin_levels` один на push
  и на опрос. Новых команд ноль (`introspect.telemetry` расширена, не продублирована). Новый слой
  ровно один — хранилище `PluginLevels`, и оно держит «имя → (значение, публикатор)» под локом;
  лок нужен не ради атомарности присваивания, а потому что копия растущего словаря без него
  поднимает `RuntimeError` (писатель — поток воркера, читатель — поток heartbeat, третий —
  поток остановки плагина). Вторая редакция при этом **сняла больше, чем добавила**: три merge
  тика схлопнулись в один, политика наложения удалена целиком, отбор по каталогу ЗАМЕНЁН (не
  дополнен) проверкой владельца.

**Последствия.** У плагина появляется пятый разъём наблюдаемости; контекст, собранный вручную,
обязан нести `declare_metric`/`publish_metric` — как уже обязан нести `write_event` и `flight_dump`.
Два плагина ОДНОГО процесса, объявившие одно имя, получают `ValueError` на `configure` — громко и
намеренно: тихий выбор «побеждает последний» сделал бы показание функцией порядка импортов.
`forget_declarations` получила точечную форму (`names=...`): восстановление реестра повторным
объявлением подменяет ВЛАДЕЛЬЦА и превращает законный reload соседа в отказ — со второй редакции
это уже не гигиена, а корректность: подменённый владелец ломает сам отбор.

---

### Вторая редакция (2026-08-16): владение стережётся при публикации

**Блокер, из-за которого редакция понадобилась — воспроизведён запуском, не выведен.** Продовое
правило троттла `processes.**.state.fps: 0.05` пропускает одну запись на путь за окно. Оба merge
тика приходили в **0.5 мс** друг от друга, а сетка `time.monotonic` на Windows — **15.6 мс**, то
есть оба прихода читали один таймстамп и попадали в одно окно ВСЕГДА. Агрегат шёл первым,
плагинный `fps` вырезался вторым: merge №2 возвращал `proceed=True` с `payload={'frame_count': 40,
'drops': 0}` и **без** `rejection_reason` — потерю не видел даже отправитель. Контроль: тот же
merge без агрегата в окне проходит с `fps`; разнос на +0.051 с проходит. Наблюдаемое следствие:
оператор при остановленном захвате видел **21.4** (частота цикла воркера) вместо **0.0**. До
миграции записи разносило по фазе случайно, поэтому дефект был перемежающимся.

**Диагноз независимого разбора:** инвариант «один лист — одно значение — один владелец» существовал
только на этапе ОБЪЯВЛЕНИЯ и не действовал на этапе ПУБЛИКАЦИИ; разрешение конфликта было
делегировано транспорту (порядок прибытия + окно троттла), у которого нет для этой роли ни
семантики, ни голоса.

**Р3.5-11. Владение стережётся при публикации.** `PluginLevels` ключуется **парой
`(имя, публикатор)`**; `build_plugin_levels` берёт лист, только если объявленный владелец имени
равен публикатору, остальные претенденты на то же имя уходят в отсев — каждый своей тройкой.

**Ключ — пара, а не имя, и это найдено инъекцией, а не рассуждением** (2026-08-17). Первая
редакция этой правки ключевала хранилище ОДНИМ именем и клала рядом публикатора. Инъекция И1
(«вернуть отбор по членству в каталоге») дала **ноль** красных на обоих тестах П1 и на авторском
тесте имени-дубля: все трое сторожили имя ФРЕЙМВОРКА (`fps`), а его в дереве защищает не владение,
а fail-safe порядок сборки — уровни плагинов ложатся первыми, агрегат накрывает их сверху в том же
dict'е. По этому следу написан тест на случай, где страховки нет по построению: **сосед пишет в имя,
объявленное ДРУГИМ ПЛАГИНОМ** (оба уровня едут одним проходом `_collect_plugin_levels`, в один
словарь). Он вскрыл дефект хуже ожидаемого:

```
plugin_a.declare_metric("shared_gauge"); plugin_a.publish_metric("shared_gauge", 11.0)
plugin_b.publish_metric("shared_gauge", 99.0)      # чужое имя, объявления нет
тик -> дерево: shared_gauge = None                 (ожидалось 11.0)
```

Публикация соседа **затирала ячейку владельца**, сборщик отбрасывал затёртое по несовпадению
владельца — и лист исчезал целиком. Перехватчик не мог подменить чужое число, но мог его
**уничтожить**, и хватало одной опечатки в имени у соседнего плагина. Прямое нарушение П1 («в
дереве по этому пути остаётся значение владельца») и тот же класс, который задача чинит: конфликт
разрешало не владение, а порядок — теперь порядок вызовов `publish_metric`. Ключ-пара убирает
причину: запись владельца физически не может быть затёрта чужой.

Проверять владение прямо в `publish_metric` — отвергнуто: сломалось бы уже зафиксированное
поведение «отдал до объявления» (`test_publishing_before_declaring_keeps_the_value_and_says_it_once`),
на момент публикации объявления законно ещё нет. Ключ-пара сохраняет и его.

Голос дедуплицируется тоже **по паре**: дедуп по имени молча проглатывал бы перехватчика,
появившегося ПОЗЖЕ первого (ленивый импорт, hot-apply рецепта) — про имя «уже сказано», хотя
сказано было про другого виновника. Это тоже промах предсказания, а не догадка: инъекция «дедуп
по имени» сперва дала ноль красных, потому что первый тест сажал обоих перехватчиков в один тик,
где множество названных ещё пусто; тест переписан на разнесение по тикам. Владельца реестр знал всегда (на нём стоит отказ `_declare` второму объявителю), но
наружу не отдавал — добавлена `observability_declarations.metric_owners()`, зеркало
`declared_sources()`. Прежний отбор «имя есть в `declared_metrics()`» **заменён**, а не дополнен:
он отвечал на вопрос «такое имя кто-нибудь объявлял», и этого хватало ровно до второго писателя.
Гейтируемость сохраняется даром — лист, чей владелец совпал с публикатором, объявлен по построению
проверки, а `TelemetryGate` обходит тот же каталог.

Владелец вычисляется в ОДНОМ месте — `PluginContext._metric_owner()`, — и им пользуются все три
дороги: объявление, публикация, снятие. Выражение писалось бы одинаково во всех трёх, и разойдись
они хоть в одном звене, уровень либо не поехал бы, либо не снялся бы на остановке.

**Р3.5-12. Один merge на тик.** `_publish_metrics_to_tree`, `_publish_router_shm_stats_to_tree` и
`_publish_plugin_levels_to_tree` схлопнуты в `_publish_telemetry_to_tree`: воркеры + агрегат +
`shm` + уровни плагинов в ОДНОМ payload под `processes.<name>`. Это возврат к собственному принципу
системы (E6/Task 5.7, «один merge вместо 3W+2 set»), который первая редакция нарушила. Троттлу
больше нечего арбитрировать — не по договорённости, а потому что арбитрировать больше нечего;
побочно 3 IPC-сообщения на тик → 1.

Три ловушки объединения обработаны явно и сторожатся тестами поимённо:

1. ранний выход `not workers` жил в воркерном публикаторе и глотал только воркерные листья —
   `shm` и уровни ехали своими merge. В объединённой сборке он проглотил бы всё, поэтому его нет;
2. политика «все счётчики `shm` нулевые → не грузим дерево» — политика ПУБЛИКАТОРА, и она уцелела
   внутри общей сборки, а не исчезла вместе со снятым методом;
3. данных нет вовсе → НОЛЬ вызовов merge, а не пустой merge.

**Порядок наложения внутри payload — fail-safe, а не политика.** Уровни плагинов кладутся ПЕРВЫМИ,
агрегат фреймворка — поверх. Спор за имя до сборки не доходит: его снимает проверка владельца.

Насколько порядок страхует — **измерено, а не заявлено** (ревью З1). Прежняя формулировка обещала
«виден будет уровень фреймворка, а не подменённый»; инъекция «отбор по каталогу вместо владения»
показала, что порядок спасает **1 случай из 5** и только когда агрегат есть на том же тике:
`fps` при живом воркере — спас (`8.0`); `fps` без воркеров, `latency_ms` без замера латентности,
`effective_hz`, `shm` при нулевых счётчиках — **не спас** (`99.0` доехало, у `shm` скаляром на
месте поддерева). Честная формулировка узкая: порядок страхует `fps`/`latency_ms` при наличии
агрегата, и ничего больше. Единственный настоящий предохранитель — проверка владельца. Прежняя редакция имела ОБРАТНЫЙ порядок и называла его несущей политикой («плагин
побеждает»); политика снята целиком — и сама, и её зеркала в докстрингах `current_levels_snapshot`
и `CapturePlugin._publish_levels`. Она и не работала: троттл вырезал лист молча.

**Р3.5-13/Р3.5-15. Две величины — два имени.** Коллизия была не только в доставке, но и в МОДЕЛИ
ДАННЫХ: под `fps` ехали `max(effective_hz)` по running-воркерам (частота ЦИКЛА) и измеренная
частота захвата камеры. Даже при идеальной доставке лист осциллировал бы. `fps` остаётся именем
фреймворка; `CapturePlugin` объявляет и публикует **`capture_fps`** — имя называет и величину, и
владельца. Отвергнуты: `measured_fps` («измеренный кем?»), `frame_rate` (коллизия по смыслу с
настроенным `cam.actual.fps`, который пишет `camera_service`), `cam_fps` (коллизия с поддеревом
`cam.*` ДРУГОГО плагина).

Прикладной слой: glob троттла, подписи графика процесса, подпись метрики системного дашборда
(`_system_dashboard.py` — найдена грепом при исполнении, в разборе названа не была). Метка `fps`
во всех местах стала «Циклов/с»: иначе задача сняла бы ложь метки с карточки и перенесла её на
график. Схема стока и `ALLOWED_METRICS` НЕ тронуты — неизвестный лист `state.*` уезжает в
JSON-колонку `extra` (`Plugins/io/telemetry_sink/plugin.py:221-226`), то есть `capture_fps`
персистится сам, без миграции.

**Где показывается `capture_fps` — поправка владельца 2026-08-17.** Первая реализация дала ему
слот «Кадров/с» на карточке процесса (вердикт арбитра). Владелец это отменил: карточка —
generic-виджет, `_METRIC_KEYS` константа на ВСЕ процессы, и прикладное понятие «кадры» в
универсальном месте даёт вечный прочерк шести процессам из семи, а следующий домен принёс бы
«Изделий/с». Правило: **карточка показывает то, чем владеет фреймворк**. Измеренная частота
переехала в секцию «Камера (actual)» инспектора строкой «FPS (измеренный):» рядом с «FPS (по
драйверу):» (`cap.get`); подписи разведены, потому что иначе одна ложь менялась бы на другую.
Попутно исправлена посылка постановки: `camera_service` и `capture` **никогда** не живут в одном
процессе (проверено по всем 14 рецептам) — гейт секции расширен с `== "camera_service"` до
`in {"camera_service", "capture"}`, иначе новая строка была бы мертва во всех рецептах.

**Ступенька в исторической серии названа.** В колонке `fps` у `camera_0` до 2026-08-16 лежит
измеренная частота захвата (~12.5), после — частота цикла воркера (~21.4). Миграция данных не
делается намеренно: смена смысла — дефект только когда она не названа. Первоклассная колонка для
`capture_fps` — строкой в QUEUE с адресом (`schemas.py` + `ALLOWED_METRICS` + `list_range`), по
образцу вычеркнутого `state.pid`.

**Р3.5-14. Свежесть жизненным циклом.** `PluginLevels.retract(owner)` зовёт ФРЕЙМВОРК в
`ProcessModulePlugin._do_shutdown`, в блоке `finally` вокруг пользовательского `shutdown`.
Автоматика, а не «каждый плагин зовёт сам»: свойство, которое держится на памяти автора плагина,
свойством не является. TTL и штампов свежести на листьях не заведено. Снимается ПУБЛИКАЦИЯ, не
объявление: поднятый заново плагин объявится тем же владельцем (это не конфликт), а забытое
объявление восстанавливать было бы некому.

**Н1 (ревью, 2026-08-17): «уровень мёртвого исчезает» было НЕПРАВДОЙ, и правда стоила ещё одной
записи в дерево.** `retract` снимал публикацию — payload следующего тика становился чист, — а лист
в дереве жил вечно с последним значением:

```
plugin_a: probe_level = 12.5 -> тик -> _do_shutdown (retract снял 1) -> тик
payload тика 1 : {'state': {'probe_level': 12.5}}
payload тика 2 : merge не отправлен вовсе          <- payload чист, как и обещано
ДЕРЕВО         : processes.pa.state = {'probe_level': 12.5}   <- живёт вечно
```

Живьём свойство держалось лишь тем, что `CapturePlugin` сам публикует `0.0` в своём `shutdown`, —
то есть ровно «на памяти автора плагина», чего механизм обещал не допускать. Теперь `retract`
откладывает имя, и ближайшие тики говорят дереву `None` — **ограниченное число раз**
(`PluginLevels.pending_retractions` / `confirm_retracted`, см. поправку S-1 ниже: первая редакция
говорила ровно один раз, и это была вторая неправда на том же шве).

Развилка решена в пользу «сделать свойство настоящим», но НЕ новой дорогой записи:

| Вариант | Почему не он |
|---|---|
| Переписать утверждение честно («лист держит последнее значение») | оставляет оператора с показанием мёртвого плагина и возвращает гарантию на память авторов плагинов — то, что задача и убирала |
| `state.delete` на снятые имена | у `StateProxy` метода `delete` **нет** (есть только `handle_state_delete` на менеджере) — это новая публичная дорога записи в чужом модуле, с отдельными вопросами «кто владелец удаления», «под гейтом ли», «что видит подписчик». Цена не окупается: живой источник снятия сегодня один — teardown процесса. Названный апгрейд, а не отказ навсегда. **[Апгрейд состоялся 2026-08-23: `StateProxy.delete` заведён Task 2.1, снятие поддерева писателя зовёт его из тика (Ф2, Task 2.2). Строка читается как история развилки, а не как факт о коде.]** |
| `None` тем же merge (**принято**) | та же дорога, тот же владелец, то же сообщение; потребители уже готовы — VM-сеттер карточки рисует «—» на нечисловом, сток пишет NULL. Разница названа: ключ листа остаётся, значение становится «нет показания» |

Снятие идёт **вне гейта**, как `status` воркеров: гейт управляет ЧАСТОТОЙ уровня, а снятие —
однократный факт. Пропусти его гейт — и у выключенной метрики лист остался бы навсегда с мёртвым
числом, то есть гейт порождал бы ту самую ложь, которую снятие убирает. Живое значение на том же
тике побеждает отложенное снятие (плагин мог быть поднят заново).

**Граница, которую Н1 не закрывает и которая теперь названа:** живая дорога `stop_capture`
`_do_shutdown` НЕ зовёт — плагин остаётся `RUNNING`, и его уровни обязаны продолжать течь. То, что
`CapturePlugin` публикует там `0.0`, — не костыль, а плагин, сообщающий собственное состояние; это
его работа, а не подмена механизма. Механизм отвечает за ОСТАНОВЛЕННЫЙ плагин.

**Ссылка на прецедент `throttle.prune` при `state.delete` снята как неверная:** `prune` существует,
но `state.delete` на `processes.<name>` не зовёт НИКТО во фреймворке и прототипе (проверено грепом
2026-08-17). Прецедента не было — было намерение в докстринге соседнего модуля.
**[Устарело 2026-08-23: вызывающий появился — тик heartbeat'а шлёт `state.delete` на
`processes.<p>.state.plugins.<писатель>` (Ф2, Task 2.2), и `throttle.prune` на этой дороге теперь
работает не в вакууме. Проверка грепом 2026-08-17 была верна на своём коммите.]**

**S-1 (сквозное ревью этапа 6, 2026-08-17): «один раз» означало «навсегда, если не доехало».**
Н1 сделала снятие настоящим, но отдала имя РОВНО ОДИН раз и вычеркнула его **до** попытки
отправить. `proxy.merge` обёрнут в `except Exception`, значит любой отказ доставки — исключение
или тихая потеря сообщения на транспорте — хоронил снятие безвозвратно:

```
retract -> тик: take_retracted() вычеркнул 'probe_level'
              -> proxy.merge(...) БРОСИЛ (или сообщение потерялось)
              -> except: залогировали и пошли дальше
следующий тик : payload чист, имени в хранилище больше нет
ДЕРЕВО        : processes.pa.state = {'probe_level': 12.5}   <- мёртвое число, навсегда
```

Это был **единственный payload тика, не восстанавливающий себя сам**: все прочие уровни
переотправляются каждым тиком, и потеря одного сообщения им ничем не грозит. Асимметрию видно
только на отказной дороге — то есть там, где показания как раз и важны.

Форма починки:

* `_retracted` — не множество, а `dict[str, int]`: имя → сколько **успешных** утверждений дереву
  ему ещё должны. `retract` ставит `RETRACTION_REASSERT_TICKS = 3` (присваивание, не сумма:
  повторное снятие даёт полный запас, а не копит долг);
* `pending_retractions()` — чтение **без дренажа**, возвращает копию имён;
* `confirm_retracted(names)` — списание, зовётся публикатором **после** `merge`, вернувшегося без
  исключения, и только для имён, реально попавших в payload;
* провалившийся такт запас **не расходует** — иначе три провала подряд съели бы его целиком, и
  починка «повторяем на случай потери» не чинила бы ровно свой случай;
* `publish(name, owner)` убирает имя целиком: плагин, поднятый заново, не получает `None` вдогонку.

**Прежний довод против повтора остаётся верным и ничего не запрещает.** Он был против
БЕСКОНЕЧНОГО повтора: «показания нет» — не уровень, и вечная дельта на мёртвый путь есть ровно тот
трафик, который задача убирала. Здесь повтор конечен и тратится только на успехах.

**Цена названа числом.** Плагин с N уровнями при остановке добавляет N ключей в секцию `state` на 3
такта — 3N лишних листьев суммарно, потом ноль. Это событие **teardown'а, а не установившийся
режим**: в стабильно работающем процессе множество пусто и цена ровно нулевая.

Почему 3, а не «пока не подтвердят»: подтверждения о доставке у этой дороги нет вовсе — `merge`
асинхронен, и «без исключения» означает «положили в очередь», а не «дерево приняло». Конечный запас
покрывает потерю одного сообщения и не превращает снятие в вечный уровень.

**Обновлённый тест назван поимённо, а не удалён:**
`test_plugin_levels_hazards.py::TestRetractedLevelLeavesTheTree::test_the_notice_goes_out_once_not_every_tick`
→ `test_the_notice_stops_after_the_bounded_reassertion`. Он пинил верное утверждение неверного
контракта; исходную опасность («нет показания» стало вечным уровнем) он держит по-прежнему, просто
предел теперь 3, а не 1. Добавлена и нижняя граница: без неё тест был бы зелёным и на реализации,
которая не шлёт снятие вовсе.

**Н2 (ревью): исключение в пользовательском `shutdown` оставляло уровни навсегда.** Снятие стояло
ПОСЛЕ незавёрнутого `self.shutdown(ctx)`. Плагин, чей `shutdown` бросил, оставлял уровни в
хранилище: `STOPPED` не наступал, оркестратор бросок логировал и шёл дальше, три следующих тика
публиковали `{'state': {'boom_level': 7.7}}`. Симптом «камера остановлена, а частота идёт»
воскресал ровно на отказной дороге — там, где диагностика нужнее всего. Снятие переехало в
`finally`; бросок по-прежнему уходит наружу и `STOPPED` не наступает.

**Н3 (ревью): точка в имени уровня — теперь отказ, а не резидуал.** Объединение трёх merge в один
сделало достижимыми ОБЕ ветки резолва точки в `TreeStore._merge_recursive`: на первом тике ключ
ложится дословно (`state['a.b.c']`), со второго дифф отдаёт per-leaf дельту с путём
`…state.a.b.c`, и она резолвится как вложенный путь. Обе встречаются в одном узле:

```
ПРЕЖНИЙ (3 merge): state = {'fps': 8.1, 'a': {'b': {'c': 2.0}}}
НОВЫЙ   (1 merge): state = {'a.b.c': 1.0, 'fps': 8.1, 'a': {'b': {'c': 2.0}}}
                            ^^^^^^^^^^^ заморожен на первом тике, голоса нет
```

Вечно-мёртвого двойника добавила ИМЕННО эта задача — значит она его и закрывает.
`ctx.declare_metric` отказывает на точке (`ValueError` с годным именем в тексте). Одного guard'а
достаточно: имя, которое нельзя объявить, до дерева не доходит — его отвергает проверка владения.
Плоскость stats точечные имена принимает и дальше (`capture.fps`): там имя путём дерева не
становится.

**Отвергнуто с причиной.**

| Вариант | Почему нет |
|---|---|
| Узаконить наложение порядком | узаконивает гонку; на Windows-часах фаза внутри тика недостоверна (15.6 мс против 0.5 мс между merge) |
| Научить троттл приоритетам или ключу «(путь, источник)» | троттл стал бы вторым авторитетом частоты — откат ADR-PM-017. При таком ключе обе записи прошли бы, но в дереве всё равно одно значение: победил бы последний |
| Снять правила троттла со `state.*` | убирает предохранитель от runaway-публикатора, владения не лечит |
| Штамп свежести на каждом листе | удваивает дерево ради того, что даёт lifecycle-хук |
| Убрать агрегатный `fps` фреймворка | потеря универсального уровня ради одного приложения |
| «Просто снять дубль» (предложение ревью) | ход правильный, но частный: без Р3.5-11 следующий плагин снова опубликует в чужое имя, без Р3.5-12 следующая пара merge снова будет арбитрироваться троттлом. Как одиночная правка — лечение симптома со сроком годности |
| Первоклассная колонка БД под `capture_fps` | миграция схемы + вторая серия графика + whitelist — вторая задача под видом первой; потребителя колонки никто не доказал |
| Не давать `capture_fps` слота на карточке | секция «Камера (actual)» показывает НАСТРОЕННЫЙ fps (`cap.get`, пишет `camera_service`), а не измеренный — измеренная частота не была бы видна в GUI нигде, то есть лист без единого читателя |

**Названный риск, проверенный прогоном.** Один укрупнённый merge вместо трёх мог бы слить per-leaf
дельты подписок. Проверено на настоящем `StateStoreManager` + `SubscriptionManager` +
`DeltaDispatcher`: один merge из десяти листьев даёт подписчику `processes.camX.state.**` тот же
набор per-leaf дельт, что три раздельных merge с той же разбивкой
(`test_plugin_levels_ownership_acceptance.py::TestP10`).

**Резидуал закрыт, а не унаследован.** Точечное имя уровня было записано резидуалом; ревью
показало, что после объединения merge это уже не резидуал, а вечно-мёртвый лист-двойник, который
добавила эта задача. Закрыт отказом в `declare_metric` — см. Н3 выше.

### Пределы и формы, названные ревью (З2, З3, мелкое)

**З2 — предел голоса есть, предела хранилища нет.** 5000 публикаций в необъявленные имена от
одного плагина давали ОДНУ строку WARNING длиной **289 107 символов** — голос сам стал инцидентом
(прежний формат дал бы ~60 КБ, то есть новый формат подорожал впятеро). Голос обрезан по 10
записям с хвостом «…и ещё M»: назвать виновника достаточно, воспроизводить его вход не нужно.
merge при этом 0 и второй тик молчит — это было верно и осталось.

Потолок `PluginLevels` назван вслух: **предела нет**, он равен |объявленных имён × публикаторов|
(было |имён|). Тот же прогон дал 5000 записей в хранилище и 5000 пар в `_warned_rejected_levels`.
Это **runaway-плагин, а не режим работы**: имя уровня пишут руками рядом с вычислением, генерировать
их незачем. Кап не заводится, пока такого писателя нет — завести его значило бы решать, какой
уровень выбросить, не имея ни одного случая для правила. Помечено `ponytail:` в обоих местах.

**З3 — боевая форма merge даёт на первом тике ОДНУ грубую дельту.** Приёмочный П10 мержит прямо в
`processes.<p>.state` и потому измеряет per-leaf всегда; тик шлёт `merge("processes.<p>",
{"state": {...}})` — на уровень выше. Измерено на настоящем `StateStoreManager`:

```
тик 1: ['processes.P.state']                                    parts=3
тик 2: ['processes.P.state.capture_fps', 'processes.P.state.fps'] parts=4
```

Следствие названо: сток телеметрии берёт только `len(parts) >= 4`
(`Plugins/io/telemetry_sink/plugin.py`), поэтому **первый тик после старта процесса он пропускает
целиком**. Раньше это касалось `fps`/`latency_ms` (они и так ехали под `processes.<p>`), а группа
`shm` мержилась ГЛУБЖЕ (`…state.shm`) и была per-leaf с первого тика — теперь она едет вместе с
остальными. Один тик, не поток; покрыто тестом боевой формы.

**Живое подтверждение «две РАЗНЫЕ величины» получено на ОСТАНОВКЕ захвата**, а не на расхождении
при работе: `capture_fps: 0.0` против `fps: 21.4`. На стенде источник — симулятор, привязанный к
тому же циклу воркера, поэтому при работе оба дают 21.3, и расхождение там не наблюдаемо. Разными
величины делает не разница чисел на стенде, а разное определение (частота цикла против прочитанных
кадров) — и именно оно проявляется, когда захват встал, а воркер тикает.

**`PluginLevels.snapshot()` — контракт с приёмочным набором, а не мёртвый путь.** Боевых
вызывающих у него нет: сборщик читает `publications()` (ему нужен публикатор). `snapshot()`
отвечает на «какие сейчас значения» без вопроса «чьи», и этим пользуется независимая приёмка П8,
судящая «что плагин отдал» без обращения к внутренностям владения. Решение: **оставить как
тестовый/диагностический аксессор и назвать это в докстринге** — удалить его значило бы заставить
приёмочный тест читать пары и тем самым пинить внутреннюю форму хранилища, чего он делать не
должен. Оспоренное имя в проекции схлопывается, и это тоже названо: проекция ничего не решает.

**Дополнение 2026-08-19 (Ф0 Task 0.2 плана `plans/observation-port/plan.md`): владение — это ещё
и право СНЯТЬ лист, а не только право его занять.** Текст выше не переписан: вторая редакция
поставила арбитра владения на ПУБЛИКАЦИЮ и на сборку, но снятие оставила поимённым, без
владельца. Ревью S-8 нашло четыре живых дефекта одного корня, независимая приёмка их
воспроизвела (`test_plugin_levels_defect_quartet_acceptance.py`), и все четыре — про то, что
решение «чей это лист» принималось в трёх местах по трём правилам.

Что измерено ДО ремонта:

* **Д1.** Самозванец публикует в объявленное, но ещё не публиковавшееся имя владельца и штатно
  уходит → в дереве появляется лист `{'quartet_d1_level': None}`. Значение самозванца (999) не
  просачивалось никогда — а вот надгробие от него легло, и имени, у которого показания никогда не
  было, дерево стало приписывать «показания нет».
* **Д2'.** Гейт активен (`default_interval_sec` 5 с при шаге тика 1 с). Владелец опубликовал `10`
  на тике 1; перехватчик, имени не объявлявший, публикует в то же имя и уходит; на тике 2
  `due_metrics` пуст → лист владельца становится `None`. Без гейта дефект НЕ виден: сборщик кладёт
  свежее значение владельца поверх надгробия и маскирует его. То есть симптом появляется ровно там,
  где гейт работает как задумано.
* **Д3.** Владелец снял метрику, самозванец продолжает публиковать в это имя → снятие не доехало
  **ни разу за 3 тика** (весь запас `RETRACTION_REASSERT_TICKS`), потому что чужая публикация
  отменяла запас по имени. Контроль без самозванца: снятие доезжает первым же тиком.
* **Д4, вторая половина (проводка).** `PluginOrchestrator.plugins` — реестр для shutdown
  (инвариант H-2: плагин с упавшим `configure()` остаётся в списках, иначе некому освободить уже
  захваченный ресурс). `GenericProcess._init_data_pipeline` читал его как «живые плагины»: в
  реестре `create_worker` стояло `['source_producer_hazard_bad_source',
  'source_producer_hazard_good_source']`, и `SourceProducer.run_loop` звал `produce()` у плагина в
  IDLE — **7 вызовов за 0.2 с**, у плагина, чей `configure()` не отработал.

Решение — четыре точки, ни одного нового механизма:

1. `PluginLevels.retract` откладывает снятие ТОЛЬКО для имён, где уходящий — объявленный владелец.
   Его публикации в чужие имена по-прежнему удаляются (это его записи), но надгробие на чужой лист
   он не кладёт. Диагональ «перехватчик уходит, владелец жив» теперь разобрана в докстринге, а не
   только упомянута.
2. `PluginLevels.publish` отменяет отложенное снятие ТОЛЬКО когда публикует владелец имени.
   Случай «отдал ДО объявления» не задет и разобран явно: владельца на тот момент нет, значит и
   отмены нет, а отменять там нечего по построению — в `_retracted` попадают только объявленные
   имена своего владельца. Само значение, как и прежде, сохраняется безусловно.
3. «Живое побеждает» в тике heartbeat сверяется с ДО-гейтовым владельческим срезом, а не с
   пост-гейтовым payload'ом. Лист, который гейт придержал на этом тике, показание ИМЕЕТ. Второго
   сборщика и второго прохода по хранилищу это не стоило: гейт в `build_plugin_levels` — чистый
   фильтр имени ПОСЛЕ отбора по владению, поэтому тик собирает срез один раз без гейта и
   фильтрует его на месте (Р3.5-12 «один merge за тик» не тронут). Равенство двух дорог сторожит
   авторский тест — иначе расхождение push/poll было бы видно только на стенде.
4. Фаза 2 оркестратора зовёт `_do_start` только для плагинов в READY, а проводка данных создаёт
   рабочий поток только **источникам** в RUNNING. H-2 сохраняется буквально: не поднявшийся
   остаётся в `_plugins`/`_contexts` ради shutdown — он просто не стартует и не получает воркер
   (стало **1** воркер вместо 2), и каждое такое исключение проговаривается в журнал поимённо.
   Раньше защита срабатывала этажом ниже (`_do_start` требует READY), ценой лживой строки журнала
   «start() в состоянии idle» на каждый упавший плагин: отказ `configure()` выглядел вторым,
   независимым отказом старта.

   **Формулировка «упал configure» была узкой** (ревью, итерация 1): `_do_start` ставит RUNNING
   ПОСЛЕ вызова `start(ctx)` (`plugins/base.py::_do_start`), поэтому фильтр отсекает и плагин,
   чей **`start()`** бросил (он остаётся в READY). Верное условие — «не дошёл до RUNNING»,
   независимо от того, на каком из двух шагов отказал.

   **Фильтр стоит ТОЛЬКО на источниках, и это граница, а не экономия** (блокер ревью, итерация 1).
   Первая редакция правки фильтровала список ДО разделения на source/processing и тем снимала
   механизм фреймворка: у processing-плагина позиция в списке — штатная дорога предохранителя.
   `PipelineExecutor._build_active_steps` ставит `SuspectTagStep` НА ПОЗИЦИЮ критического
   bypassed-плагина, а `PluginOperationStep` тегирует `inspection_status="not_inspected"`.
   Воспроизведено (боевой boot, критический processing-плагин с падающим `configure`,
   `error_max_consecutive_fails=1`): с широким фильтром `PipelineExecutor._plugins =
   ['passthrough']`, на выходе `{'bottle_id': 2, 'frame': 'f'}` — `inspection_status`
   ОТСУТСТВУЕТ; со списком оркестратора `_plugins = ['critical_inspector', 'passthrough']`,
   проход 1 → `inspection_status: 'not_inspected'`, проход 2 → `'suspect'`. То есть батч уезжал
   молча, как будто инспекция была. Сегодня латентно (`error_critical_plugins` в прод-конфигах не
   выставлен, читателей `inspection_status` вне фреймворка нет), но снятый механизм фреймворка —
   ровно тот случай, ради которого правило framework-first и написано.

**Отвергнуто: проверка состояния плагина внутри `SourceProducer.run_loop`.** Она сделала бы
зелёным приёмочный тест `test_d4_source_producer_still_calls_produce_without_state_gate`, но
контракт исполнителя («дали плагин — зову produce») запинен двумя боевыми тестами
(`test_cycle_metrics.py::test_source_producer_reports_hz` гоняет цикл на плагине в IDLE,
`test_frame_log_correlation.py::test_source_records_carry_the_freshly_born_trace` — на утином
объекте БЕЗ атрибута `state`, для которого проверка стала бы молчаливой дырой). Решение «кому
нельзя работать» принимается на проводке, где известна причина; тот тест помечен
`xfail(strict=True)` с указанием, что именно проверено, а остаток занесён в `plans/QUEUE.md` как
S-31 (перенести решение о годности в единый шов вызова `PluginRunner`).

**Цена вопроса «чьё это имя» на горячем пути названа числом** (ревью, итерация 1). Правка 2
спрашивает владение в КАЖДОМ `publish`, а `publish` зовут потоки воркеров. Замер (20 000 вызовов
`PluginLevels.publish`): база до правки **0.27 мкс/вызов**; через `metric_owners()` (копия среза
реестра под процессным локом) — **1.14** при 3 объявленных метриках, **4.52** при 50, **33.35**
при 500, то есть линейно по реестру. Заведено точечное чтение `metric_owner(name)` в
`observability_declarations` (одно обращение к словарю под тем же локом, без копии) — после него
**0.57 / 0.59 / 0.59 мкс** на тех же 3 / 50 / 500 объявлениях: зависимость от размера реестра
снята, остаток над базой — один lookup и захват лока. `retract` по-прежнему берёт всю карту
(`metric_owners()`): он редкий, и точечная функция обошлась бы ему дороже.

**Живая ручка «выключить плагин» в проде ЕСТЬ, но снятия не порождает** (уточнение ревью):
`PluginOrchestrator.set_enabled` проверяется только в `PluginRunner.call_process`, состояния
плагина не меняет и `_do_shutdown` не зовёт. Вывод «снятию не на чем доехать» в силе — неточной
была посылка «ручки нет вовсе».

**Побочная находка ремонта: авторский тест пинил дефект как контракт.**
`test_plugin_level_retraction_hazards.py::test_a_live_value_from_ANOTHER_publisher_also_cancels_by_name`
утверждал «отмена идёт по ИМЕНИ, кто бы ни публиковал», с верным доводом («лист в дереве один») и
неверным выводом. Тест перевёрнут, а не удалён, и причина названа в его докстринге. Там же
вскрылось второе: пять тестов того же файла работали с НЕОБЪЯВЛЕННЫМИ именами, то есть на входе,
которого у механизма больше нет, а ещё пять при этом оставались зелёными ВАКУУМНО (при пустом
`_retracted` любое отрицание истинно). Файл получил явную предпосылку — объявление имён фикстурой.

**Счёт починки вакуума был завышен и исправлен ревью (итерация 1): предпосылку получили все пять,
но ЯКОРЬ — сначала только два.** Предпосылка возвращает тесту вход, но не делает его способным
покраснеть: под инъекцией «`retract` перестал откладывать» три теста
(`test_over_confirming_does_not_drive_the_counter_negative`,
`test_a_live_value_removes_the_name_entirely`, `test_confirming_an_unknown_name_is_silent`)
оставались зелёными, потому что все их assert'ы — отрицания. Каждому добавлен якорь
существования в том же тесте (`pending_retractions() == {"probe"}` до отрицания); потоковый
получил `max_seen > 1` — «словарь запасов реально рос во время чтения».

**Снято уверенное объяснение без воспроизведения.** Докстринг потокового теста утверждал, что
`set(self._retracted)` под вставкой из другого потока поднимает `RuntimeError` и тем ловит снятый
лок. Измерено инъекцией «лок снят»: **10 из 10** прогонов зелёные в обеих редакциях — в CPython
3.12 `set(d)` идёт одной C-итерацией под GIL. Объяснение заменено на то, что тест сторожит на
самом деле (три роли ходят по хранилищу одновременно, ни одна не падает, множество непусто).

### ADR-PM-038 — дополнение по Ф1 «порта наблюдений» (2026-08-20, Task 1.2): владение = путь, арбитраж удалён целиком

**Статус раздела «Владение стережётся при публикации» и всего, что к нему привязано (Р3.5-11,
голос про самозванца, парный ключ, `metric_owners()`, поимённое снятие) — ОТМЕНЁН этим
дополнением.** Формулировки «Правило второе: публикуй в СВОЁ имя» и «Хранилище ключуется парой
`(имя, публикатор)`», которыми README.md модуля до 2026-08-20 описывал вторую редакцию, относятся
к УДАЛЁННОМУ механизму — README правится этим же коммитом.

**Контекст.** Вторая редакция (выше, Р3.5-11…Р3.5-15) закрыла конкретный блокер — публикация
соседа затирала ячейку владельца, — но не закрыла класс. Разбор `plans/observation-port/plan.md`
§1 (досье S-8, 2026-08-19) насчитал у плоскости уровней **шесть уникальных машин**: каталог
владения, парный ключ, арбитр owner==publisher, поимённое снятие с запасом переутверждений, голос
про самозванца — которых нет ни у одного из 27 модулей фреймворка. Решение «чей это лист»
принималось в ТРЁХ местах по ТРЁМ правилам (объявление, публикация, снятие), и это разночтение
дало четыре живых дефекта одного корня (A1, A2, B, отмена снятия чужой публикацией — разобраны
дополнением 2026-08-19 выше). Арбитраж лечил симптомы на границе трёх правил; корень — сама идея,
что ИМЯ является адресом, за который можно спорить.

**Решение владельца (2026-08-19, дословно): «Тоже самое как сделано для общения —
router_manager, command_manager, channel_routing_module и тп. Использовать готовые модули и
инструменты по максимуму… сделать один порт наблюдений».** Из него выведен принцип конструкции:
**владение = путь.** Каждый писатель публикует только в своё поддерево — ровно как воркеры уже
публикуют в `workers.<w>.*`, а health-репортер подписывает записи своим контекстом
(`process_module/health/state.py:422-431`). Уровень плагина теперь адресуется путём
`processes.<процесс>.state.plugins.<писатель>.<имя>` (`heartbeat/telemetry.py::PLUGINS_SUBTREE_KEY`,
`PluginLevels`), а не парой `(имя, публикатор)`. Два плагина, объявившие одинаковое имя метрики,
дают ДВА РАЗНЫХ листа дерева (`plugins.a.fps` и `plugins.b.fps`) — спорить за имя стало
**синтаксически невозможно**: конфликт не разрешается проверкой, а перестаёт быть достижимым
состоянием, потому что писатель — сегмент пути, а не значение поля.

**Почему не «починить парный ключ дальше» (отвергнутая альтернатива).** Вторая редакция уже была
починкой того же рода — с парного ключа на дедуп по паре, на конечный запас переутверждений — и
каждая починка закрывала один найденный дефект, оставляя класс живым (S-8 насчитал четвёртый
дефект того же корня уже ПОСЛЕ второй редакции, дополнение 2026-08-19). Очередная починка сузила
бы вероятность, но не убрала бы сам вопрос «чей это лист», который и порождает класс. Отвергнуто
владельцем как лечение симптома.

**Что удалено поимённо** (полная инвентаризация — `plans/observation-port/plan.md` §9, блок Ф1;
Task 1.1 того же плана — инвентарь читателей ДО удаления):

1. **Арбитр owner==publisher** — сверка объявленного владельца имени с публикатором при сборке
   дерева (`build_plugin_levels`, ветка `owner is None or owner != publisher` прежней редакции).
   Сборщик стал чистой проекцией хранилища `writer → {имя → значение}` в поддерево
   `{"plugins": {писатель: {имя: значение}}}` — второго прохода с отбором нет.
2. **Ключ-пара `(имя, публикатор)`** в `PluginLevels._values` — заменён на двухуровневый
   `писатель → {имя → значение}` (путь ownership, `heartbeat/telemetry.py::PluginLevels`).
3. **`observability_declarations.metric_owners()` и точечный `metric_owner(name)`** — сняты
   вместе с каталожным владением метрик. У метрик (`KIND_METRIC`) второе объявление того же имени
   стало идемпотентным no-op (`observability_declarations.py::_declare`); у лог-источников
   (`KIND_LOG_SOURCE`) отказ `ValueError` НЕ снят и остаётся намеренно — имя лог-источника
   по-прежнему адрес правила, а имя метрики адресом быть перестало (расхождение объяснено в
   шапке `observability_declarations.py`).
4. **Голос про самозванца и дедуп-множество** — `_warn_rejected_levels` /
   `_warned_rejected_levels` (`process_heartbeat.py`). Отсеивать больше нечего: недекларированная
   публикация едет легально под дефолтным правилом гейта (`TelemetryGate.due_metrics`, параметр
   `extra` — гейт тотален и по каталогу, и по факту наличия листа в хранилище).
5. **Поимённое снятие**: `_retracted`, `pending_retractions()`, `confirm_retracted()`,
   `RETRACTION_REASSERT_TICKS`, `None`-надгробия (`telemetry.py`, `process_heartbeat.py`) —
   вырезаны ВМЕСТЕ с арбитражем, а не подравнены под новую форму. Причина не косметическая:
   Ф0-фильтр снятия стоял на `metric_owners()` (удалённом п.3), а писатель надгробий клал плоское
   `state[имя] = None` со стражем `if name not in state` — во вложенной форме этот страж ВСЕГДА
   истинен для плагинных имён, и надгробие легло бы на ПЛОСКИЙ путь при живом писателе (форма-дефект
   A1, найден при планировании, до кода). Интерим-механизма не заводилось: замена — снятие
   ПОДДЕРЕВОМ писателя (`PluginLevels.retract(writer)` = `pop(writer)`) целиком, а полное удаление
   узла дерева (`state.delete`) приходит вторым шагом той же неделимой поставки (Ф2 плана); между
   Ф1 и Ф2 механизма именного снятия в дереве нет вовсе — фазы не разделяются на промежуточный
   релиз намеренно (§ «Ф1 и Ф2 — одна неделимая поставка», решение владельца по итогам ревью
   плана, блокер Б2).

**Что осталось не тронутым.** Каталог имён `declared_metrics()`/`gated_metrics()` жив — им
по-прежнему резолвит правила `TelemetryPublishConfig` publisher-gate и строит авто-строки GUI;
`declare_metric` теперь каталожная запись, а не право на имя (`observability_declarations.py`,
`plugins/base.py::PluginContext.declare_metric`). Гейт продолжает матчить по ИМЕНИ ЛИСТА
(суффиксу), а не по пути дерева — существующие правила конфига `telemetry.publish.metrics.<имя>`
действуют без миграции; glob-язык по пути (`processes.*.state.plugins.*.fps`) — предмет
следующей фазы (Ф4), не этого дополнения.

**Открытая точка в имени, которую Ф1 сама завела и сама закрыла.** Путь листа собирается
конкатенацией писателя и имени; точка в любом из двух сегментов резолвится по-разному до и после
появления узла (тот же класс, что Н3 у второй редакции выше) и оставляет вечно-мёртвый
лист-двойник. До Ф1 точечное имя не пропускал арбитр — после Ф1 арбитра нет, и пропускать
некому. Закрыто явным guard'ом на СВОЁМ такте (`plugins/base.py`, рядом с `publish_metric`):
имя или писатель с точкой не публикуется, WARNING один раз на пару.

**Последствия.** Класс «спор двух писателей за один лист» больше не чинится инвариантом — он
структурно недостижим: писатель определяет путь построением ключа, а не проверкой. Цена — лист
плагинной метрики теперь на сегмент глубже (`state.plugins.<писатель>.<имя>` вместо
`state.<имя>`); все читатели плоского пути мигрируют отдельно (`plan.md`, Task 1.4). Reversible:
нет без ревёрта Ф1 целиком — снятие возвращается в Ф2 тем же принципом (поддерево, не имя), и
интерим-формы у пары фаз не существует.

### Дополнение (Ф2, Task 2.2, 2026-08-23): снятие доведено до дерева — по писателю, с конечным запасом

Вторая половина неделимой поставки исполнена: обещание «уровень мёртвого писателя исчезает»
стало настоящим не в хранилище, а в ДЕРЕВЕ.

- **Адрес снятия — писатель, а не имя.** `retract(writer)` записывает уход в ведомость
  `PluginLevels._departed` с запасом `DEPARTED_DELETE_BUDGET = 3`; тик
  (`ProcessHeartbeat._delete_departed_subtrees`) шлёт
  `proxy.delete("processes.<p>.state.plugins.<писатель>")`. Имя листа в этой дороге не
  участвует нигде — форма-дефект A1 («надгробие на чужой лист при живом писателе») не
  выразима: ключ ведомости и ключ значений — один и тот же сегмент пути.
- **`None` как «показания нет» удалён из мира.** Нет писателя — нет узла. Потребители,
  рисовавшие «—» на нечисловом, рисуют то же на отсутствии (проверено Task 1.4).
- **Запас конечен и тратится ТОЛЬКО на успехе вызова.** «Успех» на этой дороге означает
  ровно «вызов вернулся без исключения»: `StateProxy.delete` — fire-and-forget,
  `_send` ловит ошибку транспорта сам, ответа обработчика отправитель не видит. Отсюда обе
  половины решения: повторять (тихая потеря ниже по стеку иначе хоронит снятие) и
  ограничивать повтор числом (подтверждать не о что, «до подтверждения» означало бы
  «каждый тик до конца жизни процесса», то есть цену по времени вместо цены по событию).
  Исключение запаса не стоит — сообщение из процесса не вышло.
- **Порядок внутри тика — часть механизма, а не оформление.** Снятие стоит ДО сборки
  уровней и ДО раннего выхода «нечего слать». Инъекция «снятие в конец тика, под ранний
  выход» красит 8 тестов, из них приёмочный С1 — ровно случай «ушёл последний писатель
  процесса, публиковать больше нечего».
- **Названная цена.** Прокси, чей `delete` падает КАЖДЫЙ раз, держит писателя в ведомости
  бессрочно и стоит одной пойманной попытки за тик; ограничитель — число писателей, не
  время. Воспроизведено тестом (`test_writer_retraction_hazards.py`, класс про исключение:
  пять отказов подряд, снятие состоялось на шестом тике после «починки транспорта»).
- **Что НЕ входит:** снятие фреймворковых агрегатов (`fps` при исчезновении воркеров) живёт
  по старым правилам — отдельная тема, в этот план не входит.

Reversible: yes — ревёрт возвращает состояние Ф1 (лист живёт в дереве после остановки
плагина), новых полей в контрактах сообщений не заведено; дорога `state.delete` существует
независимо (Task 2.1, `state_store_module`).

## ADR-PM-039: `default_enabled` — глобальный выключатель publisher-gate одним полем

**Статус:** принято
**Дата:** 2026-08-18
**Refs:** plans/telemetry-stage6.md (самопроверка Task 3.5, пункт «НЕ СДЕЛАНО. Пара маркеров
ON/OFF для флипа РТ-2», строки ~1497-1518), ADR-PM-018 (publisher-gate), ADR-PM-038 (уровень
плагина — тот же гейт, тот же каталог `gated_metrics()`), `configs/telemetry_publish_config.py`
(`TelemetryPublishConfig.resolve`), `backend/assembly/assembler.py::BlueprintAssembler.
_resolve_telemetry` (слияние global/per-process)

**Контекст.** Самопроверка Task 3.5 назвала щель поимённо: «Погасить push конфигом сегодня
НЕЧЕМ: `TelemetryPublishConfig.resolve` для метрики без правила возвращает `(True,
default_interval_sec)` … а в `TelemetrySection` глобального выключателя нет — есть только
`publish.metrics` и `throttle`. Значит «выключить» = перечислить ВЕСЬ каталог поимённо». Каталог —
per-process (5 имён у процесса без `capture`, 8 — с ним, ADR-PM-038) и растёт молча на каждом
`declare_metric` при импорте плагина/производителя. Явный список («каждой из восьми метрик
`enabled: false`») верен ровно для текущего состава каталога и протухает без единого голоса при
следующем `declare_metric` — то есть решение «через явные правила» не масштабируется, а не просто
неудобно. Флип РТ-2 (план `telemetry-stage6.md`) требует пары маркеров ON/OFF для ВКЛАДКИ, и ON-
половина («погасить push, вкладка остаётся живой опросом») не выполнима честно, пока «погасить»
физически нечем выразить одной ручкой.

**Решение.** Одно новое поле `TelemetryPublishConfig.default_enabled: bool = True`. Отвечает на
вопрос «что делать с метрикой, для которой в `metrics` нет правила» — ровно тот вопрос, на который
`resolve()` уже отвечал, только раньше ответ был зашит литералом `True`. `resolve()` меняется на
одну строку: `rule is None → return (self.default_enabled, self.default_interval_sec)`.
`default_enabled=False` переворачивает секцию в белый список: неизвестная метрика выключена, пока
её явно не включит `metrics[<имя>].enabled=true` (точечный opt-in остаётся рабочим — он идёт через
ветку с найденным правилом, `default_enabled` её не касается).

**Дефолт `True` — не косметика, а условие обратной совместимости.** Каждый существующий процесс,
где секция `telemetry.publish` уже задана (даже пустым `{}`), обязан продолжать публиковать всё —
иначе добавление поля само стало бы флипом РТ-2 явочным порядком, без пары маркеров ON/OFF и без
живых чисел, которых требует гейт этапа 6.

**Слияние с рецептом сохраняет глобальный `default_enabled` без специального кода.**
`BlueprintAssembler._resolve_telemetry` (`assembler.py:206-226`) сливает глобальную секцию
(конструктор) и per-process `blueprint.processes[].telemetry` через `deep_merge` — рекурсивный
merge ПО КЛЮЧУ, а не замену секции целиком (`multiprocess_framework...data_schema_module.
deep_merge`, тот же символ, что и в `assembler.py`). Рецепт, переопределяющий только `metrics`
(частый случай — точечный `opt-in`/`opt-out` одной метрики), НЕ стирает глобальный
`default_enabled`, потому что не упоминает этот ключ вовсе, и рекурсия трогает только ключи,
реально присутствующие в overlay. Явно заданный per-process `default_enabled` по тем же правилам
ПОБЕЖДАЕТ глобальный (overlay сильнее base при конфликте) — процесс волен переопределить флип для
себя одного. Проверено тестом, воспроизводящим ровно эту форму вызова (framework не имеет права
импортировать prototype, R2 — тест не ввозит сам `BlueprintAssembler`, а гоняет `deep_merge` той же
формой, какой пользуется сборщик): `test_telemetry_default_enabled_hazards.py::
TestBlueprintMergePreservesGlobalDefaultEnabled`.

**Обратная совместимость трёхзначна, а не двузначна — и это названо явно, чтобы не слиплось в
рефакторинге.** «Секции `telemetry` нет вовсе» и «`default_enabled=False`» звучат похоже
(«метрики не идут»), но физически противоположны. `_build_telemetry_gate()`: нет секции/нет
`publish` → `None` (гейта нет, легаси-путь). `_loop` (`process_heartbeat.py:165`):
`allowed_metrics = gate.due_metrics() if gate is not None else None`. У `build_worker_telemetry.
_ok()` (`heartbeat/telemetry.py`) `None` значит «всё разрешено», пустое множество — «ничего не
разрешено». `default_enabled=False` строит АКТИВНЫЙ гейт, чей `due_metrics()` пуст → в `_loop` это
`allowed_metrics=set()`, не `None`. Рефакторинг вида «`if not allowed_metrics: allowed_metrics =
None`» (интуитивно безобидный — оба состояния falsy) превратил бы `default_enabled=False` в
тихий no-op. Названная опасность закреплена тестом, наблюдающим не только `due_metrics()`, но и
итоговый payload `build_worker_telemetry` для одного и того же снимка воркера под обоими режимами:
`TestNoGateIsNotTheSameAsDefaultEnabledFalse::test_downstream_payload_is_opposite_not_merely_absent`.

**Отвергнуто с причиной.**

| Вариант | Почему нет |
|---|---|
| Явно перечислить `enabled: false` на каждую метрику каталога (рецепт из самопроверки Task 3.5) | верно ровно для текущего состава каталога; протухает без голоса на первом же новом `declare_metric` — ровно проблема, которую задача закрывает, а не решение |
| Глобальный флаг ВНЕ `TelemetryPublishConfig` (например `telemetry.enabled: bool` рядом с `publish`) | развело бы решение «публиковать ли неизвестную метрику» на ДВА источника правды (новый флаг снаружи + `resolve()` внутри); `resolve()` — единственное место, где это решение принимается сегодня, второй адрес для того же вопроса — тот же класс расхождения, что уже чинили Router/канал (`ROUTING_GLOSSARY.md`) |
| `default_enabled` без изменения дефолта (например `False` по умолчанию) | ломает КАЖДЫЙ процесс с уже заданной (даже пустой) секцией `telemetry.publish` — не расширение контракта, а breaking change без причины |

**Флип РТ-2 этой задачей НЕ выполняется** — `system.yaml` остаётся с закомментированным блоком
`telemetry`, флаг нигде не выставлен `false`. Задача делает флип ВЫРАЗИМЫМ одной ручкой; сам флип
(с парой маркеров ON/OFF для вкладки и живыми числами трафика) — предмет отдельного шага, как и
было решено владельцем при старте 3.5 (порядок «3.5 → флип РТ-2 → гейт этапа», не пересмотрен).

**Ред. 2026-08-18 (ревью, блокер Б1): рантайм-правка в дефолтном режиме `replace` молча СНИМАЕТ
флип.** Воспроизведено на боевых `ProcessHeartbeat._build_telemetry_gate` + `apply_telemetry_reconfigure`:
boot `telemetry.publish = {default_enabled: false, metrics: {fps: {enabled: true}}}` даёт
`due_metrics=['fps']`; `telemetry.reconfigure` БЕЗ ключа `telemetry_mode` (дефолт команды —
`"replace"`, `builtin_commands.py:2279`) с телом `{"publish": {"metrics": {"fps": {...}}}}` —
не упоминающим `default_enabled` — возвращает поле к схемному дефолту `true` и расширяет каталог
разрешённых метрик с одной (`fps`) до всех пяти фреймворковых. **Семантика `replace` сама по себе
корректна и не меняется** (полная замена секции — контракт Task 5.10.f) — ломается посылка ЭТОЙ
ручки: `default_enabled`, поставленный boot-конфигом, не переживает точечную правку СОСЕДНЕЙ
метрики в режиме по умолчанию, потому что тело точечной правки не обязано (и обычно не будет)
повторять `default_enabled` — отсутствующий в присланном dict ключ берёт схемный дефолт, а не
текущее значение гейта. Голоса при этом нет: `apply_telemetry_reconfigure` возвращает
`{"publish": true}`, отказа нет, `default_enabled` в ответе не отражается. Контроль
`telemetry_mode: merge` держит флип (`due_metrics` остаётся `['fps']`) — практическое правило:
флип, поставленный `default_enabled=false`, переживает только точечные (`merge`) правки; `replace`
без явного `default_enabled` в теле возвращает схемный дефолт. Закреплено тестом
`test_telemetry_default_enabled_hazards.py::TestReplaceModeDropsDefaultEnabledSilently`.

## ADR-PM-040: Исполнение флипа РТ-2 — `default_enabled: false` в боевом `system.yaml`

**Статус:** принято
**Дата:** 2026-08-18
**Refs:** ADR-PM-039 (ручка `default_enabled` — эта запись её не повторяет, только
исполнение), `plans/telemetry-stage6.md` (Task РТ-2), `multiprocess_prototype/backend/
config/system.yaml` (боевой конфиг), `multiprocess_framework/modules/process_module/
tests/test_rt2_config_flip_acceptance.py` (независимая приёмка A4-A6),
`multiprocess_prototype/backend/tests/test_rt2_config_flip_acceptance.py` (A1-A3)

**Контекст.** ADR-PM-039 сделала флип РТ-2 выразимым одним полем, но сама секция
`telemetry.publish` в боевом `system.yaml` оставалась закомментированной целиком — гейта
не было вовсе (легаси-путь, `allowed_metrics=None` в `_loop`). Эта запись — про исполнение
того шага: механизм (`resolve()`, слияние с рецептом, трёхзначная обратная совместимость)
не меняется и здесь не повторяется, см. ADR-PM-039.

**Решение.** Секция `telemetry.publish` раскомментирована:

```yaml
telemetry:
  publish:
    default_enabled: false
    default_interval_sec: 1.0
    metrics: {}
```

Флип полный, не частичный (решение владельца, 2026-08-18): `metrics` пуст, белого списка
нет ни для одной метрики — push уровней в дерево StateStore выключен целиком, GUI живёт
опросом (`TelemetryPoller`, 1/с). Подсекция `telemetry.throttle` НЕ тронута и остаётся
закомментированной — центральный троттл продолжает получать полный дефолтный набор из
**восьми** правил (`_default_throttle_rules`, `manager_setup.py:48-63`); закомментированный
пример throttle содержит только три, и его раскомментирование было бы ОТДЕЛЬНЫМ решением,
которое эта задача не принимает.

**Измерено на живом стенде** (сравнение `introspect.telemetry` до/после на одном прогоне):

- трафик плоскости уровней целиком: 20.90 → 16.56 дельт/с (−20.8 %);
- по путям, которыми владеет гейт: 5.00/с → **0.00/с**, ноль держался **122.6 с подряд**
  при ненулевом контроле в том же потоке измерения (`uptime` 15.9/с, `io_peek` 13.3/с) —
  контроль исключает «замер попал в паузу публикации», гасит именно гейт;
- гаснет **32** пути, остаётся **24**; в гаснущие попадает производная
  `system.health.avg_fps` — её нет ни в одном каталоге `gated_metrics()` процесса (сама
  метрика не декларируется `declare_metric`, она считается из уже собранных уровней);
- опрос покрывает всё гасимое: для процесса с плагином захвата каталог — восемь имён, все
  восемь присутствуют в `introspect.telemetry` → `levels` (шесть под `state.*`: `fps`,
  `capture_fps`, `latency_ms`, `frame_count`, `drops`, `shm`; два под `workers.<w>.*`:
  `effective_hz`, `cycle_duration_ms`) — флип не создаёт слепых пятен для GUI.

**Отвергнуто.** Частичный флип (белый список из части каталога — например, оставить
`fps`/`shm` включёнными явным правилом) — тот же аргумент, которым ADR-PM-039 отвергла
явное перечисление: список пришлось бы синхронизировать с каталогом, который растёт молча
на каждом новом `declare_metric`. Владелец выбрал `metrics: {}` — не потому что
перечисление невозможно, а потому что оно снова протухло бы без голоса.
