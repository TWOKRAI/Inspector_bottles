# replace-blueprint-hotswap — корректный hot-swap процессов + SHM при переключении рецепта

**Статус:** Task 1-3+5+6 DONE+verified (стоп 35→5с / SHM-teardown / config-трансформация / SHM-инкарнация); Task 4 переосмыслен; **Task 7 — ОТКРЫТЫЙ БЛОКЕР**: hot-swap'нутые процессы не инициализируются (новая камера не открывает устройство, кадры не текут → картинка замёрзла). Развилка A (доделать hot-swap) vs B (чистый рестарт worker-подсистемы boot-путём, рекомендуется).
**Ветка:** продолжение `fix/recipe-v3-engine-decouple` (или новая `fix/replace-blueprint-hotswap`)
**Тип:** fix (framework, hot-swap robustness) — fix-forward, продукт-first
**Связь:** обнаружено после `recipe-v3-engine-decouple` — фикс активации впервые довёл «Загрузить» до реального `replace_blueprint`, обнажив старую проблему.

## Симптом
«Загрузить» другой рецепт → система «зависает» на ~35с (нет кадров, нет реакции),
SHM-сегменты текут после каждого переключения.

## Root cause (диагностировано faulthandler + backend-лог, ПОДТВЕРЖДЕНО)
1. **Серийный стоп.** `replace_blueprint` ([process_manager_process.py:736-742](../multiprocess_framework/modules/process_manager_module/process/process_manager_process.py))
   зовёт `_stop_and_cleanup_process` → `registry.stop_one(name, 5s)` В ЦИКЛЕ. Каждый
   процесс: stop_event.set() → join(5s) → не погас → terminate. 7 процессов × 5с ≈ **35с**.
   GUI event loop при этом ЖИВ (faulthandler: main в `app.exec()`) — «фриз» = backend-teardown.
2. **shutdown уже параллельный, hot-swap — нет.** `registry.stop_all`/`_join_all`
   ([process_registry.py:201-244](../multiprocess_framework/modules/process_manager_module/core/process_registry.py))
   взводит ВСЕ stop_event разом → один общий дедлайн → ~5с суммарно. Комментарий там
   прямо: «Раньше 7×5с≈35с». Этот паттерн не довели до `replace_blueprint`.
3. **Утечка SHM.** `_stop_and_cleanup_process` зовёт `mm.release_process_memory(name)` —
   метода НЕТ (warning «memory_manager не имеет release_process_memory»). MemoryManager
   ([memory/core/manager.py](../multiprocess_framework/modules/shared_resources_module/memory/core/manager.py))
   имеет только `close_memory(process, shm)` и `release_memory(process, shm, index)`.
4. **Worker не гаснет за 5с (deeper).** Процессы (camera_0, region_splitter, …) не выходят
   по stop_event за 5с → terminate. Вероятно worker-loop блокируется на `queue.get()` без
   таймаута / чтении камеры / backpressure (мы видели «pipeline overload, queue full > 2.0s»),
   не поллит stop. Требует проверки `GenericProcessApp`/worker loop.

## Цель (требование владельца)
Все процессы корректно останавливаются; SHM очищается и перестраивается при КАЖДОМ
переключении; новые нужные ячейки создаются. Без костылей.

## План реализации

### Task 1 — параллельный стоп в replace_blueprint (лечит «зависание», 35с→~5с)
- Добавить `ProcessRegistry.stop_many(names: list[str], timeout) -> dict[str,bool]` по
  образцу `stop_all`/`_join_all`: (a) `stop_events[name].set()` для всех; (b) один общий
  дедлайн `time.monotonic()+timeout`, `join(remaining)` по каждому; (c) terminate/kill
  стражгеров; (d) вернуть карту «погас ли каждый».
- В `replace_blueprint` заменить серийный цикл `_stop_and_cleanup_process` на:
  `stop_many(to_replace)` → затем для каждого `remove_process` + SHM-release (Task 2).
- Сохранить rollback-семантику (partial failure → `_restore_from_snapshot`).
- **Файлы:** `core/process_registry.py` (+stop_many), `process/process_manager_process.py`
  (replace_blueprint, _stop_and_cleanup_process разделить на stop-фазу и cleanup-фазу).

### Task 2 — реализовать release_process_memory на MemoryManager (чистка SHM)
- Добавить `release_process_memory(self, process_name: str) -> None`:
  1. для каждого `memory_name` в `list(self._local_handles.get(process_name, {}))`:
     `self.close_memory(process_name, memory_name)`;
  2. `self._process_state_registry.unregister_process(process_name)` (PSR
     [state/process_state_registry.py:126](../multiprocess_framework/modules/shared_resources_module/state/process_state_registry.py));
  3. подчистить `self._local_handles.pop(process_name, None)`, `self._local_meta.pop(...)`.
- Добавить в интерфейс `IMemoryManager` ([memory/interfaces.py](../multiprocess_framework/modules/shared_resources_module/memory/interfaces.py)).
- PM уже вызывает `release_process_memory(name)` — просто заработает.
- Опц.: при остаточных stale-сегментах — `buffers/cleanup.py::cleanup_stale_shm(known_names)`.

### Task 3 — новые ячейки при старте нового процесса (проверка)
- При replace новый процесс регистрируется (`shared_resources.register_process`,
  process_manager_process.py:773) и на старте создаёт свои SHM (`create_memory_dict`).
  Убедиться: после Task 2 (release старого) нет коллизии имён/stale-хэндлов → новые
  ячейки создаются чисто. Добавить тест: switch A→B→A не оставляет лишних сегментов.

### Task 4 — worker stop-responsiveness (deeper, чтобы «все останавливались» честно)
- Проверить worker-loop `GenericProcessApp`: poll stop_event с таймаутом на blocking-точках
  (`queue.get(timeout=...)`, чтение камеры, SHM-ожидание). Цель — graceful-стоп < 5с без
  terminate. Если backpressure (full queue) держит — дренировать/прерывать по stop.

## Реализация (DONE)

- **Task 1 — параллельный стоп.** `ProcessRegistry.stop_many(names, timeout)` (process_registry.py)
  по образцу `stop_all`/`_join_all`: взвести все stop_event разом → общий дедлайн → terminate/kill
  стрэгглеров. `replace_blueprint` шаг 6: серийный `_stop_and_cleanup_process` заменён на
  `stop_many(to_replace)` + `_cleanup_process_resources(name)` (cleanup-фаза отдельно). Rollback-
  семантика сохранена (`stop_results.get(name)==False → rollback`). 35с→~5-6с.
- **Task 2 — release_process_memory.** Реализован на `MemoryManager` + добавлен в `IMemoryManager`:
  close+unlink (owner) всех блоков процесса → `unregister_process` в PSR → подчистка
  `_local_handles`/`_local_meta`. PM уже звал метод через getattr — заработал.
- **Task 3 — новые ячейки.** Тест `test_switch_a_b_a_no_leak` + `test_release_then_recreate_same_name`:
  после release имя свободно, пересоздание процесса создаёт свежие SHM без коллизий/утечки.

### Task 4 — переосмыслен (worker-loops УЖЕ корректны)
Проверка показала: `data_receiver` (`_receive(timeout=0.05)`), `source_producer` (chunked
smart-sleep 0.01с + poll), `pipeline_executor` (`chain_queue.get(timeout=0.05)`),
`worker_manager.stop_all_workers` (параллельный, общий дедлайн) — ВСЕ честно поллят stop_event
за ≤0.1с. Остаточные «did not stop in 5.0s» — НЕ в worker-loop, а в teardown процесса
(release камеры / Windows queue-feeder join / shutdown-ordering). Это отдельная глубокая тема,
worker-циклы трогать НЕ нужно. С Task 1 каждый процесс гасится параллельно → суммарно ~5-6с
(а не 7×5с), что снимает симптом «зависания». Honest sub-5s teardown — отдельный follow-up.

## Тесты (DONE)
- `test_process_registry.py`: `test_stop_many_stops_all_named_parallel`, `test_stop_many_unknown_process_returns_false`.
- `test_memory_manager.py::TestMemoryManagerReleaseProcess`: closes_all_blocks, unknown_noop,
  switch_a_b_a_no_leak, release_then_recreate_same_name.
- `test_replace_blueprint.py`: MockProcessRegistry.stop_many добавлен; 21 тест зелёный.
- Регресс: 827 passed по 4 модулям (process_manager, shared_resources, worker, process).

## Task 5 — DONE: «переключает, но картинка не меняется на новую» (корень #2)

**Симптом:** процессы переключаются (Task 1-2 работают), но изображение в GUI не
обновляется на вывод нового рецепта.

**Root cause (investigator, HIGH):** `replace_blueprint` передавал **raw recipe-process
dict** (`process_name`/`process_class`/`chain_targets`/`plugins` на ВЕРХНЕМ уровне)
напрямую в `create_and_register`. Но процесс ждёт **вложенный `config`**
(`config.plugins`/`config.chain_targets`/`queues`) — этот формат создаёт boot-путь через
`SystemBlueprint.build_configs() → process()`. Без трансформации новые процессы стартовали
**пустыми**: PluginOrchestrator не создавался (plugins=[]), нет маршрутов (chain_targets=[]),
нет очереди `data` → данные не текли в GUI.

**Fix:** `_build_proc_dicts(new_blueprint)` в `process_manager_process.py` — повторяет boot
(`SystemBlueprint.model_validate → build_configs() → process(cfg)`). Вызывается в
`replace_blueprint` ДО остановки (fail-fast на невалидном blueprint). Step 7 использует
готовые proc_dict'ы (class + вложенный config), регистрирует канонический формат.
Registry-независимо (полные `plugin_class` пути); `displays`/`wires` игнорируются
(SchemaBase `extra='ignore'`). **Hot-swap == boot** (единый путь сборки proc_dict).

**Проверено на реальном color_inspect.yaml:** camera_0→detector→painter→**gui** (painter
chain_targets=['gui'] → кадр идёт в GUI), плагины 1/2/1/1, очереди system+data. Тесты:
`test_chain_targets_and_plugins_nested_into_config`, `test_missing_process_class_defaults_to_generic`
(boot-консистентный дефолт GenericProcess вместо старого hard-fail). 22 теста replace_blueprint зелёные.

## 🔴 Task 6 — БЛОКЕР (live 17:39): SHM «File exists» + restart-loop → картинка не меняется

После Task 5 процессы поднимаются с правильным config (плагины+маршруты), НО картинка
по-прежнему не обновляется. Live-лог вскрыл следующий слой:

**Симптом:** `[ProcessManager] [MemoryManager] SharedMemory create failed for 'camera_0_frame':
[WinError 183] File exists: 'camera_0_frame_27872_0'` + новые процессы переподнимаются ~каждые 10с.

**Анализ:**
- `27872` = PID самого ProcessManager. Имя SHM = `{base}_{PM_PID}` (`_unique_base_name`,
  shm.py:88) — СТАБИЛЬНО в течение жизни PM.
- На Windows `unlink()` — no-op (shm.py:4,148); сегмент живёт пока открыт хоть один handle.
  `cleanup_stale_shm` (shm.py:35) делает open+close — НЕ освобождает, если держит другой handle.
- При переключении старый `camera_0_frame_27872_0` не освобождён вовремя (terminate закрывает
  handles АСИНХРОННО; либо PM/consumer ещё держит) → новый `camera_0` (тот же PM-PID) упирается
  в «File exists» → буфер кадра не создан → камера не отдаёт кадры → дисплей замёрз.
- Гипотеза restart-loop: камера падает на init из-за SHM → ProcessMonitor видит unresponsive →
  restart → снова коллизия → цикл. Один фикс SHM может закрыть ОБА (камера встаёт → кадры идут →
  нет рестартов).

**Task 5 это ОБНАЖИЛ (прогресс):** до Task 5 новые процессы были пустыми shell'ами и SHM вообще
не создавали → не было «File exists», но и картинки. Теперь процессы реально работают и упёрлись
в следующий слой.

**Фикс (DONE):** `create_shm_blocks` ([shm.py](../multiprocess_framework/modules/shared_resources_module/memory/platform/shm.py))
теперь при `FileExistsError` пересоздаёт набор со СВЕЖЕЙ инкарнацией имени (до 3 попыток):
`_unique_base_name(base, fresh=True)` → `{base}_{pid}_{inc}`. Старый сегмент освободится, когда
ОС закроет handles умершего процесса; новая инкарнация не ждёт это переходное окно. Consumer'ы
читают ФАКТИЧЕСКИЕ имена (memory_names в PSR / shm_actual_name в frame_data) → суффикс прозрачен.
Не костыль: старый сегмент НЕ течёт навсегда (terminate → ОС закрывает handles → free), просто
не блокируем новую камеру на окне освобождения. Тест: `test_recreate_with_live_segment_succeeds_fresh`.

**Гипотеза по restart-loop:** до Task 5 «рестарты» были пустыми shell'ами без heartbeat'а
(unresponsive). После Task 5 причиной стал SHM-краш камеры (fail init → unresponsive → restart).
Фикс SHM должен убрать и эту причину. Если restart-loop останется после live-теста — отдельная
проработка (ProcessMonitor grace-период после replace). _live-smoke pending._

## 🔴 Task 7 — ОТКРЫТЫЙ БЛОКЕР: hot-swap'нутые процессы не инициализируются (картинка всё ещё замёрзла)

Live 17:53-54 (после фикса Task 6): SHM «File exists» ушёл (в логе «пересоздан со свежей
инкарнацией»), но картинка по-прежнему не меняется. Лог `camera_0/system.log`:
- Старая камера (color_inspect) остановилась **graceful** в 17:54:08 (CapturePlugin shutdown,
  устройство освобождено) — ДО terminate процесса в 17:54:13. Значит device released корректно.
- Новая камера (region_pipeline, старт 17:54:13) **НЕ залогировала открытие устройства** вообще
  (`CapturePlugin: камера открыта` отсутствует) → камера не отдаёт кадры → дисплей замёрз.
- Цикл ~14с (стоп+старт всех) БЕЗ логов «unresponsive»/«Авто-рестарт» → НЕ ProcessMonitor;
  источник повтора replace неясен (повторные клики? переприменение рецепта?).

**Вывод:** несмотря на корректный proc_dict (Task 5 verified) и SHM (Task 6 verified),
hot-swap'нутые процессы не доходят до рабочего состояния (новая камера не инициализирует
устройство; кадры не текут в GUI). Это следующий, более глубокий слой hot-swap: полная
ре-инициализация/ре-разводка IPC нового набора процессов (heartbeat→PM, data→gui,
inter-stage `output_frames` SHM — ранее видели «output_frames_*_1 not found» в region_splitter).
Нужна LIVE runtime-диагностика (qt-mcp + точечный лог), не статический анализ.

**Стратегическая развилка (на решение владельцу):**
- **(A) Чинить hot-swap до конца** — доразвести IPC/heartbeat/inter-stage SHM для нового
  набора процессов (reuse `wire.setup`? полная ре-регистрация routing_map?). Глубоко,
  ад hoc-сложно, риск новых слоёв.
- **(B) Не hot-swap, а чистый рестарт worker-подсистемы** — при переключении рецепта
  останавливать ВСЕ non-protected процессы и поднимать новый набор ТЕМ ЖЕ boot-путём
  (`SystemLauncher`/`launch.build`), который заведомо корректно разводит routing+heartbeat+SHM.
  GUI/PM остаются. Проще и надёжнее «как полагается»: один путь сборки системы (boot==switch),
  меньше слоёв. Рекомендация — **B** (совпадает с «recipe-driven launch» и «меньше слоёв»).

### Task 7 — уточнение по live 18:08-09 (камера РАБОТАЕТ, блокер — доставка кадров)
- **Камера после hot-swap работает** (`./logs/camera_0`: «камера открыта 640x480» + producer started). Task 5 verified.
- **Межстадийный `output_frames` SHM не читается:** `SHM fallback read failed: output_frames_6592_2 not found` — И НА BOOT (color_inspect, до switch). Consumer (detector/preprocessor) не находит сегмент кадра → цепочка рвётся → GUI не обновляется. Это, похоже, ключевой блокер доставки кадров (шире hot-swap).
- **Многократный replace_blueprint:** Pipeline-таб (Старт/Перезапуск) + Recipes (Загрузить) — НЕСКОЛЬКО точек входа дёргают replace_blueprint, накладываясь → тасование системы (`running→initializing` каждые ~15с). Нужен debounce / единая точка применения.
- **Logging error (I/O on closed file):** `batch_buffer._timer_worker → logger_manager._flush_batch` пишет в закрытый хендлер при teardown — гонка остановки логгера (косметика, но шумит). Кандидат: гасить timer-flush до закрытия каналов.
- **log_dir регресс — ИСПРАВЛЕН** (env INSPECTOR_LOG_DIR в launch.build): hot-swap-процессы снова пишут в logs/prototype_2.

**Переоценка:** доставка кадров через `output_frames` SHM ломается даже без переключения — это не только hot-swap. Рекомендация по-прежнему **B** (чистый рестарт worker-набора boot-путём при switch) + отдельно разобрать `output_frames` SHM read и debounce точек входа replace_blueprint. Требует LIVE per-frame трейса.

## ⚠️ Сложные слои — кандидаты на упрощение (по запросу владельца)

Зафиксировано для отдельной проработки (НЕ в этой ветке):
1. **Dual-format proc_dict.** Recipe-blueprint (плоский: chain_targets/plugins/process_class
   на верхнем уровне) vs runtime proc_dict (вложенный `config`). Многохоповая трансформация:
   `Recipe YAML → SystemBlueprint → ProcessConfig.as_generic_config → GenericProcessConfig →
   ProcessLaunchConfig.build → data_schema.process() → proc_dict`. 6 слоёв на один конверт.
   Кандидат: один канонический трансформер recipe→proc_dict, переиспользуемый boot И hot-swap
   (сейчас boot в launch.py, hot-swap в _build_proc_dicts — логика одна, точки входа разные).
2. **wires в рецепте — мёртвая метаинформация для runtime.** Маршрутизация реально идёт через
   `chain_targets` (имя процесса), а `blueprint.wires` (port-level) — только для валидации/редактора.
   Два представления связей (chain_targets + wires) в одном рецепте → путаница. См. также
   `recipe-format-single-source` Task 1 (display дуализм).
3. **Restart-loop после replace (item #3).** Новые процессы переподнимаются ~каждые 12с
   (ProcessMonitor heartbeat-timeout после hot-swap) + камера не освобождает устройство при
   terminate (`DSHOW ... can't be used to capture by index`) → связано с Task 4 (teardown).
   Кандидат: graceful-release камеры до terminate + grace-период монитора после replace.

## Acceptance
- [x] Переключение рецепта ≤ ~5-7с (нет 35с) — параллельный стоп (Task 1). _live-smoke pending_
- [x] После switch: SHM старых процессов закрыты, PSR очищен, новые ячейки созданы (Task 2+3, тесты).
- [x] switch A→B→A N раз не растит число SHM-сегментов (тест `test_switch_a_b_a_no_leak`).
- [~] processes честно гаснут по stop — worker-loops уже корректны; residual teardown ≤5с → follow-up.
- [x] Тесты: stop_many (parallel), release_process_memory, replace round-trip. [ ] smoke через qt-mcp.

## Заметки диагностики (для реализации)
- faulthandler-инструментация (env `INSPECTOR_FREEZE_DEBUG=1`, dump каждые 6с) — снята из
  app.py после диагностики; при необходимости вернуть тем же блоком в `run_gui`.
- qt-mcp probe доступен по `QT_MCP_PROBE=1` (app.py run_gui) — для smoke кликов.
- Репро: запустить с активным region_pipeline, «Загрузить» другой рецепт → лог backend
  показывает «Process 'X' did not stop in 5.0s, terminating» по одному + «memory_manager
  не имеет release_process_memory».
