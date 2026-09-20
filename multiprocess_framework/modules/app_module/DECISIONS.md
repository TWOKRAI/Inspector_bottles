# app_module — архитектурные решения (ADR-APP-*)

Локальный индекс. Глобальный — `multiprocess_framework/DECISIONS.md`.

---

## ADR-APP-001: app_module как верхний композиционный ярус (не 4-й корень)

**Контекст.** Композиционный код (assembly, launch, manifest, discover) исторически
застрял в прототипе. Нужен дом для generic-«рыбы» (Ф5.11).

**Решение.** Новый модуль `multiprocess_framework/modules/app_module` — ярус 2 внутри
framework. **Инвариант:** только композиция, ноль механизмов; внутри framework никто
его не импортирует (направление `app_module → остальные`). Enforce: sentrux boundary
`framework/* → app_module/*` + контракт-тест `test_no_other_framework_module_imports_app_module`.
Внутренние импорты — относительные (sentrux не резолвит relative → boundary ловит только
чужие absolute, не ложно-срабатывая на self).

**Отвергнуто:** (а) 4-й корневой пакет `multiprocess_platform/` — ещё одна граница и слой
шимов; ярус — роль в модели импортов, не директория. (б) builder внутри
`process_manager_module` — утолщение модуля яруса 1 содержимым яруса 2 (PM узнал бы про
рецепты/манифест). См. `app-template-idea.md §5`.

**Reversible:** yes (модуль аддитивен; прототип — тонкий шим поверх).

---

## ADR-APP-002: манифест под движок миграций с первого дня (`version` + `extras`)

**Решение.** `AppManifest` несёт `version: int` (дефолт 1) + `extras: dict` (pass-through).
`extras` валидирует приложение, НЕ framework — туда складывается app-специфика
(тема/брендинг), которую generic-ядро не знает. Единый `version+extras`-контракт разделяют
`app.yaml`, манифест плагина (ADR-PM-013) и маркер сервиса `service.yaml`.

**Why:** иначе через год появится свой «unwrap_recipe» для манифеста. Задел движка
миграций дешевле ретрофита.

**Rejected:** плоский манифест без версии — отвергнут: миграция схемы стала бы ad-hoc.

---

## ADR-APP-003: ManifestStore: единственная сериализованная точка read/write app.yaml (NEW-1)

**Контекст.** Манифест — разделяемое состояние двух процессов: backend
(`persist_pipeline_choice`) и GUI (`_persist_active_recipe`) независимо писали ключ
`pipeline` в `app.yaml` → гонка read-modify-write (потеря обновления, torn-read).

**Решение.** `ManifestStore` — одна точка: межпроцессный лок (`fcntl.flock` на sidecar
`<manifest>.lock`) сериализует RMW; атомарная запись (temp + `os.replace`) исключает
torn-read; комментарии сохраняются (ruamel round-trip). Оба писателя прототипа
переведены на `ManifestStore.set_pipeline`. Регресс гонки — `test_concurrent_writes_no_lost_update`.

**Why:** контракт «разделяемое состояние» сделан явным вместо конвенции «все пишут через
одну функцию».

**Risk:** low (flock advisory; на платформах без fcntl деградирует до in-process лока).
**Reversible:** yes.

---

## ADR-APP-004: единый `discover()`: плагины по `plugin.py`, сервисы по маркеру `service.yaml`

**Контекст.** Плагины сканировались в ДВУХ местах (boot `launch.py` + switch
`orchestrator`), сервисы объявлялись вручную в топологии (A6).

**Решение.** Один framework-helper `discover(plugin_paths, service_paths)`:
- плагины — делегирование `PluginRegistry.discover` (рекурсивный `plugin.py`);
- сервисы — по маркер-файлу `service.yaml` в каталоге сервиса (директива владельца
  2026-07-11; симметрично `plugin.py`/манифесту плагина; тот же `version+extras`).

Обе копии в прототипе переведены на этот helper. Границы слоёв не нарушены: плагины
подгружаются динамически (`importlib`), сервисы читаются как YAML-данные — статических
импортов Plugins/Services из framework нет.

**Rejected:** дискавери сервиса по имени/конвенции каталога — отвергнуто владельцем в
пользу явного маркера (симметрия и явность важнее «магии»).

---

## ADR-APP-005: два режима сборки; carve прикладного BlueprintAssembler отложен (вход Ф5.12)

**Решение.** `SystemBuilder` двухрежимный:
- **generic** — granular build-time хуки с framework-defaults (`default_blueprint_loader`
  + `assemble_proc_dicts`), базовый `ProcessManagerProcess`. minimal_app доказывает
  самодостаточность без прототипа.
- **factory** — `AppSpec.launcher_factory`: прототип собирает launcher своим сложившимся
  `SystemBuilder.build()` (снапшот 5.1 не трогаем); `run_app` даёт generic-контур.

**Осознанный остаток (Inspector-специфика за швом — вход Ф5.12).** Прикладной
`BlueprintAssembler` (framework-clean по зависимостям, но физически в
`multiprocess_prototype/backend/assembly`) добавляет per-category normalize из
прототипной `SystemConfig` + unwrap рецепта v3 + inject recipe_devices — этого нельзя
абстрагировать в generic `assemble_proc_dicts` без формализованных build-time хуков
(state-bootstrap/normalize) и generic `AppOrchestrator`, что и есть скоуп Ф5.12. Поэтому
`app_module.assemble_proc_dicts` (generic) и прототипный `BlueprintAssembler` (augmented)
временно сосуществуют: первый — для «рыбы» и как дом будущего carve, второй — за швом
`launcher_factory`. Физперенос assembler/planner → `process_manager/topology` (ADR-RCP-005)
и конвергенция — отдельные задачи после формализации хуков.

**Reversible:** yes (factory-режим — обёртка; удаление возвращает прямой вызов `build()`).

---

## ADR-APP-006: `GenericProcessManagerApp` + двухсортные хук-точки (Ф5.12)

**Контекст.** Прототипный оркестратор `ProcessManagerProcessApp` (~250 LOC) смешивал
generic-плумбинг (StateStore из конфига, observability-watcher, shutdown) с
Inspector-спецификой (BlueprintAssembler-движок горячей замены, reload DisplayRegistry).
Нужен generic-оркестратор яруса 2, на котором бутится «рыба» (minimal_app), и
формализация точек расширения так, чтобы они не разрослись.

**Решение — два сорта хук-точек** (следствие spawn + Dict-at-Boundary):

- **build-time** (launcher-процесс, до spawn) — обычные callable в `AppSpec`:
  `blueprint_loader` / `proc_dicts_builder` / `state_bootstrap` / `throttle_rules`.
  Выполняются в родителе, их РЕЗУЛЬТАТ (dict) пиклится в `orchestrator_config`.
- **runtime** (после spawn) — callable НЕ пиклится через spawn, поэтому паттерн
  `orchestrator_class_path` (import-path строка + dict `orchestrator_config`,
  резолв на стороне ребёнка). Приложение подставляет подкласс
  `GenericProcessManagerApp` и переопределяет seam'ы (`_configure_runtime` /
  `apply_topology`).

`GenericProcessManagerApp(ProcessManagerProcess)` в app_module даёт три config-gated
generic-возможности: StateStore из build-time хуков (`_setup_state_store`),
observability-watcher (`_start_observability_watcher`), runtime-seam `_configure_runtime`
(no-op). Прототипный `ProcessManagerProcessApp` = тонкая композиция (≤ ~30 LOC, факт
~11 LOC тела): подключает два runtime-хука (topology-engine + display-reload), тела
которых вынесены в `multiprocess_prototype/backend/orchestrator_hooks.py`. minimal_app
бутится на `GenericProcessManagerApp` **без единого хука**.

**Правило против hook-взрыва (enforce этим ADR).** Хук попадает в `AppSpec` ТОЛЬКО
если: (1) прототип нуждается в нём сегодня И (2) minimal_app бутится без него (хук
опционален). Первая пара — доказательство обоих сортов: **state-bootstrap** (build-time:
`state_bootstrap`+`throttle_rules` → `initial_state`/`state_throttle_rules`; прототипу
нужен реактивный state, minimal_app без него) и **display-reload** (runtime: override
`apply_topology` в подклассе, резолвится child-side; прототип reload'ит DisplayRegistry,
minimal_app без дисплеев). Оба опциональны по построению: `_setup_state_store` — no-op
без `initial_state`/`state_throttle_rules`. Никаких хуков «на вырост».

**Отклонение от плана по имени класса.** План называл generic-оркестратор
`GenericProcessApp`, но это имя УЖЕ занято load-bearing прототипным WORKER-классом
`multiprocess_prototype.generic_process_app.GenericProcessApp` (подкласс `GenericProcess`
с StateProxy, `process_class` в ~10 топология-YAML). Два разных класса-«GenericProcessApp»
(worker vs orchestrator) — ловушка. Выбрано `GenericProcessManagerApp`: симметрия с
базой `ProcessManagerProcess` и прототипным `ProcessManagerProcessApp` делает родословную
явной (`ProcessManagerProcess` → `GenericProcessManagerApp` → `ProcessManagerProcessApp`).

**Rejected:**
- **runtime-хук как отдельный import-path в конфиге** (`display_reload_class_path`) —
  отвергнут: подкласс-оркестратор УЖЕ резолвится child-side по `orchestrator_class_path`,
  так что override метода в нём и ЕСТЬ runtime-хук; отдельная строка-путь дублировала бы
  механизм.
- **generic-оркестратор всегда создаёт StateStore** — отвергнут: тогда state-bootstrap не
  опционален, minimal_app платит за пустой store и класс инвариант «хук опционален»
  нарушается. Гейтим на наличие build-time данных.
- **имя `GenericProcessApp` буквально по плану** — отвергнуто из-за коллизии (см. выше).

**Why:** оркестратор прототипа выражен как generic + хуки (250→~40 LOC файл), точки
расширения формализованы и защищены от разрастания правилом; «рыба» получила свой
generic-оркестратор.

**Risk:** low (аддитивно; прототипный `orchestrator_class_path` не изменился —
характеризационный снапшот 5.1 и `test_run_app_prototype` зелёные без правок golden).
**Reversible:** yes (подкласс можно снова «утолстить», generic-класс аддитивен).
**Refs:** plans/2026-07-06_constructor-master/plan.md (5.12), ADR-APP-005 (вход).

---

## ADR-APP-007: дефолтный `state_bootstrap` — топология процессов, а не пустой dict (Ф1 Task 1.0)

**Дата:** 2026-09-20
**Статус:** принято
**Контекст:** `AppSpec.state_bootstrap` был опционален БЕЗ дефолта: приложение, не
написавшее Python-хук, получало `initial_state = {}`. Дальше по цепочке гейт
`GenericProcessManagerApp._setup_state_store` (ADR-APP-006) видел пустоту и не поднимал
`StateStoreManager`; команда `state.get_subtree` не регистрировалась в `CommandManager`
вовсе — диспетчер отвечал `No handler for key 'state.get_subtree'`, а `system_overview`
рапортовал пустую топологию с аномалией `empty_topology`. То есть generic-приложение
(`examples/minimal_app`, `apps/line_sim`) было **ненаблюдаемо по построению**, и цена
входа в наблюдаемость — написать прикладной bootstrap на Python — противоречила обещанию
яруса «второе приложение = данные + декларации».

**Решение:** `builder.default_state_bootstrap(blueprint)` — framework-дефолт, который
строит ТОЛЬКО ветку `processes`:
`{<имя>: {"config": {plugins, chain_targets, priority}, "state": {status, pid, fps, error}}}`.
В `SystemBuilder._build_generic` — `spec.state_bootstrap or default_state_bootstrap`:
**явный хук приложения выигрывает целиком и не мержится** с дефолтом.

**Почему топология, а не пустой dict.** Ветка `processes` — единственная, которую
framework может построить из своих данных (blueprint), и ровно она нужна потребителям
вердиктов (`system_overview`, `state.get_subtree`). Значение посева здесь не в данных
(статусы перетрёт `ProcessManager` после спавна), а в **существовании листьев**: без них
инструмент отвечает «обработчика нет» — диагноз, читающийся как поломка.

**Почему прикладные ветки не переезжают.** `system`/`wires`/`services`/`displays`/
`recipes`/`plugins` прикладного `build_initial_state` наполняются из реестров прототипа
(`SystemConfig`, `DisplaysConfig`, каталог рецептов) — у framework таких источников нет,
и «переезд» означал бы либо пустые ветки-призраки, либо импорт прототипа снизу вверх
(нарушение слоёв, правило 9). Топологическая половина живёт в framework, прикладная —
в `multiprocess_prototype/backend/state/bootstrap.py`.

**Пустой blueprint → `{"processes": {}}`, а не `{}`.** Гейт `_setup_state_store` смотрит
на истинность dict'а, поэтому выбор решает диагноз приложения без процессов: «поддерево
пусто» (законная конфигурация) против «обработчика нет» (поломка). Цена — пустой
StateStore там, где state-plane не используется. Пришпилено
`tests/test_state_bootstrap_hazards.py::test_empty_blueprint_decision_is_pinned`,
который прогоняет НАСТОЯЩИЙ гейт в обе стороны.

**Отношение к ADR-APP-006.** Тот ADR отверг «generic-оркестратор ВСЕГДА создаёт
StateStore» — чтобы хук остался опционален и minimal_app не платил за пустой store.
Гейт остаётся на месте и не тронут; изменилось то, что generic-дорога теперь подаёт
в него непустой посев, то есть на практике store у generic-приложения есть всегда.
Отклонение ADR-APP-006 сужено сознательно: доводом там была цена пустого store, а
измеренная цена ненаблюдаемости (инструмент вердиктов врёт про топологию) оказалась
выше. Приложение, которому store не нужен, может вернуть `{}` явным хуком.

**Отменяет контракт:** без хуков `initial_state == {}` и StateStore не создаётся (тесты
`test_minimal_app_smoke.py:62`, `test_orchestrator.py::TestBuildGenericHookWiring::
test_no_build_time_hooks_minimal_config` переписаны 2026-09-20 — они пинили именно эту,
теперь снятую, гарантию).

**Клиентская половина — отдельная задача.** Дефолт сеет дерево у ОРКЕСТРАТОРА. Чтобы
дочерний `GenericProcess` писал в него свои показания, нужен `ctx.state_proxy` на
клиентской стороне — Task 2.0 плана `line-sim`, сюда не входит.

**Rejected:**
- **мерж дефолта с явным хуком** — отвергнут: приложение, заявившее своё дерево,
  получало бы поверх него чужие ветки, а порядок мержа стал бы неявным контрактом.
  Победа явного хука целиком — читаемое правило («задал — твоё»).
- **дефолт внутри `_setup_state_store` (child-side)** — отвергнут: blueprint child-side
  недоступен, пришлось бы гнать топологию вторым путём через конфиг; шов посева один и
  живёт в родителе, где blueprint уже есть.
- **поднимать StateStore всегда, посев оставить пустым** — отвергнут: это прямое
  отклонение ADR-APP-006 без выигрыша — `state.get_subtree` отвечал бы, но пустотой,
  и `system_overview` по-прежнему не видел бы процессов.

**Why:** generic-приложение наблюдаемо из коробки — без единого Python-хука.
**Risk:** low (аддитивно; factory-дорога прототипа возвращается из `build()` до
`_build_generic` и дефолта не видит вовсе).
**Reversible:** yes (дефолт снимается возвратом `initial_state = {}`).
**Refs:** plans/line-sim/phase-1-vertical-slice.md (Task 1.0), ADR-APP-006 (гейт),
docs/reviews/2026-09-20_line-sim-generic-app-observability-investigation.md.
