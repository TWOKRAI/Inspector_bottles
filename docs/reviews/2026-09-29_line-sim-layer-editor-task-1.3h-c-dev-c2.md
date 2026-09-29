# Task 1.3h-c / c2 — pult_web: маршрут `/api/preset/sprites` и страница состава слоёв

Исполнитель: developer, модель Sonnet 5.5. Ветка `feat/ls-13hc-c2` (от `ba10183d`). План:
`plans/line-sim-layer-editor/task-1.3h-c-layers.md`.

## Что сделано (`Plugins/sim/pult_web/plugin.py`)

1. `_PRESET_ROUTES`: `"/api/preset/sprites": ("preset.sprites", "_layers_client", 4096, 5.0)`. `handle()`,
   `_read_command_body`, дренаж/linger не тронуты.
2. `_PRESET_SECTION`: строка с `<select id="presetSpriteSelect">`, шестью кнопками и `<span id="presetSpritesError">`.
3. `_PRESET_SCRIPT`:
   - `presetApplyLayersEdit(mutate)` — брат `presetApplyEdit` (сам он не менялся): снимок из полей, копия, `mutate(layers)`,
     ничего не изменилось -> return; иначе запись «Отмена», `presetState`, `presetDirty=false`, `renderPresetLayers()`,
     `presetScheduleDraw()`, снятие висящего `presetLayoutTimer`, немедленный `requestPresetLayout()`.
   - `presetLoadSprites()` (при загрузке и по кнопке), `presetFillSpriteSelect()`, `presetSelectedSpriteEntry()`,
     `presetLayerStem`, `presetUniqueLayerName`, `presetAddLayer(entry)`, `presetDeleteLayer`, `presetMoveLayer(delta)`,
     `presetReplaceSprite(entry)` и обработчики кнопок (`onclick`).
4. README/STATUS пульта: абзац «Состав слоёв», строка маршрута в таблице, строка в таблице STATUS.

## Прогоны (из корня worktree, `PYTHONPATH=$PWD ../../../.venv/Scripts/python.exe -m pytest -q`)

- маршрут S4 + C1–C10 + 2 самопроверки: `31 passed` (5 + 26);
- хазарды автора `test_hazards_1_3h_c_layers.py`: `10 passed`;
- весь радиус `Plugins/sim/pult_web/tests`: `165 passed, 11 warnings in 197.64s` (early-reject флейков в этом прогоне не было);
- `ruff check` + `ruff format --check` по `plugin.py` и новому тесту — чисто.

## Хазарды автора и мои инъекции (предсказание -> факт)

| Свойство | Как сломано | Ожидал упавшими | Упало |
|---|---|---|---|
| операция снимает таймер стрелок | убран блок `clearTimeout` в `presetApplyLayersEdit` | `test_operation_cancels_pending_arrow_timer_single_request` | да (запросов 2 -> 3) |
| удаление обрывает жест | закомментирован `presetCancelGesture()` в `presetDeleteLayer` | `test_delete_during_drag_cancels_gesture_no_ghost_move_after_undo` | да (letter сдвинут на 80) |
| запоздалый ответ раскладки отбрасывается | оба `if (seq !== presetLayoutSeq) return;` убраны | оба `test_late_layout_reply_*` | да (2 failed) |

Инъекции я делал скриптовой правкой копии и вернул файл из бэкапа; они не заменяют инъекции лида. Остальные
хазарды (имена `base`/`damaged`/`constructor`/`v1.2`, занятость по полям формы, «Отмена» удаления первого/последнего,
«Заменить» тем же файлом, no-op не глотает запрос стрелки) инъекциями НЕ проверены.

## Что я истолковал, а не следовал буквально

- Предсказание «убран блок clearTimeout» проверено, но вторая инъекция (no-op не глотает запрос) не делалась.
- `presetAddLayer` без `layer_template` (список ни разу не принят) — ничего не добавляет и пишет в
  `presetSpritesError` «нет шаблона слоя: обновите список спрайтов»; в плане этого случая нет. Пункт `class://`
  при этом в `<select>` уже есть только после первого успешного списка (при отказе списка пункта нет).
- Успешное «Обновить список» сохраняет прежний выбор `<select>`, если такой `sprite_source` остался (иначе — первый пункт).
- `truncated: true` -> «показаны первые N», где N = `files.length` (сейчас 500, но число берётся из ответа).
- Расширение срезается ТОЛЬКО последнее и по последней точке (`v1.2.png` -> `v1.2`), любое, не только `.png`; пустая основа -> `layer`.
- После «Добавить»/«Удалить» выбор ставится внутри `mutate` (рендер идёт после него), а не отдельным шагом.
- «Удалить» обрывает ЛЮБОЙ идущий жест (включая панораму), а не только жест над удаляемым слоем: жесты не переживают удаление.

## Что я оставил открытым / не могу считать надёжным

- Живой Chrome не проверен, харнесс слеп к: фокусу кнопки после клика (Enter/Space по сфокусированной
  «Добавить»/«Удалить» повторит операцию; после «Удалить» выбора нет, поэтому повтор безвреден, а «Добавить» продублирует слой),
  реальным `change`/`input` у `<select>` (модель `<select>` в харнессе принята на веру), сохранению выбора при пересборке `<option>`,
  кириллице и пробелам в подписях. Я НЕ переносил фокус на канву после кнопок — это решение для лида/Chrome.
- Удалённый/переставленный слой остаётся нарисованным на канве старой раскладки до ответа `preset.layout` (битмап не
  пересобирается локально); при отказе раскладки (`invalid`) картинка остаётся прежней, пока не придёт успешный ответ.
- После «Отмены» добавления выбор указывает на имя исчезнувшего слоя (кнопки при этом инертны — индекс -1), как и в 1.3h-b.
- В логе хазарда с задержанными ответами встречается `ConnectionResetError [WinError 10054]` из потока сервера —
  шум закрытия соединения при выходе node, тесты зелёные; это НЕ известный early-reject флейк, а побочный эффект
  задержанных ответов.
- Два хазарда-«зеркала» зависят от времени (задержка ответа 1 с, пауза 1.8 с): на сильно загруженной машине запас может стать тоньше.
- Бэкенд `preset.sprites` в моём дереве отсутствует: всё проверено на двойниках процессов.

Boundary: task closed. /compact (focus: files + tests + plan path).
