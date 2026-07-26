# -*- coding: utf-8 -*-
"""Ф0.3 — счётчики потерь доезжают наружу, а не остаются внутри менеджера.

План: plans/observability-unified-routing.md, задача 0.3 (резидуал R4).

Зачем отдельный файл. Счётчик, который считается правильно, но которого никто
не может спросить, — это не наблюдаемость. На этом проекте класс уже стрелял
дважды: правило читало несуществующий ключ ``drops_count`` при реальном
``drops``, и 23% ошибок отправки были невидимы при зелёных тестах на моке.
Поэтому здесь проверяется не арифметика (она в
``channel_routing_module/tests/test_batch_buffer_limits.py``), а маршрут:

    BatchBuffer.stats → LoggerCore.get_stats() → observability_counters()

— то есть ровно то, что отдаёт наружу команда ``introspect.observability``.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List

import pytest

from multiprocess_framework.modules.logger_module.channels.log_channel import LogChannel
from multiprocess_framework.modules.logger_module.core.error_floor import reset_error_floors
from multiprocess_framework.modules.logger_module.core.log_config import (
    LoggerChannelSchema,
    LoggerManagerConfig,
    LoggerScopeSchema,
)
from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager
from multiprocess_framework.modules.process_module.managers.observability_reload import (
    observability_counters,
)


@pytest.fixture(autouse=True)
def _isolate_floors() -> Iterator[None]:
    reset_error_floors()
    yield
    reset_error_floors()


def _config(tmp_path: Path, *, max_pending: int) -> LoggerManagerConfig:
    """Логгер, у которого сток заведомо не разгребает: пачка только копится."""
    return LoggerManagerConfig(
        app_name="counters_unit",
        log_directory=str(tmp_path),
        enable_batching=True,
        batch_size=10_000,  # сброс по заполнению не сработает
        batch_interval=600.0,  # и по времени тоже
        batch_max_pending=max_pending,
        modules={},
        channels={
            "system_file": LoggerChannelSchema(
                name="system_file", type="file", enabled=True, file_path="system.log", rotate=False
            )
        },
        scopes={
            scope: LoggerScopeSchema(enabled=True, min_level="DEBUG", channels=["system_file"])
            for scope in ("SYSTEM", "BUSINESS", "DEBUG")
        },
    )


@contextmanager
def _logger(tmp_path: Path, *, max_pending: int) -> Iterator[LoggerManager]:
    manager = LoggerManager(manager_name="CountersLogger", config=_config(tmp_path, max_pending=max_pending))
    try:
        yield manager
    finally:
        manager.shutdown()


def _overflow(manager: LoggerManager, count: int) -> None:
    for i in range(count):
        manager.info(f"переполняем буфер {i}", module="unit")


class _StuckChannel(LogChannel):
    """Канал, залипший на записи — модель медленного/подвисшего приёмника.

    Наследует ``LogChannel``, а не утиный тип: ``ChannelRegistry.register``
    проверяет ``isinstance(channel, IChannel)`` и утку молча отвергает.
    """

    def __init__(self, name: str = "system_file") -> None:
        super().__init__(LoggerChannelSchema(name=name, type="console", enabled=True))
        self.entered = threading.Event()
        self.release = threading.Event()
        self.writes: List[Dict[str, Any]] = []

    def write(self, record: Dict[str, Any]) -> Dict[str, Any]:
        self.entered.set()
        self.release.wait(timeout=10.0)
        self.writes.append(record)
        return {"status": "success", "channel": self.name}


@contextmanager
def _stuck_sink(manager: LoggerManager) -> Iterator[_StuckChannel]:
    """Подменить system_file залипшим каналом и занять его сброс."""
    manager._channel_registry.unregister("system_file")
    channel = _StuckChannel()
    manager._channel_registry.register(channel)

    manager.info("первая запись — она и залипнет", module="unit")
    drainer = threading.Thread(target=lambda: manager.flush(), name="drainer")
    drainer.start()
    assert channel.entered.wait(timeout=10.0), "сток не занят — сценарий не воспроизведён"
    try:
        yield channel
    finally:
        channel.release.set()
        drainer.join(timeout=10.0)


# =============================================================================
# Потери буфера
# =============================================================================


def test_dropped_by_channel_reaches_get_stats(tmp_path: Path) -> None:
    """Потеря названа в get_stats() менеджера, с именем канала-виновника.

    Сценарий приёмки: сток ЗАЛИП (а не «потолок ниже пачки») — именно так
    выглядит медленный приёмник на живой системе.
    """
    with _logger(tmp_path, max_pending=5) as manager:
        with _stuck_sink(manager):
            _overflow(manager, 50)

            batch_stats = manager.get_stats()["batch_stats"]
            assert batch_stats["dropped"] == 45
            assert batch_stats["dropped_by_channel"] == {"system_file": 45}
            assert batch_stats["pending"]["system_file"] == 5


def test_dead_sink_is_reported_as_flush_failed_not_as_delivered(tmp_path: Path) -> None:
    """Сток не принял — это не «доставлено».

    До правки: приёмники сняты, 51 запись числится доставленной, ноль байт на
    диске, все счётчики молчат. Диагностическая команда рапортовала здоровую
    плоскость при стопроцентной потере.
    """
    with _logger(tmp_path, max_pending=10_000) as manager:
        manager.set_sink_enabled("system_file", False)
        _overflow(manager, 50)
        manager.flush()

        batch_stats = manager.get_stats()["batch_stats"]
        assert batch_stats["total_flushed"] == 0
        assert batch_stats["flush_failed"] == 50
        assert batch_stats["flush_failed_by_channel"] == {"system_file": 50}


def test_healthy_logger_reports_zero_drops(tmp_path: Path) -> None:
    """Обратная половина: без переполнения счётчик молчит (нулём, а не отсутствием)."""
    with _logger(tmp_path, max_pending=10_000) as manager:
        _overflow(manager, 50)

        batch_stats = manager.get_stats()["batch_stats"]
        assert batch_stats["dropped"] == 0
        assert batch_stats["dropped_by_channel"] == {}


def test_counters_facade_normalizes_buffer_key(tmp_path: Path) -> None:
    """``observability_counters`` отдаёт буфер под одним именем для всех плоскостей.

    Логгер держит его в ``batch_stats`` (свой ручной словарь), статистика —
    в ``buffer`` (от ChannelRoutingManager). Потребитель команды не должен
    знать, какой из двух менеджеров он спрашивает.
    """
    with _logger(tmp_path, max_pending=5) as manager:
        with _stuck_sink(manager):
            _overflow(manager, 50)

            counters = observability_counters(logger=manager)
            assert set(counters) == {"logger"}
            assert counters["logger"]["buffer"]["dropped_by_channel"] == {"system_file": 45}


def test_counters_facade_survives_a_broken_manager() -> None:
    """Сломанный get_stats() не должен ронять диагностическую команду."""

    class _Broken:
        def get_stats(self):
            raise RuntimeError("boom")

    counters = observability_counters(logger=_Broken())
    assert "error" in counters["logger"], "отказ диагностируемого проглочен"
    assert "boom" in counters["logger"]["error"]

    # А вот отсутствие менеджера — не отказ: секции просто нет.
    assert observability_counters(logger=None, error=None, stats=None) == {}


# =============================================================================
# Пол ошибок (Ф0.9) — тот же класс невидимости
# =============================================================================


def test_errors_to_floor_reaches_get_stats(tmp_path: Path) -> None:
    """«Ошибка не дошла ни до одного канала» — спрашиваемый снаружи факт.

    До Ф0.3 счётчик жил только в ``self.stats`` и в get_stats() не попадал:
    сломанный маршрут ошибок нельзя было увидеть, не читая файлы на диске.
    """
    with _logger(tmp_path, max_pending=10_000) as manager:
        assert manager.get_stats()["errors_to_floor"] == 0
        assert manager.get_stats()["error_floor"] is None, "пол не должен создаваться заранее"

        manager.set_sink_enabled("system_file", False)  # приёмников не осталось
        manager.error("некуда писать", module="unit")

        stats = manager.get_stats()
        assert stats["errors_to_floor"] == 1
        assert stats["error_floor"]["written"] == 1
        assert stats["error_floor"]["path"].endswith("errors_floor.jsonl")


def test_error_floor_stays_silent_while_channel_is_alive(tmp_path: Path) -> None:
    """Обратная половина: живой канал → пол не трогается, счётчик ноль."""
    with _logger(tmp_path, max_pending=10_000) as manager:
        manager.error("канал жив", module="unit")

        stats = manager.get_stats()
        assert stats["errors_to_floor"] == 0
        assert stats["error_floor"] is None


# =============================================================================
# Регресс-страж имён
# =============================================================================


REQUIRED_BUFFER_KEYS: List[str] = [
    "dropped",
    "dropped_by_channel",
    "flush_failed",
    "flush_failed_by_channel",
    "in_flight_records",
    "max_pending",
    "overflow_policy",
    "pending",
    "urgent_flush_requests",
]


def test_published_key_names_are_pinned(tmp_path: Path) -> None:
    """Имена ключей — контракт с потребителем команды, а не деталь реализации.

    Переименование без правки этого списка = молча сломанный внешний
    потребитель (класс «дефолтный путь сверять с публикатором»).
    """
    with _logger(tmp_path, max_pending=10_000) as manager:
        buffer_stats = observability_counters(logger=manager)["logger"]["buffer"]
        missing = [k for k in REQUIRED_BUFFER_KEYS if k not in buffer_stats]
        assert not missing, f"ключи исчезли из публикации: {missing}"


def test_limit_is_operable_from_config(tmp_path: Path) -> None:
    """Потолок берётся из конфига, а не зашит константой.

    Иначе «ограничили буфер» означало бы «выбрали за оператора»: ни поднять под
    свою нагрузку, ни проверить срабатывание на живой системе было бы нельзя.
    """
    with _logger(tmp_path, max_pending=7) as manager:
        buffer_stats = manager.get_stats()["batch_stats"]
        assert buffer_stats["max_pending"] == 7
        assert buffer_stats["overflow_policy"] == "drop_oldest"


def test_config_typo_in_policy_fails_loudly() -> None:
    """Опечатка в политике — отказ на ГРАНИЦЕ конфига, а не посреди reconfigure.

    Валидация в конструкторе буфера ловила её слишком поздно: reconfigure к тому
    моменту уже остановил старый буфер и пересоздал каналы, и менеджер оставался
    с молча выключенным батчингом.
    """
    with pytest.raises(ValueError, match="overflow_policy"):
        LoggerManagerConfig(app_name="bad", batch_overflow_policy="drop_middle")
