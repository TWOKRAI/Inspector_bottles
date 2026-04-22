# Phase 5a: Processing Chain MVP — План реализации

## Context

Phases 0-4 завершены. Phase 5a — ядро системы: per-region цепочки обработки с каталогом операций. Сейчас один глобальный `ColorBlobDetector` обрабатывает все кадры одинаково. Phase 5a вводит: каталог операций, `ProcessingNode` модель, builder, chain executor, per-region обработку.

**Принципиальные решения:**
- **Один Processor процесс** с per-camera dispatch (не N процессов) — в Phase 5a
- **ProcessingNode** заменяет `BaseProcessingBlock`, но `processing_blocks` остаётся для backward compat
- **Operation** — Protocol (не ABC), как `ProcessorOutputPort`
- **Каталог** — YAML в `data/processing_catalog.yaml`
- **Region.steps** (Phase 4) — deprecated в пользу `RegionNode.nodes`

---

## Задачи

### Task 5a.1 — ProcessingOperationDef schema + YAML каталог
**Уровень:** Middle (Sonnet)
**Исполнитель:** developer
**Цель:** Модель операции каталога + seed-файл с 2 built-in операциями
**Файлы (новые):**
- `registers/processor/catalog/schemas.py` — `ProcessingOperationDef(SchemaBase)`: name, type_key, params_schema (dotted path), module_path, on_error, description
- `registers/processor/catalog/__init__.py`
- `registers/processor/catalog/loader.py` — `load_catalog(path)`, `save_catalog(path, catalog)`
- `data/processing_catalog.yaml` — seed: color_detection + blob_detection

**Критерии приёмки:**
- [ ] `ProcessingOperationDef` round-trip через model_dump/model_validate
- [ ] `load_catalog()` загружает seed YAML → 2 записи
- [ ] Невалидный `on_error` → Pydantic validation error

**Вне scope:** input_ports/output_ports (Phase 8)

---

### Task 5a.2 — ProcessingNode schema
**Уровень:** Middle (Sonnet)
**Исполнитель:** developer
**Цель:** Модель узла обработки внутри региона
**Файлы (новые):**
- `registers/pipeline/processing_node.py` — `ProcessingNode(SchemaBase)`: node_id (UUID auto), operation_ref, params, enabled, process_id, worker_id, inputs (List[NodeInput]), position

**Файлы (изменить):**
- `registers/pipeline/schemas.py` — `RegionNode` получает `nodes: Dict[str, ProcessingNode]`, `processing_blocks` остаётся

**Критерии приёмки:**
- [ ] `ProcessingNode()` создаётся с auto-UUID
- [ ] `RegionNode` имеет и `processing_blocks` (legacy) и `nodes` (new)
- [ ] Full round-trip serialization

**Вне scope:** Удаление processing_blocks, удаление Region.steps

---

### Task 5a.3 — ProcessingOperation Protocol + 2 built-in реализации
**Уровень:** Middle+ (Sonnet)
**Исполнитель:** developer
**Цель:** Интерфейс операции + ColorDetectionOp (обёртка ColorBlobDetector) + BlobDetectionOp (stub)
**Файлы (новые):**
- `services/processor/operations/__init__.py`
- `services/processor/operations/base.py` — `ProcessingOperation(Protocol)` с `execute(frame, context)` + `configure(params)` + `ChainContext` dataclass
- `services/processor/operations/color_detection_op.py` — обёртка существующего ColorBlobDetector
- `services/processor/operations/blob_detection_op.py` — stub (frame unchanged, warning в context)

**Критерии приёмки:**
- [ ] `ColorDetectionOp.execute()` даёт те же детекции что `ColorBlobDetector.detect()`
- [ ] `BlobDetectionOp.execute()` возвращает frame без изменений + warning
- [ ] Оба удовлетворяют Protocol

---

### Task 5a.4 — Operation Loader (динамический импорт)
**Уровень:** Middle (Sonnet)
**Исполнитель:** developer
**Цель:** Загрузка класса операции по `module_path` из каталога
**Файлы (новые):**
- `services/processor/operations/loader.py` — `load_operation_class(module_path) -> Type`. importlib + кэш.

**Критерии приёмки:**
- [ ] Загрузка по полному пути → класс
- [ ] Невалидный путь → ImportError с описанием
- [ ] Повторный вызов → из кэша

---

### Task 5a.5 — GraphRunnableBuilder + ChainRunnable
**Уровень:** Senior (Opus)
**Исполнитель:** teamlead
**Цель:** Построитель runnable из nodes + каталога, executor с error handling
**Файлы (новые):**
- `services/processor/chain/__init__.py`
- `services/processor/chain/builder.py` — `GraphRunnableBuilder.build(nodes, catalog) -> ChainRunnable`
- `services/processor/chain/runnable.py` — `ChainRunnable.execute(frame, metadata) -> ChainResult`

**Шаги:**
1. Builder: фильтр disabled → toposort по inputs → для каждого: load op, configure
2. Runnable: sequential execute, try/except, on_error policy (skip/stop/use_last)
3. `ChainResult` — detections, masks, contours, processing_time, errors, skipped_nodes

**Критерии приёмки:**
- [ ] 2-node chain (color + blob): color отрабатывает, blob пропускает (stub)
- [ ] Disabled node скипается
- [ ] Exception + on_error=skip → chain продолжает
- [ ] operation_ref not in catalog → clear error

---

### Task 5a.6 — Autofill Inputs Helper
**Уровень:** Junior (Sonnet)
**Исполнитель:** developer
**Цель:** Автозаполнение inputs для линейной цепочки
**Файлы (новые):**
- `services/processor/chain/autofill.py` — `autofill_inputs(nodes) -> nodes`

**Критерии приёмки:**
- [ ] 3 ноды → inputs корректно связаны цепочкой
- [ ] 1 нода → inputs пусто
- [ ] Пустой dict → пустой dict

---

### Task 5a.7 — ProcessorService рефакторинг (per-region chain)
**Уровень:** Senior+ (Opus)
**Исполнитель:** teamlead
**Цель:** Заменить единый детектор на per-region chain runnables
**Файлы (изменить):**
- `services/processor/service.py` — добавить `_runnables`, `_catalog`, `rebuild_runnables()`, рефакторинг `process_frame()`
- `backend/processes/processor/commands.py` — `_apply_vision_pipeline()` вызывает `service.rebuild_runnables()`
- `backend/processes/processor/process.py` — передать catalog_path в service, убрать прямое создание ColorBlobDetector

**Критерии приёмки:**
- [ ] Старый pipeline (только processing_blocks) → работает (backward compat)
- [ ] Новый pipeline (nodes dict) → chain per region
- [ ] Register update → rebuild_runnables() + atomic swap
- [ ] 1 регион с 1 color_detection нодой → те же детекции что Phase 4

---

### Task 5a.8 — Widget Bridge обновление
**Уровень:** Middle (Sonnet)
**Исполнитель:** developer
**Цель:** widget_bridge поддерживает ProcessingNode alongside legacy
**Файлы (изменить):**
- `registers/pipeline/widget_bridge.py` — `nodes_from_processing_blocks()` конвертер, dual populate

**Критерии приёмки:**
- [ ] Round-trip: pipeline через bridge → и nodes и processing_blocks присутствуют
- [ ] Legacy pipeline → конвертация через `nodes_from_processing_blocks()`

---

### Task 5a.9 — Chain Editor таблица (Frontend)
**Уровень:** Middle+ (Sonnet)
**Исполнитель:** developer
**Цель:** Табличный UI для редактирования chain региона
**Файлы (новые):**
- `frontend/widgets/chain_editor/` — __init__, schemas, model, view, presenter, panel_widget

**Колонки:** #, Operation (dropdown из каталога), Params (кнопка), Enabled (checkbox), Process (readonly), Worker (readonly)
**Кнопки:** Add, Remove, MoveUp, MoveDown

**Критерии приёмки:**
- [ ] Таблица показывает ноды выбранного региона
- [ ] Add/Remove/Reorder работают, inputs авто-заполняются
- [ ] Toggle enabled → нода скипается

---

### Task 5a.10 — Auto-gen Param Panels из FieldMeta
**Уровень:** Middle+ (Sonnet)
**Исполнитель:** developer
**Цель:** Динамическая генерация UI для параметров операции
**Файлы (новые):**
- `frontend/widgets/chain_editor/param_panel_factory.py` — `build_param_panel(params_schema_path, params)`

**Критерии приёмки:**
- [ ] ColorDetectionParams → 2 compound numeric (BGR) + 2 numeric (area)
- [ ] BlobDetectionParams → 2 numeric (threshold, area)

---

### Task 5a.11 — Catalog CRUD Tab
**Уровень:** Middle (Sonnet)
**Исполнитель:** developer
**Цель:** Простой таб для просмотра/редактирования каталога
**Файлы (новые):**
- `frontend/widgets/catalog_editor/` — __init__, schemas, model, view, presenter, panel_widget

**Критерии приёмки:**
- [ ] Показывает записи каталога
- [ ] Add/Remove/Save → YAML
- [ ] Невалидный on_error → ошибка валидации

---

### Task 5a.12 — Тесты Phase 5a
**Уровень:** Middle (Sonnet)
**Исполнитель:** tester
**Файлы (новые):**
- `tests/unit/test_processing_operation_def.py`
- `tests/unit/test_processing_node.py`
- `tests/unit/test_catalog_loader.py`
- `tests/unit/test_chain_builder.py`
- `tests/unit/test_autofill_inputs.py`
- `tests/unit/test_operation_loader.py`
- `tests/integration/test_chain_execution.py` — L2: real chain + synthetic frame

**Критерии приёмки:**
- [ ] Все unit тесты без Qt/OpenCV (mock)
- [ ] L2: real chain + numpy frame → detections
- [ ] Backward compat: old pipeline dict → detections

---

## Граф зависимостей

```
5a.1 (Catalog Schema) ──┐
                         ├──→ 5a.4 (Loader) ──→ 5a.5 (Builder) ──→ 5a.7 (Service Refactor)
5a.2 (ProcessingNode) ──┤                                                │
                         ├──→ 5a.6 (Autofill) ──────────────────→ 5a.7  │
5a.3 (Operations) ──────┘                                                │
                                                                         ├──→ 5a.12 (Tests)
5a.8 (Widget Bridge) ← 5a.2                                             │
5a.9 (Chain Editor) ← 5a.1 + 5a.2 + 5a.5 + 5a.6                       │
5a.10 (Param Panels) ← 5a.1                                             │
5a.11 (Catalog CRUD) ← 5a.1                                             │
```

**Порядок исполнения:**
1. **Batch 1 (параллельно):** 5a.1, 5a.2, 5a.3
2. **Batch 2:** 5a.4, 5a.6
3. **Batch 3:** 5a.5 (builder — Senior+)
4. **Batch 4:** 5a.7 (service refactor — Senior+)
5. **Batch 5 (параллельно):** 5a.8, 5a.9, 5a.10, 5a.11
6. **Batch 6:** 5a.12 (тесты)

---

## Ключевые файлы

Все пути относительно `Inspector_prototype/multiprocess_prototype_v3/`.

| Что | Путь | Действие |
|-----|------|----------|
| ProcessorService | `services/processor/service.py` | Рефакторинг (5a.7) |
| ProcessorProcess | `backend/processes/processor/process.py` | Изменить (5a.7) |
| Processor commands | `backend/processes/processor/commands.py` | Изменить (5a.7) |
| Pipeline schemas | `registers/pipeline/schemas.py` | Изменить (5a.2) |
| Widget bridge | `registers/pipeline/widget_bridge.py` | Изменить (5a.8) |
| ColorBlobDetector | `services/processor/detection.py` | Переиспользовать (5a.3) |
| ProcessorOutputPort | `services/processor/ports.py` | Переиспользовать |
| WorkerManager | `multiprocess_framework/.../worker_module/` | Переиспользовать (будущие фазы) |

**Новые директории:**
- `registers/processor/catalog/` — модель и загрузчик каталога
- `services/processor/operations/` — Protocol + реализации операций
- `services/processor/chain/` — builder + runnable + autofill
- `frontend/widgets/chain_editor/` — UI editor
- `frontend/widgets/catalog_editor/` — UI каталога

---

## Верификация

1. **Unit:** `pytest tests/unit/test_processing_*.py tests/unit/test_chain_*.py tests/unit/test_catalog_*.py tests/unit/test_autofill_*.py tests/unit/test_operation_*.py -v`
2. **L2:** `pytest tests/integration/test_chain_execution.py -v`
3. **Все тесты:** `pytest multiprocess_prototype_v3/tests/ -v`
4. **Ruff:** `ruff check && ruff format --check`
5. **Smoke:** Запуск прототипа → добавить 2 ноды в chain региона → проверить детекции → disable одну → chain продолжает
