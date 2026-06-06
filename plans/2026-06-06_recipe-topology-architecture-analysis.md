# Архитектура системы рецептов и топологии — полный анализ + карта лишних слоёв

**Дата:** 2026-06-06
**Контекст:** компаньон к [`2026-06-06_replace-blueprint-hotswap.md`](2026-06-06_replace-blueprint-hotswap.md).
**Цель:** разобрать, как реально работает вся цепочка «рецепт → топология → живые процессы»,
найти избыточные слои и предложить упрощение «тот же функционал — меньше багов».
**Метод:** статический анализ кода (3 investigator-агента + ручная верификация ключевых файлов).

---

## TL;DR (для занятых)

1. **Два ОРТОГОНАЛЬНЫХ блокера.** Их часто путают, но это разные проблемы:
   - **(A) Доставка кадров** (`output_frames_*_N not found`) — ломается **даже на boot, без переключения**.
     Это НЕ про рецепты/слои, это про **время жизни SHM-хэндлов** и lazy-аллокацию. Главный продукт-блокер.
   - **(B) Hot-swap асимметрия** — переключение рецепта идёт **другим путём**, чем boot, и теряет 4 слоя
     (defaults, observability, валидацию, нормализацию). Лечится переходом на единый путь сборки.

2. **Корень сложности — ДВА пути сборки одного и того же.** boot собирает в `launch.py`,
   hot-swap — в `_build_proc_dicts`. Логика частично дублирована, частично разошлась → баги Task 5/6/7.

3. **Конверт переупаковывается 7-8 раз:** `dict → dict → dict → dict → Pydantic → Pydantic → dict → dict`.
   Два Pydantic-слоя (`SystemBlueprint` и `GenericProcessConfig`) на одни и те же данные.

4. **Рекомендация (совпадает с «B» из плана и «меньше слоёв»):** один канонический трансформер
   `blueprint_dict + sys_config → {name: proc_dict}`, вызываемый И boot, И switch. Переключение = чистый
   рестарт non-protected процессов **тем же boot-путём**. `_build_proc_dicts` удаляется. boot == switch.

---

## 1. Понятийная модель: рецепт vs топология vs blueprint

Три слова для почти одного и того же — источник путаницы:

| Термин | Что это физически | Где живёт |
|--------|-------------------|-----------|
| **Рецепт (recipe)** | YAML-файл `recipes/X.yaml`. Обёртка: `{name, version, description, blueprint:{...}, display_bindings, gui_positions}` | `multiprocess_prototype/recipes/*.yaml` |
| **Топология (topology)** | «Плоский» dict `{processes, wires, displays}` — то, что внутри `blueprint:` после разворачивания | in-memory (после `unwrap_recipe`) |
| **Blueprint (SystemBlueprint)** | Pydantic/SchemaBase-объект `{name, processes:[ProcessConfig], wires:[Wire]}` | `process_module/generic/blueprint.py` |

> Рецепт = blueprint + GUI-метаданные (позиции нод, привязки дисплеев). Топология = тот же blueprint,
> но как сырой dict. **Три имени одной сущности** — уже сигнал лишних слоёв.

---

## 2. Полный путь BOOT: от `app.yaml` до живого процесса

Каждая стрелка — отдельная трансформация конверта. Точные file:line проверены по коду.

```
app.yaml  (pipeline: recipes/region_pipeline.yaml)
   │  load_manifest → SystemBuilder.from_manifest          [main.py:68-74, launch.py:177-194]
   ▼
recipes/region_pipeline.yaml   v3: {name, blueprint:{processes,wires,displays}, display_bindings}
   │  load_topology_dict → unwrap_recipe                   [launch.py:40-73]   dict→dict
   ▼
topology dict   плоский: {processes, wires, displays}
   │  merge_topologies(base, pipeline)  (если app.base)    [launch.py:76-115]  dict→dict
   ▼
merged dict
   │  _merge_defaults(bp, system.yaml)                     [launch.py:118-132] dict→dict (мутация плагинов)
   ▼
bp_dict   (плагины обогащены defaults категории)
   │  SystemBlueprint.model_validate                       [launch.py:243]     dict→Pydantic #1
   ▼
SystemBlueprint   {processes:[ProcessConfig], wires:[Wire]}
   │  topology.check()  — валидация портов/wires           [launch.py:244, blueprint.py:185-261]
   │  build_configs() → as_generic_config()                [blueprint.py:102-174]  Pydantic→Pydantic #2
   │      └─ _restore_plugin_configs(): динамический import Plugins.*.config + перебор атрибутов
   │         ради агрегации memory                          [blueprint.py:282-322]  ← хрупкий best-effort
   ▼
list[GenericProcessConfig]   (Pydantic #2; chain_targets/plugins/memory/process_class)
   │  process(cfg) → build_process_with_workers → .build() [config_converters.py:60-66 → process_launch_config.py:78-116]
   │      flat→nested: process_class→"class", остаток model_dump()→"config"   Pydantic→dict
   ▼
(name, proc_dict)   nested: {class, queues, priority, protected, workers, config:{plugins,chain_targets,...}, managers, memory}
   │  + obs_overlay / merge_managers                       [launch.py:283-286]  (ТОЛЬКО boot)
   │  launcher.add_process → merge_with_defaults(DEFAULT_PROCESS_SCHEMA) [system_launcher.py:88]  (ТОЛЬКО boot)
   ▼
proc_dict (финальный)
   │  spawner: {processes_config:{name:proc_dict}} → PM.initialize    [spawner.py:77-83]
   │  _create_processes_from_config → registry.create_and_register → spawn Process  [pm_process.py:996-1014]
   ▼
ЖИВОЙ ПРОЦЕСС
```

**Счёт представлений одного конверта:** raw recipe → topology → merged → bp_dict → SystemBlueprint →
GenericProcessConfig → proc_dict → normalized proc_dict. **8 форм, 2 раза в Pydantic и обратно.**

---

## 3. Путь HOT-SWAP и его асимметрия (корень багов Task 5/6/7)

```
GUI кнопка ("Загрузить" / "Перезапустить" / "Запустить")
   │  presenter → ProcessManagerProxy.replace_blueprint(blueprint_dict)   [proxy.py:72-81]
   │  IPC: cmd="blueprint.replace"
   ▼
PM._cmd_blueprint_replace → PM.replace_blueprint(new_blueprint)           [pm_process.py:690-864]
   │  _build_proc_dicts(new_blueprint)                                     [pm_process.py:650-688]
   ▼
   SystemBlueprint.model_validate → build_configs() → process(cfg)        ← ТОЛЬКО слои 3-5 из boot
```

**Что hot-swap ТЕРЯЕТ по сравнению с boot:**

| Слой boot | Есть в hot-swap? | Последствие отсутствия |
|-----------|------------------|------------------------|
| `unwrap_recipe` | — (GUI уже шлёт `blueprint`) | ок, GUI разворачивает сам |
| `merge_topologies(base⊕pipeline)` | **НЕТ** | новый рецепт без фундамента (приемлемо — protected живут) |
| `_merge_defaults(system.yaml)` | **НЕТ** | плагины hot-swap-процессов БЕЗ defaults (camera_id, fps, resolution) |
| `SystemBlueprint.model_validate` | да | — |
| `topology.check()` | **НЕТ** | невалидный рецепт упадёт уже в рантайме, не до старта |
| `build_configs()` | да | — |
| `process(cfg)` | да | — |
| `obs_overlay / merge_managers` | **НЕТ** | hot-swap-процессы без observability-настроек |
| `merge_with_defaults(DEFAULT_PROCESS_SCHEMA)` | **НЕТ** | структура уже корректна после build(), но без явной нормализации |

> **Это и есть архитектурный долг #1.** `_build_proc_dicts` — урезанная копия boot-сборки внутри
> PM-процесса, у которого НЕТ доступа к `sys_config`. Каждая «потерянная» строка — потенциальный баг
> (Task 5 «процессы пустые» был ровно этим классом — flat-формат вместо nested).

**Три точки входа в `replace_blueprint`** (агент 3, подтверждено):
1. Recipes-таб «Загрузить» — `presenter.on_set_active` (fire-and-forget) [recipes/presenter.py:295-385]
2. Pipeline-таб «Перезапустить» — `restart_topology` из in-memory графа (fire-and-forget) [pipeline/presenter.py:1632-1675]
3. Pipeline-таб «Запустить» — `launch_active_recipe` (request/response) [pipeline/presenter.py:1527-1596]

Периодического вызова в коде НЕТ — «тасование каждые 15с» = повторные клики / наложение 3 точек без
дебаунса + ProcessMonitor heartbeat. **Нужна одна дебаунс-точка применения.**

---

## 4. Рантайм-топология: как РЕАЛЬНО текут кадры

**Ключевой факт (подтверждён обоими агентами):** маршрутизация в рантайме идёт **исключительно через
`chain_targets`** (имена процессов-получателей). `wires` (port-level) — **мертвы для рантайма**:

- `build_configs() → as_generic_config()` конвертирует только `chain_targets` — `wires` **не передаются**
  в `GenericProcessConfig` вообще [blueprint.py:102-132].
- `wires` используются ТОЛЬКО в: `check()` (валидация), `describe()` (текст), `bootstrap._build_wires_section`
  (state-дерево «pending»), `topology_bridge.connect_wire()` (GUI-команда `wire.setup`, не зовётся при старте рецепта).

> **Два представления связей в одном рецепте** (`chain_targets` процессного уровня + `wires` портового) —
> архитектурный долг #2. Редактор рисует `wires`, бэкенд слушает `chain_targets`. Рассинхрон неизбежен.

**Поток кадра producer→consumer:**
```
[camera_0]  SourceProducer → RouterManager.send
   → FrameShmMiddleware.strip_and_write:                   [frame_shm_middleware.py:149-182]
        lazy _allocate_shm → create_shm_blocks("output_frames", coll=3) → output_frames_{PID}_0/1/2
        idx = write_index % 3
        shm_name = write_images(...)  → data["shm_actual_name"] = "output_frames_6592_2"
        data.pop("frame")
   → queue (multiprocessing.Queue)
[preprocessor]  DataReceiver → FrameShmMiddleware.restore_frame:   [frame_shm_middleware.py:328-341]
        Attempt 1: read_images(owner, "output_frames", idx)  → ВСЕГДА None cross-process (нет handles)
        Attempt 2: SharedMemory("output_frames_6592_2", create=False) → FileNotFoundError → лог ошибки
        item["frame"] = None  → ЦЕПОЧКА РВЁТСЯ → GUI не обновляется
```

---

## 5. Блокер доставки кадров (output_frames) — root cause

**Confidence: HIGH.** Это **главный продукт-блокер** и он **шире hot-swap** (ломается на boot).

**Две взаимоусиливающие причины:**

1. **Attempt 1 (MemoryManager.read_images) НИКОГДА не работает cross-process.** Consumer открывает
   handles producer-а в `reinitialize_handles` при своём старте [manager.py:104-138], но SHM создаётся
   **lazy** — только на первом кадре producer-а, *после* старта consumer-а. → handles пусты → Attempt 1
   всегда падает в None → всё держится на хрупком Attempt 2 (fallback по имени).

2. **Время жизни SHM-хэндла (Windows).** `unlink()` на Windows — no-op; сегмент жив, пока открыт хоть один
   handle [shm.py:149-166]. Producer не сохраняет handle после записи — сегмент жив только пока жив
   процесс-producer. Если producer перезапустился/упал (а при region_pipeline и restart-loop это
   происходит), в очереди consumer-а остаются сообщения с `shm_actual_name` уже мёртвого сегмента →
   `not found`. Индекс `_2` = третий кадр → producer успел отправить ≥3 кадра и умер.

> **Вывод:** доставка кадров держится на одном хрупком fallback-механизме (открыть SHM по имени из
> сообщения), который ломается при любом рассинхроне жизни producer-а и его очереди. Это **не про слои
> рецептов** — это про модель межстадийной передачи кадров. Лечить отдельно (см. §7.4).

---

## 6. Карта лишних слоёв (свод)

| # | Лишний слой | Где | Чем плох | Вердикт |
|---|-------------|-----|----------|---------|
| 1 | **Два пути сборки** boot vs `_build_proc_dicts` | launch.py vs pm_process.py:650 | Дублирование + асимметрия (4 потерянных слоя) → Task 5/6/7 | **Слить в один** |
| 2 | **Двойной Pydantic round-trip** | SystemBlueprint → GenericProcessConfig → model_dump | dict→Pydantic→Pydantic→dict ради тех же данных | Свернуть до одного |
| 3 | **`process()` алиас** | config_converters.py:60-66 | Пустая обёртка над `.build()` | Инлайнить |
| 4 | **`_restore_plugin_configs`** | blueprint.py:282-322 | Динамич. import + перебор атрибутов ради `memory`; тихий провал → нет SHM | Заменить явным реестром |
| 5 | **`wires` в рантайм-рецепте** | blueprint.py:167 | Мертвы для рантайма; дублируют `chain_targets` | Пометить editor-only / убрать из запуска |
| 6 | **flat vs nested proc_dict** | process_launch_config.py:78-116 | Два формата → исторический баг Task 5 | Один формат |
| 7 | **`GenericProcessConfig.build()` переписывает plugins** | generic_process_config.py:186 | `config["plugins"]` уже есть после model_dump | Удалить дубль |

---

## 7. Предложение: упрощённая архитектура (тот же функционал, меньше слоёв)

### 7.1. Единый канонический трансформер (закрывает долг #1 — асимметрию)

Один чистый модуль-функция, **вызываемая И boot, И switch**:

```python
# multiprocess_prototype/backend/assembly.py  (новый, app-слой)
def blueprint_to_proc_dicts(
    blueprint_dict: dict,          # уже развёрнутая топология {processes, wires, displays}
    sys_config: SystemConfig,      # для defaults + observability
) -> dict[str, dict]:             # {name: финальный proc_dict}
    bp = _merge_defaults(blueprint_dict, sys_config)
    topology = SystemBlueprint.model_validate(bp)
    errors = topology.check()                       # валидация и для hot-swap тоже
    if errors: raise BlueprintInvalid(errors)
    obs = expand_observability(sys_config.observability.model_dump())
    result = {}
    for cfg in topology.build_configs():
        name, proc_dict = process(cfg)
        proc_dict["managers"] = merge_managers(proc_dict.get("managers", {}), obs)
        result[name] = merge_with_defaults(proc_dict, DEFAULT_PROCESS_SCHEMA)
    return result
```

- **boot:** `SystemBuilder.build()` зовёт его вместо ручного цикла [launch.py:283-287].
- **switch:** `_build_proc_dicts` **удаляется**; switch делает то же самое.
  Проблема «PM не знает sys_config» решается тем, что **сборка proc_dict уходит из PM-процесса в GUI/app-слой**
  (где sys_config есть), а в PM по IPC летят уже готовые `{name: proc_dict}` — см. 7.2.

### 7.2. Переключение = чистый рестарт boot-путём (рекомендация «B» владельца)

Вместо «умного» hot-swap внутри PM:

```
switch(new_recipe):
    blueprint = unwrap_recipe(read_recipe(slug))
    proc_dicts = blueprint_to_proc_dicts(blueprint, sys_config)   # app-слой, единый трансформер
    PM.replace_processes(proc_dicts)   # IPC: stop_many(non-protected) + spawn новых ТЕМ ЖЕ путём
```

`PM.replace_processes` упрощается до: stop_many(non-protected) → register/spawn готовых proc_dict →
rollback при ошибке. **PM больше не собирает конфиги** — только останавливает/запускает. boot и switch
дают **байт-в-байт одинаковый proc_dict** → нет класса багов «hot-swap собрал не так, как boot».

> Это и есть «boot == switch, один путь сборки» из плана. Меньше слоёв, ровно тот же функционал
> (protected живут, rollback есть, SHM перестраивается, потому что процессы реально пересоздаются).

### 7.3. Свернуть двойной Pydantic + убрать `wires` из запуска (долги #2, #5, #6)

- Оставить **один** schema-слой как поверхность редактирования/валидации (`SystemBlueprint`).
  `GenericProcessConfig` — либо убрать (строить proc_dict напрямую из `ProcessConfig`), либо сделать его
  ЕДИНСТВЕННЫМ форматом без flat/nested-дуализма.
- `wires`: пометить как **editor-only** (валидация + рисование), исключить из контракта запуска. Источник
  истины маршрутизации — `chain_targets`. Один тип связей.
- `_restore_plugin_configs`: заменить тихий best-effort на явный `PluginRegistry.config_for(plugin_name)`
  (реестр уже есть) — провал должен быть громким, иначе процесс молча стартует без SHM.

### 7.4. Блокер кадров — лечить ОТДЕЛЬНО (не связано со слоями рецептов)

Это другой подсистемный долг. Минимальные варианты (по возрастанию надёжности):
- **(a)** Consumer: `SharedMemory(create=False)` с retry+timeout (дать ОС закрыть handles при switch).
- **(b)** Убрать мёртвый Attempt 1 для cross-process — он по design не работает (lazy alloc).
- **(c)** **Pre-allocation** SHM до старта процессов (в момент сборки топологии известны все стадии и формы
  кадров) — снимает гонку lazy-alloc целиком. Самый чистый, но требует знания shape заранее.

> **Важно:** упрощение §7.1-7.3 **не починит кадры само по себе**. Но переход на «B» (чистый рестарт)
> убирает hot-swap-специфичный класс рассинхрона producer-а → остаётся только boot-гонка, которую
> закрывает §7.4.

### 7.5. Единая дебаунс-точка применения (косметика, но убирает «тасование»)

Три кнопки (Загрузить/Перезапустить/Запустить) → один метод `apply_topology(blueprint, *, source)` с
коалесингом (как уже сделано для `SetPluginConfig`). Гасит наложение повторных кликов.

---

## 8. Приоритеты (продукт-first, по памяти владельца)

| Приоритет | Что | Почему |
|-----------|-----|--------|
| **P0** | §7.4 блокер кадров (вариант a или c) | Без кадров продукт не работает ВООБЩЕ (даже на boot) |
| **P1** | §7.2 switch = чистый рестарт boot-путём («B») | Убирает Task 5/6/7 класс багов разом, меньше слоёв |
| **P2** | §7.1 единый трансформер + §7.5 дебаунс | Закрывает асимметрию defaults/obs/валидации |
| **P3** | §7.3 свернуть Pydantic-дуализм + wires editor-only | Чистка, после стабилизации продукта |

> Порядок намеренный: сначала **кадры пошли** (P0), затем **переключение надёжно** (P1), затем чистка
> слоёв (P2-P3). Не наоборот — рефакторинг слоёв на неработающих кадрах диагностируется вслепую.

---

## Приложение: проверенные file:line якоря

- Boot-сборка: `multiprocess_prototype/backend/launch.py:210-289` (`SystemBuilder.build`)
- unwrap/merge/defaults: `launch.py:40-132`
- Schema: `multiprocess_framework/modules/process_module/generic/blueprint.py` (SystemBlueprint/ProcessConfig/Wire, `_restore_plugin_configs`)
- flat→nested: `multiprocess_framework/modules/process_module/configs/process_launch_config.py:78-116`
- `process()` алиас: `multiprocess_framework/modules/data_schema_module/container/config_converters.py:60-66`
- Hot-swap: `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py:650-688` (`_build_proc_dicts`), `:690-864` (`replace_blueprint`)
- Кадры SHM: `multiprocess_framework/modules/router_module/middleware/frame_shm_middleware.py:149-182` (write), `:328-341` (read), `shm.py:97-108/149-166`
- GUI точки входа: `recipes/presenter.py:295-385`, `pipeline/presenter.py:1527-1596/1632-1675`, `bridge/process_manager_proxy.py:72-114`
