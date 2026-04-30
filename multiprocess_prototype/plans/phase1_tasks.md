# План: Фаза 1 — Подключение StateStoreManager

**Дата:** 2026-04-30
**Статус:** DRAFT
**Фаза 0:** DONE (9 коммитов, ~2261 строк удалено)

---

## Раздел 1: Разведка — что выяснено

### 1.1 Структура StateStoreManager (зрелая подсистема)

- **Файл:** `multiprocess_prototype/state_store/manager/state_store_manager.py`
- Конструктор: `StateStoreManager(router=None, initial_state=None, logger=None)` — все аргументы опциональны, router=None допустимо для тестов (строка 34-56)
- Метод `initialize()` — регистрирует обработчики в RouterManager если router задан (строка 86-97)
- Метод `shutdown()` — очищает все подписки (строка 99-116)
- Метод `register_commands(command_manager)` — регистрирует 7 IPC-команд в CommandManager (строка 349-381)
- Метод `register_message_handlers(router)` — регистрирует 7 обработчиков в RouterManager напрямую (строка 383-405)
- **7 IPC-команд:** `state.set`, `state.merge`, `state.get`, `state.get_subtree`, `state.subscribe`, `state.unsubscribe`, `state.unsubscribe_all`

### 1.2 Два способа регистрации обработчиков

Есть два метода, и это важно:
- `register_commands(command_manager)` — через CommandManager (обычный путь для process-команд)
- `register_message_handlers(router)` — напрямую в RouterManager (используется в `initialize()`)

В `initialize()` вызывается `register_message_handlers(router)` — то есть для работы StateStoreManager достаточно передать `router` в конструктор. `register_commands` — это дополнительная опция для CLI/командной строки.

### 1.3 bootstrap.py

- **Файл:** `multiprocess_prototype/state_store/bootstrap.py`
- Функция `build_initial_state(app_config: dict) -> dict` — принимает dict (Dict at Boundary), не Pydantic (строка 84)
- Строит дерево: `{cameras: {str(id): {config, state, regions}}, renderer, robot, database, system}`
- Начальный system.status = "initializing" (строка 119)
- AppConfig имеет `model_dump()` (наследует SchemaBase) и `to_dict()` — можно использовать любой

### 1.4 ProcessManagerProcessApp — точка внедрения

- **Файл:** `multiprocess_prototype/backend/processes/process_manager/process.py`
- Класс `ProcessManagerProcessApp(ProcessManagerProcess)` — всего 31 строка
- Единственный переопределённый метод: `_setup_topology_manager()` — паттерн уже есть (строка 22-30)
- StateStoreManager НЕ упоминается и НЕ закомментирован нигде в этом файле
- Атрибут `_state_store_manager` нигде не объявлен

### 1.5 ProcessManagerProcess — lifecycle

- **Файл:** `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py`
- Lifecycle: `__init__ → _create_components()`, `initialize() → super().initialize() → _setup_console_manager() → _setup_topology_manager() → _register_builtin_commands() → _create_processes_from_config() → monitor.start()`
- `_setup_state_store()` нигде не вызывается — нужно добавить вызов в `initialize()` прототипа
- В `shutdown()` порядок: monitor.stop → registry.stop_all → console.shutdown → super()
- `self.get_config(key)` — стандартный способ читать конфиг ProcessManager
- `self.router_manager` — доступен после `super().initialize()`, поэтому `_setup_state_store()` надо вызывать ПОСЛЕ super().initialize()
- `self.command_manager` — доступен после `super().initialize()`

### 1.6 Где ProcessManager получает AppConfig

- AppConfig передаётся в `SystemLauncher.add_process(*process(cfg))` для каждого процесса
- ProcessManager получает свой конфиг через `self.get_config(key)` — это `self._config` dict
- AppConfig.to_dict() вызывается в `main.py` косвенно через `process(cfg)` — конфиг приходит уже как dict
- **Проблема:** AppConfig целиком НЕ кладётся в конфиг ProcessManager. В `main.py` конфиги добавляются по одному `for cfg in app.all_process_configs()`. ProcessManager не знает об остальных процессах напрямую.
- **Решение для bootstrap:** ProcessManager может получить конфиги процессов из `self._process_configs` (dict с именами и конфигами дочерних процессов, заполняется в `_create_processes_from_config`). Или можно передать app_config.to_dict() явно в конфиг ProcessManager.

### 1.7 StateProxy — как клиенты используют

- **Файл:** `multiprocess_prototype/state_store/proxy/state_proxy.py`
- `StateProxy(process_name, router=router)` — создаётся в каждом ProcessModule
- Адрес сервера хардкодирован: `_PROCESS_MANAGER = "ProcessManager"` (строка 27)
- Регистрация обработчика входящих дельт: `router.register_message_handler("state.changed", proxy.on_state_changed)`
- **Уже реализован:** `CameraProcess._init_application_threads()` создаёт и использует StateProxy (строки 63-81)
- StateProxy уже подключён в CameraProcess, но его команды идут в ProcessManager где StateStoreManager не работает — IPC зависает

### 1.8 Существующее использование StateProxy в CameraProcess

```
# multiprocess_prototype/backend/processes/camera/process.py, строка 63-81
self._state_proxy = StateProxy(f"camera_{self._camera_id}", router=self.router_manager)
self.router_manager.register_message_handler("state.changed", self._state_proxy.on_state_changed)
self._state_proxy.subscribe(f"cameras.{self._camera_id}.config.*", callback=..., exclude_self=True)
self._state_proxy.set(f"cameras.{self._camera_id}.state.status", "initialized")
```

Всё это уже написано в CameraProcess. Но StateStoreManager на стороне ProcessManager не создан — команды `state.*` уходят в никуда.

### 1.9 Middleware

- **ValidationMiddleware:** принимает `rules: dict[str, dict]` — паттерн путей → правило `{type, min, max, enum}` (файл `middleware/validation.py`)
- **ThrottleMiddleware:** принимает `rules: dict[str, float]` — паттерн → интервал в сек (0 = блокировать) (файл `middleware/throttle.py`)
- Подключение: `manager.use(middleware_instance)` — добавляет в `MiddlewarePipeline`
- Порядок: validation → throttle (рекомендованный)

### 1.10 Доменные адаптеры (не для Фазы 1)

- `adapters/registers_adapter.py` — `RegistersStateAdapter` — двунаправленный мост RegistersManager ↔ StateProxy (GUI-сторона, не ProcessManager)
- `adapters/camera_state_adapter.py` — `CameraStateAdapter` — читает cameras.*.state через GuiStateProxy
- `adapters/recipe_adapter.py` — `RecipeAdapter` — мост RecipeManagerProtocol → RecipeEngine
- **Все три нужны на GUI-стороне, не в ProcessManager.** Фаза 1 их не трогает.

### 1.11 Тесты

- `state_store/tests/test_state_store_manager.py` — покрывает StateStoreManager и DeltaDispatcher полностью. Тесты работают без реального RouterManager (MockRouter)
- Интеграционный тест `TestIntegration.test_full_flow` — проверяет full-cycle без IPC
- `test_integration.py` в этой директории — НЕ существует (проверено)
- Тестов для bootstrap.py отдельно нет

### 1.12 Отклонения от утверждений плана

| Утверждение | Факт |
|---|---|
| «~50 строк проводки» | Точно: ~35-45 строк в ProcessManagerProcessApp + ~30 строк доменного middleware-конфига |
| «StateStoreManager нигде не создаётся» | Подтверждено: ни в одном файле `_state_store_manager` не объявлен |
| «7 IPC-команд» | Подтверждено: ровно 7 в `register_commands` и `register_message_handlers` |
| «bootstrap принимает app_config.to_dict()» | Подтверждено: `build_initial_state(app_config: dict)` |
| «ProcessManager не имеет AppConfig целиком» | ДА — нужно решить как передать данные для bootstrap |

### 1.13 Риски (найденные при разведке)

- **Bootstrapping проблема:** ProcessManager не получает AppConfig напрямую. Конфиги процессов приходят через `_create_processes_from_config` из `get_config("processes_config")`. Для `build_initial_state` нужен dict со структурой `{cameras: [...], renderer: {...}, ...}`. Решение: собрать из `self._process_configs` после `_create_processes_from_config`, или передать `app_config_dict` явно в конфиг ProcessManagerApp.
- **Race condition:** StateStoreManager надо создать ДО того, как дочерние процессы стартуют (они шлют `state.*` команды при инициализации). Значит `_setup_state_store()` должен вызываться раньше `_create_processes_from_config`.
- **router_manager доступен только после super().initialize():** _setup_state_store() вызывать в переопределённом initialize() прототипа, строго после `super().initialize()`.

---

## Раздел 2: Дизайн интеграции

### 2.1 Где и что добавлять

**Единственный файл для изменения:** `multiprocess_prototype/backend/processes/process_manager/process.py`

Паттерн уже есть: `_setup_topology_manager()` переопределяется в `ProcessManagerProcessApp` и вызывает `super()._setup_topology_manager()`. Для StateStore аналогично — добавляем `_setup_state_store()`.

**Новый файл (доменный конфиг middleware):** `multiprocess_prototype/backend/processes/process_manager/state_store_config.py`
- Содержит `build_validation_rules() -> dict` и `build_throttle_rules() -> dict`
- Изолирует доменные правила от инфраструктуры (легко тестировать, легко менять)

### 2.2 Последовательность lifecycle

```
ProcessManagerProcessApp.initialize() (вызывается автоматически фреймворком)
    ↓
super().initialize()   ← ProcessManagerProcess.initialize()
    ↓
    super().initialize()   ← ProcessModule.initialize() — инициализирует router_manager, command_manager
    ↓
    _setup_console_manager()
    ↓
    _setup_topology_manager()   ← вызывает ProcessManagerProcessApp._setup_topology_manager()
    ↓
    _register_builtin_commands()
    ↓
    _create_processes_from_config()   ← дочерние процессы создаются и стартуют
    ↓
    monitor.start()
    ↓
    system_ready_event.set()
    ↓
↓ (возврат в ProcessManagerProcessApp.initialize())
_setup_state_store()   ← НАШ МЕТОД: создаём StateStoreManager
    ↓
    build_initial_state() из _process_configs (уже заполнен)
    ↓
    StateStoreManager.initialize() → register_message_handlers(router_manager)
```

**Критичное замечание о порядке:** дочерние процессы стартуют в `_create_processes_from_config`, а к тому моменту StateStoreManager ещё не создан. Это означает что первые `state.*` команды от CameraProcess (строка 81 camera/process.py) могут прийти до готовности.

**Решение:** переопределить `initialize()` целиком в `ProcessManagerProcessApp`, вызвать `_setup_state_store()` ДО вызова `super().initialize()` (точнее — вставить его между `super().initialize()` и `_create_processes_from_config`). Это требует переопределить initialize() вместо добавления нового метода.

**Альтернативное решение (проще и безопаснее):** переопределить в ProcessManagerProcessApp только `_setup_state_store()` как хук-метод. Добавить вызов `self._setup_state_store()` в базовый `ProcessManagerProcess.initialize()` — между `_setup_topology_manager()` и `_register_builtin_commands()`. В базовом классе реализация хука — пустая (`pass`), в прототипе — полная.

**Выбранный подход:** хук `_setup_state_store()` в базовом классе + переопределение в прототипе. Это чистый шаблонный метод (Template Method pattern), безопасный для Фазы 2.

### 2.3 Как процессы получают StateProxy

Никаких изменений в процессах не нужно. StateProxy уже используется в CameraProcess (строки 63-81). Процесс сам создаёт `StateProxy(name, router=self.router_manager)`. Механизм работает через RouterManager — команды маршрутизируются в "ProcessManager". После подключения StateStoreManager в ProcessManager эти команды начнут обрабатываться.

### 2.4 Bootstrap: как получить данные для build_initial_state

Вариант A (рекомендуемый): передать `app_config_dict` в конфиг ProcessManagerApp через SystemLauncher.
- В `main.py` добавить `app_config_dict = app.model_dump()` и передать в конфиг ProcessManagerApp: `{"app_config": app_config_dict, ...}`
- В `_setup_state_store()` читать: `app_config = self.get_config("app_config") or {}`

Вариант B (fallback): реконструировать из `self._process_configs`. Более хрупкий — зависит от внутренней структуры dict.

**Решение: Вариант A** — чистый, явный, тестируемый, соответствует Dict at Boundary.

**Изменение в main.py:** 1 строка — передать `app_config_dict` в конфиг ProcessManagerApp.

### 2.5 Shutdown

В `ProcessManagerProcessApp.shutdown()` добавить:
```
if hasattr(self, "_state_store_manager") and self._state_store_manager:
    self._state_store_manager.shutdown()
```
Перед вызовом `super().shutdown()`.

---

## Раздел 3: Подзадачи

### Задача 1.1 — Хук _setup_state_store() в базовом классе

**Уровень:** Middle (Sonnet, normal)
**Исполнитель:** developer
**Цель:** добавить пустой хук `_setup_state_store()` в `ProcessManagerProcess` и вызов его в правильном месте lifecycle

**Файлы:**
- `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py` — добавить хук и вызов

**Шаги:**
1. Добавить метод `_setup_state_store(self) -> None` после `_setup_topology_manager` (строка ~182):
   ```python
   def _setup_state_store(self) -> None:
       """Хук: создать StateStoreManager. Переопределяется в прототипе."""
       pass
   ```
2. В методе `initialize()` добавить вызов `self._setup_state_store()` после `self._setup_topology_manager()` и ДО `self._register_builtin_commands()` (строка ~144)
3. Добавить `self._state_store_manager = None` в `_create_components()` рядом с `self._topology_manager`

**Acceptance criteria:**
- [ ] `python -c "from multiprocess_framework.modules.process_manager_module.process.process_manager_process import ProcessManagerProcess; p = ProcessManagerProcess(); print('ok')"` — не падает
- [ ] Метод `_setup_state_store` присутствует в ProcessManagerProcess и возвращает None
- [ ] Вызов `_setup_state_store` в `initialize()` находится строго между `_setup_topology_manager()` и `_register_builtin_commands()`

**Out of scope:** не добавлять никакой логики StateStore в базовый класс — только пустой хук

**Edge cases:** нет

**Dependencies:** нет

---

### Задача 1.2 — Передача app_config в конфиг ProcessManagerApp

**Уровень:** Middle (Sonnet, normal)
**Исполнитель:** developer
**Цель:** передать `app_config.model_dump()` в конфиг ProcessManagerApp через SystemLauncher

**Файлы:**
- `multiprocess_prototype/main.py` — передать app_config_dict

**Шаги:**
1. После строки `app = AppConfig(cameras=cameras, gui=gui, worker_pool_size=worker_pool_size)` добавить:
   ```python
   app_config_dict = app.model_dump()
   ```
2. Перед вызовом `launcher.run()` найти место где ProcessManagerApp добавляется в launcher. Сейчас в `main.py` конфиги добавляются через `for cfg in app.all_process_configs()`. ProcessManagerApp конфиг задаётся через `SystemLauncher(orchestrator_class_path=...)`. Нужно найти как SystemLauncher передаёт config в ProcessManagerProcess.
3. Если SystemLauncher принимает `orchestrator_config` — передать `{"app_config": app_config_dict}`. Если нет — изучить API SystemLauncher и найти механизм.

**Подготовительная работа для исполнителя:** прочитать `multiprocess_framework/modules/process_manager_module/system_launcher.py` и найти как передаётся конфиг оркестратора.

**Acceptance criteria:**
- [ ] В `ProcessManagerProcessApp._setup_state_store()` вызов `self.get_config("app_config")` возвращает dict с ключами `cameras`, `renderer`, `robot`, `database`
- [ ] `python -c "from multiprocess_prototype.main import main"` — импорт без ошибок

**Out of scope:** не менять логику загрузки профиля, не трогать CameraConfig

**Edge cases:** если SystemLauncher не поддерживает orchestrator_config — использовать Вариант B (реконструировать из `self._process_configs`)

**Dependencies:** нет

---

### Задача 1.3 — Реализация _setup_state_store() и доменный конфиг middleware

**Уровень:** Middle+ (Sonnet, extended thinking)
**Исполнитель:** developer
**Цель:** создать StateStoreManager с bootstrap и middleware в ProcessManagerProcessApp, изолировав доменные правила в отдельном файле

**Файлы:**
- `multiprocess_prototype/backend/processes/process_manager/process.py` — переопределить `_setup_state_store()` и дополнить `shutdown()`
- `multiprocess_prototype/backend/processes/process_manager/state_store_config.py` — создать с доменными правилами валидации и throttle

**Шаги:**

**state_store_config.py:**
1. Создать функцию `build_validation_rules() -> dict[str, dict]`:
   - `"cameras.*.config.fps"`: `{"type": int, "min": 1, "max": 240}`
   - `"cameras.*.config.camera_type"`: `{"type": str, "enum": ["webcam", "hikvision", "simulator", "file"]}`
   - `"cameras.*.config.resolution_width"`: `{"type": int, "min": 1, "max": 7680}`
   - `"cameras.*.config.resolution_height"`: `{"type": int, "min": 1, "max": 4320}`
   - `"cameras.*.state.status"`: `{"type": str, "enum": ["stopped", "running", "error", "initialized", "paused"]}`
   - `"renderer.config.*"`: базовые правила
2. Создать функцию `build_throttle_rules() -> dict[str, float]`:
   - `"cameras.*.state.actual_fps"`: `1.0` (не чаще 1 раза в секунду)
   - `"cameras.*.state.drops_count"`: `2.0`
   - `"cameras.*.state.last_frame_seq"`: `0` (блокировать — не нужен в StateStore)

**process.py:**
3. В классе `ProcessManagerProcessApp` добавить атрибут `_state_store_manager: StateStoreManager | None = None`
4. Реализовать `_setup_state_store(self) -> None`:
   ```
   - Ленивый импорт StateStoreManager из multiprocess_prototype.state_store.manager.state_store_manager
   - Ленивый импорт build_initial_state из multiprocess_prototype.state_store.bootstrap
   - Ленивый импорт ValidationMiddleware, ThrottleMiddleware
   - Ленивый импорт build_validation_rules, build_throttle_rules из state_store_config
   - app_config = self.get_config("app_config") or {}
   - initial_state = build_initial_state(app_config)
   - self._state_store_manager = StateStoreManager(router=self.router_manager, initial_state=initial_state)
   - self._state_store_manager.use(ValidationMiddleware(build_validation_rules()))
   - self._state_store_manager.use(ThrottleMiddleware(build_throttle_rules()))
   - self._state_store_manager.initialize()
   - self._log_info("StateStoreManager подключён")
   ```
5. Добавить в `ProcessManagerProcessApp.shutdown()` перед `super().shutdown()`:
   ```
   if self._state_store_manager:
       self._state_store_manager.shutdown()
   ```

**Acceptance criteria:**
- [ ] `python -c "from multiprocess_prototype.backend.processes.process_manager.process import ProcessManagerProcessApp; print('ok')"` — не падает
- [ ] `python -c "from multiprocess_prototype.backend.processes.process_manager.state_store_config import build_validation_rules, build_throttle_rules; print(build_validation_rules())"` — возвращает dict
- [ ] `ValidationMiddleware(build_validation_rules())` создаётся без ошибок
- [ ] `ThrottleMiddleware(build_throttle_rules())` создаётся без ошибок

**Out of scope:** не менять доменные адаптеры (camera_state_adapter, registers_adapter, recipe_adapter) — они GUI-сторона. Не добавлять RecipeEngine. Не добавлять persistence/health/devtools.

**Edge cases:**
- `app_config = {}` (app_config не передан) → `build_initial_state({})` → минимальное дерево с `system.status=initializing` — это нормально, не падаем
- `router_manager = None` → StateStoreManager создаётся с router=None, работает без IPC (тестовый режим)

**Dependencies:** 1.1 (хук в базовом классе), 1.2 (app_config в конфиге)

---

### Задача 1.4 — Unit-тесты для подключения

**Уровень:** Middle (Sonnet, normal)
**Исполнитель:** developer
**Цель:** написать unit-тесты для state_store_config.py и smoke-тест создания ProcessManagerProcessApp без IPC

**Файлы:**
- `multiprocess_prototype/tests/unit/test_state_store_config.py` — создать
- `multiprocess_prototype/tests/unit/test_process_manager_app.py` — создать или добавить к существующему

**Шаги:**

**test_state_store_config.py:**
1. `test_validation_rules_structure` — проверить что build_validation_rules() возвращает dict с нужными ключами
2. `test_throttle_rules_structure` — проверить что build_throttle_rules() содержит FPS-путь с интервалом > 0
3. `test_validation_middleware_accepts_valid` — создать ValidationMiddleware с правилами, вызвать before_set для валидного значения → proceed=True
4. `test_validation_middleware_rejects_invalid` — вызвать before_set для невалидного значения → proceed=False
5. `test_throttle_middleware_blocks_rapid_writes` — два быстрых вызова before_set → первый пропускает, второй блокирует

**test_process_manager_app.py:**
6. `test_setup_state_store_without_router` — создать ProcessManagerProcessApp без router, вызвать `_setup_state_store()` напрямую → не падает, `_state_store_manager` создан
7. `test_setup_state_store_with_empty_app_config` — вызов с `app_config={}` → начальное состояние содержит ключ `system`
8. `test_shutdown_clears_state_store` — после shutdown() `_state_store_manager` не поднимает исключений

**Acceptance criteria:**
- [ ] `pytest multiprocess_prototype/tests/unit/test_state_store_config.py -v` — все тесты зелёные
- [ ] `pytest multiprocess_prototype/tests/unit/test_process_manager_app.py -v` — все тесты зелёные
- [ ] Существующие тесты `state_store/tests/test_state_store_manager.py` не сломаны

**Out of scope:** не тестировать реальный IPC через multiprocessing, не тестировать GUI

**Edge cases:** тест должен работать без запущенного Ollama/qex

**Dependencies:** 1.3

---

### Задача 1.5 — Интеграционный тест end-to-end (без GUI)

**Уровень:** Senior (Opus, normal)
**Исполнитель:** teamlead
**Цель:** написать интеграционный тест: StateProxy в одном потоке → StateStoreManager в другом → delta доставляется через mock router

**Файлы:**
- `multiprocess_prototype/tests/integration/test_state_store_integration.py` — создать

**Шаги:**
1. Создать MockRouter (или взять из test_state_store_manager.py как образец)
2. Создать `StateStoreManager(router=mock_router, initial_state=build_initial_state({}))`
3. Вызвать `manager.initialize()` → проверить что 7 обработчиков зарегистрированы
4. Создать `StateProxy("camera_0", router=mock_router)` — router здесь тот же mock
5. Симулировать подписку: напрямую вызвать `mock_router.registered_handlers["state.subscribe"](subscribe_msg)`
6. Симулировать state.set: напрямую вызвать обработчик
7. Проверить что mock_router.sent_messages содержит `state.changed` с ожидаемой дельтой
8. Проверить что `StateProxy.on_state_changed(msg)` обновляет кэш
9. Тест `test_camera_set_propagates_to_subscriber`: camera_0 ставит fps → gui получает state.changed → proxy.get() возвращает 30

**Acceptance criteria:**
- [ ] `pytest multiprocess_prototype/tests/integration/test_state_store_integration.py -v` — зелёный
- [ ] Тест не запускает реальные процессы (multiprocessing)
- [ ] Тест демонстрирует что строки 63-81 camera/process.py работали бы с реальным StateStoreManager

**Out of scope:** не тестировать реальный межпроцессный IPC, не тестировать throttle end-to-end

**Edge cases:** `exclude_self=True` в subscribe — проверить что camera_0 не получает собственные дельты

**Dependencies:** 1.3

---

### Задача 1.6 — Smoke-проверка запуска

**Уровень:** Junior (Haiku, normal)
**Исполнитель:** docs-writer
**Цель:** описать команды для ручной smoke-верификации и дополнить STATUS.md

**Файлы:**
- `multiprocess_prototype/state_store/STATUS.md` — обновить статус

**Шаги:**
1. Убедиться что команды ниже корректны и добавить их в STATUS.md как раздел "Верификация Фазы 1":

```bash
# Структурная валидация
python scripts/validate.py

# Unit-тесты state_store (уже существующие)
pytest multiprocess_prototype/state_store/tests/ -v

# Новые unit-тесты Фазы 1
pytest multiprocess_prototype/tests/unit/test_state_store_config.py -v
pytest multiprocess_prototype/tests/unit/test_process_manager_app.py -v

# Интеграционный тест
pytest multiprocess_prototype/tests/integration/test_state_store_integration.py -v

# Smoke-импорт
python -c "from multiprocess_prototype.backend.processes.process_manager.process import ProcessManagerProcessApp; print('OK')"
python -c "from multiprocess_prototype.state_store.bootstrap import build_initial_state; s = build_initial_state({}); assert 'system' in s; print('bootstrap OK')"
```

2. Обновить `state_store/STATUS.md`: изменить статус с "Не подключён" на "Фаза 1 — подключён в ProcessManagerProcessApp"

**Acceptance criteria:**
- [ ] `state_store/STATUS.md` содержит обновлённый статус
- [ ] Команды верификации задокументированы

**Out of scope:** не запускать GUI, не запускать реальный прототип

**Dependencies:** 1.3, 1.4, 1.5

---

## Раздел 4: Риски и mitigation

| Риск | Вероятность | Mitigation |
|---|---|---|
| Race condition: CameraProcess стартует раньше StateStoreManager | Высокая | StateStoreManager должен создаваться до `_create_processes_from_config`. Реализовать через хук МЕЖДУ topology и register_builtin_commands в базовом классе. |
| app_config не передаётся в ProcessManagerApp конфиг | Средняя | Задача 1.2 — явная передача через SystemLauncher. Если API не поддерживает — использовать fallback из `_process_configs`. |
| MiddlewarePipeline.use() бросает ValueError при дублировании middleware | Низкая | `_setup_state_store()` вызывается один раз в жизненном цикле. Добавить guard: `if self._state_store_manager is not None: return` |
| router_manager=None при вызове _setup_state_store | Средняя | StateStoreManager работает с router=None, просто не регистрирует обработчики. Логировать warning. |
| Блокирующий вызов router.send() из StateProxy на старте | Средняя | StateProxy._send() использует `send_async` (fire-and-forget), StateProxy.subscribe() использует `_send_sync`. Если router не готов принимать ответы — subscribe вернёт None и StateProxy использует локальный sub_id. Это нормальный fallback. |

---

## Раздел 5: Порядок выполнения

```
Фаза 1: Инфраструктура
    Задача 1.1 [PENDING] — хук в базовом классе
    Задача 1.2 [PENDING] — передача app_config

Фаза 2: Реализация (depends on 1.1, 1.2)
    Задача 1.3 [PENDING] — _setup_state_store() + state_store_config.py

Фаза 3: Тесты (depends on 1.3)
    Задача 1.4 [PENDING] — unit-тесты
    Задача 1.5 [PENDING] — интеграционный тест

Фаза 4: Документация (depends on 1.3, 1.4, 1.5)
    Задача 1.6 [PENDING] — smoke-проверка и STATUS.md
```

Задачи 1.4 и 1.5 можно вести параллельно.

---

## Раздел 6: Verification commands

```bash
# После задачи 1.1
python -c "
from multiprocess_framework.modules.process_manager_module.process.process_manager_process import ProcessManagerProcess
import inspect
src = inspect.getsource(ProcessManagerProcess.initialize)
assert '_setup_state_store' in src, 'хук не вызывается в initialize'
assert hasattr(ProcessManagerProcess, '_setup_state_store'), 'хук не добавлен'
print('1.1 OK')
"

# После задачи 1.3 — базовый smoke
python -c "
from multiprocess_prototype.backend.processes.process_manager.state_store_config import build_validation_rules, build_throttle_rules
vr = build_validation_rules()
tr = build_throttle_rules()
assert 'cameras.*.config.fps' in vr
assert any('actual_fps' in k for k in tr)
print('1.3 config OK')
"

# После задачи 1.3 — StateStoreManager создаётся с пустым app_config
python -c "
from multiprocess_prototype.state_store.manager.state_store_manager import StateStoreManager
from multiprocess_prototype.state_store.bootstrap import build_initial_state
from multiprocess_prototype.state_store.middleware.validation import ValidationMiddleware
from multiprocess_prototype.state_store.middleware.throttle import ThrottleMiddleware
from multiprocess_prototype.backend.processes.process_manager.state_store_config import build_validation_rules, build_throttle_rules
s = build_initial_state({})
mgr = StateStoreManager(initial_state=s)
mgr.use(ValidationMiddleware(build_validation_rules()))
mgr.use(ThrottleMiddleware(build_throttle_rules()))
assert mgr.initialize()
assert mgr.store.get('system.status') == 'initializing'
mgr.shutdown()
print('1.3 StateStoreManager OK')
"

# Все существующие тесты state_store (не должны быть сломаны)
pytest multiprocess_prototype/state_store/tests/test_state_store_manager.py -v

# Полный прогон новых тестов
pytest multiprocess_prototype/tests/unit/test_state_store_config.py multiprocess_prototype/tests/unit/test_process_manager_app.py multiprocess_prototype/tests/integration/test_state_store_integration.py -v

# Структурная валидация (должна пройти без изменений)
python scripts/validate.py
```
