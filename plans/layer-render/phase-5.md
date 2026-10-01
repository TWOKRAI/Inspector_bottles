# Фаза 5 — один механизм источников спрайтов

Родитель: [plan.md](plan.md). Итог фазы: откуда берётся картинка слоя — это **вид источника** в пресете, а не отдельный
инструмент под продукт. Новый продукт = пресет + каталог, без кода. Дообучение (`letters-retrain` Фаза 1) фазы **не
ждёт**: каталог первого продукта строится уже существующими инструментами.

Порядок исполнения — как в [phase-1.md](phase-1.md).

**Виды источников — только с потребителем сегодня или в этом плане:**

| Вид | Что даёт | Потребитель | Сегодня |
|---|---|---|---|
| `image` | RGBA из файла | слои пресетов, `tile` фона (1.1) | строка-путь в `sprite_source` |
| `class` | разыгранный эталон класса каталога | слой `class://`, генератор 2.2 | `class://` + `SpriteCatalog` |
| `solid` | заливка цветом (весь холст или по альфе другого источника) | `solid` фона (1.1), `color_rgb` слоя | `color_rgb`, `background_bgr` |
| `glyph` | текст шрифтом: высота, штрих, краска, зерно, мягкий край | каталоги первого продукта | `make_font_letters`, `make_ru_letter_sprites` (два кода) |
| `cutout` | вырез объекта из фото с прозрачным фоном | реальные эталоны каталогов | `dataset_gen/core/realcut.py`, `tools/cut_real_disks.py` |

Вне фазы (нет потребителя): процедурные фигуры, градиенты, шумовые текстуры, 3D. Добавляются функцией в `sources.py`,
когда появится продукт.

Источник используется в двух местах одной и той же функцией: **в слое пресета** (одна картинка при создании объекта) и
**в построителе каталога** (много картинок на класс, офлайн). Продуктовое — набор символов, шрифты, цвета, классы — только
в аргументах/пресете.

---

### Task 5.1 — `sources.py`: источники `image` / `class` / `solid` + словарная форма `sprite_source`

- **Статус:** [PENDING] (зависит от 1.1, 3.2) · **Level:** Senior (Opus 5.5) · **Assignee:** tester → teamlead → инъекции лида → reviewer
- **Module contract:** public-api-change (`LayerSpec.sprite_source` принимает словарь; новый модуль `layer_render.sources`)
- **CHAIN:** `teamlead`(INTERFACE) → `tester`(RED) → `teamlead`(GREEN) → `reviewer`

**Goal:** реестр `SOURCES: dict[str, fn -> RGBA]` с тремя видами; `sprite_source` в YAML принимает и прежние формы
(строка-путь, `class://`), и словарь `{image: путь}` / `{solid: {color_rgb, size_px | like: <слой>}}`.

**Files:**
1. `Services/layer_render/sources.py` (новый)
2. `Services/layer_render/layers.py` — тип `sprite_source` + разбор словаря
3. `Services/line_sim/core/factory.py` — загрузка словарных источников там же, где сегодня строки-пути
4. `Services/layer_render/background.py` — `solid`/`tile` фона зовут `SOURCES["solid"]`/`SOURCES["image"]` (схема YAML 1.1 та же)
5. `Services/layer_render/README.md`, `Services/line_sim/presets/README.md`
- тесты: `Services/layer_render/tests/test_sources_*.py`

**Acceptance:**
- [ ] Прежние формы (`"path.png"`, `class://`) — побайтно тот же объект: `test_hazards_1_3h_layout.py:40-44` зелёный без правки.
- [ ] `{image: p}` и `"p"` дают побайтно равный `render()` при одном seed.
- [ ] `{solid: {color_rgb: [255,255,255], size_px: [40, 40]}}` → RGBA 40×40, все пиксели `[255,255,255,255]`.
- [ ] Неизвестный вид → `ValueError` со списком известных; ни один источник не тянет rng, если не разыгрывает (`class` — тянет как сегодня).
- [ ] Эталоны фона 1.1 и `test_acceptance_lateral_offset_plugin.py:492-493` — зелёные.
- [ ] `pult_web` грузит и сохраняет пресет со словарным источником (YAML round-trip через `preset.commit`).

**Out of scope:** `glyph` (5.2), `cutout` (5.3), поля редактора для выбора вида (строка-путь в редакторе работает как сегодня).

---

### Task 5.2 — источник `glyph` + один CLI каталога глифов; два старых генератора — прокладки

- **Статус:** [PENDING] (зависит от 5.1 и решения О-3) · **Level:** Middle+ (Sonnet 5.5) · **Assignee:** tester → developer → инъекции лида → reviewer
- **Module contract:** public-api-change (новый вид источника + новый CLI; старые CLI сохраняются)
- **CHAIN:** `tester`(RED: sha256 выходов обоих старых CLI до задачи) → `developer`(GREEN) → `reviewer`

**Goal:** текст шрифтом рисует **одна** функция `SOURCES["glyph"](text, font, height_px | height_frac, stroke_px, ink_rgb,
grain_sigma, edge_blur_px, rng)`; каталог глифов строит один CLI с продуктово-нейтральными аргументами; оба прежних
генератора — тонкие прокладки с прежним CLI.

**Files:**
1. `Services/layer_render/sources.py` — вид `glyph` (тело — из `Services/line_sim/tools/make_font_letters.py`)
2. `Services/dataset_gen/tools/make_glyph_catalog.py` (новый) — `--chars`, `--font` (повтор), `--stroke-px` (повтор),
   `--height-frac`, `--ink-rgb`, `--grain-sigma`, `--edge-blur-px`, `--seed`, `--base IMAGE` (подложка под глиф, опц.), `--out`
3. `Services/line_sim/tools/make_font_letters.py` — прокладка: прежний CLI → `make_glyph_catalog`; `DEFAULT_DIAMETER_PX` по-прежнему из `make_letter_catalog.py`
4. `Services/dataset_gen/tools/make_ru_letter_sprites.py` — прокладка: прежний CLI и `RU_UPPERCASE` (импорт `test_config_preset.py:58`) остаются
5. README обоих сервисов (dataset_gen, line_sim) — где теперь инструмент
- тесты рядом с кодом: test_source_glyph.py (layer_render), test_make_glyph_catalog.py (dataset_gen)

**Acceptance:**
- [ ] `test_acceptance_look_1_2_ink_disk.py`, `test_hazards_look_1_2.py`, `test_acceptance_1_1b_font_tool.py`,
      `test_acceptance_font_stroke.py`, `test_hazards_font_stroke.py`, `test_hazards_1_1b_tool_preset.py` — зелёные без правки.
- [ ] О-3 «побайтно» (рекомендация): sha256 всех файлов `make_ru_letter_sprites --font <DejaVuSans-Bold из matplotlib>
      --size 256` — литералы сняты тестером до задачи — совпадают после. О-3 «новые пиксели»: высота/D ∈ [0.47, 0.50]
      методом замера лида, пресеты `ru_letters_disk.yaml`/`manual_letters_disk.yaml` грузятся.
- [ ] `make_glyph_catalog` с не-кириллицей (`--chars 0123`, латинский шрифт) строит каталог — продукт без правки кода.
- [ ] `ImageFont.truetype` для глифа — ровно в одном месте (`sources.py`; `preview.py` подписи — не глиф, не считается).
- [ ] `grep -inE "letter|букв|disk|диск"` по `sources.py` и `make_glyph_catalog.py` — 0 совпадений.

**Out of scope:** вид `glyph` прямо в слое пресета без каталога — работает автоматически через реестр 5.1, отдельных
полей редактора не делаем; перегенерация данных и переобучение — решение `letters-retrain`.

---

### Task 5.3 — источник `cutout` (вырез из фото) поверх `realcut`

- **Статус:** [PENDING] (зависит от 5.1) · **Level:** Middle (Sonnet 5.5) · **Assignee:** tester → developer → инъекции лида → reviewer
- **Module contract:** public-api-change (новый вид источника; CLI `cut_real_disks` сохраняется)
- **CHAIN:** `tester`(RED) → `developer`(GREEN) → `reviewer`

**Goal:** вырез объекта из фото с прозрачным фоном — вид `cutout` в реестре; форма выделения — параметр (`shape: circle`
— единственная сегодня, это `detect_disk` из `realcut.py`).

**Files:**
1. `Services/layer_render/sources.py` — вид `cutout(image, shape="circle", ...)`; детекция круга передаётся функцией (без импорта `dataset_gen`)
2. `Services/dataset_gen/core/realcut.py` — регистрирует/зовёт `cutout` с `detect_disk`; поведение то же
3. `Services/dataset_gen/tools/cut_real_disks.py` — без изменений CLI, внутри — `cutout`
4. `Services/dataset_gen/README.md`
- тесты: `Services/dataset_gen/tests/test_realcut.py` (зелёный без правки) + `Services/layer_render/tests/test_source_cutout.py`

**Acceptance:**
- [ ] `test_realcut.py` — зелёный без правки; `cut_real_disks` на 3 фикстурных фото — побайтно прежние эталоны (литералы — тестер до задачи).
- [ ] `shape` вне `{"circle"}` → `ValueError`, текст называет допустимые и говорит, что некруглые формы — вне плана.
- [ ] `layer_render` не импортирует `dataset_gen` (AST-тест 1.1).

**Out of scope:** некруглые формы (прямоугольник, полигон, маска по сегментации) — когда появится такой продукт; правка
алгоритма детекции.
