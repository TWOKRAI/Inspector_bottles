---
name: project_hikvision_aspect_ratio
description: Hikvision plugin resizes native frame anamorphically; set resolution to sensor aspect (4:3) or round objects become ellipses
metadata:
  node_type: memory
  type: project
  originSessionId: b9fd435c-64f1-47ec-9dc7-443f357cdb10
---

HikvisionCameraPlugin (`Services/hikvision_camera/plugin/plugin.py:165`) безусловно вызывает `FrameConverter.resize(frame, width, height)` = голый `cv2.resize` БЕЗ сохранения аспекта (`core/converter.py:97`). Камера снимает нативно в **4:3**. Если задать `resolution_width/height` в аспекте 16:9 (1920×1080), круглый объект растягивается по горизонтали в 1.33× → выглядит ЭЛЛИПСОМ. HoughCircles тогда рисует 2 пересекающихся круга.

**Симптом→диагноз:** наблюдаемый аспект эллипса = (target_aspect)/(sensor_aspect). 16:9 над 4:3 = 1.33.

**Fix (config, SHM-безопасный):** в рецепте задавать разрешение в аспекте сенсора — 4:3 (1440×1080 / 2048×1536 / 2592×1944). Ресайз 4:3→4:3 пропорционален → круг круглый. НЕ ставить 0 (SHM сайзится по config WxH). Для детализации датасета — поднять до нативного 4:3.

Связано: [[project_dataset_gen_service]], рецепт `dataset_circle_capture.yaml`.
