# Менеджеры данных App Inspector

Архитектура менеджеров данных с типизацией через Pydantic 2.

## Структура

```
Managers/
├── converter_manager.py    # ConverterManager - универсальная конвертация
├── recipe_manager.py       # RecipeManager - работа с рецептами
├── camera_manager.py       # CameraManager - управление камерами
├── region_manager.py       # RegionManager - управление регионами
├── data_manager.py         # DataManager - координатор CameraManager/RegionManager/RecipeManager
├── params_manager.py       # ParamsManager - сбор параметров из виджетов, применение рецептов
├── logging_manager.py      # LoggingManager - централизованное логирование
├── error_manager.py        # ErrorManager - обработка и статистика ошибок
├── translation_manager.py  # TranslationManager - i18n через metadata Pydantic-полей
└── window_manager.py       # WindowManager - жизненный цикл окон, IPC, доступ
```

## Цепочка данных

**Registers (схемы)** → **Data (работа с данными)** → **Recipes (слепки)**

1. **Registers** (`App/Registers/models/data/`) - схемы данных (CameraData, RegionData, ChainStepData)
2. **Managers** - работа с данными через типизированные модели
3. **Recipes** - сохранение/загрузка слепков данных

## Использование

### Базовое использование

```python
from App.Core.Managers import DataManager, RecipeManager, ConverterManager

# Создание менеджеров
converter = ConverterManager()
recipe_manager = RecipeManager(converter=converter)
data_manager = DataManager(recipe_manager=recipe_manager, converter=converter)

# Работа с камерами
camera_id = data_manager.add_camera(name="Camera 1")
camera = data_manager.camera_manager.get_camera(camera_id)

# Работа с регионами
data_manager.add_region(camera_id, "region_1", x1=0, y1=0, x2=100, y2=100)
region = data_manager.region_manager.get_region(camera_id, "region_1")

# Сохранение в рецепт
data_manager.save_to_recipe("backup")
```

### Типизация

Все данные типизированы через Pydantic модели:

```python
from App.Registers.models.data import CameraData, RegionData

# Валидация при создании
camera = CameraData(name="Test", regions={"main": RegionData(x1=0, y1=0, x2=100, y2=100)})

# Автодополнение в IDE
camera.name  # str
camera.regions["main"].x1  # int
```

### Конвертация

```python
from App.Core.Managers import ConverterManager

converter = ConverterManager()

# JSON
json_str = converter.to_json(camera_data)
camera = converter.from_json(json_str, CameraData)

# YAML
yaml_str = converter.to_yaml(camera_data)
camera = converter.from_yaml(yaml_str, CameraData)

# Плоский словарь (для рецептов)
flat = converter.to_flat_dict(registers_manager)
structured = converter.from_flat_dict(flat, RegistersManager)
```

## ParamsManager

Управляет параметрами виджетов и применением рецептов. Переехал из `App/Components/` в `App/Core/Managers/` — это менеджер, а не UI-компонент.

```python
from App.Core.Managers import ParamsManager
from App.Widget.Sort_widjet.sort_data import SortData

sort_data = SortData()
manager = ParamsManager(
    widgets_dict={"processing": processing_widget, "robot": robot_widget},
    sort_data=sort_data,
)

# Применить рецепт №3 ко всем виджетам
manager.apply_recipe(3)

# Сохранить текущее состояние как рецепт №3
manager.save_recipe(3)

# Получить все параметры
params = manager.get_all_params()
```

Виджет должен реализовывать `get_params() -> dict` и `apply_params(params: dict)`.

## Обратная совместимость

DataManager предоставляет методы для обратной совместимости со старым кодом:
- `get_cameras()`, `get_camera()`, `add_camera()`
- `get_regions()`, `get_region()`, `add_region()`
- `get_chains()`, `add_chain_step()`, и т.д.

Все методы возвращают словари для совместимости со старыми виджетами.
