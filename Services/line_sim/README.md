# line_sim — движок сцены «лента с объектами»

Объект-агностичный движок синтетической ленты: объект собирается из слоёв, кладётся
на ленту, едет по энкодеру. В отличие от `dataset_gen` (один объект на кадр для
обучения) сцена держит НЕСКОЛЬКО объектов на непрерывно движущейся ленте.

Зависимости: numpy, opencv, pydantic, pyyaml. Без torch и PySide6 (сверяется тестом в подпроцессе). Транзитивно: `Services.robot_comm` (pymodbus) через импорт констант из `robot_comm.core.registers` — около 0.3 с на холодный импорт; перенос констант — отдельный follow-up.
Геометрия слоя переиспользует `Services.dataset_gen.core.compose` (`rotate_expand`, `composite`).

## Публичный контракт

```python
from Services.line_sim import (
    ObjectPassport, LayerSpec, LayerAugment, LayeredObject, ObjectFactory, ScenePreset,
    SceneCompositor, encoder_to_offset_mm, FACTOR_MM, BELT_UX, BELT_UY,
)
```

| Символ | Где | Что |
|---|---|---|
| `LayerSpec` | `interfaces.py` | слой: `name`, `mode` (`static`/`augmented`/`defect`), `sprite_source`, `offset_px`, `angle_deg`, `scale`, `augment`, `defect_probability` |
| `LayerAugment` | `interfaces.py` | диапазоны `(lo, hi)`: `offset_x_px`, `offset_y_px`, `angle_deg`, `scale`, `hue_shift_deg`; дефолт — «нет вариации» |
| `ObjectPassport` | `interfaces.py` | `object_id`, `class_name`, `angle_deg`, `defect`, `spawn_encoder`, `layer_params` |
| `SceneCompositor` | `interfaces.py` | Protocol сцены: `spawn`, `despawn_stale`, `render(now_encoder, camera_rect)` — реализация в Task 3.4 |
| `LayeredObject` | `core/layered_object.py` | `LayeredObject(passport, layers, rng)`; `render()` без аргументов |
| `ScenePreset` | `core/preset.py` | Pydantic-конфиг: `catalog_dir`, `angle_range_deg`, `defect_probability`, `layers` — `from_dict`/`to_dict`/`from_yaml`/`to_yaml` |
| `ObjectFactory` | `core/factory.py` | `ObjectFactory(preset)`: `num_classes`, `class_names`, `make(object_id, spawn_encoder, rng) -> LayeredObject`, `force_defect_next()` — Task 3.2 |
| `encoder_to_offset_mm` | `core/belt.py` | `(enc_now - spawn_enc) * FACTOR_MM`; константы — из `Services.robot_comm.core.registers` |

## Выборка и рендер — один раз

`LayeredObject.__init__` потребляет всю случайность (аугментация, розыгрыш дефекта) из
переданного `rng`, компонует RGBA и кэширует. `render()` случайности не потребляет и
возвращает тот же **read-only** массив (запись в него — `ValueError`; нужна правка — `.copy()`).
Callable-провайдер `sprite_source` вызывается ровно один раз на слой при создании объекта — для всех слоёв, включая невыпавшие defect-слои (все спрайты проверяются до розыгрыша).
Итоговые значения — в `obj.passport.layer_params` (`augmented` — пять чисел, `defect` —
`{"active": bool}`), `obj.passport.defect` — имена активных defect-слоёв через запятую
или `None`. Входной паспорт не мутируется. Непустой входной `passport.defect` принудительно
включает названные defect-слои без розыгрыша (неизвестное имя — `ValueError`).
Слой i берёт случайность из `rng.spawn(len(layers))[i]`: розыгрыш одного слоя не сдвигает
выборку других, а **порядок слоёв — часть контракта seed** (LS-006).

## Конвенция поворота и холста

Угол — в градусах, положительный = **против часовой стрелки (CCW)** на экране, ось Y
направлена вниз, как в OpenCV (`cv2.getRotationMatrix2D`, `dataset_gen.core.compose.rotate_expand`).
Литерал: метка справа от центра (+5, 0) при `angle_deg=+90` у объекта оказывается сверху (0, −5).
Центр объекта = центр массива, который возвращает `render()`: канва симметрична, расширяется
под слой, выехавший за базу, и по альфе не обрезается. Точность — не абсолютная: остаток до
0.5 px от целочисленной постановки `composite`, на произвольных углах до ~0.9 px (LS-005). Слои рисуются в порядке списка
(первый — снизу); defect-слой рисуется поверх предыдущих, если выпал.
Единицы — пиксели; миллиметры придут с редактором Ф7.

## Пресет

На dict/YAML-границе `sprite_source` — строка-идентификатор; `ScenePreset` картинок сам не
читает (Dict at Boundary) — загрузку по id делает `ObjectFactory` (LS-007). `LayeredObject`
строковый источник отвергает с `TypeError` — до фабрики в него попадают только RGBA-массивы.
Ошибки валидации — pydantic `ValidationError` с именем слоя и поля
(`слой 'x': augment.angle_deg: lo=30.0 > hi=-30.0`).
YAML пишется `yaml.safe_dump` — комментарии не сохраняются (ruamel — с редактором Ф7).

Новые поля (Task 3.2): `catalog_dir: str | None` — путь к каталогу классов в формате
`Services.dataset_gen.core.catalog.SpriteCatalog`; `angle_range_deg: tuple[float, float] =
(0.0, 360.0)`; `defect_probability: float = 0.0` (`[0, 1]`); `layers: list[LayerSpec] = []` —
ДОПОЛНИТЕЛЬНЫЕ слои поверх базы каталога (не путать с 3.1, где `layers` был единственным
источником). Пресет без `catalog_dir` И без `layers` — `ValidationError` (нечего рисовать).
`from_yaml` резолвит относительные `catalog_dir` и `layers[*].sprite_source` от каталога
файла — тот же паттерн, что `GeneratorConfig.from_dict(..., base_dir)` в `dataset_gen`; id-строки
со схемой (`"fixture://..."`, `"://"` в значении) НЕ трогаются — это не файловый путь.
`from_dict` резолюцию не делает (нет base_dir, от которого мерить).

## ObjectFactory (Task 3.2)

`ObjectFactory(preset)` — единственное место, которое знает про `SpriteCatalog`
(`core/catalog_bridge.py`, тонкая обёртка над `dataset_gen.core.catalog`): если задан
`catalog_dir`, каталог грузится СРАЗУ в конструкторе (eager — `num_classes` доступен
немедленно), ошибки каталога — как есть от `SpriteCatalog`, не переписываются. Доп. слои
пресета резолвятся туда же (id → RGBA) один раз при конструкции.

`make(object_id, spawn_encoder, rng) -> LayeredObject`: класс — `rng.integers(num_classes)`,
угол — `rng.uniform(*angle_range_deg)`, оба потребляют `rng` ДО того, как он передаётся в
`LayeredObject` (значит `rng` должен быть один и тот же на серию вызовов, иначе класс/угол
не варьируются между объектами). Слои объекта: `base` (`mode="static"`, спрайт класса) →
слои пресета (резолвленные) → **`damaged`** (`mode="defect"`) — дефект строго последним,
как того требует LS-006 (иначе `defect=None` не будет побитово равен объекту без дефект-слоя).

`damaged` — occlusion-пятно (`dataset_gen.core.augment.apply_occlusion`): тёмно-серый
прямоугольник ~35% меньшей стороны базового спрайта, смещённый к верхнему левому углу,
альфа=255 внутри/0 снаружи — новый массив под размер КОНКРЕТНОГО базового спрайта на КАЖДЫЙ
`make()` (катанного каталожного спрайта не касается, только читает `.shape`).

`force_defect_next()` — одноразовый флаг: следующий `make()` получает `passport.defect ==
"damaged"` через существующий механизм `LayeredObject` (принудительный дефект по имени из
паспорта, LS-006), независимо от `defect_probability`. Флаг потребляется В НАЧАЛЕ `make()`,
безусловно — даже если дальше `make()` падает (например каталог не задан), флаг всё равно
израсходован; "следующий" значит "следующий вызов", не "следующий успешный вызов"
(пин выбора — `tests/test_hazards_3_2.py`).

Пресет без `catalog_dir` (только `layers`) даёт `num_classes == 0`, `class_names == []`; его
`make()` поднимает `ValueError` с понятным текстом — выбрать класс не из чего.
