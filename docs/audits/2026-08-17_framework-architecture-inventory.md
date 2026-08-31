# Инвентаризация архитектуры фреймворка — 2026-08-17

> Снят на ветке `feat/telemetry-stage6` (HEAD `b6838e2b`, `main` + 137 коммитов).
> Повод: пересмотр плана [`framework-layer-grouping`](../../plans/framework-layer-grouping/plan.md),
> написанного 2026-07-26 по замеру от 2026-07-20 — за месяц изменились и числа, и граф.
> Вопросы владельца, ради которых снималось: выносить ли `frontend_module` и `display_module`
> в `Services/`; где место `backend_ctl`; переносить ли плагины в сервисы; как сгруппировать
> модули по смыслу для универсального конструктора многопроцессных приложений.
>
> **Статус: полный.** 27 модулей фреймворка, 13 сервисов, 52 плагина разобраны; граф снят AST.
> Источники: четыре независимых читателя + собственный замер. Ревью независимым агентом — в работе.

---

## 1. Метод и его ошибки (читать первым)

Граф снимался четыре раза. Три первых дали **неверный результат**, и все три ошибки —
инструментальные, а не предметные. Записаны здесь, потому что каждая выглядела как факт:

| # | Инструмент | Что дал | Почему неправда |
|---|---|---|---|
| 1 | `grimp`, схлопывание модулей | «цикл из 20 модулей» | в граф попали `tests/` — тесты законно импортируют вверх и связывают всё во всём |
| 2 | `grimp` + `squash_module`, тесты убраны | «жёстких циклов нет, все модули в тире 0» | после `squash_module` grimp не отдаёт `get_import_details` — классификация рёбер считалась по **пустой выборке**; «нет циклов» означало «нет данных» |
| 3 | `grimp` без схлопывания, классификация по отступу строки | «цикл из 5 модулей» | `line_contents` у grimp приходит **без отступа** — отличить импорт верхнего уровня от импорта внутри функции по нему нельзя |
| 4 | **AST-разбор, 797 файлов** | результат ниже | — |

Четвёртый прогон тоже был исправлен по ходу: первая его версия резолвила относительные импорты
без различия «пакет (`__init__.py`) / обычный файл», из-за чего `from .._fallback import …`
уходил в несуществующий путь и **рёбра терялись молча**. Поймано сверкой с `grimp`: у него
рёбер было больше. Числа до правки — занижены, в этом документе их нет.

**Правило, вытекающее из §1:** любой вывод про «циклов нет» обязан приходить с указанием,
что именно считалось рёбрами и на какой выборке. «Нет циклов» и «нет данных» выглядят
одинаково.

### Как воспроизвести

Скрипт AST-замера — `scratchpad/ast_graph.py` (см. приложение А). Классифицирует каждый импорт
на три класса: `hard` (верхний уровень модуля — исполняется при импорте), `lazy` (внутри
функции/метода — не исполняется), `tc` (под `if TYPE_CHECKING`). Тесты, `conftest`, `test_*`
исключены.

---

## 2. Граф импортов — измеренное состояние

### 2.0 Что исключено из выборки (читать до всех чисел §2)

> **Добавлено по ревью (M-1).** Первая редакция молча не включила в выборку **корневой фасад** —
> и тем нарушила правило, которое §1 сама объявляет главным.

`multiprocess_framework/__init__.py` **жёстко импортирует ~20 модулей** на верхнем уровне
(секции «LAYER 1: FOUNDATION», «LAYER 2: ROUTING PRIMITIVES» и далее, вплоть до
`process_manager_module` и `actions_module`). Скрипт замера сканирует только `modules/`, поэтому
фасада в выборке нет. Три следствия, важные для решений:

1. **«Тир 0 не импортирует ничего» верно про файлы модуля и неверно про запуск.** Команда
   `import multiprocess_framework.modules.data_schema_module` исполняет `__init__.py`
   родительского пакета — то есть тянет почти весь фреймворк. **Поднять модуль в изоляции сегодня
   нельзя**, и §3.1 «самостоятельность» это свойство не покрывает.
2. **`actions_module` с fan-in 0 имеет потребителя уровня фреймворка** — фасад экспортирует
   `ActionBus` (`__init__.py:137-143`). Замер его не видел.
3. Вывод §2.1 «циклов нет» **устоял** под проверкой: обратно фасад тянет только `version.py`, и
   то лениво (`process_module/core/process_module.py:573`).

Показательная деталь: докстринг фасада (`:146-153`) объясняет, что PySide6 сделали **ленивым**
из-за умножения памяти при спавне 8 процессов. К остальным двадцати жёстким импортам та же логика
не применена — и это отдельный вопрос к пересмотру (§8 Q17).

Вторая известная слепая зона метода — **строковые импорты**: `plugins/manager.py:376`,
`process_manager_module/runner/class_loader.py:27`, `topology/blueprint.py:849`,
`managers/observability_wiring.py:905`, `service_module/scanner.py:131` тянут код по строке из
конфига. AST-граф их не видит по построению.

### 2.1 Циклов при импорте нет

```
ЦИКЛЫ по жёстким рёбрам (import-time):  нет
ЦИКЛЫ с учётом отложенных:              _fallback ↔ base_manager ↔ channel_routing ↔ logger
  единственное отложенное ребро:        _fallback.py:91 → logger_module
```

Единственный цикл возникает только при учёте одного **намеренно отложенного** импорта.
Докстринг `_fallback.py` объясняет приём дословно: «импортировать в этот момент
`logger_module` нельзя… объект конструируется без единого импорта, вид подтягивается при
первой записи». Это не долг.

**Следствие для плана layer-grouping:** его Фаза 2 («разорвать 2 import-time цикла») **закрыта, и
план это знает** — `:307-309` несут `[x]` с хешами `92c19f2e`/`d9dddf45` и пометку «сверено по git
2026-07-20», `:450` — «разорваны». По конвенции проекта checkbox + хеш **и есть** приёмка;
прежняя формулировка «приёмка не проводилась» снята по ревью №2 как неверная. Оба цикла мертвы:

- `process → process_manager` (шим `blueprint.py`) — ребра в графе нет;
- `console → process` — нет; `console_module` импортирует только `base_manager`,
  `data_schema_module`, `logger_module`.

Третий цикл из документов — `channel_routing → dispatch` — тоже мёртв (Ф4.6, 2026-08-05),
но **документы этого не знают** (см. §6).

### 2.2 Девять тиров

Тир = длина самой длинной цепочки жёстких зависимостей вниз. 0 — не импортирует из
фреймворка ничего.

| Тир | Модули |
|---|---|
| 0 | `data_schema`, `_fallback`, `observability_declarations`, `telemetry_readmodel`, `display`, `service` |
| 1 | `base_manager`, `message` |
| 2 | `channel_routing`, `worker`, `dispatch`, `registers` |
| 3 | `logger`, `chain`, `command` |
| 4 | `config`, `console`, `shared_resources`, `error`, `event`, `recipe`, `statistics`, `actions` |
| 5 | `router`, `frontend`, `state_store` |
| 6 | `process` |
| 7 | `process_manager` |
| 8 | `app` |

Документная «12-слойка» (`CONSTRUCTOR_BLUEPRINT.md`, `MODULE_CONTRACTS.md`,
`MODULES_RESPONSIBILITY_MAP.md`) с этим согласуется по направлению, но не по глубине:
граф широкий и мелкий, большинство модулей — низкоуровневые листья.

### 2.3 Fan-in: кто на самом деле ядро

| Модуль | fan-in внутри фреймворка | Импортирует |
|---|---|---|
| `data_schema_module` | **17** | ничего |
| `base_manager` | **16** | `_fallback`, `data_schema` |
| `logger_module` | **13** | `_fallback`, `base_manager`, `channel_routing`, `data_schema` |
| `channel_routing_module` | 5 | `_fallback`, `base_manager`, `data_schema` |
| `_fallback` | 5 | ничего (отложенно → `logger`) |
| `observability_declarations` | 4 | ничего |
| `message_module` | 3 | `data_schema` |
| `config_module` | 3 | `base_manager`, `data_schema`, `logger` |
| `worker_module` | 3 | `base_manager`, `data_schema` |
| `router_module` | 2 | 8 модулей + отложенно `shared_resources` |
| `dispatch`, `registers`, `console`, `shared_resources` | 2 | — |
| `chain`, `command`, `error`, `event`, `recipe`, `statistics`, `state_store`(0), `process`, `process_manager`, `telemetry_readmodel` | ≤1 | — |
| **`frontend_module`** | **0** | 7 модулей |
| **`display_module`** | **0** | **ничего** |
| **`service_module`** | **0** | **ничего** |
| **`actions_module`** | **0** | `data_schema`, `logger` |
| **`app_module`** | **0** | `process_manager` + 5 отложенно |

Самый тяжёлый потребитель — `process_module`: жёстко тянет **17 модулей** (из 29 вершин выборки:
27 каталогов + `_fallback.py` + `observability_declarations.py`).

> **Оговорка к заголовку, добавлена по ревью (M-4).** Низкий fan-in **сам по себе** ничего не
> говорит о нужности — он одинаково характеризует три разные вещи, и путать их нельзя:
>
> | Прочтение нуля | Пример | Что значит |
> |---|---|---|
> | **вершина стека** | `app_module` | верх лестницы никто не импортирует **по построению** |
> | **розетка для внешнего слоя** | `service_module` — 9 потребителей в `Services/` | ноль внутри — это его **роль**, а не сиротство |
> | **лист без потребителей внутри** | `frontend_module`, `display_module` | кандидат на пересмотр принадлежности |
> | **ноль — артефакт выборки** | `actions_module` | потребитель есть, но он **вне выборки**: корневой фасад экспортирует `ActionBus` (`__init__.py:137-143`). Добавлено ревью №2 — первая редакция таблицы молча выбросила пятый элемент, получив верный счёт неверным способом |
>
> Правило владельца «неиспользуемый путь = контракт, „нет вызывающих" ≠ „не нужен"» применяется
> здесь буквально: из пяти модулей с нулём (§2.3) на пересмотр принадлежности претендуют **два**,
> а не пять — остальные три имеют объяснение нуля, не требующее решения.

### 2.4 Внешние потребители (кто чем пользуется вне фреймворка)

| Модуль | Plugins | Services | prototype | backend_ctl |
|---|---|---|---|---|
| `process_module` | **144** | 14 | 13 | 5 |
| `logger_module` | 2 | **18** | **64** | 1 |
| `data_schema_module` | 3 | 8 | 13 | — |
| `frontend_module` | — | — | **63** | — |
| `state_store_module` | 1 | — | 10 | 2 |
| `registers_module` | — | — | 12 | — |
| `recipe` | — | — | 12 | — |
| `service_module` | — | 9 | 6 | — |
| `actions_module` | — | 3 | 8 | — |
| `display_module` | — | — | 7 | — |
| `app_module` | — | — | 5 | — |
| `process_manager_module` | — | — | 4 | 1 |
| `telemetry_readmodel_module` | — | — | — | 2 |

*(счёт — по файлам-импортёрам, `grimp`, тесты исключены)*

**`process_module` с 144 импортёрами из `Plugins/` — фактический публичный API конструктора.**
Контракт плагина лежит внутри модуля рантайма, вперемешку с его внутренностями.

---

## 3. Инвентарь модулей (27 из 27)

Полные карточки — в приложении Б. Здесь — сводка по осям, которые важны для решения.

### 3.1 Самостоятельность: комплект документов есть у всех

README + STATUS + DECISIONS + `tests/` + `interfaces.py` + `__all__` — **27 из 27** ✓.
Это подтверждает тезис плана layer-grouping: «цель „каждый модуль — самостоятельный пакет
с фасадом и интерфейсом" в основном уже достигнута».

Пробелы не в наличии файлов, а в их **правдивости** (§6) и в неравномерности разъёмов (§3.3).

### 3.2 Форма контракта — три разных, не одна

| Форма | Модули |
|---|---|
| **ABC** | `base_manager`, `worker`, `dispatch`, `command`, `channel_routing`, `router`, `state_store`, `shared_resources`(в `core/`), `data_schema` |
| **Protocol** (`@runtime_checkable`) | `chain`, `recipe`, `registers`, `display`, `service`, `event`, `message`, `actions` |
| **Смешанно / ре-экспорт** | `shared_resources` (верхний `interfaces.py` — чистый ре-экспорт из `core/`), `config` (`IConfigObserver` — Protocol, `IConfig`/`IConfigManager` — ABC) |

Для «идеальной архитектуры» это первый кандидат на унификацию: `Protocol` + Pure DI —
современная норма, ABC тянет наследование там, где нужна только форма.

### 3.3 Разъёмы наблюдаемости — семь разных форм, не одна

Это главная находка инвентаря по отношению к цели «каждый модуль имеет разъёмы на
логирование, телеметрию, ошибки, статистику».

| Способ | Кто так делает |
|---|---|
| **`BaseManager` + `ObservableMixin`** (штатный) | `config.ConfigManager`, `worker`(`auto_proxy=True`), `chain`, `state_store` (manager/proxy), `registers`, `dispatch.Dispatcher`, `command.CommandManager`, `channel_routing`, `router`, `shared_resources` (SRM/QueueRegistry/EventManager), **`statistics`** (`stats_manager.py:110` — `class StatsManager(ChannelRoutingManager, IStatsManager)`; клетка была неполна с первой редакции, добавлено ревью №3) |
| **Прямой `get_std_logger(__name__)`** мимо разъёма | `config.Config`, `state_store.persistence`, `recipe.RecipeEngine`, `actions` (3 файла), `event_module`, `router.frame_shm_middleware`, `shared_resources` (2 файла) |
| **DI-логгер уткой** (`logger: Any\|None`, duck-typed `log_info/...`) | `recipe.RecipeManager` |
| **Опциональный логгер, иначе молча** | `display.DisplayRegistry` |
| **Декларативный разъём в КОНТРАКТЕ** ⭐ | `dispatch_module/interfaces.py:11,28`, `command_module/interfaces.py:11,33`, `statistics_module/interfaces.py:13,34` — `LOG_SOURCE = declare_log_source(...)` прямо в файле контракта |
| **stdlib `logging.getLogger`** — мимо разъёма И мимо `get_std_logger` | `data_schema_module/registry/discovery.py:26`, `registry/process_registry.py:43` |
| **Никак** | `service_module`, `message_module` |

> **Исправлено по ревью (блокер Б-1).** Первая редакция ставила `data_schema_module` в клетку
> «Никак» и не выделяла декларативную форму в отдельную. Обе правки существенны: первая — потому
> что stdlib-логгер **хуже** отсутствия разъёма (записи уходят в root `logging`, невидимые
> конвейеру фреймворка — прямое нарушение правила «один пишущий логгер»); вторая — потому что
> меняет ответ на главный вопрос пересмотра, см. ниже.

**Декларативная форма — это прототип ответа, а не ещё один способ.** *(Формы ниже называются
по имени, а не по номеру: ревью №3 поймало, что нумерация в прозе разошлась с порядком строк
таблицы и читатель, считающий строки, получал бессмыслицу.)* `declare_log_source` объявляется
**в файле контракта модуля**, а не наследуется миксином: модуль декларирует, чем он является
как источник наблюдаемости, и не импортирует логгер. Парная механика для метрик тоже уже
существует и уже отдана прикладному слою: `declare_metric` — метод `PluginContext`
([`plugins/base.py:644`](../../multiprocess_framework/modules/process_module/plugins/base.py#L644)),
плагины зовут его как `ctx.declare_metric(имя)` рядом с вычислением метрики.

**Но прототипом закрыта только половина, и это принципиально** (уточнено ревью №2). Реализация
`declare_log_source` ([`observability_declarations.py:90-170`](../../multiprocess_framework/modules/observability_declarations.py#L90))
даёт **имя источника + правило-дефолт + каталог + отказ при конфликте владельцев + предупреждение
о позднем правиле** (`:118-127`). Она **не даёт транспорт записи**: все три объявляющих модуля
пишут логи по-прежнему через ветку `BaseManager`/`ObservableMixin` — `dispatch` и `command`
напрямую, `statistics` — через наследование `ChannelRoutingManager` (`stats_manager.py:110`).

Отсюда точная постановка для §8 Q5: **декларативная половина разъёма прототипирована
(«чем я являюсь как источник»), половина доставки («как писать, не наследуя `BaseManager`») —
нет.** Именно вторая половина и есть вопрос. Плюс охват: три модуля из 27, а сам
`observability_declarations` живёт файлом на верхнем уровне `modules/` без яруса (§7).

Отдельно: `service_module.discover()` копит отказы в `DiscoveryResult.failed` и **никуда их
не логирует** — класс «проглоченный сбой», уже известный по треку наблюдаемости.

**Про телеметрию и статистику как часть контракта** (переписано по ревью №2 — прежняя редакция
утверждала, будто модульного аналога `declare_metric` не существует; **это было ложью**, внесённой
самой же правкой раунда 1). Факт: `declare_metric` применяется и на уровне модуля фреймворка —
`process_module/heartbeat/process_heartbeat.py:21` (`METRIC_SHM`) и `heartbeat/telemetry.py:39-42`
(`fps`, `latency_ms`, `effective_hz`, `cycle_duration_ms`).

Что верно: разъём **логирования** в той или иной форме есть почти у всех, включая
`Protocol`-модули (`event` — `get_std_logger`, `recipe` — DI-утка, `display` — опциональный
логгер, `actions` — `get_std_logger`). Что действительно отсутствует — **равномерность**: обе
декларативные механики (`declare_log_source`, `declare_metric`) применены точечно, там, где автор
о них знал, а не как часть контракта модуля.

Ещё один жилец, не попавший в таблицу (найден ревью №2):
`state_store_module/middleware/logging_mw.py:46` — DI-логгер с дефолтом
`logging.getLogger("state_store.changes")`, то есть гибрид третьей и седьмой форм.

### 3.4 Внешние зависимости — где течёт домен

| Модуль | Зависимость | Замечание |
|---|---|---|
| `frontend_module` | **PySide6** | 26 файлов из 27 Qt-импортов всего фреймворка |
| `shared_resources_module` | **numpy** (top-level, `memory/core/manager.py`, `memory/format/buffer.py`) | единственный core-модуль с numpy в проде — vision-семантика в «чистом» IPC-слое |
| `chain_module` | numpy (`ChainResult.masks/contours`) | движок конвейеров знает про маски и контуры |
| `state_store`, `recipe`, `display` | PyYAML | у `recipe` — жёстко, у `display` — жёстко |
| `data_schema`, `message` | pydantic | ожидаемо |
| `config` | `watchdog` (lazy, опционально) | |

---

## 4. `frontend_module` изнутри

- **298 `.py`** — 22 % фреймворка (1370 файлов всего).
- **Весь Qt-код фреймворка внутри него**: файлов с настоящими Qt-импортами — **26, все здесь**
  (уточнено по ревью; прежняя формулировка «26 из 27» была невоспроизводима — 27-м считался
  фрагмент кода в `state_store_module/DECISIONS.md`, а документ не может быть файлом с импортом).
  Строка `PySide6` встречается ещё в ~15 файлах — в докстрингах и комментариях.
- **fan-in = 0.** Реальных `import`/`from` на `frontend_module` в продакшн-коде фреймворка —
  **ноль**. Шесть найденных вхождений строки — докстринги и комментарии, причём один из них
  явный отказ от импорта: `actions_module/builder.py` — «локальный Protocol вместо импорта
  `frontend_module.schemas.register_binding` — `actions_module` не должен знать про
  `frontend_module` (ADR-124)». Есть **контракт-тест**, стерегущий это:
  `modules/tests/test_module_tiers.py::test_frozen_frontend_flagship_has_no_consumers`.
- Сам импортирует **жёстко 7 модулей**: `base_manager`, `data_schema`, `event`, `logger`,
  `message`, `registers`, `telemetry_readmodel`; плюс `actions` — **только под `TYPE_CHECKING`**
  (`forms/form_context.py:16-17`). Различие возвращено по ревью №2: для плана выноса жёсткая
  зависимость и type-only — разные вещи. **Не** импортирует почти всю рантайм-сторону: `process`,
  `process_manager`, `app`, `router`, `statistics`, `error`, `console`, `state_store`, `chain`,
  `shared_resources`, `worker`, `channel_routing`, `config`.
- Потребители: **`multiprocess_prototype` — 63 файла** (grimp, импорт-рёбра, тесты исключены —
  то же число, что в §2.4). Ревью №2 сняло прежние «97»: это был счёт файлов, содержащих
  **строку** `frontend_module`, включая тесты и докстринги — та самая категориальная ошибка,
  которую документ исправлял двумя абзацами выше. Без тестов импорт-строк — 68.
  `Services` — 0; `Plugins` — 0; `backend_ctl` — 0.

**Лист графа симметрично в обе стороны:** он не тянет рантайм фреймворка, и фреймворк не
тянет его.

### 4.1 Qt-free ядро существует и оно немаленькое

Файлов с настоящими Qt-импортами — **26 из 298**, из них **6 продовых**: `core/qt_imports.py`,
`debug/ui_event_tap.py`, `qt_event_bridge.py`, `state/telemetry_poller.py`,
`state/telemetry_view_model.py`, `widgets/telemetry_chart.py`; остальные 20 — тесты.

> Исправлено ревью №2: прежние «12 файлов» не воспроизводились ни одним правилом счёта, а
> формулировка «`qt_imports.py` — единственная точка прямого импорта» **ложна как записана** —
> пять продовых файлов импортируют PySide6 напрямую. Верная формулировка (третья итерация, две
> предыдущие ревью забраковало): воронка единственная **для `components/`**; в `widgets/` ровно
> одно исключение — `widgets/telemetry_chart.py`, и оно есть в списке шести выше.

Косвенно Qt-зависима примерно треть модуля, сосредоточенная в `*view.py`, доменных `widgets/`,
`application/` и `debug/`.

| Папка | Файлов | Qt-зависимых | Что это |
|---|---:|---:|---|
| `components/` | 103 | 22 (21 %) | примитивы контролов; у шести «полных» компонентов MVP-пятёрка `config`+`defaults`+`facade`+`presenter`+`registers` — **вся Qt-free**, Qt только в `view.py` |
| `widgets/` | 78 | 49 (63 %) | составной UI поверх components |
| `core/` | 16 | 6 (38 %) | воронка `qt_imports.py`; Qt-free: `app_context`, `app_identity`, `registers_bridge`, `routed_command`, `schema_config` |
| `managers/` | 8 | 1 (13 %) | Qt только `ThemeManager` (QSS); остальное — Python+YAML |
| `bridge/` | 8 | 2 (25 %) | Qt-free: `command_validator`, `diff_engine`, `plugin_register_resolver`, `system_commands`, `wire_protocol` |
| `graph/` | 3 | **0** | математика раскладки DAG — полностью Qt-free, сама не рисует |
| `state/` | 4 | 2 (50 %) | `TelemetryViewModel`/`Poller` — тонкая Qt-обёртка над Qt-free `telemetry_readmodel_module`; `TelemetryHistorySource` Qt-free |
| `tabs/` | 4 | 3 (75 %) | `TabRegistry` держит фабрики (Qt), `TabSpec` — Qt-free dataclass |
| `schemas/` | 4 | **0** | живой `register_binding.py` + два Gen-1 legacy |
| `configs/` | 4 | 0 | **целиком Gen-1 legacy, 0 потребителей** |
| `application/` | 5 | 4 (80 %) | **Gen-1 LEGACY, frozen 2026-07-18, 0 внешних потребителей** |

### 4.2 Прецедент уже работает

`backend_ctl` — headless-драйвер — **не импортирует `frontend_module` вообще**, а ходит
напрямую в Qt-free `telemetry_readmodel_module`, минуя Qt-обёртку. То есть модель «Qt-free
ядро + тонкая Qt-обёртка сверху» в репозитории уже доказана на живом потребителе, а не
предложена в теории. `telemetry_readmodel_module` — эталон: ноль зависимостей от фреймворка,
ноль внешних библиотек, потребляется и GUI, и headless.

### 4.3 Вынос — операция с чек-листом, а НЕ переименование

> **Исправлено по ревью (блокер Б-2).** Первая редакция заключала «вынос — переименование, не
> операция». Это неверно: `fan_in = 0` меряет **одну** ось связи из шести. Вывод был сделан по
> одной оси и подан как вывод по данным — ровно тот дефект, который §1 объявляет главным.

| Связь помимо импортов | Якорь | Почему это работа |
|---|---|---|
| **Qt — безусловная зависимость корня** | `pyproject.toml:16` — `pyside6>=6.8,<6.11`, плюс `QDarkStyle`, `NodeGraphQt` (git-форк), `Qt.py` | «Qt-free сегодня» верно про **импорты** и неверно про **дистрибутив**: `pip install` фреймворка сегодня тянет Qt. Разрез зависимостей — и есть операция |
| Контракт-тест яруса | `modules/tests/test_module_tiers.py:149-158` ищет строку `frontend_module.application`; `:304-331` — страж сборки прибит к пути прототипа | тесты и `MODULE_TIERS.md` переписываются вместе с переездом |
| Линтер прибит к путям | `pyproject.toml:350-351` — ruff per-file-ignores на `frontend_module/widgets/...` | |
| Env-контракт продублирован по обе стороны границы | `base_manager/utils/app_identity.py:10,25` — `MPF_APP_NAME` «общая с `frontend_module.core.app_identity`» | после разреза логика живёт в двух пакетах |
| Байт-в-байт контракт конвертов | `message_module/builders/command_envelopes.py:6` — совпадение GUI и `backend_ctl` | держится дисциплиной, не импортом |
| Половина фичи по каждую сторону | `data_schema_module/core/descriptor_meta.py:13-25` — декларативный API регистров канонически завершается классами `frontend_module/components/*/registers.py` | |
| 63 сайта импорта в прототипе | §2.4 | codemod |

**Заключение по данным (исправленное):** весь Qt-**код** фреймворка действительно внутри
`frontend_module`, и это делает вынос возможным. Но операция включает разрез зависимостей
`pyproject`, переписывание двух контракт-тестов, ruff-конфига, env-контракта и codemod 63 сайтов.
Доказательством «фреймворк Qt-free» может быть только **запуск** установки без Qt — сегодня
такой проверки не существует, потому что `pyside6` объявлен безусловно.

Форма выноса, которую подсказывают данные §4.1 — не «целиком», а **расщепление**: Qt-free часть
(`graph/`, MVP-половины компонентов, большая часть `bridge/` и `managers/`, `TabSpec`,
`register_binding`) — generic-механика той же природы, что `telemetry_readmodel_module`. Плюс два
куска на отдельное решение: `application/` и `configs/` — Gen-1, ноль потребителей, стережётся
контракт-тестом (правило владельца — FREEZE, не KILL).

---

## 5. Services и Plugins

13 сервисов, 52 плагина в 11 категориях + библиотека `_shared`.

Из графа: `Services/` опирается на `logger`(18), `process`(14), `service`(9), `data_schema`(8),
`actions`(3), `router`(1). `Plugins/` — почти исключительно на `process_module` (**144**
импортёра), плюс `data_schema`(3), `logger`(2), `message`(1), `state_store`(1).

### 5.1 Формальное различие «сервис vs плагин» — по коду, не по документам

| Ось | Плагин | Сервис |
|---|---|---|
| Базовый контракт | `ProcessModulePlugin` — **ABC** ([`base.py:1087`](../../multiprocess_framework/modules/process_module/plugins/base.py#L1087)) | `IService` — **Protocol** ([`service_module/interfaces.py:46`](../../multiprocess_framework/modules/service_module/interfaces.py#L46)) |
| Что в контракте | state machine `IDLE→READY→RUNNING→PAUSED→STOPPED`, типизированные порты `inputs`/`outputs`, `commands`, манифест `VERSION`/`API_VERSION`/`REQUIRES` (проверяется на boot до `configure()`) | три члена: `name`, `start(config)`, `stop()`, `get_status()`. Ни портов, ни DAG, ни команд, ни манифеста |
| Регистрация | `@register_plugin(name, category, …)` → `PluginRegistry` | `@register_service(name=…)` → отдельный `ServiceRegistry` |
| Discovery | `plugin_paths: ["Plugins", "Services"]` | `service_paths: ["Services"]` |
| Упаковка | лист из 2–4 файлов (`plugin.py`+`config.py`[+`registers.py`][+`tests/`]) | мини-пакет: README+STATUS+`interfaces.py`+часто DECISIONS+`core/`/`sdk/`+CLI+`tests/` |

**Ключевая находка: `plugin_paths` включает `Services`** ([`system.yaml:194-196`](../../multiprocess_prototype/backend/config/system.yaml#L194)).
Сканер плагинов индексирует дерево сервисов **наравне** с деревом плагинов. Отсюда:
**«лежать в `Services/` ≠ быть сервисом»** — папка и контракт это две независимые оси.

Пять плагинов физически живут внутри `Services/`: `modbus`, `hikvision_camera`,
`ml_inference`, `control_panel`, `phone_gateway` — все зарегистрированы как
`ProcessModulePlugin` ровно так же, как 52 плагина в `Plugins/`.

### 5.2 Пограничные случаи существуют в обе стороны

| Случай | Кто | Признак |
|---|---|---|
| **По факту плагин, лежит в `Services/`** | `control_panel`, `phone_gateway` | нет `service.py`/`@register_service`; **отсутствуют в собственной таблице `Services/STATUS.md`**; ровно один внешний потребитель — своя же GUI-панель; внутри ровно один плагин. Структурно неотличимы от листа `Plugins/<cat>/<name>/` |
| **И сервис, и плагин одновременно** | `hikvision_camera`, `modbus`, `ml_inference` | зарегистрированы двумя разными декораторами, обе ипостаси в одной папке |
| **Сервис зарегистрирован, но пассивен** | `robot_comm`, `vfd_comm` | `service.py` — «только карточка каталога, соединение НЕ открывает» (дословно в README); живым соединением владеет `device_hub` |
| **Сервис без карточки, но настоящий** | `device_hub`, `documents` | нет `@register_service`, но многократно переиспользуются и присутствуют в `Services/STATUS.md` |
| **Чистый сервис без байта pipeline** | `auth` | нет `plugin/` вовсе, ноль присутствия в DAG |

Отсюда рабочий критерий, выведенный из данных: сам факт «нет `IService`» **не** признак —
надёжнее пара «отсутствует в `Services/STATUS.md`» + «единственный потребитель». Она
срабатывает ровно на `control_panel` и `phone_gateway`.

**Направление импортов подтверждено эмпирически:** обратных `Services → Plugins` не найдено
ни разу. Но правило «плагины ходят через публичный API сервиса» соблюдается **не строго**
(список уточнён ревью №2 — прежний пример был неверен):

| Обход фасада | Якорь | Статус |
|---|---|---|
| `Plugins/hub/device_hub` → `Services.hikvision_camera.core.discovery` | `plugin.py:857` | **прод** |
| `Plugins/sources/camera_service` → четыре `core`-подмодуля `hikvision_camera` | `backends/hikvision.py:17-20` | **прод** |
| `Plugins/io/robot_draw` → `Services.robot_comm.core.datatypes` | `plugin.py:200,206,216` | прод |
| `Plugins/hub/device_hub` → `Services.device_hub.manager`, `…registry.store` | `plugin.py:36-37` | **прод**, и особенно показательно: фасад **экспортирует** оба символа (`Services/device_hub/__init__.py:20-21,37`) — то есть обход не вынужденный |
| `Plugins/sinks/modbus_sink` → `Services.modbus.sdk.datatypes` | `plugin.py:30` | **прод**, строкой ниже фасадного `:29`; фасад `datatypes` не ре-экспортирует |
| ~~`Plugins/sinks/modbus_sink` → `Services.modbus.core.config`~~ | `tests/test_plugin.py:8-9` | **только тесты**. Прежняя редакция писала «прод идёт через фасад» — верно про `:29` и скрывало глубокий импорт на `:30` (строка выше) |
| погранично: `Plugins/control/robot_control` → `Services.documents.interfaces` | `plugin.py:42` | глубокий путь, но `interfaces` — **контрактный** файл сервиса. Обходом считать спорно; названо, чтобы правило потом различало «внутренности» и «контракт» |

*Три строки добавлены ревью №3 — таблица была неполна и в прод-части.*

### 5.3 Папка ≠ категория: расхождение у 9 из 52 плагинов

Канонический список категорий (`process_module/plugins/manifest.py`, `PluginCategory`) —
11 имён, 1:1 с папками. Но физическая папка (ADR-123) и `category=` в `@register_plugin` —
две независимые оси, разошедшиеся минимум девять раз.

Часть лечится централизованно: `CATEGORY_LEGACY_ALIASES = {"rendering": "render",
"output": "sink"}` (`manifest.py:99-102`). Но алиас чинит **имя**, не папку: `database`,
`frame_saver`, `telemetry_sink` лежат в `Plugins/io/`, тогда как в `Plugins/sinks/` живёт
только `modbus_sink`. Шесть плагинов не покрыты алиасами вовсе: `robot_control`
(control→processing), `chain_executor` и `worker_pool` (runtime→processing),
`render_overlay` и `renderer_compositor` (render→processing), `heartbeat` (sources→utility).

### 5.4 Наблюдаемость Services/Plugins — четыре яруса

Единого сквозного разъёма нет. Ярус определяется **не** тем, `Services` это или `Plugins`,
а тем, находится ли файл внутри жизненного цикла процесса.

| Ярус | Механизм | Что даёт | Кто |
|---|---|---|---|
| **A** | наследование `ObservableMixin` | логи + ошибки + stats | `auth` (3 файла), `sql.SQLManager`, `device_hub.DeviceManager`, **`device_hub/drivers/base.py`** — `class BaseDeviceDriver(BaseManager, ObservableMixin)` (`:33`); перенесён из яруса C по ревью №2 (у него есть и модульный логгер на `:30`, но разъём — полный) |
| **B** | фасад `PluginContext` | логи + `health.report_error` + `write_document` + `record_metric/gauge/timing/histogram` | все 52 плагина `Plugins/*` + 5 плагинов внутри `Services/` |
| **C** | голый `get_std_logger(__name__)` | **только текст** | `modbus` (sdk/core), `hikvision_camera/sdk`, `ml_inference` (engine/core/backends), `ml_train` (4 файла), `dataset_gen/core/realcut.py`. *(`device_hub/drivers/base.py` отсюда удалён ревью №3 — перенос в ярус A был сделан наполовину: добавлен туда, но не убран отсюда. Прочие жильцы яруса C проверены на тот же класс ошибки — `ObservableMixin` в `Services/` встречается только у `auth`, `device_hub`, `sql`; ложных «C» больше нет.)* |
| **D** | **ничего** | отказ выражается только `bool`/исключением | `robot_comm/core/client.py`, `vfd_comm/core/client.py`, `documents/{store,wiring}.py`, весь `phone_gateway/*` кроме `plugin/`, `control_panel/controls.py`, `auth/security/permissions.py` |

Ярусы A и B физически бьют в один и тот же сток (`ctx.log_*` внутри дергает
`services.log_info`, а `services` — тот же `ProcessModule` на `ObservableMixin`), то есть
различие между ними — способ доставки, не назначение.

**Ярус D — это и есть цель владельца «каждый модуль имеет разъёмы».** Сегодня клиент робота
и клиент ПЧ — два узла, ближайших к железу, где отказ вероятнее всего, — не имеют канала
диагностики вообще.

Отдельно: `Services/auth/audit_writer.py` — два голых `print()` как последний рубеж, когда
отказали и SQLite, и JSONL. Это осознанный last-resort, не забытый вызов.

### 5.5 Прочее по сервисам

- `Services/STATUS.md` перечисляет **11 из 13** — нет `control_panel` и `phone_gateway`
  (те же двое, что по §5.2 и не сервисы).
- `device_hub` — **единственный сервис без `interfaces.py`**, при том что собственное правило
  слоя требует его у каждого.
- Qt в `Services/` ровно одно место: `hikvision_camera/sdk_app` (debug-GUI, опционально).
- `Plugins/processing` (29 плагинов, крупнейшая категория) — единственная с **нулевым**
  импортом `Services.*`.
- `Plugins/runtime` (`chain_executor`, `worker_pool`) — единственная, где плагин рантаймово
  инстанцирует другой плагин через `importlib` по `plugin_class` из конфига. Это динамическая
  дорога, которой AST-граф §2 не видит.

---

## 6. Документы, разошедшиеся с кодом

Найдено при сверке README/STATUS с фактическим кодом. Все — класс «документ уверенно
утверждает то, чего нет», тот самый, который мерило 5 трека наблюдаемости обязано было
закрыть.

| # | Где | Что заявлено | Что в коде |
|---|---|---|---|
| Д-1 | `channel_routing_module/__init__.py:30` + README «Зависимости» | «зависит от `dispatch_module` (Dispatcher, DispatchStrategy)»; «Нет циклов: channel_routing → dispatch → base_manager» | key-based путь снесён целиком в **Ф4.6 (2026-08-05)**; импорта нет. Подтверждено дважды: grep читателя и независимый AST-граф |
| Д-2 | `data_schema_module/STATUS.md`, таблица зависимостей | «`config_module` использует `StorageManager`, `DataConverter`» | **ложно наполовину** (уточнено по ревью): `StorageManager` удалён, 0 импортов (`config_module/core/config_manager.py:10`); а `DataConverter` **используется до сих пор**, лениво — `tools/loader.py:77`, `tools/watcher.py:113`. Первая редакция опровергала оба имени и вводила в заблуждение симметрично источнику |
| Д-3 | `state_store_module/README.md` §Зависимости | «зависит **только** от stdlib+pyyaml, PySide6(опц.), `base_manager`» | плюс **eager** `recipe.RecipeEngine` и **eager** `logger_module.get_std_logger` — оба отсутствуют в «исчерпывающем» списке |
| Д-4 | `event_module/STATUS.md:21-23` | «Внешние зависимости: нет, только stdlib. Самодостаточный модуль» | `event_bus.py:22` импортирует `logger_module.get_std_logger` |
| Д-5 | `worker_module` README ↔ STATUS ↔ **код** | README:3 — «49/49»; STATUS:5,14 — «62/62» | фактический счёт `def test_` в `worker_module/tests/` — **71**. Расходятся не только два документа между собой, но и **оба с кодом** (усилено по ревью) |
| Д-6 | `actions_module` README + STATUS | не упомянут `ActionBus.set_pre_execute_hook()` | рабочий RBAC-гейт исполнения, 10 тестов (`tests/test_pre_execute_hook.py`) — **недокументированная поверхность контроля доступа** |
| Д-7 | `plans/framework-layer-grouping/plan.md` шапка | «план не знает про `telemetry_readmodel_module`» | целевая структура плана его уже содержит (строка 131). Предупреждение устарело |
| Д-8 | тот же план — **внутреннее** расхождение (переформулировано по ревью) | аналитическая секция `:86` в настоящем времени: «настоящих runtime-циклов ровно 2» | циклов нет (§2.1). Но **план знает о закрытии** — свой же чек-лист `:307-309` несёт `[x]` с хешами `92c19f2e`/`d9dddf45`, `:450` — «разорваны». То есть дефект не «план утверждает то, чего нет», а «аналитическая секция не синхронизирована с собственным чек-листом». Первая редакция цитировала одну половину источника — приём того же класса, который этот документ критикует |
| **Д-9** | README **`logger_module` И `error_module`** — диаграмма наследования в обоих | `ChannelRoutingManager → LoggerManager → ErrorManager`, то есть `ErrorManager` как **подкласс** `LoggerManager` | `error_manager.py:178` — `class ErrorManager(LoggerCore, IErrorManager)`; `logger_manager.py:28` — `class LoggerManager(LoggerCore)`. Это **братья** под общим `LoggerCore`, не родитель-потомок (Task 5.14, CRM-развязка). Отягчает то, что `LoggerCore` не входит в `__all__` ни одного из модулей — README-диаграмма единственное место, объясняющее связь читателю, и она неверна **дважды** |
| Д-10 | `Services/STATUS.md` | таблица слоя перечисляет сервисы | в ней **11 из 13**: нет `control_panel` и `phone_gateway` (§5.2 — те же двое, что по факту не сервисы) |
| Д-11 | `Services/STATUS.md` правило | «у каждого сервиса: `__init__.py`, `interfaces.py`, `STATUS.md`, `README.md`, `tests/`» | `device_hub` — **без `interfaces.py`**, единственное нарушение |
| Д-12 | `process_module/STATUS.md` | «Циклические зависимости: ✓ устранены» | верно **только благодаря ленивости**: `process → process_manager` живёт в `__getattr__` (PEP 562), обратное `process_manager → process` — eager (`ProcessManagerProcess` наследует `ProcessModule`). Инструмент, не различающий lazy и eager, отрапортует пару как цикл. Утверждение верное, но его условие не названо |

---

## 7. Числа, устаревшие в плане layer-grouping

| Величина | В плане (2026-07-26) | Сегодня (2026-08-17) | Δ |
|---|---|---|---|
| Файлов с `multiprocess_framework.modules.` | 910 | **1202** | +32 % |
| Сайтов импорта | ~1970 | пересчитать dry-run'ом codemod | — |
| Модулей | 27 | 27 | — |
| Не-модульных обитателей `modules/` | 5 (`_fallback.py`, `conftest.py`, `pytest.ini`, `logs/`, `__init__.py`) | **7** (+ `observability_declarations.py`, `tests/`) | +2 |
| Import-time циклов | 2 | **0** | закрыты |
| Тиров | ~7 | **9** (0–8) | — |

`observability_declarations.py` — не мелочь: fan-in 4, его импортируют `dispatch`, `command`,
`statistics`, `process`. Живёт файлом на верхнем уровне `modules/`, слоя у него в плане нет.

---

## 8. Открытые вопросы к пересмотру плана

Не решения — вопросы, на которые план обязан ответить явно:

1. **Где место `frontend_module`.** Отдельный peer-пакет (`multiprocess_frontend/`, extras `[gui]`)
   или `Services/frontend/`. Довод против `Services/`: там доменные адаптеры (sql, modbus,
   камера), а это второй фреймворк.
2. **Что делать с двумя модулями нулевого fan-in, у которых ноль ничем не объяснён** —
   `frontend_module` и `display_module`. Остальные три из пятёрки закрыты объяснением (§2.3):
   `app` — вершина стека, `service` — розетка для слоя `Services/`, `actions` — артефакт выборки
   (потребитель через фасад). *Формулировка сужена по ревью №2: прежняя ставила решение по всем
   пяти и противоречила собственной оговорке §2.3.*
3. **`display_module` — модуль или часть `shared_resources`.** 3 файла кода, fan-in 0,
   импортирует ничего, потребители — только прототип.
4. **`process_module` как публичный API.** 144 импортёра из `Plugins/`. Нужен ли отдельный
   контрактный фасад плагинов, отделённый от внутренностей рантайма.
5. **Единый разъём наблюдаемости — достроить вторую половину.** Сегодня форм семь (§3.3).
   Декларативная половина уже прототипирована: `declare_log_source`/`declare_metric` описывают,
   **чем модуль является как источник**. Отсутствует половина **доставки**: как модуль пишет,
   не наследуя `BaseManager`. Вопрос — каким протоколом выразить именно её.
   *Переформулирован по ревью №2: прежняя редакция утверждала «у Protocol-модулей нет ни одной
   формы», что опровергается таблицей §3.3 в том же документе.*
6. **`numpy` в `shared_resources_module`.** Разрешён ли на этом ярусе, или vision-семантику
   надо вынести.
7. **ABC или Protocol** как единая форма контракта (§3.2).
8. **`backend_ctl`** — слой `tooling/` во фреймворке (как решено в layer-grouping) или сервис.
9. **Порядок относительно codemod.** Каждая перестановка модулей — это тот же freeze-окно;
   имеет смысл делать пересмотр и codemod **одним заходом**, а не двумя.
10. **Расщепить `frontend_module` или вынести целиком** (§4.1). Внутри есть настоящее Qt-free
    ядро; прецедент `telemetry_readmodel` + `backend_ctl` показывает, что расщепление работает.
11. **Что делать с Gen-1** (`application/`, `configs/` — 9 файлов, 0 потребителей, стережётся
    контракт-тестом). Удалять или морозить дальше. Правило владельца — FREEZE, не KILL.
12. **`Services/` — папка или контракт.** Сегодня `plugin_paths` включает `Services`, и пять
    плагинов живут внутри сервисов (§5.1). Либо папка перестаёт что-либо значить, либо правило
    формализуется.
13. **`control_panel` и `phone_gateway`** — вернуть в `Plugins/` или оставить с записью причины
    (§5.2). Сейчас они не сервисы ни по одному признаку.
14. **Ярус D наблюдаемости** (§5.4): `robot_comm/core/client.py` и `vfd_comm/core/client.py` —
    узлы, ближайшие к железу, — без канала диагностики. Это и есть цель «разъёмы у всех».
15. **Папка ≠ категория у 9 из 52 плагинов** (§5.3). Выровнять или объявить оси независимыми.
16. **Динамические дороги, которых AST-граф не видит:** `Plugins/runtime` инстанцирует плагины
    через `importlib` по `plugin_class` из конфига; `Services/documents` подключается строкой
    `factory` из `system.yaml`. Гейт слоёв на статических импортах их не покроет.

### Добавлено по ревью (Fable, «чего не хватает»)

17. **Судьба корневого фасада** (§2.0). Что исполняет `import multiprocess_framework`; кому фасад
    принадлежит после перегруппировки; почему ленивость, применённая к PySide6 ради памяти при
    спавне 8 процессов, не применена к остальным ~20 жёстким импортам.
18. **Строковый граф связей.** Codemod считает import-сайты. Переезд обязан переписать и строковые
    пути в blueprint'ах, конфигах и реестре плагинов (`blueprint.py:849`, `class_loader.py:27`,
    `plugins/registry.py:200`, `observability_wiring.py:905`, `scanner.py:131`) плюс
    персистированные рецепты. **Иначе рантайм ломается при зелёных импортах** — главный риск
    именно снятия суффикса `_module`, а не перестановки папок.
19. **Версионирование контрактов между слоями.** `version.py` даёт версию кода. Нет политики
    совместимости манифеста плагинов и semver публичного API `process_module` — а у него
    **144 импортёра** из `Plugins/`. Фасад плагинов (Q4) без политики совместимости — полдела.
20. **Граница дистрибутива.** Один корневой `pyproject` на framework+Services+Plugins+prototype;
    `pyside6` и git-зависимость `NodeGraphQt` объявлены **безусловно** (`pyproject.toml:16,134`).
    Что ставится при сборке второго приложения; какие extras за пределами `[gui]`.
21. **Тестируемость модуля в изоляции.** Гоняется ли `pytest modules/X` сам по себе. Связано с
    известным долгом: корневой гейт не собирает тесты модулей фреймворка (из 82 новых дошли 6).
22. **Бюджет стоимости запуска.** Спавн 8 процессов × полный фасад — числом, не прилагательным.
23. **Путь второго приложения.** Каков минимальный вход для приложения №2 — `app_module`,
    blueprint, фасад? Без этого вопроса цель «универсальный конструктор» не проверяется вообще.
24. *(поглощён Q5 — см. переформулировку выше. Строка оставлена, чтобы нумерация не сдвинулась:
    в раунде 2 выяснилось, что Q24 объявлял Q5 переформулированным, когда Q5 ещё не был тронут.)*
25. **Qt-смежный, но Qt-free код.** `GuiStateProxy` экспортируется фасадом;
    `telemetry_readmodel/__init__.py:7` называет своей второй половиной
    `frontend_module.state.TelemetryViewModel`. Где этот класс кода живёт после разреза.

### Дорогие варианты — вопросы, снятые ограничением владельца

> Добавлено ревью №3 после того, как владелец снял ограничение: цель — лучшая архитектура,
> **«даже ценой переделок»**. Документ писался, когда экономия подразумевалась, и молча выбирал
> дешёвый вариант. Здесь дорогие варианты названы **как варианты**, а не как данность.

26. **Критерий группировки — центральный вопрос, которого в §8 не было вовсе.** Шапка объявляет
    поводом «как сгруппировать модули по смыслу», но все вопросы размещения (Q1, Q3, Q8, Q12)
    молча предполагают принцип, который **никто не выбирал**. Варианты: тиры (§2.2), домены
    (наблюдаемость / IPC / схемы / UI), жизненный цикл, границы дистрибутива. Собственный факт
    документа — «граф широкий и мелкий, большинство модулей — листья» — **подрывает** папки-слои
    плана (`plan.md:448-450`, девять слоёв): слои описывают глубину, которой в графе нет.
27. **Мульти-пакетность вместо одного `pyproject`.** Q20 спрашивает про extras — сама рамка
    предполагает один пакет. Дорогой вариант: workspace из настоящих пакетов (framework /
    frontend / services / plugins), каждый со своим `pyproject` и semver. К нему ведут три
    собственные находки: Qt безусловен в корне (`pyproject.toml:16-20`), semver для 144
    импортёров (Q19), «путь второго приложения» (Q23).
28. **Судьба корневого god-фасада — как вариант, а не как данность.** Q17 обсуждает владение и
    ленивость — оба варианта сохраняют полный-API фасад. Дорогой: **убрать** его, оставив входы
    по модулям, и переписать всех потребителей `from multiprocess_framework import X`. Довод
    готов: §2.0 — импорт одного модуля тянет 23 корня.
29. **Отставка `BaseManager`+`ObservableMixin` как «штатного» способа.** Q5 спрашивает, как писать
    тем, у кого разъёма нет. Дорогой вопрос: сделать контекст-фасад (форма B, уже обслуживает 57
    потребителей и бьёт в тот же сток) **единственным** способом для всех 27, выведя миксин из
    контрактов.
30. **Нужен ли плоский контейнер `modules/` с суффиксами вообще.** Q18 называет снятие суффикса
    риском codemod'а, но вопрос «а нужны ли контейнер и суффикс» не поставлен. Слово «модуль»
    сегодня стоит дважды — и в контейнере, и в суффиксе.
31. **Физический вынос контракта плагинов.** Q4 предлагает ре-экспорт-фасад — дешёвый вариант.
    Дорогой: вынести `plugins/base.py` + `manifest` + `context` в отдельный пакет с собственным
    semver, отделив контракт от рантайма `process_module`.
32. **UI-словарь в ядре тира 0.** `data_schema_module/core/descriptor_meta.py:55` — поле `widget`,
    «какой UI-виджет рисовать», в модуле с fan-in 17. Для numpy в `shared_resources` зеркальный
    вопрос задан (Q6), для UI-слов в схеме данных — нет. Кандидат: presentation-hints отдельной
    плоскостью от схемы.
33. **Несколько окон меньшего радиуса вместо одного большого.** Q9 сформулирован рамкой экономии
    freeze-окна («одним заходом, а не двумя»). Альтернатива — серия узких codemod'ов, каждый
    обратимый — не названа даже вопросом.

### Из ревью телеметрии (параллельный трек, 2026-08-17)

34. **У `record_metric` два противоположных смысла на одном разъёме — это семантика, а не форма.**
    В [`observability_hub.py`](../../multiprocess_framework/modules/channel_routing_module/observability/observability_hub.py)
    `record_metric` (`:177`) и `gauge` (`:186`) — **побайтно одна операция** (`_emit_stat(...,
    METRIC_GAUGE, ...)`), а counter живёт под третьим именем `increment` (`:180`). В
    `StatsManager` (`stats_manager.py:620`) то же имя означает **счётчик**. Смысл строки
    `self.record_metric("x")` определяется тем, чем сшит слот менеджера. Четвёртый глагол на той
    же поверхности — `publish_metric` («текущее значение»).
    **Следствие для Q5, важнее самого дефекта:** разъём с двусмысленным глаголом **нельзя
    «дорастить»** — рост распространит неоднозначность с трёх модулей на 27. Глаголы надо развести
    ДО расширения охвата, то есть Q5 это переделка, а не рост. Ось «семантика разъёма» документом
    до этого не мерилась вовсе — §3.3 меряет только формы доставки.
35. **Внутри `process_module` формируется безымянный модуль процессной политики наблюдаемости.**
    `managers/observability_wiring.py` — **1288** строк, `managers/observability_reload.py` —
    **1410**; вместе 2698 строк. У него уже есть предмет, размер и границы — нет имени и
    контракта. Прямая иллюстрация вопроса «что считать модулем» (Q26).

---

## 9. Журнал ревью

**Ревью №1 (2026-08-17, независимый агент, модель Fable): 6/10 при пороге 8 — НЕ принят.**

Что подтвердилось построчно: числа 1202, 144, 298/1370, `_fallback.py:91` — точно; шесть из
восьми Д-пунктов сошлись; вывод «циклов при импорте нет» **устоял** под прямой атакой (включая
проверку корневого фасада). Что не пустило выше 6:

| # | Тяжесть | Находка | Правка |
|---|---|---|---|
| Б-1 | блокер | §3.3: клетка `data_schema` = «Никак» неверна (`registry/discovery.py:26` — stdlib `logging`); пропущена **шестая форма** — декларативный `declare_log_source` в файле контракта | §3.3 переписана; шестая форма названа прототипом ответа на Q5 |
| Б-2 | блокер | §4 «вынос = переименование» неверно: `fan_in` меряет одну ось из шести; `pyside6` безусловен в `pyproject.toml:16` | добавлена §4.3 с чек-листом из шести связей |
| M-1 | major | корневой фасад молча исключён из выборки §2 — нарушено правило §1 | добавлена §2.0 |
| M-2 | major | `resolve()` теряет ребро при `from .. import X` (`frontend_module/schema_adapter.py:23`); строковый граф не заявлен как вне scope | §2.0, вторая слепая зона |
| M-3 | major | Д-8 приписывал плану вину: план знает о закрытии Фазы 2 в трёх местах | Д-8 переформулирован как внутреннее расхождение плана |
| M-4 | major | fan-in = 0 имеет три прочтения, таблица «кто ядро» их не разводит | оговорка к §2.3: на пересмотр претендуют 2 модуля, не 5 |
| minor | — | «26 из 27 файлов с PySide6» невоспроизводимо (Qt-импорты в 26 файлах, **все** внутри `frontend_module`); Д-2 срезан наполовину; Д-5 недожат (факт 71 тест); счёт модулей плавает 27/28/29 | внесены |

**Ревью №2 (2026-08-17, тот же агент, каждая правка сверена кодом заново): 7/10 — НЕ принят.**

Приняты как настоящие: чек-лист §4.3 целиком (включая `pyproject.toml:17,19,20`); §2.0 —
подтверждена **запуском**, а не чтением: `import multiprocess_framework.modules.data_schema_module`
загружает **23 корня модулей**, включая `process_manager_module`, при этом PySide6 не грузится;
Д-2, Д-5, Д-8, «26 файлов», «29 вершин», все якоря Б-1; Д-9…Д-12 построчно; §5 — точна на ~25
проверенных утверждениях, все девять расхождений папка/категория подтверждены поимённо; §4.2
принята целиком.

Что не пустило выше 7 — и внесено этой редакцией:

| # | Класс | Находка раунда 2 | Правка |
|---|---|---|---|
| 1 | **новый дефект, внесённый правкой Б-1** | «аналога `declare_metric` на уровне модуля нет» — **ложь**: `process_heartbeat.py:21`, `telemetry.py:39-42` | абзац переписан, якоря-опровержения внесены |
| 2 | перегиб | «вопрос Q5 уже отвечен в прототипе» — `declare_log_source` даёт имя+правило+каталог+гейт, но **не транспорт записи**; все три модуля пишут через `ObservableMixin` | «отвечена декларативная половина, доставки нет» |
| 3 | правка не доведена до зависимых мест | заголовок §3.3 «пять способов» при семи строках; Q5 и Q2 противоречили исправленным секциям; Q24 объявлял Q5 переформулированным, когда Q5 не был тронут; §2.1 сохранял снятое «приёмка не проводилась» | все синхронизированы |
| 4 | верный вывод неверным способом | таблица трёх прочтений нуля молча выбросила `actions_module` | добавлено четвёртое прочтение — «артефакт выборки» |
| 5 | та же категориальная ошибка, что исправлялась рядом | «97 файлов-потребителей» — счёт по **строке**, включая тесты и докстринги | 63 (grimp, без тестов), метод указан |
| 6 | потеря точности | «импортирует 8 модулей» — `actions` только под `TYPE_CHECKING` | 7 жёстко + 1 TC |
| 7 | новые неверные числа §4.1 | «12 файлов с прямым PySide6» невоспроизводимо; «воронка — единственная точка» ложно (5 других прод-файлов) | 26 файлов / 6 продовых, оговорка про воронку |
| 8 | ошибка §5.2 | пример `modbus_sink → Services.modbus.core.config` — **только в тестах**, прод идёт через фасад; реальный обход пропущен | таблица обходов, добавлен `device_hub/plugin.py:857` |
| 9 | ошибка §5.4 | `device_hub/drivers/base.py` в ярусе C, а он `BaseDeviceDriver(BaseManager, ObservableMixin)` (`:33`) | перенесён в ярус A |
| 10 | пропущенный жилец §3.3 | `state_store_module/middleware/logging_mw.py:46` | внесён |

**Ревью №3 (2026-08-17, тот же агент, узкое — проверка десяти правок + вопрос «что документ не
оспаривает»): 8/10 при пороге 8 — ПРИНЯТ с обязательным панч-листом.**

Из десяти правок раунда 2 **семь подтверждены кодом полностью**; три несли по одному ложному
предложению — все внесены этой редакцией:

| # | Остаток раунда 2 | Правка |
|---|---|---|
| 1 | §4.1 «воронка единственная для `widgets/` и `components/`» — ложно: `widgets/telemetry_chart.py` тремя строками выше в списке прямых импортов. **Третья подряд неверная итерация одной фразы** | «единственная для `components/`; в `widgets/` одно исключение» |
| 2 | §5.4 `drivers/base.py` оказался **в двух ярусах сразу** — добавлен в A, не удалён из C | удалён из C |
| 3 | §3.3 «все три объявляющих модуля стоят в первой строке» — для `statistics` ложно **по букве**: клетка строки 1 была неполна с первой редакции | `statistics` добавлен в клетку, фраза уточнена |
| 4 | §5.2 таблица обходов неполна и в прод-части | добавлены `device_hub/plugin.py:36-37`, `modbus_sink/plugin.py:30`, погранично — `robot_control/plugin.py:42`; якоря `robot_draw` |
| 5 | нумерация форм в прозе разошлась с порядком строк таблицы | формы называются по имени |

Отдельная находка раунда 3, весомее панч-листа: **центральный вопрос владельца — по какому
принципу группировать модули — в §8 отсутствовал вовсе**, а все вопросы размещения молча
предполагали невыбранный принцип. Плюс семь мест, где документ подавал выбор как данность,
экономя на переделках. Все внесены как Q26–Q33 после снятия владельцем ограничения «даже ценой
переделок». Q34–Q35 добавлены из параллельного ревью телеметрии.

**Текущая подтверждённая оценка — 8/10, порог взят.** Панч-лист исполнен; повторного прогона
после его внесения не было.

---

## Приложение А — скрипт замера

[`scripts/arch_graph/ast_graph.py`](../../scripts/arch_graph/ast_graph.py) — воспроизводимый замер:

```
python scripts/arch_graph/ast_graph.py <путь-отчёта.txt>
```

Классифицирует каждый импорт по AST на `hard` (верхний уровень модуля) / `lazy` (внутри
функции) / `tc` (под `if TYPE_CHECKING`), резолвит относительные импорты с различием
«пакет / обычный файл», исключает тесты, считает SCC (Тарьян), тиры и fan-in. Кладёт
текстовый отчёт и `ast_graph.json` рядом с ним.

Путь отчёта обязателен намеренно — дефолт в текущую директорию однажды уже насорил в корне
репозитория (§1: инструментальные ошибки записываются, а не заминаются).

Этим же скриптом проверяется **ацикличность доменов** — критерий приёмки Ф2 и Ф3 плана
[`framework-architecture-rework`](../../plans/framework-architecture-rework/plan.md).

## Приложение Б — карточки модулей

*(18 карточек от читателей 1–2; ещё 9 — после прихода читателя 3. Полные таблицы с
фасадами, контрактами, зависимостями и разъёмами — в отчётах агентов этой сессии.)*
