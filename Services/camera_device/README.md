# Services/camera_device

Общее ядро камер: один порт прибора, сеанс с потоком-владельцем, общий набор команд плагина.
Вендорские сервисы (`code_reader`, `hikvision_camera`) и драйвер OpenCV — тонкие драйверы над ним.

**Stability: draft.** Заготовка Task 0.1: кода ядра пока нет, есть только записи узлов приборов в `testing/recordings/`.
Полный текст — в Task 1.5 (контракт порта) и Task 5.4 («как добавить вендора»).

## Purpose

- Один владелец прибора на процесс; все вызовы SDK — из одного потока (ADR-CAM-002).
- Параметр описан один раз — в поле register'а; драйвер держит только таблицу привязки (ADR-CAM-003).
- Один набор команд для всех драйверов, один формат item (ADR-CAM-004).

## Boundaries

- Ядро импортирует только `multiprocess_framework` и stdlib; `cv2` и `numpy` — только `drivers/opencv_driver.py` и `testing/`.
- Ядро не импортирует вендоров: драйверы подключаются строками реестра `drivers/__init__.py` (ADR-CAM-001).
  Запрет держат две записи `[[boundaries]]` в `.sentrux/rules.toml`; проверка — `sentrux check .`.
- Вендорские пакеты импортируют ядро, не наоборот. Services не импортируют `Plugins` и `multiprocess_prototype`.
- Один экземпляр плагина камеры на процесс (путь состояния `processes.<p>.state.<плагин>` и register по имени плагина).

## Решения и план

- [`DECISIONS.md`](DECISIONS.md) — ADR-CAM-001…004.
- [`STATUS.md`](STATUS.md) — что есть.
- План: [`plans/2026-10-18_camera-device-service/plan.md`](../../plans/2026-10-18_camera-device-service/plan.md).
