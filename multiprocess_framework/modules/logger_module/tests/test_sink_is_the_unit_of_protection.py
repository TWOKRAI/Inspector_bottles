# -*- coding: utf-8 -*-
"""Единица защиты лесенки — СТОК, а не канал (Ф7.х, блокеры B-1 и B-2).

Сквозное ревью Ф7 воспроизвело инвертированную посылку спеки Ф7.2. Она гласила:
«каналы, делящие файл, делят один лок, поэтому лесенка достаётся им всем». На
деле делят они **хэндлер** (``acquire_shared_rotating_handler``), а лок был у
каждого канала свой — то есть на боевой раскладке (``messages_file`` +
``router_messages`` → один ``messages.log``) залипший диск отнимал по потоку на
КАЖДЫЙ канал: первый честно ждал предел и терял запись, второй входил в тот же
``stream.write`` без предела вообще. Живая приёмка «0 тактов против 65» ставилась
на ОДНОМ канале — ровно там, где дефект невидим.

Здесь сторожатся обе половины находки:

  * **B-1a** предел ожидания достаётся ВТОРОМУ каналу того же файла;
  * **B-1b** межканальная сериализация: два потока не входят в ``emit`` одного
    хэндлера одновременно (``handler.emit`` зовётся мимо ``Handler.handle``,
    поэтому лок обязаны брать мы);
  * **B-2** ``sink_degraded`` и разбивка потерь по имени стока доезжают до
    ``get_stats`` менеджера — то есть спрашиваются снаружи, а не только у
    ``get_info`` живого канала.

Каждый тест, способный заблокироваться, крутит запись в daemon-потоке с дедлайном
join: тест, который вешает прогон вместо падения, хуже отсутствующего.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Dict, List

from multiprocess_framework.modules.logger_module.channels.log_channel import (
    FileChannel,
    _reset_shared_handler_registry,
)
from multiprocess_framework.modules.logger_module.configs.logger_manager_config import (
    LoggerChannelSchema,
)
from multiprocess_framework.modules.logger_module.core.log_config import LogLevel

_JOIN_DEADLINE_SEC = 5.0


def _shared_file_channel(path: Path, name: str, **overrides: Any) -> FileChannel:
    """Канал на ОБЩЕМ rotating-хэндлере — та самая боевая раскладка."""
    cfg = LoggerChannelSchema(
        name=name,
        type="file",
        enabled=True,
        file_path=str(path),
        rotate=True,
        max_size=10 * 1024 * 1024,
        backup_count=3,
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


def _write_in_thread(channel: FileChannel, message: str) -> Dict[str, Any]:
    box: Dict[str, Any] = {}
    thread = threading.Thread(target=lambda: box.update(result=channel.write(_record(message))), daemon=True)
    thread.start()
    thread.join(timeout=_JOIN_DEADLINE_SEC)
    assert not thread.is_alive(), "поток-эмитент завис на залипшем стоке — предела нет"
    return box["result"]


class TestTheDeadlineReachesEveryChannelOfTheSink:
    """B-1a: залип ФАЙЛ — предел платят все его каналы, а не первый вошедший."""

    def test_second_channel_of_the_same_file_also_hits_the_deadline(self, tmp_path: Path) -> None:
        """Сердце блокера. Держим сток через канал А — теряет и канал Б.

        До правки: Б висел без предела вообще, его ``sink_writes_dropped``
        оставался нулём, ``sink_degraded`` — False, то есть счётчики показывали
        здоровье в момент, когда поток уже был потерян навсегда.
        """
        _reset_shared_handler_registry()
        path = tmp_path / "messages.log"
        a = _shared_file_channel(path, "messages_file", write_deadline_sec=0.05, degrade_after=2)
        b = _shared_file_channel(path, "router_messages", write_deadline_sec=0.05, degrade_after=2)
        try:
            assert a.handler is b.handler, "стенд не воспроизведён: хэндлер не общий"

            entered = threading.Event()
            release = threading.Event()

            def _hold() -> None:
                with a._write_lock:
                    entered.set()
                    release.wait(timeout=30.0)

            holder = threading.Thread(target=_hold, name="stuck-sink", daemon=True)
            holder.start()
            assert entered.wait(timeout=_JOIN_DEADLINE_SEC), "стенд не воспроизведён: лок стока не занят"

            result = _write_in_thread(b, "второй канал того же файла")

            assert result["status"] == "error", "второй канал не увидел предела — лок не у стока"
            assert b.sink_writes_dropped == 1
        finally:
            release.set()
            holder.join(timeout=_JOIN_DEADLINE_SEC)
            a.close()
            b.close()
            _reset_shared_handler_registry()

    def test_channels_of_the_same_file_share_one_lock(self, tmp_path: Path) -> None:
        """Механизм назван прямо: общий хэндлер ⇒ общий лок.

        Свойство проверяется и предыдущим тестом по наблюдаемому следствию;
        здесь — по устройству, потому что подмена лока обратно на частный даёт
        именно эту разницу, и увидеть её лучше сразу.
        """
        _reset_shared_handler_registry()
        path = tmp_path / "messages.log"
        a = _shared_file_channel(path, "messages_file")
        b = _shared_file_channel(path, "router_messages")
        other = _shared_file_channel(tmp_path / "errors.log", "errors_file")
        try:
            assert a._write_lock is b._write_lock, "каналы одного файла не делят лок стока"
            assert a._write_lock is not other._write_lock, "каналы РАЗНЫХ файлов делят лок — лишняя сериализация"
        finally:
            a.close()
            b.close()
            other.close()
            _reset_shared_handler_registry()

    def test_two_threads_are_never_inside_one_sink_at_the_same_time(self, tmp_path: Path) -> None:
        """B-1b: межканальная сериализация записи на общем файле.

        ``FileChannel`` зовёт ``handler.emit`` мимо ``Handler.handle``, поэтому
        stdlib свой лок за нас не берёт — до правки два потока оказывались внутри
        одного ``stream.write`` одновременно. Ловим это счётчиком одновременности
        внутри самой записи.
        """
        _reset_shared_handler_registry()
        path = tmp_path / "messages.log"
        a = _shared_file_channel(path, "messages_file", write_deadline_sec=2.0)
        b = _shared_file_channel(path, "router_messages", write_deadline_sec=2.0)
        try:
            inside = 0
            max_inside = 0
            probe_lock = threading.Lock()
            original_write = a.handler.stream.write

            def _counting_write(data: str) -> int:
                nonlocal inside, max_inside
                with probe_lock:
                    inside += 1
                    max_inside = max(max_inside, inside)
                # Окно, в котором пересечение было бы видно: без сериализации
                # второй поток войдёт сюда же.
                time.sleep(0.002)
                with probe_lock:
                    inside -= 1
                return original_write(data)

            a.handler.stream.write = _counting_write  # type: ignore[method-assign]

            threads = [
                threading.Thread(target=lambda ch=ch, i=i: ch.write(_record(f"{ch.name}-{i}")), daemon=True)
                for i in range(20)
                for ch in (a, b)
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=_JOIN_DEADLINE_SEC)
                assert not thread.is_alive(), "поток не вернулся — сток заблокирован"

            assert max_inside == 1, f"в один сток одновременно вошло {max_inside} потоков — сериализации нет"
        finally:
            a.close()
            b.close()
            _reset_shared_handler_registry()


class TestOperatorCanTellWhoIsLosingAndWhetherItIsNow:
    """B-2: два пункта приёмки Ф7.2, невыполненные при закрытой задаче."""

    def _manager(self, tmp_path: Path):
        from multiprocess_framework.modules.logger_module.core.log_config import (
            LoggerManagerConfig,
            LoggerScopeSchema,
        )
        from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager

        config = LoggerManagerConfig(
            app_name="b2",
            log_directory=str(tmp_path),
            channels={
                "stuck_file": LoggerChannelSchema(
                    name="stuck_file",
                    type="file",
                    enabled=True,
                    file_path=str(tmp_path / "stuck.log"),
                    rotate=False,
                    format="%(message)s",
                    write_deadline_sec=0.02,
                    degrade_after=2,
                ),
            },
            scopes={"system": LoggerScopeSchema(level="DEBUG", channels=["stuck_file"])},
        )
        return LoggerManager(manager_name="B2Logger", config=config)

    def test_stats_name_the_degraded_sink_and_the_owner_of_the_losses(self, tmp_path: Path) -> None:
        """Оператор спрашивает МЕНЕДЖЕРА и получает адрес, а не только сумму.

        До правки ``get_stats`` отдавал ``sink_writes_dropped=4`` и молчал о том,
        чьи это потери и продолжаются ли они прямо сейчас; ``sink_degraded`` жил
        только в ``get_info`` канала, куда команды наблюдаемости не ходят.
        """
        manager = self._manager(tmp_path)
        try:
            channel = manager._channel_registry.get("stuck_file")
            assert channel is not None

            entered = threading.Event()
            release = threading.Event()

            def _hold() -> None:
                with channel._write_lock:
                    entered.set()
                    release.wait(timeout=30.0)

            holder = threading.Thread(target=_hold, daemon=True)
            holder.start()
            assert entered.wait(timeout=_JOIN_DEADLINE_SEC), "стенд не воспроизведён"

            for i in range(3):
                _write_in_thread(channel, f"потеря-{i}")

            stats = manager.get_stats()
            assert stats["sink_writes_dropped"] == 3
            assert stats["sink_writes_dropped_by_channel"] == {"stuck_file": 3}, "потери без адреса"
            assert stats["sink_degraded"] is True, "разомкнутый сток не виден снаружи"
            assert stats["sink_degraded_channels"] == ["stuck_file"]
        finally:
            release.set()
            holder.join(timeout=_JOIN_DEADLINE_SEC)
            manager.shutdown()

    def test_breakdown_survives_sink_disable(self, tmp_path: Path) -> None:
        """Разбивка переезжает вместе с суммой, когда канал снимают.

        ``sink.disable`` жмут ВО ВРЕМЯ разбора инцидента — тот же класс «7 →
        disable → 0», который уже стоил проекту починки суммарного счётчика.
        Разбивка, живущая только на живых каналах, повторила бы его.
        """
        manager = self._manager(tmp_path)
        try:
            channel = manager._channel_registry.get("stuck_file")
            entered = threading.Event()
            release = threading.Event()

            def _hold() -> None:
                with channel._write_lock:
                    entered.set()
                    release.wait(timeout=30.0)

            holder = threading.Thread(target=_hold, daemon=True)
            holder.start()
            assert entered.wait(timeout=_JOIN_DEADLINE_SEC)
            for i in range(2):
                _write_in_thread(channel, f"потеря-{i}")
            release.set()
            holder.join(timeout=_JOIN_DEADLINE_SEC)

            manager.set_sink_enabled("stuck_file", False)
            stats = manager.get_stats()

            assert stats["sink_writes_dropped"] == 2, "сумма не пережила снятие канала"
            assert stats["sink_writes_dropped_by_channel"] == {"stuck_file": 2}, "разбивка не пережила снятие канала"
        finally:
            release.set()
            manager.shutdown()

    def test_healthy_manager_reports_keys_with_empty_values_not_missing_keys(self, tmp_path: Path) -> None:
        """«Ключа нет» и «потерь нет» — разные факты; потребитель их не должен путать."""
        manager = self._manager(tmp_path)
        try:
            manager.log("system", LogLevel.INFO, "здоровая запись", module="unit")
            stats = manager.get_stats()

            assert stats["sink_writes_dropped_by_channel"] == {}
            assert stats["sink_degraded"] is False
            assert stats["sink_degraded_channels"] == []
        finally:
            manager.shutdown()


def test_channels_without_a_sink_keep_their_private_lock(tmp_path: Path) -> None:
    """Граница названа: у кольца в памяти конкурировать не за что.

    Общий лок им не нужен и был бы вреден — два независимых ``MemoryChannel``
    сериализовались бы друг о друга без всякой причины.
    """
    from multiprocess_framework.modules.logger_module.channels.log_channel import MemoryChannel

    first = MemoryChannel(LoggerChannelSchema(name="ring", type="memory", enabled=True, capacity=8))
    second = MemoryChannel(LoggerChannelSchema(name="ring2", type="memory", enabled=True, capacity=8))
    assert first._write_lock is not second._write_lock


def test_poll_of_a_stuck_sink_does_not_lose_the_healthy_neighbour(tmp_path: Path) -> None:
    """Затык одного файла не отбирает записи у другого файла.

    Обратная половина B-1: сериализация обязана быть ВНУТРИ стока, а не между
    стоками. Проверяем, что общий механизм не свёл всё к одному глобальному локу.
    """
    _reset_shared_handler_registry()
    stuck = _shared_file_channel(tmp_path / "stuck.log", "stuck_file", write_deadline_sec=0.02)
    healthy = _shared_file_channel(tmp_path / "healthy.log", "healthy_file")
    try:
        entered = threading.Event()
        release = threading.Event()

        def _hold() -> None:
            with stuck._write_lock:
                entered.set()
                release.wait(timeout=30.0)

        holder = threading.Thread(target=_hold, daemon=True)
        holder.start()
        assert entered.wait(timeout=_JOIN_DEADLINE_SEC)

        written: List[str] = []
        for i in range(5):
            assert healthy.write(_record(f"жив-{i}"))["status"] == "success"
            written.append(f"жив-{i}")
        assert healthy.sink_writes_dropped == 0
    finally:
        release.set()
        holder.join(timeout=_JOIN_DEADLINE_SEC)
        stuck.close()
        healthy.close()
        _reset_shared_handler_registry()


class TestControlPathIsNotLimitedByTheSink:
    """Ф7.х.2 (блокер верификации корзины): управляющий путь не делит лок с лесенкой.

    Первая редакция B-1 посадила лесенку на ``handler.lock`` — тот самый объект,
    который stdlib берёт БЕЗ предела в ``close()``, ``flush()`` и
    ``logging.shutdown()``. Итог: залипший сток вешал ``logger.sink.disable`` —
    команду, которой оператор этот сток и лечит, — а также ``config.reload`` и
    выход из процесса. Здесь сторожится развязка: лок лесенки и лок stdlib —
    РАЗНЫЕ объекты, и ``close()`` возвращается, пока сток держит чужой поток.
    """

    def test_ladder_lock_is_not_the_stdlib_handler_lock(self, tmp_path: Path) -> None:
        """Устройство: наш лок стока ≠ ``handler.lock`` stdlib."""
        _reset_shared_handler_registry()
        ch = _shared_file_channel(tmp_path / "messages.log", "messages_file")
        try:
            assert ch._write_lock is not ch.handler.lock, (
                "лесенка на stdlib-локе: close()/flush()/shutdown() будут ждать за нашим дедлайном без предела"
            )
        finally:
            ch.close()
            _reset_shared_handler_registry()

    def test_close_returns_while_the_sink_is_held(self, tmp_path: Path) -> None:
        """Сердце находки: снятие канала возвращается на залипшем стоке.

        Держим лок СТОКА чужим потоком (модель залипшего write) и закрываем оба
        канала файла — включая последнего владельца, чей ``close()`` физически
        закрывает хэндлер через stdlib. До правки последний ``close()`` вставал
        на ``handler.lock`` навсегда; тест-предшественник этого не видел, потому
        что расклеивал сток ДО снятия (находка Н-5 верификации).
        """
        _reset_shared_handler_registry()
        path = tmp_path / "messages.log"
        a = _shared_file_channel(path, "messages_file", write_deadline_sec=0.05)
        b = _shared_file_channel(path, "router_messages", write_deadline_sec=0.05)
        entered = threading.Event()
        release = threading.Event()

        def _hold() -> None:
            with a._write_lock:
                entered.set()
                release.wait(timeout=30.0)

        holder = threading.Thread(target=_hold, name="stuck-sink", daemon=True)
        holder.start()
        try:
            assert entered.wait(timeout=_JOIN_DEADLINE_SEC), "стенд не воспроизведён: лок стока не занят"

            closed = threading.Event()

            def _close_both() -> None:
                b.close()
                a.close()  # последний владелец: физическое закрытие хэндлера stdlib'ом
                closed.set()

            closer = threading.Thread(target=_close_both, name="sink-disable", daemon=True)
            closer.start()
            assert closed.wait(timeout=_JOIN_DEADLINE_SEC), (
                "close() встал на залипшем стоке — управляющий путь делит лок с лесенкой"
            )
        finally:
            release.set()
            holder.join(timeout=_JOIN_DEADLINE_SEC)
            _reset_shared_handler_registry()
