# Стандарты: состояние работы системы

Раздел 9 [`design.md`](design.md), вынесен по размеру 2026-11-02. Нумерация §9.x сохранена.

## 9. Соответствие стандартам

Издания и URL сверил web-researcher координатора (2026-10-27); где он пишет «не подтверждено» — так и помечено.

| стандарт | издание | источник |
|---|---|---|
| PackML (модель состояний) | OPC 30050 v1.01, 2020-11-11 | https://reference.opcfoundation.org/PackML/docs/ |
| ANSI/ISA-TR88.00.02 | 2022 — **не подтверждено** | — |
| NAMUR NE 107 | ред. 2017-04-10 | https://www.namur.net/en/publications/news-archive/ne-107-has-been-revised.html |
| IEC 60204-1 | Ed. 6.0 2016 + AMD1:2021 (сводная 6.1); определения категорий — по вторичному источнику | https://webstore.iec.ch/publication/71256 |
| OPC 10000-100 (DI) | 1.05.0, 2025-11-15 | https://reference.opcfoundation.org/DI/docs/ |
| ANSI/ISA-18.2 | 2016; состояния аварии — по вторичному источнику | https://isa.org/standards-and-publications/isa-standards/isa-18-series-of-standards |
| ANSI/ISA-101.01 | 2015 — **не подтверждено** | — |

### 9.1. PackML (OPC 30050 v1.01; ISA-TR88.00.02 — издание не подтверждено)

Состояния OPC 30050: Aborting, Aborted, Clearing, Stopped, Stopping, Resetting, Idle, Starting, Execute, Suspending,
Suspended, Unsuspending, Holding, Held, Unholding, Completing, Complete; режимы Production, Maintenance, Manual.
Деление на «действующие» (`*-ing` и Execute) и «ожидающие» (остальные) — **наше прочтение**, источником не подтверждено:
у нас действующие — `booting`, `running`, `stopping`; ожидающие — `not_ready`, `ready`, `fault`.

| PackML | наше | 1.0 |
|---|---|---|
| Resetting | `booting` | да (подъём узлов, ожидание готовности) |
| Idle | `ready` | да |
| Stopped | `not_ready` (+ причины) | да; в PackML Stopped → Reset → Idle — у нас переход автоматический по готовности, без команды Reset |
| Starting | — | нет: START мгновенный (взвод события) |
| Execute | `running` | да |
| Stopping | `stopping` | да |
| Aborting / Aborted | `fault` (переход + состояние схлопнуты) | да, одно состояние |
| Clear / Clearing | команда `system.run.ack` («Квитировать») | да, мгновенно: `fault` → `ready`/`not_ready` (**В4**, Task 1.7) |
| Held/Holding/Unholding, Suspended/Suspending/Unsuspending | — | нет в 1.0: голодание ленты/нет диска — индикатор `out_of_spec` в `running`, не состояние (**В8**) |
| Complete/Completing | — | нет: непрерывный процесс |
| Режимы Production/Maintenance/Manual | — | нет; кандидат после 1.0 (Manual = пульт без гейта) |

### 9.2. NAMUR NE 107 (ред. 2017-04-10) — символы и цвета не подтверждены

| NE 107 | наше `severity` | C-55b | блокирует START |
|---|---|---|---|
| Failure (F) | `failure` | `error` | да |
| Function check (C) | `check_function` | — | **К3** (рекомендация: да — узел в калибровке/обслуживании) |
| Out of specification (S) | `out_of_spec` | `warning` | нет, показ |
| Maintenance required (M) | `maintenance` | `info` | нет, показ |
| OK | нет причин | — | — |

Не берём: цветовую/иконную нотацию NE 107 как требование (это ISA-101/GUI).

### 9.3. IEC 60204-1 (Ed. 6.1 сводная), категории останова

| категория | смысл | у нас |
|---|---|---|
| 0 | немедленное снятие энергии | не программная функция; ближайшее — `system.shutdown mode=force` / HALT драйвера; **не** STOP |
| 1 | управляемый останов, затем снятие энергии | STOP оператора с шагом `pre_stop` «домой → серво OFF» (T5.3e «Остановить») |
| 2 | управляемый останов, энергия остаётся | авария `fault`: `pause()` — стоп движения на месте; также `process.stop` отдельного процесса (поток останавливается, привод под питанием) |

**Аварийный останов (e-stop) — аппаратная функция безопасности (ISO 13849 / IEC 62061). Программный STOP и `fault`
этого плана e-stop'ом не являются и его не заменяют.**

### 9.4. OPC UA — PackML companion (OPC 30050 v1.01), Device Integration (OPC 10000-100 1.05.0)

Только проверка имён: `system.run.state` ↔ PackML `CurrentState`, `system.run.reasons` ↔ DI `DeviceHealth` (NE 107-
шкала в DI) + сообщения. Плоские пути state отображаются в узлы без переименования. OPC UA в 1.0 нет.

### 9.5. ISA-18.2-2016 (аварийная сигнализация) и ISA-101.01 (HMI, издание не подтверждено)

Состояния аварии ISA-18.2 (по вторичному источнику): Normal, Unacknowledged, Acknowledged, RTN Unacknowledged, Shelved,
Suppressed by Design, Out of Service. Берём только Unacknowledged → Acknowledged. Берём: авария имеет состояние подтверждения (у нас `last_fault` гасится нажатием START — подтверждение действием;
отдельная кнопка «Квитировать» — **В4**); неактивная кнопка показывает почему (первая причина `failure`, список — по
наведению/раскрытию). Не берём: приоритеты, shelving, рационализацию аварий.
