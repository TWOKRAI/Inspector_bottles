# Task 6.3 — справка: посылка, контракт ml_train, расхождения со старой 2.3

Родитель: [phase-6-task-6.3.md](phase-6-task-6.3.md) (бриф-форма). Здесь — справочные разделы брифа, вынесенные по размеру.

## Посылка (код на `87dd240dc`; не перемерять)

1. **Генератор** — `Services/dataset_gen/core/layer_scene.py`: `LayerSceneGenerator.from_yaml(path, *, seed=None)` (`:210-213`),
   `num_classes`/`class_names`/`symmetry_map` (`:231-244`), `generate_sample(class_index=None, rng=None)` (`:247-332`).
   Нет атрибута `class_registry` → `export._write_class_registry` (`export.py:99-104`) `classes.json` **не пишет**.
2. **Экспорт** — `Services/dataset_gen/export.py`: `export_splits(generator, out_dir, splits, image_format="png",
   labels_format="csv", seed=0)` (`:107-143`); rng сплита `default_rng((seed, _name_seed(name)))` (`:133`) — от seed и имени,
   не от порядка ключей; внутренний `rng` генератора экспорт **не трогает**. Раскладка: `<out>/<split>/images/{ci:03d}/{i:05d}.png`
   (`:80`) + `<out>/<split>/labels.csv` (`:146-153`), колонки `_LABEL_FIELDS` (`:35-45`). Кадр пишется `RGB2BGR` → `imwrite_unicode` (`:81`).
3. **Превью** — `Services/dataset_gen/preview.py`: `save_preview_grid(generator, path, n=16, cols=4, rng=None, caption_height=22)`
   (`:43-78`); размер сетки `(cols·tile_w, ceil(n/cols)·(tile_h + caption_height))`; каталог файла создаёт сама (`:76`).
   Шрифт подписи — системный (`:17-31`): байты сетки зависят от машины.
4. **Контракт `ml_train` для `source: exported`** (только чтение) — см. раздел «Контракт ml_train» ниже.
5. **Пресеты.** `Services/line_sim/presets/letters_layered.yaml` — боевой пресет стенда (`apps/line_sim/pipeline.yaml:92,196`
   `preset_path`), слои `disk` (static) + `letter` (`class://`), `catalog_dir: ../../../data/line_sim/letters_ink` (4 класса
   А К Р Х — `data/` вне git, на машине есть). `Services/line_sim/presets/letters_disk.yaml` — пресет `ru_letters_real`
   (каталог `data/dataset_gen/ru_letters_real/sprites`, на машине отсутствует, `layers: []`) — **не** первый продукт.
   `Services/dataset_gen/presets/*.yaml` — пресеты `GeneratorConfig`: их перечисляет `DatasetGenService` (`service.py:34`) и
   показывает вкладка GUI «neural» (`test_neural_sections.py:44`) — пресет слоёв туда класть нельзя.
6. **Фон стенда** — `apps/line_sim/pipeline.yaml:132-134`: `[{solid: [0, 0, 0]}, {tile: data/line_sim/belt_tile.png}]` — путь
   **от корня репозитория**; в пресете `tile:` резолвится **от каталога файла пресета** (`layer_scene.py:186`,
   `preset.resolve_path`). `belt_tile.png` — RGBA 410×484. Поперечное смещение стенда — `pipeline.yaml:153` `[10, 20]`.
   Вырез конвейера — `multiprocess_prototype/recipes/letter_robot_sim.yaml:249-253` (`radius`, `1.0`, `14`, `output_size 128`).
7. **Ограда `preset.commit`** — `Services/layer_render/preview.py:150-179`: `confine_preset_paths` проверяет
   `train.background_layers[*].tile` (`_train_tile_paths`, `:172`); корни — корень репозитория + каталог пресета
   (`Plugins/sim/scene_source/plugin.py:794`). `../../../data/line_sim/belt_tile.png` от `Services/line_sim/presets/` — внутри корня.
   `preset.commit` пишет только изменившиеся top-level ключи клиента (`plugin.py:738`); ключ, которого нет в dict клиента,
   из файла не удаляется.
8. **Граница слоёв** — `.sentrux/rules.toml:157-177`: `dataset_gen` не импортирует `line_sim`; `max_cycles = 2` (`:31`; факт — 0 циклов, замер лида 2026-10-14, см. TRAPS брифа).

## Контракт ml_train (`source: exported`, только чтение)

| # | Что читает | file:line |
|---|---|---|
| K1 | `root/train/` есть → `ExportedDataset(root/"train")`; `root/val/` есть → val из него, иначе `val_split`; `root/test/` — опц. | `Services/ml_train/data.py:242-258` |
| K2 | метки: `labels.csv` (`csv.DictReader`), иначе `labels.json`; иначе `FileNotFoundError` | `data.py:332-341` |
| K3 | колонки строки: `filename` (путь от каталога сплита), `class_index` (int), `angle_sin`, `angle_cos` (float), `angle_valid` (строка `True`/`False`), `class_name`, `symmetry` | `data.py:80-93`, `:344-348`, `:361-375` |
| K4 | картинка: `cv2.imdecode(IMREAD_COLOR)` → `BGR2RGB` → CHW float `/255` → `v2.Resize(image_size)` → `Normalize(mean, std)`; `image_size` по умолчанию `(128, 128)` | `data.py:47-53`, `:80-86`, `:134-156`; `config.py:81`, `:45-46` |
| K5 | `class_names` — по `class_index`/`class_name` строк **train**; `symmetry_map` — из колонки `symmetry` train; `class_index` val ≥ числа классов train → `ValueError`; `classes.json` не читается | `data.py:270-285`, `:351-375` |
| K6 | цель: `{class_index: long, angle: float32[2] (sin, cos), angle_valid: bool}`; train-лоадер `drop_last`, если строк > `batch_size` | `data.py:56-61`, `:179-192` |

Для `symmetry: none` `encode_angle` даёт `(sin θ, cos θ)` (`Services/dataset_gen/core/symmetry.py:164-176`).

## Расхождения со старой 2.3 и решения

| Старая 2.3 | Здесь | Почему |
|---|---|---|
| `Services/line_sim/tools/export_sim_crops.py` | `Services/dataset_gen/tools/export_sim_crops.py` (имя то же) | генератор, экспорт и превью — в `dataset_gen`; CLI импортирует только `dataset_gen`; рядом `cut_real_disks.py`, `align_sprites.py`; тесты `Services/dataset_gen/tests` идут в `medium` без окна, `Services/line_sim` — только в окне (`scripts/machine_gate_timed.txt`). Имя сохранено — его называет правило рамки `plan.md:29` |
| `Services/line_sim/presets/sim_crops/letters_disk.yaml` (отдельный YAML) | секция `train:` в `Services/line_sim/presets/letters_layered.yaml` | решение 6.2: продуктовые данные обучения — секция `train` **того же** пресета, что рисует сим; отдельный файл повторил бы `catalog_dir` и `layers` и разошёлся бы с симом при первой правке редактором. → «Решения» 1 (принято лидом 2026-10-14) |
| «`letters_layered.yaml` + `background_layers` стенда» | `train.background_layers` с путём от каталога пресета | `tile:` резолвится от файла пресета, не от корня (посылка 6) |
| — | `--out` обязан не существовать или быть пустым | старые файлы прошлого прогона сломали бы побайтность и попали бы в `ml_train` мимо `labels.csv` |
| `Services/line_sim/presets/README.md` — рецепт | тот же файл, два раздела | рецепт живёт рядом с пресетом |
| тесты `Services/line_sim/tests/test_acceptance_export_sim_crops.py` | `Services/dataset_gen/tests/test_acceptance_6_3_export_cli.py` | CLI в `dataset_gen` |
| — | 6.3.0: байтовый литерал на выход генератора до кода | передача 6.2 «Для 6.3» |

## Цели break-injection (стадия 5)

| # | Инъекция | Предсказано красным | Предсказано зелёным |
|---|---|---|---|
| E1 | CLI игнорирует `--seed` (всегда `0`) | ACC 3 якорь «seed 8 — другие байты» | ACC 3 равенство, ACC 1 |
| E2 | `out.mkdir()` до загрузки конфига | ACC 5 «`--out` не создан» (4 случая) | ACC 1–4 |
| E3 | ошибка конфига → `print(exc, file=sys.stderr); return 1` (текст исключения без префикса `<путь>: <тип>:`, без `SystemExit`) | ACC 5 в процессе (`SystemExit` нет), ACC 5 подпроцессом (код 1 есть, нет подстроки `<путь>: FileNotFoundError:`) | ACC 1–4 |
| E4 | нет проверки непустого `--out` | H1 | ACC 1–5 |
| E5 | сплиты перепутаны (`train` ← `--val`) | ACC 1 (10/4), ACC 4 (6/2) | ACC 2 (формы те же), ACC 3 |
| E6 | `labels_format="json"` | ACC 1 (`labels.csv` нет), ACC 4 (строки читаются из `labels.csv`), RED 9 | ACC 2 (`ml_train` читает json, `data.py:338-340`) |
| E7 | превью на `np.random.default_rng()` без seed | H4 | ACC 1–5, H3 |
| E8 | пресет B: `tile: data/line_sim/belt_tile.png` | H5 | ACC 1–5 (синтетика) |
| E9 | ветка `ValidationError` → `f"{args.config}: {type(exc).__name__}: {exc}"` (полный `str(exc)`) | ACC 5 `no_catalog`, H7 | ACC 1–4, ACC 5 `invalid_train` |

Род 2 — `junior`/haiku по таблице, плюс 2–4 своих инъекции с предсказанием до прогона. Прежняя E7 («превью на `rng=None`») —
эквивалентный мутант: внутренний поток генератора и есть `default_rng(args.seed)` (`layer_scene.py:208`), в матрицу не входит.

## Открыто (известно, не чинится в 6.3)

- Оракул G1 опирается на то, что каталог не обрезает/не масштабирует спрайт и композиция при альфе 255 даёт цвет спрайта точно —
  проверено пробами ревьюера стадии 0 (2026-10-14, `87dd240dc`): G1 и G1-radius равны выходу генератора на всех 6 кейсах;
  стоп-правило 6.3.0 остаётся: расхождение на SHA шага 1 = стоп, не подгонка.
- Литералы 6.3.0 сняты на win32 (cv2 той же версии, что m4) — на другой машине красный может быть сменой версии.
- sentrux не видит импорт формы `from Services.<pkg> import <module>` (замер лида, TRAPS) — граница держится дисциплиной записи,
  не проверкой.
- Экспорт может упасть посреди прогона (сторона > 4000 px проверяется на сэмпле — «Открыто» 6.2); частичный `--out` остаётся,
  повторный запуск требует нового каталога.
- stdout CLI (`<сплит>: N сэмплов -> путь`) тестами не закреплён — выживший E10, предсказан.
- H3 (превью не меняет экспорт) держится построением, убивающего мутанта нет; «превью на своём rng» стережёт H4 (E7).
- Трейлер `Layer: Services` в `59558a638` (список хука — строчными); историю не переписывали — на SHA ссылаются goldens и план.
- Ключ `train` в боевом пресете стенда: редактор (`preset.commit`) секцию не удаляет (посылка 7), но и не показывает; правка
  `layers` в редакторе меняет обучающие данные — это и есть цель, но без уведомления.
- Реальный прогон (ACC 6) проверяет форму и глаз лида на сетке, не качество обучения; сравнение вырезов сима с реальными
  вырезами — letters-retrain Ф1.
- `importorskip("torch")` может тихо пропустить ACC 2 в окружении без torch — лид смотрит `-rs`.
- Шаг 1 — `Level: Middle+` вопреки «Middle» владельца для 6.3: независимый оракул и подбор кейсов — не типовая работа.

## Предсказания лида на коде `397843e98` (записаны до прогона, 2026-10-14)

Файлы: А = `test_acceptance_6_3_export_cli.py` (13), Н = `test_hazards_6_3_export_cli.py` (10), Л = литерал 6.3.0 (20 — зелёный во всех строках).
Правки — в `Services/dataset_gen/tools/export_sim_crops.py` (строки по `397843e98`), E8 — в пресете.

| # | Инъекция | Предсказано красным | Предсказано зелёным |
|---|---|---|---|
| E1 | `--seed` игнорируется: `0` в `_load_generator`, `export_splits(seed=0)`, `default_rng(0)` | А `same_seed_same_bytes` (якорь seed 8), Н `h4` (якорь «другой seed — другая сетка») | остальные А, Н |
| E2 | `out.mkdir(parents=True, exist_ok=True)` перед `_load_generator` | А `bad_config` ×4, А `module_entry_bad_config` | остальные А, Н1–Н6; Н7 — не предсказываю (проверяет ли `--out`) |
| E3 | загрузка пресета: `except Exception as exc: print(exc, file=sys.stderr); return 1` вместо `_load_generator` | А `bad_config` ×4, А `module_entry_bad_config`, Н `h7` | остальные |
| E4 | проверка непустого `--out` удалена (стр. 95–96) | Н `h1_nonempty…`, Н `h1_out_is_a_file…` | А все, Н `h1_empty…` |
| E5 | `{"train": args.val, "val": args.train}` | А `layout_and_row_counts`, А `labels_columns…`, А `second_product…` | А `png_square` (14 всего), А `ml_train`, А `same_seed`, А `images_match` |
| E6 | `export_splits(..., labels_format="json")` | А `layout…`, А `labels_columns…`, А `images_match…`, А `second_product…` | А `ml_train`, А `preview_grid` |
| E7 | превью `rng=np.random.default_rng()` без seed | Н `h4` | Н `h3`, А все |
| E8 | пресет: `tile: data/line_sim/belt_tile.png` | Н `h5` | А все |
| E9 | ветка `ValidationError` → `f"{config}: {type(exc).__name__}: {exc}"` | А `bad_config[no_catalog]`, Н `h7` | А `bad_config[invalid_train]`, остальные |
| E10 | stdout: `{frames}` вместо `{frames * generator.num_classes}` | — (выживет: stdout не в приёмке, известно) | все |
| E11 | `_positive_int`: `value < 0` вместо `value < 1` | Н `h2_train_zero…` | остальные |
| E12 | `n=4` вместо `_PREVIEW_COUNT` | А `preview_grid` (размер 512×600) | Н `h3`; Н `h4` — зелёный (равенство двух прогонов) |

**Наблюдено** (2026-10-14, `397843e98`, worktree `-inj`, `junior`; база 43 passed = 13 + 10 + 20; откат после каждой строки, итог `git status` пуст):

| # | Красных | Наблюдено | Против предсказания |
|---|---|---|---|
| E1 | 2 | А `same_seed_same_bytes`, Н `h4` | точно |
| E2 | 6 | А `bad_config` ×4, А `module_entry_bad_config`, Н `h7` | больше: Н `h7` (не предсказывал) |
| E3 | 6 | А `bad_config` ×4, А `module_entry_bad_config`, Н `h7` | точно |
| E4 | 2 | Н `h1_nonempty…`, Н `h1_out_is_a_file…` | точно |
| E5 | 3 | А `layout…`, А `labels_columns…`, А `second_product…` | точно |
| E6 | 5 | А `layout…`, А `labels_columns…`, А `images_match…`, А `second_product…`, Н `h1_empty_existing_out_accepted` | больше: Н `h1_empty…` |
| E7 | 1 | Н `h4` | точно |
| E8 | 1 | Н `h5` | точно |
| E9 | 2 | А `bad_config[no_catalog]`, Н `h7` | точно |
| E10 | 0 | — | точно: выживший предсказан (stdout вне приёмки) — «Открыто» |
| E11 | 1 | Н `h2_train_zero…` | точно |
| E12 | 1 | А `preview_grid` | точно |

Итог: 12/12 по предсказанному набору; точно 10, красных больше 2, меньше 0; выживший 1 (E10, предсказан).
Литерал 6.3.0 зелёный во всех строках.

**ACCEPTANCE 6 — прогон лида** (2026-10-14, `397843e98`, боевой `letters_layered.yaml`, `data/line_sim` junction из main-checkout):
экспорт `--train 20 --val 5 --seed 0 --preview` — 6 с, exit 0; `train/labels.csv` 80 строк, `val` 20; смоук `ml_train`
`source: exported` — батч `(16, 3, 128, 128)` float32, цели `class_index (16,)`, `angle (16, 2)`, `angle_valid (16,)`;
`class_names ['А', 'К', 'Р', 'Х']`; `symmetry_map {А: none, К: none, Р: none, Х: 180}`; train 80 / val 20. Сетка 4×4
глазами: диск целиком в кадре, буква читается, фон — текстура ленты с тёмными щелями, подписи углов согласуются с поворотом.
