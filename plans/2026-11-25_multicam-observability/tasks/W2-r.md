# Task W2-r: карточки приборов камер и считывателей — адрес и связь (только показ, шаг 1)

- **Статус:** [PENDING] · **Level:** Middle+ · **Assignee:** developer
- **Module contract:** new-lite (`widgets/tabs/services/source_devices/` — новая секция GUI; `model.py` — чистый Python)
- **Dependencies:** W2-c3 (слита: `frontend/state/source_devices.py::SourceDeviceStates`). Файлы с W2-c3 не пересекаются; старт после её слияния.
- **Gate:** `machine_gate.sh light <session>` по TESTS; радиус `multiprocess_prototype/frontend/widgets/tabs/services/tests` (medium)
- **Files:** `multiprocess_prototype/frontend/widgets/tabs/services/source_devices/{__init__.py,model.py,widget.py,section.py}`, `multiprocess_prototype/frontend/widgets/tabs/services/_sections.py`, `multiprocess_prototype/frontend/widgets/tabs/services/tests/test_source_device_cards.py`
- **Acceptance:** блок ACCEPTANCE
- **Handoff:** developer (REDS в брифе, красный прогон до правки src, break-injection) -> reviewer (стадия 5, sonnet) -> лид: снимок qt-mcp на `fake_quad_synth` (W2-q2; команда `fake_cable` — W2-q)
- **Параллельно с:** W2-q.

ДОПУЩЕНИЕ (предложение, владелец ещё не утвердил): карточки читают дерево `processes.*` напрямую, зеркала хаба `devices.*` нет; план camera-device-service 4.6a-d не трогается. Если владелец выберет зеркало хаба: `model.py` и `widget.py` остаются, меняется источник — вместо `SourceDeviceStates` подписка `devices.state.<id>.conn` (как `DeviceListPanel`, `devices_common/device_list_panel.py:84-86`), а список карточек — из `devices.registry.*`; это работа 4.6a-d (хаб пишет зеркало), эта задача её не делает.

Почему не `DeviceListPanel`/`DeviceMasterDetail`: они читают записи `devices` рецепта (`RecipeDevicesStore.list(kind)`) и `devices.state.*.conn`, которые пишет только хаб (`device_list_panel.py:10-12,113-124`); камеры и считыватели — плагины процессов `blueprint.processes[].plugins[]`, их в `devices` нет. Повторяем вид (глиф + имя), не класс.

Что показывает карточка сегодня (проверено чтением, `0c4b6a068`):
- Камера (`processes.<p>.state.plugins.<n>.{link,identity}`): IP, MAC, serial, model из `identity` (или последняя известная, если прибор закрыт); связь `link.state` (`up|idle|silent|lost|off`), `reconnecting`, `outages`, `attempts`, `lost_for_s`.
- Считыватель (`processes.<p>.state.code_reader_sdk.*`, `Services/code_reader/plugin/sdk_plugin.py:385-401,414-420`): `device_state`, `device_held`, `frames`, `errors`, `last_error`; адрес — `device_ip` рецепта. Блоков `link`/`identity` НЕТ.
- Разрыв считывателя (в отчёт и в карточку текстом «связь: нет данных»): нет `link` (тишину считыватель не публикует, стенд 2026-11-25: 80 с без кабеля — `running`, ноль строк), нет `identity` (MAC, serial, model), нет `reconnect`. Закрывается переносом считывателя на общую основу приборов (П4 п.8); W2-b/W2-b1 заморожены.

TASK: W2-r — секция «Приборы источников» под «Камеры» во вкладке Services: карточка на каждый плагин камеры и считывателя активного рецепта — номер, процесс, адрес, связь; только показ   PLAN: plans/2026-11-25_multicam-observability/plan.md (П3, П4 п.3)
ROLE: developer
CHAIN: lead -> you -> reviewer (стадия 5)
DESIGN (decided by the lead — you type it, you do not derive it):
  1. `model.py` (без Qt):
     - `list_source_devices(recipe: dict | None) -> list[dict]`: обход `blueprint.processes[].plugins[]`; `plugin_class` начинается с `Services.camera_device.` или `Services.hikvision_camera.` -> `kind "camera"`; с `Services.code_reader.` -> `kind "reader"`; иное пропустить. Запись: `{"source": f"{process_name}.{plugin_name}", "process", "plugin", "kind", "number": camera_id | reader_id | None, "address": device_ip | None, "serial": device_serial | None}`. Порядок — как в рецепте.
     - `card_text(spec: dict, link: dict | None, identity: dict | None, last_identity: dict | None, reader_state: dict | None) -> dict`: `{"glyph", "title", "lines": list[str]}`. Глиф по связи: `up` -> `●`, `idle` -> `◐`, `silent` -> `◌`, `lost` -> `✕`, `off` -> `○`, нет данных -> `?`. `title` = `f"{kind_ru} № {number} · {process}"` (`kind_ru`: «Камера» / «Считыватель»; номер `None` -> `—`). Строки камеры: `"адрес: <ip>"` (живой -> последний известный с пометкой `(последний известный)` -> `device_ip` рецепта -> `—`), `"MAC: …"`, `"s/n: …"` (живой -> последний -> `device_serial` рецепта), `"связь: <state>"` + `", переподключение: попытка <attempts>"` при `reconnecting`, `"обрывов: <outages>"`, `"без связи: <lost_for_s> с"` при не `None`. Строки считывателя: `"адрес: <device_ip рецепта>"`, `"связь: нет данных"`, `"состояние: <device_state>, прибор взят: да|нет"`, `"кадров: <frames>, ошибок: <errors>"`, `"ошибка: <last_error>"` при непустой. Пустое значение -> `—`.
  2. `widget.py`, `SourceDeviceCards(QWidget)`: `__init__(self, *, read_recipe: Callable[[], dict | None], bindings: Any = None, parent=None)`. Сетка/столбец `QFrame`-карточек (глиф + заголовок жирным + `QLabel` строк); `refresh()` перечитывает рецепт и строит карточки заново. Состояние: свой `SourceDeviceStates`; подписку делает сам виджет (не `SourceDeviceStates.bind` — тому нечем позвать перерисовку): те же два шаблона, `bindings.bind_fanout(pattern, cb, owner=self)` (уборка по `owner`, `bindings.py:323-326`), `cb` = `states.apply(path, value)` и при не-`None` ключе — перерисовка + для считывателей `bindings.bind_fanout("processes.*.state.code_reader_sdk.**", cb, owner=self)` в словарь `{process: {leaf: value}}` (формы узла и листа — как в W2-c3). Перерисовка по дельте — коалесцировать `QTimer.singleShot` 200 мс (как debounce `device_list_panel.py:76-80`), не на каждую дельту. Кнопок НЕТ. GUI ничего не запускает и команд не шлёт.
  3. `section.py` — по образцу `hikvision/section.py:20-82`: `_SourceDevicesSection` (ключ `"__source_devices__"`, ленивый `widget()`, `on_activated` -> `refresh()`), `build_source_devices_section(services, runtime, *, parent_key=None, title="Приборы источников") -> SectionSpec`. `read_recipe` — то же чтение, что `app.py:1087-1102` (`recipe_manager.get_active` + `read_recipe`; где взять `recipe_manager` в секции — посмотреть соседнюю секцию, читающую рецепт, по символу; не нашёл за 3 вызова -> СТОП и вопрос лиду). `bindings` — `runtime.bindings` (`runtime_deps.py:83`).
  4. `__init__.py` — экспорт `build_source_devices_section`.
  5. `_sections.py`: после секции Hikvision (`_sections.py:415-417`) — `sections.append(build_source_devices_section(services, runtime, parent_key="cameras_root", title="Приборы источников"))`. Смена рецепта: вкладка уже ловит `RecipeActivated` (`tab.py:127`); секция пересобирает карточки на `on_activated` — достаточно для шага 1 (строка отчёта, если вкладка открыта во время смены).
FILES (complete list — nothing else; need another file -> stop and ask the lead):
  1. multiprocess_prototype/frontend/widgets/tabs/services/source_devices/__init__.py — новый
  2. multiprocess_prototype/frontend/widgets/tabs/services/source_devices/model.py — новый
  3. multiprocess_prototype/frontend/widgets/tabs/services/source_devices/widget.py — новый
  4. multiprocess_prototype/frontend/widgets/tabs/services/source_devices/section.py — новый
  5. multiprocess_prototype/frontend/widgets/tabs/services/_sections.py — регистрация
  6. multiprocess_prototype/frontend/widgets/tabs/services/tests/test_source_device_cards.py — новый
REDS (predicted red tests):
  - multiprocess_prototype/frontend/widgets/tabs/services/tests/test_source_device_cards.py::test_list_cameras_and_readers_from_recipe (рецепт-словарь в форме `hikvision_id3013_quad`: 2 камеры `hikvision`, 2 считывателя, 2 `overlay_draw` -> 4 записи, `kind` и `number` литералами; `overlay_draw` пропущен)
  - …::test_camera_card_live_identity_and_lost (`link {"state": "lost", "reconnecting": True, "attempts": 3, "outages": 1, "lost_for_s": 12}`, `identity ip "192.168.1.20"` -> глиф `✕`, строки `"адрес: 192.168.1.20"`, `"связь: lost, переподключение: попытка 3"`, `"без связи: 12 с"`)
  - …::test_camera_card_falls_back_to_last_identity_then_recipe (`identity None`, последний `ip .20` -> `"адрес: 192.168.1.20 (последний известный)"`; без обоих -> `device_ip` рецепта; без всего -> `"адрес: —"`)
  - …::test_reader_card_shows_gap (`reader_state {"device_state": "running", "device_held": True, "frames": 10, "errors": 0}` -> строки `"связь: нет данных"`, `"кадров: 10, ошибок: 0"`, глиф `?`)
  - …::test_widget_updates_on_leaf_delta (qt offscreen; настоящие `GuiStateBindings` на фейк-мосте; дельта узла `…plugins.camera_device.link` `{"state": "up"}`, затем лист `….link.state "lost"` -> через <= 0,5 с у карточки `cam_0.camera_device` глиф `✕`)
  - …::test_no_buttons_no_commands (у виджета нет `QPushButton`; фейк `command_sender` не получил ни одного вызова)
  - …::test_section_registered_under_cameras_root (`build_services_sections(...)` содержит ключ `__source_devices__` с `parent_key "cameras_root"`)
ACCEPTANCE (every number with its command):
  - `<py> -m pytest -q --tb=short multiprocess_prototype/frontend/widgets/tabs/services/tests/test_source_device_cards.py` -> exit 0, 7 passed
  - medium: `<py> -m pytest -q --tb=short multiprocess_prototype/frontend/widgets/tabs/services/tests` -> против снимка лида
  - `ruff check -q` по шести путям -> 0
  - Break-injection (предсказания лида): `leaf_ignored_in_widget` -> `test_widget_updates_on_leaf_delta`; `no_last_identity_fallback` -> `test_camera_card_falls_back…`; `draw_plugins_listed` -> `test_list_cameras_and_readers…`
  - Лид (не агент): GUI-стенд `INSPECTOR_GUI_UNATTENDED=1` на `fake_quad_synth` (W2-q2; команда `fake_cable` — W2-q), qt-mcp `qt_find_widget` карточек: 4 карточки «Камера № 0..3»; `fake_cable {"plugged": false}` у `cam_2` -> карточка `cam_2` глиф `✕` за <= `link_silence_s` + 2 с.
TESTS: bash "$(git rev-parse --path-format=absolute --git-common-dir)/../scripts/machine_gate.sh" light <session> <py> -m pytest -q --tb=short multiprocess_prototype/frontend/widgets/tabs/services/tests/test_source_device_cards.py
OUT OF SCOPE: кнопки «переподключить»/«отпустить прибор» (шаг 2, после слова владельца; команды `take_device`/`release_device` в работе заперты `run_locked`); миграция вкладки Hikvision со старого комбо (`devices_common/README.md`); зеркало хаба `devices.*` (camera-device-service 4.6a-d); `link`/`identity` у считывателя (П4 п.8); история связи, графики.
TRAPS: в колбэке подписки не читать `bindings.read_model` — он обновляется ПОСЛЕ колбэка (`app.py:457-459`). Дельта узла приходит при первой публикации блока, дальше — листья; выдача при привязке — листья. Ключ камеры — `plugin_name` рецепта (`hikvision` у quad, `camera_device` у фейков), путь дерева — `processes.<p>.state.plugins.<plugin_name>`. У считывателя путь без `plugins.` (`state.code_reader_sdk`). `QT_QPA_PLATFORM=offscreen`; GUI-тесты не параллельно.
HANDOFF IN: W2-c3 — `SourceDeviceStates(apply, link, identity, last_identity, link_state, bind)`.
REPORT: STATUS (DONE|BLOCKED), files, команды и вывод по ACCEPTANCE, красные до/после, раздел «Что оставил открытым / ненадёжно» (обязательно: что карточка считывателя не может показать).
