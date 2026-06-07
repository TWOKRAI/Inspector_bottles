# Унификация оркестрации рецептов: одна дорога топологии через существующие менеджеры

**Дата:** 2026-06-06
**Ветка:** `fix/recipe-v3-engine-decouple` (текущая)
**Slug:** `recipe-orchestrator-unify`
**Базис:** компаньон к [`2026-06-06_recipe-topology-architecture-analysis.md`](2026-06-06_recipe-topology-architecture-analysis.md) и [`2026-06-06_replace-blueprint-hotswap.md`](2026-06-06_replace-blueprint-hotswap.md).
**Цель:** тот же функционал, **меньше слоёв**. Убрать ad-hoc дорогу горячей замены, зажечь
**уже существующий** framework-менеджер `TopologyManager`. Фреймворк как конструктор: кормим
generic-менеджеры через их сиды, новых движков не пишем.

**Ревизия:** учтён план-ревью (Opus, 2026-06-06) — 8 дыр (rollback, `_process_configs`,
SHM-cleanup, monitor-pause, SHM-alloc-фаза, эталон diff-теста, адрес debounce, wire-cleanup).
Архитектура переработана под чёткое разделение ответственностей (см. ниже).

---

## Диагноз: три дороги топологии вместо одной

| Дорога | Путь | Статус |
|--------|------|--------|
| **A. boot** | `launch.py SystemBuilder.build` → инлайн-сборка proc_dict → `SystemLauncher.add_process` → spawner → `PM._create_processes_from_config` | живая |
| **B. switch (ad-hoc)** | GUI `replace_blueprint` → `PM.replace_blueprint` → **`_build_proc_dicts`** (урезанная копия boot-сборки) + инлайн stop/cleanup/spawn/rollback/monitor-pause/debounce | живая, кривая → баги Task 5/6/7 |
| **C. TopologyManager (framework)** | `PM.topology.apply` → `TopologyManager.apply` (diff → commands → create/stop) | **МЁРТВАЯ**: приложение не передало `diff_fn`/`commands_fn` → всегда `"not configured"` |

**Корень сложности:** generic-менеджер-конструктор `TopologyManager` уже встроен в PM
(`_setup_topology_manager`, команды `topology.apply/diff/get`, сиды), но **спит**. Hot-swap
построил параллельную дорогу B вместо того, чтобы зажечь C. `RecipeManager` (каталог +
активный рецепт) **тоже уже есть** (`multiprocess_prototype/recipes/manager.py`).

**Что ревью вскрыло:** дорога B — это не только «двухфазная сборка», а **сборка + rollback +
SHM-cleanup + monitor-pause + `_process_configs`-sync + debounce**. Унификация обязана сохранить
всю эту обвязку, иначе на дороге C получим утечки SHM, мёртвые процессы в реестре, гонки
монитора и невозможность отката. Решение — не размазывать обвязку, а **дать ей явного владельца**.

---

## Архитектура ответственностей (single responsibility, явные границы)

Принцип: разделить **политику** (что менять — чистые функции), **исполнение** (как исполнять
команды — generic-менеджер) и **транзакцию** (побочные эффекты и откат — обёртка PM).
Каждый слой тестируется изолированно.

```
GUI proxy.apply_topology(slug|blueprint)        ← ТОНКИЙ: только отправить cmd
        │  (slug резолвится на backend через RecipeManager)
        ▼
PM.apply_topology(blueprint)   ◄── ТРАНЗАКЦИЯ (владелец побочных эффектов)
   1. in-flight guard + debounce        (повтор-клики коалесятся; backend, не обойти по IPC)
   2. snapshot = _snapshot_processes()  (уже есть в PM)
   3. _process_monitor.pause()          (уже есть)
   4. result = TopologyManager.apply(blueprint)   ◄── ИСПОЛНЕНИЕ (чистый executor)
   5. if not result.success: _restore_from_snapshot(snapshot)   (откат, уже есть)
   6. finally: _process_monitor.resume()
        │
        ▼
TopologyManager.apply(blueprint)   ◄── ИСПОЛНЕНИЕ: diff → commands → выполнить ПО ПОРЯДКУ
   planner.diff(current, desired)     → что менять      ◄── ПОЛИТИКА (FullReplacePlanner, prototype)
   planner.commands(diff, desired)    → 5 фаз команд    ◄── ПОЛИТИКА (тот же planner)
        (передаётся в менеджер как два связанных метода — configure(diff_fn=planner.diff, ...))
   for cmd in commands: _execute_command(cmd)  → один сид на тип, собирает результаты
        │
        ▼
Сиды PM (по одной ответственности каждый):
   process.stop      → stop_process(name)                       (halt)
   process.cleanup   → remove_process + release SHM + del cfg   (free)
   process.provision → register_process(queue) + allocate SHM   (provision comms)
   process.create    → create_and_register + cfg                (instantiate)
   process.start     → start_process(name)                      (run)
```

### Кто за что отвечает

| Слой | Компонент | Файл | Ответственность (ровно одна) | Тест |
|------|-----------|------|------------------------------|------|
| **Политика: сборка** | `BlueprintAssembler` | `prototype/backend/assembly/assembler.py` (новый) | `(нормализованный blueprint dict) → proc_dicts dict`. **Stateless, только framework-примитивы внутри** (per-category defaults применяются СНАРУЖИ — carve-out-ready). Не «manager». | unit: recipe → ожидаемый proc_dict (эталон = boot A); grep import чист от prototype |
| **Политика: планировщик** | `FullReplacePlanner` | `prototype/backend/assembly/planner.py` (новый) | `diff` + `commands` — две половины ОДНОЙ политики в одном stateless-классе (Strategy). Generic: `proc_dicts_fn` + `protected_provider` — инъекция (НЕ импортирует assembler/SystemConfig). Валидация ДО stop. | unit с fake `proc_dicts_fn`: protected исключены + порядок stop→cleanup→provision→create→start |
| **App-glue (нормализация)** | `normalize_blueprint` + `build_proc_dicts` | `prototype/backend/assembly/normalize.py` (новый) | `SystemConfig`-defaults → нормализованный blueprint → `assembler.assemble`. **Единственное место app-специфики** сборки. Общий для boot и switch. | unit: defaults применены как в boot A |
| **Исполнение** | `TopologyManager` | `framework/.../topology_manager.py` | исполнить команды ПО ПОРЯДКУ, собрать результаты. **Без snapshot/monitor/configs.** Reporter, не decider. | unit с fake-сидами: порядок вызовов, fail → не коммитит `_current_topology` |
| **Сиды (1 эффект)** | `stop/cleanup/provision/create/start_process_fn` | `framework/.../process_manager_process.py` | каждый — ОДНА мутация состояния PM | unit на каждый |
| **Транзакция** | `PM.apply_topology` | `framework/.../process_manager_process.py` | snapshot → pause → execute → rollback-on-fail → resume; debounce. **Переиспользует существующие `_snapshot_processes`/`_restore_from_snapshot`/`_cleanup_process_resources`.** | integration: инъекция падения на фазе → откат + configs + monitor восстановлены |
| **Владелец рецепта** | `RecipeManager` | `prototype/recipes/manager.py` (есть) | каталог, активный, read(slug), set_active | есть |
| **GUI** | proxy + presenters | `prototype/frontend/...` | тонкий вызов `apply_topology` | qt-smoke |

**Пакет `prototype/backend/assembly/`** — три фокусных файла под «рецепт → живая топология»
(когезия без склейки; решение 2026-06-07: группировка модулем, без фасада — фасад app-привязал
бы и добавил слой при нулевой пользе):
```
assembly/
  normalize.py    normalize_blueprint + build_proc_dicts   (app-glue: SystemConfig-defaults)
  assembler.py    BlueprintAssembler                        (framework-ready)
  planner.py      FullReplacePlanner                        (framework-ready; позже сосед incremental.py)
```
> ⚠️ **Имя `topology/` ЗАНЯТО:** `prototype/backend/topology/` — это каталог YAML-данных
> (base.yaml, inspection_*.yaml, завязан в `app.yaml: base/pipeline`), НЕ Python-пакет. Поэтому
> код кладём в `backend/assembly/`, чтобы не смешивать данные и модули.
Слияние в один класс отвергнуто: `planner` нужен только switch, `assembler`/`normalize` — общие
boot+switch; слияние потянуло бы switch-политику в boot и сломало carve-out.

**Удаляется:** `_build_proc_dicts` + инлайн stop/spawn/rollback в `replace_blueprint`
(обвязка переезжает в `PM.apply_topology`, сборка — в `BlueprintAssembler`).

**Новых компонентов: 2** — `BlueprintAssembler` (сборка) + `FullReplacePlanner` (политика
diff+commands). Оба **stateless** (не «manager», нет lifecycle). Зажигаем спящий
`TopologyManager` + 1 транзакционный метод PM (на существующих хелперах). Новых
**менеджеров с lifecycle: 0**. Политика — один класс-стратегия, а не два loose-замыкания:
diff и commands делят protected-логику и assembler → гарантированно согласованы.

> **КРИТИЧНО — двухфазность (урок Task 7 / commit 5cd23192).**
> `TopologyManager.apply` исполняет команды **плоским циклом по порядку списка**, а корректный
> boot (`_create_processes_from_config`) двухфазен: provision (очереди+SHM) ВСЕХ → start ВСЕХ.
> Если собрать команды как «create+start на процесс по очереди» — `camera_0` стартует до
> регистрации очереди `detector` → кадры в пустоту (тот самый баг). **Решение бесплатное:**
> плоский цикл = порядок списка = порядок исполнения. `commands_fn` раскладывает в **5 гомогенных
> фаз** (`stop` → `cleanup` → `provision` → `create` → `start`), и двухфазность boot
> воспроизводится сама собой. SHM-аллокация привязана к фазе **provision** (вместе с очередью —
> «обеспечить ресурсы связи»), ДО create/start — детерминированно, без гонок. Раскладку по фазам
> делает `FullReplacePlanner.commands` (см. ниже).

---

## Фазы

### Phase 1 — Канонический трансформер (вынос, без изменения поведения)

#### Task 1.1 — `BlueprintAssembler` (stateless сборщик)
**Level:** Senior (TeamLead) · **Файлы:** `multiprocess_prototype/backend/assembly/assembler.py` + `normalize.py` (новый пакет; `topology/` занят данными), `tests/`
**Goal:** Именованный stateless-компонент сборки proc_dict — вынос инлайна `launch.py:238-287` + нормализация из `SystemLauncher.add_process`. **Carve-out-ready:** внутри `assemble` — ТОЛЬКО framework-примитивы (`SystemBlueprint`/`build_configs`/`process`/`merge_managers`/`merge_with_defaults`/`DEFAULT_PROCESS_SCHEMA` — все проверены framework, ревью B.1). App-специфика (per-category defaults из `SystemConfig`) **остаётся снаружи**.
**Steps:**
1. `class BlueprintAssembler` с конструктором `(observability_dict: dict)` и методом `assemble(blueprint_dict) -> dict[str, dict]`. **Без состояния/lifecycle — не «manager».**
2. Тело `assemble` (только framework): `SystemBlueprint.model_validate` → `check()` → `build_configs()` → `process(cfg)` → `merge_managers(observability_dict)` → `merge_with_defaults(DEFAULT_PROCESS_SCHEMA)`.
3. **`_merge_defaults` (per-category, читает `SystemConfig` — `launch.py:118`, app-specific) вызывается СНАРУЖИ** — прототип нормализует blueprint ДО `assemble`. Assembler получает уже смёрженный blueprint dict и НЕ знает про категории/`SystemConfig`. (Ревью B.1: иначе app-логика протечёт во framework при Phase 5.)
4. Невалидно → `raise BlueprintInvalid` (не `sys.exit`).
**Acceptance:**
- [ ] `assemble` чистая (без I/O, без мутаций аргументов; один и тот же вход → один и тот же выход)
- [ ] **`assemble` НЕ импортирует `SystemConfig`/`multiprocess_prototype.*`** — только framework-символы (grep import'ов в assembly.py чист от prototype)
- [ ] **эталон теста = дорога A (boot через `SystemLauncher.add_process`, ВКЛЮЧАЯ `merge_with_defaults`)**, НЕ текущий `_build_proc_dicts` (он уже расходится с A — пропускает defaults)
- [ ] невалид → `BlueprintInvalid`

#### Task 1.2 — boot через `BlueprintAssembler`
**Level:** Middle+ (Developer) · **Файлы:** `launch.py`
**Goal:** `SystemBuilder.build()` нормализует blueprint (`_merge_defaults` снаружи) → `BlueprintAssembler.assemble` (дорога A на единой сборке). boot и switch используют **один и тот же** assembler + одну и ту же нормализацию.
**Acceptance:** - [ ] boot proc_dict идентичен прежнему (diff-тест против дороги A) - [ ] qt-smoke старт

---

### Phase 2 — Зажечь TopologyManager (full-replace, 5 фаз, транзакционно)

#### Task 2.0 — `TopologyManager`: словарь команд + single-purpose сиды (framework)
**Level:** Senior (TeamLead) · **Файлы:** `framework/.../topology_manager.py`, `process_manager_process.py` (сиды), `tests/`
**Goal:** Менеджер умеет 5 типов команд, каждая → отдельный сид с **одной** ответственностью. Менеджер остаётся **чистым исполнителем-репортёром** (без snapshot/monitor/configs — это Task 2.2).
**Steps:**
1. `_execute_command` обрабатывает: `process.stop`, `process.cleanup`, `process.provision`, `process.create`, `process.start`. Каждый зовёт свой сид и возвращает `{cmd, name, success}`.
2. Сиды PM (single responsibility):
   - `stop_process_fn(name)` = `stop_process` — halt (есть).
   - `cleanup_process_fn(name)` = `remove_process` + `release_process_memory` + `del _process_configs[name]` — free (вынос из `_cleanup_process_resources`).
   - `provision_process_fn(name, proc_dict)` = `shared_resources.register_process` + `allocate_shm` (если `memory`) — очередь+SHM.
   - `create_process_fn(name, ...)` = `create_and_register` + `_process_configs[name]=cfg` — instantiate, БЕЗ старта.
   - `start_process_fn(name)` = `start_process` — run.
3. **Перенос SHM-аллокации:** сейчас `process.create` в `_execute_command` (topology_manager.py:152-168) инлайнит `allocate_shm`. **Убрать оттуда** — SHM теперь в `provision`. Иначе дубль аллокации. (Ревью B.3.)
4. `apply`: при наличии хоть одной `success: False` — **НЕ** ставить `_current_topology`; вернуть `{success: False, results, failed_at}`. Покрыть оба пути неуспеха: exception в сиде И `return success:False` без exception (soft-fail). (Откат живых процессов — Task 2.2.)
5. `configure`/`__init__` принимают новые сиды (опциональны — обратная совместимость).
**Acceptance:**
- [ ] unit с fake-сидами: список `[provision A, provision B, create A, create B, start A, start B]` → сиды вызваны строго в этом порядке
- [ ] unit (exception-fail): команда бросила на 2-й из 4 → `apply` = `success: False`, `_current_topology` НЕ изменён
- [ ] unit (**soft-fail**): сид вернул `{success: False}` БЕЗ exception → `apply` = `success: False`, `_current_topology` НЕ изменён (ревью B.6)
- [ ] каждый сид мутирует ровно одну вещь (unit на сид: provision не стартует, create не стартует и **не аллоцирует SHM**, cleanup чистит SHM+registry+cfg)
- [ ] **backward-compat:** вызов `apply` со старым cmd `register_update` → не падает, `success: True` (ревью B.3)
- [ ] вызовы без новых сидов (старая конфигурация) не падают

#### Task 2.1 — `FullReplacePlanner` (политика: diff + commands в одном классе)
**Level:** Senior (TeamLead) · **Файлы:** `multiprocess_prototype/backend/assembly/planner.py` (новый), `tests/`
**Goal:** Один stateless-класс-стратегия — обе половины политики когерентны. **Framework-готов:** вся app-специфика (`SystemConfig`-defaults, нормализация) инъектируется как `proc_dicts_fn`; planner про неё не знает. Strategy: full-replace сегодня, incremental позже = класс-сосед с тем же интерфейсом.
**Steps:**
1. `class FullReplacePlanner` с конструктором `(proc_dicts_fn: Callable[[dict], dict], protected_provider: Callable[[], set[str]])`. **Stateless, не «manager», без импорта `BlueprintAssembler`/`SystemConfig` — оба контракта инъекция.** (`proc_dicts_fn` = «нормализуй+собери» = `assembler.assemble ∘ normalize`, его поставляет прототип.)
2. Метод `diff(current, desired) -> dict`: помечает все non-protected (`protected_provider()`) как «снести+пересоздать»; protected исключены.
3. Метод `commands(diff, desired) -> list[dict]`:
   - собрать proc_dicts через `self._proc_dicts_fn(desired)` — **валидация ДО эмиссии команд** (невалид → `BlueprintInvalid`, ни одного stop не послано);
   - вернуть список по фазам: **A** `process.stop`×old → **B** `process.cleanup`×old → **C** `process.provision`×new → **D** `process.create`×new → **E** `process.start`×new.
4. В менеджер передаётся **связанными методами**: `configure(diff_fn=planner.diff, commands_fn=planner.commands)` — framework-контракт (два callable) не меняется, churn = 0.
**Acceptance:**
- [ ] unit: `diff` исключает protected; набор процессов = текущий replace_blueprint
- [ ] unit: `commands` даёт порядок ровно `stop → cleanup → provision → create → start` (паритет двухфазности boot)
- [ ] unit: невалидный blueprint → `BlueprintInvalid` ДО любой stop-команды
- [ ] diff и commands согласованы: для одного diff команды покрывают ровно его набор (нет «заменить X», но команды без X)

#### Task 2.2 — `PM.apply_topology`: транзакция + конфигурация менеджера (framework)
**Level:** Senior (TeamLead) · **Файлы:** `process_manager_process.py`, `orchestrator.py`, `launch.py`
**Goal:** Транзакционная обёртка — **единственный** владелец побочных эффектов и отката. Переиспользует существующий `_restore_from_snapshot` + monitor-pause из дороги B. Здесь же оживает менеджер.
**Steps:**
1. `apply_topology(blueprint)`:
   - in-flight guard + cooldown `replace_debounce_s` (**переезд debounce из дороги B — backend, не обойти по IPC**);
   - `snapshot = _snapshot_processes()` — **метод СОЗДАТЬ** (вынос инлайна `old_configs=copy.deepcopy(to_replace)` из `replace_blueprint:784`; `_restore_from_snapshot` уже есть). (Ревью B.6.)
   - `_process_monitor.pause()`;
   - `result = self._topology_manager.apply(blueprint)`;
   - `if not result.success: _restore_from_snapshot(snapshot)` → вернуть `{success: False, rolled_back: True}`;
   - `finally: _process_monitor.resume()`.
2. `_setup_topology_manager` пробрасывает все 5 сидов (Task 2.0).
3. `ProcessManagerProcessApp`: `orchestrator_config["sys_config"]=sys_config.model_dump()`; после `initialize` собрать цепочку: `assembler=BlueprintAssembler(obs_dict)` → `build_proc_dicts = lambda bp: assembler.assemble(normalize_blueprint(bp, sys_config))` → `planner=FullReplacePlanner(proc_dicts_fn=build_proc_dicts, protected_provider=self._get_protected_names)` → `self._topology_manager.configure(diff_fn=planner.diff, commands_fn=planner.commands)`. (Та же `build_proc_dicts`, что в boot Task 1.2 — одна сборка.)
4. Команда `topology.apply` маршрутизируется в `PM.apply_topology` (а не напрямую в менеджер — чтобы транзакция/debounce не обходились).
**Acceptance:**
- [ ] integration: инъекция падения на фазе `create` 3-го процесса → первые 2 откатаны, старый рецепт восстановлен (процессы + `_process_configs` + monitor resumed)
- [ ] integration: повтор-клик во время apply коалесится (in-flight guard)
- [ ] `topology.apply(blueprint)` поднимает процессы с defaults+obs (паритет boot) — live qt-smoke переключение, FPS > 0 в обе стороны
- [ ] SHM не течёт: после N свопов число SHM-сегментов стабильно (cleanup-фаза работает)

#### Task 2.3 — Свернуть ad-hoc дорогу B (через переходный алиас)
**Level:** Middle+ (Developer) · **Файлы:** PM-процесс
**Goal:** Удалить `_build_proc_dicts` и инлайн-обвязку `replace_blueprint`; команду `blueprint.replace` **на одну фазу** сделать тонким алиасом → `PM.apply_topology`. Удаление алиаса — после перехода GUI (Task 4.1).
**Steps:** 1. `_build_proc_dicts` + инлайн stop/spawn/rollback удалить. 2. `blueprint.replace` → `self.apply_topology(blueprint)`. 3. После Task 4.1 — алиас и команду удалить.
**Acceptance:** - [ ] `grep _build_proc_dicts` пуст - [ ] обвязка (rollback/cleanup/monitor/debounce) живёт ТОЛЬКО в `apply_topology` (нет дублей) - [ ] sentrux check_rules зелёный - [ ] GUI «Перезапустить» работает через алиас

---

### Phase 3 — RecipeManager как единый владелец активного рецепта

#### Task 3.1 — Активный рецепт в RecipeManager + развязка «активация ≠ применение» (backend)
**Level:** Middle+ (Developer) · **Файлы:** `recipes/manager.py` (переиспользуем), `orchestrator.py`
**Goal:** Дефолт из манифеста (`app.pipeline`) ставится через `RecipeManager.set_active`; backend — источник истины.
**Граница (ревью-уточнение):** сейчас `RecipeManager.set_active(slug)` → `load()` → движок **применяет дельты к config** (manager.py:234-255, 90-113) — активация тащит скрытый side-effect. В чистой архитектуре это **две разные операции**:
- **активировать** = пометить указатель `active` (только bookkeeping + state.recipes.active);
- **применить** = `apply_topology(RecipeManager.read(slug))` (построить топологию, поднять процессы).
**Steps:** 1. `set_active` свести к указателю (без `load`-применения к config). 2. Применение топологии — явный вызов `apply_topology`. 3. RecipeManager остаётся «про файлы»: НЕ знает про процессы/proc_dicts/топологию.
**Acceptance:**
- [ ] активный рецепт читается из RecipeManager, не из 3 мест
- [ ] `set_active` не имеет config/топология-side-effect (юнит: указатель сменился, процессы не тронуты)
- [ ] применение идёт только через `apply_topology`

---

### Phase 4 — Тонкий GUI

#### Task 4.1 — proxy: `apply_topology`
**Level:** Middle+ (Developer) · **Файлы:** `frontend/bridge/process_manager_proxy.py`
**Goal:** `apply_topology(source: str|dict, on_result=None)` → cmd `topology.apply` (slug резолвится backend через RecipeManager, либо передаём blueprint). Заменяет `replace_blueprint*`. **Тонкий — без своего debounce** (он на backend, Task 2.2).
**Acceptance:** - [ ] proxy не содержит логики сборки/коалесинга - [ ] старые `replace_blueprint*` сняты, алиас (Task 2.3) удалён

#### Task 4.2 — Свести 3 точки входа GUI
**Level:** Middle+ (Developer) · **Файлы:** `recipes/presenter.py`, `pipeline/presenter.py`
**Goal:** Recipes «Загрузить» (slug), Pipeline «Запустить»/«Перезапустить» (in-memory blueprint) → один путь `apply_topology`. Коалесинг обеспечивает backend.
**Acceptance:** - [ ] нет «тасования» - [ ] qt-smoke 3 кнопки (повтор-клики коалесятся backend-guard'ом)

---

### Phase 5 — Carve-out во фреймворк (forcing-function, ПОСЛЕ унификации)

Решение владельца (2026-06-07): выносим **устоявшийся** код, не «движущуюся мишень» — только после того, как boot==switch отлажены в прототипе (Phase 1-4). Цель: оба компонента — универсальные framework-модули.

- **`BlueprintAssembler` → framework**: уже спроектирован carve-out-ready (Task 1.1: конструктор на dict, без `SystemConfig`). Переезд = перенос файла + тесты; прототип оставляет только склейку `SystemConfig → defaults_dict/observability_dict`.
- **`RecipeManager` → framework**: универсальный модуль каталога рецептов. Предусловие — Task 3.1 (развязка «активация ≠ применение») снимает app-связанность через config-side-effect. После развязки бо́льшая часть = generic (файлы + указатель, делегация в `RecipeEngine` который уже во framework). **Блокер carve-out (ревью B.4):** метод `duplicate` (manager.py:204-215) содержит (а) прямой `import multiprocess_prototype.recipes.yaml_io` — обратная зависимость framework→prototype, и (б) знание формата v3 vs legacy (`meta.name` vs top-level `name`). При переезде: `duplicate` либо остаётся в prototype как override-подкласс, либо формат/yaml_io выносятся в инъектируемый callback. Зафиксировать ДО Phase 5.
- `FullReplacePlanner` → framework как generic-стратегия (full-replace универсален); app оставляет только `protected_provider` + маппинг defaults. Incremental-стратегия — класс-сосед.
- **Incremental `diff_fn`** (память `project_pipeline_live_incremental_vision`) — тот же `TopologyManager`, умнее diff. Full-replace → incremental без смены архитектуры. **Долг:** `_current_topology` хранит raw blueprint, а commands работают с proc_dicts — для incremental diff согласовать представление (для full-replace неважно).
- Чистка: `wires` editor-only; свернуть Pydantic-дуализм; `_restore_plugin_configs` → явный `PluginRegistry.config_for`.

---

## Вне scope

- **Блокер кадров `output_frames`** (§5/§7.4 анализа) — отдельный P0 про SHM lifetime на **boot-гонке**. Унификация switch убирает hot-swap-рассинхрон; boot-гонку лечить отдельно.
- **Wire-cleanup долг:** `_active_wires` не чистится при замене (существующий баг дороги B, ревью Дыра 8). Дорога C наследует — отдельный мелкий таск, не блокер унификации.

## Риски

| Риск | Митигация |
|------|-----------|
| sys_config не пиклится через spawn | `model_dump()` → чистый dict (Dict at Boundary) |
| **Регрессия кадров: дорога C однофазна** | 5 гомогенных фаз `stop→cleanup→provision→create→start` (Task 2.1) + плоский цикл сохраняет порядок; unit на порядок команд |
| **Дорога C поднимает мёртвые процессы** | `provision` (очередь+SHM) и `start` — отдельные фазы; acceptance Task 2.2 паритет boot, live FPS>0 |
| **Нет отката на C / частично применённая топология** | транзакция `PM.apply_topology` (Task 2.2): `_current_topology` коммитится только при полном успехе; падение → `_restore_from_snapshot`; integration-тест на инъекцию падения |
| **Утечка SHM при свопе** | фаза `cleanup` (`release_process_memory`) — отдельный сид; acceptance «N свопов → SHM стабильна» |
| **`_process_configs` рассинхрон** | мутируют только сиды `create` (set) и `cleanup` (del); rollback восстанавливает из snapshot |
| **Гонка ProcessMonitor во время свопа** | pause/resume в обёртке `PM.apply_topology` (Task 2.2), как в дороге B |
| **Debounce обходится по IPC** | guard на backend в `apply_topology`, не в GUI-proxy (Task 2.2/4.1) |
| protected рестартятся | `diff_fn` исключает protected (как `_get_protected_names`) |
| boot proc_dict разъехался | эталон диф-теста = дорога A с `merge_with_defaults` (Task 1.1) |
| GUI ломается при удалении `replace_blueprint` | Task 2.3 — переходный алиас, удаление только после Task 4.1 |

## Приёмка (общая)

- [ ] Одна дорога: boot и switch зовут `BlueprintAssembler.assemble`; switch идёт через `TopologyManager` внутри транзакции `PM.apply_topology`.
- [ ] `grep _build_proc_dicts` пуст; `topology.apply` живой (не `"not configured"`); обвязка не дублируется.
- [ ] Откат проверен: инъекция падения на любой фазе → предыдущее состояние восстановлено (процессы + configs + monitor).
- [ ] SHM не течёт после серии свопов; protected сохранены; framework не импортирует prototype (sentrux check_rules); health не ниже baseline.
- [ ] qt-smoke: старт + переключение (Recipes «Загрузить», Pipeline «Запустить»/«Перезапустить»), FPS>0 в обе стороны.
