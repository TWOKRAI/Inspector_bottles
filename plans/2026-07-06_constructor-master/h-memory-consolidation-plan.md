# H-задача — Консолидация памяти в один модуль (план исполнения)

> Создан 2026-07-14 на закрытии G.5. Директива владельца ([[project_memory_module_consolidation]]):
> **память — ОДИН модуль с фасадом/интерфейсом/взаимозаменяемостью** (в пределе — подмена на
> Rust-библиотеку типа iceoryx2), «без костылей, как полагается». Порядок: **до flip G.7**.
> Основание — вердикт Fable по памяти на ревью G.5 (3 этапа).
> Статусы задач — ТОЛЬКО в [plan.md](plan.md) (этот файл — брифы и порядок).
> Роль: исполнитель **Opus 4.8** (концуррентность loan-протокола = «одно вскрытие»); ревью 8-угловое + Fable.

## 1. Проблема (замерено по коду, не предположение)

Логика памяти размазана по **4 локусам**, из них 2 — вне модуля памяти:

| # | Локус | Что держит | Легитимно? |
|---|-------|-----------|-----------|
| 1 | `shared_resources_module/memory` (`MemoryManager`, `format`, `platform`, `validation`) | формат слота, seqlock, mmap, create/write/read/close | **ДА** — это и есть модуль памяти |
| 2 | `router_module/middleware/frame_shm_middleware.py` | free-list, `_slot_refcount`, `_slot_released`, loan-cursor, reclaim, handle-кэш (~200 строк владения) | **НЕТ** — семантика владения в **транспортном** модуле |
| 3 | `process_module/generic/pipeline_executor.py` | `pending_releases`, порог флаша, батч release | частично (координация — ок, но опирается на приватности middleware) |
| 4 | `process_module/generic/generic_process.py` | проводка handler'ов `_handle_shm_release`/`_handle_shm_reclaim` | ок (проводка) |

**Мёртвый первый учёт занятости.** `MemoryManager` уже объявляет `release_memory`/`find_free_index`
и держит `index_usage` (`memory_index_usage`), но пишет туда только `0` — «used=1» никто не ставит,
`find_free_index` всегда отдаёт слот 0. G.5 построил **ВТОРОЙ** учёт (`_slot_refcount` в middleware)
рядом с недоделанным первым. Это дубль и главный запах.

**Признано в самом коде** (хвосты-указатели на эту задачу):
- `frame_shm_middleware.py:322-324` — «Консолидация памяти (H-задача) заменит это refcount'ом view'ов»;
- `frame_shm_middleware.py:215-227` — «Полная проводка num_consumers — H-задача/G.7»;
- gonка кэша (`_cache_lock` вокруг dict+close) — «синхронизация должна быть внутренним делом объекта».

## 2. Цель и инвариант

Транспорт кадров (`FrameShmMiddleware`) должен стать **чистым адаптером**: держать пул и reader
через DI и делегировать. Вся семантика владения слотом и reader-side view — за **Protocol-фасадом**
в модуле памяти. Тогда замена реализации (боевой Rust/iceoryx2 под тем же Protocol) не трогает
middleware/executor. Контракт слота уже заявлен DDS/iceoryx2-совместимым (G.4) — держим 1:1
`loan/publish/release`.

**Жёсткий инвариант всей задачи:** всё за существующими флагами (`FW_SHM_LOAN_PROTOCOL`,
`FW_SHM_ZERO_COPY`, `FW_SHM_HANDLE_CACHE`, `FW_SHM_OWNER_INCARNATION`), дефолт off → **бит-в-бит
прежнее поведение**. Это рефактор внутренней структуры, НЕ смена поведения. Паритет G.2 обязан
остаться зелёным до/после. Никакой новой семантики — только перенос за фасад + слияние двух учётов.

## 3. Этапы (по Fable-вердикту; риск низкий — за флагами)

### Этап 1 (S/M, ~1–2 дня + перенос ~15 тестов) — FramePool / SlotLedger

**Скоуп:**
1. **Protocol `FramePool`** в `shared_resources_module/memory/pool/` (module-contract: README + Protocol
   + contract-тесты). Сигнатуры **1:1** на существующую логику middleware:
   - `acquire() -> int | None` — свободный слот (refcount==0), loan-cursor; None = исчерпание (drop-на-источнике). ← `_acquire_loan_slot`
   - `commit(idx: int, num_consumers: int) -> None` — на записи ставит refcount=fan-out. ← loan-on-write
   - `release(tickets: list[dict]) -> int` — owner-side декремент по пачке `{index,generation,reader}` c guard'ами (refcount==0/stale generation/dup reader). ← `release_slots`
   - `reclaim(dead_reader: str) -> int` — реклейм займов мёртвого читателя. ← `reclaim_reader`
   - `snapshot_stats() -> dict` — `slots_released`/`slots_reclaimed`/`loan_exhausted` (наблюдаемость → get_stats).
2. **Реализация `LoanLedger(FramePool)`** — перенос `_slot_refcount`/`_slot_released`/`_loan_cursor` +
   generation-guard (`_read_own_slot_generation` остаётся тонким колбэком в middleware ЛИБО передаётся
   в пул как `gen_reader: Callable[[int], int]` при construction — предпочтительно, чтобы пул не знал
   про SHM-format). Решить при проектировании; зафиксировать в ADR.
3. **middleware держит пул через DI** и делегирует: `_acquire_loan_slot`→`pool.acquire()`,
   `release_slots`→`pool.release()`, `reclaim_reader`→`pool.reclaim()`. Счётчики
   `frame_slots_released/reclaimed/loan_exhausted` читаются из `pool.snapshot_stats()`.
4. **Мёртвый `index_usage`/`find_free_index`** — поглотить (стать backing'ом пула) ЛИБО снести с ADR.
   Рекомендация: снести (`find_free_index` имеет 1 caller — `memory_handle.py`, проверить живой ли он;
   реальный free-list теперь у пула). Решение — ADR-SRM-01X.

**Acceptance Этап 1:** паритет G.2 зелёный (флаги off = бит-в-бит); loan-тесты `test_g5d_loan.py`
проходят через делегацию в пул; kill-9 fault-injection (reclaim) зелёный; contract-тесты пула
(acquire/commit/release/reclaim/snapshot + guard'ы); мёртвого `index_usage` больше нет (grep=0) или он
= backing пула; ADR о судьбе `find_free_index`.

### Этап 2 (M) — reader-side за фасад FrameReader / ViewLease

**Скоуп:**
1. **`FrameReader`/`ViewLease`** в `shared_resources_module/memory/reader/` (module-contract): handle-кэш
   (`_shm_handle_cache` + `_cache_lock`) + `frame_view_valid` (post-use re-check G.5.c) уходят за фасад.
   `ViewLease` = view + мета (имя сегмента + поколение на момент чтения) с методом `.valid() -> bool`.
2. **Синхронизация — внутреннее дело объекта:** `_cache_lock` инкапсулируется в `FrameReader`; гонка кэша
   (close под чтением поколения на другом потоке) чинится по построению — executor больше не лезет в
   приватный `_shm_handle_cache`/`frame_view_valid` middleware.
3. **middleware = чистый транспортный адаптер:** `_read_shm_from_actual_name`/`_open_shm_cached` делегируют
   в `FrameReader`. Приватный `_loan_protocol`-доступ снаружи убран (публичный контракт уже есть —
   `loan_protocol_enabled`/`ring_depth`).
4. **Резидуал G.5-фикс-17 (num_consumers из топологии)** — провести подсчёт loan-aware потребителей
   (copy-out терминалы вроде GUI НЕ считать), передать в `commit(num_consumers)`. Закрывает громкий warn.

**Acceptance Этап 2:** middleware не держит SHM-handle-кэш и view-логику напрямую (grep приватностей = 0);
гонка кэша закрыта тестом (close под re-check на другом потоке); zero-copy тракт зелёный; num_consumers
приходит из топологии (fan-out >1 loan-aware → refcount корректен, тест); рост handle-кэша на инкарнацию
под zero-copy ограничен (резидуал G.5) — эвикция view-aware.

### Этап 3 (ОТЛОЖЕН, по триггеру TECH_STACK §7) — Rust-реализация

Замена `LoanLedger`/`FrameReader` на Rust-библиотеку (iceoryx2 и т.п.) = новая реализация под тем же
Protocol; middleware/executor НЕ трогаются. **Не делать сейчас** — только зафиксировать, что Protocol
обязан быть достаточным для такой подмены (это критерий приёмки дизайна Этапов 1–2).

## 4. Порядок закрытия (владелец, 2026-07-14)

Этап 1 → Этап 2 → **инкрементальный qex-reindex** (`/mcp-qex:qex-reindex`) → **8-угловое ревью**
(риск-задача: концуррентность loan-протокола) → **ревью Fable** (директивы: архитектура+эффективность;
память-один-модуль — проверить, что размазанность снята) → merge в main. Формальное ревью до merge —
обязательно ([[feedback_formal_review_before_merge]]).

## 5. Правила (напоминание себе-оркестратору)

- Флаги дефолт off всю задачу — откат = флаг off, бит-в-бит (не менять поведение прод-пути).
- module-contract на оба новых фасада (README + Protocol + contract-тесты) — правило проекта 2.
- Слои импортов: `router → shared_resources` — runtime-local импорт (как сейчас), не top-level
  (coupling не растить; sentrux check_rules должен остаться зелёным).
- Commit-trailers `Why:`/`Layer: framework` обязательны; `Refs: plans/2026-07-06_constructor-master/plan.md`.
- Параллельным git-агентам (если декомпозиция) — `isolation: worktree` от свежего main ([[feedback_parallel_agents_commit_race]]).
- Тесты харнесса — `QT_QPA_PLATFORM=offscreen` ([[feedback_no_qt_popups_offscreen]]).
