# План: `Services/otel_export` — OTLP-экспортёр наружу (Ф8.6)

> **Ветка:** `feat/otel-export` · **Slug:** `otel-export`
> **Refs:** [`plans/observability-unified-routing.md`](observability-unified-routing.md) (Task 8.6 — постановка),
> [`plans/observability-roadmap.md`](observability-roadmap.md) (этап 7, Р-7),
> [`plans/observability-closure/plan.md`](observability-closure/plan.md) (Ф1.4 `trace_id`, Ф2.2 контракт секции, Ф3.1 `NumberRecord`, Ф3.3 store-tap батчем — от них здесь зависимости),
> [ADR-LOG-005](../multiprocess_framework/modules/logger_module/DECISIONS.md) (`scope` ≠ `InstrumentationScope`, ревизия Р-6 от 2026-08-11),
> [ADR-PM-028](../multiprocess_framework/modules/process_module/DECISIONS.md) (реализация строкой из конфига).
> **Статус:** **ред. 4 (2026-09-05)** — переработан по [ревью плана](../docs/reviews/2026-09-05_otel-export-plan-review.md) после Ф0–Ф3.1 `observability-closure`.
> **Ф0 ЗАКРЫТА 2026-09-05, вердикт CTO 7/10 ACCEPT WITH CONDITIONS** (условия исполнены Task 0.5).
> Сделано: 0.1 стенд-арбитр · 0.2 шаги 1–2 (extras + ленивый SDK) · 0.3 ветка и якоря · 0.4 контракт · 0.5 условия вердикта.
> Следующее — **Ф1**, она от находок Ф0 не зависит и может стартовать сразу.
> **База ветки: `feat/observability-closure` = `9d9cb8e1`** (2026-09-05, closure Task 3.2 контракт). Порядок слияния: otel → closure → `main`.
> Работа идёт в worktree `.claude/worktrees/otel-f0`: общее дерево занято соседней живой сессией (closure Ф3).
> Границы захода: **Ф0 и Ф1 — сейчас**; Ф2–Ф4 — чередуя со стендами closure; Task 2.4 — строго после closure Task 3.3.
> Состояние closure на 2026-09-05 по коммитам: Ф3 — **3 из 9** (3.0, 3.5, 3.1 закрыты; остаток 3.2, 3.3, 3.4, 3.6, 3.7, 3.8), Ф4–Ф5 не начаты. Полная карта пересечений по задачам — §«Пересечения с observability-closure».

---

## Зачем

Постановка 8.6 называет побочную выгоду главной, и она же — единственная причина
делать задачу: **живой экспортёр доказывает, что словарь полей Ф3 настоящий, а не
заявленный**. Во всех отчётах трека стоит «соответствие модели записи OTel остаётся
**заявленным**» — ни один внешний потребитель наши записи не разбирал ни разу.
Вердикт 2026-09-04 (доказанность продукта 4/10) эту формулировку не снял — и не мог:
снять её может только чужой парсер.

Уже ревью спеки (ред. 2) нашло дефект контракта до единой строки кода: ADR-LOG-005
требовал от экспортёра положить `scope` в `Attributes`, а поле до экспортёра не доезжает
(Р-6, закрыта ревизией ADR 2026-08-11). **Провал приёмки — законный исход фазы, наравне
с успехом.**

---

## Честная оценка (ред. 4)

**Что фаза даёт.** Внешнего арбитра словаря полей и один готовый выход наружу: любой
OTLP-приёмник (Grafana/Loki, Elastic, Datadog, Honeycomb) начинает принимать записи
системы без нашего кода на его стороне. Это портфолио-сигнал и проверка контракта.

**Чего фаза НЕ даёт — сказано, чтобы не ждали.** Это не панель наблюдения (она уже есть:
вкладка, `backend_ctl`, `history_query`), не фича инспекции, не метрики и не трейсы.
Балл вердикта 2026-09-04 напрямую двигают P-1 (инспектор с числами) и P-2 (второе
приложение чужими руками), а не экспорт. Экспорт снимает слово «заявлено» из отчётов и
даёт вторую линзу на плоскость наблюдаемости — не больше.

**Цена.** Оценка, не обещание: Ф0-остаток ~0.5 дня · Ф1 2–3 дня · Ф2 4–5 дней · Ф3 ~2 дня ·
Ф4 ~2 дня — около **2.5 недель агентского времени** плюс стендовые окна владельца. Настоящая
параллельность с closure есть только у Ф0–Ф1 (чистые функции, свой порт `4318`); Ф2–Ф4
конкурируют за стенд `8765` и за внимание владельца, то есть **чередуются, а не идут рядом**.

**Риски по убыванию.** (1) Logs SDK OpenTelemetry живёт под `_logs` и не обещает
совместимости в minor — пин и правило «обновление extras = прогон Ф1 заново».
(2) Объём: подписка `INFO` на 8 процессах гонит по IPC и HTTP то, что сегодня едет только
в файлы (база Ф6: 4.78 МБ/час логов) — Р-4, замер обязателен ДО включения по умолчанию.
(3) Словарь может не выдержать арбитра — законный исход, но его надо уметь принять.
(4) Прецедентов два и оба неполные: плагины ещё не подписывались на хвост наблюдаемости
(подписчики — GUI-процессы), а в `Services/` нет пакета с внешней бинарной зависимостью
по цепочке (`protobuf`). Первый заход всегда вскрывает недостающие крючки — это ожидаемая
находка фазы, а не сбой плана.

**Что я бы не делал.** Не тащить в v1 OTLP-metrics и spans (числовая плоскость —
отдельная работа с метаданными единиц из closure Task 3.4); не строить свою панель;
не править фреймворк «под экспортёр» — находки идут долгом в closure.

---

## Форма решения — как сервис, без костылей

Экспортёр собирается из трёх кирпичей по трём слоям, каждый — стандартной формой своего слоя:

```
Services/otel_export/            SDK без процесса: контракт, конфиг-схема, маппер, Resource, обёртка OTel SDK
        ▲ импортирует
Plugins/io/otel_export/          хост: плагин в GenericProcessApp — подписка, приём, счётчики, команды, останов
        ▲ объявляет
multiprocess_prototype/backend/topology/otel_export.yaml   подключаемый фрагмент топологии (образец observability_sink.yaml)
```

| Решение | Форма | Почему так, а не иначе |
|---|---|---|
| **Хост — плагин, не подкласс `ProcessModule`** | `OtelExportPlugin(ProcessModulePlugin)` в `GenericProcessApp` | так устроены ВСЕ прикладные процессы (`devices`, `telemetry_sink`, `camera_*`); в `Services/` нет ни одного подкласса `ProcessModule` — заводить первый ради экспортёра значило бы плодить вторую форму процесса |
| **Подключение — фрагментом топологии** | `topology/otel_export.yaml` + строка в `app.yaml → base:` | ровно как `observability_sink.yaml`: кто не подключил — не платит ни процессом, ни строками golden-снимков; ноль правок `base.yaml`, ноль флагов в коде (замер 2026-08-23 в шапке фрагмента) |
| **Дверь конфига — регистры плагина** | `OtelExportRegisters(OtelExportConfig)`: производная схемы сервиса. `endpoint` обязателен **в схеме сервиса**, в регистре — дефолт `""` (вердикт CTO, вариант (а)): фреймворк строит managed-регистр **без аргументов** (`plugin_orchestrator.py:325`), и обязательное поле означало бы отсутствие регистра вовсе. Плагин в `configure()` строит `OtelExportConfig(**reg.model_dump())` и на пустом уходит в `error` с адресом ключа | стандартная дверь плагина: ключи из blueprint → Pydantic внутри → readback → GUI-регистры → `set_config`. Секция `observability.otel_export` **отвергнута**: с closure Task 2.2 незнакомый ключ секции на L3 — отказ слоя, на файловых слоях — голос «ВНЕ КОНТРАКТА», а поле схемы без читателя во фреймворке режет страж |
| **Счётчики — числовая плоскость** | `ctx.declare_metric(...)` + `ctx.record_metric(...)`: `received`, `exported`, `skipped_numbers`, `dropped_overflow`, `export_failed`, `resource_evicted` | не своя команда-интроспекция, а числа, которые уже видны в `introspect.telemetry`, `history_query(metric=...)`, GUI. Тождество потерь (3.4) сводится из них |
| **Голоса — окном фреймворка** | `log_windowed` (`windowed_voice.py`, окно из `observability.voices.default_window_sec`) | свой литерал окна запрещён правилом closure «ни одного нового литерала-потолка» |
| **Петля усиления — страж фреймворка** | `ProcessModule.subscribe_observability_tail` отказывает подписке процесса на собственный хвост (`core/process_module.py`, символ `subscribe_observability_tail` — причина названа) | свой фильтр «записи ≠ моё имя» не заводится, пока петля не предъявлена красной (Р-3) |
| **SDK — лениво и с громким отказом** | импорт `opentelemetry.*` только внутри `Services/otel_export/exporter.py` при построении; отсутствие → `health.report_error` + состояние плагина `error` + поле readback `sdk: missing` с командой установки | голый `ImportError` на импорте класса глотает `class_loader` (`log.error → None`), и система об отказе не узнаёт |
| **Команды — авто-регистрация плагина** | `commands = {"otel_export.flush": ..., "otel_export.status": ...}` | попадают в `capabilities` backend_ctl без правок; `set_config` — generic |
| **Останов** | `shutdown(ctx)` → `force_flush(timeout)` → строка `otel flush: N дожато, M потеряно` литералом | до снятия форвардеров процессом и до останова логгера — порядок `ProcessModule.stop()` (:1149) → `_flush_observability()` (:1166) (`core/process_module.py`) |

**Отвергнутые формы (записать в ADR сервиса):**
- *tap внутри каждого процесса* (как store-tap): SDK и HTTP-клиент в каждом из 8 процессов, зависимость через фреймворк, N соединений с коллектором; Resource получился бы бесплатно, но цена выше выгоды;
- *`OtelExportProcess(ProcessModule)` в `Services/`*: вторая форма процесса без прецедента; хост-логика (подписка, команды, останов) уже дана `GenericProcessApp` + `PluginContext`;
- *секция `observability.otel_export`*: см. таблицу — конфликт с контрактом секции.

---

## Универсальность, масштаб, производительность — рекомендации на сентябрь 2026

Принцип один: **OTLP — единственный контракт наружу, всё остальное — конфиг коллектора, не наш код.**
Экспортёр остаётся тонким и переиспользуемым (слой `Plugins/` — словарь повторного
использования между приложениями, ADR-120), а маршрутизация в Loki/Prometheus/Elastic/облако,
персистентная очередь, ретраи и fan-out живут в `otelcol`. Так второе приложение (P-2 вердикта)
получает выход наружу той же строкой в манифесте.

| Ось | Рекомендация | Куда в план | Цена/оговорка |
|---|---|---|---|
| **Универсальность** | Resource по semconv + **`host.name`** (`socket.gethostname()` — экспортёр знает свой хост, IPC локален). Без него флот из трёх устройств на одном коллекторе неразличим: `service.instance.id = incarnation` — счётчик рестартов процесса, `camera_0`/инкарнация 0 с Jetson и с Pi совпадут | Task 1.2 (обязательно) | одна строка; сверить с semconv `host.name` |
| | `service.namespace` = имя приложения (дефолт из `app.yaml`, регистр `service_namespace`) — различает два приложения на одном коллекторе | Task 1.2 (опция, решение владельца) | поле регистра с дефолтом; без второго приложения пользы нет |
| | `schema_url` в Resource (версия semconv) — потребитель знает, по какому словарю читать, и переживает миграции имён | Task 1.2 | константа в сервисе, обновляется с extras |
| | `headers` регистром для токенов облачных приёмников; значения — **только `${ENV}`**, литералов в YAML нет (правило «секреты в env») | Task 0.4 схема, Task 3.1 | readback маскирует `***` |
| **Масштаб** | Один экспортёр на машину = fan-in через брокер: N процессов → 1 HTTP-соединение, батчинг SDK. При 20 процессах (closure Ф4.8) объём — сумма; главный рычаг — **уровень подписки** (`INFO` дефолт) и прицельная подписка `subscribe(<процесс>, <уровень>)`, а не фильтры в экспортёре | Task 3.2 замер на 8 и 20 | политика уровней уже есть во фреймворке — не дублировать |
| | **gzip** на OTLP/HTTP (`Compression.Gzip`, env `OTEL_EXPORTER_OTLP_COMPRESSION`): на Wi-Fi/4G у Pi трафик режется в разы за копейки CPU; регистр `compression`, дефолт `gzip` | Task 0.4 схема, Task 2.4 | измерить CPU на Pi, а не предполагать |
| | Параметры `BatchLogRecordProcessor` (`max_queue_size`, `schedule_delay_millis`, `max_export_batch_size`, `export_timeout_millis` — дефолты SDK 2048/5000/512/30000, **сверить в 0.4**) — регистрами с readback **эффективного** значения, не литералами внутри SDK | Task 0.4 | правило closure «ни одного нового литерала-потолка» |
| | Backpressure: bounded очередь, `drop_oldest`, счётчик и голос; поток роутера **никогда не ждёт сеть** | Task 2.4 (уже) | критерий «1000 записей при закрытом коллекторе» |
| | Эксплуатационная надёжность — на стороне коллектора: `file_storage` + persistent `sending_queue`, retry, экспортёры в бэкенды. Наш код это не дублирует | README стенда, Task 4.3 | contrib нужен только для бэкенд-экспортёров |
| **Производительность** | Горячий путь без Pydantic: записи — `dict`, маппер — прямые обращения; Pydantic только на конфиг (Dict at Boundary) | Task 1.1 | бенч соло ×3: цена маппинга на запись — число в ADR |
| | Кэши объектов SDK: `Resource` по `(proc_name, pid, incarnation)` (есть) и `InstrumentationScope` по `module` (LRU) — SDK создаёт объекты, мы их переиспользуем | Task 1.1/1.2 | небольшой выигрыш, дёшево |
| | Одна трансформация: IPC-dict → protobuf, без промежуточного JSON; JSON — только у файлового экспортёра стенда | Task 2.4 | по построению |
| | Тесты — на `InMemoryLogExporter` SDK и фейке с отказом; коллектор — только на приёмке | Ф1–Ф2 | быстрее и детерминированнее |
| **Направление v2** (не в этом плане) | Числа → **OTLP metrics** из `NumberRecord` (gauge/counter/histogram, temporality `delta`) — после closure Task 3.4 (единица/описание/род), иначе метрики безъединичные | Р-8 | отдельный план |
| | Wide events (`write_event`) → OTel **Events** (`event.name` в логе) — стандартный путь Logs Data Model для структурных событий; `frame_trace` уже даёт 128-битные W3C-совместимые id для будущих spans | Р-8 | как едут wide events по плоскости — не проверял |

**Что не делать ради «масштаба».** Свой persistent-буфер на диске, свои ретраи, свой fan-out
в несколько бэкендов, свой sampler — всё это коллектор делает лучше, а у нас каждая такая
строка — новый предохранитель, который надо доказывать парой инъекций.

---

## Механизмы фреймворка, на которые опирается экспортёр (сверено с кодом 2026-09-05)

| Механизм | Где | Роль здесь |
|---|---|---|
| Словарь OTel для полей записи | докстринг [`log_types.py:17-74`](../multiprocess_framework/modules/logger_module/core/log_types.py#L17-L74) | контракт «что задумано»: `timestamp→Timestamp`, `level→SeverityText`, `message→Body`, `module→InstrumentationScope`, `extra→Attributes`, `trace_id→TraceId`, пятёрка `→Resource` |
| Шкала уровней = OTel `SeverityNumber` | [`levels.py`](../multiprocess_framework/modules/channel_routing_module/levels.py): `SEVERITY_NUMBERS` (:61) 5/9/13/17/21, `UNSPECIFIED = 0` (:79), `severity_of` (:116) | `severity_number` записи копируется в `SeverityNumber` как есть — пересчёта нет |
| Display-вид и нормализаторы | [`record_display.py`](../multiprocess_framework/modules/channel_routing_module/observability/record_display.py): `_ENVELOPE_KEYS` (:40, включает `observed_ts`), `hub_record_to_display` (:210), `log_record_to_display` (:390), `NUMBER_SEVERITY` (:79) | **фактическая форма записи на входе** — вторая половина источника истины |
| Отметка приёма | `stamp_observed` (`record_display.py:113`) | ставит только приёмник; экспортёр — приёмник |
| Resource процесса | `core/process_module.py` ~:630-700 (`proc_name`, `pid`, `fw_version`, `incarnation` из `routing_incarnation`, `recipe`; недостающее пропускается, не `"unknown"`) | пятёрка живёт на `extra.context.*` |
| `trace_id` вне текста | closure Task 1.4: `extra.context.trace_id`, 32 hex W3C | выделенное поле `TraceId`, не атрибут |
| Брокер подписки | [`observability_broker.py`](../multiprocess_framework/modules/process_manager_module/process/observability_broker.py): `subscribe_all` (:92), `_fan_out` (:234), доигрывание свежей инкарнации | экспортёр — обычный подписчик; команда `observability.tail.subscribe_all` |
| Батч-форвардер | [`observability_wiring.py:233`](../multiprocess_framework/modules/process_module/managers/observability_wiring.py#L233) `wire_observability_forward` + [`RecordForwardChannel.push_batch`](../multiprocess_framework/modules/channel_routing_module/observability/record_forward_channel.py#L96) (:96 — **другой файл**, не `observability_wiring`) | log + stats + observation пачкой, **без фильтра по уровню**; error/critical — tap'ами с `min_level` подписчика |
| Отказ подписки на себя | `core/process_module.py`, символ `subscribe_observability_tail` | предохранитель петли — уже во фреймворке |
| Числовая плоскость | `PluginContext.declare_metric/record_metric/gauge` (`plugins/base.py:619-733`), closure Task 3.1 (`NumberRecord`, колонка `metric`) | счётчики экспортёра и их история |
| Голоса окном | [`windowed_voice.py`](../multiprocess_framework/modules/logger_module/core/windowed_voice.py): `log_windowed` (:514) | «одна строка на окно» без своего литерала |
| Прецедент side-effect-процесса | [`observability_sink.yaml`](../multiprocess_prototype/backend/topology/observability_sink.yaml), [`Plugins/io/telemetry_sink`](../Plugins/io/telemetry_sink/) | форма фрагмента, регистры, команды, `shutdown` с итогом |
| Прецедент подписчика хвоста | [`frontend/process.py:94-97, 184-211`](../multiprocess_prototype/frontend/process.py#L184), [`tail_activator.py`](../multiprocess_prototype/frontend/widgets/tabs/observability/tail_activator.py) | хендлер `observability.record`, форма `data.records`/`data.record`, намерение с `MAX_ATTEMPTS = 3` |
| Готовый стенд-арбитр | [`tools/otel_stand/`](../tools/otel_stand/) (Task 0.1) | коллектор `127.0.0.1:4318`, три контроля, раздел «что арбитр НЕ проверяет» |

Baseline 2026-09-05: `grep -r opentelemetry multiprocess_framework/ --include=*.py` = **0** (упоминания в докстрингах — словарь имён, не импорт).

---

## Правила исполнения (наследуют `observability-closure/plan.md` §3 целиком)

1. **Break-injection — на каждое заявленное свойство**, предсказание красных ДО прогона; расхождение — находка в обе стороны. Инъекции — в отдельном worktree, после коммита реализации.
2. **Независимый `tester` — на каждом механизме, ДО кода, один раз на механизм**, в `git worktree` на pre-implementation commit (слепоту даёт дерево, не проза). Красный набор = ТЗ исполнителю. Пропуска тестера нет (решение владельца 2026-08-13); прежняя строка «на Ф2 пропускается» снята.
3. **Пара инъекций на каждый диагностический ответ:** у счётчика — «событие есть, счётчик 0» И «события нет, счётчик растёт»; у readback — «эффекта нет, ответ есть» И наоборот.
4. **Ревью — синхронно** (`run_in_background: false`), вердикт без воспроизведения вход→выход — advisory.
5. **Замер — соло ×3, не под нагрузкой**; в отчёте три числа, не одно.
6. **Документ — часть задачи:** README/STATUS сервиса и плагина, `CONNECTORS.md`/`CONTROL_PANEL.md`/`SINKS_MAP.md` — в том же коммите, что ручка/команда/счётчик.
7. «Невозможно», «гарантировано», «не может» — только рядом с воспроизведением.
8. **Границы слоёв — только CLI `sentrux check .`**, не `mcp__sentrux__check_rules` (проверяет 3 правила из 39 и пишет «All pass»).
9. `if sys.platform` в `Services/otel_export` и `Plugins/io/otel_export` — признак не той задачи. Литералы-потолки — только в регистрах с readback эффективного значения.
10. Пакеты ставит владелец; агент выдаёт команду. Dict at Boundary: записи и конфиг между процессами — `dict`.
11. Коммиты: Conventional Commits + `Why:`/`Layer:` + `Refs: plans/otel-export.md`.

---

## Ф0 — стенд, зависимости, ветка, контракт

### Task 0.1 — приёмник, который умеет ОТКАЗЫВАТЬ, и его слепая зона — **[x] СДЕЛАНА 2026-08-11**
`otelcol` 0.158.0 (ядро, не contrib — втрое легче: 35.4 против 94.8 МиБ на Windows) поднят на
`127.0.0.1:4318`; конфиг и payload'ы контролей — [`tools/otel_stand/`](../tools/otel_stand/).

| Контроль | Ответ | Легло в файл |
|---|---|---|
| валидная запись | `HTTP 200` | да |
| `severityNumber` строкой | **`HTTP 400`** с адресом поля | нет |
| нет конверта `resourceLogs` | **`HTTP 200`** | нет (записей ноль) |
| семантически неверный маппинг (`scope` в `InstrumentationScope`, `trace_id` атрибутом) | `HTTP 200` | **да** |

**Спека ошибалась, и это записано:** отсутствующий `resourceLogs` — законный запрос с нулём
записей, а не ошибка. Следствие для всей фазы: **`200` от арбитра не значит «доставлено»**;
отличить «доехало 100» от «доехало 0» можно только по содержимому файла и тождеству потерь
(Task 3.4). Семантически неверный маппинг коллектор принимает молча — список того, что зелёный
стенд не доказывает, в README стенда; Task 4.2 ограничивает выводы им.
Свежий релиз коллектора — v0.160.0 (2026-09-02); обновлять не нужно, факт записан.

### Task 0.2 — extras `[otel]` с пином + ленивый импорт SDK — **[x] ЗАКРЫТА 2026-09-05 (шаги 1–2)**
> **Расщеплена вердиктом CTO.** Шаг 3 и три критерия про `configure()` / `error` / `ready` описывают
> поведение **плагина**, которого в Ф0 не существует (`plugin.py` пишется в Task 2.1) — в Ф0 они
> физически недостижимы. Перенесены подпунктом в **Task 2.1**. Инъекция «импорт на уровень модуля»
> имеет две половины: сторож `sys.modules` (сделан, Ф0) и «процесс не поднялся» (Ф2.1).
**Level:** Middle+ · **Assignee:** developer · **Layer:** infra, services, plugins
**Files:** `pyproject.toml` (шаг 1 — сделан), `Services/otel_export/exporter.py`, `Plugins/io/otel_export/plugin.py`
**Steps:**
1. **[x]** `otel = ["opentelemetry-sdk>=1.44,<1.45", "opentelemetry-exporter-otlp-proto-http>=1.44,<1.45"]`
   (`3c50e9df`; PyPI 2026-09-05 — по-прежнему 1.44.0). Пин minor обязателен: Logs SDK живёт
   под `opentelemetry.sdk._logs`. Оба пакета `py3-none-any`; единственная бинарная
   зависимость по цепочке — `protobuf` (`manylinux2014_aarch64`, `win_amd64`; на `armv7` —
   `py3-none-any` фолбэк).
2. Импорт SDK — **ленивый**, внутри `Services/otel_export/exporter.py` при построении
   экспортёра; функция `sdk_available() -> tuple[bool, str]` возвращает факт и команду
   установки. На уровне модулей `Services/otel_export/*` и плагина — ни одного
   `import opentelemetry`.
3. Плагин при отсутствии SDK: `configure()` завершается, процесс жив, состояние плагина
   `error` с причиной, `ctx.health.report_error(...)`, readback регистров несёт
   `sdk: "missing: uv pip install --inexact '.[otel]'"`. Команда владельцу:
   `uv pip install --inexact '.[otel]'` (`--inexact` — иначе `uv sync` сносит необъявленное).
**Acceptance criteria (Ф0, закрыты):**
- [x] `[otel]` в `optional-dependencies`; core не изменился ни строкой.
- [x] Ни одного module-level `import opentelemetry` в `Services/otel_export/*` и `Plugins/io/otel_export/*` — сторож разбором AST, не грепом.
- [x] Импорт пакета не тянет `opentelemetry` в `sys.modules`: проверено в подпроцессе, `[]` на всех трёх точках входа.
- [x] `sdk_available() -> (True, "1.44.0")` при установленном SDK; при смоделированном отсутствии — `(False, INSTALL_HINT)`, `ImportError` наружу не выпускается.
- [x] Инъекции I-5 (импорт на уровень модуля) и I-12/I-14 (ответ вместо факта) убили ровно предсказанные тесты.

**Перенесено в Task 2.1** (требует `plugin.py`): без extra процесс `otel_export` поднялся и плагин
в `error` с текстом, называющим extra и команду (предъявить `introspect_plugins`/`system_overview`);
пара — SDK установлен → `ready`, `sdk: "1.44.0"` в readback.
**Out of scope:** gRPC-экспортёр.

### Task 0.3 — ветка, якоря, синхронизация планов — **[x] СДЕЛАНА 2026-09-05**
**Level:** Middle · **Assignee:** developer (солo — 0 строк кода) · **Layer:** docs, infra
**Goal:** убрать расхождение между тремя документами и старой базой ветки до первого коммита кода.
**Steps:**
1. **[x]** `feat/otel-export` пересоздана от `feat/observability-closure`:
   `git branch -f feat/otel-export feat/observability-closure`. Старый единственный коммит
   `3c50e9df` — предок closure (`git merge-base --is-ancestor` = 0), терять было нечего.
2. **[x]** Якоря сверены с кодом — **ред. 4 говорила «сверено 2026-09-05», и это было неверно**:
   восемь якорей из тринадцати не совпали, два из них — не номером строки, а **путём и файлом**.
3. **[x]** `plans/QUEUE.md` §3 и `observability-roadmap.md` §«Этап 7» уже несли ред. 4 в рабочем
   дереве (не закоммичены); сверено по содержимому, закоммичено этим же коммитом.

**Таблица сдвига якорей (факт `git grep`, 2026-09-05):**

| Якорь | Ред. 4 говорила | Факт | Класс |
|---|---|---|---|
| `subscribe_observability_tail`, `stop()`, `_flush_observability`, Resource | `process_module.py` | **`core/process_module.py`** — файла по заявленному пути нет вовсе | путь |
| `RecordForwardChannel.push_batch` | `observability_wiring.py:217-228` | **`record_forward_channel.py:96`** — другой модуль | файл |
| `subscribe_observability_tail` | :1240 | **символ, без номера** | строка |

> **Поправка 2026-09-06.** Номер `:1209`, поставленный этой таблицей вчера, сегодня уже `:1229` —
> closure дописала код выше по файлу. Вдобавок в Ф0 я заменил его в **двух** местах плана из четырёх
> (строки 460 и 600 остались на `:1240`). Оба дефекта лечатся одним: у символов, живущих в файле,
> который правит соседний трек, ссылка — **имя символа**, номер строки не ставится вовсе.
> Остальные якоря таблицы сверены сегодня и держатся: `push_batch` :96, `stamp_observed` :113,
> `hub_record_to_display` :210, `log_record_to_display` :390.
| `stamp_observed` | `record_display.py:150` | :113 | строка |
| `hub_record_to_display` | :247 | :210 | строка |
| `log_record_to_display` | :398 | :390 | строка |
| `_ENVELOPE_KEYS` / `NUMBER_SEVERITY` | :39 / :78 | :40 / :79 | строка |
| `wire_observability_forward` | :233-295 | :233 | верно |
| `observability_broker.subscribe_all` / `_fan_out` | :92 / :234 | :92 / :234 | верно |
| `plugins/base.py` `record_metric` / `declare_metric` | :619-733 | :619 / :733 | верно |
| `frontend/process.py` хендлер / `_on_observability_record` | :94-97 / :184-211 | :97 / :184 | верно |
| `windowed_voice.py` | `windowed_suppressed` | символа нет; есть `log_windowed` (:514) | имя |
| `levels.py` `SEVERITY_NUMBERS` | без строки | :61, `UNSPECIFIED` :79, `severity_of` :116 | уточнено |

**Acceptance criteria:**
- [x] `git merge-base feat/otel-export feat/observability-closure` = `9d9cb8e1` = HEAD closure
  на момент ветвления (`docs(plans): контракт Task 3.2`, 2026-09-05 15:36:52). Предъявлено хэшем.
- [x] Три документа называют ред. 4 и базу `feat/observability-closure`: `otel-export.md` шапка,
  `QUEUE.md` §3, `observability-roadmap.md` §«Этап 7».
- [x] Baseline подтверждён заново: `grep -rE '^\s*(import|from) opentelemetry' multiprocess_framework/ --include=*.py` = **0**.

**Вывод, который дороже самой задачи:** якоря `файл:строка` в этом плане — **расходники, пока
closure в полёте**. Ред. 4 писалась сегодня же и уже промахнулась восемь раз из тринадцати,
причём дважды — путём, а не номером. Первый шаг каждой задачи Ф1–Ф4 сверяет якорь **по имени
символа** (`git grep -n "def <имя>"`), а не доверяет числу в таблице.

**Оговорка по дереву:** рабочее дерево делится с соседней живой сессией (её коммиты
`9bbf74cd`, `9d9cb8e1` — closure Task 3.1/3.2). Общее дерево оставлено на `feat/observability-closure`;
работа Ф0 идёт в отдельном worktree `.claude/worktrees/otel-f0` на `feat/otel-export`.
**Out of scope:** правки кода.

### Task 0.4 — контракт сервиса ДО кода — **[x] ЗАКРЫТА 2026-09-05** (`61bb7496`)
**Level:** Senior · **Assignee:** teamlead · **Layer:** services, plugins
**Goal:** будущий читатель понимает сервис по README + `interfaces.py` + контракт-тестам, не открывая реализацию; исполнители Ф1–Ф2 пишут код под уже названные имена.
**Files:** `Services/otel_export/{__init__.py, README.md, STATUS.md, DECISIONS.md, interfaces.py, config.py, tests/test_contract.py}`, `Plugins/io/otel_export/{__init__.py, README.md, STATUS.md, registers.py}`
**Steps:**
1. `interfaces.py` — Protocol'ы с pre/post в докстринге: `RecordMapper.to_otlp(display_record) -> MappedRecord | None` (None = «не экспортируется», причина в счётчике), `ResourceResolver.resolve(context) -> Resource`, `LogExporter.export(records) -> ExportOutcome(accepted, failed, reason)`, `LogExporter.force_flush(timeout) -> FlushOutcome(flushed, lost)`. Контекст наблюдаемости для сервиса — **минимальный Protocol `ObservabilityPort`** (`log_info/log_warning/log_error`, `record_metric`, `report_error`), которому удовлетворяют `PluginContext` сегодня и `ServiceContext` после closure 4.5; своего контекста сервис не заводит.
2. `config.py` — `OtelExportConfig(SchemaBase)`: `endpoint: str` (обязателен, без дефолта), `level: "INFO"`, `compression: "gzip"`, `headers: dict = {}` (значения — только `${ENV}`, readback маскирует `***`), `service_namespace` (дефолт — имя приложения), параметры батчера `max_queue_size` / `schedule_delay_ms` / `max_export_batch_size` / `export_timeout_ms` (дефолты = дефолтам SDK, **сверить по установленному 1.44.0**), `resource_pool_size`. Регистры плагина (`registers.py`) — те же поля + `FieldMeta` для GUI; одно определение полей, второе — производное (не две таблицы). Readback отдаёт **эффективные** значения (что реально передано в SDK), не сконфигурированные.
3. Словарь счётчиков литералами (имена метрик и их смысл) — в README сервиса и `CONNECTORS.md`; тесты Ф2–Ф3 ссылаются на эти имена.
4. `STATUS.md` = `contract`; `tests/test_contract.py` — читается как документация: «`None` от маппера ⇒ счётчик пропуска растёт», «отсутствующее поле Resource ⇒ атрибута нет».
**Acceptance criteria:**
- [x] README с разделами Purpose / Public API / Usage / Boundaries / Stability; `__all__` совпадает с реэкспортом из `interfaces.py`.
- [x] `python scripts/validate.py` зелёный (exit 0); сервис **зарегистрирован** в `SERVICES` и
  `SERVICES_REQUIRED_INTERFACES` — без регистрации критерий был бы **молчащим детектором**:
  `validate.py` даёт exit 0 и на отсутствующем сервисе.
- [x] `endpoint` без значения → `ValidationError` с адресом поля (тест литералом).

**Исполнение:** слепой тестер (worktree на pre-implementation коммите `5294c20c`) написал **26 красных**
тестов ДО кода; teamlead довёл до зелёного, добавив 27 авторских на опасные места. Итог — **53 зелёных**.
Инъекционная матрица ведущего — **17 заплат, ни одного пустого сторожа**. `sentrux check .` (CLI, не MCP):
36 правил, все проходят.

**Найдено при исполнении — четыре факта, каждый прогоном:**
1. `plugin_orchestrator` строит регистр всегда без аргументов → блокер двери конфига (закрыт Task 0.5).
2. `str(ValidationError)` у pydantic 2.13 печатает вход целиком → отвергнутый токен уезжал бы в `system.log`.
3. `PluginContext` **не** удовлетворяет `ObservabilityPort`: `report_error` живёт на `ctx.health`, не на
   контексте. Разрыв закрывает хост тонким адаптером в Ф2.1 (ADR-OTEL-004).
4. `declare_metric` отвергает точку в имени (ADR-PM-038) — `otel_export.received` уронил бы плагин на старте.

**Ошибки самого плана, снятые сверкой с установленным SDK 1.44.0:** `schedule_delay` = **1000**, а не 5000;
`export_timeout_millis` SDK **игнорирует** (`# Not used. No way currently to pass timeout to export.`),
у `force_flush` — `TODO: Fix force flush so the timeout is used` (issue 4568). Реальный таймаут —
`OTLPLogExporter(timeout=...)`, в секундах. `LogRecord` живёт в `opentelemetry._logs._internal`,
а не в `opentelemetry.sdk._logs`.
**Out of scope:** реализация.

### Task 0.5 — условия вердикта CTO — **[x] ЗАКРЫТА 2026-09-05**
**Level:** Middle · **Assignee:** developer · **Layer:** services, plugins
**Goal:** снять два дефекта контракта, найденных ревью и CTO, до старта Ф2.1.
**Steps:**
1. **[x]** `OtelExportRegisters.endpoint` получает дефолт `""` (вариант (а)). Механизм: у `SchemaBase`
   нет `validate_default`, поэтому регистр строится пустым и все три дороги его создания выживают.
   `FieldMeta` переобъявлен вместе с полем — иначе pydantic v2 стирает метаданные родителя.
2. **[x]** `model_config = ConfigDict(hide_input_in_errors=True)` на `OtelExportConfig`. Проверено:
   pydantic мёржит `model_config` по MRO, `validate_assignment` родителя не затирается.
3. **[x]** Пин-тест развёрнут: сторожил **опасность** («pydantic печатает вход»), стал сторожить
   **защиту** — секрет отсутствует в `str(exc)` на трёх дорогах, имя ключа `headers` остаётся.
4. **[x]** README и ADR-OTEL-005 переписаны: `format_validation_error` — форматтер читаемости,
   **не** предохранитель; «единственный безопасный способ» снято.
**Acceptance criteria:**
- [x] 53 зелёных сохранены; инъекция «снять флаг» даёт красный с текстом «секрет утёк в str(exc) целиком».
- [x] `hidden=True` **не** годится (замер CTO): `can_modify` (`field_meta.py:234`) смотрит только
  `readonly`; `readonly=True` закрывает лишь live-write и делает поле нередактируемым.
- [x] `hide_input_in_errors` закрывает **все три** дороги, включая `from_plugins`, до которой ни плагин,
  ни форматтер не дотягиваются.
**Out of scope:** правки фреймворка (три долга вынесены в `observability-closure`).

---

## Долги во фреймворк, найденные в Ф0 (идут в `observability-closure`, здесь НЕ чинятся)

| # | Дефект | Репродукция | Цена молчания |
|---|---|---|---|
| Д-1 | `plugin_orchestrator._collect_register_schemas` строит managed-регистр **без аргументов** и глотает исключение `except Exception` | `plugin_orchestrator.py:325`, `instance = reg_item()` | плагин с обязательным полем регистра теряет GUI-дверь молча, одной строкой `log_error` на буте |
| Д-2 | `RegistersManager.set_field_value` возвращает `str(exc)` — печатает **вход** для любого регистра с валидатором секретов | `manager.py:165`; четыре вызывающих печатают строку | отвергнутый токен в `system.log`; починка — `errors(include_input=False)` |
| Д-3 | `FieldMeta` докстринг обещает `can_modify() → False` при `hidden`, код смотрит только `readonly` | `field_meta.py:95` против `:234` | защита, которой нет; ревьюер предложил её как рабочую |
| Д-4 | `generic_process_config.from_plugins` строит `reg_cls(**reg_fields)` **без `try`** | `generic_process_config.py:229` | плохой фрагмент роняет сборку топологии, а не плагин; возможно намеренно, но нигде не названо |
| Д-5 | `scripts/validate.py` кладёт «нет `interfaces.py`» в `warnings`, а `main()` возвращает `1 if errors else 0` | `validate.py:211` | **гейт стандарта слоя молчащий**: `make gate` зелёный на сервисе без контракта. Сегодня без `interfaces.py` один сервис — `device_hub`, и его нет в `SERVICES_REQUIRED_INTERFACES`, значит правка `warnings → errors` бесплатна. Идёт **отдельным коммитом**, не внутри задачи фазы |

---

## Ф1 — маппер (чистые функции, без сети)

> Тестер — на каждом механизме Ф1 (маппер, Resource-пул, фильтр плоскостей), до кода, в worktree.

### Task 1.0 — форма записи на входе: живой снимок, а не догадка **(блокирует Ф1)**
**Level:** Middle+ · **Assignee:** developer · **Layer:** docs
**Goal:** приложить к плану настоящие записи с настоящей дороги. Ред. 1 описывала маппер над плоским `extra` и была неверна на обеих дорогах; ред. 3 не знала `kind=observation`, `origin`, `NUMBER_SEVERITY`.
**Files:** `docs/audits/<дата>_otel-input-shape.md`
**Steps:**
1. Снять **обе формы** и назвать разницу:
   - **форвардер** (что получит экспортёр) — `observability_tail` MCP на ближайшем стенде closure (5 минут, свой стенд не поднимать), уровень `DEBUG`; по одной записи `kind=log`, `kind=error`, `kind=stats` (агрегат И одиночная метрика), `kind=observation`;
   - **стор** (для сверки тождества в 3.4) — `history_query` по живому `observability.db` без стенда; у стора `origin` поднят на верх записи, у форвардера — нет.
   **Договорённость 2026-09-05 с сессией closure:** сырьё снимает она на стенде живой приёмки closure Task 3.2, **после merge 3.2** (3.2 меняет состав потока, не форму записи; доля потока по родам обязана отражать то, что увидит экспортёр), в `tools/otel_stand/samples/<hash>/` — `tail_debug.json`, `history_rows.json`, `history_series.json`, `introspect_observability_camera_0.json` (ключи счётчиков форвардера для 3.4), `README.md` с хэшем, рецептом, длительностью и числом записей по kind. Карточку аудита пишет этот план. Рода, которого в окне не оказалось, не эмулировать — назвать.
2. Зафиксировать происхождение `extra`: tap-дорога — `{"context": LogRecord.extra}` (`record_display.py:437`); hub-дорога — остаток вне `_ENVELOPE_KEYS` (`:309, :341`). **Итог: `trace_id`, пятёрка Resource и `origin` лежат на `extra.context.*`.**
3. Зафиксировать отсутствующие поля: `scope` в display-вид не копируется; `observed_ts` появляется только у приёмника; `kind` — в конверте.
4. Конверт сообщения: `data.records` (пачка) против `data.record` (одна) — `frontend/process.py:194-197`.
5. Назвать доли живого потока по родам за 5 минут (ожидание по стенду 3.5: числовых записей не меньше, чем логов).
**Acceptance criteria:**
- [~] Снимки форм приложены целиком, не пересказом; обе дороги рядом с diff'ом полей —
  [`docs/audits/2026-09-06_otel-input-shape.md`](../docs/audits/2026-09-06_otel-input-shape.md).
  **Частично, и это названо в карточке §6:** покрыты `observation` и `stats`-агрегат на обеих
  дорогах, `log` только на форвардере. **НЕ покрыты:** `kind=error` (ни на одной дороге, хотя
  README снимка обещает 6 за окно) и `stats` с `aggregate=false` (все 68 записей — агрегаты).
  Непокрытое выведено из кода общего нормализатора `log_record_to_display` и помечено как
  выведенное. Просьба к closure на ближайшем стенде: одна `error`-запись и одна `stats`
  с `aggregate=false`.
- [x] Тесты Ф1 строятся на **этих** снимках; синтетический плоский словарь как вход запрещён —
  зафиксировано §7 карточки.

**Найдено разбором (2026-09-06), три поправки к посылкам плана:**
1. **«У стора `origin` поднят на верх записи» — ОПРОВЕРГНУТО кодом.** В `CREATE TABLE records`
   колонки `origin` нет вовсе (`observability_store.py:237-247`), `grep origin` по файлу стора
   пуст. `origin` лежит в `extra.context` на **обеих** дорогах. Задело Task 3.4: тождество
   сверяется одинаково, а не «зная, что у стора наверху».
2. **«Пятёрка Resource на `extra.context`» — неверно.** Там шесть полей другого состава:
   `proc_name`, `pid`, `fw_version`, `incarnation`, `recipe`, `origin`. **`host.name` среди них
   нет** — значит Task 1.2 берёт его из окружения экспортёра, а не из записи.
3. **`extra` НЕ однороден:** вложенный `{"context": {...}}` у `log`/`error`, плоский у
   `observation` (`writer`/`metric`/`value`) и `stats` (`aggregate`/`metrics`/`total_count`/
   `window_ts`/`bucket_bounds`). Маппер Task 1.1 — две ветки, не одна.
4. `trace_id` — **0 вхождений** на обеих дорогах. Честно: «не наблюдалось в окне», не «невозможно».
**Out of scope:** правки фреймворка ради удобной формы.

## Ф1 — ЗАКРЫТА 2026-09-06 (`13289691`)

101 зелёный (было 27 красных / 57 зелёных), 28 из 28 приёмочных Ф1, ни один из 57 прежних не
покраснел. `ruff` чисто, `sentrux check .` 36 rules pass, импорт маппера не тянет `opentelemetry`.

**Инъекционная матрица ведущего — 11 заплат, ни одной настоящей пустой зоны.** Восемь по плану
плюс три перегона. Предсказания записаны до прогона, база сверена числом (101) без `-k`.

| # | Свойство | Предсказано | Умерло | Итог |
|---|---|---|---|---|
| M1 | `round` → `int` в `ts`→нс | 2 | **0** | **заплата в пустую ось**, см. ниже |
| M1b | `round` → `Decimal(str(ts))` — настоящая ось | 2 | 1 | сторож есть, один |
| M2 | снята половина `kind in NUMERIC_KINDS` в `to_otlp` | 0 | 0 | совпало: половина избыточна |
| M3 | снята половина `severity == NUMBER_SEVERITY` | 1 | 1 | совпало |
| M4 | `severity_number` всегда 0 | 2 | 1 | сторож один, не два |
| M5b | снята вся проверка формы `trace_id` | 2 | **21** | заплата слишком груба — мерила падучесть |
| M5c | принят нулевой `trace_id` (утверждение докстринга) | 1 | 1 | совпало |
| M6 | `record.kind` не кладётся в атрибуты | 2 | 4 | сторожей больше, чем думал |
| M7 | вытеснение FIFO вместо LRU | 1 | 1 | совпало |
| M8 | счётчик вытеснения не растёт | 2 | 2 | совпало |

**Две находки о самой матрице, а не о предмете — обе мои ошибки:**

1. **M1 дал ноль, потому что ось пуста, а не потому что сторожа нет.** При `ts ≈ 1.79e9`
   произведение `ts * 1e9 ≈ 1.79e18` **выше точного диапазона float64** (`2**53 ≈ 9.0e15`), дробной
   части у него уже нет, и `round` с `int` совпадают на **0 из 144** записей снимка. Настоящая ось
   решения Р-4 — `Decimal(str(ts))`: расхождение на **138 из 144**, по ~92 нс. Перегон M1b по ней
   даёт красный. **Ноль от инъекции имеет и пятое прочтение: заплата легла в место, где свойство
   не может измениться.**
2. **M5b убил 21 тест не тем механизмом.** Сняв проверку формы целиком, я пустил не-строку в
   `.lower()` — каскад `AttributeError`. Это замер падучести, а не свойства. Прицельная M5c по
   одному утверждению докстринга даёт ровно 1.

**Честно про M2.** Ноль предсказан и подтверждён: в `to_otlp` половина `kind in NUMERIC_KINDS`
избыточна — вторая половина (`severity == NUMBER_SEVERITY`) ловит всё на сегодняшних данных.
Это не дефект (защита в глубину), но и не сторожёная ветка. Ветку `kind` в `split_exportable`
(строка 175) стережёт авторский тест — она не та же самая.

**Что Ф1 не проверила ни разу на живых данных** (в снимке этих форм нет): `trace_id` (0 вхождений),
`observed_ts` (0/144), род `error`, `stats` с `aggregate=false`. Всё проверено на записях,
**выведенных** из нормализатора фреймворка. Догрузка — просьба к closure, карточка 1.0 §6.

**Ловушка для Ф2, воспроизведена запуском на SDK 1.44.0.** `Resource.merge` при РАЗНЫХ непустых
`schema_url` пишет отказ в stdlib-`logging` (процесс фреймворка его не слышит) и **молча возвращает
только свою сторону** — атрибуты второй исчезают. С дефолтным ресурсом SDK конфликта нет (у него
`schema_url` пуст). Обёртка Ф2 обязана сверять схему явно.

**Долг Ф0, всплывший здесь:** `test_contract_acceptance.py::test_a4_status_declares_contract_state`
требует подстроку `contract` в `STATUS.md` где угодно. Состояние сервиса больше не `contract`, но
обновить STATUS нельзя — тест краснеет, а править чужой тест реализатору запрещено. Посылка теста
истекла; нужен позитивный якорь вместо подстроки. Не чинил: это правка теста Ф0, отдельным заходом.

### Решения Ф1, принятые по вопросам независимого тестера (2026-09-06)

Тестер отработал ДО кода и честно назвал два места, где он **угадывал**, плюс две неоднозначности
контракта. Правило требует решить, чья модель верна, и записать почему — вот решения.

| # | Вопрос | Решение | Почему |
|---|---|---|---|
| Р-1 | Имя конкретного класса маппера | **`DisplayRecordMapper`** в `mapping.py` | тестер угадал `RecordMapper` — но это имя занято Protocol'ом в `interfaces.py:152`. Одноимённый конкретный класс в том же пакете ломает `isinstance(x, RecordMapper)`, ради которого Protocol и объявлен `@runtime_checkable`. Коллизия не стилистическая |
| Р-2 | Имя конкретного класса резолвера | **`PooledResourceResolver`** в `resources.py` | то же основание (`interfaces.py:180`); «Pooled» называет то, что отличает его от Protocol'а — пул с вытеснением |
| Р-3 | Как хост читает счётчик вытеснения | свойство **`evicted`** на резолвере; хост публикует его точкой `otel_export.resource_evicted` | прецедент фреймворка: `BoundedChannel.dropped` / `.written` — читаемое свойство у механизма, имя точки у хоста. Тестер угадал `resource_evicted` на самом резолвере: тогда локальное имя тащит префикс плоскости внутрь механизма |
| Р-4 | `ts` (float, секунды) → `Timestamp` (int, нс) | **`round(ts * 1e9)`** | альтернатива `Decimal(str(ts))` даёт ДРУГОЕ число (расхождение ~108 нс на образце) и выглядит точнее — но источник её точности не имел: у float64 на эпохе ~1.79e9 с шаг равен 2^-22 с ≈ **238 нс**. `Decimal(str())` изобретает разряды, которых в данных нет |
| Р-5 | Кто считает разбивку пропуска в 1.3 | **именованная функция** `split_exportable(records) -> (to_send, skipped_by_kind)` в `mapping.py` | тестер посчитал разбивку в самом тесте, сгруппировав батч по `kind` — и был прав, что `interfaces.py` возлагает учёт `None` на вызывающего. Но критерий, который тест вычисляет сам, согласен сам с собой. Разбивку обязан отдавать предмет проверки, иначе Task 1.3 непроверяема |

**Что тестер оставил непроверенным (его слова, не мои):** идентичность объекта `Resource` при
повторном `resolve()` тем же ключом (счётчик проверен, кэш — нет); дефолт `service_namespace=""`
и его разрешение в имя приложения — вероятно, обязанность хоста, а не `resources.py`.

### Task 1.1 — `record_to_otlp`: display-запись → OTel LogRecord
**Level:** Senior · **Assignee:** teamlead · **Layer:** services
**Files:** `Services/otel_export/mapping.py`, `tests/test_mapping.py`
**Предусловие:** на вход маппера попадают только `kind ∈ {log, error}` — числовые роды снимает фильтр 1.3 ДО маппера; маппер на `severity == "number"` **отказывает** (`None` + причина), а не гадает.
**Steps:**
1. `ts→Timestamp`, `severity→SeverityText`, `severity_number→SeverityNumber` (копия, шкала уже OTel — `levels.py`), `message→Body`, `module→InstrumentationScope`, `observed_ts→ObservedTimestamp`, **`extra.context.trace_id→TraceId`** (32 hex W3C, выделенное поле).
2. `Attributes` — остаток `extra.context` **после изъятия**: `trace_id`, пятёрки Resource (её берёт 1.2) и **`origin`** (внутренний маркер маршрутизации того же класса, что `scope`). Структурные наборы в атрибуты не сваливать (`log_types.py:52-56`).
3. `kind` (конверт) → атрибут `record.kind`: без него `log`/`error` на выходе неразличимы.
4. Битый/пустой `trace_id` → поля нет; нулями не заполнять.
**Acceptance criteria:**
- [ ] Тест на каждую строку таблицы, значения литералами; вход — снимок из 1.0.
- [ ] `trace_id`, `origin` и Resource-поля **не** остались в `Attributes` — **и к этому обязательна
  пара, иначе критерий пустой.** Замер 1.0 (2026-09-06): у **18 из 18** записей `kind=log` снимка
  остаток `extra.context` после изъятий **пуст**, состав ровно шесть полей
  (`proc_name`, `pid`, `fw_version`, `incarnation`, `recipe`, `origin`), из них пять забирает
  Resource (1.2), шестое изымается здесь. То есть реализация `attributes = {}` **всегда** проходит
  этот критерий наравне с правильной — он согласится с любым ответом, включая «ничего».
  **Пара:** синтетическая запись с лишним ключом в `extra.context` (например `request_id`) —
  ключ обязан **дойти** до `Attributes`. Без неё изъятие не отличимо от «атрибутов не бывает».
- [ ] `Attributes` реальной записи снимка — **литералом** `{"record.kind": "log"}` и ничего
  больше: `record.kind` (шаг 3) остаётся единственным атрибутом на сегодняшнем составе `context`.
- [ ] Инъекция: читать `extra.trace_id` вместо `extra.context.trace_id` → красный (дефект ред. 1).
- [ ] Инъекция: пересчитать `severity_number` по рангу 0…4 → красный адресно в тестах severity (для логов; у числовых записей 0 законен — они сюда не доходят, тест предусловия отдельный).
- [ ] Отказ на `severity == "number"` — тест литералом.
**Out of scope:** метрики, spans, `scope` (Р-6).

### Task 1.2 — `Resource` на ЗАПИСЬ, а не на провайдер
**Level:** Senior · **Assignee:** teamlead · **Layer:** services
**Files:** `Services/otel_export/resources.py`, tests
**Steps:**
1. Ключ пула — `(proc_name, pid, incarnation)` из `extra.context`.
2. Semconv: `proc_name→service.name`, `fw_version→service.version`, `incarnation→service.instance.id`, `pid→process.pid`, `recipe` — свой атрибут `inspector.recipe`.
3. **`host.name`** из `socket.gethostname()` — атрибут экспортёра, не записи (IPC локален, все записи с той же машины). Без него флот устройств на одном коллекторе неразличим: `incarnation` — счётчик рестартов процесса, а не идентификатор машины. `service.namespace` — из регистра `service_namespace` (дефолт — имя приложения). `schema_url` Resource — версия semconv константой сервиса.
4. **Отсутствующее поле пропускается**, не `"unknown"` — правило источника (`process_module.py` ~:640), экспортёр его сохраняет.
5. Предел размера пула из конфига (`resource_pool_size`), вытеснение LRU, счётчик `resource_evicted`. Кэш `InstrumentationScope` по `module` — тем же LRU.
6. API SDK 1.44 (Р-1, проверено живьём 2026-08-11): `ReadableLogRecord(log_record, resource, instrumentation_scope, limits)`; класса `LogRecord` в публичном экспорте `_logs` нет.
**Acceptance criteria:**
- [ ] Две записи разных процессов → два разных `Resource` (литералы); у обоих один `host.name` и один `service.namespace`.
- [ ] Запись без `fw_version` → атрибута `service.version` **нет**.
- [ ] Пул не растёт без предела: N+1 источник вытесняет самый старый, `resource_evicted` = 1; пара: при N источниках счётчик 0.
- [ ] Инъекция: свести пул к единственному `Resource` → красный в тесте двух процессов при зелёных тестах 1.1.
- [ ] Инъекция: снять `host.name` → красный в тесте «две записи с двух хостов различимы» (вход — два снимка с разным `host.name`, эмулируется параметром резолвера).
**Out of scope:** `os.*`, `process.executable.*`, `container.*` — полей, которых не собираем и не нужны для различения.

### Task 1.3 — числовая плоскость не экспортируется, и это видно числом
**Level:** Middle+ · **Assignee:** developer · **Layer:** services
**Files:** `Services/otel_export/mapping.py` (тот же файл, что 1.1 — **не параллелить**), tests
**Steps:** фильтр родов ДО маппера: `kind ∈ {stats, observation}` (обе формы `severity == "number"`, `severity_number == 0`) → не отправляется, причина `numbers` с разбивкой по kind. Логи и ошибки проходят. Числа приходят при **любом** уровне подписки — батч-форвардер уровнем не фильтрует (`push_batch`), так что фильтр обязан быть здесь, а не в настройке подписки.
**Acceptance criteria:**
- [ ] Пачка из снимка 1.0 (log + error + stats-агрегат + stats-одиночная + observation) → ушли ровно log и error; пропуск = 3 с разбивкой `{stats: 2, observation: 1}`.
- [ ] Инъекция: снять `observation` из фильтра → красный (дефект ред. 3).
- [ ] Инъекция: убрать инкремент → красный.
- [ ] После Ф2 — приёмка живьём: за 5 минут стенда `skipped_numbers > 0` при `exported > 0` (стенд 3.5 дал 1036 числовых строк за прогон — пропуск нулём быть не может).
**Out of scope:** OTLP-metrics вторым сигналом (см. Р-8).

---

## Ф2 — хост: плагин, подписка, доставка

> Тестер — на каждом механизме (приём+отметка, слышимость отказа, асинхронная доставка, жизненный цикл), до кода, в worktree. Наблюдаемость механизмов снаружи — счётчики числовой плоскости и readback регистров.

### Task 2.1 — `OtelExportPlugin`: приём записей, намерение брокеру, отметка приёма
**Level:** Senior · **Assignee:** teamlead · **Layer:** plugins
**Files:** `Plugins/io/otel_export/plugin.py`, `registers.py`, tests
**Steps:**
1. `configure(ctx)`: регистры → `OtelExportConfig`; проверка SDK (0.2); построение маппера/пула/экспортёра из `Services/otel_export`.
2. `start(ctx)`: `ctx.router_manager.register_message_handler("observability.record", ...)` — форма `data.records`/`data.record` как у `frontend/process.py:184-211`; хендлер зовёт `stamp_observed(records, time.time())` — экспортёр и есть приёмник, отметку ставит только он; **не перетирает** уже стоящий `observed_ts`.
3. Намерение брокеру: команда `observability.tail.subscribe_all` с `level` из регистров, адресат `ProcessManager`; триггер назвать явно (плагин стартует в процессе, уже порождённом PM); подтверждение — ответ брокера `success`; отказ/молчание — повтор с пределом `MAX_ATTEMPTS = 3` (дисциплина `tail_activator`), после — голос ERROR + `health.report_error`.
4. `shutdown(ctx)`: `unsubscribe_all` симметрично, затем `force_flush` (2.4).
5. Команды: `otel_export.status` (readback: состояние SDK, endpoint эффективный, счётчики), `otel_export.flush`.
6. Счётчики — `ctx.declare_metric` + `ctx.record_metric`, имена из словаря Task 0.4 (нейтральные, без CV-лексики — closure 4.6). Если closure 3.4 уже в дереве — объявлять с `unit`/`description`/`kind`; если нет — имена, и плагин вносится в список миграции closure 3.4 явной строкой в её спеке.
**Acceptance criteria:**
- [ ] Тест на настоящем `GenericProcessApp` (не на фейках): хендлер зарегистрирован, адрес подписчика == имя процесса.
- [ ] Счётчики видны в `introspect_telemetry(otel_export)` и `history_query(metric="otel_export.received")` — предъявить ответ.
- [ ] `observed_ts` проставлен у всех принятых записей; уже стоящий — сохранён.
- [ ] Намерение подтверждено ответом брокера; предъявить ответ. Пара: брокер недоступен → три попытки, голос один, состояние `degraded`.
- [ ] Инъекция: убрать `stamp_observed` → красный. Инъекция: `subscriber` константой → красный в тесте адреса.

**Перенесено из Task 0.2 (в Ф0 недостижимо — требует `plugin.py`):**
- [ ] Без установленного extra `[otel]`: процесс `otel_export` **поднялся**, плагин в состоянии `error`
  с текстом, называющим extra и команду `uv pip install --inexact '.[otel]'`; предъявить фактический
  ответ `introspect_plugins` / `system_overview`.
- [ ] Пара: SDK установлен → состояние `ready`, `sdk: "1.44.0"` в readback.
- [ ] Инъекция: перенести импорт SDK на уровень модуля → **процесс не поднялся ИЛИ причина не названа**
  (вторая половина инъекции I-5; первая — сторож `sys.modules` — закрыта в Ф0).

**Перенесено из Task 0.5 (вердикт CTO, открытый вопрос фазы):**
- [ ] Есть ли у плагина путь записи в managed-регистр через `ctx`. Критерий:
  `introspect_registers otel_export` показывает `endpoint` **из фрагмента**, не `""`.
  Если пути нет — долг Д-1 (`plugin_orchestrator.py:325`) становится **условием** этой задачи,
  а не долгом closure, и GUI-дверь до его починки показывает дефолты.
**Out of scope:** свой поток приёма, heartbeat, команды сверх двух.

### Task 2.2 — отказ доставки СЛЫШЕН (перед 2.3 и 2.4)
**Level:** Senior · **Assignee:** teamlead · **Layer:** services, plugins
**Files:** `Services/otel_export/exporter.py`, `Plugins/io/otel_export/plugin.py`, tests
**Steps:**
1. Отказы SDK уходят в stdlib-`logging` → `logging.lastResort` (у корневого логгера процесса фреймворка нет хендлеров, `std_facade.py:6-8`) — то есть при закрытом коллекторе экспортёр **молчит**. Перехватить исход `export()` по возвращаемому результату, не по чужому логу.
2. Отказ → `export_failed` (+число записей) через `ctx.record_metric` + голос **`log_windowed`** (ключ `otel_export.export_failed`, окно политики), текст несёт endpoint и число подавленных.
**Acceptance criteria:**
- [ ] Живьём: коллектор закрыт → `export_failed` растёт, в журнале одна строка на окно с числом подавленных; предъявить строку и число. Пара: коллектор открыт → 0 и ни одной строки.
- [ ] Инъекция: вернуть отказ в голый stdlib → тест слышимости красный. Инъекция: свой литерал окна вместо `log_windowed` → тест «окно из политики» красный.
**Out of scope:** ретраи сверх тех, что делает SDK.

### Task 2.3 — петля усиления: страж фреймворка предъявлен, свой не заводится
**Level:** Middle+ · **Assignee:** developer · **Layer:** plugins, docs
**Goal:** записи самого экспортёра не должны экспортироваться, иначе отказ сети кормит сам себя. Фреймворк уже отказывает процессу в подписке на собственный хвост (`core/process_module.py`, символ `subscribe_observability_tail`, причина «петля»); задача — **предъявить**, что это работает для нашего подписчика, а не поверить.
**Steps:** живьём: `subscribe_all` от `otel_export` → у процесса `otel_export` в журнале отказ с причиной; собственные записи экспортёра (`module=otel_export`) в файле коллектора отсутствуют при том, что в `system.log` они есть. Число исходящих попыток за 60 с при закрытом коллекторе не растёт от собственных голосов.
**Acceptance criteria:**
- [ ] Отказ подписки на себя предъявлен строкой журнала; записи `module=otel_export` в `otel_records.json` = 0 при ≥ 1 в файлах логов (пара).
- [ ] Если петля **воспроизводится** (страж не сработал) — это находка фреймворка: долг в closure, здесь — временный фильтр по `process == своё имя` с датой снятия и тестом лавины в daemon-потоке с дедлайном join.
- [ ] Если не воспроизводится — предохранитель не заводить, записать в ADR сервиса (правило «ноль красных = лишний слой»).
**Out of scope:** глушение собственных логов экспортёра.

### Task 2.4 — асинхронная отправка, переполнение и место в останове **(после closure Task 3.3)**
**Level:** Senior · **Assignee:** teamlead · **Layer:** services, plugins
**Files:** `Services/otel_export/exporter.py`, `Plugins/io/otel_export/plugin.py`, tests
**Зависимость:** closure Task 3.3 строит ту же форму для store-tap (bounded-канал, ёмкость из политики, `drop_oldest`, счётчик с голосом, `flush: N записано, M потеряно`). Здесь — та же форма и та же лексика, иначе на одной плоскости два разных предохранителя.
**Steps:**
1. `BatchLogRecordProcessor` поверх `OTLPLogExporter` (HTTP `/v1/logs`, `compression` из регистров, дефолт gzip); параметры батчера — из регистров (0.4), readback эффективных значений.
2. Переполнение считать **своим** счётчиком `dropped_overflow` ДО передачи в процессор; голос `log_windowed`.
3. `shutdown`: `force_flush(export_timeout_ms)` → строка `otel flush: N дожато, M потеряно` литералом, до снятия форвардеров и останова логгера.
**Acceptance criteria:**
- [ ] Приём 1000 записей при закрытом коллекторе не блокирует поток роутера дольше, чем без экспортёра — три числа соло до/после.
- [ ] Переполнение → `dropped_overflow` растёт, строка одна на окно; пара: ёмкость не достигнута → 0.
- [ ] Исход финального flush записан; предъявить строку из файла процесса.
- [ ] gzip против без сжатия: байты на проводе и CPU процесса `otel_export` — по три числа на dev-стенде; на Pi/Jetson — когда появится устройство (до тех пор дефолт gzip стоит на доводе, не на замере — записать так).
- [ ] Инъекция: фейковый экспортёр **обязан уметь отказывать** — иначе тест переполнения зелен по построению; инъекция «фейк всегда успешен» → тест переполнения красный.
**Out of scope:** persistent queue, дедупликация, гарантия доставки.

### Task 2.5 — жизненный цикл подписки: рестарт самого экспортёра
**Level:** Senior · **Assignee:** teamlead · **Layer:** plugins, docs
**Steps:** по коду брокера (`observability_broker.py:92-270`) разобрать три сценария: (а) штатный рестарт — `shutdown` снял намерение, новый старт объявил; (б) экспортёр убит SIGKILL — намерение живо, процесса нет; (в) процесс поднялся, плагин в `error` (нет SDK) — намерение не объявлено, форвардеров нет.
**Сценарий (б) — предмет closure Task 4.4** (реестр намерений в брокере, `forget_session`, replay на
`instance.started`): здесь не чинить и не обходить своим механизмом.
**Acceptance criteria:**
- [ ] Живьём: `process_restart_verified(otel_export)` → хвост восстановился; записи до/после.
- [ ] Сценарий (б): если closure 4.4 уже в дереве — проверить его механизмом (форвардеры-сироты сняты, через сколько — число); если нет — назвать, кто снимает сироты сегодня и через сколько, и записать ссылкой на 4.4, не долгом «кому-нибудь».
- [ ] Сценарий (в): плагин в `error` → намерение не объявлено, форвардеров у источников нет (пара с (а)).
**Out of scope:** правки брокера (это closure 4.4).

---

## Ф3 — включение, цена, readback

### Task 3.1 — включается фрагментом топологии; по умолчанию отсутствует
**Level:** Middle+ · **Assignee:** developer · **Layer:** prototype
**Files:** `multiprocess_prototype/backend/topology/otel_export.yaml`, `multiprocess_prototype/app.yaml` (закомментированная строка-образец, как у `observability_sink`), `Plugins/io/otel_export/registers.py`
**Steps:** фрагмент по образцу `observability_sink.yaml`: процесс `otel_export`, `process_class: multiprocess_prototype.generic_process_app.GenericProcessApp`, `priority: low`, плагин `Plugins.io.otel_export.plugin.OtelExportPlugin` с `endpoint` в записи плагина. **`endpoint` — обязательный ключ без дефолта**: `127.0.0.1:4318` годится только dev-стенду, на Jetson/Raspberry коллектор стоит на другой машине (§«Три платформы»).
**Acceptance criteria:**
- [ ] Манифест без фрагмента → система как раньше; `sys.modules` без `opentelemetry` снимается **в названном процессе** (`camera_0`) через `send_command`, не в оркестраторе.
- [ ] С фрагментом → процесс поднялся, намерение объявлено, `capabilities` показывает `otel_export.status`/`flush`.
- [ ] `endpoint` из фрагмента доезжает: пара значений, где ветки расходятся (не дефолт против дефолта), предъявлена адресом фактического HTTP-запроса.
- [ ] Фрагмент без `endpoint` → процесс поднялся, плагин в `error` с адресом ключа (не тихий дефолт).
  **Механизм этого критерия установлен вердиктом CTO 2026-09-05, вариант (а)** — прежняя формулировка
  задачи («`endpoint` — обязательный ключ **регистра** без дефолта») делала критерий **недостижимым**:
  фреймворк строит managed-регистр без аргументов (`plugin_orchestrator.py:325`), и до состояния `error`
  дело не доходило — регистр умирал раньше, а исключение глоталось `except Exception`.
  Сейчас: обязательность живёт **в схеме сервиса** `OtelExportConfig`, у регистра дефолт `""`,
  и в `error` с адресом ключа плагин уходит из `configure()`, строя
  `OtelExportConfig(**reg.model_dump())`. Дефолт `""` **не** тихий: он не проходит валидатор
  `_endpoint_not_blank` схемы сервиса.
- [ ] Пара к предыдущему: фрагмент **с** `endpoint` → плагин `ready`, и `introspect_registers otel_export`
  показывает значение **из фрагмента**, а не `""` (открытый вопрос Ф2.1 — путь записи плагина в регистр).
**Out of scope:** GUI-вкладка управления, hot-apply endpoint (смена — через `set_config` регистров, если понадобится — отдельная задача).

### Task 3.2 — цена названа числами
**Level:** Senior · **Assignee:** teamlead · **Layer:** docs
**Steps:** одна топология с фрагментом и без; `proc_dict` сверяется ключ-в-ключ (идентичность сборки); дельта объёма IPC (`RecordForwardChannel` written-байты у источников) и CPU процесса `otel_export` — соло ×3. База Ф6: 4.78 МБ/час логов; уровень подписки по умолчанию `INFO`, `DEBUG` — только на время проверки словаря.
**Acceptance criteria:**
- [ ] Дельта объёма и CPU — тремя числами каждая, в плане и ADR.
- [ ] `proc_dict` без фрагмента идентичен HEAD-сборке (golden-снимки рецептов не изменились).

### Task 3.3 — фреймворк не получил зависимости; границы слоёв целы
**Level:** Junior+ · **Assignee:** developer · **Layer:** tests
**Acceptance criteria:**
- [ ] Контракт-тест: `grep opentelemetry multiprocess_framework/ --include=*.py` = 0 импортов. **Честно:** зелен уже сегодня — страж на будущее, не доказательство работы.
- [ ] **CLI `sentrux check .`** зелёный (Services → Plugins → prototype; `Plugins/io/otel_export` импортирует `Services/otel_export`, обратного импорта нет); `python scripts/validate.py` зелёный.

### Task 3.4 — сквозной учёт потерь сходится
**Level:** Senior · **Assignee:** teamlead · **Layer:** docs, plugins
**Goal:** «записи доехали» без учёта потерь не отличает «все» от «половина».
**Steps:** свести тождество `Σ отправлено источниками = принято коллектором + Σ потерь` из уже существующих чисел, ключи — литералами в README:
1. у **источников**: `queue_observability_evicted` (`heartbeat/telemetry.py:251`, `router_manager.py:1775`) и счётчик канала форвардера `observability_forward::otel_export::batch` — из readback `introspect.observability`; **после closure 4.3 — по протоколу `ObservabilityReadback.counters()`**, до него — ключи по факту с пометкой «до 4.3»; ёмкость источника брать **эффективную** (после closure 4.1 она из политики `observability.hub.capacity`, не литерал);
2. у **экспортёра** (числовая плоскость, `history_query(metric=...)`): `received`, `skipped_numbers`, `dropped_overflow`, `export_failed`, `exported`;
3. у **коллектора**: число записей в `otel_records.json`.
**Acceptance criteria:**
- [ ] Тождество сходится на живом прогоне 5 минут; расхождение — либо найденная потеря без счётчика (находка), либо ошибка модели (записать).
- [ ] Все числа читаются агентом через MCP (`introspect_telemetry`, `history_query`, `introspect_observability(full)`) без драйвера из скрипта.
**Out of scope:** новые счётчики во фреймворке.

---

## Ф4 — приёмка и вердикт о словаре

### Task 4.1 — живой прогон
**Acceptance criteria:**
- [ ] Записи предъявлены целиком из `otel_records.json`: `service.name`, `service.instance.id`, `process.pid`, `severityNumber`, `traceId`, `body`, `observedTimeUnixNano`, `instrumentationScope.name`.
- [ ] Записи двух разных процессов различаются `Resource`-ом.
- [ ] Рестарт **источника** → новый `service.instance.id` (переподписку делает брокер).
- [ ] Рестарт **экспортёра** (2.5) → хвост восстановился.
- [ ] Тождество потерь 3.4 сходится; `skipped_numbers > 0`.

### Task 4.2 — вердикт: что словарь Ф3 не выдержал
**Acceptance criteria:**
- [ ] `docs/audits/<дата>_otel-dictionary-verdict.md`: что приёмник разобрал, что отверг, что принял не так, как мы думали.
- [ ] Выводы **ограничены** разделом «что арбитр НЕ проверяет» из Task 0.1.
- [ ] Формулировка «соответствие модели OTel остаётся заявленным» снимается **только** по факту отчёта и ровно в покрытой им части — в `real-state-map`, roadmap и `CONNECTORS.md`.

### Task 4.3 — документация по стандарту двух слоёв
**Acceptance criteria:**
- [ ] `Services/otel_export/DECISIONS.md`: ADR формы (плагин + фрагмент, отвергнутые формы), ADR пина SDK («обновление extras = прогон Ф1 заново»), ADR Р-3. **`python -m scripts.sync` слой `Services` не сканирует** (`adr_modules.py:329-331`) — ссылку в индекс внести вручную, долг «sync не видит Services» записать.
- [ ] `README.md`/`STATUS.md` сервиса и плагина; строки в `Services/STATUS.md` и `Plugins/io/STATUS.md` (или эквиваленте слоя).
- [ ] `CONNECTORS.md` (словарь счётчиков), `SINKS_MAP.md` (экспортёр как подписчик, **не** логгер-sink), `CONTROL_PANEL.md` (команды `otel_export.*`) — своими разделами, каждое утверждение с числом/именем/дефолтом получает проверку в `scripts/docs_verify` по схеме closure 5.1; если 5.1 уже в дереве — её стражи расширяются, а не дублируются.
- [ ] Отметка 8.6 в `observability-unified-routing.md`; строка в `plans/QUEUE.md`; этап 7 roadmap.

---

## Три платформы: Windows, Jetson, Raspberry (требование владельца 2026-08-11)

**Экспортёр кроссплатформенен по построению**: обычный Python-процесс топологии, зависимости
чистые (Task 0.2). `if sys.platform` в коде сервиса/плагина — признак не той задачи.

**Коллектор на устройстве жить не обязан**: экспортёр шлёт OTLP/HTTP на `endpoint` из
фрагмента, один коллектор принимает записи со всех устройств и различает их по
`service.name`/`service.instance.id`. Локальный коллектор на устройстве — буфер при рваной
сети, это эксплуатация, вне фазы.

| Машина | Артефакт коллектора (0.158.0, `otelcol`, не contrib) | Разрядность |
|---|---|---|
| Windows (dev) | `otelcol_0.158.0_windows_amd64.tar.gz` (встроенный `tar -xzf`, без установки) | — |
| Jetson (Ubuntu arm64) | `otelcol_0.158.0_linux_arm64.tar.gz` / `.deb` | `uname -m` → `aarch64` |
| Raspberry Pi 64-бит | тот же `linux_arm64` | `aarch64` |
| Raspberry Pi 32-бит | `otelcol_0.158.0_linux_armv7.tar.gz` | `armv7l` |

**Не проверено и потому не заявляется:** экспортёр на Jetson и Pi не запускался ни разу;
проверка сделана по колёсам PyPI и артефактам релиза. Здесь стоит «препятствий не найдено».

---

## Риски и развилки

| # | Риск / развилка | Как закрывается |
|---|---|---|
| **Р-1** | `Resource` в SDK привязан к `LoggerProvider`, а нужен на запись | **[x] закрыта 2026-08-11 на живом API 1.44.0**: `resource` задаётся на запись через `ReadableLogRecord(log_record, resource, instrumentation_scope, limits)`; класса `LogRecord` в публичном экспорте `_logs` нет |
| **Р-2** | Logs SDK экспериментальный (`_logs`) | пин minor (0.2); ADR: обновление extras = прогон Ф1 заново |
| **Р-3** | Петля усиления | страж фреймворка (`core/process_module.py`, символ `subscribe_observability_tail`) **предъявить** в 2.3; свой фильтр — только если петля воспроизведена |
| **Р-4** | Объём: `INFO` с 8 процессов по IPC и HTTP, очередь источника 256 `drop_oldest` | замер 3.2 соло ×3, тождество 3.4; дефолт `INFO`, `DEBUG` — только на время проверки словаря |
| **Р-5** | Приёмник принимает всё → приёмка фиктивна | Task 0.1: три контроля, включая семантический; выводы 4.2 ограничены списком слепых зон |
| **Р-6** | `scope` не доезжает до экспортёра | **[x] закрыта 2026-08-11 — (б)**: требование снято ревизией ADR-LOG-005; `scope` — внутреннее понятие маршрутизации, наружу не едет; отвергнуты (а) правка display-вида, (в) оставить долгом |
| **Р-7** (ред. 4) | Дверь конфига: `observability.otel_export` против контракта секции (closure 2.2) | **закрыта формой**: регистры плагина в записи фрагмента; секция `observability.*` не трогается |
| **Р-8** (ред. 4) | Числовая плоскость выросла (два рода, колонка `metric`, `NumberRecord`) — соблазн экспортировать метрики; этап 6 передал числа экспортёру «в display-форме без правок» | v1 — только логи, числа считаются (1.3); вход для v2 «OTLP metrics» — closure Task 3.4 (единица/описание/род), без неё экспорт чисел безъединичный. Записать как будущий план, не задачу |
| **Р-9** (ред. 4) | Первый плагин-подписчик хвоста и первый Services-пакет с бинарной цепочкой | недостающие крючки (`PluginContext`, конверт команды брокеру) — находки; фреймворк не правится здесь, долг в closure с датой |
| **Р-10** (ред. 4) | Один стенд на два плана | §«Пересечения с observability-closure»: Ф0–Ф1 сейчас, Task 1.0 — 5 минут на стенде closure, Ф2–Ф4 чередуя |

---

## Пересечения с `observability-closure` (ред. 4, сверено по файлам фаз 2026-09-05)

Прежний гейт «Ф2–Ф4 после гейта этапа 2 roadmap» формально пройден 2026-08-12, но дефицит тот
же: **один живой стенд (порт 8765)**, за него конкурируют стенды closure Ф3 (3.2, 3.3, 3.6,
3.7, 3.8) и Ф4 (4.8 на 20 процессах).

### Порядок исполнения

| Что | Когда | Почему |
|---|---|---|
| **Ф0** (0.2 шаги 2–3, 0.3, 0.4) | сейчас | стенда не требует |
| **Task 1.0** (снимок) | ближайший стенд closure (3.2/3.3/3.8), 5 минут `observability_tail`; половина (стор) — `history_query` без стенда | свой стенд не поднимать |
| **Ф1** (1.1, 1.2, 1.3) | сейчас, после 1.0 | чистые функции; 1.1 и 1.3 правят один файл — **не параллелить** |
| **Ф2** 2.1–2.3, 2.5 | чередуя со стендами Ф3 closure | стенд `4318` свой, стенд `8765` — общий |
| **Task 2.4** | **после closure Task 3.3** | одна форма предохранителя на плоскость |
| **Task 3.4** | после closure Task 4.3, либо по протоколу `counters()`, если 4.3 уже в дереве | форма readback меняется |
| **Ф3–Ф4 остальное** | после закрытия Ф3 closure или в его паузах | живые приёмки конкурируют за стенд и внимание владельца |

### Карта пересечений по задачам closure

Правило одно: **что делает closure — здесь не делается и не дублируется**; что нужно раньше, чем
closure успеет, — записывается ссылкой на его задачу, не своим механизмом.

| Задача closure | Что меняет | Отношение к этому плану | Что делать здесь |
|---|---|---|---|
| **3.2** уровни: болтовня → DEBUG, `messages.log` без дубля | объём `INFO` падает (цель < 100 строк на бут) | база для замера цены (otel 3.2) | замер otel 3.2 — после closure 3.2, иначе число протухнет через неделю; базу назвать хэшем |
| **3.3** store-tap батчем: bounded-канал, `history.queue_capacity`, `store_evicted`, `flush: N/M` | форма предохранителя на плоскости | **прямая зависимость otel 2.4** | та же форма и лексика; 2.4 не стартует раньше 3.3 |
| **3.4** метаданные метрик: `declare_metric(name, *, owner, unit, description, kind)` | сигнатура объявления счётчиков | счётчики экспортёра объявляются через `ctx.declare_metric` (otel 2.1) | если 3.4 в дереве — объявлять с единицей/родом; если нет — имена, и плагин вносится в список миграции 3.4 явной строкой |
| **3.6** восемь метрик + второй wide event | больше числовых записей | ничего: числа v1 не экспортирует (1.3) | `skipped_numbers` вырастет — это ожидаемо, не дефект |
| **3.7** уборка стора, ретенция `telemetry.db` | стор | нет пересечения | — |
| **3.8** живой стенд Ф3 | стенд 8765 | окно для Task 1.0 | подсадить снимок, 5 минут |
| **4.1** hub: карта последних значений, ёмкость/каденция из политики (`observability.hub.capacity`) | вход батч-форвардера: `changed_only` у observation, ёмкость каналов | источник потерь в тождестве otel 3.4 | тождество читает **эффективную** ёмкость из readback, не литерал 1024 |
| **4.3** протокол `ObservabilityReadback` (`readback()/sinks()/counters()`), распил хендлера, `flare` | форма `introspect.observability` | otel 3.4 берёт счётчики форвардера оттуда | после 4.3 — по протоколу; до — ключи по факту с пометкой «до 4.3» |
| **4.4** точечные подписки переживают рестарт и креш клиента: реестр намерений, `forget_session`, replay на `instance.started` | брокер | **закрывает сценарий (б) otel 2.5** (форвардеры-сироты после SIGKILL) | в 2.5 не чинить и не обходить: если 4.4 в дереве — проверить им; если нет — записать ссылкой на 4.4 |
| **4.5** `ServiceContext` — разъём наблюдаемости для авторов сервисов | как сервис логирует и считает | `Services/otel_export` — библиотека, ей нужен контекст | свой контекст не заводить: `interfaces.py` принимает минимальный Protocol (`log_*`, `record_metric`, `report_error`), которому удовлетворят и `PluginContext` сейчас, и `ServiceContext` после 4.5 |
| **4.6** нейтральный словарь, литералы в политику, `frame_trace` → `register_sink_factory` | имена метрик; реестр фабрик логгер-стоков | экспортёр — **не логгер-sink** | не регистрировать экспортёр через `register_sink_factory` (это отвергнутая форма «tap в каждом процессе»); имена счётчиков нейтральные с первого коммита |
| **4.7** реестр объявлений — объект процесса | module-level API → фасад | `ctx.declare_metric` не меняется | — |
| **4.9** `KnobManager` | универсальные ручки | параметры батчера — регистры плагина | не заводить свою ручку-механику; при появлении адаптера «регистр ↔ ручка» — принять его |
| **4.10–4.12** словарь политики, голос конфига, `telemetry.broadcast` | внутренности фреймворка | нет пересечения | — |
| **4.8** стенд Ф4 на 20 процессах | стенд | замер otel 3.2 на 20 процессах | подсадить, не поднимать своё |
| **5.1** четыре справочника под HEAD + стражи `docs_verify` | `CONNECTORS`/`CONTROL_PANEL`/`SINKS_MAP`/`NEW_MODULE_RECIPE` | otel 4.3 правит те же файлы | свои разделы — с проверками `docs_verify` по схеме 5.1; правки после 5.1 — отдельными разделами, чтобы merge был чистым |
| **5.4** переприёмка гейта Ф6 этапа 6 — **«без OTel-части»** | закрытие трека closure | нет зависимости в обе стороны | OTel-часть мерила 6 roadmap снимает **только** otel 4.2 своим отчётом |

**Из `telemetry-stage6.md` (out of scope этапа 6):** «интеграционная точка с OTel одна и пассивная —
записи `kind=stats` идут в display-форме, маппер этапа 7 получает их без правок». Здесь это
принято так: числа **доезжают** до экспортёра (форма — снимок 1.0), но v1 их **не экспортирует**
логами, а считает (1.3); экспорт чисел — метриками в v2 (Р-8). Расхождения с этапом 6 нет —
он передавал форму, а не требовал экспорта.

### Пересечение по файлам

Код: **ноль общих файлов** — otel пишет только в `Services/otel_export/`, `Plugins/io/otel_export/`,
`backend/topology/otel_export.yaml` и одну закомментированную строку `app.yaml`; extras в
`pyproject.toml` уже в closure. Документы: справочники `multiprocess_framework/docs/observability/*`
общие с closure 5.1 (см. таблицу), `plans/QUEUE.md` и roadmap — общие по одной строке. Файлов
**кода** фреймворка — **0 правок**; находки во фреймворке идут долгом в closure, не задачами сюда.
Справочники под `multiprocess_framework/docs/` — правятся (факт Ф0: `61bb7496` дописал
`docs/observability/CONNECTORS.md` §4.2, +34 строки). Формулировка «фреймворк не тронут ни строкой»
шире факта и в отчётах не употребляется: она верна про `**/*.py`, но не про дерево целиком.

---

## Out of scope (весь план)

- Трейсы (spans) и метрики в OTLP — только логи (Р-8).
- Внешняя инфраструктура сбора (Grafana, Loki, облачные бэкенды); docker-compose; сеть вне `127.0.0.1` на dev-стенде.
- Структурный формат **файлов** (ECS/OTLP-JSON) — отдельная ось.
- Error-grouping класса Sentry; автоинструментация `opentelemetry-instrumentation-*`.
- Экспорт плоскости документов (аудит/вердикты) — своё хранилище (ADR-PM-028), OTLP-логи ей не адресат.
- Правки брокера, `record_display`, `PluginContext` — находки идут долгом в closure.
- GUI-вкладка управления экспортёром (регистры плагина видны стандартной панелью — этого достаточно для v1).

---

## Отход от постановки 8.6 — объявлен явно

Постановка требует «настоящий приёмник OTLP, а не стенд ради теста». Ф0 строит именно стенд.
Отход осознан: ценность фазы — **проверка контракта внешним арбитром**, она достигается
стендом, а фрагмент топологии с `endpoint` из конфига делает переход к эксплуатационному
приёмнику сменой одной строки. Если владелец считает, что без эксплуатационного приёмника
фазу делать не стоит, — это законное «нет», план остаётся в очереди.

---

## История редакций

| Ред. | Дата | Что изменилось |
|---|---|---|
| 1 | 2026-08-06 | постановка из 8.6; маппер над плоским `extra` (неверно на обеих дорогах) |
| 2 | 2026-08-10 | после независимого ревью спеки (6/10, 4 блокера): двойной источник истины, Task 1.0, Б-3 `stamp_observed`, М-1…М-7 |
| 3 | 2026-08-11 | старт согласован; Р-6 закрыта (б); `otelcol` вместо contrib; три платформы; `endpoint` — ключ конфига; Task 0.1 сделана; Р-1 проверена живьём |
| **4** | **2026-09-05** | по [ревью](../docs/reviews/2026-09-05_otel-export-plan-review.md): база ветки — closure; форма «SDK в Services + плагин в Plugins + фрагмент топологии»; дверь конфига — регистры плагина (Р-7); числовая плоскость двумя родами (1.3); `origin` изымается; голоса через `log_windowed`; счётчики — числовая плоскость; Р-3 — страж фреймворка; тестер на всех фазах, пары инъекций, замер соло ×3, sentrux CLI; Task 0.3/0.4; 2.4 после closure 3.3; честная оценка; рекомендации 2026-09 (`host.name`, gzip, параметры батчера регистрами); карта пересечений с closure по задачам (3.3→2.4, 3.4→2.1, 4.3→3.4, 4.4→2.5, 4.5→0.4, 5.1→4.3) |
