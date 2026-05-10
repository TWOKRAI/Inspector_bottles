# Дизайн: Единое связанное хранилище данных (StateStore)

**Дата:** 2026-04-23
**Статус:** DRAFT — на согласование
**Фаза:** Phase 4 (Data Unification)

---

## 1. Проблема

Данные системы разбросаны по 6 несвязанным хранилищам:

```
GUI RegistersManager ──── плоские поля (fps, color_range)
ConfigStore (SRM) ──────── статичные конфиги (read-only после старта)
RecipeManager ──────────── снимки GUI-регистров (не backend!)
CameraRegistry ────────── runtime-статусы (fps, drops)
SettingsYamlStore ──────── профили (camera_count)
vision_pipeline dict ───── иерархия камер→регионов→обработок (в backend)
```

**Следствия:**
- GUI не знает, применил ли Backend настройку
- Backend не знает, что GUI считает текущим значением
- Рецепт = снимок GUI, а не реального состояния системы
- Профиль влияет только при старте, runtime-переключение невозможно
- Нет единого места для запроса «текущий fps камеры 0»

---

## 2. Иерархическая модель данных

### 2.1 Дерево состояния

Все данные системы — единое дерево. Каждый узел адресуется точечным путём:

```
root
├── system                              # Глобальное состояние
│   ├── profile: "production"           # Активный профиль
│   ├── status: "running"               # running | paused | stopping
│   └── uptime: 12345.6                 # Секунды с момента старта
│
├── cameras                             # Dict[camera_id, CameraState]
│   ├── 0                               # Камера 0
│   │   ├── config                      # Конфигурация (из профиля + рецепта)
│   │   │   ├── camera_type: "webcam"
│   │   │   ├── fps: 30
│   │   │   ├── device_id: 0
│   │   │   ├── resolution_width: 640
│   │   │   └── resolution_height: 480
│   │   │
│   │   ├── state                       # Runtime-состояние (только чтение для GUI)
│   │   │   ├── status: "running"       # running | stopped | error | unresponsive
│   │   │   ├── actual_fps: 28.5        # Измеренный FPS
│   │   │   ├── drops_count: 12         # Пропущенные кадры
│   │   │   ├── last_frame_seq: 4521    # Последний seq_id
│   │   │   └── last_heartbeat: 1714...
│   │   │
│   │   └── regions                     # Dict[region_name, RegionState]
│   │       ├── roi_left
│   │       │   ├── rect: {x:0, y:0, w:320, h:480}
│   │       │   ├── enabled: true
│   │       │   ├── sort_order: 0
│   │       │   └── processing          # Цепочка обработки
│   │       │       ├── nodes           # Dict[node_id, NodeState]
│   │       │       │   ├── color_detect_1
│   │       │       │   │   ├── operation_ref: "color_detection"
│   │       │       │   │   ├── enabled: true
│   │       │       │   │   ├── params
│   │       │       │   │   │   ├── color_lower: [10, 20, 30]
│   │       │       │   │   │   ├── color_upper: [100, 200, 255]
│   │       │       │   │   │   ├── min_area: 200
│   │       │       │   │   │   └── max_area: 10000
│   │       │       │   │   └── inputs: [{source:"frame", ...}]
│   │       │       │   │
│   │       │       │   └── blur_1
│   │       │       │       ├── operation_ref: "gaussian_blur"
│   │       │       │       ├── enabled: true
│   │       │       │       ├── params
│   │       │       │       │   └── kernel_size: 5
│   │       │       │       └── inputs: [{source:"color_detect_1"}]
│   │       │       │
│   │       │       └── chain_order: ["color_detect_1", "blur_1"]
│   │       │
│   │       └── roi_right
│   │           └── ... (аналогично)
│   │
│   └── 1                               # Камера 1
│       └── ... (аналогично)
│
├── renderer                            # Настройки визуализации
│   ├── config
│   │   ├── show_original: false
│   │   ├── show_bbox: true
│   │   ├── show_contours: true
│   │   ├── show_mask_overlay: true
│   │   └── overlay_alpha: 0.3
│   └── state
│       ├── status: "running"
│       └── render_fps: 24.8
│
├── robot                               # Робот-отбраковщик
│   ├── config
│   │   └── reject_delay: 0.5
│   └── state
│       ├── status: "running"
│       └── reject_count: 42
│
├── database                            # Хранилище детекций
│   ├── config
│   │   ├── path: "database/inspector.db"
│   │   └── batch_size: 50
│   └── state
│       ├── status: "running"
│       └── total_records: 12345
│
└── recipes                             # Именованные снимки config-ветвей
    ├── _active: "recipe_production"    # Текущий рецепт (или null)
    ├── _dirty: true                    # Есть ли несохранённые изменения
    └── slots
        ├── recipe_production: {...}    # Снимок всех config-ветвей
        └── recipe_debug: {...}
```

### 2.2 Разделение config / state

Ключевое архитектурное решение — **каждый узел разделён на два поддерева:**

| Ветвь | Кто пишет | Кто читает | Персистентность |
|-------|-----------|-----------|-----------------|
| `config` | GUI, Recipe, Profile | Backend, GUI | YAML (рецепты, профили) |
| `state` | Backend (процессы) | GUI, Monitor | Нет (runtime only) |

**Правило:** GUI НИКОГДА не пишет в `state`, Backend НИКОГДА не пишет в `config`.
Это устраняет конфликты записи без необходимости блокировок.

### 2.3 Адресация через точечные пути

```python
# Примеры путей:
"cameras.0.config.fps"                                    # → 30
"cameras.0.regions.roi_left.processing.nodes.blur_1.params.kernel_size"  # → 5
"cameras.0.state.actual_fps"                              # → 28.5
"renderer.config.show_bbox"                               # → True
"recipes._dirty"                                          # → True

# Wildcards для подписки:
"cameras.0.config.*"                  # Любое изменение конфига камеры 0
"cameras.*.state.status"              # Статус любой камеры
"cameras.0.regions.*.processing.**"   # Любые изменения обработки в любом регионе камеры 0
"**"                                  # Все изменения (для логирования)
```

---

## 3. Архитектура StateStore

### 3.1 Где живёт StateStore

```
┌─────────────────────────────────────────────────────────────────┐
│                    ProcessManagerProcess                         │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │                    StateStore                            │    │
│  │                                                         │    │
│  │  ┌──────────┐  ┌──────────────┐  ┌────────────────┐    │    │
│  │  │ TreeStore │  │ Subscriptions│  │ Persistence    │    │    │
│  │  │ (данные)  │  │ (подписки)   │  │ (YAML/SQLite)  │    │    │
│  │  └──────────┘  └──────────────┘  └────────────────┘    │    │
│  │                                                         │    │
│  │  ┌──────────────────────────────────────────────────┐   │    │
│  │  │              StateStoreRouter                     │   │    │
│  │  │  (принимает IPC, диспатчит подписчикам)          │   │    │
│  │  └──────────────────────────────────────────────────┘   │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                 │
│           ▲ IPC (state_update)    │ IPC (state_changed)         │
│           │                       ▼                             │
│  ┌────────┴──────────────────────────────────────────────┐      │
│  │  Camera_0  Camera_1  Processor  Renderer  GUI  Robot  │      │
│  └───────────────────────────────────────────────────────┘      │
└─────────────────────────────────────────────────────────────────┘
```

**StateStore живёт внутри ProcessManagerProcess** — единственный процесс, который:
- Всегда запущен (оркестратор)
- Имеет связь со всеми процессами через SRM
- Уже управляет жизненным циклом процессов

### 3.2 Компоненты

```
StateStore
├── TreeStore                    # Хранение данных
│   ├── _root: Dict              # Вложенный dict (дерево)
│   ├── get(path) → Any          # Чтение по пути
│   ├── set(path, value) → Delta # Запись + возврат дельты
│   ├── get_subtree(path) → Dict # Поддерево как dict
│   ├── merge(path, dict)        # Глубокий merge поддерева
│   └── snapshot() → Dict        # Полный снимок (для рецептов)
│
├── SubscriptionManager          # Управление подписками
│   ├── subscribe(pattern, callback_target) → sub_id
│   ├── unsubscribe(sub_id)
│   ├── match(path) → List[Subscription]  # Кто подписан на этот путь
│   └── _subscriptions: Dict[sub_id, Subscription]
│
├── DeltaDispatcher              # Рассылка изменений
│   ├── dispatch(delta: Delta)   # → match subscribers → send IPC
│   ├── _batch: List[Delta]      # Накопление для batch-отправки
│   └── flush()                  # Отправить batch подписчикам
│
├── PersistenceManager           # Сохранение на диск
│   ├── save_config(path?)       # config-ветви → YAML
│   ├── load_config(path?)       # YAML → config-ветви
│   ├── _debounce_timer          # Не чаще чем раз в N секунд
│   └── _dirty_paths: Set[str]   # Что изменилось с последнего save
│
├── RecipeEngine                 # Рецепты = снимки config-ветвей
│   ├── save_recipe(name)        # snapshot config → recipes.slots.{name}
│   ├── load_recipe(name)        # recipes.slots.{name} → apply to config
│   ├── list_recipes() → List
│   └── delete_recipe(name)
│
├── ValidationLayer              # Валидация перед записью
│   ├── validate(path, value) → Result
│   ├── _schemas: Dict[path_prefix, SchemaBase]  # Pydantic-модели
│   └── register_schema(path_prefix, schema_class)
│
└── StateStoreRouter             # IPC-интерфейс
    ├── handle_state_set(msg)    # Входящий запрос на изменение
    ├── handle_state_get(msg)    # Входящий запрос на чтение
    ├── handle_subscribe(msg)    # Регистрация подписки от процесса
    └── handle_recipe_cmd(msg)   # Команды рецептов
```

### 3.3 Delta (единица изменения)

```python
@dataclass
class Delta:
    path: str              # "cameras.0.config.fps"
    old_value: Any         # 25
    new_value: Any         # 30
    source: str            # "gui" | "camera_0" | "recipe" | "profile"
    timestamp: float       # time.monotonic()
    transaction_id: str    # UUID — группировка связанных изменений
```

---

## 4. Протокол взаимодействия

### 4.1 GUI меняет настройку

```
GUI: пользователь двигает слайдер FPS → 30
  │
  ├─[1] StateProxy.set("cameras.0.config.fps", 30, source="gui")
  │     └─ IPC: state_set → ProcessManager
  │
  ├─[2] StateStore.handle_state_set()
  │     ├─ ValidationLayer.validate("cameras.0.config.fps", 30)
  │     │   └─ FieldMeta: min=1, max=120 → OK
  │     ├─ TreeStore.set("cameras.0.config.fps", 30)
  │     │   └─ Delta(path="cameras.0.config.fps", old=25, new=30, source="gui")
  │     └─ DeltaDispatcher.dispatch(delta)
  │
  ├─[3] Подписчики получают state_changed:
  │     ├─ CameraProcess (подписан на "cameras.0.config.*")
  │     │   └─ CameraService.set_fps(30)
  │     │       └─ [4] StateProxy.set("cameras.0.state.actual_fps", 29.8, source="camera_0")
  │     │           └─ → StateStore → DeltaDispatcher
  │     │
  │     ├─ GUI (подписан на "cameras.0.state.actual_fps")
  │     │   └─ fps_label.setText("FPS: 29.8")  ← подтверждение!
  │     │
  │     └─ RecipeEngine (подписан на "cameras.*.config.**")
  │         └─ recipes._dirty = true
  │
  └─[5] PersistenceManager (debounced, 2s)
        └─ save_config() → YAML
```

**Ключевое отличие от текущей схемы:** GUI получает **подтверждение** через `state.actual_fps`.

### 4.2 Загрузка рецепта

```
GUI: пользователь выбирает "recipe_production"
  │
  ├─[1] StateProxy.recipe_load("recipe_production")
  │     └─ IPC: recipe_cmd → ProcessManager
  │
  ├─[2] RecipeEngine.load_recipe("recipe_production")
  │     ├─ snapshot = TreeStore.get("recipes.slots.recipe_production")
  │     │
  │     ├─ transaction_id = uuid4()  ← группировка всех изменений
  │     │
  │     └─ Для каждого пути в snapshot:
  │         TreeStore.set("cameras.0.config.fps", 30, tx=transaction_id)
  │         TreeStore.set("cameras.0.config.camera_type", "webcam", tx=transaction_id)
  │         TreeStore.set("cameras.0.regions.roi_left.rect", {...}, tx=transaction_id)
  │         TreeStore.set("cameras.0.regions.roi_left.processing.nodes.color_1.params", {...})
  │         ... (все config-пути из снимка)
  │
  ├─[3] DeltaDispatcher.flush()  ← batch: все дельты одной пачкой
  │     ├─ CameraProcess: получает пачку изменений → применяет
  │     ├─ ProcessorProcess: получает пачку → rebuild_runnables()
  │     ├─ RendererProcess: получает пачку → обновляет визуализацию
  │     └─ GUI: получает пачку → обновляет все виджеты разом
  │
  └─[4] recipes._active = "recipe_production"
        recipes._dirty = false
```

### 4.3 Backend обновляет состояние

```
CameraProcess: измерил actual FPS
  │
  ├─[1] StateProxy.set("cameras.0.state.actual_fps", 28.5, source="camera_0")
  │     └─ IPC: state_set → ProcessManager
  │
  ├─[2] StateStore: запись в TreeStore
  │     └─ DeltaDispatcher.dispatch()
  │
  └─[3] GUI (подписан на "cameras.0.state.*")
        └─ fps_widget.update(28.5)
```

---

## 5. StateProxy — клиент в каждом процессе

Каждый процесс получает **StateProxy** — лёгкий клиент для работы с StateStore через IPC.

```python
class StateProxy:
    """Клиент StateStore. Живёт в каждом процессе."""

    def __init__(self, process_name: str, router: RouterManager):
        self._process_name = process_name
        self._router = router
        self._local_cache: Dict[str, Any] = {}     # Кэш подписанных путей
        self._subscriptions: Dict[str, Callable] = {}

    # --- Запись ---
    def set(self, path: str, value: Any, source: str = None):
        """Отправить изменение в StateStore."""
        msg = {"type": "state_set", "path": path, "value": value,
               "source": source or self._process_name}
        self._router.send_to("process_manager", msg, channel="system")

    def merge(self, path: str, data: dict, source: str = None):
        """Глубокий merge поддерева."""
        msg = {"type": "state_merge", "path": path, "data": data,
               "source": source or self._process_name}
        self._router.send_to("process_manager", msg, channel="system")

    # --- Чтение ---
    def get(self, path: str) -> Any:
        """Чтение из локального кэша (если подписан) или запрос в StateStore."""
        if path in self._local_cache:
            return self._local_cache[path]
        # Синхронный запрос (request-response)
        return self._request("state_get", path)

    def get_subtree(self, path: str) -> dict:
        """Получить поддерево как dict."""
        return self._request("state_get_subtree", path)

    # --- Подписка ---
    def subscribe(self, pattern: str, callback: Callable[[Delta], None]):
        """Подписаться на изменения по паттерну."""
        sub_id = f"{self._process_name}:{pattern}"
        self._subscriptions[sub_id] = callback
        msg = {"type": "state_subscribe", "pattern": pattern,
               "subscriber": self._process_name}
        self._router.send_to("process_manager", msg, channel="system")

    def on_state_changed(self, delta_dict: dict):
        """Вызывается при получении state_changed от StateStore."""
        delta = Delta(**delta_dict)
        self._local_cache[delta.path] = delta.new_value
        for pattern, callback in self._subscriptions.items():
            if _path_matches(pattern.split(":", 1)[1], delta.path):
                callback(delta)

    # --- Рецепты ---
    def recipe_save(self, name: str):
        self._router.send_to("process_manager",
            {"type": "recipe_cmd", "action": "save", "name": name},
            channel="system")

    def recipe_load(self, name: str):
        self._router.send_to("process_manager",
            {"type": "recipe_cmd", "action": "load", "name": name},
            channel="system")
```

### 5.1 StateProxy в GUI (Qt-safe)

```python
class GuiStateProxy(StateProxy):
    """Qt-safe версия StateProxy. Все callbacks через QMetaObject."""

    def __init__(self, process_name, router, qt_receiver: QObject):
        super().__init__(process_name, router)
        self._qt_receiver = qt_receiver

    def on_state_changed(self, delta_dict: dict):
        """Перенаправляет callback в Qt main thread."""
        QMetaObject.invokeMethod(
            self._qt_receiver,
            "_on_state_delta",
            Qt.QueuedConnection,
            Q_ARG("QVariant", delta_dict)
        )
```

---

## 6. Подписки (Subscription Patterns)

### 6.1 Синтаксис паттернов

| Паттерн | Что матчит | Пример |
|---------|-----------|--------|
| `cameras.0.config.fps` | Точное совпадение | Только fps камеры 0 |
| `cameras.0.config.*` | Любое поле на 1 уровень | fps, camera_type, device_id |
| `cameras.*.state.status` | Любая камера, конкретное поле | Статус всех камер |
| `cameras.0.regions.**` | Все потомки рекурсивно | Любые изменения регионов камеры 0 |
| `**.config.**` | Любые config-изменения | Глобально |

### 6.2 Таблица стандартных подписок

| Процесс | Подписка | Реакция |
|---------|---------|---------|
| `camera_0` | `cameras.0.config.*` | Применить настройки камеры |
| `processor_0` | `cameras.0.regions.**` | `rebuild_runnables()` |
| `processor_0` | `cameras.0.config.resolution_*` | Пересоздать SHM при смене разрешения |
| `renderer` | `renderer.config.*` | Обновить режим рендера |
| `renderer` | `cameras.*.config.resolution_*` | Пересоздать output SHM |
| `gui` | `cameras.*.state.*` | Обновить StatusBar, FPS label |
| `gui` | `cameras.*.config.*` | Обновить виджеты (подтверждение) |
| `gui` | `renderer.config.*` | Обновить чекбоксы рендера |
| `gui` | `recipes.*` | Обновить список рецептов, dirty-флаг |
| `database` | `database.config.*` | Реконфигурация SQLite |
| `recipe_engine` | `**.config.**` | `recipes._dirty = true` |
| `persistence` | `**.config.**` | Debounced save → YAML |

### 6.3 Фильтрация по source

Подписчик может фильтровать по источнику изменения:

```python
# Камера: реагировать только на изменения от GUI/Recipe, не от себя самой
proxy.subscribe("cameras.0.config.*",
    callback=self._apply_config,
    exclude_sources=["camera_0"])  # Не реагировать на собственные изменения
```

---

## 7. Транзакции и batch-обновления

### 7.1 Проблема

Загрузка рецепта меняет 50+ путей. Если каждый генерирует отдельное уведомление:
- Processor вызовет `rebuild_runnables()` 50 раз
- GUI перерисует виджеты 50 раз
- Latency-шторм в IPC

### 7.2 Решение: транзакции

```python
# В RecipeEngine:
with state_store.transaction("recipe_load") as tx:
    tx.set("cameras.0.config.fps", 30)
    tx.set("cameras.0.config.camera_type", "webcam")
    tx.set("cameras.0.regions.roi_left.rect", {...})
    # ... 50+ изменений
# → при выходе из with: один batch state_changed со всеми дельтами
```

```python
# Подписчик получает:
def on_state_changed(self, deltas: List[Delta]):
    # deltas = [Delta(...), Delta(...), ...]  все с одним transaction_id
    if any(d.path.endswith(".regions") or "processing" in d.path for d in deltas):
        self.rebuild_runnables()  # Один раз на всю транзакцию
```

### 7.3 Coalescing (сжатие)

Если в одной транзакции путь менялся дважды:
```
set("cameras.0.config.fps", 25)
set("cameras.0.config.fps", 30)
→ Одна Delta(old=original, new=30)  # Промежуточное значение исчезает
```

---

## 8. Рецепты в новой архитектуре

### 8.1 Что такое рецепт

**Рецепт = именованный снимок ВСЕХ config-ветвей дерева.**

```python
recipe = state_store.snapshot(paths=[
    "cameras.*.config",
    "cameras.*.regions",
    "renderer.config",
    "robot.config",
    "database.config",
])
# Результат — dict, повторяющий структуру дерева, но только config-ветви
```

### 8.2 Иерархия рецепта

```yaml
# recipes.slots.recipe_production:
cameras:
  "0":
    config:
      camera_type: webcam
      fps: 30
      device_id: 0
      resolution_width: 640
      resolution_height: 480
    regions:
      roi_left:
        rect: {x: 0, y: 0, width: 320, height: 480}
        enabled: true
        processing:
          nodes:
            color_detect_1:
              operation_ref: color_detection
              enabled: true
              params:
                color_lower: [10, 20, 30]
                color_upper: [100, 200, 255]
                min_area: 200
                max_area: 10000
              inputs:
                - {source: frame, output_port: out, input_port: in}
          chain_order: [color_detect_1]
      roi_right:
        rect: {x: 320, y: 0, width: 320, height: 480}
        enabled: true
        processing:
          nodes:
            blob_1:
              operation_ref: blob_detection
              enabled: true
              params:
                min_blob_area: 500
              inputs:
                - {source: frame, output_port: out, input_port: in}
          chain_order: [blob_1]
  "1":
    config:
      camera_type: hikvision
      fps: 25
      camera_index: 0
    regions:
      full_frame:
        rect: {x: 0, y: 0, width: 1920, height: 1080}
        enabled: true
        processing:
          nodes: {}
          chain_order: []

renderer:
  config:
    show_original: false
    show_bbox: true
    show_contours: true

robot:
  config:
    reject_delay: 0.5
```

### 8.3 Частичные рецепты

Можно сохранить/загрузить только часть дерева:

```python
# Сохранить только настройки обработки камеры 0:
proxy.recipe_save("camera0_processing",
    paths=["cameras.0.regions"])

# Загрузить настройки обработки на камеру 1:
proxy.recipe_load("camera0_processing",
    remap={"cameras.0": "cameras.1"})
```

### 8.4 Dirty-трекинг

```python
# В RecipeEngine:
def on_config_changed(self, delta: Delta):
    if self._active_recipe:
        recipe_value = self._get_recipe_value(self._active_recipe, delta.path)
        if recipe_value != delta.new_value:
            self._dirty_paths.add(delta.path)
            state_store.set("recipes._dirty", True)

# GUI показывает: "Recipe: production*" (звёздочка = есть изменения)
```

---

## 9. Профили в новой архитектуре

### 9.1 Профиль = топология + начальные config

Профиль определяет **сколько** камер/процессоров создавать и **какие** начальные значения.

```yaml
# settings_profiles.yaml → при старте загружается в StateStore
profiles:
  production:
    topology:
      camera_count: 4
      camera_source_type: hikvision
      worker_pool_size: 2
      display_enabled: true
    defaults:
      ring_buffer_size: 5
      shm_budget_mb: 512
```

### 9.2 Runtime profile switch (целевое)

```
GUI: переключить профиль → "production"
  │
  ├─[1] StateProxy.set("system.profile", "production")
  │
  ├─[2] StateStore → ProfileEngine
  │     ├─ Если camera_count изменился:
  │     │   ├─ ProcessManager.stop_processes([camera_2, camera_3, processor_2, processor_3])
  │     │   ├─ ... или create_processes() для новых
  │     │   └─ StateStore: добавить/удалить cameras.2, cameras.3 из дерева
  │     │
  │     └─ Применить defaults через transaction
  │
  └─[3] DeltaDispatcher → уведомить всех
```

**Ограничение v1:** runtime profile switch — Phase 5+. В Phase 4 профиль только при старте.

---

## 10. Валидация

### 10.1 Уровни валидации

```
GUI (widget constraints)
  │  min=1, max=120, step=1
  ▼
StateProxy (быстрая клиентская)
  │  type check, range check
  ▼
StateStore.ValidationLayer (серверная, каноническая)
  │  Pydantic model validate_assignment
  │  Cross-field constraints
  │  Business rules
  ▼
TreeStore.set() → Delta
```

### 10.2 Реестр схем

```python
# При инициализации StateStore:
validation.register_schema("cameras.*.config", CameraConfigSchema)
validation.register_schema("cameras.*.regions.*.rect", RectSchema)
validation.register_schema("cameras.*.regions.*.processing.nodes.*", ProcessingNodeSchema)
validation.register_schema("renderer.config", RendererConfigSchema)

# При set("cameras.0.config.fps", -5):
# → CameraConfigSchema.validate_assignment → FieldMeta(min=1) → REJECT
# → StateProxy получает error response
# → GUI: показать ошибку, откатить виджет
```

---

## 11. Миграция: как перейти от текущей архитектуры

### 11.1 Принцип: обёртка, не переписывание

StateStore **оборачивает** существующие компоненты, а не заменяет:

```
Phase 4a: TreeStore + StateProxy (новый слой поверх существующего)
  └─ RegistersManager внутри GUI продолжает работать
  └─ ConfigStore внутри SRM продолжает работать
  └─ Добавляется синхронизация: RegistersManager ↔ StateStore ↔ ConfigStore

Phase 4b: Процессы переходят на StateProxy
  └─ Вместо apply_register_update() → proxy.subscribe()
  └─ Вместо send_register_update() → proxy.set()

Phase 4c: RecipeManager → RecipeEngine
  └─ Рецепты из снимков GUI → снимки StateStore

Phase 4d: Удаление устаревших прослоек
  └─ RegistersManager → тонкий адаптер над StateProxy
  └─ CameraRegistry → подписки на cameras.*.state.*
```

### 11.2 Обратная совместимость

Во время миграции оба пути работают параллельно:

```python
# Адаптер: RegistersManager → StateProxy
class RegistersStateAdapter:
    """Мост: GUI-виджеты продолжают работать с RegistersManager,
    но изменения проходят через StateStore."""

    def __init__(self, registers_manager, state_proxy):
        self._rm = registers_manager
        self._proxy = state_proxy

        # RegistersManager → StateProxy
        self._rm.subscribe_all(self._on_register_changed)

        # StateProxy → RegistersManager
        self._proxy.subscribe("cameras.*.config.*", self._on_state_changed)
        self._proxy.subscribe("renderer.config.*", self._on_state_changed)

    def _on_register_changed(self, register_name, field_name, value):
        path = self._register_to_path(register_name, field_name)
        self._proxy.set(path, value, source="gui")

    def _on_state_changed(self, delta):
        register_name, field_name = self._path_to_register(delta.path)
        self._rm.set_field_value(register_name, field_name, delta.new_value,
                                 _skip_callback=True)  # Не зацикливать
```

---

## 12. Диаграмма потоков данных (целевое состояние)

```
┌──────────────────────────────────────────────────────────────────────┐
│                                                                      │
│  ┌───────────┐                              ┌───────────────────┐    │
│  │           │   state_set                  │                   │    │
│  │    GUI    │ ─────────────────────────────►│                   │    │
│  │  (PyQt5)  │                              │                   │    │
│  │           │◄──────────────────────────────│    StateStore     │    │
│  │  StateProxy│  state_changed (batch)      │    (в ProcessMgr) │    │
│  │  (Qt-safe) │                             │                   │    │
│  └───────────┘                              │  ┌─────────────┐  │    │
│                                             │  │  TreeStore   │  │    │
│  ┌───────────┐   state_set                  │  │  (dict-дерево)│ │    │
│  │ Camera_0  │ ─────────────────────────────►│  └─────────────┘  │    │
│  │           │  (state.actual_fps,          │                   │    │
│  │  StateProxy│   state.drops_count)        │  ┌─────────────┐  │    │
│  │           │◄──────────────────────────────│  │ Subscriptions│  │    │
│  └───────────┘   state_changed              │  │ (patterns)   │  │    │
│                  (config.fps → apply)       │  └─────────────┘  │    │
│                                             │                   │    │
│  ┌───────────┐   state_set                  │  ┌─────────────┐  │    │
│  │ Processor │ ─────────────────────────────►│  │ RecipeEngine│  │    │
│  │           │  (state.detection_count)     │  │ (snapshots)  │  │    │
│  │  StateProxy│                             │  └─────────────┘  │    │
│  │           │◄──────────────────────────────│                   │    │
│  └───────────┘   state_changed              │  ┌─────────────┐  │    │
│                  (regions.** → rebuild)      │  │ Persistence │  │    │
│                                             │  │ (YAML, dbnc) │  │    │
│  ┌───────────┐                              │  └─────────────┘  │    │
│  │ Renderer  │◄──────────────────────────────│                   │    │
│  │  StateProxy│  state_changed              │  ┌─────────────┐  │    │
│  └───────────┘  (renderer.config.*)         │  │ Validation  │  │    │
│                                             │  │ (Pydantic)   │  │    │
│                                             │  └─────────────┘  │    │
│                                             └───────────────────┘    │
│                                                                      │
│  ═══════════════════════ SHM (кадры) ══════════════════════════════  │
│  (SHM НЕ проходит через StateStore — остаётся zero-copy как есть)   │
└──────────────────────────────────────────────────────────────────────┘
```

**Важно:** SHM для кадров (Ring Buffer) **не проходит** через StateStore.
StateStore управляет только **метаданными и конфигурацией**, не бинарными данными.

---

## 13. Что НЕ входит в StateStore

| Данные | Почему не входит | Где остаётся |
|--------|-----------------|-------------|
| Кадры (numpy arrays) | Слишком большие, zero-copy SHM | Ring Buffer через SHM |
| IPC-очереди | Транспорт, не данные | SRM.QueueRegistry |
| OS Events (stop, pause) | Сигналы, не состояние | SRM.EventManager |
| Логи | Поток, не состояние | LoggerManager |
| Детекции (bbox, area) | Высокочастотный поток → SQLite | DatabaseProcess |

---

## 14. Резюме ключевых решений

| Решение | Обоснование |
|---------|-------------|
| StateStore в ProcessManager | Единственный always-on процесс с доступом ко всем |
| config/state разделение | Устраняет write-конфликты GUI↔Backend без блокировок |
| Точечные пути + wildcards | Гибкая адресация иерархии любой глубины |
| Delta + transaction | Batch-уведомления при загрузке рецепта (50+ изменений → 1 batch) |
| StateProxy в каждом процессе | Dict at Boundary сохраняется (IPC = dict) |
| Validation через Pydantic | Переиспользование существующих SchemaBase моделей |
| Обёртка, не переписывание | Постепенная миграция без big-bang рефакторинга |
| Рецепт = снимок config-ветвей | Рецепт отражает реальное состояние, не только GUI |

---

## 15. Открытые вопросы

- [ ] **Consistency:** eventual (текущий подход) или strong (ack от StateStore перед обновлением GUI)?
- [ ] **Кэширование в StateProxy:** TTL-based или invalidation-based?
- [ ] **Конфликты:** что если GUI и Backend одновременно меняют один config-путь?
      (Текущее решение: GUI владеет config, Backend владеет state — конфликтов нет)
- [ ] **Масштаб state-дерева:** при 8 камерах × 10 регионов × 5 узлов = 400+ узлов обработки.
      Нужен ли lazy-loading поддеревьев?
- [ ] **Персистентность state:** нужно ли сохранять runtime-state (fps, drops) для аналитики?
