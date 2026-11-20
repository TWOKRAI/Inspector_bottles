# Брифы для слота писателя — лимит переподключения и C-101 (полоса Р2, 2026-11-20)

Вход: поправка координатора `inspector-bottles-fb` и `docs/reports/2026-11-20_cto-review-1.0.md` (строки 53, 99, 129). Код не менялся, это бриф. Рецепты 1.0 — один писатель; `hikvision_letter_robot.yaml` не трогать (R4).

## Бриф А. `max_reconnect_attempts: 0` для `robot_main` и `vfd_belt`

**Вопрос CTO:** доходят ли `params` рецепта до `entry.params`. **Ответ по чтению кода: да, целиком.** Проверено чтением, прогона нет.

| Звено | Где | Что делает |
|---|---|---|
| 1 | `multiprocess_prototype/recipes/devices_sync.py:25-62` `extract_recipe_devices` | отдаёт элементы `devices:` как есть, `params` не трогает |
| 2 | `backend/launch.py:583-597`, `backend/orchestrator_hooks.py:168` | `inject_recipe_devices` кладёт список в конфиг хаба (`recipe_devices`) |
| 3 | `Plugins/hub/device_hub/plugin.py:291-296` `start` | `manager.upsert(dev_dict, origin=…)` для каждой записи |
| 4 | `Services/device_hub/manager.py:591-602` `upsert` | новая запись — `DeviceEntry.from_dict`; существующая — `merged[key] = value`, то есть `params` **заменяется целиком** |
| 5 | `Services/device_hub/drivers/base.py:107-108` | `int(entry.params.get("max_reconnect_attempts", 3))`; `:285` — `<= 0` даёт «без лимита» |
| 6 | `robot_driver_v2/driver.py:153,538`, `vfd_driver.py:49,283` | оба вызывают `super().__init__(entry, …)` и `_note_reconnect_failed()` |

**Не доказано тестом.** Сквозного теста «рецепт → `driver.max_reconnect_attempts == 0`» нет: тесты ставят атрибут руками (`test_reconnect_exhausted_notice.py:79`) или подают `params` прямо в `DeviceEntry` (`test_robot_driver.py:297`).

**Бриф.** (1) Тест через `start()` плагина с `recipe_devices=[{…params: {max_reconnect_attempts: 0}}]` (фабрика `_make_plugin`, `Plugins/hub/device_hub/tests/test_device_hub_plugin.py:29-51`): `driver.max_reconnect_attempts == 0`. Ожидаемое — литерал 0, не из кода. (2) Потом правка `letter_robot_sim.yaml:71-95` (и других рецептов 1.0 — список даёт владелец рецептов): `max_reconnect_attempts: 0` в `params` обеих записей. (3) Стенд на симе: закрытый порт → после 4 неудач `reconnect_exhausted` остаётся False, `conn` не залипает в `failed`.

**Оговорки.** (а) Без лимита хаб ходит на закрытый порт раз в throttle — причина лимита `base.py:104-107` («спам connect»); на стенде замерить число строк лога в минуту, не оценивать глазом. (б) `upsert` заменяет `params` целиком: параметры, сохранённые оператором вручную для того же `id`, исчезают при каждой активации рецепта — не новый дефект, но правка рецепта это заденет; сверить с владельцем. (в) Класс по правилу запуска: рецепт — 1–2 файла, тест — новый; solo не годится для теста (нужен слепой tester), правка yaml — тривиальна.

## Бриф Б. C-101 — две красные `test_no_private_driver_state.py`

Запись — `plans/queue/defects.md:378`, расчёт Д2 2026-11-20. Файл вне зоны Д2; владелец — hub (Р2/Пульт).

- **Факт.** `Services/device_hub/tests/test_no_private_driver_state.py:183,196`: сторож видит 71 тестовый файл, литерал `_SCANNED_FILES = 64` → `assert 71 == 64`. Добавилось 7 файлов 2026-11-15…17 (`test_pause_all*.py`, `test_readiness_*`, `test_registry_root_acceptance.py`).
- **Одним литералом не лечится.** На 71 файле `_private_accesses` находит `_clock` в `Plugins/hub/device_hub/tests/test_readiness_pause_v2.py:232,234` (`getattr(plugin_mod, "_clock")` и `monkeypatch.setattr(plugin_mod, "_clock", …)` — модуль плагина, не драйвер); в `_SEAMS` его нет (16 имён против 15).
- **Рекомендация.** Литерал 71 + запись `"_clock": 1` в `_SEAMS` с комментарием «модуль плагина, а не драйвер» — меньше слоёв, сторож остаётся буквальным. Альтернатива (сторож отличает доступ через модуль плагина от доступа к драйверу) — новая логика на ложное срабатывание одного имени; не рекомендую.
- **Класс.** 1 файл, < 20 строк, нового механизма нет — solo допустимо, сказать вслух. Стадии 3 и 5 без solo: инъекции с предсказаниями ДО запуска — (i) вернуть 64 → красны ровно оба теста; (ii) убрать `"_clock"` из `_SEAMS` → красен только `test_seam_whitelist_is_literal`; (iii) добавить в любой тест строку с `driver._state` → красен `test_tests_do_not_touch_driver_state_fields`. Назвать набор снова после запуска; расхождение — находка. Ревью `reviewer` sonnet.
- **Проверка.** `pytest Services/device_hub/tests/test_no_private_driver_state.py` через `machine_gate.sh` (light); ожидание — `6 passed`. Красный на Windows не проверялся (оговорка Д2).

## Что осталось открытым / ненадёжно

1. Бриф А — по чтению; тест и стенд не гонялись. «Доходит» не равно «работает на стенде».
2. Список рецептов 1.0, куда ставить `0`, не получен; `letter_robot_sim.yaml` — единственный, который я открыл.
3. Выбор рекомендации Б (литерал и whitelist против правки сторожа) — моё мнение, решает владелец hub-кода.
