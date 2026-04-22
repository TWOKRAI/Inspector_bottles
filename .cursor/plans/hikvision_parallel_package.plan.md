---
name: ""
overview: ""
todos: []
isProject: false
---

# Hikvision MVP: новая папка рядом, старая без изменений

## Решение

- Папку `[Inspector_prototype/multiprocess_prototype/frontend/widgets/hikvision_widget/](Inspector_prototype/multiprocess_prototype/frontend/widgets/hikvision_widget/)` **не трогаем** (текущий BaseWidget + callbacks + старые схемы остаются эталоном/страховкой).
- Рядом создаём **новый пакет** с целевой архитектурой (единая `HikvisionParameterSpec`, презентер + `GuiCommandHandler`, без `callbacks.py`).

**Имя пакета (рабочее):** `hikvision_camera_mvp` (или `hikvision_mvp_widget` — выбрать одно при реализации; в плане ниже — `hikvision_camera_mvp`).

Структура новой папки (аналогично прежнему плану, но изолированно):

- `params_spec.py` — `HikvisionCameraParameterSpec` + `get_default_parameter_specs()`
- `schemas.py` — только UI-конфиг, ссылается на список спецификаций
- `model.py`, `presenter.py`, `widget.py`, `view.py`, `line_params.py` (или хелперы внутри view)
- `README.md` — порты, отличие от legacy `hikvision_widget`
- `__init__.py` — экспорт только нового виджета (например `HikvisionCameraMvpWidget`)

## Подключение к приложению

- В `[camera_tab/widget.py](Inspector_prototype/multiprocess_prototype/frontend/widgets/tabs_setting/camera_tab/widget.py)` на этапе внедрения: **импорт и инстанцирование нового виджета** вместо старого `HikvisionWidget` (одна строка замены класса + аргументы `command_handler`), либо временный флаг в конфиге (`use_hikvision_mvp: bool`), если нужен параллельный A/B.
- `[tab_factory.py](Inspector_prototype/multiprocess_prototype/frontend/windows/main_window/tab_factory.py)` / `[FrontendAppContext.command_handler](Inspector_prototype/multiprocess_prototype/frontend/app_context.py)` — протянуть `command_handler` в `CameraTabWidget` и далее в новый виджет (как в базовом плане).
- `[build_camera_tab_callbacks](Inspector_prototype/multiprocess_prototype/frontend/widgets/tabs_setting/camera_tab/__init__.py)`: убрать hikvision из колбэков **только когда** вкладка переключена на новый виджет; для legacy-ветки старый `build_hikvision_callbacks` может остаться до полного перехода.

## Реестр схем (`@register_schema`)

При **одновременном** импорте старого и нового пакета нельзя регистрировать схемы под **теми же строковыми именами**, что в legacy (`HikvisionUiConfig`, `HikvisionApiMapEntry`, …).

**Обязательно:** в новом пакете использовать **уникальные** имена регистрации, например:

- `HikvisionCameraMvpParameterSpec`
- `HikvisionCameraMvpUiConfig`

Секция `camera_tab` / вложенный конфиг для нового виджета — отдельный ключ или та же вложенная структура с типом, который мержится в `HikvisionCameraMvpUiConfig` (уточнить при реализации: либо поле `hikvision` в `[CameraTabUiConfig](Inspector_prototype/multiprocess_prototype/frontend/widgets/tabs_setting/camera_tab/schemas.py)` меняет тип только когда весь таб на MVP, либо добавить `hikvision_mvp: HikvisionCameraMvpUiConfig | None`).

## Документация и вывод из эксплуатации legacy

- В README нового пакета: «legacy: `hikvision_widget`».
- В README старого пакета (одна правка при желании): пометка **deprecated / заменён на `hikvision_camera_mvp`** — только когда переключите вкладку по умолчанию.
- `[FRONTEND_MAP.md](Inspector_prototype/multiprocess_prototype/docs/FRONTEND_MAP.md)`: две строки до удаления старого.

## Этапы (todo)

1. Создать `hikvision_camera_mvp/` с полным кодом по целевому MVP (с уникальными `register_schema` именами).
2. Протянуть `command_handler` в `CameraTabWidget` + фабрику вкладок.
3. Переключить стек камеры на новый виджет (или флаг в конфиге).
4. Ручные тесты по чеклисту из базового плана.
5. После стабилизации — опционально удалить legacy-папку отдельным PR (не входит в первый шаг).

## Связь с предыдущим планом

Логика слоёв (model / presenter / view / specs) — без изменений; меняется только **место правок** (новая директория + уникальные имена схем + точечное переключение импорта во вкладке камеры).