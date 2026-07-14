# Handoff — фаза G код готов, next = объединённое Fable-ревью

**Дата:** 2026-07-14 · **Ветка:** `feat/mem-module-consolidation` (tip `2faf6fba`, база от main `0a1cd566`)

## Состояние: весь код фазы G (хвост) готов, НЕ смержен

Владелец решил: ревью и merge — **одним заходом на всю фазу** в конце (не по задаче). Ветка копит
хвост фазы G. Гейты зелёные: **фреймворк 4634 passed / 36 skipped · sentrux 9/9 · ruff/pyright чисто · qex переиндексирован**.

Готово на ветке (все за флагами дефолт-off = бит-в-бит):

| Задача | Суть | Коммиты |
|--------|------|---------|
| **G.H** консолидация памяти | владение слотом → фасад `FramePool`/`LoanLedger` (`memory/pool/`); reader-side → `FrameReader`/`ShmFrameReader` (`memory/reader/`); `FrameShmMiddleware` = чистый транспорт (держит пул+reader через DI); снос мёртвого `index_usage`/`find_free_index`; **ADR-SRM-013**; module-contract на оба фасада (Protocol+README+contract-тесты) | `4bf21346` `819129e7` `41447c9a` |
| **G.9** GC + аллокации | `GcDiscipline` (`process_module/lifecycle/gc_discipline.py`, `gc.freeze` за `FW_GC_FREEZE`, сборка по расписанию `FW_GC_SCHEDULED` measurement-gated); `AllocProfiler` (`generic/alloc_profile.py`, tracemalloc soak-инструмент); per-frame Pydantic-free зафиксирован тестом (двойная конверсия снята G.5) | `9a381900` |
| **G.8** drain воркера | `IdleWorker.is_busy`; `WorkerManager.drain_worker`/`drain_and_remove`; `worker.drain` команда; «нет полукадров при detach» (drain=пауза+дождаться кадра→detach→stop) | `c3050f1b` |

Побочно: **G.F** — задача «единый реестр feature-флагов» заведена (16 `FW_*` разбросаны литералами;
свести в `config_module/feature_flags.py`, НЕ ConfigStore; отдельная ветка после merge, до flip G.7).

## Что дальше (порядок владельца)

1. **Объединённое Fable-ревью всей фазы G** (директива: см. память `project_phase_g_final_review`) —
   честная **балльная** оценка, before/after, vs коммерч. best practices (iceoryx2/DDS loan-publish,
   seqlock, claim-check). Оси: архитектура · паттерны · **модульность** · **эффективность** ·
   **безопасность** · стиль · согласованность. С советами.
   - **ВАЖНО:** ось «эффективность/перф» честно закрывается ТОЛЬКО после G.7-соака (числа FPS/p99/
     аллокаций с флагами on). Сейчас — 6/7 осей по коду, перф помечать **pending G.7**.
   - Дифф хвоста фазы: `git diff 0a1cd566..2faf6fba`. «Вся фаза» также включает G.1–G.6 (уже в main).
   - Формат: 8-угловое (риск-финдеры по памяти/конкурентности на Sonnet) + свод-оценка.
2. **G.7** flip флагов on → soak оба рецепта → числа в baseline.md (перф-вердикт) + резидуалы
   (num_consumers из топологии, E2E release, incarnation-guard, реальный kill-9).
3. **Единый merge** ветки в main.

## Как поднять новую сессию

Память проекта (`.claude/memory/` + `docs/claude/memory/`) уже несёт всё: `project_memory_module_consolidation`,
`project_phase_g_final_review`, `project_feature_flags_registry`. Стартовый промпт новой сессии:

> «Запусти объединённое Fable-ревью фазы G по ветке `feat/mem-module-consolidation` (память
> `project_phase_g_final_review`): честная балльная оценка before/after, 7 осей, vs коммерч. best
> practices, перф помечай pending-G.7. Дифф `git diff 0a1cd566..2faf6fba`.»

Планы: [plan.md](../../plans/2026-07-06_constructor-master/plan.md) (строки G.H/G.9/G.8/G.7/G.F),
[h-memory-consolidation-plan.md](../../plans/2026-07-06_constructor-master/h-memory-consolidation-plan.md).
