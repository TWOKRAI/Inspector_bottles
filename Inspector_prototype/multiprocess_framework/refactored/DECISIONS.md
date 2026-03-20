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
  - **Один GUI-класс** — `backend/processes/gui_process.py` (`GuiProcess`) всегда через `FrontendLauncher`; `GuiProcessFrontend` остаётся только как алиас в `multiprocess_prototype.frontend` для обратной совместимости импорта.
  - **Импорты схем** — только `multiprocess_prototype.registers.schemas…` в коде и тестах прототипа.
  - **`window_registry`** — `WindowRegistryEntry` и `default_window_registry()` в `frontend_config.py` (меньше файлов).
  - **FrontendManager** — параметры конструктора `queue_manager`, `stop_event` (публичный контракт вместо записи в приватные поля из лаунчера).
  - **GuiProcessMixin** — файл `backend/gui_process_mixin.py`, чтобы `gui_process` не импортировал пакет `frontend` (цикл с `GuiConfigFrontend` / `class_path_from_type(GuiProcess)`).
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
  - `ProcessingTabUiConfig` — `multiprocess_prototype/frontend/widgets/processing_tab/ui_config.py`. Пакет `registers` **не** импортирует `frontend`.
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
  - **UiSchema** (`ProcessingTabUiConfig` и аналоги) — только тексты и группировка для Qt; без маршрутизации на процессы; не дублирует алгоритмические значения; для вкладки «Обработка» — `frontend/widgets/processing_tab/ui_config.py`.
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
  - `widgets/<имя>_tab/`: `widget.py` + `config.py` (вкладка как компонент) + при необходимости `ui_config.py` для строк UI (`processing_tab`, `camera_tab`); settings_tab: ControlBinding, SettingsTabConfig.
  - Общий слой полосы вкладок: `widgets/tabs/` — `TabItemConfig`, `TabsConfig`; дефолтный список вкладок собирается из `default_tab_item()` каждого feature-пакета.
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
- Контекст: GuiProcess и GuiProcessFrontend дублировали ~25 методов gui_* и _handle_*.
- Решение: Вынести в GuiProcessMixin (frontend/mixins/gui_process_mixin.py). GuiProcess и GuiProcessFrontend наследуют GuiProcessMixin.
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
  - **frontend/configs/ удалён** — дублировал configs/; GuiConfigFrontend — в frontend.config
  - **Документация** — README, STATUS, GUI_PROCESS_COMPARISON обновлены (6 процессов, GuiConfigFrontend по умолчанию, Coordinator убран)
- Причина: Актуальность документации, отсутствие мёртвого кода.

---

## ADR-038: Устранение дублирования processes и registers (2026-03-18)
- Дата: 2026-03-18
- Статус: принято
- Контекст: processes/ и backend/processes/ содержали идентичные файлы; GuiProcess/GuiProcessFrontend дублировали создание RegistersManager.
- Решение:
  - **processes/ удалён** — все импорты через multiprocess_prototype.backend.processes; GuiProcessFrontend — через frontend.process
  - **create_frontend_registers()** — GuiProcess и GuiProcessFrontend используют frontend.registers.create_frontend_registers()
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
  - **configs/** перенесены в backend/configs/; GuiConfigFrontend — в frontend/config.py
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
