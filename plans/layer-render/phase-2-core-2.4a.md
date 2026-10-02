# layer-render — Task 2.4a (вынесена из phase-2-core.md: файл фазы перерос бюджет 32 КБ)

Фаза: [phase-2-core.md](phase-2-core.md) · план: [plan.md](plan.md)

### Task 2.4a — `ScenePreset` и каталог классов переезжают в `layer_render`, старые места — реэкспорт (часть бывш. 2.4)

- **Статус:** [PENDING] волна 5 · **Level:** Middle (Sonnet 5.5) · **Assignee:** tester → developer → инъекции лида → reviewer
- **Module contract:** public-api-change (`layer_render` получает `preset`, `catalog`, `metadata`, `procedural_backgrounds`;
  `line_sim.core.preset.ScenePreset`, `dataset_gen.core.{catalog,metadata,backgrounds}` и `CatalogConfig`/`SymmetryType` из
  `dataset_gen.core.config` — реэкспорт)
- **CHAIN:** `tester`(RED, worktree до кода) → `developer`(GREEN) → инъекции лида → `reviewer`
- **Dependencies:** 2.3 (DONE). После — 2.4b (фабрика) и 3.1 (пресет v2 расширяет `ScenePreset` уже в `layer_render`)
- **Gate:** RED тестера → GREEN; инъекции записаны; `reviewer` APPROVED по SHA; тест рамки
  `test_acceptance_1_1_background_layers.py::test_frame_rule_grep_zero_matches_in_package_python_sources` зелёный (он сканирует
  все `.py` пакета кроме `tests/`, новые файлы — автоматически)

**Goal:** пресет сцены и каталог классов — код `layer_render`; `line_sim` и `dataset_gen` только реэкспортируют. Решение
владельца 2026-10-02: каталог переезжает **целиком** (вердикт CTO п. 2), вместе с `CatalogConfig`, метой классов и
процедурными фонами. Поведение не меняется ни на байт; ни один потребитель вне `Files` не правится.

#### Files

1. `Services/layer_render/preset.py` (новый) — из `Services/line_sim/core/preset.py`: `ScenePreset`, `CLASS_SPRITE_SOURCE`,
   `_RESERVED_LAYER_NAMES`, `_looks_like_relative_path` (тела без изменений логики; `LayerSpec` — из `Services.layer_render.layers`).
   Блок конфига стенда (`REPO_ROOT`, `DEFAULT_DEFECT_PROBABILITY`, `resolve_repo_path`, `apply_defect_override`,
   `load_scene_preset`) **не переезжает** — это конфиг стенда, не механизм.
2. `Services/layer_render/catalog.py` (новый) — из `Services/dataset_gen/core/catalog.py`: `SpriteCatalog`, `ClassEntry`,
   `SPRITE_SUFFIXES`, `BACKGROUND_SUFFIXES`, `_cover_crop`; плюс `CatalogConfig` из `dataset_gen/core/config.py:209-224`.
3. `Services/layer_render/metadata.py` (новый) — весь `Services/dataset_gen/core/metadata.py` (`ClassMeta`, `load_meta`,
   `write_meta`, `META_FILENAMES`) + `SymmetryType` из `dataset_gen/core/config.py:20`.
   `Services/layer_render/procedural_backgrounds.py` (новый) — весь `Services/dataset_gen/core/backgrounds.py`
   (имя `backgrounds.py` не берётся: рядом `background.py` — стек слоёв фона Task 1.1).
4. Реэкспорт (явные имена, не `*`; в `__all__`, иначе ruff F401 снимет импорт): `Services/line_sim/core/preset.py` (два имени +
   блок стенда остаётся определённым здесь), `Services/dataset_gen/core/catalog.py`, `metadata.py`, `backgrounds.py`,
   `config.py` (`CatalogConfig`, `SymmetryType` — импортом из `layer_render`; `GeneratorConfig.catalog` остаётся тем же классом).
   Реэкспорт шире списка переехавшего (ревью спеки, B3): `catalog.py` сохраняет нынешний реэкспорт `imread_unicode`,
   `imwrite_unicode` из `layer_render.io` (Task 2.1; из старого `catalog` их импортируют 65 строк, например
   `holdout_eval.py:34`); `backgrounds.py` реэкспортирует приватный `_GENERATORS` (потребитель —
   `dataset_gen/tests/test_backgrounds.py:10`). Блок стенда в `line_sim/core/preset.py` (`REPO_ROOT`,
   `DEFAULT_DEFECT_PROBABILITY`, `resolve_repo_path`, `apply_defect_override`, `load_scene_preset`) входит в `__all__` вместе с
   реэкспортом.
5. `Services/layer_render/__init__.py` (`__all__` + новые публичные имена), `README.md` (Public API и шапка `:1-4` — «ничего
   не знает про `dataset_gen`» остаётся верным, но «стек слоёв фона» уже не весь сервис), `STATUS.md`;
   `docs/maps/layer_render.md`
6. `Services/dataset_gen/README.md`, `STATUS.md`; `Services/line_sim/README.md` — где что теперь определено
- тесты тестера: `Services/layer_render/tests/test_acceptance_2_4a_preset_catalog.py`

#### DESIGN

- Переезд, не переписывание: тела функций и классов — дословно; меняются только строки импорта и слова рамки в докстрингах.
- Рамка `letter|букв|disk|диск` (без учёта регистра) — в переехавших докстрингах переписать, смысл сохранить: `preset.py:186`,
  `:188` («разных дисках Windows», «кросс-дисковый» → «разных томах», «между томами»); `catalog.py:4`, `:42`, `:54` (пример
  иерархии `letters/vowels/А` → нейтральный, например `shapes/round/A`), `:70` («с диска» → «из файла»). В `metadata.py` и
  `backgrounds.py` совпадений нет (разведка 2026-10-02). Исполнитель проверяет запуском теста рамки, не глазами.
- Направление импортов: `dataset_gen` → `layer_render` разрешено; `layer_render` → `dataset_gen`/`line_sim` запрещено
  (`.sentrux/rules.toml:157-172`, сканеры в `layer_render/tests`). Новые модули импортируют только stdlib, cv2, numpy, yaml,
  pydantic и `Services.layer_render.*`.
- Идентичность: после переезда старый путь отдаёт **тот же объект** (`is`), не копию класса; `SymmetryType` — тот же `Literal`
  (проверка `is` для него вакуумна: `typing` кэширует `Literal[...]`, копия определения тоже даст `True`; копию ловит AST в A2).
- `REPO_ROOT` остаётся в `line_sim/core/preset.py` с `parents[3]`; в `layer_render` его нет.
- Счётчик импортов до/после (требование плана) = A6: число строк по шаблонам **вне `Files`** до и после равно, потому что
  потребители не правятся. Строки внутри `Files` (`catalog.py:28-30`, `metadata.py:27`) переезд удаляет законно.

#### Acceptance

- [ ] A1. Идентичность и `__module__` (каждое имя — отдельный кейс):
      `Services.line_sim.core.preset.{ScenePreset, CLASS_SPRITE_SOURCE}`, `Services.line_sim.ScenePreset`,
      `Services.line_sim.core.ScenePreset` `is` `Services.layer_render.preset.<имя>`;
      `Services.dataset_gen.core.catalog.{SpriteCatalog, ClassEntry, SPRITE_SUFFIXES, BACKGROUND_SUFFIXES}` `is`
      `Services.layer_render.catalog.<имя>`; `Services.dataset_gen.core.config.CatalogConfig is Services.layer_render.catalog.CatalogConfig`;
      `Services.dataset_gen.core.metadata.{ClassMeta, load_meta, write_meta, META_FILENAMES}` и
      `Services.dataset_gen.core.config.SymmetryType` `is` `Services.layer_render.metadata.<имя>`;
      `Services.dataset_gen.core.backgrounds.{procedural_background, gradient_bg, brushed_metal_bg, conveyor_belt_bg, speckled_bg}`
      `is` `Services.layer_render.procedural_backgrounds.<имя>`; `Services.dataset_gen.core.backgrounds._GENERATORS is
      Services.layer_render.procedural_backgrounds._GENERATORS`; `Services.dataset_gen.core.catalog.{imread_unicode,
      imwrite_unicode}` `is` `Services.layer_render.io.<имя>`. Пакетный уровень: `Services.dataset_gen.core.{SpriteCatalog,
      ClassMeta, SymmetryType, load_meta, write_meta}` и `Services.dataset_gen.{ClassMeta, SymmetryType}` — тот же объект.
      Для классов и функций `__module__` = новый модуль. `SymmetryType is ...` — вакуумна (кэш `typing`), её держит A2.
- [ ] A2. Старые модули не определяют переехавшее (AST): в `dataset_gen/core/catalog.py`, `metadata.py`, `backgrounds.py` —
      ни одного `def`/`class`; в `dataset_gen/core/config.py` нет `class CatalogConfig`, в `config.py` и `metadata.py` нет
      присваивания `SymmetryType`; в `line_sim/core/preset.py` нет `class ScenePreset`, а `def resolve_repo_path`,
      `apply_defect_override`, `load_scene_preset`, присваивания `REPO_ROOT` и `DEFAULT_DEFECT_PROBABILITY` и `import os`
      (на уровне модуля) — есть.
- [ ] A3. Поведение каталога прежнее — литералы, снятые тестером **на коде до переезда** (окружение снимка — комментарием у
      литералов: ОС, версии cv2/numpy). Дерево во `tmp_path`, собранное тестом: ≥ 3 листовых класса, вложенность 2 уровня, одно
      имя кириллицей, `meta.yaml` на верхнем уровне и переопределение ниже, спрайты RGBA, хотя бы в одном классе ≥ 2 спрайта,
      служебная папка `_meta/`, файл верхнего уровня — **не изображение** (например `README.txt`; PNG в корне каталога `load()`
      отвергает). Проверяются: `class_names`, `num_classes`, поля `entry(i)`/`ClassMeta` (через `model_dump`; пути — относительно
      корня дерева, не абсолютные `tmp_path`); `get_sprite(i, rng)` по seed 0..4 — оракул: исходные массивы, которые тест
      записал (не хэш), и тест проверяет, что seed 0..4 выбрали оба спрайта класса с двумя; `get_background(rng, size_hw)`
      с `backgrounds_dir=None` (процедурные, sha256) и с папкой фонов (2 файла, один в подпапке; sha256 и проверка, что
      выбраны оба файла) по seed 0..4; `procedural_background(rng, (h, w))` для seed 0..9 и двух размеров (sha256);
      `load_meta` на папке без meta и с каждым из `META_FILENAMES`. **Отдельное дерево** со спрайтом BGR без альфы:
      `load()` поднимает `ValueError`, литералом — хвост сообщения без пути.
- [ ] A4. Поведение пресета прежнее — литералы до переезда: `ScenePreset.from_dict(d).to_dict()` для 3 словарей (каталог;
      слои; оба + `class://`) — без `base_dir` либо с фиксированной строкой, без путей `tmp_path`; `to_yaml` в тот же каталог
      и в соседний (пересчёт путей, прямые слэши; сверяются относительные строки). `ValidationError` для: пусто (нет
      `catalog_dir` и `layers`); занятое имя `base`/`damaged` **в пресете с `catalog_dir`** (без каталога эти имена
      разрешены, `preset.py:87`); `angle_range_deg` lo > hi. Литералами — `exc.errors()[i]["msg"]` и `loc`, **не** `str(exc)`
      (в нём ссылка на минорную версию pydantic и `input_value`).
- [ ] A5. Блок стенда не сломан: `Services.line_sim.core.preset.REPO_ROOT == Path(__file__).resolve().parents[3]` тестового
      файла и `(REPO_ROOT / "pyproject.toml").is_file()` (путь литералом не писать — файл переносится из worktree тестера);
      `resolve_repo_path("data/x") == REPO_ROOT / "data/x"`; `load_scene_preset("<любой каталог>", None).defect_probability
      == 0.0`; `load_scene_preset(None, None)` поднимает `ValidationError`, `errors()[0]["msg"]` — литерал; подмена
      `monkeypatch.setattr("Services.line_sim.core.preset.os.path.relpath", ...)` не падает `AttributeError`
      (на этом стоит `line_sim/tests/test_hazards_1_0_paths.py:264`).
- [ ] A6. **Проверка лида в отчёте, не pytest.** Потребители не правились: `git diff --name-only` против базы — только
      `Files` + тест тестера. Числа строк до и после равны: `rg -c --glob '*.py' --glob '!.claude/**'
      --glob '!Services/dataset_gen/core/{catalog,metadata,backgrounds,config}.py' --glob '!Services/line_sim/core/preset.py'
      --glob '!Services/layer_render/**'` по 10 шаблонам: `from Services.dataset_gen.core.catalog import`,
      `from Services.dataset_gen.core.metadata import`, `from Services.dataset_gen.core.backgrounds import`,
      `from Services.dataset_gen.core.config import`, `from Services.dataset_gen.core import`, `from Services.dataset_gen import`,
      `from Services.line_sim.core.preset import`, `import Services.line_sim.core.preset`, `from Services.line_sim.core import`,
      `from Services.line_sim import`.
- [ ] A7. Наборы зелёные без правки литералов: `Services/layer_render/tests`, `Services/line_sim/tests`, `Services/dataset_gen/tests`,
      `Services/ml_train/tests`, `Plugins/sim` (все подкаталоги), эталоны [goldens.md](goldens.md); `sentrux check .` (CLI) ✓;
      `python scripts/validate.py` без ошибок.
- [ ] A8. `Services.layer_render.__all__` содержит `ScenePreset`, `CLASS_SPRITE_SOURCE`, `SpriteCatalog`, `ClassEntry`,
      `CatalogConfig`, `ClassMeta`, `load_meta`, `write_meta`, `SymmetryType`, `procedural_background`; каждое `is` объект
      своего модуля; приватных имён и дублей в `__all__` нет.

#### Out of scope

`ObjectFactory`, `RenderedObject`, `catalog_bridge`, `preview` (2.4b); перевод потребителей на новые пути;
новые поля пресета (3.1); `GeneratorConfig`/`AugmentConfig` и остальной `config.py`.

#### TRAPS

`line_sim/core/preset.py` после переезда не использует `os`, но `import os` обязан остаться (`# noqa: F401` с
причиной: строка `"Services.line_sim.core.preset.os.path.relpath"` в `test_hazards_1_0_paths.py:264`) — иначе ruff снимет
импорт и тест упадёт `AttributeError`, а не на свойстве. `REPO_ROOT` в `line_sim` — `parents[3]`; копия в `layer_render`
дала бы другой корень. `REPO_ROOT` и `resolve_repo_path` обязаны остаться в **одном** модуле:
`Plugins/sim/layer_preview/tests/test_hazards_1_3h_c_sprites.py:356` подменяет `REPO_ROOT` на старом модуле и ждёт, что
`resolve_repo_path` увидит подмену. Литералы sha256 процедурных фонов и `_cover_crop` сняты на win32 (cv2/numpy в
комментарии): на другой платформе возможны расхождения `INTER_CUBIC`/`GaussianBlur` — прецедент в тестах 2.1, 2.3, 6.1. Циклический импорт: `dataset_gen.core.config` импортирует `layer_render.metadata` → `layer_render/__init__`
не должен тянуть `dataset_gen` (проверка: `python -c "import Services.dataset_gen"` в чистом процессе). Pydantic-модели с
`from __future__ import annotations`: `LayerSpec` и `SymmetryType` обязаны быть импортированы на уровне модуля, иначе
`ScenePreset`/`ClassMeta` не соберутся (`PydanticUndefinedAnnotation`).
