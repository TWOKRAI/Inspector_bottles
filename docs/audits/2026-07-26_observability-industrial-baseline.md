# Наблюдаемость: индустриальная планка и где мы

> Дата: 2026-07-26 · Повод: требование владельца «сделать так, как делают в индустриальных системах — не хуже, а может и лучше»
>
> Метод: разбор практик рантайм-управления логами и стандартов представления записей (Spring Actuator, Envoy, Log4j2/Logback, Go zap, klog, .NET, Python stdlib, ETW, Linux dyndbg, OpenTelemetry, Erlang/OTP, JFR/LTTng, MES-трейсабилити) с привязкой к нашей фактической реализации по коду.
>
> Родительский документ: [`2026-07-26_observability-architecture-analysis.md`](2026-07-26_observability-architecture-analysis.md) · План-преемник: [`plans/observability-unified-routing.md`](../../plans/observability-unified-routing.md)

---

## 0. Короткий вывод

По **механике смены уровня без рестарта** мы уже на уровне индустрии: единый путь `apply_observability_reconfigure` + watcher + IPC-команда + `effective`-readback (`multiprocess_framework/modules/process_module/managers/observability_reload.py`).

Ниже планки мы в трёх местах:

1. **Readback доступен только как побочный эффект мутирующей команды** — `introspect.observability` не существует, то есть чтобы посмотреть уровень, надо его изменить.
2. **Адресация — процесс целиком**, модель уровней плоская (`scope × module` без наследования).
3. **Для логов нет ни sampling, ни rate-limit, ни политики при переполнении** — а живой хвост едет по той же never-drop `system`-очереди, что и heartbeat.

Три места, где мы реально можем быть **лучше** индустрии, потому что у нас закрытый драйвер, а не публичный HTTP: **verified-смена** (команда успешна только после подтверждённого readback), **TTL/авто-откат уровня**, **flight recorder кадров, привязанный к вердикту брака**.

---

## 1. Таблица практик

### 1.1. Рантайм-управление уровнями

| Механизм | Кто | Адресация | Readback: «сконфигурировано» vs «действует» | Применимо нам |
|---|---|---|---|---|
| **`/actuator/loggers`** | Spring Boot | Имя логгера (иерархическое, `com.foo.Bar`), плюс **logger groups** — именованный набор логгеров, один POST меняет группу | **Эталон.** GET отдаёт `{"configuredLevel": null, "effectiveLevel": "INFO"}`. `null` = «явно не сконфигурировано, унаследовано». POST `{"configuredLevel": null}` = **сброс к наследованию** | **Прямой прототип.** У нас `observability_effective()` возвращает похожий срез (`scopes{enabled,min_level}`, `channels_active`), но нет отдельной read-команды и нет понятия «унаследовано / сброс» |
| **`POST /logging`** (admin) | Envoy | `level=` (все), `<logger>=<level>` (один), `paths=a:debug,b:trace` (батч). Fine-grain режим: логгер = **файл исходника**, поддержаны glob (`source/common*:warning`) | POST **без параметров** = листинг всех логгеров с текущими уровнями. Отдельный admin-порт, отдельно от data-plane | **Очень применимо.** Батч `paths=` и glob — то, чего у нас нет; glob-механика уже есть в `state_store_module` (glob-подписки), переиспользуема |
| **`AtomicLevel` + `ServeHTTP`** | Go zap | Один атомик на дерево логгеров; сам уровень — `http.Handler` | GET = JSON текущего уровня, PUT = смена. Проверка на hot path — atomic load | Идея «уровень = разделяемая ячейка, а не перечитывание конфига»; наш функциональный аналог — `LoggerCore._decision_cache` + `invalidate_decision_cache()` |
| **JMX / `monitorInterval` / `scan`+`scanPeriod`** | Log4j2, Logback | Логгер по имени | `JMXConfigurator` умеет листать логгеры и менять уровни; авто-перечитывание конфига по таймеру (Logback — раз в минуту по умолчанию) | **У нас уже лучше:** watchdog-watcher с debounce вместо polling (`start_observability_watcher`, ADR-CRM-006). Индустриальный caveat: у Logback JMXConfigurator в контейнере течёт память, если не разрегистрировать |
| **klog `-v N`** | Kubernetes | Числовая verbosity, **ортогональна severity**; конвенция V(0)…V(5), прод — V(2) | Гварда `klog.V(4).Enabled()` перед дорогим форматированием | Частично. Вторая ось (**детальность** отдельно от **важности**) решает нашу проблему «DEBUG — это и шаг алгоритма, и каждый кадр» |
| **Категории + filter rules** | .NET `ILogger` | Категория = иерархическое имя; правило выбирается по **самому длинному совпадающему префиксу**, с учётом провайдера; иначе `MinimumLevel` | `IOptionsMonitor` + `reloadOnChange` → правила перечитываются на лету | **Ключевая модель для нас.** Longest-prefix делает конфиг устойчивым к появлению новых плагинов |
| **`logging.config.listen(port, verify)` + `dictConfig(incremental=True)`** | Python stdlib | Логгер по иерархическому имени | Инкрементально меняются **только `level` и `propagate`** — это осознанное ограничение CPython, не недоделка | Наш язык. Формат «дельта поверх живого» у нас уже такой (`deep_merge`). `verify`-предупреждение (там `eval`) — аргумент, что свой драйвер безопаснее стандартного `listen` |
| **Keywords + Level** | ETW / `EventSource` / EventPipe | Провайдер + **битовая маска keywords** + уровень: `"Demo:3:5"` | Сессия задаёт маску; провайдер знает, включён ли он | **Лучший ответ для hot path.** Прямая рекомендация MS: события чаще ~1K/с обязаны иметь отдельный keyword, чтобы их можно было выключить, не трогая остальное. Наш `frame_trace` — ровно такой случай |
| **Dynamic debug (`dyndbg`)** | Linux kernel | **Per-callsite**: `file:line`, `func`, `module`, `format` — адрес выводится компилятором, не пишется руками | Файл `dynamic_debug/control` = полный листинг всех callsite с их состоянием. Выключенный callsite — NOP через jump label, **ноль стоимости** | Осторожно. Per-callsite оправдан только там, где выключенное состояние бесплатно. В Python это словарь на каждый вызов — см. §4.2 |

### 1.2. Формат записи: OpenTelemetry Logs Data Model

Двенадцать полей: `Timestamp`, `ObservedTimestamp`, `TraceId`, `SpanId`, `TraceFlags`, `SeverityText`, `SeverityNumber`, `Body`, `Resource`, `InstrumentationScope`, `Attributes`, `EventName`.

**`SeverityNumber` 1–24** — нормализованная шкала: TRACE 1-4, DEBUG 5-8, INFO 9-12, WARN 13-16, ERROR 17-20, FATAL 21-24. Правило маппинга: одиночная severity источника кладётся в **нижнее** значение диапазона (`Informational` → 9); несколько — распределяются внутри диапазона по относительной строгости. Инвариант: `SeverityNumber >= 17` означает ошибку.

Зачем 24 вместо 5: сохраняется исходная градация чужой системы **без потери порядка**, и при этом любой потребитель может фильтровать по диапазону. Для нас это значит: `LogLevel` (5 значений) остаётся человеческим API, а в записи едет число — тогда klog-подобная verbosity внутри DEBUG (5, 6, 7, 8) выражается **без нового поля**.

**`Resource` vs `InstrumentationScope`.** Resource = *кто наблюдаем* (хост, сервис, инстанс) — у нас это процесс / машина / рецепт. InstrumentationScope = *кто испустил* (библиотека или модуль инструментации: имя + версия). То есть OTel решает идентичность источника **двухуровнево**: «что за система» отдельно от «какой её модуль».

Наш `module` (плоская строка `"camera"`, `"processor_frames"`) — это недоделанный InstrumentationScope: нет версии, нет иерархии, нет привязки к плагину. При этом OTel-мостам предписано класть имя логгера именно в scope-name — **то есть scope и есть точка адресации уровня**.

**`TraceId` / `SpanId`.** Даёт то, ради чего это всё в многопроцессной системе: запись из `camera_0` и запись из `inference_1` **сшиваются по одному идентификатору прохода**. У нас уже есть естественный корреляционный ключ — `seq_id` кадра (`LoggerCore.frame_trace(message, seq_id)`, `Plugins/runtime/chain_executor/plugin.py` и др.), плюс пара `(camera_id, seq_id)` из G.7. Это фактически trace_id, только не названный так и не проброшенный в каждую запись.

**Logs Bridge API `Enabled()`** — спека прямо требует дешёвый предикат, чтобы **не строить запись**, если она будет отброшена. Аналог `logger.isEnabledFor(...)` / `klog.V(4).Enabled()`.

**Стоит ли нам быть OTel-совместимыми.** Рекомендация: **совместимость на уровне модели полей — да, зависимость от SDK — нет.**

Плюсы:
- готовый словарь для того, что мы всё равно вынуждены изобрести (severity-число, scope, корреляция);
- при появлении второго потребителя (MES, Grafana/Loki, заказчик) экспорт — это маппер, а не переделка;
- спека уже решила краевые случаи: `ObservedTimestamp` для «когда собрали» против «когда произошло» — у нас это разница между временем в процессе и временем прихода в GUI, и мы её сейчас **теряем**.

Минусы и цена:
- `Attributes` как `AnyValue` конфликтует с правилом Dict at Boundary лишь частично (dict проходит), но требует дисциплины — иначе получим неограниченную кардинальность;
- полный OTLP-транспорт нам не нужен и тянет grpc/protobuf;
- `EventName` и семантические конвенции — отдельный долг.

**Практический минимум:** добавить в запись `severity_number`, `scope{name,version}`, `trace_id` (= `seq_id` / `part_id`), `observed_timestamp`, а `Resource` собрать один раз на процесс. Это ~5 полей, не архитектурная переделка.

### 1.3. Горячий путь и транспорт

| Механизм | Кто | Что даёт | Применимо нам |
|---|---|---|---|
| **Sampling first-N-then-every-Mth** | zap | Первые `first` записей с данным (level, message) за `interval` проходят, дальше — каждая `thereafter`-я. Ключ — **level + message**, то есть дросселируется «повторяющееся», а редкое проходит всегда. Точность принесена в жертву скорости | **Высоко.** Правильный ответ на `_log_debug` в `router_manager.py` (10 точек на hot path): не выключать, а прореживать по тексту |
| **BasicSampler (1 из N) / BurstSampler (N за период, дальше — делегат)** | zerolog | Две ортогональные композируемые политики | Burst = «покажи первые 5 и замолчи» — то, чего не хватает при старте рецепта |
| **Overload protection с переключением режимов** | Erlang/OTP `logger_std_h` | По длине очереди: async → **sync** (`sync_mode_qlen`) → **drop** (`drop_mode_qlen`) → **flush** (`flush_qlen`, сброс очереди без записи); плюс `burst_limit_enable`; плюс `overload_kill_enable` (убить и перезапустить хендлер) | **Прямо в нашу дыру.** У нас `ObservabilityHub` — `BoundedChannel` со счётчиком `dropped`, но наружу политика и счётчик не выведены, а `RecordForwardChannel` едет `queue_type="system"` (never-drop) вместе с heartbeat — в шапке файла это честно записано как отложенный долг |
| **Async loggers на LMAX Disruptor** | Log4j2 | Lock-free передача в поток-писатель, буфер 256K | Цена: при переполнении производительность **деградирует до синхронной**; мутабельные сообщения нельзя менять после лога; лишний поток вреден на 1 vCPU. У нас есть `BatchBuffer`/`AsyncSenderBuffer` — урок в том, что **надо определить поведение при переполнении**, а не только буферизовать |
| **Flight recorder** | JFR (< 1 % overhead, always-on, дамп по jcmd или по триггеру), LTTng (per-CPU кольца, overwrite-режим), Python `MemoryHandler(capacity, flushLevel=ERROR)` | Подробность пишется всегда, но в кольцо; на диск улетает только по событию | **Очень высоко.** У нас уже есть `FrameTraceChannel` в режиме overwrite-per-frame — до полноценного flight recorder не хватает кольца на N кадров и триггера |
| **Canonical log line / wide event** | Stripe и далее вся индустрия | **Одна широкая структурированная запись на единицу работы** вместо десятка узких; дёшево агрегировать, контекст не разорван | **Очень высоко и доменно точно:** единица работы у нас — бутылка/кадр. Одна запись «бутылка N: ROI, время этапов, вердикт, confidence» вместо россыпи DEBUG |
| **Filter + probabilistic sampler** | OTel Collector | Сначала выбросить заведомый шум (OTTL-условия), потом прореживать остаток | Применимо на стороне GUI/стока, но у нас важнее гейт **у источника** (публикатор), как в ADR-PM-018 — это дешевле, чем гнать и выбрасывать |
| **Per-part traceability в MES** | Промышленное зрение | Результат инспекции привязан к серийному номеру детали, уезжает по OPC UA/MQTT в MES/БД; ретеншен 10–25 лет | **Отдельная плоскость от логов.** Это не лог и не метрика — это запись качества. У нас уже есть telemetry DB-sink, но вердикты как «записи о детали» не отделены от диагностики |

### 1.4. Три плоскости против наших трёх менеджеров

Индустрия делит по **вопросу, на который отвечает сигнал**, а не по типу данных:

- **метрики** — «что происходит, агрегированно и дёшево, известные-известные»;
- **логи** — «что именно случилось в этом экземпляре»;
- **трейсы** — «где во всей цепочке ушло время».

Не сливают потому, что у них разные требования к кардинальности (метрика с высококардинальным лейблом убивает TSDB), к объёму, к ретеншену и к допустимости потерь.

Наше деление **не совпадает** с этим — оно по **важности/назначению**, что видно из кода:

- `LoggerManager` ≈ logs, но с шестью `LogScope` (SYSTEM / BUSINESS / PERFORMANCE / AUDIT / SECURITY / DEBUG), из которых PERFORMANCE — это метрики, а AUDIT — это трейсабилити. То есть в одну плоскость сложены три разных сигнала с разными требованиями.
- `ErrorManager` — не отдельный индустриальный сигнал, а **логи с severity >= ERROR** и жёсткой гарантией доставки. Само по себе это не ошибка: OTel тоже помечает `SeverityNumber >= 17` как ошибочные, а гарантия «errors always-on» из ADR-PM-018 совпадает с индустрией (ошибки не сэмплируют). Но раздельные файлы и раздельный менеджер — это наша реализация, не индустриальный контракт.
- `StatsManager` ≈ metrics, но публикует **только локально** (`LogStatsChannel` пишет через логгер, `FileStatsChannel` — в файл), своего IPC нет; реальная телеметрия FPS/latency идёт мимо него через self-publish в heartbeat. То есть **плоскость метрик у нас фактически расщеплена надвое**.
- **Трейсов нет вообще** — есть `frame_trace`, который по смыслу трейс, а по механике лог.

**Расхождение, которое стоит закрыть: транспорт.** В индустрии admin/наблюдаемость идёт отдельным каналом (admin-порт Envoy, JMX, actuator, EventPipe-сокет) — именно чтобы шторм диагностики не убил рабочий трафик. У нас `observability.record` и `log.record` едут `system`-очередью вместе с heartbeat и `state.changed`, и мы уже один раз этим обожглись (gui задушен system-очередью, `evict_blocked` 1466).

---

## 2. Планка «как в индустрии» — минимум, ниже которого нельзя

1. **Отдельная read-команда наблюдаемости** (`introspect.observability`), не мутирующая. Сейчас единственный способ узнать уровень — вызвать `config.reload`, то есть **чтобы посмотреть, надо изменить**. Это ниже планки: у Envoy это `POST /logging` без параметров, у Spring — GET.
2. **`configured` против `effective` в явном виде, с `null` = «унаследовано»**, и **сброс к наследованию** одной командой. Без этого «верни как было» требует помнить исходное состояние — а мы знаем, чем кончается «включил DEBUG и забыл» (645 МБ `messages.log`).
3. **Адресация тоньше процесса.** Минимум: батч `paths=<цель>:<уровень>,...` как в Envoy. Правильно: иерархическое имя + выбор правила по **самому длинному префиксу** (.NET / Java / Python). Плоский `scope × module` не масштабируется на плагины, которых нет в момент написания конфига.
4. **Уровень — единственная ось, мутируемая в рантайме.** Граф каналов/форматтеров произвольно не пересобирать. Это не наша осторожность, а явная позиция CPython: нет убедительного кейса произвольно менять граф объектов в рантайме; verbosity управляется уровнями и `propagate`; безопасно менять граф в многопоточной среде проблематично, и выигрыш не стоит сложности. Исключение, которое индустрия делает, — включение/выключение **уже описанного** sink (у нас `set_sink_enabled`), это допустимо.
5. **Дешёвый предикат перед формированием записи** (`Enabled()` / `isEnabledFor` / `V(n).Enabled()`) и дисциплина «не вычислять аргументы до проверки». `_decision_cache` у нас есть — не хватает гарантии на стороне вызывающего кода.
6. **Ограниченность всего, кроме ошибок, с явной политикой при переполнении и видимым счётчиком потерь.** Erlang задаёт планку формой «async → sync → drop → flush». У нас `ObservabilityHub.dropped` считается, но наружу не выведен — потеря невидима, а это тот самый класс «проглоченный сбой».
7. **Никакого пер-элементного логирования на 25–60 FPS по умолчанию.** Правило ETW прямое: чаще ~1K событий/с — обязателен отдельный выключаемый keyword. Всё, что нужно постоянно, — **считать** (счётчики/гистограммы), а не писать строками.
8. **Структурированная запись с нормализованной severity и идентичностью источника** (процесс + модуль/scope + версия) и корреляционным ключом. Плюс `observed_timestamp` отдельно от `timestamp`, иначе задержки в IPC неотличимы от задержек в обработке.
9. **Ротация, доказанная прогоном, а не конфигом.** Это не индустриальная новация, это наш собственный шрам (`except PermissionError: pass`, 36 процессов на один файл).
10. **Управляющая плоскость не делит транспорт с рабочей.**
11. **Записи о детали (вердикты) — отдельная плоскость с собственным ретеншеном**, а не строки в диагностическом логе.

### 2.1. Почему префикс, а не плоский enum групп

Иерархическое имя даёт три вещи, которых у enum нет:

- **Дефолт по умолчанию для незнакомого источника.** Новый плагин `Plugins.processing.roi_crop` автоматически подчиняется правилу `Plugins.processing` — конфиг не надо трогать при добавлении плагина, а enum требует правки при каждом новом члене.
- **Одна ось вместо двух.** У нас сейчас `scope` и `module` независимы, и «включить DEBUG у одного плагина» невыразимо — нужен либо весь scope, либо весь module.
- **Разрешение конфликтов детерминировано** (самый длинный префикс, при равенстве — последнее правило), а у плоского enum пересечение групп либо запрещено, либо решается ad hoc.

Именно поэтому Spring **поверх** иерархии добавляет группы как отдельную сущность-ярлык: группы **дополняют** иерархию, а не заменяют её.

---

## 3. Где мы можем быть лучше индустрии

Все пункты опираются на то, что у нас **закрытая система с собственным драйвером** — можно требовать от команды больше, чем допустимо для публичного HTTP-эндпоинта.

1. **Verified-смена уровня.** Индустрия отдаёт `200 OK` и на этом всё; проверка — на совести оператора. У нас уже есть паттерн `set_register_verified` / `process_restart_verified`. Сделать `set_log_level_verified`: команда считается успешной, только если (а) readback подтвердил `effective`, и (б) в течение N секунд пришла хотя бы одна запись нового уровня (или явно отмечено «источник молчит»). Это **структурно** закрывает класс «`config_reload` врёт про `log_level`» и «43 из 44 файлов GUI пишут в stdlib logging без хендлеров» — второй случай сегодня выглядит как успех.
2. **TTL и авто-откат.** Проверено специально: **индустрия этого практически не делает** — в Kubernetes роль TTL играет рестарт пода, в Spring/Envoy изменение живёт до перезапуска. Для промышленной установки, которая не перезапускается неделями, это дыра. `set_level(target, DEBUG, ttl=300)` с гарантированным возвратом и записью «уровень истёк» — дёшево у нас и невозможно у них.
3. **Аудит смен наблюдаемости.** Кто / когда / что менял, с автоматической отметкой в логе — у нас есть `session_log` и `register_rollback_log`, механика переиспользуема. В индустрии это внешняя дисциплина («оставьте заметку после отката»), а не свойство системы.
4. **Глобальная адресация одной командой.** Actuator и Envoy адресуют один инстанс: чтобы включить DEBUG на десяти подах, делают десять запросов. У нас единый хаб ProcessManager → `paths=camera_*/plugins.roi_crop:DEBUG` с glob и по процессам, и по модулям, с per-process результатом в одном ответе. Механика glob уже существует в `state_store_module`.
5. **Flight recorder, привязанный к доменному вердикту.** JFR/LTTng дают кольцо и дамп по команде; привязки «сбрось последние 200 кадров трассы, когда вердикт = брак или confidence в серой зоне» нет ни у кого, потому что у них нет домена. У нас `FrameTraceChannel` уже overwrite-per-frame — не хватает кольца и триггера. Это строго лучше и sampling (не теряем именно интересные кадры), и on/off (не платим объёмом за 99.9 % нормальных бутылок).
6. **Третья колонка в readback: «наблюдается».** У Spring две колонки — `configuredLevel` и `effectiveLevel`. Добавить `observed_rate` (записей/с по каждому источнику за последнее окно) — тогда «уровень DEBUG, а записей ноль» видно в одной таблице и не требует детектива. Прямое лекарство от нашего класса «сбой есть, счётчик растёт, причина проглочена».
7. **Наблюдаемость как часть рецепта.** Уровни, publisher-gate и sink'и в составе Recipe/blueprint, с версионированием и hot-swap. В индустрии это конфиг рядом с приложением; у нас может быть частью описания задачи — «рецепт отладки Hikvision-линии» переключается одной сменой рецепта.
8. **Контракт-тесты на «путь наблюдаемости не врёт».** У нас уже есть выученные уроки (дефолтный путь сверять с публикатором; тесты вне `testpaths`). Регресс-страж, который проверяет, что каждая заявленная точка управления действительно доходит до приёмника, — это то, чего в чужих проектах нет, а у нас есть основание.

---

## 4. Чего индустрия НЕ делает (и почему)

1. **Не даёт менять в рантайме произвольный граф логирования** — только уровни и `propagate` (позиция CPython, см. §2.4). Наш `deep_merge` поверх живого конфига этому соответствует; не расширять до пересборки каналов на лету.
2. **Не заводит рукописный реестр per-callsite тумблеров.** Тонкая грань: Linux dynamic debug **делает** per-callsite — но адрес (`file:line`, `func`, `module`) выводится автоматически, управление идёт **паттерном** (`module=usbcore +p`), а выключенный callsite стоит ноль благодаря jump label. Envoy fine-grain — то же самое, логгер = имя файла. Чего никто не делает — ручного перечисления тумблеров в конфиге. Для нас: адресация должна **выводиться** из имени модуля/плагина/файла и фильтроваться паттерном; в Python выключенное состояние не бесплатно, поэтому гранулярность до строки экономически не окупается — уровня модуля/плагина достаточно.
3. **Не логирует пер-элементно на высокой частоте.** Правило ETW: > 1K событий/с — только за отдельным keyword, выключенным по умолчанию. Вместо логов — счётчики, гистограммы, а для разбора — трассировка с кольцевым буфером. На 25–60 FPS «логировать каждый кадр» — **не консервативный выбор, а антипаттерн**.
4. **Не сэмплирует ошибки.** Прореживают INFO/DEBUG и успешные трейсы; ошибки идут все (tail sampling: «оставь все трейсы с ошибками и процент успешных»). Наш ADR-PM-018 «errors always-on» совпадает — это не самодеятельность.
5. **Не делает неограниченную асинхронную очередь без политики.** Log4j2 при заполнении кольца деградирует до синхронной записи; Erlang переключается sync → drop → flush и в пределе убивает хендлер. «Асинхронно» всегда идёт в комплекте с ответом на вопрос «а что при переполнении». Наш `RecordForwardChannel` на never-drop `system`-очереди — как раз то, от чего индустрия ушла.
6. **Не считает уровень достаточным рычагом.** Везде есть вторая ось: keywords (ETW), verbosity `-v` (klog), категории + провайдер (.NET), маркеры (Logback/Log4j2). Причина: важность и детальность — разные вещи, одной шкалой не выражаются. Наш `LogScope` — попытка второй оси, но он смешивает назначение (AUDIT, SECURITY) с детальностью (DEBUG).
7. **Не смешивает управляющую плоскость с рабочей** — admin-порт, JMX, EventPipe-сокет всегда отдельно.
8. **Не смешивает audit/traceability с диагностикой.** Разные гарантии и ретеншен: записи о детали в MES живут 10–25 лет, диагностические логи — дни. Держать их в одном файле и одной ротации нельзя.
9. **Не строит смену уровня как «перечитай файл целиком».** Логика везде — дельта поверх живого (`incremental`, POST одного логгера, PUT одного уровня). Полная переконфигурация из файла — отдельная, более редкая операция. У нас это уже так.
10. **Не оставляет включённый DEBUG без выхода.** У них выход даёт рестарт инстанса; у нас рестарта нет — значит выход надо строить явно (см. §3.2).

---

## 5. Ссылки

**Рантайм-управление уровнями**
- [Spring Boot Actuator — Loggers](https://docs.spring.io/spring-boot/reference/actuator/loggers.html) · [Baeldung: changing log level at runtime](https://www.baeldung.com/spring-boot-changing-log-level-at-runtime) · [5 Ways to Change Log Levels at Runtime (DZone)](https://dzone.com/articles/5-ways-to-change-the-log-levels-at-runtime) · [Better Stack: change log levels dynamically](https://betterstack.com/community/guides/logging/change-log-levels-dynamically/)
- [Envoy — Administration interface](https://www.envoyproxy.io/docs/envoy/latest/operations/admin) · [Envoy Gateway: debug logs](https://docs.tetrate.io/envoy-gateway/administration/debug-logs) · [PR #4511 — component log level](https://github.com/envoyproxy/envoy/pull/4511/files/327015db7f22df0ecdbf673f90c2431c0a34209f)
- [Logback — automatic reconfiguration (scan/scanPeriod)](https://logback.qos.ch/manual/configuration.html) · [Logback — JMXConfigurator](https://logback.qos.ch/manual/jmxConfig.html) · [Log4j2 — JMX](https://logging.apache.org/log4j/2.x/manual/jmx.html)
- [go.uber.org/zap — AtomicLevel / ServeHTTP](https://pkg.go.dev/go.uber.org/zap) · [zap/level.go](https://github.com/uber-go/zap/blob/master/level.go) · [Golang dynamic logging](https://dev.to/rusty_sys_dev/golang-dynamic-logging-3p7k)
- [Kubernetes logging conventions (sig-instrumentation)](https://github.com/kubernetes/community/blob/main/contributors/devel/sig-instrumentation/logging.md) · [k8s.io/klog/v2](https://pkg.go.dev/k8s.io/klog/v2) · [Cluster API — logging levels](https://cluster-api.sigs.k8s.io/developer/core/logging)
- [.NET — Logging overview (категории, фильтры, longest-prefix)](https://learn.microsoft.com/en-us/dotnet/core/extensions/logging/overview) · [Logging in ASP.NET Core](https://learn.microsoft.com/en-us/aspnet/core/fundamentals/logging/) · [LoggerFilterRule](https://learn.microsoft.com/en-us/dotnet/api/microsoft.extensions.logging.loggerfilterrule) · [IOptionsMonitor / reload](https://thecodeblogger.com/2021/04/22/ioptionsmonitor-demo-reload-configurations-in-net-applications/)
- [Python — logging.config (listen, incremental, disable_existing_loggers)](https://docs.python.org/3/library/logging.config.html) · [Logging Cookbook — multiprocessing/QueueHandler](https://docs.python.org/3/howto/logging-cookbook.html)
- [Linux — Dynamic debug howto](https://www.kernel.org/doc/html/v4.15/admin-guide/dynamic-debug-howto.html) · [Dynamic Debug internals (jump labels)](https://kernel-internals.org/modules/dynamic-debug/)
- [.NET — Collect and view EventSource traces (keywords/level)](https://learn.microsoft.com/en-us/dotnet/core/diagnostics/eventsource-collect-and-view-traces) · [EventPipe overview](https://learn.microsoft.com/en-us/dotnet/core/diagnostics/eventpipe) · [EventSource.md — рекомендация про > 1K событий/с](https://github.com/microsoft/dotnet-samples/blob/master/Microsoft.Diagnostics.Tracing/EventSource/docs/EventSource.md)

**Формат записи**
- [OpenTelemetry — Logs Data Model](https://opentelemetry.io/docs/specs/otel/logs/data-model/) · [Logs API (Enabled)](https://opentelemetry.io/docs/specs/otel/logs/api/) · [logs/api.md (spec source)](https://github.com/open-telemetry/opentelemetry-specification/blob/main/specification/logs/api.md) · [Issue #3917 — Add `Enabled` to Logger](https://github.com/open-telemetry/opentelemetry-specification/issues/3917) · [Issue #4154 — reporting logger name / bridge name](https://github.com/open-telemetry/opentelemetry-specification/issues/4154)

**Горячий путь, sampling, транспорт**
- [zapcore/sampler.go](https://github.com/uber-go/zap/blob/master/zapcore/sampler.go) · [zapcore docs](https://pkg.go.dev/go.uber.org/zap/zapcore) · [zerolog/sampler.go](https://github.com/rs/zerolog/blob/master/sampler.go) · [Better Stack — log sampling](https://betterstack.com/community/guides/logging/log-sampling/)
- [Erlang/OTP — Logging (overload protection)](https://www.erlang.org/doc/apps/kernel/logger_chapter.html) · [logger_olp.erl](https://github.com/erlang/otp/blob/master/lib/kernel/src/logger_olp.erl) · [Erlang/OTP 21's new logger (ferd.ca)](https://ferd.ca/erlang-otp-21-s-new-logger.html)
- [Log4j2 — Asynchronous loggers](https://logging.apache.org/log4j/2.x/manual/async.html) · [Async logging with Log4j2 (DZone)](https://dzone.com/articles/asynchronous-logging-with-log4j-2)
- [OTel Collector — probabilistic sampler processor](https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/main/processor/probabilisticsamplerprocessor/README.md) · [tail sampling processor](https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/main/processor/tailsamplingprocessor/README.md)
- [JDK Flight Recorder — overview](https://docs.redhat.com/en/documentation/red_hat_build_of_openjdk/17/html/using_jdk_flight_recorder_with_red_hat_build_of_openjdk/openjdk-flight-recorded-overview) · [Using JFR (overhead < 1 %, continuous)](https://medium.com/@chrishantha/using-java-flight-recorder-2367c01deacf) · [LTTng concepts (per-CPU ring buffers, overwrite/flight-recorder)](https://lttng.org/man/7/lttng-concepts/v2.13/) · [Python logging.handlers — MemoryHandler](https://docs.python.org/3/library/logging.handlers.html)

**Модель сигналов и домен**
- [Honeycomb — OpenTelemetry Is Not "Three Pillars"](https://www.honeycomb.io/blog/opentelemetry-is-not-three-pillars) · [IBM — three pillars](https://www.ibm.com/think/insights/observability-pillars) · [Elastic — 3 pillars](https://www.elastic.co/blog/3-pillars-of-observability)
- [Stripe — Canonical log lines](https://stripe.com/blog/canonical-log-lines) · [brandur.org — canonical log lines](https://brandur.org/canonical-log-lines) · [Wide logging](https://blog.alcazarsec.com/tech/posts/wide-logging)
- [Интеграция AI-инспекции с MES/ERP (per-part traceability, OPC UA/MQTT)](https://www.unitxlabs.com/blog/how-to-integrate-ai-visual-inspection-with-your-existing-mes-erp-systems/) · [MES traceability architecture](https://www.pcbcart.com/article/content/mes-traceability-for-pcb-assembly.html)

---

## 6. Наши файлы, к которым это относится

- `multiprocess_framework/modules/process_module/managers/observability_reload.py` — единый путь применения + `observability_effective()` (наш аналог `configuredLevel`/`effectiveLevel`)
- `multiprocess_framework/modules/process_module/commands/builtin_commands.py` — реестр команд; `introspect.observability` **отсутствует**
- `multiprocess_framework/modules/logger_module/enums/log_enums.py`, `configs/logger_manager_config.py`, `core/logger_core.py` — плоская модель `scope × module`, `_decision_cache`, `frame_trace`
- `multiprocess_framework/modules/channel_routing_module/observability/record_forward_channel.py` — живой хвост по `system`-очереди (задокументированный долг QoS)
- `multiprocess_framework/modules/channel_routing_module/observability/observability_hub.py` — `BoundedChannel` + `dropped`, наружу не выведен
- `multiprocess_framework/modules/process_module/configs/telemetry_publish_config.py` — `GATED_METRICS`, единственный существующий publisher-gate (ADR-PM-018)
- `multiprocess_framework/modules/router_module/core/router_manager.py` — 10 точек `_log_debug` на hot path без прореживания
- `backend_ctl/driver.py` — `config_reload` / `logger_sink_enable` / `log_tail` / `observability_tail` / `telemetry_*`
