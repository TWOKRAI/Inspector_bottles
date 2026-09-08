# -*- coding: utf-8 -*-
"""Приёмочные тесты Task 2.2 («отказ доставки СЛЫШЕН») — независимый тестер, ДО реализации.

Источник критериев — бриф тестеру Task 2.2 трека ``otel-export`` (решения Р-17…Р-24 +
критерии приёмки 1-8). ``Services/otel_export/exporter.py`` на момент написания несёт
только ``sdk_available()`` — класса ``OtlpHttpExporter`` в файле НЕТ. ``Plugins/io/otel_export/plugin.py``
существует (Task 2.1), но не импортирует ``OtlpHttpExporter`` и не зовёт ``log_windowed``
на ключ ``otel_export.export_failed`` — красное состояние ожидаемо и НЕ чинится заглушкой.

Импорт предмета (``OtlpHttpExporter``) — ВНУТРИ каждого теста, не на уровне модуля, ради
``pytest --collect-only``. Импорт уже реализованных ``interfaces``/``config`` — на уровне
модуля (тот же приём, что в ``test_f1_hazards.py``/``test_mapping_acceptance.py``).

**Один угаданный крючок для критериев 5-7** (плагин-уровень): тест полагается на то, что
``Plugins/io/otel_export/plugin.py`` импортирует класс ``OtlpHttpExporter`` ПО ИМЕНИ в свой
модульный namespace — тем же приёмом, каким уже импортирован ``sdk_available``
(``from Services.otel_export.exporter import sdk_available``, plugin.py:76). Патч ставится
на ``Plugins.io.otel_export.plugin.OtlpHttpExporter`` ДО конструирования плагина — это
покрывает и раннее построение экспортёра (в ``configure()``), и ленивое (внутри
``_cmd_flush``). Если реализация вызовет класс через квалифицированное имя
(``exporter_module.OtlpHttpExporter(...)``), патч не сработает — см. пункт 3 отчёта.

Сеть НЕ трогается нигде: настоящий ``OTLPLogExporter`` в тестах не строится, коллектор не
поднимается. Граница SDK — ``sdk_factory`` (Services-уровень) и подмена
``OtlpHttpExporter`` целиком (Plugins-уровень).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from Services.otel_export.config import OtelExportConfig
from Services.otel_export.interfaces import ExportOutcome, MappedRecord, Resource

REPO_ROOT = Path(__file__).resolve().parents[3]

#: 32 hex символа — валидный по форме W3C trace_id (не забивка из нулей).
VALID_TRACE_ID = "0123456789abcdef0123456789abcdef"


# ---------------------------------------------------------------------------
# Общие фабрики (используют уже реализованные Ф1-типы — не предмет проверки)
# ---------------------------------------------------------------------------


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


class _FakeSdkExporter:
    """Дубль объекта, который вернёт ``sdk_factory``. УМЕЕТ отказывать (не константа).

    ``results`` — очередь исходов ``LogRecordExportResult`` на последовательные вызовы
    ``export()``; когда очередь пуста — SUCCESS. ``raise_exc`` — если задан, КАЖДЫЙ вызов
    бросает это исключение (сценарий «SDK упал», критерий 2).
    """

    def __init__(self, results: list | None = None, raise_exc: BaseException | None = None) -> None:
        self._results = list(results) if results is not None else []
        self._raise_exc = raise_exc
        self.calls: list[list[Any]] = []

    def export(self, batch: Any) -> Any:
        self.calls.append(list(batch))
        if self._raise_exc is not None:
            raise self._raise_exc
        if self._results:
            return self._results.pop(0)
        from opentelemetry.sdk._logs._internal.export import LogRecordExportResult

        return LogRecordExportResult.SUCCESS


# ---------------------------------------------------------------------------
# Критерий 1: успех/отказ по возвращённому значению SDK
# ---------------------------------------------------------------------------


class TestExportOutcomeFromReturnedResult:
    def test_success_batch_gives_accepted_equal_len_and_zero_failed(self) -> None:
        from Services.otel_export.exporter import OtlpHttpExporter

        fake = _FakeSdkExporter()
        exp = OtlpHttpExporter(_cfg(), sdk_factory=lambda: fake)
        records = [_mapped_record(), _mapped_record(body="second")]

        outcome = exp.export(records)

        assert outcome.accepted == 2, f"успех обязан дать accepted == len(batch): {outcome!r}"
        assert outcome.failed == 0, f"успех обязан дать failed == 0: {outcome!r}"
        assert outcome.reason == "", f"reason обязан быть пуст при failed == 0: {outcome!r}"

    def test_failure_batch_gives_zero_accepted_and_reason_names_endpoint(self) -> None:
        from Services.otel_export.exporter import OtlpHttpExporter
        from opentelemetry.sdk._logs._internal.export import LogRecordExportResult

        cfg = _cfg(endpoint="http://collector.example.internal:4318/v1/logs")
        fake = _FakeSdkExporter(results=[LogRecordExportResult.FAILURE])
        exp = OtlpHttpExporter(cfg, sdk_factory=lambda: fake)
        records = [_mapped_record()]

        outcome = exp.export(records)

        assert outcome.accepted == 0, f"отказ обязан дать accepted == 0: {outcome!r}"
        assert outcome.failed == 1, f"отказ обязан дать failed == len(batch): {outcome!r}"
        assert outcome.reason, f"reason обязан быть непустым при failed > 0: {outcome!r}"
        assert "collector.example.internal" in outcome.reason, (
            f"reason обязан называть endpoint {cfg.endpoint!r}: {outcome.reason!r}"
        )


# ---------------------------------------------------------------------------
# Критерий 2: исключение SDK ловится, наружу не выходит
# ---------------------------------------------------------------------------


class TestExceptionDoesNotEscape:
    def test_sdk_exception_is_caught_and_becomes_failed_with_reason(self) -> None:
        from Services.otel_export.exporter import OtlpHttpExporter

        fake = _FakeSdkExporter(raise_exc=ConnectionRefusedError("connection refused"))
        exp = OtlpHttpExporter(_cfg(), sdk_factory=lambda: fake)
        records = [_mapped_record(), _mapped_record(body="second")]

        outcome = exp.export(records)  # НЕ обязано бросить наружу

        assert outcome.accepted == 0, f"исключение обязано дать accepted == 0: {outcome!r}"
        assert outcome.failed == 2, f"исключение обязано дать failed == len(batch): {outcome!r}"
        assert outcome.reason, f"reason обязан быть непустым при исключении SDK: {outcome!r}"


# ---------------------------------------------------------------------------
# Критерий 3: accepted + failed == len(records) на всех дорогах; пустой батч не зовёт SDK
# ---------------------------------------------------------------------------


class TestAcceptedPlusFailedInvariant:
    def test_invariant_holds_on_success(self) -> None:
        from Services.otel_export.exporter import OtlpHttpExporter

        fake = _FakeSdkExporter()
        exp = OtlpHttpExporter(_cfg(), sdk_factory=lambda: fake)
        records = [_mapped_record(), _mapped_record(), _mapped_record()]

        outcome = exp.export(records)

        assert outcome.accepted + outcome.failed == len(records), f"инвариант нарушен: {outcome!r}"

    def test_invariant_holds_on_failure(self) -> None:
        from Services.otel_export.exporter import OtlpHttpExporter
        from opentelemetry.sdk._logs._internal.export import LogRecordExportResult

        fake = _FakeSdkExporter(results=[LogRecordExportResult.FAILURE])
        exp = OtlpHttpExporter(_cfg(), sdk_factory=lambda: fake)
        records = [_mapped_record(), _mapped_record(), _mapped_record()]

        outcome = exp.export(records)

        assert outcome.accepted + outcome.failed == len(records), f"инвариант нарушен: {outcome!r}"

    def test_invariant_holds_on_exception(self) -> None:
        from Services.otel_export.exporter import OtlpHttpExporter

        fake = _FakeSdkExporter(raise_exc=RuntimeError("boom"))
        exp = OtlpHttpExporter(_cfg(), sdk_factory=lambda: fake)
        records = [_mapped_record(), _mapped_record(), _mapped_record()]

        outcome = exp.export(records)

        assert outcome.accepted + outcome.failed == len(records), f"инвариант нарушен: {outcome!r}"

    def test_empty_batch_gives_zero_zero_and_sdk_not_called_at_all(self) -> None:
        from Services.otel_export.exporter import OtlpHttpExporter

        fake = _FakeSdkExporter()
        exp = OtlpHttpExporter(_cfg(), sdk_factory=lambda: fake)

        outcome = exp.export([])

        assert outcome.accepted == 0
        assert outcome.failed == 0
        assert fake.calls == [], f"SDK.export() позван на пустом батче, а не должен быть: {fake.calls!r}"


# ---------------------------------------------------------------------------
# Критерий 4: перевод полей MappedRecord -> ReadableLogRecord
# ---------------------------------------------------------------------------


class TestFieldTranslation:
    def _export_one(self, record: MappedRecord) -> Any:
        from Services.otel_export.exporter import OtlpHttpExporter

        fake = _FakeSdkExporter()
        exp = OtlpHttpExporter(_cfg(), sdk_factory=lambda: fake)
        exp.export([record])
        assert len(fake.calls) == 1, f"SDK.export() обязан быть позван ровно раз: {fake.calls!r}"
        assert len(fake.calls[0]) == 1
        return fake.calls[0][0]

    def test_trace_id_hex_string_becomes_int(self) -> None:
        readable = self._export_one(_mapped_record(trace_id=VALID_TRACE_ID))
        assert readable.log_record.trace_id == int(VALID_TRACE_ID, 16), (
            f"trace_id не переведён в int по основанию 16: {readable.log_record.trace_id!r}"
        )

    def test_missing_trace_id_does_not_reach_the_wire(self) -> None:
        """Отсутствующий `trace_id` не доезжает до приёмника — 0 байт в кодировщике.

        **Переписан ведущим (Р-26): неверной была спека, а не код.** Исходный
        критерий требовал `log_record.trace_id is None`, но модель SDK 1.44.0
        отсутствия через `None` не выражает — конструктор нормализует его в ноль:

            LogRecord(body='x', trace_id=None) -> 0
            LogRecord(body='x')                -> 0

        Ноль здесь И ЕСТЬ «поля нет», и проверять это надо там, где гарантия
        наблюдаема, — на проводе. Замер настоящим `encode_logs`:
        нулевой `trace_id` даёт **0 байт**, настоящий — **16**.

        Так сторож заодно перестаёт зависеть от того, каким внутренним значением
        отсутствие выражено сегодня: подставь кто-нибудь выдуманный `"0"*32`
        (валидный по длине, невалидный по W3C — ровно тот дефект, на который
        есть инъекция в Ф1), и на проводе появятся 16 байт, по которым приёмник
        склеит несвязанные записи.
        """
        from opentelemetry.exporter.otlp.proto.common._internal._log_encoder import encode_logs

        missing = self._export_one(_mapped_record(trace_id=None))
        present = self._export_one(_mapped_record(trace_id=VALID_TRACE_ID))

        def _wire_len(readable: Any) -> int:
            pb = encode_logs([readable])
            return len(pb.resource_logs[0].scope_logs[0].log_records[0].trace_id)

        assert _wire_len(missing) == 0, (
            "отсутствующий trace_id уехал на провод — приёмник получит идентификатор, "
            f"которого у записи не было: {_wire_len(missing)} байт"
        )
        # Пара: без неё сторож зелен и на экспортёре, который не кладёт trace_id
        # НИКОГДА — то есть проверял бы отсутствие дороги, а не отсутствие поля.
        assert _wire_len(present) == 16, (
            f"настоящий trace_id обязан дать 16 байт на проводе, получено {_wire_len(present)}"
        )

    def test_severity_number_becomes_severitynumber_enum(self) -> None:
        from opentelemetry._logs import SeverityNumber

        readable = self._export_one(_mapped_record(severity_number=17))
        assert readable.log_record.severity_number == SeverityNumber(17), (
            f"severity_number не переведён в SeverityNumber(17): {readable.log_record.severity_number!r}"
        )

    def test_scope_name_becomes_instrumentation_scope_name(self) -> None:
        readable = self._export_one(_mapped_record(scope_name="camera_9.worker"))
        assert readable.instrumentation_scope is not None, "instrumentation_scope не построен вовсе"
        assert readable.instrumentation_scope.name == "camera_9.worker", (
            f"scope_name не переведён в InstrumentationScope.name: {readable.instrumentation_scope.name!r}"
        )

    def test_attributes_arrive_on_the_sdk_record(self) -> None:
        readable = self._export_one(_mapped_record(attributes={"foo": "bar", "n": 3}))
        assert readable.log_record.attributes.get("foo") == "bar", (
            f"атрибут foo не доехал: {readable.log_record.attributes!r}"
        )
        assert readable.log_record.attributes.get("n") == 3, f"атрибут n не доехал: {readable.log_record.attributes!r}"

    def test_resource_attributes_and_schema_url_reach_sdk_resource(self) -> None:
        our_resource = Resource(
            attributes={"service.name": "inspector", "process.pid": 4242},
            schema_url="https://opentelemetry.io/schemas/1.26.0",
        )
        readable = self._export_one(_mapped_record(resource=our_resource))
        assert readable.resource.attributes.get("service.name") == "inspector", (
            f"Resource.attributes не доехали: {dict(readable.resource.attributes)!r}"
        )
        assert readable.resource.attributes.get("process.pid") == 4242, (
            f"Resource.attributes (число) не доехало: {dict(readable.resource.attributes)!r}"
        )
        assert readable.resource.schema_url == "https://opentelemetry.io/schemas/1.26.0", (
            f"schema_url не переведён: {readable.resource.schema_url!r}"
        )


# ---------------------------------------------------------------------------
# Плагин-уровень (критерии 5, 6, 7) — угаданный крючок: см. докстринг модуля.
# ---------------------------------------------------------------------------


class _FakeCommandManager:
    def __init__(self) -> None:
        self.registered: dict[str, Any] = {}

    def register_command(self, name: str, method: Any) -> None:
        self.registered[name] = method

    def get_command_info(self, name: str) -> Any:
        return self.registered.get(name)


class _RouterHandlerSpy:
    """Дубль ГРАНИЦЫ процесса — тот же приём, что в test_f2_task21_acceptance.py."""

    def __init__(self, answers: list | None = None) -> None:
        self.handlers: dict[str, Any] = {}
        self.request_calls: list[dict] = []
        self.answers: list = list(answers or [])

    def register_message_handler(self, key: str, handler: Any, *a: Any, **k: Any) -> bool:
        self.handlers[key] = handler
        return True

    def request_async(
        self,
        message: dict,
        on_response: Any,
        timeout: float = 5.0,
        correlation_id: Any = None,
    ) -> str:
        self.request_calls.append(message)
        cid = correlation_id or f"cid-{len(self.request_calls)}"
        answer = self.answers.pop(0) if self.answers else {"success": True, "result": {"success": True}}
        if answer is not None:
            on_response(answer)
        return cid


def _make_services(process_name: str, *, router_manager: Any = None, command_manager: Any = None) -> SimpleNamespace:
    noop = lambda *a, **k: None  # noqa: E731
    return SimpleNamespace(
        name=process_name,
        worker_manager=None,
        command_manager=command_manager if command_manager is not None else _FakeCommandManager(),
        router_manager=router_manager if router_manager is not None else _RouterHandlerSpy(),
        memory_manager=None,
        state_proxy=None,
        log_debug=noop,
        log_info=noop,
        log_warning=noop,
        log_error=noop,
        log_critical=noop,
        send_message=lambda *a, **k: True,
        receive_message=lambda *a, **k: None,
    )


def _make_ctx(services: SimpleNamespace, config: dict | None = None) -> Any:
    from multiprocess_framework.modules.process_module.plugins import PluginContext

    return PluginContext(services=services, config=config or {}, io=None, registers=None, plugin_name="otel_export")


def _boot_plugin(config: dict | None = None) -> tuple[Any, Any, _RouterHandlerSpy, _FakeCommandManager, list]:
    """Собрать и завести плагин: configure -> start. Возвращает (plugin, ctx, router, cmd_mgr, recorded_metrics)."""
    from Plugins.io.otel_export.plugin import OtelExportPlugin

    router = _RouterHandlerSpy()
    command_manager = _FakeCommandManager()
    services = _make_services("proc_t22", router_manager=router, command_manager=command_manager)
    ctx = _make_ctx(services, config=config or {"endpoint": "http://127.0.0.1:4318/v1/logs"})
    recorded: list[tuple[str, Any]] = []
    ctx.record_metric = lambda name, value=1, tags=None: recorded.append((name, value))

    plugin = OtelExportPlugin()
    plugin._do_configure(ctx)
    plugin._do_start(ctx)
    return plugin, ctx, router, command_manager, recorded


def _install_fake_exporter(monkeypatch: pytest.MonkeyPatch, results: list[ExportOutcome]) -> list[list[Any]]:
    """Подменить ``OtlpHttpExporter`` в namespace ``plugin.py`` на управляемый дубль.

    Возвращает список пачек, с которыми был позван ``export()`` — растёт при каждом вызове,
    независимо от того, сколько раз плагин конструирует экспортёр (закрытие, а не
    классовый атрибут). ``results`` — очередь исходов на последовательные ``export()``;
    когда пуста — ``ExportOutcome(accepted=len(batch), failed=0, reason="")`` (успех).

    **Угаданный крючок** (см. докстринг модуля): атрибут ``OtlpHttpExporter`` в модуле
    ``Plugins.io.otel_export.plugin``. Сегодня его там нет -> ``monkeypatch.setattr``
    с ``raising=True`` (по умолчанию) поднимет ``AttributeError`` — это и есть ожидаемое
    красное состояние для тестов, использующих этот хелпер.
    """
    calls: list[list[Any]] = []
    queue: list[ExportOutcome] = list(results)

    class _FakePluginExporter:
        def __init__(self, *_a: Any, **_k: Any) -> None:
            pass

        def export(self, records: Any) -> ExportOutcome:
            batch = list(records)
            calls.append(batch)
            if queue:
                return queue.pop(0)
            return ExportOutcome(accepted=len(batch), failed=0, reason="")

    import Plugins.io.otel_export.plugin as plugin_module

    monkeypatch.setattr(plugin_module, "OtlpHttpExporter", _FakePluginExporter)
    return calls


def _install_log_windowed_spy(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Обернуть ``log_windowed`` в ``plugin.py`` шпионом, который зовёт настоящую функцию.

    Настоящий вызов сохраняется (сквозной проброс) — решение WindowedVoices.take() и
    фактическая эмиссия остаются живыми, шпион только записывает форму вызова.
    """
    import Plugins.io.otel_export.plugin as plugin_module

    calls: list[dict[str, Any]] = []
    real_log_windowed = plugin_module.log_windowed

    def _spy(key: str, interval: Any, level: str, msg: str, **kwargs: Any) -> bool:
        calls.append({"key": key, "interval": interval, "level": level, "msg": msg, "ctx": kwargs})
        return real_log_windowed(key, interval, level, msg, **kwargs)

    monkeypatch.setattr(plugin_module, "log_windowed", _spy)
    return calls


def _feed_records(router: _RouterHandlerSpy, records: list[dict]) -> None:
    handler = router.handlers["observability.record"]
    handler({"command": "observability.record", "data": {"records": records}})


def _log_record(message: str, ts: float, *, severity: str = "ERROR", severity_number: int = 17) -> dict:
    return {
        "kind": "log",
        "severity": severity,
        "severity_number": severity_number,
        "message": message,
        "module": "x",
        "ts": ts,
    }


# ---------------------------------------------------------------------------
# Критерии 5, 6: отказ доставки слышен ровно одной строкой на окно; окно из политики
# ---------------------------------------------------------------------------


class TestExportFailedIsHeardWithWindowedVoice:
    def test_failure_grows_export_failed_by_count_and_voices_exactly_once_per_flush(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Критерий 5: 3 отказавшие записи в ОДНОМ flush -> export_failed += 3, ОДНА строка."""
        _install_fake_exporter(
            monkeypatch,
            results=[
                ExportOutcome(accepted=0, failed=3, reason="collector unreachable: http://127.0.0.1:4318/v1/logs")
            ],
        )
        log_calls = _install_log_windowed_spy(monkeypatch)

        plugin, ctx, router, command_manager, recorded = _boot_plugin()
        _feed_records(router, [_log_record(f"m{i}", 1.0 + i) for i in range(3)])

        command_manager.registered["otel_export.flush"]({})

        export_failed_growth = sum(v for n, v in recorded if n == "otel_export.export_failed")
        assert export_failed_growth == 3, (
            f"export_failed обязан вырасти ровно на число отказавших записей (3): {recorded!r}"
        )

        failure_voices = [c for c in log_calls if c["key"] == "otel_export.export_failed"]
        assert len(failure_voices) == 1, (
            f"на пачку из 3 отказавших записей ожидалась РОВНО ОДНА строка голоса (не по одной "
            f"на запись), получено {len(failure_voices)}: {failure_voices!r}"
        )
        assert failure_voices[0]["level"] == "error", f"уровень голоса отказа обязан быть error: {failure_voices[0]!r}"

    def test_window_argument_is_none_not_a_literal(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Критерий 6: interval у голоса export_failed — None (окно из политики), не число."""
        _install_fake_exporter(
            monkeypatch,
            results=[ExportOutcome(accepted=0, failed=1, reason="collector unreachable")],
        )
        log_calls = _install_log_windowed_spy(monkeypatch)

        plugin, ctx, router, command_manager, recorded = _boot_plugin()
        _feed_records(router, [_log_record("m", 1.0)])

        command_manager.registered["otel_export.flush"]({})

        failure_voices = [c for c in log_calls if c["key"] == "otel_export.export_failed"]
        assert failure_voices, f"log_windowed ни разу не позван на ключ otel_export.export_failed: {log_calls!r}"
        assert failure_voices[0]["interval"] is None, (
            f"interval у голоса otel_export.export_failed обязан быть None (окно берётся из "
            f"политики, Р-23) — литеральное число запрещено. Получено {failure_voices[0]['interval']!r}"
        )

    def test_success_does_not_grow_export_failed_and_does_not_voice(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Пара к отказу: успешный flush -> export_failed не растёт, ни одной строки голоса."""
        _install_fake_exporter(monkeypatch, results=[])  # пустая очередь -> всегда успех
        log_calls = _install_log_windowed_spy(monkeypatch)

        plugin, ctx, router, command_manager, recorded = _boot_plugin()
        _feed_records(router, [_log_record("m", 1.0, severity="INFO", severity_number=9)])

        command_manager.registered["otel_export.flush"]({})

        export_failed_growth = sum(v for n, v in recorded if n == "otel_export.export_failed")
        assert export_failed_growth == 0, f"export_failed не должен расти на успешном flush: {recorded!r}"
        failure_voices = [c for c in log_calls if c["key"] == "otel_export.export_failed"]
        assert not failure_voices, f"на успехе не должно быть ни одной строки голоса export_failed: {failure_voices!r}"


# ---------------------------------------------------------------------------
# Критерий 7: otel_export.flush больше не noop
# ---------------------------------------------------------------------------


class TestFlushIsNoLongerNoop:
    def test_flush_returns_numbers_matching_accumulated_counters(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_fake_exporter(
            monkeypatch,
            results=[ExportOutcome(accepted=1, failed=1, reason="partial: collector busy")],
        )
        _install_log_windowed_spy(monkeypatch)  # не проверяется здесь — только чтобы не тронуть stdlib-логгер

        plugin, ctx, router, command_manager, recorded = _boot_plugin()
        _feed_records(
            router,
            [
                _log_record("a", 1.0, severity="INFO", severity_number=9),
                _log_record("b", 2.0, severity="ERROR", severity_number=17),
            ],
        )

        result = command_manager.registered["otel_export.flush"]({})

        assert isinstance(result, dict), f"otel_export.flush обязан вернуть dict: {result!r}"
        assert result.get("status") != "noop", (
            f"flush обязан перестать отвечать noop в этой задаче (Task 2.2, Р-21): {result!r}"
        )

        status = command_manager.registered["otel_export.status"]({})
        counters = status["counters"]
        assert counters["exported"] == 1, (
            f"счётчик otel_export.status.counters.exported не сошёлся с исходом флаша (accepted=1): {counters!r}"
        )
        assert counters["export_failed"] == 1, (
            f"счётчик otel_export.status.counters.export_failed не сошёлся с исходом флаша (failed=1): {counters!r}"
        )


# ---------------------------------------------------------------------------
# Критерий 8: ленивость сохранена и после появления OtlpHttpExporter
# ---------------------------------------------------------------------------


class TestLazyImportStillHoldsForOtlpHttpExporter:
    """Повтор приёма ``test_lazy_sdk_acceptance.py`` (E1/E3), нацеленный на новый класс.

    Красное состояние СЕЙЧАС: ``from Services.otel_export.exporter import OtlpHttpExporter``
    внутри подпроцесса поднимает ``ImportError`` (класса нет) -> ``returncode != 0`` ->
    ``AssertionError`` здесь, с traceback подпроцесса в тексте. Это ДРУГОЙ класс отказа,
    чем «opentelemetry протёк», и достаточно явный, чтобы не спутать одно с другим.
    """

    def test_importing_otlphttpexporter_does_not_pull_opentelemetry_into_sys_modules(self) -> None:
        code = (
            "import sys\n"
            "from Services.otel_export.exporter import OtlpHttpExporter\n"
            "leaked = [m for m in sys.modules if m == 'opentelemetry' or m.startswith('opentelemetry.')]\n"
            "print('LEAKED=' + repr(leaked))\n"
            "sys.exit(1 if leaked else 0)\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
            timeout=60,
        )
        assert result.returncode == 0, (
            f"Импорт OtlpHttpExporter упал или протёк opentelemetry в sys.modules.\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
