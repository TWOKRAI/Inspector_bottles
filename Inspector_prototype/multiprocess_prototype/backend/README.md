# Backend (multiprocess_prototype)

## Структура

- **`configs/`** — только общее: [`base_config.py`](configs/base_config.py), [`app_config.py`](configs/app_config.py); реэкспорт всех схем процессов в [`__init__.py`](configs/__init__.py).
- **`processes/<name>/`** — `process.py` и при необходимости `config.py` (камера), `*_config.py` у robot/gui/database.
- **`modules/`** — домен без `ProcessModule`: `processor_frame` (детекция, SHM, `ProcessorConfig`), `renderer` (отрисовка, `RendererConfig`), `camera` (constants, factory, resize; конфиг и процесс в `processes/camera`).
- **`shared/`** — `message_as_dict` и т.п.

## Регистры ↔ boot процессов

Поля, общие с GUI-регистрами (`ProcessorRegisters`, `RendererRegisters`), задаются **только** в [`registers/schemas/`](../registers/schemas/): классы регистров + [`processing_tab/boot.py`](../registers/schemas/processing_tab/boot.py) для снимка значений в `ProcessorConfig` / `RendererConfig`. Менять пороги и дефолты — в `processor.py` / `renderer.py` регистров.
