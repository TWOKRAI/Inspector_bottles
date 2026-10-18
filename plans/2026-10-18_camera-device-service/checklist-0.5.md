# Task 0.5 — чек-лист стенда MVS, 2026-10-19 (первый день с камерой)

## Решения до начала (лид / владелец)
- **Где запускать.** Зонд — из любого дерева с правками W1a (`<MAIN>/.venv` + `PYTHONPATH=<дерево>`). Стенд (`frontend/run.py`) ищет `.venv` в корне дерева, поэтому стенд — только из основной копии `<MAIN>` после слияния `feat/camera-device-service` в `main` (слово владельца; до слияния в `main` нет правок 0.2).
- **Запись дерева узлов.** `Services/camera_device/` ещё нет (ядро — часть B). Решение: положить только JSON по пути из FILES 0.5, без кода; коммит — лид.
- `<session>` — имя сессии полосы К на 2026-10-19.

Обозначения (подставить один раз):
- `G` = `bash "$(git rev-parse --path-format=absolute --git-common-dir)/../scripts/machine_gate.sh" heavy <session>` — каждая команда ниже идёт после `G`.
- `P` = `PYTHONUTF8=1 PYTHONPATH=<КОРЕНЬ_ДЕРЕВА> <MAIN>/.venv/Scripts/python.exe -m Services.hikvision_camera.tools.mvs_probe`
  (`<MAIN>` = `D:/PROJECT_INNOTECH/Inspector_vision/Inspector_bottles`; `<КОРЕНЬ_ДЕРЕВА>` = дерево, где лежит зонд; cwd = то же дерево).
- Все файлы результатов — в одну папку `logs_live/mvs_0.5/` (создать; `logs_live/*` в `.gitignore`). `<SN>` — серийный номер из шага 1.

## 0. Перед началом
1. Закрыть IDMVS / MVS Client, подождать ~10 с (камера отпускается после закрытия клиента).
2. VPN выключен. Сетевая карта ПК: 192.168.1.100/24.
3. Попросить у координатора (inspector-bottles-a9) окно `heavy`. Без окна gate вернёт код 75 — это «пропущено», не ошибка; не повторять в цикле.

## 1. Перечисление (без аргументов)
`G P --dump --out logs_live/mvs_0.5/x.json` -> выход 1 (отказ — так задумано). Записать: `devices=<n>`, `serial=`, `ip=`, `model=`.
Если `devices=0` — стоп: кабель/питание/IP, повторить один раз, иначе ESCALATION (п. 8).

## 2. Снимок ДО (только чтение)
`G P --dump --serial <SN> --out logs_live/mvs_0.5/dump_before.json`
Записать: число узлов в `nodes` (ACCEPTANCE: >= 15, у каждого есть `type`), `states` (`["idle","grabbing"]` или только `["idle"]` — тогда StartGrabbing не прошёл, записать), `device.model`.

## 3. Опыты H1 / H2 / H5 (каждый с `--write --orig`)
```
G P --serial <SN> --experiment h1 --write --orig logs_live/mvs_0.5/o_h1.json  --delay 0
G P --serial <SN> --experiment h1 --write --orig logs_live/mvs_0.5/o_h1b.json --delay 1.0
G P --serial <SN> --experiment h2 --mode same  --write --orig logs_live/mvs_0.5/o_h2s.json --delay 0
G P --serial <SN> --experiment h2 --mode split --write --orig logs_live/mvs_0.5/o_h2p.json --delay 0
G P --serial <SN> --experiment h5 --write --orig logs_live/mvs_0.5/o_h5.json
```
Ожидание H5: `rc=0x80000106` на записи `Width`, затем `restore ... read=<как в --orig>`, код выхода 0.
Split-опыт не прерывать Ctrl+C (гонка потоков) — дать дойти до конца.
Таблица (одна строка на запуск, из строк `node= rc= read= ms= thread=` и `restore node= rc= read= thread=`):

| опыт | rc | read | ms | thread | строка restore (rc / read / thread) | код выхода |
|---|---|---|---|---|---|---|
| h1 delay 0 | | | | | | |
| h1 delay 1.0 | | | | | | |
| h2 same | | | | | | |
| h2 split | | | | | | |
| h5 | | | | | | |

## 4. Снимок ПОСЛЕ и сравнение
`G P --dump --serial <SN> --out logs_live/mvs_0.5/dump_after.json`
Сравнение (одна строка, venv-python, `-I`):
`<MAIN>/.venv/Scripts/python.exe -I -c "import json,sys;a,b=[json.load(open(p,encoding='utf-8'))['nodes'] for p in sys.argv[1:3]];d=[(k,a[k]['idle']['value'],b[k]['idle']['value']) for k in a if k in b and a[k]['idle']['value']!=b[k]['idle']['value']];print(len(a),len(b),'diff=',len(d));print(*d,sep='\n')" logs_live/mvs_0.5/dump_before.json logs_live/mvs_0.5/dump_after.json`
Ожидание: `diff= 0`. Ненулевой diff: записать узлы поимённо. Узлы-счётчики/температура/время могут меняться сами — это не провал, но записать и показать лидеру. (Либо сравнение отдать junior-агенту.)

## 5. Стенд (когда зонд закончил, камера свободна ~10 с)
Запуск (один раз, боевой вход, не harness; `<дата>` = 2026-10-19):
`BACKEND_CTL=1 INSPECTOR_GUI_UNATTENDED=1 INSPECTOR_LOG_DIR=logs_live/mvs_<дата> .venv/Scripts/python.exe multiprocess_prototype/frontend/run.py hikvision_inspect`
(рецепт `hikvision_inspect`; ключ частоты в нём `fps: 25` у плагина `camera_0.hikvision`.) Записать PID процесса.
Проверки через `backend_ctl` (не psutil, не qt-mcp):
1. `capabilities` — найти процесс камеры (`camera_0`) и ответ команды `get_parameters`.
2. `send_command` `get_parameters` в `camera_0` -> записать `param_errors`: пусто, либо список «узел -> код». Записать `frame_rate` в ответе (ждём ~25, рецепт `fps`).
3. `state_get` счётчика кадров камеры: чтение 1 = ___ , подождать 10 с, чтение 2 = ___ , секунд между чтениями = ___. Счётчик растёт? (имя ключа записать как есть.)
4. `log_tail` процесса камеры: ERROR есть / нет (если есть — вставить строки).
5. Кадр цветной и доходит до дисплея «main» (подтверждает человек у экрана или `state_get`; записать как проверено).
Не сошлось — один перезапуск; не сошлось второй раз -> п. 8.

## 6. Остановка
Остановить стенд по PID (`TaskStop` / `taskkill /PID <pid>`), НИКОГДА глобальный `taskkill /IM`. Подождать ~10 с — камера отпускается. Закрыть окно координатора (`close`).

## 7. Куда класть результат
- JSON дерева `dump_before.json` -> `Services/camera_device/testing/recordings/mvs_<модель>.json` (FILES 0.5; только JSON, без кода — решение выше; коммит — лид).
- Таблица шага 3, числа шагов 1, 2, 4, 5 -> `plans/2026-10-18_camera-device-service/tasks/0.5.result.md` («Факты MVS»).

## 8. Правила остановки
- Стенд не сошёлся 2 раза -> `ESCALATION -> teamlead` (investigator по живому дефекту), блок из project-rules §7.
- `RESTORE MISMATCH` (код 2) -> СТОП, остальные опыты не гонять; вернуть `P --serial <SN> --restore logs_live/mvs_0.5/<файл --orig этого опыта> --write` (без `--write` зонд откажет, код 1); записать строки restore; затем `--dump` и diff как в п. 4.
- Зонд оборвался посреди опыта -> то же `--restore … --write`; повтор опыта с тем же `--orig` зонд не пустит (код 1), пока файл не удалён после возврата (значения также напечатаны строкой `orig saved; вручную (IDMVS): ...`). `UserSetSave` зонд не вызывает.

## 9. Что отправить координатору в конце
- окно: когда начали / закончили; камера освобождена (да/нет);
- `devices=`, `serial`, `ip`, `model`; число узлов; diff до/после (число);
- по каждому из 5 опытов: rc и код выхода; `RESTORE MISMATCH` был / не был;
- стенд: `param_errors` (пусто / коды), счётчик кадров (два числа + секунды), ERROR в логе (да/нет);
- пути: `logs_live/mvs_0.5/`, `logs_live/mvs_<дата>`, `0.5.result.md`.
