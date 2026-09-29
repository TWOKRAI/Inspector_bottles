# Task 1.3h-b — независимый tester, RED-приёмка канвы мышью (2026-09-29)

Worktree `ls-13hb-tester`, ветка `tests/ls-13hb-blind`, база `f1862c99`. Файлы не закоммичены (по брифу).
Model: claude-sonnet-5-5.

## Файлы
1. `Plugins/sim/pult_web/tests/test_acceptance_1_3h_canvas.py` — новый, 13 тестов (12 RED + 1 зелёная самопроверка харнесса).
2. `Plugins/sim/pult_web/tests/page_offline.mjs` — заглушки (2D-контекст с матрицей, Image + PNG-декодер, указатель/клавиатура,
   журнал fetch, classList/style, innerHTML сносит потомков) и сценарии `canvas_script`, `stub_selfcheck`; старые сценарии
   не тронуты (1.2h-тесты: 25 passed).

## Контракт для реализации (страница пинит ТОЛЬКО это; всё остальное — дело реализации)
====================================================================================
1. Разметка (в `_PRESET_SECTION`, один блок `<script>` в странице, как сейчас):
   `<canvas id="presetCanvas">`; `<input id="presetZoom" type="number" value="100">` (масштаб в
   ПРОЦЕНТАХ); элемент `id="presetLayoutError"` — пустой `textContent` при успешной раскладке,
   непустой при отказе `preset.layout` (пишется через `textContent`, не `innerHTML`).
2. Раскладка. Страница шлёт `POST /api/preset/layout` с телом, где `preset` — ТЕКУЩЕЕ состояние
   правки (`presetState`/поля формы, не то, что на диске): при загрузке пресета и один раз после
   каждого отпускания жеста. Ответ 1.3h-a: `{status, canvas_px, layers: [{name, png_b64, center_px,
   size_px, origin_px}]}` в порядке снизу вверх. Слой рисуется так: `img = new Image()`;
   `img.src = "data:image/png;base64," + png_b64` (другие источники харнесс не декодирует);
   `ctx.drawImage(img, ...)` прямо в 2D-контекст `#presetCanvas`; слой ставится левым верхним углом
   в `origin_px` (не пересчитывается из `center_px`).
3. Геометрия. `canvas.width/height` страница читает как размер канвы в пикселях (CSS px == пиксели
   битмапа, devicePixelRatio == 1). При 100 % и нетронутой панораме центр объекта (`canvas_px / 2`)
   лежит в центре канвы `(width/2, height/2)`, 1 px объекта == 1 px канвы. Масштаб Z % — вокруг центра
   канвы: 1 px объекта == Z/100 px канвы. Ось Y вниз. Слой без пары в пресете (авто-слой `base`)
   рисуется, но не редактируется; слои пресета сопоставляются с раскладкой по `name`.
4. Масштаб задаётся так: `presetZoom.value = "<проценты>"` и события `input` и `change` на этом поле.
5. Указатель — события `pointerdown` / `pointermove` / `pointerup` на самом `#presetCanvas`.
   Координата — `e.offsetX / e.offsetY` в пикселях канвы (харнесс даёт и `clientX/Y`, `pageX/Y`,
   `x/y` теми же числами; `getBoundingClientRect()` == `{left: 0, top: 0}`); также `e.button`
   (0 — левая), `e.buttons`, `e.pointerId`. `pointerdown` на пикселе слоя, непрозрачном по альфе
   (выбор — верхний слой с `alpha > 0` под курсором, через `getImageData`; прозрачный пиксель верхнего
   слоя -> слой под ним), выбирает слой и начинает жест. Жест `pointerdown -> pointermove* ->
   pointerup`: на `pointerup` `offset_px` слоя += (экранная дельта / (Z/100)), поля формы
   `layer{i}_offset_x/_y` показывают новое значение, в стек «Отмена» кладётся РОВНО одна запись на
   жест (не по записи на `pointermove`; и не по флагу `presetDirty` 1.2h — тот кладёт снимок лишь на
   ПЕРВУЮ правку после сохранения, здесь нужна запись на каждый жест), уходит ровно один
   `POST /api/preset/layout`. Пока кнопка зажата, раскладка НЕ запрашивается. Клик без движения
   (`pointerdown` + `pointerup` в одной точке) выбирает слой и ничего не меняет.
6. Выбор. Строка формы выбранного слоя (`div` внутри `#presetLayers`; первый потомок — `<b>` с
   именем слоя, как в 1.2h) получает токен `selected` в `className` (либо через `classList`);
   выбрана ровно одна строка.
7. Клавиатура. `keydown` на `document`; `e.key` — `ArrowLeft/Right/Up/Down`, `e.shiftKey`. Выбранный
   слой сдвигается в `offset_px` на 1 px (с Shift — на 10 px), `ArrowDown` = `+y`; ровно одна запись
   «Отмена» на нажатие. Масштаб на шаг не влияет.
8. Форма 1.2h как есть: поля `layer{i}_offset_x/_y` (i — индекс в `presetState.layers`, НЕ в
   раскладке: `base` сдвигает индексы), кнопки `btnPresetUndo`, `btnPresetSave`; «Сохранить» шлёт
   `{preset, base_rev}` как в 1.2h; конфликт (HTTP 409) не теряет правку и запоминает `current_rev`.
9. Отказ `preset.layout` (HTTP 400 `invalid`, 504 на таймаут) -> непустой текст в
   `#presetLayoutError`; `presetState`, поля формы и запись «Отмена» от жеста остаются (в следующий
   commit правка попадает).
Не пинится (нет ограничений): ручки поворота/масштаба (геометрия ручек — дело реализации; критерий
плана про `angle_deg`/`scale` мышью этим файлом НЕ покрыт), колесо и панорама, рамка выбора, размер
канвы, порядок запросов раскладки при стрелках.

## Харнесс-факты (что реализация получает в тестах): `requestAnimationFrame` == `setTimeout(16)`;
доступны `setTimeout`, `Image`, `atob/btoa`, `Math`, `Promise`, `JSON`; методы рисования кроме
drawImage/clearRect/getImageData/putImageData/createImageData — пустышки; холсты из
`document.createElement("canvas")` — такие же программные (для попиксельного hit-test).

## RED-причина по тестам (команда лида, без реализации)
Все — «фичи нет»: страница не создаёт `Image`/не рисует на `#presetCanvas`, харнесс возвращает `waits=[{'n': 2, 'ok': False, 'seen': 0}]`.
- test_drag_zoom100_sets_offset, test_drag_zoom200_halves_screen_delta, test_one_gesture_one_undo,
  test_click_transparent_top_selects_below (n=3), test_commit_parity_base_rev_and_conflict_409, test_arrow_keys_1px_shift_10px_one_undo_each,
  test_base_layer_visible_not_editable, test_release_rerequests_layout, test_layout_..._edit_kept[invalid_after_release|timeout_after_release]
  -> AssertionError в `_assert_drawn`: «страница не нарисовала слои раскладки на #presetCanvas».
- test_layout_..._edit_kept[invalid_first_request|timeout_first_request] -> `assert '' != ''`: #presetLayoutError пуст, страница раскладку не просит.
- test_harness_selfcheck_alpha_stub_is_not_always_opaque -> ЗЕЛЁНЫЙ уже сейчас (доказывает, что getImageData не «всегда непрозрачно»).

## Вывод команды лида
`12 failed, 25 passed` (1.3h-canvas: 12 red + 1 green; 1.2h acceptance+hazards: 25 green). Нюанс — см. «Флак».

## Проверка, что тесты достижимы GREEN и ловят поломки (throwaway, вне репо)
`C:/Users/INNOTECH/AppData/Local/Temp/claude/ls13hb/ref/ref_impl.py` — эталон страницы (pytest-плагин `-p ref_impl`, патчит
`_PRESET_SECTION/_PRESET_SCRIPT`), 13/13 passed. Мутации эталона (предсказание -> результат):
| MUT | предсказано красным | получено |
|---|---|---|
| alpha (выбор по bbox) | click_transparent | click_transparent |
| nozoom (без деления на zoom) | zoom200 | zoom200 |
| double_undo (две записи на жест) | one_gesture_one_undo, arrow_keys | те же два |
| base_edit (base -> индекс 0) | base_layer_visible_not_editable | он же |
| move_layout (запрос на каждое движение) | release_rerequests | он же |
| no_preset (в layout нет preset) | release_rerequests | он же |
| no_errtext (нет текста ошибки) | 4 параметра edit_kept | 4 параметра |
| click_undo (запись undo на клик без движения) | не предсказывал явно | one_gesture_one_undo (2-жестовая цепочка ловит) |
| arrow_step (Shift = 5 px) | arrow_keys | он же |

## Флак (не мой код)
`test_hazards_1_2h_preset.py::test_preset_commit_content_type_guard_still_applies` упал в 3 из ~7 полных прогонов команды лида:
`ConnectionAbortedError: [WinError 10053]` в `urlopen` (415 без чтения тела -> RST на Windows). В прогонах 1.2h-файлов БЕЗ моего
файла — 0 из 4; одиночный тест после моего файла — 0 из 4. Причинность не доказана; тест pure-HTTP и `page_offline` не использует.

## Что я истолковал, а не выполнил буквально
- Контракт лида «pointer coords via offsetX/offsetY… similar»: ввёл координаты от центра канвы + зум вокруг центра канвы, `origin_px`,
  `presetZoom`, `presetLayoutError`, `selected` в className — всё это мои решения (пункты 1-9 контракта).
- Пинится, чего в плане нет: layout-запрос несёт `preset` (иначе после жеста раскладка устарела), ни одного layout-запроса пока кнопка
  зажата, запись undo на КАЖДЫЙ жест (в 1.2h флаг presetDirty пишет только первую правку — реализации придётся отойти от него),
  ключевые события на `document`, pointer-события на самом canvas.
- Оба критерия зума/дрэга ставят жест на непрозрачный центр `cap` (с overlap-стартом для второго жеста).
- Опциональные тесты ручек (`angle_deg`, `scale`) НЕ писал: геометрия ручек не пинится без перебора.

## Что оставил открытым / ненадёжно
- Маршрут `/api/preset/layout` имеет дефолтный потолок тела 4096 байт (`_PRESET_ROUTES`: `None`): страница шлёт весь `preset`, реальный
  пресет со слоями и `augment` может превысить -> 413 и «раскладка недоступна». Тест этого не ловит (мой пресет мал). Решение лида.
- Правка на клик/`pointerup` с нулевой дельтой: «не пишет запись undo» пинится только косвенно (мутация click_undo поймана лишь
  двухжестовой цепочкой; сама по себе такая запись при одном жесте неотличима).
- Заглушка `getImageData` проверена самопроверкой (translate/scale), но rotate-ветка drawImage не покрыта тестом; в браузере
  реальные различия (cross-origin taint, DPR != 1, subpixel `offsetX`) харнессом не видны — приёмка на живом стенде обязательна.
- Реализация может слушать `mousedown` вместо `pointerdown` или вешать move/up на window — тесты этого не поддержат (контракт п.5).
- Ожидание слоёв — «>= n разных src на основной канве»; страница, рисующая через offscreen-буфер, красна по контракту п.2.
- pytest-timeout в проекте не установлен (предупреждение «Unknown pytest.mark.timeout»): страховка — timeout=30 на node-subprocess и watchdog 20 с в харнессе.
- Hook `pre_report_gate` venv в worktree не требовал; venv не создавал.

Как читал `_PRESET_SCRIPT` 1.2h (нужен для ids формы) и бэкенд `render_layout`/маршрут layout (1.3h-a) — они уже в дереве коммита
`f1862c99`; реализации 1.3h-b в дереве нет, `ls-layer`/`ls-13h-tester` и главный checkout не открывались.
