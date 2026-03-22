# SliderControl

Числовой параметр: подпись, поле ввода, горизонтальный слайдер. Значение читается и пишется через `BaseConfigurableWidget` → `RegistersManager`.

## Файлы

| Файл / папка | Ответственность |
|--------------|-----------------|
| `widget.py` | Класс `SliderControl`: жизненный цикл Qt, вызов базы, сборка UI из примитивов |
| `schema/config.py` | `SliderConfig` (Pydantic): привязка + опции UI |
| `schema/register_example.py` | Пример регистра для копирования в приложение |
| `value_mapping.py` | Пересчёт позиции слайдера ↔ значение поля (`transfer_k`, `round_k`) |
| `legacy_sync.py` | Обновление ui_elements/controls при сборке UI (legacy) |
| `common/field_sync.py` | После записи: `notify_field_changed`, `ui_elements`/`controls`, callback, `send_register_update` |
| `styles.py` | QSS ручки слайдера, отступы |

## Поведение сигналов

- Движение слайдера сразу обновляет текст в поле; запись в регистр **откладывается** (debounce, см. `primitives/value_bridge.py`).
- Завершение редактирования поля — немедленная валидация и запись.

## Пример

```python
SliderControl(
    config=SliderConfig(
        register_name="processor",
        field_name="min_area",
        label="Мин. площадь",
    ),
    registers_manager=rm,
    parent=tab,
)
```
