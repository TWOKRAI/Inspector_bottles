# T6 (дешёвый кадр панели): предсказания инъекций лида, записаны ДО кода developer-а и ДО прогона (2026-11-24)

Worktree `.claude/worktrees/gfp-t6-dev` (ветка feat/gfp-t6-cheap-frame, база bc82d9363). Правимые модули: `multiprocess_prototype/frontend/widgets/image_panel/presenter.py` [P], `display_slot.py` [S]. Два набора: [T] = слепой tester (`test_cheap_frame_contract.py`, 9 тестов: 6 красных + 3 охранных на HEAD, sha256 b0e7b813…9b8c), [D] = developer (`test_cheap_frame.py`: тест времени, шпионы; 2 красных + 1 охранный). Регресс: `test_display_slot_resize.py` (12), `test_on_frame_shapes.py` (4), `frontend/tests/test_image_panel.py` (26), `test_set_displays.py` (8), `test_frame_guard_contract.py` (56, medium).

Исполнитель — developer T6; откат по sha256; Git Bash. Красный набор ОБЯЗАН упасть; зелёный тест из набора — находка. Решения developer-а о форме колбэка и пути перерисовки идут в матрицу.

| № | мутация | файл | красный набор (минимум) | примечание |
|---|---|---|---|---|
| L1 | `cv2.resize` убран (BGR→RGB полного кадра) | P | [D] test_on_frame_median_below_3ms_1440x1080; [D] test_frame_resized_to_slot_size_before_conversion; [T] test_first_show_equals_inter_area_reference, test_gray_frame_supported (размер pixmap 1440x1080) | |
| L2 | `cv2.resize` после BGR→RGB | P | [D] test_on_frame_median_below_3ms_1440x1080; проверка `is` первого аргумента | порядок кроме времени не наблюдается |
| L3 | интерполяция `INTER_LINEAR` вместо `INTER_AREA` | P | [T] test_first_show_equals_inter_area_reference; test_nonstandard_aspect…; test_resize_roundtrip_keeps_quality | |
| L4 | ресайз слота перерисовывает из уменьшенного pixmap, а не из сырого кадра | P/S | [T] test_resize_roundtrip_keeps_quality (5 циклов) | |
| L5 | размер для `cv2.resize` = своё `round()`/`ceil()` | P | [T] test_nonstandard_aspect_equals_qsize_scaled_reference[1440x1080] | `int(w*k)` эквивалентен Qt — не мутант |
| L6 | кадр меньше слота увеличивается | P | [D] test_frame_smaller_than_slot_is_not_enlarged | |
| L7 | колбэк «обработал», слот не масштабирует (рост метки не доходит до экрана) | S | [T] test_growth_beyond_raw_goes_through_slot | |
| L8 | серый кадр (2D или (H, W, 1)) падает/уходит в отказ | P | [T] test_gray_frame_supported[gray_2d], [gray_hw1] | |
| L9 | колбэк воскрешает старый кадр после «Нет сигнала» | P/S | [T] test_resize_after_placeholder_keeps_placeholder | |
| L10 | колбэк воскрешает кадр после отвергнутого («Ошибка кадра») | P/S | [T] test_resize_after_rejected_frame_keeps_error_placeholder | |
| L11 | при заданном колбэке `resizeEvent` не вызывает `_show_scaled` при `False` (кадр без сырого в `_last_frames`) | S | [T] test_growth_beyond_raw_goes_through_slot или [12 слепых слота] test_display_slot_resize | уточнить по факту |
| L12 | `set_resize_callback` не вызывается при `register_slot` (колбэк не навешен) | P | [T] test_resize_roundtrip_keeps_quality; [T] test_growth_beyond_raw | |
| L13 | прямой `update_pixmap` мимо presenter при заданном колбэке (контракт docstring) | S | НЕТ красного ожидается — известный пробел (записан в «Открытом» T6) | не провал |
| L14 | пол метки 320x240 в `target_size()` убран | S | НЕТ красного ожидается (нижний предел защитный, не наблюдаем) | зафиксировать |

Критерий находки: (a) тест из красного набора остался зелёным; (b) sha256 после отката не совпал; (c) L13, L14 красные — расхождение; (d) L2: зелёный тест времени и `is` — порядок «до BGR→RGB» не защищён; (e) L11: если красных нет — дыра, developer добавляет тест.
