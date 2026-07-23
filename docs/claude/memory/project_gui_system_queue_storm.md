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

**ПОЧИНЕНО 2026-07-22** (`plans/truth-holes-closure.md` Фаза 1, ветка `fix/truth-holes-closure`),
оба флага пока **default OFF**:
- `FW_STATE_COALESCE` — tick-коалесцирование дельт per-subscriber (120мс, cap 200), `2c2bd721`
- `FW_STATE_QUEUE` — отдельная очередь класса `state` (drop_oldest, QoS `_STATE`), `b2c37e5c`

Live-пара `webcam_sketch` ([аудит](../../audits/2026-07-22_phase1-flip-webcam-sketch.md)):
`system_evict_blocked` **1466→0**, `errors` **1461→0**, доставка **15%→100%**,
`gui_system` **100/100→0**, gui из немого стал отвечать на `get_status`. Безвозвратные
потери **597+/30с → 0**. Искусственный флуд не понадобился — рецепт штормит сам.

**Грабли по пути (Fable-ревью, 2 итерации):** наивное коалесцирование внесло гонку с
БЕСШУМНОЙ потерей до 200 дельт (cap-flush pop под локом + send вне лока при ≥2 мутаторах PM
→ старый конверт обгоняется новым → StateProxy глушит его целиком, gap-детектор молчит).
Закрыто инвариантом «единственный отправитель» (`d1ee9402`) + replay через него же (`d1d3e4ef`).
Урок: unit-тесты и самопроверка гонку НЕ поймали, поймало независимое ревью.

**Task 1.4 ЗАКРЫТ** (2026-07-22, ui_* доказаны кликом через qt-mcp) и подтверждён
повторно закрывающим прогоном Фазы 5 (2026-07-23): `capabilities` отдаёт карточку `gui`,
`get_status(gui)` с pid, `ui_tap`/`ping`(`events_sent=9, errors=0`)/`untap` — все OK.
Прогон всех 49 инструментов: 49 OK / 0 SUSPECT / 0 NA
(`docs/audits/2026-07-23_phase5-full-sweep.md`).

Осталось: флип дефолтов и **удаление флагов** — Фаза 6, см.
[[feedback-flags-must-not-become-crutches]]. **Пока флаги OFF, шторм возвращается:**
живой прогон без них 2026-07-23 дал `never_drop_loss_total`=1702 за ~45 с, из них
`StateStore` put=1871/lost=1687 (счётчик Ф4.3 называет душителя поимённо).

Смежное: [[project_backend_ctl_framework_module]], [[project_webcam_sketch_freeze]],
[[project_telemetry_coherence_remediation]].

Также вскрыто там же: `incarnation` НЕ бампается на `process.restart` (pid сменился,
epoch 0→1, incarnation 0→0) — fence на этой полосе рестарта обезоружен; отдельный трек.
