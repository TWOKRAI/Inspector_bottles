# line_sim — движок сцены «лента с объектами»

Объект-агностичный движок синтетической ленты: объект собирается из слоёв, кладётся
на ленту, едет по энкодеру. В отличие от `dataset_gen` (один объект на кадр для
обучения) сцена держит НЕСКОЛЬКО объектов на непрерывно движущейся ленте.

Зависимости: numpy, opencv, pydantic, pyyaml. Без torch и PySide6 (сверяется тестом в подпроцессе). Транзитивно: `Services.robot_comm` (pymodbus) через импорт констант из `robot_comm.core.registers` — около 0.3 с на холодный импорт; перенос констант — отдельный follow-up.
Геометрия слоя переиспользует `Services.dataset_gen.core.compose` (`rotate_expand`, `composite`).

## Публичный контракт

```python
from Services.line_sim import (
    ObjectPassport, LayerSpec, LayerAugment, LayeredObject, ScenePreset,
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
| `ScenePreset` | `core/preset.py` | Pydantic-конфиг `{"layers": [...]}`: `from_dict`/`to_dict`/`from_yaml`/`to_yaml` |
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

На dict/YAML-границе `sprite_source` — строка-идентификатор (загрузка по id — Task 3.2);
`LayeredObject` строковый источник пока отвергает с `TypeError`. Ошибки валидации — pydantic
`ValidationError` с именем слоя и поля (`слой 'x': augment.angle_deg: lo=30.0 > hi=-30.0`).
YAML пишется `yaml.safe_dump` — комментарии не сохраняются (ruamel — с редактором Ф7).
