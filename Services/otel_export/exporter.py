# -*- coding: utf-8 -*-
"""Обёртка над OpenTelemetry SDK: проверка наличия и СИНХРОННАЯ отправка (Task 2.2).

**Единственное место сервиса, которому позволено трогать `opentelemetry`,** и
только ЛЕНИВО — внутри функции или метода. Импорт на уровне модуля запрещён
(критерий E1 плана): `class_loader` фреймворка глотает `ImportError` при
построении класса (`log.error -> None`), и отказ «нет extra [otel]» стал бы
молчаливым — процесс не поднялся бы без названной причины.

**Что здесь может сломаться, учитывая, как оно устроено.**

1. *Отказ доставки не слышен ниоткуда, кроме ВОЗВРАЩЁННОГО значения и зонда на
   транспорте.* SDK пишет свои жалобы в stdlib-`logging`, а у корневого логгера
   процесса фреймворка нет ни одного хендлера (`std_facade.py`, замер Ф6.8: 26
   тысяч событий потери — ноль строк в `logs/`). Поэтому исход берётся из
   `LogRecordExportResult`, а не из чужого лога, и никогда — из «исключения не
   было». Само по себе возвращаемое значение отвечает только «да/нет»: 401 и
   «чёрная дыра» дают ДОСЛОВНО одинаковый `FAILURE`. Чем отличается одно от
   другого — см. :class:`_TransportProbe` (Task 2.4).
2. *Отправка СИНХРОННА, и `timeout` вызов НЕ ограничивает.* `export()` держит
   вызывающего на всё время попыток, а `_export` повторяет POST на
   `requests.ConnectionError` с исходным таймаутом. Замеры CTO на стенде:
   refused localhost при 30000 мс — **23.44 с**, при 3000 мс — **4.08 с** (то
   есть +36% сверх «потолка»), чёрная дыра `10.255.255.1:4318` при 30 с —
   **42.08 с**, отвечающий 401 сервер — 0.02 с. Значит `export_timeout_ms` —
   дедлайн расписания ретраев, а не потолок вызова, и подпирать им границу
   нельзя. **С Task 2.4 боевой вызывающий здесь — не приёмный поток процесса, а
   поток дренажа очереди у хоста** (`Plugins/io/otel_export/plugin.py`,
   `BatchDrainWorker`): ждать сеть тут по-прежнему можно сколько угодно, но
   ждёт этого уже не почта процесса, а дедлайн останова держит `flush(timeout)`
   очереди, а не таймаут SDK.
3. *Один битый перевод роняет ВЕСЬ батч.* Перевод `MappedRecord` ->
   `ReadableLogRecord` строгий: отсутствующий `Resource`, `trace_id` не тех 32
   hex-символов, `severity_number` вне словаря OTel — это `ValueError`, то есть
   `failed == len(batch)` с названной причиной. Разделение батча на годные и
   битые не сделано намеренно: тождество потерь (Task 3.4) требует, чтобы каждая
   запись была посчитана ровно один раз, а частичный успех у синхронного
   `export()` неотличим от полного до Task 2.4.
4. *Отсутствие `trace_id` в модели SDK выражается НУЛЁМ, а не `None` — и это
   расходится с буквой Р-20.* Проверено запуском на 1.44.0: кодировщик
   `_encode_log` при `trace_id == 0` поля на провод НЕ кладёт (ровно «поля
   нет»), а при `None` падает `AttributeError: 'NoneType' object has no
   attribute 'to_bytes'`, то есть батч без трассы не уехал бы ни один. Дух Р-20
   («не подставлять правдоподобный идентификатор») соблюдён: ноль — это
   `INVALID_TRACE_ID` самого SDK, он не доезжает до приёмника. Подробности и
   красный приёмочный тест — в отчёте Task 2.2.
5. *`Resource.merge` молча теряет сторону.* При РАЗНЫХ непустых `schema_url` SDK
   пишет `Failed to merge resources` в тот же неслышимый stdlib-`logging` и
   возвращает только свою половину (`resources.py:SEMCONV_SCHEMA_URL`). Поэтому
   схема после сборки сверяется ЯВНО, а не принимается на веру.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from .config import OtelExportConfig
from .interfaces import ExportOutcome, FlushOutcome, MappedRecord, Resource

__all__ = [
    "INSTALL_HINT",
    "SDK_DISTRIBUTIONS",
    "TRACE_ID_HEX_LEN",
    "OtlpHttpExporter",
    "sdk_available",
]


#: Текст отказа для readback регистров и голоса плагина. Литерал: на него
#: ссылается приёмочный тест и он же попадает оператору в `otel_export.status`.
INSTALL_HINT = "missing: uv pip install --inexact '.[otel]'"
#: `--inexact` обязателен: `uv sync` без него сносит всё, что не объявлено
#: в зависимостях проекта (боевой опыт владельца).

#: Дистрибутивы extra `[otel]`. Пин minor — в `pyproject.toml`: Logs SDK живёт
#: под `opentelemetry.sdk._logs` и совместимости в minor не обещает.
SDK_DISTRIBUTIONS = ("opentelemetry-sdk", "opentelemetry-exporter-otlp-proto-http")

#: Длина W3C `trace_id` в hex-символах. Литерал, а не `len(что-то из данных)`:
#: длина — это и есть проверяемое свойство, вывести её из проверяемого значит
#: согласиться с любым.
TRACE_ID_HEX_LEN = 32


def sdk_available() -> tuple[bool, str]:
    """Установлен ли SDK — факт и человекочитаемая деталь.

    Post:
        * `(True, "<версия opentelemetry-sdk>")` — оба пакета extra `[otel]`
          импортируются; версия идёт в readback ключом `sdk`;
        * `(False, INSTALL_HINT)` — не импортируются. Наружу `ImportError`
          **не выпускается**: решение «что делать с отсутствием SDK» принимает
          хост (плагин уходит в состояние `error` с этим текстом), а не импорт.

    Проверяются оба пакета, а не один: `opentelemetry-sdk` может стоять как
    транзитивная зависимость чего-то ещё, а без `exporter-otlp-proto-http`
    отправлять всё равно нечем — и отказ вылез бы позже и глуше.
    """
    try:
        # Ровно те символы, которыми пользуется Ф2: проверка «пакет ставится»
        # без проверки нужных имён — зелёный сторож над сломанной установкой.
        from opentelemetry.exporter.otlp.proto.http._log_exporter import (  # noqa: F401
            OTLPLogExporter,
        )
        from opentelemetry.sdk._logs.export import (  # noqa: F401
            BatchLogRecordProcessor,
        )
    except ImportError:
        return False, INSTALL_HINT

    from importlib import metadata

    try:
        version = metadata.version("opentelemetry-sdk")
    except metadata.PackageNotFoundError:
        # Пакет импортируется, метаданных дистрибутива нет (vendoring, zip-app).
        # Говорим это прямо, а не подставляем правдоподобное число.
        return True, "версия неизвестна: метаданные дистрибутива opentelemetry-sdk не найдены"
    return True, version


#: Пометка на `requests.Session`: зонд уже навешен. Атрибут, а не флаг на
#: экспортёре: объект SDK может прийти извне (`sdk_factory`) и пережить не один
#: наш экземпляр — идемпотентность обязана жить там же, где обёрнутый метод.
_PROBE_ATTR = "_otel_export_transport_probe"


class _TransportProbe:
    """Обёртка `session.post`, запоминающая ИСХОД последней попытки транспорта.

    **Зачем вообще.** `OTLPLogExporter.export()` наружу отдаёт только
    `SUCCESS`/`FAILURE`: 401 (сервер ОТВЕТИЛ отказом аутентификации) и таймаут
    (сервер не ответил вовсе) неотличимы — обе дороги дают дословно один
    `reason` «приёмник вернул 'FAILURE'». На стенде это и есть самая дорогая
    минута: по такой строке нельзя решить, чинить токен или сеть.

    **Почему НЕ чтение логов SDK.** У логгера `_log_exporter/__init__.py:66`
    стоит `DuplicateFilter`: повторный ОДИНАКОВЫЙ отказ в лог не попадает
    вовсе. Механизм, читающий логи, ослеп бы на втором отказе подряд — и
    молча, что хуже, чем не знать причину совсем. `result.error` /
    `result.error_attrs`, которые SDK заполняет, живут в его внутреннем
    менеджере метрик и наружу не выходят.

    **Почему `_session` — не случайная внутренность.** `session` — публичный
    именованный параметр конструктора `OTLPLogExporter`: SDK сам предлагает
    подменять этот объект снаружи, а поле `self._session` — его известное
    место хранения. Точка выбрана как единственная, где ОДНОВРЕМЕННО видны и
    HTTP-ответ, и брошенное исключение транспорта.

    Успех не запоминается вовсе: показание нужно только для отказа, а хранить
    «последний успех» значило бы завести состояние, у которого нет читателя.
    """

    def __init__(self, post: Any) -> None:
        self._post = post
        #: Последний исход транспорта: `HTTP <код> <причина>` либо имя класса
        #: исключения. Пусто — зонд ничего не узнал (успех либо отказ случился
        #: раньше POST, например при кодировании).
        self.outcome = ""

    def forget(self) -> None:
        """Забыть прошлый исход ПЕРЕД новой отправкой.

        Без этого причина отказа прошлого батча пережила бы его и приклеилась
        к следующему, у которого POST не случился вовсе, — то есть показание
        стало бы тем правдоподобным враньём, ради борьбы с которым зонд и
        заведён.
        """
        self.outcome = ""

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        try:
            response = self._post(*args, **kwargs)
        except BaseException as exc:
            # Имя класса, а не текст: `ReadTimeout` отвечает на вопрос «что
            # именно», а текст requests у разных версий разный. Исключение
            # летит дальше — судит его SDK, а не зонд.
            self.outcome = type(exc).__name__
            raise
        # `ok` отсутствует -> зонд молчит: выдумывать исход по объекту, формы
        # которого он не знает, — то же враньё, только тише.
        if not getattr(response, "ok", True):
            code = getattr(response, "status_code", "?")
            reason = getattr(response, "reason", "") or ""
            self.outcome = f"HTTP {code} {reason}".strip()
        return response


class OtlpHttpExporter:
    """Синхронная отправка батча в приёмник OTLP/HTTP. Удовлетворяет `LogExporter`.

    Имя не `LogExporter` (Р-17): так зовут Protocol в `interfaces.py`, и
    одноимённый конкретный класс в том же пакете сломал бы `isinstance()` — тот
    же довод, что у `PooledResourceResolver` против `ResourceResolver`.

    Объект SDK строится ЛЕНИВО, при первой непустой отправке, и переживает её:
    `OTLPLogExporter` держит `requests.Session`, и построение его на каждый батч
    означало бы новое TCP-соединение на каждую пачку. Отказ построения (нет
    extra `[otel]`, битый `endpoint`) — это отказ ОТПРАВКИ с причиной, а не
    исключение наружу: решение «что делать» принимает хост, а не конструктор.
    """

    def __init__(
        self,
        config: OtelExportConfig,
        *,
        sdk_factory: Callable[[], Any] | None = None,
    ) -> None:
        """Запомнить конфиг и фабрику. Ничего не строит и упасть не может (Р-18).

        Args:
            config: разобранный конфиг сервиса. Значения берутся отсюда, а НЕ из
                `readback()` целиком: тот маскирует `headers` звёздочками, и
                отправка ушла бы с заголовком `***` вместо токена.
            sdk_factory: вызываемое без аргументов, возвращает объект с методом
                `export(batch)`. `None` -> настоящий `OTLPLogExporter`. Шов
                существует ради тестов: настоящий экспортёр открывает сокет, а
                тест, который ходит в сеть, либо виснет, либо врёт.
        """
        self._config = config
        self._sdk_factory = sdk_factory
        self._sdk: Any = None
        #: Зонд транспорта. Навешивается ЛЕНИВО, при первой отправке: объект SDK
        #: до неё не существует (а при `sdk_factory` он вообще чужой), и в
        #: конструкторе вешать не на что.
        self._probe: _TransportProbe | None = None

    # ------------------------------------------------------------------ #
    # Контракт LogExporter
    # ------------------------------------------------------------------ #

    def export(self, records: Sequence[MappedRecord]) -> ExportOutcome:
        """Отправить батч и вернуть ИСХОД числами (Р-19).

        **Что здесь может сломаться.** Соблазн — считать успехом «исключения не
        было»: SDK его и не бросает, он возвращает `LogRecordExportResult.FAILURE`
        и пишет причину в stdlib-`logging`, которого процесс не слышит. Поэтому
        успех — это ровно `LogRecordExportResult.SUCCESS`, а всё остальное
        (`FAILURE`, `None`, чужой объект) — отказ: неизвестный исход обязан
        читаться как «не доставлено», иначе потери станут невидимыми.

        Post:
            * `accepted + failed == len(records)` на ВСЕХ дорогах, включая
              перевод, построение SDK и исключение;
            * `reason` пуст ровно при `failed == 0`, а иначе называет endpoint И
              ИСХОД — HTTP-код либо класс исключения транспорта
              (:class:`_TransportProbe`). Универсальный шаблон «приёмник вернул
              'FAILURE'» остаётся ЗАПАСНЫМ и означает ровно одно: зонд ничего не
              узнал, отказ случился не на POST;
            * исключения наружу не выпускаются — поток вызывающего не падает
              из-за недоступного коллектора;
            * пустой батч -> `(0, 0)`, и SDK не строится и не зовётся вовсе:
              единственная бесплатная дорога, и она же снимает вопрос «а не
              откроет ли `flush` на пустом кольце сокет».

        `Exception`, а не `BaseException`: `KeyboardInterrupt` и `SystemExit` —
        это останов процесса, и проглотить их значило бы сделать процесс
        неубиваемым ради счётчика.
        """
        batch = list(records)
        if not batch:
            return ExportOutcome(accepted=0, failed=0, reason="")

        try:
            sdk = self._sdk_exporter()
            self._attach_probe(sdk)
            if self._probe is not None:
                self._probe.forget()
            payload = [self._to_sdk_record(record) for record in batch]
            result = sdk.export(payload)
            # Чтение исхода — ВНУТРИ try: `_is_success` лениво импортирует
            # `LogRecordExportResult`, и отказ этого импорта снаружи стал бы
            # исключением в потоке команды вместо посчитанного `failed`.
            succeeded = _is_success(result)
        except Exception as exc:
            # Исход отправки, а не падение потока: причина названа и посчитана.
            return ExportOutcome(
                accepted=0,
                failed=len(batch),
                reason=self._reason(f"{type(exc).__name__}: {exc}"),
            )

        if succeeded:
            return ExportOutcome(accepted=len(batch), failed=0, reason="")
        return ExportOutcome(accepted=0, failed=len(batch), reason=self._reason(self._failure_detail(result)))

    def _failure_detail(self, result: Any) -> str:
        """Чем именно кончилась попытка: показание зонда, иначе — запасной шаблон.

        Запасной шаблон не убран и убран не будет: он покрывает отказы, до POST
        не доехавшие вовсе (кодирование, отказ построения сессии), — и по нему
        читатель понимает, что зонд ничего не узнал, а не что причина «такая».
        """
        probe = self._probe
        if probe is not None and probe.outcome:
            return probe.outcome
        return f"приёмник вернул {getattr(result, 'name', result)!r}"

    def _attach_probe(self, sdk: Any) -> str:
        """Навесить зонд на `session.post` объекта SDK. Идемпотентно.

        Возвращает короткое слово об исходе. **Сегодня его не читает никто** —
        ни один вызывающий, ни один тест (проверено грепом при ревью), и обещание
        «оно нужно тесту опасностей и диагностике» из прежней редакции докстринга
        снято как неисполненное. Слово оставлено как заготовка для `otel_export.status`:
        там ему место, потому что «зонда нет» и «причина неизвестна» снаружи
        сегодня неотличимы. Пока этого нет — считать возврат мёртвым, а не опорой.

        Идемпотентность держится ПОМЕТКОЙ НА СЕССИИ, а не флагом на нас. Цена
        потери пометки — НЕ дубли запросов (замер ревью: повторная обёртка
        оборачивает предыдущий зонд, настоящий POST по-прежнему один), а линейно
        растущая цепочка обёрток: объект и кадр стека на каждую отправку за всю
        жизнь процесса, то есть утечка и `RecursionError` на горячем пути.
        """
        session = getattr(sdk, "_session", None)
        if session is None:
            # Чужой объект SDK (дубль в тесте, будущая замена транспорта) сессии
            # не обязан иметь вовсе. Это не отказ отправки — это отказ ДИАГНОЗА,
            # и он выражается запасным шаблоном причины, а не исключением.
            return "нет сессии"
        existing = getattr(session, _PROBE_ATTR, None)
        if isinstance(existing, _TransportProbe):
            self._probe = existing
            return "уже стоял"
        probe = _TransportProbe(session.post)
        session.post = probe
        setattr(session, _PROBE_ATTR, probe)
        self._probe = probe
        return "навешен"

    def force_flush(self, timeout: float) -> FlushOutcome:
        """Дожать очередь. Очереди у ЭКСПОРТЁРА нет — и после Task 2.4 тоже.

        Отправка здесь синхронна (Р-21): к моменту возврата `export()` записи
        либо доставлены, либо посчитаны потерянными, и держать между вызовами
        нечего. Поэтому честный ответ — `(0, 0)`, а не «дожали, сколько было».

        **Где очередь на самом деле (Task 2.4).** Она у ХОСТА, над этим методом:
        `Plugins/io/otel_export/plugin.py` держит `BatchDrainWorker`, чей сток —
        :meth:`export`. Так и обязано быть: приёмочный тест задачи подменяет
        именно `export` зависшим стоком и требует, чтобы приём записей при этом
        не блокировался, — то есть очередь по построению лежит ВЫШЕ этой точки.
        Останов дожимает её `BatchDrainWorker.flush(timeout)`, и дедлайн держит
        она же, а не SDK: `BatchProcessor.force_flush` SDK 1.44.0 несёт
        `TODO: Fix force flush so the timeout is used` (issue 4568), то есть
        переданный таймаут не соблюдает вовсе.
        """
        return FlushOutcome(flushed=0, lost=0)

    # ------------------------------------------------------------------ #
    # Построение SDK
    # ------------------------------------------------------------------ #

    def _sdk_exporter(self) -> Any:
        """Отдать объект SDK, построив его при первом обращении.

        **Что здесь может сломаться.** Ленивость — не оптимизация, а критерий E1:
        `import opentelemetry` на уровне модуля делает отказ «нет extra [otel]»
        молчаливым (`class_loader` глотает `ImportError` в `log.error -> None`).
        Поэтому импорт стоит ЗДЕСЬ, внутри метода, и покрыт приёмочным тестом,
        который запускает подпроцесс и смотрит `sys.modules`.

        Кэш — `self._sdk`, а не глобальный: два плагина с разными endpoint в
        одном процессе законны, а общий объект увёл бы записи одного в приёмник
        другого.
        """
        if self._sdk is None:
            self._sdk = self._sdk_factory() if self._sdk_factory is not None else self._build_sdk_exporter()
        return self._sdk

    def _build_sdk_exporter(self) -> Any:
        """Построить настоящий `OTLPLogExporter` из конфига.

        **Что здесь может сломаться.** `timeout` у `OTLPLogExporter` — В СЕКУНДАХ,
        а в конфиге лежит `export_timeout_ms`. Передать миллисекунды напрямую —
        это 30 000 секунд ожидания вместо 30, то есть таймаут, который никогда не
        наступит. Перевод берётся из `readback()`, где он уже назван
        `export_timeout_sec`: два места с делением на 1000 разошлись бы молча.

        `compression` — enum SDK, а не наша строка: конструктор чужую строку
        примет и молча положит её в заголовок `Content-Encoding`.
        """
        from opentelemetry.exporter.otlp.proto.http import Compression
        from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter

        return OTLPLogExporter(
            endpoint=self._config.endpoint,
            headers=dict(self._config.headers) or None,
            timeout=self._config.readback()["export_timeout_sec"],
            compression=Compression(self._config.compression),
        )

    # ------------------------------------------------------------------ #
    # Перевод в модель SDK (Р-20)
    # ------------------------------------------------------------------ #

    def _to_sdk_record(self, record: MappedRecord) -> Any:
        """`MappedRecord` -> `ReadableLogRecord`. Строго: неизвестное — отказ.

        **Что здесь может сломаться.** Каждое из трёх полей имеет правдоподобную
        неверную трактовку, и все три тихие: `trace_id` из 8 символов
        `int(v, 16)` переварит и отдаст маленькое число; отсутствующий `trace_id`
        так и просится в ноль; `severity_number` вне словаря OTel приёмник
        покажет как «неизвестно» вместо «ошибка». Поэтому перевод отказывает
        `ValueError`, а вызывающий превращает отказ в `failed` с причиной —
        громко и посчитано.

        `Resource` обязателен на записи (Р-1, `LogExporter.export` Pre): `None`
        здесь — это дефект вызывающего, а не запись «без ресурса», и молча
        подставить пустой ресурс значило бы отправить приёмнику запись без
        источника.
        """
        from opentelemetry.sdk._logs import ReadableLogRecord
        from opentelemetry.sdk._logs._internal import LogRecord
        from opentelemetry.sdk.util.instrumentation import InstrumentationScope
        from opentelemetry.trace import INVALID_TRACE_ID

        if record.resource is None:
            raise ValueError(f"запись без Resource: Resource обязателен на записи (Р-1), body={record.body!r}")

        log_record = LogRecord(
            timestamp=record.timestamp_ns,
            observed_timestamp=record.observed_timestamp_ns,
            severity_text=record.severity_text,
            severity_number=_severity_number(record.severity_number),
            body=record.body,
            attributes=dict(record.attributes),
        )
        # `trace_id` ставится ПОСЛЕ конструктора, и оба слова здесь существенны.
        # Конструктор SDK делает `trace_id or span_context.trace_id`: пустой у нас
        # трассы означал бы для него «возьми трассу ТЕКУЩЕГО спана процесса», и
        # запись уехала бы приклеенной к чужой, случайно активной трассе.
        # Отсутствие — это `INVALID_TRACE_ID` (0), потому что так его записывает
        # САМ SDK: кодировщик OTLP (`_encode_log`) при нуле поле на провод не
        # кладёт вовсе, а при `None` падает `AttributeError: 'NoneType' object has
        # no attribute 'to_bytes'` — воспроизведено на 1.44.0. То есть «поля нет»
        # на проводе достигается нулём, и только им.
        parsed_trace_id = _trace_id_to_int(record.trace_id)
        log_record.trace_id = INVALID_TRACE_ID if parsed_trace_id is None else parsed_trace_id
        return ReadableLogRecord(
            log_record,
            _to_sdk_resource(record.resource),
            InstrumentationScope(record.scope_name),
        )

    # ------------------------------------------------------------------ #
    # Причина отказа
    # ------------------------------------------------------------------ #

    def _reason(self, detail: str) -> str:
        """Причина отказа, ОБЯЗАТЕЛЬНО называющая endpoint.

        Без адреса причина бесполезна ровно там, где нужна: на стенде с двумя
        приёмниками «connection refused» не отвечает на вопрос, до кого не
        достучались.
        """
        return f"отправка в {self._config.endpoint} не удалась: {detail}"


# ============================================================================= #
# Свободные функции перевода. Вынесены из класса намеренно: они чистые, и их
# отдельно проверяют тесты опасных мест, не собирая экспортёр.
# ============================================================================= #


def _is_success(result: Any) -> bool:
    """Успех — ровно `LogRecordExportResult.SUCCESS`, всё прочее — отказ.

    Сравнение по идентичности с enum, а не `bool(result)`: у `SUCCESS` значение
    `0`, то есть `if result:` читало бы успех как ложь, а `FAILURE` (`1`) — как
    истину. Ровно наоборот.
    """
    # ПУБЛИЧНЫЙ путь `opentelemetry.sdk._logs.export` — тот же, который щупает
    # `sdk_available()`. Приватный `._internal.export` дал бы то же имя (сверено:
    # один и тот же объект на 1.44.0), но развёл бы пробу и горячий путь: проба
    # «ровно те символы, которыми пользуется Ф2» проверяла бы не тот модуль.
    from opentelemetry.sdk._logs.export import LogRecordExportResult

    return result is LogRecordExportResult.SUCCESS


def _trace_id_to_int(value: str | None) -> int | None:
    """32 hex-символа -> int; отсутствие -> `None`.

    Ноль на ЭТОМ уровне запрещён: здесь `None` означает «поля у записи нет», и
    вернуть отсюда ноль значило бы смешать отсутствие с идентификатором. В
    `INVALID_TRACE_ID` отсутствие переводит ВЫЗЫВАЮЩИЙ, у самой границы SDK, —
    и почему именно так, сказано в §4 докстринга модуля (буква Р-20 снята
    решением Р-26: модель SDK отсутствия через `None` не выражает).

    Длина проверяется ДО разбора: `int("abc", 16)` успешен и даёт 2748 —
    формально число, фактически чужой идентификатор, по которому приёмник
    склеит несвязанные трассы. Маппер (Ф1.1) обещает либо 32 hex, либо `None`,
    и нарушение этого обещания обязано быть слышно здесь, а не у приёмника.
    """
    if value is None:
        return None
    if len(value) != TRACE_ID_HEX_LEN:
        raise ValueError(f"trace_id обязан нести {TRACE_ID_HEX_LEN} hex-символов W3C, а несёт {len(value)}: {value!r}")
    try:
        return int(value, 16)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"trace_id не шестнадцатеричный: {value!r}") from exc


def _severity_number(value: int) -> Any:
    """int -> `SeverityNumber`. Число вне словаря OTel — отказ, а не «как есть».

    Шкала записи (5/9/13/17/21) уже словарь OTel, и любое другое число означает
    расхождение источника со шкалой. Пропустить его значило бы отдать приёмнику
    важность, которой в модели нет: он покажет её как неизвестную, и запись
    потеряет уровень молча.
    """
    from opentelemetry._logs import SeverityNumber

    try:
        return SeverityNumber(value)
    except ValueError as exc:
        raise ValueError(f"severity_number {value!r} вне словаря OTel SeverityNumber") from exc


def _to_sdk_resource(resource: Resource) -> Any:
    """Наш `Resource` -> `opentelemetry.sdk.resources.Resource` со сверкой схемы.

    **Что здесь может сломаться — ловушка Ф1, воспроизведённая запуском.**
    `Resource.create()` внутри МЕРЖИТ наши атрибуты с дефолтным ресурсом SDK и
    детекторами окружения. `Resource.merge` при РАЗНЫХ непустых `schema_url`
    пишет `Failed to merge resources` в stdlib-`logging` (неслышимый) и молча
    возвращает только СВОЮ сторону — наша схема исчезает без единого признака.
    С дефолтным ресурсом конфликта нет (его `schema_url` пуст, сверено на SDK
    1.44.0), но детектор из `OTEL_EXPERIMENTAL_RESOURCE_DETECTORS` со своей
    схемой этот конфликт создаёт. Поэтому схема сверяется ПОСЛЕ сборки, и при
    расхождении ресурс собирается напрямую — без обогащения `telemetry.sdk.*`,
    зато с той версией словаря, по которой атрибуты действительно собраны.
    """
    from opentelemetry.sdk.resources import Resource as SdkResource

    attributes = dict(resource.attributes)
    built = SdkResource.create(attributes, resource.schema_url)
    if resource.schema_url and built.schema_url != resource.schema_url:
        return SdkResource(attributes, resource.schema_url)
    return built
