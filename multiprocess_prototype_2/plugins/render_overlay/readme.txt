RenderOverlayPlugin — наложение маски и bounding boxes на кадр

Category: processing
Inputs:   frame (image/bgr) — BGR-кадр, mask (image/gray) — бинарная маска (опционально), detections (list[dict]) — список детекций (опционально)
Outputs:  rendered_frame (image/bgr) — кадр с наложением

Описание:
  Накладывает цветную маску с alpha blending на оригинальный кадр.
  Рисует bounding boxes из detections если включено.
  Результат записывается в item["rendered_frame"].

Команды:
  - set_alpha            — установить прозрачность маски (0.0-1.0)
  - set_color            — установить цвет маски BGR
  - toggle_detections    — вкл/выкл отрисовку bounding boxes

Config:
  - mask_alpha (float, 0.5) — прозрачность маски
  - mask_color_b/g/r (int, 0/255/0) — цвет маски BGR
  - draw_detections (bool, True) — рисовать bounding boxes
  - line_thickness (int, 2) — толщина линий bbox
  - label_font_scale (float, 0.5) — размер шрифта подписей

Зависимости:
  - opencv-python (cv2)
  - numpy

Справочник v1: multiprocess_prototype/backend/plugins/render/plugin.py
