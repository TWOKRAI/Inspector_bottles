# Task 6.3 — CLI экспорта обучающих вырезов + пресет первого продукта + смоук `ml_train` (бывш. 2.3)

Фаза: [phase-6-train.md](phase-6-train.md) · план: [plan.md](plan.md) (строка Task 6.3; ребро «Связь с letters-retrain») ·
эталоны: [goldens.md](goldens.md) · предыдущая: [phase-6-task-6.2.md](phase-6-task-6.2.md) (генератор, `91d595e6b`) ·
прежняя спека: [phase-2.md](phase-2.md) «Task 2.3» (написана до 6.2; расхождения сведены ниже) ·
передача 6.2: `docs/handoffs/2026-10-14_task-6.2-lead.md` («Для 6.3») · потребитель: `plans/letters-retrain/plan.md` Фаза 1
(стартует после слияния 6.3).

- **Статус:** [PENDING] (после 6.2 — DONE) · **Level:** Middle (6.3.0 — Middle+) · **Assignee:** developer <!-- lint-language: allow -->
- **Gate:** литерал 6.3.0 закоммичен до кода, инъекции лида по нему записаны; RED тестера → GREEN; инъекции лида
  «предсказано / наблюдено»; `reviewer` APPROVED по SHA с воспроизведением; рамка-grep — 0; `git diff <база>..<sha> -- Services/ml_train` пуст
- **Сессия гейта:** `inspector-bottles-26` (лид полосы С). Координатор: `inspector-bottles-23`.

TASK: 6.3 — одна команда даёт каталог `train/val` обучающих вырезов любого продукта (пресет слоёв с секцией `train`) и
сетку-превью; `ml_train` с `data.source: exported` читает каталог без правок; первый продукт — секция `train` в пресете сима
PLAN: plans/layer-render/plan.md (Ф6, Task 6.3; статус в plan.md правит лид)
ROLE: developer
CHAIN: developer(6.3.0: литерал, свой коммит) -> lead(инъекции по литералу) -> tester(слепая приёмка RED в worktree на коммите литерала) -> you(GREEN + hazard-тесты) -> lead(инъекции) -> reviewer(по SHA)
Module contract: new-lite (`Services/dataset_gen/tools/export_sim_crops.py`: докстринг модуля несёт `Purpose:`, `Public API:`,
`Stability: lite`; `Pre:`/`Post:` — у `main`; роль контракт-тестов играет приёмка тестера `test_acceptance_6_3_*`).
6.3.0 — n/a (только тест). Публичный API `dataset_gen`/`layer_render` не меняется.

## Порядок запуска (`.claude/CLAUDE.md` «Task launch convention»)

| # | Стадия | Кто | Выход | Стоп-условие |
|---|---|---|---|---|
| 0 | ревью этого брифа | `reviewer` (opus), `MODE: plan` | вердикт по брифу | REQUEST_CHANGES → правка брифа, ит.2 |
| 1 | **6.3.0** литерал на выход `LayerSceneGenerator` | `developer` (sonnet, Middle+) | **отдельный коммит** `test(dataset_gen):` | оракул G1 ≠ выходу → стоп, эскалация лиду, оракул не подгонять |
| 2 | инъекции по литералу | лид | таблица «предсказано / наблюдено» L1–L8 в этом файле | выживший → находка, литерал усилить до шага 3 |
| 3 | слепая приёмка | `tester` (sonnet) в worktree на SHA шага 1 | `test_acceptance_6_3_export_cli.py`, RED | RED доказан нуль-заглушкой (см. REDS), заглушка удалена |
| 4 | реализация | `developer` (sonnet, Middle) | GREEN + hazards, коммит | файл вне FILES → стоп, спросить лида |
| 5 | инъекции | лид (род 1), `junior`/haiku по готовой таблице (род 2) | «предсказано / наблюдено» | расхождение = находка |
| 6 | ревью кода | `reviewer` (opus) по SHA | APPROVED с воспроизведением | 2 итерации → `teamlead` |
| 7 | документация | `docs-writer` → `reviewer`(express) | README/STATUS `dataset_gen` | — |
| 8 | прогон на реальных данных | лид | числа в отчёте (ACCEPTANCE 6) | — |

Запрещённые пути **слепого тестера**: запрещено читать версии этих файлов разработчика (ветки, worktree, коммиты после SHA
шага 1) — `Services/dataset_gen/tools/export_sim_crops.py`, `Services/dataset_gen/tests/test_hazards_6_3_export_cli.py`,
`Services/line_sim/presets/letters_layered.yaml` (секция `train`), `Services/line_sim/presets/README.md`. Класть свою
нуль-заглушку по пути `export_sim_crops.py` в своём worktree можно (REDS). Читать можно: этот бриф, `Services/dataset_gen/{export,preview}.py`,
`Services/dataset_gen/core/layer_scene.py`, `Services/ml_train/{data,config}.py`, тесты 6.2.

## Посылка, контракт ml_train, расхождения со старой 2.3

Вынесены в [phase-6-task-6.3-context.md](phase-6-task-6.3-context.md): посылка 1–8 (file:line), контракт `ml_train` K1–K6,
таблица расхождений. Ссылки «посылка N» и «K N» ниже — туда.

## Подзадача 6.3.0 — литерал на выход генератора

Спека — [phase-6-task-6.3.0.md](phase-6-task-6.3.0.md): кейсы G1 и G1-radius (независимый numpy-оракул), G2, G3 (sha256-литералы),
инъекции лида L1–L8 с предсказаниями. Свой коммит до любого кода 6.3.

## DESIGN (решено; набираешь, не выводишь)

**A. `Services/dataset_gen/tools/export_sim_crops.py` (новый).** Докстринг модуля: `Purpose:` (каталог `train/val` обучающих
вырезов из пресета слоёв с секцией `train` + сетка-превью; формат — `export_splits`, читает `ml_train` `data.source: exported`),
`Public API:` (`main(argv: list[str] | None = None) -> int`; запуск `python -m Services.dataset_gen.tools.export_sim_crops`),
`Stability: lite`. **В файле нет слов продукта** — пример команды в докстринге с плейсхолдером `<пресет.yaml>`, не с именем
реального пресета (урок 6.2: комментарий лида поймал тест рамки).

```python
def _positive_int(text: str) -> int:          # argparse type: int >= 1, иначе argparse.ArgumentTypeError
def _non_negative_int(text: str) -> int:      # argparse type: int >= 0, иначе argparse.ArgumentTypeError (default_rng не берёт < 0)
def main(argv: list[str] | None = None) -> int:
    # флаги: --config PATH (обяз.), --out DIR (обяз.), --train N (обяз., _positive_int), --val M (обяз., _positive_int),
    #        --seed S (_non_negative_int, по умолчанию 0), --preview PNG (опц.)
    # 1. out = Path(args.out); out существует и (не каталог или не пуст) ->
    #    raise SystemExit(f"export_sim_crops: --out должен быть пустым или несуществующим каталогом: {args.out}")
    # 2. try: generator = LayerSceneGenerator.from_yaml(args.config, seed=args.seed)
    #    except pydantic.ValidationError as exc:     # первым: подкласс ValueError
    #        reason = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}"
    #                           for e in exc.errors(include_input=False, include_url=False))
    #        raise SystemExit(f"{args.config}: {type(exc).__name__}: {reason}") from exc
    #    except (OSError, ValueError, yaml.YAMLError) as exc:
    #        raise SystemExit(f"{args.config}: {type(exc).__name__}: {exc}") from exc
    #    (нечитаемый tile — ValueError imread_unicode / FileNotFoundError np.fromfile)
    # 3. paths = export_splits(generator, out, {"train": args.train, "val": args.val}, seed=args.seed)  # png + csv, дефолты
    # 4. args.preview -> save_preview_grid(generator, args.preview, n=16, cols=4, rng=np.random.default_rng(args.seed))
    # 5. print по строке на сплит: f"{name}: {frames * generator.num_classes} сэмплов -> {path}"; return 0
if __name__ == "__main__":
    raise SystemExit(main())
```

Текст ошибки конфига — `<путь --config>: <тип исключения>: <причина>`. Причина `ValidationError` — без `input_value`
(эхо ввода, правило 6.2 «тексты ошибок без входного значения»); причина `FileNotFoundError`/`yaml.YAMLError`/прочих — `str(exc)`:
файл свой, CLI локальный, путь и строка YAML оператору нужны.

Порядок 1 → 2 → 3 обязателен: при ошибке конфига или занятом `--out` на диск не пишется ничего (`out` не создаётся).
Превью — отдельный поток `default_rng(seed)`: экспорт идёт на `default_rng((seed, имя))` и от превью не зависит.
Своего формата меток, своей раскладки, `classes.json`, `--labels-format`, `--test` — нет.

**B. `Services/line_sim/presets/letters_layered.yaml` — дописать в конец файла ключ `train`** (прочие ключи и комментарии
не трогать; комментарий — над ключом, не внутри: `preset.commit` теряет комментарии внутри заменённого ключа):

```yaml
# Секция обучения (layer-render Task 6.3): читают LayerSceneGenerator и
# Services/dataset_gen/tools/export_sim_crops.py; сим секцию не читает. Поля — presets/README.md.
train:
  label: {angle_layer: letter}
  symmetry: {auto_detect: false, overrides: {Х: "180"}}
  background_layers:
    - solid: [0, 0, 0]
    - tile: ../../../data/line_sim/belt_tile.png
  lateral_offset_px: [10, 20]
  crop: {size_mode: radius, radius_scale: 1.0, margin_px: 14, output_size: 128}
  defect_probability: 0.0
```

В каталоге `data/line_sim/letters_ink` нет `meta.yaml` (проверено `find`, 2026-10-14) — симметрия задаётся только секцией.
Источники значений: симметрия — `Services/dataset_gen/presets/real_letters_disk.yaml:30,40` (только класс каталога: override
неизвестного класса — `ValueError` генератора, `layer_scene.py:200-204`); фон и смещение — `apps/line_sim/pipeline.yaml:132-134,153`;
вырез — `letter_robot_sim.yaml:249-253`. `augment` не задаётся (кадр как рисует сим) — «Решения» 2.

**C. `Services/line_sim/presets/README.md` — два раздела в конец:**
1. «Секция `train` — обучающие вырезы»: смысл шести ключей блока B; путь `tile:` — от каталога пресета, не от корня
   (в отличие от `pipeline.yaml`); команда экспорта и YAML-фрагмент `ml_train`:
   `data: {source: exported, root: <out>, image_size: [128, 128], augment: {enabled: false}}`, `model: {angle_head: true}`.
2. «Новый продукт: что скопировать и поменять» — `catalog_dir`, `layers` (`class://`), `train.label.angle_layer`,
   `train.symmetry`, `train.crop` (`radius` | `fixed`), `train.background_layers`; кода не трогать.

## FILES (полный список; нужен другой файл — стоп, спроси лида)

1. `Services/dataset_gen/tools/export_sim_crops.py` (новый) — DESIGN A
2. `Services/line_sim/presets/letters_layered.yaml` — DESIGN B (только дописать ключ `train`)
3. `Services/line_sim/presets/README.md` — DESIGN C
4. `Services/dataset_gen/tests/test_hazards_6_3_export_cli.py` (новый) — hazard-тесты автора, минимум:
   - H1 непустой `--out` (в нём файл `x.txt`) → `SystemExit`, текст содержит путь; байты `x.txt` прежние, других файлов нет;
   - H2 `--train 0` → `SystemExit` с кодом `2` (argparse); `--seed -1` → `SystemExit` с кодом `2`, `--out` не создан;
   - H3 прогон с `--preview` и без него, тот же `--seed` → каталоги `--out` побайтно равны (превью не трогает экспорт);
   - H4 два прогона с одним `--seed` и `--preview` → байты двух PNG-сеток равны;
   - H5 боевой пресет без `data/`: `ScenePreset.from_yaml(letters_layered.yaml)`, `TrainSection.model_validate(preset.train)` без
     ошибки, `Path(preset.resolve_path(tile)).resolve() == (<корень репо>/data/line_sim/belt_tile.png).resolve()` — файл не читается;
   - H7 пресет P без `catalog_dir` (слой `class://` остаётся) → текст `SystemExit` начинается с `<путь>: ValidationError:` и не
     содержит `input_value`;
   - H6 рамка: `rg -in "letter|букв|disk|диск" Services/dataset_gen/tools/export_sim_crops.py` в тесте через `re.search(..., re.I)`
     по тексту файла → `None`.
- тесты тестера (не править): `Services/dataset_gen/tests/test_acceptance_6_3_export_cli.py`
- 6.3.0 (отдельный исполнитель, до этих FILES): `Services/dataset_gen/tests/test_layer_scene_golden_6_3.py`
- документация — `docs-writer` → `reviewer`(express) после APPROVED: `Services/dataset_gen/README.md` (раздел CLI),
  `Services/dataset_gen/STATUS.md`; строка `plan.md:29` (рамка называет `export_sim_crops.py` без пути) и `goldens.md` — лид.

## REDS (тестер, на SHA 6.3.0; каждый красный до кода)

RED доказывается **нуль-заглушкой** (урок `feedback_null_stub_proves_red_on_literals_for_missing_cli.md`): без модуля всё
падает на `ImportError` — это не доказательство. Тестер кладёт в своём worktree одноразовый
`Services/dataset_gen/tools/export_sim_crops.py` с `def main(argv=None): return 0`, прогоняет, каждый тест обязан упасть на
своём утверждении (не на импорте); тест, зелёный на заглушке, усиливается якорем; заглушка удаляется, в отчёте — список
«красный на заглушке: <утверждение>». Тест с `importorskip` в отчёте — `passed`/`failed`, не `skipped` (`pytest -rs`).

1. `test_acceptance_6_3_export_cli.py::test_layout_and_row_counts` — ACCEPTANCE 1.
2. `…::test_png_square_output_size` — ACCEPTANCE 1, PNG 128×128 ×14.
3. `…::test_ml_train_loader_batch` — ACCEPTANCE 2.
4. `…::test_same_seed_same_bytes` — ACCEPTANCE 3 (равенство) + якорь «другой seed — другие байты».
5. `…::test_second_product_zero_code` — ACCEPTANCE 4.
6. `…::test_preview_grid` — ACCEPTANCE 5, сетка `(512, 600)`.
7. `…::test_bad_config_systemexit_with_path[missing|invalid_train|no_catalog|broken_yaml]` — ACCEPTANCE 5 (у `no_catalog` — ещё «нет `input_value`»; у `invalid_train` — «есть `crop.side_px`»).
8. `…::test_module_entry_bad_config` — ACCEPTANCE 5, `python -m` подпроцессом.
9. `…::test_labels_columns_and_angle_encoding` — ACCEPTANCE 1, заголовок и `sin/cos`.

## ACCEPTANCE (слепой tester: синтетика numpy → PNG в `tmp_path`; `data/` не читается; CLI зовётся в процессе через `main([...])`)

**Продукт P** (для 1–3, 5): каталог 2 класса `p0`, `p1` (асимметричные RGBA 64×64, разные цвета); `under.png` — RGBA круг 100 px;
`tile.png` — RGBA **40×160 (ширина 40, высота 160)** numpy; пресет `angle_range_deg: [0, 360]`,
`layers: [{name: under, mode: static, sprite_source: under.png},
{name: obj, mode: static, sprite_source: "class://"}]`, `train: {label: {angle_layer: obj}, symmetry: {auto_detect: false},
background_layers: [{solid: [0, 0, 0]}, {tile: tile.png}], lateral_offset_px: [2, 6],
crop: {size_mode: radius, radius_scale: 1.0, margin_px: 8, output_size: 128}}`. Имя слоя `base` не годится: с `catalog_dir` оно
зарезервировано (`layer_render/preset.py:22,91-97`, `ValueError` «имена зарезервированы ObjectFactory»).
**Продукт Q** (для 4) — продукт (б) 6.2: 2 класса прямоугольных RGBA 60×30, `layers: []`, `angle_range_deg: [123.5, 123.5]`,
`train: {label: {angle_layer: null}, symmetry: {auto_detect: false}, crop: {size_mode: fixed, side_px: 96, output_size: 96}}`.

1. **Раскладка и число строк.** `main(["--config", P, "--out", out, "--train", "5", "--val", "2", "--seed", "0"]) == 0`.
   Множество относительных путей файлов под `out` (POSIX) — ровно 16: `train/labels.csv`, `val/labels.csv`,
   `train/images/000/0000{0..4}.png`, `train/images/001/0000{0..4}.png`, `val/images/000/0000{0,1}.png`, `val/images/001/0000{0,1}.png`;
   `classes.json` нет. `csv.DictReader` → `train` 10 строк, `val` 4; заголовок — ровно
   `filename,class_index,class_name,class_path,angle_deg,angle_sin,angle_cos,symmetry,angle_valid`. В `train` `class_index`
   по порядку `0×5, 1×5`, `class_name` `p0`/`p1`, `symmetry` `none`, `angle_valid` `True`, `0 <= angle_deg < 360`,
   `abs(angle_sin − sin(radians(angle_deg))) < 1e-9` и то же для `cos`. Каждый PNG: `cv2.imdecode(..., IMREAD_UNCHANGED)` —
   `shape == (128, 128, 3)`, `uint8`.
2. **`ml_train` без правок.** `from Services.ml_train.config import DataConfig`, `from Services.ml_train.data import build_dataloaders`
   (`pytest.importorskip("torch")`, `"torchvision"`); `DataConfig(source="exported", root=str(out), image_size=(128, 128),
   batch_size=4, num_workers=0, augment={"enabled": False})`. Первый батч `train_loader`: изображения `(4, 3, 128, 128)` `float32`;
   `class_index` `(4,)` `int64`, значения ⊆ `{0, 1}`; `angle` `(4, 2)` `float32`; `angle_valid` `(4,)` `bool`, все `True`. Первый батч
   `val_loader` — `(4, 3, 128, 128)`. `bundle.class_names == ["p0", "p1"]`; `bundle.symmetry_map == {"p0": "none", "p1": "none"}`.
   Тот же смоук на выходе продукта Q (PNG 96) — батч `(B, 3, 128, 128)` (ресайз `ml_train`). Лид: `git diff --stat <база>..<sha> -- Services/ml_train` — пусто.
3. **Seed.** Два прогона P `--seed 7` в `out1`, `out2` → словари `{отн. путь: sha256}` равны, 16 записей. Якорь: прогон `--seed 8` →
   хотя бы у одного PNG sha256 другой.
4. **Второй продукт, ноль кода.** Тот же `main` на Q, `--train 3 --val 1` → `train` 6 строк, `val` 2; каждый PNG `(96, 96, 3)`;
   `angle_deg` во всех строках `123.5`.
5. **Превью и ошибки.** `--preview <tmp>/sub/grid.png` → файл есть, `PIL.Image.open(...).size == (512, 600)` (4 × 128; 4 × (128 + 22)).
   Плохой `--config` → `pytest.raises(SystemExit)`, `isinstance(e.code, str)`, `e.code.startswith(f"{config_path}: ")`, каталог
   `--out` не создан; четыре случая: `missing` — файла нет (`FileNotFoundError` в тексте); `invalid_train` — пресет P, изменён
   **только** `train.crop.side_px: 1` (в тексте `ValidationError` и `crop.side_px`); `no_catalog` — пресет P без
   `catalog_dir` (в тексте `ValidationError`, нет подстроки `input_value` — у `ScenePreset` нет `hide_input_in_errors`,
   `preset.py:50`; у `TrainSection` он есть, `layer_scene.py:107`, поэтому `invalid_train` эту ветку не проверяет); `broken_yaml` — текст `"a: [1"`. Якорь корректности — ACC 1 на том же P (зелёный после GREEN). Подпроцессом
   `subprocess.run([sys.executable, "-m", "Services.dataset_gen.tools.export_sim_crops", "--config", <нет файла>, "--out", ...,
   "--train", "1", "--val", "1"], capture_output=True, encoding="utf-8", cwd=<корень репо>, env={..., "PYTHONPATH": <корень>,
   "PYTHONUTF8": "1"}, timeout=120)` (`encoding` обязателен: ребёнок пишет UTF-8, родитель на win32 — cp1251) → `returncode == 1`,
   в `stderr` подстрока `f"{config_path}: FileNotFoundError:"` (формат DESIGN A; одного кода возврата мало — E3).
6. **Реальные данные — лид** (из корня main-checkout, `data/` на месте; `SCR` = scratchpad сессии):
   ```bash
   G="$(git rev-parse --path-format=absolute --git-common-dir)/../scripts/machine_gate.sh"
   PY=D:/PROJECT_INNOTECH/Inspector_vision/Inspector_bottles/.venv/Scripts/python
   bash "$G" light inspector-bottles-26 env PYTHONUTF8=1 $PY -m Services.dataset_gen.tools.export_sim_crops \
     --config Services/line_sim/presets/letters_layered.yaml --out "$SCR/sim_crops" --train 20 --val 5 --seed 0 \
     --preview "$SCR/grid.png"
   ```
   Смоук `ml_train` — скрипт в scratchpad (`build_dataloaders(DataConfig(source="exported", root="$SCR/sim_crops", batch_size=16,
   augment={"enabled": False}))`, печать формы первого батча, `class_names`, `symmetry_map`), запуск `$PY <скрипт>` через гейт `light`.
   В отчёт: время экспорта (с), строк `train`/`val` (ожидание `80`/`20`), `class_names` (ожидание `['А', 'К', 'Р', 'Х']` в порядке
   каталога), `symmetry_map` (ожидание `Х: 180`, прочие `none`), форма батча (ожидание `(16, 3, 128, 128)`), путь к `grid.png` и
   описание сетки глазами (`Read` PNG): диск целиком в кадре, буква читается, щели ленты чёрные.
7. **Процесс.** Слепой тестер RED (на заглушке) → GREEN; инъекции лида — таблица ниже «предсказано / наблюдено»; `reviewer` APPROVED
   по SHA с воспроизведением (команда + вывод); `rg -in "letter|букв|disk|диск" Services/dataset_gen/tools/export_sim_crops.py` — exit 1
   (не `rg -E` — в ripgrep это `--encoding`; не `grep -i` — Git Bash не сворачивает регистр кириллицы); `sentrux check .` — чисто,
   циклов не больше базы, на состоянии, где тестовые файлы **отслеживаются** (после `git add`): sentrux сканирует только `git ls-files`.

## TESTS (через гейт; main `.venv`, `PYTHONPATH` = корень worktree; никакого `uv sync`)

```bash
G="$(git rev-parse --path-format=absolute --git-common-dir)/../scripts/machine_gate.sh"
PY=D:/PROJECT_INNOTECH/Inspector_vision/Inspector_bottles/.venv/Scripts/python
bash "$G" light  inspector-bottles-26 env PYTHONPATH="$PWD" $PY -m pytest -q --tb=short -rs Services/dataset_gen/tests/test_layer_scene_golden_6_3.py
bash "$G" light  inspector-bottles-26 env PYTHONPATH="$PWD" $PY -m pytest -q --tb=short -rs Services/dataset_gen/tests/test_acceptance_6_3_export_cli.py Services/dataset_gen/tests/test_hazards_6_3_export_cli.py
bash "$G" medium inspector-bottles-26 env PYTHONPATH="$PWD" $PY -m pytest -q --tb=short Services/dataset_gen/tests   # база: 277 passed, 1 skipped (после 6.2)
bash "$G" medium inspector-bottles-26 env PYTHONPATH="$PWD" $PY -m pytest -q --tb=short Services/ml_train/tests      # только регресс; база — лид
bash "$G" --timed medium inspector-bottles-26 env PYTHONPATH="$PWD" $PY -m pytest -q --tb=short Services/line_sim/tests/test_hazards_1_1b_tool_preset.py  # окно; пресет B
$PY -m ruff check -q Services/dataset_gen
```

Лид, в своём окне: `bash "$G" heavy inspector-bottles-26 env PYTHONPATH="$PWD" $PY -m pytest -q --tb=short Services/line_sim Plugins/sim`
(база 1382 passed, 4 skipped — пресет стенда изменён ключом `train`). Код 75 — пропуск гейтом («NO WINDOW»), не красный прогон;
субагент без окна пишет «NO WINDOW» и заканчивает. Bash, запущенный из Python на Windows, стартует WSL — гейт звать только из
Bash-инструмента; тест подпроцессом зовёт `sys.executable`, не `bash`.

## OUT OF SCOPE

- Само обучение, подбор фотометрии `train.augment`, каталог 33 букв и шрифты — letters-retrain Ф1.
- `class_registry`/`classes.json` для `LayerSceneGenerator` («Решения» 3); `--labels-format`, `--test`, параллельный экспорт.
- Правки `Services/ml_train/` (в т. ч. тестов там); `Services/dataset_gen/core/*`, `export.py`, `preview.py`; `Services/layer_render/*`.
- Эффекты сцены и `schema_version` — 3.1; пересчёт путей `tile:` в `to_yaml` — follow-up 6.2.
- **Запрещённые пути для всех агентов:** `Services/device_hub/`, `Services/robot_comm/`, `Plugins/sim/robot_host/`,
  `plans/robot-protocol-v2/`, `apps/line_sim/pipeline.yaml`, `scripts/machine_gate*`, `.claude/settings.json`,
  `.claude/skills/coordinator/`, `.claude/skills/project-rules/`, `Services/ml_train/` (запись).

## TRAPS

- **Слова продукта в CLI** — в докстринге, `help=`, комментариях и тексте ошибок. Перед прогоном:
  `rg -in "letter|букв|disk|диск" Services/dataset_gen/tools/export_sim_crops.py` — exit 1. Пример команды — с `<пресет.yaml>`.
- **Путь `tile:` в пресете — от каталога пресета** (`../../../data/line_sim/belt_tile.png`), не `data/line_sim/belt_tile.png`
  из `pipeline.yaml`: иначе генератор падает при создании (нечитаемый файл — исключение, `layer_scene.py:184-191`).
- **Override симметрии только для класса каталога** — лишний класс → `ValueError` (`layer_scene.py:200-204`); весь список из
  `real_letters_disk.yaml:34-40` не копировать.
- **`"180"` в кавычках** — без них YAML даёт int.
- **Не писать в `out` до загрузки конфига** — порядок DESIGN A 1 → 2 → 3; не удалять чужие файлы в `--out` (никакого `rmtree`).
- **Не передавать один `rng` экспорту и превью** — превью свой `default_rng(seed)`; экспорт берёт rng сплитов сам.
- **Размещение импорта ml_train** (замер лида 2026-10-14: scratch-worktree на `87dd240dc`, файлы под `git add`,
  `max_cycles` временно 0): база — 0 циклов (комментарий «текущее 1» в `.sentrux/rules.toml:31` устарел); заглушка
  `Services/dataset_gen/tests/test_x.py` с `from Services.ml_train.data import build_dataloaders` внутри функции — 0 циклов,
  на верхнем уровне модуля — тоже 0; положительный контроль `_cyc_a.py ↔ _cyc_b.py` (`from Services.dataset_gen._cyc_b import B` /
  `from Services.dataset_gen._cyc_a import A`) → «✗ max_cycles: Found 1 circular dependencies» с обоими файлами — sentrux считает
  циклы **по файлам**. **Решение:** тест ACC 2 живёт в `Services/dataset_gen/tests/` и импортирует `Services.ml_train.data`
  внутри функции после `importorskip` (torch остаётся необязательным при сборке тестов). `sentrux check .` после `git add` —
  пост-проверка ACC 7, не стоп-условие.
- **Форма импорта, которую sentrux не видит.** `from Services.dataset_gen import _cyc_b` (пакет → модуль) не резолвится: тот же
  цикл a↔b в такой записи прошёл зелёным. В коде и тестах 6.3 импорты — только `from Services.<pkg>.<module> import <name>`.
- **`Services/dataset_gen/presets/`** — не класть туда пресет слоёв (его подхватят сервис и GUI как `GeneratorConfig`).
- **Сетка-превью машинозависима** (системный шрифт) — в литералы sha256 её не брать, только равенство двух прогонов на одной машине.

## Цели break-injection (стадия 5)

Матрица E1–E9 с предсказаниями «красным / зелёным» — в
[phase-6-task-6.3-context.md](phase-6-task-6.3-context.md#цели-break-injection-стадия-5) (её исполняет лид, не разработчик).

## Открыто

Список «известно, не чинится в 6.3» — в [phase-6-task-6.3-context.md](phase-6-task-6.3-context.md#открыто-известно-не-чинится-в-63).

## Решения (рекомендация, принята лидом 2026-10-14, владелец может отменить)

1. **Секция `train` первого продукта — в боевом `Services/line_sim/presets/letters_layered.yaml`**, не в отдельном файле с копией
   `catalog_dir`/`layers`: один файл = одна сцена для сима и обучения; копия разошлась бы с симом после первой правки редактором.
   Цена: стенд читает файл с ключом, который не использует; прогон `line_sim + Plugins/sim` после правки обязателен.
2. **Без `train.augment` в 6.3** — экспорт = кадр сима как есть; фотометрию подбирает letters-retrain Ф1 правкой пресета, без кода.
3. **Без `classes.json` (`class_registry`) в 6.3** — `ml_train` берёт классы и симметрию из `labels.csv` (`data.py:270-285`),
   другого потребителя нет; вернуться, если появится разметка классов (`meta.yaml`) в обучении.

HANDOFF IN: базовые числа — после 6.2: `dataset_gen` 277 passed + 1 skipped, `layer_render` 1645, `line_sim + Plugins/sim`
1382 + 4 skipped; база `ml_train/tests` — лид до шага 4. SHA шага 1 лид вписывает сюда для тестера и ревьюера.
