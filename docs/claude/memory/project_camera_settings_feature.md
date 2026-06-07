---
name: project_camera_settings_feature
description: Отложенная фича — настройки камеры во вкладке Services (пресеты + actual params, Live + persist)
metadata:
  type: project
---

Владелец отложил «в новый чат»: фича настроек камеры во вкладке **Services**.

**Что нужно:**
- Пресеты разрешения/FPS/exposure + отображение **actual** параметров (что камера реально применила, через `cap.get(...)` после `cap.set(...)`).
- Live-применение (на лету, без рестарта процесса) + persist в config.

**Контекст для старта:** камера = `CapturePlugin` (`cv2.VideoCapture`, DirectShow). Известный смежный долг: без `MJPG` FOURCC DirectShow упирается в ~15fps (джиттер 40↔65мс). Live-применение параметров — через адресный register-write по плагину (см. [[project_pipeline_live_control_stage2]] резолвер plugin_name + register_update через RouterManager). Связано с [[project_recipe_hotswap]].
