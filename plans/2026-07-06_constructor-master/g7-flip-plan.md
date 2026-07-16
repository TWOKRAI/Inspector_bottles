# G.7 — флип лесенкой с числами (план исполнения)

> Создан 2026-07-15 на финальном Fable-ревью фазы G (вердикт APPROVE, before 4.8 → after 8.0/10;
> «7.5 по эффективности» держится ТОЛЬКО отсутствием чисел под флагами — этот план их даёт).
> Статусы задач — ТОЛЬКО в [plan.md](plan.md) (здесь брифы и порядок). Числа — в [baseline.md](baseline.md).
> Правило всей фазы сохраняется: **каждый шаг откатывается флагом off бит-в-бит.**

## 0. Цель и критерий успеха

Довести тракт G из dark-launch в прод **по одному флагу за шаг**, с замером на каждом шаге,
и закрыть G.7-резидуалы fault-инъекциями. Успех фазы: полный набор флагов on, длинный soak
обоих живых рецептов зелёный, все счётчики потерь объяснимы, FPS/p99 не хуже baseline.

**Допуски (same-tier, по G.1-лесенке tier'ов: синтетика → вебкамера → Hikvision):**
- FPS ≥ baseline − 2%;
- p99 latency ≤ baseline + 5%;
- счётчики `state.shm.*` (torn / stale_drops / loan_exhausted / pickle_fallbacks /
  queue_data_evicted) = 0 или объяснимы (записать почему);
- `slots_released` РАСТЁТ при активном loan (release-контур замкнут — урок ревью G.5).

Шаг не прошёл → флаг off (бит-в-бит), находка в план, лесенка стоит до фикса.

## 1. Метрики и инструменты (одинаково на всех шагах)

| Что | Чем | Куда |
|---|---|---|
| FPS, p50/p99 цикла | `FW_PERF_PROBES=1` + `get_cycle_metrics` (пробы ВКЛЮЧЕНЫ и в baseline-замере — одинаковый overhead ⇒ честные дельты) | baseline.md, таблица шага |
| Счётчики потерь | `backend_ctl` → `introspect.router_stats` + `state.shm.*` (снапшот раз в 5 мин soak-скриптом) | лог soak + baseline.md |
| Границы/кадр | `frame_boundary_crossings` (G.6) | baseline.md |
| Аллокации/кадр, GC-паузы | `AllocProfiler` (G.9b, tracemalloc snapshot-diff) — только на длинном soak Фазы 3 | baseline.md (закрывает acceptance G.9) |
| RSS/CPU процессов | ProcessMonitor / системный монитор | лог soak |

Рецепты: `phone_sketch` (вебкамера/телефон) и `hikvision_letter_robot` (пром-камера; робот
для soak кадрового тракта НЕ обязателен). Per-шаг — короткий замер 10 мин/рецепт;
длинный soak — только на полном наборе (Фаза 3).

## 2. Фаза 0 — прекондиции (до первого флипа)

| # | Задача | Бриф | Усилие |
|---|---|---|---|
| 0.1 | Merge `feat/mem-module-consolidation` → main | Вердикт ревью APPROVE; gate 4698 passed | S |
| 0.2 ✅ | **G.F реестр флагов** (по плану владельца: ПОСЛЕ G.H, ДО flip) | `config_module/feature_flags.py`: все `FW_*` задекларированы раз (имя/default/doc/**requires**) + `list_flags()` для приёмки. Requires-связи из ревью: `ZERO_COPY ⊃ HANDLE_CACHE ⊃ OWNER_INCARNATION`, `GC_SCHEDULED ⊃ GC_FREEZE`, loan осмыслен с zero-copy. Устранить: два независимых чтения `FW_SHM_OWNER_INCARNATION` (manager + middleware), не-FW имя `MULTIPROCESS_USE_KIND_CHANNELS` (алиас в реестре, старое имя поддержать). **Финальный флип Фазы 4 = смена default'ов В ОДНОМ файле**.<br>**✅ DONE 2026-07-15** (ветка `feat/feature-flags-registry`): 18 флагов в реестре, приоритет ctor>env>default, typo→KeyError, requires-граф + advisory `validate()`, alias. Коммиты: `23c8d680` ядро+19 contract-тестов / `fa99177e` миграция 16 сайтов в 12 файлах (double-read OWNER_INCARNATION устранён, 1934 passed) / `0b89466b` boot-лог активных маркеров в оркестраторе (LoggerManager, +3 теста). Гейт: **4720 passed / 6 skipped / 2 pre-existing Windows-fail**. Плоскость наблюдаемости (логи/статы/ошибки) НЕ трогалась — она отдельна (ADR-CRM-006). | M |
| 0.3 ✅ | Проводка supervisor → `shm_reclaim` | Хендлер у владельца ЕСТЬ (G.5.e), отправителя НЕТ: ProcessMonitor по confirmed-death процесса шлёт `{type: shm_reclaim, data: {dead_reader}}` всем процессам (у кого нет пула — no-op). Без этого «реальный kill-9» Фазы 3 не проверить.<br>**✅ DONE 2026-07-15** (коммит `5501dc36`): `ProcessMonitor._broadcast_shm_reclaim()` в `_handle_dead_process`, гейт `FW_SHM_LOAN_PROTOCOL` (off = бит-в-бит), `queue_type=system`; +3 теста, process_manager 71 passed. | S/M |
| 0.4 ✅ | `multiprocess_prototype/backend/tests` в регулярный гейт | validate.py / CI job — характеризация живых рецептов больше НЕ гниёт молча (была RED на main с merge G.3/G.4, поймано ревью).<br>**✅ DONE 2026-07-15** (коммит `8fe4d5b4`): `testpaths` (+pyproject) и отдельный шаг в `ci.yml` job `tests`; CI гонял только `modules/` → прод-рецепты выпадали. 5 passed headless. | S |
| 0.5 ✅ | Метрика размера handle-кэша | `ShmFrameReader`: `cache_size` в статы → `state.shm.*` (1 строка + тест). Под zero-copy эвикция отключена — на soak следим за ростом на инкарнацию (резидуал G.5).<br>**✅ DONE 2026-07-15** (коммит `86902cb7`): `cache_size`→`frame_handle_cache_size`→`router.get_stats`→`state.shm.cache_size`; guard расширен `cache_size==0` (off = бит-в-бит); +4 теста, 350 passed. | S |
| 0.6 ✅ | Baseline-перезамер all-off | Оба рецепта, `FW_PERF_PROBES=1`, всё остальное off → строка «шаг 0» в baseline.md. Референс «до» всей лесенки.<br>**✅ DONE 2026-07-15**: строка «ШАГ 0 all-off (Windows, синтетика)» в baseline.md — source/consumer 21.35/21.39 fps, restore p50/p99 0.789/1.382 мс, границ/кадр 1.004. Tier'ы вебкамера/Hikvision hardware-gated (сравнение same-tier). | S |

## 3. Фаза 1 — лесенка per-flag (короткий замер на каждом шаге)

Порядок = зависимости (каждый следующий шаг включается ПОВЕРХ предыдущих, ничего не выключаем):

| Шаг | Флаг | Что проверяем кроме чисел |
|---|---|---|
| 1 ✅ | `FW_DATA_PLANE_DICTS` | Чистый CPU-выигрыш (нет Message/Pydantic-пересборки на кадр); ждём p99 ↓ или =.<br>**✅ DONE 2026-07-16** (синтетика, Windows): стадия `receive` 0.123 → **0.001** мс p99 — структурный коллапс пересборки Message на consumer'е (`return_messages=False`); FPS 21.35 → 21.32 (=), границ/кадр 1.007 (=), дропов нет. Gate ✓. Числа + свежий same-session control — baseline.md «ШАГ 1». Откат `=0`. |
| 2 ✅ | `FW_SHM_SEQLOCK` | Формат слота +8 байт; `torn` появляется как метрика и = 0 в спокойном режиме.<br>**✅ DONE 2026-07-16** (синтетика): `frame_torn_reads` = **0** (живая метрика), перф-нейтрален, FPS 21.34 (=). Gate ✓. baseline.md «ШАГИ 2-4». |
| 3 ✅ | `FW_SHM_OWNER_INCARNATION` | Имена `{slot}_{owner}_{pid}_{inc}`; рестарт camera_0 (restart_policy уже в рецепте) → читатели следуют за новым именем, замороженного кадра нет (**incarnation-guard E2E — резидуал**).<br>**✅ DONE 2026-07-16** перф-часть (синтетика): перф-нейтрален (наименование), torn=0, FPS 21.38–21.42 (=). **Incarnation-guard E2E → Фаза 2** (2-проц тракт рестарт писателя не гоняет). Gate перф ✓. |
| 4 ✅ | `FW_SHM_HANDLE_CACHE` | Снятие open/mmap/close на кадр — ждём заметное p99 ↓ на cross-process чтении; `close_errors`=0.<br>**✅ DONE 2026-07-16** (синтетика): **restore p50/p99 0.503/1.39 → 0.136/0.43 мс (−73%/−69%)** структурно; `frame_handle_cache_size`=3 (=глубина кольца, стабилен → утечки нет), fallback'ов 0. Gate ✓. |
| 5 ✅ | `FW_QOS_PROFILES` | Кольцо 3→4 (или `extras.frame_ring_depth` из рецепта — проведено ревью-фиксом `94e40b76`); data-очереди drop_oldest со счётчиком; system никогда молча.<br>**✅ DONE 2026-07-16** (синтетика): кольцо 3→4 подтверждено (`frame_handle_cache_size` 3→4), `queue_data_evicted`=0 (нет overload), `system_evict_blocked`=0. Gate ✓. |
| 6 ✅ | `FW_SHM_ZERO_COPY` | View вместо копии на data-plane; `stale_drops`=0 в спокойном режиме; GUI остаётся copy-out.<br>**✅ DONE 2026-07-16** (синтетика): **restore p50/p99 0.438/1.386 → 0.049/0.163 мс (−89%/−88%)** — крупнейший структурный выигрыш; `frame_stale_drops`=0. Gate ✓. |
| 7 ✅ | `FW_SHM_LOAN_PROTOCOL` | **E2E release ЖИВЫМ транспортом — резидуал:** `slots_released` растёт, `loan_exhausted`=0, free-list не голодает (num_consumers из топологии, GUI-only владельцы без пула).<br>**✅ DONE 2026-07-16** (синтетика): `frame_slots_released`=**288** (растёт, release-контур замкнут), `frame_loan_exhausted`=0. Реальный kill-9 (`slots_reclaimed`) → Фаза 2 (2.1). Gate ✓. |
| 8 ✅ | `FW_USE_KIND_CHANNELS` (alias `MULTIPROCESS_USE_KIND_CHANNELS`) | Kind-каналы доставки (G.2); **регресс-тест: socket-канал backend_ctl жив**; аудит opt-out'ов `manages_own_reply` (S5-остаток).<br>**✅ DONE 2026-07-16** (синтетика): socket 8766 жив во всех прогонах ✓, перф-нейтрален. `loan_exhausted`=4 в 1-м прогоне → 0 на двух реранах (транзиент, не регресс). Аудит `manages_own_reply` → резидуал. Gate ✓. |
| 9 ✅ | `FW_GC_FREEZE` | GC-паузы ↓ (сравнить распределение p99); RSS стабилен.<br>**✅ DONE 2026-07-16** (синтетика, полный набор on): FPS 21.34 (=), restore p99 0.207 стабилен (control-выброс 33.7мс не повторился). RSS/аллокации → soak Фазы 3 + AllocProfiler. Gate ✓. |
| 10 ⏸ | `FW_GC_SCHEDULED` | ТОЛЬКО если после шага 9 p99-выбросы от GC остались (measurement-gated по дизайну G.9); смотреть RSS-тренд на длинном soak.<br>**⏸ MEASUREMENT-GATED — OFF 2026-07-16**: после шага 9 GC-выбросов p99 НЕТ (синтетика) → условие активации не выполнено. Прогон с флагом on регресса не дал, но флаг оставлен OFF; решение — на soak Фазы 3. НЕ активирован по своему гейту (не провален). |

Отдельно, вне лесенки: `FW_SHM_PREFIX_CLEANUP` — прогнать 3 skip-теста на WSL/Linux-CI
(нит G.3); на Windows no-op. На POSIX зафиксировать правило: **мультикамера без
`FW_SHM_OWNER_INCARNATION` запрещена** (cleanup_stale_shm молча unlink'ает живой сегмент
тёзки — находка ревью).

## 4. Фаза 2 — fault-инъекции на полном наборе (все флаги on)

| # | Сценарий | Ожидание |
|---|---|---|
| 2.1 ✅ | **kill -9 читателя** под нагрузкой | Supervisor (0.3) → `shm_reclaim` → `slots_reclaimed` > 0, поток кадров живёт, исчерпания нет.<br>**✅ DONE 2026-07-16** (синтетика, полный набор): `slots_reclaimed` 0→**3**, source FPS 21.34→21.32 (не блокирован), consumer авто-рестарт (running), torn/pickle=0. `loan_exhausted +102` = back-pressure в окне смерть→восстановление. Резидуал закрыт. baseline.md «Фаза 2». |
| 2.2 ✅ | kill -9 писателя посреди записи | Нечётный generation на следующем цикле → `seqlock_recovered` + WARNING, слот не отравлен.<br>**✅ DONE частично 2026-07-16**: писатель авто-рестарт (running), consumer выжил (running), `torn_reads`=0, порчи нет — инвариант держится. Seqlock-recovery counter не воспроизведён (kill не попал в mid-write) → детерминированный write-hold+kill = резидуал Фазы 3. |
| 2.3 ⏳ | Switch рецепта под нагрузкой (B-7) | Wire re-issue без стейл-кэша; кадры после switch идут; сегменты не текут (`release_owned_memory`).<br>Механизм решён (Task 7, [[project_recipe_hotswap]], `5cd23192`); dedicated switch-fault-probe (switch-драйвер через backend_ctl) — отдельный заход. |
| 2.4 ⏳ | Медленный потребитель (искусственная задержка в плагине) | Loan: громкий drop-на-источнике + `loan_exhausted` растёт, камера НЕ блокируется; после снятия задержки — самовосстановление.<br>Back-pressure ЭМПИРИЧЕСКИ показан 2.1 (dead reader → drop, FPS ровный); dedicated slow-consumer (delay-knob в `frame_counter` + самовосст.) — отдельный заход. |
| 2.5 ✅ | Teardown-шум | `ValueError: I/O operation on closed file` — ИЗВЕСТНЫЙ graceful-stop долг, НЕ блокер G.7, отдельная задача (см. [[project_graceful_stop_debt]]).<br>**✅ ЗАФИКСИРОВАН 2026-07-16**: наблюдён `ProcessManager did not stop in 5.0s` при teardown; watchdog добивает дерево, не виснет. Не блокер. |

## 5. Фаза 3 — длинный soak + приёмка

> **Фундамент (2026-07-16):** мультикамерный SHM подтверждён на 2 синтетических камерах
> (`dualcam_synth.yaml` + `g7_dualcam_probe`, обе 21fps параллельно, `owner_incarnation` развёл
> SHM-сегменты владельцев, потерь 0 — baseline.md «Фаза 3 (фундамент)»). Остаток ниже +
> camera_0 → реальная вебкамера (идея владельца: вебкамера + синтетическая имитация 2-й камеры).

1. Оба рецепта, полный набор флагов, **≥ 2 ч каждый** (overnight — по решению владельца).
2. Снимаем: FPS/p99-тренд, все `state.shm.*`, `cache_size` (0.5), RSS-тренд (утечки),
   AllocProfiler «аллокаций/кадр» (закрывает acceptance G.9), GC-паузы.
3. Приёмка G.7 (acceptance из plan.md): все gate-метрики зелёные; drop-счётчики видимы;
   socket backend_ctl жив; num_consumers из топологии подтверждён live.
4. **Флип дефолтов** — в реестре G.F (одно место), характеризация «флаг off = прежнее»
   остаётся зелёной; откат любого флага = env `=0`.
5. **Замер потолка 50-60 fps** (вопрос владельца 2026-07-15): синтетический источник на
   60 fps (+ вебкамера, если умеет) на полном наборе флагов → headroom-отчёт в baseline.md.
   Что смотреть особо: (а) бюджет стадии = 16.7 мс — какие процессы не влезают (Hough/ML —
   кандидаты на прореживание/событийность, уже так в hikvision-рецепте); (б) глубина кольца:
   4 слота на 60 fps = всего 66 мс окна — цепочке с zero-copy view надо успевать до wrap,
   иначе `stale_drops` растёт → для 60 fps камер рекомендация `extras.frame_ring_depth: 6-8`
   (проведено ревью-фиксом `94e40b76`); (в) пейсинг источника: sleep-пейсинг на Windows
   грубый (~15.6 мс квант) — на 60 fps источник должен быть camera-driven (блокирующий grab
   SDK), не sleep-driven; (г) GC/аллокации: на 60 fps цена per-frame мусора ×2.4 — шаги 9-10
   лесенки обязательны, не опциональны.
6. Числа и вердикт — в baseline.md + строка «G.7 ✅» в plan.md.

## 6. После G.7 (отдельные задачи, НЕ блокируют флип)

| # | Задача | Бриф |
|---|---|---|
| P1 | **Роль потребителя — в топологию** | num_consumers по атрибуту потребителя на wire (loan-aware / copy-out), не по именам `chain_targets`/конфигу; `wire.configure`-тракт получает num_consumers из того же источника (сейчас дефолт 1 мимо топологии — находка ревью); per-item `target`-override: задокументировать несовместимость со статическим refcount ИЛИ считать по факту отправки |
| P2 ✅ | **Join двух камер** | `camera_id` в ключ корреляции JoinInspectorManager (было `seq_id` — кадры двух камер тихо подменяются); `_FRAME_ID_MODULO` 121 → ≥ 100_000; либо развести `data_type`.<br>**✅ ПОЧИНЕНО 2026-07-16** (коммит `83d7d48a`): ключ буфера `(camera_id, seq_id)` вместо `seq_id`; +3 теста (fanin/30 + wiring/40 passed), backward-compat (camera_id=None → прежнее). camera_id несут source-плагины + переносят overlay (line_filter). Рецепты приёмки: `dualcam_synth`/`dualcam_webcam`. Гигиена-остаток: prod camera_service/hikvision/phone_gateway `_FRAME_ID_MODULO` 121→100_000 (мооты TTL-выселением, но лучше выровнять). |
| P3 | Каталог `multiprocess_framework/tests/` | 7 collection-errors (`ProcessManagerCore`) — чинить ВМЕСТЕ с нейминг-рефактором (решение владельца), затем в гейт |
| P4 | GUI: процесс → N дисплеев | Сейчас последняя привязка молча побеждает (1 процесс = 1 дисплей-слот) — снять ограничение для мульти-дисплея |

## 7. Правила исполнения

- Один агент, строго последовательно (правило Ф7); лесенка не перепрыгивается.
- Каждый шаг: флип → 10-мин замер обоих рецептов → строка в baseline.md → коммит
  `docs(plans)` со статусом. Числа НЕ «по вере» — только замер (директива владельца).
- Hardware-tier по доступности железа: шаги гоняются минимум на вебкамере (phone_sketch);
  Hikvision-tier — как камера подключена; сравнение только same-tier.
- Любая правка кода по находке шага — отдельным `fix(...)`-коммитом с тестом, лесенка
  продолжается после зелёного гейта.
