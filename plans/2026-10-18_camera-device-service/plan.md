# Plan: общий сервис камер — ядро `Services/camera_device` + драйверы MvCodeReader, MVS, OpenCV; `device_hub` — зеркало

- **Slug:** camera-device-service
- **Дата:** 2026-10-18
- **Статус:** DRAFT
- **Plan review:** CHANGES 1 (`docs/reviews/2026-10-18_camera-plan-review.md`; правки раунда 3 внесены, ждёт раунд 2 ревью)
- **Ветка:** `feat/camera-device-service` — создаёт лидер ДО `docs(plans):` коммита плана.

## Что где живёт

| Что | Где |
|---|---|
| Контракт: цели, задачи одной строкой, волны, бюджет | этот файл |
| Тело задачи (TASK/ROLE/CHAIN/DESIGN/FILES/REDS/ACCEPTANCE/TESTS/OUT OF SCOPE) | `tasks/<id>.md` |
| Протокол волн: роли, модели, цикл, эскалация, метрики пилота, состав волн | [`wave-protocol.md`](wave-protocol.md) |
| Решения Р1–Р14, слои, ADR | [`decisions.md`](decisions.md) |
| Точки коммита, порядок с T5.3, дефекты хаба, риски, открытое | [`design.md`](design.md) |
| Сводная таблица задач, советы 1–15, связи с соседями | [`matrix.md`](matrix.md) |
| Изменения после approve | [`amendments.md`](amendments.md) |

## Контекст

Камеры обслуживают два несвязанных пакета, у MVS-камеры четыре открывателя без владельца (F14). План вводит ядро
`Services/camera_device/` (порт, сеанс с потоком-владельцем, профили run/rest с проверкой чтением, база плагина,
общий набор команд, наблюдаемость средствами framework), переводит на него оба вендорских сервиса и потребителей,
делает `device_hub` зеркалом владельца (P1), а OpenCV-драйвер доказывает универсальность (P1). Заменяет Task 2.2b
[`code-reader-gui`](../code-reader-gui.md). Входы: ревью `docs/reviews/2026-10-18_camera-services-unification-review.md`,
`docs/design/camera-device-architecture.md`, `docs/design/camera-device-service.md`, `docs/handoffs/2026-10-17_camera-service-handoff.md`,
`docs/reviews/2026-10-18_device-hub-camera-integration.md`, ревью плана `docs/reviews/2026-10-18_camera-plan-review.md`.

## Цели (вехи)

- **М1** (день приезда MVS, ~2026-10-20): старый `hikvision` с 0.2 даёт цветной кадр, параметры рецепта после `open`, коды отказа видны; дерево узлов записано (0.5).
- **М2** (MVS на ядре, 6.3): все вызовы SDK — из потока-владельца (2.1), run пишется полностью, запись подтверждается чтением (2.2), выбор по serial, поля управляются через `backend_ctl` (`set_register_verified` + `await_condition …params.<поле>`), `health` при `busy`.
- **М3** (несколько камер): 2 MVS по serial (`hikvision_dual.yaml`, 6.3), 2 ID3013 5 мин `fps_min ≥ 24`, `dropped == 0` (6.4).
- **P1:** хаб не открывает камеру, `connect() == is_connected` (4.6b); три драйвера + фейк проходят один контрактный тест (5.3); `backend_ctl` видит форму команд и диапазоны (1.3, 1.4).

## Out of scope

- Перевод всего `camera_service` на ядро (только бэкенд `hikvision`, 4.5, P2); `seq_id`/часы других источников (советы 4, 8 — `OPEN_QUESTIONS`).
- ONVIF/PTZ, `UserSetSave`, просмотрщик всего дерева узлов, страница камеры в GUI хаба; хаб как источник настроек (открытый вопрос, `design.md`).

## Решения владельца (2026-10-18, окончательные)

1. Ядро `Services/camera_device/` + два вендорских сервиса.
2. Fix-forward: `FieldMeta.apply` (`"live"|"restart"|"config"`), `FieldMeta.enabled_if`; фабрика форм их учитывает.
3. Старое API `hikvision` без алиасов, все потребители — в этом плане; FREEZE — только для путей без живого вызывающего (Р8, Р14).
4. Риск «убийство оставляет камеру в профиле run» принят; T14 — Task 1.7.
5. Дизайн универсальный (веб-камера, IP-камера): Р2, Р3, Ф5. `device_hub` — зеркало (4.6a–4.6d, P1).
6. Раунд 3: приняты B1–B8, A1–A17, перевязки R-a..R-g, приоритеты P0/P1/P2; Q1 — К4' без хаба; Q2 — цель P0 = 2 MVS по serial; режим исполнения — волны (ниже).

## Решено лидером по умолчанию (2026-10-18)

1. `sdk_app` — FROZEN диагностический инструмент, ручной запуск при остановленном стенде; запуск из плагина и вкладки удаляется (Р9).
2. `camera_id` не переименовывается; добавляется `device_id: str` (Р10).
3. Кнопки take/release во вкладке — не нарушение принципа №6, остаются.
4. `hik_release` хаба — no-op `ok` (живой вызывающий `Plugins/sources/camera_service/plugin.py:262`); остальные `hik_*` — отказ с текстом (Р8).

## Режим исполнения — волны (решение владельца 2026-10-18, только для этого плана)

Отступление от `.claude/CLAUDE.md` «Task launch convention» (ревью после каждой задачи, стадия 0 Opus): причина — скорость и
стоимость; волна W1 — пилот. Полный протокол — [`wave-protocol.md`](wave-protocol.md).
- Код и тесты — Sonnet (`developer`, `tester`); Haiku — матрица инъекций по прогнозам лидера, инвентаризации, дифф, числа стенда.
- Стадия 0 — `reviewer` (sonnet), только у 9 задач с контрактом или потоками: 1.1, 1.3, 1.5, 2.1, 2.2, 2.3a, 2.4, 4.2a, 4.6a.
- Слепой `tester` до кода — у 8 механизмных: 1.1, 1.3, 1.5, 2.1, 2.2, 2.3a, 2.4, 4.2a; остальным тесты пишет исполнитель по ACCEPTANCE.
- Ревью: один Opus `reviewer` на волну (общий diff, воспроизведение вход -> выход); Opus сразу после 2.1, 2.2, 2.4, 4.2a и любой задачи, где стадия 0 нашла блокер; раунд 2 волны — тот же агент через `SendMessage` по agentId.
- Break-injection — только механизмы: поток-владелец (2.1), проверка чтением и run/rest (2.2), subscribe (2.4), FieldMeta (1.1).
- Лестница: Sonnet -> (Sonnet стадия 0) -> Opus (лидер / ревьюер волны) -> `cto` (Fable) -> владелец. Opus не закрыл задачу или спор за 2 итерации — на 3-й зовётся `cto` (только вердикт, с фиксированным SHA).
- Метрики пилота: токены на волну, дефекты от ревью волны, дефекты, всплывшие позже, переделки, вызовы `cto` и причины.

## Бюджет

Оценка, не замер. 42 задачи: ~33 запуска исполнителей (Sonnet), 9 стадий 0 (Sonnet), 8 слепых тестеров (Sonnet), ~20 запусков
Haiku, Opus — 9 ревью волн + 4 сразу + раунды 2 через `SendMessage` (~18 запусков Opus) ≈ **~9M токенов агентов** без сессии
лидера. Пилот W1 меряет фактическое; пересчёт — записью в `amendments.md` после W1. Жёсткий порог — 14M: стоп и пересмотр с владельцем.

## Порядок выполнения

### W1 — пилот, без камер (до возврата MVS ~2026-10-20)
- Task 0.1: P0 · ADR-CAM-001…004 + `sentrux check .` [PENDING]
- Task 0.2: P0 · (T12) живой путь `hikvision`: F4, F10, F3 [PENDING]
- Task 0.3: P0 · (T9a) привязки MVS + опись экспортов DLL [PENDING]
- Task 1.5: P0 · ядро: `interface.py`, README, честный фейк, контрактный тест порта [PENDING] (после 0.1)
- Task 0.4: P0 · зонд MVS: дерево узлов в JSON, опыты H1/H2/H5 [PENDING] (после 0.3; схема — стадия 0 1.5)
- Task 1.1: P0 · `FieldMeta.apply` и `enabled_if` [PENDING] (после 0.1)

### W2 — ядро
- Task 1.6: P0 · `params.py`: план записи [PENDING] (после 1.1, 1.5)
- Task 1.8: P0 · **[VERTICAL SLICE]** рецепт `driver: fake` -> item -> дисплей -> `backend_ctl` [PENDING] (после 1.5)
- Task 2.1: P0 · (T4) сеанс: поток-владелец, очередь, `DeviceSdk`, сторож [PENDING] (после 1.5, 1.8)
- Task 2.2: P0 · (T5) run/rest, проверка чтением, обе ветки H1 [PENDING] (после 1.6, 2.1)

### W3 — база плагина, живая правка, второй вендор
- Task 2.3a: P0 · база: register, команды Р7, конверт item [PENDING] (после 2.2)
- Task 2.3b: P0 · база: метрики, события, `health`, `flight_dump` [PENDING] (после 2.3a)
- Task 2.4: P0 · (T8) живая правка через `subscribe` [PENDING] (после 2.3b)
- Task 4.1: P0 · (T9b) драйвер `mvs` [PENDING] (после 0.3, 1.5)
- Task 3.1: P0 · (T7a) драйвер `mvcr` [PENDING] (после 1.5)
- Task 3.2: P0 · (T7b) `code_reader_sdk` на ядре [PENDING] (после 2.4, 3.1)

### W4 — MVS вернулись: К4' = 4.2a + 4.2b + 4.3 + 4.4 одним коммитом
- Task 4.2a: P0 · (T10a) `hikvision` на ядре: register, команды, F12 [PENDING] (после 0.2, 2.4, 3.2, 4.1)
- Task 4.2b: P0 · чистка старого пути, F22, ADR-HIK-001 [PENDING] (после 4.2a)
- Task 4.3: P0 · (T10b) рецепты MVS + `hikvision_dual.yaml` [PENDING] (после 4.2a)
- Task 4.4: P0 · (T10c) вкладка GUI на команды плагина [PENDING] (после 4.2a)
- Task 6.1: P0 · скрипт стенда через `backend_ctl` [PENDING] (после 1.8, 2.3b)
- Task 0.5: P0 · ⚑ стенд MVS на старом пути (М1) — в день, когда MVS в сети [PENDING] (после 0.2, 0.4)
- Task 6.3: P0 · ⚑ MVS на ядре (М2), 2 MVS по serial (М3) [PENDING] (после 4.2a, 4.2b, 4.3, 4.4, 6.1, 0.5)

### W5 — P0-хвост ID3013
- Task 3.3: P0 · (T17) рецепты `qr_reader_sdk_*`, ADR-CR-011 [PENDING] (после 3.2)
- Task 6.2: P0 · ⚑ (T15) опыты H1–H6 на ID3013 [PENDING] (когда считыватели в сети)
- Task 6.4: P0 · ⚑ (T16) стенд N=2 ID3013, 5 мин (М3) [PENDING] (после 3.3, 6.1, 6.2)

### W6 — P1: хаб-зеркало и реестр
- Task 4.6a: P1 · контракт зеркала (стадия 0, без кода) [PENDING] (после 2.3b; T5.3)
- Task 4.6b: P1 · `CameraMirrorDriver`, kind `camera`, инвариант `connect()` [PENDING] (после 4.6a)
- Task 5.1: P1 · реестр драйверов + общий `CameraDevicePlugin` с `driver:` [PENDING] (после 2.4)
- Task 4.6c: P1 · хаб: подписка, индекс, `camera_owner` [PENDING] (после 4.6b, 4.2a)
- Task 4.6d: P1 · хаб: `camera_list_devices`, `hik_*` [PENDING] (после 4.6c, 5.1)

### W7 — P1: универсальность и framework
- Task 5.2: P1 · драйвер `opencv` [PENDING] (после 5.1)
- Task 5.3: P1 · контрактный тест по реестру + `cam_webcam` [PENDING] (после 5.2, 3.1, 4.1)
- Task 1.3: P1 · (T6a) контракты команд плагина [PENDING] (после 0.1, 2.3a)
- Task 1.4: P1 · (T6a) `introspect.registers` с `meta` [PENDING] (после 1.1)
- Task 1.2: P1 · фабрика форм: `enabled_if`, `apply` [PENDING] (после 1.1)
- Task 1.7: P1 · (T14) `shutdown()` детей до `kill_tree`; `INSPECTOR_LOG_DIR` [PENDING]

### W8 — P1: приёмка и закрытие
- Task 6.5: P1 · приёмка наблюдаемости [PENDING] (после 6.1, 1.3, 1.4)
- Task 6.6: P1 · документы, статусы, `OPEN_QUESTIONS` [PENDING] (последней)

### W9 — P2
- Task 3.4: P2 · (T13) копии кадра, замер `get_frame_ms` [PENDING] (после 3.1)
- Task 4.5: P2 · бэкенд `camera_service` `hikvision` на ядре [PENDING] (после 2.2, 4.1)
- Task 5.4: P2 · README ядра: «как добавить вендора» [PENDING] (после 5.3)

## Открытые вопросы

- [ ] H1–H6 (камер нет) — 0.5, 6.2; `MV_CC_Initialize` — 0.3; две DLL в `devices` — 4.6b; перечисление при занятом приборе — 0.5/6.2.
- [ ] Хаб как источник настроек камер — не планируется, вопрос владельцу (`design.md`).
- Полный список — [`design.md`](design.md), «Что оставлено открытым».

## Решения (decisions log)

- **2026-10-18:** раунд 2 — раскладка v2; 4.6 -> 4.6a–4.6c; `hik_release` — no-op.
- **2026-10-18:** раунд 3 — ревью плана CHANGES 1 принято целиком; волны вместо фаз; 2.3, 4.2, 4.6c разбиты; К4' без хаба; `restart_backoff_s` снят (B3), допуск с `eps_abs` (B2).
