# -*- coding: utf-8 -*-
"""Тесты ОПАСНЫХ МЕСТ механизма отправки (Task 2.2) — писал автор реализации.

Дополнение к приёмочному набору тестера (`test_f2_task22_acceptance.py`), а не
замена: тот проверяет критерии приёмки, этот — то, что видно только изнутри
механизма, «что здесь может сломаться, учитывая, как оно устроено».

**Восемь мест, ради которых файл существует.**

1. *Строгий перевод.* Отсутствующий `Resource`, `trace_id` не тех 32 hex,
   `severity_number` вне словаря OTel — каждое из трёх имеет тихую правдоподобную
   трактовку (пустой ресурс, маленькое число, «как есть»). Проверяется, что все
   три громкие и посчитанные.
2. *Отказ SDK в КОНСТРУКТОРЕ, а не в `export()`.* Ленивое построение переносит
   отказ «нет extra [otel]» в момент первой отправки, и он обязан стать `failed` с
   причиной, а не исключением в потоке команды.
3. *Объект SDK строится один раз.* `OTLPLogExporter` держит `requests.Session`;
   построение на каждый батч — новое TCP-соединение на каждую пачку.
4. *Неизвестный исход = отказ.* `None` вместо `LogRecordExportResult` обязан
   читаться как «не доставлено»: иначе потери станут невидимыми.
5. *Перевод обязан пережить НАСТОЯЩИЙ кодировщик OTLP.* Утверждения о форме
   объекта SDK ничего не говорят о проводе; здесь батч прогоняется через
   `encode_logs` — тот самый код, который вызывает настоящий экспортёр. Сети при
   этом нет: кодировщик чистый.
6. *Чужая трасса на нашей записи.* Конструктор `LogRecord` при пустом `trace_id`
   подставляет трассу ТЕКУЩЕГО спана процесса.
7. *Долетевшая СТРОКА, а не факт вызова* (Р-25). `log_windowed` возвращает `True`
   («голос прозвучал») даже когда `emit_voice` не нашёл у приёмника метода уровня
   и потерял строку. Сторожить обязан журнал, а не возврат функции.
8. *Дожатие: пустое кольцо, состояние `error`, повтор подряд, останов.*

**Сеть не трогается нигде.** Настоящий `OTLPLogExporter` не строится ни разу:
на уровне сервиса шов — `sdk_factory`, на уровне плагина — подмена
`OtlpHttpExporter` в namespace `plugin.py`. Дубли УМЕЮТ отказывать: дубль,
успешный всегда, делает тест отказа зелёным по построению.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from multiprocess_framework.modules.logger_module.core import windowed_voice
from Services.otel_export.config import OtelExportConfig
from Services.otel_export.exporter import OtlpHttpExporter
from Services.otel_export.interfaces import ExportOutcome, MappedRecord, Resource

ENDPOINT = "http://127.0.0.1:4318"

#: 32 hex — валидный по форме W3C trace_id.
VALID_TRACE_ID = "0123456789abcdef0123456789abcdef"

#: Он же байтами — как он обязан выглядеть на проводе. Литерал считается ОДИН
#: раз и здесь, а не тем же выражением, которым его получает предмет проверки.
VALID_TRACE_ID_BYTES = bytes.fromhex(VALID_TRACE_ID)

#: Трасса «активного спана» для проверки места 6. Отличается от VALID_TRACE_ID:
#: совпадение сделало бы утверждение слепым к самой ошибке, которую оно ловит.
AMBIENT_TRACE_ID = 0xDEADBEEFDEADBEEFDEADBEEFDEADBEEF


@pytest.fixture(autouse=True)
def _fresh_voice_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    """Свежий держатель окон голоса на КАЖДЫЙ тест файла.

    Держатель процессный, а окно берётся из политики: первый тест, задевший ключ
    `otel_export.export_failed`, сделал бы соседа немым, и утверждение «строка
    долетела» покраснело бы в наборе, будучи зелёным в одиночку.
    """
    monkeypatch.setattr(windowed_voice, "_PROCESS_VOICES", windowed_voice.WindowedVoices())


# --------------------------------------------------------------------------- #
# Харнесс уровня сервиса
# --------------------------------------------------------------------------- #


def _cfg(**overrides: Any) -> OtelExportConfig:
    data: dict[str, Any] = {"endpoint": ENDPOINT}
    data.update(overrides)
    return OtelExportConfig(**data)


def _mapped(**overrides: Any) -> MappedRecord:
    base: dict[str, Any] = dict(
        timestamp_ns=1_700_000_000_000_000_000,
        observed_timestamp_ns=1_700_000_000_100_000_000,
        severity_text="ERROR",
        severity_number=17,
        body="boom",
        scope_name="camera_1.worker",
        attributes={"k": "v"},
        trace_id=VALID_TRACE_ID,
        resource=Resource(
            attributes={"service.name": "inspector", "process.pid": 4242},
            schema_url="https://opentelemetry.io/schemas/1.43.0",
        ),
    )
    base.update(overrides)
    return MappedRecord(**base)


class _SdkDouble:
    """Дубль объекта SDK. УМЕЕТ отказывать и умеет вернуть чужой исход."""

    def __init__(self, result: Any = "SUCCESS") -> None:
        self._result = result
        self.batches: list[list[Any]] = []

    def export(self, batch: Any) -> Any:
        self.batches.append(list(batch))
        if self._result == "SUCCESS":
            from opentelemetry.sdk._logs._internal.export import LogRecordExportResult

            return LogRecordExportResult.SUCCESS
        return self._result


# --------------------------------------------------------------------------- #
# 1. Строгий перевод: три тихие трактовки становятся громким отказом
# --------------------------------------------------------------------------- #


class TestStrictTranslationFailsLoudly:
    def test_record_without_resource_fails_the_batch_and_names_the_field(self) -> None:
        sdk = _SdkDouble()
        exporter = OtlpHttpExporter(_cfg(), sdk_factory=lambda: sdk)

        outcome = exporter.export([_mapped(resource=None)])

        assert outcome.accepted == 0, f"{outcome!r}"
        assert outcome.failed == 1, f"{outcome!r}"
        assert "Resource" in outcome.reason, f"причина не называет поле: {outcome.reason!r}"
        assert sdk.batches == [], f"батч с битой записью не имеет права уехать в SDK: {sdk.batches!r}"

    def test_trace_id_of_wrong_length_fails_instead_of_becoming_a_small_number(self) -> None:
        """`int("abcdef12", 16)` успешен и даёт 2882400018 — чужой идентификатор."""
        sdk = _SdkDouble()
        exporter = OtlpHttpExporter(_cfg(), sdk_factory=lambda: sdk)

        outcome = exporter.export([_mapped(trace_id="abcdef12")])

        assert outcome.failed == 1, f"короткий trace_id принят молча: {outcome!r}"
        assert "trace_id" in outcome.reason, f"причина не называет поле: {outcome.reason!r}"
        assert "32" in outcome.reason, f"причина не называет требуемую длину: {outcome.reason!r}"

    def test_non_hex_trace_id_fails_with_our_wording_not_the_stdlib_one(self) -> None:
        sdk = _SdkDouble()
        exporter = OtlpHttpExporter(_cfg(), sdk_factory=lambda: sdk)

        outcome = exporter.export([_mapped(trace_id="z" * 32)])

        assert outcome.failed == 1, f"{outcome!r}"
        assert "trace_id" in outcome.reason, f"{outcome.reason!r}"

    def test_severity_number_outside_the_otel_dictionary_fails(self) -> None:
        sdk = _SdkDouble()
        exporter = OtlpHttpExporter(_cfg(), sdk_factory=lambda: sdk)

        outcome = exporter.export([_mapped(severity_number=99)])

        assert outcome.failed == 1, f"важность вне словаря OTel принята молча: {outcome!r}"
        assert "severity_number" in outcome.reason, f"{outcome.reason!r}"

    def test_endpoint_is_named_in_every_failure_reason(self) -> None:
        """Причина без адреса бесполезна там, где приёмников на стенде два."""
        cfg = _cfg(endpoint="http://collector.example.internal:4318")
        sdk = _SdkDouble()
        exporter = OtlpHttpExporter(cfg, sdk_factory=lambda: sdk)

        outcome = exporter.export([_mapped(resource=None)])

        assert "collector.example.internal" in outcome.reason, f"{outcome.reason!r}"


# --------------------------------------------------------------------------- #
# 2-4. Построение SDK и чтение исхода
# --------------------------------------------------------------------------- #


class TestSdkConstructionAndResultReading:
    def test_factory_raising_in_the_constructor_is_a_failed_outcome_not_an_exception(self) -> None:
        """Отказ ленивого построения приходит не в `export()`, а ДО него."""

        def _broken_factory() -> Any:
            raise ImportError("нет extra [otel]")

        exporter = OtlpHttpExporter(_cfg(), sdk_factory=_broken_factory)

        outcome = exporter.export([_mapped(), _mapped(body="second")])

        assert outcome.accepted == 0, f"{outcome!r}"
        assert outcome.failed == 2, f"отказ построения обязан считаться по всем записям: {outcome!r}"
        assert "ImportError" in outcome.reason, f"причина не называет род отказа: {outcome.reason!r}"

    def test_sdk_object_is_built_once_and_reused_across_exports(self) -> None:
        """`requests.Session` внутри — построение на батч = соединение на батч."""
        built: list[_SdkDouble] = []

        def _counting_factory() -> _SdkDouble:
            sdk = _SdkDouble()
            built.append(sdk)
            return sdk

        exporter = OtlpHttpExporter(_cfg(), sdk_factory=_counting_factory)
        exporter.export([_mapped()])
        exporter.export([_mapped(body="second")])

        assert len(built) == 1, f"объект SDK построен более одного раза: {len(built)}"
        assert len(built[0].batches) == 2, f"второй батч уехал не в тот объект: {built[0].batches!r}"

    def test_empty_batch_builds_no_sdk_object_at_all(self) -> None:
        """Пустое кольцо не имеет права открывать сокет — дорога бесплатная."""
        built: list[Any] = []

        def _counting_factory() -> _SdkDouble:
            built.append(object())
            return _SdkDouble()

        exporter = OtlpHttpExporter(_cfg(), sdk_factory=_counting_factory)

        outcome = exporter.export([])

        assert (outcome.accepted, outcome.failed) == (0, 0), f"{outcome!r}"
        assert built == [], "на пустом батче построен объект SDK"

    def test_unknown_result_object_is_read_as_failure_not_as_success(self) -> None:
        """`None` вместо enum — неизвестный исход, и он обязан читаться как потеря."""
        sdk = _SdkDouble(result=None)
        exporter = OtlpHttpExporter(_cfg(), sdk_factory=lambda: sdk)

        outcome = exporter.export([_mapped()])

        assert outcome.failed == 1, f"неизвестный исход принят за успех: {outcome!r}"
        assert outcome.reason, f"{outcome!r}"

    def test_success_enum_is_zero_and_must_not_be_read_as_falsy(self) -> None:
        """`LogRecordExportResult.SUCCESS` == 0: `if result:` прочитал бы всё наоборот."""
        from opentelemetry.sdk._logs._internal.export import LogRecordExportResult

        assert LogRecordExportResult.SUCCESS.value == 0, "предпосылка теста устарела — сверить SDK"
        sdk = _SdkDouble(result=LogRecordExportResult.SUCCESS)
        exporter = OtlpHttpExporter(_cfg(), sdk_factory=lambda: sdk)

        outcome = exporter.export([_mapped()])

        assert outcome.accepted == 1, f"успех со значением 0 прочитан как отказ: {outcome!r}"
        assert outcome.reason == "", f"{outcome!r}"


# --------------------------------------------------------------------------- #
# 5-6. Проверка на НАСТОЯЩЕМ кодировщике OTLP (сети нет: кодировщик чистый)
# --------------------------------------------------------------------------- #


def _encode(records: list[MappedRecord]) -> Any:
    """Прогнать записи через перевод экспортёра и НАСТОЯЩИЙ кодировщик OTLP."""
    from opentelemetry.exporter.otlp.proto.common._internal._log_encoder import encode_logs

    sdk = _SdkDouble()
    exporter = OtlpHttpExporter(_cfg(), sdk_factory=lambda: sdk)
    outcome = exporter.export(records)
    assert outcome.failed == 0, f"перевод отказал до кодировщика: {outcome!r}"
    return encode_logs(sdk.batches[0])


class TestTranslationSurvivesTheRealEncoder:
    def test_full_record_encodes_without_raising(self) -> None:
        """Утверждение о форме объекта SDK ничего не говорит о проводе."""
        encoded = _encode([_mapped()])

        log_records = encoded.resource_logs[0].scope_logs[0].log_records
        assert len(log_records) == 1, f"{encoded!r}"
        assert log_records[0].severity_text == "ERROR"
        assert log_records[0].trace_id == VALID_TRACE_ID_BYTES, (
            f"trace_id на проводе искажён: {log_records[0].trace_id!r}"
        )

    def test_record_without_trace_id_puts_no_trace_id_on_the_wire(self) -> None:
        """Дух Р-20 проверяется НА ПРОВОДЕ: поля нет, а не забивка из нулей.

        `None` в модели SDK этого не даёт вовсе — кодировщик падает
        `AttributeError: 'NoneType' object has no attribute 'to_bytes'`; ноль
        (`INVALID_TRACE_ID`) даёт ровно отсутствие поля. Сверено запуском на 1.44.0.
        """
        encoded = _encode([_mapped(trace_id=None)])

        log_records = encoded.resource_logs[0].scope_logs[0].log_records
        assert log_records[0].trace_id == b"", (
            f"на проводе оказался идентификатор трассы, которого у записи нет: {log_records[0].trace_id!r}"
        )

    def test_resource_schema_url_and_attributes_reach_the_wire(self) -> None:
        encoded = _encode([_mapped()])

        resource_logs = encoded.resource_logs[0]
        assert resource_logs.schema_url == "https://opentelemetry.io/schemas/1.43.0", (
            f"схема semconv потеряна при мерже (ловушка Р-24): {resource_logs.schema_url!r}"
        )
        names = {attr.key for attr in resource_logs.resource.attributes}
        assert "service.name" in names, f"{names!r}"
        assert "process.pid" in names, f"{names!r}"

    def test_ambient_span_does_not_stamp_its_trace_on_a_record_without_one(self) -> None:
        """Конструктор SDK берёт трассу ТЕКУЩЕГО спана, если наша пуста.

        Приклеенная чужая трасса — не шум: приёмник склеит по ней несвязанные
        записи, и распутать это на его стороне уже нечем.
        """
        from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags, use_span

        span_context = SpanContext(
            trace_id=AMBIENT_TRACE_ID,
            span_id=0x1122334455667788,
            is_remote=False,
            trace_flags=TraceFlags(TraceFlags.SAMPLED),
        )
        sdk = _SdkDouble()
        exporter = OtlpHttpExporter(_cfg(), sdk_factory=lambda: sdk)

        with use_span(NonRecordingSpan(span_context), end_on_exit=False):
            exporter.export([_mapped(trace_id=None)])

        stamped = sdk.batches[0][0].log_record.trace_id
        assert stamped != AMBIENT_TRACE_ID, "на запись без трассы приклеена трасса активного спана процесса"
        assert stamped == 0, f"отсутствие трассы обязано быть INVALID_TRACE_ID: {stamped!r}"


# --------------------------------------------------------------------------- #
# Харнесс уровня плагина
# --------------------------------------------------------------------------- #


class _CommandManagerDouble:
    def __init__(self) -> None:
        self.registered: dict[str, Any] = {}

    def register_command(self, name: str, method: Any) -> None:
        self.registered[name] = method

    def get_command_info(self, name: str) -> Any:
        return self.registered.get(name)


class _RouterDouble:
    def __init__(self) -> None:
        self.handlers: dict[str, Any] = {}
        self.requests: list[dict] = []

    def register_message_handler(self, key: str, handler: Any, *a: Any, **k: Any) -> bool:
        self.handlers[key] = handler
        return True

    def request_async(self, message: dict, on_response: Any, timeout: float = 5.0, correlation_id: Any = None) -> str:
        self.requests.append(message)
        on_response({"success": True, "result": {"success": True}})
        return correlation_id or "cid"


def _make_ctx(config: dict | None = None) -> tuple[Any, dict[str, list[str]], _CommandManagerDouble, _RouterDouble]:
    """Контекст на РЕАЛЬНОМ `PluginContext`; дубли — только границы процесса."""
    from multiprocess_framework.modules.process_module.plugins import PluginContext

    voices: dict[str, list[str]] = {"debug": [], "info": [], "warning": [], "error": [], "critical": []}

    def _log(level: str) -> Any:
        def _fn(message: str, **_fields: Any) -> None:
            voices[level].append(str(message))

        return _fn

    command_manager = _CommandManagerDouble()
    router = _RouterDouble()
    services = SimpleNamespace(
        name="proc_hazard",
        worker_manager=None,
        command_manager=command_manager,
        router_manager=router,
        memory_manager=None,
        state_proxy=None,
        log_debug=_log("debug"),
        log_info=_log("info"),
        log_warning=_log("warning"),
        log_error=_log("error"),
        log_critical=_log("critical"),
        send_message=lambda *a, **k: True,
        receive_message=lambda *a, **k: None,
    )
    ctx = PluginContext(
        services=services,
        config=config if config is not None else {"endpoint": ENDPOINT},
        io=None,
        registers=None,
        plugin_name="otel_export",
    )
    return ctx, voices, command_manager, router


class _PluginExporterDouble:
    """Дубль экспортёра для плагина. УМЕЕТ отказывать: число отказов задаётся.

    Исход считается ОТ БАТЧА (`accepted = len(batch) - failed`), а не берётся
    постоянным: постоянный исход дал бы «2 отправлено» на пустом батче и сделал
    бы проверку повторного дожатия бессмысленной. Инвариант
    `accepted + failed == len(batch)` дубль соблюдает — иначе он проверял бы
    механизм, которого нет.
    """

    constructions: list[Any] = []
    batches: list[list[Any]] = []
    failed: int = 0
    reason: str = ""

    def __init__(self, *_a: Any, **_k: Any) -> None:
        type(self).constructions.append(self)

    def export(self, records: Any) -> ExportOutcome:
        batch = list(records)
        type(self).batches.append(batch)
        failed_now = min(type(self).failed, len(batch))
        return ExportOutcome(
            accepted=len(batch) - failed_now,
            failed=failed_now,
            reason=type(self).reason if failed_now else "",
        )


def _install_plugin_exporter(
    monkeypatch: pytest.MonkeyPatch,
    *,
    failed: int = 0,
    reason: str = "",
) -> type[_PluginExporterDouble]:
    """Подменить `OtlpHttpExporter` в namespace `plugin.py` управляемым дублем."""
    import Plugins.io.otel_export.plugin as plugin_module

    double = type(
        "_ExporterDouble",
        (_PluginExporterDouble,),
        {"constructions": [], "batches": [], "failed": failed, "reason": reason},
    )
    monkeypatch.setattr(plugin_module, "OtlpHttpExporter", double)
    return double


def _log_envelope(count: int) -> dict:
    records = [
        {"kind": "log", "severity": "ERROR", "severity_number": 17, "message": f"m{i}", "module": "x", "ts": 1.0 + i}
        for i in range(count)
    ]
    return {"command": "observability.record", "data": {"records": records}}


def _boot(
    monkeypatch: pytest.MonkeyPatch,
    *,
    failed: int = 0,
    reason: str = "",
    config: dict | None = None,
) -> tuple[Any, ...]:
    from Plugins.io.otel_export.plugin import OtelExportPlugin

    double = _install_plugin_exporter(monkeypatch, failed=failed, reason=reason)
    ctx, voices, command_manager, router = _make_ctx(config)
    plugin = OtelExportPlugin()
    plugin._do_configure(ctx)
    plugin._do_start(ctx)
    return plugin, ctx, voices, command_manager, router, double


# --------------------------------------------------------------------------- #
# 7. Долетевшая СТРОКА, а не факт вызова (Р-25)
# --------------------------------------------------------------------------- #


class TestFailureVoiceReachesTheJournal:
    def test_export_failure_puts_a_real_line_into_ctx_log_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Сторожит ЖУРНАЛ, а не форму вызова `log_windowed`.

        Замер, ради которого тест написан: у переходника `_voice` не было метода
        `error`, `emit_voice` не нашёл его, запасной `getattr(target, "log")` у
        `SimpleNamespace` тоже отсутствует — и строка терялась, а `log_windowed`
        при этом возвращал `True`. Тест на форму вызова оставался бы зелёным.
        """
        plugin, ctx, voices, command_manager, _router, _double = _boot(
            monkeypatch, failed=3, reason="collector unreachable"
        )
        ctx.router_manager.handlers["observability.record"](_log_envelope(3))

        command_manager.registered["otel_export.flush"]({})

        assert voices["error"], (
            "отказ доставки не долетел до журнала процесса: log_windowed вернул True, а строки нет "
            f"(проверь `error` в `_voice`). Журнал: {voices!r}"
        )
        line = voices["error"][-1]
        assert ENDPOINT in line, f"строка отказа не называет endpoint: {line!r}"
        assert "3" in line, f"строка отказа не называет число потерянных записей: {line!r}"

    def test_success_leaves_the_error_journal_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Пара к отказу: на успехе строки нет вовсе, иначе сторож слеп."""
        plugin, ctx, voices, command_manager, _router, _double = _boot(monkeypatch)
        ctx.router_manager.handlers["observability.record"](_log_envelope(2))

        command_manager.registered["otel_export.flush"]({})

        assert voices["error"] == [], f"на успешной отправке в журнал ушла строка отказа: {voices['error']!r}"

    def test_one_line_per_flush_not_per_record(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Недоступный коллектор не имеет права превратить 5 записей в 5 строк."""
        plugin, ctx, voices, command_manager, _router, _double = _boot(
            monkeypatch, failed=5, reason="collector unreachable"
        )
        ctx.router_manager.handlers["observability.record"](_log_envelope(5))

        command_manager.registered["otel_export.flush"]({})

        assert len(voices["error"]) == 1, f"на пачку из 5 отказавших записей строк больше одной: {voices['error']!r}"


# --------------------------------------------------------------------------- #
# 8. Дожатие: часть батча, пустое кольцо, состояние error, повтор, останов
# --------------------------------------------------------------------------- #


class TestFlushHazards:
    def test_partial_outcome_grows_both_counters(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Часть доехала, часть нет — растут ОБА счётчика, а не один из них."""
        plugin, ctx, _voices, command_manager, _router, _double = _boot(monkeypatch, failed=1, reason="partial")
        ctx.router_manager.handlers["observability.record"](_log_envelope(2))

        result = command_manager.registered["otel_export.flush"]({})

        counters = command_manager.registered["otel_export.status"]({})["counters"]
        assert counters["exported"] == 1, f"{counters!r}"
        assert counters["export_failed"] == 1, f"{counters!r}"
        assert result["status"] == "failed", f"частичная потеря не имеет права читаться как ok: {result!r}"

    def test_flush_on_empty_ring_does_not_call_the_exporter(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Дожатие пустого кольца — бесплатная дорога: ни отправки, ни голоса."""
        plugin, ctx, voices, command_manager, _router, double = _boot(monkeypatch)

        result = command_manager.registered["otel_export.flush"]({})

        assert double.batches == [[]], f"экспортёр позван не с пустым батчем: {double.batches!r}"
        assert result["status"] == "ok", f"{result!r}"
        assert result["flushed"] == 0 and result["failed"] == 0, f"{result!r}"
        assert voices["error"] == [], f"пустое кольцо породило строку отказа: {voices['error']!r}"

    def test_flush_in_error_state_never_builds_an_exporter(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Плагин в `error` отправлять нечем и НЕ ЧЕРЕЗ ЧТО — экспортёра там нет."""
        from Plugins.io.otel_export.plugin import OtelExportPlugin

        double = _install_plugin_exporter(monkeypatch)
        ctx, _voices, command_manager, _router = _make_ctx(config={"endpoint": ""})
        plugin = OtelExportPlugin()
        plugin._do_configure(ctx)

        result = plugin._cmd_flush({})

        assert result["status"] == "error", f"{result!r}"
        assert "endpoint" in result["reason"], f"{result!r}"
        assert double.constructions == [], "в состоянии error построен экспортёр"
        assert double.batches == [], f"в состоянии error что-то отправлено: {double.batches!r}"

    def test_second_flush_in_a_row_sends_nothing_and_does_not_double_count(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Кольцо забирается ОБМЕНОМ: второй подряд флаш не имеет права посчитать то же ещё раз."""
        plugin, ctx, _voices, command_manager, _router, double = _boot(monkeypatch)
        ctx.router_manager.handlers["observability.record"](_log_envelope(2))

        first = command_manager.registered["otel_export.flush"]({})
        second = command_manager.registered["otel_export.flush"]({})

        assert [len(batch) for batch in double.batches] == [2, 0], (
            f"второй флаш увёз те же записи повторно: {[len(b) for b in double.batches]!r}"
        )
        assert first["flushed"] == 2, f"{first!r}"
        assert second["flushed"] == 0, f"второй флаш отчитался об отправке пустоты: {second!r}"
        counters = command_manager.registered["otel_export.status"]({})["counters"]
        assert counters["exported"] == 2, f"счётчик посчитал те же записи дважды: {counters!r}"

    def test_shutdown_flushes_the_ring(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Р-21: останов дожимает накопленное, а не роняет его вместе с процессом."""
        plugin, ctx, _voices, command_manager, _router, double = _boot(monkeypatch)
        ctx.router_manager.handlers["observability.record"](_log_envelope(3))

        plugin._do_shutdown(ctx)

        assert [len(batch) for batch in double.batches] == [3], (
            f"останов не дожал кольцо (или дожал не тем батчем): {[len(b) for b in double.batches]!r}"
        )
        counters = command_manager.registered["otel_export.status"]({})["counters"]
        assert counters["exported"] == 3, f"{counters!r}"

    def test_shutdown_with_empty_ring_does_not_call_the_exporter(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Пара: пустое кольцо на останове не имеет права открывать сокет."""
        plugin, ctx, _voices, _command_manager, _router, double = _boot(monkeypatch)

        plugin._do_shutdown(ctx)

        assert double.batches == [], f"на пустом кольце останов позвал отправку: {double.batches!r}"
