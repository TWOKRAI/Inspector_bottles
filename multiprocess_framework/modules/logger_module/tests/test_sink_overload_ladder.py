# -*- coding: utf-8 -*-
"""Лесенка перегрузки стока в базе канала — Ф7.2.

Механизм был написан для консоли (R2/R12) и там проверен; Ф7.2 подняла его в
`LogChannel`, потому что после снятия батчинга (Ф7.4) та же опасность появилась
у **файлового** стока: залипший диск блокирует поток-эмитент, а буфера, который
раньше это поглощал, больше нет.

Здесь сторожится то, чего у файлового стока не было ни одного дня: предел
ожидания, размыкание, обратимость, статус отказа и операбельность порогов.
Консольные стражи остаются на своём месте (`test_console_backpressure*.py`) —
эти два набора отвечают на разные вопросы: там «работает ли механизм», здесь
«достался ли он второму стоку».

Каждый тест, способный заблокироваться, крутит запись в daemon-потоке с
дедлайном join: тест, который вешает прогон вместо падения, хуже отсутствующего
(полная сюита из-за такого шла 20 минут вместо трёх — это и был симптом, с
которого задача началась).
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Dict

import pytest

from multiprocess_framework.modules.logger_module.channels.log_channel import FileChannel
from multiprocess_framework.modules.logger_module.configs.logger_manager_config import (
    LoggerChannelSchema,
)

#: Предел стенда — заведомо больше дедлайна канала и заведомо меньше терпения
#: человека: тест обязан отличать «вернулся с отказом» от «завис навсегда».
_JOIN_DEADLINE_SEC = 5.0


def _file_channel(tmp_path: Path, **overrides: Any) -> FileChannel:
    cfg = LoggerChannelSchema(
        name="stuck_file",
        type="file",
        enabled=True,
        file_path=str(tmp_path / "stuck.log"),
        rotate=False,
        format="%(message)s",
        **overrides,
    )
    return FileChannel(cfg)


def _record(message: str) -> Dict[str, Any]:
    return {
        "module": "unit",
        "level": "INFO",
        "message": message,
        "timestamp": time.time(),
        "extra": {},
    }


class _StuckHolder:
    """Чужой поток, удерживающий лок канала, — модель залипшего стока."""

    def __init__(self, channel: FileChannel) -> None:
        self._channel = channel
        self.entered = threading.Event()
        self.release = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self) -> "_StuckHolder":
        def _hold() -> None:
            with self._channel._write_lock:
                self.entered.set()
                self.release.wait(timeout=30.0)

        self._thread = threading.Thread(target=_hold, name="stuck-sink", daemon=True)
        self._thread.start()
        assert self.entered.wait(timeout=_JOIN_DEADLINE_SEC), "стенд не воспроизведён: лок не занят"
        return self

    def __exit__(self, *_exc: object) -> None:
        self.release.set()
        if self._thread is not None:
            self._thread.join(timeout=_JOIN_DEADLINE_SEC)


def _write_in_thread(channel: FileChannel, message: str) -> Dict[str, Any]:
    """Записать в daemon-потоке с дедлайном: зависание = падение, а не вечность."""
    box: Dict[str, Any] = {}

    def _run() -> None:
        box["result"] = channel.write(_record(message))

    thread = threading.Thread(target=_run, name="emitter", daemon=True)
    thread.start()
    thread.join(timeout=_JOIN_DEADLINE_SEC)
    assert not thread.is_alive(), "поток-эмитент завис на залипшем стоке — предела нет"
    return box["result"]


class TestStuckFileSinkDoesNotBlockTheEmitter:
    def test_write_returns_with_error_instead_of_hanging(self, tmp_path: Path) -> None:
        """Главное свойство задачи: эмитент возвращается, а не ждёт вечно."""
        channel = _file_channel(tmp_path, write_deadline_sec=0.05)
        try:
            with _StuckHolder(channel):
                result = _write_in_thread(channel, "не доедет")

            assert result["status"] == "error"
            assert channel.sink_writes_dropped == 1
        finally:
            channel.close()

    def test_drop_is_error_not_skipped(self, tmp_path: Path) -> None:
        """Статус именно ``error``: запись никуда не попала, и floor ошибок обязан
        это узнать. ``skipped`` означал бы «нам её и не надо», то есть тихую потерю."""
        channel = _file_channel(tmp_path, write_deadline_sec=0.05)
        try:
            with _StuckHolder(channel):
                result = _write_in_thread(channel, "потеря")

            assert result["status"] == "error"
            assert "занят" in result["error"]
        finally:
            channel.close()

    def test_healthy_write_never_hits_the_deadline(self, tmp_path: Path) -> None:
        """Обратная половина: на здоровом стоке предел не стоит ничего и не теряет."""
        channel = _file_channel(tmp_path)
        try:
            for i in range(50):
                assert channel.write(_record(f"строка {i}"))["status"] == "success"

            assert channel.sink_writes_dropped == 0
            assert channel.sink_degraded is False
            assert (tmp_path / "stuck.log").read_text(encoding="utf-8").count("строка") == 50
        finally:
            channel.close()


class TestBreakerOpensAndCloses:
    def test_channel_degrades_after_threshold(self, tmp_path: Path) -> None:
        """После N отказов подряд канал перестаёт ПЛАТИТЬ за ожидание.

        Без размыкателя процесс не виснет, но ползёт: четверть секунды за строку,
        пока сток стоит, — на кадровом логировании это хуже честного отказа.
        """
        channel = _file_channel(tmp_path, write_deadline_sec=0.05, degrade_after=2)
        try:
            with _StuckHolder(channel):
                _write_in_thread(channel, "1")
                assert channel.sink_degraded is False, "размыкание по ПЕРВОМУ отказу — дрожание"
                _write_in_thread(channel, "2")
                assert channel.sink_degraded is True

                started = time.monotonic()
                _write_in_thread(channel, "3")
                elapsed = time.monotonic() - started

            assert elapsed < channel._write_deadline_sec, (
                f"разомкнутый канал всё ещё ждёт: {elapsed:.3f} с при пределе {channel._write_deadline_sec}"
            )
            assert channel.sink_writes_dropped == 3
        finally:
            channel.close()

    def test_breaker_closes_when_the_sink_recovers(self, tmp_path: Path) -> None:
        """Возврат в строй бесплатен: отдельного таймера перепроверки нет,
        неблокирующая попытка в разомкнутом состоянии и есть проба."""
        channel = _file_channel(tmp_path, write_deadline_sec=0.05, degrade_after=1)
        try:
            with _StuckHolder(channel):
                _write_in_thread(channel, "отказ")
                assert channel.sink_degraded is True

            result = channel.write(_record("сток ожил"))

            assert result["status"] == "success"
            assert channel.sink_degraded is False, "канал остался разомкнутым при живом стоке"
            assert "сток ожил" in (tmp_path / "stuck.log").read_text(encoding="utf-8")
        finally:
            channel.close()


class TestThresholdsAreOperable:
    def test_deadline_comes_from_the_schema(self, tmp_path: Path) -> None:
        """Порог — операторский параметр, а не константа в коде.

        Измеряется ЭФФЕКТ (сколько реально ждали), а не значение поля: сверка
        поля с самим собой прошла бы и при полностью проигнорированной схеме.

        Порог взят ЗАВЕДОМО отличным от прежней константы (0.25): первая редакция
        просила 0.30 и проверяла ``>= 0.25`` — инъекция «жёсткая константа 0.25»
        оставляла её зелёной, то есть тест сторожил не операбельность, а сам факт
        ожидания.
        """
        channel = _file_channel(tmp_path, write_deadline_sec=0.60)
        try:
            with _StuckHolder(channel):
                started = time.monotonic()
                _write_in_thread(channel, "ждём дольше")
                elapsed = time.monotonic() - started

            assert elapsed >= 0.45, f"ждали {elapsed:.3f} с — порог из схемы не применён"
        finally:
            channel.close()

    def test_zero_deadline_means_do_not_wait(self, tmp_path: Path) -> None:
        """``0`` — «не ждать вовсе»: для стоков, где ожидание бессмысленно."""
        channel = _file_channel(tmp_path, write_deadline_sec=0.0)
        try:
            with _StuckHolder(channel):
                started = time.monotonic()
                result = _write_in_thread(channel, "мимо")
                elapsed = time.monotonic() - started

            assert result["status"] == "error"
            assert elapsed < 0.05, f"нулевой порог всё равно ждал {elapsed:.3f} с"
        finally:
            channel.close()

    def test_slow_write_is_counted_not_dropped(self, tmp_path: Path) -> None:
        """Предел стоит на ОЖИДАНИИ ОЧЕРЕДИ, а не на длительности самой записи:
        иначе медленный диск начал бы терять строки, и правка против потерь сама
        стала бы их источником."""
        channel = _file_channel(tmp_path, slow_write_sec=0.01)
        original = channel.handler.emit

        def _slow_emit(record: Any) -> None:
            time.sleep(0.03)
            original(record)

        channel.handler.emit = _slow_emit  # type: ignore[method-assign]
        try:
            result = channel.write(_record("медленно, но дошло"))

            assert result["status"] == "success"
            assert channel.sink_slow_writes == 1
            assert channel.sink_writes_dropped == 0
            assert channel.get_info()["max_write_sec"] >= 0.01
        finally:
            channel.handler.emit = original  # type: ignore[method-assign]
            channel.close()


class TestCountersReachTheOutside:
    def test_channel_info_carries_the_ladder(self, tmp_path: Path) -> None:
        channel = _file_channel(tmp_path, write_deadline_sec=0.05, degrade_after=1)
        try:
            with _StuckHolder(channel):
                _write_in_thread(channel, "потеря")

            info = channel.get_info()
            assert info["sink_writes_dropped"] == 1
            assert info["sink_degraded"] is True
        finally:
            channel.close()

    def test_manager_sums_over_all_sinks(self, tmp_path: Path) -> None:
        """Менеджер суммирует по реестру — и в сумму входит ФАЙЛОВЫЙ сток тоже.

        До Ф7.2 ключи назывались ``console_*``: сложив в них файловые потери,
        число врало бы по имени.
        """
        from multiprocess_framework.modules.logger_module.configs import LoggerManagerConfig
        from multiprocess_framework.modules.logger_module.core.logger_core import LoggerCore

        manager = LoggerCore(
            manager_name="LadderSum",
            config=LoggerManagerConfig(app_name="ladder", log_directory=str(tmp_path), channels={}, modules={}),
        )
        try:
            channel = _file_channel(tmp_path, write_deadline_sec=0.05)
            manager._channel_registry.register(channel)

            with _StuckHolder(channel):
                _write_in_thread(channel, "потеря")

            assert manager.get_stats()["sink_writes_dropped"] >= 1
        finally:
            manager.shutdown()


def test_hub_dropped_reaches_the_counters_facade() -> None:
    """Припаркованный долг: hub считал потери, а спросить о них было нельзя."""
    from multiprocess_framework.modules.process_module.managers.observability_reload import (
        observability_counters,
    )

    class _Hub:
        dropped = {"log": 3, "error": 0, "stats": 5}

    out = observability_counters(hub=_Hub())

    assert out["hub"]["dropped"] == {"log": 3, "error": 0, "stats": 5}
    assert out["hub"]["dropped_total"] == 8


@pytest.mark.parametrize("key", ["sink_writes_dropped", "sink_slow_writes"])
def test_keys_are_in_the_published_registry(key: str) -> None:
    """Счётчик, которого нет в реестре публикации, существует и при этом невидим."""
    from multiprocess_framework.modules.process_module.managers.observability_reload import (
        PLANE_COUNTER_KEYS,
    )

    assert key in PLANE_COUNTER_KEYS
