# Пресеты line_sim

YAML-пресеты сцены (`ScenePreset.from_yaml`). Относительные пути (`catalog_dir`,
`layers[*].sprite_source`) резолвятся от каталога файла пресета.

## Комментарии и редактор слоёв

Редактор слоёв пишет пресет командой `preset.commit` плагина `scene_source` через
`recipe.yaml_io.update_yaml_preserving`: в файл уходят только **изменившиеся** top-level ключи,
каждый — **целиком**. Поэтому:

- комментарии у нетронутых ключей и заголовок файла сохраняются;
- комментарии **внутри** заменённого ключа (например внутри `layers`) теряются при первой же
  правке этого ключа — прозу и примеры держим здесь, а не в YAML;
- commit без изменений файл не трогает (`changed: false`, `rev` прежний).

## `letters_layered.yaml` — буквы из шрифтов на дисках

Слои снизу вверх: диск-подложка (белая заливка, файл из `--disk-out`), затем буква класса
(`class://` — спрайт разыгрывает `ObjectFactory` из каталога, чёрная заливка). Заливка —
`LayeredObject.color_rgb`.

- `catalog_dir` — каталог классов `SpriteCatalog` (подкаталог на класс, RGBA-эталоны внутри).
- `angle_range_deg: [0, 360]` — угол объекта на ленте, градусы, CCW (LS-003); полный оборот —
  у диска нет выделенной стороны.
- `defect_probability: 0.0` — дефект-слой `damaged` сам не появляется; форсировать конкретный
  объект — `ObjectFactory.force_defect_next()`.

Эталоны букв генерирует `tools/make_font_letters.py`, вручную не рисуются. Пример сборки
каталога (DejaVu из matplotlib — заглушка; боевые TTF шрифта этикетки подставляет владелец):

```bash
FONTS="$(python -c 'import matplotlib; print(matplotlib.get_data_path())')/fonts/ttf"
python -m Services.line_sim.tools.make_font_letters \
    --letters АК \
    --font "$FONTS/DejaVuSans.ttf" \
    --font "$FONTS/DejaVuSans-Bold.ttf" \
    --size-px 300 --letter-frac 0.6 \
    --out data/line_sim/letters_font \
    --disk-out data/line_sim/letters_font_disk.png
```

Те же спрайты «как на реальной ленте» — краска, зерно, мягкий край и диск, вырезанный из реального
фото (значения измерены: цвет краски ≈ (65, 70, 82) по 20 кадрам плана, в фикстуре ядро
(59, 65, 77); зерно букв σ ≈ 9, край ≈ 2 px, диск 300 px). Реальный диск на кадре пересвечен до 255
(в фикстуре 95–97 % пикселей), поэтому плоский белый спрайт соответствует снимку. Зерно у диска не
добавляется; `--grain-sigma` относится только к буквам. Альфа фото-диска — круг диаметром
`size_px - 6` (хвост размытия не упирается в край канвы), поэтому видимый диск на 6 px меньше канвы.
Цвет краски пишется во все пиксели буквы, включая прозрачные (иначе при масштабе кромка темнеет).
Зерно буквы зависит от набора букв и шрифтов запуска (один rng на запуск):

```bash
python -m Services.line_sim.tools.make_font_letters \
    --letters АК \
    --font "$FONTS/DejaVuSans.ttf" \
    --font "$FONTS/DejaVuSans-Bold.ttf" \
    --size-px 300 --letter-frac 0.6 \
    --ink-rgb 65,70,82 --grain-sigma 9 --edge-blur-px 1 --seed 1 \
    --disk-from-photo Services/line_sim/tests/fixtures/real_disk_snapshot.png \
    --out data/line_sim/letters_font \
    --disk-out data/line_sim/letters_font_disk.png
```

`--disk-from-photo` требует `--disk-out`. Внимание: `color_rgb` слоя **заменяет** RGB спрайта
(`LayeredObject._transform`), поэтому для текстурированных (покрашенных, с зерном) спрайтов слои
пресета должны быть **без** `color_rgb` — иначе заливка сотрёт и краску, и зерно.

### Примеры аугментации слоёв

Реальные диски не варьируются (один физический диск), печать на диске не гуляет по масштабу,
углу и тону — поэтому оба слоя `static`. Если понадобится вариация (например партии дисков
чуть отличаются диаметром):

```yaml
  - name: disk
    mode: augmented
    augment:
      scale: [0.97, 1.03]
  - name: letter
    mode: augmented
    augment:
      scale: [0.95, 1.05]
      angle_deg: [-3.0, 3.0]
      hue_shift_deg: [-10.0, 10.0]
```

## `letters_disk.yaml`

Русские буквы на дисках — те же эталоны, что у `dataset_gen`; см. комментарии в самом файле.
