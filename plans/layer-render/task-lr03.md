# ЛР-03 — пресет из одних слоёв брака отвергается при загрузке

**Уровень:** Middle (Sonnet) · **Исполнитель:** developer · **План:** [plan.md](plan.md), шаг 0.
**Module contract:** impl-only (новых публичных имён нет; пресет, который раньше принимался, теперь отвергается).
**Dependencies:** нет.
**Gate:** RED слепого тестера → GREEN; инъекции с прогнозом лида записаны; `reviewer` APPROVED по SHA.
**Handoff:** лид полосы С1 (инъекции, ревью, отчёт владельцу).

**Цель:** пресет, в котором может не нарисоваться ни одного слоя, отвергается при загрузке понятным текстом;
прямой вызов `compose_layers` без видимых слоёв даёт понятную ошибку.

Объём — три пункта решения ([design-unified-decisions.md](design-unified-decisions.md), строка ЛР-03):
слой не-брак в пресете; понятная ошибка `compose_layers`; тест по сгенерированным пресетам.

## Дефект

`ScenePreset` без `catalog_dir`, где у всех слоёв `mode: defect`, принимается. Когда ни один брак не выпал и
служебный слой `damaged` тоже не выпал, список слоёв к рисованию пуст:
`ValueError: max() iterable argument is empty` в `canvas_size` (`Services/layer_render/layers.py`).
`preset.commit` (по чтению кода, прогоном не проверено) отвечает `ok` и пишет такой файл: `ObjectFactory`
при сборке ничего не рисует.

## DESIGN

1. Правило в `ScenePreset._catalog_or_layers` (`Services/layer_render/preset.py`):
   `catalog_dir is None`, `layers` непуст и у **всех** слоёв `mode == "defect"` → `ValueError`.
   `defect_probability` слоя правило не смотрит: набор из одних слоёв брака отвергается и при `1.0`
   (пункт плана: «пресет только из слоёв брака отвергается»). Объекта без брака в таком пресете нет.
2. Текст ошибки (по-русски) называет: имена слоёв, `catalog_dir`, слово `defect` и что нужен хотя бы один слой
   `mode` `static` или `augmented`.
3. `compose_layers` (`layers.py`): после цикла, если к рисованию не набралось ни одного слоя, —
   `ValueError` с префиксом `LayeredObject '<label>':`, до `_compose_canvas`. Поток `rng` и байты любого
   годного входа не меняются. Старый путь обучения (`DatasetEngine`, эталон m4) `compose_layers` не зовёт.
4. Пресет с `catalog_dir` не меняется: статичный слой там есть всегда (`base` или слой `class://`).
5. Кода в плагинах не добавлять: `from_dict`, `from_yaml`, `apply_defect_override`, `preset.commit`,
   `preset.preview`, `preset.layout` идут через `ScenePreset.from_dict`.
6. `canvas_size`, `_compose_canvas`, `transform_layer`, `ObjectFactory` не менять.

## FILES

- `Services/layer_render/preset.py` — правило и строка в докстринге класса (`Pre`).
- `Services/layer_render/layers.py` — ошибка в `compose_layers` и строка в докстринге о порядке проверок.
- `Services/layer_render/README.md` — строка `compose_layers`: «follow-up, не исправлено» заменить на новое поведение.
- `Services/layer_render/tests/test_acceptance_lr03_defect_only.py` — слепой тестер, REDS 1–5.
- `apps/line_sim/tests/test_acceptance_lr03_preset_commands.py` — слепой тестер, REDS 6–8 (здесь, потому что
  `Services` не имеет права импортировать `Plugins`).
- `Services/layer_render/tests/test_hazards_lr03.py` — автор (по необходимости).

## REDS (приёмка)

Тексты ошибок проверять по `exc.errors()[0]["msg"]` (у pydantic), а не по `str(exc)`: тот печатает `input_value`,
и проверка слова `defect` была бы пустой.

1. `ScenePreset.from_dict` с одним слоем `mode: defect` без `catalog_dir` бросает `ValueError`; в `msg` есть
   имя слоя, `catalog_dir`, `defect`, `static`, `augmented`.
2. То же с двумя слоями брака и со слоем `defect_probability: 1.0`. `from_yaml` такого файла бросает то же.
3. `compose_layers` с одним невыпавшим слоем `defect` (`defect_probability=0.0`, `label="x"`) бросает
   `ValueError`, текст начинается с `LayeredObject 'x':` и не содержит `max()`. С тем же слоем при `1.0` или
   через `forced_defects` рисует.
4. Принимаются: без каталога — `static` + `defect`; без каталога — только `augmented`; с `catalog_dir` — только
   слои `defect`. Для каждого `ObjectFactory(preset).render(np.random.default_rng(seed))` не бросает на
   сидах 0…19 и `nominal_layers(...)` отдаёт непустой список.
5. Сгенерированные пресеты: все наборы из 1–3 слоёв с режимами `static` / `augmented` / `defect`, с каталогом и
   без. Каждый, который `from_dict` принял, рисуется на сидах 0…19 без исключения; отвергаются ровно наборы
   «без каталога, все `defect`».
6. `preset.commit` настоящего `SceneSourcePlugin`, поднятого из годного `.yaml`, с пресетом из одних слоёв брака:
   ответ `status: error`, `code: invalid`, в `message` фраза про `static`; байты файла не изменились; после
   дельт мира старая фабрика спавнит объект (`active >= 1` по `scene.status`), `log_error` про `spawner.tick()`
   нет. Тестер записывает, что эта команда делает ДО правки.
7. `preset.preview` и `preset.layout` (`Plugins/sim/layer_preview`) с таким пресетом: `status: error`,
   `code: invalid`, в `message` есть фраза нового сообщения и нет `max()`. Один `status`/`code` не годится:
   до правки они такие же.
8. `SceneSourcePlugin.configure` с файлом такого пресета не бросает и **движок не собирает**: `scene.defect_now`
   отвечает `applied: False` (или `scene.status` → `flow == {}`), кадр — сплошной фон. До правки движок
   собирается, а `tick` падает на каждом кадре — по виду кадра эти два случая не различить.
9. Не покраснело: `Services/layer_render/tests`, `Services/line_sim/tests`, `Plugins/sim/scene_source/tests`,
   `Plugins/sim/layer_preview/tests`, `Services/dataset_gen/tests/test_engine_golden_m4.py`.

## Out of scope

Тёмная кайма; смесь по альфе; пресет v2; перенос в `Services/imaging`; прозрачный целиком `static`-слой
(проверка «полностью прозрачный итог» уже есть и не меняется).
