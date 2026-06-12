# dataset_gen — универсальный генератор синтетического датасета (cut-and-paste)

## Назначение

Генерирует обучающие данные для задач «классификация объекта + регрессия угла
поворота» методом cut-and-paste: RGBA-эталон поворачивается (угол = ground truth),
вклеивается на случайный фон и аугментируется единым проходом по всему кадру.

Ядро не знает предметной области: «класс» — это подкаталог с эталонами на
прозрачном фоне. Буквы, цифры, детали — любая задача задаётся YAML-пресетом,
движок один. В комплекте пресет под 33 русские заглавные буквы на дисках.

## Публичный API

| Символ | Описание |
|--------|----------|
| `DatasetEngine` | движок: каталог + симметрии + `generate_sample()` → (кадр, метка) |
| `GeneratorConfig` | Pydantic-конфиг; `from_yaml` / `from_dict` / `to_dict` |
| `SampleLabel` | метка: class_index, angle_deg, (sin, cos), symmetry, angle_valid |
| `SampleGenerator` | Protocol источника сэмплов ([interfaces.py](interfaces.py)) |
| `export_dataset` | режим 1: датасет на диск (PNG + labels csv/json/parquet) |
| `export_splits` | то же, но train/val/test подкаталогами (без утечки между сплитами) |
| `SyntheticDataset` | режим 2: torch Dataset на лету (ленивый импорт, torch опционален) |
| `save_preview_grid` | QC-сетка N кадров с подписями «класс + угол» |
| `detect_symmetry`, `encode_angle` | авто-детектор симметрии и кодирование угла |
| `ClassMeta` | разметка класса из meta.yaml (display_name, symmetry, произвольные поля) |
| `PRESETS_DIR` | путь к комплектным пресетам |

## Использование

**1. Экспорт датасета на диск (комплектный пресет):**

```python
from Services.dataset_gen import DatasetEngine, PRESETS_DIR, export_dataset

engine = DatasetEngine.from_yaml(str(PRESETS_DIR / "ru_letters_disk.yaml"))
export_dataset(engine, "data/dataset_gen/ru_letters/train", frames_per_class=300)
# → images/{класс:03d}/{i:05d}.png + labels.csv + classes.json (реестр+разметка)

# или сразу train/val/test (свой rng на сплит — без дубликатов между ними):
from Services.dataset_gen import export_splits
export_splits(engine, "data/dataset_gen/ru_letters",
              splits={"train": 300, "val": 50, "test": 50})
```

**2. Генерация на лету для PyTorch (без хранения файлов):**

```python
from torch.utils.data import DataLoader
from Services.dataset_gen import DatasetEngine, PRESETS_DIR, SyntheticDataset

engine = DatasetEngine.from_yaml(str(PRESETS_DIR / "ru_letters_disk.yaml"))
loader = DataLoader(SyntheticDataset(engine, length=9900, seed=42),
                    batch_size=64, num_workers=4)
images, targets = next(iter(loader))
# images: (B,3,128,128) float32 [0..1]
# targets: class_index (long), angle (B,2: sin,cos), angle_valid (bool — маска loss)
```

**3. Своя задача = свой пресет (код не меняется):**

```python
from Services.dataset_gen import GeneratorConfig, DatasetEngine, save_preview_grid

cfg = GeneratorConfig.from_dict({
    "catalog": {"classes_dir": "data/my_parts/sprites",      # подкаталог на класс
                "backgrounds_dir": "data/my_parts/backgrounds"},
    "output": {"size": [224, 224], "frames_per_class": 500},
    "symmetry": {"overrides": {"шайба": "full"}},             # ручное переопределение
})
engine = DatasetEngine(cfg)
save_preview_grid(engine, "preview.png", n=16)                # визуальный контроль
```

## Структура входных данных (две независимые папки)

```
classes_dir/                       backgrounds_dir/   ← фото реальной сцены
├── meta.yaml      ← корневая       ├── belt/          (сканируется РЕКУРСИВНО:
│                    разметка       │   ├── shot1.jpg   фоны можно раскладывать
├── letters/       ← подкласс       │   └── shot2.jpg   по подпапкам-категориям)
│   ├── meta.yaml  ← наследуется    ├── tray/
│   ├── А/                          │   └── shot3.jpg
│   │   ├── base.png  (RGBA)        └── table/
│   │   └── meta.yaml ← разметка        └── shot4.jpg
│   └── Б/ base.png  + sprite_1.png (неск. эталонов на класс)
└── digits/
    └── 1/ base.png
```

- **classes_dir** — класс = **листовая папка** со спрайтами; промежуточные папки
  становятся подклассами (иерархия `letters/А` сохраняется в метке как `class_path`).
  Несколько эталонов в классе → движок берёт случайный на каждый кадр. Имена
  листовых папок должны быть уникальны. Папки на `.`/`_` и файлы верхнего уровня
  игнорируются.
- **meta.yaml** (в любой папке, опционально) — разметка узла, **наследуется вниз**:
  ```yaml
  display_name: Буква А      # человекочитаемое имя
  symmetry: none             # переопределить симметрию рядом с данными (опц.)
  tags: [letter, ru]         # произвольная разметка — любые поля допустимы
  artikul: A-001             # → попадёт в classes.json и доступно обучению
  ```
  Приоритет симметрии: глобальный `overrides` из конфига → `meta.yaml` → авто-детектор.
- **backgrounds_dir** — фото фона; сканируется рекурсивно (подпапки-категории).
  Если не задан (`null`) — процедурные фоны нескольких типов (градиент, шлифованный
  металл, лента с планками, пятнистая). Фон под кадр выбирается случайно и кропается —
  это и есть «подстановка фона через аугментацию».

## Аугментации

Каждая — отдельный включаемый блок с диапазонами в конфиге; можно собирать
любые комбинации. Фотометрия применяется ОДНИМ проходом на весь кадр после
композиции (в порядке сцена → оптика → сенсор → кодек):

| Группа | Аугментации |
|--------|-------------|
| Геометрия (до/при композиции) | поворот, сдвиг X/Y, масштаб |
| Сцена | блик (glare), мягкая тень (shadow), **контактная тень под объектом** (contact_shadow — анти-«парение»), окклюзия/cutout (occlusion) |
| Оптика | гауссово размытие, motion blur, виньетка (vignette) |
| Сенсор | яркость/контраст, gamma (тонмаппинг), цветовая температура, сдвиг каналов, гауссов шум |
| Кодек | JPEG-артефакты |

`output.supersample` (>1) — композиция на увеличенном холсте с финальным
downscale: сглаживает шов вклейки. `contact_shadow` рисуется на фон ДО объекта,
остальная фотометрия — единым проходом после композиции.

## Симметрия и метка угла

Симметрия — вычисляемое свойство класса (авто-детектор по пиксельной разности
поворотов), с ручным override в конфиге. Кодирование угла:

| Тип | Кодирование | Смысл |
|-----|-------------|-------|
| `none` | (sin θ, cos θ) | полный диапазон 0–360° |
| `180` | (sin 2θ, cos 2θ) | θ и θ+180° неразличимы — метки совпадают |
| `full` | (0, 0), `angle_valid=False` | угол не определён — исключить из loss |

Обучающий код обязан маскировать loss по углу флагом `angle_valid`.

Детектор использует два порога: `threshold` (абсолютный) и `rel_threshold`
(относительный — спасает от «разбавления» метрики большой инвариантной областью,
например буква П на круглом диске).

## Пресет ru_letters_disk

33 класса (А–Я с Ё), 128×128, поворот 0–360°, блики (глянец) + motion blur
(конвейер). Эталоны генерируются один раз:

```bash
python -m Services.dataset_gen.tools.make_ru_letter_sprites --out data/dataset_gen/ru_letters/sprites
```

Авто-детектор на этих спрайтах (Arial Bold): **full** — О; **180°** — Ж, И, Н, Ф, Х;
остальные (включая С и П) — **none**. `backgrounds_dir: null` → процедурные фоны;
для боевого датасета укажите фото реальной сцены.

## Границы

- НЕ обучает модель — только генерирует данные (обучающий сервис —
  [`Services/ml_train`](../ml_train/README.md), контракт стыковки =
  `SampleLabel` / target-словарь `SyntheticDataset`)
- НЕ pipeline-плагин (нет GUI/IPC); чистая библиотека уровня Services
- Зависимости: numpy, OpenCV, Pillow, PyYAML, Pydantic; torch и pyarrow — опционально
- Не импортирует `multiprocess_prototype.*` (правило слоя Services)

## Грабли (Windows)

Имена классов бывают кириллицей («А/», «Б/») — `cv2.imread`/`imwrite` не умеют
non-ASCII пути на Windows. Весь I/O — через `imread_unicode`/`imwrite_unicode`
([core/catalog.py](core/catalog.py)). При генерации эталонов критично центрирование
глифа по фактическому bbox чернил — смещение в полпикселя ломает детекцию
180°-симметрии (см. [tools/make_ru_letter_sprites.py](tools/make_ru_letter_sprites.py)).

## Стабильность

contract — README + interfaces.py (Protocol) + Pre/Post в docstrings + contract-тесты (100).
