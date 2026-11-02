# C-64 — выжимка для слепого тестера

> Единственный вход тестера. Тестер работает в worktree от main `dcf7bc22c`, где брифа нет; лид передаёт этот текст
> в промпте. Как устроена правка, тестеру не известно и не проверяется.

## Что должно стать правдой

ProcessManager заводит провода командой `wire.setup` и показывает их статус наружу: ответ команды `wire.status`, пути
state `system.health.broken_wires` и `system.wires.<key>.status`.

После вызова `apply_topology`:

- если ни один процесс не тронут (отказ до исполнения команд или «изменений нет»), провод показывает тот статус, что был до вызова;
- если процессы пересозданы откатом, каждый из них получает `wire.configure` со своей ролью, провод снова `active`;
- пока переключение идёт, провод показан как `broken` (это прежнее поведение, оно остаётся).

## Обвязка (существующие тесты как образец)

- `multiprocess_framework/modules/process_manager_module/tests/conftest.py`: `make_pm({"cam": {"class": "x.Cam"}, "proc": {"class": "x.Proc"}})`, поверх него `pm.send_message = MagicMock()`.
- Провод: `pm._cmd_wire_setup(wire_key="cam->proc", source_process="cam", target_process="proc", transport="direct")`, ответ `success` True, статус `active`.
- Статус команды: `pm._cmd_wire_status()["wires"]["cam->proc"]["status"]`.
- Публикация монитора: настоящий `ProcessMonitor`, как `_monitor_with_wires` в `tests/test_wire_reissue.py:167-187`, но поверх `pm._active_wires` и `pm._process_registry`; вызов `monitor._publish_health({})`; смотреть захваченные `system.health.broken_wires` и `system.wires.cam->proc.status`.
- Отправки `wire.configure`: вызовы `pm.send_message` с `cmd["command"] == "wire.configure"`; адресат — первый аргумент, роль — `cmd["data"]["role"]`.
- Blueprint контроля и отказов: `{"processes": [{"process_name": "cam", "process_class": "x.Cam"}, {"process_name": "proc", "process_class": "x.Proc"}]}` (те же имена, иначе провод честно оборван).
- Входы отказа:
  - до команд: `pm._topology_manager.configure(commands_fn=<функция, бросает RuntimeError("BlueprintInvalid")>)`;
  - после части команд: `pm._topology_manager.configure(create_process_fn=<обёртка над pm._topology_create, бросает на 2-м вызове>)`; подмена `pm._topology_create` не сработает;
  - исключение: `pm._topology_manager.apply = MagicMock(side_effect=RuntimeError("outside apply"))`;
  - изменений нет: `pm._topology_manager.configure(diff_fn=lambda cur, new: {"has_changes": False})`.
- Выключатель: обёртка `pm.get_config`, как `tests/test_wire_reissue.py:116-123` (`wire_reissue_enabled` → False).

## Тесты (`multiprocess_framework/modules/process_manager_module/tests/test_wire_status_refused_switch_acceptance.py`)

Вход «до вызова» во всех: `wire.status` = `active`, `broken_wires` = 0 (кроме R5). Ожидаемые значения — литералы.

- **R1 `test_refused_before_commands_wire_stays_active`** — отказ до команд. Ждём: `success` False, `rolled_back` True; те же объекты процессов; `wire.status` `active`; `broken_wires` 0; `system.wires.cam->proc.status` `active`; `wire.configure` — 0. На main красный: `broken`, 1.
- **R2 `test_failed_create_rollback_reissues_wire`** — отказ на 2-м создании. Ждём: `success` False, `rolled_back` True; `active`, 0, `active`; `wire.configure` ровно 2: `cam` с ролью `sender`, `proc` с ролью `receiver`. На main красный: `broken`, 1, отправок нет.
- **R3 `test_exception_in_apply_rollback_reissues_wire`** — исключение. Те же ожидания, что R2. На main красный: то же.
- **R4 `test_no_changes_wire_stays_active`** — изменений нет. Ждём: `success` True, `applied` 0; `active`, 0, `active`; `wire.configure` — 0. На main красный: `broken`, 1.
- **R5 `test_refused_before_commands_keeps_pending_status`** — вход: статус провода перед вызовом задан тестом `pending` (`pm._active_wires["cam->proc"]["status"] = "pending"`), отказ до команд. Ждём: `wire.status` `pending`, `broken_wires` 0. На main красный: `broken`.
- **R6 `test_real_child_rollback_wire_returns`** — настоящие процессы: обвязка `running_rig`/`StopRig` из `tests/test_per_child_stop_window_acceptance.py:185-400`, команды `wire.setup` (`transport` `direct`), `topology.apply` с рецептом, в котором второй процесс задан непригодным классом, затем `wire.status`. Ждём: ответ `topology.apply` — `success` False; `wire.status` = `active` при опросе до 10,0 с. На main красный: `broken` на дедлайне. Вызов — в daemon-потоке с `join` и дедлайном. **Если обвязка не даёт такого входа — стоп и вопрос лиду, тест не подменять.**

Стражи (зелёные до и после):

- **S1 `test_successful_switch_reissues_wire`** — без инъекций: `success` True; `active`, 0; `wire.configure` ровно 2, адресаты `cam` и `proc`, порядок не проверять.
- **S2 `test_switch_window_reports_broken`** — `commands_fn` снимает `wire.status` и бросает: снятое значение `broken`.
- **S3 `test_reissue_disabled_rollback_sends_nothing`** — выключатель False, отказ на 2-м создании: статус `active` (без пометки), `wire.configure` — 0.

Команда (cwd и `PYTHONPATH` — корень worktree, основной `.venv`, без `uv sync`):
`bash "$(git rev-parse --path-format=absolute --git-common-dir)/../scripts/machine_gate.sh" light inspector-bottles-5e
<.venv python> -m pytest -q --tb=short multiprocess_framework/modules/process_manager_module/tests/test_wire_status_refused_switch_acceptance.py`

Python subprocess с `"bash"` уходит в WSL: при необходимости писать `C:/Program Files/Git/bin/bash.exe`.

## Запрещено читать

`plans/lifecycle-stop-ownership/tasks/C-64*.md` (кроме этой выжимки), `plans/lifecycle-stop-ownership/reports/C-64*`,
строку C-64 в `plans/queue/defects.md`; реализацию: `process_manager_module/process/process_manager_process.py`,
`process_manager_module/process/topology_manager.py`. Можно: `process_manager_module/tests/**`, `process_manager_module/README.md`, ADR-PMM-012 в `process_manager_module/DECISIONS.md`.
Не коммитить, не пушить.
