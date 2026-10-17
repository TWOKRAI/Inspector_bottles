# Передача: две камеры-считывателя, фикс дисплея, зонд GenICam (2026-10-16, до обеда)

Сессия `inspector-bottles-c5`. Ветка `feat/code-reader-gui`, HEAD `0148b5ad8`, 5 коммитов поверх `46d594bad`. Не запушено, не влито в `main` (нужен оформленный `/code-review`, потом `merge:`-коммит).

## Состояние сейчас

- Стенд ОСТАНОВЛЕН (порт 8765 свободен), IDMVS закрыт, камеры свободны.
- Обе камеры: `TriggerMode=1 (On)`, `TriggerSource=0 (Line0)`, `TriggerSelfTriggerPeriod=300` — ждут аппаратный триггер, не снимают. Исходное камеры 1 было свободный режим (`TriggerMode=0`, `RunningMode=2`); сохранённые исходные значения — в `cam_orig.json` (scratchpad, ниже): камера 1 `{mode 0, source 0, period 300}`, камера 2 `{mode 1, source 0, period 300}`.
- Не закоммичено мной: `docs/claude/memory/project_code_reader_selftrigger_period_sets_the_fps.md` (новый), пересобранные `BY-MODULE-{mechanism,services}.md`, `BY-MODULE.md`, этот файл.
- Не моё, не трогать: `README.md`, `multiprocess_prototype/app.yaml`, `multiprocess_prototype/recipes/letter_robot_sim.yaml`, `docs/handoffs/2026-10-14_coordinator.md`.
- Распоряжения владельца на сегодня: агенты только Sonnet/Haiku; стенд без окна координатора разрешён владельцем (координатор `inspector-bottles-d1` не жив, `machine.lock` вчерашний).

## Что сделано (коммиты)

1. `9be8cc425` фикс `DisplaySlot` (хранит исходный pixmap; ресайз не портит кадр) + 12 тестов. На живом стенде владелец сказал «работает».
2. `e708e14f6` SDK-слой get/set узлов GenICam + зонд `mvcr_probe.py` (`--params`, `--set УЗЕЛ=ТИП:ЗНАЧЕНИЕ`, `--ip`, `--node`), 324 теста, возврат значений в `finally`.
3. `df54d64db` рецепт `qr_reader_sdk_dual_demo` (два считывателя, дисплеи `main` и `second`).
4. `a4921a03d` спека Task 2.1 после ревью + итоги стенда в `plans/code-reader-gui/phase-2.md`.
5. `0148b5ad8` уроки в память.

## Что выяснено на железе

- Камера 1 `192.168.1.10` (WBPF-5M-OD), камера 2 `192.168.1.11` (SENSOTEC). Порт ПК 1 Гбит/с.
- Типы узлов: `ExposureTime`/`Gain` — float; `TriggerMode`/`RunningMode`/`TriggerSource` — enum; `LightBrightness` — int (доступ закрыт); `LightingEnable` — bool (True); `AmingLightEnable` — enum (1); `FocusScore` — int (0, читается); узлы управления фокусом закрыты/нет → объектив, скорее всего, ручной, фокус сбился механически (гипотеза).
- «3 кадра/с» = период собственного триггера 300 мс. `TriggerSource=SelfTrigger` (значение 9, ставится по имени `set_enum_str`) + `TriggerSelfTriggerPeriod` (мин 32 мс). С 32 мс: камера 2 — 25 кадров/с, камера 1 — 4,7–4,9 (при том же периоде и без кодов в кадре). Канал 100 Мбит НЕ причина (поток 33 Мбит/с).
- Зависимые узлы: `TriggerSource` закрыт при `TriggerMode=0`, период закрыт, пока источник не `SelfTrigger`. Писать родитель → зависимый, откат в обратном порядке.
- Расфокус камеры 1 выглядел как «потеря режима триггера» (кадры без кодов); отличать по сохранённому кадру (`--out`).

## Открыто (по приоритету)

1. Почему камера 1 при том же периоде медленнее камеры 2 (~5 против 25 кадров/с). Следующий шаг — прочитать `--node` ~30 узлов на обеих камерах и сравнить (экспозиция, подсветка, авто-режимы, `OD`-модуль у WBPF).
2. Нужен ли владельцу режим собственного триггера в рецепте (Task 2.2: поля `trigger_mode`/`trigger_source`/период; запись до `StartGrabbing`, порядок родитель → зависимый; план `phase-2.md` надо дополнить: источник и период, а `RunningMode` не нужен). Решение владельца.
3. Подсветка: проверить запись `AmingLightEnable` (5 с, возврат) и `LightingEnable`; `LightBrightness` закрыт.
4. Узел `FocusScore` как подсказка при наводке фокуса — отдельная идея.
5. Документы: `Services/code_reader/docs/SETUP_GEV_V4.0.2.R.md` §9 говорит запуск `run.py`, окно даёт только `multiprocess_prototype/frontend/run.py <рецепт>`; в шапке рецепта `qr_reader_sdk_dual_demo.yaml` комментарий про `position.x` ошибочен (дисплеи встроены в главное окно); статусы Task 2.1 в шапке `plans/code-reader-gui.md` не обновлены.
6. Ревью/слияние ветки в `main`: только через `/code-review` (запускает владелец) и `merge:`-коммит с `Why:`/`Layer:`/`Refs:`.

## Агенты (адрес = agentId; хранить таблицу)

| Роль | agentId | Заметка |
|---|---|---|
| developer 2.1a–e (SDK, зонд, `--ip`, `--node`) | `ab350449e3909bd7f` | держит контекст зонда, можно дозвать `SendMessage` |
| reviewer 2.1 (раунды 1–2) | `a93ffbd3ee523aed6` | APPROVED |
| reviewer стадия 0 (спека 2.1) | `abfa8a7001b1f0e78` | один раз |
| tester 2.1 (слепой) | `a584c4d62d62083c0` | свежим не звать повторно на тот же механизм |
| tester ресайза | `aa0d96a9ca0286231` | |
| developer ресайза | `ac9f98204fcf9a105` | |
| reviewer ресайза | `a2cb23c736850c086` | APPROVED |
| investigator ресайза | `abceb3fdef77553f4` | |

## Инструменты и скрипты (scratchpad `C:\Users\INNOTECH\AppData\Local\Temp\claude\d--PROJECT-INNOTECH-Inspector-vision-Inspector-bottles\502f726c-e456-4ffa-b1dc-c2b17eec0068\scratchpad\`)

- `cam_cfg.py selftrigger|period|show|revert <ip> [N]` — одноразовая настройка самотриггера; `cam_orig.json` — исходные значения. Стенд и IDMVS перед записью закрыты.
- `sample_reader.py`, `fps_two.py` — счётчики читателей через `BackendDriver` (порт 8765); `inject_slot.py`, `inject_sdk.py`, `inject_probe.py`, `inject_probe2.py` — матрицы инъекций (в Python-подпроцессах `bash` звать по пути Git Bash, иначе уходит в WSL).
- Запуск стенда с окном: `BACKEND_CTL=1 INSPECTOR_GUI_UNATTENDED=1 INSPECTOR_LOG_DIR=logs_live/<прогон> .venv/Scripts/python.exe -X faulthandler multiprocess_prototype/frontend/run.py qr_reader_sdk_dual_demo`; остановка по PID (`taskkill /PID <корень> /T /F`), после остановки прибор отпускается ~10 с.

## Правила, не забыть

Ответы владельцу по-русски, коротко; тесты через `machine_gate.sh`; в коммитах `Refs: plans/code-reader-gui.md` обязателен (хук); трейлеры одним абзацем; никогда `git add -A`; живая запись в прибор — только при остановленном стенде и с сохранением исходных значений до записи.
