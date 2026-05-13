# Phase 4: Регионы per-camera — План реализации

## Context

Phase 3 завершена (14/14 задач, 35 тестов). Следующий шаг по графу зависимостей — Phase 4: привязка регионов (ROI) к конкретным камерам. Сейчас регионы формально хранятся в `vision_pipeline` per-camera, но:
- CameraRegistry из Phase 3 **не подключён** к FrontendAppContext
- Presenter берёт список камер из статического конфига `ui.camera_ids`
- Backend Processor **игнорирует** поле `vision_pipeline` (нет handler'а)
- Region schema не имеет поля `steps` для Phase 5

Цель: полный CRUD регионов per-camera с propagation в backend.

---

## Задачи

### Task 4.1 — Region.steps: подготовка к Phase 5
**Уровень:** Junior (Haiku)
**Исполнитель:** Director (тривиально)
**Цель:** Добавить `steps: list` в Region schema для будущей цепочки обработки
**Файлы:**
- `multiprocess_prototype/registers/pipeline/region.py`

**Шаги:**
1. Добавить `from typing import Any, Dict, List` в импорты
2. Добавить поле:
```python
steps: Annotated[
    List[Dict[str, Any]],
    FieldMeta("Processing steps", info="Ordered list of processing step configs. Filled in Phase 5."),
] = Field(default_factory=list)
```

**Критерии приёмки:**
- [ ] `Region().steps == []`
- [ ] `Region(steps=[{"op": "blur"}]).model_dump()` round-trip работает
- [ ] Существующие тесты проходят

**Вне scope:** Заполнение steps реальными операциями — Phase 5.

---

### Task 4.2 — Routing для vision_pipeline
**Уровень:** Junior (Haiku)
**Исполнитель:** Director (тривиально)
**Цель:** Добавить FieldMeta с routing к полю `vision_pipeline` в ProcessorRegisters
**Файлы:**
- `multiprocess_prototype/registers/processor/schemas.py`

**Шаги:**
1. Импортировать `PIPELINE_PARAMS_ROUTING` (уже в импортах `constants`)
2. Заменить:
```python
vision_pipeline: Dict[str, Any] = Field(default_factory=dict)
```
на:
```python
vision_pipeline: Annotated[
    Dict[str, Any],
    FieldMeta("Vision Pipeline", info="Per-camera region tree (Pipeline schema).", routing=PIPELINE_PARAMS_ROUTING),
] = Field(default_factory=dict)
```

**Критерии приёмки:**
- [ ] `ProcessorRegisters.get_field_meta("vision_pipeline").routing.channel == "control_processor"`
- [ ] `set_field_value("processor", "vision_pipeline", {...})` триггерит dispatch

**Вне scope:** Динамический routing к конкретному `Processor_{camera_id}` — Phase 5 (пока один Processor).

---

### Task 4.3 — CameraRegistry в FrontendAppContext + tab_factory
**Уровень:** Middle (Sonnet)
**Исполнитель:** developer
**Цель:** Подключить CameraRegistry из Phase 3 в контекст GUI
**Файлы:**
- `multiprocess_prototype/frontend/app_context.py`
- `multiprocess_prototype/frontend/launcher.py`
- `multiprocess_prototype/frontend/windows/main_window/tab_factory.py`

**Шаги:**
1. **app_context.py:** Добавить поле `camera_registry: Optional[Any] = None` в `FrontendAppContext`
2. **launcher.py:** В `register_windows()` — создать `CameraRegistry(camera_configs)` из `self._app_config.get("camera_configs", [])` и записать в `app_ctx.camera_registry`
3. **tab_factory.py:** В ветке `"cropped_regions"` — передать `camera_registry=ctx.camera_registry` в конструктор `CroppedRegionsTabWidget`

**Критерии приёмки:**
- [ ] `FrontendAppContext(...)` без camera_registry = OK (backward compat)
- [ ] С camera_configs → `ctx.camera_registry.camera_count()` == len(configs)
- [ ] CroppedRegionsTabWidget получает camera_registry kwarg

**Вне scope:** Подключение CameraRegistry к другим табам (Camera Tab уже использует свой путь).

---

### Task 4.4 — Presenter: динамические камеры из CameraRegistry
**Уровень:** Middle+ (Sonnet)
**Исполнитель:** developer
**Цель:** Рефакторинг CroppedRegionsPresenter — список камер из CameraRegistry
**Файлы:**
- `multiprocess_prototype/frontend/widgets/cropped_regions_widget/model.py`
- `multiprocess_prototype/frontend/widgets/cropped_regions_widget/presenter.py`
- `multiprocess_prototype/frontend/widgets/cropped_regions_widget/panel_widget.py`

**Шаги:**
1. **model.py:** Добавить `camera_registry: Optional[Any] = None` в `CroppedRegionsModel`
2. **presenter.py → `camera_ids_union()`:** Если `self._model.camera_registry` есть — брать IDs из `all_entries()` как primary source. Union с остальными (cfg, keys, logical) для backward compat:
```python
def camera_ids_union(self) -> List[str]:
    registry_ids = []
    if self._model.camera_registry is not None:
        registry_ids = [str(e.camera_id) for e in self._model.camera_registry.all_entries()]
    cfg = list(self._model.ui.camera_ids or [])
    keys = list(self._model.crop_regions_by_camera.keys())
    logical = self._logical_ids_from_register()
    u = sorted(set(registry_ids) | set(cfg) | set(keys) | set(logical))
    if not u:
        u = [self._default_camera_id()]
    return u
```
3. **panel_widget.py:** Принять `camera_registry` kwarg → передать в model при создании

**Критерии приёмки:**
- [ ] CameraRegistry с камерами 0, 1, 2 → dropdown показывает "0", "1", "2"
- [ ] Без CameraRegistry (None) → fallback на `ui.camera_ids` (backward compat)
- [ ] CRUD региона на камере 1 не затрагивает камеру 0

**Вне scope:** Live-обновление при hot-add камеры, индикаторы статуса.

---

### Task 4.5 — Backend: handler vision_pipeline в Processor
**Уровень:** Middle (Sonnet)
**Исполнитель:** developer
**Цель:** Processor реагирует на обновление vision_pipeline из регистра
**Файлы:**
- `multiprocess_prototype/backend/processes/processor/commands.py`

**Шаги:**
1. Добавить handler `"vision_pipeline"` в `build_register_handlers()`:
```python
"vision_pipeline": lambda v: _apply_vision_pipeline(service, v),
```
2. Реализовать `_apply_vision_pipeline(service, value)`:
   - Парсить `value` как dict (Pipeline structure)
   - Извлечь cameras → regions → processing_blocks
   - Из первого найденного блока обработки — обновить detector params через `service.set_color_range()` / `service.set_min_area()` / `service.set_max_area()`
   - Логировать количество камер/регионов
3. Обернуть в try/except — malformed data → warning, не crash

**Критерии приёмки:**
- [ ] Register_update с vision_pipeline → handler вызывается
- [ ] Detector params обновляются из pipeline data
- [ ] Malformed data → warning в лог, без crash

**Вне scope:** Per-region processing (crop + отдельный detector на регион) — Phase 5.

---

### Task 4.6 — Unit-тесты Phase 4
**Уровень:** Middle (Sonnet)
**Исполнитель:** developer / tester
**Цель:** Покрыть тестами все изменения Phase 4
**Файлы:**
- `multiprocess_prototype/tests/unit/test_region_per_camera.py` (новый)

**Тест-кейсы:**
1. `Region().steps == []` + round-trip с steps
2. `ProcessorRegisters.get_field_meta("vision_pipeline")` имеет routing
3. `camera_ids_union()` с CameraRegistry → возвращает IDs из registry
4. `camera_ids_union()` без CameraRegistry → fallback на ui.camera_ids
5. CRUD per-camera: add region к camera "1" → camera "0" не затронута
6. `build_register_handlers()` содержит ключ `"vision_pipeline"`
7. `_apply_vision_pipeline()` парсит pipeline dict → обновляет service
8. L2: presenter → `_push_register()` → RegistersManager → read back → данные корректны

**Критерии приёмки:**
- [ ] >= 8 тест-кейсов, все проходят
- [ ] `pytest tests/unit/test_region_per_camera.py` — 0 failures

---

## Граф зависимостей задач

```
Task 4.1 (Region.steps) ──────────┐
Task 4.2 (vision_pipeline routing) ┤
                                    ├──→ Task 4.6 (тесты)
Task 4.3 (CameraRegistry wiring) ──┤
         │                          │
         └──→ Task 4.4 (Presenter) ─┘
Task 4.5 (Backend handler) ────────┘
```

4.1, 4.2, 4.3, 4.5 — **независимы**, можно параллельно.
4.4 зависит от 4.3. 4.6 зависит от всех.

---

## Ключевые файлы (существующие, переиспользовать)

| Что | Путь |
|-----|------|
| Region schema | `registers/pipeline/region.py` |
| ProcessorRegisters | `registers/processor/schemas.py` |
| Routing constants | `registers/constants.py` (PIPELINE_PARAMS_ROUTING) |
| CameraRegistry | `frontend/managers/camera_registry.py` |
| FrontendAppContext | `frontend/app_context.py` |
| Launcher | `frontend/launcher.py` |
| Tab factory | `frontend/windows/main_window/tab_factory.py` |
| CroppedRegions model | `frontend/widgets/cropped_regions_widget/model.py` |
| CroppedRegions presenter | `frontend/widgets/cropped_regions_widget/presenter.py` |
| CroppedRegions widget | `frontend/widgets/cropped_regions_widget/panel_widget.py` |
| Processor commands | `backend/processes/processor/commands.py` |
| Widget bridge | `registers/pipeline/widget_bridge.py` |
| Payload helpers | `registers/payloads/crop_regions.py` |

Все пути относительно `multiprocess_prototype/`.

---

## Верификация

1. **Unit-тесты:** ` && python -m pytest multiprocess_prototype/tests/unit/test_region_per_camera.py -v`
2. **Все тесты:** `python scripts/run_framework_tests.py`
3. **Validate:** `python scripts/validate.py`
4. **Ruff:** `ruff check multiprocess_prototype/ && ruff format --check multiprocess_prototype/`
5. **Smoke (manual):** Запустить прототип с 2+ камерами → открыть таб Regions → добавить регион на камеру 1 → проверить что камера 0 не затронута → проверить лог Processor что vision_pipeline handler вызван
