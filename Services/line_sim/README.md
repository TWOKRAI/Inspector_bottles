# line_sim — движок сцены «лента с объектами»

Объект-агностичный движок синтетической ленты: объект собирается из слоёв, кладётся
на ленту, едет по энкодеру. В отличие от `dataset_gen` (один объект на кадр для
обучения) сцена держит НЕСКОЛЬКО объектов на непрерывно движущейся ленте.

Зависимости: numpy, opencv, pydantic, pyyaml. Без torch и PySide6 (сверяется тестом в подпроцессе). Транзитивно: `Services.robot_comm` (pymodbus) через импорт констант из `robot_comm.core.registers` — около 0.3 с на холодный импорт; перенос констант — отдельный follow-up.
Геометрия слоя переиспользует `Services.dataset_gen.core.compose` (`rotate_expand`, `composite`).

## Публичный контракт

```python
from Services.line_sim import (
    ObjectPassport, LayerSpec, LayerAugment, LayeredObject, ObjectFactory, ObjectSpawner,
    ScenePreset, SceneCompositor, SceneCompositorProtocol, encoder_to_offset_mm,
    FACTOR_MM, BELT_UX, BELT_UY,
)
```

| Символ | Где | Что |
|---|---|---|
| `LayerSpec` | `interfaces.py` | слой: `name`, `mode` (`static`/`augmented`/`defect`), `sprite_source`, `offset_px`, `angle_deg`, `scale`, `augment`, `defect_probability` |
| `LayerAugment` | `interfaces.py` | диапазоны `(lo, hi)`: `offset_x_px`, `offset_y_px`, `angle_deg`, `scale`, `hue_shift_deg`; дефолт — «нет вариации» |
| `ObjectPassport` | `interfaces.py` | `object_id`, `class_name`, `angle_deg`, `defect`, `spawn_encoder`, `layer_params`; `to_dict()`/`from_dict()` — Dict at Boundary (Task 3.4) |
| `SceneCompositorProtocol` | `interfaces.py` | Protocol сцены: `spawn`, `despawn_stale`, `render(now_encoder, camera_rect)` (переименован из `SceneCompositor` при подключении конкретного класса, LS-009) |
| `SceneCompositor` | `core/scene_compositor.py` | конкретная реализация Protocol (Task 3.4): `SceneCompositor(spawner, px_per_mm, belt_y_px, background_bgr=(60,60,60))`, `render(now_encoder, camera_rect) -> (frame_rgb, passports)` |
| `LayeredObject` | `core/layered_object.py` | `LayeredObject(passport, layers, rng)`; `render()` без аргументов |
| `ScenePreset` | `core/preset.py` | Pydantic-конфиг: `catalog_dir`, `angle_range_deg`, `defect_probability`, `layers` — `from_dict`/`to_dict`/`from_yaml`/`to_yaml` |
| `ObjectFactory` | `core/factory.py` | `ObjectFactory(preset)`: `num_classes`, `class_names`, `make(object_id, spawn_encoder, rng) -> LayeredObject`, `force_defect_next()` — Task 3.2 |
| `ObjectSpawner` | `core/spawner.py` | `ObjectSpawner(factory, interval_s, scene_length_mm)`: `tick(now_encoder, now_wall_s, rng)`, `active_objects()`, `set_paused(bool)`, `force_defect_next()` — Task 3.3 |
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

`ObjectPassport.to_dict()`/`from_dict()` (Task 3.4, Dict at Boundary) — сериализация на границу
мира (`StateProxy.set`): все поля, включая `layer_params`; numpy-скаляры внутри `layer_params`
(например `np.float32` в `augmented`-полях) приводятся к нативным типам через `.item()`.
`from_dict(p.to_dict()) == p`.

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

Имена `"base"` и `"damaged"` в `layers` зарезервированы за `ObjectFactory` — при заданном
`catalog_dir` слой пресета с таким именем отклоняется `ValidationError` на границе пресета
(коллизия с именем слоя, который фабрика ставит сама). Без `catalog_dir` (layers-only пресет)
имя `"base"` остаётся легальным — коллизии там нет, `ObjectFactory` в эту ветку не заходит.

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
альфа=255 внутри/0 снаружи, ДОПОЛНИТЕЛЬНО замаскированный альфой базового спрайта
(`np.minimum`) — на круглом диске пятно не красит прозрачные углы квадратного холста. Новый
массив под размер КОНКРЕТНОГО базового спрайта на КАЖДЫЙ `make()` (каталожного спрайта не
касается, только читает `.shape`/альфу).

`force_defect_next()` — одноразовый флаг: следующий УСПЕШНЫЙ `make()` получает
`passport.defect == "damaged"` через существующий механизм `LayeredObject` (принудительный
дефект по имени из паспорта, LS-006), независимо от `defect_probability`. Флаг ЧИТАЕТСЯ в
начале `make()`, но гасится ТОЛЬКО после того, как `LayeredObject` успешно построен —
транзитная ошибка (например каталог моргнул на одном вызове) не съедает нажатие оператора:
следующий успешный вызов всё равно получит дефект (пин — `tests/test_hazards_3_2.py::
test_force_defect_survives_transient_catalog_failure`).

Пресет без `catalog_dir` (только `layers`) даёт `num_classes == 0`, `class_names == []`; его
`make()` поднимает `ValueError` с понятным текстом — выбрать класс не из чего.

## ObjectSpawner (Task 3.3, ревью 2026-09-22)

`ObjectSpawner(factory, interval_s, scene_length_mm, max_active=200)` (`ValueError` в
конструкторе при `lo > hi`, `lo <= 0`, `scene_length_mm <= 0` или `max_active <= 0`, с именем
параметра в тексте) владеет часами спавна и списком активных объектов; единственная точка
входа — `tick(now_encoder, now_wall_s, rng)` (keyword-only).

Порядок внутри `tick()`: (1) деспавн на КАЖДОМ тике — объект снимается, когда
`encoder_to_offset_mm(now_encoder, passport.spawn_encoder) > scene_length_mm` (строго больше;
равно — ещё на сцене), считается по СОБСТВЕННОМУ `spawn_encoder` объекта, не по общему счёту
спавнера; (2) первый `tick()` только взводит срок (`now_wall_s + rng.uniform(*interval_s)`) и
не создаёт объект; (3) на паузе (`set_paused(True)`) — только `return`, новый объект не
создаётся, но деспавн (шаг 1) уже отработал; (4) когда `now_wall_s >= срок` и
`len(active_objects()) < max_active` — РОВНО один `factory.make(object_id,
spawn_encoder=now_encoder, rng=rng)`, новый срок = `now_wall_s (текущего тика) + новый
interval` — пропущенные интервалы НЕ догоняются.

Срок сдвигается НА ОКНЕ (`now_wall_s >= срок`) НЕЗАВИСИМО от того, успел ли `factory.make()`
(ревью fix F1): если фабрика падает постоянно, исключение прилетает на ЧАСТОТЕ ИНТЕРВАЛА, а не
на частоте каждого кадра продюсера (репродукция ревью: 286 исключений за 300 тиков на 30 fps до
фикса) — **вызывающий (Task 3.4) обязан ловить исключение из `tick()`**, спавнер его не
проглатывает. `object_id`-счётчик инкрементируется только ПОСЛЕ успешного `make()`: неудачная
попытка не тратит id и НЕ ретраится в том же окне — транзитный сбой теряет ровно один объект
этого окна, не больше; форс-брак, взведённый до сбоя, не теряется — фабрика гасит флаг только
после успешной сборки (LS-006/LS-007).

`max_active` (ревью fix F2, LS-008) — потолок активного списка, НЕ энкодерное правило: при
`len(active_objects()) >= max_active` спавн пропускается (срок НЕ трогается — сработает, как
только появится место), без исключения и без потери существующих объектов. Деспавн зависит
ТОЛЬКО от энкодера — у остановленной ленты нет своего выхода из накопления, поэтому потолок
ограничивает память (без него — 600 объектов / 259 МБ кэша рендера за 5 симулированных минут,
замер ревью). **Остановить сам ПОТОК спавна при остановке ленты — ответственность вызывающего**
(`set_paused(True)`, Task 3.4 / Ф6) — спавнер не делает этого сам, потолок только ограничивает
худший случай, если вызывающий этого не сделает.

`active_objects() -> list[LayeredObject]` — КОПИЯ списка (`list(self._active)`): мутация
результата спавнер не трогает.

Форс-хук брака «выпусти брак сейчас» — `spawner.force_defect_next()`, тонкий делегат
`factory.force_defect_next()` (Task 3.2). На паузе объект НЕ создаётся — флаг помечает
СЛЕДУЮЩИЙ реальный спавн (после снятия паузы); брак не теряется, потому что фабрика гасит флаг
только после успешной сборки (LS-006/LS-007). Выбран этот вариант (не «спавнить немедленно,
игнорируя паузу») — оператор не получает объект на остановленном потоке (LS-008).

**Известные не-гарантии (называем стоимость, не только выгоду; ни одна не «невозможна» —
у каждой есть репродукция или прямое следствие из механизма):**
- падающая фабрика раскрывается наружу из `tick()` (на частоте интервала после fix F1) —
  продюсер Task 3.4 обязан её ловить, иначе один сбой уронит кадровый цикл;
- деспавн зависит ТОЛЬКО от энкодера: остановленная лента — это одновременно «новых объектов
  нет» (после `set_paused`) И «деспавна нет» (объекты просто перестают двигаться) — поток
  заполняется до `max_active` и там стоит;
- энкодер знаковый (`REG_ENC` — `RegDW(signed=True)`, `Services.robot_comm.core.registers`):
  если он идёт назад, `encoder_to_offset_mm` даёт отрицательное смещение, и такой объект
  никогда не пересечёт `scene_length_mm` — не деспавнится.

Единственный producer — поток-продюсер кадров (Task 3.4); `ObjectSpawner` НЕ потокобезопасен
намеренно (лока нет) — второй одновременный вызывающий на одном инстансе не предусмотрен.

## SceneCompositor (Task 3.4)

`SceneCompositor(spawner, px_per_mm, belt_y_px, background_bgr=(60, 60, 60))` — конкретная
реализация `SceneCompositorProtocol`: держит `ObjectSpawner` и рисует его активные объекты
на фон камеры. `render(now_encoder, camera_rect) -> tuple[np.ndarray, list[ObjectPassport]]`,
где `camera_rect = (x_px, y_px, w_px, h_px)`.

Кадр — **RGB** `uint8` формы `(h_px, w_px, 3)`; в BGR переводит вызывающий (плагин), НЕ этот
класс. Параметр `background_bgr` концептуально BGR (имя из контракта тестера) — компоновщик
переставляет каналы при заливке фона, так что после конвертации плагином `RGB → BGR` итоговый
`item["frame"]` содержит именно эти байты в этом порядке.

Центр объекта: `cx = encoder_to_offset_mm(now_encoder, passport.spawn_encoder) * px_per_mm -
x_px`, `cy = belt_y_px - y_px`; рисуется альфа-композицией (`dataset_gen.core.compose.
composite`, тот же примитив, что `LayeredObject`). Возвращаются паспорта объектов, чей bbox
пересекается с `camera_rect` (частично видимый — считается видимым, отрисовывается только
видимая часть); порядок — спавна (`spawner.active_objects()`). bbox, касающийся края РОВНО
(нулевая полоса пересечения), — невидим (строгие неравенства, решение автора).

`render()` **не** зовёт `spawner.tick()` — тик (часы, `rng`) принадлежит вызывающему
(плагину): один producer, одни часы. Пустой спавнер → кадр одного фона, без исключений.
Объекты рисуются в порядке спавна — при перекрытии более поздний перекрывает более ранний
(z-order = порядок списка, без отдельного сортировочного ключа).
