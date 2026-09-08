# -*- coding: utf-8 -*-
"""Приёмочные тесты Task 2.1 (``OtelExportPlugin``) — независимый тестер, ДО реализации.

Источник критериев — бриф тестеру Task 2.1 трека ``otel-export`` (решения Р-6…Р-15
+ критерии приёмки 1-11). Файл ``Plugins/io/otel_export/plugin.py`` НЕ существует
на момент написания — красное состояние ожидаемо и НАМЕРЕННО не чинится заглушкой.

Импорт предмета — ВНУТРИ каждого теста (или метода класса), не на уровне модуля,
ради ``pytest --collect-only`` и ради изоляции ошибок импорта по тестам.

**Один тест в этом файле красен НЕ из-за отсутствия ``plugin.py``, а из-за живого
дефекта в уже реализованном ``Services/otel_export/mapping.py`` (Ф1, Task 1.1)** —
см. класс ``TestRecordKindNotOverwritten`` и разбор в докстринге теста. Это другой
класс отказа (``AssertionError`` на существующем коде, не ``ImportError``/
``ModuleNotFoundError`` на отсутствующем) — назван явно, как того требует бриф.

Общий харнесс (см. хелперы ниже): ``PluginContext`` строится РЕАЛЬНЫМ конструктором
(``services``/``config``/``io``/``registers``/``plugin_name``) на дублях ГРАНИЦЫ
процесса (router/command_manager/send_message) — тот же приём, что у
``test_observability_tail_delivery.py`` («настоящая проводка, фейковый только
router — граница процесса»). Для критерия 1 (реальная регистрация хендлера)
используется НАСТОЯЩИЙ ``RouterManager`` + ``QueueChannel`` — без него тест ничего
не доказывает.

``multiprocess_framework/modules/process_module/plugins/plugin_test_bench.py``
(``PluginTestBench``), упомянутый в брифе как стенд, здесь НЕ используется:
его конструктор зовёт ``PluginContext(process_name=..., process=..., ...)`` —
устаревшая сигнатура, разошедшаяся с текущим ``PluginContext.__init__(services,
config=None, io=None, registers=None, plugin_name=None)``. Инстанцирование стенда
упадёт ``TypeError`` раньше, чем до жизненного цикла плагина дойдёт очередь
(``PluginTestBench`` не используется НИГДЕ в дереве, кроме своего же файла и
реэкспорта — проверено grep'ом). Это находка, а не мелочь: бриф ссылался на стенд
как на рабочий инструмент.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path
from queue import Queue
from types import SimpleNamespace
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
PLUGIN_MODULE_PATH = REPO_ROOT / "Plugins" / "io" / "otel_export" / "plugin.py"


# ---------------------------------------------------------------------------
# Харнесс: границы процесса — дубли; PluginContext — настоящий конструктор.
# ---------------------------------------------------------------------------


class _FakeCommandManager:
    """Перехватывает ``register_command`` — тем же приёмом, что ``PluginTestBench._capture_command``."""

    def __init__(self) -> None:
        self.registered: dict[str, Any] = {}

    def register_command(self, name: str, method: Any) -> None:
        self.registered[name] = method

    def get_command_info(self, name: str) -> Any:
        return self.registered.get(name)


class _RouterHandlerSpy:
    """Дубль ГРАНИЦЫ процесса: перехватывает ``register_message_handler``, не диспетчеризацию.

    Используется там, где предмет проверки — СОДЕРЖИМОЕ обработки записи
    (счётчики, observed_ts, coerce_attributes), а не сам факт регистрации на
    настоящем роутере — тот проверяется отдельно, на настоящем ``RouterManager``
    (см. ``TestHandlerRegistersOnRealRouter``).
    """

    def __init__(self, answers: list | None = None) -> None:
        self.handlers: dict[str, Any] = {}
        #: Отправленные через request_async билеты — намерение брокеру среди них.
        self.request_calls: list[dict] = []
        #: Сценарий ответов брокера. ``None`` в списке = «ответа не будет вовсе»
        #: (молчание), что для плагина обязано быть неотличимо от отказа только
        #: по исходу, но не по числу попыток.
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
        """Форма — дословно ``RouterManager.request_async`` (router_manager.py:1106).

        Колбэк зовётся СИНХРОННО и ровно один раз, ответом из :attr:`answers`
        (по умолчанию — успех брокера). Настоящий роутер зовёт его на приёмном
        потоке позже; здесь эта разница несущественна, потому что предмет
        проверки — что плагин делает С ОТВЕТОМ, а не когда ответ приходит.
        """
        self.request_calls.append(message)
        cid = correlation_id or f"cid-{len(self.request_calls)}"
        answer = self.answers.pop(0) if self.answers else {"success": True, "result": {"success": True}}
        if answer is not None:
            on_response(answer)
        return cid


def _make_send_message(returns: bool = True) -> Any:
    """Фейк ``services.send_message`` — граница процесса. Записывает все вызовы."""
    calls: list[tuple[str, dict]] = []

    def _send(target: str, message: dict) -> bool:
        calls.append((target, message))
        return returns

    _send.calls = calls  # type: ignore[attr-defined]
    return _send


def _make_services(
    process_name: str,
    *,
    router_manager: Any = None,
    command_manager: Any = None,
    send_message: Any = None,
) -> SimpleNamespace:
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
        send_message=send_message if send_message is not None else _make_send_message(True),
        receive_message=lambda *a, **k: None,
    )


def _make_ctx(services: SimpleNamespace, config: dict | None = None) -> Any:
    from multiprocess_framework.modules.process_module.plugins import PluginContext

    return PluginContext(services=services, config=config or {}, io=None, registers=None, plugin_name="otel_export")


def _import_plugin_class() -> type:
    from Plugins.io.otel_export.plugin import OtelExportPlugin

    return OtelExportPlugin


# ---------------------------------------------------------------------------
# Критерий 7 + гигиена импорта (E1/E3 сервиса, повторённые для плагина)
# ---------------------------------------------------------------------------


class TestNoModuleLevelOpentelemetryImportInPlugin:
    """Критерий 7: ни одного ``import opentelemetry`` на уровне модуля ``plugin.py``."""

    def test_ast_no_module_level_opentelemetry_import(self) -> None:
        """Как краснеет СЕЙЧАС: файла нет вовсе -> явный assert, а не FileNotFoundError.

        Явная проверка существования — тем же доводом, что у E1 сервиса: пустой
        список нарушений на несуществующем файле неотличим от «нарушений нет».
        """
        assert PLUGIN_MODULE_PATH.exists(), (
            f"{PLUGIN_MODULE_PATH} не существует — Plugins/io/otel_export/plugin.py "
            "ещё не реализован (ожидаемое красное состояние ДО реализации Task 2.1)"
        )

        tree = ast.parse(PLUGIN_MODULE_PATH.read_text(encoding="utf-8"), filename=str(PLUGIN_MODULE_PATH))
        hits: list[str] = []
        for node in tree.body:
            if isinstance(node, ast.Import):
                hits.extend(
                    alias.name
                    for alias in node.names
                    if alias.name == "opentelemetry" or alias.name.startswith("opentelemetry.")
                )
            elif isinstance(node, ast.ImportFrom):
                if node.module and (node.module == "opentelemetry" or node.module.startswith("opentelemetry.")):
                    hits.append(node.module)
        assert not hits, f"import opentelemetry на уровне модуля plugin.py: {hits}"

    def test_importing_plugin_module_does_not_pull_opentelemetry_into_sys_modules(self) -> None:
        """E3-аналог: импорт пакета плагина не тянет opentelemetry в sys.modules.

        Подпроцесс — чистый sys.modules, изоляция от прочих тестов файла.
        """
        code = (
            "import sys\n"
            "import Plugins.io.otel_export.plugin\n"
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
            f"Импорт plugin.py протёк opentelemetry в sys.modules или упал.\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )


# ---------------------------------------------------------------------------
# Р-6: форма класса и регистрация в PluginRegistry
# ---------------------------------------------------------------------------


class TestPluginShapeAndRegistration:
    def test_class_attributes_match_r6(self) -> None:
        OtelExportPlugin = _import_plugin_class()
        from Plugins.io.otel_export.registers import OtelExportRegisters

        assert OtelExportPlugin.name == "otel_export"
        assert OtelExportPlugin.category == "output"
        assert OtelExportPlugin.inputs == []
        assert OtelExportPlugin.outputs == []
        assert OtelExportPlugin.register_class is OtelExportRegisters

    def test_registered_in_plugin_registry_via_decorator(self) -> None:
        from multiprocess_framework.modules.process_module.plugins.registry import PluginRegistry

        OtelExportPlugin = _import_plugin_class()  # импорт исполняет @register_plugin
        assert "otel_export" in PluginRegistry
        entry = PluginRegistry.get("otel_export")
        assert entry is not None
        assert entry.plugin_class is OtelExportPlugin

    def test_reexported_from_package_init(self) -> None:
        from Plugins.io.otel_export import OtelExportPlugin as ReExported

        OtelExportPlugin = _import_plugin_class()
        assert ReExported is OtelExportPlugin


# ---------------------------------------------------------------------------
# Критерий 1: хендлер на НАСТОЯЩЕМ роутере + subscriber == имя процесса
# ---------------------------------------------------------------------------


class TestHandlerRegistersOnRealRouter:
    """Критерий 1. Роутер — настоящий ``RouterManager`` + ``QueueChannel``, не фейк.

    Угадано (см. отчёт): регистрация хендлера ``observability.record`` происходит
    в ``start()``, а не в ``configure()`` — вывод из Р-14 («в состоянии error
    start() не регистрирует хендлер»), формальный критерий этого не called вовсе.
    """

    def test_dispatch_through_real_router_reaches_the_plugin(self) -> None:
        from multiprocess_framework.modules.router_module.core.router_manager import RouterManager
        from multiprocess_framework.modules.router_module.channels.queue_channel import QueueChannel

        OtelExportPlugin = _import_plugin_class()

        router = RouterManager(manager_name="camera_7")
        q: Queue = Queue()
        channel = QueueChannel("test_channel", q)
        router.register_channel(channel)
        router.initialize()
        try:
            command_manager = _FakeCommandManager()
            services = _make_services("camera_7", router_manager=router, command_manager=command_manager)
            ctx = _make_ctx(services, config={"endpoint": "http://127.0.0.1:4318/v1/logs"})

            # Граница фреймворка (framework boundary): наблюдаем ЭФФЕКТ реальной
            # диспетчеризации через легитимную точку — ctx.record_metric, а не
            # заглядываем во внутренний счётчик плагина.
            recorded: list[tuple[Any, ...]] = []
            ctx.record_metric = lambda name, value=1, tags=None: recorded.append((name, value))

            plugin = OtelExportPlugin()
            plugin._do_configure(ctx)
            plugin._do_start(ctx)

            q.put(
                {
                    "command": "observability.record",
                    "data": {
                        "records": [
                            {
                                "kind": "log",
                                "severity": "INFO",
                                "severity_number": 9,
                                "message": "m",
                                "module": "x",
                                "ts": 1000.0,
                            }
                        ]
                    },
                }
            )
            router.receive(timeout=0.5)

            names = [name for name, _value in recorded]
            assert "otel_export.received" in names, (
                f"дошедшая через настоящий router.receive() запись не отразилась счётчиком "
                f"otel_export.received — зарегистрированный хендлер либо не тот, либо не читает "
                f"очередь. Записано: {recorded!r}"
            )
        finally:
            router.shutdown()

    def test_subscribe_intent_uses_process_name_as_subscriber_not_a_constant(self) -> None:
        """Вторая половина критерия 1: адрес подписчика == имя процесса, не литерал.

        Р-16 (арбитраж ведущего): намерение уходит через
        ``ctx.router_manager.request_async``, а не ``ctx.send_message`` — иначе
        подтверждения брокера не существует как наблюдаемого факта, хотя
        транспортный авто-reply его даёт (см. докстринг класса ниже).
        """
        OtelExportPlugin = _import_plugin_class()

        router = _RouterHandlerSpy()
        services = _make_services("camera_42", router_manager=router)
        ctx = _make_ctx(services, config={"endpoint": "http://127.0.0.1:4318/v1/logs"})

        plugin = OtelExportPlugin()
        plugin._do_configure(ctx)
        plugin._do_start(ctx)

        subscribe_calls = [m for m in router.request_calls if m.get("command") == "observability.tail.subscribe_all"]
        assert subscribe_calls, (
            f"намерение observability.tail.subscribe_all не отправлено вовсе; "
            f"через request_async ушло: {router.request_calls!r}"
        )
        message = subscribe_calls[0]
        assert message.get("targets") == ["ProcessManager"], f"адресат намерения не ProcessManager: {message!r}"
        assert message.get("data", {}).get("subscriber") == "camera_42", (
            "subscriber в намерении не равен имени процесса (camera_42) — "
            f"похоже на захардкоженный литерал: {message!r}"
        )
        assert message.get("data", {}).get("level") == "INFO", (
            "level в намерении обязан приехать из регистров (дефолт INFO), а не быть опущен: "
            f"{message!r} — без него брокер подставит ERROR, и хвост станет ERROR-only по построению"
        )


# ---------------------------------------------------------------------------
# Критерий 2: observed_ts — проставлен, сохранён, обе формы входа
# ---------------------------------------------------------------------------


class TestObservedTimestamp:
    def _handler(self, config: dict | None = None) -> tuple[Any, Any]:
        OtelExportPlugin = _import_plugin_class()
        router = _RouterHandlerSpy()
        services = _make_services("proc_ots", router_manager=router)
        ctx = _make_ctx(services, config=config or {"endpoint": "http://127.0.0.1:4318/v1/logs"})
        plugin = OtelExportPlugin()
        plugin._do_configure(ctx)
        plugin._do_start(ctx)
        return router.handlers["observability.record"], ctx

    def test_observed_ts_stamped_on_records_form(self) -> None:
        handler, _ctx = self._handler()
        record = {"kind": "log", "severity": "INFO", "severity_number": 9, "message": "m", "ts": 1.0}
        handler({"command": "observability.record", "data": {"records": [record]}})
        assert record.get("observed_ts"), "observed_ts не проставлен у принятой записи (форма records)"

    def test_existing_observed_ts_is_preserved_not_overwritten(self) -> None:
        handler, _ctx = self._handler()
        record = {
            "kind": "log",
            "severity": "INFO",
            "severity_number": 9,
            "message": "m",
            "ts": 1.0,
            "observed_ts": 12345.0,
        }
        handler({"command": "observability.record", "data": {"records": [record]}})
        assert record["observed_ts"] == 12345.0, "уже стоящий observed_ts перетёрт вместо сохранения"

    def test_single_record_form_is_stamped(self) -> None:
        handler, _ctx = self._handler()
        record = {"kind": "log", "severity": "INFO", "severity_number": 9, "message": "m", "ts": 1.0}
        handler({"command": "observability.record", "data": {"record": record}})
        assert record.get("observed_ts"), "observed_ts не проставлен у формы data.record (одна запись)"

    def test_empty_payload_does_not_raise(self) -> None:
        handler, _ctx = self._handler()
        # Ни "records", ни "record" — пустая полезная нагрузка. Не должна падать.
        handler({"command": "observability.record", "data": {}})


# ---------------------------------------------------------------------------
# Критерий 3: received / skipped_numbers / mapper_rejected
# ---------------------------------------------------------------------------


class TestCounters:
    def _handler_with_spy(self) -> tuple[Any, list[tuple[str, Any]]]:
        OtelExportPlugin = _import_plugin_class()
        router = _RouterHandlerSpy()
        services = _make_services("proc_counters", router_manager=router)
        ctx = _make_ctx(services, config={"endpoint": "http://127.0.0.1:4318/v1/logs"})
        recorded: list[tuple[str, Any]] = []
        ctx.record_metric = lambda name, value=1, tags=None: recorded.append((name, value))
        plugin = OtelExportPlugin()
        plugin._do_configure(ctx)
        plugin._do_start(ctx)
        return router.handlers["observability.record"], recorded

    @staticmethod
    def _sum_for(recorded: list[tuple[str, Any]], metric_name: str) -> int:
        return sum(int(value) for name, value in recorded if name == metric_name)

    def test_received_counts_all_incoming_records(self) -> None:
        handler, recorded = self._handler_with_spy()
        records = [
            {"kind": "log", "severity": "INFO", "severity_number": 9, "message": "a", "ts": 1.0},
            {"kind": "stats", "severity": "number", "value": 1},
            {"kind": "observation", "severity": "number", "value": 2},
        ]
        handler({"command": "observability.record", "data": {"records": records}})
        assert self._sum_for(recorded, "otel_export.received") == 3, (
            f"received обязан вырасти на 3 (все входящие) независимо от последующей фильтрации: {recorded!r}"
        )

    def test_skipped_numbers_counts_numeric_kinds(self) -> None:
        handler, recorded = self._handler_with_spy()
        records = [
            {"kind": "log", "severity": "INFO", "severity_number": 9, "message": "a", "ts": 1.0},
            {"kind": "stats", "severity": "number", "value": 1},
            {"kind": "observation", "severity": "number", "value": 2},
        ]
        handler({"command": "observability.record", "data": {"records": records}})
        assert self._sum_for(recorded, "otel_export.skipped_numbers") == 2, (
            f"skipped_numbers обязан вырасти ровно на 2 (stats + observation): {recorded!r}"
        )

    def test_mapper_rejected_counts_records_that_pass_split_but_mapper_refuses(self) -> None:
        """Р-8: mapper_rejected — запись прошла split_exportable (kind не числовой),
        но маппер вернул None (severity == "number", последний рубеж мaппера).

        Сценарий однозначен по УЖЕ РЕАЛИЗОВАННОМУ mapping.py (Ф1): kind='log' не
        входит в NUMERIC_KINDS -> split_exportable её пропускает; severity='number'
        -> DisplayRecordMapper.to_otlp отказывает. Единственная законная дорога
        к mapper_rejected>0 при received=1, skipped_numbers=0.
        """
        handler, recorded = self._handler_with_spy()
        records = [{"kind": "log", "severity": "number", "severity_number": 0, "message": "a", "ts": 1.0}]
        handler({"command": "observability.record", "data": {"records": records}})
        assert self._sum_for(recorded, "otel_export.skipped_numbers") == 0, (
            "запись рода 'log' не должна попасть в skipped_numbers — она числовая по severity, не по kind"
        )
        assert self._sum_for(recorded, "otel_export.mapper_rejected") == 1, (
            f"mapper_rejected обязан вырасти на 1 (маппер отказал по severity=='number'): {recorded!r}"
        )


# ---------------------------------------------------------------------------
# Критерий 4: подтверждение намерения / исчерпание попыток / degraded
# ---------------------------------------------------------------------------


class TestSubscribeIntentConfirmationAndRetries:
    """Критерий 4 целиком. Модель тестера была неверна — Р-16, арбитраж ведущего.

    Тестер закрепил триггером повтора «``send_message`` вернул ``False``», решив,
    что подтверждения брокера как наблюдаемого факта не существует. Оно
    существует, и это прочитано в коде фреймворка, а не предположено:
    ``observability.tail.subscribe_all`` зарегистрирована на PM обычной командой
    без ``manages_own_reply`` (``process_manager_process.py:478``), а
    ``RouterManager._dispatch_command`` после исполнения зовёт
    ``reply_to_request`` (``router_manager.py:1241``), который адресует ответ
    обратно ``sender`` ровно тогда, когда билет несёт correlation-id.

    Отсюда дорога — ``request_async``, и триггеров повтора ТРИ, не один:
    ``success is False`` в ответе, таймаут слота и синхронный отказ отправки.
    Все три приходят в один колбэк — ``request_async`` гарантирует «ровно один
    раз» арбитражем ``_take_pending`` под локом.

    Синхронный ``request()`` здесь запрещён отдельно: приёмного цикла на роутере
    в момент ``start()`` плагина ещё нет (шаг 6 против шага 7
    ``ProcessModule.initialize``), и он вернул бы
    ``{"error": "timeout", "reason": "no_receive_pump"}`` через 0.5 с — тот же
    дефект, что стоил ``telemetry_sink`` 10.03 с простоя старта.
    """

    def test_max_attempts_constant_is_three(self) -> None:
        import Plugins.io.otel_export.plugin as plugin_module

        assert plugin_module.MAX_ATTEMPTS == 3

    def test_broker_confirms_on_first_answer_then_no_second_attempt(self) -> None:
        """Пара к отказу: брокер подтвердил — попытка РОВНО одна, состояние ready."""
        OtelExportPlugin = _import_plugin_class()

        router = _RouterHandlerSpy(answers=[{"success": True, "result": {"success": True}}])
        command_manager = _FakeCommandManager()
        services = _make_services("camera_1", router_manager=router, command_manager=command_manager)
        ctx = _make_ctx(services, config={"endpoint": "http://127.0.0.1:4318/v1/logs"})

        plugin = OtelExportPlugin()
        plugin._do_configure(ctx)
        plugin._do_start(ctx)

        attempts = [m for m in router.request_calls if m.get("command") == "observability.tail.subscribe_all"]
        assert len(attempts) == 1, f"подтверждённое намерение обязано стоить ОДНУ попытку, получено {len(attempts)}"
        status = command_manager.registered["otel_export.status"]({})
        assert status["state"] == "ready", f"состояние после подтверждения брокера: {status!r}"

    def test_exhausting_attempts_marks_degraded_with_exactly_one_incident(self) -> None:
        """Отказ брокера в ОТВЕТЕ (не локальный отказ отправки) — три попытки, один инцидент."""
        OtelExportPlugin = _import_plugin_class()

        # Четыре отказа в очереди против трёх разрешённых попыток: если плагин
        # попробует четвёртый раз, ответ у дубля для него найдётся, и лишняя
        # попытка проявится числом, а не исчезнет в пустом сценарии.
        refusal = {"success": False, "result": {"success": False, "reason": "брокер отказал"}}
        router = _RouterHandlerSpy(answers=[refusal, refusal, refusal, refusal])
        command_manager = _FakeCommandManager()
        services = _make_services("camera_9", router_manager=router, command_manager=command_manager)
        ctx = _make_ctx(services, config={"endpoint": "http://127.0.0.1:4318/v1/logs"})

        plugin = OtelExportPlugin()
        plugin._do_configure(ctx)

        incidents: list[tuple[Any, ...]] = []
        real_report_error = ctx.health.report_error  # тот же кэшированный HealthReporter, что позовёт плагин

        def _spy_report_error(*args: Any, **kwargs: Any) -> None:
            incidents.append((args, kwargs))
            return real_report_error(*args, **kwargs)

        ctx.health.report_error = _spy_report_error  # type: ignore[method-assign]

        plugin._do_start(ctx)

        subscribe_attempts = [m for m in router.request_calls if m.get("command") == "observability.tail.subscribe_all"]
        assert len(subscribe_attempts) == 3, (
            f"ожидалось ровно MAX_ATTEMPTS=3 попытки объявить намерение, получено {len(subscribe_attempts)}"
        )
        assert len(incidents) == 1, f"инцидент об исчерпании попыток обязан быть ОДИН, получено {len(incidents)}"

        status = command_manager.registered["otel_export.status"]({})
        assert status["state"] == "degraded", f"состояние плагина после исчерпания попыток: {status!r}"


# ---------------------------------------------------------------------------
# Критерий 5: отсутствие SDK -> error, причина называет extra и команду установки
# ---------------------------------------------------------------------------


class TestSdkAvailability:
    def test_missing_sdk_gives_error_state_with_install_hint(self, monkeypatch: pytest.MonkeyPatch) -> None:
        OtelExportPlugin = _import_plugin_class()

        real_modules = {
            name: mod
            for name, mod in sys.modules.items()
            if name == "opentelemetry" or name.startswith("opentelemetry.")
        }
        for name in real_modules:
            monkeypatch.setitem(sys.modules, name, None)

        import importlib.abc

        class _BlockOtel(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path, target=None):  # noqa: ANN001
                if fullname == "opentelemetry" or fullname.startswith("opentelemetry."):
                    raise ImportError(f"смоделировано отсутствие пакета: {fullname}")
                return None

        blocker = _BlockOtel()
        sys.meta_path.insert(0, blocker)
        try:
            command_manager = _FakeCommandManager()
            services = _make_services("proc_nosdk", command_manager=command_manager)
            ctx = _make_ctx(services, config={"endpoint": "http://127.0.0.1:4318/v1/logs"})

            plugin = OtelExportPlugin()
            plugin._do_configure(ctx)  # НЕ обязан бросать (Р-14)

            status = command_manager.registered["otel_export.status"]({})
            assert status["state"] == "error", f"ожидалось состояние error при отсутствии SDK: {status!r}"
            reason = str(status.get("reason", ""))
            assert "otel" in reason, f"причина не называет extra 'otel': {reason!r}"
            assert "uv pip install --inexact '.[otel]'" in reason, (
                f"причина не называет точную команду установки: {reason!r}"
            )
        finally:
            sys.meta_path.remove(blocker)

    def test_sdk_available_pair_gives_ready_state_with_version(self) -> None:
        """Пара к тесту выше: SDK установлен в этом venv (сверено E2 сервиса) -> ready + версия."""
        OtelExportPlugin = _import_plugin_class()

        command_manager = _FakeCommandManager()
        services = _make_services("proc_sdk_ok", command_manager=command_manager, send_message=_make_send_message(True))
        ctx = _make_ctx(services, config={"endpoint": "http://127.0.0.1:4318/v1/logs"})

        plugin = OtelExportPlugin()
        plugin._do_configure(ctx)
        plugin._do_start(ctx)

        status = command_manager.registered["otel_export.status"]({})
        assert status["state"] == "ready", f"ожидалось состояние ready при доступном SDK: {status!r}"
        assert "1.44" in str(status.get("sdk", "")), f"версия SDK не отражена в readback: {status!r}"


# ---------------------------------------------------------------------------
# Критерий 6: пустой endpoint -> error, причина называет ключ endpoint
# ---------------------------------------------------------------------------


class TestEmptyEndpoint:
    def test_empty_endpoint_gives_error_state_naming_the_key(self) -> None:
        OtelExportPlugin = _import_plugin_class()

        command_manager = _FakeCommandManager()
        services = _make_services("proc_noendpoint", command_manager=command_manager)
        # Регистры плагина дефолтят endpoint="" (см. Plugins/io/otel_export/registers.py) —
        # config пустой, override не нужен, чтобы воспроизвести пустой endpoint.
        ctx = _make_ctx(services, config={})

        plugin = OtelExportPlugin()
        plugin._do_configure(ctx)  # НЕ обязан бросать (Р-14)

        status = command_manager.registered["otel_export.status"]({})
        assert status["state"] == "error", f"пустой endpoint обязан давать состояние error: {status!r}"
        assert "endpoint" in str(status.get("reason", "")), f"причина не называет ключ endpoint: {status!r}"


# ---------------------------------------------------------------------------
# Критерий 8: coerce_attributes
# ---------------------------------------------------------------------------


class TestCoerceAttributes:
    """``Services/otel_export/mapping.py:coerce_attributes`` — функция ещё не существует
    в файле на момент написания (проверено чтением файла целиком) -> ImportError."""

    def test_scalars_pass_through_unchanged(self) -> None:
        from Services.otel_export.mapping import coerce_attributes

        attrs = {"a": "text", "b": True, "c": 3, "d": 2.5}
        result, coerced = coerce_attributes(attrs)
        assert result == {"a": "text", "b": True, "c": 3, "d": 2.5}
        assert coerced == 0

    def test_homogeneous_scalar_sequence_passes_through_unchanged(self) -> None:
        from Services.otel_export.mapping import coerce_attributes

        attrs = {"tags": ["x", "y", "z"], "nums": (1, 2, 3)}
        result, coerced = coerce_attributes(attrs)
        assert result["tags"] == ["x", "y", "z"]
        assert result["nums"] == (1, 2, 3)
        assert coerced == 0

    def test_non_scalar_values_are_coerced_to_string_and_counted(self) -> None:
        import datetime
        from pathlib import Path as _Path

        from Services.otel_export.mapping import coerce_attributes

        attrs = {
            "d": {"nested": 1},
            "s": {1, 2, 3},
            "p": _Path("/tmp/x"),
            "dt": datetime.datetime(2026, 1, 1),
            "mixed": [1, "two", 3.0],
            "none": None,
        }
        result, coerced = coerce_attributes(attrs)
        assert coerced == 6, f"ожидалось 6 приведений, получено {coerced} ({result!r})"
        for key in attrs:
            assert isinstance(result[key], str), f"значение {key!r} не приведено к строке: {result[key]!r}"
        # Ни одно значение не ИСЧЕЗЛО — ключей столько же, сколько на входе.
        assert set(result.keys()) == set(attrs.keys())


# ---------------------------------------------------------------------------
# Критерий 9: record.kind из контекста не перебивает настоящий род
# ---------------------------------------------------------------------------


class TestRecordKindNotOverwritten:
    """Р-10. **ВАЖНО: этот тест таргетирует УЖЕ РЕАЛИЗОВАННЫЙ ``DisplayRecordMapper``
    (Ф1, Task 1.1), а не ``OtelExportPlugin``.** Импорт не падает — красное состояние
    здесь другое: живой ``AssertionError``, потому что предмет уже реализован и
    реализован НЕВЕРНО (воспроизведено запуском перед написанием этого файла):

        attributes = {KIND_ATTRIBUTE: kind}   # settled first
        for key, value in context.items():
            if key not in NON_ATTRIBUTE_CONTEXT_KEYS:
                attributes[key] = value        # 'record.kind' НЕ в чёрном списке -> перебивает

    ``"record.kind"`` не входит в ``NON_ATTRIBUTE_CONTEXT_KEYS`` (тот список — только
    поля Resource + trace_id + origin), поэтому контекст с ключом, буквально названным
    ``"record.kind"``, побеждает настоящий род записи. Это НЕ дефект Task 2.1 и
    чинить его здесь не мой мандат (тестер не правит логику) — но красный тест ЗАФИКСИРОВАН
    как приёмочный критерий 9, и разработчик Task 2.1 либо чинит mapping.py, либо
    решение Р-10 нужно пересмотреть. См. пункт 4 отчёта.
    """

    def test_context_key_named_record_kind_does_not_win_over_the_real_kind(self) -> None:
        from Services.otel_export.mapping import DisplayRecordMapper

        mapper = DisplayRecordMapper()
        record = {
            "kind": "error",
            "severity": "ERROR",
            "severity_number": 17,
            "message": "boom",
            "module": "mymod",
            "ts": 100.0,
            "extra": {"context": {"record.kind": "evil_injected_kind"}},
        }
        mapped = mapper.to_otlp(record)
        assert mapped is not None
        assert mapped.attributes.get("record.kind") == "error", (
            f"настоящий род записи ('error') обязан выигрывать у ключа контекста "
            f"'record.kind'; получено {mapped.attributes.get('record.kind')!r}"
        )


# ---------------------------------------------------------------------------
# Критерий 10: otel_export.status -> handler_threads
# ---------------------------------------------------------------------------


class TestHandlerThreads:
    def test_single_threaded_reception_gives_exactly_one_identifier(self) -> None:
        import threading

        OtelExportPlugin = _import_plugin_class()

        router = _RouterHandlerSpy()
        command_manager = _FakeCommandManager()
        services = _make_services("proc_threads", router_manager=router, command_manager=command_manager)
        ctx = _make_ctx(services, config={"endpoint": "http://127.0.0.1:4318/v1/logs"})

        plugin = OtelExportPlugin()
        plugin._do_configure(ctx)
        plugin._do_start(ctx)

        handler = router.handlers["observability.record"]
        record = {"kind": "log", "severity": "INFO", "severity_number": 9, "message": "m", "ts": 1.0}
        handler({"command": "observability.record", "data": {"records": [record]}})

        status = command_manager.registered["otel_export.status"]({})
        threads = status.get("handler_threads")
        assert isinstance(threads, list), f"handler_threads не список: {threads!r}"
        assert threads == [threading.get_ident()], (
            f"после приёма из ОДНОГО (текущего) потока ожидался ровно один идентификатор "
            f"{threading.get_ident()}, получено {threads!r}"
        )


# ---------------------------------------------------------------------------
# Критерий 11: команды otel_export.status / otel_export.flush
# ---------------------------------------------------------------------------


class TestCommands:
    def test_status_and_flush_registered_with_literal_names_no_prefix_added(self) -> None:
        OtelExportPlugin = _import_plugin_class()

        command_manager = _FakeCommandManager()
        services = _make_services("proc_cmds", command_manager=command_manager)
        ctx = _make_ctx(services, config={"endpoint": "http://127.0.0.1:4318/v1/logs"})

        plugin = OtelExportPlugin()
        plugin._do_configure(ctx)

        assert "otel_export.status" in command_manager.registered, (
            f"команда otel_export.status не зарегистрирована: {list(command_manager.registered)}"
        )
        assert "otel_export.flush" in command_manager.registered, (
            f"команда otel_export.flush не зарегистрирована: {list(command_manager.registered)}"
        )

    def test_flush_command_returns_dict_with_status_key(self) -> None:
        OtelExportPlugin = _import_plugin_class()

        command_manager = _FakeCommandManager()
        services = _make_services("proc_flush", command_manager=command_manager)
        ctx = _make_ctx(services, config={"endpoint": "http://127.0.0.1:4318/v1/logs"})

        plugin = OtelExportPlugin()
        plugin._do_configure(ctx)
        plugin._do_start(ctx)

        result = command_manager.registered["otel_export.flush"]({})
        assert isinstance(result, dict)
        assert "status" in result, f"ответ otel_export.flush без ключа status: {result!r}"
