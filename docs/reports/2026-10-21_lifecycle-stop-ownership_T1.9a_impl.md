# T1.9a — реализация: KeyedExecutor и развилка в CommandManager (teamlead)

**Дата:** 2026-10-21 · **Ветка:** `feat/lifecycle-keyed-executor` (worktree `keyed-exec-1.9a`) · **База:** `baf5569dd`
(слепые тесты) · **Бриф:** `plans/lifecycle-stop-ownership/tasks/T1.9a.md` (D1–D5) + решения лида (1)–(4).

## SHA

| Коммит | Что |
|---|---|
| `c8ea79a34` | код + hazard/контрактные тесты + README + строка карты |
| коммит с этим отчётом (следующий за `c8ea79a34`, HEAD ветки) | ADR (WRK-005, CMD-006, RTR-015), `multiprocess_framework/DECISIONS.md` (sync), правка H6, этот отчёт |

Предпроверка пути импорта (cwd = `multiprocess_framework/modules`, `PYTHONPATH=<worktree>`):
`python -c "import multiprocess_framework as m; print(m.__file__)"` →
`D:\PROJECT_INNOTECH\Inspector_vision\Inspector_bottles\.claude\worktrees\keyed-exec-1.9a\multiprocess_framework\__init__.py`.

## Тесты R / H

Команда (из `multiprocess_framework/modules`, через гейт, сессия `inspector-bottles-48`):
`machine_gate.sh light inspector-bottles-48 <python> -m pytest -q --tb=short <файл>`.

| Тест | Файл | Статус | Какая инъекция делает красным (проверено прогоном) |
|---|---|---|---|
| R1, R2, R2b, R3, R4, R5, R6, R11, R12, R12b | `worker_module/tests/test_keyed_executor_acceptance.py` | 10 passed (было 10 red) | матрица И1–И12 — у лида |
| R7, R8, R9, R10, R13 | `command_module/tests/test_command_executor_fork_acceptance.py` | 5 passed | матрица И1–И12 — у лида |
| H1a | `worker_module/tests/test_keyed_executor_hazards.py` | passed | J-H1a «правило повторного входа выключено» → RED (`:128` вложенная вернула True) |
| H1b | то же | passed | J-H1b «повторный вход на месте при любом ключе» → RED (`:153`); по прогнозу брифа — и И2 |
| H2 | то же | passed | J-H2 = И5 «`request_stop` не снимает очередь» → RED (`:191` ждущие без ответа) |
| H5 | то же | passed | J-H5 «`_deliver` не ловит исключение `reply`» → RED (`:221`) |
| H7 | то же | passed | J-H7 «лок держится поверх `action`» → RED (`:269`, submit ждал 1.004 с) |
| H3 | `command_module/tests/test_command_executor_fork_hazards.py` | passed | J-H3 = И10 «длительность при подаче (0)» → RED (`:230`, 0.000 с) |
| H4 | то же | passed | J-H4 «`action` зовёт обработчик мимо `dispatcher.dispatch`» → RED (`:261`, конверт отличается) |
| H6 | то же | passed | J-H6 «CM исполняет на месте и при `reply`» → RED (p99 1010.7 мс против 0.1 мс). Первая редакция H6 под этой инъекцией была ЗЕЛЁНОЙ (нагрузка шла до замера) — исправлено: тяжёлая команда кладётся в ту же очередь перед простой каждые 25 итераций |
| контракт worker (10 тестов) | `test_keyed_executor_hazards.py` | passed | — (контракт D1: протокол, SYSTEM-воркеры, `ValueError` на занятое имя, `pause_all`, `stop_all_workers`, `should_reject` без защёлки и с исключением, WARNING busy раз на эпизод, `None` против новых ключей, имя логгера) |
| контракт command/router (10 тестов) | `test_command_executor_fork_hazards.py` | passed | — (строки в `metadata`, отказ `key_from`/`targets` без `executor`, `DEFERRED` + один `reply`, `targets="all"`, `overwrite_command`, стёртая `metadata.executor` через роутер, `key_missing` через роутер, отказ исполнителя через роутер, `DEFERRED` при copy, сигнатура `reply` keyword-only) |

Матрица J-H — скрипт вне дерева (`scratchpad/inject_h.py`): правка якоря → один тест → `git checkout` файла; итог
`git status` после матрицы — чисто (кроме собственной правки H6 до коммита).

## Радиус (класс medium, по каталогу)

Команда: `machine_gate.sh medium inspector-bottles-48 <python> -m pytest -q --tb=short -p no:warnings <каталог>`;
прогон после правки H6 (то есть на итоговом коде и тестах).

| Каталог | cwd | Итог |
|---|---|---|
| `router_module/tests` | `multiprocess_framework/modules` | exit 0 — 724 passed |
| `command_module/tests` | то же | exit 0 — 64 passed (с R7–R13 и H3/H4/H6 + контракт) |
| `worker_module/tests` | то же | exit 0 — 96 passed (с R1–R12b и H1a/H1b/H2/H5/H7 + контракт) |
| `process_manager_module/tests` | то же | exit 0 — 1229 passed, 32 skipped (тесты ADR-PMM-024 без правок) |
| `console_module/tests` | то же | exit 0 — 105 passed |
| `frontend_module/tests` | то же | exit 0 — 658 passed, 1 skipped |
| `backend_ctl/tests` | корень репозитория (в `modules` такого каталога нет — первая попытка дала exit 4 «not found») | exit 0 — 797 passed, 70 skipped |
| `Services/robot_comm/tests` | корень репозитория | **exit 75 — NO WINDOW** (`NO WINDOW — skipped (machine_gate: medium, inspector-bottles-48)`); не прогнан, повтор не делал |

Красных нет: доказывать пред-существование на `c9c66a4d4` было нечего.

## ruff / validate / sync

- `ruff check -q` и `ruff format --check` на 8 тронутых .py — 0 замечаний, «8 files already formatted».
- `python -m scripts.sync` — exit 0, записан `multiprocess_framework/DECISIONS.md`.
- `python scripts/validate.py` — exit 1, 106 `[OK]`, 3 `[FAIL]`:
  `память: ошибки тегов или проверка не запустилась`; `память: индекс BY-MODULE*.md устарел или проверка не
  запустилась`; `G6 R1 Services/code_reader/tools/thread_split_probe.py:210`. Ни один путь не тронут этой веткой:
  `git diff --stat c9c66a4d4 -- Services docs/claude/memory` — пусто. На `c9c66a4d4` validate не перезапускал
  (нет второго дерева) — доказательство косвенное. C-13 по имени в выводе нет.
- Хук `doc-size-guard`: `router_module/DECISIONS.md` 51.4 КБ при бюджете 32 КБ (был велик и до ADR-RTR-015; +1.9 КБ).

## Отклонения от DESIGN (каждое с причиной)

1. **Критерий «сигнатуры только расширены» срабатывает буквально.** `git diff main -- command_manager.py
   interfaces.py | grep -E '^-\s+def (register_command|handle_command)'` выдаёт 2 строки
   `-    def handle_command(self, message: Dict) -> Any:` — строку `def` нельзя расширить, не изменив её. Прежние
   параметры и умолчания не изменены (добавлен только keyword-only `reply=None`); `register_command` не сработал
   (многострочная сигнатура). **По плану — предупредить координатора до слияния.**
2. **Дополнительный отказ регистрации:** `key_from` / `targets` без `executor` → `False` + WARNING (в списке D3 нет).
   Причина: иначе опечатка «забыл executor» дала бы молча синхронную команду. Плюс `executor` без метода `submit` и
   `key_from` не непустая строка → отказ.
3. **Повторный вход учитывает и `inline_if_idle`:** thread-local ключ ставится на время любого `action` этого
   исполнителя, не только на рабочем. Причина: вложенная из операции, исполненной на месте, иначе встала бы в очередь
   за собственным родителем — тот же порядок, но лишняя постановка. Записано в ADR-WRK-005.
4. **`reply` зовётся до снятия ключей операции** (D1 этого не задаёт). Причина: ответы операций с пересекающимися
   ключами уходят в порядке подачи. Цена: медленный `reply` держит ключ.
5. **`should_reject` рабочим:** рабочий видит исполнимую запись → зовёт `should_reject` вне лока → берёт запись под
   локом (или снимает очередь). Запись между проверкой и взятием может смениться — проверка относится к «следующей
   взятой», не к конкретной.
6. **`DEFERRED` импортируется локально внутри `_dispatch_command`** (только в ветке исполнителя), не в шапке
   `router_manager.py` — бриф запрещает правки вне `_dispatch_command`.
7. Ключ `key_missing` пишет и метрику `command_manager.command.execution.errors` (D3 метрику не называет).

## Что осталось открытым

- `Services/robot_comm/tests` не прогнан (гейт: NO WINDOW) — нужен прогон в окне лида.
- В первом коммите `c8ea79a34` хук сообщений выдал два предупреждения (не блок): тема 103 символа (> 100) и абзац,
  начатый с `CommandManager:`, распознан как неизвестный трейлер.
- Матрицу И1–И12 по брифу не прогонял (это шаг лида); J-H выше — только для моих hazard-тестов.
- Тайминговые тесты (R2 ≤ 0,8 с, R2b ≤ 0,3 с, R6 ≤ 0,05 с, H2 ≤ срок + 0,1 с, H7 ≤ 0,05 с) прогнаны по одному разу на
  ненагруженной машине; под нагрузкой соседей возможна ложная краснота. Повторную серию не запускал.
- validate: 3 FAIL вне ветки не перепроверены на `c9c66a4d4` запуском (см. выше).
- Строка `executor` в `metadata` для объекта без `name` — имя типа (`StubExecutor`); два исполнителя одного типа без
  имени неразличимы в карточке. Для `KeyedExecutor` имя есть всегда.
- `join_until` без предшествующего `request_stop` всегда вернёт `False` к сроку (рабочие постоянные) — по контракту
  `Stoppable` так и задумано, но вызывающий 1.9b должен звать `shutdown`, а не голый `join_until`.
- `stop_all_workers` фреймворка ждёт рабочего, пока тот исполняет текущую операцию; операция, не опрашивающая
  событие, задержит выключение `WorkerManager` до его таймаута (5 с). Опрос события — дело `action` (1.9b D4).
- `ADR-CMD-005` («async-расширение не планируется») не правил — уточнение записано в ADR-CMD-006.

## Раунд 2 ревью

Ревью р.1 (Sonnet) — CHANGES REQUESTED, 6 пунктов. Правки — коммит `3eb70c98f` до rebase, `510af2ead` после rebase
на локальный `main` (без конфликтов). SHA ветки после rebase: `4abf942d0` (слепые тесты), `1ee00f9ea` (код),
`be5a9b035` (ADR), `15ac6858d` / `d9c851b7c` (матрица инъекций, лид), `510af2ead` (правки р.1).

| # | Замечание | Правка | Тест → итог |
|---|---|---|---|
| 1 | `_execute` / `_worker_loop` ловят только `Exception`: `SystemExit` в `action` — 0 ответов, рабочий потерян | `_execute`: `except BaseException` → `reply` ровно раз `"<тип>: <текст>"`, затем `raise`; `_worker_loop` `finally`: выход не по закрытию → `request_stop()` ДО снятия счётчика живых | `test_h8_system_exit_in_action_replies_once_and_closes_executor` — passed; на коде `8e7cf6a7a` — RED (`:466` «после SystemExit ответы не пришли за 2 с») |
| 2 | `should_reject` не опрашивался, пока рабочий ждёт занятого ключа | рабочий на каждом пробуждении (`0,1 с`) при непустой очереди зовёт `should_reject` вне лока, даже если ничего не исполнимо; без защёлки | `test_h9_should_reject_drains_queue_while_key_is_busy` — passed; на `8e7cf6a7a` — RED (`:492` «ждущая за занятым ключом не снята») |
| 3 | отказ исполнителя без метрики | CM оборачивает `reply`: если `action` не стартовала — `_finish_command` как ошибка (WARNING + `errors`), длительность не пишется (`duration=None`) | `test_contract_executor_refusal_counts_as_command_error` — passed; красный на старом коде не проверял запуском (метрики там не было по построению) |
| 4 | имя занято после `shutdown` | строка в README `worker_module` и в ADR-WRK-005 | — (документ) |
| 5 | страж логгера: голый `getLogger` в `keyed_executor.py:127` | `get_std_logger("worker", fallback_name="multiprocess_framework.worker_module.keyed_executor.<name>")`; WHITELIST не тронут | `logger_module/tests/test_std_logger_guard.py` — passed после rebase (до rebase оставался чужой хит `Services/robot_comm/gui/line_source.py:45`, на `main` исправлен); `test_contract_default_logger_name` — passed (имя stdlib-логгера то же) |
| 6 | тест с «without_reply» в имени не звал без `reply` | добавлена точка: вызов без `reply` → dict обработчика, не `DEFERRED` | `test_contract_deferred_with_reply_delivers_once_and_never_returns_deferred_without_reply` — passed |

Документы: README `worker_module` (`should_reject`, `BaseException`, имя после `shutdown`, логгер), ADR-WRK-005
(те же пункты), ADR-CMD-006 (отказ как ошибка). `python -m scripts.sync` после rebase — изменений нет.

Прогоны после rebase (cwd `multiprocess_framework/modules`, предпроверка импорта — путь внутри worktree):
- light: 4 файла R/H + `logger_module/tests/test_std_logger_guard.py` — 112 passed, 2 skipped, exit 0.
- medium: `worker_module/tests` — 98 passed; `command_module/tests` — 65 passed; `router_module/tests` — 724 passed.

Матрица инъекций: якоря И7 и И10 в `scratchpad/inject_matrix.py` обновлены под правку п.3 (обёртка
`counted_reply`); все 12 якорей найдены ровно один раз на `510af2ead`. `ROOT` скрипта лид перенаправил на worktree
`keyed-exec-1.9a-inj` — там код до правок р.1: прогон матрицы на новом коде требует перевести то дерево на `510af2ead`.

Открыто после р.2:
- При `serial=True` (один рабочий) очередь по `should_reject` снимается только после текущей операции — рабочий занят.
- Отказ через `counted_reply` после `BaseException` в `action` (`ran=True`) не проходит `_finish_command` — метрики
  такого исхода нет.
- Хук сообщений коммита — предупреждения (тема > 72, абзацы «KeyedExecutor:» / «CommandManager:» как трейлеры).

## Ревью ветки

Ревью ветки (Opus) — CHANGES REQUESTED, два блокера. База — `1996a8799` (коммит лида: счётчик живых в `finally`
`_worker_loop`, `reply(r)` в `finally` внутри `counted_reply`).

| # | Замечание | Правка | Тест |
|---|---|---|---|
| 1 | `_reject_all` останавливался на первой `BaseException` из `reply`: снятые записи после неё без ответа (наблюдалось die=1 q1=1 q2=0 q3=0) | отказ доставляется каждой записи; первая `BaseException` запоминается и пробрасывается после цикла; `Exception` — прежний `log.error` в `_deliver` | H10 |
| 2 | тестов на `1996a8799` и п.1 не было | H10 `test_h10_base_exception_in_reply_during_drain_still_answers_every_waiting_op`; H11 `test_h11_refusal_reaches_initiator_even_if_outcome_accounting_fails` (сбой учёта моделируется подменой `_finish_command`: слоты stats/logger глотают сбои сами в `_call_manager`) | см. ниже |
| 3 | ADR-WRK-005 | строка: «`reply` ровно раз» держится и при `BaseException` из `reply` во время снятия очереди | — |

Доказательство красного (скрипт `scratchpad/redproof.py`: подмена файла → один тест → восстановление из копии):
- H10 на текущем коде — passed; на `keyed_executor.py` из `6bae649f9` — RED (`:528` «ответов по операциям:
  {'die': 1, 'q1': 1, 'q2': 0, 'q3': 0}»); только п.1 откатан — RED (то же); только счётчик живых из `1996a8799`
  откатан (п.1 оставлен) — RED (`:530` «join_until не дождался рабочего — счётчик живых не снят»).
- H11 на текущем коде — passed; только `finally` в `counted_reply` откатан — RED (`:523` «ответы инициатору: []»).

Прогоны: light — 4 файла R/H + страж логгера: 114 passed, 2 skipped. medium `worker_module/tests` и
`command_module/tests` — **exit 75, NO WINDOW** (гейт), не прогнаны. ruff — чисто; `scripts.sync` — без изменений
индекса; `validate.py` — exit 0.
