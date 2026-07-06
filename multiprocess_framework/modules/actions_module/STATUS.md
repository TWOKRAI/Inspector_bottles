# actions_module — Статус компонентов

**Статус:** STABLE (carve-out из `frontend_module/actions/` 2026-05-11, ADR-124)

Строительные блоки undo/redo фреймворка под контракт `UndoRedoController` — **две реализации, разные tier'ы** (ADR ACT-002, docs/audits/2026-06-18_command-undo-system.md): **PATCH**-движок `ActionBus` (для простых/сложных проектов) и generic **SNAPSHOT**-стек `SnapshotHistory[T]` (для проектов с immutable-агрегатом). Полностью изолирован от `frontend_module` (PySide6 не требуется), зависит только от `data_schema_module.SchemaBase`. Persistence реализуется внешними сервисами через Protocol-контракты — конкретный writer живёт в `Services/sql/action_log/`.

---

## Таблица компонентов

| Компонент | Файл | Статус | Описание |
|-----------|------|--------|----------|
| **core** | | | |
| Action | schemas.py | Готов | Иммутабельная единица изменения (`forward_patch`/`backward_patch`/`coalesce_key`/`undoable`); SchemaBase для SQL-маппинга |
| ActionBuilder | builder.py | Готов | Generic-фабрика: `field_set`, `from_field` (с `RegisterBindingLike` Protocol), `command` |
| ActionBus | bus.py | Готов | Шина выполнения: undo/redo-стеки (max_history), coalescing, change-callbacks, опциональный `IActionLogWriter` |
| IRegistersManagerGui | bus.py (Protocol) | Готов | Контракт RegistersManager на стороне GUI (`set_field_value`) |
| ActionHandler | bus.py (Protocol) | Готов | Контракт обработчика (`apply`/`revert`) |
| **handlers** | | | |
| NodeMoveHandler | handlers/move_handler.py | Готов | apply/revert перемещения ноды через `on_position_changed(node_id, x, y)` callback |
| TopologyMutationHandler | handlers/topology_handler.py | Готов | apply/revert мутаций topology через `TopologyHolderProtocol` + опциональный `TopologyBridgeProtocol` |
| **snapshot** | | | |
| SnapshotHistory[T] | snapshot_history.py | Готов | Generic snapshot-стек над immutable-агрегатом T (record/take_undo/take_redo/can_*/entries/clear, coalescing, max_history); строит. блок SNAPSHOT-реализации `UndoRedoController` |
| SnapshotEntry | snapshot_history.py | Готов | Проекция метаданных записи стека (label/command_type/timestamp), generic-аналог доменного HistoryEntry |
| **persistence (Protocols)** | | | |
| IActionLogWriter | persistence/interfaces.py | Готов | Буферизованный writer лога (`enqueue`/`flush`/`start`/`stop`) |
| IActionLogRepository | persistence/interfaces.py | Готов | CRUD-репозиторий action_log |

## Внешние зависимости

| Куда | Что | Зачем |
|------|-----|-------|
| `data_schema_module` | `SchemaBase` | `Action` наследник для SQL-маппинга и совместимости с регистрами |

Это единственный cross-module edge модуля. `frontend_module` не импортируется (см. ADR-124).

## Внешние потребители (по состоянию на 2026-05-11)

- `multiprocess_prototype/frontend/actions/` — прикладной слой (AppActionBuilder, доменные handlers)
- `multiprocess_prototype/frontend/app_context.py`, `app.py` — bus_factory + регистрация
- `Services/sql/action_log/` — реализация `IActionLogWriter`/`IActionLogRepository`
- `frontend_module` — не импортирует actions_module (Protocol-only через типизацию RM)

## Тесты

- `tests/test_bus.py` — 33 теста (execute/undo/redo/coalescing/callbacks/clear)
- `tests/test_snapshot_history.py` — 9 тестов generic SnapshotHistory[T] (roundtrip/coalescing/redo-clear/max_history/empty/entries n=0/clear)
- `handlers/tests/test_move_handler.py` — apply/revert NodeMoveHandler
- `handlers/tests/test_topology_handler.py` — apply/revert TopologyMutationHandler (с/без bridge)

> **Потребитель SnapshotHistory:** `multiprocess_prototype/adapters/dispatch/history.py` — `ProjectHistory = SnapshotHistory[Project]` (тонкая доменная привязка, проекция entries→HistoryEntry). Carve-out 2026-06-18.
