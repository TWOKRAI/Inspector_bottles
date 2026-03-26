# DECISIONS.md — Журнал архитектурных решений

Этот файл фиксирует все принятые архитектурные решения, чтобы новые
нейронки/разработчики не открывали уже закрытые вопросы.

Формат записи:
```
## ADR-NNN: Заголовок
- Дата: YYYY-MM-DD
- Статус: принято | отклонено | устарело
- Контекст: почему вопрос возник
- Решение: что решили
- Причина: почему именно так
- Отклонённые альтернативы: что рассматривали и отвергли
```

---

## ADR-098: Рецепты — два файла (`recipes.yaml` + `settings_recipes.yaml`), слот `0` = заводской
- Дата: 2026-03-26 (уточнение 2026-03-26: всегда два файла, классы хранилищ)
- Статус: принято
- Контекст: Нужно разделить «базу» снимков регистров и «базу» пресетов UI; явная нумерация слотов: **0** — дефолт, **1…n** — сохранённые сорта.
- Решение: **`RecipeManager`** — фасад; физически **всегда** два YAML: **`RegisterRecipesYamlStore`** → `recipes_path` (только **`register_recipes`**, **`current_register_recipe`**, **`version`**), **`AppRecipesYamlStore`** → **`settings_recipes_path`** по умолчанию рядом с `recipes_path` или из **`GuiConfig.settings_recipes_path` / `FrontendConfig.build_dict`**. Во втором файле ключ записи — **`app_recipes`**; при чтении допускается алиас **`settings_recipes`**. Старый **объединённый** `recipes.yaml` с вложенным **`app_recipes`** при **`save()`** разносится: основной файл без `app_recipes`, пресеты — во второй файл. Константа **`DEFAULT_RECIPE_SLOT_ID = "0"`**; fallback на слот **`default_value`** в презентерах при необходимости.
- Причина: Две логические БД; единый контракт загрузки/сохранения без режима «всё в одном файле» в продакшене.
- Отклонённые альтернативы: опциональный второй файл — усложняет тесты и деплой; один монолитный класс без разделения ответственности — хуже сопровождение.

## ADR-097: Touch-клавиатура — проброс из `FrontendConfig`, делегат по колонкам
- Дата: 2026-03-25
- Статус: принято
- Контекст: После **ADR-096** таблицы/деревья не получали **`touch_keyboard`** из конфига приложения; отдельные **`QLineEdit`** (слот рецепта, имя региона) не подключались. **`setItemDelegate`** на весь **`QAbstractItemView`** избыточен для колонок с чекбоксами; на Windows (PyQt5) запрещён сброс делегата в **`None`** (**ADR-096** / hotfix).
- Решение: В **`FrontendConfig`** — поле **`touch_keyboard`** (dict, опционально), в **`build_dict`** ключ **`touch_keyboard`** (мерж с **`app_cfg`**). **`FrontendAppContext.get_touch_keyboard`**, фабрика вкладок передаёт dict в панели рецептов / настроек / ROI / постобработки. Хелпер **`multiprocess_prototype/frontend/touch_keyboard_bind.bind_touch_keyboard_line_edit`**. **`StructuredTableWidget`** / **`StructuredTwoLevelTreeWidget`**: touch-делегат только на не-checkbox колонки (**`setItemDelegateForColumn`**), сброс — **`QStyledItemDelegate(self)`** по тем же индексам, без **`setItemDelegateForColumn(..., None)`**.
- Причина: Один источник правды для сенсорного стенда; клавиатура на полях формы и в ячейках; меньше побочных эффектов на чекбокс-колонках.
- Отклонённые альтернативы: только per-widget YAML на каждой вкладке — дублирование; глобальный **`setItemDelegate`** без разделения колонок — уже вызывало проблемы на Windows.

## ADR-096: Touch-клавиатура — `TouchKeyboardConfig`, интеграция numeric / tables
- Дата: 2026-03-25
- Статус: принято
- Контекст: На панельных ПК нужен ввод без физической клавиатуры; в App уже были **`VirtualKeyboard`** / **`VirtualKeyboardMini`** и клик по полю; во **`frontend_module`** поле **`touch_keyboard_factory`** в **`NumericViewConfig`** не доходило до view.
- Решение: Dataclass **`TouchKeyboardConfig`** в **`components/base/touch_keyboard_config.py`** (режим **off | mini | full**, порог **`min_screen_height_px`**, геометрия). Модуль **`widgets/keyboard/touch_keyboard.py`**: **`should_show`**, **`show_for_line_edit`**, **`install_touch_keyboard_on_line_edit`**; одна активная клавиатура закрывается перед открытием следующей. **`SliderValueView`** / **`SpinBoxValueView`**: клик по **`QLineEdit`**; таблицы/дерево — **`TouchLineEditItemDelegate`** + опционально **`touch_keyboard`** / **`touch_keyboard_factory`** на **`StructuredTableWidget`**, **`StructuredTwoLevelTreeWidget`**, тулбары. **`StructuredTableWidget`**: сигнал **`cell_changed`** дополняется **`itemChanged`** для текстовых ячеек. Реестр слайдера (**`default_factories`**) передаёт **`touch_keyboard`** (dict допускается, **`coerce_touch_keyboard`**).
- Причина: Конфиг без зависимости components→widgets; переиспользование клавиатур **`widgets/keyboard`**; совместимость с **`touch_keyboard_factory`**.
- Отклонённые альтернативы: только фабрика без typed config — хуже для YAML/рецептов.

## ADR-091: ROI по камерам — вложенный `processor.crop_regions`
- Дата: 2026-03-25
- Статус: принято
- Контекст: Плоский legacy `{region → {params, rect}}` и расширенный набор полей ROI не подходят под несколько камер и удобную сборку рецепта.
- Решение (фаза 1): В памяти и в регистре — **`camera_id → region_name → [x, y, width, height]`**. Адаптеры **`normalize_crop_regions_payload`** (загрузка + миграция плоского legacy в камеру по умолчанию из **`CroppedRegionsTabUiConfig.camera_ids`**) и **`merge_crop_regions_payload`** (снимок в `ProcessorRegisters.crop_regions`). UI: **дерево камера → регионы** (**`StructuredTwoLevelTreeWidget`**), поле имени и слайдеры; **«Сохранить»** — записать координаты и при смене имени **переименовать** выбранный регион; **«Добавить»** — только новый регион (для выбранной в дереве камеры). Отдельный регистр в `registers/schemas` и финальный пакет в data_schema для бэкенда — **после согласования** (фаза 2).
- Причина: Один предсказуемый JSON-совместимый слой между GUI, YAML рецептов и будущим процессором.
- Отклонённые альтернативы: держать данные только в виджете без записи в регистр — хуже для рецептов; правка имён только в таблице — дублирование с полем имени.

**Уточнение (2026-03-25, UI — двойной выбор и правка):** Вертикальный порядок: **дерево «камера → регионы»** (**`StructuredTwoLevelTreeWidget`**, см. **ADR-095**) → кнопки «Добавить» / «Удалить» / «Сохранить» → **`QGroupBox`** «Параметры области (ROI)»: ComboBox списка регионов текущей камеры, поле имени, **`CroppedAreaControls`**. Источник истины по выбору — **`region_id`** (ключ в `regions`); его отражают выделение листа дерева, ComboBox регионов и слайдеры. Листья дерева **редактируемые**; изменения ячеек обрабатывает презентер (**`leaf_cell_changed`** / **`itemChanged`**), значения читаются через **`CroppedRegionsTreeAdapter.read_leaf_row`**. Переименование в дереве — те же правила конфликта имён, что и «Сохранить». Программное обновление дерева и ComboBox — с **`blockSignals`**, чтобы не зациклить выбор.

## ADR-095: `StructuredTwoLevelTreeWidget` — группа → строки в `frontend_module/widgets/tables`
- Дата: 2026-03-25
- Статус: принято
- Контекст: Плоская **`StructuredTableWidget`** не показывает уровень камеры вместе с регионами; в legacy **Sort_widget** (App) уже использовался **`QTreeWidget`** для вложенных списков.
- Решение: Во **`frontend_module`** добавлен **`StructuredTwoLevelTreeWidget`**: конфиг колонок как у **`StructuredTableWidget`**, данные **`set_data([(group_id, [row_dict, …]), …])`**, идентификатор листа через **`set_row_key`**, сигнал **`leaf_cell_changed(group_id, row_id, column_key, value)`**, **`get_selection()` → (group_id | None, leaf_id | None)`**, **`select_leaf` / `select_group`**. Прототип: **`CroppedRegionsTreeAdapter`** строит группы из **`regions_to_table_rows`** по списку id камер (**`camera_ids_union`**).
- Причина: Переиспользуемый компонент фреймворка; данные на границе — словари; без зависимости прототипа от legacy App.
- Отклонённые альтернативы: только правки в прототипе без виджета во фреймворке — дублирование для следующих экранов; **`QTreeView` + модель** — тяжелее для MVP.

## ADR-092: Постобработка — `ProcessorRegisters.post_processing_regions` и вкладка прототипа
- Дата: 2026-03-25
- Статус: принято
- Контекст: Legacy **`Post_processing_widget`** (App) управляет списком регионов просмотра по камере с флагами и углами **x1,y1,x2,y2**; нужен аналог в **`multiprocess_prototype`** без **DataManager**, в стиле **BaseWidget + MVP**.
- Решение: Поле **`post_processing_regions`** в **`ProcessorRegisters`**: **`camera_id` → список** (порядок строк = порядок в пайплайне), элемент — **`name`**, **`x1..y2`**, **`enabled`**, **`is_main`**, **`processing_enabled`**. Нормализация/снимок — **`post_processing_widget.params`**. UI: **`PostProcessingPanelWidget`**, **`TableWithToolbar`**, форма координат; кнопки «Показать» / «основной» — заглушки до связи с окном просмотра. Синхронизация **`register_sync`** для детектора по этому полю — не обязательна в фазе 1 (снимок для GUI/рецепта).
- Причина: Dict at Boundary; один регистр с **`crop_regions`**; отказ от App-специфичного **DataManager** в MVP.
- Отклонённые альтернативы: только дублировать данные в **crop_regions** — другая семантика (углы vs x,y,w,h).

## ADR-093: Вложенные payload processor — канон в `registers`, миграция снимков, мульти-камера
- Дата: 2026-03-25
- Статус: принято
- Контекст: Нормализация **`crop_regions`** / **`post_processing_regions`** жила только во frontend (`params.py`), а рецепты и **`model_validate_all`** должны принимать legacy YAML без расхождений; нужен единый канон для тестов и **PostProcessingRegionEntry**; отдельно — стратегия **словаря камер** vs плоский **`CameraRegisters`**.
- Решение:
  - Канонические функции и типы: **`registers/schemas/processing_tab/crop_regions_payload.py`**, **`post_processing_payload.py`** (`PostProcessingRegionEntry`), реэкспорт **`nested_payload.py`**; виджеты реэкспортируют из регистров.
  - **`ProcessorRegisters`**: `@model_validator(mode="before")` нормализует вложенные поля при **`model_validate`** / загрузке снимка.
  - **`registers/snapshot_migrate.py`**: **`migrate_register_recipe_snapshot`** вызывается из **`RecipeManager.load_recipe_to_registers`** перед **`model_validate_all`** (явный слой I/O).
  - **Мульти-камера (id → параметры):** до отдельного ADR и согласования с бэкендом оставляем плоский **`CameraRegisters`**; при необходимости — поле **`cameras: dict[str, CameraDeviceParams]`** (внутренний Pydantic-модель) или отдельный регистр.
- Причина: один источник правды для YAML, GUI и валидации; Dict at Boundary сохраняется.
- Отклонённые альтернативы: только нормализовать в виджете — рецепты без миграции ломают **`validate_all`**; дублировать логику в **`RecipeManager`** без выделенного модуля — хуже сопровождение.

## ADR-094: Логические камеры в UI — `logical_camera_ids`, сидирование, `subscribe_all`
- Дата: 2026-03-25
- Статус: принято
- Контекст: При переключении Simulator/Webcam/Hikvision список камер в ROI/постобработке должен пополняться стабильным id; панели должны обновляться без ручного переключения вкладки; **`register_update`** на процессор для чисто GUI-списка не нужен.
- Решение:
  - Поле **`ProcessorRegisters.logical_camera_ids`**: `list[str]`, **`FieldMeta.routing`** с **`process_targets: []`**; в **`registers_module.RegistersManager._resolve_dispatch_targets`** явная ветка: пустой список целей → не слать **`register_update`** в процессы (перекрывает **`register_dispatch`** класса).
  - **`frontend/coordinators/logical_cameras.py`**: **`compute_logical_camera_id`**, **`ensure_logical_camera_and_seed_roi`** — вызов из **`CameraTabPresenter`** после записи **`camera_type`**; сидирование **`crop_regions`** (регион **`full`**) и ключа в **`post_processing_regions`**.
  - Презентеры ROI/постобработки: **`camera_ids_union`** включает **`logical_camera_ids`** из регистра.
  - **`CroppedRegionsPanelWidget`** / **`PostProcessingPanelWidget`**: **`subscribe_all`** → отложенная **`load_from_register`**; **`closeEvent`** → **`unsubscribe_all`**.
- Причина: один источник для ComboBox и рецепта; синхронизация панелей без дублирования опроса.
- Отклонённые альтернативы: только ключи **`crop_regions`** без списка — пустые камеры не видны в UI до первого ROI; слать GUI-список в процессор «на всякий случай» — шум.

## ADR-085: Сжатие документации refactored — один актуальный контур
- Дата: 2026-03-24
- Статус: принято
- Контекст: Накопились дубли (эссе, философия, overview), черновики wishlist/глобального плана, папка `docs/archived/` с разовыми отчётами и мета-файл оценки документации; поддерживать синхронно было дорого.
- Решение: Оставить операционный набор: `docs/FRAMEWORK_OVERVIEW.md`, `docs/ARCHITECTURE_REFERENCE.md`, `docs/ROUTING_GLOSSARY.md`, `docs/ARCHITECTURE_MODULE_CATALOG.md`, `docs/FRONTEND_COMMAND_LAUNCHER_ROADMAP.md`, `docs/MODULE_README_TEMPLATE.md`, плюс `README.md`, `DOCUMENTATION_INDEX.md`, `DECISIONS.md`, `PROBLEMS.md`, `MODULES_STATUS.md` и README/STATUS/docs внутри модулей. Удалены: `docs/archived/`, `docs/archive/CLEANUP_SUMMARY.md`, `DOCUMENTATION_SCORE.md`, `docs/ARCHITECTURE_ESSAY.md`, `docs/ARCHITECTURE_PHILOSOPHY.md`, `docs/FRAMEWORK_VISION_AND_WISHLIST.md`, `docs/FRAMEWORK_IDEAL_GLOBAL_PLAN.md`.
- Причина: Один источник правды для онбординга и агентов; меньше расхождений; архивные отчёты не нужны для работы с кодом.
- Отклонённые альтернативы: «оставить всё, пометить устаревшим» — шум; перенос архива в git без удаления — дубликаты в истории git сохраняются при необходимости.

---

## ADR-088: Оболочки вкладок (`*_tab`) — единый каталог `widgets/tabs_setting/`
- Дата: 2026-03-25
- Статус: принято
- Контекст: Пакеты `camera_tab`, `recipes_tab`, `settings_tab`, `processing_tab`, `cropped_regions_tab` лежали рядом с фиче-виджетами (`hikvision_widget`, `*_widget`), что усложняло навигацию.
- Решение: Все тонкие оболочки вкладок перенесены в **`multiprocess_prototype/frontend/widgets/tabs_setting/<имя>/`** рядом с **`TabItemConfig`** / **`TabsConfig`**. Фиче-виджеты остаются на уровне **`widgets/`**. Импорт: **`multiprocess_prototype.frontend.widgets.tabs_setting.<tab>`** (или реэкспорт из **`widgets`** / **`tabs_setting`**).
- Причина: Один визуальный контур «настройки полосы табов + сами вкладки»; меньше путаницы с переиспользуемыми панелями.
- Отклонённые альтернативы: оставить вкладки соседями `hikvision_widget` — прежняя структура; тонкие шимы на старых путях — отказались для простоты.

---

## ADR-089: `numeric_bind_or_lineedit` — общий fallback NumericControl vs QLineEdit
- Дата: 2026-03-25
- Статус: принято
- Контекст: В `HikvisionWidget` дублировалась ветка «есть RegistersManager → NumericControl / нет → QLineEdit»; другие фиче-виджеты могли скопировать тот же паттерн.
- Решение: Модуль **`frontend_module/widgets/tabs/numeric_bind_or_lineedit.py`**, функция **`append_spinbox_numeric_or_line_fallback`** — вход `RegisterBindingContext`, имя регистра, спецификации строк, подписи и placeholder’ы; заполняет `QVBoxLayout` и возвращает `List[Optional[QLineEdit]]` (параллельно строкам). `HikvisionWidget._build_params_group` переведён на этот API.
- Причина: один способ собрать параметры без копипасты; презентер по-прежнему читает значения через существующие утилиты (`line_params`).
- Отклонённые альтернативы: оставить только в прототипе (`widgets/common`) — меньше переиспользования между приложениями; дублировать в каждом виджете — отвергнуто.

---

## ADR-090: `frontend/coordinators`, границы виджет / Presenter / `managers`, accessors контекста
- Дата: 2026-03-25
- Статус: принято
- Контекст: Требовалось зафиксировать слои (тонкий виджет, MVP-презентер, доменные менеджеры), убрать дублирование парсинга номера слота рецепта и повтор `config.get(...)` во фабрике вкладок; не смешивать «оркестрацию UI» с `RecipeManager` в одном пакете `managers/`.
- Решение: Раздел описан в **`multiprocess_prototype/docs/FRONTEND_MAP.md`** и **`frontend/widgets/README.md`**. Пакет **`multiprocess_prototype/frontend/coordinators/`** — переиспользуемые чистые хелперы (например **`parse_clamped_recipe_slot_text`**), не YAML и не `AccessContext`. **`FrontendAppContext`** дополнен методами **`get_recipes_tab_ui`**, **`get_settings_tab_ui`**, **`get_cropped_regions_tab_ui`**, **`get_camera_tab_ui`**, **`get_recipe_access`**, **`get_processing_tab_ui`**. **`RegisterRecipePresenter`** вызывает методы **`RecipeManagerProtocol`** напрямую (без **`hasattr`**-веток).
- Причина: Один смысл слова «менеджер» для домена; меньше копипасты; стабильная точка чтения секций конфига для **`tab_factory`**.
- Отклонённые альтернативы: перенос всей логики экранов в корень **`managers/`** — размывает домен; массовый перенос презентеров из виджетов без дублирования ответственности — отложено.

---

## ADR-086: Вкладка «Регионы обрезки» и `ProcessorRegisters.crop_regions` без пакета App
- Дата: 2026-03-25
- Статус: принято
- Контекст: Нужны именованные ROI для последующей вырезки на бэкенде; старый `App/UI/Widgets/Cropped_area_widget` не должен тянуться в multiprocess_prototype.
- Решение:
  - **`multiprocess_prototype/frontend/widgets/tabs_setting/cropped_regions_tab/`**: локальные **`CroppedAreaControls`** (те же ключи params, что у legacy-виджета) + **`CroppedRegionsTabWidget`** (список регионов, сохранение снимка).
  - Формат записи региона: **`{ "params": {...}, "rect": {x,y,width,height} }`**; `rect` выводится функцией **`params_to_rect`** (x=x_min, width=x_max−x_min, y=y_delta, height=height).
  - Регистр **`ProcessorRegisters.crop_regions`**: `dict` (имя региона → payload), маршрутизация на процесс **processor**; синхронизация через **`set_field_value`**.
- Причина: Dict at Boundary; один источник для GUI и boot; отвязка от устаревшего App.
- Отклонённые альтернативы: встраивать импорт `App.CroppedAreaWidget` — лишняя связность и пути импорта.

---

## ADR-087: Таблица регионов ROI — `StructuredTableWidget` и `CroppedRegionsTabUiConfig`
- Дата: 2026-03-25
- Статус: принято
- Контекст: Список регионов на `QListWidget` хуже обзора rect; на вкладке рецептов уже принят паттерн **`StructuredTableWidget`** + подписи из схемы.
- Решение:
  - **`CroppedRegionsTabWidget`**: колонки имя, x, y, width, height; **`regions_to_table_rows`** / **`rect_to_params`** для синхронизации с `params`.
  - **`CroppedRegionsTabUiConfig`** + ключ **`cropped_regions_tab`** в **`FrontendConfig.build_dict`**; фабрика вкладок передаёт `ui=config.get("cropped_regions_tab")`.
- Причина: Единообразие с `recipes_tab`, наглядность rect, двусторонняя связь таблицы и слайдеров.
- Отклонённые альтернативы: только список имён без rect в таблице — меньше пользы для оператора.

**Уточнение (2026-03-25):** панель **`CroppedAreaControls`** переведена на **`NumericControl` / `CheckboxControl`** + локальный **`RegistersManager`** с схемой **`CroppedRoiPanelRegisters`** (`FieldMeta` min/max); вид **slider** vs **spinbox** задаётся **`CroppedRegionsTabUiConfig.roi_numeric_views`**.

---

## ADR-084: `FrontendAppContext` — явный контекст вкладок без слияния слоёв
- Дата: 2026-03-24
- Статус: принято
- Контекст: Много аргументов у `create_tab_widget_factory`; нужна навигация для новых разработчиков и точка расширения без рефакторинга launcher/MainWindow в один класс.
- Решение:
  - **`multiprocess_prototype/frontend/app_context.py`**: dataclass **`FrontendAppContext`** (`config`, `registers_manager`, `camera_callbacks_map`, `camera_type`, `recipe_manager`, опционально `command_handler`, `extras`).
  - **`create_tab_widget_factory(ctx)`** принимает только контекст; **`FrontendLauncher`** собирает контекст после `RecipeManager` / `get_registers()` / колбэков камеры.
  - **`MainWindow`** без переданной фабрики строит контекст локально с `recipe_manager=None`.
  - Карта документации: **`docs/FRONTEND_MAP.md`** (поток `run_process_attached_frontend`, мост, команды, стратегия тестов).
- Причина: Меньше прокидывания параметров; слои (лаунчер, `FrontendManager`, MVP) сохраняются.
- Отклонённые альтернативы: объединить launcher и фабрику вкладок в один модуль — хуже читаемость границ с фреймворком.

---

## ADR-083: Опциональная телеметрия UI — `ui_diagnostics`, одна подписка на шины
- Дата: 2026-03-24
- Статус: принято
- Контекст: Нужна наблюдаемость кликов/событий виджетов и основа для headless-проверок без дублирования бизнес-связей; уже есть `WidgetSignalBus` / `emit_widget_event` (frontend_module).
- Решение:
  - **`multiprocess_prototype/frontend/diagnostics.py`**: `attach_ui_diagnostics(main_window, config)` — при `ui_diagnostics.enabled` подписывается на `tab_widget.signal_bus`, на все вложенные `signal_bus` у `QWidget` внутри вкладок (дедуп по `id(bus)`), на `header.action_triggered` как `header.action_triggered`.
  - **Конфиг:** поле **`GuiConfig.ui_diagnostics`** (dict) → `FrontendConfig.build_dict` → ключ **`ui_diagnostics`**; опционально **`INSPECTOR_UI_DIAGNOSTICS=1|true|yes`** включает телеметрию с дефолтными параметрами, если в конфиге не задано `enabled: True`.
  - **Параметры:** `log_level`, `logger_name`, `include_prefixes`, `buffer_max` (кольцевой буфер в `UiDiagnosticsSession.recent_events` для отладки/тестов).
  - **`FrontendLauncher`**: после создания `MainWindow` вызывает `attach_ui_diagnostics`, сохраняет сессию в `process._ui_diagnostics`.
- Причина: один канал событий, без параллельных «трасс»; выключается по умолчанию; тесты: `tests/support/gui_env.py` (`gui_display_available`), `tests/test_ui_diagnostics.py`.
- Отклонённые альтернативы: отдельная параллельная шина событий — дублирование; обязательная телеметрия в проде — шум и накладные расходы.

---

## ADR-082: Вкладки «Рецепты» и «Настройки» — разделение register vs app-рецепт, общая панель
- Дата: 2026-03-24
- Статус: принято
- Контекст: Две таблицы на одной вкладке «Рецепты» смешивали параметры алгоритма (регистры) и пресеты UI (`SchemaBase`); нужен единый код слота/`RecipeManager`/таблицы без дублирования.
- Решение:
  - Панели рецептов на **`BaseWidget` + MVP**: **`RegisterRecipePanelWidget`**, **`AppRecipePanelWidget`**; публичные имена **`RegisterRecipePanel`** / **`AppRecipePanel`** — реэкспорт ([`recipe_slot_table_panel.py`](../../multiprocess_prototype/frontend/widgets/tabs_setting/recipes_tab/recipe_slot_table_panel.py)). Исторически общая база **`RecipeSlotTablePanel`** заменена на этот каркас (2026-03).
  - Имена каталогов (2026-03, уточнено 2026-03-25): оболочки **`tabs_setting/recipes_tab/`**, **`tabs_setting/recipes_settings_tab/`**; фичи **`recipes_widget/`**, **`settings_recipe_widget/`** (в т.ч. **`settings_recipe_widget/schemas.py`**: `RecipesTabConfig`, `default_tab_item` — прежнее имя пакета `recipes_settings_widget` не используется). Ключи секций в **`FrontendConfig`** — по-прежнему **`recipes_tab`** / **`settings_tab`**.
  - **`RecipesTabWidget`** содержит только **`RegisterRecipePanel`**.
  - **`SettingsTabWidget`** — существующие контролы + **`AppRecipePanel`**; в **`create_tab_widget_factory`** в настройки передаются **`recipe_manager`**, **`recipe_access`**, **`recipes_tab`**, опционально **`processing_tab_ui`** (как для дефолтов агрегата app).
  - Один **`RecipeManager`** на сессию (лаунчер), без второго экземпляра.
- Причина: UX: алгоритм отдельно от пресетов интерфейса; DRY для логики YAML/слота/таблицы.
- Отклонённые альтернативы: два полностью независимых копипаста виджета — отклонено в пользу наследования от общей панели.

---

## ADR-081: Двойные рецепты — register_recipes + app_recipes, AccessContext
- Дата: 2026-03-24
- Статус: принято
- Контекст: Нужны независимые слоты для параметров алгоритма (регистры) и для схем приложения (UI / ProcessingTabUiConfig и т.д.); гибкий доступ (в т.ч. обход readonly для dev).
- Решение:
  - **YAML** (`RecipeManager`): ключи `version`, `current_register_recipe`, `current_app_recipe`, `register_recipes`, `app_recipes`; при загрузке старый формат `current_recipe` + `recipes` маппится в новые поля.
  - **Регистры**: по-прежнему снимок `model_dump_all()` (ADR-080).
  - **App**: снимок `{ "RecipesTabConfig": {...}, "ProcessingTabUiConfig": {...} }`; хелперы в `managers/app_recipe_aggregate.py` (ленивые импорты схем, чтобы не тянуть `widgets/__init__` при тестах менеджера).
  - **UI**: таблица регистров — `RecipesTabWidget` (`RegisterRecipePanel`); таблица app — `SettingsTabWidget` (`AppRecipePanel`); см. **ADR-082**. **`AccessContext`** (`level`, `bypass_readonly`, `show_hidden`) и ключ **`recipe_access`** в `FrontendConfig.build_dict`.
  - **`FrontendLauncher`**: `ensure_app_slot_from_snapshot("0", …)` рядом с `ensure_slot_from_registers` (см. **ADR-098** для раздельных YAML и слота **`"0"`**).
  - **`GuiConfig`**: поля **`recipes_path`**, **`recipe_access`** — в `proc_dict["config"]` → `GuiProcess.get_config("config")` → `FrontendLauncher` / `build_frontend_config` (Dict at Boundary).
- Причина: два домена данных без смешения в одном слоте; единый файл рецептов; согласованность с FieldMeta и табличным редактированием.
- Отклонённые альтернативы: один стол с колонкой «тип» — хуже UX; отдельные файлы без запроса — отложено.

---

## ADR-080: Рецепты в multiprocess_prototype — снимок = model_dump_all
- Дата: 2026-03-24
- Статус: принято
- Контекст: Нужна вкладка «Рецепты» и хранение сортов без дублирования полей вне регистров.
- Решение:
  - **`RecipeManager`** (`multiprocess_prototype/managers/recipe_manager.py`): YAML со словарём `recipes[slot_id]`, значение — **структурированный снимок как `RegistersManager.model_dump_all()`**; загрузка через `model_validate_all`, сохранение через `model_dump_all`.
  - **`RecipesTabWidget`**: таблица строк строится обходом регистров (`build_recipe_rows`); **`StructuredTableWidget`** поддерживает переопределение редактируемости строки через **`_value_editable`** в данных строки.
  - **Конфиг**: `recipes_tab` + опциональный **`recipes_path`** в `FrontendConfig.build_dict`; фабрика вкладок получает **`RecipeManager`** из `FrontendLauncher`.
- Причина: Один источник истины — схемы регистров; снимок совместим с валидацией и маршрутизацией `set_field_value`.
- Отклонённые альтернативы: плоский YAML с `ConverterManager` как в legacy App — отложено до необходимости импорта старых файлов.

---

## ADR-076: BaseWidget — MVP-виджет с опциональным Model
- Дата: 2026-03-24
- Статус: принято
- Контекст: MvpTabBase не имел слоя Model; HikvisionWidget имел размытые границы View/Presenter, binder+params разбросан. Нужен единый шаблон для виджетов (в т.ч. контент вкладок) с Model + пассивным View.
- Решение:
  - **`widgets/base_widget/`**: **BaseWidget(BaseTab)** — жизненный цикл: `_coerce_callbacks`, `_coerce_ui` → `_create_model()` → `_init_ui()` → `_create_presenter(model)` → `_connect_signals()` → `_on_presenter_ready()`. Model опциональна (`_create_model` возвращает None по умолчанию).
  - **HikvisionWidget**: переведён на BaseWidget; HikvisionModel (регистры, колбэки); пассивный View (Presenter не вызывает get_* у View, данные передаются через слоты при клике); binder/params_section влиты в `_init_ui`; `register_ops` удалён, логика в model.
- Причина: Чёткое разделение Model/View/Presenter; переиспользуемый шаблон; пассивный View упрощает тестирование.
- Отклонённые альтернативы: расширить MvpTabBase опциональным _create_model — BaseWidget отдельно, чтобы не трогать MvpTabBase; позже можно слить.

---

## ADR-077: components vs widgets, flatten контролов, MvpTabBase = BaseWidget
- Дата: 2026-03-24
- Статус: принято
- Контекст: Папка `components/` смешивала примитивы (`control_v2`) и составной UI (вкладки, шапка); shim `controls/` и сегмент `control_v2` в пути импорта лишние; `MvpTabBase` и `BaseWidget` дублировали жизненный цикл.
- Решение:
  - **`frontend_module.components`**: только контролы; содержимое бывшего `control_v2/` поднято на уровень `components/` (`base`, `checkbox`, `examples`, …); каталог `control_v2/` и пакет `controls/` удалены.
  - **`frontend_module.widgets`**: `tabs`, `base_widget`, `header` (в т.ч. стили кнопок шапки — `header/button_style.py`), `keyboard`, `tables`, `performance_monitor`, `image_panel`; реэкспорт из `widgets/__init__.py`.
  - **`MvpTabBase`**: наследует **`BaseWidget[Any]`**; по умолчанию `_connect_signals` — no-op (как раньше вкладки без отдельного шага connect). Подклассы реализуют `_create_presenter(model)`; `BaseWidget` импортирует `BaseTab` из `tabs.tab_widget`, чтобы избежать циклического импорта с `tabs/__init__.py`.
  - **SimWebcamWidget**: переведён на `BaseWidget` + `SimWebcamModel`; binder принимает `fps_changed`, а не `presenter`.
- Причина: Ясная граница примитив/состав; короткие импорты; единая точка расширения MVP.
- Отклонённые альтернативы: оставить `control_v2` в пути — лишний уровень; deprecated-реэкспорт из старых путей — отказ в пользу массового обновления импортов.

---

## ADR-078: Стили кнопок шапки — `widgets/header/button_style`, удалён пакет `widgets/base`
- Дата: 2026-03-24
- Статус: принято
- Контекст: Пакет `widgets/base` содержал только `button_style.py` (фабрика кнопок header) и путался с `widgets/base_widget` (MVP-база).
- Решение: **`button_style.py`** перенесён в **`widgets/header/`**; пакет **`widgets/base`** удалён. **`ButtonHeader`** / **`create_header_button`** реэкспортируются из **`widgets/header/__init__.py`** и по-прежнему из **`frontend_module.widgets`** (`ButtonHeader`).
- Причина: Один смысловой домен (шапка) — один пакет; имя `base` освобождено от коллизии с `base_widget`.
- Отклонённые альтернативы: оставить `widgets/base` с переименованием только файла — лишний уровень вложенности.

---

## ADR-079: Граница `components` / `widgets`; `WidgetSignalBus`; TabWidget и клавиатуры без BaseWidget
- Дата: 2026-03-24
- Статус: принято
- Контекст: Обсуждался перенос `tabs` и `tables` в `components` и унификация с `BaseWidget`. `components` по ADR-077 — контролы полей; `tabs` — инфраструктура главного окна и MVP-мосты; `BaseWidget` импортирует `BaseTab` из `tabs`. Таблица `StructuredTableWidget` наследует `QTableWidget` — не стыкуется с наследованием от `BaseWidget` без композиции.
- Решение:
  - **`tabs` и `tables` остаются в `frontend_module.widgets`**; не смешивать с примитивами `components` без отдельного ADR и миграции импортов.
  - **`WidgetSignalBus`** вынесен в **`widgets/widget_signal_bus.py`**, чтобы **`TabWidget`** и виджеты без `BaseWidget` подключали ту же шину без циклического импорта с `base_widget.py`.
  - **`TabWidget`**: не наследует `BaseWidget`; добавлены `signal_bus` и `emit_widget_event`; события `tab_widget.current_changed`, `tab_widget.panel_visibility_changed`.
  - **`VirtualKeyboard` / `VirtualKeyboardMini`**: `signal_bus` + `emit_widget_event`; события `keyboard.full.shown` / `keyboard.full.closed`, `keyboard.mini.enter` / `keyboard.mini.closed`.
  - **`HeaderWidget` → BaseWidget** и **`TableWithToolbar` → BaseWidget** — отложены до отдельной задачи с регрессионными тестами UI.
- Причина: Единый канал телеметрии без навязывания MVP всем виджетам; ясная граница каталогов; отсутствие циклов импорта.
- Отклонённые альтернативы: перенос `tabs` в `components` — ломает смысл ADR-077; наследование `TabWidget(BaseWidget)` — смешение ролей хоста и контента.

---

## ADR-075: MvpTabBase, create_registers_placeholder, callbacks_base, recipes schemas
- Дата: 2026-03-23
- Статус: принято
- Контекст: Упрощение реализации MVP-вкладок; дублирование placeholder и callbacks from_dict/to_dict; неконсистентное именование config vs schemas в recipes_tab.
- Решение:
  - **`tabs/mvp_facade.py`**: **MvpTabBase** — фасад для MVP-вкладок; дочерний класс реализует `_coerce_callbacks`, `_coerce_ui`, `_init_ui`, `_create_presenter`, `_on_presenter_ready`; убирает дублирование flow в camera_tab.
  - **`tabs/placeholder_utils.py`**: **create_registers_placeholder(tab_name)** — единая заглушка для вкладок без RegistersManager.
  - **`tabs/callbacks_base.py`**: **tab_callbacks_from_dict** / **tab_callbacks_to_dict** (опционально без списка полей для `@dataclass`), **callback_no_args** — единый модуль колбэков вкладок.
  - **`tabs/MVP_TEMPLATE.md`**: шаблон MVP-вкладки (копировать и заполнять).
  - **camera_tab**: наследует MvpTabBase; callbacks используют callbacks_base.
  - **processing_tab, settings_tab**: используют create_registers_placeholder.
  - **recipes_tab**: config.py → schemas.py (единообразие с другими вкладками).
  - **processing_tab**: удалён неиспользуемый параметр callbacks; _processing_callbacks удалён из launcher.
- Причина: Легче добавлять новые MVP-вкладки; меньше копипаста; единый стиль.
- Отклонённые альтернативы: оставить camera_tab на BaseTab — MvpTabBase даёт явный контракт и сокращает boilerplate.

---

## ADR-071: IRegistersManagerGui — единый протокол регистров для GUI
- Дата: 2026-03-23
- Статус: принято
- Контекст: В camera_tab, контролах (исторически `control_v2`), register_ops использовались `Any` и `hasattr` для менеджера регистров. Нужен был явный контракт регистров для GUI до внедрения презентера (см. ADR-072, `frontend_module/widgets/tabs/TAB_STRUCTURE.md`).
- Решение:
  - **`frontend_module/interfaces.py`**: введён **`IRegistersManagerGui`** с методами `set_field_value`, `get_register`, `get_field_metadata`.
  - **`components/base/interfaces.py`** (путь см. **ADR-077**): **`RegistersManagerLike`** = алиас `IRegistersManagerGui`; единый тип для RegisterAdapter и NumericControl.
  - Приложение (register_ops, фабрики вкладок) типизирует `registers_manager: Optional[IRegistersManagerGui]`.
- Причина: Убрать `Any`/`hasattr`; улучшить статическую проверку и автодополнение.
- Отклонённые альтернативы: оставить RegistersManagerLike отдельно — дублирование контракта; добавить set_field_value в IRegistersManager — registers_module IRegistersManager не включает запись, разделение чтение/запись оправдано.

---

## ADR-072: Паттерн вкладок — MVP, coerce_schema_config, callback_no_args, TAB_STRUCTURE
- Дата: 2026-03-23
- Статус: принято
- Контекст: camera_tab реализовал MVP (View + Presenter + Callbacks), секции с RegisterBindingContext, локальные ui_coerce и _invoke. Требовался генеральный рефакторинг: вынос универсальных паттернов во фреймворк, единая структура для всех вкладок.
- Решение:
  - **`tabs/callbacks_base.py`**: `callback_no_args(fn)` — обёртка для Qt clicked(bool); вместе с `tab_callbacks_*` в одном модуле, экспорт в `tabs/__init__.py`.
  - **`tabs/TAB_STRUCTURE.md`**: шаблон структуры вкладки; когда MVP vs простой виджет; паттерн Callbacks dataclass; RegisterBindingContext, coerce_schema_config, callback_no_args; ссылка на camera_tab как эталон.
  - **camera_tab**: `coerce_camera_ui` → `coerce_schema_config(ui, CameraTabUiConfig)`; `_invoke(fn, no_args=True)` → `callback_no_args`; docstrings.
  - **processing_tab**: `_coerce_processing_ui` удалён, используется `coerce_schema_config(ui, ProcessingTabUiConfig)`.
  - **tabs/README.md**: создан, ссылка на TAB_STRUCTURE.
- Причина: DRY; единые рекомендации для новых вкладок; camera_tab остаётся эталоном без дублирования логики.
- Отклонённые альтернативы: отдельный coerce_ui_config в tabs — достаточно coerce_schema_config из core. TabPresenterBase — реализовано в ADR-073.

---

## ADR-073: TabPresenterBase, TabViewProtocol; processing_tab и RegisterBindingContext
- Дата: 2026-03-23
- Статус: принято
- Контекст: После ADR-072 оставались рекомендации: выровнять processing_tab с `IRegistersManagerGui` / `RegisterBindingContext` вместо `hasattr(rm, "set_field_value")`; ввести лёгкий каркас MVP во фреймворке; тесты и реэкспорт из `components`.
- Решение:
  - **`tabs/mvp_pattern.py`**: `TabViewProtocol` (маркер), `TabPresenterBase[TView, TUi]` с `_view`, `_rm`, `_ui`.
  - **`CameraTabPresenter`**: наследует `TabPresenterBase`; `CameraTabView` наследует `TabViewProtocol, Protocol`.
  - **`ProcessingTabWidget`**: `registers_manager: Optional[IRegistersManagerGui]`; в `_init_ui` — `RegisterBindingContext`, ветка заглушки при `not binding.can_bind`.
  - **`frontend_module.widgets`** (с ADR-077; ранее barrel в `components`): реэкспорт `RegisterBindingContext`, `TabPresenterBase`, `TabViewProtocol`, `callback_no_args` вместе с `BaseTab` / `TabWidget`.
  - **`tests/test_tabs_callbacks.py`**: `callback_no_args`, dataclass ↔ dict, явный `field_names`.
- Причина: Единый язык вкладок с регистрами; явный каркас для новых MVP-вкладок без дублирования полей презентера.
- Отклонённые альтернативы: только документация без кода — слабее для статической типизации и онбординга.

---

## ADR-074: Единый стиль всех вкладок — IRegistersManagerGui, RegisterBindingContext, coerce
- Дата: 2026-03-23
- Статус: принято
- Контекст: settings_tab и recipes_tab использовали `Any` для rm, `hasattr` или inline `model_validate`; API отличались от camera_tab и processing_tab.
- Решение:
  - **settings_tab**: `registers_manager: Optional[IRegistersManagerGui]`; `ui: Optional[Union[SettingsTabConfig, dict]]` вместо `controls_config` + `group_title`; `RegisterBindingContext`; заглушка при `not binding.can_bind`; `coerce_schema_config`.
  - **recipes_tab**: `registers_manager: Optional[IRegistersManagerGui]`; `ui` через `coerce_schema_config`; docstrings.
  - **tab_factory**: settings — `ui=config.get("settings_tab")`.
  - Все вкладки: единые docstrings в `__init__.py`, `registers_manager` property.
- Причина: Один контракт для всех вкладок; удобство фреймворка (TAB_STRUCTURE) для новых фич.
- Отклонённые альтернативы: оставить раздельные API — усложняет онбординг.

---

## ADR-070: primitives и common в control_v2, удаление controls v1
- *Примечание (2026-03-24): пути `control_v2/` в тексте ниже — исторические; актуально — flatten в `frontend_module.components` (**ADR-077**).*
- Дата: 2026-03-23
- Статус: принято
- Контекст: В `components/controls/` были legacy v1 (slider, checkbox на BaseConfigurableWidget), primitives и common. Архитектура v2 выиграла; требуется консолидация в control_v2.
- Решение:
  - **`control_v2/common/`**: typography, sizes, field_sync, legacy_sync, slider_styles — перенесены из `controls/common/` и `controls/slider/styles.py`.
  - **`control_v2/primitives/`**: control_label, numeric_line_edit, styled_slider, value_bridge — переписаны по образцу v2 с импортом из `control_v2.common`.
  - **`LegacySyncTrait`**: импортирует из `control_v2.common.legacy_sync` и `control_v2.common.field_sync`.
  - **`SliderValueView`**: использует `common/slider_styles` вместо локальных констант.
  - **`components/controls/`**: только реэкспорт из control_v2; v1 (slider, checkbox, primitives, common) удалены.
  - **Миграция**: settings_tab, camera_tab, processing_tab, default_factories переведены на v2 API (NumericControl.create, CheckboxControl.create, BindingConfig).
- Причина: Единая точка для примитивов и общих утилит; устранение legacy-кода.
- Отклонённые альтернативы: оставить primitives/common в controls — смешение с удаляемым v1.

---

## ADR-067: Controls v2 — `ControlHooks`, отдельные `SliderPresenter` / `SpinBoxPresenter`
- Дата: 2026-03-23
- Статус: принято
- Контекст: Ошибки записи показывались только во view; не было единой точки для логов/ErrorManager/статистики. Фасады слайдера/спинбокса проксировали `NumericControl`, смешивая API с «общим числом».
- Решение:
  - **`base/control_hooks.py`**: `ControlHooks` (`on_write_rejected`, `on_write_committed`, `on_access_denied`), события записи и **`ControlAccessDeniedEvent`** при попытке изменить значение без `can_modify()`, хелперы `emit_*`. Фреймворк не импортирует `logger_module` / `error_module`; приложение передаёт колбэки в `*.create(..., hooks=...)` или пробрасывает в `pyqtSignal`.
  - **`CheckboxPresenter` / `NumericPresenter`**: вызов хуков при неуспехе/успехе записи и при отказе по правам (в дополнение к `show_error` при ошибке регистра).
  - **`SliderPresenter` / `SpinBoxPresenter`**: наследники `NumericPresenter` с `control_kind` `slider` / `spinbox`; **`SliderControl` / `SpinBoxControl`** собирают presenter + `create_labeled_numeric_view` без прокси через `NumericControl` (импорт `create_labeled_numeric_view` — внутри `create()`, чтобы не зациклить `group.view` ↔ `spinbox` пакет).
  - Составные фасады и **`ControlFactory`** принимают `hooks` и пробрасывают в дочерние `create`.
- Причина: Слабая связность с инфраструктурой логов; явный тип presenter для слайдера/спинбокса и события с `control_kind` упрощают подписку внешних менеджеров.
- Отклонённые альтернативы: прямой импорт `LoggerManager` из `frontend_module` — нарушение границ и усложнение тестов.
- Последующая работа (выполнено, см. **ADR-068**): фабрика вынесена из `group/view.py`.

---

## ADR-068: Controls v2 — фабрика `create_labeled_numeric_view` в `group/labeled_numeric_factory.py`
- Дата: 2026-03-23
- Статус: принято
- Контекст: `group/view.py` импортировал `SpinBoxValueView` на уровне модуля; граф `group` ↔ `spinbox` требовал отложенных импортов в фасадах (ADR-067).
- Решение: модуль **`group/labeled_numeric_factory.py`** — единственное место, где собираются `LabelView` + `SliderValueView` / `SpinBoxValueView` (ленивый импорт value-виджетов внутри фабрики). **`LabeledNumericGroupView`** остаётся в `view.py` без импортов `slider`/`spinbox`. Фасады `slider`/`spinbox`/`numeric` импортируют фабрику на уровне модуля.
- Причина: Однонаправленный граф: примитивы → `view` → `factory` → `slider.view` / `spinbox.view` только при вызове фабрики.
- Отклонённые альтернативы: оставить фабрику в `view.py` с ленивым импортом спинбокса — уже лучше прежнего top-level, но смешение виджета и сборки в одном файле.

---

## ADR-069: Пакет `control_v2` вне `components/controls`, примеры в `control_v2/examples`
- *Примечание (2026-03-24): канонические пути без `control_v2/` и без shims `controls/` — **ADR-077**; текст ниже сохранён как история.*
- Дата: 2026-03-23
- Статус: принято
- Контекст: Код v2 жил в `components/controls/v2`, а учебные схемы — в `components/controls/example_with_data_schema`; пути длинные, смешение с legacy `controls` (v1) и дублирование «v2» в URL импорта.
- Решение:
  - Канонический пакет: **`frontend_module/components/control_v2/`** (импорт `frontend_module.components.control_v2`).
  - Учебный код перенесён в **`control_v2/examples/`** с прежней структурой «папка на сценарий» (`checkbox/`, `slider/`, …).
  - **`components/controls/v2`** и **`components/controls/example_with_data_schema`** оставлены как **тонкие shims** (`from …control_v2… import *`) для обратной совместимости.
  - Документация: `control_v2/README.md`, `control_v2/ARCHITECTURE.md`; `controls/__init__.py` тянет v2 API из `control_v2`.
- Причина: Явная граница между legacy-контролами и слоистой архитектурой; проще масштабировать новые компоненты и находить примеры рядом с кодом.
- Отклонённые альтернативы: только смена импортов без физического переноса — не улучшает навигацию в репозитории.

---

## ADR-066: `example_with_data_schema` — учебный checkbox с двумя SchemaBase
- Дата: 2026-03-23
- Статус: принято (пакет перенесён: см. **ADR-069**; примеры сейчас в `components/examples/`, **ADR-077**)
- Контекст: Нужен наглядный пример рядом с контролами: отдельные схемы для UI-строк и для полей регистра без дублирования смысла в dataclass-конфиге v2.
- Решение:
  - Пакет из **трёх модулей**: `schemas.py` (две SchemaBase; `BINDING_REGISTER` / `BINDING_FIELD` как `ClassVar` на классе регистра), `adapter.py` (импорт только схем), `__init__.py`.
  - **CheckboxPresenter**: непустой `CheckboxViewConfig.tooltip` перекрывает описание из метаданных регистра.
  - Шаблон для slider/spinbox: тот же каркас `schemas` + короткий `adapter` к соответствующему фасаду v2.
- Причина: Документированный эталон для прототипа; v2 остаётся на dataclass-границе; кодовая база не раздувается.
- Отклонённые альтернативы: один объединённый SchemaBase для UI и значений — смешение ответственностей.

---

## ADR-065: Controls v2 `checkbox` — выравнивание с base
- Дата: 2026-03-23
- Статус: принято
- Контекст: Checkbox presenter использовал `Any` для view и адаптера; не было README/тестов на уровне пакета.
- Решение:
  - **`CheckboxPresenter`**: `IControlView[bool]`, `IFieldBinding`, `IRegisterPort`; `set_access_level` безопасен до `attach_view`.
  - **`CheckboxControl.create`**: `Optional[RegistersManagerLike]` вместо `Any`.
  - **`checkbox/README.md`** (Mermaid + отличия от numeric), ссылка из `v2/README.md`; публичный экспорт **`CheckboxView`**, **`CheckboxPresenter`**.
  - Тесты **`test_checkbox_v2.py`** (presenter + fake view, фасад smoke с QApplication).
- Причина: Единый стиль с `base` и numeric-веткой без дублирования новых протоколов (`IControlView[bool]` достаточно).
- Отклонённые альтернативы: отдельный `IBooleanView` — избыточно.

---

## ADR-064: Controls v2 `base` — порты presenter и документация со схемами
- Дата: 2026-03-23
- Статус: принято
- Контекст: Масштабирование на новые компоненты требует явных контрактов без раздувания кода; traits опирались на `Any`.
- Решение:
  - В `components/controls/v2/base/interfaces.py`: **`IFieldBinding`**, **`IRegisterPort`**, **`RegistersManagerLike`** (structural typing); эталонные реализации — `BindingConfig`, `RegisterAdapter`.
  - **`SyncTrait` / `SchemaTrait`** принимают эти порты вместо `Any`.
  - **`RegisterAdapter.__init__`**: `Optional[RegistersManagerLike]` (совместимость с Python 3.9 — `Optional`, не `X | Y` в сигнатурах адаптера).
  - **`base/README.md`**: принципы лаконичности, Mermaid (слои, sequence, композиция traits), таблица портов; в `v2/README.md` — ссылка на base.
- Причина: Одна точка расширения для новых контролов; статическая проверка и понятные диаграммы без новых пакетов.
- Отклонённые альтернативы: отдельный `ports.py` — дублировал бы роль `interfaces.py`; ABC вместо Protocol — лишнее наследование.

---

## ADR-063: Controls v2 — доработки по ревью (9/10)
- Дата: 2026-03-22
- Статус: принято
- Контекст: Ревью v2 выявило нарушения OCP, hasattr в Presenter, отсутствие legacy, setattr, dict в SchemaTrait.
- Решение:
  - **INumericView(IControlView[float])** — явный протокол с set_range, set_validator_int/float, get_legacy_element; Presenter без hasattr.
  - **Фасад OCP**: _create_numeric_view(view_type) — выбор SliderView/SpinBoxView по view_config.view_type.
  - **LegacySyncTrait** + **LegacySyncContext** — опциональная интеграция с ui_elements/controls/callback.
  - **Facade** возвращает **NumericControlResult(widget, presenter)** вместо setattr на view.
  - **LabelOverride** — типизированный config_override вместо dict в SchemaTrait.
  - **DebounceTrait** — один QTimer в __init__, schedule() перезапускает.
  - **CheckboxView.on_finished** — no-op (не дублировать on_changed).
  - **show_error** в IControlView — отображение ошибок валидации.
- Причина: Соответствие Open/Closed, явные контракты, совместимость с v1.
- Отклонённые альтернативы: BindingConfig на SchemaBase — оставлен dataclass для минимальной зависимости.

---

## ADR-062: Controls v2 — Traits + Presenter + View + Facade, принцип конструктора
- Дата: 2026-03-22
- Статус: принято
- Контекст: BaseConfigurableWidget «божественный», View/Presenter смешаны; нужна архитектура, позволяющая собирать новые контролы из переиспользуемых «кубиков».
- Решение:
  - **controls/v2/** — новая архитектура: **Traits** (SchemaTrait, SyncTrait, DebounceTrait, AccessTrait), **Presenters** (NumericPresenter, BooleanPresenter), **Views** (SliderView, CheckboxView), **Facade** (NumericControl.create(), BooleanControl.create()), **infrastructure** (RegisterAdapter, ValueTransformer, block_signals).
  - **Принцип конструктора**: все компоненты максимально универсальны; новый контрол = композиция traits + новый View при необходимости.
  - **BindingConfig** + **NumericViewConfig** / **CheckboxViewConfig** — разделение привязки и UI-опций.
  - v2 сосуществует с v1; постепенная миграция.
- Причина: Тестируемость (MockAdapter, MockView), расширяемость (SpinboxView — один файл), чёткое разделение ответственностей.
- Отклонённые альтернативы: рефакторинг v1 на месте — риск регрессий; единый миграционный путь — v2 в отдельной папке безопаснее.

---

## ADR-061: Controls — common/field_sync, common/sizes, legacy_sync, Base без exclude
- Дата: 2026-03-21
- Статус: принято
- Контекст: Дублирование field_sync в checkbox/slider; primitives зависят от slider/styles; BaseConfigurableWidget хардкодит exclude для SliderConfig; SliderControl перегружен legacy-логикой.
- Решение:
  - **`common/field_sync.py`** — единая `publish_control_value_to_observers` с опциональными ui_elements, controls, callback. Checkbox и Slider вызывают её; старые field_sync.py удалены.
  - **`common/sizes.py`** — VALUE_INPUT_WIDTH_PX, VALUE_INPUT_HEIGHT_PX. `numeric_line_edit` импортирует из common, не из slider.
  - **`slider/legacy_sync.py`** — `publish_legacy_ui_refs` вынесена из SliderControl; обновление ui_elements/controls при сборке UI.
  - **BaseConfigurableWidget._config_to_dict** — `model_dump()` без exclude; base не знает о полях конкретных конфигов.
  - Баг: `Tuple` → `tuple` в layout_builder; унификация импортов из primitives.
- Причина: Меньше дублирования, слабее coupling, primitives независимы от slider; схемы CheckboxConfig/SliderConfig остаются развёрнутыми для квартирования в приложении.
- Отклонённые альтернативы: BaseControlConfig для объединения полей схем — отложено, т.к. схемы будут расширяться в приложении.

---

## ADR-060: Controls — примитивы UI, стили, coerce_schema_config, узкий конструктор
- Дата: 2026-03-21
- Статус: принято
- Контекст: Дублирование `_coerce_config` между контролами; повтор полей схемы в `__init__` виджетов; монолитная сборка слайдера; инлайн QSS и «магические» шрифты/размеры.
- Решение:
  - **`coerce_schema_config`** в `frontend_module/core/schema_config.py` — нормализация `None` / `dict` / экземпляра для любого `SchemaBase`-конфига контрола.
  - **Конструктор** `SliderControl` / `CheckboxControl`: только `config`, `registers_manager`, `parent`; `register_name`, `field_name`, `access_level` задаются через `SliderConfig` / `CheckboxConfig` (без дублирования в подклассе).
  - **`components/controls/common/typography.py`** — шрифты метки и поля ввода; **`slider/styles.py`**, **`checkbox/styles.py`** — QSS и метрики layout.
  - **`components/controls/primitives/`** — `create_control_label`, `create_numeric_line_edit`, `create_styled_horizontal_slider` (без знания о регистре); **`value_bridge.py`** — документированная семантика и `schedule_slider_value_commit` (debounce записи после движения слайдера).
  - Уточнение (последующий рефакторинг): конфиги и примеры регистра — в подпакете **`slider/schema/`**, **`checkbox/schema/`**; у слайдера вынесены **`value_mapping.py`**, **`field_sync.py`**; у чекбокса — **`layout_builder.py`**, **`field_sync.py`**; документация — `controls/README.md`, `slider/README.md`, `checkbox/README.md`.
- Причина: Единообразие внешнего вида, проще добавлять новые контролы из тех же кирпичей; примитивы тестируются и читаются отдельно от привязки к регистру.
- Отклонённые альтернативы: второй слой произвольных `**kwargs` в конструктор виджета; публичные `pyqtSignal` на каждый шаг — отложено, пока нет внешних подписчиков.

## ADR-059: Рефакторинг SliderControl и CheckboxControl — config-based API, инкапсуляция операций со схемами
- Дата: 2026-03-21
- Статус: принято
- Контекст: SliderControl и CheckboxControl имели 12+ параметров в `__init__`; логика работы с регистрами и метаданными размазана по компонентам; неочевидный API для потомков.
- Решение:
  - **RegisterBinding**, **RegisterFieldMeta**, **ResolvedMeta** в `frontend_module/schemas/register_binding.py` — явная привязка к регистру и слияние метаданных.
  - **BaseConfigurableWidget** принимает `config`, инкапсулирует `_get_register_meta()`, `_read_value()`, `_write_value()`, `_resolve_meta()`; подклассы используют `self._resolved_meta`.
  - **SliderConfig**, **CheckboxConfig** (SchemaBase) в `components/controls/slider/`, `checkbox/` — UI-настройки (label, transfer_k, position и т.д.).
  - Папка-на-компонент: `slider/` (`widget.py`, `schema/`, `value_mapping.py`, …); `checkbox/` аналогично.
  - Конструктор контролов: `config`, `registers_manager`, `parent` (поля привязки — внутри config; уточнено в ADR-060).
  - Схема регистра (ProcessorRegisters, RendererRegisters) остаётся в прототипе; min/max/unit — из FieldMeta.
- Причина: Упрощение входа, единый слой для всех компонентов, расширяемость, соответствие Dict at Boundary (config как dict при границах).
- Отклонённые альтернативы: Обратная совместимость через **kwargs — отказались в пользу единовременного перехода.

---

## ADR-058: Outbound GUI-команда — IRouterLike + MessageAdapter + RoutedCommandSender
- Дата: 2026-03-20
- Статус: принято
- Контекст: В прототипе дублировалась цепочка `resolve_command_targets` → `MessageAdapter.command` → `send_message` в `GuiCommandHandler` и `GuiProcessMixin`; новым приложениям нужен один переиспользуемый отправитель без копипасты.
- Решение:
  - Класс **`RoutedCommandSender`** в `frontend_module/core/routed_command.py`: инъекция `router: IRouterLike`, `message_factory: SupportsCommandMessage`, `resolve_targets`, опционально `get_args_builder` (в `core/`, чтобы не подтягивать Qt через `application/`).
  - Протокол **`SupportsCommandMessage`** в `frontend_module/interfaces.py` — контракт фабрики COMMAND (например `MessageAdapter`), без импорта `message_module` в публичные реэкспорты.
  - Домен (`command_routing`, `GUI_COMMAND_CATALOG`) остаётся в приложении; на GUI-процессе один экземпляр sender (`GuiProcess._routed_command_sender`); handler и mixin только делегируют в него.
  - Каркас запуска UI: **`run_process_attached_frontend`** + **`FrontendLaunchHooks`** в `frontend_module/application/process_attached_frontend.py`; прототип заполняет хуки в `FrontendLauncher`.
- Причина: Один канонический путь «кнопка → очередь» (см. FRONTEND_COMMAND_LAUNCHER_ROADMAP.md §0.3), меньше расхождений handler/mixin, фреймворк остаётся без доменных команд.
- Отклонённые альтернативы: Второй путь через `command_module`/`dispatch_module` из GUI — только для сообщений уже внутри процесса (путь B); отдельный модуль ради sender — избыточно.

---

## ADR-057: Персистентность прототипа — пакет persistence и корень данных
- Дата: 2026-03-20
- Статус: принято
- Контекст: `prefs.py` и `.inspector_prefs.json` в корне пакета смешивали исходники с пользовательскими данными; при росте прототипа нужен единый каталог для prefs, кэшей и экспортов.
- Решение:
  - Пакет **`multiprocess_prototype/persistence/`**: `paths.py` (`INSPECTOR_DATA_DIR` или `~/.inspector_prototype`), `user_prefs.py` (`user_prefs.json`), `README.md` для расширения.
  - Однократная **миграция** из `multiprocess_prototype/.inspector_prefs.json` → `user_prefs.json` в корне данных; старый файл удаляется при успехе.
  - Импорты **`multiprocess_prototype.persistence`** (`get_camera_type`, `set_camera_type`, `get_data_root`).
- Причина: Масштабируемая структура, данные вне git по умолчанию, явный override для CI/установки.
- Отклонённые альтернативы: Только перенос JSON в подпапку репозитория — снова риск коммита пользовательских файлов.

---

## ADR-056: Прототип — единый GuiConfig, без алиасов GUI и лишних реэкспортов
- Дата: 2026-03-20
- Статус: принято
- Контекст: Дублировались схема `GuiConfigFrontend` и `GuiConfig`; в `frontend/__init__.py` экспортировался алиас `GuiProcessFrontend`; `backend/backends.py` и `registers/connection_map.py` (`DEFAULT_CONNECTION_MAP`) дублировали каноничные точки входа без потребителей.
- Решение:
  - **Один процессный конфиг GUI** — `@register_schema("GuiConfig")` в `backend/processes/gui/gui_config.py`, импорт для `main.py` из `multiprocess_prototype.backend.configs`.
  - **Класс процесса** — только `GuiProcess`; пакет `frontend` не реэкспортирует классы процесса.
  - **Захват камеры** — импорт только из `backend.modules.camera.backends` (или через `backend.modules.camera`).
  - **connection_map** — только через `factory.build_default_connection_map()` / `create_registers()`, без глобали `DEFAULT_CONNECTION_MAP`.
- Причина: Один публичный путь к типам, меньше «совместимостных» веток и расхождений документации с кодом.
- Отклонённые альтернативы: Оставить алиасы «на переходный период» — затягивает технический долг.

---

## ADR-055: Backend — граф импортов без циклов (configs ↔ processes ↔ modules)
- Дата: 2026-03-20
- Статус: принято
- Контекст: После разнесения `backend/processes/*`, `backend/modules/*` и `backend/configs` при `import backend` / `pytest` возникали циклы: `configs` → `ProcessorConfig` → `ProcessorProcess` → пакет `processes` (агрегирующий `__init__`) → `RendererProcess` → `modules.renderer` → `RendererConfig` → снова `RendererProcess` (частично инициализированный модуль). Аналогично `modules/__init__.py` и реэкспорт `CameraConfig` из `modules.camera` провоцировал цикл с `camera.process`.
- Решение:
  - **`backend/__init__.py`** — только `configs`, без eager-импорта `processes`.
  - **`processes/__init__.py`** — ленивый `__getattr__` для имён из `__all__` (без загрузки всех процессов при импорте пакета).
  - **`modules/__init__.py`** и **`modules/camera/__init__.py`** — без реэкспорта процессов/конфигов; только доменные хелперы камеры.
  - **`ProcessorConfig` / `RendererConfig`:** поле `class_path` — строковая константа (модуль процесса не импортируется из config-модуля); дефолты регистров по-прежнему из `registers/schemas/processing_tab/boot.py`.
- Причина: Сохранить единый источник параметров регистров и при этом допустимый порядок загрузки при сборке `proc_dict` и тестах.
- Отклонённые альтернативы: Только `TYPE_CHECKING` для импорта классов — не снимает цикл при выполнении `class_path_from_type` в рантайме.

---

## ADR-054: Backend прототипа — домен вне ProcessModule, merge managers
- Дата: 2026-03-20
- Статус: принято
- Контекст: Процессы `processor` / `renderer` / `camera` смешивали алгоритмы, SHM и `register_update` с обвязкой `ProcessModule`; дефолты `ProcessorConfig` расходились с `ProcessorRegisters`; полный `get_default_managers_config()` дублировался в каждом `proc_dict` без возможности точечного overlay.
- Решение:
  - **`backend/modules/<name>/`** — процесс camera / processor / renderer: `process.py` (`ProcessModule`), `config.py` (Pydantic для `proc_dict`), доменные модули рядом. **`backend/configs/`** — общие вещи (`ProcessConfigBase`, `app_config`, robot, database, gui); три конфига камеры/процессора/рендерера реэкспортируются из `configs/__init__.py` для `main.py`. **`backend/processes/`** реэкспортирует классы процессов из `modules` + локальные gui/robot/database.
  - **Подклассы `ProcessModule`** в `modules/*/process.py`; `backend/shared/` для общих утилит.
  - **Регистры:** `apply_processor_register_update` / `apply_renderer_register_update` + константы `PROCESSOR_REGISTER` / `RENDERER_REGISTER` из `registers/schemas/processing_tab/names.py`.
  - **`ProcessorConfig`:** числовые/list-дефолты из экземпляра `ProcessorRegisters()`.
  - **`merge_managers` + `ProcessConfigBase.managers_overlay()`** — сливают overlay поверх `get_default_managers_config()` (по умолчанию overlay пустой, поведение как раньше).
  - **Камера:** `CAMERA_SHM_HEIGHT` / `WIDTH` в `modules/camera/constants.py`, те же значения в `modules/camera/config.py` (`CameraConfig.memory`).
- Причина: Явная граница фреймворк / приложение, тестируемый домен, один источник дефолтов UI↔boot, задел на урезание `managers` по процессу.
- Отклонённые альтернативы: Вынести `WorkerManager` в доменные пакеты — ломает контракт фреймворка.

---

## ADR-053: Прототип — один GuiProcess, импорты регистров, FrontendManager runtime
- Дата: 2026-03-20
- Статус: принято
- Контекст: Дублировались `GuiProcess` (InspectorWindow) и `GuiProcessFrontend` (FrontendLauncher); виджеты импортировали `registers.schemas` как top-level — ломало `pytest` без хака `sys.path`; прототип присваивал `fm._queue_manager` / `fm._stop_event` после конструктора.
- Решение:
  - **Один GUI-класс** — `backend/processes/gui/gui_process.py` (`GuiProcess`) всегда через `FrontendLauncher` (см. ADR-056: без алиаса `GuiProcessFrontend`).
  - **Импорты схем** — только `multiprocess_prototype.registers.schemas…` в коде и тестах прототипа.
  - **`window_registry`** — `WindowRegistryEntry` и `default_window_registry()` в `frontend_config.py` (меньше файлов).
  - **FrontendManager** — параметры конструктора `queue_manager`, `stop_event` (публичный контракт вместо записи в приватные поля из лаунчера).
  - **GuiProcessMixin** — файл `backend/gui_process_mixin.py`, чтобы `gui_process` не импортировал пакет `frontend` (цикл с `GuiConfig` / `class_path_from_type(GuiProcess)`).
- Причина: Меньше расхождения веток GUI, воспроизводимые тесты, явная граница фреймворка.
- Отклонённые альтернативы: Оставить legacy InspectorWindow в прод-пути — дублирование таймеров и регистров.

---

## ADR-051: Модульные логи — опция `rotate` (Windows / общий файл)
- Дата: 2026-03-20
- Статус: принято
- Контекст: `RotatingFileHandler` при достижении `maxBytes` вызывает `os.rename` текущего файла. На Windows это даёт `PermissionError` (WinError 32), если тот же путь открыт в другом процессе или внешней программе, либо при нескольких writer на один файл. Высокочастотный perf-лог `frames.log` провоцировал ротацию и лавину ошибок из фонового flush BatchBuffer.
- Решение: В `ChannelConfig` / `ModuleConfig` добавлен флаг `rotate` (по умолчанию `true`). При `rotate: false` файловый канал использует `logging.FileHandler` в режиме append без rename. В прототипе для `logger.modules.processor_frames` задано `"rotate": false`.
- Причина: Минимальное изменение без отдельного процесса-писателя или `concurrent-log-handler`; для кадрового лога ротация редко нужна относительно стабильности.
- Отклонённые альтернативы: Только увеличить `max_size` — рано или поздно ротация снова сорвётся; отдельный файл на PID — усложняет анализ логов.

---

## ADR-052: Регистры по фичам — `schemas/processing_tab/`, UI-строки у виджета
- Дата: 2026-03-20
- Статус: принято
- Контекст: Плоские `registers/schemas/processor.py|renderer.py|processing_tab_ui.py` не отражали принадлежность к одной фиче; `ProcessingTabUiConfig` не участвует в `register_update`, но лежал рядом с синхронными схемами.
- Решение:
  - Синхронизируемые классы вкладки «Обработка» — пакет `multiprocess_prototype/registers/schemas/processing_tab/` (`processor.py`, `renderer.py`, `__init__.py` barrel, `names.py` с ключами `PROCESSOR_REGISTER` / `RENDERER_REGISTER`).
  - `ProcessingTabUiConfig` — `multiprocess_prototype/frontend/widgets/tabs_setting/processing_tab/schemas.py`. Пакет `registers` **не** импортирует `frontend`.
  - Корневой `multiprocess_prototype/registers/schemas/__init__.py` реэкспортирует символы фичи; импорт приложения: `from multiprocess_prototype.registers.schemas import …` (не короткий `registers` — пакет не на PYTHONPATH как top-level).
  - Контракт: `tests/test_register_schema_backend_contract.py` — множество полей `ProcessorRegisters` / `RendererRegisters` совпадает с ветками `_apply_register_update` в соответствующих процессах.
- Причина: Навигация «одна фича — одна папка регистров»; отделение UI-текстов от шины; задел под рецепты (один источник значений в регистрах).
- Отклонённые альтернативы: Один файл `processing_tab_ui.py`, реэкспортирующий и регистры — смешение ответственности и путаница имён.

---

## ADR-050: Схемы регистров — в приложении, не во фреймворке
- Дата: 2026-03-20
- Статус: принято
- Контекст: Пакет `shared_registers` во фреймворке содержал доменные классы (`DrawRegisters`, `ProcessorRegisters`, `RendererRegisters`) — хардкод прототипа внутри универсального слоя.
- Решение: Удалить `refactored/modules/shared_registers` с конкретными схемами. Канон для Inspector prototype — `multiprocess_prototype/registers/schemas/` (подпакеты по фичам, наследники `SchemaBase` из `data_schema_module`). Фреймворк остаётся с `data_schema_module`, `registers_module`, `frontend_module` без привязки к полям приложения.
- Причина: Граница «универсальный фреймворк / приложение»; новые проекты подставляют свои Register-классы в `RegistersManager`.
- Отклонённые альтернативы: Оставить `shared_registers` как «пример» — провоцирует импорт домена из фреймворка.

---

## ADR-049: StateRegister vs UiSchema (главное окно и вкладки)
- Дата: 2026-03-20
- Статус: принято
- Контекст: На `MainWindow` смешивались строки UI, алгоритмические поля и пути доставки (`register_update` vs команды); дублировалась схема `DrawRegisters` в прототипе.
- Решение:
  - **StateRegister** (`ProcessorRegisters`, `RendererRegisters`, и др. в `multiprocess_prototype/registers/schemas/<feature>/`) — канон имён полей, `FieldMeta`, маршрутизация `register_update` через `register_dispatch` / `FieldRouting` (см. ADR-050, ADR-052).
  - **UiSchema** (`ProcessingTabUiConfig` и аналоги) — только тексты и группировка для Qt; без маршрутизации на процессы; не дублирует алгоритмические значения; для вкладки «Обработка» — `frontend/widgets/tabs_setting/processing_tab/schemas.py`.
  - Вкладка «Обработка»: контролы `frontend_module` + `RegistersManager`; BGR как шесть слайдеров ↔ `color_lower` / `color_upper`; бэкенд принимает `register_update` в цикле data-воркера (`ProcessorProcess` / `RendererProcess`).
  - Прототип: обработка — `registers/schemas/processing_tab/`; другие фичи — отдельные подпакеты при появлении синхронных регистров.
- Причина: Один источник истины для имён полей GUI и процессов; UI-строки отделены от шины; см. `docs/ROUTING_GLOSSARY.md`, чеклист `multiprocess_prototype/registers/CHECKLIST.md`.
- Отклонённые альтернативы: Оставить только GUI-команды без регистров — расходится с `RegistersManager` и диспетчеризацией ADR-048.

---

## ADR-048: Доставка register_update — RegisterDispatchMeta, FieldRouting.process_targets, fan-out
- Дата: 2026-03-20
- Статус: принято
- Контекст: `RegistersManager` использовал только `connection_map`; дублировались цели доставки в прототипе; `FieldRouting.channel` описывает канал Router, а не обязательно имя процесса для `send_message`.
- Решение:
  - `RegisterDispatchMeta(process_targets=...)` — атрибут класса регистра (`register_dispatch`), единый источник для GUI → backend по имени регистра.
  - Опционально `FieldRouting(..., process_targets=...)` — override на уровне поля.
  - Приоритет разрешения целей: `routing.process_targets` поля → `register_dispatch` класса → `connection_map` (ручной override / обратная совместимость).
  - Fan-out: несколько имён в `process_targets` → несколько вызовов `send_callback` по порядку; ошибки по-прежнему подавляются в callback.
  - `build_connection_map_from_registers()` в `registers_module` строит `Dict[str, str]` (первый target) для API, ожидающего одну строку на регистр.
- Причина: Один паттерн без дублирования dict в приложении; явное разделение канала Router и процесса для `register_update` (см. `docs/ROUTING_GLOSSARY.md`).
- Отклонённые альтернативы: Только расширение `FieldRouting` списком процессов на каждое поле — избыточно для типичного регистра.

---

## ADR-047: Прототип — матрёшка widgets: вкладка + конфиг рядом
- Дата: 2026-03-20
- Статус: принято
- Контекст: `configs/tabs/` отрывал схемы от `widgets/*`; неочевидно, где править вкладку.
- Решение:
  - `widgets/tabs_setting/<имя>_tab/`: `widget.py` + `schemas.py` (вкладка как компонент) для строк UI (`processing_tab`, `camera_tab`); `settings_tab`: ControlBinding, SettingsTabConfig.
  - Общий слой полосы вкладок: `widgets/tabs_setting/` — `TabItemConfig`, `TabsConfig`; дефолтный список вкладок собирается из `default_tab_item()` каждого feature-пакета.
  - `configs/` — только корень приложения: `frontend_config.py`, `window_registry.py`, `config.py` (GuiConfig).
  - `windows/loading/` — `LoadingWindowConfig` рядом с использованием во фреймворке `LoadingWindow`.
- Причина: Навигация «открыл папку вкладки — всё рядом»; корневая композиция не раздувается чужими схемами.
- Отклонённые альтернативы: Плоский `widgets/*.py` без пакетов — хуже при росте числа файлов на вкладку.

---

## ADR-046: Прототип — feature-папка windows/main_window
- Дата: 2026-03-20
- Статус: принято
- Контекст: Конфиги главного окна жили в `configs/main_window/`, UI — в `windows/main_window.py`; сложнее сопоставлять части одной feature.
- Решение: Пакет `multiprocess_prototype/frontend/windows/main_window/`: `window.py`, `config.py`, `tab_factory.py`. `FrontendConfig` импортирует `MainWindowConfig` оттуда. `LoadingWindowConfig` — в `windows/loading/config.py`.
- Причина: Один каталог на «главное окно» — проще масштабировать тот же паттерн на другие окна.
- Отклонённые альтернативы: Всё в `configs/` — расхождение с UI-файлами.

---

## ADR-045: action_triggered + connect_action_handlers + optional action_id
- Дата: 2026-03-20
- Статус: принято
- Контекст: Нужна единообразная привязка обработчиков к динамическому числу кнопок из конфига без N отдельных pyqtSignal на классе.
- Решение:
  - Виджеты эмитят **один** сигнал с идентификатором действия (`pyqtSignal(str)`), например `HeaderWidget.action_triggered`.
  - В конфиге элемента кнопки: опциональный `action_id`; если не задан — используется `id`. У `AdminButtonConfig` поле `action_id` (по умолчанию `"admin"`).
  - Утилита `frontend_module.core.action_binding.connect_action_handlers(signal, handlers={...}, on_unmatched=...)` маршрутизирует вызовы.
  - `HeaderWidget.get_signal_map()` дополняет контракт `ISignalProvider` для интроспекции.
- Причина: В Qt динамически создавать отдельный сигнал на каждую кнопку неудобно; строковый канал + словарь обработчиков масштабируется и сериализуемо из конфига.
- Отклонённые альтернативы: только `button_clicked` без admin в том же канале — дублирование подключений у приложения.

---

## ADR-044: Реорганизация frontend_module/components и паттерн «конфиг рядом с виджетом»
- Дата: 2026-03-19
- Статус: принято
- Контекст: 16 файлов в одной папке components, дублирование конфигов (HeaderAdminButton, LogoConfig в prototype).
- Решение:
  - Структура: base/, header/, controls/, tabs/, tables/, keyboard/. performance_monitor в корне.
  - Паттерн «конфиг рядом с виджетом»: AdminButtonConfig, LogoConfig, HeaderButtonsConfig в frontend_module рядом с виджетами.
  - HeaderConfig в prototype импортирует AdminButtonConfig, LogoConfig из frontend_module для композиции.
  - Init виджетов: config + parent. Конфиг принимает SchemaBase | dict.
  - frontend_module зависит от data_schema_module (SchemaBase, register_schema).
  - FieldMeta для всех конфигов (как в draw.py): info, info_i18n, access_level — консистентность и расширяемость.
- Причина: Меньше параметров init, единый источник конфигов виджетов, логичная группировка.
- Отклонённые альтернативы: Обратная совместимость — пользователь подстраивается под новую структуру.

---

## ADR-043: Унифицированные конфиги frontend на SchemaBase + FieldMeta
- Дата: 2026-03-19
- Статус: принято
- Контекст: frontend_config использовал build_frontend_config() → plain dict без метаданных. Требовалась унификация с регистрами (FieldMeta, min/max, i18n) и декомпозиция по компонентам.
- Решение:
  - Конфиги как SchemaBase + FieldMeta: WindowConfig, HeaderConfig, ImagePanelConfig, TabsConfig, SettingsTabConfig, ControlBinding.
  - Композиция: MainWindowConfig, FrontendConfig. Per-component: main_window/, tabs/.
  - build_frontend_config() → FrontendConfig().build_dict(app_cfg). Dict at Boundary сохранён.
  - Config-driven tabs: tab_widget_factory(widget_key, tab_config). SettingsTabConfig.controls — привязка к регистрам.
  - to_json/from_json, to_yaml/from_yaml через DataConverter.
- Причина: Единый формат для конфигов и регистров, расширяемость, отсутствие хардкода.
- Отклонённые альтернативы: Оставить plain dict — теряем валидацию и метаданные.

---

## ADR-040: GuiProcessMixin
- Дата: 2026-03-19
- Статус: принято
- Контекст: Два класса GUI-процесса дублировали ~25 методов gui_* и _handle_*.
- Решение: Вынести в `GuiProcessMixin` (`backend/gui_process_mixin.py`). Наследует только `GuiProcess` (см. ADR-053 / ADR-056).
- Причина: Устранение дублирования, единый источник логики GUI-команд.
- Отклонённые альтернативы: Оставить дублирование — нарушает DRY.

---

## ADR-041: Конфиг-драйвен window registry
- Дата: 2026-03-19
- Статус: принято
- Контекст: FrontendLauncher.register_windows хардкодил main, inspector, loading.
- Решение: window_registry в конфиге (frontend_config): {name: {factory_key: "main"}}. Launcher регистрирует окна по конфигу.
- Причина: Добавление/удаление окон без переписывания launcher.
- Отклонённые альтернативы: Динамическая загрузка по path.to:fn — требует рефакторинга фабрик (closures).

---

## ADR-042: ProcessModule как IRouterLike для FrontendManager
- Дата: 2026-03-19
- Статус: принято
- Контекст: FrontendManager(router=process) — process не RouterManager, но имеет send_message.
- Решение: Protocol IRouterLike в frontend_module/interfaces.py: send_message(target, msg) -> bool. ProcessModule реализует контракт.
- Причина: Явная семантика: process делегирует в RouterManager через ProcessCommunication.
- Отклонённые альтернативы: Передавать RouterManager напрямую — GUI-процесс не имеет прямого доступа.

---

## ADR-001: ObservableMixin остаётся
- Дата: 2026-03-11
- Статус: принято
- Контекст: Рассматривалось удаление ObservableMixin как избыточного усложнения.
- Решение: ObservableMixin остаётся как часть BaseManager.
- Причина: Связывает logger, stats, error менеджеры через прокси-методы. Удаление потребует ручного прокидывания зависимостей во всех менеджерах.
- Отклонённые альтернативы: Прямое внедрение зависимостей через конструктор — отклонено из-за слишком большого количества изменений.

---

## ADR-002: registers_module остаётся (runtime != schema)
- Дата: 2026-03-11
- Статус: принято
- Контекст: Рассматривалось объединение registers_module с data_schema_module.
- Решение: registers_module остаётся отдельным модулем.
- Причина: data_schema_module — статические схемы (чертежи). registers_module — runtime-контейнер живых экземпляров схем + routing map. Разные ответственности.
- Отклонённые альтернативы: Объединение в один модуль — отклонено из-за нарушения SRP.

---

## ADR-003: data_schema_module — «живое ДНК»
- Дата: 2026-03-11
- Статус: принято
- Контекст: Вопрос о том, нужны ли схемы после запуска приложения или только для конфигурации.
- Решение: Схемы не выбрасываются после build(). Хранятся и обновляются в runtime.
- Причина: Позволяет запрашивать структуру данных любого процесса без дополнительной документации. Каждый процесс — хозяин своих данных.
- Отклонённые альтернативы: Только статическая конфигурация — отклонено как недостаточно гибко.

---

## ADR-004: Синхронизация ДНК через connection bundle
- Дата: 2026-03-11
- Статус: принято
- Контекст: Как обмениваться структурой данных между процессами.
- Решение:
  - Каталог (phone book): статическая структура {process_name: {fields, types, routing}} — формируется ProcessManager при старте, передаётся через connection bundle.
  - Живые данные: текущие значения хранятся только локально в процессе-хозяине.
  - Запрос данных: через Router → CommandManager → handler `get_field` → ответ.
- Причина: Избегает гонок данных. Каждый процесс владеет своими данными.
- Отклонённые альтернативы: Shared memory — отклонено из-за сложности синхронизации.

---

## ADR-005: Request-response через correlation_id
- Дата: 2026-03-11
- Статус: принято
- Контекст: Как реализовать синхронный запрос-ответ между процессами.
- Решение:
  - При отправке: генерируется message_id (UUID), добавляется reply_to.
  - При ответе: correlation_id = message_id из запроса.
  - В Router: метод `request(message, timeout)` — отправляет и ждёт ответ с matching correlation_id.
- Причина: Простой и понятный механизм. Не требует дополнительной инфраструктуры.
- Отклонённые альтернативы: Async callback — отклонено как избыточно сложный на этом этапе.

---

## ADR-006: Базы данных как отдельный ProcessModule
- Дата: 2026-03-11
- Статус: принято
- Контекст: Где реализовать работу с БД.
- Решение: DatabaseProcess — обычный ProcessModule, не часть фреймворка. Добавится позже.
- Причина: Фреймворк должен оставаться независимым от конкретных технологий хранения данных.
- Отклонённые альтернативы: Встроить в shared_resources_module — отклонено как нарушение SRP.

---

## ADR-007: ProcessPriority — Windows-only stub
- Дата: 2026-03-11
- Статус: принято
- Контекст: Управление приоритетами процессов на разных ОС.
- Решение: StubPlatformAdapter достаточен. Windows-only реализация через psutil/win32.
- Причина: Не критично для работоспособности системы на первом этапе.
- Отклонённые альтернативы: Кросс-платформенная реализация — отклонено как избыточно.

---

## ADR-008: Dict at Boundary (передача данных через границы процессов)
- Дата: 2026-03-11
- Статус: принято
- Контекст: Как передавать данные между процессами — через Pydantic модели или словари.
- Решение: На границах процессов используются dict. Внутри процесса — Pydantic модели допустимы.
- Причина: Pydantic модели не всегда сериализуются для multiprocessing.Queue. Dict гарантированно pickle-able.
- Отклонённые альтернативы: Pydantic модели везде — отклонено из-за проблем с сериализацией.

---

## ADR-009: gui_module пропускается
- Дата: 2026-03-11
- Статус: принято
- Контекст: Нужен ли GUI в рамках текущего рефакторинга.
- Решение: gui_module пропускается, не включается в план рефакторинга.
- Причина: Не критично для базовой функциональности фреймворка.

---

## ADR-010: console_module — менеджер терминальных окон
- Дата: 2026-03-14 (обновлено)
- Статус: реализовано
- Контекст: ConsoleManager управляет терминальным I/O процесса.
- Решение: Полноценный модуль с IPlatformConsole, ConsoleLogChannel, ConsoleAdapter.
  Три уровня: пассивный, активный, God Mode. Кроссплатформенность через WindowsConsole/UnixConsole.
- Причина: Нужен для отладки, мониторинга и интерактивного управления.

---

## ADR-011: Подход сверху вниз (top-down)
- Дата: 2026-03-11
- Статус: принято
- Контекст: Предыдущие итерации шли снизу вверх и не приводили к рабочей системе.
- Решение: Берём тестовое приложение multiprocess_prototype, запускаем его и чиним модули по мере столкновения с проблемами.
- Причина: Гарантирует рабочий результат на каждом этапе. Позволяет приоритизировать только нужное.
- Отклонённые альтернативы: Bottom-up (сначала все модули, потом интеграция) — отклонено как неэффективно.

---

## ADR-012: Unit-тесты достаточны (без integration на первом этапе)
- Дата: 2026-03-11
- Статус: принято
- Контекст: Какой уровень тестирования нужен.
- Решение: Unit-тесты для каждого модуля. Integration тесты — на этапе 7 при необходимости.
- Причина: multiprocess_prototype сам является интеграционным тестом.

---

## ADR-013: channel_routing_module — базовый класс для всех менеджеров с каналами
- Дата: 2026-03-12
- Статус: принято
- Контекст: RouterManager, LoggerManager, ErrorManager независимо реализовывали один паттерн
  (реестр каналов, диспетчер, буфер, lifecycle). Три раза один код = три источника ошибок.
- Решение: Создать `ChannelRoutingManager(BaseManager, ObservableMixin)` в новом `channel_routing_module`.
  В него переносится: `ChannelRegistry` (thread-safe), `Dispatcher` (key→handler), `IBufferStrategy`
  (pluggable), `normalize_config()` (Dict at Boundary), `ChannelRoutingConfig(RegisterBase)`.
- Причина: DRY. Исправление ошибки в registry / buffer теперь применяется ко всем менеджерам сразу.
  Новый менеджер = наследование CRM, а не копирование кода.
- Отклонённые альтернативы:
  - Миксин-классы (ChannelRegistryMixin, BufferMixin) — отклонено как источник MRO-конфликтов.
  - Вынести логику в отдельный helper-класс без наследования — отклонено: manager.registry.register()
    читается хуже, чем manager.register_channel().

---

## ADR-014: IChannel — единый базовый интерфейс каналов
- Дата: 2026-03-12
- Статус: принято
- Контекст: `IMessageChannel` и `ILogChannel` — несовместимые иерархии. `ChannelRegistry` в CRM
  требует единый тип.
- Решение: `IChannel` определён в `channel_routing_module.interfaces`. `ILogChannel(IChannel)` —
  добавлены `name`, `channel_type` как properties. `IMessageChannel(IChannel)` — добавлен `write()`
  как alias для `send()`.
- Причина: Единый `ChannelRegistry[IChannel]` хранит каналы всех типов. `isinstance(ch, IChannel)`
  как гарантия совместимости. Нет дублирования контракта `close()` / `get_info()`.
- Отклонённые альтернативы:
  - Три независимых реестра под каждый тип — отклонено как усиление фрагментации.
  - Protocol (structural typing) вместо ABC — отклонено: теряется явная ошибка при неполной реализации.

---

## ADR-015: AsyncSender остаётся в RouterManager (не заменяется AsyncSenderBuffer)
- Дата: 2026-03-12
- Статус: принято
- Контекст: CRM предоставляет `AsyncSenderBuffer(send_fn)` как pluggable буфер. Казалось логичным
  заменить `AsyncSender` в RouterManager на него.
- Решение: `AsyncSender` остаётся внутри `RouterManager` как специализированный компонент.
  `RouterManager(ChannelRoutingManager)` передаёт `buffer_strategy=None`.
- Причина: `AsyncSenderBuffer.enqueue(channel_name, data)` работает с уже resolved каналом.
  `AsyncSender` буферизует ВЕСЬ pipeline: `enqueue(msg) → apply_middleware(msg) → resolve_channels(msg)
  → write_to_channel`. Middleware-трансформации должны происходить ДО резолюции канала.
  Заменить AsyncSender на AsyncSenderBuffer = потеря middleware pipeline.
- Отклонённые альтернативы:
  - Обогатить `IBufferStrategy` поддержкой middleware — отклонено как нарушение SRP буфера.
  - Переместить middleware в channel.write() — отклонено: middleware в RouterManager привязано
    к маршруту, а не к каналу.

---

## ADR-016: ChannelRoutingConfig(RegisterBase) — базовый конфиг через наследование
- Дата: 2026-03-12
- Статус: принято
- Контекст: Конфиги менеджеров существовали в трёх форматах: dataclass (LogConfig), RegisterBase
  (ErrorManagerConfig), отсутствует (RouterManager). Нужна унификация без потери гибкости.
- Решение: `ChannelRoutingConfig(RegisterBase)` содержит общие поля `manager_name`, `channels`.
  `build()` → `(name, dict)`. `ErrorManagerConfig(ChannelRoutingConfig)` наследует и расширяет.
  `normalize_config()` принимает `None | dict | RegisterBase` и всегда возвращает `dict`.
- Причина: RegisterBase — уже принятый стандарт в framework (ADR-003). `build()` совместим с
  `normalize_config()`. Наследование позволяет добавлять специфичные поля (severity paths, batch_size)
  без потери общего API. Все конфиги попадают в `data_schema_module` через `@register_schema`.
- Отклонённые альтернативы:
  - Pydantic BaseModel напрямую (без RegisterBase) — отклонено: теряется интеграция с registers_module.
  - Единый монолитный конфиг со всеми полями всех менеджеров — отклонено как нарушение OCP.

---

## ADR-017: ConfigStore отдельно от ProcessData
- Дата: 2026-03-13
- Статус: принято
- Контекст: Конфиги процессов хранились в `ProcessData.custom["process_config"]`, смешиваясь с
  runtime-данными (статус, очереди, события). Это нарушало SRP и усложняло сериализацию.
- Решение: `ConfigStore` — отдельный pickle-safe компонент SRM. `ProcessData.custom` — только
  пользовательские runtime-данные. Конфиги статичны, ProcessData динамична.
- Причина: Разные жизненные циклы. Конфиг создаётся один раз при `register_process()`.
  ProcessData меняется в течение всего времени жизни процесса.
- Отклонённые альтернативы:
  - Конфиги в отдельном поле ProcessData — отклонено: ProcessData уже перегружен.

---

## ADR-018: SRM.register_process() — единая точка регистрации
- Дата: 2026-03-13
- Статус: принято
- Контекст: ProcessManager вручную вызывал 5+ методов для регистрации процесса:
  `register_process_state()`, `queue_registry.create_and_register_queues()`, `add_event()` и т.д.
  Любое изменение формата требовало правок в ProcessManager.
- Решение: `SRM.register_process(name, config_dict)` — один вызов. SRM сам создаёт Queue, Event,
  сохраняет конфиг, инициализирует SharedMemory.
- Причина: Инкапсуляция. ProcessManager не должен знать КАК создаются ресурсы.
  Изменение внутренней структуры не ломает вызывающий код.
- Отклонённые альтернативы:
  - Builder pattern — отклонено как избыточный для текущего масштаба.

---

## ADR-019: SharedMemory по именам (pickle-safe)
- Дата: 2026-03-13
- Статус: принято
- Контекст: `SharedMemory` объекты не pickle-able. Предыдущий код хранил их в `ProcessData.custom`,
  что делало pickle SRM невозможным.
- Решение: Хранить только `shm.name` строки в `ProcessData.custom["memory_names"]`.
  SharedMemory объекты живут в `MemoryManager._local_handles` (не pickle-able, пересоздаются).
  Owner process: `create=True`, `unlink()` при shutdown.
  Consumer process: `create=False`, `close()` при shutdown.
- Причина: Строки pickle-safe. OS-level shared memory доступна по имени из любого процесса.
- Отклонённые альтернативы:
  - `multiprocessing.Manager().dict()` — отклонено: требует Manager process, overhead.

---

## ADR-020: reinitialize_in_child() для восстановления после unpickle
- Дата: 2026-03-13
- Статус: принято
- Контекст: После unpickle SRM в дочернем процессе `EventManager._event_queue = None`,
  `MemoryManager._local_handles = {}`. Без восстановления они нефункциональны.
- Решение: Явный метод `SRM.reinitialize_in_child()`. Вызывается в `ProcessModule.initialize()`.
  НЕ автоматически в `__setstate__` — явное лучше неявного.
- Причина: Явный вызов даёт контроль над порядком инициализации. `__setstate__` вызывается
  в неопределённом контексте (может быть до инициализации других компонентов).
- Отклонённые альтернативы:
  - Автовосстановление в `__setstate__` — отклонено: скрытая логика, трудно дебажить.

---

## ADR-021: Прямой pickle SRM вместо ad-hoc bundle dict
- Дата: 2026-03-13
- Статус: принято
- Контекст: `run_process_function` получал `bundle = {"queues": {}, "config": ..., "custom": {...}}`
  и вручную пересоздавал SRM с нуля, копируя данные из bundle (~190 строк кода).
  Routing map строилась ad-hoc. Хрупко, дублирует логику.
- Решение: SRM pickle-ируется напрямую. Все Queue/Event ссылки сохраняются через OS pipe fd.
  `run_process_function` получает готовый SRM, вызывает `reinitialize_in_child()` (~30 строк).
- Причина: `multiprocessing.Queue` и `Event` нативно pickle-safe. Прямая передача SRM
  исключает дублирование логики создания ресурсов и делает код масштабируемым.
- Отклонённые альтернативы:
  - Сохранить bundle подход с улучшенной валидацией — отклонено: фундаментально хрупкий паттерн.

---

## ADR-023: config_module — тонкая обёртка над data_schema_module
- Дата: 2026-03-15
- Статус: принято
- Контекст: config_module на этапе 0/8, дублировал функционал data_schema_module
  (собственная валидация, _deep_update, мёртвая зависимость на StorageManager).
  Вопрос: нужен ли отдельный модуль или достаточно data_schema_module + ConfigStore?
- Решение: config_module остаётся. Переписан как тонкая обёртка:
  - `data_schema_module` = ЧТО (схемы, валидация, merge_with_defaults)
  - `config_module` = КАК (runtime доступ, dot-notation, подписки, секции, env-fallback)
  - `ConfigStore` (SRM) = ГДЕ (pickle-safe cross-process хранение)
  - StorageManager и EventManager удалены из ConfigManager — не нужны
  - `ConfigManagerConfig(SchemaBase)` через `@register_schema("config_manager")`
  - Импорты между модулями: абсолютные (pythonpath = refactored/modules)
- Причина: Runtime config management (подписки, секции, env fallback, dot-notation)
  — отдельная ответственность, которую не покрывает ни data_schema_module, ни ConfigStore.
- Отклонённые альтернативы:
  - Удаление config_module — отклонено: потеря runtime-API (уже интегрирован в spawner.py,
    process_module.py, process_registry.py).
  - Объединение с data_schema_module — отклонено: нарушает SRP.

---

## ADR-022: StatsManager — прямой наследник ChannelRoutingManager (не LoggerManager)
- Дата: 2026-03-15
- Статус: принято
- Контекст: Нужен менеджер статистики и метрик по аналогии с logger_module и error_module.
  Рассматривалось наследование от LoggerManager (как ErrorManager).
- Решение: `StatsManager(ChannelRoutingManager, IStatsManager)` — прямой наследник CRM.
  Буфер: `AggregationWindow(IBufferStrategy)` с агрегацией (counter, gauge, timing, histogram).
  Каналы: `LogStatsChannel` → LoggerManager.performance(), `FileStatsChannel` → JSON/CSV.
  Конфиг: `StatsManagerConfig(ChannelRoutingConfig)` через `@register_schema`.
- Причина: LoggerManager добавляет scope/level — не нужны для метрик. StatsManager имеет свою
  специфику: агрегация, flush-таймер, типы метрик. CRM даёт каналы и буфер без лишнего.
- Отклонённые альтернативы:
  - StatsManager(LoggerManager) — отклонено: scope/level избыточны для метрик.

---

## ADR-024: channel_types в receive() — разделение system и data очередей
- Дата: 2026-03-15
- Статус: принято
- Контекст: message_processor (system thread) и worker-потоки оба вызывали router.receive().
  DATA/EVENT сообщения потреблялись system thread и терялись — GUI не получал кадры.
- Решение:
  - `RouterManager.receive(channel_types=['system']|['data']|None)` — фильтр по типу канала
  - System thread опрашивает только `channel_types=['system']`
  - Worker-потоки (Processor, Renderer, GUI) — `channel_types=['data']`
  - Robot (только команды) — `channel_types=['system']`, без system thread
- Причина: Разделение ответственности: system — команды и управление, data — поток кадров и событий.
- Отклонённые альтернативы:
  - Отдельные очереди без фильтра — уже есть, но receive() читал из всех.

---

## ADR-025: multiprocess_prototype — ProcessConfigBase, config-driven memory, logging
- Дата: 2026-03-15
- Статус: принято
- Контекст: Рефакторинг тестового приложения Inspector Prototype после этапов 0–6.
- Решение:
  - **ProcessConfigBase** — базовый класс конфигов с `_build_proc_dict(class_path, queues, priority, memory)`
  - **Config-driven SharedMemory** — Camera/Renderer создают память из `config["memory"]` в build()
  - **Logging** — console channel, INSPECTOR_LOG_LEVEL, push_context(proc_name) в ProcessLifecycle
  - **MessageAdapter** — все процессы используют MessageAdapter для DATA/COMMAND/EVENT
- Причина: Устранение дублирования, единая точка конфигурации, отладочные логи в консоли.

---

## ADR-026: SharedMemory pipeline — unlink при shutdown, stale cleanup, print fallback
- Дата: 2026-03-15
- Статус: принято
- Контекст: На macOS POSIX shm сегменты не удаляются при Ctrl+C/crash. Следующий запуск падал с
  FileExistsError при create=True. MemoryManager._log_error шёл в ObservableMixin без logger → silent NO-OP.
  write_images возвращал None, GUI показывал "Waiting for frames...".
- Решение:
  1. **ProcessLifecycle.shutdown()** — вызов `shared_resources.shutdown()` для unlink SharedMemory
  2. **MemoryManager._create_shm_blocks** — перед create=True попытка открыть+unlink устаревший сегмент
  3. **print() fallback** — в _create_shm_blocks, _validate_memory_access, write_images при критических ошибках
  4. **run.sh** — preamble очистки stale shm (camera_frame_0/1, rendered_frame_0/1)
  5. **CameraProcess** — auto_start=False, в _cmd_start явный start_worker если не запущен
- Причина: POSIX shm персистит до unlink/reboot. Без SRM.shutdown() MemoryManager.shutdown() не вызывался.
  print() гарантирует видимость ошибок при отсутствии logger.

---

## ADR-028: shared_resources_module и data_schema_module — разделение ответственностей
- Дата: 2026-03-15
- Статус: принято
- Контекст: Проверочный рефакторинг shared_resources_module. Вопрос о дублировании логики с data_schema_module.
- Решение:
  - shared_resources_module — runtime: ProcessData, Queue, Event, SharedMemory, ConfigStore (dict). Без схем, без валидации.
  - data_schema_module — схемы (RegisterBase), валидация, ProcessDataContainer (использует ProcessData.custom).
  - DataSchemaAdapter — тонкий мост: делегирует в data_schema_module.StorageManager. Не содержит схемной логики.
  - ConfigStore хранит только dict (Dict at Boundary). Валидация конфигов — в config_module через data_schema_module.
- Причина: SRP. shared_resources — инфраструктура межпроцессного взаимодействия. data_schema — структура и валидация данных.
- Отклонённые альтернативы: Объединение — отклонено (разные жизненные циклы, разные зависимости).

---

## ADR-027: rendered_frame_ready — два изображения (original + mask)
- Дата: 2026-03-15
- Статус: принято
- Контекст: multiprocess_prototype расширен: два изображения (оригинал с контурами и маска),
  чекбоксы отправляют команды в Renderer.
- Решение:
  - `rendered_frame_ready` содержит два блока: `shm_actual_name`/`shm_index` для rendered_frame,
    `mask_shm_actual_name`/`mask_shm_index` для mask_frame
  - Дополнительно: `show_original`, `show_mask`, `draw_contours` — состояние отображения
  - Processor owner `processor_mask`, Renderer owner `rendered_frame` и `mask_frame`
- Причина: Явное разделение original/mask в одном сообщении. Dict at Boundary.

---

## ADR-028: Memory config — декларативно в конфиге, создание под капотом
- Дата: 2026-03-16
- Статус: принято
- Контекст: Процессы (camera, renderer, processor) дублировали логику создания SharedMemory.
  Требовалось объявлять память в конфиге и повторять create_memory_dict в коде процесса.
- Решение:
  - Создание SharedMemory из config["memory"] выполняется только в process_runner (под капотом).
  - Процессы не вызывают create_memory_dict — только используют memory_manager.
  - Поддержка короткого формата: `(h, w, c)` → `(1, (h,w,c), "uint8")`.
  - Плоский формат: `{"camera_frame": (h,w,3)}` вместо `{"names": {...}, "coll": 2}`.
- Причина: DRY, единая точка создания памяти, лаконичный конфиг.
- Отклонённые альтернативы: Оставить fallback в процессах — отклонено как дублирование.

---

## ADR-029: hikvision_camera_module — вынос Hikvision в отдельный модуль
- Дата: 2026-03-17
- Статус: принято
- Контекст: Логика Hikvision (enum, open, grab, parameters) была размазана по backends.py и hikvision_camera_process.py. Дублирование ~400 строк. Services/hikvision_camera — чистый SDK, оставляем без изменений.
- Решение:
  - Создан отдельный пакет `Inspector_prototype/hikvision_camera_module/` (сосед multiprocess_framework и multiprocess_prototype).
  - `HikvisionCameraFacade` — простой синхронный фасад (enum_devices, open, close, start_grabbing, stop_grabbing, capture_frame, get/set_parameters).
  - `HikvisionCameraProcessAdapter` — тонкий ProcessModule-адаптер, делегирует в фасад.
  - `capture_frame()` возвращает сырой np.ndarray (2D/3D) без cv2. cv2-конвертация в прототипе (backends, adapter).
  - HikvisionBackend в backends.py — обёртка над фасадом. HikvisionCameraProcess — алиас HikvisionCameraProcessAdapter (legacy).
- Причина: Инкапсуляция сложной логики, единая точка изменений, Dict at Boundary, соответствие структуре refactored modules.
- Отклонённые альтернативы: Оставить логику в prototype — отклонено как нарушение SRP.

---

## ADR-030: SharedMemory на Windows — уникальные имена с PID
- Дата: 2026-03-17
- Статус: принято
- Контекст: На Windows `create=True` для SharedMemory даёт `FileExistsError: [WinError 183] File exists`, если блок с таким именем остался от предыдущего запуска. `unlink()` на Windows — no-op, cleanup_stale_shm не освобождает mapping.
- Решение: В `create_shm_blocks` на Windows использовать `base_name_{pid}` вместо `base_name`. Фактические имена (shm.name) сохраняются в `memory_names` и передаются consumer-процессам через bundle.
- Причина: Каждый запуск получает уникальные имена; конфликты с предыдущими сессиями исключены.
- Отклонённые альтернативы: open+close перед create — не освобождает mapping, если другой процесс держит handle.

---

## ADR-031: SharedMemory — очистка перед стартом (все платформы)
- Дата: 2026-03-17
- Статус: принято
- Контекст: Нужна единая стратегия очистки устаревших SharedMemory перед запуском на Windows, Linux, macOS.
- Решение:
  1. **cleanup_stale_shm** — на всех платформах: open+close (Windows: освобождает при последнем handle; POSIX: +unlink).
  2. **cleanup_known_shm_at_startup(processes_config)** — вызывается в SystemLauncher.run()/start() перед launch_orchestrator. Извлекает имена из config["memory"] и очищает {name}_0..{name}_{coll-1}.
  3. **create_shm_block** — всегда вызывает cleanup_stale_shm перед create.
- Причина: Windows в приоритете; Linux и macOS получают ту же логику. Конфиг-драйвен, без дублирования имён.

---

## ADR-032: sql_module — универсальный SQL-менеджер
- Дата: 2026-03-18
- Статус: принято
- Контекст: Нужен доступ к БД из процессов framework. ADR-006: DatabaseProcess — обычный ProcessModule, не часть фреймворка.
- Решение:
  - Отдельный модуль `sql_module` в refactored/modules.
  - SQLManager(BaseManager, ObservableMixin) — единая точка входа.
  - Dual sync/async через адаптеры (ISyncEngineAdapter, IAsyncEngineAdapter).
  - Fork-safety: NullPool при INSPECTOR_MULTIPROCESS=1, создание engine после fork.
  - Typed Commands: DBQueryCommand, DBExecuteCommand (Pydantic)
  - Доступ через CommandManager: execute_command(cmd)
  - IRepository[T, ID], IUnitOfWork, IAsyncUnitOfWork, ISchemaMapper
  - uow() — sync, uow_async() — async (ленивое создание адаптера при первом вызове).
  - Интеграция через ObservableMixin: logger_module (_log_*), error_module (_track_error), statistics_module (_record_timing).
  - Схемы: data_schema_module.SchemaBase или pydantic.BaseModel.
- Причина: Переиспользуемое ядро для DatabaseProcess; Clean Architecture; слабая связность через адаптеры.

---

## ADR-033: frontend_module и shared_registers — фундамент UI-фреймворка
- Дата: 2026-03-18
- Статус: принято (частично устарело по схемам регистров — см. ADR-050)
- Контекст: Нужен UI-фреймворк как конструктор виджетов. ADR-009: gui_module пропускался; теперь этап фронтенда.
- Решение:
  - **frontend_module** — модуль в refactored/modules. Интерфейсы: IConfigurableWidget, IWidgetRegistry, IWindowRegistry, IRegistersManager. Структура: core/, schemas/, tests/. Паттерн «виджеты-конструктор».
  - ~~**shared_registers** — пакет в refactored/modules~~ **Удалено (ADR-050).** Конкретные классы регистров задаёт приложение (наследники `SchemaBase`); прототип — `multiprocess_prototype/registers/schemas`.
  - Схемы и конфиги виджетов — через data_schema_module и config_module.
  - Реализация компонентов (BaseConfigurableWidget, Slider, Checkbox) — на следующих этапах.
- Причина: Фундамент без перегрузки. Единые регистры устраняют дублирование App vs backend. Интерфейсы задают контракт до реализации.
- Отклонённые альтернативы: gui_module внутри framework — оставлено имя frontend_module как более общее.

---

## ADR-034: FrontendManager — единая точка входа (BaseManager)
- Дата: 2026-03-18
- Статус: принято
- Контекст: frontend_module нуждался в единой точке входа для интеграции с фреймворком (logger, config, router).
- Решение:
  - **FrontendManager(BaseManager, ObservableMixin)** — координация регистров, конфига, окон, потоков
  - Адаптеры: registers (FrontendRegistersBridge), window_manager, thread_manager
  - Coordinator удалён (2026-03-18): логика перенесена в FrontendManager.run_app/shutdown_app
- Причина: Единообразие с другими менеджерами, ObservableMixin для _log_*, _record_*, интеграция с config_module.
- Отклонённые альтернативы: Три отдельных BaseManager (Window, Thread, Config) — избыточно для скелета.

---

## ADR-039: Рефакторинг multiprocess_prototype — документация и очистка (2026-03-18)
- Дата: 2026-03-18
- Статус: принято
- Контекст: Приведение документации в соответствие с кодом, удаление устаревших скриптов.
- Решение:
  - **Скрипты _test_phase1/2/3 удалены** — использовали process_1/process_2 (удалены с processes/)
  - **frontend/configs/ удалён** — дублировал configs/; процессный конфиг GUI — `GuiConfig` в `backend/processes/gui/`
  - **Документация** — README, STATUS обновлены (6 процессов, `GuiConfig` в `main.py`, Coordinator убран); каноничная архитектура — `multiprocess_prototype/docs/ARCHITECTURE.md`
- Причина: Актуальность документации, отсутствие мёртвого кода.

---

## ADR-038: Устранение дублирования processes и registers (2026-03-18)
- Дата: 2026-03-18
- Статус: принято
- Контекст: processes/ и backend/processes/ содержали идентичные файлы; GuiProcess/GuiProcessFrontend дублировали создание RegistersManager.
- Решение:
  - **processes/ удалён** — все импорты через multiprocess_prototype.backend.processes
  - **Регистры** — `FrontendLauncher` вызывает `multiprocess_prototype.registers.create_registers()` (единая фабрика)
- Причина: Один источник правды, отсутствие дублирования структуры.

---

## ADR-037: Рефакторинг frontend_module и multiprocess_prototype (2026-03-18)
- Дата: 2026-03-18
- Статус: принято
- Контекст: Упрощение frontend_module, разделение backend/frontend в multiprocess_prototype.
- Решение:
  - **Coordinator удалён**: логика run/shutdown перенесена в FrontendManager.run_app(), shutdown_app()
  - **_HAS_QT устранён**: frontend_module требует PyQt5; единая точка импорта — core/qt_imports.py
  - **_model_to_register_name удалён**: мёртвый код; _auto_detect_register использует register_names()
  - **multiprocess_prototype**: backend/ (configs/, processes/, modules/), frontend/ (config, process, registers, windows/)
  - **configs/** перенесены в backend/configs/; схема GUI-процесса — `GuiConfig` (`backend/processes/gui/gui_config.py`), композиция UI — `FrontendConfig` (`frontend/configs/frontend_config.py`)
- Причина: Чистота кода, чёткое разделение backend/frontend для последующей концентрации на UI.

---

## ADR-035: FrontendRegistersBridge — связь frontend с backend
- Дата: 2026-03-18
- Статус: принято
- Контекст: RegistersManager (registers_module) не BaseManager. Нужна обёртка для connection_map и send_callback.
- Решение:
  - **FrontendRegistersBridge** — реализует IRegistersManager, делегирует в RegistersManager
  - connection_map: {register_name: channel} — при set_field_value → send через router
  - send_callback: (channel, register_name, field_name, value, snapshot) → router.send_message(target, msg)
- Причина: Гибкость: RegistersManager остаётся в registers_module, frontend получает связь с backend.
- Отклонённые альтернативы: Расширить RegistersManager до BaseManager — нарушает ADR-002.

---

## ADR-036: Конфигурация frontend — hot-reload без перезапуска
- Дата: 2026-03-18
- Статус: принято
- Контекст: Требование менять конфигурацию и обновлять UI без закрытия приложения.
- Решение:
  - FrontendManager подписывается на config_module.Config (key="*")
  - При изменении → _on_config_changed → emit_event("config_changed") → WindowManager.update_config()
  - Окна с методом apply_config(config) получают новый конфиг
- Причина: Гибкость для масштабирования, единый источник конфига в ConfigManager.
