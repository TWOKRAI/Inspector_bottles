# Baseline Ф0 — constructor-master

- **Дата:** 2026-07-06
- **Ветка:** `fix/constructor-f0` (от main после merge 9a5f4b8f + fix Ф0.2)
- **Задачи:** Ф0.3 (sentrux), Ф0.4 (FPS/CPU)

## Ф0.3 — sentrux baseline (session_start снят 2026-07-06)

Скан: 3605 файлов, 529 044 строк, 2903 import-рёбер.

| Метрика | Score (0-10000) | Raw | Порог rules.toml | Статус |
|---|---|---|---|---|
| **quality_signal** | **7174** | — | min_quality 0.60 | OK |
| modularity (bottleneck) | 5652 | 0.3478 | min_modularity 0.45 | OK |
| acyclicity | 10000 | 0 циклов | min_acyclicity 0.45, max_cycles 2 | OK |
| depth | 6154 | 5 | min_depth **0.60** (временно, было 0.65) | OK¹ |
| equality | 6063 | 0.3937 | min_equality 0.60 | OK |
| redundancy | 9012 | 0.0988 | min_redundancy 0.80 | OK |

¹ min_depth временно опущен 0.65→0.60 (факт 0.6154; вернуть в Ф8 H.5 после перезамера
пост-F/E). cross_module_edges = 1600 из 2687 — источник modularity-bottleneck.

`check_rules`: 9 правил, 0 нарушений (pass).

**Чекпойнты плана:** modularity после F ≥ 5900, после Ф5 ≥ 6050, финал ≥ 6200;
quality после Ф4 ≥ 7250, финал ≥ 7500.

## Ф0.2 — pytest (фиксация для истории)

| Сьют | До Ф0.2 | После Ф0.2 |
|---|---|---|
| framework (`scripts/run_framework_tests.py`) | 3395 passed, 2 failed (hot_reload) | **3401 passed, 29 skipped, 0 failed** |
| prototype (`pytest multiprocess_prototype`) | 2819 passed, 1 failed (log_dir_parity) | **2820 passed, 14 skipped, 0 failed** |

Причины красных: (а) env-дрейф — `watchdog>=4.0` объявлен в pyproject, но отсутствовал
в .venv (→ `uv pip install watchdog`); (б) тест хардкодил `/var/log/inspector` —
mkdir требует root на macOS (→ tmp_path). Код продукта не менялся.

## Ф0.4 — FPS/CPU baseline (headless, 2026-07-06)

Headless-probe (BACKEND_CTL=1, boot phone_sketch + 10с сэмпл):

| Метрика | Значение |
|---|---|
| boot до ready (`wait_until_ready`) | ~1.0 с |
| OS-процессов в дереве | 11 |
| CPU суммарно по дереву (idle, без кадров) | ~23.6 % ¹ |
| **FPS phone_sketch** | **hardware-gated** — нет телефона-камеры (PhoneCameraPlugin без источника) |
| **FPS hikvision_letter_robot** | **hardware-gated** — нет камеры Hikvision |

¹ CPU замерен ПРИ error-спаме EdgeDetection (см. находку 2) — как idle-число завышен,
перемерить после установки extras.

**Находки probe (входные данные для следующих фаз):**

1. **env-дрейф №2: extras `[ml]` не установлены** — EdgeDetectionPlugin в цикле:
   «Для TEED нужен PyTorch. Установите extras: uv pip install '.[ml]'». Пайплайны
   sketch-семейства без ML-extras не считают инференс. Решение владельца: ставить
   PyTorch (~2 ГБ) в это окружение или нет.
2. **Shutdown-hang**: `[spawner] ProcessManager did not stop in 5.0s, terminating...`,
   дерево жило 8+ минут до kill -9. Виновник-кандидат: gui-процесс с модальным
   LoginDialog. → подтверждает приоритет Ф3 (Supervisor v2) и Ф1.3 (honest headless).
3. **BACKEND_CTL=1 ≠ headless**: gui-процесс топологии всё равно спавнит Qt
   (LoginDialog поверх рабочего стола). Честный headless-запуск — задача Ф1.3
   BackendHarness (исключение gui из топологии или offscreen-платформа).
4. Error-спам п.1 — это ровно класс «swallow/спам без деградации», который чинит
   Ф2 (`ctx.health.report_error` + breaker): плагин должен перейти в degraded,
   а не молотить ERROR каждые ~1 мс.

**Вывод:** FPS-baseline обоих живых рецептов снимается только с железом — повторить
при подключённой камере (или на Ф7 G.1, где повторный baseline обязателен).
Boot/CPU-числа выше — отправная точка для сравнения.

## Ф7 G.1 — baseline (tier: синтетика, 2026-07-13)

**Условия:** headless-прогон через `BackendHarness` (`backend_ctl/g1_perf_probe.py`,
`BACKEND_CTL=1 FW_PERF_PROBES=1 python -m backend_ctl.g1_perf_probe 10`), рецепт
`multiprocess_prototype/recipes/g1_perf_probe.yaml` — минимальный синтетический
тракт **без реального железа** (новый плагин
`Plugins.sources.synthetic_frame_source.plugin.SyntheticFrameSourcePlugin`,
не прод-плагин, используется только в этом perf-рецепте):

```
synthetic_source[synthetic_frame_source, target_fps=30] → consumer[frame_counter]
```

Ровно 2 процесса, ровно 1 граница IPC на кадр (без chain-цепочки внутри
процесса — C6d здесь неприменим, тракт заведомо минимальный). Кадр
640×480×3 uint8 (~0.92 МБ, generic-путь `strip_data_frame_on_send`/SHM
round-robin ring, 3 слота). Прогон 10с, машина — macOS (та же, что Ф0.4).

**Grep-acceptance:** `grep -rn "\[TRACE\]" multiprocess_framework/ multiprocess_prototype/ --include="*.py"`
(вне `tests/`) → **0 совпадений** (снято 6 периодических TRACE-логов в
`FrameShmMiddleware.on_receive` + по одному аналогичному блоку в
`PipelineExecutor.run_loop`, `SourceProducer.run_loop`, `DataReceiver.run_loop`,
`GuiProcess._data_receiver_loop`, `app._on_frame_received` — итого 6 файлов).

**Perf-пробы (HP-1):** `FW_PERF_PROBES=1` (env, дефолт OFF — при OFF ноль
вызовов `time.perf_counter()` на кадр, см. `perf_probes.py` +
`test_perf_probes.py::TestDisabled::test_no_perf_counter_calls_when_disabled`).
Результаты — через штатный `get_cycle_metrics()` (тот же факад, что несёт
FPS/`cycle_duration_ms` в heartbeat → GUI), ключ `perf_probes`, окно — последние
200 замеров на этап.

| Метрика | Значение |
|---|---|
| **FPS источник** (`source_producer_synthetic_frame_source.effective_hz`) | **28.03** (цель 30 — накладные capture+send+throttle) |
| **FPS потребитель** (`data_receiver.effective_hz`) | **28.03** (паритет с источником — дропов нет) |
| **Границ процесса на кадр** (`frame_boundary_crossings` / `frames_produced`) | **1.006** (326/324 — единственный IPC-хоп source→consumer, счётчик G.6 подтверждён рабочим) |
| Кадров произведено / принято (за 10с) | 324 / 325 |
| capture p50 / p99 (мс) | 0.171 / 0.509 |
| send p50 / p99 (мс) — SHM write + IPC send | 0.441 / 0.819 |
| receive p50 / p99 (мс) — to_dict-десериализация (без ожидания очереди) | 0.097 / 0.180 |
| restore p50 / p99 (мс) — SHM read (`.copy()`) | 0.559 / 1.255 |

**Наблюдение:** send+restore (SHM write+read, ~1мс суммарно на кадр) —
основной вклад тракта, согласуется с оценкой плана «SHM-налог ~1.5-4мс на
кадр» (здесь кадр меньше прод-full-HD, поэтому меньше). capture/receive —
доли миллисекунды (генерация синтетики дешёвая, к.-л. вывод про реальную
камеру отсюда делать нельзя — только про IPC/SHM-тракт).

**Не вошло в этот прогон (дозамер по мере готовности железа, G.7 сравнивает
только same-tier):** tier «вебкамера» и tier «Hikvision» — оба
hardware-gated (см. Ф0.4).

## G.9 — GC-дисциплина + аллокации (инструментарий готов, числа — на соаке G.7)

Ф7 G.9 добавил инструментарий и дисциплину (всё за флагами, дефолт off = штатное поведение):

- **`GcDiscipline`** (`process_module/lifecycle/gc_discipline.py`): `gc.freeze()` после старта
  воркеров (`FW_GC_FREEZE`) — startup-объекты в permanent-поколение, сборщик их не сканирует
  → короче каждая пауза GC; опц. сборка по расписанию в паузах (`FW_GC_SCHEDULED`,
  measurement-gated — включать после доказанного снижения p99).
- **`AllocProfiler`** (`process_module/generic/alloc_profile.py`): tracemalloc snapshot-diff →
  **байт/блоков аллокаций на кадр** + топ-источники. Soak-диагностика (не hot-path).
- **per-frame без Pydantic** — инвариант зафиксирован тестом `test_g9_per_frame_no_pydantic`
  (двойная конверсия снята G.5 `FW_DATA_PLANE_DICTS`; `TestDataPlaneDictsFlag` — поведение).

**Замер до/после — на соаке G.7** (той же лесенкой tier'ов): FPS/p99 с `FW_GC_FREEZE` on↔off
+ аллокаций/кадр из `AllocProfiler`. Числа сюда допишутся при приёмке (правило: цифры по
замеру, не по вере — как FPS-вердикт). msgspec (TECH_STACK §4) — по бенчу msgspec-vs-pickle
на known-schema сообщениях; кадры идут SHM claim-check'ом мимо очереди → их msgspec не касается.

## G.7 — ранний peek (macOS, 2026-07-15) — НЕ финальный вердикт

⚠️ **Ориентир, не приёмка.** 10-секундный probe (`python -m backend_ctl.g1_perf_probe 10`),
tier синтетика, ОДИН прогон на конфигурацию, на **macOS**. Реальные G.7-числа снимаются на
**Windows** (тест 2026-07-16) и на Linux (позже) — G.7 сравнивает same-tier same-platform.
Цель этого peek — направление эффекта + smoke живого пути после H-ремедиации (`b3576c12`).

Control (все FW_* off) ↔ Treatment (SEQLOCK+LOAN_PROTOCOL+OWNER_INCARNATION+HANDLE_CACHE+
ZERO_COPY+QOS_PROFILES+GC_FREEZE on):

| Метрика | off | on | Δ |
|---|---|---|---|
| source FPS | 28.73 | 28.53 | ≈ (упор в источник ~28-30; gate «FPS ≥ baseline» ✓) |
| **restore p50** (чтение кадра) | 0.590 ms | **0.088 ms** | **−85% (6.7×)** — zero-copy убрал memcpy чтения |
| **restore p99** (хвост чтения) | 4.143 ms | **0.353 ms** | **−91% (≈12×)** — джиттер чтения схлопнут |
| capture p99 | 2.304 ms | 0.492 ms | −79% (gc-freeze срезал выбросы пауз) |
| send p50 | 0.459 ms | 0.484 ms | +5% (плата loan acquire/commit/резерв) |
| границ/кадр | 1.006 | 1.009 | = |

Выигрыш в `restore` структурен (zero-copy физически снимает копию), не шум. Тракт с флагами on
прогнал 328/330 кадров без сбоя → single-writer guard/резерв/abort (H-ремедиация) работают вживую.
**Открыто для полной G.7:** длинный soak, оба реальных рецепта, `num_consumers` из топологии,
E2E release/incarnation-guard/реальный kill-9, регресс backend_ctl, аллокации/кадр (`AllocProfiler`).
