# План: Phase 4 — Единое связанное хранилище данных (StateStore)

**Дата:** 2026-04-23
**Обновлён:** 2026-04-23 (v7 — ALL PHASES DONE, 497 тестов)
**Статус:** ✅ COMPLETE
**Статус:** ✅ COMPLETE
**Дизайн:** [STATE_STORE_DESIGN.md](STATE_STORE_DESIGN.md)
**Оценка:** ~35 файлов, 8 фаз, ~3200 строк нового кода

---

## Обзор

Переход от 6 разрозненных хранилищ к единому реактивному дереву состояния.
Все данные системы — единое дерево с подпиской на изменения через точечные пути.

**Принцип:** сначала строим правильную модель данных в прототипе,
потом извлекаем универсальные части (TreeStore, SubscriptionManager, StateProxy) во фреймворк.

**Архитектурные вдохновения:**
- **Redux** — единый store, middleware pipeline, actions (Delta), selectors
- **MobX** — реактивные подписки, computed values, fine-grained updates
- **ROS Parameter Server** — иерархические параметры, pub/sub, namespace-based
- **Zustand** — минималистичный API, subscribe с selector
- **Elm Architecture** — однонаправленный поток данных, предсказуемость

**Разделение ответственности:**
- **Фреймворк (потом):** TreeStore, Delta, SubscriptionManager, StateProxy, PersistenceManager, Middleware — универсальные
- **Прототип (сейчас):** StateStoreManager, RecipeEngine, ValidationLayer, конкретные схемы — app-specific

---

## Зависимости между фазами

```
Phase 4a: Core (TreeStore + Delta + Subscriptions)                    ✅ DONE
    │
    ├──► Phase 4b: IPC-интеграция (StateStoreManager + StateProxy)    ✅ DONE
    │       │
    │       ├──► Phase 4b+: Middleware + Throttle + Validation        ✅ DONE (97 тестов)
    │       │       │
    │       │       ├──► Phase 4c: Backend-миграция                   ✅ DONE (41 тестов)
    │       │       │
    │       │       └──► Phase 4d: GUI-миграция                       ✅ DONE (35 тестов)
    │       │
    │       └──► Phase 4e: Persistence + Recipes                      ✅ DONE (36 тестов)
    │
    └──► Phase 4f: Cleanup (удаление устаревших прослоек)             ✅ DONE (42 теста)
              │
              └──► Phase 4g: Advanced (Selectors + DevTools + Health)  ✅ DONE (78 тестов)
```

Phase 4a — фундамент. 4b зависит от 4a. 4b+ зависит от 4b — middleware перед миграцией.
4c и 4d параллельны, оба зависят от 4b+. 4e может начаться после 4b. 4f — после 4c+4d.
4g — финальный слой, после стабилизации.

---

## Phase 4a — Core: TreeStore + Delta + Subscriptions ✅ DONE

**Статус:** Выполнено. 127 тестов.

| Task | Что | Тесты | Статус |
|------|-----|-------|--------|
| 4a.1 | TreeStore — иерархическое dict-хранилище | 43 | ✅ |
| 4a.2 | Delta + Transaction + MISSING sentinel | 31 | ✅ |
| 4a.3 | SubscriptionManager — glob-style подписки | 42 | ✅ |
| 4a.4 | Интеграция core + публичный API | 11 | ✅ |

---

## Phase 4b — IPC-интеграция ✅ DONE

**Статус:** Выполнено. 89 тестов (216 total).

| Task | Что | Тесты | Статус |
|------|-----|-------|--------|
| 4b.1 | StateStoreManager + DeltaDispatcher | 36 | ✅ |
| 4b.2 | StateProxy + GuiStateProxy | 42 | ✅ |
| 4b.3 | Bootstrap — начальное дерево из AppConfig | 12 | ✅ (в рамках 4b.2) |

---

## Phase 4b+ — Middleware + Throttle + Validation ✅ DONE

**Статус:** Выполнено. 97 тестов (313 total).

**Цель:** Расширяемый pipeline обработки state-изменений. Каждый `set()`/`merge()` 
проходит через цепочку middleware: validate → throttle → log → persist → notify.

**Почему до миграции:** Без throttle миграция backend (4c) создаст bottleneck.
Без validation невалидные данные попадут в TreeStore. Дешевле встроить сейчас.

**Архитектурный паттерн:** Express/Redux middleware chain.

```python
# API:
store_manager.use(ValidationMiddleware(schemas))
store_manager.use(ThrottleMiddleware({"**.state.**": 1.0}))
store_manager.use(LoggingMiddleware())

# Внутренний pipeline:
# set("cameras.0.state.fps", 28.5) 
#   → ValidationMiddleware.before_set() → проверка типа/диапазона
#     → ThrottleMiddleware.before_set() → пропустить если <1с с прошлого
#       → TreeStore.set() → Delta
#         → LoggingMiddleware.after_set() → log delta
#           → DeltaDispatcher → подписчики
```

---

### Task 4b+.1 — Middleware pipeline в StateStoreManager
**Уровень:** Senior (Opus)
**Исполнитель:** teamlead
**Цель:** Расширяемая цепочка middleware для обработки state-изменений

**Файлы:**
- `state_store/middleware/__init__.py`
- `state_store/middleware/base.py` — базовый класс + pipeline
- `state_store/tests/test_middleware.py`

**Контракт:**
```python
class StateMiddleware(ABC):
    """Базовый класс middleware для StateStore.
    
    Каждый middleware может:
    - before_set/merge/delete: модифицировать или отклонить операцию
    - after_set/merge/delete: реагировать на успешное изменение
    """
    
    @property
    def name(self) -> str: ...
    
    def before_set(self, path: str, value: Any, source: str, context: dict) -> tuple[bool, Any]:
        """Вызывается ПЕРЕД TreeStore.set().
        
        Returns:
            (proceed, modified_value) — False отменяет операцию.
        """
        return True, value
    
    def after_set(self, delta: Delta, context: dict) -> None:
        """Вызывается ПОСЛЕ успешного TreeStore.set()."""
        pass
    
    # Аналогично: before_merge, after_merge, before_delete, after_delete


class MiddlewarePipeline:
    """Цепочка middleware. Порядок: first registered → first called."""
    
    def __init__(self): ...
    def use(self, middleware: StateMiddleware) -> None: ...
    def run_before_set(self, path, value, source) -> tuple[bool, Any]: ...
    def run_after_set(self, delta) -> None: ...
```

**Интеграция в StateStoreManager:**
```python
# handle_state_set():
proceed, value = self._pipeline.run_before_set(path, value, source)
if not proceed:
    return {"status": "rejected", "path": path}
delta = self._store.set(path, value, source=source)
if delta:
    self._pipeline.run_after_set(delta)
    self._dispatcher.dispatch_single(delta)
```

**Критерии приёмки:**
- [ ] Middleware вызывается в порядке регистрации
- [ ] before_set может отклонить операцию (return False)
- [ ] before_set может модифицировать value
- [ ] after_set получает финальную Delta
- [ ] Пустой pipeline — нулевой overhead
- [ ] 10+ тестов

---

### Task 4b+.2 — ThrottleMiddleware
**Уровень:** Middle+ (Sonnet)
**Исполнитель:** developer
**Цель:** Ограничение частоты обновления high-frequency state (actual_fps, drops)

**Файлы:**
- `state_store/middleware/throttle.py`
- `state_store/tests/test_throttle.py`

**Контракт:**
```python
class ThrottleMiddleware(StateMiddleware):
    """Ограничение частоты обновлений по паттернам путей.
    
    Пример:
        ThrottleMiddleware({
            "**.state.actual_fps": 1.0,    # max 1 раз/сек
            "**.state.drops_count": 2.0,   # max 1 раз/2 сек
            "**.state.last_frame_seq": 0,  # отключить (не передавать через StateStore)
        })
    
    Логика:
    - 0 = полная блокировка (путь не попадает в StateStore)
    - >0 = минимальный интервал в секундах
    - Путь не в правилах = пропускать всегда
    - Последнее значение при throttle сохраняется и отправляется при следующем пропуске
    """
    
    def __init__(self, rules: dict[str, float]): ...
    
    def before_set(self, path, value, source, context):
        """Проверяет throttle-правило для path.
        Если throttled — сохраняет значение, возвращает (False, value)."""
    
    def flush(self) -> list[tuple[str, Any, str]]:
        """Принудительный сброс всех накопленных throttled-значений.
        Вызывается при shutdown."""
```

**Важно:** ThrottleMiddleware использует `time.monotonic()` и glob-matching 
из SubscriptionManager (переиспользуем `_match_pattern`).

**Критерии приёмки:**
- [ ] actual_fps обновления throttled до 1/сек
- [ ] Промежуточные значения не теряются — последнее отправляется при следующем пропуске
- [ ] flush() отправляет все накопленные значения
- [ ] Паттерн "0" блокирует полностью
- [ ] Путь без правил проходит свободно
- [ ] 8+ тестов

---

### Task 4b+.3 — ValidationMiddleware
**Уровень:** Middle+ (Sonnet)
**Исполнитель:** developer
**Цель:** Валидация значений перед записью в TreeStore

**Файлы:**
- `state_store/middleware/validation.py`
- `state_store/tests/test_validation.py`

**Контракт:**
```python
class ValidationMiddleware(StateMiddleware):
    """Валидация значений по схемам путей.
    
    Пример:
        ValidationMiddleware({
            "cameras.*.config.fps": {"type": int, "min": 1, "max": 120},
            "cameras.*.config.camera_type": {"type": str, "enum": ["webcam", "hikvision", "simulator", "file"]},
            "cameras.*.config.resolution_width": {"type": int, "min": 1, "max": 7680},
            "renderer.config.overlay_alpha": {"type": float, "min": 0.0, "max": 1.0},
        })
    
    Правила:
    - type: проверка isinstance
    - min/max: для int/float — диапазон
    - enum: допустимые значения
    - Путь не в правилах = пропускать (не валидировать)
    - Невалидное значение → reject + log warning
    """
    
    def __init__(self, rules: dict[str, dict]): ...
    
    def add_rule(self, pattern: str, rule: dict) -> None:
        """Добавить правило валидации в runtime."""
    
    def before_set(self, path, value, source, context):
        """Валидирует value по правилу для path.
        Невалидное → (False, value) + context['validation_error'] = описание."""
```

**Критерии приёмки:**
- [ ] fps=0 → rejected, fps=30 → accepted
- [ ] camera_type="invalid" → rejected
- [ ] overlay_alpha=1.5 → rejected
- [ ] Путь без правила → всегда accepted
- [ ] Glob-паттерны: `cameras.*.config.fps` матчит `cameras.0.config.fps`
- [ ] context содержит описание ошибки при reject
- [ ] 10+ тестов

---

### Task 4b+.4 — LoggingMiddleware + MetricsMiddleware
**Уровень:** Middle (Sonnet)
**Исполнитель:** developer
**Цель:** Структурированное логирование и сбор метрик state-операций

**Файлы:**
- `state_store/middleware/logging_mw.py`
- `state_store/middleware/metrics.py`
- `state_store/tests/test_logging_metrics.py`

**LoggingMiddleware:**
```python
class LoggingMiddleware(StateMiddleware):
    """Логирование state-изменений.
    
    Уровни:
    - DEBUG: каждый set/merge/delete с path + source
    - INFO: только summary (N changes от source X)
    - WARNING: rejected операции
    
    Фильтрация: exclude_patterns=["**.state.actual_fps"] — не логировать шумные.
    """
    
    def __init__(self, logger=None, level="DEBUG", exclude_patterns=None): ...
```

**MetricsMiddleware:**
```python
class MetricsMiddleware(StateMiddleware):
    """Сбор метрик для мониторинга StateStore.
    
    Считает:
    - operations_total: {set: N, merge: N, delete: N}
    - operations_rejected: N (throttle или validation)
    - operations_by_source: {"gui": N, "camera_0": N}
    - avg_delta_latency: средний time.monotonic() разброс
    - subscriptions_active: текущее количество
    """
    
    def __init__(self): ...
    
    def get_stats(self) -> dict:
        """Вернуть текущие метрики. Вызывается через IPC state.stats."""
    
    def reset(self) -> None:
        """Сбросить счётчики."""
```

**Критерии приёмки:**
- [ ] LoggingMiddleware логирует set/merge/delete
- [ ] exclude_patterns исключает шумные пути
- [ ] MetricsMiddleware считает операции по типам и источникам
- [ ] get_stats() возвращает snapshot метрик
- [ ] 8+ тестов

---

## Phase 4c — Backend-миграция: процессы → StateProxy ✅ DONE

**Статус:** Выполнено. 41 тест (354 total).

**Цель:** Процессы переходят с  + ручного IPC на StateProxy.
Backend пишет state, подписывается на config.

**Prerequisite:** Phase 4b+ (middleware+throttle должны быть на месте).

| Task | Что | Тесты | Статус |
|------|-----|-------|--------|
| 4c.1 | CameraProcess → StateProxy (dual-mode) | 20 | ✅ |
| 4c.2 | ProcessorProcess → StateProxy (regions + rebuild) | 26 | ✅ |
| 4c.3 | Renderer + Robot + Database → StateProxy | 15 | ✅ |

---

### Task 4c.1 — CameraProcess → StateProxy
**Уровень:** Middle+ (Sonnet)
**Исполнитель:** developer
**Цель:** Камера читает config и пишет state через StateProxy

**Файлы:**
- `backend/processes/camera/process.py` — изменения
- `backend/processes/camera/commands.py` — адаптация build_register_handlers
- `state_store/tests/test_camera_integration.py`

**Что меняется:**

Было (register_update через очередь):
```python
# commands.py: ручные обработчики для каждого поля
register_handlers = {
    "fps": lambda v: service.set_fps({"fps": v}),
    "camera_type": lambda v: cmd_set_camera_type({"camera_type": v}),
    ...
}

# process.py: поллинг в цикле
if data_type == "register_update":
    apply_register_update(msg_dict.get("data") or {}, CAMERA_REGISTER, register_handlers)
```

Стало (StateProxy):
```python
# process.py: подписка на config-ветвь при инициализации
self._state_proxy = StateProxy(f"camera_{self._camera_id}", router=self)
self._state_proxy.subscribe(
    f"cameras.{self._camera_id}.config.*",
    callback=self._on_config_changed,
    exclude_self=True
)

def _on_config_changed(self, deltas: list[Delta]):
    for delta in deltas:
        field = delta.path.rsplit(".", 1)[-1]  # "fps", "camera_type", ...
        handler = self._config_handlers.get(field)
        if handler:
            handler(delta.new_value)

# Запись state (throttled через middleware):
self._state_proxy.set(f"cameras.{self._camera_id}.state.actual_fps", measured_fps)
```

**Обратная совместимость:**
- `apply_register_update` остаётся как fallback до Phase 4f
- CameraProcess принимает И register_update, И state.changed
- Приоритет: state.changed (если StateProxy подключён)

**Критерии приёмки:**
- [ ] GUI меняет fps → StateStore → CameraProcess получает delta → service.set_fps()
- [ ] CameraProcess пишет actual_fps в state → GUI получает (через throttle 1/с)
- [ ] apply_register_update остаётся как fallback
- [ ] Dual-mode: оба пути работают одновременно
- [ ] 5+ тестов

---

### Task 4c.2 — ProcessorProcess → StateProxy
**Уровень:** Senior (Opus)
**Исполнитель:** teamlead
**Цель:** Processor подписывается на regions, вызывает rebuild_runnables при изменении

**Файлы:**
- `backend/processes/processor/process.py` — изменения
- `backend/processes/processor/commands.py` — адаптация
- `state_store/tests/test_processor_integration.py`

**Ключевая сложность:** Processor реагирует на глубокие изменения в дереве регионов.
Подписка на `cameras.{cam_id}.regions.**` — любые изменения в параметрах обработки.

```python
self._state_proxy.subscribe(
    f"cameras.{self._camera_id}.regions.**",
    callback=self._on_regions_changed,
    exclude_self=True
)

def _on_regions_changed(self, deltas: list[Delta]):
    # Transaction: все дельты с одним tx_id → один rebuild
    tx_ids = {d.transaction_id for d in deltas}
    if tx_ids:
        regions = self._state_proxy.get_subtree(
            f"cameras.{self._camera_id}.regions"
        )
        self._rebuild_runnables(regions)
```

**Критерии приёмки:**
- [ ] Изменение params одного узла → rebuild_runnables()
- [ ] Загрузка рецепта (50 дельт в 1 транзакции) → ОДИН rebuild_runnables()
- [ ] Добавление/удаление региона → rebuild
- [ ] Processor пишет detection_count, processing_latency в state
- [ ] 5+ тестов

---

### Task 4c.3 — RendererProcess + RobotProcess + DatabaseProcess → StateProxy
**Уровень:** Middle (Sonnet)
**Исполнитель:** developer
**Цель:** Остальные backend-процессы переходят на StateProxy

**Файлы:**
- `backend/processes/renderer/process.py` — изменения
- `backend/processes/robot/process.py` — изменения
- `backend/processes/database/process.py` — изменения

**Критерии приёмки:**
- [ ] Renderer подписан на `renderer.config.*` и `cameras.*.config.resolution_*`
- [ ] Robot подписан на `robot.config.*`
- [ ] Database подписан на `database.config.*`
- [ ] Каждый пишет свой state (status, метрики)

---

## Phase 4d — GUI-миграция: RegistersManager → StateProxy ✅ DONE

**Статус:** Выполнено. 35 тестов (28 + 7).

**Цель:** GUI использует StateProxy для чтения/записи. RegistersManager становится тонким адаптером.

---

### Task 4d.1 — RegistersStateAdapter: мост RegistersManager ↔ StateProxy
**Уровень:** Senior (Opus)
**Исполнитель:** teamlead
**Цель:** Двунаправленный мост: виджеты работают по-старому, данные идут через StateStore

**Файлы:**
- `state_store/adapters/__init__.py`
- `state_store/adapters/registers_adapter.py`
- `state_store/tests/test_registers_adapter.py`

**Контракт:**
```python
class RegistersStateAdapter:
    """Двунаправленный мост RegistersManager ↔ StateProxy.
    
    Виджеты продолжают вызывать registers_manager.set_field_value()
    → адаптер → state_proxy.set()
    
    StateStore присылает state_changed
    → адаптер → registers_manager.set_field_value(_skip_callback=True)
    → виджеты обновляются через существующие observers
    
    Anti-loop protection:
    - Адаптер отслеживает "я инициировал это изменение" через _pending_paths
    - Изменение от RegistersManager → set path in _pending → proxy.set()
    - state_changed приходит → если path in _pending → skip (это эхо)
    - Иначе → обновить RegistersManager
    """
    
    def __init__(
        self,
        registers_manager: 'RegistersManager',
        state_proxy: 'GuiStateProxy',
        path_mapping: dict[tuple[str, str], str],
    ): ...
    
    def connect(self) -> None: ...
    def disconnect(self) -> None: ...
```

**Почему адаптер, а не переписывание виджетов:**
- 170+ файлов виджетов → переписывать нереально
- Адаптер позволяет мигрировать постепенно
- Новые виджеты пишутся сразу на StateProxy

**Критерии приёмки:**
- [ ] Виджет меняет fps → RegistersManager → Adapter → StateProxy → StateStore → Backend
- [ ] Backend меняет state → StateStore → StateProxy → Adapter → RegistersManager → виджет
- [ ] Нет зацикливания (anti-loop через _pending_paths)
- [ ] 10+ тестов

---

### Task 4d.2 — GuiProcess: интеграция GuiStateProxy
**Уровень:** Middle+ (Sonnet)
**Исполнитель:** developer
**Цель:** Подключить GuiStateProxy в GuiProcess + FrontendLauncher

**Файлы:**
- `backend/processes/gui/process.py` — изменения
- `frontend/launcher.py` — изменения

**Шаги:**
1. Создать GuiStateProxy в GuiProcess.initialize()
2. Передать в FrontendLauncher → FrontendAppContext
3. Создать RegistersStateAdapter в launcher
4. Подписать GUI на `cameras.*.state.*` для StatusBar
5. Подписать GUI на `system.*` для общего статуса

**Критерии приёмки:**
- [ ] StatusBar показывает actual_fps из StateStore
- [ ] При потере heartbeat → cameras.0.state.status = "unresponsive" → StatusBar
- [ ] Все существующие виджеты работают через RegistersStateAdapter
- [ ] Qt thread safety: все callbacks через Qt main thread

---

## Phase 4e — Persistence + Recipes ✅ DONE

**Статус:** Выполнено. 36 тестов (12 + 24).

**Цель:** Config-ветви сохраняются в YAML. Рецепты = snapshot/restore config-ветвей.

---

### Task 4e.1 — PersistenceManager: debounced save
**Уровень:** Middle+ (Sonnet)
**Исполнитель:** developer
**Цель:** Автоматическое сохранение config-ветвей в YAML при изменениях

**Файлы:**
- `state_store/persistence/__init__.py`
- `state_store/persistence/persistence_manager.py`
- `state_store/tests/test_persistence.py`

**Контракт:**
```python
class PersistenceManager:
    """Debounced сохранение config-ветвей на диск.
    
    Реализуется как middleware (PersistenceMiddleware), а не отдельный менеджер.
    Подключается через store_manager.use(PersistenceMiddleware(...))
    
    Правила:
    - **.config.** → dirty → debounce 2с → save YAML
    - **.state.** → НЕ сохранять (runtime only)
    - **.regions.** → dirty → debounce 2с → save YAML (часть конфига)
    - system.* → save немедленно (profile switch)
    """
    
    def __init__(self, store: TreeStore, data_dir: Path, debounce_seconds: float = 2.0): ...
    def save_now(self) -> None: ...
    def load(self) -> None: ...
    
    @property
    def is_dirty(self) -> bool: ...
```

**Формат файлов:**
```
data/
├── state_cameras.yaml    # cameras.*.config + cameras.*.regions
├── state_renderer.yaml   # renderer.config
├── state_robot.yaml      # robot.config
├── state_database.yaml   # database.config
└── state_system.yaml     # system.profile
```

**Критерии приёмки:**
- [ ] Изменение fps → через 2с → state_cameras.yaml обновлён
- [ ] 10 изменений за 1с → один save (debounce)
- [ ] При shutdown → save_now() → всё сохранено
- [ ] При старте → load() → TreeStore содержит последние config'и
- [ ] state-ветви НЕ сохраняются
- [ ] 8+ тестов

---

### Task 4e.2 — RecipeEngine: snapshot/restore через TreeStore
**Уровень:** Senior (Opus)
**Исполнитель:** teamlead
**Цель:** Рецепты как snapshot/restore config-ветвей TreeStore

**Файлы:**
- `state_store/recipes/__init__.py`
- `state_store/recipes/recipe_engine.py`
- `state_store/tests/test_recipe_engine.py`

**Контракт:**
```python
class RecipeEngine:
    """Управление рецептами через TreeStore.
    
    Рецепт = snapshot всех config-ветвей + regions.
    Хранятся в recipes.slots.{name} в TreeStore + YAML на диске.
    """
    
    def save(self, name: str, paths: list[str] | None = None) -> None: ...
    def load(self, name: str, remap: dict[str, str] | None = None) -> None: ...
    def list(self) -> list[str]: ...
    def delete(self, name: str) -> bool: ...
    def get_active(self) -> str | None: ...
    def is_dirty(self) -> bool: ...
    def diff(self, name: str) -> list[tuple[str, Any, Any]]: ...
```

**Критерии приёмки:**
- [ ] save("production") → snapshot config-ветвей → YAML
- [ ] load("production") → одна Transaction → один batch подписчикам
- [ ] Частичный рецепт: save(paths=["cameras.0.regions"])
- [ ] Remap: настройки камеры 0 → камера 1
- [ ] diff() показывает что изменилось
- [ ] is_dirty() = true когда config изменился после загрузки
- [ ] 12+ тестов

---

## Phase 4f — Cleanup: удаление устаревших прослоек ✅ DONE

**Статус:** Выполнено. 42 теста (CameraStateAdapter 27 + RecipeAdapter 15 + обновлённые dual-mode → StateProxy-only).

**Цель:** Убрать дублирование. Старые stores → удалить.
**Prerequisite:** 4c + 4d + 4e полностью завершены и стабильны.

---

### Task 4f.1 — Удаление CameraRegistry → подписки StateProxy
**Уровень:** Middle (Sonnet)
**Исполнитель:** developer

**Файлы:**
- `frontend/managers/camera_registry.py` — удалить
- Все виджеты использующие CameraRegistry → StateProxy подписки

**Критерии приёмки:**
- [ ] Ни один виджет не импортирует CameraRegistry
- [ ] Данные о камерах читаются из StateProxy

---

### Task 4f.2 — Упрощение RecipeManager → RecipeEngine
**Уровень:** Middle (Sonnet)
**Исполнитель:** developer

**Файлы:**
- `frontend/managers/recipe_manager.py` — удалить или тонкий адаптер к RecipeEngine

**Критерии приёмки:**
- [ ] RecipeManager.save_slot() → RecipeEngine.save()
- [ ] Старый YAML-формат мигрирован

---

### Task 4f.3 — Удаление register_update IPC path
**Уровень:** Senior (Opus)
**Исполнитель:** teamlead

**Файлы:**
- `backend/helpers.py` — `apply_register_update()` → удалить
- `backend/processes/*/commands.py` — `build_register_handlers()` → удалить
- `registers/commands/routing.py` — `COMMAND_TO_REGISTER_KEY` → удалить
- `frontend/commands/gui_command_handler.py` — переключить на StateProxy

**Критерии приёмки:**
- [ ] Ноль использований `register_update` в IPC
- [ ] Все процессы получают config через state.changed
- [ ] GUI отправляет изменения через StateProxy.set()
- [ ] Все тесты зелёные
- [ ] `python scripts/validate.py` проходит

---

## Phase 4g — Advanced: Selectors + DevTools + Health ✅ DONE

**Статус:** Выполнено. 78 тестов (Selectors 24 + Inspector 29 + Health 25).

**Цель:** Финальный слой — production-ready фичи для масштабирования и отладки.
Аналоги: Redux DevTools, MobX computed, ROS diagnostics.

**Prerequisite:** Phase 4f завершён, система стабильна.

---

### Task 4g.1 — Selectors: вычисляемое производное состояние
**Уровень:** Senior (Opus)
**Исполнитель:** teamlead
**Цель:** Автоматически вычисляемые значения, зависящие от нескольких путей

**Файлы:**
- `state_store/selectors/__init__.py`
- `state_store/selectors/selector.py`
- `state_store/tests/test_selectors.py`

**Контракт:**
```python
class Selector:
    """Вычисляемое значение, зависящее от нескольких путей.
    
    Аналог MobX computed / Redux Reselect / Vue computed.
    Кэширует результат, пересчитывает только при изменении зависимостей.
    
    Пример:
        # Средний FPS по всем камерам
        avg_fps = Selector(
            name="avg_fps",
            dependencies=["cameras.*.state.actual_fps"],
            compute=lambda values: sum(values.values()) / max(len(values), 1),
        )
        store_manager.register_selector(avg_fps)
        
        # Статус системы: "ok" если все камеры running
        system_health = Selector(
            name="system_health",
            dependencies=["cameras.*.state.status"],
            compute=lambda values: "ok" if all(v == "running" for v in values.values()) else "degraded",
        )
    
    Selector публикует результат в дерево: selectors.{name} = computed_value.
    Подписчики могут подписаться на selectors.avg_fps как на обычный путь.
    """
    
    def __init__(self, name: str, dependencies: list[str], compute: Callable): ...
```

**Зачем:** Виджеты часто показывают агрегированные данные (средний fps, общий статус).
Без selectors каждый виджет считает сам → дублирование логики + лишний IPC.

**Критерии приёмки:**
- [ ] Selector пересчитывается при изменении зависимостей
- [ ] Результат кэшируется до следующего изменения
- [ ] Подписка на selectors.avg_fps работает как на обычный путь
- [ ] 8+ тестов

---

### Task 4g.2 — StateInspector: DevTools для отладки
**Уровень:** Middle+ (Sonnet)
**Исполнитель:** developer
**Цель:** IPC-команды для инспекции состояния в runtime

**Файлы:**
- `state_store/devtools/__init__.py`
- `state_store/devtools/inspector.py`
- `state_store/tests/test_inspector.py`

**Контракт:**
```python
class StateInspector:
    """DevTools для StateStore. Доступен через IPC-команды.
    
    Команды:
    - state.inspect → полное дерево (или поддерево по path)
    - state.subscriptions → список активных подписок
    - state.stats → метрики из MetricsMiddleware
    - state.history → последние N дельт (ring buffer)
    - state.diff → diff текущего состояния с сохранённым рецептом
    """
    
    def __init__(self, manager: StateStoreManager, history_size: int = 100): ...
    
    def handle_inspect(self, msg: dict) -> dict: ...
    def handle_subscriptions(self, msg: dict) -> dict: ...
    def handle_stats(self, msg: dict) -> dict: ...
    def handle_history(self, msg: dict) -> dict: ...
```

**History ring buffer:**
```python
# Хранит последние N дельт для отладки
# state.history → [
#   {"path": "cameras.0.config.fps", "old": 25, "new": 30, "source": "gui", "ts": 123.4},
#   {"path": "cameras.0.state.actual_fps", "old": 25.1, "new": 29.8, "source": "camera_0", "ts": 123.5},
# ]
```

**Зачем:** Без инструментов отладки path-based система — чёрный ящик.
Inspector позволяет в runtime посмотреть: что в дереве, кто подписан, что менялось.

**Критерии приёмки:**
- [ ] state.inspect возвращает дерево/поддерево
- [ ] state.subscriptions показывает все подписки с паттернами
- [ ] state.history возвращает последние N дельт
- [ ] state.stats возвращает метрики
- [ ] 8+ тестов

---

### Task 4g.3 — HealthMonitor: watchdog на базе state
**Уровень:** Middle+ (Sonnet)
**Исполнитель:** developer
**Цель:** Автоматическое определение здоровья процессов по state-обновлениям

**Файлы:**
- `state_store/health/__init__.py`
- `state_store/health/monitor.py`
- `state_store/tests/test_health.py`

**Контракт:**
```python
class HealthMonitor:
    """Watchdog: отслеживает state-обновления от процессов.
    
    Если процесс не обновлял state.status дольше timeout — пометить как unresponsive.
    
    Правила:
    - cameras.{id}.state.last_heartbeat → если delta > 5с → status = "unresponsive"
    - renderer.state.status → если нет обновлений > 10с → warning
    - system.health → агрегированный статус (all ok / degraded / critical)
    
    Реализуется как middleware (after_set) + периодический таймер.
    """
    
    def __init__(
        self,
        store: TreeStore,
        heartbeat_timeout: float = 5.0,
        check_interval: float = 2.0,
    ): ...
    
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def get_health(self) -> dict[str, str]: ...
```

**Зачем:** Сейчас ProcessMonitor отслеживает PID процессов. Но процесс может быть alive 
но зависнуть (deadlock, infinite loop). HealthMonitor на базе state определяет это:
если камера не обновляла actual_fps > 5с — она зависла, даже если PID жив.

**Критерии приёмки:**
- [ ] Камера не обновляет state > 5с → status = "unresponsive"
- [ ] system.health агрегирует статусы всех процессов
- [ ] Восстановление: камера обновляет state → status = "running"
- [ ] 6+ тестов

---

## Сводная таблица задач

| Task | Фаза | Уровень | Исполнитель | Зависит от | Файлов | Строк | Статус |
|------|------|---------|-------------|------------|--------|-------|--------|
| 4a.1 | Core | Middle+ | developer | — | 4 | ~300 | ✅ |
| 4a.2 | Core | Middle | developer | — | 2 | ~100 | ✅ |
| 4a.3 | Core | Senior | teamlead | — | 2 | ~200 | ✅ |
| 4a.4 | Core | Middle+ | developer | 4a.1-3 | 3 | ~100 | ✅ |
| 4b.1 | IPC | Senior+ | teamlead | 4a.4 | 4 | ~350 | ✅ |
| 4b.2 | IPC | Middle+ | developer | 4b.1 | 4 | ~250 | ✅ |
| 4b.3 | IPC | Middle+ | developer | 4b.1 | 2 | ~100 | ✅ |
| 4b+.1 | Middleware | Senior | teamlead | 4b | 3 | ~150 | ✅ |
| 4b+.2 | Middleware | Middle+ | developer | 4b+.1 | 2 | ~100 | ✅ |
| 4b+.3 | Middleware | Middle+ | developer | 4b+.1 | 2 | ~100 | ✅ |
| 4b+.4 | Middleware | Middle | developer | 4b+.1 | 3 | ~100 | ✅ |
| 4c.1 | Backend | Middle+ | developer | 4b+.2 | 3 | ~100 | ✅ |
| 4c.2 | Backend | Senior | teamlead | 4b+.2 | 3 | ~150 | ✅ |
| 4c.3 | Backend | Middle | developer | 4b+.2 | 3 | ~100 | ✅ |
| 4d.1 | GUI | Senior | teamlead | 4b+ | 3 | ~200 | ✅ |
| 4d.2 | GUI | Middle+ | developer | 4d.1 | 3 | ~100 | ✅ |
| 4e.1 | Persist | Middle+ | developer | 4b+.1 | 3 | ~150 | ✅ |
| 4e.2 | Recipes | Senior | teamlead | 4e.1 | 3 | ~200 | ✅ |
| 4f.1 | Cleanup | Middle | developer | 4d.1 | 5+ | ~(-200) | ✅ |
| 4f.2 | Cleanup | Middle | developer | 4e.2 | 3 | ~(-100) | ✅ |
| 4f.3 | Cleanup | Senior | teamlead | 4c.*, 4d.* | 8+ | ~(-300) | ✅ |
| **4g.1** | **Advanced** | **Senior** | **teamlead** | **4f** | **3** | **~200** | ✅ |
| **4g.2** | **Advanced** | **Middle+** | **developer** | **4f** | **3** | **~150** | ✅ |
| **4g.3** | **Advanced** | **Middle+** | **developer** | **4f** | **3** | **~120** | ✅ |

**Итого:** ~3200 строк нового кода, ~600 строк удалённого, 24 задачи.

---

## Порядок выполнения

```
НЕДЕЛЯ 1: Foundation                                              ✅ DONE
├── [параллельно] Task 4a.1 (TreeStore) + Task 4a.2 (Delta)       ✅
├── Task 4a.3 (SubscriptionManager)                                ✅
├── Task 4a.4 (интеграция core)                                    ✅
├── Task 4b.1 (StateStoreManager)                                  ✅
├── [параллельно] Task 4b.2 (StateProxy) + Task 4b.3 (Bootstrap)  ✅
│
НЕДЕЛЯ 2: Middleware + Persistence                                ✅ DONE
├── Task 4b+.1 (Middleware pipeline)                                ✅
├── [параллельно] Task 4b+.2-4 (Throttle+Validation+Logging)       ✅ (97 тестов)
├── Task 4e.1 (PersistenceManager)                                  ✅ (12 тестов)
│
НЕДЕЛЯ 3: Миграция                                                ✅ DONE
├── [параллельно] Task 4c.1 (Camera) + Task 4d.1 (RegistersAdapter) ✅
├── [параллельно] Task 4c.2 (Processor) + Task 4d.2 (GuiProcess)    ✅
├── Task 4c.3 (остальные процессы)                                   ✅
└── Task 4e.2 (RecipeEngine)                                         ✅ (24 теста)

НЕДЕЛЯ 4: Cleanup + Стабилизация                                  ✅ DONE
├── [параллельно] Task 4f.1 (CameraStateAdapter) + 4f.2 (RecipeAdapter) ✅ (27+15 тестов)
├── Task 4f.3 (убрать register_update)                               ✅ (-155 строк)
└── Стабилизация: dual-mode тесты → StateProxy-only                  ✅

НЕДЕЛЯ 5: Advanced                                                ✅ DONE
├── [параллельно] Task 4g.1 (Selectors) + 4g.2 (Inspector) + 4g.3 (Health) ✅ (78 тестов)

═══════════════════════════════════════════════════════════════════
PHASE 4 COMPLETE — 497 тестов, 24 задачи, все фазы 4a-4g завершены
═══════════════════════════════════════════════════════════════════
```

---

## Что потом: экстракция во фреймворк

После стабилизации Phase 4 в прототипе:

**Кандидаты на экстракцию в `multiprocess_framework/modules/state_store_module/`:**
- `TreeStore` — универсальный (нет зависимостей на приложение)
- `Delta` + `Transaction` — универсальные
- `SubscriptionManager` — универсальный
- `StateProxy` + `GuiStateProxy` — универсальные
- `DeltaDispatcher` — универсальный
- `MiddlewarePipeline` + базовые middleware (Throttle, Logging, Metrics) — универсальные
- `PersistenceManager` — универсальный (абстрактный backend: YAML/SQLite/custom)
- `Selector` — универсальный
- `StateInspector` — универсальный
- `HealthMonitor` — универсальный

**Остаётся в прототипе (app-specific):**
- `RecipeEngine` — логика рецептов специфична для Inspector
- `ValidationMiddleware` с конкретными схемами — app-specific
- `RegistersStateAdapter` — мост к RegistersManager (приложение)
- `bootstrap.py` — маппинг AppConfig → дерево (приложение)
- Конкретные подписки процессов

**Фреймворк как конструктор:**
```python
from multiprocess_framework.modules.state_store_module import (
    StateStoreManager, StateProxy, TreeStore, Delta,
    ThrottleMiddleware, HealthMonitor, Selector,
)

# 1. Определить своё дерево данных
initial = {"sensors": {"0": {"config": {...}, "state": {...}}}}

# 2. Создать StateStore с middleware
store_mgr = StateStoreManager(router, initial_state=initial)
store_mgr.use(ThrottleMiddleware({"**.state.**": 1.0}))
store_mgr.use(HealthMonitor(heartbeat_timeout=5.0))

# 3. Selectors
store_mgr.register_selector(Selector(
    name="avg_temperature",
    dependencies=["sensors.*.state.temperature"],
    compute=lambda vals: sum(vals.values()) / max(len(vals), 1),
))

# 4. В каждом процессе:
proxy = StateProxy(self.name, self._router)
proxy.subscribe("sensors.*.config.*", self._on_config)
proxy.set("sensors.0.state.temperature", 42.5)
```

---

## Риски и митигации

| Риск | Вероятность | Митигация |
|------|-------------|-----------|
| Bottleneck в ProcessManager | Средняя | ThrottleMiddleware (4b+.2), batching, coalescing |
| Потеря state.changed при переполнении очереди | Низкая | Увеличить maxsize; backpressure warning в MetricsMiddleware |
| Qt thread safety | Средняя | GuiStateProxy + QMetaObject.invokeMethod (уже реализовано) |
| Обратная совместимость 170+ виджетов | Высокая | RegistersStateAdapter — мост, не переписывание |
| Dual-write баги в переходный период | Средняя | Feature flag USE_STATE_STORE, smoke tests обоих путей |
| Невалидные данные в TreeStore | Средняя | ValidationMiddleware (4b+.3) до миграции |
| Производительность deep copy | Низкая | 400 узлов ≈ микросекунды; профилировать если растёт |
| Deadlock при зависшем процессе | Средняя | HealthMonitor (4g.3) — watchdog на базе state heartbeat |
| Отладка path-based routing | Средняя | StateInspector (4g.2) — runtime DevTools |
