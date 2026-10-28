# Стенд v2 T5.3e: `robot_park` (L1–L3) + регрессия SPI.stand

Копия `../SPI.stand/` с правками брифа 3s (`../T5.3e.3.md`, «Стенд v2»). Настоящий бэкенд через `Popen`
(`python -m multiprocess_prototype.main --headless`, `BACKEND_CTL=1`, настоящий `process.stop` при `system_shutdown`),
свой сим v2 `sim_v2.py` на `127.0.0.1:5021` unit 2, рецепт — копия `robot_demo.yaml` с `delta_v2`, устройство `robot_main`,
без камеры и дисплеев. **Не прогнан вживую** (написан вне окна `stand`, проверены компиляция, `--help`, `--dry-run` и счёт
`count.py` на выдуманных журналах). Раздел про `device_io` (чем он наблюдается, `D`) — в [`../SPI.stand/README.md`](../SPI.stand/README.md), здесь не повторяется.

| файл | что |
|---|---|
| `run_stand.py` | оркестратор: `--scenario P1\|P2\|P3`, `--regress`, `--repeats`, `--dry-run`, `--prepare-only`, `--race-only` |
| `count.py` | таблица критериев park по каталогам прогона (`PASS`/`FAIL` на критерий); для `--regress` — прежняя таблица S0/S1 + G |
| `sim_v2.py` | сим v2, **копия `SPI.stand/sim_v2.py` без правок** (`cmp` — совпадает) |

## Окружение

- Worktree `…/.claude/worktrees/robot-v2-t53e`; `run_stand.py` берёт его от своего места (`WORKTREE = HERE.parents[3]`) и сам
  прерывает прогон, если `multiprocess_framework` импортируется не оттуда. Python — главный `.venv`, `PYTHONPATH=<worktree>`;
  никаких `uv sync` / `uv run`; не запускать с cwd `process_module`.
- `--stand-root` по умолчанию `<tempdir>/t53e-stand` (на этой машине `C:/Users/INNOTECH/AppData/Local/Temp/t53e-stand`, вне git):
  `manifest/{app.yaml,stand_delta_v2.yaml}` и каталоги прогонов `run-<время>-<метка>/`.
- Порты 5021 и 8765 свободны — иначе `preflight` прерывает прогон до запуска процессов.

## Команды

```bash
cd D:/PROJECT_INNOTECH/Inspector_vision/Inspector_bottles/.claude/worktrees/robot-v2-t53e
export PYTHONUTF8=1 PYTHONPATH="$PWD"
PY=D:/PROJECT_INNOTECH/Inspector_vision/Inspector_bottles/.venv/Scripts/python.exe
S=plans/robot-protocol-v2/tasks/T5.3e.stand
G="$(git rev-parse --path-format=absolute --git-common-dir)/../scripts/machine_gate.sh"

# вне окна
$PY $S/run_stand.py --dry-run --scenario P1        # план; также --scenario P2 / P3, --regress
$PY -m py_compile $S/run_stand.py $S/count.py $S/sim_v2.py
$PY $S/run_stand.py --prepare-only                 # копии манифеста и рецепта в stand-root

# в stand-окне координатора (heavy; сессия — имя лида):
bash "$G" heavy <сессия> $PY $S/run_stand.py --scenario P1 --repeats 3
bash "$G" heavy <сессия> $PY $S/run_stand.py --scenario P2 --repeats 3
bash "$G" heavy <сессия> $PY $S/run_stand.py --scenario P3 --repeats 3
bash "$G" heavy <сессия> $PY $S/run_stand.py --regress            # один прогон: D, S0, S1, G
# S2/S3 нужны отдельно (S3 до ~2,5 мин): $PY $S/run_stand.py --only S2,S3

# повторный подсчёт без прогона (один или несколько каталогов):
$PY $S/count.py <stand-root>/run-<время>-P1 [<другой каталог> ...]
```

## Что делает прогон `--scenario`

1. preflight; сим стартует DOWN, задержка **0 мс** (при 300 мс полный `connect` идёт минуты); бэкенд; замер гонки `introspect.*`; группа **D** (связи нет).
2. Сим `up 0`; `device_connect`; **готовность C-57**: `.conn` → `connected` (`t_conn` = этот момент), затем `.status.ts > t_conn`; по 20 с, шаг 0,05 с; число попыток — событие `ready`.
3. `mark P<n>` в `sim.log`, сценарий (ниже), затем `finish`: `system_shutdown` (настоящий `process.stop`), `quit` симу, порты, `git status`, md5 `app.yaml`, `count.py`.
4. `--repeats N` (умолчание 3) — **повтор прогона целиком**, каждый в своём `run-<время>-P<n>/`; в конце один вызов `count.py` по всем каталогам.
   Для `--race-only` `--repeats` — прежняя семантика (повтор замера, умолчание 1).

| | сценарий (L) | итог — по `devices.state.robot_main.park` (опрос 0,05 с, дедлайн 40 с, `value.seq == seq ответа`, `state in {done, failed}`) |
|---|---|---|
| P1 = L1 | поток-держатель `robot_jog_hold` каждые 0,05 с (≤ 0,1 с) до возврата `system_shutdown`; `moving` из `.status.telemetry`; +0,3 с → `robot_park` | `done`, `home == moved` |
| P2 = L2 | `robot_jog_step dx=80` (вне дома, без jog-удержания); `robot_park` → `done`; `robot_servo on`; второй `robot_park` | второй: `home == already` |
| P3 = L3 | `robot_point_save` a, b; `robot_program_save` `p3` (20 ходов JOINT a/b); `robot_program_run`; `done ≥ 3` → `robot_park`; опрос `.program` каждые 25 мс | `done`, `moved`; `aborted` пользователя раньше `park_home` |

## Пороги (литералы в `count.py`)

- **P1:** ответ `accepted is True` и ≤ `1.0` с; итог `done`, `home == "moved"`, ≤ `30.0` с от ответа; `jog_hold` после ответа ≥ `3`, из них `ok` — `0`;
  `L1 == 0`, `A1 == 0`, `E1 == 0`; `d1 == 2`; последняя запись `STOP_REQ & 3 == 1`.
- **P2:** второй итог `home == "already"` за ≤ `1.5` с от ответа; `d1 == 1`; `L1 == 0`.
- **P3:** `p3`/`aborted` раньше `park_home` в `program.jsonl`; итог `done`/`moved`; `L1 == 0`, `A1 == 0`.
- `d1` — все записи `W STOP_REQ` в `sim.log` от `MARK P<n>` до конца прогона (все уровни); `L1` / `A1` / `E1` — строки «робот 'robot_main': jog остановлен поводком: окно удержания истекло» / «… после начала остановки» / «… область закрывается» в `logs/**`.
- Итог `STAND: PASS` и код 0 — только если все строки PASS (и группа D, уборка). По каталогам из `--repeats`: `P1: k/N`.
- `count.py` печатает «В отчёт»: время ответа, `elapsed_s`, тиков до итога (`elapsed_s / 0,5`), `d1`/`L1`/`A1`/`E1`, итог → `process.stop`, длительность `system_shutdown`, строки `stop_echo` в логах, «поводок jog прерван», попытки готовности.
- `--regress`: S0, S1 и G с прежними порогами SPI.stand (≤ 1,23 с, SOFT 1/1, G — 1 SOFT); S2/S3 не гоняются (проверяют `sync_params`, который park не меняет).

## Файлы прогона (`run-<время>-<метка>/`)

Прежние: `sim.log`, `events.jsonl`, `journal.jsonl`, `status.jsonl`, `checks.json`, `race.jsonl`, `logs/**`, `data/**`, `*.out.log`. Новые:
`park.jsonl` (смена значения `.park`, `t`, `label`), `jog.jsonl` (P1: `t` отправки, `t_rx`, `status`, `message` каждого `jog_hold`),
`program.jsonl` (P3: смена `name/state/done` в `.program`). События: `ready`, `park_reply`, `park_final`, `shutdown_send`, `shutdown_reply`, `precondition_failed`.

## Время (оценка, не замерено)

Один прогон park ~1–1,5 мин (старт бэкенда 10–30 с, D ~10 с, подключение ~5 с, сценарий 2–35 с, останов ~5 с); `--repeats 3` — 3–5 мин на сценарий;
`--regress` ~1,5–2 мин (S0 ~3 с, S1 ~6 с, G ~15 с). Весь набор окна (P1, P2, P3 по 3 + regress) ~12–18 мин.

## Что ненадёжно

- Не прогнан: `park.jsonl`, `jog.jsonl`, `program.jsonl`, события, готовность C-57 не видели живого бэкенда. `count.py` проверен только на выдуманных журналах.
- Форма `.status`: `telemetry.moving` и `telemetry.x_mm` взяты из `drivers/base.py::snapshot` и живого теста (`robot_get_telemetry`); что `.status` у v2 несёт ключ `telemetry`, живьём не подтверждено.
- `robot_servo on` во втором park P2 ждётся `sleep 0,5 с`, не по телеметрии; `P2` вывод из дома — `jog_step dx=80` (допуск «дома» не известен: меньше 80 мм не пробовалось).
- «Здоровье» `device_hub.stop_echo` после выключения не опрашивается (бэкенда уже нет): в отчёт идёт число строк `stop_echo` в логах, это не health.
- Времена «итог за …» и «≤ 1,5 с от ответа» меряются опросом `state.get` (шаг 0,05 с): ошибка до +0,05 с и задержка IPC. Порядок `aborted` → `park_home` — опросом 25 мс; пропуск тика исключён только тем, что `aborted` держится ≥ 0,5 с (по брифу).
- `d1` считает строки `W STOP_REQ` в `sim.log` без разбора автора записи; если сим не склеивает повторы (журнал строка на запись) — верно, иначе заниженный счёт.
- Рецепт по-прежнему называется `spi_stand_delta_v2` (копия `prepare_copies` без правок имени); `device_io`-проверки группы D те же, что в SPI.stand.
