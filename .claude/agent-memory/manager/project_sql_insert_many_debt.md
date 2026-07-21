---
name: project-sql-insert-many-debt
description: plans/2026-06-05_sql-insert-many-atomic.md — DRAFT и НЕ выполнен по состоянию на 2026-07-21; insert_many всё ещё per-row commit
metadata:
  type: project
---

`plans/2026-06-05_sql-insert-many-atomic.md` числится DRAFT и **не выполнен** — проверено по коду
2026-07-21: `Services/sql/core/base_repository.py:80-94` по-прежнему делает per-row
`self._adapter.execute(...)` в цикле, а `BaseSyncAdapter.execute` открывает соединение и коммитит на
каждый вызов.

**Why:** дефект вскрыт при миграции `DatabasePlugin` (ревью Opus, коммит `0da4d582`). Из-за него
`DatabasePlugin._do_flush` и `telemetry_sink._sample_once` работают построчно и лишены атомарности
снимка — обходной путь зашит в код с объясняющими комментариями.

**How to apply:** план проработан и корректен — **исполнять как есть, не переписывать и не дублировать**
задачу в новых планах. `plans/storage-stack-embedded-first.md` (Этап 1, Task 1.2) ссылается на него именно
так. После выполнения: снять устаревший комментарий в `Plugins/io/telemetry_sink/plugin.py:175-177`
(«insert_many — per-row commit, не атомарна») — он станет ложью. Перед действием перечитать код: если
`base_repository` уже переписан, память устарела.
