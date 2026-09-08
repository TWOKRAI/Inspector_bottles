# -*- coding: utf-8 -*-
"""Приёмочный тест Task 2.4 (Services-слой) — независимый тестер, ДО реализации.

Источник критериев — бриф тестеру Task 2.4 трека ``otel-export``. Покрывает ТОЛЬКО
критерий 5 («голос об отказе доставки обязан называть HTTP-код или класс исключения,
а не только адрес и число»); критерии 1, 2, 3, 4, 6 — в
``Plugins/io/otel_export/tests/test_f2_task24_acceptance.py``.

**MODE эквивалент RED** — заголовка MODE/INTERFACE/TASK в брифе не было, но явные
forbidden-paths + требование красного набора делают бриф RED-эквивалентом (см. память
тестера ``feedback_freeform_brief_without_mode_header``).

**Важная ревизия ПОСЛЕ первого прогона (честность важнее правдоподобия).** Первая
редакция этого файла имитировала отказ SDK через дубль, БРОСАЮЩИЙ исключение
(``sdk_factory`` -> объект, чей ``.export()`` делает ``raise requests.exceptions.HTTPError(...)``
и т.п.) — по образцу ``TestExceptionDoesNotEscape`` из Task 2.2. Прогон дал **4 из 4
зелёных** — то есть красного состояния не было вовсе, и как ТЗ для Task 2.4 та редакция
была бы бесполезна (зелёный тест ничего не говорит будущему разработчику, что строить).

Расследование (``Services/otel_export/exporter.py`` по-прежнему НЕ читан — расследован
СТОРОННИЙ, установленный код:
``.venv/Lib/site-packages/opentelemetry/exporter/otlp/proto/http/_log_exporter/__init__.py``,
пакет ``opentelemetry-exporter-otlp-proto-http==1.44.0``, тот же, что называет
``Services/otel_export/config.py`` в комментариях к ``schedule_delay_ms``/``export_timeout_ms``)
показало: **настоящий ``OTLPLogExporter.export()`` НИКОГДА не бросает исключение наружу**
(``requests.exceptions.RequestException`` ловится ВНУТРИ, строка 212 файла) — он ВСЕГДА
возвращает ``LogRecordExportResult.SUCCESS``/``FAILURE``. Реальный HTTP-код и причина
(``status_code``, ``reason``) существуют внутри SDK (``_logger.error("Failed to export
logs batch code: %s, reason: %s", status_code, reason)``) — и уходят в stdlib-`logging`,
куда наш процесс не слушает (тот же факт называет докстринг ``ExportOutcome`` в
``interfaces.py``: «отказы SDK уходят в stdlib-`logging` и у нас не слышны»). Прямым
прогоном ЭТОГО файла (реальный ``OTLPLogExporter`` с подменённым ``_session.post``,
без сети) воспроизведено: **401 (аутентификация) и таймаут («чёрная дыра») дают
БУКВАЛЬНО ОДИНАКОВЫЙ ``reason``** — ``"отправка в <endpoint> не удалась: приёмник вернул
'FAILURE'"`` — ни кода, ни причины, только адрес. Это и есть предмет критерия 5,
воспроизведённый настоящим SDK, а не угаданным дублем.

Тесты ниже используют РЕАЛЬНЫЙ ``OTLPLogExporter`` (не собственный дубль формы SDK) с
подменённым ``_session.post`` — сеть не трогается нигде, но путь ретраев/логирования
внутри SDK исполняется по-настоящему. Выбраны НЕ-повторяемые причины отказа
(``_is_retryable``: 401 — нет; ``requests.exceptions.ReadTimeout`` — не подкласс
``requests.exceptions.ConnectionError``, поэтому тоже не ретраится) — иначе SDK уходит
в цикл до 6 повторов с экспоненциальной паузой (до ~60 с), и тест стал бы медленным и
хрупким по времени.

**Что ЗАПРЕЩЕНО было читать**: ``Plugins/io/otel_export/plugin.py``,
``Services/otel_export/exporter.py``, ``Plugins/io/otel_export/tests/test_f2_task21_hazards.py``,
``Services/otel_export/tests/test_f2_task22_hazards.py``. Сигнатуры ``OtlpHttpExporter``
получены ТОЛЬКО через ``inspect.signature`` (см. другой файл трека, тот же приём).

**Что ненадёжно в этой проверке** — см. раздел отчёта тестера в финальном ответе;
коротко: не проверено, ЧЕМ именно Task 2.4 донесёт ``status_code``/причину до
``ExportOutcome.reason`` (перехват stdlib-логгера SDK, обёрнутая ``requests.Session``,
собственный HTTP-слой в обход SDK) — тест проверяет ТОЛЬКО наблюдаемый результат
(``reason`` различим и называет код/класс), а не механизм.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
import requests
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter

from Services.otel_export.config import OtelExportConfig
from Services.otel_export.interfaces import MappedRecord, Resource

#: 32 hex символа — валидный по форме W3C trace_id (тот же литерал, что у Task 2.2).
VALID_TRACE_ID = "0123456789abcdef0123456789abcdef"


def _cfg(**overrides: Any) -> OtelExportConfig:
    data: dict[str, Any] = {"endpoint": "http://127.0.0.1:4318/v1/logs"}
    data.update(overrides)
    return OtelExportConfig(**data)


def _mapped_record(**overrides: Any) -> MappedRecord:
    base: dict[str, Any] = dict(
        timestamp_ns=1_700_000_000_000_000_000,
        observed_timestamp_ns=1_700_000_000_100_000_000,
        severity_text="ERROR",
        severity_number=17,
        body="boom",
        scope_name="camera_1.worker",
        attributes={"k": "v"},
        trace_id=VALID_TRACE_ID,
        resource=Resource(attributes={"service.name": "inspector"}, schema_url=""),
    )
    base.update(overrides)
    return MappedRecord(**base)


def _real_sdk_exporter(
    endpoint: str, *, status_code: int | None = None, reason: str | None = None, raise_exc: BaseException | None = None
) -> OTLPLogExporter:
    """НАСТОЯЩИЙ ``OTLPLogExporter`` с подменённым ``_session.post`` — сеть не трогается,
    но retry/логирование внутри SDK исполняются по-настоящему (см. докстринг файла)."""
    real = OTLPLogExporter(endpoint=endpoint)

    if raise_exc is not None:

        def _post(*_a: Any, **_k: Any) -> Any:
            raise raise_exc

    else:

        def _post(*_a: Any, **_k: Any) -> Any:
            return SimpleNamespace(ok=False, status_code=status_code, reason=reason)

    real._session.post = _post  # type: ignore[attr-defined]
    return real


def _export_via_real_sdk(sdk_double: OTLPLogExporter) -> Any:
    from Services.otel_export.exporter import OtlpHttpExporter

    exp = OtlpHttpExporter(_cfg(), sdk_factory=lambda: sdk_double)
    return exp.export([_mapped_record()])


# ---------------------------------------------------------------------------
# Критерий 5: 401 (не ретраится) и «чёрная дыра»/таймаут (тоже не ретраится, см.
# докстринг файла) дают СЕГОДНЯ ОДИНАКОВЫЙ reason у настоящего SDK — обязаны различаться.
# ---------------------------------------------------------------------------


class TestDeliveryFailureReasonNamesCodeOrExceptionClass:
    """Критерий 5. Стережёт: reason у ЯВНО РАЗНЫХ причин отказа (сервер ОТВЕТИЛ отказом
    аутентификации vs сервер НЕ ОТВЕТИЛ вовсе — таймаут) обязан различаться и называть
    что-то конкретное (код 401 либо класс/природу таймаута), а не только адрес.

    Как это правдоподобно ломается: реализация продолжает читать ТОЛЬКО возвращаемое
    значение ``LogRecordExportResult`` (SUCCESS/FAILURE) и ни разу не заглядывает в то,
    ЧТО настоящий SDK знает о причине (HTTP-статус, класс пойманного исключения) — тогда
    ``test_401_and_read_timeout_currently_give_the_same_reason_and_must_stop`` красный
    ровно так же, как воспроизведено в докстринге файла ДО реализации.
    """

    def test_401_and_read_timeout_give_different_reasons(self) -> None:
        """Ядро критерия: явно разные причины отказа -> явно разные строки reason."""
        sdk_401 = _real_sdk_exporter("http://127.0.0.1:4318/v1/logs", status_code=401, reason="Unauthorized")
        sdk_timeout = _real_sdk_exporter(
            "http://127.0.0.1:4318/v1/logs", raise_exc=requests.exceptions.ReadTimeout("Read timed out")
        )

        outcome_401 = _export_via_real_sdk(sdk_401)
        outcome_timeout = _export_via_real_sdk(sdk_timeout)

        assert outcome_401.failed == 1, f"401 обязан дать failed == 1: {outcome_401!r}"
        assert outcome_timeout.failed == 1, f"таймаут обязан дать failed == 1: {outcome_timeout!r}"
        assert outcome_401.reason != outcome_timeout.reason, (
            "401 (сервер ОТВЕТИЛ отказом) и таймаут (сервер НЕ ОТВЕТИЛ вовсе) дают ОДИНАКОВЫЙ "
            f"reason — долг воспроизведён дословно настоящим SDK: {outcome_401.reason!r} == "
            f"{outcome_timeout.reason!r}"
        )

    def test_401_reason_names_the_status_code(self) -> None:
        sdk_401 = _real_sdk_exporter("http://127.0.0.1:4318/v1/logs", status_code=401, reason="Unauthorized")
        outcome = _export_via_real_sdk(sdk_401)
        assert "401" in outcome.reason, f"reason не называет HTTP-код 401: {outcome.reason!r}"

    def test_read_timeout_reason_names_timeout_not_the_generic_failure_template(self) -> None:
        sdk_timeout = _real_sdk_exporter(
            "http://127.0.0.1:4318/v1/logs", raise_exc=requests.exceptions.ReadTimeout("Read timed out")
        )
        outcome = _export_via_real_sdk(sdk_timeout)
        lowered = outcome.reason.lower()
        assert "timeout" in lowered or "timed out" in lowered or "readtimeout" in lowered, (
            f"reason не называет природу таймаута («чёрная дыра»): {outcome.reason!r}"
        )
        assert "приёмник вернул" not in outcome.reason, (
            f"reason — универсальный шаблон «приёмник вернул 'FAILURE'», неотличимый от ЛЮБОЙ "
            f"другой причины отказа (сегодняшний долг): {outcome.reason!r}"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
