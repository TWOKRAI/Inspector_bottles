# Task 2.3d — прогон break-injection (механический, по прогнозам лида)

Коммит под мутацией: d16a0442c (ветка feat/camera-2-3d). Копия: detached worktree `cam-2-3d-inj`, после прогона удалена; дерево `cam-2-3d-dev` не мутировалось.
Набор A (основной): `Services/camera_device/tests/test_plugin_device_commands.py`, `test_plugin_device_commands_hazards.py`, `test_live_apply_hazards.py` (72 теста).
Набор B (только D10): весь каталог `Services/camera_device/tests` (378 тестов).
Все команды через `machine_gate.sh medium inspector-bottles-20`, таймаут 180 с. Зависаний не было (каждый прогон ~14 с для набора A, ~51 с для каталога).

## Контроль без мутации

- Набор A: первый прогон `1 failed, 71 passed`, красный `test_live_apply_hazards.py::test_apply_в_opening_и_сразу_stop_закрывает_без_start_grabbing`. Повторные прогоны: `30 passed` (только файл `test_live_apply_hazards.py`), затем `72 passed` и `72 passed`. Итого 1 красный из 4 прогонов контроля.
- Каталог `Services/camera_device/tests`: `368 passed, 10 skipped`, rc=0.

## Таблица

| # | прогноз | факт (имена красных, итог passed/failed) | совпало |
|---|---|---|---|
| D1 | H test_сторож_видит_зависший_fn_из_call | `test_live_apply_hazards.py::test_сторож_видит_зависший_fn_из_call`; плюс `test_live_apply_hazards.py::test_apply_в_opening_и_сразу_stop_закрывает_без_start_grabbing` (та же тест, что краснела на контроле). Итог 2 failed / 70 passed | да (сторож красный); второй красный неопределённый |
| D2 | H ..._при_медленном_close_после_stop_...; остальное зелёное или неопределённо | `test_plugin_device_commands_hazards.py::test_list_devices_при_медленном_close_после_stop_отказывает_и_порт_не_зовётся`; плюс тот же `test_apply_в_opening_и_сразу_stop_...` (неопределённый). Итог 2 failed / 70 passed | да (предсказанный красный есть; второй — см. выше) |
| D3 | H test_отказ_enum_devices_без_захвата_отпускает_acquire | `test_plugin_device_commands_hazards.py::test_отказ_enum_devices_без_захвата_отпускает_acquire`. Итог 1 failed / 71 passed | да |
| D4 | H test_параллельные_list_devices_создают_один_порт_... (вероятностно) | `test_plugin_device_commands_hazards.py::test_параллельные_list_devices_создают_один_порт_и_сводят_ссылки_в_ноль`. Итог 1 failed / 71 passed | да (вероятностный прогноз, один прогон) |
| D5 | H test_команда_по_сроку_... оба параметра | `test_команда_по_сроку_отвечает_срок_и_позже_не_исполняется[trigger_software-execute]` и `[describe_params-describe_param]`. Итог 2 failed / 70 passed | да |
| D6 | тот же H, оба параметра | те же два параметра теста `test_команда_по_сроку_...`, набор красных идентичен D5. Итог 2 failed / 70 passed | да (но D5 и D6 неразличимы этим набором) |
| D7 | S test_describe_params_каждый_describe_param_идёт_в_потоке_владельца | `test_plugin_device_commands.py::test_describe_params_каждый_describe_param_идёт_в_потоке_владельца`; плюс `test_plugin_device_commands.py::test_describe_params_без_захвата_с_capability_отказывает` и `test_plugin_device_commands_hazards.py::test_команда_по_сроку_...[describe_params-describe_param]`. Итог 3 failed / 69 passed | частично (предсказанный красный есть; ещё два красных не прогнозировались) |
| D8 | S test_trigger_software_без_capability_отказывает_и_сеанс_не_создан | `test_plugin_device_commands.py::test_trigger_software_без_capability_отказывает_и_сеанс_не_создан`. Итог 1 failed / 71 passed | да |
| D9 | ничего (выживает) | ни одного красного. Итог 72 passed / 0 failed | да (мутант выжил) |
| D10 | H test_сторож_не_срабатывает_на_быстрый_fn_из_call; возможны красные сторожей в test_live_apply_hazards.py | набор A: ни одного красного, 72 passed / 0 failed. Каталог целиком: `test_live_apply_session.py::test_restart_без_restart_regrab_переоткрывает_порт_state_остаётся_grabbing`. Итог 1 failed / 367 passed / 10 skipped (контроль каталога green, поэтому красный приписан мутации) | нет (прогноз не подтвердился; красный оказался в другом файле, вне набора A) |

## Что оставил открытым / ненадёжно

- Тест `test_live_apply_hazards.py::test_apply_в_opening_и_сразу_stop_закрывает_без_start_grabbing` краснел на контроле один раз из четырёх и краснел в D1 и D2. Связь с мутациями не доказана: возможно, это флейк. Для D1 и D2 вклад мутации в этот красный не установлен. Нужен отдельный повтор контроля (N прогонов) и разбор теста.
- D5 и D6 дают одинаковый набор красных. Этот набор не различает два параметра теста (ни одна мутация не отделена от другой).
- D9 выжил: набор A не ловит мутацию. Это факт прогона, оценку значимости не давал.
- D10: прогноз не подтвердился. Набор A не содержит `test_live_apply_session.py`, поэтому красный D10 виден только при прогоне каталога. Набор A для D10 не может считаться подтверждением сторожей.
- Один прогон на мутацию. Флейки и вероятностные прогнозы (D4) этим не исключены.
- Лог мутаций D1–D3 печатал «применена», код возврата не сохранён (pipe в `tail`); D4–D10 вернули rc=0.
- Копия после каждой мутации возвращалась `git checkout -- Services/camera_device/`; после каждого возврата `git status --short` в копии пуст (0 изменений).
