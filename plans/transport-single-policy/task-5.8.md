# Task 5.8 — Пропускная способность: storage первым, пул исполнителя по замеру (ред. 3)

**План:** [`plan.md`](plan.md) · фаза 5 — [`phase-5.md`](phase-5.md).
**История редакций.**
- Ред. 2 (2026-10-03). Ревью спеки стадии 0, раунд 1 — CHANGES REQUESTED, 7 блокеров. Решение владельца 2026-10-03: «storage первым».
- Ред. 3 (2026-10-03). Раунд 2 ревью: противоречия между DESIGN и строками приёмки внутри текста. Все замены внесены лидом. Третьего раунда нет (предел — 2).
- Ред. 1 снята. Она предлагала `WorkerPoolDispatcher` — межпроцессную рассылку. При переполнении та молча выбрасывает старую задачу (`dispatcher.py:214-234`), а обработчика `worker_task_request` нет.

**Почему storage первым (числа первого прогона 5.6, `reports/stand/2026-10-03_first-run/`, 1080p@100, кумулятивно на `s2`).**

| Процесс | `effective_hz` | `lag_dropped_items` |
|---|---|---|
| storage | 53–79 | 840–956 |
| processor, хороший режим | 89–98 | 40–294 |

Причина у storage в коде:
- `_do_flush` вызывает `insert_many([одна строка])` на каждую запись (`Plugins/io/database/plugin.py:173-176`);
- `insert_many` исполняет `execute` на каждую строку (`Services/sql/core/base_repository.py:82-95`);
- `sync_adapter.py:59` коммитит каждый вызов;
- сброс идёт в потоке исполнителя, прямо в `process()` (`plugin.py:127-133`).

Processor зависит от бимодальности цикла: медиана 5.5 мс в хорошем режиме, 12.7–16.5 мс в плохом. При 60 к/с плохой режим оставляет запас около 1 %.

**Порядок:** `5.8s ∥ 5.8a` → базовый замер лида → решение по 5.8b по правилу ниже.

**Порядок останова, на который опирается 5.8a (проверено чтением, 2026-10-03):**
1. `ProcessModule.stop()` вызывает `worker_manager.stop_all_workers()` (`process_module.py:1179-1180`).
2. Затем `shutdown()` вызывает `_orchestrator.shutdown()`, а через него `plugin.shutdown` (`process_module.py:302-304`).

Значит, к моменту `DatabasePlugin.shutdown` воркер сброса и исполнитель уже остановлены. Сброс остатка в `shutdown` — единственный писатель.

---

### Task 5.8s — Стенд-гейт: профиль `throughput`
**Level:** Middle+ (Sonnet) · **Assignee:** developer, tester (слепой — по CLI и фикстурам), reviewer · **Layer:** scripts
**Goal:** одна команда меряет storage и processor на заданной частоте и печатает режим цикла.
**Files:** `scripts/stand_gate/{__main__,run,analyze,thresholds,report}.py`, `scripts/stand_gate/tests/` (+ `fixtures/`), `scripts/stand_gate/README.md`. Рецепт `scripts/capacity_bench/recipes/stand.yaml` не меняется.

**DESIGN:**
- **CLI (литерал):** `python -m scripts.stand_gate --profile throughput --fps {60|75|90|100} [--executor-workers N] [--runs N] --lock-token <сессия>`.
  - До 5.8b `--executor-workers` допускает только `1`. Любое другое значение → код 2 с текстом «executor_workers: допустимо только 1 до Task 5.8b».
- **Профиль `throughput`:** `transit_ms=0`, окно 30 с, прогрев 10 с, 1920×1080, `source_target_fps = --fps`. Сейчас `run.py:121-122` жёстко ставит 100.
- **Признак кейса.** `run` пишет в JSON ключи `"profile": "throughput"`, `"fps"`, `"executor_workers"`.
  - `detect_case` (`analyze.py:118-125`) при `profile == "throughput"` возвращает кейс `T`.
  - Кейс `T` получает все пороги кейса `E` плюс `storage_drops` и `processor_born`.
  - JSON без ключа `profile` разбирается как сегодня. Поэтому `--profile quick` и фикстуры 5.6 не меняют набор FAIL.
- **Режим цикла.**
  - `cycle_median_ms` — медиана `workers.pipeline_executor.cycle_duration_ms` processor по `introspect` с шагом 1 с за окно.
  - В JSON рядом пишется `cycle_samples` — число отсчётов.
  - `cycle_duration_ms` — длительность последнего цикла (`cycle_metrics.py:11,81`), отсюда медиана по отсчётам.
  - `mode` — `good` при `cycle_median_ms < 8.0`, иначе `bad`. Прогон в режиме `bad` из серии не исключается; режим печатается рядом с вердиктом.
  - **Сверка источника (лид, до запуска тестера):** на одном прогоне сравнить `cycle_median_ms` с «cycle med» investigator (`docs/reviews/2026-10-03_phase5-stand-w2/investigator/`). При расхождении больше 20 % порог 8.0 пересчитывается и записывается сюда до кода.
- **Строки БД.**
  - `db_rows` = `SELECT COUNT(*)` по `db_path` из `case_dir` (`run.py:127-128`), после `harness.stop()`.
  - Хвост буфера дописывается в `DatabasePlugin.shutdown` — порядок останова выше.
  - В отчёте печатаются `db_rows`, `I`, `drops(storage)` и разность `db_rows − I` с разложением по `lag_dropped_items` и `frame_stale_drops` storage. Порога у разности в 5.8s нет.

**Acceptance criteria:**
- [ ] (tester) Фикстура `throughput_green.json` — синтетика из `raw/E_3.json` (`reports/stand/2026-10-03_first-run/`). Изменённые ключи перечислены в README: настоящего зелёного прогона нет, у всех `E` storage lag > 0. `--from-json` на ней → код 0.
- [ ] (tester) Мутации зелёной фикстуры, каждая → код 1 и строка `FAIL <имя>` в stdout:
  - `storage_drops`: в `s2` у storage `workers.data_receiver.lag_dropped_items` = значение из `s0` + 1;
  - `storage_drops`: у storage `rs.frame_stale_drops` на `s2` = значение из `s0` + 1;
  - `processor_born`: у processor `not_inspected_lag` на `s2` = значение из `s0` + 1.
- [ ] (tester) Пороги: `storage_drops` = `drops(storage, s2) − drops(storage, s0) == 0`; `processor_born` = `born(processor, s2) − born(processor, s0) == 0`. Формулы `drops` и `born` — из Task 5.6.
- [ ] (tester) `mode`: `cycle_median_ms = 7.99` → `good`, `8.0` → `bad`. `cycle_median_ms` отсутствует или `null` → код 2.
- [ ] (tester) JSON без `profile` с теми же числами, что у зелёной фикстуры `T`, → кейс `E`, пороги `storage_drops`/`processor_born` не проверяются.
- [ ] (tester) Тесты 5.6 (`scripts/stand_gate/tests/`) без правки — 0 failed.
- [ ] (tester) `--executor-workers 2` и `--executor-workers 0` → код 2 и текст литералом.

**Out of scope:** `--profile full`. Rejected повторно: ступени — это серия вызовов `--fps`, отдельный профиль не нужен. `ipc_queue_depth` как максимум за окно — до 5.8b, если её DESIGN его потребует.

---

### Task 5.8a — Storage: транзакция на кусок, сброс вне потока исполнителя
**Level:** Middle+ (Sonnet) · **Assignee:** developer, tester (слепой), reviewer · **Layer:** plugins + services
**Goal:** storage при 1080p@100 пишет каждую строку без lag-дропов.

**Факт до кода (лид, до запуска тестера) — живой зонд при 1080p@100.** Снять 30 отсчётов `plugin_ms` плагина `database` (`introspect_plugins`) и `cycle_duration_ms` исполнителя storage. В JSON первого прогона `plugin_ms` нет. Если `plugin_ms` < 30 % цикла, узкое место не в коммите → `ESCALATION -> lead`, DESIGN пересматривается до кода.

**Files:**
- `Plugins/io/database/plugin.py`;
- `Plugins/io/database/registers.py` — только докстринги, если меняется смысл;
- `Plugins/io/database/tests/`, `README.md`, `STATUS.md`;
- `Services/sql/core/base_repository.py` — новый `insert_many_atomic`;
- `Services/sql/tests/`.

`sync_adapter.py` не меняется: транзакция берётся из `ISyncEngineAdapter.connection()` — она в Protocol (`Services/sql/interfaces.py:60`) и делает commit/rollback сама.

**DESIGN (утверждено лидом, у каждого пункта — причина):**
1. **Ручки прежние:** `batch_size`, `flush_interval_sec`. Причина: ред. 1 дублировала их, а `stand.yaml` уже ставит 50 / 1.0.
2. **`process()` только кладёт запись в буфер.** При `len(buffer) ≥ batch_size` он ставит `wake_event` и возвращается. Сбросом занимается только `db_flush_worker`.
   - Цикл воркера — `wake_event.wait(timeout=0.1)`. На каждой итерации проверяются `stop_event` и `_stopping`.
   - Сброс выполняется, когда буфер ≥ `batch_size` или с прошлого сброса прошло `flush_interval_sec`.
   - Причина: коммит SQLite в потоке исполнителя тормозит цикл storage, и data-очередь растёт до lag-дропа. Шаг 0.1 с не даёт стопу ждать полный интервал.
3. **Воркер забирает из буфера только полные куски по `batch_size`.** Каждый кусок — одна транзакция `insert_many_atomic`. Остаток меньше `batch_size` уходит по интервалу или на стопе.
   - При ошибке куска: `ROLLBACK` всего куска, `errors += len(chunk)`, без переинсерта, один голос `report_error`.
   - Причина: число транзакций определяется числом записей, а не частотой пробуждений. Поведение докстринга `plugin.py:157-164` сохраняется: ни дублей, ни «сколько успело».
   - Старый `insert_many` не меняется. Вне тестов его зовут `plugin.py:175` и `Plugins/io/telemetry_sink/plugin.py:322`.
4. **`shutdown` по шагам:**
   1. `_stopping = True`;
   2. `wake_event.set()`;
   3. `ctx.worker_manager.stop_worker("db_flush_worker", timeout=5.0)` — без эффекта, если воркер уже остановлен `stop_all_workers`;
   4. сброс остатка буфера кусками в своём потоке;
   5. `_sql = None`.

   Если воркер не остановился за 5 с, голос называет число строк в буфере. Причина: сейчас `shutdown` обнуляет `_sql` (`plugin.py:105-107`), а `_do_flush` при `_sql is None` возвращает 0 (`:166-167`). Остаток пакета теряется.
5. **Буфер не ограничен.** В `get_stats` появляется gauge `pending_rows`. Rejected: потолок с выбросом строк — молчаливая потеря хуже видимого роста памяти.

**Module contract:** `insert_many_atomic(entities) -> int`.
- Pre: список схем одного типа, может быть пустым.
- Post: в БД все строки или ни одной. Возвращает число записанных, при пустом входе — 0, без обращения к БД.
- При ошибке исключение пробрасывается после `ROLLBACK`.

**Acceptance criteria.** Строки 2–6 — с настоящим `WorkerManager` процесса-заглушки, не с фейком без потоков: с фейком `shutdown` пишет всё сам, и тест зелёный при любой поломке.
- [ ] (tester) Контроль живости оси: одна вставка через `insert_many_atomic` → `sqlite3.Connection.set_trace_callback` видит ровно один `COMMIT`. Без этого счёт `COMMIT` ниже ничего не доказывает.
- [ ] (tester) `batch_size=50`, `flush_interval_sec=5.0`, 1000 вызовов `process()`, ждать строк = 1000 (дедлайн 5 с) → ровно 20 `COMMIT`.
- [ ] (tester) Каждый оператор в `trace_callback` пришёл из потока, у которого `threading.get_ident()` ≠ потоку, вызывавшему `process()`. Хотя бы один `COMMIT` — из потока воркера.
- [ ] (tester) Атомарность: адаптер бросает на 30-й строке куска из 50 → в БД 0 строк этого куска, `errors == 50`. Следующий кусок пишется целиком.
- [ ] (tester) Сброс по интервалу: 10 записей, `batch_size=50`, `flush_interval_sec=0.2` → строки в БД не позже 0.6 с.
- [ ] (tester) Хвост на стопе: 70 записей, `flush_interval_sec=5.0` (в буфере остаток 20), затем `shutdown()` → строк 70. Вызов — в daemon-потоке с `join` по дедлайну 10 с: зависание красное, а не таймаут набора.
- [ ] (tester) `insert_many_atomic([])` → 0, ни одного оператора в `trace_callback`.
- [ ] (лид, стенд, после 5.8s) `python -m scripts.stand_gate --profile throughput --fps 100 --runs 3`: `storage_drops` зелёный 3 из 3; `|db_rows − I| ≤ 0.005 × F`; `effective_hz` storage до и после — в отчёте.

**Инъекции (лид):** сброс обратно в `process()`; `COMMIT` на каждую строку; `_sql = None` до сброса остатка; исключение без `ROLLBACK`; куски не по `batch_size`, а весь буфер.
**Out of scope:** async-адаптер; PostgreSQL/MySQL; схема таблицы; `telemetry_sink`.

---

### Task 5.8b — Пул исполнителя processor (по результату базового замера)
**Level:** Senior+ · **Assignee:** teamlead, tester (слепой), reviewer · **Layer:** framework
**Статус спеки:** правило решения утверждено. DESIGN — черновик. Приёмка дописывается после базового замера, перед тестером — повторный reviewer `MODE: plan`.

**Базовый замер (лид, после 5.8s):** `--profile throughput --fps 60 --executor-workers 1 --runs 3`. Затем 75, 90, 100. Режим `good`/`bad` пишется на каждый прогон.

**Правило решения (записано до замера; пункты проверяются сверху вниз):**
1. Красный только в прогонах `mode = bad` → сначала диагноз бимодальности (OPEN_QUESTIONS, «Transport Ф5: нерешённое 2026-10-03», п.2). Пул не лечит причину.
2. Красный хотя бы в одном прогоне `mode = good` → 5.8b идёт по DESIGN ниже.
3. Зелёный 3 из 3 и среди прогонов есть хотя бы один `mode = bad` → для цели владельца (1080p@60 без потерь) пул не нужен. Приёмка 5.8b переходит на первую красную ступень 75/90/100, или 5.8b уходит в бэклог. Выбор — за владельцем по таблице ступеней.
4. Зелёный 3 из 3, но `bad` не встретился → дополнительные прогоны, всего не больше 6. Если `bad` так и не встретился — вывод п.3 с пометкой «плохой режим не наблюдался».

**DESIGN (черновик из ревью спеки, к утверждению на повторном ревью):**
- **Пул** — `WorkerPoolExecutor` (`chain_module/thread_pool/worker_pool_executor.py:110`, `submit` → handle) внутри процесса, без правки самого пула.
- **Задача пула** — расчёт одного батча: поколение до цепочки → цепочка → поколение после → `_attach_batch_views`. Расчёт возвращает выходной список. Отправка `_send_results` — только в потоке исполнителя, в порядке забора. Сейчас `_run_batch` сам вызывает `_send_results` (`pipeline_executor.py:300,316`); это разделяется.
- **Маркер-коллекции** (`pipeline_executor.py:246-248`, `_forward_markers` `:321-340`) идут через ту же FIFO handles, что и батчи с кадрами. Иначе запись обгонит кадры, которые ещё в пуле.
- **В полёте не больше `N` батчей.** `chain_queue` — единственный буфер: урок Ф0.3 — потолок держал deque, а память росла в батчах в полёте.
- **Счётчики и breaker** (`pipeline_executor.py:273,298-299,339,361-363,420-454,474-540`) — под одним `threading.Lock`. `log_correlation` открывается внутри задачи: ContextVar между потоками не переходит.
- **`thread_safe`** — атрибут класса плагина, по умолчанию `False`. При `N > 1` и хотя бы одном `False` — WARNING на старте и `N = 1`. Копия плагина на воркер — Rejected: у плагинов состояние и ресурсы. `ChainRunnable.execute` состояния на `self` не хранит (`chain.py:35`).
- **Таймаут или исключение задачи под `every`** → входы батча уходят в `stale_exec` через `build_gap`.
- **`cycles`** пишет поток исполнителя на отправке: дренаж P10 мерится по нему (`scripts/stand_gate/run.py:185-192`).
- **Режим при `N > 1`:** порог 8 мс откалиброван на `N = 1`, а длительность цикла при пуле включает ожидание в FIFO. Признак режима для `N > 1` — `effective_hz` processor против `--fps`; литерал — на повторном ревью.
- **Сборка:** `executor_workers` проходит через `blueprint._pick` и `generic_process.py:288-302`.
  - При `== 1` ключ в `proc_dict` не кладётся (как `overflow`/`cv_threads`, `generic_process_config.py:305-316`), поэтому golden-снимки не меняются.
  - `FieldMeta(min=1, max=8)`, текст ошибки — без значения ввода.
- **Запасной вариант снят.** «`processor_1`, чётные/нечётные кадры» невозможен: `chain_targets` шлёт каждый item всем целям (`pipeline_executor.py:505-527`). Если плагины processor не потокобезопасны — `ESCALATION -> cto`: два процесса — уровень ADR.

**Files (предварительно):**
- `process_module/generic/pipeline_executor.py`, `generic_process.py`, `generic_process_config.py`;
- `process_manager_module/topology/blueprint.py` — только `_pick("executor_workers")`;
- `process_module/tests/test_pipeline_executor_pool.py` (новый);
- атрибут `thread_safe` у плагинов processor из `stand.yaml`.

**Риски:**
- `cv_threads=2` (Task 4.6) × N воркеров + приёмник → переподписка ядер.
- Если причина бимодальности — GIL «приёмник/исполнитель», пул её углубит.
- Слоты кольца удерживаются дольше → `stale_restore` растёт. Это ловит порог 5.6 `0.001 × F`.
