# План: device-tree-recipe — колонка устройств в сервисах (master-detail) + рецепт как источник истины

**Slug:** `device-tree-recipe` • **Ветка:** `feat/robot-vfd-services` (продолжение device-hub)
**Refs в коммитах:** `Refs: plans/device-tree-recipe.md`
**Исполнитель:** Opus. **Предыдущий план:** `plans/device-hub.md` (Фазы 0–5 + 2 раунда фиксов ревью DONE).

## Статус выполнения

- [x] **Фаза А** — хотфикс интеграционных багов (доставка devices-дельт, публикация upsert) — БАГ-1+БАГ-2 + тесты; probe перенесён на чекпойнт после Фазы C (см. ниже)
- [ ] **Фаза B** — рецепт как источник истины устройств (GUI CRUD → активный рецепт)
- [ ] **Фаза C** — вторая колонка устройств внутри страниц сервисов (master-detail + «+ Добавить»)
- [ ] **Фаза D** — страница добавления устройства (автопоиск камер + ручной ввод)
- [ ] **Фаза E** — чистка (devices.yaml/store, комбо) + документация
- [ ] **Верификация** — ОБЯЗАТЕЛЬНЫЙ qt-mcp probe-прогон (см. ниже) + чек-лист железа

## Контекст

device-hub работает на бэкенде (процесс `devices`, 46 команд, async connect, драйверы),
но живая проверка владельца выявила:

1. **Баги интеграции GUI↔hub** (диагностированы точно, см. Фазу А): «добавить устройство
   не получается», «Подключить — висит». Причина — qt-mcp probe-smoke не был прогнан
   (правило памяти нарушено), юнит-тесты с фейками эти разрывы не ловят.
2. **Решения владельца по UX/хранению (2026-06-12, уточнено):**
   - **ДВЕ колонки.** Первая колонка — как сейчас: выбор сервиса («Камеры → Hikvision»,
     «Робот Delta», «ПЧ»). **Внутри страницы выбранного сервиса** — вторая колонка со
     списком зарегистрированных устройств этого сервиса, последняя строка всегда
     **«+ Добавить устройство»**. Справа от списка — область содержимого.
   - Клик «+ Добавить» показывает в области содержимого **страницу добавления**:
     для камер — автопоиск (как в hikvision) + ручной ввод адреса + имя; для робота/ПЧ —
     пока только ручной ввод (адрес, тип соединения, имя), автопоиск отложен.
   - Выбор устройства в списке → **страница устройства = текущие панели управления**
     (камера: параметры/старт/стоп; робот: телеметрия/CVT/рисование; ПЧ: пуск/частота/статус),
     привязанные к этому device_id. Выпадающие комбо устраняются.
   - Навигация первой колонки НЕ меняется → правка BaseTreeNavTab (rebuild_tree) НЕ нужна.
   - **Источник истины — РЕЦЕПТ** (выбор владельца, осознанный trade-off): списки
     зарегистрированных устройств с параметрами хранятся в top-level секции `devices:`
     YAML рецепта. Без активного рецепта список пуст, добавление заблокировано с подсказкой.
     Pipeline-плагины обращаются к устройствам по `device_id` (уже работает).
   - `data/devices.yaml` (глобальный реестр) упраздняется.

## Опорные факты (разведано, проверено по коду)

| Что | Где | Факт |
|-----|-----|------|
| Дерево секций | `multiprocess_framework/modules/frontend_module/widgets/tabs/base_tree_nav_tab.py` | QTreeWidget из `list[SectionSpec]`; иерархия через `SectionSpec.parent_key`; `lazy=True` откладывает фабрику; страницы — стек по key |
| Построение дерева | `.../nav_tree_utils.py:77-112` | `build_nav_tree_from_specs(tree, specs)` — сначала top-level, потом дети |
| Динамики в нав-дереве НЕТ | base_tree_nav_tab.py | API add/remove узлов отсутствует — **и не нужен**: по уточнению владельца устройства живут во ВТОРОЙ колонке внутри страницы сервиса (master-detail), нав-колонка не меняется |
| Секции сервисов | `multiprocess_prototype/frontend/widgets/tabs/services/_sections.py:349-441` | `build_services_sections()`; cameras_root → вебкамера + hikvision; `__robot__`, `__vfd__` top-level с DeviceComboController внутри |
| Активный рецепт из GUI | `services.recipes.get_active()`, event `RecipeActivated` | пример подписки: `services/tab.py:127-142` |
| Чтение/запись raw рецепта | `multiprocess_prototype/adapters/stores/recipe_store.py:97` | `RecipeStoreFromManager.read_raw(slug)` / `save_raw(slug, data)` — merge top-level ключей, ruamel сохраняет комментарии. **Идеально для секции `devices:`** |
| Текущий CRUD-поток | `devices_common/{presenter,combo,editor_dialog}.py` | DevicesPresenter (device_list/describe/upsert/remove/connect) — **переиспользуется**; combo — устраняется |
| Автопоиск камер | `services/hikvision/controller.py:111` | `HikvisionRegistrationHelper`: `hik_enum` (device-less команда hub) → выбор → upsert. Логика переезжает на страницу добавления |
| Активация рецепта → hub | `multiprocess_prototype/recipes/devices_sync.py` + `recipes/presenter.py:356` | extract → `device_upsert_many {connect:true}` ДО replace_blueprint; boot-инжект в launch.py |

## Диагностированные баги (root cause точные — чинить по координатам)

- **БАГ-1 (корневой):** `multiprocess_prototype/frontend/process.py:76-83` — GuiProcess
  подписан в StateStore только на `"processes.**"` и `"system.**"`. Дельты `devices.*`
  до GUI **не доходят вообще**: комбо не обновляется, `conn` после «Подключить» вечно
  молчит (команда на бэкенде отрабатывает!). Фикс: добавить подписку `"devices.**"`
  по образцу соседних строк. Бонус: `_replay_initial_state` (state_store_manager.py:328)
  при подписке сразу отдаст снимок — список заполнится при старте.
- **БАГ-2:** `Plugins/hub/device_hub/plugin.py:456-461` — `cmd_device_upsert` не зовёт
  `_publish_full_registry()` (в `cmd_device_upsert_many` — зовёт, ~:482). Одиночное
  добавление из GUI не публикуется в state. Фикс: добавить вызов; проверить
  `cmd_device_remove` (публикует ли после удаления).
- **БАГ-3:** `services/vfd/section.py:79-84` и `robot/section.py:75-85` —
  `DeviceComboController` создан без `on_add_clicked` → кнопка «Добавить» кликается
  в пустоту (combo.py:236). **Не чинить проводку комбо** — комбо устраняется Фазой C;
  add-поток реализуется страницей добавления (Фаза D).

---

## Фаза А — Хотфикс доставки состояния (немедленно, до редизайна)

**Файлы:** `multiprocess_prototype/frontend/process.py`, `Plugins/hub/device_hub/plugin.py` + тесты.

1. БАГ-1: подписка `"devices.**"` в GuiProcess (1 строка + тест на список подписок).
2. БАГ-2: `_publish_full_registry()` в `cmd_device_upsert` и при необходимости в
   `cmd_device_remove` (+ тест: upsert → publish_cb получил `devices.registry`).
3. **Мини probe-smoke (ОБЯЗАТЕЛЬНО):** запустить `python multiprocess_prototype/run.py`
   с env `QT_MCP_PROBE=1` (порт 9142) в фоне; qt-mcp: вкладка Сервисы → ПЧ видна;
   через `request_command`-путь любым способом (например временно через qt-консоль/скрипт
   или просто проверив, что комбо заполнился после рестарта с непустым реестром) убедиться,
   что дельты доходят. Минимум: qt_snapshot вкладки + отсутствие ошибок в qt_messages.
   Убивать процессы строго по PID.

**Acceptance:** существующие тесты зелёные; дельты devices.* доходят до GUI (живой признак).
**Коммит:** `fix(gui): доставка devices-дельт в GUI + публикация одиночного upsert` /
`Layer: mixed` / `Refs: plans/device-tree-recipe.md`.

## Фаза B — Рецепт как источник истины устройств

**Цель:** список устройств живёт в активном рецепте; GUI CRUD редактирует рецепт; hub —
runtime-отражение.

**Файлы:** `multiprocess_prototype/recipes/devices_sync.py` (расширить),
`frontend/widgets/tabs/services/devices_common/` (новый `recipe_devices.py` — GUI-хелпер),
`Plugins/hub/device_hub/plugin.py` (+команда), тесты.

1. **GUI-хелпер `RecipeDevicesStore`** (devices_common/recipe_devices.py, без Qt):
   - `list(kind=None) -> list[dict]` — устройства из raw активного рецепта
     (`services.recipes.get_active()` + `read_raw`); нет активного → `[]`.
   - `upsert(entry: dict)` / `remove(device_id)` — read_raw → модифицировать top-level
     `devices:` (список dict, ключ id) → `save_raw(slug, {"devices": [...]})`.
   - Нет активного рецепта → `RecipeDevicesError("нет активного рецепта")` — GUI
     показывает подсказку и блокирует добавление.
2. **Единый CRUD-поток GUI:** добавление/правка/удаление устройства =
   (а) `RecipeDevicesStore.upsert/remove` (персист в рецепт),
   (б) при успехе — `device_upsert`/`device_remove` в hub (runtime, существующие команды;
   upsert с `origin="recipe:<slug>"`). Ошибка hub НЕ откатывает рецепт (рецепт — истина;
   hub догонит при активации) — но показывается пользователю.
3. **Активация рецепта = полная синхронизация:** новая команда hub
   `device_sync_set {devices: [...], origin}`: upsert всех из списка + **remove** устройств
   с origin `recipe:*`, отсутствующих в списке (предварительно disconnect + стоп воркера —
   reuse cmd_device_remove-путь). Вызов — там же, где сейчас `device_upsert_many`
   (recipes/presenter.py:356 и boot-инжект: плагин в start() при наличии recipe_devices
   делает sync_set, а не просто upsert). Деактивация — ничего не трогает (соединения
   живут до следующей активации).
4. **DeviceManager/плагин:** `registry_path`/RegistryStore сделать опциональными
   (store=None → реестр чисто in-memory). Полное удаление файла-стора — Фаза E.
5. Тесты: RecipeDevicesStore (tmp-рецепт: upsert/remove/нет активного), device_sync_set
   (upsert+удаление лишних recipe-устройств, manual-устройства не трогаются), порядок
   «рецепт → hub» в CRUD-потоке.

**Acceptance:** добавленное из GUI устройство есть в YAML рецепта (секция devices:);
после рестарта приложения с этим рецептом устройство в списке и auto-connect;
смена рецепта убирает чужие recipe-устройства из hub.
**Коммиты:** `feat(prototype): рецепт — источник истины устройств (RecipeDevicesStore + device_sync_set)` /
`Layer: mixed`.

## Фаза C — Вторая колонка устройств внутри страницы сервиса (master-detail)

**Файлы:** `devices_common/device_list_panel.py` + `devices_common/master_detail.py` (новые),
`services/{robot,vfd,hikvision}/section.py` (переделать страницы), тесты.
**Framework НЕ трогается** — навигация первой колонки остаётся как есть.

1. **`DeviceListPanel`** (devices_common, переиспользуемый): QListWidget слева —
   зарегистрированные устройства данного kind из `RecipeDevicesStore.list(kind)` (Фаза B),
   у каждого элемента имя + conn-индикатор (● connected / ○ disconnected / ✕ error из
   `devices.state.<id>.conn` через bindings); последний элемент ВСЕГДА
   **«+ Добавить устройство»** (отдельная роль, визуально отличим). Сигналы:
   `device_selected(device_id)`, `add_requested()`. Метод `refresh()` (repopulate с
   сохранением выбора).
2. **`DeviceMasterDetail`** (devices_common): композит — слева DeviceListPanel,
   справа QStackedWidget: страница-заглушка («выберите устройство» / «активируйте рецепт»),
   страницы устройств (lazy, по device_id), страница добавления (Фаза D). Выбор в списке
   переключает стек.
3. **Структура страницы сервиса:**
   ```
   Колонка 1 (как сейчас)        Страница сервиса
   ┌──────────────┐   ┌──────────────────┬───────────────────────────┐
   │ Сервисы      │   │ Устройства       │  Панели устройства        │
   │ Камеры       │   │ ● Робот Delta №1 │  (текущие: телеметрия/    │
   │  └ Hikvision │   │ ○ Робот стенд    │   CVT/рисование — robot;  │
   │ Робот Delta◄─┼─► │ ──────────────── │   пуск/частота — vfd;     │
   │ ПЧ           │   │ + Добавить устр. │   параметры/старт — cam)  │
   │ …            │   └──────────────────┴───────────────────────────┘
   ```
   - `robot/section.py`: страница = DeviceMasterDetail(kind="robot"); страница устройства —
     существующая связка widget+controller с зафиксированным `controller.set_device(id)`
     (комбо не строится). Сверху строки-страницы: имя, conn, кнопки
     Подключить/Отключить/Изменить/Удалить («Изменить» — reuse DeviceEditorDialog
     с describe-заполнением → CRUD-поток Фазы B; «Удалить» — подтверждение → remove).
   - `vfd/section.py`: аналогично (kind="vfd").
   - Камеры: узел «Hikvision» первой колонки (как сейчас) → страница =
     DeviceMasterDetail(kind="hikvision"); страница устройства — текущие hikvision-контролы
     по device_id (serial/index из params). «Вебкамера» — без изменений.
4. **Динамика списка:** DeviceListPanel подписан на `devices.registry.*` (после Фазы А
   дельты доходят) + `RecipeActivated` → debounce (QTimer ~200 мс) → `refresh()`
   с сохранением выбора. Тест: upsert → элемент появился; remove → исчез (выбор → заглушка).
5. Удалить DeviceComboController из секций robot/vfd (класс пока оставить — Фаза E).

**Acceptance (pytest-qt):** список строится из рецепта; «+ Добавить» последний; выбор
устройства открывает панели, привязанные к id; динамика и сохранение выбора работают.
**Коммит:** `feat(gui): колонка устройств в страницах сервисов — DeviceListPanel/MasterDetail` /
`Layer: prototype`.

## Фаза D — Страница «+ Добавить устройство»

**Файлы:** `devices_common/add_page.py` (новая секция-страница), правки `_sections.py`, тесты.

Страница добавления — НЕ отдельная секция навигации, а страница в правой области
DeviceMasterDetail (открывается выбором «+ Добавить устройство» в колонке устройств).

1. **Общая страница AddDevicePage(kind)** (devices_common/add_page.py):
   - Поле «Имя устройства», поле id (автогенерация slug из имени, редактируемое).
   - **Для камер (kind=hikvision):** блок «Автопоиск»: кнопка «Найти устройства» →
     `hik_enum` (асинхронно через RequestRunner) → таблица найденных (model/serial/ip) →
     выбор строки заполняет поля. Ниже блок «Вручную»: адрес/serial/index.
     (Логика — перенос `HikvisionRegistrationHelper`.)
   - **Для робота/ПЧ:** блок «Вручную»: тип соединения (tcp | bridge | rtu-заглушка),
     поля по типу (host/port/unit_id; bridge → выбор робота из устройств рецепта),
     протокол (из `device_protocols(kind)`), параметры (как в DeviceEditorDialog —
     reuse его form-логики, вынести общие поля в shared-форму, не дублировать).
     Автопоиск роботов/ПЧ — отложен (заглушка-надпись).
   - Кнопка «Добавить устройство» → CRUD-поток Фазы B → успех: дерево обновится
     (Фаза C.4), выбор переходит на новый узел.
   - Нет активного рецепта → страница показывает «Активируйте рецепт, чтобы добавить
     устройство» и блокирует форму.
2. Тесты (pytest-qt): форма по kind, enum-заполнение, upsert-вызов, блокировка без рецепта.

**Acceptance:** камера добавляется через автопоиск И вручную; робот/ПЧ — вручную
(tcp и bridge); запись появляется в YAML рецепта и в дереве.
**Коммит:** `feat(gui): страница добавления устройства — автопоиск камер + ручной ввод` /
`Layer: prototype`.

## Фаза E — Чистка + документация

1. Удалить `DeviceComboController` (`devices_common/combo.py`) + его тесты; grep использований.
2. Удалить `registry_path`/`data/devices.yaml`-путь: RegistryStore из DeviceManager
   (in-memory only), убрать параметр из base.yaml, удалить `registry/store.py` + тесты
   (или оставить store для headless-сценариев БЕЗ рецепта — РЕШЕНИЕ: удалить, рецепт
   обязателен — зафиксировать ADR-DH-007 «рецепт — единственный источник устройств»).
3. `DeviceEditorDialog` — остаётся только для «Изменить» (проверить, что create-режим
   не используется, упростить).
4. Обновить README/STATUS device_hub и devices_common, `plans/device-hub.md`
   (пометка: UX-итерация → этот план), статусы фаз здесь.
5. `python -m scripts.sync` + `python scripts/validate.py`.

**Коммит:** `chore(gui): удалить комбо устройств и файловый реестр devices.yaml + ADR-DH-007` /
`Layer: mixed`.

## Верификация (ОБЯЗАТЕЛЬНАЯ, через probe — провал прошлого раза учтён)

**qt-mcp probe-прогон (env QT_MCP_PROBE=1, порт 9142, чистка процессов строго по PID):**
1. Поднять sim-робота: `python -m Services.robot_comm.server` (127.0.0.1:5021), фон.
2. `python multiprocess_prototype/run.py` (активный рецепт с devices: или активировать
   robot_demo из GUI).
3. Страницы Робот/ПЧ/Камеры→Hikvision: колонка устройств с устройствами из рецепта +
   «+ Добавить» последним — qt_snapshot + qt_screenshot.
4. «+ Добавить» на странице ПЧ → вручную: name «Тест ПЧ», transport bridge → робот,
   протокол gd20_bridge → «Добавить» → элемент появился в списке, запись в YAML рецепта
   (проверить файл).
5. Робот (tcp 127.0.0.1:5021) → страница → «Подключить» → индикатор connected,
   телеметрия живая (push) → «Послать тест-job» → echo/queue меняется.
6. ПЧ-страница → Пуск 25 Гц → статус running/частота из зеркала sim.
7. «Отключить» робота → остаётся disconnected ≥10 с (desired-state, НР-1).
8. Рестарт приложения → устройства на месте (из рецепта), auto-connect отработал.
9. Переключение рецептов ×2 → процесс devices жив (PID), чужие recipe-устройства ушли.
10. pytest полный + `scripts/validate.py`.

**Чек-лист железа (выполняет владелец):**
- Робот включён, 192.168.1.7 в сети → добавить робота на вкладке → Подключить →
  X/Y/Z в телеметрии → тест-job (рука едет) → «Отключить» держится.
- ПЧ: добавить bridge-устройство поверх робота → Пуск 25 Гц (лента крутится) →
  Стоп → Сброс аварии. Heartbeat растёт, comm_errors — смотреть дельту.
- Камера hikvision: автопоиск находит, регистрация, параметры/старт/стоп.
- Выключить робота физически → quality=bad/реконнект-индикация; включить → сам поднялся.

## Риски

| Риск | Митигация |
|------|-----------|
| refresh() списка теряет выбор при deltas-шторме | debounce + сохранение selection; обновлять только при реальном изменении списка (сравнить ids) |
| save_raw конкурентно с активацией рецепта | CRUD только из Qt main (read-modify-write одного файла последовательно); активация читает свежий raw |
| ruamel/save_raw ломает форматирование рецепта | recipe_store уже на ruamel (сохраняет комментарии) — тест на дамп |
| Страница устройства тяжёлая (lazy) | SectionSpec.lazy=True для устройств-узлов |
| Нет активного рецепта на чистой установке | подсказка + блокировка добавления (решение владельца); robot_demo как стартовый пример |
