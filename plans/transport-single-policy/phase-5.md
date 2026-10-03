> Часть плана [`transport-single-policy`](plan.md). Основание — ревью системы CTO
> [`docs/reviews/2026-10-02_transport-system-review-cto.md`](../../docs/reviews/2026-10-02_transport-system-review-cto.md)
> (репродукции `scratchpad/cto_sys/cto_sys.py`, стенд 4.7d-5 `22a63e46b`). Сверка остатков фаз 0–4 — в конце этого
> файла («Сверка остатков фаз 0–4») и в `plan.md`, раздел «Порядок». Текст написан CTO (Fable) 2026-10-02, разложен лидом
> дословно.

## Фаза 5 — Форма потери и контракт привода (2026-10-02)

**Гейт входа:** 4.7d слита в main (`fc37a369d`), ревью системы принято владельцем.
**Гейт выхода (объём по решению владельца 2026-10-02):** стенд-гейт 5.6 зелёный на `stand.yaml` три прогона подряд; `multi_camera.yaml` и `inspection_basic.yaml` стартуют (5.9a); 1080p@60 без потерь (5.8); main зелёный (5.5); ADR на решения 5.2/5.3.

### Объём фазы — решение владельца 2026-10-02

Владелец спросил, нужна ли фаза целиком. Ответ лида: нет. Половина задач чинит то, что сломается на линии; вторая половина — гигиена или улучшения «на будущее». Владелец выбрал **урезанный объём, не теряя остальное из вида**.

**В работе:** 5.0 ✅ → 5.1 ✅ → **5.5** → **5.2** ∥ **5.3** ∥ **5.4** → **5.6** ∥ **5.9a** → **5.8** ∥ **5.11**.
Почему: 5.2 — без неё инспектор на линии с задержкой привода даёт 0 вердиктов (D100: `born=3008 handled=0`); 5.3 — поимённый учёт каждой единицы при сбое (владелец: нужна); 5.4 — без неё не бывает прогона с «потерь 0»; 5.9a — два рецепта не стартуют; 5.5 — гигиена, два настоящих дефекта Windows; 5.6 — «инспектор с числами» одной командой; 5.8 — «выжать максимум» (владелец: 1080p при 60–100 кадрах/с — уже хорошо); 5.11 — оператор видит потери (владелец: нужна).

**Поправка владельца в тот же день:** первый выбор — урезанный объём (5.5, 5.2, 5.4, 5.9a, 5.6); затем владелец вернул 5.3 и 5.11 и уточнил цель 5.8.

**Отложено (не удалено) — условие возврата записано до того, как оно наступит:**

| Задача | Что даёт | Вернуться, когда |
|---|---|---|
| 5.7 транзит и loan | удаление замороженного loan (~1000 строк), закрытие N3 и Task 1.1 | рефакторинг `frame_shm_middleware.py`/`pipeline_executor.py` по любой причине, или `stale_restore` > 0.1 % на гейте 5.6 |
| 5.9 две камеры живьём, кэп моста | гейт на двухкамерном рецепте | нужна вторая камера (робот, линия); 5.9a уже даёт старт рецепта |
| 4.8b выводы о мощности | «сколько камер тянет машина» | после 5.8 — питается её числами |
| 5.10 одна дверь | — | **снята по факту 5.0(а)**: data не ходит дверью Б. Вернуть — только решением OWNER-3 |

Оценка цены: этот объём ≈ 5–7 млн токенов против 6–10 млн за полный (полный процесс: тестер, исполнитель, инъекции, ревью ≈ 0.5–1 млн на задачу). Оценка — по замерам «Компании v2/v3», не измерена на этой фазе.

**Почему эта фаза, а не «тюнинг»:** три репродукции ревью показали, что потери в тракте уже считаются верно (формула 4.7d сошлась), но их *форма* ломает систему там, где она нужна: задержка привода в потоке конвейера морит кадры голодом (`frames_processed=50 из 300` при задержке 20 мс на маркер и периоде 10 мс), пачка маркеров по одному сообщению теряется на следующем хопе (`reader_got=134 из 2156`, `delivery_failed=612`), старт теряет 24–41 кадр без маркера. Фаза меняет форму, не механизмы: кольцо, поколение, bound, формула остаются.

**Числа стенда, на которые ссылаются критерии (4.7d-5, 1080p@100, окно 30 с):** E1–E3 `every`: processor `lag` 105–316, inspector `stale_restore` 43–46, `queue_data_evicted` на старте 24–41; P10 (пауза исполнителя 10 с): голова 1078 маркеров, недостача соседей 1317 = `queue_data_evicted` 245 + `errors_delivery_failed` 1076; D100 (`reject_delay_ms=100`): inspector `born=3008 handled=0`, журнал 893 строки — все маркеры; renderer `render_overlay` ≈ 39 мс, дропы ≈ 1800/30 с; storage ≈ 670/30 с.

**Правила фазы:** слепой tester до кода на каждый механизм (worktree на коммите до реализации); инъекции лида по обоим наборам тестов; ревью Opus после каждой задачи; CTO — один разбор дизайна (5.1) и одна приёмка фазы; стенд — только скриптом 5.6 после того, как он есть, до того — `stand47d.py` лида по протоколу замка. Слова «невозможно/гарантировано» в задачах не употребляются без репродукции рядом.

### Порядок и параллельность

```
Волна 0:  5.0 (лид, без кода)  ∥  5.5 (developer/debugger; файлы ни с кем не пересекаются)
Волна 1:  5.1 (CTO, разбор дизайна 5.2 и 5.3 — до первой строки кода в них)
Волна 2:  5.2 (robot_control)  ∥  5.3 (маркер/приёмник/исполнитель/дверь)  ∥  5.4 (источник/PM)
          — три писателя, файлы не пересекаются (контракт «маркер с count» зафиксирован в 5.1,
            поэтому 5.3 НЕ трогает robot_control, а 5.2 принимает count с первого дня)
Волна 3:  5.6 (стенд-гейт + экспорт счётчиков) ∥ 5.9a (валидатор портов + провода рецептов) → первый прогон гейта закрывает acceptance 5.2/5.3/5.4
Волна 4:  5.8 (пул исполнителя, batch-commit; цель 1080p@60 без потерь)  ∥  5.11 (GUI-индикатор)
Отложены: 5.7, 5.9 (условия — «Объём фазы»), 4.8b после 5.8; 5.10 снята по факту 5.0(а)
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
**Редакция 3** (ревью спек [`docs/reviews/2026-10-02_phase5-spec-review-w2.md`](../../docs/reviews/2026-10-02_phase5-spec-review-w2.md): итерация 1 — 4 блокера, итерация 2 — 1 блокер (`auto_start`) и minor, внесены заменами ревьюера; третьей итерации нет — лимит 2, проверка — инъекции и ревью кода).
**Goal:** в `process()` решателя нет ожидания; отбраковка планируется по `capture_ts + transit_ms` и исполняется планировщиком; устаревшая цель не стреляет, а считается.
**Files:** `Plugins/control/robot_control/plugin.py`, `Plugins/control/robot_control/registers.py`, `Plugins/control/robot_control/readme.txt`, новый `multiprocess_framework/modules/process_module/generic/actuation_scheduler.py` (решение 1 CTO), новый `multiprocess_framework/modules/process_module/tests/test_actuation_scheduler.py`, `multiprocess_framework/modules/process_module/plugins/base.py` (свойство `PluginContext.scheduler`), `multiprocess_framework/modules/process_module/plugins/interfaces.py` (`IActuationScheduler`), `multiprocess_framework/modules/process_module/plugins/__init__.py` (экспорт `IActuationScheduler` в `__all__`), `Plugins/control/robot_control/tests/` (новые + намеренно изменяемые), новый `multiprocess_framework/modules/process_module/tests/test_no_blocking_in_plugin_process.py` (страж), `multiprocess_framework/modules/process_module/DECISIONS.md` (ADR планировщика). `TEMPLATE.yaml` не трогается: блока `robot_control` в нём нет (только комментарий `:61`).
**Пересечение файлов:** с 5.3 и 5.4 — ноль. `test_t47d4_marker_policy.py` — только 5.2. Писатели НЕ запускают `python -m scripts.sync` (он переписывает `multiprocess_framework/DECISIONS.md` — файл 5.3); sync, README/STATUS `process_module` и галочки делает лид на слиянии.
**Дизайн (по решениям 5.1, [`docs/reviews/2026-10-02_phase5-design-cto.md`](../../docs/reviews/2026-10-02_phase5-design-cto.md)):**
- **Регистры.** `transit_ms` (умолчание 0), `actuation_tolerance_ms` (умолчание 20). `reject_delay_ms` — deprecated-алиас (OWNER-1): `effective_transit = transit_ms or reject_delay_ms`, читается на каждом вызове `process()`; при ненулевом `reject_delay_ms` — WARNING один раз на экземпляр плагина (поправка лида при слиянии: проверка в начале `process()` при любом исходе; два экземпляра в процессе — две строки), текст содержит `reject_delay_ms`. `cmd_set_delay` пишет `transit_ms` и логирует WARNING «`set_delay` устарела, пишет `transit_ms`» (решение лида). `effective_transit == 0` → планировщик не используется, статус `immediate`, `fire` синхронно (решение 8).
- **`ActuationScheduler`** — класс фреймворка `process_module/generic/actuation_scheduler.py`. Конструктор `ActuationScheduler(fire, *, clock=time.time, tolerance_s=0.020)`; `clock` — та же шкала, что `capture_ts` (`source_producer.py:188`). Heap под `threading.Condition`. Колбэк `fire(payload, count)` вызывается ВНЕ `Condition`: медленный `fire` будущего привода не должен блокировать `schedule()` в потоке исполнителя.
  - `schedule(fire_at, window_end, count, payload) -> "scheduled" | "missed"`: `now > window_end + tolerance_s` → `missed_items += count`, в heap не ставится; иначе `fire_at = max(fire_at, now)`, постановка, `notify()`.
  - `tick() -> int`: стреляет все `fire_at ≤ now`; `late_fires += 1`, если `now − fire_at > tolerance_s`; `fired_items += count`. Возвращает число выстрелов.
  - `pending() -> int` — записей в heap. `stats() -> dict` — `fired_items`, `missed_items`, `late_fires`, `unfired_on_stop_items`.
  - `run_loop(stop_event, pause_event)` — сигнатура как `PipelineExecutor.run` (`pipeline_executor.py:153`). Ждёт на `Condition` до ближайшего `fire_at` (или до `notify()` из `schedule`), шаг ожидания ≤ 0.05 с для проверки `stop_event`. На стопе невыстреленное не стреляет: `unfired_on_stop_items += count`, heap очищается.
- **Вход `PluginContext.scheduler`** (решение владельца 2026-10-02, переворачивает часть решения 1 CTO): ленивое свойство, один `ActuationScheduler` на процесс. `PluginContext` у каждого плагина свой (`base.py:83-84`, `with_config` `:167-186` создаёт новый), поэтому экземпляр хранится на `self.services` (атрибут `_actuation_scheduler`), get-or-create под замком; второй плагин получает тот же объект, второго `create_worker("actuation")` нет. Импорт `ActuationScheduler` — внутри свойства (риск цикла `generic/__init__.py:20` → `generic_process` → `plugins`). Первое обращение при `self.worker_manager is not None` запускает воркер `create_worker("actuation", scheduler.run_loop, ThreadConfig(...), auto_start=True)` — **`auto_start=True` явно**: у настоящего `WorkerAdapter.create_worker` умолчание `False` (`worker_adapter.py:50-55`), у Protocol и фейка — `True`, юниты этого не покажут. Режим `ThreadConfig` — тот, что даёт цели `(stop_event, pause_event)` один вызов на жизнь воркера (сверить в `worker_module`; образец создания — `Plugins/io/database/plugin.py:98-99`). При `None` (юниты) — без воркера, `tick()` зовут руками. Протокол `IActuationScheduler` (`schedule`, `pending`, `tick`, `stats`) — в `process_module/plugins/interfaces.py`. `generic_process.py` не трогается (файл 5.4). `robot_control` обращается к `self._ctx.scheduler` только при `effective_transit > 0` — при 0 планировщик не создаётся.
- **`process()` решателя:** решение → `_write_verdict` на фронте (как сейчас) → статус `actuation` → широкая запись с `actuation`, `fire_at`, `transit_ms` → `return item`. Значения `actuation`: `scheduled` / `missed` (от `schedule()`), `unscheduled` (нет `capture_ts`: `unscheduled_items += count`, без постановки), `immediate` (`reject` при `effective_transit == 0`), `none` (`pass`). **Планируется только `reject`;** `pass` и маркер с исходом `pass` в очередь не ставятся. `time.sleep` удалён из `process()` и `_process_marker` (сегодня `plugin.py:198`, `:240`). Вердикт пишется на решении; `fire` пишет только счётчики (решение 6).
- **`capture_ts` у решателя:** доезжает через перенос системных полей `plugin_runner.py:60` (`_CARRIED_SYSTEM_FIELDS`). Тест на настоящем `PluginRunner`, не на голом dict.
- **Запись о разрыве (5.3) и маркеры старой формы.** 5.3 в worktree 5.2 нет, поэтому код читает обе формы: `count = item.get("count", 1)`; `first = item.get("first_capture_ts", item.get("capture_ts"))`, `last = item.get("last_capture_ts", item.get("capture_ts"))`. Одна постановка с окном `[first + transit, last + transit]`; `total_not_inspected += count`; фронт `_rejecting` не меняется. Источник: `source`, если есть, иначе гистограмма `sources`; причина: `reason`, если есть, иначе гистограмма `reasons` (сегодня `origin = item.get("reason")`, `plugin.py:233`, дал бы `None` у записи со смешанными причинами).
- **Широкая запись с `count > 1`** (решение лида): несёт `count` и `trace_ids` (список); `trace_id` пуст. Поимённый поиск — по полю `trace_ids`. 5.6 сводит учёт как «кадры − Σ `count` по записям решателя = 0», а не «кадры − строки».
- **Ключи `cmd_get_stats` (литералы):** `actuation_fired_items`, `actuation_missed_items`, `actuation_late_fires`, `actuation_unscheduled_items`, `actuation_unfired_on_stop_items`. Один термин — `missed_items`; `missed_actuation` больше не используется.
- **Страж:** AST по `<корень>/**/plugin.py`, функции `process` / `_process_*`: вызов `time.sleep` / `sleep(` → красный с именем файла и строкой. Корень — параметр (тест передаёт `tmp_path` с синтетическим плагином, в `Plugins/` не пишет); боевой прогон — по `Plugins/`. На сегодняшнем HEAD страж находит ровно 2 места: `robot_control/plugin.py:198`, `:240`.
- Критерий «стреляет в `[fire_at, fire_at + 0.002]`» — только с подменными часами; живьём — `late_fires` и p99 опоздания числом (Windows: сетка 15.6 мс).
**Steps:** 1. tester: слепые тесты по acceptance в worktree до кода. 2. Исполнитель до кода проверяет и пишет в отчёт три факта, не проверенных ревью спек: режет ли `write_event` поле `trace_ids` на ~38 КБ (1078 id); пинит ли `plugins/tests/test_plugin_manifest.py` поверхность `PluginContext` / требует ли новое свойство поднять `PLUGIN_API_VERSION`; безопасен ли `create_worker` из потока исполнителя (прецедент `device_hub/plugin.py:391`). Регистры + планировщик + `PluginContext.scheduler` + перевод `process()`. 3. Страж. 4. Инъекции лида (≥ 7: планировщик стреляет по `missed`-цели; стреляет дважды на окно; `tolerance` не читается; `count` не суммируется; фронт сломан; `sleep` вернулся; `pending()` не уменьшается после `tick()`). 5. Ревью. 6. Стенд-гейт.
**Намеренно меняемые тесты:** `Plugins/control/robot_control/tests/test_t47d4_marker_policy.py:274` (`test_reject_delay_applies_to_a_rejected_marker`, acceptance 4.7d-4: `process` длится ≥ 50 мс) → «< 1 мс, `ctx.scheduler.pending() == 1`»; `test_plugin.py:225-242` (`cmd_set_delay`) → проверяет `transit_ms` и WARNING. В `test_plugin.py` кейса тайминга обычного брака нет — новый пишет tester. `test_wide_event_emitter.py` — без изменений. `test_verdict_documents.py` — изменён (поправка лида при слиянии: «без изменений» было ошибкой — вердикт пишется до выстрела механизма, тест стал `test_verdict_is_written_before_the_mechanism_fires`).
**Acceptance criteria:**
- [ ] `process()` на браке и на маркере при `transit_ms=100`, `ctx` — настоящий `PluginContext` с `worker_manager=None`: p99 длительности из 1000 вызовов < 1 мс; после каждого вызова `ctx.scheduler.pending()` вырос ровно на 1.
- [ ] Планировщик с подменными часами: цель `fire_at = capture_ts + 0.100` стреляет в `[fire_at, fire_at + 0.002]`. `schedule()` при `now > window_end + tolerance_s` → `"missed"`, `stats()["missed_items"] == 1`, `pending() == 0`. Цель, поставленная вовремя, при `tick()` позже `fire_at + tolerance_s` стреляет, `late_fires == 1`.
- [ ] Запись о разрыве — фикстура = литерал записи из acceptance 5.3 с `count=1078`: одна постановка, одно срабатывание на окно `[first + transit, last + transit]`, `fire` получил `count=1078`, `total_not_inspected += 1078`. То же для маркера старой формы (без `count`): `count = 1`.
- [ ] `pass` при `transit_ms=100`: `pending() == 0`, в широкой записи `actuation == "none"`. `reject` при `transit_ms=0` → `actuation == "immediate"`, `fire` вызван синхронно, `pending() == 0`.
- [ ] Item без `capture_ts` на `reject` → `actuation == "unscheduled"`, `actuation_unscheduled_items == 1`, `pending() == 0`.
- [ ] `reject_delay_ms=50`, `transit_ms=0` → поведение `transit_ms=50` и одна строка WARNING с `reject_delay_ms` на 100 вызовов.
- [ ] Настоящий `WorkerAdapter` (не фейк): после первого обращения к `ctx.scheduler` воркер `actuation` запущен; цель с `fire_at = now + 0.05` выстрелила за ≤ 0.2 с; два плагина одного процесса получают один и тот же объект `ctx.scheduler`; `stop_all` останавливает воркер `actuation`.
- [ ] Стоп с 3 записями в heap: `run_loop` выходит ≤ 0.1 с после `stop_event.set()`, `fire` не вызван, `unfired_on_stop_items == 3`.
- [ ] Страж красный на синтетическом плагине с `time.sleep` в `process()` (корень `tmp_path`) и зелёный на `Plugins/` после правки.
- [ ] Обычный item без детекций — `pass`; с детекцией — `reject`, вердикт на фронте (существующие тесты зелёные, кроме перечисленных выше).
- [ ] **Стенд-гейт (D100 заново):** `stand.yaml` 1080p@100, `every` на processor+inspector, `transit_ms=100`, 30 с, 3 прогона: широких записей решателя с вердиктом за прогон ≥ 0.9 × (кадров камеры − Σ `count` записей `not_inspected`) — в единицах, не в строках журнала (ред. 2026-10-03: запись `count>1` несёт много кадров; на стенде 930 строк = 1847 единиц); маркеров у inspector того же порядка, что в E1–E3 (`lag@inspector` ≤ 100 за окно, не 3008); `actuation_missed_items` и `actuation_late_fires` — числа в отчёте.
**Out of scope:** per-object tracking вместо фронта pass→reject; реальный привод (Modbus/GPIO) — `fire` пишет только счётчики, вердикт пишется на решении.

### Task 5.3 — Запись о разрыве: один item на потерю любой длины
**Level:** Senior+ · **Assignee:** teamlead (код), tester, reviewer · **Layer:** framework
**Редакция 2** (ревью спек, 5 блокеров + minor, решения лида 2026-10-02).
**Goal:** потеря N кадров уезжает одной записью `not_inspected` с `count` и списком `trace_ids`, а не N сообщениями; сообщений ⌈N/1500⌉ на разрыв; поимённость по `trace_id` сохраняется.
**Files:** `multiprocess_framework/modules/router_module/middleware/not_inspected_marker.py` (`build_gap`, `GAP_CHUNK`; `build_marker` = сегодняшние ключи + `"count": 1`; `is_marker`, `MARKER_REASONS` без изменений), `multiprocess_framework/modules/process_module/generic/data_receiver.py` (IPC-запись — отдельной коллекцией; слияние маркер-коллекций в хвост), `multiprocess_framework/modules/process_module/generic/pipeline_executor.py` (`_forward_markers` и post-chain stale через `build_gap`; `not_inspected_handled += Σ count` входа), `multiprocess_framework/modules/router_module/middleware/frame_shm_middleware.py` (дверь = `build_gap([build_marker(...)])[0]`), `multiprocess_framework/DECISIONS.md` (поправка ADR-174 п. 4–7; `scripts.sync` не запускать — лид на слиянии), тесты `multiprocess_framework/modules/process_module/tests/test_t47d2_*.py`, `multiprocess_framework/modules/router_module/tests/test_t47d1_marker_contract.py`, `test_t47d3_*.py`, новый `multiprocess_framework/modules/process_module/tests/test_t53_gap_record_reaches_chain.py`.
**Пересечение файлов:** с 5.2 и 5.4 — ноль. `Plugins/control/robot_control/**` 5.3 не трогает.
**Дизайн (по решениям 5.1, [`docs/reviews/2026-10-02_phase5-design-cto.md`](../../docs/reviews/2026-10-02_phase5-design-cto.md)):**
- Склейка в приёмнике — как есть (`_MarkerBatch`, `_coalesce_markers`, тесты не меняются). Плюс: в `on_items_ready` маркер-коллекция сливается в хвост очереди, если `pending[-1]` — `_MarkerBatch` (под `chain.mutex`, в обоих режимах). Причина: `_bound_lag` на маркер-коллекции не срабатывает (`data_receiver.py:263`), поток маркеров без кадров заполняет `chain_queue` по одному (решения 3(б), 7).
- Схлопывание в записи — в исполнителе, в `_forward_markers`, ДО `_execute_chain`: `records = build_gap(items)` → цепочка по записям → `not_inspected_handled += Σ count` (по входу) → `_send_results`. Post-chain stale (`_run_batch`, ветка `not valid` под `every`) — тоже через `build_gap` (решения 3, 4).
- **`build_gap(items) -> list[dict]`**, `GAP_CHUNK = 1500`. Пустой вход → `ValueError` (решение 2).
  - Запись `count > 1`: ровно ключи `inspection_status`, `overflow_marker: True`, `count`, `trace_ids`, `first_capture_ts`, `last_capture_ts`, `reasons: {reason: n}`, `sources: {source: n}`, плюс `source` — если источник один, `camera_id` — если ключ есть у ВСЕХ входов и значение одно (иначе ключа нет). Ключей `reason`, `trace_id`, `capture_ts`, `frame_id` в ней НЕТ.
  - Запись `count == 1` = маркер `build_marker` (сегодняшние ключи + `count: 1`) плюс `trace_ids: [t]`, `first_capture_ts = last_capture_ts = capture_ts`, `reasons: {reason: 1}`, `sources: {source: 1}`.
  - `first_capture_ts` = min, `last_capture_ts` = max по не-`None` значениям; все `None` → `None` (`build_marker` пишет `meta.get("capture_ts")`, бывает `None`).
  - Вход может быть записью: поля суммируются, `trace_ids` склеиваются в порядке входа. `len(trace_ids) == count`.
  - **Чанк:** вход неделим (у записи `reasons` по id не делится); входы упаковываются жадно, пока сумма `count` ≤ `GAP_CHUNK`; следующий вход открывает новую запись.
- `is_marker` — без изменений (две пары ключей); читатели берут `count = item.get("count", 1)`.
- Дверь: `build_gap([build_marker(...)])[0]` — запись `count=1`. Fan-out: одно рождение, N доставок одного dict (решение 5).
- Формула ADR-174 п. 5 — в items; `handled` считает Σ count входа.
- Память: ≈35 Б на `trace_id` в записи против ≈255 Б на маркер-сообщение; `trace_ids` растёт O(N), сообщений ⌈N/1500⌉.
**Steps:** 1. tester до кода. 2. `build_gap` + `_forward_markers`. 3. Дверь: `count=1`. 4. Приёмник: запись сверху, слияние в хвост. 5. Инъекции (≥ 9: `count` не суммируется; `trace_ids` теряет порядок; `first/last` перепутаны; `None` в `capture_ts` роняет min/max; запись сверху идёт в коллектор; дверь рожает две записи при fan-out; `handled` считает записи, а не items; `reasons` не агрегируются; чанк режет запись-вход). 6. Ревью. 7. Стенд-гейт.
**Намеренно меняемые тесты:** 4.7d-2 кейсы «stale pre-chain батч из 3 → `send_fn` получила 3 сообщения-маркера» → 1 сообщение, `count=3`, `trace_ids=[t1,t2,t3]`; «post-chain 2→1: 2 маркера» → 1 запись `count=2`; «маркер-коллекция, плагин без `accepts_markers`: `send_fn` по сообщению на цель, `data` равен маркеру» → `data` равен записи; `test_t47d1_marker_contract.py` — литерал `build_marker` дополняется `"count": 1`. Кейс 4.7d-4 `test_t47d4_marker_policy.py:377` (`robot_control` 1 раз) НЕ меняется: с одним маркером `robot.calls == 1` верно и так; это файл 5.2.
**Acceptance criteria:**
- [ ] `build_gap([m(t1,lag), m(t2,lag), m(t3,stale_restore)])` (один узел-источник, у всех один `camera_id`) равен ровно `[{"inspection_status": "not_inspected", "overflow_marker": True, "count": 3, "trace_ids": ["t1","t2","t3"], "first_capture_ts": ts1, "last_capture_ts": ts3, "reasons": {"lag": 2, "stale_restore": 1}, "sources": {"<узел>": 3}, "source": "<узел>", "camera_id": "<cam>"}]`. Ключей `reason`, `trace_id`, `capture_ts`, `frame_id` нет.
- [ ] `build_gap([m])` равен литералу записи `count=1` целиком (ключи `build_marker` + `count: 1` + `trace_ids`, `first/last_capture_ts`, `reasons`, `sources`).
- [ ] `capture_ts`: `[ts1, None, ts3]` → `first = ts1`, `last = ts3`; все `None` → оба `None`.
- [ ] Чанк: `build_gap([rec(1500), m])` → 2 записи, `count` 1500 и 1; `build_gap` на 3008 маркерах → 3 записи (1500/1500/8), Σ count = 3008, `len(trace_ids) == count` у каждой.
- [ ] Исполнитель, `_MarkerBatch` из 1078 маркеров, 2 `chain_targets`: `send_fn` вызвана ровно 2 раза, в обоих `data["count"] == 1078`, `len(trace_ids) == 1078`, порядок = порядок замены; `not_inspected_handled` +1078.
- [ ] Дверь (`every`, fan-out 2): одна запись `count=1`, `not_inspected_door == 1`, `door_drops == 1`.
- [ ] Приёмник соседа: IPC-запись `count=1078` → отдельная коллекция, коллектор не вызван; spy-плагин с `accepts_markers=True` (новый файл `test_t53_gap_record_reaches_chain.py`) вызван ровно 1 раз; `data` дошёл с `count`, `trace_ids`, `first_capture_ts`, `last_capture_ts`, `reasons`, `sources` без изменений. (`total_not_inspected += count` проверяется в 5.2 и на точке слияния.)
- [ ] Размер pickle записи с 1078 `trace_ids` (32-символьных) — число в отчёте; ≤ 64 КиБ (CTO замерил прототипом 38 053 Б).
- [ ] 1000 IPC-записей в узел с паузой исполнителя (`latest` и `every`): `chain_queue.qsize() ≤ 2`, `overload_events == 0`, все 1000 приняты за ≤ 2 с.
- [ ] Формула ADR-174 п. 5 в items (`every`), юнит-риг: источник → processor (`every`, исполнитель на паузе 2 с) → inspector, 300 кадров через фейковый `send_fn`: `Σ born(processor) > 0` (сторож от пустого рига) и `handled − own == Σ born(processor)`, разность 0. (Живая сверка 198/250/295 из ревью 4.7d-2a — на стенд-гейте, не здесь.)
- [ ] **Стенд-гейт (P10 заново):** пауза исполнителя processor 10 с под `every`: у processor `errors_delivery_failed` Δ = 0 и `queue_data_evicted` Δ = 0 за дренаж; inspector/renderer `handled − own = Σ born(processor)` с разностью 0; ΔRSS processor ≤ 1 МиБ; дренаж ≤ 0.1 с; 2 прогона.
**Out of scope:** `robot_control` (принимает `count` в 5.2); маркер у писателя; старение записей (5.2, решение 8 в 5.1).

### Task 5.4 — Preroll: источники стартуют после готовности потребителей
**Level:** Middle+ (Sonnet) · **Assignee:** developer, tester, reviewer · **Layer:** framework
**Редакция 3** (ревью спек: итерация 1 — 2 блокера, итерация 2 — 1 блокер (ADR-116 в чужом файле), внесён заменой ревьюера).
**Goal:** на старте ни один кадр не вытесняется из очереди ещё не читающего соседа: `SourceProducer.produce()` начинается по событию готовности системы, которое уже есть у PM.
**Files:** `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py` (`self._system_ready_event` → аргумент `ProcessRegistry(...)` рядом с `system_stop_event`, `:148-155`), `multiprocess_framework/modules/process_manager_module/core/process_registry.py` (ctor + `Process(..., kwargs={"system_ready_event": ..., "parent_pid": ...})` у `:246-247` — наследованием, НЕ в bundle custom), `multiprocess_framework/modules/process_manager_module/runner/process_runner.py` (`run_process_function(..., *, system_ready_event=None)` — keyword-only), `multiprocess_framework/modules/process_module/generic/generic_process.py` (передача события и `log_warning` в `SourceProducer`, `:336`), `multiprocess_framework/modules/process_module/generic/source_producer.py` (ожидание до первого `produce()`), `multiprocess_framework/modules/process_manager_module/DECISIONS.md` (новый `ADR-PMM-034`: проводка `system_ready_event` наследованием; ADR-116 лежит в общем `multiprocess_framework/DECISIONS.md` — файле 5.3, строку-ссылку в него вписывает лид на слиянии), тесты `process_module/tests/test_source_producer*.py`, `process_manager_module/tests/`.
**Пересечение файлов:** с 5.2 и 5.3 — ноль (`generic_process.py` — только 5.4).
**Дизайн (по факту 5.0(б), `docs/audits/2026-10-02_transport-facts.md`):**
- Событие до детей не доходит: `process_registry.py:189` вырезает `system_ready_event` из bundle (mp.Event на Windows-spawn пиклится только наследованием).
- **Проводка:** PM → `ProcessRegistry` (ctor) → `Process(kwargs={"system_ready_event": ...})` → `run_process_function(*, system_ready_event)` → атрибут экземпляра `_sources_ready_event` (ставит runner до `run()`) → `GenericProcess` → `SourceProducer(ready_event=..., log_warning=...)`.
- **Не позиционно.** Шестой позиционный параметр `run_process_function` — `new_session` (`process_runner.py:252`); событие в `args=(...)` молча попало бы туда. Поэтому — `kwargs` рядом с `parent_pid` и keyword-only параметр.
- **Не `attach_ready_event`.** Этим методом (`process_module.py:1066`) PM объявляет СВОЮ готовность (`process_manager_process.py:325`); ребёнок, получивший событие через него, взводил бы его сам. Отдельный атрибут `_sources_ready_event` только читается.
- **Ожидание в `SourceProducer`:** в своём потоке перед первым `produce()`: `ready_event.wait` кусками ≤ 0.05 с; между кусками — проверка `stop_event` и срока. Срок — константа `DEFAULT_PREROLL_TIMEOUT_S = 10.0` в `source_producer.py` (ключ конфига — вне объёма). Истёк → `log_warning` с текстом `preroll` и старт. Стоп во время ожидания → поток выходит без `produce()` и без WARNING.
- **Колбэк предупреждения:** у `SourceProducer` есть только `log_info` / `log_error` / `log_debug` (`source_producer.py:54-56`) — добавляется `log_warning: Callable[[str], None] | None = None`; `None` → строка не пишется (юниты, старые вызовы). `GenericProcess` передаёт свой `log_warning` всегда.
- `ready_event is None` (юниты, старые вызовы) → без ожидания, поведение прежнее. Рестарт процесса — событие уже взведено, ожидания нет. Взводит событие только PM (`_announce_ready`) после boot-барьера `_wait_boot_ready`.
- **Риск взаимной блокировки:** если `_wait_boot_ready` (`process_manager_process.py:4130`) ждёт готовности ребёнка, которая требует кадра, старт упрётся в 10 с. Исполнитель проверяет это до кода (шаг 2) и пишет вывод в отчёт.
- **Риск «готовность ≠ темп»:** ленивая загрузка модели в первом `process()` даст вытеснения уже после `ready`. Стенд-гейт покажет; лечение — вне задачи.
**Steps:** 1. tester до кода. 2. Проверка `_wait_boot_ready` на зависимость от кадров (вывод в отчёт; есть зависимость → ESCALATION -> teamlead до кода). 3. Проводка + ожидание. 4. Инъекции (событие не ждётся; ожидание не видит `stop_event`; таймаут бесконечный; событие передано позиционно; ребёнок взводит событие сам; событие взводится до регистрации очередей). 5. Ревью. 6. Стенд-гейт.
**Намеренно меняемые тесты:** тесты `SourceProducer`, которые ждут первый кадр сразу после `start()` без события, получают взведённое событие в фикстуре (или `ready_event=None`).
**Acceptance criteria:**
- [ ] `SourceProducer` с невзведённым событием: 0 кадров за 200 мс; событие взведено → первый кадр ≤ 50 мс после; срок 0.2 с без события → старт и ровно одна строка через `log_warning`, текст содержит `preroll`.
- [ ] Стоп во время preroll: поток выходит ≤ 0.1 с после `stop_event.set()`, `produce()` не вызван, `log_warning` не вызван.
- [ ] Настоящий spawn: ребёнок, запущенный через `ProcessRegistry`, получает тот же Event (взвести в родителе → ребёнок видит `is_set()`); до `set()` — 0 кадров, после — кадры идут.
- [ ] Ребёнок дошёл до готовности, событие НЕ взведено, пока его не взведёт PM (ни один ребёнок не зовёт `set()`).
- [ ] `run_process_function` с событием в позиционном `args` недопустим: параметр keyword-only (вызов позиционно → `TypeError`).
- [ ] **Стенд-гейт:** `stand.yaml`, 3 прогона. `s0` — кумулятивный снимок через 10 с после ready (старт + 10 с установившегося режима). `queue_data_evicted` в `s0` = 0 у всех процессов (было 24–41); `frame_stale_drops` в `s0` = 0 у процессов под `every`; у процессов под `latest` — число в отчёте (**предложение лида 2026-10-03 после замера, ждёт владельца:** у storage под `latest` 5–9 за 10 с установившегося режима — это политика `latest`, а не старт; исходная буква «у всех» на 978377d7d красная); время до первого кадра камеры — число; время старта системы — число рядом с прежним (7.4 с у `base.yaml` в 5.0(г) как ориентир).
- [ ] `multi_camera.yaml` — то же, обе камеры. **После 5.9a** (сегодня рецепт не проходит валидацию).
**Out of scope:** рестарт одного процесса (повторный preroll — отдельно, если стенд рестарта покажет вытеснения); ключ конфига для срока preroll.

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

**Поставка (ветка `fix/t55-green-main`, 2026-10-02) — расхождения с буквой спеки, принятые лидом:**
- Снимки — `.txt` (один ключ на строку, `snapshots/hot_rebuild_framework_keys.txt`, `snapshots/catalog_register_fields.txt`), не `*.snapshot.json`: падение называет появившиеся/пропавшие ключи; команды пересъёмки нет.
- Файлы сверх `Files:` (цель «0 failed» их потребовала): `data_schema_module/core/field_meta.py`, `Services/code_reader/core/sdk_reader.py` (голый stdlib-логгер), `recipe/tests/test_yaml_io.py`, `frontend_module/tests/test_remote_frame_source.py` (skipif win32 с причиной), `shared_resources_module/tests/test_reader_gone_hazards.py` (PYTHONPATH от `__file__`), `tests/test_declarations_leak_session_catalogue_guard.py` + `tests/_declarations_catalogue_guard.py` (каталог метрик 5 → 10), `router_module/DECISIONS.md` (ADR-RTR-012: Windows), `.claude/plugins/dev/commands/ship.md` + зеркало (шаг 4).
- Объяснение HOL-теста — в комментарии тела теста, не в докстринге.
- `make` на Windows-машине нет: шаг 4 сделан правкой fallback `/dev:ship` (прогнать каждую составляющую `gate`, включая `run_framework_tests.py`; красный гейт = отказ). Проверка «`/dev:ship` отказывает при красном gate инъекцией» требует запуска `/dev:ship` владельцем (`disable-model-invocation: true`) — лидом не выполнена.
- Коммиты: `8cd6a60b2` диагноз, `c8a1853f4` код, `b2504d571` + `6f5468af1` тесты, `f1682779f` правки ревью, `286266608` ship, `39718c6f9` OPEN_QUESTIONS. Ревью: APPROVED_WITH_NITS (свежий reviewer). Инъекции 10/10 по предсказанию.

### Task 5.5c — Весь `make gate` зелёный (решение владельца 2026-10-02)
**Level:** Middle+ (Sonnet) / Senior для `docs_verify` · **Assignee:** developer + teamlead, tester по механизмам, reviewer · **Layer:** mixed
**Goal:** правило `/dev:ship` «красный гейт отказывает» начинает действовать: на main зелёные все пять частей `gate`, а не только `test-fw`.
**Почему отдельно:** 5.5 влита в main (`68fb2e6df`) без этого — 5.5 не вносит новых красных, а красное лежало на main до неё. Замеры: [`docs/reviews/2026-10-02_task-5.5-gate.md`](../../docs/reviews/2026-10-02_task-5.5-gate.md).
**Объём на `003264912`/`68fb2e6df`:** ruff 7 ошибок (5 автофикс); pyright 1 error; bandit rc=1 (Medium 16, Low 3, High 0) — решить, какой порог считается красным, и записать в Makefile; корневой pytest 39 падений: `scripts/docs_verify/tests/test_docs_check.py` 29, `scripts/validate_commit` 2 (+2 зависят от текущей ветки git — тест обязан изолировать ветку), `observability/tests/test_empty_hint_and_lag.py` 2, `Services/line_sim` 2, `Services/tests/test_env_brand.py` 1, `Plugins/tests/test_no_silent_swallows.py` 1, `camera_service/test_stream_source_acceptance.py` 1, `backend_ctl/tests/test_probe_acceptance_profiles.py` 1; `examples/minimal_app/tests/test_ci_smoke.py` — ERROR в teardown только в полном наборе (флак).
**Ветка:** `fix/t55c-gate-green` от main `68fb2e6df`, свой worktree. Сливается в main **раньше** `feat/transport-f5`; ветка фазы потом вливает main и прогоняет корневой pytest заново (её новые тесты войдут в гейт тогда).
**Files (ред. 2, ревью спек волны 3):** упавшие тестовые файлы из «Объёма» выше; `scripts/docs_verify/**`; `scripts/validate_commit/**`; `Makefile` (только цель `security`); `pyproject.toml` (только секция `[tool.bandit]`, строки 330+); исходник под каждое падение — по диагнозу. **Стоп-правило:** если диагноз ведёт в файл из `Files:` задач 5.6 или 5.9a (`process_module/heartbeat/telemetry.py`, `router_module/core/router_manager.py`, `process_module/plugins/port.py`, `process_manager_module/topology/blueprint.py`, `backend/topology/*.yaml`, секция `testpaths` в `pyproject.toml`) или в `Plugins/control/robot_control/plugin.py` — правку не делать, писать `ESCALATION -> lead` с диагнозом.
**Решение лида по bandit (ред. 2):** красный порог — Medium и выше: цель `security` вызывает bandit с `-ll` (`--severity-level medium`). Все 16 Medium разобрать: правка кода или `# nosec Bxxx — <причина одной фразой>` на строке. Low (3) — в отчёте, порогом не являются. Почему не `-lll`: при `-lll` 16 Medium проходят молча, и порог ничего не охраняет.
**Acceptance criteria:**
- [x] Каждое падение — починено или `xfail(strict=True, reason=<ссылка на OPEN_QUESTIONS.md или issue>)`; skip без причины запрещён. Строк `xfail(` в репозитории после задачи ≤ 5 всего (на `68fb2e6df` их 3): `git grep -n "xfail(" -- "*.py" | wc -l` до и после — оба числа в отчёте. — 3 → 4 (`7f52d7f9b`, camera_service win32 strict).
- [~] Пять частей `gate` — exit 0 на HEAD ветки 5.5c, трижды для pytest-частей. Команды (Windows, без `make`): `ruff check .`; `pyright multiprocess_framework multiprocess_prototype`; `bandit -r multiprocess_framework multiprocess_prototype Services -c pyproject.toml -q -ll` (пути — как в цели `security` Makefile); `pytest -q` из корня; `python scripts/run_framework_tests.py`. После слияния в main — повтор на main одним прогоном. — **частично**: на `f0c118f0b` ruff/pyright/bandit exit 0; корневой pytest 10609/0 ×3; `run_framework_tests` 10750/0 ×2 и одно аварийное завершение интерпретатора вне 5.5c (OPEN_QUESTIONS §5.5c п.8, дамп `docs/reviews/2026-10-03_task-5.5c-gate3/`). Влита в main `68a8ba279` с этим названным дефектом (решение лида); повтор на main — ждёт окна соседа f0.
- [x] `bandit ... -ll` на HEAD: Medium = 0 незакрытых; число строк `# nosec` — в отчёте. — `# nosec` в *.py 127 → 143, Low 3.
- [x] `test_validate_commit.py` не зависит от текущей ветки: `git switch --detach HEAD && pytest scripts/validate_commit/tests -q` → 0 failed; то же в worktree `t5-lead` (ветка `feat/transport-f5`, у неё есть `plans/transport-single-policy/`) → 0 failed. — инъекция снятия изоляции: 3 красных и в t5-lead, и в t55c-impl (ревью р1).
- [x] `examples/minimal_app/tests/test_ci_smoke.py`: ERROR в teardown — диагноз (сосед по набору назван) и правка или xfail по правилу выше; полный корневой набор ×3 без ERROR. — корневой ×3 на `f0c118f0b` без ERROR.
**Out of scope:** pyright warnings (321), повышение строгости; правки в файлах задач 5.6 / 5.9a и в `robot_control` (см. стоп-правило).

---

### Task 5.6 — Стенд-гейт как скрипт и экспорт счётчиков тракта в телеметрию
**Level:** Senior+ · **Assignee:** teamlead (скрипт + экспорт), tester (слепые тесты скрипта и набора ключей), reviewer · **Layer:** scripts + framework
**Goal:** одна команда `python -m scripts.stand_gate` поднимает стенд по протоколу замка, снимает счётчики, проверяет пороги и выходит с кодом 1 при нарушении; счётчики 4.7c/d видны в дереве телеметрии, а не только в `introspect.status`.
**Редакция 2 (2026-10-03, ревью спек волны 3 + стенд волны 2):** формат входа скрипта = JSON `stand5.py` из [`docs/reviews/2026-10-03_phase5-stand-w2/`](../../docs/reviews/2026-10-03_phase5-stand-w2/) (там же схема в `README.md`, сырьё `raw/*.json`, анализатор `analyze5.py`). Все пороги — в единицах (Σ `count`), не в строках журнала.
**CLI (литерал):** `python -m scripts.stand_gate [--profile quick] [--runs N] [--from-json PATH ...] [--no-throughput-gate] [--out-dir reports/stand]`. `--profile quick` = три кейса на `scripts/capacity_bench/recipes/stand.yaml`, у всех 1080p@100, `extras.overflow: every` на `processor` и `inspector`, окно 30 с, прогрев 10 с: `E` (`transit_ms=0`), `D100` (`transit_ms=100`), `P10` (`transit_ms=0`, пауза воркера `pipeline_executor` у processor на 10 с через 5 с после начала окна). `--from-json` — не поднимать стенд, проверить готовые JSON (так работают тесты). Замок (ред. 4): общий файл протокола `<родитель основного дерева>/stand.lock` (путь — от `git rev-parse --git-common-dir`, не от worktree; сегодня `D:\PROJECT_INNOTECH\Inspector_vision\stand.lock`), формат `сессия | время | режим | SHA | порты`. Живой режим требует `--lock-token <сессия>`: нет токена, нет файла, токена нет в файле или режим не `measure` → код 2. Снимок процесса с ключом `error` на `s0`/`s2`/`pause.after`, заказанная, но не состоявшаяся пауза (нет `pause` или есть `pause_error`) → код 2. Отчёт — `reports/stand/<host>_<дата>_<ЧЧММСС>.md`. Коды выхода: **0** — все пороги зелёные; **1** — нарушен хотя бы один порог (в stdout строка `FAIL <имя порога>: <факт> vs <порог>`); **2** — сбой прогона (стенд не поднялся, в JSON нет обязательного ключа, замок занят).
**Files:** новый пакет `scripts/stand_gate/{__init__,__main__,run,analyze,thresholds,report}.py` (перенос `stand5.py`/`analyze5.py`, переиспользование `scripts/capacity_bench/run_case.py`, `cpu_probe.py`; `recipe.py` правится, если `render_recipe` получает `overflow`/`transit_ms`), `scripts/stand_gate/tests/` (+ `fixtures/`), `scripts/stand_gate/README.md`; `multiprocess_framework/modules/process_module/heartbeat/telemetry.py` (`build_router_shm_telemetry` и `build_worker_telemetry`), `multiprocess_framework/modules/process_module/heartbeat/process_heartbeat.py` (только если публикатор не передаёт новые листья), `multiprocess_framework/modules/router_module/core/router_manager.py` (`get_shm_stats`: `deferred_closes`, `errors_delivery_failed`), `multiprocess_framework/modules/router_module/middleware/frame_shm_middleware.py` (выдать `deferred_closes` из `ShmFrameReader`, `shm_frame_reader.py:83`); `pyproject.toml` (только `testpaths`). `backend_ctl` — без новых инструментов.
**Steps:** 1. Экспорт счётчиков — отдельный коммит. 2. Скрипт: прогон → JSON → пороги → `reports/stand/<host>_<дата>.md`. 3. Первый прогон `--profile quick --runs 3` — лид, закрывает стенд-гейты 5.2/5.3/5.4.
**Намеренно меняемые тесты:** тесты `heartbeat/telemetry.py`, пинящие набор листьев `state.shm`; `test_shm_stats_narrow` (ключи `get_shm_stats`); `test_cycle_metrics.py` не меняется.
**Определения (литералы для `analyze.py` и тестов; имена — ключи JSON `stand5.py`):** для процесса P на снимке S: `born(P) = Σ_workers(not_inspected_lag + not_inspected_stale_restore + not_inspected_stale_exec) + rs.not_inspected_door`; `drops(P) = Σ_workers lag_dropped_items + rs.frame_stale_drops + rs.frame_torn_reads + rs.frame_restore_failures`; `own_in(P) = Σ_workers(not_inspected_lag + not_inspected_stale_restore + not_inspected_stale_exec)`; `handled(P) = Σ_workers not_inspected_handled`. Кадры камеры `F` = `Σ_workers cycles` у `camera_0` в снимке `camera_before_pause` (после `worker.pause_all` камера на `introspect` не отвечает — замер 2026-10-03: 0 циклов в снимке после паузы). Единицы решателя: `I = total_inspected`, `N = total_not_inspected` из `rc_s2` (`get_stats` у inspector). Ответ `rc_s2` обёрнут драйвером — искать вложенный dict с ключом `total_inspected`. Вердиктов `V = journal.verdicts`, дублей `= journal.dup` (при `--from-json` журнал берётся из JSON: `case_dir` временный; живой прогон считает `journal` по `messages.log`). Кейс определяется по JSON: есть ключ `pause` → `P10`; иначе `transit_ms > 0` → `D100`; иначе `E`.
**Acceptance criteria (пороги — литералы в `thresholds.py`; OWNER-8):**
- [ ] (tester) Формула по процессу: для processor и inspector `born(P) − drops(P) == 0` на `s2`. Соседи processor (inspector, renderer): `handled(N) − own_in(N) − born(processor) == 0` на `s2`.
- [ ] (tester) `rs.queue_data_evicted == 0` и `rs.errors_delivery_failed == 0` у всех процессов на `s0` и `s2`; в кейсе `P10` — то же на `pause.after`.
- [ ] (tester) Учёт решателя: `0 ≤ (I + N) − F ≤ 0.005 × F` (верхний допуск — кадры, ушедшие между снимком камеры и её паузой). Замер 2026-10-03: на 978377d7d `+8…+10`, на 003264912 `−66` и `−20` (настоящие потери). Дублей `trace_id` в журнале — 0. Журнал = только файлы `messages.log`; `observability.db` текстом не читать (бинарный SQLite, текст лежит повторно — замер 2026-10-03: ложных дублей 95–462 на прогон).
- [ ] (tester) `stale_restore`: `Σ_P Σ_workers not_inspected_stale_restore ≤ 0.001 × F` на `s2`. Lag processor: `Σ_workers lag_dropped_items ≤ 0.01 × F`; при `--no-throughput-gate` — число в отчёте, порог не проверяется (до 5.8).
- [ ] (tester) Вердикты при `transit_ms > 0` (кейс `D100`): `V ≥ 0.9 × (F − N)`. Там же `lag@inspector` за окно: `Σ_workers not_inspected_lag(inspector, s1) − то же на s0 ≤ 100` (гейт 5.2).
- [ ] (tester) Кейс `P10`: `(pause.rss1 − pause.rss0) ≤ 1 МиБ` (гейт 5.3). В отчёте числами, без порога: `actuation_fired_items/missed_items/late_fires/unscheduled_items` из `rc_s2` (5.2), `start_s` и `first_frame_after_ready_s` (5.4).
- [ ] (tester) Старт (`s0`, кумулятивно = ready + 10 с): `rs.frame_stale_drops == 0` у процессов под `every`; у процессов под `latest` — число в отчёте без порога (решение владельца по 5.4 — ждёт, см. 5.4).
- [ ] (tester) Дренаж `P10` (ред. 4, ревью кода 5.6: сигнал «очередь вернулась к медиане» вырожден — при работающей 5.3 `chain_queue.size` во время паузы = 3, как в установившемся режиме): `drain_s` = время от ОТПРАВКИ `worker.start` до момента, когда `cycles` исполнителя processor вырос на `pause.backlog + 1`, где `pause.backlog = chain_queue.size` в снимке `pause_mid`; опрос одним вызовом `introspect_status(processor)` с шагом ≤ 20 мс; в JSON — `pause.drain_s` и `pause.drain_poll_period_s`. Ещё пишется `pause.drain_lower_s` — время до НАЧАЛА последнего опроса, на котором цель ещё не достигнута; это число в отчёте без порога (ред. 5: правило «нижняя граница → FAIL» снято — маркеры не пишут `cycles`, бэклог паузы при 5.3 уходит маркерами, поэтому нижняя граница не доказывает превышение; раунд 2 ревью 5.6). Вердикт — только по верхней границе `drain_s` (ложного PASS не даёт: `chain_queue` — FIFO, `cycles` ≤ числу забранных элементов). Порог `pause.drain_s ≤ 0.1`; если `pause.drain_poll_period_s > 0.1` — вердикт `NOT_MEASURED` (код 1), а не зелёный. Замер 2026-10-03 старым способом (снимок из трёх команд): первый опрос через 0.17 с уже показал пустую очередь — порог 0.1 с этим способом не доказуем.
- [ ] (tester) Фикстуры: `scripts/stand_gate/tests/fixtures/green_D100.json` и `red_E0_old.json` — копии `docs/reviews/2026-10-03_phase5-stand-w2/fixtures/` (это `raw/D100_3.json` и `raw/E0_003264912_1.json` с ключом `journal`, пересчитанным по `messages.log`). Третья фикстура — `green_P10.json` (**синтетика**: `raw/P10_2.json` + `pause.drain_poll_period_s: 0.02`, `pause.drain_s: 0.05`, названа синтетикой в README). `green_D100.json` и `green_P10.json` → код 0 с `--no-throughput-gate`; мутации порогов P10 (`pause.after.*`, дренаж, ΔRSS) — от `green_P10.json`; `red_E0_old.json` → код 1, в stdout `FAIL` по `queue_data_evicted` и по учёту решателя. На каждый порог выше — тест: мутация одного ключа зелёной фикстуры → код 1 и имя порога в stdout. JSON без ключа `s2` → код 2.
- [ ] (tester) Телеметрия, литеральный набор путей. P — `processor` и `inspector` рецепта под `every`. У camera и у процессов под `latest` листья `not_inspected_*` и `shm.not_inspected_door` отсутствуют (их нет и в `get_shm_stats`/воркерах); `ipc_queue_depth` отсутствует до первого замера глубины. Пути: `processes.<P>.state.shm.door_drops`, `…state.shm.not_inspected_door`, `…state.shm.deferred_closes`, `…state.shm.errors_delivery_failed`; суммы по воркерам: `processes.<P>.state.lag_dropped_items`, `…state.not_inspected_lag`, `…state.not_inspected_stale_restore`, `…state.not_inspected_stale_exec`, `…state.not_inspected_handled`, `…state.ipc_queue_depth` (gauge: размер data-очереди на тике публикации).
- [ ] (лид, стенд) `--profile quick --runs 3` на HEAD фазы отработал: отчёт в `reports/stand/`, каждый FAIL назван порогом и фактом. «Три зелёных подряд» — гейт выхода фазы, не приёмка 5.6. 20 стопов: число строк отпуска фидеров (подстроку лид фиксирует при реализации) — в отчёте, без порога.
**Риски (механизм):** камера после `worker.pause_all` не отвечает на `introspect` (подтверждено 2026-10-03) — всё, что нужно от камеры, снимается до паузы; два бэкенда конфликтуют через PID-реестр и SHM-cleanup — скрипт проверяет `stand.lock` и выходит с кодом 2, если замок чужой; счёт lag-маркеров шумит от прогона к прогону (24…1608 на одном дереве) — порог lag до 5.8 выключен; processor под `every` дал до 7 `frame_stale_drops` в `s0` (P10_1, причина открыта) — такой прогон по порогу старта красный, а бимодальность цикла processor (плохой режим: 63–73 кадра/с при входе 95, на обоих деревьях — investigator 2026-10-03) двигает lag и stale — гейт выхода фазы зависит от обоих.
**Rejected:** `ipc_queue_depth` как максимум за окно (аудит 5.0(в)) — нужен новый счётчик в `data_receiver.py`; отложено до 5.8, где он понадобится для пула исполнителя. Матрица `--profile full` (4.3) — вынесена из 5.6, вернуть в 5.8.
**Out of scope:** выводы о мощности (4.8b); GUI (5.11); новые MCP-инструменты backend_ctl; `--profile full`.

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

### Task 5.8 — Пропускная способность: storage первым, пул по замеру → [`task-5.8.md`](task-5.8.md)

Ред. 2 (2026-10-03, ревью спеки стадии 0 + решение владельца «storage первым»): 5.8s (профиль `throughput` стенд-гейта) ∥ 5.8a (storage: транзакция на пакет, сброс вне исполнителя) → базовый замер лида → 5.8b (пул `WorkerPoolExecutor` — по правилу решения). Ред. 1 (`WorkerPoolDispatcher`) снята.

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
**DESIGN (ред. 2, ревью спек волны 3, решения лида):**
1. **Доступность — по ИМЕНИ ключа, как в рантайме.** Рантайм — dict, ключ живёт до перезаписи. Доступное множество для узла i процесса = имена `wired_inputs` процесса (имена target-портов его входящих проводов) ∪ имена выходных портов узлов 0…i−1. Вход узла покрыт, если его имя есть в множестве и порт совместим по `are_ports_compatible` с последним производителем этого имени; иначе — если вход `optional`; иначе ошибка. Почему не по dtype: при сравнении только dtype инъекция «у источника убран `frame`» осталась бы зелёной, если выше есть другой `image/bgr`.
2. **Одна функция для двух мест:** `available_keys(chain, *, wired_inputs: Iterable[str] = ()) -> dict[str, Port]` в `port.py`; `validate_chain(plugins_with_ports, *, wired_inputs: Iterable[str] = ())` (новый keyword-only параметр, по умолчанию `()` — старые вызовы без изменений) и `_is_covered_by_auto_wiring` в `blueprint.py` зовут её.
3. **compositor в `multi_camera.yaml` получает явный `collector: {mode: fanin}`.** Причина: после проводов от `processor_0` и `processor_1` на обязательный `renderer_compositor.frame` `infer_missing_collectors` выведет join, а два источника с одинаковым тегом `frame` схлопнутся в join с ОДНИМ элементом `inputs` (докстринг `blueprint.py:452-457`, ADR-PMM-017 п.3/4) — это поменяло бы сегодняшний fan-in. Явный collector — штатный escape-hatch, вывод join-коллекторов не меняется.
4. **Два текста ошибки** (ред. 3, итерация 2 ревью спек). (а) Ключа нет в доступном множестве → `Вход '<plugin>.<port>' (<dtype>) не подключен: ключ '<port>' не производит ни провод процесса, ни узел выше по цепочке` (в `validate_chain` без префикса процесса — процесса там нет; `check()` добавляет префикс `<process>.`). (б) Ключ есть, но несовместим с последним производителем → прежний формат без изменений: `"{producer} → {consumer}: вход '{name}' ({dtype} {shape}) несовместим с выходами [...]"` — его требуют `test_port_validate_items.py:79-80` и `test_blueprint_chain_validation.py:115`.
5. **Имя из провода** даёт в доступное множество `Port(name=<имя>, dtype="any")`: dtype провода уже сверён циклом Wire (`blueprint.py:830-836`).
6. **Одна ошибка на один вход:** цикл обязательных входов `blueprint.py:860-871` не повторяет адрес, о котором уже сообщил `validate_chain`.
**Steps:** 1. `available_keys` + `validate_chain(..., wired_inputs=)` + `_is_covered_by_auto_wiring` (коммит фреймворка). 2. `wires:` в `inspection_basic.yaml` и `multi_camera.yaml` (по образцу `inspection_full.yaml:171-198`) + `collector: {mode: fanin}` у compositor. 3. Страж рецептов. 4. Лид — живой старт обоих рецептов.
**Намеренно меняемые тесты:** нет. Если существующий тест краснеет — это находка, стоп и `ESCALATION -> lead`.
**Acceptance criteria:**
- [ ] (tester) `check()` на `multi_camera.yaml` и `inspection_basic.yaml` → `[]`. Точка входа — тот же путь, что у запуска: yaml → `SystemBlueprint` → `BlueprintAssembler.assemble` без `BlueprintInvalid` (`launch.py:712-725`).
- [ ] (tester) Синтетическая цепочка в тесте: узел A выдаёт `mask`, узел B требует `frame`, `wired_inputs=("frame",)` → ошибок 0; та же цепочка с `wired_inputs=()` → ровно одна ошибка, текст содержит `'frame'` и имя узла B. Узел B с `optional` входом `mask` при A без `mask` → ошибок 0. Ключ есть, но несовместим (`gray_source(frame:image/gray) → needs_bgr(frame:image/bgr)`) → одна ошибка, текст содержит `gray_source` и `несовместим`. Вход узла 0 процесса без провода → в `check()` ровно одна ошибка на этот адрес.
- [ ] (tester) В собранном `multi_camera.yaml` collector compositor — `mode == "fanin"`.
- [ ] (tester) Страж `test_topology_recipes_check.py`: все `multiprocess_prototype/backend/topology/*.yaml` (без `TEMPLATE*`, `archive/`, `tests/`) → `check() == []` на HEAD; удаление из `inspection_basic.yaml` (копия в `tmp_path`) ВСЕХ проводов с target `processor.<любой плагин>.frame` → вывод содержит `processor.color_mask.frame`. (Один провод не годится: доступность считается на уровне процесса, второй провод `→ processor.blob_detector.frame` держит ключ `frame` — так ведёт себя и рантайм.)
- [ ] (лид, живой стенд) оба рецепта стартуют и живут 30 с (`sweep50.py` из `docs/audits/2026-10-02_transport-facts/`); у `multi_camera.yaml` compositor выдал > 0 `composite_frame` за 30 с.
**Out of scope:** вывод проводов из `chain_targets` (меняет вывод join-коллекторов, ADR-уровень); `dualcam_synth.yaml`; гейт-рецепт `stand_dualcam.yaml` (это 5.9); правки `Plugins/`.
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

### Task 5.11 — Слоты потерь в карточке процесса → [`task-5.11.md`](task-5.11.md)

Ред. 2 (2026-10-03, ревью спеки стадии 0): слот только при наличии листа телеметрии, единицы фреймворка — согласовано с решением владельца 2026-08-17 (`process_card.py:66-74`).

---

### Task 5.12 — Гейт готовности к линии: критерии приёмки инспекции числами (решение владельца 2026-10-02)
**Level:** Senior (Opus) · **Assignee:** лид (критерии и прогон), cto (вердикт) · **Layer:** docs + scripts
**Goal:** «надёжно» = «прошло гейт с числами», а не «кажется, работает». 100 % стабильности не обещаем; обещаем, что каждый сбой виден и уходит в безопасную сторону (непроверенная бутылка → брак, `not_inspected_action = "reject"` по умолчанию).
**Порядок:** после 5.8 (нужны числа пропускной способности) и 5.6 (скрипт стенд-гейта).
**Входы от владельца (до старта задачи, сейчас пусто):** скорость линии (бутылок/мин); допустимая доля ложного брака из-за потерь (%); окно срабатывания привода (мс); длительность soak (ч, предложение лида — 24).
**Acceptance criteria (пороги — от владельца):**
- [ ] 0 бутылок без вердикта: каждый кадр даёт вердикт или запись `not_inspected`; сверка Σ`born` = Σ`count` + вердикты за весь прогон.
- [ ] Доля ложного брака из-за потерь ≤ порога владельца на скорости линии.
- [ ] Soak ≥ N ч: память процессов без роста (наклон ≈ 0 по телеметрии), 0 падений процессов, 0 зависаний стопа.
- [ ] Задержка срабатывания: доля `late_fires` и `missed` ≤ порога; p99 отклонения выстрела от цели — числом, с учётом шага таймера Windows 15.6 мс.
- [ ] Решение CTO по стрельбе после закрытого окна (OPEN_QUESTIONS 2026-10-02) принято и внесено в код до подключения настоящего привода.
- [ ] Отчёт: таблица «критерий | порог | замер | прогонов» в `docs/audits/`.
**Out of scope:** камера, свет и механика на настоящей линии; несколько камер (5.9, отложена).

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
