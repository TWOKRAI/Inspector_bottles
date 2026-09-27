# Ревью Task 1.2a — команды пресета `scene_source` (редактор слоёв)

**Вердикт: REQUEST_CHANGES (итерация 1 из 2).** Блокеров нет; четыре SHOULD (S1–S3 — обязательно) закрыть до 1.2h (HTML-клиент строится
прямо на них), остальное — NIT.

- Скоуп: `git diff ace3f81b..11513087 -- Plugins/sim/scene_source Services/line_sim` (ветка `feat/line-sim-layer-editor`, worktree `ls-layer`).
- Воспроизведение: `PYTHONPATH=$PWD .venv/bin/python -m pytest Services/line_sim/tests Plugins/sim/scene_source -q --tb=short`
  → `324 passed, 1 skipped in 12.08s`; `ruff check -q` на изменённых файлах — чисто; `secrets_audit.py --root Plugins/sim/scene_source` — `findings: []`.
- Инъекции K1–K9 лида не повторял. Все замеры ниже — скретч-скрипты на реальном пресете: `letters_layered.yaml`
  (с комментариями, пути переписаны на локальные), каталог собран `make_font_letters` из macOS `Arial.ttf` + `Arial Bold.ttf`,
  буквы `АКБВ`, `--size-px 300`. Плагин — фейковый ctx (MagicMock + fake StateProxy), как в тестах `scene_source`.
- qex недоступен (по брифу) — поиск вызывающих `Grep`'ом.

## Находки

### S1 (SHOULD, IPC) — `preset.preview` держит `message_processor` всего процесса; время не ограничено лимитами seeds/tile

Команды исполняются синхронно на единственном потоке `message_processor`
(`router_manager.py:1290` `_dispatch_command` → `cm.handle_command`), и тот же поток дренирует очередь `state`
(`system_threads.py:64-71`) — то есть дельты энкодера `sim.belt.encoder` тоже. Замеры:

| Вход | Время | JSON ответа |
|---|---|---|
| `preview {}` (8×160), Arial 300 px | медиана 93.8 мс | 79 242 Б |
| `seeds=0..15, tile_px=256`, static | 194.9 мс | 286 780 Б |
| то же, слои `augmented` (примеры из комментариев пресета) | 222.3 мс | 321 122 Б |
| то же, спрайты 1200 px (`--size-px 1200`) | **2 605 мс** | 208 076 Б |

Разбивка (300 px): `ObjectFactory()` 7.4 мс, 16× `make+render` 141.8 мс (объект 396×396 RGBA) — время определяет
размер спрайтов пресета, а его ничто не ограничивает.

`scene.job_done` за превью 16×256 (один поток-диспетчер, как `message_processor`): задержка медиана **189.1 мс**,
max 192.2 мс (5 прогонов). Из второго потока (только GIL) — 0.002 мс: блокирует именно сериализация команд, не замки
плагина. С 1200-px спрайтами — ≈2.6 с задержки `job_done` и дельт энкодера (порог `stale_ms` = 500 мс будет пробит;
по коду, вживую не мерил). Ответ 287–321 КБ — класс L-6 (64 КБ pipe).

Исправить (выбор за teamlead): (а) бюджет по пикселям — `sum(h*w)` объектов превью сверх N → `bad_request`, либо
даунскейл спрайтов до `tile_px` перед `make()`; (б) либо вынести рендер превью с `message_processor`. Минимум при
любом выборе — правдивые числа в README (см. D2).

### S2 (SHOULD, spec/UX) — движок не собрался в `configure()` → пресет нельзя починить через редактор

Вход: `letters_layered.yaml` с опечаткой `sprite_source: ../typo_disk.png`. Наблюдение:
`engine built: False`; `preset.get` → `ok`, `class_names: []`; `preset.preview` исправленного пресета → `ok`;
`preset.commit` того же пресета → `{'status': 'error', 'code': 'invalid', 'message': 'preset.commit: движок сцены не запущен…'}`,
файл не тронут. Редактор покажет «пресет невалиден» для пресета, который только что превьюнулся, — выход только
правкой YAML руками и рестартом. Исправить: писать файл и отвечать отдельным кодом/флагом (`{"status": "ok", "rev", "applied": false}` или
`code: "engine_down"`, «нужен рестарт»), либо собирать спавнер/компоновщик лениво на первом успешном commit.

### S3 (SHOULD, docs + security-suspected) — «клиент не выбирает, откуда читать картинки» — ложь

Докстринг `cmd_preset_commit` (`plugin.py`, «`base_dir` клиента ИГНОРИРУЕТСЯ — … клиент не выбирает, откуда читать
картинки»). Вход: `preview` с `layers[0].sprite_source` = абсолютный путь к PNG вне каталога пресета → `ok`;
`"../../outside/secret.png"` → `ok`; `/etc/hosts` → `Не удалось прочитать изображение: /etc/hosts`; `/nonexistent/x.png`
→ `[Errno 2] No such file…` (оракул существования файла). Принудительный `base_dir` ограничивает только база
относительных строк, не место чтения. Эксплуатация — **предположение**: нужен маршрут 1.2h; `pult_web` в
`apps/line_sim/pipeline.yaml` на `127.0.0.1`. Исправить: либо ограничить resolve-путь корнем репозитория
(`is_relative_to(_REPO_ROOT)`, `letters_layered.yaml` сам ссылается на `../../../data/…`, так что каталог пресета —
слишком узко), либо переписать докстринг и вынести предел в README как требование к 1.2h.

### S4 (SHOULD, quality) — первый commit стирает комментарии, даже без изменений

Вход: `get` → `commit(get.preset, get.rev)` без правок. Наблюдение: `rev changed: True`, 3 238 → 488 байт, строк с `#`
38 → 0, в файл развёрнуты дефолты (`offset_px`, `angle_deg`, `scale`, `augment: null`, `defect_probability` у каждого
слоя). Второй такой же commit идемпотентен (`rev` тот же, байты те же). Для `letters_layered.yaml`: исчезают команда
сборки каталога и закомментированные примеры `augment` — ровно то, с чего пользователь редактора начнёт; файл в git,
так что восстановимо, но diff шумный. Дешёвое смягчение: (1) под замком после сверки `rev` — если
`from_yaml(path).to_dict() == preset.to_dict()`, ответ `ok` с текущим `rev` без записи и без подмены фабрики;
(2) прозу из `letters_layered.yaml` перенести в `Services/line_sim/presets/README.md`. ruamel — позже (Ф7, как в докстринге `to_yaml`).

### NIT

- **N1 — `class_names` в `get` отстают от файла до следующего `produce()`.** Вход: commit с `catalog_dir: ../other`
  (класс `X`), `get` без кадра → `catalog_dir=../other`, `class_names=['А','Б','В','К']`; после одного `produce()` → `['X']`.
  Окно — кадр, пока лента идёт; бесконечно, если `produce()` не зовётся. Разорванного состояния нет: `_live_factory` —
  атомарная замена ссылки после `set_factory`, `class_names` фабрики неизменны.
- **N2 — kill между записью и `os.replace` оставляет `tmp610hux9e.yaml` рядом с пресетом** (замер: `os.replace` → `os._exit(9)`).
  Валидный на вид пресет попадёт в любой `glob("*.yaml")` (список пресетов в 1.2h). Докстринг `_write_preset_atomic`
  «Любой сбой — tmp удаляется» верен только для исключений. Исправить: `prefix=".", suffix=".tmp"`.
- **N3 — пресет 0444 перезаписывается.** Вход: `chmod 444`, commit → `ok`, красный в файле, mode остался `0o444`;
  обычный `open(..., "a")` → `PermissionError`. `os.replace` в записываемом каталоге обходит защиту файла.
  Исправить: `os.access(path, os.W_OK)` под замком → `io_error`.
- **N4 — перенос форс-брака в `set_factory` не атомарен против чужого потока.** Сейчас производственных вызывающих
  `force_defect_next()` нет (grep: только `factory.py`/`spawner.py`), гонки нет. Если появится команда «выпусти брак»
  из потока команд — нажатие между проверкой `force_defect_pending` и `self._factory = factory` потеряется. Одна строка в
  докстринге `set_factory` о том, что Pre касается и `force_defect_next()`.
- **N5 — `rev` версирует только байты YAML.** Подмена `disk.png` на месте не меняет `rev` и не доходит до живой
  фабрики до следующего commit. TOCTOU «проверил → под замком» на YAML закрыт (`rev` сверяется под замком, проигравший
  получает `conflict` до передачи фабрики), на картинках его нет потому, что картинки не версируются вовсе. Строка в README.
- **N6 — `get` не говорит, что живёт на ленте.** При override `defect_probability` или после правки файла мимо
  команды редактор показывает файл, а лента крутит другое; признака (`live_rev`/`defect_override`) в ответе нет.

## Документы (D)

- **D1** — докстринг `cmd_preset_commit` (S3) и `_write_preset_atomic` (N2): утверждения ложны при запуске.
- **D2** — README `scene_source` и DONE-блок плана: «8 seed по 160 px: ~12 КБ JSON, ~12 мс (на фикстуре)». На реальном
  пресете — 79 КБ / 94 мс (в 6.6× больше), максимум 16×256 — 287–321 КБ / 195–222 мс, с крупными спрайтами — секунды.
  План требовал замер для L-6: число должно быть реальное и максимальное.
- Проверены и верны: сверка `rev` + запись под одним замком; `deque(maxlen=1)` (последний commit побеждает, согласован
  с последней записью файла — `append` под замком); `get` читает `rev` раньше пресета; превью не трогает живую фабрику,
  `self._rng`, файл и `rev` (общих кэшей в `Services/line_sim/core` нет — grep `lru_cache|_cache`); `copymode`
  сохраняет 0644; `tiles[].layer_params` сериализуются в JSON.

## Что не проверено / в чём не уверен

- Блокировка `message_processor` установлена по коду (`router_manager.py`, `system_threads.py`) и симуляцией одним
  потоком-диспетчером, не на живом стенде `backend_ctl`; влияние на heartbeat/supervision процесса не мерил.
- Пороги S1 (сколько мс превью допустимо на живой ленте) — решение лида/владельца; я дал числа, не норму.
- Эксплуатация S3 зависит от маршрутов 1.2h, которых ещё нет.
- Free-threaded CPython (3.13t) не проверял: атомарность `deque.append/popleft` держу на GIL.

---

## Итерация 2 (2026-09-27)

**Вердикт: APPROVED с условием.** S1–S4, N2, N3 закрыты воспроизведением. Новое: F1 (SHOULD, фреймворк) — закрыть до
слияния ветки отдельным коммитом; остальное — NIT/D.

- Скоуп: `git diff 30197303..8245de31 -- Services/line_sim Plugins/sim multiprocess_framework/modules/recipe apps/line_sim`
  (22 файла, +1317/−325).
- Радиус: `pytest Services/line_sim/tests Plugins/sim multiprocess_framework/modules/recipe/tests apps/line_sim -q` →
  `659 passed, 7 skipped in 133.46s`. Прототипные вызывающие `yaml_io` (`multiprocess_prototype/recipes/tests`,
  `adapters/tests/test_recipe_store.py`, `test_catalogs.py`, `test_integration_assembly.py`,
  `frontend/.../pipeline/tests/test_save_recipe.py`, `frontend/.../recipes/tests`, `domain/tests/test_commands_apply.py`) →
  `303 passed, 9 skipped`. `ruff check -q` на изменённых `.py` — чисто.
- Инъекции L1–L7 лида не повторял. Скретч — фикстуры it.1 (Arial 300 px), но картинки перенесены В каталог пресета:
  ограда S3 (правильно) отвергает `../letters_font` вне корня репозитория — см. N7.

### Закрытие находок it.1

| # | Вход | Наблюдение it.2 | Итог |
|---|---|---|---|
| S1 | `SceneSourcePlugin.commands` | `preset.commit, preset.get, scene.job_done, scene.status, truth.reset, truth.status`; `LayerPreviewPlugin.commands` = `preset.preview` | закрыто |
| S1 | `layer_preview`, `{}` (8×160) | cold 146.9 мс, warm медиана 87.9 мс, JSON 79 242 Б | — |
| S1 | 16×160 / 16×256 / 9×160 / 16×114 | `bad_request` `len(seeds) * tile_px**2 = … > 204800`, 0.0 мс | бюджет работает |
| S1 | 16×113 | ok, 167.8 мс, JSON 100 292 Б | максимум JSON — не дефолт |
| S1 | спрайты 1200 px, `{}` | ok, warm медиана 1 269 мс | бюджет ограничивает тайл, не `make()` — N8 |
| S1 живой | 10× `camera scene.status` в покое и 10× на фоне непрерывных `layers preset.preview` | медиана 12.4 → 12.6 мс, max 21.8 → 16.1 мс | поток `camera` свободен |
| S2 | опечатка `typo_disk.png`, commit исправленного | `get.engine: False`; commit → `{ok, changed: True, applied: False, message: 'движок не запущен — применится после перезапуска'}`; файл переписан, опечатки нет, `_pending_factory` пуст | закрыто |
| S3 | `sprite_source` = абс. путь вне, `../../outside/…`, `/etc/hosts`, `/nonexistent/x.png`; `catalog_dir=/etc`; симлинк в каталоге пресета → наружу | commit и preview: `invalid`, один текст `preset: путь изображения вне разрешённых каталогов (…)`; путь внутри каталога — ok | закрыто, оракула нет |
| S4 | `get` → `commit` без правок | `{ok, rev, changed: False}`, байты и `mtime_ns` те же, фабрика не отдана | закрыто |
| S4 | правка только `defect_probability` | diff файла — одна строка `0.0 → 0.5`, `#`-строк 38 → 38 | закрыто |
| S4 | правка `layers[0].color_rgb` | `#`-строк 38 → 23 (комментарии внутри `layers` уходят — задокументировано) | как заявлено |
| N2 | `os.replace` → `os._exit(9)` | остался `.letters_layered.yaml.113rh6ny.tmp` (0600), `glob("*.yaml")` его не видит | закрыто |
| N3 | 0444 + правка | `{error, io_error, 'preset.commit: файл только для чтения: …'}`, файл цел | закрыто |

### Живой стенд

`BackendHarness(build_app(apps/line_sim/app.yaml), port=8766)`; каталог — временный симлинк `data/line_sim/letter_catalog` →
главное дерево (удалён после прогона; порты 8766/5021/8091/8092 после стопа свободны; `errors.log`/`warnings.log`/
`critical.log` — 0 строк). Старт 1.6 с, стоп 1.1 с, 5 процессов.

- `layers preset.preview {}` через роутер: ok, 132 мс холодный / 80 мс, PNG 160×1280, 8 тайлов (`Г, О, Х`); ответ с
  конвертом — 119 917 Б JSON. 16×113: ok, 147 мс, 136 916 Б. 16×160: `bad_request`, 9 мс. Ответы 120–137 КБ прошли без ошибок.
- `camera preset.get` → `ok, path: None, engine: True`, `catalog_dir` — разрешённый путь ГЛАВНОГО дерева; тот же пресет в
  `layers preset.preview` → `invalid` (вне корня worktree) — N7.

### Новые находки

**F1 (SHOULD, architecture, фреймворк) — `update_yaml_preserving` / `update_blueprint_metadata_preserving` сменили
контракт для всех вызывающих.** Одинаковые входы, `957ee7ec^` против HEAD:

| Вход | old | new |
|---|---|---|
| файл — симлинк на `real/r.yaml`, `{a: 2}` | ссылка жива, цель `a: 2` | ссылка заменена обычным файлом `a: 2`, цель осталась `a: 1` |
| файл 0444 | `PermissionError` | записан молча, mode 0444 |
| жёсткая ссылка `h.yaml` | обе `a: 2` | `r.yaml a: 2`, `h.yaml a: 1`, `nlink=1` |
| каталог 0555, файл 0644 | записан | `PermissionError` (mkstemp) |
| новый файл, umask 022 / 077 | 0644 / 0600 | 0644 / 0600 — без изменений |
| значение без представления | файл обнулён `''` | файл цел `'a: 1\n'` — улучшение |

Вызывающие: `RecipeStore` (3 места), миграции `displays_to_recipe` / `drop_display_name`, дефолтный `_yaml_updater`
`RecipeManager`, `scene_source`. Жертв сегодня нет: в `multiprocess_prototype`, `apps`, `data`, `Services` главного
дерева 0 YAML-симлинков, 0 read-only, 0 с `nlink>1` (`find`). Защиту 0444 `scene_source` вернул себе (`os.access`),
остальные вызывающие её потеряли; в `recipe/README.md` / `DECISIONS.md` смены нет, симлинк упомянут только в README
`scene_source`. Исправить в `_dump_atomic`: `path = Path(os.path.realpath(path))` до записи (пишем цель, ссылка жива) и
`os.access(path, os.W_OK)` → `PermissionError` (старый контракт; проверка в `scene_source` станет дублем). Hard link и
ro-каталог — строка в докстринге. Два теста в `recipe/tests/test_yaml_io.py` (симлинк, 0444), строка в
`recipe/DECISIONS.md`.

**Условие APPROVED:** F1 закрыть до слияния ветки отдельным коммитом — латентно (0 жертв), 1.2a им не блокируется. Если
лид считает иначе — это CHANGES REQUESTED, третья итерация → teamlead.

### NIT / D

- **N7 — ограда отвергает пути самого файла, если картинки вне корня репозитория через `../` или симлинк наружу.**
  Вход: пресет вне репо с `catalog_dir: ../letters_font`, `get` → `commit` без правок → `invalid` (первый прогон скретча
  it.2). Живой: worktree + симлинк `data/line_sim/letter_catalog` → `get.preset` → `preview` → `invalid`. Главное дерево
  не затронуто (`data/line_sim` — обычный каталог). Строка в `Services/line_sim/presets/README.md`: «картинки — в корне
  репозитория или каталоге пресета; симлинки разрешаются по цели».
- **N8 — бюджет ограничивает тайл, не цену рендера:** 1200-px спрайты — 1.27 с на превью (теперь на `layers`, камеру не
  держит). «~88 мс» в README `layer_preview` — для Arial 300 px; дописать зависимость от размера спрайтов.
- **N9 — `apps/line_sim/pipeline.yaml`:** шапка «три процесса» и `description` устарели (процессов 5). Блок `layers`
  верный: `category: control`, без `chain_targets` / `wires` / `observability` — как `pult`; живьём поднялся, логи ошибок
  пусты. Дубль `preset_path` / `defect_probability` дешевле всего снять YAML-якорем (`preset_path: &scene_preset …` в
  `camera`, `preset_path: *scene_preset` в `layers`; так же `defect_probability`) — `yaml.safe_load` его разворачивает
  (проверено); `test_camera_alone_serves_frames` делает `safe_load` → `safe_dump`, якорь развернётся — безвредно.
- **N10 — tmp после kill не убирает никто** (`.…tmp` скрыт, но копится). Не чинить сейчас.
- **D3 — README `scene_source` противоречит себе:** «Движок не собрался при `configure` → `commit` = `invalid`» (пункт
  «Горячая подмена») против «файл пишется, `applied: false`» ниже; таблица команд без `engine` в `get` и без `changed` /
  `applied` / `message` в `commit`.
- **D4 (D2 it.1 закрыт наполовину) — размер ответа (L-6) в README `layer_preview` не записан; DONE-блок плана
  (`plans/line-sim-layer-editor.md:242`) всё ещё «≈ 12 КБ, ≈ 12 мс».** Реальные: ответ плагина 79 КБ / с конвертом роутера
  120 КБ, 88 мс; максимум 100 / 137 КБ (16×113).

### Что не проверено (it.2)

- Инъекции L1–L7 не повторял; у F1 нет теста — инжектировать нечего.
- Живьём — каталожный пресет, не `.yaml`: `preset.commit` через роутер и перечитывание файла `layers` после commit вживую
  не вызывал (только фейковый ctx).
- Влияние 1.3-секундного превью (крупные спрайты) на heartbeat/supervision процесса `layers` не мерил.
- Проверка 0444 через `os.access` не видит immutable-флаг (`chflags uchg`) и ACL — не проверял.
