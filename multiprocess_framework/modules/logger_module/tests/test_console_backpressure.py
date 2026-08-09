# -*- coding: utf-8 -*-
"""Тесты backpressure консольного канала (резидуал R2, plan observability-unified-routing).

Контракт (не реализация): ``ConsoleChannel.write()`` пишет СИНХРОННО в поток-эмитенте.
После Ф0.9 путь ``error``/``critical`` идёт мимо батч-буфера вообще — то есть
прямо в ``stream.write()`` вызывающего потока. Если stdout перенаправлен в трубу,
которую никто не читает, поток-эмитент виснет НАВСЕГДА, и сейчас этому ничем не
ограничено. Эти тесты написаны от acceptance criteria плана, а не от реализации
``ConsoleChannel`` — поэтому они КРАСНЫЕ до появления предела ожидания записи.

Зачем эмулировать зависший stdout объектом-потоком, а не реальной трубой: реальная
труба без читателя — это отдельный процесс/файловый дескриптор, который переживает
сам тестовый прогон при сбое уборки. Синтетический поток с ``threading.Event``
управляется из теста явно и снимается в ``finally`` — так тест не может подвесить
весь pytest, даже если проверяемая защита ещё не написана.

Все фоновые потоки — daemon: если защита не реализована и поток навсегда
застревает в ``stream.write()``, тест обязан УВИДЕТЬ и ЗАФИКСИРОВАТЬ это как
падение (через join с таймаутом), а не позволить залипшему потоку держать
процесс pytest после завершения теста.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict

from multiprocess_framework.modules.logger_module.channels.log_channel import ConsoleChannel
from multiprocess_framework.modules.logger_module.core.log_config import (
    LoggerChannelSchema,
    LoggerManagerConfig,
)
from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager

_LOGGER_NAME = "multiprocess_framework.modules.logger_module.channels.log_channel"

# Предел из AC1 (~0.5с) с запасом на дрожание CI/Windows-таймеров: тест должен
# отличать «вернулся быстро» от «завис навсегда», а не ловить дрожание в 50мс.
_RETURN_DEADLINE_SEC = 1.0
_JOIN_TIMEOUT_SEC = 1.5


def _record(
    message: str,
    *,
    level: str = "INFO",
    module: str = "probe",
    extra: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Запись в формате, который принимает ``ILogChannel.write()`` (см. test_rollover_visibility.py)."""
    return {
        "module": module,
        "level": level,
        "message": message,
        "timestamp": time.time(),
        "extra": extra or {},
    }


class _StuckStream:
    """Поток вывода, который эмулирует зависший stdout: write() блокируется НАВСЕГДА,
    пока тест явно не позовёт release(). ``entered`` позволяет тесту дождаться
    момента, когда поток-жертва реально ВОШЁЛ в write(), а не просто стартовал
    поток ОС — без этого гонка старта делает тест недетерминированным.
    """

    def __init__(self) -> None:
        self._gate = threading.Event()
        self.entered = threading.Event()

    def write(self, data: str) -> int:
        self.entered.set()
        self._gate.wait()  # НЕ возвращается сам — только через release()
        return len(data)

    def flush(self) -> None:
        pass

    def release(self) -> None:
        self._gate.set()


class _RecordingStream:
    """Здоровый поток вывода: пишет мгновенно и потокобезопасно — эталон для
    стража против «починки», которая начинает терять строки на ровном месте.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._chunks: list[str] = []

    def write(self, data: str) -> int:
        with self._lock:
            self._chunks.append(data)
        return len(data)

    def flush(self) -> None:
        pass

    def getvalue(self) -> str:
        with self._lock:
            return "".join(self._chunks)


def _make_console_channel(stream: Any) -> ConsoleChannel:
    """Строит ConsoleChannel строго по контракту (config → __init__), затем
    подменяет ТОЛЬКО поток вывода хендлера — стандартный публичный атрибут
    ``logging.StreamHandler.stream``, а не внутреннее устройство ConsoleChannel.
    """
    cfg = LoggerChannelSchema(name="console", type="console", enabled=True, format="%(message)s")
    channel = ConsoleChannel(cfg)
    channel.handler.stream = stream
    return channel


def _call_capturing(holder: Dict[str, Any], key: str, fn, *args, **kwargs) -> None:
    """Целевая функция daemon-потока: кладёт результат вызова в holder[key]."""
    holder[key] = fn(*args, **kwargs)


class TestSecondWriterNotHeldForever:
    """AC1: застрявшая консоль не имеет права держать ВТОРОЙ поток-эмитент вечно.

    Первый поток, уже находящийся внутри блокирующего ``stream.write()``,
    остаётся заблокированным — это принимается и НЕ проверяется (см. ТЗ).
    """

    def test_second_writer_returns_quickly_when_console_stuck(self) -> None:
        stream = _StuckStream()
        channel = _make_console_channel(stream)
        try:
            t1 = threading.Thread(target=channel.write, args=(_record("first"),), daemon=True)
            t1.start()
            assert stream.entered.wait(timeout=1.0), "поток 1 обязан был войти в write() консоли"

            holder: Dict[str, Any] = {}
            t2 = threading.Thread(
                target=_call_capturing, args=(holder, "result", channel.write, _record("second")), daemon=True
            )
            started_at = time.perf_counter()
            t2.start()
            t2.join(timeout=_JOIN_TIMEOUT_SEC)
            elapsed = time.perf_counter() - started_at

            assert not t2.is_alive(), (
                f"второй поток НЕ вернулся из write() за {elapsed:.2f}с — застрявшая консоль "
                "держит поток-эмитент вечно (AC1 нарушен)"
            )
            assert elapsed < _RETURN_DEADLINE_SEC, f"второй поток вернулся, но за {elapsed:.2f}с — предел ~0.5с (AC1)"
        finally:
            stream.release()


class TestDroppedWriteReportsError:
    """AC2: брошенная запись обязана быть честно помечена status == "error".

    Не "success" и не "skipped": запись не попала на диск/консоль, и
    вышестоящий слой (floor ошибок Ф0.9) обязан это узнать.
    """

    def test_dropped_write_status_is_error_not_success_or_skipped(self) -> None:
        stream = _StuckStream()
        channel = _make_console_channel(stream)
        try:
            t1 = threading.Thread(target=channel.write, args=(_record("first"),), daemon=True)
            t1.start()
            assert stream.entered.wait(timeout=1.0), "поток 1 обязан был войти в write() консоли"

            holder: Dict[str, Any] = {}
            t2 = threading.Thread(
                target=_call_capturing, args=(holder, "result", channel.write, _record("second")), daemon=True
            )
            t2.start()
            t2.join(timeout=_JOIN_TIMEOUT_SEC)

            assert not t2.is_alive(), "второй write() не вернулся вовремя — см. AC1, дальнейшая проверка невозможна"
            result = holder.get("result")
            assert result is not None, "второй write() обязан был вернуть dict, а не просто выйти без значения"
            assert result["status"] == "error", (
                f"брошенная запись обязана быть помечена status='error', получено: {result!r}"
            )
        finally:
            stream.release()


class TestHealthyConsoleUnaffected:
    """AC3 — страж: правка backpressure не должна начать терять строки в
    здоровом (неблокирующем) случае. Один поток, обычная запись."""

    def test_single_threaded_write_succeeds_and_text_appears_in_stream(self) -> None:
        stream = _RecordingStream()
        channel = _make_console_channel(stream)

        result = channel.write(_record("hello healthy console", module="healthy_probe"))

        assert result["status"] == "success"
        assert "hello healthy console" in stream.getvalue()


class TestModerateConcurrencyNoLoss:
    """AC4: умеренная многопоточная конкуренция в здоровый поток ничего не теряет.

    Отброс допустим ТОЛЬКО когда консоль реально застряла — не при обычной
    конкуренции нескольких потоков за один и тот же (живой) поток вывода.
    """

    def test_eight_threads_fifty_writes_each_all_succeed(self) -> None:
        stream = _RecordingStream()
        channel = _make_console_channel(stream)
        results: list[Dict[str, Any]] = []
        results_lock = threading.Lock()

        def _writer(thread_idx: int, count: int) -> None:
            for i in range(count):
                r = channel.write(_record(f"line-{thread_idx}-{i}"))
                with results_lock:
                    results.append(r)

        threads = [threading.Thread(target=_writer, args=(idx, 50)) for idx in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10.0)
            assert not t.is_alive(), "поток конкуренции не завершился за 10с — подозрение на дедлок/зависание"

        assert len(results) == 400, f"ожидали 400 результатов, получили {len(results)}"
        success_count = sum(1 for r in results if r.get("status") == "success")
        assert success_count == 400, (
            f"ожидали 400 успешных записей на здоровый поток, получили {success_count}; "
            "отброс допустим только когда консоль реально застряла"
        )


class TestStatsVisibility:
    """AC5: счётчики отбросов/медленных записей видны через ``LoggerManager.get_stats()``
    под точными ключами ``sink_writes_dropped`` / ``sink_slow_writes`` —
    ВСЕГДА, в том числе нулями (иначе «ключа нет» и «отбросов нет» неразличимы)."""

    @staticmethod
    def _console_only_config() -> LoggerManagerConfig:
        """Единственный канал — console, чтобы не тянуть файловые каналы/tmp_path."""
        return LoggerManagerConfig.model_validate(
            {
                "enable_batching": False,
                "modules": {},
                "channels": {
                    "console": {"type": "console", "enabled": True, "format": "%(message)s"},
                },
                "default_level": "DEBUG",
                "scopes": {
                    "SYSTEM": {"channels": ["console"]},
                },
            }
        )

    def test_keys_present_with_zero_before_any_drop(self) -> None:
        mgr = LoggerManager(manager_name="ConsoleStatsProbeZero", config=self._console_only_config())
        mgr.initialize()
        try:
            stats = mgr.get_stats()
            assert "sink_writes_dropped" in stats, "ключ обязан присутствовать ДО первого отброса"
            assert "sink_slow_writes" in stats, "ключ обязан присутствовать ДО первой медленной записи"
            assert stats["sink_writes_dropped"] == 0
            assert stats["sink_slow_writes"] == 0
        finally:
            mgr.shutdown()

    def test_sink_writes_dropped_increments_when_console_stuck(self) -> None:
        mgr = LoggerManager(manager_name="ConsoleStatsProbeDrop", config=self._console_only_config())
        mgr.initialize()
        stream = _StuckStream()
        try:
            console_channel = mgr.get_channel("console")
            assert console_channel is not None, "console-канал обязан существовать по конфигу"
            console_channel.handler.stream = stream

            # .error()/.critical() идут МИМО батч-буфера (Ф0.9) — прямо в write()
            # вызывающего потока: это и есть путь, который умеет зависать.
            t1 = threading.Thread(target=mgr.error, args=("first",), kwargs={"module": "probe"}, daemon=True)
            t1.start()
            assert stream.entered.wait(timeout=1.0), "первый .error() обязан был войти в write() консоли"

            # Второй вызов — тоже в daemon-потоке с таймаутом: если предела ещё
            # нет, он рискует зависнуть так же, как первый, и это не должно
            # повесить весь прогон pytest.
            t2 = threading.Thread(target=mgr.error, args=("second",), kwargs={"module": "probe"}, daemon=True)
            t2.start()
            t2.join(timeout=_JOIN_TIMEOUT_SEC)
            assert not t2.is_alive(), "второй .error() не вернулся вовремя — см. AC1 про застрявшую консоль"

            stats = mgr.get_stats()
            assert stats["sink_writes_dropped"] >= 1, (
                f"второй .error() на застрявшую консоль обязан был увеличить "
                f"sink_writes_dropped, получили stats={stats}"
            )
        finally:
            stream.release()
            mgr.shutdown()


class TestThrottledWarning:
    """AC6: застрявшая консоль не должна давать WARNING на КАЖДУЮ брошенную
    запись — не чаще одного раза в интервал троттлинга."""

    def test_repeated_drops_produce_at_most_one_warning_in_interval(self, caplog) -> None:
        stream = _StuckStream()
        channel = _make_console_channel(stream)
        try:
            t1 = threading.Thread(target=channel.write, args=(_record("first"),), daemon=True)
            t1.start()
            assert stream.entered.wait(timeout=1.0), "поток 1 обязан был войти в write() консоли"

            attempt_threads = []
            for i in range(20):
                t = threading.Thread(target=channel.write, args=(_record(f"drop-{i}"),), daemon=True)
                attempt_threads.append(t)

            with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
                for t in attempt_threads:
                    t.start()
                for t in attempt_threads:
                    t.join(timeout=_JOIN_TIMEOUT_SEC)
                    assert not t.is_alive(), (
                        "отброшенная запись обязана вернуться быстро (AC1) — без этого "
                        "проверка троттлинга WARNING невозможна"
                    )

            warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
            assert len(warnings) <= 1, (
                f"20 отброшенных записей подряд дали {len(warnings)} WARNING вместо "
                "не более одного в пределах интервала троттлинга (AC6)"
            )
        finally:
            stream.release()
