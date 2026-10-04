---
name: project-pipeline-node-process-worker
description: Pipeline node→process→worker feature — Phase A+B done (uncommitted), Phase B+ debt and Phase C pending in new chat
metadata:
  type: project
---

Фича «назначение ноды в процесс/воркер» в Pipeline-редакторе. План:
`multiprocess_prototype/frontend/widgets/tabs/pipeline/plans/pipeline-node-process-worker.md`
(там секция «▶ RESUME» — начинать оттуда).

**Статус (2026-05-30, НЕ закоммичено):**
- Phase A ✅ — блок «Исполнение» в карточке ноды (Процесс + воркер `pipeline_executor`/
  `source_producer_<plugin>` + шаг в цепочке); путавший combo «Процесс назначения»
  переименован в «IPC-таргет команд» и скрыт, когда пуст.
- Phase B ✅ MVP — domain-команда `MovePlugin` (+ событие `PluginMoved`,
  `Project._apply_move_plugin` с переписыванием концов проводов и удалением пустого
  источника) + combo «Перенести в процесс» в карточке → merge узла в другой процесс
  (последовательная цепочка), undo обратим. Проверено вживую (qt-mcp) + тесты.

**Остаток (новый чат):**
1. Phase B+ долг (editor): перенос отдельного плагина (не всего узла), reorder в процессе,
   визуализация node=плагин с контейнерами.
2. **Phase C (framework parallelism) — заблокирован решением:** воркер = параллельная
   ветка (**вариант A, рекомендован**) ИЛИ каждый плагин — свой воркер (вариант B).
   Спросить пользователя до начала.

**Модель исполнения (факт по коду):** разные процессы = параллельно; внутри процесса
все processing-плагины идут ПОСЛЕДОВАТЕЛЬНО в одном `pipeline_executor` (ChainRunnable),
каждый source — свой поток. Поля `worker_id` пока НЕТ (Phase C добавит).

Связано: [[feedback-pipeline-reuse-plugins-widgets]].
