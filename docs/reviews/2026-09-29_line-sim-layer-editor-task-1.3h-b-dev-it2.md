# Task 1.3h-b — исправления по ревью ит.1 (developer)

Ветка `feat/line-sim-layer-editor`, база b73afaa2. Ревью: `docs/reviews/2026-09-29_line-sim-layer-editor-task-1.3h-b-review-it1.md`.

## Что сделано

| Пункт | Где | Суть |
|---|---|---|
| MAJOR-1 | `plugin.py`, `_PRESET_SCRIPT` | `presetApplyEdit(name, mutate, deferLayout)`; стрелки (`presetShiftLayer(..., false, true)`) сразу делают «Отмену», форму и сдвиг битмапа, а раскладку просят одним `setTimeout` в `PRESET_KEY_LAYOUT_MS = 200` (каждое нажатие перевзводит таймер). Любая правка без `deferLayout` (жест move/rotate/scale) просит сразу и снимает висящий таймер. |
| MAJOR-2 | там же | `presetSpaceOnCanvas(e)`: пробел обрабатывается, только если `e.target` пуст, `presetCanvas` или `document.body`; тогда `preventDefault()` + `presetSpaceHeld`. Кнопка/поле — ничего. |
| MINOR-3 | там же | `presetLayerIndex` ищет имя в `collectPresetFromFields().layers` (при `presetState === null` — пустой список). |
| MAJOR-4 | `tests/page_offline.mjs` | `pointerId` у `fire`, `target`/`code`/`times`/`gap` у `key` (+ `out.pd` — вызовы `preventDefault`), новая операция `fire_el`. Существующие сценарии не тронуты. |
| Хазарды | `tests/test_hazards_1_3h_canvas.py` | 7 новых тестов; `test_stale_layout_reply...` перестроен на два жеста. |
| STATUS | `STATUS.md` | K11b не защищён намеренно + цена `preset.layout`. |

## Доказательства

- RED до правки `plugin.py`: `3 failed, 15 passed` — упали ровно `test_arrow_burst_requests_layout_once`,
  `test_space_on_canvas_prevents_default_and_on_button_is_ignored`, `test_rename_in_form_keeps_layer_editable`
  (остальные четыре — охранники, зелёные по замыслу).
- Break-injection охранников (throwaway `ls13hb-dev/test_brk.py`, `monkeypatch` на `_PRESET_SCRIPT`, каждый слом применяется один раз, откат — сам monkeypatch):
  - K19 (убрана проверка `e.pointerId !== g.id` в pointerup) -> `test_pointerup_of_foreign_pointer_ignored` УПАЛ (поля [100,100]).
  - K20 (убран `presetKeyFromField(e)` в keydown) -> `test_arrow_from_input_does_not_move_layer` УПАЛ (поля [6,5]).
  - K9b (тело раскладки — `presetState` вместо `collectPresetFromFields()`) -> `test_field_change_rerequests_layout_with_typed_value` УПАЛ ([[5,5],[5,5]]).
  - CHG (снят обработчик change на `#presetLayers`) -> тот же тест УПАЛ ([[5,5]], один запрос).
  - K11a (снята проверка `seq` в ветке ответа) -> `test_stale_error_does_not_overwrite_fresh_success` УПАЛ (ошибка `HTTP 400` затёрла успех).
- `pytest Plugins/sim/pult_web/tests/` после правок: `120 passed, 10 warnings in 131.23s` (полный каталог; затем после переноса двух длинных строк теста — канвас + 1.2h: `41 passed`).
- `ruff check` по `plugin.py` и файлу хазардов — чисто; `node --check page_offline.mjs` — ок.
- Break-injection самих изменений (debounce, пробел, переименование) — за лидом; моё доказательство — RED до правки.

## Что я истолковал, а не выполнил буквально

- Таймер стрелок снимается в `presetApplyEdit` для ЛЮБОЙ правки без `deferLayout` (включая rotate/scale), а не только для move-жеста: путь общий.
- K11a перестроен на два жеста (drag на 1 px и drag на 10 px), а не на две стрелки: стрелки теперь дают один запрос, «медленный invalid, потом быстрый ok» получить нечем.
- Тест пробела прогоняет ещё и `target: INPUT` (поле отсекается прежней `presetKeyFromField`, не новым кодом) — как дополнительный контроль.
- В тесте переименования проверяю «выбрана ровно одна строка формы», а не имя в строке: подпись `<b>` строки берётся из `presetState`, пока форма не перерисована.
- `document.body` в харнессе нет (`undefined`): ветка «target отсутствует» и ветка `document.body` в тестах не различаются.

## Что оставил открытым / ненадёжно

- `btnPresetUndo` и обработчик `change` на `#presetLayers` не снимают висящий таймер стрелок: после «Отмена» в пределах 200 мс уйдёт ещё один лишний запрос раскладки по текущим полям (безвредно, номер запроса отсекает старые ответы; не проверял живьём).
- Тест серии стрелок держится на том, что 20 нажатий `gap: 0` укладываются в паузы < 200 мс; на сильно нагруженной машине возможен второй запрос (не наблюдал, порог не измерял).
- Настоящего браузера нет: `preventDefault` пробела, прокрутка страницы, реальное всплытие `change` проверены только в харнессе.
- `pytest.mark.timeout` в файлах тестов — «Unknown mark» (плагина pytest-timeout нет), таймауты фактически не действуют; было до меня.
- В выводе pytest видны `WinError 10054` из потоков сервера (ранние отказы 403/415/400) — известный флак, не гонялся, тесты зелёные.
- pre_report_gate/venv в worktree не заводил (правило проекта: основной `.venv`, CPU torch); `VIRTUAL_ENV`-ловушка обойдена тем, что запуск шёл через `.venv/Scripts/python.exe` с `PYTHONPATH=$PWD` — совпадение путей кода проверил по падению RED-тестов на новом коде (RED воспроизвёлся до правки, GREEN после).
- Не тронуто (вне scope): NIT'ы (DPR, `willReadFrequently`, застрявший жест), README, `_read_command_body`.
