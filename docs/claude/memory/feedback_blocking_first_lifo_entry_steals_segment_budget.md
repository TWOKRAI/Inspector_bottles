---
name: blocking-first-lifo-entry-steals-segment-budget
description: "Запись, добавленная ПОСЛЕДНЕЙ в сегмент work lifetime, в фазе 2 идёт ПЕРВОЙ (LIFO) и не обрывается сроком (lifetime.py:364-365); если вызываемое блокируется дольше срока сегмента, воркеры получают timeout=0 и чистый стоп превращается в survivors (код 76) / a callable entry registered last in a root segment runs first and is not cut by the deadline"
module: [process_module]
mechanism: [lifecycle, concurrency]
role: reviewer
metadata:
  type: feedback
  last-verified: 2026-11-01
---

Порядок записей сегмента `work` в фазе 2 обратный регистрации, а вызываемое сроком не прерывается: ранняя запись, блокирующая дольше срока сегмента `W`, съедает срок всего, что идёт после неё. Воспроизведено (C-60, 2026-11-01): без хука `ok=True`, `survivors=[]`, 0,016 с; хук спит 1,5 с при `W` = 1,0 → `survivors=[proc/<имя>/work/workers]`, `shutdown()` всё ещё `True`, 1,516–1,547 с (6 из 6). Хук, который зависает навсегда, оставляет воркеров без `stop_event` до окна PM (через 3 с `worker_exit = None`); воркер, держащий замок до `stop_event`, + хук, берущий тот же замок → `proc.shutdown()` не вернулся за 4 с.

**Why:** бриф утверждал «правка не меняет outcome» — верно только для неблокирующего хука; фреймворк хук сроком не ограничивает (решение лида: поток на хук — лишний слой).
**How to apply:** для любой новой ранней записи корневого сегмента — hazard-тест с блокирующим телом длиной `W + 0,5 с` и ожидаемыми `survivors` числом; контракт хука «запускает остановку и возвращается, не ждёт то, что воркер отпускает по `stop_event`»; фразу «outcome не меняется» сужать до неблокирующего тела.

Related: [[project_universal_lifecycle_decision]], [[feedback_do_shutdown_on_unbooted_plugin_is_a_silent_noop]]
