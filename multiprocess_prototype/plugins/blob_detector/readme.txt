BlobDetectorPlugin — детекция цветных контуров по HSV-маске

Category: processing
Inputs:   frame (image/bgr) — BGR-кадр
Outputs:  frame (image/bgr) — кадр (опционально с контурами), detections (list[dict]), mask (image/gray)

Описание:
  Применяет HSV-маску к BGR-кадру, находит контуры через cv2.findContours,
  фильтрует по площади (min_area/max_area), возвращает detections с bbox/center/area.
  Опционально рисует контуры на кадре.

Команды:
  - set_color_range    — обновить HSV-диапазон
  - set_area_range     — обновить min/max площадь
  - toggle_draw_contours — вкл/выкл отрисовку контуров

Config:
  - h_min/h_max (int, 0/180) — Hue диапазон
  - s_min/s_max (int, 50/255) — Saturation диапазон
  - v_min/v_max (int, 50/255) — Value диапазон
  - min_area (int, 100) — минимальная площадь контура (px²)
  - max_area (int, 0) — максимальная площадь (0 = без ограничения)
  - draw_contours (bool, False) — рисовать контуры на кадре
  - contour_color_bgr (list[int], [0,255,0]) — цвет контуров BGR
  - contour_thickness (int, 2) — толщина линий контуров

Зависимости:
  - opencv-python (cv2)
  - numpy

Справочник v1: multiprocess_prototype/services/processor/detection.py
