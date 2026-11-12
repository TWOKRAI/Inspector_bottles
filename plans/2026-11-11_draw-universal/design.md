# Design: draw-universal

Спецификация к [`plan.md`](plan.md). Источник контрактов — CTO r1 §2 (`docs/reports/2026-11-11_draw-architecture-cto.md:56-142`)
и r2 §2.3–2.5 (`docs/reports/2026-11-11_draw-architecture-cto-r2.md:169-249`). Здесь — только то, что план берёт в
Ф0–Ф4, и где оно лежит. Все path:line сверены `git grep`/`sed` 2026-11-11 (qex не работал).

## 1. Пакет `Services/draw` по задачам

| Файл | Что | Задача |
|---|---|---|
| `README.md` | публичный API, pre/post, чего ядро не делает: не пишет кадры и данные конвейера, не принимает решений | 1.1 |
| `interfaces.py` | `type Figure = dict[str, Any]`, `type Scene = list[Figure]`, `Op`, `Capabilities`, `DrawBackend`, `TextRasterizer` — r1 `:58-94` | 1.1 |
| `geometry.py` | побайтная копия `Plugins/render/overlay_draw/geometry.py` (64 строки, `vline_segments`); старый файл не трогается | 1.1 |
| `scene.py` | `StyleTable`, `scene_from_overlay`, `lower`, `render` | 1.1, 1.2, 1.3, 4.1 |
| `backends.py` | `register_backend`, `get_backend`, `available_backends`, `Cv2Backend` | 1.1, 1.3 |
| `fonts.py`, `fonts/` | `FontInfo`, `FontRegistry`, `DEFAULT_FONT = "dejavu-bold"` — r2 `:178-193` | 1.2 |
| `text.py` | `PilTextRasterizer`: строка → альфа-маска uint8, кэш строк | 1.2 |
| `conformance.py` | сцены набора и `check_backend(backend) -> list[str]` | 1.3 |
| `mapping.py` | `MappingRule`, `compile_rules`, `build_scene` | 2.1 |

Две границы данных (r2 §4, строка про «сцену»): **сцена** — JSON-данные, идёт между процессами (inline, это
`list[dict]`, правило SHM её не трогает: по ссылке едут только числовые ndarray верхнего уровня ndim 2–3 от 8192 байт,
`frame_shm_middleware.py:52-55`); **список `Op`** живёт только внутри процесса.

Цвет сцены и стилей — BGR, как в рецептах сегодня. Порядок списка сцены = порядок слоёв.

### 1.1 Правила реестра бэкендов (r1 `:109-112`)

- Неизвестное имя → `ValueError` со списком доступных.
- Бэкенд без своей библиотеки → `RuntimeError` при `configure` (образец — `_make_backend`,
  `Services/ml_inference/engine.py:28-38`).
- Молчаливой замены нет (анти-образец: `Plugins/sources/camera_service/backends/__init__.py:71`, неизвестная камера
  тихо становится симулятором).
- `auto` разрешается один раз при `configure`; имя — в лог и в регистр только для чтения `active_backend` (2.1).

### 1.2 Conformance (r1 `:161`, r2 `:159-163`)

- Вне объединения рамок фигур (с запасом на толщину) пиксели побайтно равны входу.
- Внутри — покрытие и цвет с допуском. Допуски CTO (IoU 0,95) не откалиброваны: литералы ставит тестер Task 1.3.
- Бэкенд с `caps.exact_as` сравнивается с эталонным побайтно.
- В наборе — пересекающиеся полупрозрачные фигуры: ROI-вариант CTO смешал пересечение дважды (расхождение 61 уровень).
- Пин текста — тройка «Pillow, FreeType, sha256 шрифта»; совпала — побайтно, нет — с допуском и печатью новой тройки.

### 1.3 Помощники SDK (r2 §2.4–2.5)

Место — `multiprocess_framework/modules/process_module/plugins/item_template.py` и `rate_gate.py`, экспорт из
`plugins/__init__.py` (сегодня 59 строк, `__all__` с 33-й). Грамматика — таблица r2 `:209-217`; фильтры `bucket`,
`default`, `safe`. Только ключи dict и целые индексы списка, без атрибутов и выражений. `RateGate(max_fps)`, 0 —
выключено. Потребитель вне плана — DS-1 (`plans/queue/backlog.md:77-107`): диапазон DS-1 = фильтр `|bucket=N`.

## 2. Что переиспользуется (не пишется заново)

| Что | Откуда | Куда |
|---|---|---|
| разбор `overlay` (vlines, lines, dashed_lines, points), порядок отрисовки | `Plugins/render/overlay_draw/plugin.py:114-171` | `scene_from_overlay` (1.1) |
| резолв стиля: фигура → строка по `group` → по `type` → дефолт | `overlay_draw/plugin.py:63-91`, `registers.py:21-101` | `StyleTable` (1.1) |
| пунктир | `overlay_draw/plugin.py:93-110` (`_draw_dashed`) | `lower` (1.1) |
| серый → BGR, кадр не мутируется | `overlay_draw/plugin.py:119-125` | плагин (1.1) |
| `vline_segments` | `overlay_draw/geometry.py:53-64` | `Services/draw/geometry.py` (1.1) |
| текст PIL с кириллицей | `Services/ml_inference/plugin/plugin.py:39-67` (`_FONT_CANDIDATES`, `_overlay_font`, `_put_text_unicode`) | `text.py` — патч вместо полного кадра (1.2) |
| подпись распознавания: метка, уверенность, `θ°`, `∠любой`, `<порог`, цвета | `ml_inference/plugin/plugin.py:220-237` | правило `recog_draw` (3.1) |
| окружности, центр, `r=NN` | `Plugins/render/circle_draw/plugin.py:57-75` | правило mapping (2.2) |
| контуры | `Plugins/processing/contour_draw/plugin.py:69-73` | правило `polyline` (2.2) |
| маска, рамки, `area=` | `Plugins/render/render_overlay/plugin.py:97-163` | правила `mask`, `rect` (4.1, 4.2) |
| реестр бэкендов | `Services/ml_inference/engine.py:28-38` | `backends.py` (1.1, 1.3) |
| правка `list[dict]` в GUI | `multiprocess_prototype/frontend/forms/factory/kinds.py:171-173` (JSON-редактор) | регистры `mapping`, `styles` (2.1) |
| DejaVu и лицензия | `.venv/lib/python3.12/site-packages/matplotlib/mpl-data/fonts/ttf/` (`DejaVuSans.ttf`, `DejaVuSans-Bold.ttf`, `LICENSE_DEJAVU`) | `Services/draw/fonts/` (1.2, после В1) |

Тесты `overlay_draw`: 30 функций `def test_` в 4 файлах (`grep -c`); в handoff — 26. Число для приёмки берёт
прогон на стадии 0 Task 1.1.

## 3. Граница с layer-render (решение владельца 9: план пересматривается позже)

| Что | Владелец | Точка передачи |
|---|---|---|
| реестр шрифтов, текст-патч | `Services/draw` (Task 1.2) | layer-render Ф7 «спрайт из шрифта»; LR-001 правится при старте Ф7 (вопрос r2 №2) |
| словарь фигур, `transform_scene` | `Services/draw` (`transform_scene` — в «Следующих планах») | layer-render Ф9 «регион = вид слоя» (`plans/layer-render/plan.md:123-136`) |
| экспорт YOLO/COCO | `Services/draw/export.py` (не в этом плане) | layer-render Ф9 (`plan.md:128`) |
| склейка спрайтов, фон, эффекты, пресеты, rng | `Services/layer_render` | не переходит; `blit` — только по замеру |
| канва редактора | layer-render Ф5 (5.3 DONE) | режим «Разметка» (L2) |

Направление импорта: `layer_render → draw`, обратно нельзя. Правила sentrux на `Services/draw` вводит Task 1.1;
правила на `layer_render → draw` — при пересмотре layer-render.

## 4. Другие планы, которые правят `overlay_draw`

| План | Что держит | Где | Что делает этот план |
|---|---|---|---|
| code-reader-gui | вход `frame` `image/*`, серый кадр | `plans/code-reader-gui.md:35` | Task 1.1: порт `frame` без изменений, тест серого входа |
| topology-port-join | `overlay` `optional=True, join=True`; литералы A11 | `plans/topology-port-join.md:9, :52`; `overlay_draw/tests/test_overlay_port_join_catalog.py:40-57` | Task 1.1: без изменений; Task 2.1: A11 `:55-57` краснеет намеренно, решение лида |
| camera-device-service 3.4 (PENDING) | копия только BGR-входа; серый — уже новый массив после `cvtColor` | `plans/2026-10-18_camera-device-service/tasks/3.4.md:6, :17` | Task 1.1 берёт правило в себя; 3.4 снимает `overlay_draw/plugin.py` со своих FILES (правка 3.4 — через её `amendments`) |

## 5. Риски и ловушки

- **Шрифт подписей меняется.** Подписи точек `overlay_draw` и `r=NN` `circle_draw` сегодня — Hershey
  (`cv2.putText`), подпись `ml_inference` — Arial Bold на Windows (`plugin.py:41-46`). После Ф1/Ф3 — DejaVu через
  FreeType. Ширина строки 22 px: DejaVu Bold 252 px, Arial Bold 200 px (r2 `:197`). Сравнение ширины — только на
  встроенном шрифте.
- **Размер шрифта из `label_scale`.** Hershey-масштаб не равен px. Правило по умолчанию (`font_px` из строки стиля,
  иначе формула Task 1.2) — подбор глазами на стенде; число фиксирует лид на стадии 4.
- **Поле `label`.** В r1 `label` у фигуры значит «идёт в разметку». У точек `overlay` `label` — текст подписи.
  `scene_from_overlay` кладёт подпись отдельной фигурой `text`, без поля `label`.
- **Пропущенный кадр при `max_fps`.** Кадр отбрасывается (`None`), не идёт дальше без рисунка: иначе показ мигает.
- **Слепой тест A11** (`test_overlay_port_join_catalog.py:55-57`) — см. §4.
- **Фикстура** `multiprocess_prototype/recipes/tests/fixtures/letter_robot_sim_pre_c30.yaml` содержит `circle_draw` и
  `draw_overlay` — снимок истории, не трогается.
- **`inspection_basic.yaml`** не имеет блока `displays:` (grep 2026-11-11); что показывает его дисплей — Task 4.2
  выясняет до правки. Стартуют ли `inspection_basic`/`inspection_full` на `main` — не проверено (r1 `:288`).
- **`frame_saver` в `color_inspect`** (`recipes/color_inspect.yaml:113-130`): какой кадр он пишет сегодня (чистый или
  с контуром), Task 2.2 сохраняет как есть.
- **Комментарий о pickle** в `ml_inference/plugin/plugin.py:206-208` устарел (Task 4.1 transport-single-policy) —
  строка отчёта, не правка.
- Числа CTO — macOS arm64, Python 3.12.13, cv2 4.13.0, PIL 12.2.0 (r1 `:225`); стенд и Orin не мерились.
