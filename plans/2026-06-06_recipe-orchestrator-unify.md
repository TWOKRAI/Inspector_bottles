# Унификация оркестрации рецептов: одна дорога топологии через существующие менеджеры

**Дата:** 2026-06-06
**Ветка:** `fix/recipe-v3-engine-decouple` (текущая)
**Slug:** `recipe-orchestrator-unify`
**Базис:** компаньон к [`2026-06-06_recipe-topology-architecture-analysis.md`](2026-06-06_recipe-topology-architecture-analysis.md) и [`2026-06-06_replace-blueprint-hotswap.md`](2026-06-06_replace-blueprint-hotswap.md).
**Цель:** тот же функционал, **меньше слоёв**. Убрать ad-hoc дорогу горячей замены, зажечь
**уже существующий** framework-менеджер `TopologyManager`. Фреймворк как конструктор: кормим
generic-менеджеры через их сиды, новых движков не пишем.

---

## Диагноз: три дороги топологии вместо одной

| Дорога | Путь | Статус |
|--------|------|--------|
| **A. boot** | `launch.py SystemBuilder.build` → инлайн-сборка proc_dict → `SystemLauncher.add_process` → spawner → `PM._create_processes_from_config` | живая |
| **B. switch (ad-hoc)** | GUI `replace_blueprint` → `PM.replace_blueprint` → **`_build_proc_dicts`** (урезанная копия boot-сборки, БЕЗ defaults/obs/check) → инлайн stop/spawn/rollback | живая, кривая → баги Task 5/6/7 |
| **C. TopologyManager (framework)** | `PM.topology.apply` → `TopologyManager.apply` (diff → commands → create/stop) | **МЁРТВАЯ**: приложение не передало `diff_fn`/`commands_fn` → всегда `"not configured"` |

**Корень сложности:** generic-менеджер-конструктор `TopologyManager` уже встроен в PM
(`_setup_topology_manager`, команды `topology.apply/diff/get`, сиды `create_process_fn`/
`stop_process_fn`/`allocate_shm_fn`), но **спит**. Hot-swap построил параллельную дорогу B
вместо того, чтобы зажечь C. `RecipeManager` (каталог + активный рецепт) **тоже уже есть**
(`multiprocess_prototype/recipes/manager.py`).

---

## Целевая архитектура: убрать B, зажечь C (переиспользование менеджеров)

```
GUI: apply_topology(slug | blueprint)          ← тонкий, без сборки proc_dict
  → RecipeManager.read(slug)                    ← СУЩЕСТВУЕТ (каталог / активный)
  → TopologyManager.apply(blueprint_dict)       ← СУЩЕСТВУЕТ (framework, спал)
       diff_fn:     что изменилось              ← app-callback (full-replace сегодня)
       commands_fn: blueprint_to_proc_dicts(..) ← НОВОЕ (вынос инлайна boot, чистая fn)
       → create_process_fn / stop_process_fn    ← сиды PM уже есть
УДАЛЯЕТСЯ: _build_proc_dicts + ad-hoc replace_blueprint-сборка
```

| Слой | Компонент | Статус | Ответственность |
|------|-----------|--------|-----------------|
| framework | `TopologyManager` | **есть, зажечь** | generic apply: diff → commands → create/stop + SHM |
| framework | `ProcessManagerProcess` | есть | сиды `create_process_fn`/`stop_process_fn`/`allocate_shm_fn` |
| framework (карв-аут) | `BlueprintAssembler` | **цель Phase 5** | `(blueprint, defaults, observability) → proc_dicts` (generic-ядро) |
| prototype | `blueprint_to_proc_dicts` | **новое (вынос)** | склейка framework-вызовов + app-defaults; `commands_fn` |
| prototype | `RecipeManager` | **есть, переиспользовать** | каталог рецептов, активный, read(slug), set_active |
| prototype | GUI presenters | упростить | одна `apply_topology(slug\|blueprint)` + debounce |

**Счёт слоёв:** 3 дороги → 1. Удаляем `_build_proc_dicts`. Зажигаем 1 спящий менеджер
(новых классов 0). Добавляем 1 чистую функцию (на 90% — уже-framework-вызовы:
`SystemBlueprint.build_configs`, `process()`, `merge_with_defaults`, `expand_observability`,
`merge_managers`). App-specific только `_merge_defaults` (читает `SystemConfig`).

---

## Фазы

### Phase 1 — Канонический трансформер (вынос, без изменения поведения)

#### Task 1.1 — `blueprint_to_proc_dicts`
**Level:** Senior (TeamLead) · **Файлы:** `multiprocess_prototype/backend/assembly.py` (новый), `tests/`
**Goal:** Одна чистая функция сборки proc_dict (вынос инлайна `launch.py:238-287` + нормализация из `SystemLauncher.add_process`).
**Steps:** 1. `blueprint_to_proc_dicts(blueprint_dict, sys_config) -> dict[str, dict]`. 2. Тело: `_merge_defaults` → `SystemBlueprint.model_validate` → `check()` → `build_configs()` → `process(cfg)` → `merge_managers(obs)` → `merge_with_defaults(DEFAULT_PROCESS_SCHEMA)`. 3. Невалидно → `raise BlueprintInvalid` (не `sys.exit`).
**Acceptance:** - [ ] pure - [ ] тест: эталонный recipe → ожидаемые proc_dict - [ ] невалид → BlueprintInvalid

#### Task 1.2 — boot через трансформер
**Level:** Middle+ (Developer) · **Файлы:** `launch.py`
**Goal:** `SystemBuilder.build()` использует трансформер (дорога A на единой сборке).
**Acceptance:** - [ ] boot proc_dict идентичен прежнему (diff-тест) - [ ] qt-smoke старт

### Phase 2 — Зажечь TopologyManager (full-replace через сиды)

#### Task 2.1 — `diff_fn`/`commands_fn` full-replace
**Level:** Senior (TeamLead) · **Файлы:** `multiprocess_prototype/backend/topology_apply.py` (новый) или в `assembly.py`, `tests/`
**Goal:** App-callbacks для `TopologyManager`: diff = «всё non-protected заменить», commands = `blueprint_to_proc_dicts` → `[{cmd:process.stop,...}, {cmd:process.create, proc_dict:...}]`.
**Steps:** 1. `make_full_replace_diff_fn(protected_provider)`. 2. `make_commands_fn(sys_config)` строит stop+create команды из proc_dicts. 3. Учесть protected (GUI/PM не трогаем), rollback семантику.
**Acceptance:** - [ ] тест: diff/commands дают тот же набор, что текущий replace_blueprint - [ ] protected сохранены

#### Task 2.2 — Сконфигурировать менеджер в prototype-оркестраторе
**Level:** Senior (TeamLead) · **Файлы:** `orchestrator.py` (+ sys_config в PM), `launch.py` orchestrator_config
**Goal:** `ProcessManagerProcessApp` передаёт sys_config + `topology_manager.configure(diff_fn, commands_fn)`.
**Steps:** 1. `orchestrator_config["sys_config"]=sys_config.model_dump()`. 2. В подклассе после `initialize` → `self._topology_manager.configure(...)`. 3. `topology.apply` оживает.
**Acceptance:** - [ ] `topology.apply(blueprint)` поднимает процессы с defaults+obs (паритет boot) - [ ] qt-smoke переключение

#### Task 2.3 — Удалить ad-hoc дорогу B
**Level:** Middle+ (Developer) · **Файлы:** PM-процесс
**Goal:** Убрать `_build_proc_dicts`; `blueprint.replace` → делегировать в `topology.apply` (или удалить, GUI перейдёт на `topology.apply`).
**Acceptance:** - [ ] grep `_build_proc_dicts` пуст - [ ] sentrux check_rules зелёный - [ ] тесты rollback/protected зелёные на дороге C

### Phase 3 — RecipeManager как единый владелец активного рецепта

#### Task 3.1 — Активный рецепт в RecipeManager (backend)
**Level:** Middle+ (Developer) · **Файлы:** `recipes/manager.py` (переиспользуем), `orchestrator.py`
**Goal:** Дефолт из манифеста (`app.pipeline`) ставится через `RecipeManager.set_active`; backend — источник истины.
**Acceptance:** - [ ] активный рецепт читается из RecipeManager, не из 3 мест

### Phase 4 — Тонкий GUI + debounce

#### Task 4.1 — proxy: `apply_topology`
**Level:** Middle+ (Developer) · **Файлы:** `frontend/bridge/process_manager_proxy.py`
**Goal:** `apply_topology(source: str|dict, on_result=None)` → cmd `topology.apply` (slug резолвится backend через RecipeManager, либо передаём blueprint). Заменяет `replace_blueprint*`.

#### Task 4.2 — Свести 3 точки входа + debounce
**Level:** Senior (TeamLead) · **Файлы:** `recipes/presenter.py`, `pipeline/presenter.py`
**Goal:** Recipes «Загрузить» (slug), Pipeline «Запустить»/«Перезапустить» (in-memory blueprint) → один путь + коалесинг.
**Acceptance:** - [ ] нет «тасования» - [ ] qt-smoke 3 кнопки

### Phase 5 — Carve-out во фреймворк (forcing-function)

- `BlueprintAssembler` (framework): `(blueprint, defaults_dict, observability_dict) → proc_dicts`. Прототип поставляет dict из `SystemConfig`. (память `project_prototype_carveout`).
- generic `diff_fn`/`commands_fn` full-replace → framework; app оставляет только маппинг defaults.
- Дальше: incremental `diff_fn` (память `project_pipeline_live_incremental_vision`) — тот же `TopologyManager`, умнее diff. Full-replace → incremental без смены архитектуры.
- Чистка: `wires` editor-only; свернуть Pydantic-дуализм; `_restore_plugin_configs` → явный `PluginRegistry.config_for`.

---

## Вне scope

- **Блокер кадров `output_frames`** (§5/§7.4 анализа) — отдельный P0 про SHM lifetime. Унификация switch убирает hot-swap-рассинхрон, boot-гонку лечить отдельно.

## Риски

| Риск | Митигация |
|------|-----------|
| sys_config не пиклится через spawn | `model_dump()` → чистый dict (Dict at Boundary) |
| `TopologyManager.apply` diff-семантика ≠ текущему replace | Task 2.1 diff/commands повторяют full-replace 1:1, тест-паритет |
| framework перестал валидировать blueprint | валидация в `blueprint_to_proc_dicts` (commands_fn) ДО stop |
| boot proc_dict разъехался | diff-тест Task 1.2 (байт-в-байт) |
| protected рестартятся | diff_fn исключает protected (как `_get_protected_names`) |

## Приёмка (общая)

- [ ] Одна дорога: boot и switch зовут `blueprint_to_proc_dicts`; switch идёт через `TopologyManager`.
- [ ] `grep _build_proc_dicts` пуст; `topology.apply` живой (не `"not configured"`).
- [ ] framework не импортирует prototype (sentrux check_rules); health не ниже baseline.
- [ ] qt-smoke: старт + переключение (Recipes «Загрузить», Pipeline «Запустить»/«Перезапустить»).
