# Анализ архитектуры наблюдаемости — логи / ошибки / статистика / телеметрия

> Дата: 2026-07-26 · Повод: требование владельца «все логи должны быть рабочими и полезными, гибкими, без хардкода — это конструктор-фреймворк; сделать как в индустриальных системах, не хуже, а может и лучше; всё через менеджеры»
>
> Источники: карта текущей реализации по коду (агент-investigator, 42 обращения к инструментам) · адверсариальное ревью предложенной схемы (Fable, 31 обращение) · разбор индустриальных практик и стандартов (агент-research, 28 обращений) · чтение планов и ADR.
>
> Статус: **аналитический документ, не план.** Решения владельца, которые из него следуют, — §9. План-преемник: `plans/observability-unified-routing.md`.

---

## 1. Что просит владелец (рамка)

Дословно по смыслу, собрано из реплик 2026-07-26:

1. Все логи **рабочие и полезные** — помогают отлаживать фреймворк и прототип.
2. **Гибкие, без хардкода** — потому что это конструктор-фреймворк, а не одно приложение.
3. Механизм **простой, не замудрённый**, переходит от модуля к модулю и по слоям.
4. **Разные группы, но механизм один:** одни записи пишутся в файл, другие читаются через backend_ctl, третьи показываются в GUI.
5. Иерархия: у каждого модуля свой менеджер → фасад модуля → менеджер процесса → фасад `process_module` → менеджер оркестратора → backend_ctl и GUI.
6. Включать/выключать **в реальном времени** — командой backend_ctl или правкой конфига.
7. **Всё через менеджеры** — архитектурный инвариант проекта.
8. Так же для `error_manager` и `statistics_manager`, но там всё всегда включено (особенно ошибки), при этом группы и приоритеты тоже управляются.
9. Как в индустрии 2026 — **OpenTelemetry** включить в план.

---

## 2. Карта текущей реализации

Базовый факт, определяющий всё остальное: наблюдаемость собрана вокруг общей базы `ChannelRoutingManager` и живёт как **один триплет менеджеров на процесс** (Logger + Error + Stats), а не на модуль. Иерархия наружу построена не на каскаде менеджеров, а на router-push tap'ах и pull-дренаже из `ObservabilityHub`.

### 2.1. `logger_module`

| Сущность | Где | Что |
|---|---|---|
| `LoggerManager` | `logger_module/core/logger_manager.py:23` | Тонкий наследник `LoggerCore`; добавляет только process-wide синглтон `_instance` (`:31-35`); `get_logger()` (`:43`) |
| `LoggerCore` | `logger_module/core/logger_core.py:49` | Всё тело: каналы, батчинг, scope-routing, tap-sink'и, sink-control, frame-trace, контекст, статистика |
| `modules` | `configs/logger_manager_config.py:93` | Per-module **файлы** (`camera→camera.log`), поля `enabled/file_path/min_level/rotate` |
| `channels` | `configs/logger_manager_config.py:151` | `system_file`, `messages_file`, `console` |
| `scopes` | `configs/logger_manager_config.py:178` | `SYSTEM/BUSINESS/PERFORMANCE/DEBUG`: `enabled`, `min_level`, список каналов, список модулей; решение — `scope.should_log()` (`:47`) |
| `LogScope` | `logger_module/enums/log_enums.py:17` | **Enum из 6 зон** — SYSTEM/BUSINESS/PERFORMANCE/AUDIT/SECURITY/DEBUG |
| `set_sink_enabled` | `logger_core.py:527` | Рантайм вкл/выкл **канала по имени** (ADR-CRM-006 п.3) |
| `add_log_tap` | `logger_core.py:563` | Доп. приёмник каждой записи ≥ порога, **вне** `_channel_registry`, переживает `reconfigure` (`:102-106`) |
| `_decision_cache` | `logger_core.py:379-387` | Кэш решения «писать?» по строковому ключу, **dict-lookup без лока**; инвалидация при reconfigure (`:344-354`) |

**Что такое «группа» сегодня:** `LogScope` — фиксированный enum. Второй ортогональный срез — `modules` (per-module файл). Произвольных пользовательских групп нет; «приоритет» = только `LogLevel`.

### 2.2. `channel_routing_module` — общая база

- `ChannelRoutingManager` (`core/channel_routing_manager.py:28`) наследует `BaseManager, ObservableMixin`. Даёт `ChannelRegistry`, `Dispatcher`, `IBufferStrategy`, `normalize_config`, `register_channel/route/broadcast/flush/reconfigure/get_stats`.
- Соотношение трёх менеджеров (docstring `:11-16`): Logger — key=level/scope, buffer=`BatchBuffer`; **Error — брат Logger** через общий предок `LoggerCore`; Stats — key=metric_name, buffer=`AggregationWindow`.
- `ObservableMixin` (`base_manager/mixins/observable_mixin.py:46`) — слоты `{'logger','stats','error'}`, утиная типизация (`_call_manager` `:299`), методы `_log_*` (`:104-126`), `_record_metric/_record_timing` (`:146-154`), `_track_error` (`:156`). Отказ слота не глотается: счётчик `manager_call_failures` + одноразовый WARNING (`:327`).
- Duck-type контракты слотов — `channel_routing_module/observability/protocols.py:19`.

### 2.3. `error_manager` и `statistics_manager`

- `ErrorManager` (`error_module/core/error_manager.py:124`) — **брат** LoggerManager (оба потомки `LoggerCore`). Severity-routing `_setup_level_routes` (`:185`): CRITICAL→`critical_file`, ERROR→`errors_file`, WARNING→`warnings_file`. Имеет `set_sink_enabled` и `add_log_tap` (наследует от `LoggerCore`).
- `StatsManager` (`statistics_module/core/stats_manager.py:43`) — наследует `ChannelRoutingManager`, key=metric_name, buffer=`AggregationWindow`; counter/gauge/timing/histogram (`:234-274`). **Remote-stats через router не реализована** (docstring `:16-18`). **`set_sink_enabled` отсутствует.**

### 2.4. Тракт наружу

Двухуровневая схема (Ф5.15/Ф5.16):

- **Уровень 0 — `ObservabilityHub`** (`channel_routing_module/observability/observability_hub.py:68`): «модуль = устройство с 3 выходами», 3 bounded-канала, pull-модель. **Подключён только к пилоту `worker_module`.**
- **Wiring** — `process_module/managers/observability_wiring.py`: `wire_process_observability` (`:143`) создаёт один hub на процесс; `_LoggerSlotSplitter` (`:103`) — `error/critical` идут write-through в реальный `logger_manager` (мимо hub-буфера), `debug/info/warning` — в hub.
- **Дренаж по heartbeat** — `process_heartbeat.py:296` → `drain_process_observability` (`:187`) → `ObservabilityDrainAdapter` (`drain_adapter.py:67`) + `ObservabilityStore` SQLite (`observability_store.py:72`) + forwarders.
- **Push наружу:** `RecordForwardChannel` (`record_forward_channel.py:41`, `command="observability.record"`, `queue_type="system"`) и `RouterPushChannel` (`logger_module/channels/router_push_channel.py:29`, `command="log.record"`).
- **Каждый дочерний процесс пушит напрямую подписчику**, а не агрегируется через LoggerManager оркестратора. ProcessManager триплет для детей не собирает.

### 2.5. Рантайм-ручки сегодня

| Ручка | Где | Гранулярность |
|---|---|---|
| Секция `observability` (log_level, console/file, errors.enabled, stats.enabled, commands.log_success) | `system.yaml:46-58`, `observability_config.py:76` | процесс |
| hot-reload watcher + IPC `config.reload` → `apply_observability_reconfigure` | `observability_reload.py:120`, `builtin_commands.py:927` | процесс; пороги по scope (`observability_reload.py:44`) |
| `logger.sink.enable/disable` | `logger_core.py:527`, `builtin_commands.py:1137` | **отдельный канал по имени, только logger** (`_toggle_logger_sink:1145`) |
| publisher-gate телеметрии | `telemetry_publish_config.py:35` (`GATED_METRICS` — кортеж из 5), `process_heartbeat.py:375` | группа метрик на процесс |
| `commands.log_success` | `observability_config.py:57` | процесс, гейт **у источника** |
| `log.tail` / `observability.tail` | `builtin_commands.py:1158/1223` | порог уровня подписки |
| readback `observability_effective` | `observability_reload.py:72-117` | процесс; `channels_active` из живого реестра |

### 2.6. Иерархия менеджеров

- **Один триплет на процесс.** «LoggerManager модуля» как сущности нет.
- Модуль получает логгер двумя путями: инъекция менеджеров в слоты `ObservableMixin`, либо фасад `get_std_logger(module)` (`logger_module/adapters/std_facade.py:134`) поверх синглтона.
- `ObservabilityHub` — единственное, что похоже на «фасад модуля», но это буферизующий перехватчик, один на процесс, только у пилота.
- **Каскада «фасад→фасад→оркестратор» нет.**

---

## 3. Что уже заложено в планах

| Документ | Статус | Содержание |
|---|---|---|
| [observability-hub-idea.md](../../plans/2026-07-06_constructor-master/observability-hub-idea.md) | закреплена 2026-07-08, задачи Ф5.15–5.17 | Дословно идея владельца: фасад модуля с каналами err/log/stats. **Решение о гранулярности: «один hub на процесс с module-тегом»** — вариант «менеджер на модуль» рассмотрен и отклонён. Охват: «пилот `worker_module` + один сервис» |
| [observability-messaging-vision.md](../../plans/2026-07-06_constructor-master/observability-messaging-vision.md) | **СОГЛАСОВАНО 2026-07-09** | §3 целевая: единый эмиттер + сменные sink + drain-петля direct/routed; 4 инварианта-предохранителя; §4 «чего НЕ делать» — в т.ч. запрет на надстройку над `IChannel` («третий механизм») |

Исполнено (по мастер-плану): **5.14** ✅ CRM-развязка (Error — брат, не наследник) · **5.15** ✅ ObservabilityHub core · **5.16** ✅ wiring + дренаж, владелец петли `ProcessModule` · **5.17** ✅ контракт-тест «канал ≠ health» · **5.19** ✅ GUI: один `RecordHistoryPanel` на 3 вкладки · **5.20** ✅ persistent-стор SQLite + форвардинг hub→GUI · **5.21** ✅ добор после ревью.

**Не заложено нигде:** группы как данные · один реестр приёмников (5.20 построил форвардинг hub→GUI **отдельным плумбингом** — то есть «два механизма» это не побочный эффект, а результат постановки) · схлопывание трёх реестров (`scopes` / `GATED_METRICS` / `_level_to_channel`) · объявление групп рядом с модулем · H.4 существует строкой без понятия группы.

**Ключевое наблюдение:** всё, что владелец просит для логов, **уже реализовано для телеметрии** — [telemetry-publish-control.md](../../plans/telemetry-publish-control.md) содержит почти дословно ту же формулировку («частота per-параметр/группа, вкл/выкл, в реальном времени») и закрыт через ADR-PM-018. Механизм в проекте есть; его не распространили на логи и ошибки.

---

## 4. Адверсариальное ревью предложенной схемы

Схема, вынесенная на разнос: (1) группы — данные; (2) удалённые sink'и — обычные каналы; (3) гранулярность (процесс, модуль, группа, уровень); (4) гейт у источника; (5) обязательный readback; (6) каскад менеджеров отвергнут.

### 4.1. Пункт 2 — ОПРОВЕРГНУТ

«Удалённые sink'и как обычные каналы» несовместимо не по типам (оба push-канала реализуют `IChannel`), а по **жизненному циклу**:

1. `reconfigure` делает `flush → _close_all_channels → _rebuild_from_config` (`channel_routing_manager.py:162-165`), пересборка строго из `config.channels` (`logger_core.py:202-215, 294-306`). Router-канал в конфиг положить нельзя — нужна живая ссылка на router (`router_push_channel.py:13-16`). Tap'ы вынесены из реестра **намеренно ради этого** (`logger_core.py:102-106`). Сделай их каналами — любой hot-reload молча убьёт подписку GUI/backend_ctl.
2. `set_sink_enabled(name, True)` пересоздаёт канал из `config.channels[name]` и вернёт `False`, если его там нет (`logger_core.py:543-547`). Для `gui`/`ctl` — всегда `False`. **Disable работает, enable — нет.**
3. Реестровые каналы батчатся (`logger_core.py:432-435`), tap'ы пишут синхронно до буфера (`:429-430`). Слияние = «канал, который не батчится» = третий механизм из Vision §4.

**Контрпредложение:** унифицировать **плоскость управления, а не плоскость хранения**. Один namespace команд, один формат записи, один readback, покрывающий оба реестра. Различие «config-owned sink» vs «runtime-owned tap» — структурное, его надо оформить, а не стереть.

### 4.2. Пункт 4 (гейт у источника) — ВЫСТОЯЛ с поправкой

Резолв уже кэширован (`_decision_cache`, dict-lookup без лока); расширение ключа — доли микросекунды. Прецеденты гейта-до-форматирования есть: `log_success` (`command_manager.py:96-101, 248-258`, история: `messages.log` вырос до 645 МБ) и `frame_trace` (`logger_core.py:656-668`).

**Поправки:** (а) API эмиссии принимает уже готовую строку (`observable_mixin.py:104-106`), а `std_facade` форматирует **до** проверки (`std_facade.py:120-127`) — без ленивого API выигрыш только на I/O, не на CPU; (б) каждая рантайм-ручка обязана звать `invalidate_decision_cache()`, иначе кэш переживёт выключение группы.

### 4.3. Пункт 3 — доказательная база была подменена

Утверждение «506 путей сигналов, свёрнутых до 41 формы» относится к **state-плоскости read-model** (`2026-07-23_phase6-levels-vs-edges.md:42-44`), а не к логированию. **Инвентаря лог-точек в проекте нет.** Сам выбор гранулярности «четвёрка, не точка вызова» подтверждён независимо (§5), но опора была ложной.

### 4.4. Пункт про инвариант error/critical — ОПРОВЕРГНУТ, и хуже

**Инвариант дыряв уже сегодня.** У `ErrorManager` `enable_batching: True`, interval 0.5 с (`error_manager.py:39-41`); severity-путь кладёт ERROR/CRITICAL в буфер **без приоритета** (`:264-266`); `LoggerCore.log` — так же (`logger_core.py:432-435`). `BatchBuffer` сбрасывает немедленно только при `priority == "urgent"` (`batch_buffer.py:133`), **который не передаёт никто**. Окно потери crash-лога при SIGKILL: **до 0.5–1.0 с прямо сейчас**.

**Врущая документация:** README обоих модулей обещают «`priority_flush=True` — ERROR/CRITICAL записываются немедленно» (`error_module/README.md:320`, `logger_module/README.md:264`). Флаг есть, условие недостижимо.

**Контрпредложение:** захардкоженный **floor вне таблицы** — error/critical всегда дополнительно write-through в локальный файловый sink, минуя батч. Floor — инвариант, а не данные: таблица может добавлять приёмники, но не убирать этот.

### 4.5. Правда против гибкости — ТРЕБУЕТ ПОПРАВКИ

- **Существующий недосчитанный путь:** записи в отсутствующий канал теряются молча и **без счётчика** (`logger_core.py:356-374`, `:443-450`). В схеме «группы — данные» это становится магистральным: опечатка в имени приёмника → readback говорит «включено», логи в никуда.
- **Новый путь 1:** «включён» ≠ «доставляет» — `write` возвращает error-dict, эмиттер результат выбрасывает (`logger_core.py:601-606`, `record_forward_channel.py:105-106`). Известный масштаб: 23 % ошибок отправки были невидимы.
- **Новый путь 2:** асимметрия enable/disable из §4.1.
- **Требуется:** валидация ссылок группа→sink при apply (громкий отказ, не no-op); per-edge счётчики enqueued/written/dropped по паре (группа, sink); счётчик отправки наружу.

### 4.6. Миграция H.4 — масштаб занижен планом

- Не 43 файла, а **58 файлов / 63 вхождения** `logging.getLogger` в prototype; мигрировано 2.
- **Механическая замена сломает 5 вызовов:** фасад не принимает kwargs (`std_facade.py:70-84`), а `exc_info=True` живёт в `displays/tab.py:720`, `pipeline/inspector/selectors_data.py:73,92,113`, `pipeline/graph_codec.py:390`. Все пять — **внутри except-блоков**: вместо тихой потери получим `TypeError` из обработчика ошибок.
- **Startup-окно:** резолв ленивый, до поднятия `LoggerManager` запись уходит в stdlib-фолбэк — импорт-тайм логи виджетов по-прежнему в stderr.
- Из хорошего: int-уровней, `setLevel`/`addHandler`/`isEnabledFor` в prototype нет — кроме `exc_info` несовместимостей поверхности не найдено.

### 4.7. Вердикт по рамке владельца

Требование «механизм один» законно на уровне **пульта** (один формат записи, один namespace ручек, один readback) и на ~70 % выполнено существующим кодом. Прочтение «один провод» (один реестр с одной семантикой жизненного цикла) — не то, что нужно: файл живёт от конфига, подписка живёт от подписчика, и это различие — причина существования tap'ов.

---

## 5. Индустриальная планка

> Сокращённая выжимка. Полный разбор с таблицами практик, спецификациями и ссылками — [`2026-07-26_observability-industrial-baseline.md`](2026-07-26_observability-industrial-baseline.md).

### 5.1. Рантайм-управление уровнями

| Механизм | Кто | Адресация | Readback | Нам |
|---|---|---|---|---|
| `/actuator/loggers` | Spring Boot | Иерархическое имя + **logger groups** (ярлык поверх иерархии) | **Эталон:** `{"configuredLevel": null, "effectiveLevel": "INFO"}`; `null` = унаследовано; POST `null` = **сброс к наследованию** | Прямой прототип; у нас нет read-команды и понятия «унаследовано» |
| `POST /logging` | Envoy | `level=` (все), `<logger>=<level>`, батч `paths=a:debug,b:trace`, **glob** (`source/common*:warning`); логгер = файл исходника | POST без параметров = листинг всех логгеров; **отдельный admin-порт** | Батч и glob — прямо наша дыра; glob-механика уже есть в `state_store_module` |
| `AtomicLevel` + `ServeHTTP` | Go zap | Атомик на дерево | GET/PUT уровня; проверка на hot path — atomic load | Идея «уровень = разделяемая ячейка»; наш аналог — `_decision_cache` |
| JMX / `monitorInterval` / `scan` | Log4j2, Logback | Логгер по имени | JMXConfigurator листает и меняет; авто-перечитывание по таймеру | **У нас лучше:** watcher с debounce вместо polling (ADR-CRM-006) |
| `-v N` | klog | Числовая verbosity, **ортогональна severity** | `klog.V(4).Enabled()` перед дорогим форматированием | Вторая ось решает «DEBUG — это и шаг алгоритма, и каждый кадр» |
| Категории + filter rules | .NET `ILogger` | Иерархическое имя; правило по **самому длинному совпадающему префиксу** | `IOptionsMonitor` + `reloadOnChange` | **Ключевая модель:** устойчива к появлению новых плагинов |
| `logging.config.listen` + `dictConfig(incremental=True)` | Python stdlib | Иерархическое имя | Инкрементально меняются **только `level` и `propagate`** — осознанное ограничение CPython | Наш `deep_merge` соответствует; не расширять до пересборки графа |
| Keywords + Level | ETW / EventSource | Провайдер + **битовая маска keywords** + уровень | Сессия задаёт маску | **Лучший ответ для hot path.** Правило MS: события чаще ~1K/с обязаны иметь отдельный keyword |
| `dyndbg` | Linux kernel | **Per-callsite** (`file:line`, `func`, `module`, `format`) — адрес выводит компилятор | Полный листинг всех callsite; выключенный = NOP через jump label, **ноль стоимости** | Осторожно: в Python выключенное состояние не бесплатно |

### 5.2. Почему иерархическое имя, а не плоский enum групп

Три вещи, которых у enum нет:

1. **Дефолт для незнакомого источника.** Новый плагин `Plugins.processing.roi_crop` автоматически подчиняется правилу `Plugins.processing` — конфиг не трогают при добавлении плагина. Enum требует правки при каждом новом члене. **Это прямой ответ на требование «без хардкода, это конструктор».**
2. **Одна ось вместо двух.** Сейчас `scope` и `module` независимы, и «включить DEBUG у одного плагина» невыразимо — нужен либо весь scope, либо весь module.
3. **Детерминированное разрешение конфликтов** (самый длинный префикс, при равенстве — последнее правило).

Spring поверх иерархии добавляет **группы** как отдельную сущность-ярлык. То есть группы **дополняют** иерархию, а не заменяют её.

### 5.3. Формат записи — OpenTelemetry Logs Data Model

12 полей: `Timestamp`, `ObservedTimestamp`, `TraceId`, `SpanId`, `TraceFlags`, `SeverityText`, `SeverityNumber`, `Body`, `Resource`, `InstrumentationScope`, `Attributes`, `EventName`.

- **`SeverityNumber` 1–24:** TRACE 1-4, DEBUG 5-8, INFO 9-12, WARN 13-16, ERROR 17-20, FATAL 21-24. Одиночная severity источника кладётся в нижнее значение диапазона. Инвариант: `>= 17` — ошибка. Зачем 24 вместо 5: сохраняется градация без потери порядка. **Для нас:** `LogLevel` остаётся человеческим API, в записи едет число — тогда klog-подобная verbosity внутри DEBUG (5,6,7,8) выражается без нового поля.
- **`Resource` vs `InstrumentationScope`:** Resource = *кто наблюдаем* (хост/сервис/инстанс) → у нас процесс/машина/рецепт. Scope = *кто испустил* (имя + версия) → наш `module`, но плоский, без версии и иерархии. OTel-мостам предписано класть имя логгера именно в scope-name — **scope и есть точка адресации уровня**.
- **`TraceId`/`SpanId`:** у нас уже есть естественный корреляционный ключ — `seq_id` кадра (`LoggerCore.frame_trace(message, seq_id)`), плюс пара `(camera_id, seq_id)` из G.7. Это фактически trace_id, не названный так и не проброшенный в запись.
- **Logs Bridge API `Enabled()`** — спека **требует** дешёвый предикат, чтобы не строить запись, которая будет отброшена.

**Вердикт:** совместимость на уровне модели полей — да; зависимость от SDK/OTLP — нет. Практический минимум: `severity_number`, `scope{name,version}`, `trace_id`, `observed_timestamp`, `Resource` один раз на процесс. ~5 полей, не переделка. Плюс: `ObservedTimestamp` отдельно от `Timestamp` — сейчас мы теряем разницу «когда произошло» vs «когда пришло в GUI», то есть задержки IPC неотличимы от задержек обработки.

### 5.4. Горячий путь

| Механизм | Кто | Суть | Нам |
|---|---|---|---|
| Sampling first-N-then-every-Mth | zap | Первые `first` за `interval` проходят, дальше каждая `thereafter`-я; ключ = **level+message** — дросселируется повторяющееся, редкое проходит всегда | Правильный ответ на 10 точек `_log_debug` в `router_manager.py`: не выключать, а прореживать |
| BasicSampler (1 из N) / BurstSampler | zerolog | Две ортогональные композируемые политики | Burst = «покажи первые 5 и замолчи» — нужен при старте рецепта |
| Overload protection | Erlang `logger_std_h` | По длине очереди: async → **sync** → **drop** → **flush**; `burst_limit_enable`; `overload_kill_enable` | **Прямо в нашу дыру:** `RecordForwardChannel` едет never-drop `system`-очередью вместе с heartbeat |
| Async на LMAX Disruptor | Log4j2 | Lock-free, буфер 256K | Цена: при переполнении деградирует до синхронной. Урок — **определить поведение при переполнении**, а не только буферизовать |
| Flight recorder | JFR (<1 % overhead, always-on, дамп по триггеру), LTTng, Python `MemoryHandler(flushLevel=ERROR)` | Подробность пишется в кольцо, на диск улетает по событию | **Очень высоко:** `FrameTraceChannel` уже overwrite-per-frame; не хватает кольца на N кадров и триггера |
| Canonical log line / wide event | Stripe и далее | **Одна широкая структурированная запись на единицу работы** вместо десятка узких | **Доменно точно:** единица работы = бутылка/кадр |
| Per-part traceability | MES / промышленное зрение | Результат инспекции привязан к серийному номеру, ретеншен 10–25 лет | **Отдельная плоскость.** Это не лог и не метрика — запись качества |

### 5.5. Три плоскости против наших трёх менеджеров

Индустрия делит по **вопросу, на который отвечает сигнал**; не сливает из-за разных требований к кардинальности, объёму, ретеншену и допустимости потерь.

Наше деление **не совпадает** — оно по важности/назначению:

- `LoggerManager` ≈ logs, но `LogScope` смешивает три разных сигнала: PERFORMANCE — это метрики, AUDIT — это трейсабилити, DEBUG — детальность.
- `ErrorManager` — не отдельный индустриальный сигнал, а логи с `severity >= ERROR` + гарантия доставки. OTel помечает `>= 17` так же; гарантия «errors always-on» совпадает с индустрией. Раздельные файлы и менеджер — наша реализация, не индустриальный контракт.
- `StatsManager` ≈ metrics, но публикует только локально; реальная телеметрия FPS/latency идёт мимо него через self-publish в heartbeat. **Плоскость метрик расщеплена надвое.**
- **Трейсов нет вообще** — `frame_trace` по смыслу трейс, по механике лог.

---

## 6. Где мы ниже планки

1. **Нет отдельной read-команды наблюдаемости.** `introspect.observability` не существует: единственный способ узнать уровень — вызвать `config.reload`, то есть **чтобы посмотреть, надо изменить**. У Envoy это POST без параметров, у Spring — GET.
2. **Нет `configured` vs `effective` с `null` = «унаследовано»** и нет сброса к наследованию одной командой. Без этого «верни как было» требует помнить исходное состояние — а мы знаем, чем кончается «включил DEBUG и забыл» (645 МБ).
3. **Адресация — процесс целиком.** Плоский `scope × module` не масштабируется на плагины, которых нет в момент написания конфига. Нет батча, нет glob.
4. **Нет второй оси.** `LogScope` смешивает назначение (AUDIT, SECURITY) с детальностью (DEBUG). Везде в индустрии есть keywords / verbosity / категории отдельно от severity.
5. **Нет sampling и rate-limit для логов** — только on/off.
6. **Политика при переполнении не выведена наружу.** `ObservabilityHub.dropped` считается, но не публикуется — потеря невидима (класс «проглоченный сбой»).
7. **Управляющая плоскость делит транспорт с рабочей** — `observability.record` и `log.record` едут `system`-очередью вместе с heartbeat и `state.changed`. Уже обжигались: gui задушен system-очередью, `evict_blocked` 1466.
8. **Записи о детали (вердикты) не отделены от диагностики** — разный ретеншен, разные гарантии.
9. **Запись не структурная и без идентичности источника** — нет `severity_number`, версии scope, корреляционного ключа, `observed_timestamp`.

---

## 7. Где можем быть лучше индустрии

Всё опирается на то, что у нас **закрытая система с собственным драйвером** — можно требовать от команды больше, чем допустимо для публичного HTTP.

1. **Verified-смена уровня.** Индустрия отдаёт `200 OK`, проверка — на совести оператора. У нас есть паттерн `set_register_verified` / `process_restart_verified`. `set_log_level_verified`: успех только если readback подтвердил `effective` **и** в течение N секунд пришла запись нового уровня (или явно отмечено «источник молчит»). Структурно закрывает класс «`config_reload` врёт про `log_level`» и «43 файла пишут в никуда».
2. **TTL и авто-откат.** Индустрия этого практически не делает: в Kubernetes роль TTL играет рестарт пода, в Spring/Envoy изменение живёт до перезапуска. Для установки, которая не перезапускается неделями, это дыра. `set_level(target, DEBUG, ttl=300)` с гарантированным возвратом и записью «уровень истёк».
3. **Аудит смен наблюдаемости** — кто/когда/что менял. Механика `session_log` / `register_rollback_log` переиспользуема. В индустрии это внешняя дисциплина, а не свойство системы.
4. **Глобальная адресация одной командой.** Actuator и Envoy адресуют один инстанс. У нас единый хаб ProcessManager → `paths=camera_*/plugins.roi_crop:DEBUG` с glob по процессам и модулям, с per-process результатом в одном ответе. Glob уже есть в `state_store_module`.
5. **Flight recorder, привязанный к доменному вердикту.** JFR/LTTng дают кольцо и дамп по команде; привязки «сбрось последние 200 кадров трассы, когда вердикт = брак или confidence в серой зоне» нет ни у кого — у них нет домена. `FrameTraceChannel` уже overwrite-per-frame. Строго лучше и sampling (не теряем именно интересные кадры), и on/off (не платим объёмом за 99.9 % нормальных бутылок).
6. **Третья колонка readback — «наблюдается».** У Spring две: `configuredLevel`, `effectiveLevel`. Добавить `observed_rate` (записей/с за окно) — тогда «уровень DEBUG, а записей ноль» видно в одной таблице.
7. **Наблюдаемость как часть рецепта** — уровни, publisher-gate и sink'и в составе Recipe/blueprint, с версионированием и hot-swap.
8. **Контракт-тесты «путь наблюдаемости не врёт»** — регресс-страж, что каждая заявленная точка управления доходит до приёмника.

---

## 8. Чего индустрия НЕ делает

1. Не меняет в рантайме произвольный граф логирования — только уровни и propagate (явная позиция CPython).
2. Не заводит **рукописный** реестр per-callsite тумблеров. Linux dyndbg делает per-callsite, но адрес выводится компилятором, управление идёт паттерном, а выключенный callsite стоит ноль. В Python выключенное состояние не бесплатно → гранулярность до строки не окупается, уровень модуля/плагина достаточен.
3. Не логирует пер-элементно на высокой частоте. Правило ETW: > 1K событий/с — только за отдельным keyword, выключенным по умолчанию. **На 25–60 FPS «логировать каждый кадр» — антипаттерн, а не консервативный выбор.**
4. **Не сэмплирует ошибки.** Прореживают INFO/DEBUG и успешные трейсы. Наш ADR-PM-018 «errors always-on» совпадает.
5. Не делает неограниченную асинхронную очередь без политики переполнения.
6. Не считает уровень достаточным рычагом — везде есть вторая ось.
7. Не смешивает управляющую плоскость с рабочей.
8. Не смешивает audit/traceability с диагностикой (10–25 лет против дней).
9. Не строит смену уровня как «перечитай файл целиком» — везде дельта поверх живого.
10. Не оставляет включённый DEBUG без выхода (у них выход даёт рестарт; у нас рестарта нет).

---

## 9. Дефекты, найденные по ходу анализа (готовы к починке)

| # | Дефект | Якорь | Класс |
|---|---|---|---|
| 1 | ERROR/CRITICAL батчатся до 0.5–1.0 с: `priority="urgent"` не передаёт никто; окно потери crash-лога при SIGKILL | `error_manager.py:264-266`, `logger_core.py:432-435`, `batch_buffer.py:133` | нарушенный инвариант |
| 2 | README обоих модулей обещают немедленную запись ERROR/CRITICAL — условие недостижимо | `error_module/README.md:320`, `logger_module/README.md:264` | врущая документация |
| 3 | Записи в отсутствующий канал теряются молча, без счётчика | `logger_core.py:356-374`, `:443-450` | проглоченный сбой |
| 4 | `logger.sink.*` бьёт только в `logger_manager`; у `StatsManager` метода нет вовсе | `builtin_commands.py:1145`, `stats_manager.py:43` | асимметрия |
| 5 | Прикладные имена (`camera`, `robot`, `renderer`) в дефолтах **фреймворка**; комментарий «для отладки роутинга временно вернуть DEBUG» | `logger_manager_config.py:93-148` | нарушение слоёв + хардкод |
| 6 | `std_facade` не принимает kwargs → механическая миграция ломает 5 вызовов `exc_info=True` внутри except-блоков | `std_facade.py:70-84`; вызовы в `displays/tab.py:720`, `selectors_data.py:73,92,113`, `graph_codec.py:390` | регресс миграции |
| 7 | H.4 в плане занижен: не 43, а 58 файлов / 63 вхождения | `plans/.../h2-gate-g4-triage.md` п. 12 | спека плана врёт |
| 8 | `set_sink_enabled` не инвалидирует `_decision_cache` (сегодня корректно, в новой схеме станет багом) | `logger_core.py:527`, `:344-354` | латентный |
| 9 | **Гейт стоит после построения сообщения:** `should_log()` вызывается внутри `log()` — f-string на call-site уже оплачен. Сам ключ кэша — f-string, аллоцируемый на **каждом** вызове, включая попадание в кэш | `logger_core.py:379-387` | перф / корень инцидента 645 МБ |
| 10 | **`BatchBuffer` безлимитен:** `defaultdict(deque)` без `maxlen`, без проверки ёмкости, без ключа `dropped` в stats. Соседние `AsyncSenderBuffer` (`PriorityQueue(maxsize)`) и `BoundedChannel` (drop-policy + счётчик) сделаны правильно — логгер нет | `channel_routing_module/buffers/batch_buffer.py` | неограниченный рост памяти + невидимая потеря |
| 11 | **`_context_stack` не thread-local** вопреки имени `_get_thread_context()` — обычный список на инстансе. `WorkerManager` крутит реальные потоки → `push_context` одного воркера попадает в записи другого | `logger_core.py` | некорректность в многопоточном процессе |
| 12 | `log_context: ContextVar` объявлен и читается, но **никто в репозитории в него не пишет** | `logger_module` | мёртвый механизм |
| 13 | `record.to_dict()` вызывается **по разу на каждый целевой канал** внутри цикла enqueue, плюс ещё раз на taps | `logger_core.py` | перф |
| 14 | **Ретеншена нет вообще** — ни по возрасту, ни по суммарному размеру, ни компрессии. Только `max_size`/`backup_count`, зашитые в конфиг и не вынесенные в секцию observability. Факт: весь `logs/` — 1.5 ГБ | `configs/logger_manager_config.py` | эксплуатационный |
| 15 | **`default_level` — мёртвый параметр:** `_level_profile_scopes` вынужден переписывать `min_level` каждому скоупу, потому что корневой уровень ни на что не влияет. **Это корень живой находки «`config_reload` врёт про `log_level`»** | `observability_reload.py:44` | врущий API |
| 16 | `except Exception: pass  # nosec B110` в `_flush_batch` + потеря всего батча, когда имя канала не резолвится ни в `_channel_registry`, ни в `_module_channels` | `logger_core.py:356-374` | проглоченный сбой |
| 17 | Слот `_dispatcher` из `ChannelRoutingManager` в `LoggerCore` мёртв по документированному решению — цепочка процессоров его оживляет | `logger_core.py:127-130` | мёртвый механизм |

---

## 10. Решения владельца

| # | Решение | Контекст |
|---|---|---|
| 1 | **Гранулярность фасада.** Расширять hub на все модули = отмена решения 2026-07-08 («один hub на процесс с module-тегом», охват — пилот). Альтернатива, следующая из §5.2: не менеджер на модуль, а **иерархическое имя источника** — идентичность без размножения менеджеров | §2.6, §3, §5.2 |
| 2 | **Модель адресации:** плоские группы-данные или иерархическое имя + longest-prefix + группы-ярлыки поверх (модель Spring/.NET) | §5.2 |
| 3 | **Вторая ось:** вводить ли verbosity/keywords отдельно от severity, или оставить один `LogLevel` | §5.1, §6.4 |
| 4 | **Отдельный транспорт управляющей плоскости** — выносить ли наблюдаемость с `system`-очереди | §6.7 |
| 5 | **Объём OTel:** только модель полей (рекомендация) или SDK/экспортёр | §5.3 |
| 6 | **Вердикты о детали** — выделять ли в отдельную плоскость с собственным ретеншеном | §5.4, §8.8 |
| 7 | **Порядок:** чинить дефекты §9 отдельными фиксами до переделки, или одним заходом | §9 |

---

## 11. Библиотеки логирования Python

Позиция, следующая из требования «всё через менеджеры»: свой `LoggerManager` **не заменяется**. Из библиотек берутся механизмы, а не рантайм.

### 11.1. Топ-5 механизмов к переносу

**№ 1. Гейт до построения сообщения + ленивое сообщение.** structlog решает это системно: отфильтрованный метод логгера буквально подменяется на `def _nop(...): return None` — «`return None` is hard to beat». loguru даёт `opt(lazy=True).debug("{}", expensive_func)`. stdlib — `isEnabledFor` + отложенное `%`-форматирование.

Эскиз на менеджер:

```python
def is_enabled_for(self, scope: LogScope, level: LogLevel, module: str = "main") -> bool: ...
def log(self, scope, level, message: str | Callable[[], str],
        *args, module: str = "main", **extra) -> None: ...
```

Три правки в горячем пути: `LogLevel` получает **int-ранг** (сравнение `>=` вместо `LEVEL_ORDER.index(str)` дважды за решение); ключ `_decision_cache` — **кортеж**, а не f-string; `message` вычисляется **один раз после** гейта. Плюс приём structlog: при выключенном скоупе связать `self._log_debug = _noop` один раз на реконфигурации — убирает и `_call_manager` lookup, и `getattr`, и try/except.

**№ 2. Ограниченный буфер с политикой сброса и счётчиком потерь.** Это тот же баг, что открыт у loguru (issue #1419: `enqueue=True` на безлимитной `SimpleQueue`, RSS 28→69 МБ на 1 ГБ логов при стоке с 50 мс латентности). stdlib предписывает противоположное — ловить `queue.Full`.

```python
@dataclass
class BatchConfig:
    max_size: int = 100
    flush_interval: float = 1.0
    priority_flush: bool = True
    max_pending: int = 10_000                 # НОВОЕ: потолок на канал
    overflow: Literal["drop_oldest", "drop_newest", "block"] = "drop_oldest"
```
плюс `dropped_by_channel` в `stats` и публикация счётчика. Правило: **дроп допустим, невидимый дроп — нет.**

**№ 3. Цепочка процессоров над record-dict.** Сигнатура structlog — `(logger, method_name, event_dict) -> event_dict`. Наш `LogRecord.to_dict()` уже event-dict, но обработка зашита в `log()` и повторяется на каждый канал.

```python
Processor = Callable[[str, "LogLevel", Dict[str, Any]], Optional[Dict[str, Any]]]
# None == запись поглощена (structlog.DropEvent); новый dict == замена (logging.Filter, 3.12)
def add_processor(self, proc: Processor, *, position: int | None = None) -> None: ...
```

**Оговорка под принцип «меньше слоёв»:** цепочка обязана **заменить** инлайн-код в `log()`, а не лечь поверх. Побочно чинится «`to_dict()` по разу на канал» и оживает мёртвый слот `_dispatcher` (`logger_core.py:127-130`). Плагинами вместо правки ядра становятся: сэмплирование (переиспользовать `ThrottleMiddleware` из `state_store_module`), редакция секретов, обогащение `pid`/`seq_id`, JSON-рендер.

**№ 4. Контекст: `bind()` + `contextvars`.** `bind()` даёт иммутабельный контекст на объекте-логгере, `contextvars` — контекст по задаче/потоку, сливаемый процессором.

```python
class BoundLogger:            # лёгкий view, не второй менеджер
    __slots__ = ("_core", "_ctx")
def bind(self, **context) -> "BoundLogger": ...
@contextmanager
def contextualize(self, **context): ...
```

**№ 5. Иерархия имён и наследование уровня.** stdlib: `getEffectiveLevel()` идёт вверх по точкам до первого не-`NOTSET`; `propagate` даёт «хендлер на корне — видно всё поддерево». В нашем конфиге `scopes` уже **строковый** ключ — ограничение чисто в enum'е.

```python
def effective_level(self, scope: str) -> LogLevel:
    """vision.capture.hikvision → vision.capture → vision → <root>"""
def effective_channels(self, scope: str) -> tuple[str, ...]: ...
```

`LogScope` остаётся набором преднастроенных констант, но `log()` принимает произвольную строку.

**Бонус — `FingersCrossedHandler` (logbook).** DEBUG копится в кольце в памяти и уходит на диск **только если случился ERROR**. Ровно наша боль: scope `DEBUG` выключен в дефолте, потому что давал ~100 МБ/мин — то есть отладочный контекст выключен всегда, а нужен только вокруг сбоя. На 25–60 FPS «последние 500 записей до ошибки» ≈ 10 кадров контекста. Ложится на № 2: тот же bounded-буфер, но политика «держи и слей по триггеру» вместо «дропни».

### 11.2. Чего НЕ брать

**Не заменять `LoggerManager` на loguru** — шесть аргументов по существу:

1. **Глобальный синглтон против нашей модели владения.** `logger.add()` возвращает `int`, а не объект; per-process менеджера нет. У нас `logger_sink_enable/disable`, `add_log_tap`, `reconfigure()` — операции над **объектом**, вызываемые из MCP и hot-reload watcher'а.
2. **Windows + spawn.** Дочерний процесс не наследует сконфигурированный `logger`; рецепт самой loguru предлагает workaround через модульный глобал и сеттер. Плюс issue #1264: с `forkserver` `SimpleQueue` падает.
3. **`enqueue=True` — регресс наблюдаемости:** безлимитная очередь без backpressure = **второй IPC-план** рядом с `RouterManager`, у которого уже есть QoS и телеметрия. Порядок между планами не определён, счётчиков дропов нет.
4. **Опасные дефолты:** `diagnose=True` печатает значения переменных в трейсбеках — утечка кадров, путей, конфигов.
5. **Производительность не аргумент за:** structlog примерно вдвое быстрее и stdlib, и loguru.
6. **Правильное место loguru — за интерфейсом `ILogChannel`**, где он уже и живёт: единственный продовый импорт — `Services/modbus/sdk/client.py:20`.

Также не брать: реализацию `enqueue` (брать stdlib-модель `QueueHandler` + ограниченная очередь + `queue.Full`) · `structlog.stdlib.ProcessorFormatter` (нужен, когда логи идут через stdlib root — у нас наоборот; брать модель процессоров, а не мост) · `picologging` (drop-in для stdlib, которого у нас нет в горячем пути; early-alpha) · `eliot` целиком (требует переписать call-sites под контекст-менеджеры) — но **точечно взять `task_uuid`**: `seq_id` уже готовый корреляционный ключ, довести его до сквозного — это процессор из № 3.

### 11.3. Стоимость выключенного лога

Жёстких наносекундных цифр в официальных доках нет; страница performance у structlog чисел не содержит вовсе. Что есть:

| Источник | Цифра |
|---|---|
| structlog vs stdlib/loguru (сторонний бенч) | ~**2×** быстрее — plain dict вместо record-объекта, без lock |
| picologging | **4–10×** (заявляется до 17×) к stdlib; early-alpha |
| `isEnabledFor` vs lazy-обёртка (бенч) | `isEnabledFor` ~**4×** дешевле создания lazy-инстанса |
| loguru #1419 | RSS 28 → 69 МБ на 1 ГБ логов — цена отсутствия backpressure |
| **Наш инцидент** | `messages.log` **645 МБ** при потолке ~60 МБ; весь `logs/` — **1.5 ГБ** |

Существенно не это. Реальная цена в двух местах:

1. **Построение сообщения.** `logger.debug(f"frame {seq}: {arr.shape} {cfg}")` платит f-string **всегда**; цена не ограничена сверху — `repr()` numpy-массива стоит сотни микросекунд.
2. **Наш «выключенный» путь дороже stdlib-«включённой» проверки.** Отклонённая запись платит: инкремент счётчика → **построение f-string ключа кэша** → dict lookup → возврат. Мы аллоцируем строку, чтобы решить не аллоцировать строку. У stdlib отклонённый `debug()` — это сравнение int.

Оценка порядков (не измерение): гейт на int с кортежным ключом — десятки нс; текущий гейт с f-string-ключом — сотни нс плюс аллокация; f-string с парой чисел — единицы мкс; с `repr()` массива — сотни мкс. Пропорция «выключенный лог стоит ~0» достигается только если гейт стоит **до** аргументов. Перед внедрением снять свой бенч в `logger_module/tests/`.

### 11.4. Ключевые сигнатуры

```python
# loguru
logger.add(sink, level='DEBUG', filter=None, serialize=False,
           backtrace=True, diagnose=True, enqueue=False, catch=True)
logger.opt(lazy=True).debug("If sink level <= DEBUG: {x}", x=lambda: expensive())
logger.add("f.log", rotation="500 MB", retention="10 days", compression="zip")

# structlog
structlog.make_filtering_bound_logger(min_level: int)
def processor(logger, method_name: str, event_dict: dict) -> dict
structlog.contextvars.bind_contextvars(**context) / merge_contextvars(...)

# stdlib
Logger.isEnabledFor(level) -> bool
Logger.getEffectiveLevel() -> int        # вверх по иерархии до первого не-NOTSET
Filter.filter(record) -> bool | LogRecord  # с 3.12 может вернуть ЗАМЕНЯЮЩИЙ record
logging.handlers.QueueHandler(queue) / QueueListener(queue, *h, respect_handler_level=False)
```

Замечания: `respect_handler_level=True` — прямой аналог нашего per-channel `min_level`; контекст-менеджер у `QueueListener` появился в **3.14**, мы на 3.12 — `start()`/`stop()` вручную. И формулировка из cookbook, объясняющая существование `RouterPushChannel`:

> logging to a single file from *multiple processes* is *not* supported, because there is no standard way to serialize access to a single file across multiple processes in Python.

---

## Источники

Полный список ссылок на спецификации и документацию — в разделах §5.1–5.4 исследования; ключевые: [OTel Logs Data Model](https://opentelemetry.io/docs/specs/otel/logs/data-model/), [Spring Boot Actuator Loggers](https://docs.spring.io/spring-boot/reference/actuator/loggers.html), [Envoy admin interface](https://www.envoyproxy.io/docs/envoy/latest/operations/admin), [Erlang logger overload protection](https://www.erlang.org/doc/apps/kernel/logger_chapter.html), [zap sampler](https://github.com/uber-go/zap/blob/master/zapcore/sampler.go), [Linux dynamic debug](https://www.kernel.org/doc/html/v4.15/admin-guide/dynamic-debug-howto.html), [Stripe canonical log lines](https://stripe.com/blog/canonical-log-lines), [.NET logging overview](https://learn.microsoft.com/en-us/dotnet/core/extensions/logging/overview).
