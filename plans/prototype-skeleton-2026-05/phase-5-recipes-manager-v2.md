# Phase 5 — Recipe Manager + replace_blueprint

> **Master plan**: [plan.md](plan.md)
> **Branch**: `feat/recipes-manager-v2`
> **Дней**: 7-10
> **Зависимости**: Phase 2 (paths), Phase 3 (services), Phase 4 (displays)
> **Refs trailer**: `Refs: plans/prototype-skeleton-2026-05/phase-5-recipes-manager-v2.md, plans/prototype-skeleton-2026-05/plan.md`

## Цель

Рецепт = полноценный blueprint. RecipesTab переписан с slot-based на менеджер blueprints. Переключение активного рецепта вызывает `ProcessManager.replace_blueprint()` (рабочие процессы перезапускаются, GUI и orchestrator живут).

## Реальная фундация

- `RecipeEngine` — **уже в framework** (`state_store_module/recipes/recipe_engine.py`, 369 строк). Используем существующий API.
- `SystemBlueprint` (Phases 0-2 done в config_driven_arch) — валидируемый yaml.
- `ProcessManagerProcess` — есть `stop/restart` для одного процесса, **нет** `replace_blueprint`. **Нужен новый метод**.
- Текущий `RecipesPresenter` — slot-based (8 жёстких слотов, recipe = topology snapshot). Полностью переписать.

## Структура нового рецепта (`multiprocess_prototype/recipes/<slug>.yaml`)

```yaml
version: 2
name: cup_inspection
description: Контроль чашек на конвейере
created: 2026-05-24
modified: 2026-05-24
blueprint:                  # стандартный SystemBlueprint (framework) — никаких новых полей
  processes: [...]
  wires: [...]
active_services: [webcam_camera]      # application-секция, ВНЕ SystemBlueprint
display_bindings:                     # application-секция, ВНЕ SystemBlueprint
  - source: merge_proc.render_overlay.out
    display: main_output
  - source: capture_proc.resize.out
    display: debug_input
```

**Важно**: `active_services` и `display_bindings` — Inspector-специфичные секции, существующие **рядом** с blueprint, а не внутри него. SystemBlueprint остаётся generic-контрактом framework (processes + wires + name + description). ADR в `multiprocess_framework/DECISIONS.md`: «SystemBlueprint остаётся generic; application-расширения рецепта живут параллельными секциями yaml».

## Миграция со старого формата

- v1: `recipe_N.yaml` с `{name, description, topology}` (8 жёстких слотов).
- v2: `recipe_<slug>.yaml` с `{version, name, description, blueprint, active_services, display_bindings}`.
- **Новая** `multiprocess_prototype/recipes/migrations/format_v1_to_v2.py` (пишем с нуля, ~100 строк) — конвертирует topology dict в blueprint + извлекает display_bindings из старых wires `*.display.*` + active_services из используемых сервисов. **Внимание**: миграция `v1_to_v2.py` из backup — это **другая** миграция (внутренняя структура рецепта `processing_blocks → nodes`), не путать.
- Регистрируется в `RecipeEngine` через стандартный механизм (existing API).
- При первом запуске после Phase 5 — миграция всех `data/recipes/recipe_*.yaml` в `recipes/<slug>.yaml`.

## Новое

- `multiprocess_prototype/recipes/manager.py` — `RecipeManager` (тонкая application-обёртка над framework `RecipeEngine`):
  - `load/save/list/duplicate/delete/set_active`.
  - Persist в `recipes/<slug>.yaml`. Активный = `state.recipes.active` (StateProxy).
- `multiprocess_prototype/recipes/migrations/format_v1_to_v2.py` — новая миграция формата (см. выше).
- `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py` — **новый метод** `replace_blueprint(new_blueprint: SystemBlueprint)`:
  - Список процессов, помеченных `protected=true` — НЕ трогаем.
  - Список остальных — `stop` + cleanup SHM-сегментов + recreate из нового blueprint + start.
  - Rollback при partial failure (если новый процесс не стартовал — вернуть старый blueprint).
- `multiprocess_prototype/backend/state/adapters/recipe_adapter.py` — из backup, адаптирован.
- `multiprocess_prototype/registers/manager.py` — расширить `build_rm_from_topology()`:
  - Базовый слой: всегда подгружать из `multiprocess_prototype/registers/*.yaml` (если есть).
  - Active-слой: регистры плагинов/сервисов из активного рецепта.
- Расширить StateStore bootstrap: `state.recipes.*` (список + active).
- ADR в `multiprocess_framework/DECISIONS.md`: «Recipe = SystemBlueprint v2, replace_blueprint в ProcessManager».

## RecipesTab

- Переписать `tabs/recipes/tab.py` и presenter с slot-based на менеджер:
  - Левая колонка: список рецептов из `recipes/*.yaml` (динамический, не 8 фиксированных).
  - Правая панель: метаданные + сводка blueprint (процессы, плагины, дисплеи, активные сервисы) + список регистров.
  - Кнопки: «Создать новый» (пустой шаблон), «Дублировать», «Удалить», «Сделать активным», «Открыть в Pipeline».
- При смене активного → `ProcessManager.replace_blueprint(new)` → PipelineTab перерисовывает граф.

## Acceptance

- Старые `recipe_N.yaml` смигрированы в новый формат при первом запуске.
- Создали 2 рецепта (`cup_inspection`, `bottle_inspection`) с разными цепочками; переключение перезапускает worker-процессы (GUI и orchestrator живые); регистры перестраиваются; PipelineTab показывает новый граф.
- 30-40 unit-тестов: RecipeManager CRUD, миграция v1→v2, replace_blueprint (включая partial failure rollback), state adapter.

---

## Задачи

> Checkboxes: `- [ ]` → `- [x] (commit hash)` после завершения задачи.
> Порядок: 5.1 → 5.2 → [5.3 + 5.4 параллельно] → 5.5 → [5.6 + 5.7 параллельно] → 5.8
> Максимум 2 параллельных агента без worktree.

---

### Task 5.1 — [VERTICAL SLICE] Миграция формата v1→v2 + RecipeManager CRUD

- [x] Task 5.1 (798e3ab5)

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Создать `RecipeManager` (обёртку над `RecipeEngine`) и миграцию формата v1→v2 — минимальный E2E срез: старый `recipe_0.yaml` читается, мигрируется, сохраняется в новый `recipes/cup_inspection.yaml`, `RecipeManager.list()` его видит.
**Context:** Это первый работающий слой Phase 5. После этой задачи есть осязаемый результат: старые рецепты превращаются в новый формат и доступны через `RecipeManager`. Все остальные задачи зависят от этого слоя — без него нет ни replace_blueprint, ни нового UI.

**Files:**
- `multiprocess_prototype/recipes/__init__.py` — создать (пустой пакет)
- `multiprocess_prototype/recipes/manager.py` — создать: `RecipeManager`
- `multiprocess_prototype/recipes/migrations/__init__.py` — создать
- `multiprocess_prototype/recipes/migrations/format_v1_to_v2.py` — создать: функция миграции
- `multiprocess_prototype/recipes/tests/__init__.py` — создать
- `multiprocess_prototype/recipes/tests/test_recipe_manager.py` — создать: 10-12 unit-тестов

**Steps:**
1. Создать `multiprocess_prototype/recipes/migrations/format_v1_to_v2.py`:
   - Функция `migrate_v1_to_v2(data: dict) -> dict` — принимает старый dict рецепта v1 (ключи: `name`, `description`, `topology`), возвращает v2-dict (ключи: `version=2`, `name`, `description`, `blueprint`, `active_services`, `display_bindings`).
   - Конвертация `topology` → `blueprint`: topology dict (ключи `processes`, `wires`) становится `blueprint.processes`, `blueprint.wires`.
   - Извлечение `display_bindings`: из старых wire-записей с target вида `*.display.*` или `display_*` — формировать список `{source, display}`.
   - Извлечение `active_services`: из `processes[*].plugins` — собирать плагины с category `service` (если plugin_registry не доступен — пустой список, добавить TODO-комментарий).
   - Функция `is_v1_recipe(data: dict) -> bool` — True если нет ключа `version` или `version < 2`.
   - Не выбрасывать исключения при отсутствии опциональных полей — graceful fallback.
2. Создать `multiprocess_prototype/recipes/manager.py` — класс `RecipeManager`:
   - `__init__(self, engine: RecipeEngine, state_proxy: Any | None = None, logger: Any | None = None)` — принимает готовый `RecipeEngine` (не создаёт сам), опциональный `StateProxy` и logger.
   - `list() -> list[str]` — делегирует `engine.list()`.
   - `load(slug: str, remap: dict | None = None) -> list` — делегирует `engine.load(slug, remap)`, обновляет `state.recipes.active = slug` через `state_proxy.set()` если proxy доступен.
   - `save(slug: str, paths: list[str] | None = None) -> None` — делегирует `engine.save(slug, paths)`.
   - `delete(slug: str) -> bool` — делегирует `engine.delete(slug)`, сбрасывает `state.recipes.active = None` если удалён активный.
   - `duplicate(source_slug: str, new_slug: str) -> bool` — читает YAML `engine.recipes_dir / f"{source_slug}.yaml"`, записывает под новым именем с обновлённым `meta.name`. Возвращает False если source не найден или new_slug уже занят.
   - `set_active(slug: str) -> bool` — вызывает `load(slug)` + уведомляет `state_proxy`. Возвращает False если рецепт не найден.
   - `get_active() -> str | None` — делегирует `engine.get_active()`.
   - `is_dirty() -> bool` — делегирует `engine.is_dirty()`.
   - Логирование через `self._log_info/warning/error` с паттерном `if self._logger: self._logger.log_info(...)` (аналогично `RecipeAdapter` из Phase 0).
3. Создать `multiprocess_prototype/recipes/tests/test_recipe_manager.py`:
   - Использовать `tmp_path` pytest fixture для изоляции файлов.
   - Тест `test_list_empty` — новый менеджер на пустой директории → `list()` возвращает `[]`.
   - Тест `test_save_and_list` — `save("cup_inspection")` → `list()` содержит `"cup_inspection"`.
   - Тест `test_load_updates_active` — после `load("cup_inspection")` → `get_active() == "cup_inspection"`.
   - Тест `test_delete_active_resets_state` — удалить активный → `get_active() is None`.
   - Тест `test_duplicate` — `duplicate("cup", "bottle")` → `list()` содержит оба.
   - Тест `test_duplicate_fails_if_source_missing` — source не существует → `False`.
   - Тест `test_duplicate_fails_if_target_exists` — target уже есть → `False`.
   - Тест `test_state_proxy_updated_on_load` — mock StateProxy, проверить что `set("recipes.active", "cup_inspection")` вызывается.
   - Тест `test_migrate_v1_to_v2_basic` — dict с topology → v2 dict с blueprint.
   - Тест `test_migrate_v1_with_display_wires` — wire с target `*.display.*` попадает в `display_bindings`.
   - Тест `test_is_v1_recipe_true` — dict без `version` → True.
   - Тест `test_is_v1_recipe_false` — dict с `version: 2` → False.

**Acceptance criteria:**
- [ ] `pytest multiprocess_prototype/recipes/tests/` — все 12 тестов зелёные
- [ ] `RecipeEngine` инициализируется с `migration_fn=migrate_v1_to_v2`, `migration_check_fn=is_v1_recipe` — миграция срабатывает при `engine.load()` legacy-файла
- [ ] `RecipeManager.duplicate("a", "b")` → файл `b.yaml` содержит корректный YAML с `meta.name == "b"`
- [ ] Логи через `_logger.log_info` при каждой мутирующей операции

**Out of scope:**
- Интеграция с `ProcessManager.replace_blueprint` (Task 5.2)
- Обновление `build_initial_state` (Task 5.3)
- GUI (Tasks 5.6-5.7)

**Edge cases:**
- `duplicate` с пустым source_slug → вернуть False без исключения
- `save()` при отсутствии `recipes/` директории — `RecipeEngine.__init__` создаёт её автоматически через `mkdir(parents=True, exist_ok=True)`
- `is_v1_recipe` для None или не-dict → False (без исключений)

**Dependencies:** Phase 0 (RecipeEngine в framework, StateAdapterBase)
**Module contract:** new-lite (новый одиночный публичный модуль `recipes/manager.py`)

---

### Task 5.2 — replace_blueprint в ProcessManagerProcess (framework)

- [x] Task 5.2 (498d323f)

**Level:** Senior+ (Opus, extended thinking)
**Assignee:** teamlead
**Goal:** Реализовать `ProcessManagerProcess.replace_blueprint(new_blueprint: SystemBlueprint)` с snapshot+rollback, не трогая protected процессы, регистрируя команду `blueprint.replace` в CommandManager.
**Context:** Это самый критичный и рискованный кусок Phase 5. `replace_blueprint` — новый сложный код в framework с реальными OS-процессами, cleanup SHM, rollback при partial failure. Ошибка здесь означает зависание или потерю данных. Требует teamlead + отдельная задача тестирования (Task 5.4).

**Files:**
- `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py` — добавить метод `replace_blueprint` и вспомогательные `_get_protected_names`, `_stop_and_cleanup_process`, `_restore_from_snapshot`
- `multiprocess_framework/modules/process_manager_module/interfaces.py` — добавить `replace_blueprint` в `IProcessManagerProcess`

**Steps:**
1. Добавить в `IProcessManagerProcess` (interfaces.py):
   ```python
   @abstractmethod
   def replace_blueprint(self, new_blueprint: dict) -> dict:
       """Заменить blueprint: остановить незащищённые процессы, поднять новые.

       Args:
           new_blueprint: dict-представление SystemBlueprint (Dict at Boundary).
                         Ключи: processes (list[dict]), wires (list[dict]).

       Returns:
           dict с ключами: success (bool), replaced (list[str]),
           skipped_protected (list[str]), error (str|None),
           rolled_back (bool).
       """
   ```
   **Важно**: принимать `dict`, не `SystemBlueprint` — Dict at Boundary (правило проекта).

2. В `ProcessManagerProcess` добавить вспомогательный метод `_get_protected_names() -> set[str]`:
   - Читать из `self._process_configs` — ключ `"protected": True` в конфиге процесса.
   - Возвращать множество имён защищённых процессов.
   - Всегда добавлять в protected: `self.name` (ProcessManager сам себя не перезапускает).

3. Добавить `_stop_and_cleanup_process(name: str, timeout: float) -> bool`:
   - Вызвать `self.stop_process(name)` с timeout из конфига.
   - После остановки: вызвать `self._process_registry.remove_process(name)`.
   - Cleanup SHM: если `self.shared_resources` и `memory_manager` доступны — попытаться освободить SHM-сегменты, связанные с процессом (через `mm.release_process_memory(name)` если метод существует, иначе логировать предупреждение и продолжать).
   - Возвращает `True` если остановлен успешно, `False` при ошибке (не бросать исключений).
   - Логировать через `self._log_info/error` (ObservableMixin).

4. Добавить `_restore_from_snapshot(snapshot_configs: dict[str, dict]) -> None`:
   - Принимает dict `{process_name: proc_config}` — snapshot конфигов до замены.
   - Для каждой записи: `self._process_registry.remove_process(name)` + `self._process_registry.create_and_register(...)` + `process.start()`.
   - При ошибке создания/старта — логировать через `self._log_error` и продолжать (не прерывать rollback).
   - После восстановления: `self._process_configs` обновляется из snapshot.

5. Реализовать `replace_blueprint(new_blueprint: dict) -> dict`:
   ```
   1. Извлечь список процессов из new_blueprint["processes"] (dict-список).
   2. Вычислить protected = _get_protected_names().
   3. Вычислить to_replace = {name: cfg for name, cfg in _process_configs if name not in protected}.
   4. Сделать snapshot: old_configs = copy.deepcopy(to_replace).
   5. Pause ProcessMonitor (monitor.stop() или аналог).
   6. Для каждого имени в to_replace: _stop_and_cleanup_process(name).
      Если хоть один вернул False → запустить _restore_from_snapshot(old_configs),
      вернуть {"success": False, "rolled_back": True, "error": "..."}.
   7. Для каждого нового процесса из new_blueprint (не в protected):
      - Зарегистрировать через shared_resources.register_process().
      - create_and_register() + start().
      - Если start упал → rollback (шаг 6 логика).
   8. Обновить self._process_configs для новых процессов.
   9. Resume ProcessMonitor.
   10. Логировать результат (сколько остановлено, сколько запущено, protected пропущены).
   11. Вернуть {"success": True, "replaced": [...], "skipped_protected": [...], "rolled_back": False}.
   ```

6. Зарегистрировать команду в `_register_builtin_commands`:
   ```python
   "blueprint.replace": (self._cmd_blueprint_replace, "Заменить blueprint (горячая замена процессов)"),
   ```
   Где `_cmd_blueprint_replace(data=None, **kwargs) -> dict`:
   - `args = _merge_cmd_args(data, kwargs)`.
   - `new_blueprint = args.get("blueprint")`.
   - Если нет → `{"error": "blueprint required"}`.
   - Вернуть `self.replace_blueprint(new_blueprint)`.

7. Логирование через `self._log_info/error/warning` везде (ObservableMixin уже наследуется).
   НЕ использовать `print()` или `logging.getLogger()` напрямую.

**Acceptance criteria:**
- [ ] `isinstance(pm, IProcessManagerProcess)` — `replace_blueprint` присутствует в интерфейсе
- [ ] Вызов `replace_blueprint({})` с пустым blueprint → `{"success": True, "replaced": [], ...}` (нечего заменять)
- [ ] Protected процессы (с `"protected": True` в конфиге) не останавливаются при replace
- [ ] При падении одного нового процесса → `rolled_back: True`, старые процессы восстановлены
- [ ] `_process_configs` после успешного replace содержит только конфиги из нового blueprint + protected

**Out of scope:**
- Integration-тесты с реальными OS-процессами (Task 5.4)
- Интеграция с RecipeManager (Task 5.5)
- GUI (Tasks 5.6-5.7)
- Cleanup SHM ring_buffer специфичных сегментов (только базовый `release_process_memory` если доступен)

**Edge cases:**
- `new_blueprint` без ключа `"processes"` → трактовать как пустой список процессов, не бросать KeyError
- ProcessMonitor уже остановлен (при повторном вызове) → не падать при повторном `stop()`
- Timeout превышен при stop → логировать warning, продолжать rollback (не зависать)
- `self.shared_resources is None` → пропустить SHM cleanup, продолжить

**Dependencies:** Task 5.1 (независима по коду, но логически после понимания формата blueprint)
**Module contract:** public-api-change (изменяется `interfaces.py` и реализация `ProcessManagerProcess`)

---

### Task 5.3 — State bootstrap + RegistersManager двухслойный

- [x] Task 5.3 (01e110f7)

**Level:** Middle (Sonnet, normal thinking)
**Assignee:** developer
**Goal:** Расширить `build_initial_state` для ветки `state.recipes.available` (список slug'ов из `recipes/` директории) и расширить `build_rm_from_topology` двухслойным подходом: base layer (YAML из `registers/*.yaml`) + active layer (из активного рецепта).
**Context:** State bootstrap уже содержит `STATE_RECIPES: {"active": None, "available": []}` — нужно наполнять `available` реальными данными. `build_rm_from_topology` сейчас берёт регистры только из topology; нужен базовый слой из YAML-файлов для дефолтных настроек.

**Files:**
- `multiprocess_prototype/backend/state/bootstrap.py` — расширить `build_initial_state`
- `multiprocess_prototype/registers/manager.py` — расширить `build_rm_from_topology`
- `multiprocess_prototype/backend/state/tests/test_bootstrap.py` — добавить тесты (или создать если нет)

**Steps:**
1. В `build_initial_state` добавить параметр `recipes_dir: Path | None = None`:
   - Если `recipes_dir` передан и существует → `available = sorted([p.stem for p in recipes_dir.glob("*.yaml")])`.
   - Иначе → `available = []`.
   - Обновить возвращаемый dict: `STATE_RECIPES: {"active": None, "available": available}`.
   - Сохранить обратную совместимость: параметр опциональный, `None` → прежнее поведение.

2. В `build_rm_from_topology` добавить параметр `base_registers_dir: Path | None = None`:
   - Если `base_registers_dir` передан → сканировать `*.yaml` файлы в директории.
   - Каждый YAML читается и добавляется как базовый слой регистров (имя файла без `.yaml` = имя регистра).
   - Active-слой (из topology) перекрывает базовый (одинаковые ключи → topology wins).
   - Использовать `yaml.safe_load` для чтения. При ошибке парсинга → `_log_warning` + пропустить файл.
   - Параметр `plugin_registry` остаётся, `base_registers_dir` добавляется как keyword-only.

3. Тесты в `test_bootstrap.py`:
   - `test_build_initial_state_recipes_available` — передать tmp_path с двумя yaml-файлами → `available` содержит оба slug'а.
   - `test_build_initial_state_recipes_empty_dir` — пустая директория → `available == []`.
   - `test_build_initial_state_no_recipes_dir` — `recipes_dir=None` → `available == []`.
   - `test_build_rm_base_layer` — base_registers_dir с одним yaml → регистр из него попадает в менеджер.
   - `test_build_rm_active_overrides_base` — base YAML + topology с тем же именем → topology wins.

**Acceptance criteria:**
- [ ] `pytest multiprocess_prototype/backend/state/tests/test_bootstrap.py` — все новые тесты зелёные
- [ ] `build_initial_state(topology, sys_config, recipes_dir=Path("recipes/"))` — в `state["recipes"]["available"]` появляются slug'и из директории
- [ ] `build_rm_from_topology(topology, base_registers_dir=Path("registers/"))` — базовые регистры из YAML загружены, перекрываются topology

**Out of scope:**
- GUI обновления
- Интеграция с RecipeManager или replace_blueprint

**Edge cases:**
- `recipes_dir` указан, но не существует → `available == []` (без FileNotFoundError)
- `base_registers_dir` содержит невалидный YAML → пропустить с предупреждением
- Пересечение имён: base YAML и topology имеют регистр с одинаковым именем → topology wins (не суммировать поля, а заменять целиком)

**Dependencies:** Task 5.1
**Module contract:** impl-only (нет изменений в `__init__.py` или `interfaces.py`)

---

### Task 5.4 — Integration-тесты replace_blueprint (15-20 тестов)

- [x] Task 5.4 (ee704141)

**Level:** Senior (Opus, normal thinking)
**Assignee:** teamlead
**Goal:** Написать 15-20 integration-тестов для `replace_blueprint`, покрывающих happy path, partial failure rollback, protected-процессы, пустой blueprint, SHM cleanup.
**Context:** `replace_blueprint` — новый сложный код с OS-процессами. Без серьёзного тестового покрытия это замина замедленного действия. Тесты используют mock ProcessRegistry и mock процессы (не реальные OS-процессы) чтобы быть быстрыми и детерминированными.

**Files:**
- `multiprocess_framework/modules/process_manager_module/tests/test_replace_blueprint.py` — создать: 15-20 тестов

**Steps:**
1. Создать `MockProcess` (dataclass или простой класс): атрибуты `name`, `_alive: bool`, методы `start()`, `is_alive() -> bool`, `pid`. `start()` устанавливает `_alive = True` (или может бросить исключение — для тестов отказа).

2. Создать `MockProcessRegistry`: хранит dict `{name: MockProcess}`, реализует `create_and_register`, `get_process_by_name`, `remove_process`, `stop_one`. Метод `stop_one` устанавливает `process._alive = False`.

3. Создать `MockSharedResources`: опциональный `memory_manager` с методом `release_process_memory`.

4. Написать фабрику `make_pm(process_configs: dict) -> ProcessManagerProcess`:
   - Создать минимальный `ProcessManagerProcess` без реального запуска.
   - Внедрить `MockProcessRegistry` и `MockSharedResources`.
   - Заполнить `_process_configs` из аргумента.
   - Не вызывать `initialize()` — только `_create_components()` с mock'ами.

5. Тесты:
   - `test_replace_empty_blueprint_success` — пустой новый blueprint, нет незащищённых процессов → `success=True, replaced=[]`.
   - `test_replace_one_process` — 1 незащищённый процесс, новый blueprint с другим процессом → старый остановлен, новый запущен.
   - `test_replace_skips_protected` — процесс с `"protected": True` → не останавливается при replace.
   - `test_replace_self_is_always_protected` — `ProcessManager` сам себя всегда в protected, даже без флага.
   - `test_replace_multiple_processes` — 3 незащищённых, replace с 2 новыми → 3 остановлены, 2 запущены.
   - `test_rollback_on_stop_failure` — `stop_one` возвращает False для одного → `rolled_back=True`, старые процессы восстановлены.
   - `test_rollback_on_start_failure` — новый процесс не может стартовать (MockProcess.start бросает) → `rolled_back=True`.
   - `test_rollback_restores_process_configs` — после rollback `_process_configs` равен snapshot до replace.
   - `test_no_rollback_on_success` — успешный replace → `rolled_back=False`.
   - `test_protected_names_includes_self` — `_get_protected_names()` всегда содержит имя PM.
   - `test_protected_flag_from_config` — конфиг с `"protected": True` → имя в `_get_protected_names()`.
   - `test_replace_updates_process_configs` — после успешного replace `_process_configs` содержит новые конфиги.
   - `test_shm_cleanup_called` — mock memory_manager, проверить что `release_process_memory` вызывается для остановленных процессов.
   - `test_shm_cleanup_not_required` — `shared_resources is None` → replace завершается без ошибки.
   - `test_cmd_blueprint_replace_registered` — `command_manager.get_commands()` содержит `"blueprint.replace"`.
   - `test_cmd_blueprint_replace_no_blueprint_arg` — вызов команды без `blueprint` → `{"error": "blueprint required"}`.
   - `test_replace_logs_protected_skipped` — проверить что логируется предупреждение о пропущенных protected (mock logger).
   - `test_replace_empty_processes_in_new_blueprint` — `new_blueprint = {"processes": []}` → все незащищённые остановлены, ничего не запущено.

**Acceptance criteria:**
- [ ] `pytest multiprocess_framework/modules/process_manager_module/tests/test_replace_blueprint.py` — минимум 15 тестов зелёных
- [ ] Тест `test_rollback_on_start_failure` проверяет что `_process_configs` равен snapshot
- [ ] Тест `test_replace_skips_protected` проверяет что MockProcess.start() не вызывается для protected
- [ ] Тесты не запускают реальных OS-процессов (только mock)

**Out of scope:**
- Тесты с реальными OS-процессами (интеграционные, слишком медленные для CI)
- Тестирование рекурсивного rollback (double-failure в rollback — отдельная задача)

**Edge cases:**
- `new_blueprint` = `None` → трактовать как `{}`, не падать с AttributeError
- Двойной вызов `replace_blueprint` без ожидания → второй должен видеть актуальный `_process_configs`

**Dependencies:** Task 5.2
**Module contract:** n/a (только тесты)

---

### Task 5.5 — RecipeStateAdapter + wire StateProxy↔RecipeManager

- [x] Task 5.5 (315a6b6a)

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Создать `RecipeStateAdapter` (реализует `StateAdapterBase`) для синхронизации `state.recipes.active` ↔ `RecipeManager`, и обновить `bootstrap.py` для включения ветки `state.recipes.available` при старте.
**Context:** После Tasks 5.1-5.3 есть RecipeManager и bootstrap. Адаптер — клей между ними и StateProxy: когда `state.recipes.active` меняется → `RecipeManager.set_active()`, когда RecipeManager меняет активный → StateProxy обновляется. Это паттерн аналогичный `RegistersStateAdapter` из Phase 0.

**Files:**
- `multiprocess_prototype/backend/state/adapters/recipe_adapter.py` — **переписать** (текущий — старый wrapper над RecipeEngine без StateAdapterBase)
- `multiprocess_prototype/backend/state/adapters/tests/test_recipe_state_adapter.py` — создать: 8-10 тестов

**Steps:**
1. Прочитать текущий `recipe_adapter.py` — он является старым `RecipeAdapter` (list_slots/get_slot/save_slot/delete_slot wrapper над RecipeEngine). Заменить на `RecipeStateAdapter(StateAdapterBase)`.

2. Создать `RecipeStateAdapter` в `recipe_adapter.py`:
   ```python
   class RecipeStateAdapter(StateAdapterBase):
       def __init__(
           self,
           recipe_manager: RecipeManager,
           state_proxy: Any | None = None,
           logger: Any | None = None,
           stats: Any | None = None,
           error: Any | None = None,
       ) -> None:
   ```
   - `_subscribe_all()`: подписаться на `state_proxy.subscribe("recipes.active", self._on_state_active_changed)`. Сохранить `sub_id` в `self._sub_ids`.
   - `_unsubscribe_all()`: отписаться от всех `_sub_ids`.
   - `_on_state_active_changed(deltas: list[Delta])`: для каждой delta с `path == "recipes.active"` — если не в `_pending_paths` — вызвать `self._recipe_manager.set_active(delta.new_value)` (если not None).
   - `sync_domain_to_state()`: читать `recipe_manager.get_active()` → `state_proxy.set("recipes.active", active)`. Читать `recipe_manager.list()` → `state_proxy.set("recipes.available", slugs)`.
   - `sync_state_to_domain()`: читать `state_proxy.get("recipes.active")` → если не None, `recipe_manager.set_active(slug)`.
   - Anti-loop: использовать `_mark_pending` / `_check_and_clear_pending` из `StateAdapterBase`.
   - Логирование через `_log_info/warning/error` из `StateAdapterBase`.

3. В `__init__.py` адаптеров — обновить `__all__` если есть явный экспорт.

4. Тесты `test_recipe_state_adapter.py`:
   - `test_sync_domain_to_state_sets_active` — mock StateProxy, mock RecipeManager с `get_active() = "cup"` → после `sync_domain_to_state()` proxy.set вызван с `("recipes.active", "cup")`.
   - `test_sync_domain_to_state_sets_available` — mock RecipeManager с `list() = ["a", "b"]` → proxy.set с `("recipes.available", ["a", "b"])`.
   - `test_on_state_active_changed_calls_set_active` — delta с `path="recipes.active", new_value="bottle"` → `recipe_manager.set_active("bottle")` вызван.
   - `test_anti_loop_prevents_echo` — adapter меняет state → callback не вызывает повторный set_active (pending механизм).
   - `test_none_active_not_propagated` — `delta.new_value = None` → `set_active` не вызывается.
   - `test_sync_state_to_domain_loads_active` — proxy.get возвращает `"cup"` → `recipe_manager.set_active("cup")` вызван.
   - `test_sync_state_to_domain_none_skipped` — proxy.get возвращает None → `set_active` не вызывается.
   - `test_unsubscribe_clears_sub_ids` — после `disconnect()` sub_ids пусты.

**Acceptance criteria:**
- [ ] `pytest multiprocess_prototype/backend/state/adapters/tests/test_recipe_state_adapter.py` — все тесты зелёные
- [ ] `RecipeStateAdapter` наследует `StateAdapterBase` (проверить через `issubclass`)
- [ ] Anti-loop: двойное изменение не вызывает рекурсию (тест `test_anti_loop_prevents_echo`)

**Out of scope:**
- Интеграция с ProcessManager.replace_blueprint в адаптере (это делает RecipesPresenter в Task 5.7)
- Изменение `bootstrap.py` (сделано в Task 5.3)

**Edge cases:**
- `set_active` при недоступном рецепте (file not found) — `RecipeManager.set_active` вернёт False, адаптер логирует warning, не падает
- StateProxy ещё не привязан (None) — методы `_log_warning` и return без ошибки

**Dependencies:** Tasks 5.1, 5.3
**Module contract:** public-api-change (переписывается публичный `recipe_adapter.py`)

---

### Task 5.6 — RecipesPresenter + IRecipesView Protocol (MVP)

- [ ] Task 5.6

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Создать `IRecipesView` Protocol и `RecipesPresenter` (новый) согласно MVP-паттерну — полная бизнес-логика без Qt-зависимостей, управляет RecipeManager, инициирует `replace_blueprint` через коллбэк.
**Context:** Текущий `RecipesPresenter` — slot-based (8 слотов, topology snapshot). Нужен новый presenter с CRUD рецептов v2, логикой set_active через replace_blueprint callback. Паттерн идентичен `DisplaysPresenter` (Task 4). GUI (Task 5.7) зависит от этого presenter.

**Files:**
- `multiprocess_prototype/frontend/widgets/tabs/recipes/view.py` — создать: `IRecipesView` Protocol
- `multiprocess_prototype/frontend/widgets/tabs/recipes/presenter.py` — **переписать** (сохранить имя файла, удалить старый код)
- `multiprocess_prototype/frontend/widgets/tabs/recipes/tests/test_recipes_presenter.py` — создать: 10-12 тестов

**Steps:**
1. Создать `view.py` — `IRecipesView` Protocol:
   ```python
   @runtime_checkable
   class IRecipesView(Protocol):
       def refresh_list(self, slugs: list[str]) -> None: ...
       def show_recipe(self, slug: str | None, data: dict | None) -> None: ...
       def set_buttons_state(self, has_selection: bool, is_active: bool) -> None: ...
       def show_error(self, message: str) -> None: ...
       def confirm_delete(self, slug: str) -> bool: ...
   ```
   - `refresh_list`: перестроить nav-список по slug'ам.
   - `show_recipe`: заполнить правую панель метаданными + сводкой blueprint или очистить при None.
   - `set_buttons_state`: `has_selection` управляет Дублировать/Удалить/Активировать; `is_active` — кнопка "Сделать активным" disabled если уже активен.
   - `confirm_delete`: показать диалог, вернуть True если пользователь подтвердил (в тестах — mock True).
   - `show_error`: показать сообщение об ошибке.

2. Переписать `presenter.py` — `RecipesPresenter`:
   ```python
   class RecipesPresenter:
       def __init__(
           self,
           recipe_manager: RecipeManager,
           view: IRecipesView,
           replace_blueprint_fn: Callable[[dict], dict] | None = None,
           logger: Any | None = None,
       ) -> None:
   ```
   - `_recipe_manager`: `RecipeManager`.
   - `_view`: `IRecipesView`.
   - `_replace_blueprint_fn`: callback для замены blueprint при set_active (может быть None — тогда только state обновляется без перезапуска процессов).
   - `_selected_slug: str | None = None`.
   - `load() -> None`: `slugs = recipe_manager.list()` → `view.refresh_list(slugs)` → `view.set_buttons_state(False, False)`.
   - `on_select(slug: str | None) -> None`: читать YAML рецепта через `recipe_manager`'s engine (прямо `engine.recipes_dir / f"{slug}.yaml"`) → `view.show_recipe(slug, data)`. Обновить `_selected_slug`. Вызвать `view.set_buttons_state(True, slug == recipe_manager.get_active())`.
   - `on_create(name: str, description: str) -> None`: сгенерировать slug (slugify от name), создать пустой YAML через `engine.save(slug, paths=[])` с заглушечным blueprint → `load()`.
   - `on_duplicate(slug: str | None = None) -> None`: `slug or _selected_slug` → `recipe_manager.duplicate(slug, slug + "_copy")` → `load()`. Если False → `view.show_error("Не удалось дублировать")`.
   - `on_delete(slug: str | None = None) -> None`: подтверждение через `view.confirm_delete(slug)` → `recipe_manager.delete(slug)` → `load()`.
   - `on_set_active(slug: str | None = None) -> None`: `recipe_manager.set_active(slug)` → если `_replace_blueprint_fn` не None → читать blueprint из YAML → вызвать `_replace_blueprint_fn(blueprint_dict)` → если result["success"] → `load()` + `view.set_buttons_state(True, True)`. Если ошибка → `view.show_error(result.get("error", "Ошибка replace_blueprint"))`.
   - `on_open_in_pipeline(slug: str | None = None) -> None`: TODO — пустая заглушка с `self._log_info("open_in_pipeline: TBD")` (Task 7a).
   - Логирование через паттерн `if self._logger: self._logger.log_info(...)`.

3. Тесты `test_recipes_presenter.py` (mock `IRecipesView` и `RecipeManager`):
   - `test_load_calls_refresh_list` — `load()` → `view.refresh_list` вызван с списком из `recipe_manager.list()`.
   - `test_load_resets_buttons` — `load()` → `view.set_buttons_state(False, False)` вызван.
   - `test_on_select_shows_recipe` — `on_select("cup")` → `view.show_recipe` вызван с данными рецепта.
   - `test_on_select_none_clears` — `on_select(None)` → `view.show_recipe(None, None)` и `set_buttons_state(False, False)`.
   - `test_on_select_active_disables_button` — выбрать slug равный активному → `set_buttons_state(True, True)`.
   - `test_on_duplicate_success` — mock `recipe_manager.duplicate = True` → `load()` вызван.
   - `test_on_duplicate_failure` → `view.show_error` вызван.
   - `test_on_delete_with_confirm` — `view.confirm_delete` возвращает True → `recipe_manager.delete` вызван.
   - `test_on_delete_no_confirm` — `view.confirm_delete` возвращает False → `recipe_manager.delete` НЕ вызван.
   - `test_on_set_active_calls_replace` — mock `_replace_blueprint_fn` → вызывается с blueprint dict из YAML.
   - `test_on_set_active_no_replace_fn` — `_replace_blueprint_fn = None` → `set_active` вызывается без ошибки.
   - `test_on_set_active_replace_error` → `view.show_error` вызван.

**Acceptance criteria:**
- [ ] `pytest multiprocess_prototype/frontend/widgets/tabs/recipes/tests/test_recipes_presenter.py` — все тесты зелёные
- [ ] `RecipesPresenter` не импортирует ни одного Qt-модуля (чистый Python)
- [ ] `IRecipesView` — `@runtime_checkable Protocol`, проверяется `isinstance`
- [ ] `_replace_blueprint_fn = None` → `on_set_active` работает без ошибки (деградация без ProcessManager)

**Out of scope:**
- Qt-виджет RecipesTab (Task 5.7)
- Интеграция с реальным ProcessManagerProcess

**Edge cases:**
- `on_select` с несуществующим slug → YAML файл не найден → `view.show_recipe(slug, None)` и `view.show_error("Рецепт не найден")`
- `on_create` с именем содержащим спецсимволы → slug генерируется безопасно (только `[a-z0-9_-]`)
- `on_duplicate` без `_selected_slug` (None) → `view.show_error("Рецепт не выбран")`

**Dependencies:** Task 5.1
**Module contract:** public-api-change (новый `view.py`, переписывается `presenter.py`)

---

### Task 5.7 — RecipesTab переписать (Qt MVP)

- [ ] Task 5.7

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Переписать `RecipesTab` (Qt часть) на MVP-паттерне: реализует `IRecipesView` Protocol, левая колонка = динамический список, правая панель = метаданные + сводка blueprint + регистры, кнопки CRUD.
**Context:** Текущий tab — slot-based (8 фиксированных слотов, старый presenter). Нужен новый UI аналогичный `DisplaysTab` (Phase 4): три колонки через `DiffScrollTabLayout`, динамический `BaseListNavTab`, правая панель с метаданными.

**Files:**
- `multiprocess_prototype/frontend/widgets/tabs/recipes/tab.py` — **переписать** (сохранить имя класса `RecipesTab`)
- `multiprocess_prototype/frontend/widgets/tabs/recipes/recipe_form.py` — адаптировать или заменить под v2 (метаданные + blueprint summary)
- `multiprocess_prototype/frontend/widgets/tabs/recipes/recipe_io.py` — **удалить** (старое slot-based I/O, заменено RecipeManager)
- `multiprocess_prototype/frontend/widgets/tabs/recipes/__init__.py` — обновить экспорты
- `multiprocess_prototype/frontend/widgets/tabs/recipes/tests/test_recipes_tab.py` — обновить/переписать: 5-8 Qt-тестов

**Steps:**
1. Удалить `recipe_io.py` (старое slot-based I/O). Если `__init__.py` импортирует из него — убрать.

2. Адаптировать/заменить `recipe_form.py` — `RecipeFormWidget`:
   - Поля: `name` (QLineEdit), `description` (QTextEdit), `version` (QLabel readonly), `created`/`modified` (QLabel readonly).
   - Blueprint summary: `QLabel` с текстом вида «Процессы: 3 | Плагины: 5 | Сервисы: 1 | Дисплеи: 2».
   - Метод `populate(slug: str, data: dict | None) -> None` — заполняет поля из v2 YAML dict.
   - Метод `clear() -> None` — очищает все поля.
   - Метод `get_form_data() -> dict` — возвращает `{name, description}` (только редактируемые поля).

3. Переписать `tab.py` — `RecipesTab(BaseListNavTab)` реализует `IRecipesView`:
   - Структура: `DiffScrollTabLayout(title="Рецепты", action_width=160, nav_width=230)` — аналогично другим табам.
   - Action-колонка (левая): кнопки «Создать», «Дублировать», «Удалить», «Сделать активным», «Открыть в Pipeline» (disabled — Task 7a).
   - Nav-колонка (средняя): `BaseListNavTab` с динамическим списком slug'ов.
   - Content-колонка (правая): `RecipeFormWidget` в стеке.
   - `RecipesPresenter` инициализируется в `__init__`, `view=self`.
   - Реализовать `IRecipesView`:
     - `refresh_list(slugs)` → `_sync_nav(slugs)` — обновить `BaseListNavTab`.
     - `show_recipe(slug, data)` → заполнить `RecipeFormWidget.populate(slug, data)`.
     - `set_buttons_state(has_selection, is_active)` → включить/выключить кнопки.
     - `confirm_delete(slug)` → `QMessageBox.question(...)` — спросить подтверждение.
     - `show_error(message)` → `QMessageBox.warning(...)`.
   - `@classmethod create(cls, ctx)` — точка входа.
   - `presenter.load()` вызывается в конце `__init__`.

4. Обновить `__init__.py` — экспортировать `RecipesTab`, `RecipesPresenter`, `IRecipesView`.

5. Обновить тесты `test_recipes_tab.py`:
   - `test_recipes_tab_creates_without_error(qtbot)` — создать с mock ctx.
   - `test_refresh_list_adds_items(qtbot)` — `tab.refresh_list(["a", "b"])` → nav содержит 2 элемента.
   - `test_show_recipe_populates_form(qtbot)` — mock данные → форма заполнена.
   - `test_set_buttons_state_no_selection(qtbot)` — `has_selection=False` → Дублировать/Удалить disabled.
   - `test_set_buttons_state_with_selection(qtbot)` — `has_selection=True` → кнопки enabled.
   - `test_confirm_delete_returns_bool(qtbot)` — monkeypatch QMessageBox.question → проверить возврат True/False.

**Acceptance criteria:**
- [ ] `pytest multiprocess_prototype/frontend/widgets/tabs/recipes/tests/` — все тесты зелёные (включая Qt-тесты через pytest-qt)
- [ ] `isinstance(tab, IRecipesView)` → True
- [ ] Старый `recipe_io.py` удалён (нет импортов на него)
- [ ] Nav-список строится динамически из `RecipeManager.list()`, не из 8 фиксированных слотов
- [ ] Кнопки action-колонки корректно disabled/enabled по состоянию `has_selection`/`is_active`

**Out of scope:**
- Реальный вызов `replace_blueprint` через ProcessManager (только mock callback)
- Открыть в Pipeline (Task 7a)
- Drag-and-drop, горячие клавиши

**Edge cases:**
- Пустой список рецептов → nav пустой, все кнопки кроме «Создать» — disabled
- Удалить активный рецепт → active становится None, nav обновляется
- `data = None` в `show_recipe` → форма очищается без ошибок

**Dependencies:** Task 5.6
**Module contract:** public-api-change (переписывается `tab.py`, новый `view.py`)

---

### Task 5.8 — ADR + финальный интеграционный smoke-test

- [ ] Task 5.8

**Level:** Middle (Sonnet, normal thinking)
**Assignee:** developer
**Goal:** Записать два ADR в `multiprocess_framework/DECISIONS.md` и написать 2-3 E2E smoke-теста: создать рецепт → set_active → mock replace_blueprint получает правильный blueprint dict.
**Context:** ADR документируют два ключевых архитектурных решения Phase 5. Smoke-тесты верифицируют интеграцию RecipeManager → RecipesPresenter → replace_blueprint на реальных YAML-файлах (без GUI и OS-процессов).

**Files:**
- `multiprocess_framework/DECISIONS.md` — добавить два ADR
- `multiprocess_prototype/recipes/tests/test_recipes_integration.py` — создать: 2-3 smoke-теста

**Steps:**
1. Добавить в `multiprocess_framework/DECISIONS.md` (в секцию активных решений):

   **ADR-PM-009: SystemBlueprint остаётся generic; application-расширения рецепта живут параллельными секциями yaml**
   - Статус: Accepted
   - Контекст: Рецепт Inspector содержит application-специфичные данные (`active_services`, `display_bindings`), которые не должны загрязнять generic SystemBlueprint.
   - Решение: Application-секции хранятся рядом с `blueprint` в том же YAML, но не внутри `blueprint`. `SystemBlueprint` остаётся generic-контрактом framework.
   - Последствия: application-слой парсит свои секции сам; framework не знает о них.
   - Альтернативы: SubBlueprint (отвергнут — усложняет схему framework); отдельный файл (отвергнут — неудобно держать синхронно).

   **ADR-PM-010: replace_blueprint в ProcessManagerProcess с snapshot+rollback**
   - Статус: Accepted
   - Контекст: Переключение рецепта требует перезапуска рабочих процессов без остановки GUI и orchestrator.
   - Решение: `replace_blueprint(new_blueprint: dict)` делает snapshot конфигов незащищённых процессов, останавливает их, поднимает новые. При partial failure (любой процесс не стартовал) — полный rollback до snapshot.
   - Последствия: GUI и orchestrator помечаются `"protected": True` в конфиге. ProcessMonitor на время replace останавливается.
   - Альтернативы: hot-swap без rollback (отвергнут — частичное состояние хуже полного отказа); применение через TopologyManager (отвергнут — topology.apply не знает о protected).

2. Создать `test_recipes_integration.py`:
   - `test_create_activate_recipe_smoke(tmp_path)`:
     - Создать RecipeManager с RecipeEngine на tmp_path.
     - Сохранить рецепт `cup_inspection` с blueprint dict `{"processes": [{"process_name": "worker_1", "class": "Worker", "plugins": []}], "wires": []}`.
     - Создать mock `replace_blueprint_fn` (записывает аргументы).
     - Создать RecipesPresenter с mock IRecipesView.
     - Вызвать `presenter.on_set_active("cup_inspection")`.
     - Проверить: `replace_blueprint_fn` вызван с blueprint dict из YAML.
   - `test_migrate_and_load_v1_smoke(tmp_path)`:
     - Создать legacy `recipe_0.yaml` в v1-формате (с topology dict).
     - Инициализировать RecipeEngine с `migration_fn=migrate_v1_to_v2`, `migration_check_fn=is_v1_recipe`.
     - Вызвать `engine.load("recipe_0")`.
     - Проверить: `recipe_0.yaml.bak` создан, `recipe_0.yaml` теперь содержит `version: 2` и ключ `blueprint`.
   - `test_duplicate_and_set_active_smoke(tmp_path)`:
     - Создать рецепт `base_recipe`.
     - `manager.duplicate("base_recipe", "new_recipe")`.
     - `manager.set_active("new_recipe")`.
     - Проверить: `manager.get_active() == "new_recipe"`.

3. Обновить `multiprocess_framework/DECISIONS.md` — добавить ссылки на новые ADR в индексную таблицу (строки для ADR-PM-009 и ADR-PM-010).

**Acceptance criteria:**
- [ ] `pytest multiprocess_prototype/recipes/tests/test_recipes_integration.py` — все 3 теста зелёные
- [ ] `multiprocess_framework/DECISIONS.md` содержит ADR-PM-009 и ADR-PM-010 в таблице индекса
- [ ] `test_migrate_and_load_v1_smoke` проверяет наличие `.bak` файла

**Out of scope:**
- Запуск полной системы с реальными OS-процессами
- Тестирование GUI

**Edge cases:**
- Legacy файл без `description` → миграция не падает, description = ""

**Dependencies:** Tasks 5.1, 5.2, 5.5, 5.6
**Module contract:** n/a (только документация + интеграционные тесты)

---

## Порядок выполнения и параллелизм

```
5.1  (vertical slice: RecipeManager + миграция)
 │
 ├──→ 5.2  (replace_blueprint — teamlead, параллельно с 5.3)
 │    │
 ├──→ 5.3  (state bootstrap — параллельно с 5.2)
 │    │
 │    └──→ 5.4  (integration tests для replace_blueprint, зависит от 5.2)
 │
 └──→ 5.5  (RecipeStateAdapter, зависит от 5.1 + 5.3)
      │
      └──→ 5.6  (RecipesPresenter — чистый Python, зависит от 5.1)
           │
           └──→ 5.7  (RecipesTab — Qt, зависит от 5.6)
                │
                └──→ 5.8  (ADR + smoke-тесты, зависит от 5.1+5.2+5.5+5.6)
```

**Параллельно можно запускать:**
- [5.2 + 5.3] — оба зависят от 5.1, не зависят друг от друга
- [5.4 + 5.5] — после 5.2 (5.4) и после 5.1+5.3 (5.5) соответственно
- [5.6 + 5.4] — 5.6 зависит от 5.1, 5.4 от 5.2 → можно если разные агенты
- Максимум 2 параллельных агента без worktree (правило проекта)

**Рекомендуемые спринты (последовательно для одного агента):**
1. 5.1 → 5.2 (критический путь)
2. 5.3 + 5.4 (после 5.1 и 5.2)
3. 5.5 (после 5.3)
4. 5.6 → 5.7 (финальный UI)
5. 5.8 (финальные ADR + smoke)
