# Services — STATUS.md

Прикладной слой между framework и `multiprocess_prototype/`. Сервисы — реализации, специфичные для приложения «Inspector_bottles», но переиспользуемые между его процессами. Источник истины по конкретному сервису — `Services/{name}/STATUS.md`.

**Слои:** `multiprocess_framework → Services → Plugins → multiprocess_prototype`.

**Обновлено:** 2026-06-13 — добавлен `ml_train` (обучение и выбор моделей: MobileNetV3/V4 + timm,
3 источника данных, ONNX-экспорт в формат ml_inference).
Ранее 2026-06-12 — добавлен `dataset_gen` (генерация синтетических датасетов cut-and-paste,
пресет «русские буквы на дисках»).
Ранее 2026-06-07 — удалён `webcam_camera` (унификация камеры: единственный владелец cv2 —
плагин `Plugins/sources/camera_service`; настройки — через Pipeline-инспектор и Services «Камера» фасад;
sandbox-снимок переведён на `webcam_controls.capture_single_frame`).
Ранее 2026-05-27 — добавлен `webcam_camera` (Phase 0/3, ADR-128).
Ранее 2026-05-10 — приведение к стандарту валидации (`__init__.py`, `interfaces.py`, `STATUS.md`, `README.md`, `tests/`).

| Сервис | Готовность | Комментарий | ADR |
|--------|-----------|-------------|-----|
| `sql` | production | SQLManager + Repository + UoW + QuerySet; выехал из `multiprocess_framework/modules/sql_module/` | ADR-121 |
| `hikvision_camera` | production | Плагин-обёртка над HikSDK + core/sdk_app; выехал из плагинов | ADR-122 |
| `modbus` | ready | Универсальный драйвер Modbus-TCP / RS485 (pymodbus 3.x); 3 слоя sdk/core/plugin + service; атомарные `transaction`, `RegisterTransport`, декларативная `RegisterMap` — фундамент сервисов устройств | — |
| `device_hub` | ready | Реестр устройств + DeviceManager + 4 драйвера (robot/vfd/hikvision/generic_modbus); always-on процесс `devices`, GUI-вкладки, YAML-протоколы | ADR-DH-001..005 |
| `robot_comm` | ready | Робот Delta (CVT pick-place + рисование) поверх modbus; карта universal3, мост `RegisterTransport` для ПЧ, sim_robot + FakeRobotTransport; владелец соединения — процесс devices | ADR-RC-001..005 |
| `vfd_comm` | ready | ПЧ INVT GD20, транспорт-агностик (`RegisterTransport`): сегодня мост через робота (mailbox+пульс poll), закладка DIRECT_MAP под прямой RTU; robot_comm НЕ импортирует | ADR-VC-001..003 |
| `auth` | foundation | User/Role storage + RBAC API (PR1) | ADR-Auth-001..004 |
| `Operation_crop` | utility | Утилита для нарезки кадров | — |
| `Region_processors` | utility | Регион-процессоры (заготовки для пайплайнов) | — |
| `ml_inference` | foundation | Инференс НС (кадр→классы): data-driven sidecar + pluggable backend (ONNX осн., torch опц.); processing-плагин `ml_inference` + widget `model_picker` | — |
| `dataset_gen` | ready | Универсальный генератор синтетического датасета (cut-and-paste): классификация + угол поворота, авто-детектор симметрии (none/180/full), экспорт на диск / torch Dataset на лету; пресет «русские буквы на дисках» | — |
| `ml_train` | ready | Универсальное обучение и выбор моделей: MobileNetV3 (torchvision) / MobileNetV4 + `timm/<имя>` (timm), классы + угол; AMP/EMA/mixup/warmup+cosine; RunRegistry; ONNX-экспорт + sidecar → ml_inference | — |

## Правила слоя

1. Сервис **не импортирует** `multiprocess_prototype.*` (enforced через `.sentrux/rules.toml`).
2. У каждого сервиса: `__init__.py` с публичным API, `interfaces.py` с Protocol-контрактами, `STATUS.md`, `README.md`, `tests/`.
3. Зависимости — только `multiprocess_framework.*` и сторонние библиотеки (SQLAlchemy, HikSDK и т.п.).
4. Plugins используют сервисы через их публичный API; framework — нет.

## Связанные документы

- [`multiprocess_framework/DECISIONS.md`](../multiprocess_framework/DECISIONS.md) — ADR-121 (carve-out sql), ADR-122 (carve-out hikvision)
- [`.sentrux/rules.toml`](../.sentrux/rules.toml) — boundaries
- [`CLAUDE.md`](../CLAUDE.md) — корневой контекст проекта
