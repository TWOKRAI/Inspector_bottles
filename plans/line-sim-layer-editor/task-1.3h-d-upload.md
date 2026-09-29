# Task 1.3h-d — загрузка PNG из браузера (канал записи)

**Статус:** IN PROGRESS 2026-09-29. Заготовка — [task-1.3h-c-layers.md](task-1.3h-c-layers.md#заготовка-под-канал-записи--task-13h-d).
**Level:** Middle+ (Sonnet). **Assignee:** tester (слепой, до кода) → developer → лид (инъекции, стенд) → reviewer.
**Goal:** оператор выбирает PNG на своём диске, файл ложится в `sprites_dir`, слой из него добавляется тем же
путём, что из списка (`presetAddLayer(entry)`).

## Контракт

### Команда `preset.sprite_put` (`Plugins/sim/layer_preview`, процесс `layers`)

Тело `{name: str, png_b64: str}`. Порядок проверок и ответы:

| # | Проверка | Ответ |
|---|---|---|
| 1 | тело не dict; `name`/`png_b64` не строки | `bad_request` |
| 2 | `name`: пусто; содержит `/` или `\`; `.`/`..`; абсолютный или с диском (`C:x.png`); длиннее 128 | `bad_request` |
| 3 | `name` после замены символов вне `[\w.-]` (Unicode `\w`, кириллица остаётся) на `_`: суффикс не `.png` (без учёта регистра) или основа пустая/из одних `_` и `.`; зарезервированное имя Windows (`PureWindowsPath(name).is_reserved()`, `CON.png`, `nul.PNG`) | `bad_request` |
| 4 | `png_b64` не base64 (`b64decode(validate=True)`); декодированное > 6 МиБ (`SPRITE_PUT_MAX_BYTES = 6_291_456`) | `bad_request` |
| 5 | `sprites_dir` вне ограды — **раньше** существования (то же правило, что `preset.sprites`) | `bad_request` |
| 6 | `sprites_dir` нет / не каталог | `io_error` |
| 7 | файл с этим именем уже есть (на Windows — без учёта регистра, как ФС) | `conflict`, файл не тронут |
| 8 | байты не RGBA-картинка (`load_image_rgba` на временном файле; не PNG, битый, RGB без альфы) | `invalid`, в `sprites_dir` не остаётся ничего |
| 9 | сбой записи | `io_error`, временного файла не остаётся |

Успех: `{status: "ok", file: {path, sprite_source}}` — `file` строит `sprite_entry` (та же форма, что элемент
`files` у `preset.sprites`). Сохранённое имя — очищенное (п.3), не исходное.

Запись: `tempfile.mkstemp(dir=sprites_dir, suffix=".uploading")` → запись + `fsync` → `load_image_rgba(tmp)` →
`os.link(tmp, final)` (`FileExistsError` → `conflict`: гонка с внешним писателем не перезаписывает) → `unlink(tmp)`
в `finally`. `os.replace` не годится: он перезаписывает. `preset.sprites` суффикс `.uploading` не показывает.

### Маршрут `POST /api/preset/sprite_put` (`Plugins/sim/pult_web`)

Строка `_PRESET_ROUTES`: `("preset.sprite_put", "_layers_client", 9_437_184, 5.0)`. Потолок 9 МиБ — 413 до
чтения тела, как у остальных маршрутов. Тело форвардится как есть; код ошибки → HTTP по `_ERROR_CODE_TO_HTTP`
(`conflict` 409, `bad_request`/`invalid` 400, `io_error` 500) — после R-4 доходит живьём.

### Страница

`<input type="file" id="presetSpriteFile" accept="image/png">` рядом со списком спрайтов. На `change`:
`FileReader.readAsDataURL` → base64 без префикса `data:…;base64,` → `post("/api/preset/sprite_put",
{name: file.name, png_b64})`. Успех (`status === "ok"` и `file`) → `presetLoadSprites()` и `presetAddLayer(r.file)`.
Отказ → текст в `presetSpritesError` (`message || error || code`), слой не добавляется. После обработки —
`value = ""` (тот же файл можно выбрать снова) и фокус канве (урок F1 1.3h-c: фокус на контроле ловит Space/Enter).

## Acceptance criteria

- [ ] п.1–9 таблицы — каждый отказ своим кодом, после отказа содержимое `sprites_dir` побайтно прежнее
- [ ] успех: файл в `sprites_dir` побайтно равен присланному, `file` = `sprite_entry` сохранённого файла,
      `preset.sprites` сразу видит его, `.uploading` не остаётся
- [ ] `name` с `../`, `..\\`, абсолютный путь, `C:evil.png` — ничего не пишется вне `sprites_dir`
- [ ] маршрут: 413 на теле > 9 МиБ до вызова команды; `conflict` → 409, `invalid` → 400 на настоящем `DeviceHubClient`
- [ ] страница: успех добавляет слой с `sprite_source` из ответа; отказ показывает текст и слой не добавляет
- [ ] живой стенд: загрузка настоящего PNG через маршрут → слой на канве; повтор того же имени → 409

## Out of scope

Перезапись/удаление загруженных файлов; подкаталоги в `name`; открытие пульта наружу (пересматривает 1.3h-d
целиком); Д 1.3 «файлы по id»; R-5.

## Files

`Plugins/sim/layer_preview/{plugin.py,README.md,STATUS.md}`, `Plugins/sim/pult_web/{plugin.py,README.md,STATUS.md}`,
тесты — `Plugins/sim/layer_preview/tests/`, `Plugins/sim/pult_web/tests/`.
