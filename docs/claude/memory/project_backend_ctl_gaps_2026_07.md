---
name: project-backend-ctl-gaps-2026-07
description: Дыры backend_ctl, найденные в живой работе 2026-07-20 — introspect.memory не отдаёт RSS процесса, D.4 построил отменённую на GATE G3 задачу 1.8, периферия обогнала доказательства
metadata:
  type: project
---

Найдено НЕ ревью, а живой работой (прогон Ф7 G.7 soak). Резидуалы hardening'а сюда НЕ дублируем — они в `plans/backend-ctl-hardening.md`; здесь то, чего план не ловит.

**1. ✅ ЗАКРЫТО (Фаза 3 Task 3.1, 2026-07-22, `857ed851`). `introspect.memory` теперь отдаёт RSS процесса.**
Было: `MemoryStats{memory, pool, queues, shm_registry}` — только инвентарь SHM/пула/очередей, процессной памяти ОС нет; soak писала `rss: null` — выглядело поломкой. Стало: секция `os: {rss, vms, pid}` через `psutil.Process()` по своему pid (best-effort → null без psutil), поле `MemoryStats.os_memory` со строгим краем (absent→missing). Soak `_rss_mb` читает секцию `os` ответа, отдельный psutil-обход по pid убран. Live webcam_sketch: PM rss=466 МБ, все процессы тракта >0.

**2. ✅ ЗАКРЫТО (Фаза 3 Task 3.2, 2026-07-22, `6b9d4e1f`). `system_overview` несёт `effective_hz` per-process.**
Было: воркеры схлопнуты до строк-статусов, `effective_hz` терялся → за перф-сигналом нужен был отдельный `introspect_status`. Стало: карточка несёт `hz` (ведущий effective_hz по воркерам) + аномалия `hz_degraded` (<50% от target). Live: camera_0/seg/pult ~21 Гц. `perf_probes` осознанно НЕ тянем в свод (тяжёлые — по запросу per-process).

**3. D.4 flight recorder построил то, что GATE G3 решил не делать.**
Задача **1.8 record/replay** (Ф1 backend_ctl, `plans/2026-07-06_constructor-master/plan.md:111`) на GATE G3 2026-07-13 помечена «**пропустить**, остаётся опциональным, вернуться при реальной нужде в offline-отладке». Через 6 дней D.4 (2026-07-19) построил record/replay для сессий backend_ctl — 6 MCP-инструментов + session-режим replay. В мастер-плане 1.8 **до сих пор `[ ] опц`** — треки друг о друге не знали. Не обязательно ошибка (условие «при реальной нужде» могло наступить), но решение владельца было отменено без пересмотра. **Проверить: нужда была реальная или инерция?** Тот же класс дрейфа, что [[feedback_plan_queue_must_list_every_plan]].

**4. Периферия обогнала доказательства.**
D.1 (изоляция сессий) и D.2 (streamable-HTTP мультиклиент) решают проблему нескольких одновременных MCP-клиентов — сколько их у соло-разработчика, не проверялось. При этом ядро (сокет / драйвер / харнесс / introspect) окупается ежедневно: вся лесенка Ф7 G.7 (9 флагов с числами), fault-инъекции Фазы 2 и soak Фазы 3 физически невозможны без него. См. урок [[feedback_tool_features_before_validation]].
