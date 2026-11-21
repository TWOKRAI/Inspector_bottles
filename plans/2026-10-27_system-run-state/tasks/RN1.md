# Task RN1 — общий помощник «чтение узла» в framework и починка двух потребителей после П3 (бриф, ред. 1, ЧЕРНОВИК лида)

Основание: находка 2 отчёта `docs/reports/2026-11-21_system-run-state_lane-f-p3r-r3c-s4b2.md` §3; запись `OPEN_QUESTIONS` 2026-11-21; вердикт Opus-ревью P3r: «чтение узла должно жить в framework, а не в приватном модуле `backend_ctl`» (третья сборка узла из листьев). Баг после П3 (read-model хранит листья), срок — до 1.0. Статус: бриф, не стартовал (слот писателя занят К / Р2 / Д2); стадия 0 не прогонялась.

## Открыто для лида

| № | вопрос | замер | умолчание брифа |
|---|---|---|---|
| О1 | где живёт помощник: метод `TelemetryReadModel.read_node` или функция рядом | `telemetry_readmodel_module` — владелец листьев (`LeafCopy`, ADR-136); P3r запретил менять модуль «в задаче P3r», здесь запрет снят | метод модуля + тонкая обёртка `TelemetryViewModel.get_node`; `backend_ctl/_node_read.read_node` остаётся делегатом под локом драйвера (FREEZE, не KILL) |
| О2 | что читает `io_debug_section` — узел или лист | путь активного плагина `…io_peek` приходит как dict-узел | читает узел через `get_node`; ожидаемое значение — вложенный dict |
| О3 | расхождение с живым `state.get` (пустые dict, ключи с точкой) — наследуем литералами P3r | `tasks/P3r.md` DESIGN, REDS 8 | переносим те же 3 литерала, фиксируем в README модуля |

## Ревью стадии 0
- не прогонялась (Sonnet, `reviewer`, один раунд на тексте задачи — по «Task launch convention»; Senior+ пилот не применим: задача Middle).

TASK: RN1 — один общий «чтение узла» в `telemetry_readmodel_module`; `io_debug_section.py:250` и `telemetry_view_model.py:258` читают узел, а не только лист   PLAN: plans/2026-10-27_system-run-state/plan.md
ROLE: developer
CHAIN: лид полосы Ф -> you -> reviewer (Sonnet, стадия 5; Opus перед main)

FACTS:
<!-- atlas:facts 96fb1ea -->
- потребитель 1 — `git grep -n "read_model.get(self._active_path)" -- multiprocess_prototype/frontend/widgets/tabs/pipeline/inspector/io_debug_section.py` → `value = read_model.get(self._active_path)`
- потребитель 2 — `git grep -n "return self._model.get(path, default)" -- multiprocess_framework/modules/frontend_module/state/telemetry_view_model.py` → `return self._model.get(path, default)`
- третья сборка узла — `git grep -n "def read_node" -- backend_ctl/_node_read.py` → `def read_node`
<!-- /atlas:facts -->

DESIGN (decided by the lead — you type it, you do not derive it):
  Алгоритм сборки узла из листьев — ровно как в `backend_ctl/_node_read.read_node` (`tasks/P3r.md` DESIGN, правила 1–3: лист побеждает потомков, граница — точка, `(False, None)` для пустого пути и отсутствия узла). Переносится в `telemetry_readmodel_module/telemetry_read_model.py` как публичный метод `read_node(path) -> tuple[bool, Any]` поверх ОДНОГО вызова `self.snapshot(path)`; потокобезопасность — как у `snapshot` самого модуля.
  `TelemetryViewModel` (`frontend_module/state/telemetry_view_model.py`) получает `get_node(path, default=None)` — делегат ядра; существующий `get(path, default)` НЕ меняется (лист — контракт, виджеты на нём).
  `io_debug_section.py` `_replay_cached` (строки ~243–254) заменяет `read_model.get(path)` на `read_model.get_node(path)` (у `bindings.read_model` — `TelemetryViewModel`, `bindings.py:156-164`); остальное не меняется. Если у read_model нет `get_node` (внешний мок) — прежнее чтение `get`, без исключения.
  `backend_ctl/_node_read.read_node(drv, path)` оставляет лок драйвера и делегирует в `drv._telemetry_model.read_node(path)` — публичная форма `(bool, value)` и тексты ответов `conditions.py`/`recorder.py` не меняются; тесты `backend_ctl/tests/test_p3r_*` остаются зелёными без правки. Не менять: `LeafCopy`, формат `snapshot`, `state_store_module`, `bindings.py` (он уже читает `snapshot` и проецирует листья).

FILES (complete list — nothing else; need another file -> stop and ask the lead):
  1. multiprocess_framework/modules/telemetry_readmodel_module/telemetry_read_model.py — `read_node`
  2. multiprocess_framework/modules/frontend_module/state/telemetry_view_model.py — `get_node`
  3. multiprocess_prototype/frontend/widgets/tabs/pipeline/inspector/io_debug_section.py — `_replay_cached` через `get_node`
  4. backend_ctl/_node_read.py — делегирование (лок остаётся)
  5. тесты: новые файлы `telemetry_readmodel_module/tests/test_rn1_read_node.py`, `frontend_module/tests/state/test_rn1_get_node.py`, `…/pipeline/tests/test_rn1_io_debug_node.py`
  6. README/STATUS/DECISIONS модуля `telemetry_readmodel_module` (одна запись ADR-RM-…) — docs-writer после кода

REDS (predicted red tests, <= 10):
  - telemetry_readmodel_module/tests/test_rn1_read_node.py::test_node_dict_assembled_from_leaves
  - telemetry_readmodel_module/tests/test_rn1_read_node.py::test_leaf_ancestor_wins_over_descendants
  - telemetry_readmodel_module/tests/test_rn1_read_node.py::test_boundary_is_dot_not_prefix
  - telemetry_readmodel_module/tests/test_rn1_read_node.py::test_missing_and_empty_path
  - telemetry_readmodel_module/tests/test_rn1_read_node.py::test_known_divergences_from_live_state_get_literals
  - frontend_module/tests/state/test_rn1_get_node.py::test_get_node_returns_nested_dict_get_stays_leaf
  - …/pipeline/tests/test_rn1_io_debug_node.py::test_replay_cached_renders_node_from_leaves_on_real_read_model
  - backend_ctl/tests/test_p3r_node_read.py (весь файл) — зелёный до и после (контроль, не красный)

ACCEPTANCE:
- радиус — `bash "$(git rev-parse --path-format=absolute --git-common-dir)/../scripts/machine_gate.sh" medium <сессия> pytest multiprocess_framework/modules/telemetry_readmodel_module/tests backend_ctl/tests/test_p3r_node_read.py -q`
- гонка — тест читателя `read_node` против писателя (как REDS 7 из `tasks/P3r.md`) на настоящей модели

TESTS: `pytest multiprocess_framework/modules/telemetry_readmodel_module/tests multiprocess_framework/modules/frontend_module/tests/state -q`; прототип — `multiprocess_prototype/frontend/widgets/tabs/pipeline/tests -q`; `backend_ctl/tests` (medium).

OUT OF SCOPE: ядро `state_store_module`; `get()` модуля (лист); пустые dict-узлы в read-model (потеря в ядре — отдельная задача); `bindings.py`; другие читатели узла — перечислить в отчёте `git grep`-ом, не править.
TRAPS: `drv._telemetry_lock` — `threading.Lock`, не `RLock` (`driver.py:527`): помощник под уже взятым локом дедлочит; фейк read_model в тестах io_debug без `get_node` — нужен откат на `get`; слепой tester один раз ДО кода — по критериям ACCEPTANCE.
HANDOFF IN: none
