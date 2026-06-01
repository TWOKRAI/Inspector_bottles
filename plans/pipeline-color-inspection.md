# План: атомарные плагины цвет-инспекции + универсальный Modbus-пакет

## Контекст

Владелец хочет цепочку инспекции по цвету, но **атомарными плагинами-кубиками**, а не
монолитным `blob_detector` (он «кастомный»: делает HSV-маску + контуры + площадь +
рисование в одном). Разбиваем на отдельные плагины; рисование — в отдельном процессе,
«как и положено в топологии». Площадь (и любые другие данные) шлём по Modbus — пакет
должен быть **универсальным** (любые поля, любое количество).

`blob_detector`/`color_mask` НЕ трогаем (используются в legacy-топологиях + тестах).

## Целевая топология (рецепт color_inspect.yaml)

```
camera_0 → detector[hsv_mask → contour_finder] ──┬→ painter[contour_draw] → display
                                                  └→ modbus_sink (universal)
```
- `detector` = один процесс, ДВА плагина чейном (PipelineExecutor: out→in, маска не
  покидает процесс). `contour_finder` (последний) дропает `mask`, наружу → `frame`(SHM) +
  `detections` + `contours`.
- `painter` = отдельный процесс (rendering), рисует контур на кадре → дисплей.
- `modbus_sink` = универсальный пакет (площадь/счётчик/размер).

## Плагины

### 1. `hsv_mask` (NEW, Plugins/processing/hsv_mask/)
- in `frame`(BGR) → out `+mask`(uint8 1ch), **кадр сохраняется** (в отличие от color_mask).
- Слайдеры: `h_min/h_max` (0..179), `s_min/s_max` (0..255), `v_min/v_max` (0..255).
- `cv2.cvtColor(BGR2HSV)` + `cv2.inRange`. register live-tunable + config.

### 2. `contour_finder` (NEW, Plugins/processing/contour_finder/)
- in `mask` → `cv2.findContours(RETR_EXTERNAL)` → фильтр по площади →
  out `+detections` ([{bbox, center, area}]) `+contours` (list np-arrays); `mask` дропается.
- Слайдеры: `min_area`, `max_area` (0 = без верх. границы).
- Не рисует. Кадр пробрасывается без изменений.

### 3. `contour_draw` (NEW, Plugins/processing/contour_draw/, category=rendering)
- in `frame` + `contours` → `cv2.drawContours` на КОПИИ кадра → out `frame`.
- Слайдеры: `color_b/color_g/color_r` (0..255), `thickness` (1..20). Если контуров нет —
  кадр без изменений (pass-through). → дисплей.

### 4. `modbus_sink` (ENHANCE, Plugins/sinks/modbus_sink/)
- Заменить фикс `[w,h,fid]` на **конфигурируемый payload** (list[dict], редактируется
  generic JSON-виджетом инспектора). Каждая запись → 1+ регистр(ов) подряд от base_address:
  ```yaml
  payload:
    - {source: width}                                  # u16
    - {source: height}
    - {source: frame_id}
    - {source: detections, reduce: count}              # len → u16
    - {source: detections, reduce: area_sum, dtype: u32}   # Σ area → 2 рег.
    - {source: detections, reduce: area_max, dtype: u32}   # max area → 2 рег.
  ```
  - `source`: ключ item. `reduce` (для списков): `count|area_sum|area_max|first` (для скаляра — нет).
  - `dtype`: `u16` (деф.) | `u32` (через `Services.modbus.sdk.datatypes.encode_uint16/uint32`,
    `word_order` из конфига). u16 свёртка %65536, u32 = 2 регистра.
  - Дефолтный payload = w,h,frame_id,count,area_sum,area_max (работает из коробки;
    адреса 100,101,102 = w,h,fid сохраняются → старые тесты не ломаются).
  - Один `write_registers(base_address, all_regs)`.

## Файлы

| Файл | Действие |
|------|----------|
| `Plugins/processing/hsv_mask/{__init__,plugin,registers,config}.py` + `tests/` | new |
| `Plugins/processing/contour_finder/{__init__,plugin,registers,config}.py` + `tests/` | new |
| `Plugins/processing/contour_draw/{__init__,plugin,registers,config}.py` + `tests/` | new |
| `Plugins/sinks/modbus_sink/registers.py`, `plugin.py`, `tests/test_plugin.py` | enhance — payload |
| `multiprocess_prototype/recipes/color_inspect.yaml` | new рецепт |
| `multiprocess_prototype/app.yaml` | pipeline → color_inspect.yaml |

## Верификация

1. Юнит-тесты каждого плагина (cv2 на synthetic-кадрах: цветной квадрат → маска →
   контур площадью S → детект; modbus payload билдер: u16/u32, reduce-функции; FakeSdkClient).
2. Headless: `presenter._topology_to_graph` на color_inspect → ноды detector(2 плагина)/
   painter/modbus + рёбра.
3. End-to-end с реальным pymodbus: detector→modbus, slave печатает площадь (u32) и счётчик.
4. Ручной два-терминала: `python -m Services.modbus.server` + `python run.py` — на дисплее
   контур вокруг цветного объекта, в терминале сервера — payload с площадью.

## Out of scope
- Изменение color_mask/blob_detector.
- float32/строковые типы в payload (только u16/u32 целые на этом этапе).
