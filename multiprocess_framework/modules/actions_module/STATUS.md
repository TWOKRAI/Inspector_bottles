# actions_module — Статус компонентов

**Статус:** STABLE (carve-out из `frontend_module/actions/` 2026-05-11, ADR-124)

Action-bus с undo/redo и coalescing. Полностью изолирован от `frontend_module` (PySide6 не требуется), зависит только от `data_schema_module.SchemaBase`. Persistence реализуется внешними сервисами через Protocol-контракты — конкретный writer живёт в `Services/sql/action_log/`.

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
- `handlers/tests/test_move_handler.py` — apply/revert NodeMoveHandler
- `handlers/tests/test_topology_handler.py` — apply/revert TopologyMutationHandler (с/без bridge)
