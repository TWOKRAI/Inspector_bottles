# C-79 — выжимка для слепого тестера

> Единственный вход тестера. Тестер работает в worktree от main `dcf7bc22c`, где брифа нет; лид передаёт этот текст
> в промпте. Как устроена правка, тестеру не известно и не проверяется.

## Что должно стать правдой

Когда рецепт задаёт и typed-поле `ProcessConfig`, и одноимённый ключ в `extras`, при расхождении пишется WARNING
«typed-поле перекрывает extras». Если значения совпадают, WARNING нет. NaN совпадает с NaN: на верхнем уровне и на любой
глубине `dict`, `list`, `tuple`. Всё остальное сравнение — как раньше.

## Обвязка

```python
from multiprocess_framework.modules.logger_module.adapters.std_facade import StdLoggerFacade
from multiprocess_framework.modules.process_manager_module.topology.blueprint import ProcessConfig

msgs: list[str] = []
monkeypatch.setattr(StdLoggerFacade, "warning", lambda self, msg, *a, **kw: msgs.append(str(msg)))
cfg = ProcessConfig(process_name="pc", process_class="m.C", source_target_fps=n1, extras={"source_target_fps": n2})
cfg.as_generic_config()
conflicts = [m for m in msgs if "перекрывает" in m]
```

Образец захвата — `multiprocess_framework/modules/process_module/tests/test_blueprint_extras.py:164-177`; `caplog` не годится.

**Разные объекты NaN:** `n1 = float("nan"); n2 = float("nan")`. `math.nan` — один объект, он маскирует дефект в контейнерах.

## Тесты (`multiprocess_framework/modules/process_manager_module/tests/test_blueprint_pick_nan_acceptance.py`)

Ожидаемые значения — литералы.

**`test_nan_in_both_no_conflict_warning`, parametrize, `len(conflicts) == 0`, на main 1 в каждом:**

| id | Ключ | typed | extras |
|---|---|---|---|
| `stop_window_s-distinct` | `stop_window_s` | `n1` | `n2` |
| `stop_window_s-same` | `stop_window_s` | `n1` | `n1` |
| `source_target_fps` | `source_target_fps` | `n1` | `n2` |
| `collector-nested` | `collector` | `{"mode":"x","w":n1}` | `{"mode":"x","w":n2}` |
| `io_peek-in-list` | `io_peek` | `{"a":[n1]}` | `{"a":[n2]}` |
| `stop_window_s-in-list` | `stop_window_s` | `[n1]` | `[n2]` |

Стражи (зелёные до и после):

- **`test_real_conflict_warning_text`** — `chain_targets=["typed"]`, `extras` `["extras"]`: ровно 1, текст дословно `ProcessConfig[pc]: typed-поле 'chain_targets'=['typed'] перекрывает extras['chain_targets']=['extras'] (typed-приоритет).`
- **`test_nan_against_number_is_conflict`** — `source_target_fps=30.0`, `extras` NaN: ровно 1, текст дословно `ProcessConfig[pc]: typed-поле 'source_target_fps'=30.0 перекрывает extras['source_target_fps']=nan (typed-приоритет).`; и обратный случай: typed NaN, `extras` 30.0: ровно 1.
- **`test_list_against_tuple_stays_conflict`** — `chain_targets=["a"]`, `extras` `("a",)`: ровно 1.
- **`test_equal_values_no_warning`** — parametrize: `source_target_fps` 30.0/30.0; `io_peek` `{"a":1}`/`{"a":1.0}`; `stop_window_s` 1/`True`; `chain_targets` `["a"]`/`["a"]`: 0.
- **`test_typed_value_wins_and_nan_passes_through`** — `source_target_fps=n1`, `extras` `n2`: `as_generic_config()` не бросает, значение `source_target_fps` в результате — NaN (`math.isnan`).

Команда (cwd и `PYTHONPATH` — корень worktree, основной `.venv`, без `uv sync`):
`bash "$(git rev-parse --path-format=absolute --git-common-dir)/../scripts/machine_gate.sh" light inspector-bottles-5e
<.venv python> -m pytest -q --tb=short multiprocess_framework/modules/process_manager_module/tests/test_blueprint_pick_nan_acceptance.py`

Python subprocess с `"bash"` уходит в WSL: при необходимости писать `C:/Program Files/Git/bin/bash.exe`.

## Запрещено читать

`plans/lifecycle-stop-ownership/tasks/C-79*.md` (кроме этой выжимки), строку C-79 в `plans/queue/defects.md`,
`plans/lifecycle-stop-ownership/tasks/T1.11_tests.md`; реализацию: тело `as_generic_config` и окружение в
`multiprocess_framework/modules/process_manager_module/topology/blueprint.py`. Можно: объявления полей `ProcessConfig` в том же файле, `process_module/tests/test_blueprint_extras.py`.
Не коммитить, не пушить.
