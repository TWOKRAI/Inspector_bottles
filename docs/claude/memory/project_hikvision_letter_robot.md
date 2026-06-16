---
name: project-hikvision-letter-robot
description: Рецепт hikvision_letter_robot — боевой тракт робота-укладчика (Hikvision→круг→линия→инференс→робот)
metadata:
  type: project
---

Рецепт `multiprocess_prototype/recipes/hikvision_letter_robot.yaml` — Hikvision-вариант `letter_angle_inspect` для робота-укладчика. Цель: диск с буквой пересекает линию → распознать букву+угол → отдать роботу координаты точки съёма.

**Тракт:** camera_0[hikvision] → cc[color_convert bgr2rgb] → roi[roi_crop] → detector[hsv_mask(белый: s_max 60, v_min 190) → morphology(open_close 5) → circle_detector(input_key=mask, keep_mask)] → line[line_filter] → crop[center_crop 128] → infer[ml_inference] → дисплеи. + maskview→дисплей "mask".

**Цвет:** Hikvision отдаёт RGB → cc свопает в физ. BGR → ml_inference (sidecar color:RGB, сам делает BGR→RGB) получает корректные цвета. Без свопа каналы перепутаны.

**Модель:** `mobilenet_v3_large_20260616_050828` (33 буквы, вход 128×128 RGB, angle_head, ccw_deg).

**ROI = 560,240,800,600** (проверенное окно диска из dataset_circle_capture, диск ~140px радиус). КАЛИБРОВКА ЕЩЁ НЕ СДЕЛАНА → калиброваться с ЭТИМ ЖЕ ROI (гомография ROI-локальная).

**Линия:** вертикальная по центру — `angle=90` (90=вертикаль, 0=горизонталь), center_x=400, zone_width=120, mode=enter_zone.

**Фильтр «один раз» (НЕ будет повторных взятий):** enter_zone+armed-флаг (зачёт на входе, re-arm только после выхода из зоны + hysteresis), min_hits=2 (анти-вспышка), dedup_radius=5, CentroidTracker. emit_mode=current (дефолт) → center_crop кропит ТОЛЬКО событие текущего кадра, не накопленные (accumulated дал бы кроп каждый кадр — НЕ ставить для робота). Один диск через линию = один кроп = одно задание роботу.

**СТАТУС 2026-06-16: Шаг 1 (инференс на Hikvision) ГОТОВ, verified live** — белая маска убрала ложные круги, вертикальная линия рисуется, recog показал «Щ 0.89 91°». ROI/радиус/маску владелец тюнит вживую через Pipeline-инспектор.

**Долг — Шаг 2 и 3:**
- Шаг 2: калибровка камера↔робот (`camera_robot_calibration.yaml` с ROI 560,240,800,600) → `config/calibration/cam0.yaml` (гомография px→мм). Робот 192.168.1.7:502 подключён.
- Шаг 3 (КОД): новый узел px→мм по гомографии → `robot_io` (порт robot_job={x_mm,y_mm}) → процесс devices → `robot_enqueue_job`. enqueue_job сейчас XY-only (без угла); угол доворота = отдельный шаг (правка RobotDriver.enqueue_job + Lua cvt_universal_full.lua). Владелец выбрал v1 = только X/Y.

Грабли: [[project_recipe_inspector_join_key]] (inspector join). Связано: [[project_letter_angle_training]], [[project_calibration_gui_progress]], [[project_pult_control_panel]], [[project_device_hub]].
