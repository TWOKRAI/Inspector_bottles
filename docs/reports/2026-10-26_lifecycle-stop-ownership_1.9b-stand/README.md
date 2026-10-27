# Стенд Task 1.9b (lifecycle-stop-ownership): `stand_l9.py`

Замеряет S1-S5 из `plans/lifecycle-stop-ownership/tasks/T1.9b_tests.md` («Стенд») и контрольный прогон на патче И1. Печатает числа,
пишет JSON на каждый прогон и таблицу `results.md`. Бэкенд не запускался ни разу: скрипт проверен офлайн (компиляция, `--help`,
`--dry-run`, юнит-тест вердиктов, сборка временных конфигов штатным загрузчиком). Первый живой запуск - в окне стенда, сначала `--quick`.

## Запуск

```
PY=D:/PROJECT_INNOTECH/Inspector_vision/Inspector_bottles/.venv/Scripts/python.exe
export PYTHONUTF8=1 PYTHONPATH=<корень worktree>
bash "$(git rev-parse --path-format=absolute --git-common-dir)/../scripts/machine_gate.sh" heavy inspector-bottles-90 \
  $PY docs/reports/2026-10-26_lifecycle-stop-ownership_1.9b-stand/stand_l9.py --scenario all --out <каталог результатов>
# контроль: тот же S2-S4 на дереве с И1
... stand_l9.py --control --control-root D:/PROJECT_INNOTECH/Inspector_vision/Inspector_bottles/.claude/worktrees/lso-1.9b-inj \
    --inj-patch <scratchpad>/inj/I1.patch --out <каталог результатов>/control
# T1.10: S1 (outcome) + S6; S6 не входит в all
... stand_l9.py --scenario S1,S6 --out <каталог результатов> [--s6-slow-stop-s 6.0 --s6-window-s 5.0]
# проба самого стенда, по 1 повтору: добавить --quick;  план без бэкенда: --dry-run
```

Код выхода 0 только если все строки PASS (в контроле - если стенд различает и дерево после отката чистое).
Юнит-тест вердиктов (класс `light`): `python -m pytest -q docs/reports/2026-10-26_lifecycle-stop-ownership_1.9b-stand/test_stand_l9_verdict.py`.

## Что делает каждая строка

Бэкенд стартует отдельным процессом (`stand_backend.py`), со своим cwd, портом, временными `app.yaml`/`system.yaml`,
логами в `<out>/runs/<тег>/logs`; `multiprocess_prototype/app.yaml` и закоммиченные конфиги не трогаются. Команды идут через
`BackendDriver` (`request_async`, момент прихода берётся на reader-потоке сокета). Дверь `process.*`: `--door direct` (по умолчанию,
как `ProcessManager process.stop` в прежнем стенде) или `command` (`process.command`, дверь GUI).

| Строка | Повторов | Как меряется | Порог ПОСЛЕ (литерал `THRESHOLDS`) |
|---|---|---|---|
| S1 | 10, свежий бэкенд на каждый | 2 sim-робота v2 в процессе стенда, `device_upsert`+`device_connect` обоих (ждём `connected`), `process.stop devices`: время до ответа, статус `devices` через 3 с, строки логов | 0 зависаний; ответ 0,85-1,20 с; `not reported/lost` 0 |
| S2 | 10 стопов | `slow` (3,0 с) через `topology.apply`; `supervision.status` каждые 0,1 с (асинхронно, поэтому медленный ответ не прореживает пробы); берутся пробы, отправленные между `process.stop` и его ответом | каждый ответ <= 0,5 с; p99 <= 0,150 с; >= 20 проб на стоп и стоп >= 2,5 с (иначе прогон недействителен) |
| S3 | 10 | на +1,0 с стопа `slow` `process.relay` в `devices` с внутренним `introspect.status` (request_id и reply_to=PM); доставка = приход ответа `devices` на внутренний request_id (push-слушатель), плюс ответ самого relay | оба <= 0,5 с; нет сигнала доставки = FAIL |
| S4 | 5, свежий бэкенд | stop `slow`; +0,1 с `process.restart fast` (ждущий в очереди); +1,0 с `system.shutdown`; строка `System shutdown requested` из логов PM (штамп минус момент отправки stop), выход процесса бэкенда, число `did not stop in`, ответ ждущего | строка <= +1,2 с; выход <= +4,5 с; dns 0; ждущий `system_stopping` |
| S5 | 10 выходов, свежий бэкенд на каждый | `system.shutdown` без `slow`: от отправки до исчезновения лаунчера и PID детей из `supervision.status` (`tasklist`, без psutil). В прогоне 1 ещё `process_restart_verified` x3 на каждую цель и один `recipe.activate` | рестарт < 5,0; выход дерева < 2,0 (10 из 10); activate < 5,0 (строго) |
| S6 (T1.10) | 3, свежий бэкенд на каждый (повтор не наследует запись `stop_outcome` и поток исполнителя прошлого) | `slow` = `S6SlowChild` (стоп 6,0 с, параметр `--s6-slow-stop-s`), `stop_process_timeout` 5,0 с (`--s6-window-s`), `process.stop slow`: время до ответа и ответ целиком; запись `slow` в `supervision.status` после стопа. Не входит в `--scenario all` | `outcome == "terminated"`, `success is True`, ответ 5,0-5,3 с; 3 из 3 |

S1 дополнительно считает `outcome` из ответа `process.stop devices` (`{"exited": n, ...}`, в JSON `outcomes`, в `results.md` блок «Итоги стопа»); пороги S1 не менялись, `outcome` - наблюдение (прогноз: `exited` 10 из 10).

В каждой строке: min/median/max/p99, число зависаний, число строк `not reported/lost` и `did not stop in` (уникальные по штампу и тексту
во всех `*.log`). Зависание всегда FAIL с затраченным временем: S1 - нет ответа, ответ >= 4,5 с, статус `crashed` или `lost > 0`; S2-S4 - нет ответа
за дедлайн (25 с стоп, 40 с выход PM). Прежний дефект (`verdict: OK` у зависших) повторён быть не может: в скрипте нет вердикта OK.

Контроль: `git apply` I1.patch (перед этим `git diff --quiet` обязан быть чистым), S2-S4, `git apply -R`, `git diff --quiet`. Стенд «различает», если
S2-S4 на И1 дали FAIL **и** достигли нижних границ «ДО»: макс. ответ S2 >= 2,0 с, доставка S3 >= 2,0 с, строка shutdown S4 >= +3,0 с.

## Окна остановки `stop_process_timeout: 8.0` и `shutdown_timeout: 8.0` (только на этот запуск)

Что нашлось в коде:

- `shutdown_timeout` едет из `system.stop_timeout` (`multiprocess_prototype/backend/launch.py:786` -> `spawner.py:90-92`:
  `process_config["shutdown_timeout"] = stop_timeout`, если оркестратор не задал свой). Допустимо 1,0-30,0 (`config/schemas.py:28-31`).
  Стенд пишет **временный** `system.yaml` с `stop_timeout: 8.0` и подсовывает его через временный манифест
  `INSPECTOR_MANIFEST` (`main.py:47`, `manifest.py:163`; правило координатора до C-21 - манифест только во временном каталоге).
- `stop_process_timeout` **нигде не задаётся**: ни в `system.yaml`, ни в `orchestrator_config` (`launch.py:750-791`, литерал), ни через env;
  PM читает `get_config("stop_process_timeout") or 5.0` (`process_manager_process.py:1978, 3829, 4388`). Единственный способ без правки кода -
  `stand_backend.py`: до запуска `main.main(headless=True)` подменяет атрибут `assemble_launcher` пакета `launcher` и добавляет ключ в
  `orchestrator_config` (импорт в `launch.py:638` ленивый, поэтому подмена на уровне пакета срабатывает). Подмена живёт только в процессе
  бэкенда; печатает `[stand] orchestrator_config.stop_process_timeout=8.0`, и `Backend.start()` ищет эту строку в stdout (`override_seen` в JSON).
- Вход: `run.py` в worktree не годится (venv-guard `run.py:34-41` ищет `<корень>/.venv`, в worktree его нет), поэтому `stand_backend.py` зовёт
  то же `main.main(headless=True)`, что и `run.py --headless`.
- Медленный ребёнок: `topology.apply` не передаёт лишние ключи чертежа в ребёнка (`blueprint.py` комментарий про `extras`), поэтому
  `stand_slow_child.SlowChild` - тонкий наследник тестового `LifecycleChild`, зашивающий `stop_delay_s = 3.0` (и `FastChild` - 0,0). Каталог стенда
  идёт в `PYTHONPATH` бэкенда.

## Что нельзя было определить без живого бэкенда (проверить первым запуском `--quick`)

1. Принимает ли `topology.apply` чертёж `{"name","processes":[{"process_name","process_class"}],"wires":[]}` без других полей; скрипт сначала делает
   `topology.diff` и отказывается идти дальше, если diff трогает `devices`/`gui`. На первом `topology.apply` PM сносит все non-protected процессы рецепта
   (на boot `_current_topology` = None, `process_manager_process.py:3988`), остаются `devices`, `gui`, `slow`, `fast`.
2. Приходит ли ответ `devices` на внутреннее сообщение relay в push-слушатель клиента (S3). Нет сигнала - FAIL с текстом, не PASS.
3. Имя поля `alive` и ключа `processes` в `supervision.status` взято из `driver.process_restart_verified`; формат ответа `topology.diff` (`commands`) - из `topology_manager.py`.
4. Имена файлов логов PM: считаются все `*.log` каталога логов; строка shutdown берётся самая ранняя.
5. `renderer` в рецепте `region_pipeline` нет (он из старых рецептов): S5 берёт первый живой non-protected процесс и пишет подстановку в JSON.
6. `recipe.activate` активного рецепта на первом вызове после boot идёт в полную замену (`_current_topology` = None) - но это слабая проверка регресса, не замена прогона другого рецепта.

## Раунд 2 (`--round2`): методика после вердикта investigator

Источник: `docs/reviews/2026-10-26_task-1.9b-stand-investigator.md`. Запуск (окно стенда, класс `heavy`; бэкенд не запускался ни разу — офлайн
проверены компиляция, `--help`, `--dry-run --round2`, юнит-тест вердиктов и `watch_pid_exit` на настоящем процессе):

```
... stand_l9.py --round2 --out <каталог> [--round2-parts restart,s4,tree] [--main-root <корень main, только чтение>] [--quick]
```

| Часть | Что делает | Порог (литерал `R2_THRESHOLDS`) |
|---|---|---|
| R2-A `restart` | 3 сеанса на дерево, **строго A/B/A/B одиночными сеансами** (ветка, main, ветка, main, ...), поровну. Сеанс = свежий бэкенд, полная загрузка (строка PM `CommandManager 'ProcessManager' registration summary`), `process_restart_verified` camera_0 x3 и devices x3. В JSON весь `res` (polls, elapsed), момент отправки/возврата запроса драйвера (`drv.request` обёрнут), `request_error` (`timeout` = собственное окно драйвера 5,0 с, не ответ PM), ответ против строки PM `Process '<имя>' restarted` | ответ раньше `restarted` больше чем на 0,05 с = FAIL; `request_error` = FAIL; ветка < 5,0 с строго (main - база, числа печатаются) |
| R2-B `s4` | S4 x5 на ветке; выход PM по дескриптору (`OpenProcess(SYNCHRONIZE)` + `WaitForSingleObject`, ctypes), без `tasklist`; отдельно `launcher_exit_s` и `tasklist_call_s` (стоимость одного вызова) | порог S4 прежний: строка <= +1,2 с, выход PM <= +4,5 с, dns 0 |
| R2-C `tree` | Выход дерева исходным методом Task 1.1 (`backend_ctl/tests/test_system_shutdown_live.py:64-100`): рецепт `inspection_full` (`multiprocess_prototype/backend/topology/inspection_full.yaml`), полная загрузка + 2,0 с, `system.shutdown`, метрика = выход **процесса PM** (дескриптор); 10 на ветке и 10 на main строго по очереди | `< 2,0 с` строго, 10 из 10 на каждом дереве (не ослаблен) |

Выход: `<out>/json/R2A_*.json`, `R2C_*.json`, `S4_r*.json`, `round2_summary.json` (разброс min/median/max/p99 по дереву и цели), `results_round2.md`.
Ограничения метода: момент прихода ответа - возврат `request()` у вызывающего (пробуждение события reader-потока, расхождение - мс), а не штамп
внутри reader-потока; штамп `restarted` - мс-разрешение лога PM против `time.time()` той же машины (допуск 0,05 с). Рецепт `inspection_full` как
`pipeline` временного манифеста офлайн не проверялся (формат runnable-топологии допустим по `manifest.py`, но живой запуск не делался).

Окна остановки раунда 2: R2-A и R2-B идут с override `stop_process_timeout`/`stop_timeout` = 8,0 (медленный ребёнок 3,0 с); **R2-C - на окнах по умолчанию** (без подмены `orchestrator_config`, без `stop_timeout` во временном `system.yaml`: значения кода и `backend/config/system.yaml` дерева, 5,0), как исходный метод Task 1.1. Режим пишется в JSON каждого сеанса (`windows`), `--dry-run --round2` показывает окна по строкам.
