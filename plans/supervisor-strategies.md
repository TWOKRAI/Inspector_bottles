# supervisor-strategies (В5 · NEW-6b)

**Ветка:** `feat/supervisor-strategies`
**Refs:** `plans/current-path/plan.md` (В5 NEW-6), `plans/supervisor-backoff-jitter.md` (NEW-6a)
**Слой:** framework
**Статус:** реализовано

## Цель

OTP-стратегии супервизии: падение процесса каскадит рестарт на зависимых/группу.
До NEW-6b супервизор был плоским (`one_for_one`): рестартовал только упавшего, а
зависимые оставались живыми, но без апстрима (молчаливая деградация).

## Дизайн (решение владельца: «универсальный, с заделом на будущее»)

- **Группа** — именованный тег `ProcessConfig.supervision_group` (процессы с одним
  именем = одна группа). Не новая иерархия сущностей: тег + существующий граф.
- **Порядок каскада** — из `depends_on` (переиспользуем граф 3.9), апстрим раньше
  зависимого (`_topo_order`, Kahn; цикл не роняет каскад).
- **Стратегия** — `RestartPolicy.strategy: Literal["one_for_one"(деф), "rest_for_one",
  "one_for_all"]`.

| Стратегия | Кого рестартим дополнительно |
|---|---|
| `one_for_one` | никого (прежнее поведение, бит-в-бит) |
| `rest_for_one` | все, кто транзитивно `depends_on` упавшего; при заданной группе — только её члены |
| `one_for_all` | все остальные члены группы упавшего (без группы → WARNING + деградация в one_for_one) |

## Сделано

- Схема: `ProcessConfig.supervision_group` + `ProcessLaunchConfig.supervision_group`
  → верхний уровень `proc_dict` (пустой не кладём); `RestartPolicy.strategy` (Literal).
- `ProcessMonitor._resolve_restart_set(failed, strategy, groups, deps)` — чистая функция
  «кого ещё рестартить», топологически упорядоченная, без `failed`.
- `_topo_order`, `_supervision_snapshot` (живые срезы `_process_configs`, как `_resolve_policy`).
- `_cascade_restart` — induced-рестарты через тот же `_pending_restarts`/IPC-путь.
  **Induced НЕ пишет метку в `_restart_history` члена**: интенсивность (max_retries/window)
  — свойство супервизора и считается по триггеру (семантика OTP), иначе каскад «сдавался»
  бы на здоровых членах. Пропускаются protected / уже запланированные / `_given_up`.
- `_escalate_group_giveup` — при give-up по триггеру члены получают
  `processes.<name>.supervisor.note` + громкий ERROR (иначе группа тихо полумёртвая).
  Путь supervisor-owned, НЕ `health.degraded_reason`: health член публикует полным
  снапшотом, чужая метка в его поддереве затиралась бы через такт (фикс HIGH-2 ревью).
  Новый вид supervisor-события НЕ вводится: словарь {crashed, unresponsive, restarting,
  recovered, gave_up} — контракт GUI и будущего alerting (NEW-7).
- Hardening по ревью: `_induced_restarts` (heartbeat живого члена каскада ≠ `recovered`,
  watchdog H3 сохраняется), нет повторного каскада на `restart-not-confirmed`,
  лесенка `_CASCADE_STAGGER_SEC` между induced-рестартами.

## Acceptance

- [x] `one_for_one` (дефолт) — каскада нет, поведение прежнее.
- [x] `rest_for_one` — транзитивные зависимые, ограничение группой, без `failed`.
- [x] `one_for_all` — члены группы, чужие группы не задеты; без группы → WARNING + one_for_one.
- [x] Порядок каскада топологический; цикл не подвешивает.
- [x] Induced-рестарт не заряжает `_restart_history` члена; ставит pending/recovery/deadline.
- [x] Каскад пропускает protected / `_given_up` / уже запланированных (не затирает чужой план).
- [x] Эскалация give-up метит группу `degraded_reason` + ERROR; не трогает `one_for_one` и уже сдавшихся.
- [x] `supervision_group` доходит до `proc_dict`; пустой отсутствует.
- [x] Тесты: `test_supervision_strategies.py` (31) + регресс 1464 passed.
- [x] Полный framework-suite (5315 passed на первой редакции).
- [x] Fable-ревью (graphify сработал, вскрыл re-entrancy-путь): 2 HIGH + 2 MED + 3 LOW закрыты —
  induced-пометка против ложного recovered/потери H3, supervisor-owned путь эскалации,
  симметрия rest_for_one без группы, отказ от повторного каскада на watchdog-переинициации,
  лесенка induced, документирование семантики. Тесты: 51 (+20 hardening).

## Out of scope

- NEW-7 alerting (правила «gave_up/drop растёт → громкая нотификация») — следующий инкремент.
- Каскад на путях switch/hot-apply (стратегии живут на supervision-пути монитора).
- GUI-редактор `supervision_group`/`strategy`.
