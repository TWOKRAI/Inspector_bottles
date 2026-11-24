# Система камер: оценка архитектуры по коду `main`

Дата: 2026-11-23. Автор: tech-writer (Opus), сессия гейта `camera-K-assess`. Код: `main` на `b57349f68`.
Объём: ядро `Services/camera_device`, вендор `Services/hikvision_camera` и их связь с `device_hub`, `camera_service`, `code_reader`,
`phone_gateway`, вкладкой GUI и рецептами. Шкала: 1 — не работает или опасно, 3 — работает с известными дырами, 5 — нечего добавить.

## Части отчёта

| Часть | Что в ней |
|---|---|
| этот файл | суть, проверка фактов из брифа, таблица оценок |
| [01-diagrams.md](01-diagrams.md) | 6 диаграмм Mermaid: слои, сеанс, путь кадра, живая правка, карта ядра, риски |
| [02-weaknesses.md](02-weaknesses.md) | топ-5 слабых мест: вход -> наблюдение -> последствие |
| [03-good-and-missing.md](03-good-and-missing.md) | что хорошо и не трогать; чего нет и сколько это стоит по плану |
| [04-discrepancies.md](04-discrepancies.md) | расхождения кода с решениями плана, design-документами, страницей от 17 ноября |
| [05-open.md](05-open.md) | что я оставил открытым или ненадёжно; какие документы прочитаны |

## Суть

1. Ядро сделано хорошо: один поток-владелец на прибор, запись с проверкой чтением, 9 общих команд, наблюдаемость средствами framework. Ядру — 4 из 5.
2. Hikvision — единственный вендор на ядре. Второго вендора и реестра драйверов нет, поэтому универсальность ядра не доказана.
3. Ядро делает прибору одного владельца, но `device_hub` и `camera_service` по-прежнему открывают ту же камеру старым путём `core/*`. Этот путь грузит даже `__init__.py` пакета нового плагина.
4. У драйвера MVS нет `live_write` и `restart_regrab`. Поэтому любая правка поля — это `close` и `open` прибора и пауза кадров: 12 уровней вызова от `register_update` до DLL.
5. Общий вердикт — 3 из 5: ядро 4, система вокруг ядра 2. Дороже всего закрыть второго открывателя (хаб, 4 задачи P1). Дешевле всего — устаревшие `STATUS.md`, `plan.md` и `Port dtype="image/gray"`.

## Проверка фактов из брифа

| Факт | Вердикт | Источник |
|---|---|---|
| 2.3a–2.4, 4.1, 4.2a–4.4 в `main` (К4' `6cb212213`, R4 `dc7883ce6`) | да | `git branch --contains 6cb212213` и `dc7883ce6` -> `main`, `feat/pult-belt-speed` |
| Стенд 2026-11-23, MV-CS020-10GC: ~24,97 Гц, ERROR 0, перезахват `release_device -> take_device` | не мой замер, отчёта нет | `docs/claude/OPEN_QUESTIONS.md:2622` (незакоммиченная правка) сам пишет: «числа выше — из брифа лида К, не из файла» |
| Драйвер MVS — в `Services/hikvision_camera/driver.py`, не в ядре | да | `driver.py`, 437 строк; в ядре из портов только `testing/fake_port.py` |
| Старый путь `core/*` ещё в дереве; кто импортирует | да, 48 строк импорта: Services 40, Plugins 8, prototype 0 | `git grep -n -E "hikvision_camera\.core" -- '*.py'`; рабочий код: `__init__.py:18-21`, `plugin/plugin.py:16`, `sdk_app/main_window.py`, `Plugins/hub/device_hub/plugin.py:1260`, `Plugins/sources/camera_service/backends/hikvision.py:17-20`; через пакет — `Services/device_hub/drivers/hikvision_driver.py:73` |
| `create_port(driver)` в `plugin_base.py` — единственный выбор драйвера | нет | точек выбора две: функция `create_port(driver)` знает только `"fake"` (`plugin_base.py:126-132`); вендор переопределяет метод `create_port(self)` (`plugin.py:39-43`), поле `driver` при этом не читается |
| Команд ядра девять | да | `plugin_base.py:177-187`; плюс общие `set_config`, `register_update`, `set_enabled` у любого процесса с плагином (`2026-11-22_camera-W4-stand.md`, строка A4) |

Известные дефекты из брифа сверены с кодом:
- `gain_auto` нет в `BINDINGS`: подтверждено. В `driver.py:67-77` 9 ключей. `git grep -n "gain_auto" -- '*.py' '*.yaml'` — 0 строк.
- У `exposure_time` нет `enabled_if`: подтверждено (`registers_base.py:113-116`, `plugin/registers.py:21-30`).
- «Применить» вкладки не зовёт `set_value` GUI-менеджера: подтверждено частично. `presenter.set_parameters` шлёт `register_update` прямо процессу (`presenter.py:97-109`). В 4 файлах вкладки `set_value` нет. Что такое «GUI-менеджер» в этой фразе, я не проверял.
- `CommandPanel` — мёртвый код: подтверждено. `git grep -n "CommandPanel" -- '*.py'` — 7 строк, импорт только в `frontend/tests/test_bridge.py`. Р14 замораживает его (`plans/2026-10-18_camera-device-service/decisions.md:25-28`). Файл `command_panel.py` сейчас изменён в рабочем дереве чужой незакоммиченной правкой.

## Оценки

| Критерий | Балл | Причина | Источник |
|---|---|---|---|
| 1. Framework универсален: второй вендор без правки ядра | 3 | Порт и 4 хука (`create_port`, `bindings`, `software_trigger_binding`, `_build_item`) по форме дают вендору не трогать ядро. Второго вендора и реестра нет. Первый вендор потребовал правки ядра: BGR и дебайер | `plugin_base.py:310-322`, `plugin.py:39-65`, `STATUS.md:45-46`; `git ls-files Services/camera_device` — каталога `drivers/` нет |
| 2. Меньше слоёв | 3 | От `_on_register_update` до вызова DLL 12 уровней вызова, 1 очередь и 1 переход потока. Каждый уровень несёт гарантию. У MVS путь всегда ведёт в полный перезахват | [диаграмма 4](01-diagrams.md#4-путь-живой-правки-поля); `session.py:708-776`; `driver.py:63` |
| 3. Подключаемость, тестируемость, изоляция отказа | 3 | Одна камера — один процесс. Исключения колбэков не роняют сеанс. Отказ виден как состояние и `health`. Хаб и `camera_service` могут открыть ту же камеру. `failure` одной камеры блокирует START всей линии; это политика readiness, рецепт может её смягчить | `session.py:425-432`; `plugin_base.py:288-304`, `:386-391`; `hikvision_driver.py:67-79`; стенд W4, строка «B readiness» |
| 4. GUI формирует топологию, бэкенд headless | 4 | GUI ядро не импортирует. Вкладка шлёт команды и `register_update`. `auto_start` задаёт рецепт. `take_device`/`release_device` в `running` отклоняются ключом `run_locked_commands` в 6 рецептах | `controller.py:52-58`; `presenter.py:97-109`; `git grep -c run_locked_commands -- multiprocess_prototype/recipes/*.yaml` — 6 файлов |
| 5. Наблюдаемость для оператора и `backend_ctl` | 4 | 6 уровней через `publish_metric`. 10 ключей событий идут одним `merge` по отличиям. `health` — на переходах в отказ, `flight_dump` — на зависании. Слабо: текст отказа `PortError kind=other: acquire: other` не называет причину; `params_schema` и `meta` нет (1.3, 1.4 — P1) | `plugin_base.py:225-226`, `:414-419`, `:437-524`; стенд W4, строка «B take_device»; `plan.md:129-130` |
| 6. Границы слоёв framework -> Services -> Plugins -> prototype | 4 | `sentrux check .` через гейт: 43 правила, «All rules pass», exit 0. Камере принадлежат 2 правила: ядро не импортирует `hikvision_camera` и `code_reader`. Импорт `sdk` вендора правило не ловит. На хаб и `camera_service` правил нет | `machine_gate.sh light camera-K-assess sentrux check .`; `.sentrux/rules.toml:179-189`; `STATUS.md:51` |
| 7. Тестируемость | 3 | Ядро: 8940 строк тестов на 2962 строки кода (3,0); 365 строк `def test_`. Вендор: 3481 на 4515 (0,77); 219 строк `def test_`. Порт MVS проверен только на фейковом классе `MvCamera`. Маркер `hardware` есть в 1 файле, без `CAMERA_HARDWARE=1` он пропускается | `wc -l`; `tests/core_rig.py:69-83`; `tests/test_port_contract.py:56`; прогон каталогов — exit 75, см. ниже |
| **Общий вердикт** | **3** | Ядро — 4: механизм владельца, проверки чтением и наблюдаемости собран и покрыт тестами. Система — 2: вторые открыватели, перезахват на каждую правку, нет второго вендора | части 02–04 |

Прогон тестов. Каталог `Services/camera_device/tests` (`medium`) гейт пропустил: `STAND WINDOW — skipped`, exit 75. Каталоги целиком я не прогнал.
Прогнал 2 файла, которые связывают настоящие объекты (`light`): `test_live_apply_wiring.py`, `test_plugin_on_core_session.py` — `24 passed, 4 warnings in 6.80s`, exit 0.
Числа 462 passed (ядро) и 314 passed (вендор) — из `docs/reports/2026-11-22_camera-device-service_W4.md`, не мои.
