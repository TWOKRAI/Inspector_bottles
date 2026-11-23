# Task RN1 — общий «чтение узла» в `telemetry_readmodel_module` и починка двух потребителей после П3 (бриф, ред. 2)

Основание: находка 2 отчёта `docs/reports/2026-11-21_system-run-state_lane-f-p3r-r3c-s4b2.md` §3; `OPEN_QUESTIONS` 2026-11-21; Opus-ревью P3r: чтение узла живёт в framework, не в приватном `backend_ctl`. Баг после П3 (read-model хранит листья), срок до 1.0. Ред. 2 — по стадии 0 (Sonnet, 5 блокирующих Б1–Б5, закрыты ниже); бриф длиннее 8 КБ намеренно: слепому tester нужен один самодостаточный файл с литералами.

## Решено лидом
| № | вопрос | решение |
|---|---|---|
| О1 | где живёт помощник | `telemetry_readmodel_module`: две чистые функции в новом `node_read.py` + метод `TelemetryReadModel.read_node`; `backend_ctl/_node_read.py` берёт функции оттуда (одна копия алгоритма) |
| О2 | что читает `io_debug_section` | узел: путь `…io_peek` в настоящей модели — 6 листьев, `get(path)` → `None` (регресс П3) |
| О3 | расхождения с живым `state.get` | три литерала P3r (ниже), фиксируются в README модуля; для io_debug применимы так же |
| О4 | потокобезопасность | у модуля лока НЕТ, «лок держит вызывающий» (буквально); `read_node` = один `snapshot(path)` |

TASK: RN1 — `io_debug_section` (`_replay_cached`) и `TelemetryViewModel` читают узел из листьев одним общим помощником   PLAN: plans/2026-10-27_system-run-state/plan.md
ROLE: developer
CHAIN: лид полосы Ф -> you -> reviewer (Sonnet, стадия 5; Opus перед main)

FACTS:
<!-- atlas:facts 96fb1ea -->
- потребитель 1 — `git grep -n "read_model.get(self._active_path)" -- multiprocess_prototype/frontend/widgets/tabs/pipeline/inspector/io_debug_section.py` → `value = read_model.get(self._active_path)`
- потребитель 2 — `git grep -n "return self._model.get(path, default)" -- multiprocess_framework/modules/frontend_module/state/telemetry_view_model.py` → `return self._model.get(path, default)`
- третья сборка узла — `git grep -n "def read_node" -- backend_ctl/_node_read.py` → `def read_node`
- четвёртая — `git grep -n "_assemble" -- backend_ctl/driver.py` → импорт `:91` и вызов `:2310` (`driver.py` НЕ трогать)
<!-- /atlas:facts -->

DESIGN (decided by the lead — you type it, you do not derive it):
  1. `telemetry_readmodel_module/node_read.py` (новый), публичные, экспорт из `__init__.py`:
     - `assemble_leaves(leaves: dict[tuple[str, ...], Any]) -> dict[str, Any]` — перенос `_assemble` из `backend_ctl/_node_read.py` как есть (лист-предок побеждает; результат не зависит от порядка);
     - `node_read.py` импортирует ТОЛЬКО stdlib (`typing`, `collections.abc`); `telemetry_read_model.py` берёт его относительным импортом (цикл и тяга backend_ctl/frontend исключены);
     - `node_from_snapshot(snap: Mapping[str, Any], path: str) -> tuple[bool, Any]` — тело `read_node` из `backend_ctl/_node_read.py` после взятия снимка: пустой путь → `(False, None)`; `path in snap` → `(True, snap[path])` (значение может быть None); есть ключи `path + "."` → `(True, вложенный dict относительно path)`; иначе `(False, None)`.
  2. `TelemetryReadModel.read_node(path) -> tuple[bool, Any]`: `if not path: return (False, None)`, затем `node_from_snapshot(self.snapshot(path), path)` — ровно один вызов `snapshot`. Строка `read_node` в `ITelemetryReadModel` (`interfaces.py`). Докстрока и README: «лока у модуля нет, держит вызывающий».
  3. `TelemetryViewModel.get_node(path, default=None)` (`frontend_module/state/telemetry_view_model.py`): `found, value = self._model.read_node(path)`; `value if found else default`. `get(path, default)` НЕ меняется (лист — контракт).
  4. `io_debug_section._replay_cached` (~243–254): `getter = getattr(read_model, "get_node", None)`; есть — `getter(path)`, нет — прежний `read_model.get(path)`; существующий `try/except` остаётся. `bindings.py` НЕ менять (`multiprocess_prototype/frontend/state/bindings.py:189` — `self.read_model`).
  5. `backend_ctl/_node_read.py`: `read_node(drv, path)` = `if not path: return False, None`; `with drv._telemetry_lock: snap = drv._telemetry_model.snapshot(path)`; `return node_from_snapshot(snap, path)` (вне лока). `_assemble` остаётся именем модуля: `from …telemetry_readmodel_module import assemble_leaves as _assemble  # noqa: F401 — для driver.py:91` (без noqa `ruff F401` вырежет импорт через `--fix` и `driver.py:91` упадёт) — `driver.py:91` продолжает работать. Стабы `_SnapshotOnlyModel`/`_StubTelemetryModel` (только `snapshot`) остаются зелёными без правки.
  Не менять: `LeafCopy`, формат `snapshot`, `state_store_module`, `driver.py`, `bindings.py`.

FILES (complete list — nothing else; need another file -> stop and ask the lead):
  1. модуль `multiprocess_framework/modules/telemetry_readmodel_module/`: `node_read.py` (новый), `telemetry_read_model.py` (`read_node`), `interfaces.py`, `__init__.py` (экспорт)
  2. multiprocess_framework/modules/frontend_module/state/telemetry_view_model.py — `get_node`
  3. multiprocess_prototype/frontend/widgets/tabs/pipeline/inspector/io_debug_section.py — `_replay_cached`
  4. backend_ctl/_node_read.py — делегирование
  5. тесты (новые): `telemetry_readmodel_module/tests/test_rn1_read_node.py`, `frontend_module/tests/state/test_rn1_get_node.py`, `multiprocess_prototype/frontend/widgets/tabs/pipeline/tests/test_rn1_io_debug_node.py`
  6. README/STATUS/DECISIONS модуля (новый раздел в `DECISIONS.md`, не «ADR-RM-N»: нумерации там нет) — docs-writer после кода

ЛИТЕРАЛЫ (для tester; `m = TelemetryReadModel()`, запись `m.ingest(path, value)`, `m.ingest_poll_snapshot({...}, requested_at_seq=m.write_seq)`):
  - узел: `ingest("a.n", {"x": 3})` → `read_node("a.n") == (True, {"x": 3})`; `{"p": {"q": 1}, "r": 2}` → `(True, {"p": {"q": 1}, "r": 2})`
  - лист-предок: `ingest("a.n.p", 5)` + poll `{"a.n.p.q": 1}` → `read_node("a.n") == (True, {"p": 5})`, `read_node("a.n.p") == (True, 5)`; тот же результат при обратном порядке записи; `a.n`=5 и poll `{"a.n.x": 1}` → `read_node("a.n") == (True, 5)`
  - граница — точка: `a.n.x`=1 и `a.n2.y`=2 → `read_node("a.n") == (True, {"x": 1})`, `read_node("a.n2") == (True, {"y": 2})`. Этот тест — страж ядра `snapshot`, не `read_node` (фильтр режется в `snapshot`); мутант для `read_node` — срез по `len(path)` вместо `len(path)+1`
  - нет: `read_node("a.zz") == (False, None)`; `read_node("") == (False, None)`; лист `a.n.x` = None → `(True, None)`
  - известные расхождения (P3r): `ingest("a.n", {})` → `(False, None)`; `{"x": 3, "e": {}}` → `(True, {"x": 3})`; `{"k.dot": 1}` → `(True, {"k": {"dot": 1}})`
  - чистые функции (прямой тест, убивает мутант «убрать фильтр startswith»): `node_from_snapshot({"a.n.x": 1, "a.n2.y": 2}, "a.n") == (True, {"x": 1})`; `node_from_snapshot({"a.n.x": 1}, "") == (False, None)`; `assemble_leaves({("p",): 5, ("p", "q"): 1}) == {"p": 5}`; `assemble_leaves({("p", "q"): 1, ("r",): 2}) == {"p": {"q": 1}, "r": 2}`
  - `get_node` (VM): при `a.n`={"x": 3}: `get("a.n")` → `None`, `get_node("a.n")` → `{"x": 3}`, `get("a.n.x")` → `3`; `get_node("a.zz", default=7)` → `7`; лист `a.n.x` со значением None: `get_node("a.n.x", default=7)` → `None` (найден, не default)
  - пустой путь отсекается ДО `snapshot`: стаб-модель со счётчиком вызовов `snapshot`, `read_node("")` → `(False, None)` и `calls == []`
  - гонка (контрактный тест `test_race_under_external_lock`: красный лишь по отсутствию метода, реальную гонку несёт контроль): писатель- и читатель-поток берут ОДИН внешний `threading.Lock` вокруг `ingest`/`read_node`; читатель видит только целые опубликованные узлы и не бросает. Писатель без лока недопустим (`RuntimeError: dictionary changed size` — красный при любой реализации). Контроль: `backend_ctl/tests/test_p3r_node_read.py::test_red7_race_read_node_never_torn_nor_raises` — зелёный до и после
  - io_debug: `TelemetryViewModel` (PySide6, `qtbot`), питается `on_state_delta({"data_type": "state_delta", "path": "processes.draw.plugins.overlay_draw.io_peek", "value": <dict формы _peek с method="process">, "deleted": False})`; после `set_target("draw", "overlay_draw")` в `section._status.text()` есть «обработка» (образец — `test_renders_only_active_path`). Голая `TelemetryReadModel` без `get_node` — другой случай (откат на `get`); откат проверяет существующий `test_io_debug_section.py:148` (контроль, зелёный до и после)

REDS (predicted red tests, <= 10):
  - test_rn1_read_node.py::{test_node_dict_assembled_from_leaves, test_leaf_ancestor_wins_over_descendants, test_missing_and_empty_path, test_known_divergences_from_live_state_get_literals, test_race_under_external_lock} — красные: нет метода
  - test_rn1_read_node.py::test_boundary_is_dot_not_prefix — зелёный сразу (страж ядра), не красный
  - test_rn1_get_node.py::test_get_node_returns_nested_dict_get_stays_leaf; test_rn1_io_debug_node.py::test_replay_cached_renders_node_from_leaves_on_real_view_model — красные
  - контроли (зелёные до/после, без правки): весь `backend_ctl/tests/test_p3r_node_read.py`, `test_replay_live_parity.py`, `test_p3r_replay_await.py`, `test_await_condition.py`, `test_io_debug_section.py`

ПРЕДСКАЗАНИЯ инъекций (лид, до прогона; уточнены ревью раунда 2): (а) `get_node` → `return self._model.get(...)` → красны `test_rn1_get_node` И `test_rn1_io_debug_node` (там настоящая VM: `None`, виджет пуст); (б) `_replay_cached` вернуть на `get` → красен только `test_rn1_io_debug_node` (старый `test_io_debug_section.py:148` на фейке с `get` — зелёный); (в) убрать «лист-предок побеждает» в `assemble_leaves` → красны `test_leaf_ancestor_wins…`, прямой тест `assemble_leaves`, контроль REDS 9 в `test_p3r_node_read`; (г) в делегате убрать лок → красен `test_red10` (детерминированно, `lock_held_during_call == [True]`) и, вероятностно, `test_red7_race…`; (д) делегат зовёт `snapshot` дважды → красен `test_red10` (`calls == [path]`); (е) срез `len(path)` вместо `len(path)+1` в `node_from_snapshot` → красны литералы узла; (ж) убрать фильтр `startswith` → красен только прямой тест чистой функции на грязном снимке; (з) убрать `if not path` в методе → красен тест «пустой путь до snapshot» (`calls == []`).

ACCEPTANCE:
- радиус: `bash "$(git rev-parse --path-format=absolute --git-common-dir)/../scripts/machine_gate.sh" medium inspector-bottles-fr1 pytest multiprocess_framework/modules/telemetry_readmodel_module/tests multiprocess_framework/modules/frontend_module/tests/state backend_ctl/tests/test_p3r_node_read.py backend_ctl/tests/test_replay_live_parity.py backend_ctl/tests/test_p3r_replay_await.py backend_ctl/tests/test_await_condition.py -q`; прототип: `pytest multiprocess_prototype/frontend/widgets/tabs/pipeline/tests -q` (offscreen)
- литералы выше

OUT OF SCOPE: ядро `state_store_module` (`leaf_copy._assemble` — другая форма, не трогать); `get()` модуля (лист); пустые dict-узлы (потеря в ядре — отдельная задача); `bindings.py`, `driver.py`. Другие читатели (только перечислены): `_telemetry_controls.py:275` — лист-метрика, безопасно; `_panels.py:639,1138,1231` и `bindings.py:201` — `snapshot` + листья, не затронуты; `backend_ctl/driver.py:2310` — `_assemble` по процессам, остаётся через реэкспорт.
TRAPS: `drv._telemetry_lock` — `threading.Lock`, не `RLock` (`driver.py:527`): `read_node` под уже взятым локом дедлочит; мок read_model без `get_node` — откат на `get`; `MagicMock`-модель вернёт из `get_node` не dict, `_render` молча выйдет; пустой путь отсекать ДО `snapshot` (полная копия).
TESTER: слепой, один раз ДО кода, по ЛИТЕРАЛАМ и ACCEPTANCE этого файла + `tasks/P3r.md` (REDS 7–9) + существующие тесты как образец. ЗАПРЕТНЫЕ пути: `telemetry_read_model.py`, `node_read.py`, `telemetry_view_model.py`, `io_debug_section.py`, `backend_ctl/_node_read.py` (читать нельзя).
HANDOFF IN: none
