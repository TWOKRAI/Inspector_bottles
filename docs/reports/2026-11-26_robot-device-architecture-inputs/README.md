# Приложения к разбору приборов 2026-11-26

Основной документ: [`../2026-11-26_robot-device-architecture.md`](../2026-11-26_robot-device-architecture.md). Метки [А], [Ч], [Л], [CTO] — как в нём.

## Воспроизведения

Скрипты лежат в этом каталоге. Это материалы разбора, не тесты проекта. Запуск из корня дерева (`PYTHONPATH=<корень>`, `PYTHONUTF8=1`):

```bash
bash scripts/machine_gate.sh light <сессия> .venv/Scripts/python.exe docs/reports/2026-11-26_robot-device-architecture-inputs/repro_c104.py
bash scripts/machine_gate.sh light <сессия> .venv/Scripts/python.exe -m pytest docs/reports/2026-11-26_robot-device-architecture-inputs/test_r2_probe.py -s -q -p no:cacheprovider
bash scripts/machine_gate.sh light <сессия> .venv/Scripts/python.exe -m pytest docs/reports/2026-11-26_robot-device-architecture-inputs/test_r2_journal.py -s -q -p no:cacheprovider
```

`repro_c104.py` — J1–J4; `test_r2_probe.py` — C1–C4, C6; `test_r2_journal.py` — раздел 4. Сим или подменённый транспорт, без настоящего обмена между процессами.

## Атлас против кода (прав код) [А]

Использованы карточки `services/{device_hub, camera_device, robot_comm, vfd_comm, modbus, code_reader, hikvision_camera}`, `plugins/hub`.
Расхождения: «API (0)» у `device_hub` и `camera_device`, хотя `spi.py`, `kinds.py`, `interface.py` объявляют Public API; назначение `modbus` «связь с PLC» (на деле транспорт робота и ПЧ); `code_reader` «приём по TCP» (живой путь — SDK); `camera_device` «контракт порта и фейк» (там и сеанс-владелец); у `plugins/io` не названы `robot_io`, `robot_draw`; `atlas index --check`: `INDEX.md` отстал.
