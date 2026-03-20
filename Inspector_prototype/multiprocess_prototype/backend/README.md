# Backend (multiprocess_prototype)

## Структура

- **`configs/`** — общее: [`base_config.py`](configs/base_config.py), [`app_config.py`](configs/app_config.py); реэкспорт схем процессов в [`__init__.py`](configs/__init__.py).
- **`processes/<name>/`** — `process.py` и при необходимости `config.py` (камера), `*_config.py` у robot/gui/database. GUI: [`processes/gui/gui_process.py`](processes/gui/gui_process.py) + [`gui_process_mixin.py`](gui_process_mixin.py).
- **`modules/`** — домен без обязательного `ProcessModule`:
  - **`camera/`** — factory, backends (канон), resize, `register_sync`; процесс камеры в `processes/camera/`.
  - **`processor_frame/`** — детекция, SHM, `ProcessorConfig`; процесс в `processes/processor/`.
  - **`renderer/`** — отрисовка, `RendererConfig`; процесс в `processes/render/`.
- **`shared/`** — `message_as_dict` и т.п.
## Регистры ↔ boot процессов

Поля, общие с GUI-регистрами (`ProcessorRegisters`, `RendererRegisters`, `CameraRegisters`), задаются **только** в [`registers/schemas/`](../registers/schemas/): классы регистров + `*/boot.py` для снимка значений в конфигах процессов. Менять пороги и дефолты — в соответствующих файлах схем.
