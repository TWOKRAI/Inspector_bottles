# -*- coding: utf-8 -*-
"""Публичные контракты Services/otel_export — что обязаны реализовать Ф1 и Ф2.

Пять Protocol'ов и четыре типа контракта. Реализации здесь НЕТ: маппер (Ф1.1),
резолвер Resource (Ф1.2) и экспортёр поверх OTel SDK (Ф2.4) приходят позже и
пишутся под уже названные здесь имена.

Правило слоя: внешние потребители (`Plugins/io/otel_export`) импортируют
контракт отсюда, а не из внутренних модулей сервиса.

**Ни одного `import opentelemetry` на уровне модуля** (критерий E1 плана).
Тип :class:`Resource` — НАШ тип контракта, а не `opentelemetry.sdk.resources.Resource`:
сервис обязан импортироваться без установленного extra `[otel]`, иначе отказ
SDK будет молчаливым (`class_loader` глотает `ImportError` в `log.error -> None`).
Перевод нашего `Resource` в объект SDK — задача обёртки экспортёра (Ф2).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

__all__ = [
    "ExportOutcome",
    "FlushOutcome",
    "LogExporter",
    "MappedRecord",
    "ObservabilityPort",
    "RecordMapper",
    "Resource",
    "ResourceResolver",
]


# =============================================================================
# Типы контракта
#
# Выбор «dataclass, а не TypedDict» обоснован в DECISIONS.md (ADR-OTEL-002):
# приёмочные тесты обращаются к полям точкой (`outcome.accepted`), у TypedDict
# такого доступа нет вовсе; frozen+slots дают опечатке в имени поля громкий
# отказ вместо тихого нового ключа.
# =============================================================================


@dataclass(frozen=True, slots=True)
class Resource:
    """Ресурс OTel — «кто породил запись», собранный НАШИМ резолвером (Ф1.2).

    Атрибуты по semconv (`service.name`, `service.version`, `service.instance.id`,
    `process.pid`, `host.name`, `service.namespace`) плюс свои (`inspector.recipe`).

    Инвариант: **отсутствующее поле пропускается, а не заполняется "unknown"** —
    правило источника (`core/process_module.py`, сборка пятёрки Resource);
    экспортёр его сохраняет. Ключа нет в `attributes` == поля нет у записи.
    """

    attributes: Mapping[str, str | int | float | bool] = field(default_factory=dict)
    schema_url: str = ""
    """Версия словаря semconv, по которому собран `attributes`. Пусто — версия
    не заявлена; потребитель тогда читает атрибуты «как есть»."""


@dataclass(frozen=True, slots=True)
class MappedRecord:
    """Одна запись, приведённая к модели OTel Logs Data Model.

    Имена полей — наши, значения — в терминах словаря OTel (`log_types.py:17-74`).
    Перевод в объект SDK (`ReadableLogRecord`) делает обёртка экспортёра (Ф2).

    Поля `trace_id` и `resource` — единственные необязательные: битый или пустой
    `trace_id` даёт **отсутствие поля**, а не нули (Ф1.1); `resource` заполняет
    хост после :meth:`ResourceResolver.resolve`, маппер оставляет `None`.
    """

    timestamp_ns: int | None
    """`Timestamp` — момент порождения записи, наносекунды unix-эпохи. `None` —
    источник времени не дал; поле не отправляется."""

    observed_timestamp_ns: int | None
    """`ObservedTimestamp` — момент ПРИЁМА записи экспортёром (`stamp_observed`).
    Ставит только приёмник; уже проставленный не перетирается (Ф2.1)."""

    severity_text: str
    """`SeverityText` — имя уровня как есть (`DEBUG`…`CRITICAL`)."""

    severity_number: int
    """`SeverityNumber` — КОПИЯ числа записи, без пересчёта: шкала
    `channel_routing_module/levels.py:SEVERITY_NUMBERS` (5/9/13/17/21) уже
    словарь OTel. Пересчёт по рангу 0…4 — дефект, на него есть инъекция Ф1.1."""

    body: str
    """`Body` — текст сообщения."""

    scope_name: str
    """`InstrumentationScope.name` — поле `module` записи. НЕ поле `scope`:
    `scope` — внутреннее понятие маршрутизации и наружу не едет (ADR-LOG-005, Р-6)."""

    attributes: Mapping[str, Any]
    """`Attributes` — остаток `extra.context` ПОСЛЕ изъятия `trace_id`, пятёрки
    Resource и `origin`, плюс `record.kind` из конверта."""

    trace_id: str | None = None
    """`TraceId` — 32 hex W3C из `extra.context.trace_id`. Выделенное поле, не атрибут."""

    resource: Resource | None = None
    """Ресурс записи. `None` до вызова резолвера — обёртке экспортёра такая
    запись не годится: Resource в OTel обязателен на записи (Р-1)."""


@dataclass(frozen=True, slots=True)
class ExportOutcome:
    """Исход одной попытки отправки батча.

    Инвариант: `accepted + failed` == число записей, поданных в
    :meth:`LogExporter.export`. Считается по ВОЗВРАЩЁННОМУ результату, а не по
    чужому логу: отказы SDK уходят в stdlib-`logging` и у нас не слышны
    (`std_facade.py` — у корневого логгера процесса нет хендлеров), см. Ф2.2.
    """

    accepted: int
    """Сколько записей приёмник принял."""

    failed: int
    """Сколько записей отвергнуто или не доехало."""

    reason: str = ""
    """Причина отказа для голоса и счётчика `export_failed`. Пусто при `failed == 0`."""


@dataclass(frozen=True, slots=True)
class FlushOutcome:
    """Исход финального дожатия очереди при останове (Ф2.4).

    Пара чисел, а не bool: `True` от `force_flush` SDK не отличает «дожали 100»
    от «дожали 0». Строка останова литералом — `otel flush: N дожато, M потеряно`.
    """

    flushed: int
    """Сколько записей ушло за отведённый таймаут."""

    lost: int
    """Сколько осталось в очереди и потеряно вместе с процессом."""


# =============================================================================
# Protocol'ы
# =============================================================================


@runtime_checkable
class RecordMapper(Protocol):
    """Display-запись -> запись модели OTel. Чистая функция, без сети (Ф1.1)."""

    def to_otlp(self, display_record: Mapping[str, Any]) -> MappedRecord | None:
        """Отобразить одну display-запись в модель OTel.

        Pre:
            `display_record` — display-вид записи наблюдаемости
            (`record_display.hub_record_to_display` / `log_record_to_display`),
            то есть `dict` (Dict at Boundary), а не объект `LogRecord`.
            Пятёрка Resource, `trace_id` и `origin` лежат на `extra.context.*`.

        Post:
            * возвращён :class:`MappedRecord` — запись экспортируется;
            * возвращён `None` — запись НЕ экспортируется, и это **штатный**
              исход, а не ошибка: числовые рода (`kind in {stats, observation}`,
              `severity == "number"`) отсекает фильтр Ф1.3 ДО маппера, а сюда
              они попадать не должны вовсе; если попали — маппер отказывает,
              а не гадает.

        Инвариант учёта: **каждый `None` обязан быть посчитан** вызывающим
        (`skipped_numbers` с разбивкой по `kind`). Молчаливый `None` неотличим
        от «записей не было» — это класс дефекта, а не мелочь.
        """
        ...


@runtime_checkable
class ResourceResolver(Protocol):
    """Контекст записи -> :class:`Resource`, с пулом и вытеснением (Ф1.2)."""

    def resolve(self, context: Mapping[str, Any]) -> Resource:
        """Собрать (или взять из пула) Resource для источника записи.

        Pre:
            `context` — содержимое `extra.context` записи. Ключ пула —
            `(proc_name, pid, incarnation)`; отсутствующие ключи законны.

        Post:
            * возвращён :class:`Resource`, у которого атрибута НЕТ для каждого
              отсутствующего поля контекста (никаких `"unknown"`);
            * `host.name` и `service.namespace` одинаковы у всех записей одного
              экспортёра: они принадлежат ЭКСПОРТЁРУ, а не записи (IPC локален);
            * пул ограничен `resource_pool_size`; вытеснение LRU увеличивает
              счётчик `resource_evicted`. Пул без предела — утечка на долгом
              прогоне, счётчик без вытеснения — слепое место.
        """
        ...


@runtime_checkable
class LogExporter(Protocol):
    """Отправка записей наружу и дожатие очереди на останове (Ф2.2, Ф2.4)."""

    def export(self, records: Sequence[MappedRecord]) -> ExportOutcome:
        """Отправить батч записей приёмнику OTLP.

        Pre:
            У каждой записи `resource is not None` (Resource обязателен на
            записи — Р-1). Вызывающий поток НИКОГДА не ждёт сеть: отправка
            асинхронна (`BatchLogRecordProcessor`), переполнение очереди —
            `drop_oldest` со счётчиком `dropped_overflow` ДО передачи в SDK.

        Post:
            * возвращён :class:`ExportOutcome`, `accepted + failed == len(records)`;
            * исключения наружу НЕ выпускаются: отказ доставки — это `failed` и
              `reason`, а не падение потока приёма;
            * `HTTP 200` от приёмника **не значит «доставлено»** (Task 0.1:
              запрос без конверта `resourceLogs` даёт 200 при нуле записей) —
              счёт ведётся по записям, а тождество потерь сводится в Task 3.4.
        """
        ...

    def force_flush(self, timeout: float) -> FlushOutcome:
        """Дожать очередь при останове.

        Pre:
            `timeout` — секунды. **С Task 2.4**: зовётся в `shutdown(ctx)` ДО снятия
            форвардеров и до останова логгера (порядок `ProcessModule.stop()`).
            **В Task 2.2 на останове НЕ зовётся вовсе** (вердикт CTO): синхронное
            дожатие жило 23-42 с против бюджета останова 5 с, процесс убивали
            внутри retry-цикла SDK, и последняя пачка выпадала из тождества потерь.
            Пока отправка синхронна, дожимать нечего — очереди у экспортёра нет,
            и метод отдаёт `(0, 0)`.

        Post:
            * возвращён :class:`FlushOutcome` — два числа, а не bool;
            * исход записан строкой в журнал литералом
              `otel flush: N дожато, M потеряно`.

        **Оговорка про таймаут, сверенная с установленным SDK 1.44.0:**
        `BatchProcessor.force_flush` несёт `TODO: Fix force flush so the timeout
        is used` (issue 4568) — переданный таймаут SDK не соблюдает. Значит
        число `lost` берётся из состояния очереди, а не из «сработал таймаут».
        """
        ...


@runtime_checkable
class ObservabilityPort(Protocol):
    """Минимальный разъём наблюдаемости, которого хватает сервису.

    Своего контекста сервис не заводит (решение плана, пересечение с
    closure 4.5): порт достаточно узкий, чтобы ему удовлетворял `PluginContext`
    сегодня и `ServiceContext` после closure 4.5.

    **Расхождение, найденное при сверке с кодом 2026-09-05 — не замолчано:**
    `PluginContext` даёт четыре метода из пяти. `report_error` у него живёт НЕ
    на контексте, а на `ctx.health.report_error` (`plugins/base.py`, свойство
    `health` -> `HealthReporter`). То есть `isinstance(ctx, ObservabilityPort)`
    сегодня **False**, и хост (Ф2) обязан передать сервису тонкий адаптер, а не
    сам `ctx`. Подробности и отвергнутые варианты — ADR-OTEL-004.

    Сигнатуры повторяют фреймворк: `record_metric(name, value=1, tags=None)`
    (`plugins/base.py`), `report_error(exc, context=None, throttle=None, **fields)`
    (`process_module/health/state.py`). Первый аргумент `report_error` во
    фреймворке зовётся `exc` — **передавать позиционно**, вызов с ключом
    `report_error(error=...)` сломается об адаптер над `HealthReporter`.
    """

    def log_info(self, message: str, **fields: Any) -> None:
        """Диагностическая строка уровня INFO. НЕ инцидент."""
        ...

    def log_warning(self, message: str, **fields: Any) -> None:
        """Штатная деградация — строка уровня WARNING."""
        ...

    def log_error(self, message: str, **fields: Any) -> None:
        """Строка уровня ERROR, которая инцидентом НЕ становится (ADR-PM-030).

        Инцидент — это :meth:`report_error`. Оба разъёма в одной ветке
        исполнения запрещены и сторожатся машинно
        (`multiprocess_framework/modules/tests/test_one_connector_per_point.py`).
        """
        ...

    def record_metric(self, name: str, value: Any = 1, tags: dict | None = None) -> None:
        """Число в числовую плоскость: счётчики экспортёра (словарь — в README)."""
        ...

    def report_error(
        self,
        error: BaseException,
        context: str | None = None,
        throttle: float | None = None,
        **fields: Any,
    ) -> None:
        """ИНЦИДЕНТ: плоскость ошибок + голос в журнал + счётчик health.

        `throttle` — окно ГОЛОСА и только его: факт учитывается на каждое
        вхождение (Task 1.3a closure, ADR-PM-045).
        """
        ...
