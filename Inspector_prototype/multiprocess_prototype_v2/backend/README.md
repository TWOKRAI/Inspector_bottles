# multiprocess_prototype_v2\backend\README.md

# Backend (multiprocess_prototype_v2)

## Структура

- **`configs/`** — [`base_config.py`](configs/base_config.py) (`ProcessConfigBase`), [`managers_schema_lite.py`](configs/managers_schema_lite.py) (схема и дефолты logger/error/router/stats), [`proc_assembly.py`](configs/proc_assembly.py) (сборка `proc_dict`). Публичный API — в [`__init__.py`](configs/__init__.py); схемы отдельных процессов импортируйте из `modules/.../config` или `processes/.../`*_config*.
- **`processes/<name>/`** — `process.py` и при необходимости `config.py` (камера), `*_config.py` у robot/gui/database. GUI: [`processes/gui/gui_process.py`](processes/gui/gui_process.py) + [`gui_process_mixin.py`](gui_process_mixin.py).
- **`modules/`** — домен без обязательного `ProcessModule`:
  - **`camera/`** — factory, backends (канон), resize, `register_sync`; процесс камеры в `processes/camera/`.
  - **`processor_frame/`** — детекция, SHM, `ProcessorConfig`; процесс в `processes/processor/`.
  - **`renderer/`** — отрисовка, `RendererConfig`; процесс в `processes/render/`.
- **`shared/`** — `message_as_dict` и т.п.

## Регистры ↔ boot процессов

Поля, общие с GUI-регистрами, задаются в [`registers/schemas/`](../registers/schemas/): `processing_tab` / `camera_tab` (boot + `names` + `ProcessorRegisters`). Минимальные заглушки v2 — в `multiprocess_prototype_v2/registers/schemas/`; при необходимости синхронизируйте с полным деревом схем из `multiprocess_prototype`.
