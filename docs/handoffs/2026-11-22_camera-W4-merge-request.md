# Заявка на слияние К4' — камера на ядре `camera_device` (полоса К, W4)

Автор: лид полосы К, сессия `inspector-bottles-fd`, 2026-11-22. Ветка `feat/camera-w4` (дерево `Inspector_bottles--lane-K-w4`), база `main` `d221d9a9c` (в нём Р2 `95d496376`, RN1, PS1). Резервная ветка промежуточных коммитов — `feat/camera-w4-wip` (не сливать).

## Что входит (3 коммита поверх `d221d9a9c`)

| SHA | Что |
|---|---|
| `7731c5987`, `3b864c589` | `docs(plans)`: тексты 4.2a (по раундам 1–2 стадии 0), 4.2c, правки 4.2b/4.3, отчёты стадии 0 и сверка чек-листа дня №1 |
| `a4e1b325d` | **К4' одним коммитом** (4.2a + 4.2b + 4.2c + 4.3 + 4.4 + хвосты): плагин `hikvision` на `camera_device`, цвет BGR и дебайер в ядре, рецепты (4 + `hikvision_dual`), golden β, вкладка GUI, ADR-CAM-006, ADR-HIK-001; trailers `Decision:`, `Layer: mixed` |

Старый путь `Services.hikvision_camera` (13 команд, `sdk_app`-Popen, `FrameConverter` в плагине) в `main` исчезает; день №1 закреплён на `../Inspector_bottles--day1` (`d221d9a9c`) по слову координатора.

## Проверено (радиус после rebase, gate `medium`, `inspector-bottles-fd`)

| Набор | Результат |
|---|---|
| `Services/hikvision_camera/tests` | 314 passed, 15 skipped |
| `Services/camera_device/tests` | 462 passed, 10 skipped |
| `multiprocess_prototype/recipes/tests` | 257 passed, 5 skipped |
| вкладка `services/hikvision/tests` | 12 passed |
| `backend/tests/test_build_characterization.py` (golden β) | 4 passed |
| `scripts/lifecycle_guards/tests/test_lifecycle_static.py` | 25 passed |
| `frontend/forms/tests` | 107 passed, 1 failed — **красный и на `main`** (C-108, поля `robot_io` Р2; в `plans/queue/defects.md`) |
| `scripts/validate.py` | exit 0, ошибок и предупреждений нет |
| `sentrux check .` | 1 нарушение `no_god_files`: `test_recipe_1_0.py` (C-107, есть на `main`) и **новый** `Services/hikvision_camera/tests/test_plugin_on_core.py` (fan-out 18 при пороге 15, не блокер по ревью) |
| `lifecycle_guards/tests` целиком | 8 красных probe-тестов — красные и на `main` (не наши); 4 наших красных (3 литерала allowlist 72→71 и guard «tables.py не тронут» в `camera_device`) исправлены в К4' |

Конвейер: стадия 0 (2 раунда, закрыта правками N1–N4 **без раунда 3**, лимит 2 итерации) → слепой `tester` один раз (65 тестов, 61 красный до кода) → `developer` → матрица инъекций 14 мутаций (12 предсказаний совпали, M5/M9 разобраны, M14 — дыра `cv2.error`, закрыта hazard-тестами) → Opus-ревью ветки: раунд 1 CHANGES REQUESTED (B1 `color_convert` в β, M1 то же в calibration/dataset, M2 `TriggerMode=Off`), раунд 2 **APPROVED** на `f004f14d0` (после rebase содержимое то же).

## Конфликты и сращивание при слиянии

- `docs/claude/OPEN_QUESTIONS.md`: запись «полоса К · камера W4, К4'» — конец файла; конфликты с чужими записями разрешены при rebase (обе стороны сохранены).
- `test_letter_robot_sim_diff.py`: в `_EXPECTED_DIFFS` у меня 2 записи про `color_convert` (сим его оставил — чужой файл), у Р2 — 2 записи про `max_reconnect_attempts`; сращены, тест зелёный.
- `catalog_register_fields.txt`: +29 строк (`camera_device.exposure_auto`, `hikvision.*`); строки `robot_io.*` добавит владелец `robot_io` (C-108).
- Golden β перегенерирован до rebase; после rebase `test_build_characterization` зелёный без перегенерации, дифф golden — только узел `color_convert`, его провод и `trigger_*` камеры.

## Что НЕ проверено (железа и стенда нет)

- Порядок каналов реального прибора (BayerRG8 по дампу 0.5; проба cv2 на синтетике), `GainAuto`, `TriggerMode` прибора, `GevSCPSPacketSize`, время перезахвата при правке `gain`/`exposure_time` — список «на железе» в `docs/claude/OPEN_QUESTIONS.md`, запись «полоса К · камера W4, К4'», и в вердикте Opus-ревью (отчёт `docs/reports/2026-11-22_camera-device-service_W4.md`).
- **Живой стенд не гонялся** (MVS SDK на Mac нет; рецепты β без железа не поднимаются headless). Слияние без стенда — решение координатора: нужен ли стенд на `driver: fake` (`camera_device_demo.yaml`) до слияния — скажите, запущу `scripts/stand_gate` по Mac-правилу.
- Вкладка GUI не запускалась вживую (qt-mcp не подключился), только тесты offscreen и спай моста.

## Ждёт решения владельца

- `mono8`: «всегда BGR» (`GRAY2BGR` в вендорском `_build_item`) против записи 2026-11-20 «gray для `mono8`».
- Принятые риски N2 (`GainAuto=Off` не пишется), N3 («оптимальный» пакет, `packet_managed=false`), `letter_robot_sim.yaml` и его `color_convert` (8б), C-106 (мост сеанса на `get_std_logger`) — записаны в OPEN_QUESTIONS.

## После слияния (R4, К, три коммита по порядку)

1. β: `max_reconnect_attempts: 0` у `robot_main` и `vfd_belt` (дифф Р2 `2026-11-20_R2-recipe-diff-reconnect.md`) + голый остаток камеры на `camera_device` (если нужен) и снятие двух записей в `_EXPECTED_DIFFS`; golden пересобрать.
2. `use_linear: false` + `first_y: -440` (комментарий в рецепте: без калибровки F7 `cam0.yaml` β даёт отказ или нули — ожидаемо).
3. Драйвер робота `delta_universal3` → `delta_v2` — последним и отдельно; ключ `readiness` в узле камеры (2.2c) — при R4.
