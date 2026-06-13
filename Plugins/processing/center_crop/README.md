# center_crop — квадратный crop вокруг найденного центра

Processing-плагин (fan-out 1→N). Вырезает квадрат `side_px` вокруг координаты центра,
пришедшей от `line_filter` (`item["filtered"][*]["xy"]`), и эмитит отдельный кадр на
каждый сработавший центр. Для сбора датасета: один пойманный объект = один квадратный
кадр + `.json` рядом (через `frame_saver` с `write_sidecar`).

## Контракт

| | Порт | Тип | Описание |
|-|------|-----|----------|
| **in** | `frame` | `image/bgr` | Кадр для выреза (ROI) |
| **in** | `trigger_in` | `dict` | Overlay-item `line_filter` (несёт `filtered`) |
| **out** | `frame` | `image/bgr (side,side,3)` | Вырезанный квадрат |

Координата берётся **только** из `filtered` (триггер). Нет `filtered` → 0 выходов
(ничего не сохраняется). `radius` для sidecar восстанавливается сопоставлением `xy`
с `detections` (в пределах `radius_match_dist`).

## Параметры (registers)

| Поле | Дефолт | Смысл |
|------|--------|-------|
| `side_px` | 200 | Сторона квадрата (px) |
| `drop_partial` | false | Вырез вышел за границу → пропустить (приоритетнее pad) |
| `pad_if_oob` | true | Дополнять вне кадра `pad_color` → вырез всегда side×side |
| `pad_color_bgr` | [0,0,0] | Цвет заполнения вне кадра |
| `radius_match_dist` | 30 | Макс. расстояние сопоставления xy↔detection для radius в sidecar (0 = выкл) |

Поведение у границы: `drop_partial` → проверяется первым (пропуск); иначе `pad_if_oob`
→ дополнение до side×side; иначе → обрезка окна к границам (вырез меньше стороны).

## Sidecar (выходной item)

`item["sidecar"]` = `{center_px, radius_px, side_px, crop_h, crop_w, track_id, direction,
seq_id, camera_id, frame_id, timestamp}` — пишется `frame_saver`-ом рядом с кадром.

## Топология

```
camera → ROI(region_split) → circle_detector → line_filter(enter_zone)
   └─frame────────────────────────────┐
   circle_detector ─detections→ line_filter ─overlay→ [Join] center_crop → frame_saver
```
Процесс `center_crop` — в Join-режиме (`inspector.mode=join, inputs:[frame, overlay], primary:frame`):
коррелирует кадр от детектора и сработавшие координаты от `line_filter` по `seq_id`.

## Единицы

`side_px` — в пикселях (калибровки мм↔px нет; см. план Часть 2: после калибровки
`side_px = side_mm / mm_per_pixel`).
