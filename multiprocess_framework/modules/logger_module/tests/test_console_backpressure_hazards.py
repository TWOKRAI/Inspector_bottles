# -*- coding: utf-8 -*-
"""R2 — внутренние опасности предела ожидания консоли (АВТОРСКИЕ тесты).

Контрактную сторону (предел, статус отказа, счётчики, троттл, отсутствие
регресса на здоровой консоли) закрывает независимый тестировщик —
``test_console_backpressure.py``. Здесь то, что видно только автору: чем
именно сделан предел и что из этого следует.

Механизм: один лок на запись, взятие с таймаутом, второй лок на счётчики,
троттл по монотонным часам. Отсюда опасности:

  1. **Статистику должно быть можно спросить у застрявшего канала.** Если бы
     ``get_info`` брал тот же лок, что и запись, диагностика была бы недоступна
     ровно в тот момент, когда она нужна: «почему молчит консоль» осталось бы
     без ответа, потому что вопрос повис бы на том же локе.
  2. **Отброс — это НЕ доставка.** Статус отброшенной записи обязан быть
     ``error``: на нём завязан пол ошибок (Ф0.9). Пометить ``skipped`` —
     значит сказать вышестоящему слою «всё в порядке» про потерянную ошибку.
  3. **Затык консоли не отбирает файловые каналы.** Консоль — удобство,
     файл — свидетельство. Пока падает первое, второе обязано работать.
  4. **Троттл гасит текст, а не учёт.** Тот же класс, что в Ф0.4 и Ф0.7:
     заглушённое предупреждение не должно означать «потерь больше нет».
  5. **Медленная, но живая консоль — не повод терять запись.** Предел стоит
     на ОЖИДАНИИ очереди, а не на длительности самой записи; иначе на
     медленном терминале начались бы потери на ровном месте.
  6. **Порог «медленно» не срабатывает на здоровой записи.** Счётчик, который
     растёт всегда, не сигнал.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any, Dict, List

import pytest

from multiprocess_framework.modules.logger_module.channels.log_channel import ConsoleChannel
from multiprocess_framework.modules.logger_module.core.log_config import (
    LoggerChannelSchema,
    LoggerManagerConfig,
    LoggerScopeSchema,
)
from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager

_LOGGER_NAME = "multiprocess_framework.modules.logger_module.channels.log_channel"


class _StuckStream:
    """Поток вывода, зависший навсегда до явного ``release()``."""

    def __init__(self) -> None:
        self._gate = threading.Event()
        self.entered = threading.Event()

    def write(self, data: str) -> int:
        self.entered.set()
        self._gate.wait()
        return len(data)

    def flush(self) -> None:
        pass

    def release(self) -> None:
        self._gate.set()


class _SlowStream:
    """Живой, но медленный поток вывода: запись возвращается, просто не сразу."""

    def __init__(self, delay_sec: float) -> None:
        self.delay_sec = delay_sec
        self.written: List[str] = []

    def write(self, data: str) -> int:
        time.sleep(self.delay_sec)
        self.written.append(data)
        return len(data)

    def flush(self) -> None:
        pass


def _record(message: str, level: str = "INFO") -> Dict[str, Any]:
    return {
        "module": "hazard_probe",
        "level": level,
        "message": message,
        "timestamp": time.time(),
        "extra": {},
    }


def _console(stream: Any) -> ConsoleChannel:
    channel = ConsoleChannel(LoggerChannelSchema(name="console", type="console", enabled=True, format="%(message)s"))
    channel.handler.stream = stream
    return channel


def _write_with_deadline(channel: ConsoleChannel, record: Dict[str, Any], timeout: float = 3.0) -> Dict[str, Any]:
    """Записать в канал из daemon-потока и потребовать возврата за ``timeout``.

    Прямой вызов в главном потоке здесь запрещён: если предел ожидания снят
    (регресс), запись не вернётся НИКОГДА — прогон повиснет вместо того, чтобы
    покраснеть. Тест, который вешает сборку, не сообщает о поломке, а прячет
    её: это выяснилось на проверке «красный без правки», где первый же слом
    убил весь прогон по таймауту вместо девяти внятных падений.
    """
    holder: Dict[str, Any] = {}
    thread = threading.Thread(target=lambda: holder.update(result=channel.write(record)), daemon=True)
    thread.start()
    thread.join(timeout=timeout)
    assert not thread.is_alive(), f"write() не вернулся за {timeout}с — предел ожидания консоли не сработал"
    return holder["result"]


def _occupy(channel: ConsoleChannel, stream: _StuckStream) -> threading.Thread:
    """Занять канал навсегда первым потоком и дождаться, что он реально вошёл в запись."""
    thread = threading.Thread(target=channel.write, args=(_record("occupier"),), daemon=True)
    thread.start()
    assert stream.entered.wait(timeout=2.0), "поток-захватчик не вошёл в write() консоли"
    return thread


# =============================================================================
# 1. Диагностика доступна у застрявшего канала
# =============================================================================


def test_stats_readable_while_console_is_stuck() -> None:
    """``get_info()`` обязан ответить, пока другой поток заблокирован в записи.

    Это главная причина ДВУХ локов вместо одного. С общим локом вопрос «что с
    консолью» повис бы на том же затыке, который и хотят диагностировать, —
    механизм наблюдаемости стал бы недоступен ровно в час нужды.
    """
    stream = _StuckStream()
    channel = _console(stream)
    try:
        _occupy(channel, stream)

        answered = threading.Event()
        info: Dict[str, Any] = {}

        def _ask() -> None:
            info.update(channel.get_info())
            answered.set()

        threading.Thread(target=_ask, daemon=True).start()

        assert answered.wait(timeout=2.0), "get_info() повис на застрявшем канале — диагностика недоступна"
        assert "console_writes_dropped" in info
    finally:
        stream.release()


# =============================================================================
# 2. Отброс — не доставка: пол ошибок обязан сработать
# =============================================================================


def test_dropped_error_reaches_the_floor(tmp_path: Path) -> None:
    """Консоль — единственный приёмник и она застряла → ошибка уходит в пол (Ф0.9).

    Смысл статуса ``error`` у отброшенной записи именно в этом. Пометь мы её
    ``skipped``, ``_channel_accepted`` счёл бы приёмник рабочим, floor не
    сработал бы, и ошибка исчезла бы молча — то есть предел ожидания чинил бы
    одну потерю, создавая другую.
    """
    mgr = LoggerManager(
        manager_name="FloorProbe",
        config=LoggerManagerConfig.model_validate(
            {
                "log_directory": str(tmp_path),
                "enable_batching": False,
                "modules": {},
                "channels": {"console": {"type": "console", "enabled": True, "format": "%(message)s"}},
                "scopes": {"SYSTEM": {"enabled": True, "min_level": "WARNING", "channels": ["console"]}},
            }
        ),
    )
    mgr.initialize()
    stream = _StuckStream()
    try:
        console = mgr.get_channel("console")
        assert console is not None
        console.handler.stream = stream
        _occupy(console, stream)

        victim = threading.Thread(
            target=mgr.error, args=("ошибка при застрявшей консоли",), kwargs={"module": "hazard_probe"}, daemon=True
        )
        victim.start()
        victim.join(timeout=3.0)
        assert not victim.is_alive(), "поток-эмитент не вернулся — предел ожидания не сработал"

        stats = mgr.get_stats()
        assert stats["console_writes_dropped"] >= 1
        assert stats["errors_to_floor"] >= 1, (
            "ошибка, которую не принял ни один канал, обязана уйти в пол; "
            f"получено stats={ {k: v for k, v in stats.items() if 'floor' in k or 'console' in k} }"
        )
    finally:
        stream.release()
        mgr.shutdown()


# =============================================================================
# 3. Затык консоли не отбирает файловые каналы
# =============================================================================


def test_file_channel_still_writes_while_console_is_stuck(tmp_path: Path) -> None:
    """Консоль потеряна — файл обязан получить запись.

    Иначе один заткнувшийся приёмник уносил бы с собой всю плоскость: консоль
    это удобство, файл — свидетельство, и терять их вместе нельзя.
    """
    mgr = LoggerManager(
        manager_name="FileSurvivesProbe",
        config=LoggerManagerConfig.model_validate(
            {
                "log_directory": str(tmp_path),
                "enable_batching": False,
                "modules": {},
                "channels": {
                    "console": {"type": "console", "enabled": True, "format": "%(message)s"},
                    "system_file": {
                        "type": "file",
                        "enabled": True,
                        "file_path": "system.log",
                        "format": "%(message)s",
                    },
                },
                "scopes": {
                    "SYSTEM": {
                        "enabled": True,
                        "min_level": "WARNING",
                        "channels": ["console", "system_file"],
                    }
                },
            }
        ),
    )
    mgr.initialize()
    stream = _StuckStream()
    try:
        console = mgr.get_channel("console")
        assert console is not None
        console.handler.stream = stream
        _occupy(console, stream)

        victim = threading.Thread(
            target=mgr.error, args=("должно долететь до файла",), kwargs={"module": "hazard_probe"}, daemon=True
        )
        victim.start()
        victim.join(timeout=3.0)
        assert not victim.is_alive(), "поток-эмитент не вернулся"

        mgr.flush()
        assert "должно долететь до файла" in (tmp_path / "system.log").read_text(encoding="utf-8"), (
            "застрявшая консоль забрала с собой файловый канал"
        )
    finally:
        stream.release()
        mgr.shutdown()


# =============================================================================
# 4. Троттл гасит текст, а не учёт
# =============================================================================


def test_counter_grows_after_warning_is_silenced() -> None:
    """Пять отбросов подряд: один WARNING, но счётчик — пять.

    Заглушённое предупреждение не должно означать «потерь больше нет».
    """
    stream = _StuckStream()
    channel = _console(stream)
    try:
        _occupy(channel, stream)

        results: List[Dict[str, Any]] = []
        for i in range(5):
            results.append(_write_with_deadline(channel, _record(f"drop-{i}")))

        assert all(r["status"] == "error" for r in results)
        assert channel.console_writes_dropped == 5, (
            f"учёт отбросов заглушён вместе с текстом: {channel.console_writes_dropped} вместо 5"
        )
        assert channel.get_info()["console_writes_dropped"] == 5
    finally:
        stream.release()


def test_warning_is_emitted_once_per_interval(caplog: pytest.LogCaptureFixture) -> None:
    """Текст предупреждения — один раз за интервал, а не на каждый отброс.

    Интервал сдвигается ЧЕРЕЗ АТРИБУТ ЭКЗЕМПЛЯРА, а не патчем ``time.monotonic``:
    глобально подменённые часы с конечным side_effect доедают соседние потоки и
    дают StopIteration в невиновном тесте (урок прошлых фаз).
    """
    stream = _StuckStream()
    channel = _console(stream)
    try:
        _occupy(channel, stream)

        with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
            for i in range(3):
                _write_with_deadline(channel, _record(f"first-wave-{i}"))
            first_wave = len([r for r in caplog.records if r.levelno == logging.WARNING])

            # Интервал «истёк» — не трогая глобальные часы.
            channel._WARNING_INTERVAL_SEC = 0.0
            _write_with_deadline(channel, _record("second-wave"))
            second_wave = len([r for r in caplog.records if r.levelno == logging.WARNING])

        assert first_wave == 1, f"три отброса подряд дали {first_wave} предупреждений вместо одного"
        assert second_wave == first_wave + 1, "по истечении интервала предупреждение обязано прозвучать снова"
    finally:
        stream.release()


# =============================================================================
# 5-6. Медленная живая консоль: считается, но не теряется
# =============================================================================


def test_slow_but_alive_console_is_counted_not_dropped() -> None:
    """Запись длиннее порога «медленно», но короче предела ожидания.

    Предел стоит на ОЖИДАНИИ ОЧЕРЕДИ, а не на длительности самой записи.
    Стой он на длительности — медленный терминал начал бы терять строки, и
    правка против потерь сама стала бы их источником.
    """
    stream = _SlowStream(delay_sec=ConsoleChannel._SLOW_WRITE_SEC * 2)
    channel = _console(stream)

    result = channel.write(_record("медленно, но дошло"))

    assert result["status"] == "success", "живая медленная запись не должна отбрасываться"
    assert "медленно, но дошло" in "".join(stream.written)
    assert channel.console_slow_writes == 1, "медленная запись обязана быть замечена"
    assert channel.console_writes_dropped == 0
    assert channel.get_info()["max_write_sec"] >= ConsoleChannel._SLOW_WRITE_SEC


def test_healthy_write_is_not_counted_as_slow() -> None:
    """Счётчик, который растёт всегда, — не сигнал, а шум."""
    stream = _SlowStream(delay_sec=0.0)
    channel = _console(stream)

    for i in range(50):
        assert channel.write(_record(f"fast-{i}"))["status"] == "success"

    assert channel.console_slow_writes == 0, "здоровые записи попали в «медленные» — порог не работает"
    assert channel.console_writes_dropped == 0


def test_manager_stats_sum_over_channels(tmp_path: Path) -> None:
    """Менеджер отдаёт СУММУ по каналам, а не копию счётчика у себя.

    Копия разъезжается при пересоздании канала (``logger.sink.disable`` →
    ``enable``, ``reconfigure``): менеджер продолжал бы показывать старое
    число от давно закрытого объекта. Сумма по живому реестру такого класса
    ошибок не имеет.
    """
    mgr = LoggerManager(
        manager_name="SumProbe",
        config=LoggerManagerConfig.model_validate(
            {
                "log_directory": str(tmp_path),
                "enable_batching": False,
                "modules": {},
                "channels": {"console": {"type": "console", "enabled": True, "format": "%(message)s"}},
                "scopes": {"SYSTEM": LoggerScopeSchema(enabled=True, min_level="WARNING", channels=["console"])},
            }
        ),
    )
    mgr.initialize()
    try:
        assert mgr.get_stats()["console_writes_dropped"] == 0
        console = mgr.get_channel("console")
        assert console is not None
        console.console_writes_dropped = 7

        assert mgr.get_stats()["console_writes_dropped"] == 7, "менеджер не видит счётчик живого канала"

        # Канал ушёл из реестра — вместе с ним обязано уйти и его число.
        mgr.set_sink_enabled("console", False)
        assert mgr.get_stats()["console_writes_dropped"] == 0, (
            "менеджер показывает счётчик снятого канала — значит держит копию, а не сумму"
        )
    finally:
        mgr.shutdown()
