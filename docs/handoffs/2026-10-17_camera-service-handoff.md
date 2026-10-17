# Передача: сервис камер и считыватели ID3013 (2026-10-17, вечер)

Автор: Opus-ревьюер `a52844da255df6423` по просьбе владельца, для продолжения в НОВОМ чате. Сессия лидера `inspector-bottles-c5`.
Ветка `feat/code-reader-gui`, HEAD `785e16075`. Не запушено, в `main` не влито. Камеры по сети не отвечают (ping 0/2).

## 0. ОБНОВЛЕНИЕ (позже, лидер сессии) — читать первым

Шаги 2, 3 и 4 раздела 1 ВЫПОЛНЕНЫ, разделы 2 и 7 ниже описывают состояние на момент написания. Актуально:
- HEAD `8807d2917`; поверх `785e16075` три коммита: `b2e1c6c5c` (правка `labels`: плохая подпись не роняет `produce()`, проверка один раз в `configure`; пределы по замеру на cv2: координаты ±2**30, `scale` до 50 — `putText` на 1000 занимает 12,6 с; ревью Sonnet два раунда APPROVED, 34 608 враждебных подписей без расхождений), `0dbe7b2e0` (SETUP, шапки dual-рецептов, этот handoff, `OPEN_QUESTIONS`, отчёт разработчика), `8807d2917` (зонды в `Services/code_reader/tools/`: `thread_split_probe.py`, `cam_cfg.py`, `cam_orig.json`).
- Тесты: `Services/code_reader/tests` + рецепты dual + снимок каталога = 637 passed, ruff чист. Красный `test_letter_robot_sim_diff` — от чужой правки `letter_robot_sim.yaml`, не от нас.
- В дереве осталось ТОЛЬКО чужое: `README.md`, `multiprocess_prototype/app.yaml`, `multiprocess_prototype/recipes/letter_robot_sim.yaml`, `docs/handoffs/2026-10-14_coordinator.md`.
- Не сделано: пункты 5-7 раздела 1 (план `plans/camera-device-service.md` после чтения проекта владельцем, опыты на камерах, разделение `phase-2.md` по `##`). Реализация сервиса камер НЕ запущена по просьбе владельца.
- Записано в `docs/claude/OPEN_QUESTIONS.md` для проекта сервиса: залипание сообщения о `labels` при правке на ходу; отказ построения overlay виден оператору только одной строкой лога (нужен сигнал в статусе).
- Зонд запускается из репозитория: `PYTHONUTF8=1 PYTHONPATH=. .venv/Scripts/python.exe Services/code_reader/tools/thread_split_probe.py --ip 192.168.1.10 --mode split --reopen-after 1,15` (IDMVS и стенд закрыть); `--fake` для проверки без камер. `cam_cfg.py` пишет в `cam_orig.json` рядом — это эталон исходных значений камер, не перезаписывать вручную.
- Недельный лимит Sonnet уже один раз прерывал ревью; сброс был 17 окт 22:00 МСК, после него агенты работали.

## 1. С чего начать (по приоритету)

1. Сверить состояние с разделом 2:
   `git -C D:/PROJECT_INNOTECH/Inspector_vision/Inspector_bottles log --oneline -6` и `git … status --short`.
2. Закрыть правку `labels`. Разработчика `a2740848ceea4ed66` дозвать через `SendMessage`, нового не запускать.
   Прогон через gate (`<сессия>` — из брифа):
   `bash "$(git rev-parse --path-format=absolute --git-common-dir)/../scripts/machine_gate.sh" light <сессия> .venv/Scripts/python.exe -m pytest Services/code_reader/tests/test_sdk_labels_robust.py Services/code_reader/tests/test_sdk_labels_check.py Services/code_reader/tests/test_sdk_trigger_hazards.py -q --tb=short -p no:cacheprovider`.
   Дальше по правилам: матрица инъекций (Haiku, прогнозы пишет лидер), ревью (Sonnet), коммит явных путей:
   `Services/code_reader/plugin/sdk_plugin.py`, оба `test_sdk_labels_*.py`, `test_sdk_trigger_hazards.py`.
3. Закоммитить документы от Haiku отдельным коммитом (явные пути): `Services/code_reader/docs/SETUP_GEV_V4.0.2.R.md`,
   `multiprocess_prototype/recipes/qr_reader_sdk_dual_demo.yaml`, `multiprocess_prototype/recipes/qr_reader_sdk_dual_selftrigger.yaml`.
   Перед коммитом — `git diff` по этим путям: в рецептах только шапка.
4. **Сохранить зонды в репозиторий.** Scratchpad нового чата будет другим. Решение: перенести
   `thread_split_probe.py` в `Services/code_reader/tools/thread_split_probe.py` (рядом с `mvcr_probe.py`) и `cam_cfg.py` +
   `cam_orig.json` в `Services/code_reader/tools/` (или `docs/`, если инструмент разовый). Источник (пока жив):
   `C:/Users/INNOTECH/AppData/Local/Temp/claude/d--PROJECT-INNOTECH-Inspector-vision-Inspector-bottles/502f726c-e456-4ffa-b1dc-c2b17eec0068/scratchpad/`.
   Коммит `chore(code-reader): …`, `Refs: plans/code-reader-gui.md`. Исходные значения камер продублированы в разделе 4.
5. Владелец читает `docs/design/camera-device-service.md`. После его «да» — `manager` пишет `plans/camera-device-service.md`
   по §6 проекта (заменяет Task 2.2b старого плана; Task 2.3 остаётся в `plans/code-reader-gui`). Затем Opus `reviewer`
   в `MODE: plan` на этот план.
6. Когда камеры вернутся — Task 1.0, опыты (раздел 4.5). Первая команда, без записи:
   `PYTHONUTF8=1 PYTHONPATH=. .venv/Scripts/python.exe Services/code_reader/tools/mvcr_probe.py --params --ip 192.168.1.10 --node TriggerMode --node TriggerSource --node TriggerSelfTriggerPeriod` (и `.11`).
7. Разделить `plans/code-reader-gui/phase-2.md` по `##`: файл больше 32 КБ, хук doc-size-guard просит разделить.

## 2. Состояние репозитория

Коммиты 2026-10-17 (поверх `0148b5ad8`):

| SHA | Что |
|---|---|
| `383242ac9` | Task 2.2a — заготовка: режим съёмки из рецепта пишется при старте, возврат при остановке. На железе не проверена |
| `d267f711b` | рецепты разведены: `qr_reader_sdk_dual_demo` режим не пишет; `qr_reader_sdk_dual_selftrigger` пишет, запуск вручную |
| `0cfa3ac4e` | документы: спека 2.2a, ревью r1, Opus-отчёт, проект сервиса камер, передача и бриф |
| `785e16075` | память: 3 урока + BY-MODULE |

Не закоммичено (наше):
- `Services/code_reader/plugin/sdk_plugin.py` — правка `labels`: проверка один раз в `configure`, отказ в `last_error` вида
  `labels[i]: поле Тип`; опечатка не роняет `produce()` (C1 ревью). Ведёт `a2740848ceea4ed66`, отчёта ещё нет.
- `Services/code_reader/tests/test_sdk_labels_robust.py` — слепой тестер `a3de46e9e9d2558da`: 21 тест, 15 красных до правки.
- `Services/code_reader/tests/test_sdk_labels_check.py` — новый, по всей видимости тесты разработчика (по `git status`; не открывал).
- `Services/code_reader/tests/test_sdk_trigger_hazards.py` — правка нестабильного `test_release_logs_durations_for_stop_grabbing_and_each_restore`.
- `Services/code_reader/docs/SETUP_GEV_V4.0.2.R.md` (раздел 3), шапки двух dual-рецептов — от Haiku `ad78b55b4fdf80996`, готово.

Чужие правки владельца — НЕ трогать и не коммитить: `README.md`, `multiprocess_prototype/app.yaml`,
`multiprocess_prototype/recipes/letter_robot_sim.yaml` (из-за неё красный `test_letter_robot_sim_diff.py`), `docs/handoffs/2026-10-14_coordinator.md`.

## 3. Решения владельца

| Дата | Решение |
|---|---|
| 2026-10-16 | «Так не должно быть» — ресайз дисплея не должен портить кадр (исправлено `9be8cc425`) |
| 2026-10-16 | В этот день агенты только Sonnet/Haiku; стенд без окна координатора разрешён |
| 2026-10-16 | Dual-рецепт — `pipeline` по умолчанию в `app.yaml` (позже уточнено 10-17: рецепты разведены) |
| 2026-10-17 | Для ревью — Opus (полный проход) |
| 2026-10-17 | Рецепты развести на два (сделано `d267f711b`) |
| 2026-10-17 | Профиль покоя ID3013 — `On/Line0` (ждать аппаратный триггер, подсветка не мигает) |
| 2026-10-17 | 2.2a закоммитить как заготовку (сделано `383242ac9`) |
| 2026-10-17 | Реализацию сервиса камер пока НЕ запускать: владелец сначала читает проект |
| 2026-10-17 | Новый план `plans/camera-device-service.md` заменяет Task 2.2b; Task 2.3 (секция в GUI) остаётся в `plans/code-reader-gui` |
| 2026-10-17 | Sonnet пишет код; Opus проектирует и ревьюит дизайн, потоки и жизненный цикл. Без костылей, лучшая архитектура; один механизм для ID3013, Hikvision и следующих камер; надёжно, производительно, камеры не пересекаются; qex и графы — по необходимости |

## 4. Лучшие знания

### 4.1 Камеры и SDK — установлено

| Факт | Доказательство |
|---|---|
| Камера 1 `192.168.1.10` (MV-ID3013PM-06M-WBPF-5M-OD, прошивка GEV V4.0.2.R), камера 2 `192.168.1.11` (SENSOTEC); порт ПК 1 Гбит/с | передача 2026-10-16 |
| Исходные значения (ручной возврат, порядок: период -> источник -> режим): `.10` — `TriggerMode=0`, `TriggerSource=0`, `TriggerSelfTriggerPeriod=300`; `.11` — `1 / 0 / 300` | `cam_orig.json`; INFO-строки старта |
| Типы узлов: `ExposureTime`/`Gain` — float; `TriggerMode`/`TriggerSource`/`RunningMode` — enum; `LightBrightness` — int (закрыт); `LightingEnable` — bool; `AmingLightEnable` — enum; `FocusScore` — int (0) | стенд Task 2.1, `phase-2.md:110-118` |
| Зависимые узлы: `TriggerSource` закрыт при `TriggerMode=0`; период закрыт, пока источник не `SelfTrigger` (`0x80020106`); при идущем захвате узлы триггера не пишутся | стенд 2.1, зонд |
| `SelfTrigger` = значение 9, ставится по имени (`set_enum_str`); период от 32 мс. 300 мс -> ~3 к/с; 40 мс -> ~25 к/с; свободный режим камеры 1 однажды 57 к/с | стенд 2026-10-16 |
| Поток ~33 Мбит/с: сеть не ограничивает | замер 2026-10-16 |
| Калибровка фокуса в IDMVS гонит поток кадров; расфокус выглядит как «потеря режима» (кадры без кодов) — отличать по сохранённому кадру (`--out`) | урок памяти `project_code_reader_focus_calibration_streams_frames.md` |
| `0x80020206` = `MV_CODEREADER_E_NETER` (заголовок `MvCodeReaderErrorDefine.h`); на этом приборе так же отвечает `OpenDevice`, когда прибор не отвечает в сети | `SETUP_GEV_V4.0.2.R.md:31-33` |
| `ForceIp` возвращает `0x80020204`, а IP меняется: код ошибки SDK не равен результату | там же |
| Прибор отпускается ~10 с после убийства клиента; повторное открытие через ~9,4 с прошло | бриф; логи 16:30:35.8 -> 16:30:45.2 |

### 4.2 Живой дефект возврата (стенд 2026-10-16, рецепт с самотриггером) — установлено

1. Первая инкарнация: все 6 записей возврата — `0x80020206`, каждая меньше 1 мс (успешная запись при старте — 13–23 мс).
   `logs_live/dual_20261016_trigger/reader_{1,2}/{system,messages}.log`.
2. Остановку дал full-replace того же рецепта; PM сразу поднял читателей заново.
3. **Вторая инкарнация прочитала исходные значения** (`logs/prototype_2/reader_1/messages.log:13-15`: `.10` `0/0/300`;
   `reader_2/messages.log:14-16`: `.11` `1/0/300`) и снова записала `On/SelfTrigger/40`.
4. Вторая инкарнация не записала ни строки остановки или возврата. `TerminateJobObject` снёс дерево через 1,02 с после
   `system_stop_event` (`logs_live/dual_20261016_trigger/launcher/messages.log` #10–#13; код `launcher/spawner.py:200`, `:224`).
5. Вторая инкарнация писала логи в `logs/prototype_2/`, а не в `INSPECTOR_LOG_DIR` прогона: после full-replace каталог логов
   теряется (PM `system.log` #91: `protected 'gui': … отличается … managers.logger…`).
6. Процессы читателей прожили 4,6 с после `shut down successfully` -> «did not stop in 5.0s» (E9). Причина не найдена.
7. На фейке: после отказа возврата следующий `start()` считает самотриггер «исходным», и `Off` теряется навсегда
   (`opus_rev_repro.py` в старом scratchpad; вывод — в ревью, A3).
8. Строка `shutdown` пишется в КОНЦЕ `shutdown()` плагина (`sdk_plugin.py:167-171`), то есть возврат шёл внутри остановки процесса.

### 4.3 Гипотезы (не проверены, камер нет)

| H | Суть | Что решит |
|---|---|---|
| H1 | после `StopGrabbing` в самотриггере запись отвергается | `thread_split_probe` `same`, `--delay 0` против `1.0` |
| H2 | SDK привязан к потоку (открытие и запись в одном потоке, возврат в другом) | `--mode same` против `split` |
| H3 | ломает контекст остановки процесса (сокет, выгрузка) | `release_device` через `backend_ctl` на живом процессе: там `ok`, а при выходе `отказ` |
| H4 | быстрая отдача ошибки сокета на Windows | время вызова `мс=` в зонде |
| H5 | запись дошла, SDK соврал (ложный NETER) | чтение узла сразу после отказа: `прочитано=записанное` |
| H6 | прибор сам вернул сохранённое состояние (перезагрузка или User Set) | `--reopen-after 1,15`: значения после повторного открытия через 1 с и 15 с |
| — | прогноз: сейчас обе камеры в `1 / 9 / 40` (оставила убитая вторая инкарнация) | первая команда раздела 1, п.6 |

### 4.4 Неверные выводы сессии (отозваны)

- «Режим триггера сбросился» — это был расфокус камеры 1.
- «Калибровка фокуса = Smart Tune» — не подтвердилось.
- «3 к/с из-за 100 Мбит» — нет: период самотриггера 300 мс.
- «Камера 1 медленнее из-за модели или настроек» — после выключения питания не повторилось (25,1 к/с на обеих); гипотеза «прежнее состояние прибора».
- «Возврат 0 из 6, камеры остались в самотриггере после первой инкарнации» — опровергнуто логами второй инкарнации (4.2 п.3). Ошибка брифа лидера.
- «Возврат шёл до `shutdown` плагина» — неверное чтение порядка строк (ревью r1 и бриф).

### 4.5 На что смотреть в опытах (Task 1.0)

- После КАЖДОЙ записи читать узел, после отказа тоже (зонд уже так делает): `код=0x80020206, прочитано=цель` — H5.
- Сравнить `same` и `split` при той же задержке (H2); `--delay 0` и `1.0` (H1).
- `release_device` на живом стенде, затем зонд без записи (H3).
- `--reopen-after 1,15` (H6).
- Записать `мс=` у `stop_grabbing` и каждой записи. До и после каждого опыта — зонд без записи; ручной возврат по 4.1.
- Живая запись в прибор — только при остановленном стенде и закрытом IDMVS, исходные сохранить ДО записи.

### 4.6 Проект сервиса камер — рассуждения (подробно: `docs/design/camera-device-service.md`)

- **Почему (a) + (c).** Полный «профиль работы» пишется при каждом старте, включая `Off`; это сходится к нужному состоянию
  из любого исходного, в том числе после убийства. «Профиль покоя» (`On/Line0`) пишется при остановке как best-effort.
  Исходные значения прибора не читаются как истина: так нет потери `Off`. Журнал исходных (d) и возврат прочитанного (b) —
  костыли вокруг отсутствия явного профиля.
- **Почему один поток-владелец.** Все вызовы SDK одного прибора идут из одного потока: снимается H2, нет гонок вызовов SDK,
  правило «`close` только владелец» распространяется на открытие и запись. Команды (`start`, `stop`, `apply`) — сообщения
  в его очередь с дедлайном.
- **Проверка чтением** после каждой записи: результат берётся из прибора, не из кода возврата SDK (H5 и прецедент ForceIp).
- **Группа целиком.** Если рецепт управляет группой (триггер), он задаёт всю группу; частичная группа — отказ в `configure`.
  Узлы вне таблицы не трогаются никогда; скрытые записи (`HikvisionCamera.open` пишет `TriggerMode=Off`) переносятся в таблицу.
- **Живая правка:** `live=True` (экспозиция, усиление) — без остановки захвата; группа триггера — `stop_grabbing` -> запись ->
  `start_grabbing` в том же handle, без ожидания ~10 с отпускания.
- **Что может не сработать:** H1 подтвердится — покой и перезахват без `close` не пройдут (запасной путь: `close` -> `open`
  в том же потоке-владельце); имена функций MVS не проверены на живой камере; `RegistersManager.subscribe` впервые на живом
  пути бэкенда (не зовётся -> дефект framework, эскалация, не обходить); выход приложения во framework (Task 1.8) может
  оказаться глубже; рецепты станут длиннее (группа целиком).
- **Принцип №6:** желаемое — поля register'а (рецепт, GUI); исполняет сеанс в процессе захвата; PM и `device_hub` прибором не владеют.

## 5. Порядок работ по проекту (задачи — §6 проекта)

| Задача | Суть | Исполнитель | Opus |
|---|---|---|---|
| 1.0 | опыты на камерах | лидер, числа — Haiku | вывод |
| 1.1 | таблица узлов и планы (чистая логика) | Sonnet | — |
| 1.2 | Protocol порта + фейк (режимы H1, H5, id потока) | Sonnet | стадия 0 (публичный контракт) |
| 1.3a | сеанс: поток-владелец, жизненный цикл | Sonnet после Opus stage 0 | дизайн + код |
| 1.3b | профили работы/покоя, проверка чтением | Sonnet после Opus stage 0 | дизайн + код |
| 1.3c | живая правка (вклад 2.2b) | Sonnet или teamlead | дизайн + код; ждёт 1.0 (H1) |
| 1.4 | `code_reader` на сеансе | Sonnet | код |
| 1.5 | поля покоя, частота публикации ≤ 5 Гц, `params` в снимке | Sonnet | — |
| 1.6 | рецепты (частично сделано `d267f711b`; профиль покоя добавить в 1.5/1.6) | Sonnet или Haiku | — |
| 1.7 | лишние копии кадра | Sonnet | — |
| 1.8 | framework: выход приложения, каталог логов после full-replace | investigator -> teamlead (Opus) | всё |
| 1.9 | Hikvision MVS на сеансе | Sonnet | код; нужна MVS-камера |
| 1.10 | `device_hub` `HikvisionDriver`: камерой владеет процесс захвата | Sonnet | — |

Что мешает начать: владелец ещё читает проект; `plans/camera-device-service.md` не написан; ADR «один сеанс прибора GenICam»
не оформлен; камеры не в сети (1.0, а от неё 1.3c); есть ли MVS-камера (1.9) — вопрос владельцу; недельный лимит Sonnet
(сброс был 17 окт 22:00 МСК, однажды прерывал ревью). Остальные вопросы владельцу — §8 проекта (3, 4, 5, 6 открыты).

## 6. Процессные правила и ловушки сессии

- Бриф агенту — форма DESIGN / FILES / REDS (хук lint-brief); модель агента — явно; «не коммитить, не пушить» — в тексте брифа.
- Тесты и стенд — только через `scripts/machine_gate.sh` (light/medium/heavy, имя сессии из брифа); exit 75 = пропуск гейтом, не красный.
- В Python-подпроцессах `bash` звать по полному пути Git Bash, иначе уходит в WSL.
- `git add` только явные пути, никогда `-A`. Трейлеры (`Why:`, `Layer:`, `Refs:`, `Co-Authored-By`) — одним абзацем, без пустой строки внутри;
  `Refs: plans/code-reader-gui.md` обязателен (хук commit-msg). После коммита — `git show --stat HEAD`.
- Тест, который может зависнуть, — в daemon-потоке с дедлайном `join`. Hazard-тесты 2.2a №1 и №4 держатся на `join` 0,2–0,3 с.
- Агент-исполнитель упирается в лимит 30 ходов и обрывается без отчёта — дозвать `SendMessage` тем же agentId. Новый запуск стоит ~56k токенов на старт.
- Открытие камеры сразу после остановки стенда падает: прибор отпускается ~10 с. Стенд останавливать по PID (`taskkill /PID <корень> /T /F`), не глобально.
- Длинный heredoc в Bash падает («unexpected EOF», похоже на лимит командной строки) — писать частями по ~7 КБ.
- `rg` по `logs/` и `logs_live/` нужен с `--no-ignore` (каталоги в `.gitignore`).
- Перед вердиктом по живому дефекту — опись логов ВСЕХ каталогов и инкарнаций (после full-replace логи уходят в `logs/prototype_2/`).
- Чужие правки не трогать (раздел 2).
- Стенд с окном: `BACKEND_CTL=1 INSPECTOR_GUI_UNATTENDED=1 INSPECTOR_LOG_DIR=logs_live/<прогон> .venv/Scripts/python.exe -X faulthandler multiprocess_prototype/frontend/run.py <рецепт>`.

## 7. agentId (дозыв через `SendMessage`, не новым запуском)

| Роль | agentId |
|---|---|
| developer 2.1, зонд `mvcr_probe` | `ab350449e3909bd7f` |
| developer 2.2a, правка `labels` (в работе) | `a2740848ceea4ed66` |
| reviewer 2.1 | `a93ffbd3ee523aed6` |
| reviewer стадии 0 (2.2a) | `a1747b39608e9e913` |
| reviewer r1 (2.2a) | `a8d2d73b7b7b9089c` |
| tester 2.1 | `a584c4d62d62083c0` |
| tester 2.2a | `a8ebefc745d8f3f03` |
| tester `labels` | `a3de46e9e9d2558da` |
| инъекции 2.2a (Haiku) | `af5bbb68e36faf93b` |
| docs-writer (Haiku) | `ad78b55b4fdf80996` |
| зонд `thread_split_probe` (Sonnet) | `ab20d08da49d2bdb5` |
| Opus-ревьюер (ревью, проект, эта передача) | `a52844da255df6423` |
| ресайз дисплея: tester / developer / reviewer / investigator | `aa0d96a9ca0286231` / `ac9f98204fcf9a105` / `a2cb23c736850c086` / `abceb3fdef77553f4` |

Свежими по правилам остаются tester и reviewer раунда 1: на тот же механизм их повторно не звать.

## 8. Файлы

- Проект: `D:/PROJECT_INNOTECH/Inspector_vision/Inspector_bottles/docs/design/camera-device-service.md`
- Ревью (проходы 1 и 2, оценка Sonnet): `D:/PROJECT_INNOTECH/Inspector_vision/Inspector_bottles/docs/reviews/2026-10-17_codereader-multicamera-opus-review.md`
- Бриф Opus-ревью: `D:/PROJECT_INNOTECH/Inspector_vision/Inspector_bottles/docs/handoffs/2026-10-17_code-reader-opus-review-brief.md`
- Передача 2026-10-16: `D:/PROJECT_INNOTECH/Inspector_vision/Inspector_bottles/docs/handoffs/2026-10-16_code-reader-dual-cameras.md`
- Ревью r1 и отчёт разработчика: `D:/PROJECT_INNOTECH/Inspector_vision/Inspector_bottles/docs/reviews/2026-10-17_task-2.2a-review-r1.md`, `…/docs/reviews/2026-10-16_task-2.2a-developer.md`
- План: `D:/PROJECT_INNOTECH/Inspector_vision/Inspector_bottles/plans/code-reader-gui.md`, `…/plans/code-reader-gui/phase-2.md`
- Код: `D:/PROJECT_INNOTECH/Inspector_vision/Inspector_bottles/Services/code_reader/core/sdk_reader.py`, `…/Services/code_reader/plugin/sdk_plugin.py`, `…/Services/code_reader/sdk/api.py`, `…/Services/code_reader/tools/mvcr_probe.py`
- Рецепты: `D:/PROJECT_INNOTECH/Inspector_vision/Inspector_bottles/multiprocess_prototype/recipes/qr_reader_sdk_dual_demo.yaml`, `…/qr_reader_sdk_dual_selftrigger.yaml`
- Логи стенда: `D:/PROJECT_INNOTECH/Inspector_vision/Inspector_bottles/logs_live/dual_20261016_trigger/`, `D:/PROJECT_INNOTECH/Inspector_vision/Inspector_bottles/logs/prototype_2/reader_1/messages.log`, `…/logs/prototype_2/reader_2/messages.log`
- Scratchpad старого чата (зонды, `cam_cfg.py`, `cam_orig.json`, `opus_rev_repro.py`): `C:/Users/INNOTECH/AppData/Local/Temp/claude/d--PROJECT-INNOTECH-Inspector-vision-Inspector-bottles/502f726c-e456-4ffa-b1dc-c2b17eec0068/scratchpad/`
- Память: `D:/PROJECT_INNOTECH/Inspector_vision/Inspector_bottles/docs/claude/memory/project_code_reader_selftrigger_period_sets_the_fps.md`, `…/project_code_reader_focus_calibration_streams_frames.md`

## 9. Что я оставил открытым / ненадёжным

- H1–H6 не проверены; прогноз «камеры сейчас в `1/9/40`» — вывод из логов, не чтение прибора.
- Почему процессы, поднятые full-replace, пишут логи в `logs/prototype_2/` и не логируют общий стоп — не разобрано (Task 1.8, framework).
- E9 (4,6 с до выхода процесса читателя) не разобран.
- `test_sdk_labels_check.py` и правку `labels` не читал: отчёта разработчика ещё нет. Состояние зонда `thread_split_probe.py` знаю по его шапке; проверен только на фейке (со слов лидера).
- Находки по коду без воспроизведения: `HikvisionDriver` передаёт серийник в `open(camera_index: int)`; `HikvisionCamera.open` сам пишет `TriggerMode=Off`; nit в `overlay_draw` (`float(scale)` без проверки, лишняя копия серого кадра).
- Имена функций MVS для порта (проект §3.2) на живой камере не проверены. Оценки производительности — по коду, не замер.
- Состояние дерева взято из `git status` на момент записи; правки агентов после этого могли его изменить — сверить (раздел 1, п.1).
