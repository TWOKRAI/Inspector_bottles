# База красных до волны 1 (заполняет лид)

- **Коммит:** `85a7906d1` (`integ/multicam-obs`)
- **Когда:** до старта developer-ов W1-a, W1-a2, W1-b, W1-c
- **Радиусы (по одному каталогу, класс medium):** `Services/camera_device/tests`, `Services/hikvision_camera/tests`, `Services/code_reader/tests`, `multiprocess_framework/modules/process_module/tests`, `multiprocess_framework/modules/logger_module/tests`
- **Команда:** `bash "$(git rev-parse --path-format=absolute --git-common-dir)/../scripts/machine_gate.sh" medium <session> <py> -m pytest -q --tb=no -rfE <каталог>`

| test id | status | note |
|---|---|---|
