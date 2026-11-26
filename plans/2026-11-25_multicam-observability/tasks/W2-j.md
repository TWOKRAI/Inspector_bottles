# Task W2-j: запрет прогона для правок полей (`FieldMeta.run_locked`)

- **Статус:** [PENDING] · **Level:** Senior · **Assignee:** teamlead
- **Блокер:** решение владельца Р-W2-5 (какие поля запираются в прогоне); обход администратором — W2-k, не здесь
- **Module contract:** public-api-change (`data_schema_module` `FieldMeta`: новый признак; ответ `register_update`)
- **Dependencies:** W2-i (тот же путь записи); по файлам независима
- **Gate:** `machine_gate.sh light <session>` по файлам TESTS; радиусы `data_schema_module/tests`, `process_module/tests` (heavy — окно лида)
- **Files:** `multiprocess_framework/modules/data_schema_module/core/field_meta.py`, `multiprocess_framework/modules/process_module/generic/plugin_orchestrator.py`, `multiprocess_framework/modules/process_module/plugins/base.py`, `multiprocess_framework/modules/process_module/tests/test_field_run_lock.py`
- **Acceptance:** блок ACCEPTANCE
- **Handoff:** lead (DESIGN) -> teamlead (REDS до правки src) -> reviewer (стадия 5, opus)

Основание: ADR-PM-062 «Не закрыто: правки регистров (`register_update`, `set_config`) запрет по имени команды не закрывает — нужен признак на `FieldMeta`». Ревью волны 1: живая правка поля `apply="restart"` перезапускает захват в прогоне, хотя `release_device`/`take_device` заперты (`_run_active` в `Services/` вне тестов — 0 совпадений, Explore-карта).

TASK: W2-j — поле с `run_locked=True` не пишется, пока система в `running`; ответ — тот же литерал, что у запертой команды   PLAN: plans/2026-11-25_multicam-observability/plan.md
ROLE: teamlead
CHAIN: lead -> you -> reviewer (стадия 5)

DESIGN (decided by the lead — you type it, you do not derive it):
  1. `FieldMeta(..., run_locked: bool = False)`; в `get_field_metadata` ключ `run_locked`. Иначе поле ведёт себя как раньше.
  2. `PluginOrchestrator._on_register_update` (`plugin_orchestrator.py:855-879`): до `set_field_value` — `run_locked` поля и `getattr(services, "_run_active", None)` взведён -> ответ `{"success": False, "error": "running", "message": "сначала ОСТАНОВИТЬ"}`, запись не делается, одна INFO `register_update <register>.<field>: отказ, система в работе`.
  3. `cmd_set_config` (после W2-i): та же проверка по каждому полю пакета ДО записи; хоть одно заперто -> `{"status": "error", "error": "running", "message": "сначала ОСТАНОВИТЬ"}`, ничего не записано.
  4. Какие поля камеры и считывателя получают `run_locked=True` — список из решения Р-W2-5 (рекомендация лида: все `apply="restart"` и `apply="config"` полей приборов). Пометка полей — отдельный коммит этой задачи ПОСЛЕ решения, файлы регистров — с разрешения лида (вне FILES сейчас).

FILES (complete list — nothing else; need another file -> stop and ask the lead):
  1. multiprocess_framework/modules/data_schema_module/core/field_meta.py — признак
  2. multiprocess_framework/modules/process_module/generic/plugin_orchestrator.py — отказ `register_update`
  3. multiprocess_framework/modules/process_module/plugins/base.py — отказ `set_config`
  4. multiprocess_framework/modules/process_module/tests/test_field_run_lock.py — новый

REDS (predicted red tests):
  - multiprocess_framework/modules/process_module/tests/test_field_run_lock.py::test_locked_field_refused_in_running
  - multiprocess_framework/modules/process_module/tests/test_field_run_lock.py::test_locked_field_written_when_not_running
  - multiprocess_framework/modules/process_module/tests/test_field_run_lock.py::test_unlocked_field_written_in_running (охранный)
  - multiprocess_framework/modules/process_module/tests/test_field_run_lock.py::test_set_config_batch_with_locked_field_writes_nothing

ACCEPTANCE (every number with its command):
  - `<py> -m pytest -q --tb=short multiprocess_framework/modules/process_module/tests/test_field_run_lock.py` -> exit 0
  - `<py> -m pytest -q --tb=short multiprocess_framework/modules/process_module/tests/test_run_locked_commands.py` -> exit 0; полный радиус — у лида
  - `ruff check -q` по четырём путям -> 0

TESTS: bash "$(git rev-parse --path-format=absolute --git-common-dir)/../scripts/machine_gate.sh" light <session> <py> -m pytest -q --tb=short multiprocess_framework/modules/process_module/tests/test_field_run_lock.py

OUT OF SCOPE: обход запрета ролью и аудит (W2-k); GUI (серое поле в прогоне) — prototype, позже.
TRAPS: `services` оркестратора — тот же объект, что `ctx.services` у плагина (флаг кладёт раннер, ADR-PMM-051); проверьте, а не предполагайте. Признак в `FieldMeta` влияет на кэш метаданных `SchemaMixin` — новый ключ не ломает сравнение кэша.
HANDOFF IN: W2-i — путь `cmd_set_config`; решение Р-W2-5.
REPORT: STATUS (DONE|BLOCKED), files, команды и вывод по ACCEPTANCE, красные до/после, раздел «Что оставил открытым / ненадёжно».
