---
name: live2-release-on-evict
description: LIVE-2/LIVE-1 fix — вытеснение из полной data-очереди теряло loan → смерть SHM-кольца; release-on-evict через shm_release IPC владельцу
metadata:
  type: project
---

LIVE-2 (CRITICAL, был блокером G.7 Ф3) + LIVE-1 (HIGH) закрыты на ветке fix/bug-hunt-live-findings.

**LIVE-2 — вытеснение из полной data-очереди теряло loan-тикет → перманентная смерть кольца.**
`QueueRegistry.remove_old_if_full` (drop_oldest) выбрасывал кадр-сообщение вместе с его SHM-займом; release слал только дочитавший исполнитель → за вытесненное не релизил НИКТО → free-list owner'а исчерпан навсегда (skipped растёт со скоростью FPS).

Выбранный дизайн — **release-on-evict, вариант (а)** (не TTL-reclaim (б)):
- `QueueRegistry.send_to_queue(..., on_evict)` — опциональный колбэк `(evicted_item, process)`. Слой памяти о кадрах НЕ знает (чистый Callable); хук регистрирует `RouterManager` (знает про кадры).
- `RouterManager._on_frame_evicted` шлёт владельцу `shm_release(evicted=True)` ЧЕРЕЗ system-почту (тем же `_handle_shm_release`→`release_slots`, что и штатный release).
- **Почему через почту, а не прямой release_slots:** вытеснение идёт на треде-ПИСАТЕЛЕ (send-путь), штатный release — на message_processor. Прямой вызов гонялся бы за refcount (пул lock-free по контракту single-thread-release). owner==self → почта в свою же system-очередь → свой message_processor → тот же тред → инвариант цел. owner≠sender (fan-in) → IPC владельцу.
- **generation-agnostic** `LoanLedger.release_evicted` (тикет вытеснения поколения не несёт; вытеснение всегда относится к текущему займу — слот под refcount>0 писателем не переиспользуется). Отдельный счётчик `slots_released_on_evict` → `frame_loans_released_on_evict` в get_stats.
- **flags-off = ноль оверхеда:** `RouterManager._frame_loan_active` (пересчёт при (un)register_frame_middleware) — при OFF on_evict НЕ передаётся, сигнатура send_to_queue бит-в-бит прежняя.
- **Страховка** — В1 post-use re-check (pipeline_executor `_frame_views_valid`→seqlock generation): преждевременное освобождение → writer перезапишет → drift → drop, НЕ порча. «Занижение refcount безопасно» (§8.2 G.5) — подтверждено кодом.

**LIVE-1 — канал system_events осиротел, errors PM росли ~13-57/с.**
Убрана регистрация канала в `process_communication.register_router_channels` (потребителя нет: 0 handler'ов типа system_event, 0 читателей очереди). `emit_event` гейтит рассылку на наличие канала (`if ch("system_events")`) → отсутствие канала само разоружает send; локальные подписчики + `_event_queue` целы.

Файлы: shared_resources_module/{queues/core/manager.py, memory/pool/{loan_ledger,interfaces}.py}, router_module/{core/router_manager.py, middleware/frame_shm_middleware.py}, process_module/{generic/generic_process.py, communication/process_communication.py}. Прогон: shared_resources 322/router 357/process 813 passed. Коммит НЕ делал (запрет задачи).
