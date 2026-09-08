# -*- coding: utf-8 -*-
"""Тесты опасных мест Task 2.4, Services-слой: зонд транспорта.

Пишет автор реализации — про внутренние риски МЕХАНИЗМА, которые независимый
тестер видеть не обязан: он проверяет наблюдаемое свойство («причина отказа
различима»), а здесь проверяется то, чем это свойство держится, и то, что оно
не ломает соседей.

**Что в ЭТОМ механизме правдоподобно ломается.**

1. *Зонд навешивается дважды.* `export()` зовётся на каждую пачку, а навешивание
   ленивое — идемпотентность держится ПОМЕТКОЙ на сессии. Потеряй её, и каждая
   отправка добавляла бы ещё один слой обёртки: на десятой пачке один POST
   превратился бы в десять настоящих запросов к коллектору. Снаружи это выглядит
   как «коллектор получает дубликаты», а не как дефект экспортёра.
2. *Показание переживает свой батч.* Причина хранится между вызовами (иначе её
   нечем было бы отдать после возврата SDK). Не забудь её перед новой отправкой —
   и отказ, случившийся ДО POST (битый перевод записи), отчитается прошлым
   HTTP-кодом. Это ровно тот класс дефекта, ради которого зонд и заведён:
   правдоподобная причина хуже отсутствующей.
3. *Объект SDK без `_session`.* Через `sdk_factory` приходит что угодно — дубль
   теста, будущий транспорт. Зонд обязан промолчать, а не уронить отправку:
   отказ ДИАГНОЗА не имеет права стать отказом ДОСТАВКИ.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
import requests
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter

from Services.otel_export.config import OtelExportConfig
from Services.otel_export.exporter import OtlpHttpExporter
from Services.otel_export.interfaces import MappedRecord, Resource

ENDPOINT = "http://127.0.0.1:4318/v1/logs"
VALID_TRACE_ID = "0123456789abcdef0123456789abcdef"


def _cfg(**overrides: Any) -> OtelExportConfig:
    data: dict[str, Any] = {"endpoint": ENDPOINT}
    data.update(overrides)
    return OtelExportConfig(**data)


def _record(**overrides: Any) -> MappedRecord:
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


def _sdk_with_counted_post(status_code: int = 401, reason: str = "Unauthorized") -> tuple[OTLPLogExporter, list[int]]:
    """Настоящий SDK с подменённым `_session.post`, считающим ВЫЗОВЫ.

    Сеть не трогается: `post` подменён. 401 выбран не случайно — он не
    ретраится (`_is_retryable`), то есть на одну отправку приходится РОВНО один
    POST, и число вызовов становится показанием, а не шумом расписания.
    """
    sdk = OTLPLogExporter(endpoint=ENDPOINT)
    calls: list[int] = []

    def _post(*_a: Any, **_k: Any) -> Any:
        calls.append(1)
        return SimpleNamespace(ok=False, status_code=status_code, reason=reason)

    sdk._session.post = _post  # type: ignore[attr-defined]
    return sdk, calls


class TestProbeIsAttachedExactlyOnce:
    """Опасность 1: повторное навешивание превращает один POST в N настоящих."""

    def test_the_probe_is_attached_once_and_does_not_grow_a_chain(self) -> None:
        """Пометка на сессии стережётся ГЛУБИНОЙ обёртки, а не числом POST.

        **Прежняя редакция была зелёной по неверной причине, и её довод неверен**
        (находка ревью, воспроизведена заплатой «снять пометку»): она считала
        POST'ы, ожидая 1-2-4, и обещала «коллектор получит дубликаты». Дубликатов
        не бывает: повторное навешивание оборачивает ПРЕДЫДУЩИЙ зонд, вызов идёт
        цепочкой probe2 -> probe1 -> post, и настоящий запрос по-прежнему один.
        Заплата убивала **0 тестов из 246**.

        Настоящая цена потери пометки другая: цепочка обёрток растёт линейно —
        объект и кадр стека на каждую отправку за всю жизнь процесса. Замер с
        заплатой: после 5 отправок глубина 5 при 5 POST. То есть утечка и, на
        горячем пути, `RecursionError`. Сторожим именно это.
        """
        from Services.otel_export.exporter import _TransportProbe

        sdk, calls = _sdk_with_counted_post()
        exporter = OtlpHttpExporter(_cfg(), sdk_factory=lambda: sdk)

        exporter.export([_record()])
        first_probe = sdk._session.post
        assert isinstance(first_probe, _TransportProbe), "зонд не навешен вовсе — сторожить нечего"

        for _ in range(4):
            exporter.export([_record()])

        assert sdk._session.post is first_probe, (
            "зонд навешен повторно: цепочка обёрток растёт на каждую отправку — "
            "объект и кадр стека за всю жизнь процесса"
        )
        assert not isinstance(first_probe._post, _TransportProbe), (
            "под зондом оказался ещё один зонд — обёртка обернула обёртку"
        )
        assert len(calls) == 5, f"настоящих POST обязано быть 5, а их {len(calls)}"


class TestProbeDoesNotOutliveItsBatch:
    """Опасность 2: причина прошлого батча приклеивается к следующему."""

    def test_translation_failure_after_a_401_does_not_report_401(self) -> None:
        """Отказ ДО POST обязан назвать себя, а не прошлый HTTP-код.

        Вторая запись битая (`trace_id` не тех 32 hex-символов) — до транспорта
        она не доезжает вовсе, POST не случается. Убери `forget()`, и причина
        отказа перевода отчитается «HTTP 401 Unauthorized»: диагноз указал бы на
        токен, когда сломан формат записи.
        """
        sdk, calls = _sdk_with_counted_post()
        exporter = OtlpHttpExporter(_cfg(), sdk_factory=lambda: sdk)

        first = exporter.export([_record()])
        assert "401" in first.reason, f"сценарий не воспроизведён, первый отказ не 401: {first.reason!r}"

        posts_after_first = len(calls)
        second = exporter.export([_record(trace_id="abc")])

        assert len(calls) == posts_after_first, (
            f"битая запись всё-таки уехала в транспорт: POST'ов было {posts_after_first}, стало {len(calls)}"
        )
        assert second.failed == 1, f"битый перевод обязан дать failed == 1: {second!r}"
        assert "401" not in second.reason, (
            f"причина отказа перевода унаследована от прошлого батча — зонд не забыл своё показание: {second.reason!r}"
        )
        assert "trace_id" in second.reason, f"причина не называет настоящий отказ (перевод записи): {second.reason!r}"

    def test_success_after_a_failure_leaves_no_reason_at_all(self) -> None:
        """Пара: починившийся приёмник не имеет права нести причину прошлого отказа.

        **Код взят НЕповторяемый, и это не деталь.** Первая редакция теста отвечала
        503 — а его SDK считает временным и ретраит: вторая попытка возвращала 200,
        отказа не случалось вовсе, и тест падал на своём же предохранителе
        «сценарий не воспроизведён» (). То есть
        красным был не предмет, а посылка о чужом поведении. 403 SDK не повторяет,
        поэтому отказ доезжает до нашего кода и паре есть что проверять.
        """
        sdk = OTLPLogExporter(endpoint=ENDPOINT)
        answers = [SimpleNamespace(ok=False, status_code=403, reason="Forbidden")]

        def _post(*_a: Any, **_k: Any) -> Any:
            if answers:
                return answers.pop(0)
            return SimpleNamespace(ok=True, status_code=200, reason="OK")

        sdk._session.post = _post  # type: ignore[attr-defined]
        exporter = OtlpHttpExporter(_cfg(), sdk_factory=lambda: sdk)

        broken = exporter.export([_record()])
        assert "403" in broken.reason, f"сценарий не воспроизведён: {broken.reason!r}"

        healed = exporter.export([_record()])
        assert healed.failed == 0, f"починившийся приёмник отчитался отказом: {healed!r}"
        assert healed.reason == "", f"успех несёт причину прошлого отказа: {healed.reason!r}"


class TestProbeFailureIsNotADeliveryFailure:
    """Опасность 3: объект SDK без `_session` (любой дубль, будущий транспорт)."""

    def test_sdk_without_session_still_delivers_and_falls_back_to_the_template(self) -> None:
        """Отказ ДИАГНОЗА не имеет права стать отказом ДОСТАВКИ.

        Так устроен КАЖДЫЙ дубль экспортёра в наборах Task 2.1/2.2: у него нет
        ни `_session`, ни `requests` вовсе. Урони зонд здесь исключением — и
        отправка станет отказом всюду, где её подменяют, а виноватым будет
        выглядеть коллектор.
        """
        sent: list[int] = []

        class _SdkWithoutSession:
            def export(self, batch: Any) -> Any:
                sent.append(len(list(batch)))
                from opentelemetry.sdk._logs.export import LogRecordExportResult

                return LogRecordExportResult.SUCCESS

        exporter = OtlpHttpExporter(_cfg(), sdk_factory=_SdkWithoutSession)
        outcome = exporter.export([_record(), _record()])

        assert sent == [2], f"батч не доехал до объекта SDK: {sent!r}"
        assert outcome.accepted == 2 and outcome.failed == 0, f"успешная отправка прочитана как отказ: {outcome!r}"

    def test_failure_without_a_probe_says_the_generic_template_and_nothing_invented(self) -> None:
        """Пара: у объекта без сессии причина отказа — ЗАПАСНОЙ шаблон, а не выдумка.

        Утверждение положительное (шаблон на месте), а не «в строке нет HTTP»:
        второе прошло бы и на пустой строке, то есть на потерянной причине.
        """

        class _FailingSdkWithoutSession:
            def export(self, _batch: Any) -> Any:
                from opentelemetry.sdk._logs.export import LogRecordExportResult

                return LogRecordExportResult.FAILURE

        exporter = OtlpHttpExporter(_cfg(), sdk_factory=_FailingSdkWithoutSession)
        outcome = exporter.export([_record()])

        assert outcome.failed == 1, f"{outcome!r}"
        assert "приёмник вернул" in outcome.reason, (
            f"запасной шаблон причины потерян — отказ без зонда остался бы без слов: {outcome.reason!r}"
        )
        assert ENDPOINT in outcome.reason, f"причина не называет адрес: {outcome.reason!r}"


class TestProbeDoesNotSwallowTheTransportException:
    """Ретраи SDK живут на исключении: проглоти его зонд — и отказ станет тишиной."""

    def test_exception_reaches_the_sdk_and_the_class_name_reaches_the_reason(self) -> None:
        sdk = OTLPLogExporter(endpoint=ENDPOINT)

        def _post(*_a: Any, **_k: Any) -> Any:
            raise requests.exceptions.ReadTimeout("Read timed out")

        sdk._session.post = _post  # type: ignore[attr-defined]
        exporter = OtlpHttpExporter(_cfg(), sdk_factory=lambda: sdk)

        outcome = exporter.export([_record()])

        # SDK ловит `RequestException` ВНУТРИ себя (строка 212 его `__init__.py`)
        # и возвращает FAILURE. Значит исключение до нас не долетело, а имя
        # класса — долетело: ровно это и доказывает, что зонд его пропустил, а
        # не съел.
        assert outcome.failed == 1, f"{outcome!r}"
        assert "ReadTimeout" in outcome.reason, f"класс исключения не доехал до причины: {outcome.reason!r}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


class TestStaleOutcomeCannotSurviveIntoABatchThatNeverPosted:
    """Опасность 2b: SDK отказал, НЕ сходив в сеть — а зонд помнит прошлый батч.

    **Почему этот тест дописан отдельно, хотя рядом уже есть два про залипание.**
    Матрица инъекций поймала мёртвую зону: заплата «`forget()` ничего не забывает»
    убила **0 тестов из 245** при живой базе. Разбор показал, что оба соседних
    теста зелены по ПРИЧИНЕ, ОТЛИЧНОЙ ОТ ЗАЯВЛЕННОЙ в их докстрингах: отказ
    перевода записи уходит в ветку `except Exception`, где причина строится из
    самого исключения, а показание зонда не читается вовсе. То есть `forget()`
    они не сторожили.

    Настоящая дорога к протечке одна: `sdk.export()` вернул FAILURE, **не сходив
    в сеть**. У настоящего SDK такая ветка есть и она не выдумана — «exporter
    already shutdown, ignoring batch» (`_log_exporter/__init__.py:197`). POST не
    случается, зонд молчит, и без `forget()` в причину уедет HTTP-код прошлого
    батча: диагноз укажет на токен там, где экспортёр просто остановлен.
    """

    def test_failure_without_a_post_does_not_inherit_the_previous_http_code(self) -> None:
        sdk = OTLPLogExporter(endpoint=ENDPOINT)
        posts: list[Any] = []

        def _post(*_a: Any, **_k: Any) -> Any:
            posts.append(1)
            return SimpleNamespace(ok=False, status_code=401, reason="Unauthorized")

        sdk._session.post = _post  # type: ignore[attr-defined]
        exporter = OtlpHttpExporter(_cfg(), sdk_factory=lambda: sdk)

        first = exporter.export([_record()])
        assert "401" in first.reason, f"сценарий не воспроизведён, первый отказ не 401: {first.reason!r}"
        posts_after_first = len(posts)

        # SDK остановлен: его `export` вернёт FAILURE, не дойдя до транспорта.
        sdk._shutdown = True  # type: ignore[attr-defined]
        second = exporter.export([_record()])

        assert len(posts) == posts_after_first, (
            f"POST всё-таки случился — сценарий «отказ без сети» не воспроизведён: {len(posts)}"
        )
        assert second.failed == 1, f"остановленный SDK обязан дать failed == 1: {second!r}"
        assert "401" not in second.reason, (
            f"причина унаследована от прошлого батча, у которого был POST: {second.reason!r}"
        )
