# hikvision_camera — архитектурные решения

Решения плана [`camera-device-service`](../../plans/2026-10-18_camera-device-service/plan.md). Номера `Р<n>` —
[`decisions.md`](../../plans/2026-10-18_camera-device-service/decisions.md) плана. Общие решения ядра (набор команд, сеанс,
переименование без алиасов) — [`Services/camera_device/DECISIONS.md`](../camera_device/DECISIONS.md), ADR-CAM-001 и ADR-CAM-004.

## ADR-HIK-001 — Плагин `hikvision` на ядре, команды Р7; `sdk_app` FROZEN, ручной запуск; сервис — оболочка

**Дата:** 2026-11-22
**Статус:** Accepted
**Task context:** Task 4.2a (плагин на ядре), Task 4.2b (чистка старого пути); Р7, Р8; решение владельца 3; ревью F22

### Context
Плагин `hikvision` держал собственный набор команд (`open`, `start_capture`, `get_parameters`, …) и сам запускал `sdk_app`
через `Popen`. Это второй открыватель MVS-камеры (F14) и запуск процесса из GUI-пути (принцип №6). Рядом лежали
`HikvisionCameraService` с ложным статусом `running` при ничего не запущенном захвате (F22) и запись стража R4 на `Popen`/`terminate`
в `plugin.py` (`FROZEN Ф4`). ADR-CAM-004 решил: старые имена команд удаляются без алиасов.

### Alternatives

**A. Оставить старые команды рядом с общим набором (алиасы)**
- Pros: потребители не ломаются.
- Cons: второй контракт без срока жизни; отвергнуто в ADR-CAM-004.

**B. Плагин на ядре: общий набор Р7, `sdk_app` вне приложения, сервис-оболочка** (выбрано)
- Pros: один контракт и один владелец сеанса камеры; в плагине нет `subprocess`.
- Cons: потребители по имени команды переводятся вручную (вкладка GUI, хаб, рецепты — Task 4.3, 4.4, 4.6).

**C. Удалить `sdk_app` вместе с командами**
- Pros: меньше кода.
- Cons: нарушает принцип №3 (FREEZE, не KILL); потеря инструмента диагностики MVS на стенде.

### Decision
Chose B.
- `HikvisionCameraPlugin` наследует `CameraDevicePlugin`; команды — набор Р7: `take_device`, `release_device`, `get_status`,
  `reset_stats`, `read_params`, `apply_params`, `list_devices`, `describe_params`, `trigger_software`. Вендорское — порт `mvs`
  (`driver.make_port`), таблица привязки `driver.BINDINGS`, поля register и приведение кадра к размеру слота SHM.
- Удалены команды `open`, `close`, `start_capture`, `stop_capture`, `enum_devices`, `get_parameters`, `set_parameters`,
  `set_exposure`, `set_gain`, `set_frame_rate`, `set_resolution`, `open_sdk_app`, `close_sdk_app`; тесты этих команд удалены
  вместе с ними.
- `sdk_app` — **FROZEN**, отдельный инструмент диагностики: ручной запуск `python -m Services.hikvision_camera` при остановленном
  стенде (два открывателя одной камеры конфликтуют). Из приложения не запускается. `HikvisionCamera` (`core/camera.py`) FROZEN:
  им пользуется `sdk_app`.
- `HikvisionCameraService` — оболочка (F22): `get_status()` -> `"shell"`, `start()` -> `False` («оболочка, захват — плагин
  `hikvision`»). Захват ведёт плагин.
- Запись стража R4 для `plugin/plugin.py` снята: `Popen`/`terminate` ушли из плагина.

### Consequences
- Architectural changes: один набор команд камеры; `subprocess` в плагине нет (тест `test_в_исходнике_плагина_нет_subprocess`).
- Migration: потребители старых имён — рецепты (4.3), вкладка (4.4), хаб (4.6); откат — `git revert` точки коммита К4'.
- Constraints: алиасов старых имён не добавлять; запуск `sdk_app` из приложения не восстанавливать; `sdk_app` и `core/camera.py`
  не править без решения владельца.
- Known risks: `get_status()` сервиса теперь строка, а `IService.get_status` в аннотации — `dict`; хост (`service_module/host.py`)
  оборачивает не-словарь в `{"status": ...}`, поэтому статус не теряется, но контракт Protocol расходится с реализацией.

### Links
- Related: ADR-CAM-001, ADR-CAM-004; `docs/reviews/2026-10-18_camera-services-unification-review.md` (F14, F22)
