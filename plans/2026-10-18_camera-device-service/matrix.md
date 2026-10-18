# camera-device-service — сводная таблица, советы, связи

Часть плана [`plan.md`](plan.md).

## Задача -> приоритет -> волна -> исполнитель -> стадии -> железо -> gate

Строится из шапок `tasks/<id>.md` (раунд 3). Роли и модели — [`wave-protocol.md`](wave-protocol.md). Gate `--timed medium` — путь в
`scripts/machine_gate_timed.txt` (`multiprocess_framework/`, `Services/device_hub/`), нужно своё окно. Break-injection обязателен только
для механизмов 1.1, 2.1, 2.2, 2.4 (прогнозы лидера, прогон Haiku).

| Task | Priority | Wave | Зависит | Исполнитель | Stage0 | Тестер до кода | Ревью | Камера / стенд | Gate |
|---|---|---|---|---|---|---|---|---|---|
| 0.1 | P0 | W1 | — | `tech-writer` (sonnet): ADR по `decisions.md` + прогон `sentrux check .` | нет | нет | волна W1 (Opus) | нет | light |
| 0.2 | P0 | W1 | — | `developer` (sonnet) | нет | нет | волна W1 (Opus) | нет; на камере — 0.5 | medium (`Services/hikvision_camera/tests`) |
| 0.3 | P0 | W1 | — | `developer` (sonnet) | нет | нет | волна W1 (Opus) | нет (DLL на машине есть: импорт пакета грузит её, F16) | light |
| 1.5 | P0 | W1 | 0.1 | `developer` (sonnet) | reviewer (sonnet) | да | волна W1 (Opus) | нет | light |
| 0.4 | P0 | W1 | 0.3; схема JSON записи — стадия 0 Task 1.5 | `developer` (sonnet) | нет | нет | волна W1 (Opus) | нет (`--fake`); прогон на камере — 0.5 | light |
| 1.1 | P0 | W1 | 0.1 | `developer` (sonnet) | reviewer (sonnet) | да | волна W1 (Opus) | нет | light (свой файл), затем `medium --timed` (`multiprocess_framework/modules/data_schema_module/tests`) |
| 1.6 | P0 | W2 | 1.1, 1.5 | `developer` (sonnet) | нет | нет | волна W2 (Opus) | нет | light |
| 1.8 | P0 | W2 | 1.5 | `developer` (sonnet) | нет | нет | волна W2 (Opus) | стенд без камер | light (тесты); heavy — только стенд, в окне |
| 2.1 | P0 | W2 | 1.5, 1.8 | `developer` (sonnet); 3-я итерация -> `teamlead` (opus) | reviewer (sonnet) | да | Opus сразу + волна W2 | нет | light |
| 2.2 | P0 | W2 | 1.6, 2.1 | `developer` (sonnet); 3-я -> `teamlead` | reviewer (sonnet) | да | Opus сразу + волна W2 | нет; ветку по умолчанию выбирают 6.2/0.5 | light |
| 2.3a | P0 | W3 | 2.2 | `developer` (sonnet) | reviewer (sonnet) | да | волна W3 (Opus) | нет | light |
| 2.3b | P0 | W3 | 2.3a | `developer` (sonnet) | нет | нет | волна W3 (Opus) | нет; живой — 6.1 (`camera_device_demo`) | light |
| 2.4 | P0 | W3 | 2.3b | `developer` (sonnet) после Opus stage 0; 3-я -> `teamlead` (opus) | reviewer (sonnet) | да | Opus сразу + волна W3 | нет; ветка по умолчанию — после 6.2 | medium (`Services/camera_device/tests`) |
| 4.1 | P0 | W3 | 0.3, 1.5 | `developer` (sonnet) | нет | нет | волна W3 (Opus) | нет; запись дерева 0.5 — данные фейка; на камере — 6.3 | light |
| 3.1 | P0 | W3 | 1.5 | `developer` (sonnet) | нет | нет | волна W3 (Opus) | нет; `hardware`-вариант — 6.2 | light |
| 3.2 | P0 | W3 | 2.4, 3.1 | `developer` (sonnet) | нет | нет | волна W3 (Opus) | нет; живой — 6.4 | medium (`Services/code_reader/tests`) |
| 4.2a | P0 | W4 | 0.2, 2.4, 3.2 (снимок каталога), 4.1 | `developer` (sonnet) | reviewer (sonnet) | да | Opus сразу + волна W4 | нет; на камере — 6.3 | medium (`Services/hikvision_camera/tests`) |
| 4.2b | P0 | W4 | 4.2a | `developer` (sonnet) | нет | нет | волна W4 (Opus) | нет | medium (`Services/hikvision_camera/tests`) |
| 4.3 | P0 | W4 | 4.2a | `junior` (haiku) по точному диффу из отчёта 4.2a -> `developer` (sonnet) проверка | нет | нет | волна W4 (Opus) | нет | medium (`multiprocess_prototype/recipes/tests`) |
| 4.4 | P0 | W4 | 4.2a | `developer` (sonnet) | нет | нет | волна W4 (Opus) | GUI unattended — 6.3 | medium (`multiprocess_prototype/frontend/widgets/tabs/services/hikvision/tests`) |
| 6.1 | P0 | W4 | 1.8, 2.3b | `developer` (sonnet) | нет | нет | волна W4 (Opus) | стенд `camera_device_demo` (`driver: fake`) | light (тесты); heavy — только стенд, в окне |
| 0.5 | P0 | W4 | 0.2, 0.4; MVS-камера в сети | лидер (запуск), `junior` (haiku) — сбор чисел, вывод — `reviewer` (opus) | нет | нет | волна W4 (Opus) | **MVS-камера**, стенд с рецептом `hikvision_inspect` | heavy (окно координатора) |
| 6.3 | P0 | W4 | К4' (4.2a, 4.2b, 4.3, 4.4), 6.1, 0.5 | лидер; `junior` (haiku) — числа; вывод — `reviewer` (opus) | нет | нет | волна W4 (Opus) | **MVS-камера** | heavy |
| 3.3 | P0 | W5 | 3.2 | `junior` (haiku) по точному диффу из отчёта 3.2 -> `developer` (sonnet) проверка и прогон | нет | нет | волна W5 (Opus) | нет | medium (`multiprocess_prototype/recipes/tests`) |
| 6.2 | P0 | W5 | камеры ID3013 в сети | лидер (запуск); `junior` (haiku) — числа; вывод — `reviewer` (opus) | нет | нет | волна W5 (Opus) | **ID3013 ×2** | heavy |
| 6.4 | P0 | W5 | 3.3, 6.1, 6.2 | лидер; `junior` (haiku); вывод — `reviewer` (opus) | нет | нет | волна W5 (Opus) | **ID3013 ×2** (+MVS) | heavy |
| 4.6a | P1 | W6 | 2.3b; согласование с T5.3 `robot-protocol-v2` | `reviewer` (sonnet) в роли стадии 0: ADR-DH и уточнение брифов 4.6b/4.6c/4.6d | reviewer (sonnet) | нет | волна W6 (Opus) | нет; опыт перечисления при занятом приборе — в 0.5 (MVS) и 6.2 (ID3013) | light (`python scripts/validate.py`) |
| 4.6b | P1 | W6 | 4.6a; не одновременно с T5.3 | `developer` (sonnet) | нет | нет | волна W6 (Opus) | нет | `medium --timed` (`Services/device_hub/tests`, путь в `scripts/machine_gate_timed.txt`) |
| 5.1 | P1 | W6 | 2.4 | `developer` (sonnet) | нет | нет | волна W6 (Opus) | нет | light |
| 4.6c | P1 | W6 | 4.6b, 4.2a | `developer` (sonnet) | нет | нет | волна W6 (Opus) | стенд `camera_device_demo` (`driver: fake`) + процесс `devices` | medium (`Plugins/hub/device_hub/tests`) |
| 4.6d | P1 | W6 | 4.6c, 5.1 | `developer` (sonnet) | нет | нет | волна W6 (Opus) | нет | medium (`Plugins/hub/device_hub/tests`) |
| 5.2 | P1 | W7 | 5.1 | `developer` (sonnet) | нет | нет | волна W7 (Opus) | фейк `VideoCapture`; `hardware` — любая веб-камера машины | light |
| 5.3 | P1 | W7 | 5.2, 3.1, 4.1 | `developer` (sonnet) | нет | нет | волна W7 (Opus) | стенд без камер (`driver: fake`); веб-камера — по желанию | light (тесты); heavy — только стенд, в окне |
| 1.3 | P1 | W7 | 0.1, 2.3a | `developer` (sonnet) | reviewer (sonnet) | да | волна W7 (Opus) | живой `backend_ctl capabilities` на любом рецепте без камер | `medium --timed` (`multiprocess_framework/modules/process_module/tests`) |
| 1.4 | P1 | W7 | 1.1 | `developer` (sonnet) | нет | нет | волна W7 (Opus) | живой процесс без камер | `medium --timed` (`multiprocess_framework/modules/process_module/tests`) + light (`backend_ctl/tests`, свой файл) |
| 1.2 | P1 | W7 | 1.1 | `developer` (sonnet) | нет | нет | волна W7 (Opus) | нет; живая проверка — 6.3 (GUI unattended) | medium (`multiprocess_prototype/frontend/forms/tests`) |
| 1.7 | P1 | W7 | — | `investigator` (opus) — только диагноз; правка — `developer` (sonnet) | нет | нет | волна W7 (Opus) | стенд без камер | heavy (окно; стенд и `process_manager_module/tests`) |
| 6.5 | P1 | W8 | 6.1, 1.3, 1.4 | лидер (стенд + зонд), вердикт — `reviewer` (opus) | нет | нет | волна W8 (Opus) | стенд `camera_device_demo`; камера не обязательна (с камерой — повтор на 6.3/6.4) | heavy |
| 6.6 | P1 | W8 | все задачи P0 и P1 | `docs-writer` (haiku) по точному списку от лидера | нет | нет | волна W8 (Opus) | нет | light (`python scripts/validate.py`) |
| 3.4 | P2 | W9 | 3.1 | `developer` (sonnet) | нет | нет | волна W9 (Opus) | нет; замер — 6.4 | light |
| 4.5 | P2 | W9 | 2.2, 4.1 | `developer` (sonnet) | нет | нет | волна W9 (Opus) | нет | medium (`Plugins/sources/camera_service/tests`) |
| 5.4 | P2 | W9 | 5.3 | `tech-writer` (sonnet) по оглавлению, которое даёт `reviewer` (opus) | нет | нет | волна W9 (Opus) | нет | light (`python scripts/validate.py`) |

## Советы архитектуры (`camera-device-architecture.md` §3): в плане или отложено

| Совет | Решение |
|---|---|
| 1 метаданные в `introspect.registers` | в плане, 1.4 |
| 2 контракты команд плагина | в плане, 1.3 |
| 3 прибор проверять по `state…params` | в плане: Р13, README 5.4, приёмка 6.3–6.5 |
| 4 `seq_id` без переполнения | в плане для плагинов ядра (2.3a). `camera_service` (`plugin.py:31`), `phone_gateway` (`plugin.py:38`), `capture` (`plugin.py:23`) — **отложено**: не плагины ядра, их счётчик — межисточниковый контракт; строка в `OPEN_QUESTIONS` (6.6) |
| 5 записанный фейк | в плане: запись — 0.4/0.5 (MVS), 6.2 (ID3013, тем же форматом через `mvcr_probe.py`); загрузка — 1.5 |
| 6 сторож потока-владельца | в плане, 2.1 |
| 7 один скрипт стенда | в плане, 6.1 |
| 8 единые часы | частично: `ts` wall в конверте ядра (2.3a). Правка `Plugins/io/database/plugin.py:121` (F21) — **отложено**: межисточниковый потребитель; строка в `OPEN_QUESTIONS` |
| 9 общий контрактный тест с `hardware` | в плане, 1.5 (тест + маркер), 5.3 (по всему реестру) |
| 10 флаг миграции `session: legacy|core` | **отклонено**: решение владельца 3 — без двух путей; откат — `git revert` точки коммита |
| 11 `HikvisionCameraService` -> статус `shell` | в плане, 4.2b (F22) |
| 12 бюджет GigE полями | в плане, 4.1 (поля `packet_size`, `packet_delay`) и 4.2a (register) |
| 13 метрики команд в приёмке | в плане, 6.5 |
| 14 README: схема состояний, таблица «ошибка -> kind» | в плане, 5.4 |
| 15 просмотрщик всего дерева узлов | **отложено**: `describe_params` по управляемым полям есть (2.3a); полное дерево — по просьбе владельца после 6.3 |

## Связи с соседними планами (двусторонние; лидер вносит строки в чужие планы)

| План | Что отдаёт / берёт | Строка, которую лидер добавит туда |
|---|---|---|
| [`code-reader-gui`](../code-reader-gui.md) | отдаёт 2.1 (get/set узлов) и 2.2a (поля режима); берёт форму register'а ядра для своей 2.3 | ниже, «Правка code-reader-gui» |
| [`code-reader-sdk`](../code-reader-sdk.md) | история Ф6 | в шапку: «продолжение — `2026-10-18_camera-device-service/plan.md`» |
| [`lifecycle-stop-ownership`](../lifecycle-stop-ownership.md) (IN PROGRESS) | владеет остановкой детей PM; Task 1.7 этого плана — тот же механизм | «Выход приложения и `INSPECTOR_LOG_DIR` после full-replace — Task 1.7 `2026-10-18_camera-device-service`; стадия 0 1.7 сверяет с Ф1 этого плана» |
| [`dataset-circle-capture`](../dataset-circle-capture.md), [`camera-robot-calibration`](../camera-robot-calibration.md) | их рецепты меняет 4.3 | «рецепт переведён на `hikvision` ядра — Task 4.3 `2026-10-18_camera-device-service`» |
| [`device-tree-recipe`](../device-tree-recipe.md) | `device_hub` перестаёт открывать камеры (4.6a–4.6c); hikvision-секция master-detail Фазы E — после 4.6b на командах `camera_*` | «хаб камерой не владеет, зеркало владельца — ADR-DH, Task 4.6a–4.6c `2026-10-18_camera-device-service`» |
| [`robot-protocol-v2`](../robot-protocol-v2/plan.md) T5.3 [PENDING] | общий писатель `Plugins/hub/device_hub/plugin.py` (таблица `commands`) и `Services/device_hub/manager.py:_register_defaults` (форма фабрики) | «T5.3 и `camera-device-service` 4.6b/4.6c правят одни файлы хаба: один писатель; форма фабрики `factory(entry, proto, *, services)` — Task 4.6a» |
| `plans/queue/ORDER.md` | очередь владельца | строки 23–26 блока `owner-queue` (Task 0.1, 0.2, 0.3, 1.7 — входные без зависимостей), позицию определяет владелец |

**Правка `code-reader-gui` — применена в раунде 2 (2026-10-18):** статусы 2.1, 2.2a — DONE; 2.2b — SUPERSEDED со ссылкой сюда; 2.3 и 3.1 зависят от Task 2.3/3.2 и 6.4 этого плана; шапка `Статус` — IN PROGRESS; `phase-2.md` (46 КБ) разделён: 2.2a и 2.2b перенесены в `plans/code-reader-gui/phase-2-history.md`. Во все соседние планы таблицы выше добавлена строка «2026-10-18, связь с camera-device-service» под заголовком.
