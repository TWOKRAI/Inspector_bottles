# День №1: камера — чек-лист (MVS, запись набора кадров дисков)

> Составлен 2026-11-15, ветка `feat/camera-device-w2-core` (от `main` 506eea281). Камера вернётся ≈ 2026-11-22 (слово владельца в брифе).
> Правило документа: шаг без источника в коде/плане помечен «ИСТОЧНИКА НЕТ → вопрос»; числа-предложения помечены **[НА УТВЕРЖДЕНИЕ ЛИДА]**; прогнозов «успеем» нет.
> Обозначения как в `plans/2026-10-18_camera-device-service/checklist-0.5.md`: `G` = `bash "$(git rev-parse --path-format=absolute --git-common-dir)/../scripts/machine_gate.sh" heavy <session>` (стенд — окно `stand`/`heavy`; `<session>` — имя полосы, спросить лида), `<MAIN>` = `D:/PROJECT_INNOTECH/Inspector_vision/Inspector_bottles` (путь из checklist-0.5).

## 1. Что уже сделано (по git) и что осталось от 0.5

Верим коммитам, не шапкам: `15e3687a6` (дерево узлов + факты MVS), `c115a2d97` (ссылка на C-67), `d0a990f6f` (итог стенда: цвет подтверждён, набор кадров дисков перенесён) — все тремя в истории ветки; источник чисел — `plans/2026-10-18_camera-device-service/tasks/0.5.result.md`.

| Пункт ACCEPTANCE 0.5 | Статус | Источник |
|---|---|---|
| JSON дерева узлов, ≥15 узлов, у каждого `type` | СДЕЛАНО: 15 узлов, состояния idle и grabbing | `Services/camera_device/testing/recordings/mvs_MV-CS020-10GC.json`, `15e3687a6` |
| Таблица H1/H2/H5 (`rc`, `read`, `ms`) | СДЕЛАНО: H1 rc 0x0 (5,62 / 5,70 мс), H2 rc 0x0 (2,18 / 1,82 мс), H5 `0x80000106` на Width в grabbing | `0.5.result.md`, `15e3687a6` |
| Стенд: кадр цветной камеры доходит до дисплея, счётчик кадров растёт, `param_errors` пуст | СДЕЛАНО с оговорками: `get_parameters` -> `param_errors {}`; `camera_0` циклы 2551 -> 2718 за 6,72 с (24,8 Гц), `color_convert` 25,1 Гц, ERROR нет; до дисплея дошло «глазами владельца», не `state_get` | `0.5.result.md` |
| Значения камеры после опытов = `--orig` (дамп до/после, diff пуст) | СДЕЛАНО для опытов H1/H2/H5 (`before.json`/`after.json`, `diff` пуст). Файлы в `data/` (gitignored) — из git не воспроизводятся. ПОСЛЕ стенда значения другие (см. разд. 5) | `0.5.result.md` |
| Цвет (порядок каналов) | СДЕЛАНО: белая стена светло-серая, лампа тёплая, подсветка синяя, принтер чёрный; красного предмета не показывали | `d0a990f6f`, `0.5.result.md` |
| **Набор реальных кадров дисков с буквами** (строка 27 очереди, letters-retrain 0.4, веха β7) | **НЕ СДЕЛАНО** — владелец держал камеру в руках, кадры комнаты, резкость по Лапласу 2,1–2,8 | `0.5.result.md` «Осталось» |

Рабочая заготовка из 0.5 — `data/mvs_stand/hikvision_capture.yaml` (не в git, на машине стенда). Пробные каталоги `data/mvs_stand/frames/_look`, `_look2`, `_start`, `_test` (~2,5 тыс. PNG комнаты) — не набор дисков, не удалены.

## 2. Что должно лежать на машине с MVS (Windows-стенд)

| Пункт | Требование | Источник |
|---|---|---|
| MVS SDK / драйвер | `MvCameraControl.dll` загружается обёрткой (`SDK_AVAILABLE`); версия и путь установки — ИСТОЧНИКА НЕТ → вопрос владельцу | `Services/hikvision_camera/sdk/bindings.py:2`, `:66` |
| IP / подсеть | камера в link-local `169.254.49.1`, DHCP нет; карта «Ethernet» (Killer E2600) `169.254.49.100/255.255.0.0`; пинг 1–2 мс. В checklist-0.5 §0 ещё `192.168.1.100/24` — устарело | `0.5.result.md` «Сделано» |
| Файрвол | выключен (на прошлом стенде) | `0.5.result.md` |
| Права | ИСТОЧНИКА НЕТ → вопрос (нужны ли права администратора для SDK/сетевого сокета) | — |
| IDMVS / MVS Client | закрыт, подождать ~10 с (камера отпускается после закрытия клиента) | `checklist-0.5.md` §0 п.1 |
| VPN | выключен | `checklist-0.5.md` §0 п.2 |
| `.venv` | `<MAIN>/.venv/Scripts/python.exe`; из связанного worktree `run.py` берёт `.venv` основной копии через `git rev-parse --git-common-dir` | `multiprocess_prototype/run.py:5-9` (докстринг), `checklist-0.5.md` |
| Путь плагина камеры | `Services/hikvision_camera/` (плагин `Services.hikvision_camera.plugin.plugin.HikvisionCameraPlugin`, зонд `Services/hikvision_camera/tools/mvs_probe.py`) — старый путь, не `camera_device` | `hikvision_inspect.yaml:61`, `mvs_probe.py` |
| Данные | `data/mvs_stand/` (gitignored: `.gitignore:135` `data/`); логи `logs_live/<дата>` (gitignored, `.gitignore:64`) | `.gitignore` |
| Камера | серийник на прошлом стенде `DA1689923`; MV-CS020-10GC, цветная; в камере после стенда остались 25 fps, `AcquisitionFrameRateEnable=True`, `GevSCPSPacketSize=1500` | `0.5.result.md` |

Робот Modbus `192.168.1.7:502` из подсети `169.254.49.100/16` недоступен (`0.5.result.md`) — для записи кадров не нужен.

## 3. Запуск стенда на старом пути

Рецепты: `multiprocess_prototype/recipes/hikvision_inspect.yaml` (камера -> `color_convert` bgr2rgb -> дисплей `main`; `camera_0` `fps: 25`, `resolution_width/height: 1440/1080`, `auto_start: true`; `gui` — `HeadlessGuiProcess`) и `hikvision_letter_robot.yaml` (боевой тракт робота; `camera_0` с `restart_policy`, :131; для записи кадров не нужен).

Запуск (аргумент — имя рецепта: `multiprocess_prototype/main.py:176-180`, `frontend/run.py:81-86`):
```
G env BACKEND_CTL=1 INSPECTOR_GUI_UNATTENDED=1 INSPECTOR_LOG_DIR=logs_live/mvs_<дата> \
   .venv/Scripts/python.exe multiprocess_prototype/run.py hikvision_inspect
```
`frontend/run.py hikvision_inspect` — то же с окном GUI (так запускал владелец в 0.5; на подъёме GUI была `Full()` — C-67, см. разд. 7). Остановка — `TaskStop` или `taskkill /PID <pid>`, НИКОГДА `/IM`; подождать ~10 с.

Проверки через `backend_ctl` (MCP-инструменты `backend-ctl`, существование проверено `git grep` в `backend_ctl/mcp_tools.py`: `send_command` :792, `state_get` :994, `log_tail` :1100, `set_register_verified` :334):
1. `capabilities` — процессы, команды, регистры (начинать с него, `backend_ctl/AGENTS.md`).
2. `send_command(target="camera_0", command="get_parameters")` -> `param_errors` пуст, `frame_rate` ~25 (команда `get_parameters`: `Services/hikvision_camera/plugin/plugin.py:89`).
3. Счётчик кадров: `state_get(path=...)` дважды с паузой ≥10 с. Путь ключа счётчика циклов `camera_0` — ИСТОЧНИКА НЕТ в плане (в 0.5.result.md «циклы 2551 -> 2718», путь не записан) → найти через `state_get_subtree(path="")` или `system_overview` и записать как есть.
4. `log_tail(process="camera_0", level="ERROR")`, читать инструментом `events` (описание `log_tail` в `mcp_tools.py:1100`: записи едут push'ем).
5. Цвет: взять в кадр красный/цветной предмет (в 0.5 красного не было).

## 4. Запись набора кадров дисков для letters-retrain 0.4

### 4.1 Что умеет `frame_saver` (по коду `Plugins/io/frame_saver/`)

- Имя файла жёстко: `<filename_prefix>_<индекс:0{index_padding}d>.<ext>` (`plugin.py:274`). Шаблона каталога/имени (`subfolder_template`) НЕТ — это Task 3.1 плана DS-1, DEFERRED (DS-В4). `save_when` — тоже DEFERRED (Task 2.2).
- Каталог: `output_dir` [+ `<YYYY-MM-DD>` при `subfolder_by_date=true`]. Формат `png|jpeg|bmp|tiff|webp`. Запись атомарная (`*.tmp` + rename). `output_dir`, `filename_prefix` читаются из регистра на каждом кадре — меняются на ходу (`plugin.py:274`, `_resolve_dir` :375: при новой папке индекс пересканируется по текущему префиксу).
- `.json`-sidecar (`write_sidecar`) пишется ТОЛЬКО если во входном item есть dict `item["sidecar"]` (`_write_sidecar`: «payload не dict -> return»). Кадр камеры его не несёт (его делает `center_crop`: `Plugins/processing/center_crop/plugin.py:196`). Вывод: **для кадров камеры без crop sidecar не появится**; буква и угол живут только в пути и имени.
- Режимы: `stream` (каждый N-й кадр) и `trigger` (буфер `last`/`accumulate` до команды `save_now`; `buffer_size` читается в `configure()` — менять только в рецепте, не на ходу, `plugin.py:151`).
- Команды: `save_now`, `get_stats` (`saved_count`, `output_dir`, `last_saved`); имя команды у процесса `saver` сверить `introspect_handlers("saver")` — НЕ проверено на живом.

### 4.2 Схема имён (минимальный вариант)

```
data/mvs_stand/day1/<БУКВА>/a<УГОЛ:03d>_<индекс:06d>.png
пример: data/mvs_stand/day1/П/a045_000003.png
```
Буква — подкаталог (одна заглавная кириллическая буква; так же читает `ml_train` источник `folder`: класс = имя подкаталога, `Services/ml_train/data.py:97-112`), угол в градусах — в префиксе. Реализация: рецепт `subfolder_by_date: false`; оператор на ходу меняет два регистра — `output_dir` (`.../day1/<БУКВА>`) и `filename_prefix` (`a<УГОЛ>`). Индекс сквозной внутри префикса (resume с диска), повторная съёмка ячейки не затирает старое. Таблица-журнал не нужна, пока оператор следует схеме; скрипт-проверка (4.6) ловит неверные имена.

Не совпадает с DS-1: там `.json` несёт `truth` (буква, угол сима) и `pred`, метка обучения только через `training_label()` из `Services/line_sim/tools/join_frame_truth.py` — файла в `main` и в этой ветке НЕТ (DS-1 1.1a/1.1b не влиты, `docs/reports/2026-11-12_release-1.0_alpha-rerun.md:76`). Ручная метка реальных кадров — DS-В4, DEFERRED: схему метки не придумываю.

### 4.3 Рецепт записи

Временный `hikvision_capture.yaml` не в git. **Решение лиду:** положить рецепт capture в git (где — решение лида; в `multiprocess_prototype/recipes/` я его не создавал) ИЛИ собирать из `hikvision_inspect.yaml` по блокам ниже. Блоки по образцу `color_inspect.yaml:113-137` (плоские ключи) — загрузчиком и на железе НЕ прогонялись:

```yaml
# 1) в процессе color_convert:  chain_targets: [gui, saver]      # было [gui]
# 2) новый процесс (после color_convert):
    - process_name: saver
      process_class: multiprocess_prototype.generic_process_app.GenericProcessApp
      priority: low
      chain_targets: []
      plugins:
        - plugin_class: Plugins.io.frame_saver.plugin.FrameSaverPlugin
          plugin_name: frame_saver
          category: output
          output_dir: data/mvs_stand/day1/_start
          filename_prefix: a000
          subfolder_by_date: false
          image_format: png
          save_mode: trigger
          buffer_mode: accumulate
          buffer_size: 3          # [НА УТВЕРЖДЕНИЕ ЛИДА] кадров за один save_now
# 3) wires:
    - source: color_convert.color_convert.frame
      target: saver.frame_saver.frame
# 4) разрешение камеры: resolution_width: 1624, resolution_height: 1240   # [ВОПРОС ЛИДУ], см. 4.5
```
Сохранять после `color_convert` (BGR): камера отдаёт RGB, `cv2.imencode` в `frame_saver` ждёт BGR (`hikvision_inspect.yaml:4-7`, `hikvision_letter_robot.yaml:25`). Из какой точки писал временный рецепт 0.5 — не записано; цвет 0.5 подтверждён «как BGR» (`0.5.result.md`).

`trigger`+`accumulate` выбран, чтобы смена каталога/префикса не «протекала» кадрами: в `stream` между двумя `set_register` кадры уйдут не туда.

### 4.4 Процедура на ячейку (буква, угол)

1. Положить диск буквой под заданный угол (способ задания угла — вопрос 4 в разд. 9), подождать ~1 с.
2. `set_register_verified("saver", "frame_saver", "output_dir", "data/mvs_stand/day1/<БУКВА>")` и то же для `filename_prefix` = `a<УГОЛ:03d>` (имя регистра `frame_saver` взято из `0.5.result.md` «set_register saver frame_saver output_dir»; сверить `introspect_registers("saver")`). `set_register_verified` возвращает `verified/expected/actual` (`backend_ctl/AGENTS.md:116`).
3. `send_command("saver", "save_now")` — сбросит последние 3 кадра буфера. Повторить с перекладкой диска (пример: 2 раза = 6 кадров на ячейку). Кадры подряд при 25 Гц почти одинаковы, различие даёт только перекладка.
4. `send_command("saver", "get_stats")` — `saved_count` растёт на 3 за вызов.

### 4.5 Постановка (камера, свет, фокус, геометрия)

- Камера жёстко закреплена; свет — равномерный; фокус — по резкости кадра (диск с буквой в кадре, не комната).
- Порог резкости по Лапласу в репозитории: ИСТОЧНИКА НЕТ (`git grep` по `laplac` в `*.py/*.md/*.yaml` — 0 хитов). Метод замера 0.5 (2,1–2,8) не записан; скрипт 4.6 считает дисперсию Лапласа серого кадра, порог 100 — **[НА УТВЕРЖДЕНИЕ ЛИДА]**, не из репо; откалибровать на первом кадре «в фокусе» (диск виден чётко) и записать.
- Яркость: сцена 0.5 ≈ 28/255 — тёмная. `ExposureTime=40000` мкс при 25 fps (период 40 мс) уже на пределе периода кадра (вывод из `0.5.result.md`, не проверен): темноту лечить светом/усилением (`Gain` был 0; `set_parameters` камеры — `plugin.py:62`, аргументы не сверял).
- Размеры (цифры из плана `plans/letters-retrain/plan.md`): высота буквы / D = 0.486 (штрих/D 0.075–0.088); видимый диск сима 294 px. **Мой расчёт, не из плана:** буква ≈ 0.486·294 ≈ 143 px, штрих ≈ 24 px. Рецепт `letter_robot_sim.yaml:134-141` принимает кадр сима как 1440×1080. Сенсорный кадр 1624×1240 (`0.5.result.md`, аспект 1.31, не 4:3); при `resize_mode: letterbox` (умолчание, `plugin.py:120`) в 1440×1080 масштаб ≈ 0.871 (min(1440/1624; 1080/1240)), значит диск 294 px в кадре 1440×1080 = ≈ 337 px в нативном 1624×1240, буква ≈ 164 px. Физический диаметр диска (мм), высота камеры, объектив: ИСТОЧНИКА НЕТ → вопрос.
- Ярлык: скрипт проверки размер диска НЕ измеряет (только единый размер кадра).

### 4.6 Минимум букв и число кадров

Слово «ПЕРЕМИРИЕ» (`plans/queue/decisions.md:36`, запись 25): различных букв 5 — **П, Е, Р, М, И** (повторы Е×3, Р×2, И×2).
В плане числа углов/кадров на ячейку НЕТ (`git grep` по плану и `release-1.0` — 0 хитов). Предложение **[НА УТВЕРЖДЕНИЕ ЛИДА]**: 8 углов (0, 45, …, 315°) × 5 букв × 6 кадров = 240 кадров; весь алфавит (33 буквы) — «если успеем», без числа.
Допуски угла в спеке: ±5° (`release-1.0/amendments.md:64`), окно α ±15°, β9 «буквы прямо ± 10°» (`design.md` β9) — число для 0.4 на реальных кадрах: ИСТОЧНИКА НЕТ → вопрос.

Скрипт проверки набора: `scripts/day1_capture_check.py` (stdlib + opencv/numpy, слои не нарушает, не импортирует `multiprocess_prototype`), тест `scripts/tests/test_day1_capture_check.py` (каталог `scripts/tests` есть в списке тестов `pyproject.toml:209`). Запуск:
```
.venv/bin/python -I scripts/day1_capture_check.py data/mvs_stand/day1            # Windows: .venv/Scripts/python.exe
  [--letters ПЕРМИ] [--angles 0,45,...,315] [--min-per-cell 6] [--min-sharpness 100]
  [--min-bright 60] [--max-bright 230] [--max-bad-frac 0.10]
```
Выход: таблица «годных/всего» по (буква, угол), резкость/яркость min и медиана, строки PASS/FAIL, `ИТОГ`, код 0/1 (2 — ошибка вызова). Чтение через `imdecode(fromfile)` — путь с кириллицей на Windows.

## 5. Критерий PASS (числами)

| # | Критерий | Порог | Как мерить |
|---|---|---|---|
| 1 | Частота кадров `camera_0` на рецепте `fps 25` | ≥ 24,0 Гц на окне ≥ 10 с [НА УТВЕРЖДЕНИЕ ЛИДА]; в 0.5 было 24,8–25,1 | `state_get` дважды, разница / секунды |
| 2 | ERROR в логе камеры/`saver`/`color_convert` | 0 | `log_tail level=ERROR` + `events` |
| 3 | `param_errors` | `{}` | `get_parameters` |
| 4 | Кадров по ячейкам (буква × угол) | ≥ 6 годных [НА УТВЕРЖДЕНИЕ ЛИДА], 5 букв × 8 углов | `day1_capture_check.py` |
| 5 | Резкость (дисперсия Лапласа) | ≥ 100 [НА УТВЕРЖДЕНИЕ ЛИДА; в 0.5 комната 2,1–2,8 = негодная] | скрипт |
| 6 | Яркость (среднее по каналам) | 60…230 из 255 [НА УТВЕРЖДЕНИЕ ЛИДА; 0.5 ≈ 28 = тёмная] | скрипт |
| 7 | Доля плохих/нечитаемых кадров | ≤ 0,10 [НА УТВЕРЖДЕНИЕ ЛИДА] | скрипт |
| 8 | Единый размер кадра, имена по схеме | 1 размер, 0 BAD_NAME | скрипт |
| 9 | Дамп `--dump` до/после стенда | `diff` пуст по всем узлам, кроме трёх, которые плагин пишет по рецепту: `AcquisitionFrameRate` (20->25), `AcquisitionFrameRateEnable` (False->True), `GevSCPSPacketSize` (8164->1500), и узлов, которые оператор менял осознанно (экспозиция/усиление — записать). Счётчики/температура/время могут плыть (`checklist-0.5.md` §4) | зонд `P --dump --serial <SN> --out ...`; сравнение — однострочник из `checklist-0.5.md` §4 |

`P` = `PYTHONUTF8=1 PYTHONPATH=<КОРЕНЬ_ДЕРЕВА> <MAIN>/.venv/Scripts/python.exe -m Services.hikvision_camera.tools.mvs_probe` (`mvs_probe.py:861-872`: `--dump`, `--serial`, `--out`). Если дамп «до» сегодняшнего дня уже показывает 25/True/1500 — это остаток 0.5, не регрессия.

## 6. Проверка без железа (до дня)

- `frame_saver`: `G`-класс light: `bash ".../machine_gate.sh" light <session> env PYTHONPATH=$PWD .../.venv/bin/python -m pytest Plugins/io/frame_saver/tests -q --tb=short` -> **53 passed** (2026-11-15, Mac, эта ветка; в этой выборке живая смена `output_dir`/`filename_prefix` через `set_register` на процессе не проверена — это мой пробел).
- Скрипт набора: `.../python -m pytest scripts/tests/test_day1_capture_check.py -q --tb=short` -> **7 passed**; инъекция (знак сравнения резкости перевернут) -> 3 failed; на синтетическом наборе 5×8×6 = 240 кадров `-I` прогон -> `ИТОГ: PASS`.
- Зонд: `mvs_probe.py --fake` (FakeMvCamera, `:872`) — без железа; прогон не делал.
- Источники для репетиции на Mac: `bridge_synth.yaml` / `dualcam_synth.yaml` (`SyntheticFrameSourcePlugin`), либо `letter_robot_sim.yaml` (кадр от `apps/line_sim` по MJPEG `127.0.0.1:8091`). Репетиция «блок `saver` из 4.3 + `set_register` + `save_now` на синтетике» **не выполнена** — предлагаю сделать до дня (процесс: `saver`, команда `save_now`, регистр `frame_saver` проверить `introspect_*`).

## 7. Если провал

- `devices=0` / камеры не видно: кабель, питание, IP/подсеть карты (разд. 2), IDMVS закрыт и ~10 с; повторить один раз, иначе `ESCALATION -> teamlead` (`checklist-0.5.md` §1, §8).
- Стенд не сошёлся дважды -> `ESCALATION -> teamlead` (investigator по живому дефекту), блок из `project-rules` §7.
- `RESTORE MISMATCH` (код 2) -> СТОП, вернуть `P --serial <SN> --restore <файл --orig> --write`, затем `--dump` и diff (`checklist-0.5.md` §8).
- Кадры тёмные (яркость < 60): свет / усиление; не снижать fps ради экспозиции без записи значения; записать значения узлов до/после.
- Резкость ниже порога: фокус, расстояние, перезапись набора; кадры комнаты в набор не класть.
- `send_to_queue('gui','data') Full()` при подъёме GUI (~13 с) — C-67 (`0.5.result.md`, `multiprocess_framework/.../queues/core/manager.py:365`): **не чинить**, записать время и счётчики (`delivery_failed`, `middleware_dropped`); для записи кадров стенд поднимается headless (`run.py`, без окна).
- Записанные кадры не затирать и не удалять без слова лида; набор — только в `data/mvs_stand/day1/`.

## 8. Что разблокирует

- letters-retrain Task 0.4 (`plans/letters-retrain/plan.md`; строка 27 `ORDER.md` расширяет его до «на симе и на реальных кадрах дня №1»);
- веха β7 «Сеть на реальных кадрах» (`plans/release-1.0/design.md` §3: letters-retrain 0.4 на наборе дня №1; провал -> строка 40 layer-render Task 3.1 «поднять в 1.0»);
- вход в решение DS-В4 (разморозка записи реальных кадров, `plans/2026-11-11_dataset-sidecar-truth/plan.md:18`, `decisions.md:38` запись 27) — набор даёт материал, но метку реальных кадров не решает;
- Task 6.3 (М2, `camera-device-service/plan.md:109`): 0.5 — одна из зависимостей (4.2a, 4.2b, 4.3, 4.4, 6.1, 0.5); стендовая часть 0.5 по git уже выполнена, набор кадров 6.3 не нужен. Сам по себе набор 6.3 не открывает.

## 9. Расхождения, открытое, вопросы

### Расхождения между шапками / ORDER / git

1. `plan.md:108` Task 0.5 `[PENDING]`, `plan.md:5` «следующая — W2», `ORDER.md` строка 23 — «поставить как можно раньше»; по коммитам `15e3687a6`, `c115a2d97`, `d0a990f6f` стенд, дерево узлов и цвет выполнены 2026-10-27.
2. `0.5.result.md` «SHA: нет коммита» — коммиты есть (`15e3687a6` и др.).
3. `checklist-0.5.md` §0: карта `192.168.1.100/24`; `0.5.result.md`: `169.254.49.100/16`. Также checklist: стенд только из `<MAIN>` после слияния; `run.py` теперь берёт `.venv` основной копии из worktree (C-55a) — ограничение checklist, возможно, устарело.
4. `plans/letters-retrain/plan.md` Task 0.4 — «базовая линия на исправленном симе», сим; `ORDER.md` строка 27 расширяет до реальных кадров; в плане letters-retrain реальных кадров в 0.4 нет.
5. Рецепт `hikvision_inspect.yaml` — `resolution 1440×1080`, а PNG 0.5 — 1624×1240 (временный рецепт, не в git).
6. `join_frame_truth.py` (брифом назван как источник схемы sidecar) в `main` и ветке отсутствует; DS-1 1.1a/1.1b не влиты.

### Что осталось открытым / ненадёжно

- Весь рецепт 4.3 не загружался и не гонялся (ни Mac, ни железо); имя команды `save_now` у процесса `saver`, регистра `frame_saver`, путь счётчика кадров — не проверены на живом.
- Схема имён `a<УГОЛ>` + подкаталог буквы — моё предложение (минимум по возможностям `frame_saver`); `.json`-sidecar для кадров камеры без `center_crop` не появится.
- Резкость: метод 0.5 неизвестен, порог 100 из воздуха (честно: взят как стартовая точка). Размер диска в пикселях скриптом не проверяется; расчёт 337 px / 164 px — арифметика по плановым числам при допущении, что кадр сима 1440×1080.
- Угол «истинный» при ручной укладке на реальном диске: способ задания и его точность не определены; без этого проверка ошибки угла в 0.4 нечестная.
- Скрипт-тест: 7 passed, инъекция 3 failed — это синтетика, не реальные кадры камеры; на PNG с железа не гонялся.
- Права/версия MVS SDK/объектив/диаметр диска — ИСТОЧНИКА НЕТ. Модель `mobilenet_v3` ожидает кропы дисков, набор — полные кадры; нарезка — отдельный шаг, не описан.

### Вопросы лиду / владельцу

1. Рецепт capture — положить в git (где) или собирать блоками 4.3? Как запускать рецепт из `data/mvs_stand/` (как запускали временный в 0.5 — не записано)?
2. Утвердить числа: 5 букв (П, Е, Р, М, И) × 8 углов (шаг 45°) × 6 кадров; пороги резкости 100, яркости 60…230, доля плохих ≤ 0,10, частота ≥ 24,0 Гц.
3. Угол на реальном диске: чем задаём (транспортир-шаблон под диском?) и допуск в 0.4 (±5° спека, ±10/15° в других местах)? Какие «пороги владельца» для top-1 и угла в β7?
4. Диск неподвижен под камерой или на движущейся ленте? Полные кадры или кропы (нужен ли `center_crop`/`dataset_circle_capture`-цепочка)?
5. Разрешение записи: нативное 1624×1240 или 1440×1080 letterbox (как в рецепте)?
6. Кириллица в именах каталогов (`П`, `Е`…) приемлема или переходим на латинские коды классов?
7. DS-В4 — разморозить ли ручную метку реальных кадров (иначе набор остаётся «кадры + буква/угол в имени»)?
8. Диаметр диска (мм), высота/объектив камеры, версия MVS SDK и права на машине стенда.
9. Репетицию 4.3 на синтетике (Mac) до дня — поручить?
