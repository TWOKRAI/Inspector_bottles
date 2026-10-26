# Стенд SPI хаба: S0–S3 (как C-29) + device_io

Скрипты восстановлены по `../C-29.stand.md`, handoff `docs/handoffs/2026-10-21_task-T5.3h-merged.md` и коду (скрипты C-29
жили в scratchpad и потеряны). Прогнаны 2026-10-26 (окно SPI ч.2): 4 запуска, три последних — `STAND: PASS`. Первый запуск нашёл три ошибки самого
стенда (SOFT, триггер S3, форма ответа `device_list`) — исправлены, описаны ниже.

| файл | что |
|---|---|
| `run_stand.py` | оркестратор: сим + бэкенд + сценарии + останов + `count.py`; `--dry-run` печатает план, `--prepare-only` пишет копии |
| `sim_v2.py` | сим v2 (`SimRobotServer` + `RobotSimCoreV2`), управление файлом `sim.ctl` (`drop`, `up <мс>`, `delay <мс>`, `mark <имя>`, `quit`) |
| `count.py` | таблица S0–S3 и проверки по каталогу прогона; код выхода 0 — всё PASS |

## Окружение (ловушка координатора)

- Код — из worktree `…/.claude/worktrees/robot-v2-spi`; python — **главный** `.venv` (`D:/PROJECT_INNOTECH/Inspector_vision/Inspector_bottles/.venv/Scripts/python.exe`);
  `PYTHONPATH=<worktree>`; никаких `uv sync` / `uv run`; не запускать python с cwd `process_module`.
  `run_stand.py` сам печатает `import multiprocess_framework -> <путь>` и **прерывает прогон**, если путь вне worktree.
- Данные главного `data/` бэкенду **не нужны**: `devices.yaml` и `data/robot` (хранилище точек) создаются заново — путь
  задаёт `INSPECTOR_DATA_DIR` (`Plugins/hub/device_hub/plugin.py:62-80`), логи — `MULTIPROCESS_LOG_DIR`. Оба — в каталог прогона
  `<stand-root>/run-<время>/`. Проверено чтением кода, не запуском (см. «Что ненадёжно»).
- Копия манифеста и рецепта — **вне git**: `<stand-root>/manifest/{app.yaml,stand_delta_v2.yaml}`
  (`<stand-root>` = `C:/Users/INNOTECH/AppData/Local/Temp/claude/d--PROJECT-INNOTECH-Inspector-vision-Inspector-bottles/f21dbeed-4bd4-4703-9052-60b3a63c25d4/scratchpad/spi-stand`).
  Рецепт собирается из `robot_demo.yaml` worktree: `delta_v2` на `127.0.0.1:5021` unit 2, `on_connect: {servo: true, do: {"1": true}}`,
  ПЧ `vfd_belt` оставлен (`--no-vfd` убирает), `camera_0` и все `displays` убраны. Копия уже записана (`--prepare-only`),
  загрузка манифеста проверена (`manifest ok`). Манифест главного дерева (`multiprocess_prototype/app.yaml`) не читается бэкендом и не меняется.

## Последовательность команд

```bash
cd D:/PROJECT_INNOTECH/Inspector_vision/Inspector_bottles/.claude/worktrees/robot-v2-spi
export PYTHONUTF8=1 PYTHONPATH="$PWD"
PY=D:/PROJECT_INNOTECH/Inspector_vision/Inspector_bottles/.venv/Scripts/python.exe
S=plans/robot-protocol-v2/tasks/SPI.stand

# 1. Вне окна (минуты не тратить): план и сухая проверка
$PY $S/run_stand.py --dry-run                 # печатает план, ничего не запускает
$PY -m py_compile $S/sim_v2.py $S/run_stand.py $S/count.py
$PY $S/run_stand.py --prepare-only            # копии манифеста и рецепта, проверка загрузки манифеста (запуска нет)

# 2. В stand-окне координатора (heavy; <сессия> — имя сессии лида):
bash "$(git rev-parse --path-format=absolute --git-common-dir)/../scripts/machine_gate.sh" heavy <сессия> \
  $PY $S/run_stand.py
# по окончании run_stand.py сам запускает count.py и печатает итог; повтор подсчёта без прогона:
$PY $S/count.py <stand-root>/run-<время>
```

Порты 5021 (сим) и 8765 (backend_ctl) должны быть свободны — иначе `preflight` прерывает прогон до запуска процессов.
`--only S1,S3` — часть сценариев (группы D и G идут всегда); `--no-vfd`; `--delay-ms`; `--boot-timeout`.

## Что делает прогон (по порядку)

1. preflight: порты, путь импорта из worktree, md5 `multiprocess_prototype/app.yaml` главного дерева, `git status` worktree.
2. Сим стартует **DOWN** (слушатель не поднят), задержка 300 мс; затем бэкенд `python -m multiprocess_prototype.main --headless`
   с `BACKEND_CTL=1`; ждёт ответ `device_list` с `robot_main` (ключ `devices` ищется в ответе на глубину 3: он может лежать во вложенном `result`;
   формы ответов `send_command`: команды хаба — dict без обёртки, `introspect.*` — `{type: response, success, result: {...}}`).
3. **D** (до связи, робот не подключён): `introspect.executors` и `introspect.status` у `devices`; `robot_point_list {device_id}`;
   `robot_point_list {}`; `robot_stop {}`; `vfd_get_status`.
4. **S0** — сим DOWN: `mark S0`, `device_connect`, через 0,5 с `device_disconnect`, сразу `up 300`; ждёт `disconnected`.
5. **S1 / S2 / S3** — «Отключить» посреди ручного подключения, момент — по журналу обмена драйвера (`robot_exchange_log_get`, опрос 25 мс):
   S1 — первая строка `out` после `connect ok` (probe); S2 — 3-я запись `PARAM_SET` из 58; S3 — первая строка `out` после 58-й `PARAM_SET`
   (после sync, до SERVO); потолок ожидания триггера 260 с (замер 2026-10-26: sync 58 `PARAM_SET` при 300 мс занял до ~150 с). Фаза в таблице **пересчитывается из журнала** (как в C-29), не берётся из триггера: триггер, попавший в соседнюю фазу, даёт итог `ФАЗА?`.
6. **G** (сим `delay 0`, иначе полное подключение занимает минуты): `device_connect` до `connected`; `robot_stop {device_id, level: SOFT}`;
   `vfd_get_status`; `robot_point_list`; `device_disconnect`. G идёт **после** S3 нарочно: подключённый робот оставляет воркер тика, и S0–S3 пошли бы по О12.
7. Останов: `system_shutdown` (graceful, без `taskkill`), сим — `quit`; порты свободны; `git status` и md5 `app.yaml` до = после.

## Ожидаемые числа (критерии SPI.injections.md; не хуже C-29)

| | фаза | SERVO+DO после команды | SOFT клиент/сим | до `disconnected` | статусы |
|---|---|---|---|---|---|
| S0 | до связи | 0 | 0/0, обмен сима после `up` до `MARK S1` — 0 | ≤ 1,23 с (C-29: 0,75) | connecting → disconnected |
| S1 | probe | 0 | 1/1 | ≤ 1,23 с (C-29: 1,22) | connecting → disconnecting → disconnected |
| S2 | sync_params k из 58 | 0 | 1/1 | ≤ 1,23 с (C-29: 1,23) | то же |
| S3 | после sync, до SERVO | 0 | 1/1 | ≤ 1,23 с (C-29: 0,91) | то же |

Порог критерия — 5,0 с: 1,23–5,0 с `count.py` пишет `PASS (>1,23 с)`, выше — `FAIL`. `disconnecting` в опросе 25 мс может не попасть в выборку (как в S0 C-29).
`count.py` считает обмен S0 **только до первой строки следующего сценария** (`MARK S1`) в `sim.log` — урок C-29 (прежний счётчик брал журнал до конца и дал ложный FAIL).

D/G, ожидается (печатает `count.py`):
- `introspect.executors`: `device_io`, `max_workers 4`, `max_pending 64`, 4 живых рабочих `keyed-device_io-0..3`;
- `robot_point_list {device_id}` → `status ok`, ключи `points`, `rev`;
- `robot_point_list {}` → ровно `{"success": False, "error": "key_missing", "command": "robot_point_list"}`;
- `robot_stop {}` → `status error`, «device_id обязателен» (контраст: не привязана к исполнителю);
- G: `robot_stop SOFT` → `status ok`, в журнале сима ровно 1 запись SOFT; `vfd_get_status` — ответ получен.
- Счёт SOFT: `STOP_REQ = stop_seq*4 + level` (`client_v2.py:113`), SOFT = 1, то есть **`значение & 3 == 1`**; значения 5, 9, 13, 17, 21 — все SOFT.
  Форму `robot_stop` / `vfd_get_status` «как на main» скрипт **не сверяет** (на main стенд не гонялся): сверять по снимкам d3 или прогоном на main.

## Чем наблюдается device_io

Прямого признака «исполнено на потоке `device_io`» в `backend_ctl` нет: строки логов без имени потока, `introspect.executors`
отдаёт тип/число рабочих без счётчиков (`pending_depth`, `running_keys` — в `unavailable`). Стенд берёт доказательства по цепочке:
1. `introspect.executors` у `devices`: исполнитель `device_io` создан из `executors:` манифеста (`base.yaml`), рабочие живы; рабочие — потоки `keyed-device_io-N` (видны и в `introspect.status`).
2. `robot_point_list {}` → `key_missing`: этот ответ даёт только `CommandManager` для команды **с привязкой к исполнителю** (`command_manager.py:426-434`); у команды без привязки пришло бы «device_id обязателен» (его контраст — `robot_stop {}`).
3. `robot_point_list {device_id}` через IPC вернула `ok` — ответ пришёл отложенно (`DEFERRED` + `reply` исполнителя), иначе `reply` не вызывался бы.
4. В логе `devices` нет строки «исполнитель … не найден» (А23 наоборот); `run_stand.py` кладёт строки про исполнитель в `checks.json` → `finish.devices_log_executor_lines`.

Это структурное доказательство, не замер потока. Сильнее — тест A17 (`обработчик исполнен не на потоке роутера`), он уже в наборе.

## Замер `introspect.*` после старта и режимы `--base`, `--race-only`

- Сразу после `Popen` бэкенда оркестратор опрашивает `devices` по кругу: `device_list`, `introspect.status`, `introspect.executors`
  (пауза между кругами 0,1 с, вызов ≤ 2 с, команда с первым `ok` больше не опрашивается; конец — все три `ok` либо 20 с после первого
  `device_list` с `robot_main`). Каждая попытка — строка `race.jsonl` (`i, cmd, t_start_s, t_end_s` от `Popen`, `ok`, `err`);
  итог — `race.json` (попыток до первого успеха, время первого успеха, тексты ошибок), он же в stdout и в выводе `count.py`.
- Наблюдение 2026-10-26: у `devices` сразу после старта `introspect.*` в части запусков отвечали «No handler for key …». Причина не
  установлена, разбирается отдельно. Группа D повторяет `introspect.*` (до 20 попыток, пауза 1 с); число попыток — `checks.json: D.introspect_attempts`.
- `--base` — дерево без `device_io` (main): проверки исполнителя печатаются как `n/a` и не краснят итог; `--race-only [--repeats N]` — только
  старт бэкенда и замер (без сима и сценариев, ~1 мин на повтор). Правило замера одно на оба дерева (`RACE_*`).

## Что пишет прогон (`<stand-root>/run-<время>/`)

`sim.log` (обмен и события сима, границы `MARK`), `sim.ctl`, `events.jsonl` (метки и команды оркестратора), `journal.jsonl`
(журнал драйвера, последняя версия строки по `seq`), `status.jsonl` (`devices.state.robot_main.conn`), `checks.json` (ответы D/G, итог уборки),
`logs/**` (логи бэкенда), `data/**` (реестр и хранилище), `backend.out.log`, `sim.out.log`.

## Время и процессы

- Время: полный прогон **2,5–2,9 мин** (3 запуска 2026-10-26; запуск с таймаутом триггера S3 — 5 мин): старт бэкенда 10–30 с, S0 ~3 с, S1 ~6 с, S2 ~10 с,
  S3 до ~2,5 мин, G ~15 с, останов ~5 с.
- Процессы: оркестратор 1 + сим 1 + бэкенд 4 (корневой/PM, `devices`, `gui` headless, `robot`) = **6 python** (оценка); плюс три сокета-клиента `backend_ctl` в потоках оркестратора.

## Что ненадёжно

- Подтверждено прогоном 2026-10-26: путь `state.get devices.state.robot_main.conn`, чтение `lines` журнала, формы ответов.
  Не подтверждено: ПЧ `vfd_belt` в стенде не подключается — `vfd_get_status` отвечает ошибкой «не подключено», успешная форма не наблюдалась;
  форма ответов `robot_stop` и `vfd_get_status` «как на main» не сверена.
- Триггеры S1–S3 — по тексту строк журнала, реакция ≈ 25 мс опроса + IPC; S3 («до SERVO») тоньше всех: окно — одно чтение TLM (0,3 с). Промах даёт `ФАЗА?`, не PASS.
- ПЧ `vfd_belt` в рецепте: хаб с ним стартует, но стенд ПЧ не подключает (`--no-vfd` убирает его).
- Вне критерия (как в C-29): окно О1, тик-переподключение (A7), jog/задания; по одному прогону сценария на запуск.
