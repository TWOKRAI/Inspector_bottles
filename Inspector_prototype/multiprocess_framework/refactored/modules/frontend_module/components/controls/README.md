# components/controls

Виджеты с **привязкой к полю регистра** (`RegistersManager`): числовой слайдер и чекбокс.

## v1 vs v2

- **v1** (slider/, checkbox/): SliderControl, CheckboxControl — наследуют BaseConfigurableWidget.
- **v2** (v2/): NumericControl, CheckboxControl — архитектура **Traits + Presenter + View + Facade** (принцип конструктора: компоненты как переиспользуемые «кубики»). См. `v2/README.md`.

## Структура

| Путь | Назначение |
|------|------------|
| `v2/` | NumericControl, CheckboxControl — фасады; slider, spinbox, checkbox, group, compound |
| `slider/` | `SliderControl`, пакет `schema/`, пересчёт значений, стили, синхронизация с legacy-словарями |
| `checkbox/` | `CheckboxControl`, пакет `schema/`, сборка layout, уведомления |
| `common/` | Типографика (`typography.py`), размеры (`sizes.py`), синхронизация (`field_sync.py`) |
| `primitives/` | Qt-«кирпичи» без знания о регистре: подпись, поле ввода, слайдер, debounce |

## Импорт

```python
from frontend_module.components.controls import (
    SliderControl,
    SliderConfig,
    CheckboxControl,
    CheckboxConfig,
)
```

Схемы и примеры регистра можно импортировать явно из `slider.schema` / `checkbox.schema`.

## Границы

- **Примитивы** не импортируют `RegistersManager` и `ResolvedMeta`.
- **Схема регистра приложения** (processor, renderer, …) живёт в прототипе / приложении; в `schema/register_example.py` — только учебные заготовки.

Подробнее: `slider/README.md`, `checkbox/README.md`.
