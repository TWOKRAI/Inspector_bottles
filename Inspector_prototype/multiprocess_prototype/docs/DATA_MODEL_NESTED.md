# Вложенная модель данных (матрёшка) и рецепты

Канон для прототипа **`multiprocess_prototype`**: как устроены камера → ROI → постобработка → параметры алгоритма, где лежит код и как связаны снимки рецептов.

**См. также:** [RECIPES_SYSTEM.md](RECIPES_SYSTEM.md), [ARCHITECTURE.md](ARCHITECTURE.md), ADR-091/092/093 в `multiprocess_framework/DECISIONS.md`.

---

## 1. Инвентаризация регистров (фабрика)

Файл [`registers/factory.py`](../registers/factory.py) создаёт три регистра:

| Имя (`RegistersManager`) | Класс `SchemaBase` | Назначение |
|--------------------------|-------------------|------------|
| `camera` | `CameraRegisters` | Тип камеры, FPS, разрешение, параметры Hikvision (плоская модель под текущую выбранную камеру). |
| `processor` | `ProcessorRegisters` | BGR-диапазон, площадь, **`logical_camera_ids`**, **`crop_regions`**, **`post_processing_regions`**. |
| `renderer` | `RendererRegisters` | Параметры отображения. |

Расширение: новый пакет в [`registers/schemas/<feature>/`](../registers/schemas/), экспорт в [`schemas/__init__.py`](../registers/schemas/__init__.py), подключение в `factory.py`, boot в `schemas/*/boot.py`, маршрутизация в `command_routing.py` / `gui_command_catalog.py`.

---

## 2. Матрёшка в `ProcessorRegisters`

### 2.1 `crop_regions` (ADR-091)

- **Форма:** `camera_id → region_name → [x, y, width, height]` (список из четырёх неотрицательных int).
- **Legacy:** плоский `{ region_name → {params, rect} }` при загрузке переносится под камеру по умолчанию (`default`), см. [`crop_regions_payload.normalize_crop_regions_payload`](../registers/schemas/processing_tab/crop_regions_payload.py).
- **UI:** [`frontend/widgets/cropped_regions_widget/`](../frontend/widgets/cropped_regions_widget/) — таблица и слайдеры; запись через `merge_crop_regions_payload` / `set_field_value`.

### 2.2 `post_processing_regions` (ADR-092)

- **Форма:** `camera_id → [ { name, x1, y1, x2, y2, enabled, is_main, processing_enabled }, ... ]` (порядок списка = порядок в пайплайне).
- **Тип строки:** [`PostProcessingRegionEntry`](../registers/schemas/processing_tab/post_processing_payload.py) → сериализация в dict для YAML.
- **UI:** [`frontend/widgets/post_processing_widget/`](../frontend/widgets/post_processing_widget/).

### 2.3 Параметры детекции (BGR, min_area, …)

Скалярные и векторные поля на уровне **`ProcessorRegisters`**. Перенос «параметров на каждый регион» потребует отдельного ADR (вложенный dict или схема per-region).

---

## 3. Логические камеры и списки в ROI

- **`ProcessorRegisters.logical_camera_ids`:** стабильные id для ComboBox на вкладках ROI и постобработки: `simulator`, `webcam_<device_id>`, `hikvision_<camera_index>` (см. [`logical_cameras.compute_logical_camera_id`](../frontend/coordinators/logical_cameras.py)).
- **Сидирование:** при смене типа камеры на вкладке [`camera_tab`](../frontend/widgets/tabs_setting/camera_tab/) вызывается **`ensure_logical_camera_and_seed_roi`** — id добавляется в список; для нового id создаются регион **`full`** = весь кадр (размеры из **`CameraRegisters`**) и пустой список **`post_processing_regions`**.
- **Синхронизация панелей:** [`CroppedRegionsPanelWidget`](../frontend/widgets/cropped_regions_widget/panel_widget.py) и [`PostProcessingPanelWidget`](../frontend/widgets/post_processing_widget/panel_widget.py) подписываются на **`subscribe_all`** и перезагружают данные при изменении регистра **`processor`**.
- **Полный мульти-поток «несколько независимых камер»** в бэкенде — по-прежнему отдельное решение (ADR-093); текущий список отражает **логический** состав UI и матрёшку в регистрах.

## 3a. Камеры: плоская модель `CameraRegisters`

- Один набор полей в **`CameraRegisters`** (в т.ч. Hikvision); виджет [`hikvision_widget`](../frontend/widgets/hikvision_widget/) управляет UI.

---

## 4. Рецепты и миграция снимков

- **Регистры:** снимок = `RegistersManager.model_dump_all()` в YAML (`register_recipes`), см. [RECIPES_SYSTEM.md §3](RECIPES_SYSTEM.md).
- **Перед загрузкой:** [`migrate_register_recipe_snapshot`](../registers/snapshot_migrate.py) нормализует вложенные поля **`processor`**; затем **`model_validate_all`**.
- **В модели:** `ProcessorRegisters` дополнительно нормализует те же поля при **`model_validate`** (двойной слой: I/O и конструктор).

---

## 5. Редактирование: таблица рецептов vs панели

- **Вкладка «Рецепты» / [`recipes_widget`](../frontend/widgets/recipes_widget/):** таблица всех полей регистров — удобно для **обзора** и правки скаляров; вложенные структуры отображаются как JSON.
- **Основной путь** для ROI и постобработки: соответствующие вкладки и виджеты, затем **«Сохранить в рецепт»** — см. [README панели рецептов](../frontend/widgets/recipes_widget/README.md).

---

## 6. Доставка в процессор (бэкенд)

[`apply_processor_register_update`](../backend/modules/processor_frame/register_sync.py) применяет к детектору поля цвета и площади. Поля **`crop_regions`** и **`post_processing_regions`** в прототипе не маппятся в состояние детектора (снимок для GUI/рецепта; расширение — по задаче пайплайна).
