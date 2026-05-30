# Pipeline: назначение ноды в процесс и воркер (process/worker assignment)

**Slug:** pipeline-node-process-worker
**Статус:** Phase A ✅ + Phase B ✅ (MVP) сделаны; Phase B+ долг и Phase C — в новом чате
**Связано:** [[pipeline-ux-displays-gui-layout]]

## ▶ RESUME (следующая сессия) — начни отсюда

**Сделано (этот чат, НЕ закоммичено):** Phase A (блок «Исполнение» в карточке),
Phase B MVP (команда `MovePlugin` + combo «Перенести в процесс» → merge узла в процесс).
Проверено вживую (qt-mcp) и тестами (domain 257 + pipeline 425, ruff чисто).

**Остаток (по приоритету):**
1. **Phase B+ долг** (editor, без фреймворка): перенос ОТДЕЛЬНОГО плагина (не всего узла);
   reorder плагинов внутри процесса через UI; (опц.) визуализация node=плагин с
   контейнерами-процессами. Domain `MovePlugin` уже умеет `from_index`/`to_index` —
   нужен только UI (per-plugin контрол в карточке вместо node-level combo).
2. **Phase C** (framework + editor): СНАЧАЛА выбрать модель воркера (см. «КРИТИЧНЫЙ
   вопрос дизайна» ниже) — **вариант A (рекомендую) vs B**. Без решения не начинать.

**Ключевые файлы:** `domain/commands.py` (`MovePlugin`), `domain/entities/project.py`
(`_apply_move_plugin`); `inspector/inspector_panel.py` (`move_to_process_requested`,
`_populate_move_process_combo`), `presenter.py` (`_on_move_to_process_requested`),
`tab.py` (`available_processes` в `_on_selection_changed`). Тесты —
`domain/tests/test_commands_apply.py` (секция MovePlugin).
**Прогон:** `.venv/Scripts/python.exe -m pytest multiprocess_prototype/domain/tests/
multiprocess_prototype/frontend/widgets/tabs/pipeline/tests/ -q`.

## Запрос пользователя

В карточке ноды не видно, в каком ПРОЦЕССЕ она исполняется, и нельзя сменить.
Хочу: назначать ноду (плагин) в процесс И в воркер. Семантика:
- один воркер = последовательная цепочка (слева направо);
- разные воркеры / разные процессы = параллельно.

## Что есть сейчас (по коду)

- Редактор: **нода = процесс** (`node_id == process_name`). Несколько плагинов в
  процессе показываются в карточке списком, но на графе — один узел.
- Воркеры назначаются **автоматически** в `GenericProcess`
  ([generic_process.py:110-155](../../../../../multiprocess_framework/modules/process_module/generic/generic_process.py)):
  source-плагин → свой воркер; ВСЕ processing-плагины → один воркер `pipeline_executor`,
  исполняются **последовательно** (`ChainRunnable`). Поля `worker_id` НЕТ.
- Параллелизм сейчас = **разные процессы**. Внутри процесса — строго последовательно.
- combo «Процесс назначения» = `target_process` (IPC-роутинг команд), НЕ «где исполняется».
  Пустой, т.к. список берётся из активного рецепта (`recipes.get_active()` = None).

## КРИТИЧНЫЙ вопрос дизайна (gate для Phase C)

Что значит «плагин в воркере N» при потоковом pipeline?
- **Вариант A (рекомендую):** воркер = **параллельная ветка** внутри процесса. В один
  воркер кладётся линейная под-цепочка (последовательно), независимые ветки — в разные
  воркеры (параллельно). Совпадает с DAG: ветки fan-out → разные воркеры.
- Вариант B: каждый плагин — свой воркер, фреймворк сам разруливает зависимости
  (pipeline-stages / backpressure). Сильно сложнее, меняет рантайм-исполнение.

Без ответа Phase C не начинать.

## Фазы

### Phase A — Прозрачность (editor only, без фреймворка) — ✅ DONE
- [x] Карточка показывает блок «Исполнение»: **Процесс: <name>** + по каждому плагину
  **воркер** (source → `source_producer_<name>` свой поток; processing →
  `pipeline_executor · последовательно (шаг N/total)`).
- [x] Combo «Процесс назначения» → «IPC-таргет команд» + tooltip; скрывается, когда пуст
  (это и была жалоба «почему не могу поменять» — combo не про исполнение и часто пуст).
- [x] Файлы: `inspector/inspector_panel.py`. Тесты: +4 (TestExecInfo), pipeline 425 зелёные.
- [x] Live (qt-mcp): `preprocessor` → «Процесс: preprocessor / resize: pipeline_executor ·
  последовательно», пустой combo скрыт.

### Phase B — Перенос узла в другой процесс (merge) — ✅ DONE (MVP)
Реализовано через карточку (combo «Перенести в процесс»), без рефактора графа на
node=плагин: узел=процесс, перенос = слияние всех плагинов узла в целевой процесс
(последовательная цепочка). Граф перерисовывается из TopologyReplaced.
- [x] **Domain:** команда `MovePlugin(from_process, from_index, to_process, to_index?)`
  + событие `PluginMoved`; `Project._apply_move_plugin`: перенос плагина, переписывание
  концов проводов `from.<plugin>.* → to.<plugin>.*`, сброс ставших внутрипроцессными
  проводов, удаление опустевшего источника, `_validate_topology`. 8 тестов + exhaustiveness.
- [x] **Editor:** combo «Перенести в процесс» в карточке (другие процессы, кроме self
  и protected) → `presenter._on_move_to_process_requested` → серия `MovePlugin(index 0)`
  с общим `coalesce_key` (одна undo-запись).
- [x] **Live (qt-mcp):** `process_negative` → `process_grayscale`: узел слился, карточка
  показывает `grayscale (шаг 1/2)` + `negative (шаг 2/2)`, undo полностью обратим.
- Файлы: domain/commands, events, project, __init__ (+тесты); presenter, inspector, tab.
- **Долг Phase B+ (не в MVP):** перенос ОТДЕЛЬНОГО плагина (не всего узла); reorder
  внутри процесса через UI; полноценная визуализация node=плагин с контейнерами.

### Phase C — Воркеры внутри процесса (параллелизм) — FRAMEWORK + editor
- Зависит от ответа на критичный вопрос (вариант A/B).
- Вариант A: поле `worker` у PluginInstance/ProcessConfig; `GenericProcess` создаёт
  воркер на группу и раскидывает независимые ветки по воркерам; цепочка внутри воркера —
  последовательно. ChainRunnable на воркер, ветки параллельно.
- Файлы: framework (generic_process, blueprint, worker_module), domain (plugin/process),
  editor (карточка воркера, визуализация веток). Risk: high (рантайм). Нужны тесты.

## Acceptance (по фазам)
- A: карточка показывает Процесс/Воркер/порядок; пустой combo не вводит в заблуждение.
- B: можно собрать 2+ плагина в один процесс из редактора; сохраняется в рецепт; запуск ок.
- C: независимые ветки в одном процессе реально исполняются в разных воркерах (метрика/лог).

## Решение по порядку
Стартуем с **Phase A** (быстрая ценность, 0 риска), параллельно — sign-off варианта A/B
для Phase C. Phase B — после A. Phase C — после согласования дизайна.
