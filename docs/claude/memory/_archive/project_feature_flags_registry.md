---
name: project_feature_flags_registry
description: "FW_* реестр feature_flags.py ЗАКРЫТ 2026-07-15 (0.2/G.F): 18 флагов, ctor>env>default, typo→KeyError, requires+validate, alias; 16 сайтов мигрированы; boot-лог в оркестраторе"
metadata:
  node_type: memory
  type: project
  originSessionId: 2bbae9f7-11c0-4154-8369-2fd9c8dfa9bb
---

**ЗАКРЫТО 2026-07-15** (задача 0.2/G.F flip-плана, ветка `feat/feature-flags-registry`,
3 коммита, гейт 4720 passed / 6 skipped / 2 pre-existing Windows-fail):
- `config_module/feature_flags.py` (lite, contract-first): `FeatureFlag` + `FlagState` +
  `FLAGS` (18 флагов) + `resolve/is_enabled/state_of/list_flags/validate`. Приоритет
  `ctor-arg > env > default` (откат dark-launch бит-в-бит), неизвестное имя → `KeyError`
  (ловит опечатку). Requires-граф декларативный (`ZERO_COPY⊃HANDLE_CACHE⊃OWNER_INCARNATION`,
  `LOAN⊃ZERO_COPY`, `GC_SCHEDULED⊃GC_FREEZE`); `validate()` **advisory** (не бросает —
  enforcement остаётся у владельца ресурса, напр. FrameShmMiddleware). Alias
  `MULTIPROCESS_USE_KIND_CHANNELS` → канон `FW_USE_KIND_CHANNELS`. 19 contract-тестов.
- Мигрировано 16 сайтов в 12 файлах (коммит `fa99177e`): хелперы `_resolve_env_flag`/
  `_resolve_bool_flag` → делегация в `resolve()` (callers не тронуты, hot-path бит-в-бит);
  double-read `FW_SHM_OWNER_INCARNATION` (manager+middleware) устранён. **Урок:** парсинг
  нормализован к каноническому truthy F9 → 6 ops-сайтов (PERF_PROBES/HEALTH_RESTART/FENCE/
  PORT_VALIDATE/ROUTING_REFRESH/AUTORESTART) чуть изменили поведение на НЕстандартных
  строках (бит-в-бит на `0/1/true/false`); ladder dark-launch флаги были на env_truthy → строго бит-в-бит.
- **Экспозиция в оркестратор** (коммит `0b89466b`): `ProcessManagerProcess._log_active_feature_flags()`
  — boot-лог не-дефолтных маркеров + validate-нарушений через LoggerManager (раз на старте,
  0 hot-path). НЕ в `introspect.capabilities` (там CI-gate детерминизма — env-значения нельзя).
- **Разграничение (требование владельца 2026-07-15):** маркеры движка `FW_*` — ЭТА плоскость;
  логи/статистика/ошибки — ДРУГАЯ (секция `observability` app.yaml + hot-reload, [[project-observability-control-plane]],
  ошибки всегда on). Не смешивать. NEXT по flip-плану: 0.3 supervisor→shm_reclaim, 0.4 backend/tests в гейт.

---

## Исходное решение (2026-07-14)

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
