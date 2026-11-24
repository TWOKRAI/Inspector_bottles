# T3 (подключение ящика и насоса): предсказания инъекций лида, записаны ДО кода developer-а и ДО прогона (2026-11-24)

Worktree `.claude/worktrees/gfp-t3-dev` (ветка feat/gfp-t3-wiring, база bc82d9363 + принятый код T1 + код T2 + тесты слепого tester-а). Правимые модули: `multiprocess_prototype/frontend/bridge_impl.py` [B], `multiprocess_prototype/frontend/app.py` [A], `multiprocess_prototype/frontend/widgets/image_panel/recipe_displays.py` [R]. Два набора: [T] = слепой tester (`test_frame_overload_real_objects.py`: 7 REDS + 3 охранных + проверка помощника; `test_recipe_displays.py` с новыми тестами), [D] = тесты developer-а (`test_gui_process.py` — два переписанных теста dispatch на `bridge.frame_mailbox.take("")`; `test_frame_wiring_sender_vs_display.py` — тест sender≠id дисплея, ПО УКАЗАНИЮ ЛИДА, закрывает дыру: tester назвал дисплеи так же, как sender).

Исполнитель мутаций — developer T3 (владелец файлов); откат по sha256 от байтовой копии; Git Bash явно (не WSL). Мутации, заливающие кадры, гонять ТОЛЬКО через тесты tester-а с потолком private +500 МБ (хелпер прерывает продюсеров); перед ними убедиться, что потолок в хелпере действует. Класс гейта: файл перегрузки — medium; остальные — light; по одному файлу. Красный набор (минимум) ОБЯЗАН упасть; красные вне набора — «шире»; тест из набора, оставшийся зелёным, — находка.

| № | мутация | файл | красный набор (минимум) | примечание |
|---|---|---|---|---|
| G1 | возврат `_deliver.emit` в ветку кадра `dispatch` (кадр снова идёт через очередь Qt) | B | [T] test_overload_memory_stays_bounded; test_qt_timer_ticks_under_overload; test_state_delta_delivered_under_frame_flood | красный — по потолку памяти (рост >500 МБ, продюсеры прерваны, предусловие «заливка не прервана» не выполнено); шире: test_overload_last_frame_reaches_screen |
| G2 | вместо ящика кольцо 64 МБ drop-oldest (put выбрасывает старейший кадр при превышении) | B | [T] test_overload_last_frame_reaches_screen; test_slow_sender_shown_while_fast_floods | |
| G3 | `dispatch` возвращается, пока насос не создан (кадр до насоса теряется) | B/A | [T] test_frame_before_callback_shown_after | остальные зелёные |
| G4 | `fps_limit` не читается из рецепта (слот без ключа) | R | [T] test_fps_limit_read_from_recipe; test_extracts_id_label_enabled_position; шире: test_no_aliasing_22hz_source_limit_20 | |
| G5 | умолчание `fps_limit` не 30.0, а 0.0/None | R | [T] test_fps_limit_read_from_recipe (параметр «ключа нет»); test_extracts_id_label_enabled_position | |
| G6 | нечисловой `fps_limit` роняет `build_panel_displays` (float() без защиты) | R | [T] test_fps_limit_garbage_falls_back_to_30 (None, "abc", NaN) | |
| G7 | `set_keys` в `app.py` не вызывается | A | [T] test_no_aliasing_22hz_source_limit_20 (ключ идёт на скан 30 Гц: показано больше 63); [D] test_frame_wiring_sender_vs_display (fps не из рецепта) | |
| G8 | адаптер sink передаёт ключ вместо item (`lambda k, item: _on_frame_received(k)`) | A | [T] test_overload_last_frame_reaches_screen; test_no_aliasing_22hz_source_limit_20 | |
| G9 | фильтр «время только вперёд» (кадр со старшим `capture_ns` отбрасывается в слоте/адаптере) | A/B | [T] охранный test_frame_with_older_capture_ns_is_shown | |
| G10 | адаптер/насос портит item (удаляет `data`/`capture_ts`) | A | [T] охранный test_item_meta_reaches_sink | |
| G11 | ветка state в `dispatch` трогается (дельта состояния идёт в ящик/теряется) | B | [T] охранный test_state_delta_delivery_unchanged | |
| G12 | ключ ящика/насоса = id дисплея вместо sender | A/B | [D] test_frame_wiring_sender_vs_display (минимум); [T] НЕ ловит (дисплеи названы как sender) — подтвердить | это и есть дыра tester-а; ожидаю: [T] зелёные, [D] красный |
| G13 | `put` вернул False игнорируется неверно: `dispatch` бросает исключение при отказе ящика (65-й ключ) | B | [D] если есть тест на rejected; иначе — НЕТ красного (находка: дыра, добавить тест) | |
| G14 | насос создаётся ПОСЛЕ первого `_rebuild_displays()` | A | [T] test_no_aliasing_22hz_source_limit_20 или test_frame_before_callback_shown_after (первый `set_keys` не находит насоса) | |
| G15 | насос не останавливается по `aboutToQuit` | A | НЕТ красного ожидается (тест не покрывает: бриф записал пробел) | подтвердить как известный пробел, не провал |
| G16 | `frame_received.emit` оставлен в `dispatch` для кадров (двойная доставка) | B | [D] переписанные test_dispatch_frame_ready / test_dispatch_frame или [T] G1-набор | уточнить по факту |
| G17 | `test_gui_process.py`: возврат прежних ожиданий `frame_received` | — | не мутация кода, проверка: два переписанных теста красные на мутанте G16 | |

Критерий находки: (a) тест из красного набора остался зелёным; (b) sha256 после отката не совпал; (c) G12: если [T] красный — расхождение (тесты tester-а различают sender и id); если [D] зелёный — тест developer-а неверен; (d) G13: ни один тест не красный — дыра покрытия, developer добавляет тест; (e) G15: красный — расхождение (появился тест на остановку).
