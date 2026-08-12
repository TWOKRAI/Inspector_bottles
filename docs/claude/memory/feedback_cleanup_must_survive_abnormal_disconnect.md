---
name: cleanup-must-survive-abnormal-disconnect
description: "уборку клиентских ресурсов проверять и аварийным разрывом (RST/kill), не только вежливым close — «редкая гонка» может оказаться непокрытой веткой"
metadata:
  node_type: memory
  type: feedback
  originSessionId: e261020d-c8af-43b5-9e51-f1aa2099dd0d
  modified: 2026-08-12T15:38:36.501Z
---

Н3-1: приёмка пробовала два вежливых завершения (`watch → unwatch → close` и `watch → close`) —
0/12, вывод «гонка в уборке». RST-обрыв (SO_LINGER=0) посреди потока пушей воспроизвёл призрака
**с первой попытки**: `errors_delivery_failed` 0 → 1486 за 30 с при нуле клиентов (2026-08-12,
стенд webcam_sketch).

**Why:** уборка `on_session_closed`, повешенная на штатное закрытие, молчит при креше, kill'е и
обрыве сети — а именно так клиенты и умирают в бою; «не воспроизводится на вежливых формах» ≠
«редкая гонка».

**How to apply:** для любого учёта per-client ресурсов (подписки, форвардеры, кольца, сессии)
проверять ТРИ формы смерти клиента: снятие → close; close без снятия; RST/kill посреди потока.
Репро-зонд как образец: `backend_ctl/probes/probe_n3_1_ghost_rst.py`.
Связано: [[observability-tail-repair]].
