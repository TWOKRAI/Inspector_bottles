# release-1.0 — спецификация приёмки (вехи α и β)

ТЗ для задач [`plan.md`](plan.md) и для скрипта α (word-layout P4, ORDER #12). Литералы §1–§2.7 сверены с кодом `main` =
`57d1491fd` (2026-11-10, Task 1.1; записи `amendments.md` 6–17). Первая редакция — по `main` = `b7da49e51` (2026-10-25).
Решение владельца 25 (`plans/queue/decisions.md:36`) учтено. Номера строк в цитатах — на `57d1491fd`; §2.8 и §3 в
Task 1.1 по цитатам не перечитывались (литералы окон съёма не менялись), §2.9 — историческая справка.

## 1. Источники записей

| Запись | Источник | Как читать | Доказательство |
|---|---|---|---|
| Связь с роботом | state `devices.state.robot_main.conn` = `{"conn": …, "ts": tick_n}` (пишется каждый тик) | опрос `state_get`, условие `["conn"] == "connected"`; `await_condition` по равенству словаря не сработает (`ts` меняется) | `Plugins/hub/device_hub/plugin.py:546`; сравнение `==` — `backend_ctl/conditions.py:331` (дельты) и `:352` (read-model) |
| Параметр `P_PICK_RZ` | файл `data/robot/robot_main/params.yaml` (вне git) | `send_command("devices", "robot_param_get_all", {"device_id": "robot_main"})` → `params.P_PICK_RZ.raw` | команда сгенерирована из операции `param_get_all`: `Plugins/hub/device_hub/plugin.py:1051-1079`, `Services/device_hub/spi.py:371`, `Services/device_hub/robot_data_ops.py:124-130`; источник — `Services/robot_comm/robot_data.py:136, 192` |
| Слово | регистр `word_layout` процесса `layout` | `set_register_verified("layout", "word_layout", "target_word", <слово>)` | `backend_ctl/driver.py:1479-1489` → `backend_ctl/registers.py:139-165`; регистр = имя плагина — `backend_ctl/registers.py:113-119` |
| Журнал диска: буква, угол, решение, задание | одна строка INFO на каждый диск в журнале процесса `layout` (`ctx.log_info`): `WordLayoutPlugin: диск '<Б>' <угол>° → <решение>`; литералы решений — §2.3 | `log_tail("layout", level="INFO")` **до** первого слова (умолчание `ERROR`, подписка — с момента вызова); `events_page("logs", cursor=…, limit=500)`: у элемента `item["event"]["command"] == "log.record"`, текст — `item["event"]["data"]["record"]["message"]` (с префиксом `WordLayoutPlugin: `) | `Plugins/processing/word_layout/plugin.py:269-271` (строка), `:201, 217-219, 248-250` (решения); `backend_ctl/driver.py:2260-2275` (`log_tail`); `backend_ctl/events.py:168` (плоскость `logs`), `:449-532` (форма страницы), `:637`; `multiprocess_framework/modules/logger_module/channels/router_push_channel.py:73-82` (конверт). Так читает P4: `scripts/alpha_sim/run_alpha.py:160-190` |
| Прогресс слова | регистр `word_layout` процесса `layout`: `word_norm`, `slots_total`, `slots_filled`, `jobs_emitted`, `done`, `next_letter` — обновляется сразу при решении. State `processes.layout.state.word_layout` (поле `word`) — только справка: пишется не чаще 1 раза в 1 с и лишь внутри `process()`, после последнего диска не обновится | `introspect_registers("layout")`, поля регистра `word_layout` | `word_layout/plugin.py:240-244, 453-457` (регистры), `:29, 159-162, 569-587` (state); так читает P4: `scripts/alpha_sim/run_alpha.py:343, 437, 543` |
| Задание `CVT_JOB` | журнал обмена драйвера (T5.6, `6b16c17fb`), включён по умолчанию | `send_command("devices", "robot_exchange_log_get", {"device_id": "robot_main", "since_seq": N0, "limit": 2000})`; требование `dropped == 0` | `Services/device_hub/drivers/exchange_log.py:119-155` (строка на слово), `:214` (`enabled=True`), `:235` (`limit` по умолчанию 200), `:285-286, 301` (`dropped`) |
| Задание у робота | счётчики сима: `send_command("robot", "sim_robot.status", {})` → `journal.jobs` (принятые `CVT_JOB`) и `journal.done` (`[v2] DONE seq=<n> op=CVT_JOB`). Строки `[v2] CMD seq=<n> op=CVT_JOB` и `[v2] DONE seq=<n> op=CVT_JOB` — в `sim_robot.journal` (кольцо `recent` на 50 строк с тегами `job`/`dup`/`done`; `wire` — 200 строк всех записей), счёт по кольцам не вести | `BackendDriver(port=8766)`, опрос ≤ 0,25 с | строки пишет сим: `Services/robot_comm/server/sim_core_v2.py:1440` (CMD), `:968` (DONE); разбор и счётчики — `Services/robot_comm/server/sim_journal.py:95, 358-361, 379-396`; команды и кольца — `Plugins/sim/robot_host/plugin.py:76-83, 146-153, 825`; CMD — `docs/reports/2026-10-19_T5.6_stand.md:12`; так читает P4 — `scripts/alpha_sim/run_alpha.py:403-405` |
| Стоп | журнал обмена: `W STOP_REQ = n`, `n = stop_seq·4 + level`, `stop_seq` накопительный; SOFT = 1 | строки журнала обмена после S9; процесс к этому времени остановлен, поэтому — файл `<INSPECTOR_LOG_DIR>/devices/robot_exchange.log`: путь и имя — по стенду P4 (`scripts/alpha_sim/run_alpha.py:655`, `scripts/alpha_sim/tests/fixture_p4_stand_exchange_file.py:2`), писатель файла в коде не найден | `Services/robot_comm/core/client_v2.py:113, 386-394, 705`; адрес — `Services/robot_comm/core/protocol_v2.py:16`; имя адреса — `exchange_log.py:78, 88` |
| «Домой» | ручная команда хаба: `send_command("devices", "robot_park_all", {"timeout_s": 30.0}, timeout=40.0)`. Ответ: `{"status": "ok", "robots": {"robot_main": {"result": "done", "seq": k, "home": "moved" \| "already", "elapsed_s": e}}}`; итог — state `devices.state.robot_main.park` = `{seq, state: "done", step, home}`, терминал сравнивается по `seq` ответа | на проводе (журнал обмена) при `home == "moved"`: `W* CMD_OPCODE = 48 (SC_RUN)`, затем `W* CMD_OPCODE = 65 (SERVO)` и `W* CMD_ARGS[0] = 0`; при `already` — только `SERVO` с `ARGS[0] = 0`; строки `STOP_REQ` в блоке «домой» нет | `Plugins/hub/device_hub/plugin.py:131, 919-934`; `Services/device_hub/manager.py:618, 654`; автомат — `Services/device_hub/drivers/robot_driver_v2/park.py`, программа `park_home` — `programs.py:127-128`; опкоды — `Services/robot_comm/protocols/delta_v2.yaml` (`SC_RUN` 0x30 = 48, `SERVO` 0x41 = 65); судья P4 — `scripts/alpha_sim/logic.py:604-641` |

## 2. Веха α — скрипт через backend_ctl (код — word-layout P4)

### 2.1 Предусловия (каждое — шаг через координатора или строку очереди, не механизм плана)

- Окно `stand`. `apps/line_sim/run.py` с `BACKEND_CTL=1 BACKEND_CTL_PORT=8766`; `multiprocess_prototype/run.py letter_robot_sim --headless`
  с `BACKEND_CTL=1` (8765), `INSPECTOR_LOG_DIR=<дерево>/data/logs/prototype` и `INSPECTOR_MANIFEST` на копию `app.yaml` (C-21).
  Форма — стенд T5.6 (`docs/reports/2026-10-19_T5.6_stand.md:3`); команды запуска — `scripts/alpha_sim/README.md`.
- **Каталог сима — весь алфавит** (решение 25; ORDER #3, R1b влит). `data/line_sim/letters_ink` — 33 буквы, 66 файлов
  (`built letters_ink 66 files`); каталог вне git, его собирает `python -m Services.line_sim.tools.build_stand_assets` в дереве
  стенда (`_LETTERS` — 33 буквы, `Services/line_sim/tools/build_stand_assets.py:62`); 33 класса — как у сети
  (`data/models/mobilenet_v3_large_20260616_050828_classes.txt`). В каталоге есть П Е Р М И А Б (`docs/reports/2026-11-09_R1.md`).
- **Подача дисков по списку `{буква, угол}`** — ORDER #3 (R1, влит; `amendments.md` 4). Команда `scene.sequence` процесса
  `camera` (порт 8766): `{"discs": [[буква, угол], …]}` — загрузить, если прошлый список исчерпан; `{"discs": …, "replace": true}` —
  заменить, остаток выброшен; `{"random": true}` — вернуться к случайным. Угол — градусы `[0, 360)`, ноль — буква прямо.
  Ответ в поле `result`: `{"status": "ok", "queued": N, "dropped": M}`; ошибки — `busy` (+`remaining`), `invalid` (+`index` или
  `unknown`). Подача не чаще 1 диска в 1 с (`SEQUENCE_MIN_INTERVAL_S`, `Services/line_sim/core/spawner.py`). Порядок для
  скрипта: `scene.defect_rate {"probability": 0.0}` (перед B; иначе `defect_probability` 0,25 действует и на диски списка) →
  `scene.pause {"paused": true}` → опрос `scene.status.active == 0` (≈ 25–30 с, срок 60 с) → слово в регистр →
  `scene.sequence` → `scene.pause {"paused": false}`. Код — `Plugins/sim/scene_source/plugin.py:199` (таблица команд), `:584`
  (`scene.pause`), `:635` (`scene.defect_rate`), `:702` (`scene.sequence`). Литералы B подтверждены на симе, 12 из 12 по порядку
  (`docs/reports/2026-11-09_R1.md`).
- **Геометрия ячеек, журнал каждого диска, смена слова на ходу, C-32** — ORDER #10 (word-layout P3) влит, C-32 влит
  (`9c477e5dc`). α берёт рецепт `letter_robot_sim.yaml` как есть, регистров геометрии не правит.
- **Конвенция угла** сим ↔ сеть (знак, ноль) совпадает, `angle_invert` и `angle_zero_deg` не ставятся. Рендер: угол в градусах,
  положительный — против часовой стрелки на экране, ось Y вниз (`Services/layer_render/layers.py:9-13`); сеть отдаёт
  `atan2(sin, cos)` в градусах в `[0, 360)` (`Services/ml_inference/core/postprocess.py:20-38`); доворот —
  `wrap180(angle_zero_deg − sign·угол сети)` при `0` и `+1` (`word_layout/geometry.py:88-102`; рецепт
  `letter_robot_sim.yaml`: `angle_zero_deg 0.0`, `angle_invert false`). Кодирование метки обучения — `sin/cos` угла без смены
  знака (`Services/dataset_gen/core/symmetry.py:164-181`, `encode_angle`), что согласуется с «инверсии нет». Оговорка: для
  симметрии «180» угол сети выходит в `[0, 180)` (`postprocess.py:36-43`). Вывод «инверсии нет» держится на числах стенда:
  P4, прогоны 6–8 (2026-11-10), 15 дисков с совпавшей буквой: медианы Δ (сеть − подача) +2,2 / +2,4 / +2,0°, |Δинв| 53…178°
  (`docs/reports/2026-11-10_word-layout_P4.md`). Таблицы
  `ARGS[9]` §2.3 при отсутствии инверсии не пересчитывались. Точность сети — отдельный вопрос (§2.3, ORDER #27).

### 2.2 Шаги

| Шаг | Вызов | Ожидаемо (литерал) |
|---|---|---|
| S0 | `connect()`; опрос `state_get("devices.state.robot_main.conn")` раз в 0,5 с, срок 60 с | `["conn"] == "connected"` (`device_hub/plugin.py:443-448, 546`) |
| S1 | `robot_param_get_all {"device_id": "robot_main"}` | `params.P_PICK_RZ.raw == -1000` (умолчание `delta_v2.yaml:630`); иное — стоп, пересчёт `ARGS[9]` записью `amendments.md` |
| S2 | `log_tail("layout", level="INFO")` | подписка ок; дальше чтение `events_page("logs", …)` |
| S3 | `send_command("devices", "vfd_run", {"device_id": "vfd_belt", "freq_hz": 10.0})` | `ok` (команда сгенерирована из операции `run`: `device_hub/plugin.py:1051-1079`, `Services/device_hub/drivers/vfd_driver.py:208, 250`; 10 Гц — `default_freq_hz` рецепта); лента 20,2 мм/с = 101,1311 × 10/50 (`apps/line_sim/pipeline.yaml`, `belt_mm_s_at_max_freq`) |
| S4 | перед каждым случаем: дождаться хвоста прошлого случая — по факту выданных заданий (прирост регистра `jobs_emitted`; красный случай не блокирует следующий): столько же строк `CVT_JOB` в журнале обмена и прирост `sim_robot.status.journal.done` на столько же (B 9, D 3, C 3; `done` в state публикуется раньше последнего задания); 3,0 с тишины в журнале `layout`; затем `robot_exchange_log_set {"device_id": "robot_main", "clear": true}`; читать случай — тоже после этого счёта | `ok`; N0 = `last_seq` |
| S5 | `defect_rate 0` → пауза → `active == 0` → случай B (§2.4): `set_register_verified(…, "target_word", "ПЕРЕМИРИЕ")`; `scene.sequence` → снять паузу | §2.4 |
| S6 | случай D (§2.5): пауза → `active == 0` → без перезапуска `set_register_verified(…, "target_word", "МИР")`; `scene.sequence` → снять паузу | §2.5 |
| S7 | случай C (§2.6): пауза → `active == 0` → без перезапуска `set_register_verified(…, "target_word", "ПЕРЕМИРИЕ")`; `scene.sequence` → снять паузу | §2.6 |
| S8 | «домой»: `send_command("devices", "robot_park_all", {"timeout_s": 30.0}, timeout=40.0)` | §2.7 |
| S9 | `system_shutdown()` | §2.7 |

Смена слова: раскладка пересобирается только на **следующем item** (`_ensure_assembler` зовётся из `_handle_item`,
`word_layout/plugin.py:170`; подпись слова — `:432-444`), до него регистры держат старое слово и `done`. Поэтому ждать
**все поля регистра вместе**: `word_norm`, `slots_total`, `slots_filled`, `jobs_emitted`, `done`; срок 180 с на случай.
State публикуется ≤ 1 раза в 1 с (`:29, 159-162`) и после последнего диска не обновится — на него не опираться.

### 2.3 Геометрия ячеек и общие поля задания

Ячейки — линия от первого диска с шагом `2 × disk_radius_mm 55 = 110` (`word_layout/plugin.py:417-428`,
`geometry.py:64-85`; режим `use_pitch: true`), x = `first_x`, y_i = `first_y` + 110·i. Рецепт `letter_robot_sim.yaml:315-316`:
`first_x 320.0`, `first_y −440.0` (word-layout P3; прежнее `first_y −200` выводило ячейки 7, 8 — y 570, 680, радиус 653 и
751 мм — за досягаемость сима `P_WS_R_MAX` = 600,0 мм, `delta_v2.yaml:647`, а `CVT_JOB` в симе проверяет зону:
`sim_core_v2.py:1621-1626`). При `−440` радиусы ячеек 320,0…544,1 мм. Колонки ниже — **значения рецепта**, пересчитаны через
настоящий `Services/robot_comm/core/client_v2._geom_words` (×10: `WIRE_SCALE`, `delta_v2.yaml:524`; отрицательное — u16:
`& 0xFFFF` в `_encode_word`, `client_v2.py:144-154`; `cvt_job` — `:881-902`).

| Ячейка i | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|---|
| y, мм | −440,0 | −330,0 | −220,0 | −110,0 | 0,0 | 110,0 | 220,0 | 330,0 | 440,0 |
| `ARGS[7]` | 61136 | 62236 | 63336 | 64436 | 0 | 1100 | 2200 | 3300 | 4400 |

Общее для каждого `CVT_JOB` (15 строк подряд): `W* CMD_OPCODE = 32 (CVT_JOB)`, `W* CMD_ARGC = 10`, `ARGS[0]`/`[1]` — энкодер
(литералом не проверяется: `pixel_to_robot` не даёт `e_capture`, драйвер читает энкодер при постановке, `jobs.py:159-160`),
`ARGS[2]` pick_x ∈ 4549…4615, `ARGS[3]` pick_y ∈ 62096…62116 (§2.8), `ARGS[4]` pick_z = 64216 (−132,0), `ARGS[5]` flags = 3
(`jobs.py:70`), `ARGS[6]` place_x = 3200 (`first_x 320.0`), `ARGS[8]` place_z = 64216, `W CMD_FLAG = 1`, ответ
`R RES_SEQ..+12 RES_SEQ = <seq>, RES_STATUS = 1, RES_ERRNO = 0 (ОК)`.

Доворот: `r = wrap180(0 − угол сети)` (`geometry.py:88-102`; угол — из сети, `word_layout/plugin.py:190, 205-212`), допуск ±5°
до замера letters-retrain 0.4 (ORDER #27). `ARGS[9] = 10 · (P_PICK_RZ −100,0° + r)` (`jobs.py:73`), допуск ±50.

| Угол диска | r в журнале | `ARGS[9]` |
|---|---|---|
| 0° | −5,0…5,0 | 64486…64586 |
| 30° | −35,0…−25,0 | 64186…64286 |
| 60° | −65,0…−55,0 | 63886…63986 |
| 90° | −95,0…−85,0 | 63586…63686 |
| 300° | 55,0…65,0 | 65086…65186 |
| 330° | 25,0…35,0 | 64786…64886 |

Слот повторной буквы — первый незаполненный слот этой буквы в порядке слова (`assembler.py:113-124`, цикл поиска `:113-114`).

Журнал диска — одна строка INFO на каждый диск: `WordLayoutPlugin: диск '<Б>' <угол>° → <решение>` (`word_layout/plugin.py:269-271`;
буква — верхний регистр, угол сети с одним знаком, `-0.0` не печатается; кадр ниже порога — не диск, строки нет). Решения,
литералы кода:

- взят: `ячейка <N>: взять(<px>,<py>) → положить x<..> y<..> z<..> r<..>° [<k>/<n>]` (`:245-250`; без `взять(…) → `, если координаты
  забора нет и `require_pick` выключен);
- пропуск: `пропуск: нет в слове '<слово>'` (`:219`); `пропуск: ячейки '<Б>' заняты (<i>, <j>, …)` — номера занятых ячеек этой буквы
  (`:217`); `пропуск: слово готово` (`:181`; диск после `done` уходит до `offer`); `пропуск: слово не задано` (`:168`);
  `пропуск: нет координаты забора` (`:201`). «Слово готово» и «слово не задано» пишутся один раз на диск (`_note_skip_once`, `:280-303`);
- слово: `WordLayoutPlugin: слово '<СЛОВО>' (источник: регистр)` при первой установке (`:465`); смена —
  `WordLayoutPlugin: смена слова '<старое>' → '<новое>' (источник: регистр) — ячейки с нуля (было заполнено <k>/<n>)` (`:467-470`);
  смена геометрии — `WordLayoutPlugin: геометрия ячеек изменена — ячейки с нуля (было заполнено <k>/<n>)` (`:472-474`).

Литералы закреплены тестами `Plugins/processing/word_layout/tests/test_p3_disk_journal.py` и перечислены в
`Plugins/processing/word_layout/README.md:119-132`; их читает скрипт α (`scripts/alpha_sim/logic.py`, `_DISK_RE`, `_TAKE_RE`).

### 2.4 Случай B — «ПЕРЕМИРИЕ» (слово 1.0, основная приёмка)

Ячейки: П 0, Е 1, Р 2, Е 3, М 4, И 5, Р 6, И 7, Е 8. Диски (соседи разные):
`[["Р",0],["А",0],["Е",30],["И",60],["Е",90],["Б",0],["Р",300],["Е",330],["И",30],["Е",60],["П",90],["М",300]]`.
Код (`assembler.py:113-114`) даёт то же назначение, что гипотеза лида. Строка слова перед первым диском:
`WordLayoutPlugin: слово 'ПЕРЕМИРИЕ' (источник: регистр)`.

| # | Диск | Решение | `ARGS[7]` | r | `ARGS[9]` | прогресс |
|---|---|---|---|---|---|---|
| 1 | Р 0° | ячейка 2 | 63336 | −5…5 | 64486…64586 | [1/9] |
| 2 | А 0° | пропуск: нет в слове 'ПЕРЕМИРИЕ' | — | — | — | — |
| 3 | Е 30° | ячейка 1 | 62236 | −35…−25 | 64186…64286 | [2/9] |
| 4 | И 60° | ячейка 5 | 1100 | −65…−55 | 63886…63986 | [3/9] |
| 5 | Е 90° | ячейка 3 | 64436 | −95…−85 | 63586…63686 | [4/9] |
| 6 | Б 0° | пропуск: нет в слове 'ПЕРЕМИРИЕ' | — | — | — | — |
| 7 | Р 300° | ячейка 6 | 2200 | 55…65 | 65086…65186 | [5/9] |
| 8 | Е 330° | ячейка 8 | 4400 | 25…35 | 64786…64886 | [6/9] |
| 9 | И 30° | ячейка 7 | 3300 | −35…−25 | 64186…64286 | [7/9] |
| 10 | Е 60° | пропуск: ячейки 'Е' заняты (1, 3, 8) | — | — | — | — |
| 11 | П 90° | ячейка 0 | 61136 | −95…−85 | 63586…63686 | [8/9] |
| 12 | М 300° | ячейка 4 | 0 | 55…65 | 65086…65186 | [9/9] |

Регистры `word_layout` (`introspect_registers("layout")`): `word_norm "ПЕРЕМИРИЕ"`, `slots_total 9`, `slots_filled 9`,
`jobs_emitted 9`, `done true`. Журнал обмена: 9 `CVT_JOB`; сим: 9 CMD и 9 DONE (`journal.done` +9). Журнал дисков: 12 записей
(9 ячеек + 3 пропуска). Стенд P4, прогоны 6–8: 12 строк, 9 `CVT_JOB`, регистры совпали (геометрия съёма и угол — красные, §2.8).

### 2.5 Случай D — смена слова на ходу: «ПЕРЕМИРИЕ» → «МИР» без перезапуска

После §2.4 (слово готово) — `target_word = "МИР"`. По коду первый же диск пересобирает раскладку: новый `WordAssembler`,
все ячейки свободны, `slots_filled 0`, `next_letter` нового слова, взвод сброшен (`word_layout/plugin.py:430-462`);
`jobs_emitted` не сбрасывается (растёт только на `:240`). Ячейки «МИР» — 0, 1, 2 той же геометрии; там уже лежат диски П, Е, Р
прошлого слова. Правило владельца (2026-10-25): смена слова = оператор убрал собранное, ячейки с нуля. Правило закреплено
word-layout P3: строка `WordLayoutPlugin: смена слова 'ПЕРЕМИРИЕ' → 'МИР' (источник: регистр) — ячейки с нуля (было заполнено 9/9)`
(`plugin.py:467-470`) и тесты — смена посреди слова `test_p3_disk_journal.py:258-278` (RED 8), смена на «МИР»
`Plugins/processing/word_layout/tests/test_disk_identity.py:85-111`. Строка смены пишется перед первым диском случая.
Диски: `[["П",0],["М",30],["Е",0],["И",90],["Р",300]]` — П и Е были в прошлом слове, в новом их нет.

| # | Диск | Решение | `ARGS[7]` | r | `ARGS[9]` | прогресс |
|---|---|---|---|---|---|---|
| 1 | П 0° | пропуск: нет в слове 'МИР' (пересборка на этом item) | — | — | — | — |
| 2 | М 30° | ячейка 0 | 61136 | −35…−25 | 64186…64286 | [1/3] |
| 3 | Е 0° | пропуск: нет в слове 'МИР' | — | — | — | — |
| 4 | И 90° | ячейка 1 | 62236 | −95…−85 | 63586…63686 | [2/3] |
| 5 | Р 300° | ячейка 2 | 63336 | 55…65 | 65086…65186 | [3/3] |

Регистры: `word_norm "МИР"`, `slots_total 3`, `slots_filled 3`, `jobs_emitted 12`, `done true`. Журнал обмена: ровно 3 `CVT_JOB`,
все с `ARGS[7]` ячеек 0…2 — заданий по старому слову нет. Журнал `layout`: строка смены и 5 строк дисков. Стенд P4, прогоны 6–8:
5 строк, 3 `CVT_JOB`, регистры совпали.

### 2.6 Случай C — одинаковые диски подряд (обязателен; C-32 влит `9c477e5dc`)

Без перезапуска `target_word = "ПЕРЕМИРИЕ"`: первый диск пересобирает раскладку, ячейки пусты (`plugin.py:430-474`); строка
`WordLayoutPlugin: смена слова 'МИР' → 'ПЕРЕМИРИЕ' (источник: регистр) — ячейки с нуля (было заполнено 3/3)`.
Диски `[["Е",0],["Е",30],["Е",60],["Е",90]]`.
**Ожидание (решение 25):** Е 0° → ячейка 1 (`ARGS[7]` 62236, `ARGS[9]` 64486…64586, [1/9]); Е 30° → ячейка 3 (64436,
64186…64286, [2/9]); Е 60° → ячейка 8 (4400, 63886…63986, [3/9]); Е 90° → `пропуск: ячейки 'Е' заняты (1, 3, 8)`. Регистры:
`word_norm "ПЕРЕМИРИЕ"`, `slots_filled 3`, `jobs_emitted 15`, `done false`. Журнал обмена: 3 `CVT_JOB`.
Механизм (C-32): диск различается по `sidecar.track_id`, который ставит `center_crop` (`word_layout/plugin.py:500-505, 524-545`;
`Plugins/processing/center_crop/plugin.py:189`; без `filtered` выходов нет — `:80-83`), поэтому два одинаковых диска подряд
берутся оба. Стенд P4, прогоны 6–8: 4 строки диска, 3 `CVT_JOB`, `jobs_emitted 15`.

### 2.7 «Домой» и чистый стоп

- S8: ручная команда хаба `robot_park_all` (`{"timeout_s": 30.0}`, ответ ждать до 40 с). PASS, если
  одновременно: `status == "ok"`; `robots.robot_main.result == "done"`; `home ∈ {"moved", "already"}`; `devices.state.robot_main.park`
  догнал ответ (`seq` совпал, `state == "done"`; первому снимку не верить, срок 5 с); в журнале обмена после S7: при `moved`
  — `W* CMD_OPCODE = 48 (SC_RUN)` раньше `W* CMD_OPCODE = 65 (SERVO)`, и в блоке `SERVO` строка `W* CMD_ARGS[0] = 0`; строки
  `STOP_REQ` нет (`scripts/alpha_sim/logic.py:604-641`, `run_alpha.py:628-648`). Стенд P4, прогоны 6–8: PASS, `home moved`, 1,39–1,51 с.
  Команда `robot_park_all` — T5.3e.5 (`Plugins/hub/device_hub/plugin.py:131, 919-934`); T5.3e.6 в `main` не влита (не блок для α).
- S9: ответ `system_shutdown` без ошибки; в журнале обмена после S8 ровно одна строка `W STOP_REQ = n` с `n % 4 == 1`
  (SOFT). Две строки SOFT допускает ADR-DH-011 (H19) только при стопе, пересекающем `connect`/`disconnect`
  (`Services/device_hub/DECISIONS.md:123-130`, `docs/adr/ADR-DH-011.md`); в S9 робот подключён и простаивает, пересечения нет —
  вторая строка считается красной. Затем строка `disconnect` (`docs/reports/2026-10-19_T5.6_stand.md:13`). После: порт 8765
  свободен, процессов с путём дерева нет; с 1.10 (ORDER #5) — `outcome` каждого ребёнка `exited`.

### 2.8 Окна съёма

Из геометрии, не со стенда. `pixel_to_robot` в линейном режиме (`letter_robot_sim.yaml`, `use_linear: true`;
`pixel_to_robot/plugin.py:132-146`): x = 497,4 − 78,4·v/481, y = −282 − 98·u/800. Центр диска v = 240,5 (`belt_y_px 537.5` −
ROI y 297) → x = 458,2; сдвиг сима ±10…20 px (`lateral_offset_px`) → x ∈ 454,9…461,5. Триггер `line_filter` — вход центра в
зону [251, 501] px (`Plugins/filter/line_filter/plugin.py:141-196`, `_apply_zone_edge`; конфиг `letter_robot_sim.yaml:228-232`:
`center_x 376`, `zone_width 250`, `mode zone_edge` → 251…501); при 20,2 мм/с и 25 к/с ход 6,6 px за кадр → u ∈ 494,4…501 → y −343,4…−342,6; окно −344,0…−342,0. Сужать окно — только решением
владельца после красного прогона, с причиной в `amendments.md`.

### 2.9 Подача дисков до R1 (историческая справка)

До R1 фабрика сцены звала `render` без `class_index`, угол был `uniform(angle_range_deg)`, команд выбора диска не было;
`preset.commit` фиксировал угол всем дискам сразу. R1 влит (`10d50e315`, `amendments.md` 4): подача по списку — §2.1. Запасной путь
через `seed` (line-sim Ф3, `plans/line-sim/phase-3-object-engine.md:563-564`) исторический: не используется, режим «smoke α»
для него не нужен. Ограничение «не чаще одного диска в 1 с» осталось и действует в коде (`SEQUENCE_MIN_INTERVAL_S`): публикация
state `word_layout` — не чаще 1 раза в 1 с, поэтому ожидание берётся с регистров (§1).

## 3. Веха β — чек-лист железа

| # | Проверка | Условие прохода | Строка / Task |
|---|---|---|---|
| β1 | MVS на ядре `camera_device` | `introspect_plugins("camera_0")` — плагин ядра, не `HikvisionCameraPlugin` (сейчас он, `hikvision_letter_robot.yaml:114`); выбор по serial; ≥ 20 к/с за 60 с (`telemetry_snapshot`) | #18–#22, #23; рецепт — #21 (R4) |
| β2 | Рецепт β на роботе v2 | `robot_main` с `protocol: delta_v2` (сейчас `delta_universal3`, `hikvision_letter_robot.yaml:58`); `state_get("devices.state.robot_main.conn")["conn"] == "connected"` | #21 (R4, решение 25: после W4, до #26) |
| β3 | Прошивка v2 | отчёт T0.3 (GATE-1); T4.0 — контракт-тесты против `sim_core_v2` зелёные; T4.1–T4.4 — `build_fw --check` = 0, контрактный набор против прошивки зелёный (`plans/robot-protocol-v2/tasks-2.md:53-63`) | #24, #8, #25 (T4.1–T4.4 — одна строка #25, `plans/robot-protocol-v2/plan.md:287`) |
| β4 | Ось доворота | `pt_set` пишет четыре оси с `"RZ"` (`plans/robot-protocol-v2/tasks-2.md:59-60`); задание с `place_rz` −130,0° даёт поворот диска на 30° ± 3° (метка на диске) | #25, #11 |
| β5 | Лента | T5.4: известный ход → `P_BELT_FACTOR` с ошибкой < 0,5 %, `PARAM_APPLY` ок | #13 |
| β6 | Калибровка камера ↔ робот | визард F7 пишет файл с `camera_id` = `cam0` рецепта (`Plugins/calibration/camera_robot/registers.py:20-22`; `hikvision_letter_robot.yaml:240`); рецепт β — `use_linear: false`, гомография F7 (решение владельца 2026-10-25; сейчас `true` — файл не читается, `pixel_to_robot/plugin.py:89-96`); 5 из 5 пробных дисков взяты | #26; `use_linear` — #21 |
| β7 | Сеть на реальных кадрах | letters-retrain 0.4 на наборе дня №1: top-1 и ошибка угла не хуже порогов владельца в 0.4 | #27, #23; провал → #40 |
| β8 | Ввод и смена слова оператором | поле «Слово» пульта пишет `word_layout.target_word` (readback `introspect_registers("layout")`); смена слова на ходу без перезапуска даёт журнал §2.5 | #15–#17 |
| β9 | Сценарий | слово «ПЕРЕМИРИЕ», на столе 2–3 копии каждой буквы; диски по §2.4 плюс повторы подряд по §2.6: 9 дисков в ячейках 0…8, буквы прямо ± 10°; лишние копии уехали, по каждой — запись пропуска с причиной (в том числе «слово готово» для копий после девятой ячейки); ячейки — в досягаемости робота (геометрия #10; боевой рецепт `hikvision_letter_robot.yaml:290` держит `first_y: -200.0` — ячейки 7, 8 вне 600 мм, β9 на нём красный до правки рецепта, #21) | #26, #10, C-32 |
| β10 | Стоп, крестик, «домой» | «Стоп» и крестик: робот дома, процессов не осталось, без зависания | #7, #14, #1, #5, #6 |

## 4. Зависимости: строка → что даёт → какую строку приёмки держит

| Строка ORDER / задача | Даёт | Держит |
|---|---|---|
| #1 1.9b, #5 1.10, #6 1.11 | стоп PM не глохнет; `outcome`; окно стопа | S9, β10 |
| #2 T5.3 (C-29, SPI хаба) | исполнитель команд хаба | только через #7 |
| #3 (полоса Д): C-21(б), C-30, R1 | чистое дерево после прогона; диски по списку `{буква, угол}`; ассеты — весь алфавит | S0, S5–S7, §2.1 |
| #7 T5.3e | «домой» | S8, β10 |
| #9 T5.5 | приёмка «задание от линии → DONE» (кодовый путь есть с T3.7, `jobs.py:139-165`) | DONE сима §2.4–§2.6 |
| #10, #11 P3 ×2 + C-32 | геометрия 9 ячеек; журнал каждого диска (R2); смена слова на ходу; второй одинаковый диск подряд; связка съём + укладка + доворот (поля идут: `word_layout/plugin.py:224-253` → `Plugins/io/robot_io/plugin.py:182` → `jobs.py:146-149`) | `ARGS[6..9]`, §2.3–§2.6, β4, β9 |
| #12 word-layout P4 | скрипт α по этой спеке | весь §2 |
| #13 T5.4 | `P_BELT_FACTOR` | β5, β9 |
| #15–#17 пульт | поле «Слово», смена на ходу | β8 |
| #18–#23 камеры; #21 R4 | MVS на ядре, реальные кадры; рецепт β на `delta_v2` + `camera_device` | β1, β2, β7 |
| #24, #8, #25 | прошивка v2 с `RZ` | β3, β4 |
| #26 F7 | калибровка | β6, β9 |
| #27 letters-retrain 0.4 | точность сети | допуск угла §2.3, β7 |
| #14 gui-graceful-close | закрытие по крестику | β10 |
