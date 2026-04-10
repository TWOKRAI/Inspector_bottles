# ADR Registry — коды модулей и миграция нумерации

**Назначение:** единый формат модульных архитектурных решений и таблица соответствия старых номеров новым.

## Правило

| Где принято решение | Формат |
|---------------------|--------|
| Между модулями / глобально | `ADR-NNN` в корневом [`../DECISIONS.md`](../DECISIONS.md) |
| Внутри одного модуля | `ADR-{MODULE_CODE}-NNN` в `modules/<name>/DECISIONS.md` |

Заголовок после миграции: `## ADR-BM-001 (was ADR-114): …`

## Коды модулей

| Код | Модуль | Файл решений |
|-----|--------|----------------|
| **BM** | base_manager | `modules/base_manager/DECISIONS.md` |
| **DS** | data_schema_module | `modules/data_schema_module/DECISIONS.md` |
| **DSP** | dispatch_module | `modules/dispatch_module/DECISIONS.md` |
| **CRM** | channel_routing_module | `modules/channel_routing_module/DECISIONS.md` |
| **MSG** | message_module | `modules/message_module/DECISIONS.md` |
| **RTR** | router_module | `modules/router_module/DECISIONS.md` |
| **LOG** | logger_module | `modules/logger_module/DECISIONS.md` |
| **EM** | error_module | `modules/error_module/DECISIONS.md` (без изменений) |
| **SM** | statistics_module | `modules/statistics_module/DECISIONS.md` (без изменений) |
| **CFG** | config_module | `modules/config_module/DECISIONS.md` |
| **SRM** | shared_resources_module | `modules/shared_resources_module/DECISIONS.md` (уже ADR-SRM-*) |
| **CMD** | command_module | `modules/command_module/DECISIONS.md` |
| **WRK** | worker_module | `modules/worker_module/DECISIONS.md` |
| **PM** | process_module | `modules/process_module/DECISIONS.md` |
| **PMM** | process_manager_module | `modules/process_manager_module/DECISIONS.md` |
| **RM** | registers_module | `modules/registers_module/DECISIONS.md` (без изменений) |

## Маппинг старых → новых (модульные ADR)

### base_manager (BM)

| Было | Стало |
|------|--------|
| ADR-114 | ADR-BM-001 |
| ADR-115 | ADR-BM-002 |
| ADR-116 | ADR-BM-003 |
| ADR-117 | ADR-BM-004 |

### data_schema_module (DS)

| Было | Стало |
|------|--------|
| ADR-120 | ADR-DS-001 |
| ADR-121 | ADR-DS-002 |
| ADR-122 | ADR-DS-003 |
| ADR-123 | ADR-DS-004 |

### dispatch_module (DSP)

| Было | Стало |
|------|--------|
| ADR-130 | ADR-DSP-001 |
| ADR-131 | ADR-DSP-002 |
| ADR-132 | ADR-DSP-003 |

### channel_routing_module (CRM)

| Было | Стало |
|------|--------|
| ADR-013 | ADR-CRM-001 |
| ADR-014 | ADR-CRM-002 |
| ADR-015 | ADR-CRM-003 |
| ADR-016 | ADR-CRM-004 |
| ADR-108 | ADR-CRM-005 |

*Примечание:* ADR-013…016 и ADR-108 остаются также в **глобальном** `DECISIONS.md` как межмодульные решения; детализация и эволюция — в модульном файле.

### message_module (MSG)

| Было | Стало |
|------|--------|
| ADR-147 | ADR-MSG-001 |
| ADR-148 | ADR-MSG-002 |
| ADR-149 | ADR-MSG-003 |
| ADR-150 | ADR-MSG-004 |
| ADR-151 | ADR-MSG-005 |
| ADR-152 | ADR-MSG-006 |

### router_module (RTR)

| Было | Стало |
|------|--------|
| ADR-153 | ADR-RTR-001 |
| ADR-154 | ADR-RTR-002 |
| ADR-155 | ADR-RTR-003 |
| ADR-156 | ADR-RTR-004 |
| ADR-157 | ADR-RTR-005 |
| ADR-158 | ADR-RTR-006 |

### logger_module (LOG)

| Было | Стало |
|------|--------|
| ADR-140 | ADR-LOG-001 |
| ADR-141 | ADR-LOG-002 |
| ADR-142 | ADR-LOG-003 |

### config_module (CFG)

| Было | Стало |
|------|--------|
| ADR-143 | ADR-CFG-001 |
| ADR-144 | ADR-CFG-002 |
| ADR-145 | ADR-CFG-003 |
| ADR-146 | ADR-CFG-004 |

### command_module (CMD)

| Было | Стало |
|------|--------|
| ADR-168 | ADR-CMD-001 |
| ADR-169 | ADR-CMD-002 |
| ADR-170 | ADR-CMD-003 |
| ADR-171 | ADR-CMD-004 |
| ADR-172 | ADR-CMD-005 |

### worker_module (WRK)

| Было | Стало |
|------|--------|
| ADR-159 | ADR-WRK-001 |
| ADR-160 | ADR-WRK-002 |
| ADR-161 | ADR-WRK-003 |
| ADR-162 | ADR-WRK-004 |

### process_module (PM)

| Было | Стало |
|------|--------|
| ADR-163 | ADR-PM-001 |
| ADR-164 | ADR-PM-002 |
| ADR-165 | ADR-PM-003 |
| ADR-166 | ADR-PM-004 |
| ADR-166a | ADR-PM-005 |
| ADR-167 | ADR-PM-006 |

### process_manager_module (PMM)

| Было | Стало |
|------|--------|
| ADR-PM-001 | ADR-PMM-001 |
| ADR-PM-002 | ADR-PMM-002 |
| ADR-PM-003 | ADR-PMM-003 |
| ADR-PM-004 | ADR-PMM-004 |
| ADR-PM-005 | ADR-PMM-005 |
| ADR-PM-006 | ADR-PMM-006 |

### shared_resources_module (SRM)

Глобальные **ADR-017…021** (ConfigStore, register_process, SharedMemory, reinitialize_in_child, pickle SRM) по смыслу относятся к SRM; текст остаётся в корневом `DECISIONS.md`. Локальные решения модуля уже в формате **ADR-SRM-NNN**.

### Глобальные ADR (без переноса номера)

**ADR-001…115+** в [`../DECISIONS.md`](../DECISIONS.md) не переименовываются. При ссылке из кода модулей на глобальное решение используйте глобальный номер.

## Новый модульный ADR

1. Выбрать код модуля из таблицы (или добавить строку согласованно).
2. Следующий свободный NNN в `modules/<name>/DECISIONS.md`.
3. Кратко: контекст, решение, последствия; при необходимости ссылка на глобальный ADR.

## Проверка после миграции

В каталоге `modules/` не должно остаться заголовков вида `## ADR-11x` … `## ADR-17x` (кроме случайных упоминаний в тексте ссылок на **глобальные** ADR — допустимо).

```bash
# из корня репозитория (пример)
rg "^## ADR-1[1-7][0-9]" Inspector_prototype/multiprocess_framework/modules/
```

Ожидается **0** совпадений в заголовках `DECISIONS.md`; ссылки в теле на `ADR-008`, `ADR-112` и т.д. — нормальны.
