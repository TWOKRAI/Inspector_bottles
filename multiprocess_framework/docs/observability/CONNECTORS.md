# Разъёмы наблюдаемости — что доступно автору модуля и автору плагина

> Сверено с кодом **2026-08-10**, коммит **`fb705053`** (ветка `feat/observability-review-remediation`, фазы A–D закрыты).
> Читатель: автор модуля фреймворка, автор плагина.
> Соседние справочники: [`NEW_MODULE_RECIPE.md`](NEW_MODULE_RECIPE.md) · [`CONTROL_PANEL.md`](CONTROL_PANEL.md) · [`SINKS_MAP.md`](SINKS_MAP.md)

Документ отвечает на один вопрос: **чем и куда пишет код, который ты пишешь**, и что при этом
обязано быть правдой. Всё, что здесь утверждается, имеет адрес в коде; утверждений без адреса
в документе нет намеренно.

---

## 1. Два разъёма, а не один

| | `ObservableMixin` | `PluginContext` |
|---|---|---|
| Кто получает | наследник `BaseManager` / любой класс, подмешавший миксин | плагин (`ProcessModulePlugin`), через `ctx` в каждом хуке |
| Адрес | [`modules/base_manager/mixins/observable_mixin.py`](../../modules/base_manager/mixins/observable_mixin.py) | [`modules/process_module/plugins/base.py`](../../modules/process_module/plugins/base.py) |
| Логи | `_log_debug/_log_info/_log_warning/_log_error/_log_critical` (+ публичные алиасы без подчёркивания) | `ctx.log_debug/log_info/log_warning/log_error/log_critical` |
| Ошибки | `_track_error(exc, context)` → слот `error` | `ctx.health.report_error(exc, context=…, throttle=…)` |
| Метрики | `_record_metric(name, value, tags)`, `_record_timing(name, sec, tags)` → слот `stats` | **разъёма нет** (см. §3, строка C1) |
| Документы | — | `ctx.write_document(kind, summary, **fields)` |
| Штамп источника | `_observability_source()`: явный `source_name` → `manager_name` → `"main"` | имя плагина, ставит `PluginContext._stamped` через `functools.partial(log_fn, module=…)` |

**Оба разъёма ведут в одни и те же три менеджера процесса.** Их регистрирует
[`process_managers.register_all`](../../modules/process_module/managers/process_managers.py) под
каноничными именами слотов `logger` / `error` / `stats` (`error`, не `errors` — Task 5.14).
`PluginContext` — фасад над `IProcessServices`, а тот вызывает те же методы миксина у процесса.

**Отсутствующий менеджер — не исключение, а тишина.** `ObservableMixin._call_manager` при
незарегистрированном или выключенном слоте возвращает `None` и считает отказ в
`manager_call_failures` — логирование не имеет права уронить того, кто логирует.

**Штамп имени: кто кого перебивает.** `module=` ставится через `setdefault`, поэтому порядок
приоритета такой: явный `module=` на call-site → имя плагина (у per-plugin копии контекста) →
имя менеджера/процесса. У плоскости ошибок имя едет **в контексте**, а не в kwargs
(`_track_error` кладёт `ctx["module"]`) — у слота `error` другая сигнатура, и без этой строки
заштампованной осталась бы только плоскость логов.

### `log_error` ≠ `report_error` — разница наблюдаема в файлах

Это не стилистика, а **разные плоскости** (ADR-PM-030, задача C2):

```
ctx.log_error("строка")          → плоскость логов    → system.log / messages.log
ctx.health.report_error(exc)     → плоскость ошибок   → errors.log / critical.log
                                   + дросселированная строка в журнал
                                   + счётчик health + подряд-счётчик breaker
```

До C2 (2026-08-09) второе было **названием без обязательства**: прогон
`backend_ctl/probes/probe_c2_error_route.py` показал, что `report_error` уходила в `system.log`,
то есть дороги в плоскость ошибок у плагина не было ни одной. Дорогу сторожит тест на МАРШРУТ
(`test_error_route.py`), а не на имя метода.

---

## 2. Поля записи и их владельцы

`LogRecord` ([`logger_module/core/log_types.py`](../../modules/logger_module/core/log_types.py)) —
семь полей; ниже они же в терминах OTel, потому что одно из имён совпадает с **чужим другим**
понятием.

| Поле | Кто ставит | OTel | Примечание |
|---|---|---|---|
| `timestamp` | эмитент | `Timestamp` | момент эмиссии |
| `level` | эмитент | `SeverityText` | каноничное имя уровня |
| `message` | эмитент | `Body` | |
| `module` | разъём (`setdefault`) | `InstrumentationScope` | **имя источника** — это и есть «scope» по OTel |
| `scope` | гейт логгера | — | наша *группа* (`SYSTEM`/`BUSINESS`/`PERFORMANCE`/`DEBUG`); в OTel соответствия нет, экспортёр обязан класть её в `Attributes` |
| `extra` | эмитент + процессоры | `Attributes` | внутри два структурных набора, см. ниже |
| `seq` | `LoggerCore.log` | — | пломба процесса (ADR-LOG-004); `0` = «запись создана мимо писателя», и проверяющий обязан сказать об этом вслух |

Внутри `extra` едут два набора, которые экспортёру **нельзя** хоронить в общих атрибутах:
`trace_id` (32 hex, W3C — `TraceId`) и база процесса `proc_name` / `fw_version` / `incarnation` /
`recipe` / `pid` (`Resource`).

**`observed_ts` в `LogRecord` не живёт вовсе.** Отметку приёма ставит **принимающая** сторона на
display-виде записи — `record_display.stamp_observed`
([`channel_routing_module/observability/record_display.py`](../../modules/channel_routing_module/observability/record_display.py)).
У эмитента она совпала бы с `ts` с точностью до микросекунд и не несла бы ни бита: наблюдатель и
источник — один процесс. Информация появляется ровно на границе процессов, поэтому единственное
законное место вызова — обработчик приёма у подписчика. Разность `observed_ts - ts` и есть
задержка доставки; существующий ключ не перетирается, чтобы пересылка через несколько рук
сохраняла отметку первого, кто увидел.

> **Не путать с `observed_at`** (`OBSERVED_AT_KEY` в
> [`channel_routing_manager.py`](../../modules/channel_routing_module/core/channel_routing_manager.py)) —
> там момент СНЯТИЯ СНИМКА СЧЁТЧИКОВ, а не приём записи. Разные вещи, похожие имена;
> дисциплина имён — ADR-LOG-005.

**Display-вид** (`{kind, process, module, ts, severity, message, extra}`, стор добавляет `id`) —
единый для живого хвоста и для истории: и `ObservabilityStore`, и push-канал строят строку через
`hub_record_to_display`. Форма live == форма history **по построению**, а не по договорённости.

---

## 3. Таблица асимметрий: что было несимметрично и когда закрыто

Асимметрия здесь — это когда две плоскости (или два разъёма) отвечают на один вопрос по-разному.
Каждая строка — воспроизведённый дефект, а не подозрение.

| # | Асимметрия | Закрыта | Чем |
|---|---|---|---|
| 1 | Фасад плагина штамповал **две** функции из пяти; протокол объявлял **три**; миксин имел **пять**. `ctx.log_warning` в ветке штатной деградации давал `AttributeError` | **2026-08-09**, A2 | явная пятёрка в `PluginContext.__init__` + контракт-тест на реальном контексте (список берётся ИЗ протокола, не константой) |
| 2 | У плагина не было **ни одной** дороги в плоскость ошибок; `health.report_error` писала через `services.log_warning` | **2026-08-09**, C2 | `HealthState` получил зависимость `track`; ADR-PM-030; тест на маршрут |
| 3 | «Документ без приёмника» молчал (`return False`), тогда как у записей тот же случай назван четвёртым классом потери | **2026-08-09**, C3 | `documents.declared` / `without_sink` / `dropped` в `introspect.observability`; голос — по одному на КЛАСС отказа |
| 4 | `level` подписчика не доезжал до процесса: пять звеньев теряли его, tap резал всё ниже ERROR | **2026-08-09**, A1 | `level` протянут через все звенья, объявлен в обоих контрактах, дефолт живёт в ОДНОЙ позиции |
| 5 | `error_manager` и `stats_manager` не гасились при останове вообще; логгер гасился третьим, и записи уборки терялись | **2026-08-09**, B3 | порядок останова (§5) + строка `observability planes stopped: …`, называющая ФАКТИЧЕСКИ погашенное |
| 6 | Ветка readback'а stats **не исполнялась ни разу** (сторожилась `getattr(stats, "config")`, которого у `StatsManager` нет) — темп, приёмники и молчащие стоки третьей плоскости наружу не выходили | **2026-08-09**, B1 | `StatsManager.observability_readback()`: темп из живого окна агрегации |
| 7 | `channels_active` / `sinks_disabled_by_operator` / `idle_sinks` отдавал только логгер — на error/stats оператор не отличал «я выключил» от «не поднялось» | Task 5.10 | `_sink_readback` / `_idle_sinks` зовутся для всех трёх плоскостей |
| 8 | Реентрантный tap давал лавину до предела рекурсии (498 записей), а `RecursionError` съедал `except Exception` | **2026-08-10**, D1 | поточный счётчик глубины + именованный `tap_reentrant_suppressed` |
| 9 | **stats-разъёма у плагина нет** — `IProcessServices` не объявляет stats-методов, 0 использований на ~30 плагинов | **НЕ ЗАКРЫТА** | развилка Р-2 решена владельцем как **(в)**: C1 уехала первой фазой в план телеметрии. Ветку `KIND_STATS` в drain трогать нельзя — на ней стоит это решение |

Строка 9 — единственная открытая. Пока она открыта, бизнес-числа плагин отдаёт телеметрией
(self-publish в дерево состояния), а не `StatsManager`.

---

## 4. Пять классов потери и их счётчики

Единый перечень — `LOSS_COUNTER_KEYS` в
[`channel_routing_manager.py:46`](../../modules/channel_routing_module/core/channel_routing_manager.py#L46).
Один список обслуживает объявление в `self.stats`, выдачу в `get_stats` и реестр публикации
`PLANE_COUNTER_KEYS`: разъехавшийся перечень уже стоил одной невидимой наружу метрики.

| Счётчик | Что случилось | Чем лечится |
|---|---|---|
| `unresolved_channel_records` | имя канала не резолвится | опечатка в конфиге или снятый sink |
| `channel_write_errors` | канал **бросил** | дефект канала |
| `channel_refused_records` | сток жив, но **отказал** | перегрузка стока, лесенка ADR-LOG-009 |
| `records_without_channels` | приёмников не было **вовсе** | конфиг: у скоупа пустой список каналов |
| `tap_reentrant_suppressed` | запись не роздана в tap'ы, потому что раздача уже шла в этом потоке | защита D1; законно, но невидимым быть не вправе |

Классы **не сливаются**, потому что лечатся разным. Рядом живёт счётчик ДОСТАВКИ
`channel_written_records` (`DELIVERY_COUNTER_KEYS`): до него ноль потерь одинаково означал и
здоровую систему, и систему, из которой ничего не выходит.

**Темпа в счётчиках нет ни в каком виде.** Наружу едут счётчик и момент чтения
(`observed_at`), частное берёт потребитель — так устроен любой scraper поверх counter-метрики.
Готовый `observed_rate_per_sec` был снят: он держал ОДНУ базу отсчёта внутри менеджера, и два
потребителя (GUI-панель и `backend_ctl`) при опросе с разной частотой портили показания друг
другу. Ни один тест этого не ловил — все читали в одиночку.

**Что потерей НЕ считается и почему:**

* запись в `NullChannel` — это **доставка** (`status=success`, `written += 1`): оператор выбрал
  «никуда» явно. Вырожденный случай назван прямо — скоуп уровня ERROR, маршрутизированный только
  туда, глушит пол ошибок, и об этом предупреждает `LoggerCore._warn_on_silenced_error_scopes`;
* вытеснение из кольца `MemoryChannel` (`evicted`) — контракт кольца: ёмкость N заказал оператор.

---

## 5. «Всё через менеджеры» и два named-исключения

Правило: **прикладной и модульный код пишет только через разъёмы**. Прямых обращений к stdlib в
плоскости наблюдаемости ровно два, и оба — по устройству:

| Исключение | Адрес | Почему без него нельзя |
|---|---|---|
| `emergency_log` | [`modules/_fallback.py`](../../modules/_fallback.py) | отказ писателя нельзя рассказать через самого писателя. Один выход на всю плоскость: `CRM._fallback_log`, четыре точки `log_channel`, немой `ChannelRegistry` (D1), миграция стора (D3), жалоба на снятые ключи конфига — все они именованные вызовы **этой** функции. Счёт держит страж-тест по AST: текстовый поиск ложно срабатывал на упоминании в докстринге |
| `ErrorFloor` | [`logger_module/core/error_floor.py`](../../modules/logger_module/core/error_floor.py) | синхронный конфиго-независимый пол error/critical. Прикладной код его позвать не может — это внутренний приёмник последней инстанции. Подробности в [`SINKS_MAP.md §4`](SINKS_MAP.md) |

Вне плоскости названо поимённо ещё одно: `shared_resources/queues` лежит **ниже** слоя логгера.

**Чужие библиотеки — мостом, а не терпением.** Библиотека, пишущая в свой stdlib-логгер
(`pymodbus.logging`), подключается `logging.Handler`-мостом, который форвардит в `get_std_logger`;
у перехваченного логгера ставится `propagate = False`, иначе при любом обработчике на stdlib-root
запись выходит ДВАЖДЫ (воспроизведено `logging.basicConfig()` в чистом процессе, D7). Живой
образец — `install_pymodbus_bridge` в [`Services/modbus/sdk/client.py`](../../../Services/modbus/sdk/client.py);
мост живёт в прикладном слое, потому что зависимость — прикладная.

**`get_std_logger` — это ВИД, а не писатель**
([`logger_module/adapters/std_facade.py`](../../modules/logger_module/adapters/std_facade.py)):
именованная точка входа для кода, которому удобнее stdlib-стиль. Единственный писатель —
`LoggerCore`.

---

## 6. Порядок останова

Установлен задачей B3 (2026-08-09), живёт в
[`process_module/lifecycle/process_lifecycle.py`](../../modules/process_module/lifecycle/process_lifecycle.py):

```
console → command → router → error → stats → статус + итоговая INFO → logger (ПОСЛЕДНИМ)
```

Почему именно так:

* **логгер последним** — до B3 он гасился третьим, и «shut down successfully» не попадало в файл
  ни у одного процесса: последней записью была «LoggerManager shutting down». Floor спасал только
  ERROR/CRITICAL, INFO/WARNING уборки терялись всегда;
* **stats до логгера** — его канал `log_stats` пишет ЧЕРЕЗ логгер, и обратный порядок отправил бы
  финальный снапшот метрик в закрытый приёмник;
* **error и stats гасятся вообще** — до B3 `shutdown()` у них не звался никем, и финальный flush
  двух плоскостей был на совести ОС. `shutdown()` оба наследуют от CRM: `flush()` → `buffer.stop()`
  → `_close_all_channels()`;
* **гашение младших плоскостей сделано видимым** — собственная запись плоскости ошибок идёт по её
  же маршруту, а INFO по нему не ездит, поэтому «погасили» и «не погасили» выглядели бы в журнале
  одинаково. Строка `observability planes stopped: error, stats` называет **фактически**
  погашенное, а не список из докстринга;
* **отказ гашения логгера не проглатывается** — он единственный, о ком нельзя сказать через него
  самого, поэтому named-исключение `emergency_log`. Успех останова при этом не отменяется.

Известный долг, названный и не закрытый: 5-секундный ханг на пути останова ПМ
(`ProcessManager did not stop in 5.0s, terminating...`). Измерено **5.1 с до и 5.1 с после** B3 —
к порядку гашения менеджеров он отношения не имеет; числится в [`plans/QUEUE.md`](../../../plans/QUEUE.md) как L-2.

---

## 7. Принятое как есть (не костыли, но названо)

* **Поток, вошедший в блокирующий `write()` стока, не ограничен ничем.** Лесенка перегрузки
  (ADR-LOG-009) спасает ОСТАЛЬНЫХ — тех, кто иначе выстроится за ним; свою жертву она не спасает.
  Размен на отдельный поток-писатель отвергнут сознательно: очередь writer'а умирает вместе с
  процессом, а лог нужен именно в момент падения.
* **Per-callsite тумблеры отвергнуты** индустриальным доводом: в Python выключенное состояние не
  бесплатно. Гранулярность — источник или группа источников.
* **Отложенное сообщение обязательно** там, где точка на пути КАЖДОЙ записи:
  `self._log_debug(lambda: f"…")` вместо f-строки. f-строка собирается на call-site, то есть до
  гейта, и никаким порогом внутри не снимается. Точке с постоянным текстом лямбда не нужна —
  собирать там нечего.
* **Mojibake русских строк в консоли Windows** (cp866) — принято как есть; числа при этом верны.
* **`events_page` на бутстрапе отдаёт ~114 КБ** — принято как есть.

---

## Решения

| ADR | О чём | Где |
|---|---|---|
| ADR-CRM-001, ADR-CRM-005, ADR-CRM-010, ADR-CRM-011 | база CRM, две роли конфигов, validate-then-swap, учёт потерь как общее хозяйство трёх плоскостей | [`channel_routing_module/DECISIONS.md`](../../modules/channel_routing_module/DECISIONS.md) |
| ADR-CRM-006 | точки расширения control plane | там же |
| ADR-CRM-013 | долговечность гейтится severity, а документ — не severity | там же |
| ADR-LOG-003, ADR-LOG-004, ADR-LOG-005 | `LogRecord` как тип, пломба `seq`, дисциплина имени `scope` vs `module` | [`logger_module/DECISIONS.md`](../../modules/logger_module/DECISIONS.md) |
| ADR-LOG-006, ADR-LOG-008, ADR-LOG-009, ADR-LOG-010 | редакция секретов, снятый батчинг, лесенка перегрузки, одна ось порога | там же |
| ADR-EM-007, ADR-EM-008 | единая точка эмиссии `_route()`, severity-лестница данными | [`error_module/DECISIONS.md`](../../modules/error_module/DECISIONS.md) |
| ADR-SM-006, ADR-SM-007 | `AggregationWindow` как `IBufferStrategy`, граница statistics ↔ hub | [`statistics_module/DECISIONS.md`](../../modules/statistics_module/DECISIONS.md) |
| ADR-PM-028, ADR-PM-029, ADR-PM-030 | плоскость документов, вердикт как второй клиент, `log_error` vs `report_error` | [`process_module/DECISIONS.md`](../../modules/process_module/DECISIONS.md) |
| ADR-PM-016, ADR-PM-017, ADR-PM-018 | телеметрийный тик, центральный троттл, управляемая публикация | там же |
| ADR-136, ADR-137 | GUI read-model без блокирующего IPC; фреймворк нейтрален к продукту | [`multiprocess_framework/DECISIONS.md`](../../DECISIONS.md) |
| ADR-PMM-025 | адрес обязан быть объявлен; headless — воплощение процесса | [`process_manager_module/DECISIONS.md`](../../modules/process_manager_module/DECISIONS.md) |
