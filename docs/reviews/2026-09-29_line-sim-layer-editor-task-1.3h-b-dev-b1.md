# Task 1.3h-b, B1 — клик по канве забирает фокус (developer)

Модель: claude-sonnet-5-5. Ветка `feat/line-sim-layer-editor`, база 8d914edc.

## Что сделано
- `plugin.py`: CSS `#presetCanvas:focus { outline: 1px dotted #888; }`; первой строкой `pointerdown` —
  `if (presetCanvas.focus) presetCanvas.focus({ preventScroll: true });` (до раннего return).
- `page_offline.mjs`: `focus(opts)` пишет вызов в `focusCalls` и ставит `doc.activeElement`; `doc.activeElement`
  по умолчанию `doc.body`; шаги `focus_el`, цель `key` = `"ACTIVE"`; снимок несёт `active` и копию `focusCalls`.
- Тест `test_canvas_pointerdown_takes_focus_so_space_pans_not_button` (слой и пустое место + разметка).
- `STATUS.md`: абзац B1.

## RED -> GREEN
- До правки plugin.py: `assert 'btnPresetUndo' == 'presetCanvas'` (фокус остался на кнопке).
- После: канва 35/35 (hazards + acceptance).
- Каталог `Plugins/sim/pult_web/tests/`: 122 passed, 2 failed — `test_acceptance_5_3a.py::test_negative_content_length_is_400_and_never_reaches_scene`
  и `test_pult_web_hazards.py::test_non_json_content_type_rejected_415` (известный сокет-флейк раннего отказа,
  чужая сессия); по отдельности оба проходят (2 passed).

## Истолковано, а не выполнено буквально
- `tabindex="0"` на `#presetCanvas` уже стоял в HEAD (коммит 7fbf6d68), поэтому в plugin.py добавлены только CSS
  и `focus()`; проверка разметки в тесте проходит и до правки — красным делает тест только проверка фокуса.
- Снимок харнесса берёт `focusCalls.slice()`: без копии первый прогон показал вызовы, случившиеся после снимка.
- Тест регулярным выражением ищет `tabindex="0"` в теге `<canvas id="presetCanvas">` по GET `/` стенда, а не в
  исходнике константы.

## Открыто / ненадёжно
- Реальное «пробел нажимает сфокусированную кнопку на keyup» харнесс не исполняет: тест доказывает перенос фокуса
  и то, что пробел с источником-канвой идёт в панораму, но не то, что браузер перестал жать кнопку. Только живая проверка лида.
- Место `focus()` пришпилено только относительно `if (!kind) return` (сценарий «пустое место» умрёт, если
  перенести focus ниже него). Ранний return `!presetLayout || presetGesture` тестом не покрыт: клик при
  не загруженной раскладке или во время чужого жеста на фокус не проверен (сценария нет, в харнессе не строил).
- CSS `:focus` outline — на глаз не смотрел (нет браузера); `:focus` для мыши может показать рамку в Chrome.
- Break-injection не делал (за лидом).
