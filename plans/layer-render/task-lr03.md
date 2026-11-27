# ЛР-03 — пресет из одних слоёв брака отвергается при загрузке

**Уровень:** Middle (Sonnet) · **Исполнитель:** developer · **План:** [plan.md](plan.md), шаг 0.

**Цель:** пресет, который может не нарисовать ни одного слоя, отвергается при загрузке понятным текстом,
а не падает при рисовании.

## Дефект

`ScenePreset` без `catalog_dir`, где у всех слоёв `mode: defect`, принимается. Когда ни один брак не выпал и
служебный слой `damaged` тоже не выпал, список слоёв к рисованию пуст:
`ValueError: max() iterable argument is empty` в `canvas_size` (`Services/layer_render/layers.py`).

## DESIGN

- Одно правило в `ScenePreset._catalog_or_layers` (`Services/layer_render/preset.py`):
  `catalog_dir is None` и `layers` непуст и у **всех** слоёв `mode == "defect"` → `ValueError`.
- `defect_probability` слоя правило не смотрит: набор из одних слоёв брака отвергается и при `1.0`
  (пункт плана: «пресет только из слоёв брака отвергается»). Объекта без брака в таком пресете нет.
- Текст ошибки (по-русски) называет: имена слоёв, что `catalog_dir` не задан, и что нужен хотя бы один слой
  `mode: static` или `augmented`.
- Пресет с `catalog_dir` не меняется: нижним всегда рисуется спрайт класса.
- Пути `from_dict`, `from_yaml`, `apply_defect_override`, `preset.commit`, `preset.preview`, `preset.layout`
  идут через `ScenePreset.from_dict` — отдельного кода в плагинах не добавлять.
- `compose_layers`, `canvas_size`, `ObjectFactory` не менять (на них стоят эталоны).

## FILES

- `Services/layer_render/preset.py` — правило и строка в докстринге класса (`Pre`).
- `Services/layer_render/tests/test_acceptance_lr03_defect_only.py` — слепой тестер.
- `Services/layer_render/tests/test_hazards_lr03.py` — автор (по необходимости).
- `Services/layer_render/README.md` или `STATUS.md` — только если там перечислены правила пресета.

## REDS (приёмка)

1. `ScenePreset.from_dict` с одним слоем `mode: defect` без `catalog_dir` бросает `ValueError`
   (pydantic `ValidationError`); в тексте есть имя слоя, `catalog_dir` и слово `defect`.
2. То же с двумя слоями брака и с `defect_probability: 1.0`.
3. `ScenePreset.from_yaml` такого файла бросает то же.
4. Принимаются и рисуются, как раньше: без каталога — `static` + `defect`; без каталога — только `augmented`;
   с `catalog_dir` — только слои `defect`.
5. `preset.commit` настоящего `SceneSourcePlugin` с таким пресетом отвечает
   `{"status": "error", "code": "invalid"}`, байты файла пресета не меняются, следующий кадр рисуется.
   До правки этот путь никто не воспроизводил — тестер фиксирует, что он делает сейчас.
6. `preset.preview` и `preset.layout` (`Plugins/sim/layer_preview`) с таким пресетом отвечают
   `status: error`, `code: invalid` с этим текстом, а не `max() iterable argument is empty`.
7. `SceneSourcePlugin.configure` с таким файлом пресета не бросает: движок не собран, кадр — сплошной фон
   (поведение при негодном пресете уже есть, проверить, что оно покрывает этот случай).
8. Эталоны не меняются: `Services/layer_render/tests`, `Services/line_sim/tests`,
   `Services/dataset_gen/tests/test_engine_golden_m4.py` зелёные.

## Out of scope

Тёмная кайма; смесь по альфе; пресет v2; перенос в `Services/imaging`; прозрачный целиком `static`-слой
(отдельная проверка «полностью прозрачный итог» уже есть и не меняется).
