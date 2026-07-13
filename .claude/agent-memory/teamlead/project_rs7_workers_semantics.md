---
name: rs7-workers-semantics
description: RS-7 recipe `workers` field семантика — process-level named threads, НЕ chain-pool; ортогонально C6e, требует отдельного адаптера
metadata:
  type: project
---

Поле `Process.workers` рецепта (`multiprocess_prototype/domain/entities/process.py`)
= `tuple[WorkerSpec, ...]` — декларативный список **именованных потоков процесса**
(worker_name / priority / execution_mode / target_interval_ms / worker_class / config),
явно «для спавна через WorkerManager». Это НЕ размер chain-пула.

**Why (важно для будущей доводки RS-7):** план `constructor-master` (RS-7, строка ~321)
говорит «довести `workers` до worker_module ПОПУТНО с C6(e), там вскрывается worker_module-пул».
Это конфляция: C6(e)-пул (`WorkerPoolExecutor`, анонимные `chain_pool_i`, ADR-CHN-009) —
внутренний исполнитель параллельных бандлов chain, а `workers` рецепта — процессные
именованные треды. Общий у них только `worker_module`, не семантика и не код-путь. Поэтому
доводка `workers` НЕ идёт «попутно» с C6(e) — это независимая фича.

**Почему поле «пока не влияет» (доказано кодом на 2026-07-13):**
1. Домен→framework: `workers` НЕ пробрасывается ассемблером в framework blueprint /
   `proc_dict["workers"]` (grep пуст в `backend/assembly`, `domain/services`).
2. Shape-mismatch: framework `ProcessModule._create_workers_from_config`
   (`process_module/core/process_module.py:401`) ждёт **dict** `{name: {class, config, thread}}`;
   домен даёт `tuple[WorkerSpec]` с иными именами (`worker_class` vs `class`, плоские
   priority/execution_mode vs вложенный `thread`).
3. `worker_class=None` → generic IdleWorker (`process_module/generic/idle_worker.py` есть),
   но текущий `_create_workers_from_config` СКИПАЕТ записи без ключа `"class"`.

**How to apply:** доводка RS-7 `workers`→рантайм = отдельная задача: адаптер
`tuple[WorkerSpec]`→`{name:{class,thread,config}}` (с IdleWorker-дефолтом при None) +
проброс через ассемблер в proc_dict + решение владельца «спавнить ли idle-треды без
Pipeline-нагрузки» (WorkerSpec: «нагрузку даёт Pipeline» → сейчас спавн = no-op треды).
Не встраивать наугад в C6(e). См. [[new-framework-module-registration]] стиль плана.
Живой плумбинг: `_init_application_threads`→`_create_workers_from_config`,
`WorkerManager.create_worker/remove_worker`.
