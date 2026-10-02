> Часть плана [`transport-single-policy`](plan.md). Основание — ревью системы CTO
> [`docs/reviews/2026-10-02_transport-system-review-cto.md`](../../docs/reviews/2026-10-02_transport-system-review-cto.md)
> (репродукции `scratchpad/cto_sys/cto_sys.py`, стенд 4.7d-5 `22a63e46b`). Сверка остатков фаз 0–4 — в конце этого
> файла («Сверка остатков фаз 0–4») и в `plan.md`, раздел «Порядок». Текст написан CTO (Fable) 2026-10-02, разложен лидом
> дословно.

## Фаза 5 — Форма потери и контракт привода (2026-10-02)

**Гейт входа:** 4.7d слита в main (`fc37a369d`), ревью системы принято владельцем.
**Гейт выхода (урезанный объём, решение владельца 2026-10-02):** стенд-гейт 5.6 зелёный на `stand.yaml` три прогона подряд; `multi_camera.yaml` и `inspection_basic.yaml` стартуют (5.9a); main зелёный (5.5); ADR на решение 5.2.

### Объём фазы — решение владельца 2026-10-02

Владелец спросил, нужна ли фаза целиком. Ответ лида: нет. Половина задач чинит то, что сломается на линии; вторая половина — гигиена или улучшения «на будущее». Владелец выбрал **урезанный объём, не теряя остальное из вида**.

**В работе:** 5.0 ✅ → 5.1 ✅ → **5.5** (зелёный main) → **5.2** (привод не ждёт в конвейере) ∥ **5.4** (preroll) ∥ **5.9a** (валидатор + провода рецептов) → **5.6** (стенд-гейт скриптом + экспорт счётчиков).
Почему именно они: 5.2 — без неё инспектор на линии с задержкой привода даёт 0 вердиктов (D100: `born=3008 handled=0`); 5.4 — без неё не бывает прогона с «потерь 0»; 5.9a — два рецепта не стартуют; 5.5 — гигиена, два настоящих дефекта Windows; 5.6 — «инспектор с числами» одной командой вместо 40 минут ручного замера.

**Отложено (не удалено) — условие возврата записано до того, как оно наступит:**

| Задача | Что даёт | Вернуться, когда |
|---|---|---|
| 5.3 запись о разрыве | строгий учёт каждой единицы при зависании исполнителя; пачка маркеров перестаёт теряться (`delivery_failed`) | стенд-гейт 5.6 показал `errors_delivery_failed > 0` или `queue_data_evicted > 0` в установившемся режиме, ИЛИ линии нужен поимённый учёт при сбоях. Дизайн по 5.1 уже готов. Без 5.3 запись в 5.2 работает с маркерами `count=1` |
| 5.7 транзит и loan | удаление замороженного loan (~1000 строк), закрытие N3 и Task 1.1 | рефакторинг `frame_shm_middleware.py`/`pipeline_executor.py` по любой причине, или `stale_restore` > 0.1 % на гейте 5.6 |
| 5.8 пул исполнителя, batch-commit | 100 fps 1080p без lag-дропов, storage без потерь | задана целевая скорость линии, и гейт 5.6 показывает, что она не держится |
| 5.9 две камеры живьём, кэп моста | гейт на двухкамерном рецепте | нужна вторая камера (робот, линия); 5.9a уже даёт старт рецепта |
| 5.11 индикатор в GUI | оператор видит потери | после 5.6 (нужны счётчики в телеметрии), по запросу владельца |
| 4.8b выводы о мощности | «сколько камер тянет машина» | после 5.8 |
| 5.10 одна дверь | — | **снята по факту 5.0(а)**: data не ходит дверью Б. Вернуть — только решением OWNER-3 |

Оценка цены: урезанный объём ≈ 3–4 млн токенов против 6–10 млн за полный (полный процесс: тестер, исполнитель, инъекции, ревью ≈ 0.5–1 млн на задачу). Оценка — по замерам «Компании v2/v3», не измерена на этой фазе.

**Почему эта фаза, а не «тюнинг»:** три репродукции ревью показали, что потери в тракте уже считаются верно (формула 4.7d сошлась), но их *форма* ломает систему там, где она нужна: задержка привода в потоке конвейера морит кадры голодом (`frames_processed=50 из 300` при задержке 20 мс на маркер и периоде 10 мс), пачка маркеров по одному сообщению теряется на следующем хопе (`reader_got=134 из 2156`, `delivery_failed=612`), старт теряет 24–41 кадр без маркера. Фаза меняет форму, не механизмы: кольцо, поколение, bound, формула остаются.

**Числа стенда, на которые ссылаются критерии (4.7d-5, 1080p@100, окно 30 с):** E1–E3 `every`: processor `lag` 105–316, inspector `stale_restore` 43–46, `queue_data_evicted` на старте 24–41; P10 (пауза исполнителя 10 с): голова 1078 маркеров, недостача соседей 1317 = `queue_data_evicted` 245 + `errors_delivery_failed` 1076; D100 (`reject_delay_ms=100`): inspector `born=3008 handled=0`, журнал 893 строки — все маркеры; renderer `render_overlay` ≈ 39 мс, дропы ≈ 1800/30 с; storage ≈ 670/30 с.

**Правила фазы:** слепой tester до кода на каждый механизм (worktree на коммите до реализации); инъекции лида по обоим наборам тестов; ревью Opus после каждой задачи; CTO — один разбор дизайна (5.1) и одна приёмка фазы; стенд — только скриптом 5.6 после того, как он есть, до того — `stand47d.py` лида по протоколу замка. Слова «невозможно/гарантировано» в задачах не употребляются без репродукции рядом.

### Порядок и параллельность

```
Волна 0:  5.0 (лид, без кода)  ∥  5.5 (developer/debugger; файлы ни с кем не пересекаются)
Волна 1:  5.1 (CTO, разбор дизайна 5.2 и 5.3 — до первой строки кода в них)
Волна 2:  5.2 (robot_control)  ∥  5.3 (маркер/приёмник/исполнитель/дверь)  ∥  5.4 (источник/PM)   ← 5.3 ОТЛОЖЕНА (решение владельца 2026-10-02): волна 2 = 5.2 ∥ 5.4 ∥ 5.9a
          — три писателя, файлы не пересекаются (контракт «маркер с count» зафиксирован в 5.1,
            поэтому 5.3 НЕ трогает robot_control, а 5.2 принимает count с первого дня)
Волна 3:  5.6 (стенд-гейт + экспорт счётчиков) ∥ 5.9a (валидатор портов + провода рецептов) → первый прогон гейта закрывает acceptance 5.2/5.3/5.4
Волна 4:  5.7 (транзит и loan)  ∥  5.8 (пул исполнителя, batch-commit)  ∥  5.9 (две камеры, мост)
Волна 5:  5.10 (одна дверь; условно — по 5.0(а))  ∥  5.11 (GUI-индикатор)  → 4.8b (в task-4.8.md)
```

Зависимости жёсткие: 5.1 → {5.2, 5.3}; 5.3 → 5.6 (формула в items); 5.6 → {5.7, 5.8, 5.9} (гейт нужен для их приёмки); 5.9a → 5.9 (рецепт двух камер должен стартовать); 5.0(а) → 5.10; 5.7 → решение по Task 1.1.

---

### Task 5.0 — Сверка фактов до кода (лид, без правок)
**Статус (2026-10-02): ✅ сделано** — [`docs/audits/2026-10-02_transport-facts.md`](../../docs/audits/2026-10-02_transport-facts.md). Кадры — дверью А; событие готовности до детей не доходит; **`multi_camera.yaml` и `inspection_basic.yaml` не стартуют с `917ec7ed4`** (блокер 5.9).
**Level:** Senior (Opus) · **Assignee:** лид (teamlead при занятости) · **Layer:** docs
**Goal:** закрыть пять непроверенных фактов, от которых зависят 5.4, 5.10 и остатки 4.7; ни один из них не угадывается по чтению.
**Files:** без правок кода; новый `docs/audits/2026-10-0X_transport-facts.md`; чтение `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py:131,324,4135`, `multiprocess_framework/modules/process_module/generic/source_producer.py`, `multiprocess_framework/modules/router_module/core/router_manager.py:556-580,584-597`, `backend_ctl/probes/g7_soak_probe.py`.
**Steps:**
1. (а) Какой дверью ходят кадры: один прогон `stand.yaml` 30 с, снять `introspect_router_stats` каждого процесса: `sent_via_channel`, `sent_via_targets`, `put_timeout_total`, `errors_delivery_failed`, `middleware_dropped`. Закрывает Task 0.2.
2. (б) Доходит ли `system_ready_event` до generic-детей: по коду `process_manager_process.py:131/324` событие читает PM; проверить, передаётся ли оно в `custom` дочернего `ProcessModule` и есть ли у `SourceProducer` точка, где его ждать. Ответ «нет» = 5.4 добавляет проводку через bundle.
3. (в) Из JSON стенда 4.7d-5 (`m47d/*.json`) и одного свежего прогона: `transit_over_budget`, `ipc_queue_depth` у processor и inspector — числа за окно.
4. (г) Все рецепты `multiprocess_prototype/backend/topology/*.yaml` (кроме `archive/`, `tests/`), которые стартуют на этой машине: 30 с, grep логов на `assignment destination is read-only` (остаток acceptance 4.7).
5. (д) Текст строки `RouterSendError delivery_failed` из лога P10: ветка `_do_send:572-575` («ни один из N адресатов не принял») или `:590` («канал вернул ошибку») — это и есть ответ (а) для пачки.
6. (е) Жива ли проба `g7_soak_probe` против нынешнего бэкенда (запуск `--tier live` 1 мин): да/нет — для судьбы 0.3/3.1.
**Acceptance criteria:**
- [x] Таблица «процесс × {sent_via_channel, sent_via_targets, put_timeout_total, errors_delivery_failed}» с литералами; вывод одной строкой: «кадры ходят дверью А/Б».
- [x] Ответ (б) «да/нет» с файлом:строкой, где событие появляется (или не появляется) у ребёнка.
- [x] `transit_over_budget` и `ipc_queue_depth` processor/inspector — числа.
- [x] Список рецептов: стартовал/нет, `read-only` в логах: 0/N.
- [x] Строка лога P10 процитирована, ветка названа. — `docs/audits/2026-10-02_transport-facts.md`
**Out of scope:** любые правки; выводы о мощности (4.8b).

### Task 5.1 — Разбор дизайна механизмов 5.2 и 5.3 у CTO (до кода)
**Статус (2026-10-02): ✅ сделано** — [`docs/reviews/2026-10-02_phase5-design-cto.md`](../../docs/reviews/2026-10-02_phase5-design-cto.md). Дизайн 5.2/5.3 принят с шестью правками (внесены ниже), добавлена Task 5.9a.
**Level:** CTO (Fable) · **Assignee:** cto · **Layer:** docs
**Goal:** тот шаг, которого не хватило в 4.7d: сценарный разбор дизайна механизма до кода. Входы — разделы «Дизайн» задач 5.2 и 5.3 ниже и факты 5.0; выход — решения, по которым пишутся слепые тесты.
**Files:** новый `docs/reviews/2026-10-0X_phase5-design-cto.md`; этот файл (правка разделов «Дизайн» 5.2/5.3 лидом по решениям).
**Steps:** CTO отвечает на вопросы списком, каждый — решение + сценарий, который его переворачивает: (1) планировщик привода — часть плагина `robot_control` или сервис процесса (`ProcessModule`), доступный любому решателю; (2) схема записи о разрыве: ключи, предел длины `trace_ids` (есть ли), поведение при `count=1`; (3) где склеивать — в приёмнике (уже `_MarkerBatch`) или в исполнителе перед отправкой; (4) формула приёмки в items: левая часть `Σ count`, `not_inspected_handled` считает items или записи; (5) fan-out: одна запись на цель, доставок N — как в 4.7d; (6) фронт `_rejecting` при планировщике: вердикт пишется на фронте решения (сейчас) или на выстреле; (7) совместимость `every`-записи с узлом `latest` посередине (проход записи не зависит от режима — остаётся?); (8) что делать с записью, чей `last_capture_ts + transit` уже в прошлом на момент прихода (старение).
**Acceptance criteria:**
- [x] Восемь решений записаны, у каждого — «что перевернёт». (девять: плюс валидатор портов)
- [x] Разделы «Дизайн» 5.2 и 5.3 в этом файле приведены к решениям до запуска слепого tester'а (коммит `docs(plans)`).
**Out of scope:** код, тесты, приёмка фазы.

### Task 5.2 — Контракт привода: конвейер не ждёт механизма
**Level:** Senior+ · **Assignee:** teamlead (код), tester (слепые тесты до кода), reviewer · **Layer:** mixed
**Goal:** в `process()` решателя нет ожидания; отбраковка планируется по `capture_ts + transit_ms` и исполняется планировщиком; устаревшая цель не стреляет, а считается.
**Files:** `Plugins/control/robot_control/plugin.py`, `Plugins/control/robot_control/registers.py`, новый `multiprocess_framework/modules/process_module/generic/actuation_scheduler.py` (планировщик, решение 1 CTO), новый `multiprocess_framework/modules/process_module/tests/test_actuation_scheduler.py`, `Plugins/control/robot_control/tests/` (новые + намеренно изменяемые), `Plugins/control/robot_control/README.md`, новый `multiprocess_framework/modules/process_module/tests/test_no_blocking_in_plugin_process.py` (страж), `multiprocess_prototype/backend/topology/TEMPLATE.yaml` (новые регистры).
**Дизайн (по решениям 5.1, [`docs/reviews/2026-10-02_phase5-design-cto.md`](../../docs/reviews/2026-10-02_phase5-design-cto.md)):**
- Регистры: `transit_ms` (умолчание 0 = прежнее `reject_delay_ms`), `actuation_tolerance_ms` (умолчание 20), `reject_delay_ms` — deprecated-алиас с WARNING раз на старт (OWNER-1). `transit_ms == 0` → планировщик не используется, `fire` синхронно, `missed_actuation = 0` (решение 8).
- `ActuationScheduler` — класс фреймворка `process_module/generic/actuation_scheduler.py` (heap под Lock, `clock` по умолчанию `time.time` — та же шкала, что `capture_ts`, `source_producer.py:188`; колбэк `fire(payload, count)`); `robot_control` запускает его воркером через `ctx.worker_manager.create_worker`. Новый вход в `PluginContext` не добавляется до второго потребителя (решение 1).
- API: `schedule(fire_at, window_end, count, payload) -> "scheduled"|"missed"`; `now > window_end + tolerance` → `missed_items += count`, без постановки; `fire_at < now` → `fire_at = now`. `tick()`: стреляет все `fire_at ≤ now`, `late_fires += 1` при `now − fire_at > tolerance`. Счётчики: `fired_items`, `missed_items`, `late_fires`, `unscheduled_items` (нет `capture_ts`).
- `process()`: решение → `_write_verdict` на фронте (как сейчас) → `status = scheduler.schedule(...)` → широкая запись с `actuation=status`, `fire_at`, `transit_ms` → `return item`. `time.sleep` удалён из `process()` и `_process_marker`. Вердикт пишется на решении, не на выстреле; `fire` документов не пишет (решение 6).
- Запись с `count` (5.3): `total_not_inspected += count`; одна постановка с окном `[first_capture_ts + transit, last_capture_ts + transit]`; одна широкая запись; фронт `_rejecting` не меняется. Источник: `source`, если он есть, иначе гистограмма `sources` (единственный читатель — `plugin.py:233`).
- Страж: AST по `Plugins/**/plugin.py`, функции `process`/`_process_*`: `time.sleep`/`sleep(` → красный с именем файла. Проверка стража инъекцией.
- Критерий «стреляет в `[fire_at, fire_at + 0.002]`» — только с подменными часами; живьём — `late_fires` и p99 опоздания числом (Windows: сетка 15.6 мс).
**Steps:** 1. tester: слепые тесты по acceptance в worktree до кода. 2. Регистры + планировщик + перевод `process()`. 3. Страж. 4. Инъекции лида (≥ 6: планировщик не стреляет по старой цели; стреляет дважды на окно; `tolerance` не читается; `count` не суммируется; фронт сломан; `sleep` вернулся). 5. Ревью. 6. Стенд-гейт (ниже).
**Намеренно меняемые тесты:** `Plugins/control/robot_control/tests/test_plugin.py` — кейс «`reject_delay_ms=50`, маркер: `process` длится ≥ 50 мс» (acceptance 4.7d-4) переворачивается в «< 1 мс, в планировщике одна запись»; аналогичный кейс для обычного брака; `test_verdict_documents.py` — если 5.1 переносит фронт на выстрел (решение 6), кейсы фронта переписываются; `test_wide_event_emitter.py` — без изменений (одна запись на единицу сохраняется).
**Acceptance criteria:**
- [ ] `process()` на браке и на маркере при `transit_ms=100`: p99 длительности из 1000 вызовов < 1 мс; в планировщике ровно 1 запись на вызов.
- [ ] Планировщик с подменными часами: цель `fire_at = capture_ts + 0.100` стреляет в `[fire_at, fire_at + 0.002]`; цель с `now > fire_at + tolerance` не стреляет, `missed_actuation == 1`.
- [ ] Запись о разрыве `count=1078`, `first_capture_ts`/`last_capture_ts`: одна постановка, одно срабатывание на окно `[first + transit, last + transit]`, `total_not_inspected += 1078`.
- [ ] Страж красный при инъекции `time.sleep` в `process()` любого плагина под `Plugins/` и зелёный на HEAD.
- [ ] Обычный item без детекций — `pass`; с детекцией — `reject`, вердикт на фронте (существующие тесты зелёные, кроме перечисленных выше).
- [ ] **Стенд-гейт (D100 заново):** `stand.yaml` 1080p@100, `every` на processor+inspector, `transit_ms=100`, 30 с, 3 прогона: вердиктов по кадрам за окно ≥ 0.9 × (кадров камеры − маркеров); маркеров у inspector того же порядка, что в E1–E3 (`lag@inspector` ≤ 100 за окно, не 3008); `missed_actuation` число в отчёте.
**Out of scope:** per-object tracking вместо фронта pass→reject; реальный привод (Modbus/GPIO) — планировщик зовёт тот же `fire`, что сегодня пишет вердикт.

### Task 5.3 — Запись о разрыве: один item на потерю любой длины
**Level:** Senior+ · **Assignee:** teamlead (код), tester, reviewer · **Layer:** framework
**Goal:** потеря N кадров уезжает одной записью `not_inspected` с `count` и списком `trace_ids`, а не N сообщениями; память и fan-out O(1) на разрыв; поимённость по `trace_id` сохраняется.
**Files:** `multiprocess_framework/modules/router_module/middleware/not_inspected_marker.py` (`build_gap`, `is_marker` принимает `count`, `MARKER_REASONS` без изменений), `multiprocess_framework/modules/process_module/generic/data_receiver.py` (IPC-запись сверху — отдельной коллекцией, как маркер), `multiprocess_framework/modules/process_module/generic/pipeline_executor.py` (`_forward_markers`: `_MarkerBatch` → одна запись перед `_send_results`; `not_inspected_handled += Σ count`), `multiprocess_framework/modules/router_module/middleware/frame_shm_middleware.py` (дверной маркер = запись с `count=1`), `multiprocess_framework/modules/router_module/core/router_manager.py` (без изменений, если `get_shm_stats` не меняется), `multiprocess_framework/DECISIONS.md` (поправка ADR-174 п. 4–7), тесты `multiprocess_framework/modules/process_module/tests/test_t47d2_*.py`, `multiprocess_framework/modules/router_module/tests/test_t47d1_marker_contract.py`, `test_t47d3_*.py`.
**Дизайн (по решениям 5.1, [`docs/reviews/2026-10-02_phase5-design-cto.md`](../../docs/reviews/2026-10-02_phase5-design-cto.md)):**
- Склейка в приёмнике — как есть (`_MarkerBatch`, `_coalesce_markers`, тесты не меняются). Плюс: в `on_items_ready` маркер-коллекция сливается в хвост очереди, если `pending[-1]` — `_MarkerBatch` (под `chain.mutex`, в обоих режимах). Причина: `_bound_lag` на маркер-коллекции не срабатывает (`data_receiver.py:263`), поток маркеров без кадров заполняет `chain_queue` по одному (решения 3(б), 7).
- Схлопывание в записи — в исполнителе, в `_forward_markers`, ДО `_execute_chain`: `records = build_gap(items)` → цепочка по записям → `not_inspected_handled += Σ count` (по входу) → `_send_results`. Post-chain stale (`_run_batch`, ветка `not valid` под `every`) — тоже через `build_gap` (решения 3, 4).
- `build_gap(items) -> list[dict]`, чанк `GAP_CHUNK = 1500`: `{inspection_status, overflow_marker: True, count, trace_ids, first_capture_ts (min), last_capture_ts (max), reasons: {…}, sources: {…}}` + `source`/`camera_id`/`reason`, если единственны. Вход может быть записью (`count>1`) — поля суммируются. `len(trace_ids) == count`. `count=1` несёт и сингулярные ключи (`trace_id`, `capture_ts`, `reason`). Пустой вход → `ValueError` (решение 2).
- `is_marker` — без изменений (две пары ключей); `count = item.get("count", 1)`.
- Дверь: запись `count=1` с полным набором ключей. Fan-out: одно рождение, N доставок одного dict (решение 5).
- Формула ADR-174 п. 5 — в items; `handled` считает Σ count входа.
**Steps:** 1. tester до кода. 2. `build_gap` + `_forward_markers`. 3. Дверь: `count=1`. 4. Приёмник: запись сверху. 5. Инъекции (≥ 8: `count` не суммируется; `trace_ids` теряет порядок; `first/last` перепутаны; запись сверху идёт в коллектор; дверь рожает две записи при fan-out; `handled` считает записи, а не items; `reasons` не агрегируются; `count=0`). 6. Ревью. 7. Стенд-гейт.
**Намеренно меняемые тесты:** 4.7d-2 кейсы «stale pre-chain батч из 3 → `send_fn` получила 3 сообщения-маркера» → 1 сообщение, `count=3`, `trace_ids=[t1,t2,t3]`; «post-chain 2→1: 2 маркера» → 1 запись `count=2`; «маркер-коллекция, плагин без `accepts_markers`: `send_fn` по сообщению на цель, `data` равен маркеру» → `data` равен записи; `test_t47d1_marker_contract.py` — точный набор ключей `build_marker` дополняется `count` (литерал обновить); 4.7d-4 кейс «`blob_detector` 0 раз, `robot_control` 1 раз на маркер-коллекцию» — 1 раз на запись (не на маркер).
**Acceptance criteria:**
- [ ] `build_gap([m(t1,lag), m(t2,lag), m(t3,stale_restore)])` равен ровно `{inspection_status: "not_inspected", overflow_marker: True, count: 3, trace_ids: ["t1","t2","t3"], first_capture_ts: ts1, last_capture_ts: ts3, reasons: {"lag": 2, "stale_restore": 1}, source: "<узел>"}` (+ `camera_id`, если он один у всех).
- [ ] Исполнитель, `_MarkerBatch` из 1078 маркеров, 2 `chain_targets`: `send_fn` вызвана ровно 2 раза, в обоих `data["count"] == 1078`, `len(trace_ids) == 1078`, порядок = порядок замены; `not_inspected_handled` +1078.
- [ ] Дверь (`every`, fan-out 2): одна запись `count=1`, `not_inspected_door == 1`, `door_drops == 1`.
- [ ] Приёмник соседа: запись сверху → отдельная коллекция, коллектор не вызван, поля целы; `robot_control.process` вызван 1 раз, `total_not_inspected += count`.
- [ ] Размер pickle записи с 1078 `trace_ids` (32-символьных) — число в отчёте; ≤ 64 КиБ (CTO замерил прототипом 38 053 Б).
- [ ] `build_gap` на 3008 маркерах → 3 записи (1500/1500/8), Σ count = 3008, `len(trace_ids) == count` у каждой.
- [ ] 1000 IPC-записей в узел с паузой исполнителя (`latest` и `every`): `chain_queue.qsize() ≤ 2`, приёмник не блокируется.
- [ ] Формула 4.7d (`every`, риг 4.7d-2 198/250/295) сходится в items с разностью 0.
- [ ] **Стенд-гейт (P10 заново):** пауза исполнителя processor 10 с под `every`: у processor `errors_delivery_failed` Δ = 0 и `queue_data_evicted` Δ = 0 за дренаж; inspector/renderer `handled − own = Σ born(processor)` с разностью 0; ΔRSS processor ≤ 1 МиБ; дренаж ≤ 0.1 с; 2 прогона.
**Out of scope:** `robot_control` (принимает `count` в 5.2); маркер у писателя; старение записей (5.2, решение 8 в 5.1).

### Task 5.4 — Preroll: источники стартуют после готовности потребителей
**Level:** Middle+ (Sonnet) · **Assignee:** developer, tester, reviewer · **Layer:** framework
**Goal:** на старте ни один кадр не вытесняется из очереди ещё не читающего соседа: `SourceProducer.produce()` начинается по событию готовности системы, которое уже есть у PM.
**Files:** `multiprocess_framework/modules/process_module/generic/source_producer.py`, `multiprocess_framework/modules/process_module/generic/generic_process.py` (передача события в `SourceProducer`), `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py` (проводка `system_ready_event` в bundle ребёнка — только если 5.0(б) ответил «не доходит»), `multiprocess_framework/modules/process_module/tests/test_source_producer*.py`, `multiprocess_framework/modules/process_manager_module/tests/`.
**Первый шаг — факт 5.0(б).** Если событие уже у ребёнка — задача на два файла; если нет — проводка через `custom`/bundle по образцу `process_manager_process.py:131`.
**Steps:** 1. tester до кода. 2. `SourceProducer`: ждать событие с таймаутом `preroll_timeout_s` (по умолчанию 10 с; истёк → WARNING и старт, не зависание). 3. Инъекции (событие не ждётся; таймаут бесконечный; событие взводится до регистрации очередей). 4. Ревью. 5. Стенд-гейт.
**Намеренно меняемые тесты:** тесты `SourceProducer`, которые ждут первый кадр сразу после `start()` без события, получают взведённое событие в фикстуре.
**Acceptance criteria:**
- [ ] `SourceProducer` с невзведённым событием: 0 кадров за 200 мс; событие взведено → первый кадр ≤ 50 мс после; таймаут 0.2 с без события → старт с WARNING (текст содержит `preroll`).
- [ ] **Стенд-гейт:** `stand.yaml`, 3 прогона: `queue_data_evicted` в `s0` = 0 у всех процессов (было 24–41); `frame_stale_drops` в `s0` = 0; время до первого кадра камеры — число.
- [ ] `multi_camera.yaml`: то же, обе камеры.
**Out of scope:** рестарт одного процесса (повторный preroll — отдельно, если стенд рестарта покажет вытеснения).

### Task 5.5 — Зелёный main: пять красных и гейт слияния
**Level:** Middle+ (Sonnet) · **Assignee:** debugger (диагноз), developer (правки), reviewer · **Layer:** mixed
**Goal:** `python scripts/run_framework_tests.py` на main — 0 failed; карантин только `xfail(strict=True)` с issue; `make gate` обязателен перед слиянием.
**Files:** `multiprocess_framework/modules/router_module/tests/test_socket_channel_hol_acceptance.py`, `test_socket_channel_hol_hazards.py`, `multiprocess_framework/modules/router_module/channels/socket_channel.py` (если дефект), `multiprocess_framework/modules/registers_module/tests/test_field_info_codec_acceptance.py` (+ `registers_module` кодек, если дефект Windows-пути), `multiprocess_prototype/backend/tests/test_hot_rebuild_provenance_acceptance.py:309-322` (пин числом → снимок-файл), `multiprocess_prototype/frontend/forms/tests/test_catalog_kind_roundtrip.py:67` (пин 417 → снимок), `multiprocess_framework/modules/logger_module/tests/test_sampler_ceiling_policy.py` (segfault только в общем прогоне — диагноз), `Makefile`/`scripts/run_framework_tests.py`.
**Steps:** 1. `debugger`: по каждому красному — дефект кода или теста/окружения, с репродукцией (socket HOL ×3: таймаут 5 с «клиент A не завершился» — гонка или реальный HOL?). 2. Правки по диагнозу; пины ключей — снимком (`*.snapshot.json`), не числом. 3. Segfault sampler: прогон `logger_module/tests` целиком с `-p no:cacheprovider`, `faulthandler` — найти соседа. 4. `make gate` в `/dev:ship` как обязательный шаг.
**Намеренно меняемые тесты:** оба пина (hot_rebuild 37→снимок, catalog 417→снимок); HOL-тесты — только если диагноз «тест», с объяснением в докстринге.
**Acceptance criteria:**
- [ ] `python scripts/run_framework_tests.py` на main: `0 failed`; строк `xfail` ≤ 5, у каждой ссылка на issue/OPEN_QUESTIONS.
- [ ] Прогон CTO (5 файлов из ревью) — `0 failed` литералом.
- [ ] `logger_module/tests` целиком — без segfault, 3 прогона.
- [ ] `make gate` зелёный; `/dev:ship` отказывает при красном gate (проверено инъекцией — временно сломанный тест).
**Out of scope:** новые тесты для транспорта (у задач свои).

### Task 5.6 — Стенд-гейт как скрипт и экспорт счётчиков тракта в телеметрию
**Level:** Senior+ · **Assignee:** teamlead (скрипт + экспорт), tester (слепые тесты скрипта), reviewer · **Layer:** scripts + framework
**Goal:** одна команда `python -m scripts.stand_gate --recipe <yaml> [--runs 3] [--pause 10]` поднимает стенд по протоколу замка, снимает счётчики, проверяет пороги §5 ревью и падает с кодом 1 при нарушении; счётчики 4.7c/d видны в дереве телеметрии, а не только в `introspect.status`.
**Files:** новый пакет `scripts/stand_gate/{__init__,__main__,run,analyze,thresholds,report}.py` (перенос `stand47d.py`/`analyze47d.py` из scratchpad лида, переиспользование `scripts/capacity_bench/run_case.py`, `cpu_probe.py`, `recipe.py`), `scripts/stand_gate/tests/`, `scripts/stand_gate/README.md`, `multiprocess_framework/modules/process_module/heartbeat/telemetry.py` (`declare_metric` для `lag_dropped_items`, `not_inspected_lag/stale_restore/stale_exec/handled`, `transit_over_budget`, `ipc_queue_depth`), `multiprocess_framework/modules/router_module/core/router_manager.py` (`get_shm_stats`: `door_drops`, `not_inspected_door`, `deferred_closes`, `errors_delivery_failed` рядом с `queue_data_evicted`), `backend_ctl` без новых инструментов, `pyproject.toml` (`testpaths`).
**Steps:** 1. Экспорт счётчиков (отдельный коммит; tester по набору ключей). 2. Скрипт: прогон → JSON → проверка порогов → `reports/stand/<host>_<дата>.md`. 3. Матрица: `stand.yaml` (quick) и `--profile full` через `capacity_bench.matrix` (закрывает 4.3). 4. Критерий «стоп чистый»: 20 стопов, строки отпуска feeder'ов — число (перемер для `lifecycle-stop-ownership`). 5. Ночной запуск — OWNER-9.
**Намеренно меняемые тесты:** тесты `heartbeat/telemetry.py`, пинящие набор объявленных метрик; `test_shm_stats_narrow` (ключи `get_shm_stats`); `test_cycle_metrics.py` не меняется (ключи воркеров те же).
**Acceptance criteria (пороги — литералы в `thresholds.py`, те же, что в §5 ревью; владелец утверждает OWNER-8):**
**Пока 5.3 отложена:** порог «`errors_delivery_failed = 0` и `queue_data_evicted = 0` на дренаже паузы» и случай `--pause` выключены флагом `--no-gap-gate` (по умолчанию включён, пока 5.3 не сделана); формула приёмки — в маркерах `count=1`, как в 4.7d. Отчёт печатает числа и по выключенным порогам — для условия возврата 5.3.
- [ ] Формула приёмки под `every` на каждом процессе: разность 0 (в items после 5.3).
- [ ] `queue_data_evicted = 0` и `errors_delivery_failed = 0` на data-пути у всех процессов, включая `s0` (после 5.4) и дренаж паузы (после 5.3).
- [ ] Журнал решателя: `кадры камеры − строки = 0` после preroll; дублей `trace_id` 0.
- [ ] `stale_restore ≤ 0.1 %` кадров узла; lag-дропы processor ≤ 1 % на заявленной частоте (до 5.8 — число в отчёте, порог выключен флагом `--no-throughput-gate`).
- [ ] Вердиктов/с при `every` + `transit_ms > 0` ≥ 0.9 × (кадры − потери).
- [ ] 20 стопов: строк отпуска feeder'ов — число; порог 0 после диагноза в `lifecycle-stop-ownership`.
- [ ] `state.*` телеметрии содержит `lag_dropped_items`, `not_inspected_*`, `transit_over_budget`, `ipc_queue_depth`, `shm.door_drops`, `shm.deferred_closes`, `shm.errors_delivery_failed` (литеральный набор в тесте).
- [ ] Скрипт падает с кодом 1 на подменённом JSON с нарушением каждого порога (по тесту на порог); зелёный на `E1.json`.
- [ ] Три прогона подряд зелёные на `stand.yaml` после 5.2–5.4; отчёт в `reports/stand/`.
**Out of scope:** выводы о мощности (4.8b); GUI (5.11); новые MCP-инструменты backend_ctl.

### Task 5.7 — Транзит и судьба loan-протокола
**Level:** Senior+ · **Assignee:** teamlead, reviewer; замер — лид · **Layer:** framework
**Goal:** stale_restore ≈ 1 % у inspector объяснён числом транзита, а не гипотезой; замороженный loan либо удалён (с N3 и Task 1.1), либо включён и доказан — не «заморожен навсегда».
**Files:** замер — без кода; при удалении: `multiprocess_framework/modules/config_module/feature_flags.py` (`FW_SHM_LOAN_PROTOCOL`), `multiprocess_framework/modules/router_module/middleware/frame_shm_middleware.py` (`loan_protocol`, `_last_loan_exhausted`, `_accumulate_releases`-путь исполнителя), `multiprocess_framework/modules/process_module/generic/pipeline_executor.py` (`_accumulate_releases/_flush_releases`), `multiprocess_framework/modules/shared_resources_module/memory/pool/` (леджер), `multiprocess_framework/modules/router_module/core/router_manager.py` (`_on_frame_evicted`, `frame_loans_released_on_evict`), тесты `router_module/tests/test_g5d_loan.py` (22), `shared_resources_module/memory/tests/*loan*`, ADR в `multiprocess_framework/DECISIONS.md` + пометка «снято» в ADR-RTR-010 (закрывает 1.4 часть).
**Первый шаг — замер (лид, 5.6 скриптом):** `stand.yaml` при `frame_ring_depth` 8 и 12 у processor, 3 прогона каждая: `stale_restore`, `transit_over_budget`, `ipc_queue_depth` у inspector. Правило решения (записать до замера): stale_restore ≤ 0.1 % при глубине ≤ 12 → loan удалить; > 0.1 % при 12 → вытеснение к владельцу очереди (Task 5.12 в следующей фазе, не здесь) и loan всё равно удалить, потому что лечит не он.
**Acceptance criteria:**
- [ ] Таблица «глубина × {stale_restore, transit_over_budget, ipc_queue_depth}» с числами, 3 прогона на строку.
- [ ] При удалении: `grep -rn "FW_SHM_LOAN_PROTOCOL\|loan_protocol\|_last_loan_exhausted" multiprocess_framework Plugins multiprocess_prototype --include=*.py` пуст вне истории/документации; радиус router + shared_resources + process зелёный; ADR с числами замера.
- [ ] Task 1.1 в `phase-0-1.md` помечена «устарело (loan удалён, ADR-…)» либо переведена в фазу 6.
**Out of scope:** вытеснение у владельца очереди (отдельная задача по итогам замера).

### Task 5.8 — Пропускная способность: пул исполнителя и batch-commit
**Level:** Senior+ · **Assignee:** teamlead (пул), developer (storage), tester, reviewer · **Layer:** framework + plugins
**Goal:** processor держит 100 fps 1080p без lag-дропов (сейчас 105–316/30 с при цепочке 13 мс), storage пишет без потерь (сейчас ≈ 670/30 с).
**Files:** `multiprocess_framework/modules/chain_module/worker_pool/dispatcher.py` (reuse `WorkerPoolDispatcher`), `multiprocess_framework/modules/process_module/generic/pipeline_executor.py` (`_execute_chain` через пул при `executor_workers > 1`), `multiprocess_framework/modules/process_module/generic/generic_process_config.py`, `multiprocess_framework/modules/process_manager_module/topology/blueprint.py` (`_pick("executor_workers")`, extras-only как `overflow`), `Plugins/io/database/plugin.py`, `Plugins/io/database/config.py` (batch: `commit_every_rows`, `commit_every_ms`), тесты `process_module/tests/test_pipeline_executor*.py`, `Plugins/io/database/tests/`.
**Первый шаг — факт:** даёт ли `WorkerPoolDispatcher` сохранение порядка выходов и как он ведёт себя с read-only view и тикетами `_shm_views` (проверка поколения ДО и ПОСЛЕ цепочки должна остаться на входах батча). Если порядок не держится — вместо пула второй процесс `processor_1` с чётными/нечётными кадрами и join по `frame_id` у inspector (решение лида после факта, в этом же файле).
**Steps:** 1. Факт. 2. tester до кода (оба механизма — свои тестеры, файлы не пересекаются: пул ∥ storage). 3. Код. 4. Инъекции (порядок; stale после пула; batch не сбрасывается по времени; потеря хвоста на стопе). 5. Ревью. 6. Стенд-гейт.
**Намеренно меняемые тесты:** `test_pipeline_executor_characterization.py` — если пул оборачивает `_execute_chain`; тесты database-плагина, проверяющие коммит на каждую строку.
**Acceptance criteria:**
- [ ] `executor_workers: 2` в extras доходит до `PipelineExecutor` (реальная сборка); без ключа — 1, поведение прежнее бит-в-бит (характеризационные тесты зелёные).
- [ ] Пул: 100 батчей, выходы в порядке входов; stale-проверка на входах батча работает (риг 4.7d-2 pre/post-chain даёт те же счётчики).
- [ ] Storage: `commit_every_rows=50`/`commit_every_ms=50` — за 1000 строк ≤ 25 коммитов (spy на `commit`); на стопе хвост дописан (строк в БД = отправлено).
- [ ] **Стенд-гейт:** `stand.yaml` 1080p@100, `executor_workers: 2`, 3 прогона, медиана: lag-дропы processor ≤ 1 % кадров за 30 с; `plugin_ms` и ядра processor — числа до/после; storage `lag_dropped_items = 0`, строк в БД = кадров камеры − потерь; renderer под `latest` — без изменений (дропы ≈ 1800/30 с остаются по замыслу, число в отчёте).
**Out of scope:** `render_overlay` ROI; B-7 per-target; `color_mask` (OWNER-7); GPU.

### Task 5.9 — Несколько камер живьём (остаток 4.7e) и кэп моста
**Level:** Middle+ (Sonnet) · **Assignee:** developer (мост, рецепт), лид (стенд) · **Layer:** framework + prototype
**Goal:** двухкамерный рецепт проходит стенд-гейт; кэш handles моста не вытесняет перед повторным обращением.
**Files:** `multiprocess_prototype/backend/topology/multi_camera.yaml` (проверить состав; при необходимости синтетические камеры 1080p — OWNER-10), `multiprocess_framework/modules/frontend_module/bridge/remote_frame_source.py:72` (`_HANDLE_CAP = 32` → сумма глубин подписанных отправителей из топологии/конфига), тесты `frontend_module/bridge/tests/`, `scripts/stand_gate` (второй рецепт в матрице).
**Steps:** 1. Прочитать `multi_camera.yaml`; при аппаратной зависимости — вариант с двумя синтетическими источниками. 2. Кэп моста из суммы глубин. 3. Стенд-гейт на двух камерах.
**Acceptance criteria:**
- [ ] Мост при 5 ключах × глубина 8 и 3 × 12: попаданий в кэш > 0 (сейчас 0), `deferred_closes` число.
- [ ] **Стенд-гейт `multi_camera.yaml`, 30 с, 3 прогона:** чужих кадров 0 у обеих камер (пиксельная метка), `pacer_late` и stale_restore по каждой камере — числа; `queue_data_evicted = 0`; формула приёмки на узле за двумя камерами сходится.
- [ ] Третья камера с `frame_ring_depth: 12` не меняет бюджет узлов за первыми двумя (`inflight_budget` тест есть; живьём — `chain_max_lag_items` узлов в `introspect.status`).
**Out of scope:** аппаратные камеры (QR-прибор на триггере).

### Task 5.9a — Валидатор моделирует проход ключа; рецепты получают провода (найдено в 5.0, решение 9 CTO)
**Level:** Middle+ (Sonnet) · **Assignee:** developer, tester (слепой — по yaml и `check()`), reviewer · **Layer:** mixed
**Goal:** `multi_camera.yaml` и `inspection_basic.yaml` стартуют; валидатор не требует, чтобы вход узла объявил непосредственный предшественник, если ключ доступен выше по цепочке.
**Основание:** 5.0(г) — оба рецепта падают `SystemExit(1)` на `check()`. Разбор CTO ([`docs/reviews/2026-10-02_phase5-design-cto.md`](../../docs/reviews/2026-10-02_phase5-design-cto.md), решение 9): два дефекта. A (фреймворк): `validate_chain` (`port.py:210-231`) и `_is_covered_by_auto_wiring` (`blueprint.py:1006`) смотрят только предыдущий узел, а рантайм — dict, ключ живёт до перезаписи. B (прототип): у рецептов никогда не было `wires:` (в версии до `917ec7ed4` — тоже); `917ec7ed4` добавил только строку `color_mask → blob_detector`.
**Files:** `multiprocess_framework/modules/process_module/plugins/port.py` (`validate_chain` → накопленная доступность: `wired_inputs процесса ∪ выходы предыдущих узлов`), `multiprocess_framework/modules/process_manager_module/topology/blueprint.py` (`_is_covered_by_auto_wiring` → та же функция), `multiprocess_prototype/backend/topology/multi_camera.yaml`, `inspection_basic.yaml` (секция `wires:` по образцу `inspection_full.yaml:171-198`), новый `multiprocess_framework/modules/process_module/tests/test_validate_chain_passthrough.py`, новый `multiprocess_prototype/backend/tests/test_topology_recipes_check.py` (все `backend/topology/*.yaml` без TEMPLATE/archive/tests → `check() == []`); строка-ссылка в `plans/pipeline-node-timing.md`.
**Acceptance criteria:**
- [ ] `check()` на `multi_camera.yaml` и `inspection_basic.yaml` → 0 ошибок; оба стартуют живьём 30 с (`sweep50.py` из `docs/audits/2026-10-02_transport-facts/`).
- [ ] Инъекция «у `color_mask` убран выход `mask`» → ошибок 0 (`blob_detector.mask` optional); инъекция «у источника убран `frame`» → ошибка названа.
- [ ] Страж по всем рецептам зелёный на HEAD и красный при удалении одного провода.
**Out of scope:** вывод проводов из `chain_targets` (меняет вывод join-коллекторов, ADR-уровень); `dualcam_synth.yaml`.
**Гейт-рецепт двух камер для 5.9 (OWNER-10, рекомендация CTO):** `scripts/capacity_bench/recipes/stand_dualcam.yaml` — закреплённая копия по конвенции `stand.yaml:1-4`: 2 синтетических источника 1080p → fan-in processor с `extras: {overflow: every}` → inspector → storage/gui; собирается из `multi_camera.yaml` после 5.9a. `dualcam_synth.yaml` не годится: нет fan-in узла.

### Task 5.10 — Одна дверь переполнения (Фаза 1 в сокращённой форме; условно)
**Level:** Senior+ · **Assignee:** teamlead, tester, reviewer; ADR — tech-writer · **Layer:** framework
**Условие запуска:** 5.0(а) показал data-трафик через kind-каналы (`sent_via_channel > 0` на data) ИЛИ владелец решил делать безусловно (OWNER-3). Иначе — фаза 6, но инвариант-тест «одна дверь» пишется здесь.
**Goal:** решение «что делать с полной очередью» существует в репозитории один раз (`send_to_queue`); `QueueChannel` без собственного `put(timeout=1.0)`; инвариант проверяется тестом.
**Files:** `multiprocess_framework/modules/router_module/channels/queue_channel.py`, `multiprocess_framework/modules/router_module/interfaces.py` (`ProcessQueueDescriptor`), `multiprocess_framework/modules/router_module/core/router_manager.py` (`_do_send`: дескриптор → `send_to_queue`), `multiprocess_framework/modules/process_module/communication/process_communication.py` (`register_router_channels`), новый `multiprocess_framework/modules/tests/test_one_overflow_door.py` (AST: `put(`/`put_nowait(` только в `queues/core/manager.py`), `.sentrux/rules.toml`, `multiprocess_framework/modules/router_module/DECISIONS.md` (ADR из Task 1.4 с Rejected-блоком A/C/E/binding-map), `multiprocess_framework/DECISIONS.md`.
**Steps:** по Task 1.2 шаги 1–3, 6, 7; шаг 4 (независимость от «кольцо < очередь») — уже ADR-173; шаг 5 — характеризационные тесты доставки.
**Намеренно меняемые тесты:** характеризационные тесты `QueueChannel.send` с таймаутом 1.0 с; `test_live2_evict_release.py` — на обоих путях адресации (если loan удалён в 5.7 — переписать на `data_evicted` без release).
**Acceptance criteria:** из Task 1.2 (`phase-0-1.md:103-110`) без пунктов про `on_evict`/loan, если loan удалён; плюс:
- [ ] Инвариант «одна дверь» зелёный на HEAD и красный при инъекции прямого `put` в любой другой модуль.
- [ ] `put_timeout_total` удалён (или 0 по построению, тест-инъекция).
- [ ] Стенд-гейт зелёный после правки; `sent_via_channel_policy > 0` на data, если kind-каналы для data есть.
**Out of scope:** богатое самоописание канала; опрос сообщением.

### Task 5.11 — Индикатор потерь в карточке процесса (остаток 2.1)
**Level:** Middle+ (Sonnet) · **Assignee:** developer, reviewer (qt-mcp смоук) · **Layer:** prototype
**Goal:** оператор видит потери без чтения счётчиков: кадров/с потеряно и записей `not_inspected`/с, подсветка при > 0 в установившемся режиме.
**Files:** виджет карточки процесса в `multiprocess_prototype/frontend/` (точный путь — по `docs/refactors/2026-04_widgets_reorg.md`, домен `pipeline/`), чтение из дерева телеметрии (после 5.6), тесты pytest-qt + qt-mcp смоук.
**Acceptance criteria:**
- [ ] На `stand.yaml` под `every` карточка inspector показывает `not_inspected/с` ≈ (`born` за окно)/30 ± 10 %; processor — `lag/с`; под `latest` — `lag/с` и 0 маркеров.
- [ ] qt-mcp: `qt_snapshot` содержит индикатор, `qt_messages` без новых warning'ов; Dict at Boundary.
**Out of scope:** дашборды, алертинг.

---

### Приёмка фазы (CTO, один раз)
Три линзы: (1) стенд-гейт 5.6 зелёный трижды на двух рецептах, числа в отчёте; (2) инъекции по каждой заявленной гарантии 5.2/5.3/5.4 — записаны в задачах; (3) основание для фазы 6: ADR 5.2/5.3/5.7(/5.10), план без лага за кодом, `OPEN_QUESTIONS` обновлён. Условие приёмки — «Не проверено» непустое и названное.

### Что сознательно не делаем в фазе 5
Маркер у писателя; `color_mask`/`render_overlay` ROI/B-7 (после чисел 5.8); 4.8b/4.8c; per-object tracking в решателе; вытеснение у владельца очереди до замера 5.7; смена умолчания `overflow` (OWNER-4).

---

## Сверка остатков фаз 0–4 (CTO, 2026-10-02)

Сверка остатков `plans/transport-single-policy` по коду и `git log` на `fc37a369d` (main). Источник каждого вердикта — в графе «Опора» (файл:строка, SHA, прогон). Статусы в файлах отстают от кода в семи местах — отмечено «галочки отстают».

| Пункт | Что осталось по файлу плана | Вердикт | Опора |
|---|---|---|---|
| 0.1 счётчики дверей | чекбоксы `phase-0-1.md:18-20` пусты | **сделано, галочки отстают**; живую проверку `introspect_router_stats` — в 5.0 | `router_manager.py:246-247` (`sent_via_channel`/`sent_via_targets`), `queue_channel.py:45,78` (`put_timeout_total`), `:1886` в `get_stats` |
| 0.2 живой замер «какой дверью кадры» | не начат | **слить с 5.0** (один прогон, счётчики 0.1 уже есть); гипотезы §8.4 про webcam-soak и loan-конверты **устарели** — флаги `FW_SHM_*` сняты в 4.7b, loan заморожен | `plan.md:36`; 4.7b `4b773d416` |
| 0.3 строгие имена в soak-пробе | чекбоксы `:49-50` пусты | **сделано, галочки отстают** (plan.md:36 «0.3 в main»); жива ли проба `g7_soak_probe` на нынешнем стенде — не проверял → 5.0 | `plan.md:36` |
| 1.1 guard чужого reader'а в `release_evicted` | не начат | **зависит от 5.7**: loan удалён → устарело; loan оставлен → делать как есть после 5.7 | `FW_SHM_LOAN_PROTOCOL` FROZEN (`task-4.7.md` п. 6) |
| 1.2 одна политика двери | не начат; дверь Б по-прежнему `put(block=True, timeout=1.0)` | **слить с 5.10** в сокращённой форме, после 5.0(а) и 5.3: пачка маркеров (причина `delivery_failed`) уходит в 5.3, стойло двери Б — вопрос, ходит ли data-трафик через kind-каналы вообще (5.0) | `queue_channel.py:60-80`; ревью CTO MAJOR-2 |
| 1.3 probe-рецепт «кольцо 64, очередь 4» | не начат | **устарело**: очередь 4 противоречит ADR-173 (очередь — потолок памяти 50); цель «вытеснение и release исполняются живьём» закрывается стенд-гейтом 5.6 и приёмкой 5.10 | ADR-173 п. 3 |
| 1.4 ADR «одна политика» + поправка ADR-RTR-010 | не начат | **слить с 5.10** (ADR) и с 5.7 (если loan удалён — ADR-RTR-010 получает пометку «снято») | — |
| 2.1 потеря кадров в телеметрию и GUI | не начата | **разделить**: экспорт счётчиков в дерево телеметрии → 5.6; индикатор в карточке процесса → 5.11 | ADR-174 «счётчики не попадают в дерево телеметрии»; `heartbeat/telemetry.py:59-64` |
| 3.1 провенанс вердиктных счётчиков (`BLIND_SPOT`) | не начата | **вне фазы 5**: зависит от дескрипторов 1.2 (5.10); переоценить после 5.10 | `phase-2-3.md:31-32` |
| 4.1 хвост acceptance (`phase-4.md:47-53`) | 7 чекбоксов пусты | байты ≤ порога и 0 `SHM fallback` — **сделано по аудиту 2026-09-29** (≤ 781 Б, 0 fallback на 50/100 fps 1080p), галочки отстают; break-injection `mask` → 307 848 Б — **не проверено**, проставить по отчёту ревью 4.1 или снять; универсальность `foo` — сделано (`test_claim_check_any_key.py`); перемер 20 стопов для `lifecycle-stop-ownership` → **слить с 5.6** (критерий «стоп чистый») | `phase-4.md:185`; 4.4 статус |
| 4.2 формат ссылки + имена | — | **сделано** внутри 4.4/4.7b | `phase-4.md:209` |
| 4.3 стенд высокой частоты, приёмка 480p/1080p × 60/100 | открыт | **слить с 5.6** (матрица `capacity_bench --profile full`); критерий «stale = torn = 0» **устарел** — заменён ADR-173/174: stale считается, маркеруется, порог ≤ 0.1 % | `phase-4.md:208`; ADR-174 п. 5 |
| 4.3a темп источника | ✅ | сделано | `53d17d9d` |
| 4.4 A1–A8 + живьём | чекбоксы `phase-4-redesign.md:87-107` пусты | **сделано, галочки отстают** (статус ✅ `d0901979`, tester 24 RED → green, живьём 0 чужих кадров) | `phase-4-redesign.md:114-122` |
| 4.5 acceptance (`task-4.5.md:32-41`) | чекбоксы пусты | **сделано, галочки отстают** (✅ `14fdf123`); «стоимость ≤ +1 %» и «CPU ±5 %» — проставить по отчёту закрытия, не перемерять | `phase-4-redesign.md:145` |
| 4.6 потоки OpenCV | чекбоксы `:156-157` пусты | **сделано, галочки отстают** (✅ `939be356`, таблица 1/2/4 есть) | `phase-4-redesign.md:161-173` |
| 4.7 верхний acceptance (`task-4.7.md:77-94`) | 8 чекбоксов пусты | флаги, имена, 100 realloc, `blob_detector`, умолчания, `overflow` — **сделано** (4.7b/c/d), галочки отстают; «все рецепты `backend/topology` стартуют 30 с без `read-only` ValueError» — **не проверено** → 5.0(г); «живьём stale-доля vs 4.4» — закрыто стендом 4.7d-5 (stale_restore ≈ 1 % у inspector), проставить с числом | `task-4.7.md:550` |
| 4.7b хвосты | `deferred_closes` не в телеметрии; кэп моста 32 даёт 0 попаданий при 5×8 и 3×12; prefix-cleanup/сироты POSIX | `deferred_closes` → **5.6**; кэп моста → **5.9**; сироты POSIX → **владельцу** (OWNER-11) | `task-4.7.md:173-174`; `remote_frame_source.py:72` |
| 4.7e несколько камер | не начата (только спека `9ae6621e2`) | структурные пункты (имена, бюджет по min глубины, `inflight_budget([8,12]) == (4,2)`) **сделаны** 4.7b/c; живой двухкамерный прогон и кэп моста → **5.9**. Рецепта `dualcam_synth` нет; есть `multiprocess_prototype/backend/topology/multi_camera.yaml` (состав не читал) | `ls backend/topology` |
| 4.7 out of scope (шаги 3–5 вердикта Ф4): B-7 per-target, `render_overlay` ROI, `color_mask` без потребителя | открыты | **вне фазы 5** до чисел 5.8; `color_mask` — продуктовое решение владельца (OWNER-7) | `phase-4.md:206-207` |
| 4.8a бенч | ✅ `95093b96` | сделано; nits (`fields.window` при смене воркеров, сирота, Ctrl+C) — **как есть**, в 5.6 при переносе стенд-скрипта | `task-4.8.md:131-145` |
| 4.8b выводы о мощности | не начата | **как есть**, после 5.8 (питается отчётом 5.6); остаётся в `task-4.8.md` | — |
| 4.8c запуск бенча из GUI | решение владельца | **вне фазы 5** (не транспорт), OWNER-6 | `task-4.8.md:150-157` |
| N3 `_last_loan_exhausted` | известный дефект | → **5.7** | `frame_shm_middleware.py:454,876,1147,1204,1293` |
| OPEN_QUESTIONS: маркер по разрыву `frame_id` | владельцу | **частично снимается 5.3 + 5.4** (пачки и стартовые вытеснения); остаток — после 5.6 (OWNER-5) | `OPEN_QUESTIONS.md:1373-1377` |
| OPEN_QUESTIONS: `every` + `reject_delay_ms > 0` несовместимы | владельцу | **закрывает 5.2** | `OPEN_QUESTIONS.md:1412-1427` |
| Красные на main (5 тестов) | — | **5.5** | прогон CTO 2026-10-02: 5 failed / 26 passed |

## Решения владельца (OWNER-1…12, рекомендации CTO)

1. **Регистр задержки привода (5.2).** Варианты: (а) новый `transit_ms` + `actuation_tolerance_ms`, `reject_delay_ms` — deprecated-алиас с WARNING на старт; (б) переосмыслить `reject_delay_ms` на месте. **Рекомендую (а):** имя `reject_delay_ms` описывает сон, которого больше нет; алиас сохраняет рецепты.
2. **Планировщик привода — в плагине или сервис процесса (5.1, вопрос 1).** **Рекомендую сервис процесса** (`ProcessModule`), чтобы любой будущий решатель не повторял механизм; первая реализация — только для `robot_control`, интерфейс — один метод `schedule`.
3. **Фаза 1 (одна дверь, 5.10) — в фазе 5 или после.** **Рекомендую условно:** решает факт 5.0(а); при data-трафике через kind-каналы — в фазе 5, иначе — инвариант-тест и ADR сейчас, унификация в фазе 6.
4. **Умолчание `overflow`.** Сегодня `latest` везде (решение 2026-10-01). **Рекомендую оставить `latest` умолчанием**, но в `TEMPLATE.yaml` и `inspection_*.yaml` прописать `extras: {overflow: every}` у процессов с решателем; пересмотреть после трёх зелёных прогонов 5.6 с A/B (`queue_wait_ms`, трафик записей).
5. **Маркер по разрыву `frame_id` у писателя.** **Рекомендую не делать:** 5.3 убирает пачки, 5.4 — стартовые вытеснения; остаток виден в `queue_data_evicted` под `every` на гейте 5.6; вернуться, только если он > 0 три прогона подряд.
6. **4.8c — бенч из GUI.** **Рекомендую вне транспортного плана** (отдельный план prototype после 5.11).
7. **`color_mask` без потребителя и `render_overlay` ROI.** Продуктовые решения. **Рекомендую отложить до чисел 5.8**: если processor держит 100 fps с пулом, `color_mask` остаётся; renderer под `latest` с 39 мс — по замыслу, ROI только если нужен preview > 25 Гц.
8. **Пороги «стабильной системы» (5.6):** stale_restore ≤ 0.1 %, lag processor ≤ 1 %, `queue_data_evicted = 0`, `errors_delivery_failed = 0`, ΔRSS < 20 МиБ/ч, вердиктов ≥ 0.9 × (кадры − потери). **Рекомендую утвердить как стартовые** и пересмотреть после первых трёх ночных прогонов — это предложение ревью, не измеренная норма.
9. **Ночной стенд-гейт:** на какой машине и в какое окно (протокол замка, ~5 мин на рецепт, 2 рецепта × 3 прогона ≈ 30 мин). Решение владельца по железу и времени.
10. **Двухкамерный рецепт (5.9):** расширить `multi_camera.yaml` синтетическими источниками 1080p или завести `dualcam_synth.yaml`. **Рекомендую расширить существующий** — без зависимости от аппаратных камер.
11. **Сироты сегментов POSIX и prefix-cleanup** (хвост 4.7b, вопрос уже в `OPEN_QUESTIONS.md`): нужен ли уборщик на старте для Linux/Orin. **Рекомендую решить при первом Linux-прогоне 4.8a**, не в фазе 5.
12. **Loan-протокол (5.7):** удалить при stale_restore ≤ 0.1 % на глубине ≤ 12. **Рекомендую удалить** по правилу, записанному до замера; оставить — только если владелец видит сценарий, где перезапись с проверкой поколения не годится (например, долгие ML-плагины > глубина/fps — тогда это аргумент за глубину, а не за loan).

## Не проверено (CTO)

- Какой дверью ходят data-кадры (А через targets или Б через kind-канал) — не проверял; план 5.10 условный именно из-за этого (5.0(а)).
- Доходит ли `system_ready_event` до generic-детей: по коду его читает PM (`process_manager_process.py:131/324`), о детях не знаю (5.0(б)).
- `WorkerPoolDispatcher`: сохранение порядка и совместимость с тикетами `_shm_views` — не читал; 5.8 начинается с этого факта.
- Состав `multi_camera.yaml` (синтетика или железо) — не читал.
- Путь леджера займов: в `shared_resources_module/memory/` есть `pool/`, файл `loan_ledger.py` по пути из Task 1.1 грепом не нашёл — Files 5.7 уточнить при удалении.
- Жива ли `g7_soak_probe` против нынешнего бэкенда — не запускал; судьба 0.3/3.1 зависит от 5.0(е).
- Галочки 4.1 (break-injection `mask` → 307 848 Б) — есть ли отчёт, не проверял; «проставить или снять» — после чтения ревью 4.1.
- Арифметика D100 (893 маркера × 100 мс > 30 с окна) не сведена; критерий 5.2 опирается на долю вердиктов, а не на эту сумму.
- Размер pickle записи с 1078 `trace_ids` — не измерял; порог 64 КиБ в 5.3 — ожидание, проверяется тестом.
- Segfault `test_sampler_ceiling_policy` в общем прогоне и `test_catalog_kind_roundtrip.py:67` — не воспроизводил; 5.5 начинается с диагноза.
- Пороги §5/OWNER-8 — предложение по ревью, не измеренные нормы линии.
- Пилотный вывод «разбор дизайна у CTO до кода окупается» (5.1) — гипотеза по одному треку; измерить токены и находки 5.1 так же, как в `docs/claude/pilot-company-v2.md`.
