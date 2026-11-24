# Слабые места (топ-5 по тяжести)

Часть отчёта [README.md](README.md). Диаграммы — [01-diagrams.md](01-diagrams.md).

1. **Второй открыватель камеры жив.**
   - Вход: `git grep -n -E "hikvision|HikvisionCamera" -- Services/device_hub Plugins/hub/device_hub ':!**/tests/**'` — 29 строк.
   - Наблюдение: `HikvisionDriver.connect` открывает камеру по serial (`hikvision_driver.py:67-79`). Кнопка вкладки «Зарегистрировать камеру в реестре» делает `device_upsert` с kind `hikvision` (`controller.py:153-160`). Команды `hik_*` хаба идут в этот драйвер (`Plugins/hub/device_hub/plugin.py:1283-1310`). `camera_service` — третий открыватель (`backends/hikvision.py:67`).
   - План знает этот риск: хаб — после М2 отдельными коммитами (`plans/2026-10-18_camera-device-service/design.md:29-30`), задачи 4.6a–4.6d — P1.
   - Последствие: если хаб подключит такую запись, камера уйдёт процессу `devices`. Процесс камеры при следующем `take_device` получит `busy`, а `failure` readiness заблокирует START линии. Подключает ли хаб запись сам — не проверено.
2. **Любая правка поля MVS закрывает и открывает прибор.**
   - Вход: `driver.py:63`, `plugin/registers.py:21-52`, `session.py:741-776`.
   - Наблюдение: `CAPABILITIES` = `read_back`, `node_describe`, `software_trigger`, `exception_cb`. Все 3 поля вкладки (`frame_rate`, `exposure_time`, `gain`) имеют `apply="restart"`. `_drain` без `live_write` зовёт `_regrab`: `stop_grabbing`, `close`, `open`, весь план `run`, `start_grabbing`.
   - Это ветка Р12 по умолчанию. Выбор ветки для MVS план отдал опыту 0.5 (`docs/design/camera-device-service.md:202`); записи итога я не нашёл.
   - Последствие: каждая правка даёт паузу кадров. README оценивает `open` GigE в 1–3 с (`Services/camera_device/README.md:169`); замера на MVS нет. Команды с `session.call` в это окно могут получить ответ «срок» (`README.md:242-246`).
3. **Управление параметрами MVS неполное.**
   - Вход: `driver.py:67-77`, `registers_base.py:108-116`, `presenter.py:97-109`, `git grep -n "check_bindings(" -- Services`.
   - Наблюдение: привязки `gain_auto` нет. У `exposure_time` нет `enabled_if` по `exposure_auto`. «Применить» шлёт `register_update` мимо GUI-копии register'а. `check_bindings` зовут только тесты ядра (`tests/test_params*.py`, `tests/test_plugin_base.py`); рабочий код её не зовёт, и ключ `BINDINGS` без поля молча игнорируется (`plugin/registers.py:4-5`). Р4 требует контрактный тест `set(BINDINGS) == {вендорские поля register'а}` (`decisions.md:13`); у Hikvision такого вызова `check_bindings` нет.
   - Последствие (по коду, на приборе не воспроизведено): при `exposure_auto=Continuous` план всё равно пишет `exposure_time`, и в `param_errors` может появиться ложный отказ. При `GainAuto` не `Off` прибор может перекрыть `gain`. GUI-копия поля может разойтись со значением процесса.
4. **Универсальность не доказана.**
   - Вход: `plugin_base.py:126-132`, `:341-354`; `registers_base.py:88-96`; `Services/camera_device/README.md:315`.
   - Наблюдение: реестра нет; README обещает строки `drivers/__init__.py`, а такого файла нет. Register ядра несёт значения MVCR/MVS (`Line0`, `Software`, `SelfTrigger`). План `rest` выбирает привязки по префиксу `trigger_`. Поле `driver` у Hikvision не читается, хотя задача 5.1 требует сделать его константой `readonly` у вендора (`tasks/5.1.md:18`).
   - Последствие: цену второго вендора нельзя назвать. Реестр, драйвер `opencv` и контрактный тест по реестру — 3 задачи P1 (5.1–5.3).
5. **Старый путь `core/*` загружается вместе с новым плагином.**
   - Вход: `Services/hikvision_camera/__init__.py:18-21`, `plugin/plugin.py:16`.
   - Наблюдение: любой импорт пакета `Services.hikvision_camera` грузит `core.camera`, `core.discovery`, `core.parameters`, `core.converter`. Новый плагин берёт `FrameConverter.resize` из `core`.
   - Последствие: в процессе камеры живут две реализации одной камеры. Правка `core` ради `sdk_app` или хаба может сломать ресайз нового плагина. Путь держит FREEZE (Р14, `decisions.md:25`), пока у него есть живые вызывающие: хаб и `camera_service`.
