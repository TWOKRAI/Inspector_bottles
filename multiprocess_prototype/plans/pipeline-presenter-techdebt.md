# Pipeline presenter — pre-existing tech-debt (находки ревью #3/#7/#8)

- **Slug:** pipeline-presenter-techdebt
- **Дата:** 2026-05-30
- **Статус:** DRAFT (не начато)
- **Ветка:** `<type>/pipeline-presenter-techdebt` (создать при старте)
- **Источник:** адверсариальное ревью фичи `pipeline-place-display-node` (12/16 находок подтверждено).
  Эти 3 находки — **пре-существующий долг**, НЕ относятся к фиче display-узла, поэтому
  вынесены отдельно (в PR фичи сознательно не трогались).

## Обзор

Ревью подтвердило три реальных, но не связанных с фичей дефекта в `pipeline/`:

1. **#3 (MEDIUM)** — `_on_target_process_changed` пишет в приватный `PipelineModel._topology`
   напрямую, минуя domain dispatch. Изменение `target_process` не персистится в
   TopologyRepository, не публикует `TopologyReplaced`, не попадает в undo/redo.
2. **#8 (LOW)** — в том же методе мёртвая ветка `else` (строки ~209-215) обрабатывает
   не-dict записи процессов через `getattr/setattr` с `except AttributeError: pass`.
   После `from_topology_dict` (deepcopy уже-плоского dict) записи всегда `dict` →
   ветка недостижима, маскирует инвариант Dict at Boundary и глушит ошибки молча.
3. **#7 (LOW)** — `WireMetricsController._update_badge_positions` (строка ~242) итерирует
   приватный `self._scene._edges` (`list[EdgeItem]`). Внутрислойная связь (оба в
   `pipeline/`), но хрупкая: любое изменение внутреннего представления edges в
   `GraphScene` тихо сломает контроллер телеметрии.

Серьёзность по вердиктам ревью: #3 — функциональный (тихая потеря метаданных
`target_process`); #7/#8 — качество кода (инкапсуляция / dead code).

## Контекст (проверено по коду)

- Domain-команда `AssignTargetProcess` **уже существует** (`domain/commands.py:~173`) —
  ровно под эту операцию, но презентер её не использует.
- `_on_target_process_changed` — **единственное** место в презентере, которое трогает
  `_topology` напрямую; все остальные 8 мутаций идут через `services.commands.dispatch`.
- `GraphScene` (`graph/graph_scene.py`) не имеет публичного аксессора для `_edges`
  (есть только `edge_count()` и `export_data()` → `EdgeData`, не `EdgeItem`).
- #3 и #8 — в одном методе: правильный фикс #3 (маршрут через domain) **устраняет**
  и dead code #8.

---

## Порядок выполнения

### Task 1 — target_process через domain dispatch (#3) + удаление dead code (#8)

**Level:** Senior+ (Opus) — затрагивает domain-команду, персист и undo/redo
**Assignee:** teamlead
**Goal:** Изменение `target_process` идёт через `dispatch(AssignTargetProcess)` (персист +
TopologyReplaced + undo/redo); мёртвая не-dict ветка удалена.

**Files:**
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/presenter.py` — `_on_target_process_changed`.
- `multiprocess_prototype/domain/commands.py` — сверить сигнатуру `AssignTargetProcess`.
- При необходимости — handler команды в domain (если ещё не реализован).

**Steps:**
1. Сверить `AssignTargetProcess` (поля, handler в `Project`/dispatch). Если handler
   отсутствует — реализовать (persist target_process в запись процесса топологии).
2. Заменить прямую запись в `_model._topology` на `self._services.commands.dispatch(
   AssignTargetProcess(process_name=node_id, target_process=new_process))` с
   `try/except DomainError` и `_report` (как остальные мутации).
3. Учесть `_suppress`-guard и взаимодействие с `_on_topology_replaced` (scene reload).
4. Удалить мёртвую `else`-ветку (getattr/setattr) — после dispatch она не нужна.

**Acceptance criteria:**
- [ ] Смена target_process персистится (виден в `services.topology.load()`), undoable.
- [ ] `TopologyReplaced` публикуется (подписчики получают актуальную топологию).
- [ ] Прямого доступа к `_model._topology` в методе больше нет.
- [ ] Dead-ветка удалена; существующие тесты презентера зелёные.
- [ ] Новый/обновлённый тест: dispatch вызван, значение персистится, undo откатывает.

**Out of scope:** прочие мутации презентера; рефактор остальных isinstance/getattr
паттернов в модуле (отдельно, если решим).

---

### Task 2 — публичный аксессор edges в GraphScene (#7)

**Level:** Middle (Sonnet)
**Assignee:** developer
**Goal:** `WireMetricsController` читает edges через публичный API `GraphScene`, не через
`_edges`.

**Files:**
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/graph/graph_scene.py` — добавить
  `edges` (property или `get_edges()`), возвращающий копию `list[EdgeItem]`.
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/telemetry/wire_metrics_controller.py`
  — заменить `self._scene._edges` на публичный аксессор.

**Acceptance criteria:**
- [ ] `GraphScene` имеет публичный read-only аксессор edges (копия списка).
- [ ] `WireMetricsController` не обращается к `_edges` напрямую.
- [ ] Тесты телеметрии (`test_wire_metrics_*`) зелёные.

**Out of scope:** изменение модели телеметрии/бейджей; прочие private-доступы.

---

## Зависимости

Task 1 и Task 2 независимы — можно параллельно (разные файлы). Оба малы.

## Примечание

Это долговой план: приоритет ниже продуктовых фич (см. memory
`project_priority_product_over_engine`). Брать, когда есть окно на качество движка.
