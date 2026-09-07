# Services/otel_export — экспорт записей наблюдаемости наружу по OTLP

> **Стадия:** частичная реализация (план [`plans/otel-export.md`](../../plans/otel-export.md)).
> Ф1 закрыта: маппер (`mapping.py`), резолвер `Resource` (`resources.py`), фильтр числовой
> плоскости и приведение атрибутов — есть. Task 2.2 закрыт: `OtlpHttpExporter`
> (`exporter.py`) отправляет батч **синхронно** и возвращает исход числами. Чего ещё нет:
> асинхронной пачки по расписанию (`BatchLogRecordProcessor`) — она приходит в Ф2.4, и до
> неё отправка идёт **только по команде** `otel_export.flush`: на останове плагин не
> дожимает, а считает оставшееся потерей и называет число (вердикт CTO по замеру стенда).
> Заголовки разделов по-английски — литерал шаблона module-contract; тело по-русски.

## Purpose

Отдать записи плоскости наблюдаемости (логи и ошибки) наружу по протоколу **OTLP/HTTP**,
чтобы их принял чужой коллектор (`otelcol`, Grafana/Loki, Elastic, Datadog) без нашего кода
на его стороне.

Главная ценность — **не панель и не фича, а внешний арбитр словаря полей**. Во всех отчётах
трека наблюдаемости стоит формулировка «соответствие модели записи OTel остаётся
**заявленным**»: наши записи ни разу не разбирал чужой парсер. Снять эту формулировку может
только он. Провал приёмки — законный исход фазы наравне с успехом.

Сервис — **библиотека без процесса**. Хост — плагин `Plugins/io/otel_export` в
`GenericProcessApp`, подключается фрагментом топологии; кто не подключил — не платит ни
процессом, ни строками golden-снимков.

## Public API

Публичный контур пакета == `interfaces.__all__` (это сторожится тестом A3):

| Имя | Что это | Кто реализует |
|---|---|---|
| `RecordMapper` | Protocol: display-запись → `MappedRecord \| None` | Ф1.1 `mapping.py` |
| `ResourceResolver` | Protocol: контекст записи → `Resource` (пул + LRU) | Ф1.2 `resources.py` |
| `LogExporter` | Protocol: `export(records)`, `force_flush(timeout)` | `exporter.py` -> `OtlpHttpExporter` (Task 2.2; `force_flush` станет непустым в Ф2.4) |
| `ObservabilityPort` | Protocol: минимальный разъём наблюдаемости для сервиса | хост (Ф2) |
| `MappedRecord` | запись в модели OTel Logs Data Model | — |
| `Resource` | **наш** тип ресурса (не тип SDK) | — |
| `ExportOutcome` | исход отправки: `accepted`, `failed`, `reason` | — |
| `FlushOutcome` | исход дожатия: `flushed`, `lost` | — |

Схема параметров и проверка SDK лежат в своих модулях и в `__all__` пакета НЕ входят —
они тянут pydantic и метаданные дистрибутивов, контракту это не нужно:

```python
from Services.otel_export import MappedRecord, RecordMapper   # контракт
from Services.otel_export.config import OtelExportConfig      # схема параметров
from Services.otel_export.config import format_validation_error  # читаемый текст отказа
from Services.otel_export.exporter import sdk_available       # факт наличия SDK
from Services.otel_export.mapping import coerce_attributes    # атрибуты -> то, что кодировщик примет
```

`coerce_attributes(attributes) -> (dict, count)` живёт в `mapping.py` рядом с маппером и в
`__all__` пакета не входит по тому же доводу: это шаг ХОСТА между маппером и экспортёром, а
не контракт. Скаляры (`str`/`bool`/`int`/`float`) и однородные их последовательности едут как
есть; всё прочее приводится к строке и считается (`otel_export.attr_coerced`). Инвариант —
**ни одно значение не исчезает**: замер ревью Ф1 (Н-3) показал, что кодировщик SDK роняет
`Path`/`datetime`/`set` целиком, а исключение уходит в stdlib-`logging`, которого процесс
фреймворка не слышит.

### `OtelExportConfig` — единственное объявление параметров

| Поле | Дефолт | Смысл |
|---|---|---|
| `endpoint` | **обязателен, дефолта нет** | адрес приёмника OTLP/HTTP |
| `level` | `"INFO"` | уровень подписки на хвост наблюдаемости |
| `compression` | `"gzip"` | `gzip` \| `deflate` \| `none` |
| `headers` | `{}` | значения **только** `${ENV_VAR}`; литерал отвергается |
| `service_namespace` | `""` | semconv `service.namespace`; пусто = имя приложения |
| `max_queue_size` | `2048` | ёмкость очереди батчера |
| `schedule_delay_ms` | `1000` | период выгрузки батча |
| `max_export_batch_size` | `512` | записей в одном запросе |
| `export_timeout_ms` | `30000` | таймаут ОТПРАВКИ (см. оговорку ниже) |
| `resource_pool_size` | `64` | предел пула `Resource`, вытеснение LRU |

Дефолты батчера равны дефолтам **установленного** SDK 1.44.0 (сверено с
`opentelemetry/sdk/_logs/_internal/export/__init__.py`). Редакция 4 плана называла
`schedule_delay = 5000` — **это была ошибка плана**, факт `1000`.

`readback()` отдаёт **эффективные** значения, а не сконфигурированные:
`headers` замаскированы `***`, и добавлен ключ `export_timeout_sec`.

### Предохранитель от утечки секрета — `hide_input_in_errors` на схеме, не форматтер

`str(ValidationError)` у pydantic 2.13 печатает вход целиком —
`input_value={'authorization': 'Bearer …'}`. То есть естественная строка
`ctx.log_error(f"конфиг не принят: {exc}")` утащит отвергнутый токен в `system.log`, и
правило «секреты в env» защитит YAML, потеряв секрет в журнале. Найдено авторским тестом.

Предохранитель — `model_config = ConfigDict(hide_input_in_errors=True)` на
`OtelExportConfig`. Он закрывает утечку на ВСЕХ дорогах построения схемы: конструктор,
`model_validate`, присваивание (`validate_assignment`) — и, что важнее всего, на
`generic_process_config.from_plugins` (`reg_cls(**reg_fields)`, без `try`), до которой не
дотягивается ни плагин, ни форматтер. `format_validation_error(exc)` остаётся — это
форматтер ЧИТАЕМОГО ТЕКСТА для хоста (убирает URL и context, оставляет только `loc` + `msg`),
а не предохранитель; звать его по-прежнему стоит везде, где нужен человекочитаемый текст
отказа (ADR-OTEL-005).

### Оговорка про `export_timeout_ms` — стоит дороже остального списка

`BatchLogRecordProcessor` свой одноимённый параметр **игнорирует**: в исходнике SDK 1.44.0
над ним стоит комментарий `# Not used. No way currently to pass timeout to export.`, а
`BatchProcessor.force_flush` несёт `TODO: Fix force flush so the timeout is used`
(issue 4568). Реальный таймаут отправки — аргумент `timeout` (**секунды**, float)
конструктора `OTLPLogExporter`. Поэтому `readback()` показывает значение там, где оно
действует, ключом `export_timeout_sec`, а не только в миллисекундах батчера.

## Usage

```python
from Services.otel_export.config import OtelExportConfig
from Services.otel_export.exporter import OtlpHttpExporter, sdk_available

available, info = sdk_available()
# (True, "1.44.0")  либо  (False, "missing: uv pip install --inexact '.[otel]'")

cfg = OtelExportConfig(endpoint="http://127.0.0.1:4318", headers={"authorization": "${OTEL_TOKEN}"})
cfg.readback()["headers"]        # {"authorization": "***"}
cfg.readback()["export_timeout_sec"]  # 30.0 — уйдёт в OTLPLogExporter(timeout=...)

exporter = OtlpHttpExporter(cfg)          # ничего не открывает: объект SDK строится лениво
outcome = exporter.export(mapped_records)  # синхронно; 23-42 с, если приёмник недоступен
outcome.accepted, outcome.failed, outcome.reason
# (128, 0, "")  либо  (0, 128, "отправка в http://127.0.0.1:4318 не удалась: ...")
```

**Исход берётся из ВОЗВРАЩЁННОГО значения, а не из чужого лога.** Отказы SDK уходят в
stdlib-`logging`, у корневого логгера процесса фреймворка хендлеров нет — при закрытом
коллекторе экспортёр молчал бы, а счётчик показывал ноль потерь (замер Ф6.8: 26 тысяч
событий потери — ноль строк в `logs/`). Успех — ровно
`LogRecordExportResult.SUCCESS`; `FAILURE`, `None` и любой чужой объект читаются как отказ.

Три свойства, на которые стоит рассчитывать вызывающему:

* `accepted + failed == len(records)` на всех дорогах — включая перевод, построение SDK и
  исключение внутри него; исключения наружу не выпускаются;
* пустой батч даёт `(0, 0)` и **не строит объект SDK вовсе** — дожатие пустого кольца
  сокета не открывает;
* перевод строгий: отсутствующий `Resource`, `trace_id` не тех 32 hex-символов,
  `severity_number` вне словаря OTel — это отказ ВСЕГО батча с названной причиной
  (цена решения и отвергнутые варианты — ADR-OTEL-006).

Отправка синхронна, и её единственный боевой вызывающий (`otel_export.flush`) сидит на
приёмном потоке процесса — долг с числом записан в
[`Plugins/io/otel_export/STATUS.md`](../../Plugins/io/otel_export/STATUS.md), закрытие в Ф2.4.

Установка extra (ставит владелец, агент только выдаёт команду):

```
uv pip install --inexact '.[otel]'
```

`--inexact` обязателен: `uv sync` без него сносит всё, что не объявлено в зависимостях.

## Counters

Словарь счётчиков — **литералы**, на которые ссылаются тесты Ф2–Ф3 и тождество потерь
Task 3.4. Своей команды-интроспекции у экспортёра нет и не заводится: показания отдаёт
`otel_export.status` плюс штатные дороги наблюдаемости процесса.

**Счётчик живёт в ДВУХ плоскостях, и это не дубль (Р-7, Task 2.1).** Прежняя редакция
этого раздела утверждала, что числовой плоскости достаточно — «счётчики видны в
`introspect_telemetry`». **Это неверно, сверено по коду:** секция `levels` ответа
`introspect.telemetry` собирается из УРОВНЕЙ дерева состояния (`declare_metric` +
`publish_metric`), а плоскости stats там нет вовсе (`builtin_commands.py`, перечень
секций). Отсюда обе дороги, у каждой своя:

| Дорога | Имя | Кто читает |
|---|---|---|
| `ctx.record_metric` | точечное (`otel_export.received`) | `history_query(metric="otel_export.received")`, агрегаты окна, история в сторе |
| `ctx.declare_metric` + `ctx.publish_metric` | БЕЗ точки и без префикса (`received`) | `introspect.telemetry` → `levels`, GUI-строки; лист ложится в `state.plugins.otel_export.received` |

| Имя в плоскости чисел | Что означает |
|---|---|
| `otel_export.received` | запись принята от брокера и отмечена `observed_ts` |
| `otel_export.exported` | запись принята приёмником OTLP (`ExportOutcome.accepted`) |
| `otel_export.skipped_numbers` | числовой род (`kind ∈ {stats, observation}`) не экспортируется — штатный отказ фильтра, с разбивкой по `kind` |
| `otel_export.mapper_rejected` | `split_exportable` признал запись экспортируемой, а `to_otlp` вернул `None` — сработал ВТОРОЙ сторож числовой плоскости (`severity == "number"` при не-числовом `kind`). Это НЕ `skipped_numbers`: смешать их значило бы спрятать расхождение двух сторожей за общим числом |
| `otel_export.attr_coerced` | значение атрибута приведено к строке (`coerce_attributes`): `dict`/`set`/`Path`/`datetime`/разнородная последовательность/`None`. **Не потеря, а искажение** — ключ доехал, тип изменён |
| `otel_export.dropped_overflow` | запись выброшена своим bounded-кольцом ДО передачи в SDK (`drop_oldest`) |
| `otel_export.export_failed` | отправка отвергнута приёмником или не доехала (`ExportOutcome.failed`) |
| `otel_export.resource_evicted` | из пула `Resource` вытеснен самый старый источник (LRU). Считается ДЕЛЬТОЙ свойства `PooledResourceResolver.evicted`: `record_metric` — counter, и абсолютное значение сложилось бы само с собой |

Тождество потерь (Task 3.4) сводится из них:

```
received = exported + skipped_numbers + mapper_rejected + dropped_overflow + export_failed + (в кольце)
```

`attr_coerced` в тождество **не входит** и входить не может: приведение не теряет записи и
не теряет ключа — оно меняет тип значения. Своя ось, свой вопрос («насколько приёмник
получил не то, что было»).

**Ловушка именования, найденная при сверке с кодом 2026-09-05 и снятая в Task 2.1.** План
говорит «счётчики — `ctx.declare_metric(...)` + `ctx.record_metric(...)`», но это ДВЕ разные
плоскости с разными правилами имён: `record_metric` берёт точечное имя, а `declare_metric` —
это УРОВЕНЬ дерева состояния и **точку в имени отвергает `ValueError`**
(`plugins/base.py`, ADR-PM-038: точечное имя даёт вечно-мёртвый лист-двойник). Дословный
перенос строки плана уронил бы плагин на старте; в `plugin.py` имена разведены константой
`METRIC_PREFIX`, и она же — единственное место, где префикс написан.

## Boundaries

**Слои.** `multiprocess_framework → Services → Plugins → multiprocess_prototype`. Сервис
импортирует фреймворк (`data_schema_module` через `process_module.plugins`,
`channel_routing_module.levels`) и **никогда** — `Plugins/*` или `multiprocess_prototype/*`.
Обратные импорты enforced через `.sentrux/rules.toml` (проверять CLI `sentrux check .`, не
MCP-инструментом: тот смотрит 3 правила из 39 и пишет «All pass»).

**Фреймворк не получает зависимости от OTel.** Baseline `grep -rE '^\s*(import|from)
opentelemetry' multiprocess_framework/ --include=*.py` = **0** и обязан остаться нулём.

**SDK — только лениво.** Единственное место, которому позволено трогать `opentelemetry`, —
`exporter.py`, и только внутри функций. Импорт на уровне модуля запрещён: `class_loader`
глотает `ImportError` при построении класса (`log.error → None`), и отказ «нет extra
`[otel]`» стал бы молчаливым. Поэтому же `Resource` здесь — **наш** тип, а не
`opentelemetry.sdk.resources.Resource`.

**Никаких `if sys.platform`** в этом сервисе и в плагине: экспортёр кроссплатформенен по
построению, платформенная ветка — признак не той задачи.

**Что сервис НЕ делает и делать не будет:** свой persistent-буфер на диске, свои ретраи,
свой fan-out по нескольким бэкендам, свой sampler. Это работа коллектора (`otelcol`:
`file_storage`, persistent `sending_queue`, retry). OTLP — единственный контракт наружу.

**Что не входит в v1:** метрики и трейсы OTLP (числа считаются, но не экспортируются),
`scope` в атрибутах (ADR-LOG-005 ревизия Р-6: `scope` — внутреннее понятие маршрутизации),
экспорт плоскости документов (у неё своё хранилище, ADR-PM-028).

## Stability

| Что | Стабильность |
|---|---|
| Имена и сигнатуры Protocol'ов `interfaces.py` | **контракт фазы**: Ф1–Ф2 пишутся под них; смена — правкой этого файла и ADR |
| Поля и дефолты `OtelExportConfig` | контракт двери конфига; регистры плагина — производная, второй таблицы полей нет |
| Имена счётчиков | литералы, на них ссылаются тесты Ф2–Ф3 и тождество 3.4 |
| Форма `readback()` | ключи-поля + `export_timeout_sec`; на стадии `contract` это «что БУДЕТ передано в SDK», после Ф2 — снятое с построенных объектов |
| Версия SDK | пин minor `>=1.44,<1.45` в extras: Logs SDK живёт под `opentelemetry.sdk._logs` и совместимости в minor не обещает. **Обновление extras = прогон Ф1 заново** |

**Пока НЕ доказано (не заявлять как факт):** ни одна запись этим сервисом ещё не
отправлена — экспорта нет в коде. На Jetson и Raspberry не запускался ни разу; проверка
сделана по колёсам PyPI и артефактам релиза коллектора, здесь стоит «препятствий не найдено»,
а не «работает».

**Решения:** [`DECISIONS.md`](DECISIONS.md) · **Состояние:** [`STATUS.md`](STATUS.md)
