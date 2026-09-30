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
