# Карта наблюдаемости — логи, ошибки, статистика, документы

> Обновлено **2026-08-23** (Ф1+Ф2 плана `observation-port`: владение метрик = путь в дереве;
> плагины пишут в `state.plugins.<имя>.*`; ушедших писателей удаляют `state.delete`, не `None`-надгробиями).
> Предыдущая редакция (2026-08-10, коммит `b04a0c12`) знала метрики плагина только плоским листом
> `state.<метрика>` — до того, как владение стало путём.
> **Это карта и навигация.** Подробности — в четырёх справочниках, они же единственное место, где
> утверждения держатся якорями в коде:
> [`observability/CONNECTORS.md`](observability/CONNECTORS.md) — разъёмы, поля записи, классы потерь ·
> [`observability/SINKS_MAP.md`](observability/SINKS_MAP.md) — приёмники, маршруты, хранилища ·
> [`observability/CONTROL_PANEL.md`](observability/CONTROL_PANEL.md) — слои, команды, вердикт ·
> [`observability/NEW_MODULE_RECIPE.md`](observability/NEW_MODULE_RECIPE.md) — как подключить модуль.
>
> План, закрывший фазы A–D: [`plans/observability-review-remediation.md`](../../plans/observability-review-remediation.md).
> Предшественник: [`plans/observability-unified-routing.md`](../../plans/observability-unified-routing.md).

---

## 1. Четыре плоскости

У наблюдаемости **четыре** плоскости, и различаются они не важностью записи, а **вопросом, на
который отвечают**:

| Плоскость | Отвечает на | Разъём | Где оседает в дереве | Срок |
|---|---|---|---|---|
| **Логи** | что происходило | `_log_*`, `ctx.log_*` | `system.log`, `messages.log`, `performance.log` | ротация 10 МиБ × 5; ретеншен **выключен по умолчанию** |
| **Ошибки** | что сломалось | `_track_error`, `ctx.health.report_error` | `errors.log`, `critical.log`, `warnings.log` + пол `errors_floor.jsonl` | там же; пол не подметается, ротирует себя сам |
| **Статистика / агрегаты** | сколько и как быстро | `_record_metric`, `_record_timing` (воркеры / глобальные); `ctx.publish_metric` (плагины) | `processes.<P>.state.fps`, `latency_ms`, `shm` (фреймворк); `processes.<P>.state.plugins.<плагин>.*` (плагины) | там же; Ф3 — управление полем (то есть слот `ObservationManager` — **спланирован**, не реализован) |
| **Документы** | что **решено** | `ctx.write_document` | SQLite `DocumentStore` | `retention_sec` **по роду документа** |

Плоскость документов — не «логи поважнее». Вердикт о качестве изделия живёт годами, диагностика —
днями, поэтому правило допуска там **структурное** (свой приёмник), а не «фильтр по уровню, который
надо не забыть настроить» (ADR-CRM-013, ADR-PM-028).

**Телеметрия (FPS, latency, статистика плагинов) — структура владения (Ф1+Ф2 плана `observation-port`):**
Каждый писатель публикует только в своё поддерево, и спорить за имя становится синтаксически
невозможно — арбитраж не починен, а удалён. Фреймворк (heartbeat) пишет `state.fps`,
`state.latency_ms`, `state.shm.*` — они остались ПЛОСКИМИ и остаются агрегатами фреймворка;
плагин через `ctx.publish_metric` пишет только в `state.plugins.<имя_плагина>.<метрика>`.
Ушедший писатель снимается удалением его поддерева (`state.delete`), а не поимёнными
`None`-надгробиями. Читатель GUI — единый `telemetry_readmodel_module` (ADR-136).

**Плоский адрес метрики плагина остаётся законным — и это не хвост миграции.** `publish_metric` не
единственная дорога в дерево: прямая запись `state_proxy.merge` кладёт лист плоско, поэтому
предохранители-троттлы держат ОБЕ формы (`multiprocess_prototype/backend/state/manager_setup.py:62-75`
— там же назван потолок: разводить интервалы двух форм врозь нельзя, не починив матчинг
`judge_throttle_caps`). Читая карту как «плоского больше нет», можно снять живой предохранитель.

**Сверщик потолков троттла отвечает ТРЕМЯ показаниями, а не двумя** (`managers/telemetry_reload.py`,
`judge_throttle_caps`; в ответе `config.reload` → `observation_applied`). `throttle_checked` говорит,
позвали ли сверщика; `capped_by_throttle` — где троттл строже публикатора, причём частота в нём это
РЕАЛЬНЫЙ ask (`max(заявка, эффективный такт)`: публикатор не публикует чаще такта heartbeat'а);
`capped_by_throttle_unjudged` — кого рассудить было нечем, с причиной-литералом (`"no_tick"` — нет
ни заявки, ни такта; `"unreadable_rule"` — правило на адресе есть, а интервал не число). Третий ключ
появляется только непустым. Класс ошибки, ради которого он заведён
(Ф3, задача 3.0, находка F2 вердикта CTO по Ф2): пустой `capped_by_throttle` рядом с
`throttle_checked: true` читался как «потолков нет», хотя часть кандидатов не судил никто. Прежнее
имя `detect_throttle_caps` живо как тонкая обёртка, отдающая только `capped_by_throttle`.

**Реальный ask доезжает не по всякой дороге.** Такт участвует в расчёте только там, где вызывающий
его знает: `config.reload` берёт его readback'ом у своего `ProcessHeartbeat`, а оптовый
`telemetry.broadcast` (`process_manager_process.py`) такта РЕБЁНКА не имеет вовсе и судит по
заявленному `interval_sec` дословно — то есть на нём ошибка модели F1 ещё живёт. Замер:
`{"metrics": {"fps": {"interval_sec": 1.0}}}` против правила `2.0` даёт `publisher_interval_sec: 1.0`
и назван потолок, которого при такте 5.0 с нет. Долг назван Task 4.12
([`plans/observability-closure/phase-4-scale-and-form.md`](../../plans/observability-closure/phase-4-scale-and-form.md)),
и до него читать отчёт оптовой дороги как «реальный ask» нельзя.

**Широкая запись о единице работы (`ctx.write_event`, ADR-PM-036) пятой плоскости НЕ заводит.**
Она едет плоскостью ЛОГОВ (`BUSINESS`/`INFO`), просто несёт весь контекст единицы в одной записи —
вердикт, счётчики, ROI, спаны — и `trace_id` в тексте, чтобы находиться поиском. Своё у неё одно:
отбор (`observability.events`, живой `WideEventSelector` на процессе), потому что дроссель логгера
ключует пару «уровень + текст», а у широкой записи текст свой у каждой единицы.

**Flight recorder (`ctx.flight_dump`, ADR-PM-037) плоскости не заводит тоже — он её ЧИТАЕТ.**
Кольцо последних записей процесса — это существующий `MemoryChannel` логгера (приёмник
`type: memory` в `observability.channels`, ретроспективное чтение `observability.sink.tail`); дамп
выгружает его в `<логи>/<процесс>/flight/<ts>_<reason>.jsonl` по явному вызову приложения. Отвечает
на «что процесс писал ВОКРУГ момента X» — в отличие от широкой записи, которая отвечает «что было
с ЭТОЙ единицей». Не путать с `backend_ctl record_*` и `telemetry_readmodel.export_history`: те
кольцуют ТЕЛЕМЕТРИЮ и стоят снаружи процесса. Дефолт — выключено
(`observability.flight.enabled`).

**Окно голоса (`observability.voices`, ADR-LOG-012) плоскости не заводит — оно решает, КОГДА
писать.** Повторяющееся состояние (нет маршрута, очередь полна, приоритет не ставится) обязано
оставлять факт всегда, а строку в журнал — не чаще окна на ключ. Механизм —
`logger_module/core/windowed_voice.py`; разъём для менеджеров — `ObservableMixin.should_voice`
(решение без записи) и `ObservableMixin.log_windowed` (удобство, когда голос — это всё, что нужно).
Не путать с дросселем логгера (`observability.sampling_*`, ADR-LOG-007): тот ключует пару
«уровень + текст» на выходе плоскости, а здесь ключ выбирает ВЫЗЫВАЮЩИЙ (адрес события), и
подавляется только голос — счётчики, записи в плоскость ошибок и статистика растут мимо окна.
Четыре ручки (добор ревью Ф1, Task 2.7 — раньше их было две, `max_tracked_keys`/`stale_windows`
были литералами без ручки и без readback): `default_window_sec` (окно, дефолт 5.0),
`escalate_after_repeats` (повторов ПОДРЯД до INFO → WARNING, дефолт 3; ось повторов, а не
времени), `max_tracked_keys` (потолок карты ключей держателя окон, дефолт 512) и
`stale_windows` (такт протухания бездолжного ключа в окнах, дефолт 10). Процессные счётчики
механизма — `windowed_suppressed` и `windowed_keys_evicted` — публикует плоскость логов
(`introspect.observability`).

**Телеметрия (FPS/latency) — вторая половина плоскости метрик** и живёт мимо `StatsManager`:
self-publish в дерево состояния по такту heartbeat с publisher-gate (ADR-PM-018), чтение —
локальный read-model без блокирующего IPC (ADR-136). Их объединение — первая фаза плана телеметрии
(она же задача C1, см. §5).

---

## 2. Общая схема

```mermaid
flowchart TB
    subgraph EMIT["Точки эмиссии (в каждом процессе)"]
        MIX["ObservableMixin._log_* / _track_error / _record_metric<br/>676 вызовов в 64 файлах"]
        CTX["PluginContext: пятёрка log_* + health.report_error<br/>+ write_document + write_event + четвёрка stats — 242 вызова в 59 файлах"]
        FAC["get_std_logger(name) — ВИД над писателем<br/>116 вызовов в 112 файлах (после Ф6)"]
        BRG["logging.Handler-мост для чужих библиотек<br/>(pymodbus, D7) — propagate=False"]
    end

    subgraph CRM["Общая база: ChannelRoutingManager"]
        BASE["писатель · sink-control · tap-механика<br/>5 классов потерь + счётчик доставки · levels.py"]
    end

    subgraph MGRS["Три менеджера-брата (триплет на процесс)"]
        LC["LoggerCore → LoggerManager<br/>гейт по имени источника (longest-prefix) · seq-пломба · процессоры"]
        EM["ErrorManager (наследник LoggerCore)<br/>severity-маршруты данными, один _route()"]
        SM["StatsManager (наследник CRM)<br/>counter/gauge/timing · AggregationWindow"]
    end

    subgraph SINKS["Приёмники (config-owned)"]
        FCH["file · console · memory · null · http · frame_trace<br/>реестр _SINK_FACTORIES, расширяется register_sink_factory"]
        FLOOR["ErrorFloor: errors_floor.jsonl —<br/>синхронный пол, не зависит от конфига приёмников"]
    end

    subgraph TAPS["Tap'ы (runtime-owned, переживают reconfigure)"]
        STORE["StoreTapChannel → ObservabilityStore (SQLite)"]
        FWD["forward-tap, keyed по subscriber →<br/>адресный пуш подписчику, без транзита через ПМ"]
    end

    subgraph DOCS["Плоскость документов"]
        DS["DocumentStore (SQLite): вердикты приложения<br/>+ аудит смен наблюдаемости — ОДИН экземпляр на процесс"]
    end

    subgraph CONSUMERS["Потребители"]
        GUI["GUI: вкладки Логи / Ошибки / Статистика"]
        CTL["backend_ctl: log_tail · observability_tail ·<br/>introspect.observability · system_overview"]
        SEAL["scripts/observability_seal — внешний проверяющий пломб"]
    end

    MIX --> LC & EM & SM
    CTX --> LC & EM & DS
    FAC --> LC
    BRG --> FAC
    LC & EM & SM -->|наследуют| BASE
    LC --> FCH
    EM --> FCH
    EM --> FLOOR
    SM -->|снапшот через логгер| FCH
    LC & EM -.->|add_tap| STORE & FWD
    STORE --> GUI
    FWD --> GUI & CTL
    FCH --> SEAL
    DS --> CTL
```

Чего в схеме больше **нет** и почему: `BatchBuffer` снят целиком в Ф7.4 (ADR-LOG-008) — батчинг
файловой записи не давал экономии на границе ОС и портил хвост эмитента (p99 1348 против 75 мкс);
запись синхронна на всех уровнях. `_LoggerSlotSplitter` снят вместе с лог-буфером hub'а: живой
хвост даёт tap, а инварианты «дубль» и «потеря при SIGKILL» стали невозможны по построению.

---

## 3. Кто пишет

Цель владельца: **в пределе один писатель**, всё остальное — вид поверх него или доказанное
исключение.

| Кто | Роль сегодня |
|---|---|
| `LoggerCore` | **единственный писатель** |
| `get_std_logger` | **вид** над ним: 116 вызовов в 112 файлах — результат Ф6 |
| `emergency_log` | аварийный выход: отказ писателя нельзя рассказать через писателя |
| `ErrorFloor` | приёмник последней инстанции; прикладной код звать его **не должен** — соглашение, а не запрет: класс публичен, стража нет (F1 воспроизвела вызов) |
| голый `logging.getLogger` | **7 файлов**, каждый с обязательной причиной в страже `test_std_logger_guard.py` (AST, четыре формы написания, протухшая строка whitelist'а — красный) |

**Ф6 закрыта числом, а не намерением:** было **107 файлов**, писавших в пустоту (у stdlib-root в
живых процессах хендлеров не подключает никто; под `pythonw` теряется вообще всё). Стало 7
исключений с причинами. Объём логов при этом **не вырос** (5.4 → 4.78 МБ/час) — миграция не
добавила записей, она вернула им адрес.

Три формата в одной консоли сведены к одному в D7: loguru в `Services/modbus` переведён на вид,
чужой `pymodbus` — на мост, `topology/blueprint.py` — тоже на вид. Полный список — в
[`CONNECTORS.md §5`](observability/CONNECTORS.md).

---

## 4. Ручки управления

Полностью — в [`CONTROL_PANEL.md`](observability/CONTROL_PANEL.md). Здесь только карта:

| Слой | Кто владеет | Чем правится |
|---|---|---|
| **L0** код (`ObservabilityConfig`) | фреймворк | — |
| **L1** `system.yaml` | машина | правка файла + hot-reload watcher |
| **L2** рецепт и спутник | конвейер | `switch`, `observability.persist` |
| **L3** память процесса | оператор | `config.reload` inline, срок по умолчанию **300 с** |

Канонические имена команд: `config.reload`, `observability.persist`,
`observability.sink.enable/disable/tail` (алиасы `logger.sink.*`),
`observability.tail.subscribe/unsubscribe[_all]`, `introspect.observability`, `health.report`.
Применение везде идёт одним путём — `apply_observability_layers`, **пересборка из источников**, а
не дельта поверх живого.

Чтение без мутации: `introspect.observability` → `effective` + `counters` + `provenance` + `ttl` +
`documents` + аудит. Доказательство применения: `config_reload_verified` → трёхзначный `verdict`
(`confirmed`/`failed`/`unverifiable`) **и отдельно** `delivering`/`losing`/`silent_source` с
вычетом цены самого опроса.

---

## 5. Что не так сегодня (честный список с адресами)

### 5.1. Открыто

* **`observability.documents` и `observability.history` не действуют на лету.** Слои их принимают,
  но сток документов и политика истории сшиваются один раз на `initialize()`; действуют со
  следующего старта процесса. Найдено при написании справочников (E1).
* **Чужое дерево логов фреймворк называет только одно** — `<cwd>/logs`. Второй известный пример
  (`multiprocess_prototype/logs/`) он структурно назвать не может: импорт прототипа запрещён
  правилом слоёв. Хук `_foreign_log_root_candidates()` переопределяемый — работа композиционного
  корня прототипа.
* **Отказ переполненной очереди живого GUI неотличим по счётчику от отсутствия приёмника** —
  роутер считает оба случая одним ключом. Назван в D8, кандидат в [`plans/QUEUE.md`](../../plans/QUEUE.md).
* **Ретеншен логов выключен по умолчанию** (`retention_days`/`retention_total_mb` = 0). Механизм
  построен и оттестирован; включать чистку молча нельзя — это решение приложения.

### 5.2. Принято осознанно (не костыли, но названо)

* поток, вошедший в блокирующий `write()` стока, не ограничен ничем — лесенка перегрузки
  (ADR-LOG-009) спасает остальных, свою жертву не спасает;
* per-callsite тумблеры отвергнуты: в Python выключенное состояние не бесплатно, гранулярность —
  источник или группа;
* mojibake русских строк в консоли Windows (cp866); `events_page` на бутстрапе ~114 КБ;
* Linux-вердикты подтверждены CI на ubuntu, но живого Linux-прогона не было — машины нет.

### 5.3. Закрыто в последнем заходе (фазы A–D, 2026-08-09…10)

`level` подписчика доезжает до процесса (A1) · пятёрка `log_*` у плагина (A2) · темп стат-плоскости
действует и читается из живого окна (B1) · мусор не доживает до слоя (B2) · порядок останова, error
и stats гасятся вообще (B3) · у плагина появилась дорога в плоскость ошибок (C2, ADR-PM-030) ·
документ без приёмника имеет голос и счётчик (C3) · реентрантный tap не даёт лавину (D1) · тестовая
сетка перестала врать (D2) · миграция `auto_vacuum` (D3, ADR-CRM-014) · доменное имя ушло из
универсального слоя (D4, ADR-137) · ПМ метёт всё дерево логов (D5) · один писатель в консоли (D7) ·
headless-шторм в `gui` снят (D8, ADR-PMM-025).

### 5.4. Закрыто планом «порт наблюдений» (Ф3, 2026-08-25)

* **C1 «У плагина нет stats-разъёма» — закрыт, но НЕ дорогой, которую называла запись.**
  `IProcessServices` по-прежнему не объявляет stats-методов, и `kind=stats` от плагина до стора
  по-прежнему не доезжает — эта половина посылки не изменилась. Закрыт сам ВОПРОС записи
  («метрика, которую публикует плагин, доезжает до стора») — другой дорогой: уровни плагина
  (`ctx.publish_metric`, `state.plugins.<писатель>.<имя>`) с задачи 3.2 дублируются записями
  `kind=observation` в `ObservabilityHub` процесса и той же дорогой, что `stats`, доезжают до
  `ObservabilityStore` и живого хвоста (`observability.tail.*`). Ветку `KIND_STATS` в drain
  трогать не пришлось — четвёртый канал, не правка третьего (ADR-SM-013,
  `statistics_module/DECISIONS.md`).

---

## 6. Сколько это стоит

Замер **2026-08-10** (`.py`, без `__pycache__`; тесты считаются отдельно):

| Область | Production | Тесты |
|---|---|---|
| `channel_routing_module` | 3 782 | 4 279 |
| `logger_module` | 6 936 | 18 213 |
| `error_module` | 910 | 1 862 |
| `statistics_module` | 1 327 | 1 186 |
| `telemetry_readmodel_module` | 359 | 282 |
| обвязка `process_module` (`observability_*` + слои + аудит) + брокер + листы (`observability_declarations`, `_fallback`) | 5 176 | 11 165 |
| внешний проверяющий пломб (`scripts/observability_seal`) | 302 | — |
| GUI-вкладка «Наблюдаемость» (прототип) | 979 | 606 |
| **Итого** | **19 771** | **37 593** |

Соотношение тестов к коду — **1.9 : 1**; у одного `logger_module` — 2.6 : 1. Это цена
доказанности после Ф0, где 12 зелёных тестов закрепляли неверную модель.

**Что публикуется наружу для сверки учёта.** Прежняя редакция карты приводила здесь равенство с
`dropped` и `in_flight_records` — это был инвариант **снятого** `BatchBuffer`, и сегодня половины
его членов не существует. Сейчас наружу едут два независимых набора:

* у менеджеров — пять классов потерь + счётчик доставки `channel_written_records` (единый список
  `LOSS_COUNTER_KEYS`, он же реестр публикации `PLANE_COUNTER_KEYS`);
* у окна агрегации — `total_enqueued` / `total_flushed` / `total_flushes` / `flush_failed` /
  `pending_metrics` / `flush_interval`. Равенство «сколько положили = сколько сбросили + в очереди»
  сторожит `test_stats_no_double_count.py` (число `record_metric`-вызовов против `total_enqueued`).

Цена защиты реентрантности tap'а (D1, бенч 5 × 200 000 вызовов, медиана): база эмиссии
0.36–0.41 мкс, с защитой 0.52 мкс. При живом темпе плоскости (~44 записи/с) это ~7 мкс/с.

---

## 7. Куда идти дальше

| Вопрос | Документ |
|---|---|
| «чем писать из моего кода» | [`observability/CONNECTORS.md`](observability/CONNECTORS.md) |
| «подключаю новый модуль» | [`observability/NEW_MODULE_RECIPE.md`](observability/NEW_MODULE_RECIPE.md) |
| «куда физически попала запись» | [`observability/SINKS_MAP.md`](observability/SINKS_MAP.md) |
| «как покрутить на живом стенде» | [`observability/CONTROL_PANEL.md`](observability/CONTROL_PANEL.md) |
| «принять как потребитель: что есть, чем управлять, что наблюдаемо» | [`observability/ACCEPTANCE_CHECKLIST.md`](observability/ACCEPTANCE_CHECKLIST.md) + зонд `backend_ctl/probes/probe_observability_consumer_acceptance.py` (`/core:quality:observability-acceptance`); эталон [`docs/reviews/2026-09-08_observability-consumer-acceptance.md`](../../docs/reviews/2026-09-08_observability-consumer-acceptance.md) |
| «какие решения приняты и почему» | [`../DECISIONS.md`](../DECISIONS.md) + локальные `DECISIONS.md` модулей |
| «что ещё не сделано» | [`plans/observability-review-remediation.md`](../../plans/observability-review-remediation.md) |
