# Вердикт cto (Fable) по тракту кадров в GUI: ACCEPT WITH CONDITIONS

Автор: cto (Fable), только чтение и запуск репро; файл записан лидом (у роли нет Write). HEAD `46bdcdfff`, ветка `docs/camera-4.2d-4.2e-status`, код не менял, стенд не поднимал. Основа: `docs/reviews/2026-11-24_gui-memory-investigation.md`. Черновики вне репозитория: `...\scratchpad\cto\pull_fix.py`, `repro2.py`.

## Вердикт

Диагноз investigator-а принят: очередь событий Qt с полными копиями кадров не ограничена. Рост и замирание экрана cto воспроизвёл сам на настоящих `DataReceiverBridge` + `ImagePanelWidget`. Вариант A («последний кадр на ключ») принят как ядро, но не как решение целиком. Надёжное решение: почтовый ящик «последний кадр на ключ» как примитив framework + вытягивание из Qt-потока по таймеру с частотой `fps_limit` (не событие на кадр) + копия из SHM только для показываемого кадра + метрики через `get_cycle_metrics`.
Уверенность: механизм роста и ограничение памяти ящиком — ВЫСОКАЯ (запуски ниже); что именно это дало 7 ГБ в quad2 — СРЕДНЯЯ (числа стенда сходятся, живое окно не воспроизведено); отложенная копия (T5) и удешевление кадра (T6) — НИЗКАЯ, не прототипированы.

## Запуски cto (offscreen; смесь 2×1440×1080×3 + 2×1280×1024×3; база репро ≈660 МБ private)

| вход | вариант | private, МБ | отрисовок на слот | прочее |
|---|---|---|---|---|
| 220/с | как сейчас | 1063 → 1520 за 2 с (+457 МБ/с), стоп по потолку | 4 → 1 → 0 в секунду | очередь 93 → 205; таймер 100 мс: 1 тик/с; возраст кадра 534 → 1924 мс |
| 220/с, 8 с | A (latest на sender) | ≤679 | 156 | вытеснено 767 из 1763 |
| 220/с, 8 с | кольцо 64 МБ drop-oldest (идея владельца буквально) | ≤739 | **7 за 8 с** | показано reader_1 110 против camera_1 335; возраст ~200 мс |
| 400/с, 8 с | A | ≤684 | 116 | Qt-поток занят кадрами 7,72 с из 8; показано ~220 на слот |
| 400/с, 8 с | вытягивание таймером 25 Гц (черновик) | ≤686, в ящике макс. 16,4 МБ | 153 | Qt-поток занят 4,75 с из 8; показано 151 на слот; таймер 9-10 тик/с |

`on_frame`: медиана 7,2-7,5 мс, p95 12,5-15 мс. Числа quad2 из `stand-4.2i-numbers.md`: `cpu.seconds_total` gui 77,96 → 131,17 за ~46 с = 1,16 ядра (один поток занят полностью).

## Находки

| № | суть | путь:строка | вход → выход | серьёзность |
|---|---|---|---|---|
| 1 | Очередь Qt без предела держит полные копии кадров: событие на кадр | `multiprocess_prototype/frontend/bridge_impl.py:45,95`; `process.py:269-270` | 220 кадр/с → +457 МБ/с, отрисовка 0-1/с | HIGH |
| 2 | Тот же FIFO несёт state-дельты, записи наблюдаемости, ответы команд; затор кадров останавливает всё окно | `bridge_impl.py:81-95`; `process.py:183,208` | очередь 205 кадров → таймер 1 тик/с вместо 10 (поток одних дельт не проверялся) | HIGH |
| 3 | Перегрузка gui валит соседей: предела памяти процесса и реакции на него в framework нет | числа стенда: gui 6984,6 МБ, свободно 347 МБ, `MemoryError` camera_1, reader_2 «не жив» | не воспроизводилось; причина падения reader_2 не доказана | HIGH |
| 4 | Конфиг врёт: `displays[].fps_limit`, `width`, `height`, `format` главная панель не читает | `widgets/image_panel/recipe_displays.py:60-73` | рецепт quad `fps_limit: 20` → показ на частоте источника; `fps_limit` есть в 23 рецептах; `ring_buffer_blocks` читает только `backend/displays/blueprint_binding.py:80,131,137` (живость пути не проверена) | MED |
| 5 | Предел в штуках там, где нужны байты: один `receive()` копирует всю пачку до первой выдачи | `router_module/channels/queue_channel.py:101` (`POLL_DRAIN_CEILING = 4096`); `router_manager.py:1469-1471` | факт кода: 142 сообщения (busy.log) × 4,67 МБ = 663 МБ в одной пачке | MED |
| 6 | Дубль механизма: свой цикл приёма в gui без потолка и без метрик; третий такой же в headless | `process.py:255-307` против `process_module/generic/data_receiver.py:426-509`; `headless_process.py:86` | у воркера gui в `get_status` нет hz/dropped | MED |
| 7 | Счётчики вводят в заблуждение | `process.py:273-281` (пачки); `app.py:1161-1163` (FPS только первичного слота); `app.py:1291` + `windows/main_window.py:716-719` (задержка не передаётся) | «Latency: 0.0 ms» при любом потоке; штамп `capture_ts` в источниках не найден | MED |
| 8 | 4 полные копии кадра, три из них в Qt-потоке | `frame_shm_middleware.py:1333`; `image_panel/presenter.py:150,153`; `display_slot.py:58-62` | 7,4 мс на кадр → потолок ≈130 кадр/с на все дисплеи; 4 слота × 30 Гц = 90 % Qt-потока даже с ограничением частоты | MED |
| 9 | При событии на кадр конвертируются кадры, которые не рисуются | `bridge_impl.py:95` | A при 400/с: показано 220, отрисовано 116 на слот | MED |
| 10 | Кадр до `set_frame_callback` теряется молча | `bridge_impl.py:101-104`; `app.py:1185` | факт кода; важно для источника по триггеру (один кадр) | LOW |
| 11 | Потери gui видны только в router_stats; память отдаётся как `os.rss` | стенд-док | RSS встал на ~7 ГБ при исчерпанной RAM; private/commit не измерен | LOW |
| 12 | Тот же паттерн в других местах | `frontend_module/qt_event_bridge.py:109-114` (событие на сообщение, мелкие); `frontend_module/bridge/remote_frame_source.py:517` (после своего ящика `dispatch` на кадр; живого вызова `RemoteFrameSource(` вне тестов нет); `process_module/generic/cycle_metrics.py:59` (`deque()` без maxlen, не разбирался) | не запускалось | LOW |

Про «RSS упал на 290 МБ за 45 с»: по стенд-доку `last_cycle_age_s` = 4,47-4,60 и ≈1030 циклов `camera_0` за интервал — источники встали за ~4,5 с до замера 3; в запуске cto после остановки источника private вернулся 1520 → 659 МБ за 2 с (правдоподобно, не доказано).

## Целевая архитектура

| звено | политика перегрузки | предел | метрика |
|---|---|---|---|
| источник → SHM-кольцо `output_frames` | перезапись старого, писатель не ждёт | блоки × размер кадра | `shm_bytes_written`, отказы loan |
| IPC `gui_data` (ссылки) | drop_oldest у отправителя (есть) | штуки (сообщения мелкие) | `queue_data_evicted`, `queue_size` |
| приём gui (`FrameIntake`) | не блокирует, не копирует: кладёт сообщение со ссылкой в ящик | нет своей очереди | `frames_in` (кадры, не пачки), `batches` |
| `LatestMailbox` (framework, ключ = sender) | новое вытесняет старое того же ключа; ключи независимы | 1 элемент на ключ, `max_keys` 64 | `put`/`taken`/`superseded`/`pending`, `bytes_held`, `max_bytes_held` |
| `FramePump` (Qt, таймер на ключ, период из `fps_limit`) | вытягивает; событий на кадр нет | ≤ `fps_limit` конвертаций/с на слот | `shown`, `max_frame_age_ms`, `pump_busy_share` |
| копия из SHM | только при выемке; stale/torn = счётчик, следующий тик | 1 кадр в работе | `restore_dropped`, `shm_bytes_read` |
| слот | 1 исходный + 1 масштабированный pixmap | 2 на слот | — |
| процесс целиком | страховка: бюджет памяти процесса, реакция supervision | решение владельца | private bytes в `introspect_memory` |

Память тракта становится структурной: ключи × 1 кадр (16,4 МБ в замере) при любой частоте входа. Метрики идут готовым путём: воркер с `get_cycle_metrics()` → `WorkerManager.get_worker_status` (`worker_module/core/worker_manager.py:327-329`) → heartbeat → `get_status` backend_ctl.

## Оценка идеи владельца и вариантов

- **Бюджет + кольцо drop-oldest.** Политика «выбрасывать старое» верная. Кольцо глубже 1 для живого дисплея вредно: под перегрузкой оно всегда полно, экран отстаёт и почти не рисуется (7 отрисовок за 8 с), быстрый источник вытесняет медленный. Глубина 1 на дисплей и есть правильный предел. Бюджет в рецепте полезен на уровне процесса как страховка (находка 3).
- **A.** Надёжно: память ограничена (≤684 МБ при 220 и 400/с), все слоты живые. Заплатка: Qt-поток занят на 96 %, половина конвертаций впустую; копируются все кадры; `fps_limit` остаётся ложью; метрик нет; ящик стал бы третьей частной копией механизма (одна уже в `remote_frame_source.py:232,452-469`).
- **B** (`fps_limit` в `app.py:1149`): кадр уже скопирован и стоит в очереди, предела нет.
- **C** (уменьшать кадр под слот): поднимает порог, предела не даёт; вошёл как T6.
- Framework `DataReceiver` как есть не подходит: `_bound_lag` (`data_receiver.py:231`) держит N свежих коллекций на всех, дисплею нужен «последний на ключ».

## Задачи для sonnet

Порядок: T1 → T2 → T3 → (T4 ∥ T6) → T5; T7 параллельно с самого начала. Слепой tester один раз на механизм: T1 и T3. Стадия 0 на каждой; T5 — reviewer opus (потоки, SHM).

### T1. `LatestMailbox` (framework).
FILES: `multiprocess_framework/modules/frontend_module/bridge/latest_mailbox.py` (новый); `.../bridge/tests/test_latest_mailbox.py`; `.../bridge/__init__.py`; `frontend_module/DECISIONS.md`. DESIGN: класс без Qt, один `threading.Lock`. `put(key, item, nbytes=0) -> bool` заменяет ожидающий элемент ключа, считает `superseded`; новый ключ сверх `max_keys=64` отвергается (`rejected`). `take(key)` возвращает `(item, age_s)` или `None`; `clear()` считает выброшенное как `superseded`. `stats()`: `put, taken, superseded, rejected, pending, bytes_held, max_bytes_held`; инвариант `put == taken + superseded + pending`. REDS: `test_second_put_same_key_supersedes_first`, `test_keys_are_independent_fast_key_does_not_evict_slow_key`, `test_bytes_held_never_exceeds_latest_per_key`, `test_invariant_holds_under_two_threads`, `test_take_empty_returns_none`, `test_max_keys_rejects_and_counts`, `test_take_returns_age_from_injected_clock`, `test_clear_counts_superseded`. ACCEPTANCE: 4 ключа × 2500 put по 4 665 600 байт → `pending == 4`, `superseded == 9996`, `max_bytes_held == 18662400`. Reviewer: замена на общий FIFO должна убить тест независимости ключей.

### T2. `FramePump` (framework, Qt; после T1).
FILES: `.../frontend_module/bridge/frame_pump.py` (новый); `.../bridge/tests/test_frame_pump.py`; `frontend_module/DECISIONS.md`. DESIGN: `FramePump(QObject)` создаётся в Qt-потоке с `mailbox` и `sink(key, item)`. `set_keys({key: fps_limit})` заводит `QTimer` на ключ, период `1000 / clamp(fps_limit or 60, 1, 60)` мс; обработчик делает один `take(key)` и один `sink`. Ключ без настройки — таймер по умолчанию 30 Гц. Ни один Signal кадр не несёт, поток-источник Qt не трогает. Счётчики на ключ: `shown`, `max_age_ms`, `busy_ms_total`, `errors`; исключение `sink` не останавливает насос. REDS: `test_pump_delivers_only_latest_after_blocked_loop` (300 put, цикл заблокирован 0,5 с → вызовов ≤ 2, последний номер 300), `test_rate_capped_by_fps_limit` (200 put/с, предел 20, 1 с → 14..22), `test_slow_key_not_starved_by_fast_key`, `test_put_posts_no_qt_event`, `test_sink_exception_does_not_stop_pump`, `test_unconfigured_key_served_at_default_rate`, `test_zero_fps_limit_capped_at_60`, `test_stop_no_calls_after`. Reviewer: вызов `sink` прямо из `put` должен убить тесты частоты и «нет события».

### T3. Подключение в прототипе (после T2).
FILES: `multiprocess_prototype/frontend/bridge_impl.py`; `frontend/app.py`; `frontend/widgets/image_panel/recipe_displays.py`; `frontend/tests/test_frame_overload_real_objects.py` (новый); тесты `recipe_displays`; `multiprocess_prototype/docs/FRAME_DELIVERY.md`. DESIGN: в `DataReceiverBridge.dispatch` (`bridge_impl.py:81-95`) ветка кадра делает `self.frame_mailbox.put(sender, msg_dict, nbytes)` без `_deliver.emit`; остальные виды не меняются; ветка кадра в `_on_deliver` остаётся (FREEZE). `build_panel_displays` (`recipe_displays.py:64-72`) добавляет `"fps_limit": float(defn.get("fps_limit", 30.0))`. `_rebuild_displays` (`app.py:1110-1129`) строит `{sender: fps_limit его дисплея}` и зовёт `pump.set_keys`; `sink` насоса = существующий `_on_frame_received` (`app.py:1149`). Кадр до установки колбэка остаётся в ящике и показывается первым тиком. REDS: `test_overload_memory_stays_bounded` (4 sender, 400 кадр/с 1440×1080×3, 5 с: `max_bytes_held <= 18662400`, рост private ≤ 100 МБ), `test_overload_last_frame_reaches_screen` (номер кадра в пикселе; после остановки на каждом слоте номер 2000), `test_qt_timer_ticks_under_overload` (≥ 8 тиков/с), `test_slow_sender_shown_while_fast_floods` (1 кадр/с рядом с 300/с → показано ≥ 4 за 5 с), `test_frame_before_callback_shown_after`, `test_fps_limit_read_from_recipe` (20.0), `test_missing_fps_limit_defaults_30`, `test_state_delta_delivery_unchanged`, `test_no_aliasing_22hz_source_limit_20` (3 с → 45..63, не 33). Reviewer: возврат `_deliver.emit` должен убить тесты памяти и таймера (ожидаемый красный: +457 МБ/с, 1 тик/с); замена ящика кольцом 64 МБ — тесты последнего кадра и медленного sender.

### T4. Метрики и честные надписи (после T3).
FILES: `frontend/frame_intake.py` (новый); `frontend/process.py`; `frontend/app.py`; `frontend/windows/main_window.py`; `frontend/tests/test_frame_intake_metrics.py`. DESIGN: тело `_data_receiver_loop` (`process.py:255-307`) переносится в `FrameIntake.run_loop`; воркер создаётся на этом методе, `get_cycle_metrics()` отдаёт `frames_in, batches, superseded, pending, bytes_held, max_bytes_held, shown, max_frame_age_ms, pump_busy_share, qt_pending`. `data_receiver.success` остаётся, добавляется счёт по кадрам. `update_status` показывает `Latency: —`, пока замера нет. REDS: `test_metrics_have_literal_keys`, `test_frames_in_counts_messages_not_batches` (пачка 7 → 7 и 1), `test_superseded_grows_when_qt_blocked`, `test_worker_status_contains_intake_metrics` (настоящий `WorkerManager`), `test_latency_label_dash_without_sample`, `test_qt_pending_returns_to_zero`.

### T6. Дешёвый кадр (после T3, параллельно с T4).
FILES: `image_panel/presenter.py`; `image_panel/display_slot.py`; их тесты. DESIGN: `on_frame` (`presenter.py:139-155`) уменьшает кадр `cv2.resize(INTER_AREA)` до размера метки слота до шага BGR→RGB и QPixmap; при `resizeEvent` слот перерисовывается из сырого кадра (`_last_frames`), не из уменьшенного pixmap (урок `feedback_display_rescale_must_not_degrade_the_frame`). REDS: `test_on_frame_median_below_3ms_1440x1080`, `test_resize_roundtrip_keeps_quality`, `test_gray_frame_supported`. ACCEPTANCE: медиана ≤ 3 мс (сейчас 7,4); цель — оценка, не замер.

### T5. Отложенная копия (после T4).
FILES: `frontend/process.py`; `frontend/bridge_impl.py`; `frontend/app.py`; тесты; при нужде `frame_shm_middleware.py`. DESIGN: gui не регистрирует `on_receive` как middleware роутера (`process.py:55`), `register_frame_middleware` (`:60`) остаётся. `dispatch` узнаёт кадр по `data["_shm_refs"]["frame"]` или по inline `frame`. `sink` насоса зовёт `self._recv_frame_mw.on_receive(msg)` в Qt-потоке перед показом; `None` → `restore_dropped`. Читает один поток. REDS: `test_only_shown_frames_are_copied` (400 на входе, ≤ 25 показано → `shm_bytes_read <= 25 * 4665600`), `test_stale_ref_counted_next_frame_shown`, `test_inline_frame_still_shown`, `test_batch_of_142_holds_no_frame_bytes`, `test_one_unreadable_ref_drops_whole_message`.

### T7. Рецепт для стенда (параллельно).
FILES: `multiprocess_prototype/recipes/gui_overload_synth.yaml` (новый); `recipes/tests/test_gui_overload_synth_recipe.py`. DESIGN: 4 процесса с `SyntheticFrameSourcePlugin` (`Plugins/sources/synthetic_frame_source/plugin.py:41`): 2 × 1440×1080 и 2 × 1280×1024, по 50 Гц (200 кадр/с), 4 дисплея `fps_limit` 30/30/20/20, gui = `GuiProcess`, железа нет. REDS: `test_recipe_validates`, `test_four_sources_routed_to_four_displays`, `test_no_hardware_plugins`.

Отложено: перевод `RemoteFrameSource` на `LatestMailbox` (решение владельца, п. 6).

## План стенда без подсветки

Синтетический источник в проекте есть (плагин выше; рецепты `g1_perf_probe.yaml`, `dualcam_synth.yaml`, `bridge_synth.yaml` — 640×480, 30 Гц). Рецепта с четырьмя большими потоками в окно нет — нужен T7. Ответ на вопрос investigator-а: **синтетический источник, самотриггер считывателей не включать.**
1. До правки, HEAD как есть, рецепт T7, ступени 50/100/150/200 кадр/с числом работающих источников, по 60 с. Каждые 10 с: `introspect_memory` gui, `get_status` gui (`cpu.seconds_total`), `introspect_router_stats` gui (`shm_bytes_read / размер кадра` = точная частота; `frame_stale_drops`, `middleware_dropped`); qt-mcp: текст FPS и два `qt_screenshot` слота с интервалом 2 с. Ожидание: выше порога RSS растёт ≥ 30 МБ/с (закрывает «порог живого окна не измерен»). Стоп: RSS gui > 3 ГБ или свободно < 3 ГБ → `system_shutdown`.
2. После T3: та же лестница. Проход: дрейф RSS ≤ 50 МБ за 5 мин на 200/с; снимки слота различаются; `shown` на слот в пределах `fps_limit` ±15 %; `max_frame_age_ms` ≤ 150; gui ≤ 1,0 ядра; RSS соседей без изменений.
3. `hikvision_id3013_quad_hw` 5 мин: картинка камер есть, регрессии нет. В приборы не писать.
4. Прогон 30 мин на 200/с: дрейф RSS ≤ 50 МБ.

## Решения владельца

1. `fps_limit` главной панели становится настоящим: показ в 23 рецептах ограничится их значениями. `fps_limit: 0` («без ограничения», `display_module/interfaces.py:48`) против страховочного потолка 60 Гц.
2. Строка FPS: «принято» (сейчас, только первичный слот) или «показано» по слотам плюс «вытеснено».
3. Бюджет памяти процесса в рецепте и реакция supervision (предупреждение / fault / перезапуск только виновника): схема и поведение, отдельный план.
4. `ring_buffer_blocks`, `width`, `height`, `format` в `displays[]`: оставить с пометкой «только SHM-привязка» или убрать (миграция рецептов).
5. Штамп `capture_ts` в источниках или снятие надписи Latency.
6. Переводить ли `RemoteFrameSource` на общий ящик (трогает рабочий модуль с тестами).

## Что оставил открытым / ненадёжно

- Все запуски offscreen, 8-10 с. Порог живого окна и связь с 7 ГБ в quad2 не воспроизведены; стенд не поднимался.
- Вытягивание проверено черновиком с одним таймером на все ключи, не `FramePump` с таймером на ключ: при номинале 25 Гц вышло 19 Гц, причина не разобрана — T2 обязан измерить.
- T5 не прототипирован: потокобезопасность читателя SHM из Qt-потока и доля stale при выемке неизвестны. Для ограничения памяти T5 не нужен.
- Цель T6 (3 мс) и «90 % Qt-потока на 4 слота» — расчёт из 7,4 мс, не замер.
- Находка 5 — факт кода (`maxsize` очереди `gui_data` в рецепте не найден). Находка 3 и падение reader_2 — только числа стенда. Плато RSS — вывод из стенд-дока.
- `capture_ts`: искались три написания в четырёх деревьях. Поток одних state-дельт, `qt_event_bridge.py`, `cycle_metrics.py:59` не запускались.
- Может ли backend_ctl ставить источник на паузу для ступеней — не проверялось; иначе нужен второй рецепт на 100/с.
- Индекс qex устарел (2026-10-18), поиск шёл через `git grep`.
- Кандидат в урок: «байтовое кольцо между потоком и Qt ограничивает память, но не возвращает отрисовку; нужен последний на ключ и вытягивание».
