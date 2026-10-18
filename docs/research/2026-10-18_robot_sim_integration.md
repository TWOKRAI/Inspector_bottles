# Интеграция прототипа с внешними симуляторами роботов: RoboDK, Visual Components, CoppeliaSim

Дата: 2026-10-18. Исполнитель: Web Researcher (haiku). Вопрос владельца: можно ли подключить прототип
(Python 3.12, Windows 10, PySide6, multiprocess) к RoboDK, Visual Components или CoppeliaSim вместо
или вместе с собственным симулятором (контроллер-эмулятор на нашем TCP-протоколе v2, 3D-вид, линия
розлива с конвейером). Целевой робот: промышленный SCARA / 4-осевой, программа говорит с контроллером по TCP.

Правило отчёта: каждое фактическое утверждение снабжено URL, который был открыт (`WebFetch`) в этом прогоне.
Утверждения, взятые только из сниппетов поиска (`WebSearch`) без открытия страницы, помечены «не подтверждено».

Ограничения прогона: память проекта (`search.py`) не запускалась — у роли нет Bash (memory hits: n/a (no Bash)).
Публичные страницы CoppeliaSim/RoboDK на момент прогона частично не загрузились (см. раздел «открытое»).

---

## 1. RoboDK

### 1.1 Внешний API из Python
- Пакет `robodk` (PyPI), модуль `robolink`; подключение — при создании объекта `Robolink()`, по умолчанию
  `robodk_ip='localhost'`; `Connect()` при отсутствии запущенного RoboDK пытается его запустить из пути установки.
  Источник: https://robodk.com/doc/en/PythonAPI/robodk.html
- Порт API по умолчанию — 20500 (параметр `-PORT=` переопределяет). Источник: https://robodk.com/doc/en/RoboDK-API-Command-Line-Options.html
- Вывод: клиент **вне процесса** RoboDK (TCP-сокет к приложению), вызовы синхронные (блокирующие по ответу).
  Документация, что вызовы синхронные, явно не цитируется — **частично не подтверждено**.
- Последняя версия пакета на PyPI по открытой странице: 6.0.2, 21 сентября 2026; заявлен Python >=3.5, классификаторы до 3.14
  (совместимо с 3.12). Источник: https://pypi.org/project/robodk/
- Типичная частота обновления: **не подтверждено** (в документации, открытой в прогоне, не найдено).

### 1.2 Управление позой/осями в ~20 Hz и чтение состояния
- `Item.setJoints(joints)`: «Set the current joints of a robot or a target. If robot joints are set, the robot position will be updated on the screen.»
  `Item.Joints()`: возвращает текущие суставы. `Item.setPose(pose)`, `Pose()`. Источник: https://robodk.com/doc/en/PythonAPI/robodk.html
- `setPoses()` описан как «faster speed» по сравнению с `setPose()` — там же.
- Режимы запуска: `RUNMODE_SIMULATE = 1` (симуляция, по умолчанию), `RUNMODE_RUN_ROBOT = 6` — «moves the real robot from the PC (PC is the client, the robot behaves like a server)». Источник: https://robodk.com/doc/en/PythonAPI/robodk.html
- Вывод: 20 Hz по сокету на `setJoints` плausible, но **не подтверждено** — нет замера и нет заявленной частоты.

### 1.3 Программа внутри симулятора и цифровые сигналы
- Программы: `RunProgram(wait_for_finished)`; «Set to True to block execution during a simulation until the program finishes.» Источник: https://robodk.com/doc/en/PythonAPI/robodk.html
- В примерах: `program.setDO('DO_NAME', 1)` и `program.waitDI('DI_NAME', 1)`; `RunInstruction(...)`; `Pause(ms)`. Источник: https://robodk.com/doc/en/PythonAPI/robodk.html
- Чтение DI из Python (`getDI`) — **не подтверждено** (в открытой части документации не найдено).
- Симуляционное время: `SimulationSpeed` по умолчанию 5 (ускорение); `setSimulationSpeed`. Источник: https://robodk.com/doc/en/PythonAPI/robodk.html

### 1.4 Виртуальный контроллер / эмуляция TCP-сервера
- Драйверы RoboDK управляют **реальным** роботом с ПК: «A robot driver can control a real robot that is connected to a computer.» Большинство драйверов — TCP/IP сокет; подключение через «Connect to robot…» и IP. Источник: https://eu.robodk.com/doc/en/Robot-Drivers.html
- Пользовательские драйверы можно писать «using any programming platform» (в т.ч. Python-модуль или исполняемый файл). Источник: https://eu.robodk.com/doc/en/Robot-Drivers.html
- Эмуляции «сервера контроллера» (RoboDK говорит с нашим протоколом v2 как с контроллером) страница не описывает: **не подтверждено**, и по смыслу RoboDK-драйвер — это клиент к реальному контроллеру. Встреченный на форуме прокси-сценарий (Python TCP-сервер между RoboDK и KUKA) — только сниппет поиска, **не подтверждено**.
- Список брендов с драйверами (Fanuc, ABB, KUKA, UR, Epson, Yaskawa и др.) — только из сниппета, **не подтверждено** (страница https://eu.robodk.com/doc/en/Robot-Drivers.html открыта, но списка брендов в ответе не было). SCARA-поддержка на открытой странице не упомянута.

### 1.5 Конвейер, детали, камера
- Виртуальная камера: «retrieve the color image (8 bits), grayscale image (8 bits) and depth map (8 bits or 32 bits)», вывод «as a disk file or as plain data». Источник: https://robodk.com/doc/en/Computer-Vision-Accessing-simulated-camera-image-API.html
- Точное имя функции Python для получения кадра, частота кадров, требования к запущенной симуляции — **не подтверждено** (страница ссылается на примеры, которые не открывались).
- Конвейер/поток деталей: сниппеты форума про conveyor — **не подтверждено**; штатного «belt»-объекта по открытым страницам не найдено.

### 1.6 Лицензия, цена, Windows, headless
- Цены (страница https://robodk.com/pricing, валюта EUR, копирайт 2026):
  - Trial: бесплатно, 30 дней, генерация программ до 50 инструкций, после 30 дней — «basic functionality».
  - Educational: €145 / 1 год, только студенты и преподаватели с университетским email; до 1000 инструкций.
  - Professional: €3995 бессрочно, сопровождение 1 год, далее €1500/год.
  - Robot Calibration: €17995. Enterprise и Classroom — «contact for pricing».
  - Python API / драйверы / подключение к реальному роботу по каждому тарифу на странице **не подтверждено** (таблица не читается однозначно).
- Headless: флаг `-NOUI` — «Start RoboDK without the User Interface (Window and 3D view)», предназначен для фонового режима через API; `-HIDDEN`, `-NOSPLASH`, `-SKIPMAINT`. Источник: https://robodk.com/doc/en/RoboDK-API-Command-Line-Options.html
- Windows: нативная поддержка Windows — **не подтверждено** (официальные системные требования не открыты; в прогоне не найдено).

### 1.7 Зрелость
- Актуальная версия пакета `robodk` 6.0.2 (21.09.2026) — https://pypi.org/project/robodk/. Активность поддержки — по этой дате, отдельный changelog не открывался.

---

## 2. Visual Components (VC)

### 2.1 Внешний API
- Официальная документация Python API: версия 5.0 (https://help.visualcomponents.com/5.0/Premium/en/Python_API/Overview2.htm) — классы vcRobotController, vcSignal (vcBoolSignal, vcIntegerSignal…), vcSimulation, vcSimInterface, vcPythonProcessHandler. Описание, как внешний процесс подключается к VC через Python API, на открытых страницах **не найдено**: скрипты выполняются **внутри** VC. Внешний Python-процесс — **не подтверждено**.
- Наличие Python 3 API в 5.1: https://help.visualcomponents.com/5.1/Robotics/en/English/WhatsNew.htm (ссылка на «Module and Class Overview», текст страницы неполный).
- Версии VC: 5.1.0 — 11 июня 2026; 5.1.1 — 28 сентября 2026 (https://help.visualcomponents.com/5.1/Robotics/en/English/WhatsNew.htm).
- Внешняя связь — OPC UA: VC выступает **OPC UA клиентом**, подключается к внешним серверам; «The OPC UA client in Connectivity feature of VC requires the connected server to be standard-compliant»; «uamethods cannot be used with the OPC UA connection plugin in VC»; «The connection test may fail in VC» (форум, без указания версии). Источник: https://forum.visualcomponents.com/t/opc-ua-server/1931
- Частота обновления OPC UA, поведение при симуляции без хода — **не подтверждено** (в ветке нет цифр; сниппет-форум утверждает, что сигналы работают только при запущенной симуляции — не подтверждено).
- Структуры данных: VC работает с простыми типами; структуры надо разбивать на примитивы (сниппет форума, **не подтверждено** как официальная позиция).

### 2.2 Драйв позы / чтение состояния / программа с I/O
- Управление позой 20 Hz через внешний процесс — **не подтверждено**: в открытой документации нет внешнего клиента, кроме OPC UA.
- Робот-программы и сигналы (vcSignal, SignalMap) существуют в Python API (https://help.visualcomponents.com/5.0/Premium/en/Python_API/Overview2.htm). Сигналы OPC UA можно связывать с сигналами компонентов через Connectivity (форум, https://forum.visualcomponents.com/t/opc-ua-server/1931).

### 2.3 Эмуляция контроллера
- VC — клиент OPC UA; эмулятор TCP-протокола v2 внутри VC не описан. Наш протокол (TCP, байтовые регистры) VC напрямую не говорит. Для нас путь — внешний OPC UA-сервер-переводчик, не проверено на практике.

### 2.4 Конвейер и камера
- Официально подтверждённых данных о камере-симуляторе с выгрузкой изображения в Python — **не подтверждено**.
- Ветка форума (сниппет): «Python inside VC: OpenCV нельзя добавить; нужен .NET API или внешний Python 3» — **не подтверждено** (страница не открывалась).
- Компонент для съёмки кадра («eCat») — только сниппет, **не подтверждено**.

### 2.5 Лицензия, цена, Windows, headless
- Студенческий trial: 30 дней, только образование, коммерция запрещена; образовательный пакет — 30 плавающих мест Premium OLP, бессрочный или на 1 год; **цена не указана**. Источник: https://www.visualcomponents.com/academia/
- Коммерческая лицензия: цена не опубликована в открытых источниках — **не подтверждено** (Capterra/GetApp-сниппеты не открывались; «€0.01 per feature» — сниппет стороннего сайта, не принимается).
- Windows: системные требования 4.10 (Windows 10/11, 8 GB RAM, 3 GB диска) — страница visualcomponents.com/system-requirements найдена поиском, **не открывалась**; требования к 5.1 — не подтверждено. Режима headless/batch для VC — **не подтверждено**.

### 2.6 Зрелость
- Версия 5.1.1 (28.09.2026), 5.1.0 (11.06.2026) — https://help.visualcomponents.com/5.1/Robotics/en/English/WhatsNew.htm.

---

## 3. CoppeliaSim

### 3.1 Внешний API из Python
- ZeroMQ remote API: «The ZeroMQ remote API allows to control a simulation (or the simulator itself) from an external application». Клиент Python: пакет `coppeliasim-zmqremoteapi-client`; `RemoteAPIClient()`, `client.require('sim')`. Источник: https://manual.coppeliarobotics.com/en/zmqRemoteApiOverview.htm (установка и `require` — из поисковых сниппетов страницы PyPI, **сама страница PyPI не открылась**, поэтому `require` — не подтверждено как официальное; см. ниже).
- Режим: вне процесса (out-of-process), по ZeroMQ, поддерживаются stepped (`sim.setStepping(True)`, `sim.step()`) и non-stepped режимы. Источник: https://manual.coppeliarobotics.com/en/zmqRemoteApiOverview.htm
- Порт: в открытой странице порт по умолчанию не назван; в Lua-примере — 23002. Источник: тот же. Значение 23000 из сниппета PyPI — **не подтверждено**.
- Legacy remote API: «deprecated», оставлен «for backward compatibility». Источник: https://manual.coppeliarobotics.com/en/remoteApiOverview.htm
- Асинхронный клиент (asyncio) — из сниппета PyPI, **не подтверждено** (страница не открылась).
- Скорость/латентность: документация не даёт цифр — **не подтверждено**.

### 3.2 Управление позой / состояние / сигналы
- Суставы: `sim.setJointTargetPosition`, `sim.setJointPosition`, `sim.getJointPosition` — есть в индексе API. Источник: https://manual.coppeliarobotics.com/en/apiFunctions.htm
- Сигналы (`sim.readSignal`, `sim.setInt32Signal`): на индексной странице — только ссылка на «signal properties»; функции подтверждены не полностью. Использование как цифровых I/O — **не подтверждено**.
- Программа робота с инструкциями внутри симулятора: CoppeliaSim — не интерпретатор робот-программ; скрипты Lua/Python (встроенные и внешние). Источник: https://manual.coppeliarobotics.com/en/apiFunctions.htm (поиск, сниппет по архитектуре скриптов — не подтверждено).

### 3.3 Эмуляция TCP-сервера контроллера
- Lua-сокеты в CoppeliaSim (`sim.socket` или внешний плагин) — **не подтверждено** (найдена только документация LuaSocket общего вида, не CoppeliaSim). Оценка: возможность поднять TCP-сервер внутри сцены **не подтверждена**, в открытых источниках не найдена.
- Текущий ZMQ-API — клиент-управление симулятором, не сервер протокола робота.

### 3.4 Конвейер, камера
- Vision sensor: «image content can be accessed via the API», «A vision sensor has a fixed resolution». Функция `sim.getVisionSensorImg` есть в индексе. Источники: https://manual.coppeliarobotics.com/en/visionSensors.htm, https://manual.coppeliarobotics.com/en/apiFunctions.htm
- Глубина/облако точек — **не подтверждено**. Частота кадров — **не подтверждено**.
- Конвейер (belt): штатного компонента по открытым страницам не найдено; есть примеры движения через `sim.moveToPose` в корутине (форум, сниппет; **не подтверждено**).

### 3.5 Лицензия, цена, Windows, headless
- Edu: «CoppeliaSim Edu is exclusively available for use by students, teachers and professors of schools and universities»; «CoppeliaSim Edu cannot be used commercially». Источник: https://manual.coppeliarobotics.com/en/licensing.htm
- Pro и Lite — коммерческие; цены — по запросу, страница с ценами (coppeliarobotics.com/pricing) не открылась — **не подтверждено**.
- Headless: `-H` — «truly headless mode, without any GUI or GUI dependencies», требуется display server, vision sensor работает только в POV-Ray режиме; `-h` — эмулированный headless. Источник: https://manual.coppeliarobotics.com/en/commandLine.htm
- Windows: пример `coppeliaSim.exe -h -s5000 -q myScene.ttt` в документации; официальные системные требования не открыты — **не подтверждено**.

### 3.6 Зрелость
- Последняя версия в истории релизов на открытой странице: V4.10.0 (14 мая 2025). Новее — **не подтверждено** (страница https://manual.coppeliarobotics.com/en/versionInfo.htm, по тексту, не перечисляет 2026 релизы). Источник: https://manual.coppeliarobotics.com/en/versionInfo.htm

---

## 4. Сравнительная таблица

| Критерий | RoboDK | Visual Components | CoppeliaSim |
|---|---|---|---|
| Python API | `robodk`/`robolink`, сокет к приложению, порт 20500 | Python 3 API внутри VC; внешняя связь — OPC UA (VC клиент) | ZMQ remote API, вне процесса, stepped/non-stepped |
| Частота 20 Hz | не подтверждено | не подтверждено | не подтверждено |
| setJoints / чтение | да (`setJoints`, `Joints()`) | через сигналы/OPC UA — не подтверждено | да (`setJointPosition`, др.) |
| Программа + DO/DI | `setDO`, `waitDI` (чтение DI не подтверждено) | сигналы vcSignal; OPC UA (без UA Methods) | скрипты; сигналы не подтверждены |
| Эмуляция TCP-сервера контроллера | нет (драйверы — клиенты к реальным) | нет (VC — OPC UA клиент) | не подтверждено |
| Камера в Python | кадр: color/gray/depth (функция не подтверждена) | не подтверждено | `sim.getVisionSensorImg` (частота/GPU не подтверждены) |
| Конвейер | не подтверждено | не подтверждено | не подтверждено (примеры есть) |
| Лицензия, цена | Trial 30 дней; Edu €145/год (студенты/преподаватели); Pro €3995 | Trial студентов 30 дней; цена не опубликована | Edu только учеб.; Pro/Lite — по запросу |
| Headless | `-NOUI` | не подтверждено | `-H` / `-h` |
| Windows | не подтверждено | 4.10 требования (не открыто) | не подтверждено |
| Последняя версия | пакет 6.0.2 (21.09.2026) | 5.1.1 (28.09.2026) | 4.10.0 (14.05.2025, см. открытое) |

---

## 5. Рекомендация (5–8 строк)

1. Ни один из трёх **не эмулирует TCP-протокол v2** нашего контроллера: RoboDK-драйверы — клиенты к реальным контроллерам, VC — OPC UA клиент, CoppeliaSim — внешний управляющий API симулятора.
2. Спайк стоит делать на **CoppeliaSim** (ZMQ remote API, stepped-режим, `-H`, `getVisionSensorImg`) как дополнение, если нужна детерминированная кинематика и кадры: коммерческая лицензия неизвестна по цене, Edu не подходит компании.
3. **RoboDK** — второй кандидат для офлайн-проверки траекторий и `setJoints`/`RunProgram` с DO/DI; Professional €3995 без проверенного подтверждения Python API по тарифу — сначала уточнить у вендора.
4. **VC** — не первый выбор для нашей задачи: сложный OPC UA-путь, цена по запросу, внешний Python не подтверждён.
5. Свой симулятор обязан сохранить: протокольную эмуляцию нашего контроллера (байтовые регистры, ~20 Hz state), инъекцию сбоев (обрыв TCP, задержки, битые кадры), детерминированные тесты без внешнего GUI.
6. Внешний симулятор не заменяет тесты контракта протокола: он проверяет кинематику и камеру, а не наш wire-формат.
7. Прежде чем тратить время: вопрос к вендорам — точная частота `setJoints` на нашем железе (RoboDK), цена Pro/Lite (CoppeliaSim), коммерческая цена VC.

---

## Что осталось открытым / ненадёжным

- Частота обновления (20 Hz и выше) для всех трёх — **не подтверждено**, замеров нет.
- RoboDK: точная функция получения кадра камеры, `getDI`, поведение блокировки `setJoints`, наличие Python API в каждом тарифе, Windows-совместимость — **не подтверждено** (страница примеров не открывалась; `robodk.com/pricing` открыта, но таблица тарифов неоднозначна).
- VC: официальный раздел Connectivity/OPC UA, внешний Python-процесс, камера, headless, системные требования 5.1, цена — **не подтверждено** (многие источники — сниппеты форумов или сторонних сайтов).
- CoppeliaSim: порт по умолчанию (23000 против 23002 — из двух разных источников), `require`/asyncio в клиенте (страница PyPI не открылась: `coppeliasim-zmqremoteapi-client`), latency, Lua-сокеты, Windows, цены Pro/Lite (страница цен не открылась), новее ли 4.10.0 — **не подтверждено**.
- Не найдено ни у одного вендора явного «virtual controller / TCP server emulation» — вывод «нет» основан на отсутствии описания в открытых страницах, а не на доказанном отсутствии функции.
- Сниппеты поиска (включая форумы RoboDK о KUKA-прокси, форум VC о OpenCV, сторонние сайты о ценах и ОС) не использованы как доказательства.
- Память проекта не проверялась (нет Bash у этой роли).
- Вопрос «прибыльно/сколько стоит внедрить» не решён; это вне исследования.

Открытые вопросы, которые переживут задачу, стоит занести в `docs/claude/OPEN_QUESTIONS.md` — занесение делает лид.

---

## Sources

Открыты (WebFetch) в этом прогоне:
- https://robodk.com/doc/en/PythonAPI/index.html
- https://robodk.com/doc/en/PythonAPI/intro.html
- https://robodk.com/doc/en/PythonAPI/robodk.html
- https://robodk.com/pricing
- https://robodk.com/doc/en/RoboDK-API-Command-Line-Options.html
- https://robodk.com/doc/en/Computer-Vision-Accessing-simulated-camera-image-API.html
- https://pypi.org/project/robodk/
- https://eu.robodk.com/doc/en/Robot-Drivers.html
- https://help.visualcomponents.com/5.1/Robotics/en/English/WhatsNew.htm
- https://help.visualcomponents.com/5.0/Premium/en/Python_API/Overview2.htm
- https://forum.visualcomponents.com/t/opc-ua-server/1931
- https://www.visualcomponents.com/academia/
- https://manual.coppeliarobotics.com/en/zmqRemoteApiOverview.htm
- https://manual.coppeliarobotics.com/en/remoteApiOverview.htm
- https://manual.coppeliarobotics.com/en/licensing.htm
- https://manual.coppeliarobotics.com/en/commandLine.htm
- https://manual.coppeliarobotics.com/en/visionSensors.htm
- https://manual.coppeliarobotics.com/en/apiFunctions.htm
- https://manual.coppeliarobotics.com/en/versionInfo.htm

Не открывались (только сниппеты поиска; утверждения по ним помечены «не подтверждено»):
- https://pypi.org/project/coppeliasim-zmqremoteapi-client/ (открытие вернуло ошибку)
- https://visualcomponents.com/system-requirements
- https://forum.visualcomponents.com/t/how-to-use-camera-with-robot-program/6930
- https://robodk.com/forum/Thread-Generating-Robot-Programs-Through-API (и связанные форумные ветки RoboDK)
- https://coppeliarobotics.com/pricing
