# Services/camera_device — Статус

Дата: 2026-10-28 · ветка `feat/camera-device-service`

## Текущее состояние

Ядро не написано. Записаны решения и два набора фактов с приборов; код начинается с Task 1.5 (порт, фейк, контрактный тест).

## Что есть

| Что | Где | Как получено |
|---|---|---|
| ADR-CAM-001…004 | `DECISIONS.md` | Task 0.1 |
| Boundary «ядро -> `code_reader` / `hikvision_camera`» | `.sentrux/rules.toml` | Task 0.1; проба: красный на `import Services.code_reader`, зелёный после удаления пробы |
| Дерево узлов ID3013 (8 узлов, `.10`) | `testing/recordings/mvcr_ID3013.json` | Task 6.2, 2026-10-19 |
| Дерево узлов MVS MV-CS020-10GC (15 узлов) | `testing/recordings/mvs_MV-CS020-10GC.json` | Task 0.5, 2026-10-27 |

## Чего нет

`interface.py`, `session.py`, `params.py`, `plugin_base.py`, `registers_base.py`, `drivers/`, `testing/fake_port.py`, тестов.
Порядок — в [плане](../../plans/2026-10-18_camera-device-service/plan.md), волны W2 и далее.

## Не проверено

- Запрет «ядро -> вендор» не ловит `from Services.hikvision_camera.sdk import structures` (один замер, Task 0.1).
- Перезахват `stop -> план -> start_grabbing` в том же handle у `mvcr` — шлюз Task 6.4.
