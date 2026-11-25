# Task W2-e: ручной перезапуск отличим от решения супервизора в причине аварии

- **Статус:** [PENDING] · **Level:** Middle+ · **Assignee:** developer
- **Module contract:** impl-only (`process_manager_module`: именованный параметр `origin` у `mark_restarting`, поле `EvalInput`)
- **Dependencies:** нет (база волны 2). Степень причины (авария или «вне допуска») — решение Р-W2-9, здесь НЕ меняется
- **Gate:** `machine_gate.sh light <session>` по файлам TESTS; радиус `multiprocess_framework/modules/process_manager_module/tests` (heavy — только в окне лида)
- **Files:** `multiprocess_framework/modules/process_manager_module/monitor/process_monitor.py`, `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py`, `multiprocess_framework/modules/process_manager_module/process/run_state.py`, `multiprocess_framework/modules/process_manager_module/tests/test_restart_origin_reason.py`
- **Acceptance:** блок ACCEPTANCE
- **Handoff:** developer (REDS в брифе, красный прогон до правки src, break-injection) -> reviewer (стадия 5, opus — машина состояний прогона)

Основание: инцидент 2026-11-25 11:44 — ручной `process_restart_verified` камеры дал причину «camera_0: перезапускается супервизором» (`run_state.py:90`); оператор и агент читают её как отказ.

TASK: W2-e — причина `restarting` несёт происхождение: «по команде» или «супервизор»   PLAN: plans/2026-11-25_multicam-observability/plan.md
ROLE: developer
CHAIN: lead -> you -> reviewer (стадия 5)

DESIGN (decided by the lead — you type it, you do not derive it):
  1. `process_monitor.py:387`, `mark_restarting(self, process_name: str, origin: str = "supervisor") -> None`; монитор хранит `origin` рядом с пометкой; `unmark_restarting` снимает оба. Допустимые значения `"supervisor"`, `"command"`; иное -> `"supervisor"` и одна WARNING.
  2. `process_manager_process.py:5696` (путь ручного `process.restart`) — `mark(name, origin="command")`; путь решения супервизора — без изменений (умолчание).
  3. `run_state.py`: `EvalInput.restarting_origin: Mapping[str, str] = field(default_factory=dict)`; в `_process_reasons` для процесса из `restarting`: `origin == "command"` -> текст `f"{name}: перезапуск по команде"`, иначе прежний литерал `f"{name}: перезапускается супервизором"`. Степень (`failure`) и `source` (`liveness`) не меняются. Вызов `evaluate` в PM (`process_manager_process.py:1389`, `restarting=restarting`) передаёт и `restarting_origin`.

FILES (complete list — nothing else; need another file -> stop and ask the lead):
  1. multiprocess_framework/modules/process_manager_module/monitor/process_monitor.py — `origin`
  2. multiprocess_framework/modules/process_manager_module/process/process_manager_process.py — ручной путь, передача в `evaluate`
  3. multiprocess_framework/modules/process_manager_module/process/run_state.py — поле, текст
  4. multiprocess_framework/modules/process_manager_module/tests/test_restart_origin_reason.py — новый

REDS (predicted red tests):
  - multiprocess_framework/modules/process_manager_module/tests/test_restart_origin_reason.py::test_command_restart_reason_text (`EvalInput` с `restarting={"camera_0"}`, `restarting_origin={"camera_0": "command"}` -> причина `camera_0: перезапуск по команде`, `failure`)
  - multiprocess_framework/modules/process_manager_module/tests/test_restart_origin_reason.py::test_supervisor_restart_reason_unchanged (охранный: без `restarting_origin` — прежний литерал)
  - multiprocess_framework/modules/process_manager_module/tests/test_restart_origin_reason.py::test_monitor_keeps_origin_until_unmark
  - multiprocess_framework/modules/process_manager_module/tests/test_restart_origin_reason.py::test_unknown_origin_falls_back_with_warning

ACCEPTANCE (every number with its command):
  - `<py> -m pytest -q --tb=short multiprocess_framework/modules/process_manager_module/tests/test_restart_origin_reason.py` -> exit 0
  - тесты `run_state` пакета — `<py> -m pytest -q --tb=short -k "run_state or restart" multiprocess_framework/modules/process_manager_module/tests` (medium) -> exit 0; полный радиус — у лида
  - `ruff check -q` по четырём путям -> 0

TESTS: bash "$(git rev-parse --path-format=absolute --git-common-dir)/../scripts/machine_gate.sh" light <session> <py> -m pytest -q --tb=short multiprocess_framework/modules/process_manager_module/tests/test_restart_origin_reason.py

OUT OF SCOPE: степень причины ручного перезапуска в прогоне (Р-W2-9); кто именно дал команду (W2-k, аудит).
TRAPS: `restarting` — `frozenset` в `EvalInput` (чистая функция, без IO): `restarting_origin` — словарь, приходящий снаружи, как `down_since`. Причина входит в подпись push (ADR-PMM-048): смена текста — новая подпись, это верно.
HANDOFF IN: none
REPORT: STATUS (DONE|BLOCKED), files, команды и вывод по ACCEPTANCE, красные до/после, раздел «Что оставил открытым / ненадёжно».
