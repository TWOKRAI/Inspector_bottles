# CheckboxControl

Булево поле регистра: подпись + `QCheckBox`. Позиция подписи задаётся в `CheckboxConfig`.

## Файлы

| Файл / папка | Ответственность |
|--------------|-----------------|
| `widget.py` | Класс `CheckboxControl`, подписка на `stateChanged`, вызов `_write_value` |
| `schema/config.py` | `CheckboxConfig`: привязка + `position` (left/right/top/bottom) |
| `schema/register_example.py` | Пример регистра с bool-полем |
| `layout_builder.py` | Сборка `QHBoxLayout` / `QVBoxLayout` и порядок виджетов |
| `common/field_sync.py` | `notify_field_changed` и `send_register_update` у родителя |
| `styles.py` | Размер чекбокса, отступы layout |

## Пример

```python
CheckboxControl(
    config=CheckboxConfig(
        register_name="renderer",
        field_name="show_mask",
        label="Маска",
        position="left",
    ),
    registers_manager=rm,
    parent=tab,
)
```
