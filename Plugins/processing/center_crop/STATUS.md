# STATUS — center_crop

**Состояние:** v1, реализован (план `dataset-circle-capture`, Часть 1).

## Готово
- [x] Квадратный crop side_px вокруг центра из `filtered.xy`
- [x] Fan-out 1→N (несколько центров в кадре → несколько вырезов)
- [x] Поведение у границы: drop_partial / pad_if_oob / clamp
- [x] sidecar-метаданные (center_px, radius_px, side_px, track_id, seq_id, ...)
- [x] radius из detections (сопоставление по xy)
- [x] Команда set_side (runtime)
- [x] README + контракт
- [x] Тесты (clamp/pad/drop_partial/fan-out/пустой filtered)

## Известные ограничения
- Координата только из `filtered` (требует line_filter в цепочке).
- Размер в пикселях (мм — после калибровки, Часть 2).
- `encoder` в sidecar не пишется (нет в item рабочего pipeline; добавить при интеграции с devices).

## Дальше
- Интеграция размера в мм после hand-eye калибровки (Часть 2).
