# CTO (Fable), раунд 2, 2026-10-20 — D1a (развилка в CommandManager) и инструменты фреймворка

Вердикт: **ACCEPT WITH CONDITIONS** по D1a (черновик T1.9 на `4b123bac3`). Записал лид из отчёта CTO; в репо CTO ничего не писал.

## D1a принят
Развилку делает `CommandManager`, ключ берёт приёмник из сообщения по регистрации. Правильнее варианта с роутером:
`handle_command` (`command_manager.py:262-317`) — единственный, кто знает регистрацию и вызов обработчика
(`dispatcher.dispatch(message, key_field="command", data_field="data")`, `:293`). Роутер остаётся транспортом и разбором.
В `command_module` нет ни одного потока — исполнитель туда не кладём, только развилку.

## Три обязательные правки текста D1a/D2 (стадия 0)
1. **Как `reply` попадает в CM:** `handle_command(message, *, reply=None)` — новый необязательный kwarg. Есть исполнитель →
   CM строит `action = lambda: dispatcher.dispatch(...)`, зовёт `executor.submit(action, key, reply)`, возвращает сентинел
   `DEFERRED`; роутер при `DEFERRED` авто-ответ пропускает (рядом с `manages_own_reply`, `router_manager.py:1362`). Вызов без
   `reply` у команды с исполнителем — исполнение на месте + один WARNING на имя команды. Обе двери передают `reply`: прямая —
   роутер (`reply_to_request(processed, r, success=_result_is_success(r))`); вложенная `process.command`
   (`process_manager_process.py:3297`) — свой `reply` с `response_command="process.command.response"`.
2. **D2 противоречит D1a** («решение принимает роутер») — переписать под D1a; в роутере ~5 строк (передать `reply`, узнать `DEFERRED`).
3. **Нет поля ключа — громкий отказ** `{"success": False, "error": "key_missing"}`, не `key=None`; `None` — только через `targets="all"`.

## Риски
(а) `DEFERRED` утечёт к синхронному вызывающему (`_handle_process_command`, тесты CM, консоль) — страж-тест «без `reply`
никогда не `DEFERRED`». (б) Метрика длительности `:287-316` станет мерить подачу — обернуть `action`. (в) Middleware приёма
идёт до развилки (`router_manager.py:1451`) — `receive_time` = снятие трубки; документировать. (г) `manages_own_reply` не
трогать: с исполнителем — `reply`-no-op. (д) `submit` с потока исполнителя — на месте (H2).

## Что уже есть (переиспользовать, не писать второе)
| Инструмент | file:line | Вердикт |
|---|---|---|
| `_run_when_child_ready` / `_drain_child_actions` (ADR-PMM-024) | `process_manager_process.py:1499-1594` | **обобщить → ядро KeyedExecutor**; не хватает потолка, reply ровно раз, shutdown + join, ключей-множеств, владельца потока |
| `WorkerManager` / `WorkerLifecycle` | `worker_manager.py:26, 75, 99, 228` | переиспользовать для потоков (как `ProcessMonitor`, `process_monitor.py:195`) |
| `Stoppable` / `Scope` | `base_manager/interfaces.py:252-304`; `lifetime.py:281, 661, 897` | переиспользовать как контракт `shutdown` = `request_stop()` + `join_until(deadline)` |
| `register_command` / `handle_command` / `update_command_metadata` | `command_manager.py:166, 262, 389` | переиспользовать + расширить: `reply`, `DEFERRED`, реестр исполнителей вне `metadata`, `key_from` |
| `reply_to_request` | `router_manager.py:1274` | переиспользовать как `reply` |
| `WorkerPoolExecutor`, `WorkerPoolDispatcher`, `DataReceiver`, `_sender`, `async_sender_buffer` | — | не годятся (без ключей / data-plane / транспорт, Task 3.3) |

## Дубли «очередь + поток» — свести к KeyedExecutor (FREEZE, не KILL)
1. `_run_when_child_ready` / `_drain_child_actions` — в самой 1.9; старые методы — тонкие обёртки, тесты ADR-PMM-024 без правок.
2. `ServiceHost._cmd_start` (`service_module/host.py:59, 143-151`): поток на старт, `pending` через 0,2 с, без join — отдельная задача после 1.9, полоса Services.
3. Дверь сокета ADR-RTR-012 (поток на запрос под потолком) — только если всплывут порядок/потолок.
Не дубли: `pump_inbound` / `stop_wait_idle` (страховка, О2), `QueueChannel.start_listening` (де-факто заморожен), `ProcessMonitor`.

## Открыто (по CTO)
Сигнатуру и сентинел не прогонял; число вызывающих `handle_command` вне роутера — опись стадии 0; `Dispatcher.dispatch` при
исключении на потоке исполнителя — по докстрингу; влезет ли исполнитель в корень PM без правки `_own_work` (`:3539`) — не
проверено; `worker_lifecycle.py:260-275`, `host.py` `_run_start`, `socket_channel.py` — не прослежены; стенда нет.
