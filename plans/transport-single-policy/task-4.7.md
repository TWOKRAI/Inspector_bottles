> Часть плана [`transport-single-policy`](plan.md), Ф4 — [`phase-4-redesign.md`](phase-4-redesign.md) (факты, порядок задач).

### Task 4.7 — Один режим пути кадра
**Level:** Senior+ · **Assignee:** teamlead · **Layer:** framework + prototype + Plugins
**Goal:** одна конфигурация без флагов; сообщение не переживает свой кадр в штатном режиме.

**Дизайн:**
1. **Уникальные имена сегментов всегда:** имя = (слот, владелец, pid, инкарнация) на всех платформах;
   флаг `FW_SHM_OWNER_INCARNATION` удаляется (закрывает `/output_frames_N` на POSIX и вопрос в
   `OPEN_QUESTIONS.md`).
2. **Кэш handles всегда, без LRU-кэпа 8:** ключ — `(owner, slot, idx)`. Пришло новое имя для того же
   ключа → старый handle в «отставку» и закрывается, когда на нём нет живых view (`BufferError` →
   повтор при следующей отставке или teardown, счётчик). Число открытых handles = числу живых имён.
   Флаг `FW_SHM_HANDLE_CACHE` удаляется.
3. **Zero-copy всегда для читателей-пайплайнов** (view только для чтения); copy-out (GUI, мост) — копия
   с проверкой `gen`. Флаг `FW_SHM_ZERO_COPY` удаляется. **`blob_detector` копирует кадр перед
   рисованием** — переезжает сюда из шага 4, потому что zero-copy по умолчанию делает его вход
   read-only.
4. **Глубина кольца из рецепта:** `frame_ring_depth` на процесс, по умолчанию **8** (≈ 60 мс на 100 fps
   плюс 2), без гейта `FW_QOS_PROFILES`; то же для `buffer_slots` в wire.
5. **В полёте меньше кольца:** для процесса, получающего данные от generic-писателей, data-очередь +
   `chain_max_lag_items` ≤ min(глубина кольца писателей) − 2. PM выводит размер data-очереди из
   топологии при сборке (рецепт у него на руках: `assembler.py:139` → `register_process`). Явная
   настройка рецепта, нарушающая неравенство, — ошибка старта с текстом «очередь X больше кольца Y».
6. **Loan заморожен:** `FW_SHM_LOAN_PROTOCOL` остаётся выключенным, в реестре — пометка FROZEN
   («удалить после 4.3, если честный stale = 0 на 60/100 fps; пересмотреть, если stale > 0.1 % при
   глубине 8 и очереди 6»); `requires` на удалённые флаги снимается. В заметке назвать обе утечки
   займа из ревью 4.4: дроп в двери после `commit` и атомарный дроп после уже восстановленных view.

7. **Правило переполнения по потребителю (решение владельца 2026-09-30):** буфер = глубина кольца (из
   рецепта, п. 4) — поглощает пики переменной нагрузки. Что делать, когда буфер всё же переполнен, задаёт
   рецепт процесса: `overflow: latest | every`.
   - `latest` (GUI, превью, мост): берём свежий кадр, старые отбрасываются, счётчик — справочно.
   - `every` (инспекция, **по умолчанию** для процессов с processing-плагинами): каждый потерянный кадр —
     громкое событие. Вниз по цепочке уходит item-маркер с `trace_id`/`capture_ts` и тегом `not_inspected`
     (тег уже есть у breaker'а), чтобы отбраковщик мог сбросить объект, а не пропустить его молча.
     Потерянный кадр в инспекции = непроверенная бутылка.
   - Открытый вопрос для teamlead: где рождается маркер — в месте дропа (очередь / stale в приёмнике /
     дверь) или одним местом в executor'е по разрыву `bseq`.

**Предусловия из ревью 4.4 итерация 2 — сделать ДО включения zero-copy (п. 3):**
- **P-1 (major, было до 4.4):** `Plugins/_shared/fanin/join_inspector_manager.py:93-109` `_merge` теряет
  `_shm_views` второго входа (`elif k not in merged`) → join пропускает чужие пиксели мимо executor'а и двери
  (`sent=['t1'] stale=0`). Склеивать `_shm_views` как list-ключ всегда + тест join+view.
- **P-2 (лишние дропы):** дверь дропает выходы, которые из слота ничего не копируют (dict результата без
  массивов, кадр-копия) — верное решение об отбраковке теряется и завышает stale. Звать
  `_inputs_still_valid`, только если в двери скопировано что-то, смотрящее в чужую память (корень цепочки
  `.base` — не собственный ndarray; критерий по итерации 1 ревью, не `flags.owndata`); тест F2a.
  Репро: scratchpad сессии `77e53bb3…/rev44b/r2.py`, `r2j.py`.

#### Перемер стенда после T1 (2026-09-30)

`a0457ee8`, `seed_stand45.py T1r1/T1r2 1080 100 30`, два прогона. База «до T1» — замер B 4.5 (`dadd9918`, один прогон, цепочка без детекций):

| Поле | До T1 | После T1 (r1 / r2) |
|---|---|---|
| processor Гц | 54–58 | 54.8 / 51.2 |
| processor `color_mask` + `blob_detector`, мс | 8.4 + 6.7 = 15.1 | 11.5 + 1.9 = 13.4 / 11.8 + 1.8 = 13.6 |
| processor `queue_wait_ms` | 1110 | 1098 / 1102 |
| processor `transport_ms` (приём data) | — | 26.6 / 27.0 |
| processor stale / torn за 30 с | 821 / 1247 | 838 / 1065 · 797 / 967 |
| renderer `render_overlay`, мс | 11.6 | **38.9 / 39.5** |
| renderer Гц / `queue_wait_ms` | — | **21.3 / 3053** · 20.4 / 3119 |
| renderer stale / torn | — | 1231 / 313 · 1185 / 313 |
| camera `pacer_late` за прогон | 42 | **456 / 497** |
| ядра всего (снаружи, 16 логических) | — | 4.62 / 4.81 |

Выводы для 4.7/4.8: (1) T1 не сдвинула узкое место processor — очередь по-прежнему ~1.1 с, stale + torn
≈ 1800–1900 за 30 с, то есть проблема 4.7 не в стоимости цепочки. (2) Цепочка на стенде 13.4 мс, а у
`bench_t1` 4.1–4.7 мс: `color_mask` в живом процессе 11.5 мс против 8.4 до T1. Причина не найдена (кандидаты:
`cv_threads`, соседние процессы на тех же ядрах, другой вход после T1). (3) **Новое узкое место — renderer:**
теперь есть что рисовать, `render_overlay` 11.6 → 39 мс, 21 Гц, очередь 3 с. `overflow: latest` (п. 7)
для renderer обязателен, иначе он копит секунды. (4) `pacer_late` камеры вырос ×11 — не разбирал,
для 4.8. Сырые `s45_T1r*.json` лежат в `%TEMP%` (временные).

#### Acceptance
- [ ] В реестре нет `FW_SHM_OWNER_INCARNATION`, `FW_SHM_HANDLE_CACHE`, `FW_SHM_ZERO_COPY`,
      `FW_SHM_SEQLOCK`; `grep FW_SHM_` вне реестра, тестов и истории — только `LOAN_PROTOCOL` и
      `PREFIX_CLEANUP`.
- [ ] Два процесса с ключом `mask` получают разные имена сегментов (Windows и POSIX-логика имени).
- [ ] 100 realloc писателя подряд: у читателя открытых handles ≤ глубина × ключи, `close_errors` не
      растёт без живых view.
- [ ] `blob_detector(draw_contours=True)` на read-only входе работает, вход не меняется.
- [ ] Без настройки: глубина 8, IPC data-очередь у всех 50 (потолок памяти, не выводится из топологии),
      `chain_max_lag_items` 2 для процесса за писателем кольца; транзитный запас B − lag = 4 (B = 8 − 2 = 6);
      рецепт с `frame_ring_depth: 12` даёт lag 2 и транзит 8; явный `chain_max_lag_items` вне `1..B−2` →
      ошибка старта (ADR-173, вердикт CTO C2/C3).
- [ ] **Живьём (лид):** 1080p 100 fps, 30 с, пиксельная метка: чужих кадров у плагина 0; доля
      stale+torn — число в отчёте; сравнение с 4.4 (та же машина, тот же рецепт).
- [ ] Все рецепты из `backend/topology` и `recipes/`, которые стартуют на этой машине, стартуют и 30 с
      работают без `ValueError: assignment destination is read-only` в логах.
- [ ] `overflow: every` на процессе инспекции, плагин медленнее потока: каждый потерянный кадр даёт ровно
      один маркер `not_inspected` ниже по цепочке (число маркеров = числу дропов по счётчикам, литерал на
      стенде с пиксельной меткой); `overflow: latest` на GUI — маркеров нет.

**Out of scope (шаги 3–5 вердикта, отдельно):** B-7 per-target; `render_overlay` ROI; `color_mask`
без потребителя; финальная приёмка 4.3 (480p/1080p × 60/100).

#### Разбиение на подзадачи (2026-10-01, разведка по `e6976f8b`)

Сверка спеки с кодом: `FW_SHM_SEQLOCK` уже удалён из реестра в 4.4, в коде его имя осталось только в
docstring'ах. `blob_detector` после T1 уже копирует кадр перед рисованием (`plugin.py:135-145`), от
пункта 3 остаётся тест на read-only вход. `bseq` в pipeline нет: он есть только в мосте GUI. Ключа
`overflow` нет нигде. Data-очередь сейчас у всех 50 (`DEFAULT_QUEUES`). Блюпринт `queues` не задаёт.
Оба сборщика (`assembler.py:139`, `app_module/builder.py:253`) идут через
`TopologyBlueprint.build_configs()`, туда и кладётся вывод размеров.

Ориентир владельца (2026-10-01): система универсальная и производительная по всем узлам. Отсюда одно
правило для всех узлов без исключений по типу процесса: бюджет в полёте (4.7c) выводится для любого
процесса за любым писателем кольца (generic или wire), а не только за generic.

Порядок: 4.7a → 4.7b → 4.7c → 4.7d. Код пишет Sonnet (`developer`), ревью — Opus. Слепой tester
запускается на каждую подзадачу до кода, в worktree на коммите этого раздела.

##### 4.7a — Предусловия P-1, P-2
**Files:** `Plugins/_shared/fanin/join_inspector_manager.py`,
`multiprocess_framework/modules/router_module/middleware/frame_shm_middleware.py` (`strip_and_write`).
**Acceptance:**
- [ ] join двух входов, у каждого `_shm_views` (список ссылок): у склеенного item'а `_shm_views` =
      конкатенация обоих (первичный вход первым), независимо от `_list_keys` в конфиге.
- [ ] `_shm_views` только у вторичного входа → есть в склеенном item'е.
- [ ] Дверь: вход-view устарел (поколение слота сменилось) к моменту отправки, а выход не несёт ни
      одного массива, смотрящего в чужую память (корень цепочки `.base` — собственный ndarray: dict без
      массивов; массивы-копии) → сообщение уходит, stale-счётчики не растут.
- [ ] Дверь: выход несёт массив, смотрящий в чужую память (корень цепочки `.base` — не собственный ndarray:
      view или срез входа), вход устарел → дроп, как сейчас.

##### 4.7b — Один режим shm: имена, кэш handles, zero-copy, флаги
**Files:** `config_module/feature_flags.py`, `shared_resources_module/memory/platform/shm.py`,
`shared_resources_module/memory/core/manager.py`, `shared_resources_module/memory/reader/shm_frame_reader.py`,
`router_module/middleware/frame_shm_middleware.py`, `frontend_module/bridge/remote_frame_source.py`,
`multiprocess_prototype/frontend/bridge_process.py`, рецепты и `backend_ctl/probes` с env-строками флагов.
**Acceptance:**
- [ ] В реестре нет `FW_SHM_OWNER_INCARNATION`, `FW_SHM_HANDLE_CACHE`, `FW_SHM_ZERO_COPY`.
      `FW_SHM_LOAN_PROTOCOL` остаётся выключенным, с пометкой FROZEN (п. 6), и в его `requires` нет удалённых
      флагов. `grep FW_SHM_` в `*.py`/`*.yaml` вне реестра и тестов находит только `LOAN_PROTOCOL` и
      `PREFIX_CLEANUP`.
- [ ] Имя сегмента без env: два владельца с ключом `mask` дают разные имена. Это проверяется для
      Windows-ветки и для POSIX-ветки (платформа подменяется в тесте). В имени есть владелец, pid и
      инкарнация. Повторное создание тем же владельцем даёт новое имя.
- [ ] Кэш reader'а без env и без кэпа 8. Ключ — `(owner, slot, idx)` из ссылки. 100 realloc писателя
      подряд: открытых handles у читателя ≤ глубина × ключи. Без живых view `close_errors` не растёт.
- [ ] Handle с живым view при отставке не закрывается и не роняет чтение. Он закрывается на следующей
      отставке или на teardown после освобождения view. Отложенные закрытия видны счётчиком.
- [ ] Читатель-пайплайн (`restore_frame` с `allow_view=True`) без env получает view только для чтения
      (`flags.writeable == False`). Copy-out (`on_receive`, GUI, мост) получает копию с проверкой `gen`.
- [ ] `blob_detector(draw_contours=True)` на read-only входе работает, вход не меняется.

##### 4.7c — Глубина кольца и размер очереди из рецепта
**Files:** `router_module/middleware/frame_shm_middleware.py` (`_resolve_ring_depth`),
`process_module/generic/{generic_process.py,generic_process_config.py}`, `process_module/commands/builtin_commands.py`
(wire `buffer_slots`), `frontend_module/bridge/wire_protocol.py`, `process_manager_module/topology/blueprint.py`,
новый `process_manager_module/topology/inflight.py`.
**Контракт:** `inflight_budget(writer_depths, *, queue=None, lag=None, process="?") -> tuple[int, int]`
возвращает `(data_queue_maxsize, chain_max_lag_items)`. D = min(writer_depths), бюджет B = D − 2.
По умолчанию lag = 2, queue = B − lag. Явный `queue` или `lag` из рецепта с queue + lag > B →
`ValueError` с текстом `очередь <queue> больше кольца <D>` и именем процесса. Если D < 4, то
`ValueError`: на очередь ≥ 1 и lag ≥ 1 места нет, а lag 0 в `DataReceiver` означает «без границы».
Ключи рецепта процесса — `data_queue_maxsize` (новый) и `chain_max_lag_items` (есть).
**Acceptance:**
- [ ] Без env и без настройки глубина кольца generic-писателя 8, wire `buffer_slots` 8. Гейта
      `FW_QOS_PROFILES` на глубину нет.
- [ ] Процесс за писателем кольца (generic или wire) после `build_configs()` получает `chain_max_lag_items` 2;
      его IPC data-очередь остаётся 50 (memory cap, не выводится из топологии — C2).
- [ ] `frame_ring_depth: 12` у писателя даёт lag 2 и транзитный запас 8. Два писателя с глубинами 8 и 12 дают
      транзитный запас 4: `inflight_budget([8, 12]) == (4, 2)` — «4» читается как резерв `B − lag`, а не как
      maxsize очереди.
- [ ] Явный `chain_max_lag_items` вне `1..B−2` (кольцо 8: B = 6, допустимо 1..4) → ошибка сборки с именем
      процесса. Явная `data_queue_maxsize` — потолок памяти, к проверке бюджета не относится.
- [ ] Bound в `DataReceiver` вытесняет только кадровые коллекции (`_shm_views` или `frame`), выборочно под
      `chain_queue.mutex`; сигнал рядом с кадрами при превышении lag не теряется (C1).
- [ ] Приёмник отдаёт в `get_cycle_metrics()` gauge `ipc_queue_depth` и счётчик `transit_over_budget`
      (глубина > B − lag); поколение view проверяется до цепочки (C4); для провода глубина берётся у кольца
      процесса-источника.
- [ ] Процесс без входа от писателя кольца сохраняет прежнюю data-очередь 50 и lag без вывода.

##### 4.7e — Несколько камер (указание владельца 2026-10-01)
Камер может быть больше одной. Они не должны конфликтовать и должны работать максимально эффективно.
Сквозной критерий для 4.7b–d, отдельного кода не требует.
- [ ] Две камеры с одинаковыми ключами (`frame`, `mask`) получают непересекающиеся сегменты. Для
      длинных имён уникальность держится на хеше полного имени (`_bounded_name`), а владелец и pid
      читаются в имени, только если укладываются в лимит.
- [ ] Узел за несколькими камерами (join, inspector) получает бюджет в полёте по минимальной глубине их
      колец (`inflight_budget([8, 12]) == (4, 2)`). Кэш handles у такого узла ограничен суммой
      «глубина × ключи» по камерам.
- [ ] **Живьём (лид):** двухкамерный рецепт (`dualcam_synth`) 30 с: чужих кадров 0 у обеих камер,
      `pacer_late` и stale+torn по каждой камере в отчёте, A/B к базе в одном окне замка.
- [ ] Вывод бюджета и глубины берётся из рецепта каждого процесса. Глобальной константы «на систему»
      нет: третья камера с `frame_ring_depth: 12` не меняет бюджет узлов за первыми двумя.

##### 4.7d — Правило переполнения `overflow: latest | every` (п. 7)
**Level:** Senior+ · **Assignee:** teamlead (4.7d-1 — developer) · **Layer:** framework + Plugins
**Goal:** рецепт процесса выбирает, что делать с потерянным кадром: `latest` — отбросить и посчитать (как сейчас),
`every` — отбросить, посчитать и пустить вниз по цепочке маркер `not_inspected` на каждый потерянный входной кадр.
Основания: п. 7 дизайна, вердикт CTO Q2 (`docs/reviews/2026-10-01_task-4.7-cto-verdict.md`), ADR-173. Решения лида
ниже зафиксированы и не пересматриваются в этой задаче.

**Решения (зафиксированы):**
1. **Умолчание `latest`.** П. 7 писал «`every` по умолчанию для processing-процессов»; здесь умолчание — `latest`,
   поведение 4.7c не меняется молча. `every` включается рецептом процесса инспекции. Смена умолчания — отдельное
   решение после живого A/B (`every` добавляет трафик маркеров).
2. **Единица счёта — один маркер на один потерянный ВХОДНОЙ item** (кадр, который не проверили; у маркера свои
   `trace_id`/`capture_ts`). «Item» — элемент коллекции, пришедшей в `chain_queue` после коллектора; у join это
   склеенный item (один маркер, не по числу склеенных сообщений). На restore единица — сообщение (коллектора ещё нет).
3. **Маркер рождается только там, где в руках метаданные item** (CTO Q2): (а) `DataReceiver._bound_lag`;
   (б) `restore_frame` вернул `_shm_dropped`; (в) `PipelineExecutor._run_batch`, pre- и post-chain; (г) дверь
   `strip_data_frame_on_send`. У писателя — только `data_evicted.<жертва>`, маркера нет.
4. **Маркеры идут мимо коллектора и мимо плагинов**, кроме плагинов с `accepts_markers = True` (разбор ниже).
5. **Склейка «сигнал + кадр» в одной коллекции** (join): коллекция кадровая (C1) и выбрасывается целиком, вместе с
   сигналом. Это семантика join, не дефект bound. Сигнал в маркер не переносится, потеря сигнала видна только как
   `lag_dropped_items`.

**Что код делает сегодня (сверка по `23f872bce`, от неё зависят шаги):**
- Нигде в коде нет читателя `inspection_status`. Тег ставят `PluginOperationStep` (сбой плагина) и `SuspectTagStep`, но
  `RobotControlPlugin.process` решает только по `item["detections"]`: item без детекций получает `action: "pass"`.
  Поэтому маркер, дошедший до отбраковщика обычным item'ом, был бы принят за годный кадр. Отсюда шаг 4.7d-2 (маркеры
  мимо цепочки) и 4.7d-4 (потребитель).
- `frame_stale_drops` = `reader.stale_drops` + отвязанные сегменты + `note_stale_drops`. Один счётчик reader'а бьют
  restore, pre-chain, post-chain и дверь, по месту дроп не различить. Поэтому формула приёмки сводится по сумме (ниже).
- Pre-chain stale считает входы (`1 + note_stale_drops(len(items)-1)`), post-chain — выходы
  (`pipeline_executor.py:262-267`; 2→1 даёт 2 против 1, 1→3 даёт 1 против 3). Дверь считает выходы
  (по одному на item). После 4.7d-2 post-chain считает входы, как pre-chain; дверь остаётся по выходам.
- Пост-проверка `valid` стоит ПОСЛЕ `if not items: return` (`pipeline_executor.py:258-260`): при пустом выходе и
  устаревшем view reader уже прибавил 1, но батч «не дропнут». 4.7d-2 ставит проверку `valid` раньше.
- «torn@exec» в коде нет: `_run_batch` видит только расхождение поколения (stale). Torn (перезапись во время чтения)
  возникает на restore (`frame_torn_reads`) и входит в причину `stale_restore`.

**Контракт маркера** (новый модуль `router_module/middleware/not_inspected_marker.py`; рядом с `SHM_*`-константами,
чтобы `router_module` не импортировал `process_module`):
- `NOT_INSPECTED = "not_inspected"`; `MARKER_REASONS = ("lag", "stale_restore", "stale_exec", "door")`.
- `build_marker(meta: dict, *, reason: str, source: str) -> dict`. Ровно эти ключи:
  `inspection_status="not_inspected"`, `overflow_marker=True`, `reason`, `source` (имя процесса, где кадр потерян;
  при пересылке не перезаписывается), `trace_id` (str, `""` если у кадра не было), `capture_ts` (float | None);
  `frame_id` и `camera_id` — только если есть в `meta`. Никаких `frame`, `_shm_refs`, `_shm_views`, `_shm_dropped`,
  `target`. `reason` вне `MARKER_REASONS` — `ValueError`.
- `is_marker(item) -> bool`: `True` только при `overflow_marker is True` и `inspection_status == "not_inspected"`.
  Item с тегом `not_inspected` от сбоя плагина (кадр с картинкой, течёт по цепочке) маркером не считается.
- `meta` собирается так же, как `DataReceiver._build_item` строит item: `trace_id`/`capture_ts` из `msg["data"]`,
  `frame_id`/`camera_id` из `data`, иначе из `msg`.
- Поля выбраны под отбраковщика: `trace_id` связывает с широкой записью и вердиктом, `capture_ts` даёт возраст
  потерянного кадра, `source` и `reason` — куда смотреть, `frame_id`/`camera_id` — какая камера.

**Счётчики (имена фиксированы, их читает слепой tester):**
- `DataReceiver.get_cycle_metrics()`: `lag_dropped_items` (при `chain_max_lag_items > 0`, любой режим; сумма
  `len(coll)` выброшенных коллекций; `lag_dropped_total` остаётся числом коллекций); `not_inspected_lag`,
  `not_inspected_stale_restore` — только при `every`.
- `PipelineExecutor.get_cycle_metrics()`: `not_inspected_stale_exec` — только при `every`; `not_inspected_handled` —
  всегда: сколько маркер-item'ов прошло через `_forward_markers` (рождённые в этом процессе на restore/bound/exec и
  пришедшие сверху). Дверные маркеры сюда не входят.
- `FrameShmMiddleware`: свойство `door_drops` (всегда; выходов, дропнутых дверью по `_inputs_still_valid`; это
  подмножество `frame_stale_drops`, не добавка к нему) и `not_inspected_door` (только при `every`; рождено, не
  доставлено: при fan-out на N целей одно рождение = N доставок).
- Публичное read-only свойство `overflow` у `DataReceiver`, `PipelineExecutor`, `FrameShmMiddleware`.
- При `latest` ключей `not_inspected_lag`, `not_inspected_stale_restore`, `not_inspected_stale_exec`,
  `not_inspected_door` нет вовсе (не нули).

**Формула приёмки (вердикт CTO, в терминах счётчиков процесса).** Под `every`, для каждого процесса:
`not_inspected_lag + not_inspected_stale_restore + not_inspected_stale_exec + not_inspected_door
= Δlag_dropped_items + Δframe_stale_drops + Δframe_torn_reads + Δframe_restore_failures`.
Слева — рождённые маркеры, справа — независимые счётчики дропов. `data_evicted.<жертва>` пишется отдельной строкой и на
стенде под `every` равен 0; не ноль — находка по мощности, не дефект 4.7d. Дроп по исчерпанию займа (loan заморожен),
дроп при остановке (`stop_event` в `on_items_ready`) и дроп по `frame_id`-разрыву в формулу не входят.

**Порядок и независимость.** 4.7d-1 первой. После неё 4.7d-2, 4.7d-3, 4.7d-4 независимы друг от друга (общих файлов
нет) и идут параллельно. 4.7d-3 правит `frame_shm_middleware.py`, как и 4.7b: идти после слияния 4.7b или
перебазироваться (разные методы, текстуально конфликта быть не должно). 4.7d-5 — после 2 и 3. Слепой tester — на
каждую подзадачу до кода, в worktree на коммите этого раздела.

###### 4.7d-1 — Ключ рецепта и контракт маркера (4 кода-файла, developer)
**Files:** новый `multiprocess_framework/modules/router_module/middleware/not_inspected_marker.py`,
`multiprocess_framework/modules/process_module/generic/generic_process_config.py`,
`multiprocess_framework/modules/process_manager_module/topology/blueprint.py` (`as_generic_config`, по образцу `_pick`
у `chain_max_lag_items`), `multiprocess_framework/modules/process_module/generic/generic_process.py` (чтение
`overflow` из `app_cfg` и передача в `DataReceiver`, `PipelineExecutor`, `FrameShmMiddleware`; сами они меняются в 4.7d-2/3,
здесь только проводка и kwarg `overflow="latest"` в их конструкторах).
**Steps:** 1. Модуль маркера по контракту выше. 2. Поле `GenericProcessConfig.overflow: Literal["latest","every"] = "latest"`;
`build()` кладёт `config["overflow"]` только при `every`. 3. `_pick("overflow", "latest")` в `as_generic_config`, ошибка
сборки на неизвестное значение. 4. Проводка в `_init_data_pipeline`.
**Acceptance:**
- [ ] `ProcessConfig(process_name="p", extras={"overflow": "every"}).as_generic_config().overflow == "every"`; без ключа
      `== "latest"`; typed-поле, заданное явно, перекрывает extras (как у остальных `_pick`).
- [ ] `overflow: "sometimes"` в рецепте → `ValueError`, текст содержит имя процесса, `overflow` и `'sometimes'`.
- [ ] `GenericProcessConfig(overflow="every").build()[1]["config"]["overflow"] == "every"`; при `latest` ключа
      `"overflow"` в `proc_dict["config"]` нет (golden-снапшоты `build` не меняются).
- [ ] `build_marker({"trace_id": "t1", "capture_ts": 12.5, "frame_id": 7, "camera_id": "cam0", "frame": <ndarray>,
      "_shm_views": [...]}, reason="lag", source="processor_0")` равен ровно
      `{"inspection_status": "not_inspected", "overflow_marker": True, "reason": "lag", "source": "processor_0",
      "trace_id": "t1", "capture_ts": 12.5, "frame_id": 7, "camera_id": "cam0"}`.
- [ ] `build_marker({}, reason="door", source="p")`: `trace_id == ""`, `capture_ts is None`, ключей `frame_id` и
      `camera_id` нет. `build_marker({}, reason="foo", source="p")` → `ValueError`.
      `MARKER_REASONS == ("lag", "stale_restore", "stale_exec", "door")`.
- [ ] `is_marker(build_marker(...)) is True`; `is_marker({"inspection_status": "not_inspected", "frame": f}) is False`;
      `is_marker({}) is False`.
- [ ] `GenericProcess` с `overflow: every` в конфиге: `receiver.overflow`, `executor.overflow`, `shm_middleware.overflow`
      равны `"every"`; без ключа — `"latest"` (проверка на реальной сборке `_init_data_pipeline`, не на подменах).

###### 4.7d-2 — Рождение маркера в приёмнике и исполнителе, проход маркера (3 кода-файла, teamlead)
**Files:** `multiprocess_framework/modules/process_module/generic/data_receiver.py`,
`multiprocess_framework/modules/process_module/generic/pipeline_executor.py`,
`multiprocess_framework/modules/process_module/generic/plugin_operation_step.py`.
**Steps:**
1. `_bound_lag`: при `every` каждая выбрасываемая кадровая коллекция заменяется НА ТОМ ЖЕ МЕСТЕ очереди коллекцией
   маркеров (`pending[i] = markers`, под `chain.mutex`, по маркеру на item, `reason="lag"`). Длина очереди не растёт,
   порядок сохраняется. Маркер-коллекция не кадровая (`_is_frame_collection` её не считает) и потолком не вытесняется.
   Метка `enq_ts` у неё — момент замены. При `latest` — `del`, как сейчас. Счётчик `lag_dropped_items` растёт в обоих режимах.
2. `run_loop`: на ветке `_is_shm_dropped` при `every` вместо `continue` строится маркер из `msg` (`reason="stale_restore"`,
   `source` = имя узла) и уходит `self.on_items_ready([marker])` — мимо коллектора. При `latest` — `continue`, как сейчас.
   Покрывает любой отказ restore: stale, torn, отвязанный сегмент, сбой открытия ссылки.
3. `run_loop`: пришедший по IPC маркер (`is_marker(data)`), в любом режиме, не идёт в коллектор, а уходит
   `on_items_ready([item])` отдельной коллекцией.
4. `_run_batch`: коллекция из одних маркеров (`all(is_marker)`) идёт в `_forward_markers`: без проверок view и без
   `_attach_batch_views`, `_execute_chain` (плагины без `accepts_markers` пропускаются) → `_send_results`;
   `not_inspected_handled += len(items)`.
5. Шаги цепочки: `PluginOperationStep.execute` на маркер-коллекции возвращает её как есть, если у плагина нет
   `accepts_markers = True` (плагин не вызывается, `on_success`/`on_fail` и счётчики breaker не трогаются);
   `SuspectTagStep` маркер-коллекцию не тегирует (`not_inspected` не перезаписывается на `suspect`).
6. Stale в `_run_batch` (оба режима): единица счёта — ВХОДНЫЕ items батча. Post-chain: `valid` проверяется до
   `if not items`; `note_stale_drops(len(inputs) - 1)` вместо `len(items) - 1`. При `every` метаданные входов снимаются
   ДО цепочки (`build_marker` из каждого входного item; плагин может заменить dict), и при stale (pre- или post-chain)
   уходит по маркеру на вход, `reason="stale_exec"`, через `_forward_markers`; `not_inspected_stale_exec += len(inputs)`.
   Выходы цепочки при post-chain stale не отправляются (как сейчас).
**Acceptance** (литералы; `chain_queue` и `FrameShmMiddleware`/reader настоящие, исполнитель в тестах остановлен, где сказано):
- [ ] Bound, `every`, `chain_max_lag_items=2`, исполнитель не читает. Приходят кадровые коллекции по 1 item,
      `trace_id` `t1..t6`. Очередь после шестой: `qsize() == 6`, порядок `[M(t1), M(t2), M(t3), M(t4), c5, c6]`, где `M(tN)` —
      коллекция из одного маркера `reason="lag"`, `trace_id="tN"`. `lag_dropped_total == 4`, `lag_dropped_items == 4`,
      `not_inspected_lag == 4`.
- [ ] Тот же вход при `latest`: `qsize() == 2`, `[c5, c6]`, маркеров в очереди 0, `lag_dropped_total == 4`,
      `lag_dropped_items == 4`, ключа `not_inspected_lag` в `get_cycle_metrics()` нет.
- [ ] Выброшена коллекция из 2 items (`t1`, `t2`) при `every`: на её месте одна коллекция из 2 маркеров (`t1`, `t2`);
      `lag_dropped_total` +1, `lag_dropped_items` +2, `not_inspected_lag` +2.
- [ ] Сигнальная коллекция (без `frame` и `_shm_views`) не заменяется маркером и не вытесняется ни при каком режиме
      (C1 сохраняется): очередь `[сигнал, c1, c2]`, приходит `c3`, lag 2 → `[сигнал, M(c1), c2, c3]`.
- [ ] Join: выброшена коллекция `[{"frame": f, "trace_id": "t1", "pult": {...}}]` → ровно 1 маркер `t1`; в маркере
      нет ключа `pult`; `lag_dropped_items == 1`.
- [ ] Restore, `every`: `restore_frame` вернул msg с `_shm_dropped`, в `data` `trace_id="t9"`, `capture_ts=3.5`. В
      `chain_queue` одна коллекция из одного маркера `{reason: "stale_restore", trace_id: "t9", capture_ts: 3.5, source: <имя узла>}`;
      `collector.on_item` не вызывался; `not_inspected_stale_restore == 1`. При `latest`: `chain_queue` пуст, коллектор не
      вызывался, ключа нет.
- [ ] Restore на реальном middleware, `every`, четыре отказа по одному (перезапись слота до чтения; перезапись во время
      чтения; отвязанный сегмент; битая ссылка): каждый даёт ровно 1 маркер `stale_restore`, и после каждого
      `Δframe_stale_drops + Δframe_torn_reads + Δframe_restore_failures == 1`.
- [ ] Пришедший по IPC маркер (`is_marker`), режимы `latest` и `every`: `collector.on_item` не вызывался, в `chain_queue`
      отдельная коллекция из этого item'а, все поля маркера целы, `source` не изменён.
- [ ] Исполнитель, маркер-коллекция, плагин без `accepts_markers` (в цепочке есть критический bypassed плагин): `process`
      вызван 0 раз, `consecutive_fails` не изменился, `inspection_status == "not_inspected"` (не `"suspect"`);
      `send_fn` получила по сообщению на каждый `chain_targets`, `data` равен маркеру (кроме служебных `_t_sent_ns`,
      `frame_trace`-штампа); `not_inspected_handled` +1.
- [ ] Плагин с `accepts_markers = True` получает маркер-item в `process` ровно 1 раз (spy), тот же объект данных.
- [ ] Stale pre-chain, `every`, батч из 3 items (`t1,t2,t3`) со view, слот перезаписан до такта: цепочка не вызывалась
      (spy 0), `send_fn` получила 3 сообщения-маркера (`stale_exec`, `t1,t2,t3` по порядку), `frame_stale_drops` +3,
      `not_inspected_stale_exec == 3`.
- [ ] Stale post-chain 2→1 (плагин склеивает 2 входа в 1 выход, слот перезаписан во время `process`), `every`:
      `send_fn` получила 2 маркера (`t1,t2`) и 0 обычных, `frame_stale_drops` +2 (было +1 по выходам),
      `not_inspected_stale_exec == 2`.
- [ ] Stale post-chain 1→3: `frame_stale_drops` +1 (было +3), 1 маркер.
- [ ] Stale post-chain, плагин вернул `[]`, слот перезаписан: `frame_stale_drops` +1 (вход), 1 маркер (`every`).
- [ ] Те же три сценария (pre 3, post 2→1, post 1→3) при `latest`: `send_fn` не вызывалась, `frame_stale_drops`
      +3 / +2 / +1, ключа `not_inspected_stale_exec` нет, `not_inspected_handled` не вырос.
- [ ] Батч с неизменёнными view: маркеров 0, обычные результаты уходят как раньше.

###### 4.7d-3 — Маркер в двери отправителя (1 код-файл, developer)
**Files:** `multiprocess_framework/modules/router_module/middleware/frame_shm_middleware.py`
(`strip_data_frame_on_send`, `strip_and_write`; конструктор принимает `overflow`, `source` = `self._owner`).
**Steps:** 1. Счётчик `door_drops` (всегда): +1 на каждый item, у которого `strip_and_write` впервые поставил
`_shm_dropped`. 2. При `every` вместо `return None` содержимое `msg["data"]` заменяется на маркер (`reason="door"`,
метаданные — из item до замены; `msg["target"]`, `type`, `channel` не трогаются), сообщение уходит. Замена идёт на
месте в общем `data`-dict, поэтому повторный `send` fan-out видит уже маркер, и второе рождение не происходит.
3. При `latest` — `None`, как сейчас.
**Acceptance:**
- [ ] `every`, одна цель: выход с массивом, смотрящим в чужой слот (условие дропа 4.7a), слот входа перезаписан во время
      копии. `strip_data_frame_on_send(msg)` возвращает msg, не `None`; `msg["data"]` равен маркеру `reason="door"`,
      `trace_id`/`capture_ts` исходного item, `source == owner`; в `msg["data"]` нет ключей `frame`, `_shm_refs`,
      `_shm_views`, `_shm_dropped`; `door_drops == 1`, `not_inspected_door == 1`, `frame_stale_drops` +1.
- [ ] Fan-out на 2 цели, один и тот же `data`-dict: оба вызова возвращают сообщение с одним маркером;
      `not_inspected_door == 1`, `door_drops == 1` (рождено один раз, доставлено 2).
- [ ] `latest`, тот же вход: возвращает `None` (как сегодня), `door_drops == 1`, ключа `not_inspected_door` нет.
- [ ] Вход валиден: маркера нет, `door_drops == 0`, сообщение идёт как раньше. Выход без чужой памяти (4.7a): тоже 0.
- [ ] `msg["target"]` сохранён при замене (per-item target не теряется).
- [ ] Дроп по исчерпанию займа (`_last_loan_exhausted`) по-прежнему `None` в обоих режимах (loan заморожен, вне 4.7d).
- [ ] Реальный путь на двух настоящих middleware (писатель и читатель, настоящее SHM): перезапись входа в двери под `every`
      даёт на стороне читателя item с `is_marker(item)`; под `latest` читатель ничего не получает.

###### 4.7d-4 — Отбраковщик принимает маркер (1 код-файл, developer; решение о политике — за владельцем)
**Files:** `Plugins/control/robot_control/plugin.py`.
**Контекст:** без этого шага маркер доезжает и виден в счётчиках, но `RobotControlPlugin` его не видит или считает
годным (item без детекций → `pass`). Политика «непроверенное = брак» взята из `multiprocess_prototype/plans/phase5_data_pipeline.md`
(«лучше выкинуть хорошую, чем пропустить плохую»); подтверждение владельца нужно до кода.
**Steps:** 1. `accepts_markers = True` на классе. 2. Для маркер-item: `inspection_result = {"action": "reject",
"reason": "not_inspected", "origin": <reason маркера>, "source": <source маркера>}`; свой счётчик `total_not_inspected`;
`total_inspected` не растёт, вердикт-документ и фронт `_rejecting` не пишутся и не меняются.
**Acceptance:**
- [ ] Маркер `reason="lag"`, `trace_id="t1"` в `process`: `item["inspection_result"]["action"] == "reject"`,
      `["reason"] == "not_inspected"`, `["origin"] == "lag"`; `total_not_inspected == 1`, `total_inspected` не изменился.
- [ ] Обычный item без детекций по-прежнему `pass`; обычный item с детекцией — `reject` (существующие тесты зелёные).
- [ ] Маркер не пишет вердикт-документ (`_verdicts_written` не меняется) и не меняет `_rejecting`.
- [ ] Связка с 4.7d-2: цепочка `[blob_detector, robot_control]`, маркер-коллекция на входе: `blob_detector.process`
      вызван 0 раз, `robot_control.process` — 1 раз.

###### 4.7d-5 — Приёмка на стенде (лид, без кода)
**Acceptance:**
- [ ] ADR в `multiprocess_framework/DECISIONS.md` (одна запись: правило переполнения, единица счёта, три отказа от
      иного места рождения маркера) + `python -m scripts.sync`; README/STATUS у `process_module` и `router_module`.
- [ ] Стенд из перемера 4.7 (1080p, 100 fps, 30 с, пиксельная метка), процесс инспекции с `overflow: every`, плагин
      медленнее потока, ≥ 3 прогона. По каждому процессу формула приёмки сходится с разностью 0, числа слева и справа в
      отчёте. `data_evicted.<жертва>` 0 (иначе находка по мощности, не провал 4.7d).
- [ ] Учёт кадров: для каждого `trace_id` камеры ровно один исход, результат на выходе цепочки либо маркер.
      `результатов + маркеров == кадров камеры − data_evicted` (литералы в отчёте). Ни один `trace_id` не встречается
      и там, и там.
- [ ] Число маркеров, дошедших до следующего узла (`not_inspected_handled` у него), равно числу рождённых маркеров на
      процессе при одной цели `chain_targets` (при N целях — рождённые × N).
- [ ] Тот же стенд с `overflow: latest` (и процесс GUI/renderer/мост): маркеров 0, ключей `not_inspected_*` в метриках нет.
- [ ] A/B `latest` против `every` на одной машине в одном окне замка: пропускная способность и `queue_wait_ms` в отчёте
      (цена маркеров).

**Out of scope:** маркер по разрыву `frame_id` (вопрос владельцу в `docs/claude/OPEN_QUESTIONS.md`, 2026-10-01); маркер у
писателя при вытеснении `data_evicted`; дроп по исчерпанию займа; дроп при остановке процесса; смена умолчания на
`every`; разбор `OPEN_QUESTIONS` по ожидающему партнёру join при потерянной половине; приём маркера мостом и GUI
(`frontend_module/bridge`), не являющимися generic-узлами; маркер для копии `copy_out_targets`.

**Единица счёта (ревью 4.7a/c) закрыта решением 2:** выбран входной item; post-chain переведён с выходов на входы;
дверь считает выходы (она не знает состава батча) и совпадает с входами при цепочках 1→1, как на стенде.

#### Статус на 2026-10-01 (пауза по просьбе владельца)

| Часть | Итог |
|---|---|
| 4.7a | Слита в ветку. Слепой tester `0d1b4f8a`, developer `8b3f2c1d`, ревью Opus — APPROVE_WITH_NITS, итерация 1 `9fc01550` (своя память плагина по корню `.base`, ключ `SHM_VIEWS_KEY` импортом) — ревью Opus APPROVE_WITH_NITS, страховка owndata (N-2) в `5dff941f1`. Инъекции лида 7/7 пойманы |
| 4.7b | Только слепые RED-тесты (`efd8d3df`), в ветке они стоят как `xfail(strict=True)`. Реализации нет |
| 4.7c | Переделана по C1–C4 и проводу: tester `da19b452a`, developer `375bbb4b2` + `f4f8993c7` + `5dff941f1`, инъекции лида 11 мутаций (`notify` — ненаблюдаем, задокументировано), ревью Opus APPROVE_WITH_NITS, нитки закрыты. Решение записано как ADR-173 (`multiprocess_framework/DECISIONS.md`). Первая редакция `a8ffdf54` отвергнута (REQUEST_CHANGES + вердикт CTO) |
| 4.7d | Место маркера решено вердиктом CTO (ниже). Спеки нет |

**Вердикт CTO (`docs/reviews/2026-10-01_task-4.7-cto-verdict.md`) заменяет п. 5 дизайна и acceptance «очередь 4».**
Бюджет в полёте считает **кадры**, а не сообщения. Сигналы и решения бюджет не вытесняет: ревью
воспроизвело потерю кнопки `pult → points` при очереди 4 и lag 2. Условия:
- **C1.** Bound в `DataReceiver` считает только коллекции с `_shm_views`/`frame`. Удаление выборочное,
  под `chain_queue.mutex`.
- **C2.** IPC data-очередь остаётся memory cap 50. `data_queue_maxsize` из топологии не выводится:
  писатель не может отличить кадр от сигнала, `get_nowait` на чужой `mp.Queue`.
- **C3.** `inflight_budget` остаётся (D − 2, lag 2). Глубина IPC-очереди измеряется (gauge +
  `transit_over_budget`), а не навязывается.
- **C4.** Проверка поколения view идёт ДО цепочки, а не только после.
- **Провод.** Для провода глубина берётся у кольца процесса-источника (находка ревью C-1).

Маркер `not_inspected` (4.7d) рождается там, где на руках метаданные кадра: bound приёмника, stale на
`restore_frame`, stale/torn в `_run_batch`, дверь (к своим `chain_targets`). У писателя только
счётчик `data_evicted`. Acceptance 4.7d: `lag_dropped + stale@restore + stale/torn@exec +
door_drops = маркеры`. `data_evicted` считается отдельно и под `every` на стенде равен 0.

**Следующие шаги:** 4.7c переделана и ждёт слияния лидом (ветка `feat/t47c-impl`) → 4.7b → 4.7d → живой A/B
(≥ 3 прогона на сторону, `dualcam_synth` по 4.7e).
