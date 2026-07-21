---
name: project-live-verification-2026-07-21
description: "Охота на баги ЗАКРЫТА фиксами в тот же день — 17 находок починено (ветка fix/bug-hunt-live-findings, 10 коммитов); A-10 опровергнута; открыты LIVE-3 + дыры backend_ctl"
metadata:
  node_type: memory
  type: project
  originSessionId: 7bcc64af-e20c-4d51-b2ac-880ae1ee517c
  modified: 2026-07-21T07:09:38.935Z
---

Сессия 2026-07-21: живая верификация аудита через backend_ctl + фиксы всех подтверждённых находок командой агентов (3 Sonnet + Opus teamlead, потом ещё 4 волны). Итоги в docs/audits/2026-07-20_bug-hunt.md §9-10.

**Починено (17):** C-1, C-2, H-1, H-2, H-3, M-1, LIVE-1, LIVE-2, A-1..A-9, A-11(рядом), A-12, A-13, A-14. Ключевое — **LIVE-2 release-on-evict (ADR-RTR-010)**: вытеснение кадра из полной data-очереди теряло loan → кольцо умирало навсегда; теперь транспорт шлёт release владельцу через system-почту (single-thread инвариант пула цел). Блокер webcam-soak Ф3 снят, но live-репро фикса НЕ прогнан.

**Опровергнуто:** A-10 (release сериализован одним message_processor-тредом), A-11 в цитированной строке (set(keys) — C-level bulk).

**Открыто:** LIVE-3 (вечный ханг main после shutdown, 1 заблокированный тред — нужен py-spy); 5 дыр backend_ctl (§9); новые кандидаты — worker_pool_executor коллизия имён при resize, _event_queue unbounded, test_constants.py hikvision, красный test_history_graph.

**Why:** статические находки закрыты живыми доказательствами и фиксами за один день; охота → верификация → фикс — рабочий конвейер.

**How to apply:** следующая сессия начинается с webcam-репро LIVE-2 (кольцо seg должно пережить TEED-загрузку, счётчик frame_loans_released_on_evict) → soak обоих рецептов на исправленном коде → LIVE-3 py-spy. Ветка fix/bug-hunt-live-findings не смержена в main — сначала живая проверка.
