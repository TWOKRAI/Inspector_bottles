# Inspector Prototype v2

Прототип системы инспекции дефектов через камеру. Config-driven архитектура: YAML topology — это чертёж системы, плагины — детали конструктора.

## Быстрый старт

### 1. Установка зависимостей

```bash
cd /path/to/Inspector_bottles
uv sync
```

### 2. Запуск минимального примера

```bash
python multiprocess_prototype_2/run.py multiprocess_prototype_2/topology/hello_world.yaml
```

Увидишь окно с трансляцией камеры-симулятора.

### 3. Запуск с полной обработкой

```bash
python multiprocess_prototype_2/run.py multiprocess_prototype_2/topology/inspection_basic.yaml
```

Pipeline: камера → HSV-фильтрация → детекция контуров → наложение маски → GUI.

## Структура проекта

| Директория | Назначение |
|-----------|------------|
| `topology/` | YAML-чертежи системы (hello_world, inspection_basic, multi_camera, ...) |
| `plugins/` | 19 плагинов (source, processing, rendering, output, utility, control) |
| `registers/` | Pydantic-схемы конфигурации плагинов + RegistersManagerV2 |
| `frontend/` | PySide6 GUI: MainWindow, 7 табов, bridge, state bindings |
| `frontend/windows/` | MainWindow (AppHeader, ImagePanel, TabWidget) |
| `frontend/widgets/tabs/` | Табы: settings, recipes, processes, services, plugins, pipeline, displays |
| `frontend/widgets/chrome/` | Общие компоненты: AppHeader, ErrorBanner |
| `frontend/widgets/primitives/` | Базовые элементы: LabeledInput, EnumCombo, ... |
| `frontend/bridge/` | GUI ↔ Runtime интеграция (CommandCatalog, TopologyBridge) |
| `frontend/state/` | GuiStateBindings — реактивные подписки |
| `frontend/actions/` | Undo/Redo через ActionBus |
| `frontend/styles/` | Темы (InnoTech), CSS |
| `config/` | Конфиг приложения (system.yaml, schemas.py) |
| `data/recipes/` | Сохранённые рецепты в YAML |
| `plans/` | Документация фаз разработки |

## Плагины (19 шт.)

| Плагин | Категория | Описание |
|--------|-----------|----------|
| **capture** | source | Захват из видео-файла |
| **camera_service** | source | Камера (simulator / opencv / hikvision) |
| **frame_counter** | utility | Счётчик кадров с метаданными |
| **color_mask** | processing | HSV-фильтрация |
| **grayscale** | processing | Преобразование в градации серого |
| **negative** | processing | Инверсия цветов |
| **flip** | processing | Зеркалирование (H/V/диагональ) |
| **resize** | processing | Масштабирование |
| **region_split** | processing | Разделение на регионы по сетке |
| **blob_detector** | processing | Детекция контуров (OpenCV findContours) |
| **stitcher** | processing | Объединение кадров в мозаику |
| **render_overlay** | rendering | Наложение маски/bbox на кадр |
| **renderer_compositor** | rendering | Композитинг слоёв с альфа-каналом |
| **database** | output | Запись результатов в БД |
| **frame_saver** | output | Сохранение кадров на диск |
| **robot_control** | service | Управление роботом (relay commands) |
| **worker_pool** | control | Пул воркеров (fan-out обработка) |
| **chain_executor** | control | Исполнение цепочки плагинов с DAG |
| **heartbeat** | utility | Heartbeat-мониторинг процессов |

## Как создать новый плагин

### Минимальный пример

Файл `plugins/my_plugin/plugin.py`:

```python
from multiprocess_framework.modules.process_module.plugins.base import PluginBase

class MyPlugin(PluginBase):
    """Мой первый плагин."""
    
    plugin_name = "my_plugin"
    category = "processing"  # source / processing / rendering / output / control / utility
    
    def process(self, items: list[dict]) -> list[dict]:
        """Обработка коллекции items.
        
        items[i] имеет структуру:
          {
            "frame": ndarray (H, W, 3 или 1),
            "timestamp": float,
            "seq_id": int,
            ...другие метаданные...
          }
        
        Возвращай список items (может быть пустым, одного элемента, или развёрнутым).
        """
        for item in items:
            # Логика обработки
            item["my_result"] = ...
        return items
```

### С параметрами конфигурации

Файл `plugins/my_plugin/registers.py`:

```python
from pydantic import BaseModel

class MyPluginConfig(BaseModel):
    """Конфиг для MyPlugin."""
    threshold: int = 100
    invert: bool = False
```

Обнови `plugin.py`:

```python
class MyPlugin(PluginBase):
    plugin_name = "my_plugin"
    category = "processing"
    
    def configure(self, config: dict) -> None:
        """Парсинг конфига (dict → Pydantic)."""
        from .registers import MyPluginConfig
        cfg = MyPluginConfig(**config)
        self.threshold = cfg.threshold
        self.invert = cfg.invert
    
    def process(self, items: list[dict]) -> list[dict]:
        for item in items:
            # Используй self.threshold, self.invert
            ...
        return items
```

### Регистрация в GUI

Файл `registers/my_plugin_config.py`:

```python
from multiprocess_prototype_2.registers.base import RegisterConfig

my_plugin_registers = {
    "my_plugin": RegisterConfig(
        label="My Plugin",
        fields=[
            {
                "name": "threshold",
                "type": "spinbox",
                "default": 100,
                "min": 0,
                "max": 255,
            },
            {
                "name": "invert",
                "type": "checkbox",
                "default": False,
            },
        ],
    ),
}
```

Добавь в `registers/manager.py` при инициализации `RegistersManagerV2`.

### Добавь в topology YAML

```yaml
processes:
  - process_name: processor
    process_class: multiprocess_prototype_2.generic_process_app.GenericProcessApp
    plugins:
      - plugin_class: multiprocess_prototype_2.plugins.my_plugin.plugin.MyPlugin
        plugin_name: my_plugin
        category: processing
        threshold: 120
        invert: true
```

## Запуск тестов

```bash
# Все тесты прототипа
pytest multiprocess_prototype_2/ -q

# Конкретный модуль
pytest multiprocess_prototype_2/frontend/tests/test_bridge.py -v

# С фреймворком
python scripts/run_framework_tests.py
```

## Topology файлы (примеры)

| Файл | Описание | Сложность |
|------|----------|-----------|
| `hello_world.yaml` | Камера → GUI | ⭐ |
| `inspection_basic.yaml` | Камера → HSV → детекция → overlay → GUI | ⭐⭐ |
| `inspection_full.yaml` | Полный pipeline с worker_pool + database | ⭐⭐⭐ |
| `multi_camera.yaml` | 2 камеры с параллельными pipeline | ⭐⭐⭐ |
| `region_pipeline.yaml` | Region split → разная обработка на регионы | ⭐⭐⭐ |
| `TEMPLATE.yaml` | Пустой шаблон для новой topology |  |

## Документация фреймворка

Если нужен более глубокий контекст плагинов, процессов, IPC:

- [`../../multiprocess_framework/docs/MODULES_OVERVIEW.md`](../../multiprocess_framework/docs/MODULES_OVERVIEW.md) — все 21 модули фреймворка
- [`../../multiprocess_framework/docs/MODULE_CONTRACTS.md`](../../multiprocess_framework/docs/MODULE_CONTRACTS.md) — контракты модулей (интерфейсы, сигналы)
- [`../../multiprocess_framework/docs/CONSTRUCTOR_BLUEPRINT.md`](../../multiprocess_framework/docs/CONSTRUCTOR_BLUEPRINT.md) — blueprint конструктора (как собрать систему)
- [`../../multiprocess_framework/docs/DESIGN_RULES.md`](../../multiprocess_framework/docs/DESIGN_RULES.md) — правила архитектуры (Dict at Boundary, SRP, ...)

## Командная справка

| Команда | Действие |
|---------|----------|
| `/validate` | Проверка фреймворка и прототипа |
| `/fw-test` | Запуск тестов фреймворка |
| `/qex-status` | Статус семантического индекса кода |
| `/qex-reindex` | Переиндексация |
| `/run-proto` | Запуск прототипа (с GUI) |

## Фазы разработки

| Фаза | Название | Статус |
|------|---------|--------|
| 5 | Data Pipeline | ✅ |
| 6 | Plugin Migration | ✅ |
| 7 | Registers v2 | ✅ |
| 8 | StateStore + Реактивность | ✅ |
| 9 | GUI Foundations | ✅ |
| 10 | GUI Tabs (7 табов) | ✅ |
| 11 | Recipes + Undo/Redo | ✅ |
| 12 | TopologyBridge v2 | ✅ |
| 12.5 | Bridge Runtime | ✅ |
| 13 | Pipeline Editor (граф + палитра) | ✅ |
| 14 | Schema Ports + FW Extraction | ✅ |
| 15 | Production Ready (документация) | 🔲 |

## Отладка

### Логи

Логи пишутся в:
- `$INSPECTOR_LOG_DIR/system.log` — системные события (StartUp, Shutdown)
- `$INSPECTOR_LOG_DIR/business.log` — бизнес-события (процесс запущен, плагин выполнен)
- `$INSPECTOR_LOG_DIR/performance.log` — метрики (FPS, latency)
- `$INSPECTOR_LOG_DIR/errors.log` — все ошибки (WARNING, ERROR, CRITICAL)

Переменная среды: `export INSPECTOR_LOG_DIR=/tmp/inspector_logs`

### Встроенная диагностика

В GUI tab **Services** → **System Diagnostics**:
- SHM статус (использование памяти)
- IPC очередь (задержки)
- Процессы (PID, RSS, uptime)
- Плагины (state, последняя обработка)

## Контрибьютинг

1. Создай новый плагин или таб в отдельной ветке
2. Добавь unit-тесты (pytest)
3. Запусти `/validate` и убедись что не сломаны имеющиеся тесты
4. Создай PR с описанием

## Лицензия

Proprietary. Copyright 2026 InnoTech.
