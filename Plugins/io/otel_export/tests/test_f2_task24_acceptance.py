# -*- coding: utf-8 -*-
"""Приёмочные тесты Task 2.4 (Plugins-слой, асинхронный дренаж) — независимый тестер, ДО реализации.

Источник критериев — бриф тестеру Task 2.4 трека ``otel-export`` (критерии приёмки 1-6,
дословно). Покрывает критерии 1, 2, 3, 4, 6. Критерий 5 (голос отказа доставки называет
HTTP-код/класс исключения) живёт на Services-слое — см.
``Services/otel_export/tests/test_f2_task24_acceptance.py``.

**MODE эквивалент RED.** Заголовка MODE/INTERFACE/TASK в брифе не было, но бриф несёт
явные forbidden-paths и явное требование красного набора по критериям приёмки — тот же
случай, что описан в памяти тестера ``feedback_freeform_brief_without_mode_header``:
следую протоколу брифа, а не механическому ``MODE: regression``.

**Предмет задачи.** Сегодня ``Plugins/io/otel_export/plugin.py`` копит записи в кольце и
отправляет их СИНХРОННО по команде ``otel_export.flush``. Task 2.4 переводит приём в
асинхронный: очередь с потолком, фоновый дренаж пачкой, вытеснение старых записей со
своим счётчиком (``dropped_overflow``), ограниченное по времени (5 с) дожатие на останове.
Готовый механизм очереди — ``BatchDrainWorker``
(``multiprocess_framework/modules/channel_routing_module/observability/batch_drain.py``,
прочитан целиком) — реализация обязана переиспользовать его, не писать свой аналог.

**Что ЗАПРЕЩЕНО было читать** (бриф, дословно): ``Plugins/io/otel_export/plugin.py``,
``Services/otel_export/exporter.py``, ``Plugins/io/otel_export/tests/test_f2_task21_hazards.py``,
``Services/otel_export/tests/test_f2_task22_hazards.py``. Ни один не открывался; сигнатуры
``OtlpHttpExporter.__init__``/``.export``/``.force_flush`` получены ТОЛЬКО через
``inspect.signature`` в отдельном Bash-вызове (докстринг/тело не читаны — приём из памяти
тестера ``feedback_read_tool_cannot_skip_forbidden_docstrings``).

**Что читано и разрешено явно**: ``Services/otel_export/interfaces.py``, ``Services/otel_export/config.py``,
``batch_drain.py`` целиком, ``bounded_channel.py`` целиком (не в списке брифа буквально, но это
внутренность ``BatchDrainWorker`` — того самого «готового механизма», который бриф прямо
называет источником истины; без него нельзя понять учёт ``dropped``). Также прочитаны
(НЕ запрещены брифом, settled scaffolding предыдущих задач того же трека, тот же приём,
каким Task 2.2 читает Task 2.1): ``Plugins/io/otel_export/tests/test_f2_task21_acceptance.py``
(харнесс ``PluginContext``/``_RouterHandlerSpy``/``_FakeCommandManager``, лестница
``_do_configure``/``_do_start``/``_do_shutdown``) и ``Services/otel_export/tests/test_f2_task22_acceptance.py``
(паттерн ``sdk_factory`` + ``_FakeSdkExporter``, паттерн подмены ``OtlpHttpExporter`` для
плагин-уровневых тестов). ``Plugins/io/otel_export/registers.py`` прочитан — подтверждает,
что ``max_queue_size``/``max_export_batch_size``/``schedule_delay_ms`` из ``OtelExportConfig``
наследуются регистрами плагина без изменений.

**Угаданные крючки — минимизированы, и оба привязаны к УЖЕ СУЩЕСТВУЮЩЕМУ коду, не к Task 2.4:**

1. ``Services.otel_export.exporter.OtlpHttpExporter.export`` патчится ПРЯМО НА КЛАССЕ
   (``monkeypatch.setattr(OtlpHttpExporter, "export", ...)``), а не на имени, импортированном
   в ``plugin.py`` (как делает Task 2.2 для СВОИХ критериев). Это сознательный выбор ради
   устойчивости: подмена на классе перехватывает вызов независимо от того, как именно
   Task 2.4 достаёт объект экспортёра (готовый атрибут плагина, каждый раз новый объект,
   поле воркера очереди) — риск угадать НЕВЕРНОЕ имя атрибута этим снят полностью.
2. ``dropped_overflow`` читается ЛИБО из ``otel_export.status()["counters"]["dropped_overflow"]``
   (по аналогии с уже существующими ``counters["exported"]``/``counters["export_failed"]``
   у Task 2.2), ЛИБО из метрики ``ctx.record_metric`` с именем, оканчивающимся на
   ``dropped_overflow`` (по аналогии с ``otel_export.received``/``otel_export.skipped_numbers``
   у Task 2.1) — ОБА адреса проверяются, засчитывается любой ненулевой/нулевой результат
   (см. ``_read_dropped_overflow``). Хедж, а не гадание вслепую.

Голос переполнения/потерь стока ловится НЕ через угаданное имя в ``plugin.py``, а через
патч на ``log_windowed`` В МОДУЛЕ ЕГО ОПРЕДЕЛЕНИЯ
(``multiprocess_framework.modules.logger_module.core.windowed_voice``) — ``batch_drain.py``
делает ``from ...logger_module.core.windowed_voice import log_windowed`` ЛЕНИВО, ВНУТРИ
метода ``_voice`` (прочитано дословно, строка 514 модуля), то есть каждый вызов заново
берёт ИМЯ С МОДУЛЯ — патч на модуле гарантированно перехватывается, независимо от того,
где именно (плагин или сервис) ``BatchDrainWorker`` сконструирован.

Любой вызов, способный заблокироваться (приём под зависшим стоком, останов), исполняется в
daemon-потоке с ``join(deadline)`` — см. ``_call_with_deadline``.
"""

from __future__ import annotations

import re
import threading
import time
from types import SimpleNamespace
from typing import Any, Callable

import pytest

_ENDPOINT = "http://127.0.0.1:4318/v1/logs"

#: Литерал из ``Services/otel_export/interfaces.py`` (``LogExporter.force_flush``, Post):
#: «исход записан строкой в журнал литералом `otel flush: N дожато, M потеряно`».
FLUSH_LINE_RE = re.compile(r"otel flush:\s*\d+\s*дожато,\s*\d+\s*потеряно")


# ---------------------------------------------------------------------------
# Харнесс: границы процесса — дубли (тот же приём, что в test_f2_task21/22_acceptance.py).
# ---------------------------------------------------------------------------


class _FakeCommandManager:
    def __init__(self) -> None:
        self.registered: dict[str, Any] = {}

    def register_command(self, name: str, method: Any) -> None:
        self.registered[name] = method

    def get_command_info(self, name: str) -> Any:
        return self.registered.get(name)


class _RouterHandlerSpy:
    """Дубль ГРАНИЦЫ процесса — не отзывает регистрацию хендлера сам (это фейк, не настоящая
    отписка), что намеренно используется в критерии 6 для моделирования «форвардер снят
    позже, чем закрыта очередь»."""

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


def _log_record(message: str, ts: float, *, severity: str = "ERROR", severity_number: int = 17) -> dict:
    return {
        "kind": "log",
        "severity": severity,
        "severity_number": severity_number,
        "message": message,
        "module": "x",
        "ts": ts,
    }


def _install_log_windowed_spy(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Патч на МОДУЛЕ ОПРЕДЕЛЕНИЯ ``log_windowed`` — см. докстринг файла про ленивый импорт
    ``batch_drain._voice``. Настоящий вызов сохраняется (сквозной проброс)."""
    import multiprocess_framework.modules.logger_module.core.windowed_voice as wv

    calls: list[dict[str, Any]] = []
    real_log_windowed = wv.log_windowed

    def _spy(key: str, interval: Any, level: str, msg: str, **ctx: Any) -> bool:
        calls.append({"key": key, "interval": interval, "level": level, "msg": msg, "ctx": ctx})
        return real_log_windowed(key, interval, level, msg, **ctx)

    monkeypatch.setattr(wv, "log_windowed", _spy)
    return calls


@pytest.fixture(autouse=True)
def _fresh_process_voices() -> Any:
    """``WindowedVoices`` — процессный синглтон (см. память тестера
    ``feedback_windowed_voice_is_a_process_wide_singleton``): без сброса окно подавления
    одного теста маскирует голос следующего."""
    from multiprocess_framework.modules.logger_module.core.windowed_voice import reset_process_voices

    reset_process_voices()
    yield
    reset_process_voices()


def _patch_hanging_export(
    monkeypatch: pytest.MonkeyPatch, entered: threading.Event, release: threading.Event, hang_seconds: float = 30.0
) -> None:
    """Подменить ``OtlpHttpExporter.export`` НА КЛАССЕ стоком, который ЖДЁТ (не бросает).

    ``entered`` взводится СРАЗУ на входе (доказывает, что фон реально дошёл до стока —
    достижимость); ``release`` развязывает зависание (вызывающий тест обязан его взвести
    в ``finally``, иначе фоновый поток останется висеть до истечения ``hang_seconds``)."""
    from Services.otel_export.exporter import OtlpHttpExporter
    from Services.otel_export.interfaces import ExportOutcome

    def _hanging_export(self: Any, records: Any) -> Any:
        entered.set()
        release.wait(hang_seconds)
        return ExportOutcome(accepted=len(list(records)), failed=0, reason="")

    monkeypatch.setattr(OtlpHttpExporter, "export", _hanging_export)


def _call_with_deadline(fn: Callable[[], Any], *, timeout: float, message: str) -> tuple[Any, float]:
    """Позвать ``fn`` в daemon-потоке с ``join(timeout)``.

    Правило проекта: вызов, способный заблокироваться, обязан идти этим путём — тест,
    который ВИСНЕТ вместо того чтобы упасть, хуже отсутствующего теста. Возвращает
    ``(результат, прошедшее_время)``; исключение внутри потока пробрасывается наружу.
    """
    result: dict[str, Any] = {}
    error: dict[str, BaseException] = {}

    def _run() -> None:
        try:
            result["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 — пробрасывается ниже, не проглатывается
            error["exc"] = exc

    thread = threading.Thread(target=_run, daemon=True)
    started = time.monotonic()
    thread.start()
    thread.join(timeout=timeout)
    elapsed = time.monotonic() - started
    if thread.is_alive():
        raise AssertionError(f"{message}: вызов не вернулся за {timeout} с (завис) — elapsed >= {elapsed:.3f} с")
    if "exc" in error:
        raise error["exc"]
    return result.get("value"), elapsed


def _boot(monkeypatch: pytest.MonkeyPatch, config: dict[str, Any] | None = None) -> SimpleNamespace:
    """Собрать и завести плагин: configure -> start. Возвращает связку объектов теста.

    ``log_windowed`` спай ставится ЗДЕСЬ (не в каждом тесте отдельно) — иначе события,
    случившиеся между конструированием и первым явным патчем в теле теста, терялись бы.
    """
    router = _RouterHandlerSpy()
    cmd = _FakeCommandManager()
    service_logs: list[dict[str, Any]] = []

    def _log_factory(level: str) -> Callable[..., None]:
        def _fn(message: str, **kwargs: Any) -> None:
            service_logs.append({"level": level, "msg": message, "kwargs": kwargs})

        return _fn

    services = SimpleNamespace(
        name="proc_t24",
        worker_manager=None,
        command_manager=cmd,
        router_manager=router,
        memory_manager=None,
        state_proxy=None,
        log_debug=_log_factory("debug"),
        log_info=_log_factory("info"),
        log_warning=_log_factory("warning"),
        log_error=_log_factory("error"),
        log_critical=_log_factory("critical"),
        send_message=lambda *a, **k: True,
        receive_message=lambda *a, **k: None,
    )

    from multiprocess_framework.modules.process_module.plugins import PluginContext

    ctx = PluginContext(
        services=services,
        config=config or {"endpoint": _ENDPOINT},
        io=None,
        registers=None,
        plugin_name="otel_export",
    )
    recorded: list[tuple[str, Any]] = []
    ctx.record_metric = lambda name, value=1, tags=None: recorded.append((name, value))  # type: ignore[method-assign]

    log_windowed_calls = _install_log_windowed_spy(monkeypatch)

    from Plugins.io.otel_export.plugin import OtelExportPlugin

    plugin = OtelExportPlugin()
    plugin._do_configure(ctx)
    plugin._do_start(ctx)

    return SimpleNamespace(
        plugin=plugin,
        ctx=ctx,
        router=router,
        cmd=cmd,
        recorded=recorded,
        log_windowed=log_windowed_calls,
        service_logs=service_logs,
        handler=router.handlers.get("observability.record"),
    )


def _boot_blocked_with_pilot(
    monkeypatch: pytest.MonkeyPatch, config: dict[str, Any] | None = None, wait_entered: float = 3.0
) -> SimpleNamespace:
    """``_boot`` + сток, который ЖДЁТ + одна пилотная запись, дождавшаяся входа в сток.

    После возврата фон ГАРАНТИРОВАННО стоит внутри ``export()`` и канал ГАРАНТИРОВАННО
    пуст (единственная взятая пачка — уже в полёте) — детерминированная база для теста
    переполнения (критерий 2) и теста останова (критерии 3, 4).
    """
    entered = threading.Event()
    release = threading.Event()
    _patch_hanging_export(monkeypatch, entered, release)

    boot = _boot(monkeypatch, config)
    assert boot.handler is not None, "хендлер observability.record не зарегистрирован после _do_start"
    boot.handler({"command": "observability.record", "data": {"records": [_log_record("pilot", 0.0)]}})

    assert entered.wait(wait_entered), (
        f"фон дренажа не дошёл до стока за {wait_entered} с после ОДНОЙ пилотной записи — "
        "асинхронный дренаж не запущен вовсе (ожидаемое красное состояние ДО реализации)"
    )

    boot.entered = entered
    boot.release = release
    return boot


def _read_dropped_overflow(cmd: _FakeCommandManager, recorded: list[tuple[str, Any]]) -> int | None:
    """Хедж по двум правдоподобным адресам — см. докстринг файла, пункт про угаданные крючки.

    Возвращает ``None``, когда счётчик НЕ обнаружен НИ по одному адресу — это отдельный,
    ЗВУЧАЩИЙ факт («счётчика нет вовсе»), а не молчаливый 0 (проектное правило: отсутствие
    обязано иметь парную проверку достижимости, иначе оно неотличимо от «есть, но пуст»).
    """
    status_fn = cmd.registered.get("otel_export.status")
    if status_fn is not None:
        counters = status_fn({}).get("counters", {})
        if "dropped_overflow" in counters:
            return int(counters["dropped_overflow"])
    metric_hits = [v for n, v in recorded if n.endswith("dropped_overflow")]
    if metric_hits:
        return int(sum(int(v) for v in metric_hits))
    return None


# ---------------------------------------------------------------------------
# Критерий 1: приём не блокирует поток роутера, даже при висящем стоке.
# ---------------------------------------------------------------------------


class TestReceptionDoesNotBlockOnHangingSink:
    """Критерий 1. Стережёт: обработчик ``observability.record`` исполняется на потоке
    роутера — зависший там вызов останавливает диспетчеризацию ВСЕХ сообщений процесса,
    не только наблюдаемости.

    Пара-достижимость обязательна (иначе тест доказывает пустоту): без неё «вернулось
    быстро» было бы истинно и на СЕГОДНЯШНЕМ коде, где приём просто копит записи в кольце
    и сеть не трогает вовсе — то есть тест прошёл бы вхолостую и до, и после реализации.
    ``entered.wait(...)`` требует, чтобы фон РЕАЛЬНО дошёл до стока.

    Как это правдоподобно ломается: реализация вызывает ``exporter.export()`` СИНХРОННО
    прямо в обработчике «для простоты» (например, при достижении порога батча дренирует
    последний батч на ТОМ ЖЕ потоке вместо будильника фонового потока) — тогда 1000
    записей при висящем стоке зависнут на месте первой записи, достигшей порога.
    """

    def test_1000_records_return_fast_while_sink_hangs_and_sink_is_reached(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        entered = threading.Event()
        release = threading.Event()
        _patch_hanging_export(monkeypatch, entered, release)

        boot = _boot(monkeypatch)
        assert boot.handler is not None
        records = [_log_record(f"m{i}", float(i)) for i in range(1000)]

        try:
            _value, elapsed = _call_with_deadline(
                lambda: boot.handler({"command": "observability.record", "data": {"records": records}}),
                timeout=2.0,
                message="приём 1000 записей при висящем стоке",
            )
            assert elapsed < 1.0, (
                f"приём 1000 записей занял {elapsed:.3f} с при висящем стоке — поток роутера "
                f"похоже заблокирован сетью (бюджет < 1.0 с)"
            )
            assert entered.wait(3.0), (
                "сток экспортёра ни разу не был позван фоновым дренажом за 3 с после приёма 1000 "
                "записей — приём 'вернулся быстро' потому что асинхронного дренажа нет вовсе, а не "
                "потому что он реально асинхронен (тест иначе доказывал бы пустоту)"
            )
        finally:
            release.set()

    def test_reception_cost_is_not_dramatically_higher_than_without_a_hanging_sink(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Вторая половина критерия 1 (дословно брифа): сравнение с контролем (сток отвечает
        мгновенно), а не только абсолютный бюджет — защита от медленной машины CI."""
        from Services.otel_export.exporter import OtlpHttpExporter
        from Services.otel_export.interfaces import ExportOutcome

        def _fast_export(self: Any, records: Any) -> Any:
            return ExportOutcome(accepted=len(list(records)), failed=0, reason="")

        monkeypatch.setattr(OtlpHttpExporter, "export", _fast_export)
        control_boot = _boot(monkeypatch)
        assert control_boot.handler is not None
        records = [_log_record(f"m{i}", float(i)) for i in range(1000)]
        _value, control_elapsed = _call_with_deadline(
            lambda: control_boot.handler({"command": "observability.record", "data": {"records": records}}),
            timeout=2.0,
            message="приём 1000 записей с мгновенным стоком (контроль)",
        )

        entered = threading.Event()
        release = threading.Event()
        _patch_hanging_export(monkeypatch, entered, release)
        blocked_boot = _boot(monkeypatch)
        assert blocked_boot.handler is not None
        try:
            _value2, blocked_elapsed = _call_with_deadline(
                lambda: blocked_boot.handler({"command": "observability.record", "data": {"records": records}}),
                timeout=2.0,
                message="приём 1000 записей при висящем стоке",
            )
            budget = max(1.0, control_elapsed * 10)
            assert blocked_elapsed < budget, (
                f"приём при висящем стоке ({blocked_elapsed:.3f} с) заметно дороже контроля без "
                f"зависания ({control_elapsed:.3f} с, допуск x10={budget:.3f} с) — приём платит "
                f"цену сети"
            )
            # Достижимость: без неё сравнение прошло бы и на СЕГОДНЯШНЕМ коде, где сток НИКОГДА
            # не потревожен (записи просто лежат в кольце) — «не дороже контроля» было бы верно
            # по причине «дренажа нет вовсе», а не по причине «дренаж асинхронен».
            assert entered.wait(3.0), (
                "сток экспортёра ни разу не был позван фоновым дренажом за 3 с — сравнение с "
                "контролем прошло бы вхолостую (дренажа нет вовсе), а не потому что он реально "
                "асинхронен"
            )
        finally:
            release.set()


# ---------------------------------------------------------------------------
# Критерий 2: dropped_overflow — свой счётчик, пара «ниже/выше ёмкости», голос окном.
# ---------------------------------------------------------------------------


class TestOverflowCounterHasAnAchievabilityPair:
    """Критерий 2. Стережёт: переполнение очереди дренажа считается СВОИМ, отдельным
    счётчиком (``dropped_overflow``) и звучит РОВНО ОДНОЙ строкой на окно политики —
    не по строке на каждую вытесненную запись (иначе шторм переполнения топит журнал).

    Ёмкость очереди тестом НЕ фиксируется явным конфигом: адрес (поле ``max_queue_size``
    конфига сервиса или собственный дефолт ``BatchDrainWorker`` — 1024) тестеру достоверно
    неизвестен (см. отчёт). Вместо угаданного числа — заведомо малый объём (below) и
    заведомо больший, чем ЛЮБОЙ правдоподобный дефолт/конфиг (above, N=3000 > 2048 > 1024).

    Как это правдоподобно ломается: реализация считает вытеснение в ОБЩИЙ счётчик потерь
    (например, тот же, что у отказа стока) — тогда below-тест уже красный на ЛЮБОМ трафике
    (общий счётчик отражает и «отказ стока» из других тестов), а above-тест не различает
    причину роста числа.
    """

    def test_pair_below_any_plausible_capacity_counter_stays_zero_and_no_voice(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        boot = _boot_blocked_with_pilot(monkeypatch)
        try:
            for i in range(3):  # заведомо меньше любого правдоподобного дефолта ёмкости
                boot.handler({"command": "observability.record", "data": {"records": [_log_record(f"m{i}", float(i))]}})

            dropped = _read_dropped_overflow(boot.cmd, boot.recorded)
            assert dropped is not None, (
                "dropped_overflow не обнаружен НИ в otel_export.status().counters, НИ в "
                "ctx.record_metric — счётчика переполнения нет вовсе (ожидаемое красное "
                "состояние ДО реализации Task 2.4)"
            )
            assert dropped == 0, (
                f"ёмкость заведомо не достигнута (3 записи сверх одной пилотной), а "
                f"dropped_overflow уже не ноль: {dropped!r}"
            )
            overflow_voices = [c for c in boot.log_windowed if "overflow" in c["key"]]
            assert not overflow_voices, f"голос overflow прозвучал без переполнения: {overflow_voices!r}"
        finally:
            boot.release.set()

    def test_pair_above_any_plausible_capacity_counter_grows_and_voices_once(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        boot = _boot_blocked_with_pilot(monkeypatch)
        try:
            written = 0

            def _feed() -> None:
                # АРБИТРАЖ ВЕДУЩЕГО 2026-09-08 (второй проход ревью): литерал 3000
                # давал флейк ~15 %. Комментарий обещал «переполнение гарантировано»,
                # и это оказалось неправдой: замер ревью — `q_dropped=0` при
                # `depth=1751 < cap=2048`, потому что часть записей уезжает в полёт
                # к заблокированному стоку, и сколько именно — решает планировщик.
                # Фраза «гарантировано» без воспроизведения рядом — ровно то, что
                # правила проекта запрещают. Условие выхода теперь — сам предмет.
                nonlocal written
                while written < 40000 and not _read_dropped_overflow(boot.cmd, boot.recorded):
                    for i in range(500):
                        boot.handler(
                            {
                                "command": "observability.record",
                                "data": {"records": [_log_record(f"m{written + i}", float(i))]},
                            }
                        )
                    written += 500

            _call_with_deadline(_feed, timeout=30.0, message="приём записей до переполнения при висящем стоке")

            dropped = _read_dropped_overflow(boot.cmd, boot.recorded)
            assert dropped is not None, (
                "dropped_overflow не обнаружен НИ в otel_export.status().counters, НИ в "
                "ctx.record_metric — счётчика переполнения нет вовсе (ожидаемое красное "
                "состояние ДО реализации Task 2.4)"
            )
            assert dropped > 0, (
                f"{written} записей при заблокированном стоке обязаны дать dropped_overflow > 0, получено {dropped!r}"
            )
            overflow_voices = [c for c in boot.log_windowed if "overflow" in c["key"]]
            assert len(overflow_voices) == 1, (
                f"на многократное переполнение ожидалась РОВНО ОДНА строка голоса (окно политики), "
                f"получено {len(overflow_voices)}: {overflow_voices!r}"
            )
        finally:
            boot.release.set()


# ---------------------------------------------------------------------------
# Критерии 3 и 4: останов укладывается в 5 с даже против зависшего стока
# и называет исход числами.
# ---------------------------------------------------------------------------


class TestShutdownFlushIsBoundedAndOutcomeIsCountedNumerically:
    """Критерии 3 и 4 вместе — один сценарий (сток зависает НА останове) доказывает оба:
    бюджет 5 с (крит. 4) и числовую строку исхода (крит. 3, литерал из
    ``LogExporter.force_flush`` — ``otel flush: N дожато, M потеряно``).

    Останов способен заблокироваться -> daemon-поток с ``join`` дедлайном (проектное
    правило: тест, который ВИСНЕТ, хуже отсутствующего).

    Как это правдоподобно ломается: ``_do_shutdown``/``shutdown`` зовёт что-то вроде
    ``worker.flush(timeout=None)`` (без дедлайна) или сам сливает очередь синхронным
    циклом вместо будильника фонового потока (тот же класс дефекта, что описан в
    докстринге ``BatchDrainWorker.flush`` — «сток, который ЖДЁТ, уносил бы вызывающего
    с собой») — тогда останов виснет НА ВСЮ ДЛИНУ зависания стока (в этом тесте — 30 с),
    что daemon-поток с join(6.0) ловит как явный красный, а не как тихий hang сюиты.
    """

    def test_shutdown_completes_within_5s_budget_against_a_hanging_sink_and_logs_flush_numbers(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging

        caplog.set_level(logging.INFO)
        boot = _boot_blocked_with_pilot(monkeypatch)

        try:
            _value, elapsed = _call_with_deadline(
                lambda: boot.plugin._do_shutdown(boot.ctx), timeout=6.0, message="останов при висящем стоке"
            )
        finally:
            boot.release.set()

        assert elapsed <= 5.5, (
            f"останов обязан укладываться в бюджет 5 с даже против зависшего стока (запас 0.5 с "
            f"на накладные теста), фактически {elapsed:.3f} с"
        )

        ctx_lines = [str(c["msg"]) for c in boot.service_logs]
        found_in_ctx = any(FLUSH_LINE_RE.search(line) for line in ctx_lines)
        found_in_caplog = bool(FLUSH_LINE_RE.search(caplog.text))
        assert found_in_ctx or found_in_caplog, (
            "строка «otel flush: N дожато, M потеряно» (литерал из interfaces.py, "
            f"LogExporter.force_flush, Post) не найдена ни в ctx.log_*, ни в caplog.\n"
            f"ctx.log_*: {ctx_lines!r}\ncaplog:\n{caplog.text}"
        )

    def test_shutdown_with_no_pending_records_is_still_fast(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Пара к «зависший сток»: без единой записи в полёте останов не имеет права
        стоить сколько-нибудь заметное время — иначе бюджет 5 с закрывался бы каждый раз
        безусловным ожиданием, а не РЕАЛЬНЫМ дожатием."""
        boot = _boot(monkeypatch)
        _value, elapsed = _call_with_deadline(
            lambda: boot.plugin._do_shutdown(boot.ctx), timeout=6.0, message="останов без записей в очереди"
        )
        assert elapsed < 1.0, (
            f"останов без единой записи в полёте занял {elapsed:.3f} с — похоже на безусловное "
            f"ожидание дедлайна, а не на условное дожатие"
        )


# ---------------------------------------------------------------------------
# Критерий 6: запись, пришедшая ПОСЛЕ close(), не имеет права инфлировать dropped_overflow.
# ---------------------------------------------------------------------------


class TestPostCloseWritesDoNotInflateOverflowCounter:
    """Критерий 6. Стережёт границу СМЫСЛА счётчика: ``dropped_overflow`` обещает «не
    поместилось из-за наплыва записей», а не «что угодно, из-за чего запись не доехала».

    Основание — собственный докстринг ``BatchDrainWorker.counters()`` (прочитан дословно):
    «Вытеснение переполнением и отказ после останова — один факт для читателя (принято
    write(), стоку не отдано), поэтому они складываются под ОДНИМ именем, которое дал
    вызывающий» — то есть ``worker.counters()[counter_name]`` УЖЕ смешивает два разных
    факта внутри самого готового механизма. Если реализация Task 2.4 наивно транслирует
    это смешанное число напрямую в ``otel_export.status.counters.dropped_overflow``, поздняя
    запись (пришедшая уже ПОСЛЕ ``close()``) исказит именно это число, хотя ёмкость ни разу
    не была превышена — ровно та путаница, от которой критерий 6 предостерегает
    («таймер, переконфигурация, останов» — тот же класс, что «отказ после close»).

    Фейковый роутер (``_RouterHandlerSpy``) не отзывает регистрацию хендлера сам — это
    дубль границы процесса, не настоящая отписка, — поэтому вызов хендлера ПОСЛЕ
    ``_do_shutdown`` всё ещё возможен. Этим моделируется реальная гонка, которую сам
    интерфейс называет явно: ``LogExporter.force_flush`` зовётся «ДО снятия форвардеров»
    (``interfaces.py``), то есть запись способна дойти от роутера уже ПОСЛЕ того, как
    очередь дренажа закрыта.
    """

    def test_record_arriving_after_shutdown_does_not_grow_dropped_overflow_beyond_real_overflow(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Достижимость обязательна и здесь: ``dropped_overflow`` уже существует как ключ в
        ``otel_export.status().counters`` СЕГОДНЯ (статический 0 — заготовка схемы, а не живой
        счётчик), поэтому голое «после == до == 0» прошло бы вхолостую и БЕЗ реализации Task 2.4
        (см. отчёт тестера). Тест сперва добивается РЕАЛЬНОГО ненулевого значения через
        настоящее переполнение (тот же приём, что критерий 2, N=3000), и только затем проверяет,
        что поздняя запись НЕ добавляет к этому УЖЕ живому числу.
        """
        boot = _boot_blocked_with_pilot(monkeypatch)
        try:

            def _feed_overflow() -> None:
                for i in range(3000):
                    boot.handler(
                        {"command": "observability.record", "data": {"records": [_log_record(f"m{i}", float(i))]}}
                    )

            _call_with_deadline(_feed_overflow, timeout=10.0, message="приём 3000 записей при висящем стоке")

            dropped_from_real_overflow = _read_dropped_overflow(boot.cmd, boot.recorded)
            assert dropped_from_real_overflow is not None and dropped_from_real_overflow > 0, (
                "достижимость не выполнена: 3000 записей в ограниченную очередь обязаны дать "
                f"dropped_overflow > 0 ДО того, как проверять позднюю запись — иначе «не выросло» "
                f"неотличимо от «счётчика нет вовсе». Получено {dropped_from_real_overflow!r}"
            )
        finally:
            boot.release.set()  # развязать сток — дальше останов не обязан упираться в бюджет 5 с

        _value, _elapsed = _call_with_deadline(
            lambda: boot.plugin._do_shutdown(boot.ctx), timeout=6.0, message="останов после развязанного стока"
        )
        dropped_after_shutdown = _read_dropped_overflow(boot.cmd, boot.recorded)

        # Поздняя запись — «дошла» уже ПОСЛЕ close(). Если это вообще падает исключением
        # (реализация решила НЕ принимать вызовы хендлера после shutdown жёстко), это ДРУГОЙ,
        # тоже законный результат — тест намеренно не глушит исключение здесь.
        boot.handler({"command": "observability.record", "data": {"records": [_log_record("late", 999.0)]}})

        dropped_after_late_write = _read_dropped_overflow(boot.cmd, boot.recorded)
        assert dropped_after_late_write == dropped_after_shutdown, (
            f"запись, пришедшая ПОСЛЕ close(), выросла в dropped_overflow сверх уже накопленного "
            f"РЕАЛЬНЫМ переполнением значения: до поздней записи={dropped_after_shutdown}, "
            f"после={dropped_after_late_write}. BatchDrainWorker.counters() складывает "
            f"переполнение и «отказ после close» под ОДНИМ именем по собственному докстрингу — "
            f"эта путаница не имеет права всплыть в otel_export.status как dropped_overflow"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
