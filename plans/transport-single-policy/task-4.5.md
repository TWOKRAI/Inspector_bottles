> Часть плана [`transport-single-policy`](plan.md), Ф4 — [`phase-4-redesign.md`](phase-4-redesign.md) (факты, порядок задач).

### Task 4.5 — Постоянная наблюдаемость пути кадра
**Level:** Middle+ · **Assignee:** developer · **Layer:** framework + backend_ctl
**Goal:** всё, что в разведке 4.3 и у CTO искали одноразовыми хуками, видно штатно через `backend_ctl`
при ~0 стоимости на горячем пути.

**Дизайн:**
1. **CPU процесса точно:** Windows — `QueryProcessCycleTime` (такты → секунды по частоте TSC,
   калибровка один раз на процесс, ≤ 30 мс, **в покое** — замер 4.6: busy-loop под нагрузкой стенда дал
   2.76 ГГц против 3.10 в покое, калибрующий поток вытесняют и CPU завышается на ~12 %); POSIX — `time.process_time()`. **Не psutil** (на Windows
   считает по тикам таймера и прятал нагрузку ×100). Считает heartbeat раз в тик, не горячий путь.
   Поля: `introspect.status → cpu: {cores, seconds_total, method}`, heartbeat `state.cpu.cores`.
2. **Байты SHM:** `bytes_written` / `bytes_read` на процесс — прибавление `nbytes` в точке записи слота и
   в точке успешного чтения (копия или view). В `get_shm_stats` → `state.shm`.
3. **Время плагина:** одна пара `perf_counter` вокруг `PluginRunner.call_process`/`call_produce`, EMA
   (α = 0.1) на плагин → heartbeat `state.plugin_ms.<plugin>`. Трассировка под env не трогается.
4. **Пейсер:** `FramePacer` считает `late` (сколько раз дедлайн уже прошёл); `target_hz`,
   `achieved_hz`, `late` → heartbeat и `introspect.status`.
5. **Очереди:** `introspect.queues` отдаёт `{qtype: {size, maxsize}}` и `chain_queue` отдельно.
6. **Кольца:** `introspect.router_stats` → `rings: {key: {depth, name}}` на процесс.
7. Всё новое проходит через существующий путь `get_shm_stats` / heartbeat / `introspect.*`; новых
   инструментов `backend_ctl` не добавлять (урок ultra-ревью: сначала живой потребитель).
8. **Ожидание в очереди (добавлено 2026-09-30, цель владельца — [[project-capacity-planning-goal]]):**
   метка времени при постановке в `chain_queue` (`DataReceiver`) и при выемке executor'ом → EMA
   `queue_wait_ms` на процесс в heartbeat. Без него «очередь 50 полна» не отличает «медленный плагин» от
   «медленного транспорта»: сумма `transport + queue_wait + plugin_ms` должна объяснять задержку кадра.
9. **Экспорт `frame_restore_failures`** (из 4.4 итерация 2) — рядом с `frame_stale_drops` в
   `router_manager.py` (`_mw(...)`) и `heartbeat/telemetry.py`.

**Acceptance:**
- [ ] CPU: на стенде 1080p 100 fps `cores` каждого процесса отличается от эталона
      (`QueryProcessCycleTime` снаружи, метод `cpu_truth.py`) не больше чем на 5 %.
- [ ] Байты: на 480p у процесса, пишущего один кадр 640×480×3 на сообщение, `bytes_written` растёт на
      921 600 × число записанных сообщений (литерал).
- [ ] Плагин со `sleep(0.010)` показывает `plugin_ms` в [9, 13].
- [ ] Пейсер 100 Гц под нагрузкой 15 мс на кадр: `late` растёт, `achieved_hz` < 70.
- [ ] `introspect.queues` для data: `maxsize` = 50 (литерал, до 4.7).
- [ ] Стоимость: CPU стенда 480p 25 fps с новыми полями — не больше +1 % к базе (три прогона).
- [ ] Плагин со `sleep(0.030)` при потоке 50 fps: `queue_wait_ms` растёт, а `plugin_ms` остаётся в [29, 33] —
      задержка приписана очереди, а не плагину.

#### Решения лида перед запуском (2026-09-30, инвентарь Explore по `8c…`/`e285fdf5`)

Бриф исполнителя — ≤ 6 файлов и ≤ 10 RED, поэтому 4.5 режется на три механизма; у каждого свой tester до кода.
Части независимы по файлам, кроме `telemetry.py` (a, c — разные функции) и `builtin_commands.py` (b, c — разные
хэндлеры); сливает лид.

**Отступления от дизайна выше:**
- **Частота тактов — из реестра `~MHz`, без калибровки.** Замер лида: i5-12500H, `~MHz` = 3110; занятый поток даёт
  0.998 / 0.995 / 0.988 ядра на окнах 0.03 / 0.3 / 2 с. Калибровка busy-loop в каждом ребёнке при старте стенда
  как раз и есть «не в покое» (−12 % в 4.6). Калибровка — только запасной путь, если ключа нет.
- **Пейсер:** `achieved_hz` и `target_hz` уже публикуются (`effective_hz`, `target_interval_ms` из
  `CycleMetricsRecorder`). Нового — только счётчик `late`.
- **`queue_wait_ms` и `pacer_late` — поля воркера** (`workers.<w>.*`) через штатный `get_cycle_metrics()` →
  `WorkerManager.get_worker_status` → `build_worker_telemetry`, а не `state.*`: у heartbeat нет доступа к
  executor'у, а канал воркера уже есть. `plugin_ms` — в `state.plugin_ms.<плагин>`: `PluginRunner` один на процесс
  (общий у producer и executor, `generic_process.py:240`), в поле воркера он задвоился бы.
- **Кольца:** список `rings: [{key, name, depth}]` (ключ `key` не уникален между middleware'ами процесса).

**4.5a — поля воркера: ожидание в очереди, опоздания пейсера.**
`pacing.py` (`FramePacer.late` +1, когда `nxt < now`), `source_producer.py` / `idle_worker.py` (`pacer_late` в
`get_cycle_metrics`), `data_receiver.py` (три `put` кладут `_StampedBatch(list)` с `enq_ts = perf_counter()`),
`pipeline_executor.py` (после `get` EMA α = 0.1 `queue_wait_ms`, чужой батч без метки — не считается),
`heartbeat/telemetry.py` (`declare_metric` `queue_wait_ms`, `pacer_late`, проброс в `workers.<w>`).

**4.5b — поля процесса: CPU, время плагина, ёмкость очередей.**
Новый `heartbeat/cpu_clock.py` (Windows `QueryProcessCycleTime` / `~MHz`, POSIX `time.process_time`,
`method` = `cycles` | `process_time`), `plugin_runner.py` (пара `perf_counter` только вокруг `plugin.process` /
`plugin.produce`, EMA α = 0.1 под lock, снимок `plugin_ms()`), `generic_process.py` (публичные `plugin_runner`,
`chain_queue`), `process_heartbeat.py` (`state.cpu.cores` по дельте между тиками, `state.plugin_ms`, метрики
`cpu`, `plugin_ms`), `builtin_commands.py` (`introspect.status → cpu: {cores, seconds_total, method}`;
`introspect.queues → queues: {qtype: {size, maxsize}}, chain_queue: {size, maxsize}`, `maxsize` у mp-очереди —
`_maxsize` CPython).

**4.5c — транспорт: байты, отказы восстановления, кольца.**
`frame_shm_middleware.py` (`bytes_written` += `frame.nbytes` в `_Ring.write_and_publish` после успешной записи;
`bytes_read` += `arr.nbytes` в `_read_ref`, только `arr is not None`; оба под одним lock middleware'а;
`ring_info()`), `router_manager.py` (`get_shm_stats`: `shm_bytes_written`, `shm_bytes_read`,
`frame_restore_failures`; `get_ring_info()`), `heartbeat/telemetry.py` (`bytes_written`, `bytes_read`,
`restore_failures` в `state.shm`), `router_module/tests/test_shm_stats_narrow.py` (`NARROW_KEYS`),
`builtin_commands.py` (`introspect.router_stats → rings`).

#### ✅ Статус 4.5 — 2026-09-30: СЛИТА `14fdf123`

Пять частей: a/b/c (developer на Sonnet, tester до кода у каждой), d `transport_ms` (добавлена после ревью: межпроцессная
очередь data не мерилась ничем), e `bytes_mapped` (лид соло — правка счётчика по ревью, ~20 строк). Инъекции лида
25: все по прогнозу после починки двух пустых тестов автора (CPU-окно, `late` через `reset()`); выжили предсказанные
B2/C5 — снятый lock у счётчиков под GIL тестом не ловится. Ревью: итерация 1 REQUEST_CHANGES (блокер — CPU не
мерился под гейтом прототипа), итерация 2 APPROVE_WITH_NITS ([1](../../docs/reviews/2026-09-30_task-4.5-review.md),
[2](../../docs/reviews/2026-09-30_task-4.5-review-iter2.md)). ADR-PM-050.

**Живьём (стенд-worktree на SHA, замок `measure`, A = `89336393`, B = `dadd9918`):**
- CPU изнутри (`state.cpu`) против тактов снаружи, 1080p 100 fps: **−1.4…+1.2 %** по пяти процессам (два прогона).
  На малой нагрузке (480p, 0.05–0.2 ядра) внутреннее ниже на 2–9 % (≤ 0.02 ядра) — причина не найдена.
- Стоимость, 480p 25 fps, по 5 прогонов: A медиана 0.619 ядра (0.612–0.626), B медиана 0.607 (0.575–0.738) —
  **−1.9 %**, в пределах шума; один выброс B +19 % равномерно по всем процессам (состояние машины, не код).
  Горячий путь по замеру ревьюера < 1 мкс на кадр.
- **Что поля уже сказали о стенде 1080p 100 fps** (B, 30 с) — первое сырьё для 4.8:
  processor `color_mask` 8.4 мс + `blob_detector` 6.7 мс = 15.1 мс на кадр при бюджете 10 мс, 1.75 ядра;
  `queue_wait_ms` у processor **1110 мс** (кадр ждёт больше секунды в chain_queue); renderer `render_overlay` 11.6 мс;
  цепочка 54–58 Гц; у камеры `pacer_late` 42 за прогон; stale 821 / torn 1247 у processor.
