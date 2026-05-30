# План: «Процессы» — насыщенные карточки + управление воркерами (config + runtime)

**Slug:** `processes-workers-runtime` · **Ветка:** `feat/processes-workers-runtime`
**Scope:** config-персист **И** реальный runtime-спавн через IPC (по решению владельца — «сделать сразу правильно»)

---

## Context (зачем)

Вкладка «Процессы» сейчас: плоские `EntityCard` (визуально бедные), кнопки «Создать»/«Удалить» — заглушки `QMessageBox` ([tab.py:220-242](multiprocess_prototype/frontend/widgets/tabs/processes/tab.py#L220-L242)), воркеров в GUI/domain/топологии нет вообще (только дефолтный `message_processor` в каждом процессе).

Нужно: на каждый процесс — насыщенная карточка (ds-card) + таблица CRUD-воркеров с настройкой **по приоритету** (SYSTEM/REALTIME/NORMAL/BATCH/BACKGROUND), плюс рабочие «Создать/Удалить» процесс. Воркеры — конфигурируемые сущности, которые **позже** нагружает Pipeline.

Архитектура (подтверждена владельцем и разведкой): в каждом процессе дефолтный воркер `message_processor` крутится в цикле, опрашивает `RouterManager` (channel `system`) и диспатчит команды в `CommandManager`. Туда добавляем `worker.create/stop/restart/update` → `WorkerManager.create_worker(IdleWorker)`. Воркер сначала idle (loop + smart-sleep), нагрузку даёт Pipeline. Конфиг воркеров персистится в `Process.workers` → топологию; при старте процесса респавнятся из `config["workers"]`.

**Итог:** «сейчас» — GUI создаёт/удаляет/настраивает процессы и воркеры, воркеры реально стартуют/останавливаются в живых процессах, список переживает рестарт процесса и виден Pipeline.

---

## Разрешённые тех-решения (по итогам разведки)

| Вопрос | Решение | Опора (file:line) |
|--------|---------|-------------------|
| Где хранить воркеры (persist) | Новая frozen-сущность `WorkerSpec` + `Process.workers: tuple[WorkerSpec,...]`; сохранение через `services.topology.save()` (in-session, публикует `TopologyReplaced`) | process.py, [topology_repository.py:64](multiprocess_prototype/adapters/stores/topology_repository.py#L64) |
| Runtime-спавн «сейчас» | Live IPC: `send_command(owner_process, "worker.create", {...})` → `message_processor` → `CommandManager` → новый хендлер → `WorkerManager.create_worker` | system_threads.py:28-43, [command_sender.py](multiprocess_framework/modules/frontend_module/bridge/command_sender.py) |
| Спавн при старте из конфига | Расширить `ProcessLaunchConfig` полем `workers` (сейчас жёстко `{}` на [process_launch_config.py:90](multiprocess_framework/modules/process_module/configs/process_launch_config.py#L90)) → долетает в `config["workers"]` → `_create_workers_from_config` (process_module.py:351) | process_module.py:342-372 |
| Класс idle-воркера | Новый generic `IdleWorker(run(stop_event,pause_event))` в **framework** (`process_module/generic/`) — без prototype-зависимостей, резолвится по dotted-path. Готового нет (SourceProducer/DataReceiver — компоненты) | source_producer.py:90-101 (образец smart-sleep) |
| Где хендлеры worker.* | **framework** `process_module/commands/builtin_commands.py` рядом с `worker.pause_all/resume_all` — переиспользуемо | builtin_commands.py:40-90 |
| Телеметрия воркеров → GUI | Heartbeat **уже** несёт `workers_status` ([process_heartbeat.py:83](multiprocess_framework/modules/process_module/heartbeat/process_heartbeat.py#L83)) → ProcessMonitor → broadcast. Обогатить `get_all_workers_status()` (cycle_duration_ms/effective_hz/status) + GUI-мост раздаёт в ключи `processes.{proc}.workers.{name}.*` | process_monitor.py:~150, bindings.py |
| Адресация worker.* команды | Прямо во владельца через `CommandSender.send_command` (НЕ через `process.command` wrapper ProcessManager) | command_sender.py:50-71 |
| Защита | `message_processor` неудаляем/неостанавливаем (guard в presenter + хендлерах). Protected-процесс (`gui`) — без delete/stop | существующий `is_protected` |

**Переиспользовать:** `CrudTable` ([crud_table.py](multiprocess_framework/modules/frontend_module/components/primitives/crud_table.py), set_cell_widget для combo/spin), `StatusIndicator`, `ViewModeToggle`, qss `role="ds-card"` ([cards.qss](multiprocess_prototype/frontend/styles/themes/innotech_theme/components/primitives/cards.qss)), `GuiStateBindings.bind` (glob + weakref auto-cleanup), `TopologyBridge.hot_add_process/hot_remove_process`, паттерн `PluginInstance` для `WorkerSpec`.

---

## Фаза A — Domain: `WorkerSpec` + `Process.workers`

**Goal:** воркер становится сериализуемой domain-сущностью внутри процесса.
**Files:** `multiprocess_prototype/domain/entities/worker.py` (новый), `domain/entities/process.py`, `domain/entities/__init__.py`, `domain/tests/test_entities_roundtrip.py`
**Steps:**
1. `WorkerSpec(SchemaBase, frozen, extra="forbid")` по образцу `PluginInstance`: `worker_name: str`, `priority: Literal["SYSTEM","REALTIME","NORMAL","BATCH","BACKGROUND"]="NORMAL"`, `execution_mode: Literal["loop","task"]="loop"`, `target_interval_ms: int|None=None`, `worker_class: str|None=None` (dotted-path; None→IdleWorker), `protected: bool=False`, `description: str|None=None`, `config: dict[str,Any]` (+ `_fold_extra_into_config`), `from_dict/to_dict`.
2. В `Process`: `workers: tuple[WorkerSpec,...] = ()` + `@field_validator("workers", mode="before")` list→tuple (копия `_coerce_plugins_to_tuple`). `_fold_extra_into_metadata` подхватит автоматически (через `model_fields`).
3. Экспорт в `__init__.py`.
**Acceptance:** round-trip `Process` с воркерами; пустой дефолт `()`; `extra="forbid"` не ломается; protected сохраняется.
**Out of scope:** типизация `config` под конкретный payload (Pipeline-фаза).

## Фаза B — Runtime: IdleWorker + worker.* хендлеры + телеметрия + конфиг-спавн

**Goal:** воркеры реально создаются/останавливаются в живых процессах и респавнятся из конфига.
**Files (framework):** `process_module/generic/idle_worker.py` (новый), `process_module/commands/builtin_commands.py`, `worker_module/core/worker_manager.py` (метрики статуса), `process_module/configs/process_launch_config.py`, + их `tests/`
**Steps:**
1. **IdleWorker:** `__init__(self, process, config: dict)`, `run(self, stop_event, pause_event)` — loop со smart-sleep (паттерн source_producer.py:90-101): `target = config["target_interval_ms"]/1000`; измеряет `cycle_duration`, копит `effective_hz`, спит порциями ≤0.01s, реагирует на `stop_event`/`pause_event`. Без полезной нагрузки (заполнит Pipeline). TASK-режим — один проход.
2. **Хендлеры** в `BuiltinCommands.register()`: `worker.create` (data: `worker_name, worker_class?, priority, execution_mode, target_interval_ms, config?`) → собрать `ThreadConfig` из priority/mode → `worker_manager.create_worker(name, IdleWorker(...).run, tc, auto_start=True)`; `worker.stop` / `worker.restart` / `worker.update` (stop+пересоздать с новым ThreadConfig). Guard: `message_processor` (и `worker_type==SYSTEM`) запрещён к stop/restart/delete — возврат `{status:"error", reason:"protected"}`.
3. **Телеметрия:** `WorkerManager.get_all_workers_status()` дополнить полями `priority, execution_mode, status, cycle_duration_ms, effective_hz, protected` (top-level, не под `metrics` — heartbeat их срезает на process_heartbeat.py:82).
4. **Конфиг-спавн:** в `ProcessLaunchConfig` добавить опциональное поле `workers: dict = {}`; в `build()` класть `payload`-workers в `proc_dict["workers"]` вместо жёсткого `{}` (process_launch_config.py:90).
**Acceptance:** unit — `create_worker` хендлер поднимает поток (WorkerManager.has_worker==True); `stop` убивает; protected-guard работает; `get_all_workers_status` содержит тайминги; ProcessModule из `config["workers"]` поднимает IdleWorker. Контракт-тесты framework зелёные.
**Out of scope:** реальная полезная нагрузка воркера; авто-перезапуск по failure (есть в ThreadConfig, не трогаем).

## Фаза C — GUI bridge + Presenter (CRUD воркеров и процессов)

**Goal:** связать GUI с runtime IPC и config-персистом, без двойного спавна.
**Files:** `multiprocess_prototype/frontend/bridge/worker_bridge.py` (новый) или методы в `topology_bridge.py`; `frontend/bridge/system_commands.py` (builders, если нужно); `processes/presenter.py`, `processes/data.py`, `processes/tests/`
**Steps:**
1. **WorkerBridge:** `worker_create/stop/restart/update(process_name, **fields)` → `command_sender.send_command(process_name, "worker.<op>", data)`. Прямой путь во владельца.
2. **Presenter воркеры:** `WORKER_PRIORITIES` const; `get_workers(proc)` (читает `Process.workers` + синтетический protected `message_processor` первым, если своих нет); `add_worker/remove_worker/update_worker` → (a) мутируют `Process.workers` immutable-пересборкой → `services.topology.save()`; (b) шлют live-IPC через WorkerBridge. `is_worker_protected`.
3. **Presenter процессы:** `create_process(name, category)` → добавить `Process` в топологию + `save()` + `bridge.hot_add_process`; `delete_process(name)` → guard protected → удалить + `save()` + `bridge.hot_remove_process`.
4. **Без двойного спавна:** live-IPC — единственный источник старта в рантайме; `topology.save` — только персист (на старте процесса конфиг-спавн поднимет тех же из `config["workers"]`). При live-create процесс уже запущен → конфиг-спавн его не дублирует (создаётся при `init`, а не при каждом save).
**Acceptance:** presenter add/remove/update воркера и create/delete процесса — на fake-topology персистятся и (с mock-sender) шлют корректный IPC dict; protected-guard.
**Out of scope:** durable-запись топологии на диск (отдельно — через активный рецепт, как Pipeline `save_to_active_recipe`).

## Фаза D — Widgets: ProcessCard (ds-card) + WorkerTable + qss

**Goal:** насыщенная карточка и таблица воркеров.
**Files:** `processes/widgets/process_card.py`, `processes/widgets/worker_table.py` (новые), `styles/themes/innotech_theme/components/primitives/cards.qss`
**Steps:**
1. **ProcessCard** (`QFrame` `role="ds-card"`/`property("role","process-card")`): цветная полоса категории слева, крупный заголовок + статус-пилюля (StatusIndicator + текст), строка метрик FPS/Latency/PID, кнопки-иконки ▶/⏸/↻/🗑 справа. Сигнал `action_clicked(entity_id, action_id)`.
2. **WorkerTable** (на базе `CrudTable`): колонки `Имя · Приоритет(QComboBox) · Режим(QComboBox) · Интервал мс(QSpinBox) · Статус · ⋮`. `set_cell_widget` для combo/spin. Protected-строка: combo приоритета активен, кнопка удаления скрыта/disabled. Сигналы `worker_added/worker_removed(name)/worker_changed(name, field, value)`.
3. **qss:** `QFrame[role="process-card"]` (градиент по токенам), `[category="source|processing|..."]` левый бордер-цвет, статус-пилюля, оформление таблицы. Только токены темы (без хардкода цветов).
**Acceptance:** оба виджета рендерятся; combo приоритета = 5 значений; protected-строка без удаления; сигналы летят (pytest-qt).
**Out of scope:** анимации, drag-reorder воркеров.

## Фаза E — Сборка в панель + диалог + динамические bindings

**Goal:** всё вместе во вкладке.
**Files:** `processes/_panels.py`, `processes/tab.py`, `processes/widgets/create_process_dialog.py` (новый), `frontend/state/` (мост workers_status→ключи, если нужно)
**Steps:**
1. `SingleProcessPanel` Cards-режим: `ProcessCard` + секция «Воркеры» (`QGroupBox` + `WorkerTable`). Сигналы таблицы → presenter (Фаза C). `ProcessCard.action_clicked` → presenter.
2. `tab.py`: заглушки → реальные. «Создать» → `CreateProcessDialog` (имя + категория) → `presenter.create_process`. «Удалить» → confirm → `presenter.delete_process`. Подписка на `TopologyReplaced` (`services.events`) → `_sync_nav` + перестроение панелей.
3. **Динамические bindings:** при перестроении строк воркеров — `bindings.bind(f"processes.{proc}.workers.{wname}.status|cycle_duration_ms|effective_hz", cell_widget, ...)`; мост раздаёт `workers_status` из broadcast в эти ключи (по образцу `processes.{name}.state.*`). `unbind_widget` при пересоздании (weakref авто-cleanup уже есть).
4. `AllProcessesPanel`: лёгкий рестайл групповых карточек под ds-card + метрика «Воркеров: N».
**Acceptance:** на вкладке создаётся/удаляется процесс; в карточке добавляется/удаляется/настраивается воркер с приоритетом; изменения видны после `TopologyReplaced`; backward-compat алиасы tab (`_cards`, `_all_table`, `_health_panel`) сохранены для тестов.
**Out of scope:** перенос воркеров между процессами (Pipeline).

## Фаза F — Тесты + Qt smoke + docs/memory

**Files:** `processes/tests/`, `domain/tests/`, framework `*/tests/`, `docs/claude/memory/` + локальная memory, STATUS.md вкладки
**Steps:**
1. Unit: WorkerSpec round-trip; presenter CRUD (воркеры+процессы); WorkerTable/ProcessCard/dialog (pytest-qt); framework worker.* хендлеры + IdleWorker + конфиг-спавн.
2. **Qt smoke (обязательно, см. memory feedback_qt_mcp_smoke):** запуск прототипа (`/run-proto` или `python run.py`), `qt_snapshot` вкладки «Процессы», проверка ProcessCard + WorkerTable; визуальный round-trip «Добавить воркер» → строка появилась; `qt_messages` без ошибок.
3. Обновить memory `project_workers_architecture`, `project_processes_tab`, `project_worker_cycle_timing` (dual-write в `docs/claude/memory/` + локально).
**Acceptance:** `python scripts/run_framework_tests.py` + `python scripts/validate.py` зелёные; Qt-smoke подтверждает реальную сборку; sentrux-инварианты (`framework→prototype` запрещён) не нарушены.

---

## Порядок и зависимости

```
A (domain) ──► C (presenter/bridge) ──► E (сборка)
B (runtime) ──┘                          ▲
D (widgets) ─────────────────────────────┘
F (тесты/smoke/docs) — сквозная, финал
```
A и B независимы (параллельно). D независим (только qss/widgets). C зависит от A+B. E зависит от C+D. F — финал.

## Риски
- **Framework-правки** (Фаза B): IdleWorker, BuiltinCommands, ProcessLaunchConfig, WorkerManager — затрагивают контракт-тесты framework. Держать изменения аддитивными (новые поля опциональны, новые команды не ломают существующие).
- **Двойной спавн:** строго разделить — live-IPC при GUI-действии vs конфиг-спавн при `init` процесса. Не вызывать конфиг-спавн на каждый `save`.
- **Телеметрия:** `workers_status` срезает `metrics` (process_heartbeat.py:82) — тайминги класть top-level.
- **Layering:** IdleWorker/хендлеры в framework (без prototype-импортов); GUI-виджеты в prototype.

## Verification (end-to-end)
1. `python run.py` → вкладка «Процессы»: карточки в ds-стиле, у процесса — таблица воркеров.
2. «Создать воркер» с priority=REALTIME → строка появилась; `qt_messages` чистый; в логах процесса — `WorkerManager.create_worker` поднял поток.
3. «Удалить воркер» → исчез и в GUI, и в рантайме; `message_processor` удалить нельзя (кнопки нет).
4. «Создать процесс» → новый процесс в nav + рантайме (hot_add); «Удалить» → исчез.
5. Переключение nav/Cards↔Table — режим сохраняется; `TopologyReplaced` перестраивает список.
6. `python scripts/run_framework_tests.py`, `python scripts/validate.py`, целевые pytest — зелёные.

## Commit-стратегия
Conventional Commits + trailers `Why:`/`Layer:` (mixed/framework/prototype), `Refs: plans/processes-workers-runtime.md`. Отдельный `docs(plans):` на создание плана. План продублировать в `multiprocess_prototype/.../plans/processes-workers-runtime.md` (app-зона) — dual-save.
