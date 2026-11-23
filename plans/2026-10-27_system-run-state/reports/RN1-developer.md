# RN1 — отчёт developer

Ветка feat/run-state-rn1, worktree `Inspector_bottles--lane-F-rn1`. Не коммитил, `git add` не делал.

## Что сделано (по файлам)
- `telemetry_readmodel_module/node_read.py` (новый, только stdlib): `assemble_leaves` (перенос `_assemble`), `node_from_snapshot` (тело `read_node` после снимка; пустой путь -> `(False, None)`).
- `telemetry_read_model.py`: `read_node` (пустой путь до `snapshot`, затем один `snapshot(path)`), импорт `from .node_read import node_from_snapshot`.
- `interfaces.py`: строка `read_node` в `ITelemetryReadModel`; в докстроке «лока у модуля нет, держит вызывающий».
- `__init__.py`: экспорт `assemble_leaves`, `node_from_snapshot` (+ строка в докстроке модуля).
- `telemetry_view_model.py`: `get_node(path, default=None)`; `get` не менял.
- `io_debug_section.py::_replay_cached`: `getattr(read_model, "get_node", None)`, иначе прежний `get`; `try/except` на месте.
- `backend_ctl/_node_read.py`: `read_node` = лок + один `snapshot` + `node_from_snapshot` вне лока; реэкспорт `assemble_leaves as _assemble  # noqa: F401 — для driver.py:91`. `driver.py` не тронут.

## Прогоны (через gate; PYTHONPATH = корень worktree; `multiprocess_framework.__file__` лежит внутри worktree)
- радиус (telemetry_readmodel_module/tests, frontend_module/tests/state, test_p3r_node_read, test_replay_live_parity, test_p3r_replay_await, test_await_condition): 299 passed, 0 failed.
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/tests`: 626 passed, 0 failed.
- три файла test_rn1_*.py отдельно: 32 passed (31 красный стали зелёными + test_boundary_is_dot_not_prefix).
- `ruff check` и `ruff format --check` по 7 тронутым файлам: чисто.
- RED до кода отдельно не прогонял (тесты уже лежали в ветке; красноту подтверждает только отсутствие методов в диффе до правки).

## Другие читатели узла (только перечень, не тронуты)
`_telemetry_controls.py:275` (лист-метрика), `_panels.py:639,1138,1231` и `bindings.py:201` (`snapshot` + листья), `backend_ctl/driver.py:2310` (`_assemble` по процессам, через реэкспорт). Список взят из брief (OUT OF SCOPE); отдельным `git grep` не перепроверял.

## Что я оставил открытым / ненадёжным
- Инъекции (а)–(з) из бриф-предсказаний не гонял: «зелёное без красного под инъекцией» не доказано мной, это работа лида/reviewer.
- Реальную гонку `read_node` под внешним локом проверяет только контроль `test_red7_race…` (зелёный, но вероятностный); `test_race_under_external_lock` красен лишь по отсутствию метода.
- `read_node` в `backend_ctl` по-прежнему дедлочит при вызове под уже взятым `threading.Lock` (ловушка из брифа, не менял).
- Известные расхождения с живым `state.get` (пустой dict-узел, ключ с точкой) остались как зафиксированные литералы; README/DECISIONS — за docs-writer.
- Импорт `assemble_leaves as _assemble` в `backend_ctl/_node_read.py` держится только на `noqa: F401`; если кто-то уберёт его, `driver.py:91` упадёт.
