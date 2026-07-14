---
name: project_g5_ownership_decision
description: Ф7 G.5 — владелец решил делать ОБА примитива владения слотами сразу (кольцо+seqlock + owner-mediated loan/release), GUI остаётся copy-out
metadata:
  type: project
---

Ф7 G.5 (hot-path, «главный риск фазы» — вобрал протокол владения из G.4 по Варианту A) — решения владельца 2026-07-14:

**Примитив владения слотами — «надо и то и то, сразу как полагается, чтобы потом не беспокоиться».** G.5 делает ПОЛНЫЙ frame-pool сразу, а не минимально:
- **В1 (глубокое кольцо + seqlock)** — безопасный ПОЛ by-construction: kill-9 читателя безвреден (нечего реклеймить), torn исключён seqlock'ом G.3.
- **+ поверх В3 (owner-mediated loan/release/refcount + reclaim-on-death, контракт 1:1 с iceoryx2 loan/publish/release)** — для строгого never-drop + back-pressure к источнику. Композируются: В1 = страховка, В3 = детерминированное владение.
- **В2 (refcount через `multiprocessing.Lock`) — отклонён** (kill-9 под локом = deadlock пула в CPython без robust-mutex).
- Осознанное усиление скоупа против минимальной рекомендации Fable (В1-сейчас + В3-по-триггеру). Расходится с обычным «fewer layers / не переделывать» ([[feedback_fewer_layers]]) — здесь владелец выбрал больше-сейчас ради «потом не беспокоиться».
- **Риск-нот:** release-IPC на кадр на читателя нельзя слать синхронно на hot-path → обязателен батчинг/async-агрегация release'ов, иначе IPC съедает выигрыш zero-copy.

**GUI-путь остаётся copy-out** («запомнить; если надо — надо, если нет — как лучше»). Zero-copy (`restore_frame(copy=False)`) только на data-plane цепочки инспекции; GUI = `copy=True` (Qt держит пиксели дольше кадрового окна). Пересмотр GUI-zero-copy — отдельный заход по триггеру. Попутно закрыть нит G.3 (регистрация GUI `_recv_frame_mw` в stats).

**Размер SHM-слота при переменной форме кадра** (grayscale/resize/crop внутри pipeline) — «вроде бы работало», подтверждено кодом (buffer.py): слот под max_shape, per-image заголовок с фактическими h/w/c; меньший кадр влезает и читается по факту; превышение max/смена dtype → громкий pickle-fallback (G.3d), не порча. Внесено инвариантом+тестами в g5-execution-plan §1/§6.

Критерий владельца для фазы: **«лучшая архитектура — универсальная, эффективная, безопасная»** (та же линза, что в вердикте Fable G.4). Детали — [[project_arch_boundaries_plan]], план `plans/2026-07-06_constructor-master/g5-execution-plan.md`.

**Прогресс исполнения (ветка feat/constructor-f7, всё за флагами default-off):**
- G.5.a ✅ (4c0616f1) — снятие двойной конверсии data-plane, `FW_DATA_PLANE_DICTS`.
- фикс пре-существующего G.4 ring-теста (c26d4d62) — env-утечка маскировала красный.
- G.5.b ✅ (41b0895c) — zero-copy чтение view, `FW_SHM_ZERO_COPY`; гейт на handle-кэш; GUI явно copy-out; переменная форма кадра by-design.
- G.5.c ✅ (a45a782c) — **В1-пол by-construction**: post-use re-check поколения в PipelineExecutor (между _execute_chain и _send_results) → drift → drop батча + `frame_stale_drops`→heartbeat. Zero-copy тракт теперь БЕЗОПАСЕН (read-moment seqlock + hold-duration re-check); kill-9 читателя безвреден.
- **G.5.d/e — ОСТАЛОСЬ**: В3 owner-mediated loan/release/refcount + back-pressure (release батч/async, не на per-frame пути) + kill-9 fault-injection обоих уровней. Самый крупный/рисковый блок — делать отдельным сфокусированным заходом «как полагается», без костылей.
