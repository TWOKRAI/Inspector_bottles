---
name: project-sketch-robot-draw
description: Рисование портрета роботом — 3 дисплея (оригинал/line-art/точки) + заморозка кадра + отправка по кнопке
metadata:
  type: project
---

Фича «портрет роботом» (ветка `feat/sketch-robot-draw`): вебкамера → сегментация → TEED line-art → точки → рисование роботом. Порт логики из внешнего `D:/PROJECT_INNOTECH/projects_obsidian/sketch_robot` (run_v3.py = эталон цепочки).

**Рецепт** `multiprocess_prototype/recipes/webcam_sketch.yaml` — 4 процесса, **3 дисплея**:
- `camera_0` [capture] → `seg` → дисплей «Оригинал»
- `seg` [segmentation] → `lines` → дисплей «Line-art»
- `lines` [edge_detection→blob_filter→strokes_to_points] → `points` → дисплей «Карта точек»
- `points` [points_render→robot_draw]

**Новые плагины:**
- `Plugins/processing/edge_detection` — метод `teed` (PyTorch, vendor `_vendor/teed/`, ОСНОВНОЙ для робота-линий). **TEED threshold≈0.5 оптимум**: ниже 0.5 ПЕРЕСЫЩАЕТ на сегментированном кадре (белый фон даёт edge_map~0.4 → всё бело), не «больше деталей». Есть второй метод `u2net_portrait` (ONNX, vendor `_vendor/portrait/`), НО `u2net_portrait.onnx` из кэша = **saliency/сегментация** (заливает субъект), НЕ рисунок линий → даёт кашу, для линий НЕ годится. Тумблер `invert`. Веса в `~/.cache/sketch_robot/`.
- `Plugins/processing/blob_filter` — фильтр шума по площади (connected components).
- `Plugins/processing/segmentation` — mediapipe selfie segmenter, человек на белом. **Требует `uv pip install mediapipe`** (УСТАНОВЛЕН 2026-06-15: mediapipe 0.10.35 + opencv-contrib-python 4.13 → даёт cv2.ximgproc.thinning; модель selfie_segmenter.tflite в кэше). Без пакета — кадр с подсказкой «SEGMENTATION OFF». Сегментация кормит TEED → линии без фоновых краёв.
- `Plugins/processing/strokes_to_points` — линия→точки. **centerline-режим (дефолт)**: skeletonize (cv2.ximgproc.thinning → skimage → numpy Zhang-Suen) + trace_skeleton (граф-обход) = ОДНА центральная линия, НЕ контур из двух. Прореживание dp/step/angle. **Зона по углам** (`zone_mode` + zone_x0/y0/x1/y1 мм) ИЛИ scale+offset+flip_y. Считает **непрерывно** (live-карта), НЕ one-shot.
- `Plugins/processing/points_render` — карта точек: pen-down зелёный путь, pen-up красный пунктир (geometry.render_points, bbox-fit в холст).
- `Plugins/io/robot_draw` — форвардер `robot_draw_polyline` в devices. Отправляет **только по команде** `robot_draw_send` (armed), не каждый кадр.

**capture** (`Plugins/sources/capture`): добавлен **freeze** (команды `freeze_capture`/`unfreeze_capture`) — переотправка последнего кадра, чтобы тюнить параметры на статике.

**Кнопки** (роботная вкладка): «Стоп камеры (заморозить)» → `freeze_capture` в camera_0; «Возобновить» → `unfreeze_capture`; «Отправить роботу» → `robot_draw_send` в points. Адресуются в процессы pipeline, НЕ в `devices`.

**Грабли (важно):**
- **Дисплей питается через `chain_targets: [gui]`** процесса-источника. Без `gui` в chain_targets кадры НЕ доходят (дисплей пустой). Это была главная причина «пустого экрана».
- **Маршрутизация дисплеев — по процессу-отправителю** (`build_frame_routing`: node_id → имя процесса → display_id). Поэтому **каждый дисплей = отдельный процесс** (нельзя 3 дисплея из одного процесса).
- Запуск рецепта launch-аргументом (`run.py webcam_sketch`) стартует процессы И поднимает дисплеи рецепта (routing виден в gui-логе `мульти-дисплей: routing=...`).
- Чанкование точек роботу уже в `RobotClient.draw()` (PTS_MAX=100) — не дублировать.

**How to apply:** `uv pip install mediapipe`; `python multiprocess_prototype/run.py webcam_sketch`; sim робота `python -m Services.robot_comm.server` (127.0.0.1:5021). Проверено визуально: 3 дисплея live (FPS 13, TEED на CUDA). Связано: [[project_device_hub]], [[project_robot_vfd_services]], [[project_pipeline_recipe_driven_launch]].
