# Task 5.8 — Пропускная способность: storage первым, пул исполнителя по замеру (ред. 2)

**План:** [`plan.md`](plan.md) · фаза 5 — [`phase-5.md`](phase-5.md).
**Редакция 2 (2026-10-03).** Источник — ревью спеки, стадия 0 (CHANGES REQUESTED, 7 блокеров). Решение владельца 2026-10-03: «storage первым». Ред. 1 предлагала `WorkerPoolDispatcher`. Это межпроцессная рассылка: она молча выбрасывает старую задачу при переполнении (`dispatcher.py:214-234`), а обработчика `worker_task_request` нет. Поэтому ред. 1 снята.

**Почему storage первым (числа первого прогона 5.6, `reports/stand/2026-10-03_first-run/`, 1080p@100, кумулятивно на `s2`):**

| Процесс | `effective_hz` | `lag_dropped_items` |
|---|---|---|
| storage | 53–79 | 840–956 |
| processor, хороший режим | 89–98 | 40–294 |

Причина у storage в коде:
- `_do_flush` вызывает `insert_many([одна строка])` на каждую запись (`Plugins/io/database/plugin.py:173-176`);
- `BaseRepository.insert_many` исполняет один `execute` на строку (`Services/sql/core/base_repository.py:82-95`);
- `sync_adapter.py:59` делает `commit` на каждый вызов;
- сброс идёт в потоке исполнителя, прямо в `process()` (`plugin.py:127-133`).

Processor зависит от бимодальности цикла: медиана 5.5 мс в хорошем режиме и 12.7–16.5 мс в плохом. При 60 к/с плохой режим оставляет запас около 1 % (OPEN_QUESTIONS, «Transport Ф5: нерешённое 2026-10-03»). Пул без базового замера ничего не доказывает.

**Порядок:** `5.8s ∥ 5.8a` → базовый замер лида → решение по 5.8b по правилу ниже.

---

### Task 5.8s — Стенд-гейт: профиль `throughput`
**Level:** Middle+ (Sonnet) · **Assignee:** developer, tester (слепой — по CLI и фикстурам), reviewer · **Layer:** scripts
**Goal:** одна команда меряет storage и processor на заданной частоте и печатает режим цикла. Без этого 5.8a и базовый замер 5.8b нечем принять.
**Files:** `scripts/stand_gate/{__main__,run,analyze,thresholds,report}.py`, `scripts/stand_gate/tests/` (+ `fixtures/`), `scripts/stand_gate/README.md`. Рецепт `scripts/capacity_bench/recipes/stand.yaml` не меняется.
**DESIGN:**
- CLI (литерал): `python -m scripts.stand_gate --profile throughput --fps {60|75|90|100} [--executor-workers N] [--runs N] --lock-token <сессия>`. Пока нет 5.8b, `--executor-workers` принимает только `1`; любое другое значение → код 2 с текстом «executor_workers > 1 появится в 5.8b».
- Профиль `throughput` = кейс `E` (`transit_ms=0`), окно 30 с, прогрев 10 с, 1920×1080, `source_target_fps = --fps`. Сейчас `run.py:121-122` жёстко ставит 100 — частота становится параметром.
- Новые числа в JSON и отчёте:
  - `cycle_median_ms` исполнителя `pipeline_executor` у processor;
  - `mode` — `good` при `cycle_median_ms < 8.0`, иначе `bad`;
  - `effective_hz` исполнителей processor и storage;
  - строки БД — `SELECT COUNT(*)` по `db_path` из `case_dir` (путь уже изолирован на кейс, `run.py:127-128`).
- Прогон в режиме `bad` из серии не исключается. Режим печатается рядом с вердиктом.
**Acceptance criteria:**
- [ ] (tester) `--from-json` на фикстуре `throughput_green.json` → код 0. Мутация `storage` `lag_dropped_items` на `s2` (+1 к `s0`) → код 1 и строка `FAIL storage_lag`. Мутация `born(processor)` → код 1 и `FAIL processor_born`.
- [ ] (tester) Порог `storage_lag`: `Σ_workers lag_dropped_items(storage, s2) − (…, s0) == 0`. Порог `processor_born`: `born(processor, s2) − born(processor, s0) == 0` (формула `born` — из Task 5.6).
- [ ] (tester) `mode`: фикстура с `cycle_median_ms = 7.99` → `good`, `8.0` → `bad`. Ключ без значения → код 2.
- [ ] (tester) Строки БД: фикстура с `db_rows` → в отчёте число. Порог: `|db_rows − I| ≤ 0.005 × F`, где `I` = `total_inspected` из `rc_s2`. `DatabasePlugin` маркеры не принимает (`accepts_markers` нет) — маркеры обходят плагин.
- [ ] (tester) `--profile quick` ведёт себя бит-в-бит как до задачи: тесты 5.6 без правки — 0 failed.
**Out of scope:** `--profile full`. Rejected повторно: матрица ступеней — это серия вызовов `--fps`, отдельный профиль не нужен. `ipc_queue_depth` как максимум за окно — до 5.8b, если её DESIGN его потребует.

---

### Task 5.8a — Storage: одна транзакция на пакет, сброс вне потока исполнителя
**Level:** Middle+ (Sonnet) · **Assignee:** developer, tester (слепой), reviewer · **Layer:** plugins + services
**Goal:** storage при 1080p@100 пишет каждую строку без lag-дропов.
**Факт до кода (лид, до запуска тестера):** `plugin_ms` плагина `database` против цикла исполнителя storage, по JSON первого прогона 5.6. Если `plugin_ms < 30 %` цикла, узкое место не в коммите. Тогда `ESCALATION -> lead`, и DESIGN пересматривается до кода.
**Files:** `Plugins/io/database/plugin.py`, `Plugins/io/database/registers.py` (только докстринги, если меняется смысл), `Plugins/io/database/tests/`, `Services/sql/core/base_repository.py` (новый `insert_many_atomic`), `Services/sql/adapters/sync_adapter.py` (транзакция на пакет), `Services/sql/tests/`, `Plugins/io/database/README.md`, `STATUS.md`.
**DESIGN (утверждено лидом, у каждого пункта — причина):**
1. Ручки остаются прежние: `batch_size`, `flush_interval_sec`. Новых `commit_every_*` нет. Причина: ред. 1 дублировала существующие регистры, а `stand.yaml` уже ставит 50 / 1.0.
2. `process()` только кладёт запись в буфер. При `len(buffer) ≥ batch_size` он будит воркер `threading.Event` и возвращается. Сброс выполняет только `db_flush_worker`. `time.sleep` (`plugin.py:141`) заменяется на `wake_event.wait(flush_interval_sec)` с проверкой `stop_event`. Причина: коммит SQLite в потоке исполнителя задерживает цикл storage, и data-очередь растёт до lag-дропа.
3. Одна транзакция на пакет — новый `BaseRepository.insert_many_atomic(entities) -> int`. Адаптер исполняет все строки и один `COMMIT`; при исключении делает `ROLLBACK` всего пакета. В плагине при ошибке: `errors += len(batch)`, без переинсерта, один голос `report_error`. Причина: поведение из докстринга `plugin.py:157-164` сохраняется — ни дублей, ни «сколько успело» в неизвестном числе. Старый `insert_many` не меняется: у него есть другие вызывающие.
4. Стоп. `shutdown()` ставит `stop_event`, будит воркер и ждёт его `join` с дедлайном 5 с. Затем сбрасывает остаток буфера своим вызовом. Только после этого `_sql = None`. Причина (найдено чтением в ревью спеки, не воспроизведено): сейчас `shutdown` обнуляет `_sql` (`plugin.py:105-107`), а `_do_flush` при `_sql is None` возвращает 0 (`:166-167`) — пакет в полёте теряется.
5. Буфер не ограничен. В `get_stats` появляется gauge `pending_rows`. Rejected: потолок с выбросом строк — молчаливая потеря хуже видимого роста памяти; рост виден в `pending_rows`.
**Module contract:** `insert_many_atomic(entities)` — Pre: список схем одного типа, может быть пустым. Post: в БД все строки или ни одной; возвращает число записанных (0 при пустом входе); при ошибке исключение пробрасывается после `ROLLBACK`.
**Acceptance criteria:**
- [ ] (tester) 1000 записей подряд через `process()`, `batch_size=50`, `flush_interval_sec=0.2`. Число `COMMIT` по `sqlite3.Connection.set_trace_callback` — от 20 до 25 включительно, строк в БД — 1000. Шпион на имя `commit` не годится: он защищает имя, а не свойство.
- [ ] (tester) Пока идут вызовы `process()`, `trace_callback` не получает ни одного SQL-оператора: запись в БД идёт только из потока воркера.
- [ ] (tester) Атомарность: адаптер бросает на 30-й строке пакета из 50 → в БД 0 строк этого пакета, `errors == 50`; следующий пакет пишется целиком.
- [ ] (tester) Сброс по времени: 10 записей при `batch_size=50`, `flush_interval_sec=0.2` → строки в БД не позже 0.6 с.
- [ ] (tester) Хвост на стопе: адаптер с задержкой 50 мс на пакет, `shutdown()` посреди сброса → строк в БД = отправлено. Тест держит вызов в daemon-потоке с `join` по дедлайну: зависание — красный, а не таймаут набора.
- [ ] (tester) `insert_many_atomic([])` → 0, ни одного `COMMIT`.
- [ ] (лид, стенд) `python -m scripts.stand_gate --profile throughput --fps 100 --runs 3` после 5.8s: `storage_lag` зелёный 3 из 3, `|db_rows − I| ≤ 0.005 × F`. В отчёте `effective_hz` storage до и после.
**Инъекции (лид):** сброс обратно в `process()`; `COMMIT` на каждую строку; `_sql = None` до `join`; проглатывание исключения без `ROLLBACK`.
**Out of scope:** async-адаптер; PostgreSQL/MySQL; схема таблицы.

---

### Task 5.8b — Пул исполнителя processor (по результату базового замера)
**Level:** Senior+ · **Assignee:** teamlead, tester (слепой), reviewer · **Layer:** framework
**Статус спеки:** DESIGN записан, приёмка дописывается после базового замера. Перед запуском тестера — повторный reviewer `MODE: plan` на этот раздел.
**Базовый замер (лид, после 5.8s):** `--profile throughput --fps 60 --executor-workers 1 --runs 3`, затем то же на 75, 90 и 100. Каждая ступень — с режимом `good`/`bad` на прогон.
**Правило решения (записано до замера):**
- 60 к/с при `N=1`: `processor_born` зелёный 3 из 3 → для цели владельца (1080p@60 без потерь) пул не нужен. Приёмка 5.8b переходит на первую красную ступень 75/90/100, или 5.8b уходит в бэклог. Выбор — за владельцем по таблице ступеней.
- 60 к/с при `N=1` красный хотя бы раз → 5.8b идёт по DESIGN ниже.
- Красный только в прогонах с `mode = bad` → сначала диагноз бимодальности (OPEN_QUESTIONS п.2), пул не лечит причину.
**DESIGN (из ревью спеки стадии 0, к утверждению на повторном ревью):**
- Пул — `WorkerPoolExecutor` (`chain_module/thread_pool/worker_pool_executor.py:110`, `submit` → handle) внутри процесса, без правки самого пула. `WorkerPoolDispatcher` не используется.
- При `executor_workers > 1` задача пула — весь `_run_batch` одного батча: поколение до цепочки → цепочка → поколение после → `_attach_batch_views`. `_send_results` вызывается только потоком исполнителя, в порядке забора из `chain_queue`.
- В полёте не больше `N` батчей. `chain_queue` остаётся единственным буфером: урок Ф0.3 — потолок держал deque, а память росла в батчах в полёте.
- Счётчики и breaker (`pipeline_executor.py:273,298-299,339,361-363,420-454,474-540`) — под одним `threading.Lock`. `log_correlation` открывается внутри задачи: ContextVar между потоками не переходит.
- Плагины цепочки получают атрибут класса `thread_safe` (по умолчанию `False`). При `N > 1` и хотя бы одном `False` — WARNING на старте и `N = 1`. Копия плагина на воркер — Rejected: у плагинов состояние и ресурсы (модели, сокеты).
- Таймаут или исключение задачи под `every` → входы батча уходят в `stale_exec` через `build_gap`.
- `cycles` пишет поток исполнителя на отправке: дренаж P10 мерится по нему (`scripts/stand_gate/run.py:185-192`).
- Сборка: `executor_workers` проходит через `blueprint._pick` и `generic_process.py:288-302`. При `== 1` ключ в `proc_dict` не кладётся (как `overflow`/`cv_threads`, `generic_process_config.py:305-316`), golden-снимки не меняются. `FieldMeta(min=1, max=8)`, текст ошибки — без значения ввода.
- Запасной вариант ред. 1 «`processor_1`, чётные/нечётные кадры + join» снят: `chain_targets` шлёт каждый item всем целям (`pipeline_executor.py:505-527`), и деления нет. Если плагины processor не потокобезопасны — `ESCALATION -> cto`: два процесса — уровень ADR.
**Files (предварительно):** `process_module/generic/pipeline_executor.py`, `generic_process.py`, `generic_process_config.py`, `process_manager_module/topology/blueprint.py` (только `_pick("executor_workers")`), `process_module/tests/test_pipeline_executor_pool.py` (новый), атрибут `thread_safe` у плагинов `stand.yaml` processor.
**Риски:** `cv_threads=2` (Task 4.6) × N воркеров + приёмник → переподписка ядер; если причина бимодальности — GIL «приёмник/исполнитель», пул её углубит; дольше удержанные слоты кольца → рост `stale_restore` (ловит порог 5.6 `0.001 × F`).
