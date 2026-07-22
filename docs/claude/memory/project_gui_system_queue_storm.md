---
name: project-gui-system-queue-storm
description: "gui слеп для команд — PM топит его system-очередь per-delta пушами state.changed; дренаж gui ~18 сообщ/с, очередь вечно 85-94/100"
metadata:
  node_type: memory
  type: project
  originSessionId: 6bbde6d4-7d7b-416c-bf22-f08f4b622bb0
  modified: 2026-07-22T13:10:48.688Z
---

Диагноз 2026-07-22 (live webcam_sketch): `gui` не отвечает НИ на одну команду
(introspect/watch/ui_* — timeout/`no channel resolved`) даже с живым GUI. Механика:
PM шлёт КАЖДУЮ state-дельту отдельным сообщением в never-drop system-очередь gui
(74k за прогон), gui дренирует ~18 сообщ/с → очередь стоит на 85-94/100, команды
не могут даже ВОЙТИ (put сдаётся). PM `router.errors` ≈ `queue_system_evict_blocked`
— «загадка 78% ошибок» = этот backpressure, не роутинг. Центральный троттл НЕ лечит:
шторм — сумма путей × per-delta сообщения, а не частота одного пути.

**Фикс-направление (отдельный план):** коалесцировать дельты per-subscriber/tick
(ADR-PM-016 delta-mode), state.changed к gui на droppable-QoS (стейл-дельту вытесняет
следующая), batch-дренаж в message_processor. Пока дыра жива: ui_tap/ui_tap_ping
непроверяемы, capabilities без карточки gui.

Смежное: [[project_backend_ctl_framework_module]], [[project_webcam_sketch_freeze]],
[[project_telemetry_coherence_remediation]].

Также вскрыто там же: `incarnation` НЕ бампается на `process.restart` (pid сменился,
epoch 0→1, incarnation 0→0) — fence на этой полосе рестарта обезоружен; отдельный трек.
