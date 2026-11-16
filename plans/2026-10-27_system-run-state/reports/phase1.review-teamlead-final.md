# Ф1 run-state — итоговая проверка teamlead (третья итерация, 2026-11-16)

Ветка `fix/run-state-phase1-review`. Бриф называл HEAD `a1d10922c`. За время работы ветка ушла на `896dd2d96`: два коммита, только документы и комментарии. `7baa1490e` — отчёт итерации 2. `896dd2d96` — ADR RunFlag переименован в **ADR-PMM-047**, потому что 046 в `main` занят PID-реестром. В `.py` изменились 6 строк, все комментарии: `git diff a1d10922c 896dd2d96 -- '*.py'`. Ниже «ADR-PMM-046» из брифа = ADR-PMM-047.

- Проверял код `896dd2d96`. Сессия гейта `rs-teamlead`, все прогоны `light`/`medium`.
- Отдельный worktree для инъекций: `<scratchpad>/tl/wt` (удалён после работы). Путь импорта: `multiprocess_framework.__file__` = `<scratchpad>/tl/wt/multiprocess_framework/__init__.py`, запуск из того же cwd `multiprocess_framework/modules`.
- Скрипты:
  - `/private/tmp/claude-501/-Users-twokrai-Project-code-Inspector-bottles/d2c67523-26b4-41a7-a0e5-4ce5d93d7eca/scratchpad/tl/predictions.md` (предсказания, записаны до прогона);
  - `/private/tmp/claude-501/-Users-twokrai-Project-code-Inspector-bottles/d2c67523-26b4-41a7-a0e5-4ce5d93d7eca/scratchpad/tl/inject.py` (T1–T7, откат `cp`, `git status` пуст после каждой);
  - `/private/tmp/claude-501/-Users-twokrai-Project-code-Inspector-bottles/d2c67523-26b4-41a7-a0e5-4ce5d93d7eca/scratchpad/tl/repro_tl.py` (Q1–Q3);
  - `/private/tmp/claude-501/-Users-twokrai-Project-code-Inspector-bottles/d2c67523-26b4-41a7-a0e5-4ce5d93d7eca/scratchpad/rs/repro.py` (R1, R1b, R6, R7 ревьюера).
- memory hits: `scripts/memory/search.py run-state readiness reasons validator` -> `feedback_ready_signal_meant_less_than_read.md`, `project_industrial_standards_packml.md`, `project_plugin_paused_is_a_label.md` (контекст, находок не дают).

## 1. Вердикт

**MERGE WITH CONDITIONS.**

- Блокирующих дефектов нет.
- И2-1 закрыт, проверено воспроизведением: R6 даёт `fault` вместо прежнего `running`, R7 даёт `ack` -> `not_ready`.
- Валидатор причин не строже ни одного настоящего отправителя.
- Свойства fix-B4 и RunFlag держатся тестами: из 7 инъекций 6 дали красный, 1 — эквивалентный мутант.
- Нашёл три новых дефекта класса «итог/выход не случается». Все три с воспроизведением и все с малой вероятностью (Q1–Q3). Это **minor**: без них сливать можно, но их обязательно записать.

Условия слияния — §6.

## 2. Таблица находок

| # | severity | что | воспроизведение (вход -> наблюдаемо) | решение |
|---|---|---|---|---|
| Q1 | minor | Авария без выхода, если поток остановки в аварии не стартовал. `_submit_run_sequence.detached()`: при сбое `Thread.start()` итог ставится только для `run-stop`, для `run-fault-stop` — нет. Тот же класс, что И2-1 п.2, другой вход | `running`; поток `run-fault-stop` бросает `RuntimeError` на `start()`; `b` упал; такт -> `Q1 state: fault \| fault_stop_done: False \| ack: {'success': False, 'state': 'fault', 'error': 'fault_stopping'}` — навсегда, выход только `system.shutdown` | Исправить вперёд: в ветке `except` у `detached()` для аварии звать `_run_stop_finish(fault=True, seq=<seq подачи>, names=[], timeout_s=0.0)` (~5 строк + тест). До слияния — желательно; не сделано — записать (§6) |
| Q2 | minor | «Одиночный сбой оценки не даёт дребезга» неверно сразу после START. `_run_ready` обновляет только `tick`. После `settled(ready=True)` в нём остаётся `False` от тактов `booting`. START сразу после `settled` (≤ 0,5 с). Первый такт с исключением оценки берёт `ready=None` -> `_run_ready=False` -> `fault` | `Q2 settled: ready \| _run_ready False`; `START: running \| _run_ready False`; один сбойный такт -> `fault`, причина `['оценка готовности не удалась']` | Сторона безопасная (авария, а не слепота). Правка: `_run_apply` пишет `_run_ready` и на успешных `settled`/`start`/`ack`, не только на `tick`. Записать |
| Q3 | minor | START и `ack` зовут `_evaluate_run_readiness(admission=True)` без охраны. При исключении команда бросает, хотя обещан ответ с кодом отказа | оценка бросает -> `Q3 _cmd_system_run_start RAISES RuntimeError eval broken`, то же у `_cmd_system_run_ack` | Тупика нет: состояние не меняется, выход — когда оценка снова пройдёт. Но контракт ответа нарушен, а текст исключения уходит в ответ диспетчера (по чтению). Правка: тот же `_evaluate_or_fail` -> отказ `not_ready` с причиной. Записать |
| A1 | advisory | Двойная защита: `run_state.evaluate` фильтрует `isinstance(r, dict)` и `or []` за `normalize_leaf` (принцип 4) | T7 — фильтр убран: `282 passed` (эквивалентный мутант) | Убрать или явно записать «`evaluate` доверяет `normalize_leaf`» (Task 3.2) |
| A2 | advisory | Одна причина «оценка готовности не удалась» строится в двух местах с разным `source`: `_evaluate_or_fail` — `report`, `_evaluation_failed` — `liveness`. Имя узла тоже разное: `getattr(self, "name", ...)` и `self.name` | чтение `process_manager_process.py:1435-1440`, `:1540-1545` | Один конструктор причины, один `source` |
| A3 | advisory | Докстринг `readiness_reason_is_valid` и коммит fix-B4 говорят, что функцию зовёт и отправитель-ребёнок. Это не так: ребёнок берёт только константы и строит причину своим `_reason`. Связь держит тест `test_reason_built_by_child_orchestrator_is_valid_by_the_shared_function` (красный под T1) | чтение + T1 | Поправить докстринг. Код верен |
| A4 | advisory | Негодный лист не пишется в журнал PM. Оператор видит только «лист готовности негоден: <процесс>», без поля, которое не прошло | чтение `normalize_leaf` (чистая функция, без лога) | WARNING один раз на серию в `_admit_heartbeat` (имя поля, без значения) |
| A5 | nit | `_eval_fail_since` не объявлен на классе, читается через `getattr`. Пишет только поток монитора, гонки нет | чтение | `_eval_fail_since: float \| None = None` рядом с `_run_ready` (`:184`) |
| A6 | advisory | `_evaluation_failed` зовёт `_run_stale_s()`. Если бросает `get_config`, то бросает и он: такт теряется каждый раз, `fault` не наступает. Тот же класс, что исходный F1 | чтение; вероятность ничтожна (`get_config` — чтение dict) | Записать вместе с Q3 |
| M | merge | `multiprocess_framework/modules/process_manager_module/DECISIONS.md`: `main` добавил ADR-PMM-046 (PID-реестр), ветка добавила ADR-PMM-047, обе вставки после ADR-PMM-045 (`:2539` в обеих версиях) | `git grep -n "^## ADR-PMM-046" main -- …/DECISIONS.md` -> `:2539` | Текстовый конфликт: оставить оба ADR (046, затем 047), затем `python -m scripts.sync`. Других пересечений с `main` в затронутых модулях нет: `git diff --stat <merge-base>..main` — только `launcher/pid_registry*` и документы |

## 3. Пункт 1 брифа — fix-B4

### 3.1. Не строже ли валидатор настоящих отправителей — нет

Перебрал всех производителей.

- **Отправитель heartbeat один:** `ProcessHeartbeat` (`process_heartbeat.py:448`, `copy.deepcopy` снимка). `git grep` по `"readiness":` / `["readiness"]` в коде вне тестов даёт 2 места: монитор (читатель) и heartbeat (писатель).
- **Снимок пишут два места:**
  1. `PluginOrchestrator.readiness_snapshot`. Каждая причина идёт через `_reason`:
     - `node` — f-строка или `process_name`;
     - `severity` — литерал из `READINESS_SEVERITIES`;
     - `reason` — срез `[:200]`, всегда точный `str` (срез подкласса `str` даёт точный `str`);
     - `source` — литерал `"readiness"`.

     Число причин — `_cap_reasons` ≤ 32 вместе с маркером. Для `ready`/`paused` выражения дают настоящий `bool`.
  2. `ProcessModule._refresh_readiness_snapshot` без оркестратора: `reasons: []`, `ready` — `bool`-атрибут, `paused` — `bool`.
- **Хуки `readiness()`** (`Services/ml_inference/plugin/plugin.py:325`, база `plugins/base.py:1565`; в `Plugins/` своих хуков нет) идут через `_canonical_items`. Из них берутся только `severity` и `reason`, а `node`/`source` ставит оркестратор. Чужая форма хука становится причиной `failure` «неверная форма», а не негодным листом.
- **Ключ `"message"` рядом с `severity`.** `git grep '"severity"'` вне тестов дал 34 строки. С `"message"` встречаются только записи наблюдаемости (`observability_hub.py:155`, `record_display.py:40`, другой контракт). У настоящих производителей причин готовности ключа `"message"` нет. Отклонение было только в трёх тестовых хелперах, лид их исправил.
- **Прямая проверка:** `test_reason_built_by_child_orchestrator_is_valid_by_the_shared_function` — зелёный на HEAD, красный под T1.

Остаток теоретический: `self._services.name` не `str` -> маркер `_cap_reasons` негоден -> лист негоден -> `not_ready` с видимой причиной. Сторона безопасная.

### 3.2. «Негодная причина = негоден весь лист» — согласен

Отправитель строит причины годными по построению. Значит, негодная причина — это сломанный отправитель (ошибка или расхождение версий), и остальным причинам того же листа верить нельзя. Цена — потеря диагноза — снимается советом A4 (журнал), а не ослаблением правила.

### 3.3. Серия сбоев оценки на такте — корректна, с оговоркой Q2

- Порог равен `_run_stale_s()`.
- ERROR пишется один раз на серию (T4 — красный).
- `ready=False` ставится, только когда серия ≥ порога (T3 — красный).
- Успешный такт сбрасывает серию (T5 — красный).
- Нового тупика нет: `ready=None` берёт `_run_ready`, таблица даёт выход из всех состояний (R4 итерации 1).
- Дыра одна — Q2 (устаревший `_run_ready` после `settled`).
- `_eval_fail_since` через `getattr` работает (A5).

### 3.4. `finally` у `_fault_stop_done` — достаточен локально, но не сквозным образом

- Для шага «дописать причины срока» `finally` эквивалентен присваиванию после `try/except`. Это мутант ii-a исполнителя. Смысл у `finally` есть только для `BaseException`.
- Ранний `return` при чужом `seq` или выходе из `fault` верен.
- Но свойство «из `fault` выход есть всегда» держится не одним `finally`. Его ломает Q1: последовательность не запустилась вовсе, и до `_run_stop_finish` дело не дошло.

## 4. Пункт 2 — ветка целиком

- **Противоречий между правками исполнителей не нашёл.**
  - A (замки PM, обход отказа исполнителя): у `_submit_run_sequence` один путь обхода для всех видов, кроме Q1.
  - B (монитор, допуск, форма листа): одна точка `normalize_leaf`, один разборщик `resolve_policy`.
  - C (причины `ml_inference`): идут через `_canonical_items`.
  - RunFlag: под `_run_lock` межпроцессных замков нет.

  Все четыре правки сходятся.
- **Двойная защита:** A1 (подтверждено T7) и A2. Связка R7 — проверка формы на входе и `try/except` на выходе из `fault` — не дубль: это два разных свойства, форма входа и живость выхода, и у каждого свой прямой тест (T1 и ii-b исполнителя).
- **Мёртвый код:** гард `isinstance(resolved, tuple)` под двойник убран. Локальный `_MpEvent` жив (им пользуется `stop_event`). Мёртвым стал только фильтр из A1.
- **Комментарии против кода:** ADR-047 в коде, ADR и amendments согласованы после `896dd2d96`. «046» осталось в старых коммитах и отчётах `docs/reviews/2026-11-15_task-1.10.md`, `…fix-B4.md` — это история, её не правят. Расхождение A3.
- **ADR-PMM-047 против кода:** `run_flag.py` (`RawValue(c_bool)`, без `wait`, умолчательный контекст), `_run_apply`/`_run_stop_clear_event` (`RunFlag` под `_run_lock`) и `pause_event` (`threading.Event` воркера) — совпадают.
- **ruff** на 5 изменённых `.py`: `All checks passed` (вывод `RUFF_OK`).
- **Радиус на HEAD (medium):** `test_run_*.py`, `test_monitor_*.py`, `test_restart_process_failure_unmarks.py`, `test_supervisor_restart_incarnation*.py`, `test_process_monitor.py`, `test_boot_progress*.py`, `test_supervision_status_system_stop_hazards.py` и `Services/ml_inference/tests/test_readiness_{orchestrator_wiring,reason}.py` -> `707 passed, 1 warning in 78.50s`.

## 5. Пункт 3 — инъекции (предсказание записано до прогона, `predictions.md`)

База: целевые файлы без инъекций -> `338 passed`.

| # | что сломано | предсказание | наблюдено |
|---|---|---|---|
| T1 | `readiness_reason_is_valid` -> `isinstance(reason, dict)` | красные таблица полей и R6, ~15; R7 зелёный (вторая защита); `too_many` зелёный | **16 failed**: 14 строк таблицы, тест «причина ребёнка годна», R6. R7 и `too_many` зелёные — совпало |
| T2 | убран потолок 32 причин | 1 красный (`too_many_reasons`) | **1 failed** — совпало |
| T3 | серия никогда не даёт `fault` | 1 красный (порог) | **1 failed** (`…_not_shorter_than_stale_goes_fault`) — совпало |
| T4 | ERROR на каждом сбое | 1 красный | **2 failed**: тест порога тоже считает ERROR. Защита сильнее предсказанной |
| T5 | успех не сбрасывает серию | 1 красный | **1 failed** (`…resets_the_series`) — совпало |
| T6 | `RunFlag` внутри — `mp.Event` (тот же API и тип) | `test_run_flag.py` тест 4 красный, вероятностно; `test_run_flag_pm_wiring.py` зелёный (тип прежний) | прогон 1: **25 failed**, прогон 2: **23 failed** — все `test_parent_not_hung_after_child_killed_in_hot_read_loop[*]`; проводка зелёная. Совпало. Вероятность ловли высокая: 23–25 из ~30 параметров на прогон |
| T7 | убран фильтр `isinstance(r, dict)` в `run_state.evaluate:94` | всё зелёное (эквивалентный мутант) | **282 passed** — совпало (A1) |

Воспроизведения ревьюера на HEAD:

- R6 -> `fault`, «лист готовности негоден: a», ошибок `unhashable` нет;
- R7 -> `fault_stop_done True | ack: {'success': True, 'state': 'not_ready'}`;
- R1 -> `fault`;
- R1b -> `ready`, START -> `running`.

## 6. Пункт 4 — решения лида

**«M2 оставить» (негодный per-process `restart_policy` без флага -> `not_ready`) — согласен.**

- Супервизор на негодном dict молча берёт глобальную политику (`resolve_policy`, умолчание `enabled=False`). Процесс, который оператор считал перезапускаемым, не перезапустится.
- Отказ START с названной причиной без значений честнее, чем тихий откат.
- Цена: один кривой конфиг держит START всей системы. Это напряжение с принципом 5, но это ошибка конфигурации, а не отказ рантайма, и выход есть (`run_required: false` или правка рецепта).
- Рецепты проверил запуском: 7 dict `restart_policy` в `multiprocess_prototype/recipes/**/*.yaml`, `RestartPolicy(**rp)` -> `invalid: 0`.
- Совет на будущее: лучшее место этой проверки — отказ `topology.apply`. Сейчас ошибка всплывает только на START.

**«Сбой оценки на такте -> fault по порогу» — согласен.**

- Это не новое решение владельца, а следствие R2 («молчание = не готов») и R3 («потеря в работе — авария»).
- Порог равен сроку молчания, новой константы нет.
- Одиночный сбой не дребезжит — за исключением окна Q2.
- Оговорки: Q2 и Q3 (START/`ack` бросают вместо отказа) надо записать.

## 7. Пункт 5 — готовность к слиянию

**Блокирует:** ничего из кода.

**Условия до слияния:**
1. Разрешить конфликт `process_manager_module/DECISIONS.md`: оставить ADR-PMM-046 (main) и ADR-PMM-047 (ветка), затем `python -m scripts.sync`.
2. Записать в `docs/claude/OPEN_QUESTIONS.md` или в очередь плана (рядом с Task 3.2):
   - Q1: желательно исправить до слияния, ~5 строк + тест;
   - Q2, Q3 и A6 — одной задачей «оценка и итог не бросают на всех путях»;
   - A1–A4 — советами.
3. Полный прогон набора у лида в его окне (heavy). Я его не гонял, см. §8.

**Не блокирует:**
- Находки стенда 1.10. С решением лида согласен.
  - Гонка импорта `cpu_clock` старше Ф1 (`6601abd2b`, предок `dd5378bb8`). Дифф Ф1 по `builtin_commands.py` пуст.
  - Мёртвая линия — это C-36. Дифф `queues/`, `router_module/`, `data_receiver.py` пуст.
  - Обе записаны в `OPEN_QUESTIONS.md:2323-2328` и в очередь.
  - Оговорка: Ф1 добавил ребёнку потоки до `run()`. Меняет ли это частоту гонки, не измерено (investigator, §(г)). Лечение — импорт на уровень модуля — от этого не зависит.
  - Что `running` без причин при мёртвой линии, — граница смысла готовности (самоотчёт узла, data-plane не виден). Это не дефект Ф1. Стоит одной строкой добавить в `phase1.known-compromises.md`, если там этого нет.

**Нужен ли `cto` — нет.**
- Спора teamlead и reviewer нет: с И2-1 согласен, он закрыт.
- Новых межмодульных контрактов ветка не вводит. ADR-047 и форма листа живут внутри framework: один писатель (`ProcessHeartbeat`), один читатель (монитор).
- Приёмка фазы уже была при слиянии Ф1 в `main` (`506eea281`, merge-base ветки). Эта ветка — правки ревью после неё.
- `cto` нужен по C-36 (очереди убитого ребёнка, структурное решение), но это отдельный трек вне этой ветки.

## 8. Что не проверено / ненадёжно

- Полный набор тестов и весь каталог `process_manager_module/tests` не гонял: ENOSPC по брифу, heavy запрещён. `process_module/tests` целиком тоже не гонял. Опираюсь на прогон исполнителя fix-B4 (`3625 passed`, его worktree, до правки хелперов лидом). Правка лида касалась только тестов PM — по `git show --stat 11f4081e4`.
- Стенд и живой бэкенд не запускал. Q1–Q3 и R6/R7 воспроизведены на `make_readiness_pm`: настоящие PM и `ProcessMonitor`, но `MockProcessRegistry` и `MagicMock` у связи. Q1 — имитация (`Thread.start` бросает только для `run-fault-stop`), природная частота неизвестна (исчерпание потоков ОС).
- Q3: что диспетчер команд отвечает на исключение `_cmd_*` и уходит ли текст исключения наружу, — по чтению, не проверял.
- Windows не проверял: передача `RawValue` при spawn, T6 на семафорах Win32.
- Валидацию рецептов проверил на сыром YAML через `RestartPolicy(**rp)`. Путь `ProcessLaunchConfig.build` (возможное преобразование dict) не проходил.
- T6 — свойство вероятностное: 2 прогона, 23 и 25 красных из ~30 параметров. Это много, но не доказательство на каждом прогоне.
- Дифф ветки (~15 тыс. строк, 72 файла) читал выборочно: fix-B4 целиком, `_run_apply`, `_submit_run_sequence`, `_run_stop_*`, `normalize_leaf`, `resolve_policy`, оркестратор (снимок и причины). Тесты не читал построчно.
- Ф1 и частота гонки `cpu_clock` — не измерял (§7).
