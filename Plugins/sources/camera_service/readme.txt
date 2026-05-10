CameraServicePlugin — multi-backend камера

Category: source
Inputs:   нет (source plugin)
Outputs:  frame (image/bgr, H*W*3)

Описание:
  Полнофункциональный source-плагин с поддержкой 4 backend'ов камеры:
  simulator (тестовые кадры), webcam (cv2), hikvision (MVS SDK), file (видеофайл).
  Горячее переключение backend'а без перезапуска процесса.

Команды:
  - start_capture       — запустить захват
  - stop_capture        — остановить захват
  - set_camera_type     — переключить backend (simulator/webcam/hikvision/file)
  - set_fps             — установить целевой FPS (1-120)
  - set_resolution      — установить разрешение
  - set_device_id       — OpenCV device index (webcam)
  - set_camera_index    — Hikvision camera index
  - enum_devices        — перечислить доступные устройства
  - hik_open/close/start_grabbing/stop_grabbing/get_parameters/set_parameters

Config:
  - camera_type (Literal, "simulator") — тип бэкенда
  - camera_id (int, 0) — ID камеры в системе
  - device_id (int, 0) — OpenCV device index
  - fps (int, 25) — целевой FPS
  - resolution_width (int, 640) — ширина кадра
  - resolution_height (int, 480) — высота кадра
  - auto_start (bool, False) — автозапуск
  - camera_index (int, 0) — Hikvision camera index
  - hikvision_resolution_width (int, 1920)
  - hikvision_resolution_height (int, 1080)
  - simulator_image_path (str|None, None) — путь к статическому изображению
  - file_source_path (str, "") — путь к видеофайлу
  - ring_buffer_size (int, 3) — SHM ring-buffer slots

Зависимости:
  - opencv-python (cv2)
  - hikvision_camera_module (опционально, для Hikvision backend)

Справочник v1: multiprocess_prototype/services/camera/, multiprocess_prototype/backend/processes/camera/
