# План: группировка модулей `multiprocess_framework` по слоям + enforcement

**Статус (сверено по git 2026-07-20):** **Фаза 2 в основном закрыта** — 3 из 5 пунктов сделаны отдельными коммитами в `main` 2026-07-18 (`92c19f2e`/`d9dddf45`/`bf484bcd`), приёмка фазы (перезамер циклов + прогон suite) **не проводилась**. Фазы 0/3/4/5 — **не начаты**, ветки `refactor/framework-layer-grouping` нет.

⚠️ **Этот план — блокер двух других треков:** Фаза 3 (codemod, ~1970 импортов / 910 файлов) требует **freeze-окна**, во время которого кодовые фазы не выполняются. Ждут его: [frontend-constructor](../frontend-constructor/plan.md) Блок В (Ф3+) и Task 1.1/1.2 «скелет модуля»/«generic harness» из [backend-ctl-proof-discipline](../backend-ctl-proof-discipline.md) (раздел «За внешним гейтом codemod»; исходный мини-план в архиве — [backend-ctl-framework-module](../_archive/2026-07-21_backend-ctl-framework-module.md)) — слой `tooling/` создаётся codemod'ом.

**Учесть при старте:** план написан на 27 модулей и не знает про `telemetry_readmodel_module` (создан 2026-07-18) и переезд `backend_ctl → tooling/` — rename-таблицу Фазы 3 надо пересобрать под факт.

## Context (зачем это)

Сейчас все 27 модулей фреймворка лежат **физически плоско** в `multiprocess_framework/modules/`. При этом
разведка кода показала, что архитектура **уже зрелая**, а не «каша»:

- Единообразие высокое: у всех 27 модулей есть `README.md`/`STATUS.md`/`DECISIONS.md`/`tests/`;
  у 26 из 27 — верхний `interfaces.py`; у большинства — `core/` + фасад `XxxManager`/`Registry` + `__all__`.
- Граф зависимостей уже ацикличен и направлен снизу вверх: `coupling 0.13`, god-файлов 0,
  цикл `recipe↔state_store` осознанно разорван через `StoreProtocol`.
- 12-слойная модель задокументирована согласованно в трёх местах: `CONSTRUCTOR_BLUEPRINT.md`,
  `MODULE_CONTRACTS.md`, `MODULES_RESPONSIBILITY_MAP.md`.

**Значит цель «каждый модуль — самостоятельный пакет с фасадом и интерфейсом» в основном уже достигнута.**
Реальные пробелы — навигационные и enforcement-овые, а не структурные:

1. Дерево папок не отражает слои → новому человеку «одна большая папка».
2. 12-слойная иерархия **не enforced**: sentrux видит весь framework как один слой и не резолвит
   relative-импорты → «0 циклов» это дыра измерения, а не гарантия. Регресс слоя пройдёт молча.
3. Латентный цикл `process_module ↔ process_manager_module` через временный re-export-шим
   (`process_module/generic/blueprint.py`, ADR-PMM-016, помечен «после миграции удаляется»).
4. `actions_module` — единственный без верхнего `interfaces.py`.

**Решение (выбранный масштаб):** физически сгруппировать 27 модулей по ~8 папкам-слоям, **сохранив все
модули, их API и логику** (никаких слияний/удалений в духе радикальной схемы) + убрать суффикс `_module`
+ формализовать слои через `import-linter` + закрыть шим-цикл + дать `actions` свой `interfaces.py`.

**Радикальная схема (слить logger+error+stats, удалить `service_module`, переименовать в
foundation/communication/domain/…) ОТВЕРГНУТА:** заденет ~1970 импортов в 910 файлах, сломает
ADR/контракты/2904 теста ради косметики; противоречит установке «продукт важнее красоты движка».

**Масштаб переноса (замерено):** `multiprocess_framework.modules.X` встречается **~1970 раз в 910 файлах**
(из них ~395 в 207 файлах прототипа, плюс Services, backend_ctl, tests). Поэтому перенос делается
**детерминированным codemod-скриптом**, а не руками.

---

## Тренды 2026 и к чему стремиться (веб-анализ)

Куда движется индустрия для **single-deploy** приложений вроде нашего (десктоп GUI + multiprocess),
и как это ложится на наш фреймворк:

1. **Modular Monolith — золотая середина 2026.** Не микросервисы, не Kafka, не k8s (для десктопа это
   over-engineering). Один деплой + чёткие модули с явными границами, enforced архитектурными тестами.
   → У нас ровно это. Не ломать в сторону «модности».
2. **Слои vs Vertical Slices — по месту.** Индустрия уходит от горизонтальных слоёв к вертикальным
   срезам (код группируется по фиче, а не по тех-слою) — но это про **приложение**. **Фреймворк** —
   это набор горизонтальных возможностей, для него технические слои (foundation/communication/…) — правильно.
   → Vertical slices применяем в `multiprocess_prototype/` (фичи), НЕ в движке. Парадигму движка не меняем.
3. **«Модули ссылаются только на контракты».** Краеугольный камень modular monolith: потребитель
   импортирует **публичный API** модуля (`interfaces.py` + фасад), а не его внутренности.
   → У нас 26/27 уже имеют `interfaces.py`; закрываем последний (`actions`). `import-linter` умеет
   enforce «public interface» (импорт только через фасад).
4. **Enforcement архитектурными тестами.** `import-linter` (layers/independence/forbidden) в CI.
   Альтернатива `Tach` — **не берём**: не поддерживается с 2025-06. `import-linter` — безопасный выбор.
5. **Protocol-oriented + Pure DI** (PEP-544) вместо наследования-ради-переиспользования, синглтонов и
   service-locator. → У нас уже Protocol везде (`IRouter`, `ILogChannel`, …) и DI через конструктор.
6. **Infrastructure as detail (Hexagonal).** Доменное ядро (`state`, `registers`, `chain`) не знает про
   PySide6/SQL/файлы — заменяемые адаптеры. → В основном уже так; беречь при переносе.
7. **Современный tooling:** `ruff` + `uv` + `pyright` + `pydantic v2`. → Всё уже в стеке.

**Лестница зрелости (к чему стремиться, по возрастанию):**
- Ур.1 «Работает»: модули разделены, тесты есть, Dict-at-Boundary — ✅ есть.
- Ур.2 «Понятно»: Protocol-контракты, DI, папки = слои, in-memory адаптеры для тестов — **цель этого плана**.
- Ур.3 «Индустриальный стандарт»: enforced слои (`import-linter` в CI), ацикличность доказана
  (не ложно как у sentrux), `pyright --strict` — **добираем этим планом** (Фаза 2 + Фаза 4).
- Ур.4 «Over-engineering»: микросервисы/Kafka/k8s/GraphQL — **сознательно НЕ идём**.

Источники: milanjovanovic.tech (vertical slices в modular monolith), kamilgrzybek.com (domain-centric
modular monolith), import-linter (seddonym), tach-org/tach (unmaintained с 2025-06), Griffe (public APIs).

## Реальный граф зависимостей (ИЗМЕРЕНО grimp + AST-агент, а не документ)

Замер `grimp` (резолвит relative-импорты, в отличие от sentrux) + независимый AST-разбор сошлись.
Скрипты замера: `scratchpad/measure_graph.py`, `scratchpad/cycle_details.py` (перенести в `scripts/regroup_modules/`).

**Факты, опровергающие документную «чистую 12-слойку»:**
- Граф **широкий и мелкий (~7 тиров)**, а не 12 глубоких. Большинство модулей — низкоуровневые листья.
- **Настоящих runtime-циклов ровно 2** (исполняются при импорте), оба в «семье процессов»:
  1. `console → process` — `console_module/configs/console_process_config.py:12-13` тянет
     `process_module.configs.{managers_config, process_launch_config}` на верхнем уровне. Обратное
     `process → console` легитимно. **Разорвать console→process** (в `TYPE_CHECKING`).
  2. `process → process_manager` — единственное ребро `process_module/generic/blueprint.py:12`
     (шим ADR-PMM-016). **Удалить шим** → цикл исчезает.
  → После этих 2 правок runtime-граф **полностью ацикличен**; тройка `{console, process, process_manager}`
    становится цепочкой `console < process < process_manager`.
- **Остальные «циклы» не исполняются при импорте**, но различаются по типу (важно для enforcement):
  - `TYPE_CHECKING`-only (снимаются флагом `exclude_type_checking_imports`): `config→shared_resources`,
    `data_schema→process`, `data_schema→shared_resources`. Значит `data_schema` — **чистый фундамент**.
  - **lazy (function-level)** (флаг НЕ снимает, нужен `ignore_imports`): `router→shared_resources` (×4 в
    `frame_shm_middleware`), lazy `process→process_manager`, `app→*`. Их видит `grimp`/`import-linter`.
- **sentrux acyclicity 10000 — ложно-положительно** (слеп к relative). Реальный узкий bottleneck — `modularity`.

**Измеренный import-time порядок тиров (снизу вверх; тип-only И lazy рёбра исключены, циклы разорваны):**
`data_schema, base_manager` (config тоже низ) → тир-2 `{worker, chain | state_store, recipe, registers,
actions | display, service}` → communication `message, dispatch, event, channel_routing, router, command` →
observability `logger, error, statistics` → ipc `shared_resources` → runtime `console<process<process_manager`
→ application `app, frontend`.

## Целевая структура (ВЕРИФИЦИРОВАНА против реального графа)

Слои промотируются на верхний уровень (`multiprocess_framework.<layer>.<module>`), суффикс `_module` снят.
Порядок папок = валидный `import-linter` layers по IMPORT-TIME графу (+`ignore_imports` для lazy/тестов, Фаза 4).
Ключевые размещения (после независимого ревью): **`config` в foundation**; **`message`+`dispatch`+`event`
в communication** (вся связь — in-proc и IPC — в одной папке); **`actions` в state** (undo-патчи состояния);
тир-2 — 3 когезивных сиблинга (`execution`/`state`/`catalogs`), внутри-тировые рёбра `chain→worker` и
`state_store→recipe` остаются внутри групп; **`ipc` (бывш. `resources`) ВЫШЕ observability** (т.к.
`shared_resources → logger`).

```
multiprocess_framework/
├── foundation/          # фундамент (deps: только внутри группы)
│   ├── base_manager/
│   ├── data_schema/         (data_schema_module)
│   └── config/              (config_module)      ← ОПУЩЕН СЮДА (deps только base+data)
├── execution/           # тир 2 (сиблинг): работа/исполнение
│   ├── worker/              (worker_module)
│   └── chain/               (chain_module)        # chain→worker внутри группы
├── state/               # тир 2 (сиблинг): состояние/регистры/undo/телеметрия(read-model)
│   ├── state_store/         (state_store_module)  # state_store→recipe внутри группы
│   ├── recipe/              (recipe)
│   ├── registers/           (registers_module)
│   ├── actions/             (actions_module)      ← из execution (undo-патчи СОСТОЯНИЯ, ADR-124)
│   └── telemetry_readmodel/ (telemetry_readmodel_module) ← 27-й модуль: проекция дерева StateStore (Р1, frontend-constructor Ф0)
├── catalogs/            # тир 2 (сиблинг): реестры внешних сущностей (листья)
│   ├── display/             (display_module)
│   └── service/             (service_module)
├── communication/           # тир 3: вся связь — in-proc и IPC (deps ≤ тир-2)
│   ├── message/             (message_module)      ← из foundation
│   ├── dispatch/            (dispatch_module)     ← из тир-2 (in-proc key→handler)
│   ├── event/               (event_module)        ← из state (pub/sub факты, родня dispatch)
│   ├── channel_routing/     (channel_routing_module)
│   ├── router/              (router_module)
│   └── command/             (command_module)
├── observability/       # тир 4: логи/ошибки/метрики (deps ≤ communication)
│   ├── logger/              (logger_module)
│   ├── error/               (error_module)
│   └── statistics/          (statistics_module)
├── ipc/                 # тир 5: межпроцессные примитивы (deps: base+data+logger)
│   └── shared_resources/    (shared_resources_module)  # ВЫШЕ observability (тянет logger)
├── runtime/             # тир 6: семья процессов (console/process/process_manager)
│   ├── console/             (console_module)
│   ├── process/             (process_module)      # + сюда переезжает console_process_config.py (K1)
│   └── process_manager/     (process_manager_module)
└── application/         # тир 7: composition root + UI
    ├── app/                 (app_module)
    └── frontend/            (frontend_module)
```

Правило нейминга (по ревью): **слой-роль/способность = ед.ч.** (`foundation/execution/state/communication/
observability/ipc/runtime/application`), **слой-коллекция однотипных = мн.ч.** (`catalogs`). `registries`
отвергнуто (путается с модулем `registers`); `resources`→`ipc` (роль, ед.ч., без расплывчатости).

Контракт `import-linter` layers (сверху вниз; `|` = независимые сиблинги; `ipc` ВЫШЕ observability, т.к.
`shared_resources → logger` — реальное import-time ребро):
```
layers =
    multiprocess_framework.application
    multiprocess_framework.runtime
    multiprocess_framework.ipc
    multiprocess_framework.observability
    multiprocess_framework.communication
    multiprocess_framework.execution | multiprocess_framework.state | multiprocess_framework.catalogs
    multiprocess_framework.foundation
```

> **Enforcement работает по СТАТИЧЕСКОМУ графу (grimp), а тиры выведены по IMPORT-TIME графу** — их надо
> примирить, иначе линтер покраснеет (находка ревью K2). `exclude_type_checking_imports = True` убирает только
> `TYPE_CHECKING`-рёбра, но НЕ lazy-импорты внутри функций. Поэтому в контракт добавить **`ignore_imports`** для:
> - lazy back-edges (перечислить явно): `router.middleware.frame_shm_middleware → ipc.shared_resources` (4 сайта),
>   `runtime.process → runtime.process_manager` (lazy), `application.app → runtime/state` (lazy) и т.п.;
> - тестов: wildcard `multiprocess_framework.**.tests.** -> **` (тесты легитимно импортируют вверх — находка K3).

---

## Рекомендованный способ переноса (ответ на «как заложить правильно»)

**Детерминированный codemod + верификационные гейты, атомарно по слоям, без вечных шимов.**
Именно та схема, что ты описал (скрипт → qex → проверка нейронкой), формализованная:

- **Единая rename-таблица** `{старый_dotted_path → новый_dotted_path}` — единственный источник правды
  (например `multiprocess_framework.modules.router_module` → `multiprocess_framework.communication.router`).
  Маппинг 1:1, механический (снять суффикс + добавить слой) — без «творческих» переименований,
  чтобы codemod был предсказуем.
- **Codemod-скрипт** (`scripts/regroup_modules/`) на базе `libcst` (сохраняет форматирование) +
  `grimp` (граф импортов, тот же движок, что у import-linter):
  1. `git mv` папок (сохранить историю git);
  2. переписать **абсолютные** импорты во всём репозитории по rename-таблице;
  3. конвертировать **внутренние relative cross-module** импорты (`from ...router_module import`) в
     абсолютные — иначе смена глубины папок их сломает, а заодно это чинит слепоту sentrux к relative;
  4. обновить `__init__.py`-реэкспорты и любые обращения к пакету `modules` целиком.
- **Верификация (гейт перед merge):**
  1. `qex`/`grep`-свип на остаточные `\.modules\.` и старые имена с суффиксом — ловим пропуски codemod;
  2. LLM-ревью diff’а (агент `reviewer`) на семантический дрейф и пропущенные сайты;
  3. полный прогон **2904 тестов** + `import-linter` + `sentrux check` — красный = не мержим.
- **Шимы — опционально и временно.** Если полный атомарный diff покажется рискованным, допускается
  переходный `modules/<old>/__init__.py` с `DeprecationWarning`, реэкспортящий из нового места, но
  **удаляется в той же серии PR** — не постоянный дуализм путей.

**Почему не «просто шимы навсегда»:** два пути к одному модулю убивают «понятность», ради которой всё
затевается, и оставляют sentrux/import-linter слепыми. Цель — один канонический путь.

---

## Фазы

### Фаза 0 — Подготовка и заморозка (docs)
- `/plan`-ветка `refactor/framework-layer-grouping`, план в `plans/<slug>.md` (dual-save).
- Зафиксировать baseline: `sentrux session_start`, сохранить текущее число тестов и `coupling/quality`.
- Файлы: `plans/`, `.sentrux/baseline.json` (снимок).

### Фаза 1 — ✅ Граф измерен, слои утверждены (см. раздел «Реальный граф»)
- ГОТОВО: `grimp` + AST-агент дали точный DAG; финальный 7-уровневый порядок и раскладка папок —
  в разделах выше. Осталось оформить: `scripts/regroup_modules/mapping.py` (rename-таблица 1:1 из
  27 модулей → `<layer>/<module без _module>`) + `docs/refactors/2026-07_layer-grouping.md`
  (перенести туда обоснование + вывод `measure_graph.py`/`cycle_details.py` из scratchpad).
- **Не-модульные обитатели `modules/` (ревью K5):** `_fallback.py` (импортится `from ..._fallback import
  FallbackLogger` → положить в `foundation/` или `observability/`, обновить импортёров), `conftest.py`/
  `pytest.ini` (в новый корень пакетов или per-layer), `logs/` (runtime-вывод, в `.gitignore` — не мигрировать
  как код), `__init__.py`. Внести в mapping явно.

### Фаза 2 — Разорвать 2 import-time цикла (для чистоты графа; для layers НЕ обязателен, т.к. все 3 в `runtime`)
Точные точки из замера (`cycle_details.py`). Уточнение (ревью K4): речь про **import-time** цикл —
в статическом графе у пары есть ещё lazy-сайты (их накрывает `ignore_imports`, Фаза 4).
- **`process → process_manager`:** удалить шим-импорт в `process_module/generic/blueprint.py:12`
  (ADR-PMM-016 «после миграции удаляется») — потребители берут `SystemBlueprint/ProcessConfig/Wire/Port`
  напрямую из `process_manager_module.topology`.
- **`console → process`:** ⚠️ TYPE_CHECKING НЕВОЗМОЖЕН (ревью K1): `ProcessLaunchConfig` — базовый класс
  `ConsoleProcessConfig`, `ManagersConfig` инстанцируется. Фикс — **переместить** `console_module/configs/
  console_process_config.py` → `process_module/configs/` (это артефакт запуска процесса, не собственность
  консоли); обратное `process → console` (владение) остаётся.
- Проверить `measure_graph.py` (мерит import-time): раздел «ЦИКЛЫ» пуст.
- Заодно (единообразие 27/27): дать `actions_module` верхний `interfaces.py`
  (поднять `IActionLogWriter`/`IActionLogRepository`/`IRegistersManagerGui` в канонический контракт).

### Фаза 3 — Codemod: перенос + переписывание импортов
- **Precondition (frontend-constructor Ф0):** влиты/закрыты все in-flight ветки, трогающие import-поверхность — в частности `feat/backend-ctl-debug-console` (**влит в main 2026-07-18**, SHA 27d17ee7). `backend_ctl → tooling/` — отдельный пост-codemod план (BCTL-DECISIONS); codemod лишь переписывает импорты ВНУТРИ `backend_ctl`, не переносит пакет.
- Написать и прогнать `scripts/regroup_modules/` (см. «Способ переноса»). Один атомарный проход,
  либо послойно (foundation → … → application), каждый слой — отдельный коммит, но всё в одной ветке.
- Обновить якоря на старые пути: `.sentrux/rules.toml` (boundaries), `pyproject.toml`
  (`[tool.pytest]`, packages/`conftest`), `Makefile`, `scripts/validate.py`, диаграммы, CLAUDE.md-ссылки.
- Ключевые внешние потребители под особым вниманием: `multiprocess_prototype/**` (~395 сайтов),
  `Services/**`, `backend_ctl/**`, корневой `multiprocess_framework/__init__.py`.

### Фаза 4 — Enforcement (import-linter)  [пакеты уже установлены: grimp/import-linter/libcst/pydeps]
- `.importlinter`: контракт `layers` в порядке из блока «Целевая структура» (`ipc` выше observability;
  `execution|state|catalogs` — сиблинги) + `independence` для листьев (`foundation.data_schema`,
  `communication.message`, `communication.event`, `state.recipe`, `catalogs.display`, `catalogs.service`) +
  `forbidden` «никто не импортирует `application`».
- **`ignore_imports` (обязательно, ревью K2/K3):** `exclude_type_checking_imports=True` НЕ покрывает
  lazy-импорты внутри функций. Явно игнорировать: (1) lazy back-edges (перечислить по факту `grimp`, в т.ч.
  `...router.middleware.frame_shm_middleware -> ...ipc.shared_resources.*` ×4, lazy `process→process_manager`,
  `app→*`); (2) тесты `multiprocess_framework.**.tests.** -> **` (тесты импортируют вверх легитимно).
  Практика: сначала прогнать `lint-imports`, собрать список нарушений-от-lazy/тестов, занести в `ignore_imports`.
- Подключить `lint-imports` в `make check`/CI и в pre-push рядом с sentrux.
- Обновить `.sentrux/rules.toml`: описать межслойные boundaries новыми путями (теперь абсолютными —
  sentrux их увидит), убрать оговорку про relative-слепоту.

### Фаза 5 — Верификация и закрытие
- Гейт: `python scripts/run_framework_tests.py` (все ~2904), `lint-imports`, `sentrux session_end`
  (дельта coupling/quality не хуже baseline), qex-свип на остаточные старые пути.
- Обновить `CONSTRUCTOR_BLUEPRINT.md`/`MODULE_CONTRACTS.md`/`MODULES_RESPONSIBILITY_MAP.md`:
  теперь слои = реальные папки, а не только mermaid. Прогнать `python -m scripts.sync`.
- Коммиты по Conventional Commits с `Why:`/`Layer: framework`/`Refs: plans/<slug>.md`.

---

## Риски и как их держим

| Риск | Митигация |
|------|-----------|
| ~1970 импортов, пропуск сайта | Детерминированный codemod + qex/grep-свип + LLM-ревью diff + полный тест-суит как гейт |
| Смена глубины ломает relative-импорты | Codemod конвертирует cross-module relative → absolute (заодно чинит слепоту sentrux) |
| Слои из документа ≠ реальный граф (router→shared_resources) | Фаза 1: порядок выводится из измеренного графа, не из блупринта |
| Латентный цикл process↔process_manager всплывёт при переносе | Закрыть ДО переноса (Фаза 2) |
| Продукт важнее движка (установка владельца) | Работа изолирована в одной ветке, атомарна, полностью откатываема; не трогает поведение |
| Динамический скан плагинов/сервисов по путям | Проверить `app_module/discovery.py` и `service_module/scanner.py` на хардкод `modules.` |
| Codemod-конфликт с параллельными ветками (переписывает импорты в 910 файлах) | Precondition Фазы 3: влить/закрыть in-flight ветки (`feat/backend-ctl-debug-console` — **влит 2026-07-18**; в т.ч. [`gui-telemetry-read-model`](../gui-telemetry-read-model.md) — его Фаза 0-hotfix идёт ДО codemod); на время Фазы 3 — freeze-окно на новые ветки |
| Строковые dotted-пути вне импортов (YAML-топологии `worker_class`, рецепты, БД, pickle-останки очередей) | Свип `multiprocess_framework.modules.` по НЕ-py файлам (yaml/json/db/md) + отдельная проверка перед merge; персистированные рецепты перегенерировать |

## Verification (как убедиться, что всё работает)
1. `python scripts/run_framework_tests.py` и `python scripts/validate.py` — зелёные, число тестов не упало.
2. `lint-imports` — контракт `layers` проходит (ни одного нарушения слоя).
3. `sentrux session_end` vs baseline — `coupling`/`quality` не хуже, `cycle_count 0` теперь честный
   (relative→absolute), `check_rules` зелёный.
4. qex/grep: `\bmultiprocess_framework\.modules\.` и `_module\b` в путях импорта — 0 остаточных (кроме
   намеренных временных шимов, если выбраны).
5. Дымовой прогон прототипа: `python multiprocess_prototype/run.py <recipe>` + qt-mcp probe
   (`QT_MCP_PROBE=1`, порт 9142) — GUI собирается, вкладки живые.

---

## Чек-лист миграции (по порядку)

**Фаза 0 — подготовка**
- [ ] Ветка `refactor/framework-layer-grouping`, план в `plans/<slug>.md` (dual-write в `docs/claude/memory/` не нужен — это план, не memory)
- [ ] Baseline: `sentrux session_start`; зафиксировать число тестов + `coupling/quality`
- [ ] Перенести `measure_graph.py` / `cycle_details.py` из scratchpad в `scripts/regroup_modules/`

**Фаза 2 — разорвать 2 runtime-цикла (ДО переноса)** — ✅ **основное закрыто 2026-07-18** (сверено по git 2026-07-20; выполнено вне ветки плана, отдельными коммитами в `main`)
- [x] `process_module/generic/blueprint.py:12` — убрать шим-импорт `process_manager` (ADR-PMM-016), потребители берут типы из `process_manager_module.topology` — **`92c19f2e`** (шим удалён целиком)
- [x] `console_module/configs/console_process_config.py:12-13` — импорт `process.configs.*` под `if TYPE_CHECKING:` — **`d9dddf45`**, но **решено иначе, чем планировалось**: `ConsoleProcessConfig` физически перенесён `console_module` → `process_module` (цикл разорван переносом владельца, а не отложенным импортом). План здесь опережён фактом — способ лучше, фиксируем как есть.
- [x] `actions_module/interfaces.py` — создать (поднять `IActionLogWriter`/`IActionLogRepository`/`IRegistersManagerGui`) → единообразие 27/27 — **`bf484bcd`**
- [ ] `measure_graph.py`: раздел «ЦИКЛЫ» пуст, топосортировка без остатка — **не перепроверено после трёх фиксов выше**
- [ ] Тесты зелёные (циклы правились — прогнать `run_framework_tests.py`) — **не прогонялось как приёмка фазы**

**Фаза 3 — codemod (перенос + импорты)**
- [ ] `scripts/regroup_modules/mapping.py` — rename-таблица 1:1 (27 модулей → `<layer>/<без _module>`)
- [ ] `git mv` папок по 9 группам (сохранить историю)
- [ ] Codemod (`libcst`): переписать абсолютные импорты по таблице
- [ ] Codemod: relative cross-module → absolute (чинит слепоту sentrux)
- [ ] Обновить `__init__.py`-реэкспорты и обращения к пакету `modules` целиком
- [ ] Обновить якоря: `.sentrux/rules.toml`, `pyproject.toml`, `Makefile`, `scripts/validate.py`, диаграммы, CLAUDE.md
- [ ] Проверить хардкод путей: `app_module/discovery.py`, `service_module/scanner.py` (динамический скан)
- [ ] qex/grep-свип: 0 остаточных `\.modules\.` и `_module\b` в импортах
- [ ] LLM-ревью diff (агент `reviewer`) — семантический дрейф, пропущенные сайты
- [ ] Полный тест-суит (~2904) зелёный

**Фаза 4 — enforcement**
- [ ] `.importlinter`: `layers` (измеренный порядок, `execution|state|catalogs` сиблинги) + `exclude_type_checking_imports=True` + `independence` листьев + `forbidden` на `application`
- [ ] `lint-imports` проходит; подключить в `make check`/CI + pre-push
- [ ] Обновить `.sentrux/rules.toml` под новые (абсолютные) пути

**Фаза 5 — закрытие**
- [ ] `sentrux session_end` vs baseline — не хуже; `cycle_count 0` теперь честный
- [ ] Обновить `CONSTRUCTOR_BLUEPRINT.md`/`MODULE_CONTRACTS.md`/`MODULES_RESPONSIBILITY_MAP.md` (слои = папки) + `python -m scripts.sync`
- [ ] Дымовой прогон прототипа + qt-mcp probe — GUI жив
- [ ] Коммиты по Conventional Commits (`Why:`/`Layer:`/`Refs:`)

## Критерии приёмки
- [ ] 27 модулей физически лежат в 9 папках-слоях, суффикс `_module` снят
- [ ] Все 26 имеют `interfaces.py` + фасад + `README/STATUS/DECISIONS/tests` (единообразие сохранено)
- [ ] `import-linter` layers зелёный, runtime-граф ацикличен (доказано `measure_graph.py`, не ложно)
- [ ] Число тестов не упало, прототип запускается
- [ ] Один канонический путь импорта (нет вечных шимов)

---

# ИНИЦИАТИВА 2: контракт модуля-устройства (расширение замысла)

**Замысел владельца:** каждый модуль — самостоятельное «электронное устройство» (как ЧП): снаружи только
фасад + типизированные порты, внутренности скрыты (инкапсуляция). Порты **функциональные** (вход/выход/
двунаправленные) и **информационные** (log/error/stats) — все внутренние сообщения сведены в одну точку
съёма, а через конфиг настраивается, что снимать (ошибки — всегда; логи/стат — вкл/выкл в реальном времени,
чтобы не грузить систему). У каждого модуля свой оркестратор-`main`, у фреймворка — свой фасад/бутстрап.

## Что из этого УЖЕ построено (замер 3 агентами — не изобретать заново)

| Элемент замысла | Статус | Где |
|---|---|---|
| Фасад + `interfaces.py` + инкапсуляция | ✅ 26/27 | `XxxManager` в `core/` + `__all__`; DI внутренней сборки |
| **Единый tap** (один порт, 3 сигнала log/error/stats) | ✅ есть | `ObservabilityHub` (ADR-CRM-007): 3 `BoundedChannel`, drop-in в слоты, pull-drain + счётчик потерь |
| **Ошибки always-on** | ✅ есть | write-through `ErrorManager` (переживает SIGKILL) + ERROR-tap в стор/GUI; ErrorManager создаётся всегда |
| **Логи/стат — рантайм-toggle через конфиг** | ✅ есть | секция `observability` + `ConfigFileWatcher` (watchdog) + `reconfigure()`; IPC `config.reload`; `logger.sink.enable/disable` |
| **Оркестратор-`main` модуля** | ✅ на уровне процесса | `ProcessModule` собирает 7 менеджеров в порядке зависимостей (`ProcessManagers.create_all`, return-based ADR-PM-009) |
| **Фасад + бутстрап фреймворка** | ✅ есть (два) | корневой `multiprocess_framework/__init__.py` (реестр по слоям, lazy GUI) + `app_module` (`run_app`/`SystemBuilder`, bootstrap из `app.yaml`) |
| Документация на модуль | ✅ README/STATUS/DECISIONS 27/27 | `docs/` только 7/27, `ARCHITECTURE.md` 2/27 — не единообразно |

**Вывод:** замысел реализован на ~75–80% разрозненно. Задача Инициативы 2 — **формализовать и
доунифицировать**, а не строить с нуля. Это согласуется с установкой «продукт важнее движка».

## Пробелы (что реально добавить)

1. **Единый tap подключён не универсально** — `ObservabilityHub` воткнут только в «пилотный» worker, а не
   в каждый менеджер каждого модуля. → универсализировать инъекцию hub в слоты всех менеджеров.
2. **Нет авто-fan-out конфига на дочерние процессы** — watcher живёт в оркестраторе и перестраивает только
   ЕГО менеджеры; детям — только адресной IPC `config.reload`. → достроить broadcast (задел ADR-CRM-006 Phase 4).
3. **Per-slot тумблеры** (`enable/disable/context` в `ObservableMixin`) есть в коде, но **не проброшены в
   hot-reload-конфиг**. → добавить в секцию `observability` гранулярные тумблеры на модуль/слот.
4. **Функциональные типизированные порты не формализованы** как единый контракт (есть `Port`/`Wire` в
   pipeline и `Message`/router для IPC, но не декларативный «вход/выход/двунаправленный» на каждом модуле).
   → описать контракт портов (можно поверх существующих `Port`/`FieldRouting`), не плодя новый механизм.
5. **Терминология и docs**: «оркестратор-main» реально только у процесса; рядовые модули — «фасад+сборка».
   `docs/`/`ARCHITECTURE.md` не у всех. → либо довести до 27/27, либо явно объявить опциональными.

## Решение A (ПРИНЯТО) — полный переход ObservableMixin → композитный obs-порт

Владелец выбрал **полный DI** (убрать миксин, внедрять объект-порт). Это **реверс** прежнего решения
(2026-06-07 `feedback_all_components_base_manager`: «всё наследует `BaseManager`+`ObservableMixin`») —
при исполнении обновить эту memory.
- **Как:** ввести `IObservability` (Protocol: `log/error/stat` + рычаги `enable/disable/context`) + конкретный
  `Observability`-адаптер, оборачивающий текущие слоты/`ObservabilityHub`. Внедрять `obs` в конструктор
  каждого менеджера (`def __init__(self, …, obs: IObservability)`), звать `self.obs.log/error/stat`.
- `BaseManager` (жизненный цикл) ОСТАЁТСЯ; удаляется только `ObservableMixin`-поведение → заменяется `self.obs`.
- **Масштаб/риск:** трогает `__init__` и все call-site'ы `_log/_record_metric/_track_error` во ВСЕХ модулях —
  поведенческий рефактор. Механические call-site'ы переписать codemod'ом (`libcst`); гейт — полный тест-суит.
- **Порядок:** ПОСЛЕ структурной Инициативы 1 (сначала стабильные пути, потом поведенческая правка).

## Решение B (ПРИНЯТО) — стандартные Services/Plugins → в framework как слой `stdlib/` (не в ядро)

Владелец выбрал перенос в framework. Делаем это **безопасно**: не вливать в ядро (это запрет ADR-120), а
создать **новый верхний слой** `multiprocess_framework/stdlib/{services,plugins}/` («batteries included», как
`django.contrib`). Инвариант ядра сохраняется: `core(9 слоёв) → stdlib` — **запрещён**, `stdlib → core` —
разрешён (stdlib использует `PluginContext`, как application).
- **Новый ADR**, замещающий раскладочную часть ADR-120/121/122 (не механизм discovery — он остаётся data-driven).
- **Переносим (стандартные):** Services — `sql, auth, modbus, ml_inference, ml_train, dataset_gen`;
  Plugins — `processing/*` (кроме robot/text/word/pixel/scale/strokes), `sources/{capture,frame_counter,
  heartbeat,synthetic}`, `render/*`, `runtime/*`, `io/{frame_saver,database,telemetry_sink}`, `filter/line_filter`.
- **Остаются снаружи (специфичные):** `hikvision_camera, device_hub, robot_comm, vfd_comm`; robot/vfd/text/
  word/calibration/camera_service-плагины — подключаются как сейчас через `discovery.plugin_paths`.
- **Правки:** codemod путей перенесённых пакетов; `system.yaml discovery.plugin_paths/service_paths`
  (добавить `multiprocess_framework/stdlib/...`); `.sentrux/rules.toml` (новый boundary `core→stdlib` forbid,
  снять/переписать старые `framework→Services/Plugins`); `import-linter` (слой `stdlib` над ядром).

## Мини-фазы Инициативы 2 (объём 2A+2B+2C+2D — ПРИНЯТО; после структурной Инициативы 1)

- **2A — Формализовать контракт** (docs): `MODULE_DEVICE_CONTRACT.md` (фасад + порты функц./информ. +
  оркестратор + инкапсуляция), шаблон нового модуля, довести `docs/`/`ARCHITECTURE.md` до единообразия.
  Enforce публичного API: `import-linter` правило «импорт модуля только через фасад/`interfaces`» (public-interface).
- **2B — Mixin→obs-порт + единый tap везде** (код, Решение A): `IObservability`+`Observability`,
  внедрить во все менеджеры, `ObservabilityHub` как порт во ВСЕ модули (не только пилот); гранулярные
  per-module/per-slot тумблеры в секцию `observability`.
- **2C — Config fan-out на детей** (код): broadcast reconfigure на дочерние процессы (ADR-CRM-006 Phase 4).
- **2D — Слой `stdlib/`** (структура, Решение B): перенести стандартные Services/Plugins в
  `multiprocess_framework/stdlib/`, новый ADR, обновить discovery/rules/import-linter. Специфичные — снаружи.

> Порядок: сначала Инициатива 1 (структура/пути стабилизируются), затем 2A → 2D → 2B → 2C (доки и структура
> раньше поведенческих правок observability). 2B — самый рискованный (поведенческий, все модули) — под усиленным
> тест-гейтом. Ни одна фаза не меняет бизнес-логику прототипа.

## Критерии приёмки Инициативы 2
- [ ] `MODULE_DEVICE_CONTRACT.md` + шаблон модуля; `import-linter` public-interface зелёный (импорт только через фасад)
- [ ] `docs/`/`ARCHITECTURE.md` единообразны (27/27) либо явно помечены опциональными в контракте
- [ ] `ObservableMixin` удалён; все менеджеры получают `obs: IObservability` в конструкторе; тесты зелёные
- [ ] `ObservabilityHub` подключён во все модули (не только пилот); per-module/per-slot тумблеры в `observability`
- [ ] Изменение `observability` в `system.yaml` долетает до дочерних процессов (fan-out) без рестарта — verified probe
- [ ] Стандартные Services/Plugins в `multiprocess_framework/stdlib/`; `core→stdlib` forbid зелёный; специфичные снаружи работают
- [ ] Новый ADR (замещает раскладку 120/121/122); memory `feedback_all_components_base_manager` обновлена (реверс)
- [ ] Прототип запускается, число тестов не упало

---

## Балльная оценка: до → после

«До» — по измерениям (sentrux `quality 7356`, `modularity raw 0.053`, grimp-циклы, interfaces 26/27).
«После» — проекция при ПОЛНОМ выполнении обеих инициатив.

| # | Критерий | До | После | Обоснование |
|---|----------|:--:|:-----:|-------------|
| 1 | Навигация (папки=слои) | 4 | 8.5 | было: 26 плоско, слои на бумаге; стало: 9 папок-слоёв |
| 2 | Единообразие модулей | 8 | 9.5 | уже сильно (interfaces 26/27, RSD+tests 27/27); станет 27/27 + контракт+шаблон |
| 3 | Ацикличность графа | 6 | 9 | 2 реальных runtime-цикла (grimp) → разорваны |
| 4 | Enforcement слоёв | 2 | 9 | sentrux слеп к relative («10000» ложна); станет import-linter в CI |
| 5 | Инкапсуляция / контракт-устройство | 6 | 8.5 | фасады есть, но не формализованы/не enforced |
| 6 | Информационные порты | 7 | 9 | tap/errors-always-on/toggle есть, но hub только в пилоте, нет fan-out |
| 7 | Связность / modularity | 4 | 6.5 | узкое место sentrux (3.7/10); process-hub fan-out врождённый (потолок ~7) |
| 8 | Нейминг | 5 | 9 | `_module` избыточен, `recipe` без суффикса; станет единое правило |
| 9 | Стандартное vs специфичное | 4 | 8 | нет градации; станет `stdlib/` + специфичные снаружи |
| 10 | Соответствие трендам 2026 | 6.5 | 9 | Protocol+DI+modular-monolith есть; не хватает enforced-слоёв/full-DI/batteries |

**Итог (среднее): ~5.3 / 10 → ~8.6 / 10 (+3.3).**

Оговорки: «после» предполагает и рискованный шаг 2B (Mixin→DI по всем модулям). Только Инициатива 1 даёт
~**7.2/10** (растут пп. 1,3,4,8). Самый устойчивый к росту — п.7 (modularity): низок не из-за беспорядка, а
из-за естественного fan-out `process`-хаба (17 deps) — потолок ~7/10. Проект НЕ был «плохим»: сильные стороны
(единообразие, инфо-порты, тренды) уже были — план их формализует и защищает; основной прирост — enforcement
(2→9) и навигация (4→8.5).
