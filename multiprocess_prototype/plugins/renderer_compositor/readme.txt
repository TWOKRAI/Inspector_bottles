RendererCompositorPlugin — compositing нескольких кадров в один

Category: processing
Inputs:   frame (image/bgr) — кадры от нескольких источников
Outputs:  composite_frame (image/bgr) — составной кадр

Описание:
  Объединяет кадры из нескольких источников в один составной кадр.
  Поддерживает grid (NxM), side-by-side и picture-in-picture layout.
  Опционально добавляет текстовый overlay.

Команды:
  - set_layout         — изменить layout (grid/side_by_side/pip)
  - toggle_overlay     — вкл/выкл текстовый overlay

Config:
  - layout_mode (str, "grid") — тип layout
  - grid_cols/rows (int, 2/2) — размер сетки
  - output_width/height (int, 1280/720) — размер выходного кадра
  - pip_scale (float, 0.25) — масштаб PiP
  - pip_position (str, "top_right") — позиция PiP
  - overlay_enabled (bool, True) — текстовый overlay

Зависимости: opencv-python, numpy
