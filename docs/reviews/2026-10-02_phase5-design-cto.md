# Разбор дизайна 5.2/5.3 — CTO (Fable), 2026-10-02

Task 5.1 плана [`transport-single-policy`](../../plans/transport-single-policy/phase-5.md). Текст CTO (agentId `aebdaa3b36791e860`, 242k токенов, 39 вызовов, 11 мин), записан лидом дословно; агент без права записи.
База: worktree `.claude/worktrees/t5-lead`, `feat/transport-f5`, HEAD `5dab8565d`. Стенд не поднимался. Три оффлайн-скрипта в scratchpad CTO `cto51/` (`pickle_size.py`, `sched_proto.py`, `check_recipes.py`), вывод цитируется. qex не использовался (индекс устарел).

**Вердикт: дизайн 5.2 и 5.3 принимается с шестью правками.** Три из них меняют текст задач: (1) схлопывание в запись — ДО цепочки, не перед `_send_results`; (2) `transit_ms = 0` обходит планировщик; (3) Q9 — у рецептов два дефекта, и `917ec7ed4` виновен только в одном.

## Решения

### 1. Планировщик — класс фреймворка, запущенный воркером процесса
**Решение.** `ActuationScheduler` живёт в `multiprocess_framework/modules/process_module/generic/actuation_scheduler.py`: чистый класс (heap + часы + колбэк `fire`), без импорта плагинов. `robot_control` создаёт экземпляр и запускает его через `ctx.worker_manager.create_worker("actuation", scheduler.run_loop)` — контракт `IPluginWorkerManager.create_worker` уже есть (`plugins/interfaces.py:35`), `PluginContext.worker_manager` его отдаёт (`base.py:103`). В `IProcessServices`/`PluginContext` новый метод НЕ добавляется: один потребитель — ловушка «неиспользуемый путь = контракт». Lifecycle (pause/stop) — как у остальных LOOP-воркеров. `schedule()` зовёт поток исполнителя, `tick()` — поток воркера: heap под `threading.Lock`; `fire` пишет только счётчики планировщика (`fired_items`, `missed_items`, `late_fires`), поля плагина не трогает.
**Что перевернёт.** Второй решатель с приводом (Modbus/GPIO-плагин) → поднять до `PluginContext.scheduler`. Или замер: воркер под `worker.pause_all` на стенде ломает учёт — тогда планировщик вне WorkerManager.
**Опора.** `grep -rn "import heapq\|class \w*Scheduler\|class \w*Timer" multiprocess_framework/modules --include=*.py` (без tests) → 0: механизма в фреймворке нет. Остальное — рассуждение.

### 2. Схема записи о разрыве — без усечения, чанк 1500, `count=1` несёт оба набора ключей
**Решение.** `build_gap(items) -> list[dict]`: ключи `inspection_status, overflow_marker=True, count, trace_ids, first_capture_ts (min), last_capture_ts (max), reasons: {reason: n}, sources: {source: n}`; `source`/`camera_id`/`reason` — только если единственны у всех входов. Инвариант `len(trace_ids) == count` всегда (пустой `trace_id` остаётся как `""`). Вход может сам быть записью (`count>1`): поля суммируются. Чанк `GAP_CHUNK = 1500`: 3008 → 3 записи (1500/1500/8), Σcount точен, усечения нет. `count=1` несёт и сегодняшние ключи (`trace_id`, `capture_ts`, `reason`), и новые. `build_gap([])` → `ValueError`.
**Что перевернёт.** Владелец требует одну запись на разрыв любой длины → снять `GAP_CHUNK`. Пин точного набора ключей `test_t47d1_marker_contract` должен остаться бит-в-бит → потребителю два пути.
**Опора.** `python cto51/pickle_size.py`:
```
record n=    1 idlen=32: pickle=    356 B
record n= 1078 idlen=32: pickle=  38053 B  per_id=35.3
record n= 1078 idlen=36: pickle=  42365 B  per_id=39.3
record n= 3008 idlen=32: pickle= 105616 B
record n=10000 idlen=36: pickle= 390384 B
single marker msg (today): 255 B; x1078 = 274890 B
```
1078 id → 38 КБ (порог 5.3 ≤ 64 КиБ держится); 3008 (D100) → 103 КиБ > порога, отсюда чанк 1500 (≤ 59 КБ при 36-символьных id). Запись в 7 раз дешевле 1078 сообщений.

### 3. Склейка — в приёмнике по типу (как есть); схлопывание — в исполнителе ДО цепочки; плюс два пропущенных места
**Решение.** `_MarkerBatch`/`_coalesce_markers` в приёмнике не меняются. В исполнителе `_forward_markers`: `records = build_gap(items)` → `out = _execute_chain(records)` → `handled += Σ count` → `_send_results(out)`. «Перед `_send_results`» оставит `robot_control.process` вызванным N раз (цепочка идёт по входу, `_forward_markers:330`), а acceptance требует 1 раз. Два места, которых нет в дизайне лида: (а) post-chain stale (`_run_batch:295-299`) шлёт `stale_markers` напрямую — тоже через `build_gap`; (б) приёмник: `_MarkerBatch`, пришедшая в `on_items_ready`, при `isinstance(pending[-1], _MarkerBatch)` сливается в хвост под `chain.mutex` — в ОБОИХ режимах. Причина (б): `_bound_lag` для маркер-коллекции не выполняется (`_is_frame_collection` → False → `return False`, `data_receiver.py:263`), склейка срабатывает только при приходе КАДРА; поток маркеров без кадров заполняет `chain_queue` (maxsize = `queue_size`, `generic_process.py:262`) по одному и уводит приёмник в блокирующий `put` — механизм P10 у inspector (245 + 1076).
**Что перевернёт.** Тест: 1000 IPC-записей в узел с паузой исполнителя → `chain_queue.qsize()` ≤ 2 без правки (б). Сегодняшний код даст 64 и блокировку.
**Опора.** Чтение `data_receiver.py:263-306, 361-399`, `pipeline_executor.py:246-333`. Рассуждение, прогона нет.

### 4. Формула — в items; `handled` считает Σcount по ВХОДУ `_forward_markers`
**Решение.** `not_inspected_handled += Σ count` входных записей (не выходов цепочки). `born`-счётчики уже в items. Формула ADR-174 п.5 по форме не меняется.
**Что перевернёт.** Плагин с `accepts_markers`, дробящий запись 1→N, — учёт по входу всё равно верен; переворота нет.
**Опора.** Рассуждение; ADR-174 п.4-5.

### 5. Fan-out — рождение одно, доставок N, как 4.7d
**Решение.** `_send_results` шлёт один и тот же dict каждой цели (`pipeline_executor.py:491-519`): pickle на цель, `handled` один раз. Запись без `_shm_views` — `_attach_batch_views` и дверь её не трогают.
**Что перевернёт.** Потребность в per-target `data_type` на записи — нет.
**Опора.** Чтение кода.

### 6. Фронт и вердикт — на решении, не на выстреле
**Решение.** `_write_verdict` и широкая запись остаются в `process()`. `fire` документов не пишет. Промах решается СИНХРОННО в `schedule()` (см. 8), поэтому широкая запись получает `actuation: scheduled|missed|immediate` и `fire_at` в момент решения. Запись о разрыве: одна широкая запись с `count`, `first/last_capture_ts`, `total_not_inspected += count`; фронт `_rejecting` не трогает (ADR-174 п.9).
**Что перевернёт.** Стенд P10: вердиктов после паузы меньше серий брака — запись в 10 с посреди серии спрятала фронт → регистр `front_reset_gap_ms`. Или владелец требует вердикт = подтверждение физического выстрела → отдельный документ `actuation_result`.
**Опора.** `plugin.py:189-195`. Рассуждение.

### 7. Запись `every` через узел `latest` — проходит; склейку сделать независимой от режима
**Решение.** Проход не зависит от режима уже сегодня: IPC-маркер → `_MarkerBatch([item])` без проверки `overflow` (`data_receiver.py:476-478`), под `latest` потолок её не вытесняет (`:335-337`). Оставить. Правка (б) из решения 3 закрывает накопление маркер-коллекций у `latest`-узла.
**Что перевернёт.** Тот же тест из решения 3.
**Опора.** Чтение кода.

### 8. Старение — промах при постановке; `transit_ms = 0` обходит планировщик; часы — `time.time()`
**Решение.** `schedule(fire_at, window_end, count)`: `now > window_end + tolerance` → `missed_actuation += count`, в heap не кладётся, возвращает `missed`; `fire_at < now ≤ window_end + tol` → `fire_at = now`; `late_fires` считает опоздание тика. `transit_ms == 0` (умолчание) → планировщик не зовётся, `fire` синхронно, `missed = 0`. `capture_ts` — `time.time()` (`source_producer.py:188`), сравнение в той же шкале. `capture_ts is None` → `actuation_unscheduled += count`, действие записывается.
**Что перевернёт.** Владелец объявляет `transit_ms > 0` обязательным → 0 = ошибка конфигурации на старте. Прыжок системных часов (NTP) → шторм `missed`.
**Опора.** `python cto51/sched_proto.py` (fake clock, tolerance 20 мс, transit 100 мс):
```
frame      : scheduled
stale frame: missed
gap 1078   : scheduled -> fire_at clamped to now
gap old    : missed
  t=+7.0ms fired ['gap-1078']
  t=+100.0ms fired ['frame-A']
fired_items=1079 missed_items=43 late_fires=0 heap_left=0
time.time distinct values in 200 ms: 305 -> step ~0.656 ms
```
Шаг `time.time()` 0.66 мс — годится для допуска 20 мс. Реальный поток на Windows — сетка 15.6 мс: критерий «`[fire_at, fire_at+2 мс]`» — ТОЛЬКО с подменными часами; живьём мерить `late_fires` и p99 опоздания.

### 9. Два дефекта у рецептов; `917ec7ed4` — причина одного
**Решение.** `check()` на рецептах ДО и ПОСЛЕ `917ec7ed4` (`python cto51/check_recipes.py`, плагины сегодняшние):
```
multi_camera_pre917.yaml: 3 errors   (все три — «Вход ... не подключен», первый плагин процесса)
multi_camera.yaml:        3 errors   (те же три)
inspection_basic_pre917:  6 errors   (1 — color_mask → blob_detector; 5 — «не подключен»)
inspection_basic.yaml:    6 errors   (те же)
dualcam_synth.yaml:       0 errors
```
`git log -- multi_camera.yaml` → 4 коммита, `grep -c wires` в версии до 917 → 0: у рецепта никогда не было `wires:`. `check()` требует провод на каждый вход первого плагина (`_is_covered_by_auto_wiring` при `idx == 0` → False, `blueprint.py:1006`). Дефект A (фреймворк): `validate_chain` (`port.py:210-231`) и `_is_covered_by_auto_wiring` смотрят только предыдущий узел, а рантайм — dict, ключ живёт до перезаписи; одна функция «накопленная доступность» (`wired_inputs процесса ∪ выходы предыдущих узлов`) на оба места. Дефект B (прототип): рецептам нужны `wires:` как у `inspection_full.yaml:171-198` (комментарий `stand.yaml:168-170`, `infer_missing_collectors` выводит join из wires). Выводить провода из `chain_targets` в валидаторе НЕ делать: меняет вывод join-коллекторов, ADR-уровень. Страж: параметризованный тест по `backend/topology/*.yaml` → `check() == []`. Владелец: **новая Task 5.9a, волна 3 (∥ 5.6), Middle (Sonnet), до 5.9**; в `plans/pipeline-node-timing.md` — строка-ссылка.
**OWNER-10.** `dualcam_synth.yaml` НЕ заменяет `multi_camera.yaml`: нет fan-in узла, формула «на узле за двумя камерами» не измерима. Гейт-рецепт двух камер — `scripts/capacity_bench/recipes/stand_dualcam.yaml` (закреплённая копия по конвенции `stand.yaml:1-4`): 2 синтетических источника 1080p → fan-in processor с `extras: {overflow: every}` → inspector → storage/gui, собран из `multi_camera.yaml` после 5.9a. `multi_camera.yaml` остаётся продуктовым рецептом и обязан стартовать; `dualcam_synth.yaml` остаётся пробой g7.
**Что перевернёт.** Плагин, который на рантайме выбрасывает ключи — накопленная модель оптимистична; ловит `FW_PORT_VALIDATE`. Владелец хочет в гейте `camera_service simulator` → расширять `multi_camera.yaml`.

## Не проверено (CTO)
- Живой старт `multi_camera.yaml`/`inspection_basic.yaml` после 5.9a — только `check()` оффлайн. Когда `check()` стал обязательным на старте — по git не искал.
- Pre-917 прогон `check()` сделан с сегодняшними классами плагинов: строка `color_mask → blob_detector` в «pre917» — артефакт; пять строк «не подключен» от плагинов не зависят.
- Второй потребитель `accepts_markers` в `Plugins/` — **проверил лид**: `grep -rn accepts_markers Plugins` → один, `robot_control/plugin.py:68`.
- Решение 3(б) — рассуждение, репродукция «64 и блокировка» не прогонялась; тест в acceptance 5.3 и есть проверка.
- Склейка записи от upstream с локальными маркерами меняет `source` на гистограмму `sources` — **лид**: потребитель `source` один, `robot_control/plugin.py:233` (`origin = {"origin": item.get("reason"), "source": item.get("source")}`); 5.2 читает `sources`, если `source` нет.
- Точность потока планировщика на Windows не измерена; `late_fires` на стенде 5.6 даст число.
- Пилотная гипотеза «разбор дизайна до кода окупается»: разбор нашёл три правки текста задач (3, 8, 9) до строки кода.
