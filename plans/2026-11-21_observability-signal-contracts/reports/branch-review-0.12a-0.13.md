APPROVED — ветковое ревью Opus, 0.12a + 0.12b + 0.13 (refactor/observability-signal-contracts, e1cd3f85e..ed1ccacc2); текст сохранён лидом (у роли нет Write)

Дефектов кода, блокирующих слияние, нет. Три задачи сошлись: все клиенты порта управления читают токен, сервер закрыт без токена и в окне «порт слушает, токена нет» отказывает; тесты радиуса зелёные, единственный красный — такой же на main.

## Прогоны (через machine_gate, inspector-bottles-95)
- `backend_ctl/tests` без `--backend-live`: 1049 passed, 72 skipped.
- `multiprocess_prototype/backend/tests` + `Services/robot_comm/tests`: 1 failed, 2072 passed, 23 skipped, 2 xpassed; красный `test_e2e_rig_v2.py::test_rig_restart_retries_until_port_free` (Errno 48) — красный и на main (e1cd3f85e).
- `router_module/tests`: 789 passed. endpoint + process_manager_process: 55 passed. `validate.py` чисто; `sentrux check .` — 43 правила, все зелёные; `ruff check`/`format --check` по 13 `.py` чисто; `secrets_audit` — 0 находок; `~/.multiprocess_framework` до и после — пустой каталог `drwx------`.
- Собственное воспроизведение на настоящих `setup_backend_ctl_channel` и `BackendDriver`: файл токена 0600, каталог 0700; драйвер проходит `hello`; сырой `system.shutdown` → `auth_required` + EOF (система не остановилась); неверный токен → `TokenRejected` (`OSError`), токена нет во всей цепочке исключений; нет файла → `TokenFileMissing`; teardown удаляет свой файл; в журнале токена нет.

## Потребители порта
Через `BackendDriver`/`_TransportMixin` с токеном: `harness.py`, `mcp_driver_session.py`, `recorder.py`, `dump_capabilities.py`, `run_alpha.py`, все `backend_ctl/probes/*`, `stand_gate`, `capacity_bench` (через `BackendHarness`, env ставит сам). `run_sim_all.ps1` — `BACKEND_CTL=1` обоим портам. `SocketClient(` вне тестов один — `line_source.py` с `file_token_provider`. Ломается только простой старт без `BACKEND_CTL=1` (так и задумано; единственная команда без env в документах — находка 1). Golden: ровно 4 строки `enabled true→false`. Запрещённых файлов в диффе нет (39 путей).

## Находки
1. [важная, не блокирует] `backend_ctl/AGENTS.md:90` — запуск без `BACKEND_CTL=1` при `enabled: false` даёт «Connection refused». Исправлено лидом.
2. [nit] `backend_ctl/README.md:39,48` — ярлыки способов (a)/(b) наоборот относительно ADR-PMM-052 п. 3. Исправлено лидом.
3. [nit] `docs/claude/memory/reference_qt_mcp_launch.md:17–18` — флуд `bad line skipped` с токеном больше не WARNING; «8765 нет в LISTENING» без `BACKEND_CTL=1` ложно. Исправлено лидом.
4. [nit] ADR-PMM-052 п. 5 называл два условия отключения изоляции, в коде три (ещё `harness_smoke`) — исправлено; обратная ссылка из ADR-RTR-017 — в `OPEN_QUESTIONS` (файл вне границы).
5. [nit] `socket_auth.py:55–57` — относительный `BACKEND_CTL_TOKEN_FILE` принимается как есть — `OPEN_QUESTIONS`.
6. [nit] `probe…:1972` — при `pm_pid=None` защита ПМ только по имени цели; на стенде цель `processor` — отдельный процесс — `OPEN_QUESTIONS`.
7. [nit, до ветки] `mcp_driver_session.py:425` — подсказка «Подними систему» для `TokenRejected` — `OPEN_QUESTIONS`.

## Что оставил открытым / ненадёжно
- Живой стенд, `--backend-live`, `-m harness_smoke` не запускались; строки 0.12b и SF1 — по `tasks/0.13.result.md`.
- Полный `process_manager_module/tests` не гонялся (macOS, C-93); Windows не проверялся.
- Входит ли ПМ в `supervision_status.processes` на живом стенде — не проверено.
- Инъекции не повторялись; `except BackendUnavailable` искали только по `backend_ctl/` и `scripts/`.
- Изоляция HOME вне `backend_ctl/tests` и `process_manager_module/tests` не закрыта (`OPEN_QUESTIONS`).
