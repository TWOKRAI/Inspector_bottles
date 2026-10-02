# Фаза 1 — фон из слоёв + альфа плитки

Родитель: [plan.md](plan.md). Итог фазы, видимый владельцу: на стенде `apps/line_sim` под лентой чёрное — в просветах
между звеньями и выше/ниже ленты; фон задаётся списком слоёв в конфиге. Заменяет Task 0.1 `letters-retrain`.

Общий порядок исполнения каждой задачи (конвенция проекта): **tester (Sonnet 5.5, слепой, git worktree на коммите
до реализации, только критерии приёмки; запрещены файлы реализации и тесты автора)** → **developer (Sonnet 5.5) или
teamlead (Opus 5.5)** → **break-injection лида** (по одной на заявленное свойство, предсказание до прогона) →
**reviewer (Opus 5.5, `run_in_background: false`, вердикт по SHA)**. Исполнитель не коммитит в `main` и не пушит;
лимит — 2 итерации на петлю, третья — эскалация к `teamlead`. Каждая задача с кодом проходит grep рамки
(plan.md → «Рамка плана») по своим новым/изменённым файлам механизма. Данные продукта, реальная плитка и фото лежат
в `data/` вне git — тесты тестера и CI работают на синтетических копиях той же структуры; реальные данные — отдельный
прогон лида точной командой из задачи.

---

### Task 1.1 — [VERTICAL SLICE] стек фона `background_layers` от конфига до кадра сима

- **Статус:** [PENDING] · **Level:** Senior (Opus 5.5) · **Assignee:** tester → teamlead → инъекции лида → reviewer
- **Module contract:** new-full (`Services/layer_render/` — пакет: `__init__.py`, `interfaces.py`, `background.py`)
- **CHAIN:** `tester`(RED) → `teamlead`(GREEN) → `reviewer`
- **Dependencies:** нет
- **Gate:** RED тестера → GREEN; инъекции лида записаны; `reviewer` APPROVED по SHA; grep рамки — 0

**Goal:** ключ `background_layers` в конфиге `scene_source` задаёт фон сцены стеком слоёв снизу вверх (`solid` — заливка
RGB, `tile` — RGB/RGBA-картинка, прокручивается с лентой); без ключа кадр байт в байт прежний.

**Files:**
1. `Services/layer_render/__init__.py` (новый)
2. `Services/layer_render/interfaces.py` (новый) — `SolidFill(color_rgb)`, `ScrollingTile(image)` (frozen dataclass, RGB или RGBA uint8)
3. `Services/layer_render/background.py` (новый) — `background_layers_from_config(items, load_image)`, `render_background(...)`
4. `Services/layer_render/README.md` + STATUS.md рядом (новые; README — контракт, схема YAML, порядок сцены)
5. `Services/line_sim/core/scene_compositor.py` — необязательный `background_layers`
6. `Plugins/sim/scene_source/plugin.py` — ключ `background_layers` (чтение картинок, ошибки)
- тесты: каталог `Services/layer_render/tests/` (новый) и файл `test_background_layers_*.py` в тестах `scene_source`

**DESIGN:**
- Схема YAML (одна и та же для сима и, в 2.2, для генератора):
  ```yaml
  background_layers:          # снизу вверх
    - solid: [0, 0, 0]        # RGB, не BGR
    - tile: data/line_sim/belt_tile.png   # путь от корня репо; RGB = непрозрачно, RGBA = по альфе
  ```
  Элемент — словарь ровно с одним ключом `solid` или `tile`; иное (`{}`, два ключа, неизвестный ключ, цвет не из трёх
  int 0..255, пустой список) → `ValueError`, текст называет индекс элемента и значение. Под всеми слоями — чёрный.
- `tile` раскладывается **ровно как сегодня** `background_tile` (`scene_compositor.py:92-103`): столбцы — по модулю
  ширины со сдвигом `belt_direction * round(encoder_to_offset_mm(now, 0) * px_per_mm)`, строки — симметрично `belt_y_px`,
  строки вне тайла — прозрачны (видно слой ниже). Сдвиг считает `SceneCompositor` и передаёт в `render_background`
  числом — `layer_render` не знает про энкодер и про `line_sim`.
- Смешение — альфа-«over»; альфа 255 даёт пиксель тайла точно, альфа 0 — пиксель ниже точно.
- Подсказка (не требование): сплошные слои под единственной плиткой сворачиваются в один непрозрачный тайл при сборке
  компоновщика — тогда кадр стоит столько же, сколько старый путь.
- `SceneCompositor(..., background_layers=None)`: `None` → ветка 3.6 нетронута (`background_bgr` + `background_tile`).
  Заданы оба (`background_layers` и `background_tile`) → `ValueError` в конструкторе.
- Где `ValueError`: кривая схема — в `background_layers_from_config` (функция); плагин зовёт её в `configure()` **до и вне**
  try/except сборки движка (`plugin.py:312-333`), поэтому ошибка схемы и «оба ключа фона» (`background_layers` +
  `background_texture`) роняют `configure()` — ошибка конфигурации стенда, не откат. Нечитаемая картинка слоя `tile` —
  не ошибка схемы: ровно один `ctx.log_error`, слой выброшен, движок жив (приём `_load_background_tile`,
  `plugin.py:352-370`); если выброшены все слои — стек пуст, фон чёрный (это не «пустой список» схемы).
  Чтение — `imread_unicode(..., IMREAD_UNCHANGED)`, BGR(A)→RGB(A).
- Строка лога `configure()` называет фон: `фон=слои[solid(0,0,0), tile(<путь>, 410x484, RGBA)]`.

**Steps:** 1. tester пишет приёмку по Acceptance (RED). 2. teamlead: `interfaces.py` + `background.py` → компоновщик →
плагин. 3. Прогон радиуса + золотые эталоны. 4. Замер производительности (см. ниже), числа — в отчёт.

**Acceptance:**
- [ ] Без ключа `background_layers` золотой эталон плагина `test_acceptance_lateral_offset_plugin.py:492-493` — зелёный без правки литералов.
- [ ] Эквивалентность старому пути: `[{solid: [10,20,30]}, {tile: <RGB-тайл>}]` даёт кадр, **побайтно равный** старому
      `background_bgr=(30,20,10), background_tile=<тот же тайл>` (несимметричный цвет ловит перестановку RGB/BGR), на 3 позициях энкодера × `belt_direction ±1` × `y_px` с
      тайлом, выходящим за верх и низ кадра.
- [ ] RGBA-тайл 4×4 с альфой 0 в одном столбце поверх `solid [0,0,0]`: в этом столбце пиксели кадра `[0,0,0]`, в остальных — RGB тайла.
- [ ] Альфа 128 над `solid [0,0,0]` и пикселем тайла `[200,100,50]` → `[100,50,25]` ± 1.
- [ ] Каждая форма кривой схемы → `ValueError` из `background_layers_from_config` с индексом элемента; она же и «оба ключа
      фона» из `configure()` плагина — исключение выходит наружу (движок не собирается на сплошном фоне).
- [ ] Нечитаемый файл `tile` → ровно 1 `log_error` за `configure()`, 0 исключений в 10 вызовах `produce()`.
- [ ] Медиана `SceneCompositor.render()` на 1440×1080 без объектов, 200 кадров: `[solid, RGBA-тайл 410×484]` ≤ 1.3× медианы
      старого пути `background_tile` на той же машине; оба числа в отчёте.
- [ ] `layer_render` не импортирует `Services.line_sim`, `Services.dataset_gen`, `Services.ml_train` (тест на AST импорта).

**Goldens:** `test_acceptance_lateral_offset_plugin.py:492-493`, `test_acceptance_3_6.py`, `test_hazards_3_6.py`,
`test_scene_source_task_3_6.py`, `test_scene_source_hazards_3_6.py`, `test_hazards_1_3h_layout.py:40-44`.

**Out of scope:** конфиг стенда и пересборка плитки (1.3), инструмент (1.2), эффекты на слоях фона, фон в ветке
`_background_only_frame`, правка `pipeline.yaml`.

**TRAPS:** `background_bgr` концептуально BGR, кадр хранится в RGB (`scene_compositor.py:85-90`) — в новой схеме цвет
сразу RGB, не переставлять дважды. `composite` из `dataset_gen` округляет центр — для тайла не годится, тайл индексируется.

---

### Task 1.2 — опция `--gap-alpha` у `make_seamless_texture`: просветы прозрачные

- **Статус:** [PENDING] · **Level:** Middle+ (Sonnet 5.5) · **Assignee:** tester → developer → инъекции лида → reviewer
- **Module contract:** impl-only (CLI-инструмент, новая необязательная опция)
- **CHAIN:** `tester`(RED) → `developer`(GREEN) → `reviewer`
- **Dependencies:** нет; `Services/line_sim/README.md` правит и 2.2 (разные разделы — лид сводит при слиянии)
- **Gate:** RED тестера → GREEN; инъекции лида записаны; `reviewer` APPROVED по SHA; grep рамки — 0

**Goal:** с `--gap-alpha` инструмент пишет RGBA-PNG: RGB — тот же тайл, что без опции, альфа 0 в просветах между звеньями,
255 на звеньях и бортах.

**Files:**
1. `Services/line_sim/tools/make_seamless_texture.py` — опция + чистая функция `gap_alpha_mask(tile_rgb, ...) -> uint8`
2. `Services/line_sim/README.md` — раздел инструмента: рецепт и измеренные пороги
- тесты: `Services/line_sim/tests/test_acceptance_gap_alpha.py`, `test_hazards_gap_alpha.py`

**DESIGN:**
- Маска считается по HSV готового тайла (после масштаба и шва — иначе маска не совпадёт с пикселями): пиксель — просвет,
  если тон в `--gap-hue LO,HI` и насыщенность ≥ `--gap-sat-min`, и строка не в зоне бортов `--rails-px TOP,BOTTOM`
  (строки `[0, TOP)` и `[h-BOTTOM, h)` — всегда альфа 255).
- Дефолты порогов — **измерить** на `data/line_sim/belt_photo_full.png` → тайл (рецепт `apps/line_sim/pipeline.yaml:119-123`)
  и записать в README с числами замера (медианы H/S у просветов и у звеньев). Фото и тайл лежат в `data/` (вне git):
  на 2026-10-01 — в worktree `.claude/worktrees/stand/data/line_sim/`.
- Маска бинарная; сглаживание края — не делать (YAGNI, добавить, если на стенде будет «лесенка»).
- Без `--gap-alpha` — путь записи не меняется.

**Acceptance:**
- [ ] Без опции выход побайтно равен выходу до задачи (sha256 PNG на синтетическом фото, литерал снят тестером до реализации).
- [ ] С опцией: `out[:, :, :3]` побайтно равен тайлу без опции (опция добавляет только альфу).
- [ ] Синтетический тайл (тестер рисует сам: серые звенья V≈78, мятные просветы V≈79 с S выше звеньев, зелёные борта
      15 строк сверху/снизу S≈100 V≈190): альфа 0 у ≥ 99 % пикселей просвета, 255 у ≥ 99 % пикселей звеньев, у 100 % бортов.
- [ ] Альфа периодична: на синтетическом тайле с известным периодом `P` (два периода в ширину) столбцы `x` и `x+P`
      совпадают у ≥ 99 % строк для всех `x < P`; на реальном тайле — то же с `P = period_px` из вывода инструмента (прогон лида в 1.3).
- [ ] Пороги — параметры CLI; кривые значения (`LO>HI`, вне 0..179/0..255, `TOP+BOTTOM ≥ h`) → `SystemExit` с именем флага.
- [ ] README: рецепт команды с `--gap-alpha` и таблица замера порогов.

**Goldens:** `test_acceptance_look_1_1_period.py`, `test_hazards_look_1_1.py`, тесты инструмента из `test_acceptance_3_6.py`.

**Out of scope:** пересборка `data/line_sim/belt_tile.png` и конфиг стенда (1.3), фон выше/ниже ленты, перерисовка фото.

---

### Task 1.3 — стенд на `[чёрный, плитка]` + границы sentrux + удаление ветки `background_tile`

- **Статус:** [IN PROGRESS] волна 2 · **Level:** Middle (Sonnet 5.5) · **Assignee:** tester → developer → инъекции лида → живой стенд лида → reviewer
- **Module contract:** public-api-change (удаляются kwarg `SceneCompositor(background_tile=)` и ключ конфига `background_texture`)
- **CHAIN:** `tester`(RED, worktree до кода) → `developer`(GREEN) → инъекции лида → стенд лида → `reviewer`
- **Dependencies:** 1.1, 1.2
- **Gate:** RED тестера → GREEN; инъекции записаны; `sentrux check .` зелёный; замер стенда записан; `reviewer` APPROVED
- **Перестроено 2026-10-01 (волна 2):** условие CTO (б) — после перевода стенда ветка `background_tile` и ключ
  `background_texture` удаляются в этой же задаче. С кодом задача получает слепого тестера (раньше «без кода, без тестера»).
  Критерий периодичности альфы на реальной плитке снят (решение владельца: два периода тайла — разные звенья).

**Goal:** стенд `apps/line_sim` рисует ленту поверх чёрного стеком `background_layers`; старого пути фона-тайла нет —
один способ задать фон.

**Files:**
1. `data/line_sim/belt_tile.png` — пересобрать с `--gap-alpha` (вне git; старый сохранить как `belt_tile_rgb.png`) — **лид**
2. `apps/line_sim/pipeline.yaml` — `background_texture` → `background_layers: [{solid: [0, 0, 0]}, {tile: data/line_sim/belt_tile.png}]`, комментарий-рецепт обновить
3. `Services/line_sim/core/scene_compositor.py` — удалить kwarg `background_tile`, `_validate_background_tile`, ветку рендера тайла; `background_bgr` (сплошная заливка без слоёв) остаётся
4. `Plugins/sim/scene_source/plugin.py` — удалить чтение `background_texture` и `_load_background_tile`; ключ `background_texture` в конфиге → `ValueError` из `configure()` с подсказкой `background_layers` (не тихое игнорирование)
5. Тесты старого пути (`Services/line_sim/tests/test_acceptance_3_6.py`, `test_hazards_3_6.py`, `test_hazards_5_3b.py::test_background_tile_shifts_same_direction_as_objects_when_reversed`,
   `Plugins/sim/scene_source/tests/test_scene_source_task_3_6.py`, `test_scene_source_hazards_3_6.py`, ветки `background_texture` в тестах 1.1) — **перевести на `background_layers`**
   с теми же литералами sha256, либо удалить с указанием теста, который держит то же свойство. Таблица «старый тест → новый/эквивалент» — в отчёт
6. README/STATUS/DECISIONS `Services/line_sim`, `Plugins/sim/scene_source`, `Services/layer_render/README.md` — убрать `background_texture`/`background_tile` как живой путь (в DECISIONS — запись об удалении)
7. `.sentrux/rules.toml` — четыре `[[boundaries]]`: layer_render ↛ line_sim, layer_render ↛ dataset_gen, layer_render ↛ ml_train, dataset_gen ↛ line_sim (все под `Services/`)
8. `Services/STATUS.md` — строка `layer_render`
9. `Services/layer_render/DECISIONS.md` (новый) — LR-001: пакет ниже обоих сервисов, политика реэкспорта, контракт rng; LR-002: один способ задать фон (удаление `background_texture`)
10. `scripts/validate.py` — `"layer_render"` в список `SERVICES` (`validate.py:73-77`)

**Acceptance:**
- [ ] A1. `SceneCompositor(..., background_tile=<любой массив>)` → `TypeError` (kwarg нет); в `scene_compositor.py` нет имени `background_tile`.
- [ ] A2. `scene_source.configure()` с ключом `background_texture` (любое значение, в т.ч. `None`-строка пути, и вместе с `background_layers`)
      → `ValueError` из `configure()`, в тексте есть `background_layers`. Без ключа — поведение 1.1 как есть.
- [ ] A3. Эталоны старого пути держатся на новом: кадры `scene_source`/`SceneCompositor` с `background_layers: [{solid: <тот же цвет>}, {tile: <тот же файл>}]`
      дают **те же литералы sha256**, что пинили тесты 3.6 и `_GOLDEN_BACKGROUND_TEXTURE_SHA` (1.1). Литералы не переписываются.
- [ ] A4. Свойства 3.6/5.3b на пути `background_layers`: фон едет с энкодером в ту же сторону, что объекты, и при реверсе ленты;
      сдвиг цикличен по ширине тайла; узкий тайл заполняет кадр без растяжения; относительный путь `tile` — от корня репо, не от cwd;
      нечитаемый тайл — один `log_error`, слой выброшен, движок работает.
- [ ] A5. `apps/line_sim/pipeline.yaml`: у `scene_source` ключ `background_layers` ровно `[{solid: [0, 0, 0]}, {tile: data/line_sim/belt_tile.png}]`, ключа `background_texture` нет.
- [ ] A6. `grep -rnE "background_texture|background_tile" Services Plugins apps` вне `tests/`, `DECISIONS.md` и текста `ValueError`/строки миграции в README — 0.
- [ ] A7. `sentrux check .` (CLI, не MCP) — `✓ All rules pass`, правил на 4 больше, чем на `main`; вывод в отчёт.
- [ ] A8. `python scripts/validate.py` — зелёный, `layer_render` в выводе; инъекция: убрать `Services/layer_render/STATUS.md` → validate красный.
- [ ] A9 (лид, стенд, `backend_ctl`): на кадре `scene_source` медиана V просветов (маска 1.2, перенесённая на кадр) ≤ 10, медиана V звеньев ± 3
      от кадра до задачи; поля выше/ниже ленты — `[0,0,0]`.
- [ ] A10 (лид): `python -m Services.line_sim.tools.make_seamless_texture data/line_sim/belt_photo_full.png --out data/line_sim/belt_tile.png --force-period --gap-alpha` — `period_px` в отчёте.

**Out of scope:** `_background_only_frame` `scene_source` (сплошная заливка остаётся); фон в пресете (Ф3); правки `dataset_gen`.

---

### Task 1.4 — фильтр площади в `gap_alpha_mask`: убрать «перец» плитки

- **Статус:** [PENDING] волна 3 · **Level:** Middle (Sonnet 5.5) · **Assignee:** tester → developer (dev-effects после 2.2) → инъекции лида → reviewer
- **Module contract:** public-api-change (новый keyword `min_area` у `gap_alpha_mask`, флаг CLI `--gap-min-area`)
- **CHAIN:** `tester`(RED, worktree до кода) → `developer`(GREEN) → инъекции лида → `reviewer`
- **Dependencies:** 1.2 (DONE)
- **Gate:** RED тестера → GREEN; тесты 1.2 зелёные без правки; инъекции записаны; `reviewer` APPROVED по SHA

**Почему.** Стенд волны 2: на звеньях чёрные крапинки. Замер лида 2026-10-02 на `data/line_sim/belt_tile.png`
(RGBA 410×484, альфа = маска 1.2), 8-связность: прозрачных 1735 px в 537 компонентах; компонент < 8 px — 523
(655 px), ≥ 8 px — 14 (1080 px). Между 7 px и 12 px в распределении нет ни одной компоненты — естественный разрыв,
порог 8 стоит в нём.

**Goal:** `gap_alpha_mask` отбрасывает прозрачные связные компоненты (8-связность) площадью меньше `min_area` px —
они становятся непрозрачными (255); инструмент по умолчанию фильтрует с порогом 8.

**Files:**
1. `Services/line_sim/tools/make_seamless_texture.py` — keyword `min_area: int = 0` у `gap_alpha_mask` (`:241-260`);
   константа `_GAP_MIN_AREA = 8` рядом с `_GAP_HUE`/`_GAP_SAT_MIN`; флаг `--gap-min-area N` с той же проверкой, что у
   `--gap-sat-min` (`:353-369`: только вместе с `--gap-alpha`, целое ≥ 0, иначе `parser.error` с именем флага)
2. `Services/line_sim/README.md` — раздел инструмента: флаг, порог 8 и замер выше
- тесты тестера: `Services/line_sim/tests/test_acceptance_layer_render_1_4_gap_min_area.py`

**DESIGN:**
- Фильтр — один вызов `cv2.connectedComponentsWithStats((alpha == 0).astype(np.uint8), connectivity=8)`; компоненты с
  `CC_STAT_AREA < min_area` → 255. Порядок закреплён: **сначала** строки бортов → 255, **потом** фильтр — площадь
  считается без пикселей в бортах (обратный порядок на реальном тайле расходится на 1 px — замер ревью спеки).
- Края тайла по x **не склеиваются** (тайл повторяется по x, компонента на шве считается двумя): решение «не усложнять»;
  на реальном тайле склейка меняет результат на 4 px. Числа A6 сняты без склейки.
- Дефолт **функции** — `min_area=0` = фильтр выключен, выход побайтно прежний: на этом стоит тест 1.2
  `test_hazards_gap_alpha.py:96` (однопиксельный просвет без нового параметра). Дефолт **CLI** — `_GAP_MIN_AREA = 8`:
  это продуктовая починка, она приходит из инструмента.
- Фильтр трогает только альфу: RGB выхода с `--gap-alpha` побайтно тот же, что без фильтра.
- Обратная операция (закрыть непрозрачные точки внутри просвета) — не делается.

**Acceptance:**
- [ ] A1. `min_area=0` и отсутствие keyword — выход побайтно равен выходу до задачи (литералы тестера на синтетическом
      тайле, снятые на коде до задачи); тесты 1.2 (`test_acceptance_layer_render_1_2_gap_alpha.py`,
      `test_hazards_gap_alpha.py`) — зелёные без правки.
- [ ] A2. Синтетический тайл с прозрачными компонентами площадью 1, 3, 7, 8, 20 px и `min_area=8`: компоненты 1/3/7 →
      255, 8 и 20 — 0 попиксельно как без фильтра.
- [ ] A3. 8-связность: два прозрачных пикселя, касающиеся только углом, — одна компонента площади 2 (при `min_area=3`
      оба → 255, при `min_area=2` оба остаются 0); четыре таких пикселя по диагонали — одна компонента площади 4.
- [ ] A4. Строки бортов (`rails_px`) — 255 при любом `min_area`; вход не мутирован; выход `uint8 (H, W)` ∈ {0, 255}.
- [ ] A4b. Порядок «борта, потом фильтр»: прозрачная по цвету компонента 10 px, из них 7 в строках борта, при `min_area=8`
      → оставшиеся 3 px → 255 (при обратном порядке они бы выжили).
- [ ] A5. CLI: `--gap-alpha` без `--gap-min-area` = порог 8 (проверка на синтетическом фото: компонента 3 px исчезает,
      8 px остаётся); `--gap-min-area 0` = выход как до задачи; `--gap-min-area` без `--gap-alpha`, `-1`, `abc` →
      `SystemExit` с именем флага в stderr. RGB-каналы PNG с фильтром и без — побайтно равны.
- [ ] A6 (лид, реальные данные вне git; вход — `.claude/worktrees/stand/data/line_sim/belt_photo_full.png`, sha256
      `4444f158592a7fc34d014d79ea362e2b080693a6409369c5b00a4aa2e11ecd8e`; фикстура в git `Services/line_sim/tests/fixtures/` —
      ДРУГОЕ фото): `python -m Services.line_sim.tools.make_seamless_texture <вход>
      --out <tmp>/belt_tile.png --force-period --gap-alpha` → компонент < 8 px = 0; прозрачных компонент 14 ± 0 и
      px 1080 ± 0 (замер выше); покрытие видимого стола — новое число рядом с прежним 72.4 %.
- [ ] A7 (лид, стенд): стенд на плитке A6; на точном рендере (без JPEG) число тёмных (V < 10) связных пятен < 8 px
      в полосе ленты — до и после числом (ожидание: после = 0); снимок кадра до/после в отчёт лида.

**Out of scope:** сглаживание края маски; закрытие непрозрачных точек в просветах; смена правила H∧S и его порогов;
склейка краёв тайла; код сима и `layer_render`.

**TRAPS:** `test_hazards_gap_alpha.py:60` сравнивает альфу CLI (теперь порог 8) с `gap_alpha_mask` по умолчанию (порог 0) на
синтетическом тайле — держится только потому, что самая малая компонента там ровно 8 px (ревью спеки прогнало 1.2 с
имитацией фильтра: 47 passed, 1 skipped). Править этот тест нельзя; если он покраснел — стоп и вопрос лиду.
