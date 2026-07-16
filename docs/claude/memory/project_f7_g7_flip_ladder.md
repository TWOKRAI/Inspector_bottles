---
name: project_f7_g7_flip_ladder
description: "Ф7 G.7 флип-лесенка Фаза 1 ЗАКРЫТА 2026-07-16: 9 флагов движка флипнуты по одному с замером (синтетика/Windows); restore p99 ~1.4→0.2мс; step10 measurement-gated OFF; пробник расширен счётчиками state.shm.*"
metadata:
  node_type: memory
  type: project
---

**Ф7 G.7 флип-лесенка — Фаза 1 (per-flag) ЗАКРЫТА 2026-07-16** (ветка `feat/webcam-sketch-perf`;
коммиты 63c78547 шаг1 / 063cf7ed тулинг / 92b37385 шаги2-4 / ebf5c749 шаги5-7 / 76ad4d5b шаги8-10).
План `plans/2026-07-06_constructor-master/g7-flip-plan.md`, все числа — в baseline.md.

**Что сделано:** по одному `FW_*`-флагу за шаг ПОВЕРХ предыдущих, замер на каждом через
`backend_ctl.g1_perf_probe 12` (tier синтетика, Windows — same-tier референс ШАГ 0). Шаги 1-9
включены, gate ✓ на каждом. Шаг 10 `FW_GC_SCHEDULED` — **measurement-gated OFF** (после gc_freeze
GC-выбросов p99 нет → условие активации не выполнено; решение на soak Фазы 3, НЕ провален).

**Числа (all-off → полный набор on):** restore p99 **~1.4 → 0.2 мс**, receive p99 ~0.15 → 0.004 мс,
FPS без регресса (упор в источник ~21, Windows sleep-пейсинг ~15.6мс квант). Флагманы — zero-copy
(restore −88%, view вместо memcpy) и handle_cache (−69%, снят open/mmap/close на кадр). Все
`state.shm.*` = 0 или объяснимы; `slots_released` растёт (release-контур замкнут); `cache_size`
стабилен (утечки handle нет); socket backend_ctl жив на kind-каналах.

**Тулинг:** `g1_perf_probe` расширен — `_shm_counters()` дампит `frame_torn_reads/stale_drops/
loan_exhausted/slots_released/slots_reclaimed/handle_cache_size/pickle_fallbacks/queue_data_evicted`
(уже агрегированы `RouterManager.get_stats`) для source+consumer; без них seqlock/zero-copy/loan не
загейтить. +5 юнит-тестов чистого хелпера. Счётчики видны и в pull (`introspect.router_stats`), и в
push (`state.shm.*` через heartbeat → StatsManager) — источник один, дубля нет.

**УРОКИ:**
- **Same-session control обязателен** — Windows run-to-run разброс большой (control restore p99 ловил
  одиночный выброс 33.7мс от GC/планировщика на copy-пути). Флип сравнивать со свежим control того же
  окна, не только с записанным ШАГ 0.
- **Счётчик потерь в 1 прогоне ≠ регресс** — `loan_exhausted=4` на шаге 8 (1-й прогон) → 0 на двух
  реранах ⇒ транзиент (миг лага consumer → back-pressure drop-на-источнике, камера не блокнута).
  Перепрогонять, прежде чем гейтить как провал.
- **measurement-gated флаг честно OFF** — gc_scheduled не включать «за компанию»: его гейт (остаточные
  GC-выбросы после freeze) не выполнен на синтетике.

**Фаза 2 (fault-инъекции, 2026-07-16):** 2.1 kill-9 читателя ✅ (`slots_reclaimed` 0→3 reclaim +
авто-рестарт + source FPS ровный; `loan_exhausted +102` = back-pressure в окне смерть→восстановление),
2.2 kill-9 писателя ✅ (авто-рестарт + consumer выжил, `torn_reads`=0, порчи нет — инвариант держится).
Остаток: 2.3 switch под нагрузкой ([[project_recipe_hotswap]]), 2.4 slow-consumer (back-pressure показан
2.1) — dedicated-пробы отдельно; детерминированный seqlock-recovery (write-hold+kill) → Фаза 3. **УРОК
Windows:** `signal.SIGKILL` отсутствует → `harness.kill_child` падал AttributeError; фикс
`psutil.Process(pid).kill()` (TerminateProcess, та же crash-семантика) + ASCII-логи (cp1251-консоль не
кодирует '→'). Ломало и live fault-тесты на Windows (коммит `7d91f95f`, пробник `g7_fault_probe`).

**Фаза 3 (резидуал):** длинный soak обоих ЖИВЫХ рецептов (phone_sketch + hikvision) + AllocProfiler +
флип дефолтов в реестре G.F. Tier'ы вебкамера/Hikvision — по железу. plan.md «G.7 ✅» НЕ ставить до Фазы 3.

Связано: [[project_feature_flags_registry]], [[project_f7_g7_num_consumers]], [[project_f7_g4_done]],
[[project_phase_g_final_review]], [[feedback_logger_error_stats_managers]].
