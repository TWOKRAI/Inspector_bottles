# Карта инструментов фреймворка для KeyedExecutor

Источник — вердикт CTO (Fable), раунд 2, 2026-10-20:
[`cto_round2_commandmanager.md`](../reports/2026-10-20_L-9-residual-evidence/cto_round2_commandmanager.md).
Владелец попросил эту таблицу запомнить: она — опись того, что уже есть, чтобы `worker_module/keyed_executor.py`
не стал вторым механизмом рядом с существующими. Потребитель — план
[`lifecycle-stop-ownership`](../../plans/lifecycle-stop-ownership.md), Task
[1.9a](../../plans/lifecycle-stop-ownership/tasks/T1.9a.md) и [1.9b](../../plans/lifecycle-stop-ownership/tasks/T1.9b.md).

**Ядро — `worker_module/keyed_executor.py`** (Task 1.9a, 2026-10-21; контракт — протокол `OrderedExecutor` в `worker_module/interfaces.py`, ADR-WRK-005).

Первые пять колонок перенесены из таблицы CTO дословно. «Проверено» — менеджер сверил каждую ссылку `file:line` с деревом
`37235a122` (код совпадает с `a5485097a`): по каждому номеру строки выведена сама строка (`sed -n`). Пути даны от
`multiprocess_framework/modules/`.

| Инструмент | file:line | Что умеет | Вердикт | Чего не хватает | Проверено | В какой задаче берётся |
|---|---|---|---|---|---|---|
| `_run_when_child_ready` / `_drain_child_actions` | `process_manager_process.py:1499-1594` | FIFO на ключ (deque), один daemon-поток на занятый ключ, `still_relevant` (поколения), перечитывание инкарнации | **обобщить → ядро KeyedExecutor** | потолок очереди, `reply` ровно раз, `shutdown(deadline)` + join, ключи-множества, владелец потока | да: `:1499 def _run_when_child_ready`, `:1569 def _drain_child_actions`, `:1594` — пустая строка перед `_run_child_action_after_ready` (`:1595`, до `:1675`), где живут ожидание готовности и `still_relevant` | 1.9a — ядро обобщается в `keyed_executor`; 1.9b — старые методы становятся тонкими обёртками |
| `WorkerManager` / `WorkerLifecycle` | `worker_manager.py:26, 75, 99, 228`; `worker_lifecycle.py:74, 126-163` | именованные daemon-потоки со stop_event, join по таймауту, общий дедлайн | **переиспользовать** для потоков исполнителя | ничего | да: `worker_module/core/worker_manager.py` `:26 class WorkerManager`, `:75 create_worker`, `:99 stop_worker`, `:228 stop_all_workers`; `worker_module/lifecycle/worker_lifecycle.py` `:74 threading.Thread(`, `:126 stop_worker`, `:163` — WARNING «не остановился за …с (таймаут join)» | 1.9a — потоки исполнителя |
| `Stoppable` / `Scope` / `open_scope` | `base_manager/interfaces.py:252-304`; `lifetime.py:281, 661, 897` | `request_stop` + `join_until(deadline)`, владение и бюджет закрытия | **переиспользовать** как контракт `shutdown` | ничего | да: `base_manager/interfaces.py:252 class Stoppable(Protocol)` (`:304` — конец блока); `base_manager/core/lifetime.py` `:281 class Scope`, `:661 def close(…, deadline=…)`, `:897 def open_scope(` | 1.9a — контракт `shutdown`; 1.9b — запись исполнителя в корне PM |
| `CommandManager.register_command` / `handle_command` / `get_command_info` / `update_command_metadata` | `command_manager.py:166, 262, 365, 389` | регистрация с метаданными, вызов через диспетчер, экспорт info | **переиспользовать + расширить** (развилка D1a) | kwarg `reply`, сентинел `DEFERRED`, реестр исполнителей вне `metadata`, `key_from` | да: `command_module/core/command_manager.py` `:166 register_command(`, `:262 handle_command(self, message)`, `:365 get_command_info`, `:389 update_command_metadata`; вызов обработчика — `:293 dispatcher.dispatch(…)`, метрика длительности — `:287-316` | 1.9a |
| `reply_to_request` | `router_manager.py:1274` | ответ с любого потока, самоответ локально (ADR-RTR-013) | **переиспользовать** как `reply` | ничего | да: `router_module/core/router_manager.py:1274 def reply_to_request(`; авто-ответ — `:1362` | 1.9a — `reply` прямой двери; 1.9b — `reply` двери `process.command` |
| `request_async` / `_PendingRequest` / `_expire_async_pending` | `router_manager.py:80, 1139, 1221` | клиентская сторона отложенного ответа | не часть исполнителя; без правок | — | да: `:80 class _PendingRequest`, `:1139 def request_async(`, `:1221 def _expire_async_pending` | не берётся |
| `WorkerPoolExecutor` / `_PoolTask` | `worker_pool_executor.py:110, 57, 301, 177-203` | пул N, одна общая безразмерная очередь, слив без дедлайна | **не годится** (нет ключей; план кадров) | — | да: `chain_module/thread_pool/worker_pool_executor.py` `:110 class WorkerPoolExecutor`, `:57 class _PoolTask`, `:301 def submit(`, `:177 _stop_workers` … `:203 remove_worker` | не берётся |
| `WorkerPoolDispatcher` | `chain_module/worker_pool/dispatcher.py:35` | маршрутизация в рабочие процессы, своих потоков нет | не годится | — | да: `:35 class WorkerPoolDispatcher` | не берётся |
| `ServiceHost` | `service_module/host.py:59, 143-151` | поток на старт, pending-ответ через 0,2 с | **кандидат на сведение №2** | join, порядок, потолок | да: `:59 class ServiceHost`, `:143 threading.Thread(`, `:151 return {…, "pending": True}` | отдельная задача после 1.9b, полоса Services |
| `ProcessMonitor` | `process_monitor.py:73, 195, 205, 1475-1511` | один worker через WorkerManager; рестарты шлёт командой в очередь PM | образец владения потоком; без правок | — | да: `process_manager_module/monitor/process_monitor.py` `:73 class ProcessMonitor`, `:195 create_worker(`, `:205 def stop(`, `:1475 def _dispatch_due_restarts`, `:1511 comm.send_message(` | образец для 1.9a; в 1.9b — только докстринг `:1476-1481` |
| `DataReceiver` + `_chain_queue` | `data_receiver.py:426`; `generic_process.py:263, 307-312` | data-plane, ограниченная очередь с бэкпрешером | **не трогать** | — | да: `process_module/generic/data_receiver.py:426 def run_loop(`; `process_module/generic/generic_process.py` `:263 _chain_queue = queue.Queue(maxsize=…)`, `:307-312 create_worker(…)` | не берётся |
| `_sender` / `async_sender_buffer` / `QueueChannel._listen_loop` | `_sender.py:66-86`; `async_sender_buffer.py:67-89`; `queue_channel.py:143-209` | отправители/слушатель транспорта | не дубли исполнителя (Task 3.3) | — | да: `router_module/core/_sender.py` `:66 PriorityQueue(maxsize=…)`, `:86 threading.Thread(`; файл `async_sender_buffer.py` лежит в `channel_routing_module/buffers/` (`:67`, `:89` — то же); `router_module/channels/queue_channel.py` `:143 def start_listening(`, `:209 time.sleep(1.0)` | не берётся |

## Дубли к сведению (FREEZE, не KILL)

1. `_run_when_child_ready` / `_drain_child_actions` (ADR-PMM-024) — сводится в **1.9b**: старые методы остаются
   тонкими обёртками над `KeyedExecutor`, тесты ADR-PMM-024 — без правок.
2. `ServiceHost._cmd_start` (`service_module/host.py:59, 143-151`: поток на старт, `pending` через 0,2 с, без join) —
   **отдельная задача после 1.9b, полоса Services**.
3. Дверь сокета ADR-RTR-012 (поток на запрос под потолком) — **по триггеру**: только если всплывут порядок или потолок.

## Не дубли

- `pump_inbound` / `stop_wait_idle` — страховка (решение CTO по О2), заморожены; не исполнитель.
- `QueueChannel.start_listening` — де-факто заморожен, слушатель транспорта.
- `ProcessMonitor` — один свой поток через `WorkerManager`; образец владения, не очередь команд.

## Что не проверено

- Ссылки проверены только по номеру строки (что на ней стоит). Поведение («слив без дедлайна», «бэкпрешер»,
  «де-факто заморожен») — со слов CTO, не по прогону.
- `worker_lifecycle.py:260-275`, `host.py` `_run_start` и `socket_channel.py` CTO не проследил; менеджер тоже.
