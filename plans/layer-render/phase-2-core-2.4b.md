# layer-render — Task 2.4b (вынесена из phase-2-core.md: файл фазы у бюджета 32 КБ)

Фаза: [phase-2-core.md](phase-2-core.md) · план: [plan.md](plan.md) · предыдущая: [phase-2-core-2.4a.md](phase-2-core-2.4a.md)

### Task 2.4b — `ObjectFactory` и превью переезжают в `layer_render`, фабрика отдаёт `RenderedObject` (часть бывш. 2.4)

- **Статус:** [PENDING] волна 5; ревью спеки ит.1 — CHANGES REQUESTED, правки B1–B2, M1–M3, m1–m6 внесены (2026-10-02) · **Level:** Middle (Sonnet 5.5) · **Assignee:** tester → developer → инъекции лида → reviewer
- **Module contract:** public-api-change (`layer_render` получает `factory`, `preview`, `load_catalog`, `load_image_rgba`,
  `json_safe`; `line_sim.ObjectFactory` становится наследником `layer_render.factory.ObjectFactory`;
  `LayeredObject` получает второй конструктор; `line_sim.core.{preview,catalog_bridge}` — реэкспорт)
- **CHAIN:** `tester`(RED, worktree до кода) → `developer`(GREEN; тот же агент трека, re-summon) → инъекции лида → `reviewer`
- **Dependencies:** 2.4a (DONE, `be42ba755`). После — 3.1 (пресет v2), `render_scene`, 6.2 (`LayerSceneGenerator` зовёт
  `layer_render.factory`, не `line_sim`)
- **Gate:** RED тестера → GREEN; инъекции записаны; `reviewer` APPROVED по SHA. Живой стенд: путь `make()` сима
  переподключается, поэтому стенд нужен — sha256 N кадров `scene_source` до и после на одном seed. Поднимать только при
  свободном `stand.lock` и с записью; если стенд занят — пропуск записать в план с причиной, задача остаётся без живой проверки.

**Goal:** фабрика объекта и превью — код `layer_render`. Генератор обучения (6.2) получает объект без симулятора ленты.
`line_sim` добавляет к объекту только своё: паспорт ленты и форс-брак оператора. Кадры, спрайты и превью не меняются ни на байт;
ни один потребитель вне `Files` не правится.

#### Files

1. `Services/layer_render/factory.py` (новый) — из `Services/line_sim/core/factory.py`:
   `RenderedObject` (новый), `ObjectFactory` (база), `_read_only_view`, `_DEFECT_LAYER_NAME`, `_DEFECT_COLOR_RGB`,
   `_DEFECT_SIDE_FRAC`, `_DEFECT_OFFSET_FRAC`. В базе: `__init__(preset)`, `num_classes`, `class_names`,
   `defect_probability`, `nominal_layers(rng)`, `_resolve_bottom_layers(rng)`, `_build_defect_blob` (static) — тела без
   изменения логики. Новый метод `render(rng, *, force_defect=False, label="") -> RenderedObject` — тело нынешнего `make()`
   без паспорта и без флага оператора.
2. `Services/layer_render/preview.py` (новый) — весь `Services/line_sim/core/preview.py`. Плитка строится через
   `ObjectFactory.render(default_rng(seed), label=f"preview-{seed}")`, `layer_params` плитки — через `json_safe`.
3. Дополнения в существующих модулях `layer_render`:
   `catalog.py` + `load_catalog(classes_dir)` и `io.py` + `load_image_rgba(path)` (оба из `line_sim/core/catalog_bridge.py`,
   тела дословно); `layers.py` + публичная `json_safe(value)` (тело `_json_safe` из `line_sim/interfaces.py:87-96`);
   `preset.py` — докстринг `:1-7` без ссылок на `dataset_gen.core.config.GeneratorConfig`, `catalog_bridge` и LS-007
   (хвост 2.4a).
4. `line_sim` после переезда:
   `core/factory.py` — `class ObjectFactory(Services.layer_render.factory.ObjectFactory)`: `force_defect_next()`,
   `force_defect_pending`, `make(object_id, spawn_encoder, rng) -> LayeredObject` (флаг оператора + `render` +
   `LayeredObject.from_rendered`) и реэкспорт `_DEFECT_SIDE_FRAC`, `_DEFECT_OFFSET_FRAC` (потребитель —
   `line_sim/tests/test_hazards_3_2.py:32`), а также `apply_occlusion` (из `layer_render.effects`) и `load_layer_sprite`
   (из `layer_render`) — все четыре в `__all__` модуля (потребители глобалов модуля — `test_acceptance_2_2_effects.py:339`,
   `test_acceptance_2_3_layers.py:1172`; ревью спеки B2).
   `core/layered_object.py` — `LayeredObject.from_rendered(rendered, *, object_id, spawn_encoder)`; прежний
   `__init__(passport, layers, rng)` остаётся (его зовут тесты 2.3 и `test_hazards_look_1_2.py`); `canvas_size` остаётся
   в `__all__` (`test_acceptance_2_3_layers.py:1153`), хотя `preview` его больше не берёт.
   `core/preview.py`, `core/catalog_bridge.py` — только реэкспорт (явные имена, в `__all__`).
   `interfaces.py` — `_json_safe` импортом из `Services.layer_render.layers` (имя `_json_safe` в модуле остаётся).
5. `Services/layer_render/__init__.py` (`__all__`), `README.md` (Public API, шапка), `STATUS.md`; `docs/maps/layer_render.md`
6. `Services/line_sim/README.md` (`:29` строка `ObjectFactory`, `:98` `catalog_bridge`), `STATUS.md`
- тесты тестера: `Services/layer_render/tests/test_acceptance_2_4b_factory_preview.py`

#### DESIGN

- **Наследник, не обёртка.** `line_sim.ObjectFactory` наследует базу `layer_render`. Причина — потребители трогают
  внутренности экземпляра: `factory._catalog.get_sprite = ...` (`test_hazards_3_2.py:79`, подмена на объекте каталога),
  и чтение `factory._catalog` (`:70,109,117`), `plugin._live_factory._preset` (`test_scene_source_controls.py:262,279`),
  `plugin._spawner._factory._preset` (`test_scene_source_hazards_1_2a.py:128`), `factory._build_defect_blob` и
  `ObjectFactory._build_defect_blob` (`test_hazards_3_2.py:139,229`), `monkeypatch.setattr(factory, "make", ...)` (`test_hazards_3_3.py:86,122`,
  `test_spawner.py:224`, `test_scene_source_hazards.py:310`). Наследник отдаёт всё это без прокси-свойств.
- **Метод базы — `render`, не `make`.** У `line_sim.make` другая сигнатура (`object_id`, `spawn_encoder`); переопределение
  с другой сигнатурой нарушает подстановку (pyright `reportIncompatibleMethodOverride`). Имя класса `ObjectFactory` в
  `layer_render` — по карте CTO. `Services.layer_render.ObjectFactory` и `Services.line_sim.ObjectFactory` — **разные**
  классы; второй — подкласс первого.
- **Флаг оператора остаётся в `line_sim`.** `force_defect_next()` — команда пульта сима. База без состояния кроме кэшей
  слоёв и каталога: её можно делить (кэш превью). `line_sim.make` читает флаг, зовёт `render(rng, force_defect=флаг,
  label=object_id)`, гасит флаг **только после** успешного `render` и `from_rendered` (контракт `factory.py:100-106`).
- **`RenderedObject`** — `@dataclass(frozen=True, eq=False)`: `rgba` (RGBA uint8, read-only), `class_name`, `angle_deg`,
  `defect: str | None` (имена активных defect-слоёв через запятую, как `passport.defect`), `layer_params`. `render`
  ставит `rgba.flags.writeable = False`. Сравнения по значению нет: `eq` по ndarray неоднозначен.
- **`LayeredObject.from_rendered`** строит паспорт `ObjectPassport(object_id, class_name, angle_deg, defect,
  spawn_encoder, layer_params)`; `lateral_px` — дефолт (его ставит спавнер после). `render()` объекта возвращает **тот же**
  массив `rendered.rgba`, без копии.
- **Контракт rng не меняется.** `render` тратит rng в прежнем порядке: `integers` (класс) → `uniform` (угол) →
  `get_sprite` → `compose_layers` (`rng.spawn(len(layers))`). Сборка блоба дефекта rng не тратит. Форс меняет расход
  только внутри дочернего генератора defect-слоя (`layers.py:346`, короткое замыкание `or`), родителя не трогает.
  `rng.spawn` не двигает поток родителя (замер ревью спеки): число вызовов `spawn` видит только следующий `spawn`.
- **Тексты ошибок прежние.** `label=object_id` → `compose_layers` пишет `LayeredObject '<object_id>': ...` как раньше.
  Префикс `LayeredObject` в `layers.py` не меняется: тексты закреплены тестами.
- **Превью побайтно прежнее.** Плитка и раскладка строятся теми же вызовами. Кэш превью держит базовую фабрику.
  Плагин `Plugins/sim/layer_preview` не правится: старые пути — реэкспорт.
- **Направление импортов.** Новые модули импортируют только stdlib, cv2, numpy, pydantic и `Services.layer_render.*`
  (`apply_occlusion` — из `layer_render.effects`, Task 2.2). Сканеры границ в `layer_render/tests` видят новые файлы сами.
- **Рамка `letter|букв|disk|диск`** в переехавших докстрингах переписать с сохранением смысла: `factory.py:103` («каталог на
  сетевом диске» → «на сетевом томе»), `:202` («круглый диск» → «круглый объект»), `preview.py:14` («картинки на диске» →
  «файлы картинок»). Проверка — запуском теста рамки, не глазами.

#### Acceptance

##### Имена, фабрика, объект (A1–A5)

- [ ] A1. Идентичность (каждое имя — отдельный кейс): все имена `__all__` модуля `Services.line_sim.core.preview` `is`
      `Services.layer_render.preview.<имя>`; `Services.line_sim.core.catalog_bridge.load_catalog is
      Services.layer_render.catalog.load_catalog`, `...catalog_bridge.load_image_rgba is Services.layer_render.io.load_image_rgba`;
      `Services.line_sim.interfaces._json_safe is Services.layer_render.layers.json_safe`;
      `Services.line_sim.core.factory.{_DEFECT_SIDE_FRAC, _DEFECT_OFFSET_FRAC}` равны значениям `layer_render.factory`.
      Пакетный уровень: `Services.line_sim.{render_preview_grid, validate_preview_request, confine_preset_paths,
      PreviewLimitError}` и `Services.line_sim.core.OUTSIDE_ROOTS_MESSAGE` — тот же объект. Для функций и классов
      `__module__` — новый модуль. `is` для `PREVIEW_MAX_SEEDS`, `PREVIEW_MIN_TILE_PX`, `PREVIEW_DEFAULT_TILE_PX`,
      `PREVIEW_MAX_TILE_PX` вакуумна (CPython кэширует целые −5..256, копия даст `True`) — копию держит A2.
- [ ] A2. Наследование: `issubclass(Services.line_sim.ObjectFactory, Services.layer_render.factory.ObjectFactory)`;
      `Services.line_sim.ObjectFactory is not Services.layer_render.factory.ObjectFactory`;
      `Services.line_sim.ObjectFactory._build_defect_blob is Services.layer_render.factory.ObjectFactory._build_defect_blob`.
      AST: в `line_sim/core/factory.py` нет `def` с именами `render`, `nominal_layers`, `_resolve_bottom_layers`,
      `_build_defect_blob` и нет присваиваний `_DEFECT_*`; в `line_sim/core/preview.py` и `catalog_bridge.py` — ни
      одного `def`/`class` и ни одного присваивания, кроме `__all__`; в `line_sim/interfaces.py` нет `def _json_safe`.
- [ ] A3. **Фабрика `layer_render` даёт прежний объект.** Литералы снимает тестер на коде до переезда через
      `line_sim.ObjectFactory.make` (окружение снимка — комментарием: ОС, версии cv2/numpy). Пресеты в `tmp_path` (сборка
      как в `Plugins/sim/layer_preview/tests/test_hazards_1_3h_layout.py`): со слоем `class://`; с каталогом без
      `class://` (авто-слой `base`); без каталога (только слои); четвёртый — с каталогом и `defect_probability=0.5`.
      Для seed 0..4 и `force_defect ∈ {False, True}` литералами: sha256 байт `rgba` + `shape`, `class_name`, `angle_deg`,
      `defect`, `json.dumps(_json_safe(layer_params), sort_keys=True)` (на коде до переезда `_json_safe` — из
      `Services.line_sim.interfaces`; на дороге `make` то же даёт `obj.passport.to_dict()["layer_params"]`) и **после**
      вызова два литерала: `rng.random()` (расход родителя: класс, угол, спрайт) и `rng.spawn(1)[0].random()` (счётчик
      `spawn`: `compose_layers` зовёт `rng.spawn(len(layers))` ровно раз).
      Сверять две дороги: `Services.layer_render.factory.ObjectFactory(preset).render(default_rng(s), force_defect=f)`
      и `Services.line_sim.ObjectFactory(preset).make("obj", 0.0, default_rng(s))` (при `f=True` — после
      `force_defect_next()`). Плюс: `RenderedObject.rgba.flags.writeable is False`; при `defect_probability=0.5` среди
      seed 0..4 есть и `defect=None`, и `defect="damaged"` без форса (иначе ветка розыгрыша не проверена; замер ревью
      спеки: seed 0..4 дают оба исхода во всех четырёх раскладках).
- [ ] A4. `LayeredObject.from_rendered(r, object_id="o-1", spawn_encoder=12.5)`: поля паспорта равны полям `r` и
      аргументам, `lateral_px == 0.0`, `render() is r.rgba`; `r` после вызова не изменён (`r.defect`, `r.layer_params`
      — прежние значения). Текст ошибки: пресет **без `catalog_dir`**, единственный слой — PNG с нулевой альфой (с каталогом
      спрайт класса непрозрачен и ошибки нет) —
      `line_sim.ObjectFactory.make("obj-7", ...)` и базовый `render(rng, label="obj-7")` поднимают `ValueError`; текст
      сообщения — литерал, снятый до переезда.
- [ ] A5. Флаг оператора прежний: `make` после `force_defect_next()` при `defect_probability=0` даёт
      `passport.defect == "damaged"`, флаг после успеха `False`; если `render` поднял исключение (подмена
      `factory._catalog.get_sprite` на падающую), флаг остаётся `True`, и следующий успешный `make` получает дефект.
      База `layer_render` не имеет атрибутов `force_defect_next` и `force_defect_pending`.
##### Превью, импорты, проверки лида (A6–A10)

- [ ] A6. **Превью побайтно прежнее** — литералы до переезда через `Services.line_sim.core.preview`:
      `render_preview_grid(preset, [0, 1, 2, 3], 64)` — sha256 PNG и `json.dumps(tiles, sort_keys=True)` для пресетов
      `class://` и «без каталога»; `render_layout(preset, s)` для s ∈ {0, 1, 2} — sha256 от `json.dumps(..., sort_keys=True)`.
      Сверять через старый и новый путь импорта.
- [ ] A7. Цикла импорта нет в любом порядке: отдельный чистый подпроцесс на каждый модуль, модуль импортируется **первым** —
      `Services.layer_render`, `Services.layer_render.factory`, `Services.layer_render.preview`, `Services.line_sim`,
      `Services.line_sim.core.factory`, `Services.line_sim.core.preview`, `Services.line_sim.core.catalog_bridge`,
      `Services.line_sim.core.layered_object`, `Services.line_sim.interfaces`, `Services.dataset_gen`,
      `Plugins.sim.layer_preview.plugin`, `Plugins.sim.scene_source.plugin`; код возврата 0 у каждого.
      (Урок 2.4a i5: pytest грузит пакеты в своём порядке и цикл прячет.)
- [ ] A8. `Services.layer_render.__all__` содержит `ObjectFactory`, `RenderedObject`, `render_preview_grid`, `render_layout`,
      `validate_preview_request`, `confine_preset_paths`, `PreviewLimitError`, `OUTSIDE_ROOTS_MESSAGE`, `load_catalog`,
      `load_image_rgba`, `json_safe`; каждое `is` объект своего модуля; приватных имён и дублей нет.
- [ ] A9. **Проверка лида в отчёте, не pytest.** Потребители не правились: `git diff --name-only` против базы — только
      `Files` + тест тестера. Числа строк до и после равны: `rg -c --glob '*.py' --glob '!.claude/**'
      --glob '!Services/layer_render/**' --glob '!Services/line_sim/core/{factory,preview,catalog_bridge,layered_object}.py'
      --glob '!Services/line_sim/interfaces.py'` по шаблонам: `from Services.line_sim.core.factory import`,
      `from Services.line_sim.core.preview import`, `from Services.line_sim.core.catalog_bridge import`,
      `from Services.line_sim.core.layered_object import`, `from Services.line_sim.core import`,
      `from Services.line_sim import`, `from Services.line_sim.interfaces import`.
- [ ] A10. Наборы зелёные без правки литералов: `Services/layer_render/tests`, `Services/line_sim/tests`,
      `Services/dataset_gen/tests`, `Services/ml_train/tests`, `Plugins/sim` (все подкаталоги), `apps/line_sim/tests`,
      эталоны [goldens.md](goldens.md); тест рамки `test_acceptance_1_1_background_layers.py::test_frame_rule_grep_zero_matches_in_package_python_sources`;
      `sentrux check .` (CLI) ✓; `python scripts/validate.py` без ошибок.

#### Out of scope

Перевод потребителей на новые пути (`Plugins/sim/layer_preview`, `scene_source`, `spawner`, тесты); `render_scene` и
`scene.py`; `preset_store`; пресет v2 (3.1); `LayerSceneGenerator` (6.2); префикс `LayeredObject '...'` в текстах
`compose_layers`; текст `TypeError` в `load_layer_sprite` (называет `Services.line_sim.core.factory`, закреплён
`test_acceptance_2_3_layers.py:420-424`; путь остаётся верным) — follow-up; follow-up «`compose_layers` без слоёв на
канве падает сырым `max()`».

#### TRAPS

Тело `nominal_layers` дословно не переносится: оно зовёт `LayeredObject._transform` (`factory.py:185`), а база в
`layer_render` импортировать `LayeredObject` не может (граница). В базе — `transform_layer` из `layer_render.layers`
(тот же объект, `test_acceptance_2_3_layers.py:1163`). Модуль `line_sim/core/factory.py` хранит глобалы, которые читают
тесты (`apply_occlusion`, `load_layer_sprite`, `_DEFECT_*`), хотя сам их больше не использует — без `__all__` ruff снимет.
`factory._catalog.get_sprite = flaky` (`test_hazards_3_2.py:79`) подменяет метод на **объекте** каталога: `render` обязан
звать `self._catalog.get_sprite` в момент вызова. Связанный метод, сохранённый в `__init__`, тихо обойдёт подмену, и тест
флаки-каталога позеленеет без свойства. `_DEFECT_SIDE_FRAC`/`_DEFECT_OFFSET_FRAC` в `line_sim/core/factory.py` не
используются — ruff F401 снимет импорт; нужен `# noqa: F401` с причиной (как `import os` в 2.4a). `render` не копирует `rgba`
в `from_rendered`: копия удвоит память объекта ленты и сломает `render() is r.rgba`. Тест рамки сканирует все `.py`
пакета кроме `tests/` — новые `factory.py`/`preview.py` попадают в него автоматически. Кэш превью `_factory_cache` —
глобал модуля `layer_render.preview`; присваивание через старый модуль (`line_sim.core.preview._factory_cache = None`)
создало бы второй глобал — в тестах таких присваиваний нет (разведка 2026-10-02), новых не заводить. Литералы sha256 сняты
на win32: на другой платформе возможны расхождения `INTER_AREA`/поворота — прецедент в тестах 2.1, 2.3, 6.1.
