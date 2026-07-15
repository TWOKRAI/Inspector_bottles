---
name: project_feature_flags_registry
description: "Владелец: FW_* флаги разбросаны литералами — свести в единый реестр-модуль feature_flags.py (не ConfigStore); задача после H-память, до flip G.7"
metadata: 
  node_type: memory
  type: project
  originSessionId: 2bbae9f7-11c0-4154-8369-2fd9c8dfa9bb
---

Владелец (2026-07-14, во время H-память): **маркеры-флаги `FW_*` разбросаны** строковыми
литералами по модулям — хочет все в ОДНОМ месте (как Config в прототипе).

**Факт:** 16 боевых флагов (`FW_QOS_PROFILES`, `FW_SHM_LOAN_PROTOCOL`, `FW_SHM_SEQLOCK`,
`FW_SHM_ZERO_COPY`, `FW_SHM_HANDLE_CACHE`, `FW_SHM_OWNER_INCARNATION`, `FW_SHM_PREFIX_CLEANUP`,
`FW_DATA_PLANE_DICTS`, `FW_PERF_PROBES`, `FW_HEALTH_RESTART`, `FW_AUTORESTART`, `FW_FENCE`,
`FW_PORT_VALIDATE`, `FW_ROUTING_REFRESH`, `FW_CONTRACTS_STRICT`, …) + `use_kind_channels`.
Парсинг уже централизован (`env_flag()` в `config_module/tools/env.py`, G.2 F9), но РЕЕСТРА нет:
имя/дефолт/док каждого флага живут строкой в модуле-читателе. Опечатка → тихий default=False.

**Решение владельца (2026-07-14):**
- Подход: **единый реестр-модуль** `feature_flags.py` в `config_module` (НЕ через ConfigStore).
  Каждый флаг задекларирован раз (имя/default/doc), приоритет **ctor-arg > env > default**
  сохранён (на нём держится откат «бит-в-бит» dark-launch), `list_flags()` — снимок всех для
  `/dev` и приёмки G.7. ConfigStore отклонён: Config = Pydantic-прикладной-конфиг (правила 1/5),
  а флаги — глобальные process-toggles движка; смешивать нельзя, precedence не даёт из коробки.
- Когда: **отдельной задачей ПОСЛЕ H-память** (cross-cutting 16 флагов × ~10 файлов — не мешать
  в ветку H-память, чтобы ревью двух рефакторов не слиплось), ветка `feat/feature-flags-registry`.
  **До flip G.7** (вместе с [[project_memory_module_consolidation]]).

Связано: [[project_memory_module_consolidation]] (тот же спринт «без костылей до G.7»),
[[feedback_ruff_strips_unused_import]].
