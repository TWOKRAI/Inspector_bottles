# Plan: `WorkerManager.start_worker` не врёт «запущен» без нового потока (C-91)

- **Slug:** worker-start-honest
- **Дата:** 2026-11-16
- **Статус:** DRAFT (стадия 0, раунд 1: CHANGES REQUESTED — внесено 2026-11-16; слепой tester дальше)
- **Ветка:** `fix/worker-start-honest`
- **Полоса:** Д (дефекты). Дефект: `plans/queue/defects.md` C-91 (номер предварительный: на 2026-11-16 в `main` записи нет, сверить перед слиянием).
- **Модуль:** `multiprocess_framework/modules/worker_module` (framework, принципы 1 и 2: чиним улучшением, функциональность не удаляем).
- **Стадия 0:** [`docs/reviews/2026-11-16_task-c91-1.1-stage0.md`](../../docs/reviews/2026-11-16_task-c91-1.1-stage0.md).

## Контекст

`WorkerLifecycle.start_worker` (`lifecycle/worker_lifecycle.py:90-122`) возвращает `True` и не создаёт нового потока в двух ветках:
- `status == RUNNING` (`:97-98`), в том числе когда `stop_event` уже взведён;
- `thread.is_alive()` (`:100` → `:122`), в том числе когда прежний поток уже получил `stop_event` и умирает (статус `STOPPING`).

Вторая ветка — потерянный старт: вызывающий считает воркер запущенным, прежний поток доработает по `stop_event`, и воркер не работает, статус `STOPPED`.
Дефект найден по чтению, на 1500 повторах не воспроизведён (окно мало): тесты ниже выстраивают состояние детерминированно.
Поток-владелец камер (`Services/camera_device/session.py:319-340`, `_launch_owner`) обходит дефект ожиданием выхода прежнего потока (`prev.join(watchdog_s)`) и трактует `False` как «воркер владельца не запущен».
Упростить обход может только лид полосы К после слияния; здесь `Services/**` не трогаем.

Статусы `WorkerStatus` (`types/types.py:31-35`): STOPPED, RUNNING, ERROR, STOPPING, COMPLETED (пять; PAUSED/CREATED нет; пауза — `pause_event` при RUNNING; начальный статус STOPPED).

**H2 (второй дефект того же класса, по чтению верен, достижимость в production не доказана).** `_worker_wrapper.finally` при ошибке цели с `restart_on_failure` спит 0,1 с, затем `_restart_worker_internal` (`:252-275`)
создаёт НОВЫЙ поток с НОВЫМ `stop_event`, игнорируя запрос остановки. Если `stop_worker` пришёл в окно сна: STOPPING, `E1.set()`, `join(T1)` → T1 просыпается, создаёт T2 с `E2` (не взведён), `stop_worker` видит T1 мёртвым,
пишет `STOPPED` и возвращает `True`, а T2 живёт. `restart_on_failure=True` вне тестов в `.py` не найден (YAML/JSON не проверяли).
Также `stop_worker` читает `stop_event` (`:143`) и поток (`:149`) раздельно; два параллельных `start_worker` без замка могут создать два живых потока.

## Цель

Контракт `start_worker`: возврат `True` означает «на момент возврата жив ровно один поток этого воркера, и он не остановлен»; нового потока над живым прежним не создаём никогда (два писателя в одно SHM-кольцо).
Запрос остановки не теряется авто-рестартом: после `stop_worker → True` потоков воркера нет.

## Принципы владельца

1, 2 (framework, fix forward); 3 (идемпотентный старт запущенного остаётся); 4 (один замок, слои не добавляем); 5 (сбой воркера не валит соседей).

## Задачи

| Task | Суть | Уровень |
|---|---|---|
| 1.1 | Тесты-«воспроизведения» состояния + таблица A/B/C в `start_worker` + замок проверки-и-запуска + уважение запроса остановки в авто-рестарте (H2) | Senior (concurrency): teamlead |

Цена: 5 участников × ~56k ≈ 280k + работа ≈ 250k.

## Task 1.1

- **Level:** Senior · **Assignee:** teamlead
- **Handoff:** tester (слепой, один раз, до кода) -> teamlead -> лид (инъекции) -> reviewer (стадия 5; конкурентность — sonnet по классу, ветка — opus)
- **Gate:** light (`worker_module/tests`); medium (`process_module/tests`, `Services/camera_device/tests`, `Plugins/sim/robot_host/tests/test_v2_real_worker_manager.py`)
- **Module contract:** публичная сигнатура `start_worker(name) -> bool` не меняется; меняется ответ в состоянии B (было `True`, стало `False`); контракт — в докстрингах `interfaces.py`, `README.md`, ADR-WRK-007
- **Dependencies:** нет

```
TASK: 1.1 — C-91: start_worker честный по таблице          PLAN: plans/worker-start-honest/plan.md
ROLE: teamlead
CHAIN: tester (слепой) -> you -> лид (инъекции) -> reviewer
```

### DESIGN

(decided by the lead — you type it, you do not derive it)

Обозначения: `T = worker_info["thread"]`, `E = worker_info["stop_event"]`.

**1. Таблица `start_worker`.**

| # | Состояние на входе (под замком, перечитано после захвата) | Что делает | Ответ |
|---|---|---|---|
| A | `T` жив, `status == RUNNING`, `E` не взведён | ничего (идемпотентный старт) | `True` |
| B | `T` жив, иначе (`STOPPING`; `RUNNING` при взведённом `E`; `ERROR` в окне `sleep(0,1)`; `COMPLETED`/`STOPPED` в окне `finally`) | ничего; нового потока над живым не создаём; `_log_warning` «старт воркера '<имя>' отклонён: прежний поток ещё жив (статус <статус>)» — ТОЛЬКО имя воркера и статус, без `args`; вызов лога — ВНЕ замка | `False` |
| C | `T` не жив (не запускался / завершился / залипший статус) | новый `Thread` с тем же именем `f"{manager_name}_{worker_name}"`, свежие `stop_event`/`pause_event`, `restart_count` как сейчас, статус `RUNNING`, `start()`; если `Thread.start()` бросил — под замком вернуть статус и `restart_count`, исключение пробросить | `True` |

Мёртвый поток (`is_alive() == False` в CPython 3.12 — только после выхода `run()` вместе с `finally` обёртки) → всегда C.
Имя потока `f"{manager_name}_{worker_name}"` сохранить в обоих местах создания: на нём держится `ExecutorManager.is_executor_thread` (ADR-WRK-006).
Нетривиальные клетки (RUNNING+`E` взведён; ERROR в окне авто-рестарта: `worker.start` ответит `False`, воркер воскреснет сам через ~0,1 с; COMPLETED при живом потоке) описать в README и ADR («повторить вызов»).

**2. Замок.** Простой `threading.Lock` (`self._start_lock` в `WorkerLifecycle`), не `RLock`: вложенности нет (берут только `start_worker` и `_restart_worker_internal`, и `stop_worker` коротко, см. п. 3);
`RLock` скрыл бы случайную вложенность — это причина выбора, записать в ADR. Порядок замков единственный: `_start_lock → registry._lock` (реестр — лист). Под замком НЕТ `join`, `sleep`, вызовов `target` и лога.
`Thread.start()` под замком допустим (ждёт bootstrap потока, миллисекунды, цель не исполняет).

**3. Запрос остановки не теряется (H2, корень).**
- `_worker_wrapper` передаёт `_restart_worker_internal(worker_name, stop_event)` (то есть `E` умирающего потока).
- `_restart_worker_internal` под `_start_lock` сверяет `stop_event.is_set()`: взведён → рестарт отменён, статус `STOPPED`, `return False`.
- `stop_worker` под `_start_lock` коротко (без `join`) делает снимок `(T, E)` одновременно, ставит STOPPING и `E.set()`; затем снаружи замка — `join(T)`.
  Это взаимно упорядочивает stop и авто-рестарт: либо `set()` раньше проверки (рестарт отменён), либо подмена раньше снимка (stop видит T2/E2).
- Сверху — страховка: после `join` перечитать `worker_info["thread"]`; пока он сменился и жив — взвести его `E` и ждать его в пределах остатка `timeout`; повторять до стабильности или исчерпания `timeout` (T2 мог дать T3).
  Не стабилизировался за `timeout` → прежнее поведение: `False`, статус STOPPING, лог ошибки.
- Если `stop_worker` вызван на воркере, чей `T` не жив, поведение прежнее.

**4. Вызывающие.** `False` в B проверено чтением по всему репозиторию (`git grep -n "start_worker("`): `create_worker(auto_start=True)` всегда путь C (поток свежий); `restart_worker`, `builtin_commands.py:586/602` (сквозная передача `success`),
`start_all_workers` (результат игнорируется), `Services/camera_device/session.py:330,:514` (теперь откат, а не вечный `held`), `Plugins/sim/robot_host/plugin.py:473` — не ломаются. Править их запрещено.
Устаревший текст вне FILES (в отчёт лиду К и лиду Р2): `Services/camera_device/session.py:320,520`, `Plugins/sim/robot_host/plugin.py:482`, `Plugins/sim/robot_host/tests/test_v2_real_worker_manager.py:8,203`.

### FILES

1. `multiprocess_framework/modules/worker_module/lifecycle/worker_lifecycle.py` — таблица A/B/C, `_start_lock`, снимок в `stop_worker`, проверка остановки в `_restart_worker_internal`
2. `multiprocess_framework/modules/worker_module/tests/test_worker_start_honest.py` (новый, слепой tester)
3. `multiprocess_framework/modules/worker_module/interfaces.py` — только докстринги `IWorkerLifecycle.start_worker` (:226-232), `IWorkerManager.start_worker` (:307-311) (сейчас обещают «жив при статусе не RUNNING → True»)
4. `multiprocess_framework/modules/worker_module/README.md` — абзац с таблицей A/B/C рядом с «Жизненным циклом воркера» (~:140-152)
5. `multiprocess_framework/modules/worker_module/DECISIONS.md` — **`## ADR-WRK-007: <заголовок>`** (суффиксов вроде `(C-91)` в заголовке нет: `scan_module` падает `ValueError`); поля как у ADR-WRK-006: Статус / Контекст / Решение / Отвергнуто / Следствия / Reversible / Refs; номер сверить `git grep -n '^## ADR-WRK-00' main`
6. `multiprocess_framework/DECISIONS.md` — только то, что перегенерирует `python -m scripts.sync` (строка `:2654` — диапазон `ADR-WRK-001…007` и последний заголовок); `python -m scripts.sync --check` → пусто; руками не править
7. `multiprocess_framework/modules/worker_module/tests/test_worker_lifecycle.py` — только если существующий тест ждёт `True` в состоянии B (по чтению таких нет; teamlead подтверждает прогоном и сообщает лиду)

Запрещено: `Services/**`, `Plugins/**`, `process_manager_process.py`, `launcher/spawner.py`, `multiprocess_prototype/**`. `STATUS.md` модуля не трогать (устарел, не про это).

### REDS

Все тесты — в daemon-потоках с дедлайном `join`; состояния B, «двойной старт» и H2 выстраиваются детерминированно, без натуральной гонки. Живые потоки считать через `threading.enumerate()` по имени `f"{manager_name}_{worker}"` (в реестре виден только последний созданный поток).

| # | Свойство | Красное сейчас |
|---|---|---|
| R1 | два цикла start/stop → два разных `thread.ident` у потоков воркера; оба раза `True` | нет (охрана) |
| R2 | состояние B: `target` не реагирует на `stop_event` до сигнала; `stop_worker(timeout=0.05)` вернул `False`; `start_worker` → `False`, живых потоков воркера ровно 1, `ident` прежний, `restart_count` не вырос, в логе «отклонён» | да (`True`) |
| R3 | после R2: сигнал отпущен, прежний поток вышел; `start_worker` → `True`, новый `ident`, `restart_count` вырос на 1 | нет (охрана) |
| R4 | залипший `RUNNING` при мёртвом потоке (статус выставлен вручную после выхода потока): `start_worker` → `True`, живой поток ровно 1, новый `ident` | да (`True` без потока) |
| R5 | A: повторный `start_worker` запущенного воркера → `True`, `ident` тот же, поток 1 | нет (охрана) |
| R6 | двойной старт: два потока зовут `start_worker` воркера с мёртвым потоком, точка встречи — `Barrier(2, timeout≈0.3)` с `except BrokenBarrierError: pass` (простой `Barrier(2)` повесит зелёный вариант) на обёртке `registry.get` или прокси `is_alive`; → ровно один живой поток | да (два), по ожиданию |
| R7 | H2: подмена экземплярного атрибута `lc._restart_worker_internal` обёрткой `in_window.set(); release.wait(timeout); return orig(name, stop_event)`; `stop_worker(timeout=2.0)` стартует в окне и стоит в `join` (подтвердить через `sys._current_frames()` верхний фрейм в `Thread.join`, запасной вариант — опрос `E1.is_set()`, он даёт только ложно-зелёное); после `release`: `stop_worker` → `True`, живых потоков воркера 0, статус `STOPPED` | да (T2 жив) |
| R8 | поток жив, статус `RUNNING`, `E` взведён → `start_worker` → `False` (без R8 удаление условия «`E` не взведён» в A оставляет R1–R7 зелёными) | да (`True`) |
| R9 | имя потока `f"{manager_name}_{worker}"` сохранено при старте по C и при авто-рестарте | нет (охрана) |

Предсказания инъекций (лид пишет ДО прогона; повторяются после последнего теста):
- вернуть ветку «`RUNNING` → `True`» — красный {R4} (R2 и R6 зелёные: статус STOPPING / один поток от первого вызова);
- вернуть «жив → `True`» — красные {R2, R8};
- убрать `_start_lock` — красный {R6} (при барьере с timeout);
- убрать условие «`E` не взведён» в A — красный {R8};
- убрать проверку `stop_event` в `_restart_worker_internal` — красный {R7};
- убрать снимок/перечитывание в `stop_worker` — R7 может остаться зелёным (корневая проверка в `_restart_worker_internal` его закрывает): ожидаемо {} — записать как «страховка, не охрана»;
- убрать `_start_lock` из `_restart_worker_internal` — НЕ доказывается чёрным ящиком (нет хука между подменой `worker_info["thread"]` и `.start()`): ожидаемо все зелёные; записать как недоказанное, не заявлять охват;
- `Thread.start()` бросает (подмена): статус и `restart_count` возвращены — отдельный тест R10 (красный сейчас: `RUNNING` залип при непущенном потоке).

### ACCEPTANCE

1. R1–R10 зелёные. Команда: `bash "$(git rev-parse --path-format=absolute --git-common-dir)/../scripts/machine_gate.sh" light D <python> -m pytest -q --tb=short multiprocess_framework/modules/worker_module/tests/test_worker_start_honest.py`.
2. Радиус без новых красных против `main` (сначала базовый прогон тем же набором на `main` в основном checkout, `medium`): `multiprocess_framework/modules/worker_module/tests`, `multiprocess_framework/modules/process_module/tests`,
   `Services/camera_device/tests`, `Plugins/sim/robot_host/tests/test_v2_real_worker_manager.py` (30 циклов start/stop на настоящем `WorkerManager`). Числа passed/failed в отчёт.
3. `python -m scripts.sync --check` пусто; `scripts/validate.py` — набор ошибок не хуже `main`; `sentrux check .` не краснее `main`; `ruff check -q` по изменённым файлам.
4. Стенд (лид, числами): 1500 циклов start/stop воркера + 3 цикла `release/take` камеры на фейке (`camera_device_demo`): число воркеров не растёт, потоков с одним именем ≤ 1.

### OUT OF SCOPE

- Упрощение `session.py:_launch_owner` (лид К после слияния).
- C-36 (очереди убитого процесса) и C-92 (импорт `heartbeat`).
- Любые правки текста вне FILES (список — в DESIGN п. 4, в отчёт).

### TRAPS

- Замок нельзя держать через `join`: `_restart_worker_internal` зовётся из потока воркера, `stop_worker` — снаружи (взаимная блокировка).
- `_worker_wrapper` в начале потока безусловно пишет `RUNNING` (`:215`) — поверх `STOPPING` от немедленного `stop_worker`: поэтому «`E` не взведён» обязательно в A.
- `restart_worker` ветка `status == RUNNING` проверяет статус, а не поток: не расширять.
- Образец состояния B — `test_worker_lifecycle.py::test_restart_worker_does_not_start_second_thread_when_stop_fails` (`:142`).
- Смена ответа `worker.start`/`worker.restart` в B видна в GUI (`success: False`).

## Журнал

- 2026-11-16 — план написан лидом полосы Д; стадия 0 раунд 1 (reviewer, sonnet): CHANGES REQUESTED, 8 групп пунктов; внесены; решение по H2 — корневая проверка остановки в `_restart_worker_internal` + снимок под замком в `stop_worker`.
