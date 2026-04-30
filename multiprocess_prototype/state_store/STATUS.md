# state_store — Статус подключения (Фаза 1)

## Текущий статус: STABLE (подключён в ProcessManagerProcessApp)

**Дата:** 2026-04-30  
**Статус Фазы 1:** COMPLETE  
**Коммиты production:** 6713ada, 45ee030, 204d15e  
**Коммиты тестов:** 88ec8e6 (40 unit), d66060f (14 integration)

---

## Что реализовано в Фазе 1

- [x] Пустой хук `_setup_state_store()` добавлен в `ProcessManagerProcess` (базовый класс)
- [x] `ProcessManagerProcessApp._setup_state_store()` создаёт и инициализирует `StateStoreManager` с начальным состоянием и middleware
- [x] Начальное состояние собирается функцией `build_initial_state()` из `app_config` (Dict at Boundary)
- [x] Доменные правила валидации и throttle изолированы в `state_store_config.py`
- [x] `StateStoreManager` регистрирует 7 IPC-команд в `RouterManager`
- [x] Graceful shutdown: `StateStoreManager.shutdown()` вызывается перед `super().shutdown()`
- [x] `CameraProcess` может использовать `StateProxy` для подписки на изменения состояния

---

## Архитектура подключения

### 1. Создание StateStoreManager

**Файл:** `multiprocess_prototype/backend/processes/process_manager/process.py`  
**Метод:** `ProcessManagerProcessApp._setup_state_store()`

StateStoreManager создаётся в переопределённом методе хука `_setup_state_store()`, вызываемом из `ProcessManagerProcess.initialize()` строго **до** `_create_processes_from_config()` — чтобы StateStoreManager был готов принимать команды от дочерних процессов при их старте.

**Порядок lifecycle:**
```
ProcessManagerProcessApp.initialize()
    ↓
super().initialize() → ProcessManagerProcess
    ↓
    _setup_topology_manager()
    ↓
    _setup_state_store()          ← ВСЕ процессы: пустой хук pass (базовый класс)
                                      Прототип: создаёт StateStoreManager
    ↓
    _register_builtin_commands()
    ↓
    _create_processes_from_config()  ← дочерние процессы стартуют
```

### 2. Передача начального состояния

**Путь данных:** AppConfig → `app_config_dict` → конфиг ProcessManagerApp → `build_initial_state()`

**Файл:** `multiprocess_prototype/main.py`  
Передаётся `app_config_dict` (результат `app.model_dump()`) в конфиг ProcessManagerApp через `orchestrator_config` в `SystemLauncher`. В `_setup_state_store()` извлекается через `self.get_config("app_config")`.

**Формат дерева состояния:**
```python
{
    "cameras": {str(camera_id): {config, state, regions}},
    "renderer": {config, state},
    "robot": {...},
    "database": {...},
    "system": {status: "initializing", ...}
}
```

**Файл bootstrap:** `multiprocess_prototype/state_store/bootstrap.py`  
Функция `build_initial_state(app_config: dict) -> dict` собирает начальное дерево из переданного конфига.

### 3. Подключённые middleware

**Валидация:** `ValidationMiddleware` с правилами из `build_validation_rules()`
- Паттерны путей: `"cameras.*.config.fps"`, `"cameras.*.state.status"` и т.д.
- Каждый путь задаёт тип, min/max, enum
- Блокирует невалидные значения перед сохранением в StateStore

**Throttle:** `ThrottleMiddleware` с правилами из `build_throttle_rules()`
- Высокочастотные метрики (`actual_fps`, `drops_count`) ограничены по интервалу
- `last_frame_seq` полностью заблокирована (0 = блокировка)
- Остальные пути проходят без ограничения

**Файл конфига:** `multiprocess_prototype/backend/processes/process_manager/state_store_config.py`  
Содержит две функции для изоляции доменной логики от инфраструктуры.

### 4. Использование StateProxy в процессах

**Файл:** `multiprocess_prototype/backend/processes/camera/process.py` (строки 63-81)

Процессы создают `StateProxy(process_name, router=self.router_manager)` и используют для:
- `proxy.subscribe(path, callback, exclude_self=True)` — подписаться на изменения
- `proxy.set(path, value)` — установить значение
- `proxy.get(path)` — прочитать значение из локального кэша

StateProxy отправляет команды `state.set`, `state.subscribe` и т.д. в адрес `_PROCESS_MANAGER` (хардкод строка 27). После подключения StateStoreManager эти команды маршрутизируются и обрабатываются корректно.

**Регистрация обработчика дельт:** после создания StateProxy вызывается:
```python
router.register_message_handler("state.changed", proxy.on_state_changed)
```
Это позволяет StateProxy получать уведомления об изменениях состояния от StateStoreManager и обновлять локальный кэш.

### 5. Что НЕ подключено в Фазе 1

- **devtools** (инспектор дерева в реальном времени) — будет в Фазе 2
- **health checks** (периодическая валидация целостности) — будет в Фазе 2
- **persistence** (сохранение состояния на диск) — будет в Фазе 3
- **recipe_adapter** (мост RecipeManager → StateStore) — GUI-сторона, отдельно
- **registers_adapter** (мост RegistersManager → StateStore) — GUI-сторона, отдельно
- **camera_state_adapter** (синхронизация CameraProcess.state с StateStore) — пока manual sync

---

## Верификация Фазы 1

Запустить в корне проекта следующие команды для проверки корректности подключения:

### Структурная валидация
```bash
python scripts/validate.py
```
Проверяет импорты, циклы зависимостей, соответствие конфигов схемам.

### Существующие unit-тесты state_store
```bash
pytest multiprocess_prototype/state_store/tests/ -v
```
Исходные тесты StateStoreManager, DeltaDispatcher и middleware (не должны быть сломаны).

### Новые unit-тесты доменной конфигурации
```bash
pytest multiprocess_prototype/tests/unit/test_state_store_config.py -v
```
Проверяет структуру правил валидации и throttle.

### Новые unit-тесты создания ProcessManagerProcessApp
```bash
pytest multiprocess_prototype/tests/unit/test_process_manager_app.py -v
```
Проверяет создание StateStoreManager без IPC, идемпотентность `_setup_state_store()`, корректный shutdown.

### Интеграционный тест end-to-end
```bash
pytest multiprocess_prototype/tests/integration/test_state_store_integration.py -v
```
Проверяет StateProxy ↔ StateStoreManager через MockRouter, доставку дельт, кэширование в proxy.

### Smoke-импорты (быстрая проверка)
```bash
# Проверить что ProcessManagerProcessApp создаётся без ошибок
python -c "from multiprocess_prototype.backend.processes.process_manager.process import ProcessManagerProcessApp; print('OK')"

# Проверить что bootstrap работает с пустым app_config
python -c "from multiprocess_prototype.state_store.bootstrap import build_initial_state; s = build_initial_state({}); assert 'system' in s; print('bootstrap OK')"

# Проверить что доменные правила возвращают dict
python -c "from multiprocess_prototype.backend.processes.process_manager.state_store_config import build_validation_rules, build_throttle_rules; vr = build_validation_rules(); tr = build_throttle_rules(); assert 'cameras.*.config.fps' in vr; print('config OK')"
```

---

## Что осталось для Фазы 2

### 1. Router-контракт: минимальные методы в RouterManager

StateProxy ожидает от router следующие методы (должны быть явно задокументированы):
- `register_message_handler(channel: str, handler: callable)` — регистрация обработчика
- `send_async(target: str, msg: dict)` — отправка с fire-and-forget
- `send(target: str, msg: dict) -> dict` — синхронная отправка с ответом (для StateProxy.subscribe)

Сейчас StateProxy работает, но контракт не явный — в Фазе 2 добавить `IRouter` интерфейс и синхронный `send` в `TestRouter`.

### 2. Конфигурируемый адрес сервера StateStore

**Текущее состояние:** StateProxy имеет хардкод `_PROCESS_MANAGER = "ProcessManager"` (строка 27 state_proxy.py).

**Проблема:** при вынесении StateProxy в отдельный пакет (не прототип-специфичный) этот хардкод станет несовместимым с другими приложениями.

**Решение (Фаза 2):** сделать адрес конфигурируемым через конструктор или глобальную переменную (`StateProxy(server_target="CustomProcessManager")`).

### 3. Авто-регистрация обработчика state.changed в базовом ProcessModule

**Текущее состояние:** каждый процесс должен явно вызвать:
```python
self.router_manager.register_message_handler("state.changed", proxy.on_state_changed)
```

**Решение (Фаза 2):** добавить в `ProcessModule.initialize()` автоматическую регистрацию если `StateProxy` создан. Или создавать StateProxy в базовом классе как опциональный атрибут.

### 4. Маршрутизация state.changed по targets (вместо broadcast)

**Текущее состояние:** StateStoreManager отправляет дельты через `router.send("state.changed", delta_msg)` — broadcast всем подписчикам.

**Оптимизация (Фаза 2):** использовать `msg["targets"]` в delta_msg для отправки только процессам, которые подписались на конкретный путь (exclude_self реализуется на сервере).

### 5. exclude_self: реализация на сервере вместо StateProxy

**Текущее состояние:** `StateProxy.subscribe(..., exclude_self=True)` передаёт флаг серверу, но обработка происходит на клиенте (StateProxy проверяет `msg["source"]`).

**Решение (Фаза 2):** переместить логику исключения в `DeltaDispatcher` на стороне StateStoreManager (более эффективно, логика в одном месте).

---

## Известные проблемы и ограничения

- **Нет persistence:** состояние теряется при перезагрузке процесса. Будет добавлено в Фазе 3.
- **Нет health checks:** StateStore не проверяет целостность дерева. Будет в Фазе 2.
- **StateProxy кэширует дельты в памяти:** нет синхронизации с диском. Нормально для текущей архитектуры.
- **Высокочастотные метрики throttlируются жёстко:** можно сделать throttle адаптивным в зависимости от нагрузки (будущее улучшение).

---

## Таблица статусов компонентов

| Компонент | Статус | Примечание |
|-----------|--------|-----------|
| StateStoreManager | ✅ ПОДКЛЮЧЁН | Полная функциональность с middleware |
| Bootstrap из app_config | ✅ ПОДКЛЮЧЁН | Dict at Boundary; работает с {} |
| ValidationMiddleware | ✅ ПОДКЛЮЧЁН | Правила в state_store_config.py |
| ThrottleMiddleware | ✅ ПОДКЛЮЧЁН | Высокочастотные метрики ограничены |
| StateProxy в CameraProcess | ✅ РАБОТАЕТ | Используется для subscribe/set/get |
| Graceful shutdown | ✅ РЕАЛИЗОВАНО | StateStoreManager.shutdown() вызывается перед super() |
| health / devtools | ❌ НЕ ПОДКЛЮЧЕНО | Планируется на Фазе 2 |
| persistence | ❌ НЕ ПОДКЛЮЧЕНО | Планируется на Фазе 3 |
| recipe_adapter | ❌ НЕ ПОДКЛЮЧЕНО | GUI-сторона; вне scope ProcessManager |
| registers_adapter | ❌ НЕ ПОДКЛЮЧЕНО | GUI-сторона; вне scope ProcessManager |

---

## История этапов

| Дата | Что сделано | Фаза |
|------|-------------|------|
| 2026-03-XX | StateStoreManager, middleware, bootstrap написаны | 0 (design) |
| 2026-04-30 | Фаза 1: хук в базовом классе, _setup_state_store() в прототипе, 40 unit + 14 int тестов | 1 |
| TBD | Фаза 2: devtools, router-контракт, health, конфиг server_target | 2 |
| TBD | Фаза 3: persistence, снимки на диск | 3 |

---

## Ссылки

- **Разведка:** `multiprocess_prototype/plans/phase1_tasks.md` § 1.1-1.13
- **Дизайн:** `multiprocess_prototype/plans/phase1_tasks.md` § 2.1-2.5
- **Tasklist:** `multiprocess_prototype/plans/phase1_tasks.md` § 3 (задачи 1.1-1.6)
- **Риски:** `multiprocess_prototype/plans/phase1_tasks.md` § 4
- **Code:** `multiprocess_prototype/backend/processes/process_manager/process.py`
- **Config:** `multiprocess_prototype/backend/processes/process_manager/state_store_config.py`
- **Bootstrap:** `multiprocess_prototype/state_store/bootstrap.py`
