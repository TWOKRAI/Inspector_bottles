---
name: project-topology-fencing-token
description: "Требование владельца: message-fencing — старый инстанс не вкидывает stale в новую топологию. ИСПОЛНЕНО Ф4.2 (e16e2ea8): дроп по per-sender incarnation, НЕ epoch (ADR-PMM-014)."
metadata: 
  node_type: memory
  type: project
  originSessionId: 82ad289c-65e8-4577-b5ec-2891866a2fd0
---

**ИСПОЛНЕНО (2026-07-09, Ф4.2 шаги 3-5, коммит e16e2ea8, ADR-PMM-014 + ADR-MSG-009).**
Fencing-token: `message_module/fencing/` штампует `_fence={sender,inc,epoch}` на
control-plane (send-mw) и дропает на приёме билет, чей `inc < PSR[sender].routing_
incarnation` (receive-mw) — билет от ЗАМЕНЁННОГО инстанса. Проводка
`BuiltinCommands._register_message_guards` за `FW_FENCE` (дефолт ON). **Ключевое:
дроп по per-sender INCARNATION, НЕ по глобальному epoch** — эпоха-критерий ложно
дропал легитимный state/telemetry текущих процессов в переходном окне после switch
(вскрыл live `test_routing_epoch_live`; unit был зелёный). incarnation меняется только
при пересоздании очередей процесса (`_bump_incarnation`) → устаревший инстанс отличим
точно. restart-reuse корректно НЕ фенсит. Live `test_fencing_live` (restart-no-reuse →
PM дропает стейл, RED/GREEN). Счётчик `fence_dropped`. Data-plane — Ф7 G.4.
Детали: [[project-constructor-master-progress]].

---

**Требование владельца (2026-07-08):** у каждого процесса должен быть индивидуальный
id, и при переключении топологии старые процессы НЕ должны вкидывать ненужные
сообщения/данные в новую топологию.

**Текущее состояние (после Ф3.1 routing-epoch, ADR-PMM-010):**
- `incarnation` (per-process) и `epoch` (поколение топологии) УЖЕ существуют.
- НО используются только для CLEANUP очередей: выживший сбрасывает стейл-очереди
  (`drop_process_queues`) → send падает в hub-relay. Guard `epoch <= last_seen → ignore`
  применяется ТОЛЬКО к самому сообщению `routing.refresh`, НЕ к обычным data/msg.
- Sender-side epoch-check на КАЖДОМ send был СОЗНАТЕЛЬНО отвергнут (hot-path кадров).
- Есть задокументированное ОКНО ГОНКИ (ADR-PMM-010): сообщения в мёртвых очередях
  или отправленные до обработки refresh теряются/могут проскочить.

**ЧЕГО НЕ ХВАТАЕТ (то, что просит владелец) = fencing-token паттерн:**
штамповать каждое сообщение (sender_name, incarnation, epoch) + receiver-side
middleware, который ОТБРАСЫВАЕТ сообщения со стейл epoch/incarnation. Тогда старый
процесс физически не сможет вкинуть данные в новую топологию — гарантия жёсткая,
а не «окно гонки».

**Куда встроить — Ф4 (контракты/версии):** message-envelope и так версионируется в
Ф4.2 (реестр контрактов сообщений, warn-middleware на receive control-plane). Именно
туда логично добавить поля `sender_incarnation`/`epoch` в конверт + drop-middleware.
Для data-plane (hot-path) — оценить стоимость, возможно под флагом как в Ф7 G.4.
Проверить пересечение с Ф4.3 (payload-валидатор по Port-декларациям) и Ф4.9
(StateStore ревизии — тот же паттерн монотонного счётчика). Связь: [[project-constructor-master-progress]].

**Также разъяснить владельцу нюанс авто-рестарта (Ф3.8/G1):** авто-рестарт включён
PER-PROCESS и только там, где `restart_policy.enabled=true` — по G1 это source/hub
(camera_0, hikvision hub), НЕ все процессы топологии. Рестарт на crash(exitcode≠0)
и unresponsive(нет heartbeat>timeout); graceful stop НЕ рестартится. Процессы вне
новой топологии закрываются при switch (FullReplacePlanner сносит все non-protected).
