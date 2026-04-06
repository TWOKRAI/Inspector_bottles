# Фреймворк как конструктор многопроцессорных приложений

## Главная идея

Фреймворк — это набор **слабо связанных модулей**, каждый из которых решает одну задачу. Из них, как из кубиков, собирается многопроцессорное приложение: запускаются процессы (**`ProcessModule`**), внутри каждого — свои менеджеры, которые общаются через **единую систему сообщений** и **маршрутизации по каналам**.

## Что делает каждый модуль (коротко)

| Модуль | Ответственность |
|--------|-----------------|
| **base_manager** | **`BaseManager`** + **`ObservableMixin`**: жизненный цикл менеджеров, адаптеры, прокси в logger / stats / error. Основа почти всех менеджеров. |
| **data_schema_module** | Описание данных: **`SchemaBase`**, поля с метаинформацией (**`FieldMeta`**, **`FieldRouting`**). **Без зависимостей на другие модули фреймворка** — ядро. |
| **message_module** | Единый формат сообщений (**`Message`**, **`MessageAdapter`**). **На границе процессов — только dict** (ADR-008). |
| **channel_routing_module (CRM)** | База для всех, кто гоняет данные по каналам: реестр каналов, буферизация, диспетчеризация. От него наследуются Router / Logger / Error / Stats. |
| **router_module** | Межпроцессная маршрутизация: исходящие через **`AsyncSender`** и каналы, входящие через **`message_dispatcher`**. **Не путать канал Router и имя процесса** — см. `docs/ROUTING_GLOSSARY.md`. |
| **dispatch_module** | Стратегии маршрутизации **внутри одного процесса**: **EXACT**, **FALLBACK**, **PATTERN**, **CHAIN** (и сценарии). |
| **command_module** | Регистрация и вызов обработчиков по полю **`command`** в сообщении. Надстройка над **`dispatch_module`**. |
| **logger_module** | Логирование с маршрутизацией по каналам (scope-based, batch). |
| **error_module** | Ошибки (critical / error / warning) с записью в отдельные файлы, **`log_exception`**. |
| **statistics_module** | Метрики (counter, gauge, timing, histogram) и сброс по каналам. |
| **config_module** | Runtime-доступ к конфигурации (dot-notation, env-fallback, подписки). **Межпроцессовое хранилище конфигов** — **`ConfigStore`** в SRM; валидация/схемы — в **data_schema_module**. |
| **shared_resources_module (SRM)** | **Очереди, события, разделяемая память, ConfigStore.** Pickle-safe; в дочернем процессе после unpickle — **`reinitialize_in_child()`**. **Регистры приложения сюда не входят** — это **`registers_module`** + схемы в приложении. |
| **worker_module** | Потоки внутри процесса: циклы, задачи, пауза / останов. |
| **process_module** | Базовый класс процесса приложения: композиция **RouterManager**, **CommandManager**, **WorkerManager**, **LoggerManager**, **ErrorManager**, **StatsManager** и т.д. **`sql_module`** подключается **по необходимости** (часто только в процессе БД). |
| **process_manager_module** | Оркестрация: **`SystemLauncher`** → **`ProcessManagerProcess`**. Конфиги на границе — **dict**; сборка из **SchemaBase** / схем приложения — см. `docs/CONFIG_SCHEMA_DATA_FLOW.md`, ADR-102/104. |
| **registers_module** | Runtime **регистров** (живые экземпляры схем): **`RegistersManager`**, карты доставки, связь с UI. **Классы схем** лежат в приложении (например `multiprocess_prototype/registers/schemas/`). Маршруты для **`register_update`** строятся из **`FieldRouting`**, **`register_dispatch`**, **`connection_map`**; **Router** переносит **сообщения** по каналам, а не «хранит» регистры. |
| **frontend_module** | GUI (PyQt): **FrontendManager**, **FrontendRegistersBridge**, исходящие команды — **RoutedCommandSender**. |
| **sql_module** | БД (SQLAlchemy 2.0). Обычно **отдельный процесс**; команды по каналу **`database`** / `db.*`. |
| *(расширения)* | Например modbus, camera — по тем же правилам: **`interfaces.py`**, каналы, команды, **Dict at Boundary**. |

## Как это собирается в приложение

1. **Конфиги и схемы** описываются через **data_schema_module** (Pydantic v2 / **`SchemaBase`**); на границе запуска — **dict**.

2. **`SystemLauncher`** (`process_manager_module`) поднимает систему и создаёт главный процесс-оркестратор — **`ProcessManagerProcess`**.

3. Оркестратор по конфигам дочерних процессов создаёт экземпляры **`ProcessModule`** (или наследников).

4. При инициализации каждый **`ProcessModule`** поднимает типичный набор менеджеров:
   - **`RouterManager`** — обмен с другими процессами (**каналы** → очереди SRM);
   - **`CommandManager`** — обработка поля **`command`** в сообщении;
   - **`WorkerManager`** — потоки доменной логики (камера, пайплайн и т.п.);
   - логирование, ошибки, статистика; при необходимости — **SQLManager**.

5. Приём сообщений в роутере обычно ведёт **внутренний цикл `RouterManager` / AsyncReceiver**; воркеры не обязаны «крутить» роутер — это зависит от lifecycle конкретного процесса.

6. Общение между процессами — только через **`Message`** (**на границе — dict**). **`RouterManager`** направляет исходящие:
   - по **`msg["channel"]`** — в очереди других процессов или в служебные каналы;
   - входящие отдаются в **`message_dispatcher`** → зарегистрированные обработчики.

7. Внутри процесса поле **`command`** (на верхнем уровне сообщения, плюс **`data`** / **`args`** по контракту типа) обрабатывает **`CommandManager`** поверх **`dispatch_module`**.

8. **Регистры:** схемы в коде приложения; **`FrontendRegistersBridge`** и **`registers_module`** связывают UI и бэкенд; обновления уходят сообщениями по согласованным каналам / целям (**`ROUTING_GLOSSARY`**).

9. Логи и ошибки — через **`ObservableMixin`** (`_log_*`, `_track_error`) и/или явные **LOG**-сообщения в каналы.

## Ключевой принцип

Фреймворк — **конструктор**: IPC не пишется с нуля, берутся модули, настраиваются **конфигами и схемами**, связь — через **роутер и каналы**. У каждого модуля — **чёткий контракт (`interfaces.py`)**, тесты и документация.

## Куда смотреть в коде

| Что | Путь |
|-----|------|
| Модули фреймворка | `Inspector_prototype/multiprocess_framework/modules/` |
| Прототип инспектора | `Inspector_prototype/multiprocess_prototype/` (в т.ч. `registers/schemas/` или актуальный пакет схем в этом прототипе) |
| ADR | `Inspector_prototype/multiprocess_framework/DECISIONS.md` |

См. также: `.claude/FRAMEWORK_RULES_EXTRACT.md`, `.claude/CLAUDE.md`.
