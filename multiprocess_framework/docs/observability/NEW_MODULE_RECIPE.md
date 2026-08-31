# Рецепт: подключить новый модуль к наблюдаемости

> Сверено с кодом **2026-08-10**, коммит **`fb705053`** (ветка `feat/observability-review-remediation`, фазы A–D закрыты).
> Читатель: автор нового модуля фреймворка или сервиса.
> Соседние справочники: [`CONNECTORS.md`](CONNECTORS.md) · [`SINKS_MAP.md`](SINKS_MAP.md) · [`CONTROL_PANEL.md`](CONTROL_PANEL.md)

Шесть шагов, из них обязательны первые три. В конце — **как доказать, что записи доезжают**, и
почему правок в `multiprocess_framework/` при этом ровно ноль.

---

## Шаг 1. Взять разъём

Наследник `BaseManager` получает наблюдаемость подмешиванием `ObservableMixin`; менеджер с
собственными каналами наследует `ChannelRoutingManager` (он уже и то, и другое).

```python
from multiprocess_framework.modules.base_manager import BaseManager, ObservableMixin

from .interfaces import LOG_SOURCE          # объявляется на шаге 2

class MyManager(BaseManager, ObservableMixin):
    def __init__(self, name, managers=None, **kw):
        BaseManager.__init__(self, name)
        ObservableMixin.__init__(self, managers=managers or {},
                                 source_name=LOG_SOURCE, **kw)   # ← шов, см. шаг 2

    def initialize(self) -> bool:            # ОБЯЗАТЕЛЕН — abstractmethod
        self.is_initialized = True
        return True

    def shutdown(self) -> bool:              # ОБЯЗАТЕЛЕН — abstractmethod
        self.is_initialized = False
        return True
```

**`initialize`/`shutdown` — не «по вкусу», а условие существования класса.** Оба объявлены
`@abstractmethod` в `IBaseManager`
([`base_manager/core/base_manager.py:57-67`](../../modules/base_manager/core/base_manager.py#L57)),
поэтому без них наследник не инстанцируется вовсе: `TypeError: Can't instantiate abstract class`.
Слепой автор модуля (линза S2 приёмки F1) споткнулся здесь первым же прогоном.

Слоты называются **канонично**: `logger`, `error`, `stats` (`error`, не `errors` — Task 5.14).
Внутри процесса их кладёт `process_managers.register_all`
([`process_managers.py:68`](../../modules/process_module/managers/process_managers.py#L68)), поэтому
модулю, живущему в процессе, отдельно регистрировать нечего — достаточно получить `managers` от
владельца.

Незарегистрированный слот **не роняет** вызывающего: `_call_manager` вернёт `None` и посчитает
отказ в `manager_call_failures`.

## Шаг 2. Объявить имя источника рядом с константой

[`modules/observability_declarations.py`](../../modules/observability_declarations.py). Пишется
**в `interfaces.py` модуля**, рядом с публичным API:

```python
from ..observability_declarations import declare_log_source

LOG_SOURCE = declare_log_source(
    "multiprocess_framework.modules.my_module",
    owner=__name__,
)
```

Правила, которые тут держатся:

* **имя точечное, а не короткий ярлык.** Плоское имя — лист без поддерева: правило по префиксу на
  нём не работает, и каждый новый файл модуля пришлось бы заводить в конфиге руками. Точечное даёт
  обратное — правило `multiprocess_framework.modules` действует на всё поддерево. Так же выводят
  имя логгера stdlib (`getLogger(__name__)`), logback (FQCN), .NET (`ILogger<T>`) и OTel
  (`InstrumentationScope.name`);
* **объявление активное**: имя попадает в `declared_sources()` — ответ на «что бывает» **до первой
  записи**. `seen_sources` отвечает только про тех, кто уже писал, а разбирают обычно как раз того,
  у кого всё гасится порогом;
* **два объявления одного имени — отказ на импорте**, а не выбор по порядку импортов. Повторное
  объявление тем же владельцем с тем же правилом — не конфликт (реимпорт в тестах, spawn);
* **правило-дефолт опционально** и уезжает в **L0**, то есть ПОД конфиг приложения: модуль знает
  про себя, но последнее слово за тем, кто систему собирает.

```python
from ..logger_module.configs.logger_manager_config import LoggerRuleSchema

LOG_SOURCE = declare_log_source(
    "multiprocess_framework.modules.my_module",
    owner=__name__,
    rule=LoggerRuleSchema(level="WARNING"),   # «я болтливый»
)
```

Правило обязано быть **схемой**, а не словарём: форма проверяется здесь, на границе реестра
(утиная проверка `model_dump`), потому что словарь молча доехал бы до сборки конфига и упал там без
имени виновника.

**Ленивое объявление говорит вслух.** Правило, объявленное ПОСЛЕ сборки конфига (ленивый импорт,
плагин), в уже собранные конфиги не попало — об этом сообщает `emergency_log`, и действовать оно
начнёт со следующей сборки.

## Шаг 3. Писать

```python
self._log_info("подключено")
self._log_debug(lambda: f"кадр {seq}: {len(items)} элементов")   # ОТЛОЖЕННО
self._track_error(exc, context={"stage": "decode"})
self._record_metric("frames_decoded")
self._record_timing("decode_sec", elapsed)
```

**Лямбда в `_log_debug` — правило, а не стиль**: f-строка собирается на call-site, то есть до
гейта, и никаким порогом внутри не снимается; лямбда зовётся только после гейта и ровно один раз.
Точке с постоянным текстом лямбда не нужна — собирать там нечего, и замыкание было бы чистой ценой.

**Шов, который легко пропустить: объявление имени (шаг 2) и штамп записи (шаг 3) — разные
механизмы, и связывает их ровно один аргумент.** `declare_log_source` наполняет реестр
объявлений; `module` в записи ставит `_observability_source()`
([`observable_mixin.py:112-125`](../../modules/base_manager/mixins/observable_mixin.py#L112)) по
порядку **явный `source_name` из `__init__` → `manager_name` → `"main"`**. Не передал
`source_name=LOG_SOURCE` (шаг 1) — записи поедут под именем менеджера (`my_manager`), правило
конфига по точечному префиксу на них не подействует, а проверка доставки шага «Доказательство»
прочитается как провал при исправной доставке. Ровно это произошло со слепым автором модуля
(линза S2 приёмки F1): слово `source_name` в прежней редакции рецепта не встречалось ни разу.

Явный `module=` на call-site перебивает штамп.

## Шаг 4 (по необходимости). Свой тип приёмника

Без правки `create_channel` и вообще без правки фреймворка:

```python
from multiprocess_framework.modules.logger_module.channels.log_channel import register_sink_factory

register_sink_factory("sql", MySqlChannel)   # наследник LogChannel либо любой класс с write()
```

Дальше приёмник адресуется конфигом как `{"type": "sql", ...}`. Мусор отвергается на границе
(`TypeError`), неизвестный `type` в конфиге даёт `ValueError` в `create_channel`. Подробности и
шесть встроенных типов — [`SINKS_MAP.md §1`](SINKS_MAP.md).

## Шаг 5 (по необходимости). Метрика телеметрии

```python
from ..observability_declarations import declare_metric

METRIC_FPS = declare_metric("fps", owner=__name__)
```

Зовётся **рядом с кодом, который метрику считает**: прежний кортеж-литерал `GATED_METRICS` жил в
`configs/`, на два слоя ниже вычисления, и связь «строка каталога — вот эта величина» держалась
только именем. Правила-дефолта у метрики нет намеренно: как часто её публиковать — решение того,
кто собирает систему, и живёт оно в `telemetry.publish` рецепта.

## Шаг 6 (по необходимости). Свой уровень или свой файл ошибок

Заводится конфигом через `severity_routes` — это данные, а не ветвление в коде (ADR-EM-008).
Приёмники перечисляются **в порядке предпочтения**, действует первый, который есть в реестре.

---

## Доказательство доставки

Тест не заменяет этот прогон: зелёный юнит доказывает механизм, а не проводку.

### 1. Заведи кольцо и направь в него свой источник

**Куда это класть.** Секция `observability:` живёт в конфиге **приложения**, не фреймворка: у
прототипа это [`multiprocess_prototype/backend/config/system.yaml`](../../../multiprocess_prototype/backend/config/system.yaml)
(слой L1). Своё приложение — свой файл; фреймворк прикладных имён не содержит вовсе (см. раздел
«Правок во фреймворке — 0»). Правка на живой системе, без файла — `config.reload` со слоем L3
([`CONTROL_PANEL.md §1`](CONTROL_PANEL.md)).

```yaml
observability:
  channels:
    my_ring: { type: memory, capacity: 200 }
  loggers:
    multiprocess_framework.modules.my_module:
      level: DEBUG
      channels_extra: [my_ring]
```

Ключ в `loggers` — то самое имя из `declare_log_source`, и оно попадает в запись только если
передано `source_name=LOG_SOURCE` (шаг 1). Имя менеджера сюда писать бессмысленно: правило по
префиксу работает на точечном имени.

**Ярлык на набор источников** — `logger_groups`, форма `{имя_группы: [полный_точечный_префикс, …]}`
(модель `logging.group.*` Spring Boot). Ярлык раскрывается по каждому члену при сборке дерева,
поэтому правило пишется один раз на группу, а не построчно на компонент:

```yaml
observability:
  logger_groups:
    служебное:
      - multiprocess_framework.modules.command_module
      - multiprocess_framework.modules.dispatch_module
  loggers:
    служебное:
      channels: [busy_file]        # правка одна на всю группу
```

Имя группы, не заведённое в `logger_groups`, видно в `effective.logger.unknown_scopes` (см. шаг 3
ниже) — молча оно не теряется.

`channels_extra` **добавляет** приёмник к унаследованным и накапливается по всей ветке имени;
`channels` — **замещает** список, и там побеждает самый длинный совпавший префикс. Обе оси
резолвятся независимо: `None` = «правило про эту ось молчит, наследую», `[]` = «приёмников нет, и
это решение».

### 2. Спроси хвост приёмника

```
observability.sink.tail {"sink": "my_ring", "limit": 20}
```

Кольцо — единственное место, где последние N записей достаются **ретроспективно**, без подписки и
без диска, и оно **переживает** `config.reload` и `sink.disable/enable` (живёт в процессном
реестре, а не в объекте канала).

### 3. Спроси, что видит сам процесс

```
introspect.observability {"flush": true, "resolve": "multiprocess_framework.modules.my_module"}
```

| Что смотреть | Что должно быть |
|---|---|
| `effective.logger.declared_sources` | твоё имя **есть** — объявление сработало |
| `effective.logger.sources` | твоё имя **есть** — записи действительно шли |
| `effective.logger.unknown_scopes` | твоей группы там **нет** (иначе имя группы не заведено в конфиге) |
| `effective.logger.idle_sinks` | `my_ring` там **нет** — приёмник что-то принял |
| `counters.channel_written_records` | **растёт** между двумя снимками |
| `counters.*` из пяти классов потерь | нули; ненулевое — читать поимённо ([`CONNECTORS.md §4`](CONNECTORS.md)) |
| `resolve` | какое правило и какой префикс выиграли для твоего имени. Отвечает и на имя, под которым ещё никто не писал — это вопрос-гипотеза. **Разбирает ОДНУ ось решения, а не судьбу записи**: приёмник мог быть снят оператором, а плоскость ошибок ходит своим severity-путём и иерархию не спрашивает вовсе |

`flush=true` обязателен, если судишь по приросту счётчиков: без него контрольный снимок отдаёт
ноль при реальных записях.

### 4. Убедись, что смена ручки ДЕЙСТВУЕТ, а не «принята»

```
config_reload_verified(process="<твой процесс>",
                       observability={"loggers": {"multiprocess_framework.modules.my_module": {"level": "INFO"}}})
```

`verdict=confirmed` + `delivering=true` — это два разных утверждения, и ни одно не выводится из
другого (см. [`CONTROL_PANEL.md §5`](CONTROL_PANEL.md)). `unverifiable` означает «не проверено», а
не «плохо».

---

## «Правок во фреймворке — 0»: чем это гарантировано

Не обещанием, а устройством четырёх реестров.

| Что заводится | Механизм | Что было бы иначе |
|---|---|---|
| имя источника + его правило-дефолт | `declare_log_source` — реестр наполняется **импортом самого модуля** | список в общем файле пришлось бы править при каждом добавлении модуля |
| метрика телеметрии | `declare_metric` — то же объявление, другое пространство имён (`kind`) | кортеж-литерал `GATED_METRICS` в коде фреймворка |
| тип приёмника | `register_sink_factory` | ветка в `create_channel` |
| уровень ошибок и его файл | `severity_routes` данными | лестница `if has_critical: … elif …` внутри `_setup_level_routes` |

**Прикладных имён во фреймворке нет.** `loggers` и `logger_groups` пусты по умолчанию, и это часть
контракта, а не «ещё не заполнили»: прикладные правила живут в конфиге приложения, фреймворк несёт
только механизм. Доменное имя приложения ушло из универсального слоя целиком (ADR-137, задача D4):
имя берётся из composition root (`MPF_APP_NAME`), нейтраль — `MultiprocessApp`, pid-файл называется
`<app>_system_pids.jsonl`.

**Где реестр объявлений физически лежит и почему.** [`modules/observability_declarations.py`](../../modules/observability_declarations.py)
— лист без зависимостей, рядом с `_fallback.py`, а НЕ внутри `logger_module`. Объявление зовут из
`interfaces.py` модулей, которые сам логгер и импортирует; импорт через пакет логгера замкнул бы
кольцо — воспроизведено на первой редакции (`ImportError: cannot import name
'ChannelRoutingConfig' from partially initialized module`).

---

## Чего делать не надо

* **не заводить `logging.getLogger(__name__)`** — у stdlib-root в живых процессах хендлеров не
  подключает никто, `INFO`/`DEBUG` теряются всегда, а под `pythonw` теряется вообще всё. Нужен
  stdlib-стиль — бери `get_std_logger(module)`: это **вид** над единственным писателем;
* **не заводить второй писатель на файл**: сток `DocumentStore` публикуется на процессе именно
  затем, чтобы аудит смен и прикладные вердикты шли в ОДИН экземпляр;
* **не звать `emergency_log`** из прикладного кода: он существует для случая «штатный маршрут
  сломан». Это **соглашение**: AST-страж
  [`test_std_logger_guard.py`](../../modules/logger_module/tests/test_std_logger_guard.py) считает
  другое — писателей `logging.getLogger` и `loguru` вне whitelist'а; вызовы `emergency_log` не
  считает никто (расхождение №5 приёмки F1);
* **не писать документ на каждый кадр**: `ctx.write_document` идёт синхронно в SQLite (медиана
  3.6 мс, p95 82 мс, max 928 мс под конкуренцией шести процессов) — это бюджет редкого события;
* **не полагаться на `MagicMock` в тестах разъёма**: он порождает любой атрибут, поэтому
  `ctx.log_warning.assert_called_once()` проходил и тогда, когда у реального фасада метода не было
  (блокер Б-2, задача A2). Дубль обязан **уметь отказывать** и хранить `**kwargs` — иначе свойство
  «запись пришла под именем плагина» не может проверить ни один тест в принципе.

---

## Решения

| ADR | О чём | Где |
|---|---|---|
| ADR-CRM-001, ADR-CRM-005 | паттерн CRM, две роли конфигов | [`channel_routing_module/DECISIONS.md`](../../modules/channel_routing_module/DECISIONS.md) |
| ADR-CRM-006 | точки расширения control plane | там же |
| ADR-LOG-005 | `scope` — наша группа, `module` — источник (OTel `InstrumentationScope`) | [`logger_module/DECISIONS.md`](../../modules/logger_module/DECISIONS.md) |
| ADR-LOG-010 | у порога одна ось — правило по имени источника | там же |
| ADR-EM-008 | severity-лестница живёт данными | [`error_module/DECISIONS.md`](../../modules/error_module/DECISIONS.md) |
| ADR-SM-001 | `StatsManager` — прямой наследник CRM | [`statistics_module/DECISIONS.md`](../../modules/statistics_module/DECISIONS.md) |
| ADR-PM-028, ADR-PM-029 | плоскость документов и дорога приложения в неё | [`process_module/DECISIONS.md`](../../modules/process_module/DECISIONS.md) |
| ADR-137 | фреймворк нейтрален к продукту: имя приложения из composition root | [`multiprocess_framework/DECISIONS.md`](../../DECISIONS.md) |
