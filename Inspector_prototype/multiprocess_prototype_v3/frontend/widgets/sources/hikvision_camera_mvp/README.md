# HikvisionCameraMvp — виджет камеры Hikvision (MVP)

Параллельная реализация рядом с legacy [`hikvision_widget`](../hikvision_widget/README.md).

## Источник границ параметров

Минимум/максимум/дефолты для **frame rate, exposure, gain** берутся из [`CameraRegisters`](../../../registers/schemas/camera_tab/camera.py) и [`HikvisionParamRow`](../../../registers/schemas/camera_tab/hikvision_param_rows.py) (`build_hikvision_param_rows()`). Дублирования чисел во фронте нет.

## UI-конфиг

[`HikvisionCameraMvpUiConfig`](schemas.py) — группы, кнопки, `touch_keyboard`, ширина line edit. Опционально **`param_display`**: `{ "hikvision_frame_rate": { "placeholder", "format_spec", "label" } }`.

## Слои

| Файл | Роль |
|------|------|
| `view.py` | Qt-разметка, `QLineEdit` parse/apply для fallback |
| `widget.py` | `BaseWidget`, сигналы, презентер |
| `model.py` | Регистры + clamp / диапазон по `HikvisionParamRow` |
| `presenter.py` | `GuiCommandHandler` |

## Входы

- `command_handler` — обязательный `GuiCommandHandler`
- `registers_manager`, `ui`, `webcam_enum_max_index`, `touch_keyboard`

## Реестр схем

`HikvisionCameraMvpUiConfig` зарегистрирован отдельно от legacy `HikvisionUiConfig`.
