# camera_tab — Вкладка управления камерой

Контейнер с переключателем типа камеры (Simulator / Webcam / Hikvision) и тремя самодостаточными виджетами.

Пакет: `widgets/tabs_setting/camera_tab/`.

## Архитектура

```
camera_tab/           — контейнер: ComboBox + QStackedWidget
├── widget.py         — CameraTabWidget
├── schemas.py        — CameraTabUiConfig (список типов)
├── register_ops.py   — set_camera_type_field, persist_camera_type
└── build_camera_tab_callbacks(cmd) → callbacks_map

camera_common/        — SimWebcamWidget + FPS + схема (Simulator/Webcam)
hikvision_widget/     — рядом с tabs_setting
```

## callbacks_map

Launcher вызывает `build_camera_tab_callbacks(cmd)` и передаёт в tab_factory:

```python
{
    "simulator": SimWebcamWidgetCallbacks(...),  # тот же объект, что и webcam
    "webcam": ...,
    "hikvision": HikvisionWidgetCallbacks(on_enum_devices=..., on_open=..., ...),
    "on_camera_type_changed": cmd.send_camera_type_changed,  # при отсутствии rm
}
```

## MVC в каждом виджете

- **View** — Protocol + реализация в widget.py
- **Presenter** — логика без Qt
- **Binder** — привязки UI ↔ callbacks, presenter
